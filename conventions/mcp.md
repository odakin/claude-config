# MCP 規約

MCP ツールを使うリポで適用。CLAUDE.md から参照: `~/Claude/claude-config/conventions/mcp.md`

> **関連**: MCP 経由で取得した外部 content (Gmail 本文・Discord メッセージ・Calendar event の title/description・ticket 本文等) に adversarial な指示文が混入していた場合の取扱は [prompt-injection.md](prompt-injection.md) を参照。

## 共通（CONVENTIONS.md §5.7 の手順詳細）

- **確認方法** (⚠️ 2026-06-20 訂正 — 現行 setup に `get_profile` / `gmail_get_profile` という **MCP tool は存在しない**、 旧 built-in connector の名残。 実在 tool ベースで確認する):
  - **gongrzhe standalone** (`mcp__gmail-<alias>__*`): **alias 名 = account** (1:1、 `~/.gmail-mcp/<alias>/`)。 runtime の identity tool は無いので alias 名が account の identity。
  - **Cowork UUID** (`mcp__<UUID>__*`): identity tool 無し。 自分発 mail を `search_threads`→`get_thread` で読んで From を確認 / desktop Connectors UI / user 確認 のいずれか。
  - **Calendar**: `list_calendars` の primary calendar id = 接続 account の email。
  - (script レベルの API `users().getProfile` は reauth.sh が account 検証に使うが、 session から呼べる MCP tool ではない)
- **複数 MCP がある場合**: セッションの deferred tools 一覧で同一サービスの MCP が何個あるか確認し、上記方法 (alias 名 / Calendar は list_calendars / Cowork は自分宛 mail 読み) で UUID→アカウントの対応を把握する
- **UUID→アカウント対応表は MCP 設定リポに保持**: 各 MCP 設定リポ (例: `gmail-mcp-config`) の CLAUDE.md または SESSION.md に UUID→アカウントの対応を記録する。memory には書かない (machine-local で cross-machine 不整合を招く。詳細: [docs/convention-design-principles.md §5](../docs/convention-design-principles.md))。新規セッションで対応表が不明・古ければ、上記方法で UUID→account を照合し、差分を MCP 設定リポに追記する
- **アカウント一覧の正本**: 各 MCP 設定リポの CLAUDE.md を参照（各プロジェクトリポの CLAUDE.md にはハードコードしない）

## `claude mcp` の project 解決ルール (注意)

`claude mcp add` / `claude mcp remove` の default scope は **local** = 「対象 Claude Code project 内の MCP 登録」(`~/.claude.json` の `projects[<path>].mcpServers` 配下)。"対象 project" は cwd ではなく **cwd から ancestor を辿って最初に見つかる `.claude/` を持つディレクトリ** で決まる (= claude CLI が project と認識するディレクトリ)。

セットアップ用の bash スクリプト等が、**自分自身のリポ内**から `claude mcp` を呼ぶと、登録先が想定外の project に入る:

- 期待: `~/Claude` project に gmail server を登録
- 実態: スクリプトが `~/Claude/gmail-mcp-config/` 配下から走り、`~/Claude/gmail-mcp-config/.claude/` を最寄り `.claude/` として resolve → 登録先が `gmail-mcp-config` project になる

回避策:

- スクリプト冒頭で target project に **明示的に `cd`** してから `claude mcp` を呼ぶ。target は引数 / 環境変数で受け取れるようにしておく (cwd 暗黙依存をなくす)
- あるいは `--scope user` で全 project 共通の user-level 登録にする (per-project 登録にしたい場合は不向き)

設置時 / 撤去時の冪等化 (`claude mcp remove "<name>" 2>/dev/null || true; claude mcp add ...`) は target project が正しいときに初めて意味を持つので、target 解決を先に固める。

## MCP 接続失敗時のセッション内復旧 (runbook)

