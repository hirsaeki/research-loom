# Work Conversation fixtures

Synthetic executable fixtures for PR 10. They exercise the canonical interaction chain above PR 9 without implementing a coordinator runtime:

`Human natural language -> typed Action Proposal -> optional state-bound Confirmation -> Harness service or PR9 Capability Invocation -> immutable Action Receipt`

The generic flow also binds PR9 Handoff candidates `NA-001` and `NM-001` into conversational presentations. Both remain `proposal_only`; the candidate next method retains a Human Decision boundary and deliberately has no selected execution route.

The fixture's state identifiers and payload contracts are test-only sentinels. They do not establish a production action enum, runtime state store, Work API, CLI syntax, expiry duration, or coordinator implementation.
