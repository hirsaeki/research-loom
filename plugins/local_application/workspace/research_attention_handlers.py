"""Research attention provider, handlers and payload checks (#494)."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from core.conversation import (
    ConversationRuntimeError,
    HarnessServiceResult,
)
from plugins.local_attention_store import (
    LocalAttentionStore,
    LocalAttentionStoreError,
    attention_map_digest,
)


class EffectiveResearchAttentionProvider:
    """Resolve complete effective guidance without changing Project Config or Research State."""

    def __init__(
        self, store: LocalAttentionStore, *, profile_history_root: Path | None = None
    ) -> None:
        self._store = store
        self._profile_history_root = (
            Path(profile_history_root) if profile_history_root is not None else None
        )

    @staticmethod
    def _is_canonical_config_digest(value: object) -> bool:
        return isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None

    @classmethod
    def _event_successor(
        cls, event: Mapping[str, Any], *, project_id: str, source_config_digest: str
    ) -> str | None:
        if event.get("event_type") != "project_profile_generation_advanced":
            return None
        if str(event.get("project_id") or "") != project_id:
            return None
        old_binding = event.get("old_binding")
        new_binding = event.get("new_binding")
        if not isinstance(old_binding, Mapping) or not isinstance(new_binding, Mapping):
            raise ValueError("Profile advancement event binding is malformed")
        old_digest = old_binding.get("project_config_digest")
        new_digest = new_binding.get("project_config_digest")
        if not cls._is_canonical_config_digest(old_digest) or not cls._is_canonical_config_digest(
            new_digest
        ):
            raise ValueError("Profile advancement event digest is malformed")
        if old_digest != source_config_digest:
            return None
        return new_digest

    def _profile_generation_connects(
        self,
        *,
        project_id: str,
        source_config_digest: str,
        target_config_digest: str,
    ) -> bool:
        if source_config_digest == target_config_digest:
            return True
        if self._profile_history_root is None:
            return False
        events_root = self._profile_history_root / "events"
        if not events_root.is_dir():
            return False

        if not self._is_canonical_config_digest(
            source_config_digest
        ) or not self._is_canonical_config_digest(target_config_digest):
            return False

        # Pre-merge Issue #128 builds wrote flat PGA-*.json events. Parse that
        # legacy set once so already-probed workspaces remain reopenable.
        legacy_by_source: dict[str, set[str]] = {}
        for path in events_root.glob("PGA-*.json"):
            try:
                event = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                return False
            if not isinstance(event, Mapping):
                return False
            if event.get("event_type") != "project_profile_generation_advanced":
                continue
            if str(event.get("project_id") or "") != project_id:
                continue
            old_binding = event.get("old_binding")
            new_binding = event.get("new_binding")
            if not isinstance(old_binding, Mapping) or not isinstance(new_binding, Mapping):
                return False
            old_digest = old_binding.get("project_config_digest")
            new_digest = new_binding.get("project_config_digest")
            if not self._is_canonical_config_digest(
                old_digest
            ) or not self._is_canonical_config_digest(new_digest):
                return False
            legacy_by_source.setdefault(old_digest, set()).add(new_digest)

        pending = [source_config_digest]
        visited = {source_config_digest}
        while pending:
            current = pending.pop()
            if not self._is_canonical_config_digest(current):
                return False
            successors = set(legacy_by_source.get(current, ()))
            source_dir = events_root / "by-source" / current.removeprefix("sha256:")
            if source_dir.is_dir():
                for path in source_dir.glob("PGA-*.json"):
                    try:
                        event = json.loads(path.read_text(encoding="utf-8"))
                    except (OSError, ValueError, json.JSONDecodeError):
                        return False
                    if not isinstance(event, Mapping):
                        return False
                    try:
                        successor = self._event_successor(
                            event,
                            project_id=project_id,
                            source_config_digest=current,
                        )
                    except ValueError:
                        return False
                    if successor is not None:
                        successors.add(successor)

            for successor in successors:
                if successor == target_config_digest:
                    return True
                if successor not in visited:
                    visited.add(successor)
                    pending.append(successor)
        return False

    def active(self, state) -> Mapping[str, Any] | None:
        try:
            active = self._store.load_active(state.project_ref)
        except LocalAttentionStoreError as exc:
            raise ConversationRuntimeError(exc.code, exc.message) from exc
        if active is None:
            return None
        document = active["map"]
        project_matches = (
            document["project_id"] == state.project_ref
            and document["project_config"]["ref"] == state.project_config_ref
        )
        config_matches = self._profile_generation_connects(
            project_id=state.project_ref,
            source_config_digest=str(document["project_config"]["digest"]),
            target_config_digest=str(state.project_config_digest),
        )
        if not project_matches or not config_matches:
            raise ConversationRuntimeError(
                "ATTENTION-STALE-001", "active Attention Map is bound to a different Project Config"
            )
        return active

    def resolve(self, state):
        active = self.active(state)
        source_items = (
            active["map"]["items"]
            if active is not None
            else state.project_config.get("research_attention", ())
        )
        return active, deepcopy(list(source_items))

    def __call__(self, state):
        return self.resolve(state)[1]


class ResearchAttentionStatusHandler:
    def __init__(self, effective_attention: EffectiveResearchAttentionProvider) -> None:
        self._effective = effective_attention

    def execute(self, payload, *, state, actor, proposal):
        active, effective_attention = self._effective.resolve(state)
        return HarnessServiceResult(
            result_reference=(
                str(active["map_id"]) if active is not None else state.project_config_ref
            ),
            data={
                "baseline": {
                    "project_config_digest": state.project_config_digest,
                    "items": deepcopy(list(state.project_config.get("research_attention", ()))),
                },
                "active_map": (
                    {
                        "map_id": str(active["map_id"]),
                        "map_digest": str(active["map_digest"]),
                        "activation_id": str(active["activation_id"]),
                    }
                    if active is not None
                    else None
                ),
                "effective_attention": effective_attention,
            },
            research_state_mutation_performed=False,
        )


def _current_authoritative_rq_ids(state) -> set[str]:
    return {
        str(item["id"])
        for item in state.effective_objects()
        if item.get("kind") == "research_question"
        and item.get("project_id") == state.project_ref
        and item.get("adoption_state") in {"approved", "revised"}
    }


def _validate_attention_references(items, state) -> None:
    resource_ids = {
        str(item["reference_id"])
        for item in state.project_config.get("resource_references", ())
        if isinstance(item, Mapping) and item.get("reference_id")
    }
    seed_ids = {
        str(item["seed_id"])
        for item in state.project_config.get("research_questions", {}).get("seeds", ())
        if isinstance(item, Mapping) and item.get("seed_id")
    }
    rq_ids = _current_authoritative_rq_ids(state)
    attention_ids = [str(item["attention_id"]) for item in items]
    if len(attention_ids) != len(set(attention_ids)):
        raise ConversationRuntimeError("ATTENTION-IDENTITY-001", "Attention IDs must be unique")
    for item in items:
        unknown_resources = set(map(str, item.get("source_reference_ids", ()))) - resource_ids
        if unknown_resources:
            raise ConversationRuntimeError(
                "ATTENTION-REF-001",
                "Attention source_reference_ids do not resolve: "
                + ", ".join(sorted(unknown_resources)),
            )
        unknown_seeds = set(map(str, item.get("related_question_seed_ids", ()))) - seed_ids
        if unknown_seeds:
            raise ConversationRuntimeError(
                "ATTENTION-REF-001",
                "Attention related_question_seed_ids do not resolve: "
                + ", ".join(sorted(unknown_seeds)),
            )
        unknown_rqs = set(map(str, item.get("related_question_ids", ()))) - rq_ids
        if unknown_rqs:
            raise ConversationRuntimeError(
                "ATTENTION-REF-001",
                "Attention related_question_ids do not resolve to current authoritative Research Questions: "
                + ", ".join(sorted(unknown_rqs)),
            )


class ResearchAttentionProposeHandler:
    """Build and persist one immutable complete effective Attention snapshot."""

    def __init__(self, store, effective_attention, id_provider, clock) -> None:
        self._store = store
        self._effective = effective_attention
        self._ids = id_provider
        self._clock = clock

    def execute(self, payload, *, state, actor, proposal):
        active, effective_items = self._effective.resolve(state)
        items = [deepcopy(dict(item)) for item in effective_items]
        by_id = {str(item["attention_id"]): item for item in items}

        for addition in payload.get("additions", ()):
            attention_id = self._ids.new("ATT-")
            if attention_id in by_id:
                raise ConversationRuntimeError(
                    "ATTENTION-IDENTITY-001",
                    "Harness-generated Attention ID collides with current effective Attention",
                )
            item: dict[str, Any] = {
                "attention_id": attention_id,
                "statement": str(addition["statement"]),
                "disposition": "active",
            }
            for field in (
                "rationale",
                "source_reference_ids",
                "related_question_ids",
                "related_question_seed_ids",
                "projection_hints",
            ):
                if field in addition:
                    item[field] = deepcopy(addition[field])
            items.append(item)
            by_id[attention_id] = item

        for change in payload.get("dispositions", ()):
            attention_id = str(change["attention_id"])
            item = by_id.get(attention_id)
            if item is None:
                raise ConversationRuntimeError(
                    "ATTENTION-UNKNOWN-001", f"unknown effective Attention ID: {attention_id}"
                )
            item["disposition"] = str(change["disposition"])
            if "disposition_reason" in change:
                item["disposition_reason"] = str(change["disposition_reason"])
            elif item["disposition"] == "active":
                item.pop("disposition_reason", None)

        for change in payload.get("links", ()):
            attention_id = str(change["attention_id"])
            item = by_id.get(attention_id)
            if item is None:
                raise ConversationRuntimeError(
                    "ATTENTION-UNKNOWN-001", f"unknown effective Attention ID: {attention_id}"
                )
            for field in ("related_question_ids", "related_question_seed_ids"):
                if field in change:
                    item[field] = list(change[field])

        _validate_attention_references(items, state)
        base = (
            {
                "source": "active_map",
                "map_id": str(active["map_id"]),
                "map_digest": str(active["map_digest"]),
            }
            if active is not None
            else {"source": "project_config_baseline"}
        )
        candidate: dict[str, Any] = {
            "schema_version": "0.1.0",
            "map_id": self._ids.new("ATTMAP-"),
            "project_id": state.project_ref,
            "project_config": {
                "ref": state.project_config_ref,
                "digest": state.project_config_digest,
            },
            "base": base,
            "items": items,
            "provenance": {
                "source_action_proposal_id": str(proposal["proposal_id"]),
                "source_action_proposal_digest": str(proposal["proposal_digest"]),
                "source_input_id": str(proposal["source"]["input_id"]),
            },
            "created_at": self._clock.now(),
        }
        candidate["map_digest"] = attention_map_digest(candidate)
        try:
            self._store.store_map(candidate)
        except LocalAttentionStoreError as exc:
            raise ConversationRuntimeError(exc.code, exc.message) from exc
        return HarnessServiceResult(
            result_reference=str(candidate["map_id"]),
            data={"attention_map": deepcopy(candidate), "active_map_changed": False},
            research_state_mutation_performed=False,
        )


class ResearchAttentionActivateHandler:
    def __init__(self, store, id_provider, clock) -> None:
        self._store = store
        self._ids = id_provider
        self._clock = clock

    def execute(self, payload, *, state, actor, proposal):
        map_id = str(payload["attention_map_id"])
        try:
            candidate = self._store.load_map(map_id)
        except LocalAttentionStoreError as exc:
            raise ConversationRuntimeError(exc.code, exc.message) from exc
        if candidate is None:
            raise ConversationRuntimeError(
                "ATTENTION-MAP-UNKNOWN-001", f"unknown Attention Map: {map_id}"
            )
        if (
            candidate["project_id"] != state.project_ref
            or candidate["project_config"]["ref"] != state.project_config_ref
            or candidate["project_config"]["digest"] != state.project_config_digest
        ):
            raise ConversationRuntimeError(
                "ATTENTION-STALE-001",
                "Attention Map is bound to a different current project/configuration",
            )
        try:
            event = self._store.activate(
                project_id=state.project_ref,
                map_id=map_id,
                activation_id=self._ids.new("ATTACT-"),
                actor_id=str(actor.get("actor_id", "")),
                source_action_proposal=proposal,
                activated_at=self._clock.now(),
            )
        except LocalAttentionStoreError as exc:
            raise ConversationRuntimeError(exc.code, exc.message) from exc
        return HarnessServiceResult(
            result_reference=str(event["activation_id"]),
            data={
                "activation": deepcopy(event),
                "active_map": {
                    "map_id": str(candidate["map_id"]),
                    "map_digest": str(candidate["map_digest"]),
                    "activation_id": str(event["activation_id"]),
                },
            },
            research_state_mutation_performed=False,
        )


def _attention_status_payload(payload: Mapping[str, Any]) -> None:
    if payload:
        raise ValueError("research_attention.status payload must be empty")


def _string_list(value, field: str) -> None:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{field} must be an array of non-empty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{field} must not contain duplicates")


def _attention_proposal_payload(payload: Mapping[str, Any]) -> None:
    allowed = {"additions", "dispositions", "links", "rationale"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(
            "research_attention.propose payload contains unknown fields: "
            + ", ".join(sorted(str(item) for item in unknown))
        )
    operations = 0
    additions = payload.get("additions", [])
    dispositions = payload.get("dispositions", [])
    links = payload.get("links", [])
    for name, value in (("additions", additions), ("dispositions", dispositions), ("links", links)):
        if not isinstance(value, list):
            raise ValueError(f"{name} must be an array")
        operations += len(value)
    if not operations:
        raise ValueError("research_attention.propose requires at least one bounded operation")
    if "rationale" in payload and (
        not isinstance(payload["rationale"], str) or not payload["rationale"].strip()
    ):
        raise ValueError("rationale must be a non-empty string")

    addition_allowed = {
        "statement",
        "rationale",
        "source_reference_ids",
        "related_question_ids",
        "related_question_seed_ids",
        "projection_hints",
    }
    for item in additions:
        if not isinstance(item, Mapping) or set(item) - addition_allowed:
            raise ValueError("addition contains unknown or forbidden fields")
        if not isinstance(item.get("statement"), str) or not item["statement"].strip():
            raise ValueError("addition requires non-empty statement")
        if "rationale" in item and not isinstance(item["rationale"], str):
            raise ValueError("addition rationale must be a string")
        for field in ("source_reference_ids", "related_question_ids", "related_question_seed_ids"):
            if field in item:
                _string_list(item[field], field)
        if "projection_hints" in item and not isinstance(item["projection_hints"], list):
            raise ValueError("projection_hints must be an array")

    seen_dispositions: set[str] = set()
    for item in dispositions:
        if not isinstance(item, Mapping) or set(item) - {
            "attention_id",
            "disposition",
            "disposition_reason",
        }:
            raise ValueError("disposition update contains unknown fields")
        if set(item) < {"attention_id", "disposition"}:
            raise ValueError("disposition update requires attention_id and disposition")
        attention_id = item.get("attention_id")
        if (
            not isinstance(attention_id, str)
            or not attention_id.strip()
            or attention_id in seen_dispositions
        ):
            raise ValueError("disposition attention_id must be unique and non-empty")
        seen_dispositions.add(attention_id)
        disposition = item.get("disposition")
        if disposition not in {"active", "dropped", "out_of_scope"}:
            raise ValueError("invalid Attention disposition")
        reason = item.get("disposition_reason")
        if disposition in {"dropped", "out_of_scope"} and (
            not isinstance(reason, str) or not reason.strip()
        ):
            raise ValueError("dropped/out_of_scope Attention requires disposition_reason")
        if reason is not None and (not isinstance(reason, str) or not reason.strip()):
            raise ValueError("disposition_reason must be a non-empty string")

    seen_links: set[str] = set()
    for item in links:
        if not isinstance(item, Mapping) or set(item) - {
            "attention_id",
            "related_question_ids",
            "related_question_seed_ids",
        }:
            raise ValueError("link update contains unknown fields")
        attention_id = item.get("attention_id")
        if (
            not isinstance(attention_id, str)
            or not attention_id.strip()
            or attention_id in seen_links
        ):
            raise ValueError("link attention_id must be unique and non-empty")
        seen_links.add(attention_id)
        if not ({"related_question_ids", "related_question_seed_ids"} & set(item)):
            raise ValueError("link update requires at least one relation field")
        for field in ("related_question_ids", "related_question_seed_ids"):
            if field in item:
                _string_list(item[field], field)


def _attention_activate_payload(payload: Mapping[str, Any]) -> None:
    if set(payload) != {"attention_map_id"}:
        raise ValueError("research_attention.activate_candidate accepts only attention_map_id")
    if (
        not isinstance(payload.get("attention_map_id"), str)
        or not payload["attention_map_id"].strip()
    ):
        raise ValueError("attention_map_id must be a non-empty string")
