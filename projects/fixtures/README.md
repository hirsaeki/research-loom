# Project Config fixtures

These fixtures are synthetic executable examples for the canonical Project Config contract.

- `valid/generic-project-config.json` exercises project identity/scope, RQ references and seeds, direct Profile requests, Communication Brief, Research Attention, project-local guards, resource/capability hints, provenance, and deterministic digest.
- `semantic/cases.json` lists fixture-only mutations and expected semantic error codes.

The generic fixture intentionally requests only Narrative and Publication Profiles directly while the existing PR 4 Effective Profile Set also contains transitive Research and Organization Profiles. This proves that Project Config records direct requests rather than resolver output.

No concrete MISCO Project Config, chapter map, method requirement, organization rule, publication format, or runtime capability behavior is canonicalized here.
