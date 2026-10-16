# #466 現稿レビューの対象一致と部分改稿

基点はPR #470のsquash merge `c3398da759f73ee2ec7db8dde31a9de966ef129d`。
#471のrequest manifestにあるartifact 12034790566を取得し、ZIP SHA-256
`b634ce797aecda3d2a57ed1ea9431ef11c796425092acc64a9225239441aa357`、bundle SHA-256
`16528d2404e854e41713d6370ee4211b8e6438f8de11725334333f26086f70a1`、full historyとHEADを照合した。
元の作業場所にあるユーザー変更3ファイルは変更していない。

## 変更と受入

- 任意の `document_review` を既存responseとrevisionに追加。省略時は従来の保存・部分改稿を継続する。
- 公開prepare-reviewでexact inputとbaseから対象本文を組み立て、既存canonical digestを返す。
  importでも同じprojectionを照合する。本文・引用・図表参照・順序・Profile pinsを対象に含める。
- 文書scopeの規則結果は既存の分類・outcome・groupを再利用し、構造・意味・編集を分けて表示する。
  部分点検、未評価、不正N/Aを文書conformantへ変換しない。
- 部分改稿で未変更節の本文・引用・図表・originを再利用するが、文書レビューは継承しない。
  旧recordは旧revisionに保持。exact responseの再送もVERIFIED_REUSEを維持する。
- 既存Writing Feedbackに具体的な対象・影響・編集案を残し、違反のある草稿でも継続できる。
  新Manager／DB／Profile rule ID／主観品質gateは作らない。

手順とprojectionの詳細は [運用文書](../../operations/writer-document-review.md)。
本機能はレビュー主体の申告を対象へ結び付けるもので、文章の意味・研究的妥当性・独立性・
Human承認や実際の読者効果をbackendが保証するものではない。

## 2026-10-16 実Host往復

[合成証跡](host-smoke.json)は#465で保存した比較ケースの新契約初回稿を使用する。
既存の隔離済みSYNTHETIC_TEST_ONLY fixtureを開き、公開prepare/import/inspectだけで往復した。
主担当Hostによる自己点検であり、独立レビューでも新たな人間評価でもない。
responseのgenerated_atとreviewed_atは合成fixtureの固定値で、実行時刻の計測値ではない。

1. 全4節と固定入力を点検し、文書scopeの `PUB-RC-04` のみsemantic conformantを申告した。
   逆方向の結果、原因未確認、保留・調査・追試後の範囲判断が導入・結果・提言で一致する。
   残りのProfile規則はsectionのUNEVALUATEDを維持し、Profile全体合格とはしていない。
2. 読者体験の所見は別のWriting Feedbackに記録した。結末のB即時中止の否定は軽微な重複で、
   ブロッカーではないというユーザー所見に対応する。本文を変えない点検recordをrevision 6へ保存した。
3. 同一response再送はVERIFIED_REUSE。
4. 結末の当該文を削り、適用範囲の判断材料を整える文へ置き換えた一節だけのresponseを作った。
   旧review付きでは対象不一致として拒否された。
5. 旧reviewを外した同じ改稿をrevision 7へ保存し、未変更3節の再利用と新稿unevaluatedを確認した。
   旧revision再読で旧record・本文の不変を確認した。すべてResearch State mutation=false。

読者体験の所見を意味違反へ昇格させず、意味の所見を読者効果の証明にもしていない。
本文を実際に直した事例であり、所見だけ・注意書き追加だけでは終わっていない。

## 検証

既存uv環境を `uv run --project <既存repo> --frozen --no-sync python -m unittest discover ...` で使用。
追加installなし。

| 範囲 | 結果 |
| --- | --- |
| #466 公開prepare/import/inspect・CLI・不一致／部分点検の回帰 | 7成功 |
| 既存契約 | 314成功 |
| #219 Writer round-trip | 9成功 |
| #464 規則scope・分類 | 5成功 |
| 旧MISCO Writer Profile | 6成功 |
| #249 Writer復旧 | 10成功 |

targetのunit対照では固定入力digestと節順の変更を検査し、公開経路では本文、引用のみ、
図表のみ、Composition変更による入力更新を確認した。Profile-onlyの新しい公開fixtureは作らず、
input_digestがProfile pinsを包含する既存の配信・exact-context検査と合わせて担保する。
正式Publication/PDFの組版QAは本受入の対象外。CI/KodyはPRの最終HEADで別途確認する。

## #467への引継ぎ

本証跡は対象一致・改稿継続の機能確認。掴み・推進力・回収の3除去条件や実運用の読者効果の
実証ではない。#467では#465の読者確認と本往復を結合し、未実施の評価を実施するか、根拠付きで
範囲を限定する判断を残す。Epicはその受入まで継続する。
