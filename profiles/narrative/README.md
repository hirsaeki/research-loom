# Canonical Narrative Profiles

Narrative Profiles define reusable **argument and semantic composition** above authoritative Research State. The canonical vocabulary is in `../contracts/narrative-semantics.yaml` and its catalog schema is `../contracts/narrative-semantics.schema.json`.

Narrative stages form a minimum semantic dependency graph rather than a literal chapter tree. `consumes` and `requires` refer to authoritative research inputs; `produces` is limited to reader-facing Narrative products and never creates or revises Core research objects.

Literal headings, chapter numbers, provisional outlines, and primary/publication locations are Writer/Project projection hints rather than canonical Narrative semantics. Project-specific Research Attention belongs to Project Config.

The generic fixture under `../fixtures/narrative/` is synthetic. It demonstrates partial-order composition, preservation of counter-findings/qualifiers/limitations, and read-only connections to Argument, Finding, Contribution, and Recommendation without encoding MISCO or any concrete report structure.

## Production MISCO Writer delivery

`misco/profile.json` is the production migration carrier for Human-approved MISCO Writer/Narrative clean rules. Version `1.1.0` also carries the normalized UTF-8 content of the eight approved Layer A source documents referenced by its 127 Writer runtime items, so a detached host can review the real rule text without reading the legacy tree. `WRITER_RULES` remains the rule inventory; `WRITER_SOURCE_DOCUMENTS` is source text, not a second rule identity set.

The Profile instantiates only the minimum semantic stage/dependency/purpose/preservation definitions already required by the canonical Research Package boundary; it does not import literal chapters, project Attention, research methods, or synthetic fixture defaults. Synthetic few-shot material and Layer B/C audit/review material remain excluded from runtime delivery. Section Writer input projects the exact Writer Profile pins, both verified resources, and a review plan covering all delivered rule IDs by responsibility class. An import that declares a Profile-rule violation must route the exact violated IDs through section-targeted Writing Feedback; import success itself is not an editorial PASS. Research validity, causal support, adoption, and authoritative-state mutation remain upstream Research/Human responsibilities.
