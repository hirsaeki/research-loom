from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import rfc8785
import yaml

from plugins.local_application import LocalApplicationFacade
from plugins.local_application.profile_resolution import resolve_effective_profile_set
from plugins.local_application.research_quality_evaluation import (
    ResearchQualityEvaluationError,
    evaluate,
    normalize_input,
)
from runtime_fixtures import seed_state
from tests.runtime.test_external_desktop_research_intake import adopt_rq, bootstrap_config, run_cli


ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "profiles/fixtures/research-quality/valid/generic-research-quality.profile.json"
CASES = ROOT / "profiles/fixtures/research-quality/semantic/cases.json"
POLICY = ROOT / "profiles/contracts/research-quality-policy.yaml"
PROJECT_FIXTURE = ROOT / "projects/fixtures/valid/generic-project-config.json"
ORG_PROFILE = ROOT / "profiles/fixtures/valid/organization.profile.json"
ORG_RESEARCH_BASE = ROOT / "profiles/fixtures/valid/research-base.profile.json"
ORG_RESEARCH_STRICT = ROOT / "profiles/fixtures/valid/research-strict.profile.json"
ORG_RESEARCH_STRICT_LATEST = ROOT / "profiles/fixtures/valid/research-strict-1.2.0.profile.json"


def _effective_constraints(*, drop: str | None = None, organization: dict | None = None):
    manifest = json.loads(PROFILE.read_text(encoding="utf-8"))
    rows = {}
    for item in manifest["constraints"]:
        if item["path"] == drop:
            continue
        rows[item["path"]] = {
            "path": item["path"],
            "value": deepcopy(item["value"]),
            "merge_strategy": item["merge_strategy"],
            "provenance": [{
                "profile_id": manifest["profile_id"],
                "profile_type": "research",
                "profile_version": manifest["profile_version"],
                "constraint_id": item["id"],
            }],
        }
    if organization:
        rows[organization["path"]] = {
            "path": organization["path"],
            "value": deepcopy(organization.get("value", True)),
            "merge_strategy": organization.get("merge_strategy", "replace"),
            "provenance": [{
                "profile_id": "fixture.organization",
                "profile_type": "organization",
                "profile_version": "1.0.0",
                "constraint_id": "org-rule",
            }],
        }
    return rows


def _base():
    return json.loads(CASES.read_text(encoding="utf-8"))["base_state"]


def _basis(*object_ids: str):
    return {"object_ids": list(object_ids), "exhibit_ids": [], "run_ids": []}


def _semantic_input(base=None):
    base = deepcopy(base or _base())
    assessments = {"sources": {}, "evidence": {}, "claims": {}, "methods": {}, "sufficiency": {}}
    for group in ("sources", "evidence", "claims", "methods"):
        for subject_id, fields in base["assessments"][group].items():
            assessments[group][subject_id] = {
                field: {
                    "value": deepcopy(value),
                    "basis": _basis(subject_id),
                    "rationale": f"Synthetic explicit assessment for {subject_id}.{field}.",
                }
                for field, value in fields.items()
            }
    for field, value in base["sufficiency"].items():
        assessments["sufficiency"][field] = {
            "value": deepcopy(value),
            "basis": _basis("FND-1", "CR-1", "CR-2"),
            "rationale": f"Synthetic explicit sufficiency assessment for {field}.",
        }
    return {
        "rq_id": "RQ-1",
        "finding_id": "FND-1",
        "claim_id": "CLM-1",
        "method_id": "MTH-1",
        "assessments": assessments,
        "organization_assessments": {},
    }


def _state(*, base=None, constraints=None):
    base = deepcopy(base or _base())
    return seed_state(
        objects=list(base["objects"].values()),
        constraints=constraints if constraints is not None else _effective_constraints(),
        snapshot_id="SNP-RQ-EVAL",
    )


def _result_by_path(result):
    return {row["path"]: row for row in result["constraint_results"]}


def _organization_workspace_inputs(root: Path):
    config = bootstrap_config()
    config["profile_requests"] = {
        "research": [],
        "organization": [{
            "profile_id": "fixture.organization",
            "profile_type": "organization",
            "version": "2.0.0",
        }],
        "narrative": [],
        "publication": [],
    }
    payload = deepcopy(config)
    payload.pop("configuration_digest", None)
    config["configuration_digest"] = "sha256:" + hashlib.sha256(rfc8785.dumps(payload)).hexdigest()
    eps = resolve_effective_profile_set(
        config,
        [ORG_RESEARCH_BASE, ORG_RESEARCH_STRICT, ORG_RESEARCH_STRICT_LATEST, ORG_PROFILE],
    )
    cfg = root / "organization-project-config-input.json"
    eps_path = root / "organization-profiles-input.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    eps_path.write_text(json.dumps(eps), encoding="utf-8")
    return cfg, eps_path, eps


