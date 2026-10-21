# #452 自省レビュー比較の検証手順

この手順は [#452](https://github.com/hirsaeki/research-loom/issues/452) の段階1を、同じ入力・順序・記録形式で2回実施するためのものです。正本は [比較プロトコル](../../skills/research-conversation/acceptance/reflective-review.md) です。Helper はモデルを呼び出さず、研究状態も変更しません。実行者・採点者はオーナー（hirsaeki）です。自動検査の成功と、人手による意味上の合格は別です。

## 1. 準備する

PowerShell **7.5以上**（日時を文字列として読むJSON処理を使用）、Git、対象リポジトリが必要です。追加のPowerShellモジュール、APIキー、Python環境は不要です。`pwsh -NoProfile` でプロファイルを読み込まないセッションを開始し、以下はリポジトリのルートで実行します。全コマンドを同じHelperの版で実施し、途中でHelperや比較資産を更新しないでください。更新が必要なら別のRunRootで新しい比較を準備します。

```powershell
$helper = Join-Path (Get-Location) 'scripts/Invoke-ReflectiveReviewValidation.ps1'
$run = 'D:\wsroot\scratch\reflective-review-2026-10-21'
$settings = 'D:\wsroot\scratch\reflective-review-settings.json'
```

RunRootは**まだ存在しない、リポジトリ外の専用ディレクトリ**にします。実研究のworkspaceを指定しません。例の名前が存在する場合は別名を選びます。Helperを同時に複数起動しないでください。既存記録は上書きしません。

設定ファイルをJSONオブジェクトとして作成します。使用モデルの識別子、provider、推論設定などの実際のホスト設定を事前に確認します。下記は形式例であり、使用するモデルや設定の推奨値ではありません。

```powershell
@{ reasoning_effort = '実際の値'; other_settings = '実際に固定した設定' } |
    ConvertTo-Json | Set-Content -LiteralPath $settings -Encoding utf8NoBOM
& $helper -Action Prepare -RunRoot $run -Model '実際のモデル識別子' `
    -Provider '実際のprovider' -SettingsFile $settings
```

生成物は次の構成です。

| 保存先 | 内容・編集可否 |
|---|---|
| `manifest.json` | HEAD、準備日時、資産とHelperのdigest、設定、8ケース、実行順。編集しない |
| `inputs/RR*/target.txt` | Aの出力・B/Cの初期Target。編集しない |
| `inputs/RR*/case.txt` | 原発言・明示指示・Target・事実・状態。編集しない |
| `setup.json` | 送信同意とB用履歴の事前確認。Freeze前だけ編集する |
| `round-1/scores.json`, `round-2/scores.json` | 人手採点欄。モデルに渡さない |

Targetの外側の引用符はMarkdownの区切りとして除き、本文をUTF-8 BOMなし・LF・末尾改行追加なしで固定します。RR5・RR8のRR2参照は展開済みです。版は `RR1-v1` 等、digestはそのTarget本文のSHA-256です。修正後本文もBOMを除いたテキストの改行をLFに揃えて照合します。**取り込んだ生出力ファイル自体はバイト列のまま保存し、別途digestを記録します。**

## 2. Bの作業文脈を作成し、固定する

**B用履歴の作成を含め、最初のモデル送信より前に、オーナーがproviderへのケース本文の送信に同意し、その日時と対象providerを記録します。** レビューや期待事項の閲覧より先に、RR1〜RR8それぞれについて、使い捨て環境・別会話でB用履歴を一度だけ作成します。モデル・設定は比較と同じにし、原発言を冒頭近くに置き、実際のツール呼出しと出力、対象Targetを出した過程、主担当によるその説明を保存します。使用するのは当該ケースの情報だけです。研究状態の採用・承認や実研究の再実行は行いません。

履歴は実記録をそのまま保存します。ツールログや自己正当化を後から架空の対話として作らないでください。期待事項や他ケースの回答を見せてはいけません。**生成された対象が固定Targetと違う場合は準備未完了です。** 成功するまで再生成したり、ログや固定Targetを書き換えたりせず、差異を残してオーナーがプロトコル上の扱いを判断します。

`setup.json` の `histories.RR1` 等について、履歴ファイルの絶対パス、使い捨て環境の識別情報を記入し、実際に確認できた項目だけ `true` にします。

| フィールド | 確認内容 |
|---|---|
| `real_transcript` | 架空の再構成ではなく実履歴である |
| `request_near_start` | 人間の原発言が冒頭近くにある |
| `tools_and_outputs` | Targetを出した実際のツール呼出しと出力がある |
| `exact_target` | 固定Target本文に一致する |
| `host_justification` | 主担当によるTargetの説明がある |
| `no_expected_findings` | 期待事項・正解・採点記録が混入していない |

オーナーがproviderへのケース本文の送信に同意した後、`provider_consent` を `true` にし、`confirmed_by` と `confirmed_at`（タイムゾーン付き日時）を記入します。同意前に送信しません。

```powershell
& $helper -Action Freeze -RunRoot $run
```

8件すべての確認と原発言・Targetの文字列一致を検査してから、B/C入力と `frozen.json` を作成します。履歴の真正性・非混入などは人の確認であり、Helperが独立に証明するものではありません。以後、元の履歴ファイルの更新は比較入力に反映されません。

実行順は1回目RR1→RR8、奇数ケースB→C・偶数ケースC→B、2回目RR8→RR1、B/C順も逆です。Aではモデルを呼びません。

## 3. Nextに従い、呼出しと取込みを繰り返す

```powershell
$next = (& $helper -Action Next -RunRoot $run) | ConvertFrom-Json -AsHashtable
$next | ConvertTo-Json -Depth 30
```

### CALL_REQUIRED：レビューまたは1回の修正

1. `input_path` のファイル本文だけを、新しい独立した会話に渡します。原会話・他条件・以前の反復・採点者の会話から続けません。モデルと設定はmanifestに一致させます。ファイル参照を渡してモデルに開かせるのではなく、本文を渡します。
2. reviewerには検索・ファイル読出し・研究状態の変更をさせません。自動継承される会話・プロジェクト指示、メモリ、ツール接続等を確認し、指定入力以外の研究情報・過去応答・採点情報が入っていなければ `only_supplied_input` を真にします。ホスト標準のsystem指示まで空にするという意味ではありません。全条件に共通する標準指示や追加設定は識別情報をsettingsに記録し、条件間で変えません。この確認は実施者の記録であり、ホスト隔離の自動証明ではありません。
3. 初回応答を編集せず、リポジトリ外の受渡し用ファイルに保存します。レビューのJSONからコードフェンスを除く等の修復もしません。修正担当の出力はJSONではなく本文だけです。追加の質問や情報取得を無記録で挟まず、入力不足は未点検範囲として返させます。
4. `$next.record` をレコード用ファイルに保存し、以下の項目を実測・確認値で埋めます。

```powershell
$record = 'D:\wsroot\scratch\rr-call-record.json'
$next.record | ConvertTo-Json -Depth 30 |
    Set-Content -LiteralPath $record -Encoding utf8NoBOM
# $record を編集してから取り込む
& $helper -Action Import -RunRoot $run -RecordPath $record
```

| レコード項目 | 記録する内容 |
|---|---|
| `round`, `case`, `condition`, `kind`, `input_sha256` | Nextの値を保持する |
| `raw_path` | 初回生出力ファイルの絶対パス |
| `model`, `provider`, `settings` | 実際に使用した設定。相違を隠してmanifestの値に合わせない |
| `call_id`, `conversation_id` | 呼出しと新規会話の追跡可能な識別情報。ホストがIDを出さない場合は、一意のローカルIDを割り当て、対応する手動記録を保持する |
| `fresh_context`, `only_supplied_input`, `provider_consent` | 実施者が確認した場合だけ `true` |
| `elapsed_seconds`, `cost`, `cost_currency` | 送信から応答完了までの経過秒数、その呼出しの費用、通貨。手動の採点・取込み時間は含めない。費用と時間が不明なら `null` と対応する `*_unknown_reason`。不明をゼロにしない |
| `status` | `ok`, `timeout`, `not_run`, `malformed`, `wrong_target` |
| `reason` | 失敗理由、またはHelperが提示した2回目のレビュー理由 |

失敗時もレコードと生出力を残します。未実施で出力がない場合は空ファイルを指定し、`not_run` と理由を記入します。実施していなければ呼出しIDは空でも構いません。timeout等も費用・時間の不明理由を残します。

レビューの形式は次のとおりです。指摘なしなら `findings: []` を返します。採点用PASS／FAILは要求しません。

```json
{
  "target_version": "Nextに表示された版",
  "target_sha256": "Nextに表示されたdigest",
  "findings": [{
    "location": "対象箇所",
    "reference": "原発言・指示・事実への参照",
    "lens": "purpose",
    "problem": "具体的な問題",
    "minimal_fix": "最小修正案",
    "return": "explanation",
    "unreviewed_scope": "none"
  }]
}
```

`lens` は `purpose` / `meaning`、`return` は `explanation` / `research` / `clarify` / `none` です。Helperは形式と版を検査します。指摘内容の正しさ・具体性は主担当が判断します。

### DISPOSITION_REQUIRED：主担当が採否を記録

`review_event` の原出力を読み、`raw_template` の各指摘に対して1から始まる `finding`、`accepted` / `rejected`、理由を記入します。これを別JSONに保存し、`record.raw_path` から指定してImportします。判断はモデルによる正式な採用ではなく、検証内の説明修正・差戻しの判断です。

```powershell
Get-Content -LiteralPath (Join-Path $run "events/$($next.review_event)/raw.txt") -Raw -Encoding UTF8
$disposition = 'D:\wsroot\scratch\rr-disposition.json'
$next.raw_template | ConvertTo-Json -Depth 30 |
    Set-Content -LiteralPath $disposition -Encoding utf8NoBOM
# $disposition の採否・outcome・理由を編集する
$next.record.raw_path = $disposition
$next.record | ConvertTo-Json -Depth 30 |
    Set-Content -LiteralPath $record -Encoding utf8NoBOM
& $helper -Action Import -RunRoot $run -RecordPath $record
```

```json
{
  "decisions": [{"finding": 1, "decision": "accepted", "reason": "採否理由"}],
  "outcome": "revise",
  "reason": "今回の処置の理由"
}
```

- `keep`：採択した要修正指摘がなく、Targetを保持する。指摘ゼロでも理由を記録する。
- `revise`：採択した説明上の指摘を1回だけ反映する。次のNextが修正担当用入力を出す。修正担当には当該ケース・当該レビュー・採否だけを渡し、Bの長い履歴や期待事項は渡さない。
- `research` / `clarify`：研究工程へ戻す、または人間への確認が必要。検証内で新規研究・承認・回答の捏造を行わず、その比較セルを未成立として記録する。

研究不足の指摘を説明だけで解決した扱いにはできません。必要なら説明修正より研究差戻し・意図確認を優先します。修正後のレビューで新たな問題が出ても、2回目の修正は行えません。

### 有限回・失敗・再開

各反復・ケース・B/C条件でレビュー最大2呼出し、修正最大1回です。標準はレビュー1回→採否→必要なら修正1回です。無記録の情報取得や良い回答を選ぶための再試行は行いません。

- 初回レビューが不正形式の場合だけ、Nextが `malformed_retry` と同じ入力を提示します。2回目で改善しても初回失敗は残ります。
- 修正後確認が必要なら、**次の比較セルを取り込む前に** `Next -Recheck` を使います。理由は `revision_recheck`、対象はv2とそのdigestです。2回目が済んでいれば追加呼出しはできません。
- timeout、未実施、対象不一致、設定差、隔離未確認は有効な出力として採点しません。2回目も失敗した場合も同様です。次のセルへ進めても、全体の判定は未完了になります。
- `Next` の再実行は同じ未完了操作を提示します。実際の呼出し直後にImportし、取込み前にモデルを再度呼ばないでください。既存原出力・レコードの訂正で初回失敗を消しません。
- 保存済み証跡の改変、入力digest不一致、実行順違反、会話IDの再利用はエラーです。元の証跡を復元するか、新しいRunRootで比較をやり直します。Helperに上書き用のForce機能はありません。
- `journal.json` はHelperが更新するイベント索引です。末尾のイベント欠落も検出します。書込み途中の中断で索引とイベントが一致しない場合は、その場で再呼出しせず、証跡を保全して中断箇所を調べます。既存ファイルを削除して見かけ上成功させません。

入力・出力ファイルの丸ごとの添付で他の記録までモデルに渡さないようにしてください。特に `setup.json`、`manifest.json`、採点ファイル、Report、期待事項をレビュー・修正担当に渡しません。

## 4. 人が採点し、Reportを作成する

`CALLS_RECORDED` になったら、次の検査で各セルの採点対象パスとdigestを確認します。途中でも実行できます。

```powershell
& $helper -Action Validate -RunRoot $run
```

各 `round-*/scores.json` の24行をオーナーが記入します。採点者だけが [期待事項](../../skills/research-conversation/acceptance/reflective-review-expectations.md) と [2つのレンズ](../../skills/research-conversation/acceptance/rubric.md#reflective-review-lenses-590) を読みます。Aの本文は両反復で同じですが、記録は各反復に残します。

- `output_sha256` はValidateの `outputs` の値、`scorer` は採点者、`scored_at` はタイムゾーン付き日時を記入する。
- `purpose`, `meaning` はそれぞれ `PASS` / `FAIL` とし、各 `*_reason` を記入する。未採点は空のままにし、自動合格にしない。
- `observations` はunsupported claim、結論消失、条件欠落、authority誤表示、不要な質問、原案の劣化の有無を各booleanで記入する。`new_*` はAに対してCが新たに導入した問題を区別する。A/Bの `new_*` は非該当として `false` にする。`observation_note` に判断理由を残す。例えばAにunsupported claimがなくCにある場合、Cの `new_unsupported_claim` も真です。Helperはこの種の記録の矛盾も未完了として扱います。
- 原レビューも保存して読むが、最終比較は処置後のTargetに対して採点する。修正なしならv1、修正ありならv2。初回の失敗や差分は原記録から消さない。
- モデルの自己採点やLLM judgeを人手採点の代用にしない。

```powershell
& $helper -Action Validate -RunRoot $run
& $helper -Action Report -RunRoot $run `
    -ReportDirectory 'D:\wsroot\scratch\reflective-review-report-2026-10-21'
```

ReportDirectoryも未作成の専用ディレクトリにします。JSONには全条件のレンズ別件数、各基準、欠落、出力binding、呼出しごとの入力文字数・時間・費用と不明理由、証跡digestを残します。Markdownは概要です。入力文字数はUnicodeコードポイント数であり、token数ではありません。

各反復で次を独立に確認します。

1. CのPASSレンズ数がAより多いケースが8件中5件以上ある。これは既存基準のケース比較だけに用い、2レンズの総合品質点は作らない。
2. Purpose合計とMeaning合計のそれぞれで、CがBを下回らない。
3. RR5のCが両レンズPASSで、原案を劣化させていない。
4. Cが新たなunsupported claim、authority誤り、条件欠落を導入していない。

両反復で満たした場合だけ `STAGE2_CONSIDERATION_CRITERIA_MET`（段階2の検討基準を充足）です。完了した2反復で再現しなければ `CRITERIA_NOT_REPRODUCED`、欠落・未実施・無効出力・未採点があれば `INCOMPLETE` です。1回だけでは暫定です。Helperの終了コード0は操作成功を示し、比較合格を意味しません。正式採用・段階2着手を自動承認しません。

全RunRootとReportを一緒に保管し、オーナーが内容を確認した後、既存プロトコルどおり `skills/research-conversation/acceptance/reflective-review-run-<date>.md` に実施記録を配置します。同日複数回なら同じ記録から各RunRootの識別子を明示します。JSON、初回原出力、修正、採否、採点に到達できる保管先とdigestを記録してください。有利でない結果も#452に報告します。配置・コミット・Issue投稿はこのHelperの動作には含まれません。
