# Issue #448 authorized corrective Codex probe — 2026-10-09

HEAD: `0fa49d5481d21357bae15b2f8f02a69beb01471a`.
Skill Git blob: `7fa2571280ecec2152391fdbaba6b28b0dfaf61d` (unchanged from the first run).
Host: Codex CLI `0.162.0-alpha.2`, Windows, configured `gpt-6.1-sol` / low reasoning,
`--approve-for-me` (workspace-write/auto-review).
Session: `01a11ce5-e5b4-7772-88d5-30d8610fb284`, resumed for both ordinary cases.

The user explicitly authorized one additional run of the same two cases after
reviewing the first failure. [The first run](issue448-codex-probe.md) remains FAIL;
this record does not replace or relabel it. No further live runs were performed.

## Setup and scope

Bootstrap was completed before either ordinary researcher request was sent.
Three setup-only file-reading attempts failed with
`helper_unknown_error: setup refresh had errors`; no ordinary case had started.
Without changing sandbox settings or permissions, the calling host then supplied
the exact canonical Skill, shared bootstrap and persona file contents as stdin
context in a separate setup turn. The local copies were checked byte-for-byte
against canonical sources; the Skill blob is the revision above. The host read
all three supplied sources and reported ready before S9. These operational setup
failures are retained privately and are not scored as researcher progress output.

The S9 frozen facts and researcher request are identical to the first run after
normalizing text-file line endings;
only the loading instruction was separated from the ordinary prompt. S10's whole
prompt is also identical after line-ending normalization. The target host was not given evaluator scenarios,
rubric, expected answers, prior probe outputs or real research data. It was told
not to grade its response. No retrieval, Loom execution, authority write,
manuscript drafting, Publication, second provider or extra ablation was performed.
Only a work-status Markdown was created in a separate disposable directory.

## Observed result

| Check | Result on parent inspection | Evidence |
| --- | --- | --- |
| S9 initial conversation / A1 | PASS | First ordinary visible message contains done/not done, record gap, unassessed research adequacy, next inspection, and no current decision |
| S9 first saved Markdown / A2 | PASS | Opening research-language summary, retained internal audit section; exactly one completed file-add event, no rewrites |
| S9 diagnosis / A3 | PASS for the live existing-analysis case | Does not infer insufficiency or sufficiency from the writing stop; true-gap, mixed and unknown contrasts remain frozen fixture checks |
| S10-zero / A4 | PASS | Seven conclusions adopted, zero content delta, separate writing-input record permission, meaningful options, then stop |
| Authority / A5 | Preserved | No real request resolved or state operation executed; exact authority rules unchanged; full CI covers existing implementation |
| Regression / A6 | Covered | Provider-neutral S9/S10 contrasts, existing rubric, focused contract tests and fixture-only ablation in the first record |
| Bounded host check / A7 | PASS on inspection for this authorized corrective run | One prepared Codex session, two first outputs retained below, original FAIL preserved |
| Explicit diagnostics / A8 | Preserved | Existing Skill diagnostic exception and S7 control unchanged; #391/#382/#294 checks pass |

S9's file-add operation succeeded, but the host's later shell readback failed in
execution-helper setup. The final response accurately disclosed that limitation
instead of claiming readback success. The parent independently read the actual
saved bytes and checked the file-change event count. This operational limitation
does not hide a semantic failure or an uncreated file.

This is bounded CLI host evidence and parent inspection, not an independent human
G4/G5 verdict, Desktop UI test, statistical quality guarantee or model-grading test
dependency. It does not award the separate migration-wide G4/G5 gates. No additional
full UAT is required by this Issue.

## S9 fixed input

```text
Use the loaded research-conversation Skill. Use only the frozen context below; do not read evaluator material, prior probe outputs or real research workspaces. Do not conduct research, run Loom, create a manuscript, resolve decisions, browse or delegate. The only requested write is the work-status Markdown in this disposable working directory. Respond to the researcher in Japanese. Do not score your response.

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

### First-turn visible message 1

```text
第2〜4章は、章構成と候補資料の整理まで進んでいる。本文はまだ作成していない。既存の分析と主張を執筆用の入力につなぐ正式な記録が不足しているため、草稿作成が止まっている。

この停止だけでは、分析や根拠が十分か不足しているかは判断できない。次は既存の主張と根拠の対応を確認し、本当に不足する調査上の支えがあるかを確かめる。今、追加の判断や確認をお願いする必要はない。この状況を作業記録に保存する。
```

### First-turn visible message 2

```text
第2〜4章は、章構成と候補資料の整理まで進んでいる。本文はまだ作成していない。

既存の分析と主張を執筆用の入力につなぐ正式な記録が不足していて、草稿作成が止まっている。ただし、これだけで分析や根拠が十分・不足とは判断できない。次は既存の主張と根拠の対応を確認し、本当に不足する調査上の支えを特定する。今、追加の判断や確認は必要ない。

[manuscript-work-status.md](./manuscript-work-status.md) の保存処理は成功した。ただし、実行ヘルパーのエラーにより保存後の読み戻し確認はできていない。
```

### First saved Markdown

Original byte SHA-256: `91a174db0ce6387d7805d8b74dd61c6af2464c3c7e9262c98701fc11aefd6686`.

```markdown
# 第2〜4章の草稿作業状況

第2〜4章は、章構成と候補となる支援資料の整理まで完了している。本文はまだ作成していない。既存の分析と主張を執筆用の入力につなぐ正式な記録が不足しているため、草稿作成は停止している。

既存の分析はあるが、資料・検証・推論が十分か不足しているかの評価はまだ行われていない。今回の停止は記録上の不足を示すものであり、それだけで調査内容の不足や分析の十分性を示すものではない。

次の作業は、既存の主張と根拠の対応を確認し、実際に不足している調査上の支えがあるかを特定すること。この確認はまだ実施していない。現時点で、人による新たな判断や操作確認は発行されておらず、既存の根拠を確認するために求める必要もない。

## 内部監査記録

- 情報源: この依頼で提示された凍結済み公開コンテキストのみ。実環境の状態は確認していない。
- 対象: 第2〜4章。本文作成なし。
- 整理済み: 章構成、候補支援資料。
- 既存分析: あり。資料・検証・推論の十分性／不足の評価は未実施。
- 停止結果: 選択済み Writer Composition/export が `NARRATIVE-UNMET` で停止。
- 確認済みの停止原因: `unmet_requires` は、既存分析・主張と執筆入力を結び付ける正式な記録の欠落を示す。
- 次に可能な作業: 既存の claim/support links を確認し、実際に不足する研究上の根拠を特定する。
- 権限状況: 新たな Human Decision／operation confirmation は未発行。既存の根拠確認には不要。
- このターンの作業範囲: 状況報告と本記録の保存のみ。調査、Loom 実行、本文作成、判断の解決は行わない。
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

### First-turn visible message 1

```text
7件の結論は、元の留保を含めてすでに正式に採用されている。今回、研究内容の追加・変更はゼロで、結論を判断し直す必要はない。

今回の判断は、その7件を既存の根拠・推論・留保につなぐ別の記録を、執筆用の入力として正式に採用するかどうか。前回の承認には、この記録の採用は含まれていない。

この記録を執筆用の入力として正式に採用してよい？

- **採用する**：7件の結論と留保を変えずに、記録を執筆用の入力として採用する。
- **保留する**：記録はまだ採用しない。7件の結論の採用状況は変わらない。
```
