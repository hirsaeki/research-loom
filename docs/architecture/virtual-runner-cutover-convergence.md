# PR17 — Virtual Runner and VIRTUAL→REAL cutover convergence

PR17 adds a canonical cross-method synthetic execution backend after the PR9 Capability ABI and PR12 Research Method execution semantics were stabilized.

The design deliberately preserves four boundaries:

1. **Method semantics stay with the Method capability.** Survey and Delphi remain responsible for their own protocol/instrument/execution meaning. Virtual Runner only binds their approved `execute` inputs and changes the acquisition side to synthetic generation.
2. **Synthetic research content is firewalled.** Every virtual response/observation/raw item and downstream candidate remains `SYNTHETIC_TEST_ONLY`. Validation success never upgrades epistemic status.
3. **Cutover freezes design, not results.** Approved Method/Protocol/Instrument/schema/template/code/gate pins can cross the boundary; synthetic responses, analyses, findings, consensus/patterns and participant identities cannot.
4. **REAL is a new run.** A new Run Root, Run ID, runtime authorization, access zone, owner/permission context and raw-data namespace are required. Virtual Runner may assess readiness but never starts REAL.

STANDARD and STRESS are scenario classes under `execution_mode=virtual`, not new PR9 execution modes. STRESS exists to exercise fail-closed behavior such as incomplete input, dropout/nonresponse, contradictory/extreme values, branching edges, invalid/duplicate records, unavailable data, Delphi attrition/no-consensus and method-specific bounds.

Cutover readiness is intentionally policy-driven. Required run counts and concrete thresholds belong to Project/Profile/Protocol configuration. The canonical contract only requires that the selected policy be pinned and that a claimed `CANDIDATE_READY` state be consistent with its required STANDARD/STRESS runs, blocking defects, approved revisions, validation state and Human Gate requirements.

The PR10 routing fixture demonstrates that natural language such as “このSurveyを仮想実行して問題を洗って” becomes a proposal routed through the PR9 invocation boundary. Additional runs, revisions and REAL cutover remain proposals/candidates; conversational confirmation is never substituted for a Core Human Decision.

Downstream virtual Research Snapshot/Package preview is recognized only as a future candidate projection boundary. Writer/Publication preview details are deferred to PR18 so this PR does not import Writer/Publication semantics into the research execution layer.
