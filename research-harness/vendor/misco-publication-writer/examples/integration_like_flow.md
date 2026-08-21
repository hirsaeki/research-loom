# Integration-like Synthetic Flow — Phase Draft → Update → Revision → Delta → Final Editorial → Human Stable Authorization

**Fixture is fully fictional and intentionally independent of any current MISCO research.**

## Initial approved Research State R0

- Publication eligibility: `ELIGIBLE`
- Research state status: `CANDIDATE`
- Candidate question: 「処理中断は受付時点の情報品質だけで説明できるか」
- Target section: 「処理中断の観測結果」
- Primary Exposition Location: Chapter 3
- Legacy alias: `home_chapter_map = Chapter 3` (same value; no conflict)
- Quantitative result: 任意回答40名。22名が「受付後の差戻し」を最も負担と回答。11名は「承認待ち」、7名は「その他」。単一回答。
- Approved interpretation: 回答者範囲では差戻し負担が相対的に多い
- Limitation: 任意回答、全担当者代表性は未判定
- Case A/B: 受付情報不足で差戻し
- Approved provisional model: 「受付品質 → 後工程の中断」の一方向整理
- Publication status authorization: stable=false, final=false

## Step 1 — Phase Draft (R0)

### Output

本節では、現時点の問い候補として、処理中断を受付時点の情報品質だけで説明できるかを検討するための観測結果を整理する。この問いは研究上の最終確定事項ではなく、後続の検討により修正され得る。

回答者40名のうち22名が「受付後の差戻し」を最も負担と回答し、「承認待ち」の11名を上回った。この結果から、今回の回答者の範囲では、後工程での差戻しを負担として挙げる回答が相対的に多い。ただし、回答は任意であり、全担当者を代表するものとは判定していない。

事例AとBでは、受付時に必要情報が不足していた案件が後工程から戻されていた。これらの観察を踏まえ、この時点では、受付品質と後工程の中断の関係を整理するため、一方向の暫定モデルを置く。これは現時点の承認済み暫定整理であり、後続事例による修正可能性を残す。

`Publication Status: PROVISIONAL`

## Later approved Research Update R1

- Publication eligibility: `ELIGIBLE`
- Research state status: `REFINED`
- New Case C: 受付情報は充足していたが、判断基準が部署間で一致せず中断
- New Case D: 内容判断後に追加確認が必要となり受付確認へ戻った
- Approved counterevidence effect: old one-direction model is insufficient
- Approved revised model:
  - retain: 受付品質は一要因
  - add: 判断基準整合
  - change: 一方向から、原則順方向＋例外的戻り経路へ
- Approved minority warning: 戻り経路はDの一部案件のみ
- Unresolved: 戻り条件未特定
- New approved recommendation: 判断基準の参照版を明示する
- Supplied downstream trace:
  - Ch3 result section: add C/D and weaken single-factor wording
  - Ch4 model section: replace old model with revised model
  - Ch5 recommendation section: add approved recommendation tied to Case C
  - Executive summary: replace model summary; add recommendation only after Ch5 is revised

## Step 2 — Revision

### Revised output excerpt

受付情報の不足は事例AとBで差戻しに結びついていた一方、事例Cでは受付情報がそろっていても、判断基準が部署間で一致しないため処理が止まった。また事例Dでは、内容判断に入った後で追加確認が必要となり、受付確認へ戻る動きが一部案件でみられた。したがって、受付品質だけで後工程の中断を説明する一方向の整理は維持しない。

修正版では、受付品質を引き続き一要因として残しつつ、判断基準の整合を加える。また、処理は原則として前へ進むものの、必要時には後工程から確認工程へ戻る経路を含む構造へ改める。ただし、この戻りが生じる条件は特定できておらず、観察も事例Dの一部案件に限られる。

`Publication Status: REVISED`

## Step 3 — Manuscript Delta

| Affected area | What changed | Why revision is required | Downstream effect |
|---|---|---|---|
| Ch3 result section | 「受付不足が中断要因」から「受付不足に加え基準不一致・戻り経路も観察」へ | Case C/Dが旧単一要因表現と整合しないため | Ch4 model wording must weaken single-factor assumption |
| Ch4 model section | one-direction model → revised model with judgment-criteria element + exceptional return path | approved model revision supplied | Ch5 may cite revised model, but must not re-analyze Ch3 raw results |
| Ch5 recommendation | approved recommendation「判断基準の参照版を明示」追加 | supplied link to Case C / revised model | Executive summary recommendation list/order must be synchronized |
| Executive summary | model summary and recommendation set need update | downstream trace explicitly supplied | update only after Ch4/Ch5 revision is reflected |

No additional downstream impact is inferred beyond the supplied trace.

## Step 4 — Final Editorial without Human Stable authorization

### Integrated output excerpt

定量結果では、任意回答者の範囲で受付後の差戻しを負担として挙げる回答が相対的に多かった。事例分析では、受付情報の不足が差戻しにつながる場面が確認された一方、情報がそろっていても判断基準の不一致で処理が止まる事例や、内容判断後に確認工程へ戻る事例もみられた。これらの結果を受け、受付品質だけを中断要因とする一方向の暫定モデルは修正し、判断基準の整合と例外的な戻り経路を含む構造とした。ただし、戻り経路の発生条件は特定できていない。

この修正版に対応し、受付時の必須情報確認に加え、内容判断で用いる判断基準の参照版を明示することを提言する。後者は、基準不一致によって処理が停止した事例に対応するものである。なお、これらの提言の効果は本fixtureでは検証していない。

`Publication Status: INTEGRATED`

No `STABLE` or `FINAL` is emitted because no Human authorization exists in this step.

## Step 5 — Human Publication Stable Decision

Additional input:

```yaml
publication_status_authorization:
  stable_authorized: true
  final_authorized: false
  decision_id: SYN-HUMAN-STABLE-01
```

The same integrated content may now be labeled:

`Publication Status: STABLE`

`FINAL` remains prohibited because `final_authorized` is false.

## Integration-like QA result

- Publication-eligible `CANDIDATE` can be written without becoming a final RQ: PASS
- Later Research State overrides prior prose: PASS
- Counterevidence preserved: PASS
- Model revision visible: PASS
- Primary Exposition result scattering avoided: PASS (Ch5 refers to approved result/model; no raw survey re-analysis)
- Recommendation trace retained: PASS
- Final Editorial does not restore the elegant but obsolete one-direction narrative: PASS
- Final Editorial without Human Stable authorization emits `INTEGRATED`: PASS
- Explicit Human Stable authorization permits `STABLE` but not `FINAL`: PASS
- Publication draft treated as research evidence: NO
- Publication Feedback treated as research evidence: NO
