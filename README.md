# claude-config

Shared conventions and setup for managing multiple projects with [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

## What This Is

A central configuration repository that provides:

- **CONVENTIONS.md** — Project-wide rules for file structure, Git workflow, session management, and safety guardrails
- **setup.sh** — One-command bootstrap: creates symlinks and clones all your repos
- **gfm-rules.md** — Quick reference for GitHub Flavored Markdown edge cases with CJK text

The idea is simple: keep one authoritative set of conventions and symlink it into your workspace, so every project follows the same rules without duplication.

## How It Works

```
~/Claude/
├── CONVENTIONS.md → claude-config/CONVENTIONS.md  (symlink)
├── claude-config/          # this repo
│   ├── CLAUDE.md           # project-specific instructions for this repo
│   ├── CONVENTIONS.md      # the single source of truth
│   ├── README.md           # this file
│   ├── setup.sh            # bootstrap script
│   ├── gfm-rules.md        # CJK markdown reference
│   ├── LICENSE             # MIT
│   └── .gitignore
├── project-a/              # your projects
├── project-b/
└── ...
```

Each project's `CLAUDE.md` references `~/Claude/CONVENTIONS.md` for shared rules and adds only project-specific instructions.

## Quick Start

```bash
mkdir -p ~/Claude && cd ~/Claude
gh repo clone <your-username>/claude-config
cd claude-config && ./setup.sh
```

`setup.sh` will:
1. Create `~/Claude/CONVENTIONS.md` as a relative symlink to `claude-config/CONVENTIONS.md`
2. Clone all your GitHub repos into `~/Claude/` (skips repos already present)

## What's in CONVENTIONS.md

| Section | Summary |
|---------|---------|
| §1 Repo creation | `gh repo create` + initial commit recipe |
| §2 Required files | `CLAUDE.md` (permanent instructions), `SESSION.md` (volatile work log), `.gitignore` |
| §3 Auto-update protocol | When and how to update SESSION.md and CLAUDE.md automatically |
| §4-5 Templates | Starter templates for CLAUDE.md and SESSION.md |
| §6 .gitignore | Global and per-project ignore patterns |
| §7 Directory naming | Standard directory names (`src/`, `docs/`, `analyses/`, etc.) |
| §8 Git conventions | Branch strategy, commit messages, push protocol |
| §9 Safety rules | Guardrails for destructive operations, LaTeX editing, credentials |
| §10 Exhaustive verification | Mechanical checks before claiming completeness |
| §11 Miscellaneous | Image output, GFM CJK rules reference |

## Key Concepts

### CLAUDE.md vs SESSION.md

- **CLAUDE.md** = "How to work on this project" — structure, build commands, resume instructions. Updated rarely.
- **SESSION.md** = "Where we are right now" — current task, progress, decisions. Updated continuously.

This separation ensures that after context compression, Claude can always resume from SESSION.md without losing track of work.

### Push-Before-Check

Before every `git push`, Claude automatically verifies that SESSION.md and CLAUDE.md reflect the actual state of the project. This prevents documentation drift.

### Autocompact Recovery

When Claude Code's context window is compressed, the recovery flow is:

1. CLAUDE.md is loaded automatically (always in context)
2. "How to Resume" section directs Claude to read SESSION.md
3. SESSION.md provides current state, tasks, and next steps
4. Work continues seamlessly

This is why SESSION.md accuracy is critical — it's the sole recovery path after context compression.

### Safety Guardrails (§9)

The conventions include strict safety rules to prevent AI-assisted accidents:

- No destructive operations (force push, `reset --hard`, file deletion) without user confirmation
- No credentials or secrets in commits
- No modification of LaTeX equations without explicit approval (prevents hallucinated physics)
- Scope limited to owned repositories only

## Customization

Fork or clone this repo and edit CONVENTIONS.md to match your workflow. The conventions are written in Japanese, but the structure is language-agnostic — translate or adapt as needed.

Key things to customize:
- §1: Replace the GitHub username in repo creation commands
- §4: Adjust the CLAUDE.md template to your project structure
- §7: Modify directory naming conventions for your domain
- §9: Add or remove safety rules for your use case
- `setup.sh`: Change the GitHub username for repo cloning

## License

MIT

---

# claude-config（日本語）

[Claude Code](https://docs.anthropic.com/en/docs/claude-code) で複数プロジェクトを管理するための共有規約とセットアップツール。

## 概要

- **CONVENTIONS.md** — ファイル構造、Git ワークフロー、セッション管理、安全規則をまとめた全プロジェクト共通の規約（正本）
- **setup.sh** — symlink 作成と全リポ clone を一発で行うブートストラップスクリプト
- **gfm-rules.md** — 日本語テキストの GFM bold 崩れ対策リファレンス

## 仕組み

```
~/Claude/
├── CONVENTIONS.md → claude-config/CONVENTIONS.md  (symlink)
├── claude-config/          # このリポ
│   ├── CLAUDE.md           # このリポ固有の指示書
│   ├── CONVENTIONS.md      # 規約の正本
│   ├── README.md           # このファイル
│   ├── setup.sh            # セットアップスクリプト
│   ├── gfm-rules.md        # CJK markdown リファレンス
│   ├── LICENSE             # MIT
│   └── .gitignore
├── project-a/              # 各プロジェクト
├── project-b/
└── ...
```

各プロジェクトの `CLAUDE.md` は `~/Claude/CONVENTIONS.md` を参照し、プロジェクト固有の指示のみ追記する。

## クイックスタート

```bash
mkdir -p ~/Claude && cd ~/Claude
gh repo clone <your-username>/claude-config
cd claude-config && ./setup.sh
```

`setup.sh` が行うこと:
1. `~/Claude/CONVENTIONS.md` → `claude-config/CONVENTIONS.md` の相対 symlink を作成
2. GitHub 上の全リポを `~/Claude/` 以下に clone（既存はスキップ）

## CONVENTIONS.md の構成

| セクション | 内容 |
|-----------|------|
| §1 リポ作成 | `gh repo create` + 初期コミット手順 |
| §2 必須ファイル | `CLAUDE.md`（永続的指示書）、`SESSION.md`（揮発的作業ログ）、`.gitignore` |
| §3 自動更新プロトコル | SESSION.md / CLAUDE.md の自動更新タイミングとルール |
| §4-5 テンプレート | CLAUDE.md / SESSION.md のスターターテンプレート |
| §6 .gitignore | グローバル・プロジェクト固有の除外パターン |
| §7 ディレクトリ命名 | 標準ディレクトリ名（`src/`, `docs/`, `analyses/` 等） |
| §8 Git 規約 | ブランチ戦略、コミットメッセージ、push プロトコル |
| §9 安全規則 | 破壊的操作・LaTeX 編集・機密情報に関するガードレール |
| §10 網羅性の検証 | 「全部」を主張する前の機械的検証 |
| §11 その他 | 画像出力、GFM CJK ルール参照 |

## 核となるコンセプト

### CLAUDE.md と SESSION.md の役割分担

- **CLAUDE.md** = 「このプロジェクトの作業方法」— 構造、ビルドコマンド、復帰手順。更新は稀
- **SESSION.md** = 「今どこにいるか」— 現在のタスク、進捗、決定事項。継続的に更新

この分離により、コンテキスト圧縮後も SESSION.md から確実に作業を再開できる。

### push 前チェック

`git push` の前に、SESSION.md と CLAUDE.md がプロジェクトの実態を反映しているか自動で確認する。ドキュメントの陳腐化を防ぐ。

### autocompact 復帰

Claude Code のコンテキストウィンドウが圧縮された場合の復帰フロー:

1. CLAUDE.md が自動読み込みされる（常にコンテキスト内）
2. 「How to Resume」セクションが SESSION.md の参照を指示
3. SESSION.md が現在の状態・タスク・次のステップを提供
4. シームレスに作業を継続

SESSION.md の正確性が重要な理由 — コンテキスト圧縮後の唯一の復帰パスだから。

### 安全規則（§9）

AI アシスタントによる事故を防ぐための厳格なルール:

- 破壊的操作（force push、`reset --hard`、ファイル削除）はユーザー確認なしに実行しない
- 機密情報・認証情報をコミットしない
- LaTeX の数式は明示的な承認なしに変更しない（物理のハルシネーション防止）
- 操作範囲は自分のリポジトリのみに限定

## カスタマイズ

フォークまたは clone して、CONVENTIONS.md を自分のワークフローに合わせて編集する。

カスタマイズのポイント:
- §1: リポ作成コマンドの GitHub ユーザー名を変更
- §4: CLAUDE.md テンプレートをプロジェクト構造に合わせて調整
- §7: 自分の分野に合ったディレクトリ命名に変更
- §9: ユースケースに応じて安全規則を追加・削除
- `setup.sh`: リポ clone の GitHub ユーザー名を変更

## ライセンス

MIT
