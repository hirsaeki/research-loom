"""Hardened new-material continuation behavior is part of the services themselves (#487).

These used to be applied by import-time monkeypatches in the package __init__, so the
behavior depended on import order. They must hold however the modules are imported.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from plugins.local_application import new_material_continuation_service as base
from plugins.local_application import new_material_group_continuation_service as group
from plugins.local_application.facade import LocalApplicationError

ROOT = Path(__file__).resolve().parents[2]


class NewMaterialContinuationHardeningTests(unittest.TestCase):
    def test_malformed_end_tag_does_not_end_skip_scope(self):
        rendered = base._render_reacquired_html_rendition(
            b"<p>keep</p><script>hidden</style>still hidden</script><p>after</p>",
            "text/html",
            max_bytes=1024,
        )
        self.assertEqual(rendered, b"keep\r\nafter\r\n")

    def test_pinned_text_budget_caps_rendition_limit(self):
        token = base._TEXT_RENDITION_LIMIT.set(4)
        try:
            with self.assertRaisesRegex(LocalApplicationError, "bounded artifact limit"):
                base._render_reacquired_html_rendition(
                    b"<p>longer than four bytes</p>", "text/html", max_bytes=1024
                )
        finally:
            base._TEXT_RENDITION_LIMIT.reset(token)

    def test_group_service_uses_pdf_aware_render_and_capture(self):
        self.assertIsNot(
            group._render_reacquired_html_rendition, base._render_reacquired_html_rendition
        )
        self.assertTrue(
            issubclass(group.DesktopResearchCaptureService, group._BASE_CAPTURE_SERVICE)
        )
        self.assertIsNot(group.DesktopResearchCaptureService, group._BASE_CAPTURE_SERVICE)

    def test_hardening_holds_when_services_are_imported_first(self):
        script = (
            "from plugins.local_application import new_material_group_continuation_service as g\n"
            "from plugins.local_application import new_material_continuation_service as b\n"
            "out = b._render_reacquired_html_rendition("
            "b'<script>x</style>y</script>z', 'text/html', max_bytes=64)\n"
            "assert out == b'z\\r\\n', out\n"
            "assert g.DesktopResearchCaptureService is not g._BASE_CAPTURE_SERVICE\n"
        )
        subprocess.run([sys.executable, "-c", script], cwd=ROOT, check=True)


if __name__ == "__main__":
    unittest.main()
