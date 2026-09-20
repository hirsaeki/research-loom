from __future__ import annotations

from typing import Any, Mapping

from plugins.local_application.facade import LocalApplicationFacade as _BaseLocalApplicationFacade
from plugins.local_application.resume import build_resume_context


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Production facade extended with the read-only research resume projection."""

    def resume_context(self, *, limits: Mapping[str, int] | None = None) -> Mapping[str, Any]:
        result = dict(build_resume_context(
            self._application,
            self._project_id,
            limits=limits,
        ))
        if self._workspace_root is not None:
            from plugins.local_durable_store import inspect_optional_children
            from .workspace import _read_json, BINDING_NAME, INTERNAL_DIR

            binding = _read_json(
                self._workspace_root / INTERNAL_DIR / BINDING_NAME, code="WORKSPACE-BINDING-001"
            )
            optional = inspect_optional_children(self._workspace_root, binding)
            result["optional_children"] = optional
            if any(row["status"] == "UNAVAILABLE" for row in optional):
                result["status"] = "DEGRADED"
        return result
