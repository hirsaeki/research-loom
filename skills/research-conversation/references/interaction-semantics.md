# Interaction semantics

## Candidate and current state

A candidate may contain the value that would apply after approval, including an `approved` target value. Read the current-vs-candidate projection rather than treating the candidate target as the current authoritative state. A stale historical candidate may remain readable; stale binding alone does not prove that it was never applied or that it must be proposed again.

## Retrieval failures and gaps

Blocked, failed, or unavailable retrieval means the material was not successfully obtained in that attempt. It does not prove the material or fact does not exist. Preserve the failed attempt/gap when it matters to coverage.

## Synthetic and empirical work

Virtual/synthetic respondents, test fixtures, and simulated runs are useful for procedure/instrument testing. They are not empirical respondents or REAL evidence. Keep the origin visible in any human-facing conclusion.

## Execution completion

Run `COMPLETED` is an execution fact. Check the operation-specific required result, normalization/candidate status, remaining gaps, and any unresolved decision before describing the research task as complete.

## Saved vs current-chat work

Persisted Loom facts and current-chat working analysis can both matter. Keep them distinct. Do not overwrite persisted facts with chat assumptions and do not erase current-chat work merely because it is not in `resume`.

## Internal detail on request

When the human asks for diagnostic details, show the relevant ID, digest, Snapshot/lineage binding, error code, or raw status and explain what it means. The normal-language contract is about default presentation, not concealment.
