"""Characterization tests for ``core.runtime.schema_validation`` (#507).

They pin how ``CanonicalResearchObjectSchemaValidator`` collects objects from
requests and reductions and how it reports schema violations.
"""

from __future__ import annotations

import unittest

from jsonschema.exceptions import SchemaError

from core.runtime.schema_validation import CanonicalResearchObjectSchemaValidator
from core.runtime.transition_models import (
    ReductionResult,
    TransitionAction,
    TransitionKind,
    ValidationStage,
)
from tests.runtime.runtime_fixtures import (
    SCHEMA,
    make_request,
    project,
    rq,
    seed_state,
    snapshot,
)

# A small schema keeps error paths and messages deterministic.
TOY_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["id", "kind"],
    "properties": {
        "id": {"type": "string"},
        "kind": {"type": "string"},
        "count": {"type": "integer"},
        "nested": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
        },
        "at": {"type": "string", "format": "date-time"},
    },
}


def reduction(*, objects=(), new_snapshot=None, audit_events=()) -> ReductionResult:
    return ReductionResult(
        object_revisions=tuple(objects),
        decision_records=(),
        new_snapshot=new_snapshot,
        lineage_updates=(),
        new_lineages=(),
        active_lineage_update=None,
        adoption_refs=(),
        used_decision_refs=(),
        audit_events=tuple(audit_events),
        applied_actions=(),
    )


class ConstructorTests(unittest.TestCase):
    def test_invalid_schema_document_is_rejected_at_construction(self):
        with self.assertRaises(SchemaError):
            CanonicalResearchObjectSchemaValidator({"type": "not-a-json-type"})

    def test_canonical_schema_is_accepted(self):
        CanonicalResearchObjectSchemaValidator(SCHEMA)


class ValidateRequestTests(unittest.TestCase):
    def setUp(self):
        self.validator = CanonicalResearchObjectSchemaValidator(TOY_SCHEMA)
        self.state = seed_state()

    def request(self, *actions):
        return make_request(self.state, actions)

    def test_valid_object_payload_produces_no_issues(self):
        action = TransitionAction(
            TransitionKind.CREATE_OBJECT, {"object": {"id": "A", "kind": "k"}}
        )
        self.assertEqual(self.validator.validate_request(self.request(action)), ())

    def test_action_without_object_payload_is_skipped(self):
        action = TransitionAction(TransitionKind.SWITCH_ACTIVE_LINEAGE, {"target": "LIN-2"})
        self.assertEqual(self.validator.validate_request(self.request(action)), ())

    def test_non_mapping_object_payload_is_skipped(self):
        action = TransitionAction(TransitionKind.CREATE_OBJECT, {"object": ["not", "a", "map"]})
        self.assertEqual(self.validator.validate_request(self.request(action)), ())

    def test_invalid_object_payload_reports_schema_issue(self):
        action = TransitionAction(TransitionKind.CREATE_OBJECT, {"object": {"id": "A"}})
        issues = self.validator.validate_request(self.request(action))
        self.assertEqual(len(issues), 1)
        issue = issues[0]
        self.assertEqual(issue.error_code, "RT-SCHEMA-CORE-001")
        self.assertEqual(issue.stage, ValidationStage.SCHEMA)
        self.assertEqual(
            issue.message,
            "Canonical Core object schema violation at $: 'kind' is a required property",
        )
        self.assertEqual(issue.affected_refs, ("A",))
        self.assertFalse(issue.retryable)

    def test_treatment_derived_objects_are_validated(self):
        action = TransitionAction(
            TransitionKind.APPLY_LINEAGE_PLAN,
            {
                "treatments": [
                    {"treatment": "RECONFIRM", "derived_object": {"id": "D1", "kind": 3}},
                    {"treatment": "PRESERVE"},
                    {"treatment": "RECONFIRM", "derived_object": "not-a-mapping"},
                    "not-a-mapping-treatment",
                ]
            },
        )
        issues = self.validator.validate_request(self.request(action))
        self.assertEqual([issue.affected_refs for issue in issues], [("D1",)])
        self.assertEqual(
            issues[0].message,
            "Canonical Core object schema violation at kind: 3 is not of type 'string'",
        )

    def test_treatments_as_tuple_are_validated(self):
        action = TransitionAction(
            TransitionKind.APPLY_LINEAGE_PLAN,
            {"treatments": ({"derived_object": {"kind": "k"}},)},
        )
        issues = self.validator.validate_request(self.request(action))
        self.assertEqual(len(issues), 1)
        # A derived object without an id reports an empty affected ref.
        self.assertEqual(issues[0].affected_refs, ("",))

    def test_non_sequence_treatments_are_ignored(self):
        for treatments in ("RECONFIRM", {"derived_object": {"id": "X"}}, None):
            with self.subTest(treatments=treatments):
                action = TransitionAction(
                    TransitionKind.APPLY_LINEAGE_PLAN, {"treatments": treatments}
                )
                self.assertEqual(self.validator.validate_request(self.request(action)), ())

    def test_object_and_treatments_of_one_action_are_both_validated_in_order(self):
        action = TransitionAction(
            TransitionKind.APPLY_LINEAGE_PLAN,
            {
                "object": {"id": "OBJ"},
                "treatments": [{"derived_object": {"id": "DER"}}],
            },
        )
        issues = self.validator.validate_request(self.request(action))
        self.assertEqual([issue.affected_refs for issue in issues], [("OBJ",), ("DER",)])


