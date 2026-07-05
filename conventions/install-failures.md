# install-failures: machine-local な install 不可 package を memory に蓄積する

同じマシンで `brew install foo` を試行して失敗 → 別セッションで再試行 → 同じ失敗、 という再試行コストを払い続ける問題が起きやすい。 マシン差 (= macOS バージョン / arch / Homebrew Tier 等) に起因する install 不可は **machine-local な事実**であり、 layer 4 (= machine-local memory) の典型用途である。 本規約はその記録運用を定義する。

## Why layer 4 か

「`foo` が install 不可」 という事実は次の理由で **machine-local**:

- 同じ user の別マシン (= 別 arch / 別 OS バージョン) では install 可能なことが多い (= 全マシンで true ではない)
- 「マシン A では不可 / マシン B では可」 という**比較構造** (= layer 3 で扱うべき cross-machine fact) は別軸 (cf. [`personal-layer.md` §「Why does layer 4 isolate machine-local facts?」](../docs/personal-layer.md))
- 単に「**このマシンでは入らなかった**」 という観察は**比較を含まない単独事実**で、 layer 4 が適切な置き場

layer 3 (= 個人層 `<your>-prefs/`) には **規律 / 手順** (= 「`brew info` で bottle 確認」「version manager に逃がす」) を書く。 layer 4 には **個別 package の試行結果** を蓄積する。 補完関係。

## Where に書くか

- **配置**: `~/.claude/projects/<project-slug>/memory/reference_install_failures.md`
- **命名**: ファイル名は **hostname suffix を付けない** (= 1 マシン 1 ファイル、 memory directory は machine-local で git 非同期なので別マシンと collision しない)
- **hostname の明示**: frontmatter の `description` と本文冒頭の「このマシン spec」 セクションに hostname を含める (= 後で別マシンで誤って読んでも自マシンの記録だと判別できる)

## Frontmatter format

```markdown
---
name: <hostname> で install 不可な package 一覧
description: <hostname> (<OS バージョン> / <arch>) 固有の install 不可 package の登録簿。 install 試行前に grep して再試行コストを避ける。
type: reference
---

<!-- machine-local: <hostname> (<OS バージョン>, <arch>) 固有の install 失敗履歴 — 他マシンでは install 可能なことが多いので cross-machine fact ではない -->
```

`<!-- machine-local: ... -->` marker は [`memory-guard.sh`](../hooks/memory-guard.sh) hook の escape hatch として **必須** (= これがないと Write tool が deny する)。 marker の説明文には「**他マシンでは状況が違う**」 旨を 1 行で書いておくと、 後で読み返した時に「なぜ layer 4 にあるか」 が即座に分かる。

## 本文 schema

3 セクション:

### このマシン spec

