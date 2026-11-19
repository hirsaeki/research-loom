#!/usr/bin/env python3
"""Prepare two fixed synthetic #627 cases using the existing #467 fixture path.

This is an experiment driver, not an LLM client or a production Workspace path.
Baseline reproduces main 91d0825's omitted positive communication projection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.runtime import canonical_digest  # noqa: E402
from plugins.local_application.workspace.profile_resolution import resolve_effective_profile_set  # noqa: E402
from plugins.local_application.writer.writer_composition_support import _digest_document  # noqa: E402
from plugins.local_application.writer.writer_section_input import WriterSectionInputMixin  # noqa: E402
from scripts import writer_reader_quality_probe as previous  # noqa: E402

CASES = ROOT / "docs/acceptance/writer-answer-delivery/cases.json"
COMMON_PROMPT = """固定入力から、日本語の短稿を初回一稿だけ作成してください。
各ケースは別の文書です。各文書は入力の4節を使い、全体3000〜4500字を目標とします。
skills/writer/SKILL.mdと同references/reader-flow.mdを読み、そのWriter手順に従ってください。
各writer-input.jsonの配信済みWRITER_*資料・規則と節入力を読み、供給された意味だけを文章化してください。
公開されたdetached入力が材料の全体です。非公開のWorkspace、他の条件、過去の稿、採点資料は読まないでください。
提言・根拠・必要条件・未解決点を保持し、読みやすい日本語本文を作成してください。
採択済みの提言を、新たな研究判断や実施済みの施策として扱わないでください。
合成材料である旨は文書冒頭で示し、各段落へ同じ監査説明を反復する必要はありません。
返却ファイルはケースごとにsections[{section_id,content}]のみのJSONとしてください。
意味・編集レビューは別段階なので、本文の改善反復やProfileのPASS申告は行わないでください。
初回出力を書き出した後に書き換えず、試行回数は各ケース一回としてください。
"""


def historical_projection(instance, *args, **kwargs):
    value = _CURRENT_BUILD(instance, *args, **kwargs)
    value["communication"].pop("must_include", None)
    value["section_input_digest"] = _digest_document(value, "section_input_digest")
    return value


_CURRENT_BUILD = WriterSectionInputMixin._build_section_input_document


def prepare(run_root: Path, condition: str) -> None:
    if condition not in {"baseline", "current", "transport-control"}:
        raise ValueError("unsupported fixed experimental condition")
    run_root = run_root.resolve()
    run_root.mkdir(parents=True, exist_ok=False)
    cases = previous._read_json(CASES)
    version = "1.1.0" if condition == "baseline" else "1.4.0"
    receipts = []
    for index, case in enumerate(cases["cases"]):
        code = previous._short_code(index)
        project_id = f"PRJ-WRQ-{code}"
        config = previous._config_for(case, project_id, f"RQ-{code}")
        config["profile_requests"]["narrative"][0]["version"] = version
        # Keep Publication constant at the bundled Project's baseline version.
        config["profile_requests"]["publication"] = [
            {"profile_id": "misco.publication", "profile_type": "publication", "version": "1.3.0"}
        ]
        config["communication_brief"]["must_include"] = deepcopy(case["must_include"])
        config.pop("configuration_digest")
        config["configuration_digest"] = canonical_digest(config)
        eps = resolve_effective_profile_set(
            config,
            [
                ROOT / f"profiles/narrative/misco/{version}/profile.json",
                ROOT / "profiles/publication/misco/1.3.0/profile.json",
            ],
        )
        state, refs = previous._case_state(
            case, project_id, code, config, eps, cases["common_invariants"]
        )
        workspace = run_root / "cases" / case["case_id"] / "workspace"
        facade = previous._new_facade(workspace, eps, seed=state, project_id=project_id)
        try:
            package = facade.build_research_package(
                {
                    "snapshot_id": state.current_snapshot["id"],
                    "rq_id": refs["rq_id"],
                    "object_ids": [
                        refs[key]
                        for key in ("method_id", "finding_id", "argument_id", "recommendation_id")
                    ],
                }
            )["package"]
            composition = facade.capture_writer_composition(
                package["package_id"],
                {
                    "purpose": "固定された合成材料から読者の問いに答える短稿。",
                    "audience": [case["target_reader"]],
                    "sections": previous._sections(case, refs),
                    "created_by": {
                        "type": "human_or_external_llm",
                        "instruction": "SYNTHETIC_TEST_ONLY; no real research adoption",
                    },
                },
            )["composition"]
            facade.select_writer_composition(
                composition["composition_id"], 1, composition["composition_digest"]
            )
            output = run_root / "inputs" / case["case_id"]
            output.parent.mkdir(parents=True, exist_ok=True)
            context = (
                patch.object(
                    WriterSectionInputMixin, "_build_section_input_document", historical_projection
                )
                if condition != "current"
                else nullcontext()
            )
            with context:
                facade.export_writer_round_trip_input(
                    composition["composition_id"],
                    [s["section_id"] for s in composition["sections"]],
                    output,
                )
            doc = previous._read_json(output / "writer-input.json")
            record = {
                "authority": "SYNTHETIC_TEST_ONLY",
                "case_id": case["case_id"],
                "workspace": str(workspace),
                "project_id": project_id,
                "package": package,
                "composition": composition,
                "writer_input": {
                    "path": str(output / "writer-input.json"),
                    "input_digest": doc["input_digest"],
                    "input_id": doc["input_id"],
                },
                "research_snapshot_digest": doc["source"]["research_snapshot_digest"],
                "profile_pins": eps["effective_profiles"],
            }
            previous._write_json(
                run_root / "receipts" / case["case_id"] / "prepare.json", record, exclusive=True
            )
            receipts.append(record)
        finally:
            facade.close()
    previous._write_json(
        run_root / "conditions.json",
        {
            "authority": "SYNTHETIC_TEST_ONLY",
            "condition": condition,
            "prepared_at": previous._utc_now(),
            "preparation_head": previous._git_head(),
            "writer_version": version,
            "publication_version": "1.3.0",
            "positive_brief_delivery": condition == "current",
            "baseline_projection": "Reproduction of main 91d0825's omission, not an export run under that historical checkout.",
            "prose_generation_performed": False,
            "cases_sha256": hashlib.sha256(CASES.read_bytes()).hexdigest(),
            "common_prompt": COMMON_PROMPT,
            "host_files": {
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for name in ("skills/writer/SKILL.md", "skills/writer/references/reader-flow.md")
            },
            "cases": receipts,
        },
        exclusive=True,
    )
    (run_root / "prompt.txt").write_text(COMMON_PROMPT, encoding="utf-8")
    print(
        json.dumps({"condition": condition, "run_root": str(run_root), "case_count": len(receipts)})
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument(
        "--condition", choices=("baseline", "current", "transport-control"), required=True
    )
    args = parser.parse_args(argv)
    prepare(args.run_root, args.condition)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
