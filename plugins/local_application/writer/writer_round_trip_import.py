"""Writer response import and revision inspection for round trips (#494)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any
from uuid import uuid4

from core.runtime import canonical_digest
from plugins._infra.clock import utc_now as _now
from plugins.application_errors import LocalApplicationError

from .writer_composition_support import _digest_document
from .writer_round_trip_support import (
    MAX_INSPECT_ANCESTRY,
    MAX_RESPONSE_BYTES,
    SCHEMA_VERSION,
    _sha256_text,
    _validate_schema,
)


class WriterRoundTripImportMixin:
    def import_response(self, value: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-INPUT-001", "Writer response must be an object"
            )
        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-BOUND-001", "Writer response exceeds supported size"
            )
        _validate_schema(value)
        input_ref = value["input_ref"]
        receipt = self._load_input(str(input_ref["input_id"]))
        if input_ref["input_digest"] != receipt["input_digest"]:
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-PIN-001",
                "Writer response does not name the exact exported input digest",
            )
        composition, package = self._validate_input_context(receipt)
        self._validate_response_semantics(value, receipt, package)
        composition_id = str(composition["composition_id"])
        composer = self._composition_service()

        response_digest = canonical_digest(value)
        revision_id = "WMR-" + response_digest.split(":", 1)[1][:24]
        response_section_ids = {str(row["section_id"]) for row in value["sections"]}
        receipt_section_ids = {str(row["section_id"]) for row in receipt["sections"]}
        with composer._series_lock(composition_id):
            head, restored = self._reconcile_head(composition_id)
            existing_path = self._revision_path(composition_id, revision_id)
            if existing_path.is_file():
                stored = self._read_json(existing_path, message="manuscript revision is unreadable")
                revision_id = str(stored.get("revision_id", ""))
                existing = self._load_revision(composition_id, revision_id)
                if (
                    existing.get("response_digest") != response_digest
                    or existing.get("source", {}).get("input_digest") != receipt["input_digest"]
                ):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-IMMUTABLE-001",
                        "existing manuscript revision identity conflicts with this response",
                    )
                if head is None or int(existing["revision_number"]) > int(head["revision_number"]):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                        "stored response is ahead of the retained continuity record; restore a consistent exact backup",
                    )
                if int(head["revision_number"]) == int(existing["revision_number"]) and (
                    head["revision_id"] != existing["revision_id"]
                    or head["revision_digest"] != existing["revision_digest"]
                ):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                        "manuscript head conflicts with an existing revision at the same revision number",
                    )
                return {
                    "status": "RESTORED" if "manuscript_revision" in restored else "VERIFIED_REUSE",
                    **(
                        {"restored_components": restored, "recovered_at": _now()}
                        if restored
                        else {}
                    ),
                    "revision_id": revision_id,
                    "revision_digest": existing["revision_digest"],
                    "revision_number": existing["revision_number"],
                    "research_state_mutation_performed": False,
                }

            base_ref = value.get("base_revision_ref")
            base_revision = None
            if head is None:
                if base_ref is not None:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-STALE-001",
                        "initial manuscript response must not name a base revision",
                    )
                if response_section_ids != receipt_section_ids:
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-INPUT-001",
                        "initial manuscript response must provide every section in the exported input",
                    )
                revision_number = 1
            else:
                if (
                    not isinstance(base_ref, Mapping)
                    or base_ref.get("revision_id") != head["revision_id"]
                    or base_ref.get("revision_digest") != head["revision_digest"]
                ):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-STALE-001",
                        "Writer response must be based on the exact current manuscript revision",
                    )
                base_revision = self._load_revision(composition_id, str(head["revision_id"]))
                revision_number = int(base_revision["revision_number"]) + 1
                if (
                    base_revision["source"]["input_id"] != receipt["input_id"]
                    and response_section_ids != receipt_section_ids
                ):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-INPUT-001",
                        "a changed Writer input requires a complete fresh section response; unchanged sections are reused only within the same exact input",
                    )

            revision_id += "-" + uuid4().hex
            drafts = {str(row["section_id"]): row for row in value["sections"]}
            sections: list[dict[str, Any]] = []
            base_sections = (
                {str(row["section_id"]): row for row in base_revision.get("sections", [])}
                if base_revision is not None
                else {}
            )
            for input_section in receipt["sections"]:
                section_id = str(input_section["section_id"])
                draft = drafts.get(section_id)
                if draft is None:
                    base = base_sections.get(section_id)
                    if base is None:
                        raise LocalApplicationError(
                            "APPLICATION-WRITER-ROUND-TRIP-INPUT-001",
                            f"Writer response omits section without a reusable base: {section_id}",
                        )
                    sections.append(deepcopy(dict(base)))
                    continue
                row = {
                    "section_id": section_id,
                    "content": str(draft["content"]),
                    "content_digest": _sha256_text(str(draft["content"])),
                    "citations": deepcopy(list(draft.get("citations", []))),
                    "exhibit_refs": deepcopy(list(draft.get("exhibit_refs", []))),
                    **(
                        {"profile_review": deepcopy(list(draft["profile_review"]))}
                        if "profile_review" in draft
                        else {}
                    ),
                    "origin_revision_id": revision_id,
                }
                sections.append(row)

            self._validate_document_review(value, receipt, sections)
            feedback = deepcopy(list(value.get("feedback", [])))
            candidate_follow_ups = [
                {
                    "source_issue_id": str(issue["issue_id"]),
                    "instruction": str(issue["proposed_next_action"]),
                    "status": "candidate",
                    "research_state_mutation_performed": False,
                }
                for issue in feedback
            ]
            document: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "object_type": "writer_manuscript_revision",
                "revision_id": revision_id,
                "revision_number": revision_number,
                "source": {
                    "input_id": receipt["input_id"],
                    "input_digest": receipt["input_digest"],
                    **receipt["source"],
                },
                "parent_revision_ref": deepcopy(dict(base_ref))
                if isinstance(base_ref, Mapping)
                else None,
                "response_id": value["response_id"],
                "response_digest": response_digest,
                "writer": deepcopy(dict(value["writer"])),
                "sections": sections,
                **(
                    {"document_review": deepcopy(value["document_review"])}
                    if "document_review" in value
                    else {}
                ),
                "writing_feedback": {
                    "issues": feedback,
                    "is_research_evidence": False,
                    "research_state_mutation_performed": False,
                },
                "candidate_follow_ups": candidate_follow_ups,
                "authority_boundary": {
                    "research_state_mutation_performed": False,
                    "evidence_verification_performed": False,
                    "finding_adoption_performed": False,
                    "recommendation_adoption_performed": False,
                },
                "created_at": _now(),
                "revision_digest": "",
            }
            document["revision_digest"] = _digest_document(document, "revision_digest")
            _validate_schema(document)
            # Retain exact immutable facts before either emitted copy. This latest
            # per-series record is also the O(1) pending-write witness on next import.
            self._write_pointer(self._checkpoint_path(composition_id), document)
            self._write_immutable(self._revision_path(composition_id, revision_id), document)
            self._write_head(
                composition_id,
                {
                    "revision_id": revision_id,
                    "revision_digest": document["revision_digest"],
                    "revision_number": revision_number,
                },
            )
        return {
            "status": "IMPORTED",
            "revision_id": revision_id,
            "revision_digest": document["revision_digest"],
            "revision_number": revision_number,
            "reused_section_ids": [
                row["section_id"] for row in sections if row["origin_revision_id"] != revision_id
            ],
            "research_state_mutation_performed": False,
        }

    def inspect(self, composition_id: str, revision_id: str | None = None) -> Mapping[str, Any]:
        self._composition_service()
        if revision_id is None:
            checkpoint = self._checkpoint_path(composition_id)
            if checkpoint.exists():
                latest = self._read_json(
                    checkpoint,
                    message="Writer continuity record is unreadable; restore an exact backup",
                )
                self._validate_revision(latest, composition_id, str(latest.get("revision_id", "")))
                head_path = self._head_path(composition_id)
                head_copy = (
                    self._read_json(
                        head_path,
                        message="manuscript head is unreadable; restore the derived pointer",
                    )
                    if head_path.exists()
                    else None
                )
                if head_copy != self._revision_ref(latest):
                    raise LocalApplicationError(
                        "APPLICATION-WRITER-ROUND-TRIP-RECOVERY-REQUIRED-001",
                        "manuscript import needs recovery; retry the exact stored response before requesting the latest revision",
                    )
            head = self._head(composition_id)
            if head is None:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-404", "manuscript revision head does not exist"
                )
            revision_id = str(head["revision_id"])
        revision = self._load_revision(composition_id, revision_id)
        receipt = self._load_input(str(revision["source"]["input_id"]))
        composition, package = self._validate_input_context(receipt)
        if (
            revision["source"]["composition_digest"] != composition["composition_digest"]
            or revision["source"]["research_package_digest"] != package["package_digest"]
        ):
            raise LocalApplicationError(
                "APPLICATION-WRITER-ROUND-TRIP-PIN-001",
                "manuscript revision source pins do not match its input",
            )
        if "document_review" in revision:
            self._validate_document_review(
                {
                    "document_review": revision["document_review"],
                    "feedback": revision["writing_feedback"]["issues"],
                },
                receipt,
                list(revision["sections"]),
            )

        lineage: list[dict[str, Any]] = []
        current = revision
        truncated = False
        for _ in range(MAX_INSPECT_ANCESTRY):
            lineage.append(
                {
                    "revision_id": current["revision_id"],
                    "revision_number": current["revision_number"],
                    "revision_digest": current["revision_digest"],
                    "input_id": current["source"]["input_id"],
                }
            )
            parent = current.get("parent_revision_ref")
            if not isinstance(parent, Mapping):
                break
            current = self._load_revision(composition_id, str(parent["revision_id"]))
            if current["revision_digest"] != parent["revision_digest"]:
                raise LocalApplicationError(
                    "APPLICATION-WRITER-ROUND-TRIP-INTEGRITY-001",
                    "manuscript parent revision digest does not resolve",
                )
        else:
            truncated = isinstance(current.get("parent_revision_ref"), Mapping)

        return {
            "status": "OK",
            "document_review_target": self._document_target(receipt, list(revision["sections"])),
            "document_review_status": self._document_review_status(revision, composition, receipt),
            "source_package": {
                "package_id": package["package_id"],
                "package_digest": package["package_digest"],
                "research_snapshot": deepcopy(package["source_research_snapshot"]),
                "effective_profile_set": deepcopy(package["effective_profile_set"]),
            },
            "composition": {
                "composition_id": composition["composition_id"],
                "version": composition["version"],
                "composition_digest": composition["composition_digest"],
                "sections": deepcopy(composition["sections"]),
            },
            "writer_input": deepcopy(receipt),
            "effective_constraints": deepcopy(
                package.get("resolved_profiles", {}).get("effective_constraints", [])
            ),
            "revision": deepcopy(revision),
            "revision_lineage": lineage,
            "lineage_truncated": truncated,
            "research_state_mutation_performed": False,
        }
