from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import rfc8785

from plugins.desktop_research import DesktopResearchExternalAdapter, build_result_extension
from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalResearchApplication
from plugins.local_application.cli import main as cli_main
from runtime_fixtures import project, rq, seed_state


ROOT = Path(__file__).resolve().parents[2]
PROJECT_FIXTURE = ROOT / "projects/fixtures/valid/generic-project-config.json"
PROFILE_FIXTURE = ROOT / "profiles/fixtures/valid/effective-profile-set.json"
DESCRIPTOR = json.loads(
    (ROOT / "core/packages/desktop-research/desktop-research-capability-descriptor.json").read_text(encoding="utf-8")
)


class NullResolver:
    def resolve(self, *_args, **_kwargs):
        return None


def profile_provider(_project_ref, expected_digest):
    return {
        "schema_version": "0.1.0",
        "core_contracts": {"research_contract": "0.1.0", "invariant_contract": "0.1.0"},
        "profile_pins": [{
            "profile_id": "fixture.research",
            "profile_type": "research",
            "profile_version": "1.0.0",
            "manifest_sha256": "1" * 64,
        }],
        "content_digest": expected_digest,
    }


def refresh(document: dict, field: str) -> dict:
    payload = deepcopy(document)
    payload.pop(field, None)
    document[field] = "sha256:" + hashlib.sha256(rfc8785.dumps(payload)).hexdigest()
    return document


def run_cli(argv, stdin_text=""):
    stream = io.StringIO()
    with patch("sys.stdin", io.StringIO(stdin_text)), redirect_stdout(stream):
        code = cli_main(argv)
    raw = stream.getvalue()
    return code, json.loads(raw)


def bootstrap_config() -> dict:
    config = json.loads(PROJECT_FIXTURE.read_text(encoding="utf-8"))
    config["research_questions"]["references"] = []
    for attention in config["research_attention"]:
        attention.pop("related_question_ids", None)
    value = deepcopy(config)
    value.pop("configuration_digest", None)
    config["configuration_digest"] = "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()
    return config


