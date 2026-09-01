from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Mapping


def missing_semantics(question: Mapping[str, Any]) -> dict[str, Any]:
    declared = question.get("missing_value_semantics")
    result = {
        "missing": "no_response",
        "unknown_value": None,
        "not_applicable_value": None,
        "prefer_not_to_answer_value": None,
    }
    if not isinstance(declared, Mapping):
        return result
    option_values = {
        str(item["option_id"]): str(item.get("value", item["option_id"]))
        for item in question.get("response_options", [])
    }
    for source, target in (
        ("unknown_option_id", "unknown_value"),
        ("not_applicable_option_id", "not_applicable_value"),
        ("prefer_not_to_answer_option_id", "prefer_not_to_answer_value"),
    ):
        option_id = declared.get(source)
        if option_id is not None:
            result[target] = option_values[str(option_id)]
    return result


def question_projection(question: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(question["question_id"]),
        "variable": str(question.get("response_key", question["question_id"])),
        "type": str(question["question_type"]),
        "prompt": str(question["text"]),
        "required": bool(question["required"]),
        "choices": [
            {"value": str(option.get("value", option["option_id"])), "label": str(option["label"])}
            for option in question.get("response_options", [])
        ],
        "scale": deepcopy(question.get("scale")),
        "validation": deepcopy(question.get("numeric_constraints")),
        "branching": deepcopy(list(question.get("branching", []))),
        "missing_value_semantics": missing_semantics(question),
        "randomization_group_id": question.get("randomization_group_id"),
        "traceability": deepcopy(dict(question["traceability"])),
    }


def exchange_projection(record: Mapping[str, Any], design_record: Mapping[str, Any]) -> dict[str, Any]:
    questionnaire = record["questionnaire"]
    design = design_record["design"]
    declared = questionnaire.get("sections") or []
    if declared:
        sections = [
            {"id": str(s["section_id"]), "title": str(s["title"]), "description": str(s.get("description", "")), "questions": []}
            for s in declared
        ]
        by_id = {s["id"]: s for s in sections}
        for question in questionnaire["questions"]:
            by_id[str(question["section_id"])] ["questions"].append(question_projection(question))
    else:
        sections = [{
            "id": "SECTION-1", "title": "Questionnaire", "description": "",
            "questions": [question_projection(q) for q in questionnaire["questions"]],
        }]
    return {
        "schema_version": "0.1.0",
        "exchange_type": "research_loom_survey_instrument",
        "survey_id": str(design["survey_design_id"]),
        "survey_version": str(design["version"]),
        "survey_content_digest": str(design["content_digest"]),
        "instrument_id": str(questionnaire["questionnaire_id"]),
        "instrument_version": str(questionnaire["version"]),
        "instrument_content_digest": str(questionnaire["content_digest"]),
        "title": str(record["title"]),
        "description": str(record["description"]),
        "rq_ids": list(record["rq_ids"]),
        "snapshot_binding": deepcopy(dict(record["captured_against"])),
        "sections": sections,
    }


def _inline(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def markdown_projection(exchange: Mapping[str, Any]) -> str:
    lines = [
        f"# {exchange['title']}", "",
        f"- Survey ID: `{exchange['survey_id']}`",
        f"- Survey version: `{exchange['survey_version']}`",
        f"- Survey digest: `{exchange['survey_content_digest']}`",
        f"- Instrument ID: `{exchange['instrument_id']}`",
        f"- Instrument version: `{exchange['instrument_version']}`",
        f"- Instrument digest: `{exchange['instrument_content_digest']}`",
        f"- Research Questions: {', '.join(f'`{x}`' for x in exchange['rq_ids'])}",
        f"- Snapshot: `{exchange['snapshot_binding']['snapshot_ref']}`",
        f"- Snapshot digest: `{exchange['snapshot_binding']['snapshot_digest']}`",
    ]
    if exchange["description"]:
        lines += ["", exchange["description"]]
    for section in exchange["sections"]:
        lines += ["", f"## {section['title']} (`{section['id']}`)"]
        if section["description"]:
            lines += ["", section["description"]]
        for q in section["questions"]:
            lines += [
                "", f"### {q['id']}", f"- Variable: `{q['variable']}`", f"- Prompt: {q['prompt']}",
                f"- Type: `{q['type']}`", f"- Required: `{str(q['required']).lower()}`",
            ]
            if q["choices"]:
                lines.append("- Choices / stable values:")
                lines += [f"  - `{c['value']}` — {c['label']}" for c in q["choices"]]
            else:
                lines.append("- Choices / stable values: none")
            lines += [
                f"- Scale: `{_inline(q['scale'])}`",
                f"- Validation: `{_inline(q['validation'])}`",
                f"- Branching: `{_inline(q['branching'])}`",
                f"- Missing-value semantics: `{_inline(q['missing_value_semantics'])}`",
                f"- Traceability: `{_inline(q['traceability'])}`",
            ]
    return "\n".join(lines) + "\n"
