from __future__ import annotations

import re

from misco_harness.models import (
    PublicationDraft,
    PublicationFeedback,
    PublicationState,
    PublicationStructure,
    PublicationStructureChange,
    PublicationStructureNode,
    PublicationWriterOutput,
    ResearchState,
)


class PublicationLaneError(RuntimeError):
    pass


_CHAPTER_ROW = re.compile(r"^\|\s*(第\d+章[^|]+?)\s*\|")
_CHAPTER_HEADING = re.compile(r"^###\s+第(\d+)章")
_SECTION_ROW = re.compile(r"^\|\s*(\d+)[－-](\d+)\s+([^|]+?)\s*\|")


def generate_provisional_structure(
    research_state: ResearchState,
    attention_map_text: str | None = None,
    *,
    structure_id: str,
    attention_map_artifact_id: str | None = None,
) -> PublicationStructure:
    """Create a reader-facing structure from current state and map guidance.

    The map contributes candidate locations only. No node carries question,
    method, or answer authority, and no generated node is written to Research
    State.
    """
    nodes: list[PublicationStructureNode] = []
    chapter_numbers: dict[int, str] = {}
    for line in (attention_map_text or "").splitlines():
        match = _CHAPTER_ROW.match(line)
        if match:
            chapter_label = match.group(1).strip()
            number_match = re.match(r"第(\d+)章", chapter_label)
            if number_match:
                number = int(number_match.group(1))
                node_id = f"chapter-{number}"
                chapter_numbers[number] = node_id
                nodes.append(PublicationStructureNode(
                    node_id=node_id,
                    kind="CHAPTER",
                    title=chapter_label,
                    position=number - 1,
                attention_refs=[attention_map_artifact_id] if attention_map_artifact_id else [],
                ))

    current_chapter: int | None = None
    section_positions: dict[str, int] = {}
    for line in (attention_map_text or "").splitlines():
        heading = _CHAPTER_HEADING.match(line)
        if heading:
            current_chapter = int(heading.group(1))
            continue
        match = _SECTION_ROW.match(line)
        if not match or current_chapter is None or current_chapter not in chapter_numbers:
            continue
        section_number = int(match.group(2))
        node_id = f"section-{match.group(1)}-{match.group(2)}"
        parent_id = chapter_numbers[current_chapter]
        nodes.append(PublicationStructureNode(
            node_id=node_id,
            kind="SECTION",
            title=f"{match.group(1)}-{match.group(2)} {match.group(3).strip()}",
            parent_id=parent_id,
            position=section_number - 1,
            attention_refs=[attention_map_artifact_id] if attention_map_artifact_id else [],
        ))
        section_positions[parent_id] = max(section_positions.get(parent_id, -1), section_number - 1)

    def add_state_section(parent_number: int, suffix: str, title: str) -> None:
        parent_id = chapter_numbers.get(parent_number)
        if parent_id is None:
            return
        node_id = f"section-current-{suffix}"
        if any(item.node_id == node_id for item in nodes):
            return
        position = section_positions.get(parent_id, -1) + 1
        section_positions[parent_id] = position
        nodes.append(PublicationStructureNode(
            node_id=node_id,
            kind="SECTION",
            title=title,
            parent_id=parent_id,
            position=position,
        ))

    if research_state.questions:
        add_state_section(1, "question", "Current Research Question")
    if research_state.findings:
        add_state_section(8, "findings", "Current Findings and Limits")
    if research_state.evidence_gaps or research_state.evidence_gap_hypotheses:
        add_state_section(6, "gaps", "Open Evidence Gaps and Uncertainty")

    if not nodes:
        nodes = [PublicationStructureNode(
            node_id="chapter-current",
            kind="CHAPTER",
            title="Current Research and Findings",
            position=0,
        )]
        if research_state.questions:
            nodes.append(PublicationStructureNode(
                node_id="section-current-question",
                kind="SECTION",
                title="Current Research Question",
                parent_id="chapter-current",
                position=0,
            ))

    return PublicationStructure(
        structure_id=structure_id,
        source_research_state_id=research_state.state_id,
        source_attention_map_id=attention_map_artifact_id,
        nodes=nodes,
    )