def write_workspace_inputs(root: Path) -> tuple[Path, Path]:
    config = root / "project-config-input.json"
    profiles = root / "profiles-input.json"
    config.write_text(json.dumps(bootstrap_config()), encoding="utf-8")
    profiles.write_text(PROFILE_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    return config, profiles


def adopt_rq(facade: LocalApplicationFacade) -> str:
    proposed = facade.submit_action({
        "action_type": "research_question.propose",
        "payload": {
            "text": "Which current conditions materially shape the research target?",
            "acceptance_criteria": ["Relevant current conditions can be compared."],
            "scope_limits": ["Do not infer beyond gathered evidence."],
            "derived_from_seed_ids": ["RQ-SEED-001"],
        },
        "actor_id": "HUMAN-PR35",
    })
    rq_id = proposed["data"]["research_question_candidate"]["id"]
    pending = facade.submit_action({
        "action_type": "state.apply_candidate",
        "payload": {"state_delta_proposal_id": proposed["data"]["state_delta_proposal_id"]},
        "actor_id": "HUMAN-PR35",
    })
    decision = facade.submit_confirmation({
        "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
        "actor_id": "HUMAN-PR35",
    })["decision_request"]
    resolved = facade.resolve_human_decision({
        "request_id": decision["request_id"],
        "request_digest": decision["request_digest"],
        "disposition": "approve_exact",
        "actor_id": "HUMAN-PR35",
    })
    assert resolved["status"] == "RESOLVED"
    return rq_id


def golden_submission(app, run_id: str, capture: dict) -> tuple[dict, dict]:
    run = app.execution_store.load_run(run_id)
    assert run is not None
    context = app.execution_store.load_context_pack(run.context_pack_id)
    invocation = app.execution_store.load_invocation(run.invocation_id)
    assert context is not None and invocation is not None
    handoff = {
        "schema_version": "0.1.0",
        "handoff_id": f"HND-{run_id}",
        "invocation_id": run.invocation_id,
        "run_id": run_id,
        "project_id": run.project_ref,
        "capability": deepcopy(invocation["capability"]),
        "execution_mode": "real",
        "input_pins": {
            "invocation_digest": run.invocation_digest,
            "context_pack_digest": run.context_pack_digest,
            "project_config_digest": context["pins"]["project_config"]["configuration_digest"],
            "effective_profile_set_digest": context["pins"]["effective_profile_set"]["content_digest"],
            "research_snapshot": deepcopy(context["pins"]["research_snapshot"]),
        },
        "preserved_context": {
            "research_attention_ids": [item["attention_id"] for item in context["research_attention"]],
            "project_guard_ids": [],
            "effective_constraint_paths": [],
        },
        "validation": {"status": "valid", "issues": []},
        "outputs": {
            "observations": [{
                "observation_id": "OBS-NULL",
                "statement": "No additional relevant counter source was found in the bounded search.",
                "epistemic_mode": "empirical",
            }],
            "source_captures": [{
                "capture_id": "CAP-1",
                "origin": {
                    "origin_type": "acquired_source",
                    "acquisition_locator": "https://example.test/source-a",
                },
                "locator": "https://example.test/source-a#section-1",
                "content_digest": capture["original_capture"]["content_digest"],
            }],
            "evidence_candidates": [{
                "evidence_candidate_id": "EVC-1",
                "statement": "Captured support candidate.",
                "source_basis": {"basis_type": "source_capture", "capture_id": "CAP-1"},
                "locator": "https://example.test/source-a#quote-1",
                "epistemic_mode": "empirical",
                "limitations": ["Candidate only; not verified Evidence."],
            }],
            "candidate_findings": [{
                "candidate_finding_id": "CF-1",
                "question_ids": list(context["question_ids"]),
                "statement": "The bounded material supports a candidate conclusion but counter coverage remains incomplete.",
                "supporting_evidence_candidate_ids": ["EVC-1"],
                "counterevidence_candidate_ids": [],
                "boundary_conditions": ["Bounded external retrieval only."],
                "limitations": ["Counter-source coverage remains incomplete."],
                "epistemic_mode": "empirical",
            }],
            "counterevidence": [],
            "conflicts": [],
            "unknowns": [],
            "evidence_gaps": [{
                "gap_id": "GAP-1",
                "statement": "Additional counter-source coverage remains material.",
                "question_ids": list(context["question_ids"]),
            }],
            "candidate_next_actions": [],
            "candidate_next_methods": [],
        },
        "provenance": {
            "trace_id": invocation["trace"]["trace_id"],
            "produced_at": "2026-08-31T00:00:00Z",
            "implementation_id": DesktopResearchExternalAdapter.implementation_id,
            "implementation_version": DesktopResearchExternalAdapter.implementation_version,
            "input_content_digests": [
                DESCRIPTOR["descriptor_digest"],
                run.context_pack_digest,
                run.invocation_digest,
            ],
        },
        "adoption_boundary": {
            "research_state_mutation_performed": False,
            "outputs_are_candidates": True,
            "human_decision_required_for_authoritative_transition": True,
        },
    }
    refresh(handoff, "handoff_digest")
    extension = build_result_extension(
        handoff,
        context,
        source_capture_details=[capture],
        citation_details=[{
            "citation_id": "CIT-1",
            "handoff_output_kind": "evidence_candidate",
            "handoff_output_id": "EVC-1",
            "capture_id": "CAP-1",
            "excerpt": "exact supporting excerpt",
            "excerpt_locator": "https://example.test/source-a#quote-1",
            "text_rendition_digest": capture["text_rendition"]["content_digest"],
            "capture_integrity_verified": True,
            "excerpt_containment_verified": True,
            "evidence_adoption_performed": False,
        }],
        search_trace={
            "entries": [
                {
                    "trace_entry_id": "ATT-1",
                    "strategy": "support search",
                    "coverage_dimension_ids": ["COV-SUPPORT"],
                    "outcome": "source_captured",
                    "related_handoff_output_ids": ["EVC-1"],
                    "source_capture_ids": ["CAP-1"],
                },
                {
                    "trace_entry_id": "ATT-2",
                    "strategy": "counter search",
                    "coverage_dimension_ids": ["COV-COUNTER"],
                    "outcome": "no_relevant_source",
                    "related_handoff_output_ids": ["OBS-NULL", "GAP-1"],
                    "source_capture_ids": [],
                },
            ],
            "unsuccessful_entry_ids": ["ATT-2"],
        },
        null_results=[{
            "null_id": "NULL-1",
            "statement": "No additional relevant counter source was found.",
            "question_ids": list(context["question_ids"]),
            "handoff_projection": {"output_kind": "observation", "output_id": "OBS-NULL"},
        }],
        evidence_gap_assessments=[{
            "gap_id": "GAP-1",
            "materiality": "material",
            "coverage_dimension_ids": ["COV-COUNTER"],
            "rationale": "Counter-source coverage remains incomplete.",
        }],
        coverage_assessment={
            "dimensions": [
                {
                    "dimension_id": "COV-SUPPORT",
                    "status": "covered",
                    "trace_entry_ids": ["ATT-1"],
                    "rationale": "Captured support.",
                },
                {
                    "dimension_id": "COV-COUNTER",
                    "status": "uncovered",
                    "trace_entry_ids": ["ATT-2"],
                    "rationale": "Attempt completed with no relevant counter source.",
                },
            ],
            "saturation": {"level": "low", "rationale": "Counter coverage remains incomplete."},
            "remaining_information_value": {"level": "high", "rationale": "A material gap remains."},
            "stopping_recommendation": {
                "stop_recommended": False,
                "basis": ["coverage", "saturation", "evidence_gaps", "remaining_information_value"],
                "rationale": "Continue research if operationally possible.",
                "research_completion_claimed": False,
                "human_decision_performed": False,
            },
        },
        candidate_next_method_ids=[],
    )
    return handoff, extension


class ExternalDesktopResearchIntakeTests(unittest.TestCase):
    def make_facade(self, root: Path):
        seed = seed_state(
            objects=[project(), rq(state="approved")],
            mode="real",
            snapshot_id="SNP-PR35-0",
        )
        app = LocalResearchApplication(
            root / ".research-loom",
            resolver=NullResolver(),
            effective_profile_set_provider=profile_provider,
            seed_state=seed,
        )
        return app, LocalApplicationFacade(app, "PRJ-1", workspace_root=root)

    def prepare(self, facade: LocalApplicationFacade):
        return facade.submit_action({
            "action_type": "desktop_research.investigate",
            "payload": {"question_id": "RQ-1", "purpose": "PR35 external intake production test."},
        })

    def write_capture_files(self, root: Path):
        raw = root / "captures/raw/source-a.html"
        text = root / "captures/text/source-a.txt"
        raw.parent.mkdir(parents=True, exist_ok=True)
        text.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(b"<html>original source A bytes</html>")
        text.write_text("Source A contains the exact supporting excerpt used here.", encoding="utf-8")

    def test_facade_external_attempt_capture_collect_is_candidate_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade = self.make_facade(root)
            try:
                prepared = self.prepare(facade)
                run_id = prepared["run_id"]
                before = app.state_repository.load_state_view("PRJ-1", "LIN-1").current_snapshot
                facade.start_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-1",
                    "strategy": "support search",
                    "coverage_dimension_ids": ["COV-SUPPORT"],
                    "query_or_target": "support terms",
                    "provider_or_tool": "external_operator",
                    "target_locator": "https://example.test/source-a",
                    "provenance": {"reason": "known source"},
                })
                self.write_capture_files(root)
                captured = facade.capture_external_source(run_id, {
                    "capture_id": "CAP-1",
                    "source_category": "other",
                    "exact_locator": "https://example.test/source-a#section-1",
                    "acquired_at": "2026-08-31T00:00:00Z",
                    "original_file": "captures/raw/source-a.html",
                    "original_media_type": "text/html",
                    "text_rendition_file": "captures/text/source-a.txt",
                    "provenance": {"retrieval_method": "external_operator"},
                })["capture"]
                facade.complete_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-1",
                    "outcome": "source_captured",
                    "target_locator": "https://example.test/source-a",
                    "resulting_capture_id": "CAP-1",
                    "provenance": {},
                })
                facade.start_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-2",
                    "strategy": "counter search",
                    "coverage_dimension_ids": ["COV-COUNTER"],
                })
                facade.complete_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-2",
                    "outcome": "no_relevant_source",
                    "provenance": {},
                })

                handoff, extension = golden_submission(app, run_id, captured)
                result = facade.collect_external(run_id, {"handoff": handoff, "extension": extension})
                after = app.state_repository.load_state_view("PRJ-1", "LIN-1").current_snapshot

                self.assertEqual(result["status"], "CAPABILITY_RESULT_COLLECTED")
                self.assertTrue(result["execution_result"]["state_delta_proposal"]["candidate_only"])
                self.assertEqual(
                    (before["id"], before["content_digest"]),
                    (after["id"], after["content_digest"]),
                )
                artifacts = app.execution_store.artifacts_for(run_id)
                self.assertEqual(len(artifacts), 2)
                original = next(item for item in artifacts if item.role == "desktop_research.original_capture")
                text = next(item for item in artifacts if item.role == "desktop_research.text_rendition")
                self.assertEqual(original.size, len(b"<html>original source A bytes</html>"))
                self.assertEqual(original.digest, captured["original_capture"]["content_digest"])
                self.assertEqual(text.provenance["parent_artifact_refs"], [original.artifact_id])
            finally:
                facade.close()

    def test_cli_operations_survive_process_style_reopen(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path, profile_path = write_workspace_inputs(root)
            workspace = root / "workspace"
            code, initialized = run_cli([
                "init", "--workspace", str(workspace),
                "--project-config", str(config_path),
                "--effective-profile-set", str(profile_path), "--json",
            ])
            self.assertEqual((code, initialized["status"]), (0, "INITIALIZED"))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                rq_id = adopt_rq(facade)
            code, prepared = run_cli(
                ["action", "submit", "--workspace", str(workspace), "--json", "-"],
                json.dumps({
                    "action_type": "desktop_research.investigate",
                    "payload": {"question_id": rq_id, "purpose": "CLI external intake."},
                }),
            )
            self.assertEqual(code, 0)
            run_id = prepared["run_id"]
            code, started = run_cli(
                ["external", "attempt", "start", "--workspace", str(workspace), "--run-id", run_id, "--json", "-"],
                json.dumps({
                    "attempt_id": "ATT-CLI",
                    "strategy": "blocked fetch",
                    "coverage_dimension_ids": ["COV-SUPPORT"],
                    "target_locator": "https://example.test/restricted",
                }),
            )
            self.assertEqual((code, started["status"]), (0, "EXTERNAL_ATTEMPT_STARTED"))
            code, completed = run_cli(
                ["external", "attempt", "complete", "--workspace", str(workspace), "--run-id", run_id, "--json", "-"],
                json.dumps({
                    "attempt_id": "ATT-CLI",
                    "outcome": "blocked",
                    "target_locator": "https://example.test/restricted",
                    "failure_or_blocking_reason": "JavaScript/cookie challenge",
                    "provenance": {},
                }),
            )
            self.assertEqual((code, completed["status"]), (0, "EXTERNAL_ATTEMPT_COMPLETED"))
            self.assertEqual(completed["attempt"]["outcome"], "blocked")
            self.assertEqual(completed["attempt"]["failure_or_blocking_reason"], "JavaScript/cookie challenge")

    def test_unsafe_files_untrusted_metadata_and_invalid_utf8_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside_temp:
            root = Path(temp)
            outside = Path(outside_temp)
            app, facade = self.make_facade(root)
            try:
                run_id = self.prepare(facade)["run_id"]
                self.write_capture_files(root)
                base = {
                    "capture_id": "CAP-X",
                    "source_category": "other",
                    "exact_locator": "https://example.test/x",
                    "acquired_at": "2026-08-31T00:00:00Z",
                    "original_file": "captures/raw/source-a.html",
                    "original_media_type": "text/html",
                    "text_rendition_file": "captures/text/source-a.txt",
                }
                with self.assertRaises(LocalApplicationError) as untrusted:
                    facade.capture_external_source(run_id, {**base, "digest": "sha256:" + "0" * 64})
                self.assertEqual(untrusted.exception.code, "APPLICATION-EXTERNAL-INPUT-001")
                with self.assertRaises(LocalApplicationError) as nested:
                    facade.capture_external_source(run_id, {**base, "provenance": {"storage_locator": "fake://x"}})
                self.assertEqual(nested.exception.code, "APPLICATION-EXTERNAL-INPUT-001")
                with self.assertRaises(LocalApplicationError) as traversal:
                    facade.capture_external_source(run_id, {**base, "original_file": "../outside.bin"})
                self.assertEqual(traversal.exception.code, "APPLICATION-EXTERNAL-FILE-001")
                escaped = outside / "outside.bin"
                escaped.write_bytes(b"outside")
                with self.assertRaises(LocalApplicationError) as absolute:
                    facade.capture_external_source(run_id, {**base, "original_file": str(escaped)})
                self.assertEqual(absolute.exception.code, "APPLICATION-EXTERNAL-FILE-001")
                bad_text = root / "captures/text/bad.txt"
                bad_text.write_bytes(b"\xff\xfe")
                with self.assertRaises(LocalApplicationError) as utf8:
                    facade.capture_external_source(run_id, {**base, "text_rendition_file": "captures/text/bad.txt"})
                self.assertEqual(utf8.exception.code, "APPLICATION-EXTERNAL-UTF8-001")
            finally:
                facade.close()

    def test_attempt_invariants_wrong_run_and_failed_collect_preserve_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade = self.make_facade(root)
            try:
                run_id = self.prepare(facade)["run_id"]
                with self.assertRaises(LocalApplicationError) as unknown:
                    facade.start_external_retrieval_attempt("RUN-MISSING", {
                        "attempt_id": "ATT-X", "strategy": "x", "coverage_dimension_ids": ["COV-SUPPORT"]
                    })
                self.assertEqual(unknown.exception.code, "APPLICATION-EXTERNAL-RUN-001")
                facade.start_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-1", "strategy": "support search", "coverage_dimension_ids": ["COV-SUPPORT"]
                })
                with self.assertRaises(LocalApplicationError) as invalid:
                    facade.complete_external_retrieval_attempt(run_id, {
                        "attempt_id": "ATT-1", "outcome": "blocked", "resulting_capture_id": "CAP-X",
                        "failure_or_blocking_reason": "blocked"
                    })
                self.assertEqual(invalid.exception.code, "APPLICATION-EXTERNAL-ATTEMPT-001")
                self.write_capture_files(root)
                facade.capture_external_source(run_id, {
                    "capture_id": "CAP-1", "source_category": "other",
                    "exact_locator": "https://example.test/source-a#section-1",
                    "acquired_at": "2026-08-31T00:00:00Z",
                    "original_file": "captures/raw/source-a.html", "original_media_type": "text/html",
                    "text_rendition_file": "captures/text/source-a.txt",
                })
                facade.complete_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-1", "outcome": "source_captured", "resulting_capture_id": "CAP-1"
                })
                before = app.state_repository.load_state_view("PRJ-1", "LIN-1").current_snapshot
                failed = facade.collect_external(run_id, {"handoff": {"invalid": True}, "extension": {}})
                after = app.state_repository.load_state_view("PRJ-1", "LIN-1").current_snapshot
                self.assertIsNone(failed.get("state_delta_proposal"))
                self.assertEqual(len(app.execution_store.artifacts_for(run_id)), 2)
                self.assertEqual(len(app.operational_store.events_for(run_id)), 2)
                self.assertEqual(
                    (before["id"], before["content_digest"]),
                    (after["id"], after["content_digest"]),
                )
            finally:
                facade.close()


if __name__ == "__main__":
    unittest.main()
