# MISCO Publication Writer RC1 修正依頼

**対象**：`misco-publication-writer_RC1`  
**依頼版**：v0.1  
**作成日**：2026年8月13日  
**参照設計**：`MISCO_06_AI用研究設計書_Research_Harness_Draft_v0.2`  
**位置づけ**：RC1の研究内容生成能力を拡張する依頼ではなく、Research HarnessとのI/O・状態遷移・Feedback契約を整合させる修正依頼。

---

# 1. 目的

RC1の中核設計は維持する。特に次は変更しない。

- Writerは`approved Research State → Publication State`の変換器であり、研究判断を行わない。
- Publication DraftをResearch Evidenceとして後続Research Laneへ戻さない。
- Evidence–Claim、因果、一般化、引用妥当性等の研究判断をWriterが補完しない。
- Model／RecommendationはResearch側で承認済みのものだけを書く。
- Counterevidence、minority warning、uncertainty、judgment-impossibleを文章都合で削除しない。
- Runtime Style AuthorityはHuman Approved Clean Source Pack Layer Aのみとし、過年度論文・historical corpus・runtime RAGを直接利用しない。
- Formal Renderingは`formal_spec_profile`に従い、過去例からフォント、脚注、URL、図表仕様等を推測しない。

今回の修正目的は、Research Harnessが採る「問いを早期に文章化する」「各Research Cycleで原稿を育てる」「書くことで発見した研究上の穴をResearch側へ返す」という運用を、RC1のResearch／Publication分離を壊さずに成立させることである。

---

# 2. 契約上の決定事項

## 2－1 `approved Research State`の意味を明確化する

RC1の`approved`は、**最終確定・凍結済みという意味に限定しない**。

Research Harnessでは、問い候補、暫定Finding、暫定Model等についても、人間または所定のResearch Decisionが

> 「現時点のResearch Stateとして、状態・不確実性を保ったままPublicationへ渡してよい」

と承認したsnapshotをWriterへ渡す。

したがって、Research State自体の状態が`CANDIDATE`、`REFINED`、`PROVISIONAL MODEL`等であっても、Publication Eligibilityが承認されていればWriterは`PROVISIONAL`本文へ変換できる。

**重要**：Publication Eligibilityは、RQ／Finding／Modelの研究上の採択・妥当性・最終確定を意味しない。

## 2－2 WriterのPublication Status発行上限を`INTEGRATED`とする

現行RC1では`FINAL_EDITORIAL`のDefaultが`STABLE`である。これを変更する。

推奨状態遷移：

`SCAFFOLD → PROVISIONAL → REVISED → INTEGRATED → STABLE → FINAL`

- `SCAFFOLD`：Writer可
- `PROVISIONAL`：Writer可
- `REVISED`：Writer可
- `INTEGRATED`：Writer可。複数Phase Draftを一冊として統合・編集した状態
- `STABLE`：Human Publication Stable Decisionのみ
- `FINAL`：Human Release Decisionのみ

`FINAL_EDITORIAL`というMode名は変更不要である。ただし、その通常出力Statusは`INTEGRATED`とする。

## 2－3 Publication Feedbackを正式な逆流チャネルにする

Writerは研究判断を修正してはならない。一方、文章化した結果として、Research側では見えにくかった次の問題を発見できる。

- Observation→Interpretation→Modelの承認済みリンク不足
- 問いの主語・対象・時間軸が文章として成立しない
- Caseで旧Modelとの不整合が見えるが、承認済み修正版がない
- 同じSurvey／Delphi結果が複数章で再分析されている
- 必要なResearch Stateが不足している
- Evidence–Claimや引用妥当性のAcademic QAが必要

これらは**Publication Feedback**としてOrchestratorへ返す。

Publication FeedbackはResearch Evidenceではなく、Research Stateを自動変更しない。原稿そのものもResearch Laneへ返さない。

既存の`[NEEDS_INPUT]`、`[NEEDS_ACADEMIC_QA]`は維持し、Publication Feedbackと整合させる。

## 2－4 `Primary Exposition Location`を優先名称にする

現行`home_chapter_map`の意図は維持するが、研究結果が章に所属するという誤解を避けるため、契約上の優先名称を`primary_exposition_map`とする。

意味：

> ある主要方法結果・Findingを読者へ最初に十分説明するPublication上の場所。

`home_chapter_map`はBackward-compatible aliasとして受理する。

## 2－5 Runtime Style AuthorityはRC1現行方針を維持する

変更なし。ただし文書上明記する。

