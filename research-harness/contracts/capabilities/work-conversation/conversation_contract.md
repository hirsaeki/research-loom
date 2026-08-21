# Work Conversation Contract v0.1

The Work chat is an interface to the Harness, not a source of authority. Chat
prose is never Research Evidence and never directly mutates state.

The closed input classes are `QUERY`, `PROPOSAL`, `COMMITTABLE_ACTION`,
`CONFIRMATION`, and `CANCEL`. State-changing requests resolve only to the
allow-listed typed actions in `ConversationActionType`. A proposal creates an
immutable action and a state-bound, single-use `ConfirmationRequest`.

Confirmation is bound to the current orchestrator head ID and SHA-256, actor,
action, expiry, and one use. Missing, stale, mismatched, ambiguous, duplicate,
expired, or unknown actions fail closed. Every state-changing attempt emits an
immutable `ActionReceipt`.

The Human-only lifecycle actions `REGISTER_ATTENTION_DROP` and
`ARCHIVE_RESEARCH` use the same confirmation and state binding. Registration
freezes one explicitly selected raw Attention batch for the bounded
`ATTENTION_DISTILLATION` Work event; it does not adopt a Map. Archive creates a
verified preservation bundle and then freezes the source lifecycle. Work cannot
invoke either operation, and `rh new` is a separate Human CLI operation that
creates an independent target.

The coordinator calls existing Harness services. It does not assume a Work
API, automate the Work UI, or create a second planner or decision engine.
