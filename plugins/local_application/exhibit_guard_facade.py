from __future__ import annotations

from core.runtime.ports import StaleHeadError
from plugins.local_research_exhibit_store import LocalResearchExhibitStoreError
from plugins.sqlite_state_store.exhibit_guard import guard_research_state_head

from .exhibit_facade import LocalApplicationFacade as _BaseLocalApplicationFacade


class _StateGuardedResearchExhibitStore:
    def __init__(self, delegate, state_repository) -> None:
        self._delegate = delegate
        self._state_repository = state_repository

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)

    def capture(self, document):
        binding = document["captured_against"]
        try:
            with guard_research_state_head(
                self._state_repository,
                str(document["project_id"]),
                lineage_ref=str(binding["lineage_ref"]),
                snapshot_ref=str(binding["snapshot_ref"]),
                snapshot_digest=str(binding["snapshot_digest"]),
            ):
                return self._delegate.capture(document)
        except StaleHeadError as exc:
            raise LocalResearchExhibitStoreError(
                "APPLICATION-EXHIBIT-STATE-STALE-001",
                "Research State changed before Research Exhibit persistence",
            ) from exc


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Exhibit facade whose final persistence is guarded by the bound State HEAD."""

    def _exhibit_store(self):
        return _StateGuardedResearchExhibitStore(
            super()._exhibit_store(),
            self._application.state_repository,
        )
