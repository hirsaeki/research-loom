"""Candidate Delphi statistics, partitioned by declared response mode and scale."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from math import isfinite
from typing import Any, Mapping

from .facade import LocalApplicationError

ANALYSIS_CONTRACT = "delphi-mode-scales@1"
NUMERIC_MODES = ("rating", "probability", "confidence")
MISSING_STATES = ("missing", "not_applicable", "prefer_not_to_answer")


def _finite_number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return isfinite(value) and (not isinstance(value, int) or abs(value) <= 9007199254740991)
    except OverflowError:
        return False


def validate_scales(instrument: Mapping[str, Any]) -> None:
    for item in instrument["items"]:
        scales = item.get("response_scales", {})
        if not isinstance(scales, Mapping) or set(scales) - set(NUMERIC_MODES):
            raise LocalApplicationError("APPLICATION-DELPHI-SCALE-001", "response_scales must map numeric modes to declared scales")
        for mode, scale in scales.items():
            if (mode not in item["response_modes"] or not isinstance(scale, Mapping)
                or set(scale) != {"scale_id", "minimum", "maximum"}
                or not isinstance(scale["scale_id"], str) or not scale["scale_id"].strip()
                or not _finite_number(scale["minimum"]) or not _finite_number(scale["maximum"])
                or scale["minimum"] >= scale["maximum"]):
                raise LocalApplicationError("APPLICATION-DELPHI-SCALE-001", "a declared scale requires its mode, scale_id, and finite increasing minimum/maximum")


def validate_numeric_answer(answer, item):
    for mode in NUMERIC_MODES:
        if mode not in answer:
            continue
        value = answer[mode]
        if not _finite_number(value):
            raise LocalApplicationError("APPLICATION-DELPHI-RESPONSE-001", f"{mode} must be a finite canonical JSON number")
        scale = item.get("response_scales", {}).get(mode)
        if scale is not None and not scale["minimum"] <= value <= scale["maximum"]:
            raise LocalApplicationError("APPLICATION-DELPHI-RESPONSE-001", f"{mode} is outside the Instrument's declared scale")


def _median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    low, high = ordered[middle - 1], ordered[middle]
    # Avoid overflow on two finite large values, without underflowing two
    # equal same-sign subnormals by halving both operands first.
    return low + (high - low) / 2 if (low >= 0 or high <= 0) else low / 2 + high / 2


def _item_analysis(item, responses):
    answered = []
    missing = {state: 0 for state in MISSING_STATES}
    for response in responses:
        answer = next(a for a in response["answers"] if a["item_id"] == item["item_id"])
        if answer["state"] == "answered":
            answered.append((response["participant_id"], answer))
        else:
            missing[answer["state"]] += 1
    modes = []
    for mode in NUMERIC_MODES:
        if mode not in item["response_modes"]:
            continue
        positions = [(pid, answer[mode]) for pid, answer in answered if mode in answer]
        values = [value for _, value in positions]
        scale = item.get("response_scales", {}).get(mode)
        status = "no_answers" if not values else "scale_not_declared" if scale is None else "summarized"
        center = _median(values) if status == "summarized" else None
        modes.append({
            "response_mode": mode, "scale": deepcopy(scale), "status": status,
            "answered_count": len(values), "missing_value_count": len(responses) - len(values),
            "numeric_summary": None if center is None else {"median": center, "minimum": min(values), "maximum": max(values), "distinct_count": len(set(values))},
            "explicit_disagreement": None if center is None else len(set(values)) > 1,
            "positions": [{"participant_id": pid, "value": value, "minority": center is not None and value != center} for pid, value in positions],
        })
    if "ranking" in item["response_modes"]:
        rankings = [(pid, tuple(answer["ranking"])) for pid, answer in answered if "ranking" in answer]
        counts = Counter(value for _, value in rankings)
        highest = max(counts.values()) if counts else 0
        common = {value for value, count in counts.items() if count == highest}
        modes.append({
            "response_mode": "ranking", "scale": None, "status": "summarized" if counts else "no_answers",
            "answered_count": len(rankings), "missing_value_count": len(responses) - len(rankings),
            "numeric_summary": None, "explicit_disagreement": len(counts) > 1 if counts else None,
            "positions": [{"participant_id": pid, "value": list(value), "minority": len(common) == 1 and value not in common} for pid, value in rankings],
        })
    numeric_modes = [group for group in modes if group["response_mode"] in NUMERIC_MODES]
    observed = [group for group in modes if group["answered_count"]]
    return {
        "item_id": item["item_id"], "item_revision": item["item_revision"],
        "submitted_response_count": len(responses), "answered_count": len(answered), "missing_states": missing,
        "mode_summaries": modes,
        # Compatibility projection only when the Instrument declares one numeric
        # mode. A rating and a probability can never share this scalar summary.
        "numeric_summary": deepcopy(numeric_modes[0]["numeric_summary"]) if len(numeric_modes) == 1 else None,
        "explicit_disagreement": any(group["explicit_disagreement"] is True for group in modes),
        "disagreement_assessed": bool(observed) and all(group["status"] == "summarized" for group in observed),
        "positions": [{**deepcopy(position), "response_mode": group["response_mode"]} for group in modes for position in group["positions"]],
        "rationales": [{"participant_id": pid, "rationale": answer["rationale"]} for pid, answer in answered if "rationale" in answer],
    }


def analyze_round(instrument, responses, expected, *, prior_round=None, prior_instrument=None):
    items = {item["item_id"]: item for item in instrument["items"]}
    summaries = [_item_analysis(item, responses) for item in items.values()]
    current_ids = {response["participant_id"] for response in responses}
    prior_responses = {} if prior_round is None else {row["participant_id"]: row for row in prior_round["responses"]}
    prior_items = {} if prior_instrument is None else {item["item_id"]: item for item in prior_instrument["items"]}
    changes, incomparable = [], []
    for response in responses:
        previous = prior_responses.get(response["participant_id"])
        if previous is None:
            continue
        old_answers = {answer["item_id"]: answer for answer in previous["answers"]}
        for answer in response["answers"]:
            old = old_answers.get(answer["item_id"])
            if old is None or old.get("state") != "answered" or answer["state"] != "answered":
                continue
            item = items[answer["item_id"]]
            old_item = prior_items.get(answer["item_id"], {})
            for mode in NUMERIC_MODES:
                if mode not in old and mode not in answer:
                    continue
                scale = item.get("response_scales", {}).get(mode)
                old_scale = old_item.get("response_scales", {}).get(mode)
                reason = None
                if mode not in old or mode not in answer:
                    reason = "response_mode_not_shared"
                elif scale is None or old_scale is None:
                    reason = "scale_not_declared"
                elif scale != old_scale:
                    reason = "scale_changed"
                elif item["text"] != old_item.get("text") or item["item_type"] != old_item.get("item_type"):
                    reason = "item_meaning_changed"
                binding = {"participant_id": response["participant_id"], "item_id": item["item_id"], "response_mode": mode}
                if reason:
                    incomparable.append({**binding, "reason": reason})
                else:
                    changes.append({**binding, "scale": deepcopy(scale), "before": old[mode], "after": answer[mode], "changed": old[mode] != answer[mode]})
    missing = sorted(set(expected) - current_ids)
    attrited = sorted(set(prior_responses) - current_ids) if prior_round is not None else []
    late = sorted(current_ids - set(prior_responses)) if prior_round is not None else []
    analysis = {
        "analysis_contract": ANALYSIS_CONTRACT,
        "expected_participant_count": len(expected), "submitted_response_count": len(responses),
        "missing_response_count": len(missing), "missing_participant_ids": missing,
        "attrition_count": len(attrited), "attrited_participant_ids": attrited,
        "late_join_count": len(late), "late_joined_participant_ids": late,
        "explicit_disagreement_item_count": sum(item["explicit_disagreement"] for item in summaries),
        "unassessed_disagreement_item_count": sum(not item["disagreement_assessed"] for item in summaries),
        "changed_opinion_count": sum(change["changed"] for change in changes),
        "comparable_opinion_count": len(changes),
        "stability_ratio": None if not changes else round(sum(not change["changed"] for change in changes) / len(changes), 6),
        "opinion_changes": changes, "incomparable_opinions": incomparable,
        "comparison_basis": None if prior_round is None else {"round_result_id": prior_round["identity"], "version": prior_round["version"], "content_digest": prior_round["content_digest"]},
    }
    return summaries, analysis


def require_current_analysis(record):
    if record.get("analysis", {}).get("analysis_contract") != ANALYSIS_CONTRACT:
        raise LocalApplicationError("APPLICATION-DELPHI-ANALYSIS-001", "legacy analysis is read-only; explicitly recalculate it into a new Round revision before building new feedback or stopping candidates")


def feedback_summaries(record):
    require_current_analysis(record)
    output = []
    for item in record["item_analysis"]:
        summary = {key: deepcopy(item[key]) for key in ("item_id", "item_revision", "answered_count", "missing_states", "numeric_summary", "explicit_disagreement", "disagreement_assessed")}
        summary["minority_positions"] = [{"response_mode": p["response_mode"], "value": deepcopy(p["value"])} for p in item["positions"] if p["minority"]]
        summary["rationales"] = [entry["rationale"] for entry in item["rationales"]]
        summary["mode_summaries"] = []
        for group in item["mode_summaries"]:
            deidentified = {key: deepcopy(value) for key, value in group.items() if key != "positions"}
            deidentified["positions"] = [{key: deepcopy(value) for key, value in position.items() if key != "participant_id"} for position in group["positions"]]
            summary["mode_summaries"].append(deidentified)
        output.append(summary)
    return output
