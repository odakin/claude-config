<!-- doc-meta
when: 新しい Mac を立ち上げるとき + Intel Mac から Apple Silicon Mac へ移行アシスタントで移した直後 + dotfile・script・launchd plist に Homebrew の path や arch を書く前 + `Bad CPU type in executable` / `EBADARCH` / launchd の exit 126 を見たとき + 「どの機械で定期ジョブを回すか」 を arch で決めようとしたとき
category: macos
summary: Intel (x86_64) と Apple Silicon (arm64) の判定は「機械の arch」 と「process の arch (uname -m)」 の使い分け、 Homebrew の prefix は arch で決まる (/opt/homebrew と /usr/local) ので dotfile は arch を見て選び PATH はネイティブ側を先にする。 arch を「どの機械か」 の判定に使わない。 移行アシスタントは Intel の binary・Homebrew・node・Python の拡張・npx cache・git-crypt の filter path・アプリ・launchd plist・同期フォルダの写しをそのまま運ぶので、 Rosetta が無いと全部起動せず、 入れると黙って混ざる。 点検 = scripts/macos-arch-audit.py (読むだけ、 両 arch 対応)
-->
# Intel と Apple Silicon — 自動判定して、 どちらの Mac でも正しく動かす

同じ設定・script を Intel Mac (x86_64) と Apple Silicon Mac (arm64) の両方で使うときと、 Intel から
Apple Silicon へ移ったときの正本。 点検の機械化 = [`scripts/macos-arch-audit.py`](../scripts/macos-arch-audit.py)
(読むだけ。 どちらの arch の機械でも同じに動き、 「この機械ではネイティブで動かないもの」 を列挙する)。

## <a id="detect"></a>判定 — 「機械の arch」 と「この process の arch」 は別

| 知りたいこと | 見るもの | 注意 |
|---|---|---|
| 機械が Apple Silicon か | `sysctl -n hw.optional.arm64` が `1` | Rosetta 下の process からでも本物を返す |
| この process / shell の arch | `uname -m` (`arm64` / `x86_64`) | Rosetta で変換中の shell では `x86_64` を返す (= そのとき選ぶべき Homebrew は x86 側) |
| この process が変換中か | `sysctl -n sysctl.proc_translated` が `1` | |
| binary がどの arch を持つか | `lipo -archs <file>` | `arm64e` は arm64 として扱う。 script では失敗する (= 判定対象外) |

「ネイティブ」 = 機械の arch の slice を持つ binary。 Apple Silicon 機では x86_64 だけの binary、
Intel 機では arm64 だけの binary が異物。 i386 / ppc だけの binary (32-bit 時代のアプリ) はどちらでも起動しない。

## <a id="homebrew-prefix-by-arch"></a>Homebrew の置き場所と PATH の並び

Homebrew の prefix は arch で決まる: **arm64 = `/opt/homebrew`、 x86_64 = `/usr/local`**。
dotfile に `/usr/local/bin` を決め打ちで先頭に置くと、 Apple Silicon 機では (移行で残った) Intel 版が arm64 版を覆い隠す。

`~/.zshenv` (= 非対話 shell・agent の Bash も読む唯一の file) は arch を見て選ぶ:

```sh
# いまの shell の arch に合う brew を優先し、 無ければもう一方
if [ "$(uname -m)" = arm64 ] && [ -x /opt/homebrew/bin/brew ]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -x /usr/local/bin/brew ]; then
  eval "$(/usr/local/bin/brew shellenv)"
elif [ -x /opt/homebrew/bin/brew ]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi
```

login shell では `/etc/zprofile` の `path_helper` が `/etc/paths` (先頭 = `/usr/local/bin`) を PATH の前に押し込み、
上の並びを崩す。 `~/.zprofile` で `brew shellenv` が設定した `$HOMEBREW_PREFIX` を先頭へ戻す
(`brew shellenv` 自体は二重に呼ばない = [`shell-env.md`](shell-env.md)):

