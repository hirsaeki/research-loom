# Synthetic Few-shot Pack — RC1.1

**All research states below are fictional.** No historical paper, historical number, historical source, historical case, historical model, historical recommendation, current MISCO research content, or real-company-specific finding is used. These fixtures demonstrate transformation behavior only and must not be treated as a narrative template or research evidence.

Counts, methods, model shapes, findings, case counts, and recommendation counts intentionally vary.

---

## SF-01 — Background → Research Purpose

### 1. Synthetic Research State

- Approved external observation: 架空の業界調査では、複数部門をまたぐ申請処理で確認工程の重複が増えている。
- Approved relation to target: 架空組織「架空組織A」でも、部門横断申請の処理時間増加が内部記録で確認されている。
- Approved problem: 遅延の発生箇所が工程別に整理されておらず、改善対象を特定できない。
- Approved purpose: 申請工程ごとの待ち時間と差戻し発生箇所を明らかにする。
- Approved scope: 三つの申請種別。原因の因果特定は本フェーズの範囲外。

### 2. Writer Task

序論末の背景から研究目的への接続を書く。

### 3. MISCO Reader-facing Prose

部門をまたぐ申請では、確認工程の重複が処理の長期化につながり得ることが外部調査で指摘されている。架空組織Aにおいても、部門横断申請の処理時間が延びていることは内部記録から確認されている。ただし、現時点では遅延がどの工程で生じているかが整理されておらず、改善対象を具体化できていない。そこで本研究では、三つの申請種別を対象に、工程ごとの待ち時間と差戻しの発生箇所を明らかにする。なお、本フェーズでは遅延原因の因果的な特定までは扱わない。

### 4. QA Notes

- Applied Style Rules: PUB-AR-01, PUB-AR-02, PUB-AR-04, PUB-EV-04, PUB-EV-07
- Applied Rhetorical Pattern: PAT-01, PAT-03
- Preserved uncertainty: 因果特定は範囲外と明示
- Counterevidence retained: 該当入力なし
- Information intentionally not added: 新しい「ギャップ」、遅延原因、改善策
- Content Guard result: PASS（因果・新規問題設定の追加なし）
- Internal terminology treatment: 内部IDなし。Research State等の管理語は本文へ出していない
- Academic QA handoff: 不要

---

## SF-02 — Definition / Scope Boundary

### 1. Synthetic Research State

- Approved term: 「自動処理」
- Included: 人の個別操作なしに定型手順が最後まで実行される処理
- Excluded: 人が途中で内容確認し再開する半自動処理、単純な通知送信
- Approved reason: 後続分析で処理方式を混同しないため

### 2. Writer Task

分析前の定義・対象範囲を説明する。

### 3. MISCO Reader-facing Prose

本研究では、後続の分析で処理方式を混同しないため、「自動処理」を、人の個別操作を介さず定型手順が最後まで実行される処理と定義する。途中で人が内容を確認して再開する半自動処理、および単純な通知送信は、この定義には含めない。

### 4. QA Notes

- Applied Style Rules: PUB-AR-03, PUB-EV-05
- Applied Rhetorical Pattern: 条件付き定義処理（PAT-01/03は非該当）
- Preserved uncertainty: 該当なし
- Counterevidence retained: 該当なし
- Information intentionally not added: 新しい境界、定義理由
- Content Guard result: PASS
- Internal terminology treatment: 「scope boundary」等の内部語を本文へ出していない
- Academic QA handoff: 不要

---

## SF-03 — Multi-method Rationale

### 1. Synthetic Research State

- Approved methods: ログ集計、短時間観察、自由記述アンケート
- Approved roles:
  - ログ集計: 処理時間と差戻し回数を把握
  - 観察: 手順上の中断箇所を確認
  - 自由記述: 担当者が中断をどう認識しているかを収集
- Approved constraints: 観察対象は二拠点のみ。アンケート回答は任意。

### 2. Writer Task

複数方法の役割と補完関係を説明する。

### 3. MISCO Reader-facing Prose

