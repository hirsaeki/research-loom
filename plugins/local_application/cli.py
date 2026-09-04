from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from core.conversation import ConversationRuntimeError
from core.decision import HumanDecisionError
from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_application.application import ATTENTION_STORE_NAME
from plugins.local_application.workspace import LocalWorkspaceError
from plugins.local_attention_store import LocalAttentionStoreError, validate_attention_store_schema


def _emit(value: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def _terminal_safe(value: Any) -> str:
    return "".join(
        character if character.isprintable() else f"\\u{ord(character):04x}"
        for character in str(value)
    )


def _emit_external_materials_human(value: Mapping[str, Any]) -> None:
    materials = value.get("materials", [])
    sys.stdout.write(f"Captured external materials: {len(materials)}\n")
    for index, material in enumerate(materials, start=1):
        locators = material.get("source_locators") or []
        original = material.get("original") or {}
        label = _terminal_safe(
            locators[0]
            if locators
            else original.get("artifact_id", material.get("material_id", "material"))
        )
        runs = ", ".join(_terminal_safe(item) for item in material.get("run_ids") or [])
        renditions = material.get("renditions") or []
        rendition_ids = ", ".join(
            _terminal_safe(item.get("artifact_id")) for item in renditions
        )
        sys.stdout.write(f"\n{index}. {label}\n")
        sys.stdout.write(
            f"   Digest: {_terminal_safe(material.get('original_digest'))}\n"
        )
        sys.stdout.write(f"   Runs: {runs}\n")
        sys.stdout.write(
            "   Original: "
            f"{_terminal_safe(original.get('artifact_id'))} "
            f"({_terminal_safe(original.get('media_type'))}, "
            f"{_terminal_safe(original.get('size_bytes'))} bytes)\n"
        )
        sys.stdout.write(f"   Rendition: {rendition_ids}\n")
    if value.get("truncated"):
        sys.stdout.write(
            "\nMore materials available. Next cursor: "
            f"{_terminal_safe(value.get('next_cursor'))}\n"
        )


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


def _add_external_input(parser: argparse.ArgumentParser) -> None:
    _add_workspace(parser)
    parser.add_argument("--run-id", required=True)
    _add_input_json(parser)


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

    resume = sub.add_parser("resume")
    _add_workspace(resume)
    _add_output_json(resume)

    doctor = sub.add_parser("doctor")
    _add_workspace(doctor)
    _add_output_json(doctor)

    actions = sub.add_parser("actions")
    _add_workspace(actions)
    _add_output_json(actions)

    run = sub.add_parser("run")
    run_sub = run.add_subparsers(dest="run_command", required=True)
    run_show = run_sub.add_parser("show")
    _add_workspace(run_show)
    run_show.add_argument("--run-id", required=True)
    _add_output_json(run_show)
    run_replay = run_sub.add_parser("replay")
    _add_workspace(run_replay)
    run_replay.add_argument("--run-id", required=True)
    _add_output_json(run_replay)

    research_input = sub.add_parser("research-input")
    research_input_sub = research_input.add_subparsers(dest="research_input_command", required=True)
    research_input_register = research_input_sub.add_parser("register")
    _add_workspace(research_input_register)
    _add_input_json(research_input_register)
    research_input_list = research_input_sub.add_parser("list")
    _add_workspace(research_input_list)
    _add_output_json(research_input_list)
    research_input_show = research_input_sub.add_parser("show")
    _add_workspace(research_input_show)
    research_input_show.add_argument("--input-id", required=True)
    _add_output_json(research_input_show)

    exhibit = sub.add_parser("exhibit")
    exhibit_sub = exhibit.add_subparsers(dest="exhibit_command", required=True)

    exhibit_capture = exhibit_sub.add_parser("capture")
    _add_workspace(exhibit_capture)
    _add_input_json(exhibit_capture)

    exhibit_list = exhibit_sub.add_parser("list")
    _add_workspace(exhibit_list)
    exhibit_list.add_argument("--rq-id")
    _add_output_json(exhibit_list)

    exhibit_show = exhibit_sub.add_parser("show")
    _add_workspace(exhibit_show)
    exhibit_show.add_argument("--exhibit-id", required=True)
    _add_output_json(exhibit_show)

    survey = sub.add_parser("survey")
    survey_sub = survey.add_subparsers(dest="survey_command", required=True)

    survey_design = survey_sub.add_parser("design")
    survey_design_sub = survey_design.add_subparsers(dest="survey_design_command", required=True)
    survey_design_capture = survey_design_sub.add_parser("capture")
    _add_workspace(survey_design_capture)
    _add_input_json(survey_design_capture)
    survey_design_show = survey_design_sub.add_parser("show")
    _add_workspace(survey_design_show)
    survey_design_show.add_argument("--survey-design-id", required=True)
    survey_design_show.add_argument("--version", required=True)
    _add_output_json(survey_design_show)

    survey_instrument = survey_sub.add_parser("instrument")
    survey_instrument_sub = survey_instrument.add_subparsers(dest="survey_instrument_command", required=True)
    survey_instrument_capture = survey_instrument_sub.add_parser("capture")
    _add_workspace(survey_instrument_capture)
    _add_input_json(survey_instrument_capture)
    survey_instrument_show = survey_instrument_sub.add_parser("show")
    _add_workspace(survey_instrument_show)
    survey_instrument_show.add_argument("--instrument-id", required=True)
    survey_instrument_show.add_argument("--version", required=True)
    _add_output_json(survey_instrument_show)
    survey_instrument_export = survey_instrument_sub.add_parser("export")
    _add_workspace(survey_instrument_export)
    survey_instrument_export.add_argument("--instrument-id", required=True)
    survey_instrument_export.add_argument("--version", required=True)
    survey_instrument_export.add_argument("--format", required=True, choices=("json", "markdown"))
    _add_output_json(survey_instrument_export)

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

    attempt = external_sub.add_parser("attempt")
    attempt_sub = attempt.add_subparsers(dest="attempt_command", required=True)
    attempt_start = attempt_sub.add_parser("start")
    _add_external_input(attempt_start)
    attempt_complete = attempt_sub.add_parser("complete")
    _add_external_input(attempt_complete)

    capture = external_sub.add_parser("capture")
    _add_external_input(capture)

    collect = external_sub.add_parser("collect")
    _add_external_input(collect)

    materials = external_sub.add_parser("materials")
    materials_sub = materials.add_subparsers(dest="materials_command", required=True)
    materials_list = materials_sub.add_parser("list")
    _add_workspace(materials_list)
    materials_list.add_argument(
        "--limit",
        type=int,
        default=100,
        help="materials per page (1-100)",
    )
    materials_list.add_argument(
        "--cursor",
        help="opaque next_cursor from a previous materials list response",
    )
    _add_output_json(materials_list)

    return parser


def _doctor_with_optional_attention(workspace: str | Path) -> Mapping[str, Any]:
    result = deepcopy(dict(LocalApplicationFacade.doctor_workspace(workspace)))
    if result.get("status") != "OK":
        return result
    attention_path = Path(workspace).expanduser().resolve(strict=False) / ".research-loom" / ATTENTION_STORE_NAME
    if not attention_path.exists():
        result.setdefault("checks", []).append({
            "check": "attention_store",
            "status": "OK",
            "mode": "baseline_only",
        })
        return result
    try:
        validate_attention_store_schema(attention_path)
    except LocalAttentionStoreError as exc:
        result["status"] = "ERROR"
        result.setdefault("issues", []).append({"code": exc.code, "message": exc.message})
        return result
    result.setdefault("checks", []).append({"check": "attention_store", "status": "OK"})
    return result


def _run(args: argparse.Namespace) -> Mapping[str, Any]:
    if args.command == "init":
        return LocalApplicationFacade.initialize_workspace(
            args.workspace,
            args.project_config,
            args.effective_profile_set,
        )

    if args.command == "doctor":
        return _doctor_with_optional_attention(args.workspace)

    with LocalApplicationFacade.open_workspace(args.workspace) as facade:
        if args.command == "status":
            return facade.status()
        if args.command == "resume":
            return facade.resume_context()
        if args.command == "actions":
            return facade.list_actions()
        if args.command == "run" and args.run_command == "show":
            return facade.show_run(args.run_id)
        if args.command == "run" and args.run_command == "replay":
            return facade.replay_completed_desktop_research_run(args.run_id)
        if args.command == "exhibit":
            if args.exhibit_command == "capture":
                return facade.capture_exhibit(_read_input(args.json_input))
            if args.exhibit_command == "list":
                return facade.list_exhibits(rq_id=args.rq_id)
            if args.exhibit_command == "show":
                return facade.show_exhibit(args.exhibit_id)
        if args.command == "survey":
            if args.survey_command == "design":
                if args.survey_design_command == "capture":
                    return facade.capture_survey_design(_read_input(args.json_input))
                if args.survey_design_command == "show":
                    return facade.show_survey_design(args.survey_design_id, args.version)
            if args.survey_command == "instrument":
                if args.survey_instrument_command == "capture":
                    return facade.capture_survey_instrument(_read_input(args.json_input))
                if args.survey_instrument_command == "show":
                    return facade.show_survey_instrument(args.instrument_id, args.version)
                if args.survey_instrument_command == "export":
                    return facade.export_survey_instrument(
                        args.instrument_id,
                        args.version,
                        format=args.format,
                    )
        if args.command == "research-input":
            if args.research_input_command == "register":
                return facade.register_project_input(_read_input(args.json_input))
            if args.research_input_command == "list":
                return facade.list_project_inputs()
            if args.research_input_command == "show":
                return facade.show_project_input(args.input_id)
        if args.command == "action" and args.action_command == "submit":
            return facade.submit_action(_read_input(args.json_input))
        if args.command == "confirmation" and args.confirmation_command == "submit":
            return facade.submit_confirmation(_read_input(args.json_input))
        if args.command == "decision" and args.decision_command == "resolve":
            return facade.resolve_human_decision(_read_input(args.json_input))
        if args.command == "external":
            if args.external_command == "attempt" and args.attempt_command == "start":
                return facade.start_external_retrieval_attempt(
                    args.run_id,
                    _read_input(args.json_input),
                )
            if args.external_command == "attempt" and args.attempt_command == "complete":
                return facade.complete_external_retrieval_attempt(
                    args.run_id,
                    _read_input(args.json_input),
                )
            if args.external_command == "capture":
                return facade.capture_external_source(
                    args.run_id,
                    _read_input(args.json_input),
                )
            if args.external_command == "collect":
                return facade.collect_external(args.run_id, _read_input(args.json_input))
            if args.external_command == "materials" and args.materials_command == "list":
                return facade.list_external_materials(
                    limit=args.limit,
                    cursor=args.cursor,
                )
    raise LocalApplicationError("CLI-COMMAND-001", "unsupported command")


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        result = _run(args)
        human_materials = (
            args.command == "external"
            and args.external_command == "materials"
            and args.materials_command == "list"
            and not args.json
        )
        if human_materials:
            _emit_external_materials_human(result)
        else:
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