```sh
if [ -n "$HOMEBREW_PREFIX" ]; then
  export PATH="$HOMEBREW_PREFIX/bin:$HOMEBREW_PREFIX/sbin:$PATH"
fi
typeset -U path PATH
```

`.zshrc` で PATH を足すときも `/usr/local/bin` と書かず `${HOMEBREW_PREFIX:-/usr/local}/bin` と書く。
script・launchd plist に PATH を焼くときは **両方の prefix を書き、 ネイティブ側を先に**する
(片方しか無い機械では、 無い dir は害が無い)。 候補を順に試す script (`for c in ...`) もネイティブ側を先に。
agent の Bash の snapshot を補う [`hooks/fix-snapshot-path-patch.sh`](../hooks/fix-snapshot-path-patch.sh) も同じ規則で並べる。

## <a id="arch-is-not-a-host-id"></a>arch を「どの機械か」 の判定に使わない

「x86_64 なら常時起動の本番機」 のように arch で機械を見分けると、 機械を買い替えた瞬間に逆向きに外れる
(本番になった新機で判定が偽になり、 退役する旧機で真のまま残る)。 機械の役割は hostname を鍵にした台帳で決める
(= [`multi-machine-state.md#account-host-failover`](multi-machine-state.md#account-host-failover) の
`routine-host-gate.py`、 終了値 0 = この機械が本番)。 arch で分けてよいのは「その arch で動く binary を選ぶ」 ことだけ。

## <a id="migration-intel-to-apple-silicon"></a>Intel から Apple Silicon へ移行アシスタントで移したとき

移行アシスタントは user の領域を丸ごと運ぶので、 **Intel の binary がそのまま来る**。 Rosetta が入っていないと
それらは起動せず (`Bad CPU type in executable` / `EBADARCH` / launchd の `exit 126`)、 Rosetta を入れると
**黙って Intel 版が動き出して arm64 版と混ざる** (例: Intel 版 python3 が arm64 で入れ直した拡張を読めず import で落ちる)。
⚠️ zsh は PATH 上の最初の候補が起動できないと次の候補を黙って試すので、 対話 shell では一部が動いて見える。
`env` 経由・`sh -c`・launchd・git の filter は試し直さないので、 同じ機械で「手で打つと動くのにジョブは落ちる」 になる。

直す順 (どれも元の物を消さず退避してから。 実測の順):

| 何が来るか | 症状 | 直し方 |
|---|---|---|
| Rosetta 未導入 | Intel 専用アプリ (同期クライアント等) が起動しない | `sudo softwareupdate --install-rosetta --agree-to-license` (つなぎ。 下の入れ替えを済ませれば頼らない) |
| `/usr/local` の Intel Homebrew | brew の CLI・`git-crypt`・`gh`・`jq` が起動しない | `/opt/homebrew` に Homebrew を入れ、 自分で入れた formula (各 `INSTALL_RECEIPT.json` の `installed_on_request`) を入れ直す。 `/usr/local/{bin,lib,...}` の Cellar への symlink を退避し、 `/usr/local/Homebrew` 等の本体は root 所有の親の下なので sudo で後片付け |
| 公式 installer の CLI (`~/.local/share/<tool>/versions/*` 等) | その CLI が起動しない | 古い版を退避して公式 installer を再実行。 ⚠️ installer が PATH 上の `jq` 等を呼ぶので、 **PATH を `/usr/bin:/bin:/usr/sbin:/sbin` に絞って**走らせる (Intel 版の補助 binary を掴むと installer ごと落ちる) |
| nvm の node | MCP server・`npx` が起動しない | 版の dir を退避して同じ版を `nvm install <ver>` (PATH を絞って)。 global package は入れ直す |
| npx cache の platform 部品 (`*-darwin-x64`) | native 部品を使う package が落ちる | `~/.npm/_npx/<hash>` ごと消す (次回ネイティブで取り直す) |
| Python の user site の拡張 (`.so`) | numpy・lxml・PyMuPDF 等が import で落ちる | `pip freeze --user` → `pip install --user --force-reinstall --no-deps -r <list>` を arm64 の python で |
| python.org の Framework Python / pyenv の版 | `python3` が Intel 版に化ける | `.zprofile` の Framework を PATH に足す行を外す。 pyenv は版を作り直すか `pyenv global system` |
| repo の venv と、 PATH に無い Intel 版の interpreter (`/usr/local/opt/python@3.X` など) | 版だけを見て interpreter を選ぶ道具が Intel 版で venv を作り、 依存も Intel 版の wheel で入る (Rosetta で動くので気付かない) | venv を arm64 の python で作り直す。 **interpreter の arch は起動せずに `file -bL` で見る** (起動して確かめると、 その時点で Rosetta で動いて「Intel プロセッサ用アプリの対応は終了します」 の通知が出る / Rosetta が無ければ Bad CPU type)。 repo の入口 (`tools/py`) が機械ごとに何を使うか (Intel の Mac・Apple Silicon の Rosetta あり / なし) の表 = [`shared-repo.md#python-env-arch`](shared-repo.md#python-env-arch) |
| git-crypt の filter | `git status` すら `external filter ... git-crypt clean failed 126/127` | unlock 時の git-crypt の**絶対 path** が各 repo の `.git/config` に焼かれている。 `macos-arch-audit.py --fix-git-crypt-paths --repos-root <dir>` が今の git-crypt に書き換える |
| launchd plist | ジョブが毎回 `exit 126` | 生成した installer を再実行して plist を作り直す (焼かれた PATH・interpreter・機械名も更新される) |
| アプリ | Rosetta 頼み / 32-bit は起動不能 | Homebrew cask で入れ直す (旧 bundle を退避してから。 ⚠️ cask が**同じ bundle id** かを先に確かめる = 改名したアプリで別物を入れない。 `.pkg` の cask は sudo が要る。 配布停止の cask もある)。 32-bit (i386 / ppc だけ) は削除候補。 種類ごとの入れ替え方 = 下の [§アプリの入れ替え](#app-replacement) |
| クラウド同期フォルダ (File Provider) | 同期クライアントが「フォルダが見つからない」 / 二重 | `~/Library/CloudStorage/<service>` は File Provider として移らず、 **ただのフォルダの写し**として来る。 写しを同期フォルダとして拾わせない (古い写しが、 移行後にクラウド側で消したファイルを復活させうる) = 写しを改名して退避 → 同期クライアントを入れ直して再リンク → 同期後に写しとの差を点検してから写しを消す |
| CLI の認証 (keychain) | headless の CLI が未 login | config-dir ごとに login し直す ([`remote-control-server.md#account-auth-keychain`](remote-control-server.md#account-auth-keychain)) |

⚠️ `brew` を `while read` の loop の中で呼ぶと、 brew が loop の入力を食べて 2 件目以降が黙って飛ぶ = `brew ... </dev/null`。

### <a id="app-replacement"></a>アプリの入れ替え (実測)

棚卸し = `macos-arch-audit.py` の「アプリ」 節か、 `system_profiler SPApplicationsDataType -json` の `arch_kind`
(`arch_i64` = Intel だけ / `arch_i32`・`arch_other` = 32-bit・PPC の混在 = 起動しない)。 ⚠️ 移行直後は Spotlight の
最終使用日 (`kMDItemLastUsedDate`) が全部空 = 「使っていないアプリ」 の判定に使えない。 旧 bundle は消さずに退避先へ移す
(入れ替えが合わなければ戻せる)。

| 種類 | 入れ替え方 |
|---|---|
| cask があり bundle id が同じ | 旧 bundle を退避 → `brew install --cask <name> </dev/null` → main executable を `lipo -archs` で確かめる。 `app` artifact の cask は sudo 不要 (root:admin 所有の bundle でも admin group に書込権があれば退避できる) |
| cask の後継が別 bundle id (版番号つきの id・改名) | 既定アプリが旧 bundle id のまま残る = 関連付けを書き換える ([`macos-side-by-side-app-migration.md#file-association-engine`](macos-side-by-side-app-migration.md#file-association-engine))。 ⚠️ 有料アプリは旧版のライセンスが新版で通るとは限らない = 旧版を退避先に残し、 認証が通らなければ戻す |
| `.pkg` の cask | sudo が要る = 1 本の script にまとめ、 user が terminal のタブでパスワードを 1 回入れる。 arch 別の sub-pkg (`*_arm64.pkg`) を内包する pkg もある = 頼む前に `pkgutil --expand-full` で中身の arch を確かめる。 ⚠️ cask が最新版を指していても中身が Intel だけのことがある (実測) = Payload の main executable を `lipo -archs` で見てから sudo を頼む |
| cask の URL が Intel 版 / ベンダーが配布終了 | ネイティブ版が無い = Rosetta のまま残すか web 版などで代替。 user に判断を渡す |
| ベンダーの dmg に使用許諾 (SLA) が付く | `hdiutil attach` を stdin なしで呼ぶと `attach canceled` で止まる (事前に分かる = `hdiutil imageinfo <dmg>` の `Software License Agreement: true`)。 同意は user の行為 = `open <dmg>` で同意の画面を出し、 `/Volumes/<名前>*` が現れるまで待つ loop を background で回して、 現れたら arch を確かめて写す (同意の後は待たせない) |
| formula が `.app` を作る (Qt の viewer など、 cask が無効化されている) | `brew install <formula>` の後、 `/Applications/<App>.app` を `/opt/homebrew/opt/<formula>/<App>.app` への symlink にする (`opt` の path は版を上げても変わらない)。 formula を消すとアプリも消える = その旨を機械の記録に書く |
| Java の `.app` (`JavaApplicationStub` / `JavaAppLauncher` が Intel、 同梱 JRE も Intel) | jar は arch 非依存。 arm64 の JDK (`brew install openjdk`) を入れ、 `Contents/MacOS/<CFBundleExecutable>` を `exec /opt/homebrew/opt/openjdk/bin/java <Info.plist の JVMOptions> -cp <jar> <main class>` の shell script に差し替える。 確認 = `-Djava.awt.headless=true` で `HeadlessException` まで進めば class は読めている + `open -g -a` で起動した java process が arm64 |
| Unity エディタ (Hub の `Editor/<版>/`) | Hub の `--headless` は移行直後に応答しないことがある。 release API (`services.api.unity.com/unity/editor/release/v1/releases?version=<版>&architecture=ARM64&platform=MAC_OS`) から `MacEditorInstallerArm64/Unity-<版>.pkg` を取り、 `pkgutil --expand-full` の Payload (`Unity/`) を `Editor/<版>/` に置けば sudo 不要。 `Documentation`・`modules.json`・言語の `.po` は旧 install から写せる。 ⚠️ WebGL 等の target module は arch 共通の 1 本で中の toolchain が x86_64 = その build だけは Rosetta が要る |
| 32-bit だけ | 起動しない。 後継が入っているなら退避 (新旧が同じ bundle id を持つ一式は LaunchServices がどちらを引くか曖昧になる) |
| 消えたアプリ・Intel だけの部品を起動する LaunchAgent | `launchctl bootout gui/$(id -u)/<label>` → plist を退避先へ (点検の「LaunchAgents」 節が対象を出す) |
| 自動更新係 (`/Library/Application Support/<vendor>/<Updater>/` と `~/Library/Application Support/...`) | 移行で来た Intel 版の更新係は Rosetta の下で自分を x64 と名乗って更新を取る (実測: updater の log の request が `"arch":"x64"`、 OS は arm64) = 本体を入れ替えても次の更新で Intel 版に戻りうる。 本体に同梱の universal 版 (`<App>.app/Contents/.../Helpers/<Updater>.app`) で入れ直す。 system の Chromium 系 updater は `sudo <Intel 版> --uninstall --system` → `sudo <同梱版> --install --system` で、 入った版が universal・`ARM_64` で動くことを log で確かめた (実測)。 user 領域の更新係は退避すれば本体が次の起動で同梱版を入れる想定 (未確認)。 点検の「アプリ」 節がこの置き場も見る。 Sparkle などが残した旧版の写し (`<App> <版>/`) も同じ置き場に出る = 本体がネイティブなら片付けの対象 (ゴミ箱へ) |

| 古い browser plug-in・設定 pane (`/Library/Internet Plug-Ins/*.plugin`・`/Library/PreferencePanes/*.prefPane`。 例 = Java の plug-in と設定 pane) | 今の browser は plug-in を読まないので、 本体ごと要らない。 中の更新係が `/Library/LaunchAgents`・`/Library/LaunchDaemons` の plist から Rosetta で常駐する (実測)。 sudo で `launchctl bootout` → plug-in・pane・plist を退避先へ (点検の「LaunchAgents」「動いている process」「アプリ」 の 3 節が出す) |

点検の終わり = `macos-arch-audit.py` の「実行経路に別 arch なし」 + 定期ジョブを 1 本手で回して最後まで走ること。
アプリ・npx cache・退避した Intel Homebrew の残置・Rosetta で常駐する process・PATH の外の Framework Python・
base が別 arch か消えた venv (`--repos-root` を付けると repo の venv も) は 🟠 として出続ける (= 片付けるまでの carrier)。

## <a id="who-launched-intel"></a>「Intel プロセッサ用アプリの対応は終了します」 が出たとき — 何が Intel 版を起動したか

- この通知は、 Apple Silicon の機械で x86_64 だけの binary が Rosetta で起動したことを示す。 通知の名前と icon は起動した bundle のもの
  (例: 「"Python"」 とロケットの icon = python.org の Framework 版 Python の `Python.app`)。 今は動くが、 Rosetta を外す将来の macOS では起動しなくなる、 という予告。
- **時刻**は unified log で分かる: `/usr/bin/log show --last 1h --style compact --predicate 'eventMessage CONTAINS "rosettaAnalyze"'`
  (`ecosystemanalyticsd` が起動ごとに行を出す)。 path は `<private>` で伏せられるので、 何が起動したかは log からは分からない。 zsh では `log` を full path で書く ([`shell-env.md#zsh-log-builtin`](shell-env.md#zsh-log-builtin))。
- **常駐しているもの** = `macos-arch-audit.py` の「動いている process」 節 (`ps -axo comm=` の実行 file を `lipo -archs` で見る)。
  `/System` の下には x86_64 だけの Apple の部品 (古い音声 plug-in を調べる `CarbonComponentScannerXPC` など) があり、 Rosetta で動くのが正常なので、 この節の一覧には出さない。
- **1 回起動して終わったもの** (道具が interpreter を版で探し `--version` を打った、 など) は process に残らない。 agent の session が起動したなら、 会話記録を path で引く:
  `python3 scripts/search-agent-transcripts.py --tool-runs --since <日> --regex '<path の正規表現>'` (subagent の呼び出しも、 親の session の id で出る)。
  ⚠️ desktop の `search_session_transcripts` は記録の一部しか検索しない ([`multi-session-coordination.md`](multi-session-coordination.md) の caveat) = 0 件を「どの session も起動していない」 の根拠にしない。
- 直し方 = 起動したものの種類ごとに、 上の 2 つの表で。 候補を起動して arch を確かめる道具は、 起動せずに `file -bL` / `lipo -archs` で見る形に直す
  (実装例 = [`shared-repo.md#python-env-arch`](shared-repo.md#python-env-arch) の `tools/py`)。

## 関連

- PATH の rc file と shell の種類の対応 = [`shell-env.md`](shell-env.md)
- 機械の役割 (本番ホスト) の台帳 = [`multi-machine-state.md#account-host-failover`](multi-machine-state.md#account-host-failover)
- install の失敗の記録の仕方 = [`install-failures.md`](install-failures.md)
- 旧新版アプリの並存の片付け = [`macos-side-by-side-app-migration.md`](macos-side-by-side-app-migration.md)
