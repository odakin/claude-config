# Scheduled Tasks 規約

Claude Code scheduled tasks を使うリポで適用。CLAUDE.md から参照: `~/Claude/claude-config/conventions/scheduled-tasks.md`

## <a id="execution-locus-selection"></a>0. 実行 locus で機構を選ぶ (= scheduled task が正しい道具か先に問う)

定期/自動ジョブを組む前に、 **(1) run-time に Claude の judgment が要るか** + **(2) 何にアクセスするか** で実行機構を選ぶ。 「定期 = scheduled task」 と reflex で選ぶと、 deterministic job に Claude を毎回起こす過剰や、 cloud routine の local-access 不在に後で衝突する。

| ジョブの要件 | 機構 | 理由 |
|---|---|---|
| **deterministic** な機械処理 (= run-time に Claude judgment 不要) で local file/repo/CLI (sips, npm, git push) に依存 | **launchd / cron (該当マシンで local 実行)** | local 実行・token cost ゼロ・LLM 非依存・Claude runtime 不要。 純粋な script はこれが最適 |
| **Claude の judgment / draft** が run-time に要る (+ PushNotification を使いたい) | **Claude Code scheduled task (SKILL.md)** | **local の fresh Claude session で実行され local file/cred に アクセスできる** (= 実例: daily-mail-triage-check が `~/Claude/.../*.py` を local OAuth `~/.gmail-mcp/` で実行)。 「backend」 は **prompt の保存先**であって実行 locus ではない (下記 §アーキテクチャ)。 ⚠️ 1 run = 1 session が「最近の項目」 に積まれる ([#headless-session-persistence](#headless-session-persistence)、 launchd cron + `claude -p` なら回避可) |
| 職場/組織 NW から API が block される (例: campus から Discord API が Cloudflare 1010) | **GitHub Actions (cloud cron)** | 別 network egress から実行 + secret で credential 供給 |

⚠️ **`schedule` skill の「remote agent / routine」 は上記 scheduled task とは別物**: これは **cloud で起動し local file に一切アクセスできない** (= 過去に「local 完結 script を schedule skill で trigger」 が cloud 実行で根本的に動かず redesign した RCA)。 local 依存ジョブを cloud routine に載せない。 **scheduled task (= local) と混同しない** (= 「scheduled task は local 不可」 は誤り、 上記の通り local access あり)。

**reflex**: 「定期実行 = scheduled task」 ではない。 まず **(1) run-time に Claude judgment が要るか** — 不要 (= 純粋 script) なら launchd/cron (= Claude を毎回起こさない、 決定的、 無料)。 要るなら scheduled task (= local access あり)。 次に **(2) cloud に出す必要があるか** — NW block 回避なら GitHub Actions、 それ以外で local 依存があるなら cloud routine (schedule skill) を避ける。 実行 locus が不確かな機構は、 local access を前提にする前に locus を検証する (= 機構名から「remote だろう」 と推測せず実証する)。

machine-local job を「どのマシンに登録するか / 登録漏れをどう surface するか」 は [multi-machine-state.md](multi-machine-state.md)。 無人 publish の安全 gate は [`data-pipeline-automation.md` autonomous-execution-gate](data-pipeline-automation.md#autonomous-execution-gate)。

### <a id="account-switch-independent"></a>アカウント切り替えに非依存にしたいとき (= Claude Code desktop app と CLI の 2 認証ストア)

Claude Code の認証は **2 つの独立ストア**を持つ: **Claude Code desktop app** と **CLI (`claude`、 `~/.claude.json` の単一 `oauthAccount`)**。両者は別アカウントで**共存**しうる — `claude auth` は login/logout/status のみ (= 同時 1 アカウント) だが、 **Claude Code (desktop) 側のアカウント切り替えは CLI の `~/.claude.json` を上書きしない** (実測: Claude Code (desktop) と CLI が別アカウントで同時に存在した)。これが無人ジョブの機構選択に効く:

- **scheduled task はアカウントに紐づく** → Claude Code (desktop) のアカウントを切り替えると、 別アカウントで作った task が見えなくなり **発火が止まる** (実測: 切替後に定時ジョブが約 37h 未発火)。
- **launchd cron + `claude -p --permission-mode auto` は CLI 認証 (= 固定・Claude Code (desktop) 切替に非依存) で走る**。`claude -p` は Claude judgment (翻訳・判定・検証ゲート) と MCP も headless で提供する (実測: `--permission-mode auto` で MCP 込みの SKILL が headless 完走し、 SKILL の安全則も順守された)。

→ 上の表は「Claude judgment 要 → scheduled task」 だが、 **Claude judgment が要り、 かつ アカウント切替で止めたくないなら、 第 3 の道 = launchd cron + `claude -p` (= CLI 認証を固定土台にする)**。同じ理由で `claude remote-control` サーバーモード (= CLI 認証で常駐、 [remote-control-server.md](remote-control-server.md)) も Claude Code (desktop) 切替に非依存。 ⚠️ ただし launchd は LANG 空 (C locale) なので `claude -p` の prompt は ASCII のみにする ([shell-multibyte-truncation.md](shell-multibyte-truncation.md))。

### <a id="launchd-cron-engine"></a>launchd cron の登録機構 (= 汎用エンジン)

launchd cron で無人ルーチンを回す plist の生成・登録・状態確認・解除は、 `scripts/install-launchd-cron.sh` が **汎用エンジンの SoT** (= [remote-control-server.md](remote-control-server.md) と同じ「スクリプトが plist / label 設計の SoT、 doc に複製しない」 パターン)。 呼び出し側は label prefix・workdir・ROUTINES を渡すだけで、 **ROUTINES list / 個別ジョブ定義はエンジンに焼かない** (= エンジンは汎用機構のみ、 個別ジョブは呼び出し側の責務)。

```sh
install-launchd-cron.sh --label-prefix PREFIX [--workdir DIR] \
  --routine "id|type|target|cron" [--routine ...] [ACTION]
```

- **ACTION**: (既定 install) / `--status` / `--run <id>` / `--install-one <id>` / `--uninstall-one <id>` / `--uninstall` / `--ensure`。 `--uninstall-one` は label-prefix + id だけで動く (= routine spec 不要、 期間限定ジョブの停止に使える)。 `--ensure` は **未 install の routine だけを install** する冪等・quiet・fail-open アクション (= loaded 済 / target 未取得 / 非 macOS を無音 skip) で、 **SessionStart hook から呼んで「新 routine を git pull したマシンに自動配備」** する用途 (= ROUTINES に足して pull すれば次 session でそのマシン〔新 active host 等〕に自動 install、 「新ホストへ手動 install」 gap を塞ぐ)。
- **type**: `skill` = `claude -p --permission-mode bypassPermissions` で SKILL.md を indirection 実行 (= Claude judgment 要) / `cmd` = script を直接実行 (= 決定的・claude 不要)。
- **cron** は 5-field。 **`*/N` step 分** (= `*/30` → Minute `[0,30,...]`) と **`N-M` 曜日範囲** (= `1-5` → Weekday 月〜金) を StartCalendarInterval 配列へ展開する (launchd は step を持たないため)。
- CLI 認証 (`~/.claude.json` の単一 account) で走るので Claude Code (desktop) のアカウント切替に非依存 (= 上記)。 launchd は LANG 空なので prompt は ASCII のみ ([shell-multibyte-truncation.md](shell-multibyte-truncation.md))。
- **`--gate "<snippet>"`** (任意): wrapper に `cd WORKDIR && <snippet> || exit 0; exec <routine>` の形で gate を挿入する。 snippet が非 0 で終わると routine は実行されず exit 0 (= defer)。 複数マシンで「今どのマシンが本番か」 を台帳で切り替える **active-routine-host failover** ([`multi-machine-state.md` account-host-failover](multi-machine-state.md#account-host-failover)) に使う (gate 実体 = `scripts/routine-host-gate.py`)。

**止め方の違い (= launchd cron 版 vs scheduled-task MCP 版)**: 同じ「定期ジョブ」 でも停止操作が機構で異なる。 launchd cron 版は `--uninstall-one <task-id>` (= `launchctl bootout` + plist 削除)、 scheduled-task MCP 版は `scheduled-tasks` MCP の delete。 期間限定ジョブ (= 大会期間だけ等) の自己停止 runbook を書くときは、 **どちらの機構で登録したか**に応じた停止コマンドを記す (= 機構を取り違えると停止できない)。

### <a id="headless-session-persistence"></a>無人 run の session 痕跡 (= 「最近の項目」 noise と `--no-session-persistence`)

定期 routine は **1 run = 1 session** を作る。 これがどの surface に痕跡を残すかは機構で違い、 daily × 複数本を数週間回すと session 一覧 (= desktop app の「最近の項目」) が routine session で埋まる実害になる (2026-07 実測: 3 本/日 × 数週間 ≈ 数十 entry を手で消す羽目)。

| 機構 | session 痕跡 (2026-07 実測) |
|---|---|
| **Claude Code desktop app の scheduled task** | 1 run ごとに desktop session が作られ「最近の項目」 に積まれる。 **抑止 option なし** (= task 側に session を隠す設定が存在しない)。 掃除は `archive_session` (1 件ずつ承認) か手動 |
| **launchd cron + `claude -p`** (既定) | transcript は local `~/.claude/projects/<dir>/<session-id>.jsonl` に保存される。 ⚠️ さらに **settings で `remoteControlAtStartup: true` のマシンでは headless run も Remote Control session として claude.ai に登録され「最近の項目」 に出る** (= `--remote-control-session-name-prefix` default = hostname による自動命名 `<hostname>-<codename>`。 2026-07-04 実測: 30 分 cron の完走 run が別マシンの一覧に出現 + run session が終了せず**数十件 live で積み上がる**事例)。 ⚠️ errata (同日): 初版の「recents に出ない実測」 は standby マシン (= active-routine-host gate defer で cron が実行されない側) での観測で、 **観測として無効**だった |
| **launchd cron + `claude -p --no-session-persistence` + RC override** (= 下記、 engine 既定) | **session が disk にも session 一覧にも一切残らない** (実測: .jsonl 生成ゼロ + `list_sessions` 不出現)。 `--no-session-persistence` 単独で RC 登録まで抑止するかは未検証のため、 RC override と併用する (= belt-and-braces) |

- **`--no-session-persistence` は `--print` (= `-p`) 専用 flag**。 resume 不可・transcript 無しになるので、 **事後デバッグは plist の `StandardOutPath` log file が唯一の手掛かり** — 無人 routine は元々 log file が主 debug surface なので通常は失うものがない。 対話 session には使わない。
- **RC 自動有効化の per-invocation override**: settings の `remoteControlAtStartup: true` (= 手元対話 session のリモート続行用) は**そのマシンの CLI 全 session に効く**ため、 cron run には `--settings '{"remoteControlAtStartup":false}'` を渡して RC 登録を無効化する (= 対話 session 側の設定・リモート続行は不変。 これを怠ると上表の「hostname-prefix RC session が recents に出る + live 積み上がり」 が起きる)。
- `scripts/install-launchd-cron.sh` (= 汎用エンジン) は skill 型 routine に **`--no-session-persistence` と RC override の両方を capability-gated で自動付与** (= install/run 時に `--help` probe、 未対応 CLI では従来挙動に degrade して routine を殺さない)。 ⚠️ **flag は plist 生成時に焼かれる** — engine 更新後は各マシンで再 install しないと既存 routine に反映されない (`--ensure` は未 install 分のみで既存 plist を再生成しない)。
- 旧 CLI 世代の代替: `CLAUDE_CODE_SKIP_PROMPT_HISTORY=1` (= 全 transcript 書込み抑止、 対話含め全 run に効くので過剰) / `cleanupPeriodDays` (= 起動時の古い session 掃除、 即時性なし)。 `--no-save` / `--incognito` / session-sync 無効化 env は**存在しない** (2026-07 時点 docs + issue 調査)。
- **PushNotification は headless `claude -p` でも動く** (実測: wire 健全)。 ⚠️ user がキーボード操作中 (直近 ~60s) は「Not sent (user active)」 で suppress される **documented 挙動 = エラーでない**。 無人 routine の SKILL には「Not sent は正常、 リトライしない」 と書いておく (= 無人時間帯なら届く)。
- **機構選択への含意**: 毎日/高頻度の無人 routine を desktop scheduled task で回すと「最近の項目」 noise が構造的に発生する。 launchd cron + `claude -p` + 上記 2 flag なら zero-trace (= [#account-switch-independent](#account-switch-independent) のアカウント非依存に加えた第 2 の移行動機)。

## アーキテクチャ: SKILL.md とバックエンドの二重構造

### 構造

```
リポ/skill/{task-id}/SKILL.md     ← git 管理（差分追跡・レビュー用）
        ↑ symlink
~/.claude/scheduled-tasks/{task-id}/SKILL.md  ← ローカル参照
        ✗ 実行時には読まれない

Claude バックエンド（リモート）    ← 実際に実行される prompt
```

### なぜこうなっているか

- **SKILL.md をリポに置く理由**: git で差分追跡・コードレビューができる。複数端末間で `git pull` で内容を共有できる
- **バックエンドが SKILL.md を読まない理由**: scheduled task の実行 prompt は `create_scheduled_task` / `update_scheduled_task` 呼び出し時にバックエンドに保存され、以後ローカルファイルは参照されない（Claude Code の仕様）
- **symlink の役割**: ローカルで `~/.claude/scheduled-tasks/` を見たとき、SKILL.md の内容をリポ側で一元管理するための便宜。実行には影響しない
- **「バックエンド（リモート）」 の正確な意味**: これは **prompt の保存先**を指す (= prompt 本文が backend に保存される)。 **agent の実行自体は該当マシンの local fresh session** で、 **local file / OAuth token / CLI に access できる** (= 実例: daily-mail-triage-check の SKILL.md は `~/Claude/.../*.py` を local OAuth `~/.gmail-mcp/` で実行する前提で書かれ、 §15 メール防御の一部として依存されている)。 ⚠️ 「backend remote 保存」 を「remote 実行 = local file 不可」 と誤読しないこと (= §0 の機構選択で「scheduled task は local 不可」 と誤判定する原因になる)。 cloud で実行され local file に触れないのは別物の **`schedule` skill の routine** の方 (§0 参照)

### 制約

SKILL.md を single source of truth にできない。リポの SKILL.md とバックエンドの prompt が乖離するリスクが常にある。

## <a id="registrable-session-types"></a>登録できる session 種別 (= bridge / デスクトップアプリ backend session では create_scheduled_task が wire されない)

`create_scheduled_task` / `update_scheduled_task` は **harness 組み込み tool** (= MCP server ではない。 `~/.claude.json` の `mcpServers` に現れない、 CronCreate と同類)。 これらが session で呼べるかは **起動経路で決まる**:

- ✅ **登録できる**: Terminal から `claude` を直接起動した通常 Claude Code CLI session (= `--allowedTools` 無制限運用)。 既存の登録済 task (`weekly-web-freshness` 等) はこの経路で作られている。
- ❌ **登録できない**: desktop / Claude Code desktop app が裏で起動する **bridge session** (= 判定 = `env | grep CLAUDE_CODE_ENVIRONMENT_KIND` が `bridge` + `CLAUDE_CODE_ENTRYPOINT=sdk-cli`)。 `--allowedTools` で tool が大幅に subset され、 `create_scheduled_task` が **session に wire されない** (= `ToolSearch "select:create_scheduled_task"` が "No matching deferred tools found")。 これは [`mcp.md` desktop-allowedtools-restriction](mcp.md#desktop-allowedtools-restriction) と同根 (= 同じ subset 機構が組み込み scheduled-task tool も削る)。

**対処**: bridge session で scheduled task を登録したくなったら、 同じマシンの **Terminal で `claude` を直起動**した session に移って `create_scheduled_task` を呼ぶ (= mcp.md 対処 (b))。 bridge session 自身からは制限なし session を生やせない (= harness 仕様)、 user の手動操作が要る。

### ⚠️ bridge session で `CronCreate durable` に逃げない (= 永続化されない trap)

「定期実行が要る、 でも `create_scheduled_task` が無い」 となったとき harness の `CronCreate` に逃げると、 **`durable: true` を渡しても無視され session-only になる** (= 2026-06-23 実証: `CronList` が `[session-only]` 表示、 `~/.claude/scheduled_tasks.json` が未作成、 session を閉じると消える)。 `RemoteTrigger` (= claude.ai routine) は cloud 実行で local file に触れない (§0)。 → **bridge session には永続 local scheduled task を作る手段が無い**。 唯一の道は上記 Terminal 直起動 session での `create_scheduled_task`。

> 判定 reflex: 定期 local job を登録する前に起動経路を疑う。 `env | grep CLAUDE_CODE_ENVIRONMENT_KIND` が `bridge` なら登録系 tool が削られている前提で、 Terminal 直起動 session に移る。 (= harness 版 2.1.165 で観察。 `--allowedTools` の subset 内容は版で変わりうる — UI 同様に実機で確認する。 ⚠️ scheduled task 自体は backend 実行されれば local file に access できる 〔§アーキテクチャ〕。 ここで言う制約は **登録 (= create/update tool) を呼べる session** の話であって、 実行 locus の話ではない)

## ルール

### SKILL.md にステップ0: SESSION.md チェックを含める（必須）

Scheduled task のエージェントは CLAUDE.md / CONVENTIONS.md を確実に読む保証がない。そのため SESSION.md の要対応事項が無視されるリスクがある。対策として、**各 SKILL.md の冒頭にステップ0として SESSION.md チェックを明記する**。これは CONVENTIONS.md §3 の「リポでの作業開始手順」を task prompt 内で確実に発火させるためのもの。

CONVENTIONS.md のルール（人間セッション・手動実行をカバー）と SKILL.md のステップ0（scheduled task 自動実行をカバー）は役割が異なり、両方必要。

### SKILL.md 編集時（必須。ただし「焼き込み」prompt の場合）

> 以下は prompt に SKILL.md **全文を焼き込む**標準方式が対象。 prompt を **indirection** (= 「`<path>/SKILL.md` を Read して実行せよ」 だけを backend に保存) にしているなら、 backend は path しか持たず実行時に最新の SKILL.md を読むため **この同期は不要** (= § prompt 設計 参照)。

1. リポの SKILL.md を編集する
2. **直後に `update_scheduled_task` で prompt フィールドを同期する**
3. コミット・push する

この順序を守らないと、バックエンドが古い prompt のまま実行される。

### 新規タスク作成時

1. `create_scheduled_task` でバックエンドに登録（prompt を渡す）
2. リポに `skill/{task-id}/SKILL.md` を作成（同じ内容）
3. symlink を張る: `ln -s /path/to/repo/skill/{task-id}/SKILL.md ~/.claude/scheduled-tasks/{task-id}/SKILL.md`

### マルチマシン運用

- バックエンドはマシンごとに独立。マシン A で `update_scheduled_task` しても、マシン B のバックエンドは更新されない
- 新しいマシンで pull 後、そのマシンで使う scheduled task は `update_scheduled_task` で prompt を同期すること
- SESSION.md にマシン固有の要対応事項を書いておくと pull 後に気づける

## パス表記について

本ドキュメントおよび各リポの CLAUDE.md では `~/Claude/` をハードコードしている。これは現運用者（odakin）の全マシンで統一されたパスであり、`<base>` のような抽象化は行わない。共同編集者が `~/github/` 等の別パスを使っていても、本規約はリポオーナーの Claude Code scheduled task 運用にのみ適用されるため問題ない。共同編集者が scheduled task を運用する場合は、その時点でパス抽象化を検討する。

## UI と手動実行・tool 承認 (= local scheduled task の運用)

⚠️ UI 構造は Claude Code app の版で変わる (= 手順描写は陳腐化前提で疑う、 下記は 2026-06 時点 / 公式 docs `desktop-scheduled-tasks.md` ベース)。 構造非依存の要点を優先。

- **管理場所**: local scheduled task は remote routine (= `claude-ai-routines.md`) と **同じ "Routines" tab で統合表示** される (= 作成時に Local / Remote を選ぶ)。 task が発火すると "Scheduled" セクションが出現しそのセッションが並ぶ。 ⚠️ `create_scheduled_task` のレスポンス文言「manage it from the Scheduled section」は誤解を招く (= 発火前は Scheduled section が無い、 実体は Routines tab)。 tool レスポンスの UI 案内も実機と乖離しうる (= 鵜呑みにせず実機 or docs で確認)。
- **手動実行 (Run now)**: Routines tab → task の detail page → "Run now"。 スケジュールを待たず即 fresh session を起動。 MCP / CLI からの run action は無い (= UI のみ。 list/create/update の MCP tool に run は無い)。
- **tool 承認の事前付与**: cron 自動実行は SKILL.md が使う tool (Bash / WebSearch / Edit 等) の承認が要り、 未承認だと自動実行が **そこで停止する**。 回避策: 作成後に **"Run now" で 1 回手動実行 → 各 tool に「常に許可」** を選ぶ → task に保存され以降の自動実行に auto-apply (detail page の "Always allowed" panel で確認・revoke 可)。 代替: `~/.claude/settings.json` の `permissions.allow` に追加 (= allow rule は scheduled task session にも適用される。 ただし全 session 共通なので広すぎる許可を避け、 Run now 経由で必要 tool だけ承認する方が安全)。

## prompt 設計: 焼き込み vs indirection

backend は prompt 本文を保存し SKILL.md を実行時に読まない (= 上記アーキテクチャ)。 この乖離リスクへの 2 つの対処:

1. **焼き込み (= 標準)**: prompt = SKILL.md 全文。 SKILL.md 編集時に `update_scheduled_task` で同期必須 (= 上記「SKILL.md 編集時」 ルール)。
2. **indirection**: prompt = 「`<絶対path>/SKILL.md` を Read tool で読み上から self-contained に実行せよ」 + 最小限の前提だけ。 SKILL.md (= git canonical) が手順の SoT で、 **手順変更が backend 再登録なしで次回実行に反映される** (= drift しない、 = §「制約」 の SKILL.md↔backend 乖離を構造的に解消)。
   - ⚠️ **trade-off**: prompt に説明文 (= 頻度・背景) や安全則を焼くなら、 その焼いた値は **設定値変更時に prompt 本体も sweep** する (= 焼いた分だけ drift 対象に戻る)。 2026-06-04 RCA: ある定期 publish task の頻度を変えた際、 cron と description は `update_scheduled_task` したが **prompt 冒頭に焼いた「週次」表記を取り逃した** (= cron / description / SKILL.md / 周辺 doc は直したのに backend prompt 本体だけ漏れた、 整合性軸 sweep の死角)。 設定値を 1 つ変えたら **その値が現れる全 surface (= コード / doc / backend prompt) を grep して sweep** する (`CONVENTIONS.md §3` 整合性軸)。
   - indirection でも安全則を prompt に焼く判断はある (= fresh session が SKILL.md read に失敗しても安全則が効く保険)。 その場合「焼いた分だけ drift 対象」 と自覚する。

## recurring task の jitter

recurring (`cronExpression`) task は dispatch 時に数分の deterministic jitter が乗る (= server load 分散、 例: `0 3 * * *` → 実発火 03:08)。 one-time (`fireAt`) は jitter なし。 分単位の正確な発火を要する用途では考慮する。

## 経緯

- 2026-03 symlink 方式を導入。SKILL.md 編集が自動反映されると想定していた
- 2026-04-01 `inspire-monthly` で同期漏れが発覚。バックエンドが旧 prompt で実行され、存在しないモジュール `arxiv_digest.profile` を呼んで失敗
- 原因調査の結果、バックエンドは SKILL.md を実行時に読まないことが判明。手動同期ルールを導入
- 2026-06-04 ある定期 publish task の登録・頻度変更を通じて UI 操作 / indirection trade-off / jitter の 3 節を追記。 着手時に本 doc を読まず `schedule` skill を寄り道した RCA (= §0 の「scheduled task と schedule skill を混同しない」 は既出だった = 着手時に本 doc を先に読むべきだった)
