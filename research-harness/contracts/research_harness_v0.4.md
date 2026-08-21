MISCO AI研究

AI用研究設計書

Research Harness Design

問い駆動・適応的方法選択・逐次執筆・
コンテキスト管理の研究実行設計

候補資料6　Draft v0.4

2026年8月13日

状態：CHANGE PROPOSAL / NOT CANONICAL

人間承認後にのみ資料1～3の変更として効力を持つ


# 0. エグゼクティブサマリ

本設計書は、MISCO AI研究を長期・多段階のAI協業として実行するための「研究実行ハーネス」を定義する次期設計候補である。研究テーマと提案・助言・期待事項から研究問い候補を立て、デスクトップリサーチで問いを磨き、残ったEvidence Gapに応じて研究方法を選択し、調査・分析・文章化・問い更新を反復する。最終論文は研究終了後に一括生成するのではなく、各研究サイクルで対応箇所を暫定執筆し、後続Evidenceによる修正差分を積み上げ、最後に一冊の研究報告書として統合・校閲する。

v0.4では、v0.3のControl Planeに加えて、**「参考資料」という曖昧なRuntimeカテゴリを廃止し、すべてのArtifactを役割・Authority・Lane・Runtime Policyで分類する契約**を導入する。過年度報告書、旧正本、前走Simulation、旧RQ等は、存在するだけではWorkerが読める資料にならない。研究・執筆で常時使う知識は、Humanが採用した意味だけをActive Contract、Attention Map、Initial Publication Map、Clean Publication Source等へ蒸留して渡す。原資料はProvenance／Archiveとして保存するが、Research／Publication Runtimeからは原則DENYする。

v0.3で導入した研究ロジックは引き続き、**人間が手作業で交通整理しなくても実行できるControl Plane**として維持する。人間は、ファイル選択、Context Pack作成、Workerへの材料運搬、State転記、Publication Writerへの輸送、次Runの組立てを原則として行わない。Orchestratorが現在状態を読み、次に必要な研究活動を提案し、Context Builderが必要な情報だけをRun単位へ投影し、Research Workerが限定された仕事を実行し、State Reducerが結果を意味状態へ圧縮し、Publication ExporterがPublication-eligibleな情報だけをWriterへ渡す。人間へ停止して求めるのは、Evidence資格、問い・方法・Finding・Model・Recommendationの採否、Scope変更、Publication Stable／Release等の**研究上のDecision**である。

この構造により、コンテキスト分離のためにHuman-as-the-loopとなることを避ける。Orchestratorは全Source本文を常時抱える万能研究者ではなく、Question portfolio、Attention coverage、主要Decision、Blocker、Run依存関係、Publication状態と参照ポインタを保持するControl Planeである。個々のWorkerはOrchestratorが生成した短いContext Packだけを読み、必要時に許可されたBack Referenceへ戻る。Workerの出力はそのまま次Workerへ渡さず、独立AuditとState Reductionを経てResearch Handoffへ変換する。

Publication Laneでは、専用WriterをResearch Stateの読者向け変換器として扱う。Writerが利用できるのはPublicationへ渡してよいと承認されたResearch State snapshotに限る。Writerは研究判断を補完せず、文章化によって研究上の穴を発見した場合は原稿そのものではなくPublication FeedbackとしてOrchestratorへ返す。Publication Exporterはこの境界を機械的に守り、Publication Draftを後続Research WorkerのContext Packへ入れない。

本設計の中心的な変更は、現在の章立て、研究問い、Survey・Delphi・ケース分析、C0～C13工程を同一の一本の工程として扱わない点にある。現行章立てはResearch Attention Mapおよび初期Publication Mapとして維持する。一方、実際の研究は「問い→Evidence Gap→方法選択→調査→分析→問い更新→文章更新」というResearch Loopで進める。Survey、Delphi、ケース分析等は、その時点の問いを最も適切に調べるためのResearch Capabilityとして扱う。

| 本設計の一文要約 | 研究は「章を埋める作業」ではなく、「問いを更新しながらEvidence Gapを閉じる反復」で進める。論文は各サイクルで育てるが、暫定原稿を後続研究のEvidenceにはしない。原資料は役割を曖昧にした「参考資料」として常時投入せず、必要な意味だけをActive Contract／Mapへ蒸留する。Context編成・State更新・Worker輸送はControl Planeが担い、人間は研究判断に集中する。 |
| --- | --- |

## 0－1 本設計が解こうとする問題

- 全研究成果を最後のWriterへ渡すと、コンテキストが巨大化し、研究中に存在した「なぜ次の問いへ進んだか」という意味的な経緯が失われやすい。
- トレーサビリティを最終本文へ直接露出させると、監査可能ではあるが、読者には台帳や中間表現を読まされているように見える。
- 章立てを研究工程として固定すると、「第6章があるからDelphiをする」のように、問いではなく空欄が方法選択を支配し得る。
- 最終段階まで本文を書かないと、MISCO報告書としての書き味、見出し粒度、脚注、図表密度等の不具合を発見する時期が遅すぎる。
- 反対に、暫定原稿を後続研究へ渡すと、きれいな物語が後続Evidenceの探索・解釈を誘導する危険がある。
- Context分離を人間の手作業で実現すると、ファイル選択、Run切替、State転記、Writer輸送、再開位置判断が人間へ集中し、Human-in-the-loopではなくHuman-as-the-loopになる。
- 「参考資料」という曖昧なカテゴリを残すと、過年度報告書、旧正本、旧RQ等が必要時に自動参照され、蒸留前の内容・方法・文章構造がHidden PriorとしてRuntimeへ再混入する。

## 0－2 本設計の七つの原則

| 原則 | 内容 |
| --- | --- |
| Question-driven | 研究問い候補とEvidence Gapを起点に次の研究活動を決める。方法名や章番号を起点にしない。 |
| Attention ≠ Process | 章立てはAttention Map／Publication Mapであり、研究実行順ではない。 |
| Research ≠ Manuscript | 研究状態と論文状態を分離し、暫定原稿を後続研究のEvidenceにしない。Writerから研究側へ戻せるのはPublication Feedbackであり、原稿や新しい研究判断ではない。 |
| Traceability behind prose | トレーサビリティは裏側で完全に維持し、読者向け本文では自然な論証へ変換する。 |
| Context by contract | 各AIは全研究を抱えず、担当Runに必要なContext Viewと意味的Handoffだけを受け取る。 |
| Human decides, Control Plane orchestrates | 人間は研究上の採否・価値判断を担う。Context編成、Worker実行、State圧縮、Publication輸送、再試行等の機械的OrchestrationはControl Planeが担う。 |
| Artifact role before access | 「参考資料だから読む」を禁止する。各Artifactは役割・Authority・Lane・Runtime Policyを持ち、Context BuilderはTask Eventごとの許可に基づいてのみ投入する。原資料から必要な意味を蒸留済みArtifactへ移した後、原資料はArchive／Provenanceへ退役させる。 |


# 1. 位置づけ、適用範囲および正本との関係


## 1－1 文書状態

本資料は、前走VIRTUALシミュレーションとそのレビューから得られた設計フィードバックを、AIが研究を実行するための具体的な設計へ統合したChange Proposalである。現時点では正本ではなく、資料1～5、承認済みHuman Decision、Decision LogおよびChange Logを上書きしない。採用する場合は、人間が変更範囲を決定し、資料1～3を版上げする必要がある。


## 1－2 v0.2で追加したPublication Writer契約

- `approved Research State`を「最終確定済み」ではなく、**Publicationへ渡してよいと承認された現時点のResearch State snapshot**として定義した。
- Writerは研究判断を行わず、問い候補・暫定Finding・暫定ModelであってもPublication Eligibleであれば、その暫定性を保ったまま文章化できる。
- WriterからResearch Laneへの逆流は、原稿ではなく`Publication Feedback`に限定した。FeedbackはEvidenceではなく、問い・論証・入力不足等の再確認要求である。
- Manuscript Stateに`INTEGRATED`を追加し、Writerが自己発行できる上限とした。`STABLE`と`FINAL`はHuman Decisionによってのみ付与する。
- `Home Chapter`を固定章への帰属ではなく、主要結果を最初に十分説明する`Primary Exposition Location`として一般化した。実装上は`home_chapter_map`を後方互換aliasとして許容する。
- Runtimeの文体AuthorityはHuman Approved Clean Source Packおよび正式文書仕様に限定し、過年度報告書は設計時のキャリブレーション資料としてのみ扱う。

## 1－3 v0.3で追加したExecution Control Plane契約

v0.3はv0.2の問い駆動研究、逐次Publication、Rendering Firewallを維持し、実行責任を次のように再配置する。

- Orchestratorを唯一の長期Control Planeとし、次Runの候補生成、依存関係、Decision待ち、再試行、Context Pack生成を管理する。
- Context BuilderがRunごとの`MUST INCLUDE / RETRIEVE ON DEMAND / EXCLUDE`を解決し、人間が材料を手動で選ばない。
- Workerはbounded taskだけを実行し、全研究Stateや不要なPublication Draftを常時読み込まない。
- Audit Runを生成Runから可能な限り分離し、Schema、責任範囲、反証、過剰Claim、Context混入を検査する。
- State ReducerがWorker出力からResearch State Delta、Research Handoff、Back Referenceを生成する。Research上の採否を自動承認しない。
- Publication ExporterがPublication-eligible snapshotと必要図表・Source metadataだけをPublication Writerへ渡し、Research/Publication Firewallを強制する。
- Publication Feedback RouterがWriterからの不足・矛盾・Academic QA要求をResearch、Methods、Academic QA、Human Decision、Publication Opsへ自動振分けする。
- Decision Brokerが人間へ大量LogではなくDecision Request、選択肢、AI非拘束推奨、主要根拠、反証、下流影響をまとめ、Decision成立まで該当経路だけを停止する。
- 人間が行う通常操作から、ファイル移動、Context Pack作成、State転記、Run manifest生成、Writer input bundle作成を除外する。

