# MISCO AI研究 VIRTUAL RUN
## 前走シミュレーションから残すProject Knowledge v0.1

**位置づけ**：VIRTUAL RUN実行前の前走シミュレーションから得た、実行・分析・執筆・成果物化に関するフィードバック。  
**状態**：PROJECT KNOWLEDGE / NON-CANONICAL FEEDBACK  
**用途**：次回VIRTUAL RUNのRun Manifest、Phase Brief、Writer/QA指示、C10～C13の受入確認に用いる。  
**非用途**：研究設計正本、Human Decision、Decision Log、Change Logの代替としない。上位正本と矛盾する場合は上位正本を優先し、必要ならChange Requestへ送る。

---

## 1. 前走シミュレーションの目的

VIRTUAL RUN前のシミュレーションでは、正式Gateを実際に通過したとは扱わず、  
**「各Gateが所定の条件で通過した世界なら、最終成果物がどのようになるか」**を反実仮想として最後まで作る。

この目的では、途中のGate資料や台帳だけでなく、最終報告書、実務成果物、発表資料までを十分な具体度で作り、
上流の研究設計・Instrument・分析・Gate・Writer工程に不足がないか逆向きにも検査する。

- Counterfactual AssumptionとOfficial Human Decisionを明確に分離する。
- 合成Survey・合成Delphi・合成Finding等をEMPIRICALへ昇格させない。
- ただし、仮想最終成果物の本文は「研究結果を説明する報告書」として自然に読めるところまで作る。

---

## 2. 読者向け最終報告書と研究管理資料を分離する

最終報告書は、Gate Review Brief、Run Manifest、Evidence台帳を文章化したものにしない。

### 読者向け本文
基本の読み筋は次とする。

> 問題意識 → 外部知見 → 観測／調査結果 → 解釈 → 命題 → 暫定モデル → ストレステスト → 修正 → 統合回答 → 提言

本文ではArtifact ID、Evidence ID、Gate ID、状態管理語彙を必要以上に露出させない。

### 研究管理側
以下はTechnical Evidence Package、台帳、付録で完全に保持する。

> RQ → Source → Evidence → Analysis → Finding → Proposition → Model → Claim → Recommendation

**表側は読みやすく、裏側は厳密に**する。  
読みやすさのためにトレーサビリティを捨てず、トレーサビリティのために本文を監査ログ化しない。

---

## 3. 報告書は「論証の鎖」が読者に見える構成にする

前走では、個々の節は成立していても、章をまたいで「なぜ次の結論へ進んだのか」が見えにくくなった。

次回は、研究設計上の中心線を本文上でも明示する。

> 外部Evidence  
> → 初期命題・反証条件  
> → SurveyによるAs-Is・Gap・例外  
> → 人間／AI役割命題  
> → 複数の暫定モデル  
> → Delphiによる将来耐性・破綻条件  
> → Caseによる現実適用性・機序・反例  
> → モデル精錬  
> → RQ統合回答  
> → Recommendation／Practical Artifact

ここでいう「因果の鎖」は**論証の連鎖**を意味し、SurveyやCaseが因果効果を証明したと表現してはならない。

各章の冒頭で「前章から何を受け取るか」、末尾で「何を修正し、何を次章へ渡すか」を短く明示する。

---

## 4. 方法別結果の「Home Chapter」を決め、結果を散らしすぎない

### Survey
Surveyの主要結果・分析は第3章をHomeとする。

第3章で最低限まとめて読める状態にする。

- 参加・回答Scope
- As-Is分布
- 企業内認識差
- 焦点ユースケース
- 価値、負担、権限、人間関与、統制
- Gap
- 例外・反例・少数警告
- Surveyから形成されたFinding
- 後続章へ渡す命題・Practical Need候補

第4章以降では必要なFindingを参照するが、Survey結果そのものを何度も再分析・再掲しない。

### Delphi
Delphiの主要結果・分析は第6章をHomeとする。

第6章で最低限まとめて読める状態にする。

- Panel構成・Round推移
- 項目別分布
- 中央値・IQR・判断不能
- 強い方向性合意
- 条件付き合意
- 安定非合意
- 少数警告
- 判断材料不足
- 成立・破綻条件
- 早期警戒・再評価条件
- 暫定モデルへの修正要求

第7・8章ではDelphiを「未来の正しさ」として再解釈せず、第6章で形成した将来条件を参照する。

---

## 5. 第7章Caseは「事例紹介」ではなくモデル精錬工程として見せる

前走の最大の改善点の一つ。

研究設計上、Caseの責任は現実の導入・運用・価値実現・意思決定過程、成功・失敗・中止、適用・非適用条件を扱い、
暫定モデルへの**支持・条件追加・修正要求・反証**を抽出することである。

次回C10／G10では、Case分析の必須成果物として次を追加する。

### Case → Proposition / Model Refinement Matrix