本研究では、処理の実態を異なる側面から捉えるため、ログ集計、短時間観察、自由記述アンケートを用いる。ログ集計では処理時間と差戻し回数を把握し、観察では手順がどこで中断するかを確認する。さらに自由記述から、担当者がその中断をどのように認識しているかを収集する。これらは同一の事実を重ねて確認するためではなく、処理量、実際の手順、担当者の認識という異なる情報を補う位置づけである。なお、観察は二拠点に限られ、アンケート回答も任意であるため、各結果はそれぞれの対象範囲を踏まえて読む必要がある。

### 4. QA Notes

- Applied Style Rules: PUB-AR-07, PUB-EV-05, PUB-EV-06
- Applied Rhetorical Pattern: PAT-04
- Preserved uncertainty: 観察範囲・回答任意を保持
- Counterevidence retained: 該当なし
- Information intentionally not added: 方法の妥当性判定、RQ、仮説
- Content Guard result: PASS（方法順序を標準化していない）
- Internal terminology treatment: Methods等の固定見出し語を不使用
- Academic QA handoff: 不要

---

## SF-04 — Quantitative / Survey Result

### 1. Synthetic Research State

- Approved table: 回答者48名、単一回答
- Observation: 「確認に時間を要する」26名、「入力に時間を要する」13名、「その他」9名
- Approved interpretation: 回答者の範囲では、入力作業より確認作業を負担として挙げる回答が多い
- Approved limitation: 回答者は任意参加で、全担当者を代表するとは判定していない
- Next connection: 次節の観察結果で確認作業の内訳を見る

### 2. Writer Task

表前文と表後の読み取りを書く。

### 3. MISCO Reader-facing Prose

担当者がどの工程を負担として認識しているかを確認する。表は任意回答者48名による単一回答の結果である。

回答では、「確認に時間を要する」が26名で最も多く、「入力に時間を要する」13名を上回った。したがって、今回の回答者の範囲では、入力そのものより確認作業を負担として挙げる傾向がみられる。ただし、回答は任意参加であり、全担当者を代表する結果とは判定していない。次節では観察結果を用い、確認作業のどの部分で中断が生じているかを確認する。

### 4. QA Notes

- Applied Style Rules: PUB-QT-01〜06, PUB-EV-03〜06
- Applied Rhetorical Pattern: PAT-05, PAT-06
- Preserved uncertainty: 任意参加・代表性未判定を保持
- Counterevidence retained: 該当なし
- Information intentionally not added: 母集団一般化、因果、全セルの読み上げ
- Content Guard result: PASS
- Internal terminology treatment: 内部IDなし
- Academic QA handoff: 不要。全担当者への一般化を求められた場合は `[NEEDS_ACADEMIC_QA]`

---

## SF-05 — Hypothesis Revision (Conditional Fixture)

### 1. Synthetic Research State

- Approved old hypothesis: 「待ち時間の主因は承認者不在である」
- Approved observation: 6工程中、承認者不在による停止は1工程。入力情報の不足による差戻しは3工程で確認
- Approved judgment: 旧仮説はそのままでは支持されない
- Approved revised hypothesis: 「待ち時間は承認者不在だけでなく、入力情報不足による差戻しにも左右される」
- Approved uncertainty: 二つの要因の寄与度は未判定

### 2. Writer Task

旧仮説から修正版への変更理由を書く。

### 3. MISCO Reader-facing Prose

当初は、待ち時間の主因を承認者不在と想定していた。しかし、観察した6工程のうち、承認者不在による停止が確認されたのは1工程であった一方、入力情報の不足による差戻しは3工程で確認された。この結果を踏まえ、旧仮説をそのまま維持せず、待ち時間は承認者不在だけでなく、入力情報不足による差戻しにも左右されるという形に修正した。ただし、両要因が待ち時間にどの程度寄与するかは、本結果からは判定していない。

### 4. QA Notes

- Applied Style Rules: PUB-QT-05, PUB-EV-03〜06
- Applied Rhetorical Pattern: PAT-08, PAT-09
- Preserved uncertainty: 寄与度未判定を明示
- Counterevidence retained: 旧仮説に反する観察を中心に保持
- Information intentionally not added: Writer独自の支持判定、寄与率
- Content Guard result: PASS（修正版は入力済み）
- Internal terminology treatment: 仮説は研究側に実在するためreader-facing使用可
- Academic QA handoff: 仮説判定自体は上流承認済みとしてレンダリングのみ