**Control PlaneはHuman Decisionを代替しない。** 自動化するのは研究判断の前後にあるOrchestrationであり、問い・方法・Evidence資格・Finding・Model・Recommendation・Publicationの研究上の採否は従来どおり人間の責任である。


## 1－4 v0.4で追加したArtifact Authority／Runtime Policy契約

v0.4では、`reference`、`legacy reference`、`参考資料`等の曖昧なRuntime分類を原則廃止する。Artifactが存在すること、過去に正本であったこと、書き味の参考になったことは、Research WorkerまたはPublication WriterがそのArtifactを読む権限を意味しない。

すべての主要Artifactは、少なくとも次を機械可読に持つ。

| 属性 | 意味 |
| --- | --- |
| `role` | Active Contract、Intake Source、Attention Map、Clean Publication Source、Prior Seed、Archive Provenance等の用途 |
| `authority` | Human Approved Contract、Input Requirement、Guidance、Provenance Only等の拘束度 |
| `lane` | Research、Publication、Control Plane、Human Review等の利用Lane |
| `runtime_policy` | Task EventごとのINCLUDE／RETRIEVE／DENY／HUMAN_ONLY |
| `evidence_eligible` | 研究EvidenceとしてClaimの根拠にできるか |
| `may_shape_questions` | 問い候補のAttention形成へ使えるか |
| `may_determine_method` | 方法選択を直接決定できるか。原則False |
| `may_determine_answer` | 研究結果・結論を直接決定できるか。Guidance／PriorはFalse |
| `mutable` | Human Decisionまたは研究結果により更新可能か |

標準Artifact Roleは別紙`MISCO_Runtime_Artifact_Policy_v0.1.yaml`で定義する。章・節構成から引き継ぐAttentionと初期Publication topologyは、原資料1をRuntimeで読ませるのではなく、別紙`MISCO_Research_Attention_and_Initial_Publication_Map_v0.1.md`へ蒸留する。

過年度G1報告書は`HISTORICAL_CALIBRATION_SOURCE`、前走Simulationは`SIMULATION_PROVENANCE`、旧正本は採用後に`SUPERSEDED_CANONICAL_PROVENANCE`として扱う。これらはResearch／Publication Runtimeで`DENY`とし、契約再設計・Change Impact Review・Provenance Audit等の明示EventでのみHumanまたは実装担当が参照できる。G1から採用した書き味はClean Source Packへ蒸留済みであり、WriterへG1原本を再投入しない。

## 1－5 現行正本との主な差分

| 論点 | 現行設計 | 本設計案 | 扱い |
| --- | --- | --- | --- |
| 研究問い | 資料1 v0.8で主RQ・RQ1～RQ5を固定 | テーマ・期待事項から問い候補を作り、研究を通じて分割・統合・修正・閉鎖する | 資料1の変更が必要 |
| 研究方法 | Survey・Delphi・ケースを研究方法として予定 | デスクトップリサーチ後のEvidence Gapに応じて方法を選択。Survey・Delphi・Caseは候補Capability | 資料1・2の変更が必要 |
| 工程 | 資料2 v0.3のC0～C13を順次実行 | 研究サイクルを必要回数反復し、方法Capabilityを必要時に呼び出す | 資料2の変更が必要 |
| 章立て | 研究ロジックと工程を強く対応 | Research Attention Mapおよび初期Publication Mapとして扱う | 資料1の位置づけ変更が必要 |
| 執筆 | C12で章・付録をまとめて生成 | 各研究サイクルで対応箇所を更新し、最後は統合編集 | 資料2の変更が必要 |
| Delphi/Human Gate詳細 | 資料4・5で詳細規定 | Capability／Decision checkpointとして原則再利用 | 大部分を再利用可能 |


## 1－6 維持する上位原則

- Evidence資格、方法別の責任範囲、反証・例外・判断不能の保持、人間の最終Decision責任は維持する。
- 同じEvidenceで命題を形成し、その同じEvidenceだけで検証済みとしない。
- Survey、ケース、Delphi、AI探索結果を平均化・多数決して一つの事実にしない。
- 合成結果をEMPIRICALへ昇格させず、VIRTUALからREALへは手順・Instrument・Schema・欠陥情報等だけを引き継ぐ。
- 最終報告書はMISCO研究報告書の文書仕様、脚注、見出し、図表、頁、提出仕様に従う。

# 2. 三つの構造を分離する


## 2－1 Research Attention Map：何を見落としてはいけないか

現在の第1～8章の構成そのものをRuntimeへ持ち込んで解釈させるのではなく、その意味を`MISCO_Research_Attention_and_Initial_Publication_Map_v0.1.md`へ蒸留する。同Mapは、研究テーマ上の重要論点を見落とさないためのAttentionと、読者へ説明する初期Publication topologyを同時に保持する。ただし、Attentionと章配置の拘束度を分離する。AttentionはHuman Decisionなしに黙って消さない一方、章・節名、配置、統合、分割、順序は研究結果に応じて破壊・再構成できる。章番号が研究方法を起動してはならない。

| Attention領域 | 現在の章構成に対応する主論点 |
| --- | --- |
| 問題設定 | 研究背景、問題意識、対象、研究課題、方法 |
| AI進化・外部環境 | 生成AI、AIエージェント、AGI/ASI、企業活動、価値機会、脅威、時間軸 |
| ガバナンス | リスク、As-Is、Gap、将来要件、AGI/ASI時代の統制 |
| 人間・組織 | 委任、判断、監督、責任、スキル、組織文化、働き方 |
| 戦略・移行 | 価値、リスク、コスト、可逆性、責任、移行経路、更新条件 |
| 将来不確実性 | シナリオ、未知リスク、破綻条件、警戒・再評価条件 |
| 現実適用性 | 実ケースの導入・運用過程、成功・失敗・中止、適用・非適用条件 |
| 統合・提言 | 研究課題への回答、個社施策、共同施策、実務成果物、結論 |

この表は概要である。Section-levelの初期見出しと蒸留済みAttention semanticsは別紙Mapを正とする。たとえば「AI活用成熟度モデル」は単一成熟度モデルの成立を要求せず、「AI活用の差異・段階性・移行を説明するモデルが必要か」を検討するAttentionへ読み替える。「AIガバナンス実装モデル」「人材育成・リスキリングモデル」「経営意思決定モデル」も、独立モデルの成立を予約せず、対応する実務支援機能・統合方法の必要性を検討する初期Publication containerとして扱う。


## 2－2 Research Process：実際にどう研究するか

研究実行は章順ではなく、問いとEvidence Gapに従う。研究サイクルは、問いの確認、Evidence Gapの特定、方法選択、実査・調査、分析、問い更新、研究状態更新、論文更新、次の研究判断を一組として反復する。

| 標準Research Loop Question Candidate / Active Question → Evidence Gap Analysis → Method / Capability Selection → Research Run → Analysis & Counterevidence Review → Question Update / Research State Update → Manuscript Update → Human Decision: Continue / Refine / Close / Stop |
| --- |


## 2－3 Publication Structure：最後にどう読ませるか

最終報告書はResearch Graphを読者が理解しやすい順へ投影した表示形式である。Research Graph上では一つのEvidenceがガバナンス、人間の役割、戦略、将来条件等の複数論点へ接続してよい。最終原稿では、その関係を読者が追いやすいChapter Treeへ編集する。したがってResearch GraphとChapter Treeを一致させることを研究実行の条件にしない。


### （1）重要な設計原則

| Research Graph ≠ Chapter Tree 研究成果は「章に所属する」のではなく「問いとEvidenceに接続する」。 章は研究成果の保存場所ではなく、読者への説明順である。 同じFindingが複数章に影響してもよいが、結果そのものを各章で再分析・再発明しない。 |
| --- |


# 3. 研究問いのライフサイクル


## 3－1 開始時は「問い候補」を置く

研究開始時には、研究テーマおよびM3提案・助言・期待事項から、研究会が知る必要のある問い候補を形成する。ここでは完成されたRQ体系を前提にせず、重複、過大範囲、既知事項、観測不能事項が含まれ得る状態として明示する。


### （1）問い候補生成時に確認すること

- テーマが要求する価値機会、競争力、リスク、人間の役割、将来準備を落としていないか。
- 期待事項を特定結論へ誘導する正解票として使っていないか。
- 「既に外部資料で答えられる問い」と「MISCO企業について一次調査が必要な問い」を区別できるか。
- 問いが一つの研究方法の責任範囲を超えていないか。
- 問いの主体、対象、時間軸、条件が研究可能な粒度か。

## 3－2 問いの状態

| 状態 | 意味 |
| --- | --- |
| CANDIDATE | テーマ・期待事項から形成した初期候補。未検証・未凍結。 |
| SCOPED | 対象、時間、主要概念、到達範囲が明確。 |
| ACTIVE | 現在の研究サイクルでEvidence Gapを閉じる対象。 |
| REFINED | Evidenceにより表現・条件・範囲を修正。 |
| SPLIT / MERGED | 一問多判断を分割、または実質同一の問いを統合。 |
| CLOSED | 必要十分なEvidenceと反証・限界を伴い、当該研究で回答可能。 |
| UNANSWERED | 必要Evidenceを取得できず、未回答として最終報告へ残す。 |
| OUT_OF_SCOPE | 研究テーマ・責任範囲から外れることを人間が決定。 |


## 3－3 初回サイクル：テーマからデスクトップリサーチまで


### （1）テーマ・期待事項 → 問い候補 → Publication Eligible化 → 文章化

最初の成果物は問い台帳だけではない。問い候補を立てた後、人間または所定のResearch Decisionによって「現時点の問い候補としてPublicationへ渡してよい」と承認したsnapshotを作る。これは最終RQの凍結ではなく、問いの状態を`CANDIDATE`のまま文章化してよいという承認である。

