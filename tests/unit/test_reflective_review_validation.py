"""Exercise the manual comparison helper through PowerShell, never a model (#452)."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

CI_WINDOWS = True
ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/Invoke-ReflectiveReviewValidation.ps1"
PWSH = shutil.which("pwsh")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@unittest.skipUnless(PWSH, "PowerShell 7 is required; the Windows CI lane supplies it")
class ReflectiveReviewValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_tmp = tempfile.TemporaryDirectory(prefix="rr452-fixture-")
        cls.base = Path(cls.base_tmp.name)
        cls.prepared = cls.base / "prepared"
        settings = cls.base / "settings.json"
        write_json(settings, {"reasoning_effort": "high", "other": {"z": 1, "a": 2}})
        cls.invoke(
            cls.prepared,
            "prepare",
            "-Model",
            "test-model",
            "-Provider",
            "test-provider",
            "-SettingsFile",
            str(settings),
        )
        cls.complete_setup(cls.prepared, cls.base)
        cls.frozen = cls.base / "frozen"
        shutil.copytree(cls.prepared, cls.frozen)
        cls.invoke(cls.frozen, "freeze")

    @classmethod
    def tearDownClass(cls):
        cls.base_tmp.cleanup()

    @staticmethod
    def invoke(run: Path | str, action: str, *args: str, fails: str | None = None):
        result = subprocess.run(
            [
                PWSH,
                "-NoProfile",
                "-File",
                str(HELPER),
                "-Action",
                action,
                "-RunRoot",
                str(run),
                *args,
            ],
            cwd=ROOT,
            capture_output=True,
            encoding="utf-8",
            timeout=180,
        )
        if fails is not None:
            if result.returncode == 0 or fails not in result.stderr:
                raise AssertionError(f"Expected {fails!r}: {result.stdout}\n{result.stderr}")
            return result
        if result.returncode:
            raise AssertionError(f"{action}: {result.stdout}\n{result.stderr}")
        return json.loads(result.stdout)

    @staticmethod
    def complete_setup(run: Path, directory: Path):
        setup = read_json(run / "setup.json")
        manifest = read_json(run / "manifest.json")
        setup.update(
            confirmed_by="test-only",
            confirmed_at="2026-10-21T00:00:00+09:00",
            provider_consent=True,
        )
        for case in manifest["cases"]:
            history = directory / f"{case['id']}-history.txt"
            # Deliberately synthetic test data; never submitted as real comparison evidence.
            history.write_text(
                f"SYNTHETIC TEST ONLY\n{case['request']}\nTool: fixture read\nOutput: fixture\n"
                f"{case['target']}\nHost justification: fixture\n",
                encoding="utf-8",
            )
            setup["histories"][case["id"]] = {
                "path": str(history),
                "disposable_workspace": "synthetic-test-only",
                **dict.fromkeys(
                    [
                        "real_transcript",
                        "request_near_start",
                        "tools_and_outputs",
                        "exact_target",
                        "host_justification",
                        "no_expected_findings",
                    ],
                    True,
                ),
            }
        write_json(run / "setup.json", setup)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rr452-test-")
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.run = self.work / "run"
        shutil.copytree(self.frozen, self.run)
        self.serial = 0

    def call(self, action: str, *args: str, fails: str | None = None):
        return self.invoke(self.run, action, *args, fails=fails)

    def step(self, recheck=False):
        return self.call("Next", *(["-Recheck"] if recheck else []))

    def import_raw(self, step, raw, *, fails=None, **overrides):
        self.serial += 1
        raw_path = self.work / f"raw-{self.serial}.txt"
        raw_path.write_bytes(raw if isinstance(raw, bytes) else raw.encode("utf-8"))
        record = dict(step["record"])
        if record["kind"] != "disposition":
            record.update(
                call_id=f"call-{self.serial}",
                conversation_id=f"conversation-{self.serial}",
                fresh_context=True,
                only_supplied_input=True,
                provider_consent=True,
                elapsed_seconds=1.25,
                cost=None,
                cost_unknown_reason="not available in this host",
            )
        record.update(raw_path=str(raw_path), **overrides)
        path = self.work / f"record-{self.serial}.json"
        write_json(path, record)
        return self.call("Import", "-RecordPath", str(path), fails=fails)

    @staticmethod
    def review(step, findings=None):
        return json.dumps(
            {
                "target_version": step["target_version"],
                "target_sha256": step["target_sha256"],
                "findings": findings or [],
            }
        )

    @staticmethod
    def finding(route="explanation"):
        return {
            "location": "target",
            "reference": "original request",
            "lens": "purpose",
            "problem": "synthetic test issue",
            "minimal_fix": "synthetic test change",
            "return": route,
            "unreviewed_scope": "none",
        }

    def disposition(self, outcome="keep", decisions=None):
        return self.import_raw(
            self.step(),
            json.dumps(
                {
                    "outcome": outcome,
                    "reason": "test-only host decision",
                    "decisions": decisions or [],
                }
            ),
        )

    def test_inputs_are_self_contained_and_repeatable_without_scorer_material(self):
        other = self.work / "other"
        shutil.copytree(self.prepared, other)
        self.invoke(other, "Freeze")
        manifest = read_json(self.run / "manifest.json")
        self.assertEqual(32, len(manifest["order"]))
        self.assertEqual({"round": 1, "case": "RR1", "condition": "B"}, manifest["order"][0])
        self.assertEqual({"round": 2, "case": "RR8", "condition": "B"}, manifest["order"][16])
        cases = {c["id"]: c for c in manifest["cases"]}
        for key in ["facts", "state"]:
            self.assertEqual(cases["RR2"][key], cases["RR5"][key])
            self.assertEqual(cases["RR2"][key], cases["RR8"][key])
        for case in cases.values():
            directory = self.run / "inputs" / case["id"]
            self.assertEqual(
                case["target_sha256"],
                hashlib.sha256((directory / "target.txt").read_bytes()).hexdigest(),
            )
            c = (directory / "C.txt").read_text(encoding="utf-8")
            b = (directory / "B.txt").read_text(encoding="utf-8")
            self.assertTrue(b.startswith(c))
            for excluded in [
                "as in RR2",
                "## RR",
                "Scorer-only",
                "expected findings",
                "RR5, the degradation control",
            ]:
                self.assertNotIn(excluded, c)
            self.assertIn(case["request"], c)
            for name in ["target.txt", "case.txt", "B.txt", "C.txt", "history.txt"]:
                self.assertEqual(
                    (directory / name).read_bytes(),
                    (other / "inputs" / case["id"] / name).read_bytes(),
                )

    def test_freeze_requires_consent_real_history_and_exact_target(self):
        for field, value, message in [
            ("provider_consent", False, "Provider consent"),
            ("real_transcript", False, "History confirmation missing"),
            ("path", str(self.work / "bad-history.txt"), "lacks exact request or target"),
        ]:
            with self.subTest(field=field):
                other = self.work / field
                shutil.copytree(self.prepared, other)
                (self.work / "bad-history.txt").write_text(
                    "SYNTHETIC BAD HISTORY", encoding="utf-8"
                )
                setup = read_json(other / "setup.json")
                if field == "provider_consent":
                    setup[field] = value
                else:
                    setup["histories"]["RR8"][field] = value
                write_json(other / "setup.json", setup)
                self.invoke(other, "Freeze", fails=message)
                self.assertFalse((other / "frozen.json").exists())
                self.assertFalse((other / "inputs/RR1/history.txt").exists())

    def test_no_overwrites_input_tampering_and_outside_repo_boundary(self):
        self.call(
            "Prepare",
            "-Model",
            "m",
            "-Provider",
            "p",
            "-SettingsFile",
            str(self.base / "settings.json"),
            fails="already exists",
        )
        self.call("Freeze", fails="Already frozen")
        self.invoke(ROOT / "dist/rr-test-must-not-exist", "Prepare", fails="outside the repository")
        step = self.step()
        self.assertEqual(step, self.step())
        self.assertEqual(step, self.invoke(str(self.run) + "/", "Next"))
        Path(step["input_path"]).write_text("changed", encoding="utf-8")
        self.call("Next", fails="Pending input changed")
        (self.run / "inputs/RR1/target.txt").write_text("changed", encoding="utf-8")
        self.call("Validate", fails="Changed or missing evidence")

    def test_missing_last_event_is_detected_by_the_journal(self):
        step = self.step()
        self.import_raw(step, self.review(step))
        event = (self.run / "events/0001").resolve()
        self.assertTrue(event.is_relative_to(self.work.resolve()))
        shutil.rmtree(event)
        self.call("Validate", fails="Event journal mismatch")

    def test_malformed_retry_preserves_first_output_and_valid_empty_findings(self):
        first = self.step()
        raw = b"not JSON\r\n"
        self.assertEqual("malformed", self.import_raw(first, raw)["effective_status"])
        retry = self.step()
        self.assertEqual("malformed_retry", retry["record"]["reason"])
        self.assertEqual(first["target_sha256"], retry["target_sha256"])
        self.assertEqual("ok", self.import_raw(retry, self.review(retry))["effective_status"])
        self.disposition()
        self.assertEqual("C", self.step()["tuple"]["condition"])
        self.assertEqual(raw, (self.run / "events/0001/raw.txt").read_bytes())
        assessment = self.call("Validate")
        output = assessment["rounds"][0]["outputs"][1]
        self.assertTrue(output["execution_valid"])
        self.assertEqual(first["target_sha256"], output["output_sha256"])
        self.assertEqual("INCOMPLETE", assessment["status"])
        self.call(
            "Import",
            "-RecordPath",
            str(self.work / "record-1.json"),
            fails="frozen execution order",
        )

    def test_empty_review_is_preserved_and_uses_the_retry_budget(self):
        first = self.step()
        self.assertEqual("malformed", self.import_raw(first, b"")["effective_status"])
        self.assertEqual(b"", (self.run / "events/0001/raw.txt").read_bytes())
        retry = self.step()
        self.assertEqual("malformed_retry", retry["record"]["reason"])
        self.assertEqual("malformed", self.import_raw(retry, b"")["effective_status"])
        self.assertEqual("C", self.step()["tuple"]["condition"])
        self.assertFalse(self.call("Validate")["rounds"][0]["outputs"][1]["execution_valid"])

    def test_failures_are_explicit_and_do_not_become_passes(self):
        scenarios = [
            ({"status": "timeout", "reason": "host timeout"}, "", "timeout"),
            ({"status": "not_run", "reason": "operator cancelled"}, "", "not_run"),
            ({"model": "different-model"}, None, "settings_mismatch"),
            ({"fresh_context": False}, None, "isolation_unconfirmed"),
            (
                {},
                '{"target_version":"wrong","target_sha256":"wrong","findings":[]}',
                "wrong_target",
            ),
        ]
        for index, (overrides, raw, expected) in enumerate(scenarios):
            with self.subTest(status=expected):
                self.run = self.work / f"failure-{index}"
                shutil.copytree(self.frozen, self.run)
                step = self.step()
                result = self.import_raw(
                    step, raw if raw is not None else self.review(step), **overrides
                )
                self.assertEqual(expected, result["effective_status"])
                self.assertEqual("C", self.step()["tuple"]["condition"])
                output = self.call("Validate")["rounds"][0]["outputs"][1]
                self.assertFalse(output["execution_valid"])
                self.assertIsNone(output["output_sha256"])

    def test_revision_recheck_binding_context_reuse_and_finite_budget(self):
        review = self.step()
        self.import_raw(review, self.review(review, [self.finding()]))
        self.disposition(
            "revise", [{"finding": 1, "decision": "accepted", "reason": "test reason"}]
        )
        revision = self.step()
        self.assertEqual("revision", revision["record"]["kind"])
        self.assertNotIn(
            "Frozen working transcript", Path(revision["input_path"]).read_text(encoding="utf-8")
        )
        self.import_raw(
            revision,
            "Synthetic revised target.\r\n",
            conversation_id="conversation-1",
            fails="Conversation reused",
        )
        self.import_raw(revision, b"Synthetic revised target.\r\n")
        recheck = self.step(recheck=True)
        self.assertEqual("RR1-v2", recheck["target_version"])
        self.assertEqual(digest("Synthetic revised target.\n"), recheck["target_sha256"])
        self.assertNotEqual(review["target_sha256"], recheck["target_sha256"])
        self.import_raw(recheck, self.review(recheck, [self.finding()]))
        step = self.step()
        self.import_raw(
            step,
            json.dumps(
                {
                    "outcome": "revise",
                    "reason": "test",
                    "decisions": [{"finding": 1, "decision": "accepted", "reason": "test"}],
                }
            ),
            fails="unused revision budget",
        )
        self.disposition(
            "keep", [{"finding": 1, "decision": "rejected", "reason": "test: revision preserved"}]
        )
        self.call("Next", "-Recheck", fails="No recheck budget")
        self.call(
            "Import",
            "-RecordPath",
            str(self.work / "record-5.json"),
            fails="frozen execution order",
        )
        (self.run / "events/0001/raw.txt").write_text("tampered", encoding="utf-8")
        self.call("Validate", fails="Changed or missing evidence")

    def test_input_binding_metrics_dispositions_and_research_return(self):
        step = self.step()
        self.import_raw(
            step, self.review(step), input_sha256="wrong", fails="Input digest mismatch"
        )
        self.import_raw(
            step,
            self.review(step),
            elapsed_seconds=None,
            elapsed_unknown_reason="",
            fails="elapsed_unknown_reason",
        )
        self.import_raw(step, self.review(step, [self.finding("research")]))
        disposition = self.step()
        self.import_raw(
            disposition, '{"outcome":"keep","reason":"test","decisions":[]}', fails="Every finding"
        )
        self.import_raw(
            disposition,
            json.dumps(
                {
                    "outcome": "revise",
                    "reason": "test",
                    "decisions": [{"finding": 1, "decision": "accepted", "reason": "test"}],
                }
            ),
            fails="return path",
        )
        self.disposition(
            "research", [{"finding": 1, "decision": "accepted", "reason": "return to research"}]
        )
        self.assertEqual("C", self.step()["tuple"]["condition"])
        self.assertFalse(self.call("Validate")["rounds"][0]["outputs"][1]["execution_valid"])

    def test_two_round_human_scores_and_reports_with_negative_controls(self):
        # Keep one pwsh process for the 64 review/disposition imports. Every call
        # still invokes the real public script and replays its on-disk evidence.
        driver = self.work / "simulate.ps1"
        driver.write_text(
            r"""param($Helper, $Run, $Work)
