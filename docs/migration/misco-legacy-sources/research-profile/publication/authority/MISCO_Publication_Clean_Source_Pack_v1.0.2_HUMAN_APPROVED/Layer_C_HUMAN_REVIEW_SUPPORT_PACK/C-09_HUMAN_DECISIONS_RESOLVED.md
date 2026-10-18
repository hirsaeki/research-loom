# C-09 HUMAN DECISIONS — RESOLVED

**Status: CLOSED.** v1.0.1 Human Reviewで4項目すべての選択が確定し、v1.0.2 Layer Aへ反映した。以下は決定記録であり、Layer Cはruntime対象外である。

## HD-01 正式書式の具体設定値 — A

- **Human Decision:** A. 現行正式仕様原本を将来Skillの正式設定ソースとして与える。
- **Layer A反映:** 頁設定、本文・見出し書体、字下げ等の正本を現行正式仕様原本と明示。Source Packから推測しない。
- **runtime不足時:** 正式原本または必要設定が未提供なら `HUMAN_DECISION_REQUIRED`。これは未決ではなく入力不足。

## HD-02 参考文献一覧の最終配置 — A

- **Human Decision:** A. 現行正式仕様原本をそのまま適用する。
- **Layer A反映:** Source Pack独自の参考文献配置既定値は追加せず、現行正式仕様原本の配置方針に従う。
- **runtime不足時:** HD-01と同じ正式仕様入力不足として扱う。

## HD-03 長いURL（raw URL）の表示方法 — B

- **Human Decision:** B. 人間が新規出力用の統一方式を承認する。
- **Layer A反映:** 長いraw URLのreader-facing表示は、人間承認済み統一URL表示プロファイルを使う。
- **重要:** Human Review記録には具体的なURL表記パターン自体は記載されていないため、Source Packが方式を創作しない。承認済みプロファイルをruntime入力として与える。
- **runtime不足時:** URL表示プロファイルが未提供なら `HUMAN_DECISION_REQUIRED`。これは選択肢の未決ではなく入力不足。

## HD-04 カラー図表の品質確認（QA）の扱い — B

- **Human Decision:** B. 条件付きの品質確認にする。
- **Layer A反映:** カラー図表を使用する場合だけ、承認済みのカラー使用条件と白黒表示時の識別性をQAで確認する。
- **非該当時:** カラー図表がない出力にはこの確認を要求しない。

## Closure statement

HD-01〜HD-04に方針未決事項は残っていない。新しいStyle Ruleは追加しておらず、既存51 runtime ruleのID集合は不変である。
