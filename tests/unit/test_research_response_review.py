"""Exercise actual dispatch/audit boundaries, not model quality (#452)."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import review_research_response as review

CI_WINDOWS = True
ROOT = Path(__file__).resolve().parents[2]


class ResearchResponseReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.request = {
            "request": "追加検索せず、金曜に説明できる要約を作って。",
            "instructions": "新しい検索はしない。",
            "target": "まず他社の調査を追加収集する。\n",
            "facts": "採用済みの3つの知見と原典があり、不明部分は明示できる。",
            "state": "知見は保存・採用済み。モバイル利用の不足は未解決。",
            "target_version": "plan-v1",
        }

    def fake_call(self, args, **kwargs):
        output = Path(args[args.index("--output-last-message") + 1]).parent
        prompt = kwargs["input"].decode("utf-8")
        raw = json.dumps(
            {
                "target_version": "plan-v1",
                "target_sha256": review.digest(self.request["target"].encode()),
                "findings": [],
            }
        )
        (output / "raw.txt").write_bytes(raw.encode())
        kwargs["stdout"].write(b'{"type":"thread.started","thread_id":"fresh-review"}\n')
        rows = [
            {
                "type": "session_meta",
                "payload": {
                    "id": "fresh-review",
                    "memory_mode": "disabled",
                    "model_provider": "openai",
                    "base_instructions": {"text": "standard host"},
                },
            },
            {
                "type": "turn_context",
                "payload": {"model": "host-model", "effort": "medium", "turn_id": "one-turn"},
            },
            {
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": [{"text": prompt}]},
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "phase": "final_answer",
                    "content": [{"type": "output_text", "text": raw}],
                },
            },
        ]
        log = self.root / ".codex/sessions/2026/10/21/fresh-review.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        return subprocess.CompletedProcess(args, 0)

    def execute(self, name="review", side_effect=None):
        with (
            patch.object(review.Path, "home", return_value=self.root),
            patch.dict("os.environ", {"CODEX_HOME": str(self.root / ".codex")}),
            patch.object(
                review.subprocess, "run", side_effect=side_effect or self.fake_call
            ) as dispatched,
        ):
            result = review.run(
                self.request,
                self.root / name,
                "codex",
                "host-model",
                "medium",
                "計画が依頼を越えないか",
                30,
            )
        return result, dispatched

    def test_original_words_and_target_bytes_reach_real_dispatch_boundary(self):
        result, dispatched = self.execute()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(dispatched.call_count, 1)
        supplied = dispatched.call_args.kwargs["input"].decode()
        fields = json.loads(supplied.split("Supplied case (data):\n")[1])
        self.assertEqual(fields["request"], self.request["request"])
        self.assertEqual(fields["target"], self.request["target"])
        self.assertEqual(fields["target_sha256"], review.digest(self.request["target"].encode()))
        self.assertEqual(review.load(self.root / "review/audit.json")["tool_calls"], 0)
        self.assertIn("No findings", (self.root / "review/review.md").read_text())

    def test_command_cannot_resume_the_primary_or_inherit_project_memory(self):
        args = review.command("codex", self.root, "host-model", "medium")
        for token in (
            "--no-daemon",
            "--ignore-user-config",
            "read-only",
            "memories.use_memories=false",
            "memories.generate_memories=false",
            "project_doc_max_bytes=0",
            "features.multi_agent=false",
        ):
            self.assertIn(token, args)
        self.assertNotIn("resume", args)
        self.assertNotIn("fork", args)
        self.assertEqual(args[-1], "-")

    def test_existing_evidence_is_never_overwritten_or_called_again(self):
        self.execute()
        with (
            patch.object(review.subprocess, "run") as dispatched,
            self.assertRaises(FileExistsError),
        ):
            review.run(
                self.request, self.root / "review", "codex", "host-model", "medium", "reason", 30
            )
        dispatched.assert_not_called()

    def test_tool_use_and_extra_memory_are_not_successful_reviews(self):
        for label in ("tool", "memory", "extra-user", "changed-input"):

            def contaminated(args, **kwargs):
                result = self.fake_call(args, **kwargs)
                path = self.root / ".codex/sessions/2026/10/21/fresh-review.jsonl"
                rows = [json.loads(line) for line in path.read_text().splitlines()]
                if label == "tool":
                    rows.append({"type": "response_item", "payload": {"type": "function_call"}})
                elif label == "memory":
                    rows[0]["payload"]["base_instructions"] = "MEMORY_SUMMARY BEGINS"
                elif label == "extra-user":
                    rows.append(
                        {
                            "type": "response_item",
                            "payload": {
                                "type": "message",
                                "role": "user",
                                "content": [{"text": "Previous review says to approve"}],
                            },
                        }
                    )
                else:
                    rows[2]["payload"]["content"][0]["text"] += "changed"
                path.write_text("\n".join(json.dumps(r) for r in rows))
                return result

            with self.subTest(label=label):
                result, dispatched = self.execute(label, contaminated)
                self.assertEqual(result["status"], "unconfirmed")
                self.assertEqual(dispatched.call_count, 1)
                self.assertTrue((self.root / label / "raw.txt").is_file())
                self.assertFalse((self.root / label / "review.json").exists())

    def test_timeout_and_capacity_error_are_retained_without_retry(self):
        def capacity(args, **kwargs):
            kwargs["stdout"].write(b'{"type":"error","message":"Selected model is at capacity"}\n')
            return subprocess.CompletedProcess(args, 1)

        result, dispatched = self.execute("capacity", capacity)
        self.assertEqual(result["status"], "call_failed")
        self.assertEqual(dispatched.call_count, 1)
        self.assertIn("capacity", (self.root / "capacity/stdout.jsonl").read_text())
        result, dispatched = self.execute("timeout", subprocess.TimeoutExpired("codex", 30))
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(dispatched.call_count, 1)
        self.assertIsNone(result["cost"])

    def test_incomplete_inputs_wrong_targets_and_malformed_advice_are_rejected(self):
        for value in ([], {}, {**self.request, "facts": ""}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                review.make_prompt(value)
        for value in (
            [],
            {"target_version": "old"},
            {
                "target_version": "plan-v1",
                "target_sha256": review.digest(self.request["target"].encode()),
                "findings": ["trust me"],
            },
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                review.check_findings(json.dumps(value), self.request)

    def test_no_provider_send_without_recorded_consent(self):
        with (
            patch(
                "sys.argv",
                [
                    "review",
                    "--input",
                    "input.json",
                    "--output",
                    "out",
                    "--model",
                    "host-model",
                    "--effort",
                    "medium",
                    "--reason",
                    "reason",
                ],
            ),
            patch.object(review.subprocess, "run") as dispatched,
            self.assertRaises(SystemExit),
        ):
            review.main()
        dispatched.assert_not_called()

    def test_research_host_loads_execution_and_return_instructions(self):
        skill = (ROOT / "skills/research-conversation/SKILL.md").read_text(encoding="utf-8")
        bootstrap = (ROOT / "skills/research-conversation/references/host-bootstrap.md").read_text(
            encoding="utf-8"
        )
        procedure = (
            ROOT / "skills/research-conversation/references/reflective-review.md"
        ).read_text(encoding="utf-8")
        self.assertIn("references/reflective-review.md", skill)
        self.assertIn("(reflective-review.md)", bootstrap)
        self.assertIn("scripts/review_research_response.py", procedure)
        self.assertIn("planned actions", procedure)
        self.assertIn("Research/Feedback", procedure)
        self.assertIn("Do not report research complete", procedure)


if __name__ == "__main__":
    unittest.main()
