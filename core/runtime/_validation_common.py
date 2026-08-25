from __future__ import annotations

from typing import Any, Mapping, Sequence

from .transition_models import ValidationIssue, ValidationStage, canonical_digest


def _snapshot_digest(snapshot: Mapping[str, Any]) -> str:
    data = dict(snapshot)
    data.pop("content_digest", None)
    return canonical_digest(data)


def _issue(
    code: str,
    stage: ValidationStage,
    message: str,
    refs: tuple[str, ...] = (),
    retryable: bool = False,
) -> ValidationIssue:
    return ValidationIssue(error_code=code, stage=stage, message=message, affected_refs=refs, retryable=retryable)


def _dedupe_issues(issues: Sequence[ValidationIssue]) -> list[ValidationIssue]:
    result: list[ValidationIssue] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for issue in issues:
        key = (issue.error_code, issue.message, issue.affected_refs)
        if key not in seen:
            seen.add(key)
            result.append(issue)
    return result
