<!-- doc-meta
when: Dropbox をプログラムから操作したいとき (共有リンク発行・metadata・upload)
category: infra
summary: Dropbox HTTP API 直叩きの setup pattern — 公式 MCP / CLI 不在ゆえ API 直が機械経路 (= scoped app 最小 permission + 「authorize 時点の permission が token に焼き込まれる」順序罠 #scoped-app-setup、 PKCE public client = app secret 無し #pkce-no-secret、 共有リンクの冪等取得 = create 409 → list fallback #share-link-idempotent、 path 変換と online-only placeholder でもリンク可 #path-semantics、 共有状態の read recipe = list_folders は cursor 完走まで不在断定しない + get_metadata の sharing_info 直行 + list_folder_members で共同編集者の own-account 検証 + search_v2 は upload 失敗 file に痕跡ゼロ #sharing-read-recipes、 sharing.write token の blast radius = 全 file への公開リンク発行が可能 #blast-radius)
-->
# Dropbox API 直アクセス (共有リンク・metadata)

Dropbox には公式 MCP が無く、 公式 CLI (dbxcli) も保守停止 — **HTTP API 直叩きが機械経路** (= [`machine-route-first.md`](machine-route-first.md) の instantiation)。 Python stdlib (urllib) だけで完結する。

## <a id="scoped-app-setup"></a>Scoped app の作成 (user 操作) と最小 permission

https://www.dropbox.com/developers/apps/create で **Scoped access** app を作る (user 操作 = 認証境界)。

- **access type**: 既存のファイル / フォルダを触るなら **Full Dropbox**。 App folder は専用フォルダしか見えない
- **Permissions タブで最小 scope だけ ✓ → Submit**。 共有リンク用途なら `sharing.write` + `sharing.read` + `files.metadata.read` の 3 つで足りる (`files.content.*` は付けない — #blast-radius)
- ⚠️ **順序罠: token に載る scope は authorize 時点で app に有効な permission**。 Permissions の Submit より先に consent すると scope 不足 token になり再認証が要る — **Permissions → Redirect URI → consent の順**
- **Settings タブ**: Redirect URIs に loopback (`http://localhost:<port>/`) を登録
- **Status = Development のままで個人利用は完結する** (production apply は第三者に配る時だけ。 app owner 自身の token は Development のまま失効しない)

## <a id="pkce-no-secret"></a>PKCE public client (= app secret 無し)

native / script 用途では **PKCE (S256) で app secret を使わない**: 保管すべき secret が refresh token 1 つに減る (app secret の rotate / 漏洩管理が丸ごと消える)。

- authorize URL: `https://www.dropbox.com/oauth2/authorize?client_id=<APP_KEY>&response_type=code&code_challenge=<S256>&code_challenge_method=S256&token_access_type=offline&redirect_uri=…&state=<nonce>`
- token 交換 / refresh: `https://api.dropboxapi.com/oauth2/token` に `client_id` だけ (secret 不要)。 `token_access_type=offline` で refresh token が返る
- **loopback consent は [`google-api-direct-access.md` oauth-loopback-hardening](google-api-direct-access.md#oauth-loopback-hardening) の 4 点 set をそのまま適用** (state nonce + 検証 loop / PKCE / 手動貼付経路を持たない / account 検証 hard-fail)。 account 検証は `POST /2/users/get_current_account` の `email` を期待値と照合し、 不一致 token は保存しない
- refresh token は暗号化保管 (個人層の git-crypt 経路等)。 App key は public client の識別子で secret ではない

## <a id="share-link-idempotent"></a>共有リンクの冪等取得

「リンクを作る」 でなく 「リンクを得る」 に設計する (再実行で同じ URL):

1. `POST /2/sharing/create_shared_link_with_settings` `{"path": "/<相対 path>"}`
2. **409** で `error[".tag"] == "shared_link_already_exists"` なら
   `POST /2/sharing/list_shared_links` `{"path": …, "direct_only": true}` → `links[0].url`

file でも folder でも同じ。 返る URL は `https://www.dropbox.com/scl/…?rlkey=…` 形式 (リンクを知る全員が閲覧可、 既定)。

## <a id="path-semantics"></a>path 変換と placeholder

- API の path は **Dropbox 相対** (`/フォルダ/ファイル`)。 ローカル path から変換するなら realpath で sync root (`~/Dropbox` 等、 symlink 解決後) と照合して相対化する — root 外 path は reject
- **online-only placeholder (ローカル 0 byte) でもリンク発行は可能** — metadata は server 側に実在する ([`dropbox-placeholder-diagnosis.md`](dropbox-placeholder-diagnosis.md))

## <a id="sharing-read-recipes"></a>共有状態の読み取り recipe (メンバー確認・フォルダ列挙・雲内検索)

共有リンク用の最小 scope set (`sharing.read` + `files.metadata.read`) のままで、以下の read 系がすべて通る (2026-08-29 実測)。「この共同編集者は自分のアカウントで正規アクセスを持っているか」の検証 (device 整理・アカウント棚卸しの前提確認) に使える:

- **共有フォルダ列挙**: `POST /2/sharing/list_folders` `{"limit": 100}` → ⚠️ **cursor を完走するまで不在断定しない** — 続きは `/2/sharing/list_folders/continue` `{"cursor": …}`。実測: 196 folder の account で目的 folder が 2 ページ目にあり、1 ページ目だけ見て「共有されていない」と誤結論しかけた (= 単一ページ null を absence に変換する trap の API 版)
- **path から直接**: folder 名で列挙を探すより `POST /2/files/get_metadata` `{"path": "/<相対 path>"}` が速い — `sharing_info.shared_folder_id` が返れば共有フォルダ (無ければ非共有)
- **メンバー確認**: `POST /2/sharing/list_folder_members` `{"shared_folder_id": …}` → `users[].user.email` + `access_type` (owner/editor/viewer)、`invitees[]` は招待未承諾
- **雲内検索**: `POST /2/files/search_v2` `{"query": …, "options": {"file_status": "active"}}` (`"deleted"` で削除済みも)。⚠️ **同期エラーで upload に失敗した file は雲に痕跡ゼロ** — search でも list でも出ない。「雲に無い」は「どのマシンにも無い」を意味しない (実体は作成元マシンのローカルにだけある)

## <a id="blast-radius"></a>blast radius (= この token で何が壊せるか)

`sharing.write` token は **Dropbox 全体の任意 file / folder への公開リンク発行**ができる = 漏洩時は data exfiltration 級。 最小 scope でも「軽い secret」 ではない:

- 暗号化保管 (git-crypt 等) + mode 600、 値を chat / plaintext commit に出さない
- `files.content.*` を付けない限り**内容の read / write は API level で拒否される** (`files/get_temporary_link` が 400 "not permitted to access this endpoint" を返すことを 1 probe で実測確認できる = scope 検証の exposure 操作)
- 失効: App Console → 当該 app → Settings で token revoke (or app 削除)。 その後の再認証は consent やり直しのみ

関連: [`machine-route-first.md`](machine-route-first.md) (経路選択の一般則) / [`google-api-direct-access.md`](google-api-direct-access.md) (Google 版 sibling) / [`dropbox-refs.md`](dropbox-refs.md) (共有 PDF の symlink 参照規約)
