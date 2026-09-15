from __future__ import annotations

import io
import subprocess
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from plugins.local_application import material_reacquisition_facade as base
from plugins.local_application import material_reacquisition_pypdf_provider as provider


class HistoricalMaterialReacquisitionPypdfProviderTests(unittest.TestCase):
    def test_uv_pypdf_provider_is_version_pinned_bounded_and_crlf_replaying(self):
        rendered = b"page one\r\n\r\npage two\r\n"
        created = []

        class FakeProcess:
            def __init__(self):
                self.stdout = io.BytesIO(rendered)
                self.returncode = 0
                self.killed = False

            def wait(self, timeout=None):
                self.assert_timeout = timeout
                return self.returncode

            def kill(self):
                self.killed = True
                self.returncode = -9

        def fake_popen(command, **kwargs):
            self.assertEqual(
                command[1:7],
                [
                    "run",
                    "--quiet",
                    "--isolated",
                    "--no-project",
                    "--with",
                    "pypdf==6.16.2",
                ],
            )
            self.assertEqual(command[7:9], ["python", "-c"])
            self.assertIn("PdfReader", command[9])
            self.assertIn("emit(page_text", command[9])
            self.assertEqual(command[11], "1024")
            self.assertIs(kwargs["stdout"], subprocess.PIPE)
            self.assertIs(kwargs["stderr"], subprocess.DEVNULL)
            process = FakeProcess()
            created.append(process)
            return process

        with patch.object(provider.shutil, "which", return_value="uv"), patch.object(
            provider.subprocess, "Popen", side_effect=fake_popen
        ):
            result = provider._run_historical_pypdf(
                b"%PDF-1.7 fixture",
                "https://arxiv.org/pdf/2412.09385v2",
                max_bytes=1024,
            )

        self.assertEqual(result.content, rendered)
        self.assertEqual(result.provider, "uv-pypdf/6.16.2;newline=crlf")
        self.assertFalse(created[0].killed)
        self.assertEqual(created[0].assert_timeout, 60)

    def test_child_script_streams_exact_historical_bytes_and_enforces_bound(self):
        class FakePage:
            def __init__(self, text):
                self.text = text

            def extract_text(self):
                return self.text

        fake_module = types.ModuleType("pypdf")
        fake_module.PdfReader = lambda _source: SimpleNamespace(
            pages=[FakePage("page one\nline two"), FakePage("page two")]
        )
        output = io.BytesIO()
        with patch.dict(sys.modules, {"pypdf": fake_module}), patch.object(
            sys, "argv", ["-c", "source.pdf", "1024"]
        ), patch.object(sys, "stdout", SimpleNamespace(buffer=output)):
            exec(provider._PYPDF_SCRIPT, {})
        self.assertEqual(
            output.getvalue(),
            b"page one\r\nline two\r\n\r\npage two\r\n",
        )

        fake_module.PdfReader = lambda _source: SimpleNamespace(
            pages=[FakePage("x" * 65), FakePage("must-not-be-read")]
        )
        output = io.BytesIO()
        with patch.dict(sys.modules, {"pypdf": fake_module}), patch.object(
            sys, "argv", ["-c", "source.pdf", "64"]
        ), patch.object(sys, "stdout", SimpleNamespace(buffer=output)):
            with self.assertRaises(SystemExit) as raised:
                exec(provider._PYPDF_SCRIPT, {})
        self.assertEqual(raised.exception.code, provider._PYPDF_BOUND_EXIT)
        self.assertLessEqual(len(output.getvalue()), 64)

    def test_uv_pypdf_provider_reports_child_bound_without_fallback(self):
        class FakeProcess:
            def __init__(self):
                self.stdout = io.BytesIO(b"")
                self.returncode = provider._PYPDF_BOUND_EXIT

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.returncode = -9

        with patch.object(provider.shutil, "which", return_value="uv"), patch.object(
            provider.subprocess, "Popen", return_value=FakeProcess()
        ):
            with self.assertRaisesRegex(
                base.MaterialReacquisitionRetrievalError,
                "exceeds bounded material intake limit",
            ):
                provider._run_historical_pypdf(
                    b"%PDF-1.7 fixture",
                    "https://example.test/source.pdf",
                    max_bytes=64,
                )

        with patch.object(
            provider,
            "_run_historical_pypdf",
            side_effect=base.MaterialReacquisitionRetrievalError(
                "regenerated rendition exceeds bounded material intake limit"
            ),
        ), patch.object(provider, "_BASE_GENERATOR") as fallback:
            with self.assertRaisesRegex(
                base.MaterialReacquisitionRetrievalError,
                "exceeds bounded material intake limit",
            ):
                provider._regenerate_text_rendition(
                    b"%PDF-1.7 fixture",
                    "application/pdf",
                    "https://example.test/source.pdf",
                    max_bytes=64,
                )
            fallback.assert_not_called()

    def test_pdf_provider_falls_back_without_changing_non_pdf_behavior(self):
        fallback_result = base.RetrievedMaterial(
            b"fallback",
            "text/plain",
            "https://example.test/source.pdf",
            "pdftotext",
            None,
        )
        with patch.object(
            provider,
            "_run_historical_pypdf",
            side_effect=base.MaterialReacquisitionRetrievalError("uv unavailable"),
        ), patch.object(provider, "_BASE_GENERATOR", return_value=fallback_result) as fallback:
            result = provider._regenerate_text_rendition(
                b"%PDF-1.7 fixture",
                "application/pdf",
                "https://example.test/source.pdf",
                max_bytes=1024,
            )
            self.assertIs(result, fallback_result)
            fallback.assert_called_once()

        with patch.object(provider, "_BASE_GENERATOR", return_value=fallback_result) as fallback:
            result = provider._regenerate_text_rendition(
                b"hello",
                "text/plain",
                "https://example.test/source.txt",
                max_bytes=1024,
            )
            self.assertIs(result, fallback_result)
            fallback.assert_called_once()

    def test_provider_target_match_rejects_results_from_old_implementation_version(self):
        old_child = SimpleNamespace(
            capability_id=base._CAPABILITY_ID,
            capability_version="0.2.0",
            implementation_version="0.2.0",
            provenance={
                "historical_target": {
                    "capture_id": "CAP-1",
                    "kind": "rendition",
                }
            },
        )
        current_child = SimpleNamespace(
            capability_id=base._CAPABILITY_ID,
            capability_version="0.2.1",
            implementation_version="0.2.1",
            provenance=old_child.provenance,
        )
        with patch.object(base, "_CAPABILITY_VERSION", "0.2.1"), patch.object(
            base, "_IMPLEMENTATION_VERSION", "0.2.1"
        ):
            self.assertFalse(
                provider._matches_current_target(old_child, "CAP-1", "rendition")
            )
            self.assertTrue(
                provider._matches_current_target(current_child, "CAP-1", "rendition")
            )


if __name__ == "__main__":
    unittest.main()
