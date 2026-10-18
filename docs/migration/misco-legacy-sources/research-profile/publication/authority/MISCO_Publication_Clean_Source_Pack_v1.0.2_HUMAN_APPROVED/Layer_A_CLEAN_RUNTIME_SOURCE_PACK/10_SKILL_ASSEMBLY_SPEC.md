# 10_SKILL_ASSEMBLY_SPEC

**このファイルは将来のSkill組立仕様であり、Skill prompt本文もFew-shot本文も含まない。**

**Runtime assembly scope:** `Layer_A_CLEAN_RUNTIME_SOURCE_PACK` のみを使用する。`Layer_B_AUDIT_ONLY_PROVENANCE_LEDGER` と `Layer_C_HUMAN_REVIEW_SUPPORT_PACK` は監査・Human Review専用であり、runtimeへ読み込まない。

## 読むSource Pack

1. `02_PUBLICATION_LANE_IO_CONTRACT` — 使ってよい研究入力と不足時の扱い
2. `06_CONTENT_AND_NARRATIVE_GUARDS` — 研究判断を文章側へ持ち込まない禁止条件
3. `01_PUBLICATION_STYLE_CONTRACT` — 採用済みの文章・編集・正式書式ルール
4. `03_RHETORICAL_PATTERN_LIBRARY` — 該当時だけ使う文章パターン
5. `04_PHASE_SPECIFIC_WRITING_RULES` — 出力Phase別の変換範囲
6. `05_TERMINOLOGY_RENDERING_FIREWALL` — reader-facing語彙と内部語彙の分離
7. `07_FORMAL_RENDERING_RULES` — 正式書式の適用
8. `08_EDITORIAL_QA_CHECKLIST` — 出力後の文章・編集の確認項目
9. `09_SYNTHETIC_FEWSHOT_SPECIFICATION` — Human Review後にFew-shotを作る際の仕様だけを参照

## 適用順序

### 1. 入力検証

- 各研究内容が承認済みであることを確認する。
- 依頼された出力に必要な研究要素がない場合、補完せず停止する。
- Human Reviewで正式設定ポリシー（HD-01〜HD-04）は確定済み。必要な正式仕様原本・メタデータ・承認済みURL表示プロファイルがruntime入力としてない場合は `HUMAN_DECISION_REQUIRED` とする。

### 2. 禁止条件を先に固定

- RQ、仮説、モデル、分類、提言等をStyle側から要求しない。
- 件数・段階数・章順を固定しない。
- 新しい解釈・因果・支持判定・研究判断を作らない。

### 3. Pattern selector

- `03_RHETORICAL_PATTERN_LIBRARY` の `APPLIES_WHEN` を評価する。
- 条件を満たすPatternだけを選ぶ。
- 条件を満たさないPatternは**スキップ**し、入力をPatternに合わせて捏造しない。

### 4. Phase writer

- `04_PHASE_SPECIFIC_WRITING_RULES` に従い、入力を読者向けの章・節・段落へ整理する。
- 観測と承認済み解釈、推定、限界を必要に応じて文章上区別する。
- 図表・モデル・提言は存在するときだけ文章化する。

### 5. Terminology renderer

- reader-facing側ではMISCO側の日本語を優先する。
- 内部管理語は本文の必須語彙・見出しにしない。
- 一般的な研究論文の型をMISCO標準として追加しない。

### 6. Formal renderer

- `07_FORMAL_RENDERING_RULES` の正式ソース優先順位に従う。
- HD-01=Aに従い、頁設定・書体・字下げ等は現行正式仕様原本を正本とする。
- HD-02=Aに従い、参考文献一覧の最終配置は現行正式仕様原本の方針を適用する。
- HD-03=Bに従い、長い raw URL は人間承認済み統一URL表示プロファイルでreader-facing表示する。
- 必要な原本・設定・表示プロファイルが入力されていない場合は推測せず `HUMAN_DECISION_REQUIRED`。

### 7. QA

- `08_EDITORIAL_QA_CHECKLIST` を実施する。
- HD-04=Bに従い、カラー図表を使用する場合だけ、承認済みカラー使用条件と白黒表示時の識別性を確認する。
- 根拠と主張の正否・因果の成立は別QAへ送る。

## Stop / return-to-research conditions

`RETURN_TO_RESEARCH_REQUIRED`:
- 必要な研究目的、観測、解釈、モデル構成、提言等が未承認または欠落しており、出力にその内容が必要。
- Writerが分類・モデル・提言・支持判定等を作らないと依頼を満たせない。
- 想定と異なる結果の意味・修正方針が研究側で未承認。

`SEND_TO_EVIDENCE_CLAIM_QA`:
- 根拠が主張を本当に支持するか。
- 因果と言えるか。
- 引用元がどこまで支持しているか。
- 統計的妥当性・一般化の正否を判定する必要がある。

`HUMAN_DECISION_REQUIRED`:
- 現行正式仕様原本、research group type、公開条件、人間承認済みURL表示プロファイル等、Human Reviewで方針確定済みの正式runtime入力が不足している。

## この段階で生成しないもの

- Skill prompt本文
- Synthetic Few-shot本文
- 新しい研究内容
- 過年度研究の具体例・出典・章構成
