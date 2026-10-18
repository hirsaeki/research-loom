# 09_SYNTHETIC_FEWSHOT_SPECIFICATION

**Few-shot本文はこの段階では作成しない。** 架空の承認済み研究情報だけを使い、過年度の文章・数値・出典・情報源・モデルをコピーしない。

固定禁止: 段落数、提言数、Finding数、Model要素数、段階数、Case数、RQ数、Limitation数。

## SF-01
- **Purpose:** 背景→研究目的
- **Required approved synthetic input:** 架空の承認済み外部事実、対象との関係、研究目的
- **Writer transformation:** 短い背景説明から研究目的へ接続する
- **Negative space:** 新しい問題・ギャップ・因果を作らない
- **Prohibited invention:** 外部統計から対象組織の因果を断定しない
- **Rule IDs trained:** PUB-AR-01/02/04, PUB-EV-04/07
- **Variation dimensions:** 背景事実の量、関係の長さ、研究目的の表現。段落数は可変

## SF-02
- **Purpose:** 定義境界
- **Required approved synthetic input:** 架空の承認済み定義、含む範囲・含まない範囲、定義理由
- **Writer transformation:** 定義境界を読者向けに説明する
- **Negative space:** 定義項目数を固定しない
- **Prohibited invention:** 新しい定義・除外範囲を作らない
- **Rule IDs trained:** PUB-AR-03, PUB-EV-05
- **Variation dimensions:** 用語の複雑さ、境界数、定義理由の有無

## SF-03
- **Purpose:** 複数方法の役割説明
- **Required approved synthetic input:** 架空の承認済み方法、各方法の役割・対象・制約
- **Writer transformation:** 方法の役割と補完関係を説明する
- **Negative space:** 方法の順序・数を固定しない
- **Prohibited invention:** 方法の正当性、研究上の問いをWriterが新規生成しない
- **Rule IDs trained:** PUB-AR-04/07, PUB-EV-05
- **Variation dimensions:** 方法数、役割の組み合わせ、制約の量、掲載順

## SF-04
- **Purpose:** アンケート表の読み取り
- **Required approved synthetic input:** 架空数値、読み方、承認済み解釈・限定・次の接続先
- **Writer transformation:** 表前文→主要値→承認済み解釈・限定→次の接続
- **Negative space:** 強調する値の数を固定しない
- **Prohibited invention:** 全数値読み上げ、母集団一般化、意味・限界の新規推論をしない
- **Rule IDs trained:** PUB-EV-03〜06, PUB-QT-01〜06
- **Variation dimensions:** 表サイズ、主要値数、解釈の有無、限定の種類

## SF-05
- **Purpose:** 仮説の修正（仮説型研究のみ）
- **Required approved synthetic input:** 承認済み旧仮説、架空結果、承認済み関係判定、承認済み修正版仮説
- **Writer transformation:** 修正理由と変更内容を読者向けに説明する
- **Negative space:** 仮説数・修正幅を固定しない
- **Prohibited invention:** 支持判定・仮説修正をWriterが行わない。修正版がなければ停止
- **Rule IDs trained:** PUB-QT-05, PUB-EV-03/04/05
- **Variation dimensions:** 仮説数、判定種類、修正幅、残る不確実性

## SF-06
- **Purpose:** 定性事例
- **Required approved synthetic input:** 架空事例事実、許諾、選定理由、承認済み比較軸・比較結果
- **Writer transformation:** 事実記述→承認済み比較の説明
- **Negative space:** 事例数・比較軸数を固定しない
- **Prohibited invention:** 共通点・差異の発見、一般化をWriterが行わない
- **Rule IDs trained:** PUB-QL-01〜05, PUB-EV-03/05
- **Variation dimensions:** 事例数、匿名条件、比較軸の数、解釈の有無

## SF-07
- **Purpose:** 情報不足なので書かない／研究側へ戻す
- **Required approved synthetic input:** 提言・モデル・解釈等を確定できない架空の不足状態
- **Writer transformation:** 不足項目を明示し、新規結論・モデル・提言を書かず研究側へ戻す
- **Negative space:** 不足の種類・個数を固定しない
- **Prohibited invention:** Evidence不足を文章で補完しない
- **Rule IDs trained:** PUB-MF-01, PUB-RC-03, PUB-QT-05, PUB-EV-06, PUB-AR-09
- **Variation dimensions:** 不足要素の種類、入力の充足度、停止するPhase

