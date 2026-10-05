# Late visual needs

The Host translates ordinary requests such as “this comparison would be clearer as a graph” into existing Research Exhibit, Package, Composition and Writer operations. Humans review meaning and the actual output; they do not choose internal IDs or manipulate Package files.

Use `exhibit visual-need --json-input ...` (or `capture_visual_need`) to retain an ordinary note Exhibit. Its request contains `origin`, `purpose`, `semantic_changes` and `affected_section_ids`. The Host resolves the current origin internally:

- Narrative: `{stage: narrative, composition_id, composition_version}`.
- Writer: `{stage: writer, composition_id, revision_id}`.
- Publication: `{stage: publication, build_id}`.

The operation loads and pins the actual immutable source Composition and Package, plus the exact Writer revision or Publication build when applicable. It creates no workflow state, Research mutation or approval.

An empty `semantic_changes` list routes to Exhibit capture/generation and Package rebuild. New value, aggregation, classification, causality, relation, interpretation or generalization routes to ordinary Research work and its Human Decision boundaries. New external material also uses ordinary Research intake. The Host asks about the substantive new meaning only where needed. Publication does not invent it to fill a gap.

For representation-only work, capture the new Exhibit and any required explanation review. Call `exhibit resume-visual` (`resume_visual_need`) with the note `need_id`, final selected `exhibit_ids`, and `section_exhibit_refs` for affected sections. These are Host-resolved fields. Select all existing Exhibits still referenced by preserved sections and all semantic dependencies/review notes required by the new visual. Removing/replacing a visual changes this final selection and the affected section references.

Resume reloads source pins after a fresh process and requires the represented Research objects to remain exactly current. It rejects declared research-changing candidates or review conflicts and requires a selected conforming review before resuming an explanation. Pending candidates may be retained in a Package for review, but cannot resume affected writing through this operation. It builds a new Package with the existing objects, Runs, material captures, inputs and gaps plus the selected Exhibits and visual-need note. It then captures a new Composition series with source-history provenance, retaining purpose, audience and all untouched section meaning. Existing Composition series cannot be rebound to a different Package, so the new series records its exact predecessor in `created_by` rather than rewriting the old one.

The Host selects the new Composition and exports source-bound Writer inputs. Revise only affected prose; reuse unaffected prose only when its meaning and exact source scope still match. Import it under the new input pins through the existing Writer response operation. Old Writer revisions cannot silently become revisions of the new Package. Build a fresh Publication preview and inspect it. Old Packages, Compositions, Writer revisions and previews remain available unchanged. Preview success provides no manuscript or release approval.

Backend regression tests exercise all three origins, fresh-process resume, representation-only addition/removal, new-research rejection and stale-Package insertion rejection. Their synthetic review fixtures are not live Host UAT; that is tracked separately in #409.
