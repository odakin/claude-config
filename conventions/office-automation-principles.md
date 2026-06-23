# Office ファイル処理の考え方 (= 原則編)

行政・学術様式の Excel / Word / PDF を機械で扱うときの**思考の枠組み**。 個別の罠と手順は
[`office-automation.md`](office-automation.md) (= slug 付き gotcha 集) が正本で、 本 file は
「**新しい様式・新しい罠に出会ったとき、 slug が無くても正しい判断に辿り着く**」 ための原則を
まとめる。 入口の順番: 本 file (考え方) → office-automation.md (該当 slug を grep) → 実装。

---

## 0. 問題の本質: 様式ファイルは「データ」ではない

3 つの認識がすべての出発点になる。

**(a) 様式は「見た目が契約」の文書である。**
事務窓口は file 内のデータ構造ではなく**印刷された紙 / render された PDF の見た目**で受理・差戻しを
判定する。 標題が消えた・label が書き換わった・`###` が印字された様式は、 値が全部正しくても
「様式が改変されている」 として差し戻される。 → 正しさの単位は **rendered artifact** であり、
検証は最終的に必ず「見た目」 に到達しなければならない ([`pdf-visual-confirm`](office-automation.md#pdf-visual-confirm))。

**(b) office ファイルは地層である。**
1 つの xlsx の中に cell 値 / merge 構造 / drawing (標題・図形) / style / 数式 / data validation /
印刷設定 / 隠し sheet が**別の層**として積み重なっている。 docx も同様 (本文 run / style 継承 /
content control / XML 宣言 / bookmark)。 **どの道具も、 この地層の一部しか読み書きできない**。

**(c) 処理は lossy な解釈器の連鎖である。**
`雛形 xlsx → openpyxl → xlsx → Excel → PDF → CUPS/driver → printer RIP → 紙` — 矢印 1 本ごとに
**別のパーサが別の解釈**をする。 ある段で正しく見えることは、 次の段で正しいことを何も保証しない
(実例: subset font 埋め込み PDF は画面 renderer で完璧 → printer RIP で文字化け
[`print-raster-pdf`](office-automation.md#print-raster-pdf))。

---

## 1. 道具を選ぶ前に問う 2 つの質問

**Q1. 成果物は何か?** — xlsx/docx 本体の提出か、 紙 (印刷物) だけか、 内容確認だけか。
**Q2. 雛形にどの層があるか?** — 触る前に必ず dump ([`form-dump-first`](office-automation.md#form-dump-first))。
特に `unzip -l form.xlsx | grep -iE 'drawing|media'` で **drawing の有無**を最初に見る。

この 2 つで道具が決まる (= 道具選択の梯子):

| 状況 | 道具 | 理由 |
|---|---|---|
| 読み取り・分析だけ | openpyxl / fitz / python-docx 何でも | lossy でも害がない |
| drawing 無し + xlsx 提出 | openpyxl fill + [`diff-form-xlsx-detection`](office-automation.md#diff-form-xlsx-detection) | 最速で機械検証可能 |
| drawing 有り + xlsx 提出 | Excel osascript ([`excel-osascript-cell-write`](office-automation.md#excel-osascript-cell-write)) or zip 注入 + integrity gate | openpyxl は drawing を破壊する ([`openpyxl-destroys-drawings`](office-automation.md#openpyxl-destroys-drawings)) |
| **紙だけ** 必要 (単票) | 雛形を Excel で PDF 化 → fitz で直接印字 ([`pdf-prefill-direct`](office-automation.md#pdf-prefill-direct)、 汎用実装 = `scripts/pdf_form_fill.py`) | drawing は render 済で安全、 最速 |
| 紙だけだが **多項目 + 派生 sheet が数式導出される** workbook | Excel osascript で雛形 copy に記入 → PDF → ページ抽出 | drawing native 保持 + 依頼書/承諾書等の**派生書類が数式で自動的に埋まる** (= PDF 印字だと派生分も手で印字する羽目になる)。 紙のみでもこちらが速くて正しい |
| **docx fill** (本文提出も visual confirm も) | python-docx で XML/run/段落編集 ([`docx-fill-xml-edit`](office-automation.md#docx-fill-xml-edit) / [`docx-python-docx-surgical-edit`](office-automation.md#docx-python-docx-surgical-edit))。 配置先は `~/<repo>/...` 必須 ([`docx-tmp-sandbox-deny`](office-automation.md#docx-tmp-sandbox-deny)) | Word.app は sandbox で `/tmp` の grant 永続化不能、 一度詰むと automation も手動も止まる |
| **docx → PDF** (内容確認・正式書類提出いずれも) | **Word AppleScript 駆動が default** ([`docx-to-pdf-pages`](office-automation.md#docx-to-pdf-pages) / [`docx-pdf-stale-cache`](office-automation.md#docx-pdf-stale-cache))。 既存 wrapper = `scripts/docx-to-pdf.sh` (引数なし = Word、 `--pages` で明示 Pages) | docx は「Word 体裁が契約」 の正式書類が大半。 Pages は re-typeset で見出し/表が重なる artifact + reviewer は Word 体裁を見る。 Word automation の cold-start trap は [`docx-pdf-stale-cache`](office-automation.md#docx-pdf-stale-cache) で対処済 (= fallback 1 = user の Word 書き出し) |

**原則: 道具を使う前に「この道具はこの file の何を round-trip できないか?」 を 1 回問う。**
答えを知らない道具で本番 file を触らない (= まず copy で挙動を観察する)。

⚡ **新規 docx automation script を書く時の default engine 選択 reflex** (= 上の梯子の docx 行に直結):

1. **default は Word 忠実版に倒す** (= `docx-to-pdf.sh` の 2026-06 反転と同じ哲学)。 「Pages の方が automation が安定」 という旧 reflex は **正式書類の体裁 contract を壊すコストの方が大きい** ので **default にしない**。 Pages は `--pages` 等の明示 opt-in で使う。
2. **`/tmp` 配下を docx の作業場所にしない** = script が docx を生成 / 受領 / 中間保存する場所は project 配下 (= cwd か `~/<repo>/...`) を default に。 `/tmp` を input/output に取る引数は [`docx-tmp-sandbox-deny`](office-automation.md#docx-tmp-sandbox-deny) と同じ warn (= block でなく user 判断) を出す。
3. **Word AppleScript の cold-start trap を踏むのは前提**。 timeout を `with timeout of N seconds` で 60s default から伸ばす + 失敗時は **旧 default (= Pages 等) に自動 fallback しない** + 「user の Word.app で File > 名前を付けて保存 > PDF」 を error message で案内する (= [`docx-pdf-stale-cache`](office-automation.md#docx-pdf-stale-cache) §「automation が続けて失敗するときの fallback 階層」)。 自動裏起動で「気づいたら Pages が立ち上がっている」 を作らない。
4. **既存 sibling script を流用するなら `docx-to-pdf.sh` の構造を模倣する** — engine flag、 `/tmp` warn、 cold-start timeout、 fallback error message の 4 点を最低限 mirror。

✅ 既存 wrapper を呼ぶだけで済むなら新 script を書かず `docx-to-pdf.sh` を呼ぶ (= 上の 4 点を 1 か所に集約)。 新 script を書くのは「複数 docx を batch 処理」 「pipeline の一部に組み込む」 等で wrapper では足りない時のみ。

---

## 2. 検証の 3 層モデル (= どれも他の代わりにならない)

| 層 | 何で検証 | 捕まえられるもの | 捕まえられないもの |
|---|---|---|---|
| ① 機械 (決定論) | 雛形 diff / integrity script / NFKC text 照合 / 結合セル clipping 照合 (check-form-clipping.py) | label 上書き、 構造破損、 値の欠落、 **結合セルの記入値 clipping** (= 値↔描画 text 照合、 engine 依存の第一防衛線) | 見た目の破綻 (overflow `###` / 配置ズレ / glyph 不描画) |
| ② 視覚 (render) | PDF を**画像として**目視 | `###` / 文字切れ / 標題消失 / ズレ | 次の解釈器の挙動 (printer 化け) |
| ③ 実機 | 実際に Word/Excel で開く、 実際に印刷する | 「破損」 ダイアログ、 printer RIP 問題 | — (最終 ground truth) |

応用の指針:
- **①で済ませた気にならない** — text 層の検証は「値が存在する」 ことしか言わない。 glyph が
  描画されない PDF も text 検証は通る。 layout 問題 (overflow `###`) は text 抽出では不定
  ([`clear-yellow-fill-marks`](office-automation.md#clear-yellow-fill-marks) 末尾の警告)。
  ⚠️ **例外的に結合セルの記入値 clipping だけは ① で機械検出できる** (= 値↔PDF 描画 text の照合、
  [`merged-cell-text-clipping`](office-automation.md#merged-cell-text-clipping))。 ただし clip しても
  text 層に全文を残す renderer もある (engine 依存) ので ② 視覚は依然必須 = ① は第一防衛線。
- **②の目視で見つけた異常は print-blocker** — 「その欄はどうせ後で書くから」 等の理由で
  **黙認して進まない** (直すか user に確認)。 時間圧の下で最も踏みやすい失敗は
  「異常に気づいたのに合理化して進む」 こと (実例 3 連: `###` 黙認印刷 / 標題なしを「設計通り」 と
  説明 / page-ranges が効いていると思い込み)。
- **③に到達できない不確実性は、 到達可能な形に変換して潰す** — printer の font 解釈は制御
  できない → **600dpi ラスタ化**でフォント処理自体を経路から消す ([`print-raster-pdf`](office-automation.md#print-raster-pdf))。
  一般化: 下流の解釈器が信用できないなら、 **解釈の余地がない表現 (= 画像) まで上流で潰してから渡す**。

**変換 1 回ごとに検証 1 回** が基本リズム。 変換を 3 回重ねてから検証すると、 どの段が壊したか
特定できず全部やり直しになる。

---

## 3. 文字列照合の罠 (= 「無い」 という判定を信用する前に)

PDF / office ファイルの text 抽出は **見た目と同じ文字を返すとは限らない**:
- CJK 互換字形 (「日」→「⽇」 等) で literal 照合が空振りする → **照合は必ず両辺 NFKC 正規化**
  ([`pdf-text-match-nfkc`](office-automation.md#pdf-text-match-nfkc))
- ①②等の囲み数字は NFKC で「1」「2」 に潰れる → anchor に使うなら別の語を選ぶ
- merged cell の値は左上以外から見えない / `###` overflow の text 層は renderer 依存で不定

**原則: 「検索したが見つからない」 は「存在しない」 の証明にならない。** 不在を主張する前に
正規化・別経路 (画像目視 / words dump) で確認する。 これを怠ると「prefill が消えている」 等の
誤診断 → 不要な作り直し、 という二次被害になる (1 日に 3 回実演した実績がある)。

---

## 4. 座標・cell 番地は「導出」する (= hardcode しない)

様式の cell 番地・PDF 座標は雛形の改訂で黙って変わる。 file を跨いだ流用 (= 「前回の様式と同じ
番地のはず」) は merge 構造の違いで壊れる (実例: 同じ様式の v1/v2 で 業務担当者行が
「1 個の wide merge」 ↔ 「所属/職名/氏名の小組み」 と別構造だった)。

- xlsx: 番地は**その file の dump から**取る。 merged cell への書き込みは左上に解決する helper を
  常備 ([`merged-cell-write-topleft`](office-automation.md#merged-cell-write-topleft))
- PDF: 座標は **label 語の bbox から相対導出** (`get_text("words")` + NFKC 照合)。 これなら
  雛形の微改訂に生き残る
- 検証も同じ思想: 「N ページ目が⑭-2」 と hardcode せず、 内容 (= 特徴語) でページを特定する

---

## 4b. 「テンプレ」「前例」 の肩書きを信用しない (= 素性は実 file に聞く)

**先行物の肩書き (= 「最新テンプレ」「前例 script」「doc に上書き済と記載」) は無検証の信頼を誘発する**。
2026-06-12 に同一 session で 3 連発見された事故の共通根は全てこれ:

- 「最新版で上書き済」 と doc に書かれたテンプレ → **実 file は旧版のまま** (= doc と file の drift)
- 「最新様式」 として保存された file → **実は他人の記入済み修正版** (= 個人データ・修正指示 artifact 入り)
- 「前例 dir の fill script」 → **drawing 破壊 script の再演装置** (= 前例 file 自身が既に標題を喪失)

**Reflex**: テンプレ・前例・過去成果物を base にする**直前**に、 file 自身に 4 つ聞く —
① ブランクか (= 全 sheet に個人データ値が無いか) ② 新版か (= 様式更新で増えた欄が実在するか)
③ drawing 健在か (= `unzip -l` で標題 shape の有無) ④ 修正指示 artifact (= 黄色 fill・コメント) が残っていないか。
手順の正本 = [`template-provenance-check`](office-automation.md#template-provenance-check) /
[`openpyxl-destroys-drawings`](office-automation.md#openpyxl-destroys-drawings)。

> 肩書きは証拠ではない。 file の素性は file 自身に聞く。 doc 記述と実 file が食い違ったら実 file が真実で、
> doc を直すのも仕事のうち (= 黙って受け入れない、 次の session のために drift を閉じる)。

---

## 5. 人間系の原則 (= 様式仕事は対人サービスである)

機械処理の目的は**人間の手間と心理的負担の最小化**。 技術的に正しくても以下を破ると失敗:

1. **既知情報 prefill 原則**: こちらが既に知っている情報 (氏名・フリガナ・日付・所属・課題番号…) は
   **全て機械が書き入れる**。 相手に書かせてよいのは**本人にしか書けないもの**
   (自署・押印・本人名義口座・自宅住所・実際の移動経路) だけ。 「記入欄だから空欄で渡す」 は
   相手の手間を不必要に増やす設計ミス。
2. **print-last 原則**: 印刷は「これ以上機械が書き入れられる情報が無い」 状態になってから **1 回だけ**。
   不完全な紙の刷り直しは資源と信頼の無駄。 印刷前 checklist = 全情報源 (メール・記録・
   メール外チャネル) に未投入の既知情報が無いか。
3. **記入分担を明文化**: 様式 type ごとに「当方 prefill / 本人記入 / 事務側算出 / 数式自動導出」 の
   4 区分表を作る (= 分担表そのものが手順書になる)。 分担が暗黙だと「誰も書かない欄」 と
   「相手に書かせてしまう欄」 が発生する。
4. **提出の完了条件は受理側**: 「送った / 渡した」 で task を閉じない。 「受理・承認を確認した」 で閉じる
   (= メール添付送付が正式提出と認められない窓口は普通にある)。
5. **印刷・提出はセット単位で突合する**: 様式は単票でなく「一式」 (= 申請書 + 依頼書 + 承諾書 +
   日程表 + 報告書 + 証憑…) で受理される。 個別ページの修正・差し替えに追われている時ほど、
   **最後に必ず「セット定義 (= 窓口が要求する全書類 list)」 と紙の山を突合**する。 セット定義は
   form ごとに 1 箇所に明文化し、 生成 script の出力末尾に checklist として強制表示するのが
   機械化形 (= 「○○が無い」 と窓口に言われる事故は、 ページ単位の消火がセット視点を
   押し出すことで起きる — 実例: 4 枚セットのうち 2 枚だけ刷って提出に向かわせた)。

---

## 6. 新しい罠に出会ったときの手順 (= 本体系の拡張方法)

1. **その場で root cause を 1 段掘る** — 「どの解釈器が、 地層のどの層を、 どう壊したか」 を特定する
   (= 「もう一度やったら直った」 で済ませない。 同じ穴に必ず落ち直す)
2. **回避策は「判断を要しない形」 まで機械化する** — 規律 prose より script、 script より
   built-in 検証付き script。 将来の session のモデル性能に依存させない
3. **[`office-automation.md`](office-automation.md) に slug 付き subsection で記録** — 症状 / 原因 /
   規律 / origin の 4 部構成、 index.yaml に entry 追加、 validator で dangling 0 を確認
4. **環境固有の観察は層を分ける** — universal な規律は layer 1 (本リポ)、 特定マシン・特定プリンタの
   観察は個人層 (layer 3/4) に置き、 相互に pointer (= 4 層モデル、 [`docs/personal-layer.md`](../docs/personal-layer.md))

---

## 7. 1 行 summary (= 迷ったらこれだけ)

> **様式は見た目が契約。 道具は地層の一部しか守れない。 テンプレと前例は素性を確かめ、
> 変換のたびに検証し、 最後は画像で確認し、 異常は黙認せず、 既知情報は全部機械が書き、
> 印刷は完成後に 1 回、 提出は受理確認で閉じる。**

origin: 2026-06-11 謝金様式の当日運用 session (= 印刷事故 3 連 RCA + prefill 原則の確立)
+ 2026-06-12 様式⑭-1 session (= §4b 先行物の素性、 テンプレ stale / 記入済み混入 / 前例 script 再演の 3 連 RCA)。
個別の手順・コード断片は office-automation.md の各 slug を参照。
