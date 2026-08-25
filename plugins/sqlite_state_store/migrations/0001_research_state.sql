-- Canonical SQLite Research State persistence schema.
-- Physical storage only: Research semantics remain owned by core/runtime.

CREATE TABLE project_state (
    project_ref TEXT PRIMARY KEY,
    project_config_ref TEXT NOT NULL,
    project_config_digest TEXT NOT NULL,
    project_config_json TEXT NOT NULL,
    effective_profile_set_ref TEXT NOT NULL,
    effective_profile_set_digest TEXT NOT NULL,
    effective_constraints_json TEXT NOT NULL
);

CREATE TABLE object_revisions (
    kind TEXT NOT NULL,
    object_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    project_ref TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_commit_id TEXT,
    PRIMARY KEY (kind, object_id, revision),
    FOREIGN KEY (project_ref) REFERENCES project_state(project_ref),
    FOREIGN KEY (created_commit_id) REFERENCES commits(commit_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX object_revisions_project_kind_id
    ON object_revisions(project_ref, kind, object_id, revision);

CREATE TABLE snapshots (
    snapshot_ref TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    project_ref TEXT NOT NULL,
    mode TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    created_commit_id TEXT,
    FOREIGN KEY (project_ref) REFERENCES project_state(project_ref),
    FOREIGN KEY (created_commit_id) REFERENCES commits(commit_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE snapshot_members (
    snapshot_ref TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    member_kind TEXT NOT NULL,
    member_id TEXT NOT NULL,
    member_revision INTEGER NOT NULL CHECK (member_revision >= 0),
    member_content_digest TEXT NOT NULL,
    PRIMARY KEY (snapshot_ref, member_kind, member_id, member_revision),
    UNIQUE (snapshot_ref, ordinal),
    FOREIGN KEY (snapshot_ref) REFERENCES snapshots(snapshot_ref) ON DELETE RESTRICT,
    FOREIGN KEY (member_kind, member_id, member_revision)
        REFERENCES object_revisions(kind, object_id, revision)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX snapshot_members_lookup
    ON snapshot_members(member_kind, member_id, member_revision);

CREATE TABLE decisions (
    decision_ref TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    project_ref TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    created_commit_id TEXT,
    FOREIGN KEY (project_ref) REFERENCES project_state(project_ref),
    FOREIGN KEY (created_commit_id) REFERENCES commits(commit_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE lineages (
    lineage_id TEXT PRIMARY KEY,
    project_ref TEXT NOT NULL,
    lineage_kind TEXT NOT NULL,
    parent_lineage_ref TEXT,
    baseline_snapshot_ref TEXT,
    head_snapshot_ref TEXT NOT NULL,
    head_snapshot_digest TEXT NOT NULL,
    head_snapshot_revision INTEGER NOT NULL CHECK (head_snapshot_revision >= 0),
    execution_mode TEXT NOT NULL,
    status TEXT NOT NULL,
    project_config_ref TEXT,
    project_config_digest TEXT,
    effective_profile_set_ref TEXT,
    effective_profile_set_digest TEXT,
    created_commit_id TEXT,
    updated_commit_id TEXT,
    FOREIGN KEY (project_ref) REFERENCES project_state(project_ref),
    FOREIGN KEY (parent_lineage_ref) REFERENCES lineages(lineage_id)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (baseline_snapshot_ref) REFERENCES snapshots(snapshot_ref)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (head_snapshot_ref) REFERENCES snapshots(snapshot_ref)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (created_commit_id) REFERENCES commits(commit_id)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (updated_commit_id) REFERENCES commits(commit_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX lineages_project
    ON lineages(project_ref, lineage_id);

CREATE TABLE project_active_lineage (
    project_ref TEXT PRIMARY KEY,
    active_lineage_ref TEXT NOT NULL,
    updated_commit_id TEXT,
    FOREIGN KEY (project_ref) REFERENCES project_state(project_ref),
    FOREIGN KEY (active_lineage_ref) REFERENCES lineages(lineage_id)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (updated_commit_id) REFERENCES commits(commit_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE used_decisions (
    decision_ref TEXT PRIMARY KEY,
    consuming_transition_id TEXT,
    consuming_commit_id TEXT,
    FOREIGN KEY (decision_ref) REFERENCES decisions(decision_ref)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (consuming_commit_id) REFERENCES commits(commit_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE adoption_refs (
    adoption_ref TEXT PRIMARY KEY,
    project_ref TEXT NOT NULL,
    lineage_ref TEXT NOT NULL,
    created_commit_id TEXT,
    FOREIGN KEY (project_ref) REFERENCES project_state(project_ref),
    FOREIGN KEY (lineage_ref) REFERENCES lineages(lineage_id)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (created_commit_id) REFERENCES commits(commit_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE non_reusable_refs (
    ref TEXT PRIMARY KEY,
    project_ref TEXT NOT NULL,
    FOREIGN KEY (project_ref) REFERENCES project_state(project_ref)
);

CREATE TABLE source_modes (
    source_ref TEXT PRIMARY KEY,
    project_ref TEXT NOT NULL,
    source_mode TEXT NOT NULL,
    FOREIGN KEY (project_ref) REFERENCES project_state(project_ref)
);

CREATE TABLE audit_events (
    audit_ref TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    project_ref TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    commit_ref TEXT NOT NULL,
    FOREIGN KEY (project_ref) REFERENCES project_state(project_ref),
    FOREIGN KEY (commit_ref) REFERENCES commits(commit_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE commits (
    commit_id TEXT PRIMARY KEY,
    transition_id TEXT NOT NULL,
    project_ref TEXT NOT NULL,
    lineage_ref TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_digest TEXT NOT NULL,
    bundle_digest TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    prior_snapshot_ref TEXT NOT NULL,
    prior_snapshot_digest TEXT NOT NULL,
    new_snapshot_ref TEXT,
    new_snapshot_digest TEXT,
    committed_at TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    FOREIGN KEY (project_ref) REFERENCES project_state(project_ref),
    FOREIGN KEY (lineage_ref) REFERENCES lineages(lineage_id)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (prior_snapshot_ref) REFERENCES snapshots(snapshot_ref)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (new_snapshot_ref) REFERENCES snapshots(snapshot_ref)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX commits_project_lineage
    ON commits(project_ref, lineage_ref, commit_id);