def apply_structure_changes(
    structure: PublicationStructure,
    changes: list[PublicationStructureChange],
    *,
    source_research_state_id: str | None = None,
) -> PublicationStructure:
    nodes = {item.node_id: item for item in structure.nodes}

    def descendants(node_id: str) -> set[str]:
        removed = {node_id}
        changed = True
        while changed:
            changed = False
            for item in list(nodes.values()):
                if item.parent_id in removed and item.node_id not in removed:
                    removed.add(item.node_id)
                    changed = True
        return removed

    for change in changes:
        if change.action == "ADD":
            if change.node is None:
                raise PublicationLaneError("ADD requires a node")
            if change.node.node_id in nodes:
                raise PublicationLaneError(f"Publication Structure node already exists: {change.node.node_id}")
            nodes[change.node.node_id] = change.node
        elif change.action == "REMOVE":
            missing = set(change.node_ids).difference(nodes)
            if missing:
                raise PublicationLaneError(f"Publication Structure nodes are missing: {sorted(missing)}")
            for node_id in set().union(*(descendants(item) for item in change.node_ids)):
                nodes.pop(node_id, None)
        elif change.action == "MERGE":
            if change.target_node_id not in nodes:
                raise PublicationLaneError(f"MERGE target node is missing: {change.target_node_id}")
            missing = set(change.node_ids).difference(nodes)
            if missing:
                raise PublicationLaneError(f"MERGE source nodes are missing: {sorted(missing)}")
            source_node_ids = [item for item in change.node_ids if item != change.target_node_id]
            if not source_node_ids:
                raise PublicationLaneError("MERGE requires at least one source besides the target")
            for node_id in source_node_ids:
                for descendant_id in descendants(node_id):
                    nodes.pop(descendant_id, None)
        elif change.action == "SPLIT":
            missing = set(change.node_ids).difference(nodes)
            if len(change.node_ids) != 1 or missing:
                raise PublicationLaneError("SPLIT requires one existing node")
            for new_node in change.new_nodes:
                if new_node.node_id in nodes:
                    raise PublicationLaneError(f"SPLIT node already exists: {new_node.node_id}")
                nodes[new_node.node_id] = new_node
        elif change.action == "MOVE":
            if len(change.node_ids) != 1 or change.node_ids[0] not in nodes:
                raise PublicationLaneError("MOVE requires one existing node")
            parent_id = change.new_parent_id or change.target_node_id
            item = nodes[change.node_ids[0]]
            nodes[item.node_id] = item.model_copy(update={"parent_id": parent_id})
        elif change.action == "RENAME":
            if len(change.node_ids) != 1 or change.node_ids[0] not in nodes:
                raise PublicationLaneError("RENAME requires one existing node")
            nodes[change.node_ids[0]] = nodes[change.node_ids[0]].model_copy(update={"title": change.new_title})

    return PublicationStructure(
        structure_id=structure.structure_id,
        source_research_state_id=source_research_state_id or structure.source_research_state_id,
        source_attention_map_id=structure.source_attention_map_id,
        authority=structure.authority,
        revision=structure.revision + len(changes),
        nodes=list(nodes.values()),
        changes=[*structure.changes, *changes],
    )


