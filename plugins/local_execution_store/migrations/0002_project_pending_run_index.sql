CREATE INDEX IF NOT EXISTS runs_project_pending_idx
    ON runs(project_ref, status, prepared_at, run_id);