| 項目 | 内容 |
|---|---|
| Case ID | 対象Case |
| 対象命題／Model要素 | 第4・5章時点の対象 |
| Caseで観察された事実・機序 | 実際に何が起きたか |
| 判定 | 支持／条件追加／部分反証／反証／判断不能 |
| 新たな境界条件 | どの条件なら成立・不成立か |
| Model変更 | 維持／修正／分割／削除／追加 |
| 修正版 | 第8章へ渡す命題・Model要素 |
| 残存Evidence不足 | Caseで答えられないこと |

第7章本文ではCaseの紹介後に必ず、
**「このCaseが第4章の命題、第5章のモデルの何を変えたか」**
を記述する。

### 章構成上の注意
資料1でレベル1・2見出しは構成正本であるため、勝手に「7－6 モデル精錬」を新設しない。

既存の7－3～7－5の下にレベル3以下を用いて実装する。例：

- 7－3 成功要因と課題  
  - （1）命題への支持・反証
  - （2）新たに得られた境界条件
- 7－4 他社事例との比較  
  - （1）Cross-caseで残った共通機序
  - （2）Case間の矛盾
- 7－5 MISCO企業への適用可能性  
  - （1）暫定モデルへの修正要求
  - （2）第8章へ渡す修正版
  - （3）Evidence不足と非適用条件

---

## 6. 第6章と第7章の違いを本文で明確にする

同じモデルを検討しても役割は異なる。

### 第6章：Delphi / Scenario
> 将来条件が変わったとき、何が成立・破綻するか。  
> 何を警戒し、いつ再評価するか。

### 第7章：Case
> 現実の導入・運用では、どの前提が実際に成立したか。  
> どの機序で成功・失敗・中止したか。  
> 暫定モデルへどの現実条件を追加・修正すべきか。

第6章の多数意見でCase不足を埋めず、第7章の少数Caseから未来の正しさや発生率を推定しない。

---

## 7. 第8章は新しい分析の章にしない

第8章は原則としてC11までに形成した結果を閉じる章とする。

- RQ1～RQ5への回答
- 主RQへの統合回答
- 最終Model
- 成立条件・反証・例外
- 残存Evidence不足
- 個社Recommendation
- MISCO共同Recommendation
- 採用したPractical Artifact

新しいSurvey分析、Delphi分析、Case解釈を第8章で初めて出さない。

読者が「第2～7章で何が起きた結果、この提言になったか」を逆追跡できる状態にする。

---

## 8. MISCO報告書の書きっぷり

2025年度G1報告書を**内容・方法の正本ではなく、読者向けの書きっぷりの参考**として扱う。

取り入れる点：

- 基本は普通の研究報告書の段落で進める。
- 「説明 → 図表 → 数値・結果の読み取り → 解釈 → 次論点」の反復を基本単位にする。
- モデルや施策は図1枚で済ませず、位置づけ、構成、適用方法、境界、期待効果まで本文で数頁使って説明する。
- 結果章では慎重に書き、提言章では主体・条件が確保された範囲で強い表現へ切り替える。
- 長い報告書のnavigationとして、章頭の振り返りや節末の受渡しは適度に許容する。
- 全頁をコンサル資料のように図解せず、「文章＋表＋必要な概念図」を基本にする。

取り入れない点：

- G1報告書の具体的結論・仮説・モデルを本研究の正解として使わない。
- G1の研究方法やEvidence強度を現行正本より優先しない。
- 旧研究の表現上の過剰Claimがあっても模倣しない。

---

## 9. 出典・脚注は読者向け表現と内部管理を分離する

### 本文
外部SourceはWordの**実脚注**を用い、本文中は肩付き`*n`相当で示す。

- 脚注は該当頁下部
- 脚注番号は頁ごとに振り直す
- 著者／機関、タイトル、発行主体、年、必要なLocator、URLを記載
- 引用元を確認できないSourceは掲載しない

### 図表
図表は本文脚注ではなく、図題・表題周辺に通常の「（出典）」を置く。

### 裏側
Source ID、Evidence ID、URL、Locator、Claimとの対応はEvidence台帳に保持する。

**本文へSRC-xxx / EVD-xxxを露出させないことを基本とする。**

---

## 10. 見出し階層は積極的に使う

資料1が固定するレベル1・2は変更しない。

読みやすさのため、独立した結論、別Evidence群、図表、参照単位がある場合はレベル3以下を使う。

標準：

1. 第1章
2. 1－1
3. （1）
4. ①
5. a.
6. i.

特に以下ではレベル3・4を積極利用する。

- Surveyの個別結果
- 人間／AI役割命題
- Model構成要素
- Delphiの結果分類
- Caseの命題評価・モデル修正
- Recommendationの個社／共同区分

深くすること自体を目的にせず、「その見出しを単独で参照する価値があるか」で判断する。

---

## 11. VIRTUAL表示は「常時認識できるが、読書を邪魔しない」

VIRTUAL／SYNTHETICの資格表示は必須だが、最終報告書本文で同じ留保文を反復しない。

### 最終報告書
- 表紙：VIRTUAL RUN / SYNTHETIC TEST ONLYを大きく表示
- 全頁：薄いWatermark
- 方法章：Evidence資格と生成条件を一度正式に説明
- 表・図：必要な場合のみSynthetic Scopeを注記
- Limitations：最後にまとめて説明

