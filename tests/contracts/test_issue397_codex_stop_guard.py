from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
HOOK_CONFIG = ROOT / ".codex" / "hooks.json"
HOOK_SCRIPT = ROOT / ".codex" / "hooks" / "research_conversation_stop_guard.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location("research_conversation_stop_guard", HOOK_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_transcript(path: Path, user_prompt: str) -> None:
    items = [
        {"type": "session_meta", "payload": {"id": "test"}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": user_prompt}],
            },
        },
    ]
    path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in items) + "\n", encoding="utf-8")


class CodexStopGuardContractTests(unittest.TestCase):
    def test_repo_local_stop_hook_is_configured(self):
        config = json.loads(HOOK_CONFIG.read_text(encoding="utf-8"))
        stop = config["hooks"]["Stop"]
        self.assertEqual(len(stop), 1)
        command = stop[0]["hooks"][0]["command"]
        self.assertEqual(command, "python .codex/hooks/research_conversation_stop_guard.py")
        self.assertTrue(HOOK_SCRIPT.is_file())

    def test_exact_u2_leak_is_blocked(self):
        guard = _load_guard()
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "rollout.jsonl"
            _write_transcript(transcript, "この問いを正式な研究問いとして採用してよい？")
            payload = {
                "stop_hook_active": False,
                "transcript_path": str(transcript),
                "last_assistant_message": (
                    "この問いを採用してよい？\n\n"
                    "[適用中の調査手順](/D:/repo/skills/research-conversation/SKILL.md) が "
                    "“Bind a human answer only to that issued request” を求めている。"
                ),
            }
            blocked, labels, diagnostic = guard.evaluate(payload)
            self.assertTrue(blocked)
            self.assertFalse(diagnostic)
            self.assertIn("skill-md", labels)
            self.assertIn("binding-rule", labels)

    def test_named_writer_documents_pdf_skill_narration_is_blocked(self):
        guard = _load_guard()
        payload = {
            "stop_hook_active": False,
            "last_assistant_message": "Writerスキルで草稿を作り、Documents Skill と PDF Skill で確認する。",
        }
        blocked, labels, diagnostic = guard.evaluate(payload)
        self.assertTrue(blocked)
        self.assertFalse(diagnostic)
        self.assertIn("named-skill", labels)

    def test_clean_domain_language_passes(self):
        guard = _load_guard()
        payload = {
            "stop_hook_active": False,
            "last_assistant_message": "指定3資料を確認して、根拠・限界・未解決点を整理します。",
        }
        self.assertEqual(guard.evaluate(payload), (False, [], False))

    def test_explicit_diagnostic_request_allows_internal_terms(self):
        guard = _load_guard()
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "rollout.jsonl"
            _write_transcript(transcript, "内部ではどのSkillとパスを使っているの？")
            payload = {
                "stop_hook_active": False,
                "transcript_path": str(transcript),
                "last_assistant_message": "skills/research-conversation/SKILL.md を使っています。",
            }
            blocked, labels, diagnostic = guard.evaluate(payload)
            self.assertFalse(blocked)
            self.assertTrue(labels)
            self.assertTrue(diagnostic)


    def test_generic_path_word_does_not_disable_guard(self):
        guard = _load_guard()
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "rollout.jsonl"
            _write_transcript(transcript, "What path should we take to answer this research question?")
            payload = {
                "stop_hook_active": False,
                "transcript_path": str(transcript),
                "last_assistant_message": "Use skills/research-conversation/SKILL.md for this step.",
            }
            blocked, labels, diagnostic = guard.evaluate(payload)
            self.assertTrue(blocked)
            self.assertTrue(labels)
            self.assertFalse(diagnostic)

    def test_clean_response_does_not_read_transcript(self):
        guard = _load_guard()
        payload = {
            "stop_hook_active": False,
            "transcript_path": "should-not-be-read.jsonl",
            "last_assistant_message": "指定3資料を確認して、根拠・限界・未解決点を整理します。",
        }
        with mock.patch.object(guard, "latest_user_prompt", side_effect=AssertionError("unexpected transcript read")):
            self.assertEqual(guard.evaluate(payload), (False, [], False))

    def test_latest_user_prompt_scans_from_transcript_tail(self):
        guard = _load_guard()
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "rollout.jsonl"
            older = [
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": f"old-{index}"}],
                    },
                }
                for index in range(1000)
            ]
            latest = {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "内部ではどのSkillを使っているの？"}],
                },
            }
            transcript.write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in [*older, latest]) + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(guard.json, "loads", wraps=guard.json.loads) as loads:
                self.assertEqual(guard.latest_user_prompt(str(transcript)), "内部ではどのSkillを使っているの？")
                self.assertEqual(loads.call_count, 1)

    def test_stop_hook_active_prevents_rewrite_loop(self):
        guard = _load_guard()
        payload = {
            "stop_hook_active": True,
            "last_assistant_message": "research-conversation/SKILL.md を使う。",
        }
        blocked, labels, diagnostic = guard.evaluate(payload)
        self.assertFalse(blocked)
        self.assertTrue(labels)
        self.assertFalse(diagnostic)

    def test_uat_requires_live_codex_hook_evidence(self):
        runbook = (ROOT / "docs" / "architecture" / "misco-integrated-acceptance.md").read_text(encoding="utf-8")
        for phrase in (
            "### Codex Stop-hook evidence",
            "RESEARCH_LOOM_CODEX_HOOK_LOG",
            "At least one `Stop` event from the UAT session must be present",
            "host-integration blocker",
            "do not award G4 PASS merely",
            "Codex-specific",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, runbook)

    def test_command_emits_block_decision_and_optional_probe_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "hook.jsonl"
            payload = {
                "hook_event_name": "Stop",
                "session_id": "s1",
                "turn_id": "t1",
                "stop_hook_active": False,
                "last_assistant_message": "[手順](skills/research-conversation/SKILL.md) に従う。",
            }
            env = os.environ.copy()
            env["RESEARCH_LOOM_CODEX_HOOK_LOG"] = str(log)
            proc = subprocess.run(
                [sys.executable, str(HOOK_SCRIPT)],
                input=json.dumps(payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                env=env,
                check=True,
            )
            output = json.loads(proc.stdout)
            self.assertEqual(output["decision"], "block")
            self.assertIn("Rewrite the final user-visible response", output["reason"])
            record = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
            self.assertTrue(record["blocked"])
            self.assertEqual(record["hook_event_name"], "Stop")


if __name__ == "__main__":
    unittest.main()
