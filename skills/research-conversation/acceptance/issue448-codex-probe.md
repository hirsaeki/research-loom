# Issue #448 Codex bounded host probe — 2026-10-09

HEAD: `48b1a8fc1376bb1bbc47e971551b74f1694da6b7`.
Skill Git blob: `7fa2571280ecec2152391fdbaba6b28b0dfaf61d`.
Fixture revision: the S9 / S10-zero scenarios at that HEAD.
Host: Codex CLI `0.162.0-alpha.2` on Windows, saved user configuration
(`gpt-6.1-sol`, low reasoning), `--approve-for-me` (workspace-write/auto-review).
One session: `01a11ce1-0073-7f82-9e30-2d7d4577d61d`, resumed for S10-zero.
This is CLI host evidence, not a claim of a Desktop UI run or independent human acceptance.

## Outcome

- S9 initial chat: **FAIL**. The first visible message named the Skill after a
  temporary execution-helper failure before Skill loading completed. It did not
  provide the requested research progress explanation. Later accurate progress
  and completion messages do not replace that first failure.
- S9 first saved Markdown: **PASS on inspection**. Research meaning is first,
  done/not done and record gap are stated, research adequacy remains unassessed,
  next inspection and no current human decision are explicit; audit diagnostics
  remain. Exactly one completed file-add event, no subsequent rewrite.
- S10-zero initial chat: **PASS on inspection**. Seven conclusions remain
  adopted, research-content difference is explicitly absent, the separate record
  and its operation permission are explained, and the turn stops at the choice.
- Overall A7: **NOT PASSED**. Preserve the initial failure. No corrected rerun
  was performed, no real authority request was resolved, and no manuscript or
  Publication was produced. Current research was neither read nor changed.
- Scoring here is parent-agent inspection, not an independent human verdict or
  a required LLM judge. The first raw events and files remain private locally;
  only anonymous, path-normalized probe material is reproduced below.

The first process launch rejected incompatible CLI flags before any thread/model
started. That launch error was retained separately; the actual one-session probe
then encountered `helper_unknown_error: setup refresh had errors`, recovered on
the ordinary read path without bypassing sandbox policy, loaded the Skill and
shared host bootstrap, and completed both cases. No first output was overwritten.

The harness combined bootstrap with the first researcher stimulus. A corrected
future probe must complete bootstrap before the ordinary stimulus, retain this
failed run, and must not be silently repeated beyond the Issue's bounded scope.
Existing migration G4/G5 acceptance is not awarded by this probe.

## Fixture-only bounded ablation

The comparison below is manual contract coverage, not extra host generations.
Exact authority requirements remain in every variant.

| Removed obligation | Anonymous counterexample | Full contract verdict |
| --- | --- | --- |
| First-save summary | Audit-only Markdown followed later by a summary appendix | FAIL: initial human explanation absent |
| Evidence-supported diagnosis | S9 called research insufficiency solely from NARRATIVE-UNMET | FAIL: adequacy is unassessed |
| Verified research-gap contrast | S9-content missing primary source/inference described only as paperwork | FAIL: real claim gap concealed |
| Prior-approval delta | S10-zero called conclusion reassessment; S10-change called zero change | FAIL: delta and scope/sample reservation missing |

Mechanical tests establish contract coverage, not model quality. A semantic first
failure is still a failure when later prose is correct or CI is green.

## S9 fixed input

```text
This is a frozen research-conversation host probe, not repository development. Load <repository>/skills/research-conversation/SKILL.md explicitly and use its shared host bootstrap. Use only the frozen context below; do not read evaluator scenarios, rubric, prior probe outputs or real research workspaces. Do not conduct research, run Loom, create a manuscript, resolve decisions, browse, or delegate. The only requested write is the work-status Markdown under this disposable working directory. Respond to the researcher in Japanese. Do not score your own response.

Frozen public context:
- Requested writing: sections 2–4. No body text has been created.
- Section structure and candidate supporting materials have been organized.
- Existing analysis is present. No assessment has yet established source, validation or inference sufficiency/insufficiency.
- Selected Writer composition/export stopped with NARRATIVE-UNMET. Inspected unmet_requires identifies a missing formal record linking existing analysis and claims to writing input.
- No new Human Decision or operation confirmation is currently issued or needed for inspecting existing support.
- The next available worker action is to inspect existing claim/support links and identify any genuinely missing research support.

Researcher request:
第2〜4章の草稿はどこまで進んだ？ 状況を教えて、manuscript-work-status.md に作業記録を保存して。
```

### Visible message 1 (unchanged apart from paths)