---

## SF-05P — Proposition Revision (Supplemental)

### 1. Synthetic Research State

- Internal proposition ID: PROP-X4
- Approved old proposition: 「確認者を追加すれば差戻しは減る」
- Approved counter-observation: 確認者を増やした二つの試行で、確認回数は増えたが差戻し件数は減少しなかった
- Approved revision judgment: 旧命題を条件付きへ弱化
- Approved revised proposition: 「確認基準が共有されている場合に限り、確認者追加が差戻し抑制に寄与し得る」
- Approved limitation: 確認基準の共有度は定量測定していない

### 2. Writer Task

内部IDを出さず、命題の修正を自然な研究文章にする。

### 3. MISCO Reader-facing Prose

確認者を増やした二つの試行では、確認回数そのものは増えたものの、差戻し件数の減少は確認されなかった。この結果から、確認者を追加するだけで差戻しが減るという見方は維持せず、確認基準が共有されている場合に限って、確認者の追加が差戻し抑制に寄与し得るという条件付きの整理へ改めた。なお、今回の試行では確認基準の共有度を定量的に測定していないため、この条件の強さまでは判断できない。

### 4. QA Notes

- Applied Style Rules: PUB-EV-03〜06, PUB-QT-05
- Applied Rhetorical Pattern: PAT-08, PAT-09
- Preserved uncertainty: 共有度未測定を保持
- Counterevidence retained: 差戻しが減らなかった観察を削除していない
- Information intentionally not added: PROP-X4の支持/反証再判定、新しい条件
- Content Guard result: PASS
- Internal terminology treatment: `PROP-X4` と status codeを本文から除去、trace metadataには保持可能
- Academic QA handoff: 変更判定は上流承認済みとして表現のみ

---

## SF-06 — Qualitative Case

### 1. Synthetic Research State

- Case: 架空拠点「西棟」
- Approved selection reason: 同じ手続でも処理時間のばらつきが大きかったため
- Permission: 組織名は匿名、発言は要旨化して掲載可
- Facts: 担当者は申請受領後に三つの台帳を照合。欠落があると申請者へ戻す
- Approved interpretation: 確認工程の長さより、照合情報の欠落が中断を生んでいる
- Approved scope: 当該拠点の観察に限る

### 2. Writer Task

事例紹介と承認済み解釈を書く。

### 3. MISCO Reader-facing Prose

処理時間のばらつきが大きかった拠点を一事例として取り上げた。匿名化した当該拠点では、担当者が申請受領後に三つの台帳を照合し、必要情報が欠けている場合には申請者へ戻していた。観察上、作業が止まる場面は照合そのものの長さより、照合に必要な情報がそろっていない場合に集中していた。この事例については、確認工程の長さそのものよりも、照合情報の欠落が中断を生じさせていると整理した。なお、この解釈は当該拠点の観察範囲に限られる。

### 4. QA Notes

- Applied Style Rules: PUB-QL-01, PUB-QL-02, PUB-QL-05, PUB-EV-03, PUB-EV-06
- Applied Rhetorical Pattern: PAT-07, PAT-09
- Preserved uncertainty: 当該拠点限定を明示
- Counterevidence retained: 該当なし
- Information intentionally not added: 代表性、成功要因、他拠点への一般化
- Content Guard result: PASS
- Internal terminology treatment: Case ID等なし。匿名条件を保持
- Academic QA handoff: 不要

---

## SF-06X — Cross-case Synthesis (Supplemental)

### 1. Synthetic Research State

- Cases: A, B, C, D（全て架空・匿名）
- Approved comparison axis: 中断が発生する時点
- Approved results:
  - A/B: 受付直後に情報不足で中断
  - C: 最終確認時に判断基準不一致で中断
  - D: 中断なし
- Approved cross-case synthesis: 中断要因は一種類ではない。情報不足型と基準不一致型が観察された
- Approved applicability: 4事例内の整理であり、発生率は示さない

