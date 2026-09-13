# Public Research Argument proposal

Issue #134 adds one bounded Research-side synthesis ingress: `research.argument.propose`.

The caller supplies the semantic Core Argument fields plus explicit IDs already present in the exact current Research Snapshot. Loom derives the Argument ID, project/lineage/Snapshot binding, canonical candidate digest, and proposal provenance. Research Question and Finding references must already be authoritative; detached Package prose, Exhibit text, and candidate-only Run output do not count as support merely because they exist elsewhere.

The action only stores a candidate `StateDeltaProposal`. It does not mutate Research State. The operator applies the exact proposal through the existing `state.apply_candidate` route, including its existing Confirmation and dynamic Human Decision rules. Argument creation itself does not introduce a new authority class.

Desktop Research continues to be the production Finding source. Its normalized `candidate_findings` now request an `approved` target state inside the candidate-only proposal. Therefore `state.apply_candidate` detects the existing `research_adoption / approve` requirement and invokes the established Human Decision gate before the Finding becomes authoritative. No generic Finding editor or second adoption engine is introduced.
