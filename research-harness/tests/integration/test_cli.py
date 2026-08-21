import json
from pathlib import Path

import pytest

from misco_harness.cli import build_parser, main
from tests.integration.test_discovery_cycle import prepare_workspace


def test_cli_status_plan_continue_decision_and_validate(tmp_path: Path, capsys) -> None:
    _orchestrator, _ = prepare_workspace(tmp_path)
    assert main(["--root", str(tmp_path), "status"]) == 0
    assert json.loads(capsys.readouterr().out)["phase"] == "QUESTION_FORMATION"
    assert main(["--root", str(tmp_path), "plan"]) == 0
    assert json.loads(capsys.readouterr().out)["task_type"] == "INDEPENDENT_QUESTION_CANDIDATES"
    assert main(["--root", str(tmp_path), "continue", "--run-limit", "10"]) == 10
    stopped = json.loads(capsys.readouterr().out)
    decision_id = stopped["pending_decision_ids"][0]
    assert main(["--root", str(tmp_path), "decisions"]) == 0
    assert json.loads(capsys.readouterr().out)["pending_decision_ids"] == [decision_id]
    assert main(["--root", str(tmp_path), "decision", "show", decision_id]) == 0
    assert "## 1. Decision Request" in capsys.readouterr().out
    assert main([
        "--root", str(tmp_path), "decision", "record", decision_id,
        "--choice", "ADOPT_PROPOSED_BASELINES", "--by", "human",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["phase"] == "RESEARCH_PLANNING"
    assert main(["--root", str(tmp_path), "validate"]) == 0
    validation = json.loads(capsys.readouterr().out)
    assert validation["status"] == "VALID"
    assert validation["runs"] == 2


def test_cli_continue_reports_interactive_work_context_and_schema(tmp_path: Path, capsys) -> None:
    _orchestrator, _ = prepare_workspace(tmp_path, worker_backend="interactive-work")
    assert main(["--root", str(tmp_path), "continue"]) == 11
    waiting = json.loads(capsys.readouterr().out)
    assert waiting["execution_state"] == "WORK_EXECUTION_REQUIRED"
    assert Path(waiting["pending_work"]["context_pack"]).is_dir()
    assert waiting["pending_work"]["expected_output_schema"] == "IndependentQuestionFormationHandoff"
    assert Path(waiting["pending_work"]["expected_output_schema_file"]).is_file()
    assert waiting["pending_work"]["expected_output_file"].endswith("result.json")
    task = Path(waiting["pending_work"]["task_file"]).read_text(encoding="utf-8")
    assert "## Objective" in task
    assert "## Authority boundaries" in task
    assert "## Required work" in task
    assert "## Forbidden context" in task
    assert "## Output requirements" in task


def test_cli_init_requires_an_explicit_worker_backend() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([
            "init", "--theme", "theme.md", "--expectations", "expectations.md", "--seed", "seed.md",
        ])


def test_cli_next_action_returns_typed_coordinator_json(tmp_path: Path, capsys) -> None:
    prepare_workspace(tmp_path, worker_backend="interactive-work")
    assert main(["--root", str(tmp_path), "next-action"]) == 11
    action = json.loads(capsys.readouterr().out)
    assert action["state"] == "WORK_EXECUTION_REQUIRED"
    assert action["task_type"] == "INDEPENDENT_QUESTION_CANDIDATES"
    assert Path(action["task_file"]).is_file()


def test_cli_operational_error_returns_error_exit_code_and_stderr_json(tmp_path: Path, capsys) -> None:
    assert main(["--root", str(tmp_path), "status"]) == 1
    error = json.loads(capsys.readouterr().err)
    assert error["status"] == "ERROR"
    assert error["error_type"]