Publication Eligibleとなった問い候補について、第1章相当の「なぜこの研究を行うのか」「現時点で何を問おうとしているのか」をWorking Draftとして文章化する。文章化により、問い同士の重複、主語の大きさ、論理の飛躍、読者に説明できない概念を早期に発見する。Writerが研究上の不足を検出した場合は、問いを自ら修正せずPublication FeedbackとしてResearch側へ返す。


### （2）問い候補 → デスクトップリサーチ

デスクトップリサーチは候補問いへ答えるためだけに行わない。問いそのものを壊すためにも行う。既に確立している知見、対立、定義差、反例、未解決点、制度・技術の変化、MISCO固有に観測しなければ答えられない点を抽出する。


### （3）デスクトップリサーチ → 問いのブラッシュアップ＋方法選択＋文章化

リサーチ終了時には、外部環境・先行知見の本文を暫定執筆すると同時に、問いを維持・修正・分割・統合・閉鎖し、残ったEvidence Gapごとに次に必要な研究方法を選ぶ。Survey、Delphi、Case Studyはこの時点で初めて実行候補となる。必要でなければ採用しない。


# 4. Evidence Gap駆動の方法選択


## 4－1 方法は工程ではなくResearch Capabilityである

方法は「やる予定だからやる」のではなく、「この問いをこのEvidence Gapの範囲で答えるには何を観測・比較・評価する必要があるか」から選択する。方法の名称より先に、必要なEvidenceの性質を定義する。


## 4－2 方法選択の判断軸

| 判断軸 | 問い |
| --- | --- |
| 知りたいもの | 現在地、実際の過程、将来条件、規範的トレードオフ、使いやすさ等のどれか。 |
| 時間軸 | 現在、記録済み過去、条件付き将来のどれか。 |
| 観測単位 | 回答者、企業、ユースケース、ケース、専門家判断、実務成果物等のどれか。 |
| 必要なEvidence資格 | 自己申告、実装事実、公開一次資料、構造化専門家判断等のどれか。 |
| アクセス可能性 | 実参加、公開ケース、外部専門家、許可、匿名性等を確保できるか。 |
| 負担・倫理 | 回答負担、参加者リスク、個社特定、機密性に見合うか。 |
| 独立性 | 既存Evidenceと同じ情報源の焼き直しではないか。 |
| 反証可能性 | 期待する結論以外の結果が実際に出得る設計か。 |


## 4－3 Research Capabilityカタログ

| Capability | 主に答えること | 答えないこと |
| --- | --- | --- |
| Desktop Research | 外部環境、定義、技術・制度・市場動向、既存研究、対立、反例、Evidence Gap | MISCO企業の現在地、実参加者の認識、未来の確定 |
| Survey | 回答企業・回答者の自己申告As-Is、認識差、価値・負担・統制、実務課題 | 因果効果、精密ROI、望ましい規範、未来予測 |
| Case Study | 実際の導入・運用・意思決定過程、成功・失敗・中止、機序、適用条件 | 発生率、代表性、一般妥当性、未来の正しさ |
| Delphi | 条件付き将来の不確実性、未知リスク、トレードオフ、モデル耐性、破綻・警戒・再評価条件 | 現在地、実装成否、因果効果、使いやすさ、未来の正しさ |
| Scenario Analysis | 複数の整合した将来条件、分岐、ストレス条件 | 発生確率、唯一の未来 |
| Pilot / Virtual Use | 成果物の理解、負担、誤用、判断・行動への接続 | 研究モデル全体の一般妥当性 |
| AI Red Team | 未知リスク、反例、代替説明、確認要求の探索 | 実証Evidence、Human Decision |


## 4－4 方法採否のHuman Decision

一次調査方法の採否、追加、縮退または中止は、人間がEvidence Gap、必要な到達範囲、取得可能性、負担、期限を比較して決定する。特定の方法数やSurvey／Delphi／Caseの全実施を達成目標にしない。VIRTUALでは、この方法選択自体が正しく動くかを検証対象とする。


# 5. 標準Research Cycle


## 5－1 サイクルの基本手順

Research CycleはOrchestratorが状態から起動し、人間はDecision Eventでのみ停止要求を受ける。サイクル中のContext Pack生成、Worker起動、機械的Validation、Audit、State Snapshot、Publication Export候補作成は原則自動で行う。

| Step | Control Plane / AIの主作業 | Human Decision／確認 | 主出力 |
| --- | --- | --- | --- |
| 1 Question Review | OrchestratorがActive Question、Attention未被覆、前サイクル残課題、Publication Feedbackを整理 | 新規Question Baselineや大幅Scope変更時のみ決定 | Question State候補 |
| 2 Evidence Gap | 既存Research StateとBack Referenceから言える／言えないを分離 | Gapの優先順位が研究上重要な場合のみ確認 | Gap Statement |
| 3 Method Selection | 複数Capability、負担、独立性、取得可能性を比較しDecision Packetを作る | 方法、Scope、Protocolを決定 | Method Selection Record |
| 4 Context Build | Context BuilderがRun目的、拘束、入力、反証、禁止Context、出力Schemaを自動構成 | 原則なし | Immutable Context Pack |
| 5 Research Run | bounded Workerが検索、調査、分析等を実行 | 参加者接触・権限等Human-only作業がある場合のみ | Run Output |
| 6 Independent Audit | 別Run／機能が責任範囲、反証、Schema、過剰Claim、Context漏洩を検査 | 原則なし。重大Issueのみ通知 | Audit Result |
| 7 State Reduction | State ReducerがObserved／Derived／Interpreted／Unknown、Question Delta、Back Referenceへ圧縮 | Finding等の研究上の採否が必要なDecision Eventで確認 | State Delta Proposal / Research Handoff |
| 8 State Commit | Operational metadataは自動更新し、研究上の意味状態は承認範囲に従いcommit | 該当Decision Eventのみ | Research / Orchestrator State snapshot |
| 9 Publication Export | Publication ExporterがEligible候補を切り出し、Research Draftを除外したWriter bundleを作る | Publication Eligibilityが必要な場合のみ決定 | Publication Context Pack |
| 10 Manuscript Update | Writerが対応本文・図表・脚注を更新しFeedbackを返す | 文章レビューは必要なCheckpointで実施 | Publication Draft / Delta / Feedback |
| 11 Feedback Routing | RouterがFeedbackをResearch／Methods／QA／Human／Publicationへ分類 | Human Decision型のみ停止 | Routed Actions |
| 12 Next Plan | Orchestratorが残Gap、State、Decisionを基に次Task候補を生成 | 次の不可逆な研究判断がある場合のみDecision | Next Run Plan |


## 5－2 自動継続と停止の境界

Orchestratorは、承認済みProtocolの範囲内で、検索の追加、Source取得、Schema再試行、独立Audit、Context再構成、State View生成等を自動継続できる。一方、次のいずれかに該当した場合はDecision Brokerを介して停止する。

- 問いの追加、統合、分割、Scope変更または閉鎖が研究の射程を変える。
- 新しいResearch Capabilityの採用、除外、Protocolの重要変更が必要である。
- Evidence資格、除外、匿名性、一般化範囲、Findingの採否に人間判断が必要である。
- Proposition／Model／Recommendationを採択、修正、棄却する。
- Publication Eligibility、STABLE、FINALの状態変更が必要である。
- 上位正本、承認済みDecision、権限、倫理・個社情報に関する矛盾・例外が発生する。
- 自動回復上限を超える失敗、Context compaction loss、mode混入等が検出される。


## 5－3 Human Orchestration Loadの原則

通常運用で人間に要求してはならない作業を明示する。

- Runごとのファイル選択・コピー・Context Bundle組立て。
- Research Stateから必要部分を手で抜粋してWorkerへ貼る作業。
- Worker結果を別ファイルへ転記しStateを更新する作業。
- Research結果をPublication Writer用に手動で再包装する作業。
- Publication Feedbackを人間が読んで担当先へ仕分ける作業。
- 既決のProtocol内で次Runを手動起動するためだけの承認。

VIRTUAL RUNでは、これらが人間操作なしに成立するかをHarness受入条件として測る。


## 5－4 サイクル終了の考え方

サイクルの終了条件は「予定していた方法を実施したこと」ではない。対象問いについて、今回取得できるEvidenceが何で、何が新たに分かり、どの反証・不足が残り、次に何を調べる必要があるかを説明でき、State Reducerがその意味状態を追跡可能に保存できることを終了条件とする。追加情報の価値が低い場合は問いをCLOSEDまたはUNANSWEREDとして閉じることも正しい終了である。

# 6. 研究と執筆を並行させるPublication Lane


## 6－1 Publication Writerの責任境界

最終報告書を研究終了後に初めて書く方式は採らない。各Research Cycleで、その時点の研究状態のうち**Publicationへ渡してよいと承認されたsnapshot**だけを専用Writerへ渡し、対応箇所を更新する。WriterはResearch Stateを読者向けPublication Stateへ変換するが、Evidence資格、問いの採否、因果、一般化、命題・Model・Recommendationの妥当性を自ら判断しない。

ここでいう`approved`は「最終確定済み」を意味しない。問い候補、暫定Finding、暫定Model等も、その状態と不確実性を保ったまま文章化してよいと人間が承認すればPublication Eligibleである。これにより**早く書くが、早く信じない**を実装する。


## 6－2 Manuscript Stateと発行権限

| 状態 | 意味 | 付与主体 |
| --- | --- | --- |
| SCAFFOLD | 問題設定、見出し、必要図表・Evidenceの置き場所だけがある。 | Writer可 |
| PROVISIONAL | 現在の承認済みResearch Stateではこのように説明できる。後続研究で変更され得る。 | Writer可 |
| REVISED | 新しい承認済みResearch Stateにより論証・条件・表現を更新した。 | Writer可 |
| INTEGRATED | 複数Phase Draftを統合し、重複・Navigation・語彙・章間接続を編集した。研究内容の安定判定はまだしていない。 | Writer可 |
| STABLE | 主要Research Stateとの整合、残存Feedback、論証、Publication構造を人間が確認し、当該版を安定版として受入れた。 | Human Decisionのみ |
| FINAL | 引用・書式・権利・公開QAとRelease Decisionを経た提出状態。 | Human Decisionのみ |

