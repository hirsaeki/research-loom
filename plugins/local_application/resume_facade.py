from __future__ import annotations

from typing import Any, Mapping

from plugins.local_application.facade import LocalApplicationFacade as _BaseLocalApplicationFacade
from plugins.local_application.resume import build_resume_context


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Production facade extended with the read-only research resume projection."""

    def resume_context(self, *, limits: Mapping[str, int] | None = None) -> Mapping[str, Any]:
        return build_resume_context(
            self._application,
            self._project_id,
            limits=limits,
        )