- `hostname` (`hostname` コマンドの出力)
- `macOS` バージョン (`sw_vers` の `ProductVersion` + `BuildVersion`)
- `arch` (`uname -m`、 例: `x86_64` / `arm64`)
- Homebrew prefix (`brew --prefix`)
- Homebrew tier ([Tier 1 / Tier 2](https://docs.brew.sh/Support-Tiers) のどちらか — Tier 2 だと bottle 縮小)
- Xcode Command Line Tools の状態 (= macOS バージョンに応じた古い CLT を抱えていないか)

### install 不可 (= 試行して失敗を確認した package)

各 entry の必須項目:

- **試行日** (`YYYY-MM-DD`)
- **試行コマンド** (例: `brew install poppler`)
- **失敗原因** (例: Tier 2 bottle 不在 + source build failure、 Command Line Tools 古い、 Apple Silicon 未対応、 etc.)
- **代替手段** (例: Python ライブラリ、 GitHub Releases binary 直置き、 version manager 等)

「重いが最終的に成功した」 系は本ファイルには書かない (= layer 3 の dev-environment.md 等で扱う、 「実例」 と区別)。

### 更新ルール

- 「試して失敗を確認した」 ものだけ書く
- macOS major update / Homebrew tier 変更などの環境変化があったら全 entry の有効性を再検証 (= 古い CLT が原因のものは update 後に install 可能になる可能性)

## How to apply (Claude が brew install する前に)

1. `hostname` を確認 (= 自マシン特定)
2. layer 4 memory の `reference_install_failures.md` を grep (例: `grep -i '<package-name>' ~/.claude/projects/*/memory/reference_install_failures.md`)
3. 該当 package が記録済なら、 **そのまま代替手段を適用** (= 再試行コスト回避)
4. 未記録なら試行 → **失敗時は entry 追加** (= 記録更新ルールを守る)

逆方向の運用 (= `brew install foo` を試して失敗した場合):
1. 失敗の原因を Homebrew のエラーメッセージから特定 (Tier 2 / CLT 古い / etc.)
2. 代替手段を検討 (Python lib / version manager / Releases binary 等)
3. `reference_install_failures.md` の「install 不可」 セクションに新 entry を追加 (= 試行日 + コマンド + 原因 + 代替)

## <a id="prebuilt-binary-fallback"></a>source build 陥落時の定番脱出路: GitHub Releases の prebuilt binary 直置き

`brew install foo` が依存 chain (openssl@3 等) の source build に陥落して数十分コースになったら (= 兆候: `==> Cloning`、 または `ps` に `build.rb` / コンパイラ process が見える)、 完走を待たずにこの fallback を検討する:

1. **upstream の GitHub Releases に prebuilt binary があるか確認** — Go / Rust 製 CLI はほぼ確実にある (git-lfs / gh / ripgrep / fd / jq 等)。 C 依存が深いもの (poppler 等) は無いことが多い
2. `uname -m` で arch を特定 (`x86_64` → release 名は多くの場合 `amd64` / `arm64` はそのまま) → 該当 zip / tar.gz を curl で取得
3. `~/bin` 等 **user 書込可能な場所**に実体を置き、 PATH 上のディレクトリへ symlink (macOS + Homebrew なら `/usr/local/bin` ないし `/opt/homebrew/bin` が admin group 書込可能なことが多い)

コマンド例 (git-lfs):

```bash
V=3.5.1; A=amd64   # A は uname -m から (x86_64 → amd64)
curl -fsSL -o /tmp/git-lfs.zip \
  "https://github.com/git-lfs/git-lfs/releases/download/v${V}/git-lfs-darwin-${A}-v${V}.zip"
cd /tmp && unzip -o -q git-lfs.zip
mkdir -p ~/bin && cp "/tmp/git-lfs-${V}/git-lfs" ~/bin/ && chmod +x ~/bin/git-lfs
ln -sf ~/bin/git-lfs /usr/local/bin/git-lfs
```

運用ノート:

- ⚠️ **install に走る前に、 binary が既にどこかに置かれていないか探す**: `ls ~/.local/bin/<foo> ~/bin/<foo> 2>/dev/null` + layer 4 memory / 個人層 doc を package 名で grep。 「`which foo` が not found」 は「**現在の PATH で**見えない」 であって「マシンに無い」 の証明ではない (= 過去 session が既に直置きしていて PATH 問題だけ、 というケースが実在する。 下の non-interactive PATH trap 参照)
- ⚠️ **配置先は non-interactive shell の PATH に載る場所にする** — `~/.local/bin` 等 **`.zshrc` (= interactive 専用) でしか PATH に足されないディレクトリに置くと、 Claude の Bash tool / launchd / cron からは不可視**で「未 install」 と誤診され、 後日同じ install が再試行される (= 直置き repair が数ヶ月後に silent 再発する構造)。 `/usr/local/bin` (Intel) / `/opt/homebrew/bin` (Apple Silicon) への symlink が確実 (= `.zshenv` レベルで PATH に載る)。 配置後、 **実際に使う非 interactive shell で `which foo` を verify** — interactive shell でだけ通っても意味がない
- 走行中の brew source build は kill してよい (`pkill -9 -f "Formula/.*/<formula>.rb"`)。 依存 chain (llvm 等) の中間ファイルが `/private/tmp/<dep>-YYYYMMDD-*` に **数 GB** 残るので `du -sh` で確認して削除する
- この経路を採った fact (= package / version / 実体の場所 / symlink 先) は layer 4 の「install 不可」 entry の**代替手段**欄に記録する (= 次 session が brew 再試行せず binary 経路を直行できる)

### 付随 gotcha: git-lfs 不在は LFS repo の全 push を block する

Git LFS 設定済み repo では `.git/hooks/pre-push` (LFS 導入時に自動配置) が binary 不在を検出すると **exit 2 で push 全体を block する** — **今回の diff に LFS 管理 file が 1 つも無くても** fail する (= hook は content を見る前に `command -v git-lfs` で門前払い)。 一方 commit 側は post-commit hook が warn を出すだけで**通る**。 症状 signature = 「commit は成功したのに push だけが LFS hook message で fail」。 自分の変更内容を疑う前に **env (binary 有無) を疑う**。 対処 = 上記 prebuilt binary 直置き (LFS content を触らない push なら、 install 後そのまま `git push` が通る)。

## Machine-specific install state vs cross-machine 規律の分担

layer 1 (本ファイル) | 全 Claude Code ユーザーが従う **規律 / format / 配置場所**
layer 3 (個人層) | 自分のフリート全体の **machine 別分岐表 / bottle 規律 / 試行手順** (= 「`brew info` で bottle 行確認」「`==> Cloning` で即 kill」 等の cross-machine 手順)
layer 4 (memory) | このマシン固有の **試行結果蓄積** (= 個別 package の install 不可 list)

3 層が補完的に働く。 layer 4 だけ作って layer 3 (規律) が無いと「失敗時にどう対処するか」 が定まらず、 layer 3 だけで layer 4 (試行結果) が無いと「再試行コスト」 を回避できない。

## なぜ hook 化しないか

「`brew install` を PreToolUse hook で検出して memory grep を強制する」 機械的検出は本規約には含めない。 理由 2 つ:

1. **`brew install` 以外の install 経路** (= `pip`, `npm`, `cargo install`, GitHub Releases binary 直置き、 言語別 version manager 等) も同じ問題を持つので、 `brew install` だけ hook 化すると非対称
2. **失敗の判定** (= 「source build に陥落 = 失敗扱い」「30 分待っても完了しない = kill 推奨」 等) は contextual で hook では難しい

代わりに **Claude / user が `brew install` 試行前に自然に memory を grep する習慣** を docs 規律 + 個人層 (= `<your>-prefs/`) の bottle / 試行手順規律で定着させる。 失敗が反復するパターンが見えてきたら、 その時点で hook 化を再検討。

## 関連

- 4 層モデル正本 + layer 4 の意義: [`docs/personal-layer.md` §「Why does layer 4 isolate machine-local facts?」](../docs/personal-layer.md)
- multi-machine state 全般 (= 同期されない state の扱い): [`conventions/multi-machine-state.md`](multi-machine-state.md)
- memory 書き込み hook (= machine-local marker 必須): [`hooks/memory-guard.sh`](../hooks/memory-guard.sh) + [`hooks/memory-guard-bash.sh`](../hooks/memory-guard-bash.sh)
- convention design principles §8 (memory policy): [`docs/convention-design-principles.md`](../docs/convention-design-principles.md)
