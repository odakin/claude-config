<!-- doc-meta
when: PATH 消失・shell 環境変数まわりを触るとき + **user に貼り付けて実行してもらうコマンドを chat に書く瞬間** + **Claude が Bash tool で複数の対象を loop で走査する 1-liner を書く瞬間** (= zsh は未 quote の変数を単語分割しない、 `#claude-issued-shell-commands`) + **変数の直後に `:` を書く瞬間** (= `"$c:path"` は zsh の修飾子になる) (= 行内 `#` / `~` の zsh 固有罠。 コマンドを 1 行でも提示するなら該当)
category: macos
summary: シェル環境（PATH 二層防御: .zprofile 修正 + スナップショットパッチ、macOS deny ルール） + ユーザーに貼り付けさせるコマンドの zsh 固有罠 2 件 (= 行内 # はコメントにならない / `env VAR=~/x` は tilde 展開されず literal `~` dir が cwd 配下に生える、 どちらも bash では踏まない非対称。 framework は paste-destined-plain-text.md) + 受け手側の保険 = `.zshrc` に `setopt interactive_comments` (= 1 行で行内/行頭 # とも直るが、 提示先の環境を選べない以上 出し手の規律の代替にはならない) + Claude が発行するコマンドも zsh (= 未 quote の変数は単語分割されず、 cd 失敗後も loop が別の対象を走査して結果を返した 2026-09-11 の 2 件目で規約化。 対象の解決に失敗したら止め、 何を走査したかを印字する。 3 件目 = `"$c:path"` の `:s` が置換修飾子として残りを飲み込み別の object を表示した、 `${c}:path` と書く)
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

### 実測 (2026-09-09、 pty 上の対話 zsh で再現) — 3 つの補強

**(1) 決定的であって確率的でない。** 「短い注釈なら」 「ASCII だけなら」 「1 行だけなら」 は全部誤り。 貼れば必ず argv に化ける:

| 提示した行 | 対話 zsh が実際に渡す argv |
|---|---|
| `git status <SP><SP>#<SP>"rebase in progress"` | `[status, #, rebase in progress]` |
| `git rebase --continue<SP><SP>#<SP>todo 残り 0 なので完了` | `[rebase, --continue, #, todo, 残り, 0, なので完了]` |

2 行目は `git rebase` が余計な引数で **usage error** になって停止し、 続く `git push` が detached HEAD のまま走って `fatal: You are not currently on a branch.` を出した (= 注釈が原因で 2 段の失敗になる典型)。

**(2) 行頭 `#` の単独行でも壊れる。** 「注釈を独立行に逃がせば安全」 は成り立たない — 対話 zsh は `#` をコマンド名として探し `zsh: command not found: #` を出す。 実害は小さい (= その行が失敗するだけ) が、 **エラー出力が増えて本物の失敗を覆い隠す**。 ∴ 貼り付け用ブロックは **`#` を 1 文字も含めない**。

**(3) 第一選択は「注釈を消す」 でなく「script 経路にする」。** 説明を書きたい欲求と貼り付け安全性は**両立できる** — script ファイル内の `#` は正しくコメントになるので、 2 行以上 or quote/glob を含むなら **script を書いて起動 1 行だけを渡す**。 注釈を捨てずに済み、 quote 崩れ・行の取りこぼし・部分実行も同時に消える (= [machine-route-first.md](machine-route-first.md#route-ladder)「経路を先に作る」 の最小 instance)。

```sh
sh "$HOME/Claude/<repo>/scripts/fix-rebase.sh"
```

⚠️ **この失敗は Claude 自身の道具では原理的に観測できない**: Claude の Bash tool は**非対話** zsh なので `#` が正しくコメントとして効く。 Claude は日常的に「`#` は動く」 という体験だけを蓄積し、 壊れる場面は「user の対話プロンプト」 = 自分が一度も立ち会えない場所にしかない。 ∴ **自分の実行経験を根拠にしてはならない**規約 class (= 経験的反証が構造的に得られない)。 とくに **Claude が Bash を失っていて user に手打ちを頼む状況**でこそ発火すべきなのに、 その状況は認知負荷が高く規律が緩む — 発火条件と緩み条件が一致する悪い形をしている。

### 受け手側の保険 — `.zshrc` に `setopt interactive_comments` を 1 行

上は**出し手 (= コマンドを提示する側) の authoring 規律**だが、 **受け手 (= 貼る側) にも 1 行で効く保険**がある。 zsh を対話で使う人は `~/.zshrc` に入れておくとよい:

```sh
setopt interactive_comments
```

実測 (2026-09-09、 pty 対話 zsh): これで**行内 `#` も行頭 `#` も正しくコメントになる** (= 事故行 `git rebase --continue  <SP><SP>#<SP>…` が argv `[rebase, --continue]` に復帰、 行頭 `#` の `command not found: #` も消える)。 bash の既定挙動に揃うので、 bash から来た人の直感とも一致する。

⚠️ **保険が入っても出し手の規律は緩めない** (= 二重防御であって代替ではない)。 理由:

1. **提示したコマンドは提示先の環境を選べない** — 別マシン・別ユーザー・同僚への転送・issue への貼り付け・CI の再現手順に流れる。 `.zshrc` は**その 1 台の 1 ユーザーにしか効かない**
2. **sibling の `~` 罠は直らない** (= `magicequalsubst` は別オプション、 次節)。 「貼り付けコマンドの罠」 は `#` だけではない
3. **script 経路の利点は `#` 以外にもある** — quote 崩れ・glob 展開・行の取りこぼし・部分実行は `interactive_comments` では 1 つも直らない

∴ 保険は「事故の最後の 1 枚」 であって、 第一選択は依然 §「実測 (3) 第一選択は script 経路」。

機械 backstop: Stop hook [`hooks/pasted-command-comment-guard.sh`](../hooks/pasted-command-comment-guard.sh) が「貼り付け指示語 ∧ fence 内の実行系コマンド行に `#`」 で block する (= `setup.sh` が Stop に登録、 selftest 12 件)。 日本語 cue は 2026-07-22..09-09 の 49 日 transcript で校正済 (真陽性 3 / FP 0)、 **英語 cue は推定なので FP 監視対象**。 ⚠️ Claude Code desktop は hook の model 向け出力を honor しない ([hook-authoring.md](hook-authoring.md#frontend-dependent-cowork)) ので desktop では死ぬ — desktop 側の floor は本規約と script 経路の既定化。

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

### <a id="claude-issued-shell-commands"></a>scope の拡張 — Claude が Bash tool で発行するコマンドも zsh (2026-07-30 に 1 件目、 2026-09-11 の 2 件目で規約化)

本節と兄弟節の scope は当初「**user に貼り付けさせる**コマンド」 に限定していた。 だが同じ「**zsh の pattern/parse semantics が bash 前提の想定と違う**」 class は、 **Claude 自身が Bash tool で発行するコマンド**にも及ぶ。 1 件目 (2026-07-30、 上記 incident の検証中):

```sh
l="pre(post)"; print -r -- "${l##*(}"    # zsh: bad pattern: *(  /  bash: post)
l="pre(post)"; print -r -- "${l##*\(}"   # zsh でも通る (= ( を escape)
```

`##` の pattern 内の `(` を zsh は glob 構文として厳しく parse する (= bash は literal 扱い)。 兄弟 2 節と同じ非対称 (bash で書いて zsh で壊れる) だが、 **貼り付けを経由せず Claude 自身の 1 コマンドが失敗するだけ**なので事故 mode が違う (= 即 error・実害なし。 上記 1 件は同 turn に python で書き直して完了)。

**当初 (n=1) は規約化しなかった** (= 「incident 無しで規約を書かない」)。 **un-defer trigger = 同 class の 2 件目** — Claude 自身が発行した shell コマンドが zsh 固有 semantics で壊れる事例を再度観測したら、 本 family の scope を「貼り付け用」 から「Claude が発行する全 shell コマンド」 へ広げる判断に入る (= 現状は「pattern を含む 1-liner は python で書く」 が実務上の回避策で、 規律化する価値があるかは 2 件目まで保留)。 症状 token: `bad pattern:` (= 観測済)、 近縁で未観測 = `no matches found` / `unmatched`。 この記録自体が trigger の成立条件 (= 記録しなければ次の観測者は 1 件目を知らず永遠に n=1 のまま = [debugging-discipline.md #recovery-ends-investigation](debugging-discipline.md#recovery-ends-investigation) の「記録されない残骸は trigger を持たない」 と同型)。

**2 件目 (2026-09-11) で trigger 成立 → Claude が発行する全 shell コマンドへ scope を広げる**。 公開 commit 3 本の追加行を私的な名前で走査する 1-liner を `for spec in "repo hash" …; do set -- $spec; cd ~/Claude/$1; git show … $2 | grep …; done` と書いた。 zsh は未 quote の `$spec` を単語分割しない (bash は分割する) ので `$1` が `"repo hash"` 全体になり、 `cd` は失敗したが loop は続き、 `git show` は直前の cwd にある別 repo の HEAD を走査した。 出力は「168 行、 hit N 件」 というもっともらしい形で、 取り違えは cd の error 行と、 3 対象の行数が同じだったことからしか分からなかった。 1 件目 (即 error) と違い、 **検査が別の対象を検査して結果を返す** = 気付かなければ誤った 0 件や誤った hit が報告に載る mode。

→ **規則**:
1. 複数語を 1 変数に入れて分割に頼らない。 zsh で分割するなら `${=var}`、 そうでなければ配列にする。 対象を列挙して走査する検査は python (`subprocess.run(["git", "-C", path, …])`) で書く。
2. 対象を解決する段 (`cd`、 path・commit の存在) が失敗したら止める。 `cd` せず `git -C <path>` を使い、 解決できなければ `exit 1`。 結果には**何を走査したか** (repo・commit・行数) を印字し、 対象ごとの行数が同じなどの不自然さを見る。
3. pattern を含む 1-liner は python で書く (1 件目の回避策)。
4. 変数の直後に `:` を続けるときは `${var}:` と書く (3 件目、 下記)。

**3 件目 (2026-09-11) — `"$var:…"` は zsh の修飾子になる**。 run 履歴の commit ごとに `git show "$c:scripts/x.test.sh"` (= その commit の file を表示) と書いた。 zsh は `$c` の直後の `:s…` を置換修飾子 (`:s/old/new/`、 区切り文字は `s` の次の 1 文字 = ここでは `c`) と読んで残りの文字列を飲み込み、 `git show 07866f1` (= commit 全体の diff) を実行した。 後段の grep は diff の行を拾って「行番号」 を返し、 別の commit では 0 件になった。 error は出ず、 別の対象を検査した結果がそれらしい形で返る = 2 件目と同じ mode。 zsh 5.9 の実測: `c=07866f1; print -r -- "[$c:scripts/x]"` → `[07866f1` (閉じ括弧まで消える)、 `x=v1; print -r -- "$x:a"` → cwd を前置した絶対 path、 `d=/a/b.c` で `"$d:t" "$d:h" "$d:r" "$d:e"` → `b.c` `/a` `/a/b` `c`。 bash ではどれも literal。 `"${c}:scripts/x"` と波括弧で閉じれば zsh でも literal になる。 `:` の次が修飾子の文字 (`a` `A` `c` `e` `h` `l` `q` `Q` `r` `s` `t` `u` 等) のときだけ壊れるので、 `rev:path`・`host:port`・`$remote:$branch` のどれが壊れるかは見た目では分からない。 常に波括弧で閉じる。

兄弟 = 「Bash tool は bash script ではない」 の別の現れ: [`edit-intent-record.md#apply-then-record`](../../ai-collaboration/conventions/edit-intent-record.md#apply-then-record) の shell 注 (Bash tool の最上位では `set -e` が効かない、 gate を pipe の後ろに置かない、 2026-09-11)。 1 件目を記録していたので 2 件目で規約化できた (上の「記録されない残骸は trigger を持たない」 が機能した例)。

## <a id="bound-command-runtime"></a>Bind reusable command runtimes at installation

A successful `python3` invocation in one shell does not establish the runtime
used from another working directory, login mode, task surface, or PATH. For a
repeated account operation, select and probe a supported interpreter once in
the explicit installer, then generate a launcher with its absolute executable
path and a shell-quoted script path. Do not depend on opportunistically finding
another interpreter's site-packages every time the operation runs.

Audit the executable already bound in the launcher, not a fresh PATH-based
selection. Otherwise the audit can declare a valid installation stale merely
because the caller's PATH changed. Rebinding belongs to explicit installation,
not a read-only check. Test installation idempotency, conflicting user files,
symlink paths, and audit with interpreter discovery disabled.

Use a distinct irreversible subcommand so command-policy rules can target the
stable launcher plus that verb without also matching read or preview. Runtime
availability, policy matching, client loading, and remote delivery are separate
claims. The generic Codex mail installer and its isolated fixtures are
`scripts/codex_mail_install.py` and `scripts/test_codex_mail_install.py`.
The mail transaction contract remains in
[Gmail sending](gmail-sending.md#reviewed-reply-bundle).
