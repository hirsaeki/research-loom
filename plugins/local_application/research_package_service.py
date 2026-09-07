from __future__ import annotations
from copy import deepcopy
import json, os, shutil, tempfile
from pathlib import Path
from typing import Any, Mapping
from core.runtime import canonical_digest as core_canonical_digest
from plugins.local_execution_store import canonical_handoff_for
from .facade import LocalApplicationError
from .research_package_builder import build_package
from .research_package_format import MAX_OUTPUT_BYTES, MAX_PACKAGES, safe_component, verify_export_root

class ResearchPackageService:
    def __init__(self,facade)->None:
        self.facade=facade; self.app=facade._application; self.project_id=facade._project_id; self.workspace=facade._workspace_root
        if self.workspace is None: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-001","opened workspace is required")
        self.root=self.workspace/".research-loom"/"research-packages"
    def _state(self):
        repo=self.app.state_repository; lineage=repo.load_active_lineage_ref(self.project_id); return repo.load_state_view(self.project_id,lineage)
    def _snapshot(self,snapshot_id,state)->Mapping[str,Any]:
        repo=self.app.state_repository; current=state.current_snapshot; seen=set()
        while current is not None:
            cid=str(current.get("id"))
            if cid in seen: break
            seen.add(cid)
            if cid==snapshot_id:
                if str(current.get("project_id",self.project_id))==self.project_id:return current
                break
            prior=current.get("prior_snapshot_id")
            if not isinstance(prior,str) or not prior: break
            current=repo.load_snapshot(prior)
        raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-BINDING-001","selected Snapshot is not in active project lineage")
    def _objects(self,snapshot,object_ids:set[str])->dict[str,Mapping[str,Any]]:
        out={}; repo=self.app.state_repository
        members=[member for member in snapshot.get("members",[]) if str(member.get("id")) in object_ids]
        for member in members:
            obj=repo.load_object_revision(str(member["kind"]),str(member["id"]),int(member["revision"]))
            if obj is None: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",f"missing Snapshot member: {member['id']}")
            if core_canonical_digest(obj)!=str(member["digest"]): raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",f"Snapshot member digest mismatch: {member['id']}")
            out[str(member["id"])]=deepcopy(dict(obj))
        return out
    def _handoff(self,run):
        if not run.handoff_ref:return None
        h=canonical_handoff_for(self.app.execution_store,str(run.handoff_ref))
        if h is None: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",f"missing persisted Handoff for {run.run_id}")
        if h.get("handoff_digest")!=run.handoff_digest: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",f"Run/Handoff digest mismatch: {run.run_id}")
        return h
    def build(self,value:Mapping[str,Any])->Mapping[str,Any]: return build_package(self,value)
    def _markdown(self,p:Mapping[str,Any])->str:
        rc=p["resolved_content"]; rq=next(o for o in rc["research_objects"] if o.get("id") in p["content"]["research_question_refs"])
        lines=[f"# Research Package {p['package_id']}","","## Research Question","",str(rq.get("text") or rq.get("question") or rq.get("statement") or rq["id"]),"","## Communication Brief","",str(p["communication_brief"]["core_message"]),"","## Resolved Profile Constraints",""]
        lines += [f"- `{x.get('path')}`: `{json.dumps(x.get('value'),ensure_ascii=False,sort_keys=True)}`" for x in p["resolved_profiles"]["effective_constraints"]]
        lines += ["","Canonical Narrative semantics: `attachments/profile/narrative-semantics.yaml`","","## Research Objects",""]
        for o in rc["research_objects"]: lines += [f"### {o.get('kind')} `{o.get('id')}`","","```json",json.dumps(o,ensure_ascii=False,sort_keys=True,indent=2),"```",""]
        lines += ["## Working Material",""]
        for x in rc["working_material"]["research_exhibits"]: lines.append(f"- Exhibit `{x.get('exhibit_id')}`: {x.get('title','')}")
        for r in rc["working_material"]["run_candidates"]: lines.append(f"- Candidate Run `{r['run_id']}` captured against `{r['historical_binding']['snapshot_id']}`; candidate-only")
        lines += ["","## Evidence Materials",""]
        for m in rc["materials"]:
            c=m["capture"]; loc=(c.get("source_locators") or [c.get("source_locator")])[0]
            lines.append(f"- `{c.get('capture_id')}` — locator: {loc}; text: `{m['text_rendition']['attachment_path']}`")
        lines += ["","## Unresolved Gaps",""]
        lines += [f"- `{g.get('gap_id')}`: {g.get('statement',g.get('description','unresolved'))}" for g in rc["unresolved_gaps"]] or ["- None selected."]
        lines += ["","## Authority Boundary","","This is a read-only in-progress material package. It does not verify Evidence, adopt Findings or Recommendations, freeze Research State, or make a Publication release eligible.",""]
        return "\n".join(lines)
    def _persist(self,p,md,attachments):
        self.root.mkdir(parents=True,exist_ok=True); pid=safe_component(str(p["package_id"]),"package_id"); target=self.root/pid
        if target.exists(): raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-IMMUTABLE-001","Research Package ID already exists")
        tmp=Path(tempfile.mkdtemp(prefix=".rp-",dir=self.root))
        try:
            (tmp/"research-package.json").write_text(json.dumps(p,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8"); (tmp/"research-package.md").write_bytes(md)
            for rel,data,_,_ in attachments:
                q=tmp/rel; q.parent.mkdir(parents=True,exist_ok=True); q.write_bytes(data)
            verify_export_root(tmp); os.replace(tmp,target)
        except OSError as exc:
            shutil.rmtree(tmp,ignore_errors=True)
            raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-WRITE-001","Research Package persistence failed") from exc
        except Exception:
            shutil.rmtree(tmp,ignore_errors=True)
            raise
    def _load(self,pid):
        pid=safe_component(pid,"package_id"); root=self.root/pid
        if not root.is_dir(): raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-404","Research Package does not exist")
        verify_export_root(root); return json.loads((root/"research-package.json").read_text(encoding="utf-8"))
    def list(self):
        if not self.root.exists(): return {"status":"OK","project_id":self.project_id,"packages":[],"truncated":False}
        roots=[x for x in sorted(self.root.iterdir()) if x.is_dir() and not x.name.startswith(".rp-")]
        selected=roots[:MAX_PACKAGES]
        packages=[]
        for root in selected:
            path=root/"research-package.json"
            try:
                if path.stat().st_size>MAX_OUTPUT_BYTES: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-BOUND-001","Research Package metadata exceeds output bound")
                value=json.loads(path.read_text(encoding="utf-8"))
            except LocalApplicationError:
                raise
            except (OSError,UnicodeError,json.JSONDecodeError) as exc:
                raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",f"invalid saved Research Package metadata: {root.name}") from exc
            if not isinstance(value,Mapping): raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",f"invalid saved Research Package metadata: {root.name}")
            packages.append(self._summary(value))
        return {"status":"OK","project_id":self.project_id,"packages":packages,"truncated":len(roots)>MAX_PACKAGES}
    def show(self,pid): return {"status":"OK","package":self._load(pid)}
    def export(self,pid,output_dir):
        p=self._load(pid); raw=Path(output_dir).expanduser(); out=raw if raw.is_absolute() else Path.cwd()/raw
        if out.exists(): raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-EXPORT-001","Research Package export will not overwrite an existing path")
        try: parent=out.parent.resolve(strict=True)
        except OSError as exc: raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-EXPORT-001","export parent must exist") from exc
        managed=(self.workspace/".research-loom").resolve(strict=False); out=parent/out.name
        if out.resolve(strict=False).is_relative_to(managed): raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-EXPORT-001","export may not write inside managed workspace state")
        temp=Path(tempfile.mkdtemp(prefix=".rp-export-",dir=parent)); staging=temp/"payload"
        try:
            shutil.copytree(self.root/pid,staging); result=verify_export_root(staging); os.replace(staging,out)
        except OSError as exc:
            shutil.rmtree(temp,ignore_errors=True)
            raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-WRITE-001","Research Package export failed") from exc
        except Exception:
            shutil.rmtree(temp,ignore_errors=True)
            raise
        finally: shutil.rmtree(temp,ignore_errors=True)
        return {"status":"EXPORTED","package_id":pid,"package_digest":p["package_digest"],"output":str(out),"verification":result}
    @staticmethod
    def _summary(p):
        return {"package_id":p["package_id"],"package_digest":p["package_digest"],"schema_version":p["schema_version"],"project_id":p["project"]["project_id"],"snapshot_id":p["source_research_snapshot"]["snapshot_id"],"rq_ids":list(p["content"]["research_question_refs"]),"source_epistemic_status":p["source_epistemic_status"],"preview_only":p["preview_only"],"release_eligible":p["release_eligible"]}

__all__=["ResearchPackageService","verify_export_root"]