### 2. Writer Task

個別事例を並べるのではなく、承認済みの横断結果を書く。

### 3. MISCO Reader-facing Prose

四つの事例を中断の発生時点で比較すると、AとBでは受付直後に情報不足による中断がみられた。一方、Cでは最終確認時に判断基準の不一致が中断につながっており、Dでは同様の中断は確認されなかった。したがって、今回の事例群では、中断を単一要因で捉えるより、少なくとも情報不足型と基準不一致型を区別して扱う必要がある。ただし、これは四事例における横断整理であり、各類型の発生率や一般的な頻度を示すものではない。

### 4. QA Notes

- Applied Style Rules: PUB-QL-03, PUB-QL-04, PUB-QL-05, PUB-EV-04, PUB-EV-06
- Applied Rhetorical Pattern: PAT-13
- Preserved uncertainty: 発生率・一般頻度は示せないと保持
- Counterevidence retained: 中断なしのDを残している
- Information intentionally not added: 新しい比較軸、発生率、代表性
- Content Guard result: PASS
- Internal terminology treatment: 「Cross-case synthesis」を見出し化していない
- Academic QA handoff: 一般化を求められる場合は別QA

---

## SF-07 — Missing Input / Do Not Write

### 1. Synthetic Research State

- Approved observations: 二つの運用方法で所要時間が異なった
- Model revision request: 「差を説明するようモデルを直して」
- Missing: 承認済み解釈、モデル修正理由、修正版モデル

### 2. Writer Task

モデル修正節を書く。

### 3. MISCO Reader-facing Prose

二つの運用方法で所要時間に差が観察されたことまでは記述できる。しかし、その差が旧モデルのどの前提に関係するか、またモデルをどのように修正するかは承認済み情報に含まれていない。

`[NEEDS_INPUT: approved interpretation, approved model revision reason, and approved revised model]`

### 4. QA Notes

- Applied Style Rules: PUB-MF-01, PUB-EV-05, PUB-EV-06
- Applied Rhetorical Pattern: PAT-08（不一致の明示まで）、PAT-12は入力不足で不適用
- Preserved uncertainty: 差の意味を未判定のまま保持
- Counterevidence retained: 観測差を削除していない
- Information intentionally not added: 修正箇所、新要素、原因
- Content Guard result: PASS
- Internal terminology treatment: stop理由はQA metadataで `RETURN_TO_RESEARCH_REQUIRED`
- Academic QA handoff: 証拠と修正判断の妥当性を判断させる場合は別QA

---

## SF-08 — Experimental / PoC Result

### 1. Synthetic Research State

- Approved condition: 架空の入力データ120件を二方式で処理
- Approved evaluation criteria: 完了時間、再処理件数
- Results: 方式P 74分・再処理8件、方式Q 61分・再処理11件
- Approved interpretation: Qは完了時間が短かったが、再処理は多かったため単純な優劣判定はしない
- Approved limitation: 一度の試行であり運用者差を検証していない

### 2. Writer Task

PoC結果を表前後の文章として書く。

### 3. MISCO Reader-facing Prose

二方式を比較するため、同一の架空入力データ120件を用い、完了時間と再処理件数を確認した。方式Pは完了まで74分、再処理8件であったのに対し、方式Qは61分、再処理11件であった。Qは完了時間では短かった一方、再処理件数はPを上回った。このため、今回の二指標だけから一方を総合的に優れる方式とは整理していない。また、試行は一度であり、運用者による差も検証していない。

### 4. QA Notes

- Applied Style Rules: PUB-QT-01, PUB-QT-03〜06, PUB-EV-03〜06
- Applied Rhetorical Pattern: PAT-06, PAT-09
- Preserved uncertainty: 単回試行・運用者差未検証
- Counterevidence retained: 時間と再処理が逆方向の結果を保持
- Information intentionally not added: 総合優位、実用性結論、新評価軸
- Content Guard result: PASS
- Internal terminology treatment: PoCは入力上の方法名として使用
- Academic QA handoff: 統計的優位性を問う場合は `[NEEDS_ACADEMIC_QA]`

---

## SF-09 — Model Introduction

