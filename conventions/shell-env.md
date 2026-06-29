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

macOS の既定 shell は zsh。 **interactive zsh は `interactive_comments` が既定で OFF** なので、対話プロンプトに貼り付けた行の `#` は**コメントにならない** — `#` 以降が glob 修飾子や `claude` 等への余計な引数として解釈され、 コマンドが壊れる / 誤動作する。 bash の interactive は同オプションが既定 ON なので bash ユーザーは平気 = これは zsh 固有の罠 (= macOS 既定 shell なので最も踏みやすい)。

→ **Claude が「ターミナルで実行して」 とユーザーにコマンドを提示するときは、 行内 `#` コメントを付けない**。 説明はコマンドの前後に**散文**で書く。

✅ 安全 (説明は散文、 コマンドは素のまま):

```sh
CLAUDE_CONFIG_DIR=~/.claude-alt claude auth login
```
（↑ ブラウザで alt アカウントにサインイン、 のように説明はコマンドの外に出す）

❌ 壊れる (貼り付けると `#` 以降が `claude` への余計な引数 / glob になる):

```sh
CLAUDE_CONFIG_DIR=~/.claude-alt claude auth login   # alt にサインイン
```

例外: **script ファイル内**の `#` は常にコメント (= 非対話 parse なので問題ない)。 本ルールは「ユーザーが対話プロンプトに貼り付ける用に提示するコマンド」 にのみ適用。 ユーザーが `setopt interactive_comments` を `.zshrc` に入れていれば行内 # も通るが、 提示側は「既定 OFF + 環境差」 を前提にできないので、 常に行内 # なしで出す。
