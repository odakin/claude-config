<!-- doc-meta
when: Claude for Mac (desktop / Code タブ) の通知音が鳴らない・通知が来ないとき + macOS の通知が全般に鳴らない原因を調べるとき + 集中モード (おやすみモード) の設定画面を user に案内する前
category: macos
summary: Claude for Mac の通知が鳴らない原因を 5 層で切り分ける (アプリ仕様 = 完了通知は常に無音・表示中の session は通知なし / アプリ設定 notificationSound / macOS 通知許可 / 音量 / 集中モード)。 集中モードの実状態は unified log で読める (設定 DB は TCC で読めない、 zsh では /usr/bin/log と書く)。 「デバイス間で共有」 + 使わなくなった iPhone でおやすみモードが終わらない罠と、 macOS 26 の集中モード設定画面の読み方。 一発診断 = scripts/claude-app-notify-diagnose.py、 完了時にも鳴らすなら opt-in の Stop hook = hooks/turn-complete-sound-nudge.sh
-->
# Claude for Mac の通知音 — 鳴らないときの切り分け

「Claude アプリの通知音が一度も鳴らない」 は、 Claude の設定とは限らず 5 つの層のどこでも起きる。 上から順に見る。 全層の一発診断 (read-only) = [`scripts/claude-app-notify-diagnose.py`](../scripts/claude-app-notify-diagnose.py)。

## <a id="notification-layers"></a>切り分けの順序 (5 層)

