from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch

from plugins.local_application import LocalApplicationError
from plugins.local_application.writer_composition_history_service import WriterCompositionHistoryService
import issue80_writer_composition_suite as issue80
from research_package_acceptance_support import ResearchPackageAcceptanceSupport


class Issue177WriterHistoryTests(ResearchPackageAcceptanceSupport):
    _proposal = issue80.Issue80WriterCompositionTests._proposal

    def test_wlb1_revision_history_can_exceed_legacy_ceiling_and_old_versions_remain_exact(self):
        facade, case = self._build()
        try:
            current = facade.capture_writer_composition(
                case["package_id"], self._proposal(case, composition_id="COMP-WLB-REV")
            )["composition"]
            first_digest = current["composition_digest"]
            for revision in range(2, 65):
                proposal = self._proposal(case, composition_id=current["composition_id"], base=current)
                proposal["sections"][0]["purpose"] = f"Revision {revision} framing."
                current = facade.capture_writer_composition(case["package_id"], proposal)["composition"]
            self.assertEqual(current["version"], 64)

            next_proposal = self._proposal(case, composition_id=current["composition_id"], base=current)
            next_proposal["sections"][0]["purpose"] = "Revision 65 framing."

            original_capture = WriterCompositionHistoryService.capture

            def legacy_lifetime_bound(service, package_id, value):
                info = service._latest_version_info(str(value.get("composition_id")))
                if info is not None and int(info["version"]) >= 64:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-COMPOSITION-BOUND-001",
                        "composition version bound exceeded",
                    )
                return original_capture(service, package_id, value)

            with patch.object(WriterCompositionHistoryService, "capture", legacy_lifetime_bound):
                with self.assertRaises(LocalApplicationError) as bounded:
                    facade.capture_writer_composition(case["package_id"], next_proposal)
            self.assertEqual(bounded.exception.code, "APPLICATION-WRITER-COMPOSITION-BOUND-001")

            current = facade.capture_writer_composition(case["package_id"], next_proposal)["composition"]
            self.assertEqual(current["version"], 65)
            self.assertEqual(
                facade.show_writer_composition(current["composition_id"], 1)["composition"]["composition_digest"],
                first_digest,
            )
            self.assertEqual(
                facade.show_writer_composition(current["composition_id"], 65)["composition"]["base_version"],
                64,
            )
        finally:
            facade.close()

    def test_wlb2_more_than_64_series_are_valid_while_list_stays_bounded(self):
        facade, case = self._build()
        try:
            created = []
            for index in range(65):
                composition = facade.capture_writer_composition(
                    case["package_id"],
                    self._proposal(case, composition_id=f"COMP-WLB-SERIES-{index:03d}"),
                )["composition"]
                created.append(composition["composition_id"])
            listed = facade.list_writer_compositions()
            self.assertEqual(len(listed["compositions"]), 64)
            self.assertTrue(listed["truncated"])
            self.assertEqual(
                facade.show_writer_composition(created[-1], 1)["composition"]["composition_id"],
                created[-1],
            )
        finally:
            facade.close()

    def test_wlb3_wlb4_exact_selection_retry_is_idempotent_but_real_changes_are_events(self):
        facade, case = self._build()
        try:
            v1 = facade.capture_writer_composition(
                case["package_id"], self._proposal(case, composition_id="COMP-WLB-SELECT")
            )["composition"]
            edit = self._proposal(case, composition_id=v1["composition_id"], base=v1)
            edit["sections"][0]["purpose"] = "Second version for selection history."
            v2 = facade.capture_writer_composition(case["package_id"], edit)["composition"]

            first = facade.select_writer_composition(v1["composition_id"], 1, v1["composition_digest"])
            retry = facade.select_writer_composition(v1["composition_id"], 1, v1["composition_digest"])
            self.assertFalse(first["selection_reused"])
            self.assertTrue(retry["selection_reused"])
            self.assertEqual(retry["selection"], first["selection"])

            facade.select_writer_composition(v1["composition_id"], 2, v2["composition_digest"])
            duplicate_v2 = facade.select_writer_composition(v1["composition_id"], 2, v2["composition_digest"])
            self.assertTrue(duplicate_v2["selection_reused"])
            facade.select_writer_composition(v1["composition_id"], 1, v1["composition_digest"])

            shown = facade.show_writer_composition(v1["composition_id"], 2)["selection"]
            self.assertEqual(shown["history_total"], 3)
            self.assertFalse(shown["truncated"])
            self.assertEqual([event["version"] for event in shown["history"]], [1, 2, 1])
        finally:
            facade.close()

    def test_wlb6_selection_history_can_exceed_legacy_ceiling_but_show_is_bounded(self):
        facade, case = self._build()
        try:
            v1 = facade.capture_writer_composition(
                case["package_id"], self._proposal(case, composition_id="COMP-WLB-HISTORY")
            )["composition"]
            edit = self._proposal(case, composition_id=v1["composition_id"], base=v1)
            edit["sections"][0]["purpose"] = "Alternate selection target."
            v2 = facade.capture_writer_composition(case["package_id"], edit)["composition"]

            facade.select_writer_composition(v1["composition_id"], 1, v1["composition_digest"])
            for sequence in range(2, 258):
                target = v2 if sequence % 2 == 0 else v1
                facade.select_writer_composition(
                    v1["composition_id"], target["version"], target["composition_digest"]
                )

            shown = facade.show_writer_composition(v1["composition_id"], 2)["selection"]
            self.assertEqual(shown["history_total"], 257)
            self.assertTrue(shown["truncated"])
            self.assertEqual(len(shown["history"]), 256)
            before = shown["history_total"]
            latest = shown["selected"]
            retried = facade.select_writer_composition(
                v1["composition_id"], latest["version"], latest["digest"]
            )
            self.assertTrue(retried["selection_reused"])
            self.assertEqual(
                facade.show_writer_composition(v1["composition_id"], 2)["selection"]["history_total"],
                before,
            )
        finally:
            facade.close()

    def test_wlb5_ablation_base_version_guard_remains_fail_closed(self):
        facade, case = self._build()
        try:
            v1 = facade.capture_writer_composition(
                case["package_id"], self._proposal(case, composition_id="COMP-WLB-STALE")
            )["composition"]
            v2_proposal = self._proposal(case, composition_id=v1["composition_id"], base=v1)
            v2_proposal["sections"][0]["purpose"] = "Second version."
            v2 = facade.capture_writer_composition(case["package_id"], v2_proposal)["composition"]

            stale = self._proposal(case, composition_id=v1["composition_id"], base=v1)
            stale["sections"][0]["purpose"] = "Stale concurrent edit."
            with self.assertRaises(LocalApplicationError) as rejected:
                facade.capture_writer_composition(case["package_id"], stale)
            self.assertEqual(rejected.exception.code, "APPLICATION-WRITER-COMPOSITION-STALE-001")

            with patch.object(WriterCompositionHistoryService, "_validate_revision_base", return_value=None):
                invalid = facade.capture_writer_composition(case["package_id"], deepcopy(stale))["composition"]
            self.assertEqual(invalid["version"], 3)
            self.assertEqual(invalid["base_version"], 1)
            self.assertEqual(invalid["base_digest"], v1["composition_digest"])
            self.assertNotEqual(invalid["base_digest"], v2["composition_digest"])

            with self.assertRaises(LocalApplicationError) as restored:
                facade.capture_writer_composition(case["package_id"], stale)
            self.assertEqual(restored.exception.code, "APPLICATION-WRITER-COMPOSITION-STALE-001")
        finally:
            facade.close()