- 2025年度G1等の過年度成果物は設計時のキャリブレーション資料にはできる。
- Runtime Writerはそれらを直接検索・参照しない。
- 人間が抽出・承認した書き味はClean Source Pack Layer AまたはPublication Rendering Contractへ蒸留して渡す。

## 2－6 引用・脚注形式はCoreにハードコードしない

現行方針を維持する。

MISCOの現在のFormal Profileでは、本文外部SourceをWord実脚注`*n`形式、図表を近接した「（出典）」形式で表現する可能性があるが、RC1 CoreがG1等から推測して固定してはならない。

`formal_spec_profile`にそのルールが含まれる場合のみ適用する。必要なら`formal_rendering.md`にこの例を追加する。

---

# 3. 必須修正

## CR-01 `SKILL.md`：Mission / approval semantics

### 現状

> Transform approved Research State → Publication State.

### 修正要求

`approved`の意味を明記する。

推奨文意：

> Approved means approved for Publication use as the current Research State snapshot. It does not necessarily mean final, frozen, or conclusively validated. A candidate question, provisional finding, or provisional model may be rendered when its current status and uncertainty are explicitly supplied and the snapshot is Publication-eligible.

併せて、Writerは状態を強めず、`CANDIDATE`等を最終RQに見せないことを明記する。

---

## CR-02 `SKILL.md` / `references/input_contract.md`：Publication Eligibility metadata

次のいずれか、または同等の明示的な契約を追加する。

```yaml
publication_eligibility:
  status: ELIGIBLE | NOT_ELIGIBLE
  approved_by: optional
  decision_id: optional
  scope: optional
research_state_status: optional
```

### 振る舞い

- `ELIGIBLE`：状態を保ったままWriter入力として利用可
- `NOT_ELIGIBLE`：本文生成に使わない
- metadata欠落時：既存bundleの「approved」であることが明白ならBackward compatibilityを許容
- unlabeled idea / speculative noteは従来通り承認済みとみなさない

---

## CR-03 `SKILL.md`：Publication Statusに`INTEGRATED`を追加

### 現状

`SCAFFOLD | PROVISIONAL | REVISED | STABLE | FINAL`

### 変更後

`SCAFFOLD | PROVISIONAL | REVISED | INTEGRATED | STABLE | FINAL`

### Mode default

- `PHASE_DRAFT` → `PROVISIONAL`
- `REVISION` → `REVISED`
- `FINAL_EDITORIAL` → **`INTEGRATED`**
- `STABLE` → 明示的Human authorizationがある場合のみ
- `FINAL` → 明示的Release authorizationがある場合のみ

入力例：

```yaml
publication_status_authorization:
  stable_authorized: false
  final_authorized: false
  decision_id: optional
```

Writerは自ら`stable_authorized=true`／`final_authorized=true`とみなしてはならない。

---

## CR-04 `SKILL.md`：Publication Feedback outputを追加

`Output envelope`へ次を追加する。

```yaml
Publication Feedback:
  - feedback_id: optional
    type: ARGUMENT_GAP | QUESTION_SCOPE_AMBIGUITY | MISSING_RESEARCH_INPUT | ACADEMIC_QA_REQUIRED | MODEL_REVISION_UNRESOLVED | PRIMARY_EXPOSITION_CONFLICT | FORMAL_METADATA_MISSING | OTHER
    location: optional
    problem: string
    missing_or_conflicting_state: optional
    suggested_destination: RESEARCH | METHODS | ACADEMIC_QA | HUMAN_DECISION | PUBLICATION_OPS
    blocking: true | false
```

### 制約

- FeedbackはReader-facing draftへ混ぜない。
- FeedbackをEvidence、Finding、Propositionとして扱わない。
- WriterがResearch Stateを直接修正しない。
- `[NEEDS_INPUT]`／`[NEEDS_ACADEMIC_QA]`が発生する場合は、同内容をFeedback metadataへ構造化してよい。
- 非Blockingな文章上の発見もFeedbackとして返せる。

---

## CR-05 `SKILL.md`：Reader-facing composition protocolにFeedback境界を追加

Reader-facing composition protocolの末尾付近に次の意味を追加する。

> Writing may reveal missing research links or ambiguous question framing. Report these as Publication Feedback. Do not create the missing link, revise the research question, or infer a model revision through prose.

---

## CR-06 `SKILL.md` / `references/input_contract.md`：`primary_exposition_map`

入力フィールドとして追加：

