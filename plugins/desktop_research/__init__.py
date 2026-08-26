"""Production external-first Desktop Research capability adapter."""

from .adapter import DesktopResearchExternalAdapter
from .attempts import DesktopResearchAttemptRecorder
from .capture import DesktopResearchCaptureService
from .context_validation import DesktopResearchContextValidator
from .conversation import DesktopResearchConversationMaterializer
from .normalization import DesktopResearchNormalizer
from .result_validation import DesktopResearchResultValidator
from .submission import build_result_extension, with_context_extension_digest

__all__ = [
    "DesktopResearchAttemptRecorder",
    "DesktopResearchCaptureService",
    "DesktopResearchContextValidator",
    "DesktopResearchConversationMaterializer",
    "DesktopResearchExternalAdapter",
    "DesktopResearchNormalizer",
    "DesktopResearchResultValidator",
    "build_result_extension",
    "with_context_extension_digest",
]
