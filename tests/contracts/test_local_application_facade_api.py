"""Public API snapshot of LocalApplicationFacade (#491).

The facade is being moved from a ~30-level inheritance chain to composition.
This snapshot is the compatibility gate: every public name keeps its kind and
signature. After an intentional API change, regenerate it with

    uv run --frozen python -m tests.contracts.test_local_application_facade_api --update
"""

from __future__ import annotations

import inspect
import json
import sys
import unittest
from pathlib import Path
from typing import Any

SNAPSHOT = Path(__file__).with_name("local_application_facade_api.json")

# Stage order of each public operation on the exported facade, outermost
# first (module of each stage). It follows the MRO, as the former super()
# chain did; a change here is a behavior change and must be deliberate.
STAGE_ORDER = {
    "capture_exhibit": [
        "visual_need_facade",
        "visual_facade",
    ],
    "capture_external_source": [
        "retention_facade",
    ],
    "capture_virtual_run_response_dataset": [
        "survey_response_facade",
    ],
    "close": [
        "project_input_facade",
    ],
    "collect_external": [
        "synthesis_candidate_facade",
        "external_attempt_lifecycle_facade",
    ],
    "list_actions": [
        "source_bibliography_facade",
        "evidence_qualification_facade",
        "recommendation_facade",
        "new_material_continuation_public_facade",
        "finding_recovery_facade",
        "argument_facade",
        "question_review_facade",
        "survey_analysis_facade",
        "virtual_runner_facade",
        "survey_response_facade",
        "retention_facade",
    ],
    "replay_completed_desktop_research_run": [
        "synthesis_candidate_facade",
    ],
    "resolve_human_decision": [
        "synthesis_candidate_facade",
    ],
    "resume_context": [
        "synthesis_candidate_facade",
        "recommendation_facade",
        "question_review_facade",
    ],
    "show_run": [
        "synthesis_candidate_facade",
        "new_material_continuation_public_facade",
        "material_reacquisition_public_facade",
        "historical_result_recovery_facade",
        "historical_finding_recovery_facade",
        "virtual_runner_inspection",
    ],
    "status": [
        "synthesis_candidate_facade",
    ],
    "submit_action": [
        "source_bibliography_facade",
        "evidence_qualification_facade",
        "synthesis_candidate_facade",
        "recommendation_facade",
        "new_material_continuation_public_facade",
        "finding_recovery_facade",
        "argument_facade",
        "project_input_facade",
        "question_review_facade",
        "survey_analysis_facade",
        "virtual_runner_facade",
        "survey_response_facade",
        "retention_facade",
    ],
    "submit_confirmation": [
        "synthesis_candidate_facade",
    ],
}


def facade_api() -> list[dict[str, Any]]:
    from plugins.local_application import LocalApplicationFacade

    entries = []
    for name in sorted(dir(LocalApplicationFacade)):
        if name.startswith("_"):
            continue
        raw = inspect.getattr_static(LocalApplicationFacade, name)
        if isinstance(raw, property):
            entries.append({"name": name, "kind": "property"})
            continue
        if isinstance(raw, classmethod):
            kind = "classmethod"
        elif isinstance(raw, staticmethod):
            kind = "staticmethod"
        elif callable(raw):
            kind = "method"
        else:
            entries.append({"name": name, "kind": "attribute"})
            continue
        signature = str(inspect.signature(getattr(LocalApplicationFacade, name)))
        entries.append({"name": name, "kind": kind, "signature": signature})
    return entries


class LocalApplicationFacadeApiTests(unittest.TestCase):
    def test_public_api_matches_snapshot(self):
        expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        actual = facade_api()
        expected_by_name = {entry["name"]: entry for entry in expected}
        actual_by_name = {entry["name"]: entry for entry in actual}
        self.assertEqual(
            sorted(expected_by_name.keys() - actual_by_name.keys()), [], "public names removed"
        )
        self.assertEqual(
            sorted(actual_by_name.keys() - expected_by_name.keys()), [], "public names added"
        )
        changed = [
            name
            for name in sorted(expected_by_name)
            if expected_by_name[name] != actual_by_name.get(name)
        ]
        self.assertEqual([], changed, "public kind or signature changed")

    def test_public_methods_are_not_overridden_by_layers(self):
        # Layers contribute ordered stages (_<NAME>_STAGES, see
        # facade.run_stages) rather than overriding public methods via super().
        from plugins.local_application import LocalApplicationFacade

        overridden = {
            name: [cls.__module__ for cls in LocalApplicationFacade.__mro__ if name in vars(cls)]
            for name in dir(LocalApplicationFacade)
            if not name.startswith("_")
        }
        self.assertEqual(
            {}, {name: owners for name, owners in overridden.items() if len(owners) > 1}
        )

    def test_stage_order_is_pinned(self):
        from plugins.local_application import LocalApplicationFacade
        from plugins.local_application.facade import stages_for

        actual = {
            name: [
                stage.__module__.rsplit(".", 1)[-1]
                for stage in stages_for(LocalApplicationFacade, name)
            ]
            for name in STAGE_ORDER
        }
        self.assertEqual(STAGE_ORDER, actual)

    def test_facade_is_defined_once_from_mixins(self):
        # The facade is composed in facade_composition.py; feature modules
        # contribute mixins and never define LocalApplicationFacade themselves.
        import ast
        from pathlib import Path

        package = Path(__file__).resolve().parents[2] / "plugins" / "local_application"
        definers = sorted(
            path.name
            for path in package.glob("*.py")
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.ClassDef) and node.name == "LocalApplicationFacade"
        )
        self.assertEqual(["facade_composition.py"], definers)

    def test_intermediate_facades_run_the_stages_below_them(self):
        # Continuation services build this intermediate facade directly; it
        # must keep running the stages its former super() chain reached.
        from plugins.local_application import LocalApplicationFacade
        from plugins.local_application.facade import stages_for
        from plugins.local_application.facade_composition import ContinuationFacade

        for name in STAGE_ORDER:
            full = stages_for(LocalApplicationFacade, name)
            below = stages_for(ContinuationFacade, name)
            self.assertEqual(full[len(full) - len(below) :], below, name)
        self.assertEqual(
            [
                stage.__module__.rsplit(".", 1)[-1]
                for stage in stages_for(ContinuationFacade, "submit_action")
            ],
            STAGE_ORDER["submit_action"][5:],
        )


if __name__ == "__main__":
    if sys.argv[1:] == ["--update"]:
        SNAPSHOT.write_text(json.dumps(facade_api(), indent=2) + "\n", encoding="utf-8")
    else:
        unittest.main()