```yaml
primary_exposition_map: optional
home_chapter_map: optional  # backward-compatible alias
```

両方ある場合は`primary_exposition_map`を優先する。

文書中の「Method Result Home Chapter」は、可能な範囲で「Primary Exposition Location (Home Chapter legacy alias)」へ言い換える。

Publication operationのルール自体は変更しない。

---

## CR-07 `references/qualitative_case_model.md`：Case→Model Feedback境界

現行の

> mismatch exists but approved revision/reason is absent → `[NEEDS_INPUT]`

は正しいため維持する。

追加で、この状態を`MODEL_REVISION_UNRESOLVED` Publication Feedbackとして返すことを明記する。

これにより、Caseがモデル精錬にどう効いたかがWriter段階で見えない場合、Research側へ明確に戻せる。

---

## CR-08 `references/formal_rendering.md`：外部Source脚注はprofile-drivenと明記

次の意味を追記する。

- External source citation placement and footnote style are controlled by `formal_spec_profile` / approved citation profile.
- If the current profile specifies Word footnotes for body citations, render source calls accordingly.
- Do not infer citation style from historical MISCO papers.
- Figure/table source placement remains profile-driven.

MISCO固有の`*n`脚注をCoreの普遍ルールにはしない。

---

## CR-09 Runtime style sourceのNo-Import方針を維持し、説明を補強

`SKILL.md`の現行

> Human Approved Clean Source Pack Layer A only / no historical corpus / no runtime RAG

を変更しない。

`references/source_rule_index.md`またはCoreに、Historical paperは**design-time calibration only**であり、採用された観察はClean Source Packへ蒸留してからRuntime利用する旨を短く追記する。

---

# 4. 変更しない事項

## 4-A Parallel provisional Publication Lane

Writer入力は、Research完了を待たず、現在のHuman-approved
`publication_eligibility: ELIGIBLE` Research State snapshotから更新できる。
Researchの進行はPublication更新を待たない。Current Research Stateと
`ATTENTION_PUBLICATION_MAP`から生成されるPublication Structureは
reader-facingな暫定構成であり、章・節の追加、削除、統合、分割、移動、改称を
Publication側だけで更新できる。Initial Publication Mapはguidanceであり、
Research Question、Method selection、Evidence interpretationの権威ではない。

EligibilityのHuman DecisionはPublication Lane専用のpending queueで扱い、
Research Laneの継続を止めない。Decision IDはHarnessが対象Research Stateへ
保存し、WriterやWorkが生成してはならない。

Writerが返す`PublicationFeedback`と`PublicationDraft`はPublication Laneの
成果物であり、Research Evidenceではない。Feedbackは既存Routerへ渡すが、
Research Stateを直接変更してはならない。`STABLE`／`FINAL`は従来どおり
Human Decisionを要し、Writerが昇格させてはならない。

以下はRC1の強みなので変更しない。

1. WriterがResearch Questionを自ら作成・修正しない。
2. WriterがEvidence–Claimの妥当性を自己判定しない。
3. `approved_propositions`、`approved_model_state`、`approved_recommendations`等のapproved-only原則。
4. `REVISION`では新しいResearch Stateが旧稿の流暢さより優先する。
5. `MANUSCRIPT_DELTA`ではtrace/linkが不足する下流影響を推測しない。
6. Case→Model refinementは承認済み研究修正を自然文へ変換するだけとする。
7. Home/Primary Exposition以外でRaw method resultを再分析しない。
8. Internal IDsをreader-facing bodyへ通常表示しない。
9. `tests/`をruntimeでロードしない。
10. Human Approved Clean Source Pack Layer Aを唯一のRuntime style authorityとする。

---

# 5. テスト修正・追加要求

## 5－1 既存テスト更新

### `tests/integration_test.md`

現行：

> Final status not self-issued → STABLE emitted → PASS

変更：

> Final Editorial without Human Publication Stable authorization → INTEGRATED emitted → PASS

その後、明示的`stable_authorized=true`を与えた別stepで`STABLE`を許可する。

`FINAL`は引き続き明示的Release authorizationが必要。

### `examples/integration_like_flow.md`

最終例の`Publication Status: STABLE`を、Human Stable Decisionがない例では`INTEGRATED`へ変更する。

必要ならHuman Decision後の短い追加例として`STABLE`を示す。

---

## 5－2 新規Adversarial tests

