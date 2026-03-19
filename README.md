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
│   ├── CONVENTIONS.md      # the single source of truth
│   ├── setup.sh            # bootstrap script
│   └── gfm-rules.md        # CJK markdown reference
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
| §4–5 Templates | Starter templates for CLAUDE.md and SESSION.md |
| §6 .gitignore | Global and per-project ignore patterns |
| §7 Directory naming | Standard directory names (`src/`, `docs/`, `analyses/`, etc.) |
| §8 Git conventions | Branch strategy, commit messages, push protocol |
| §9 Safety rules | Guardrails for destructive operations, LaTeX editing, credentials |

## Key Concepts

### CLAUDE.md vs SESSION.md

- **CLAUDE.md** = "How to work on this project" — structure, build commands, resume instructions. Updated rarely.
- **SESSION.md** = "Where we are right now" — current task, progress, decisions. Updated continuously.

This separation ensures that after context compression, Claude can always resume from SESSION.md without losing track of work.

### Push-Before-Check

Before every `git push`, Claude automatically verifies that SESSION.md and CLAUDE.md reflect the actual state of the project. This prevents documentation drift.

## Customization

Fork or clone this repo and edit CONVENTIONS.md to match your workflow. The conventions are written in Japanese, but the structure is language-agnostic — translate or adapt as needed.

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
│   ├── CONVENTIONS.md      # 規約の正本
│   ├── setup.sh            # セットアップスクリプト
│   └── gfm-rules.md        # CJK markdown リファレンス
├── project-a/              # 各プロジェクト
├── project-b/
└── ...
```

各プロジェクトの `CLAUDE.md` は `~/Claude/CONVENTIONS.md` を参照し、プロジェクト固有の指示のみ追記します。

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
| §4–5 テンプレート | CLAUDE.md / SESSION.md のスターターテンプレート |
| §6 .gitignore | グローバル・プロジェクト固有の除外パターン |
| §7 ディレクトリ命名 | 標準ディレクトリ名（`src/`, `docs/`, `analyses/` 等） |
| §8 Git 規約 | ブランチ戦略、コミットメッセージ、push プロトコル |
| §9 安全規則 | 破壊的操作・LaTeX 編集・機密情報に関するガードレール |

## 核となるコンセプト

### CLAUDE.md と SESSION.md の役割分担

- **CLAUDE.md** = 「このプロジェクトの作業方法」— 構造、ビルドコマンド、復帰手順。更新は稀
- **SESSION.md** = 「今どこにいるか」— 現在のタスク、進捗、決定事項。継続的に更新

この分離により、コンテキスト圧縮後も SESSION.md から確実に作業を再開できます。

### push 前チェック

`git push` の前に、SESSION.md と CLAUDE.md がプロジェクトの実態を反映しているか自動で確認します。ドキュメントの陳腐化を防ぎます。

## カスタマイズ

フォークまたは clone して、CONVENTIONS.md を自分のワークフローに合わせて編集してください。

## ライセンス

MIT