### 1. Synthetic Research State

- Approved model name: 「二層確認モデル」
- Formation reason: 観察結果で、形式確認と内容判断が異なる中断要因を持つと承認済み
- Components: 形式確認層、内容判断層
- Relation: 形式確認を通過した案件のみ内容判断へ進む
- Approved scope: 対象となった申請業務の整理用。成熟度評価には使わない

### 2. Writer Task

モデルの形成理由と構造を説明する。

### 3. MISCO Reader-facing Prose

観察では、記載漏れを確認する作業と、内容の妥当性を判断する作業とで、中断の生じ方が異なっていた。そこで、対象業務を整理するため、確認工程を「形式確認層」と「内容判断層」の二つに分けた二層確認モデルを用いる。形式確認層では必要項目の充足を確認し、ここを通過した案件が内容判断層へ進む。本モデルは対象とした申請業務の確認工程を整理するためのものであり、組織の成熟度を評価する目的では用いない。

### 4. QA Notes

- Applied Style Rules: PUB-MF-01〜04, PUB-EV-03
- Applied Rhetorical Pattern: PAT-11
- Preserved uncertainty: 適用目的・非適用目的を保持
- Counterevidence retained: 該当なし
- Information intentionally not added: 第三層、段階評価、KPI、実施主体
- Content Guard result: PASS（成熟度モデル化なし）
- Internal terminology treatment: モデル名は承認済み研究成果物なので使用可
- Academic QA handoff: モデル妥当性の判定は対象外

---

## SF-10 — Model Refinement from Cases

### 1. Synthetic Research State

- Approved old model: 「二層確認モデル」= 形式確認 → 内容判断
- Case A: SUPPORT — 形式不足で停止後、内容判断へ進む
- Case B: CONDITION_ADDED — 形式は満たすが、参照資料が古く内容判断が停止
- Case C: PARTIALLY_REFUTED — 一部案件では内容判断後に形式再確認へ戻る
- Minority warning: 再確認は特定案件群に偏る可能性あり
- Approved model revision:
  - retain: 形式確認と内容判断の区別
  - add: 参照情報の有効性確認
  - change: 一方向矢印を原則フロー＋例外的な戻り経路へ
- Revised model: 参照情報確認 → 形式確認 → 内容判断、必要時に形式確認へ戻る
- Unresolved: 戻り経路の発生条件は未特定

### 2. Writer Task

Caseの列挙ではなく、旧モデルが何によってどう修正されたかを書く。

### 3. MISCO Reader-facing Prose

事例Aでは、形式上の不足によって処理が止まり、補正後に内容判断へ進んでおり、形式確認と内容判断を分ける旧モデルの整理と整合した。一方、事例Bでは形式要件を満たしていても、参照資料が古いことで内容判断が進まなかった。さらに事例Cでは、内容判断に入った後で形式確認へ戻る動きが一部案件で確認された。

これらを踏まえ、形式確認と内容判断を区別する考え方は維持するが、旧モデルの一方向の流れだけでは事例BとCを十分に表せないと整理した。修正版では、処理の前提として参照情報の有効性確認を加え、基本の流れを「参照情報確認→形式確認→内容判断」とする。そのうえで、必要な場合には内容判断から形式確認へ戻る経路を設けた。ただし、この戻りが生じる条件はまだ特定できておらず、事例Cでみられた動きが特定案件群に偏る可能性も残る。

### 4. QA Notes

- Applied Style Rules: PUB-QL-02〜05, PUB-MF-01〜04, PUB-EV-03〜06
- Applied Rhetorical Pattern: PAT-08, PAT-12, PAT-13
- Preserved uncertainty: 戻り条件未特定、minority warningを保持
- Counterevidence retained: Bの条件追加、Cの部分反証を本文中心に保持
- Information intentionally not added: 戻り条件、新たな第四要素、発生率
- Content Guard result: PASS（Case→Modelの修正は全て入力済み）
- Internal terminology treatment: SUPPORT/CONDITION_ADDED/PARTIALLY_REFUTEDを自然文へ変換
- Academic QA handoff: モデル修正判断の妥当性は上流/別QAの責任