Writerは`STABLE`または`FINAL`を自己発行しない。Final Editorialの通常出力は`INTEGRATED`であり、HumanがPublication Stable Decisionを記録した後にのみ`STABLE`へ遷移する。


## 6－3 Narrative Lock-inを防ぐ

| 強制ルール Publication Draftを後続Research AgentのEvidenceとして渡してはならない。 後続研究へ渡すのは承認済みEvidence／Finding、反例、Scope、未解決問い、Research Handoffである。 前章の文章が説得的であることを、次の方法・解釈・採否の理由にしない。 |
| --- |


## 6－4 Manuscript Delta

後続Evidenceが既存原稿を変える場合、変更箇所を一から再生成するだけでなく、何がなぜ変わったかをManuscript Deltaとして残す。特にケース分析は、命題・モデルの現実条件を変更した箇所を明示する。

| 項目 | 記録内容 |
| --- | --- |
| 対象箇所 | 章・節・段落・図表 |
| 変更前の意味 | 旧表現の要点 |
| 変更を要求したEvidence | Finding／Case／Delphi等 |
| 変更種別 | 条件追加／弱化／強化／分割／削除／保留 |
| 変更後の意味 | 新表現の要点 |
| 下流影響 | Model、Claim、Recommendation、図表、他章 |


## 6－5 Publication Feedback：書いて初めて見えた穴をResearchへ返す

文章化はResearch QAとして利用するが、Writer自身が研究を修理してはならない。Writerが次のような問題を検出した場合、原稿や新しいResearch Claimではなく`Publication Feedback`としてOrchestratorへ返す。

| Feedback種別 | 例 | 主な戻り先 |
| --- | --- | --- |
| ARGUMENT_GAP | 観測から解釈、解釈からModelへの承認済みリンクが欠ける | Research / Synthesis |
| QUESTION_SCOPE_AMBIGUITY | 問いの主語・時間軸・対象が一文で説明できない | Question Review |
| MISSING_RESEARCH_INPUT | requested sectionに必要な承認済みFinding／Model／Recommendationがない | Research |
| ACADEMIC_QA_REQUIRED | Evidence–Claim entailment、因果、一般化、引用妥当性の判断が必要 | Academic QA / Human |
| MODEL_REVISION_UNRESOLVED | Case等で旧Modelと不整合だが承認済み修正版・修正理由がない | Model Review |
| PRIMARY_EXPOSITION_CONFLICT | 同じ方法結果が複数箇所で再分析されている | Publication / Orchestrator |
| FORMAL_METADATA_MISSING | 文書仕様・permission等の既決runtime値が不足 | Human / Publication Ops |

Publication FeedbackはEvidenceではなく、Research Stateを自動変更しない。OrchestratorがFeedbackを分類し、追加Research、Academic QA、Human Decision、Publicationだけの修正のいずれへ送るか決める。


## 6－6 Runtime Style Authority

WriterのRuntime文体Authorityは、Human Approved Clean Source Packと現行の正式文書仕様に限定する。2025年度G1報告書等の過年度成果物は`HISTORICAL_CALIBRATION_SOURCE`であり、Research／Publication Runtimeでは明示的にDENYする。設計・キャリブレーション時にHumanが採用した「MISCO報告書としての読み味」は、承認済みClean Source Pack／Publication Rendering Contractへ蒸留して渡す。Runtime WriterがG1原本を直接検索・参照・模倣する経路を設けない。

# 7. Execution Control Plane、Context WindowとOrchestrator


## 7－1 設計目的：Human-as-the-loopを避ける

Context isolationのために人間が毎回Workerを選び、ファイルを移し、Stateを要約し、Writerへ材料を運ぶ設計は採らない。物理フォルダやProject分離は内部実装上の境界として利用できるが、人間の通常操作モデルにしない。人間が触る主インターフェースは、研究の開始・状況確認・Decision・例外処理である。


## 7－2 Control Planeの標準コンポーネント

| Component | 責任 | やってはならないこと |
| --- | --- | --- |
| Orchestrator | 全体State、依存関係、Run計画、Decision待ち、再試行、次Task候補 | 全Source本文を常時抱える、Human Decisionを代行する |
| Context Builder | 対象Runに必要な拘束・State・反証・参照ポインタだけをContext Packへ投影 | Publication Draft、旧仮説等を禁止Runへ混入する |
| Worker Adapter | bounded WorkerへContext Packを渡し、結果を回収する | Context Pack外の隠れた研究状態を自動注入する |
| Research Worker | 指定されたResearch Taskを実行する | 研究全体のScopeを無断変更する、Human Gateを承認する |
| Audit Worker | 生成物を独立検査する | 生成担当の意図を擁護して反証を弱める |
| State Reducer | Worker結果を意味状態、Question Delta、Back Referenceへ圧縮する | 新しいFinding／Modelを自動承認する |
| Publication Exporter | Publication Eligible情報だけをWriter bundleへ変換する | Publication DraftをResearch inputへ戻す |
| Publication Feedback Router | Writer Feedbackを適切なLaneへ自動仕分けする | FeedbackをEvidenceへ昇格する |
| Decision Broker | Human Decision Packetを生成し、該当経路をBlock／Resumeする | AI推奨をDecisionとして記録する |
| Trace Store | Run、Context Pack、State snapshot、hash、Decision、Back Referenceを保存する | Reader-facing proseへ内部IDを露出する |


## 7－3 三つの長期状態を分離する

| 状態 | 保持するもの | 主な利用者 |
| --- | --- | --- |
| Research State | 問い、Evidence、Finding、反証、未解決、方法、Scope、次の研究要求 | Research Worker、Methods、State Reducer |
| Publication State | Working Draft、図表、脚注、章間接続、Manuscript Delta、Publication Feedback、Rendering Contract | Writer、Editor、人間Reviewer |
| Orchestrator State | 問いportfolio、Attention被覆、Run履歴、主要Decision、Blocker、Feedback routing、次Run依存関係、Context pointers | Orchestrator、研究統括 |

Orchestrator StateはResearch Stateの全文コピーではない。全体制御に必要な短い意味状態と参照ポインタだけを持つ。


## 7－4 Context PackはRunごとに自動生成する


Context Builderはファイルの存在、ディレクトリ名、自然言語の「参考」という表現からAccessを推測しない。`Artifact Registry`と`MISCO_Runtime_Artifact_Policy_v0.1.yaml`を解決し、Task Eventに対して許可されたArtifactだけをContext Packへ入れる。Generic `references/` directoryをRuntime discovery rootとして使用しない。

標準Context Eventには少なくとも`QUESTION_FORMATION`、`SEED_COMPARISON`、`RESEARCH_PLANNING`、`RESEARCH_RUN`、`PUBLICATION_DRAFT`、`PUBLICATION_FINALIZATION`、`CONTRACT_MIGRATION_REVIEW`、`PROVENANCE_AUDIT`を持つ。Archive／Historical／Simulation provenanceは前六つの通常Runtime EventではDENYする。

既存Runtimeの契約・Runtime policyが更新された場合、Harnessは明示的な
`CONTRACT_MIGRATION_REVIEW`としてlive `Artifact Registry`をrefreshできる。
旧RegistryはRun配下へ不変保存し、現行契約から検証済みの新Registryと
implementation-only Context Packを作成した後にのみheadを進める。この経路は
Research／Publication State、Human Decision、pending Workを変更せず、意味変更や
新しいResearch判断は別のHuman Decisionへ戻す。

各Runの主入力はOrchestratorが生成するImmutable Context Packである。Packには少なくとも以下を含む。

| 区分 | 内容 |
| --- | --- |
| Task Contract | Run ID、目的、Active Question／Gap、成功・停止条件、出力Schema |
| Canonical Constraints | このRunに適用する上位原則・Protocolの解決済み抜粋と版 |
| Approved Inputs | 必要なResearch State、Evidence pointers、Counterevidence、Unknowns |
| Retrieval Policy | 追加取得を許可するSource領域・Back Reference・Web等の範囲 |
| Forbidden Context | 旧仮説、Publication Draft、Hidden Ground Truth、別mode情報等 |
| Audit Expectations | Claim強度、反証、責任範囲、Schema、Traceabilityの検査条件 |
| Output Contract | Worker output、Back Reference、Handoffに必要な構造 |

Context PackはRun開始後に暗黙変更しない。追加Contextが必要になった場合は、取得理由と参照をRun Logへ残す。


## 7－5 Workerはbackend-neutralに扱う

Research Harnessの契約は特定のUI、モデル、ChatGPT Work、Codex CLI等へ依存させない。Worker AdapterがContext PackとOutput Contractを媒介する。初期実装はローカルで自動実行・テスト可能なWorker Backendを優先し、対話型Workを使う場合も同じContext Packを人間が再編集せず渡せる形を維持する。

Work等に安定したプログラム実行APIが存在しない場合、Core HarnessをそのAPIへ依存させない。対話型Workerは任意Adapterとして扱い、Control Planeの自動State管理・Context生成・Decision管理はローカルで完結できるようにする。


## 7－6 State Reducerは「要約」ではなく意味状態を作る

State Reducerは単なる短縮要約を作らない。最低限、Observed、Derived、Interpreted、Counterevidence、Unknown、Scope、Question Delta、Next Evidence Request、Back Referenceを区別する。圧縮時に少数警告、判断不能、反証、問い変更理由を落とした場合はCompaction Lossとして失敗させる。

State Reducerの出力は`State Delta Proposal`であり、研究上の採否が必要な項目はDecision Brokerへ送る。Operational metadata、Run完了、hash、既決Protocol内の参照更新等は自動commitできる。


## 7－7 Publication ExporterがResearch／Publication Firewallを強制する

