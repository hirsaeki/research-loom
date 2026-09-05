from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from core.runtime import CommitReceipt, StateTransitionRejected, TransitionAction, TransitionKind
from plugins.local_application.workspace import LocalWorkspace
from runtime_fixtures import make_request
from test_research_question_adoption import _bootstrap_config


ROOT = Path(__file__).resolve().parents[2]
PROFILE_FIXTURE = ROOT / "profiles/fixtures/valid/effective-profile-set.json"


def _profile_set(*, enforce_capture_digest: bool) -> dict:
    value = json.loads(PROFILE_FIXTURE.read_text(encoding="utf-8"))
    constraints = value["effective_constraints"]
    required = next(item for item in constraints if item["path"] == "evidence.capture.required_fields")
    required["value"] = ["capture_digest", "locator", "source_id"]
    if not enforce_capture_digest:
        required["value"] = ["locator", "source_id"]
    return value


def _open_workspace(root: Path, *, enforce_capture_digest: bool):
    config_path = root / "project-config.json"
    profile_path = root / "effective-profile-set.json"
    config_path.write_text(json.dumps(_bootstrap_config()), encoding="utf-8")
    profile_path.write_text(json.dumps(_profile_set(enforce_capture_digest=enforce_capture_digest)), encoding="utf-8")
    return LocalWorkspace.init(root / "workspace", config_path, profile_path)


def _source(project_id: str) -> dict:
    return {
        "schema_version": "0.1.0", "id": "SRC-PROFILE", "kind": "source", "revision": 0,
        "project_id": project_id, "source_type": "report", "canonical_locator": "fixture://profile/source",
    }


def _evidence(project_id: str, *, with_capture_digest: bool) -> dict:
    value = {
        "schema_version": "0.1.0", "id": "EVD-PROFILE", "kind": "evidence", "revision": 0,
        "project_id": project_id, "source_id": "SRC-PROFILE", "locator": "p.1",
        "statement": "Profile-bound evidence", "evidence_kind": "supporting",
        "verification_status": "unverified", "evidence_mode": "empirical", "limitations": [],
    }
    if with_capture_digest:
        value["capture_digest"] = "sha256:" + "1" * 64
    return value


class ProductionProfileConstraintEnforcementTests(unittest.TestCase):
    def _apply_evidence(self, opened, *, with_capture_digest: bool, suffix: str):
        state = opened.application.state_repository.load_state_view(opened.project_id, opened.application.state_repository.load_active_lineage_ref(opened.project_id))
        request = make_request(
            state,
            [
                TransitionAction(TransitionKind.CREATE_OBJECT, {"object": _source(opened.project_id)}),
                TransitionAction(TransitionKind.CREATE_OBJECT, {"object": _evidence(opened.project_id, with_capture_digest=with_capture_digest)}),
            ],
            suffix=suffix,
        )
        return state, opened.application.state_transition_service.apply(request)

    def test_workspace_profile_required_field_is_enforced_before_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            with _open_workspace(Path(temp), enforce_capture_digest=True) as opened:
                before, result = self._apply_evidence(opened, with_capture_digest=False, suffix="41")
                self.assertIsInstance(result, StateTransitionRejected)
                self.assertIn("RT-PROFILE-002", {issue.error_code for issue in result.issues})
                after = opened.application.state_repository.load_state_view(opened.project_id, before.lineage_ref)
                self.assertEqual(after.current_snapshot["content_digest"], before.current_snapshot["content_digest"])
                self.assertIsNone(after.latest_object("source", "SRC-PROFILE"))
                self.assertIsNone(after.latest_object("evidence", "EVD-PROFILE"))

    def test_workspace_profile_required_field_accepts_satisfying_input(self):
        with tempfile.TemporaryDirectory() as temp:
            with _open_workspace(Path(temp), enforce_capture_digest=True) as opened:
                _before, result = self._apply_evidence(opened, with_capture_digest=True, suffix="42")
                self.assertIsInstance(result, CommitReceipt)

    def test_ablation_changes_profile_result_but_not_core_floor(self):
        with tempfile.TemporaryDirectory() as temp:
            with _open_workspace(Path(temp), enforce_capture_digest=False) as opened:
                _before, result = self._apply_evidence(opened, with_capture_digest=False, suffix="43")
                self.assertIsInstance(result, CommitReceipt)

                state = opened.application.state_repository.load_state_view(opened.project_id, opened.application.state_repository.load_active_lineage_ref(opened.project_id))
                bad_artifact = {
                    "schema_version": "0.1.0", "id": "ART-CORE-FLOOR", "kind": "artifact", "revision": 0,
                    "project_id": opened.project_id, "role": "output", "lane": "publication",
                    "artifact_class": "input", "locator": "fixture://artifact/core-floor", "evidence_eligible": True,
                }
                rejected = opened.application.state_transition_service.apply(make_request(
                    state,
                    [TransitionAction(TransitionKind.CREATE_OBJECT, {"object": bad_artifact})],
                    suffix="44",
                ))
                self.assertIsInstance(rejected, StateTransitionRejected)
                self.assertIn("RT-CORE-FW-001", {issue.error_code for issue in rejected.issues})


if __name__ == "__main__":
    unittest.main()