## SF-08
- **Purpose:** 実験・PoC結果
- **Required approved synthetic input:** 架空の承認済み条件、評価基準、結果、限界
- **Writer transformation:** 評価基準→結果表→承認済み解釈・限界
- **Negative space:** 評価段階・カテゴリ数を固定しない
- **Prohibited invention:** 評価軸・実用性結論をWriterが作らない
- **Rule IDs trained:** PUB-QT-01/03〜06, PUB-EV-03〜05
- **Variation dimensions:** 評価軸数、カテゴリ数、結果形式、限界の量

## SF-09
- **Purpose:** モデル／枠組みの導入（必要時のみ）
- **Required approved synthetic input:** 承認済みモデル・枠組み、要素、関係、形成理由、適用範囲
- **Writer transformation:** 形成理由→構成→図の読み→使い方・条件（存在時）
- **Negative space:** 要素数・段階数・関係形を固定しない
- **Prohibited invention:** モデル・要素・関係をStyle側で発明しない
- **Rule IDs trained:** PUB-MF-01〜06, PUB-QT-01
- **Variation dimensions:** 要素数、図形、適用範囲、実施方法の有無

## SF-10
- **Purpose:** モデル／枠組みの修正（必要時のみ）
- **Required approved synthetic input:** 承認済み旧モデル、架空結果、承認済み修正版・変更点・変更理由
- **Writer transformation:** 不整合→承認済み修正内容→残る不確実性
- **Negative space:** 変更点数・段階数を固定しない
- **Prohibited invention:** 修正内容・新定義をWriterが作らない
- **Rule IDs trained:** PUB-MF-01/02, PUB-EV-05/06
- **Variation dimensions:** 変更点数、変更理由、残る不確実性、再評価の有無

## SF-11
- **Purpose:** 提言
- **Required approved synthetic input:** 承認済み提言、その根拠・主体・行動・条件・期待効果等の存在する要素
- **Writer transformation:** 承認済み要素を対応付けた提言文章
- **Negative space:** 提言数・要素数・順序を固定しない
- **Prohibited invention:** 提言内容・期待効果をWriterが作らない
- **Rule IDs trained:** PUB-AR-08/09, PUB-RC-01〜05, PUB-MF-06
- **Variation dimensions:** 提言数、主体の粒度、条件の有無、期待効果の強度

## SF-12
- **Purpose:** 章頭／章末
- **Required approved synthetic input:** 承認済み章構成、前章到達点、本章役割、次接続
- **Writer transformation:** 短い章頭・章末のnavigation
- **Negative space:** 文数・章数を固定しない
- **Prohibited invention:** 新しい章要約・到達点を発明しない
- **Rule IDs trained:** PUB-AR-05/06, PUB-EV-10
- **Variation dimensions:** 章の長さ、接続の強さ、前章参照の有無

## SF-13
- **Purpose:** 最終総括＋限界
- **Required approved synthetic input:** 承認済み研究目的、主要結果、提言、限界・残課題のうち存在するもの
- **Writer transformation:** 存在する要素だけで終盤を総括する
- **Negative space:** 結果数・提言数・限界数・順序を固定しない
- **Prohibited invention:** 実務含意・次課題を入力なしに作らない
- **Rule IDs trained:** PUB-AR-10, PUB-EV-04/06/10, PUB-RC-04
- **Variation dimensions:** 要素の組み合わせ、件数、総括順、提言の有無

## SF-14
- **Purpose:** 正式書式
- **Required approved synthetic input:** 架空図表・脚注・Web出典と、利用可能な正式rendering要件
- **Writer transformation:** 正式な図表題・脚注・出典形式へ変換する
- **Negative space:** 図表数・脚注数を固定しない
- **Prohibited invention:** 過年度の出典・情報源・書式variantを流用しない
- **Rule IDs trained:** PUB-FR-01〜10, PUB-EV-09, PUB-QL-05
- **Variation dimensions:** 図/表/脚注/出典の組み合わせ、研究会種別メタデータの有無
