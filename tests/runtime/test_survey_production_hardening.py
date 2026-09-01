from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_survey_store import canonical_document_digest
from test_survey_production import (
    ROOT,
    adopt_rq,
    design_payload,
    extended_questionnaire,
    fixtures,
    initialize_workspace,
    instrument_payload,
    make_app,
)


def run_launcher(argv: list[str]) -> tuple[int, dict]:
    result = subprocess.run(
        [str(ROOT / "research-loom"), *argv],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"launcher did not return JSON: exit={result.returncode} stderr={result.stderr!r} stdout={result.stdout!r}"
        ) from exc
    return result.returncode, payload


class SurveyProductionHardeningTests(unittest.TestCase):
    def test_choice_branching_uses_stable_values_and_missing_categories_do_not_collapse(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                facade.capture_survey_design(design_payload())

                unstable_branch = extended_questionnaire()
                unstable_branch["questions"][1]["branching"][0]["value"] = "M"
                unstable_branch["content_digest"] = canonical_document_digest(
                    unstable_branch, "content_digest"
                )
                with self.assertRaises(LocalApplicationError) as branch_error:
                    facade.capture_survey_instrument(
                        instrument_payload(questionnaire=unstable_branch)
                    )
                self.assertEqual(
                    branch_error.exception.code, "APPLICATION-SURVEY-BRANCH-001"
                )

                collapsed_missing = extended_questionnaire()
                collapsed_missing["questions"][0]["missing_value_semantics"][
                    "not_applicable_option_id"
                ] = "U"
                collapsed_missing["content_digest"] = canonical_document_digest(
                    collapsed_missing, "content_digest"
                )
                with self.assertRaises(LocalApplicationError) as missing_error:
                    facade.capture_survey_instrument(
                        instrument_payload(questionnaire=collapsed_missing)
                    )
                self.assertEqual(
                    missing_error.exception.code,
                    "APPLICATION-SURVEY-QUESTIONNAIRE-001",
                )
            finally:
                app.close()

    def test_production_launcher_capture_show_and_both_exports_reopen_cleanly(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = initialize_workspace(root)
            rq_id = adopt_rq(workspace)
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                before = deepcopy(facade.status()["snapshot"])

            design_file = root / "survey-design.json"
            design_file.write_text(
                json.dumps(design_payload(rq_id=rq_id), ensure_ascii=False),
                encoding="utf-8",
            )
            code, captured_design = run_launcher([
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
            code, captured_instrument = run_launcher([
                "survey", "instrument", "capture",
                "--workspace", str(workspace),
                "--json", str(instrument_file),
            ])
            self.assertEqual((code, captured_instrument["status"]), (0, "CAPTURED"))

            code, shown = run_launcher([
                "survey", "instrument", "show",
                "--workspace", str(workspace),
                "--instrument-id", "QNR-1",
                "--version", "1.0.0",
                "--json",
            ])
            self.assertEqual((code, shown["status"]), (0, "OK"))
            self.assertEqual(shown["instrument"]["rq_ids"], [rq_id])

            code, exported_json = run_launcher([
                "survey", "instrument", "export",
                "--workspace", str(workspace),
                "--instrument-id", "QNR-1",
                "--version", "1.0.0",
                "--format", "json",
                "--json",
            ])
            self.assertEqual((code, exported_json["status"]), (0, "OK"))
            code, exported_markdown = run_launcher([
                "survey", "instrument", "export",
                "--workspace", str(workspace),
                "--instrument-id", "QNR-1",
                "--version", "1.0.0",
                "--format", "markdown",
                "--json",
            ])
            self.assertEqual((code, exported_markdown["status"]), (0, "OK"))
            self.assertEqual(
                json.loads(exported_json["content"])["instrument_id"], "QNR-1"
            )
            self.assertTrue(exported_markdown["content"].startswith("# "))

            with LocalApplicationFacade.open_workspace(workspace) as facade:
                after = facade.status()["snapshot"]
                self.assertEqual(after, before)
                repeat = facade.export_survey_instrument(
                    "QNR-1", "1.0.0", format="json"
                )
                self.assertEqual(
                    repeat["export_digest"], exported_json["export_digest"]
                )
                self.assertEqual(repeat["content"], exported_json["content"])


if __name__ == "__main__":
    unittest.main()
