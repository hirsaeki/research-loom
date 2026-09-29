# Profiles

Declarative, composable policy separated by concern:

- `research/` — methodology and research-quality rules
- `organization/` — organization/domain constraints and terminology
- `narrative/` — argument/semantic composition plus Writer-facing rule delivery
- `publication/` — output, citation, template, rendering, and release rules

The canonical contracts live under `contracts/`:

- `profile-manifest.schema.json` — common Profile envelope, versioning, Core compatibility, `extends`, `requires`, constraints, invariant strengthenings, and resource declarations
- `composition-semantics.yaml` — deterministic composition and hard-conflict semantics
- `effective-profile-set.schema.json` — resolved `effective_profiles`, `effective_constraints`, optional verified `effective_resources`, and provenance
- `research-quality-policy.*` / `narrative-semantics.*` — closed canonical vocabularies for those Profile namespaces
- `fixtures/` — **synthetic** contract fixtures only; their concrete values are not production defaults

## Production MISCO Profiles

Issue #332 introduced only the production Profiles justified by the #331 migration ledger; Issue #334 completes detached Writer rule-text/review delivery without adding invented Research/Organization defaults:

- `narrative/misco/profile.json` (`misco.writer@1.1.0`) — instantiates the minimal canonical Narrative definitions required by the Research Package boundary and delivers the Human-approved clean Writer/Narrative rule inventory plus the eight approved Layer A source documents needed by a detached Writer host.
- `publication/misco/profile.json` (`misco.publication@1.2.0`) — delivers the Human-approved clean Publication rule inventory, six approved Layer A source documents, the SHA-256-pinned current formal-spec application values supplied on 2026-09-29, and the Human-approved full-URL display policy; it `requires` `misco.writer>=1.1.0 <2.0.0`. Project/material-specific permissions, editorial review, and conditional outer-structure metadata remain explicit runtime inputs.

There is deliberately no empty MISCO Research or Organization Profile. The #331 inventory found no reusable MISCO Research/Organization values with authority independent of project-specific Attention/feedback, and the synthetic Research fixtures explicitly are not defaults. Concrete Research/Organization policy must therefore be added only when an authoritative reusable value exists; project RQ, method choices, provisional chapter placement, and runtime state do not belong here.

The legacy `research-profile/` tree remains migration/reference material. Production resolution must not read it to recover rule text.

## Resource delivery

A manifest resource is resolved relative to its manifest, must remain inside canonical `profiles/`, must carry a SHA-256 pin for production resolution, and must be UTF-8 text. The production resolver verifies the pin and copies the normalized text plus provenance into `effective_resources` in the Effective Profile Set (EPS). This makes Workspace history and detached EPS inputs self-contained. Research Package 0.2.0 also copies the selected `effective_resources` beside its Profile pins, so detached Writer/Publication work does not need the current checkout or legacy tree to recover selected rule text.

Layer B audit material, Layer C Human Review material, and synthetic few-shot examples are not production resources. For `misco.writer@1.1.0`, `WRITER_RULES` is the rule inventory and `WRITER_SOURCE_DOCUMENTS` carries the normalized UTF-8 bytes of the eight approved Layer A documents actually referenced by those runtime rules. For `misco.publication@1.2.0`, `PUBLICATION_FORMAL_SPEC` and `PUBLICATION_URL_DISPLAY` carry the approved production application policy in addition to the clean rule/source-document resources; the formal binary originals remain external and are identified by exact digests in the resource. Detached inputs project these resources and exact Profile pins; a host must not recover missing policy from `research-profile/`, historical examples, or the network.

## Composition

`extends` is same-profile-type inheritance. Cross-type dependencies use `requires`; `requires` never creates override precedence. Cross-category last-write-wins is forbidden: ambiguous collisions are errors.

Core non-overridable invariants remain the semantic floor. Profiles may preserve or explicitly strengthen them but may not disable, weaken, reinterpret, or replace them.

## Minimal resolution example

For an existing Workspace, a profile-generation request can select the production Publication Profile (which pulls the Writer/Narrative Profile transitively):

```json
{
  "profile_manifest_files": [
    "profiles/narrative/misco/profile.json",
    "profiles/publication/misco/profile.json"
  ],
  "request_replacements": [
    {
      "from": {"profile_id":"OLD_PUBLICATION","profile_type":"publication","version":"1.0.0"},
      "to": {"profile_id":"misco.publication","profile_type":"publication","version":"1.2.0"}
    }
  ]
}
```

Then use the normal production path:

```bash
./research-loom profile resolve --workspace WORKSPACE --output OUT --json request.json
```

The resulting `effective-profile-set.json` exposes the selected profile/version, manifest pins, effective constraints, verified rule resources with bodies, and their provenance. Consumer-specific evaluation remains the responsibility of Research/Writer/Publication application layers; the presence of a resource in the EPS is not by itself an “applied” or “passed” result.
