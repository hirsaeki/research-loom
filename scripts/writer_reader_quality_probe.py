#!/usr/bin/env python3
"""Prepare and round-trip bounded SYNTHETIC_TEST_ONLY Writer inputs for #467.

This driver seeds a disposable virtual Research State, then uses only the public
LocalApplicationFacade for package/composition/export and manuscript operations.
It does not generate prose or call an LLM; wrap-response only packages supplied
prose and explicitly marks all delivered semantic rules unevaluated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FIXTURES = ROOT / "tests" / "runtime"
CASES_PATH = ROOT / "docs" / "acceptance" / "writer-reader-quality" / "cases.json"
WRITER_MANIFEST = ROOT / "profiles" / "narrative" / "misco" / "1.2.0" / "profile.json"
DRIVER_VERSION = "0.1.0"
PROJECT_PREFIX = "PRJ-WRQ"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(RUNTIME_FIXTURES) not in sys.path:
    sys.path.insert(0, str(RUNTIME_FIXTURES))

from runtime_fixtures import seed_state  # noqa: E402

from core.runtime import canonical_digest  # noqa: E402
from plugins.local_application import LocalApplicationFacade, LocalResearchApplication  # noqa: E402
from plugins.local_application.profile_resolution import resolve_effective_profile_set  # noqa: E402
from plugins.local_application.writer_round_trip_service import MAX_RESPONSE_BYTES  # noqa: E402


class _NoCapabilityResolver:
    def resolve(self, *_args, **_kwargs):
        return None


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _write_json(path: Path, value: Any, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "xb" if exclusive else "wb"
    with path.open(mode) as handle:
        handle.write(_json_bytes(value))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"
    return result.stdout.strip()


def _short_code(index: int) -> str:
    return ("DUP", "CONCEPT", "COMPARE")[index]


def _config_for(case: Mapping[str, Any], project_id: str, rq_id: str) -> dict[str, Any]:
    fixed = case["fixed_material"]
    forbidden = case.get("must_not_claim", [])
    config: dict[str, Any] = {
        "schema_version": "0.1.0",
        "config_version": "0.1.0",
        "project": {
            "project_id": project_id,
            "title": "SYNTHETIC_TEST_ONLY — Writer reader-quality acceptance",
            "objective": str(case["reader_decision_question"]),
        },
        "scope": {
            "in_scope": [str(case["title"]), "このケースに固定された架空材料のWriter表現"],
            "out_of_scope": [
                "実在組織・実研究への一般化",
                "Research Stateの実運用採択",
                "公開・提出判断",
            ],
        },
        "research_questions": {"references": [{"question_id": rq_id}], "seeds": []},
        "profile_requests": {
            "research": [],
            "organization": [],
            "narrative": [
                {"profile_id": "misco.writer", "profile_type": "narrative", "version": "1.2.0"}
            ],
            "publication": [],
        },
        "communication_brief": {
            "audience": [str(case["target_reader"])],
            "purpose": "固定された合成材料から、読者が限定された判断に必要な情報を得られる短稿を準備する。",
            "desired_decision": str(case["reader_decision_question"]),
            "core_message": str(fixed["approved_interpretation"]),
            "must_include": [str(fixed["method"]), "未解決点", "限定された提言"],
            "tone": "明確で、根拠の範囲を保つ",
        },
        "research_attention": [],
        "project_constraints": {
            "requirements": [],
            "prohibitions": [
                {
                    "guard_id": f"GUARD-{_short_code_from_project(project_id)}",
                    "statement": "合成試験材料を実研究の証拠、Human Decision、または公開可能な判断として扱わない。",
                }
            ],
            "must_not_claim": [
                {
                    "guard_id": f"NO-{_short_code_from_project(project_id)}-{i + 1}",
                    "statement": str(value),
                }
                for i, value in enumerate(forbidden)
            ],
        },
        "resource_references": [],
        "capability_hints": [],
        "provenance": {
            "source_reference_ids": [],
            "derived_from_configuration_digests": [],
            "notes": ["SYNTHETIC_TEST_ONLY; generated from the fixed #467 cases.json material."],
        },
    }
    config["configuration_digest"] = "sha256:" + hashlib.sha256(_json_canonical(config)).hexdigest()
    return config


def _json_canonical(value: Mapping[str, Any]) -> bytes:
    import rfc8785

    return rfc8785.dumps(value)


def _short_code_from_project(project_id: str) -> str:
    return project_id.removeprefix(f"{PROJECT_PREFIX}-")


def _fixture_decision(
    decision_id: str, project_id: str, subject_kind: str, subject_id: str
) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "id": decision_id,
        "kind": "decision",
        "revision": 0,
        "project_id": project_id,
        "decision_kind": "synthetic_fixture_adoption",
        "subjects": [{"kind": subject_kind, "id": subject_id}],
        "choice": "synthetic_acceptance_only",
        "actor_type": "system",
        "decided_by": "SYNTHETIC_TEST_FIXTURE",
        "decided_at": "2026-10-14T00:00:00Z",
    }


def _fact_statement(row: Mapping[str, Any]) -> str:
    if isinstance(row.get("statement"), str):
        return str(row["statement"])
    if "team" in row:
        return (
            f"{row.get('id', 'fact')}: チーム{row['team']}の{row['measure']}は、"
            f"導入前{row['baseline']}{row['unit']}、導入後{row['after']}{row['unit']}。"
            f"前後各期間{row['n_per_period']}件。"
        )
    raise ValueError(f"fixed fact has no supported representation: {row!r}")


def _case_state(
    case: Mapping[str, Any],
    project_id: str,
    code: str,
    config: Mapping[str, Any],
    eps: Mapping[str, Any],
    common_invariants: list[str],
):
    fixed = case["fixed_material"]
    rq_id, method_id, finding_id, argument_id, recommendation_id = (
        f"RQ-{code}",
        f"MTH-{code}",
        f"FND-{code}",
        f"ARG-{code}",
        f"REC-{code}",
    )
    question = {
        "schema_version": "0.1.0",
        "id": rq_id,
        "kind": "research_question",
        "revision": 1,
        "project_id": project_id,
        "text": str(case["reader_decision_question"]),
        "adoption_state": "approved",
        "decision_ids": [f"DEC-{code}-RQ"],
        "scope_limits": ["この架空ケースに記載された対象・期間・条件を超えて一般化しない。"],
    }
    method = {
        "schema_version": "0.1.0",
        "id": method_id,
        "kind": "method",
        "revision": 1,
        "project_id": project_id,
        "question_ids": [rq_id],
        "name": str(fixed["method"]),
        "protocol_ref": f"synthetic-fixture://writer-reader-quality/{case['case_id']}/method",
        "adoption_state": "approved",
        "decision_ids": [f"DEC-{code}-METHOD"],
        "limitations": ["この方法記述は架空の受入試験材料であり、実施記録ではない。"],
    }
    fact_lines = [_fact_statement(row) for row in fixed["facts"] if isinstance(row, Mapping)]
    finding = {
        "schema_version": "0.1.0",
        "id": finding_id,
        "kind": "finding",
        "revision": 1,
        "project_id": project_id,
        "question_ids": [rq_id],
        "statement": "\n".join(
            [f"背景: {fixed['context']}", f"方法: {fixed['method']}", "固定事実:", *fact_lines]
        ),
        "evidence_ids": [],
        "analysis_ids": [],
        "counter_evidence_ids": [],
        "boundary_conditions": [
            *map(str, case.get("semantic_invariants", [])),
            *map(str, common_invariants),
        ],
        "limitations": list(map(str, fixed.get("unresolved", []))),
        "adoption_state": "approved",
        "decision_ids": [f"DEC-{code}-FINDING"],
    }
    argument = {
        "schema_version": "0.1.0",
        "id": argument_id,
        "kind": "argument",
        "revision": 0,
        "project_id": project_id,
        "question_ids": [rq_id],
        "conclusion": str(fixed["approved_interpretation"]),
        "warrant": str(fixed["interpretation_warrant"]),
        "qualifier": "未解決点: " + "；".join(map(str, fixed.get("unresolved", []))),
        "finding_ids": [finding_id],
        "evidence_ids": [],
        "implications": [*map(str, fixed.get("unresolved", [])), str(fixed["selection_reason"])],
    }
    recommendation = {
        "schema_version": "0.1.0",
        "id": recommendation_id,
        "kind": "recommendation",
        "revision": 1,
        "project_id": project_id,
        "statement": str(fixed["approved_recommendation"]),
        "finding_ids": [finding_id],
        "conditions": list(map(str, fixed.get("unresolved", []))),
        "scope": ["限定された合成ケースの次の判断まで"],
        "adoption_state": "approved",
        "decision_ids": [f"DEC-{code}-RECOMMENDATION"],
    }
    objects = [
        {
            "schema_version": "0.1.0",
            "id": project_id,
            "kind": "project",
            "revision": 0,
            "title": "SYNTHETIC_TEST_ONLY — Writer reader-quality acceptance",
            "objective": str(case["reader_decision_question"]),
        },
        question,
        method,
        finding,
        argument,
        recommendation,
    ]
    decisions = [
        _fixture_decision(f"DEC-{code}-RQ", project_id, "research_question", rq_id),
        _fixture_decision(f"DEC-{code}-METHOD", project_id, "method", method_id),
        _fixture_decision(f"DEC-{code}-FINDING", project_id, "finding", finding_id),
        _fixture_decision(
            f"DEC-{code}-RECOMMENDATION", project_id, "recommendation", recommendation_id
        ),
    ]
    state = seed_state(
        objects=objects,
        decisions=decisions,
        mode="virtual",
        snapshot_id=f"SNP-WRQ-{code}",
        project_id=project_id,
        project_config=config,
    )
    config_digest = canonical_digest(config)
    eps_digest = canonical_digest(eps)
    lineage = replace(
        state.lineages[0],
        project_config_digest=config_digest,
        effective_profile_set_digest=eps_digest,
    )
    state = replace(
        state,
        project_config=config,
        project_config_digest=config_digest,
        effective_profile_set_digest=eps_digest,
        lineages=(lineage,),
    )
    return state, {
        "rq_id": rq_id,
        "method_id": method_id,
        "finding_id": finding_id,
        "argument_id": argument_id,
        "recommendation_id": recommendation_id,
    }


def _sections(case: Mapping[str, Any], refs: Mapping[str, str]) -> list[dict[str, Any]]:
    fixed = case["fixed_material"]
    section_ids = ["SEC-FRAMING", "SEC-METHOD", "SEC-RESULTS", "SEC-IMPLICATION"]
    shared = {
        "parent_section_id": None,
        "detailed": True,
        "evidence_refs": [],
        "source_refs": [],
        "counter_review_refs": [],
        "qualifier_refs": [],
        "limitation_refs": [],
        "contribution_refs": [],
        "exhibit_refs": [],
        "gap_refs": [],
        "material_refs": [],
        "citation_requirements": [],
        "citation_bindings": [],
        "exhibit_bindings": [],
        "prohibited_claims": list(map(str, case.get("must_not_claim", []))),
        "unresolved_items": list(map(str, fixed.get("unresolved", []))),
    }
    rows = [
        {
            "section_id": section_ids[0],
            "order": 1,
            "heading": "問いと判断の焦点",
            "reader_question": str(case["reader_decision_question"]),
            "purpose": "読者の判断課題と、この短稿で得られる答えを示す。",
            "narrative_stage_refs": ["framing"],
            "semantic_purpose_refs": ["frame_problem"],
            "messages": [str(case["title"]), str(case["target_reader"]), str(fixed["context"])],
            "opening_intent": "読者の判断課題から始める。",
            "closing_intent": "固定された方法を示す次節へつなぐ。",
            "previous_section_id": None,
            "next_section_id": section_ids[1],
            "argument_refs": [refs["argument_id"]],
            "finding_refs": [refs["finding_id"]],
            "recommendation_refs": [refs["recommendation_id"]],
        },
        {
            "section_id": section_ids[1],
            "order": 2,
            "heading": "方法と条件",
            "reader_question": "どの材料を、どの条件で確認したのか。",
            "purpose": "方法の性質と判断範囲を明確にする。",
            "narrative_stage_refs": ["formation"],
            "semantic_purpose_refs": ["expose_argument"],
            "messages": [str(fixed["context"]), str(fixed["method"])],
            "opening_intent": "必要な方法条件を説明する。",
            "closing_intent": "この条件から何が観察されたかへ進む。",
            "previous_section_id": section_ids[0],
            "next_section_id": section_ids[2],
            "argument_refs": [refs["argument_id"]],
            "finding_refs": [refs["finding_id"]],
            "recommendation_refs": [refs["recommendation_id"]],
        },
        {
            "section_id": section_ids[2],
            "order": 3,
            "heading": "観察された結果と限界",
            "reader_question": "固定された事実から何が言え、何はまだ言えないか。",
            "purpose": "結果、条件、未解決点を同時に保つ。",
            "narrative_stage_refs": ["validation"],
            "semantic_purpose_refs": ["test_and_qualify"],
            "messages": [
                str(fixed["context"]),
                str(fixed["method"]),
                *[_fact_statement(row) for row in fixed["facts"]],
            ],
            "opening_intent": "方法と結果の関係を示す。",
            "closing_intent": "入力済み解釈の範囲を保ったまま判断へ向かう。",
            "previous_section_id": section_ids[1],
            "next_section_id": section_ids[3],
            "argument_refs": [refs["argument_id"]],
            "finding_refs": [refs["finding_id"]],
            "recommendation_refs": [refs["recommendation_id"]],
        },
        {
            "section_id": section_ids[3],
            "order": 4,
            "heading": "判断と次の一手",
            "reader_question": "問いにどう答え、次に何を確かめるか。",
            "purpose": "提言を冒頭の判断課題と観察へ結びつける。",
            "narrative_stage_refs": ["implication"],
            "semantic_purpose_refs": ["present_implications"],
            "messages": [str(fixed["approved_recommendation"]), str(fixed["selection_reason"])],
            "opening_intent": "冒頭の問いへ戻る。",
            "closing_intent": "適用範囲と次の確認事項を明示して結ぶ。",
            "previous_section_id": section_ids[2],
            "next_section_id": None,
            "argument_refs": [refs["argument_id"]],
            "finding_refs": [refs["finding_id"]],
            "recommendation_refs": [refs["recommendation_id"]],
        },
    ]
    return [{**deepcopy(shared), **row} for row in rows]


def _new_facade(
    workspace: Path, eps: Mapping[str, Any], *, seed=None, project_id: str
) -> LocalApplicationFacade:
    workspace.mkdir(parents=True, exist_ok=True)
    eps_path = workspace / "effective-profile-set.json"
    if seed is not None:
        _write_json(workspace / "project-config.json", seed.project_config)
        _write_json(eps_path, eps)
    else:
        eps = _read_json(eps_path)
    digest = canonical_digest(eps)

    def profile_provider(_project_ref: str, expected_digest: str):
        if expected_digest != digest:
            return None
        value = deepcopy(dict(eps))
        value["content_digest"] = digest
        return value

    app = LocalResearchApplication(
        workspace / ".research-loom",
        resolver=_NoCapabilityResolver(),
        effective_profile_set_provider=profile_provider,
        seed_state=seed,
    )
    return LocalApplicationFacade(app, project_id, workspace_root=workspace, owns_application=True)


def _prepare_case(
    case: Mapping[str, Any],
    index: int,
    run_root: Path,
    profile_digest: str,
    eps: Mapping[str, Any],
    common_invariants: list[str],
) -> dict[str, Any]:
    code = _short_code(index)
    project_id = f"{PROJECT_PREFIX}-{code}"
    ids = {
        "rq_id": f"RQ-{code}",
        "method_id": f"MTH-{code}",
        "finding_id": f"FND-{code}",
        "argument_id": f"ARG-{code}",
        "recommendation_id": f"REC-{code}",
    }
    config = _config_for(case, project_id, ids["rq_id"])
    state, refs = _case_state(case, project_id, code, config, eps, common_invariants)
    case_root = run_root / "cases" / str(case["case_id"])
    workspace = case_root / "workspace"
    facade = _new_facade(workspace, eps, seed=state, project_id=project_id)
    try:
        package_result = facade.build_research_package(
            {
                "snapshot_id": str(state.current_snapshot["id"]),
                "rq_id": refs["rq_id"],
                "object_ids": [
                    refs["method_id"],
                    refs["finding_id"],
                    refs["argument_id"],
                    refs["recommendation_id"],
                ],
            }
        )
        package = package_result["package"]
        proposal = {
            "purpose": "固定された研究材料を使い、読者が限定された判断を行える短稿を組み立てる。",
            "audience": [str(case["target_reader"])],
            "sections": _sections(case, refs),
            "created_by": {
                "type": "human_or_external_llm",
                "instruction": "SYNTHETIC_TEST_ONLY acceptance fixture; no real-world research or editorial decision.",
            },
        }
        capture_result = facade.capture_writer_composition(package["package_id"], proposal)
        composition = capture_result["composition"]
        selection = facade.select_writer_composition(
            composition["composition_id"],
            int(composition["version"]),
            str(composition["composition_digest"]),
        )
        export_dir = run_root / "inputs" / str(case["case_id"])
        export_dir.parent.mkdir(parents=True, exist_ok=True)
        exported = facade.export_writer_round_trip_input(
            composition["composition_id"],
            ["SEC-FRAMING", "SEC-METHOD", "SEC-RESULTS", "SEC-IMPLICATION"],
            export_dir,
        )
        writer_input = _read_json(export_dir / "writer-input.json")
        source = writer_input.get("source", {})
        authority = writer_input.get("authority_boundary", {})
        if (
            source.get("source_epistemic_status") != package["source_epistemic_status"]
            or source.get("package_mode") != "preview"
            or source.get("preview_only") is not True
            or source.get("authoritative_research_freeze") is not False
            or source.get("release_eligible") is not False
            or any(
                authority.get(key) is not False
                for key in (
                    "research_state_mutation_performed",
                    "evidence_verification_performed",
                    "finding_adoption_performed",
                    "recommendation_adoption_performed",
                )
            )
        ):
            raise RuntimeError(
                "exported Writer input authority flags differ from the synthetic fixture boundary"
            )
        record = {
            "schema_version": "0.1.0",
            "record_type": "writer_reader_quality_prepare_receipt",
            "driver_version": DRIVER_VERSION,
            "prepared_at": _utc_now(),
            "head": _git_head(),
            "case_id": str(case["case_id"]),
            "authority": "SYNTHETIC_TEST_ONLY",
            "fixture_bootstrap": {
                "mechanism": "LocalResearchApplication(seed_state=..., mode=virtual)",
                "decision_records": "synthetic system fixture records only; no production Human Decision was requested or resolved",
                "sources_and_evidence": "omitted; no real or verified empirical sources are represented",
            },
            "profile": {
                "profile_id": "misco.writer",
                "profile_version": "1.2.0",
                "manifest_sha256": profile_digest,
            },
            "project_id": project_id,
            "workspace": str(workspace),
            "package": dict(package),
            "package_mode": source["package_mode"],
            "source_epistemic_status": source["source_epistemic_status"],
            "source_flags": {
                key: source[key]
                for key in (
                    "source_epistemic_status",
                    "package_mode",
                    "preview_only",
                    "authoritative_research_freeze",
                    "release_eligible",
                )
            },
            "input_authority_boundary": authority,
            "composition": {
                "composition_id": composition["composition_id"],
                "version": composition["version"],
                "digest": composition["composition_digest"],
                "validation": composition.get("validation"),
            },
            "selection": selection,
            "export": exported,
            "writer_input": {
                "path": str(export_dir / "writer-input.json"),
                "input_id": writer_input["input_id"],
                "input_digest": writer_input["input_digest"],
                "sha256": hashlib.sha256(
                    (export_dir / "writer-input.json").read_bytes()
                ).hexdigest(),
                "section_ids": [row["section_id"] for row in writer_input["sections"]],
            },
            "research_state_mutation_performed": False,
        }
        receipt_path = run_root / "receipts" / str(case["case_id"]) / "prepare.json"
        _write_json(receipt_path, record)
        return record
    finally:
        facade.close()


def _prepare(args: argparse.Namespace) -> int:
    run_root = Path(args.run_root).expanduser().resolve()
    if run_root.exists():
        raise SystemExit(f"run root already exists; preserving existing work: {run_root}")
    cases_doc = _read_json(CASES_PATH)
    if cases_doc.get("status") != "SYNTHETIC_TEST_ONLY":
        raise SystemExit("cases.json is not labeled SYNTHETIC_TEST_ONLY")
    if len(cases_doc.get("cases", [])) != 3:
        raise SystemExit("bounded driver expects exactly three fixed cases")
    manifest = _read_json(WRITER_MANIFEST)
    if (manifest.get("profile_id"), manifest.get("profile_version")) != ("misco.writer", "1.2.0"):
        raise SystemExit("the configured Writer manifest is not misco.writer@1.2.0")
    profile_digest = hashlib.sha256(WRITER_MANIFEST.read_bytes()).hexdigest()
    first_config = _config_for(
        cases_doc["cases"][0], f"{PROJECT_PREFIX}-{_short_code(0)}", f"RQ-{_short_code(0)}"
    )
    eps = resolve_effective_profile_set(first_config, [WRITER_MANIFEST])
    run_root.mkdir(parents=True, exist_ok=False)
    bootstrap = {
        "schema_version": "0.1.0",
        "record_type": "writer_reader_quality_bootstrap_manifest",
        "created_at": _utc_now(),
        "driver_version": DRIVER_VERSION,
        "authority": "SYNTHETIC_TEST_ONLY",
        "case_file": str(CASES_PATH),
        "case_file_sha256": hashlib.sha256(CASES_PATH.read_bytes()).hexdigest(),
        "repo_root": str(ROOT),
        "head": _git_head(),
        "profile": {
            "profile_id": "misco.writer",
            "profile_version": "1.2.0",
            "manifest_sha256": profile_digest,
        },
        "profile_set_digest": canonical_digest(eps),
        "llm_generation_performed": False,
        "production_human_decision_performed": False,
        "fixed_case_count": len(cases_doc["cases"]),
    }
    _write_json(run_root / "bootstrap-manifest.json", bootstrap)
    _write_json(run_root / "effective-profile-set.json", eps)
    receipts = []
    common_invariants = list(map(str, cases_doc.get("common_invariants", [])))
    for index, case in enumerate(cases_doc["cases"]):
        receipts.append(
            _prepare_case(case, index, run_root, profile_digest, eps, common_invariants)
        )
    _write_json(run_root / "prepare-index.json", {"status": "PREPARED", "cases": receipts})
    print(
        json.dumps(
            {
                "status": "PREPARED",
                "run_root": str(run_root),
                "cases": [
                    {
                        "case_id": row["case_id"],
                        "input_path": row["writer_input"]["path"],
                        "input_digest": row["writer_input"]["input_digest"],
                    }
                    for row in receipts
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _receipt(run_root: Path, case_id: str) -> dict[str, Any]:
    path = run_root / "receipts" / case_id / "prepare.json"
    if not path.is_file():
        raise SystemExit(f"prepared case receipt is missing: {path}")
    return _read_json(path)


def _open_case_facade(
    run_root: Path, case_id: str
) -> tuple[LocalApplicationFacade, dict[str, Any]]:
    record = _receipt(run_root, case_id)
    workspace = Path(record["workspace"])
    eps = _read_json(workspace / "effective-profile-set.json")
    facade = _new_facade(workspace, eps, seed=None, project_id=str(record["project_id"]))
    return facade, record


def _next_receipt_path(run_root: Path, case_id: str, stem: str) -> Path:
    directory = run_root / "receipts" / case_id
    directory.mkdir(parents=True, exist_ok=True)
    index = 1
    while True:
        candidate = directory / f"{stem}-{index:03d}.json"
        if not candidate.exists():
            return candidate
        index += 1


def _write_immutable_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(raw)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise SystemExit(
                f"immutable artifact path conflicts with existing bytes: {path}"
            ) from None


def _wrap_response(args: argparse.Namespace) -> int:
    run_root = Path(args.run_root).expanduser().resolve()
    case_id = str(args.case_id)
    prepared = _receipt(run_root, case_id)
    prose_source = Path(args.prose).expanduser().resolve(strict=True)
    prose_raw = prose_source.read_bytes()
    prose_digest = hashlib.sha256(prose_raw).hexdigest()
    prose = json.loads(prose_raw.decode("utf-8"))
    if (
        not isinstance(prose, Mapping)
        or set(prose) != {"sections"}
        or not isinstance(prose.get("sections"), list)
    ):
        raise SystemExit("prose JSON must contain only a sections array")
    input_path = Path(prepared["writer_input"]["path"])
    writer_input = _read_json(input_path)
    if writer_input.get("input_digest") != prepared["writer_input"]["input_digest"]:
        raise SystemExit("frozen Writer input digest does not match its prepare receipt")
    input_sections = {str(row["section_id"]): row for row in writer_input["sections"]}
    drafts = prose["sections"]
    if not drafts:
        raise SystemExit("prose response must contain at least one section")
    draft_ids: list[str] = []
    for row in drafts:
        if not isinstance(row, Mapping) or set(row) != {"section_id", "content"}:
            raise SystemExit("each prose section must contain only section_id and content")
        section_id, content = row.get("section_id"), row.get("content")
        if not isinstance(section_id, str) or section_id not in input_sections:
            raise SystemExit(
                f"prose response names a section outside the frozen input: {section_id!r}"
            )
        if not isinstance(content, str) or not content.strip():
            raise SystemExit(f"prose response content must be nonempty text: {section_id}")
        if section_id in draft_ids:
            raise SystemExit(f"duplicate prose section: {section_id}")
        draft_ids.append(section_id)

    base_ref: dict[str, Any] | None = None
    if args.base_revision_id:
        facade, _record = _open_case_facade(run_root, case_id)
        try:
            inspection = facade.inspect_writer_round_trip(
                str(prepared["composition"]["composition_id"]), str(args.base_revision_id)
            )
        finally:
            facade.close()
        revision = inspection.get("revision")
        if (
            not isinstance(revision, Mapping)
            or revision.get("revision_id") != args.base_revision_id
        ):
            raise SystemExit(
                "requested partial-revision base did not resolve through the public facade"
            )
        base_ref = {
            "revision_id": str(revision["revision_id"]),
            "revision_digest": str(revision["revision_digest"]),
        }
        base_sections = {str(row["section_id"]): row for row in revision.get("sections", [])}
        if all(
            str(row["content"])
            == str(base_sections.get(str(row["section_id"]), {}).get("content", ""))
            for row in drafts
        ):
            raise SystemExit("revision contains no prose change from its exact base")
    elif set(draft_ids) != set(input_sections) or len(draft_ids) != len(input_sections):
        raise SystemExit(
            "initial prose response must include every section in the frozen Writer input"
        )

    response_sections: list[dict[str, Any]] = []
    review_rationale = (
        "Transport wrapper did not semantically review prose; this outcome remains unevaluated."
    )
    for draft in drafts:
        section_id = str(draft["section_id"])
        section_scope = input_sections[section_id]
        section_input = section_scope["section_input"]
        contract = section_input["section_contract"]
        review_plan = section_input.get("writer_profile", {}).get("review_plan", [])
        profile_review = []
        for group in review_plan:
            rule_ids = [str(rule_id) for rule_id in group.get("rule_ids", [])]
            profile_review.append(
                {
                    "review_id": str(group["review_id"]),
                    "rule_ids": rule_ids,
                    "violated_rule_ids": [],
                    "outcome": "unevaluated",
                    "rationale": review_rationale,
                    "rule_results": [
                        {
                            "rule_id": rule_id,
                            "outcome": "unevaluated",
                            "applicability": "undetermined",
                            "method": "unevaluated",
                            "rationale": review_rationale,
                        }
                        for rule_id in rule_ids
                    ],
                }
            )
        response_sections.append(
            {
                "section_id": section_id,
                "content": str(draft["content"]),
                "citations": [
                    {
                        "source_ref": str(citation["source_ref"]),
                        "locator_ref": citation.get("locator_ref"),
                    }
                    for citation in contract.get("citation_requirements", [])
                ],
                "exhibit_refs": deepcopy(list(section_scope.get("exhibit_refs", []))),
                "profile_review": profile_review,
            }
        )

    response_seed = f"{case_id}\n{prose_digest}\n{base_ref or ''}".encode()
    response_id = "WR-" + hashlib.sha256(response_seed).hexdigest()[:20]
    response = {
        "schema_version": "0.1.0",
        "object_type": "writer_response",
        "response_id": response_id,
        "input_ref": {
            "input_id": writer_input["input_id"],
            "input_digest": writer_input["input_digest"],
        },
        "base_revision_ref": base_ref,
        "writer": {"writer_id": str(args.writer_id), "writer_version": str(args.writer_version)},
        "sections": response_sections,
        "feedback": [],
        "provenance": {
            "generated_at": _utc_now(),
            "channel": "synthetic-acceptance-transport-wrapper",
        },
    }
    response_raw = _json_bytes(response)
    response_digest = hashlib.sha256(response_raw).hexdigest()
    prose_path = run_root / "writer-prose" / case_id / f"{prose_digest}.json"
    response_path = run_root / "writer-responses" / case_id / f"{response_digest}.json"
    _write_immutable_bytes(prose_path, prose_raw)
    _write_immutable_bytes(response_path, response_raw)
    receipt = {
        "schema_version": "0.1.0",
        "record_type": "writer_transport_wrap_receipt",
        "wrapped_at": _utc_now(),
        "case_id": case_id,
        "writer_input_digest": writer_input["input_digest"],
        "prose_input_path": str(prose_path),
        "prose_input_sha256": prose_digest,
        "writer_response_path": str(response_path),
        "writer_response_sha256": response_digest,
        "response_id": response_id,
        "base_revision_ref": base_ref,
        "prose_content_modified": False,
        "semantic_review_performed": False,
        "profile_rule_outcomes": "all delivered rules marked unevaluated by the transport wrapper",
    }
    receipt_path = _next_receipt_path(run_root, case_id, f"wrap-{response_digest[:12]}")
    _write_json(receipt_path, receipt, exclusive=True)
    print(
        json.dumps(
            {"status": "WRAPPED", "receipt": str(receipt_path), **receipt},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _import_response(args: argparse.Namespace) -> int:
    run_root = Path(args.run_root).expanduser().resolve()
    source_path = Path(args.response).expanduser().resolve(strict=True)
    if source_path.stat().st_size > MAX_RESPONSE_BYTES:
        raise SystemExit("response file exceeds the supported size")
    with source_path.open("rb") as handle:
        raw = handle.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise SystemExit("response file exceeds the supported size")
    response_digest = hashlib.sha256(raw).hexdigest()
    response = json.loads(raw.decode("utf-8"))
    case_id = str(args.case_id)
    response_dir = run_root / "responses" / case_id
    response_path = response_dir / f"{response_digest}.json"
    response_dir.mkdir(parents=True, exist_ok=True)
    if response_path.exists():
        if response_path.read_bytes() != raw:
            raise SystemExit(
                f"response digest path conflicts with preserved bytes: {response_path}"
            )
    else:
        with response_path.open("xb") as handle:
            handle.write(raw)
    facade, prepared = _open_case_facade(run_root, case_id)
    try:
        try:
            result = facade.import_writer_response(response)
            status = str(result.get("status", "UNKNOWN"))
            record = {
                "schema_version": "0.1.0",
                "record_type": "writer_response_import_receipt",
                "operation": args.operation,
                "recorded_at": _utc_now(),
                "case_id": case_id,
                "response_path": str(response_path),
                "response_sha256": response_digest,
                "writer_input_digest": prepared["writer_input"]["input_digest"],
                "result": result,
            }
            output = _next_receipt_path(
                run_root,
                case_id,
                f"response-{response_digest[:12]}-{status.lower()}-{args.operation}",
            )
            _write_json(output, record, exclusive=True)
        except Exception as exc:
            record = {
                "schema_version": "0.1.0",
                "record_type": "writer_response_import_failure",
                "operation": args.operation,
                "recorded_at": _utc_now(),
                "case_id": case_id,
                "response_path": str(response_path),
                "response_sha256": response_digest,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "error_code": getattr(exc, "code", None),
            }
            output = _next_receipt_path(
                run_root, case_id, f"response-{response_digest[:12]}-failure"
            )
            _write_json(output, record, exclusive=True)
            print(
                json.dumps(
                    {"status": "FAILED", "receipt": str(output), **record},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        print(
            json.dumps(
                {"status": status, "receipt": str(output), **record}, ensure_ascii=False, indent=2
            )
        )
        return 0
    finally:
        facade.close()


def _inspect(args: argparse.Namespace) -> int:
    run_root = Path(args.run_root).expanduser().resolve()
    case_id = str(args.case_id)
    facade, prepared = _open_case_facade(run_root, case_id)
    try:
        result = facade.inspect_writer_round_trip(
            str(prepared["composition"]["composition_id"]), args.revision_id
        )
        record = {
            "schema_version": "0.1.0",
            "record_type": "writer_round_trip_inspection",
            "recorded_at": _utc_now(),
            "case_id": case_id,
            "revision_id": args.revision_id,
            "result": result,
        }
        path = _next_receipt_path(run_root, case_id, "inspection")
        _write_json(path, record, exclusive=True)
        print(
            json.dumps(
                {"status": "OK", "receipt": str(path), **record}, ensure_ascii=False, indent=2
            )
        )
        return 0
    finally:
        facade.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser(
        "prepare", help="seed virtual synthetic fixtures and export the three genuine Writer inputs"
    )
    prepare.add_argument("--run-root", required=True)
    prepare.set_defaults(handler=_prepare)
    wrap = sub.add_parser(
        "wrap-response",
        help="mechanically wrap prose-only JSON without changing or evaluating its prose",
    )
    wrap.add_argument("--run-root", required=True)
    wrap.add_argument("--case-id", required=True)
    wrap.add_argument(
        "--prose", required=True, help="JSON containing only sections[{section_id,content}]"
    )
    wrap.add_argument(
        "--base-revision-id", help="exact imported revision ID for a partial revision"
    )
    wrap.add_argument("--writer-id", default="external-writer")
    wrap.add_argument("--writer-version", default="unspecified")
    wrap.set_defaults(handler=_wrap_response)
    for name, operation in (("import-response", "import"), ("replay", "replay")):
        command = sub.add_parser(
            name,
            help="reopen the fixture workspace and import/replay an exact supplied response JSON",
        )
        command.add_argument("--run-root", required=True)
        command.add_argument("--case-id", required=True)
        command.add_argument(
            "--response",
            required=True,
            help="existing Writer response JSON; no output is generated by this driver",
        )
        command.set_defaults(handler=_import_response, operation=operation)
    inspect = sub.add_parser(
        "inspect", help="reopen a prepared workspace and inspect a stored manuscript revision"
    )
    inspect.add_argument("--run-root", required=True)
    inspect.add_argument("--case-id", required=True)
    inspect.add_argument("--revision-id")
    inspect.set_defaults(handler=_inspect)
    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
