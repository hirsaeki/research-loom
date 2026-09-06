# External material exact-content read and export

Captured Desktop Research material remains an immutable execution artifact. The public content surface adds no Source/Evidence registry and does not re-fetch, re-extract, normalize, adopt, or mutate Research State.

## Selection and identity

Use the existing material inventory first:

```bash
./research-loom external materials list --workspace "$WS" --json
```

Select one exact capture from `materials[].captures[]` using both its `run_id` and `capture_id`. The pair is required because one original-byte digest may appear in multiple Runs/captures with different UTF-8 renditions.

No command silently selects the newest or representative capture.

## Bounded UTF-8 viewing

```bash
./research-loom external materials show \
  --workspace "$WS" \
  --run-id RUN-... \
  --capture-id CAP-... \
  --max-text-bytes 65536 \
  --json
```

`show` verifies the persisted UTF-8 rendition bytes through the execution artifact store before returning content. It also validates project/Run/capture binding, the original/rendition pairing, exact locator, acquisition time, the selected rendition digest/size, the original artifact metadata, and original parent provenance. Original bytes are independently verified when `--kind original` is exported.

The result includes `text_rendition_view.truncated`, `displayed_bytes`, and `total_bytes`. A truncated view is never represented as the full rendition. The maximum display bound is 1 MiB.

`show` is valid for persisted captures on RUNNING or terminal Runs. Handoff success is not required. An attempt-only target has no capture body and therefore cannot be shown.

## Exact byte export

```bash
./research-loom external materials export \
  --workspace "$WS" \
  --run-id RUN-... \
  --capture-id CAP-... \
  --kind original \
  --output /new/path/source.bin \
  --json

./research-loom external materials export \
  --workspace "$WS" \
  --run-id RUN-... \
  --capture-id CAP-... \
  --kind rendition \
  --output /new/path/source.txt \
  --json
```

Export loads the selected persisted artifact through the existing verified artifact read path, including the managed `external-original://` retention locator for oversized originals, then writes the exact stored bytes. No newline, encoding, or content conversion is performed.

The output path must not already exist, its parent must already exist, and it may not be inside the workspace-managed `.research-loom` tree. A failed integrity check leaves no output file. Export does not overwrite existing user files.

## Integrity and authority boundary

The read path fails closed for unknown/cross-project Runs, unknown captures, incomplete or mismatched original/rendition pairs, missing blobs, size mismatches, and digest mismatches. It never falls back to the original intake file, network retrieval, OCR, or LLM regeneration.

`list`, `show`, and `export` do not alter the Research Snapshot, Run/Handoff state, attempts, captures, artifacts, Evidence verification, Finding adoption, or Publication Release. The only intended side effect is a newly created export file.

## Issue #91 acceptance and ablation

Focused acceptance:

```bash
uv run --frozen python -m unittest discover -s tests/runtime -p 'test_issue91_external_material_content.py' -v
```

The file maps the Issue #91 public scenarios as follows:

- C1: `test_c1_public_cli_round_trip_survives_source_removal_without_state_mutation`
- C2: `test_c2_large_original_exports_exact_bytes_and_show_marks_truncation`
- C3: `test_c3_explicit_capture_selects_version_and_cli_requires_capture_id`
- C4: `test_c4_same_size_corruption_missing_pair_wrong_pair_and_foreign_ids_fail_closed`
- C5: `test_c5_terminal_capture_remains_readable_but_attempt_only_has_no_content`
- C6: `test_c6_export_never_overwrites_or_writes_managed_state`

Ablation control is `test_ablation_digest_guard_is_the_control_for_same_size_corruption`. The control first demonstrates that same-size one-byte corruption is rejected. It then patches only the execution store's blob digest/size verifier for the same read boundary; the corrupted bytes become exportable and differ from the original. This isolates the digest verification used by the production content read instead of counting an unrelated fixture failure as an ablation result.

Full runtime CI parity remains:

```bash
uv run --frozen python -m unittest discover -s tests/runtime -p 'test_*.py' -v
```
