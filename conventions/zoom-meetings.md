<!-- doc-meta
when: Zoom のミーティングを script から作る・設定を読む経路を用意するとき + 定例用に「いつでも入れる常設の部屋」 を個人ミーティングルーム (PMI) と別に用意するとき + 作った部屋が待機室つきになった / 参加 URL が個人部屋のものになったとき + 会議の議事録は欲しいが録画は要らないとき
category: infra
summary: Zoom の機械経路は Server-to-Server OAuth app 1 つで開く (#s2s-oauth-route、 scope は meeting read/write/delete + user read/settings の admin 版、 token は account_id + Basic 認証で自己発行)。 常設の部屋を PMI と分ける判断 (#dedicated-room-vs-pmi)。 create の 2 つの罠 = アカウント既定「予定されたミーティングに PMI を使用」 が ON だと新しい id が発番されるのに参加 URL は PMI のものになる (#use-pmi-silently-hijacks-create)、 passcode なしで作ると waiting_room が要求を無視して true に上書きされる (#passcode-or-waiting-room)。 固定時刻なしの定期ミーティングは最終使用から 365 日で失効する (#no-fixed-time-expiry)。 録画と議事録は別機能で、 録画せずに要約だけ回せる (#recording-vs-summary)。 作った部屋は番号だけ残ると用途が失われる (#record-the-room)
-->
# Zoom のミーティングを script から扱う

Zoom には user 名義で常設の API credential を発行する経路が無いが、 **account の owner / admin は
Server-to-Server OAuth app を 1 つ作れる**。 これで token を自己発行でき、 部屋の作成・設定の読み取りが
機械経路に乗る (= [`machine-route-first.md`](machine-route-first.md) `#route-ladder` の段 2 に上がる)。
画面を開いて毎回 click する必要は無くなる。

実装 = [`../scripts/zoom-client.py`](../scripts/zoom-client.py) (stdlib のみ、 `whoami` / `show` / `list` /
`create` / `update` / `delete`。 作成・削除・変更は既定 dry-run)。

## <a id="s2s-oauth-route"></a>Server-to-Server OAuth (= 唯一の常設 credential)

本人が Marketplace で 1 回だけ行う (以後は不要):

1. Marketplace → Develop → Build App → **Server-to-Server OAuth** → Create
2. **Information** タブの必須欄 (Company Name / Developer Contact Name / Developer Contact Email)
3. **Scopes** タブ → Add Scopes。 ⚠️ 検索欄に製品名 (`meeting` 等) を入れると数百件出るので、
   **スコープ名をそのまま入れて 1 つずつ足す**:
   `meeting:read:meeting:admin` / `meeting:write:meeting:admin` / `meeting:delete:meeting:admin` /
   `user:read:user:admin` / `user:read:settings:admin`
   (旧体系の account なら `meeting:read:admin` / `meeting:write:admin` / `user:read:admin`)
4. **Activation** タブ → Activate
5. **App Credentials** タブの **Account ID / Client ID / Client Secret** の 3 値を保管する

token の取り方: `POST https://zoom.us/oauth/token` に
`grant_type=account_credentials&account_id=<Account ID>` を form で、 `Authorization: Basic
base64(client_id:client_secret)` を header で。 有効 1 時間。

⚠️ **Activate 前の token 要求は `invalid_client` + `"The app has been disabled by the developer"`**。
これは client_id が間違っているのではなく**アプリが未有効化**の合図で、 逆に言えば
**この文言が返れば Account ID と Client ID は正しい** (= 切り分けに使える)。

⚠️ 3 値は secret として扱う (= 平文で chat・issue・commit message に載せない)。 ⚠️ 変更系のスコープを
後から足すと既存 token では足りず `4711 Invalid access token, does not contain scopes:[...]` が返る
(= エラーが必要な scope 名をそのまま教えてくれるので、 それを足して再 Activate する)。

## <a id="dedicated-room-vs-pmi"></a>常設の部屋を PMI と分けるか

個人ミーティングルーム (PMI) は「いつでも入れる常設の部屋」 そのものなので、 **別に作る理由があるのは
衝突を避けたいとき**: PMI を複数の定例で共用していると、 時間が重なった 2 つの会議が同じ部屋に入る。
用途ごとに部屋を分ければ混ざらない。

分けて作るときの既定は **type 3 (定期ミーティング・固定時刻なし)** で、 設定は PMI から写すのが早い
(`create --like <PMI>`)。 写すのは開催者側の運用設定 (ビデオ・待機室・ホストより前の参加・音声・暗号化)
だけで、 招待・録画先・代替ホストは写さない。

## <a id="use-pmi-silently-hijacks-create"></a>罠 1: 新しい部屋が PMI の別名になる

アカウント設定 **「予定されたミーティングに個人ミーティング ID を使用」 が ON** だと、 API で作った
ミーティングも PMI を使う。 このとき:

- **新しい meeting id は発番される** (= 作成は成功したように見える)
- しかし `join_url` は `https://<cluster>.zoom.us/j/<PMI>?pwd=...&omn=<新 id>` = **参加先は個人部屋**
- ∴ 「別の部屋を作った」 つもりが PMI の別名でしかなく、 分けた意味が消える

**対策**: create のとき `settings.use_pmi` を**常に明示的に false で送る** (省略するとアカウント既定に従う)。
**見分け方**: `join_url` の番号が PMI と同じか / `settings.use_pmi`。 **id が違うことは根拠にならない**
(= 別 id が出るので気づきにくい)。 実測。

## <a id="passcode-or-waiting-room"></a>罠 2: passcode を付けないと待機室が強制される

Zoom は **「パスコード」 と「待機室」 のどちらかを必須**にする。 `waiting_room: false` を明示しても、
**passcode 無しで作れば `waiting_room` は true に上書きされる** (要求は黙って無視される)。

待機室 ON は「いつでも入れる部屋」 を壊す — ホストが来るまで相手は待合室に取り残され、 ホストが毎回
承認操作をすることになる。 ∴ **常設の部屋は passcode を付けて作る** (= `join_url` に `?pwd=` が埋まるので
参加側の手間は増えない)。 実測。

**受け入れ検査**: 作った直後に `settings.waiting_room` を読み、 false になっているか見る。
要求した値がそのまま入っているとは限らない、 というのがこの罠の一般形
([`../docs/convention-design-principles.md`](../docs/convention-design-principles.md) の「要求と結果を突き合わせる」)。

## <a id="no-fixed-time-expiry"></a>固定時刻なしの定期ミーティングは 365 日で失効する

type 3 (No Fixed Time) の部屋は **最終使用から 365 日**で消える。 PMI にはこの制約が無い。
年 1 回しか使わない用途 (年度単位の講義・年次の委員会) では**失効しうる**ので、
作り直せるように **作成コマンドを記録に残す** (#record-the-room)。

## <a id="recording-vs-summary"></a>録画と議事録は別機能 — 録画せずに要約だけ回せる

`auto_recording` は **自動録画**の設定で `none` / `local` (ホストの端末に保存) / `cloud` の 3 択。
一方 **AI Companion の「ミーティング要約」 は録画とは独立**していて、
`settings.auto_start_meeting_summary: true` にすれば **`auto_recording: none` のままで**
入室と同時に要約が回る。

∴ 「議事録は欲しいが録画は要らない」 は `auto_recording=none` + `auto_start_meeting_summary=true`。
録画を ON にしてから要約だけ取り出す必要は無い。

⚠️ 要約が動くことは参加者にも表示される。 相手のいる会議では一言断る前提で設定する。
⚠️ 要約の送付先はアカウント側の設定 (`in_meeting.meeting_summary_with_ai_companion`) で決まる。

## <a id="read-summary-and-transcript"></a>終わった会議の要約と文字起こしを読む — 「無い」 も API で言い切る

道具 = `zoom-client.py notes <meeting_id> --date YYYY-MM-DD [--out DIR]` (その日の回を過去の回の一覧から探し、
要約の JSON と文字起こしの VTT を保存する)。 要る scope は読み取りの 5 つ
(`meeting:read:list_past_instances:admin` / `meeting:read:past_meeting:admin` / `meeting:read:summary:admin` /
`meeting:read:list_summaries:admin` / `cloud_recording:read:meeting_transcript:admin`)。 実測では、
有効化済みの app に scope を足すと、 その直後に発行した token から効いた (Activate し直す操作は要らなかった)。

- **「無い」 の根拠は 2 つの応答**: 過去の回の詳細 (`GET /past_meetings/{uuid}`) の `has_meeting_summary` と、
  文字起こし (`GET /meetings/{uuid}/transcript`) の code 3322。 通知メールの有無で判断しない
  (届かない設定もあるし、 メール検索の空振りは「無い」 の証明にならない)
- **ローカル録画のフォルダには要約も文字起こしも入らない** (入るのは音声・動画・設定 file だけ)。
  要約は Zoom 側にだけ残る
- **個人部屋 (PMI) は既定で `auto_start_meeting_summary=false`** = 要約が作られるのは会議中に手で開始したときだけ。
  講義など「あとで要約が欲しい」 部屋は、 その部屋の設定で自動開始にしておく (参加者に表示される点は上の ⚠️)
- 過去の回の UUID が `/` で始まるか `//` を含むときは、 path に入れる前に二重に percent-encode する (しないと 404)
- ⚠️ My Notes (本人のメモ機能の文字起こし) は別の API (`/my_notes/notes`) で、 `my_notes:read:note:admin` 等の
  別 scope が要る

## <a id="record-the-room"></a>作った部屋は「番号 + 用途 + 失効条件」 で記録する

常設の部屋は **id だけが残ると何の部屋か分からなくなる** (= 1 年後に作り直すべきか、
まだ誰かが使っているかが判断できない)。 作ったらその用途の home (講義なら科目の dir、
プロジェクトならその repo) に:

- ミーティング **id** と用途
- 設定の要点 (固定時刻なし / 待機室なし / 録画の有無)
- **失効条件と作り直しのコマンド** (#no-fixed-time-expiry)

を書く。 ⚠️ **参加 URL は passcode を含むので記録に書かない** — id を書いておけば
`zoom-client.py show <id>` で引ける。 これは「秘密は保存しない > 暗号化する」
([`confidential-repo-boundary.md`](confidential-repo-boundary.md)) の小さい instance。
