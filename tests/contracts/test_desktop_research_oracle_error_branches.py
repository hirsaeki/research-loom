from __future__ import annotations

from copy import deepcopy
import json
import unittest

from desktop_research_oracle import context_semantic_error, result_semantic_error
from test_desktop_research_contracts import (
    CONTEXT_PATH,
    DR,
    HANDOFF_PATH,
    build_context_extension,
    build_desktop_handoff,
    build_result_extension,
    refresh_extension_digest,
)


class DesktopResearchOracleErrorBranches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Build one valid cross-document chain for focused branch regressions."""
        cls.context = json.loads(CONTEXT_PATH.read_text())
        cls.generic_handoff = json.loads(HANDOFF_PATH.read_text())
        cls.descriptor = json.loads(
            (DR / "desktop-research-capability-descriptor.json").read_text()
        )
        cls.context_extension = build_context_extension(cls.context)
        cls.handoff = build_desktop_handoff(
            cls.generic_handoff,
            cls.descriptor,
            cls.context,
        )
        cls.result_extension = build_result_extension(cls.context, cls.handoff)

    def test_rejects_stale_extension_digests(self):
        """Exercise both digest mismatch branches without refreshing the digest."""
        stale_context = deepcopy(self.context_extension)
        stale_context["retrieval_scope"]["scope_statement"] = (
            "Changed without refreshing the Context extension digest."
        )
        self.assertEqual(
            "DR-CONTEXT-DIGEST-001",
            context_semantic_error(stale_context, self.context),
        )

        stale_result = deepcopy(self.result_extension)
        stale_result["coverage_assessment"]["saturation"]["rationale"] = (
            "Changed without refreshing the result extension digest."
        )
        self.assertEqual(
            "DR-RESULT-DIGEST-001",
            result_semantic_error(
                stale_result,
                self.context_extension,
                self.context,
                self.handoff,
            ),
        )

    def test_rejects_context_binding_drift(self):
        """Exercise exact Context Pack binding rejection."""
        bad = deepcopy(self.context_extension)
        bad["context_binding"]["context_pack_id"] = "CTX-MISSING"
        refresh_extension_digest(bad)
        self.assertEqual(
            "DR-CONTEXT-BINDING-001",
            context_semantic_error(bad, self.context),
        )

    def test_rejects_capture_provenance_and_budget_drift(self):
        """Exercise capture provenance and bounded-result budget branches."""
        bad_provenance = deepcopy(self.result_extension)
        bad_provenance["source_capture_details"][0]["exact_locator"] = (
            "fixture://source#wrong"
        )
        refresh_extension_digest(bad_provenance)
        self.assertEqual(
            "DR-CAPTURE-PROVENANCE-001",
            result_semantic_error(
                bad_provenance,
                self.context_extension,
                self.context,
                self.handoff,
            ),
        )

        tight_context = deepcopy(self.context_extension)
        tight_context["budget"]["max_search_trace_entries"] = 1
        refresh_extension_digest(tight_context)
        self.assertEqual(
            "DR-CAPTURE-BUDGET-001",
            result_semantic_error(
                self.result_extension,
                tight_context,
                self.context,
                self.handoff,
            ),
        )

    def test_rejects_null_and_evidence_gap_reference_drift(self):
        """Exercise null projection and Evidence Gap assessment branches."""
        bad_null = deepcopy(self.result_extension)
        bad_null["null_results"][0]["handoff_projection"]["output_id"] = (
            "OBS-MISSING"
        )
        refresh_extension_digest(bad_null)
        self.assertEqual(
            "DR-NULL-001",
            result_semantic_error(
                bad_null,
                self.context_extension,
                self.context,
                self.handoff,
            ),
        )

        missing_gap = deepcopy(self.result_extension)
        missing_gap["evidence_gap_assessments"] = []
        refresh_extension_digest(missing_gap)
        self.assertEqual(
            "DR-EVIDENCE-GAP-001",
            result_semantic_error(
                missing_gap,
                self.context_extension,
                self.context,
                self.handoff,
            ),
        )


if __name__ == "__main__":
    unittest.main()
