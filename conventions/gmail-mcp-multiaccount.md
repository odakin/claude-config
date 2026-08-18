<!-- doc-meta
when: 複数 Gmail アカウントを Claude Code の MCP として繋ぎたいとき + N 個目のアカウントを追加するとき
category: mail
summary: 多アカウント Gmail MCP の end-to-end runbook — @gongrzhe server を account 数ぶん起動 (1:1)、credential は git-crypt な private repo を canonical に symlink 運用 (1 回認証で全マシン)、reauth / runtime-links エンジンは scripts/gmail-mcp-*.sh (state+PKCE / alias 検証 / permission 矯正込み)、送信は ask gate 必須
-->

# 多アカウント Gmail MCP (multi-account runbook)

複数の Gmail アカウント (個人 / 職場 / 共有 / 用途別) を Claude Code から読み書きする
ための end-to-end 手順。**アーキテクチャ = `@gongrzhe/server-gmail-autoauth-mcp` を
アカウント数ぶん起動する 1:1 構成** (server × account)。upstream README は単アカウント
まで — 本 doc は多アカウント + 全マシン配布 + 送信ガードの家風一式。

## 構成

```
claude-config/scripts/                 # 実行実体 (エンジン) は本リポ = 層 1 の 1 本だけ
├── gmail-mcp-reauth.sh                #   OAuth (再)認証エンジン
└── gmail-mcp-install-runtime-links.sh #   symlink 張りエンジン (冪等)

<your-private-config-repo>/            # private + git-crypt (メール・token を含むため)
├── accounts.yaml                      # alias → email の一覧 (git-crypt。エンジンが実行時に読む)
├── reauth.sh                          # 2 行 wrapper: exec <claude-config>/scripts/gmail-mcp-reauth.sh "$(dirname "$0")" "$@"
├── install-runtime-links.sh           # 2 行 wrapper (同上、 install-runtime-links エンジンへ)
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
   [`templates/gmail-mcp/accounts.yaml.example`](../templates/gmail-mcp/accounts.yaml.example)
   → `accounts.yaml` に自分の alias/email。wrapper 2 本 (各 2 行、上の構成図の形) を作成。
3. `~/.gmail-mcp/reauth.sh` → private repo の wrapper reauth.sh へ symlink。

**なぜ engine を層 1 に置くか** (= fork drift の design-out): instance ごとに script を
copy すると必ず実装が分岐する。実行実体を層 1 の 1 本に統一し、instance 側は
「data (accounts.yaml / secrets) + 2 行 wrapper」だけにすれば、engine の改良が
全 instance に git pull で届き、逆に instance 固有の値は engine に混入しない。

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
- reauth が「期待 email を解決できません」で中止 → **先に `git-crypt unlock`** (+
  accounts.yaml に alias entry があるか確認)。未検証で押し切る escape hatch は
  `REAUTH_ALLOW_UNVERIFIED=1` (アカウント選び間違いが検出されなくなる、常用しない)
- **新マシン** → clone + `git-crypt unlock` + `install-runtime-links.sh` (再認証不要)
- MCP に無い操作 (添付 byte 列・batch 削除等) は同じ credential で Gmail REST API を
  Python から直叩き ([`google-api-direct-access.md`](google-api-direct-access.md))

## セキュリティ設計 (invariant として維持するもの)

1. **公開面 (層 1 engine) に秘匿情報ゼロ**: メールアドレス・alias・token・client keys
   は engine に一切書かない。engine は実行時に private repo の git-crypt な
   accounts.yaml / secrets/ を読むだけ。engine を変更するときはこの invariant を
   毎回 grep で確認する (email regex + 固有名)。
2. **token の露出面**: credential file は 0600、engine は token 本体を print しない
   (presence の yes/no のみ)。`.expired.*` backup はローカル実 file (= repo に乗らない)。
   backup (`.expired.*` / `.premigration.*`) は engine が必ず chmod 600 に矯正し
   (`cp -p` は旧 mode を保存するため — 644 backup が残った実例 2026-08-18)、
   `~/.gmail-mcp` と account dir は 0700 (macOS の $HOME は staff group traverse 可の
   構成がありうるため、credential 置き場自体を owner-only にする)。
3. **trust model の変化に注意**: engine は public repo から git pull で更新される =
   **credential を触るコードの供給路が public repo になる**。書き込みは owner 単独 +
   branch protection + push protection + secret scanning が前提。それでも
   **engine の diff は pull 時に他の code より一段注意して見る** (特に token の
   書き込み先・print・network 先の変更)。不安なら instance 側 wrapper で engine を
   commit hash に pin する選択肢もある (更新が手動になる trade-off)。
4. **送信は必ず ask gate 越し** (checklist 5)。gate の宣言配線は silent に消えうるので
   機械 audit で恒常監視する ([`gmail-sending.md#double-confirmation-design`](gmail-sending.md#double-confirmation-design))。
5. **アカウント取り違え防止**: reauth engine は login_hint 事前選択 + 認証後
   getProfile 照合で、違うアカウントの token が alias に紐づく事故を構造的に防ぐ
   (不一致 = token 自動破棄)。
6. **npm package は version pin**: `~/.claude.json` の args は
   `@gongrzhe/server-gmail-autoauth-mcp@<version>` と exact pin する (unpinned だと
   npx cache miss 時に upstream の最新 = 悪意ある新 release がそのまま mailbox token
   を握る)。version 更新は意図的な bump として diff review とセットで行う。
7. **OAuth callback は state nonce + PKCE (S256) で保護** (2026-08-18 実装):
   loopback (127.0.0.1) listener は state 一致の request しか受理せず、不一致
   (drive-by page / 同一マシン他プロセスの偽 callback) は 400 で無視して本物を
   待ち続ける。token 交換は code_verifier 必須 = 横取りされた code の再利用も不能。
   手動 URL 貼付 fallback でも state を検証する (= phishing された URL は貼っても
   state 不一致で拒否)。さらに **expected email を解決できない reauth は既定で中止**
   (= 5 の getProfile 照合が空振りになる状態で consent に進まない。accounts.yaml の
   unlock を先に直すのが正道、意図的に未検証で進む場合のみ
   `REAUTH_ALLOW_UNVERIFIED=1`)。一般則・レシピの正本 =
   [`google-api-direct-access.md#oauth-loopback-hardening`](google-api-direct-access.md#oauth-loopback-hardening)。
8. **引数は信頼しない**: account alias は plain token (`A-Za-z0-9_-`) のみ受理 —
   alias は filesystem path と `pgrep -f` pattern に流れるため、traversal (`..`) や
   ERE metachar (`|` は alternation で kill 対象が任意プロセスに化ける) を入口で拒否する。

実例 instance: 所有者の `gmail-mcp-config` (private) が 6 アカウントでこの構成を運用
(collaborator はアクセス不要 — 本 doc + templates だけで独立に構築できる)。
