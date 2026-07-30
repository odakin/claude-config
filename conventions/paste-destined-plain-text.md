<!-- doc-meta
when: Claude が書いた文面 / コマンドを user が手で貼り付けて実行・投稿する workflow を設計・実行するとき (= 貼り先が plain text 入力欄でも terminal でも)
category: web
summary: 貼り付け先行きテキストの 3 層規律 (= ① authoring: 最終的に plain text 入力欄へ貼られる文面は中間 artifact 込みで最初から markdown 装飾ゼロ 〔「いま md/yaml に書いている」 は適用除外の理由にならない〕 / ② delivery: クリップボード直渡し 〔pbcopy 等〕 か code block、 rendered md 表示からのコピーは bold span ごとテキスト消失する事故源なので禁止 / ③ verification: 投稿後に read-back API で読み戻して draft と機械照合、 記録 commit はその後。 記号剥がれ 〔文は残る〕 と span 消失 〔文ごと消える〕 の 2 段階の悪性差)。 3 層は貼り先一般の framework = 貼り先が対話 zsh なら ① は shell-env.md の 2 規律 (行内 # / tilde) で最上位 mode は silent 成功、 共通 kernel = 機械生成 artifact を人間貼り付け用に書き直した瞬間に元の保証が消える ∴ 提示文面それ自体が検査対象
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

## <a id="same-framework-other-paste-targets"></a>同じ framework の別 instance — 貼り付け先が terminal のとき

上の 3 層 (① authoring / ② delivery / ③ verification) は plain text 入力欄に固有ではなく、 **「Claude が書く → user が手で貼る → 貼り先の parser が解釈する」 workflow 一般**の framework。 貼り先が変われば事故 mode が変わるだけで、 層構造と ① の判断基準 (= 「最終的にどの parser に食わせるか」) はそのまま効く:

| 貼り先 | ① authoring 規律 | 悪性の最上位 mode |
|---|---|---|
| plain text 入力欄 (web UI) | markdown 装飾ゼロ (= 上記 ①) | **span 消失** (= 文ごと消える) |
| 対話 zsh (terminal) | 行内 `#` を付けない + `~` でなく `"$HOME/…"` ([shell-env.md](shell-env.md#no-inline-comments-in-pasted-commands) / [同](shell-env.md#no-tilde-in-pasted-commands)) | **silent 成功** (= error が出ず、 別の場所に「正しく見える」 結果ができる) |

⚠️ terminal 側の最上位 mode が **silent 成功**である点が web UI 側より悪い: span 消失は「消えた」 が最終的には目に入るが、 silent 成功は「別の場所に出来た」 なので、 やり直して機能が回復した後も誰も気付かない (= 実測で発覚まで 4 週間)。 この「機能回復が調査を終わらせる」 構造は [debugging-discipline.md #recovery-ends-investigation](debugging-discipline.md#recovery-ends-investigation)。

**共通 kernel**: **機械が生成した artifact (= script の出力・API の raw export) を、 人間貼り付け用に Claude が書き直した瞬間、 元の保証は消える**。 script が絶対パスを印字していても、 chat で `~` 表記に書き直せばそこで壊れる ∴ **提示する文面それ自体が検査対象の surface**。 → 書き直さず機械の出力をそのまま渡す (= ② delivery の思想) が常に第一選択。 同 kernel の data 版 = [web-tools.md](web-tools.md#raw-export-snapshot-3set) (= manual transcribe を避けて raw export を保存)。

## 限界と隣接規約

- ① は authoring 規律 = 書く瞬間の reflex 依存 (機械 gate は draft file の正当な markdown 部と本文の区別が general には不能)。 ②が構造的に強い分、 ① が漏れても ② で吸収される (plain text file を pbcopy する運用なら、 装飾が残っていれば `**` が文字として貼られる = 記号剥がれ mode に降格し、 目視で気づける)
- 隣接: PDF コピー由来の改行・RTF 書式の整形は [clipboard-cleaner.md](clipboard-cleaner.md) (= 逆方向 = 「外 → 手元」 の clipboard 衛生)。 クリップボードの単一資源原則と secret との共存は [secret-handoff.md](secret-handoff.md)
