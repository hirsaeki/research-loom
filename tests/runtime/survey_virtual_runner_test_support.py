from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalResearchApplication
from plugins.local_survey_store import canonical_document_digest
from plugins.survey_virtual_runner.response_validation import SurveyResponseValidator
from runtime_fixtures import decision, project, rq, seed_state
from test_survey_production import (
    NullResolver,
    design_payload,
    extended_questionnaire,
    instrument_payload,
    profile_provider,
    state_signature,
)

METHOD_ID = "METHOD-SURVEY-1"
PROTOCOL_ID = "PROTOCOL-SURVEY-1"
PROTOCOL_VERSION = "1.0.0"
PROTOCOL_DIGEST = "sha256:" + "7" * 64
PROTOCOL_REF = f"{PROTOCOL_ID}@{PROTOCOL_VERSION}#{PROTOCOL_DIGEST}"


def method_object() -> dict:
    return {
        "schema_version": "0.1.0",
        "id": METHOD_ID,
        "kind": "method",
        "revision": 0,
        "project_id": "PRJ-1",
        "question_ids": ["RQ-1"],
        "name": "Approved Survey method fixture",
        "protocol_ref": PROTOCOL_REF,
        "adoption_state": "approved",
        "decision_ids": ["DEC-METHOD-1"],
    }


def make_virtual_app(root: str | Path) -> LocalResearchApplication:
    method_decision = decision(
        "DEC-METHOD-1",
        "research_adoption",
        "approve",
        "method",
        METHOD_ID,
    )
    protocol_revision_decision = decision(
        "DEC-PROTOCOL-MAT-1",
        "research_revision",
        "revise",
        "protocol",
        PROTOCOL_ID,
    )
    seed = seed_state(
        objects=[project(), rq(state="approved"), method_object()],
        decisions=[method_decision, protocol_revision_decision],
        snapshot_id="SNP-VR-0",
    )
    return LocalResearchApplication(
        root,
        resolver=NullResolver(),
        effective_profile_set_provider=profile_provider,
        seed_state=seed,
    )


def execution_payload(
    *,
    scenario: str,
    instrument_version: str,
    instrument_digest: str,
    prior=(),
    stress_faults=None,
) -> dict:
    payload = {
        "instrument_id": "QNR-1",
        "instrument_version": instrument_version,
        "instrument_digest": instrument_digest,
        "scenario_class": scenario,
        "core_method_id": METHOD_ID,
        "core_method_revision": 0,
        "protocol": {
            "protocol_id": PROTOCOL_ID,
            "version": PROTOCOL_VERSION,
            "content_digest": PROTOCOL_DIGEST,
            "material_revision": False,
        },
        "evidence_gap_refs": [{
            "gap_id": "GAP-1",
            "source_handoff_id": "HND-G1",
            "source_handoff_digest": "sha256:" + "8" * 64,
            "source_resource_reference_id": "RES-G1",
        }],
        "run_spec_id": f"RUNSPEC-{scenario}",
        "run_spec_version": "1.0.0",
        "population_size": 6,
        "sampling_seed": 41,
        "prior_virtual_run_ids": list(prior),
        "readiness_policy": {
            "require_standard": True,
            "require_stress": True,
            "blocking_severities": ["critical"],
        },
    }
    if stress_faults is not None:
        payload["stress_faults"] = list(stress_faults)
    return payload


class SurveyVirtualRunnerTestBase(unittest.TestCase):
    def _capture(self, facade: LocalApplicationFacade, *, questionnaire=None):
        facade.capture_survey_design(design_payload())
        captured = facade.capture_survey_instrument(
            instrument_payload(questionnaire=questionnaire)
        )
        return facade.show_survey_instrument(
            captured["instrument_id"],
            captured["version"],
        )["instrument"]["questionnaire"]
