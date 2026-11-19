# #625 選択版と節入力の診断

## 対象と結論

調査基点は main `91d08254a69e9972b8e9cd2735d423ae1b410a21`。
実原稿を持つ研究Workspaceはこの開発作業の対象として指定されていない。
隣接するWorkspaceを勝手に選ばず、#467と同じ隔離virtual fixtureで、公開Facadeの
Package作成、Composition capture/select、round-trip exportを実行した。
実際のChatGPT Workでの読込みと実原稿の執筆は未検証であり、#628へ残す。

確認できた問題は二つを区別する必要がある。

1. 配布済みWriter 1.4.0が存在しても、既定ProjectはPublication 1.3.0とWriter 1.1.0を選ぶ。
   未選択の新しい指示は、そのWorkspaceに自動では届かない。
2. Packageの`communication_brief.must_include`が基点の節入力から欠落する。
   `must_not_claim`は届く。この非対称を#626で補正する。

主張の明確さ、根拠、必要条件、過大・過小主張の双方の点検は#450/#463の既存経路にある。
新しい管理機構、保存時の文章品質gate、別の採択経路は不要。
入力欠落の修正だけで文章が改善すると結論しない。

## 追跡記録

`diagnosis.json`と版別の`diagnosis-1.1.0.zip` / `diagnosis-1.4.0.zip`は
2026-11-20に作成した合成データの記録。各版のPackage識別情報、選択Compositionと
全節を内包するcompact Writer入力を保持する。standalone節入力はその展開内容と一致する。
書出しは#626の修正後であり、基点mainの欠落はコード照合と旧形式の回帰試験で確かめた。
これを未修正mainそのものから取得したexportと偽って扱わない。

| 対象 | Writer 1.1.0 | Writer 1.4.0 |
| --- | --- | --- |
| manifest SHA-256 | `08de4b27085a56e10abf0662f367e97db315048fdd809c71c1583412ae0d2b08` | `458ddd2acf32095c79d7669eb0b2e0e98afd62bb2cac9f9f7fdb3f8980317723` |
| EPS digest | `sha256:ec73aed8e75855794c11c70d730520737d67d7ee3b65562c3287d934871b23a4` | `sha256:c53564e41ce47e84bcd522f6752249fa2cacb2b8954764dee9d6e34a8e713355` |
| Writer input digest | `sha256:a3a7e495b4f886ee87e1c10fa5db89632ab76a29de30e328d083d689f8184029` | `sha256:cccb3afad81c7cd817feb6bd43273bf54bbbb54a2cf55d17437e7ca2fd410a4f` |
| 配信規則数 | 127 | 127 |

両方にPublication 1.6.0を明示指定し、Writerだけを各版へ固定した。
規則IDの個数が同じでも本文は同一ではない。1.4.0ではPUB-RC-01/02/04/05に
採択済み提言を検討手順へ薄めない説明があり、対応する資料本文も入力内に届く。
各Package/Composition/sectionの版とdigest、Profile pins、previewとauthority flagsは
機械可読記録と書出し内にある。外部の旧資料から規則を補っていない。

Codex側で参照したWriter入口とreader-flowのbytesは診断記録の`skills`に記録した。
これはWorkホストが同じ資料を読み込んだ証明ではない。Workでは入口の明示読込みと
入力の選択版を再確認する。

## 解決規則と適用

Publication 1.3.0/1.6.0はいずれもWriter `>=1.1.0 <2.0.0`を要求する。
resolverは明示された有限候補集合の中から、直接要求と依存を同時に満たす高い版を選ぶ。
Publicationだけの要求はWriter 1.4.0の指定と同義ではない。
Writer 1.1.0と1.4.0は双方利用でき、互換解のない要求は`PROFILE-VERSION-001`で拒否する。
存在しない版や依存不整合を最新化で握りつぶさない。

新規Projectで現行の組合せを使う指定は[Profilesの版選択](../../../profiles/README.md)
にある。既存Workspaceは、現在の直接要求を確認し、通常の
[resolve → advance → history](../../architecture/profile-generation-advancement.md)
を明示実行する。Writerの直接要求がない場合はrequest addition、旧版を直接要求している
場合は正確なfrom/toのreplacementを使う。解決結果を確認してから適用する。
この作業では既存Workspaceのadvanceを実行していない。

既存のProfile advancement回帰試験は、対象世代の再現、競合・不正要求の拒否、
EPSだけの更新、歴史的研究・旧Writer入力の保持、失敗時の回復を対象とする。
これらの機構を再実装しない。既存Packageは元のEPSを保持するため、適用後の確認には
新たなPackageと選択Compositionからのexportを使う。

## 主張が消えた場合の切分け

| 観察 | 対処 |
| --- | --- |
| 入力のWriter pinが意図した版でない | 対象Projectの明示的なProfile選択を確認する。自動移行しない。 |
| Packageに優先事項があり節入力にない | 配信経路の不具合。#626の修正を使用し、新しくexportする。 |
| `reader_question`、`purpose`、`messages`、opening/closing intentとargument/finding参照が主張を説明しない | 既存Compositionを編集し、新版をcapture/selectする。空欄・TBDの途中稿を保存禁止にしない。 |
| 入力に主張・理由・条件が揃うが本文で留保や手順へ埋没する | 既存Writing Feedbackで具体箇所と編集を返す。直ちに新研究・新採択が必要とはしない。 |
| 主張の根拠自体が不足する | 文章の断定だけを強めず、既存Research経路で扱う。 |

今回の合成Compositionは各節のreader question、purpose、messages、opening/closing intentと
Finding/Argument/Recommendation参照を備える。これを欠く実原稿の構成を確認したとは言わない。
実運用の未適用、構成不足、生成文の問題を混同しないことが診断の成果である。
