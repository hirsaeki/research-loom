# Production Survey Virtual Runner

PR41 adds the first production binding from the canonical Virtual Runner execution backend to Survey.

The authority flow is:

```text
Canonical Survey Instrument
        ↓
Virtual Runner
execution_mode = virtual
        ↓
STANDARD / STRESS
        ↓
structural synthetic response artifacts
        ↓
canonical Survey response validation
        ↓
defects / warnings / candidate change requests
        ↓
candidate pre-REAL readiness
```

## Authority boundary

The canonical authority remains:

- `core/packages/virtual-runner/virtual-runner-contract.schema.json`
- `core/packages/virtual-runner/virtual-runner-semantics.yaml`
- the Research Method execute contract
- the PR40 Survey Design / Instrument registry and Survey contracts

The production binding does **not** redefine those contracts.

`STANDARD` and `STRESS` are `scenario_class` values. They are not execution modes. Every PR41 Run uses `execution_mode = virtual`.

Virtual Runner is an execution backend, not a Research Method. Survey-specific response, missing-value, stable-value, and branching semantics remain owned by Survey.

## Exact input pins

A Survey Virtual Run uses the exact PR40 Instrument revision supplied by `instrument_id`, `instrument_version`, and `instrument_digest`, and verifies its stored Design, RQ, Project Config, Effective Profile Set, and Research Snapshot provenance against the current State.

The canonical Virtual Runner contract additionally requires an adopted Core Method, approved Protocol, and pinned RunSpec. PR41 does not create a second Survey Protocol authority to satisfy that requirement. The production action therefore requires those existing Research Method inputs and verifies Human approval bindings where authority is required.

Instrument, Protocol, and RunSpec pins are immutable for the Run. A revised Instrument is a new revision/digest and requires a new Virtual Run.

## Public production surface

The existing typed action ingress is reused:

```text
research-loom action submit --workspace <workspace> --json <request.json>
```

with `action_type = virtual_runner.survey.execute`. No new generic runner CLI namespace is required.

A completed Run is inspected through the existing surface:

```text
research-loom run show --workspace <workspace> --run-id <RUN-ID> --json
```

For Survey Virtual Runner Runs, `run show` adds a `virtual_runner` projection containing execution mode/scenario, exact input pins, synthetic population specification, generation provenance, validation failures/preservation events, defects/warnings, candidate change requests, and candidate readiness. Ordinary Run diagnostics remain separate from the Virtual Runner defect register.

## Generator backends

The Survey Virtual Runner supports two deliberately separate generator roles. The PR41 structural generator remains the schema/branch/STRESS backend. The LLM Virtual Respondent is an additive semantic synthetic-response backend; it still uses `execution_mode = virtual`, and its first slice uses `scenario_class = STANDARD`. Both backends must feed the same canonical Survey response boundary rather than defining backend-specific response or aggregation semantics. See `production-survey-llm-virtual-respondent.md`.

## Structural generator

The built-in generator is intentionally structural. It uses only declared Instrument values and bounds, explicit missing-value states, branch rules, and synthetic placeholders such as `SYNTHETIC_TEXT_001`.

Synthetic identities use a dedicated `synthetic:survey:...` namespace and `SYN-PARTICIPANT-...` IDs. It does not generate names, email addresses, employee numbers, REAL participant IDs, organizational personas, or population-distribution claims.

The canonical generation-provenance field named `prompt_template_*` is pinned to the deterministic structural generation recipe because the frozen Virtual Runner contract requires that field. It is not an LLM prompt, and provider/model fields are intentionally absent for the built-in generator.

## STANDARD and STRESS

STANDARD exercises normal completion, stable values, supported branch paths, optional missingness, and declared explicit missing-value states.

STRESS can inject bounded structural cases including required missing, optional missing, invalid choices, out-of-range scales, branch violations, duplicates, partial/dropout responses, malformed response input, extreme valid values, and declared `unknown` / `not_applicable` / `prefer_not_to_answer` states.

Expected STRESS failures are preserved as detected/resolved defects. They demonstrate that the validator caught the injected condition; they do not imply that the Instrument itself must be changed. Unexpected validation failures remain open defects and can produce candidate change requests. The runner never edits the Instrument.

## Shared Survey response validation

`core/packages/survey/survey-response.schema.json` is the provider-neutral detailed response shape used by the production Virtual Runner and intended for later REAL Survey intake. It preserves the canonical Survey response metadata and adds answer-level values plus explicit identity namespace needed for structural validation. For `execution_mode = virtual`, response `epistemic_mode` remains `virtual`; `synthetic = true` and the `synthetic:` namespace keep the synthetic firewall explicit.

`plugins/survey_virtual_runner/response_validation.py` validates that shared Survey response contract. It distinguishes `missing`, `unknown`, `not_applicable`, and `prefer_not_to_answer`; it never collapses those states into `null` or an empty string. This is Survey response validation reused by the Virtual Runner, not a virtual-only response validator.

## Synthetic epistemic firewall

All PR41 execution artifacts and Virtual Runner result objects remain `evidence_status = SYNTHETIC_TEST_ONLY`. The Survey binding emits no synthetic Evidence, authoritative Analysis, Finding, Recommendation, or answered-RQ transition.

```text
Virtual Runner ≠ synthetic research method
synthetic result ≠ empirical result
readiness ≠ REAL execution
```

The normalization boundary may expose only an operational candidate `next_action` for Human review. It never carries synthetic responses, analyses, or findings into authoritative Research State.

## Readiness

Readiness is a candidate assessment only. The runner configuration pins whether STANDARD and STRESS are required and which defect severities block readiness. Prior Virtual Runs used for readiness are explicitly named and must be completed Runs with the same exact Design, Instrument, Core Method, Protocol, Research Snapshot, Project Config, Effective Profile Set, Virtual Runner descriptor, runner-code digest, and Survey binding digest. Scenario-specific RunSpec values may differ between STANDARD and STRESS.

The first production slice does not hard-code universal Core thresholds or run counts. `CANDIDATE_READY` does not approve or start REAL Survey execution. A later REAL path must use a separate authorized invocation, new Run root/Run ID, isolated REAL raw-data namespace, and empirical responses only.

## Out of scope

PR41 itself did not implement Microsoft/Google Forms execution, REAL response intake or participant registry, empirical analysis, LLM respondents, Delphi/Case Study production bindings, dashboards, or distributed runner infrastructure. The later LLM Survey Virtual Respondent slice adds only the semantic synthetic-response backend described above; the remaining non-goals stay unchanged.
