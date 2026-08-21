<!-- doc-meta
when: referee report への point-by-point 返信を書くとき
category: paper
summary: referee report への point-by-point 返信 (= author response) 作成 6 reflex (= 回答は本文 grep 照合・起源でない文献は see e.g.・referee 誤記は静かに正す・自己否定語回避・全 comment フル引用・旧式番号は submission 版基準)、 paper-audit.md と相補
-->
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

## <a id="defensive-revision"></a>reject 後の誌替え再投稿: 防御改訂の 3 検査 (2026-08)

rebuttal を書かない誌替え再投稿 (= reject 済み原稿を修正して別誌へ) で、本文に claim・引用・修正を足すときの検査 3 点。いずれも 2026-08 の実例 (reject を重ねた共著論文の 5 誌目) で発火した。

1. **断言 framing 検査**: 足す文が「予言 + 精密実験の制限」型の量的主張なら、referee がその場で back-of-envelope できるかを自分で先に計算する。安全に通過すると示せない (= 見積もりが現行 bound と同 order 以下にならない) 制限は断言せず、**test/example framing** (「can be tested by ...」の例示) に落とす。新規主張ゼロで引用は復活でき、攻撃面を作らない。
2. **修正の 2 次露出 sweep**: 表記・整合性の修正 (例: 未定義記号をただしい結合定数に relabel) が、それまで曖昧さの陰に隠れていた本文内矛盾 (= 図の使用パラメータ vs 本文の許容域、など) を**露出させないか**を突き合わせる。露出するなら、力学の駆動変数を特定して scaling で読み替えられないかをまず調べ、成立するなら caption/本文の 1 文で先回りして塞ぐ (= 数値の再計算より先に構造を疑う)。
3. **査読実績の照合**: 「referee に突かれうる」と主張・対策する前に、過去の report 群を機械照合 (grep) して**実績あり (= 対応必須) と純予防 (= 入れ得だが optional)** を区別し、その label 付きで判断者に提示する。予防コストの妥当性は実績の有無で変わる。

関連: 依頼側の縮小原則 = [`research-email.md #shrink-the-ask`](research-email.md#shrink-the-ask)。

## <a id="manuscript-lineage-verification"></a>改訂に入る前の系譜検証: 「手元の最新」 を疑う 3 検査 (2026-08-21)

reject 後の改訂や 5 誌目の投稿準備で、 **土台にした版が共著者合意済の最新でなかった**事故の再発防止。 共著論文では「最後に自分が受け取った添付」 ≠ 最新 (自分が cc 外だった期間の改訂、 別の共著者が投稿システム向けに変換した版、 など) が普通に起きる。

1. **系譜表を作る** — 投稿ごとに (日付、 投稿者、 source の所在、 語数、 識別 keyword の有無) を 1 行ずつ並べる。 **語数・keyword は単調でなければならない** (改訂を重ねた版が 2,500 語短くなる、 referee が褒めた framing の語が消えている = 土台の取り違えの signal)。 referee report が言及する語句 (「coarse-grained」 等) が原稿に無ければ、 その report が読んだ版を持っていない。
2. **cc 外期間を列挙する** — 共著者間 thread で自分が外れていた期間の版は「手元に無い」 と仮定し、 投稿者に source を直接要求する (投稿システムの proof PDF だけでは source は復元できない)。
3. **referee が名指しした文を grep する** — 過去 report の引用句 ("at rest in all stages" 等) が改訂版に原文のまま残っていないか機械照合。 残っていれば「直した」 認識が誤り (= 別の版を直した) か、 修正が取り込まれていない。

**図の再現性** — 数値図は「本文の式 + caption のパラメータ」 から再計算して照合する (= [`scientific-computing.md #figure-vector-extraction`](scientific-computing.md#figure-vector-extraction))。 caption のパラメータで再現できない図は、 作図 code が別の式・別のパラメータを使っていた signal で、 referee に突かれる前に著者間で決着させる。
