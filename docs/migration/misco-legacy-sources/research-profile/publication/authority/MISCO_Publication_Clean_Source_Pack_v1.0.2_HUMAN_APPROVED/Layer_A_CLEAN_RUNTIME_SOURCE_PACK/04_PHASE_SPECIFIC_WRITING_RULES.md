# 04_PHASE_SPECIFIC_WRITING_RULES

## Background / research purpose
- **INPUT:** approved_problem, approved_research_purpose, approved_scope, approved_external_materials_if_any, approved_external_material_relations_if_any
- **ALLOWED TRANSFORMATION:** 承認済み背景を問題と研究目的へ絞る。外部資料は研究との関係を示し、目的・範囲を近接配置する。
- **PROHIBITED INFERENCE:** 新しい問題設定、研究上の問い、因果、未確認の資料間関係を作らない。
- **OUTPUT FUNCTION:** 読者が「何が問題で、何を明らかにする研究か」を追える序論。
- **QA CHECK:** PUB-AR-01/02/03/04/05, PUB-EV-07/08。目的・範囲・関係が入力にあるか。

## Method / investigation introduction
- **INPUT:** approved_methods, approved_scope, approved_uncertainties, publication_metadata
- **ALLOWED TRANSFORMATION:** 方法の対象・期間・制約・役割を整理し、複数方法なら補完関係を説明する。
- **PROHIBITED INFERENCE:** 方法の妥当性、RQ、仮説、必要性をWriterが新規判断しない。
- **OUTPUT FUNCTION:** 結果の読み方を支える調査・検証方法の導入。
- **QA CHECK:** PUB-AR-04/07, PUB-EV-05。必要な方法情報が欠けていないか。

## Quantitative result rendering
- **INPUT:** approved_observations, approved_interpretations, approved_uncertainties, approved_limitations, approved_figures_tables_if_any
- **ALLOWED TRANSFORMATION:** 主要値を選び、観測→承認済み解釈→承認済み限定の順で文章化する。
- **PROHIBITED INFERENCE:** 母集団一般化、因果、支持判定、代替説明を新規生成しない。全数値を読み上げない。
- **OUTPUT FUNCTION:** 数値の意味と読み方を過不足なく読者へ渡す結果記述。
- **QA CHECK:** PUB-EV-03/04/05/06, PUB-QT-01〜06。n・分母等と承認済み限定を落としていないか。

## Qualitative / case rendering
- **INPUT:** approved_cases_if_any, approved_case_comparison_if_any, approved_interpretations, publication_metadata.permission_status
- **ALLOWED TRANSFORMATION:** 選定理由→事実・発言→承認済み解釈の順で書き、複数事例は承認済み比較軸で揃える。
- **PROHIBITED INFERENCE:** 発言の一般事実化、成功モデル化、比較軸や一般化の新規生成をしない。
- **OUTPUT FUNCTION:** 事例の役割・事実・承認済み意味を区別した記述。
- **QA CHECK:** PUB-QL-01〜05, PUB-EV-03/05。許諾・匿名化・比較軸を確認。

## Figure / table rendering
- **INPUT:** approved_figures_tables_if_any, approved_observations, approved_interpretations, publication_metadata.figure_table_metadata
- **ALLOWED TRANSFORMATION:** 図表前に見る目的を示し、正式番号・題名・出典を付け、図表後に主要な承認済み読み取りを説明する。
- **PROHIBITED INFERENCE:** 図表を置いて終える、全セル音読、図表から新しい意味を発見することをしない。
- **OUTPUT FUNCTION:** 図表が本文の論点を進める視覚情報として機能する状態。
- **QA CHECK:** PUB-FR-06/07, PUB-QT-01/02/03, PUB-MF-04。番号・題名・出典・読み方・本文説明を確認。

