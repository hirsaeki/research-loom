from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from misco_harness.context_builder import ArtifactAccessPolicy
from misco_harness.conversation import WorkConversationCoordinator
from misco_harness.coordinator import InteractiveWorkResearchCoordinator
from misco_harness.distribution import upgrade_workspace
from misco_harness.models import (
    ArtifactRegistry,
    ChatTurnInput,
    ContextPackManifest,
    OrchestratorState,
    PublicationState,
    PublicationStructureChange,
    PublicationWriterOutput,
    RecoveryRequest,
    ResearchState,
    RunManifest,
    SAFE_IDENTIFIER_PATTERN,
)
from misco_harness.orchestrator import DiscoveryOrchestrator, NextRunPlan
from misco_harness.recovery import RecoveryService
from misco_harness.trace_store import verify_hash
from misco_harness.workspace import new_workspace, verify_archive


EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_HUMAN_DECISION_WAIT = 10
EXIT_WORK_WAIT = 11


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rh", description="MISCO Research Execution Control Plane")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Harness workspace root")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Initialize explicit inputs and compact state")
    init.add_argument("--theme", type=Path, required=True)
    init.add_argument("--expectations", type=Path, required=True)
    init.add_argument("--seed", type=Path)
    init.add_argument("--worker-backend", choices=["mock", "interactive-work"], required=True)
    attention = commands.add_parser("attention", help="Register raw Attention intake for bounded Work distillation")
    attention_commands = attention.add_subparsers(dest="attention_command", required=True)
    attention_ingest = attention_commands.add_parser("ingest")
    attention_ingest.add_argument("--path", type=Path, required=True)
    attention_ingest.add_argument("--by", dest="registered_by", required=True)
    archive = commands.add_parser("archive", help="Archive and freeze the current Research workspace")
    archive.add_argument("--destination", type=Path)
    archive.add_argument("--by", dest="created_by")
    archive.add_argument("--reason")
    archive.add_argument("--allow-incomplete", action="store_true")
    archive.add_argument("--verify", type=Path, help="Verify an existing archive bundle without mutating a workspace")
    new = commands.add_parser("new", help="Create a fresh workspace from an explicit template")
    new.add_argument("--template-root", type=Path, required=True)
    new.add_argument("--theme", type=Path, required=True)
    new.add_argument("--expectations", type=Path, required=True)
    new.add_argument("--worker-backend", choices=["mock", "interactive-work"], required=True)
    new.add_argument("--drop", type=Path)
    new.add_argument("--profile-source")
    new.add_argument("--profile-ref")
    new.add_argument("--init-git", action="store_true")
    upgrade = commands.add_parser("upgrade", help="Upgrade Harness/Profile sources in a research workspace")
    upgrade.add_argument("--harness-source")
    upgrade.add_argument("--harness-ref")
    upgrade.add_argument("--profile-source")
    upgrade.add_argument("--profile-ref")
    seed = commands.add_parser("seed", help="Register an optional prior Question Seed")
    seed_commands = seed.add_subparsers(dest="seed_command", required=True)
    register_seed = seed_commands.add_parser("register", help="Register a prior Seed before independent Work is collected")
    register_seed.add_argument("--path", type=Path, required=True)
    commands.add_parser("status")
    commands.add_parser("plan")
    continuation = commands.add_parser("continue")
    continuation.add_argument("--run-limit", type=int, default=10)
    decisions = commands.add_parser("decisions")
    decisions_commands = decisions.add_subparsers(dest="decisions_command")
    migrate_kinds = decisions_commands.add_parser("migrate-kinds", help="Apply the one-time legacy Decision kind migration")
    migrate_kinds.add_argument("--mapping", type=Path, required=True, help="JSON object mapping Decision IDs to Decision kinds")
    decision = commands.add_parser("decision")
    decision_commands = decision.add_subparsers(dest="decision_command", required=True)
    show_decision = decision_commands.add_parser("show")
    show_decision.add_argument("decision_id")
    record = decision_commands.add_parser("record")
    record.add_argument("decision_id")
    record.add_argument("--choice", required=True)
    record.add_argument("--by", dest="decided_by", required=True)
    record.add_argument("--condition", action="append", default=[])
    record.add_argument("--rationale")
    runs = commands.add_parser("runs")
    runs_commands = runs.add_subparsers(dest="runs_command", required=True)
    show_run = runs_commands.add_parser("show")
    show_run.add_argument("run_id")
    context = commands.add_parser("context")
    context_commands = context.add_subparsers(dest="context_command", required=True)
    show_context = context_commands.add_parser("show")
    show_context.add_argument("run_id")
    commands.add_parser("validate")
    coordinator = commands.add_parser(
        "coordinator",
        aliases=["coordinate"],
        help="Query or continue the thin Interactive Work Research Coordinator",
    )
    coordinator_commands = coordinator.add_subparsers(dest="coordinator_command", required=True)
    coordinator_next = coordinator_commands.add_parser("next", help="Return the next Harness-authorized action")
    coordinator_next.add_argument(
        "--no-advance",
        action="store_true",
        help="Only inspect an already materialized Work/Decision boundary",
    )
    coordinator_submit = coordinator_commands.add_parser(
        "submit",
        aliases=["collect"],
        help="Submit the pending Work result and return the next action",
    )
    coordinator_submit.add_argument(
        "--result",
        type=Path,
        help="Structured result path; defaults to the generated Work exchange destination",
    )
    coordinator_submit.add_argument(
        "--reacquire",
        action="store_true",
        help="Discard a failed pending PROVENANCE_AUDIT run and prepare a fresh Work exchange",
    )
    next_action = commands.add_parser(
        "next-action",
        aliases=["next_action"],
        help="Alias for coordinator next",
    )
    next_action.add_argument("--no-advance", action="store_true")
    work = commands.add_parser("work")
    work_commands = work.add_subparsers(dest="work_command", required=True)
    collect = work_commands.add_parser("collect")
    collect.add_argument("run_id")
    collect.add_argument("--result", type=Path, required=True)
    collect.add_argument("--run-limit", type=int, default=10)
    publication = commands.add_parser("publication", help="Update the independent Publication Lane")
    publication_commands = publication.add_subparsers(dest="publication_command", required=True)
    publication_commands.add_parser(
        "request-eligibility",
        help="Open an optional Publication-only Human Decision without blocking Research",
    )
    publication_commands.add_parser(
        "migrate-eligibility",
        help="Quarantine a pre-P2 unbound eligibility record and require a fresh Human decision",
    )
    refresh = publication_commands.add_parser("refresh", help="Refresh a provisional publication from current Research State")
    refresh.add_argument("--changes", type=Path, help="JSON array of PublicationStructureChange records")
    refresh.add_argument("--draft-sections", type=Path, help="JSON object mapping structure node IDs to draft text")
    writer_submit = publication_commands.add_parser("writer-submit", help="Persist a structured Publication Writer output")
    writer_submit.add_argument("--result", type=Path, required=True)
    provenance = commands.add_parser("provenance", help="Run explicit provenance-only Harness events")
    provenance_commands = provenance.add_subparsers(dest="provenance_command", required=True)
    provenance_audit = provenance_commands.add_parser("audit", help="Prepare a PROVENANCE_AUDIT Work boundary")
    provenance_audit_commands = provenance_audit.add_subparsers(dest="provenance_audit_command", required=True)
    provenance_audit_start = provenance_audit_commands.add_parser("start")
    provenance_audit_start.add_argument("--plan", type=Path, required=True)
    evidence = commands.add_parser("evidence", help="Migrate and inspect Research Evidence models")
    evidence_commands = evidence.add_subparsers(dest="evidence_command", required=True)
    evidence_migrate = evidence_commands.add_parser("migrate", help="Create an immutable v0.3 evidence state")
    evidence_migrate.add_argument("--state", type=Path, help="Legacy Research State JSON; defaults to the current head")
    contracts = commands.add_parser(
        "contracts",
        aliases=["contract"],
        help="Refresh live contract and runtime-policy records without reinitializing the workspace",
    )
    contracts_commands = contracts.add_subparsers(dest="contracts_command", required=True)
    contracts_commands.add_parser(
        "refresh",
        aliases=["migrate"],
        help="Run an explicit CONTRACT_MIGRATION_REVIEW event",
    )
    conversation = commands.add_parser("conversation", help="Typed Work-chat control-plane actions")
    conversation_commands = conversation.add_subparsers(dest="conversation_command", required=True)
    conversation_commands.add_parser("status")
    propose = conversation_commands.add_parser("propose")
    propose.add_argument("--actor", required=True)
    propose.add_argument("--turn-id")
    propose.add_argument("--action")
    propose.add_argument("--text", default="")
    propose.add_argument("--parameters", help="JSON object or path to a JSON object")
    confirm = conversation_commands.add_parser("confirm")
    confirm.add_argument("confirmation_id")
    confirm.add_argument("--by", dest="actor", required=True)
    run = commands.add_parser("run", help="Operational Run controls")
    run_commands = run.add_subparsers(dest="run_command", required=True)
    abort = run_commands.add_parser("abort")
    abort.add_argument("run_id")
    abort.add_argument("--reason", required=True)
    abort.add_argument("--by", dest="actor", required=True)
    abort.add_argument("--no-replacement", action="store_true")
    recovery = commands.add_parser("recovery", help="Append-only Harness Recovery")
    recovery_commands = recovery.add_subparsers(dest="recovery_command", required=True)
    recovery_request = recovery_commands.add_parser("request")
    recovery_request.add_argument("--request", type=Path, required=True)
    recovery_show = recovery_commands.add_parser("show")
    recovery_show.add_argument("recovery_id")
    recovery_approve = recovery_commands.add_parser("approve")
    recovery_approve.add_argument("recovery_id")
    recovery_approve.add_argument("--by", dest="actor", required=True)
    recovery_approve.add_argument("--treatment", action="append", default=[], help="DECISION_ID=TREATMENT")
    recovery_approve.add_argument("--treatments", type=Path, help="JSON object mapping Decision IDs to treatments")
    recovery_replay = recovery_commands.add_parser("replay")
    recovery_replay.add_argument("recovery_id")
    locks = commands.add_parser("locks", help="Inspect or explicitly release transition locks")
    locks_commands = locks.add_subparsers(dest="locks_command", required=True)
    locks_commands.add_parser("status")
    release_lock = locks_commands.add_parser("release")
    release_lock.add_argument("name", choices=["discovery-transition", "publication-transition"])
    release_lock.add_argument("--by", dest="actor", required=True)
    release_lock.add_argument("--reason", required=True)
    release_lock.add_argument("--owner-token")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return _dispatch(argv)
    except Exception as error:  # noqa: BLE001 - CLI boundary converts operational failures to stable exit codes.
        print(json.dumps({
            "status": "ERROR",
            "error_type": type(error).__name__,
            "error": str(error),
        }, ensure_ascii=False), file=sys.stderr)
        return EXIT_ERROR


