# 02_PUBLICATION_LANE_IO_CONTRACT

## 基本原則

文章作成側が使用してよい研究内容は、**その時点で研究側から承認済みの情報だけ**である。入力欄が存在していても、承認状態が明示されていない情報は使用しない。存在しない研究要素を「論文らしさ」や文章上の都合で補完しない。

各フィールドはスキーマ上は保持可能でも、**必要条件を満たしたときだけ使用する**。該当情報がない場合は、その要素を作らず、必要に応じて研究側へ戻す。

| Input field | 必須/任意の条件 | Publication Writer がしてよいこと | 入力がない場合 |
|---|---|---|---|
| `approved_problem` | 背景から未解決の問題へ絞る場合は必要 | 承認済み問題を背景から研究目的へ接続 | 問題を新規作成しない |
| `approved_research_purpose` | 全体報告書、要約、終盤総括、研究目的節を作る場合は必須 | 承認済み研究目的を読者向けに明確化 | `RETURN_TO_RESEARCH_REQUIRED` |
| `approved_scope` | 対象範囲・除外範囲・適用範囲がある場合は必要 | 承認済み範囲を明示 | 新しい境界を作らない |
| `approved_definitions_if_any` | 用語・対象範囲に曖昧性があり、定義が承認済みの場合のみ | 定義・含む範囲・含まない範囲を説明 | 定義を発明しない |
| `approved_methods` | 方法紹介、結果の読み方、要約で方法を書く場合は必要 | 方法・対象・期間・制約・役割を整理 | 方法を発明せず、必要なら研究側へ戻す |
| `approved_observations` | 結果を文章化する場合は必須 | 数値・事実・発言等を観測として記述 | 結果を作らない |
| `approved_interpretations` | 任意。解釈を書く場合のみ必要 | 承認済み解釈を観測と分けて表現 | 観測だけで止める |
| `approved_uncertainties` | 任意。存在するときは関係箇所で表示必須 | 承認済み不確実性を読者に見える形にする | 新しい不確実性を作らない |
| `approved_limitations` | 任意。存在するときは関係箇所または終盤で表示必須 | 承認済み限界・適用範囲を明示 | 新しい限界・追加検証計画を作らない |
| `approved_external_materials_if_any` | 外部資料を本文で使う場合のみ | 承認済み資料内容を正式出典とともに説明 | 過年度の資料を流用しない |
| `approved_external_material_relations_if_any` | 複数資料を横断整理する場合のみ | 研究側で確認済みの共通点・差異・条件等を必要範囲で整理 | 資料間関係を新規発見しない |
| `approved_figures_tables_if_any` | 図表を掲載する場合のみ | 図表、読み方、承認済み主要読み取りを文章化 | 図表から新しい意味を発見しない |
| `approved_cases_if_any` | ヒアリング・事例を扱う場合のみ | 事実、選定理由、役割、許諾条件、承認済み解釈を整理 | 代表性や成功要因を作らない |
| `approved_case_comparison_if_any` | 複数事例を比較する場合のみ | 承認済み比較軸・比較結果・一般化範囲を説明 | 比較軸・横断結果を作らない |
| `approved_chapter_structure_if_any` | 全体構成・章頭章末を文章化する場合のみ | 承認済み章構成と章の役割を案内する | 章順・章機能を作らない |
| `approved_research_question_or_hypothesis_if_any` | 研究側に実在する場合のみ | その存在と承認済み関係判定を必要に応じて表現 | RQ・仮説を要求・生成しない |
| `approved_classification_if_any` | 研究側で分類・上位整理が承認済みの場合のみ | 形成理由・包含関係・適用範囲を説明 | 分類数・分類名を作らない |
| `approved_model_if_any` | 承認済みモデル・枠組みがある場合のみ | 形成理由・目的・構成・関係・適用範囲を説明 | モデルを要求・生成しない |
| `approved_model_revision_if_any` | 承認済み修正版と変更理由がある場合のみ | 変更点・理由・残る不確実性を説明 | Writerが修正を決めない |
| `approved_implementation_details_if_any` | 実施方法が承認済みかつ研究範囲内の場合のみ | 存在する主体・手順・入力・判断等を説明 | 欠けた実施要素を補わない |
| `approved_recommendations_if_any` | 提言を掲載する場合のみ。正式要約で提言が必須なら条件付き必須 | 承認済み提言を既出分析へ接続し、存在する要素を説明 | 提言を新規作成しない。形式上必要なら研究側へ戻す |
| `approved_recommendation_links_if_any` | 提言と既出分析の対応を文章化する場合のみ | 承認済みの根拠・主体・行動・条件・期待効果等の対応を使う | 対応関係や欠けた要素を補完しない |
| `approved_conclusions_if_any` | 終盤総括・要約で結論を明示する場合のみ | 承認済み結論を適切な強さで再表現 | 新しい結論を作らない |
| `publication_metadata` | 全体正式書式を出す場合は必須 | 正式仕様分岐と公開条件に使用 | 必須値がなければ `HUMAN_DECISION_REQUIRED` |

## `publication_metadata` に必要となり得る情報

- `research_group_type`：外側の構成を分岐するために必要な場合。
- `formal_spec_profile`：Human Review HD-01=Aに従い、現行正式仕様原本を正本として供給される正式設定。Source Pack側で具体値を推測しない。
- `output_scope`：全体報告書、要約、特定章、図表説明等の依頼範囲。
- `permission_status`：ヒアリング・社内情報・社名開示・原稿確認の状態。
- `figure_table_metadata`：図表番号、題名、出典、n、分母、単位等の正式情報。
- `citation_metadata`：著者、題名、発行元、年、頁等、正式出典に必要な情報。長い raw URL をreader-facing表示する場合は、HD-03=Bで選択された人間承認済み統一URL表示プロファイルもここで与える。

## 入力契約上の停止条件

1. 文章化に必要な研究判断が未承認である → `RETURN_TO_RESEARCH_REQUIRED`。
2. 根拠と主張が本当に対応しているか、因果と言えるか等の判断が必要 → `SEND_TO_EVIDENCE_CLAIM_QA`。
3. 正式書式の具体値・研究会種別・公開条件等、研究内容ではない人間メタデータが不足 → `HUMAN_DECISION_REQUIRED`。
4. 「モデルを入れて」「提言を増やして」「分類して」等、入力にない研究成果物の生成を求められた → 生成せず研究側へ戻す。
