"""Error type shared by the local application and the plugin layers below it.

``plugins.local_application.facade`` re-exports it, so callers that catch
``LocalApplicationError`` from either module catch the same class.
"""

from __future__ import annotations


class LocalApplicationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