| 層 | 見るもの | 止まっているときの印 |
|---|---|---|
| 1. アプリの仕様 | 何の通知か / その session を見ていたか | 完了通知・表示中の session = 仕様で鳴らない ([#app-notification-model](#app-notification-model)) |
| 2. アプリの設定 | `claude_desktop_config.json` の `preferences.notificationSound` | `"none"` |
| 3. macOS の通知許可 | `com.apple.ncprefs` の flags / `swift.log` の `Authorization granted` | 許可 bit・サウンド bit が落ちている / `false` ([#macos-notification-prefs](#macos-notification-prefs)) |
| 4. 音量 | `osascript -e 'get volume settings'` | `output muted:true` / `alert volume:0` |
| 5. 集中モード | unified log | Claude の通知が `interruptionSuppression: delay delivery` ([#focus-dnd-unified-log](#focus-dnd-unified-log)) |

実例 (2026-09): 2〜4 は全部「鳴らす」 側だったのに、 5 のおやすみモードが約 2 ヶ月オンのままで全通知が保留されていた ([#focus-shared-retired-device](#focus-shared-retired-device))。 設定値だけ見て「正常」 と結論しない — 5 は設定でなく**状態**なので log を読むまで分からない。

## <a id="app-notification-model"></a>Claude アプリ側の仕様 (app.asar の読解、 版に依存)

観測版 = Claude for Mac 1.52386.3 (2026-09)。 版が変わったら下の「読み直し方」 で確かめる。

- **設定 key**: `~/Library/Application Support/Claude/claude_desktop_config.json` の `preferences.notificationSound` = `"system"` (鳴らす) | `"none"`。 **key が無ければ既定 `"system"`**。 同じ場所に `notificationLevels` (permission / idle / question ごとの banner・badge) と `dockBounceEnabled`。
- **鳴るのは 許可要求 / 質問 (AskUserQuestion) / 入力待ち だけ**。 **タスク完了 (`turn_complete` =「Claude finished a task」) は silent 固定 + `interruptionLevel: passive`** で、 設定では変えられない (remote session の完了も同じ)。
- 1.5 秒以内の連続通知は 2 通目以降を無音にする (chime の重複抑制)。
- **アプリの window が前面かつその session を表示中なら、 許可要求の通知自体を出さない** (`viewing_session` で抑制)。 「見ている間は鳴らない」 は仕様。 ほかの抑制理由 = `level_off` (notificationLevels で banner も badge も off) / `banners_disabled`。
- **許可状態**: `~/Library/Logs/Claude/swift.log` の `[Notifications] … Authorization granted: true|false` (アプリ起動ごとに 1 行)。 `main.log` には個々の通知の表示・抑制は出ない (telemetry 送信のみ)。
- **読み直し方**: `/Applications/Claude.app/Contents/Resources/app.asar` を bytes のまま `notificationSound` / `turn_complete` / `viewing_session` で検索し前後を読む (python の `re` で。 ugrep は長い正規表現で `exceeds complexity limits` になる)。 設定画面の文言はローカルの locale file (`Resources/ja-JP.json` 等) には無い。

## <a id="macos-notification-prefs"></a>macOS の通知許可と音量

- `defaults export com.apple.ncprefs -` の `apps[]` で `bundle-id == com.anthropic.claudefordesktop` の `flags`。 観測からの bit 推定: 25 = 通知を許可 / 1 = バッジ / 2 = サウンド / 3 = バナー / 4 = 通知パネル。 **公開仕様ではない**ので、 「通知を許可している他の app と同じ bit が立っているか」 の比較で補強する (script がやる)。
- 同じ plist の `dnd_prefs` (中身は binary plist) の `dndMirrored` = 集中モードの「デバイス間で共有」。
- 音量: `osascript -e 'get volume settings'` の `alert volume` と `output muted`。

## <a id="focus-dnd-unified-log"></a>集中モードの実状態は unified log で読む

- 設定 DB (`~/Library/DoNotDisturb/DB/*.json`) と通知履歴 DB (`~/Library/Group Containers/group.com.apple.usernoted/db2/db`) は TCC で読めない (`Operation not permitted` / `authorization denied`)。 **unified log は読める**。
- ⚠️ zsh では `log` が builtin (`log: too many arguments`) → **`/usr/bin/log`** と書く。
- **状態の変化**:
  ```bash
  /usr/bin/log show --last 2d --style compact --predicate 'subsystem == "com.apple.donotdisturb" AND eventMessage CONTAINS "Did receive state update"'
  ```
  各行の `state:` (その後ろの `previousState:` は変化前) を読む: `activeModeIdentifier` (`(null)` = オフ) / `suppressionState` (`inactive` = オフ) / `reason` (`scheduled` / `user action` / `system state`) / mode の `name` / `startDate` (いつから) / `userVisibleTransitionDate` (**`4001-01-01` = 終了時刻なし**)。
- **Claude の通知ごとの扱い**: 述語を `… AND eventMessage CONTAINS "claudefordesktop"` にする。 `interruptionSuppression: delay delivery` = 音もバナーも出さず通知センター行き / `none` = 素通り。 `Breakthrough is allowed with reason: mode configuration for application` = 「通知されるアプリ」 に入っているので通過した印。
- `suppressionState: while UI locked` という表示でも、 画面を使っている最中の通知が `delay delivery` になっていた (2026-09 実測、 直近 2 日の全 7,841 件)。 **この文字列を「ロック中だけ」 と読まない**。 判定は通知ごとの `interruptionSuppression` で。
- 常時オンか時間帯限定かは、 全 app 分の `process == "NotificationCenter" AND eventMessage CONTAINS "Resolved event behavior"` を時間別に数えると分かる。
- `log show` は数日分で数十秒かかる。

## <a id="focus-shared-retired-device"></a>「デバイス間で共有」 + 使わなくなった端末 = おやすみモードが終わらない

集中モードは既定で同じ Apple Account の端末間で共有される。 iPhone で終了時刻なしでオンにしたままその iPhone を使わなくなると、 Mac 側に終わらない状態 (`userVisibleTransitionDate: 4001-01-01`) が残り、 スケジュール (例 23:00〜8:00) の終了時刻が来てもオフにならない (実例: 約 2 ヶ月)。 オフに戻すはずの端末がもう無いので、 放置すれば永久に続く。 ⚠️ 本件でオンにしたのがその iPhone だったこと自体は、 起点が unified log の保持期間外で直接は確かめていない (終了時刻の無い状態 + 共有が on + その端末を使っていない、 の 3 点からの推定)。 直し方は起点がどの端末でも同じ。

直し方 (システム設定の変更 = user が操作する):
1. **Claude だけ通す**: システム設定 → 集中モード → おやすみモード →「通知を許可」 の「通知されるアプリ」 に Claude を追加。 おやすみモードはオンのままで、 Claude の通知は `interruptionSuppression: none` になる。
2. **(任意) 共有を切る**: 集中モードの画面の「デバイス間で共有」 をオフ。 使っていない端末の状態に引きずられないための保険。 3 で Mac 側をオフにすればそれが最新の状態になり、 1 で Claude を許可してあれば戻っても Claude は通るので、 必須ではない (2026-09 の実例では切らずに済ませた)。
3. **Mac でオフにする**: 機種によってはファンクションキー列の 🌙 キー (例: 2021 年以降の MacBook Pro の F6)、 またはコントロールセンター。 どちらも環境差があるので、 案内する前に実物を確かめる ([#ui-guidance-look-first](#ui-guidance-look-first))。

効いたかは unified log の `reason: user action` → `activeModeIdentifier: (null)` か、 設定画面の表示で確かめる ([#macos26-focus-settings-ui](#macos26-focus-settings-ui))。

## <a id="macos26-focus-settings-ui"></a>macOS 26 の集中モード設定画面の読み方 (2026-09 実測、 26.5)

- 集中モード一覧の各行は、 **オンのときだけ右端に「オン」**、 オフのときは何も出ない (「オフ」 という表記は無い)。
- おやすみモードの詳細画面 (行をクリック) に**オン/オフのスイッチは無い** (通知を許可 / スケジュール / 集中モードフィルタだけ)。
- 「集中モード状況」 の「オン」 は、 集中モード中であることを相手に知らせる機能の設定で、 集中モード自体がオンという意味ではない。
- `open "x-apple.systempreferences:com.apple.Focus-Settings.extension"` は 26.5.2 で集中モードでなく「一般」 を開いた。 開いたらサイドバーの「集中モード」 をクリックする。
- メニューバーのコントロールセンターは、 環境によっては見えない (user 報告)。

## <a id="ui-guidance-look-first"></a>OS の画面操作を案内する前に実画面を見る

本件では、 記憶に頼った UI 案内が 2 回外れた (「メニューバーのコントロールセンターから」 → 無かった / 「行の右端にオンかオフが出る」 → オフは空欄)。 OS の設定画面の手順を user に書く前に、 computer-use の screenshot (読むだけ) か user の screenshot で該当画面を確かめる。 設定を変える操作そのものは user に任せる (システム設定の変更は agent がやらない)。

## <a id="turn-complete-sound-hook"></a>タスク完了でも鳴らす (Stop hook、 opt-in)

完了通知はアプリの仕様で無音なので、 設定では鳴らせない。 代わりに Stop hook [`hooks/turn-complete-sound-nudge.sh`](../hooks/turn-complete-sound-nudge.sh) が応答の終わりごとに音を鳴らす。 層1 の配線 list に入っているが、 **既定は無音**。
- **有効化**: `touch ~/.claude/turn-complete-sound.on` (machine-local)。 止めるときは `touch ~/.claude/turn-complete-sound.off` (off が優先)。 `.on` の 1 行目に音声 file の path を書くとその音 (既定 `/System/Library/Sounds/Glass.aiff`)。
- **鳴らない条件**: `CLAUDE_CODE_ENTRYPOINT` が許可 list (既定 = `claude-desktop` だけ) に無い = headless の `claude -p` で夜中に鳴らない。 対話 CLI も鳴らしたいなら env `CLAUDE_TURN_SOUND_ENTRYPOINTS="claude-desktop cli"` のように足す (headless の値は足さない) / 別の Stop hook が block して turn が続いた後の 2 回目 (`stop_hook_active`) / macOS 以外 (afplay が無い)。
- 並列 session が多いとそのぶん鳴る。 アプリの「表示中の session は通知しない」 抑制も集中モードも効かない (afplay は通知ではない)。 アプリ自身の入力待ち通知と重なって 2 回鳴ることがある。
- 同じ turn で別の Stop hook が block すると、 鳴るのは最初の Stop (= 実際の終わりより少し早い) の 1 回。
- 最後に鳴らした時刻 = `~/.claude/state/turn-complete-sound.last` (効いているかの確認用)。
- hook が desktop で効くかの前提は [`hook-authoring.md#desktop-hook-honor-remeasure`](hook-authoring.md#desktop-hook-honor-remeasure)。

## 関連

- [`macos-claude-app-pty-leak.md`](macos-claude-app-pty-leak.md) — 同じ Claude.app の別症状 (pty 枯渇)
- [`hook-authoring.md#disableallhooks-kill-switch`](hook-authoring.md#disableallhooks-kill-switch) — 「desktop だけ効かない」 に見えて実は設定だった別の例 (設定値でなく実状態を測る、 の同型)
