# 03_RHETORICAL_PATTERN_LIBRARY

Pattern は全てを使うテンプレートではない。**APPLIES_WHEN（この書き方を使う条件）を満たす場合だけ**選択する。

## PAT-01 — 背景から研究目的への絞り込み
- **APPLIES_WHEN:** 研究側に承認済みの問題・対象範囲・研究目的と、背景との関係がある場合
- **Required approved input:** 承認済みの外部事実、対象との関係、研究目的・対象範囲
- **Reader-facing purpose:** 背景を研究目的へ収束させ、読者が「なぜこの研究を行うのか」を追えるようにする
- **Suggested sequence:** 背景 → 対象との関係 → 研究目的
- **Must not infer:** 外部事実から対象組織の因果を断定しない。入力にない「ギャップ」を作らない
- **Exit / next connection:** 研究目的または対象範囲へ
- **Skip condition:** 承認済み関係がなければ使わない

## PAT-02 — 外部資料・文献の整理
- **APPLIES_WHEN:** 複数資料と、研究側で確認済みの資料間関係・使用目的がある場合
- **Required approved input:** 複数資料、承認済み資料間関係、使用目的
- **Reader-facing purpose:** 資料の列挙ではなく、研究で使う意味を読者に示す
- **Suggested sequence:** 必要な関係だけを整理 → 本研究での使用目的
- **Must not infer:** 固定の整理項目セットを要求しない。資料間関係を新規発見しない
- **Exit / next connection:** 定義、研究目的、分析軸等へ
- **Skip condition:** 資料間関係が未承認なら個別資料の説明に留める

## PAT-03 — 研究目的への接続
- **APPLIES_WHEN:** 承認済みの問題・研究目的・方法または範囲がある場合
- **Required approved input:** 承認済み問題、研究目的、対象範囲、使用方法
- **Reader-facing purpose:** 問題の残存から研究目的へ自然に接続する
- **Suggested sequence:** 問題の残存 → 研究目的 → 方法・範囲（承認済みのもの）
- **Must not infer:** 目的文へ結論を先取りしない。成果用途を補完しない
- **Exit / next connection:** 論文構成または調査・検証方法へ
- **Skip condition:** 研究目的や方法が未承認なら使わない

## PAT-04 — 調査・検証方法の導入
- **APPLIES_WHEN:** 承認済みの方法・対象・制約・役割がある場合
- **Required approved input:** 方法、対象、期間、制約、各方法の役割
- **Reader-facing purpose:** 結果をどう読むかの前提を与える
- **Suggested sequence:** 何を観測するか → 方法 → 対象・期間 → 制約 → 他方法との役割
- **Must not infer:** 方法の妥当性を判定しない。RQ・仮説を新規生成しない
- **Exit / next connection:** 結果の読み方、評価軸へ
- **Skip condition:** 方法情報が不足する場合は研究側へ戻す

## PAT-05 — 図表の導入
- **APPLIES_WHEN:** 承認済み図表と、確認すべき論点・読み方が入力にある場合
- **Required approved input:** 図表、読者が確認すべき論点、n・単位等
- **Reader-facing purpose:** 図表を突然置かず、見る目的を先に示す
- **Suggested sequence:** 見る目的 → 必要な読み方 → 図表
- **Must not infer:** 入力にない解釈を作らない
- **Exit / next connection:** 表示後の主要結果へ
- **Skip condition:** 見るべき論点・読み方が不要な単純表では短縮可

## PAT-06 — 定量結果の読み取り
- **APPLIES_WHEN:** 数値だけでなく、承認済み解釈・限定・次の接続先がある場合
- **Required approved input:** 承認済み数値、解釈、限定、次の接続先
- **Reader-facing purpose:** 主要結果を本文で読み、次の論点へ渡す
- **Suggested sequence:** 主要値 → 承認済み比較・解釈 → 承認済み限定 → 次の接続
- **Must not infer:** 母集団一般化・因果化・全数値読み上げをしない。意味・限界を新規発見しない
- **Exit / next connection:** 次設問、ヒアリング、考察等へ
- **Skip condition:** 解釈がなければ観測の記述までで止める

