# Writer reader-quality trial and evaluation preparation

For the current #467 acceptance scope, start with
[the final limited assessment](acceptance-decision.md). The historical trial
records below retain their original time-specific statements of unperformed
work. The #466 public document-review round trip is now available in
[its separate acceptance record](../writer-document-review/README.md).

Start with [the actual manuscript comparison](comparison.md). It records six
unaltered initial outputs, separate meaning/comprehension/reader-experience
observations, a targeted edit, and the remaining limits. This work starts
#465 and prepares #467 under the 2026-10-14 #463 handoff; it does not close the
Epic or establish an independent human reader effect.

- [Fixed fictional material](cases.json): diagnostic, unmeasured concept and opposing-direction comparison.
- [Generation conditions](generation-conditions.md) and [added trial procedures](revision-instructions.md): unchanged baseline Skill plus the exact additional instruction condition.
- [Rule correspondence](rule-correspondence.md): reuse of 127 IDs / eight groups, with residual overlaps for future removal comparisons.
- [Evaluation protocol](evaluation-protocol.md): separate axes, small blinded first-read assignment and three finite removal conditions. These reader/removal evaluations are prepared, not performed.
- [Handwritten negative examples](negative-examples.md): teaching mutations, separately labelled from actual Writer outputs.
- [Run manifest](run-manifest.json): verified bundle acquisition, frozen input/prose/transport/revision digests, public import/inspection and reuse results.
- [Exact public detached exports](detached-inputs.zip): the v5 `inputs/` directory only. No private store, database or real research is included. The manifest records archive and individual input SHA-256 values.

## Public operation driver

`scripts/writer_reader_quality_probe.py` is a bounded synthetic acceptance driver.
It seeds disposable **virtual SYNTHETIC_TEST_ONLY** fixtures using the existing
test fixture helper. After bootstrap, composition/package selection, export,
import and inspection use `LocalApplicationFacade`. It does not generate prose
or create production Human Decisions. Use the repository's existing uv
environment; no additional dependency installation is required.

Example for a new disposable run from the repository root:

```powershell
uv run --frozen --no-sync python scripts/writer_reader_quality_probe.py prepare --run-root D:\wsroot\scratch\writer-reader-quality-new-run
```

The first-generation Writer reads the selected exported input and pinned
resources, then saves prose-only JSON with `sections[{section_id,content}]`.
`wrap-response` packages those exact prose bytes separately; it marks every
delivered Profile rule `unevaluated`, rather than fabricating a semantic PASS.

```powershell
uv run --frozen --no-sync python scripts/writer_reader_quality_probe.py wrap-response --run-root D:\wsroot\scratch\writer-reader-quality-new-run --case-id synthetic-comparison-checklist-a8-6-b4-5-v1 --prose path\to\first-prose.json
uv run --frozen --no-sync python scripts/writer_reader_quality_probe.py import-response --run-root D:\wsroot\scratch\writer-reader-quality-new-run --case-id synthetic-comparison-checklist-a8-6-b4-5-v1 --response path\to\wrapped-response.json
uv run --frozen --no-sync python scripts/writer_reader_quality_probe.py inspect --run-root D:\wsroot\scratch\writer-reader-quality-new-run --case-id synthetic-comparison-checklist-a8-6-b4-5-v1 --revision-id EXACT_RECEIPT_REVISION_ID
```

For a later complete or partial revision, pass the exact public current
`--base-revision-id` to the wrapper. A partial response contains only changed
sections; the service reuses the rest. `replay` takes the exact preserved
response file and records the public verified-reuse result. Import/inspect
receipts are saved separately and never establish meaning, reader quality or
publication approval. Read IDs from receipts rather than transcribing them.

The original run uses the unchanged Skill from base commit
`861367bebd07f10f38f1d743bac00cb0e2a91bf8`; later Skill changes in this PR are
review proposals informed by that trial. Do not describe a fresh run against a
later Skill as the original baseline. Fixture IDs/time stamps may change on a
new prepare run; the archive preserves the exact original generation material.