def _workspace_inputs(root: Path):
    config = bootstrap_config()
    config["profile_requests"] = {
        "research": [{
            "profile_id": "fixture.generic-research-quality",
            "profile_type": "research",
            "version": "1.0.0",
        }],
        "organization": [],
        "narrative": [],
        "publication": [],
    }
    payload = deepcopy(config)
    payload.pop("configuration_digest", None)
    config["configuration_digest"] = "sha256:" + hashlib.sha256(rfc8785.dumps(payload)).hexdigest()
    eps = resolve_effective_profile_set(config, [PROFILE])
    cfg = root / "project-config-input.json"
    eps_path = root / "profiles-input.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    eps_path.write_text(json.dumps(eps), encoding="utf-8")
    return cfg, eps_path, eps


class ResearchQualityApplicationTests(unittest.TestCase):
    def test_conformant_semantic_fixture_evaluates_all_configured_paths_without_mutation(self):
        state = _state()
        before = deepcopy(state.current_snapshot)
        result = evaluate(state, normalize_input(_semantic_input()))
        self.assertEqual(result["evaluation_status"], "conformant")
        self.assertEqual(len(result["constraint_results"]), 22)
        mapping = yaml.safe_load(
            (ROOT / "profiles/contracts/research-quality-application.yaml").read_text(encoding="utf-8")
        )
        expected_modes = {row["path"]: row["evaluation_mode"] for row in mapping["constraints"]}
        self.assertEqual(
            {row["path"]: row["verification_mode"] for row in result["constraint_results"]},
            expected_modes,
        )
        self.assertEqual(
            {row["path"]: row["configured_value"] for row in result["constraint_results"]},
            {path: row["value"] for path, row in _effective_constraints().items()},
        )
        self.assertEqual(state.current_snapshot, before)
        self.assertFalse(result["authoritative_state_changed"])
        self.assertFalse(result["human_decision_performed"])
        self.assertFalse(result["semantic_assessment_boundary"]["classification_truth_verified"])

    def test_missing_semantic_assessment_is_unevaluated_not_pass(self):
        value = _semantic_input()
        del value["assessments"]["sufficiency"]["remaining_information_value"]
        result = evaluate(_state(), normalize_input(value))
        row = _result_by_path(result)["research_quality.evidence_sufficiency.required_checks"]
        self.assertEqual(row["status"], "unevaluated")
        self.assertEqual(result["evaluation_status"], "unevaluated")

    def test_independence_double_count_is_a_violation(self):
        base = _base()
        base["objects"]["EVD-2"]["independence_group"] = "origin-a"
        result = evaluate(_state(base=base), normalize_input(_semantic_input(base)))
        row = _result_by_path(result)["research_quality.evidence.independence.requirements"]
        self.assertEqual(row["status"], "not_applicable")  # descriptive claims do not require independence

        value = _semantic_input(base)
        value["assessments"]["claims"]["CLM-1"]["claim_family"]["value"] = "causal"
        for evidence_id in ("EVD-1", "EVD-2"):
            value["assessments"]["evidence"][evidence_id]["support_scope"]["value"] = "causal_effect"
        result = evaluate(_state(base=base), normalize_input(value))
        row = _result_by_path(result)["research_quality.evidence.independence.requirements"]
        self.assertEqual(row["status"], "violation")
        self.assertIn("RESEARCH-QUALITY-INDEPENDENCE-001", row["diagnostic_codes"])

    def test_causal_overclaim_is_detected_and_constraint_ablation_changes_result(self):
        value = _semantic_input()
        value["assessments"]["claims"]["CLM-1"]["claim_family"]["value"] = "causal"
        for evidence_id in ("EVD-1", "EVD-2"):
            value["assessments"]["evidence"][evidence_id]["support_scope"]["value"] = "causal_effect"
        value["assessments"]["evidence"]["EVD-1"]["inference_bases"]["value"] = ["association_only"]
        normalized = normalize_input(value)
        full = evaluate(_state(), normalized)
        path = "research_quality.claim.causal.prohibited_inference_bases"
        self.assertEqual(_result_by_path(full)[path]["status"], "violation")

        ablated = evaluate(_state(constraints=_effective_constraints(drop=path)), normalized)
        self.assertNotIn(path, _result_by_path(ablated))
        self.assertNotEqual(full["evaluation_status"], ablated["evaluation_status"])

    def test_missing_finding_qualifier_and_source_count_only_stopping_do_not_pass(self):
        base = _base()
        base["objects"]["FND-1"]["limitations"] = []
        result = evaluate(_state(base=base), normalize_input(_semantic_input(base)))
        row = _result_by_path(result)["research_quality.finding.required_qualifier_fields"]
        self.assertEqual(row["status"], "violation")

        value = _semantic_input()
        del value["assessments"]["sufficiency"]["remaining_information_value"]
        result = evaluate(_state(), normalize_input(value))
        rows = _result_by_path(result)
        self.assertEqual(rows["research_quality.thresholds.material_finding.min_supporting_evidence_count"]["status"], "conformant")
        self.assertEqual(rows["research_quality.evidence_sufficiency.required_checks"]["status"], "unevaluated")
        self.assertEqual(result["evaluation_status"], "unevaluated")

    def test_missing_counter_review_lens_is_a_violation(self):
        base = _base()
        del base["objects"]["CR-2"]
        value = _semantic_input(base)
        for item in value["assessments"]["sufficiency"].values():
            item["basis"] = _basis("FND-1", "CR-1")
        result = evaluate(_state(base=base), normalize_input(value))
        row = _result_by_path(result)["research_quality.counter_review.required_lenses"]
        self.assertEqual(row["status"], "violation")
        self.assertIn("RESEARCH-QUALITY-COUNTER-REVIEW-001", row["diagnostic_codes"])

    def test_organization_assessment_rejects_non_string_status_as_input_error(self):
        value = _semantic_input()
        value["organization_assessments"]["organization.fixture.handling_rule"] = {
            "status": [],
            "basis": _basis("RQ-1"),
            "rationale": "Invalid non-string status must be normalized to an input error.",
        }
        with self.assertRaises(ResearchQualityEvaluationError) as caught:
            normalize_input(value)
        self.assertEqual(caught.exception.code, "APPLICATION-RESEARCH-QUALITY-INPUT-001")

    def test_organization_semantics_require_explicit_host_or_human_assessment(self):
        org = {"path": "organization.fixture.handling_rule", "value": ["fixture"]}
        state = _state(constraints={**_effective_constraints(), **_effective_constraints(organization=org)})
        value = _semantic_input()
        result = evaluate(state, normalize_input(value))
        self.assertEqual(result["organization_results"][0]["status"], "unevaluated")
        self.assertEqual(result["evaluation_status"], "unevaluated")

        value["organization_assessments"][org["path"]] = {
            "status": "conformant",
            "basis": _basis("RQ-1"),
            "rationale": "Human/Host assessment against the configured organization rule.",
        }
        result = evaluate(state, normalize_input(value))
        self.assertEqual(result["organization_results"][0]["status"], "conformant")
        self.assertFalse(result["semantic_assessment_boundary"]["classification_truth_verified"])

    def test_no_selected_quality_profile_is_not_applicable_and_core_state_is_unchanged(self):
        state = _state(constraints={})
        before = deepcopy(state.current_snapshot)
        result = evaluate(state, normalize_input(_semantic_input()))
        self.assertEqual(result["evaluation_status"], "not_applicable")
        self.assertEqual(result["constraint_results"], [])
        self.assertEqual(result["organization_results"], [])
        self.assertEqual(state.current_snapshot, before)

    def test_public_evaluation_is_immutable_exhibit_and_does_not_block_more_research(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg, eps_path, _eps = _workspace_inputs(root)
            workspace = root / "workspace"
            LocalApplicationFacade.initialize_workspace(workspace, cfg, eps_path)
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                rq_id = adopt_rq(facade)
                before = deepcopy(facade.status()["snapshot"])
                payload = {"rq_id": rq_id, "assessments": {}, "organization_assessments": {}}
                first = facade.evaluate_research_quality(payload)
                second = facade.evaluate_research_quality(payload)
                self.assertEqual(first["evaluation"]["evaluation_status"], "unevaluated")
                self.assertEqual(second["evaluation"]["evaluation_status"], "unevaluated")
                self.assertNotEqual(
                    first["evaluation_exhibit"]["exhibit_id"],
                    second["evaluation_exhibit"]["exhibit_id"],
                )
                stored_first = facade.show_exhibit(first["evaluation_exhibit"]["exhibit_id"])["exhibit"]
                self.assertEqual(
                    stored_first["content"]["value"],
                    first["evaluation"],
                )
                self.assertEqual(facade.status()["snapshot"], before)
                prepared = facade.submit_action({
                    "action_type": "desktop_research.investigate",
                    "payload": {
                        "question_id": rq_id,
                        "purpose": "Corrective research remains allowed after an unevaluated quality check.",
                    },
                })
                self.assertEqual(prepared["status"], "CAPABILITY_EXECUTION_PREPARED")
                self.assertEqual(facade.status()["snapshot"], before)

    def test_selected_organization_rule_reaches_real_research_context_without_becoming_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg, eps_path, eps = _organization_workspace_inputs(root)
            workspace = root / "workspace"
            LocalApplicationFacade.initialize_workspace(workspace, cfg, eps_path)
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                rq_id = adopt_rq(facade)
                before = deepcopy(facade.status()["snapshot"])
                prepared = facade.submit_action({
                    "action_type": "desktop_research.investigate",
                    "payload": {"question_id": rq_id, "purpose": "Issue #333 Organization delivery acceptance."},
                })
                run = facade._application.execution_store.load_run(prepared["run_id"])
                context = facade._application.execution_store.load_context_pack(run.context_pack_id)
                actual = {row["path"]: row for row in context["effective_constraints"]}
                self.assertIn("organization.review.roles", actual)
                expected = next(
                    row for row in eps["effective_constraints"] if row["path"] == "organization.review.roles"
                )
                self.assertEqual(actual["organization.review.roles"]["value"], expected["value"])
                self.assertEqual(actual["organization.review.roles"]["provenance"], expected["provenance"])
                evaluation = facade.evaluate_research_quality({
                    "rq_id": rq_id,
                    "assessments": {},
                    "organization_assessments": {
                        "organization.review.roles": {
                            "status": "conformant",
                            "basis": _basis(rq_id),
                            "rationale": "Synthetic Host/Human assessment of the selected Organization rule.",
                        }
                    },
                })
                self.assertEqual(evaluation["evaluation"]["evaluation_status"], "conformant")
                self.assertEqual(
                    evaluation["evaluation"]["organization_results"][0]["path"],
                    "organization.review.roles",
                )
                self.assertFalse(
                    evaluation["evaluation"]["semantic_assessment_boundary"]["classification_truth_verified"]
                )
                self.assertEqual(facade.status()["snapshot"], before)

    def test_cli_research_quality_evaluate_uses_public_workspace_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg, eps_path, _eps = _workspace_inputs(root)
            workspace = root / "workspace"
            LocalApplicationFacade.initialize_workspace(workspace, cfg, eps_path)
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                rq_id = adopt_rq(facade)
                before = deepcopy(facade.status()["snapshot"])
            input_path = root / "quality-input.json"
            input_path.write_text(
                json.dumps({"rq_id": rq_id, "assessments": {}, "organization_assessments": {}}),
                encoding="utf-8",
            )
            code, output = run_cli([
                "research-quality", "evaluate",
                "--workspace", str(workspace),
                "--json", str(input_path),
            ])
            self.assertEqual(code, 0)
            self.assertEqual(output["status"], "EVALUATED")
            self.assertEqual(output["evaluation"]["evaluation_status"], "unevaluated")
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                self.assertEqual(facade.status()["snapshot"], before)

    def test_public_workspace_context_pack_receives_real_profile_values_and_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg, eps_path, eps = _workspace_inputs(root)
            workspace = root / "workspace"
            LocalApplicationFacade.initialize_workspace(workspace, cfg, eps_path)
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                rq_id = adopt_rq(facade)
                before = deepcopy(facade.status()["snapshot"])
                prepared = facade.submit_action({
                    "action_type": "desktop_research.investigate",
                    "payload": {"question_id": rq_id, "purpose": "Issue #333 C1 acceptance."},
                })
                run = facade._application.execution_store.load_run(prepared["run_id"])
                context = facade._application.execution_store.load_context_pack(run.context_pack_id)
                expected = {x["path"]: x for x in eps["effective_constraints"]}
                actual = {x["path"]: x for x in context["effective_constraints"]}
                self.assertEqual(set(actual), set(expected))
                for path in expected:
                    self.assertEqual(actual[path]["value"], expected[path]["value"])
                    self.assertEqual(actual[path]["provenance"], expected[path]["provenance"])
                self.assertEqual(facade.status()["snapshot"], before)


if __name__ == "__main__":
    unittest.main()
