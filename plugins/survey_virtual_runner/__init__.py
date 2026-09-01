"""Production Survey Virtual Runner binding.

The canonical Virtual Runner contract remains under core/packages/virtual-runner.
This plugin supplies only the first Survey execution adapter and shared Survey
response validation; it is not a Research Method and never starts REAL execution.
"""

from .adapter import StructuralSurveyVirtualRunnerAdapter
from .contracts import SurveyVirtualRunnerContextValidator
from .normalization import SurveyVirtualRunnerNormalizer
from .response_validation import SurveyResponseValidator

__all__ = [
    "StructuralSurveyVirtualRunnerAdapter",
    "SurveyResponseValidator",
    "SurveyVirtualRunnerContextValidator",
    "SurveyVirtualRunnerNormalizer",
]
