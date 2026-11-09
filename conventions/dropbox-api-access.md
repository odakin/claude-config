<!-- doc-meta
when: Dropbox をプログラムから操作したいとき (共有リンク発行・metadata・upload) + 共同編集者から「Dropbox の容量がいっぱい」 と言われ、 自分の共有フォルダが相手の容量をどれだけ使っているかを量るとき + 共有フォルダに大きいデータを足す前 (#shared-folder-quota) + 共有フォルダの重い中身を自分だけのフォルダへ移すとき・容量のいっぱいな相手から大きい file を受け取るとき (#split-shared-folder-keep-paths)
category: infra
summary: Dropbox HTTP API 直叩きの setup pattern — 公式 MCP / CLI 不在ゆえ API 直が機械経路 (= scoped app 最小 permission + 「authorize 時点の permission が token に焼き込まれる」順序罠 #scoped-app-setup、 PKCE public client = app secret 無し #pkce-no-secret、 共有リンクの冪等取得 = create 409 → list fallback #share-link-idempotent、 path 変換と online-only placeholder でもリンク可 #path-semantics、 共有状態の read recipe = list_folders は cursor 完走まで不在断定しない + get_metadata の sharing_info 直行 + list_folder_members で共同編集者の own-account 検証 + search_v2 は upload 失敗 file に痕跡ゼロ #sharing-read-recipes、 共有フォルダは入っている全員の容量に数えられる・online-only では減らない・大きさは list_folder recursive の size の和・誰が入れたかは sharing_info.modified_by・外す前に他の仕組みが読む file を確かめる #shared-folder-quota、 sharing.write token の blast radius = 全 file への公開リンク発行が可能 #blast-radius)
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

- <a id="members-only-link"></a>**共有フォルダのメンバーだけが開けるリンク** (私的な録音・下書きを、 すでにフォルダを共有している相手に指し示すとき):
  `{"path": …, "settings": {"audience": "no_one", "access": "viewer"}}` で作る。 リンクは場所を指すだけで権限を足さない =
  メンバーでない人が開いても中身は見えない (返る `link_permissions.effective_audience` が `no_one` であることを確かめる = 実測でこの値が返った)。 ⚠️ 先に `list_shared_links` を見る: 既定 (全員が閲覧可) のリンクが既にあると、
  create は 409 で**その既存リンクを返す**ので、 狭いリンクのつもりで広いリンクを渡すことになる。
  渡す相手がフォルダのメンバーかは [#sharing-read-recipes](#sharing-read-recipes) の `list_folder_members` で先に確かめる

## <a id="path-semantics"></a>path 変換と placeholder

- API の path は **Dropbox 相対** (`/フォルダ/ファイル`)。 ローカル path から変換するなら realpath で sync root (`~/Dropbox` 等、 symlink 解決後) と照合して相対化する — root 外 path は reject
- **online-only placeholder (ローカル 0 byte) でもリンク発行は可能** — metadata は server 側に実在する ([`dropbox-placeholder-diagnosis.md`](dropbox-placeholder-diagnosis.md))

## <a id="sharing-read-recipes"></a>共有状態の読み取り recipe (メンバー確認・フォルダ列挙・雲内検索)

共有リンク用の最小 scope set (`sharing.read` + `files.metadata.read`) のままで、以下の read 系がすべて通る (2026-08-29 実測)。「この共同編集者は自分のアカウントで正規アクセスを持っているか」の検証 (device 整理・アカウント棚卸しの前提確認) に使える:

- **共有フォルダ列挙**: `POST /2/sharing/list_folders` `{"limit": 100}` → ⚠️ **cursor を完走するまで不在断定しない** — 続きは `/2/sharing/list_folders/continue` `{"cursor": …}`。実測: 196 folder の account で目的 folder が 2 ページ目にあり、1 ページ目だけ見て「共有されていない」と誤結論しかけた (= 単一ページ null を absence に変換する trap の API 版)
- **path から直接**: folder 名で列挙を探すより `POST /2/files/get_metadata` `{"path": "/<相対 path>"}` が速い — `sharing_info.shared_folder_id` が返れば共有フォルダ (無ければ非共有)
- **メンバー確認**: `POST /2/sharing/list_folder_members` `{"shared_folder_id": …}` → `users[].user.email` + `access_type` (owner/editor/viewer)、`invitees[]` は招待未承諾
- **雲内検索**: `POST /2/files/search_v2` `{"query": …, "options": {"file_status": "active"}}` (`"deleted"` で削除済みも)。⚠️ **同期エラーで upload に失敗した file は雲に痕跡ゼロ** — search でも list でも出ない。「雲に無い」は「どのマシンにも無い」を意味しない (実体は作成元マシンのローカルにだけある)
  - **本文も引ける**: 既定で file の中身も検索し、 結果の `match_type` が `filename`・`file_content`・`filename_and_content` のどれかで返る (実測)。 online-only の file を落とさずに中身で探せるので、 file 名が題名と違う論文の PDF はこれで見つかる。 file 名だけなら `"filename_only": true`
  - **範囲は `options.path` で絞る**: 付けないと全 file が対象になり、 機密のフォルダの file 名まで手元に返る。 探す先のフォルダを指定する
  - **本文の一致は言及も拾う**: 上位の結果にその題を引用しているだけの file が並ぶ = 開いて確かめる。 `max_results` の外は見えない。 文字の層が無い scan が本文で掛かるかは未確認

## <a id="shared-folder-quota"></a>共有フォルダが相手の容量にどう数えられるか・大きさと誰が入れたかの量り方

共同編集者から「Dropbox の容量がいっぱい」 と言われたときに、 自分が共有しているフォルダが相手の容量をどれだけ使っているかを、 同じ最小 scope (`sharing.read` + `files.metadata.read`) で量る手順。 file の中身は読まない。

**数え方** (Dropbox の公式 help。 判断に使う前に、 各頁の今の版を開いて確かめる):

- 共有フォルダの大きさは、 入っている**全員の**容量にまるごと数えられる。 全員が同じ team (Standard・Advanced・Enterprise) か同じ Family plan にいるときは 1 回だけ数える ([shared-folder-count-against-storage](https://help.dropbox.com/storage-space/shared-folder-count-against-storage))
- 共有リンクで受け取ったものは、 受け取った人の容量に数えられない (自分の Dropbox に保存すれば数えられる) ([storage-space](https://help.dropbox.com/storage-space/storage-space))
- 共有フォルダから抜けると、 その中身は容量に数えられなくなる。 戻るには持ち主が招待し直す ([leave-shared-folder](https://help.dropbox.com/share/leave-shared-folder))
- **online-only にしてもアカウントの容量は減らない** (減るのは PC やスマホのディスクだけ) ([make-files-online-only](https://help.dropbox.com/sync/make-files-online-only))。 同じアカウントの中で別のフォルダに動かしても減らない。 減らすのは、 抜ける・Dropbox の外へ出す・消す (消した file と版の履歴は数えられない = [delete-files](https://help.dropbox.com/delete-restore/delete-files) / [version-history-overview](https://help.dropbox.com/delete-restore/version-history-overview))
- 無料の Basic で容量を超えたままだと、 前もってメールで知らせたうえで、 **その人が持ち主の file** を最後に変えた日の古いものから消すことがある。 他人が持ち主の共有フォルダは、 中身を消さずに外す ([over-quota](https://help.dropbox.com/storage-space/over-quota)) = 急ぐ理由は相手の側の file にある
- 「容量がいっぱい」 が PC のディスクのことなら話が違う (online-only にすればディスクが空く)。 どちらかを相手に確かめる

**量り方**:

1. **相手が入っている共有フォルダ**: 上の `sharing/list_folders` を cursor の最後まで回し、 各フォルダの `sharing/list_folder_members` の `users[].user.email` (と `invitees[]`) を相手のアドレスと照合する。 ⚠️ **1 人が複数のアカウントで入っていることがある** (個人のアドレスを 2 つ持つなど。 実測) = 相手のアドレスを全部渡し、 アカウントごとに数える (容量はアカウントごと)
2. **大きさ**: `POST /2/files/list_folder` `{"path": "<フォルダの path>", "recursive": true, "include_mounted_folders": true, "limit": 2000}` → `has_more` が false になるまで `/2/files/list_folder/continue` → `.tag == "file"` の `size` を足す。 online-only の file も元の大きさで返る (= 手元の `du` は placeholder の分しか数えない、 [#path-semantics](#path-semantics))。 入れ子の共有フォルダは親の再帰に入るので、 アカウントごとの合計は同じ path を 1 回だけ数えて足す
3. **誰が入れたか**: 各 entry の `sharing_info.modified_by` (account id) を、 `list_folder_members` の `users[].user.account_id` と突き合わせて表示名にする。 ⚠️ これは**最後に変えた人**で、 入れた人と別のことがある (名前を変えた人など)
4. **中身の同じ file**: `content_hash` が同じなら中身が同じ (別の名前・別の場所の重複を、 落とさずに見つけられる)
5. **増え方**: `server_modified` で期間ごとに足す。 最後に変わった日なので、 古い file に新しい版を保存すると新しく見える
- ⚠️ **自分の token から見えないもの**: 相手の plan・割り当て・使用量、 相手だけの file、 第三者が相手と共有しているフォルダ、 相手が mount しているか (`sharing/list_mountable_folders` は mount 済みのフォルダも返すので、 未 mount だけの一覧にならない = 実測)。 「空き」 は書けず、 書けるのは「自分の共有フォルダが占める量」 だけ

**大きいデータを足す前に** (取得したデータ・生成物を共有フォルダに置く前):

- 相手の空きは自分の token から見えない (上の ⚠️) = 足す量を相手に伝え、 相手の画面で確かめてもらう
- データは先に手元 (共有フォルダの外) に置き、 検査 (行数・既知のデータとの照合) を通してから共有フォルダに置く = 検査で落ちたデータが相手の解析に流れず、 置き直しで相手の容量と同期を二度使わない

**減らす案を出すとき**:

- 共有フォルダから人を外す案を出す前に、 そのフォルダに**他の仕組みが読む file** (共有 repo の暗号鍵の写し、 setup の手順が path で指す file) が無いかを確かめる。 外すと相手の新しい機械での setup が止まる (実測)。 その repo の共同編集者の一覧と突き合わせる
- 持ち主の側から外す (`POST /2/sharing/remove_folder_member`) なら `"leave_a_copy": false` = 写しを残すと、 その写しが相手の容量にそのまま数えられる
- 相手が入れた file を共有の外へ出す案は、 自分の Dropbox からも消える = 自分が要るものは先に共有していないフォルダへ写す。 自分の file を共有していないフォルダへ動かす分には、 自分の容量は変わらない

<a id="split-shared-folder-keep-paths"></a>**減らす形の 1 つ = 重い中身を持ち主だけのフォルダへ移し、 道具の path は変えない**:

- 共有していない新しいフォルダを作って重い下のフォルダを移す → 共有フォルダの名前を**自分の側だけ**変える (共有フォルダの名前の変更は、 変えた人の側だけに効く = [rename-move-shared-folder](https://help.dropbox.com/organize/rename-move-shared-folder)) → 新しいフォルダに元の名前を付ける。 手元の道具・symlink・文書が指す path は元のまま持ち主だけの中身を指し、 相手の側の共有フォルダの名前も元のまま
- 1 段ごとにサーバーに届いたのを確かめてから次へ (名前を入れ替える途中で同じ名前が 2 つになると衝突する)。 確かめ方 = 新しい path の `files/get_metadata` (届く前は 409 が返る = 実測)、 共有リンクの `path_lower` が新しい path に変わったか
- 共有リンクは file と一緒に動く = 移した後も開け、 新しい path を指す (実測: 移す前に一覧にしたリンクが全部開けた)。 共有フォルダの頂に付けたリンクは共有フォルダに残る。 ⚠️ 移した先にも「リンクを知る誰でも開ける」 リンクがそのまま付いている = 移す前に `sharing/list_shared_links` で一覧にして、 公開範囲を確かめる
- **容量のいっぱいな相手から大きい file を受け取る口 = ファイルリクエスト**: 置かれた file は依頼した側の容量に数えられ ([storage-space](https://help.dropbox.com/storage-space/storage-space))、 置く人は Dropbox のアカウントが無くても置ける。 相手が共有フォルダに置くと相手の容量にも数えられる = 容量のいっぱいな相手には共有フォルダに置かせない。 ⚠️ 作るには `file_requests.write` の scope が要る (共有リンクの最小 scope には無い) = その scope を足すか、 持ち主が web の画面で 1 回作る。 リンクの頁からは届け先のフォルダが見えない = 最初の 1 通が届いた場所で確かめる。 届いた物は相手が書いた物として検査してから使う ([`downloaded-file-scan.md`](downloaded-file-scan.md))
- ⚠️ **形を変えたら、 相手に渡した手順も同じ時に差し替える**: 前に渡した手順 (AI に貼る文面など) が「共有フォルダの X に置く」 と言っていると、 相手はその手順で置き、 X の消えた相手の側では共有フォルダの頂に入る (実測)。 古い手順で置かれた物は持ち主のフォルダに写し、 共有の方を消すのは、 相手が元の file を手元に持っているのを確かめてから

## <a id="shared-folder-editor-invite"></a>共有フォルダにして相手を編集者として招待する (相手も書き込める)

閲覧リンクでは相手が書き込めない。 共同で使うフォルダは shared folder にして編集者として招待する。 scope は共有リンクと同じ `sharing.write` + `sharing.read` で足りる (内容の read / write 権限は要らない)。

- `POST /2/sharing/share_folder` `{"path": …, "force_async": false}` → `shared_folder_id`。 既に共有なら 409 `bad_path` / `already_shared` に id が入る = 冪等に扱える。 大きいフォルダは `async_job_id` → `check_share_job_status`
- `POST /2/sharing/add_folder_member` `{"shared_folder_id": …, "members": [{"member": {".tag": "email", "email": …}, "access_level": {".tag": "editor"}}]}` — ⚠️ **相手に Dropbox から招待メールが飛ぶ = 外部発信** (道具は既定 dry-run にし、 送る指定のときだけ呼ぶ)
- `POST /2/sharing/list_folder_members` で参加者と招待中を見る。 相手がそのアドレスの Dropbox アカウントを持っていれば、 招待の直後から参加者に載る (実測)
- **招待先は見つかったアドレス全部** — 相手がこのサービスで使っているアドレスは分からない。 使っているアカウントで参加が成立し、 残りの招待は未受諾のまま残る ([`#person-address-channels`](../docs/convention-design-principles.md#person-address-channels))
- 用途の例 = 共同編集の repo の PDF を push のたびに写す共有フォルダ ([`templates/shared-project/pdf-publish/`](../templates/shared-project/pdf-publish/))

## <a id="blast-radius"></a>blast radius (= この token で何が壊せるか)

`sharing.write` token は **Dropbox 全体の任意 file / folder への公開リンク発行**と、 **任意のフォルダを共有フォルダにして他人を招待すること**ができる = 漏洩時は data exfiltration 級。 最小 scope でも「軽い secret」 ではない:

- 暗号化保管 (git-crypt 等) + mode 600、 値を chat / plaintext commit に出さない
- `files.content.*` を付けない限り**内容の read / write は API level で拒否される** (`files/get_temporary_link` が 400 "not permitted to access this endpoint" を返すことを 1 probe で実測確認できる = scope 検証の exposure 操作)
- 失効: App Console → 当該 app → Settings で token revoke (or app 削除)。 その後の再認証は consent やり直しのみ

関連: [`machine-route-first.md`](machine-route-first.md) (経路選択の一般則) / [`google-api-direct-access.md`](google-api-direct-access.md) (Google 版 sibling) / [`dropbox-refs.md`](dropbox-refs.md) (共有 PDF の symlink 参照規約)