def refresh_publication_state(
    *,
    research_state: ResearchState,
    current_state: PublicationState,
    attention_map_text: str | None = None,
    attention_map_artifact_id: str | None = None,
    state_id: str,
    structure_id: str,
    draft_id: str,
    changes: list[PublicationStructureChange] | None = None,
    draft_sections: dict[str, str] | None = None,
) -> PublicationState:
    if current_state.status in {"STALE", "REVIEW_REQUIRED", "REVOKED_PENDING_REVIEW"}:
        raise PublicationLaneError(
            f"Publication State is {current_state.status}; Human review must clear Recovery impact before refresh"
        )
    eligibility = research_state.publication_eligibility
    if (
        eligibility is None
        or eligibility.status != "ELIGIBLE"
        or not eligibility.is_snapshot_bound
        or eligibility.recorded_research_state_id != research_state.state_id
    ):
        raise PublicationLaneError(
            "Publication refresh requires snapshot-bound ELIGIBLE status for the current Research State; "
            "run 'rh publication request-eligibility' again"
        )
    structure = generate_provisional_structure(
        research_state,
        attention_map_text,
        structure_id=structure_id,
        attention_map_artifact_id=attention_map_artifact_id,
    )
    if current_state.structure is not None:
        existing_ids = {item.node_id for item in current_state.structure.nodes}
        new_guidance_nodes = [item for item in structure.nodes if item.node_id not in existing_ids]
        structure = current_state.structure.model_copy(update={
            "structure_id": structure_id,
            "source_research_state_id": research_state.state_id,
            "source_attention_map_id": attention_map_artifact_id,
            "nodes": [*current_state.structure.nodes, *new_guidance_nodes],
        })
    if changes:
        structure = apply_structure_changes(structure, changes, source_research_state_id=research_state.state_id)
    sections = draft_sections or {}
    unknown_sections = set(sections).difference(item.node_id for item in structure.nodes)
    if unknown_sections:
        raise PublicationLaneError(f"Publication Draft references unknown Structure nodes: {sorted(unknown_sections)}")
    draft = PublicationDraft(
        draft_id=draft_id,
        source_research_state_id=research_state.state_id,
        structure_id=structure.structure_id,
        status="REVISED" if current_state.draft is not None else "PROVISIONAL",
        sections=sections,
    )
    return PublicationState(
        state_id=state_id,
        status="REVISED" if current_state.status != "SCAFFOLD" else "PROVISIONAL",
        pending_decision_ids=current_state.pending_decision_ids,
        pending_feedback_ids=current_state.pending_feedback_ids,
        source_research_state_id=research_state.state_id,
        source_attention_map_id=attention_map_artifact_id,
        publication_eligibility=eligibility,
        structure=structure,
        draft=draft,
        prior_snapshot_id=current_state.state_id,
    )


def apply_writer_output(
    current_state: PublicationState,
    output: PublicationWriterOutput,
    *,
    state_id: str,
) -> PublicationState:
    if current_state.status in {"STALE", "REVIEW_REQUIRED", "REVOKED_PENDING_REVIEW"}:
        raise PublicationLaneError(
            f"Publication State is {current_state.status}; Writer output cannot clear Recovery impact"
        )
    if current_state.status in {"STABLE", "FINAL"}:
        raise PublicationLaneError("Publication Writer cannot overwrite a STABLE or FINAL Publication State")
    candidate = output.publication_state
    if candidate.status in {"STABLE", "FINAL"}:
        raise PublicationLaneError("Publication Writer cannot grant STABLE or FINAL status")
    if current_state.source_research_state_id and candidate.source_research_state_id not in {
        None,
        current_state.source_research_state_id,
    }:
        raise PublicationLaneError("Publication Writer output references a different Research State")
    if (
        candidate.publication_eligibility is not None
        and candidate.publication_eligibility != current_state.publication_eligibility
    ):
        raise PublicationLaneError("Publication Writer cannot change Research Publication Eligibility")
    if (
        candidate.structure is not None
        and current_state.source_research_state_id
        and candidate.structure.source_research_state_id != current_state.source_research_state_id
    ):
        raise PublicationLaneError("Publication Writer Structure references a different Research State")
    if (
        candidate.draft is not None
        and current_state.source_research_state_id
        and candidate.draft.source_research_state_id != current_state.source_research_state_id
    ):
        raise PublicationLaneError("Publication Writer Draft references a different Research State")
    feedback_ids = [*current_state.pending_feedback_ids]
    for item in output.feedback:
        if item.feedback_id not in feedback_ids:
            feedback_ids.append(item.feedback_id)
    return candidate.model_copy(update={
        "state_id": state_id,
        "pending_decision_ids": current_state.pending_decision_ids,
        "source_research_state_id": candidate.source_research_state_id or current_state.source_research_state_id,
        "source_attention_map_id": candidate.source_attention_map_id or current_state.source_attention_map_id,
        "publication_eligibility": candidate.publication_eligibility or current_state.publication_eligibility,
        "structure": candidate.structure or current_state.structure,
        "draft": candidate.draft or current_state.draft,
        "pending_feedback_ids": feedback_ids,
        "prior_snapshot_id": current_state.state_id,
    })


def feedback_is_publication_only(feedback: PublicationFeedback) -> bool:
    return not feedback.evidence_eligible and not feedback.research_state_mutation
