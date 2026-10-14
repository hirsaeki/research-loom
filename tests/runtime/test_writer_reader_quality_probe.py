from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import writer_reader_quality_probe as probe


class WriterReaderQualityProbeTests(unittest.TestCase):
    def test_oversized_response_is_rejected_before_read_or_parse(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "response.json"
            with source.open("wb") as handle:
                handle.truncate(probe.MAX_RESPONSE_BYTES + 1)
            args = argparse.Namespace(run_root=directory, response=str(source))
            with patch.object(Path, "open") as opened, patch.object(probe.json, "loads") as parsed:
                with self.assertRaisesRegex(SystemExit, "exceeds the supported size"):
                    probe._import_response(args)
                opened.assert_not_called()
                parsed.assert_not_called()

    def test_response_growth_after_stat_is_rejected_before_parse(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "response.json"
            source.write_bytes(b"{}")
            args = argparse.Namespace(run_root=directory, response=str(source))
            stream = BytesIO(b" " * (probe.MAX_RESPONSE_BYTES + 1))
            with patch.object(Path, "open", return_value=stream), patch.object(probe.json, "loads") as parsed:
                with self.assertRaisesRegex(SystemExit, "exceeds the supported size"):
                    probe._import_response(args)
                parsed.assert_not_called()

    def test_response_at_limit_reaches_json_parser(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "response.json"
            raw = b"{}" + b" " * (probe.MAX_RESPONSE_BYTES - 2)
            source.write_bytes(raw)
            args = argparse.Namespace(run_root=directory, response=str(source))
            with patch.object(probe.json, "loads", side_effect=RuntimeError("parser reached")) as parsed:
                with self.assertRaisesRegex(RuntimeError, "parser reached"):
                    probe._import_response(args)
                parsed.assert_called_once_with(raw.decode("utf-8"))
