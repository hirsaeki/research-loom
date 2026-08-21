# Human Approved Source Rule Index

This is a runtime lookup index of the 51 approved Layer A rules. It is not a new rule set.

## Runtime source isolation note

This index is the only runtime style-rule authority alongside the other Human Approved Layer A references. Historical papers/corpora are not runtime sources and are not retrieved by this Skill. If historical observations are ever used outside runtime for design-time calibration, they must be distilled, sanitized, and human-approved into the Clean Source Pack before the runtime Writer can use them. This Release Candidate has no historical corpus or runtime RAG dependency.


| Rule ID | Strength | Owner | Approved rule |
|---|---|---|---|
| PUB-FR-01 | REQUIRED | Formal | 現行の頁設定、本文・見出しの書体、字下げ等は正式文書仕様に従う。 |
| PUB-FR-02 | REQUIRED | Formal | 見出しは正式な見出し階層を使い、独自の平行階層を増やさない。 |
| PUB-FR-03 | REQUIRED | Formal | 本文は原則として「である調」とし、挨拶文・謝辞・提言見出しの行動を示す表現は別機能として扱う。 |
| PUB-FR-04 | REQUIRED | Formal | 要約は現行MISCO固有要領の範囲内に収め、経営への提言を含める。 |
| PUB-FR-05 | DEFAULT | Formal | 本文は50〜60頁を標準的な編集目標とし、研究内容上必要な場合は70頁程度まで許容する。超過時は冗長性と付録移管可能性を確認する。 |
| PUB-FR-06 | REQUIRED | Formal | 図は題名を下、表は題名を上に置き、正式な番号で一意に参照する。 |
| PUB-FR-07 | REQUIRED | Formal | 外部図表・引用には出典を近接表示し、著者・題名・発行元・年・頁等を正式文書仕様に沿って示す。 |
| PUB-FR-08 | REQUIRED | Formal | 補足説明・用語解説は原則としてWord脚注を使い、本文の論理線から分離する。 |
| PUB-FR-09 | REQUIRED | Formal | 目次・本文・添付資料の頁付け、および研究会種別等で異なる外側の構成は現行MISCO要領に従う。 |
| PUB-FR-10 | REQUIRED | Formal | ヒアリング・社内情報は掲載可否、社名開示、原稿確認等の公開条件を事前に満たす。 |
| PUB-AR-01 | DEFAULT | Publication | 序論は話題の重要性だけで終えず、読者にとって未解決の問題を明示して研究目的へ接続する。 |
| PUB-AR-02 | DEFAULT | Publication | 外部環境から組織・MISCOの問題へ狭める際は、なぜ外部事実が内部課題に関係するかの橋渡しを置く。 |
| PUB-AR-03 | CONDITIONAL | Publication | 主要語・対象範囲に曖昧性がある場合は、分析前に定義と除外範囲を示す。 |
| PUB-AR-04 | DEFAULT | Publication | 研究目的は、何を明らかにするかと、どの根拠・観測結果・方法で迫るかを近い位置に置く。 |
| PUB-AR-05 | DEFAULT | Publication | 序論末では、本論の構成または調査・分析の流れを短く予告する。 |
| PUB-AR-06 | DEFAULT | Publication | 章頭では前章の到達点と本章の仕事を短く示す。 |
| PUB-AR-07 | CONDITIONAL | Publication | 複数方法を使う場合は、各方法が何を補うかを読者に説明する。 |
| PUB-AR-08 | CONDITIONAL | Publication | 提言の前には、その提言が必要になる承認済み根拠・分析の到達点を読者から追える位置に置く。 |
| PUB-AR-09 | CONDITIONAL | Publication | 提言を提示する箇所では、原則として新しい主要な根拠・観測結果を追加せず、承認済み分析と提言の対応を追えるようにする。 |
| PUB-AR-10 | DEFAULT | Publication | 終盤では主要結論に加え、承認済みの適用範囲・未解決課題・次の検討条件を示す。 |
| PUB-EV-02 | CONDITIONAL | Publication | 長い説明を整理する必要がある場合、段落冒頭で主題を示してから詳細を展開する書き方を選択肢として使える。 |
| PUB-EV-03 | DEFAULT | Publication | 観測されたことを先に書き、承認済みの解釈を後に置く。 |
| PUB-EV-04 | DEFAULT | QA-boundary | 断定の強さは承認済みの根拠・観測結果に合わせ、「示す」「示唆する」「考えられる」「可能性」等を使い分ける。 |
| PUB-EV-05 | DEFAULT | QA-boundary | 推論・仮定・推定は、その身分が分かる語で明示する。 |
| PUB-EV-06 | CONDITIONAL | QA-boundary | 研究側で承認済みの代替説明・測定不能範囲・不確実性がある場合、それを読者から見える位置に示す。 |
| PUB-EV-07 | CONDITIONAL | Publication | 外部文献・統計は、内容紹介、本研究との関係、承認済み解釈の順で接続する。 |
| PUB-EV-08 | CONDITIONAL | Publication | 複数資料を扱う場合、研究側で確認済みの資料間関係のうち論点に必要なものを整理し、本研究での使用目的を示す。固定した整理項目セットを要求しない。 |
| PUB-EV-09 | REQUIRED | Formal | 接続語は論理関係を示す目的で使い、対比・推論・補足等の役割を混同しない。 |
| PUB-EV-10 | DEFAULT | Publication | 同じ主張の反復は、要約・章末・提言等の機能境界に限定し、本文内部の言い換え連打を避ける。 |
| PUB-QT-01 | CONDITIONAL | Publication | 図表の前に、読者が何を見るべきかを短く示す。 |
| PUB-QT-02 | CONDITIONAL | Publication | アンケート・定量図表には、n、分母、複数回答等の読み方を題名または近傍に明示する。 |
| PUB-QT-03 | CONDITIONAL | Publication | 図表後の本文は主要値・差分・順位だけを再掲し、全セルを読み上げない。 |
| PUB-QT-04 | CONDITIONAL | QA-boundary | アンケート・定量結果では、研究側で承認済みのサンプル範囲・適用範囲・限定・不確実性を本文で明示する。一般化・因果の妥当性判定は別の確認へ送る。 |
| PUB-QT-05 | CONDITIONAL | QA-boundary | 研究上の問い・研究目的・仮説・検証論点等との関係は、研究側で承認済みの判定がある場合のみ、その判定を適切な強度で表現する。 |
| PUB-QT-06 | CONDITIONAL | QA-boundary | 測定の限界・不確実性は結果の近傍または考察で明示し、数値の意味を限定する。 |
| PUB-QL-01 | CONDITIONAL | Publication | 事例・ヒアリングを使う前に、選定理由と研究上の役割を示す。 |
| PUB-QL-02 | CONDITIONAL | Publication | 事例本文は事実・発言・観察を先に置き、研究側の承認済み評価・意味付けは別文または別段落にする。 |
| PUB-QL-03 | CONDITIONAL | Publication | 複数事例は、研究側で承認済みの比較軸がある場合、その軸で比較可能な形に揃えて書く。 |
| PUB-QL-04 | CONDITIONAL | Publication | 個別事例の後は、研究側で承認済みの共通点・差異・例外・不明点等を横断整理してから一般論へ進む。 |
| PUB-QL-05 | REQUIRED | Formal | 匿名化・社名開示・原稿確認の状態を守り、事例を代表例として過剰一般化しない。 |
| PUB-MF-01 | GUARD | QA-boundary | 研究側でモデル・枠組みの導入・構成が承認済みの場合のみ、その形成理由・位置づけ・構成・適用範囲を文章化する。Publication側でモデル採用・構成を決めない。 |
| PUB-MF-02 | CONDITIONAL | Publication | 研究側でモデル・枠組みと、その形成理由・分析結果との関係が承認済みの場合、その関係をモデル提示前後で説明する。 |
| PUB-MF-03 | CONDITIONAL | Publication | モデルの目的・適用位置・構成要素を本文で定義する。 |
| PUB-MF-04 | CONDITIONAL | Publication | モデル図を置いたら、本文で各要素の意味・関係を説明する。 |
| PUB-MF-05 | CONDITIONAL | Publication | 実施方法が研究側で承認済みかつ研究範囲内の場合、主体・手順・入力・判断等のうち存在する要素を説明する。 |
| PUB-MF-06 | CONDITIONAL | QA-boundary | 効果・効用は成立条件と限界を併記し、未検証効果は期待値として書く。 |
| PUB-RC-01 | CONDITIONAL | Publication | 提言見出しは、可能な限り主体と行動方向が一読で分かる表現にする。 |
| PUB-RC-02 | CONDITIONAL | Publication | 提言本文では、研究側で承認済みの根拠・主体・行動・条件・期待効果等のうち必要な要素を対応付ける。要素数・順序を固定しない。 |
| PUB-RC-03 | GUARD | QA-boundary | 提言数・柱数・分類数は研究側で承認済みの構成を用い、Publication側では決めない・補完しない。文章・編集ルールで固定しない。 |
| PUB-RC-04 | CONDITIONAL | Publication | 要約と本論で同じ提言を繰り返す場合、名称・順序・対応関係を一致させる。 |
| PUB-RC-05 | CONDITIONAL | QA-boundary | 命令形・感嘆符は根拠・観測結果を強める装置として使わない。明快さは保ちつつ、本文の断定の強さは承認済み分析に合わせる。 |
