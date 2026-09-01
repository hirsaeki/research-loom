from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

from jsonschema import Draft202012Validator, FormatChecker
import rfc8785

from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalResearchApplication
from plugins.local_application.cli import main as cli_main
from plugins.local_survey_store import (
    LocalSurveyStoreError,
    canonical_document_digest,
)
from runtime_fixtures import project, rq, seed_state


ROOT = Path(__file__).resolve().parents[2]
SURVEY_FIXTURE = ROOT / "core/fixtures/capabilities/valid/generic-survey-contract-fixtures.json"
EXCHANGE_SCHEMA = ROOT / "core/packages/survey/survey-instrument-exchange.schema.json"
PROJECT_FIXTURE = ROOT / "projects/fixtures/valid/generic-project-config.json"
PROFILE_FIXTURE = ROOT / "profiles/fixtures/valid/effective-profile-set.json"


class NullResolver:
    def resolve(self, *_args, **_kwargs):
        return None


def profile_provider(_project_ref, expected_digest):
    return {
        "schema_version": "0.1.0",
        "core_contracts": {
            "research_contract": "0.1.0",
            "invariant_contract": "0.1.0",
        },
        "profile_pins": [{
            "profile_id": "fixture.research",
            "profile_type": "research",
            "profile_version": "1.0.0",
            "manifest_sha256": "1" * 64,
        }],
        "content_digest": expected_digest,
    }


def fixtures() -> dict:
    return json.loads(SURVEY_FIXTURE.read_text(encoding="utf-8"))


def make_app(root: str | Path) -> LocalResearchApplication:
    seed = seed_state(
        objects=[project(), rq(state="approved")],
        snapshot_id="SNP-SURVEY-0",
    )
    return LocalResearchApplication(
        root,
        resolver=NullResolver(),
        effective_profile_set_provider=profile_provider,
        seed_state=seed,
    )


def state_signature(app: LocalResearchApplication) -> tuple:
    repository = app.state_repository
    lineage = repository.load_active_lineage_ref("PRJ-1")
    state = repository.load_state_view("PRJ-1", lineage)
    return (
        state.active_lineage_ref,
        str(state.current_snapshot["id"]),
        str(state.current_snapshot["content_digest"]),
        tuple(
            (str(item["kind"]), str(item["id"]), int(item.get("revision", 0)))
            for item in state.effective_objects()
        ),
        tuple(
            str(item["request_id"])
            for item in app.human_decisions.pending("PRJ-1")
        ),
    )


def extended_questionnaire(*, rq_id: str = "RQ-1") -> dict:
    questionnaire = deepcopy(fixtures()["questionnaire"])
    questionnaire["sections"] = [
        {
            "section_id": "SEC-CORE",
            "title": "Core questions",
            "description": "Stable provider-neutral section.",
        }
    ]
    response_keys = {
        "Q1": "role",
        "Q2": "usefulness",
        "Q3": "count",
        "Q4": "notes",
    }
    for question in questionnaire["questions"]:
        question["section_id"] = "SEC-CORE"
        question["response_key"] = response_keys[question["question_id"]]
        question["traceability"]["research_question_ids"] = [rq_id]
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
    questionnaire["questions"][1]["branching"] = [{
        "condition_question_id": "Q1",
        "operator": "equals",
        "value": "manager",
        "action": "show",
        "target_question_id": "Q2",
    }]
    questionnaire["content_digest"] = canonical_document_digest(
        questionnaire, "content_digest"
    )
    return questionnaire


def design_payload(*, rq_id: str = "RQ-1") -> dict:
    return {
        "rq_ids": [rq_id],
        "design": deepcopy(fixtures()["design"]),
        "capture_origin": "test_probe",
    }


def instrument_payload(*, rq_id: str = "RQ-1", questionnaire=None) -> dict:
    return {
        "survey_design_id": "SV-DES-1",
        "survey_design_version": "1.0.0",
        "title": "Provider-neutral Survey fixture",
        "description": "Production registry and exchange test.",
        "questionnaire": questionnaire or extended_questionnaire(rq_id=rq_id),
        "capture_origin": "test_probe",
    }