## Discussion / interpretation rendering
- **INPUT:** approved_observations, approved_interpretations, approved_uncertainties, approved_limitations, approved_research_question_or_hypothesis_if_any
- **ALLOWED TRANSFORMATION:** 観測と承認済み解釈を分け、推定の身分と断定の強さを調整し、承認済み限定を近くに置く。
- **PROHIBITED INFERENCE:** 新しい解釈、因果、一般化、支持判定、仮説修正を行わない。
- **OUTPUT FUNCTION:** 研究側で承認済みの意味づけを、読者が事実と区別して理解できる考察。
- **QA CHECK:** PUB-EV-03〜06, PUB-QT-04/05/06。新しい判断が混入していないか。

## Model / framework rendering — only if approved model exists
- **INPUT:** approved_model_if_any, approved_model_revision_if_any, approved_implementation_details_if_any, approved_interpretations, approved_limitations
- **ALLOWED TRANSFORMATION:** 形成理由・目的・位置づけ・構成・関係・適用範囲・使い方のうち承認済みで存在するものを本文化する。
- **PROHIBITED INFERENCE:** モデルの採用・構成・要素数・段階数・分類をWriterが決めない。
- **OUTPUT FUNCTION:** 承認済みモデル・枠組みを図だけに依存せず理解できる説明。
- **QA CHECK:** PUB-MF-01〜06。モデルの存在と構成が承認済みか。なければPhase自体をスキップ。

## Recommendation rendering — only if approved recommendation exists
- **INPUT:** approved_recommendations_if_any, approved_recommendation_links_if_any or equivalent approved links, approved_limitations
- **ALLOWED TRANSFORMATION:** 既出分析の到達点から提言へつなぎ、承認済みの主体・行動・条件・期待効果等を必要範囲で説明する。
- **PROHIBITED INFERENCE:** 提言内容・件数・柱数・要素数・期待効果を作らない。根拠以上に強く見せない。
- **OUTPUT FUNCTION:** 承認済み提言を読者が追跡・理解できる行動記述。
- **QA CHECK:** PUB-AR-08/09, PUB-RC-01〜05, PUB-MF-06。提言が未承認なら生成せず研究側へ戻す。

## Chapter opening / closing
- **INPUT:** approved_chapter_structure_if_any or publication_metadata.output_scope, approved_conclusions_if_any, approved_limitations
- **ALLOWED TRANSFORMATION:** 章頭は前章の到達点→本章の役割、章末は要点→限定→次章接続を必要範囲で示す。
- **PROHIBITED INFERENCE:** 新しい章要約、新しい結論、新しい次課題を作らない。
- **OUTPUT FUNCTION:** 長い報告書で読者が現在地と次の流れを見失わない接続。
- **QA CHECK:** PUB-AR-06, PUB-EV-10。前後の役割が承認済みか。

## Executive summary
- **INPUT:** approved_research_purpose, approved_methods, approved_observations, approved_conclusions_if_any, approved_recommendations_if_any, approved_limitations, publication_metadata
- **ALLOWED TRANSFORMATION:** 承認済み要素を圧縮し、要約独自の新情報を入れず、正式要件の範囲に収める。提言が存在する場合は本論と名称・順序・対応を一致させる。
- **PROHIBITED INFERENCE:** 提言や結論を要約のために新規生成しない。項目数を固定しない。
- **OUTPUT FUNCTION:** 本論前に問題・方法・主要結果・提言・限界等を必要範囲で把握できる入口。
- **QA CHECK:** PUB-FR-04, PUB-EV-10, PUB-RC-04。正式要件上提言が必要で未承認なら `RETURN_TO_RESEARCH_REQUIRED`。

## Final synthesis / closing
- **INPUT:** approved_research_purpose, approved_observations, approved_conclusions_if_any, approved_recommendations_if_any, approved_limitations, approved_uncertainties
- **ALLOWED TRANSFORMATION:** 存在する承認済み要素だけで主要結果・提言・限界・残課題を総括し、要約とは役割を変えて閉じる。
- **PROHIBITED INFERENCE:** 未来の断定、入力にない実務含意・次課題・研究課題を作らない。
- **OUTPUT FUNCTION:** 報告書の到達点と適用範囲を明確にして閉じる。
- **QA CHECK:** PUB-AR-10, PUB-EV-10, PUB-EV-04/06。件数・章名・順序を固定していないか。
