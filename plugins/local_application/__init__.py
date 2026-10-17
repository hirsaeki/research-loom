"""Explicit local production composition root, workspace, facade, and CLI boundary."""

from plugins.application_errors import LocalApplicationError

from .facade_composition import LocalApplicationFacade
from .workspace.application import LocalResearchApplication, LocalStaticAuthorizationProvider
from .workspace.workspace import LocalWorkspace, LocalWorkspaceError, OpenedLocalWorkspace
from .writer.writer_composition_service import (
    verify_section_input_root as verify_writer_section_input,
)

__all__ = [
    "LocalApplicationError",
    "LocalApplicationFacade",
    "LocalResearchApplication",
    "LocalStaticAuthorizationProvider",
    "LocalWorkspace",
    "LocalWorkspaceError",
    "OpenedLocalWorkspace",
    "verify_writer_section_input",
]
