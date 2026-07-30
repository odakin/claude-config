<!-- doc-meta
when: PATH 消失・shell 環境変数まわりを触るとき
category: macos
summary: シェル環境（PATH 二層防御: .zprofile 修正 + スナップショットパッチ、macOS deny ルール） + ユーザーに貼り付けさせるコマンドの zsh 固有罠 2 件 (= 行内 # はコメントにならない / `env VAR=~/x` は tilde 展開されず literal `~` dir が cwd 配下に生える、 どちらも bash では踏まない非対称。 framework は paste-destined-plain-text.md)
-->
# シェル環境（Claude Code + macOS）

## <a id="path-loss-problem"></a>問題

Claude Code（デスクトップ版）は起動時にシェルスナップショット（`~/.claude/shell-snapshots/`）を生成し、Bash ツール実行のたびにそれを source する。スナップショットには `export PATH=...` が含まれ、シェル init で設定した PATH がここで確定する。

問題は二つ:

1. **`.zprofile` の二重 `brew shellenv`**: macOS login shell の起動順は `.zshenv` → `/etc/zprofile`（system `path_helper`）→ `~/.zprofile`。Homebrew の推奨設定（`eval "$(brew shellenv)"`）を `.zshenv` と `.zprofile` の両方に書くと、`.zprofile` の `path_helper`（`PATH_HELPER_ROOT="/opt/homebrew"` 付き）が PATH を再構築し、`.zshenv` の if-blocks で追加した TeX・Python 等を消す。
2. **スナップショット生成時の PATH 欠損**: 上記の結果、スナップショットに不完全な PATH が焼き込まれ、セッション中ずっと引きずる。

### macOS login shell の PATH 構築順

| 順序 | ファイル | path_helper | 読むもの |
|------|----------|-------------|----------|
| 1 | `~/.zshenv` | brew shellenv 経由 (`PATH_HELPER_ROOT=homebrew`) | `/opt/homebrew/etc/paths` のみ |
| 2 | `/etc/zprofile` | **macOS system** | `/etc/paths` + `/etc/paths.d/*`（TeX 含む） |
| 3 | `~/.zprofile` | **ここが問題だった** | 再度 `/opt/homebrew/etc/paths` のみ |

### 試して効かなかった方法

| 方法 | 結果 |
|---|---|
| `~/.zshenv` に PATH 設定 | `.zprofile` の二重 brew shellenv が上書き |
| `launchctl setenv PATH ...` | Claude.app のスナップショット生成に反映されない |
| `settings.json` の `env.PATH` | スナップショットが優先される |
| LaunchAgent plist | 同上 |

## <a id="layer2-main-fix"></a>実態: 第2層が主対策 (2026-04-07 検証)

当初は「第1層 (`.zprofile`/`.zshenv` 修正) で根治、第2層 (snapshot patch) は防御的措置」という設計だったが、Intel Mac での実証で **第1層は Claude Code Bash tool には届かない**ことが判明:

- Login shell では `.zshenv` の `/usr/local/bin` 追加は機能している (`/bin/zsh -l -c 'echo $PATH'` で確認可)
- しかし Claude Code の snapshot 生成プロセスは login shell 経路を通っていない (snapshot ファイルの `export PATH=` 行に `/usr/local/bin` が含まれない)
- Apple Silicon でも同様と思われる (Anthropic 側の snapshot 生成仕様)

**したがって実態は: 第2層 (snapshot patch) が Claude Code 用の主対策、第1層は terminal/login shell 用の補完**。以下の見出しでは「第1層 = 根本対策」と書いているが、これは「terminal 系での根治」の意味で、Claude Code には届かない。

## <a id="two-layer-defense"></a>解決策: 二層防御

### 第1層: `.zprofile` の修正（terminal 用の根本対策）

`.zprofile` から `eval "$(brew shellenv)"` を削除。PATH 設定は `~/.zshenv` に一元化する。Claude Code には届かないが、ターミナルや login shell の挙動は正常化する。

- `~/.zshenv` は全 shell type（login / non-login / interactive / non-interactive）で実行される
- `/etc/zprofile` の system `path_helper` が `/etc/paths.d/TeX` 等を読むので、login shell でも TeX は通る
- `.zprofile` には brew shellenv を書かない（コメントで理由を残す）

```zsh
# ~/.zprofile
# brew shellenv は ~/.zshenv で実行済み（全 shell type 対応）
# ここで二重実行すると path_helper が PATH を再構築し、
# .zshenv の if-blocks で追加した TeX, Python 等が消える問題があった
```

#### `.zprofile` の Python.framework エントリは残す

macOS の Python.framework インストーラ (python.org からインストールしたとき) は `~/.zprofile` の冒頭に以下のような PATH 追記行を挿入する:

```zsh
# Setting PATH for Python 3.9
PATH="/Library/Frameworks/Python.framework/Versions/3.9/bin:${PATH}"
export PATH
```

これは Step 2c の対象外（`brew shellenv` ではないので）。**消すと Python.framework の `python3`/`pip3` が PATH から外れる**ので、残しておくのが正解。Step 2c が消すのはあくまで二重 `brew shellenv` のみ。

### 第2層: スナップショット自動パッチ（Claude Code 用の主対策）

launchd WatchPaths でスナップショットディレクトリを監視し、必須 PATH を補完する。Intel/Apple Silicon どちらでも、Claude Code Bash tool が `command not found` に陥らない唯一の保証はこの層。

PreToolUse フックで毎回パッチする方式は棄却した（理由は DESIGN.md 参照）。

**セットアップ:** `setup.sh` の Step 2 (hooks symlink) + Step 2b (launchd plist) で自動インストールされる。以下は仕組みの説明。

#### パッチスクリプト

`~/.claude/hooks/fix-snapshot-path-patch.sh`（正本: `claude-config/hooks/`）

REQUIRED_PATHS リストで管理。各スナップショットをスキャンし、不足している PATH エントリがあれば先頭に追加する。

- ディレクトリの実在チェック付き（存在しない PATH は追加しない）
- バックスラッシュエスケープ（`\:`）とプレーン（`:`）の両形式に対応
- パターンマッチではなく不足検出方式 — Claude Code のスナップショット形式が変わっても動く

**REQUIRED_PATHS の更新:** 新しいツール（例: Ruby, Go）をインストールしたら、スクリプトの REQUIRED_PATHS 配列に追加すること。

**Intel Mac / Apple Silicon の両対応:** REQUIRED_PATHS には Apple Silicon の `/opt/homebrew/{bin,sbin}` と Intel の `/usr/local/{bin,sbin}` の **両方を併記**する。各エントリは `[ -d ]` で実在チェックされるので、該当しない側は自動的にスキップされ無害。Intel Mac で `/usr/local/bin` が抜けていると `jq` 等の brew インストール CLI が `command not found` になる事故が発生した（2026-04-07）。

**post-merge hook での即時反映:** REQUIRED_PATHS を更新して `git pull` した場合、新規スナップショットは launchd WatchPaths が捕捉するが、**既に生成済みのスナップショットには反映されない**。post-merge hook (`setup.sh` Step 4 で生成) が pull 後に `fix-snapshot-path-patch.sh` を一度実行することで既存スナップショットも即時更新される。

**ニワトリと卵問題 — 他マシンで初回反映するときの注意:** post-merge hook 自体は `.git/hooks/` 配下にあり git で管理されない。post-merge hook の中身を変更するコミット (例: snapshot patch 自動実行ロジックの追加) を他マシンに展開する場合、そのマシンの古い post-merge hook には新ロジックが入っていないので、`git pull` だけでは新版が走らない。**他マシンでは `setup.sh` を 1 回再実行する**ことで `.git/hooks/post-merge` が heredoc から再生成され、以後の `git pull` から新ロジックが走る。`setup.sh` は冪等なので何度実行しても安全。

**REQUIRED_PATHS の順序設計:** patch script は配列を for ループで順次 `prepend` するので、**配列の後ろのエントリほど最終 PATH の先頭に来る**。慣例 (`~/.local/bin` 最優先 → brew → 特殊 → 末尾) に沿うため、配列は逆順で書く（最重要を最後に置く）。**ただしこの順序が効くのは「親プロセス PATH に存在しないエントリ」のみ**。既に存在するものは patch script がスキップするので、順序は親 PATH のまま固定される（= Apple Silicon マシンで `/opt/homebrew/bin` が親 PATH にある場合、その位置は変えられない）。

**snapshot bloat 対策:** Claude Code は古いスナップショットを削除しないので無限に蓄積する。patch script 冒頭で **最新 20 個だけ保持**する cleanup ロジックを実行する。判定はファイルの mtime ではなく**ファイル名に埋め込まれた unix_ms** (`snapshot-zsh-<unix_ms>-<random>.sh`) を使う — patch script 自身が書き換えで mtime を更新してしまうため。sort は subshell `cd` で basename だけを対象にする (フルパスだと親ディレクトリ名 `shell-snapshots` の `-` でフィールド分割がずれて壊れる)。

#### launchd エージェント

`~/Library/LaunchAgents/com.user.claude-snapshot-fix.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.claude-snapshot-fix</string>
    <key>WatchPaths</key>
    <array>
        <!-- plist は $HOME を展開しない。フルパスで記述する -->
        <string>/Users/YOUR_USERNAME/.claude/shell-snapshots</string>
    </array>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/YOUR_USERNAME/.claude/hooks/fix-snapshot-path-patch.sh</string>
    </array>
</dict>
</plist>
```

`launchctl load ~/Library/LaunchAgents/com.user.claude-snapshot-fix.plist` で有効化。

## <a id="macos-deny-rules"></a>macOS システムコマンドの deny ルール

settings.json の `deny` に以下を設定し、破壊的な macOS システムコマンドをブロックする:

```json
"Bash(*tccutil*)",
"Bash(*defaults delete com.apple*)",
"Bash(*csrutil disable*)",
"Bash(*launchctl remove com.apple*)",
"Bash(*launchctl unload com.apple*)"
```

`Bash(*)` パターンはコマンド文字列全体にマッチするため、文字列中に含まれるだけでもブロックされる。正当な用途（grep 等）は専用ツール（Grep, Read）で代替可能なので実害なし。

**背景:** `tccutil reset Calendar` を実行して全アプリのカレンダー権限が消失する事故が発生（2026-04-03）。PreToolUse フックの `exit 2` ではブロックできなかったため、deny ルールで対応。

## <a id="no-inline-comments-in-pasted-commands"></a>ユーザーに渡すコマンドに行内 `#` コメントを付けない (zsh)

macOS の既定 shell は zsh (= 本節と次節は「貼り付け先が terminal のとき」 の ① authoring 規律。 framework 全体 = [paste-destined-plain-text.md #same-framework-other-paste-targets](paste-destined-plain-text.md#same-framework-other-paste-targets))。 **interactive zsh は `interactive_comments` が既定で OFF** なので、対話プロンプトに貼り付けた行の `#` は**コメントにならない** — `#` 以降が glob 修飾子や `claude` 等への余計な引数として解釈され、 コマンドが壊れる / 誤動作する。 bash の interactive は同オプションが既定 ON なので bash ユーザーは平気 = これは zsh 固有の罠 (= macOS 既定 shell なので最も踏みやすい)。

→ **Claude が「ターミナルで実行して」 とユーザーにコマンドを提示するときは、 行内 `#` コメントを付けない**。 説明はコマンドの前後に**散文**で書く。

✅ 安全 (説明は散文、 コマンドは素のまま):

```sh
CLAUDE_CONFIG_DIR="$HOME/.claude-alt" claude auth login
```
（↑ ブラウザで alt アカウントにサインイン、 のように説明はコマンドの外に出す）

❌ 壊れる (貼り付けると `#` 以降が `claude` への余計な引数 / glob になる):

```sh
CLAUDE_CONFIG_DIR="$HOME/.claude-alt" claude auth login   # alt にサインイン
```

例外: **script ファイル内**の `#` は常にコメント (= 非対話 parse なので問題ない)。 本ルールは「ユーザーが対話プロンプトに貼り付ける用に提示するコマンド」 にのみ適用。 ユーザーが `setopt interactive_comments` を `.zshrc` に入れていれば行内 # も通るが、 提示側は「既定 OFF + 環境差」 を前提にできないので、 常に行内 # なしで出す。

## <a id="no-tilde-in-pasted-commands"></a>ユーザーに渡すコマンドに `~` を書かない (zsh は `env` 前置で展開しない)

上の兄弟ルールと同じ「zsh 固有 × 貼り付け用コマンド」 の罠。 zsh は **assignment prefix** (`VAR=~/x cmd`) なら tilde を展開するが、 **`env VAR=~/x cmd` では展開しない** (= コマンド引数中の `=` 以降を tilde 展開する `magicequalsubst` が既定 OFF)。 bash は同等挙動が既定 ON で両方展開するため、 bash で書いて zsh で壊れる非対称になる。

展開されないと `~` が **literal な dir 名**として使われ、 cwd 配下に `./~/…` が生える。 とくに設定 dir を渡す env var (`CLAUDE_CONFIG_DIR` 等) だと、 **誰も見ない場所に状態が書かれる一方で本物の `~/…` は空のまま** = 「認証したのに効いていない」 「設定が反映されない」 という debug しにくい症状になり、 生えた `./~/` は後続の tree scan にも noise として残る。

→ **ユーザーに提示するコマンドでは `~` を使わず `"$HOME/…"` (or 絶対パス) を書く**。 危険が顕在化するのは **`env -u FOO …` のような prefix を足す瞬間**: prefix を足す側は既存の `~` 表記をそのまま残すので、 その 1 手で silent に壊れる。

✅ 安全 (どんな prefix を足しても壊れない):

```sh
env -u ANTHROPIC_API_KEY CLAUDE_CONFIG_DIR="$HOME/.claude-alt" claude auth login
```

❌ 壊れる (`env` 前置で `~` が literal → `<cwd>/~/.claude-alt/` が生える):

```sh
env -u ANTHROPIC_API_KEY CLAUDE_CONFIG_DIR=~/.claude-alt claude auth login
```

**背景 (2026-07-02)**: alt アカウント用 config dir の初回 auth 手順で、 script 自身は絶対パスを印字していた (= script は正しかった) のに、 chat に手順を書き直す段で `~` 表記へ置き換え + `env -u ANTHROPIC_API_KEY` 前置を併記した。 ユーザーがそれを貼って 3 コマンド実行 → `$HOME/~/` と `<base>/~/` の 2 箇所に literal `~` dir が生成され、 6 MB の空 config dir が 4 週間残置した (= 本物の dir は別途正しい手順で auth し直して復旧)。 **script が正しくても chat での書き直しで壊れる** = 提示する文面そのものが検査対象 (= 共通 kernel と他 domain の instance は [paste-destined-plain-text.md #same-framework-other-paste-targets](paste-destined-plain-text.md#same-framework-other-paste-targets)、 4 週間気付かれなかった構造は [debugging-discipline.md #recovery-ends-investigation](debugging-discipline.md#recovery-ends-investigation))。 検出は `find "$HOME" -maxdepth 4 -name '~' -type d`。

### scope の観測境界 — 「貼り付け用」 の外側 (= n=1、 未規約化)

本節と兄弟節の scope は意図的に「**user に貼り付けさせる**コマンド」 に限定してある。 だが同じ「**zsh の pattern/parse semantics が bash 前提の想定と違う**」 class は、 **Claude 自身が Bash tool で発行するコマンド**にも及ぶ。 観測 1 件 (2026-07-30、 上記 incident の検証中):

```sh
l="pre(post)"; print -r -- "${l##*(}"    # zsh: bad pattern: *(  /  bash: post)
l="pre(post)"; print -r -- "${l##*\(}"   # zsh でも通る (= ( を escape)
```

`##` の pattern 内の `(` を zsh は glob 構文として厳しく parse する (= bash は literal 扱い)。 兄弟 2 節と同じ非対称 (bash で書いて zsh で壊れる) だが、 **貼り付けを経由せず Claude 自身の 1 コマンドが失敗するだけ**なので事故 mode が違う (= 即 error・実害なし。 上記 1 件は同 turn に python で書き直して完了)。

⚠️ **n=1 なので規約化していない** (= 「incident 無しで規約を書かない」)。 **un-defer trigger = 同 class の 2 件目** — Claude 自身が発行した shell コマンドが zsh 固有 semantics で壊れる事例を再度観測したら、 本 family の scope を「貼り付け用」 から「Claude が発行する全 shell コマンド」 へ広げる判断に入る (= 現状は「pattern を含む 1-liner は python で書く」 が実務上の回避策で、 規律化する価値があるかは 2 件目まで保留)。 症状 token: `bad pattern:` (= 観測済)、 近縁で未観測 = `no matches found` / `unmatched`。 この記録自体が trigger の成立条件 (= 記録しなければ次の観測者は 1 件目を知らず永遠に n=1 のまま = [debugging-discipline.md #recovery-ends-investigation](debugging-discipline.md#recovery-ends-investigation) の「記録されない残骸は trigger を持たない」 と同型)。
