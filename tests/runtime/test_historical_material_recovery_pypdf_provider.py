from __future__ import annotations

import io
import subprocess
import unittest
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
            self.assertEqual(command[1:7], [
                "run",
                "--quiet",
                "--isolated",
                "--no-project",
                "--with",
                "pypdf==6.16.2",
            ])
            self.assertEqual(command[7:9], ["python", "-c"])
            self.assertIn("PdfReader", command[9])
            self.assertIn('replace("\\n", "\\r\\n")', command[9])
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

    def test_uv_pypdf_provider_kills_process_when_output_exceeds_bound(self):
        class FakeProcess:
            def __init__(self):
                self.stdout = io.BytesIO(b"x" * 65)
                self.returncode = 0
                self.killed = False

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.killed = True
                self.returncode = -9

        process = FakeProcess()
        with patch.object(provider.shutil, "which", return_value="uv"), patch.object(
            provider.subprocess, "Popen", return_value=process
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
        self.assertTrue(process.killed)

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


if __name__ == "__main__":
    unittest.main()
