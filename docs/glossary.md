# Glossary

Terms used across the repository, with the layer that owns each one. **User-facing** says whether a host may use the term in what it tells a human during a research conversation:

- **yes** means the term is fine as is.
- **no** means the term is internal. The [research-conversation Skill](../skills/research-conversation/SKILL.md) tells hosts to describe the research meaning instead. The Codex Stop hook blocks only the terms its patterns cover (for example Research Package, Writer round trip, Publication preview and Loom), so it does not catch every **no** term.

## Spelling and language

- Write **ChatGPT Work** for the host. Do not write "ChatGPT Desktop App Work", "Work mode", or "Work session" in current documents (records and acceptance evidence keep their original wording).
- Write **Effective Profile Set (EPS)** on first use in a document; **EPS** is fine after that.
- Write **Application Facade** for the public application boundary. `LocalApplicationFacade` is its class name.
- Write **Skill** for a host-loaded workflow under `skills/`.
- Specifications, contracts, code and comments are in English. MISCO manuscripts, acceptance records and some operations notes may be in Japanese. See [CONTRIBUTING](../CONTRIBUTING.md#language).

## Terms

| Term | Definition | Owner | Former names / aliases | User-facing |
| --- | --- | --- | --- | --- |
| Application Facade | The public operations a host or the CLI calls; the only way in to Research State and stores. | plugin (`plugins/local_application`) | application facade, public Facade, `LocalApplicationFacade` | no |
| Capability | A versioned research operation (Desktop Research, Survey, Delphi, Case Study…) described by a Descriptor and run through an Invocation. | core (ABI), plugin (implementations) | Research Capability | no |
| ChatGPT Work | The ChatGPT desktop agent host that runs research conversations through the CLI. | host | ChatGPT Desktop App Work, Work mode, Work session | yes |
| Context Pack | The bounded, read-only projection of Project Config, EPS pins and Snapshot that a Capability receives. | core | bounded context | no |
| Durable Store Root | A directory that owns a self-contained set of durable stores; the workspace Parent is `<workspace>/.research-loom/`. | plugin | Parent store root | no |
| Effective Profile Set (EPS) | The resolved, digest-pinned set of Profiles, constraints and resource bodies a Workspace is bound to. | profile (contract), plugin (resolver) | EPS | no |
| Handoff | The machine-readable result a Capability returns: candidates, captures, gaps and provenance. It never changes Research State by itself. | core | Capability Handoff | no |
| Human Decision | The recorded, exact-bound decision of a human that is required to adopt a candidate into Research State. | core | Decision, Human Decision Gate | yes (as "your decision") |
| Manuscript Package | Planned packaging of a fixed manuscript for release; named in the target flow but not implemented. | — | — | no |
| pre-REAL | Readiness checked with virtual or synthetic runs before a REAL (empirical) execution. | core / plugin | pretest | no |
| Profile | Declarative, versioned policy for research, organization, narrative or publication, under `profiles/<type>/<name>/<version>/`. | profile | — | no |
| Project Config | The project-local configuration that requests Profiles and holds project inputs; it is not Research State. | core (contract), `projects/` | — | no |
| Release Manifest | Planned record of a released publication; named in the target flow but not implemented. | — | — | no |
| Research Coordinator | The component that routes Work Conversation inputs to Harness actions. It is not the host. | core / plugin | Work Research Coordinator | no |
| Research Exhibit | A project-scoped, immutable analytical figure or table with its sources. | plugin | exhibit | yes (as "figure" or "table") |
| Research Package | A pinned, self-contained snapshot of research objects and materials handed to Writer and Publication. | plugin | Package | no |
| Research State | The authoritative, append-only research objects and their history. | core | — | no |
| Skill | A host-loaded workflow document under `skills/` (research-conversation, writer, publication). | `skills/` | skill | no |
| Snapshot | An immutable, content-digested set of exact research-object revisions; the unit that pins state. | core | Research Snapshot | no |
| Virtual Runner | The synthetic execution backend for Survey and other methods; its outputs are always synthetic. | plugin | VR | no |
| Writer Composition | A versioned selection and ordering of research material for the Writer round trip. | plugin | composition | no |
