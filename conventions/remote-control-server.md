# Remote Control サーバーモードの launchd 常駐 (= スマホからいつでも Claude Code)

`claude remote-control` (サーバーモード) は、スマホの Claude アプリや claude.ai/code から
**自分のマシン上に新規 Claude Code セッションを生やせる待ち受けサーバー**。実行は常に
ローカルマシン側なので、filesystem・MCP・hooks・settings がそのまま使える (= Anthropic
インフラで動く cloud session とは別物)。これを launchd で常駐させると「常時起動マシンが
ある人は、いつでもどこでもスマホから自分の環境で Claude Code」になる。

install / plist / KeepAlive 設計の SoT は `scripts/install-remote-control-server.sh`
(= 本 doc は要件・落とし穴・運用知見のみ。公式 doc: https://code.claude.com/docs/en/remote-control)。

## 使い方

```sh
# 常時起動しているマシンで 1 回 (idempotent)。--dir がリモート生成セッションの root
sh scripts/install-remote-control-server.sh --dir "$HOME/my-projects"

sh scripts/install-remote-control-server.sh --status      # 稼働確認 + log tail
sh scripts/install-remote-control-server.sh --uninstall   # 解除
```

接続側: スマホ Claude アプリ → Code タブ (またはブラウザで claude.ai/code) →
**緑ドット + computer icon** の environment を選んで新規セッション作成。launchd 常駐では
QR (space キー) は使えないが、接続先は ① claude.ai/code のセッション一覧 ② log 内の
`https://claude.ai/code?environment=env_…` URL の 2 経路で入れる (= QR 不要)。

## <a id="requirements-and-selfheal"></a>要件 (= 欠けていても install は通り、解消後 60 秒以内に自動で生き返る)

| 要件 | 欠けた時の症状 | 解消 |
|---|---|---|
| macOS + Claude Code v2.1.139+ (RC server 起動 minimum。 v2.1.51+ 系は `remote-control` サブコマンド自体は存在するが server 起動時に runtime error で cycling する、 詳細 [Troubleshooting](#ts-version-mismatch)) | 起動時 `too old for Remote Control` error | `claude update` |
| **workspace trust** (= config JSON `projects[<dir>].hasTrustDialogAccepted`) | 未承認だと非対話の launchd サーバーが dialog を出せず `Workspace not trusted` で exit-1 永久 cycling ([#ts-workspace-trust](#ts-workspace-trust)) | **install script が install 時に自動 seed** (2026-07-02〜)。 手動 fallback = 一度 `cd <dir> && claude` で承認 |
| **claude.ai OAuth login** (subscription 必須) | log に「must be logged in」で即 exit を繰り返す | ターミナルで `claude auth login`。⚠️ API key・旧「managed key」型・`claude setup-token`/`CLAUDE_CODE_OAUTH_TOKEN` の inference-only token は全て不可 (= 公式 docs)。`ANTHROPIC_API_KEY` が env にあれば unset。`claude auth status` が loggedIn でも `subscriptionType: null` ならこれ (2026-06-12 実測)。 **唯一 seed 不能な interactive 段** (= keychain + browser OAuth、 マシン × アカウント 1 回きり) |
| **初回同意** (= config JSON top-level `remoteDialogSeen`) | log に「Enable Remote Control? (y/n)」、無人では進めない | **install script が install 時に自動 seed** (2026-07-02〜)。 手動 fallback = `claude remote-control` を一度起動して y |

この managed-key 非対応は upstream の既知制約 (= anthropics/claude-code #50977〔API key / setup-token OAuth サポート要望〕・#50642〔Bedrock 認証〕の feature request、いずれも未対応)。ユーザ側のミスではないので `subscriptionType: null` を見たら迷わず `claude auth login`。

## CLI フラグ早見 (= `claude remote-control --help`、2026-06-12 実測)

| フラグ | 効果 |
|---|---|
| `--spawn same-dir\|worktree\|session` | 既定 same-dir = 全セッション cwd 共有 / worktree = セッション毎に git worktree (起動 dir が git repo 必須) / session = 単一セッション (それが終わると server も exit)。実行中 `w` キーで same-dir↔worktree トグル |
| `--capacity N` | same-dir / worktree の最大同時セッション数 (既定 32) |
| `--permission-mode MODE` | spawn するセッションの permission mode (acceptEdits / auto / bypassPermissions / default / dontAsk / plan) |
| `--name NAME` | セッション表示名のみ (cwd には無関係) |
| `--remote-control-session-name-prefix PREFIX` | 自動生成名の接頭辞 (既定 hostname、env `CLAUDE_REMOTE_CONTROL_SESSION_NAME_PREFIX`) |
| `--[no-]create-session-in-dir` | 起動時に cwd でセッションを 1 個先行作成 (既定 on)。worktree モードではこの 1 個だけ cwd に残り以後の on-demand が worktree 化 |
| `--debug-file PATH` / `-v,--verbose` | デバッグログ |

## 設計の要点 (= 変更・移植する人向け)

- **復元力**: `KeepAlive` + `ThrottleInterval 60` で 再起動 / crash / 未認証 / ネットワーク断
  (10 分超で claude 側が自滅する仕様) の全てから自動復帰。放置運用前提。
- ⚠️ **PTY を与えてはいけない**: launchd 配下で script(1) 等の PTY 経由にすると、stdin
  (/dev/null) の EOF が端末 close として claude に届き graceful exit → 60 秒周期の
  接続/切断 cycling になる (2026-06-12 実測 RCA)。non-TTY 直接 exec なら stdin EOF を
  無視して安定する (= TUI の QR 表示等は失うが、サーバー機能に不要)。
- shutdown 時の「Environment preserved」は正常 (= environment は再起動を跨いで維持され、
  同じ environment ID で再接続する)。

## 運用知見 (実測)

- **モバイル UI の「リポ選択」は cwd を変えない**: 既定の `--spawn same-dir` では新規
  セッションの cwd は常にサーバーの `--dir`。UI で何を選んでも変わらない (2026-06-12
  transcript 配置で実測)。リポ単位で隔離したければ `--spawn worktree` (= `--dir` 自体が
  git repo である必要、セッション毎に worktree)。
- **cloud session との取り違え注意**: アプリの新規作成 UI には「ローカル (Remote Control)」
  と「cloud session (Anthropic インフラ、GitHub repo 必須)」が同居する。緑ドット +
  computer icon がローカル。
- **死んだセッションの残骸**: サーバー再起動を跨ぐと旧セッション行が一覧に残り、開くと
  無限スピナーになる。残骸は削除し、新規作成で入り直す。
- 並列セッションは同じ cwd を共有する (same-dir) ので、同一ファイルの同時編集は衝突し得る。
- **ultraplan を起動すると Remote Control が切断される** (= 両者が claude.ai/code を占有、公式 docs)。
- ⚠️ **`--sandbox`/`--no-sandbox` の食い違い**: 公式 docs は server mode の flag に filesystem/network 隔離の `--sandbox` を挙げるが、v2.1.165 の `claude remote-control --help` には**無い** (= 自版で要確認、版依存)。常時公開サーバーで隔離を効かせたい場合は自分の `--help` で実在を確認してから付ける (= docs だけ見て plist に焼くと unknown-flag で永久 cycling し得る)。

## <a id="troubleshooting"></a>Troubleshooting

install が通ったのに server がまともに起動しない・接続できないときの実測 pattern。 いずれも `install-remote-control-server.sh` の preflight が `[warn]` として拾う設計 (= 静かに素通りさせない)。

### <a id="ts-version-mismatch"></a>"Remote Control is not enabled for your account" — 実は CLI 古すぎ (v2.1.139 未満)

**症状**: `claude remote-control` 直後に `Error: Remote Control is not enabled for your account. Contact your administrator.` が返る。 org policy の blocker と読めるが実は誤誘導 — RC server 起動は v2.1.139 以上を要求し (= server 側が返す runtime error `too old for Remote Control` の閾値)、 v2.1.53 系の古い CLI がこの misleading な wording を返す。 launchd log tail に `Your version of Claude Code (X.Y.Z) is too old for Remote Control.` があれば確定。

**検出**:
- `claude --version` が 2.1.139 未満 → install script の version gate が `[warn]` を出す
- `which -a claude` が複数を返す → 古い方が先に呼ばれている疑い (次項)

**Fix (どれか)**:
- `claude update` (現在 first-in-PATH の CLI が更新される)
- 新しい install (例: `~/.npm-global/bin/claude`) を PATH 前置き ([`shell-env.md`](shell-env.md) の PATH 二層防御と併読、 次項)
- 古い install を削除 (例: 過去に `sudo npm install -g` で置いた `/usr/local/bin/claude` が root 所有で残置、 通常の `claude update` では触れない)

⚠️ この error の literal を org policy blocker と誤読して support に issue を切る前に必ず `claude --version` と `which -a claude` を確認。 実測で **~1.5h 診断に溶かした** 事例あり。

### <a id="ts-api-key-conflict"></a>"Remote Control requires claude.ai subscription auth" — `ANTHROPIC_API_KEY` が混入

**症状**: v2.1.139+ の新しい CLI で `Error: Remote Control requires claude.ai subscription auth. ANTHROPIC_API_KEY is set, so this session is using API-key auth — unset it (or run in a shell without it) to use Remote Control.` が返る。 これは**正直な error** で wording どおり。

**launchd 側は既に安全** (= plist が defensive に `unset ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN` してから `exec claude remote-control` する = `install-remote-control-server.sh` の SoT)。 問題は **install / verify を叩く user shell** に env が残っているとき — probe / `claude auth login` / 手動 `claude remote-control` が全部この error に落ちる。

**Fix**:
- 一時: `unset ANTHROPIC_API_KEY` してから作業
- 恒久: shell 起動 file (`.zshenv` / `.zprofile` / `.zshrc` / `~/.config/`) を grep して export 元を除去。 出所不明な場合は `launchctl getenv ANTHROPIC_API_KEY` や Terminal.app / iTerm2 の per-profile plist も確認 (= GUI で env を渡している可能性)。 詳細な env var 二層防御は [`shell-env.md`](shell-env.md)

⚠️ RC は claude.ai OAuth (subscription) 必須で API key auth を拒否する upstream 制約 (= `#50977` feature request、 [§要件](#requirements-and-selfheal) 参照)。 「動いていたのに動かなくなった」 系は API key を後から export した回帰が疑わしい。

⚠️ **status-check 版の同 trap (2026-07-02 実測)**: `ANTHROPIC_API_KEY` が env にあると **`claude auth status` が `authMethod: api_key` で `loggedIn: true` (email 無し) を返す** — 「login 済か」 を auth status で判定する automation (install wrapper / SessionStart hook 等) が **偽 auth 判定** (= 「別アカウント ()」 の空 email error や、 未 auth dir を auth 済と誤認) に落ちる。 automation 側の Fix = auth 確認は必ず `env -u ANTHROPIC_API_KEY -u CLAUDE_CODE_OAUTH_TOKEN` で叩き、 判定は `"loggedIn": true` でなく **`"authMethod": "claude.ai"`** を要求する (= launchd plist の defensive unset と同じ発想を status-check にも)。

### <a id="ts-path-helper-inversion"></a>macOS `path_helper` が PATH を反転させて古い CLI が呼ばれる

**症状**: `.zshenv` で user-scoped bin (例: `~/.npm-global/bin`) を PATH 先頭に prepend しても、 login shell (= Terminal 起動時 / launchd job 実行時) では `/usr/local/bin` 等 system path が上に来ていて古い CLI が呼ばれる。 [前項の version mismatch](#ts-version-mismatch) の root cause として典型。

**機構**: macOS の `/etc/zprofile` が `eval "$(/usr/libexec/path_helper -s)"` を実行し、 `/etc/paths` (先頭 `/usr/local/bin`) を PATH の**前**に押し込む。 `.zshenv` が login 前に走っても、 `.zprofile` 段階で反転する。

**検出**:
```
zsh -l -c 'echo $PATH' | tr ':' '\n' | head -5
```
先頭に `/usr/local/bin` が居て、 user-scoped bin (`~/.npm-global/bin` / `~/.local/bin` 等) がその下なら反転している。

**Fix**: `~/.zprofile` (login shell が `/etc/zprofile` の直後に読む) で user path を **再 prepend** する。 この axis (= `/etc/zprofile` の後始末) と、 [`shell-env.md`](shell-env.md) の PATH 二層防御 (= スナップショットパッチによる不足補填) は**直交する別 axis** で、 両方必要。 前者は「順序」 の問題、 後者は「消失」 の問題。

### <a id="ts-workspace-trust"></a>"Workspace not trusted" — virgin config dir の headless 死 (exit-1 永久 cycling)

**症状**: launchd label は loaded なのに process が居ない (`launchctl list` で pid `-` / `last exit code = 1`)。 server log が `Error: Workspace not trusted. Please run claude in <dir> first to review and accept the workspace trust dialog.` で埋まる。 KeepAlive が 60 秒ごとに retry して**永久 cycling** — 表面上は「server が silent に消えた」 ようにしか見えない (2026-07-02 実測: desktop app の bridged session 切断調査から発覚)。

**機構**: workspace trust と RC 初回同意は、 いずれも config dir ごとの config JSON (`<config-dir>/.claude.json`、 既定は `~/.claude.json`) に保存される **interactive dialog 由来の flag**。 pinned per-account 構成で config dir を新設すると、 **OAuth (keychain) を済ませても trust / consent は virgin のまま** — headless の launchd server は dialog を出せず exit 1。 「OAuth 1 回で永続」 の裏に interactive 段がもう 2 つ隠れていた、 が本質。

**Fix (どれか)**:
- install script を再実行 (= 2026-07-02 以降、 install 時に `projects[<dir>].hasTrustDialogAccepted` + `remoteDialogSeen` を自動 seed。 server は 60s 以内に self-heal)
- 手動 seed: config JSON に上記 2 flag を書く
- interactive fallback: `cd <dir> && CLAUDE_CONFIG_DIR=<cfg> claude` で trust 承認 → `claude remote-control` に y

**検出**: fleet-heartbeat が log marker `Workspace not trusted` → `trust_error` として記録し、 reader (`check-fleet-status.py`) が 🔴 surface する。

**セキュリティ note**: 自動 seed は「この dir を root に server を install する」 という user の明示行為を trust consent と見なす (= trust dialog が確認したい内容と install の意図が一致するため、 consent の機械化であって bypass ではない)。 seed 対象は指定 `--dir` 1 個のみ。

### <a id="ts-desktop-bridge-4090"></a>desktop app の「リモートコントロールが切断されました」 — bridged worker の code 4090 eviction

**症状**: Claude desktop app の conversation が「ターミナルの Claude Code セッションが応答しなくなりました / The bridged Claude Code process stopped responding mid-turn」 を表示する。 RC server の障害と紛らわしいが**別物** — desktop の対話 session はマシン上の bridged CLI process が worker として動いており、 それが turn 中に落ちた症状。

**機構**: 別の connection が同じ session を claim すると、 先住 worker が `Transport closed: this connection is no longer the active worker for the session (code 4090)` で eject される (= app log `~/Library/Logs/Claude/main.log` に記録)。 同マシンの RC server / auth が不安定な時に再接続 race で連発しやすい。

**対処**: (1) `main.log` を `code 4090` で grep して時刻を特定 (2) config の projects dir にある `bridge-pointer.json` の pid が死んでいれば stale (= 削除可) (3) 同時期に RC server が cycling していれば先にそれ (前項 trust / auth / version) を治す (4) conversation はメッセージ再送 or 新規作成で復帰。 root は upstream の worker 管理で client 側から予防は不能 — できるのは検出と復旧のみ。

### 併発 pattern

上記は独立に起こるが、 特に **dual-install (v2.1.53 残置) + `path_helper` 反転** はセットで潜みやすい (= 古い install が `sudo npm install -g` で `/usr/local/bin` に落とされ、 `path_helper` がそこを先頭に置く → 新しい `~/.npm-global/bin/claude` が影に隠れる)。 install script の `[warn]` version mismatch を見たら両方 check。 また **virgin config dir では trust / consent / auth の 3 つが同時に欠けている** — install script の自動 seed が前 2 者を消すので、 残るのは OAuth 1 回のみ ([#ts-workspace-trust](#ts-workspace-trust))。

## セキュリティ

- 通信は**外向き HTTPS のみ** (Anthropic API 経由の polling)。inbound port は開かないので
  NAT / FW 配下でも動き、露出面の追加はほぼ無い。
- リモート生成セッションは通常のローカルセッションと同じ settings.json / hooks /
  permission mode に従う (= permission の絞りは settings 側で行う。
  `claude remote-control --permission-mode <mode>` で spawn 時の mode 指定も可)。
- スマホを持つ人 = あなたのマシンで Claude Code を動かせる人。端末ロックは前提。

## 相補機能

- `remoteControlAtStartup: true` (`~/.claude/settings.json`、machine-local): 手元で開いた
  **対話セッション全部**を自動でリモート続行可能にする。サーバーモード (= 何も開いて
  いなくても外から新規に生やす) とは役割が別で、併用が自然。

## <a id="multi-account-servers"></a>複数アカウント — 1 マシンに 2 サーバー

別アカウントの新規 session をスマホから選べるようにするには、 1 マシンで remote-control サーバーを**アカウントごとに 1 本**立てる。 認証ストアの分離は `CLAUDE_CONFIG_DIR` で行う (⚠️ アカウント × マシン × 端末の**運用全体像** = [multi-account-machine-surface.md](multi-account-machine-surface.md)、 本節はその I1 の機構):

⚠️ **推奨構成 = pinned per-account (全 server を suffix label + アカウント固定の config dir で立て、 既定 `~/.claude/` には載せない)**。 既定 dir の account は desktop / CLI の都合でいつでも切替わる**変数**なので、 そこに server を載せると account 切替のたびにそのマシンの mobile coverage が壊れる (実測: 既定 dir の account 切替で片方のセルが silent 消失)。 pinned dir 方式なら interactive OAuth は「マシン × アカウントごとに 1 回だけ」 で永続 — 以後は既定 dir の account をいくら切替えても coverage 不変 (再 auth が要るのは token 失効時のみ)。 base label (flag 無し install) は単一アカウント運用でのみ使う。

- `install-remote-control-server.sh --config-dir DIR --label-suffix SUF` で 2 本目以降を別 config dir + 別 launchd label で常駐 (= 既定サーバーと衝突しない)。 既定 (flag 無し) が 1 本目。 outbound polling なので 2 本同時起動でポート/ロック衝突なし。
- ⚠️ **`CLAUDE_CONFIG_DIR` は `~/.claude/` を丸ごと別 dir に分離する** (認証・`settings.json`・hooks・MCP・projects すべて)。 何もしないと 2 本目の名義 session は leak-guard 等の hooks を失う。 → 2 本目の config dir に `settings.json` を symlink で持ち込む (hook の command は `~/.claude/hooks/...` の絶対パスなので実体は共有先に解決される)。 MCP server は `.claude.json` 側で分離され別名義には付かない (= 安全性でなく機能差、 要れば別途その config dir で `claude mcp add`)。
- ⚠️⚠️ **OAuth はブラウザの現在 claude.ai アカウントを掴む** (= config dir を分けても、 `claude auth login` の認可画面が別アカウントでサインイン済だとそっちで認可されてしまう)。 2 本目を**別アカウントで認証するときは、 認可の瞬間にブラウザをその別アカウントに切り替える** (claude.ai のアカウントメニューで切替、 またはサインアウトして選び直す)。 認可後はブラウザを戻してよい (= 資格は config dir に保存される)。 必ず `CLAUDE_CONFIG_DIR=DIR claude auth status` で email を確認してから本番化する。
- スマホ側は **アプリのアカウント = 見える environment 群のスイッチ** (= odakin でサインインすると odakin 名義サーバーの environment が、 別名義でサインインすると別名義の environment が候補に出る)。

### <a id="account-auth-keychain"></a>auth の保存構造 — 「切替」 は config-dir の選択であって copy ではない

複数アカウント運用の設計を縛る基礎 fact (macOS、 2026-07-01 実測):

- **auth トークンは `.claude.json` でなく macOS keychain に保存される**。 keychain service 名は `Claude Code-credentials[-<hash>]` の形で、 `<hash>` は **config-dir の path から導出**される (= keychain namespace が config-dir 固有)。
- ゆえに **`.claude.json` を config-dir 間で copy しても auth は移動しない**: `oauthAccount` 欄 (email 等の metadata) だけが付いてきて `claude auth status` は `loggedIn: false` を返す = **metadata が嘘をつく状態**になる (copy はむしろ有害。 metadata だけ copy された dir は「email 表示 = login 済」 と誤読される)。
- config-dir に auth を確立する唯一の経路 = `CLAUDE_CONFIG_DIR=<dir> claude auth login` (browser OAuth、 新しい keychain entry を hash 付きで作成。 ⚠️ 上の browser 罠がここでも効く)。
- **∴ アカウント切替の正しい primitive は「どの config-dir を使うか」 の選択 = `CLAUDE_CONFIG_DIR` env var の切替**。 file 操作で account を「移す」 発想は成立しない。

運用面は 3 面が独立に切替可能:

| 面 | 切替 mechanism |
|---|---|
| CLI (ターミナル) | `CLAUDE_CONFIG_DIR` の export / unset (shell function 化すると快適) |
| desktop app | 起動プロセスの env なので shell からは届かない。 `launchctl setenv` + app 再起動 / `CLAUDE_CONFIG_DIR=<dir> open -na "Claude"` の単発起動 / 実用上は 1 つの primary 固定が楽 |
| mobile (remote-control) | 切替不要 — 本節の 2 サーバー構成なら**両アカウントの environment が常時見える** (アプリ側のアカウント切替だけで選ぶ) |