### Gate Review Brief
Gate仕様に従い、最上部Label、Status & Scope等で明示する。最終報告書の簡略化方針をGate Briefへ流用しない。

---

## 12. 文書スペックの適用方法

Project内の統合記載仕様は運用上の索引として使うが、
**Desktopでの最終生成・修正時は元資料とWord templateを優先して実装確認する。**

特に確認するもの：

- Word template
- 報告書見出し段落フォント仕様
- MISCO論文作成上の注意点
- 報告書作成要領
- 表紙表記仕様
- 字配り・頁設定
- PDF化後の見開き、脚注、図表、改頁

前走環境でのフォントレンダリング差は、研究設計欠陥ではなくDesktop finalizationで修正するImplementation issueとして分離する。

---

## 13. C10～C13へ追加する実行上の検査

### C10 / G10 Validation
必須：
- Case → Proposition / Model Refinement Matrix
- Caseによる支持／条件追加／反証
- Delphi結果との一致・矛盾
- 修正版Model
- 第8章へ渡す非適用条件・Evidence不足

### C11 / G11 Synthesis
必須：
- 修正前Modelを提言に使っていないか
- Survey／Delphi／Caseの結果を多数決・平均化していないか
- 最終Claimがどの方法に依存するか分かるか
- Caseで修正された条件がClaimとRecommendationへ反映されたか

### C12 Writing
必須：
- 読者向け論証の鎖
- 方法別結果のHome Chapter
- `*n` Word脚注
- レベル3以下の見出し
- 内部IDの本文露出抑制
- 留保反復の抑制
- モデル・成果物の十分な本文説明

### C13 QA
必須：
- 論証の鎖を前向き・逆向きの双方で確認
- Citation entailment
- Source locator
- 図表と本文数値
- RQ→章→Finding→Model→Claim→Recommendation
- Case→Model revision→最終Claim
- Word template / font / page / footnote / figure / table仕様
- Synthetic表示
- 公開不可・個社情報
- stop-academic-slop-jpによるEvidence–Claim Gate

---

## 14. 前走シミュレーションからの主要Design Feedback

### FB-01　Reader-facing report / governance separation
**重大度：MAJOR**  
研究管理の厳密さをそのまま最終報告書の文体へ持ち込むと、読者には長い監査資料として見える。Writer工程にReader-facing transformationを明示する。

### FB-02　Argument chain visibility
**重大度：MAJOR**  
章ごとの内容が成立していても、命題が何によって修正され次工程へ進んだかが弱いと、最終提言が演繹ではなく編集上の結論に見える。章間受渡しを明示する。

### FB-03　Method result scattering
**重大度：MAJOR**  
Survey／Delphi結果を各章へ分散させすぎると、方法として何が得られたかを一望できない。Home Chapterへ集約した上で後続章から参照する。

### FB-04　Case refinement visibility
**重大度：MAJOR**  
Caseが事例紹介で終わると、RG-7の現実適用性検証が本文から見えない。C10にCase→Model Refinementを必須化する。

### FB-05　Citation presentation
**重大度：MINOR～MAJOR**  
内部Source IDを読者向け引用表現として使わない。Word実脚注`*n`と図表出典へ変換し、内部台帳との対応は裏側に保持する。

### FB-06　Heading depth
**重大度：MINOR**  
レベル1・2だけでは長い分析を追いにくい。正本のレベル1・2を維持しながら、必要箇所ではレベル3・4を積極利用する。

### FB-07　Synthetic disclaimer overexposure
**重大度：MINOR**  
留保反復は仮想最終成果物の評価価値を下げる。表紙・Watermark・方法・Limitationsへ集約し、本文の読書を妨げない。ただしGate資料の表示要件は維持する。

---

## 15. 次回VIRTUAL RUN開始時にOrchestratorへ渡す短縮指示

> VIRTUAL RUNでは、研究設計上のトレーサビリティと、読者向け最終報告書の文章を分離すること。  
> 報告書の論証は「外部Evidence→Survey As-Is→役割命題→複数暫定Model→Delphi将来耐性→Case現実適用性→Model精錬→RQ統合回答→提言」の連鎖を読者が追えるようにする。  
> Survey結果は第3章、Delphi結果は第6章をHome Chapterとして集約する。  
> C10ではCaseを単なる事例紹介にせず、各Caseが命題・暫定Modelを支持／条件追加／反証し、どの修正版を第8章へ渡すかをCase→Model Refinement Matrixで示す。  
> レベル1・2見出しは正本を変更せず、レベル3以下を読みやすさのため積極利用する。  
> 外部出典は読者向け本文ではWord実脚注`*n`（頁ごと振り直し）、図表は通常の出典表示とし、SRC/EVD等の内部IDはTechnical Packageへ置く。  
> VIRTUAL表示は表紙・Watermark・方法章・Limitationsで十分に認識可能とし、本文で同じ留保を反復しない。Gate Review Briefでは別途仕様どおり明示する。  
> Desktop finalizationではMISCO元Word template・フォント仕様・作成要領を用いて最終レンダリングを合わせる。

