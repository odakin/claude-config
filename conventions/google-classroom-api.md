<!-- doc-meta
when: Google Classroom をプログラムから操作するとき (クラスの作成・名簿からの招待・お知らせや課題の投稿・提出の読み取り) + 学期はじめにクラスを用意するとき + API で作った課題の設定が画面で変えられないと気づいたとき
category: infra
summary: Classroom API の実測済み挙動 = 先生はクラスを ACTIVE で直接作れる / 学生を直接追加できず招待のみ (全員に mail) / 教師は別クラスで見えている数値 userId で招待すると住所の推測が要らない / API で作った課題は期限後締切を画面で ON にできないが API で作ったクラスに画面で作った課題なら ON にできる / お知らせの Drive 添付は共有設定不要 / ヘッダー画像は API に項目が無い / scope ごとの読める・書ける範囲
-->
# Google Classroom API の実測済み挙動

教員アカウントで Classroom API (v1) を叩くときに、 docs だけからは読み取りにくい挙動の集。 接続の setup (OAuth client・token の置き場) は [`google-api-direct-access.md`](google-api-direct-access.md)、 URL を書くときは [`google-url.md`](google-url.md)。 「実測」 と書いた項目は Workspace for Education の教員アカウント 1 件で確かめたもの。 印の無い項目は API の仕様から書いたもので未実測。 組織の管理設定で変わりうる箇所は ⚠️ を付けた。

## <a id="scopes"></a>scope と、 それで何ができるか

| scope | 読める / できる | 足りないと起きること |
|---|---|---|
| `classroom.courses.readonly` | クラス一覧・詳細 | 作成・変更はできない (= 「作れない」 の原因はたいていこれ。 実測 = 作成の tool を持たない読むだけの構成で止まった) |
| `classroom.courses` | クラスの作成・変更 (名前・section・状態 = ARCHIVED 等) | — |
| `classroom.rosters.readonly` | 学生・教師の一覧 (userId と氏名、 実測) | 招待はできない |
| `classroom.rosters` | 招待の作成 | — |
| `classroom.profile.emails` | 一覧に mail address が付く | 無いと userId と氏名だけ (address で突き合わせられない、 実測) |
| `classroom.announcements` | お知らせの読み書き | — |
| `classroom.coursework.students` | 課題の作成・提出の読み書き | — |

scope を足したら token を取り直す (consent を 1 回)。 同じ OAuth client を使う他の道具 (提出の取り込み等) は scope が広がっても壊れない。

## <a id="create-course"></a>クラスの作成

- `courses.create` に `ownerId: "me"` と `courseState: "ACTIVE"` を渡すと、 そのまま ACTIVE で返る (実測)。 ⚠️ 組織によっては PROVISIONED で返る → 所有者本人なら `courses.patch` (`updateMask: courseState`) で ACTIVE にできる。 両方を扱う実装にしておく
- 作った直後は誰にも見えない (学生は参加コードか招待で入る)。 返り値の `enrollmentCode` が参加コード
- **ヘッダー画像 (テーマ) は API に項目が無い** (実測 = `courses.get` の返す field に theme / photo が無い) = 画面の「カスタマイズ → 写真をアップロード」 で貼る。 画像は横長 4:1 (例 1600×400) で、 左下にクラス名が白字で重なるので左下は暗く・模様を少なくすると読める

## <a id="class-calendar"></a>クラスのカレンダーに授業の予定を入れる

- クラスを作ると、 そのクラス用の Google カレンダーが自動で作られる (`courses.get` の `calendarId` = `c_classroom…@group.calendar.google.com`、 実測)。 先生のアカウントは owner。 課題の期限はここに自動で載るが、 **授業の時間そのものは載らない** → 毎週の予定を 1 件入れておくと、 学生の Google カレンダーに授業が並ぶ
- 形 = 毎週の繰り返し 1 件 (`RRULE:FREQ=WEEKLY;UNTIL=<最終回の開始 (UTC)>;BYDAY=<曜日>`) + 授業の無い日を `EXDATE;TZID=<地域>:<日付T時刻>,...` で除く (休暇・休講日・オンデマンド週・補講日・自分の休講)。 除く日は学年暦から拾う
- クラスのカレンダーは timeZone が UTC で作られる (実測) → event 側に地域の timeZone を明示する。 `UNTIL` は UTC、 `EXDATE` は TZID 付きの現地時刻で書く
- 入れたら `singleEvents=true` で展開して、 回数と日付の並びを学年暦と照合する (EXDATE の書き損じは展開しないと見えない)
- 補講のように日付が確定していない回は入れず、 確定してから単発で足す

## <a id="late-submission-lock"></a>API で作った課題と「期限後に提出を締め切る」

