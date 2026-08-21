# Interactive Work Research Coordinator

This document is the stable bootstrap contract for a human-interactive Work
session. It is an execution contract, not a research method, research result,
question definition, or publication instruction.

Start a session by opening this repository in Desktop Work and telling Work:

```text
Execute WORK_RESEARCH_COORDINATOR.md.
```

The repository's `rh` CLI and the immutable `.rh/` runtime are the control
plane. Work performs only the bounded research or reasoning described by the
generated task for the current run.

## Authority and roles

The Harness is the sole authority for:

- the current `OrchestratorState` and `ResearchState`;
- the current phase and runnable operation;
- the authorized Context Pack and its forbidden context;
- the expected structured-result schema and result location;
- independent audit, state reduction, snapshots, and continuation;
- pending Human Decisions and terminal or blocked status.

Interactive Work is responsible only for the substantive research or
reasoning requested by the current generated `TASK.md`, within its authorized
Context Pack. Work must not infer a next phase from repository contents or
from a previous task, and must not edit Research State directly.

The human remains the authority for semantic research decisions, including
question-baseline adoption or revision, method/protocol approval, Evidence
qualification, finding/model/recommendation adoption, scope changes, and
publication decisions.

Repository access for Harness control is not permission to use repository
contents as Research Context.

## Start or resume

From the repository root, use the existing CLI boundary:

```powershell
uv run rh --root . status
uv run rh --root . coordinator next
```

`status` returns the compact orchestrator state. `coordinator next` observes
the state and, when the Harness is ready, materializes at most the next
bounded Work run. It returns one typed action and does not execute substantive
research. `coordinator next --no-advance` only inspects an already materialized
Work or Decision boundary. The lower-level `continue` command remains
available for Harness-only operation:

```powershell
uv run rh --root . continue --run-limit 10
uv run rh --root . plan
```

For a new real workspace, the backend must be explicit; use
`--worker-backend interactive-work` during initialization. Never omit the
backend and never select `mock` for real research:

```powershell
uv run rh --root . init `
  --theme intake/theme.md `
  --expectations intake/expectations.md `
  --worker-backend interactive-work
