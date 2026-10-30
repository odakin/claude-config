<!-- doc-meta
when: macOS の GUI app (Office / Pages / Keynote / Preview 等) を osascript・AppleScript・JXA で駆動する script を書く・直すとき + app を quit / kill / 再起動しようとした瞬間 + 自動化のたびに app が前面に出る・user の文書が閉じられたと言われたとき + 本人が使っている browser に script から tab を開かせる・閉じるとき (#chromium-tab-scripting) + 自動化が止まった原因が app の dialog かを script から確かめるとき (#dialog-presence-probe) + script で動かせない項目を本人に Finder で操作してもらうとき (#hand-off-selected-item) + この Mac で特定の app を自動で起動させない・起動の経路が無いことを確かめるとき (#autostart-route-inventory)
category: macos
summary: macOS の GUI app を script で駆動するときの作法。 (1) quit の前に app へ開いている文書を聞き、 自分が開いたもの以外が 1 つでもあれば quit も kill もしない (数え直しと quit は同じ osascript の中、 plain quit で saving no を付けない、 app 名指定の killall/pkill は禁止) (2) 背景で動かす = `open -g`、 `activate` を書かない、 `open -j` (hidden) は dialog まで隠して quit が -128 で取り消されたまま残るので使わない (3) `application id "…" is running` は app を起動しない probe、 `tell application` は起動する (4) 前面を奪ったら `path to frontmost application` で覚えた app へ `open -a` で返す (System Events 権限不要) (5) 文書は path か open が返す参照で指す (`active document` / `workbook 1` は user の文書を指しうる、 /private/tmp と /tmp の表記差を揃える) (6) Chromium 系 browser の tab = 裏で開いて前面の tab を戻す・id で指す・見るのは query を落とした URL と loading だけ・閉じるのは自分が開いた tab を場所を確かめてから (scripts/lib/browser_tab.py) (7) app が dialog を出しているかを読む = System Events は補助アクセスが要り無いと -25211、 代わりは画面撮影か「AppleScript が -1712 で止まったか」、 probe 自身の失敗 message に検出語が入る罠 (8) 本人に手で押してもらう項目 = 名前で探させず `open -R` で選択状態にして 1 つずつ渡す (同じ folder への連続の `open -R` は同じ窓の選択を移すだけ、 container の表示名は app を消すと bundle id に戻る、 保護された folder ではまとめて選ばせる AppleScript が通らない) (9) app を自動で起こす経路の数え上げ = launchd の agent / ログイン項目 / `sfltool dumpbtm` (bundle id で照合) / 再ログイン時のウインドウ復元 / 自分の script の `open -a`、 「無い」 は起動役の間隔より長く閉じたまま待って確かめ、 起動の時刻は launchservicesd の CHECKIN 行。 Office 向け実装 = scripts/lib/office-app-guard.sh
-->

# macOS の GUI app を script で駆動する作法 <a id="macos-gui-app-automation"></a>

osascript / AppleScript / JXA で GUI app を動かす script は、 **user がその app で作業している最中にも走る**。 だから「動けば良い」 では足りず、 **user の文書と前面 (focus) に触らない**ことが要件になる。 本 doc はその一般則の正本。 Office (Excel / Word / PowerPoint) 向けの実装と実測は [`office-automation.md#office-app-reset-guard`](office-automation.md#office-app-reset-guard)、 復旧を「命令の再実行」 でなく状態遷移として扱う原則は [`convention-design-principles.md#recovery-state-transition`](../docs/convention-design-principles.md#recovery-state-transition)。

## <a id="ask-before-quit"></a>1. quit の前に、 開いている文書を app に聞く

「前回の実行の残骸で固まるから毎回 quit + sleep」「効かなければ killall」 は、 user が同じ app で文書を開いていると壊れる: 未保存なら保存 dialog で script が止まり (-1712)、 kill なら作業ごと消える。

- **quit してよいのは、 開いている文書が全部「この script が開いたもの」 の時だけ**。 文書一覧 (path + 保存済みか) を app に聞き、 自分のもの (staging dir の中の copy 等) を保存せず閉じてから quit する。 1 つでも user の文書 (path が外 / 未保存の新規) があれば **quit せず、 自分の文書だけを開閉して続行**する。
- **数え直しと quit は同じ osascript の中で**撃つ (= 一覧を取ってから quit までの間に user が文書を開いても quit しない)。
- **`quit saving no` にしない** — 数え直しをすり抜けた user の文書も、 plain `quit` なら保存 dialog が守る。
- quit が **-128 (user canceled)** で返ったら、 app に dialog (開く panel・警告) が出ている。 触らず続行し、 dialog の存在を伝える。
- 応答しない (-1712 / -609) app は、 **文書を確かめられないので quit も kill もしない**。 user に「保存して自分で終了してから」 を頼む。
- **app 名指定の `killall` / `pkill` は使わない**。 唯一の例外 = その session が自分で起動したと起動時刻で確かめた process で、 文書一覧に 0 と答えたものを PID 指定で終わらせる時。
- 自分が起動した app は、 終わりに同じ条件 (自分の文書を閉じた後に 0 件) で quit して起動前の状態に戻す。 もとから起動していた app は起動したままにする。

## <a id="background-launch"></a>2. 前面に出さない

- **起動は `open -g -b <bundle id>`** (= 前面に出さない)。 AppleScript に **`activate` を書かない**。 file を開くなら `open -g -a "<App>" <file>` (LaunchServices 経由 = cold start に強く、 sandbox app にも file 単位の読み取りが付く)。
- **`open -j` (hidden) は使わない** — 開く失敗の警告などの dialog まで見えなくなり、 `quit` が -128 で取り消されたまま誰も気づかない (実測)。
- `activate` を外すだけで背景のまま動く app が多い (実測: Excel は冷えた状態からの `tell` 起動でも前面が動かず書込・保存できた)。 ⚠️ **外すと `open` が `missing value` / -1712 で止まる app は、 sandbox の file access 許可を dialog で求めていて、 その dialog が前面に出ないせい**であることがある (実測: Pages)。 `activate` を戻すのでなく、 **file をその app 自身の sandbox container の中 (`~/Library/Containers/<bundle id>/Data/tmp/<unique>/`) に copy して開かせ、 出力もそこに書かせてから持ち帰る** (= 許可が要らないので背景のまま通る。 Office 3 app の場合は共有の group container が同じ役 = [`office-automation.md#office-pregranted-staging-dir`](office-automation.md#office-pregranted-staging-dir))。 外したら 1 回実機で確かめる。

## <a id="is-running-probe"></a>3. 起動していない app を起こさずに調べる

- `osascript -e 'application id "com.microsoft.Excel" is running'` は **app を起動しない** probe (System Events の権限も要らない)。
- `tell application "X" to …` は **app を起動する**。 状態を聞くだけのつもりの script が app を立ち上げないよう、 先に `is running` で分岐する (script の中でも `if application id "…" is running then tell …`)。
- `pgrep -x` は process の有無しか分からない (= 文書を持っているか、 応答するかは分からない)。

## <a id="focus-handback"></a>4. 奪った前面を返す

- 始める前に `osascript -e 'POSIX path of (path to frontmost application)'` で前面 app の path を覚える (System Events 不要)。
- 終わった時点で **駆動した app が前面にいて、 かつ覚えた app が別** なら `open -a "<覚えた path>"` で返す。 駆動した app が前面にいなければ何もしない (= user が途中で別 app に移っている)、 もとからその app が前面なら返さない。

## <a id="address-by-path"></a>5. 文書は path か参照で指す

- `active document` / `active presentation` / `active workbook` / `workbook 1` は、 user が同じ app で文書を開いていると **user の文書を指しうる** (= save / close が user の文書に当たる)。 `open workbook …` が返す参照か、 `full name` が自分の path に一致する文書だけを save / close する。
- 同じ path (Excel は同名の book を 2 つ開けないので**同名**) の文書が既に開いていたら、 開かずに止まる (= 開いていた方を自分のものとして閉じると未保存の編集が消える)。
- **path の表記差を揃えてから比べる**: app は `/private/tmp/x` を `/tmp/x` と答えることがある (実測: Excel)。 古い版は HFS path (`Macintosh HD:Users:…`) で答えるので POSIX に変換してから比べる (変換は scripting addition なので `tell` の外で)。

## <a id="chromium-tab-scripting"></a>6. Chromium 系 browser の tab を裏で開き、 行き先を見て、 自分の tab だけ閉じる

本人が使っている browser に「1 回だけページを開かせる」 用途 (SSO の入り直し = [`machine-route-first.md#sso-session-recovery`](machine-route-first.md#sso-session-recovery))。 実装 = [`scripts/lib/browser_tab.py`](../scripts/lib/browser_tab.py)。 文書 app の「quit の前に聞く」 (1.) と同じ考え方を tab に当てる = **閉じてよいのは自分が開いたものだけで、 閉じる直前に確かめる**。

- **開く**: `make new tab at end of tabs of <window> with properties {URL:u}` は、 その窓の前面の tab を新しい tab に切り替える。 直前に `active tab index` を覚え、 直後に戻す (実測: `activate` を書かなければ app は前面に出ない)。 窓が 1 枚も無ければ `make new window` → `active tab` の `URL` を設定。 `open -g -a <App> <url>` でも裏で開けるが、 開いた tab を後から特定できない (= 行き先を見られず、 閉じられない)。
- **profile を指定して開く (AppleScript 不要)**: browser の実行 file を `"/Applications/<App>.app/Contents/MacOS/<App>" --profile-directory="<profile の dir 名>" <url>` で起動すると、 起動中の instance に command line が渡ってすぐ終わり (browser が起動していなければ普通に起動してしまう = 下の「起動していない browser を起こさない」 と同じく先に `pgrep -x` で見る)、 その profile の窓に tab が開く (窓が無ければ作る。 実測 = 複数 profile の browser で片方の窓を前に出したい時・拡張の設定画面 `chrome-extension://…/options.html` を特定の profile で開かせたい時)。 `https://` と `chrome-extension://` は開くが、 `chrome://` / `brave://` の URL は渡しても開かない (実測) = 設定画面は本人にアドレスバーへ打ってもらう。 dir 名 (`Default` / `Profile 1` …) と表示名の対応は user data dir の `Local State` の `profile.info_cache`。 開いた tab は自分で閉じられない (= 上の「自分の tab だけ閉じる」 の外) ので、 本人に見せる用途で使う。
- **窓を選ぶ**: `mode of window` が `"normal"` の窓だけ。 incognito 等の窓は cookie を共有していないので、 SSO の入り直しに使うと必ずログイン画面に落ちる。
- **tab は id で指す**: 開いた時に `id of window` と `id of tab` を返し、 以後は `tab id T of window id W` で指す。 本人が tab を別の窓へ移す・閉じると参照が error になる → `try` で受けて「無くなった」 として扱う (index や `active tab` で指すと本人の tab に当たる = 5. と同じ)。
- **見るのは `URL` と `loading` だけ**。 URL の query と fragment は AppleScript の中で落としてから返す (`text item delimiters` を `?` と `#` に)。 redirect の途中の URL には認証の request が query に載ることがあり、 script 側に渡す理由が無い。 ページの中身 (`execute javascript` 等) は読まない。
- **閉じる**: `close <tab>`。 直前に URL を取り直し、 期待する prefix の下に居る時だけ閉じる (開いた後に本人がその tab で別の場所へ移っていたら、 もう本人の tab)。 最後の 1 枚を閉じると窓も閉じるはず (= 自分で作った窓なら元の状態に戻る。 未実測)。
- **app 名を AppleScript の本文に入れるなら固定の一覧からだけ** (`tell application "<名前>"` は変数にすると用語が解決できないので本文に埋めることになる = 外から来た文字列を埋めない)。
- **起動していない browser を起こさない**: `tell application` は app を起動する (3.)。 先に `pgrep -x` / `is running` で見て、 起動していなければ何もしない。
- **自動操作の許可 (Automation) は「呼び元の app × 相手の app」 ごと**で、 初回に macOS の dialog が出る。 無人実行では dialog を出せず error -1743 になる。 osascript が応答しない・失敗する時は「開くだけ」 (`open -g`) に落とし、 行き先が見えない前提で別の信号 (cookie の更新等) を上限つきで待つ。
- **実行せずに構文だけ確かめる** = `osacompile -o /tmp/x.scpt script.applescript` (app の用語も解決される。 本人の browser で閉じる系の操作を試走できない時の最低限)。

## <a id="dialog-presence-probe"></a>7. app が dialog を出しているかを script から確かめる

「自動化が止まったのは app の dialog のせいか」 を確かめたい時 (例 = sandbox の folder 許可 dialog、 [`office-automation.md#office-pregranted-staging-dir`](office-automation.md#office-pregranted-staging-dir))。

- **System Events で UI を読む** (`tell process "X"` の `windows` / `sheets` / `buttons` / `static texts`) には、 osascript を呼んだ app (Terminal / Claude.app 等) に **補助アクセス (Accessibility) の許可**が要る。 無いと落ちる。 ⚠️ **error 番号は当てにしない** — 実測で 2 形 (`-25211` / `-1728`) が出た。 変わらないのは**文言**の「補助アクセスは許可されません」 なので、 判定はそちらに当てる (実測は日本語の環境のみ = 英語の環境の文言は未確認。 当てるなら両方の形を並べる)。 app 自身の AppleScript 辞書 (`name of every document` 等) はこの許可が要らないが、 dialog は見えない。 確かめ方 = `osascript -e 'tell application "System Events" to tell process "<app>" to return name of every window'` (許可があれば窓の名前、 無ければ `-25211`)。
- **許可が無い時の代わり** (実測): (a) `screencapture -x <png>` で画面を撮り、 縮小して画像で見る (他 app の窓を写すには呼び元に画面収録の許可が要る — 写らなければそれを疑う)。 (b) 待っていた AppleScript の結果で推す = modal dialog が出ている間 app は AppleEvent に答えず、 `with timeout` を過ぎて `-1712` で返る。 数秒で成功して返れば dialog は出ていない。 (b) は無人でも回るので、 回帰検査は (b) を合否に使い、 (a) は最初の 1 回の確認に使う。
- **probe の出力を判定に使う前に、 probe 自身が成功したか (exit code) を見る**: 「アクセス」 のような語で dialog を探すと、 補助アクセスが無い時の失敗 message そのものに一致し、 UI を 1 つも読めていないのに「dialog あり」 と判定する (実測)。 検出語が自分の失敗経路の出力にも現れる形 = [`convention-design-principles.md#detector-fires-on-its-own-signal`](../docs/convention-design-principles.md#detector-fires-on-its-own-signal)。

## <a id="hand-off-selected-item"></a>8. 本人に手で押してもらう項目は、 選択状態にして 1 つずつ渡す

script では動かせず本人の操作が要る時 (保護された folder の削除、 権限 dialog の先の操作) は、 **名前で探させない**。 Finder が見せる名前は実体の名前と違うことがあり、 しかも途中で変わる (sandbox の container folder は、 app が在る間は app の表示名で並び、 app を消すと bundle id の名前に戻る = 実測)。 名前で頼むと、 本人は言われた名前を一覧に見つけられず止まる。

- **渡し方**: `open -R <path>` で Finder の窓に選択状態で出し、 本人は ⌘⌫ などを押すだけにする。 文面では「選ばれているもの」 と言う。 名前を添えるなら、 今の表示と違いうると断る。
- **1 つずつ**: 同じ folder の項目に続けて `open -R` すると、 Finder は新しい窓を開かず同じ窓の選択を移すだけ = 最後の 1 つしか選ばれていない (実測)。 出す → 本人の「やった」 → 消えたかを path で確かめる → 次を出す、 を繰り返す。
- **まとめて選ばせる AppleScript は保護された folder では使えない**: `~/Library/Containers` の項目は Finder の `select` に渡す参照が作れない (`POSIX file … as alias` が `-1700`、 `item "<名前>" of folder` が `-1728`、 `whose displayed name is …` は `-1712` で時間切れ = 実測)。
- 本人が窓を閉じた・見失ったと言ったら、 残っている項目を path で確かめてから、 残りの 1 つ目をもう一度 `open -R` で出す。

## <a id="autostart-route-inventory"></a>9. app を自動で起こしている経路を数え上げる

「この Mac ではこの app を自動で起動しないで」 と頼まれた時 (例 = 同時に 1 台しかログインできない app を別の機械に常駐させる)。 システム設定のログイン項目だけを見て「無い」 と言わない。 経路は 5 つあり、 どれも script で読める:

| 経路 | 読み方 | 止め方 |
|---|---|---|
| launchd の agent (KeepAlive の plist が、 app を起こす script を呼ぶ形を含む) | `ls ~/Library/LaunchAgents/` と `launchctl list` | 入れた installer の uninstall、 無ければ `launchctl bootout gui/$(id -u)/<label>` + plist を消す |
| ログイン項目 (ログイン時に開く) | `osascript -e 'tell application "System Events" to get the name of every login item'` | システム設定 › 一般 › ログイン項目から外す |
| app が自分で登録した起動 (SMAppService・背景の helper) | `sfltool dumpbtm` の `Identifier:` / `Name:` の行を bundle id で照合 (一般ユーザーで読める = 実測)。 app 名の短い語で grep すると別の語の一部に当たる (`line` が `deadline` に当たる = 実測) | app の設定の「ログイン時に起動」、 またはシステム設定 › ログイン項目の「バックグラウンドで許可」 |
| 再ログイン時のウインドウ復元 | `defaults read com.apple.loginwindow TALLogoutSavesState` (1 = ON) | 全 app に効く設定なので変えるなら本人に聞く。 変えなくても、 その app を閉じてから再起動・ログアウトすれば戻らない |
| 自分の script・定期処理が `open -a` で起こす | 自分の repo を `command grep -rn -e 'open .*-a <App>'` で引く ([`shell-env.md#bash-tool-grep-ignores-gitignore`](shell-env.md#bash-tool-grep-ignores-gitignore)) | 呼び元を止める |

- **「無い」 の確かめ方**: app が閉じた後、 常駐の起動役が持ちうる間隔 (毎分起こす常駐なら 1 分) より長く待って戻らなければ、 常駐で起こす経路は無い (実測)。 閉じるのは本人に頼む (本人が使っている app を script で quit しない = [§1](#ask-before-quit))。
- **いつ起動したか** = unified log: `/usr/bin/log show --last 12h --style compact --predicate 'process == "launchservicesd" AND eventMessage CONTAINS "CHECKIN" AND eventMessage CONTAINS "<bundle id>"'` が起動の時刻と pid を出す (helper は `<bundle id>.<suffix>` の別の行)。 誰が起こしたか (手か script か) はこの行だけでは決まらない。 log の保存期間より前の起動は出ない。 zsh では素の `log` が組み込みに取られる = full path ([`shell-env.md#zsh-log-builtin`](shell-env.md#zsh-log-builtin))。

## <a id="implementations"></a>実装と検査

- Office 向け = [`scripts/lib/office-app-guard.sh`](../scripts/lib/office-app-guard.sh) (bash の 1 実装 + CLI、 python は `scripts/lib/office_staging.py` の `office_app()`)。 手書きの osascript は [`scripts/office-stage-run.sh`](../scripts/office-stage-run.sh) が拡張子から app を決めて前後に guard を挟み、 python driver は `with Stage(...)` が同じことを出口で行う (= with の中で起動した app だけ、 自分の copy を閉じて空なら quit)。 Pages は [`scripts/docx-to-pdf.sh`](../scripts/docx-to-pdf.sh) `--pages` が自身の container 経由で同じ規則を実装。 Bash で Office を名指しで止める command (`killall` / `pkill` / `kill $(pgrep …)` / inline osascript の quit) は PreToolUse hook [`hooks/office-inplace-guard.py`](../hooks/office-inplace-guard.py) が deny する。
- 検査の型 = osascript / open を PATH の stub に差し替え、 app の状態 (起動中か・文書一覧) を file で持つ ([`scripts/lib/office-app-guard.test.sh`](../scripts/lib/office-app-guard.test.sh))。 **AppleScript 本体の挙動は stub では検査できない** = 実機で 1 回確かめた結果を doc に残す。
- 他の app に広げる時は、 app ごとに「文書一覧の取り方」 (Office = `full name` + `saved` / Pages 等 = `file of document`) と「`activate` を外して動くか」 を 1 回ずつ実測する。
