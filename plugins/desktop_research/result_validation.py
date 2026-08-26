from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from jsonschema import Draft202012Validator, FormatChecker
import rfc8785
import yaml

from .attempts import UNSUCCESSFUL_OUTCOMES, operational_terminations, reconstruct_attempts

ROOT = Path(__file__).resolve().parents[2]
DR = ROOT / "core" / "packages" / "desktop-research"
_SCHEMA = json.loads((DR / "desktop-research-result-extension.schema.json").read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())
_SEMANTICS = yaml.safe_load((DR / "desktop-research-semantics.yaml").read_text(encoding="utf-8"))
_ERRORS = {str(item["id"]) for item in _SEMANTICS["errors"]}


def canonical_extension_digest(document: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(document)); payload.pop("extension_digest", None)
    return "sha256:" + hashlib.sha256(rfc8785.dumps(payload)).hexdigest()


def _utc(value: str) -> bool:
    try: parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError: return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def _exact(locator: str) -> bool:
    if not locator.strip(): return False
    if locator.startswith(("http://", "https://")):
        p = urlparse(locator)
        return bool((p.path and p.path != "/") or p.query or p.fragment)
    return True


def _add(codes: list[str], code: str) -> None:
    if code not in _ERRORS: raise RuntimeError(f"uncataloged Desktop Research error: {code}")
    if code not in codes: codes.append(code)


