from __future__ import annotations

import unittest
from unittest.mock import patch

from plugins.local_application import (
    new_material_group_continuation_pdf_provider as provider,
)
from plugins.local_application import new_material_group_continuation_service as group
from plugins.local_application.material_reacquisition_facade import RetrievedMaterial
from plugins.local_application.facade import LocalApplicationError


class Issue127PdfGroupProviderTests(unittest.TestCase):
    def test_pdf_group_provider_ablation_and_provenance(self):
        with self.assertRaisesRegex(LocalApplicationError, "only text/html"):
            provider._BASE_RENDER(
                b"%PDF-1.4 fixture",
                "application/pdf",
                max_bytes=1024,
            )

        rendered = RetrievedMaterial(
            b"OECD replacement text\r\n",
            "text/plain",
            "",
            "uv-pypdf/6.16.2;newline=crlf",
            None,
        )
        with patch.object(
            provider,
            "_regenerate_pinned_text_rendition",
            return_value=rendered,
        ) as regenerate:
            content = group._render_reacquired_html_rendition(
                b"%PDF-1.4 fixture",
                "application/pdf",
                max_bytes=1024,
            )
            self.assertEqual(content, rendered.content)
            regenerate.assert_called_once_with(
                b"%PDF-1.4 fixture",
                "application/pdf",
                "",
                max_bytes=1024,
            )

            with patch.object(
                provider._BASE_CAPTURE_SERVICE,
                "capture",
                return_value={"status": "ok"},
            ) as capture:
                service = group.DesktopResearchCaptureService(object())
                result = service.capture(
                    object(),
                    capture_id="CAP-OECD",
                    source_category="other",
                    exact_locator="https://example.test/oecd.pdf",
                    acquired_at="2026-09-17T00:00:00Z",
                    original_bytes=b"%PDF-1.4 fixture",
                    original_media_type="application/pdf",
                    text_rendition=content,
                    provenance={
                        "text_rendition_provider": (
                            "python-htmlparser/g1-normalized-text@0.1.0;newline=crlf"
                        )
                    },
                )
            self.assertEqual(result, {"status": "ok"})
            self.assertEqual(
                capture.call_args.kwargs["provenance"]["text_rendition_provider"],
                "uv-pypdf/6.16.2;newline=crlf",
            )

        self.assertIsNone(provider._PDF_RENDITION_PROVIDER.get())


if __name__ == "__main__":
    unittest.main()
