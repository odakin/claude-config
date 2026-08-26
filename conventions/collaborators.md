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
- **email の一次情報源と、その射程 (2026-08-26 訂正)**: 連絡先が registry に無いとき、contacts / Gmail を探し回る前に**論文本体（`\author` / `\email`）を最初に見る**。見つけたら本 DB に登録する（探索コストの再発防止）。⚠️ ただし author block が authoritative なのは **所属 email（掲載・帰属のために共著者本人が維持しているもの）**であって、**その人が実際に送受信している運用 address とは限らない**。移籍の前後で特に乖離する（新所属の address が刷られている一方、本人は旧 mailbox を使い続けている、等）。∴ **DB に entry がある相手は DB の `email`（primary）が勝つ**。author block の印字は `alt_email` 側に「所属 email = 論文印字、送受信実績は未確認」の由来注記つきで置く
- **⚠️ この乖離は mail 検索で false null を作る**: 印字 address だけで `from:` 検索すると 0 件が返り、「返信が無い」と誤って結論できてしまう（実際には別 address で届いている）。共著者を検索するときは **primary + alt_email を全部 OR で並べる**。そのうえで **日付フィルタ無しの control query を 1 本回して「その address 群に送受信実績があるか」を先に確かめる** — control が 0 件なら、絞り込み結果の 0 件は「不在」ではなく「address が違う」の証拠。単一の address が返した null を不在に飛躍させない
- **更新タイミング**: 所属変更、メールアドレス変更が判明したとき
- **projects の更新**: プロジェクトへの参加・離脱時
- **PII の扱い**: git-crypt 必須。暗号化されていないファイルに書かない
- **id の命名**: 姓のローマ字小文字。重複時は名前の頭文字を追加（例: yamada-m）

## 旧データからの移行

`gmail-mcp-config/collaborators.yaml` は旧正本。`research-collab/collaborators.yaml` に移行済み。