session 中に MCP server が `Failed to connect` / `disconnected` 状態になったときの対応手順。**Claude Code の設計上、stdio MCP server は session 起動時に bind されており、起動時に接続失敗するとそのセッション内で再接続する built-in 経路がない** (上流既知 bug、GitHub claude-code issues #20684, #33468 参照)。HTTP/SSE 系は exponential backoff で auto-retry するが、stdio は手動。以下、軽い順に試す:

### 0. 状態確認

```bash
# 全 MCP の現状
claude mcp list           # ✓ Connected / ✗ Failed to connect

# 該当 server の詳細 (登録 args / env)
claude mcp get <server-name>
```

`claude mcp list` の "Connected" は **session 起動時の bind 結果**で、その後 server が落ちても更新されない場合がある。実際のツール呼び出しが通るかどうかが真の動作確認。

### 1. 該当 server を素手で立ち上げて handshake 通る確認

stdio server の場合、生 stdio で `initialize` リクエストを投げて応答するか確認:

```bash
echo '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}' | \
  env <NEEDED_ENV_VARS> node /path/to/server.mjs
```

応答に `"result":{"protocolVersion":...}` が返れば server 側は健全。問題は Claude Code の MCP daemon 側の cache。

#### handshake は「起動確認」 であって「依存検証」 ではない (= dependency bump 時の落とし穴)

`initialize` handshake が PASS しても、それは **server の boot + protocol negotiation** を確認したに過ぎない。多くの MCP server は API client (`googleapis` 等) を **lazy に構築する** (= 初回 `tools/call` まで未構築)。したがって、ある dependency が **tool handler の中でしか使われない** 場合、handshake では一切 exercise されず、**handshake PASS は「その依存が動く」 証明にならない**。

→ **major dependency bump (e.g. `googleapis` 171→173) を検証するなら、handshake では不十分。read-only な `tools/call` を投げて実 API round-trip まで確認する**:

```bash
# 1) initialize で result を受けたら 2) initialized 通知 → 3) read-only tool を call
#    {"jsonrpc":"2.0","method":"notifications/initialized"}
#    {"jsonrpc":"2.0","method":"tools/call","id":2,"params":{"name":"<read_only_tool>","arguments":{}}}
```

複数行 JSON を順に書く client は **`Write` で小さな node/python harness にして単純コマンドで起動**する (= inline の nested-quote JSON は tool call malformed を誘発、 [tool-call-robustness.md](tool-call-robustness.md) 参照)。staged verification 推奨: 1 dir だけ先に bump → bump 前と live 結果を比較 (同一なら回帰なし) → 全 dir 展開、で blast radius を最小化。

**OAuth-backed server を live test する時の副作用**: 実 `tools/call` は token refresh を誘発し、credential file が drift する (= ephemeral な `access_token` / `expiry_date` のみ、durable な `refresh_token` は標準的 refresh では rotate されない)。検証後は drift を `git checkout --` で破棄してよい (= 次回使用時に refresh_token から自動再 refresh)。git-crypt'd credential file の durable field が不変かを `git show <rev>:<path>` で diff 確認することは**できない** (= ciphertext が返る、[git-crypt-guide.ja.md トラブルシューティング](../docs/git-crypt-guide.ja.md) 参照) ので、OAuth refresh semantics に依拠する。

### 2. log を確認

```bash
ls -t ~/Library/Caches/claude-cli-nodejs/-Users-odakin-Claude/mcp-logs-<server>/ | head -3
cat ~/Library/Caches/claude-cli-nodejs/-Users-odakin-Claude/mcp-logs-<server>/$(ls -t ~/Library/Caches/claude-cli-nodejs/-Users-odakin-Claude/mcp-logs-<server>/ | head -1)
```

`Successfully connected` で終わっていれば session 起動時は OK だった = mid-session で落ちた。`timeout` / `stderr` で終わっていれば起動時失敗。

### 3. remove + re-add で再登録 (transient 失敗のリトライ誘発)

```bash
cd ~/Claude  # ★ ~/Claude project scope 必須
claude mcp remove <server-name> -s local
claude mcp add <server-name> \
  -e KEY1=VALUE1 -e KEY2=VALUE2 \
  -- <command> <args...>
```

env vars と args は `claude mcp get` で取った内容を再投入。再登録後、**少し待ってから (10-30s)** ToolSearch で当該 MCP の tool schema を取得し直す:

```
ToolSearch select:mcp__<server>__<tool>
```

実際に tool を呼んでみる。MCP daemon が新登録を pick up していれば動く。

### 4. `/mcp` slash command (status 確認のみ、reconnect ボタンなし)

Claude for Mac の Code タブで `/mcp` を打つと UI 一覧が出る。**stdio server の reconnect/restart アクションは無い** (上流バグ #33468 で feature request 中)。HTTP/SSE は auto-retry 進捗が見える。status 確認用途のみ。

### 5. `claude --resume` で session 再起動 (最終手段)

ステップ 0-4 で復旧しなければ:

```bash
# 1. Claude for Mac を Cmd+Q または Code タブを閉じる
# 2. 元の作業ディレクトリで:
cd ~/Claude/<project>
claude --resume
```

session の会話 / context / tool 許可は **保たれる**。MCP server だけ再起動から bind し直される。stdio server の起動時失敗が transient だったなら今度は通る。**ただし起動時失敗が決定論的 (env / 設定不備) なら何度試しても同じ** → 設定を直してから resume。

### 6. それでも動かない場合の根本原因別 checklist

- **環境変数の missing**: MCP server は Claude Code 起動時の minimal env を継承する。`$PATH` / `$NODE_OPTIONS` / カスタム credential path 等。`-e KEY=VALUE` で明示的に渡す
- **working directory**: stdio server は Claude Code の cwd を継承。絶対パスで file を参照する設計が安全
- **credential lock 競合**: OAuth token file を読む系の server が、別プロセス (Python script 等) と同時に lock を取りに行くと timeout。MCP 起動と batch script の同時実行を避ける
- **cold-start タイムアウト**: googleapis 等の重い import で 2-3 sec かかる。MCP daemon の timeout (30s) には収まるが、複数 server 同時起動で IO 競合があると押し出される。重い server は esbuild 等で single-file bundle を試す

### Chrome MCP (Claude in Chrome) の特殊事情

Chrome MCP は `claude mcp` 配下ではなく **Claude.app の Chrome extension 経由** で別経路。`claude mcp list` には出ない。復旧:

1. Chrome で `chrome://extensions/` → Claude 拡張のトグル OFF → ON で reload
2. または Chrome を quit + 再起動
3. 上記でダメなら Mac app (Claude.app) も quit + 再起動

### Chrome MCP で 認証 SPA を scrape できないケース

一部の Google SPA (= Classroom 等、 認証済 iframe 内に主要 content が描画される構成) は Chrome MCP context (= browser の Claude 拡張経由) で **完全に load しない**。 症状:

- `navigate` → URL は変わるが body innerText は ~75 chars (= top nav + 「ページを読み込んでいます…」 banner のみ)
- 数十秒待っても content frame の grid / button 群が render されない
- `read_page` accessibility tree に `progressbar "読み込んでいます…"` が永続表示
- `javascript_exec` で `document.querySelectorAll('iframe')` を probe すると `iframe.src` / `window.gapi` 等の sensitive accessor が **`[BLOCKED: Sensitive key]` / `[BLOCKED: Cookie/query string data]`** で blanked (= Chrome MCP の defensive feature、 cookie / OAuth state が embedded されている可能性のある属性は遮蔽)
- `window.location.reload()` / 更新 button click でも改善せず

### 対処 (= fallback path)

1. **user の主 browser で開いてもらう**: 通常の browser window (= MCP context 外) で同じ URL を開き、 user に手動で paste / 必要なら screenshot 投稿してもらう。 Chrome MCP の通常 page navigation は依然動くので、 別 tab に「scrape できる方」 と「できない方」 が共存可
2. **scrape できる類似 page を探す**: 該当 service に MCP / REST API があれば API ルートを優先 (= SPA の view が API で代替可能なら API 取得を選ぶ)

### 一般化 (= 他の認証 SPA でも起こりうる)

「Chrome MCP は scrape できる前提」 で workflow を組まない。 navigate 後に accessibility tree が `読み込んでいます` で凍る、 iframe internals が BLOCKED で取れない場合、 **その page を Chrome MCP で取れない**と判定して即 fallback (= user 手動 paste / API ルート)。 ループで waiting し続けて時間を溶かさない。

### 過去事例

- **2026-05-01**: classroom-cis (stdio) が session 中に disconnected。server.mjs 単独 stdio handshake は OK、log は `Successfully connected` で終わる (落ちた時刻のログなし)。`claude mcp remove + add` で再登録 → 数分後に ToolSearch + tool 呼び出し成功。Mac app は quit せず session 維持で復旧した sample。同時に gmail-* 4 server も system-reminder で disconnected と告知されたが、こちらは自動で再接続成功 (stdio でも `@gongrzhe` の MCP は graceful reconnect 機構を持つ模様)。Chrome MCP は別 incident で接続不可、Mac app 側の対応必要。
- **2026-05-19**: Classroom UI (= 課題提出者一覧の「ファイルを開いていない」 ラベル展開 view) を Chrome MCP で scrape 試行。 上記症状 (body 75 chars / progressbar 永続 / iframe BLOCKED) を観察、 ~1 min waiting で reload + 更新 button click でも改善せず。 fallback で user 主 browser からの paste 経由に切替えて解決。 一般化ルール (= 上記「対処」) を本 convention に組み入れ。

## MCP 設定リポの役割

MCP サーバーの認証情報やセットアップ手順を一箇所で管理するためのリポ。複数のプロジェクトが同じ MCP サーバー（Gmail、Calendar 等）を利用する場合、認証情報の管理を各プロジェクトに分散させると更新漏れや不整合が起きる。設定リポに集約することで、アカウント追加・トークン更新・サーバー移行等の変更が1箇所で完結する。

記録すべき内容:
- アカウント一覧と認証情報の保存場所
- MCP サーバーの選定理由（DESIGN.md）
- セットアップ・再認証の手順（スクリプト化推奨）
- OAuth スコープと制約
- 認証情報のバックアップ方針

MCP 設定リポは private にすること（認証情報のパスやアカウント構成を含むため）。認証情報そのものはリポ外（例: `~/.gmail-mcp/`）に置き、リポには構造とスクリプトだけを入れる。

---

## desktop Cowork session の `--allowedTools` 制限 (= 「登録済なのに使えない」 trap)

Claude desktop (Cowork) app から起動した Claude Code session は `--allowedTools` で **限られた tool list (= 6 個程度: `mcp__computer-use` / `mcp__ccd_session__*` / `mcp__ccd_session_mgmt__*`)** しか渡してこない。 `~/.claude.json` の `mcpServers` に `gmail-personal` / `calendar-cis` 等が登録されていても、 そのまま自動 spawn されず session 内で見えない。

= 「`~/.claude.json` 登録 ≠ session 内可用」 の構造ギャップ。 user が「Gmail MCP 設定してるはずなのに動かない」 と感じる典型 trap。

### 切り分け 3 step

1. **`ps -ef | grep -i "gmail\|mcp"`** で gmail-* MCP server process が走っているか確認。 0 件なら spawn されていない
2. **当該 session の親 process command を `ps -p <pid> -o command`** で確認。 `--allowedTools` の中身を見て gmail-* が含まれているか
3. **`~/.claude.json` の projects.<workdir>.mcpServers**  に登録があり、 spawn だけされてない (= allowedTools 由来) なら下記対処

### 対処 3 経路

| (a) | desktop Cowork に Gmail connector を追加 | desktop UI → Connectors → Gmail → OAuth で新規 wire。 `mcp__<UUID>__*` 形式で見えるようになる (= Cowork hosted 経路、 1 connector / 1 account) |
| (b) | Terminal から Claude Code を直起動 | desktop Cowork でなく `claude` コマンドを直接 launch → `~/.claude.json` 登録 MCP が allowedTools に含まれる起動になる (= 制限なし運用) |
| (c) | 本 session 内で OAuth token 直叩き Python | `~/.gmail-mcp/<account>/credentials.json` (= access_token + refresh_token) + `oauth-keys.json` (= client_id + client_secret) を Python で読み、 `oauth2.googleapis.com/token` で refresh → Gmail API 直叩き。 MCP layer 経由しない (= 当 session 内即効性ある) |

### harness 組み込み tool への波及 (= scheduled task 登録不可)

⚠️ この `--allowedTools` subset は MCP server だけでなく **harness 組み込み tool** も削る: bridge session (= `CLAUDE_CODE_ENVIRONMENT_KIND=bridge`) では `create_scheduled_task` / `update_scheduled_task` が wire されず (= `ToolSearch "select:create_scheduled_task"` が空)、 fallback の `CronCreate` も `durable: true` を渡して **session-only 化** する (= 永続 local scheduled task を登録できない、 2026-06-23 実証)。 → 定期 task の登録は Terminal 直起動 session (= 上記対処 (b)) に移って行う。 詳細は [scheduled-tasks.md §登録できる session 種別](scheduled-tasks.md)。

### 教訓 (= sweep skipping 防止)

「MCP 経由で取れた = 該当 account 全部見えた」 と判断するな。 **2026-06-20 layer-3 RCA**: 単一 Gmail account のみ wired の状態で人名 query 0 件を「Gmail で 0 件で確定」 と universalize、 4 回繰り返してから user の繰返 push で別 account に該当 thread が存在することが判明。 真因 = MCP tool metadata が wire account を expose しない構造ギャップ。 「該当 account が全部 session に bind されているか」 を**最初に**確認するのが正しい sweep の入口。 〔起票 commit (= 2026-06-20 prior version) は **incident 固有名・thread 内容を本節に literal で焼き込んでいた** = 自身が public layer 1 安全規則 §「2026-06-16 拡張」 を踏んだ leak。 該当 literal は 2026-06-20 cold-eyes session でこの commit で sanitize、 git history 側は不可逆〕

詳細 (= 固有名・transcript 内容含む incident 記録) = owner の personal layer (= layer 3、 collaborator は access 不要) に記録。

### 機械 enforcement (= 2026-06-20 RCA 後に追加、 soft guard を hard mechanism で強化)

上記「教訓」 は文字どおり読まれない場合の保険として、 以下 3 hook を `claude-config/hooks/` に投入済 (= setup.sh で全 machine の `~/.claude/hooks/` に symlink + settings.json 登録、 起源 = owner の personal layer の設計 plan (2026-06-20、 collaborator access 不要)):

| hook | phase | matcher | 役割 |
|---|---|---|---|
| [`mcp-search-scope-reminder-nudge.sh`](../hooks/mcp-search-scope-reminder-nudge.sh) | PreToolUse | `mcp__.*__(search_threads\|search_emails\|list_messages\|list_threads\|search_threads_by\|list_events)` | search 系 tool 呼び出し直前に scope universalization trap の reminder + fill-in template (= `Verified scope = ___ / NOT verified = ___`) を inject |
| [`mcp-search-zero-result-nudge.sh`](../hooks/mcp-search-zero-result-nudge.sh) | PostToolUse | 同上 | 0 件結果 (= `No threads found` / `"messages": []` / `Found 0` / `resultSizeEstimate: 0` 等の明確 marker) を検出した直後に強 reminder + 「universal claim 禁止 list (= 「Gmail で 0 件」 「Mac Mail 全 sweep 0 件で確定」 等)」 を inject |
| [`session-start-mcp-scope-nudge.sh`](../hooks/session-start-mcp-scope-nudge.sh) | SessionStart | (matcher なし) | session 起動時に `~/.gmail-mcp/` + `claude_desktop_config.json` から register 済 account を列挙、 「register 済 ≠ session-active subset」 caveat 込みで anchor として inject |

3 hook とも `-nudge` suffix (= 非 block、 informational only)、 出力経路は `additionalContext` JSON + `~/.claude/surface/*.txt` の 2 段 defensive (= CLI session は前者、 desktop Cowork session は後者、 [hook-authoring.md §9.3](hook-authoring.md) 「desktop は hook を実行はするが出力を honor しない」)。 配線は `claude-config/setup.sh install_hooks` で全自動、 各 hook 直下に `*.test.sh` (= logic test §A + 起票 transcript の retroactive selftest §B) 同梱。

⚠️ 二次 trap 自覚: hook も「reminder を読み飛ばす Claude」 の前で必ず機能する保証はない (= 起票 session author confession)。 多層化 (= 3 hook 並走 + ToolSearch enumeration + user 側 wire 拡張 = Cowork connector に personal Gmail 追加、 plan §blocker (4)) でリスク低減を狙う。 効果検証は live invoke (= §9.1 build-dependent: 新規 hook は同 session 非発火、 次 session で観察) が必要、 数回の Gmail-search session で「scope-template が実際に埋められるか」 を観察 → false negative 多発なら escalate (= `permissionDecision: ask` 化、 hook-authoring §6.3)。 **2026-06-20 post-ship 観察 (n=1)**: 別 session で同 trap 構造 (= Cowork に write tool 不在) を踏みかけたが、 SessionStart capability anchor + 人読 manifest 経由で attempt 前に fallback (= `account-direct.py` Python wrapper) へ routing し完遂、 stuck-state 回避を 1 件で観察。 ⚠️ n=1 の一般化禁止 (= `work-discipline.md §A` 「一度の観察を一般法則化しない」 遵守)、 同型 case の複数 session 再現で仮説支持強化、 逆 case で escalation 検討。

### MCP tool scope manifest (= 人読 reference、 hook の動的 enumeration を補完)

hook C は session 起動時に filesystem + desktop config から register 済 tool を動的に列挙するが、 hook 出力に出ない時 (= silent fail / desktop frontend で surface 経由) や hook が読まれない時のために、 **「どの tool prefix がどの scope に対応するか」 の人読 manifest** を以下に置く。 owner の personal layer の MCP-scope reflex (= 「MCP tool / 外部 search の null」 行) がこの節を pointer 参照する (= reflex の機械補強欄、 personal layer は collaborator access 不要)。

⚠️ leak 規律: 本節は public layer 1 ゆえ **特定 account の email literal は書かない** (= 「odakin@<domain>」 等の literal は禁止、 alias 名と filesystem location までで止める。 詳細 = [`claude-config/CLAUDE.md §「安全規則 (公開リポ)」 + §「2026-06-16 拡張」`](../CLAUDE.md))。

| tool prefix pattern | wire scope (= 何が見えるか) | account 推定の起点 |
|---|---|---|
| `mcp__gmail-<alias>__*` (= gongrzhe `@gongrzhe/server-gmail-autoauth-mcp`) | **1 account / 1 alias** (= alias と Gmail account の 1:1 対応、 「register 済 ≠ session-active」 は SessionStart hook で確認) | **alias 名 = account** (= `~/.gmail-mcp/<alias>/credentials.json`)。 ⚠️ gongrzhe server に `get_profile` MCP tool は無い (= account 検証は reauth.sh が API `getProfile` を script で叩く、 session の MCP tool ではない) |
| `mcp__<UUID>__*` (= Cowork hosted connector、 UUID 形式) | **1 connector / 1 account**、 ただし **UUID から account を filesystem 由来で推定不可** (= Cowork app 内部の wiring) | identity MCP tool 無し。 account を知るには 自分発 mail を `search_threads`→`get_thread` で読んで From 確認 / desktop Connectors UI / user 確認 |
| `mcp__calendar-<alias>__*` (= 個別 Google Calendar MCP) | 1 alias の Google account / 紐付く全 calendar (= 個人 + 共有) | `~/Library/Application Support/Claude/claude_desktop_config.json` の `mcpServers.<alias>` |
| `mcp__filesystem__*` | desktop config で許可された path tree (= 全 file が見えるわけではない) | `claude_desktop_config.json` の filesystem entry の path 引数 |
| `mcp__computer-use__*` | macOS GUI + user 承認した application のみ | `list_granted_applications` で session 中の許可 list を確認 |

**capability profile (= read scope と write scope は別軸、 2026-06-20 write-tool RCA)**: 上記表は「どの account / data が見えるか」 の scope。 別軸として「その tool で何が**できるか**」 (= capability) があり、 特に **Gmail は connector type で send capability が分かれる**:

| connector type | read | draft 作成 + label | send / delete / modify |
|---|---|---|---|
| Cowork hosted (`mcp__<UUID>__*`) | ✅ `search_threads` / `get_thread` | ✅ `create_draft` / `label_*` / `create_label` | ❌ **expose しない** (= `send_email` / `delete_email` / `modify_email` 不在) |
| standalone gongrzhe (`mcp__gmail-<alias>__*`) | ✅ `search_emails` / `read_email` | ✅ `draft_email` | ✅ `send_email` / `delete_email` / `modify_email` / `batch_*` |

⚠️ **tool 名に send verb が「無い」 = 「送信不能」 ではない**: Cowork connector は **「read-only」 ではなく「send 不可」 が正確** (= draft / label は書ける、 send だけ出さない)。 capability は connector type で決まり、 同 account でも別 connector type が send を出すので、 Cowork connector に `send_email` が無いのを見て「メール送信できない」 と即断しない。 send したい時 = (a) standalone `mcp__gmail-<alias>__send_email` の wire を ToolSearch で確認 → (b) なければ `account-direct.py` (= 上記「対処 3 経路」 (c) の Python wrapper) → (c) それも無理なら user に手動送信を依頼。 wire-*account* は UUID から推定不可だが、 **capability *TYPE* は name pattern (= UUID vs alias) で確実に判別できる** (= 静的推論可能、 これが account 軸との非対称性)。 起票 = 2026-06-20 write-tool RCA (= Cowork-only session で send_email 不在を観察、 詳細は owner の personal layer の設計 plan、 collaborator access 不要)。

⚠️ **session-active subset の verify は manifest だけでは不能** = 上記は **machine 上 register 済の universe** であって、 session で実際 wire されている subset は別。 desktop Cowork session は `--allowedTools` で大幅に subset される (= 上記 §「desktop Cowork session の `--allowedTools` 制限」)。 session 内 verify = (a) ToolSearch で `mcp__` 接頭辞 query して deferred tool list を取得 / (b) wire account の確認は上記 §「MCP tool scope manifest」 表の「account 推定の起点」 列に従う (= gmail alias は alias 名、 Cowork は自分宛 mail 読み、 Calendar は `list_calendars`)。 ⚠️ `get_profile` / `whoami` という MCP tool は現行 setup に**存在しない** (= 旧 built-in connector の名残、 §共通「確認方法」 参照)。

**起票 incident** (2026-06-20、 詳細 = 個人層 plan): Cowork desktop session で Cowork connector (`mcp__<UUID>__*`) 1 個のみ wired、 他の複数 Gmail account (`mcp__gmail-<alias>__*` 群) は register 済だが session subset 外 → search で「該当無し」 を universalize → 4 回 push 後に Python wrapper (= account-direct.py、 上記「対処 3 経路」 (c)) で別 account に到達。 = **manifest を session 冒頭で「machine 上 register vs session-active」 の差分として読まないと、 同 trap が再演する** (= hook C が surface する役)。

### scope manifest と reflex の関係 (= 重複防止の整理、 起票 plan = `2026-06-20-tool-scope-verification-reflex.md`)

scope-related artifact 3 つの責務分離:

| layer | artifact | 役割 |
|---|---|---|
| 機構 (hook) | 上記「機械 enforcement」 の 3 hook | 自動 inject + 0 件結果 trap |
| 人読 reference (= 本節) | 「MCP tool scope manifest」 表 | tool prefix → scope の type system 的 documentation |
| 個人層 discipline | owner の personal layer reflex (= 「MCP tool / 外部 search の null」 行、 collaborator access 不要) | reflex (= 0 件 → universalize 前の self-question) + 機構 + 本節への routing |

= **同じ事実を 3 場所に書かない**: hook の reminder 内容 / 本節の manifest / inline reflex の文言、 それぞれ責務が異なる layer なので一見重複に見えても各 layer の観客 (= 機構 / 人読知識 / Claude reflex) に対する用途が違う。 drift 防止は inline reflex の機械補強欄が「mcp.md §機械 enforcement + §MCP tool scope manifest」 を pointer 参照することで吸収 (= manifest 変更時に inline は触らなくて良い)。

**capability 軸 (= write/send tool 不在 trap、 2026-06-20 write-tool RCA) も同 3 layer pattern**: 機構 = `session-start-mcp-scope-nudge.sh §4b` の write/send capability block / 人読 = 上記「capability profile」 表 / inline reflex = owner の personal layer reflex (= 「MCP tool / 外部 search の null」 行) の capability-absence 句。 read scope の null 軸とは別 trap (= 「0 件 → universal absence」 でなく「verb 不在 → 操作不能」 の誤推論) だが、 上流 trait は同一 (= **tool 名は何が含まれ・何ができるかの hint であって guarantee ではない**)。 起票 = owner の personal layer の設計 plan (collaborator access 不要)。

---

## MCP で不十分な場合: API 直接アクセス

MCP ツールは個別操作に最適だが、バッチ操作（一括削除・ラベル付け・統計取得等）には向かない。Gmail MCP の `modify_email` は1件ずつだが、Gmail API の `batchModify` は1回で最大1000件を処理できる。

**基本的な考え方:** MCP サーバーが OAuth 認証情報をローカルに保持しているなら、同じ認証情報を Python（`google-api-python-client`）から直接利用できる。新規に OAuth フローを構築する必要はない。

### 使い分けの基準

| 操作 | 手段 | 理由 |
|---|---|---|
| メール1件の読み取り・返信 | MCP | 対話的操作に最適、Claude が直接呼べる |
| 一括操作（削除、ラベル付け等） | Python + API | `batchModify`/`batchDelete` で最大1000件/回 |
| 統計・分析（件数、容量等） | Python + API | `messages.list` + 集計が柔軟 |
| フィルター管理 | Python + API | MCP にフィルター API がない |
| 確実な thread continuity (`In-Reply-To` 付きの返信送信) | Python + API | 多くの Gmail MCP 実装は `read_email` の戻り値に `Message-ID` ヘッダを含めないため、MCP 単独で `inReplyTo` パラメータを組み立てられない。`messages.get(format='full')` で全 headers 取得 → `Message-ID` 抽出 → 送信側に渡す経路が必要 (個別実装ごとの実機検証は MCP 設定リポの DESIGN.md に記録) |
| `to` パラメータが array で詰まる場合 | Python + API | 2026-05 `@gongrzhe/server-gmail-autoauth-mcp` v1.1.11 の send_email で、 schema は `to: array` だが harness が JSON array を string と誤って serialize し `invalid_type: expected array, received string` を返す事例あり。 文字列 1 個でも array でも fail。 同一 MCP の他ツール (`search_emails` 等) は影響なし。 fallback として Python Gmail API 直接送信を使う (= `~/.gmail-mcp/{account}/credentials.json` + `gcp-oauth.keys.json` を read して `Credentials` 構築 → `service.users().messages().send`)。 詳細実装例: ある grant 申請 repo の specific 助成事業 dir 内の Python 送信 script (= MCP fallback として `service.users().messages().send` を直接呼ぶ pattern) |
| Google Sheets / Drive 上のスプレッドシート読み | Python + API | MCP server がないため Python 直接が筋。 `mimeType` で分岐: `application/vnd.google-apps.spreadsheet` (Sheets native) → Sheets API、 `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` (xlsx upload) → Drive API で `get_media` + `openpyxl` で parse。 詳細パターンは `conventions/google-api-direct-access.md` |
| Google Calendar の bulk update (recurring 時限シフト等) | Python + API | MCP の `update_event` は 1 件ずつ。 expansion 後の instance を patch する系は API 直接が筋 |

### スコープに注意

MCP サーバーが取得した OAuth トークンのスコープによって使える API が異なる:

- `gmail.modify`: `batchModify`（ラベル操作・ゴミ箱移動）は可。`batchDelete`（永久削除）は不可
- `mail.google.com`: 全 API が利用可能（フルアクセス）

スコープが足りない場合は GCP コンソールで OAuth 同意画面を更新し再認証が必要。

### 実装時の注意

- Python スクリプトがトークンを refresh した場合、access_token だけでなく **refresh_token も書き戻す**。Google が refresh_token を回転させた場合に旧トークンだけがファイルに残ると、MCP サーバーも Python スクリプトも認証不能になる
- MCP サーバーと Python スクリプトの同時実行は避ける（token refresh の競合リスク）

各ユーザーの具体的な実装（認証情報のパス、スクリプト等）は MCP 設定リポの DESIGN.md に記録すること。

## Google API で create された resource の UI 制約 (third-party tool 制限)

Google API 経由で create された Calendar event / Classroom coursework / Drive file 等の resource は、 Google 側で「third-party tool 由来」 として永続フラグされる場合があり、 **UI 上の一部 toggle / 操作が disable される**ことがある。 これは API ルートで完全に同等な resource を作れないことを意味し、 「UI で create された state を完全再現したい」 use case では UI 経由でしか達成できない。

### 観測された具体例

- **Classroom courseWork**: API 経由で create されたものは `associatedWithDeveloper: true` が永続的に付与され、 UI で「サードパーティ製ツールからの提出は締め切ることができません」 message が表示されて 「期限後に提出を締め切る」 toggle がグレーアウト。 これは creation state (DRAFT / PUBLISHED) を問わず適用、 つまり「DRAFT で API create → UI で toggle flip + publish」 ワークフローでも回避不能 (= API ルート完全 close)。 「生徒はクラスメイトに返信できます」 toggle も同制限の対象と推定 (要 UI 検証、 Google が公開 schema に expose していない UI 専用 toggle 全般が同制限を受ける可能性)
- **Calendar event**: API 経由で create された event は creator の application name が UI に表示される。 一部 advanced settings (recurring rule の細部、 visibility 等) で制限を受ける場合あり (Calendar API は比較的緩い)
- **Drive file**: API 経由で upload された file は「<App name> から作成」 が表示される。 ファイル type 変換 / format 制限が一部働く

### 検出と回避

実装時に判別する手段:
1. **Discovery doc** (`https://<service>.googleapis.com/$discovery/rest?version=v1`) を取得して resource schema 全 field を確認 → UI 上 toggle に対応する field が無ければ **API では set 不可**
2. **Experimental に予想 field 名を投稿** → reject されれば確認 (rare に "silently ignored" もあるので read で echo back されるか確認も)
3. **API で create した resource を UI で開いて toggle / 操作の有効性を確認** → グレーアウト されれば third-party tool 制限あり

回避策:
- UI 完全制御が必要な resource は **UI で create する**経路を残す (= 利用者個別の運用ルールは MCP 設定リポ側の docs / SESSION.md に記録)
- API ルートは**制約を受けても困らない use case** で活用 (e.g., 期限後 late submission を accept する運用、 配点付き ASSIGNMENT、 内部試行 / DRAFT prototype、 batch 投稿)

### 経緯 (本 section 追加の契機)

2026-05-09 Classroom MCP の `classroom_create_coursework` ツール (= `courses.courseWork.create`
を wrap、 SHORT_ANSWER_QUESTION 対応) を実運用に投入する dogfood 段階で、 **API ルートで
「期限後に提出を締め切る」 toggle を ON にできない**ことが判明。 第一段では Discovery
doc + 8 field name experimental 投稿で API field 不存在を確認、 第二段では DRAFT で
create + UI で開く検証で associatedWithDeveloper 永続フラグによる UI grayout も確認
→ API ルート完全 close。 詳細・メタ教訓は owner の private layer (= gmail-mcp 運用記録 + personal layer、 collaborator access 不要) に記録。

## Google Calendar MCP
- 操作前にカレンダー一覧で対象カレンダーが正しいことを確認
- 共有カレンダー命名: `{共同研究者名}{自分の名字}共同研究`
- イベント作成時は日時・タイトル・参加者をユーザーに確認してから作成

## Gmail 本文の plain-text / HTML 二重表現 (= 読み「空」誤認 + 書き HTML entity)

メール本文は **plain-text 表現と HTML 表現の 2 つ**を持ちうる (multipart/alternative)。**HTML-only のメール** (= text/plain パートを持たない。HTML メーラ + S/MIME 署名や一部の通知系で起きる) を素朴に扱うと**読み・書きの両方向で事故る**。両者は同じ「plain-text と HTML を取り違える」混同の表裏。

### 読み側: 「text/plain が無い」 ≠ 「本文が空」

- **text/plain だけを抽出する body extractor は、HTML-only メールに対して無音で空文字列を返す**。読み手はそれを「本文空」と誤読する (= 単一の表現〔text/plain〕の null を「本文不在」に飛躍させる失敗。安価な検証を先に回す原則の email-body 形態)。実際には HTML パートに実質的な本文が入っている。
- 標準の `read_email` (= `@gongrzhe/server-gmail-autoauth-mcp`) は `body = text || html` で **HTML に fallback** し `[Note: This email is HTML-formatted. Plain text version not available.]` を付けるので「空」を出さない。**だが自作の直読 helper / Python snippet で `mimeType == "text/plain"` だけ拾う実装は空を返す** (= ここが事故源)。
- **reflex**: メール本文が「空」に見えたら結論する前に、それが**表現の artifact でなく本当の空**かを 1 操作で verify する — (1) `format=full` で text/html パートを見る、または (2) 標準 `read_email` で読み直す。
- body extractor を自作するなら **text/plain 不在時は text/html に fallback** し (de-tag + 「HTML-only」 marker)、空を返すのは plain も html も無い時だけにする (= 標準 MCP と同じ契約)。空文字列を「本文空」の意味で出さない。

### 書き側: send_email の body は plain text — HTML entity を書かない

- MCP / API の send は body を plain text として MIME に詰めるだけで HTML entity を**decode しない**。`<` を `&lt;`・`>` を `&gt;`・`&` を `&amp;` と (XML/JSON escape の reflex で) 書くと、**受信側に literal `&gt;` がそのまま表示**される。返信の引用行 `> 元本文` で特に起きやすい。
- `<` `>` `&` は **literal で書く**。「XML/JSON 内だから escape が要る」と感じたら危険サイン (= 実際には plain text を渡している)。

### 機械化の射程 (= honest、effective な層だけに置く)

- **読み側**は body extractor のコードで根治できる (= 自作 helper を text/html fallback にする)。これは tool が返す値そのものを直すので **hook 不要・どの frontend でも効く** (= Cowork desktop でも有効)。最も leverage が高い。
- **書き側は本質的に機械化が難しい**。PreToolUse hook で send body を scan する手はあるが、**Cowork desktop では hook 出力が honor されない** ([hook-authoring.md §9.3](hook-authoring.md))ため、まさに事故が起きる環境で無効 = 足しても「対策済」の false confidence にしかならない。送信が Bash script (= 直叩き wrapper) 経由なら script 内に entity の事前 scan を仕込めば**その経路では**機械的に止まる (frontend 非依存)。だが **MCP send 経路 (`mcp__gmail-*__send_email`) は介入できない**。∴ MCP-send-in-desktop の `&gt;` は **prose 規律 + human review が最後の floor**。欠陥自体は cosmetic (引用が崩れて見えるだけで趣旨は伝わる) なので、効かない機械層を積むより honest にそう書く。

## Gmail send: 添付ファイルは明示 MIME が要る

send (= MCP `send_email` / Gmail API `messages/send`) に file を添付するには、 plain-text body をセットするだけでは**付かない**。 multipart MIME を組んで file パートを足す要がある: stdlib なら `EmailMessage.set_content(body)` の後に `msg.add_attachment(data, maintype=…, subtype=…, filename=…)` (= MIME type は拡張子から `mimetypes.guess_type` で推定)、 それを `base64.urlsafe_b64encode(msg.as_bytes())` して `messages/send` の `raw` に渡す。

- **body だけ受ける send helper / thin wrapper は body しか送らない** (= 添付フィールドを持たない)。 添付が要るなら API 直叩きで raw MIME を自前で組む経路に切り替える (= `send_email` MCP tool が添付 param を出すかは server / version 依存、 確実なのは raw MIME)。
- **送信前に添付パスの存在を atomic に検証**する (= 1 つでも欠けたら batch 全体を abort)。 §書き側 の HTML-entity gate と同様、 部分送信してから気付く事故を防ぐ。

## Gmail MCP: read_email の大容量出力と chunked 処理

### 現象

`gmail_read_email` / `mcp__gmail-multi__read_email` は HTML-rich なメール（Substack newsletter、他の通知系メール等）で **70〜200 KB の出力**を返す。このサイズは Claude のメインコンテキスト token limit を超えるため、戻り値が error 風のメッセージ + 以下のようなファイルパスになる:

```
Error: result (XX,XXX characters) exceeds maximum allowed tokens.
Output has been saved to /Users/{user}/.claude/projects/{proj-id}/tool-results/mcp-gmail-multi-read_email-{timestamp}.txt
Format: JSON array with schema: [{type: string, text: string}]
```

ファイルには JSON `[{type:"text", text:"..."}]` 形式で、`text` フィールドに email 本文の HTML マルチパート（ときに base64 urlsafe エンコード）が入っている。

### 戦略

1. **メインコンテキストで中身を見たい場合**: 諦める。サイズが常に limit を超える
2. **内容を処理して構造化したい場合**: subagent に委譲。ファイルパスを渡して「Read tool で offset/limit を使って chunk ごとに読み切れ（limit=2000 行推奨）」と**明示する**
3. **複数メールを一括処理したい場合**:
   - メインから `read_email` を**並列で 4〜8 件**発火する
   - 全件 error 応答になるが、error メッセージの中のファイルパスは有効
   - パスのリストを subagent に渡して一括処理させる

### 並列化の注意

- Subagent の**4 並列**起動は 529 Overloaded エラーが頻発する。**3 並列まで**が安全圏
- 失敗した subagent は SendMessage で継続ではなく新規スポーンでリトライする方が確実
- `read_email` 自体の並列（MCP tool call の並列）は 8 件並列まで問題なく動く

### 典型的な処理パターン

```
1. gmail search → message id のリスト取得（メインで完結）
2. メインから read_email を 4-8 件並列発火 → ファイルパスのリスト取得
3. 残りがあれば 2 をもう一度
4. subagent 2-3 本を並列起動、各 subagent に (a) ファイルパスのサブセット
   (b) 抽出ルール (c) 出力先ファイルパス を渡す
5. subagent が各ファイルを Read で chunk ごとに最後まで読み、抽出結果を
   markdown として出力先に Write する
6. メインはファイルパスのみ確認し、必要なら merge
```

### Subagent への指示で忘れやすい点

- **「最後まで読み切れ」と明示する**。default では subagent は最初の chunk だけで判断しがち
- **著作権ガード**: 第三者の著作物（記事本体、他者のコメント本文）を引用しないことを明示する
- **529 時の再試行**: 「少し待ってから再試行」を明示的に指示しないと諦めて終わる
- **完了報告の形式指定**: 「何を抽出できたか (verbatim を除く) を 1 行ずつ報告せよ。要約不要」と書く。書かないと長文要約が返ってきてメインのコンテキストを食う

### Substack 通知メール固有の注意

Substack の `reaction@mg1` / `forum@mg1` 通知メールからユーザーのコメント本文を取得する際の構造的な制約（forum 通知には parent コメントが含まれない等）は → `substack.md` の「取得」セクション参照
