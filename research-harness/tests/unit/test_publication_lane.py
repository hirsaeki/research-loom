import pytest

from misco_harness.models import (
    PublicationFeedback,
    PublicationState,
    PublicationStructure,
    PublicationStructureChange,
    PublicationStructureNode,
    PublicationWriterOutput,
    ResearchState,
)
from misco_harness.publication_lane import (
    PublicationLaneError,
    apply_structure_changes,
    refresh_publication_state,
)


def base_structure() -> PublicationStructure:
    return PublicationStructure(
        structure_id="structure-1",
        source_research_state_id="research-1",
        source_attention_map_id="attention-map",
        nodes=[
            PublicationStructureNode(node_id="chapter-1", kind="CHAPTER", title="Background", position=0),
            PublicationStructureNode(
                node_id="section-1-1", kind="SECTION", title="Scope", parent_id="chapter-1", position=0,
            ),
            PublicationStructureNode(node_id="chapter-2", kind="CHAPTER", title="Findings", position=1),
        ],
    )


def test_publication_structure_supports_reader_facing_deltas() -> None:
    updated = apply_structure_changes(base_structure(), [
        PublicationStructureChange(
            action="ADD",
            node=PublicationStructureNode(node_id="chapter-3", kind="CHAPTER", title="Implications", position=2),
        ),
        PublicationStructureChange(
            action="ADD",
            node=PublicationStructureNode(
                node_id="section-3-1", kind="SECTION", title="Limits", parent_id="chapter-3", position=0,
            ),
        ),
        PublicationStructureChange(action="RENAME", node_ids=["chapter-1"], new_title="Research Context"),
        PublicationStructureChange(action="MOVE", node_ids=["section-1-1"], new_parent_id="chapter-2"),
        PublicationStructureChange(
            action="SPLIT",
            node_ids=["section-1-1"],
            new_nodes=[
                PublicationStructureNode(
                    node_id="section-1-1-a", kind="SECTION", title="Observed scope", parent_id="chapter-2", position=1,
                ),
                PublicationStructureNode(
                    node_id="section-1-1-b", kind="SECTION", title="Uncertainty", parent_id="chapter-2", position=2,
                ),
            ],
        ),
        PublicationStructureChange(
            action="MERGE", node_ids=["section-1-1-a"], target_node_id="section-1-1-b",
        ),
        PublicationStructureChange(action="REMOVE", node_ids=["chapter-3"]),
    ])
    assert updated.revision == 7
    assert {node.node_id for node in updated.nodes} == {"chapter-1", "chapter-2", "section-1-1", "section-1-1-b"}
    assert next(node for node in updated.nodes if node.node_id == "chapter-1").title == "Research Context"
    assert not any(node.node_id == "chapter-3" for node in updated.nodes)


def test_refresh_requires_current_publication_eligibility() -> None:
    with pytest.raises(PublicationLaneError):
        refresh_publication_state(
            research_state=ResearchState(state_id="research-1"),
            current_state=PublicationState(state_id="publication-1"),
            attention_map_text="# Map",
            attention_map_artifact_id="attention-map",
            state_id="publication-2",
            structure_id="structure-2",
            draft_id="draft-2",
        )


def test_writer_feedback_and_draft_are_explicitly_non_research() -> None:
    feedback = PublicationFeedback(feedback_id="feedback-1", type="ARGUMENT_GAP", problem="missing link")
    output = PublicationWriterOutput(
        output_id="writer-output-1",
        publication_state=PublicationState(state_id="publication-2"),
        feedback=[feedback],
    )
    assert output.feedback[0].evidence_eligible is False
    assert output.feedback[0].research_state_mutation is False
    assert output.publication_state.structure is None
