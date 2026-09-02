"""Shared origin-neutral descriptive Survey aggregation over canonical response Datasets."""

from .aggregation import (
    AGGREGATION_IMPLEMENTATION,
    aggregate_dataset,
    default_analysis_items,
    normalize_analysis_items,
)
from .contracts import (
    AGGREGATE_RESULT_SCHEMA_PATH,
    ANALYSIS_SPEC_SCHEMA_PATH,
    aggregate_result_content_digest,
    analysis_spec_content_digest,
    registry_digest,
    stable_identity,
    validate_aggregate_result,
    validate_analysis_spec,
)

__all__ = [
    "AGGREGATE_RESULT_SCHEMA_PATH",
    "ANALYSIS_SPEC_SCHEMA_PATH",
    "AGGREGATION_IMPLEMENTATION",
    "aggregate_dataset",
    "aggregate_result_content_digest",
    "analysis_spec_content_digest",
    "default_analysis_items",
    "normalize_analysis_items",
    "registry_digest",
    "stable_identity",
    "validate_aggregate_result",
    "validate_analysis_spec",
]
