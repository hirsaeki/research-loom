# #628 ChatGPT Work実機への引渡し

**未実施。#628とEpic #624のWork受入は未完了。**
Codexの構造検査、合成データの生成比較、モデルによる点検はWork実機の代替にしない。

## 対象と版を選ぶ

実機担当者が対象Workspaceを明示する。研究資料を持つWorkspaceをパスの近さで選ばない。
既存の状態とProfile履歴を確認し、必要な更新を本人が選択する。
[版選択](../../../profiles/README.md)と
[公開Profile操作](../../architecture/profile-generation-advancement.md)を使い、
Writer 1.4.0、Publication 1.6.0を使う場合は双方を明示要求する。
旧版をそのまま使う選択も保持する。依存のcompatible rangeを現行Writerの指定と読み替えない。
resolve結果のConfig/EPS・manifest pinsを確認してからadvanceする。
過去のPackage、入力、原稿、Decisionは変更しない。

Work実機では、通常のhost bootstrap、research-conversation、Writerの入口を
それぞれ明示的に読み込む。読み込んだbytes・版と、実際の入力にあるWriter pinを記録する。
開発側で同じファイルが存在したことを、ホストでの読込み確認として転記しない。

## 検証入力

まず[cases.json](cases.json)の二つを使う。

- `adopted-operation-unmeasured-effect`: 採択済みの具体的変更を明確に述べ、理由、例外と本人確認の維持、未測定の効果を保つ。
- `legitimate-hold-counterresult`: 通常8→6分/件と例外4→5分/件を対照し、一律展開の保留と例外案件の比較を明確に述べる。

これは架空の材料であり実際の研究Evidenceではない。準備済みのdetached入力を使うか、
隔離した合成Workspaceで既存のfixture手順から公開操作を通す。
実Workspaceに合成の採択やHuman Decisionを登録しない。
少なくとも一件はWork実機で次の公開経路全体を実行して記録する。

1. 固定Research Packageを確認し、対象Compositionをcapture/selectする。
2. `writer-round-trip export-input`で対象節を明示し、新しい出力先へ書き出す。
3. Workでそのdetached入力と配信規則だけから初回本文を生成し、そのまま保存する。
   対照条件の出力・採点結果を先に読まず、改善するまでの再生成で置き換えない。
4. responseを通常のimportに渡し、inspectで入力pin、保存稿、authorityとFeedbackを確認する。
5. 文書全体の点検を申告する場合は、公開`prepare-review`が返す現稿対象で点検し、
   exact-targetの`document_review`を付ける。[既存の手順](../../operations/writer-document-review.md)を使う。
6. 修正が必要なら具体箇所と修正方針を残し、exact current baseで変更節だけ再提出する。
   旧文書レビューを新稿へ流用しない。初回稿を保持する。

CLIの完全な形は[既存round-trip契約](../../architecture/versioned-writer-composition.md)
にある。人が手作業でdigestを作ったり、非公開の保存領域を読んで不足情報を補わない。

## 期待結果と失敗の記録

| 検査 | 期待結果・失敗条件 |
| --- | --- |
| 配信 | Packageの非空`must_include`が新exportのcommunicationに届く。禁止事項・pins・根拠・反証・留保が保持される。 |
| 明確な変更 | 通常案件の共通項目再利用と二重入力廃止を答える。未測定を理由に、会議・調査・PoCの検討へ置き換えたら結論消失。 |
| 効果の限界 | 時間短縮・誤入力減少を実証済みとしない。採択済み提言と実施済み施策を区別する。 |
| 正当な保留 | 一律展開を保留し、例外案件を比較する。強い導入判断を作ったら失敗。 |
| 反証 | 例外4→5分/件を本文で保持し、通常の低下と対照する。隠したり因果原因を補ったら失敗。 |
| 編集 | 中心主張、理由、判断を変える条件を別々に点検する。留保の数だけで不合格にせず、論旨を中断する具体箇所を示す。 |
| 履歴と権限 | 下書き・Feedbackは保存できる。研究採択・provenance・Human Decision・公開承認を文章生成で変更しない。 |
| レビュー失効 | 本文・引用・図表・順序・入力pinを変更した後、旧レビューを現稿の確認として使えない。 |

過大主張、無根拠な規範判断、反証脱落、結論消失、正当な保留の破壊を別々に報告する。
構造の成功、編集者の所見、実読者の理解を一つの総合点やPASSへ合算しない。
Workのモデル評価だけならreader-effect PASSを出さない。

## 残す記録と残存課題

担当者、実行日時、Workのホスト・表示モデル・取得できない設定、読み込んだ入口、
Profile/EPS/Package/Composition/input pins、固定prompt、長さ目標、初回本文、response、
import/inspect結果、review targetと所見、改稿前後を残す。
実施できなかった段階と理由も記録する。

Codex側では実際のWork環境、実研究Workspaceの選択版と節の充足、Workでの入口読込み、
Work上の初回生成と公開経路全体、実読者の理解は確認していない。
これらを確認せず#628を閉じない。追加の規則やProfile更新は、対照の結果と必要性が
示された場合だけ別の正規変更として検討する。

Codexでの[初回稿比較の所見と限界](assessment.md)は、Workの初回稿を固定してから参照する。
中心の答えの保持と、重みづけ・限定の正確さ・重複免責の編集課題を分けて点検するための
参考資料であり、Workで同じ結果になるという証明ではない。