```

`--seed` is optional. The command above starts Question Formation without a
provisional prior seed. If the human later chooses to use one, register it
before the independent candidate snapshot is frozen:

```powershell
uv run rh --root . seed register --path quarantine/provisional_rq_seed.md
```

With no registered seed, the frozen independent candidate snapshot proceeds
directly to `QUESTION_REVIEW`; `SEED_COMPARISON` is skipped. A seed registered
after that snapshot is immutable is not injected into Question Formation and
cannot be retrofitted into the already-completed discovery cycle.

## Read the next action

Use the JSON emitted by `status` or `continue`. The following fields are the
current CLI/state contract:

- `execution_state == "WORK_EXECUTION_REQUIRED"` and non-null `pending_work`
  mean that Work must execute one generated task.
- `pending_work.task_file` identifies the generated task contract.
- `pending_work.context_pack` and `pending_work.manifest` identify the only
  research context authorized for that run.
- `pending_work.expected_output_schema_file` identifies the exact JSON Schema.
- `pending_work.expected_output_file` is the only accepted result path.
- `pending_work.run_id` is the run identifier required by collection.
- a non-empty `pending_decision_ids` list means `DECISION_REQUIRED`.
- `terminal == true` means `TERMINAL`; stop.

The coordinator action returned by `coordinator next` or `coordinator submit`
uses these states: `WORK_EXECUTION_REQUIRED`, `DECISION_REQUIRED`,
`COMPLETE`, `ERROR`, and `BLOCKED`. Treat `ERROR` and `BLOCKED` as stops; use
the returned `message` and `recovery` fields as the only recovery guidance.

The current first-cycle operation names are:

```text
INDEPENDENT_QUESTION_CANDIDATES  / QUESTION_FORMATION
SEED_COMPARISON                  / SEED_COMPARISON
DESKTOP_RESEARCH_PREPARATION    / RESEARCH_PLANNING
DESKTOP_RESEARCH                 / DESKTOP_RESEARCH
```

Do not add an operation or invent a state when the Harness reports a value
outside this contract. Stop and report it as an error or blocked condition.

## Execute a Work task

When `pending_work` is present:

1. Open exactly `pending_work.task_file`.
2. Read only the authorized Context Pack and manifest named there. Follow the
   task's `Authority boundaries`, `Required work`, and `Forbidden context`.
3. Perform the requested research or reasoning. Do not make a Human Decision.
4. Validate the structured output against
   `pending_work.expected_output_schema_file`.
5. Write the result only to `pending_work.expected_output_file`.
6. Return it through the Coordinator:

   ```powershell
   uv run rh --root . coordinator submit --result <expected-output-file>
   ```

The Coordinator submits through the same Harness collection boundary. The
submission validates the schema, checks the Context Pack, runs the independent
audit, reduces the result, writes immutable run and Research State snapshots,
and exposes the next action. Do not copy result fields into `.rh/state/`, edit
`head.json`, or bypass collection. The lower-level equivalent remains
`uv run rh --root . work collect <run-id> --result <expected-output-file> --run-limit 10`
when direct CLI operation is required.

The supported Work result schemas are selected by the pending request. They
include `IndependentQuestionFormationHandoff`, `SeedComparisonHandoff`,
`WorkerResult` for Desktop Research preparation, and
`DesktopResearchHandoff` for Desktop Research. Always use the schema named by
the request rather than assuming a schema from the phase.

After submission returns, repeat `coordinator next`. If a Work host supplies
an external executor to the Python coordinator, it may use the same
`next_action` → execute `TASK.md` → `submit_result` loop; no Work API or UI
automation is implied.

## Context and research-lane invariants

The Context Pack is frozen before Work preparation. It is never a result or
output directory. Task files, schemas, and result exchange are kept in the
separate `.rh/work_exchange/<run-id>/` directory. Do not mutate, rename, or
write into an existing Context Pack.

The Harness enforces the following boundaries; Work must preserve them in its
reasoning and output:

- Independent Question Formation cannot read the provisional Seed. Seed
  Comparison can use the Seed only after the independent candidate snapshot
  is immutable.
- The Attention Map is coverage guidance only. It is neither answer authority
  nor method authority.
- Discovery and planning tasks may report options, uncertainty, limitations,
  overlaps, counterevidence, and Evidence Gap hypotheses, but may not select a
  research method or approve a Question Baseline.
- Desktop Research uses only the approved baseline and protocol supplied by
  its Context Pack. Candidate next-method options are non-binding and remain a
  Human Decision.
- Publication Drafts, Publication Feedback, Clean Publication Source, Writer
  materials, historical calibration sources, archive/provenance, and other
  denied roles are not Research Context unless an explicit Harness contract
  authorizes a specific artifact for that run. Publication prose is never
  Research Evidence.
- Preserve counterevidence, uncertainty/unknowns, scope limits, question
  overlaps, Evidence Gaps, and their hypotheses. Do not replace them with a
  conclusion for convenience.

Do not browse sibling directories, `archive/`, `provenance/`, `quarantine/`,
publication materials, historical reports, prior research questions, or other
files merely because they exist in the repository. The Context Pack manifest
and task are the access boundary.

## Human Decision hard stop

When `pending_decision_ids` is non-empty, stop Work immediately. Do not infer
approval from an AI recommendation, option order, majority, prior decisions,
or an apparently obvious next step. Do not create or record a decision.

The human reviews the emitted packet:

```powershell
uv run rh --root . decisions
uv run rh --root . decision show <decision-id>
```

The coordinator action also supplies `decision_id`, `decision_packet`,
`decision_request`, and the declared `decision_options` as pointers and
metadata; it does not include authority to choose among them.

Only the human records a declared option from that packet:

```powershell
uv run rh --root . decision record <decision-id> --choice <declared-choice> --by <human-name>
```

After the record succeeds, resume with `status` and `continue`. A rejected,
unknown, or malformed decision must not advance the state.

## Failure and terminal handling

On a missing task/result, schema failure, Context Pack mismatch, forbidden
reference, audit failure, or command error:

- preserve the immutable run and prior snapshots;
- show the Harness error and any stated recovery information;
- correct only the authorized task result or use the Harness retry path;
- do not bypass schema validation, audit, reduction, or a Human Decision;
- stop if safe recovery is not explicitly supplied by the Harness.

When `terminal` is true, report completion and stop. Do not start a new run
from repository contents after a terminal or blocked state.

## Operational trace

The Harness records operational trace in `.rh/`: run manifests, Context Pack
manifests, Work execution requests, structured results, audit results, state
delta proposals, Research Handoffs, Decision Requests/Records, and immutable
state snapshots. This coordinator records operational events only; it does
not store private chain-of-thought.