$ErrorActionPreference = 'Stop'
$i = 0
while ($true) {
    $step = (& $Helper -Action Next -RunRoot $Run) | ConvertFrom-Json -AsHashtable
    if ($step.status -eq 'CALLS_RECORDED') { break }
    $i++
    $meta = $step.record
    $raw = if ($meta.kind -eq 'review') {
        @{ target_version = $step.target_version; target_sha256 = $step.target_sha256; findings = @() }
    } else { @{ decisions = @(); outcome = 'keep'; reason = 'SYNTHETIC TEST ONLY' } }
    $rawPath = Join-Path $Work "batch-raw-$i.json"
    $raw | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $rawPath -Encoding utf8NoBOM
    $meta.raw_path = $rawPath
    if ($meta.kind -eq 'review') {
        $meta.call_id = "batch-call-$i"; $meta.conversation_id = "batch-context-$i"
        $meta.fresh_context = $true; $meta.only_supplied_input = $true; $meta.provider_consent = $true
        $meta.elapsed_seconds = 1; $meta.cost_unknown_reason = 'SYNTHETIC TEST ONLY'
    }
    $recordPath = Join-Path $Work "batch-record-$i.json"
    $meta | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $recordPath -Encoding utf8NoBOM
    & $Helper -Action Import -RunRoot $Run -RecordPath $recordPath | Out-Null
}
""",
            encoding="utf-8",
        )
        result = subprocess.run(
            [PWSH, "-NoProfile", "-File", str(driver), str(HELPER), str(self.run), str(self.work)],
            cwd=ROOT,
            capture_output=True,
            encoding="utf-8",
            timeout=300,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        status = self.call("Validate")
        self.assertEqual("INCOMPLETE", status["status"])
        targets = {
            c["id"]: c["target_sha256"] for c in read_json(self.run / "manifest.json")["cases"]
        }
        for round_number in [1, 2]:
            path = self.run / f"round-{round_number}/scores.json"
            scores = read_json(path)
            for score in scores:
                score.update(
                    output_sha256=targets[score["case"]],
                    scorer="hirsaeki",
                    scored_at="2026-10-21T00:00:00+09:00",
                    purpose="FAIL"
                    if score["condition"] == "A" and score["case"] != "RR5"
                    else "PASS",
                    meaning="PASS",
                    purpose_reason="SYNTHETIC TEST ONLY",
                    meaning_reason="SYNTHETIC TEST ONLY",
                    observation_note="SYNTHETIC TEST ONLY; these are not real quality scores",
                    observations=dict.fromkeys(score["observations"], False),
                )
            write_json(path, scores)
            status = self.call("Validate")
            if round_number == 1:
                self.assertEqual("INCOMPLETE", status["status"])
                self.assertTrue(status["provisional"])
        self.assertEqual("STAGE2_CONSIDERATION_CRITERIA_MET", status["status"])
        self.assertFalse(status["provisional"])
        self.assertEqual(7, status["rounds"][0]["improved_cases"])
        self.assertEqual({"purpose": 8, "meaning": 8}, status["rounds"][0]["lens_totals"]["C"])
        report = self.work / "report"
        self.call("Report", "-ReportDirectory", str(report))
        self.assertEqual(32, len(read_json(report / "report.json")["calls"]))
        self.call("Report", "-ReportDirectory", str(report), fails="already exists")
        path = self.run / "round-2/scores.json"
        original = read_json(path)
        for lens, observation, criterion in [
            ("purpose", None, "purpose_not_worse_than_B"),
            ("meaning", None, "meaning_not_worse_than_B"),
            (None, "new_unsupported_claim", "no_new_errors"),
            (None, "new_authority_error", "no_new_errors"),
            (None, "new_dropped_condition", "no_new_errors"),
            (None, "degradation", "RR5_preserved"),
        ]:
            with self.subTest(lens=lens, observation=observation):
                changed = json.loads(json.dumps(original))
                row = next(s for s in changed if s["case"] == "RR5" and s["condition"] == "C")
                if lens:
                    row[lens] = "FAIL"
                else:
                    row["observations"][observation] = True
                    underlying = {
                        "new_unsupported_claim": "unsupported_claim",
                        "new_authority_error": "authority_error",
                        "new_dropped_condition": "missing_condition",
                    }.get(observation)
                    if underlying:
                        row["observations"][underlying] = True
                write_json(path, changed)
                status = self.call("Validate")
                self.assertEqual("CRITERIA_NOT_REPRODUCED", status["status"])
                self.assertFalse(status["rounds"][1]["criteria"][criterion])
        write_json(path, original[:-1])
        self.assertEqual("INCOMPLETE", self.call("Validate")["status"])


if __name__ == "__main__":
    unittest.main()
