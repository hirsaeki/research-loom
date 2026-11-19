from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts import writer_answer_delivery_probe as probe


class WriterAnswerDeliveryProbeTests(unittest.TestCase):
    def test_conditions_preserve_research_and_contracts_and_never_overwrite(self):
        with TemporaryDirectory() as directory:
            roots = {
                name: Path(directory) / name
                for name in ("baseline", "current", "transport-control")
            }
            for name, root in roots.items():
                probe.prepare(root, name)
            records = {
                name: json.loads((root / "conditions.json").read_text(encoding="utf-8"))
                for name, root in roots.items()
            }
            self.assertEqual(
                records["baseline"]["common_prompt"], records["current"]["common_prompt"]
            )
            self.assertEqual(
                records["baseline"]["cases_sha256"], records["current"]["cases_sha256"]
            )
            self.assertEqual(records["baseline"]["host_files"], records["current"]["host_files"])
            self.assertEqual(records["transport-control"]["writer_version"], "1.4.0")
            for old, new in zip(
                records["baseline"]["cases"], records["current"]["cases"], strict=True
            ):
                self.assertEqual(old["case_id"], new["case_id"])
                self.assertEqual(old["research_snapshot_digest"], new["research_snapshot_digest"])
                inputs = [
                    json.loads(Path(row["writer_input"]["path"]).read_text(encoding="utf-8"))
                    for row in (old, new)
                ]
                self.assertNotEqual(inputs[0]["input_digest"], inputs[1]["input_digest"])
                for old_section, new_section in zip(
                    inputs[0]["sections"], inputs[1]["sections"], strict=True
                ):
                    before, after = old_section["section_input"], new_section["section_input"]
                    for key in (
                        "resolved_research_objects",
                        "section_contract",
                        "resolved_materials",
                        "unresolved_gaps",
                    ):
                        self.assertEqual(before[key], after[key])
                    self.assertNotIn("must_include", before["communication"])
                    communication = deepcopy(after["communication"])
                    self.assertTrue(communication.pop("must_include"))
                    self.assertEqual(communication, before["communication"])
                    for payload in (before, after):
                        self.assertFalse(any(payload["authority_boundary"].values()))
                        self.assertEqual(
                            payload["source"]["source_epistemic_status"], "SYNTHETIC_TEST_ONLY"
                        )
                        self.assertFalse(payload["source"]["release_eligible"])
            for current, control in zip(
                records["current"]["cases"], records["transport-control"]["cases"], strict=True
            ):
                self.assertEqual(current["profile_pins"], control["profile_pins"])
                self.assertEqual(
                    current["research_snapshot_digest"], control["research_snapshot_digest"]
                )
                documents = [
                    json.loads(Path(row["writer_input"]["path"]).read_text(encoding="utf-8"))
                    for row in (current, control)
                ]
                for left, right in zip(
                    documents[0]["sections"], documents[1]["sections"], strict=True
                ):
                    before, after = (
                        deepcopy(left["section_input"]),
                        deepcopy(right["section_input"]),
                    )
                    self.assertEqual(before["writer_profile"], after["writer_profile"])
                    self.assertTrue(before["communication"].pop("must_include"))
                    # Opaque operation identities differ; domain content does not.
                    for value in (before, after):
                        value.pop("source")
                        value.pop("section_input_digest")
                    self.assertEqual(before, after)
            original = (roots["baseline"] / "conditions.json").read_bytes()
            with self.assertRaises(FileExistsError):
                probe.prepare(roots["baseline"], "baseline")
            self.assertEqual((roots["baseline"] / "conditions.json").read_bytes(), original)
