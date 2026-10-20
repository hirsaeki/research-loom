# Research continuity and operational limits

## Status and scope

This is a normative principle for future design and review across Research Loom
contracts, runtime operations, and user-facing status. It does not assert that
all existing limits comply; each existing limit requires review in its own
context.

## Research continuity

Research Loom must support the continuation of human research. An arbitrary
count or capacity threshold must not become a research stopping rule.

- **Research and domain rules** govern the validity or admissibility of a
  particular research action. Required integrity, provenance, security, and
  authority checks remain hard boundaries within their declared scope.
  Operational convenience must not be presented as one of these rules.
- **Operational thresholds** concern counts, payload sizes, storage, context
  capacity, or execution budgets. They default to actionable warnings when the
  operation can safely continue. Crossing a threshold does not establish that
  research is blocked, invalid, saturated, or complete, and cannot substitute
  for a research judgment or required Human Decision.

Preserve all research data and submitted material. Never silently truncate,
discard, or overwrite data to satisfy a threshold. A bounded view or batch
must identify its scope and provide access to the retained remainder;
required governance and provenance information must remain intact.

## Operations that cannot safely complete

Some operations cannot safely complete within actual resource limits. In that
case, fail only the affected operation, leave authoritative Research State
unchanged, and preserve existing data and any already retained inputs or
results. If an input cannot be retained, report that explicitly without
claiming successful acceptance. Explain the concrete constraint and provide a
recoverable continuation path, such as explicit batching, pagination, retry
after resources become available, or a supported alternative representation.
The continuation must preserve the same integrity and authority checks and
must not imply that the human's research has ended.
