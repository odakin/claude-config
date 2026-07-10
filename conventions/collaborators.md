<!-- doc-meta
when: 共同研究者 DB (collaborators.yaml) を作成・更新するとき
category: research-domain
summary: 共同研究者DB規約
-->
# 共同研究者DB規約

共同研究者の管理ルール。CLAUDE.md から参照: `~/Claude/claude-config/conventions/collaborators.md`

## 正本

`~/Claude/research-collab/collaborators.yaml`（git-crypt 暗号化）

## スキーマ

```yaml
- id: slug                    # 短い識別子（姓のローマ字小文字）
  name_en: "Full Name"        # 英語名
  name_ja: "氏名"             # 日本語名（不明なら null）
  aliases: ["愛称"]           # 会話で使う呼称・愛称（あれば、disambiguation 用）
  affiliation: "所属"         # 不明なら null
  email: "primary@example.com"
  alt_email:                  # 複数メールがある場合
    - "alt1@example.com"
  inspire_id: null            # INSPIRE 著者ID（あれば）
  discord_id: null            # Discord 数値 ID（arxiv-digest 等で mention に使う、あれば）
  github_handle: null         # GitHub username（共同編集リポで push 권があるなら必須）
  projects: [project-id]      # 関連プロジェクト（projects.yaml の id）
  notes: null                 # 備考
```

## 運用ルール

- **追加タイミング**: 新しい共同研究者とメールやり取りが始まったとき
- **email の一次情報源**: 論文共著者の email / 所属は、その論文 draft の `\author` / `\email` ブロックが authoritative（= 共著者本人が Overleaf 等で維持している）。連絡先が registry に無いとき、contacts / Gmail を探し回る前に**論文本体（`\author` / `\email`）を最初に見る**。見つけたら本 DB に登録する（探索コストの再発防止）
- **更新タイミング**: 所属変更、メールアドレス変更が判明したとき
- **projects の更新**: プロジェクトへの参加・離脱時
- **PII の扱い**: git-crypt 必須。暗号化されていないファイルに書かない
- **id の命名**: 姓のローマ字小文字。重複時は名前の頭文字を追加（例: yamada-m）

## 旧データからの移行

`gmail-mcp-config/collaborators.yaml` は旧正本。`research-collab/collaborators.yaml` に移行済み。
