from __future__ import annotations

from typing import Any, Mapping

from .models import CapabilityExecutionError, ExecutionFailureCode, ResourcePayload
from .ports import ExecutionArtifactStore, ResourceProvider


class BoundedResourceAccess:
    """Capability-facing read-only resource session.

    Only Context Pack references authorized for this Run can be loaded. The
    provider itself is never exposed to the capability implementation.
    """

    def __init__(
        self,
        context_pack: Mapping[str, Any],
        authorized_reference_ids: tuple[str, ...],
        provider: ResourceProvider,
        artifact_store: ExecutionArtifactStore | None = None,
    ) -> None:
        self._resources = {
            str(item["reference_id"]): dict(item)
            for item in context_pack["resources"]
        }
        self._authorized = frozenset(authorized_reference_ids)
        self._provider = provider
        self._artifact_store = artifact_store

    @property
    def artifact_store(self) -> ExecutionArtifactStore | None:
        """Return the explicitly injected trusted output store, if configured."""
        return self._artifact_store

    def read(self, reference_id: str) -> ResourcePayload:
        resource = self._resources.get(reference_id)
        if resource is None or reference_id not in self._authorized:
            raise CapabilityExecutionError(
                ExecutionFailureCode.RESOURCE_DENIED,
                f"resource {reference_id!r} is outside the bounded authorized Context Pack",
            )
        return self._provider.load(resource)

    def metadata(self, reference_id: str) -> Mapping[str, Any]:
        resource = self._resources.get(reference_id)
        if resource is None or reference_id not in self._authorized:
            raise CapabilityExecutionError(
                ExecutionFailureCode.RESOURCE_DENIED,
                f"resource {reference_id!r} is outside the bounded authorized Context Pack",
            )
        return dict(resource)
