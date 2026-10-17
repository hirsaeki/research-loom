"""The local application facade, composed from its feature mixins.

``LocalApplicationFacade`` is defined here once. Its bases are listed in the
order the former layered facade resolved them, so method resolution, stage
order (see ``facade.stages_for``) and ``super()`` behave as before. The
partial facades below are the compositions some services instantiate
directly; they run exactly the layers they used to.
"""

from __future__ import annotations

from .argument_facade import ArgumentMixin
from .delphi_facade import DelphiMixin
from .evidence_qualification_facade import EvidenceQualificationMixin
from .exhibit_facade import ExhibitMixin
from .exhibit_guard_facade import ExhibitGuardMixin
from .external_attempt_lifecycle_facade import ExternalAttemptLifecycleMixin
from .external_desktop_facade import ExternalDesktopMixin
from .facade import LocalApplicationFacadeCore
from .finding_recovery_facade import FindingRecoveryMixin
from .historical_finding_recovery_facade import HistoricalFindingRecoveryMixin
from .historical_result_recovery_facade import HistoricalResultRecoveryMixin
from .material_import_facade import MaterialImportMixin
from .material_inventory_facade import MaterialInventoryMixin
from .material_reacquisition_public_facade import MaterialReacquisitionPublicMixin
from .new_material_continuation_public_facade import NewMaterialContinuationPublicMixin
from .project_input_facade import ProjectInputMixin
from .question_review_facade import QuestionReviewMixin
from .recommendation_facade import RecommendationMixin
from .research_quality_facade import ResearchQualityMixin
from .resume_facade import ResumeMixin
from .retention_facade import RetentionMixin
from .run_inspection_facade import RunInspectionMixin
from .source_bibliography_facade import SourceBibliographyMixin
from .survey_analysis_facade import SurveyAnalysisMixin
from .survey_facade import SurveyMixin
from .survey_response_facade import SurveyResponseMixin
from .synthesis_candidate_facade import SynthesisCandidateMixin
from .virtual_runner_facade import VirtualRunnerMixin
from .visual_facade import VisualMixin
from .visual_need_facade import VisualNeedMixin


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
