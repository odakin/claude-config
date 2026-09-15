<!-- doc-meta
when: 共同研究者 DB (collaborators.yaml) を作成・更新するとき
category: research-domain
summary: 共同研究者DB規約 (= 連絡先・所属に加え、native 表記は parts ごとの source と確度を持ち、発音は本人録音 / 母語話者録音 / 対象言語 TTS / IPA / 近似を区別。生成音声の一時 URL は正本に保存しない)
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
  name_native:                # native 表記を持つ場合。推測した full name を入れない
    language: "Language"
    script: "Script"
    full: null                # 本人固有の full spelling が未確認なら null
    parts:                    # 確認済みの部分と候補を名前で区別
      family: null
      given: null
      given_candidate: null
    status: null              # verified / partial / provisional
    sources: {}               # parts ごとの本人・user・公式・辞書 source
  aliases: ["愛称"]           # 会話で使う呼称・愛称（あれば、disambiguation 用）
  affiliation: "所属"         # 不明なら null
  email: "primary@example.com"
  alt_email:                  # 複数メールがある場合
    - "alt1@example.com"
  inspire_id: null            # INSPIRE 著者ID（あれば）
  discord_id: null            # Discord 数値 ID（arxiv-digest 等で mention に使う、あれば）
  github_handle: null         # GitHub username（共同編集リポで push 권があるなら必須）
  projects: [project-id]      # 関連プロジェクト（projects.yaml の id）
  pronunciation:             # 個人固有の発音 evidence がある場合
    status: null              # person-recording / native-speaker-recording / target-language-tts-only / ipa-only / approximation
    workflow_ref: null        # pronunciation-verification.md への pointer
    tool_ref: null            # 再生成できる tool があれば pointer
    audio_url: null           # 一時 URL は保存しない。恒久録音だけ別 artifact の pointer を置く
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
- **native 表記**: ローマ字から full spelling を復元しない。確認済み part だけ `parts` に置き、未確認の full は `null`、候補は `*_candidate`、根拠は `sources` に分ける。一般則 = [`name-rendering.md#pronunciation-is-separate-fact`](name-rendering.md#pronunciation-is-separate-fact)
- **発音 evidence**: `pronunciation.status` で本人録音・母語話者録音・対象言語 TTS・IPA・近似を区別する。対象言語 TTS を本人の発音と書かず、生成 URL の UUID は正本に残さない。一般 workflow = [`pronunciation-verification.md`](pronunciation-verification.md)

## 旧データからの移行

`gmail-mcp-config/collaborators.yaml` は旧正本。`research-collab/collaborators.yaml` に移行済み。
