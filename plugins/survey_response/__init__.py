"""Shared provider-neutral Survey response normalization and canonical contracts."""

from .contracts import (
    CANONICAL_RESPONSE_SCHEMA_PATH,
    DATASET_SCHEMA_PATH,
    RAW_SCHEMA_PATH,
    dataset_content_digest,
    registry_digest,
    validate_canonical_response,
    validate_dataset,
)
from .normalization import append_rejection_issue, normalize_response, virtual_record_to_raw

__all__ = [
    "CANONICAL_RESPONSE_SCHEMA_PATH",
    "DATASET_SCHEMA_PATH",
    "RAW_SCHEMA_PATH",
    "append_rejection_issue",
    "dataset_content_digest",
    "normalize_response",
    "registry_digest",
    "validate_canonical_response",
    "validate_dataset",
    "virtual_record_to_raw",
]
