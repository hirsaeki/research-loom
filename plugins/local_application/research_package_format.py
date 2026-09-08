from __future__ import annotations
from copy import deepcopy
import hashlib, json
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping
from jsonschema import Draft202012Validator, FormatChecker
import rfc8785
from .facade import LocalApplicationError

SCHEMA_VERSION="0.2.0"; TOOL_VERSION="0.2.0"
MAX_OBJECTS=64; MAX_RUNS=16; MAX_EXHIBITS=32; MAX_INPUTS=32; MAX_MATERIALS=32; MAX_PACKAGES=100
MAX_ITEM_BYTES=1024*1024; MAX_TEXT_BYTES=4*1024*1024; MAX_OUTPUT_BYTES=16*1024*1024
ALLOWED={"snapshot_id","snapshot_digest","lineage_ref","project_config_digest","effective_profile_set_digest","rq_id","object_ids","run_ids","exhibit_ids","project_input_ids","materials","gap_ids"}
ROOT=Path(__file__).resolve().parents[2]
SCHEMA=ROOT/"core/packages/writer-publication/research-package.schema.json"
NARRATIVE=ROOT/"profiles/contracts/narrative-semantics.yaml"

REQUIRED_NARRATIVE_PATHS={
    "narrative.stages.definitions",
    "narrative.dependencies.required",
    "narrative.section_purposes.definitions",
    "narrative.preservation.required_content",
    "narrative.connections.preserve",
}

def require_resolved_narrative(constraints:list[Mapping[str,Any]])->None:
    present={str(item.get("path")) for item in constraints}
    missing=sorted(REQUIRED_NARRATIVE_PATHS-present)
    if missing:
        raise LocalApplicationError(
            "APPLICATION-RESEARCH-PACKAGE-PROFILE-001",
            "resolved Narrative definitions are incomplete: "+", ".join(missing),
        )

def project_must_not_claim(config:Mapping[str,Any])->list[str]:
    rows=config.get("project_constraints",{}).get("must_not_claim",[])
    result=[]
    for row in rows:
        if isinstance(row,Mapping) and isinstance(row.get("statement"),str): result.append(str(row["statement"]))
        elif isinstance(row,str): result.append(row)
    return list(dict.fromkeys(result))

def digest_bytes(v:bytes)->str: return "sha256:"+hashlib.sha256(v).hexdigest()
def digest_json(v:Mapping[str,Any])->str: return "sha256:"+hashlib.sha256(rfc8785.dumps(dict(v))).hexdigest()
def without_digest(p:Mapping[str,Any])->dict[str,Any]:
    x=deepcopy(dict(p)); x.pop("package_digest",None); return x

def validate_schema(v:Mapping[str,Any])->None:
    schema=json.loads(SCHEMA.read_text(encoding="utf-8")); errors=sorted(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(v),key=lambda e:tuple(map(str,e.absolute_path)))
    if errors:
        e=errors[0]; where=".".join(map(str,e.absolute_path)) or "$"
        raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-SCHEMA-001",f"Research Package schema violation at {where}: {e.message}")

def _package_required_refs(obj:Mapping[str,Any])->list[tuple[str,str]]:
    kind=str(obj.get("kind","")); refs=[]
    def add(k,values):
        if isinstance(values,str) and values: refs.append((k,values))
        elif isinstance(values,list): refs.extend((k,str(v)) for v in values if isinstance(v,str) and v)
    if kind=="claim": add("evidence",obj.get("supporting_evidence_ids")); add("evidence",obj.get("challenging_evidence_ids"))
    elif kind=="evidence": add("source",obj.get("source_id"))
    elif kind=="analysis": add("evidence",obj.get("evidence_ids"))
    elif kind=="finding": add("evidence",obj.get("evidence_ids")); add("analysis",obj.get("analysis_ids")); add("evidence",obj.get("counter_evidence_ids"))
    elif kind=="counter_review":
        target=obj.get("target")
        if isinstance(target,Mapping) and target.get("kind") not in {None,"research_question"} and isinstance(target.get("id"),str): refs.append((str(target["kind"]),str(target["id"])))
        add("evidence",obj.get("evidence_ids"))
    elif kind=="argument": add("claim",obj.get("conclusion_claim_id")); add("claim",obj.get("premise_claim_ids")); add("finding",obj.get("finding_ids")); add("evidence",obj.get("evidence_ids")); add("counter_review",obj.get("counter_review_ids"))
    elif kind in {"contribution","recommendation"}: add("finding",obj.get("finding_ids"))
    return refs

