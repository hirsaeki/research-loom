from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Any, Mapping

from core.runtime.transition_models import canonical_digest

from .models import (
    AuthorizationDecision,
    CapabilityRunRecord,
    ExecutionArtifactMetadata,
    ExecutionIssue,
    ResourcePayload,
    RunLifecycleEvent,
)


class InMemoryExecutionTraceStore:
    def __init__(self) -> None:
        self.runs: dict[str, CapabilityRunRecord] = {}
        self.events: dict[str, list[RunLifecycleEvent]] = {}
        self.descriptors: dict[str, Mapping[str, Any]] = {}
        self.invocations: dict[str, Mapping[str, Any]] = {}
        self.contexts: dict[str, Mapping[str, Any]] = {}
        self.handoffs: dict[str, Mapping[str, Any]] = {}
        self.extensions: dict[str, Mapping[str, Any]] = {}
        self.artifacts: dict[str, ExecutionArtifactMetadata] = {}
        self.diagnostics: list[tuple[str, str, Mapping[str, Any]]] = []

    @staticmethod
    def _immutable_put(store, identity, document, *, single_use=False):
        frozen = deepcopy(dict(document))
        prior = store.get(identity)
        if prior is not None:
            if single_use or canonical_digest(prior) != canonical_digest(frozen):
                raise ValueError(f"immutable execution identity collision: {identity}")
            return
        store[identity] = frozen

    def create_run(self, run):
        if run.run_id in self.runs:
            raise ValueError(f"Run ID is single-use: {run.run_id}")
        self.runs[run.run_id] = run
        self.events[run.run_id] = []

    def load_run(self, run_id): return self.runs.get(run_id)
    def update_run(self, run):
        if run.run_id not in self.runs: raise ValueError("unknown Run")
        self.runs[run.run_id] = run
    def append_run_event(self, event): self.events[event.run_id].append(event)
    def events_for(self, run_id): return tuple(self.events.get(run_id, ()))
    def store_descriptor(self, descriptor): self._immutable_put(self.descriptors, descriptor["descriptor_digest"], descriptor)
    def store_invocation(self, invocation): self._immutable_put(self.invocations, invocation["invocation_id"], invocation)
    def store_context_pack(self, context): self._immutable_put(self.contexts, context["context_pack_id"], context)
    def store_handoff(self, handoff): self._immutable_put(self.handoffs, handoff.get("handoff_id", f"raw-{len(self.handoffs)}"), handoff)
    def store_result_extension(self, run_id, extension):
        ref = str(extension.get("extension_digest") or canonical_digest(extension))
        self._immutable_put(self.extensions, ref, extension)
        return ref
    def register_output_artifact(self, artifact):
        prior=self.artifacts.get(artifact.artifact_id)
        if prior is not None and asdict(prior) != asdict(artifact): raise ValueError("immutable artifact identity collision")
        self.artifacts[artifact.artifact_id]=artifact
    def load_invocation(self, invocation_id): return deepcopy(self.invocations.get(invocation_id))
    def load_context_pack(self, context_pack_id): return deepcopy(self.contexts.get(context_pack_id))
    def load_descriptor(self, descriptor_digest): return deepcopy(self.descriptors.get(descriptor_digest))
    def store_diagnostic(self, run_id, kind, payload): self.diagnostics.append((run_id,kind,deepcopy(dict(payload))))


class StaticClock:
    def __init__(self, value: str = "2026-08-26T00:00:00Z") -> None: self.value=value
    def now(self) -> str: return self.value


class AllowListedAuthorizationProvider:
    def __init__(self, authorization_digests=(), *, denied=False) -> None:
        self._digests=frozenset(authorization_digests); self._denied=denied
    def validate(self, evidence, *, invocation, context_pack, now):
        if self._denied or evidence.get("authorization_digest") not in self._digests:
            return AuthorizationDecision(False, (), (ExecutionIssue("AUTHORIZATION_DENIED","authorization evidence is unknown, expired, stale, or denied"),))
        if evidence.get("capability_id") != invocation["capability"]["capability_id"] or evidence.get("function_id") != invocation["capability"]["function_id"] or invocation["execution_mode"] not in evidence.get("execution_modes", ()):
            return AuthorizationDecision(False, (), (ExecutionIssue("AUTHORIZATION_DENIED","authorization binding mismatch"),))
        return AuthorizationDecision(True, tuple(evidence.get("resource_reference_ids", ())), ())


class InMemoryResourceProvider:
    def __init__(self, payloads: Mapping[str, bytes] | None = None) -> None: self.payloads=dict(payloads or {})
    def load(self, resource):
        ref=str(resource["reference_id"])
        if ref not in self.payloads: raise KeyError(ref)
        return ResourcePayload(ref,self.payloads[ref],resource.get("digest"))
