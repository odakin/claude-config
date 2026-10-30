<!-- doc-meta
when: Zoom のミーティングを script から作る・設定を読む経路を用意するとき + 定例用に「いつでも入れる常設の部屋」 を個人ミーティングルーム (PMI) と別に用意するとき + 作った部屋が待機室つきになった / 参加 URL が個人部屋のものになったとき + 会議の議事録は欲しいが録画は要らないとき + 終わった会議の AI 要約・文字起こしを取り出すとき・「無い」 と言う前 (#read-summary-and-transcript) + 相手と口頭で決めた段取りを探すとき (#summary-mail-holds-agreements) + 開催通知のメールから本人を会議に入れるとき (#join-from-notice) + 会議・研修に出ていたかを機械で残すとき (#presence-from-process)
category: infra
summary: Zoom の機械経路は Server-to-Server OAuth app 1 つで開く (#s2s-oauth-route、 scope は用途ごとに admin 版を 1 つずつ足す = 部屋の作成・読み取り・変更・削除 / 自分と設定 / 終わった会議、 token は account_id + Basic 認証で自己発行)。 常設の部屋を PMI と分ける判断 (#dedicated-room-vs-pmi)。 create の 2 つの罠 = アカウント既定「予定されたミーティングに PMI を使用」 が ON だと新しい id が発番されるのに参加 URL は PMI のものになる (#use-pmi-silently-hijacks-create)、 passcode なしで作ると waiting_room が要求を無視して true に上書きされる (#passcode-or-waiting-room)。 固定時刻なしの定期ミーティングは最終使用から 365 日で失効する (#no-fixed-time-expiry)。 録画と議事録は別機能で、 録画せずに要約だけ回せる (#recording-vs-summary)。 終わった会議の要約と文字起こしは `notes` で取り出し、 「無い」 も過去の回の `has_meeting_summary` と transcript の 3322 で言い切る (#read-summary-and-transcript)。 作った部屋は番号だけ残ると用途が失われる (#record-the-room)。 通知メールの会議に本人を入れるときは passcode を chat に出さずクリップボードへ、 末尾の \r を落とす (#join-from-notice)。 出ていたかは account の参加の記録 (report API の pastJoined、 直近 6 か月の月だけ、 他人主催の会議は会議 id で同定) を毎日写し、 別 account の網として会議中だけ動く process `CptHost` を各機械で見張り、 1 台で予定と突き合わせる (自分主催の会議は開始の前後 15 分に入ったものだけ数える、 #presence-from-process)
-->
# Zoom のミーティングを script から扱う

Zoom には user 名義で常設の API credential を発行する経路が無いが、 **account の owner / admin は
Server-to-Server OAuth app を 1 つ作れる**。 これで token を自己発行でき、 部屋の作成・設定の読み取りが
機械経路に乗る (= [`machine-route-first.md`](machine-route-first.md) `#route-ladder` の段 2 に上がる)。
画面を開いて毎回 click する必要は無くなる。

実装 = [`../scripts/zoom-client.py`](../scripts/zoom-client.py) (stdlib のみ、 `whoami` / `show` / `list` /
`create` / `update` / `delete` / `notes`。 作成・削除・変更は既定 dry-run)。

## <a id="s2s-oauth-route"></a>Server-to-Server OAuth (= 唯一の常設 credential)

本人が Marketplace で 1 回だけ行う (以後は不要):

1. Marketplace → Develop → Build App → **Server-to-Server OAuth** → Create。 作った app を後で開く (scope を足すなど) =
   古い画面は右上の Develop / Manage、 新しい画面 (右上の「Try new experience」 が on) は左下の **Developers** から作った app の一覧へ (実測)
2. **Information** タブの必須欄 (Company Name / Developer Contact Name / Developer Contact Email)
3. **Scopes** タブ → Add Scopes。 ⚠️ 検索欄に製品名 (`meeting` 等) を入れると数百件出るので、
   **スコープ名をそのまま入れて 1 つずつ足す**。 使う操作の分だけ:
   - 部屋を作る・読む・消す (`create` / `show` / `list` / `delete`): `meeting:write:meeting:admin` /
     `meeting:read:meeting:admin` / `meeting:delete:meeting:admin`
   - 既存の部屋の設定を変える (`update`): `meeting:update:meeting:admin` (`write` だけでは PATCH が 4711 で止まる、 実測)
   - 自分と設定を読む (`whoami`): `user:read:user:admin` / `user:read:settings:admin`
   - 終わった会議の要約と文字起こし (`notes`): [#read-summary-and-transcript](#read-summary-and-transcript) の 5 つ
   - 自分の account で入った会議の一覧 (`joined`): `report:read:user:admin` ([#presence-from-process](#presence-from-process))
   - 足した scope が効いたかは `scopes` (token に付いている scope の一覧) で確かめる
   (旧体系の account なら `meeting:read:admin` / `meeting:write:admin` / `user:read:admin`)
4. **Activation** タブ → Activate
5. **App Credentials** タブの **Account ID / Client ID / Client Secret** の 3 値を保管する

token の取り方: `POST https://zoom.us/oauth/token` に
`grant_type=account_credentials&account_id=<Account ID>` を form で、 `Authorization: Basic
base64(client_id:client_secret)` を header で。 有効 1 時間。

⚠️ **Activate 前の token 要求は `invalid_client` + `"The app has been disabled by the developer"`**。
これは client_id が間違っているのではなく**アプリが未有効化**の合図で、 逆に言えば
**この文言が返れば Account ID と Client ID は正しい** (= 切り分けに使える)。

⚠️ 3 値は secret として扱う (= 平文で chat・issue・commit message に載せない)。 ⚠️ 足りない scope の操作は
`4711 Invalid access token, does not contain scopes:[...]` で止まる = **エラーが要る scope 名をそのまま教える**ので、
それを足す。 有効化済みの app なら、 足した直後に発行した token から効く (Activate し直す操作は要らなかった、 実測)。

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

道具 = `zoom-client.py notes <meeting_id> --date YYYY-MM-DD [--between HH:MM-HH:MM] [--out DIR]`
(その日の回を過去の回の一覧から探し、 要約の JSON と文字起こしの VTT を保存する)。 同じ部屋を 1 日に何度も使う
(個人部屋で授業と打ち合わせ、 など) なら `--between` で開始時刻を絞る = 別の会議の要約を拾わない。
終了値で分岐できる: 0 = 要約か文字起こしを取れた / 4 = 回はあるが両方とも無い (= 手元の録音を起こす合図、
[`audio-transcription.md#loop-runs-in-speech`](audio-transcription.md#loop-runs-in-speech)) / 5 = その日 (時間帯) の回が無い / 1 = API の失敗。
要る scope は読み取りの 5 つ (`meeting:read:list_past_instances:admin` / `meeting:read:past_meeting:admin` /
`meeting:read:summary:admin` / `meeting:read:list_summaries:admin` / `cloud_recording:read:meeting_transcript:admin`)。

- **「無い」 の根拠は 2 つの応答**: 過去の回の詳細 (`GET /past_meetings/{uuid}`) の `has_meeting_summary` と、
  文字起こし (`GET /meetings/{uuid}/transcript`) の code 3322。 通知メールの有無で判断しない
  (届かない設定もあるし、 メール検索の空振りは「無い」 の証明にならない)
- <a id="summary-mail-holds-agreements"></a>**相手と口頭で決めた段取りを探すときは、 会議の要約のメールも引く** — 通知のメールの本文に要約が丸ごと入っていて、 誰が何をするかの一覧 (Next steps) と日程の見込みが残る。
  差出人は Zoom の no-reply で本文は HTML だけ、 人の名前と話題で検索に掛かる (実測: 差出人と宛先で探しても出ず、 名前 + 話題で出た)。 AI の要約なので、 人の姓の取り違えや日付と曜日の不一致がある (実測) = 記録には「要約の読み・未確認」 と書く
- **ローカル録画のフォルダには要約も文字起こしも入らない** (入るのは音声・動画・設定 file だけ)。
  要約は Zoom 側にだけ残る
- <a id="transcript-speaker-labels"></a>**文字起こし (VTT) は参加者ごとの表示名つき** = ローカル録画は全員を 1 本に混ぜていて
  機械で話者を分けられない ([`audio-transcription.md#no-speaker-separation`](audio-transcription.md#no-speaker-separation)) が、
  こちらで誰の発言かを引ける (内容から推すより確か)。 使うときの 3 点 (実測):
  - **時刻は会議の開始から**で、 ローカル録画の開始からではない。 `notes --rec-start <録画を始めた現地の時刻 HH:MM:SS>`
    を付けると、 録画の時刻に直して話者ごとにまとめた `*_transcript-rec.txt` も書く
    (録画より前は負の時刻 = 録画を始める前の会話も読める)。 cue は実際の発話より 2〜3 秒遅れる = 切れ目は音で決める
  - <a id="rec-start-not-folder-name"></a>**Zoom の録画フォルダ名の時刻は、 録画の開始とは限らない** — 会議の開始の時刻が付いていて、
    録画は数分後に始まっていたことがある (実測: 約 3 分ずれた)。 録画を会議の終わりまで回したなら、 開始 = 会議の終わり − 録音の長さ
    (`ffprobe` の duration)。 書き出した `*_transcript-rec.txt` の目立つ語の時刻を、 ローカルの転写の同じ語の時刻と 1〜2 か所比べ、
    数秒以内で合うことを確かめてから使う (合わなければ差の分だけ `--rec-start` を直して取り直す)
  - **語は取り違える**: ある参加者の日本語の相づちを英語の文に起こした区間、 同音の語を別の語にした所があった。
    語はローカルの転写と突き合わせる (話者の手がかりと語の正しさは別)
  - **名前は表示名のまま** = 実名が入る。 共有の場所に写すときは通称に置き換える
- **要約が作られるのは、 その部屋の `auto_start_meeting_summary` が true の回か、 会議中に手で開始した回だけ**。
  個人部屋 (PMI) では false だった (実測)。 あとで要約が欲しい部屋は自動開始にしておく
  (`update <id> --set auto_start_meeting_summary=true`、 参加者に表示される点は上の ⚠️)。 自分の部屋の値は `show <id>` で読む
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

## <a id="join-from-notice"></a>通知メールの会議に本人を入れる (URL と passcode が別の行のとき)

「会議の Zoom を開いて」 と頼まれたら、 開催通知のメールから参加 URL を取って開く。
通知の URL に passcode が埋め込まれていない (`?pwd=` が無い) と、 Zoom は開いた後に passcode を聞いてくる。

- passcode は本文の別の行にある。 **chat に出さず、 クリップボードに入れて「聞かれたら貼る」 と伝える** (会話は他の端末からも読める)。
- 取り出した値の末尾の `\r` を落としてから入れる = text/plain の本文は CRLF で届く ([`mcp.md#gmail-body-crlf`](mcp.md#gmail-body-crlf)。 実測: 落とさずに入れて「passcode が違う」 と言われた)。 入れた後は中身を出さずに、 字の種類と長さだけを確かめる。
- 開くのは今の機械の画面 = 本人が別の端末にいるなら、 その端末でメールの URL から入ってもらう。

## <a id="presence-from-process"></a>会議に出ていたかを機械で残す — 会議中だけ動く process をその場で見る

研修の出席票や会議の出欠の届けは、 数週間後に「出たか」 を問う。 予定 (カレンダー) は残っても、 出たかは誰も残していない。

- **遡れる範囲は限られる**: Zoom の account の参加の記録 (下の report API) は、 今月を含む直近 6 か月の月までしか問えない
  (それより古い月は code 300、 実測)。 macOS の Zoom アプリの参加の履歴は暗号化された DB の中にあって読めず、 unified log は数日で消える (実測)。
  → 6 か月を越えて残すには、 **毎日取って自分の台帳に写す**
- **第一の出所 = account の参加の記録** (`GET /report/users/{userId}/meetings?type=pastJoined&from=…&to=…`、 道具 = `zoom-client.py joined --from … --to …`): 入室・退室・会議 id・
  主催者 (`host_id` を自分の id と比べれば自分 / 他人) が返る。 server 側の記録なので、 その account で入っていればブラウザ・スマホから入った分も残る
  - Server-to-Server OAuth app に `report:read:user:admin` が要る (無いと 4711)。 足した後は app の Scopes の一覧にその名前が並んでいることを
    確かめる = 並んでいないと token に入らない (実測: 1 回目は入っておらず、 足し直して一覧に出た後の token から効いた)。 token の応答の `scope` (`zoom-client.py scopes`) で確かめられる
  - `userId` に `me` は効かない (code 1001 「User does not exist: me」) = `GET /users/me` の `id` を使う。 1 回の問い合わせは 1 か月まで (月ごとに区切る)
  - 時刻は UTC で、 書式が混ざる (`join_time` / `leave_time` = `MM/DD/YYYY HH:MM` の分の精度、 `start_time` = `YYYY-MM-DD HH:MM:SS`)。
    同じ入室が 2 行返ることがある = 重複を除く
  - **他人が主催した会議は題も開始時刻も返らない** (入室・退室・会議 id だけ)。 その **会議 id は主催者の案内メールの会議 id と一致する** (実測) =
    メールを id で検索すれば、 どの会議かを同定できる
- **第二の出所 = 会議中だけ動く process `CptHost`** (別の account・サインインしないで入った分の網): Zoom アプリ (macOS) の補助 process
  `CptHost` は、 会議に入っている間だけ動く (実測: アプリは数日開いたままで、 `CptHost` は会議の間だけ動き、 account の記録の入室・退室と
  分の単位で一致した)。 `aomhost` は会議の中で何本も起きては消えるので区間の印にしない。 残るのは時間だけ (どの会議かは持たない)
  - 形: 機械ごとに常駐の見張り (短い間隔で `pgrep -x CptHost`、 launchd の KeepAlive) → 会議中の区間を machine-local の spool に足す →
    会議が終わったら未送の分を **新しい file 1 つ** にして repo に送る (書いた file は書き換えない = [`repo-history-growth.md#encrypted-ledgers`](repo-history-growth.md#encrypted-ledgers)。
    作業 tree を使わない一時 index の書き方 = 同 [`#slow-round-trip`](repo-history-growth.md#slow-round-trip))
  - スリープで見えなかった間は区間を切る (寝ていた時間を会議に数えない)。 見張りが会議中に止まったら、 次の起動で最後に見えた時刻で閉じる
  - **見張りは全部の機械、 突き合わせは 1 台**: 会議にはどの機械からも入るので、 無人の定期 job を 1 台だけで走らせる gate を見張りに掛けない
    ([`scheduled-tasks.md#per-recipient-notification-locus`](scheduled-tasks.md#per-recipient-notification-locus) と同じ「その機械の事実はその機械で」)
- **突き合わせ** (1 台が毎日、 予定と時刻で。 後から届いた分が入るよう直近の数日を毎回やり直す):
  - 他人が主催した会議 = 予定の時間に数分以上重なれば痕跡
  - **自分が主催した会議は、 予定の開始の前後 15 分に入ったものだけ** を痕跡に数える = 研究の Zoom を自分の部屋で開いたまま、 対面の会に
    重なることがある (実測)。 数えなかった重なりも記録には「数えない」 として残す
  - 見張りの区間が account の記録で説明できるとき (同じ時間に account の入室がある) は、 account の記録に任せる
  - どの出所も記録の無い時期 (見張りを入れる前、 account の記録の 6 か月より前) の予定は残さない (「痕跡なし」 と区別できない)
- **痕跡の限界**: 別の account でブラウザ・スマホから入った Zoom、 他の会議 service、 対面は残らない = **「痕跡なし」 は欠席ではない**。
  後で出欠が要る会 (研修・正式な会議) で痕跡が無いものだけを、 1 日分まとめて本人に 1 回聞き、 答えは本人の言葉のまま残す