def _outputs(handoff: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    spec = {
        "observation": ("observations", "observation_id"),
        "source_capture": ("source_captures", "capture_id"),
        "evidence_candidate": ("evidence_candidates", "evidence_candidate_id"),
        "candidate_finding": ("candidate_findings", "candidate_finding_id"),
        "counterevidence": ("counterevidence", "counterevidence_id"),
        "conflict": ("conflicts", "conflict_id"),
        "unknown": ("unknowns", "unknown_id"),
        "evidence_gap": ("evidence_gaps", "gap_id"),
        "next_action": ("candidate_next_actions", "proposal_id"),
        "next_method": ("candidate_next_methods", "proposal_id"),
    }
    return {(kind, str(item[field])): item for kind,(coll,field) in spec.items() for item in handoff["outputs"][coll]}


class DesktopResearchResultValidator:
    """Production PR11 validation using trusted stored bytes and retrieval ledger."""

    def __init__(self, artifact_store, operational_store) -> None:
        self._artifacts = artifact_store
        self._operations = operational_store

    def validate(self, handoff, extension, context_pack, context_extension, *, run_id: str) -> tuple[str, ...]:
        codes: list[str] = []
        if extension is None:
            return ("DR-RESULT-BINDING-001",)
        if list(_VALIDATOR.iter_errors(extension)):
            return ("DR-RESULT-BINDING-001",)
        if extension["extension_digest"] != canonical_extension_digest(extension): _add(codes,"DR-RESULT-DIGEST-001")
        expected = {
            "handoff_id": handoff["handoff_id"], "handoff_digest": handoff["handoff_digest"],
            "invocation_id": handoff["invocation_id"], "run_id": handoff["run_id"],
            "context_pack_id": context_pack["context_pack_id"], "context_pack_digest": context_pack["context_pack_digest"],
            "capability_id": handoff["capability"]["capability_id"], "function_id": handoff["capability"]["function_id"],
        }
        if (extension["handoff_binding"] != expected or run_id != handoff["run_id"] or
            (handoff["capability"]["capability_id"],handoff["capability"]["capability_version"],handoff["capability"]["function_id"])
            != ("desktop-research","0.1.0","investigate") or
            context_extension["context_binding"]["context_pack_digest"] != context_pack["context_pack_digest"]):
            _add(codes,"DR-RESULT-BINDING-001")

        captures = {str(x["capture_id"]):x for x in handoff["outputs"]["source_captures"]}
        details = extension["source_capture_details"]
        if len({str(x["capture_id"]) for x in details}) != len(details) or {str(x["capture_id"]) for x in details} != set(captures):
            _add(codes,"DR-CAPTURE-PROVENANCE-001")
        detail_index = {str(x["capture_id"]):x for x in details}
        meta = {x.artifact_id:x for x in self._artifacts.artifacts_for(run_id)}
        texts: dict[str,str] = {}; original_bytes = text_bytes = 0; refs: set[str] = set()
        allowed = set(context_extension["allowed_source_categories"])
        for d in details:
            cid=str(d["capture_id"]); cap=captures.get(cid); bad=False
            if cap is None or d["source_category"] not in allowed or d["exact_locator"] != cap["locator"] or not _utc(str(d["acquired_at"])) or not _exact(str(d["exact_locator"])):
                bad=True
            if cap is not None and d["original_capture"]["content_digest"] != cap["content_digest"]: bad=True
            for key,role in (("original_capture","desktop_research.original_capture"),("text_rendition","desktop_research.text_rendition")):
                dec=d[key]; ref=str(dec["content_reference"]); refs.add(ref); m=meta.get(ref)
                if m is None or m.run_id != run_id or m.role != role or m.digest != dec["content_digest"] or m.media_type != dec["media_type"] or m.size != dec["byte_length"]:
                    bad=True; continue
                try: payload=self._artifacts.load_artifact(ref)
                except Exception: bad=True; continue
                if payload.digest != dec["content_digest"] or len(payload.content) != dec["byte_length"]: bad=True
                if key == "original_capture": original_bytes += len(payload.content)
                else:
                    text_bytes += len(payload.content)
                    try: text=payload.content.decode("utf-8")
                    except UnicodeDecodeError: text=""; bad=True
                    if payload.media_type != "text/plain" or (dec.get("inline_text") is not None and dec["inline_text"] != text): bad=True
                    texts[cid]=text
            if bad: _add(codes,"DR-CAPTURE-PROVENANCE-001")
        b=context_extension["budget"]
        if (len(details)>b["max_acquired_source_captures"] or len(extension["search_trace"]["entries"])>b["max_search_trace_entries"] or
            text_bytes>b["max_text_rendition_bytes"] or len(refs)>b.get("max_capture_artifacts",2*b["max_acquired_source_captures"]) or
            (b.get("max_original_capture_bytes") is not None and original_bytes>b["max_original_capture_bytes"])):
            _add(codes,"DR-CAPTURE-BUDGET-001")

        output_index=_outputs(handoff); all_ids={x for _,x in output_index}; required_citations=set()
        for kind,coll,field in (("evidence_candidate",handoff["outputs"]["evidence_candidates"],"evidence_candidate_id"),("counterevidence",handoff["outputs"]["counterevidence"],"counterevidence_id")):
            for x in coll:
                if x["source_basis"]["basis_type"] == "source_capture": required_citations.add((kind,str(x[field])))
        cited=set(); citation_ids=set()
        for c in extension["citation_details"]:
            if c["citation_id"] in citation_ids: _add(codes,"DR-CITATION-001")
            citation_ids.add(c["citation_id"]); key=(str(c["handoff_output_kind"]),str(c["handoff_output_id"])); out=output_index.get(key)
            cid=str(c["capture_id"]); d=detail_index.get(cid); text=texts.get(cid)
            if out is None or d is None or text is None or out["source_basis"] != {"basis_type":"source_capture","capture_id":cid} or c["text_rendition_digest"] != d["text_rendition"]["content_digest"] or out["locator"] != c["excerpt_locator"] or c["excerpt"] not in text:
                _add(codes,"DR-CITATION-001")
            cited.add(key)
        if not required_citations.issubset(cited) or ("DR-CAPTURE-PROVENANCE-001" in codes and extension["citation_details"]): _add(codes,"DR-CITATION-001")

        entries=extension["search_trace"]["entries"]; entry_index={str(x["trace_entry_id"]):x for x in entries}; dims={str(x["dimension_id"]) for x in context_extension["coverage_dimensions"]}
        if len(entry_index)!=len(entries): _add(codes,"DR-SEARCH-TRACE-001")
        for e in entries:
            if not set(e["coverage_dimension_ids"]).issubset(dims) or not set(e["related_handoff_output_ids"]).issubset(all_ids) or not set(e["source_capture_ids"]).issubset(captures): _add(codes,"DR-SEARCH-TRACE-001")
        try: attempts=reconstruct_attempts(self._operations,run_id)
        except Exception: attempts={}; _add(codes,"DR-SEARCH-TRACE-001")
        if set(attempts)!=set(entry_index) or any(x.get("completed_at") is None for x in attempts.values()): _add(codes,"DR-SEARCH-TRACE-001")
        for aid,a in attempts.items():
            e=entry_index.get(aid)
            if e is None: continue
            ec=[a["resulting_capture_id"]] if a["outcome"]=="source_captured" else []
            if e["strategy"]!=a["strategy"] or set(e["coverage_dimension_ids"])!=set(a["coverage_dimension_ids"]) or e["outcome"]!=a["outcome"] or list(e["source_capture_ids"])!=ec or (ec and ec[0] not in captures): _add(codes,"DR-SEARCH-TRACE-001")
        unsuccessful={aid for aid,a in attempts.items() if a.get("outcome") in UNSUCCESSFUL_OUTCOMES}
        if set(extension["search_trace"]["unsuccessful_entry_ids"]) != unsuccessful: _add(codes,"DR-SEARCH-TRACE-001")

        qids=set(context_pack["question_ids"]); null_ids=set()
        for n in extension["null_results"]:
            key=(str(n["handoff_projection"]["output_kind"]),str(n["handoff_projection"]["output_id"]))
            if n["null_id"] in null_ids or not set(n["question_ids"]).issubset(qids) or key not in output_index: _add(codes,"DR-NULL-001")
            null_ids.add(n["null_id"])
        if extension["null_results"] and not any(a.get("outcome")=="no_relevant_source" for a in attempts.values()): _add(codes,"DR-NULL-001")

        gaps={str(x["gap_id"]) for x in handoff["outputs"]["evidence_gaps"]}; ga=extension["evidence_gap_assessments"]
        if len({str(x["gap_id"]) for x in ga})!=len(ga) or {str(x["gap_id"]) for x in ga}!=gaps or any(not set(x["coverage_dimension_ids"]).issubset(dims) for x in ga): _add(codes,"DR-EVIDENCE-GAP-001")
        da=extension["coverage_assessment"]["dimensions"]; di={str(x["dimension_id"]):x for x in da}
        if len(di)!=len(da) or set(di)!=dims or any(not set(x["trace_entry_ids"]).issubset(entry_index) for x in da): _add(codes,"DR-COVERAGE-001")
        for dim,a in di.items():
            relevant=[x for x in attempts.values() if dim in x["coverage_dimension_ids"]]
            if a["status"]=="covered" and not any(x.get("outcome")=="source_captured" for x in relevant): _add(codes,"DR-COVERAGE-001")
        for a in attempts.values():
            if a.get("outcome") in {"blocked","unavailable","failed"}:
                related=entry_index.get(a["attempt_id"],{}).get("related_handoff_output_ids",[])
                visible=any(("unknown",str(x)) in output_index or ("evidence_gap",str(x)) in output_index for x in related)
                limited=any(di.get(dim,{}).get("status") in {"partial","uncovered"} for dim in a["coverage_dimension_ids"])
                if not (visible or limited): _add(codes,"DR-COVERAGE-001")

        stop=extension["coverage_assessment"]["stopping_recommendation"]; riv=extension["coverage_assessment"]["remaining_information_value"]["level"]
        if set(stop["basis"])=={"source_count"} or (stop["stop_recommended"] and operational_terminations(self._operations,run_id)): _add(codes,"DR-STOP-BASIS-001")
        if stop["stop_recommended"] and any(x["materiality"] in {"material","unknown"} for x in ga): _add(codes,"DR-STOP-GAP-001")
        if stop["stop_recommended"] and riv in {"high","unknown"}: _add(codes,"DR-STOP-RIV-001")
        methods={str(x["proposal_id"]) for x in handoff["outputs"]["candidate_next_methods"]}
        if set(extension["candidate_next_method_ids"])!=methods: _add(codes,"DR-NEXT-METHOD-001")
        return tuple(codes)
