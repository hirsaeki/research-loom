# Work Chat Operator Guide

Work chat is the normal Human interface to the Harness. It is not a Research
Evidence source and it cannot directly mutate state from natural language.

## Inspect and propose

```powershell
uv run rh --root . conversation status
uv run rh --root . conversation propose --actor <human> --text "What is pending?"
uv run rh --root . conversation propose --actor <human> --action SHOW_DECISION --parameters '{"decision_id":"<decision-id>"}'
```

The response contains the state ID/hash, bounded summaries, Human-attention
reasons, and only currently allowed typed actions. A proposal is not a commit.

## Transition lock status and crash recovery

Inspect the Discovery and Publication transition locks before retrying after an
interrupted process:

```powershell
uv run rh --root . locks status
```

An old timestamp is evidence for investigation, not permission for automatic
reclamation. After confirming that the owning process is gone, a Human may
release the named lock and must record the reason:

```powershell
uv run rh --root . locks release discovery-transition --by <human> --reason "confirmed orphaned process"
uv run rh --root . locks release publication-transition --by <human> --reason "confirmed orphaned process"
```

The release writes an immutable record under `.rh/locks/releases/`. A lock
held by the current process cannot be released through this path.

## Confirm a typed action

```powershell
uv run rh --root . conversation propose --actor <human> --action RECORD_DECISION --parameters '{"decision_id":"<id>","choice":"<choice>"}'
uv run rh --root . conversation confirm <confirmation-id> --by <human>
```

Confirmation is single-use and bound to the current state ID/hash, actor,
action, and expiry. If the state changed, propose again. Accepted and rejected
state-changing attempts produce immutable receipts under
`.rh/conversation/receipts/`.

## Work result and operational stop

```powershell
uv run rh --root . conversation propose --actor <human> --action SUBMIT_WORK_RESULT --parameters '{"run_id":"<run-id>","result_path":".rh/work_exchange/<run-id>/result.json"}'
uv run rh --root . run abort <run-id> --reason "operator stop" --by <human>
```

The existing interactive Work exchange remains the bounded transport. Large
or restricted files, authentication, technical repair, direct immutable audit,
and unsafe-to-summarize comparisons remain explicit exceptions.

Do not paste unstructured findings as a substitute for the declared result
schema. Do not ask chat to choose a method, Evidence qualification, or Recovery
Decision treatment.

## Attention intake and lifecycle actions

For raw Attention material, register one explicit file or directory. This freezes
that batch and makes it available only to the next bounded distillation Work:

```powershell
uv run rh --root . attention ingest --path .\intake\drop\batch-01 --by <human>
uv run rh --root . coordinator next
uv run rh --root . coordinator submit --result .rh\work_exchange\<run-id>\result.json
```

Review the resulting `ATTENTION_MAP_ADOPTION` Decision. `ADOPT_CANDIDATE_MAP`
creates a new Map version, `KEEP_CURRENT_MAP` leaves the pointer unchanged, and
`REQUEST_REVISION` requeues the same drop. None of these choices creates
Evidence or changes Research State.

To archive a completed or explicitly allowed-incomplete workspace:

```powershell
uv run rh --root . archive --destination ..\archives\misco-2026-08-19 --by <human> --reason "research boundary closed"
```

The destination must be outside the source and new/empty. The source becomes
`ARCHIVED` only after bundle verification; data is not deleted. Create a fresh
study independently with `rh new`:

```powershell
uv run rh --root ..\misco-next new --template-root . --theme .\intake\new-theme.md --expectations .\intake\new-expectations.md --worker-backend interactive-work
```
