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

## Layout and versions

Every production manifest lives at `<profile_type>/<name>/<version>/profile.json`, with its resources in `resources/` beside it (#498). A version is immutable: a manifest pins each resource by a path relative to itself and a SHA-256, so versions never share resource files. Byte-identical copies between versions are allowed and listed in `tests/contracts/test_profile_layout.py`.

| Manifest | Profile | Selected by default |
| --- | --- | --- |
| `narrative/misco/1.1.0/profile.json` | `misco.writer@1.1.0` | yes, transitively by `misco.publication@1.3.0` in `projects/misco-ai-2026` |
| `narrative/misco/1.2.0/profile.json` | `misco.writer@1.2.0` | no; opt-in #464 classified Writer rules |
| `publication/misco/1.3.0/profile.json` | `misco.publication@1.3.0` | yes, requested by `projects/misco-ai-2026` |
| `publication/misco/1.4.0/profile.json` | `misco.publication@1.4.0` | no; opt-in #456 formal report conformance through profile generation |
| `research/misco-workspace-continuity/1.0.0/profile.json` | `misco.workspace-continuity.exact-locator@1.0.0` | no; migration only |

Moving the directories in #498 left every manifest byte-identical, so `manifest_sha256` pins and existing Workspaces are unaffected. A newly resolved EPS records the new paths in `effective_resources[].path`; an EPS that a Workspace already holds keeps its old paths and stays valid. Requests that name a manifest must use the new path:

| Before #498 | Now |
| --- | --- |
| `profiles/narrative/misco/profile.json` | `profiles/narrative/misco/1.1.0/profile.json` |
| `profiles/publication/misco/profile.json` | `profiles/publication/misco/1.3.0/profile.json` |
| `profiles/publication/misco-v1.4/profile.json` | `profiles/publication/misco/1.4.0/profile.json` |
| `profiles/research/misco-workspace-continuity/profile.json` | `profiles/research/misco-workspace-continuity/1.0.0/profile.json` |

A profile-generation target prepared before the move does not match a fresh resolution any more, and apply refuses it with `PROFILE-ADVANCE-PROVENANCE-001`. Prepare it again with the new manifest paths.

## Production MISCO Profiles

Issue #332 introduced only the production Profiles justified by the #331 migration ledger; Issue #334 completes detached Writer rule-text/review delivery without adding invented Research/Organization defaults:

- `narrative/misco/1.1.0/profile.json` (`misco.writer@1.1.0`) — instantiates the minimal canonical Narrative definitions required by the Research Package boundary and delivers the Human-approved clean Writer/Narrative rule inventory plus the eight approved Layer A source documents needed by a detached Writer host.
- `publication/misco/1.3.0/profile.json` (`misco.publication@1.3.0`) — delivers the Human-approved clean Publication rule inventory, six approved Layer A source documents, the SHA-256-pinned corrected formal-spec application authority supplied on 2026-09-30, and the Human-approved full-URL display policy; it `requires` `misco.writer>=1.1.0 <2.0.0`. Project/material-specific permissions, editorial review, and conditional outer-structure metadata remain explicit runtime inputs.

There is deliberately no empty MISCO Research or Organization Profile. The #331 inventory found no reusable MISCO Research/Organization values with authority independent of project-specific Attention/feedback, and the synthetic Research fixtures explicitly are not defaults. Concrete Research/Organization policy must therefore be added only when an authoritative reusable value exists; project RQ, method choices, provisional chapter placement, and runtime state do not belong here.

`research/misco-workspace-continuity/1.0.0/profile.json` is the one exception in shape but not in policy: it is a **migration-only continuity Profile**, not a fresh-project MISCO Research Profile. It carries only the `CORE-TRACE-001` exact-locator strengthening that an older fixture-bound Workspace already had, so Profile advancement does not weaken Core while removing synthetic Writer/Publication Profiles. Fresh MISCO projects do not select it, and it contains no methodology, source-quality, threshold, or method-choice defaults.

The legacy `research-profile/` tree was removed in #500 (tag `legacy-archive-2026`); `docs/migration/misco-legacy-sources/` keeps the files the migration ledger pins. Production resolution must not read that archive to recover rule text.

## Resource delivery

A manifest resource is resolved relative to its manifest, must remain inside canonical `profiles/`, must carry a SHA-256 pin for production resolution, and must be UTF-8 text. The production resolver verifies the pin and copies the normalized text plus provenance into `effective_resources` in the Effective Profile Set (EPS). This makes Workspace history and detached EPS inputs self-contained. Research Package 0.2.0 also copies the selected `effective_resources` beside its Profile pins, so detached Writer/Publication work does not need the current checkout or legacy tree to recover selected rule text.

Layer B audit material, Layer C Human Review material, and synthetic few-shot examples are not production resources. For `misco.writer@1.1.0`, `WRITER_RULES` is the rule inventory and `WRITER_SOURCE_DOCUMENTS` carries the normalized UTF-8 bytes of the eight approved Layer A documents actually referenced by those runtime rules. For `misco.publication@1.3.0`, `PUBLICATION_FORMAL_SPEC` and `PUBLICATION_URL_DISPLAY` carry the approved production application policy in addition to the clean rule/source-document resources; the formal binary originals remain external and are identified by exact digests in the resource. Detached inputs project these resources and exact Profile pins; a host must not recover missing policy from `research-profile/`, historical examples, or the network.

## Composition

`extends` is same-profile-type inheritance. Cross-type dependencies use `requires`; `requires` never creates override precedence. Cross-category last-write-wins is forbidden: ambiguous collisions are errors.

Core non-overridable invariants remain the semantic floor. Profiles may preserve or explicitly strengthen them but may not disable, weaken, reinterpret, or replace them.

## Minimal resolution example

For an existing Workspace, a profile-generation request can select the production Publication Profile (which pulls the Writer/Narrative Profile transitively):

```json
{
  "profile_manifest_files": [
    "profiles/narrative/misco/1.1.0/profile.json",
    "profiles/publication/misco/1.3.0/profile.json"
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
