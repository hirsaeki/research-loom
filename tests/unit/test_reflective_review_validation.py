"""Exercise the manual comparison helper through PowerShell, never a model (#452)."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        cls.case_file = cls.base / "cases.json"
        cls.make_controlled_study(cls.case_file)
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
        if action.lower() == "prepare" and "-CaseFile" not in args:
            args = (*args, "-CaseFile", str(ReflectiveReviewValidationTests.case_file))
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
    def make_controlled_study(path: Path):
        contexts = []
        for number in range(1, 9):
            context = path.parent / f"RR{number}-context.txt"
            context.write_text("SYNTHETIC TEST ONLY\nScenario working notes.\n", encoding="utf-8")
            contexts.append(
                {
                    "id": f"RR{number}",
                    "context": {
                        "kind": "constructed",
                        "path": str(context),
                        "construction_note": "Synthetic fixture; no observed conversation claimed",
                    },
                }
            )
        write_json(
            path,
            {
                "schema_version": 2,
                "study_kind": "controlled_fixture",
                "suite_id": "synthetic-fixed-v2",
                "selection_rule": "All eight fixed cases in order, before any response",
                "exclusions": [],
                "cases": contexts,
            },
        )

    @staticmethod
    def complete_setup(run: Path, directory: Path):
        setup = read_json(run / "setup.json")
        setup.update(
            confirmed_by="test-only",
            confirmed_at="2026-10-21T00:00:00+09:00",
            provider_consent=True,
        )
        for context in setup["histories"].values():
            for field in context:
                if field != "context_kind":
                    context[field] = True
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

    def historical_study(self):
        # Original-format synthetic events exercise the actual transcript adapter.
        # This is fixture evidence, never an empirical or real-model result.
        def message(event_id, role, text):
            return {
                "type": "message",
                "id": event_id,
                "role": role,
                "content": [
                    {"type": "input_text" if role == "user" else "output_text", "text": text}
                ],
            }

        payloads = [
            ("session_meta", {"id": "synthetic-session"}),
            ("response_item", message("request", "user", "SYNTHETIC: report the saved status.\n")),
            (
                "response_item",
                {
                    "type": "custom_tool_call",
                    "call_id": "read",
                    "name": "fixture-read",
                    "input": "status",
                },
            ),
            (
                "response_item",
                {
                    "type": "custom_tool_call_output",
                    "call_id": "read",
                    "output": "Saved draft only; /private/path",
                },
            ),
            (
                "response_item",
                {
                    "type": "function_call",
                    "call_id": "read2",
                    "name": "fixture-read",
                    "arguments": "{}",
                },
            ),
            (
                "response_item",
                {
                    "type": "function_call_output",
                    "call_id": "read2",
                    "output": [{"type": "input_text", "text": "No adoption"}],
                },
            ),
            (
                "response_item",
                message(
                    "target", "assistant", "SYNTHETIC: a draft is saved; adoption is pending.\n"
                ),
            ),
            ("response_item", message("later-correction", "user", "SCORER_SECRET_AFTER_TARGET")),
            ("compacted", {"message": "COMPACTION_IS_NOT_ORIGINAL"}),
            ("response_item", message("system", "developer", "HOST_POLICY_IS_NOT_CASE_INPUT")),
            ("response_item", {"type": "reasoning", "summary": "PRIVATE_REASONING"}),
        ]
        rows = [
            {"timestamp": "2026-10-01T00:00:00Z", "type": kind, "payload": payload}
            for kind, payload in payloads
        ]
        source = self.work / "synthetic-source.jsonl"
        source.write_bytes(b"\xef\xbb\xbf" + "\r\n".join(json.dumps(r) for r in rows).encode())
        case = {
            "id": "HR1",
            "request": payloads[1][1]["content"][0]["text"],
            "target": payloads[6][1]["content"][0]["text"],
            "instructions": "none",
            "facts": "Draft saved, no adoption",
            "state": "Draft only",
            "field_sources": {
                field: {"events": ["read/tool_output"], "note": "SYNTHETIC source check"}
                for field in ("instructions", "facts", "state")
            },
            "context": {
                "kind": "historical",
                "format": "codex-jsonl",
                "session_id": "synthetic-session",
                "path": str(source),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "start_event": "request",
                "request_event": "request",
                "target_event": "target",
                "author_model": "unknown",
                "author_settings_note": "Not captured in this synthetic fixture",
                "omissions": [],
                "transformations": [
                    {
                        "event": "read/tool_output",
                        "text": "Saved draft only; [path redacted]",
                        "reason": "Private path",
                    }
                ],
            },
        }
        bundle = {
            "schema_version": 2,
            "study_kind": "historical_replay",
            "suite_id": "synthetic-history",
            "selection_rule": "One original pair chosen before any review",
            "exclusions": [],
            "cases": [case],
        }
        path = self.work / "historical-cases.json"
        write_json(path, bundle)
        return path, bundle, rows

    def prepare_study(self, case_file, run):
        return self.invoke(
            run,
            "Prepare",
            "-Model",
            "test-model",
            "-Provider",
            "test-provider",
            "-SettingsFile",
            str(self.base / "settings.json"),
            "-CaseFile",
            str(case_file),
        )

    def test_historical_cutoff_source_snapshot_transformations_and_study_binding(self):
        path, bundle, _ = self.historical_study()
        self.run = self.work / "historical"
        self.prepare_study(path, self.run)
        self.complete_setup(self.run, self.work)
        self.call("Freeze")
        manifest = read_json(self.run / "manifest.json")
        self.assertEqual(4, len(manifest["order"]))
        self.assertEqual("C", manifest["order"][2]["condition"])
        source = Path(bundle["cases"][0]["context"]["path"])
        self.assertEqual(source.read_bytes(), (self.run / "inputs/HR1/history.raw").read_bytes())
        b = (self.run / "inputs/HR1/B.txt").read_text(encoding="utf-8")
        c = (self.run / "inputs/HR1/C.txt").read_text(encoding="utf-8")
        self.assertTrue(b.startswith(c))
        self.assertIn("[path redacted]", b)
        for secret in (
            "/private/path",
            "SCORER_SECRET",
            "COMPACTION_IS_NOT",
            "HOST_POLICY",
            "PRIVATE_REASONING",
            "author_settings_note",
            "field_sources",
        ):
            self.assertNotIn(secret, b)
        step = self.step()
        self.import_raw(
            step, self.review(step), suite_id="other-suite", fails="Study binding mismatch"
        )
        source.write_text("external source changed after Prepare", encoding="utf-8")
        path.write_text("external definition changed", encoding="utf-8")
        self.assertEqual(step, self.step())
        self.import_raw(step, self.review(step))
        self.disposition()
        self.assertEqual("C", self.step()["tuple"]["condition"])
        (self.run / "inputs/HR1/history.raw").write_text("tampered original", encoding="utf-8")
        self.call("Validate", fails="Changed or missing evidence")

    def test_study_definition_rejects_mixed_origins_and_fixed_field_overrides(self):
        original = read_json(self.case_file)
        for number, (field, value, error) in enumerate(
            [
                ("context", {"kind": "historical"}, "requires constructed context"),
                ("target", "changed target", "Cannot override fixed field"),
                ("id", "RR2", "exactly RR1-RR8"),
            ]
        ):
            with self.subTest(field=field):
                study = json.loads(json.dumps(original))
                study["cases"][0][field] = value
                path = self.work / f"mixed-{number}.json"
                write_json(path, study)
                run = self.work / f"mixed-{number}"
                self.invoke(
                    run,
                    "Prepare",
                    "-Model",
                    "test-model",
                    "-Provider",
                    "test-provider",
                    "-SettingsFile",
                    str(self.base / "settings.json"),
                    "-CaseFile",
                    str(path),
                    fails=error,
                )
                self.assertFalse(run.exists())

    def test_historical_original_event_validation_negative_controls(self):
        path, original, rows = self.historical_study()
        source = Path(original["cases"][0]["context"]["path"])
        controls = [
            ("request", "different request", "Original request does not match"),
            ("target", "different target", "Original target does not match"),
            ("id", "RR1", "requires separate IDs"),
            ("context.session_id", "wrong-session", "session ID mismatch"),
            ("context.sha256", "0" * 64, "source digest mismatch"),
            ("context.target_event", "request", "cutoff order"),
            ("context.target_event", "missing", "Original event not found"),
            (
                "context.omissions",
                [{"event": "request", "reason": "hide original"}],
                "cannot be transformed or omitted",
            ),
            (
                "context.omissions",
                [{"event": "read/tool_output", "reason": "hide output"}],
                "tool pair",
            ),
            (
                "context.transformations",
                [{"event": "later-correction", "text": "later", "reason": "post cutoff"}],
                "outside selected cutoff",
            ),
            (
                "context.transformations",
                [{"event": "read/tool_output", "text": "redacted", "reason": ""}],
                "transformation/omission.reason",
            ),
            ("field_sources.facts.events", ["later-correction"], "Field evidence after cutoff"),
        ]
        for number, (field, value, error) in enumerate(controls):
            with self.subTest(field=field, error=error):
                study = json.loads(json.dumps(original))
                node = study["cases"][0]
                parts = field.split(".")
                for key in parts[:-1]:
                    node = node[key]
                node[parts[-1]] = value
                if field == "context.omissions":
                    study["cases"][0]["context"]["transformations"] = []
                write_json(path, study)
                run = self.work / f"invalid-{number}"
                self.invoke(
                    run,
                    "Prepare",
                    "-Model",
                    "test-model",
                    "-Provider",
                    "test-provider",
                    "-SettingsFile",
                    str(self.base / "settings.json"),
                    "-CaseFile",
                    str(path),
                    fails=error,
                )
                self.assertFalse(run.exists())
        # An output genuinely absent from the original source is rejected too.
        rows = [r for r in rows if r["payload"].get("type") != "custom_tool_call_output"]
        source.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        original["cases"][0]["context"]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
        original["cases"][0]["context"]["transformations"] = []
        original["cases"][0]["field_sources"]["facts"]["events"] = ["target"]
        original["cases"][0]["field_sources"]["instructions"]["events"] = []
        original["cases"][0]["field_sources"]["state"]["events"] = ["target"]
        write_json(path, original)
        self.invoke(
            self.work / "missing-output",
            "Prepare",
            "-Model",
            "test-model",
            "-Provider",
            "test-provider",
            "-SettingsFile",
            str(self.base / "settings.json"),
            "-CaseFile",
            str(path),
            fails="tool pair",
        )

    def test_v1_root_is_rejected_without_modification(self):
        manifest_path = self.run / "manifest.json"
        manifest = read_json(manifest_path)
        manifest["schema_version"] = 1
        write_json(manifest_path, manifest)
        before = {
            p.relative_to(self.run): p.read_bytes() for p in self.run.rglob("*") if p.is_file()
        }
        self.call("Next", fails="preserve this RunRoot")
        self.assertEqual(
            before,
            {p.relative_to(self.run): p.read_bytes() for p in self.run.rglob("*") if p.is_file()},
        )

    def test_original_adapter_rejects_duplicate_and_multimodal_selected_events(self):
        path, original, rows = self.historical_study()
        source = Path(original["cases"][0]["context"]["path"])
        for number, error in enumerate(
            ("Duplicate original event ID", "multimodal event is unsupported")
        ):
            with self.subTest(error=error):
                changed = json.loads(json.dumps(rows))
                if number == 0:
                    changed.insert(2, changed[1])
                else:
                    changed[1]["payload"]["content"].append(
                        {"type": "input_image", "image_url": "fixture"}
                    )
                source.write_text("\n".join(json.dumps(r) for r in changed), encoding="utf-8")
                study = json.loads(json.dumps(original))
                study["cases"][0]["context"]["sha256"] = hashlib.sha256(
                    source.read_bytes()
                ).hexdigest()
                write_json(path, study)
                self.invoke(
                    self.work / f"bad-adapter-{number}",
                    "Prepare",
                    "-Model",
                    "test-model",
                    "-Provider",
                    "test-provider",
                    "-SettingsFile",
                    str(self.base / "settings.json"),
                    "-CaseFile",
                    str(path),
                    fails=error,
                )

    def test_fixed_controls_share_context_and_prepare_needs_explicit_study(self):
        self.invoke(
            self.work / "no-definition",
            "Prepare",
            "-Model",
            "test-model",
            "-Provider",
            "test-provider",
            "-SettingsFile",
            str(self.base / "settings.json"),
            "-CaseFile",
            "",
            fails="CaseFile (v2)",
        )
        study = read_json(self.case_file)
        separate = self.work / "other-control.txt"
        separate.write_text("SYNTHETIC altered control context", encoding="utf-8")
        study["cases"][4]["context"]["path"] = str(separate)
        path = self.work / "different-controls.json"
        write_json(path, study)
        self.invoke(
            self.work / "different-controls",
            "Prepare",
            "-Model",
            "test-model",
            "-Provider",
            "test-provider",
            "-SettingsFile",
            str(self.base / "settings.json"),
            "-CaseFile",
            str(path),
            fails="identical constructed context",
        )

    def test_prepare_binding_is_recomputed_before_freeze(self):
        for field, error in (
            ("study_sha256", "Study digest mismatch"),
            ("cases", "Study digest mismatch"),
            ("order", "Study digest mismatch"),
            ("settings", "Study digest mismatch"),
            ("suite_id", "Study kind or suite mismatch"),
            ("study_kind", "Study kind or suite mismatch"),
        ):
            with self.subTest(field=field):
                run = self.work / f"changed-{field}"
                shutil.copytree(self.prepared, run)
                path = run / "manifest.json"
                manifest = read_json(path)
                if field == "cases":
                    manifest[field][0]["target"] = "Changed target"
                elif field == "order":
                    manifest[field].reverse()
                elif field == "settings":
                    manifest[field]["reasoning_effort"] = "changed"
                else:
                    manifest[field] = "changed"
                write_json(path, manifest)
                before = {p.relative_to(run): p.read_bytes() for p in run.rglob("*") if p.is_file()}
                self.invoke(run, "Freeze", fails=error)
                self.assertEqual(
                    before,
                    {p.relative_to(run): p.read_bytes() for p in run.rglob("*") if p.is_file()},
                )

    def test_long_interleaved_tool_history_and_pair_order_validation(self):
        path, bundle, rows = self.historical_study()
        source = Path(bundle["cases"][0]["context"]["path"])

        def event(kind, call_id, **fields):
            return {
                "timestamp": "2026-10-01T00:00:00Z",
                "type": "response_item",
                "payload": {"type": kind, "call_id": call_id, **fields},
            }

        calls = [
            event("function_call", f"long-{n}", name="fixture", arguments="{}") for n in range(1000)
        ]
        outputs = [
            event("function_call_output", f"long-{n}", output="Synthetic tool output")
            for n in reversed(range(1000))
        ]
        expanded = rows[:6] + calls + outputs + rows[6:]
        for number, (events, error) in enumerate(
            (
                (expanded, None),
                (
                    rows[:6]
                    + [
                        event("function_call_output", "reversed", output="output"),
                        event("function_call", "reversed", name="fixture", arguments="{}"),
                    ]
                    + rows[6:],
                    "Tool output precedes its call",
                ),
                (
                    rows[:6]
                    + [
                        event(
                            "function_call",
                            "read",
                            name="duplicate",
                            arguments="{}",
                            id="different-id",
                        )
                    ]
                    + rows[6:],
                    "Duplicate tool pair event",
                ),
                (
                    rows[:6]
                    + [
                        event("function_call", "CaseID", name="fixture", arguments="{}"),
                        event("function_call_output", "caseid", output="different ID"),
                    ]
                    + rows[6:],
                    "Missing tool pair",
                ),
            )
        ):
            with self.subTest(error=error):
                source.write_text("\n".join(json.dumps(r) for r in events), encoding="utf-8")
                bundle["cases"][0]["context"]["sha256"] = hashlib.sha256(
                    source.read_bytes()
                ).hexdigest()
                write_json(path, bundle)
                run = self.work / f"tool-pairs-{number}"
                if error:
                    self.invoke(
                        run,
                        "Prepare",
                        "-Model",
                        "test-model",
                        "-Provider",
                        "test-provider",
                        "-SettingsFile",
                        str(self.base / "settings.json"),
                        "-CaseFile",
                        str(path),
                        fails=error,
                    )
                else:
                    self.prepare_study(path, run)
                    selected = read_json(run / "provenance/HR1.json")["selected_event_ids"]
                    self.assertEqual(2006, len(selected))

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
            for name in ["target.txt", "case.txt", "B.txt", "C.txt", "history.txt", "history.raw"]:
                self.assertEqual(
                    (directory / name).read_bytes(),
                    (other / "inputs" / case["id"] / name).read_bytes(),
                )

    def test_script_checkout_line_endings_do_not_change_inputs_or_replay(self):
        snapshots = []
        source = HELPER.read_bytes().replace(b"\r\n", b"\n")
        for ending in (b"\n", b"\r\n"):
            with self.subTest(ending=ending):
                label = "lf" if ending == b"\n" else "crlf"
                repo = self.work / f"repo-{label}"
                subprocess.run(
                    ["git", "clone", "--shared", "--no-checkout", "--quiet", str(ROOT), str(repo)],
                    check=True,
                    capture_output=True,
                    timeout=60,
                )
                assets = Path("skills/research-conversation/acceptance")
                (repo / assets).mkdir(parents=True)
                for name in (
                    "reflective-review.md",
                    "reflective-review-cases.md",
                    "reflective-review-expectations.md",
                    "rubric.md",
                ):
                    shutil.copy2(ROOT / assets / name, repo / assets / name)
                script = repo / "scripts" / HELPER.name
                script.parent.mkdir()
                script.write_bytes(source.replace(b"\n", ending))
                self.run = self.work / f"run-{label}"
                settings = self.work / f"settings-{label}.json"
                write_json(settings, {"reasoning_effort": "high"})
                with patch(__name__ + ".HELPER", script):
                    self.call(
                        "Prepare",
                        "-Model",
                        "test-model",
                        "-Provider",
                        "test-provider",
                        "-SettingsFile",
                        str(settings),
                    )
                    self.complete_setup(self.run, self.work)
                    self.call("Freeze")
                    review = self.step()
                    self.assertEqual(review, self.step())
                    self.import_raw(review, self.review(review, [self.finding()]))
                    self.disposition(
                        "revise", [{"finding": 1, "decision": "accepted", "reason": "test"}]
                    )
                    revision = self.step()
                    self.assertEqual(revision, self.step())
                    self.import_raw(revision, "Synthetic revised target.\n")
                    recheck = self.step(recheck=True)
                    self.import_raw(recheck, self.review(recheck))
                    self.disposition()
                    self.assertEqual("C", self.step()["tuple"]["condition"])
                    inputs = []
                    for step in (review, revision, recheck):
                        content = Path(step["input_path"]).read_bytes()
                        self.assertNotIn(b"\r", content)
                        self.assertEqual(
                            step["record"]["input_sha256"], hashlib.sha256(content).hexdigest()
                        )
                        inputs.append(content)
                    snapshots.append(inputs)
        self.assertEqual(2, len(snapshots))
        self.assertEqual(snapshots[0], snapshots[1])

    def test_frozen_history_keeps_original_bytes_separate_from_model_text(self):
        self.run = self.work / "raw-history"
        case_file = self.work / "raw-cases.json"
        self.make_controlled_study(case_file)
        study = read_json(case_file)
        source = self.work / "original-history.txt"
        original = b"\xef\xbb\xbfSYNTHETIC TEST ONLY\r\nWorking notes\rMore notes\r\n"
        source.write_bytes(original)
        study["cases"][0]["context"]["path"] = str(source)
        write_json(case_file, study)
        self.invoke(
            self.run,
            "Prepare",
            "-Model",
            "test-model",
            "-Provider",
            "test-provider",
            "-SettingsFile",
            str(self.base / "settings.json"),
            "-CaseFile",
            str(case_file),
        )
        self.complete_setup(self.run, self.work)
        self.call("Freeze")
        raw = self.run / "inputs/RR1/history.raw"
        self.assertEqual(original, raw.read_bytes())
        normalized = (self.run / "inputs/RR1/history.txt").read_bytes()
        self.assertNotIn(b"\r", normalized)
        self.assertFalse(normalized.startswith(b"\xef\xbb\xbf"))
        asset = next(
            a
            for a in read_json(self.run / "manifest.json")["assets"]
            if a["path"] == "inputs/RR1/history.raw"
        )
        self.assertEqual(hashlib.sha256(original).hexdigest(), asset["sha256"])
        step = self.step()
        source.write_bytes(b"changed external source")
        self.assertEqual(step, self.step())
        raw.write_bytes(b"tampered frozen original")
        self.call("Next", fails="Changed or missing evidence")

    def test_freeze_requires_scoped_consent_and_typed_context_confirmations(self):
        for field, value, message in [
            ("provider_consent", False, "Provider consent"),
            ("confirmed_at", "2026-10-21T00:00:00", "timezone-qualified confirmed_at"),
            ("construction_disclosed", False, "History confirmation missing"),
            ("context_kind", "historical", "Context kind mismatch"),
            ("provider", "other-provider", "Consent provider mismatch"),
        ]:
            with self.subTest(field=field):
                other = self.work / field
                shutil.copytree(self.prepared, other)
                (self.work / "bad-history.txt").write_text(
                    "SYNTHETIC BAD HISTORY", encoding="utf-8"
                )
                setup = read_json(other / "setup.json")
                if field in ("provider_consent", "confirmed_at", "provider"):
                    setup[field] = value
                else:
                    setup["histories"]["RR8"][field] = value
                write_json(other / "setup.json", setup)
                self.invoke(other, "Freeze", fails=message)
                self.assertFalse((other / "frozen.json").exists())
                self.assertFalse((other / "inputs/RR1/B.txt").exists())

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

    def record_keep_cycles(self):
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

    def test_historical_report_never_applies_fixed_eight_case_criteria(self):
        path, _, _ = self.historical_study()
        self.run = self.work / "history-report"
        self.prepare_study(path, self.run)
        self.complete_setup(self.run, self.work)
        self.call("Freeze")
        self.record_keep_cycles()
        self.assertEqual("INCOMPLETE", self.call("Validate")["status"])
        target = read_json(self.run / "manifest.json")["cases"][0]["target_sha256"]
        for number in (1, 2):
            scores_path = self.run / f"round-{number}/scores.json"
            scores = read_json(scores_path)
            self.assertEqual(3, len(scores))
            for score in scores:
                score.update(
                    output_sha256=target,
                    scorer="fixture-only",
                    scored_at="2026-10-21T00:00:00Z",
                    purpose="PASS",
                    meaning="PASS",
                    purpose_reason="synthetic",
                    meaning_reason="synthetic",
                    observation_note="synthetic",
                    observations=dict.fromkeys(score["observations"], False),
                )
            write_json(scores_path, scores)
        report = self.work / "historical-report"
        self.call("Report", "-ReportDirectory", str(report))
        result = read_json(report / "report.json")
        self.assertEqual("HISTORICAL_REPLAY_RECORDED", result["status"])
        self.assertEqual("historical_replay", result["study_kind"])
        for round_result in result["rounds"]:
            self.assertIsNone(round_result["criteria_met"])
            self.assertIsNone(round_result["criteria"])
            self.assertEqual({"purpose": 1, "meaning": 1}, round_result["lens_totals"]["C"])
        self.assertIn("Descriptive historical replay only", (report / "report.md").read_text())
        scores_path = self.run / "round-2/scores.json"
        scores = read_json(scores_path)
        next(s for s in scores if s["condition"] == "C")["purpose"] = "FAIL"
        write_json(scores_path, scores)
        failed_lens = self.call("Validate")
        self.assertEqual("HISTORICAL_REPLAY_RECORDED", failed_lens["status"])
        self.assertEqual(0, failed_lens["rounds"][1]["lens_totals"]["C"]["purpose"])

    def test_two_round_human_scores_and_reports_with_negative_controls(self):
        self.record_keep_cycles()
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
        for timestamp in (
            "not a timestamp",
            "2026-10-21T00:00:00",
            "2026-02-30T00:00:00Z",
            "2026-10-21T00:00:00Z",
        ):
            with self.subTest(timestamp=timestamp):
                changed = json.loads(json.dumps(original))
                changed[0]["scored_at"] = timestamp
                write_json(path, changed)
                status = self.call("Validate")
                self.assertEqual(
                    "STAGE2_CONSIDERATION_CRITERIA_MET"
                    if timestamp == "2026-10-21T00:00:00Z"
                    else "INCOMPLETE",
                    status["status"],
                )
        fields = ("new_unsupported_claim", "new_authority_error", "new_dropped_condition")
        for condition in ("A", "B"):
            with self.subTest(non_applicable_condition=condition):
                changed = json.loads(json.dumps(original))
                row = next(s for s in changed if s["case"] == "RR1" and s["condition"] == condition)
                row["observations"].update(dict.fromkeys(fields, True))
                write_json(path, changed)
                status = self.call("Validate")
                self.assertEqual("INCOMPLETE", status["status"])
                for field in fields:
                    self.assertTrue(
                        any(
                            f"non-applicable observation {field}" in issue
                            for issue in status["rounds"][1]["issues"]
                        )
                    )
        write_json(path, original[:-1])
        self.assertEqual("INCOMPLETE", self.call("Validate")["status"])


if __name__ == "__main__":
    unittest.main()
