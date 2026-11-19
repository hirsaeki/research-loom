# #627 固定した初回稿の比較条件

## 試験前の固定

2026-11-20、[二つのケース](cases.json)を条件間で固定した。
以前の#467で不足していた「具体的な変更を選択済みだが効果は未測定」を追加し、
正当な保留の対照には、既存の逆方向の前後観察の形を通常案件・例外案件に当てた。
いずれもSYNTHETIC_TEST_ONLYであり実測や実研究の採択を表さない。

既存の#467 driverのfixture・virtual State準備と公開Facadeを再利用する。
新たな執筆engine、評価DB、Research採択経路、文章品質gateを作らない。

| 条件 | 固定したWriter | 正のbrief配信 | 他の条件 |
| --- | --- | --- | --- |
| baseline | 1.1.0（配布Projectの選択版） | main 91d0825の欠落を再現 | 同じ現行Writer入口とreader-flow、同じ研究内容・構成・prompt・長さ目標 |
| current | 1.4.0 | #626の修正によって配信 | baselineと同じ |

Publicationは両方1.3.0に固定する。基準条件を弱くするため旧いWriter入口へ差し替えない。
基準の節投影は、現行builderから今回追加した正のbriefだけを除き、その節digestを
再計算して再現する。歴史的checkoutから取得したexportであるとは主張しない。
正のbriefの伝達だけを調べる回帰試験と、複数差分がある二条件の文章比較を区別する。

準備:

```text
uv run --frozen python scripts/writer_answer_delivery_probe.py --run-root NEW_BASELINE_DIRECTORY --condition baseline
uv run --frozen python scripts/writer_answer_delivery_probe.py --run-root NEW_CURRENT_DIRECTORY --condition current
```

出力先が存在すれば停止する。各runの`conditions.json`が選択版・時刻・準備HEAD、
ケースと入口のhash、共通prompt、公開操作が返したpins、inputとsnapshotを保持する。
研究Snapshotのcontent digest、各節の研究objectsとSection Contractは条件間で一致する。
ID・時刻・Profile世代などの機械的差分を文章効果と数えない。

## 生成と保存

ユーザーの明示許可により、条件ごとにfresh contextのCodex subagentを一つずつ使う。
両方とも親のモデル設定を継承し、別モデルの上書きはしない。
一つのsubagentが二つのケースを固定順で読む。異なる条件の材料・稿・採点資料は読まない。
一ケース一稿、各稿4節・全体3000〜4500字を目標にし、初回本文の改善再生成はしない。
実際の文字数のずれも結果として残す。モデルの正確なbackend版、sampling設定、seedは
取得できなければ不明と記録し、推測で埋めない。

本文だけの`sections[{section_id,content}]`を最初に保存する。
既存driverのwrap-responseは、そのbytesを変えずtransport responseへ包み、実施していない
Profile点検をunevaluatedに保つ。通常import/replay/inspectは構造・履歴の確認であり
本文品質のPASSではない。初回稿・包んだresponse・結果を別々に保持する。

## 点検と採否

中心の一文、主な理由、判断を変える条件を抜き出し、本文の具体箇所で比較する。
過大主張、無根拠な規範判断、反証脱落、結論消失、正当な保留の破壊をそれぞれ点検する。
留保は数ではなく、主張を中断している具体箇所と役割で評価する。
語調の強さ、意味の忠実さ、編集所見、実読者の理解を総合点にしない。

baselineに上記五種類の失敗がありcurrentに同じ失敗がないケースに限り、
Writer 1.4.0のまま正のbrief伝達だけを除いた追加対照Cを一稿生成する。
Cは該当ケースにつき一回、最大二稿とし、それ以外の再生成はしない。
表現の好みだけの差や両条件での失敗なしはCの実施理由にしない。
両条件に同趣旨の規則・材料が残る場合は効果を独立識別できないと記録する。
改善が再現されなければ、新たなWriter指示・Profile条項を採用しない。
新しい試行回数や有利な条件を結果を見て追加しない。

この比較はCodex上の限定モデル試験であり、実読者の理解の測定ではない。
ChatGPT Workの統合受入は[引渡し手順](work-handoff.md)に従う別作業で、#628を未完了のまま残す。
