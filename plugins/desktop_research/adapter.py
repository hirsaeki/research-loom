from __future__ import annotations

from core.execution import ExecutionStyle


class DesktopResearchExternalAdapter:
    """External-first production binding for the canonical PR11 capability.

    The adapter intentionally owns no browser, search engine, fetch transport,
    or LLM provider. External/interactive tooling drives retrieval between
    prepare_external() and collect_external().
    """

    implementation_id = "plugin.desktop-research.external"
    implementation_version = "0.1.0"
    capability_id = "desktop-research"
    capability_version = "0.1.0"
    supported_functions = ("investigate",)
    supported_execution_modes = ("real", "virtual", "synthetic_test")
    execution_style = ExecutionStyle.EXTERNAL
    requires_context_extension = True

    def execute(self, request):
        raise AssertionError("DesktopResearchExternalAdapter must use external execution")

    def cancel(self, run_id: str) -> None:
        # External transports are intentionally not owned by this adapter.
        return None