def _dispatch(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    if args.command == "new":
        _print(new_workspace(
            root,
            template_root=args.template_root,
            theme=args.theme,
            expectations=args.expectations,
            worker_backend=args.worker_backend,
            initial_drop=args.drop,
            profile_source=args.profile_source,
            profile_ref=args.profile_ref,
            init_git=args.init_git,
        ))
        return EXIT_SUCCESS
    if args.command == "upgrade":
        _print(upgrade_workspace(
            root,
            harness_source=args.harness_source,
            harness_ref=args.harness_ref,
            profile_source=args.profile_source,
            profile_ref=args.profile_ref,
        ))
        return EXIT_SUCCESS
    if args.command == "archive" and args.verify is not None:
        _print(verify_archive(args.verify).model_dump(mode="json"))
        return EXIT_SUCCESS
    orchestrator = DiscoveryOrchestrator(root)
    if args.command == "init":
        orchestrator.initialize(theme=args.theme, expectations=args.expectations, seed=args.seed, worker_backend=args.worker_backend)
        _print({"status": "INITIALIZED", "root": str(root)})
    elif args.command == "attention" and args.attention_command == "ingest":
        manifest = orchestrator.register_attention_drop(args.path, registered_by=args.registered_by)
        _print(manifest.model_dump(mode="json"))
    elif args.command == "archive":
        if args.destination is None or not args.created_by or not args.reason:
            raise SystemExit("archive creation requires --destination, --by, and --reason")
        manifest = orchestrator.archive(
            args.destination,
            created_by=args.created_by,
            reason=args.reason,
            allow_incomplete=args.allow_incomplete,
        )
        _print(manifest.model_dump(mode="json"))
    elif args.command == "seed" and args.seed_command == "register":
        state = orchestrator.attach_prior_seed(args.path)
        _print({"status": "SEED_REGISTERED", "artifact_id": "rq-seed", "phase": state.phase})
    elif args.command == "status":
        _print(orchestrator.status().model_dump(mode="json"))
    elif args.command == "plan":
        plan = orchestrator.plan()
        _print(_plan_json(plan) if plan else {"status": "STOPPED", "reason": _stop_reason(orchestrator.status())})
    elif args.command == "continue":
        state = orchestrator.continue_until_stop(run_limit=args.run_limit)
        _print(state.model_dump(mode="json"))
        return _state_exit_code(state)
    elif args.command == "decisions" and args.decisions_command == "migrate-kinds":
        _print(orchestrator.migrate_decision_kinds(_read_json(args.mapping)))
    elif args.command == "decisions":
        state = orchestrator.status()
        _print({
            "pending_decision_ids": state.pending_decision_ids,
            "publication_pending_decision_ids": orchestrator.publication_state().pending_decision_ids,
        })
    elif args.command == "decision" and args.decision_command == "show":
        _validate_identifier(args.decision_id, "decision_id")
        print((root / ".rh" / "decisions" / args.decision_id / "request.md").read_text(encoding="utf-8"), end="")
    elif args.command == "decision" and args.decision_command == "record":
        _validate_identifier(args.decision_id, "decision_id")
        state = orchestrator.record_decision(
            args.decision_id, choice=args.choice, decided_by=args.decided_by,
            conditions=args.condition, rationale=args.rationale,
        )
        _print(state.model_dump(mode="json"))
    elif args.command == "runs" and args.runs_command == "show":
        _validate_identifier(args.run_id, "run_id")
        _print(_read_json(root / ".rh" / "runs" / args.run_id / "manifest.json"))
    elif args.command == "context" and args.context_command == "show":
        _validate_identifier(args.run_id, "run_id")
        match = None
        for path in (root / ".rh" / "context_packs").glob("*/manifest.json"):
            candidate = _read_json(path)
            if candidate["run_id"] == args.run_id:
                match = candidate
                break
        if match is None:
            raise SystemExit(f"no Context Pack found for run {args.run_id!r}")
        _print(match)
    elif args.command == "validate":
        _print(validate_workspace(root))
    elif args.command in {"coordinator", "coordinate"}:
        coordinator_client = InteractiveWorkResearchCoordinator(root, orchestrator=orchestrator)
        if args.coordinator_command == "next":
            action = coordinator_client.next_action(advance=not args.no_advance)
        else:
            action = coordinator_client.submit_result(args.result, reacquire=args.reacquire)
        _print(action.model_dump(mode="json"))
        return _action_exit_code(action.state)
    elif args.command in {"next-action", "next_action"}:
        action = InteractiveWorkResearchCoordinator(root, orchestrator=orchestrator).next_action(
            advance=not args.no_advance,
        )
        _print(action.model_dump(mode="json"))
        return _action_exit_code(action.state)
    elif args.command == "work" and args.work_command == "collect":
        _validate_identifier(args.run_id, "run_id")
        state = orchestrator.collect_work_result(
            args.run_id, args.result, run_limit=args.run_limit,
        )
        _print(state.model_dump(mode="json"))
        return _state_exit_code(state)
    elif args.command == "publication" and args.publication_command == "request-eligibility":
        state = orchestrator.request_publication_eligibility()
        _print(state.model_dump(mode="json"))
        return EXIT_HUMAN_DECISION_WAIT if state.pending_decision_ids else EXIT_SUCCESS
    elif args.command == "publication" and args.publication_command == "migrate-eligibility":
        _print(orchestrator.migrate_publication_eligibility())
    elif args.command == "publication" and args.publication_command == "refresh":
        changes = None
        if args.changes:
            changes = [PublicationStructureChange.model_validate(item) for item in _read_json(args.changes)]
        draft_sections = _read_json(args.draft_sections) if args.draft_sections else None
        _print(orchestrator.refresh_publication(
            changes=changes, draft_sections=draft_sections,
        ).model_dump(mode="json"))
    elif args.command == "publication" and args.publication_command == "writer-submit":
        output = PublicationWriterOutput.model_validate(_read_json(args.result))
        _print(orchestrator.apply_publication_writer_output(output).model_dump(mode="json"))
    elif (
        args.command == "provenance"
        and args.provenance_command == "audit"
        and args.provenance_audit_command == "start"
    ):
        _print(orchestrator.start_provenance_audit(args.plan).model_dump(mode="json"))
    elif args.command == "evidence" and args.evidence_command == "migrate":
        _print(orchestrator.migrate_evidence_model(args.state).model_dump(mode="json"))
    elif args.command in {"contracts", "contract"} and args.contracts_command in {"refresh", "migrate"}:
        _print(orchestrator.refresh_contract_registry().model_dump(mode="json"))
    elif args.command == "conversation" and args.conversation_command == "status":
        _print(WorkConversationCoordinator(root).status().model_dump(mode="json"))
    elif args.command == "conversation" and args.conversation_command == "propose":
        parameters = _parameters(args.parameters)
        client = WorkConversationCoordinator(root)
        if args.action:
            result = client.propose_action(args.action, actor=args.actor, turn_id=args.turn_id, parameters=parameters)
        else:
            result = client.propose(ChatTurnInput(turn_id=args.turn_id or "cli-turn", actor=args.actor, text=args.text, parameters=parameters))
        _print(result.model_dump(mode="json"))
    elif args.command == "conversation" and args.conversation_command == "confirm":
        _print(WorkConversationCoordinator(root).confirm(args.confirmation_id, actor=args.actor).model_dump(mode="json"))
    elif args.command == "run" and args.run_command == "abort":
        _print(RecoveryService(root).abort_pending_run(
            args.run_id, reason=args.reason, actor=args.actor, replacement=not args.no_replacement,
        ).model_dump(mode="json"))
    elif args.command == "recovery" and args.recovery_command == "request":
        _print(RecoveryService(root).request(RecoveryRequest.model_validate(_read_json(args.request))).model_dump(mode="json"))
    elif args.command == "recovery" and args.recovery_command == "show":
        _print(RecoveryService(root).show(args.recovery_id))
    elif args.command == "recovery" and args.recovery_command == "approve":
        treatments: dict[str, str] = {}
        if args.treatments:
            treatments.update({str(key): str(value) for key, value in _read_json(args.treatments).items()})
        for item in args.treatment:
            if "=" not in item:
                raise SystemExit("--treatment must use DECISION_ID=TREATMENT")
            key, value = item.split("=", 1)
            treatments[key] = value
        _print(RecoveryService(root).approve(args.recovery_id, decided_by=args.actor, decision_treatments=treatments).model_dump(mode="json"))
    elif args.command == "recovery" and args.recovery_command == "replay":
        _print(RecoveryService(root).replay(args.recovery_id).model_dump(mode="json"))
    elif args.command == "locks" and args.locks_command == "status":
        _print(orchestrator.transition_lock_status())
    elif args.command == "locks" and args.locks_command == "release":
        _print(orchestrator.release_transition_lock(
            args.name, actor=args.actor, reason=args.reason, owner_token=args.owner_token,
        ))
    return EXIT_SUCCESS


def validate_workspace(root: Path) -> dict[str, object]:
    runtime = root / ".rh"
    state = OrchestratorState.model_validate(_read_json(runtime / "state" / "orchestrator" / "head.json"))
    ResearchState.model_validate(_read_json(runtime / "state" / "research" / "head.json"))
    PublicationState.model_validate(_read_json(runtime / "state" / "publication" / "head.json"))
    registry = ArtifactRegistry.model_validate(_read_json(runtime / "registry" / "artifact_registry.json"))
    policy = ArtifactAccessPolicy(root / "contracts" / "runtime_artifact_policy.yaml")
    registry_by_id = {item.artifact_id: item for item in registry.artifacts}
    if state.active_attention_map_id:
        active = registry_by_id.get(state.active_attention_map_id)
        if active is None or active.role != "ATTENTION_PUBLICATION_MAP" or active.status in {"INVALIDATED", "SUPERSEDED"}:
            raise ValueError("active Attention Map pointer is missing, invalid, or superseded")
    for artifact in registry.artifacts:
        if not policy.is_known_role(artifact.role):
            raise ValueError(f"artifact {artifact.artifact_id!r} has unknown role {artifact.role!r}")
        if not artifact.runtime_policy:
            raise ValueError(f"artifact {artifact.artifact_id!r} has no explicit runtime policy")
        if artifact.sha256 is None:
            raise ValueError(f"artifact {artifact.artifact_id!r} has no SHA-256")
        verify_hash(Path(artifact.path), artifact.sha256)
    run_count = 0
    for path in (runtime / "runs").glob("*/manifest.json"):
        RunManifest.model_validate(_read_json(path))
        run_count += 1
    pack_count = 0
    for path in (runtime / "context_packs").glob("*/manifest.json"):
        ContextPackManifest.model_validate(_read_json(path))
        pack_count += 1
    return {
        "status": "VALID",
        "phase": state.phase,
        "artifacts": len(registry.artifacts),
        "runs": run_count,
        "context_packs": pack_count,
    }


def _plan_json(plan: NextRunPlan) -> dict[str, object]:
    return {
        "task_type": plan.task_type,
        "event": plan.event,
        "objective": plan.objective,
        "artifact_ids": plan.artifact_ids,
        "required_ids": sorted(plan.required_ids),
    }


def _stop_reason(state: OrchestratorState) -> str:
    if state.pending_decision_ids:
        return "HUMAN_DECISION_PENDING"
    if state.pending_work:
        return "WORK_EXECUTION_REQUIRED"
    if state.terminal:
        return "TERMINAL"
    return "NO_RUNNABLE_WORK"


def _state_exit_code(state: OrchestratorState) -> int:
    if state.pending_decision_ids:
        return EXIT_HUMAN_DECISION_WAIT
    if state.pending_work:
        return EXIT_WORK_WAIT
    return EXIT_SUCCESS


def _action_exit_code(state: str) -> int:
    if state == "DECISION_REQUIRED":
        return EXIT_HUMAN_DECISION_WAIT
    if state == "WORK_EXECUTION_REQUIRED":
        return EXIT_WORK_WAIT
    if state in {"ERROR", "BLOCKED"}:
        return EXIT_ERROR
    return EXIT_SUCCESS


def _validate_identifier(value: str, label: str) -> None:
    import re

    if not re.fullmatch(SAFE_IDENTIFIER_PATTERN, value):
        raise ValueError(f"unsafe {label}: {value!r}")


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _parameters(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    candidate = Path(value)
    if candidate.is_file():
        data = _read_json(candidate)
    else:
        data = json.loads(value)
    if not isinstance(data, dict):
        raise SystemExit("--parameters must be a JSON object or a JSON file containing an object")
    return data


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
