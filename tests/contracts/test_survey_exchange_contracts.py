from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from research_method_oracle import canonical_digest


ROOT = Path(__file__).resolve().parents[2]
SURVEY = ROOT / "core/packages/survey"
FIXTURE = ROOT / "core/fixtures/capabilities/valid/generic-survey-contract-fixtures.json"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def refresh(document: dict, field: str = "content_digest") -> None:
    document[field] = canonical_digest(document, field)


class SurveyExchangeContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract_schema = load(SURVEY / "survey-contract.schema.json")
        cls.exchange_schema = load(SURVEY / "survey-instrument-exchange.schema.json")
        cls.fixtures = load(FIXTURE)
        cls.format_checker = FormatChecker()

    def test_existing_questionnaire_fixture_remains_compatible(self):
        validator = Draft202012Validator(
            self.contract_schema, format_checker=self.format_checker
        )
        questionnaire = self.fixtures["questionnaire"]
        self.assertEqual(list(validator.iter_errors(questionnaire)), [])
        self.assertNotIn("response_key", questionnaire["questions"][0])
        self.assertNotIn("value", questionnaire["questions"][0]["response_options"][0])

    def test_optional_exchange_semantics_extend_without_redefining_questionnaire(self):
        questionnaire = deepcopy(self.fixtures["questionnaire"])
        questionnaire["sections"] = [
            {
                "section_id": "SEC-CORE",
                "title": "Core questions",
                "description": "Provider-neutral fixture section.",
            }
        ]
        for question in questionnaire["questions"]:
            question["section_id"] = "SEC-CORE"
            question["response_key"] = "var_" + question["question_id"].lower()
        first = questionnaire["questions"][0]
        first["response_options"][0]["value"] = "manager"
        first["response_options"][1]["value"] = "contributor"
        first["response_options"].append(
            {"option_id": "U", "value": "unknown", "label": "Unknown"}
        )
        first["missing_value_semantics"] = {
            "missing": "no_response",
            "unknown_option_id": "U",
            "not_applicable_option_id": None,
            "prefer_not_to_answer_option_id": None,
        }
        refresh(questionnaire)

        validator = Draft202012Validator(
            self.contract_schema, format_checker=self.format_checker
        )
        self.assertEqual(list(validator.iter_errors(questionnaire)), [])
        self.assertEqual(first["response_key"], "var_q1")
        self.assertEqual(first["response_options"][0]["label"], "Manager")
        self.assertEqual(first["response_options"][0]["value"], "manager")
        self.assertEqual(first["missing_value_semantics"]["missing"], "no_response")

    def test_provider_neutral_exchange_schema_is_valid_and_has_no_provider_fields(self):
        Draft202012Validator.check_schema(self.exchange_schema)
        exchange = {
            "schema_version": "0.1.0",
            "exchange_type": "research_loom_survey_instrument",
            "survey_id": "SV-DES-1",
            "survey_version": "1.0.0",
            "survey_content_digest": "sha256:" + "1" * 64,
            "instrument_id": "QNR-1",
            "instrument_version": "1.0.0",
            "instrument_content_digest": "sha256:" + "2" * 64,
            "title": "Provider-neutral instrument",
            "description": "Reconstructable without a Forms provider.",
            "rq_ids": ["RQ-1"],
            "snapshot_binding": {
                "lineage_ref": "LIN-1",
                "snapshot_ref": "SNP-1",
                "snapshot_digest": "sha256:" + "3" * 64,
            },
            "sections": [
                {
                    "id": "SEC-1",
                    "title": "Core",
                    "description": "",
                    "questions": [
                        {
                            "id": "Q1",
                            "variable": "role",
                            "type": "single_choice",
                            "prompt": "Role?",
                            "required": True,
                            "choices": [
                                {"value": "manager", "label": "Manager"}
                            ],
                            "scale": None,
                            "validation": None,
                            "branching": [],
                            "missing_value_semantics": {
                                "missing": "no_response",
                                "unknown_value": None,
                                "not_applicable_value": None,
                                "prefer_not_to_answer_value": None,
                            },
                            "randomization_group_id": None,
                            "traceability": {
                                "construct_ids": ["ROLE"],
                                "research_question_ids": ["RQ-1"],
                                "evidence_gap_ids": [],
                            },
                        }
                    ],
                }
            ],
        }
        validator = Draft202012Validator(
            self.exchange_schema, format_checker=self.format_checker
        )
        self.assertEqual(list(validator.iter_errors(exchange)), [])
        serialized = json.dumps(exchange, sort_keys=True)
        for provider_term in (
            "microsoft_form_id",
            "google_form_id",
            "graph_payload",
            "apps_script",
        ):
            self.assertNotIn(provider_term, serialized)


if __name__ == "__main__":
    unittest.main()
