<!-- doc-meta
when: macOS Calendar.app 上の iCloud (または CalDAV / local) 所有 calendar に AppleScript / osascript で event を書き込もうとする前 + Google Calendar API から見て read-only (webcal 購読) な calendar に write する経路を探しているとき + API で Google Calendar に書いた予定が Mac の Calendar.app に出ない時 (#google-to-calendar-app-sync-check) + 予定にゲスト (参加者) を足す・繰り返し予定を消す時 (#eventkit-add-attendees / #applescript-recurring-delete) + Android (DAVx5) で作った予定が Mac で消えない・Mac にだけ出ない時 (#android-davx5-organizer-invitation) + 繰り返し予定の 1 回だけをずらす・飛ばす時 / 重なった繰り返しの写しを消す時 (#recurring-one-occurrence)
category: macos
summary: macOS Calendar.app の calendar に AppleScript (osascript) で event を作る universal recipe。 `tell application "Calendar" ... make new event with properties {summary, location, description, start date, end date}` で書ける。 property 名は英語 literal (日本語は syntax error)、 calendar name は Calendar.app が list する literal string (全角括弧 / 空白 込み)、 iCloud 側の write は数分〜数十分で iCloud sync 経由で Google Calendar の webcal 購読 view (`@import.calendar.google.com`) に反映、 他 iCloud 端末には即時反映。 TCC = Terminal.app / iTerm 側に Calendar 権限を付与、 osascript 経由も同 grant で通る。 verify は `every event whose summary contains "..."` で件数 + start date 確認。 「MCP から write 不可能な calendar (= webcal import は Google 側 read-only)」 の唯一の Claude-executable 経路
-->

# macOS Calendar.app に AppleScript で event を書き込む recipe <a id="applescript-calendar-event-write"></a>

macOS `Calendar.app` の calendar に **AppleScript 経由で event を write する universal recipe** の SoT。 Google Calendar MCP から書けない calendar (= iCloud 所有 + webcal 購読で Google 側 view が read-only、 owner は iCloud 側) への write は本 recipe が唯一の Claude-executable 経路。

## <a id="tldr"></a>TL;DR

```applescript
tell application "Calendar"
  set targetCal to first calendar whose name is "<literal calendar name>"
  set startDate to (current date)
  set year of startDate to 2026
  set month of startDate to 7
  set day of startDate to 11
  set hours of startDate to 16
  set minutes of startDate to 0
  set seconds of startDate to 0
  set endDate to startDate + (90 * minutes)
  tell targetCal
    set newEv to make new event with properties {summary:"...", location:"...", description:"...", start date:startDate, end date:endDate}
    return uid of newEv
  end tell
end tell
```

- `osascript /path/to/script.applescript` で実行、 rc=0 + `uid` (RFC 5545 UID) が stdout に出れば成功
- 複数 event は AppleScript の `repeat with d in dateList` loop で 1 script にまとめられる (= 1 event 1 osascript 起動より速い)

## <a id="property-names"></a>property 名は英語 literal

`make new event with properties {...}` の key は **英語のみ**。 日本語 property (「件名」「場所」 等) は syntax error。

| 用途 | property 名 | 型 |
|---|---|---|
| タイトル | `summary` | text |
| 場所 | `location` | text |
| メモ / 詳細 | `description` | text |
| 開始 | `start date` | date (AppleScript date object) |
| 終了 | `end date` | date |
| ID (return only) | `uid` | text (RFC 5545 UID) |
| 終日 | `allday event` | boolean |
| URL | `url` | text |

⚠️ `start date` / `end date` は **space 込みの 2 語**が 1 key (property 名にスペース含み)、 quote 不要。 AppleScript date object は `(current date)` を base に `set year of X to ...` 等で組み立てるのが最も安定 (直接 `date "2026/7/11 16:00:00"` は locale 依存で fragile)。

## <a id="calendar-name-literal-match"></a>calendar name は Calendar.app が list する literal

```bash
osascript -e 'tell application "Calendar" to name of calendars'
```

が返す string を **literal 一致** で書く (`first calendar whose name is "..."`)。

- **全角括弧 `（）` も literal**: 例えば iCloud 側で `欣直（カレンダー専用）` という名前なら、 Google Calendar 側の表示名が `欣直` に短縮されていても script では iCloud 実名を使う (= Google 側の表示名は購読 view の rename、 iCloud 上の owner name とは別)
- **前後 space / trailing 記号も literal**
- 存在しない name を渡すと `AppleScript error -1728 (Can't get first calendar whose name is ...)` で fail

## <a id="tcc-permission"></a>TCC (Calendar 権限)

- Calendar 権限は **呼び出し元 process の bundle** に付与される。 Terminal.app / iTerm から `osascript` 実行なら Terminal/iTerm の grant で通る
- Claude.app のバックグラウンドから直接 `osascript` を呼ぶと **prompt が表示されず silent-fail する** ことがある — Terminal 経由での実行、 または `System Settings → Privacy & Security → Calendar` で対象 app に手動 grant
- **`tccutil reset Calendar` は全 app の grant を消す destructive command** → 実行禁止 (= 一般則は shell-env.md macOS deny rules)

## <a id="verify-pattern"></a>verify pattern

write 後に「本当に入ったか」 を osascript で読み返して確認:

```bash
osascript -e 'tell application "Calendar"
  tell calendar "<literal name>"
    set matches to every event whose summary contains "<distinctive key>"
    set out to ""
    repeat with ev in matches
      set out to out & (summary of ev) & " | " & (start date of ev as string) & linefeed
    end repeat
    return out
  end tell
end tell'
```

件数 + start date + summary を確認 (locale の日付書式で返る)。 重複 (= 既存 event との衝突) の検出にも同じ query が使える。

## <a id="icloud-google-sync-lag"></a>iCloud → Google Calendar 同期は数分〜数十分 lag

iCloud 所有 calendar を Google Calendar に **webcal 購読** させている場合、 Google 側 (`@import.calendar.google.com`) への反映は **webcal poll 間隔 (数分〜数十分)** に律速。 一方:

- **Calendar.app / iPhone Calendar / 他 iCloud 端末**: iCloud sync で即時反映 (通常 1 分以内)
- **Google Calendar view**: 遅延あり (Google が webcal を再取得するタイミングまで表示されない)

∴ verify は Calendar.app 側 (osascript) で行い、 Google view の反映は待つ。 「Google に見えない = 未書き込み」 とは限らない (= §3 単一情報源 null 結論飛躍 の calendar domain 変種)。

## <a id="google-to-calendar-app-sync-check"></a>逆向き: API で Google Calendar に書いた予定が Mac の Calendar.app に出ない

API / MCP で Google 所有 calendar に書いた予定を、 user は Mac の Calendar.app (Google アカウントを CalDAV で登録) で見ることが多い。 **API の書き込み成功は「user の画面に出た」 ではない**。 Calendar.app 側のアカウントが同期に失敗し続けていると、 予定もその通知 (Calendar.app が出す alarm) も user に届かないまま、 どこにもエラーが出ない (実測)。

**切り分け (全部 read-only)**:

1. **Calendar.app に予定があるか** — §verify pattern の osascript を、 見ているはずの calendar 名で打つ。 ⚠️ `every calendar` を全部回すと遅く (数十秒〜timeout)、 名前で 1 つに絞る。
2. **アカウントの同期状態** — Calendar.app の DB を read-only で開き、 アカウント (Store) ごとの最後の同期と error を見る:

   ```bash
   DB="$HOME/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb"
   [ -e "$DB" ] || DB="$HOME/Library/Calendars/Calendar.sqlitedb"   # macOS 13 の置き場所 (実測)
   sqlite3 "file:$DB?mode=ro" "select ROWID, name, error_id,
     datetime(last_sync_start+978307200,'unixepoch','localtime'),
     round(last_sync_end-last_sync_start,3) from Store where type=2;"
   ```

   時刻は 2001-01-01 起点の秒 (`+978307200` で Unix 時刻)。 **`error_id` が 0 でなく、 同期の所要が ~0 秒** = そのアカウントは同期を試みるたびに即失敗している。 正常なアカウントは同じ時刻に error 0 で数百 ms〜秒かかる。 error の中身は `Error` 表の `user_info` (NSKeyedArchiver の plist)。
3. **予定の行が DB にあるか** — `CalendarItem` を `summary like '%<distinctive key>%'` で引く (1 と独立な 2 本目の証拠)。

**直し方** = そのアカウントの再サインイン (システム設定 → インターネットアカウント、 または Calendar.app のツールバーの ⚠ から)。 **パスワードを扱うので user の操作**。 Claude は切り分けの結果と場所を 1 行で渡す。

**機械で見る** = `scripts/check-calendar-app-sync.py` (2 と、 Calendar.app が使う CalDAV の子アカウントの**親** 〔Google 等〕 の認証を読む。 子は親が切れても認証済みのままなので親まで辿る。 `--surface` は異常時だけ、 flag なしで全アカウントの表)。

**やってはいけない読み方**:

- `osascript -e 'tell application "Calendar" to reload calendars'` の **rc=0 は同期の成功を意味しない** (失敗するアカウントは reload しても失敗する)。
- 反映を poll して待つだけにしない — 待つ前に 2 の error を見る (失敗中なら何分待っても来ない)。
- EventKit で書き出す自作 tool が出力を **cwd 相対の file** に書き、 書けない時に黙る作りだと、 別の cwd から回した poll は古い file を読み続けて「まだ無い」 と誤判定する。 **tool の stdout を読む**か、 出力 path を固定する。
- DB を開けるかは呼び出し元 process の権限次第 (TCC)。 開けなかったことを「アカウントは正常」 と読まない。

<a id="api-vs-eventkit-compare"></a>**DB を読めない機械では、 結果を突き合わせて代える** — DB を読むにはフルディスクアクセスが要り、 agent の shell を起動する app に付けると、 その shell の全コマンドがメール・メッセージ・閲覧履歴まで読めるようになる。 同期の検査のためだけに付けない方がよい。 代わりに、 API で読んだ予定 (今から N 日先まで) と、 EventKit で書き出した Calendar.app の予定 (同じ calendar) を (日付, 開始時刻, 題名) で突き合わせる。 API にあって Mac に無い予定 (最終更新から 30 分ほど経ったもの = 同期の遅れを除く) があれば同期が止まっている疑い、 Mac にあって API に無い予定は消した・動かした予定が残っている疑い。 EventKit の書き出しは「今より後に終わる予定」 から始まることが多いので、 API の側も同じ窓で読む。 書き出しの CLI が agent の shell から拒否されるときは [`macos-notification-db.md#tcc-disclaim-child`](macos-notification-db.md#tcc-disclaim-child) (実測: フルディスクアクセスなしで照合できた)。 アカウントの認証切れそのものは見えない (結果だけを見る) ので、 DB を読める機械では上の 2 を正本にする。

## <a id="reminders-not-enforced-by-mcp-hooks"></a>reminder / alarm は AppleScript で個別に付与する

MCP `create_event` を対象にした reminder 強制 hook (= layer 3 の calendar-reminder-guard.sh 等) は **AppleScript 経路を catch しない** — matcher が MCP tool 名にしか反応しないため。 AppleScript で reminder が欲しい event は script 内で明示:

```applescript
tell newEv
  make new sound alarm at end of sound alarms with properties {trigger interval:-15}
end tell
```

`trigger interval` の単位は分、 負値 = 開始前。 sound alarm / display alarm / mail alarm がある (`type` は別 property)。

## <a id="applescript-recurring-delete"></a>AppleScript の `delete` は繰り返し予定だと 1 回分しか消さない

`delete e` (e = `every event ... whose uid is ...` で取った繰り返し予定) は、 系列全体でなく**選ばれた回だけ**を除外日 (EXDATE) にして終わる。 戻り値も error も無いので消えたように見え、 次の週から同じ予定が出続ける (実測)。 系列ごと消すのは EventKit で、 系列の本体を `span = futureEvents` で消す:

```javascript
// osascript -l JavaScript
ObjC.import('EventKit');
var store = $.EKEventStore.alloc.init;
var item = store.calendarItemWithIdentifier('<AppleScript の uid と同じ値>');
store.removeEventSpanCommitError(item, 1 /* EKSpanFutureEvents */, true, null);
```

⚠️ 大きい calendar で `whose uid is` を回すと 2 分を超える (= 消す対象が分かっているなら最初から EventKit の id で引く)。

## <a id="eventkit-add-attendees"></a>ゲスト (参加者) つきの予定をプログラムで作る

AppleScript の attendee は**読み取り専用** (`iCal.sdef` の attendee の property が全部 `access="r"`)、 EventKit の公開 API にも参加者を足す method は無い。 画面操作に降りる前に、 EventKit の**内部 method** で足す (Calendar.app 自身が招待の作成に使うもの、 macOS 26 で実測):

1. `-[EKCalendarItem addOrganizerAndSelfAttendeeForNewInvitationInCalendar:force:]` (calendar, YES) = 主催者を本人にし、 本人の出席を入れる。 ⚠️ 引数なしの `addOrganizerAndSelfAttendeeForNewInvitation` は主催者を入れない (organizer が nil のまま)
2. `+[EKAttendee attendeeWithName:emailAddress:]` (name には nil を渡す) → `-[EKCalendarItem addAttendee:]`
3. `save(_:span:commit:)`

```swift
// swiftc で build (Command Line Tools で通る)。 BOOL 引数は perform では渡せないので IMP を直に呼ぶ
let sel = Selector(("addOrganizerAndSelfAttendeeForNewInvitationInCalendar:force:"))
typealias F = @convention(c) (AnyObject, Selector, AnyObject, Bool) -> Void
let f = unsafeBitCast(method_getImplementation(class_getInstanceMethod(type(of: ev), sel)!), to: F.self)
f(ev, sel, ev.calendar, true)
let a = (NSClassFromString("EKAttendee")! as AnyObject)
  .perform(Selector(("attendeeWithName:emailAddress:")), with: nil, with: "guest@example.org")!.takeUnretainedValue()
_ = ev.perform(Selector(("addAttendee:")), with: a)
try store.save(ev, span: .thisEvent, commit: true)
```

- ⚠️ **既存の繰り返し予定に足して保存すると span が何でも「An invalid span was specified」 (EKErrorDomain code 13)** = 新しい `EKEvent` に全部 (繰り返し・場所・通知・参加者) を載せて 1 回で保存し、 古い方を [#applescript-recurring-delete](#applescript-recurring-delete) の手で消す。 単発の予定は既存のものに足して `thisEvent` で保存が通る
- 保存前に `organizer` と `attendees` を print して確かめる (dry run = 保存せず終える)。 結果は Calendar.app の画面で招待した予定と同じ形 (主催者 = 本人、 本人の出席 = 承諾、 ゲスト = 返事待ち)
- ⚠️ **iCloud など server 側で招待を扱う calendar では、 保存した時点で server がゲストに招待メールを送る** = 外部への送信。 送るかどうかを owner に聞いてから保存する
- ⚠️ **既存の予定を作り直すときは、 参加者も含めて元の field を全部移す**。 参加者を外すと送信は避けられるが、 予定の中身を owner に断らず変えることになる。 移せない field があるなら、 作り直す前に owner に聞く

## <a id="android-davx5-organizer-invitation"></a>Android (DAVx5) でゲストを入れて作った予定が、 Mac では「他人からの招待」 になる

**症状**: Android で作った予定のうち、 Mac で消したはずのものが Android には残る / Mac にだけ出ない。 Mac の同期は error 0 で、 予定は Mac の DB にも server にも在る。

**機構**:

1. ゲストのいる予定には主催者 (ORGANIZER) が必須 (iCalendar の決まり)。 Android のカレンダーには「この account での自分の address」 の欄が無く、 **DAVx5 の account 名がそのまま主催者になる** ([DAVx5 manual](https://manual.davx5.com/accounts_collections.html))。 account 名を「iCloud」 のような address でない名前にすると、 主催者は `mailto:iCloud` になる
2. Mac (と iCloud.com) は主催者を本人と認めないので、 自分の予定を**他人からの招待**として扱う。 ゲストのいない予定は主催者が書かれないので起きない
3. **招待された予定は、 Mac / iCloud.com で消しても server からは消えず「不参加」 になるだけ** (Mac は「通知して削除 / 通知せずに削除」 を聞く。 [iCloud.com の help](https://support.apple.com/en-ae/guide/icloud/mmfbbb4470/icloud) も「招待された予定を消す = 不参加にする」)。 本人の address がゲストに入っていてその返事が不参加だと、 Mac はその予定を隠す
4. 隠す・隠さないの切替 = Calendar.app の**メニュー「表示」 →「欠席する予定を表示」** (`defaults read com.apple.iCal ShowDeclinedEvents`)。 ⚠️ 設定 →「詳細」 の「不参加者を表示」 は別の項目

**見つけ方** (read-only):

```sql
-- ~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb を mode=ro で
SELECT ci.summary, i.address AS organizer,
       (SELECT p.status FROM Participant p WHERE p.ROWID = ci.self_attendee_id) AS self_status
FROM CalendarItem ci
JOIN Participant o ON o.ROWID = ci.organizer_id
JOIN Identity i ON i.ROWID = o.identity_id
WHERE i.address = 'mailto:<DAVx5 の account 名>';
-- self_status = 2 が「不参加」 (= Mac で隠れている)。 OccurrenceCache に 1 件も無いことでも分かる
```

Android 製の予定は UID が小文字の UUID (Apple 製は大文字) なので、 出所の見分けにも使える。

**直し方**:

- **DAVx5 の account 名を、 server が本人と認める address (iCloud なら Apple ID の address) にする** = 以後に作る予定の主催者が本人になる。 ⚠️ 既存の予定の主催者は変わらない。 ⚠️ **その結果、 Android に取り込み済みの予定が編集できなくなる**: Etar は「予定の主催者 (ORGANIZER) = カレンダーの持ち主 (OWNER_ACCOUNT)」 の予定にだけ編集を出し (`EventInfoFragment`: `mCanModifyEvent = mCanModifyCalendar && mIsOrganizer`)、 DAVx5 は名前の変更でカレンダーの持ち主だけを新しい名前にする (DAVx5 の issue #1716 / #1751)。 → 名前を変えたら、 DAVx5 で各カレンダーのチェックを外して同期 → 戻して同期 (= 取り込み直し。 先に「今すぐ同期」 で未送信の変更を送る) まで行う (実測: 取り込み直しで、 古い予定も新規に作った予定も編集が戻った)。 ⚠️ 主催者が本人になると、 Android でゲストを入れた予定に server が招待メールを送るようになりうる
- 既存の予定の主催者は Mac・iCloud.com からは書き換えられない = 先の回が残るものだけ作り直す ([#eventkit-add-attendees](#eventkit-add-attendees)、 参加者も移す)。 **古い方は Android 側で消す** (Mac で消すとまた不参加になるだけ)。 過去の回しか無いものは表示に影響しないので、 作り直さずにそのまま置く

## <a id="recurring-one-occurrence"></a>繰り返し予定の 1 回だけをずらす・飛ばす (EventKit の道具)

道具 = [`scripts/calendar-app-occurrence.py`](../scripts/calendar-app-occurrence.py) (`list` / `move` / `skip` / `remove-series`、 既定 dry-run、 `--apply` で書いて読み直す)。 中身は osascript の JXA から EventKit を呼ぶだけなので build は要らない。

- **span の意味**: `この予定のみ` (EKSpanThisEvent = 0) = 元の系列に、 その回だけを変えた印 (RECURRENCE-ID の回) が付くだけで、 系列は変わらない。 `これ以降` (EKSpanFutureEvents = 1) = その回から先。 **1 回だけの変更は必ず `この予定のみ`**
- ⚠️ **系列を丸ごと消すときは、 最初に見えている回でなく系列の本体に対して `これ以降` を当てる** (`calendarItemsWithExternalIdentifier`)。 最初の回が個別に変えた回 (id が `<uid>/RID=…` の別物) だったり検索の窓より前だったりすると、 見えている最初の回から先だけが消え、 系列は途中で切れて残る (実測: 道具の dry-run で気づいた)
- **Android (Etar) で予定を開いて「編集」 が出ず「複製」 しか選べないときは、 複製で代わりにしない** (実測): 複製は同じ繰り返しの写しをもう 1 本作るだけなので、 元は変わらないまま同じ予定が重なる。 この状態の原因 = DAVx5 の account 名の変更 (上の [#android-davx5-organizer-invitation](#android-davx5-organizer-invitation) の「直し方」 の ⚠️)、 直し方 = 取り込み直し。 編集が出る状態なら、 Android でも「この予定のみ」 を選べば 1 回だけ変えられる。 Mac からは Calendar.app か本道具で
- **他の端末への反映**: Mac からの変更は iCloud にすぐ届くが、 **iCloud は DAVx5 に変更を知らせない** = Android は DAVx5 の次の同期まで古いまま (実測: 「二重のまま」 に見えた後、 同期で消えた)。 急ぐなら DAVx5 の「今すぐ同期」
- **重なりの診断** (read-only): Calendar.app の DB (`~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb`、 `mode=ro`) の `CalendarItem` を summary で引き、 `Recurrence.specifier` (曜日、 例 `D=0MO,0SA`) と `end_date` (空 = 終わらない) を見る。 Android 製は UID が小文字の UUID。 ⚠️ Google の webcal 購読の写しは数時間遅れるので、 直後の診断には使えない
- ⚠️ JXA で NSError** を受けるときは `$()` を渡す (`Ref()` を渡すと osascript が segfault した、 macOS 26 実測)

## <a id="use-cases"></a>使い所

- **webcal 購読で Google 側 read-only な iCloud calendar への write** (= 主用途): Google Calendar MCP は Google 側からしか書けない、 iCloud owner の calendar には API がない
- **local (このマシンだけの) calendar への write**: iCloud sync させたくない private calendar 等
- **CalDAV 3rd party calendar への write**: Calendar.app が subscribe しているなら AppleScript から write 可能

Google 所有 calendar (= 自分の primary / group calendar / 他 Google account share) は **Calendar MCP `create_event`** を使う (= reminder hook 発火・sync 遅延なし)。 AppleScript は使わない。