def run_cli(argv: list[str], stdin_text: str = "") -> tuple[int, dict]:
    stream = io.StringIO()
    with redirect_stdout(stream):
        if stdin_text:
            import unittest.mock
            with unittest.mock.patch("sys.stdin", io.StringIO(stdin_text)):
                code = cli_main(argv)
        else:
            code = cli_main(argv)
    return code, json.loads(stream.getvalue())


def configuration_digest(config: dict) -> str:
    value = deepcopy(config)
    value.pop("configuration_digest", None)
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def bootstrap_config() -> dict:
    config = json.loads(PROJECT_FIXTURE.read_text(encoding="utf-8"))
    config["research_questions"]["references"] = []
    for attention in config["research_attention"]:
        attention.pop("related_question_ids", None)
    config["configuration_digest"] = configuration_digest(config)
    return config


def initialize_workspace(root: Path) -> Path:
    config = root / "project-config.json"
    profiles = root / "effective-profile-set.json"
    config.write_text(json.dumps(bootstrap_config()), encoding="utf-8")
    profiles.write_text(PROFILE_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    workspace = root / "workspace"
    result = LocalApplicationFacade.initialize_workspace(workspace, config, profiles)
    assert result["status"] == "INITIALIZED"
    return workspace


def adopt_rq(workspace: Path) -> str:
    with LocalApplicationFacade.open_workspace(workspace) as facade:
        proposed = facade.submit_action({
            "action_type": "research_question.propose",
            "payload": {
                "text": "Which bounded Survey observations answer this research question?",
                "derived_from_seed_ids": ["RQ-SEED-001"],
            },
            "actor_id": "HUMAN-SURVEY",
        })
        rq_id = proposed["data"]["research_question_candidate"]["id"]
        apply = facade.submit_action({
            "action_type": "state.apply_candidate",
            "payload": {
                "state_delta_proposal_id": proposed["data"]["state_delta_proposal_id"]
            },
            "actor_id": "HUMAN-SURVEY",
        })
        confirmed = facade.submit_confirmation({
            "confirmation_request_id": apply["confirmation_request"]["confirmation_request_id"],
            "actor_id": "HUMAN-SURVEY",
        })
        request = confirmed["decision_request"]
        resolved = facade.resolve_human_decision({
            "request_id": request["request_id"],
            "request_digest": request["request_digest"],
            "disposition": "approve_exact",
            "actor_id": "HUMAN-SURVEY",
        })
        assert resolved["status"] == "RESOLVED"
        return rq_id


class SurveyProductionFacadeTests(unittest.TestCase):
    def test_capture_show_export_reopen_is_deterministic_and_non_mutating(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            before = state_signature(app)
            design = facade.capture_survey_design(design_payload())
            instrument = facade.capture_survey_instrument(instrument_payload())
            self.assertEqual(design["status"], "CAPTURED")
            self.assertEqual(instrument["status"], "CAPTURED")
            self.assertEqual(state_signature(app), before)

            shown_design = facade.show_survey_design("SV-DES-1", "1.0.0")["survey_design"]
            shown_instrument = facade.show_survey_instrument("QNR-1", "1.0.0")["instrument"]
            self.assertEqual(shown_design["rq_ids"], ["RQ-1"])
            self.assertEqual(shown_instrument["design_ref"]["content_digest"], shown_design["design"]["content_digest"])
            self.assertEqual(shown_instrument["questionnaire"]["questions"][0]["response_key"], "role")

            json_a = facade.export_survey_instrument("QNR-1", "1.0.0", format="json")
            json_b = facade.export_survey_instrument("QNR-1", "1.0.0", format="json")
            markdown_a = facade.export_survey_instrument("QNR-1", "1.0.0", format="markdown")
            markdown_b = facade.export_survey_instrument("QNR-1", "1.0.0", format="markdown")
            self.assertEqual(json_a["content"], json_b["content"])
            self.assertEqual(json_a["export_digest"], json_b["export_digest"])
            self.assertEqual(markdown_a["content"], markdown_b["content"])
            self.assertEqual(markdown_a["export_digest"], markdown_b["export_digest"])

            exchange = json.loads(json_a["content"])
            validator = Draft202012Validator(
                json.loads(EXCHANGE_SCHEMA.read_text(encoding="utf-8")),
                format_checker=FormatChecker(),
            )
            self.assertEqual(list(validator.iter_errors(exchange)), [])
            q1 = exchange["sections"][0]["questions"][0]
            self.assertEqual(q1["variable"], "role")
            self.assertEqual(q1["choices"][0], {"value": "manager", "label": "Manager"})
            self.assertEqual(q1["missing_value_semantics"]["missing"], "no_response")
            self.assertEqual(q1["missing_value_semantics"]["unknown_value"], "unknown")
            self.assertIn("`manager`", markdown_a["content"])
            self.assertIn("Missing-value semantics", markdown_a["content"])
            self.assertEqual(state_signature(app), before)
            app.close()

            reopened = LocalResearchApplication(
                temp,
                resolver=NullResolver(),
                effective_profile_set_provider=profile_provider,
            )
            try:
                reopened_facade = LocalApplicationFacade(reopened, "PRJ-1")
                reopened_export = reopened_facade.export_survey_instrument(
                    "QNR-1", "1.0.0", format="json"
                )
                self.assertEqual(reopened_export["content"], json_a["content"])
                self.assertEqual(reopened_export["export_digest"], json_a["export_digest"])
                self.assertEqual(state_signature(reopened), before)
            finally:
                reopened.close()

    def test_invalid_bindings_question_identity_branching_and_missing_semantics_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                with self.assertRaises(LocalApplicationError) as missing_rq:
                    facade.capture_survey_design(design_payload(rq_id="RQ-MISSING"))
                self.assertEqual(missing_rq.exception.code, "APPLICATION-SURVEY-RQ-001")

                owned = design_payload()
                owned["project_id"] = "PRJ-CALLER"
                with self.assertRaises(LocalApplicationError) as authority:
                    facade.capture_survey_design(owned)
                self.assertEqual(authority.exception.code, "APPLICATION-SURVEY-AUTHORITY-001")

                with self.assertRaises(LocalApplicationError) as missing_design:
                    facade.capture_survey_instrument({
                        **instrument_payload(),
                        "survey_design_id": "SV-MISSING",
                    })
                self.assertEqual(
                    missing_design.exception.code,
                    "APPLICATION-SURVEY-DESIGN-BINDING-001",
                )

                facade.capture_survey_design(design_payload())

                duplicate = extended_questionnaire()
                duplicate["questions"][1]["response_key"] = "role"
                duplicate["content_digest"] = canonical_document_digest(
                    duplicate, "content_digest"
                )
                with self.assertRaises(LocalApplicationError) as duplicate_error:
                    facade.capture_survey_instrument(
                        instrument_payload(questionnaire=duplicate)
                    )
                self.assertEqual(
                    duplicate_error.exception.code,
                    "APPLICATION-SURVEY-QUESTIONNAIRE-001",
                )

                bad_branch = extended_questionnaire()
                bad_branch["questions"][1]["branching"][0]["condition_question_id"] = "Q-MISSING"
                bad_branch["content_digest"] = canonical_document_digest(
                    bad_branch, "content_digest"
                )
                with self.assertRaises(LocalApplicationError) as branch_error:
                    facade.capture_survey_instrument(
                        instrument_payload(questionnaire=bad_branch)
                    )
                self.assertEqual(
                    branch_error.exception.code, "APPLICATION-SURVEY-BRANCH-001"
                )

                bad_missing = extended_questionnaire()
                bad_missing["questions"][0]["missing_value_semantics"]["unknown_option_id"] = "NO-SUCH-OPTION"
                bad_missing["content_digest"] = canonical_document_digest(
                    bad_missing, "content_digest"
                )
                with self.assertRaises(LocalApplicationError) as missing_error:
                    facade.capture_survey_instrument(
                        instrument_payload(questionnaire=bad_missing)
                    )
                self.assertEqual(
                    missing_error.exception.code,
                    "APPLICATION-SURVEY-QUESTIONNAIRE-001",
                )
            finally:
                app.close()

    def test_revision_is_idempotent_but_immutable_and_row_metadata_corruption_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                first = facade.capture_survey_design(design_payload())
                second = facade.capture_survey_design(design_payload())
                self.assertEqual(first["status"], "CAPTURED")
                self.assertEqual(second["status"], "ALREADY_CAPTURED")

                changed = deepcopy(fixtures()["design"])
                changed["target_population"]["definition"] += " Changed."
                changed["content_digest"] = canonical_document_digest(
                    changed, "content_digest"
                )
                with self.assertRaises(LocalApplicationError) as immutable:
                    facade.capture_survey_design({
                        "rq_ids": ["RQ-1"],
                        "design": changed,
                        "capture_origin": "test_probe",
                    })
                self.assertEqual(immutable.exception.code, "SURVEY-IMMUTABLE-001")

                db = sqlite3.connect(Path(temp) / "survey-registry.sqlite3")
                try:
                    db.execute(
                        "UPDATE survey_designs SET content_digest=? WHERE survey_design_id=?",
                        ("sha256:" + "0" * 64, "SV-DES-1"),
                    )
                    db.commit()
                finally:
                    db.close()
                with self.assertRaises(LocalApplicationError) as corrupt:
                    facade.show_survey_design("SV-DES-1", "1.0.0")
                self.assertEqual(corrupt.exception.code, "SURVEY-STORE-INTEGRITY-001")
            finally:
                app.close()


class SurveyProductionCliTests(unittest.TestCase):
    def test_public_json_cli_vertical_slice_reopens_and_does_not_mutate_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = initialize_workspace(root)
            rq_id = adopt_rq(workspace)
            code, before = run_cli(["status", "--workspace", str(workspace), "--json"])
            self.assertEqual(code, 0)

            design_file = root / "survey-design.json"
            design_file.write_text(
                json.dumps(design_payload(rq_id=rq_id), ensure_ascii=False),
                encoding="utf-8",
            )
            code, captured_design = run_cli([
                "survey", "design", "capture",
                "--workspace", str(workspace),
                "--json", str(design_file),
            ])
            self.assertEqual((code, captured_design["status"]), (0, "CAPTURED"))

            questionnaire = deepcopy(fixtures()["questionnaire"])
            for question in questionnaire["questions"]:
                question["traceability"]["research_question_ids"] = [rq_id]
            questionnaire["content_digest"] = canonical_document_digest(
                questionnaire, "content_digest"
            )
            instrument_file = root / "survey-instrument.json"
            instrument_file.write_text(
                json.dumps(
                    instrument_payload(rq_id=rq_id, questionnaire=questionnaire),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            code, captured_instrument = run_cli([
                "survey", "instrument", "capture",
                "--workspace", str(workspace),
                "--json", str(instrument_file),
            ])
            self.assertEqual((code, captured_instrument["status"]), (0, "CAPTURED"))

            code, shown = run_cli([
                "survey", "instrument", "show",
                "--workspace", str(workspace),
                "--instrument-id", "QNR-1",
                "--version", "1.0.0",
                "--json",
            ])
            self.assertEqual((code, shown["status"]), (0, "OK"))
            self.assertEqual(shown["instrument"]["rq_ids"], [rq_id])

            code, exported_json = run_cli([
                "survey", "instrument", "export",
                "--workspace", str(workspace),
                "--instrument-id", "QNR-1",
                "--version", "1.0.0",
                "--format", "json",
                "--json",
            ])
            self.assertEqual((code, exported_json["status"]), (0, "OK"))
            code, exported_markdown = run_cli([
                "survey", "instrument", "export",
                "--workspace", str(workspace),
                "--instrument-id", "QNR-1",
                "--version", "1.0.0",
                "--format", "markdown",
                "--json",
            ])
            self.assertEqual((code, exported_markdown["status"]), (0, "OK"))
            self.assertTrue(exported_json["content"].startswith("{"))
            self.assertTrue(exported_markdown["content"].startswith("# "))

            code, repeated = run_cli([
                "survey", "instrument", "export",
                "--workspace", str(workspace),
                "--instrument-id", "QNR-1",
                "--version", "1.0.0",
                "--format", "json",
                "--json",
            ])
            self.assertEqual(code, 0)
            self.assertEqual(repeated["export_digest"], exported_json["export_digest"])
            self.assertEqual(repeated["content"], exported_json["content"])

            code, after = run_cli(["status", "--workspace", str(workspace), "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(after["snapshot"], before["snapshot"])
            self.assertEqual(
                after["pending_human_decisions"], before["pending_human_decisions"]
            )

    def test_repository_launcher_exposes_survey_namespace(self):
        result = subprocess.run(
            [str(ROOT / "research-loom"), "survey", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("design", result.stdout)
        self.assertIn("instrument", result.stdout)


if __name__ == "__main__":
    unittest.main()