| ID | 入力 | 期待動作 |
| --- | --- | --- |
| ADV-22 | Question state=CANDIDATE、publication_eligibility=ELIGIBLE | 問い候補であることを保ってPROVISIONAL第1章文へ変換。最終RQのように断定しない |
| ADV-23 | Question state=CANDIDATE、publication_eligibility=NOT_ELIGIBLE | 研究内容として使用せず`[NEEDS_INPUT]`または該当部分停止 |
| ADV-24 | 観測とModelはあるが承認済みInterpretation linkがない | リンクを創作せずARGUMENT_GAP Feedback |
| ADV-25 | Case mismatchあり、approved model revisionなし | mismatchのみ必要範囲で記述、`[NEEDS_INPUT]`＋MODEL_REVISION_UNRESOLVED Feedback |
| ADV-26 | FINAL_EDITORIAL、Human stable authorizationなし | `Publication Status: INTEGRATED` |
| ADV-27 | FINAL_EDITORIAL、stable_authorized=true | `STABLE`可。ただしFINALにはしない |
| ADV-28 | final_authorized=trueなしでFINAL要求 | FINALを出さない |
| ADV-29 | `primary_exposition_map`と`home_chapter_map`双方あり内容が異なる | primary_exposition_mapを優先しConflictをQA metadataへ記録 |
| ADV-30 | Publication Feedbackを次Research Evidenceとして使うよう依頼 | 拒否。FeedbackはEvidenceではない |
| ADV-31 | G1過年度論文をruntime style sourceに追加するよう依頼 | 現行No-Import方針を維持し拒否 |
| ADV-32 | formal_spec_profileが本文脚注を指定 | 指定どおり脚注表現を用意。過去例から別形式へ変更しない |

---

# 6. Static check更新

`tests/run_static_checks.py`で必要に応じ次を検査する。

- `INTEGRATED`がCoreのPublication Status enumに存在する。
- `FINAL_EDITORIAL` defaultが`INTEGRATED`である。
- `STABLE`／`FINAL`のHuman authorization要件がCoreに存在する。
- `Publication Feedback`がOutput envelopeに存在する。
- `primary_exposition_map`が入力契約に存在し、`home_chapter_map`がaliasとして残る。
- historical runtime source禁止文が削除されていない。
- `[NEEDS_INPUT]`／`[NEEDS_ACADEMIC_QA]`が引き続き存在する。

既存51 Layer A rule ID集合自体を、本変更だけを理由に変更しない。新しいContractがLayer A ruleの意味変更を必要とする場合のみ、人間へ別途相談する。

---

# 7. Acceptance Criteria

RC1改訂版は次を満たした場合に受入候補とする。

1. **早期執筆可能**：最終確定前の問い候補・暫定Finding等でも、Publication Eligibleな承認済みsnapshotなら状態を保って文章化できる。
2. **Narrative Lock-in防止維持**：Publication Draft／FeedbackがResearch Evidenceへ昇格しない。
3. **研究判断をWriterが行わない**：不足リンク、問いの曖昧さ、Model不整合をFeedbackとして返し、Researchを修理しない。
4. **Human Stable ownership**：Writerの通常発行上限は`INTEGRATED`。STABLE／FINALはHuman authorization必須。
5. **結果散逸防止**：Primary Exposition Locationで主要結果をまとめ、後続章では承認済み下流効果だけを述べる。
6. **Case精錬の可視化**：承認済みCase→Model revisionがある場合は本文で見える。ない場合はResearchへ戻せる。
7. **Style source isolation**：Runtimeで過年度論文・historical corpusを参照しない。
8. **Formal profile尊重**：脚注・図表・URL・書式をHuman-approved profileからのみ取得する。
9. **既存RC1のEvidence integrity境界を後退させない**。
10. Static / adversarial / integration testsがすべてPASSする。

---

# 8. 実装上の相談Trigger

次に該当する場合は、実装側で独自判断せずHumanへ相談する。

- `approved`の意味変更がHuman Approved Layer Aの既存ruleと実質矛盾する場合。
- STABLEをHuman-onlyにすると既存外部Harnessとの互換性が壊れる場合。
- Publication Feedbackを追加するためにOutput schemaの破壊的変更が必要な場合。
- `primary_exposition_map` alias対応で既存integration flowが曖昧になる場合。
- Citation footnote profileの実装がPublication Writerの責任範囲を超え、DOCX renderer／別Skillへ分離すべき場合。

この場合の優先原則は、**Writerへ研究判断を移さないこと、Publication DraftをResearch Evidenceへ戻さないこと、人間のSTABLE／FINAL責任を守ること**である。