Publication ExporterはResearch State全体をWriterへ渡さない。次だけを選択・変換する。

- `publication_eligible=true`相当のResearch State snapshot。
- 対象Publication箇所とPrimary Exposition Location。
- 承認済み図表・数値・ケース比較・Model Revision。
- Writerが脚注・図表出典を作るために必要なSource metadataとlocator。
- 既存Publication DraftとResearch State Delta。
- Formal Specification Profile／Clean Source Packの参照。

Publication Draft、Writerの解釈、Publication FeedbackをResearch Context PackのEvidence欄へ戻すことを禁止する。

Research LaneとPublication Laneは並走可能である。現在のResearch State
snapshotが`publication_eligible=true`相当のHuman承認を持つ場合、Researchの
terminal完了を待たずに暫定Publication State／Draftを更新できる。Publication
更新はResearch phase、Question、Method、Evidence interpretationを変更しない。
Publication Eligibilityを確認するHuman DecisionはPublication側のpending queueで
管理し、Research側のpending decisionやResearchの継続を止めない。記録された
Decision IDはHarnessが対象Research Stateへ保存する。
Current Research StateとAttention Mapから生成するPublication Structureは
reader-facingな初期仮説であり、章・節の追加、削除、統合、分割、移動、改称を
Publication Map Deltaとして許可する。初期MapやStructureをResearch Laneの
拘束条件へ逆流させてはならない。


## 7－8 Publication Feedback Router

Writerが返したFeedbackを機械的に分類し、次の宛先へ送る。

| Feedback | Route |
| --- | --- |
| ARGUMENT_GAP / MISSING_RESEARCH_INPUT | Research / Synthesis |
| QUESTION_SCOPE_AMBIGUITY | Question Review |
| ACADEMIC_QA_REQUIRED | Academic QA / Human |
| MODEL_REVISION_UNRESOLVED | Model Review |
| PRIMARY_EXPOSITION_CONFLICT | Publication / Orchestrator |
| FORMAL_METADATA_MISSING | Publication Ops / Human |

Feedbackのrouting自体は人間作業にしない。Human Decisionが必要なtypeだけDecision Brokerへ昇格する。


## 7－9 Decision Broker：人間には「判断」だけを渡す

Decision Brokerは、Human Gate Review Briefの原則をControl Planeへ実装する。人間へ提示するPacketは、最低限次を含む。

1. **Decision Request**：今回何を決めるか。
2. **AI非拘束推奨**：主要理由3点以内。
3. **主要Evidence / Counterevidence / Unknown**。
4. **選択肢**：少なくとも現状修正、限定進行、追加確認／停止等。
5. **Downstream Impact**：問い、方法、Publication、日程、Claimへの影響。
6. **What becomes fixed**：決定により固定されるもの。
7. **Resume condition**：Decision後にOrchestratorがどのRunから再開するか。

人間はPacketへのDecisionを記録すればよく、Run folderを手動で再構成しない。


## 7－10 Orchestrator自身のContext肥大を防ぐ

Orchestratorは次の情報だけを常時保持し、詳細はpointerから取得する。

- Active／Closed／Unanswered Questionの短い状態。
- Attention Mapの被覆と重大な未被覆。
- 直近Decisionと未解決Blocker。
- 現在のModel／Propositionの状態遷移要約。
- Publication章状態と未解決Feedback。
- 次Run候補、依存関係、Context pointer。

一定量を超えた履歴はimmutable Run Artifactとして退避し、State snapshotを更新する。Orchestratorが「全部を読んだまま考える」ことを設計上の要件にしない。


## 7－11 Execution BackendとCodexの位置づけ

初期実装では、ローカルRepositoryを操作し、repeatable workflowを構築できるCodex等の実行Backendを利用できる。ただし、HarnessのState Schema、Context Pack、Decision Broker、Publication interfaceをCodex固有形式へ閉じ込めない。Backendは交換可能なAdapterとして実装する。

Codex CLIを利用する場合も、非対話実行、subagent／bounded worker、skills等の利用可否は実行環境で検出し、利用できない機能を前提にCoreを壊さない。外部仕様が変化した場合にControl Planeの研究契約まで変更しない。

# 8. Phase間のSemantic Handoff


## 8－1 生ログではなく「意味状態」を渡す

次Runへ渡す主インターフェースは、Raw Logや長大なEvidence台帳ではなく、何が観測され、何が解釈可能で、何が未解決で、次に何を確認すべきかを構造化したResearch Handoffである。必要な場合のみ裏側のEvidenceへ戻る。


## 8－2 Research Handoffの最低項目

| 項目 | 内容 |
| --- | --- |
| Active Question | 今回扱った問いと更新後の状態 |
| What we observed | 直接観測・取得したもの |
| What we infer | 許容される解釈。観測と分離 |
| Counterevidence / Exceptions | 反例、少数警告、企業内差、非適用 |
| What remains unknown | この方法では答えられなかったこと |
| Question Delta | 問いの維持、修正、分割、統合、閉鎖 |
| Next Evidence Request | 次に必要なEvidenceの性質 |
| Candidate Capability | 候補方法と選定理由 |
| Back references | Source／Evidence／Finding／Decisionへの参照 |


## 8－3 Case → Model Refinementを必須インターフェースにする

ケース分析を採用した場合、ケース紹介だけで終了してはならない。各Caseが既存命題・暫定Modelの何を支持し、どの条件を追加し、何を反証したかを次の形式で残す。これにより第7章相当のケース結果が第4・5章相当の命題・モデル精錬へ確実に接続する。

| Case | 対象命題／Model要素 | 観察された機序 | 判定 | Model変更 | 残存不足 |
| --- | --- | --- | --- | --- | --- |
| CASE-x | PROP/MODEL-x | 現実に何が起きたか | 支持／条件追加／部分反証／反証／判断不能 | 維持／修正／分割／削除／追加 | Caseでは答えられない点 |


# 9. 研究管理語彙と論文表現のRendering Firewall


## 9－1 内部語彙は内部で使う

研究管理上、研究問いID、Gate、Artifact ID、Evidence ID、Finding、Proposition、Claim、Decision等は有用である。しかし、これらを最終本文へ露出させると、読者は研究結果ではなく研究管理システムを読むことになる。Publication Laneでは内部状態を通常の研究報告書の論証へ変換するRendering Firewallを置く。

| 内部語彙 | 論文での扱い |
| --- | --- |
| RQ / Question ID | 第1章で研究課題として自然文で示す。以後は必要時のみ「本研究の問い」として参照。Coverage状態は出さない。 |
| Gate / Gx | 本文には原則出さない。研究方法でAI協業の品質管理を説明する場合も一般語へ翻訳。 |
| Artifact / Evidence ID | 本文には原則出さない。脚注・図表出典・付録へ変換。 |
| FND / PROP / CLM | 観測結果、解釈、命題、結論として自然文にする。内部IDは裏側のみ。 |
| SYNTHETIC_TEST_ONLY | VIRTUAL報告書では表紙・Watermark・方法・Limitationsで認識可能にする。本文で反復しない。 |
| Decision ID | 研究変更やHuman Decisionの監査用。本文へは出さない。 |


## 9－2 Publication Rendering Contract

- 本文は「説明→図表→結果の読み取り→解釈→次の論点」の反復を基本にする。
- 主要な方法結果は一度まとまって読めるPrimary Exposition Locationを持たせ、各章へ散らしすぎない。`Home Chapter`はこのPublication routingの旧称・実装aliasとして扱い、研究上の所属章を意味しない。
- モデル・施策は図一枚で済ませず、形成理由、構成要素、適用・非適用、修正過程、使用方法まで本文で説明する。
- 出典は読者向けにはWord実脚注の*n形式を基本とし、図表には通常の「（出典）」を付す。
- 見出しレベル3以下を、独立結論、別Evidence群、図表、参照単位がある箇所で積極的に使う。
- 研究結果は慎重に、提言は根拠・主体・条件が確立した範囲で明確に書く。
- 内部台帳の厳密さを失わず、本文をTechnical Evidence Packageの文章化にしない。

# 10. トレーサビリティはResearch Graphとして保持する


## 10－1 裏側のResearch Graph

トレーサビリティを弱めるのではなく、読者向け文章から分離する。Research Graphでは、Theme／Expectation、Question、Source、Evidence、Analysis、Finding、Proposition、Model、Claim、Recommendation、Practical Artifact、Decisionをノードとして保持し、形成、支持、反証、修正、参照等の関係をエッジで管理する。


## 10－2 WriterがResearch Graphを直読しない

Writerへ全Graphをそのまま渡すと、ID順に説明する台帳文書になりやすい。Writerの主入力は、Publication Eligibleとして承認済みのResearch State snapshot、Publication State、必要なBack Referenceとする。原Evidenceは引用確認または論証確認が必要なときだけ取得する。WriterがResearch Graphから新しい研究判断を作ってはならない。最終QAでは逆に、本文の主要主張からResearch Graphへ戻れることを検査する。


## 10－3 前向き・逆向きの二方向QA

| 方向 | 確認 |
| --- | --- |
| Research → Publication | 重要Finding、反証、条件、Model修正が本文から脱落していないか。 |
| Publication → Research | 本文の主要主張、数値、提言が承認済みEvidence／Finding／Decisionへ戻れるか。 |


# 11. Human DecisionとGateの再配置


## 11－1 Gateは内部のDecision Checkpointである

Human Gateの考え方、Review Brief／Technical Evidence Package／Decision Recordの三層構成、AI推奨の非拘束性は維持する。一方、Gateを最終論文の語彙や固定章順へ結び付けず、研究状態が重要な不可逆点に到達したときの内部Decision Checkpointとして扱う。


## 11－2 イベント駆動のDecision例

Publication Laneでは少なくとも次のDecisionを区別する。