class ValidateReductionTests(unittest.TestCase):
    def setUp(self):
        self.validator = CanonicalResearchObjectSchemaValidator(TOY_SCHEMA)

    def test_empty_reduction_has_no_issues(self):
        self.assertEqual(self.validator.validate_reduction(reduction()), ())

    def test_revisions_snapshot_and_audit_events_are_validated_in_that_order(self):
        result = self.validator.validate_reduction(
            reduction(
                objects=[{"id": "REV"}],
                new_snapshot={"id": "SNP"},
                audit_events=[{"id": "AUD"}],
            )
        )
        self.assertEqual([issue.affected_refs for issue in result], [("REV",), ("SNP",), ("AUD",)])

    def test_no_snapshot_means_only_revisions_and_audit_events(self):
        result = self.validator.validate_reduction(
            reduction(objects=[{"id": "REV"}], audit_events=[{"id": "AUD", "kind": "k"}])
        )
        self.assertEqual([issue.affected_refs for issue in result], [("REV",)])

    def test_multiple_errors_are_sorted_by_path_then_validator(self):
        obj = {
            "id": "X",
            "kind": "k",
            "nested": {"value": 1},
            "count": "many",
        }
        result = self.validator.validate_reduction(reduction(objects=[obj]))
        self.assertEqual(
            [issue.message for issue in result],
            [
                "Canonical Core object schema violation at count: 'many' is not of type 'integer'",
                "Canonical Core object schema violation at nested.value: 1 is not of type 'string'",
            ],
        )

    def test_root_errors_sort_before_nested_errors(self):
        obj = {"count": 1.5}
        result = self.validator.validate_reduction(reduction(objects=[obj]))
        self.assertEqual(
            [issue.message for issue in result],
            [
                "Canonical Core object schema violation at $: 'id' is a required property",
                "Canonical Core object schema violation at $: 'kind' is a required property",
                "Canonical Core object schema violation at count: 1.5 is not of type 'integer'",
            ],
        )

    def test_format_checker_is_enabled(self):
        result = self.validator.validate_reduction(
            reduction(objects=[{"id": "X", "kind": "k", "at": "not-a-date"}])
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0].message,
            "Canonical Core object schema violation at at: 'not-a-date' is not a 'date-time'",
        )
        ok = self.validator.validate_reduction(
            reduction(objects=[{"id": "X", "kind": "k", "at": "2026-08-26T00:00:00Z"}])
        )
        self.assertEqual(ok, ())


class CanonicalSchemaTests(unittest.TestCase):
    def setUp(self):
        self.validator = CanonicalResearchObjectSchemaValidator(SCHEMA)

    def test_fixture_objects_are_valid_under_canonical_schema(self):
        objects = [project(), rq()]
        result = self.validator.validate_reduction(
            reduction(objects=objects, new_snapshot=snapshot("SNP-9", objects))
        )
        self.assertEqual(result, ())

    def test_unknown_kind_is_rejected_at_root(self):
        result = self.validator.validate_reduction(
            reduction(objects=[{"id": "Z-1", "kind": "unknown"}])
        )
        self.assertTrue(result)
        self.assertTrue(all(issue.error_code == "RT-SCHEMA-CORE-001" for issue in result), result)
        self.assertTrue(all(issue.affected_refs == ("Z-1",) for issue in result))
        self.assertTrue(
            result[0].message.startswith("Canonical Core object schema violation at $: ")
        )


if __name__ == "__main__":
    unittest.main()
