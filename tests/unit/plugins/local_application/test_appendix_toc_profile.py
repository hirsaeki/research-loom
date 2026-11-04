import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET

import rfc8785

import tests.runtime.test_external_desktop_research_intake as intake
from plugins.local_application import LocalApplicationError
from plugins.local_application.misco import appendix_toc
from plugins.local_application.misco.formal_report import assemble, inspect_formal
from plugins.local_application.misco.publication_dialect import MISCO_PUBLICATION_DIALECT
from plugins.local_application.publication.publication_docx import W, docx_bytes
from plugins.local_application.publication.publication_release_support import _publication_policy
from plugins.local_application.publication.word_tools import export_word_tools
from plugins.local_application.workspace.profile_resolution import resolve_effective_profile_set
from tests.runtime.test_issue456_formal_document import representative_report

ROOT = Path(__file__).resolve().parents[4]
CI_WINDOWS = True


class AppendixTocProfileTests(unittest.TestCase):
    def setUp(self):
        config = intake.bootstrap_config()
        config["profile_requests"] = {
            "research": [],
            "organization": [],
            "narrative": [
                {"profile_id": "misco.writer", "profile_type": "narrative", "version": "1.3.0"}
            ],
            "publication": [
                {
                    "profile_id": "misco.publication",
                    "profile_type": "publication",
                    "version": "1.6.0",
                }
            ],
        }
        config.pop("configuration_digest", None)
        config["configuration_digest"] = (
            "sha256:" + hashlib.sha256(rfc8785.dumps(config)).hexdigest()
        )
        eps = resolve_effective_profile_set(
            config,
            [
                ROOT / "profiles/narrative/misco/1.3.0/profile.json",
                ROOT / "profiles/publication/misco/1.6.0/profile.json",
            ],
        )
        # Detached JSON retains resource bodies; no resource file is opened below.
        package = json.loads(json.dumps({"effective_profile_set": eps, "resolved_content": {}}))
        self.policy = _publication_policy(
            package,
            {"profile_id": "misco.publication", "profile_version": "1.6.0"},
            {},
            dialect=MISCO_PUBLICATION_DIALECT,
        )
        self.layout = self.policy["formal_spec_profile"]["docx_layout"]

    def test_two_native_tocs_scopes_and_distinct_footer_are_generated_and_checked(self):
        report = representative_report()
        report.pop("introduction")
        report["footnotes"] = []
        self.layout["formal_document"] = True
        output = assemble(
            docx_bytes(
                [("title", report["title"]), ("heading1", "本文見出し"), ("body", "本文。")],
                self.layout,
            ),
            report,
            "M",
            self.layout,
        )
        self.assertEqual(inspect_formal(output, report, "M", self.layout), [])
        with zipfile.ZipFile(io.BytesIO(output)) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
            footer = ET.fromstring(archive.read("word/footer-appendix.xml"))
            self.assertNotIn("vbaProject.bin", archive.namelist())
            metadata = json.loads(ET.fromstring(archive.read("customXml/formal-report.xml")).text)
        self.assertEqual("".join(footer.itertext()), "付1")
        self.assertEqual(
            metadata["word_toc_helper_sha256"], self.layout["misco_appendix_toc"]["helper_sha256"]
        )
        helper = next(
            row for row in self.policy["word_tools"]["files"] if row["filename"].endswith(".ps1")
        )
        self.assertEqual(metadata["word_toc_helper_sha256"], helper["sha256"])
        self.assertEqual(
            (ROOT / "scripts/appendix_toc_word_helper.ps1").read_bytes(),
            helper["content"].encode("utf-8"),
        )
        bookmark = document.find('.//w:bookmarkStart[@w:name="AUTO_APPENDIX"]', {"w": W})
        bookmark.set(f"{{{W}}}name", "AUTO_APPENDIX_BACKUP")
        self.assertIn("toc-bookmark:AUTO_APPENDIX", appendix_toc.inspect(document, footer))

    def test_export_survives_detachment_without_execution_or_overwriting(self):
        preview = {"build": {"publication_policy": self.policy}}
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "export"
            rows = export_word_tools(preview, output)
            self.assertEqual(len(rows), 3)
            macro = (output / "UpdateTocWithAppendixPrefix.bas").read_text(encoding="utf-8")
            self.assertTrue(macro.isascii())
            self.assertIn("ChrW(AppendixCodePoint)", macro)
            self.assertIn("SetTocFieldsLocked appendixToc, True", macro)
            self.assertIn('tokens(i)) = "\\b"', macro)
            with self.assertRaises(FileExistsError):
                export_word_tools(preview, output)

    def test_bad_digest_or_filename_fails_before_creating_output(self):
        for field, value in [("filename", "../escape.bas"), ("sha256", "0" * 64)]:
            policy = deepcopy(self.policy)
            policy["word_tools"]["files"][0][field] = value
            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / "export"
                with self.assertRaises(LocalApplicationError):
                    export_word_tools({"build": {"publication_policy": policy}}, output)
                self.assertFalse(output.exists())

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell renderer preflight")
    def test_self_declared_helper_digest_cannot_authorize_code_execution(self):
        report = representative_report()
        report.pop("introduction")
        report["footnotes"] = []
        self.layout["formal_document"] = True
        output = assemble(
            docx_bytes([("title", report["title"]), ("body", "本文。")], self.layout),
            report,
            "M",
            self.layout,
        )
        payload = b"throw 'UNTRUSTED_HELPER_EXECUTED'\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            helper = root / "untrusted.ps1"
            helper.write_bytes(payload)
            source = root / "untrusted.docx"
            with (
                zipfile.ZipFile(io.BytesIO(output)) as archive,
                zipfile.ZipFile(source, "w") as target,
            ):
                for name in archive.namelist():
                    data = archive.read(name)
                    if name == "customXml/formal-report.xml":
                        meta = ET.fromstring(data)
                        value = json.loads(meta.text)
                        value["word_toc_helper_sha256"] = hashlib.sha256(payload).hexdigest()
                        meta.text = json.dumps(value)
                        data = ET.tostring(meta)
                    target.writestr(name, data)
            result = subprocess.run(
                [
                    "pwsh.exe",
                    "-NoProfile",
                    "-File",
                    str(ROOT / "scripts/render_publication_word.ps1"),
                    "-SourceDocx",
                    str(source),
                    "-OutputPdf",
                    str(root / "output.pdf"),
                    "-ReceiptPath",
                    str(root / "receipt.json"),
                    "-TocHelperPath",
                    str(helper),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("application-trusted", result.stderr)
            self.assertNotIn("UNTRUSTED_HELPER_EXECUTED", result.stderr)
            self.assertFalse((root / "output.pdf").exists())
