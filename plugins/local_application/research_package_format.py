from __future__ import annotations
from copy import deepcopy
import hashlib, json
from pathlib import Path
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

def safe_component(v:str,field:str)->str:
    if not v or v in {".",".."} or "/" in v or "\\" in v: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INPUT-001",f"{field} is not a safe identifier")
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

def verify_export_root(root:str|Path,*,verify_package_digest:bool=True)->Mapping[str,Any]:
    try: base=Path(root).expanduser().resolve(strict=True)
    except OSError as exc: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001","export root does not exist") from exc
    try: package=json.loads((base/"research-package.json").read_text(encoding="utf-8"))
    except (OSError,UnicodeError,json.JSONDecodeError) as exc: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001","invalid research-package.json") from exc
    if not isinstance(package,Mapping): raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001","research-package.json must be an object")
    validate_schema(package)
    if verify_package_digest and package.get("package_digest")!=digest_json(without_digest(package)): raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001","Research Package digest mismatch")
    total=(base/"research-package.json").stat().st_size; seen=set()
    for a in package.get("attachments",[]):
        rel=str(a["path"]); p=Path(rel)
        if p.is_absolute() or ".." in p.parts or rel in seen: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001","unsafe or duplicate attachment path")
        seen.add(rel); path=(base/p).resolve(strict=False)
        if not path.is_relative_to(base): raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001","attachment escapes export root")
        try:data=path.read_bytes()
        except OSError as exc: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",f"missing attachment: {rel}") from exc
        if len(data)!=int(a["byte_length"]) or digest_bytes(data)!=a["content_digest"]: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",f"attachment digest/size mismatch: {rel}")
        total+=len(data)
    try: md=(base/"research-package.md").read_bytes()
    except OSError as exc: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001","missing Research Package Markdown") from exc
    proj=package.get("projections",{}).get("markdown",{})
    if proj.get("path")!="research-package.md" or int(proj.get("byte_length",-1))!=len(md) or proj.get("content_digest")!=digest_bytes(md): raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001","Research Package Markdown integrity mismatch")
    total+=len(md)
    if total>MAX_OUTPUT_BYTES: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-BOUND-001","Research Package export exceeds output bound")
    return {"status":"VERIFIED","package_id":package["package_id"],"package_digest":package["package_digest"],"attachment_count":len(package.get("attachments",[])),"total_verified_bytes":total}
