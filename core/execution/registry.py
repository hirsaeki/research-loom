from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from .models import CapabilityExecutionError, ExecutionFailureCode
from .ports import CapabilityAdapter


class CapabilityRegistry:
    """Explicit deterministic registry for exact Capability runtime bindings."""

    def __init__(self) -> None:
        self._bindings: dict[
            tuple[str, str, str, str], list[CapabilityAdapter]
        ] = defaultdict(list)

    def register(
        self,
        adapter: CapabilityAdapter,
        descriptor: Mapping[str, Any],
    ) -> None:
        """Validate one adapter completely, then atomically publish its bindings."""
        if (
            adapter.capability_id != descriptor.get("capability_id")
            or adapter.capability_version != descriptor.get("capability_version")
        ):
            raise CapabilityExecutionError(
                ExecutionFailureCode.DESCRIPTOR_INVALID,
                "adapter capability identity/version does not match descriptor",
            )

        declared = {
            str(item.get("function_id")): tuple(
                str(mode) for mode in item.get("supported_execution_modes", ())
            )
            for item in descriptor.get("declared_functions", ())
        }
        pending: list[tuple[str, str, str, str]] = []
        for function_id in adapter.supported_functions:
            declared_modes = declared.get(function_id)
            if declared_modes is None:
                raise CapabilityExecutionError(
                    ExecutionFailureCode.DESCRIPTOR_INVALID,
                    f"adapter function {function_id!r} is not declared by descriptor",
                )
            for mode in adapter.supported_execution_modes:
                if mode not in declared_modes:
                    raise CapabilityExecutionError(
                        ExecutionFailureCode.DESCRIPTOR_INVALID,
                        f"adapter mode {mode!r} is not declared for function {function_id!r}",
                    )
                pending.append(
                    (
                        adapter.capability_id,
                        adapter.capability_version,
                        function_id,
                        mode,
                    )
                )

        for key in pending:
            self._bindings[key].append(adapter)
            self._bindings[key].sort(
                key=lambda item: (
                    item.implementation_id,
                    item.implementation_version,
                )
            )

    def resolve(
        self,
        capability_id: str,
        capability_version: str,
        function_id: str,
        execution_mode: str,
    ) -> CapabilityAdapter:
        """Resolve exactly one implementation; unknown and ambiguous both fail closed."""
        matches = tuple(
            self._bindings.get(
                (
                    capability_id,
                    capability_version,
                    function_id,
                    execution_mode,
                ),
                (),
            )
        )
        if not matches:
            raise CapabilityExecutionError(
                ExecutionFailureCode.IMPLEMENTATION_NOT_FOUND,
                "no registered implementation for "
                f"{capability_id}@{capability_version}:{function_id}/{execution_mode}",
            )
        if len(matches) != 1:
            identities = ", ".join(
                f"{item.implementation_id}@{item.implementation_version}"
                for item in matches
            )
            raise CapabilityExecutionError(
                ExecutionFailureCode.IMPLEMENTATION_AMBIGUOUS,
                "multiple registered implementations for one exact binding: "
                + identities,
            )
        return matches[0]
