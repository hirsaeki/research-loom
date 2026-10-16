# 現稿へ結び付いた文書レビュー

`writer_response.document_review` は任意。省略した草稿・部分改稿は従来どおり保存できる。
記録がある場合だけ、組み立てた現稿の対象一致と申告範囲・規則結果を検査する。
文章の正しさや読む動機をbackendが自動判定する機能ではない。

## 公開操作

1. 既存のComposition選択・`writer-round-trip export-input`で固定入力を得る。
2. Writer responseを作る。改稿ではexact current baseを指定し、変更した節だけを返す。
3. `writer-round-trip prepare-review --workspace <workspace> --json <response.json>`
   または `facade.prepare_writer_document_review(response)` を呼ぶ。
4. 返された `material.sections` の全対象本文・引用・図表参照と `writer_input` の必要材料を読む。
   `review_plan` は文書scopeの規則だけを、既存group IDのまま返す。
5. 実際の点検後に下記のrecordをresponseへ加え、既存importへ渡す。
6. `writer-round-trip inspect`で保存稿・target・点検範囲・意味／編集所見を確認する。

既存稿を読むだけならinspectの `document_review_target` と `writer_input` を使える。
prepareは保存せず、最新baseを確認する。prepare後に現稿が動けば、既存のstale-base検査で
importを拒否する。中断したimportは既存のexact-response retryで回復してから再開する。
部分改稿後に旧文書レビューを自動継承しない。履歴の旧recordは元のrevisionに保持する。

## Record

```json
{
  "document_review": {
    "target_digest": "sha256:<prepareが返す64桁のdigest>",
    "coverage": "full",
    "section_ids": ["<exportした対象節をその順序で列挙>"],
    "reviewer": {"reviewer_id": "host-reviewer", "method": "host_self_review"},
    "reviewed_at": "2026-10-16T08:00:00Z",
    "profile_review": []
  }
}
```

上記は形の説明であり、そのまま提出するJSONではない。`profile_review` はprepareの文書scope
plan全groupを埋める。各groupは既存のreview recordと同じ `review_id`、`rule_ids`、`outcome`、
`violated_rule_ids`、`rationale`、`rule_results` を持つ。文書reviewではrule_resultsが必須。
規則ごとのmethodは配信されたstructural／semantic／editorialを維持する。
N/Aは実際に非該当を点検した場合のみ。全規則がN/Aのgroupだけをgroup N/Aとする。
点検しなかった規則はunevaluated。Profileなし／旧Profileでは文書scope planを捏造しない。

`coverage: full` はexportされた原稿範囲の全節を読んだ申告であり、論文全体を意味しない。
inspectの `covers_composition` と対象節一覧を併記する。抜粋点検はpartialと対象節を明記し、
全文のconformant／N/Aを申告できない。判明した違反と未評価を記録することはできる。
reviewer.methodはhost_self_review／model_proxy／human_review／independent_review。
申告された主体・方法を保存するもので、独立性や人間の実読をbackendが証明するものではない。

意味の忠実さと読者体験は、既存ruleのcheck_kindと本文に基づくrationaleを別々に残す。
inspectは `results_by_check_kind` を分け、総合点や全文品質PASSを作らない。
違反は既存Writing Feedbackへexact rule IDsで対応させる。文書scopeのFeedbackは関連節、
入力内のargument／research object／packageを対象にできる。箇所、読む負担・意味への影響、
残す条件、配置変更・重複削減・接続の修正を具体化し、必要な本文改稿まで行う。
違反のある草稿も、所見を正直に記録して保存できる。Research採択・公開承認は変更しない。

## 対象projection

canonical digestの入力は次の内容だけ。

- `projection_version: 1.0.0`
- 固定Writer `input_digest`（Research Package／Compositionの順序・役割／Profile pinsを包含）
- 固定入力の対象順に組み立てた各節の `section_id`、`content`、`citations`（source／locator）、`exhibit_refs`

responseの配列順ではなく固定入力の節順を使う。本文・引用・図表・順序・Profileの変更で
targetが変わる。review metadata、本文hashの派生値、origin、revision ID／digestは除外するため、
reviewを内包するrevision digestとの循環はない。Host／Writerはhashを手計算しない。
target不一致のreviewだけを外して再提出でき、保存済み草稿と履歴を失わない。

## 検証範囲

#466の回帰テストは、公開prepare/import/inspect、同一response再送、exact base、部分改稿後の
未変更節再利用・旧レビュー非流用、本文以外のtarget変更、抜粋／不正N/A／method代替を検証する。
構造一致と申告結果は文章の意味や読者効果を保証しない。#467の実Host・読者確認は別に記録する。
