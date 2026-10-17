"""Optional-tier write connections set their durability explicitly (ADR 0001, #531)."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPTIONAL_STORES = (
    "local_attention_store.py",
    "local_delphi_store.py",
    "local_project_input_store.py",
    "local_research_exhibit_store.py",
    "local_survey_analysis_store.py",
    "local_survey_response_store.py",
    "local_survey_store.py",
)
REQUIRED = {"journal_mode": "DELETE", "synchronous": "FULL"}


def _is_sqlite_connect(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "connect"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "sqlite3"
    )


def _sets_required_pragmas(node: ast.AST) -> bool:
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "apply_pragmas"
    ):
        return False
    given = {
        keyword.arg: keyword.value.value
        for keyword in node.keywords
        if isinstance(keyword.value, ast.Constant)
    }
    return all(given.get(name) == value for name, value in REQUIRED.items())


def unpinned_write_connections() -> list[str]:
    offenders = []
    for name in OPTIONAL_STORES:
        path = ROOT / "plugins" / name
        source = path.read_text(encoding="utf-8")
        for function in ast.walk(ast.parse(source)):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            nodes = list(ast.walk(function))
            pinned = any(_sets_required_pragmas(node) for node in nodes)
            for node in nodes:
                if not _is_sqlite_connect(node):
                    continue
                if "mode=ro" in (ast.get_source_segment(source, node) or ""):
                    continue
                if not pinned:
                    offenders.append(f"plugins/{name}:{node.lineno} in {function.name}")
    return sorted(set(offenders))


class OptionalStorePragmaTests(unittest.TestCase):
    def test_write_connections_set_journal_mode_and_synchronous(self):
        self.assertEqual(
            [],
            unpinned_write_connections(),
            "apply_pragmas(..., journal_mode='DELETE', synchronous='FULL') after each write connect",
        )


if __name__ == "__main__":
    unittest.main()
