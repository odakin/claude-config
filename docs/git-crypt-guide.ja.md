# git-crypt で機密リポを暗号化する

> **English version**: [git-crypt-guide.md](git-crypt-guide.md)
>
> **関連**: [sensitive-repo-patterns.ja.md](sensitive-repo-patterns.ja.md) — git-crypt を使った機密リポの設計パターン集 (ファイル名・commit message・ブートストラップ経路・公開面の最小化など、ツールの使い方よりも一段上の運用設計)

[git-crypt](https://github.com/AGWA/git-crypt) は Git リポジトリ内のファイルを透過的に暗号化する。push 時に暗号化、clone/pull 時に復号されるため、ローカルでは平文で作業しつつ GitHub 上は暗号文で保存できる。

## クイックスタート

### 1. インストール

```bash
brew install git-crypt    # macOS
sudo apt install git-crypt # Debian/Ubuntu
```

### 2. リポで初期化

```bash
cd my-sensitive-repo
git-crypt init
```

対称鍵が `.git/git-crypt/` 内に生成される。バックアップと共有のためにエクスポートが必要。

### 3. 鍵のエクスポート

```bash
mkdir -p ~/.secrets
git-crypt export-key ~/.secrets/git-crypt.key
chmod 600 ~/.secrets/git-crypt.key
```

> **なぜ `~/.secrets/`？** `setup.sh` がこのパスを自動検出し、ブートストラップ時（Step 5b）に暗号化リポを自動 unlock する。別のパスを使う場合は `setup.sh` を更新すること。

### 4. `.gitattributes` の設定

リポルートに `.gitattributes` を作成し、暗号化対象を指定する：

```gitattributes
# デフォルトで全ファイル暗号化、例外をホワイトリスト
* filter=git-crypt diff=git-crypt

# これらは暗号化しない
CLAUDE.md !filter !diff
.gitignore !filter !diff
.gitattributes !filter !diff
```

または特定ディレクトリのみ暗号化：

```gitattributes
# 機密ディレクトリのみ暗号化
data/** filter=git-crypt diff=git-crypt
private/** filter=git-crypt diff=git-crypt
SESSION.md filter=git-crypt diff=git-crypt
```

### 5. コミット・push

```bash
git add .gitattributes
git add .  # 暗号化ファイルも通常通り add
git commit -m "Initial commit (git-crypt encrypted)"
git push
```

`.gitattributes` のパターンにマッチするファイルが GitHub 上で暗号化される。

## CLAUDE.md テンプレート

リポの `CLAUDE.md` 冒頭に以下を追加：

```markdown
**⚠️ このリポは private 必須。<理由>を含むため、絶対に public にしないこと。**

**git-crypt 有効。** <ファイル> が読めない場合 → `brew install git-crypt` → `git-crypt unlock ~/.secrets/git-crypt.key`
```

## 1つの鍵を複数リポで共有する

リポごとに新しい鍵を生成する代わりに、同じ鍵を使い回せる：

```bash
cd another-repo
git-crypt init           # 新しい鍵が生成される（無視される）
git-crypt unlock ~/.secrets/git-crypt.key  # 共有鍵で置き換え
```

**トレードオフ**: 鍵管理がシンプルになるが、1つの鍵が漏洩すると全リポが露出する。全リポが同一オーナーで脅威モデルが同じなら許容範囲。

## 別端末でのセットアップ

1. 鍵ファイルを安全に転送（暗号化バックアップ、SSH 経由の直接コピー等）
2. `~/.secrets/git-crypt.key` に配置し `chmod 600`
3. `setup.sh` を実行 — git-crypt リポを自動検出・unlock

手動 unlock も可能：

```bash
cd my-sensitive-repo
git-crypt unlock ~/.secrets/git-crypt.key
```

## 共有リポでの自動復元 (`.claude/git-crypt-backup` 経路)

共有 git-crypt 鍵を使う collaborative リポでは、**鍵バックアップを暗号化してクラウドストレージ (Dropbox / Google Drive / iCloud Drive 等) に置き、setup.sh で全自動復元**するパターンを推奨する。共同編集者が新端末でセットアップする時、Dropbox 内のフォルダ構造を覚えていなくても (= 共有フォルダのマウント先がデバイス間で違っていても) 動く。

### 仕組み

リポルートに `.claude/git-crypt-backup` ファイルを置き、暗号化バックアップの **ファイル名 (パスではない) を 1 行**で記載:

```
my-sensitive-repo.key.enc
```

新端末で `setup.sh` を実行すると、**Step 5b-pre** が以下を行う:

1. 各リポの `.gitattributes` に `git-crypt` 設定があるかチェック
2. `~/.secrets/<repo>.key` が既にあれば skip
3. なければ `.claude/git-crypt-backup` のファイル名を読み、クラウドストレージ root を `~/Dropbox` 等から resolve (`scripts/dropbox-root.sh`)
4. `find <storage-root> -maxdepth 5 -name "<filename>"` で暗号化バックアップを発見
5. `openssl enc -aes-256-cbc -d -pbkdf2` で復号 (パスフレーズ入力のみ対話)
6. `~/.secrets/<repo>.key` に配置 (mode 600)

その後 **Step 5b** が `git-crypt unlock` を自動実行する。

### 共同編集者向け運用

このパターンを採用するリポでは、collaborator 向け README に以下を **必ず最優先で**記載:

```bash
# 推奨: claude-config の setup.sh で全自動復元 + unlock
gh repo clone <your-config-repo>/claude-config
cd claude-config && ./setup.sh
# → パスフレーズプロンプトに答えるだけ
```

**手動 `openssl enc -d ...` を最初に書かない**。手動経路は「setup.sh の前提が崩れた時の最後の砦」として fallback 節に置く。理由:

- 手動経路はクラウドストレージ内の literal path を覚えている必要があり、collaborator の環境で path がズレると file-not-found に陥る
- placeholder 入りの中継ドキュメントを読んだ場合、prompt 上で誤展開されて誤った path で openssl を投げる事故が起きる
- bad decrypt 時に exit code を確認しないと garbage を `~/.secrets/` に残し、後続セッションで「鍵があるが unlock 失敗」状態になり原因究明が長引く

`setup.sh` Step 5b-pre は `find` で path 非依存にし、復号失敗時は warning を出してファイルを残さない。**手動 openssl では同等の防御を毎回書き直すコストがあるため、機械化された経路を最優先にする**。

### セットアップ例 (公開しても安全な記述例)

リポの README:

```markdown
## 共同編集者向けセットアップ

**Quick start (推奨)**: `claude-config` の setup.sh で全自動。
\`\`\`bash
brew install git-crypt gh
gh auth login
gh repo clone <your-config-repo>/claude-config
cd claude-config && ./setup.sh
# パスフレーズは out-of-band で受領 (対面 / Signal 等)
\`\`\`

**手動セットアップ (fallback)**: setup.sh が動かない場合のみ。
\`\`\`bash
# 1. 暗号化鍵を Dropbox 共有フォルダから openssl で復号
mkdir -p ~/.secrets
openssl enc -aes-256-cbc -d -pbkdf2 \
  -in ~/Dropbox/<shared-folder>/keys/my-repo.key.enc \
  -out ~/.secrets/my-repo.key
chmod 600 ~/.secrets/my-repo.key
# 2. リポを clone + unlock
gh repo clone <your-org>/my-repo
cd my-repo && git-crypt unlock ~/.secrets/my-repo.key
\`\`\`

Dropbox の共有フォルダパスが手元と違う場合: `mdfind -name "my-repo.key.enc"` (macOS) で検索。
```

## 鍵のバックアップ

**鍵ファイルはデータを復号する唯一の手段。** 紛失してバックアップがなければ、GitHub 上の暗号化ファイルは復元不能。

推奨プラクティス：
- 暗号化したバックアップを別の場所に保管（クラウドストレージ、USB ドライブ等）
- バックアップの暗号化には強いパスフレーズを使用
- 定期的に復元テストを実施

## トラブルシューティング

### clone 後にファイルがバイナリ表示される

リポがロック状態。`git-crypt unlock ~/.secrets/git-crypt.key` を実行。

### git 操作中に `git-crypt: command not found`

git filter が `git-crypt` の絶対パスを使用している。`.git/config` を確認：

```ini
[filter "git-crypt"]
    smudge = "git-crypt" smudge
    clean = "git-crypt" clean
    required = true
```

パスが絶対パス（例: `/usr/local/Cellar/git-crypt/0.8.0/bin/git-crypt`）の場合、git-crypt の再インストールやアップグレード後に更新が必要。

### `setup.sh` がリポを unlock しない

Step 5b は以下の両方が揃った場合のみ実行される：
- `git-crypt` がインストール済み
- `~/.secrets/git-crypt.key` が存在する

どちらか一方でも欠けていればサイレントスキップされる。

### `git diff --stat` が encrypted file を「Bin N -> 0 bytes」 と誤解させる表示

git-crypt 暗号化対象 file (= `.gitattributes` で filter=git-crypt 指定) が working tree clean 状態でも `git diff --stat` で「`Bin 22 -> 0 bytes`」 等の差分があるように表示されることがある (= 特に `.gitkeep` 等の空 plain content を持つ file)。

**真因**: git-crypt の clean/smudge filter は encrypt 時に header + IV を付与するため、 plaintext 0 byte の `.gitkeep` は encrypted 22 bytes になる。 `git diff --stat` は表示時に **HEAD stored size (= encrypted 22) と working tree decrypted size (= 0) を mix 比較** する UI 挙動で、 あたかも差分があるように見える。

**確認方法**:
```bash
git status                                    # ← clean (= 実態は stage 差分なし)
ls -la <file>                                 # ← 0 byte (= working tree 実体)
git cat-file -p HEAD:<file> | wc -c           # ← 22 (= HEAD stored encrypted size)
git-crypt status <file>                       # ← encrypted ✓
git add <file> && git status                  # ← stage されない (= SHA 同一)
```

**実害**: なし。 `git status` clean + `git add` で stage されない = git は content 同一性を SHA で正しく判定している、 `--stat` の表示 UI のみが mix 表示で誤解を招く。

**corollary (= committed 版の field 比較には `git show` を使えない)**: `git cat-file -p HEAD:<file>` / `git show <rev>:<path>` は git-crypt'd file に対して **ciphertext を返す** (= clean/smudge filter は working tree ↔ blob 変換でのみ走り、 `git show <rev>:` 出力には適用されない)。 → committed 版の plaintext field を parse して working tree と比較する (= 例: live API test の token-refresh で drift した OAuth credential の durable `refresh_token` が不変かを確認) ことは `git show` では**不能** (= UnicodeDecodeError)。 こういう時は git diff に依存せず semantics (= 標準的 OAuth access_token refresh は refresh_token を rotate しない) で判断し、 ephemeral drift は `git checkout --` で破棄する (= MCP server を live test する場合の手順は [`conventions/mcp.md` runbook §1](../conventions/mcp.md#runbook-handshake-check))。

**RCA reflex**: sweep / audit で「想定外の bin diff」 を観察したら、 まず上記 5 step で「git-crypt encrypted file の表示挙動」 を rule out。 「leak / corruption / 別 session の touch」 と reflex 結論しない (= [`conventions/debugging-discipline.md §9`](../conventions/debugging-discipline.md#mcp-zero-result-not-absence) 「count return 0 reflex」 と同 trait family の git-diff display domain での現れ)。

**実例 (= 2026-05-26 観察)**: ある講義運営 repo の 12 file の `.gitkeep` (= 各 `exams/`, `grades/` 配下) が複数の sweep で「`Bin 22 -> 0 bytes`」 と一斉に表示、 working tree clean + git-crypt encrypted の状態だった。 上記 5 step で transient = leak / bug でなく git-crypt 表示挙動と判明。
