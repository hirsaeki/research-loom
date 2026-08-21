# P0 contract freeze

## Active implementation contracts inspected

1. `contracts/research_harness_v0.4.md`
2. `contracts/research_constitution.md`
3. `contracts/runtime_artifact_policy.yaml`
4. MISCO Profile pack: `maps/research_attention_and_initial_publication_map.md`
5. `contracts/publication_writer_rc1_change_request.md`
6. `contracts/publication_parallel_lane.md`
7. `contracts/publication_structure.schema.yaml`
8. `vendor/misco-publication-writer/` RC1.1 core, references, examples, and tests
9. `contracts/capabilities/desktop-research/desktop_research_contract.md`
10. `contracts/capabilities/desktop-research/source_policy.yaml`
11. `contracts/capabilities/desktop-research/evidence_capture.schema.yaml`
12. `contracts/capabilities/desktop-research/evidence_capture_v03.schema.yaml`
13. `contracts/capabilities/desktop-research/coverage_stopping.schema.yaml`
14. `contracts/capabilities/desktop-research/research_handoff.schema.yaml`
15. `contracts/capabilities/desktop-research/research_handoff_v03.schema.yaml`
16. `contracts/capabilities/desktop-research/provenance_audit_contract.md`
17. `contracts/capabilities/work-conversation/conversation_contract.md`
18. `contracts/capabilities/work-conversation/action_schema.yaml`
19. `contracts/capabilities/harness-recovery/recovery_contract.md`
20. `contracts/capabilities/harness-recovery/recovery_schema.yaml`
21. MISCO Profile pack: `maps/research_attention_and_initial_publication_map.md`
22. MISCO Profile pack: `project_feedback/virtual_run_feedback_v0.1.md`
23. `WORK_RESEARCH_COORDINATOR.md`
24. `AGENTS.md`
25. `contracts/capabilities/attention-intake/attention_distillation_contract.md`
26. `contracts/capabilities/workspace-lifecycle/workspace_lifecycle_contract.md`
27. `contracts/capabilities/workspace-lifecycle/distribution_contract.md`

The P1-P12 implementation review and completion evidence are recorded in
[`docs/proposal_review_2026-08-18.md`](proposal_review_2026-08-18.md). It is a
review record, not a runtime authority; the contracts above remain the source
of implementation semantics.

The vendor directory is an integration contract only. It is not loaded or
invoked as an active runtime skill.

## Contract conflict review

No implementation-blocking contradiction was found.

- The harness proposal, constitution, policy, and map are explicitly marked
  non-canonical candidates. This inventory records them as implementation
  inputs without claiming that they amend the canonical research design.
- RC1.1 already implements the correction request: Publication Eligibility,
  `INTEGRATED` as the normal Writer ceiling, Human-only `STABLE`/`FINAL`,
  Publication Feedback, `primary_exposition_map`, and historical-source
  no-import. Vendor static and contract regression checks pass.
- The project feedback describes historical lessons and includes an old G1
  style-reference statement. The later v0.4 policy and RC1.1 contract supersede
  that runtime implication: the G1 original is provenance-only and DENY; only a
  Human-approved clean publication source may enter Writer runtime.
- `ATTENTION_PUBLICATION_MAP` may shape coverage and publication routing but is
  never Evidence and cannot decide method or answer.
- Raw `ATTENTION_INTAKE_DROP` material is explicit, hash-frozen intake for the
  bounded `ATTENTION_DISTILLATION` event only. Work produces a candidate; the
  Human-owned `ATTENTION_MAP_ADOPTION` Decision alone can create a new active Map
  version.
- `rh archive` freezes source lifecycle only after bundle verification; `rh new`
  creates an independent mapless-capable target and does not mutate or copy the
  old runtime.
- The new Conversation and Recovery contracts do not conflict with the
  existing Desktop Research or Publication Writer boundaries. They add an
  interface and append-only compensation layer; they do not add a Work API,
  research algorithm, direct head rewind, or Publication Writer runtime.

## Deliberate non-blocking implementation decisions

- Missing optional capability flags on some policy roles are normalized to
  `false`; explicit policy values remain authoritative.
- `RETRIEVE` means a pointer is available for an explicit retrieval operation;
  it does not copy the artifact into the initial Context Pack.
- Archive/provenance acceptance scenarios use isolated test fixtures. P0 did
  not inspect repository archive/provenance artifacts.
- Pydantic v2 is used for strict versioned models; PyYAML is used only to load
  explicit policy and registry manifests. `argparse` avoids another CLI
  dependency.

## Artifact classification audit

| Supplied path | Role | Authority | Lane | Runtime treatment |
| --- | --- | --- | --- | --- |
| `AGENTS.md` | IMPLEMENTATION_CONTRACT | repository instruction | IMPLEMENTATION | implementation-only |
| `docs/work_chat_recovery_scope.md` | IMPLEMENTATION_SCOPE | durable current increment scope | IMPLEMENTATION | scope and invariant reference |
| `contracts/research_harness_v0.4.md` | ACTIVE_CONTRACT | contract candidate | CONTROL_PLANE | policy-resolved |
| `contracts/research_constitution.md` | ACTIVE_CONTRACT | contract candidate | RESEARCH | policy-resolved; not Evidence |
| `contracts/runtime_artifact_policy.yaml` | ACTIVE_CONTRACT | policy authority | CONTROL_PLANE | policy source |
| MISCO Profile pack: `maps/research_attention_and_initial_publication_map.md` | ATTENTION_PUBLICATION_MAP | guidance candidate | CONTROL_PLANE | profile input; planning only; not Evidence |
| `contracts/publication_writer_rc1_change_request.md` | ACTIVE_CONTRACT | interface change contract | PUBLICATION | implementation/interface only |
| `contracts/publication_parallel_lane.md` | ACTIVE_CONTRACT | parallel Publication contract | PUBLICATION | implementation/interface only |
| `contracts/publication_structure.schema.yaml` | ACTIVE_CONTRACT | Publication Structure schema | PUBLICATION | schema validation |
| `vendor/misco-publication-writer/**` | PUBLICATION_WRITER_INTERFACE | RC1.1 integration contract | IMPLEMENTATION | never runtime-discovered |
| MISCO Profile pack: `project_feedback/virtual_run_feedback_v0.1.md` | PROJECT_KNOWLEDGE | non-canonical guidance | IMPLEMENTATION | profile input; not Research Evidence |
| `contracts/capabilities/work-conversation/**` | ACTIVE_CONTRACT | typed interface contract | CONTROL_PLANE | typed actions only; chat prose denied |
| `contracts/capabilities/harness-recovery/**` | ACTIVE_CONTRACT | recovery contract | CONTROL_PLANE | append-only request, impact, decision, replay |
| `contracts/capabilities/attention-intake/attention_distillation_contract.md` | ACTIVE_CONTRACT | detachable Attention intake contract | CONTROL_PLANE | Work distillation only; no semantic adoption |
| `contracts/capabilities/workspace-lifecycle/workspace_lifecycle_contract.md` | ACTIVE_CONTRACT | archive/new lifecycle contract | CONTROL_PLANE | append-only archive and independent target |
| `contracts/capabilities/workspace-lifecycle/distribution_contract.md` | ACTIVE_CONTRACT | Harness/Profile distribution and upgrade contract | CONTROL_PLANE | manifest-bound, hash-checked, pending-boundary upgrade |

There is no generic reference role. Generated artifacts must be registered
before runtime access.
