# Research Package acceptance evidence (Issue #77)

Baseline: `6df92f9d23de843bce3934c5a98db68c871b8c91` (`main`, PR #104). This change reuses authoritative Snapshot reads, immutable Project Input reads, verified Desktop Research material reads, canonical completed Handoff reads, and Research Exhibit reads. It does not depend on the #76 refactor or closed PR #86 and does not implement #80/#78/#79/Publication.

The connected acceptance test is `tests/runtime/test_research_package_acceptance.py`; it creates the research/source/Exhibit inputs through public Facade paths and never injects a finished package into storage.

| ID | Evidence |
|---|---|
| RP1 | Build one RQ package with verified source text, locator/provenance, exact Exhibit, resolved Narrative semantics and unresolved Gap; remove the original intake directory; export and verify detached content without Workspace access. |
| RP2 | REAL in-progress research with no adopted Finding still builds; canonical Run candidates remain candidate-only and no authority is promoted. |
| RP3 | Advancing Research HEAD and removing intake files after build does not change the immutable package or historical source Run; re-export still verifies. |
| RP4 | Legitimate Gap remains packageable while unknown IDs, pin contradictions, foreign project/lineage bindings and byte tamper fail closed. |
| RP5 | A production Survey Virtual Runner Run remains `SYNTHETIC_TEST_ONLY`, preview-only, unfrozen and non-release while preserving its authoritative REAL Snapshot pin. REAL/VIRTUAL mixing is rejected and preview/release authority is not forged. |
| RP6 | Bounds fail explicitly, existing export target is preserved, and injected write failure leaves no successful partial output. |

## Limited ablation

A1 removes resolved bodies/attachments from the same package into the legacy reference-only shape. The object may remain valid under the old contract but no longer provides the exact detached material required by RP1, demonstrating why body resolution/bundling remains.

A2 mutates inline saved RQ content. Normal detached verification rejects the package digest mismatch. A test-only call omitting only package-document digest verification allows the same mutation through the remaining schema/attachment/projection checks, demonstrating why the package-level digest remains.

## Verification

Sandbox: changed Python files compile and `git diff --check` passes. The Sandbox fixed environment lacks the `rfc8785` dependency and cannot fetch missing wheels under its network/DNS restriction, so authoritative dependency-complete Linux/Windows execution is delegated to PR CI. CI and Kody responses must be checked before completion. Merge remains separate.
