from __future__ import annotations

from collections import OrderedDict
from typing import Any, Mapping

from .models import ActionDefinition, ConversationRuntimeError
from .ports import CapabilityActionMaterializer, HarnessServiceHandler


class ActionRegistry:
    """Explicit fail-closed semantic action registry. Duplicate registration is an error."""

    def __init__(self) -> None:
        self._actions: OrderedDict[str, ActionDefinition] = OrderedDict()

    def register(self, definition: ActionDefinition) -> None:
        if definition.action_type in self._actions:
            raise ConversationRuntimeError(
                "CONV-ROUTE-001",
                f"action already registered: {definition.action_type}",
            )
        if definition.effect not in {"read_only", "state_changing"}:
            raise ConversationRuntimeError("CONV-ROUTE-001", "invalid action effect")
        if definition.route_kind not in {"harness_service", "capability_invocation"}:
            raise ConversationRuntimeError("CONV-ROUTE-001", "invalid action route")
        if definition.effect == "read_only" and definition.confirmation_required:
            raise ConversationRuntimeError(
                "CONV-READONLY-001", "read-only action cannot require confirmation"
            )
        self._actions[definition.action_type] = definition

    def get(self, action_type: str) -> ActionDefinition:
        try:
            return self._actions[action_type]
        except KeyError as exc:
            raise ConversationRuntimeError(
                "CONV-ROUTE-001", f"unknown action type: {action_type}"
            ) from exc

    def definitions(self) -> tuple[ActionDefinition, ...]:
        return tuple(self._actions.values())


class HarnessServiceRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, HarnessServiceHandler] = {}

    def register(self, service_id: str, handler: HarnessServiceHandler) -> None:
        if service_id in self._handlers:
            raise ConversationRuntimeError(
                "CONV-ROUTE-001", f"Harness service already registered: {service_id}"
            )
        self._handlers[service_id] = handler

    def resolve(self, service_id: str) -> HarnessServiceHandler:
        try:
            return self._handlers[service_id]
        except KeyError as exc:
            raise ConversationRuntimeError(
                "CONV-ROUTE-001", f"unknown Harness service: {service_id}"
            ) from exc


class CapabilityActionMaterializerRegistry:
    def __init__(self) -> None:
        self._items: dict[str, CapabilityActionMaterializer] = {}

    def register(self, materializer: CapabilityActionMaterializer) -> None:
        if materializer.materializer_id in self._items:
            raise ConversationRuntimeError(
                "CONV-ROUTE-001",
                f"capability materializer already registered: {materializer.materializer_id}",
            )
        self._items[materializer.materializer_id] = materializer

    def resolve(self, materializer_id: str) -> CapabilityActionMaterializer:
        try:
            return self._items[materializer_id]
        except KeyError as exc:
            raise ConversationRuntimeError(
                "CONV-ROUTE-001", f"unknown materializer: {materializer_id}"
            ) from exc


class CapabilityDescriptorRegistry:
    """Immutable descriptor registry used by proposal materialization, separate from runtime adapter lookup."""

    def __init__(self) -> None:
        self._descriptors: dict[tuple[str, str], Mapping[str, Any]] = {}

    def register(self, descriptor: Mapping[str, Any]) -> None:
        key = (str(descriptor["capability_id"]), str(descriptor["capability_version"]))
        if key in self._descriptors:
            raise ConversationRuntimeError(
                "CONV-ROUTE-001", f"descriptor already registered: {key[0]}@{key[1]}"
            )
        self._descriptors[key] = dict(descriptor)

    def resolve(self, capability_id: str, capability_version: str) -> Mapping[str, Any]:
        try:
            return self._descriptors[(capability_id, capability_version)]
        except KeyError as exc:
            raise ConversationRuntimeError(
                "CONV-ROUTE-001",
                f"unknown descriptor: {capability_id}@{capability_version}",
            ) from exc
