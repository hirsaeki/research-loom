from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from core.conversation import ConversationRuntimeError
from core.decision import HumanDecisionError
from plugins.local_application.facade import LocalApplicationError, LocalApplicationFacade
from plugins.local_application.workspace import LocalWorkspaceError


def _emit(value: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def _read_input(source: str | None) -> dict[str, Any]:
    source = source or "-"
    try:
        raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LocalApplicationError("CLI-INPUT-001", "input is not readable JSON") from exc
    if not isinstance(value, dict):
        raise LocalApplicationError("CLI-INPUT-001", "input JSON must be an object")
    return value


def _add_workspace(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", required=True)


def _add_output_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="machine-readable JSON output (always enabled)")


def _add_input_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        dest="json_input",
        nargs="?",
        const="-",
        default="-",
        metavar="FILE|-",
        help="read JSON input from FILE or stdin (-)",
    )


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise LocalApplicationError("CLI-COMMAND-001", message)


def build_parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(prog="research-loom")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    _add_workspace(init)
    init.add_argument("--project-config", required=True)
    init.add_argument("--effective-profile-set", required=True)
    _add_output_json(init)

    status = sub.add_parser("status")
    _add_workspace(status)
    _add_output_json(status)

    doctor = sub.add_parser("doctor")
    _add_workspace(doctor)
    _add_output_json(doctor)

    actions = sub.add_parser("actions")
    _add_workspace(actions)
    _add_output_json(actions)

    action = sub.add_parser("action")
    action_sub = action.add_subparsers(dest="action_command", required=True)
    submit = action_sub.add_parser("submit")
    _add_workspace(submit)
    _add_input_json(submit)

    confirmation = sub.add_parser("confirmation")
    confirmation_sub = confirmation.add_subparsers(dest="confirmation_command", required=True)
    confirm = confirmation_sub.add_parser("submit")
    _add_workspace(confirm)
    _add_input_json(confirm)

    decision = sub.add_parser("decision")
    decision_sub = decision.add_subparsers(dest="decision_command", required=True)
    resolve = decision_sub.add_parser("resolve")
    _add_workspace(resolve)
    _add_input_json(resolve)

    external = sub.add_parser("external")
    external_sub = external.add_subparsers(dest="external_command", required=True)
    collect = external_sub.add_parser("collect")
    _add_workspace(collect)
    collect.add_argument("--run-id", required=True)
    _add_input_json(collect)

    return parser


def _run(args: argparse.Namespace) -> Mapping[str, Any]:
    if args.command == "init":
        return LocalApplicationFacade.initialize_workspace(
            args.workspace,
            args.project_config,
            args.effective_profile_set,
        )

    if args.command == "doctor":
        return LocalApplicationFacade.doctor_workspace(args.workspace)

    with LocalApplicationFacade.open_workspace(args.workspace) as facade:
        if args.command == "status":
            return facade.status()
        if args.command == "actions":
            return facade.list_actions()
        if args.command == "action" and args.action_command == "submit":
            return facade.submit_action(_read_input(args.json_input))
        if args.command == "confirmation" and args.confirmation_command == "submit":
            return facade.submit_confirmation(_read_input(args.json_input))
        if args.command == "decision" and args.decision_command == "resolve":
            return facade.resolve_human_decision(_read_input(args.json_input))
        if args.command == "external" and args.external_command == "collect":
            return facade.collect_external(args.run_id, _read_input(args.json_input))
    raise LocalApplicationError("CLI-COMMAND-001", "unsupported command")


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        result = _run(args)
        _emit(result)
        return 1 if result.get("status") == "ERROR" else 0
    except (LocalWorkspaceError, LocalApplicationError, ConversationRuntimeError, HumanDecisionError) as exc:
        _emit({
            "status": "ERROR",
            "issues": [{"code": str(exc.code), "message": str(exc.message)}],
        })
        return 2
    except Exception as exc:
        _emit({
            "status": "ERROR",
            "issues": [{"code": "APPLICATION-UNEXPECTED-001", "message": str(exc)}],
        })
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