## PAT-07 — ヒアリング・事例の記述
- **APPLIES_WHEN:** 事例事実・許諾・選定理由があり、解釈を書く場合は承認済み解釈がある場合
- **Required approved input:** 事例事実、許諾、選定理由、承認済み解釈（ある場合）
- **Reader-facing purpose:** 事例の役割と事実を先に示し、解釈との境界を保つ
- **Suggested sequence:** 事例の役割 → 事実・発言 → 背景 → 承認済み解釈
- **Must not infer:** 発言を一般事実化しない。匿名条件を破らない。解釈がなければ事実で止める
- **Exit / next connection:** 複数事例の横断整理等へ
- **Skip condition:** 事例・許諾・選定理由がない場合は使わない

## PAT-08 — 想定と異なる結果・例外の扱い
- **APPLIES_WHEN:** 不一致に対する研究側の承認済み評価・修正内容がある場合。未承認なら不一致の明示まで
- **Required approved input:** 想定と異なる結果、承認済み影響評価・修正内容（ある場合）
- **Reader-facing purpose:** 不都合な結果を隠さず、研究側の承認済み扱いを正確に見せる
- **Suggested sequence:** 不一致を明示 → 承認済み意味・影響 → 承認済み修正。未承認なら停止
- **Must not infer:** Writerが必要な修正や新しい結論を決めない
- **Exit / next connection:** 修正版説明または研究側への戻しへ
- **Skip condition:** 不一致がない場合は使わない

## PAT-09 — 限界・不確実性の扱い
- **APPLIES_WHEN:** 適用範囲・制約・残課題が研究側で承認済みの場合
- **Required approved input:** 承認済み適用範囲、制約、残課題
- **Reader-facing purpose:** 読者に「言える範囲／言えない範囲」を見せる
- **Suggested sequence:** 承認済みの言える範囲・言えない範囲 → 影響 → 残課題
- **Must not infer:** 新しい限界判定・追加検証設計をしない
- **Exit / next connection:** 慎重な結論・提言へ
- **Skip condition:** 承認済み限界等がない場合は作らない

## PAT-10 — 複数結果から上位の整理を行う場合
- **APPLIES_WHEN:** 上位整理・分類・まとめが研究側で既に承認済みの場合
- **Required approved input:** 承認済み上位整理・分類、形成理由、適用範囲
- **Reader-facing purpose:** 承認済みの上位整理がどのように位置づくかを説明する
- **Suggested sequence:** 形成理由 → 承認済み上位整理 → 適用範囲
- **Must not infer:** 分類数を先に決めない。Writerが共通構造・分類を新規発見しない
- **Exit / next connection:** 考察、必要ならモデル・枠組みへ
- **Skip condition:** 上位整理が存在しない場合は使わない

## PAT-11 — モデル・枠組みを提示する場合
- **APPLIES_WHEN:** モデル・枠組み、その構成・関係・形成理由が研究側で承認済みの場合
- **Required approved input:** 承認済みモデル、構成要素・関係・形成理由・適用範囲
- **Reader-facing purpose:** モデルを図だけでなく本文で使える形にする
- **Suggested sequence:** 形成理由 → 目的 → 構成 → 関係 → 適用範囲
- **Must not infer:** Writerがモデル・要素・関係を作らない
- **Exit / next connection:** 利用方法、検証、提言等へ
- **Skip condition:** 承認済みモデルがない場合は使わない

## PAT-12 — モデル・枠組みを修正する場合
- **APPLIES_WHEN:** 修正版と変更点・理由が研究側で承認済みの場合
- **Required approved input:** 承認済み旧モデル、修正版、変更点・変更理由、残る不確実性
- **Reader-facing purpose:** 承認済み修正の理由と変更内容を読者へ説明する
- **Suggested sequence:** 既存モデル → 不整合 → 承認済み変更 → 残る不確実性
- **Must not infer:** Writerが修正箇所・新定義を作らない。未承認なら不整合の記述で停止
- **Exit / next connection:** 再評価、提言等へ
- **Skip condition:** 承認済み修正版がなければ使わない