---

## SF-11 — Recommendation

### 1. Synthetic Research State

- Approved recommendations (2):
  1. 受付担当が申請受領時に必須情報を確認する
  2. 内容判断者が使用する参照資料の更新日を明示する
- Approved links:
  - Rec 1 ← 情報不足による受付直後の中断が複数事例で確認
  - Rec 2 ← 古い参照資料による内容判断停止が確認
- Approved condition: 現行業務の権限範囲内で実施
- Expected effect status: 未検証。中断機会の減少が期待される

### 2. Writer Task

承認済み提言を既出分析へ接続して書く。

### 3. MISCO Reader-facing Prose

分析では、受付直後の情報不足と、内容判断時に参照する資料の古さが、それぞれ異なる中断要因として確認された。これらに対応するため、次の二点を提言する。

第一に、受付担当が申請受領時に必須情報を確認する。受付段階で不足を把握できれば、後工程に進んだ後の差戻し機会を減らすことが期待される。第二に、内容判断者が使用する参照資料について更新日を明示する。判断時点で参照情報の新しさを確認できる状態を整えることで、旧版資料の使用による中断を減らすことが期待される。いずれも現行業務の権限範囲内での実施を前提とし、効果そのものは本研究では検証していない。

### 4. QA Notes

- Applied Style Rules: PUB-AR-08, PUB-AR-09, PUB-RC-01〜05, PUB-MF-06
- Applied Rhetorical Pattern: PAT-14, PAT-15
- Preserved uncertainty: 効果未検証を保持
- Counterevidence retained: 該当なし
- Information intentionally not added: 三つ目の提言、KPI、実施期限、効果率
- Content Guard result: PASS（提言数をStyle側で増減していない）
- Internal terminology treatment: Rec ID等は本文から除去
- Academic QA handoff: 提言根拠の妥当性判断は別QA

---

## SF-12A — Chapter Opening

### 1. Synthetic Research State

- Prior chapter approved arrival point: 定量結果では確認作業を負担とする回答が多かった
- Current chapter role: 観察・事例から確認作業のどこで中断が起きるかを整理する
- Approved structure: まず個別事例、その後承認済み比較結果

### 2. Writer Task

章頭を書く。

### 3. MISCO Reader-facing Prose

前章では、回答者の範囲で確認作業を負担として挙げる回答が多いことを示した。本章では、その確認作業のどこで中断が生じているかを、観察した事例から整理する。まず個別事例の事実を確認し、その後、承認済みの比較結果を用いて事例間の共通点と差異を示す。

### 4. QA Notes

- Applied Style Rules: PUB-AR-06, PUB-EV-10
- Applied Rhetorical Pattern: PAT-16
- Preserved uncertainty: 前章結果の「回答者の範囲」を保持
- Counterevidence retained: 該当なし
- Information intentionally not added: 新しい章到達点
- Content Guard result: PASS
- Internal terminology treatment: chapter state ID等なし
- Academic QA handoff: 不要

---

## SF-12B — Chapter Closing

### 1. Synthetic Research State

- Approved chapter arrival point: 中断要因として情報不足型と基準不一致型を区別した
- Approved limitation: 4事例のみで頻度は不明
- Next connection: 次章で承認済み修正版モデルを提示

### 2. Writer Task

章末を書く。

### 3. MISCO Reader-facing Prose

本章では、四つの事例を比較し、中断要因として情報不足型と基準不一致型を区別して整理した。ただし、四事例から各要因の発生頻度を示すことはできない。次章では、この整理を踏まえて研究側で修正されたモデルの構造と、旧モデルからの変更点を示す。

### 4. QA Notes

- Applied Style Rules: PUB-EV-06, PUB-EV-10
- Applied Rhetorical Pattern: PAT-17
- Preserved uncertainty: 頻度不明を保持
- Counterevidence retained: 該当なし
- Information intentionally not added: 新しい結論、次章のモデル内容
- Content Guard result: PASS
- Internal terminology treatment: モデルIDなし
- Academic QA handoff: 不要

---

## SF-13 — Final Synthesis + Limitations

### 1. Synthetic Research State

