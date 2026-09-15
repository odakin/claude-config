<!-- doc-meta
when: macOS の GUI app (Office / Pages / Keynote / Preview 等) を osascript・AppleScript・JXA で駆動する script を書く・直すとき + app を quit / kill / 再起動しようとした瞬間 + 自動化のたびに app が前面に出る・user の文書が閉じられたと言われたとき
category: macos
summary: macOS の GUI app を script で駆動するときの作法。 (1) quit の前に app へ開いている文書を聞き、 自分が開いたもの以外が 1 つでもあれば quit も kill もしない (数え直しと quit は同じ osascript の中、 plain quit で saving no を付けない、 app 名指定の killall/pkill は禁止) (2) 背景で動かす = `open -g`、 `activate` を書かない、 `open -j` (hidden) は dialog まで隠して quit が -128 で取り消されたまま残るので使わない (3) `application id "…" is running` は app を起動しない probe、 `tell application` は起動する (4) 前面を奪ったら `path to frontmost application` で覚えた app へ `open -a` で返す (System Events 権限不要) (5) 文書は path か open が返す参照で指す (`active document` / `workbook 1` は user の文書を指しうる、 /private/tmp と /tmp の表記差を揃える)。 Office 向け実装 = scripts/lib/office-app-guard.sh
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

## <a id="implementations"></a>実装と検査

- Office 向け = [`scripts/lib/office-app-guard.sh`](../scripts/lib/office-app-guard.sh) (bash の 1 実装 + CLI、 python は `scripts/lib/office_staging.py` の `office_app()`)。 手書きの osascript は [`scripts/office-stage-run.sh`](../scripts/office-stage-run.sh) が拡張子から app を決めて前後に guard を挟み、 python driver は `with Stage(...)` が同じことを出口で行う (= with の中で起動した app だけ、 自分の copy を閉じて空なら quit)。 Pages は [`scripts/docx-to-pdf.sh`](../scripts/docx-to-pdf.sh) `--pages` が自身の container 経由で同じ規則を実装。 Bash で Office を名指しで止める command (`killall` / `pkill` / `kill $(pgrep …)` / inline osascript の quit) は PreToolUse hook [`hooks/office-inplace-guard.py`](../hooks/office-inplace-guard.py) が deny する。
- 検査の型 = osascript / open を PATH の stub に差し替え、 app の状態 (起動中か・文書一覧) を file で持つ ([`scripts/lib/office-app-guard.test.sh`](../scripts/lib/office-app-guard.test.sh))。 **AppleScript 本体の挙動は stub では検査できない** = 実機で 1 回確かめた結果を doc に残す。
- 他の app に広げる時は、 app ごとに「文書一覧の取り方」 (Office = `full name` + `saved` / Pages 等 = `file of document`) と「`activate` を外して動くか」 を 1 回ずつ実測する。