## PAT-13 — 複数事例の横断整理
- **APPLIES_WHEN:** 共通点・差異・例外・一般化範囲が研究側で承認済みの場合
- **Required approved input:** 承認済み比較軸、比較結果、一般化範囲
- **Reader-facing purpose:** 個別事例を承認済み横断結果へまとめる
- **Suggested sequence:** 承認済み共通点・差異・例外 → 一般化範囲 → 次の意味
- **Must not infer:** 比較軸・比較結果をWriterが生成しない。事例数を無視して一般化しない
- **Exit / next connection:** 上位整理、提言等へ
- **Skip condition:** 複数事例または承認済み横断結果がなければ使わない

## PAT-14 — 提言への接続
- **APPLIES_WHEN:** 提言とその根拠・適用範囲が研究側で承認済みの場合
- **Required approved input:** 承認済み提言、その根拠、適用範囲
- **Reader-facing purpose:** 既出分析から提言へ読者をつなぐ
- **Suggested sequence:** 既出分析の到達点 → 承認済み提言への接続
- **Must not infer:** 新しい主要根拠・実務含意・提言目的をWriterが作らない
- **Exit / next connection:** 個別提言へ
- **Skip condition:** 承認済み提言がなければ使わない

## PAT-15 — 提言の記述
- **APPLIES_WHEN:** 主体・行動・条件・期待効果等、研究側で承認済み要素が存在する場合
- **Required approved input:** 承認済み提言と存在する主体・行動・条件・期待効果等
- **Reader-facing purpose:** 提言を読者が実際に理解できる形へ整える
- **Suggested sequence:** 存在する要素を対応付けて説明。順序は内容に応じる
- **Must not infer:** 件数・要素数・順序を固定しない。未検証効果を断定しない
- **Exit / next connection:** 次提言、実施方法等へ
- **Skip condition:** 提言がない、または必要要素が未承認なら作らない

## PAT-16 — 章頭
- **APPLIES_WHEN:** 前章・本章の役割・使用材料が既存構成上確定している場合
- **Required approved input:** 承認済み章構成、前章の到達点、本章の役割
- **Reader-facing purpose:** 章間の断絶を減らし、読者の位置を示す
- **Suggested sequence:** 前章の到達点 → 本章の役割 → 必要なら章内順序
- **Must not infer:** 前章を長く再要約しない。新しい到達点を認定しない
- **Exit / next connection:** 第1節へ
- **Skip condition:** 前章参照が不要な箇所では短縮する

## PAT-17 — 章末
- **APPLIES_WHEN:** 本章の承認済み到達点・限定・次章接続がある場合
- **Required approved input:** 承認済み本章到達点、限定、次章接続
- **Reader-facing purpose:** 本章の役割を閉じ、次へ渡す
- **Suggested sequence:** 要点 → 限定 → 次章で使う形
- **Must not infer:** 新しい論点・新しい結論を追加しない
- **Exit / next connection:** 次章へ
- **Skip condition:** 短章・次章接続が不要な場合は省略可

## PAT-18 — 最終総括
- **APPLIES_WHEN:** 研究側に存在する目的・主要結果・提言・限界・残課題等のうち総括対象が承認済みの場合
- **Required approved input:** 承認済み研究目的、主要結果、提言、限界、残課題等のうち存在するもの
- **Reader-facing purpose:** 存在する要素だけで報告書を閉じる
- **Suggested sequence:** 存在する要素を選び、内容に応じて総括。数・順序・章名は固定しない
- **Must not infer:** 要約の逐語反復、未来の断定、入力にない実務含意・次課題を作らない
- **Exit / next connection:** 報告書を閉じる
- **Skip condition:** 総括対象がない場合はWriterが作らず、必要なら研究側へ戻す
