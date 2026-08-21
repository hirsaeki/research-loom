# Attention Intake and Workspace Lifecycle

この文書は、研究中のハーネスを Work と Human の境界に合わせて運用するための補助契約である。意味を持つ正本は次の契約にある。

- `contracts/capabilities/attention-intake/attention_distillation_contract.md`
- `contracts/capabilities/workspace-lifecycle/workspace_lifecycle_contract.md`
- `contracts/runtime_artifact_policy.yaml`

## Attention の放り込みと蒸溜

Raw material は `intake/` などのワークスペース内の任意の場所に雑に置ける。ただし、Harness は広域 watcher や暗黙のフォルダ走査を行わない。Human が一回の batch として明示的に登録した時点で、ファイルを `.rh/intake/drops/` にコピーし、各ファイルと manifest を SHA-256 で凍結する。

```powershell
uv run rh --root . attention ingest --path .\intake\drop\2026-08-19 --by <human>
uv run rh --root . plan
uv run rh --root . coordinator next
```

登録された drop は通常の Research/Publication Context Pack には入らず、`ATTENTION_DISTILLATION` Work にだけ渡る。Work の交換は既存の `Context Pack -> TASK.md -> JSON Schema -> result.json -> coordinator submit` 境界を使う。Work が返す `AttentionDistillationHandoff` は候補 Map、除外理由、衝突、不確実性、back-reference を含むが、Evidence、Question、method、answer を決められない。

蒸溜が終わると Harness は候補 Map を `.rh/runs/<run-id>/` に保存し、Human Decision を開く。Human は次のいずれかを明示的に記録する。

- `ADOPT_CANDIDATE_MAP`: `.rh/attention/maps/` に新しい immutable Map version を作り、active pointer を切り替える。
- `KEEP_CURRENT_MAP`: 現在の pointer を維持する。Map がなければ Map-less のまま進む。
- `REQUEST_REVISION`: 同じ drop を再び蒸溜待ちに戻す。

Map は routing/publication guidance であり、採用しても Evidence や Research State にはならない。旧 Map の bytes と履歴は残り、active pointer だけが Human Decision によって変わる。

旧バージョンの workspace で `active_attention_map_id` がまだない場合は、
Registry の legacy `attention-map` を一度だけ active guidance として扱う。
次の adoption Decision で明示的な versioned pointer に移行する。

```powershell
uv run rh --root . decisions
uv run rh --root . decision show <decision-id>
uv run rh --root . decision record <decision-id> --choice ADOPT_CANDIDATE_MAP --by <human>
```

## 研究の archive

Archive は Harness と Human の操作であり、Work のタスクではない。保存先は source workspace の外側にある新しい空ディレクトリを指定する。Harness は `.rh`、contracts、登録済み artifact の hash-verified copy、`archive_manifest.json` を一つの bundle にまとめ、bundle を検証できた後にだけ source の lifecycle を `ARCHIVED` にする。

```powershell
uv run rh --root . archive --destination ..\archives\misco-2026-08-19 --by <human> --reason "研究区切り"
uv run rh --root . archive --verify ..\archives\misco-2026-08-19
```

Archive は削除、head の巻き戻し、意味の自動確定を行わない。未完了の Work または Decision がある場合はデフォルトで停止する。例外的に bundle に `INCOMPLETE` として保存する場合だけ `--allow-incomplete` を付ける。

## 全く新しい研究

`rh new` は旧 workspace を変更せず、明示した template の `src/`、`contracts/`、実行定義を新しい target にコピーし、theme と expectations から新しい `.rh` を初期化する。旧 `.rh`、Decision、Run、Research State、Map はコピーしない。初期 drop を渡した場合だけ、新 target の蒸溜待ちに登録する。

```powershell
uv run rh --root ..\misco-next new `
  --template-root . `
  --theme .\intake\new-theme.md `
  --expectations .\intake\new-expectations.md `
  --worker-backend interactive-work `
  --drop .\intake\drop\first-batch
```

`rh new` は clone 済み Harness checkout と、必要なら別repoのProfile packを
入力にできる。Profileはmanifestで許可された静的ファイルだけを取り込み、
`.git`や旧runtimeは取り込まない。研究repoとしてGitを使う場合は、明示的に
`--init-git`を付ける。このオプションは `git init` だけを実行し、commit・remote・
pushは人間が確認して行う。

```powershell
uv run rh --root ..\misco-study new `
  --template-root ..\misco-research-harness `
  --profile-source ..\misco-research-profile `
  --profile-ref v0.1.0 `
  --theme .\intake\theme.md `
  --expectations .\intake\expectations.md `
  --worker-backend interactive-work `
  --init-git
```

生成された `harness.lock.json` はHarnessとProfileのref、hash、managed pathを
保持する。Harnessの修正はHarness repoでcommit/tag化し、研究側ではarchive URLまたは
local archiveを指定して、pending境界の外で取り込む。

```powershell
uv run rh --root . upgrade `
  --harness-source https://forgejo.example/hsaeki/misco-research-harness/archive/v0.2.0.zip `
  --harness-ref v0.2.0 `
  --profile-source https://forgejo.example/hsaeki/misco-research-profile/archive/v0.1.1.zip `
  --profile-ref v0.1.1
```

`rh upgrade` はpending Work、Human Decision、Attention drop、transition lock、
Archive済みworkspace、または研究側で変更されたmanaged fileがある場合に停止する。
この停止は `git reset --hard` で回避してはならない。

旧研究を archive することと、新研究を作ることは別操作である。必要なら Human が `archive` を先に実行し、その bundle の場所を記録してから `new` を実行する。
