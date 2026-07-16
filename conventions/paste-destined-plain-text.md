<!-- doc-meta
when: Claude が書いた文面を user がコピペして web UI (plain text 入力欄) に投稿する workflow を設計・実行するとき
category: web
summary: 貼り付け先行きテキストの 3 層規律 (= ① authoring: 最終的に plain text 入力欄へ貼られる文面は中間 artifact 込みで最初から markdown 装飾ゼロ 〔「いま md/yaml に書いている」 は適用除外の理由にならない〕 / ② delivery: クリップボード直渡し 〔pbcopy 等〕 か code block、 rendered md 表示からのコピーは bold span ごとテキスト消失する事故源なので禁止 / ③ verification: 投稿後に read-back API で読み戻して draft と機械照合、 記録 commit はその後。 記号剥がれ 〔文は残る〕 と span 消失 〔文ごと消える〕 の 2 段階の悪性差)
-->
# 貼り付け先行きテキスト — plain text authoring・クリップボード直渡し・投稿後照合

Google Classroom の課題文・学務 system の入力欄・CMS の投稿 form など、 **markdown を解釈しない plain text 入力欄**に最終的に貼り付けられる文面を Claude が書くときの規律。 「Claude が draft を書く → user が web UI にコピペして投稿する」 分業 workflow で、 3 つの独立した事故 mode がある。

## 事故 mode の分類 (= 悪性の 2 段階)

| mode | 何が起きるか | 典型経路 |
|---|---|---|
| **記号剥がれ** | `**` 等の marker だけ残る/消え、 文は残るが読みにくい | plain text として markdown 原文をそのまま貼る |
| **span 消失** | `**bold**` で囲んだ**テキストごと**消える (= 課題の本体指示 1 文が丸ごと欠落する等、 文意が壊れる) | **rendered md 表示** (chat 描画 / viewer panel) を選択コピー → contenteditable な web UI に貼る。 renderer → クリップボード → 貼り先の変換で装飾 span が落ちる |

span 消失は記号剥がれより悪性 (= 欠落に気づきにくく、 貼った本人の目視 proofread をすり抜けやすい)。

## 3 層規律

### ① authoring — 最初から plain text (中間 artifact 込み)

最終的に plain text 入力欄へ貼られる文面は、 **どこに書く場合でも** markdown 装飾 (bold / heading / table / link 記法 / inline code) を使わず書く。 「いま chat に書いている」 「いま yaml field に書いている」 「いま draft の .md に書いている」 は適用除外の理由にならない — **判断基準は「最終的にどの UI に貼られるか」** (= 中間 artifact 原則)。 draft file 自体の metadata header・検討事項 list など「貼られない部分」 は markdown で構わない。

強調の代替は plain text 内で可能な手段 (「鍵カッコ」 / `[見出し]` 独立行 / ・箇条書き / 番号 (1)(2))。

### ② delivery — コピー操作を機械側に寄せる

1. **第一選択 = クリップボード直渡し**: 文面確定後に `cat <plain-text-file> | pbcopy` (macOS。 Linux は `xclip -selection clipboard` / WSL は `clip.exe`) を実行し、 「クリップボードに入れました、 貼り付けてください」 と渡す。 user のコピー操作自体が消えるので、 rendered 表示経由の変換事故も選択範囲ミスも構造的に起きない。 ⚠️ クリップボードは単一資源 — 使用直前に載せる (途中で別のコピーに上書きされる前提で、 貼り付け直前の turn で実行)
2. **第二選択 = chat の code block**: ``` で囲んだテキストは rendered されないので、 そこからのコピーは安全
3. **禁止 = rendered md 表示からのコピー**: chat の地の文や viewer panel で開いた .md の描画をコピー元にしない (= span 消失の事故経路)。 draft file を目視レビューに使うのは OK、 コピー元にしない

### ③ verification — 投稿後 read-back 照合

user が「投稿した」 と言ったら、 **同 turn で** 投稿先の read API (Classroom なら `classroom_list_coursework` 等) で読み戻し、 draft と機械照合する (= 欠落文・orphan 句読点・壊れ行の検出)。 目視 proofread は span 消失を素通しした実績があるので、 照合は substring match 等の機械で行う。 投稿の記録 commit はこの照合を通してから。 read API が無い投稿先では user に「貼った結果の全文コピー」 を返してもらって照合する。

## 根拠 (= 実測 3 incident、 2026-05〜07、 大学講義の Classroom 運用)

1. **2026-05**: chat に markdown で出した説明 draft を user が送信用に流用 → 記号剥がれで bold 部の主語・述語が消えた文面が学生に届いた (= ① の欠如)
2. **2026-05 (2 週後)**: 「chat では plain text」 規律の確立後、 yaml field に書く draft で markdown が再発 (= 中間 artifact を別カテゴリと reflex 分類する trap → ① の「最終的にどの UI に貼られるか」 基準を明文化)
3. **2026-07**: 課題文 draft .md の本文に bold 2 文 → user が rendered 表示からコピペ投稿 → **span 消失** (課題の本体指示 1 文が丸ごと欠落)。 投稿後 read-back 照合が欠落を検出し、 学生の実害前に修正 (= ③ が実働した初例。 ②③ を規律化)

## 限界と隣接規約

- ① は authoring 規律 = 書く瞬間の reflex 依存 (機械 gate は draft file の正当な markdown 部と本文の区別が general には不能)。 ②が構造的に強い分、 ① が漏れても ② で吸収される (plain text file を pbcopy する運用なら、 装飾が残っていれば `**` が文字として貼られる = 記号剥がれ mode に降格し、 目視で気づける)
- 隣接: PDF コピー由来の改行・RTF 書式の整形は [clipboard-cleaner.md](clipboard-cleaner.md) (= 逆方向 = 「外 → 手元」 の clipboard 衛生)。 クリップボードの単一資源原則と secret との共存は [secret-handoff.md](secret-handoff.md)