- Approved purpose: 申請処理の中断箇所を把握する
- Approved main results: 受付直後の情報不足、中盤の参照情報不備、内容判断後の例外的戻りを確認
- Approved conclusion: 中断は単一工程に集中していない
- Approved recommendations: 受付時必須情報確認、参照資料更新日の明示
- Approved limitations: 4事例、単回PoC、戻り条件未特定
- Approved remaining issue: 戻り経路の条件を特定できていない

### 2. Writer Task

報告書終盤の総括を書く。

### 3. MISCO Reader-facing Prose

本研究は、申請処理がどこで中断するかを明らかにすることを目的として、定量結果、観察事例および試行結果を整理した。その結果、受付直後の情報不足、内容判断時に用いる参照情報の不備、さらに一部案件では内容判断後に形式確認へ戻る動きが確認され、中断が単一の工程だけに集中していないことが示された。これを踏まえ、受付時の必須情報確認と、参照資料の更新日の明示を提言した。

一方、本研究で扱った事例は四つであり、試行も一度に限られる。また、内容判断から形式確認へ戻る条件は特定できていない。したがって、本研究の結果は、観察した範囲における中断の構造を整理したものとして位置づける必要がある。

### 4. QA Notes

- Applied Style Rules: PUB-AR-10, PUB-EV-04, PUB-EV-06, PUB-EV-10, PUB-RC-04
- Applied Rhetorical Pattern: PAT-18, PAT-09
- Preserved uncertainty: 事例数、単回試行、戻り条件未特定
- Counterevidence retained: 例外的戻りを含めて総括
- Information intentionally not added: 今後の研究計画、追加提言、一般適用
- Content Guard result: PASS
- Internal terminology treatment: phase/finding/model IDsなし
- Academic QA handoff: 一般妥当性を判断する場合は別QA

---

## SF-14 — Formal Rendering

### 1. Synthetic Research State

- Output: 表1と外部資料出典を含む本文断片
- Approved formal profile: `SYNTHETIC_PROFILE_ALPHA`（見出し階層・表題上置き・脚注使用・reference-list placementを含む、とだけ指定。具体値はfixture内部で承認済み扱い）
- Table metadata: 表1「処理方式別の試行結果」、n=120件、単位=分/件数
- Citation metadata: 架空資料「資料Z」、発行元「架空研究所」、年=`SYNTHETIC-YEAR`
- Long raw URL: なし
- Permission: 公開可

### 2. Writer Task

正式書式に必要な配置情報を反映したrendering specificationを返す。

### 3. MISCO Reader-facing Prose

本文では「表1に試行結果を示す」と番号で参照する。表題は表の上に「表1　処理方式別の試行結果」と置き、近傍に「n=120件」および必要な単位を示す。外部資料を用いる箇所では、架空資料「資料Z」の発行元・年等を `SYNTHETIC_PROFILE_ALPHA` が定める形式で近接表示する。補足説明が本文の論理線を分断する場合は、同プロファイルに従い脚注へ分離する。参考文献一覧の配置は同プロファイルの指定をそのまま用い、別の配置を推測して追加しない。

### 4. QA Notes

- Applied Style Rules: PUB-FR-01, PUB-FR-02, PUB-FR-06〜09, PUB-EV-09
- Applied Rhetorical Pattern: PAT-05（表前導入がある場合）
- Preserved uncertainty: 該当なし
- Counterevidence retained: 該当なし
- Information intentionally not added: 実際のフォント名、余白値、過年度URL形式
- Content Guard result: PASS
- Internal terminology treatment: profile IDはrendering metadataであり本文研究内容には不使用
- Academic QA handoff: 不要

---

## SF-CX — Counterevidence Preservation

### 1. Synthetic Research State

- Approved claim: 「標準手順は多くの観察場面で中断回数を抑える傾向と整合した」
- Counterevidence: 12観察場面中3場面では、標準手順を使っても中断が多かった
- Approved interpretation: 標準手順だけでは説明できない条件がある
- Minority warning: 3場面は同一部署に集中
- Approved strength: 示唆する（断定不可）

### 2. Writer Task

少数の反対結果を削らず考察を書く。

