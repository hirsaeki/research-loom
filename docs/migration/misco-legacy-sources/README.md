# Archived MISCO legacy sources

Byte-identical copies of the legacy files that the frozen MISCO Profile migration
ledger (`docs/migration/misco-profile-migration-ledger/`) pins by sha256 and size.
Each copy keeps its original repository path under this directory, so
`research-profile/maps/...` is kept at
`docs/migration/misco-legacy-sources/research-profile/maps/...`.

The copies were made by #499 so that `research-profile/` and `research-harness/`
can be removed (#500) without losing the evidence the ledger records. Never edit
these files: the ledger, `tests/contracts/test_misco_profile_migration_ledger.py`
and the Project Config pin of `REF-MISCO-ATTENTION-MAP` check their exact bytes.

- `research-profile/publication/authority/MISCO_Publication_Clean_Source_Pack_v1.0.2_HUMAN_APPROVED/`:
  the Human-approved MISCO Publication source pack (Layers A–C, MANIFEST, validation records).
- `research-profile/maps/research_attention_and_initial_publication_map.md`: the attention map
  that `projects/misco-ai-2026/project-config.json` pins as `REF-MISCO-ATTENTION-MAP`.
  The config keeps its historical `research-profile/...` locator, so its configuration digest
  is unchanged.
- `research-profile/profile.manifest.json`, `research-profile/project_feedback/virtual_run_feedback_v0.1.md`:
  legacy manifest and project knowledge recorded as validation-only provenance.
- `research-harness/{contracts,src/misco_harness}/...`: the three harness files the ledger records
  as legacy consumers.
