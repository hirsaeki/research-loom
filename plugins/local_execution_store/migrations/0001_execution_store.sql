CREATE TABLE runs(
    run_id TEXT PRIMARY KEY,
    invocation_id TEXT NOT NULL,
    invocation_digest TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    capability_version TEXT NOT NULL,
    descriptor_digest TEXT NOT NULL,
    implementation_id TEXT NOT NULL,
    implementation_version TEXT NOT NULL,
    function_id TEXT NOT NULL,
    execution_mode TEXT NOT NULL,
    context_pack_id TEXT NOT NULL,
    context_pack_digest TEXT NOT NULL,
    project_ref TEXT NOT NULL,
    lineage_ref TEXT NOT NULL,
    snapshot_ref TEXT NOT NULL,
    snapshot_digest TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK(attempt > 0),
    parent_run_id TEXT,
    status TEXT NOT NULL,
    prepared_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    handoff_ref TEXT,
    handoff_digest TEXT,
    failure_json TEXT,
    provenance_json TEXT NOT NULL
);

CREATE INDEX runs_project_pending_idx
    ON runs(project_ref, status, prepared_at, run_id);

CREATE TABLE run_events(
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    from_status TEXT,
    to_status TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY(run_id, sequence)
);

CREATE TABLE execution_documents(
    document_type TEXT NOT NULL,
    identity TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    run_id TEXT,
    PRIMARY KEY(document_type, identity)
);

CREATE TABLE diagnostics(
    diagnostic_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE execution_artifacts(
    artifact_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    role TEXT NOT NULL,
    media_type TEXT NOT NULL,
    size INTEGER NOT NULL CHECK(size >= 0),
    digest TEXT NOT NULL,
    storage_locator TEXT NOT NULL,
    execution_mode TEXT NOT NULL,
    provenance_json TEXT NOT NULL
);

CREATE INDEX execution_artifacts_run_idx
    ON execution_artifacts(run_id);

CREATE TABLE input_resources(
    reference_id TEXT PRIMARY KEY,
    media_type TEXT,
    size INTEGER NOT NULL CHECK(size >= 0),
    digest TEXT NOT NULL,
    storage_locator TEXT NOT NULL,
    provenance_json TEXT NOT NULL
);
