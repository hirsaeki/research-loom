"""SQLite schemas of the optional workspace stores.

The stores create their tables from these definitions and
``plugins.local_durable_store`` validates existing databases against them,
so both import them from here instead of from each other.
"""

from __future__ import annotations

ATTENTION_STORE_SCHEMA_VERSION = "0.1.0"
ATTENTION_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS attention_store_meta (
    schema_version TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS attention_maps (
    map_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    map_digest TEXT NOT NULL,
    document_json TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS attention_maps_digest_idx
    ON attention_maps(map_digest);
CREATE TABLE IF NOT EXISTS attention_activation_events (
    activation_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    map_id TEXT NOT NULL,
    map_digest TEXT NOT NULL,
    activated_at TEXT NOT NULL,
    event_digest TEXT NOT NULL,
    document_json TEXT NOT NULL,
    FOREIGN KEY(map_id) REFERENCES attention_maps(map_id)
);
CREATE TABLE IF NOT EXISTS active_attention_map (
    project_id TEXT PRIMARY KEY,
    map_id TEXT NOT NULL,
    map_digest TEXT NOT NULL,
    activation_id TEXT NOT NULL,
    FOREIGN KEY(map_id) REFERENCES attention_maps(map_id),
    FOREIGN KEY(activation_id) REFERENCES attention_activation_events(activation_id)
);
"""

EXHIBIT_STORE_SCHEMA_VERSION = "0.1.0"
EXHIBIT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS exhibit_store_meta (
    schema_version TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS research_exhibits (
    exhibit_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    document_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS research_exhibits_project_idx
    ON research_exhibits(project_id, captured_at, exhibit_id);
CREATE TABLE IF NOT EXISTS research_exhibit_rqs (
    exhibit_id TEXT NOT NULL,
    rq_id TEXT NOT NULL,
    PRIMARY KEY(exhibit_id, rq_id),
    FOREIGN KEY(exhibit_id) REFERENCES research_exhibits(exhibit_id)
);
CREATE INDEX IF NOT EXISTS research_exhibit_rq_idx
    ON research_exhibit_rqs(rq_id, exhibit_id);
CREATE TABLE IF NOT EXISTS research_exhibit_metadata (
    exhibit_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    FOREIGN KEY(exhibit_id) REFERENCES research_exhibits(exhibit_id)
);
CREATE INDEX IF NOT EXISTS research_exhibit_metadata_project_idx
    ON research_exhibit_metadata(project_id, captured_at, exhibit_id);
"""

SURVEY_STORE_SCHEMA_VERSION = "0.1.0"
SURVEY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS survey_store_meta (
    schema_version TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS survey_designs (
    project_id TEXT NOT NULL,
    survey_design_id TEXT NOT NULL,
    version TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    document_json TEXT NOT NULL,
    PRIMARY KEY(project_id, survey_design_id, version)
);
CREATE TABLE IF NOT EXISTS survey_instruments (
    project_id TEXT NOT NULL,
    questionnaire_id TEXT NOT NULL,
    version TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    document_json TEXT NOT NULL,
    PRIMARY KEY(project_id, questionnaire_id, version)
);
"""

SURVEY_RESPONSE_STORE_SCHEMA_VERSION = "0.1.0"
SURVEY_RESPONSE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS survey_response_store_meta (
    schema_version TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS survey_responses (
    project_id TEXT NOT NULL,
    response_id TEXT NOT NULL,
    identity_namespace TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    instrument_version TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    response_origin TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    document_json TEXT NOT NULL,
    raw_input_json TEXT NOT NULL,
    PRIMARY KEY(project_id, identity_namespace, response_id)
);
CREATE TABLE IF NOT EXISTS survey_response_datasets (
    project_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    instrument_version TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    response_origin TEXT NOT NULL,
    created_at TEXT NOT NULL,
    summary_digest TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    document_json TEXT NOT NULL,
    PRIMARY KEY(project_id, dataset_id)
);
CREATE TABLE IF NOT EXISTS survey_response_dataset_entries (
    project_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    entry_index INTEGER NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY(project_id, dataset_id, entry_index)
);
CREATE TABLE IF NOT EXISTS survey_response_dataset_entry_counts (
    project_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    entry_count INTEGER NOT NULL DEFAULT 0,
    accepted_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(project_id, dataset_id)
);
CREATE TRIGGER IF NOT EXISTS survey_response_dataset_count_init
AFTER INSERT ON survey_response_datasets
BEGIN
    INSERT OR IGNORE INTO survey_response_dataset_entry_counts(
        project_id,dataset_id,entry_count,accepted_count
    ) VALUES (NEW.project_id,NEW.dataset_id,0,0);
END;
CREATE TRIGGER IF NOT EXISTS survey_response_dataset_count_insert
AFTER INSERT ON survey_response_dataset_entries
BEGIN
    INSERT INTO survey_response_dataset_entry_counts(
        project_id,dataset_id,entry_count,accepted_count
    ) VALUES (
        NEW.project_id,
        NEW.dataset_id,
        1,
        CASE WHEN NEW.kind='accepted_response' THEN 1 ELSE 0 END
    )
    ON CONFLICT(project_id,dataset_id) DO UPDATE SET
        entry_count=entry_count+1,
        accepted_count=accepted_count+
            CASE WHEN NEW.kind='accepted_response' THEN 1 ELSE 0 END;
END;
CREATE TRIGGER IF NOT EXISTS survey_response_dataset_count_delete
AFTER DELETE ON survey_response_dataset_entries
BEGIN
    UPDATE survey_response_dataset_entry_counts
    SET entry_count=entry_count-1,
        accepted_count=accepted_count-
            CASE WHEN OLD.kind='accepted_response' THEN 1 ELSE 0 END
    WHERE project_id=OLD.project_id AND dataset_id=OLD.dataset_id;
END;
CREATE TRIGGER IF NOT EXISTS survey_response_dataset_count_kind_update
AFTER UPDATE OF kind ON survey_response_dataset_entries
BEGIN
    UPDATE survey_response_dataset_entry_counts
    SET accepted_count=accepted_count
        - CASE WHEN OLD.kind='accepted_response' THEN 1 ELSE 0 END
        + CASE WHEN NEW.kind='accepted_response' THEN 1 ELSE 0 END
    WHERE project_id=NEW.project_id AND dataset_id=NEW.dataset_id;
END;
CREATE INDEX IF NOT EXISTS survey_response_dataset_entries_page
ON survey_response_dataset_entries(project_id, dataset_id, entry_index);
"""

SURVEY_ANALYSIS_STORE_SCHEMA_VERSION = "0.1.0"
SURVEY_ANALYSIS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS survey_analysis_store_meta (
    schema_version TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS survey_analysis_specs (
    project_id TEXT NOT NULL,
    analysis_spec_id TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    dataset_digest TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    instrument_version TEXT NOT NULL,
    instrument_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    document_json TEXT NOT NULL,
    PRIMARY KEY(project_id, analysis_spec_id)
);
CREATE TABLE IF NOT EXISTS survey_aggregate_results (
    project_id TEXT NOT NULL,
    aggregate_result_id TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    analysis_spec_id TEXT NOT NULL,
    analysis_spec_digest TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    dataset_digest TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    instrument_version TEXT NOT NULL,
    instrument_digest TEXT NOT NULL,
    response_origin TEXT NOT NULL,
    epistemic_status TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    document_json TEXT NOT NULL,
    PRIMARY KEY(project_id, aggregate_result_id)
);
CREATE INDEX IF NOT EXISTS survey_aggregate_results_by_spec
ON survey_aggregate_results(project_id, analysis_spec_id, dataset_id);
"""

DELPHI_SCHEMA_VERSION = "0.1.0"
DELPHI_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS delphi_store_meta (
    schema_version TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS delphi_documents (
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    identity TEXT NOT NULL,
    version TEXT NOT NULL,
    panel_id TEXT,
    round_sequence INTEGER,
    content_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    document_json TEXT NOT NULL,
    PRIMARY KEY(project_id, kind, identity, version)
);
CREATE INDEX IF NOT EXISTS idx_delphi_panel_round
ON delphi_documents(project_id, panel_id, round_sequence, kind);
"""


# Project Input records its version in this meta row (ADR 0001). It also keeps
# PRAGMA user_version at 2, the value older releases check.
PROJECT_INPUT_STORE_SCHEMA_VERSION = "0.2.0"
PROJECT_INPUT_META_SQL = """
CREATE TABLE IF NOT EXISTS project_input_store_meta (
    schema_version TEXT PRIMARY KEY
)
"""


def project_inputs_table_sql(table: str = "project_inputs") -> str:
    return f"""
            CREATE TABLE {table}(
                input_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                role TEXT NOT NULL,
                media_type TEXT NOT NULL,
                byte_length INTEGER NOT NULL,
                content_digest TEXT NOT NULL,
                source_path TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                registered_at TEXT NOT NULL,
                lineage_ref TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                snapshot_digest TEXT NOT NULL,
                UNIQUE(project_id, role, content_digest, lineage_ref, snapshot_id, snapshot_digest)
            )
        """