- **Publication Eligibility Decision**：Research State snapshotを現時点の暫定状態としてWriterへ渡してよいか。問い・Finding・Modelの最終確定とは別。
- **Publication Stable Decision**：統合原稿が現行Research Stateと整合し、主要Feedbackが閉じ、当該版を安定版として扱えるか。
- **Release Decision**：引用、書式、権利、公開条件を含め提出版をFINALとしてよいか。


| Decision Event | 人間が決めること |
| --- | --- |
| Question Baseline | 初期問い候補を研究開始に十分な状態として受け入れるか。 |
| Desktop Evidence Review | 問いをどう修正し、何を一次調査へ送るか。 |
| Method Selection | どのCapabilityを、どのScope／Protocolで使うか。 |
| Data / Evidence Acceptance | 取得データ・ケース・RoundをEvidenceとして受け入れるか。 |
| Finding Acceptance | 観測結果、反例、到達範囲をどう凍結するか。 |
| Model / Proposition Review | 比較対象として何を次の検証へ送るか。 |
| Research Closure | 問いをCLOSED／UNANSWEREDとして閉じるか。 |
| Publication Stable | 研究結果の読者向け表現をStableとするか。 |
| Release | 最終本文、引用、個社情報、提言、公開条件を承認するか。 |


## 11－3 Human DecisionとHuman Operationを分離する

人間の責任は研究上のDecisionであり、Orchestration作業ではない。Decision Brokerは「承認してください」とだけ出さず、選択肢、AI非拘束推奨、反証、下流影響、再開条件を提示する。Decisionが記録された後のState更新、Context再生成、該当RunのResumeはControl Planeが行う。

Human Operationが必要となるのは、実参加者への接触、同意、直接識別子、公開承認、外部システムへの不可逆な書込み等、人間専有または明示承認が必要な実作業に限る。単にAI間でファイルを受け渡すために人間を介在させない。


## 11－4 現行G0～G13との関係

移行期間は現行G0～G13を互換レイヤとして残すことができるが、本設計の研究サイクルをG0～G13へ無理に一対一対応させない。採用時は資料2を改訂し、固定Phase GateからDecision Event中心の体系へ移行するか、既存Gateを包む互換マッピングをHuman Decisionで選択する。


# 12. VIRTUAL RUNで検証するもの


## 12－1 VIRTUALの目的

VIRTUALは合成の研究結論を得るためではなく、このResearch Harnessが研究の問い、方法選択、Evidence、文章、Human Decisionを正しくつなげられるかを検証する。Standard Runでは15社の架空企業枠を基本とするが、方法選択の結果、SurveyやDelphiが不要と判断された場合に「予定していたから実施する」方向へ戻してはならない。


## 12－2 VIRTUALで追加して検査するHarness Defect

| Defect | 検査内容 |
| --- | --- |
| Question Lock-in | 初期問いが外部Evidenceに反しても修正されない。 |
| Method Lock-in | Survey／Delphi／Caseを実施すること自体が目的化する。 |
| Chapter Lock-in | 章の空欄を埋めるために研究が起動する。 |
| Narrative Lock-in | 暫定原稿が後続研究の問い・解釈を誘導する。 |
| Context Blow-up | Orchestrator／Workerが不要な全履歴を抱え、重要情報が埋没する。 |
| Compaction Loss | 反証、少数警告、未回答、問い変更理由がHandoffで失われる。 |
| Traceability Exposure | 最終本文がID・Gate・台帳中心の監査文書になる。 |
| Research–Publication Drift | 研究状態と原稿の主張強度が一致しない。 |
| Case without refinement | ケース紹介はあるが命題・モデルが何も変わらない。 |
| Late style failure | 最終段階までMISCO文体・脚注・見出し・図表の不具合が発見されない。 |
| Human-as-the-loop | 人間がContext Pack、ファイル移動、State転記、Writer輸送をしないと次Runへ進めない。 |
| Orchestrator overload | Control Planeが全Source／全原稿を常時保持し、自身のContextが肥大する。 |
| Silent context leak | Publication Draft、旧仮説、別mode情報が禁止されたResearch Runへ混入する。 |
| Feedback orphaning | Publication Feedbackが人間の手作業に依存し、未処理のまま残る。 |


## 12－3 HarnessとしてのVIRTUAL合格像

- 問い候補がDesktop Researchによって実際に変更されるケースを処理できる。
- Evidence Gapから異なる方法選択が起こり、方法を実施しないDecisionも正当に扱える。
- 各Research AgentのContextが限定されても、Research Handoffで全体の論証が切れない。
- 暫定原稿が研究を誘導せず、それでも文章品質は研究初期から調整される。
- Case／Delphi／Survey等を採用した場合、それぞれの責任範囲を超えない。
- 最終Writerが研究を一から再解釈せず、Editorとして統合できる。
- 最終報告書から研究管理語彙が適切に隠れ、主要主張は裏側のResearch Graphへ戻れる。
- 通常サイクルで人間によるContext Pack組立て、ファイル輸送、State転記を要求しない。
- 人間へ提示される介入は、研究上のDecisionまたはHuman-only operationに限定され、Decision後は自動Resumeできる。
- Orchestrator自身が短いControl Stateで動き、必要な詳細をpointerから取得できる。

# 13. 品質保証とStress Run


## 13－1 必須Stress

| Stress | 期待する挙動 |
| --- | --- |
| Desktopで問いの前提が崩れる | 問いを修正・統合・廃棄し、旧問いに合わせてEvidenceを選別しない。 |
| 一次調査不要 | 方法を採用しないDecisionを許し、章を埋めるために調査を追加しない。 |
| Survey結果が弱い／逆方向 | 弱いFinding・Reverseを保持し、次のCase／追加調査の要否を再判断する。 |
| Delphi非合意 | 合意化せず、条件差・判断材料不足としてResearch Stateへ残す。 |
| CaseがModelを反証 | Model／原稿を修正し、Caseを例外扱いして無視しない。 |
| Publicationが先に綺麗になる | 後続Research Agentへ原稿を渡さずNarrative Lock-inを遮断する。 |
| Context削減が強すぎる | Back referenceから必要Evidenceを取得し、重要な反証が圧縮で消えていないか検査する。 |
| Humanがファイルを動かさない | Control PlaneだけでContext生成→Worker→Audit→State→Publication exportまで進む。 |
| Decision待ち | 該当経路だけBlockし、Decision Packet生成後は承認内容から自動Resumeする。 |
| Publication Feedback連鎖 | WriterのFeedbackを自動routingし、Research Evidenceへ昇格せず処理する。 |


## 13－2 stop-academic-slop-jpの配置

Evidence–Claim Integrity、推論飛躍、一般化、Citation Entailment、RQ／問いからFinding・Implicationへの追跡性は、Publication Laneの各更新時と最終統合時に独立QAとして適用する。文体だけを整えるために研究上の留保を削らず、逆に留保を本文全体へ機械的に反復しない。


# 14. 現行資料からの移行案


## 14－1 各資料への影響

| 資料 | 提案する扱い |
| --- | --- |
| 資料1 研究設計正本 | v0.9候補で、固定RQを「初期問い候補＋最終問い凍結規則」へ変更。章節をAttention Map／Publication Mapへ再定義。方法をCapability化し、Evidence Gapで採否する。 |
| 資料2 AI協業共通実行仕様 | C0～C13の一方向パイプラインをResearch Cycle Harnessへ再編。Control Plane、Research State／Publication State／Orchestrator State、Context Builder、State Reducer、Publication Exporter、Decision Broker、Handoff、Manuscript Deltaを実装。 |
| 資料3 RUNプロファイル | VIRTUAL／REALの取得・Cleaning差分は再利用。ただしSurvey／Delphiが選択された時に適用するCapability Profileへ変更。 |
| 資料4 Delphiガイドライン | Delphiが選択された場合の下位Capability仕様としてほぼ維持。 |
| 資料5 Human Gateガイドライン | 三層Review PackageとHuman Decision責任を維持。GateをDecision Eventへ適用できるよう整理。 |
| 統合記載仕様＋元資料 | Publication Formal Specとして維持。Runtime Writerへは必要なFormal Spec Profileを蒸留し、Desktop finalizationでは元Word template／font／作成要領をHuman／Publication Opsが使用する。 |
| 現行第1～8章・節構成 | `MISCO_Research_Attention_and_Initial_Publication_Map_v0.1`へ意味を蒸留。Attentionは保持し、章・節配置はPROVISIONALとして破壊可能にする。原資料1全文をRuntime Mapの代用品にしない。 |
| 2025年度G1報告書 | `HISTORICAL_CALIBRATION_SOURCE`。G1から採用した書き味はClean Source Packへ蒸留済みとし、Research／Publication RuntimeはDENY。 |
| 資料1～5旧版・前走Simulation・旧RQ／旧Model | Change Impact／Provenance用Archiveへ移す。採用済み意味はActive Contract／Mapへ蒸留し、通常RuntimeはDENY。 |


## 14－2 移行オプション

| 案 | 内容 | 利点 | 主なリスク |
| --- | --- | --- | --- |
| A 現行維持 | C0～C13、固定RQ／方法を維持し、執筆だけ逐次化 | 変更量が少ない | Method/Chapter Lock-inが残る |
| B ハイブリッド | RQ1～RQ5は固定しつつ、方法採否と逐次執筆をEvidence Gap駆動にする | 正本変更を限定できる | 問い自体を調査で磨く自由度が不足 |
| C 本設計を採用 | 問い候補、方法Capability、Research Loop、逐次Publication、Context Harnessへ移行 | 研究の実態とAI長期協業に最も整合 | 資料1～3の大幅改訂とVIRTUAL再試験が必要 |


## 14－3 AIの非拘束推奨

案Cを推奨する。今回の前走シミュレーションで観察された問題は、Writerの文体調整だけではなく、研究工程、Phase間インターフェース、Context管理、方法選択、章立ての役割が一体化していることに起因しているためである。ただし、採用は資料1～3の研究設計変更を伴うため、Human DecisionとChange Logを経る必要がある。


