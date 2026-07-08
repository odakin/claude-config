# Rebuttal Letter (= Author Response to referees)

paper revision で referee report に point-by-point 回答する rebuttal letter (= response-to-referees / author response) 作成の規律。 [`paper-audit.md`](paper-audit.md) (= 誤り検出 / forward ref / 重複) と相補 (= こちらは「referee への返信作成」 側)。

**Sibling docs** (= 全 5 で paper / proposal lifecycle を cover): 自分 paper の internal audit = [`paper-audit.md`](paper-audit.md) / 自分が referee として外部 paper / 申請書を評価 = [`peer-review-workflow.md`](peer-review-workflow.md) / grant 申請書の submit = [`erad-submission.md`](erad-submission.md) / 論文の journal / arXiv 投稿ポータル経由の submit = [`paper-submission.md`](paper-submission.md)。 本書 (= author response) はこれら 4 の方向違いで、 referee からの指摘に著者として返す側。

## 構造

- LaTeX standalone document (例: `response-to-referees.tex`)。 referee comment を色付き italic quote (= `\newenvironment{referee}{\begin{quote}\color{blue!65!black}\itshape}{\end{quote}}`) で表示、 各 comment に `\textbf{Response.}` で回答。
- referee ごとに `\section*{Referee N}`、 major / minor revisions を `\subsection*`。
- 冒頭で thank-you + 全体方針 (= 例: 「2 manuscript を merge した」) を 1 段落。

## 規律 (= 6 reflex)

### 1. 回答は変更記録でなく本文を直接照合して書く (= 最重要)

変更記録 (= task tracker / completed-tasks 等の作業ログ) の「removed / added / moved」 表現は曖昧で、 回答が本文の実際の対応とズレる。 **回答 draft 後、 各「removed / added / changed / moved」 claim を本文 grep で検証する**。

**failure mode** (= 記録ベースで書くと起きる):
- 記録に「削除 *または* 引用追加」 と両論あると、 回答が「削除」 と決め打ち → 本文は「根拠追加」 だった (= 逆の対応)。
- 記録に「(旧版時点で) 対応済み」 とあるのに回答が「has been added」 (= 新規追加) と書く → 本文は元から参照済み (= added は不正確)。

**reflex**: rebuttal 完成後、 全 Response の検証可能 claim を本文 grep で一括照合する:
- 用語置換 (= 「X を Y に置換」) → 旧 X が `grep -c` で 0、 新 Y が `>0`。
- 削除 (= 「removed」) → 該当語句が本文に残っていない。
- 追加 (= 「added」「cite」) → 該当が本文に存在。
- 「removed と書いたが本文に残存」 「added と書いたが grep で見つからない」 を潰す。
- 旧式番号 (= Eq.(N)) は改訂版で変わるので grep 不能 → 旧版 tex の該当箇所を内容 (= keyword) で特定 + 現本文の対応を Read で個別確認。

### 2. 起源でない文献は「see, e.g.」 で引く

referee が「for example: X」 と挙げた文献は **一例であって唯一の出典ではない**。 X が standard result (= 教科書級) の起源でない場合、 唯一の出典のように引かない:
- 本文: `$...$~\cite{X}` (= X が出典に見える) でなく `$...$ (see, e.g., \cite{X})`。
- 回答: 「we cite X *as a reference*」 / 「as the referee suggests」 で、 「the original source」 と誤認させない。
- 文献の年・巻を WebSearch で確認し、 起源か standard treatment かを判定する。

### 3. referee の誤記は静かに正す

referee が著者名 / 式番号 / 用語を誤記した場合、 正しいものを使う (= 露骨に「あなたの誤りです」 と指摘しない)。 例: referee が citation 著者名を誤記 → 回答では正しい著者名・年・巻を書く (= 訂正を明示せず自然に正しい情報を出す)。

### 4. referee 指摘に同意しない時、 自己否定語を避け中立に

著者が「我々は誤っていない」 立場の場合、 「erroneous」 「our mistake」 等の自己否定語を使わない。 中立表現に置換:
- 「Corrected」 → 「We have revised the text」
- 「the erroneous mention of B has been removed」 → 「the mention of B has been removed」

referee を怒らせず、 かつ誤りを認めない。 例: referee が「principle A が principle B と混同されている」 と指摘 → 「the text now consistently refers to principle A, and the mention of principle B has been removed」 (= 混同を認めず、 wording を整えた、 と返す)。

### 5. 全 referee comment を省略せずフル引用

`[...]` / `[\dots]` で省略しない。 referee が「自分の comment が正確に受け止められた」 と確認できるよう、 **原文を逐語フル引用**。 原文の箇条書き構造 (= bullet) も保つ (= referee が 2 点を 1 bullet にまとめていたら、 回答も 1 block で両方に答える)。

### 6. 旧式番号は submission 版基準、 回答は「done / moved」 形式

referee の Eq / section / page 番号は **submission 版基準**で、 改訂版 (= merge / restructure 後) では変わる。 回答で改訂版の新番号に深入りせず、 「done」 「moved to an appendix」 「rephrased」 形式で答える。 冒頭で次を断る:
> Equation, section, and page numbers in the quoted comments refer to the originally submitted version; the numbering has changed in the revised manuscript.

## referee の section/Eq 番号 ≠ 改訂版・旧版 tex の番号

referee は submission PDF の番号で書く。 merge/restructure した改訂版とも、 古い source tree の section 構造とも一致しないことがある。 照合時は **番号でなく内容 (= keyword)** で旧版該当箇所を特定する。 submission PDF が repo に無い場合は旧版 tex を内容 grep で辿る (= §1 reflex の旧式番号確認と同じ手法)。

## 実例 (= 該当 private paper repo、 2026-06-02)

2-paper merger の major revision で 37 referee comment に point-by-point 回答 (= 8pp)。 §1 reflex (= 本文 grep 照合) で **2 件のズレを発見・修正**:
- 「the unsupported sentence has been removed」 ← 実際は Lorentz 不変性の根拠を追加して justify した (= 削除でなく根拠追加)。
- 「a reference … has been added」 ← 実際は旧版から `\eqref` で既に参照済みだった (= added でなく対応済み)。

両方とも task tracker の記録ベースで回答を書いたために発生。 残り 35 Response は検証可能 claim (= 20+ の用語置換 / 削除 / 引用 + 質的 4 項目) が全て本文と一致。 → **教訓: rebuttal は最初から本文 grep で書く (= 記録ベースは removed/added が本文とズレる)、 §1 reflex を最初に回せば 2 件を未然に防げた**。
