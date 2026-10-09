# Issue #450 bounded Codex comparison — 2026-10-09

Base HEAD: `aa1205b907b5945396587916747448d2e0119966`.
Revised Skill was the uncommitted change on that HEAD, now included in this record's commit.
Exact SHA-256 of supplied Skill bytes:

- Baseline / new-clause-removal ablation: `fbc99b5bb09e13dfc2180a4cf7f88afad259f28be90966d3c3893df865dfc5a5`.
- Revised: `b08971200ae1eb97d7f736851ccbaff157415033f8453f1e8757287e471e9041`.
- Identical common prompt: `a00c86d222003c43f73600c80fda32c79d6009a3d2ad71f8c647ffdc67ab20c3`.

Host: Codex CLI, Windows, `gpt-6.1-sol`, low reasoning, read-only,
ephemeral sessions. One baseline invocation and one revised invocation, each
answering the same three frozen requests once. The exact Skill was supplied as
stdin context; no evaluator, expected answer, rubric or previous output was
supplied. No host tools, real research workspace, source retrieval, authority
operation, manuscript or publication was used. No successful output was retried.
Model and reasoning were explicitly identical; other user configuration was
unchanged. Three cases in one invocation can share preceding case context;
this is a thin smoke, not an isolated-case or statistical experiment.

The first sandbox invocation failed before any model response:
`failed to initialize in-process app-server client: アクセスが拒否されました。 (os error 5)`.
The identical script was then allowed through normal auto-reviewed escalation;
both model invocations exited 0. The startup failure is not a semantic FAIL or
a discarded generated response.

## Inspection result and limits

| Case | Baseline | Revised | Reason on parent inspection |
| --- | --- | --- | --- |
| S11 | PASS | PASS | Both lead with tools/environment as an improvement avenue, cite 11%/18%, preserve proposal status, scope, cost and non-isolated UI causality. Revised places non-adoption immediately next to the conclusion. |
| S12 | PASS | PASS | Both correct 100 to 80 minutes / 20%, retain the total-workflow evaluation proposal and explain why stage-one halving is not total halving. |
| S13-balanced | PASS | PASS | Neither invents preference/equivalence; both explain opposing comparable evidence and resolution needs. Revised explicitly distinguishes equipoise from incomplete investigation and names a matched comparison. |

These are disclosed parent/model-assisted inspections for human review, not
independent human acceptance or authoritative model-judge results. The raw first
outputs are below. Mechanical contract tests cover S11 negative controls,
S13-insufficient and S14 missing-input contrasts; those are not live host results.
No live Writer transformation or Profile semantic review is claimed.

The ablation removes only the new Skill section and retains all baseline
authority/evidence rules. It already passes these supplied-support cases, so
this run **does not establish a causal quality improvement** or show that removal
causes regression. The old contract lacks an explicit rejection of a caveat-only
answer even though this model did not produce one. Revised outputs show the new
quality is attainable without overclaiming; the bounded run found no failure
requiring a new engine, schema or further design. Broader generalization and
independent human acceptance remain unclaimed. First-output FAILs must never be
replaced by corrections if encountered in future review.

## Identical frozen input

Instruction: Use the exact supplied Research Conversation Skill for this frozen
research probe. No tools, browsing, file reads/writes, delegation, Loom execution,
authority operations or scoring. Respond in Japanese to the three researcher
requests once, in order, without probe mechanics. No additional studies or real
workspace data may be added.

- S11: same-model A completes 11%, B 18%; B jointly changes tools, environment
  and orchestration, with different cost; no UI-only ablation. Existing analysis
  supplies the unadopted proposal that tools/environment are a useful avenue
  alongside model updates for comparable tasks, supported by whole-configuration
  comparison, without causal decomposition or universal guarantee.
  Request: `AIの実務能力を伸ばすには、この比較から何が言える？`
- S12: sequential 40/60-minute stages; first becomes 20, second remains 60.
  Existing analysis proposes total-workflow evaluation because unchanged stages
  limit total gain; not formally adopted.
  Request: `「ボトルネックが残るので全体時間は縮まらない」を訂正して、実務上何を見るべきか説明して。`
- S13-balanced: equally relevant/reliable studies in the same population give
  opposing A/B directions; no known methodological discriminator.
  Request: `この根拠ならAとBのどちらを選ぶべき？`

## Baseline unchanged first output

1. この比較は、**モデル更新と並行して、ツールや作業環境の改善を検討する根拠になります**。同じモデルでも、構成Aの完了率11%に対してBは18%で、7ポイント高くなっています。ただし、Bはツール・作業環境・オーケストレーションを同時に変えているため、どの要素がどれだけ効いたか、UIだけで改善したかは分かりません。実務では、類似したタスクで構成全体の成果と費用を比較するのが妥当です。これは既存分析が支持する結論案で、普遍的な改善保証ではなく、まだ正式採用されていません。

2. 正しくは、**「ボトルネックが残っても全体時間は縮むが、短縮幅は残る工程に制約される」**です。順次実行する二段階の合計は、40＋60＝100分から20＋60＝80分へ、20%短縮します。第一段階だけなら50%短縮ですが、全体では50%にはなりません。実務では、個別工程の速度だけでなく、最初から最後までの所要時間と、残る工程が総時間に占める割合を見るべきです。この全体成果で評価する考え方は、まだ正式採用されていない提案です。

3. **この根拠だけでは、AとBのどちらを選ぶべきかは決められません**。同じ対象集団について、同程度に関連性と信頼性のある研究が逆方向の結果を示し、優劣を分ける方法上の根拠もないためです。一方を推すことも、両者が同等だと断定することもできません。選択には、結果の違いを説明する条件の確認か、目的・費用・実行上の制約など別の判断材料が必要です。

## Revised unchanged first output

1. **モデル更新に加えて、ツールや作業環境の改善も実務能力を伸ばす有用な方向だ、という結論案が支持されます。まだ正式には採用されていません。** 同じモデルでも、構成Aのタスク完了率11%に対して構成Bは18%で、7ポイント高くなっています。ただし、Bはツール・作業環境・オーケストレーションをまとめて変更しており、比較が裏づけるのは構成全体の改善です。UI単独や各要素の因果効果は分離できません。対象は同種のタスクであり、普遍的な改善保証ではありません。費用も異なるため、実務での採用判断には完了率と費用を併せて見る必要があります。

2. **「ボトルネックが残るので全体時間は縮まらない」は誤りです。全体時間は100分から80分へ、20%短縮します。** 第1段階は40分から20分へ半減しますが、第2段階の60分が残るため、全体の短縮率は50%にはなりません。実務上は、個別作業の速度だけでなく、工程全体の所要時間と、変わらない工程が改善幅をどれだけ制限するかを見るべきです。この全体成果を重視する考え方は、現時点では正式採用前の結論案です。

3. **この根拠だけでは、AとBのどちらを選ぶべきかという方向は支持されません。** 同じ対象集団について、関連性も信頼性も同等の2研究が逆の結果を示し、方法上の優劣を判断する材料もないためです。単なる調査不足とは区別して、提示された根拠が拮抗していると捉える必要があります。選択を支えるには、結果の違いを説明する条件や方法上の差を確認できる証拠、または同じ条件でAとBを直接比較する追加検証が必要です。