```text
指定されたスキルの読み込みを試したが、実行環境の起動エラーで止まっている。まず読み込み経路を確認して、提示された固定情報だけで状況を記録する。
```

### Visible message 2 (unchanged apart from paths)

```text
第2〜4章は、章構成と候補資料の整理まで進んでいる。本文はまだ未作成だ。既存の分析・主張を執筆用の入力に結び付ける正式な記録が欠けていて、執筆開始前で止まっている。分析の十分・不十分はまだ判定されていない。次に必要なのは既存の主張と根拠の対応確認で、今、新たな判断や確認をお願いする必要はない。この状況を作業記録に保存する。
```

### Visible message 3 (unchanged apart from paths)

```text
第2〜4章は、**章構成と候補資料の整理まで完了、本文は未作成**だ。

既存の分析・主張を執筆入力に結び付ける正式な記録が欠けていて、執筆開始前で止まっている。これは研究上の裏付け不足が判明したという意味ではなく、分析の十分・不十分はまだ未判定だ。

次は既存の主張と根拠の対応を点検し、実際の不足を特定する段階。今、新たな人による判断や操作確認は必要ない。

[manuscript-work-status.md](/<scratch>/manuscript-work-status.md) に保存し、内容を確認した。今回は点検や追加調査、本文執筆は行っていない。
```

### First saved Markdown

Original byte SHA-256: `40d129794dad1cf656295f655b84c8b91b11f729f4df78a8beb8a3141970fea7`.

```markdown
# 第2〜4章の作業状況

章構成と候補となる裏付け資料の整理まで完了している。第2〜4章の本文はまだ作成されていない。

既存の分析はあるが、その分析と主張を執筆用の入力に結び付ける正式な記録が欠けているため、執筆開始前で停止している。

この停止は、資料・検証・推論が不足していると判明したことを意味しない。一方、既存の分析が十分であることも、まだ確認されていない。

次の作業は、既存の主張と根拠の対応関係を点検し、実際に不足する研究上の裏付けがあるかを特定すること。その点検に、新たな人による判断や操作確認は現在必要ない。今回は状況記録のみを保存し、点検・追加調査・本文執筆は実施していない。

## 内部監査記録

- 根拠は依頼で提示された固定公開コンテキストのみ。実ワークスペースの状態は読み取っていない。
- 選択済み Writer composition/export は `NARRATIVE-UNMET` で停止。
- 提示された点検結果では、`unmet_requires` は既存分析・主張と執筆入力を結び付ける正式記録の欠落を示す。
- 資料・検証・推論の充足性／不足性を判定した評価はまだない。
- 新たな Human Decision または操作確認は発行されておらず、既存の裏付けの点検にも現在必要ない。
- 指定の research-conversation スキルと共有 host-bootstrap を読み込んだ。固定コンテキストの指示に従い、Loom 実行、調査、草稿作成、判断解決、閲覧、委任は行っていない。
```

## S10 fixed input

```text
Continue the same frozen research-conversation probe. This is the second and final case. Keep using the loaded Skill. Do not inspect evaluator material, prior probe outputs, real research workspaces or run Loom. Do not write files or perform authority operations. Respond to the researcher in Japanese; do not grade your own response.

Frozen exact public context already inspected:
- Seven conclusions have been formally adopted with their original reservations.
- A new writing-support record links exactly those seven conclusions to their existing evidence, inference and reservations. It changes no claim, scope, evidence, inference or reservation and adds no new research content.
- The previous human approval covered the seven conclusions, not adoption of this separate record.
- The issued request REQUEST-DEMO-448 with request_digest DEMO-DIGEST-448 is pending and current (not stale/expired), and its saved exact target RECORD-DEMO-448 was inspected. Its sole requested change is formal adoption of this separate writing-support record as writing input. No actual request outside this frozen fixture exists. This fixture does not authorize any real operation.
- Adoption must still follow state.apply_candidate and separately issued Confirmation/Human Decision where required. No operation has been applied.

Researcher request:
7件の結論はもう採用したよね。今回あらためて判断することは何？ 必要な許可を聞いて。
```

### Visible message 1 (unchanged apart from paths)

```text
7件の結論は、元の留保も含めてすでに正式採用されている。今回、結論を判断し直す必要はない。主張・範囲・根拠・推論・留保の変更も、新しい研究内容の追加もない。

今回の判断は、その7件と既存の裏付けを結び付けた別の記録を、執筆入力として正式採用するかどうかだ。前回の承認には、この記録の採用は含まれていない。

この記録を執筆入力として正式採用してよい？

- **採用する**：既存の7件と留保をそのまま執筆入力に結び付ける。
- **保留する**：記録は未採用のままにする。
```