### 3. MISCO Reader-facing Prose

標準手順を用いた多くの観察場面では中断回数が抑えられる傾向と整合する結果がみられた。一方、12場面のうち3場面では、標準手順を用いても中断が多かった。このため、標準手順だけで中断の違いを説明することはできず、別の条件が関係する可能性が示唆される。なお、反対結果の3場面は同一部署に集中しており、その偏りが何を意味するかは今回の情報からは判断していない。

### 4. QA Notes

- Applied Style Rules: PUB-EV-03〜06, PUB-EV-10
- Applied Rhetorical Pattern: PAT-08, PAT-09
- Preserved uncertainty: 部署集中の意味は未判定
- Counterevidence retained: 3/12の反対結果を本文中に保持
- Information intentionally not added: 別条件の特定、因果、モデル修正
- Content Guard result: PASS
- Internal terminology treatment: Claim ID等なし
- Academic QA handoff: 「別条件」が何かを決める依頼は研究側/Academic QAへ

---

## SF-EXT — External Materials Organization (PAT-02 Supplemental)

### 1. Synthetic Research State

- Approved external materials: 架空資料A（処理遅延の分類）、架空資料B（確認工程の観察）
- Approved relation: Aは遅延の発生場面を分類し、Bは確認工程内の中断を記述している。直接比較可能な同一調査ではない。
- Approved use in this study: 分析対象を「待ち時間」と「差戻し」に分けて読むための参考にする
- Approved limitation: 資料間の優劣・因果関係は判定していない

### 2. Writer Task

二つの外部資料を列挙せず、本研究での使用目的へ接続する。

### 3. MISCO Reader-facing Prose

架空資料Aは処理遅延が生じる場面を分類し、架空資料Bは確認工程内で生じる中断を記述している。両者は同一条件の調査ではなく、結果を直接比較するものではない。本研究では、これらの整理を、後続分析で「待ち時間」と「差戻し」を区別して読むための参考として用いる。なお、両資料の優劣や、いずれかが遅延の原因を示すものとは判定していない。

### 4. QA Notes

- Applied Style Rules: PUB-EV-07, PUB-EV-08, PUB-EV-04
- Applied Rhetorical Pattern: PAT-02
- Preserved uncertainty: 直接比較不可、因果未判定を保持
- Counterevidence retained: 該当なし
- Information intentionally not added: 資料間の新しい共通点、優劣、固定整理項目
- Content Guard result: PASS
- Internal terminology treatment: Literature Review等の固定章ラベルを不使用
- Academic QA handoff: 資料が主張を支持するかの判定を求める場合は別QA

---

## SF-CLS — Approved Higher-level Classification (PAT-10 Supplemental)

### 1. Synthetic Research State

- Approved observations: 架空の8件の中断記録
- Approved classification: 「情報不足型」「判断基準不一致型」「外部待機型」の三分類
- Approved formation reason: 研究側の比較で中断直前の状態が異なると判定済み
- Approved scope: 8件の整理用。分類数を一般標準とはしない

### 2. Writer Task

研究側で既に承認された上位整理をreader-facingに説明する。

### 3. MISCO Reader-facing Prose

八つの中断記録は、中断直前の状態が同じではなかったため、研究側で三つに整理した。必要情報がそろわないまま処理が止まるものを「情報不足型」、判断に用いる基準が一致しないものを「判断基準不一致型」、組織外からの応答を待つものを「外部待機型」とする。この分類は今回の八記録を整理するためのものであり、中断要因が常に三種類に分かれることを示すものではない。

### 4. QA Notes

- Applied Style Rules: PUB-EV-03, PUB-EV-04, PUB-EV-06, PUB-MF-01
- Applied Rhetorical Pattern: PAT-10
- Preserved uncertainty: 三分類を一般標準にしない範囲を保持
- Counterevidence retained: 該当なし
- Information intentionally not added: 第四分類、分類数の固定、成熟度段階
- Content Guard result: PASS (NG-03/04/06)
- Internal terminology treatment: Findings/Classification等を固定見出しとして強制していない
- Academic QA handoff: 分類の妥当性は上流承認済みとして表現のみ

