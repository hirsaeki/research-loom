# Independent review in the conversation flow (#452)

The purpose is to recover the human's goal when working history or internal
procedures displace it. This is a selective host action, not a new research gate.

1. Before the relevant first presentation/action, freeze the exact candidate and
   copy the original human request and still-applicable explicit instructions.
   Add the relevant evidence, warrant, counterevidence, real constraints and
   saved/candidate/adopted state. Preserve conditions needed to judge the answer;
   do not reconstruct the human's intent from the primary host's summary alone.
2. Make one actual new, read-only call in an isolated context. Do not resume/fork
   the primary session, inherit its memory/tool history, or send scorer notes.
   Reviewer tools/search/state changes are prohibited. Existing provider consent
   must cover the actual text; do not ask again when it already does.
3. Inspect the result and target binding. For each finding, record accept/reject
   and the specific original words/facts that justify the disposition. An empty
   list is valid. Lack of independent verification is not proof of content loss;
   a real operation refusal is not permission to bypass it.
4. Act before presenting: for a plan, change the planned actions; for an answer,
   revise the explanation; for missing research, use the existing public
   Research/Feedback path and take the next authorized step or identify the
   actual blocking condition. Preserve Writer/Publication and Human Decision
   boundaries. Do not report research complete after merely rewriting a stop.
5. Retain the original, raw review, dispositions, resulting plan/answer or public
   research result, model/settings, time/cost (unknown with reason), and first
   presented output in the host's ordinary work record. Keep failures too. Do not
   create a new Core authority/store. Do not promote a model judge into a score.

Budget is at most two reviews and one revision per request/stage; extra information
gathering uses the same budget. A second review is only for malformed output or a
specific post-revision issue, never to find a more agreeable critique. Failure
does not constitute PASS or justify stopping unrelated authorized research.

## Codex execution

Use `scripts/review_research_response.py` from the repository with the current
host model/settings and a **new private output directory**. It calls the existing
authenticated Codex CLI with no daemon/resume, explicit memory disabling, no
project instructions/apps/plugins/search, an empty working directory and a
read-only sandbox. It checks the original session log for supplied-input equality,
model/settings, disabled memory, no tool calls/compaction and unchanged raw output.
Standard host/global instructions still apply and are fingerprinted in the audit.
This adapter targets the locally verified CLI flags; unsupported flags or missing
audit logs are an unavailable review, not a reason to relax isolation.

The input is UTF-8 JSON with six strings: `request`, `instructions` (`none` if not
applicable), `target`, `facts`, `state`, `target_version`. Preserve the original
words and candidate bytes. The helper adds the SHA-256 and reviewer instructions.

```text
uv run --frozen python scripts/review_research_response.py --input <private-input.json> --output <new-private-directory> --model <host-model> --effort <host-effort> --reason <why-this-boundary-needs-review> --provider-consent --codex <codex-executable>
```

`--provider-consent` records already established consent to send this text to
OpenAI through the existing CLI login. It does not obtain consent or change global
settings. `review.md` is readable host feedback; `raw.txt`, `session.jsonl` and
`audit.json` retain evidence. A nonzero exit is a recorded failure. The helper does
not adopt findings, revise a target, execute research or decide when a Human
Decision is needed: the existing primary host performs steps 3–5 immediately.

On Windows, the primary host must retain its configured native sandbox and normal
approval route. `--ignore-user-config` also removes `windows.sandbox`; applying
the reviewer's isolated configuration to the primary host can leave no usable
sandbox backend and cause even file reads to be rejected. The reviewer itself
must not use tools. Its authenticated CLI still writes runtime/session records
under `CODEX_HOME`, so launching it from a restricted primary host may require
ordinary execution approval. Request that approval for the exact helper command
before the known restricted launch; retain any refusal and stop the operation.
Do not add allow rules, copy credentials, disable sandboxing or silently retry a
denied command. Keep all helper outputs within the approved writable workspace.

## Other hosts

A host with an isolated model-call tool can use the same five research fields,
target identity and reviewer instructions without the Codex adapter. Verify the
actual supplied context and retain its invocation evidence. If Work cannot make
an isolated call, record that limitation and continue honestly through the
existing workflow; do not claim Work live acceptance from a Codex run.

For human-readable examples, see the [Japanese operator guide](../../../docs/operations/reflective-review-in-conversation.md).
The existing [A/B/C comparison](../acceptance/reflective-review.md) remains a
separate, unchanged benchmark. Neither this helper nor contract tests establish
semantic effectiveness or broad-rollout acceptance.
