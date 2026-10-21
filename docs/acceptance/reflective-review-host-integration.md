# Selective conversation-host review: bounded live check (#452)

## Result and scope

On 2026-10-21, a fresh Codex primary host loaded the updated research-conversation
Skill, invoked the helper once, checked the findings against the original words
and supplied facts, and revised its first presentation once. This demonstrates
the Codex dispatch-to-presentation path, not general model effectiveness or live
acceptance of other hosts. Both calls used `gpt-6.1-sol`, effort `medium`.

The existing frozen HR2 input was used without prior reviews, scorer expectations
or scores. The host retained the real historical operation refusal, distinguished
adoption from evidence validation, and limited its proposed next step to checking
an unverified writing prerequisite. It did not execute the historical adoption or
claim research completion. The original comparison and all HR1 B/C score deferrals
remain unchanged; all 109 files in that RunRoot matched their pre-check hashes.

Earlier bounded checks exercised RR7 plan correction and the HR1 public research
return path. The latter used a separate disposable workspace copy, public material
reads, a note and an Argument proposal/readback; it did not adopt the proposal.
It was a primary-operator path check, not another fresh-host end-to-end run or
completion of the underlying research. The original managed workspace was
byte-identical before and after that check.

## Windows refusal diagnosis

The first fresh host failed before review: `Get-Content` of a required global
Skill was rejected as `blocked by policy`. The launcher combined
`--ignore-user-config`, a restricted filesystem and `approval_policy=never`,
without restoring the configured native Windows sandbox. Explicitly selecting
the same configured `windows.sandbox="mxc"` allowed the Skill reads and helper
launch. No matching rule was found by the non-executing check of the two local
rule files; that check alone does not evaluate all runtime policy.

The next failure was distinct: the sandboxed child CLI could not open its own
`CODEX_HOME/state_5.sqlite` and runtime paths. The successful new host retained MXC
and used the ordinary `on-request` / `auto_review` route for the exact helper
invocation with `require_escalated` and a scoped justification. No allow rule,
global configuration, ACL or credential was changed, and no sandbox was disabled.
Both failed invocations were retained separately. See the official
[Windows sandbox documentation](https://learn.chatgpt.com/docs/windows/windows-sandbox)
for native sandbox configuration.

## Evidence and validation

Private original evidence remains outside Git under
`D:\wsroot\scratch\reflective-review-integrated-host-20261021`.
The successful `primary-host-reviewed` directory contains the invocation,
unchanged primary/reviewer outputs and session logs, dispositions, first
presentation and `verification.json`.

- Primary conversation: `01a15e36-cdfd-7112-ab92-61f366cc1998`.
- Independent reviewer: `01a15e37-3bcb-71f3-ab34-c42f46fb4bcd`.
- Reviewer audit: memory disabled, zero tools, one new conversation, exact supplied
  input/settings/target binding, raw final equal to original session output.
- Reviewer raw SHA-256:
  `58ec5734dd76e3be772157b7c1f40848a9ecf3676895daa722a935ad184b4507`.
- First-presentation text equals the primary raw final except for one saved trailing
  LF; neither original output was edited. CLI cost is unknown with a reason.
- Full local suite: 2,072 tests passed, four workers, 521.075 seconds. Frozen uv
  sync, ruff lint/format and mypy passed. The local mypy entry point was unavailable;
  the same installed tool passed via `python -m mypy` (44 source files).
- After the Windows procedure documentation change, 19 focused review, document
  link, CI selection and test-map checks passed. These regression checks use
  synthetic CLI output and do not score semantic model quality.

The private paths and identities locate this bounded observation; they are not
portable fixtures or a requirement to expose research conversations in Git.
