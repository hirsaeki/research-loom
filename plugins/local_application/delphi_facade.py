from __future__ import annotations

from collections import Counter
from copy import deepcopy
from pathlib import Path
from statistics import median
from typing import Any, Mapping

from plugins.local_delphi_store import (
    LocalDelphiStore,
    LocalDelphiStoreError,
    canonical_digest,
    registry_digest,
)
from .facade import LocalApplicationError
from .survey_analysis_facade import LocalApplicationFacade as _BaseLocalApplicationFacade
from .survey_facade import _snapshot
from .survey_validation import schema_validate, validate_digest, validate_rqs

_ROOT = Path(__file__).resolve().parents[2]
_DESIGN_SCHEMA = _ROOT / "core/packages/delphi/delphi-design.schema.json"
_CONTRACT_SCHEMA = _ROOT / "core/packages/delphi/delphi-contract.schema.json"
_STORE_NAME = "delphi-registry.sqlite3"
_ALLOWED_STATES = {"answered", "missing", "not_applicable", "prefer_not_to_answer"}


def _str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LocalApplicationError("APPLICATION-DELPHI-INPUT-001", f"{field} must be a non-empty string")
    return value


def _str_list(value: Any, field: str, *, allow_empty: bool = False) -> list[str]:
    if (
        not isinstance(value, list)
        or (not value and not allow_empty)
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise LocalApplicationError("APPLICATION-DELPHI-INPUT-001", f"{field} must be a unique string array")
    return list(value)


def _schema_instrument(value: Mapping[str, Any]) -> None:
    schema_validate(dict(value), _CONTRACT_SCHEMA, "APPLICATION-DELPHI-INSTRUMENT-SCHEMA-001")
    if value.get("object_type") != "delphi_round_instrument":
        raise LocalApplicationError(
            "APPLICATION-DELPHI-INSTRUMENT-SCHEMA-001",
            "Delphi Instrument must be a canonical delphi_round_instrument",
        )
    validate_digest(dict(value), "content_digest", "APPLICATION-DELPHI-INSTRUMENT-DIGEST-001")


def _item_map(instrument: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    items = instrument.get("items")
    if not isinstance(items, list):
        raise LocalApplicationError("APPLICATION-DELPHI-INSTRUMENT-001", "Delphi Instrument items are invalid")
    result: dict[str, Mapping[str, Any]] = {}
    for item in items:
        if not isinstance(item, Mapping):
            raise LocalApplicationError("APPLICATION-DELPHI-INSTRUMENT-001", "Delphi Instrument item is invalid")
        item_id = _str(item.get("item_id"), "item_id")
        if item_id in result:
            raise LocalApplicationError("APPLICATION-DELPHI-INSTRUMENT-001", "Delphi item IDs must be unique")
        result[item_id] = item
    return result


def _numeric_answer_with_field(answer: Mapping[str, Any]) -> tuple[str | None, float | None]:
    for field in ("rating", "probability", "confidence"):
        value = answer.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return field, float(value)
    return None, None


def _numeric_answer(answer: Mapping[str, Any]) -> float | None:
    return _numeric_answer_with_field(answer)[1]


def _decision_matches(state, decision_id: Any, instrument_id: str, choice: str) -> bool:
    for decision in state.decisions:
        if str(decision.get("id")) != str(decision_id):
            continue
        if (
            str(decision.get("project_id", state.project_ref)) != str(state.project_ref)
            or decision.get("actor_type") != "human"
            or decision.get("decision_kind") != "research_revision"
        ):
            return False
        subjects = decision.get("subjects")
        return bool(
            decision.get("choice") == choice
            and isinstance(subjects, list)
            and any(
                isinstance(subject, Mapping)
                and subject.get("kind") == "instrument"
                and str(subject.get("id")) == instrument_id
                for subject in subjects
            )
        )
    return False


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Minimal production two-round Delphi registry and inspection surface."""

    def _delphi_store(self) -> LocalDelphiStore:
        root = self._workspace_root or getattr(self._application, "root", None)
        if root is None:
            raise LocalApplicationError("APPLICATION-DELPHI-STORE-001", "Delphi registry requires a local application root")
        base = Path(root)
        path = base / ".research-loom" / _STORE_NAME if self._workspace_root is not None else base / _STORE_NAME
        return LocalDelphiStore(path)

    def _delphi_state(self):
        repository = self._application.state_repository
        lineage = repository.load_active_lineage_ref(self._project_id)
        return repository.load_state_view(self._project_id, lineage)

    def _persist(self, document: dict[str, Any]) -> bool:
        document["registry_digest"] = registry_digest(document)
        try:
            return self._delphi_store().capture(document)
        except LocalDelphiStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc

    def capture_delphi_design(self, input_value: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(input_value, Mapping) or set(input_value) != {"rq_ids", "panel_id", "design"}:
            raise LocalApplicationError("APPLICATION-DELPHI-INPUT-001", "Delphi Design capture requires rq_ids, panel_id, and design")
        rq_ids = _str_list(input_value["rq_ids"], "rq_ids")
        panel_id = _str(input_value["panel_id"], "panel_id")
        design = input_value["design"]
        if not isinstance(design, Mapping):
            raise LocalApplicationError("APPLICATION-DELPHI-INPUT-001", "design must be an object")
        design = deepcopy(dict(design))
        schema_validate(design, _DESIGN_SCHEMA, "APPLICATION-DELPHI-DESIGN-SCHEMA-001")
        validate_digest(design, "content_digest", "APPLICATION-DELPHI-DESIGN-DIGEST-001")
        planned = design["planned_rounds"]
        planned_sequences = {int(item["sequence"]) for item in planned["round_plan"]}
        if (
            int(planned["minimum_rounds"]) != 2
            or int(planned["maximum_approved_rounds"]) != 2
            or len(planned["round_plan"]) != 2
            or planned_sequences != {1, 2}
        ):
            raise LocalApplicationError(
                "APPLICATION-DELPHI-ROUND-001",
                "the production slice requires exactly approved Round 1 and Round 2 plans",
            )
        state = self._delphi_state()
        validate_rqs(rq_ids, state)
        document = {
            "schema_version": "0.1.0", "project_id": self._project_id,
            "document_kind": "design", "identity": str(design["delphi_design_id"]),
            "version": str(design["version"]), "panel_id": panel_id,
            "round_sequence": None, "content_digest": str(design["content_digest"]),
            "created_at": self._application.clock.now(), "rq_ids": rq_ids,
            "captured_against": _snapshot(state), "design": design,
        }
        created = self._capture(state, lambda: self._persist(document))
        return {"status": "CAPTURED" if created else "ALREADY_CAPTURED", "delphi_design_id": document["identity"], "version": document["version"], "panel_id": panel_id, "content_digest": document["content_digest"]}

    def show_delphi_design(self, design_id: str, version: str) -> Mapping[str, Any]:
        record = self._delphi_store().load(self._project_id, "design", _str(design_id, "delphi_design_id"), _str(version, "version"))
        if record is None:
            raise LocalApplicationError("APPLICATION-DELPHI-DESIGN-001", "unknown Delphi Design revision")
        return {"status": "OK", "delphi_design": record}

    def capture_delphi_instrument(self, input_value: Mapping[str, Any]) -> Mapping[str, Any]:
        allowed = {"delphi_design_id", "delphi_design_version", "panel_id", "instrument", "derived_from"}
        if not isinstance(input_value, Mapping) or set(input_value) - allowed:
            raise LocalApplicationError("APPLICATION-DELPHI-INPUT-001", "Delphi Instrument capture contains unknown fields")
        design_id = _str(input_value.get("delphi_design_id"), "delphi_design_id")
        design_version = _str(input_value.get("delphi_design_version"), "delphi_design_version")
        panel_id = _str(input_value.get("panel_id"), "panel_id")
        design = self._delphi_store().load(self._project_id, "design", design_id, design_version)
        if design is None or str(design.get("panel_id")) != panel_id:
            raise LocalApplicationError("APPLICATION-DELPHI-BINDING-001", "Delphi Design/panel binding does not resolve")
        instrument = input_value.get("instrument")
        if not isinstance(instrument, Mapping):
            raise LocalApplicationError("APPLICATION-DELPHI-INPUT-001", "instrument must be an object")
        instrument = deepcopy(dict(instrument))
        _schema_instrument(instrument)
        state = self._delphi_state()
        instrument_id = str(instrument["instrument_id"])
        if instrument.get("approval_status") == "approved" and not _decision_matches(
            state, instrument.get("approval_decision_id"), instrument_id, "approve"
        ):
            raise LocalApplicationError(
                "APPLICATION-DELPHI-AUTHORITY-001",
                "approved Delphi Instrument requires an exact Human Decision",
            )
        if instrument.get("material_revision") is True and not _decision_matches(
            state, instrument.get("material_revision_decision_id"), instrument_id, "revise"
        ):
            raise LocalApplicationError(
                "APPLICATION-DELPHI-AUTHORITY-001",
                "material Delphi revision requires an exact Human Decision",
            )
        round_sequence = int(instrument["round_sequence"])
        if round_sequence not in {1, 2}:
            raise LocalApplicationError("APPLICATION-DELPHI-ROUND-001", "production slice supports exactly Round 1 and Round 2")
        derived = input_value.get("derived_from")
        if round_sequence == 1:
            if derived is not None:
                raise LocalApplicationError("APPLICATION-DELPHI-LINEAGE-001", "Round 1 must not claim prior-round derivation")
        else:
            required = {"prior_instrument_id", "prior_instrument_version", "prior_instrument_digest", "prior_round_result_id", "prior_round_result_digest", "feedback_id", "feedback_digest"}
            if not isinstance(derived, Mapping) or set(derived) != required:
                raise LocalApplicationError("APPLICATION-DELPHI-LINEAGE-001", "Round 2 requires exact prior Instrument, Round 1 result, and feedback bindings")
            prior_inst = self._delphi_store().load(self._project_id, "instrument", _str(derived["prior_instrument_id"], "prior_instrument_id"), _str(derived["prior_instrument_version"], "prior_instrument_version"))
            prior_round = self._delphi_store().load(self._project_id, "round", _str(derived["prior_round_result_id"], "prior_round_result_id"), "1")
            feedback = self._delphi_store().load(self._project_id, "feedback", _str(derived["feedback_id"], "feedback_id"), "1")
            if (
                prior_inst is None or prior_round is None or feedback is None
                or int(prior_inst.get("round_sequence") or 0) != 1
                or str(prior_inst.get("panel_id")) != panel_id
                or str(prior_round.get("panel_id")) != panel_id
                or str(feedback.get("panel_id")) != panel_id
                or str(prior_inst.get("content_digest")) != str(derived["prior_instrument_digest"])
                or str(prior_round.get("content_digest")) != str(derived["prior_round_result_digest"])
                or not isinstance(prior_round.get("instrument_ref"), Mapping)
                or str(prior_round["instrument_ref"].get("instrument_id")) != str(derived["prior_instrument_id"])
                or str(prior_round["instrument_ref"].get("version")) != str(derived["prior_instrument_version"])
                or str(prior_round["instrument_ref"].get("content_digest")) != str(derived["prior_instrument_digest"])
                or str(feedback.get("content_digest")) != str(derived["feedback_digest"])
                or str(feedback.get("source_round_result_id")) != str(prior_round["identity"])
            ):
                raise LocalApplicationError("APPLICATION-DELPHI-LINEAGE-001", "Round 2 derivation binding is stale or mismatched")
            prior_items = _item_map(prior_inst["instrument"])
            if not instrument.get("revision_changes"):
                raise LocalApplicationError("APPLICATION-DELPHI-LINEAGE-001", "Round 2 must record explicit revision changes")
            for item in instrument["items"]:
                lineage = item.get("lineage")
                if item["item_id"] in prior_items:
                    controlled_feedback = item.get("controlled_feedback")
                    if (
                        not isinstance(lineage, Mapping)
                        or str(lineage.get("prior_item_id")) != str(item["item_id"])
                        or not isinstance(controlled_feedback, Mapping)
                        or str(controlled_feedback.get("feedback_id")) != str(derived["feedback_id"])
                        or str(controlled_feedback.get("feedback_digest")) != str(derived["feedback_digest"])
                    ):
                        raise LocalApplicationError(
                            "APPLICATION-DELPHI-LINEAGE-001",
                            "retained Round 2 items require explicit prior-item and controlled-feedback lineage",
                        )
        document = {
            "schema_version": "0.1.0", "project_id": self._project_id,
            "document_kind": "instrument", "identity": str(instrument["instrument_id"]),
            "version": str(instrument["version"]), "panel_id": panel_id,
            "round_sequence": round_sequence, "content_digest": str(instrument["content_digest"]),
            "created_at": self._application.clock.now(),
            "captured_against": _snapshot(state),
            "design_ref": {"delphi_design_id": design_id, "version": design_version, "content_digest": design["content_digest"]},
            "derived_from": deepcopy(dict(derived)) if isinstance(derived, Mapping) else None,
            "instrument": instrument,
        }
        created = self._capture(state, lambda: self._persist(document))
        return {"status": "CAPTURED" if created else "ALREADY_CAPTURED", "instrument_id": document["identity"], "version": document["version"], "panel_id": panel_id, "round_sequence": round_sequence, "content_digest": document["content_digest"]}

    def show_delphi_instrument(self, instrument_id: str, version: str) -> Mapping[str, Any]:
        record = self._delphi_store().load(self._project_id, "instrument", _str(instrument_id, "instrument_id"), _str(version, "version"))
        if record is None:
            raise LocalApplicationError("APPLICATION-DELPHI-INSTRUMENT-001", "unknown Delphi Instrument revision")
        return {"status": "OK", "delphi_instrument": record}

    def capture_delphi_round(self, input_value: Mapping[str, Any]) -> Mapping[str, Any]:
        required = {"panel_id", "instrument_id", "instrument_version", "instrument_digest", "expected_participant_ids", "responses"}
        if not isinstance(input_value, Mapping) or set(input_value) != required:
            raise LocalApplicationError("APPLICATION-DELPHI-INPUT-001", "Delphi Round capture requires exact panel/instrument binding, expected participants, and responses")
        panel_id = _str(input_value["panel_id"], "panel_id")
        instrument_id = _str(input_value["instrument_id"], "instrument_id")
        version = _str(input_value["instrument_version"], "instrument_version")
        instrument_record = self._delphi_store().load(self._project_id, "instrument", instrument_id, version)
        if (
            instrument_record is None
            or str(instrument_record.get("panel_id")) != panel_id
            or str(instrument_record.get("content_digest")) != str(input_value["instrument_digest"])
        ):
            raise LocalApplicationError("APPLICATION-DELPHI-BINDING-001", "Round response Instrument/panel binding is invalid")
        instrument = instrument_record["instrument"]
        if instrument.get("approval_status") != "approved":
            raise LocalApplicationError("APPLICATION-DELPHI-AUTHORITY-001", "Delphi response intake requires an approved Instrument revision")
        round_sequence = int(instrument_record["round_sequence"])
        expected = _str_list(input_value["expected_participant_ids"], "expected_participant_ids")
        items = _item_map(instrument)
        responses_raw = input_value["responses"]
        if not isinstance(responses_raw, list):
            raise LocalApplicationError("APPLICATION-DELPHI-INPUT-001", "responses must be an array")
        responses: list[dict[str, Any]] = []
        participant_ids: set[str] = set()
        response_ids: set[str] = set()
        for raw in responses_raw:
            if not isinstance(raw, Mapping) or set(raw) != {"response_id", "participant_id", "answers"}:
                raise LocalApplicationError("APPLICATION-DELPHI-RESPONSE-001", "Delphi response shape is invalid")
            response_id = _str(raw["response_id"], "response_id")
            participant_id = _str(raw["participant_id"], "participant_id")
            if response_id in response_ids or participant_id in participant_ids or participant_id not in expected:
                raise LocalApplicationError("APPLICATION-DELPHI-RESPONSE-001", "duplicate or unexpected Delphi response identity")
            response_ids.add(response_id); participant_ids.add(participant_id)
            answers_raw = raw["answers"]
            if not isinstance(answers_raw, list):
                raise LocalApplicationError("APPLICATION-DELPHI-RESPONSE-001", "answers must be an array")
            answers: dict[str, dict[str, Any]] = {}
            for ans in answers_raw:
                if not isinstance(ans, Mapping):
                    raise LocalApplicationError("APPLICATION-DELPHI-RESPONSE-001", "answer must be an object")
                allowed = {"item_id", "item_revision", "state", "rating", "probability", "confidence", "ranking", "rationale"}
                if set(ans) - allowed:
                    raise LocalApplicationError("APPLICATION-DELPHI-RESPONSE-001", "answer contains unknown fields")
                item_id = _str(ans.get("item_id"), "item_id")
                item = items.get(item_id)
                if item is None or item_id in answers or int(ans.get("item_revision", 0)) != int(item["item_revision"]):
                    raise LocalApplicationError("APPLICATION-DELPHI-BINDING-001", "answer item revision does not match the bound Instrument")
                state = ans.get("state")
                if state not in _ALLOWED_STATES:
                    raise LocalApplicationError("APPLICATION-DELPHI-RESPONSE-001", "unsupported Delphi answer state")
                value_fields = [field for field in ("rating", "probability", "confidence", "ranking", "rationale") if field in ans]
                mode_for_field = {"rationale": "free_text_rationale"}
                response_modes = set(item.get("response_modes", ()))
                if any(mode_for_field.get(field, field) not in response_modes for field in value_fields):
                    raise LocalApplicationError(
                        "APPLICATION-DELPHI-RESPONSE-001",
                        "answer uses a response mode not allowed by the Instrument",
                    )
                if state == "answered" and not value_fields:
                    raise LocalApplicationError("APPLICATION-DELPHI-RESPONSE-001", "answered Delphi item requires a response value")
                if state != "answered" and value_fields:
                    raise LocalApplicationError("APPLICATION-DELPHI-RESPONSE-001", "non-answered Delphi item must not carry response values")
                for field in ("rating", "probability", "confidence"):
                    if field in ans and (not isinstance(ans[field], (int, float)) or isinstance(ans[field], bool)):
                        raise LocalApplicationError("APPLICATION-DELPHI-RESPONSE-001", f"{field} must be numeric")
                if "ranking" in ans and (not isinstance(ans["ranking"], list) or any(not isinstance(x, str) or not x for x in ans["ranking"])):
                    raise LocalApplicationError("APPLICATION-DELPHI-RESPONSE-001", "ranking must be a string array")
                if "rationale" in ans and (not isinstance(ans["rationale"], str) or not ans["rationale"].strip()):
                    raise LocalApplicationError("APPLICATION-DELPHI-RESPONSE-001", "rationale must be non-empty")
                answers[item_id] = deepcopy(dict(ans))
            if set(answers) != set(items):
                raise LocalApplicationError("APPLICATION-DELPHI-RESPONSE-001", "each submitted response must preserve an answer state for every Instrument item")
            responses.append({
                "response_id": response_id,
                "participant_id": participant_id,
                "binding": {
                    "panel_id": panel_id,
                    "round_sequence": round_sequence,
                    "instrument_id": instrument_id,
                    "instrument_version": version,
                    "instrument_digest": instrument_record["content_digest"],
                },
                "answers": [answers[item_id] for item_id in items],
            })

        prior_round = None
        prior_by_participant: dict[str, Mapping[str, Any]] = {}
        if round_sequence == 2:
            rounds = self._delphi_store().panel_documents(self._project_id, panel_id, "round")
            prior = [row for row in rounds if int(row.get("round_sequence") or 0) == 1]
            if len(prior) != 1:
                raise LocalApplicationError("APPLICATION-DELPHI-LINEAGE-001", "Round 2 requires exactly one stored Round 1 result for the panel")
            prior_round = prior[0]
            prior_by_participant = {str(r["participant_id"]): r for r in prior_round["responses"]}

        item_analysis = []
        answers_by_response = [
            {str(answer["item_id"]): answer for answer in response["answers"]}
            for response in responses
        ]
        for item_id, item in items.items():
            answered = []
            missing_states = {state: 0 for state in sorted(_ALLOWED_STATES - {"answered"})}
            for response, answer_map in zip(responses, answers_by_response):
                answer = answer_map[item_id]
                if answer["state"] == "answered":
                    answered.append((str(response["participant_id"]), answer))
                else:
                    missing_states[str(answer["state"])] += 1
            numeric = [(pid, _numeric_answer(answer)) for pid, answer in answered]
            numeric = [(pid, value) for pid, value in numeric if value is not None]
            values = [value for _, value in numeric]
            center = median(values) if values else None
            positions = [
                {"participant_id": pid, "value": value, "minority": center is not None and value != center}
                for pid, value in numeric
            ]
            explicit_disagreement = len(set(values)) > 1 if values else False
            if not numeric:
                rankings = [
                    (pid, tuple(answer["ranking"]))
                    for pid, answer in answered
                    if isinstance(answer.get("ranking"), list)
                ]
                if rankings:
                    counts = Counter(value for _, value in rankings)
                    highest = max(counts.values())
                    modes = {value for value, count in counts.items() if count == highest}
                    positions = [
                        {
                            "participant_id": pid,
                            "value": list(value),
                            "minority": len(modes) == 1 and value not in modes,
                        }
                        for pid, value in rankings
                    ]
                    explicit_disagreement = len(counts) > 1
            item_analysis.append({
                "item_id": item_id,
                "item_revision": int(item["item_revision"]),
                "submitted_response_count": len(responses),
                "answered_count": len(answered),
                "missing_states": missing_states,
                "numeric_summary": None if not values else {"median": center, "minimum": min(values), "maximum": max(values), "distinct_count": len(set(values))},
                "explicit_disagreement": explicit_disagreement,
                "positions": positions,
                "rationales": [
                    {"participant_id": pid, "rationale": answer["rationale"]}
                    for pid, answer in answered if "rationale" in answer
                ],
            })

        missing_participants = sorted(set(expected) - participant_ids)
        attrited: list[str] = []
        late_joined: list[str] = []
        changes: list[dict[str, Any]] = []
        if prior_round is not None:
            prior_ids = set(prior_by_participant)
            attrited = sorted(prior_ids - participant_ids)
            late_joined = sorted(participant_ids - prior_ids)
            for response in responses:
                prior_response = prior_by_participant.get(str(response["participant_id"]))
                if prior_response is None:
                    continue
                prior_answers = {str(a["item_id"]): a for a in prior_response["answers"]}
                for answer in response["answers"]:
                    item_id = str(answer["item_id"])
                    old = prior_answers.get(item_id)
                    if old is None or old.get("state") != "answered" or answer.get("state") != "answered":
                        continue
                    before_field, before = _numeric_answer_with_field(old)
                    after_field, after = _numeric_answer_with_field(answer)
                    if before_field == after_field and before is not None and after is not None:
                        changes.append({
                            "participant_id": response["participant_id"],
                            "item_id": item_id,
                            "response_mode": before_field,
                            "before": before,
                            "after": after,
                            "changed": before != after,
                        })

        analysis = {
            "expected_participant_count": len(expected),
            "submitted_response_count": len(responses),
            "missing_response_count": len(missing_participants),
            "missing_participant_ids": missing_participants,
            "attrition_count": len(attrited),
            "attrited_participant_ids": attrited,
            "late_join_count": len(late_joined),
            "late_joined_participant_ids": late_joined,
            "explicit_disagreement_item_count": sum(1 for item in item_analysis if item["explicit_disagreement"]),
            "changed_opinion_count": sum(1 for change in changes if change["changed"]),
            "comparable_opinion_count": len(changes),
            "stability_ratio": None if not changes else round(sum(1 for change in changes if not change["changed"]) / len(changes), 6),
            "opinion_changes": changes,
        }
        result_id = f"DLR-{panel_id}-R{round_sequence}"
        payload_for_digest = {
            "panel_id": panel_id, "round_sequence": round_sequence,
            "instrument_ref": {"instrument_id": instrument_id, "version": version, "content_digest": instrument_record["content_digest"]},
            "expected_participant_ids": expected, "responses": responses,
            "item_analysis": item_analysis, "analysis": analysis,
        }
        content_digest = canonical_digest(payload_for_digest)
        document = {
            "schema_version": "0.1.0", "project_id": self._project_id,
            "document_kind": "round", "identity": result_id, "version": "1",
            "panel_id": panel_id, "round_sequence": round_sequence,
            "content_digest": content_digest, "created_at": self._application.clock.now(),
            **payload_for_digest,
            "candidate_only": True, "research_state_mutation_performed": False,
        }
        created = self._persist(document)
        return {"status": "CAPTURED" if created else "ALREADY_CAPTURED", "round_result_id": result_id, "content_digest": content_digest, "panel_id": panel_id, "round_sequence": round_sequence, "analysis": deepcopy(analysis), "item_analysis": deepcopy(item_analysis)}

    def show_delphi_round(self, round_result_id: str) -> Mapping[str, Any]:
        record = self._delphi_store().load(self._project_id, "round", _str(round_result_id, "round_result_id"), "1")
        if record is None:
            raise LocalApplicationError("APPLICATION-DELPHI-ROUND-001", "unknown Delphi Round result")
        return {"status": "OK", "delphi_round": record}

    def build_delphi_feedback(self, round_result_id: str) -> Mapping[str, Any]:
        round_record = self._delphi_store().load(self._project_id, "round", _str(round_result_id, "round_result_id"), "1")
        if round_record is None or int(round_record.get("round_sequence") or 0) != 1:
            raise LocalApplicationError("APPLICATION-DELPHI-FEEDBACK-001", "controlled feedback requires a stored Round 1 result")
        source_analysis_digest = canonical_digest({
            "item_analysis": round_record["item_analysis"],
            "analysis": round_record["analysis"],
        })
        feedback_payload = {
            "source_round_result_id": round_record["identity"],
            "source_round_result_digest": round_record["content_digest"],
            "source_analysis_digest": source_analysis_digest,
            "panel_id": round_record["panel_id"],
            "round_sequence": 1,
            "summaries": [
                {
                    "item_id": item["item_id"],
                    "item_revision": item["item_revision"],
                    "answered_count": item["answered_count"],
                    "missing_states": deepcopy(item["missing_states"]),
                    "numeric_summary": deepcopy(item["numeric_summary"]),
                    "explicit_disagreement": item["explicit_disagreement"],
                    "minority_positions": [
                        {"value": deepcopy(position["value"])}
                        for position in item["positions"] if position["minority"]
                    ],
                    "rationales": [entry["rationale"] for entry in item["rationales"]],
                }
                for item in round_record["item_analysis"]
            ],
        }
        digest = canonical_digest(feedback_payload)
        feedback_id = "DLF-" + digest.removeprefix("sha256:")[:24]
        document = {
            "schema_version": "0.1.0", "project_id": self._project_id,
            "document_kind": "feedback", "identity": feedback_id, "version": "1",
            "panel_id": round_record["panel_id"], "round_sequence": 1,
            "content_digest": digest, "created_at": self._application.clock.now(),
            **feedback_payload, "immutable": True, "candidate_only": True,
        }
        created = self._persist(document)
        return {"status": "CAPTURED" if created else "ALREADY_CAPTURED", "feedback_id": feedback_id, "content_digest": digest, "source_round_result_id": round_result_id, "summaries": deepcopy(document["summaries"])}

    def show_delphi_feedback(self, feedback_id: str) -> Mapping[str, Any]:
        record = self._delphi_store().load(self._project_id, "feedback", _str(feedback_id, "feedback_id"), "1")
        if record is None:
            raise LocalApplicationError("APPLICATION-DELPHI-FEEDBACK-001", "unknown Delphi feedback artifact")
        return {"status": "OK", "delphi_feedback": record}

    def inspect_delphi_panel(self, panel_id: str) -> Mapping[str, Any]:
        panel_id = _str(panel_id, "panel_id")
        rounds = self._delphi_store().panel_documents(self._project_id, panel_id, "round")
        instruments = self._delphi_store().panel_documents(self._project_id, panel_id, "instrument")
        feedback = self._delphi_store().panel_documents(self._project_id, panel_id, "feedback")
        stopping = self._delphi_store().panel_documents(self._project_id, panel_id, "stopping_candidate")
        return {
            "status": "OK", "panel_id": panel_id,
            "rounds": rounds, "instruments": instruments, "feedback_artifacts": feedback,
            "stopping_candidates": stopping,
        }

    def build_delphi_stopping_candidate(self, panel_id: str) -> Mapping[str, Any]:
        panel_id = _str(panel_id, "panel_id")
        rounds = self._delphi_store().panel_documents(self._project_id, panel_id, "round")
        round2 = [row for row in rounds if int(row.get("round_sequence") or 0) == 2]
        if len(round2) != 1:
            raise LocalApplicationError("APPLICATION-DELPHI-STOPPING-001", "stopping assessment requires exactly one Round 2 result")
        round2_record = round2[0]
        instrument_ref = round2_record.get("instrument_ref")
        if not isinstance(instrument_ref, Mapping):
            raise LocalApplicationError("APPLICATION-DELPHI-STOPPING-001", "Round 2 Instrument binding is missing")
        instrument_record = self._delphi_store().load(
            self._project_id,
            "instrument",
            _str(instrument_ref.get("instrument_id"), "instrument_id"),
            _str(instrument_ref.get("version"), "instrument_version"),
        )
        if (
            instrument_record is None
            or str(instrument_record.get("panel_id")) != panel_id
            or str(instrument_record.get("content_digest")) != str(instrument_ref.get("content_digest"))
        ):
            raise LocalApplicationError("APPLICATION-DELPHI-STOPPING-001", "Round 2 Instrument binding is stale or mismatched")
        design_ref = instrument_record.get("design_ref")
        if not isinstance(design_ref, Mapping):
            raise LocalApplicationError("APPLICATION-DELPHI-STOPPING-001", "Round 2 Design binding is missing")
        design_record = self._delphi_store().load(
            self._project_id,
            "design",
            _str(design_ref.get("delphi_design_id"), "delphi_design_id"),
            _str(design_ref.get("version"), "delphi_design_version"),
        )
        if (
            design_record is None
            or str(design_record.get("panel_id")) != panel_id
            or str(design_record.get("content_digest")) != str(design_ref.get("content_digest"))
        ):
            raise LocalApplicationError("APPLICATION-DELPHI-STOPPING-001", "bound Delphi Design is stale or mismatched")
        design = design_record["design"]
        analysis = round2_record["analysis"]
        max_rounds = int(design["planned_rounds"]["maximum_approved_rounds"])
        max_reached = 2 >= max_rounds
        stability_goal = design.get("stopping", {}).get("stability_goal", {})
        consensus_goal = design.get("stopping", {}).get("consensus_goal", {})
        minimum_stability = stability_goal.get("minimum_ratio") if isinstance(stability_goal, Mapping) else None
        maximum_disagreement = consensus_goal.get("maximum_disagreement_item_count") if isinstance(consensus_goal, Mapping) else None
        stability_met = None if not isinstance(minimum_stability, (int, float)) or isinstance(minimum_stability, bool) or analysis["stability_ratio"] is None else analysis["stability_ratio"] >= float(minimum_stability)
        disagreement_met = None if not isinstance(maximum_disagreement, int) or isinstance(maximum_disagreement, bool) else analysis["explicit_disagreement_item_count"] <= maximum_disagreement
        if max_reached:
            recommendation = "stop"
            rationale = "maximum approved round count has been reached"
        elif stability_met is True and disagreement_met is True:
            recommendation = "stop"
            rationale = "configured stability and disagreement goals are satisfied"
        else:
            recommendation = "continue"
            rationale = "approved rounds remain and configured stopping goals are not both satisfied"
        payload = {
            "panel_id": panel_id,
            "round2_result_id": round2[0]["identity"],
            "round2_result_digest": round2[0]["content_digest"],
            "recommendation": recommendation,
            "basis": {
                "maximum_approved_rounds": max_rounds,
                "maximum_approved_rounds_reached": max_reached,
                "stability_ratio": analysis["stability_ratio"],
                "configured_minimum_stability_ratio": minimum_stability,
                "stability_goal_satisfied": stability_met,
                "explicit_disagreement_item_count": analysis["explicit_disagreement_item_count"],
                "configured_maximum_disagreement_item_count": maximum_disagreement,
                "disagreement_goal_satisfied": disagreement_met,
                "attrition_count": analysis["attrition_count"],
                "missing_response_count": analysis["missing_response_count"],
            },
            "rationale": rationale,
            "limitations": [
                "Delphi consensus or stability is candidate analysis and is not truth or an adopted Finding.",
                "The recommendation does not perform a Research State transition.",
                "Human Decision remains required for any authoritative transition that depends on this Delphi result.",
            ],
            "candidate_only": True,
            "human_decision_required": True,
            "research_state_mutation_performed": False,
        }
        digest = canonical_digest(payload)
        candidate_id = "DLS-" + digest.removeprefix("sha256:")[:24]
        document = {
            "schema_version": "0.1.0", "project_id": self._project_id,
            "document_kind": "stopping_candidate", "identity": candidate_id, "version": "1",
            "panel_id": panel_id, "round_sequence": 2,
            "content_digest": digest, "created_at": self._application.clock.now(), **payload,
        }
        created = self._persist(document)
        return {"status": "CAPTURED" if created else "ALREADY_CAPTURED", "stopping_candidate_id": candidate_id, "content_digest": digest, **deepcopy(payload)}

    def show_delphi_stopping_candidate(self, candidate_id: str) -> Mapping[str, Any]:
        record = self._delphi_store().load(self._project_id, "stopping_candidate", _str(candidate_id, "stopping_candidate_id"), "1")
        if record is None:
            raise LocalApplicationError("APPLICATION-DELPHI-STOPPING-001", "unknown Delphi stopping candidate")
        return {"status": "OK", "delphi_stopping_candidate": record}
