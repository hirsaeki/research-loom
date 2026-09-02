# Production LLM Survey Virtual Respondent

This slice adds a semantic synthetic-response backend to the existing Survey Virtual Runner. It does not replace the PR41 structural generator.

```text
Canonical Survey Instrument
        │
        ├──────── structural generator
        │          schema / branch / stress testing
        │
        └──────── LLM Virtual Respondent
                   semantic synthetic responding
                         │
                         ▼
                  Raw Survey Responses
                         │
                         ▼
              PR42 canonical response path
                         │
                         ▼
               SurveyResponseDataset
                         │
                         ▼
               PR43 shared aggregation
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
       individual responses   aggregate results
              └──────────┬──────────┘
                         ▼
                  Human inspection
```

## Epistemic boundary

LLM respondents are test fixtures for Instrument inspection. They are not research participants and their output is never population evidence.

```text
synthetic response distribution != real population distribution
LLM persona                     != real participant
LLM aggregate                   != empirical Survey finding
Virtual pretest                 != validity certification
```

Every generated response is runner-owned `synthetic` / `SYNTHETIC_TEST_ONLY`. Provider output cannot override origin, identity namespace, evidence status, or Research authority. The Run does not verify Evidence, adopt a Finding or Recommendation, answer an RQ, revise the Instrument, or mutate the Research Snapshot.

The shared PR42 response boundary and PR43 aggregation service remain the only response and aggregation paths. There is no LLM-only Dataset or analytics implementation.

## Backend selection

`virtual_runner.survey.execute` keeps `execution_mode = virtual` and adds a provider-neutral generator selection:

```text
generator_backend = structural | llm
```

`llm` is not a new execution mode or scenario class. The initial LLM slice supports `STANDARD`; PR41 `STRESS` remains the responsibility of the structural generator.

The core port is intentionally small: `VirtualRespondentBackend.generate_response(...)` accepts the exact Instrument, one explicit synthetic respondent profile, generation configuration, and prompt-template pin. Provider-specific request/response shapes remain inside the adapter.

The concrete production adapter is `openai_responses`. It uses the Responses API with schema-constrained structured output and `store=false`. Credentials are read at call time from a configured environment-variable name (default `OPENAI_API_KEY`). The credential value is never persisted in Project Config, Run artifacts, provenance, or logs.

## Synthetic respondent plan

The first slice accepts explicit structured profiles only. Profiles use a synthetic namespace such as `SYN-PROFILE-*` and may contain declared project dimensions in `attributes`, a bounded `knowledge_scope`, and optional scenario notes. Direct identifiers such as names, email addresses, employee IDs, or staff IDs are rejected.

Profile composition is a test configuration. It does not claim to represent an organization or population. Profile generation by another LLM, demographic simulation, population weighting, respondent societies, memory, and model ensembles are out of scope.

Each Run pins:

- exact Instrument ID/version/digest;
- exact respondent profiles and per-profile/content digests;
- backend/model and backend-configuration digest;
- stable prompt template ID/version/digest;
- generation-configuration digest;
- Research Snapshot and existing Project/Profile pins.

The initial interaction model is `full_instrument_single_call`: one independent LLM call per respondent, with the ordered Instrument supplied as structured data. Respondents never receive other respondents' answers or aggregate results. This is not claimed to reproduce a question-by-question human cognitive interview.

## Prompt and answer boundary

The stable prompt assigns only the synthetic respondent role. It does not ask the model to review the questionnaire, decide validity, or rewrite the Instrument. Instrument text is serialized as data and cannot redefine backend control instructions.

The model receives only the synthetic profile, Survey introduction/question text, canonical stable choices and constraints, branching semantics, and the minimum answer context needed for the Instrument. Research Findings, expected conclusions, and Desktop Research results are not injected by the backend.

Structured output is converted into the existing structural response record and then into PR42 `RawSurveyResponseInput`. Stable choice values are requested. If a model nevertheless produces a semantic invalidity, the backend does not substitute a plausible answer: canonical response validation preserves/rejects it. Branch violations, invalid choices, invalid scales, malformed multi-selects, and missing-state problems therefore remain inspection material.

No chain-of-thought or hidden reasoning is requested or persisted. Sanitized provider response capture retains message/output text, request ID, usage when available, and digests, but drops reasoning output types and credentials.

## Retry and partial success

Retries are bounded independently for transport failure and serialization-only repair. A repair request may repair JSON serialization; it must not reinterpret or improve answer content. Runtime/backend failures and Survey validation issues remain separate categories.

A generation report retains respondent profile IDs, attempt count/history, provider request ID where available, sanitized provider output/digest, parsed-answer digest, and failure codes. Partial generation success is allowed. The caller may set a small `minimum_valid_response_count`; shared aggregation is not produced when the canonical Dataset does not meet that minimum, and zero valid responses cannot become a successful aggregate.

## Public inspection and durability

The existing public surfaces remain authoritative:

- `run show` reports backend/model/prompt/profile pins, generation attempts, requested/generated/valid/rejected/failed counts, Dataset reference, AggregateResult reference, validation issues, and diagnostics;
- Survey Dataset/response show surfaces expose accepted and rejected canonical responses;
- PR43 aggregate show exposes frequency, missingness, multi-select frequency, scale distributions, requested cross-tabs, and bounded free text.

Run artifacts, response Dataset, and aggregate results are immutable. Re-running after an Instrument/profile/model/configuration change creates a new Run. Workspace reopen preserves the same provenance and public inspection references.

## Non-goals

This slice does not add automatic profile synthesis, cognitive interviews, questionnaire scoring/certification, automatic Instrument revision, REAL Forms/CSV/Excel intake, population inference, confidence intervals, REAL-population weighting, psychometric validity claims, model benchmarking, ensembles, dashboards, or automatic Evidence/Finding/Recommendation adoption.
