from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from core.runtime.transition_models import StateView

from .models import CapabilityExecutionError, ExecutionFailureCode, ExecutionIssue


class CapabilityContextExtensionValidator(Protocol):
    """Capability-specific, deterministic preflight validation.

    Validators inspect only the immutable execution documents, the supplied
    extension, and the already-loaded StateView. They must not perform resource
    access or mutate authoritative Research State.
    """

    def supports(
        self,
        capability_id: str,
        capability_version: str,
        function_id: str,
    ) -> bool:
        ...

    def validate(
        self,
        descriptor: Mapping[str, Any],
        invocation: Mapping[str, Any],
        context_pack: Mapping[str, Any],
        extension: Mapping[str, Any],
        state: StateView,
    ) -> tuple[ExecutionIssue, ...]:
        ...


class CapabilityContextExtensionStore(Protocol):
    """Immutable storage for one exact capability/Context Pack extension."""

    def store(
        self,
        capability_id: str,
        capability_version: str,
        function_id: str,
        context_pack_id: str,
        extension: Mapping[str, Any],
    ) -> str:
        ...

    def load(
        self,
        capability_id: str,
        capability_version: str,
        function_id: str,
        context_pack_id: str,
    ) -> Mapping[str, Any] | None:
        ...


class CapabilityContextExtensionRegistry:
    """Exact, fail-closed registry for capability Context extension validators."""

    def __init__(
        self,
        validators: Sequence[CapabilityContextExtensionValidator] = (),
    ) -> None:
        self._validators = tuple(validators)

    def validate(
        self,
        descriptor: Mapping[str, Any],
        invocation: Mapping[str, Any],
        context_pack: Mapping[str, Any],
        extension: Mapping[str, Any] | None,
        state: StateView,
        *,
        required: bool,
    ) -> None:
        capability = invocation["capability"]
        binding = (
            str(capability["capability_id"]),
            str(capability["capability_version"]),
            str(capability["function_id"]),
        )
        matches = tuple(
            item for item in self._validators if item.supports(*binding)
        )

        if extension is None:
            if required:
                if not matches:
                    raise CapabilityExecutionError(
                        ExecutionFailureCode.CONTEXT_INVALID,
                        "required capability Context extension has no registered validator",
                    )
                if len(matches) != 1:
                    raise CapabilityExecutionError(
                        ExecutionFailureCode.CONTEXT_INVALID,
                        "required capability Context extension validator binding is ambiguous",
                    )
                raise CapabilityExecutionError(
                    ExecutionFailureCode.CONTEXT_INVALID,
                    "required capability Context extension is missing",
                )
            return

        if not matches:
            raise CapabilityExecutionError(
                ExecutionFailureCode.CONTEXT_INVALID,
                "unknown capability Context extension has no registered validator",
            )
        if len(matches) != 1:
            raise CapabilityExecutionError(
                ExecutionFailureCode.CONTEXT_INVALID,
                "capability Context extension validator binding is ambiguous",
            )

        issues = matches[0].validate(
            descriptor,
            invocation,
            context_pack,
            extension,
            state,
        )
        if issues:
            first = issues[0]
            raise CapabilityExecutionError(
                first.code,
                "; ".join(issue.message for issue in issues),
                retryable=any(issue.retryable for issue in issues),
            )
