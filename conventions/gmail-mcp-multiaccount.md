<!-- doc-meta
when: 複数 Gmail アカウントを Claude Code の MCP として繋ぎたいとき + N 個目のアカウントを追加するとき
category: integration
summary: 多アカウント Gmail MCP の end-to-end runbook — @gongrzhe server を account 数ぶん起動 (1:1)、credential は git-crypt な private repo を canonical に symlink 運用 (1 回認証で全マシン)、reauth / runtime-links は templates/gmail-mcp/ の実証済 script、送信は ask gate 必須
-->

# 多アカウント Gmail MCP (multi-account runbook)

複数の Gmail アカウント (個人 / 職場 / 共有 / 用途別) を Claude Code から読み書きする
ための end-to-end 手順。**アーキテクチャ = `@gongrzhe/server-gmail-autoauth-mcp` を
アカウント数ぶん起動する 1:1 構成** (server × account)。upstream README は単アカウント
まで — 本 doc は多アカウント + 全マシン配布 + 送信ガードの家風一式。

## 構成

```
<your-private-config-repo>/            # private + git-crypt (メール・token を含むため)
├── accounts.yaml                      # alias → email の一覧 (git-crypt。script が実行時に読む)
├── reauth.sh                          # OAuth (再)認証 (templates/gmail-mcp/ から copy)
├── install-runtime-links.sh           # symlink 張り (同上)
└── secrets/                           # 🔒 git-crypt (.gitattributes: secrets/** filter=git-crypt)
    ├── gmail-<alias>-credentials.json # OAuth token (canonical、アカウント毎)
    └── gmail-gcp-oauth.keys.json      # OAuth client keys (全アカウント共有)

~/.gmail-mcp/<alias>/credentials.json      → repo canonical への symlink
~/.gmail-mcp/<alias>/gcp-oauth.keys.json   → 同上 (client keys)

~/.claude.json の projects[<cwd>].mcpServers:
  "gmail-<alias>": { "command": "npx", "args": ["@gongrzhe/server-gmail-autoauth-mcp"],
                     "env": { "GMAIL_CREDENTIALS_PATH": "~/.gmail-mcp/<alias>/credentials.json" } }
```

設計の要点 3 つ:

1. **credential の canonical は repo (git-crypt)、runtime は symlink** — 1 回認証すれば
   clone + unlock + `install-runtime-links.sh` だけで全マシンが認証済みになる。
2. **永続化するのは `refresh_token` だけ** (= Google は rotate しない)。`access_token` /
   `expiry_date` は各プロセスが in-memory refresh するので書き戻さない —
   書き戻すと repo が常時 dirty + マシン間 conflict になる。
3. **script は平文で commit できる**: メールアドレスは script にハードコードせず、
   実行時に git-crypt な accounts.yaml から読む (unlock されていなければ検証 skip)。

## 初期 setup (1 回だけ)

1. **GCP**: project 作成 → Gmail API を enable → OAuth client (アプリの種類 =
   デスクトップ) 作成 → `gcp-oauth.keys.json` として保存。consent screen が
   テストモードの場合、**繋ぐ Google アカウントを全部テストユーザーに登録**。
2. **private repo**: 上の構成で作成 (git-crypt 有効化、`secrets/** filter=git-crypt`)。
   [`templates/gmail-mcp/`](../templates/gmail-mcp/) の 3 file を copy
   (`accounts.yaml.example` → `accounts.yaml` に自分の alias/email)。
3. `~/.gmail-mcp/reauth.sh` → repo の reauth.sh へ symlink。

## アカウント追加 checklist (N 個目、~10 分)

1. `accounts.yaml` に `{alias, email}` entry を追加
2. `mkdir ~/.gmail-mcp/<alias>` + symlink 2 本 (credentials.json は canonical 未作成でも
   dangling symlink で OK — reauth が symlink 越しに canonical を作る):
   `ln -s <repo>/secrets/gmail-gcp-oauth.keys.json ~/.gmail-mcp/<alias>/gcp-oauth.keys.json`
   `ln -s <repo>/secrets/gmail-<alias>-credentials.json ~/.gmail-mcp/<alias>/credentials.json`
3. `~/.gmail-mcp/reauth.sh <alias>` → ブラウザで**当該アカウントとして**承認
   (script が login_hint 事前選択 + 認証後に getProfile で account 一致を検証、
   不一致なら token を自動破棄 — アカウント選び間違いは silent に通らない)
4. `~/.claude.json` に `gmail-<alias>` entry (上の形の copy)。**次 session 起動から bind**
5. **送信 gate**: `~/.claude/settings.json` の `permissions.ask` に
   `mcp__gmail-<alias>__send_email` を追加 (設計 =
   [`gmail-sending.md#double-confirmation-design`](gmail-sending.md#double-confirmation-design))
6. repo を commit + push (= 他マシンへ token 配布)

## 運用

- **`invalid_grant`** (token 失効) → `~/.gmail-mcp/reauth.sh <alias>` → commit + push
- **新マシン** → clone + `git-crypt unlock` + `install-runtime-links.sh` (再認証不要)
- MCP に無い操作 (添付 byte 列・batch 削除等) は同じ credential で Gmail REST API を
  Python から直叩き ([`google-api-direct-access.md`](google-api-direct-access.md))

実例 instance: 所有者の `gmail-mcp-config` (private) が 6 アカウントでこの構成を運用
(collaborator はアクセス不要 — 本 doc + templates だけで独立に構築できる)。
