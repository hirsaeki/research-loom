"""Explicit local production composition root, workspace, facade, and CLI boundary."""

from .application import LocalResearchApplication, LocalStaticAuthorizationProvider
from .facade import LocalApplicationError
from .new_material_continuation_html_hardening import (
    install_new_material_continuation_html_hardening as _install_new_material_continuation_html_hardening,
)

_install_new_material_continuation_html_hardening()
from .new_material_group_continuation_pdf_provider import (
    install_new_material_group_continuation_pdf_provider,
)

install_new_material_group_continuation_pdf_provider()
from .recommendation_facade import LocalApplicationFacade
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