def validate_resolved_references(package:Mapping[str,Any])->None:
    resolved=package.get("resolved_content",{})
    if not isinstance(resolved,Mapping):
        raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-REFERENCE-001","Research Package resolved content is invalid")
    objects=resolved.get("research_objects",[])
    if not isinstance(objects,list):
        raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-REFERENCE-001","Research Package research objects are invalid")
    by_id={str(obj.get("id")):obj for obj in objects if isinstance(obj,Mapping) and isinstance(obj.get("id"),str)}
    missing=[]
    for obj in objects:
        if not isinstance(obj,Mapping):
            missing.append("resolved_content.research_objects")
            continue
        for expected,ref_id in _package_required_refs(obj):
            target=by_id.get(ref_id)
            if target is None or str(target.get("kind"))!=expected: missing.append(f"{obj.get('id')}->{expected}:{ref_id}")
    content=package.get("content",{})
    if not isinstance(content,Mapping):
        raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-REFERENCE-001","Research Package content references are invalid")
    ref_kinds={
        "research_question_refs":"research_question",
        "finding_refs":"finding",
        "argument_refs":"argument",
        "contribution_refs":"contribution",
        "evidence_refs":"evidence",
        "counter_review_refs":"counter_review",
    }
    for field,expected_kind in ref_kinds.items():
        declared={str(ref_id) for ref_id in content.get(field,[]) or [] if isinstance(ref_id,str)}
        actual={oid for oid,obj in by_id.items() if obj.get("kind")==expected_kind}
        if declared!=actual: missing.append(f"content.{field}")
    source_refs=content.get("source_refs",[]) or []
    declared_sources={str(ref.get("source_id")) for ref in source_refs if isinstance(ref,Mapping) and isinstance(ref.get("source_id"),str)}
    actual_sources={oid for oid,obj in by_id.items() if obj.get("kind")=="source"}
    if len(declared_sources)!=len(source_refs) or declared_sources!=actual_sources: missing.append("content.source_refs")
    manifest={str(a.get("path")):a for a in package.get("attachments",[]) if isinstance(a,Mapping) and isinstance(a.get("path"),str)}
    def require_attachment(ref: Any, *, digest: Any = None, size: Any = None, label: str) -> None:
        if not isinstance(ref,str) or ref not in manifest:
            missing.append(label)
            return
        entry=manifest[ref]
        if digest is not None and entry.get("content_digest") != digest:
            missing.append(label)
        entry_size=entry.get("byte_length")
        if size is not None and (
            isinstance(size,bool) or not isinstance(size,int)
            or isinstance(entry_size,bool) or not isinstance(entry_size,int)
            or entry_size != size
        ):
            missing.append(label)

    material_rows=resolved.get("materials",[])
    if not isinstance(material_rows,list):
        missing.append("resolved_content.materials")
        material_rows=[]
    materials=set()
    source_material_ids=set()
    for material in material_rows:
        if not isinstance(material,Mapping):
            missing.append("resolved_content.materials")
            continue
        capture=material.get("capture")
        if not isinstance(capture,Mapping):
            missing.append("material.capture")
            continue
        run_id=str(material.get("run_id"))
        capture_id=str(capture.get("capture_id"))
        materials.add((run_id,capture_id))
        source_id=material.get("source_id")
        if isinstance(source_id,str):
            source_material_ids.add(source_id)
            source=by_id.get(source_id)
            original=capture.get("original",{})
            if not isinstance(original,Mapping): original={}
            if (
                source is None
                or source.get("kind") != "source"
                or str(source.get("canonical_locator", "")) != str(capture.get("source_locator", ""))
                or str(source.get("content_digest", "")) != str(original.get("digest", ""))
            ):
                missing.append(f"material.source_id:{source_id}")
        text=material.get("text_rendition")
        label=f"material:{run_id}:{capture_id}"
        if not isinstance(text,Mapping):
            missing.append(label)
        else:
            require_attachment(text.get("attachment_path"),digest=text.get("content_digest"),size=text.get("byte_length"),label=label)
    if actual_sources-source_material_ids:
        missing.append("resolved_content.materials.source_id")

    working=resolved.get("working_material",{})
    if not isinstance(working,Mapping):
        missing.append("resolved_content.working_material")
        working={}
    project_inputs=working.get("project_inputs",[])
    if not isinstance(project_inputs,list):
        missing.append("working_material.project_inputs")
        project_inputs=[]
    for project_input in project_inputs:
        content_row=project_input.get("content") if isinstance(project_input,Mapping) else None
        if not isinstance(content_row,Mapping):
            missing.append("project_input.attachment_path")
        else:
            require_attachment(content_row.get("attachment_path"),digest=content_row.get("content_digest"),size=content_row.get("byte_length"),label="project_input.attachment_path")
    narrative=package.get("resolved_profiles",{}).get("narrative_semantics",{}) if isinstance(package.get("resolved_profiles",{}),Mapping) else {}
    if isinstance(narrative,Mapping):
        require_attachment(narrative.get("contract_path"),digest=narrative.get("content_digest"),size=narrative.get("byte_length"),label="resolved_profiles.narrative_semantics.contract_path")
    else:
        missing.append("resolved_profiles.narrative_semantics.contract_path")
    run_candidates=working.get("run_candidates",[])
    if not isinstance(run_candidates,list):
        missing.append("working_material.run_candidates")
        run_candidates=[]
    for run in run_candidates:
        if not isinstance(run,Mapping):
            missing.append("working_material.run_candidates")
            continue
        handoff=run.get("handoff")
        outputs=handoff.get("outputs",{}) if isinstance(handoff,Mapping) else {}
        captures=outputs.get("source_captures",[]) if isinstance(outputs,Mapping) else []
        if not isinstance(captures,list):
            missing.append(f"{run.get('run_id')}->source_captures")
            continue
        for capture in captures:
            cid=capture.get("capture_id") if isinstance(capture,Mapping) else None
            if isinstance(cid,str) and (str(run.get("run_id")),cid) not in materials: missing.append(f"{run.get('run_id')}->capture:{cid}")
    if missing: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-REFERENCE-001","Research Package has unresolved required references: "+", ".join(sorted(set(missing))))

