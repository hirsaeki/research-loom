"""The local application facade, composed from its feature mixins.

``LocalApplicationFacade`` is defined here once. Its bases are listed in the
order the former layered facade resolved them, so method resolution, stage
order (see ``facade.stages_for``) and ``super()`` behave as before. The
partial facades below are the compositions some services instantiate
directly; they run exactly the layers they used to.

Feature layers never import this module. The partial facades they need are
set here, on every composed class, as ``_*_facade_class`` attributes that the
mixins pass on to their action handlers and services.
"""

from __future__ import annotations

from .facade import LocalApplicationFacadeCore
from .material.external_attempt_lifecycle_facade import ExternalAttemptLifecycleMixin
from .material.external_desktop_facade import ExternalDesktopMixin
from .material.finding_recovery_facade import FindingRecoveryMixin
from .material.historical_finding_recovery_facade import HistoricalFindingRecoveryMixin
from .material.historical_result_recovery_facade import HistoricalResultRecoveryMixin
from .material.material_import_facade import MaterialImportMixin
from .material.material_inventory_facade import MaterialInventoryMixin
from .material.material_reacquisition_facade import MaterialReacquisitionPublicMixin
from .material.new_material_continuation_public_facade import NewMaterialContinuationPublicMixin
from .material.retention_facade import RetentionMixin
from .research.argument_facade import ArgumentMixin
from .research.evidence_qualification_facade import EvidenceQualificationMixin
from .research.exhibit_facade import ExhibitMixin
from .research.exhibit_guard_facade import ExhibitGuardMixin
from .research.project_input_facade import ProjectInputMixin
from .research.question_review_facade import QuestionReviewMixin
from .research.recommendation_facade import RecommendationMixin
from .research.research_quality_facade import ResearchQualityMixin
from .research.resume_facade import ResumeMixin
from .research.run_inspection_facade import RunInspectionMixin
from .research.source_bibliography_facade import SourceBibliographyMixin
from .research.synthesis_candidate_facade import SynthesisCandidateMixin
from .research.visual_facade import VisualMixin
from .research.visual_need_facade import VisualNeedMixin
from .survey.delphi_facade import DelphiMixin
from .survey.survey_analysis_facade import SurveyAnalysisMixin
from .survey.survey_facade import SurveyMixin
from .survey.survey_response_facade import SurveyResponseMixin
from .virtual_runner.virtual_runner_facade import VirtualRunnerMixin


class LocalApplicationFacade(
    SourceBibliographyMixin,
    EvidenceQualificationMixin,
    VisualNeedMixin,
    VisualMixin,
    ResearchQualityMixin,
    SynthesisCandidateMixin,
    RecommendationMixin,
    NewMaterialContinuationPublicMixin,
    MaterialReacquisitionPublicMixin,
    HistoricalResultRecoveryMixin,
    HistoricalFindingRecoveryMixin,
    FindingRecoveryMixin,
    ArgumentMixin,
    ProjectInputMixin,
    ExternalAttemptLifecycleMixin,
    QuestionReviewMixin,
    DelphiMixin,
    SurveyAnalysisMixin,
    VirtualRunnerMixin,
    SurveyResponseMixin,
    SurveyMixin,
    MaterialImportMixin,
    RetentionMixin,
    MaterialInventoryMixin,
    ExhibitGuardMixin,
    ExhibitMixin,
    RunInspectionMixin,
    ExternalDesktopMixin,
    ResumeMixin,
    LocalApplicationFacadeCore,
):
    """Public local application facade."""


class ContinuationFacade(
    MaterialReacquisitionPublicMixin,
    HistoricalResultRecoveryMixin,
    HistoricalFindingRecoveryMixin,
    FindingRecoveryMixin,
    ArgumentMixin,
    ProjectInputMixin,
    ExternalAttemptLifecycleMixin,
    QuestionReviewMixin,
    DelphiMixin,
    SurveyAnalysisMixin,
    VirtualRunnerMixin,
    SurveyResponseMixin,
    SurveyMixin,
    MaterialImportMixin,
    RetentionMixin,
    MaterialInventoryMixin,
    ExhibitGuardMixin,
    ExhibitMixin,
    RunInspectionMixin,
    ExternalDesktopMixin,
    ResumeMixin,
    LocalApplicationFacadeCore,
):
    """Facade used by the new-material continuation services."""


class SurveyAnalysisFacade(
    SurveyAnalysisMixin,
    VirtualRunnerMixin,
    SurveyResponseMixin,
    SurveyMixin,
    MaterialImportMixin,
    RetentionMixin,
    MaterialInventoryMixin,
    ExhibitGuardMixin,
    ExhibitMixin,
    RunInspectionMixin,
    ExternalDesktopMixin,
    ResumeMixin,
    LocalApplicationFacadeCore,
):
    """Facade used by the Survey analysis capability services."""


class SurveyResponseFacade(
    SurveyResponseMixin,
    SurveyMixin,
    MaterialImportMixin,
    RetentionMixin,
    MaterialInventoryMixin,
    ExhibitGuardMixin,
    ExhibitMixin,
    RunInspectionMixin,
    ExternalDesktopMixin,
    ResumeMixin,
    LocalApplicationFacadeCore,
):
    """Facade used by the Survey response capability services."""


_COMPOSED = (LocalApplicationFacade, ContinuationFacade, SurveyAnalysisFacade, SurveyResponseFacade)
for _facade in _COMPOSED:
    _facade._continuation_facade_class = ContinuationFacade
    _facade._survey_analysis_facade_class = SurveyAnalysisFacade
    _facade._survey_response_facade_class = SurveyResponseFacade
del _facade
