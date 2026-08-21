from __future__ import annotations

import json
from pathlib import Path

from misco_harness.models import (
    PublicationBundleManifest,
    PublicationFeedback,
    PublicationState,
    PublicationWriterOutput,
)


class FakeWriterOutput(PublicationWriterOutput):
    """Deterministic writer envelope used by tests and local fixtures."""


class FakeWriterAdapter:
    """Deterministic RC1 interface fixture; it never invokes an LLM."""

    def run(self, bundle: Path, *, output_state_id: str) -> FakeWriterOutput:
        manifest = PublicationBundleManifest.model_validate(
            json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        )
        if manifest.output_status_ceiling != "INTEGRATED":
            raise ValueError("Writer bundle exceeds the RC1 INTEGRATED ceiling")
        state = PublicationState(
            state_id=output_state_id,
            status="INTEGRATED",
            source_research_state_id=manifest.research_snapshot_id,
        )
        feedback = [PublicationFeedback(
                feedback_id=f"feedback-{manifest.bundle_id}",
                type="ARGUMENT_GAP",
                problem="Deterministic fake-writer feedback for routing tests",
                suggested_destination="RESEARCH_SYNTHESIS",
            )]
        return FakeWriterOutput(output_id=f"writer-output-{manifest.bundle_id}", publication_state=state, feedback=feedback)
