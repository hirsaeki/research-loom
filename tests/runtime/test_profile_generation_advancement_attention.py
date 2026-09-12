from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from unittest import mock

from core.conversation import ConversationRuntimeError
from plugins.local_application import LocalApplicationFacade
from plugins.local_application.application import EffectiveResearchAttentionProvider
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import test_external_desktop_research_intake as intake
from test_profile_generation_advancement import (
    GENERIC_NARRATIVE,
    OLD_EPS,
    ORGANIZATION,
    PUBLICATION,
    RESEARCH_BASE,
    RESEARCH_STRICT_NEXT,
    _run_cli,
)


class ProfileAdvancementAttentionTests(ResearchPackageAcceptanceSupport):
    def _write_structured_workspace_inputs(self):
        config = intake.bootstrap_config()
        cfg = self.root / "project-config-input.json"
        eps = self.root / "profiles-input.json"
        cfg.write_text(json.dumps(config), encoding="utf-8")
        eps.write_text(OLD_EPS.read_text(encoding="utf-8"), encoding="utf-8")
        return cfg, eps

    def _resolve(self):
        request = {
            "profile_manifest_files": [
                str(PUBLICATION),
                str(ORGANIZATION),
                str(RESEARCH_STRICT_NEXT),
                str(RESEARCH_BASE),
                str(GENERIC_NARRATIVE),
            ],
            "request_replacements": [{
                "from": {"profile_id": "fixture.narrative", "profile_type": "narrative", "version": "1.0.0"},
                "to": {"profile_id": "fixture.generic-narrative", "profile_type": "narrative", "version": "1.0.0"},
            }],
        }
        request_path = self.root / "resolve-request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        output = self.root / "resolved"
        code, result = _run_cli([
            "profile", "resolve", "--workspace", self.workspace,
            "--output", output, "--json", request_path,
        ])
        self.assertEqual(code, 0, result)
        return request, output

    def _advance(self, request, output):
        payload = {
            "project_config_file": str(output / "project-config.json"),
            "effective_profile_set_file": str(output / "effective-profile-set.json"),
            "profile_manifest_files": request["profile_manifest_files"],
            "origin": "issue-128-attention-regression",
        }
        path = self.root / "advance.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return _run_cli(["profile", "advance", "--workspace", self.workspace, "--json", path])

    def test_active_attention_survives_profile_advancement_without_rebinding_candidates(self):
        with LocalApplicationFacade.open_workspace(self.workspace) as facade:
            attention_map = facade.submit_action({
                "action_type": "research_attention.propose",
                "payload": {"additions": [{"statement": "Keep operator focus through Profile advancement."}]},
                "actor_id": "HUMAN-ATT-128",
            })["data"]["attention_map"]
            pending = facade.submit_action({
                "action_type": "research_attention.activate_candidate",
                "payload": {"attention_map_id": attention_map["map_id"]},
                "actor_id": "HUMAN-ATT-128",
            })
            confirmed = facade.submit_confirmation({
                "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                "actor_id": "HUMAN-ATT-128",
            })
            self.assertEqual(confirmed["status"], "SUCCEEDED")
            stale_candidate = facade.submit_action({
                "action_type": "research_attention.propose",
                "payload": {"additions": [{"statement": "Do not auto-rebind unapproved guidance."}]},
                "actor_id": "HUMAN-ATT-128",
            })["data"]["attention_map"]
            active_before = deepcopy(facade._application.attention_store.load_active(facade.project_id))

        request, output = self._resolve()
        code, advanced = self._advance(request, output)
        self.assertEqual(code, 0, advanced)
        self.assertEqual(advanced["result"], "ADVANCED")
        self.assertNotEqual(
            active_before["map"]["project_config"]["digest"],
            advanced["new_project_config_digest"],
        )

        code, resumed = _run_cli(["resume", "--workspace", self.workspace, "--json"])
        self.assertEqual(code, 0, resumed)
        with LocalApplicationFacade.open_workspace(self.workspace) as facade:
            self.assertEqual(facade._application.attention_store.load_active(facade.project_id), active_before)
            status = facade.submit_action({"action_type": "research_attention.status", "payload": {}})
            self.assertEqual(status["data"]["active_map"]["map_id"], active_before["map_id"])
            self.assertIn(
                "Keep operator focus through Profile advancement.",
                [item["statement"] for item in status["data"]["effective_attention"]],
            )
            pending_stale = facade.submit_action({
                "action_type": "research_attention.activate_candidate",
                "payload": {"attention_map_id": stale_candidate["map_id"]},
                "actor_id": "HUMAN-ATT-128",
            })
            with self.assertRaises(ConversationRuntimeError) as stale:
                facade.submit_confirmation({
                    "confirmation_request_id": pending_stale["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "HUMAN-ATT-128",
                })
            self.assertEqual(stale.exception.code, "ATTENTION-STALE-001")

        code, history = _run_cli(["profile", "history", "--workspace", self.workspace, "--json"])
        self.assertEqual(code, 0, history)
        self.assertEqual(len(history["events"]), 1)
        self.assertEqual(
            history["events"][0]["old_binding"]["project_config_digest"],
            active_before["map"]["project_config"]["digest"],
        )
        self.assertEqual(
            history["events"][0]["new_binding"]["project_config_digest"],
            advanced["new_project_config_digest"],
        )

        # Ablation: the old active map is accepted only because the append-only
        # advancement event proves the bounded old->new Project Config transition.
        events_root = self.workspace / ".research-loom" / "profile-history" / "events"
        event_path = next(events_root.rglob("PGA-*.json"))
        legacy_event = events_root / event_path.name
        event_path.replace(legacy_event)
        code, legacy_resume = _run_cli(["resume", "--workspace", self.workspace, "--json"])
        self.assertEqual(code, 0, legacy_resume)
        event_path = legacy_event
        hidden_event = event_path.with_suffix(".ablation")
        event_path.replace(hidden_event)
        try:
            code, stale_resume = _run_cli(["resume", "--workspace", self.workspace, "--json"])
            self.assertEqual(code, 2, stale_resume)
            self.assertEqual(stale_resume["issues"][0]["code"], "ATTENTION-STALE-001")
        finally:
            hidden_event.replace(event_path)
        code, resumed_again = _run_cli(["resume", "--workspace", self.workspace, "--json"])
        self.assertEqual(code, 0, resumed_again)

    def test_active_attention_rejects_noncanonical_history_digest_before_path_traversal(self):
        with LocalApplicationFacade.open_workspace(self.workspace) as facade:
            attention_map = facade.submit_action({
                "action_type": "research_attention.propose",
                "payload": {"additions": [{"statement": "Reject forged profile-history links."}]},
                "actor_id": "HUMAN-ATT-FORGED",
            })["data"]["attention_map"]
            pending = facade.submit_action({
                "action_type": "research_attention.activate_candidate",
                "payload": {"attention_map_id": attention_map["map_id"]},
                "actor_id": "HUMAN-ATT-FORGED",
            })
            confirmed = facade.submit_confirmation({
                "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                "actor_id": "HUMAN-ATT-FORGED",
            })
            self.assertEqual(confirmed["status"], "SUCCEEDED")

        request, output = self._resolve()
        code, advanced = self._advance(request, output)
        self.assertEqual(code, 0, advanced)
        target_digest = advanced["new_project_config_digest"]

        events_root = self.workspace / ".research-loom" / "profile-history" / "events"
        event_path = next(events_root.rglob("PGA-*.json"))
        event = json.loads(event_path.read_text(encoding="utf-8"))
        malicious_digest = "sha256:../../../outside-history"
        event["new_binding"]["project_config_digest"] = malicious_digest
        event_path.write_text(
            json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

        forged_dir = self.workspace / ".research-loom" / "outside-history"
        forged_dir.mkdir(parents=True, exist_ok=True)
        forged = deepcopy(event)
        forged["event_id"] = "PGA-FORGED-ESCAPE"
        forged["old_binding"]["project_config_digest"] = malicious_digest
        forged["new_binding"]["project_config_digest"] = target_digest
        (forged_dir / "PGA-FORGED-ESCAPE.json").write_text(
            json.dumps(forged, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

        code, stale = _run_cli(["resume", "--workspace", self.workspace, "--json"])
        self.assertEqual(code, 2, stale)
        self.assertEqual(stale["issues"][0]["code"], "ATTENTION-STALE-001")

    def test_profile_history_index_stops_glob_at_read_limit(self):
        history_root = self.root / "bounded-profile-history"
        events_root = history_root / "events"
        source_digest = "sha256:" + "1" * 64
        successor_digest = "sha256:" + "2" * 64
        target_digest = "sha256:" + "f" * 64
        source_dir = events_root / "by-source" / source_digest.removeprefix("sha256:")
        source_dir.mkdir(parents=True, exist_ok=True)
        event_path = source_dir / "PGA-BOUND.json"
        event_path.write_text(
            json.dumps({
                "event_type": "project_profile_generation_advanced",
                "project_id": "PRJ-BOUND",
                "old_binding": {"project_config_digest": source_digest},
                "new_binding": {"project_config_digest": successor_digest},
            }, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        provider = EffectiveResearchAttentionProvider(None, profile_history_root=history_root)
        real_glob = Path.glob
        observed = {"indexed_yields": 0}

        def bounded_glob(path: Path, pattern: str):
            if path == events_root and pattern == "PGA-*.json":
                return iter(())
            if path == source_dir and pattern == "PGA-*.json":
                def iterator():
                    for _ in range(4):
                        observed["indexed_yields"] += 1
                        yield event_path
                    raise AssertionError("bounded history traversal consumed beyond limit + 1")
                return iterator()
            return real_glob(path, pattern)

        with mock.patch.object(
            EffectiveResearchAttentionProvider,
            "_PROFILE_HISTORY_EVENT_READ_LIMIT",
            3,
        ), mock.patch.object(Path, "glob", new=bounded_glob):
            connected = provider._profile_generation_connects(
                project_id="PRJ-BOUND",
                source_config_digest=source_digest,
                target_config_digest=target_digest,
            )

        self.assertFalse(connected)
        self.assertEqual(observed["indexed_yields"], 4)

    def test_active_attention_accepts_profile_chain_longer_than_256_events(self):
        with LocalApplicationFacade.open_workspace(self.workspace) as facade:
            attention_map = facade.submit_action({
                "action_type": "research_attention.propose",
                "payload": {"additions": [{"statement": "Preserve long-running operator focus."}]},
                "actor_id": "HUMAN-ATT-LONG",
            })["data"]["attention_map"]
            pending = facade.submit_action({
                "action_type": "research_attention.activate_candidate",
                "payload": {"attention_map_id": attention_map["map_id"]},
                "actor_id": "HUMAN-ATT-LONG",
            })
            confirmed = facade.submit_confirmation({
                "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                "actor_id": "HUMAN-ATT-LONG",
            })
            self.assertEqual(confirmed["status"], "SUCCEEDED")
            source_digest = attention_map["project_config"]["digest"]

        request, output = self._resolve()
        code, advanced = self._advance(request, output)
        self.assertEqual(code, 0, advanced)
        target_digest = advanced["new_project_config_digest"]

        events_root = self.workspace / ".research-loom" / "profile-history" / "events"
        original_path = next(events_root.rglob("PGA-*.json"))
        template = json.loads(original_path.read_text(encoding="utf-8"))
        original_path.unlink()

        previous = source_digest
        for index in range(300):
            successor = target_digest if index == 299 else f"sha256:{index + 1:064x}"
            event = deepcopy(template)
            event["event_id"] = f"PGA-LONG-{index:04d}"
            event["old_binding"]["project_config_digest"] = previous
            event["new_binding"]["project_config_digest"] = successor
            source_dir = events_root / "by-source" / previous.removeprefix("sha256:")
            source_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / f"PGA-LONG-{index:04d}.json").write_text(
                json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            previous = successor

        code, resumed = _run_cli(["resume", "--workspace", self.workspace, "--json"])
        self.assertEqual(code, 0, resumed)
        with LocalApplicationFacade.open_workspace(self.workspace) as facade:
            status = facade.submit_action({"action_type": "research_attention.status", "payload": {}})
            self.assertEqual(status["data"]["active_map"]["map_id"], attention_map["map_id"])
