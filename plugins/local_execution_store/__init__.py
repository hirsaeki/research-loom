"""Production local execution trace, artifact, resource, and auxiliary stores."""

from .retention import LocalExecutionStore as _RetentionLocalExecutionStore
from .verified_artifact_read import VerifiedArtifactReadMixin
from .atomic import LocalOperationalTraceStore
from .context_extensions import LocalCapabilityContextExtensionStore
from .inspection import artifact_metadata_for, diagnostics_for
from .intake import bind_controlled_import_root, read_controlled_file
from .material_inventory import external_capture_artifact_metadata_for_project
from .status import pending_runs_for_project, recent_runs_for_project
from .store import (
    LocalExecutionStoreConfig,
    LocalExecutionStoreError,
    LocalExecutionStoreIntegrityError,
    RegisteredResource,
    StoreIntegrityDiagnostic,
)


class LocalExecutionStore(VerifiedArtifactReadMixin, _RetentionLocalExecutionStore):
    """Production store with single-read and bounded verified artifact reads."""


__all__ = [
    "LocalCapabilityContextExtensionStore",
    "LocalExecutionStore",
    "LocalExecutionStoreConfig",
    "LocalExecutionStoreError",
    "LocalExecutionStoreIntegrityError",
    "LocalOperationalTraceStore",
    "RegisteredResource",
    "StoreIntegrityDiagnostic",
    "artifact_metadata_for",
    "bind_controlled_import_root",
    "diagnostics_for",
    "external_capture_artifact_metadata_for_project",
    "pending_runs_for_project",
    "read_controlled_file",
    "recent_runs_for_project",
]
