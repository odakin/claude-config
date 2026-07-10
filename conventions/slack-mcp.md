<!-- doc-meta
when: Slack workspace を MCP で wire するとき
category: harness-core
summary: Slack workspace を user session token (xoxc/xoxd) で wire する規約（= admin 承認不要で一般 member として read+post、korotovsky/slack-mcp-server + wrapper で secret を config 外に逃がす + token 抽出手順〔Console `copy()` で xoxc / Application タブで xoxd cookie〕+ self-XSS「allow pasting」gate + clipboard 上書き/file名取り違え trap + post は SLACK_MCP_ADD_MESSAGE_TOOL=true で有効化・file upload tool は無く画像は user 手動 + reauth ~30日 + registration 介さず wrapper 直接 JSON-RPC invoke で当 session 使用。generic 機構のみ、workspace 固有値は個人層側）
-->
# Slack MCP を user session token で wire する

Slack workspace を Claude Code の MCP として繋ぐ規約。 **admin ではない一般 member** として参加している workspace を、 workspace admin の承認なしに read + post まで使えるようにする方法の SoT。

> **なぜ専用規約か**: Slack の公式 bot app (`xoxb-*`) は workspace admin の install 承認が要る (= 学会・省庁・他組織の workspace では数週間 + 却下リスク)。 一般 member が自分の browser session を再利用する `xoxc`/`xoxd` 方式なら admin 無関与で繋がる。 この方式は Slack ToS 上グレーだが個人利用の主流 OSS 実装 ([korotovsky/slack-mcp-server](https://github.com/korotovsky/slack-mcp-server) 等) の前提。 token 抽出・self-XSS gate・file upload の限界・reauth 等の gotcha を毎回踏むので規約化する。

odakin 環境の具体的な instantiation (= workspace 一覧・secret path・登録済 alias) は個人層 (layer 3) の Slack MCP config repo が持つ。 本 file は generic な機構のみ。

---

## <a id="server-choice"></a>0. server 選定 = korotovsky/slack-mcp-server

npm `slack-mcp-server` (= [korotovsky/slack-mcp-server](https://github.com/korotovsky/slack-mcp-server)、 MIT)。 stdio + SSE 両対応、 **xoxc/xoxd の user session token を受ける**設計 (= bot app 不要が売り)。

- runtime = `npx slack-mcp-server` (global install しない、 常に最新 patch を pull)
- 認証 = 環境変数 `SLACK_MCP_XOXC_TOKEN` + `SLACK_MCP_XOXD_TOKEN`
- post 有効化 = `SLACK_MCP_ADD_MESSAGE_TOOL=true` (未設定なら read-only、 [§4](#post-enable) 参照)

### 2 種類の token

| token | 出所 | 役割 |
|---|---|---|
| `xoxc-…` | browser の **Local Storage** (`localConfig_v2` 内の team ごとの `token`) | workspace client token |
| `xoxd-…` | browser の **Cookie** `d` (HttpOnly) の value | session cookie |

両方揃って初めて認証が通る (= xoxc だけ / xoxd だけでは無効)。

---

## <a id="wrapper-pattern"></a>1. wrapper script pattern (secret を config に literal で書かない)

MCP registration に token を直書きすると `~/.claude.json` に平文で焼き付く。 **thin wrapper script** に逃がす:

```sh
#!/usr/bin/env bash
# ~/.secrets/slack-<alias>-{xoxc,xoxd}.txt を env に export して npx を exec。
set -euo pipefail
SECRETS_DIR="${HOME}/.secrets"
XOXC_FILE="${SECRETS_DIR}/slack-<alias>-xoxc.txt"
XOXD_FILE="${SECRETS_DIR}/slack-<alias>-xoxd.txt"
for f in "$XOXC_FILE" "$XOXD_FILE"; do
    [[ -r "$f" ]] || { echo "[slack-mcp] missing secret: $f" >&2; exit 2; }
done
export SLACK_MCP_XOXC_TOKEN="$(tr -d '[:space:]' < "$XOXC_FILE")"
export SLACK_MCP_XOXD_TOKEN="$(tr -d '[:space:]' < "$XOXD_FILE")"
# post 有効化する時だけ: export SLACK_MCP_ADD_MESSAGE_TOOL=true
exec npx --yes slack-mcp-server "$@"
```

⚠️ **`tr -d '[:space:]'` で改行・空白を strip 必須** — token file に改行が混入すると認証が silent fail する。

⚠️ **npx の PATH**: nvm 経由の node は非対話 shell で PATH に載らないことがある。 wrapper に `command -v npx` fallback (絶対 path 候補列挙) を入れておく。

registration (= user scope、 gmail MCP 等と同じ scope):

```sh
claude mcp add-json --scope=user slack-<alias> '{
  "type": "stdio",
  "command": "/absolute/path/to/slack-mcp-<alias>.sh"
}'
```

token 空でも registration は通る (= wire だけ先に作れる、 その時 `claude mcp list` は `✘ Failed to connect` を返す = 正常)。

---

## <a id="token-extraction"></a>2. token 抽出手順 (browser DevTools、 user 手動)

**前提**: 対象 workspace に browser でログイン済 (例: `https://<subdomain>.slack.com/` を開いて sign in 済)。

### xoxc は Console で 1 行 (最速)

DevTools → **Console** タブ:

```js
copy(JSON.parse(localStorage.localConfig_v2).teams[Object.keys(JSON.parse(localStorage.localConfig_v2).teams)[0]].token)
```

出力は `undefined` だが副作用で `xoxc-…` が clipboard に入る (Chrome DevTools `copy()`)。 team が複数なら URL の `/client/<TEAM_ID>/` の TEAM_ID を key に指定。

⚠️ **self-XSS gate**: Slack は「ペーストするな」 警告を出す (= social-engineering 対策)。 Console に **キーボードで直接** `allow pasting` + Enter とタイプすると解除され、 以後 paste 可。

### xoxd は Application タブから手動 copy (HttpOnly ゆえ JS 不可)

DevTools → **Application** → **Storage** → **Cookies** → 対象 domain → name = **`d`** の row → Value 欄 (`xoxd-…`) をダブルクリックで全選択 → Cmd+C。

### secret file への保存 (chat に token を出さない)

Terminal 直打ちで (= chat 経由で literal を貼らせない、 [`secret-handoff.md`](secret-handoff.md) 準拠):

```sh
# clipboard に xoxc を入れた直後:
(umask 077; pbpaste > ~/.secrets/slack-<alias>-xoxc.txt) && head -c 8 ~/.secrets/slack-<alias>-xoxc.txt && echo
# 同様に xoxd:
(umask 077; pbpaste > ~/.secrets/slack-<alias>-xoxd.txt) && head -c 8 ~/.secrets/slack-<alias>-xoxd.txt && echo
```

`xoxc-…` / `xoxd-…` の先頭 8 文字だけ verify (= それ以上は transcript に残さない)。

⚠️ **clipboard 上書き trap (実発生)**: token を clipboard に入れた後、 **Terminal に貼る command 自体を copy すると token が上書きされる**。 順序は「browser で `copy()` → Terminal で `pbpaste`」 の 2 動作しか挟まない (= 途中で chat / URL / command を copy しない)。 up-arrow で直前 command を recall するのが安全。

⚠️ **file 名取り違え trap (実発生)**: xoxc を保存した command を up-arrow で recall して xoxd 用に流用する時、 **file 名の `xoxc`→`xoxd` 書換えを忘れると xoxc file が xoxd で上書きされる**。 各保存後に `head -c 8` で中身の prefix (`xoxc-` vs `xoxd-`) を必ず確認。

---

## <a id="activation"></a>3. activation (session 再起動が要る場合)

Claude Code (desktop) は **起動時に MCP config を load** するので、 registration 後の同 session では wire されない。 user が Claude Code を再起動すると次 session で `mcp__slack-<alias>__*` tools が使える。

⚠️ **再起動を待たずに今 session で使う裏道**: wrapper script は MCP registration とは独立に **直接 stdio で叩ける**。 JSON-RPC (`initialize` + `tools/call`) を stdin に流せば MCP を介さず同じ操作ができる (= registration は「次 session 以降の常用 wire」、 wrapper 直接 invoke は「今すぐ 1 回使う」 用)。 実装は [§7](#direct-invoke) 参照。

smoke test (= 認証確認):

```sh
printf '%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"1.0"}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | /path/to/slack-mcp-<alias>.sh 2>&1 | grep -o '"name":"[a-z_]*"' | head
```

stderr に `Authenticated to Slack ... team:<name>` が出れば認証成功。

---

## <a id="post-enable"></a>4. post 有効化と file upload の限界

- **read-only が default** (`SLACK_MCP_ADD_MESSAGE_TOOL` 未設定)。 `channels_list` / `conversations_history` / `conversations_search_messages` / `users_search` 等が使える
- **post するには wrapper で `export SLACK_MCP_ADD_MESSAGE_TOOL=true`** → `conversations_add_message` tool が生える (channel_id + text、 content_type = markdown/plain、 thread_ts で返信)
- ⚠️ **file / image upload tool は無い** — korotovsky server は ToS 配慮で `files.upload` を expose しない。 **画像添付は user 手動** (browser / app で drag & drop)。 text は MCP で post できるが image は人手、 という非対称を前提に段取りする
- ⚠️ post は外部発信 = **user 明示 OK 経由必須** ([mail-send 等と同じ autonomy 禁則](../CONVENTIONS.md))。 wrapper で post を有効化した後も、 実 post は user の explicit 指示を trigger にする

---

## <a id="verification"></a>5. 送信・添付の verify は conversations_history で

post や user の手動添付が反映されたかは `conversations_history` で channel を読み返す (= `files_list` 相当が無いので message の attachment ID で確認)。 CSV 行に `FileCount` / `AttachmentIDs` / `HasMedia` が出る。 添付差し替え後は attachment ID が変わるのを見て確認できる。

---

## <a id="reauth"></a>6. reauth (token 失効時)

Slack の session token は **~30 日で失効** (log-out / password 変更でも失効)。 症状 = MCP tool が `session expired` / `invalid_auth` 等で error。 → [§2](#token-extraction) を再実行して 2 file を再生成すれば復活。 **MCP registration は不変、 再起動も不要** (wrapper が起動毎に file を読む)。

---

## <a id="direct-invoke"></a>7. wrapper 直接 invoke (registration を介さず今 session で使う)

MCP registration は「次 session 以降の常用」。 今 session で 1 回操作したいだけなら wrapper に JSON-RPC を stdin から流す。 Python で init + 1 tool call を送って id=2 の応答を待つ薄い driver を書けばよい (= stdout を行ごとに parse、 `initialize` → `tools/call` の 2 メッセージ)。 post / history / search いずれもこの経路で叩ける。

origin: 2026-07-08〜09 の Slack MCP 初回 wire session (= admin でない workspace に自己紹介を post する必要が発生 → korotovsky server を xoxc/xoxd で wire → registration の再起動待ちを避けて wrapper 直接 invoke で当日 post を完遂)。 token 抽出中に踏んだ self-XSS gate / clipboard 上書き / file 名取り違えの 3 trap を [§2](#token-extraction) に焼いた。

## 関連

- MCP 一般則: [`mcp.md`](mcp.md)
- secret の運搬: [`secret-handoff.md`](secret-handoff.md) (chat に literal を貼らせない)
- browser cookie 抽出の限界 (= OAuth-token SPA では cookie replay が認証を carry しない): [`web-tools.md`](web-tools.md)
