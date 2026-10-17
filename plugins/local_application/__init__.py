"""Explicit local production composition root, workspace, facade, and CLI boundary."""

from plugins.application_errors import LocalApplicationError

from .application import LocalResearchApplication, LocalStaticAuthorizationProvider
from .facade_composition import LocalApplicationFacade
from .workspace import LocalWorkspace, LocalWorkspaceError, OpenedLocalWorkspace
from .writer_composition_service import verify_section_input_root as verify_writer_section_input

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
