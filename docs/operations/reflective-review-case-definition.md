# Reflective Review v2：ケース定義と実履歴対応表

[#605](https://github.com/hirsaeki/research-loom/issues/605) の入力契約です。[操作手順](reflective-review-validation.md)のPrepareより前に使用します。正本は[比較プロトコル](../../skills/research-conversation/acceptance/reflective-review.md)です。このファイル、出所対応表、原本JSONL、採点記録はモデルに渡しません。

## 確認した由来と対応の限界

2026年10月21日に、ローカルの「MISCO向けAI影響調査を開始」セッション（`01a11a4a-f635-7eb2-bb85-2655fa6f8df8`）を調査しました。固定RRケースの英語の原発言・Targetと完全一致する発言は確認できませんでした。以下の対応は問題の構造の対応であり、逐語的な生成履歴ではありません。

| 固定ケース | 定義上の由来 | 実履歴との対応・追加された条件 |
|---|---|---|
| RR1 | S9 / #448 | 2026-10-08 17:12〜17:14 UTCの執筆停止説明に関連。Target候補は `msg_0198d5890e90f963016ac7cf62fe2c8191b8a109da021b22d1`。固定ケースの「今日の判断が必要か」という原発言と英語Targetは実発言ではない |
| RR2 | S11 / #450 の結論消失対照 | 同日19:48 UTCの留保に関する指摘（`msg_01a11d0f-879a-7a20-8710-d479a6640462`）に関連。11%→18%はS11の匿名化された固定条件であり、この場面の実測値と称しない |
| RR3 | 新規作成 | オンボーディング調査に対応する実場面は未確認 |
| RR4 | S10-change | 同日18:13〜19:17 UTCの7結論と論証記録の区別に関連。実履歴は内容差分なし。小企業への拡張はS10-changeで加えた対照条件 |
| RR5 | S11 supported | RR2と同じ固定条件の正しい回答対照。該当する実出力としては未確認 |
| RR6 | S2 | 保存と会話内作業の違いを扱う意味上のシナリオ。市場規模・競合・価格感度という具体的な実場面は未確認 |
| RR7 | 新規作成 | 二段階Delphiの該当実場面は未確認 |
| RR8 | S11 overstatement | RR2と同じ固定条件の過大主張対照。該当する実出力としては未確認 |

S9/S10とS11の定義は[シナリオ](../../skills/research-conversation/acceptance/scenarios.md)、匿名の実行記録は[#448記録](../../skills/research-conversation/acceptance/issue448-codex-probe.md)と[#450記録](../../skills/research-conversation/acceptance/issue450-codex-probe.md)にあります。これらも固定RRの逐語的な元履歴ではありません。

実履歴比較の候補は、執筆停止の説明、結論と論証記録の許可の説明、留保と回答の関係の3場面です。採点や新しいモデル応答を見る前に選定規則と全候補・除外理由を決めます。最後の場面では、指摘後のユーザー発言をBへ入れず、指摘前の対象草稿の原版と出所を取得できるかを先に確認します。取得できなければ、その理由を除外記録に残します。この対応表だけでケースが完成したとは扱いません。

## 共通ケースファイル

`-CaseFile` はUTF-8のJSONオブジェクトです。`schema_version` は2、`study_kind` は下記のどちらか、`suite_id` は英数字・ハイフン・アンダースコアで始めは英数字にします。`selection_rule` は事前の選定規則、`exclusions` は理由の文字列配列（なしなら `[]`）、`cases` は実行する全ケースの順序付き配列です。IDも同じ文字制限で一意にします。異なる内容・種別を同じsuite版として扱いません。

CaseFileと参照元の `path` は絶対パスで指定します。相対パスを作業ディレクトリに依存して解釈しません。

ケースファイルと全参照ファイルを準備してからPrepareします。Prepareはファイルを読み取り専用で読み、原バイトと生成入力を新しいRunRootへスナップショットします。すべての定義を検査してから書込みを開始するため、不正な入力ではRunRootを作りません。IO障害による部分生成があれば保全して別名で再準備します。`provenance/cases.json` は入力ファイル原本です。個々の `provenance/<case>.json` は文脈種別と選択した原イベントIDを示します。

## controlled_fixture

`cases` はRR1〜RR8をこの順で全件含めます。5フィールドは正本から取り出すため、JSONに `request` / `instructions` / `target` / `facts` / `state` を指定して上書きできません。

各ケースの `context` は次の形式です。以下は形式例です。`path` のファイルは先に作成します。

```json
{
  "id": "RR1",
  "context": {
    "kind": "constructed",
    "path": "D:/wsroot/scratch/rr-v2-contexts/RR1.txt",
    "construction_note": "作成者、作成方法、参照した場面、匿名化・追加条件・元場面との違い"
  }
}
```

文脈作成担当は5フィールドだけを使い、採点者専用期待事項を見ません。今回の実装・採点用会話からモデルに文脈を生成させません。Targetと整合する作業メモをローカルで構成し、観測されていないツール実行・出力・自己正当化を実記録として作りません。修正案、採点、望ましい回答を入れません。時系列上の作業経緯を追加する場合も、構成したものと明示します。HelperはBの文脈に構成物である旨を表示します。

RR2・RR5・RR8の共通事実については同じ文脈を使い、異なるTargetに合わせた正当化を作り分けないでください。Bへだけ新しい根拠を加えてCを情報不足にしません。長さを増やすためだけの無関係な他案件・他ケースを追加しません。構成文脈は自然な長期会話の再現ではなく、その版で固定した実験条件です。

8ファイルを用意した後、次のコードでケースファイルを作れます。保存先が既存でないことを確認して使います。

```powershell
$definitions = foreach ($n in 1..8) {
    @{
        id = "RR$n"
        context = @{
            kind = 'constructed'
            path = "D:/wsroot/scratch/rr-v2-contexts/RR$n.txt"
            construction_note = 'ここをケースごとの実際の作成方法と差分に置き換える'
        }
    }
}
@{
    schema_version = 2
    study_kind = 'controlled_fixture'
    suite_id = 'rr-fixed-v2-1'
    selection_rule = '固定RR1〜RR8を全件、定義順で実施する'
    exclusions = @()
    cases = @($definitions)
} | ConvertTo-Json -Depth 30 | Set-Content `
    -LiteralPath 'D:/wsroot/scratch/reflective-review-v2-cases.json' -Encoding utf8NoBOM
```

このコードは文脈や作成方法を自動生成しません。`construction_note` は空でないことのみ機械検査するため、プレースホルダーのまま比較を開始してはいけません。

## historical_replay

`cases` にHR1等の独立したIDを使い、RR番号は使用しません。各ケースは5フィールド、`field_sources`、`context` を持ちます。5フィールドは空にせず、適用指示なしなら `instructions` は `none` とします。

現行HelperのTargetは原assistantメッセージの本文です。草稿ファイルだけに存在する本文を別のassistant発言として作り直すことはできません。その場合は現行形式では未対応として除外理由を記録します。対応表の候補がすべて利用可能だとは限りません。

```json
{
  "id": "HR1",
  "request": "指定した原ユーザーイベントの本文そのもの",
  "instructions": "当時有効な指示",
  "target": "指定した原assistantイベントの本文そのもの",
  "facts": "Target時点までに確認できた関連事実",
  "state": "当時の保存・候補・採用・保留状態",
  "field_sources": {
    "instructions": {"events": ["原イベントID"], "note": "この指示が引き続き有効な理由"},
    "facts": {"events": ["原イベントID"], "note": "事実と根拠の対応"},
    "state": {"events": ["原イベントID"], "note": "当時の状態の根拠"}
  },
  "context": {
    "kind": "historical",
    "format": "codex-jsonl",
    "path": "原本JSONLの絶対パス",
    "sha256": "原本全体のSHA-256、小文字64桁",
    "session_id": "原セッションID",
    "start_event": "選択文脈の開始イベントID",
    "request_event": "対象の原ユーザーイベントID",
    "target_event": "対象の原assistantイベントID",
    "author_model": "原生成モデル、またはunknownと理由",
    "author_settings_note": "原生成時の設定、または不明の理由",
    "omissions": [],
    "transformations": []
  }
}
```

この形式例のプレースホルダーは原記録から置き換えます。研究用workspaceやDBの最新状態から、過去の状態を推定して埋めません。原本が更新され得る場合は、まずリポジトリ外へ原バイトをコピーしてSHA-256を計算し、その保存コピーを参照します。元の研究workspaceは変更しません。

HelperはCodex JSONLの `session_meta.payload.id` と `response_item` を読みます。user/assistantの `message` のテキスト部分を改行で連結し、`function_call` / `custom_tool_call` と対応する出力を取り出します。イベントIDは `payload.id`、ない場合は `call_id/tool_call` または `call_id/tool_output` です。原本中の並びでstart≦request＜targetを確認します。日時はタイムゾーン付きで記録されている必要があります。

原発言とTargetは、BOMをデコードしてCRLF/CRをLFに揃えた後に完全一致させます。末尾改行・文字の省略・翻訳は行いません。Targetを出させるための再試行は不要です。添付画像等の非テキスト要素を含む選択イベントは未対応として停止し、無言でテキスト部分だけにしません。system/developer指示、reasoning、圧縮要約、UIイベントの重複は会話本文に含めません。全条件共通のホスト設定・指示の識別情報はsettingsに記録します。

`omissions` は `{"event": "ID", "reason": "理由"}`、`transformations` は `{"event": "ID", "text": "変更後本文", "reason": "理由"}` の配列です。省略・変換は選択範囲内のイベントだけに指定でき、request/targetには指定できません。同じイベントに二重指定できません。ツール呼出しと出力は残すなら対で、順序も保持します。省略するなら両方の理由を記録します。`field_sources` の参照先は原本に存在し、Targetより後であってはいけません。指示なし等で参照なしの場合も配列 `[]` と理由が必要です。

これらの検査は、意味を失った匿名化や望ましい修正の混入を自動判定しません。生成された `history.txt` と `case.txt` を人が原記録と照合します。Target前でも既に修正・採点情報が含まれる範囲なら、そのケースをそのまま使わず、選択規則・除外理由を記録します。

`history.raw` にはTarget後も含む元JSONL全体が保存され得ます。**モデルに渡すのはNextが示す入力本文だけ**です。元JSONL、`history.raw`、ケース定義、出所、採点ファイルを添付すると、後日の情報や私的情報が混入します。実履歴比較の結果は固定8件と別レポートで扱います。
