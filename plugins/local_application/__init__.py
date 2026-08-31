"""Explicit local production composition root, workspace, facade, and CLI boundary."""

from .application import LocalResearchApplication, LocalStaticAuthorizationProvider
from .external_desktop_facade import LocalApplicationFacade
from .facade import LocalApplicationError
from .workspace import LocalWorkspace, LocalWorkspaceError, OpenedLocalWorkspace

__all__ = [
    "LocalApplicationError",
    "LocalApplicationFacade",
    "LocalResearchApplication",
    "LocalStaticAuthorizationProvider",
    "LocalWorkspace",
    "LocalWorkspaceError",
    "OpenedLocalWorkspace",
]
