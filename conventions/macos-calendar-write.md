<!-- doc-meta
when: macOS Calendar.app 上の iCloud (または CalDAV / local) 所有 calendar に AppleScript / osascript で event を書き込もうとする前 + Google Calendar API から見て read-only (webcal 購読) な calendar に write する経路を探しているとき
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

## <a id="reminders-not-enforced-by-mcp-hooks"></a>reminder / alarm は AppleScript で個別に付与する

MCP `create_event` を対象にした reminder 強制 hook (= layer 3 の calendar-reminder-guard.sh 等) は **AppleScript 経路を catch しない** — matcher が MCP tool 名にしか反応しないため。 AppleScript で reminder が欲しい event は script 内で明示:

```applescript
tell newEv
  make new sound alarm at end of sound alarms with properties {trigger interval:-15}
end tell
```

`trigger interval` の単位は分、 負値 = 開始前。 sound alarm / display alarm / mail alarm がある (`type` は別 property)。

## <a id="use-cases"></a>使い所

- **webcal 購読で Google 側 read-only な iCloud calendar への write** (= 主用途): Google Calendar MCP は Google 側からしか書けない、 iCloud owner の calendar には API がない
- **local (このマシンだけの) calendar への write**: iCloud sync させたくない private calendar 等
- **CalDAV 3rd party calendar への write**: Calendar.app が subscribe しているなら AppleScript から write 可能

Google 所有 calendar (= 自分の primary / group calendar / 他 Google account share) は **Calendar MCP `create_event`** を使う (= reminder hook 発火・sync 遅延なし)。 AppleScript は使わない。
