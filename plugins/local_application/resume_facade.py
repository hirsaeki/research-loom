from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from plugins.local_application.resume import build_resume_context

from .support.stages import given_kwargs, run_stages, stages_for


class ResumeMixin:
    """Production facade extended with the read-only research resume projection."""

    def resume_context(
        self, *, limits: Mapping[str, int] | None = None, view: str | None = None
    ) -> Mapping[str, Any]:
        return run_stages(
            stages_for(type(self), "resume_context"),
            self,
            self._resume_context_terminal,
            limits=limits,
            **given_kwargs(view=view),
        )

    def _resume_context_terminal(
        self, *, limits: Mapping[str, int] | None = None
    ) -> Mapping[str, Any]:
        result = dict(
            build_resume_context(
                self._application,
                self._project_id,
                limits=limits,
            )
        )
        if self._workspace_root is not None:
            from plugins.local_durable_store import inspect_optional_children

            from .workspace import BINDING_NAME, INTERNAL_DIR, _read_json

            binding = _read_json(
                self._workspace_root / INTERNAL_DIR / BINDING_NAME, code="WORKSPACE-BINDING-001"
            )
            optional = inspect_optional_children(self._workspace_root, binding)
            result["optional_children"] = optional
            if any(row["status"] == "UNAVAILABLE" for row in optional):
                result["status"] = "DEGRADED"
        return result
