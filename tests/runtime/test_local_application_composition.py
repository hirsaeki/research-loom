from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from plugins.local_application import LocalApplicationFacade
from plugins.local_application.project_input_facade import (
    LocalApplicationFacade as LegacyStackedLocalApplicationFacade,
)
from tests.runtime.test_research_question_review import _workspace as make_workspace


class LocalApplicationCompositionTests(unittest.TestCase):
    def test_public_facade_has_shallow_mro_and_eager_action_composition(self):
        modules = [item.__module__ for item in LocalApplicationFacade.__mro__]
        self.assertEqual(
            modules,
            [
                "plugins.local_application.composition",
                "plugins.local_application.facade",
                "builtins",
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(Path(tmp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                # Registration is a composition-root concern now; it is complete
                # before list_actions()/submit_action() are used.
                registered = {
                    item.action_type
                    for item in facade._application.coordinator.action_definitions()
                }
                self.assertIn("research_question.review", registered)
                self.assertIn("survey_response.normalize", registered)
                self.assertIn("survey_aggregate.run", registered)

    def test_action_projection_matches_legacy_stack(self):
        with tempfile.TemporaryDirectory() as left, tempfile.TemporaryDirectory() as right:
            new_workspace = make_workspace(Path(left))
            old_workspace = make_workspace(Path(right))
            with LocalApplicationFacade.open_workspace(new_workspace) as composed:
                current = composed.list_actions()
            with LegacyStackedLocalApplicationFacade.open_workspace(old_workspace) as legacy:
                previous = legacy.list_actions()

            def normalized(value):
                return sorted(value["actions"], key=lambda item: item["action_type"])

            self.assertEqual(normalized(current), normalized(previous))


if __name__ == "__main__":
    unittest.main()