def safe_component(v:str,field:str)->str:
    windows=PureWindowsPath(v)
    if not v or v in {".",".."} or "/" in v or "\\" in v or ":" in v or windows.drive or windows.root: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INPUT-001",f"{field} is not a safe identifier")
    return v

def str_list(v:Any,field:str,maximum:int)->list[str]:
    if v is None:return []
    if not isinstance(v,list) or any(not isinstance(x,str) or not x for x in v): raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INPUT-001",f"{field} must be an array of non-empty strings")
    if len(v)!=len(set(v)): raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INPUT-001",f"{field} contains duplicates")
    if len(v)>maximum: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-BOUND-001",f"{field} exceeds bound {maximum}")
    return list(v)

def profile_pins(eps:Mapping[str,Any])->list[dict[str,Any]]:
    return [{"profile_type":str(x["profile_type"]),"profile_id":str(x["profile_id"]),"profile_version":str(x["profile_version"]),"content_digest":"sha256:"+str(x["manifest_sha256"])} for x in eps.get("effective_profiles",[])]

def brief(config:Mapping[str,Any],override:Mapping[str,Any]|None)->dict[str,Any]:
    src=deepcopy(dict(override)) if override is not None else deepcopy(dict(config.get("communication_brief",{}))); audience=src.get("audience") or []; message=src.get("core_message") or src.get("purpose")
    if not isinstance(audience,list) or not audience or any(not isinstance(x,str) or not x for x in audience): raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INPUT-001","Communication Brief audience is required")
    if not isinstance(message,str) or not message: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INPUT-001","Communication Brief core_message is required")
    mi=src.get("must_include") or []; mn=src.get("must_not_claim") or []
    if any(not isinstance(x,str) for x in mi+mn): raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INPUT-001","Communication Brief lists must contain strings")
    return {"audience":list(dict.fromkeys(audience)),"core_message":message,"must_include":list(dict.fromkeys(mi)),"must_not_claim":list(dict.fromkeys(mn))}

def narrative_refs(constraints:list[Mapping[str,Any]])->dict[str,Any]:
    stages=[]; purposes=[]; preserve=[]; edges=[]
    for item in constraints:
        path,value=item.get("path"),item.get("value")
        if path in {"narrative.semantic_stages","narrative.stages.definitions"} and isinstance(value,list):
            for x in value:
                if isinstance(x,str): stages.append(x)
                elif isinstance(x,Mapping) and isinstance(x.get("id"),str): stages.append(x["id"])
        elif path=="narrative.section_purposes.definitions" and isinstance(value,list): purposes += [str(x["id"]) for x in value if isinstance(x,Mapping) and isinstance(x.get("id"),str)]
        elif path in {"narrative.preservation.required_content","narrative.connections.preserve"} and isinstance(value,list): preserve += [x for x in value if isinstance(x,str)]
        elif path=="narrative.dependencies.required" and isinstance(value,list):
            for x in value:
                if isinstance(x,Mapping) and all(isinstance(x.get(k),str) for k in ("from_stage","to_stage","relation")): edges.append({k:str(x[k]) for k in ("from_stage","to_stage","relation")})
    return {"stage_refs":list(dict.fromkeys(stages)),"section_purpose_refs":list(dict.fromkeys(purposes)),"required_preservation_refs":list(dict.fromkeys(preserve)),"partial_order_edges":edges}


