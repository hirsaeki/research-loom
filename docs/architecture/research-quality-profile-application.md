# Research quality Profile application

Issue #333 connects the canonical `research_quality.*` Profile catalog to the
existing research path. It does not add a second research-quality model or a
new authority transition.

## Data path

1. The production Profile resolver composes Research/Organization Profiles.
2. The existing Desktop Research Context Pack receives the resolved
   `effective_constraints`, including configured values and provenance.
3. `research-quality evaluate` inspects the current Research State plus
   explicit Host/Human semantic assessments and evaluates only the selected
   Profile constraints.
4. The result is captured as an immutable Research Exhibit with the current
   snapshot/Profile pins. Capturing the evaluation does not mutate Research
   State and does not perform a Human Decision.
5. Authoritative adoption continues to use the existing candidate ->
   confirmation -> Human Decision path.

The machine-readable one-to-one mapping for the 22 closed Research quality
paths is `profiles/contracts/research-quality-application.yaml`.

## Machine facts and semantic assessments

Machine checks may decide facts that are already explicit in Core Research
State, such as Evidence verification status, independence-group identity,
Finding qualifier fields, Counter Review records, method protocol/limitations,
and configured numeric counts.

The evaluator does **not** infer source tier/role, Evidence directness or
support scope, Claim family, causal inference basis, source/synthesis overlap,
method family, remaining information value, or Organization-specific meaning
from names or prose. These are explicit assessments. Each assessment carries a
non-empty rationale and basis references to current Research objects, Research
Exhibits, or Runs. Machine validation checks the configured Profile rule against
those supplied judgments; it does not claim that the judgments are semantically
true.

Accordingly, `unevaluated` is distinct from `conformant`. Loading a Profile,
receiving a checklist, or recording that a Host read a rule never produces a
PASS-equivalent result by itself.

## Liveness and history

A quality evaluation is an observation about one pinned Research State/Profile
state. `violation` and `unevaluated` do not globally block source collection,
candidate creation, saving, or another evaluation. A corrected or expanded
research state is evaluated by capturing a new Research Exhibit; prior exhibits
remain unchanged. Existing Human Decision and Core provenance guards remain the
only authority boundary for adoption.

This separation also keeps unrelated Publication input gaps and pending
Decisions from becoming a research-wide gate.

## Production and fixture boundary

Issue #331 found no authoritative reusable MISCO Research/Organization values
that could be promoted into production defaults, and #332 therefore did not
create empty or invented MISCO Research/Organization Profiles. This Issue does
not manufacture them. The production evaluator applies whichever valid
Research/Organization Profiles are actually selected. Tests use the generic
Research-quality fixture only as a synthetic wiring/semantics oracle; its
numeric values and method choices are not MISCO defaults.

Project Attention remains planning context, not Evidence or an adopted research
conclusion. REAL/VIRTUAL separation and all Core provenance/Decision rules are
unchanged.
