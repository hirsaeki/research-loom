from __future__ import annotations

from copy import deepcopy
from typing import Mapping
from unittest.mock import patch

from plugins.local_application.new_material_continuation_service import (
    _render_reacquired_html_rendition,
)
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
from test_issue171_new_material_continuation import (
    Issue171NewMaterialContinuationTests as _Issue171Support,
)


class Issue127HtmlContinuationReviewTests(ResearchPackageAcceptanceSupport):
    _remove_producer_candidate = staticmethod(_Issue171Support._remove_producer_candidate)
    _make_original_pair_missing = staticmethod(_Issue171Support._make_original_pair_missing)
    _make_original_new_version = _Issue171Support._make_original_new_version

    def _continue_with_budget(self, facade, case, reacquired, **budget_overrides):
        del case
        extension_store = facade._application.context_extension_store
        real_load = extension_store.load

        def load_with_budget(*args, **kwargs):
            extension = real_load(*args, **kwargs)
            if not isinstance(extension, Mapping):
                return extension
            budget = extension.get("budget")
            if not isinstance(budget, Mapping):
                return extension
            overridden = deepcopy(dict(extension))
            overridden["budget"] = dict(budget)
            overridden["budget"].update(budget_overrides)
            return overridden

        with patch.object(extension_store, "load", side_effect=load_with_budget):
            return facade.submit_action(
                {
                    "action_type": "desktop_research.material.continue_new_version",
                    "payload": {
                        "reacquisition_run_id": reacquired["reacquisition_run_id"]
                    },
                }
            )

    def test_malformed_skip_close_does_not_expose_hidden_html(self):
        rendered = _render_reacquired_html_rendition(
            b"<html><body><noscript>hidden</script>must-stay-hidden</noscript>"
            b"<p>visible</p></body></html>",
            "text/html",
            max_bytes=4096,
        )
        self.assertNotIn(b"must-stay-hidden", rendered)
        self.assertIn(b"visible", rendered)

    def test_pinned_original_budget_aborts_before_collect(self):
        facade, case = self._prepare_case()
        try:
            _original, _rendition, changed, reacquired = self._make_original_new_version(
                facade, case
            )
            rejected = self._continue_with_budget(
                facade,
                case,
                reacquired,
                max_original_capture_bytes=len(changed) - 1,
            )
            self.assertEqual(rejected["status"], "FAILED")
            self.assertIn(
                "reacquired original exceeds the pinned capture budget",
                rejected["issues"][0]["message"],
            )
            shown = facade.show_run(reacquired["reacquisition_run_id"])
            child_id = shown["new_material_continuation"]["new_run_id"]
            self.assertEqual(
                facade._application.execution_store.load_run(child_id).status.value,
                "ABORTED",
            )
        finally:
            facade.close()

    def test_pinned_text_budget_aborts_before_collect(self):
        facade, case = self._prepare_case()
        try:
            _original, _rendition, changed, reacquired = self._make_original_new_version(
                facade, case
            )
            rejected = self._continue_with_budget(
                facade,
                case,
                reacquired,
                max_original_capture_bytes=len(changed) + 1,
                max_text_rendition_bytes=8,
            )
            self.assertEqual(rejected["status"], "FAILED")
            self.assertIn(
                "derived text rendition exceeds bounded artifact limit",
                rejected["issues"][0]["message"],
            )
            shown = facade.show_run(reacquired["reacquisition_run_id"])
            child_id = shown["new_material_continuation"]["new_run_id"]
            self.assertEqual(
                facade._application.execution_store.load_run(child_id).status.value,
                "ABORTED",
            )
        finally:
            facade.close()