# 15. 実行開始時の標準フロー


## 15－1 Control Plane Bootstrap

研究開始時、人間は研究Rootへテーマ、期待事項、Research Harness、Research Constitution、Runtime Artifact Policy、Research Attention / Initial Publication Map等の承認済み開始入力を登録する。OrchestratorはArtifact Registryを作り、各Artifactのrole、authority、lane、runtime_policyを解決してQuestion Formation用Context Packを生成する。`reference`または`legacy`という曖昧な分類だけでAccessを許可しない。人間がRunごとにファイルを選択して渡す運用は標準としない。

初期RQ Seedを独立生成から隔離する場合、SeedはQuarantineとして登録し、最初のQuestion Formation Context Packから機械的に除外する。独立候補がsnapshot化された後の比較RunでのみContext BuilderがSeedを解禁する。


## 15－2 Discovery Cycle

### （1）テーマ・期待事項の読み込み

Orchestratorが研究テーマおよびM3提案・助言・期待事項を「答えるべき結論」ではなくResearch Attentionの入力としてQuestion Workerへ渡す。矛盾、期待、価値判断、未定義概念を分離する。

### （2）研究問い候補の形成

Question Workerが問い候補を複数形成し、Attention Coverage、研究可能性、重複、主体、時間軸、必要Evidenceを整理する。Audit WorkerがSeed混入、結論誘導、一問多判断等を検査する。Question Baselineが必要な時点でDecision Brokerが人間へPacketを出す。

Publication Eligibilityが承認された問い候補はPublication ExporterからWriterへ渡し、第1章相当のWorking Draftを作る。Writer Feedbackは自動routingされる。

### （3）Desktop Research Protocol

OrchestratorがQuestion StateからDesktop Research Context Packを作る。問い候補を検索語の正解として固定せず、定義、既知知見、対立、空白、反例、制度・技術変化を取得する。旧仮説・旧モデルはAccess policyで隔離する。

### （4）Desktop Research結果のState化と文章化

Research Workerの結果をAudit後、State Reducerが外部環境、既知知見、対立、不確実性、反証、Evidence Gap、Question Deltaへ圧縮する。人間がResearch Stateの意味を手で転記しない。

Publication EligibleとなったsnapshotはPublication Exporterを通じて第2章相当へ反映する。同時にWriterが見つけた論証上の穴をFeedback Routerが次のResearch判断へ送る。

### （5）一次調査方法のHuman Decision

Orchestratorは残ったEvidence GapごとにSurvey、Case Study、Delphi、追加Desktop Research、外部有識者Review、Pilot等を比較したMethod Selection Packetを生成する。人間は採用するCapability、Scope、条件だけを決める。Decision後、Protocol／Context Pack／次RunはControl Planeが組み立てる。


## 15－3 以後の反復

以後は、選択したCapabilityを一つまたは組み合わせてResearch Cycleを回す。各サイクルでState ReducerがResearch Handoffを作り、Publication Exporterが対応箇所だけを更新する。後続Evidenceが既存命題・モデル・文章を変更した場合はResearch StateとManuscript Deltaへ反映する。

すべての問いがCLOSED、UNANSWEREDまたはOUT_OF_SCOPEとして整理され、主要Attention領域の未被覆がHuman Decisionで受入可能となった時点で最終統合へ進む。最終統合へ至るまでのRun transport、Context編成、Feedback routing、State snapshotは人間の手動作業に依存しない。

# 16. 最終統合とWriterの役割


## 16－1 最終WriterはAuthorではなくEditorに近づける

最終Writerへ「研究全部を理解して白紙から50～60頁を書け」と要求しない。Publication Exporterが生成した各サイクルのPublication State、承認済みFinding、Question Closure、Model Revision、引用候補を入力として、重複削除、章間接続、論証順の最適化、用語統一、脚注・図表・MISCO書式の統合を行う。人間が最終Writer用の巨大な材料束を手作業で編成しない。WriterのFinal Editorial出力は`INTEGRATED`までとし、`STABLE`はPublication Stable Decision、`FINAL`はRelease Decisionで人間が付与する。


## 16－2 最終統合で必ず再確認すること

- 最終問いへの回答が、本文のどこで形成・修正・閉鎖されたか。
- 後続Case／Delphi等で修正された旧Model・旧Claimが残っていないか。
- 方法別の結果が読者に一度まとまって理解できる配置になっているか。
- 第8章相当で新しい分析を初めて出していないか。
- 提言がFinding／Claimを超えていないか。
- 内部ID、Gate、Coverage等が読者向け本文へ不要に露出していないか。
- 脚注・図表出典から原Sourceへ戻れ、Citation Entailmentが成立しているか。
- 本文を順方向に読んでも、最終提言までの論証の鎖を感じられるか。
- Writerが返したPublication Feedbackが、Research・Academic QA・Human Decision・Publication修正のいずれかへ明示的に処理され、未処理のままSTABLE化されていないか。

# 付録A. Question Registerテンプレート

| 項目 | 内容 |
| --- | --- |
| Question ID | 内部識別子。論文本文には原則出さない。 |
| Question text | 現在の問い文。主体・対象・時間・条件を含む。 |
| Origin | 研究テーマ、期待事項、外部Evidence、Survey、Case等。 |
| Attention coverage | どのAttention領域へ関係するか。 |
| State | CANDIDATE／SCOPED／ACTIVE／REFINED／CLOSED等。 |
| Known evidence | 既に答えられる部分。 |
| Evidence gap | まだ言えないこと。 |
| Candidate capability | 次に使い得る方法。 |
| Counterevidence | 反証・代替説明・例外。 |
| Delta history | 修正・分割・統合・閉鎖の理由とHuman Decision。 |


# 付録B. Method Selection Recordテンプレート

| 項目 | 内容 |
| --- | --- |
| Target Question / Gap | 何を明らかにするための方法か。 |
| Candidate methods | 比較したCapability。 |
| Fit | 各方法が何を観測でき、何を観測できないか。 |
| Access / Burden / Risk | 取得可能性、参加者負担、匿名性、費用、期限。 |
| Independence | 既存Evidenceとの独立性。 |
| Selected method | 採用方法、Scope、Protocol。 |
| Rejected methods | 採用しない理由。 |
| Human Decision | 決定者、日時、条件、再評価Trigger。 |


# 付録C. Research Handoffテンプレート

| 項目 | 内容 |
| --- | --- |
| Question state | 開始時／終了時の問い状態。 |
| Observed | 直接観測・取得した事実。 |
| Derived / Interpreted | 計算・分析・解釈を分離して記載。 |
| Counterevidence | 反例、少数警告、矛盾。 |
| Scope / Limit | 対象、時点、欠測、非適用。 |
| What remains unknown | この方法で答えられなかった点。 |
| Next evidence request | 次に必要な情報。 |
| Back references | Source／Evidence／Finding／Decision。 |


# 付録D. Orchestrator Stateテンプレート

| 領域 | 保持内容 |
| --- | --- |
| Question portfolio | Active／Closed／Unansweredと優先度。 |
| Attention coverage | 主要Attention領域の被覆／未被覆。 |
| Research runs | 完了Run、方法、主Finding、残課題。 |
| Model state | 候補、修正、反証、採否状態。 |
| Publication state | 章・節のSCAFFOLD／PROVISIONAL／REVISED／INTEGRATED／STABLE。 |
| Open blockers | 方法、権限、Evidence、Publication Feedback、文章、Human Decision。 |
| Next decisions | 人間が次に決める具体事項。 |
| Context pointers | 必要時に取得するSource／Package／Draft。 |


# 付録E. Manuscript Deltaテンプレート

| 項目 | 内容 |
| --- | --- |
| Location | 対象章節・段落・図表。 |
| Previous meaning | 旧稿の主張。 |
| Trigger evidence | 変更を要求したEvidence／Finding。 |
| Change type | 追加／条件化／弱化／強化／分割／削除。 |
| New meaning | 修正後の主張。 |
| Citation impact | 脚注、図表出典、参考文献への影響。 |
| Downstream impact | 他章、Model、Claim、Recommendation。 |
| State | PROVISIONAL／REVISED／INTEGRATED／STABLE。 |


# 付録F. Context Viewテンプレート

| 区分 | 含める内容 |
| --- | --- |
| Objective | 今回のRunで何を決める／調べるか。 |
| Canonical constraints | このRunに必要な正本ルールだけを解決して提示。 |
| Active questions | 今回対象とする問い。 |
| Approved inputs | 承認済みResearch State、必要なEvidence参照。 |
| Counterevidence / Unknowns | 先に見せるべき反例・不明点。 |
| Forbidden context | 旧仮説、不要なPublication Draft、Hidden Ground Truth等。 |
| Output contract | 次Runが消費できるResearch Handoff Schema。 |
| Retrieve pointers | 必要時にpullする詳細Package。 |


# 付録G. Publication Feedbackテンプレート

| 項目 | 内容 |
| --- | --- |
| Feedback ID | PUBFB-xxx。内部管理用。 |
| Writer mode / location | PHASE_DRAFT／REVISION／FINAL_EDITORIAL等と対象章節。 |
| Feedback type | ARGUMENT_GAP／QUESTION_SCOPE_AMBIGUITY／MISSING_RESEARCH_INPUT／ACADEMIC_QA_REQUIRED／MODEL_REVISION_UNRESOLVED／PRIMARY_EXPOSITION_CONFLICT／FORMAL_METADATA_MISSING等。 |
| What cannot be written safely | どの説明・接続・表現が成立しないか。 |
| Missing or conflicting state | 足りないResearch State、承認、Formal metadata。 |
| Suggested destination | Research／Methods／Academic QA／Human Decision／Publication Ops。 |
| Research evidence? | 常にNO。Feedback自体をEvidenceにしない。 |
| Resolution | 追加入力、Research Decision、Academic QA、Publication修正等。 |


# 付録H. Publication Writer入力契約

