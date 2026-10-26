"""Writer response and document review validation for round trips (#494)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from core.runtime import canonical_digest
from plugins.application_errors import LocalApplicationError

from .writer_composition_support import _object_index, _package_ref_sets
from .writer_round_trip_support import (
    MAX_RESPONSE_BYTES,
    _validate_schema,
)


class WriterRoundTripReviewMixin:
    @staticmethod
    def _known_package_refs(package: Mapping[str, Any]) -> set[str]:
        refs = set(_object_index(package))
        ref_sets = _package_ref_sets(package)
        for values in ref_sets.values():
            refs.update(values)
        refs.add(str(package["package_id"]))
        return refs

    @staticmethod
    def _writer_review_plan(scope: Mapping[str, Any]) -> dict[str, set[str]]:
        section_input = scope.get("section_input")
        if not isinstance(section_input, Mapping):
            return {}
        delivery = section_input.get("writer_profile")
        if delivery is None:
            return {}
        if not isinstance(delivery, Mapping) or not isinstance(delivery.get("review_plan"), list):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                "Writer Profile review plan is malformed",
            )
        result: dict[str, set[str]] = {}
        for row in delivery["review_plan"]:
            if (
                not isinstance(row, Mapping)
                or not isinstance(row.get("review_id"), str)
                or not isinstance(row.get("rule_ids"), list)
            ):
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                    "Writer Profile review plan is malformed",
                )
            review_id = str(row["review_id"])
            rule_ids = {
                str(rule_id) for rule_id in row["rule_ids"] if isinstance(rule_id, str) and rule_id
            }
            if not review_id or not rule_ids or review_id in result:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                    "Writer Profile review plan contains an invalid group",
                )
            result[review_id] = rule_ids
        return result

    @staticmethod
    def _validate_profile_review(draft: Mapping[str, Any], scope: Mapping[str, Any]) -> set[str]:
        plan = WriterRoundTripReviewMixin._writer_review_plan(scope)
        metadata = WriterRoundTripReviewMixin._writer_rule_metadata(scope)
        reviews = draft.get("profile_review", [])
        if not plan:
            if reviews:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                    "Writer response reports Profile review without delivered Writer rules",
                )
            return set()
        if not isinstance(reviews, list):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                "Writer response must report the delivered Profile review plan",
            )
        by_id: dict[str, Mapping[str, Any]] = {}
        for row in reviews:
            if not isinstance(row, Mapping) or not isinstance(row.get("review_id"), str):
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                    "Writer Profile review entry is malformed",
                )
            review_id = str(row["review_id"])
            if review_id in by_id:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                    f"duplicate Writer Profile review group: {review_id}",
                )
            by_id[review_id] = row
        if set(by_id) != set(plan):
            missing = sorted(set(plan) - set(by_id))
            extra = sorted(set(by_id) - set(plan))
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                f"Writer Profile review groups do not match delivered plan; missing={missing}, extra={extra}",
            )
        violations: set[str] = set()
        for review_id, expected_rule_ids in plan.items():
            row = by_id[review_id]
            actual_rule_ids = {str(x) for x in row.get("rule_ids", []) if isinstance(x, str)}
            violated_rule_ids = {
                str(x) for x in row.get("violated_rule_ids", []) if isinstance(x, str)
            }
            if actual_rule_ids != expected_rule_ids:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                    f"Writer Profile review does not cover exact rules for {review_id}",
                )
            if not violated_rule_ids <= expected_rule_ids:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                    f"Writer Profile review names unavailable rules for {review_id}",
                )
            outcome = str(row.get("outcome"))
            if metadata:
                WriterRoundTripReviewMixin._validate_rule_results(row, expected_rule_ids, metadata)
            if outcome in {"violation", "mixed"}:
                if not violated_rule_ids:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                        f"Writer Profile review {review_id} reports a violation without rule IDs",
                    )
                violations.update(violated_rule_ids)
            elif violated_rule_ids:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                    f"Writer Profile review {review_id} lists violated rules for non-violation outcome",
                )
        return violations

    @staticmethod
    def _writer_rule_metadata(scope: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
        delivery = scope.get("section_input", {}).get("writer_profile", {})
        result = {}
        for resource in delivery.get("resources", []):
            if resource.get("role") != "WRITER_RULES":
                continue
            body = json.loads(resource["content"])
            if body.get("review_contract_version") != "1.0.0":
                continue
            for item in body["items"]:
                result[item["id"]] = item["review"]
        return result

    @staticmethod
    def _validate_rule_results(
        row: Mapping[str, Any],
        expected_rule_ids: set[str],
        metadata: Mapping[str, Mapping[str, Any]],
        *,
        scope: str = "section",
    ) -> None:
        def refuse(message: str) -> None:
            raise LocalApplicationError("APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001", message)

        results = row.get("rule_results", [])
        by_id = {item["rule_id"]: item for item in results}
        if len(by_id) != len(results) or set(by_id) != expected_rule_ids:
            refuse("Writer rule results must cover exact delivered IDs once")
        violations = set()
        outcomes = set()
        for rule_id, item in by_id.items():
            review = metadata.get(rule_id)
            outcome = item["outcome"]
            outcomes.add(outcome)
            if not item["rationale"].strip():
                refuse("Writer rule result needs a content-based rationale")
            if outcome == "violation":
                violations.add(rule_id)
            if review is None:
                continue
            if outcome == "not_applicable":
                if (
                    item["applicability"] != "not_applicable"
                    or item["method"] != review["check_kind"]
                ):
                    refuse(
                        "Writer N/A needs evaluated non-applicability and the rule's review method"
                    )
            elif outcome != "unevaluated":
                if item["applicability"] != "applicable" or item["method"] != review["check_kind"]:
                    refuse(
                        "Writer result cannot replace semantic/editorial review with structural presence"
                    )
            elif item["method"] != "unevaluated":
                refuse("Unevaluated Writer result must identify its unperformed review")
            if (
                scope == "section"
                and review["scope"] == "document"
                and outcome not in {"unevaluated", "not_applicable"}
            ):
                refuse("Section review cannot establish a document-scoped result")
        if violations != set(row.get("violated_rule_ids", [])):
            refuse("Group violations must match rule results")
        group = row["outcome"]
        if group == "not_applicable" and outcomes != {"not_applicable"}:
            refuse("Group N/A requires every rule to be non-applicable")
        if group == "conformant" and not outcomes <= {"conformant", "not_applicable"}:
            refuse("Unevaluated or violated rules cannot become group conformance")
        if group == "conformant" and outcomes == {"not_applicable"}:
            refuse("All-N/A review cannot become conformance")
        if group in {"violation", "mixed"} and not violations:
            refuse("Group violation requires a violated rule result")
        if group == "mixed" and not outcomes.intersection({"conformant", "not_applicable"}):
            refuse("Mixed group requires both violated and conformant or non-applicable rules")
        if group == "unevaluated" and violations:
            refuse("Group unevaluated cannot conceal declared violations")

    def _validate_response_semantics(
        self,
        response: Mapping[str, Any],
        receipt: Mapping[str, Any],
        package: Mapping[str, Any],
        document_receipt: Mapping[str, Any] | None = None,
    ) -> None:
        section_scope = {str(row["section_id"]): row for row in receipt["sections"]}
        feedback_scope = {
            str(row["section_id"]) for row in (document_receipt or receipt)["sections"]
        }
        response_ids: set[str] = set()
        violations_by_section: dict[str, set[str]] = {}
        for draft in response["sections"]:
            section_id = str(draft["section_id"])
            if section_id in response_ids:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-INPUT-001",
                    f"duplicate Writer response section: {section_id}",
                )
            response_ids.add(section_id)
            scope = section_scope.get(section_id)
            if scope is None:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PIN-001",
                    f"Writer response section was not exported by the pinned input: {section_id}",
                )
            allowed_exhibits = set(map(str, scope.get("exhibit_refs", [])))
            if not set(map(str, draft.get("exhibit_refs", []))) <= allowed_exhibits:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001",
                    f"Writer response introduces an unavailable Exhibit in {section_id}",
                )
            citation_scope = {
                str(row["source_ref"]): set(map(str, row.get("locators", [])))
                for row in scope.get("citation_scope", [])
                if isinstance(row, Mapping)
            }
            for citation in draft.get("citations", []):
                source = str(citation["source_ref"])
                locator = citation.get("locator_ref")
                if source not in citation_scope:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001",
                        f"Writer response citation Source is unavailable: {source}",
                    )
                if locator is not None and str(locator) not in citation_scope[source]:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001",
                        f"Writer response citation locator is unavailable: {locator}",
                    )
            if self._writer_rule_metadata(scope):
                citations = draft.get("citations", [])
                for required in scope["section_input"]["section_contract"].get(
                    "citation_requirements", []
                ):
                    if not any(
                        item["source_ref"] == required["source_ref"]
                        and (
                            required.get("locator_ref") is None
                            or item.get("locator_ref") == required["locator_ref"]
                        )
                        for item in citations
                    ):
                        raise LocalApplicationError(
                            "APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001",
                            "Writer response omits an explicitly required citation: "
                            + str(required["source_ref"]),
                        )
            violations_by_section[section_id] = self._validate_profile_review(draft, scope)
        known_refs = self._known_package_refs(package)
        document_violations = {
            rule_id
            for row in response.get("document_review", {}).get("profile_review", [])
            for rule_id in row.get("violated_rule_ids", [])
        }
        feedback_rule_ids_by_section: dict[str, set[str]] = {}
        for issue in response.get("feedback", []):
            target_type = issue["target_type"]
            target_id = str(issue["target_id"])
            if target_type == "section" and target_id not in feedback_scope:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001",
                    f"Writer feedback targets an unavailable section: {target_id}",
                )
            if target_type == "package" and target_id != package["package_id"]:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001",
                    "Writer feedback targets the wrong Research Package",
                )
            if target_type in {"research_object", "argument"} and target_id not in known_refs:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001",
                    f"Writer feedback target is not in the pinned Research Package: {target_id}",
                )
            unknown_support = sorted(
                set(map(str, issue.get("supporting_package_refs", []))) - known_refs
            )
            if unknown_support:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-REFERENCE-001",
                    "Writer feedback references material outside the pinned Research Package: "
                    + ", ".join(unknown_support),
                )
            profile_rule_ids = {
                str(x) for x in issue.get("profile_rule_ids", []) if isinstance(x, str)
            }
            if profile_rule_ids:
                section_rule_ids = profile_rule_ids - document_violations
                if section_rule_ids and target_type != "section":
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                        "Profile rule feedback must target a section",
                    )
                allowed = violations_by_section.get(target_id, set())
                if not section_rule_ids <= allowed:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                        "Writing Feedback names Profile rules not reported as violated for the section",
                    )
                feedback_rule_ids_by_section.setdefault(target_id, set()).update(section_rule_ids)
        for section_id, violated_rule_ids in violations_by_section.items():
            missing = sorted(
                violated_rule_ids - feedback_rule_ids_by_section.get(section_id, set())
            )
            if missing:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                    "Writer Profile violations require Writing Feedback for exact rule IDs: "
                    + ", ".join(missing),
                )

    @staticmethod
    def _document_target(
        receipt: Mapping[str, Any], sections: list[Mapping[str, Any]]
    ) -> dict[str, Any]:
        # input_digest already includes the exact package, composition (roles/order)
        # and Profile pins. Review metadata and revision identity are not content.
        projection = {
            "projection_version": "1.0.0",
            "input_digest": receipt["input_digest"],
            "sections": [
                {
                    key: deepcopy(row[key])
                    for key in ("section_id", "content", "citations", "exhibit_refs")
                }
                for row in sections
            ],
        }
        return {"target_digest": canonical_digest(projection), "material": projection}

    @classmethod
    def _document_plan(
        cls, receipt: Mapping[str, Any]
    ) -> tuple[dict[str, set[str]], dict[str, Mapping[str, Any]]]:
        plan: dict[str, set[str]] = {}
        metadata: dict[str, Mapping[str, Any]] = {}
        for section in receipt["sections"]:
            rules = cls._writer_rule_metadata(section)
            for rule_id, review in rules.items():
                if rule_id in metadata and metadata[rule_id] != review:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-PROFILE-REVIEW-001",
                        "conflicting document rule metadata",
                    )
                metadata[rule_id] = review
            for review_id, rule_ids in cls._writer_review_plan(section).items():
                selected = {
                    rule_id
                    for rule_id in rule_ids
                    if rules.get(rule_id, {}).get("scope") == "document"
                }
                if selected:
                    plan.setdefault(review_id, set()).update(selected)
        return plan, metadata

    @classmethod
    def _validate_document_review(
        cls,
        response: Mapping[str, Any],
        receipt: Mapping[str, Any],
        sections: list[Mapping[str, Any]],
    ) -> None:
        review = response.get("document_review")
        if review is None:
            return

        def refuse(message: str) -> None:
            raise LocalApplicationError("APPLICATION-WRITER-DOCUMENT-REVIEW-001", message)

        if not review["reviewer"]["reviewer_id"].strip():
            refuse("Document review needs an identified reviewer")
        target = cls._document_target(receipt, sections)
        if review["target_digest"] != target["target_digest"]:
            refuse(
                "Document review does not match the assembled manuscript target; remove or review it again"
            )
        target_ids = [row["section_id"] for row in sections]
        covered = review["section_ids"]
        if not set(covered) <= set(target_ids) or covered != [
            sid for sid in target_ids if sid in covered
        ]:
            refuse("Document review must name existing sections in target order")
        if review["coverage"] == "full" and covered != target_ids:
            refuse("Full review must cover every section in the exported manuscript scope")
        plan, metadata = cls._document_plan(receipt)
        rows = review["profile_review"]
        by_id = {row["review_id"]: row for row in rows}
        if len(by_id) != len(rows) or set(by_id) != set(plan):
            refuse("Document review groups must match the delivered document-scoped plan")
        violations: set[str] = set()
        for review_id, expected in plan.items():
            row = by_id[review_id]
            if not row["rationale"].strip():
                refuse("Document review group needs a content-based rationale")
            if set(row["rule_ids"]) != expected:
                refuse("Document review must cover the exact document-scoped rule IDs")
            cls._validate_rule_results(row, expected, metadata, scope="document")
            if review["coverage"] == "partial" and any(
                item["outcome"] in {"conformant", "not_applicable"} for item in row["rule_results"]
            ):
                refuse("Partial review cannot establish document conformance or document N/A")
            violations.update(row["violated_rule_ids"])
        feedback_ids = {
            rule_id
            for issue in response.get("feedback", [])
            for rule_id in issue.get("profile_rule_ids", [])
        }
        if not violations <= feedback_ids:
            refuse("Document violations require Writing Feedback for the exact rule IDs")
        for issue in response.get("feedback", []):
            if (
                set(issue.get("profile_rule_ids", [])) & violations
                and issue["target_type"] == "section"
                and issue["target_id"] not in covered
            ):
                refuse(
                    "Document rule feedback must target a reviewed section or a pinned research/package target"
                )

    @classmethod
    def _document_review_status(
        cls, revision: Mapping[str, Any], composition: Mapping[str, Any], receipt: Mapping[str, Any]
    ) -> dict[str, Any]:
        review = revision.get("document_review", {})
        results = [
            item for group in review.get("profile_review", []) for item in group["rule_results"]
        ]
        _, metadata = cls._document_plan(receipt)
        evaluated = bool(results) and all(item["outcome"] != "unevaluated" for item in results)
        return {
            "status": "partial"
            if review.get("coverage") == "partial"
            else "reviewed"
            if evaluated
            else "unevaluated",
            "coverage": review.get("coverage", "unevaluated"),
            "scope_section_ids": [row["section_id"] for row in revision["sections"]],
            "reviewed_section_ids": list(review.get("section_ids", [])),
            "covers_composition": [row["section_id"] for row in revision["sections"]]
            == [row["section_id"] for row in composition["sections"]],
            "rule_outcomes": {item["rule_id"]: item["outcome"] for item in results},
            "results_by_check_kind": {
                kind: [
                    deepcopy(item)
                    for item in results
                    if metadata[item["rule_id"]]["check_kind"] == kind
                ]
                for kind in ("structural", "semantic", "editorial")
            },
            "semantic_quality_guaranteed": False,
            "reader_effect_validated": False,
        }

    def prepare_document_review(self, value: Mapping[str, Any]) -> Mapping[str, Any]:
        """Materialize a proposed response plus its exact base without saving a draft."""
        if (
            not isinstance(value, Mapping)
            or len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_RESPONSE_BYTES
        ):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-BOUND-001",
                "Writer response exceeds supported size or is not an object",
            )
        _validate_schema(value)
        receipt = self._load_input(str(value["input_ref"]["input_id"]))
        if value["input_ref"]["input_digest"] != receipt["input_digest"]:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-PIN-001",
                "Writer response does not name the exact exported input digest",
            )
        composition, package = self._validate_input_context(receipt)
        composition_id = str(composition["composition_id"])
        with self._composition_service()._series_lock(composition_id):
            head = self._head(composition_id)
            if head is not None:
                # Read-only continuity check; an interrupted import must be recovered
                # through the existing exact-response retry before preparing a review.
                inspected = self.inspect(composition_id)
                base = inspected["revision"]
                exact_base = {key: base[key] for key in ("revision_id", "revision_digest")}
                if value["base_revision_ref"] != exact_base:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-STALE-001",
                        "review preparation requires the exact current base",
                    )
            else:
                if self._checkpoint_path(composition_id).exists():
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-RECOVERY-REQUIRED-001",
                        "restore the manuscript head by retrying the exact response",
                    )
                base = None
                if value["base_revision_ref"] is not None:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-STALE-001",
                        "initial review target must not name a base",
                    )
            drafts = {row["section_id"]: row for row in value["sections"]}
            if len(drafts) != len(value["sections"]):
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-INPUT-001", "duplicate Writer response section"
                )
            _, effective_receipt = self._effective_input(receipt, base, drafts, composition)
            self._validate_response_semantics(value, receipt, package, effective_receipt)
            required_ids = [row["section_id"] for row in effective_receipt["sections"]]
            previous = {row["section_id"]: row for row in base["sections"]} if base else {}
            sections = [
                deepcopy(drafts[sid] if sid in drafts else previous[sid]) for sid in required_ids
            ]
            target = self._document_target(effective_receipt, sections)
            plan, metadata = self._document_plan(effective_receipt)
            return {
                "status": "PREPARED",
                **target,
                "input_ref": deepcopy(value["input_ref"]),
                "base_revision_ref": deepcopy(value["base_revision_ref"]),
                "writer_input": deepcopy(effective_receipt),
                "response_input": deepcopy(receipt),
                "review_plan": [
                    {"review_id": key, "rule_ids": sorted(ids)} for key, ids in plan.items()
                ],
                "rule_metadata": {
                    key: metadata[key] for ids in plan.values() for key in sorted(ids)
                },
                "scope_section_ids": required_ids,
                "composition_section_ids": [row["section_id"] for row in composition["sections"]],
                "research_state_mutation_performed": False,
            }
