"""Explicit local production composition root, workspace, facade, and CLI boundary."""

from .application import LocalResearchApplication, LocalStaticAuthorizationProvider
from .facade import LocalApplicationError
from .external_attempt_lifecycle_facade import LocalApplicationFacade
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