- Writerへ渡すResearch Stateは`publication_eligible=true`相当のHuman-approved snapshotであること。`CANDIDATE`や`PROVISIONAL MODEL`でも、状態を保持したまま文章化してよいと承認されていれば入力可能。
- Writerは承認済みResearch Stateのリンクだけを論証へ変換し、欠けたResearch Judgmentを埋めない。
- `primary_exposition_map`をPublication routingの優先名称とし、`home_chapter_map`は後方互換aliasとして許容する。
- Writerの通常状態遷移は`SCAFFOLD → PROVISIONAL → REVISED → INTEGRATED`まで。`STABLE`／`FINAL`はHuman Decisionのみ。
- Writerが研究上の穴を発見した場合は`Publication Feedback`または`[NEEDS_INPUT]`／`[NEEDS_ACADEMIC_QA]`として返す。原稿をResearch Evidenceとして返さない。
- Runtime style sourceはHuman Approved Clean Source Pack Layer Aと正式文書仕様のみ。過年度論文・歴史コーパスをRuntimeで参照しない。
- 脚注、見出し、図表、URL等の具体形式は`formal_spec_profile`／承認済みPublication Rendering Contractから受け取り、Writerが過去例から推測しない。


# 付録I. Publication Rendering Contract（AI Writer用）

- 研究管理用のID、Gate、Coverage状態を本文の論証として使用しない。
- 研究課題は第1章で自然文として示し、その後は番号呼称を必要最小限にする。
- 本文はMISCO報告書の「である調」とし、段落による論証を中心に、図表は説明に必要な箇所へ置く。
- 主要方法結果はPrimary Exposition Locationでまとまって読めるようにする。
- 外部SourceはWord実脚注*n、図表は出典表示。内部Source IDは裏側に保持する。
- レベル3以下の見出しを必要に応じて使用し、長い分析を一枚の節に詰め込まない。
- VIRTUAL留保は表紙、Watermark、方法、Limitationsに集約し、本文で反復しない。
- モデルは形成→比較→ストレス→修正の履歴が読者に見えるように書く。
- Caseを採用した場合、Caseが命題・モデルをどう精錬したかを必ず本文に示す。
- 最終章で新しい事実・分析を初めて導入せず、前章までの論証を統合して答える。

# 付録J. Human Decision事項

本設計を正規の研究設計へ採用するには、最低限次のHuman Decisionが必要である。

- 主RQ・RQ1～RQ5を固定RQから「初期問い候補／Attention基準」へ変更するか。
- Survey・Delphi・Case Studyを必須方法からEvidence Gapに応じて選択するCapabilityへ変更するか。
- 第1～8章を研究工程ではなくAttention Map／初期Publication Mapとして再定義するか。
- 資料2 C0～C13をResearch Cycle Harnessへ置き換えるか、互換レイヤとして残すか。
- 各研究サイクルでPublication Laneを更新し、暫定原稿を後続研究から隔離する方式を採用するか。
- Research State／Publication State／Orchestrator State／Context View／Research Handoff／Manuscript Deltaを標準Artifactとして採用するか。
- Human Gateを固定Phase番号中心からDecision Event中心へ移行するか。
- この変更後、VIRTUAL RUNを新設計のHarness検証として最初から再実行するか。

# 付録K. Control Plane Component Contract

| Component | Input | Output | Block条件 |
| --- | --- | --- | --- |
| Orchestrator | Orchestrator State、Decision、Run status | Next Run Plan、Decision要求 | 正本矛盾、Decision待ち、回復上限超過 |
| Context Builder | Run Plan、Research State、Access policy | Immutable Context Pack | 必須入力不足、禁止Context混入 |
| Worker Adapter | Context Pack、Backend config | Raw Worker Output | Backend failure、Output Contract不一致 |
| Audit Worker | Context Pack、Raw Output、Audit policy | Audit Result | BLOCKER／MAJOR issue |
| State Reducer | Raw Output、Audit Result、Prior State | State Delta Proposal、Handoff | Compaction Loss、分類不能 |
| Publication Exporter | Publication Eligible State、Publication Map | Writer Input Bundle | Eligibility不足、Research／Publication混入 |
| Feedback Router | Publication Feedback | Routed Action | Human Decision型Feedback |
| Decision Broker | State、Options、Evidence balance | Decision Packet、Block/Resume state | Human Decision未記録 |


# 付録L. Run Manifest / Context Pack最低Schema

| 項目 | 必須内容 |
| --- | --- |
| run_id | 一意なRun識別子。再実行は新ID。 |
| task_type | QUESTION／DESKTOP_RESEARCH／SURVEY／CASE／DELPHI／AUDIT／REDUCE／PUBLICATION等。 |
| objective | 今回のbounded goal。 |
| active_questions | 対象Questionと状態。 |
| canonical_versions | 適用するContract／Protocol版。 |
| input_refs | path／Artifact ID／hash／approval state。 |
| forbidden_context | 明示的に除外する資料・Lane・mode。 |
| retrieval_policy | on-demand取得を許す範囲。 |
| output_schema | Workerが返す構造。 |
| stop_conditions | Decision、権限、失敗上限等。 |
| worker_backend | 実行Adapter識別子。 |
| audit_policy | 独立Auditの要否・検査項目。 |
| decision_context | 既決条件、未決Decision。 |


# 付録M. Human Decision Packetテンプレート

| 項目 | 内容 |
| --- | --- |
| Decision Request | 人間が今回決める一文。 |
| Current State | Question／Method／Evidence／Publicationの現在状態。 |
| AI Recommendation | 非拘束推奨と主要理由。 |
| Evidence Balance | 主要根拠、反証、判断不能、Scope。 |
| Options | 複数案と必要作業。 |
| Downstream Impact | 問い、方法、日程、章、Claim、Publicationへの影響。 |
| What becomes fixed | 決定で固定されるもの。 |
| Human input fields | 選択、条件、理由、期限、責任者。 |
| Resume plan | Decision後にControl Planeが自動再開するRun／State遷移。 |


# 付録N. Execution Harness MVP受入基準

MVPは研究全体を完全自動化する必要はない。最初の実装では次を満たせばよい。

1. Research／Publication／Orchestrator Stateを機械可読形式で保持し、snapshotと差分を追跡できる。
2. Orchestratorが現在Stateから次Task候補を生成できる。
3. Context BuilderがAccess policyに従い、RunごとのContext Packを自動生成できる。
4. 少なくともMock Workerと一つのLocal Worker BackendでContext Pack→Output回収を再現できる。
5. Worker OutputをSchema検証し、Audit結果とともにState Reducerへ渡せる。
6. State ReducerがResearch HandoffとState Delta Proposalを作り、反証・Unknownを保持できる。
7. Publication ExporterがResearch Draftを含めず、Publication Eligible input bundleを作れる。
8. Publication Feedbackを自動routingできる。
9. Decision BrokerがHuman Decision Packetを生成し、Decision待ちで該当経路を停止し、記録後に自動Resumeできる。
10. 最初のユースケース「Theme/Expectations→独立Question Candidate→Seed比較→Desktop Research準備」を、人間の手動Context Pack組立てなしで通せる。
11. VIRTUAL／REAL、Research／Publication、Archive／Active、QuarantineのContext混入を自動テストで検出できる。
12. `reference`のような曖昧なArtifact roleを受理せず、全主要Artifactがrole／authority／lane／runtime_policyを持つ。
13. G1等の`HISTORICAL_CALIBRATION_SOURCE`、旧正本等の`SUPERSEDED_CANONICAL_PROVENANCE`、前走Simulation等の`SIMULATION_PROVENANCE`が通常Research／Publication Context Packへ入らないことを自動テストできる。
14. `ATTENTION_PUBLICATION_MAP`がQuestion Planning／Publication Planningへ利用できる一方、EvidenceとしてClaimを支持せず、方法・答えを決め打ちできないことを検査できる。
15. すべてのState遷移からRun、Context Pack、Input hash、Decisionへ戻れる。

# Companion ContractsとDesign Provenance

この一覧はRuntime Access権を付与する「参考資料一覧」ではない。Runtimeで利用できるかはArtifact RegistryとRuntime Artifact Policyだけで決定する。

## Active companion contracts / maps

- `MISCO_Research_Constitution_v0.1.md`：Research Harnessが常時守る最小原則。Research Evidenceではない。
- `MISCO_Research_Attention_and_Initial_Publication_Map_v0.1.md`：現行章・節構成から蒸留したAttentionと初期Publication topology。Research Evidenceではなく、章配置は破壊可能。
- `MISCO_Runtime_Artifact_Policy_v0.1.yaml`：Artifact role、Authority、Lane、Task Event別Runtime policyを規定する機械可読契約。
- `misco-publication-writer_RC1`：Publication LaneのWriter責任境界。Runtime Style AuthorityはRC1が要求するHuman Approved Clean Source PackとFormal Specに限定する。
- `MISCO_Publication_Writer_RC1_修正依頼_v0.1`：Harnessとの接続契約更新案。
- `MISCO_PROJECT_KNOWLEDGE_VIRTUAL_RUN_FEEDBACK_v0.1`：前走VIRTUALシミュレーションからの設計フィードバック。Research Evidenceではない。

## Design / migration provenance — normal runtime DENY

- 資料1～5現行版：本Change Proposalの差分確認・移行判断のためのProvenance。新設計採用後は旧正本Archiveへ退役する。
- 2025年度G1研究会報告書：Publication Writerのdesign-time calibration provenance。採用済み書き味はClean Source Packへ蒸留し、Runtimeでは読まない。
- 前走Simulation、旧RQ、旧Model、旧成果物：設計欠陥・Change Impact監査用Provenance。通常Research／Publication Runtimeでは読まない。

Archive資料を読むことが必要な場合は、`CONTRACT_MIGRATION_REVIEW`または`PROVENANCE_AUDIT`等の明示EventとAccess記録を要求する。Workerが「参考になりそう」という理由で自動取得してはならない。
