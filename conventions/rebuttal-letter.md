<!-- doc-meta
when: referee report への point-by-point 返信を書くとき + 不採択の直後に編集者へ第 2 referee を頼む返信を書くとき (#ask-editor-second-referee) + 編集者が再審を許したあと、 referee に転送される返答書と編集者だけへの文を書くとき (#reconsideration-reply) + preprint を読んだ人への返信で約束した本文の修正を、 改訂・投稿の前に原稿と照合するとき (#promised-edits-check) + 読み手が引いた式・文献の番号を版ごとに正確に出すとき (#exact-numbers-per-version)
category: paper
summary: referee report への point-by-point 返信 (= author response) 作成 6 reflex (= 回答は本文 grep 照合・起源でない文献は see e.g.・referee 誤記は静かに正す・自己否定語回避・全 comment フル引用・旧式番号は submission 版基準)、 paper-audit.md と相補。 不採択の直後の 1 通 (専任の編集者に確かめられる事実 1 つ・誤読を言い切る 1 文・report の限定まで引いて答える) = #ask-editor-second-referee
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

<a id="exact-numbers-per-version"></a>**番号そのものが要るとき** (返答書で「旧 (N) は今の (M)」 と書く・約束の照合 = 下の [#promised-edits-check](#promised-edits-check)) は、 各版の source を一時 dir で組んで読む。
label のある式・図・節 = `.aux` の `\newlabel`。 文献 = `.aux` の `\bibcite` (引用順の bst では、 前の方に引用を 1 本足すと後ろの番号が全部ずれる)。 label の無い式 = 一時の写しのその式に `\label` を差して組む (原稿は変えない)。
組んだ番号は、 相手が読んだ PDF の文字層とも突き合わせる (同じ頁にその式番号がある・文献番号の項の著者が key と合う)。 突き合わせには、 番号を全部ずらした写しで食い違いが出ることを foil に置く。
構成を変えていなくても番号はずれる: 前の式の 1 行を番号なしにしただけで、 後ろの式番号が全部 1 つずれた (実測)。

## 実例 (= 該当 private paper repo、 2026-06-02)

2 本の原稿を統合した major revision で、 数十の referee comment に point-by-point 回答。 §1 reflex (= 本文 grep 照合) で **2 件のズレを発見・修正**:
- 「the unsupported sentence has been removed」 ← 実際は根拠を追加して justify した (= 削除でなく根拠追加)。
- 「a reference … has been added」 ← 実際は旧版から `\eqref` で既に参照済みだった (= added でなく対応済み)。

両方とも task tracker の記録ベースで回答を書いたために発生。 残りの Response は検証可能 claim (= 用語置換 / 削除 / 引用 + 質的な項目) が全て本文と一致。 → **教訓: rebuttal は最初から本文 grep で書く (= 記録ベースは removed/added が本文とズレる)、 §1 reflex を最初に回せば 2 件を未然に防げた**。

## <a id="defensive-revision"></a>reject 後の誌替え再投稿: 防御改訂の 3 検査 (2026-08)

rebuttal を書かない誌替え再投稿 (= reject 済み原稿を修正して別誌へ) で、本文に claim・引用・修正を足すときの検査 3 点。いずれも 2026-08 の実例 (reject 後の共著論文の再投稿) で発火した。

1. **断言 framing 検査**: 足す文が「予言 + 精密実験の制限」型の量的主張なら、referee がその場で back-of-envelope できるかを自分で先に計算する。安全に通過すると示せない (= 見積もりが現行 bound と同 order 以下にならない) 制限は断言せず、**test/example framing** (「can be tested by ...」の例示) に落とす。新規主張ゼロで引用は復活でき、攻撃面を作らない。
2. **修正の 2 次露出 sweep**: 表記・整合性の修正 (例: 未定義記号をただしい結合定数に relabel) が、それまで曖昧さの陰に隠れていた本文内矛盾 (= 図の使用パラメータ vs 本文の許容域、など) を**露出させないか**を突き合わせる。露出するなら、力学の駆動変数を特定して scaling で読み替えられないかをまず調べ、成立するなら caption/本文の 1 文で先回りして塞ぐ (= 数値の再計算より先に構造を疑う)。
3. **査読実績の照合**: 「referee に突かれうる」と主張・対策する前に、過去の report 群を機械照合 (grep) して**実績あり (= 対応必須) と純予防 (= 入れ得だが optional)** を区別し、その label 付きで判断者に提示する。予防コストの妥当性は実績の有無で変わる。

関連: 依頼側の縮小原則 = [`research-email.md #shrink-the-ask`](research-email.md#shrink-the-ask)。

> **姉妹**: 系譜 (= どの版か) と防御改訂 (= どう書くか) の手前に、 **中心主張がそもそも成立するか**の検算がある — [`paper-audit.md#headline-claim-budget-check`](paper-audit.md#headline-claim-budget-check) (= 模型の形式に依らない収支で 2〜3 行。 再投稿の直前に中心主張が収支で不成立と判明した実例)。

## <a id="manuscript-lineage-verification"></a>改訂に入る前の系譜検証: 「手元の最新」 を疑う 3 検査 (2026-08-21)

reject 後の改訂や誌替え再投稿の準備で、 **土台にした版が共著者合意済の最新でなかった**事故の再発防止。 共著論文では「最後に自分が受け取った添付」 ≠ 最新 (自分が cc 外だった期間の改訂、 別の共著者が投稿システム向けに変換した版、 など) が普通に起きる。

1. **系譜表を作る** — 投稿ごとに (日付、 投稿者、 source の所在、 語数、 識別 keyword の有無) を 1 行ずつ並べる。 **語数・keyword は単調でなければならない** (改訂を重ねた版が大幅に短くなる、 referee が褒めた framing の語が消えている = 土台の取り違えの signal)。 referee report が言及する語句が原稿に無ければ、 その report が読んだ版を持っていない。
2. **cc 外期間を列挙する** — 共著者間 thread で自分が外れていた期間の版は「手元に無い」 と仮定し、 投稿者に source を直接要求する (投稿システムの proof PDF だけでは source は復元できない)。
3. **referee が名指しした文を grep する** — 過去 report が名指しした句が改訂版に原文のまま残っていないか機械照合。 残っていれば「直した」 認識が誤り (= 別の版を直した) か、 修正が取り込まれていない。

**図の再現性** — 数値図は「本文の式 + caption のパラメータ」 から再計算して照合する (= [`scientific-computing.md #figure-vector-extraction`](scientific-computing.md#figure-vector-extraction))。 caption のパラメータで再現できない図は、 作図 code が別の式・別のパラメータを使っていた signal で、 referee に突かれる前に著者間で決着させる。

## <a id="deferred-check-reserve"></a>「検証済みだが companion 送り」 の cross-check は、 構造的境界で閉じる部分を本稿に印字し、 残りを response letter の予備として持つ (2026-09-08、 2026-09-09 改訂)

**Pattern**: 本稿の主張を支える cross-check (例: 別 sector の恒等式を多成分で機械検証) を、 その閉形式ごと companion に送って本文は「検証した、 詳細は Ref. [x]」 だけにすると、 referee は「検査可能な式が本稿に無い」 と突く。 このとき 4 手がある: (i) companion を先に (同時に) 公開して引用を checkable にする / (ii) 本稿は現状の正直な scope のままにし、 恒等式と検証 artifact を response letter の予備として手持ちにする (求められた時だけ付録化) / (iii) 主張を検証済み sector に絞る (真の主張を弱める) / (iv) 恒等式のうち印字済みの量だけで閉じる部分 (例: 最低次の接触項) を印字する。

**Rule (2026-09-09 改訂)**: 既定は (ii) と (iv) の併用、 companion が近ければ (i) を重ねる。 **(iv) の可否は「印字済み量だけで閉じる部分」 の切れ目が構造的境界かで決まる**。 切れ目が「どの振幅が入るか」 で決まり (例: 最低次の恒等式には異なる sector を混ぜる振幅が入らない = 背景の対称性がその次数の混合項を作る定数 tensor を許さないので、 混合項は次の次数から)、 本稿と companion の sector 分担線に一致するなら、 (iv) は fig leaf にならない。 その場合の書き方 = ① 恒等式**全体**を Γ レベルで display する (混合項は記号だけ、 値と規約辞書は companion) ② 印字部分は loop 計算の check として 3 拍 (何が決まるか / 調整余地なし / 一致した値) で書き、 機械 anchor (印字式からの audit script) を残す ③ 残りは「混合振幅が入る次数」 と名指しして companion へ送り、 検証範囲 (成分数・generic q・pole) を明記する。 切れ目が展開の途中の恣意的な打ち切りなら「自明部だけ印字して非自明部は次の論文」 に見えて「残りも出せ」 を誘うので、 (iv) は避けて (ii) だけにする。 (ii) の条件 = 本文の文が「係数決定には使わない cross-check」 のように主張の重さを既に限定していること、 材料 (note + 機械検証 script) が即座に出せる状態にあること。 ⚠️ 「既に本文で示した別の結果の言い換えだから印字する価値が無い」 は却下理由にならない — Ward–Takahashi 恒等式は誘導作用への制約でなく loop 計算の check で、 印字済みの別の対称性の恒等式も同じ立場 (誘導作用が共変なら自動) にある。 検査可能な式がゼロの現状が floor で、 恒等式と閉じる部分の印字は checkable 量を単調に増やすだけで、 referee の要求はそれ以上強くならない。

起源 = 第 2 ラウンドの AI 査読 (ある恒等式を本稿でどこまで示すか)、 著者裁定「(ii) でいこう」 → **後日、 著者が (iv) を再提起して採用** (趣旨: 全く書かないのは有り得ない、 閉じる次数だけ書いて残りを次の論文に回すのが、 何もしないより悪いことは無い)。 印字式からの実測で、 閉じる次数が構造的な境界と判明し、 付録 (導出) + 本文 (最低次の形) に印字、 audit script が anchor。 ⚠️ meta: 前日版の rule「(iv) は罠」 は単一 instance の referee 心理推測をその日のうちに層1 へ hoist したもので、 後日の first-principles 検算で反転した。 一般則の hoist は instance が settle してから (= 著者が採否を実際に運用した後)。 sibling = [`paper-audit.md#claim-strength-three-tests`](paper-audit.md#claim-strength-three-tests) (言明の強さ)、 [`#defensive-revision`](#defensive-revision) (断言 → test framing)。

## <a id="ask-editor-second-referee"></a>不採択の直後に編集者へ出す 1 通: 第 2 referee を頼む

report が 1 本で、 その中の具体的な主張が原稿で確かめられる誤読のとき、 誌替えの前に担当編集者へ返信で第 2 referee を頼む。 正式 appeal ではない。

- **段を分ける**: 例 = APS (Physical Review) は公開の規程で 3 段 (journals.aps.org/authors/editorial-appeal-procedures)。 (1) 担当編集者への再考依頼 (慣行) (2) 正式 appeal = Editorial Board の 1 名が記録を見て助言、 著者は適任・不適任の member を挙げられる (3) 手続きの公正さだけを見る最終段。 最初の 1 通は (1) だけにし、 (2) の候補名は返事を見てから使う。
- **読み手は専任の編集者**: 多くの誌の associate editor は研究歴のある専任職で、 その分野の現役研究者ではない。 物理の優劣は判定できないので、 技術語・節の列挙・関連文献の比較を並べても説得にならない。 書くのは 3 つだけ:
  1. 編集者が原稿を開いて 1 分で確かめられる事実 (例 = 「report が挙げた文献を、 本稿は付録の照合でだけ引いている」)
  2. 誤読を平易に言い切る 1 文 (例 = 「report はその照合を本稿の結果と読んだ」)
  3. 本稿の結果が何かを 1 文
- **report の文は限定まで verbatim で引き、 限定ごと答える**: "see Refs. X, for example" なら、 例を崩すだけでは「many papers」 の本体が残る。 「挙がったのは X だけ / X は照合で引いた / 近い先行研究の一覧と違いは §N に書いた / report は他を挙げていない」 の形で本体に答える。
- **頼み方**: 第 2 referee の分野を 1 句で指定する。 report が挙げた文献の著者本人を候補に挙げると、 自分たちの読みへの自信として効く (その人が当の referee でも、 自分の論文との違いは当人が判断する)。
- **文体**: 簡潔・平易・論理的。 1 段落 1 主張。 読みにくい英文 (主語が抽象名詞の受け身、 "questions no equation" のような詰めすぎた言い方) は短い普通の文に言い直す。 冗長の差し戻しが続いた (実測) = 初稿から絞る。
- **共著者に「appeal は効かない、 誌替えが安い」 と言われたら**: これは正式 appeal でなく 1 通であること、 費用は書き終えた 1 通だけであること、 期限 (例 = 3 週) を切って動きがなければ誌替えに移ることで答える。 決めた人たちの連名で「こう決めた、 今日中に異論が無ければ出す」 の形にする。 誌替え先の cover letter にも同じ線引きを入れる (同じ referee に回ることがある)。
- **予防 (原稿の側)**: 古典的な文献との一致を付録で確かめると、 その付録が主結果と読まれることがある。 照合のための引用は「照合のため」 と本文に明示し、 序論で既知との線引きを 1 文で言う ([`paper-audit.md`](paper-audit.md) の主張の配置の検査)。
- 他人の mail client から送られる文面の非 ASCII = [`paste-destined-plain-text.md#non-ascii-via-other-client`](paste-destined-plain-text.md#non-ascii-via-other-client)。

## <a id="reconsideration-reply"></a>編集者が再審を許したあとの返答書: 一問一答・原稿は最小・同じ referee が読む前提

不採択の後に編集者が「referee の反論への詳しく collegial な返答があれば再審する」 と返したとき、 referee に転送される返答書の書き方。
report が修正を求めず新規性だけを否定している場合を想定する (修正の要求がある report は上の 6 reflex)。

- **同じ referee が先に読む前提で書く**: 「referee に転送できる形で」 という編集者の依頼は定型で、 referee の交代を約束していない。
  中身は固く、 口調は友好的にする。 友好的で論理の固い文は新しい referee にもそのまま効き、 敵対的な文は同じ referee には逆効果 = 失うものが小さい側を取る。
  分野を指定した referee の依頼は編集者だけへの欄に書き、 頼みは 1 つにする (「その分野の referee に評価してほしい」 まで。 「今の referee に加えて、 または替えて」 のように選択肢を文末に並べると、 どちらを望むか決めかねているように読める = 残すか替えるかは編集者が決める)。 新しい referee には今の report とこちらの返答も見せるよう頼む (判断の材料になる)。
  その欄で、 認めること (例: 個々の係数は既知) と主張すること (例: 計算した対象は新しい) を並べるときは、 両方が同時に成り立つ理由を 1 段ずつつなぐ: 相手の計算は何を変数にして何をしたか → 認めることはその計算から分かる (原稿のどこが照合しているか) → こちらの結果 (対象と確かめた恒等式) は相手の論文に無い (本文で確かめた範囲で。 「その計算には現れない」 は変数の取り方の論拠になり成り立たないことがある = 下の "for example" の行)。 専門外の編集者は、 並べただけの 2 文の関係を補えない (実測)。
- **原稿の変更は最小にする**: 求められていない変更を入れると、 その分だけ指摘が正当だったように読める。 返答は原稿の既存の文 (節・付録・表) を指して答え、 「新しい版ではこう書いた」 を約束しない。
  投稿画面が新しい原稿を必須にするなら、 小さな誤りの訂正と記号の統一だけを入れ、 その一覧は referee 向けの返答書に置かず、 編集者だけへの欄に事実だけで書く (何を外した・何を直した。 訂正の理由の物理を限定句つきで語らない = 1 文で論理が閉じない)。 式番号がずれるなら返答書の冒頭に 1 文で、 何番以降がいくつずれたかだけを書く (ずれていない番号の種類と、 ずれた原因の表示は書かない = 原因は編集者だけへの欄の変更の一覧が持つ)。 ずれの範囲は、 両方の版を組んで全 label で確かめる = [`../scripts/tex-label-shift.py`](../scripts/tex-label-shift.py) (投稿版の PDF が手元に無くても、 git の commit から組む)。
- **一問一答で短く**: report の文を全部 verbatim で引き、 各点に 1〜数文で答える。 書けば書くほど、 指摘が正当だったように見える。
  点は report の文の組ごとでなく、 反論ごとに切る (論文を要約する文は、 その後に続く「新しくない」 の前置きなので同じ点に入れる)。
  点を併せたら、 2 つの答えの文を並べ直すのでなく、 論理の線を 1 本に組み直して文の数を前後で数える (並べ直しただけの答えは、 併せる前より長かった = 実測)。
  推薦・判定の文 (「掲載を勧めない」) は反論でないので点にしない: 引用して、 見出しの無い短い結び (その推薦が立つ見方 → どの点がそれに答えたか → その上で再考を) にする。
  語数は引用を除いた自分の文で前後を記録する = [`../scripts/letter-word-count.py`](../scripts/letter-word-count.py) (`--quote-env` に引用の環境、 `--git-rev` に直す前の版)。
- **書き出しで同意しない**: 「Correct.」「Agreed.」「The summary is accurate.」 で始めると、 その点を譲ったように読める。 自分の主張で始め、 report の記述は「…, as the report describes」 のような従属句で受ける (次の文で、 その対象が新しいと短く言い切る)。
  report が原稿の主張していないことを否定しているときも、 「原稿はそれを新しいと言っていない」 を主語にして書く (相手の誤読を主語にしない)。
- **結びで譲歩しない**: 「指摘してくれれば喜んで削る」 は弱い。 かといって「失わずに削れる部分は見つけていない」 のような削らない宣言も、 優先順位を付ける気が無いと読まれる (実測)。 長さの点は下の行のとおり、 主結果の読みと読み方の案内で閉じる。 文献の招き (「他に計算した仕事を知っていれば引く」) は新規性の点に 1 回だけ置く。
- **長さの指摘 (「N 頁で書ける」) には、 長さでなく主結果の読みで答える**: その指摘は、 論文の主結果を何と読んだかに立つ (帰結だけが新しいと読めば N 頁に収まる)。 主結果は何か → 帰結はそこから出る → N 頁に入るのは帰結だけ → 主結果は新しい (新規性の点を指す) ので検証できるよう全部示す → 復習の部分は原稿がそうと明記していて、 既知の読者は飛ばせる、 の一直線で書く。 「report は〜と言う」 を主語にした文を途中に挟むと、 報告の見方とこちらの主張を行き来して読みにくい (実測)。 「どこを削れるか report は示していない」 は、 長さの懸念を述べるのに個々の削除を挙げる義務は無い、 と返される (実測)。
- **原稿の自己記述は切らずに引く**: 序論の「新しい結果は §X と、 それを支える付録にある」 を「新しい結果は §X にある」 と途中で切って引き、 付録を「結果ではない」 と言うと、 序論 1 行で反証される (実測)。 付録の役割は中身で言う (「標準の方法で既知の係数を独立に再現した照合」)。
- **"for example" の反論は種類全体で、 事実だけで**: 挙がった例を崩すだけでは「many papers」 が残る (上の [#ask-editor-second-referee](#ask-editor-second-referee))。
  種類全体に効く答えは事実で組む: こちらが何をどの理論で計算したか (対象・成分・確かめた恒等式) / 挙がった文献が何を変数にし、 何を計算したか (本文で 1 本ずつ読んだ範囲。 束ねる動詞は全部に当てはまるものを選ぶ) / この対象を計算した論文を知らない (名指しがあれば引く)。
  ⚠️ 「相手の変数には X が現れない」「相手は X を量子化しない、 こちらは量子化する」「どの計算でも同じ」 は論拠にしない: その一ループに X の内線が無ければ、 こちらの量は相手の汎関数の X についての変分で、 連鎖律から出る ([`paper-audit.md#novelty-from-variables-or-identities`](paper-audit.md#novelty-from-variables-or-identities)、 実測)。 「恒等式を確かめた」 も同じく論拠にならない (同じ節)。
  ⚠️ referee が問うていない「2 つの量の関係」 を認める文は足さない (答えが弱くなる = 実測)。 問われたら、 原稿の導出の節 (こちらの量から結果を組んだ節) を指して答える。
  「report も挙げていない」 は付けない (印字の有無の争いに移り、 重要性の反論に答えない = 実測)。 返答書の地の文に「X は例である」 のような議論の手続きの語りを持ち込まない (推敲の会話の流れの語が文に残った形 = 読み手には不自然)。
- **非母語の読み手に通じる平易さ**: 共著者と referee の多くは英語の非母語話者。 名詞の動詞用法 (「the summary names X」)、 口語の句 (「as much」)、 指示先の曖昧な語 (「the rest」)、 切り詰めた言い方 (「and we see none」) を避ける。 動詞は say より state / specify。 1 文に主張 1 つ、 式番号の尾を長く引かない。
  文が短くても通じない形 (抽象的な述語・名詞句が運ぶ判断・同格の挟み込み・圧縮した否定の並列・文末の選択肢) と直し方 = [`writing-discipline.md#short-but-unreadable`](writing-discipline.md#short-but-unreadable)。 返答書は全文の長さが 30 語以下でも、 この形で何度も止まった (実測)。
- **完成稿は更の目で読み直す**: 何十回の直しの後は、 会話で使った語・論点の名前が文に残る。 最後に原稿を見ていない読み手のつもりで頭から読み、 論理の流れだけを追って整える。
- 編集者だけへの欄の文は ASCII で ([`paste-destined-plain-text.md#non-ascii-via-other-client`](paste-destined-plain-text.md#non-ascii-via-other-client))。 返答書は PDF (上の「構造」)。

## <a id="promised-edits-check"></a>査読の外で約束した修正の照合 (preprint を読んだ人への返信)

preprint を読んだ人への返信で「本文に明示する・引用する・図に足す・別途確かめる」 と書いたら、 改訂・投稿の前に、 その約束が原稿に入っているかを確かめる。 §1 と同じく、 記録でなく本文で照合する。

1. **約束は送った mail の文面から 1 件ずつ拾う** — 下書きや内部の要約から拾わない。 内部の要約は約束を数え落とす (実測)。 下書きと送信版の違いも 1 文ずつ見る。
2. **外への約束と、 共著者の間の方針を分ける** — 送った文に無い書き換え (主張の範囲を絞る、 など) は外への約束ではない。 照合の表には両方を並べるが、 「約束を守っていない」 と書くのは前者だけ。
3. **版ごとに 1 対 1 で照合し、 約束より前の版を foil にする** — 相手が読んだ版では「無い」、 約束を入れた版では「有る」 と出なければ、 照合が区別していない。 照合は script にして、 相手が読んだ版・投稿版・いまの原稿・改訂案の全部に回す。 番号は上の [#exact-numbers-per-version](#exact-numbers-per-version)。 改訂案が著者への注の中で置き換えた旧文を引用しているなら、 注の中身を除いてから照合する (旧文を本文と取り違える = 実測)。
4. **改訂案が約束を当てた文を書き換えるとき** — 文字どおり保たれるか、 中身で保たれるかを分けて書き、 判断を著者に渡す (例: 明示すると約束した仮定が、 書き直しで要らなくなって消える)。 返答書や相手への連絡で触れるかも著者が決める。
5. **送った後の相手の再返信を拾う** — thread の記録が最初のやりとりで止まり、 こちらの返信への反論が記録に入らないことがある (実測)。 照合のときに、 返信を送った thread を差出人で 1 回引く。
6. **新しい査読の指摘と重なる文に印を付ける** — 約束した引用の整理 (誰を先行として引くか) と、 査読の新規性の指摘 (既存の文献との違い) は、 同じ文 (「先行文献では明らかでなかった」 型の主張) に効く。 主張の範囲を絞る案は、 査読が既知と言う所に主張を寄せることがある = 印を付けて著者の判断に渡す。