def _bounded_file_digest(path:Path,maximum:int)->tuple[int,str]:
    try:
        size=path.stat().st_size
    except OSError as exc:
        raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",f"missing file: {path.name}") from exc
    if size>maximum:
        raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-BOUND-001","Research Package export exceeds output bound")
    digest=hashlib.sha256()
    read=0
    try:
        with path.open("rb") as handle:
            while True:
                chunk=handle.read(min(64*1024,maximum-read+1))
                if not chunk: break
                read+=len(chunk)
                if read>maximum:
                    raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-BOUND-001","Research Package export exceeds output bound")
                digest.update(chunk)
    except LocalApplicationError:
        raise
    except OSError as exc:
        raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",f"unreadable file: {path.name}") from exc
    if read!=size:
        raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",f"file changed while verifying: {path.name}")
    return size,"sha256:"+digest.hexdigest()

def verify_export_root(root:str|Path)->Mapping[str,Any]:
    try: base=Path(root).expanduser().resolve(strict=True)
    except OSError as exc: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001","export root does not exist") from exc
    package_path=base/"research-package.json"
    try:
        package_size=package_path.stat().st_size
    except OSError as exc:
        raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001","invalid research-package.json") from exc
    if package_size>MAX_OUTPUT_BYTES: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-BOUND-001","Research Package export exceeds output bound")
    try:
        with package_path.open("rb") as handle:
            package_raw=handle.read(MAX_OUTPUT_BYTES+1)
        if len(package_raw)>MAX_OUTPUT_BYTES: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-BOUND-001","Research Package export exceeds output bound")
        if len(package_raw)!=package_size: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001","research-package.json changed while verifying")
        package=json.loads(package_raw.decode("utf-8"))
    except LocalApplicationError: raise
    except (OSError,UnicodeError,json.JSONDecodeError) as exc: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001","invalid research-package.json") from exc
    if not isinstance(package,Mapping): raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001","research-package.json must be an object")
    validate_schema(package)
    validate_resolved_references(package)
    if package.get("package_digest")!=digest_json(without_digest(package)): raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001","Research Package digest mismatch")
    total=package_size; seen=set()
    for a in package.get("attachments",[]):
        rel=str(a["path"]); p=Path(rel)
        if p.is_absolute() or ".." in p.parts or rel in seen: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001","unsafe or duplicate attachment path")
        seen.add(rel); path=(base/p).resolve(strict=False)
        if not path.is_relative_to(base): raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001","attachment escapes export root")
        try: size=path.stat().st_size
        except OSError as exc: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",f"missing attachment: {rel}") from exc
        if total+size>MAX_OUTPUT_BYTES: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-BOUND-001","Research Package export exceeds output bound")
        if size!=int(a["byte_length"]): raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",f"attachment digest/size mismatch: {rel}")
        _,digest=_bounded_file_digest(path,MAX_OUTPUT_BYTES-total)
        if digest!=a["content_digest"]: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",f"attachment digest/size mismatch: {rel}")
        total+=size
    md_path=base/"research-package.md"
    try: md_size=md_path.stat().st_size
    except OSError as exc: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001","missing Research Package Markdown") from exc
    if total+md_size>MAX_OUTPUT_BYTES: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-BOUND-001","Research Package export exceeds output bound")
    _,md_digest=_bounded_file_digest(md_path,MAX_OUTPUT_BYTES-total)
    proj=package.get("projections",{}).get("markdown",{})
    if proj.get("path")!="research-package.md" or int(proj.get("byte_length",-1))!=md_size or proj.get("content_digest")!=md_digest: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001","Research Package Markdown integrity mismatch")
    total+=md_size
    return {"status":"VERIFIED","package_id":package["package_id"],"package_digest":package["package_digest"],"attachment_count":len(package.get("attachments",[])),"total_verified_bytes":total}
