from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .facade import LocalApplicationError
from .research_quality_evaluation import (
    ResearchQualityEvaluationError,
    basis_refs,
    evaluate,
    normalize_input,
)
from .synthesis_candidate_facade import LocalApplicationFacade as _BaseLocalApplicationFacade


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Public non-authoritative Research/Organization quality evaluation."""

    def evaluate_research_quality(self, input_value: Mapping[str, Any]) -> dict[str, Any]:
        try:
            normalized = normalize_input(input_value)
            state = self._current_state()
            evaluation = evaluate(state, normalized)
        except ResearchQualityEvaluationError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc

        refs = basis_refs(normalized)
        object_ids: list[str] = []
        for object_id in [
            str(normalized["rq_id"]),
            *refs["object_ids"],
            *[
                str(normalized[key])
                for key in ("finding_id", "claim_id", "method_id")
                if key in normalized
            ],
        ]:
            if object_id not in object_ids:
                object_ids.append(object_id)

        captured = self.capture_exhibit(
            {
                "kind": "note",
                "title": f"Research quality evaluation: {normalized['rq_id']}",
                "purpose": (
                    "Immutable Profile-bound Research/Organization quality evaluation; "
                    "not Research State adoption."
                ),
                "rq_ids": [str(normalized["rq_id"])],
                "source_run_ids": refs["run_ids"],
                "source_artifact_refs": [],
                "source_object_ids": object_ids,
                "derived_from_exhibit_ids": refs["exhibit_ids"],
                "content": {"representation": "json", "value": evaluation},
                "capture_origin": "research_quality_evaluator",
            }
        )
        return {
            "status": "EVALUATED",
            "project_id": self.project_id,
            "evaluation": deepcopy(evaluation),
            "evaluation_exhibit": deepcopy(captured["exhibit"]),
            "research_state_mutation_performed": False,
        }
