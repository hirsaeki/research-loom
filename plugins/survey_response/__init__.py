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


def append_rejection_issue(*args, **kwargs):
    from .normalization import append_rejection_issue as implementation

    return implementation(*args, **kwargs)


def normalize_response(*args, **kwargs):
    from .normalization import normalize_response as implementation

    return implementation(*args, **kwargs)


def virtual_record_to_raw(*args, **kwargs):
    from .normalization import virtual_record_to_raw as implementation

    return implementation(*args, **kwargs)


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
