# Canonical Virtual Runner / VIRTUAL-to-REAL contracts

This package defines the cross-method execution boundary for synthetic pre-REAL runs.

Virtual Runner is an execution backend, not a Research Method. It uses the PR9 Capability ABI and binds an already-designed PR12 `execute` context. It does not select or adopt a Method, generate or approve Protocol/Instrument artifacts, redefine Survey/Delphi semantics, mutate authoritative Research State, or start REAL execution.

## Contracts

- `virtual-runner-contract.schema.json`
  - `virtual_runner_context`: approved Method/Protocol/Instrument/RunSpec pins, PR9 project/profile/snapshot/auth bindings, STANDARD/STRESS class, synthetic population and generation provenance.
  - `virtual_runner_result`: immutable synthetic execution result, defects, candidate changes, warnings and candidate cutover readiness. All research content remains `SYNTHETIC_TEST_ONLY`.
  - `virtual_real_cutover_manifest`: explicit readiness/freeze boundary. Readiness thresholds/run counts come from Project/Profile/Protocol policy rather than a universal Core threshold.
  - `real_run_start`: separate REAL root/run/authorization/access/raw-data namespace with no VIRTUAL content or identity transfer.
- `virtual-runner-semantics.yaml`: normative semantic catalog and stable semantic error IDs.

Initial canonical bindings exercise Survey and Delphi. The wire contract remains method-family-neutral so later method families can bind PR12 `execute` without duplicating method-specific semantics here.

## Synthetic content firewall

VIRTUAL responses, observations, raw data, Evidence candidates, Analysis candidates, Finding candidates, consensus/patterns, and participant identities never become empirical merely because a VIRTUAL run validated successfully. A validated virtual run may later support a synthetic preview projection, but that projection remains non-authoritative and `SYNTHETIC_TEST_ONLY`; the downstream Writer/Publication preview contract is intentionally deferred.

## Cutover

`CANDIDATE_READY` is only an assessment. REAL begins through a separate authorized invocation after required Human Decision boundaries and frozen content pins are satisfied. The freeze package carries approved design/configuration and validated implementation pins; it does not approve VIRTUAL research content. REAL observations, Analysis, Evidence/Finding candidates, participant identities, and raw-data namespaces are created anew from empirical inputs.
