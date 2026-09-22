# Public surfaces for research conversation

Use public Facade/CLI operations. Do not make private SQLite or blob-layout inspection part of ordinary research conversation.

| Need | Public surface | What it proves |
|---|---|---|
| Resume saved work | `resume --json` | Bounded persisted checkpoint, pending workflow, Research Questions, and compact saved synthesis candidates |
| Inspect saved Recommendation/Argument | `synthesis-candidate list/show` | Bounded discovery and exact semantic content of saved synthesis candidates; candidate position is not adoption |
| Inspect one Run | `run show --run-id ... --json` | Run lifecycle, attempts, handoff/artifact/diagnostic provenance for that Run |
| Inventory captured external material | `external materials list --json` | Materials actually captured; failed attempts without capture are not materials |
| Discover typed actions | `actions --json` | Registered public operations and their contracts |
| Execute a typed operation | `action submit --json INPUT.json` | Result of that exact public operation; interpret its status narrowly |
| Continue confirmation/decision | public confirmation/decision commands or Facade methods | Exact issued request and receipt; do not synthesize authority from prose |

Prefer the smallest read that answers the current question. `resume` is not a full audit log, and a bounded/truncated list does not prove older items do not exist.