- API で作った課題 (courseWork) には `associatedWithDeveloper: true` が永続的に付き、 画面の「期限後に提出を締め切る」 が灰色になる (「サードパーティ製ツールからの提出は締め切ることができません」)。 DRAFT で作っても外れない = **期限後の締切が要る課題は画面で作る**
- これは課題単位の制限で、 **API で作ったクラスそのものには及ばない**: API で作ったクラスの中で画面から作った課題は、 締切を ON にできる (実測)。 クラスを API で用意して、 毎週の課題は画面で作る、 という分業が成り立つ
- ⚠️ 未検証: 同じ課題の「生徒はクラスメイトに返信できます」 も同じ制限を受けるか (画面で投稿するときに同じ文言が出るかを見れば分かる)
- API の既定値が画面の既定値と違う項目: `submissionModificationMode` は API の既定が `MODIFIABLE_UNTIL_TURNED_IN` (提出後は編集不可)、 画面の既定は「生徒は解答を編集できます」 = `MODIFIABLE`。 画面と同じにしたいなら明示する
- 締切の要らない課題 (配点つきの任意レポート・下書き・一括投稿) は API で作ってよい

## <a id="invite-members"></a>メンバーの追加 = 招待だけ

- **先生は学生を直接追加できない**: `courses.students.create` は管理者か、 参加コードを持つ本人の自己登録用。 先生からは `invitations.create` (`role: STUDENT | TEACHER`) で招待する
- 招待すると **Google が招待した全員に mail を出す** = 取り消せない外向きの送信。 対象と人数を人に見せて OK をもらってから送る。 実装は既定を dry-run にする
- 招待を受け入れた時点でクラスに入る。 送った直後でもすぐ参加する人がいるので (実測)、 検算は「参加済み + 承諾待ちの招待 (`invitations.list`) = 招待した数」 で見る
- 招待は 1 人 1 回の API 呼び出しで、 1 回に 1 秒強かかる (実測) = 1 クラス分を逐次で送ると分単位になる → 数本を並列にする (結果は入力順に並べ、 失敗と「済み」 を集計して返す)
- すでに招待済み・参加済みの人への招待は `ALREADY_EXISTS` で返る (未実測) = 実装はこれを失敗でなく「済み」 として数える
- **`userId` は mail address でも数値の userId でもよい** (実測): 1 人が複数の address (学内の複数ドメイン等) を持つと、 どれが Classroom のアカウントか推測になる。 以前のクラスの教師一覧 (`courses.teachers.list`) に出ている数値 userId で招待すれば、 同じアカウントに確実に届く
- 名簿 (教務システムの CSV 等) の address で学生を一括招待するのが学期はじめの定形。 旧課程・新課程で時間割番号や科目名が分かれる科目は、 名簿を科目名で絞ると片方が落ちる → コマ (曜日・時限) で束ねる

## <a id="announcement-attachments"></a>お知らせにファイルを添付する

- `courses.announcements.create` の `materials` に `{driveFile: {driveFile: {id}, shareMode: "VIEW"}}` を入れる (実測)。 file は先生本人の Drive に上げておくだけでよく、 **共有設定は要らない** (Classroom が受講者に閲覧権限を付ける)
- Drive への upload に使う token (例: `drive.file` scope の別 token) と Classroom の token が別でも、 同じアカウントなら添付できる (実測)
- 添付の代わりに Dropbox 等の共有リンクを本文に貼る運用もある。 添付は Classroom の中で開けて、 受講者以外には見えない
- お知らせも投稿した瞬間にクラス全員に見える: 文面と添付を人に見せてから投稿し、 投稿後は `announcements.get` で読み戻して本文と添付を照合する (貼り付けで文が落ちる事故の検出 = [`paste-destined-plain-text.md`](paste-destined-plain-text.md))

## <a id="read-submissions"></a>提出の読み取り

- 短答課題の提出は `studentSubmissions.list`。 締切前は未提出の submission が `CREATED` で並ぶだけ = 取り込み件数 0 を「提出が無い」 と読まない ([`debugging-discipline.md`](debugging-discipline.md) の dedup の話と同じ)
- `assignedGrade` は返却 (`RETURNED`) 後にだけ入る。 返却前の採点は `draftGrade`
- 画面の「ファイルを開いていない」 は API に無い

## 実装の置き場所

参照実装 (MCP server + CLI: クラス作成・変更・招待・添付つきお知らせ・提出の取り込み) は owner の private な MCP 設定 repo (`gmail-mcp-config`) にある。 node の依存と MCP の登録がその repo に結びついているため、 engine はまだ上げていない (もう 1 つ使う場所が出たら層1 に移す)。 上の挙動はその実装で確かめたもの。
