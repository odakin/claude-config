<!-- doc-meta
when: Windows (Git Bash / MSYS) 上で本リポの script・hook を動かす / 移植性のある shell・Python を書くとき
category: infra
summary: Windows (MSYS/Git Bash) 固有の silent failure 集 (= native Win32 tool の stdout は text mode ゆえ jq/gh が CRLF を吐き `while read` だけが CR を残す / drive root `C:` は `dirname` の不動点で `!= "/"` 型の上り詰め loop が無限化 / MSYS path `/tmp` と native path `C:/` は同じ dir を指しても文字列一致しない・native library は前者を開けない / Windows Python に `python3.exe` は無く Store の App Execution Alias が「Python」 とだけ印字して成功終了する / console は cp932 で emoji 印字が UnicodeEncodeError / core.autocrlf=true が shell script を壊す / Windows では hook は symlink でなく copy なのでリポ修正が installed hook に伝播しない / mkstemp の fd を捨てると Windows でだけ後続 save が Permission denied)。 共通 kernel = すべて例外を出さず「もっともらしく」 失敗するため症状が原因から遠い。 新規 Windows 機の一括 setup = `scripts/bootstrap-windows.ps1` + 以後の毎 session 自己治癒 = `hooks/session-start-windows-bootstrap.sh` (#bootstrap-one-liner、 実機検証待ち)
-->
# Windows (Git Bash / MSYS) の silent failure 集

**いつ読む**: Windows 端末で `setup.sh` / hooks / `scripts/*` が「動いているように見えて実は違う」 とき。 または shell / Python を書いていて **POSIX 以外でも動く必要がある**とき。

> 本 file の全項目は 2026-08-03 に Windows 11 Pro (MINGW64, 日本語 locale, Python 3.13) で実測した症状に基づく。 macOS/Linux では 1 つも再現しない — それが厄介さの本体で、 開発機で緑なら CI と手元で永久に見えない。

## <a id="bootstrap-one-liner"></a>新規 Windows 機の一括 bootstrap (1 行)

本 file の予防可能な地雷 (git 不在 gate / autocrlf / python3 stub / cp932) を、 新しい Windows 機で最初にまとめて design-out する script を用意している。 PowerShell に 1 行貼るだけ:

```powershell
irm https://raw.githubusercontent.com/odakin/claude-config/main/scripts/bootstrap-windows.ps1 | iex
```

やること (全 step 冪等 = 導入済みは skip): ① Git for Windows (winget) + `core.autocrlf=false` ② Python 3 実体 (Store stub 判別つき) + `python3.exe` shim ③ `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8` (User env) ④ Claude Code CLI (公式 installer、 `$env:CLAUDE_BOOTSTRAP_SKIP_CLI=1` で skip)。 詳細は script header 参照。

**以後の維持は自動**: `setup.sh` を一度通せば SessionStart hook `hooks/session-start-windows-bootstrap.sh` が毎 session 冒頭に ①〜③ を自己点検・自動修復する (= python 再インストールで shim が消えても次 session で復活する自己治癒。 非 Windows では即 silent exit、 健全時は stamp fast path で subprocess ゼロ)。 ⚠️ 既存 install に新規追加された hook の settings.json 登録は post-merge では走らない — pull 後に `setup.sh` を 1 回再実行すること。

背景: Claude desktop app の Code 機能は git 不在だと local session を門前払いし、 エラー文言の "Git" を非開発者は "GitHub" と区別できず「GitHub 登録」 の迷路に迷い込む (= 上流 FR [anthropics/claude-code#83539](https://github.com/anthropics/claude-code/issues/83539))。 gate の実体は git という開発ツールの不在 1 個であって、 GitHub アカウントは一切不要。

⚠️ **2026-08-03 起草時点で実機未検証** (起草環境 = macOS)。 初回実行者は成否を issue / PR で報告してほしい — 検証が取れたらこの marker を実測日付に置換する。

## 総論: 「POSIX に見える層」 と native binary の境界

Git Bash (MSYS) は POSIX の**見かけ**を提供するが、 そこから呼ばれる `jq.exe` / `gh.exe` / `git.exe` / Python の C 拡張は**native Win32 プログラム**で、 MSYS の約束事を共有しない。 事故はほぼ全部この境界で起きる:

| 層 | path の形 | 改行 | 例 |
|---|---|---|---|
| MSYS bash 内 | `/tmp/x`, `/c/work/...` | LF | `mktemp -d`, `dirname` |
| native binary | `C:/work/...` | **CRLF** (stdout が text mode) | `jq`, `gh`, `git rev-parse`, PyMuPDF |

**両者は同じ dir を指していても文字列として一致しない**。 そして不一致は例外にならず、 fallback 経路に静かに落ちる。

## <a id="crlf-from-native-tools"></a>native tool の stdout は CRLF — `while read` だけが CR を残す

`jq.exe` / `gh.exe` は MSVC build で stdout が text mode のため `\n` を `\r\n` に変換して出す:

```console
$ echo '{"a":"x"}' | jq -r '.a' | od -c
0000000   x  \r  \n
```

⚠️ **非対称が罠の本体**: MSYS bash の command substitution `$(...)` は末尾の CR を**落とす**が、 `while IFS= read -r` は**落とさない**。

```bash
v=$(... | jq -r '.login')          # OK — CR は落ちる
... | jq -r '.[]' | while read -r x; do   # ✗ $x は "value\r"
```

∴ scalar を 1 個取るだけの経路は無事に見え、 **行単位で読む経路だけが壊れる**。 実害 (2026-08-03):

- `merge-hook-event.sh` が期待 hook 名を `"<name>.sh\r"` と導出 → `contains($cmd)` が永久に不一致 → `setup.sh` を回すたびに全 hook を重複追加 + entry 探索も外して `null` を追記 (3 回で 6/5/3/1 → 18/15/9/3)。 `setup.sh` は「冪等・再実行安全」 と README に書かれているうえ post-merge hook からも走るので、 黙って肥大する
- repo 名の list が末尾 CR 付きで split され clone 先 path が壊れる

**対処**: 行単位で食う直前に `| tr -d '\r'` を挟む。 POSIX では no-op。

```bash
done < <(... | jq -r '...' | tr -d '\r')
```

⚠️ **test 側も独立に jq を呼ぶ**なら同じ処置が要る。 `... | tr '\n' ' '` は LF だけを置換して CR を残すため、 失敗メッセージ上は期待値と**完全に同一の文字列**が表示される (= CR が不可視)。

## <a id="dirname-drive-root-fixpoint"></a>drive root は `dirname` の不動点 — `!= "/"` の上り詰めは無限 loop

```console
$ dirname C:/work/x   ->  C:/work
$ dirname C:/          ->  C:
$ dirname C:           ->  C:      # 不動点。 "/" には永久に到達しない
```

∴ 「親を辿って `.git` を探す」 型の loop で停止条件を `/` に置くと Windows で**回り続ける**:

```bash
dir="$(dirname "$FILE_PATH")"
while [ "$dir" != "/" ] && [ -n "$dir" ]; do   # ✗ Windows で無限
  ...
  dir="$(dirname "$dir")"
done
```

実害: `public-leak-guard.sh` は `PreToolUse(Edit|Write|MultiEdit)` hook なので、 **git repo の外の file を編集した瞬間に tool call ごと固まる**。 repo 内の path は `.git` を見つけて早期脱出するため「たまたま」 動いており、 発症条件が絞られる分だけ発見が遅れた。

**対処**: hardcode した `/` でなく**不動点**を検出する。 POSIX (`dirname /` = `/`) でも同じ式で閉じる。

```bash
parent="$(dirname "$dir")"
[ "$parent" = "$dir" ] && break
dir="$parent"
```

## <a id="msys-vs-native-paths"></a>MSYS path と native path は一致しない・native library は前者を開けない

`git rev-parse --show-toplevel` は Git for Windows では **native 形式** (`C:/work/.../repos/x`) を返す。 一方 `mktemp -d` は **MSYS 形式** (`/tmp/...`)。 同じ dir なのに substring 照合が通らない。

- test 側で期待値を作るなら、 生成直後に `cygpath -m` で native 形式へ畳む (`command -v cygpath` で guard すれば POSIX では no-op)
- **native library に MSYS path を渡さない**。 PyMuPDF に `/tmp/x.pdf` を渡すと `cannot open file '/tmp/x.pdf': No such file or directory` になる (bash からは見えている path なので混乱しやすい)。 Python 側は `tempfile.gettempdir()` を使う
- `glob()` は platform separator (`\`) で返すのに pattern は `/` で書かれる。 `m.startswith(prefix)` 型の比較は Windows で必ず外れ、 basename fallback があると**全 entry が glob 末尾の file 名に潰れる** (= 例外は出ず、 件数 1 の「もっともらしい」 結果になる)。 両辺を `/` に正規化してから比較・分割する

## <a id="python3-missing-store-stub"></a>`python3` は存在しない — Store の alias が「成功」 して何もしない

Windows の Python は `python.exe` しか置かない。 `python3` は Microsoft Store の **App Execution Alias** に解決され、 `Python` とだけ印字して終了する — **実行もエラーもしない**。

```console
$ python3 -c "print('hello')"
Python
```

∴ `#!/usr/bin/env python3` の script、 `python3 foo.py` を呼ぶ git hook や runner は、 **全部 no-op のまま成功扱い**になる。 pre-commit から呼ばれた場合は「drift を検出しました」 のような偽の警告に化けることもある。

**対処**: `python.exe` を同 dir に `python3.exe` として copy する (Python 再 install のたびに必要)。 PATH 上で Store alias より実体側を先に置くこと。

## <a id="console-encoding-cp932"></a>console は cp932 — emoji 1 個で Python が落ちる

日本語 locale の Windows では Python の stdout encoding が `cp932` になり、 絵文字や一部記号の print が例外になる:

```
UnicodeEncodeError: 'cp932' codec can't encode character '\U0001f550'
```

実害: SessionStart hook (`currentdate-anchor.py`) が 🕐 を出力しており、 **毎 session 起動で落ちて日付 anchor が入らない**。 hook の失敗は表に出ないので気づけない。

**対処**: 環境側で `PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1` を与える (`~/.claude/settings.json` の `env` に置ける)。 script 側で閉じるなら子プロセス出力の decode に `errors="replace"` を付ける。 ⚠️ `subprocess.run(..., text=True)` の decode 例外は **capture 用の reader thread 内**で起きるため呼び出し側の `try/except` では捕まらず、 traceback を撒いたうえで出力だけが失われる。

## <a id="autocrlf-corrupts-scripts"></a>`core.autocrlf=true` (Git for Windows の既定) が shell script を壊す

既定のまま clone すると **作業ツリー全 file が CRLF** になる。 shell script の CRLF 化は多くの下流で誤動作を生むうえ、 上記 CRLF 系の症状と混ざって切り分けを難しくする。

**対処**: `git config --global core.autocrlf false` にして clone し直す (既存ツリーは `git rm --cached -r . && git reset --hard` で LF に戻る)。

⚠️ Python から file を書き戻すときも同様の罠がある。 `Path.write_text()` は既定 (`newline=None`) で `\n` を `os.linesep` に変換するため、 **Windows で編集 script を走らせると file 全体が CRLF 化して diff が全行差分になる**。 `write_bytes()` を使うか `newline="\n"` を明示する。

## <a id="hooks-are-copies-not-symlinks"></a>Windows では hook は copy — リポを直しても installed hook は古いまま

`setup.sh` は symlink が使えない Windows で `~/.claude/hooks/` へ **copy** する。 ∴ **リポ側の hook を修正しても、 稼働中の hook は前のまま**。 macOS (symlink) では自動で追随するため、 この差は忘れやすい。

**対処**: hook を直したら `setup.sh` を再実行する (または当該 file を copy し直す)。 加えて Claude Code の hook は **session 開始時の snapshot** で動くため、 反映は次 session から。 「直したのに直らない」 ときはこの 2 段を疑う。

## <a id="tempfile-open-handle"></a>開いたままの temp file handle は Windows でだけ後続 write を拒む

`tempfile.mkstemp()` は **開いた fd** を返す。 `Path(mkstemp(...)[1])` のように fd を捨てると、 POSIX では単に fd leak として溜まるだけだが、 **Windows では handle が生きているため後続の `save()` が失敗する**:

```
cannot remove file 'C:\...\fix_A_xxxx.pdf': Permission denied
```

`NamedTemporaryFile(delete=False)` を別の writer に `f.name` で渡す場合も同じ — 先に `f.close()` する。

**対処**: `fd, name = mkstemp(...)` を受けて必ず `os.close(fd)`。

## 共通 kernel

本 file の全項目は **例外を出さずに「もっともらしい」 結果を返す**:

- dead な stub が「成功」 する
- 照合が永久に外れ、 追加系の処理が毎回「未登録」 と判断して追記し続ける
- fallback があるために件数 1 の妥当そうな値が返る
- 無限 loop は「遅い」 としか見えない

∴ **症状は原因から遠いところに出る**。 Windows で挙動が説明できないときは、 対象 script の logic を追う前に本 file の境界 (改行 / path 形式 / interpreter の実在 / encoding) を先に潰すほうが速い。

⚠️ 逐次実行の test runner では、 **止まった 1 本が以降の全 check を無効化する** — 落ちないので赤い印がどこにも出ず、 途中で切れた log は「そこまでは通った」 と読めてしまう。 遅い suite は「遅い」 と決めつけず、 log の byte 数が伸びているかで stall を判定すること。
