from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from threading import RLock
from typing import Any, Mapping

from core.runtime.transition_models import canonical_digest

from .models import (
    AuthorizationDecision,
    CapabilityRunRecord,
    ExecutionArtifactMetadata,
    ExecutionIssue,
    ResourcePayload,
    RunLifecycleEvent,
    RunStatus,
)


_RUN_IMMUTABLE_FIELDS = (
    "run_id",
    "invocation_id",
    "invocation_digest",
    "capability_id",
    "capability_version",
    "descriptor_digest",
    "implementation_id",
    "implementation_version",
    "function_id",
    "execution_mode",
    "context_pack_id",
    "context_pack_digest",
    "project_ref",
    "lineage_ref",
    "snapshot_ref",
    "snapshot_digest",
    "attempt",
    "parent_run_id",
    "prepared_at",
    "provenance",
)


class InMemoryExecutionTraceStore:
    """Test-only trace store with immutable documents and atomic Run CAS."""

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
        self._run_lock = RLock()

    @staticmethod
    def _immutable_put(
        store: dict[str, Mapping[str, Any]],
        identity: str,
        document: Mapping[str, Any],
        *,
        single_use: bool = False,
    ) -> None:
        frozen = deepcopy(dict(document))
        prior = store.get(identity)
        if prior is not None:
            if single_use or canonical_digest(prior) != canonical_digest(frozen):
                raise ValueError(
                    f"immutable execution identity collision: {identity}"
                )
            return
        store[identity] = frozen

    def create_run(self, run: CapabilityRunRecord) -> None:
        with self._run_lock:
            if run.run_id in self.runs:
                raise ValueError(f"Run ID is single-use: {run.run_id}")
            self.runs[run.run_id] = run
            self.events[run.run_id] = []

    def load_run(self, run_id: str) -> CapabilityRunRecord | None:
        with self._run_lock:
            return self.runs.get(run_id)

    def append_run_event(self, event: RunLifecycleEvent) -> None:
        with self._run_lock:
            self.events[event.run_id].append(event)

    def transition_run(
        self,
        expected_status: RunStatus,
        updated_run: CapabilityRunRecord,
        event: RunLifecycleEvent,
    ) -> bool:
        with self._run_lock:
            current = self.runs.get(updated_run.run_id)
            if current is None or current.status is not expected_status:
                return False
            for name in _RUN_IMMUTABLE_FIELDS:
                if getattr(current, name) != getattr(updated_run, name):
                    raise ValueError(
                        f"immutable Run field {name} cannot change on transition"
                    )
            self.runs[updated_run.run_id] = updated_run
            self.events[updated_run.run_id].append(event)
            return True

    def events_for(self, run_id: str) -> tuple[RunLifecycleEvent, ...]:
        with self._run_lock:
            return tuple(self.events.get(run_id, ()))

    def store_descriptor(self, descriptor: Mapping[str, Any]) -> None:
        self._immutable_put(
            self.descriptors,
            str(descriptor["descriptor_digest"]),
            descriptor,
        )

    def store_invocation(self, invocation: Mapping[str, Any]) -> None:
        self._immutable_put(
            self.invocations,
            str(invocation["invocation_id"]),
            invocation,
        )

    def store_context_pack(self, context: Mapping[str, Any]) -> None:
        self._immutable_put(
            self.contexts,
            str(context["context_pack_id"]),
            context,
        )

    def store_handoff(self, handoff: Mapping[str, Any]) -> None:
        identity = str(handoff.get("handoff_id", f"raw-{len(self.handoffs)}"))
        self._immutable_put(self.handoffs, identity, handoff)

    def store_result_extension(
        self,
        run_id: str,
        extension: Mapping[str, Any],
    ) -> str:
        del run_id
        ref = str(extension.get("extension_digest") or canonical_digest(extension))
        self._immutable_put(self.extensions, ref, extension)
        return ref

    def register_output_artifact(
        self,
        artifact: ExecutionArtifactMetadata,
    ) -> None:
        prior = self.artifacts.get(artifact.artifact_id)
        if prior is not None and asdict(prior) != asdict(artifact):
            raise ValueError("immutable artifact identity collision")
        self.artifacts[artifact.artifact_id] = artifact

    def load_invocation(
        self,
        invocation_id: str,
    ) -> Mapping[str, Any] | None:
        return deepcopy(self.invocations.get(invocation_id))

    def load_context_pack(
        self,
        context_pack_id: str,
    ) -> Mapping[str, Any] | None:
        return deepcopy(self.contexts.get(context_pack_id))

    def load_descriptor(
        self,
        descriptor_digest: str,
    ) -> Mapping[str, Any] | None:
        return deepcopy(self.descriptors.get(descriptor_digest))

    def store_diagnostic(
        self,
        run_id: str,
        kind: str,
        payload: Mapping[str, Any],
    ) -> None:
        self.diagnostics.append(
            (run_id, kind, deepcopy(dict(payload)))
        )


class StaticClock:
    def __init__(self, value: str = "2026-08-26T00:00:00Z") -> None:
        self.value = value

    def now(self) -> str:
        return self.value


class AllowListedAuthorizationProvider:
    def __init__(
        self,
        authorization_digests: tuple[str, ...] = (),
        *,
        denied: bool = False,
    ) -> None:
        self._digests = frozenset(authorization_digests)
        self._denied = denied

    def validate(
        self,
        evidence: Mapping[str, Any],
        *,
        invocation: Mapping[str, Any],
        context_pack: Mapping[str, Any],
        now: str,
    ) -> AuthorizationDecision:
        del context_pack, now
        if (
            self._denied
            or evidence.get("authorization_digest") not in self._digests
        ):
            return AuthorizationDecision(
                False,
                (),
                (
                    ExecutionIssue(
                        "AUTHORIZATION_DENIED",
                        "authorization evidence is unknown, expired, stale, or denied",
                    ),
                ),
            )
        if (
            evidence.get("capability_id")
            != invocation["capability"]["capability_id"]
            or evidence.get("function_id")
            != invocation["capability"]["function_id"]
            or invocation["execution_mode"]
            not in evidence.get("execution_modes", ())
        ):
            return AuthorizationDecision(
                False,
                (),
                (
                    ExecutionIssue(
                        "AUTHORIZATION_DENIED",
                        "authorization binding mismatch",
                    ),
                ),
            )
        return AuthorizationDecision(
            True,
            tuple(evidence.get("resource_reference_ids", ())),
            (),
        )


class InMemoryResourceProvider:
    def __init__(
        self,
        payloads: Mapping[str, bytes] | None = None,
    ) -> None:
        self.payloads = dict(payloads or {})

    def load(self, resource: Mapping[str, Any]) -> ResourcePayload:
        ref = str(resource["reference_id"])
        if ref not in self.payloads:
            raise KeyError(ref)
        return ResourcePayload(
            ref,
            self.payloads[ref],
            resource.get("digest"),
        )
