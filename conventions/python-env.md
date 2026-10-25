<!-- doc-meta
when: 計算・検算を Python で回す repo を新しい機械・clone・OS (macOS / Linux / WSL / Windows / CI / Docker) で始めるとき + `pip install -r` が固定した依存で落ちたとき・venv が作れないとき + 検算の script に `.venv/bin/python` を書きかけたとき + repo の入口 `tools/py` の雛形を直す・配るとき + 機械に Python を入れる方法を選ぶとき + 外から落とした file を Python で読むとき・`python3 -I` を付けたら module が見つからなくなったとき (#isolated-mode-drops-user-site)
category: infra
summary: repo の Python の版は `.python-version` に 1 行で宣言し、 venv の用意・requirements への追従・宣言の版が無いときの案内は入口 `tools/py` (雛形 = templates/shared-project/python-env/py) が機械でやる。 環境ごと (macOS の Apple Silicon・Intel、 Linux の glibc・musl、 WSL、 Windows の Git Bash、 conda、 CI、 Docker) に何を使い、 合う python が無いとき何を案内するかの表が正本 (#python-env-environments)。 macOS の候補の arch は起動せずに `file -bL` で見る (起動すると Intel 版の対応終了の通知が出る)。 Linux と Windows は arch を見ない。 Windows の venv の python は Scripts/python.exe、 Store の alias は候補にしない。 WSL・Linux で Windows の venv を見つけたら消さずに止まる。 venv が作れない (ensurepip が無い) と依存が入らないを分けて言う。 固定した依存が入らないときは版を外さず宣言の版を入れる。 依存の Python の下限と platform ごとの wheel は scripts/python-pin-floor.py
-->
# repo の Python の版・venv・固定した依存 — 宣言は 1 か所、 用意は入口の機械が

計算や検算を Python で回す repo を、 別の人・別の機械・別の OS・新しい clone で動かすときの正本 (共有リポに限らず、 所有者だけの repo を新しい機械で使う場合も同じ)。 共有リポの招待した相手の手元の点検 ([`shared-repo.md#collaborator-check`](shared-repo.md#collaborator-check)) からは、 conf の `python` 行が本 doc の入口を使う ([`shared-repo.md#collaborator-check-python`](shared-repo.md#collaborator-check-python))。 一般則 (前提は、 それを使う人の入口で機械が満たす) は [`../docs/convention-design-principles.md#self-provisioning-prerequisites`](../docs/convention-design-principles.md#self-provisioning-prerequisites)、 本 doc はその Python の版・venv・固定した依存の場合。 道具:

| 道具 | 役 |
|---|---|
| [`templates/shared-project/python-env/py`](../templates/shared-project/python-env/py) | 入口の正本。 repo の `tools/py` はその写し (挙動・環境変数の正本 = file の冒頭) |
| [`scripts/install-collaborator-check.py`](../scripts/install-collaborator-check.py) `--item 'python tools/py -- <用途>'` | 入口を repo に写す・宣言を書く・`.venv/` を ignore・session 開始の点検に載せる。 `check` が写しの drift を言う |
| [`scripts/python-pin-floor.py`](../scripts/python-pin-floor.py) | 固定した依存が要る Python の下限と、 wheel が揃う上限を PyPI から出して宣言と照合する。 platform ごと (macOS・Linux の glibc と musl・Windows × arch) に、 宣言の版で使える wheel が無い依存も出す |
| [`scripts/repo-python-env.test.sh`](../scripts/repo-python-env.test.sh) | 入口の検査 (偽の interpreter・偽の uv・偽の `file`・`REPO_PY_OS` で模した OS、 network なし) |

## <a id="python-env-failure-modes"></a>壊れ方

1〜5 は実測。 6 の Store の alias は [`windows-msys.md#python3-missing-store-stub`](windows-msys.md#python3-missing-store-stub) の実測、 6 の venv の形・7・8 は各 OS と Python の仕様から書いた (実機では起こしていない。 入口の対処は test で模して確かめた)。

1. **黙って全滅** — 検算の script が `.venv/bin/python` を直書きしていて、 venv の無い clone では全項目が FAIL になる。 原因は 1 つなのに N 件の FAIL に見え、 読む人は 1 件ずつ原因を探しに行く
2. **手で回避して食い違う** — 手順どおりに `python3 -m venv .venv` を打つと、 その機械の `python3` (OS 付属の古い版) で venv が作られ、 固定した依存が requires_python で入らない。 その場で版を外して入れると検算は通るが、 requirements と違う venv が残り、 以後の PASS が何の環境での結果か誰も知らない
3. **文書の版の主張がずれる** — 引き継ぎ文書の「Python 3.X 以上」 が、 固定した依存の requires_python の下限より古かった (その版の機械でも入らない)。 人の文は依存を上げても追従しない
4. **venv が追従しない** — requirements を上げても、 各機械の venv は最後に入れた版のまま (Node の lockfile と同型 = [`github-security-automation.md#node-modules-follow-lockfile`](github-security-automation.md#node-modules-follow-lockfile))。 venv の元の interpreter が package manager の更新で消えると、 venv の python が起動しなくなる
5. **Intel 版を拾う** — Intel の Mac から Apple Silicon へ移した機械には、 旧 Homebrew (`/usr/local/opt/python@3.X`) や python.org の Intel 版が残る。 Rosetta があれば起動できるので、 版だけを見て選ぶ道具は黙ってそれで venv を作る。 候補を起動して arch を確かめる道具も、 起動した時点で macOS の「Intel プロセッサ用アプリの対応は終了します」 の通知を出す (Rosetta が無ければ Bad CPU type) ([`macos-cpu-arch.md#migration-intel-to-apple-silicon`](macos-cpu-arch.md#migration-intel-to-apple-silicon))
6. **Windows の venv と `python3` の形が違う** — Windows の python が作る venv の python は `Scripts/python.exe` で、 `bin/python` は無い。 `.venv/bin/python` を直書きした script は Windows では起動しない。 `python3` (と何も入っていない機械の `python`) は Microsoft Store の alias で、 起動すると「Python」 とだけ出して成功で終わる = 版を聞く道具は版の無い答えを受け取る。 native の出力は CRLF で、 path は `C:\…`
7. **venv が作れないのに、 依存の失敗に見える** — Debian・Ubuntu の python は venv の部品 (ensurepip) が別の package (`python3.X-venv`) で、 入れていないと `python3.X -m venv` が `ensurepip is not available` で失敗する。 入口がこれを依存の失敗と同じ文で言うと、 読む人は版の問題を探しに行く
8. **2 つの OS で同じ checkout を使う** — Windows の checkout (`C:\…`) を WSL から `/mnt/c/…` で開くと、 `.venv` は片方の OS の python のもの。 作り直す道具は相手の venv を消して自分の venv を作り、 相手も同じことをする (毎回作り直し合う)。 WSL では Windows の python も interop で起動できてしまうので、 そのまま使うと Linux の側で Windows の python が走る。 同期フォルダ (Dropbox など) に置いた venv も同じ形で壊れる

## <a id="python-env-declare"></a>宣言 — `.python-version` に 1 行

- repo root の `.python-version` に、 **作者が検算を通した版**を major.minor で 1 行 (例 `3.13`)。 uv・pyenv・CI (`actions/setup-python` の `python-version-file`) がそのまま読む標準の置き場所なので、 版を書く場所はここだけにする
- 依存は repo root の `requirements.txt`。 検算の repo では `==` で固定する (再現のため)。 冒頭の説明は「入口が venv を作る」 とだけ書き、 `python3 -m venv ...` の手順を書かない (その手順が壊れ方 2 を生む)
- **下限を機械で確かめる**: 宣言を書くとき・依存を上げるときに `python3 scripts/python-pin-floor.py requirements.txt` (宣言は同じ dir の `.python-version` を読む)。 宣言が下限より古ければ exit 1。 宣言が wheel の揃う上限より新しければ ⚠️ (その版では source から build しようとする)。 platform ごとの行は、 宣言の版で使える wheel が無い依存を platform ごとに出す = 共同編集者の環境 (Windows の ARM 機・Alpine の image など) で build が要るかを、 その人が試す前に知る
- 文書 (README・引き継ぎ・CLAUDE.md) に版を書くなら「`.python-version` のとおり」 と参照にする。 数字を写すと壊れ方 3 になる

## <a id="python-env-entry"></a>入口 — `tools/py`

Python を起動するのは全部 `tools/py` を通す (`tools/py` の後に script の path か `-c ...`)。 bash の script なので、 macOS・Linux・WSL と Windows の Git Bash で動く。 入口がすること:

- **venv が無ければ作る**。 interpreter の選び方は上から: 明示の `REPO_PYTHON` → 宣言と同じ minor が既にある (探す場所 = [下の表](#python-env-environments)) → uv があれば uv で宣言の版 (無ければ uv が取ってくる。 管理者権限は要らない。 uv は OS・arch・libc に合う build を選ぶ) → 宣言より新しい minor (1 行で告知する。 依存が入らなければ元に戻して止まる。 `REPO_PY_EXACT=1` で使わない)。 **古い minor は使わない**。 macOS の `/usr/bin/python3` (Xcode に従う shim = [`shell-env.md#system-python3-is-xcode-gated`](shell-env.md#system-python3-is-xcode-gated)) と Windows の Store の alias は候補にしない。 版を答えない interpreter は使わない (答えの形 = `3.13.1 <arch>`)。 macOS では機械の arch に合う binary だけを使う ([#python-env-arch](#python-env-arch))
- **requirements が変われば追従する** (`pip install -r`、 venv は作り直さない)。 venv の python が起動しない・宣言より古い版や機械に合わない arch の版で作られていれば作り直す。 作り直すときは前の venv を退けておき、 新しい方が出来なければ元に戻す。 前の venv にあって新しい venv に無い package (手で入れた物) は名前を 1 行出す
- **venv の python の path は venv の形で決める** (Linux・macOS の python = `bin/python` / Windows の python = `Scripts/python.exe`)。 Linux・macOS (WSL を含む) で Windows の python が作った venv (`Scripts/python.exe` だけがある) を見つけたら、 起動も削除もせずに止まる (壊れ方 8)。 その側で `REPO_PY_VENV` を別の dir に向ける (例 `.venv-wsl`。 その dir も `.gitignore` に足す)
- **合う interpreter が無ければ止まる** (exit 3)。 見つかった版の一覧と、 その OS での入れ方 ([表](#python-env-environments) の右の列) を 1 つの文で言う。 黙って全滅しない・黙って別の版で作らない
- **venv が作れないのと依存が入らないのを分けて言う** (壊れ方 7)。 venv の作成の失敗 = ensurepip の package か uv を案内する。 依存の失敗 = 宣言の版の Python を入れる案内 + musl の機械なら musllinux の wheel の話 ([#python-env-pins-dont-install](#python-env-pins-dont-install))
- 速い道: venv が宣言を満たし requirements が前回から変わっていなければ、 何も言わずにそのまま実行する
- 並列の session が同時に呼んでも、 用意は 1 つずつ (lock は `.git/` の中)。 git でない dir (再現用の束など) でも動く (root = `tools/` の 1 つ上)

これは [`#self-provisioning-prerequisites`](../docs/convention-design-principles.md#self-provisioning-prerequisites) の 2 の形: venv を作る・追従させる・uv で interpreter を取ってくるのは判断の要らない作業なので、 点検して待たずにその場でやる。 interpreter を新しく入れる (package manager を使う) のは人の判断なので、 揃うまで毎回言い続ける側に回す。

## <a id="python-env-environments"></a>環境ごとに何を使い、 無いとき何を案内するか (正本の表)

入口 (`tools/py`) が環境ごとに何を見て、 どの python を使い、 合う python が無いとき何を言うか。 本 doc の他の節・雛形の冒頭・test はこの表に合わせる。 「確かめ方」 の R の番号は [`scripts/repo-python-env.test.sh`](../scripts/repo-python-env.test.sh) の test (R41 だけが実機の python3、 他は偽の interpreter で模したもの)。

<a id="python-env-arch"></a>**macOS の arch** — 機械の arch で決める (process の arch でない = Rosetta の shell から呼ばれても同じ)。 候補の arch は**起動せずに** `file -bL` で見る (起動して確かめると、 合わない binary が Rosetta で動いて通知が出るか、 Bad CPU type で落ちる)。 中身の arch が分からない script (pyenv の shim など) は、 組み込みの探し場所では起動しない (`REPO_PYTHON` で明示すれば使う)。

| 環境 | 入口が見るもの | 使う python (上から) | 使わないもの | 合う python が無いときの案内 | 確かめ方 |
|---|---|---|---|---|---|
| Apple Silicon の Mac (Rosetta あり・なし) | `uname -s` = Darwin、 `hw.optional.arm64` = 1 | arm64 を含む binary (universal2 を含む)。 PATH の `python3.X` → Homebrew (`/opt/homebrew`) → MacPorts (`/opt/local`) → python.org → pyenv の版の dir → uv の dir → 汎用の `python3` (PATH・Command Line Tools) → uv → 新しい minor | x86_64 だけの binary (起動すると Rosetta あり = Intel 版の対応終了の通知 / なし = Bad CPU type)、 `/usr/bin/python3`、 pyenv の shim | `/opt/homebrew` の Homebrew で `uv` か `python@3.X`。 Intel 版だけがあるときは「合わない arch の Python はあるが使わない、 arm64 版を入れる」 | 実機 (Apple Silicon の Mac で本物の venv を作った = R41) + R27–R30・R37–R39 |
| Intel の Mac | Darwin、 `hw.optional.arm64` ≠ 1 | x86_64 を含む binary (universal2 を含む)。 探す場所は上と同じ (Homebrew は `/usr/local`) | arm64 だけの binary、 `/usr/bin/python3` | `/usr/local` の Homebrew で `uv` か `python@3.X` | 模しただけ (R31–R34) |
| Linux (glibc。 x86_64・aarch64 など) | `uname -s` = Linux。 arch は見ない ([下](#python-env-why-no-arch-elsewhere)) | PATH の `python3.X` → `/usr/local/bin` → Homebrew on Linux → `/usr/bin` → pyenv の版の dir → uv の dir → PATH の `python3` → uv → 新しい minor | — | uv (管理者権限なし)。 apt があれば `sudo apt install python3.X python3.X-venv` (その版が distribution に無ければ uv)、 dnf があれば `sudo dnf install python3.X`。 venv が作れない (ensurepip が無い) ときは `python3.X-venv` を案内する | 模しただけ (R51・R53・R54) |
| Linux (musl。 Alpine・その image) | 上 + `/lib/ld-musl-*.so.1` があれば musl | 上と同じ (uv は musl の build を取ってくる) | — | uv (package manager は版を選べないことが多い)。 依存が入らないときは「musllinux の wheel が無い依存は source から build する (compiler と header が要る)」 を足す | 模しただけ (R52・R53) |
| WSL | `uname -s` = Linux = 上の Linux の行 | Linux と同じ。 Windows の `python.exe` は PATH の探索に掛からない (bash は `.exe` を補わない) | 同じ checkout の Windows の venv (`Scripts/python.exe` だけ) は起動も削除もせずに止まる | Linux と同じ。 止まったときは「こちら側で `REPO_PY_VENV` を別の dir に」 | 模しただけ (R48–R50) |
| Windows (Git for Windows の Git Bash・MSYS2) | `uname -s` = MINGW・MSYS・CYGWIN。 arch は見ない | PATH の `python3.X` → py launcher (`py -3.X` が答える interpreter) → python.org (`%LOCALAPPDATA%\Programs\Python\Python3X`・`%ProgramFiles%\Python3X`) → uv の dir → pyenv-win → PATH の `python3`・`python` (Store の alias は飛ばす) → uv → 新しい minor。 venv の python = `Scripts/python.exe`。 native の出力の CR を落とし、 `C:\…` の path は `cygpath` で直す | Store の alias (WindowsApps の `python`・`python3`)、 版を答えない interpreter | uv (`winget install --id=astral-sh.uv -e`) か python.org の installer (`winget install Python.Python.3.X`)。 Store の python は使わない | 模しただけ (R42–R47・R55・R56) |
| Windows (PowerShell・cmd だけ) | — | `tools/py` は bash の script = Git Bash から `bash tools/py …` (Claude Code の Windows 版も Git Bash の上で動く = [`windows-msys.md`](windows-msys.md)) | — | Git for Windows を入れる | 確かめていない |
| conda・mamba を使う人 | 特別には見ない | activate した env の `python3.X` は PATH にあるので、 宣言と同じ minor なら使う (conda の env は作らず、 その python から venv を作る)。 決まった env を使うなら `REPO_PYTHON=$CONDA_PREFIX/bin/python` | — | 上の各 OS の行と同じ。 conda で揃えるなら `conda create -n <名前> python=3.X` で作って `REPO_PYTHON` で指す | 模していない (PATH の候補と同じ道 = R54) |
| CI (GitHub Actions) | runner の OS = 上の行 (Linux の runner = glibc、 macOS の runner = その arch の Mac の行、 Windows の runner の `shell: bash` = Git Bash) | `actions/setup-python` の `python-version-file: .python-version` が宣言の版を PATH に置く = 「PATH の `python3.X`」 で使う。 `astral-sh/setup-uv` で uv を置けば uv の段で取ってくる ([#python-env-ci](#python-env-ci)) | — | 止まって exit 3 = job が赤 (理由 1 つ) | 模しただけ (R54 = PATH の `python3.X`)。 runner では走らせていない |
| Docker | image の OS = Linux の行 (Debian 系 = glibc、 Alpine = musl) | 公式の python image は `/usr/local/bin/python3.X` を持つ = 宣言と同じ minor の tag の image なら「PATH の `python3.X`」 で使う。 slim の image に `file` が無くても、 Linux では arch を見ないので困らない | — | Linux の行と同じ | 模しただけ (R54) |

<a id="python-env-why-no-arch-elsewhere"></a>**Linux と Windows で arch を見ない理由** — Linux で別の arch の binary は起動できない (`Exec format error` = 起動できない候補として自然に落ちる) か、 binfmt の emulation で遅く動く (通知は出ない)。 さらに 32 bit の userland を 64 bit の kernel で動かす機械 (Raspberry Pi OS の 32 bit 版など) では、 `file` の arch (32 bit の ARM) と `uname -m` (aarch64) が食い違う = `file` で選ぶと動く python を落とす。 Windows の ARM の機械でも x64 の python は emulation で動く。 起動した時点で通知が出るのは macOS だけなので、 起動前に `file -bL` で選ぶのは macOS だけにしている。 wheel は venv の python の arch に合わせて pip が選ぶ。

**道具ごとの探し場所** (表の「使う python」 の詳細。 実装 = 雛形の `cands_for_minor`):

- **uv** — `uv python find 3.X` (uv があれば) と、 uv が入れた dir (`~/.local/share/uv/python/cpython-3.X*`、 Windows は `%APPDATA%\uv` の下の `python` か `data\python` = どちらかは実機で未確認なので両方を見る)。 uv を消しても、 前に uv が入れた python は使う
- **pyenv** — 版の dir (`$PYENV_ROOT/versions/3.X.*`) の実体だけ。 shim は組み込みの探し場所では起動しない。 pyenv-win は `%USERPROFILE%\.pyenv\pyenv-win\versions`
- **Homebrew** — `python@3.X` の opt の dir と bin の `python3.X` (`/opt/homebrew`・`/usr/local`・Linux の `/home/linuxbrew/.linuxbrew`)
- **MacPorts** — `/opt/local/bin/python3.X`
- **python.org** — macOS = `/Library/Frameworks/Python.framework/Versions/3.X`、 Windows = py launcher と `Programs\Python\Python3X`
- **OS の Python** — macOS は `/usr/bin/python3` を使わず、 Command Line Tools の実体 (`/Library/Developer/CommandLineTools/usr/bin/python3`) を汎用の候補にする (今は 3.9 なので、 宣言が 3.10 以上なら選ばれない)。 Linux は `/usr/bin/python3.X`
- **conda・mamba** — PATH (activate した env) だけ

## <a id="python-env-ci"></a>CI (GitHub Actions) で回す

```yaml
- uses: actions/setup-python@v5
  with:
    python-version-file: .python-version
- run: tools/py --venv-ensure
- run: tools/py verify.py
```

- 宣言の版を runner に置くのは setup-python (か、 `astral-sh/setup-uv` で uv を置いて入口に取らせる)。 workflow に版の数字を写さない (壊れ方 3 と同じ)
- venv を cache するなら、 key に OS・arch・`.python-version`・`requirements.txt` の hash を入れる。 戻した venv の元の python が runner に無ければ、 入口が「起動しない」 として作り直す
- Windows の runner は `shell: bash` (Git Bash) で `tools/py` を呼ぶ
- platform ごとに wheel が揃うかは、 matrix を回す前に `python-pin-floor.py` の platform の行で見る

## <a id="python-env-verify"></a>検算の script は入口を通す

- 検算を一括で回す script は、 **先頭で 1 回 `tools/py --venv-ensure`** を呼び、 失敗したらその理由 1 つで止まる (N 件の FAIL を並べない = 壊れ方 1)。 個々の script も `tools/py` で起動する。 `.venv/bin/python` (Windows では `.venv/Scripts/python.exe`) を直書きしない
- Python の中から子の Python を起動するときは `sys.executable` を使う (path を組まない)
- venv の中の path (`.venv/lib/python3.X/site-packages/...`) を直書きしない = 版と OS で path が変わる。 package の data は package の API (`importlib.resources` など) で引く

## <a id="python-env-pins-dont-install"></a>固定した依存が今の Python で入らないとき

pip が `Could not find a version that satisfies the requirement` か、 新しい pip なら `require a different python version` で落ちたら、 たいてい今の Python が宣言より古い。 順に:

1. **宣言の版の Python を入れる** — uv (`tools/py` が以後自分で取ってくる) か、 package manager の版つきの Python。 入れたら `tools/py --venv-ensure`
2. **既にある interpreter を指す** — `REPO_PYTHON=<path> tools/py --venv-rebuild` (宣言を満たさない指定は止まる)
3. **一時的に今の venv で回すだけなら明示する** — `REPO_PY_ACCEPT_VENV=1`。 入口は何も直さず、 実行のたびに「宣言外の環境」 を 1 行出し、 session 開始の点検も ⚠️ を出し続ける。 その検算の結果は「宣言外の環境での結果」 と書いて報告し、 宣言の環境での PASS と同じ扱いにしない

❌ **版を外した requirements で venv を作って黙って使わない** (壊れ方 2)。 版の幅を正式に支えたいなら、 それは repo の決定 = 別の requirements の file と別の宣言を置き、 両方を検算で回す。 1 台の機械の回避策にしない。

- **musl の機械 (Alpine など)** — 版は合っているのに入らないなら、 その依存に musllinux の wheel が無く、 pip が source から build しようとしている (compiler と header が要る)。 どの依存か = `python-pin-floor.py` の platform の行。 glibc の環境 (Debian 系の image など) で回すか、 build の道具を入れる。 入口は musl の機械で依存が入らないとき、 この 1 文を足す
- <a id="python-env-venv-create-fails"></a>**venv そのものが作れない** — `ensurepip is not available` (Debian・Ubuntu で `python3.X-venv` を入れていない) なら `sudo apt install python3.X-venv` か、 uv を入れる (uv は ensurepip を使わずに venv を作る)。 入口はこれを依存の失敗と分けて言う (壊れ方 7)

## <a id="python-env-session-check"></a>session 開始の点検

collaborator-check の conf に `python tools/py -- <用途>` の 1 行を置く ([`shared-repo.md#collaborator-check`](shared-repo.md#collaborator-check))。 session 開始時に `tools/py --venv-check` (network を使わず、 何も変えない) を聞き、 **人の手が要るときだけ** ❌ / ⚠️ を出す = 宣言の版の Python がこの機械に無い / 宣言外の venv を使っている / 別の OS (Windows) の venv が同じ場所にある。 venv が無い・requirements が変わったは初回の実行で入口が済ませるので出さない。

## <a id="python-env-install"></a>repo に入れる

    python3 <claude-config>/scripts/install-collaborator-check.py install <repo> \
      --item 'python tools/py -- 計算と検算' --python-version 3.13

- 入口を `tools/py` に写す (既に別の `tools/py` があれば置き換えずに言う。 中身を見て置き換えるなら `--replace-python-wrapper`)、 `.python-version` が無ければ書く、 `.venv/` を ignore に足す、 session 開始の点検に載せる。 repo の CLAUDE.md に足す文面を最後に出す
- `check <repo>` = 入口の写しが正本と同じか・宣言があるか・`.venv/` が ignore か
- 写しは repo 単体で動くために置く (共同編集者は claude-config を持たない)。 直すときは正本を直して配り直す
- 検算の script の `.venv/bin/python` の直書きを `tools/py` に替えるのは repo ごとの作業 (installer は script を書き換えない)
- 再現用の束を配るなら、 束に `tools/py`・`.python-version`・`requirements.txt` を入れ、 README の手順を `tools/py` から起動する形にする (束の受け手も同じ入口で venv が出来る)

## <a id="python-env-machine-side"></a>機械の側 — どの Python を入れるか

- **`python3` の向き先を変えない入れ方を選ぶ** — uv が取ってくる Python (uv の dir に入る)、 package manager の版つきの Python (例: Homebrew の `python@3.X` は `python3.X` だけを PATH に置く)。 他の自動化 (hook・定期ジョブ) が今の `python3` と、 そこに入れた package に頼っていることがある ([`shell-env.md#job-python-by-capability`](shell-env.md#job-python-by-capability))。 Homebrew の版の無い `python` (や、 それに依存する formula) は `python3` を Homebrew の版に替え、 PATH で Homebrew が先なら全部の `python3` が替わる
- **venv は機械と OS ごとのもの** — 同期フォルダ (Dropbox など) や、 2 つの OS (Windows と WSL) で開く checkout に、 共有の venv を置かない。 置くなら片方の側で `REPO_PY_VENV` を別の dir に向ける (壊れ方 8)
- 無人ジョブの `python3` 選び ([`shell-env.md#job-python-by-capability`](shell-env.md#job-python-by-capability)) と本 doc は別の問題: ジョブは「依存を import できる既存の interpreter」 を選び、 repo の計算は「宣言の版で作った venv」 を使う
- どの機械に何の Python があるか・入れるか (uv / Homebrew) は機械ごとの事実なので、 公開層に書かず、 個人層の機械別の表に置く ([`docs/personal-layer.md`](../docs/personal-layer.md))
- 依存の下限を上げる PR が Python の下限も上げる話 = [`github-security-automation.md#requirement-floor-vs-python`](github-security-automation.md#requirement-floor-vs-python)

## <a id="isolated-mode-drops-user-site"></a>外から落とした file を読むときの `-I` と user site

- 外から落とした file (download・展開した zip の中身) を読む Python は、 その dir から起動しない: `-c` なら cwd が、 script なら script の dir が sys.path の先頭に入り、 そこに置かれた `json.py` などが標準 library より先に import される
- その対策に `python3 -I` (隔離 mode) を付けると、 `-I` は `-s` と `-E` を含むので **user site (`pip install --user` の入り先) も切れる** = user site にしか入っていない module (PyMuPDF の `fitz` など) が `ModuleNotFoundError` になる (実測)。 依存が入っていないのではない
- user site の module を使うなら、 **自分で作った空の dir に cd して、 `-I` を付けずに** `python3 -c '…' <落とした file の path>` (またはその空の dir に置いた script) を走らせる。 sys.path の先頭は空の dir になり、 落とした file は引数で渡すだけで sys.path に入らない。 Python 3.11 以降は `-P` (sys.path の先頭に cwd・script の dir を入れない、 user site は残す) でも同じ
- venv の python に `-I` を付けても venv の site-packages は残る (切れるのは user site と環境変数)

## <a id="new-syntax-on-old-python"></a>3.10 からの構文の script を古い Python で回したとき

- 型注釈の `X | None` (PEP 604) は 3.10 からの構文。 3.9 で読むと、 関数を定義する時点 (= import の時点) で `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'` で落ちる (実測 = 他所から配られた script の helper)。 script の誤りでなく interpreter の版の問題
- 3.10 以上の python で回す。 macOS の Command Line Tools の python3 は 3.9 ([上の表](#python-env-environments))。 依存も要るなら、 新しい python で作業用の venv を作って入れる (`python3.X -m venv <dir> && <dir>/bin/pip install <依存>`)
- 先頭に `from __future__ import annotations` がある file は注釈を評価しないので落ちない = 落ちるのは、 それの無い file の注釈と、 注釈の外の `|` (`isinstance(x, int | str)` など) = 依存を venv に入れてある repo では `-I` を付けたまま読める
