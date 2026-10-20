"""Production local execution trace, artifact, resource, and auxiliary stores."""

from .atomic import LocalOperationalTraceStore
from .context_extensions import LocalCapabilityContextExtensionStore
from .diagnosed_artifact_read import DiagnosedArtifactReadMixin
from .inspection import artifact_metadata_for, diagnostics_for, latest_diagnostic_for
from .intake import bind_controlled_import_root, read_controlled_file
from .material_inventory import external_capture_artifact_metadata_for_project
from .read_only import ReadOnlyLocalExecutionStore, open_read_only_execution_store
from .recovery import result_extensions_for_run
from .retention import LocalExecutionStore as _RetentionLocalExecutionStore
from .status import (
    child_runs_for_parent,
    latest_child_attempt_for_parent,
    pending_runs_for_project,
    recent_runs_for_project,
)
from .store_model import (
    LocalExecutionStoreConfig,
    LocalExecutionStoreError,
    LocalExecutionStoreIntegrityError,
    RegisteredResource,
    StoreIntegrityDiagnostic,
)


class LocalExecutionStore(DiagnosedArtifactReadMixin, _RetentionLocalExecutionStore):
    """Production store with single-read and bounded verified artifact reads."""


def canonical_handoff_for(store: LocalExecutionStore, handoff_id: str):
    """Read one persisted canonical Handoff through the store document verifier."""
    return store._load_document("handoff", str(handoff_id))


__all__ = [
    "LocalCapabilityContextExtensionStore",
    "LocalExecutionStore",
    "LocalExecutionStoreConfig",
    "LocalExecutionStoreError",
    "LocalExecutionStoreIntegrityError",
    "LocalOperationalTraceStore",
    "ReadOnlyLocalExecutionStore",
    "RegisteredResource",
    "StoreIntegrityDiagnostic",
    "artifact_metadata_for",
    "bind_controlled_import_root",
    "canonical_handoff_for",
    "child_runs_for_parent",
    "diagnostics_for",
    "latest_diagnostic_for",
    "latest_child_attempt_for_parent",
    "external_capture_artifact_metadata_for_project",
    "open_read_only_execution_store",
    "pending_runs_for_project",
    "read_controlled_file",
    "result_extensions_for_run",
    "recent_runs_for_project",
]
