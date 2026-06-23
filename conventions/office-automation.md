# Office automation (macOS): xlsx form fill, PDF conversion, TTS review

研究費応募書類 / 教務書類 / 学術様式の Excel xlsx を **openpyxl で fill する作業**、 および生成物の **PDF 化 / 印刷 / 音声読み上げ** に関する規約と落とし穴集。

> 🧠 **考え方 (原則編) は [`office-automation-principles.md`](office-automation-principles.md)** — 様式 = 「見た目が契約」 / file = 地層 / 処理 = lossy 解釈器の連鎖、 という枠組みと、 道具選択の梯子・検証 3 層モデル・既知情報 prefill / print-last 等の人間系原則。 **新しい様式・新しい罠 (= 本 file に slug が無い状況) ではまず原則編を読む**。 本 file は個別 gotcha の正本。

origin: 2026-05 SPReAD (AI for Science 萌芽的挑戦研究創出事業) 応募で得た知見 (= 様式 1 研究計画調書 xlsx の Python 自動 fill、 figure 埋め込み、 字数制限管理、 PDF snapshot 生成、 TTS 確認)。

> 🍳 **入口 — 多 sheet 様式 xlsx → 提出用 PDF を端から端まで** (= 構造把握 → fill → ページ分割 → 余白均等化 → 結合 → 検証) やる手順は [`multi-sheet-pdf-assembly`](#multi-sheet-pdf-assembly) の **RECIPE** に集約。 週次の様式 PDF 業務はまずそこを見る。

> 🧭 **構造メモ — 各 subsection は安定 slug-anchor で ident性を持つ** (= positional §-番号は廃止)。 cross-ref は `[`<slug>`](#<slug>)` で書く (= 挿入・移動・ファイル分割で壊れない、 機械検証可能)。 slug ↔ 旧 §-番号 ↔ title ↔ related の対応は併設 [`office-automation.index.yaml`](office-automation.index.yaml) が正本。 旧 §-番号は他 doc の dated 参照解決のため index の `legacy` に保存。 一般則は [`docs/convention-design-principles.md`](../docs/convention-design-principles.md) §14。
>
> **新規 subsection を足すとき**: (1) kebab-case の slug を heading に `<a id="...">` で付与、 (2) index.yaml に entry 追加 (id / legacy は空可 / title / related)、 (3) `python3 scripts/check-office-automation-index.py` で dangling 0 / orphan 0 を確認。 既存と内容が重複しないか先に dedup 確認 (= 検証系の [`pdf-visual-confirm`](#pdf-visual-confirm) / [`image-budget-exhaustion`](#image-budget-exhaustion) / [`docx-pdf-stale-cache`](#docx-pdf-stale-cache) は overlap しやすい — validator が keyword 重複を surface する)。 🔎 **dedup info の仕分け**: validator の dedup は **title token 共有の heuristic** なので、 出たら精査して **FP (= 親子 `##`⊃`###` / 別概念 / 既に pointer 済) と 真の内容重複 (= 要 SoT 統一) を分ける**。 FP は触らない (= info を 0 にするのを目的化しない、 keyword 共有は構造上残り続ける)。
>
> 📂 **作業ルート (cwd) 外の office file** (`~/Downloads` / `~/Desktop` 等) を弄ると Claude Code が permission 確認を連発する → [`claude-code-permissions.md`](claude-code-permissions.md) で `additionalDirectories` に登録すると解消 (どの folder を登録するかは各自の personal layer の設定)。

---

## <a id="symptom-index"></a>🔑 まず読め + 症状 → 対処 早見表 (= 何も知らない session の入口)

⚠️ **Excel / Word を触る前、 自前で osascript / openpyxl を書き始める前に、 まずここで「既出の罠か」 を引く。** この doc は macOS Office 自動化の罠をほぼ網羅しており、 **既存 script で解決できることを hand-roll すると数十ターン溶かす**。 手順:

1. 本 doc + [`office-automation-principles.md`](office-automation-principles.md) (= slug の無い新罠はまず原則編) を読む。 個人層に Office 用 router があるならそれを先に
2. **既存 script を使う (hand-roll しない)**:
   - **xlsx → PDF / 視覚確認**: [`scripts/xlsx-to-pdf.sh`](#xlsx-to-pdf-script) (LibreOffice → Excel osascript fallback、 reset + timeout + automation 許可案内 込み)。 ⚠️ 自前で `save workbook as … PDF` を書くと **-50**。 動く形は **sheet 単位** `save as <worksheet> … file format PDF file format` (= script が既に実装済)
   - **雛形 PDF へ直接印字 (単票・紙提出)**: [`scripts/pdf_form_fill.py`](#pdf-prefill-direct)
   - **docx → PDF**: [`scripts/docx-to-pdf.sh`](#docx-to-pdf-pages)
   - **様式改変 / 破損の検出**: [`diff-form-xlsx.py`](#diff-form-xlsx-detection) / `check-xlsx-integrity.py` / `check-docx-integrity.py`

> **RCA 2026-06-16 (= 本 section の存在理由)**: ある session が上を読まずに学術様式の Excel cell 記入を hand-roll した結果、 **既出の罠 (日付 serial 化 [`excel-write-string-autoconvert`](#excel-write-string-autoconvert) / consecutive-op freeze [`excel-osascript-cell-write`](#excel-osascript-cell-write) / PDF export の verb 誤り [`xlsx-to-pdf-script`](#xlsx-to-pdf-script)) を全て再発見し、 さらに Excel を 5 サイクル叩いてクラッシュさせた**。 = 「読めば 1 発、 読まねば数十ターン + クラッシュ」。 後続 session がこの轍を踏まないための入口がこの早見表。

### 症状 → 対処 早見表

| 症状 (観察できること) | 真因 | 対処 (→ slug) |
|---|---|---|
| Excel がクラッシュ /「作業内容を回復」 dialog | 同 session で osascript の open/save/close/quit を多数 cycle し既存 instance を酷使 | **補正を 1 pass に織り込む単発記入** + 各 op 前に killall reset → [`excel-osascript-cell-write`](#excel-osascript-cell-write) |
| osascript が `-1712` (AppleEvent timeout) | Excel が固まり / **background 実行で automation 許可 dialog を出せない** | killall+sleep reset / **初回は foreground で許可 dialog に応答** → [`xlsx-to-pdf-script`](#xlsx-to-pdf-script) |
| osascript が `-609`「接続が無効」 で全 cell が沈黙・未書込 | 同一 tell に `close saving yes`+`quit` を詰めた / app 未 ready | reset + 4 勘所 → [`excel-osascript-cell-write`](#excel-osascript-cell-write) |
| osascript が `-50` パラメータエラー | **`save workbook as … PDF` (workbook 単位の verb)** / merged cell への number-format 設定 | PDF は **sheet 単位** `save as <sheet>` ([`xlsx-to-pdf.sh`](#xlsx-to-pdf-script)) / 書式強制は apostrophe (下行) |
| 日付が「46205」 等の serial 数字で印字される | Excel が和文日付文字列を date 値に auto-convert + cell 書式が General | **apostrophe prefix で text 強制** → [`excel-write-string-autoconvert`](#excel-write-string-autoconvert) |
| 申請日等が「火曜日, 6/月 16, 2026」 の冗長書式で表示 | `=TODAY()` 等 date 書式の cell を date 値で上書き → 冗長書式を継承 | apostrophe prefix の text で上書き → [`excel-write-string-autoconvert`](#excel-write-string-autoconvert) |
| 標題・縦書きラベル・textbox が消えた | openpyxl の save が drawing (shape) を破壊 | Excel osascript / fitz 直印字 / 別 file XML 移植 の 3 経路 → [`openpyxl-destroys-drawings`](#openpyxl-destroys-drawings) |
| 値は書けたが見た目を PDF で確認したい | — | [`xlsx-to-pdf.sh`](#xlsx-to-pdf-script) で render。 ⚠️ **Quick Look (`qlmanage`) は textbox/標題 を忠実に描かない** → drawing 健在は zip 内 drawing 数で、 体裁は xlsx-to-pdf.sh の PDF で |
| 承認欄/印影欄ボックスの**下罫線が出ない** (box が下に開く) | Excel→PDF が最下部の結合セル下罫線を落とす (罫線は xlsx に在るのに出力で消える) | **`close-pdf-form-boxes.py`** を pipeline 最後に挟む (= 開いた枠を全検出して閉じる、 print_area 拡張では直らない) → [`excel-pdf-bottom-border-drop`](#excel-pdf-bottom-border-drop) |
| 氏名/所属など**長い文字列が結合セルで両端切れ** | 固定 font でセル幅超過 + **shrink_to_fit は結合セルで無効** | **font size を下げる** (osascript は `font size of font object`) + `check-form-clipping.py` で機械検出 → [`merged-cell-text-clipping`](#merged-cell-text-clipping) |
| xlsx が openpyxl から save できない / lock `~$…` が残る | Excel が当該 file を開いている | Excel quit + lock 削除 → [`xlsx-locked-by-excel`](#xlsx-locked-by-excel) |
| Bash tool で `sleep` がブロックされ reset 待ちが打てない | harness が foreground の bare `sleep` を禁止 | bare sleep を打たず **script (xlsx-to-pdf.sh 等) に sleep を内包**させて呼ぶ / osascript 内 `delay` / 別 op は run_in_background |
| 何を / どこに書くか不明 | — | 着手前に [`form を dump`](#form-dump-first) (原則編が先) |
| 様式の label を誤って上書きしていないか | label vs input row の混同 | [`diff-form-xlsx.py`](#diff-form-xlsx-detection) で機械検出 |
| Word が「破損」 と言うが原因不明 | XML 宣言 single-quote / 空 `<w:tc>` 等 | [`check-docx-integrity.py`](#docx-checkbox-content-control) で決定論検出 |

---

## <a id="form-dump-first"></a>開始前に form を **必ず dump する** (= 推測で書かない)

雛形 xlsx を受け取ったら、 fill コードを書く前に必ず構造を全部出力する。 form ごとに layout・merged 範囲・data validation・列幅・font が異なる。 推測で write 先 cell を決めると merged の途中・validation 不整合・列幅と合わない font size を踏む。 ⚠️ **drawing の有無も起点で確認する**: `unzip -l form.xlsx | grep -iE 'drawing|media'` で textbox/縦書きラベル等の shape があれば openpyxl save で消える ([`openpyxl-destroys-drawings`](#openpyxl-destroys-drawings)) ので、 起点で検出して回避経路を選ぶ。

下記 `dump_form.py` を雛形毎に 1 回実行 → 出力を見て fill 対象 cell を確定する:

```python
#!/usr/bin/env python3
"""Inspect xlsx template structure: cells, merged, validation, column widths."""
import sys
from openpyxl import load_workbook

PATH = sys.argv[1] if len(sys.argv) > 1 else 'template.xlsx'
wb = load_workbook(PATH, data_only=False)

for sname in wb.sheetnames:
    ws = wb[sname]
    print(f"\n========== Sheet: {sname} [{ws.sheet_state}] ({ws.max_row}r × {ws.max_column}c) ==========")  # sheet_state で hidden/visible を起点で明示 (= 全シート把握原則)
    # Column widths
    print("\n-- Column widths --")
    for col_letter in 'ABCDEFGHIJKLMN':
        cd = ws.column_dimensions.get(col_letter)
        if cd and cd.width:
            print(f"  {col_letter}: {cd.width:.1f}")
    # Merged ranges
    if ws.merged_cells.ranges:
        print("\n-- Merged ranges --")
        for r in ws.merged_cells.ranges:
            print(f"  {r}")
    # Data validations (standard format; extension format is NOT readable by openpyxl)
    if ws.data_validations.dataValidation:
        print("\n-- Data validations --")
        for dv in ws.data_validations.dataValidation:
            print(f"  sqref={dv.sqref}, type={dv.type}, formula1={dv.formula1}, operator={dv.operator}")
    # All non-empty cells (label or value)
    print("\n-- Non-empty cells --")
    for row in ws.iter_rows():
        for c in row:
            if c.value is not None:
                v = str(c.value).replace('\n', '⏎')[:80]
                print(f"  {c.coordinate} (font={c.font.size}pt {c.font.name or '?'}, wrap={c.alignment.wrap_text}): {v}")
```

実行: `python3 dump_form.py /path/to/様式1.xlsx | tee form-structure.txt`

出力を `form-structure.txt` に保存しておくと、 fill code 書きながら同時に参照できる + 後で再 fill する時 (= 雛形更新時) の diff も取れる。

> **注**: openpyxl は **extension 形式の data validation** (Excel 2007+ で追加された list dropdown 等) を読めない (= `UserWarning: Data Validation extension is not supported and will be removed` で警告 + skip)。 dropdown 選択肢を知るには 雛形 xlsx を Excel/Numbers で開いて目視するか、 「リスト」 タブ (= form 内部の選択肢シート) を openpyxl で別途読む。

## <a id="form-filename-convention"></a>ファイル命名規約 (form 別 registry)

行政・学術 form ごとに「ファイル名フォーマット」 が指定されている場合が多い。 fill 先のファイル名は **form 仕様通り** に作る (= submit 時の自動検証に必要)。 観測したパターン (placeholder のみ、 literal は private repo 側に置く):

| Form | 命名規則 |
|---|---|
| JST SPReAD 様式1 | `様式1＿研究計画調書＿<機関コード半角数字>＿<姓ローマ字><名ローマ字>.xlsx` (区切りは **全角アンダースコア `＿`**、 「様式1」 の `1` は半角、 ローマ字氏名は姓名の順で連続書き) |
| 科研費 学振 DC1/DC2 | (個別の e-Rad 仕様、 form 毎に DC1.pdf / DC2.pdf 形式が指示される) |
| 学内・財団推薦書 (汎用) | `<書類種別>_<年度>_<対象者識別>_<目的>.<拡張子>` (区切りは form 仕様に従う、 半角_全角＿混在に注意) |

**最重要 gotcha — 区切り文字の半角/全角**: 公的様式の多くは雛形ファイル名で `＿` (全角アンダースコア、 U+FF3F) を使う。 user が補完入力する際に `_` (半角、 U+005F) で書くと spec 違反になる場合がある。 雛形ファイル名そのままを copy して提出側パーツだけ追記する方が安全。 「様式1」 の数字部分は 雛形によって半角/全角バラバラ (雛形 instruction では「様式１」 = 全角だが、 配布 file 名は「様式1」 = 半角、 など)。 **雛形 file 名を grep して、 文字種を厳密に確認する** のが第一歩。

新 form を扱う時は雛形の「記入にあたっての留意事項」 タブを最初に grep して、 ファイル名仕様を抽出する。 規則違反は submit 時に reject されることがあるため厳守。

---

## <a id="openpyxl-xlsx-fill"></a>openpyxl xlsx fill の落とし穴

### <a id="openpyxl-destroys-drawings"></a>⚠️ openpyxl の save は既存の textbox / shape (= 標題・縦書きラベル・図形) を破壊する

**症状**: 既存 xlsx (= 官製 / 事務様式テンプレ) を openpyxl で load → 値だけ書いて save すると、 **セルに乗っていない drawing オブジェクト (= 標題のテキストボックス・縦書きラベル・ロゴ図形・矢印) が消える**。 値は正しいのに「一番上の様式名が消えた」 等の事故になる (= 事務に「様式が改変されている」 と差し戻される。 label 上書き [`label-vs-input-antipattern`](#label-vs-input-antipattern) と並ぶ**様式改変の二大主因**)。

**原因**: openpyxl は drawing part (`xl/drawings/drawingN.xml`) を完全には round-trip できない。 load 時に解釈できない shape を保持せず、 save 時に drop する。 **`add_image` で入れた純画像は残るが、 textbox / autoshape / グループ化図形は失われる**。

**事前確認** (= 触る前に drawing の有無と種類を判定):
```bash
unzip -l form.xlsx | grep -iE 'drawing|media'
#   xl/drawings/drawing1.xml          → twoCellAnchor/oneCellAnchor の textbox/shape (= openpyxl が壊す。要保護)
#   xl/drawings/commentsDrawingN.vml  → セルコメントの吹き出し (= 別物。標題ではない)
#   xl/media/imageN.png               → 埋め込み画像
```

**回避 (2 択)**:
1. **Excel osascript で値を直接書く** (= drawing を一切触らず cell value だけ変更、 最も確実)。 osascript の組み立ては [`excel-osascript-cell-write`](#excel-osascript-cell-write) の堅牢パターンに従う。
0. **(紙提出だけなら最速)** 雛形を Excel で PDF 化 → PDF に fitz で直接印字 ([`pdf-prefill-direct`](#pdf-prefill-direct))。 xlsx 成果物が要らない当日運用向け。
2. **drawing XML を migration** (= openpyxl save 後の xlsx に、 元 xlsx の `xl/drawings/` + 関連 `_rels` part を zip レベルでコピーし直す)。 値編集と drawing 保護を両立したいが Excel を起動できない (CI 等) とき。 ⚠️ **別 file (= 標題を持つ blank テンプレ) から注入して復元するときは注入前に 4 点を確認** (= いずれか欠くと標題ずれ / 破損): ① 両 file の **merged 範囲が一致** (= drawing の anchor cell がずれず標題が正位置に乗る保証)、 ② テンプレ側 drawing が **standalone** (= `xl/media` 画像を参照しない。 参照ありなら media と rels も連れて行かないと dangling rel になる。 連れて行く場合は `[Content_Types].xml` に拡張子 Default 〔例: emf〕 も追加)、 ③ 注入先に **drawing が皆無で `rId` が衝突しない** (= 既に drawing を持つ file に重ねると rId 重複で Excel が破損判定)、 ④ **`<drawing r:id="…"/>` を挿す worksheet root に `xmlns:r` が宣言されているか確認** (= 一部の生成 tool 産 xlsx は root が `xmlns` のみで **`xmlns:r` 無し** 〔その file の `<legacyDrawing>` が inline `xmlns:r` を持っているのが signal〕。 そのまま挿すと unbound prefix = invalid XML で Excel が「壊れている」 ダイアログを出す。 inline で `<drawing xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="…"/>` と書けば安全)。 **注入後の機械 gate**: `scripts/check-xlsx-integrity.py FILE.xlsx` (= `check-docx-integrity.py` の xlsx 版。 全 XML well-formedness 〔unbound prefix = ④〕 + rels 両方向参照整合 〔dangling Target / 未定義 rId = ③ の検出面 / rId 重複〕 + [Content_Types] coverage を Excel 不要・決定論で検出、 exit 1 で fail)。 **zip 直編集した xlsx は納品前に必ず通す** — ③④ は実害 2 件とも本 gate で捕捉できた class (= 規約 prose の注意書きだけでは 2 回とも素通りした、 2026-06-10 RCA)。 pass 後 [`pdf-visual-confirm`](#pdf-visual-confirm) で標題の有無・位置を目視。 最終 ground truth は実機 open (= docx の教訓と同じ、 validator は必要条件。 ⚠️ AppleScript `open` の戻り値 "opened" は修復ダイアログの有無を検出できない = open 成功を健全性の根拠にしない)。

**再発しやすい経路 = 前例 fill script の流用** (2026-06-12 再発 RCA): 同種様式の過去 dir に openpyxl 製 fill script があると、 それを copy して書き始めるのが自然な動線になり、 **起点の drawing 確認を skip して同じ破壊を再演**する。 3 つの reflex で塞ぐ:
1. **前例 script を流用する瞬間こそ `unzip -l` 確認を発火**させる (= 「前例があるから安全」 は逆 — 前例 script が openpyxl 製なら前例 file 自身が既に標題を失っている可能性が高い)。
2. **openpyxl `load_workbook` 時の `UserWarning: DrawingML support is incomplete ... will be lost` は破壊予告**として扱う (= warning を見たら save する前に止まって経路を選び直す。 2>/dev/null で warning を捨てる習慣がこの signal を殺す)。
3. **過去の fill 済み file を base / 前例として再利用する前に drawing 数を確認** (= `python3 -c "import zipfile; print([n for n in zipfile.ZipFile('f.xlsx').namelist() if 'drawings/drawing' in n])"`)。 **喪失 file を base にすると喪失が連鎖**し、 「いつ消えたか」 の追跡も難しくなる。

**事後の横断 sweep**: この罠を一度踏んでいたと発覚したら、 同 repo の**過去の openpyxl 製 xlsx を全部 drawing 数で走査**する (= 1 件見つかった時点で同経路の他 file も喪失している可能性が高い。 2026-06-12 の走査では 3 file 中 3 file が喪失済みだった)。

origin: 2026-06 連続発生した「様式の標題テキストボックスが openpyxl save で消える」 事故。 cell value の一致検証では検出できず、 [`pdf-visual-confirm`](#pdf-visual-confirm) の PDF 画像確認で初めて気づく。 2026-06-12 に前例 script 流用経路で再発 (= 上記 reflex の起源)。

### <a id="excel-osascript-cell-write"></a>Excel osascript で cell 値を書く堅牢パターン (= drawing 保護 + -609 回避)

[`openpyxl-destroys-drawings`](#openpyxl-destroys-drawings) の回避 1 (= drawing を壊さず値だけ変える) や、 fill 後の微修正を Excel 経由でやる時の osascript の組み立て方。 **起動・reset** は [`xlsx-to-pdf-script`](#xlsx-to-pdf-script) の「連続 Excel 操作の reset」 (第 1 手 quit+sleep / 第 2 手 killall+sleep) に従い、 その上で **osascript 本体**を以下で組む:

```applescript
-- shell 側で先に reset: killall "Microsoft Excel"; sleep 6  (= cell 編集では sleep を 4 でなく 6 に厚く)
set lf to (ASCII character 10)
tell application "Microsoft Excel"
  activate
  delay 3                              -- 起動を待つ (cold start)
  set wbk to open workbook workbook file name (POSIX file "/abs/path/form.xlsx")
  delay 3                              -- workbook open を待つ
  set value of range "S13" of worksheet 1 of wbk to "..."    -- ★ worksheet は index 指定
  set ws2 to worksheet 2 of wbk
  set value of range "I10" of ws2 to ("行1" & lf & "行2")     -- ★ 改行は (ASCII character 10)
  save wbk
  delay 2
  close wbk saving no                  -- ★ save 済なので saving no (二重保存しない)
end tell
```
```bash
# ★ quit は別 osascript に分離 (同一 tell 内の close saving yes + quit は -609 を誘発)
osascript -e 'tell application "Microsoft Excel" to quit'
```

**4 つの勘所** (= いずれも欠くと「接続が無効です **(-609)**」 で値が書かれず沈黙失敗する、 2026-06-05 RCA):
1. **worksheet は index** (`worksheet 1` / `worksheet 2`) で指定 — シート名に全角括弧・末尾スペースがあると名前解決が不安定 (= **openpyxl とは逆**: openpyxl は名前が安全で数値 index が罠 〔[`sheet-by-name-not-index`](#sheet-by-name-not-index)〕、 Excel osascript は名前が不安定なので index を使う)。 ⚠️ ただし index は順序依存なので、 **`worksheet N` が目的シートか dump (= [`form-dump-first`](#form-dump-first)、 sheet_state 付き) で確認してから**指定する (= 「index で参考シート混入」 罠は Excel osascript でも起きる)。
2. **起動待ちを厚く** — `activate` 後 `delay 3` + `open` 後 `delay 3` (cold / killall 直後は特に)。
3. **`close ... saving no`** — `save wbk` の後に `saving yes` を重ねない (二重保存)。
4. **`quit` は別 osascript** — 同一 `tell` ブロックに `close saving yes` + `quit` (+ `return`) を詰めると接続が落ちる。

⚠️ delay/quit/cold-start の非同期対策は **AppleScript で Office app を automation する一般則** (= -609「接続無効」 は quit 後も AppleScript が reference を clear せず vanishing app にコマンドが届く / app 未 ready で起き、 **any app に共通**)。 Word docx→PDF も同根の gotcha ([`docx-pdf-stale-cache`](#docx-pdf-stale-cache) の cold-start / quit)。

⚠️ **merged cell の font size を osascript で変える正しい構文** (= 長い氏名/所属が結合セルで両端切れた時の根本対処): `set font size of font object of range "G13" of ws to 9` (= **property 名は `font size`**)。 よくある誤り = `set size of font object of …` → **`-1728` (object not found)** で沈黙失敗する (= `size` という property は font object に無い)。 setup によっては `-10006` (errAEPrivilegeError) が返ることもあり、 その時は各操作を `try` で囲んで続行。 ⚠️ **font が効かない時の fallback を `shrink_to_fit=True` にしてはいけない** — **shrink_to_fit は結合セルでは no-op** (Excel 制約) で、 立てても何も縮まず「直したつもり」 で clip が残る (= 2026-06-16 謝金様式⑭-1 所属見切れ事故の温床)。 結合セルの文字溢れは **font size を下げる** のが唯一効く手。 詳細・検出・検証は [`merged-cell-text-clipping`](#merged-cell-text-clipping)。 origin: 2026-06-04 謝金様式の fill 後微修正 + 2026-06-16 G13 所属見切れ RCA。

⚠️ **正しい AppleScript property 名が不明なときの特定法** (= 上記 `font size` を当てた手順): Excel の scripting 定義は `sdef "/Applications/Microsoft Excel.app"` で引けるが **Xcode が要る** (Command Line Tools のみだと `xcode-select: error … requires Xcode` で空振り)。 → 候補構文を **`try` ブロックで順に試し、 効いたものだけ flag を立てて最後に save する probe applescript** を 1 本書けば **1 起動で特定**できる (= 構文を当て推量で叩いて Excel を毎回 cold-start するより速い + [`excel-osascript-cell-write`](#excel-osascript-cell-write) の crash リスクも減る)。 2026-06-16 に `size of font object` (誤、 -1728) → `font size of font object` (正) を probe で 1 発特定。

⚠️ **`-1712` (AppleEvent timeout) は「Excel が固まっている」 signal**: 同一 session で Excel 操作 (= PDF export / cell write) を連続させると、 既存 instance が応答不能になり次の osascript が -1712 で落ちることがある。 復旧 = **`killall "Microsoft Excel"` → `sleep 5` → 再実行** (= -609 と同じ reset で直る、 driver script は 2 段 retry を組み込む)。 origin: 2026-06-11 雛形 PDF 化を 1 日に複数回実行した session。

⚠️ **多 round は -1712 で済まず Excel 本体を CRASH させる → 「単発記入」 を第一原則に** (2026-06-16 RCA): 同 session で open/save/close/quit を **5 cycle 以上**重ねると Excel が落ちて「作業内容を回復します」 dialog が出る (= cell 記入 + 日付 serial 修正 + 書式修正 + PDF 書出 を別々に叩いた)。 → **補正を最初の 1 pass の applescript に織り込み、 修正の往復をゼロにする**: cell を書いてから「serial 化してた / 書式が冗長」 と気づいて再 open するのでなく、 **最初から** [`excel-write-string-autoconvert`](#excel-write-string-autoconvert) の apostrophe prefix / `number format "@"` を入れておく (= 1 回の `open → set 全部 → save → close` で完結)。 round が避けられない時だけ各 op 前に killall reset。 ⚠️ crash しても **save 済 ∧ commit 済の disk file は無傷** (= git が安全網)。 Excel の「ドキュメントの回復」 pane が出ても **回復版を保存せず破棄** (disk の検証済 file が正、 回復版で上書きさせない)。

⚠️ **harness の Bash tool は foreground の bare `sleep` を block する** (= 「`killall …; sleep 6`」 を Bash に直書きすると止まる)。 → reset の待ちは (a) **`xlsx-to-pdf.sh` 等 script の内部 `sleep` に任せて script ごと呼ぶ**、 (b) **applescript 内の `delay`** で待つ、 (c) 長い処理は `run_in_background` で逃がす、 のいずれか。 bare `sleep` 直打ちに依存した reset 手順は harness 上で機能しない。

**検証**: 書き込み後は openpyxl で読み直して値を assert する (= osascript は失敗しても exit 0 で沈黙しがち)。 ⚠️ ただし **merged cell の値は fitz / openpyxl の text 抽出では取れないことがある** (= 結合範囲の左上以外は空に見える / PDF の text 抽出も同様) → 抽出の空振りを「書けていない」 と即断せず、 [`pdf-visual-confirm`](#pdf-visual-confirm) の PDF **画像**で最終確認する。

origin: 2026-06-05 学外者用様式 (= 複数シート + 数式参照 + textbox 標題) の cell 値修正。 killall 直後の 1 osascript (activate→open→set→save→close saving yes→quit) が -609 で全 cell 未書き込み → 上記 4 点で復旧。

### <a id="excel-write-string-autoconvert"></a>Excel 経由 write は文字列を auto-convert する (= 日付文字列が serial 数字で印字される)

**症状**: osascript で `set value of range "D12" ... to "2026年6月25日"` と**文字列**を書いたのに、 読み戻すと cell 値が date (= serial `46198`) になっている。 cell の表示形式が `General` のままだと **PDF / 印刷に「46198」 という生の serial 数字が印字**される (= 様式の作業日欄が数字の羅列になる事故)。 同様に `"1/2"` → 日付、 先頭 0 付き番号 → 数値、 等。

**原因**: Excel は UI 入力と同じ parser を `set value` にも適用する (= 文字列が日付・数値に見えれば**型ごと変換**)。 **openpyxl は literal 文字列をそのまま書くので、 この罠は Excel (osascript) 経由 write 固有** (= [`openpyxl-destroys-drawings`](#openpyxl-destroys-drawings) 回避 1 を選んだ時に新たに踏む罠、 という関係)。

**対処**: 日付・数値に見える文字列は **apostrophe prefix** で書く (= Excel の text 強制入力と同じ): `set value of range "D12" of ws to "'2026年6月25日"`。 cell 値は apostrophe 抜きの text になる。

**検証**: 書き込み後 openpyxl で read-back し、 **値の型** (= str か datetime/число か) と `cell.number_format` を確認する。 `datetime` + `'General'` の組合せ = serial 印字事故の前兆。 auto-convert された日付が「たまたま日付書式で表示される」 場合もあるが、 様式の前例が文字列なら文字列で揃える (= 事務側の見た目互換)。

origin: 2026-06-12 様式⑭-1 fill。 作業日 cell に書いた和文日付が serial 46198 (General) になり、 PDF 目視前の read-back 検証で捕捉 → apostrophe prefix で復旧。

⚠️ **追加 case 1 — `=TODAY()` 等 date 書式の cell を date 値で上書きすると「冗長書式」 を継承する** (2026-06-16): 申請日 cell が template で `=TODAY()` (date 書式付き) のとき、 そこに `"2026/6/16"` を書くと値が date になり、 cell の date 書式で「火曜日, 6/月 16, 2026」 のように冗長表示される (= General の serial 化とは別症状)。 → **apostrophe prefix の text** (`"'2026年6月16日"`) で上書きしてクリーンな固定文字列にする (= 申請日は提出時点の固定日なので `=TODAY()` の動的値より固定 text が正しい)。

⚠️ **追加 case 2 — `number format "@"` (text 書式化) は merged / 特定 cell で `-50` を返す** (2026-06-16): `set number format of range … to "@"` は普通 cell では効くが、 結合 cell 等では -50 (パラメータエラー) で失敗することがある。 → **apostrophe prefix が cell 種別に依らない universal な text 強制法** (= 書式変更を要さず値だけで text 化)。 `@` 書式に依存せず apostrophe を第一手にすると通る。 ⚠️ ただし「日付に見えない普通の文字列を text にしたい」 だけなら apostrophe 不要 (= auto-convert は日付・数値に見える文字列のみ)。

### <a id="excel-pdf-bottom-border-drop"></a>⚠️ Excel→PDF はフォーム最下部の結合セル下罫線を落とす (= 承認欄ボックス等が下に開く)

**症状**: Excel→PDF (印刷/書き出し) で、 フォーム**最下部にある結合セルの下罫線** (= 承認欄/印影欄ボックスの底辺の閉じ線) が描画されず、 ボックスが下に開いて見える。 罫線は xlsx に**定義済** (openpyxl の `cell.border.bottom.style` read-back で `'thin'` が返る) なのに、 出力 PDF だけで消える。 日本の行政・学術様式は全項目を枠で囲う文化なので、 承認欄が閉じていないと目立つ (= 2026-06-16 user 指摘「日本の糞エクセル文化ではすべてを枠で囲いがち」)。

**原因**: Excel は出力時にシート最下部の (特に結合セルの) 下罫線を落とす癖がある。 結合セル (例 `AC48:AG51` / `AH49:AJ51`) の bottom は最下行 (row 51) にあり、 その下が trailing empty row だと描画されない。 ⚠️ **`print_area` を下に伸ばしても直らない** (= 単純な「印刷境界での border drop」 ではない、 2026-06-16 に print_area row51→54 拡張で未改善を実証済)。

**検証の罠**: 「全幅の横罫線を pixel scan」 では **box 下罫線が部分幅 (承認欄の列幅のみ) なので検出できず**、 「下は白＝余白」 と誤判定する (= 2026-06-16 に実際にこれで user の正しい指摘を 1 度 dismiss した)。 → (a) PDF を**実画像で目視**、 or (b) `page.get_drawings()` で box 縦線群の bottom y に左右を繋ぐ水平線セグメントが在るか確認 (無ければ開いている)。

**原則 (= user 確立 2026-06-16「枠の下線が無くて開いている事は有り得ない」)**: 日本の行政・学術様式は全項目を枠で囲う文化なので、 **枠が「下罫線無しで開いている」 状態は設計上あり得ず、 必ず出力欠落**。 = 開いた枠を見つけたら「設計かも」 と迷わず**全て閉じる**。

**対処 (= システム、 確実)**: 一回限りの座標手描きでなく [`scripts/close-pdf-form-boxes.py`](../scripts/close-pdf-form-boxes.py) を **xlsx→PDF pipeline の最後に固定で挟む**:

```
xlsx → PDF (xlsx-to-pdf.sh) → fitz で p1 抽出 → close-pdf-form-boxes.py  ← この最後の 1 段で全枠を閉じる
```
PDF のベクター線だけで「**3 辺あって 1 辺欠けた矩形 (= 開いた枠)**」 を**全て**検出して欠けた辺を draw する (= xlsx 不要・engine 非依存、 **fill-in 下線〔縦線対を持たない単独の水平線〕 は枠でないので触れない = 設計を壊さない**、 冪等、 `--dry-run`/`--selftest` 内蔵)。 ⚠️ 検証は必ず **PDF→PNG 実画像で目視** (= 全幅 pixel scan は部分幅の box 罫線を拾えず「白=余白」 と誤判定する)。 内部実装の中核は下記 (= script の検出ロジック):

```python
import fitz
d=fitz.open(pdf); pg=d[0]; W,H=pg.rect.width,pg.rect.height
verts=[]
for dr in pg.get_drawings():
    for it in dr['items']:
        if it[0]=='l':
            x0,y0,x1,y1=it[1].x,it[1].y,it[2].x,it[2].y
            if abs(x0-x1)<1.5 and x0>0.6*W and max(y0,y1)>0.88*H: verts.append((x0,max(y0,y1)))
xs=[v[0] for v in verts]; ybot=max(v[1] for v in verts)
sh=pg.new_shape(); sh.draw_line(fitz.Point(min(xs),ybot), fitz.Point(max(xs),ybot))
sh.finish(color=(0,0,0), width=0.75); sh.commit(); d.save(pdf+'.t')  # → os.replace
```
Excel 側で結合セル border を再設定する手もあるが merged-cell border は描画が不安定なので、 出力 PDF への線描が確実。 ⚠️ ただし**生成物 PDF への後描画なので、 再生成したら再度引く必要**がある (= pipeline の最後に挟む)。

origin: 2026-06-16 様式⑭-1 の承認欄ボックス (`AC48:AG51`/`AH49:AJ51`) 下罫線が複数件とも未描画 → user 指摘 → 当初 1 箇所を座標手描きで閉じたが、 user「他も全部チェックする system を作れ」 で [`scripts/close-pdf-form-boxes.py`](../scripts/close-pdf-form-boxes.py) に格上げ (= 全枠を検査して閉じる、 selftest 付)。

### <a id="merged-cell-text-clipping"></a>⚠️ 結合セルの長文 clipping は shrink_to_fit が効かない → font size を下げる

**症状**: 氏名・所属など長い文字列を**結合セル** (例 `G13:M13`) に固定 font で書くと、 セル幅を超えた分が PDF 描画で **両端 clip** (center 配置なら左右、 left 配置なら右) される。 セル値そのものは完全なので値 diff (diff-form-xlsx) や read-back では出ず、 視覚確認も所属行を凝視しないと気づかない。 2026-06 謝金様式⑭-1 で長い研究機関名 (= 16 字相当) が中央付近だけ表示され目視で発覚 (= 値は完全)。 短い所属 (= 11 字程度) は収まるので **長い値でだけ顕在化する silent failure**。

**原因 + 効かない対処**: ⚠️ **shrink_to_fit は結合セルでは no-op** (Excel 制約)。 `Alignment(..., shrink_to_fit=True)` を立てても結合セルでは何も縮まない。 font 設定が効かない時の fallback を shrink_to_fit にすると「直したつもり」 で clip が残る (= この罠で 1 度はまった)。

**対処 (= 結合セルで唯一効く = font size を下げる)**:
- osascript (= 標題 drawing を保護したい様式。 [`excel-osascript-cell-write`](#excel-osascript-cell-write) 経由): `set font size of font object of range "G13" of ws to 9` — property 名は **`font size`** (`size` だと `-1728` object-not-found で沈黙失敗)。
- openpyxl (= drawing 無しの form): `from copy import copy; f = copy(c.font); f.size = 9; c.font = f` を**結合範囲の左上 cell** ([`merged-cell-write-topleft`](#merged-cell-write-topleft)) に。 ⚠️ ただし openpyxl save は drawing を消す ([`openpyxl-destroys-drawings`](#openpyxl-destroys-drawings)) ので標題付き様式では osascript 必須。
- size の目安: 収まる近傍値から比例で当てる (例: 11 字 @14pt が収まるなら 16 字相当は 14×11/16 ≈ 9pt) → 検出器 + 視覚で詰める。

**検証 (= 機械 + 視覚、 両方)**: [`scripts/check-form-clipping.py`](../scripts/check-form-clipping.py) `<雛形.xlsx> <記入済.xlsx> <生成.pdf>` が、 雛形 diff で**記入セルだけ**に絞り、 各記入値が PDF 抽出テキストに完全な部分文字列として現れるか機械照合する (= 欠落 ≥3 字を clip 疑いとして flag、 `--selftest` 内蔵)。 ⚠️ レンダラによっては clip でも text 層に全文が残るので **[`pdf-visual-confirm`](#pdf-visual-confirm) の視覚確認も必ず併用** (= 検証 3 層は相互代替不可)。

**再生成 pipeline** (= 様式⑭ 系を直したら毎回この順):

```
font 修正 → xlsx-to-pdf.sh → fitz で p1 抽出 → close-pdf-form-boxes.py → check-form-clipping.py + 視覚確認
```

origin: 2026-06 謝金様式⑭-1 の G13 所属見切れ。 当時の規約が [`clear-yellow-fill-marks`](#clear-yellow-fill-marks) で shrink_to_fit=True を勧めていた (= 結合セルで無効) ため「規約どおりにやると直らない」 状態だった → font 縮小に訂正 + 機械検出器 (check-form-clipping.py) を新設し principles §2「機械層は clipping 捕捉不能」 を更新。

### <a id="xlimage-size-silent-fail"></a>`XLImage.width` / `.height` setter は silent fail する

**症状**: `openpyxl.drawing.image.Image` (= `XLImage`) のインスタンスに `img.width = 600` / `img.height = 400` を代入しても save 後の xlsx には反映されず、 元 PNG のオリジナル解像度がそのまま埋め込まれる。 Excel 側では rendered display で縮小されているように見えるので気づきにくい。

**原因**: `XLImage.width` / `.height` は内部の `PIL.Image` インスタンスの `width` / `height` プロパティを proxy しているが、 PIL 側は **read-only**。代入は silent に no-op になる。

**正しい解法**: PIL で実 resize して別ファイルに保存、 それを embed する。

```python
from PIL import Image as PILImage
from openpyxl.drawing.image import Image as XLImage

src = Path('research-flow.png')
resized = Path('research-flow-embed.png')
target_width_px = 640

pil = PILImage.open(src)
new_size = (target_width_px, int(target_width_px * pil.height / pil.width))
pil.resize(new_size, PILImage.LANCZOS).save(resized)

img = XLImage(str(resized))  # ← resized 版を embed
ws.add_image(img)
```

### <a id="sheet-by-name-not-index"></a>画像挿入は `wb[シート名]` で参照、 `wb.sheetnames[N]` の数値 index は罠

**症状**: 「5 枚目のシート」 という指示を `wb.sheetnames[4]` で取ると、 form template が先頭に参考シート (= 「はじめにご確認ください」 / 「府省共通経費取扱区分表」 等) を持っている場合、 実際は「研究計画調書\_3 枚目」 を指してしまう。 結果として SS が間違ったシートに貼られる。

**正しい解法**: シート名を**直接指定**する。

```python
wb = load_workbook(xlsx_path)
# Bad: ws = wb[wb.sheetnames[4]]   # 5 枚目目的だが index で取ると参考シートを跨ぐと壊れる
# Good:
ws = wb['研究計画調書_5枚目']        # form template の実際のシート名で参照
img = XLImage(ss_path)
img.anchor = 'A1'
ws.add_image(img)
```

事前に `print(wb.sheetnames)` で全シート名を dump して目的のシートを目視で特定する習慣を持つ (= [`dump-cell-structure-first`](#dump-cell-structure-first) 「最初に dump」 原則と同源)。

⚠️ **Excel osascript (AppleScript) は逆向き**: シート名に全角括弧・末尾スペースがあると名前解決が不安定なので `worksheet N` (index) で指定する ([`excel-osascript-cell-write`](#excel-osascript-cell-write))。 = **ツールで安全な指定法が逆** (openpyxl は名前 / Excel osascript は index) なので混同しない。 ただし osascript 側も index の順序依存罠 (= 上記の参考シート混入) は残るので、 dump で `worksheet N` が目的シートか確認する。

### <a id="image-anchor-onecellanchor"></a>画像 anchor は `OneCellAnchor` + `ext` で完全制御

**症状**: `img.anchor = 'A13'` (string) は openpyxl 内部で `OneCellAnchor` に変換されるが、 ext (= 表示サイズ) は画像 metadata に依存して不安定。 また cell の top-left ぴったりに anchor すると上の cell の罫線と接触して**罫線を切る**ように見える。

**正しい解法**:

```python
from openpyxl.drawing.spreadsheet_drawing import OneCellAnchor, AnchorMarker
from openpyxl.drawing.xdr import XDRPositiveSize2D

EMU_PER_PX = 9525  # 96 DPI で 1 px = 9525 EMU
OFFSET_PX = 10      # cell の top-left からのオフセット (= 罫線との空き)

img.anchor = OneCellAnchor(
    _from=AnchorMarker(
        col=0, row=12,            # 0-indexed: col 0 = A、row 12 = 1-indexed の 13 行目
        colOff=EMU_PER_PX * OFFSET_PX,
        rowOff=EMU_PER_PX * OFFSET_PX,
    ),
    ext=XDRPositiveSize2D(
        cx=EMU_PER_PX * resized_width_px,
        cy=EMU_PER_PX * resized_height_px,
    ),
)
ws.add_image(img)
```

- `_from.row` / `.col` は **0-indexed** (= openpyxl の cell address 1-indexed と混乱しがち)
- 罫線切り回避には `colOff` / `rowOff` で数 px 内側に配置
- 行高は画像の pt 換算 (`px × 72 / 96`) + offset + padding で確保

### <a id="column-width-units"></a>列幅の単位は Excel "0-glyph" units (= 不直感)

**問題**: `ws.column_dimensions['A'].width` の値 (例: 96.64) は px でも pt でもない。「default フォントで "0" 文字を何個並べられるか」 という独自単位。 Japanese 全角文字の幅推定には換算が必要。

**換算式**:

```python
# col_width = ws.column_dimensions['A'].width  # 例: 96.64
pixel_width = col_width * 7.0                  # Excel column width × 7 px ≈ 実 px 幅
char_px_japanese = font_size * 1.33            # 全角 char 幅 ≈ font_size pt × 1.33
chars_per_line = int(pixel_width / char_px_japanese * safety)  # safety=0.92~0.95
```

96.64 units、 10pt MS Pゴシック → 676 px ÷ 13.3 px/char × 0.92 ≈ **46 chars/line** (全角)。

### <a id="wrap-text-needs-row-height"></a>`wrap_text=True` だけでは Excel は行高 auto-fit しない

**症状**: cell に `Alignment(wrap_text=True)` を set + 長文書き込みしても、 openpyxl で save した xlsx を Excel で開くと行高が小さいまま (= text が切れて 1 行だけ表示)。

**原因**: Excel の auto-fit row height は user 操作 (ホーム → 書式 → 行の高さの自動調整) で発動する機能で、 ファイル open 時に自動実行されない (= openpyxl 経由の save は customHeight=True で固定扱い)。

**正しい解法**: 行高を openpyxl 側で **論理的に計算して explicit set** する。

```python
from openpyxl.styles import Alignment

def fit_cell(ws, addr, content, line_height_pt=12.5, pad_pt=4, safety=0.95):
    """wrap_text を有効化し、 column width から chars/line を auto 算出して行高を set。"""
    cell = ws[addr]
    cell.alignment = Alignment(wrap_text=True, vertical='top',
                                horizontal=cell.alignment.horizontal or 'left')
    if content is None:
        return
    col_letter = cell.column_letter
    col_width = ws.column_dimensions.get(col_letter)
    col_width = (col_width.width if col_width and col_width.width else None) \
        or ws.sheet_format.defaultColWidth or 8.43
    font_size = cell.font.size or 10
    chars_per_line = max(1, int(col_width * 7.0 / (font_size * 1.33) * safety))
    text_lines = str(content).split('\n')
    wrap_lines = sum(max(1, (len(line) + chars_per_line - 1) // chars_per_line)
                     for line in text_lines)
    height = max(20, wrap_lines * line_height_pt + pad_pt)
    ws.row_dimensions[cell.row].height = height
```

経験値:
- `line_height_pt = 12.5` (10 pt フォント × 1.25 line spacing 相当)
- `pad_pt = 4` (= 上下 margin 計 4 pt)
- `safety = 0.95` (= chars/line を保守的に縮めて wrap 安全)

これより generous (line_height=14、 pad=14) にすると cell 下に **余白が貯まる** (user 視覚で「スカスカ」 感)、 tight すぎる (line_height=11、 pad=0) と最終行が clip する。

### <a id="data-validation-not-enforced"></a>Excel data validation の auto-resize は外部信号で発動しない

`ws.data_validations.dataValidation` で読める validation rule (例: `type=whole, formula1=9999999`) は openpyxl で write しても Excel 側の dropdown / 入力制限が発動するかは Excel version 依存。 リスト dropdown (extension 形式) は openpyxl が読めず警告を出す。 **値の正当性は openpyxl 側で別途検証する**。

### <a id="xlsx-locked-by-excel"></a>xlsx は Excel に open されている間は openpyxl から save できない

**症状**: `wb.save(path)` が `PermissionError: [Errno 13]` で fail する、 または silently 別 tempfile に書いて消える。

**原因**: Excel が xlsx を編集モードで lock している。

**正しい解法**: 再 fill する前に必ず Excel を quit:

```bash
osascript -e 'tell application "Microsoft Excel" to quit' 2>/dev/null
sleep 1
python3 fill_xlsx.py
open -a "Microsoft Excel" /path/to/output.xlsx
```

`fill_xlsx.py` を反復実行する work-loop ではこの 3 行を冒頭に置く。

### <a id="merged-cell-write-topleft"></a>Merged cells への write は top-left のみ有効

**症状**: 例えば `B7:I7` が merged なのに `ws['D7'] = 'value'` と書いても表示されない (= D7 は merged の途中で、 top-left は B7)。

**正しい解法**: dump で merged 範囲を確認、 必ず **左上 cell** に write:

```python
# B7:I7 merged → 必ず B7 (= top-left) に書く、 D7 や F7 ではない
ws['B7'] = 'my-input-value'
```

`ws.merged_cells.ranges` で全 merged 範囲を列挙できる (上記 [`form-dump-first`](#form-dump-first) `dump_form.py` 参照)。

⚠️ **同じ項目でも sheet ごとに座標が違う — 別 sheet の座標を流用しない**: 同じ様式集の複数 sheet (= 申請 sheet と報告 sheet 等) は同じ項目 (= 担当者欄等) を **別座標**に置くことが多い。 sheet A で確定した座標を sheet B にそのまま流用すると、 B では merged の **非 top-left** を指し、 openpyxl の `MergedCell` は read-only なので write が `AttributeError` か (各操作を try/except で被せていると) 黙って no-op になり、 **値が入らないまま PDF が出る** (= silent fail。 cell 値検証でも当該 cell が空に見えるだけで原因が分かりにくい)。 → 座標は使い回さず **sheet ごとに [`form-dump-first`](#form-dump-first) で merged 範囲を取り直し**、 その sheet 固有の top-left に write する。 全 sheet を漏れなく回す sweep は [`all-sheet-sweep`](#all-sheet-sweep)。

⚠️ **border も同じく anchor (左上) cell に set する** (= value だけでなく罫線も): 例えば `H91:S93` merged の **下罫線**を引くとき、 構成 cell (= `H93` 等、 merge の途中) に `cell.border = Border(bottom=...)` しても **save で消える / 元の罫線に戻る** (= 非 anchor cell への border 代入は openpyxl/Excel で安定しない)。 merged 範囲の外周罫線は必ず **anchor cell** に set する (= 上罫線も下罫線も左右罫線も anchor 1 つで merge 全体の外周に効く):

```python
# H91:S93 merged の「下」罫線 → 構成 cell H93 ではなく anchor H91 に set
from openpyxl.styles import Border, Side
from copy import copy
a = ws['H91']                         # anchor (= top-left)
b = a.border
a.border = Border(top=copy(b.top), left=copy(b.left), right=copy(b.right), bottom=Side(style='thin'))
```

検証は read-back では不十分 (= 非 anchor cell の border は読めても render に出ないことがある) → 必ず PDF **画像**で確認する ([`pdf-visual-confirm`](#pdf-visual-confirm))。 症状例: 表の最下行が merged のとき左端 column だけ下罫線が欠ける (= 構成 cell に set して消えた)。

### <a id="bool-cell-hash-overflow"></a>Boolean checkbox cell は narrow column で `###` 表示

**症状**: `ws['F20'] = True` と書いた cell が Excel で `###` と表示される。 値そのものは TRUE で正しい。

**原因**: Excel は bool を `TRUE` / `FALSE` の文字列幅で render する。 列幅が narrow (= 4 chars 程度未満) だと `###` overflow indicator になる。 多くの form template は label と組み合わせる narrow column 想定で bool を置くので、 `###` が正常表示。

**対処**:
- 機能上は問題なし (値は TRUE)、 表示だけ気にしない
- どうしても見えるようにしたいなら、 該当列を一時的に広げる: `ws.column_dimensions['F'].width = 6`
- ただし form 雛形の列幅変更は他の cell 表示を崩すリスクがあるため、 表示優先より値優先を取る

### <a id="datetime-cell-hash-overflow"></a>日付 (datetime) を narrow / merged cell に入れると「###」 表示

**症状**: `ws['B5'] = datetime(2026, 6, 1)` のように datetime 値を狭い列幅 / merged cell に書くと、 Excel で `###############` と表示される (= [`bool-cell-hash-overflow`](#bool-cell-hash-overflow) の bool `###` と同種の overflow indicator)。 cell 値そのものは正しい日付。

**原因**: Excel は datetime を `2026/6/1` 等の date 書式文字列の幅で render する。 列幅がその文字列より狭いと `###` overflow になる。 日付欄を narrow merged cell に置く form template で頻発。

**正しい解法**: 日付は datetime オブジェクトではなく **文字列** で write すると潰れにくい:

```python
ws['B5'] = "2026/6/1"               # str。 datetime より幅を取らず ### になりにくい
# ws['B5'] = datetime(2026, 6, 1)   # ← narrow cell で ### 化しやすい
```

⚠️ この潰れは cell 値検証 (= [`diff-form-xlsx-detection`](#diff-form-xlsx-detection) `diff-form-xlsx.py`) では catch **できない** (= 値は正しい)。 **PDF visual confirmation ([`pdf-visual-confirm`](#pdf-visual-confirm)) でのみ可視化される**。 ⚠️ **PDF の text 抽出 (`"###" in text`) で overflow を検出するのは信頼できない**: `###` は表示上の overflow indicator で、 PDF text 層の内容は **renderer 依存で不定** (= 元の値 / 文字コード差で化けた文字列 / 稀に `###` literal のいずれか)。 多くは grep が空振りして「直った」 と誤認する (= false negative)、 たまたま literal が載れば拾えるが当てにならない。 overflow は LAYOUT 問題なので **PNG 画像で目視**して確定する ([`image-budget-exhaustion`](#image-budget-exhaustion) の CONTENT/LAYOUT 検証切り分け)。 fill 後の PDF 確認 (= [`xlsx-to-pdf-script`](#xlsx-to-pdf-script) `xlsx-to-pdf.sh`) を必須とする理由の一つ。

### <a id="int-vs-str-by-spec"></a>値の型 (`int` vs `str`) は form の仕様で決まる

**判定基準** (form の cell 仕様から):

1. **`=LEN(<cell>)` のような counter formula が当該 cell に紐付いている** → str で write (LEN は string 長を期待、 int 渡しても内部 stringify されるが想定外動作のリスク)
2. **`data validation type=whole` (= 整数要求) が当該 cell に付いている** → int で write (= 検証 pass)
3. **両方ある** → form 設計矛盾。 data validation 優先 (= int)、 counter は通らないが多くの form でエラー扱いされない
4. **どちらもない** → 数値は int、 文字列は str、 default 通り

`ws.data_validations.dataValidation` で type を、 隣接 cell の formula で counter を、 [`form-dump-first`](#form-dump-first) dump で同時に確認する。

```python
# 例: 研究者番号 cell が type=whole validation 付き、 counter なし → int
ws['B6'] = 12345678          # int で write

# 例: 課題名 cell が =LEN(B22) counter 付き → str (本来 string なので素直)
ws['B22'] = '研究課題名のテキスト'

# 例: 生年月日 cell が yyyymmdd 半角数字指定 + type=whole → int
ws['B10'] = 19990101          # int (= 8 桁 yyyymmdd)
```

### <a id="print-area-one-page"></a>Print area / page setup を設定して PDF を 1 ページ化

xlsx → PDF 変換 ([`xlsx-to-pdf-script`](#xlsx-to-pdf-script)) で 1 sheet が複数ページに分割される問題は、 form 雛形が print area を設定していないことが原因。 openpyxl で fit-to-width を強制:

```python
from openpyxl.worksheet.page import PrintOptions, PageMargins

ws.page_setup.fitToWidth = 1
ws.page_setup.fitToHeight = 0  # = unlimited (縦は何ページでも可、 幅だけ 1 ページ)
ws.sheet_properties.pageSetUpPr.fitToPage = True
ws.page_margins = PageMargins(left=0.5, right=0.5, top=0.5, bottom=0.5)
ws.print_options.horizontalCentered = True
```

研究費 form の場合: 実提出は xlsx そのものなので print area 設定は省略可。 確認用 PDF を綺麗に出したい時のみ追加。

### <a id="row-height-409pt-limit"></a>Excel の行高さ上限は 409pt — これを超えると視覚的に「非表示」 化する

**症状**: 行高さに 591.5pt や 2754pt 等の極端な値が入った xlsx を Excel で開くと、 周囲の行が「非表示扱い」 のように見える (= 巨大行が画面を占有し、 viewport 内で他の行が visible にならない)。 reviewer (= 事務担当者) から「行 N-M が非表示になっている」 と指摘される。

**原因**: Excel の行高さ MAX = **409pt** (= ~545 px @ 96 dpi、 ~14 cm)。 openpyxl は値を strict 検証しないため 409pt を超えても save できるが、 Excel で開くと表示が異常になる。 ユーザー直接編集時の auto-resize (= 長文 + wrap_text=True で row 高さが自動拡大) で意図せず 409pt 超過に陥るケース多し。

**正しい解法**: row height は内容量から論理計算した値を **409pt 以内** に収める。 [`wrap-text-needs-row-height`](#wrap-text-needs-row-height) `fit_cell` 計算式を使えば自動的に reasonable な値になるが、 既に巨大値が入った xlsx を inherit する場合は再計算で明示 reset:

```python
# 既存の超過 row height を reset
for r in range(1, ws.max_row + 1):
    h = ws.row_dimensions[r].height
    if h and h > 409:
        ws.row_dimensions[r].height = min(409, _calc_height_for_cell(ws, r))
```

origin: 2026-05-14 JST SPReAD で 行 22 = 591.5pt / 行 26 = 2754pt の状態が「行 20-22 が非表示」 として事務担当者から指摘 → 行 22 = 30pt / 行 26 = 150pt に reset で修復。

### <a id="topleftcell-scroll-persist"></a>sheetView.topLeftCell の scroll 位置 persistence

**症状**: 提出した xlsx を reviewer が開くと、 ファイルの先頭ではなく中間行 (= A17 等) から表示される。 reviewer が「先頭が表示されない、 内容が欠けている」 と誤解する。

**原因**: xlsx の sheet metadata に `<sheetView topLeftCell="A17">` が記録されている。 これは Excel/openpyxl で「最後にユーザーが scroll した位置」 を保存する仕様で、 file 保存時に巨大行 (= [`row-height-409pt-limit`](#row-height-409pt-limit)) が view を占めていたとき、 viewport 起点が下方に固定される。 template 配布者が「入力位置にスクロール済」 で配布する慣習もあるが、 reviewer 視点では先頭から見たい。

**正しい解法**: 提出前に topLeftCell を A1 に reset:

```python
for sname in wb.sheetnames:
    wb[sname].sheet_view.topLeftCell = "A1"
```

または最初の submission で行高 (= [`row-height-409pt-limit`](#row-height-409pt-limit)) を適切化していれば、 topLeftCell も自然に A1 のままになる (= scroll 履歴が template 配布時点のまま)。

origin: 2026-05-14 JST SPReAD で「行 20-22 が非表示」 指摘と同時に発覚。 topLeftCell="A17" のままだと先頭の研究者情報行 (= 行 6-15) が viewport 外で「行を欠落して提出された」 と誤読される risk。

### <a id="xlsx-rich-text-underline"></a>xlsx rich text formatting (= 部分 underline / bold / italic)

行政・学術 様式 で「**著者 (本人に下線)**」 「**重要部分は太字**」 等の要件がある場合、 セル内の特定文字列だけに format を適用する必要がある。 openpyxl では **`CellRichText` + `TextBlock` + `InlineFont`** で実装。

```python
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont

# Run-level font specs (= 同じ font name / size、 装飾だけ差し替え)
plain = InlineFont(rFont="ＭＳ Ｐゴシック", sz=10)
underlined = InlineFont(rFont="ＭＳ Ｐゴシック", sz=10, u="single")
bold = InlineFont(rFont="ＭＳ Ｐゴシック", sz=10, b=True)

# Build the rich text from alternating runs (= 業績欄の例、 本人氏名のみ下線)
# cell.value (= 例): "C1, C2 and SELF, \"Title A\", J1 ... \nC3, SELF and C4, \"Title B\", J2 ..."
TARGET = "<applicant-name>"  # = 提出者の姓 or イニシャル (form の表記に合わせる)
parts, remaining = [], cell.value
while True:
    idx = remaining.find(TARGET)
    if idx < 0:
        if remaining: parts.append(TextBlock(plain, remaining))
        break
    if idx > 0: parts.append(TextBlock(plain, remaining[:idx]))
    parts.append(TextBlock(underlined, TARGET))
    remaining = remaining[idx + len(TARGET):]
cell.value = CellRichText(parts)
```

**重要 caveat — openpyxl readback の flatten bug**: 上記で書いた xlsx を後で `cell.value` で read back すると **`str` 型に flatten される** (= rich text の run 構造が見えない)。 format が正しく保存されたかを verify するには **xlsx の生 XML を unzip → `xl/worksheets/sheetN.xml` で `<u val="single"/>` 等を grep** する:

```python
import zipfile, re
with zipfile.ZipFile(xlsx_path) as z:
    xml = z.read("xl/worksheets/sheet4.xml").decode("utf-8")
underline_runs = re.findall(r'<u val="single"/>[^<]*</rPr><t[^>]*>([^<]+)</t>', xml)
print(f"Underlined runs: {underline_runs}")  # ['<applicant-initial>', '<applicant-initial>', ...]
```

xlsx XML の文字エンコード形式: ＭＳ Ｐゴシック等の全角文字は `&#65325;&#65331;` 等の numeric character reference にされる。 visual diff には decode しなければ読みにくい。

origin: 2026-05-14 JST SPReAD 様式 1 Sheet 2 A15 (研究業績欄) で提出者本人氏名 (= 業績 5 件すべて) に underline を rich text で適用。 readback は str だったが xlsx 内部 XML 上で `<u val="single"/>` × 5 個 確認で OK 検証。

---

## <a id="xlsx-md-to-pdf"></a>xlsx / md → PDF 変換 (macOS)

### <a id="xlsx-to-pdf-script"></a>xlsx → PDF: `xlsx-to-pdf.sh` (LibreOffice → Excel fallback)

汎用スクリプト [`scripts/xlsx-to-pdf.sh`](../scripts/xlsx-to-pdf.sh) を使う。 openpyxl は cell 値の read/write のみで PDF を **render できない**ため、 実 render engine が要る。 スクリプトは利用可能な engine を自動選択する:

```bash
xlsx-to-pdf.sh <input.xlsx> [sheet] [output.pdf]
```

| 優先 | engine | platform | sheet 指定 | 採用条件 |
|---|---|---|---|---|
| 1 | LibreOffice (`soffice --headless --convert-to pdf`) | Linux / Windows / macOS | ✗ (workbook 全体) | `soffice` / `libreoffice` が PATH にある |
| 2 | Microsoft Excel (osascript) | macOS のみ | ✓ (1 sheet) | LibreOffice 不在時の fallback |

- `sheet` 省略時は active sheet (Excel) / workbook 全体 (LibreOffice)。 `sheet` 指定は **Excel engine 専用** — LibreOffice engine は warning を出して無視 (workbook 全体を出力)。 ⚠️ **但し Excel の単一 sheet 指定は version 依存で当てにならない** (= observed: `save as active/worksheet` でも workbook 全 visible sheet が出る)。 出力ページを確実に制御するには [`excel-pdf-whole-workbook-export`](#excel-pdf-whole-workbook-export) の「不要 sheet を temp で削除」 を使う。
- `output.pdf` 省略時は input と同じ場所・同名 `.pdf`。
- LibreOffice engine は isolated user profile (`-env:UserInstallation`) で起動するので、 LibreOffice GUI を開いたままでも変換できる。

🔑 **macOS + Excel engine は「オートメーション権限」が前提**:
- 初回実行時に macOS が「"osascript" が "Microsoft Excel" を制御することを求めています」ダイアログを出す → 「許可」。
- ⚠️ **background 実行 (`run_in_background` / nohup 等) はダイアログが見えず AppleEvent timeout (-1712) で失敗する**。 初回は必ず **foreground** で実行してダイアログに応答する。 一度許可すれば以後は無確認。 ⚠️ **長時間コマンド (= 「PDF 生成 + fitz 抽出 + git commit」 を 1 コマンドに詰める等) は harness が自動で background に回すことがある** (= `run_in_background` 未指定でも「Command running in background」 になる) → Excel GUI 操作が background 化されて同 timeout。 **Excel を呼ぶコマンドは単独・短命に保つ** (= PDF 生成だけ。 fitz 抽出 / git commit は別コマンドに分離)。
- 後から変更: システム設定 > プライバシーとセキュリティ > オートメーション。

🔑 **連続 Excel 操作の不安定化と確実な reset (= 2026-06-05 RCA)**: 1 セッションで Excel を多数回 (= 10 回以上) 開閉すると、 `osascript ... to quit` が **非同期** (quit が返っても Excel は終了処理中) なため、 次の `open` 時に**前プロセスが残存** → AppleEvent 無応答 **(-1712)** / パラメータ拒否 **(-50)** が散発する。
- **第 1 手 (通常)**: Excel を呼ぶ前に **`osascript -e 'tell application "Microsoft Excel" to quit'; sleep 3`** (= sleep を 1 でなく **3 以上**に厚く、 quit の非同期完了を待つ)。
- **第 2 手 (失敗時)**: -1712 / -50 / **接続無効 (-609)** が出たら **`killall "Microsoft Excel"; sleep 4`** (= cell 値編集で killall を使うときは **sleep 6** に厚く) でプロセス強制終了 → クリーン起動 (= 2026-06-05 はこれで復旧)。 ⚠️ **`killall` は user が開いている未保存 Excel も問答無用で閉じる** → Claude 作業中に user が Excel を触らない前提でのみ使う (= 通常は第 1 手、 killall は最終手段)。 ⚠️ **killall 直後に cell 値を書く osascript を撃つ場合は起動待ち + 組み立て方が critical** → [`excel-osascript-cell-write`](#excel-osascript-cell-write) の 4 勘所に従う (= 怠ると -609 で沈黙失敗)。
- **失敗の沈黙化を防ぐ**: 上記「単独・短命」 と合わせ、 Excel コマンド直後に**出力ファイルの存在を検査**して失敗を verbose に surface する (= background 化 + GUI 不調の二重で失敗が埋もれた 2026-06-05 RCA。 `[ -f out.pdf ] || echo FAILED` を後置)。
- 設計判断: `xlsx-to-pdf.sh` の Excel engine 分岐の起動直前に第 1 手 (quit + sleep) を組み込み済 (= 呼び出し側で忘れても毎回クリーン起動)。

注意:
- 印刷範囲・ページレイアウトが未設定だと各 sheet が複数ページに分割される。 提案書用途では問題ないが、 1 ページに収めたい場合は事前に [`print-area-one-page`](#print-area-one-page) (`ws.page_setup.fitToWidth = 1` 等) を openpyxl で set。
- 提出本体は xlsx、 PDF は確認 / 添付用 snapshot ([`pdf-snapshot-xlsx-submission`](#pdf-snapshot-xlsx-submission))。 fill 後の見た目崩れ (= merged cell の値潰れ・列幅不足の `###`、 [`bool-cell-hash-overflow`](#bool-cell-hash-overflow) / [`datetime-cell-hash-overflow`](#datetime-cell-hash-overflow)) はこの PDF でのみ可視化される (= [`pdf-visual-confirm`](#pdf-visual-confirm) の PDF visual confirmation 義務)。

### <a id="md-to-pdf-chrome"></a>md → PDF: Chrome headless + Python markdown

```python
import markdown, subprocess
from pathlib import Path

html_body = markdown.markdown(md_text, extensions=['tables', 'fenced_code', 'toc'])
html = f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<style>
@page {{ size: A4; margin: 18mm; }}
body {{ font-family: 'Hiragino Sans', 'Yu Gothic', sans-serif;
        line-height: 1.55; font-size: 10.5pt; }}
table {{ border-collapse: collapse; }}
th, td {{ border: 1px solid #888; padding: 4px 8px; }}
</style></head><body>{html_body}</body></html>"""

Path('/tmp/out.html').write_text(html, encoding='utf-8')
subprocess.run([
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '--headless=new', '--disable-gpu', '--no-pdf-header-footer',
    '--print-to-pdf=/path/to/out.pdf',
    'file:///tmp/out.html',
], check=True)
```

注意:
- Chrome `--headless=new` を必ず使う (旧 `--headless` は 2024 以降 deprecated)
- `--no-pdf-header-footer` で URL / ページ番号の footer を抑制
- 日本語 font は `font-family: 'Hiragino Sans', 'Yu Gothic', sans-serif` で macOS native font を指定 (= TeX 経由より高速 + 字体が綺麗)
- pandoc は不要 (= 別途 install せずに済む)、 Python `markdown` ライブラリで HTML 生成 + Chrome で render

### <a id="pdf-snapshot-xlsx-submission"></a>PDF は確認 / 印刷 / 後参照用、 提出は xlsx 本体

研究費応募 (e-Rad) や事務書類提出時、 PDF は **reference snapshot** で、 実提出は xlsx (or docx) 本体。 PDF と xlsx が drift しないよう、 PDF は `fill_xlsx.py` 実行後に再生成する pipeline にする。

### <a id="pdf-prefill-direct"></a>雛形 PDF への直接印字 (= drawing 保護の回避経路 3、 紙提出専用)

成果物が**印刷した紙だけ**でよい (= xlsx 本体の提出が無い) とき、 [`openpyxl-destroys-drawings`](#openpyxl-destroys-drawings) の回避経路 1 (osascript) / 2 (zip 注入) より速い第 3 の経路: **雛形 xlsx を Excel 経由で PDF 化 (= drawing は render されて画像同然になる) → その PDF に fitz で値を直接印字**する。

```python
import fitz
doc = fitz.open("template.pdf")   # Excel が吐いた雛形 PDF (標題 drawing は render 済)
p = doc[0]
p.insert_text((125, 165), "〇〇学科",
              fontname="Anything", fontfile="/Library/Fonts/Arial Unicode.ttf", fontsize=9)
doc.subset_fonts()                # 必須: full embed だと 20MB 超 → subset で ~0.2MB
doc.save("filled.pdf", garbage=3, deflate=True)
```

- **座標の取り方**: `page.get_text("words")` で label 語の bbox を取り、 その右/下に置く。 `search_for()` は CJK 互換字形で空振りするので [`pdf-text-match-nfkc`](#pdf-text-match-nfkc) 必読
- ⚠️ **組み込み `fontname="japan"` を使わない**: text 層には入る (= 抽出検証は通る) のに **glyph が描画されない renderer がある** (= 数字と ASCII だけ見える紙ができる)。 必ず実フォント file (= 例: `/Library/Fonts/Arial Unicode.ttf`) を `fontfile=` で渡し、 `subset_fonts()` でサイズを潰す
- 雛形 PDF 内の `=TODAY()` 起因の `###############` は `add_redact_annot` + `apply_redactions()` で除去。 ⚠️ redact 矩形は**隣接文字の bbox に被ると巻き添え削除**する — `search_for` の返す rect を数 pt 縮めて適用
- 検証 3 点 set: ① text 抽出 (NFKC) で全値 in ② **画像で目視** (= 配置ズレ・glyph 不描画は text 検証で見えない) ③ 印刷は [`print-raster-pdf`](#print-raster-pdf) 経由 (= subset font は printer で化けることがある)

origin: 2026-06-11 謝金様式⑭-2 (= 標題 drawing 持ち雛形への prefill、 紙だけ必要な当日運用)。 openpyxl 派生の旧 file は標題消失で 1 枚無駄刷り → 本経路で 標題 + prefill 両立。

**汎用実装**: [`scripts/pdf_form_fill.py`](../scripts/pdf_form_fill.py) (= library。 anchor 印字 / NFKC 照合 / `#+` redact / font subset / 内蔵検証 / 600dpi ラスタ化 を `build_document()` 1 呼び出しに集約)。 様式ごとの driver はこれを import して item spec (anchor / dx / dy / align / text) だけ書く。 **適用境界**: 単票向け。 記入項目が多く**派生 sheet が数式導出される workbook** (= 依頼書・承諾書が sheet 1 から自動で埋まる類) は、 [`excel-osascript-cell-write`](#excel-osascript-cell-write) で雛形 copy に Excel 記入 → PDF → ページ抽出の方が速くて正しい (= 派生書類も自動で完成する。 2026-06-11 旅費請求書一式で実証)。

### <a id="print-raster-pdf"></a>加工した PDF の印刷は 600dpi ラスタ化してから (= WYSIWYG 保証)

**症状**: fitz で text 印字 + `subset_fonts()` した PDF が、 **画面プレビュー (MuPDF/Preview 系) では完全に正常なのに、 印刷すると日本語が文字化け**する (= printer 側 RIP / CUPS filter の subset font 解釈問題)。 PDF file 自体は正しいので、 **どれだけ画面で検証しても捕捉できない経路**。

**規律**: プログラムで印字・加工した PDF を印刷する時は、 **600dpi でラスタ化した画像 PDF に変換してから刷る**。 フォント処理が紙への経路から消えるので「画面で見えた見た目がそのまま出る」 が構造的に保証される:

```python
import fitz
src = fitz.open("filled.pdf"); page = src[0]
page.get_pixmap(dpi=600).save("r.png")
out = fitz.open(); np = out.new_page(width=page.rect.width, height=page.rect.height)
np.insert_image(np.rect, filename="r.png"); out.save("print_raster.pdf", deflate=True)
```

Excel / Word が直接吐いた PDF は素のままで OK (= OS 標準フォントのみで化け実績なし)。 origin: 2026-06-11 ⑭-2 完成版が Canon laser で化けた実害 (画面検証は通過していた)。

### <a id="lp-page-ranges-distrust"></a>`lp -o page-ranges` を信用しない (= 印刷は単独ページ PDF を抽出してから)

**症状**: `lp -o page-ranges=1` を指定しても **queue/driver によっては無視されて全ページ出力**される (= xlsx 由来 PDF は隠れ「マスタ」 sheet の日付リスト等で 20-30 ページあることが多く、 ゴミ数十枚が出る実害)。

**規律**: 一部ページだけ刷りたい時は、 **fitz で必要ページだけの単独 PDF を作り → `page_count` を assert → その file を丸ごと印刷**:

```python
import fitz
d = fitz.open("src.pdf"); n = fitz.open()
n.insert_pdf(d, from_page=0, to_page=0); n.save("p1.pdf")
assert fitz.open("p1.pdf").page_count == 1
```

抽出方式は全環境で正しく、 page-ranges が効く環境でも害がない → 一律 default にする。 加えて、 **視認で見つけた表示破綻 (= `###` / 文字切れ / 欄消失) は print-blocker** — 「その欄はどうせ後で手書きするから」 等の理由で**黙認して刷らない** (直すか user に確認。 黙認判断の一人歩きで破綻紙を刷った実害が origin)。 origin: 2026-06-11 Canon laser queue で page-ranges 無視 + 同日 `###` 黙認印刷。

### <a id="pdf-text-match-nfkc"></a>PDF text 照合は両辺 NFKC 正規化必須 (= CJK 互換字形の false negative)

**症状**: PDF の text 層が 「日」 を U+2F49 (康熙部首「⽇」)、 「谷」 を 「⾕」 等の**互換字形で返す**ことがあり (= フォントの cmap 由来)、 `"申請日" in text` / `page.search_for("<氏名>")` が**正常な文書に対して空振り**する。 「prefill が消えている」 「ラベルが消えた」 等の誤診断 → 不要な作り直しに直結する。

**規律**: PDF text 抽出に対する文字列照合は、 **必ず `unicodedata.normalize("NFKC", text)` してから比較**する。 `search_for()` は内部照合を正規化できないので、 互換字形を含みうる語の bbox が要る時は `get_text("words")` を取って NFKC 照合で探す。 1 度の検証で 2 回連続 false negative を踏んだ実害 (= 2026-06-11 ⑭-2、 「氏名欄・申請者欄が空」 と 2 度誤診断)。

### <a id="docx-to-pdf-pages"></a>docx → PDF: Pages.app AppleScript が macOS では最も robust

⚡ **まず [`scripts/docx-to-pdf.sh`](../scripts/docx-to-pdf.sh) を使う** (= xlsx-to-pdf.sh の docx 版、 engine 自動選択)。 `docx-to-pdf.sh [--word] <in.docx> [out.pdf]` — macOS 既定は Pages、 `--word` で Word 忠実版、 非 macOS は LibreOffice。 ⚠️ **`soffice` を直に叩かない** (= mac には未 install のことが多く「command not found」 で詰む。 2026-06-10 RCA: router を読まず soffice を試した参照漏れ)。 以下は engine 別の中身 (= スクリプトが内部で行うこと、 手組みが要るときの参照)。

**選択肢**:
1. **Pages.app** (macOS 標準、 install 済): automation としては一番安定。 ⭐ ただし出力 **layout は Word と一致しない** (= 組版し直し) → reviewer が体裁を見る正式書類では **[`docx-pdf-stale-cache`](#docx-pdf-stale-cache) の fallback 階層**を参照 (= 最終忠実版は user の Word 書き出し)
2. **Microsoft Word** AppleScript: 動くが罠多し — 変数 scope 罠 (`set theDoc to open ...` の戻り値が「変数定義されていない」 エラー) に加え **stale in-memory cache / cold-start 失敗** (= 詳細と対処は [`docx-pdf-stale-cache`](#docx-pdf-stale-cache))
3. **LibreOffice** `soffice --convert-to pdf`: 別途 install 必要、 mac では推奨しない
4. **pandoc** + xelatex: フォント設定地獄

**Pages.app 解法**:

```bash
osascript << 'OSAEOF'
tell application "Pages"
    activate
    set theDoc to open POSIX file "/path/to/form.docx"
    delay 2
    export theDoc to POSIX file "/path/to/form.pdf" as PDF
    close theDoc saving no
end tell
OSAEOF
```

- `delay 2` は docx の Pages 内 layout 完了待ち (= 表組みや長文の場合)
- `close ... saving no` で Pages に「変更を保存しますか?」 ダイアログを出させない
- 出力 PDF は Pages の組版で render される (= Word docx と layout は厳密一致しない、 form チェック☑等は正常表示される)
- ⚠️ **Pages の layout 差は「見出し/表の重なり」 として出る — docx の不具合と誤認するな**: Pages は横並びの表 (= form の値テーブルと選択肢凡例テーブルが並ぶ官製様式等) を**重ねて配置**することがある。 これは Pages の組版 artifact で **docx 側のデータは正しい**。 PDF で「見出しが重なってる/崩れてる」 を見ても **docx を直す前に (1) docx の table セル値が正しいか確認 + (2) Word で render し直す**。 Word が綺麗なら docx は正しく原因は Pages → **docx を触らない** (= renderer artifact を追って docx を壊すな。 2026-06 §研究分野の「見出し重なり」 を docx 不具合と誤認しかけた RCA、 Word render はクリーンだった)。
- **PDF の作成元を metadata で確認**: `fitz.open(pdf).metadata['creator']` が `'Pages'` なら Pages 組版 (= 体裁非忠実)、 Word 由来なら空 or Word 名。 体裁問題を見たとき「何が render したか」 + reviewer 提出版が Pages 由来でないかを、 この 1 行で判別する。

⚠️ **Pages を使う前に [`docx-pdf-stale-cache`](#docx-pdf-stale-cache) 必読**: docx→PDF は Word automation でも可だが stale / cold-start で頻繁に詰まる + Pages は layout が変わる。 最終忠実版・automation 失敗時の fallback 階層・PDF テキストでの中身検証は [`docx-pdf-stale-cache`](#docx-pdf-stale-cache) にまとめた。

### <a id="docx-pdf-stale-cache"></a>Word docx → PDF AppleScript の二大故障: stale in-memory cache + cold-start 失敗

[`docx-to-pdf-pages`](#docx-to-pdf-pages) で Word AppleScript を「動くが罠あり」 とした、 その罠の中身。 docx を反復編集しながら Word で PDF 書き出す work-loop で **2 つの故障が独立に** 起きる。 ⚠️ どちらも [`docx-checkbox-content-control`](#docx-checkbox-content-control) の「XML 宣言由来の破損」 とは別物 (= こちらは zip も XML も健全、 docx 本体は正しい)。 なお **非同期 open → delay/sleep + quit を慎重に** は AppleScript で Office app を automation する一般則で、 Excel cell 書き ([`excel-osascript-cell-write`](#excel-osascript-cell-write) の -609 回避) も同根。

#### 故障 1: stale in-memory cache (= PDF だけ古い、 docx は正しい)

**症状**: docx をディスク上で編集 → Word で PDF 書き出すと **編集前の古い内容の PDF が出る**。 docx 本体は正しい。 **「XML を grep したら該当文字列は消えているのに、 書き出した PDF にはまだ残っている」 が決定的サイン**。

**原因**: Word が**前回 open したドキュメントを in-memory に保持**し、 osascript の `active document` がそのメモリ上の旧版を export する (= ディスクの新版を読み直さない)。 quit が中途半端 (= window だけ閉じてプロセス生存) だと特に起きる。

**正しい解法 — 完全 kill → fresh open → export → PDF テキストで検証**:

```bash
pkill -x "Microsoft Word"          # ← window close では不十分、 プロセスを完全 kill
sleep 2
open "/path/to/form.docx"          # shell open (= file association)。 osascript 内 open より cold start に強い
sleep 5                            # async load 完了待ち (= cold 時は長めに)
# save as の AppleScript syntax は Word version 依存 (pdf-visual-confirm と同 caveat)。 active document を PDF 書き出し:
osascript -e 'tell application "Microsoft Word" to save as active document file name "/path/to/out.pdf" file format format PDF'
```

🔑 **検証は必ず「生成済み PDF のテキスト」 で回す** (docx でなく):

```python
import fitz
txt = "".join(p.get_text() for p in fitz.open("/path/to/out.pdf"))
assert "削除したはずの文字列" not in txt   # ← stale なら PDF にまだ残っている
assert "追記したはずの文字列" in txt
```

docx を検証して「正しい」 と確認しても、 export が stale なら PDF は古いまま。 stale を検出できるのは **PDF テキスト照合だけ** (= 削除に使った判定で docx を見るのは循環検証、 [`manual-review-required`](#manual-review-required))。

#### 故障 2: cold-start で AppleScript が active document を掴めない

**症状** (= 実エラー文字列):
- `missing valueは“save as”メッセージを認識できません` (= active document が `missing value` = ドキュメント 0 個)
- `active documentは“save as”メッセージを認識できません` / `…は“close”メッセージを認識できません`
- Word が「名称未設定」 等の**空ドキュメントを複数開いた**状態になり、 実 docx が active にならない

**原因**: Word が cold (= 起動直後 / 直前に kill した) のまま osascript を撃つと `open` が非同期で間に合わず、 active document が無い／空。 `open -a "Microsoft Word" file` の戻り値を変数に取る方式も cold 時に変数未定義系で死ぬ (= [`docx-to-pdf-pages`](#docx-to-pdf-pages) の「変数 scope 罠」 の実体)。

**正しい解法**: osascript 内で `open` せず、 **shell の `open <file>` (file association) + 長め sleep** で warm-up を保証してから export (= 故障 1 の前処理と同じ)。

⚠️ **どうしても osascript 内で open する場合** (= 複数ファイルを 1 つの `tell` で loop する等) は 2 点を守る: **(a) `POSIX file (...)` の coercion は `tell application "Microsoft Word"` ブロックの外で評価する** — tell の内側で書くと Word に誤ルートされ `…変数は定義されていません` で死ぬ (= 変数 scope 罠の別形態)。 **(b) `open` の戻り値を変数に取らず**、 `activate` → `delay 3` (warm-up) → `open f` → `delay 5` → `set d to active document` で掴む (= cold-start で open の戻り値 binding は不安定)。 ただし結局 shell `open` + 別 osascript の方が安定するので、 osascript-内 open は loop 等で已むを得ない時だけ。

#### automation が続けて失敗するときの fallback 階層 (= 最終 PDF を automation に賭けない)

⚡ **reflex — 同じ automation を何度も叩き直さない**: cold-start / stale が 2〜3 回続いたら、 同じ手順の微調整 retry をやめて即 fallback に降りる (= 「次こそ通るかも」 で何十回も Word を起動し直すのは時間の浪費、 [`image-budget-exhaustion`](#image-budget-exhaustion) の image reflex と同型)。 中身は PDF テキストで検証済みなら、 PDF 生成手段は下記のどれでもよい。

1. ⭐ **最終・忠実版は user に Word で書き出してもらう** (= File ＞ 名前を付けて保存 ＞ PDF)。 レイアウト忠実、 automation 不安定さゼロ。 reviewer が Word の体裁を見る正式書類 (= 官製様式・決裁書類) はこれが確実。
2. **Pages export ([`docx-to-pdf-pages`](#docx-to-pdf-pages)) を automation fallback に**。 動くが **layout が Word と一致しない** (= 組版し直し)。 ⚠️ よくある懸念「Pages はデータを壊す」 は **PDF 書き出し用途では誤解** — **内容は保持され、 崩れるのは体裁だけ** (= re-typeset、 文字落ちではない、 docx 本体は read-only)。 だが官製様式では体裁差が問題になるので最終版には使わない。 ⚠️ **ただし PDF 書き出し限定**: Pages で開いて **docx として保存し直すと** content control / field code / コメント等の Word 固有機能が失われうる (= [`docx-checkbox-content-control`](#docx-checkbox-content-control) の checkbox 等) → **docx round-trip には使わない**。
3. 中身の machine 検証 (= 上記 PDF テキスト照合) は automation の成否と独立 → automation が死んでも検証は止めない。

⚡ **context-first reflex — 用件が「官公署様式の visual confirm」 なら最初から Pages 不可** (= 上記 reflex の前段、 2026-06 RCA で補強): [`docx-to-pdf.sh`](#docx-to-pdf-pages) の mac default は Pages なので**無思考で叩くと文脈に反する** — 官公署様式・決裁書類は体裁が契約 → Pages の re-typeset で「見出し/表の重なり」 artifact が出る可能性 + そもそも reviewer は Word 体裁を見るので Pages 出力は提出にも目視確認にも不向き。 ① script を打つ前に「これは正式書類か?」 を 1 秒問う ② 正式書類なら `--word` を最初から付ける or fallback 1 (user の Word 書き出し / Word.app 目視) に直行 ③ docx が PW 暗号化なら automation はそもそも PW 入力 prompt にハマる → fallback 1 一択 (= [`docx-password-roundtrip-edit`](#docx-password-roundtrip-edit) からの誘導)。 origin = 2026-06 PW 暗号化 docx の visual confirm 場面で、 中身は python-docx readback + [`check-docx-integrity.py`](#docx-checkbox-content-control) で完全検証済なのに「画面で見たい」 欲求で default Pages を叩き、 cold-start を 3 回連続踏んだ後やっと fallback 1 (= 平文抽出 preview docx を Word.app open) に降りた RCA。 reflex を再活性化させたのは **「画面で見たい = PDF 化必須」 の誤等式** で、 実は user 目視確認は **Word.app で docx を直接開く方が早い** (= PDF 中継不要)。

origin: 2026-06 ある官製様式 (JST 系) の docx 修正。 docx を直しても PDF が古いまま (= stale) → quit 不十分が真因 → `pkill` + fresh open で解消。 さらに Word が cold-start で `missing value` / 空ドキュメント複数の状態に陥り automation 不能 → Pages で代替 → 最終は user の Word 書き出しに委ねた。

### <a id="word-applescript-password-open"></a>Word.app の AppleScript で PW 暗号化 docx を開く / select/find が動かない罠

PW 暗号化された docx を Word.app で開く時、 user に PW prompt を出させず AppleScript から渡せる。 visual confirm を user に頼む際の手間を 1 段減らす。

**正しい syntax** (= 2026-06 確認、 `password document` parameter):

```applescript
tell application "Microsoft Word"
    activate
    open file name "/abs/path/to/encrypted.docx" password document "<PW>"
end tell
```

- `open POSIX file "..." with password protect "..."` は **syntax error** (= Word AppleScript dictionary に無い)、 `open file name ... password document ...` が正解
- 戻り値は `document <basename>` (= success のサイン)
- 同 syntax で連続 open する場合は `activate` を 1 回でよい
- ⚠️ 当然だが PW literal を AppleScript source に書く時は **leak guard** が効く layer か確認 (= 本リポ等 public は不可、 個人層 / private repo の script や 1 回限りの shell heredoc に留める)

**select/find/特定ページへ jump は AppleScript で不安定**:

- `tell active document to select` → `active document は "select" メッセージを認識できません` (= -1708)
- `tell selection to find object` → `find object of selection は "clear formatting" メッセージを認識できません`
- Word.app の AppleScript dictionary は Find 系オブジェクトの coercion が脆く、 cold-start に弱い (= [`docx-pdf-stale-cache`](#docx-pdf-stale-cache) と同根)
- → **「特定シートだけ見せる」 用途では Find/select に頼らず [`docx-section-extract-preview`](#docx-section-extract-preview) で別 docx に抜き出す方が確実**

origin: 2026-06 ある PW 暗号化 6 シート様式の visual confirm で、 物理シートだけ見せたい → AppleScript で `tell active document to select` / `tell selection to find object` を試行 → 全 syntax で error → 関心 table のみ deepcopy で別 docx に抽出する pattern に切替で解決。

### <a id="docx-section-extract-preview"></a>機密書類の「必要なところだけ見せる」: 関心 table のみ平文 preview docx を生成して Word.app open

機密 / PW 暗号化された大型 form (= 多科目 / 多シート構成) で、 user に「自分の担当ページだけ目視確認したい」 と言われた時の確実 pattern。 [`word-applescript-password-open`](#word-applescript-password-open) の find/select が動かない代替経路。

**設計**: 関心 table を python-docx で deepcopy → **新しい平文 docx** に挿入 → preview として Word.app で open (= PW 不要)。 元の **提出用 docx は別ファイル**として PW 維持で保存 (= [`docx-password-roundtrip-edit`](#docx-password-roundtrip-edit))。 二本立てで「visual confirm = 平文 preview」 + 「提出 = 暗号化 final」 を分離。

```python
from docx import Document
from copy import deepcopy

src = Document('filled_decrypted.docx')   # 復号 + 記入済の作業 copy
new = Document()                          # 平文 / 空白テンプレ
new.add_heading('用紙X (関心領域) — preview / 平文', level=1)
new.add_paragraph('科目: 物理')             # 元 docx の前後 paragraph で「どの table か」 を user に示す
tbl_xml = deepcopy(src.tables[5]._element)  # 関心 table を deepcopy
new.element.body.append(tbl_xml)
new.save('preview_butsuri.docx')
```

**注意**:
- **preview docx は提出に使わない** (= 機密性 / 体裁 / 完全性が落ちる)。 必ず `提出用` と `preview` を明確に別名 (例: `*_記入済.docx` vs `preview_*.docx`) で保存
- preview は **平文** なので、 leak risk のある場所 (= 共有 cloud / 公開リポ) に置かない。 一時 work dir (= `/tmp/` 配下 or 元の private repo 配下) で完結させる
- Word.app で open する時は `open <file>` (shell) で十分 (= AppleScript の cold-start trap を回避)
- 既存 cell の paragraph 構造を deepcopy で持っていくので、 fill した値 (= 改行・font・spacing) も忠実に再現される

### <a id="docx-fill-xml-edit"></a>docx fill: `python-docx` で XML 直編集 (= 共通パターン)

研究費応募・申請書類で頻出する 「☐ チェックリストと placeholder の docx を fill して PDF 化」 パターン。 `python-docx` ライブラリよりも、 zipfile + `word/document.xml` の直編集が **runtime 軽量で確実**。

**typical docx form** の構造:

- ☐ (= U+2610) と ☑ (= U+2611) はテキスト文字。 単純置換可
- placeholder `＿＿＿＿＿＿` (= 全角アンダースコア繰り返し) は単一 `<w:t>...</w:t>` run に入っていることが多い
- 識別フィールド (= 氏名・所属・部署・日付) は `<w:t>氏名：＿＿＿＿＿</w:t>` のようにラベル + placeholder が同じ run、 もしくは `<w:t>氏名</w:t>` + `<w:t>：＿＿＿＿＿</w:t>` の 2 run 分割

**実装スケルトン**:

```python
import zipfile

with zipfile.ZipFile(template_docx) as z:
    files = {n: z.read(n) for n in z.namelist()}
xml = files['word/document.xml'].decode('utf-8')

# ☐ → ☑ (= 全置換、 または位置で選択置換)
# ⚠️ この素朴な文字置換が安全なのは ☐ が「プレーンテキスト」 の時だけ。
#    コンテンツコントロール checkbox (<w:sdt><w14:checkbox>) は状態同期が要る (別の実在 inconsistency) → docx-checkbox-content-control。
#    ※Word「破損」の確定真因は別物 = python-docx の XML 宣言形式 (docx-checkbox-content-control banner)
# 例: 19 個の ☐ のうち、 ある領域 (= 学生用 2 個) は ☐ 保持
boundary_start = xml.find('学生が研究代表者として応募')
boundary_end = xml.find('提出形式の確認')
out = list(xml)
for i, c in enumerate(xml):
    if c == '☐' and not (boundary_start < i < boundary_end):
        out[i] = '☑'
xml = ''.join(out)

# Placeholder 置換 (= <w:t>...</w:t> 単位)
xml = xml.replace('<w:t>＿＿＿＿＿＿＿＿＿＿＿＿</w:t>',
                  f'<w:t>{identity["name"]}</w:t>', 1)
xml = xml.replace('<w:t>所属機関：＿＿＿＿＿＿＿＿</w:t>',
                  f'<w:t>所属機関：{identity["org"]}</w:t>', 1)
# 月日: <w:t>年＿＿月＿＿日</w:t> のような複合 run
xml = xml.replace('<w:t>年＿＿月＿＿日</w:t>',
                  f'<w:t>年{month}月{day}日</w:t>', 1)

files['word/document.xml'] = xml.encode('utf-8')
with zipfile.ZipFile(dest_docx, 'w', zipfile.ZIP_DEFLATED) as z:
    for name, data in files.items():
        z.writestr(name, data)
```

**事前 dump 必須**: docx の XML 構造を必ず最初に `unzip -p form.docx word/document.xml | python3 -c "..."` で grep して確認。 placeholder が `＿` 何文字か、 ラベルと placeholder が同じ run か分かれた run かを事前に把握。

### <a id="docx-password-roundtrip-edit"></a>PW 暗号化 docx を編集して PW 維持で返す: msoffcrypto + python-docx round-trip 5 step

行政・学術・社内 配布の form が **「Word ファイルのパスワードを解除せず、 元のメールに添付返信」** を要求する場合の確実 pattern。 提出物として **PW 暗号化を維持したまま中身を書き換える** ための 5 step。

**前提**: `msoffcrypto-tool` 5.4 以降は `encrypt` mode (`-e` flag) を持つ (= 旧版は decrypt only だった)。 `pip show msoffcrypto-tool` で 5.4+ を確認。 PW は配布元 mail / 別送 mail / 関連 doc から取得 (= 本リポ等 public surface に literal を書かない)。

**5 step**:

```bash
# 1. backup + decrypt
cp form_encrypted.docx form_orig.docx          # 元 file を保全 (常に手元 backup)
msoffcrypto-tool -p "$PW" form_encrypted.docx form_decrypted.docx

# 2. python-docx で fill (= 別 file に書き出し、 decrypted は触らない)
python3 fill.py form_decrypted.docx form_filled.docx

# 3. 再暗号化 (= 同 PW で encrypt)
msoffcrypto-tool -e -p "$PW" form_filled.docx form_final.docx

# 4. roundtrip verify (= 再 decrypt → readback で内容一致 + XML 健全性)
msoffcrypto-tool -p "$PW" form_final.docx form_rt.docx
python3 -c "from docx import Document; d=Document('form_rt.docx'); ... # cell readback"
python3 ~/Claude/claude-config/scripts/check-docx-integrity.py form_rt.docx

# 5. visual confirm = user の Word.app 目視 (= [`docx-pdf-stale-cache`] の reflex 通り)。
#    関心セクションだけ抜き出した平文 preview は [`docx-section-extract-preview`]、
#    PW 付き open は [`word-applescript-password-open`]。
```

**step 2 (python-docx fill) の cell 編集 gotcha**:

- **既存 cell の paragraph 構造を温存** する: cell.text への代入は 1 paragraph に collapse して既存 formatting / 改行を壊す。 cell が複数 paragraph (= 散文 + 空行 + 散文 等) なら paragraph index で書き分ける
- **空 paragraph に文字を入れる**: `p = cell.paragraphs[i]; for r in list(p.runs): r._element.getparent().remove(r._element); p.add_run(text)` (= 既存 run を全削除 → 新 run 追加で formatting を維持)
- **新規行追加**: `cell.add_paragraph('text')` (= 既存 paragraph の後に追加)
- **複数行 cell をリセット**: 既存 paragraph を全削除 (`for p in list(cell.paragraphs): p._element.getparent().remove(p._element)`) してから `add_paragraph` × N

```python
# 例: cell に氏名 3 名を改行区切りで入れる (= 既存 paragraph リセット → 3 個追加)
cell = doc.tables[5].cell(2, 2)
for p in list(cell.paragraphs):
    p._element.getparent().remove(p._element)
cell.add_paragraph('氏名 A')
cell.add_paragraph('氏名 B')
cell.add_paragraph('氏名 C')

# 例: 既存 paragraph (= 空行プレースホルダ) の特定 index 行に文言を流す
lines = ['散文 1 行目', '散文 2 行目', '散文 3 行目']
for idx, line in enumerate(lines):
    p = cell.paragraphs[2 + idx]  # 0 = ラベル "【点検方法】"、 1 = 空、 2-4 = 記入領域
    for r in list(p.runs):
        r._element.getparent().remove(r._element)
    p.add_run(line)
```

**step 4 (verify) は print-blocker**: roundtrip readback で「自分が書いた内容と一致」 を確認し、 加えて [`check-docx-integrity.py`](#docx-checkbox-content-control) を pass させる。 暗号化済 docx は zip 直 grep が効かないため、 verify は **必ず再 decrypt 経由**。 失敗時に step 1 の `form_orig.docx` から再開できる (= backup 規律)。

**visual confirm の注意 (= 上の §[`docx-pdf-stale-cache`] context-first reflex を遵守)**:
- PW 暗号化 docx を `docx-to-pdf.sh` の mac default (= Pages) に投げると cold-start + PW prompt の両罠に当たる → 最初から不可
- 平文 [`docx-section-extract-preview`](#docx-section-extract-preview) を生成して Word.app で open する fallback 1 が確実
- final (= encrypted) を user に手渡したい時は [`word-applescript-password-open`](#word-applescript-password-open) で PW 付き open

origin: 2026-06 ある官公署様式 (= 担当者表 + 体制表 の 2 docx、 配布元から PW 別送) の記入返送。 form 構造は 6 シート (= 多科目分の table)、 自分の担当 1 シートのみ記入。 step 4 (roundtrip readback) で「点検方法の散文行が空 paragraph に流し込まれていない」 (= 私の paragraph index 取り違え) を 1 度検出 → 修正。 step 5 (visual confirm) で Pages cold-start を 3 回踏んで時間を浪費 → [`docx-pdf-stale-cache`] reflex に降りて平文抽出 preview pattern を確立。

### <a id="docx-python-docx-surgical-edit"></a>確定済 docx の外科編集: python-docx で run / 段落を直接いじる

[`docx-fill-xml-edit`](#docx-fill-xml-edit) は **template を fill** する zipfile+XML 文字列置換。 別軸として、 **既に確定・提出・承認済の docx に小修正だけ当てる** (= 校正・誤記訂正・1 段落追加) には python-docx の段落 / run API が読みやすい。

**原則 — source 再生成でなく docx を外科編集**: 承認 / 提出済の文書を generator の source から作り直すと、 **source が drift していて承認版と別物が出る**ことがある (= 出力が静かに変わり承認済の内容を壊す)。 小修正は docx 本体を直接編集する。 着手前に「この docx がその PDF の正本か」 を確認する (= docx 全文と PDF 全文を whitespace strip して一致を見る。 body 全走査は [`docx-guidance-deletion`](#docx-guidance-deletion))。

**run 単位の置換**: `insert_paragraph_before(text)` / `add_paragraph(text)` で作った散文段落は **単一 run** なので `for r in p.runs: r.text = r.text.replace(old, new)` が安全。 ⚠️ **置換前に run 構造を確認** — target が単一 run に収まっているか (複数 run に分割されていると replace が空振りする)。

**1 段落だけ狙う** (= 同じ boilerplate が複数段落にある時): その段落固有の token を併せて match し兄弟段落を巻き込まない。

```python
for p in all_paras:                                  # all_paras = body 全走査 (docx-guidance-deletion)
    if title_token in p.text and "同著者" in p.text:    # 題目 token で 1 段落だけ特定
        for r in p.runs:
            r.text = r.text.replace("同著者", correct_authors, 1)
```

**書式を保って段落を挿入** (= 見出しの直後に本文を追加): 既存本文段落を deep-copy して書式を継承し `addnext` で順序挿入する。

```python
import copy
from docx.oxml.ns import qn
ref = next(p for p in doc.paragraphs if "既存本文の特徴語" in p.text)       # 書式の手本
hdr = next(p for p in doc.paragraphs if p.text.strip().startswith("10."))  # 挿入位置 (見出し)
prev = hdr._p
for line in new_lines:
    newp = copy.deepcopy(ref._p)
    wt = newp.findall(".//" + qn("w:t"))
    wt[0].text = line; wt[0].set(qn("xml:space"), "preserve")   # ← 先頭空白を保つ
    for extra in wt[1:]: extra.text = ""
    prev.addnext(newp); prev = newp                              # 見出しの直後に順に挿入
```

⚠️ **挿入の idempotency gate は「挿入文の unique な lead 句」 で**判定する。 ゆるい substring (= 文書の別所にも在る語) で「挿入済か」 を見ると、 既存本文に誤 match して挿入を skip する (= 実際に踏んだ事故)。

**保存後**: python-docx で save したら [`docx-checkbox-content-control`](#docx-checkbox-content-control) の XML 宣言正規化を通す (auto-patch 済なら自動)。 ⚠️ **段落 / セル内容を削除する編集は空セル (段落なし `<w:tc>`) を生みうる** → save 後に `check-docx-integrity.py` ([`docx-empty-cell`](#docx-empty-cell) クラス8) を必ず通す。 PDF 化は [`docx-pdf-stale-cache`](#docx-pdf-stale-cache)、 検証は docx でなく **PDF テキスト**で回す (= 削除マーカーの不在・追記の存在を grep + 色 histogram)。 ⚠️ content 保全 verifier (= テンプレ差分照合) は **意図的に消した文字列を「欠落」 と flag する** — 想定どおりで regression ではない ([`docx-guidance-deletion`](#docx-guidance-deletion) 方向 B と同型)。

### <a id="docx-checkbox-content-control"></a>☐ チェックは「ただの文字」か「コンテンツコントロール」かを見分ける

> ⚠️ **2026-06-05 RCA 確定 (3 度の誤診の末 ground-truth で決着)**: Word「破損/開いて修復」の**確定真因は XML 宣言の形式**だった。 python-docx (lxml) が再シリアライズした OOXML パーツの宣言は `<?xml version='1.0' ... ?>` (**single-quote + LF**) になるが、 厳格な macOS Word (実証: 16.108) はこれを「このファイルは破損しています」と判定し開くたびにダイアログを出す。 Word 正規形 `<?xml version="1.0" ... ?>` (**double-quote + CRLF**) に揃えると解消 (= 実機 open で確定・内容不変)。 **fix = [`scripts/normalize-docx-decl.py`](../scripts/normalize-docx-decl.py)` FILE.docx`** (宣言のみ書換・idempotent)。 **python-docx で docx を save したら必ず通す**。 `check-docx-integrity.py` もこの single-quote 宣言を検出するよう更新済。 ⚠️ この症状は普遍でない (python-docx は通常 Word で開ける) が厳格 Word 個体で再現。 **以下の checkbox 節は「直す価値のある別の実在 inconsistency だが Word 破損の真因ではなかった」** として読む (= 当初 checkbox を真因と誤診 → ground-truth で反証 → 宣言が真因と判明)。 教訓: **決定論 check ✅ ≠ Word 受理、 最終 ground truth は実機 open** (= validator は必要条件であって十分条件でない)。
>
> **🔧 自動予防システム (恒久・推奨)**: 個別ファイルを後追いで normalize すると取りこぼす (= 2026-06-05 に filled-official だけ直して提出名 copy を取り逃し再発)。 根治は **save 時 source で clean にする**: [`scripts/docx_decl_patch.py`](../scripts/docx_decl_patch.py) が python-docx の `Document.save()` を wrap し保存のたび宣言を Word 形式へ自動正規化 (lazy import hook・content 不変・idempotent)。 [`scripts/install-docx-decl-patch.sh`](../scripts/install-docx-decl-patch.sh) (= setup.sh Step 9) が user site-packages に `.pth`+module を置き **全 python3 起動で auto-load** → 以後どの script が吐く docx も source で Word-clean (= 覚える必要なし・race-free・取りこぼし不能)。 **3 段防御**: ① 自動 patch (save 時, 主) / ② [`normalize-docx-decl.py`](../scripts/normalize-docx-decl.py) (既存 docx の後追い修正 CLI) / ③ `check-docx-integrity.py` (single-quote 宣言の検出 gate)。 ⚠️ 覆えるのは `.pth` が効く python3 (= 既定の user-site 有効な python)。 venv/別 python は ②③ で補完。

`☐ → ☑` の置換は **2 種類の ☐** で扱いが違う。 取り違えると **zip も XML も well-formed なのに Word だけが「このファイルは破損しています。 開いて修復しますか?」 を開くたびに出す** (= 2026-06-05 JST LOTUS 様式の RCA)。

| ☐ の種類 | 構造 | グリフだけ置換して良いか |
|---|---|---|
| **プレーンテキスト** | `<w:t>☐ ○○する</w:t>` のように `<w:t>` 内の素の文字 | ✅ OK (= [`docx-fill-xml-edit`](#docx-fill-xml-edit) の `xml.replace('☐','☑')` でよい) |
| **コンテンツコントロール checkbox** | `<w:sdt><w:sdtPr>…<w14:checkbox><w14:checked w14:val="0"/>…</w14:checkbox></w:sdtPr><w:sdtContent><w:r><w:t>☐</w:t>…` | ❌ **NG** — グリフだけ ☑ にすると `<w14:checked val="0">`(未チェック状態) と表示(☑)が**不整合**になり Word が破損判定 |

**症状**: 行政・学術の正式様式 (= Word で作られたテンプレ) は checkbox を **コンテンツコントロール**で実装していることが多い。 `w:t` 内の ☐ を文字置換しただけだと、 zip 整合・全 XML well-formed・関係参照 OK で構造監査を全部通過するのに Word の修復ダイアログだけが出続ける (xmllint では検出不能なスキーマ/コンテンツモデル層)。

**正しい fill** = グリフと一緒に親 `<w:sdt>` の `<w14:checked>` 状態も同期する:

```python
# python-docx で element-level に置換する場合
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
def sync_sdt_checked(tnode, val="1"):           # tnode = 該当 <w:t> element
    sdt = tnode.getparent()
    while sdt is not None and not sdt.tag.endswith('}sdt'):
        sdt = sdt.getparent()
    if sdt is not None:
        for chk in sdt.iter(f'{{{W14}}}checked'):
            chk.set(f'{{{W14}}}val', val)        # ☑ なら "1"、☐ なら "0"
# tnode.text = tnode.text.replace("☐","☑"); sync_sdt_checked(tnode, "1")
```

**出荷前 gate**: `~/Claude/claude-config/scripts/check-docx-integrity.py FILE.docx …` で checkbox 状態↔グリフ不整合 + bookmark 不均衡 + table grid 不一致 + 空 run + dangling r:id 等を **Word 不要・決定論的**に検出 (終了コード 1 で fail)。 fill pipeline の末尾に組み込むと「Word で開いて初めて破損が判明」 を防げる。

**既存の破損ファイルの確実な復旧**: Word 自身に修復させるのが bullet-proof — 修復ダイアログで「はい(開いて修復)」 → 内容が復元されて開く → そのまま保存し直すと正規の OOXML に書き直されてダイアログが消える (= 自作 pipeline 産で内容健全なら修復はロスレス)。 ⚠️ Word の「破損」判定/修復を **AppleScript で自動化するのは不安定** (= alerts-off auto-repair は復元 doc が generic 名で元パスに紐付かず save 困難、 修復ダイアログ検出も session state でブレる)。 自動検証に頼らず上記 gate (決定論) + 実機 1 回 open で確認する。

### <a id="docx-word-corruption-diagnosis"></a>Word が「破損」と言うが決定論 check は通る時の真因特定 (= 修復版との diff)

[`docx-checkbox-content-control`](#docx-checkbox-content-control)(XML 宣言)や [`docx-empty-cell`](#docx-empty-cell)(空セル)のように、 **zip も XML も well-formed・`check-docx-integrity.py` の gate も通過するのに macOS Word だけが「破損 / 開いて修復」を出す**ことがある。 Word の破損ヒューリスティックは非公開なので、 決定論 gate は **必要条件であって十分条件でない** ([`manual-review-required`](#manual-review-required))。 未知の破損モードの真因はこう特定する:

**① 壊れた版を退避 → Word に「開いて修復」させ別名保存 → diff** (= gold standard)。 Word の repair は破損トリガーだけを除去するので **repaired と broken の diff = トリガー**。 Word は computer-use で開く (or user に「開いて修復 → 別名保存」 を頼む — 「開くだけ」 の確認は自分でスクショするより user に聞く方が速い)。 ⚠️ **repair 前に broken のコピーを必ず取る** (repair で上書きされうる)。

**② Word は repair 時に全体を再シリアライズする** → 生バイト diff はノイズだらけ。 **構造的カウントで絞る**: part list / `[Content_Types]` / `<w:sdt>`・`<w:drawing>` 数 / **空セル数** / rels の Target。 broken と repaired で食い違う 1 点がトリガー。

**③ 要素カウントの delta が signature**: repaired が **段落 +N** = 空セル (Word が `<w:p>` を N 個補填 → [`docx-empty-cell`](#docx-empty-cell))。 他の delta は他トリガーを指す。

⚠️ **false-positive の罠 (実際に踏んだ)**: `etree.tostring(部分要素)` は、 その要素が使う名前空間を **毎回 `xmlns:` 付きで出力**する (fragment を standalone で well-formed にするため)。 これを「stored の `document.xml` に局所再宣言がある」 と誤読するな (2026-06-06 に「namespace 汚染が原因」 と誤診して時間を浪費)。 **局所再宣言の有無は raw stored バイトで** `<w:p xmlns` を grep して確認する (tostring した文字列でなく)。

**④ 特定したら決定論側に畳み込む**: トリガーを `check-docx-integrity.py` の新クラス + generator の予防 step に追加し、 同モードを二度と実機 open まで持ち越さない (= [`docx-empty-cell`](#docx-empty-cell) のクラス8 検出 / `ensure_cell_paragraphs` 補填はこの手順で生まれた)。

### <a id="docx-empty-cell"></a>空セル `<w:tc>`(段落なし)は Word 破損判定源 — 各セルに `<w:p>` を補う

OOXML は **全ての表セル `<w:tc>` が最低 1 つの block 要素 (`<w:p>` か `<w:tbl>`) を含むことを必須**とする。 python-docx で段落を削除したり form を fill した結果、 **段落の無い空セル** (`<w:tc><w:tcPr>…</w:tcPr></w:tc>`) が残ると、 **zip も XML も well-formed・grid 整合・宣言 double-quote・[`docx-checkbox-content-control`](#docx-checkbox-content-control) の出荷前 gate を全部通過するのに、 macOS Word だけが「このファイルは破損しています」** を開くたびに出す。 Word の「開いて修復」は各空セルに `<w:p>` を補って直す (= **段落数が +N される**のが決定的サイン)。

⚠️ **決定論 check の盲点だった** (2026-06-06 RCA): 宣言・bookmark・grid・空 run・dangling r:id は検査していたが **空セルは未検出**。 well-formed parse も通るため、 **Word の「開いて修復」版との diff で初めて「Word が +N 段落を空セルに補った」** と判明した = 真因。 [`manual-review-required`](#manual-review-required) の「決定論 ✅ ≠ Word 受理、 最終 ground truth は実機 open」 の生きた実例 (= 決定論チェッカに新検査を足して塞いだ)。

**検出 (決定論)**: `check-docx-integrity.py` クラス 8 — `<w:tc>` 直後が (tcPr のみ挟んで) `</w:tc>` の空セルを flag。

**fix (補填)**: 各空セルに最小の `<w:p>` を append する。 generator は save 直前に必ず通す。

```python
from docx.oxml.ns import qn
def ensure_cell_paragraphs(doc):
    n = 0
    for tc in doc.element.body.iter(qn('w:tc')):
        if not tc.findall(qn('w:p')) and not tc.findall(qn('w:tbl')):
            tc.append(tc.makeelement(qn('w:p'), {})); n += 1   # tcPr の後ろに空段落を補う
    return n
```

既存の破損ファイルは Word の「開いて修復」→上書き保存でも直る ([`docx-checkbox-content-control`](#docx-checkbox-content-control) の「既存破損の確実な復旧」)。 ただし repair 版は Word が全体を再シリアライズするので、 **編集途中なら ↑ の補填で直す方が edit を保てる**。

### <a id="docx-guidance-deletion"></a>docx form から記入要領 / ガイダンスを削除する: 構造は残す + content-control を見逃さない + 双方向検証

官製様式の docx を提出前に「記入要領 (= 各欄の評価基準・※注記・記入例) を削除」 する作業の落とし穴。 **「削除しすぎ」 と「削除し漏れ」 を同時に踏みやすい**。

**(1) 何を消し何を残すか — 境界**:
- **削除する = ガイダンス**: 各項目の評価基準 (「以下の観点から評価」 「Evaluation will be based…」)、 ※注記 (字数・ページ上限・記入例・「青字は提出時に削除」)、 予算欄の ※説明文。
- **残す = 様式構造**: フォームの識別見出し (= 「○○専用様式」)、 各 § 見出し【…】、 表ラベル。
- ⚠️ よくある両側エラー: 上部の**様式見出しブロックごと消す** (= 削除しすぎ) / 見出しは残すが**※注記を残す** (= 削除し漏れ)。 「見出しは残し、 ※注記だけ消す」 が正解。

**(2) 削除対象を grep するとき content-control / table / textbox を見逃さない**:

python-docx の `doc.paragraphs` は **本文段落しか拾わず**、 **表セル・テキストボックス・content control (`<w:sdt>`) 内のテキストを取りこぼす**。 官製様式はガイダンスを content control や表セルに埋めることが多く、 「`doc.paragraphs` で grep して 0 件 → 消えた」 が嘘になる (= 別 variant が content control 内に残存)。 body 全体の `<w:p>` を走査する:

```python
from docx.oxml.ns import qn
def all_paragraph_texts(doc):
    # body 全体を走査 = 表セル・textbox・content control 内の <w:p> も拾う
    return ["".join(t.text or "" for t in p.iter(qn('w:t')))
            for p in doc.element.body.iter(qn('w:p'))]
```

**(3) 双方向検証を template を oracle にして PDF テキストで回す** (= 「✓ 全消し」 を自分の削除判定で言わない):
- **方向 A (削除し漏れ 0)**: 空テンプレに在るガイダンス文字列が、 提出版の **PDF テキスト**に 1 件も残っていない。 ⚠️ 削除に使った predicate で検証すると、 predicate が取りこぼした variant (= 複数形・※無しの項目名ガイダンス等) は検証も取りこぼす (= 循環、 [`manual-review-required`](#manual-review-required))。 **テンプレ由来の精密な署名文字列**で照合する。
- **方向 B (削除しすぎ 0)**: 自分が記入した内容 (= 残すべき本文) が PDF テキストに全保全。 折返しに強いよう distinctive な chunk で照合。
- 照合先が **docx でなく PDF テキスト**なのは [`docx-pdf-stale-cache`](#docx-pdf-stale-cache) の stale を貫通するため。

**(4) ガイダンスが「色」 で区別される様式 (= 青字=提出時削除) は、 色そのものを ground truth にする**:

官製様式は記入要領を **青字 (典型 `0070C0`)** で刷り「青字は提出時に削除」 と指示することが多い。 この削除を色で機械化するとき 2 つの落とし穴があり、 **両方を踏むと strip も検証も pass するのに青字が残る** (= 2026-06 JST 系様式の §予算記入要領 10 段落残存 RCA、 user が rendered 色を目視して発覚)。

- **落とし穴 a — 色は run 直接色とは限らず段落/文字 style 継承で来る**: python-docx の `run.font.color.rgb` は **直接 run 色しか見ず style 継承色には `None` を返す**。 §予算記入要領などは段落 style (例 `a0`) が `0070C0` を定義し run に `w:color` が無い → run 色だけ見る strip / 検証は **その青字を丸ごと素通し**する。 effective color を **run 直接色 → `rStyle` → `pStyle` の style 色** の順で解決する:

```python
from docx.oxml.ns import qn
BLUE = '0070C0'
def style_color_map(doc):                  # styleId -> 直接定義色
    m = {}
    for st in doc.styles.element.iter(qn('w:style')):
        rpr = st.find(qn('w:rPr')); c = rpr.find(qn('w:color')) if rpr is not None else None
        m[st.get(qn('w:styleId'))] = c.get(qn('w:val')) if c is not None else None
    return m
def eff_color(r, pstyle, smap):            # r=<w:r>, pstyle=段落の pStyle val
    rpr = r.find(qn('w:rPr'))
    if rpr is not None:
        c = rpr.find(qn('w:color'))
        if c is not None and c.get(qn('w:val')) not in (None, 'auto'): return c.get(qn('w:val'))
        rs = rpr.find(qn('w:rStyle'))
        if rs is not None and smap.get(rs.get(qn('w:val'))) == BLUE: return BLUE
    return smap.get(pstyle)                 # ← style 継承色。 ここを見落とすと青字が残る
```
  strip 方針: 全 run が effective 青の段落は**段落ごと削除**、 混在段落は青 run を黒 (`w:color val="auto"`) に **recolor** (= 削除でなく recolor = 重複見出し等の layout 破壊を回避)。

- **落とし穴 b — phrase 照合 ((3) 方向 A) は list に無い文言を見逃す**: テンプレ署名文字列での照合は **list に登録していないガイダンスを素通し**する (= list-based audit の implicit-scope 盲点)。 「色」 という意味属性は **属性そのもの = rendered 色で検証**するのが漏れない。 提出版 PDF の非黒 text span を 0 件要求する:

```python
import fitz   # PDF render の span 色は style 継承も解決済 (= Word が描いた最終色) → 落とし穴 a・b を 1 check で塞ぐ
blue = [s['text'] for pg in fitz.open(pdf) for b in pg.get_text('dict')['blocks']
        for l in b.get('lines', []) for s in l.get('spans', []) if s['color'] not in (0, None) and s['text'].strip()]
assert not blue, f"色付きガイダンス残存: {blue[:3]}"
```
  **一般則**: 色・構造など「意味を持つ属性」 の検証は、 **その属性自体を ground truth にする** (= proxy の phrase list や docx run 属性で代用しない)。 proxy 検証は proxy の盲点 (= list 外 / style 継承) をそのまま検証の盲点にする。

origin: 2026-06 官製様式 docx の記入要領削除。 (a) 上部様式見出しブロックを過剰削除 → 復元、 (b) ※注記を削除し漏れ、 (c) `doc.paragraphs` 走査で content control 内の variant を取りこぼし「全消し」 と誤宣言、 (d) 青字記入要領を **run 直接色だけ見て strip** → 段落 style 継承の青字 (`a0`) を素通し + phrase 検証も list 外で pass → user が rendered 色を目視して発覚、 を反復。 テンプレ基準 + PDF テキスト + **PDF span 色** の検証で決着。

### <a id="erad-forbidden-chars"></a>e-Rad の使用禁止文字 (= 入力フィールド charset 制限)

e-Rad の long-textarea フィールド (= 研究目的・研究概要・経費根拠・役割分担等) は厳格な charset を強制。 以下は **エラーで弾かれる**:

| 禁止文字 | 例 | 置換 |
|---|---|---|
| 上付き・下付き数字 | `H₀` (U+2080) | `H_0` (= ASCII underscore + 数字) |
| ギリシャ文字 | `σ` `α` `μ` `β` | カタカナ「シグマ」「アルファ」「ミュー」 |
| 数学記号 | `×` (multiplication U+00D7) | `と` or `に` |
| 不等号系 | `≦` `≧` `≠` `→` | カタカナや日本語 |
| セクション記号 | `§` (U+00A7) | `第〜節` or `〜節` |
| エム・ダッシュ | `—` (U+2014) | `、` or ASCII `-` |
| 丸付き数字 | `①②③` | `(1)(2)(3)` 半角括弧 |
| ローマ数字 | `Ⅰ Ⅱ Ⅲ` | `I II III` (= ASCII) |
| 機種依存文字 | `㈱ ㈲` | `(株) (有)` |

xlsx 内部 (= 審査員が読む書類) は制限なし (= ギリシャ文字 / 下付き OK)。 制限は **e-Rad の textarea 経由でのみ**。 応募書類の draft 段階で禁止文字を排除しておくと、 xlsx と e-Rad textarea で writing convention の二重 maintenance が不要。

> 本節は**様式 fill 視点の禁止文字リスト（正本）**。 e-Rad 提出フロー全体（応募情報ファイル添付・研究分野の二系統・予算の年度配分・相違点欄・機関承認フロー・英語課題名の半角 ASCII 化）は [erad-submission.md](erad-submission.md) を参照。

### <a id="signature-not-stamp"></a>「署名」 要求は手書き署名 or 電子署名、 認印画像では不可

行政・学術 様式 (= 助成金応募同意確認書、 推薦書、 法的同意書等) で「**署名 又は 電子署名**」 「**本人が署名**」 と明記された欄に、 認印 (= 朱印 PNG) を貼っても reject される。 「電子署名 (e-signature)」 が広義に「電子的に署名処理されたもの」 と解釈されるため認印画像で代替できそうに見えるが、 実務上 reviewer は **手書き署名 (= scan された自筆画像) または 電子署名 cert 付き PDF** を期待する。

**対処**: 自筆署名 (= 紙に署名 → scan or タブレット → 透過 PNG) を準備して docx 氏名欄に挿入:

```python
from docx.shared import Inches
for p in doc.paragraphs:
    if p.text.startswith('氏名') and ('<surname>' in p.text or '＿' in p.text):
        p.add_run('  ')  # spacer
        p.add_run().add_picture(str(SIGNATURE_PNG), width=Inches(1.8))
        break
```

幅 1.8 inch (= ~4.5 cm) が標準的な「署名らしい」 サイズ。 0.5 inch だと縮小されすぎて読めない。

**認印 (= 朱印) との使い分け**:
- 「印 / 印鑑 / 認印」 が要求 → hanko PNG (= 朱印) で可
- 「署名 / 電子署名 / 本人署名」 が要求 → **signature PNG (= 手書き) 必須**

個人 user は事前に両方準備しておく (= 個人層 layer に置く)。

origin: 2026-05-14 JST SPReAD 様式 0 + 様式 2 の氏名欄、 当初 hanko を挿入 → 「電子署名必要」 と事務担当者から電話指摘 → signature PNG に差替えて再提出。

### <a id="physical-seal-required"></a>紙原本要求の窓口では貼付電子印影は印刷しても拒否される (= 実押印が確実)

[`signature-not-stamp`](#signature-not-stamp) の「認印要求 → hanko PNG で可」 は **電子提出 / 電子印影が許される窓口に限る**。 「紙原本に押印して提出」 を求める事務窓口では、 xlsx/docx に画像で貼った認印 (= 朱印 PNG) を PDF 化・印刷しても **「電子的に貼った印影」 と見破られて差し戻される** ことがある (= 印刷された朱色は網点・エッジが本物の朱肉押印と異なり、 印影を見慣れた窓口は判別する)。

- **正攻法 = 実押印**: 印影欄は**空のまま印刷** → 紙に**実物の印を朱肉 / シャチハタで押す** (= 物理押印)。 最も確実でルール準拠、 かつスキャン加工より速い。
- **NG = 偽装**: 貼付電子印影をスキャン画像等で「本物らしく」 見せる路線は、 見破られると「偽装」 と取られ事務との信頼を損なう → 避ける。 電子提出が許される窓口でのみ「本物の朱肉押印を高解像度スキャン」 が正当な代替。
- **生成時の reflex**: 様式を openpyxl 等で生成するとき、 押印欄に印影画像を埋め込まず**空で出力**し、 印刷後の物理押印を前提にする (= そういう窓口は [`pdf-snapshot-xlsx-submission`](#pdf-snapshot-xlsx-submission) の通り提出本体も紙原本を要求しがち)。

origin: 2026-06 ある学内事務窓口で、 出張様式に貼り付けた電子印影を印刷提出 → 「印刷された印影は不可、 紙に実押印を」 と差戻し。 同窓口は謝金様式でも「ハンコ画像貼付は不可、 紙に朱肉 / シャチハタ捺印した原本を」 と一貫 (= 署名だけでなく **認印も電子貼付不可** の窓口が存在)。

### <a id="placeholder-trailing-underscore"></a>docx template の placeholder 末尾装飾 underscore の cleanup

**症状**: docx form template の placeholder (= `氏名：＿＿＿＿＿＿＿＿＿＿＿＿＿`) を python-docx 経由で置換 (例: 12 個の `＿` を name に) しても、 **末尾に 1〜2 個の trailing underscore run** が残る。 結果: `氏名: <提出者氏名>＿` のように半端な `＿` が残って見栄え悪化。

**原因**: 雛形が「装飾用 placeholder = 12 個」 + 「trailing 装飾 = 別 run の 1〜2 個」 で構成されている。 単純な `xml.replace('<w:t>＿＿＿＿＿＿＿＿＿＿＿＿</w:t>', f'<w:t>{name}</w:t>')` では 12 個 run しか置換されず、 trailing run が残る。 XML 上では:

```xml
<w:r><w:t>氏名：</w:t></w:r>
<w:r><w:t>＿＿＿＿＿＿＿＿＿＿＿＿</w:t></w:r>   ← 置換対象 (12 個)
<w:r><w:t>＿</w:t></w:r>                            ← 残る (装飾 trailing、 1 個)
```

**対処**: placeholder 置換後、 trailing run を別途除去:

```python
xml = xml.replace('<w:t>＿</w:t>', '<w:t></w:t>', 1)        # trailing 全角 1 個 (= 氏名後)
xml = xml.replace('<w:t>__</w:t>', '<w:t></w:t>')           # trailing 半角 2 個 (= 所属/部署後、 計 2 箇所、 全削除)
```

各 form template ごとに trailing pattern が違うので、 dump で全 `<w:t>` を出力して目視確認後に置換 pattern を確定。

origin: 2026-05-14 JST SPReAD 様式 0 で発覚 (= 「氏名: <提出者氏名>＿」 という末尾装飾 _ が user 視覚に悪い印象を与えると指摘) → 上記 cleanup を fill_forms に追加。 様式 2 は trailing 装飾を持たない雛形だったため変更不要。

### <a id="docx-pdf-page-compress"></a>docx → PDF の page count 圧縮 (= 余白縮小 + 行間 + 末尾空段落削除)

事務指定で「1 ページ / 2 ページに収める」 が要件の docx (= チェックリスト・同意書) は、 default レイアウト (= margin 0.5 inch、 line_spacing 1.0、 末尾空段落多数) のままだと自動的に複数ページに割れる。

**python-docx で行う 3 段階圧縮**:

```python
from docx.shared import Inches, Pt

# 1. Margin 縮小
for sec in doc.sections:
    sec.top_margin = Inches(0.3)
    sec.bottom_margin = Inches(0.3)
    sec.left_margin = Inches(0.4)
    sec.right_margin = Inches(0.4)

# 2. Line spacing 0.9 + 空段落の上下 spacing 削除
for p in doc.paragraphs:
    pf = p.paragraph_format
    pf.line_spacing = 0.9
    if not p.text.strip():
        pf.space_after = Pt(0)
        pf.space_before = Pt(0)

# 3. 末尾の連続空段落を削除 (= page break trigger の主因)
while doc.paragraphs and not doc.paragraphs[-1].text.strip():
    p = doc.paragraphs[-1]
    p._element.getparent().remove(p._element)
```

経験値:
- margin 0.5 → 0.3 inch で ~22pt (= 0.3 inch = ~22pt) ずつ vertical space 増加 (= 上下計 ~44pt)
- line_spacing 1.0 → 0.9 で 30 行に対し ~30pt 短縮 (= 1pt × 10% × 30)
- 末尾空段落 3 個 削除で ~36pt 短縮 (= 12pt × 3)
- 計 ~110pt 圧縮 → 2 page → 1 page を実現可能

これでも収まらない場合は font_size を 10pt → 9.5pt に下げる (但し可読性低下)。

origin: 2026-05-14 JST SPReAD で 様式 0 = 2 → 1 page、 様式 2 = 3 → 2 page を上記 3 段階で達成。

---

## <a id="tts-review"></a>提案書を音声で確認 (macOS `say` で TTS)

長文 (= 6 セクション数千字) を視覚読みで疲れた時、 macOS 標準の `say` で TTS して耳で確認。

```bash
say -v "Kyoko (Enhanced)" -r 200 "本研究の目的は..."
```

- 日本語音声: `Kyoko` (女性) / `Otoya` (男性)、 各 Enhanced 版が高音質
- `-r 200` は WPM (Words Per Minute)、 200 が読み上げに自然なペース
- 長文を sections で区切って速報生成: `bash` script で `say` を順次呼ぶと中断 (`killall say`) しやすい
- 数式記号や英略語 (LLM、 H₀、 EJP-C 等) は読みづらいので script で読みやすく書き換え (例: `H₀` → `エイチゼロ`)

提案書 self-review 用途では、 自分で書いた文章の「不自然な日本語」 が聞いて初めてバレることが多い。

---

## <a id="common-discipline"></a>共通の規律

### <a id="dump-cell-structure-first"></a>xlsx 内部の cell 構造を **常に最初に dump** する

書き込む前に必ず構造 (= cell + alignment + merged + validation) を dump して把握する (= 推測で `B6` に書いたら実際は `B6:I6` merged で input は `B6` だけ、 等を防ぐ)。 **method・dump コードは [`form-dump-first`](#form-dump-first) が正本** (= 本 common-discipline はこの規律への index で、 ここでは再掲しない)。

### <a id="char-limit-formula-check"></a>字数制限は cell 末尾の formula で常時確認

form template が `=LEN(A3)` のような counter cell を持っていることが多い。 fill 後に該当 cell の値を読んで `0 < count <= limit` を assertion する pipeline にする。

### <a id="visual-check-by-user"></a>user 視覚確認は computer-use ではなく user に依頼

GUI 確認は MCP round-trip より user の直接視認が **常に速い**ので、 xlsx の render 視覚確認は computer-use で自動化せず user に依頼する (= Claude は xlsx の render を直接観察できない、 [`claude-cannot-observe-render`](#claude-cannot-observe-render))。

---

## <a id="label-vs-input-antipattern"></a>**label vs input row anti-pattern** (= 様式 改変 の主因)

行政・学術 様式 xlsx の頻発バグ。 **記入前に必ず読む**。 ⚠️ 様式改変の主因はもう 1 系統ある: **openpyxl の save が既存 textbox/shape を破壊** ([`openpyxl-destroys-drawings`](#openpyxl-destroys-drawings))。 label 上書き (本節) と併せて様式改変の二大主因。

### <a id="label-input-structure"></a>構造

日本の公的 様式 xlsx は section ごとに以下の 2 行 pair で組まれる:

```
Row N:    "<セクション名>の必要性" / "<セクション名>の明細"   ← pre-printed LABEL
Row N+1:  (空白、 列方向に merged)                        ← 記入位置
```

例 (= 2026-05 JST SPReAD 様式 1 研究計画調書 Sheet 3):

| 行 | 内容 | role |
|---|---|---|
| 9  | "総計" | label |
| **10** | **"設備備品費、消耗品費の必要性"** | **label (pre-printed)** |
| 11 | (empty, A11:G11 merged) | **input — 記入はここ** |
| 18 | "謝金、旅費の必要性" | label |
| 19 | (empty) | input |
| 28 | "その他の必要性" | label |
| 29 | (empty) | input |

### <a id="label-overwrite-bug"></a>典型バグ (= 様式改変)

label cell に narrative を直接書き込んでしまう (= overwriting the pre-printed label)。

**原因 (= reflexive form-fill)**:
- label テキストが「section title なので、 ここに content を書け」 と読めてしまう
- 真の入力行 (N+1) は empty に見えて「未使用 cell」 と誤解する
- Excel は label vs input を視覚的に区別する style 付けをしない (= 同じ font、 同じ border)
- merged input cell が大きく開いていても「装飾の空き」 にしか見えない

**実害**:
- 提出後に審査機関 (= 大学事務等) から 「**①様式の改変**」 として差戻し
- ファイル単位の reject や再提出処理コスト
- 2026-05-13 JST SPReAD で 提出者が同 pattern で 3 箇所 (= Sheet 3 行 10/18/28) で発生、 所属機関の事務担当者から指摘で発覚。 提出者申告では prior form fill でも同 pattern を起こしていた (= 再発 pattern)

### <a id="diff-form-xlsx-detection"></a>機械的検出: `diff-form-xlsx.py`

`claude-config/scripts/diff-form-xlsx.py` で雛形と提出版を全 cell diff し、 label 上書きを検出。

```bash
python3 ~/Claude/claude-config/scripts/diff-form-xlsx.py \
    /path/to/filled.xlsx \
    /path/to/template.xlsx
```

- **`LABEL_OVERWRITE`** (= critical): 雛形に「〜の必要性 / 〜の明細 / 〜について」 等の label-like text があり、 提出版がそれを別 text で上書き
- **`LABEL_DELETED`** (= critical): label が空になっている
- **`INPUT_FILLED`** (= info): 雛形 empty → 提出版 fill (= 正常)
- **`VALUE_CHANGED`** (= info): その他の変更 (= placeholder 置換等)

critical 検出時は exit code 1。 提出前 / commit 前に必ず実行する pipeline にする。

label 判定は heuristic で suffix 一致 (= `の必要性 / の明細 / について / の内容 / の確認 / の有無 / の状況`)。 新しい雛形で別 suffix が現れたら script の `LABEL_SUFFIXES` に追記する。

⚠️ **盲点: 比較基準のテンプレ自身が記入済みだと、 残骸が見えない**。 diff は「両 file で違う cell」 しか出さないので、 **テンプレに他人の記入値が残っている場合、 自分が触らなかった cell の残骸は filled 側にもそのまま在って diff に現れない** (= 他人の氏名・金額が新規書類に混入したまま全検証 pass する)。 → テンプレを使う前に [`template-provenance-check`](#template-provenance-check) で素性を確認するのが上流対策。

### <a id="template-provenance-check"></a>テンプレの素性確認 (= 「最新様式」 が誰かの記入済み修正版である罠)

**症状**: 「最新様式」 としてリポに保存された xlsx が、 実は**事務が個別案件への修正指示として返した記入済み file** (= 黄色 cell + コメント + 他人の氏名・日付・金額入り) で、 それを base に新規書類を作ると他人のデータ・修正指示 artifact が混入する。 逆 pattern も起きる: 「上書き済」 と doc に書かれたテンプレが**実際は旧版のまま** (= 新様式で追加された行が無い) で、 そこから作った書類が差戻し対象になる。

**Why 起きるか (= 考え方)**: 事務はブランクの新様式を配布するとは限らない — **様式更新が「個別案件の修正版」 という形でしか存在しない**ことがある (= 新構造を持つ唯一の file が誰かの記入済み)。 また「テンプレを最新版で上書きした」 という doc 記述は、 実 file の検証なしには信用できない (= doc と file の drift)。

**Reflex (= テンプレを base にする前の 3 確認)**:
1. **全 sheet を dump して個人データ走査** (= 氏名・日付・金額・所属らしき値が label 以外にあれば、 それは filled form でありブランクテンプレではない)。 対象 sheet を絞らない — 多 sheet 様式は別 sheet に残骸が居る。
2. **新様式で追加されたはずの行・欄が実在するか**を確認 (= 様式更新の announce に「追加した」 と書かれた欄を grep。 無ければテンプレが旧版)。
3. **黄色 fill / コメント / 修正指示 artifact** の残存走査 ([`clear-yellow-fill-marks`](#clear-yellow-fill-marks))。

**記入済み file からブランクテンプレを作る手順**: 個人データ cell を特定 (= dump で値 cell を列挙し、 label・記入例 placeholder 〔「〇〇大学」 等〕・全案件共通の定数 〔申請者・予算番号等〕 を除いた残り) → **Excel osascript で空文字に** (= 標題 drawing がある様式で openpyxl は不可 [`openpyxl-destroys-drawings`](#openpyxl-destroys-drawings)) → 黄色 fill 解除 → 検証 (= 再 dump + drawing 数 + 黄色走査) → テンプレとして保存 + **素性 (= どの file からいつ作ったか) を doc に記録**。

origin: 2026-06-12 様式⑭-1。 「6/2 版で上書き済」 と記述されたテンプレが実は旧版 (= 新設の交通費起点住所行なし) で、 そこから作った別件書類が旧様式製になった + 真の新様式は個別案件の記入済み修正版にしか存在しなかった (= 上記手順でブランク化して解決)。 diff-form-xlsx をその記入済み file 基準で回しても残骸は不可視だった (= 上記盲点の実例)。

### <a id="fill-prevention-workflow"></a>予防 workflow (= 規律)

1. **[`form-dump-first`](#form-dump-first) dump で template の構造を **必ず** 最初に把握** (= label 行 と input 行 を **目視で特定** 後に fill code 書く)
2. fill code 内で **label 行に対する write は禁止**。 input 行 (= N+1) にのみ write (= narrative を label に書かない)。 ⚠️ **例外**: 選択肢 label が並び input 行が無い form の選択マークは [`choice-label-marking`](#choice-label-marking) 参照 — label 文字を**破壊しなければ**○前置きで可 (= 禁止の本体は「label 文字の消失」 であって「label cell に一切触らない」 ではない)
3. **fill 後に `diff-form-xlsx.py` を実行** して mechanical 検証 (= 人間目視が missed cell を catch)
4. critical 検出時は、 label を template から restore + narrative を N+1 行に move

### <a id="embedded-instruction-in-label"></a>label 内 embedded instruction の見落とし防止

label cell には input cell に対する **embedded instruction** が書かれていることがある。 例 (= JST SPReAD 様式 1 から):

- 「研究業績等\n※ ... **著者（本人に下線）**...」 → input cell で本人氏名を rich text underline 必須
- 「研究目的(日本語：**80 文字以上 400 文字以内**)」 → input cell で字数制限を守る
- 「e-Rad 研究者番号 (**8 桁の半角数字**)」 → input cell は半角数字 8 桁
- 「氏名 ※姓と名は **全角で 1 スペース空ける**」 → 全角空白挿入

これらは label 全文を読まないと拾えない (= 多くは ※ marker 以降の長い注記内)、 短い label 部分だけで input cell を fill すると見落とす。

**機械的検出**: `claude-config/scripts/scan-form-instructions.py <xlsx>` で xlsx 全 cell から instruction keyword を抽出し category 別 (= format / charset / limit / structure / attachment / auth) に group 表示:

```bash
python3 ~/Claude/claude-config/scripts/scan-form-instructions.py /path/to/form.xlsx
```

検出 keyword 例:
- format: 「下線」 / 「本人に下線」 / 「太字」 / 「斜体」 → rich text 適用必要
- charset: 「半角数字」 / 「半角英数字」 / 「全角」 → 文字種チェック
- limit: 「字以内」 / 「字程度」 / 「最大」 → 字数 / 件数チェック
- structure: 「改行」 / 「箇条書き」 → 構造化
- attachment: 「別紙」 / 「別添」 → 別ファイル提出
- auth: 「署名」 / 「電子署名」 / 「印鑑」 / 「認印」 → 認証要素

**運用**: 提出前に scan を回し、 各 instruction が input cell に反映されているかを user/Claude が手動 verify。 keyword 検出は informational (= critical/non-critical 判定なし、 exit 0)。

origin: 2026-05-14 JST SPReAD で「本人氏名に下線」 (= 様式 1 Sheet 2 A14 ラベル内) を見落として複数回再提出。 A14 ラベル全文 (= 80 字 truncate せず) を読んでいれば検出できた典型例。

### <a id="label-detection-at-dump"></a>dump 段階での label 識別

[`form-dump-first`](#form-dump-first) の `dump_form.py` 出力時、 各 cell が label か input かを mark するヘルパ:

```python
# dump_form.py の cell loop 内に追加
label_marker = " [LABEL?]" if isinstance(c.value, str) and any(
    c.value.strip().endswith(s) for s in ("の必要性", "の明細", "について", "の内容", "の確認")
) else ""
print(f"  {c.coordinate} (...): {v}{label_marker}")
```

dump 時点で label が浮き上がる → fill 対象から自動的に除外する判断が容易になる。

### <a id="choice-label-marking"></a>選択肢ラベルの選択マーク (= 専用 input cell がない選択)

[`label-input-structure`](#label-input-structure) の「label 行 + 空 input 行」 とは**別構造**として、 **複数の選択肢が pre-printed label として並び、 選択用の専用 cell が無い** form がある (= 例: 旅費様式の支給方法欄 `本学教員立替` / `出張者立替` が merged label cell のみで checkbox 列を持たない)。 この選択をどう mark するか:

- ⭕ **OK = ラベル文字を保持してマークを前置き**: `cell = "○" + 元ラベル` (例: `"○出張者立替"`)。 元の label text が substring として残るので「項目が消えた」 改変にならない。
- 🚫 **NG = ラベル文字を mark で置換 (= 破壊)**: `cell = "☑"` 単体で `"出張者立替"` を消す → 審査機関から「項目が消えた / 様式の改変」 で差戻し (= [`label-overwrite-bug`](#label-overwrite-bug) と同じ harm)。
- **境界線は「破壊か保持か」**。 「label cell に一切触るな」 ではない (= prohibition を過度一般化すると有効な選択マークまで禁じてしまう)。 harm の本体は **pre-printed text の消失**であって「cell に触ること」 ではない。
- **対比**: 専用の `☐` checkbox cell を持つ form (= 教育職員用様式等) は `☐ → ☑` の toggle で mark する (= input cell があるので [`label-input-structure`](#label-input-structure) 通り)。 ○前置きは checkbox cell が無い form 限定の手段。
- **機械検証の補助**: ○前置きなら filled value が template label を **substring として含む**。 含まない短い mark (= `☑` 単体) への置換は [`label-overwrite-detection-limit`](#label-overwrite-detection-limit) の検出漏れ pattern に該当 → `diff-form-xlsx.py` の `VALUE_CHANGED` を [`manual-review-required`](#manual-review-required) 通り逐一 expose し「label を mark で潰していないか」 を手 review。
- ⚠️ 審査機関が「印刷済み cell への文字追加」 自体を改変とみなす可能性は form/機関依存で未確定。 厳格なら fill 段階では label を素のまま残し、 **印刷後に手書き○囲み** (= デジタル無改変) に切替。

origin: 2026-06 学外者旅費様式 (`3_…`) 支給方法選択。 前 session が `☑` で label を上書き → 審査機関差戻し → ○前置き (= label 保持) に修正。

### <a id="multi-sheet-formula-propagation"></a>multi-sheet form の数式伝播 + literal の帰属区別

出張者の属性 (所属 / 職名 / 氏名) を**主 sheet に書き、 従 sheet が `=主sheet!セル` の数式で参照**する form がある (= 学外者旅費様式の 依頼書 / 承諾書 / 報告書 が請求書 sheet を参照)。

- **fix は主 sheet の source cell のみ**で足りる (= 従 sheet は数式で自動伝播)。 各 sheet を個別に手入力すると二重管理 + 不整合の元。
- 同じ文字列が複数 sheet に literal で現れても **帰属が違うことがある** (= 出張者本人の所属 vs 依頼者/所属機関の名称)。 全件一括置換せず、 [`form-dump-first`](#form-dump-first) dump で「どの cell が誰の属性か」 を特定してから直す。
- free-text cell で審査機関が表記を**直接指定**してきたら、 form の `マスタ` / 記載例の略語より **審査機関の指定をそのまま使う** (= form 内蔵の例示語に寄せない)。

### <a id="clear-yellow-fill-marks"></a>事務が黄色マークした入力 cell は fill 後に「白に戻す」 (= 黄色残置 = 様式改変扱い)

事務 (= 教研支援課 等) が修正版様式を返すとき、 **記入してほしい cell を黄色 fill でマーク + コメント**して送ることがある。 指示は典型的に「黄色セルに追記 → **セルを白に戻して** → 押印 → 提出」。 値を入れただけで黄色を残すと「標題等が黄色のまま = 様式の改変」 扱いになりうる (= [`label-overwrite-bug`](#label-overwrite-bug) の label overwrite とは別経路の 改変リスク)。

- **fill 後に該当 cell の fill をクリア**する: `cell.fill = PatternFill(fill_type=None)` (= openpyxl、 merged は top-left cell に set)。
- ⚠️ **file が標題 drawing を持つ場合は openpyxl 法は使えない** ([`openpyxl-destroys-drawings`](#openpyxl-destroys-drawings) = fill クリアのための save で標題が消える)。 **Excel osascript で解除**する:
  ```applescript
  repeat with addr in {"G13", "Q13", "D19"}
    set color index of (interior object of range (contents of addr) of ws) to color index none
  end repeat
  ```
  (= `contents of addr` が list 要素の dereference に必須。 起動・保存の枠組は [`excel-osascript-cell-write`](#excel-osascript-cell-write) の堅牢パターンに従う。 2026-06-12 様式⑭-1 で確立)
- ⚠️ **`diff-form-xlsx.py` ([`diff-form-xlsx-detection`](#diff-form-xlsx-detection)) は cell 値の diff のみで fill 色を見ない** → 黄色残置を catch できない。 **[`pdf-visual-confirm`](#pdf-visual-confirm) PDF visual confirmation でのみ可視化**される。
- 黄色 cell の機械走査: `cell.fill.patternType == 'solid' and getattr(cell.fill.fgColor, 'rgb', None) == 'FFFFFF00'`。

同じ [`pdf-visual-confirm`](#pdf-visual-confirm) PDF visual で**同時に捕捉される他の落とし穴** (= いずれも cell 値検証では見えない。 2026-06-03 教研支援課様式⑭-1 fill で 3 件同時発見):
- **文字 clipping**: center 配置の長い文字列 (= 例「東京大学大学院工学系研究科」) が cell 幅超過で**両端が clip** (= left 配置なら右のみ clip)。 **非結合セル**なら fix = `cell.alignment = Alignment(horizontal=a.horizontal, vertical=a.vertical, ..., shrink_to_fit=True)` (= 既存 alignment 属性を保持して shrink_to_fit だけ足す)。 ⚠️ **結合セル (例 G13:M13) では shrink_to_fit は no-op** = 効かない。 結合セルは **font size を下げる**のが唯一の手 ([`merged-cell-text-clipping`](#merged-cell-text-clipping))。
- **multi-sheet workbook → PDF 全ページ出力**: `xlsx-to-pdf.sh` ([`xlsx-to-pdf-script`](#xlsx-to-pdf-script)) に sheet 名を渡しても Excel engine が **workbook 全 sheet を各ページ出力**することがある (= 例 様式⑭-1/⑭-2/⑭-3/領収書/dropdown の 5 sheet → 5 ページ PDF)。 提出は目的 sheet のみなので **PyMuPDF で目的ページを抽出**: `import fitz; src=fitz.open(big); out=fitz.open(); out.insert_pdf(src, from_page=0, to_page=0); out.save(submit)`。 [`multi-sheet-form`](#multi-sheet-form) の多 sheet 注意と併読。

---

## <a id="xlsx-visual-unobservable"></a>xlsx visual rendering の Claude 観察不可 と PDF 視認義務

openpyxl で xlsx を fill する Claude は **Excel UI でどう visual rendering されるかを直接観察できない構造的限界** がある。 `cell.value = '...'` や `cell.alignment = Alignment(wrap_text=True)` を設定して save しても、 Excel UI 側で「文字 clip」 「dropdown 不動作」 「row height 不足」 「page break wrong location」 等で user 期待と乖離する事故が多発する。

### <a id="claude-cannot-observe-render"></a>構造的限界

- openpyxl で setting 完了 = xlsx の xml 更新 = Excel が読み込んだ時の動作の **necessary condition**
- ただし **sufficient condition ではない**: Excel UI の render engine 側で別解釈・縮小・auto fit・font fallback 等が起きる
- 結果として「設定した = 動作した」 と等式化する trap に陥りやすい (= setting の完了 ≠ render の確認)。 → 次の [`pdf-visual-confirm`](#pdf-visual-confirm) で実 PDF を視認するまで「動作した」 と結論しない

### <a id="wrap-text-row-height-prereq"></a>wrap_text 依存の落とし穴 (= row height prerequisite)

`cell.alignment = Alignment(wrap_text=True)` 設定だけでは Excel UI で visual wrap が effective でない場合あり:

- **真因**: merged cell の row height が固定だと wrap で複数行になっても height 制約で clip = 1 行分しか visible
- **prerequisite**: `ws.row_dimensions[r].height = X` で row height 拡大が必須 (= openpyxl の `height` setter は内部で customHeight=True 自動設定)
- ⚠️ `customHeight=True` 直接 set は **AttributeError** (= read-only): height setter のみ使う

```python
# ❌ NG (= AttributeError)
ws.row_dimensions[21].customHeight = True

# ✅ OK (= height setter が内部で customHeight=True 設定)
ws.row_dimensions[21].height = 40
```

### <a id="explicit-newline-break"></a>explicit `\n` 改行 = wrap_text 依存しない確実方法

`wrap_text` 設定の Excel 側 effective を信用できない場合の **最確実 fallback**:

```python
ws['M21'] = '「課題名」\n本文 1 行目、\n本文 2 行目'
```

cell value 内に手動 `\n` (= line break character) を埋め込めば、 Excel は必ず改行 render する (= `wrap_text` 設定不要、 alignment ignored 関係なし)。 row height は依然 prerequisite なので併用する。

### <a id="pdf-visual-confirm"></a>PDF visual confirmation 義務

xlsx fill 完了直前に必ず **PDF preview 生成 + 視認**:

```bash
# AppleScript で Excel に PDF として保存命令 (= macOS、 Excel 起動必要)
osascript -e 'tell application "Microsoft Excel"
    open POSIX file "/path/to/form.xlsx"
    save as active workbook filename "/path/to/form.pdf" file format PDF file format
end tell'
```

⚠️ AppleScript の save as syntax は Excel for Mac の version で異なる + parameter error 出やすい。 fallback として **user に Excel で「ファイル → 印刷 → PDF として保存」 を依頼 + PDF を chat 添付してもらう**。

**運用 reflex**: 「私の setting した xlsx を 私の判断だけで完成宣言しない」 を 1 つの問い として保持。 PDF visual confirmation は form fill の **必須 prerequisite** で、 「user 指摘待ち」 reactive ではなく **proactive 早期催促** が筋。 user 指摘で初めて気付く pattern は連鎖失敗 (= 同 user に複数 turn の修復依頼) を必ず生む。

### <a id="image-budget-exhaustion"></a>画像レンダリング検証の "image budget" 枯渇 → text-first 原則

[`pdf-visual-confirm`](#pdf-visual-confirm) は「PDF を render して目視」 を義務化するが、 **画像を読みすぎると会話単位の hard limit に達し、 以後その会話では画像が一切読めなくなる**。

**症状**: 数十ページの PDF を PNG 化して目視する等で画像を大量に読むと、 ある時点から **すべての画像読み込みが恒久的に失敗**する:
- 内部エラー: `API Error: an image in the conversation could not be processed and was removed`
- user 側表示: 「画像を処理できませんでした」 「画像を読み込めませんでした」
- ⚠️ **同一会話内では回復しない** (= 新しい session を開くまで戻らない)。

**重要な切り分け**: この limit は **画像 content block だけ**に効く。 **テキストは依然読める**:
- PDF テキスト: `fitz` の `page.get_text()` (= render でなく抽出)
- docx 構造: python-docx / zipfile で `word/document.xml` を直読み
- 通常の Read (テキストファイル)

→ 検証を image でなく text に切り替えれば作業は続行できる (= 読んでいるのは「画像の推測」 でなく「docx/PDF の中身そのもの」 = 本物のデータ)。

**したがって [`pdf-visual-confirm`](#pdf-visual-confirm) を精緻化 (= 否定でなく検証目的の分離)**: 「何を確かめるか」 で道具を分ける。 ⚠️ **text-first は「視覚確認を省く」 ではない** — [`pdf-visual-confirm`](#pdf-visual-confirm) の視覚確認 mandate は LAYOUT について不変。

- **CONTENT 検証** (= 正しい文字列が在る / 無い) → **text-first**。 「PDF を render → 目視」 より「PDF テキスト抽出 → 期待文字列を assert」 が優れる (= image render は遅い + image budget を消費 + [`docx-pdf-stale-cache`](#docx-pdf-stale-cache) の stale を見逃す)。 text で十分なのはこの目的**だけ**。
- **LAYOUT 検証** (= 文字 clipping / `###` overflow / row height 不足 / page break / 体裁、 [`bool-cell-hash-overflow`](#bool-cell-hash-overflow) / [`datetime-cell-hash-overflow`](#datetime-cell-hash-overflow) / [`claude-cannot-observe-render`](#claude-cannot-observe-render)) → 多くは **text では捕捉できない**。 ⚠️ **例外 = 結合セルの記入値 clipping は [`check-form-clipping.py`](../scripts/check-form-clipping.py) で機械検出できる** (= LibreOffice/Excel は clip 時に text 層も truncate するので「記入値↔PDF 描画文字列」 照合で出る。 ただし clip-path で全文を残す renderer もあるので engine 依存 = 第一防衛線)。 `###` / row height / page break / 罫線欠けは依然 text 不可。 いずれにせよ [`pdf-visual-confirm`](#pdf-visual-confirm) の視覚確認は **必須** (= 機械検出は視覚を置換しない、 [`merged-cell-text-clipping`](#merged-cell-text-clipping))。 image budget が枯渇しているときは Claude が render するのでなく **user に PDF を見てもらって relay** で行う (= mandate を満たす手段を user に移すだけ)。

**visual が要る具体例** (= 体裁・削除後の空き詰め・手書き赤入れ・上記 LAYOUT 問題) は **user に見てもらって relay** する (= [`visual-check-by-user`](#visual-check-by-user)「視覚確認は user に依頼」 を、 image limit が "速いから" でなく "そうするしかない" に格上げ)。 自分への「目視で確認」 は責任放棄 + 循環検証の温床 (= 削除に使った判定で見ると漏れが見えない、 [`manual-review-required`](#manual-review-required))。

⚡ **reflex — 1 回 fail を確認したら image 再試行を即やめる**: 画像が読めないと分かったら、 **同じ画像読み込みを何十回も retry しない**。 in-session では回復しないので retry は時間と budget の純粋な浪費 + user を待たせる。 1 回の明確な fail で確定とみなし、 即座に手段を切り替える: ① **text 抽出で代替して続行** (= 大半はこれで足りる、 §上記) → ② visual が必須なら **user に relay 依頼** → ③ それも無理なら **新しい session に移る** (= image budget は session 単位なのでリセットされる)。 「もう一度試せば読めるかも」 は false hope。 同型 reflex は automation 全般に適用 (= [`docx-pdf-stale-cache`](#docx-pdf-stale-cache) の Word automation ループも同じ「N 回で諦めて fallback」)。

origin: 2026-06 ある官製様式の修正で、 事務側の赤入れ PDF を全ページ画像化して赤字を追ううちに image limit に到達 → 以後 Claude は画像を一切読めず → docx 構造 + PDF テキスト基準の検証に切替 + 事務側の赤入れマークは user が page-by-page で relay して完遂 (= 読めない画像を何度も読み直そうとして時間を浪費したのが反省点)。

---

## <a id="multi-sheet-form"></a>多 sheet form の構造理解と sheet 全 sweep 義務

xlsx form template は通常 **複数 sheet 構造** で、 sheet 間 数式自動連動 + 横並び left/right page 分割 等の特殊構造が頻繁。 「sheet = 縦長 1 form」 reflex equate が複数の落とし穴を作る。

> 🔑 **全シート把握原則 (read は hidden を skip しない)**: dump / sweep / verify など **読み取り系は常に hidden を含む全シートを対象**にする。 `if sheet_state=='hidden': continue` で skip すると同型 cell・印欄・数式連動先を見落とす。 hidden cell は `[HIDDEN]` marker を併記して把握し、 「直すか / user 確認か」 はその上で判断する。 ⚠️ **hidden 化する (write) のは別問題**で user 明示時のみ ([`hidden-sheet-user-expectation`](#hidden-sheet-user-expectation))。 = read は全把握 / write は慎重、 の非対称。

### <a id="all-sheet-sweep"></a>sheet 全 sweep 必須 (= form fill 完了直前の checklist)

```python
wb = openpyxl.load_workbook(path, data_only=False)
for sn in wb.sheetnames:
    ws = wb[sn]
    print(f'[{sn}] state={ws.sheet_state} / max_row={ws.max_row} / max_col={ws.max_column}')
```

各 sheet (= hidden 含む全シート、 上記 全シート把握原則) を inspect + 「私が fill した sheet 以外で同型 narrative cell が残っていないか」 を grep (hidden cell は `[HIDDEN]` marker で把握)。 「form の中心 sheet (= row 1-50 part)」 だけを fill して「form 全体 fill 完了」 と reflex equate するな。

### <a id="cross-sheet-formula-chain"></a>数式自動連動 cell の chain effect

xlsx form 内に `=IF(他sheet!cellA="","",他sheet!cellA)` 等の **数式自動連動 cell** が頻繁。 master sheet の cell を fill すると別 sheet の参照 cell も自動 update = 同型 overflow が複数 sheet に伝播する:

- 例: 出張願 sheet M21 (= 用務) → 出張報告書 sheet M29 が `=IF(...,出張願!M21,...)` で連動 → M21 overflow が M29 でも同型に発生 + 出張報告書 sheet を inspect していないと user 指摘まで気付かない
- **対策**: form fill 後に sheet 間 `=` で始まる数式 cell を grep + 全参照先 sheet の同 cell visual も check

```python
for sn in wb.sheetnames:
    ws = wb[sn]
    for row in ws.iter_rows():
        for cell in row:
            if isinstance(cell.value, str) and cell.value.startswith('=') and '!' in cell.value:
                print(f'[{sn}] {cell.coordinate}: {cell.value!r}')  # = 別 sheet 参照を grep
```

### <a id="side-by-side-page-split"></a>横並び left + right page 分割構造

1 sheet 内に「**左半分 (= col A-AI) + 右半分 (= col AP-BV) の横並び 2 page** 構造」 が存在する form あり (= 学術出張報告書、 海外帰国届、 等)。 sheet = 縦長 1 form と reflex equate すると wrong:

- print_area = `A1:BV100` + scale fit で 1 page 圧縮 → 文字 unreadable + clip
- user 「~~~ が無くなってる」 「~~~ がはみ出してる」 で初めて気付く typical pattern

**対策**: print_area を **multiple ranges** で設定 (= [`multiple-print-areas`](#multiple-print-areas) 参照)。 加えて column 範囲を dump 時に sheet 全 inspect (= col AP+ も visible にする) + form の visual layout を user PDF で確認。

### <a id="hidden-sheet-user-expectation"></a>hidden sheet 判断は user 期待に依存

「帰国後 fill 想定」 「印刷不要」 等の理由で `ws.sheet_state = 'hidden'` 設定する判断は **user 期待を misread する risk** あり (= 例: 出張報告書 sheet を「帰国後だから hidden」 と判断 → user 「出張報告書もいる」 で reject)。

- マニュアル / template の sheet 構成は通常「提出パッケージに含める全 sheet が visible」
- hidden 化 = user 明示指示があった時のみ実行
- 判断不明なら user 確認

### <a id="same-pattern-grep-sweep"></a>同型文字列 grep 全 cell sweep (= user 指摘 1 cell scope trap 防止)

user 指摘で 1 cell の修復を行う時、 **同型文字列 (= 同じ narrative pattern) を含む全 cell を grep で sweep** + 全部修復する:

```python
target_keywords = ['大阪大学', '大阪府', '量子波束']
for sn in wb.sheetnames:               # hidden も含む全シート (= 全シート把握原則)
    ws = wb[sn]
    mark = ' [HIDDEN]' if ws.sheet_state == 'hidden' else ''   # skip せず marker 併記
    for row in ws.iter_rows():
        for cell in row:
            v = cell.value
            if isinstance(v, str) and any(k in v for k in target_keywords):
                print(f'[{sn}{mark}] {cell.coordinate} ({len(v)}文字): {v[:60]!r}')
```

「user 指摘 1 cell scope = 私の修復 scope」 reflex trap (= literal interpretation trap) は同型 cell を含む multi-sheet で連鎖失敗する。 → user が 1 cell を指摘しても、 その文字列を全 sheet grep して同型 cell を横断修正する (=「user 指摘文字列の grep 全 cell sweep」 を form fill domain で必須化)。

---

## <a id="print-area-pagebreak"></a>印刷範囲 / page break / scale の設定

xlsx 印刷 setup は openpyxl で `print_area` + `page_setup.scale` + `pageSetUpPr.fitToPage` + `row_breaks` / `col_breaks` の組合せで決まる。 各 attribute の interaction を理解する。

### <a id="print-area-tradeoff"></a>print_area の設定 trade-off

- `print_area = None` (= template 原状態): user が Excel UI で手動印刷範囲設定
- `print_area = "A1:AH100"` (= 任意設定): 私の判断が wrong だと user 期待と乖離 + page 数 wrong

**Best practice**: template に `print_area` 既設定があれば触らない (= origin keep)。 未設定なら user 期待 (= PDF or 口頭) を先に取ってから設定。 「任意設定 → user 指摘 → 修復」 連鎖を避ける。 ⚠️ ただし**体裁を能動的に直す**局面 (= 余白偏り・1 sheet を複数ページに) は例外で詰める → [`print-area-bbox-fit`](#print-area-bbox-fit) / [`one-sheet-multi-page-split`](#one-sheet-multi-page-split)。

### <a id="fittopage-vs-scale"></a>fitToPage vs scale 明示

```python
ws.sheet_properties.pageSetUpPr.fitToPage = True
ws.page_setup.fitToWidth = 1
ws.page_setup.fitToHeight = 1
```

→ Excel が「1 page に縮小 fit」 mode で全 content を 1 page に圧縮、 文字 clip 可能性。 通常 form では wrong (= row_breaks / col_breaks が ignored される可能性)。

⚠️ **`fitToPage=True` だけでは縦に効かない罠**: `fitToHeight=0` (= template 既定値 = 無制限) のままだと、 fitToPage を立てても**縦は fit せず scale 任せで縦溢れ**する (= 2026-06 出張様式で全 sheet が `fitToPage=True ∧ fitToHeight=0 ∧ scale=75/36` で溢れていた実例)。 1 ページに収めるなら **`fitToWidth=1` と `fitToHeight=1` を両方明示**する (= 0 は「無制限」 で 1 は「1 ページ」、 別物)。

```python
ws.sheet_properties.pageSetUpPr.fitToPage = False
ws.page_setup.scale = 85  # = 85% 縮小
ws.page_setup.fitToWidth = 0
ws.page_setup.fitToHeight = 0
```

→ scale 明示で「横 page 内、 縦自然 break」 になる。 row_breaks / col_breaks で manual page break。

### <a id="multiple-print-areas"></a>multiple print_areas (= 横並び form 用)

```python
ws.print_area = 'A1:AI100,AP1:BV100'
```

カンマ区切りで multiple print areas、 left + right を別 page で印刷 (= [`side-by-side-page-split`](#side-by-side-page-split) の横並び form 用)。 sheet 内 1 件の print_area attribute に複数範囲を comma 区切りで列挙。

### <a id="row-col-breaks"></a>row_breaks / col_breaks (= manual page break)

```python
from openpyxl.worksheet.pagebreak import Break
ws.row_breaks = openpyxl.worksheet.pagebreak.RowBreak()
ws.row_breaks.append(Break(id=63, max=ws.max_column, min=0))
```

row 63 と 64 の間に horizontal break = page 1 (row 1-63) + page 2 (row 64+)。 横並びは `ws.col_breaks` で同型。

### <a id="print-setup-visual-confirm"></a>印刷 setup 変更後の PDF visual confirmation 義務

[`pdf-visual-confirm`](#pdf-visual-confirm) と同型: 印刷 setup 変更後は必ず PDF visual confirmation を user PDF or AppleScript で実行。 「私の setting だけで OK」 reflex stop しない。 印刷範囲設定 は visual rendering の中で最も「私の判断 vs user 期待」 乖離が起きやすい domain。

### <a id="print-dialog-whole-workbook"></a>user 印刷時の dialog 「ブック全体」 vs 「アクティブシート」

Excel UI の印刷 dialog で **default 「アクティブシート」** の場合あり (= 当面 visible な sheet 1 つのみ印刷)。 multi-sheet form の印刷時 user に「**ブック全体**」 選択を **明示 案内**:

- 「印刷 dialog で『ブック全体』 を選択してください (= 全 sheet 印刷)」 を必ず案内
- 「ブック全体」 を選ばないと hidden 化していない sheet が含まれない → user 「~~~ がない」 連鎖の trigger

---

## <a id="multi-sheet-pdf-assembly"></a>多 sheet xlsx → 提出用 PDF: ページ分割・余白・体裁の作り込み

複数 sheet の様式 xlsx を「**提出用 PDF** (= 各 sheet が 1 ページ、 体裁が整った成果物)」 に変換する end-to-end の作り込み。 単純な [`xlsx-to-pdf-script`](#xlsx-to-pdf-script) 一発では「不要 sheet が混ざる / 1 sheet を 2 ページに割れない / 表が縮小して余白が偏る / 表末尾に点線が浮く」 が起きる。 これらを潰す slug 群 + それを順に適用する RECIPE。

> 🍳 **RECIPE (= 端から端まで、 週次の様式 PDF 業務はこの順で)**:
> 1. **構造把握**: [`form-dump-first`](#form-dump-first) で全 sheet を dump → 提出に含める sheet / 1 sheet を 2 ページに割る sheet を決める ([`multi-sheet-form`](#multi-sheet-form))
> 2. **fill**: [`openpyxl-xlsx-fill`](#openpyxl-xlsx-fill) 各則で記入 → [`all-sheet-sweep`](#all-sheet-sweep) + [`same-pattern-grep-sweep`](#same-pattern-grep-sweep) で全 sheet sweep + 同型文字列の横断修正 + [`label-vs-input-antipattern`](#label-vs-input-antipattern) を踏まない
> 3. **ページ体裁**: [`print-area-bbox-fit`](#print-area-bbox-fit) で印刷範囲を実内容に詰める + [`even-margins-centering`](#even-margins-centering) で余白均等化 + [`trailing-print-artifact`](#trailing-print-artifact) の点線を除去
> 4. **出力**: [`excel-pdf-whole-workbook-export`](#excel-pdf-whole-workbook-export) (= 不要 sheet を temp で削除) + 必要なら [`one-sheet-multi-page-split`](#one-sheet-multi-page-split) → [`fitz-pdf-toolkit`](#fitz-pdf-toolkit) で結合
> 5. **検証**: [`pdf-visual-confirm`](#pdf-visual-confirm) (= 全ページ目視、 LAYOUT) + [`pdf-margin-pixel-measure`](#pdf-margin-pixel-measure) (= 余白を px 実測) + [`image-budget-exhaustion`](#image-budget-exhaustion) (= 画像は 1 枚ずつ・fail したら即 text 切替、 budget 節約)
> 6. **永続化**: 生成手順が複雑・反復するなら [`expensive-intermediate-artifacts.md`](expensive-intermediate-artifacts.md) 準拠で生成 script をリポに置く (= 毎回手で組み直さない)

### <a id="excel-pdf-whole-workbook-export"></a>Excel の PDF 書き出しは workbook 全体を出す (= sheet 選択は効かない) → 不要 sheet は temp 削除

**症状**: macOS の Excel osascript で `save as active sheet of wbk ... file format PDF` (や `save as worksheet "名" of wbk ...`) を撃つと、 active sheet だけでなく **workbook 内の全 visible sheet が各 print_area で連続ページ出力**される (= observed: Excel for Mac)。 [`xlsx-to-pdf-script`](#xlsx-to-pdf-script) の表で Excel engine を「✓ 1 sheet」 としているが、 単一 sheet 指定は version 依存で**当てにならない**。

**確実な解法 (= 出力ページを制御する)**: temp copy を作り、 **出したくない sheet を `wb.remove()` してから**出力する。 出力 PDF のページ順 = temp に残した visible sheet の順。

```python
import openpyxl
wb = openpyxl.load_workbook("form.xlsx")
for name in ["不要シートA", "不要シートB", "マスタ"]:   # 提出に含めない sheet
    wb.remove(wb[name])
wb.save("/tmp/temp.xlsx")          # これを xlsx-to-pdf.sh / osascript で PDF 化 → 残した sheet 順のページ
```

⚠️ **数式参照の罠**: 削除する sheet を **残す sheet が数式参照していると、 Excel は open 時に再計算して #REF** になる (= 例: 報告書 sheet が `=日程表!C10` を持つのに 日程表 sheet を消す)。 削除前に [`cross-sheet-formula-chain`](#cross-sheet-formula-chain) の grep (`=...!`) で参照関係を確認し、 **参照先 sheet は消さず残す** (印刷したくないだけなら下記 [`one-sheet-multi-page-split`](#one-sheet-multi-page-split) の「全 sheet 出力して fitz で必要ページだけ抜く」 でも可)。

### <a id="one-sheet-multi-page-split"></a>1 sheet を複数ページに分割する (= print_area 切替 → 個別出力 → 結合)

**症状**: 1 つの sheet に 2 ページ分の内容がある (= 上半分が本体、 下半分が別表)。 これを 2 ページの PDF にしたい。 `fitToHeight=1` だと 1 ページに潰れ、 `row_breaks` で割っても **soffice も Excel も manual break を無視しがち** ([`soffice-excel-fidelity`](#soffice-excel-fidelity)) で安定しない。

**確実な解法**: **print_area を切替えて 2 回出力 → fitz で結合**。 同じ workbook を temp_A (= 上半分の print_area) と temp_B (= 下半分の print_area) の 2 つ作り、 それぞれ PDF 出力 → 必要ページを抜いて結合する。 数式参照先 sheet は両 temp に残すので #REF にならない。

```python
def build(out, report_pa):
    wb = openpyxl.load_workbook("form.xlsx")
    for n in REMOVE: wb.remove(wb[n])         # 不要 sheet 削除 (参照先は残す)
    wb["報告書"].print_area = report_pa        # 同 sheet で print_area だけ変える
    wb.save(out)
build("/tmp/A.xlsx", "A1:AJ45")    # 上半分 (= 本体。 余白を詰めるなら実内容 bbox に → print-area-bbox-fit)
build("/tmp/B.xlsx", "A46:AJ93")   # 下半分 (= 別表)
# → A.xlsx / B.xlsx を各 PDF 化 (excel-pdf-whole-workbook-export) → fitz で
#   A[本体ページ] + B[別表ページ] + A[残りページ] の順に結合 (fitz-pdf-toolkit)
```

### <a id="print-area-bbox-fit"></a>print_area は実内容の bounding box に詰める (= 広いと fitToHeight で縮小+余白偏り)

**症状**: 表が小さく、 右 (や上下) の余白が過大。 **原因 = print_area が実内容より広い** (= 空列・空行を含む)。 `fitToWidth=1 ∧ fitToHeight=1` は「縦横**両方**に収まる scale (= min を取る)」 なので、 縦長 sheet で print_area に空行が多いと**縦が binding** になり全体が縮小 → その分 横に余白が出る。 [`print-area-tradeoff`](#print-area-tradeoff) (= 触らない原則) の例外で、 体裁を能動的に直す局面。

**解法**: print_area を **実内容の bounding box** に詰める。 bbox は「**値 OR 罫線がある cell**」 を scan して求める (= 値だけだと罫線枠を取りこぼす)。

```python
minc=maxc=minr=maxr=None
for r in range(1, 200):
    for c in range(1, 60):
        cell = ws.cell(row=r, column=c); b = cell.border
        has = cell.value not in (None,"") or any(s and s.style for s in (b.top,b.bottom,b.left,b.right))
        if has:
            minr = r if minr is None else min(minr,r); maxr = r if maxr is None else max(maxr,r)
            minc = c if minc is None else min(minc,c); maxc = c if maxc is None else max(maxc,c)
# → ws.print_area = f"{get_column_letter(minc)}{minr}:{get_column_letter(maxc)}{maxr}"
```

### <a id="even-margins-centering"></a>余白を均等にする (= page_margins 統一 + 水平/垂直 中央寄せ)

**症状**: 内容が左 (や上) に寄り、 余白が偏る。 様式 template は **L/R と T/B の page_margins が非対称** (= 実例: T/B 0.748" vs L/R 0.236") なことが多く、 中央寄せも未設定。

**解法**: (1) `page_margins` を均等値に。 (2) `print_options.horizontalCentered` + `verticalCentered` を True に。

```python
ws.page_margins.left = ws.page_margins.right = ws.page_margins.top = ws.page_margins.bottom = 0.4
ws.print_options.horizontalCentered = True
ws.print_options.verticalCentered   = True
```

⚠️ **Excel は両 centered を尊重するが soffice は verticalCentered を無視** ([`soffice-excel-fidelity`](#soffice-excel-fidelity))。 注: 内容の縦横比が page と違うと、 binding でない側の余白は (歪ませず拡大した結果) **残る** — それを中央寄せで左右・上下に**均等配分**するのが目標 (= 余白ゼロではなく「偏りゼロ」)。 確認は [`pdf-margin-pixel-measure`](#pdf-margin-pixel-measure) で px 実測。

### <a id="fitz-pdf-toolkit"></a>PyMuPDF (fitz) で PDF を render / crop / 結合 / ページ数確認

xlsx→PDF の検証・加工の万能道具。 soffice / pdftoppm 不在でも動く (= 当 setup の標準)。

```python
import fitz
from PIL import Image
doc = fitz.open("out.pdf"); print(doc.page_count)
# 1. render to PNG (倍率は Matrix。 大きすぎると Read 不可 → image-budget-exhaustion)
pix = doc[4].get_pixmap(matrix=fitz.Matrix(1.7, 1.7))
img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
img.thumbnail((850, 1180)); img.save("/tmp/p5.png")          # Read で目視
crop = img.crop((x0, y0, x1, y1)); crop.save("/tmp/c.png")   # 問題箇所を拡大
# 2. PDF 結合 (= one-sheet-multi-page-split の仕上げ)
A, B = fitz.open("A.pdf"), fitz.open("B.pdf"); out = fitz.open()
out.insert_pdf(A, from_page=0, to_page=4)   # A の 0-4 ページ
out.insert_pdf(B, from_page=4, to_page=4)   # B の 5 ページ目を挿入
out.insert_pdf(A, from_page=5, to_page=5)
out.save("提出用.pdf")
# 3. 全ページを 1 枚に tile (= contact sheet。 N ページを 1 Read で一望 → image budget 節約)
import math
ts = []
for p in doc:
    px = p.get_pixmap(matrix=fitz.Matrix(0.5, 0.5))
    ts.append(Image.frombytes("RGB", [px.width, px.height], px.samples))
cols = 4; rows = math.ceil(len(ts) / cols)
w = max(t.width for t in ts); h = max(t.height for t in ts)
sheet = Image.new("RGB", (w * cols, h * rows), "white")
for i, t in enumerate(ts): sheet.paste(t, ((i % cols) * w, (i // cols) * h))
sheet.thumbnail((1400, 1400)); sheet.save("/tmp/contact.png")   # 1 枚で全ページ点検
```

⚠️ contact sheet は **全体把握用** (= ページ抜け・空白ページ・大崩れ・ページ数違いを 1 Read で検出、 [`image-budget-exhaustion`](#image-budget-exhaustion) を温存)。 細部 (= 罫線欠け・文字 clip・誤字) は解像度が足りないので**個別ページ render で確認**する (= 役割分担: contact sheet で当たりを付け → 怪しいページだけ拡大)。

### <a id="pdf-annotation-markup-read"></a>共同編集者の「青字 / 赤字」 マークアップは text 色でなく注釈 (ink / Stamp) のことがある

PDF を受け取って「青字 = ここを直して / 赤字 = ここが誤り」 と指示されたとき、 その色は **PDF の text レイヤの色とは限らない** — スマホ等で描いた **手書き注釈 (ink / Stamp annotation)** であることが多い。 この場合 `page.get_text("dict")` の span 色は **全部黒** (`#000000`) に見え、 色で拾おうとすると 0 件で空振りする。

**診断 (text 色か注釈 ink か)**:

```python
import fitz
doc = fitz.open("marked.pdf")
for pno, page in enumerate(doc):
    # (a) text レイヤに色があるか: span color の集合 (黒 = 0)
    cols = {s["color"] for b in page.get_text("dict")["blocks"]
            for l in b.get("lines", []) for s in l["spans"] if s["text"].strip()}
    # (b) 注釈があるか: annots() — 手書き系は Stamp(13) / Ink(15) 等 (a.type で実型確認)
    for a in (page.annots() or []):
        print(pno + 1, a.type, a.rect)      # a.rect = マークの位置 (= crop に使う)
```

全 span が `0` (黒) なのに `annots()` に Stamp がある → **色は注釈 ink 側**。

**読み取り (= Claude が ink を直接読む)**: 注釈を **含めて** render し、 注釈の `rect` 周辺に高 DPI で crop して手書きを読む。

```python
page = doc[pno]
pix = page.get_pixmap(matrix=fitz.Matrix(300 / 72, 300 / 72), annots=True,  # annots は既定 True (明示は意図表示)
                      clip=fitz.Rect(28, 420, 567, 500))                     # a.rect 周辺を拡大
pix.save("/tmp/markup.png")    # Read で手書きの訂正テキストを読む
```

⚠️ **肝は「ink は text でなく注釈なので `get_text` では拾えず、 render (画像化) してはじめて見える」** こと (`get_pixmap` の `annots` は **既定 True** なので render すれば注釈は出る — 明示 `annots=True` は意図を示すだけで必須ではない)。 [`fitz-pdf-toolkit`](#fitz-pdf-toolkit) の render に、 診断 (`annots()` で位置を特定) と注釈 rect への高 DPI crop を足したのが本節。 これは [`visual-check-by-user`](#visual-check-by-user) の「手書き赤入れは user に見てもらって relay」 を、 **image budget があるとき Claude が直接 ink を読む**経路で補完する (= budget 枯渇時は従来どおり user relay、 [`image-budget-exhaustion`](#image-budget-exhaustion))。

**補完ケース (= 色が text レイヤにある場合)**: 上は ink 注釈で「色で拾う → 0 件」 の側だが、 逆に **マークアップの色が text レイヤ (= 着色した `<w:t>` span)** にあるなら、 span 色を直接読んで triage bucket に振り分けられる (= render 不要、 決定論)。 span を走査して `span["color"]` (RGB int) を分類する:

```python
import fitz
doc = fitz.open("marked.pdf")
for page in doc:
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                c = s["color"]; r = (c >> 16) & 0xFF; g = (c >> 8) & 0xFF; bl = c & 0xFF
                if r > 120 and g < 100 and bl < 100:      bucket = "red=直す"        # fix this
                elif bl > 120 and r < 100 and g < 120:    bucket = "blue=コメント削除"  # delete guidance/comment
                else:                                     continue                  # 黒 = 本文
                # bucket ごとに s["text"] を集める
```

⚠️ どちらの経路かは [`pdf-annotation-markup-read`](#pdf-annotation-markup-read) 冒頭の診断 (span 色の集合が全黒か / `annots()` に Stamp があるか) で先に確定させる。

### <a id="pdf-margin-pixel-measure"></a>余白を px で客観測定する (= render → 非白 bbox)

「余白が均等か」 のような体裁判断を**目視に頼らず数値で**詰める。 render image を grayscale 化 → 非白 pixel の bbox → 上下左右の余白 px を出す。 [`even-margins-centering`](#even-margins-centering) の前後で測れば改善を定量化できる。

```python
import numpy as np
g = np.asarray(img.convert("L")); m = g < 250          # 非白 = 内容
ys = np.where(m.any(axis=1))[0]; xs = np.where(m.any(axis=0))[0]; H, W = g.shape
print(f"margins px: L={xs.min()} R={W-1-xs.max()} T={ys.min()} B={H-1-ys.max()}")
# L≈R かつ T≈B なら偏りなし。 片側だけ突出していれば print-area / centering を調整
```

⚠️ これは **LAYOUT (体裁) の客観化**であって [`pdf-visual-confirm`](#pdf-visual-confirm) の全ページ目視を**置き換えない** (= 文字 clip・罫線欠け・誤字は bbox では出ない)。 目視 + px 実測の併用。

### <a id="soffice-excel-fidelity"></a>soffice と Excel の体裁差 (= verticalCentered / page break の扱い)

同じ xlsx でも render engine で結果が変わる。 体裁に効く差:

| 設定 | soffice (LibreOffice) | Excel (osascript) |
|---|---|---|
| `print_area` / `fitToWidth` / `fitToHeight` | 尊重 | 尊重 |
| `horizontalCentered` | 尊重 | 尊重 |
| `verticalCentered` | **無視** | 尊重 |
| `row_breaks` / `col_breaks` (manual break) | **無視しがち** | 概ね尊重 (但し fitToPage と競合時は break 無効、 [`fittopage-vs-scale`](#fittopage-vs-scale)) |

→ 中央寄せ・manual break に依存する体裁は **Excel engine で出す**。 soffice 不在マシン (= 当 setup) では [`xlsx-to-pdf-script`](#xlsx-to-pdf-script) が自動的に Excel engine に fall back する。

### <a id="trailing-print-artifact"></a>表末尾の「浮いた点線」 = 印刷範囲に余分な末尾行/半スロットが入っている

**症状**: 表の下に、 表本体から離れて「**浮いた横点線**」 が 1 本出る。 user に「これ何?」 と聞かれる典型。

**原因**: print_area に **template の最後の余分な行 (= 空スロット / 半スロット)** が入っており、 その行が**側罫線を失って下罫線 (hairline) だけ残る**と、 表から切り離された点線に見える。

**解法**: print_area を **最後の「実線区切り (= 罫線が全幅に通った完全な行)」 まで**に詰める ([`print-area-bbox-fit`](#print-area-bbox-fit) の特殊形)。 逆に表の最下行で**左端だけ下罫線が欠ける**症状は merged cell の anchor 罫線漏れ ([`merged-cell-write-topleft`](#merged-cell-write-topleft) の罫線版)。

---

## <a id="label-overwrite-detection-limit"></a>label overwrite 機械検証 limit + 手 review 必須

`diff-form-xlsx.py` の `LABEL_OVERWRITE` 検出は完全でない:

- **検出範囲**: template cell value が「label-like suffix」 (= 「の必要性」 「の明細」 等、 [`diff-form-xlsx-detection`](#diff-form-xlsx-detection) 参照) で終わり、 fill 後に value が input narrative に置き換えられた場合
- **検出漏れ pattern**: template cell value が「月日」 「交通費経路」 「研究種別選択」 等の **短い header label** で、 fill 後に value が input data に置き換えられた場合 → script は **VALUE_CHANGED** 扱いで pass (= LABEL_OVERWRITE 検出せず)

### <a id="detection-miss-example"></a>典型検出漏れ事例

```
3_ 旅費請求書 row 27 = header row (= label):
  B27 = '月日' / F27 = '交通費経路' / W27 = '運賃' / AC27 = 'その他'
3_ 旅費請求書 row 28+ = actual input row

→ 私が B27 / F27 を input で fill = label overwrite (= 様式 label 上書き禁止 violation)
→ diff-form-xlsx.py は「VALUE_CHANGED: B27 月日 -> 2026-06-12」 と表示するだけで LABEL_OVERWRITE 検出せず
→ 「✓ No label overwrites detected」 で pass → 手 review なしで stop → user 指摘で発覚
```

### <a id="manual-review-required"></a>手 review 義務

機械検証 pass = OK reflex で「✓ pass」 stop しない:

- VALUE_CHANGED 出力を **逐一 chat に expose** + template value を確認 (= 「月日」 「交通費経路」 等の **header label を input で上書きしていないか?**)
- 「VALUE_CHANGED is harmless」 reflex を疑う (= 大半は dropdown / chk box の placeholder 置換で valid だが、 header label 上書きが混入する pattern あり)
- row 27 が header / row 28+ が input、 等の form 構造を **dump で確認**してから fill 開始

### <a id="header-row-detection-helper"></a>dump 時の header row 識別 helper

```python
# dump 時に「同 row の複数 cell に短い label-like value が並んでいる」 = header row 候補
for row_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=ws.max_row), 1):
    text_cells = [c for c in row if isinstance(c.value, str) and 1 <= len(c.value) <= 10]
    if len(text_cells) >= 3:
        print(f'  row {row_idx} candidate header: {[(c.coordinate, c.value) for c in text_cells]}')
```

短い text cell が同 row に 3 件以上 = header row 候補 → fill 対象から除外。

---

## <a id="business-trip-proof-forward"></a>学外団体主催出張の用務証明書類 forward flow

公的研究費 (= 科研費等) 規程で **学外団体主催出張 = 用務証明書類添付必須** (= 国内旅費規程典型 第 5 条 3 「学外団体主催の会合に出張する場合は、 このことを証明し得る書類の写しを日程表に代えて出張届に添付しなければならない」)。 紙の印刷物添付以外に、 **公式 announcement mail を事務窓口 ML 宛 forward** が代替 method。

### <a id="forward-mail-template"></a>forward mail 構造 (= template)

```
{事務窓口} 御中

{出張概要 1 文} の出張にあたり、 用務証明書類として公式案内のメールを
転送いたします。

科研費は {grant 課題名 + 課題番号} から支出予定です。

{(optional) 同研究会には {同行者 list} も参加します。}

よろしくお願いいたします。

{送信者名}

---------- Forwarded message ----------
From: {original sender}
Date: {original date}
Subject: {original subject}
To: {original to}

{original body — full retain、 truncate しない}
```

### <a id="forward-mail-components"></a>構成要素

- **宛名**: 事務窓口 ML (= 個人姓不明) なら「**御中**」、 個人なら「**姓 + 様**」 (= 一般 email 慣行)
- **用務概要 1 文**: 「{日付} {event 名} ({場所}) の出張」 で identifying info を contain
- **grant source note**: 「{grant 課題名}」 + 「課題番号 {番号}」 を明示 (= 出張支出 source の事務 verification 用)
- **同行者 list (= optional)**: 同 organization から複数名参加なら 1 行 list、 事務窓口で bulk 処理しやすくなる
- **Subject**: `Fwd: {original subject} — 出張用務証明書類` 等で **目的明示** (= 単純 `Fwd:` だけだと用途不明)

### <a id="forward-record-sync"></a>内部 record の同 turn 同期

forward mail send 後、 同 turn で:
1. `inbox/{月}.yaml` に entry (= category=送信済、 messageId、 cross_ref で全関連 entry 双方向接続)
2. `<project-thread-repo>/threads/<project>.yaml` に同型 thread entry
3. 関連 grant / event repo の cross_ref も update
4. 全 repo commit + push (= cross-repo drift 圧力 4「同 session 完結」 規律)

「mail send + yaml 記録 → 完了」 ではなく「mail send + yaml 記録 + commit + push → 完了」 を 1 unit として扱う (= 別 session の救済に依存しない)。

---

## <a id="external-vs-internal-form"></a>学外者 form vs 学内者 form の構造差認識

機関ごとに「**学内者 (= 教育職員) 用**」 と「**学外者 (= 大学院生 / 共同研究者) 用**」 で別 form template あり。 **印鑑構造 / 承認 chain が根本的に異なる**:

### <a id="external-internal-structure-diff"></a>典型的 構造差 (= 機関別 form 設計の一般 pattern)

| | 学内者 (= 教育職員) 用 | 学外者 (= 大学院生 / 共同研究者) 用 |
|---|---|---|
| 申請者 | 教員本人 | 出張依頼者 (= 研究代表者・分担者) |
| 承認 chain | 学長宛 + 学科主任 + 部局長 + 経理 / 人事 / 学務課 | 出張依頼者印 + 出張者印 のみで完結 |
| 提出物 | 出張願 + 日程表 + 旅費請求書 + 出張報告書 | 依頼書 + 承諾書 + 旅費請求書 + 日程表 |
| 出張先機関の印 | **不要** (= 機関ごとに異なる運用、 source 機関側完結が一般) | 同左 (= form 設計上 source 機関側で完結) |

### <a id="seal-field-verify-method"></a>user 質問への verify method (= 印欄存在問合せ reflex)

印欄の有無・位置・承認 chain は form (学外 / 学内 / 機関) で異なるので、 user 「{役職} 印欄ない?」 「{機関名} の承認印は?」 等の質問は推測で答えず必ず grep verify する。 **method の正本は [`seal-approval-sweep`](#seal-approval-sweep) 体系**: keyword set = [`seal-keyword-set`](#seal-keyword-set)、 template との grep+diff = [`seal-diff-with-template`](#seal-diff-with-template) (=「消えた」 TPL のみ存在 /「元から無い」 TPL+EDIT 両方 0 hit /「追加した」 EDIT のみ存在 を判別)、 質問への即答 + sweep range/keyword/confidence 明示 = [`seal-question-reflex`](#seal-question-reflex)。 ⚠️ grep は hidden sheet も scan (= skip すると false positive、 [`tpl-only-false-positive`](#tpl-only-false-positive))。

### <a id="tpl-only-false-positive"></a>「TPL のみ存在」 = false positive trap (= hidden sheet 関連)

私 (Claude) が hidden 化した sheet は「TPL では visible で grep hit」 「EDIT では hidden で grep skip」 で false positive 「私が消した」 風に見える。 grep 時に `ws.sheet_state == 'hidden'` continue を入れない (= 全 sheet scan)、 もしくは hidden marker を出力に併記して user judgment に渡す。

---

## <a id="seal-approval-sweep"></a>印鑑欄 / 承認 chain の機械的 sweep

[`seal-field-verify-method`](#seal-field-verify-method) の reflex を一般化: form 提出前に **全 sheet で印鑑欄 + 承認 chain の機械 sweep** を 1 回回す。

### <a id="seal-keyword-set"></a>sweep keyword set (= 漏れなし list)

```python
INKAN_KEYWORDS = [
    '印', '殿',                           # 基本
    '承認', '検印', '押印', '署名', '判',  # 認証 action
    '主任', '専攻長', '部局長', '科長',     # 内部承認 chain
    '研究科長', '学長', '機関の長',        # 上位承認
    '部長', '課長',                       # 部署長
]
```

### <a id="seal-diff-with-template"></a>diff with template (= 提出前 verify)

```python
# template と編集後 file の印鑑欄を grep + diff
tpl_inkan = grep_inkan(template_path)
edit_inkan = grep_inkan(edited_path)
print('TPL のみ (= 消えた candidate):', tpl_inkan - edit_inkan)
print('EDIT のみ (= 追加):', edit_inkan - tpl_inkan)
print('value 変更:', [k for k in tpl_inkan & edit_inkan if values[k]['TPL'] != values[k]['EDIT']])
```

### <a id="seal-question-reflex"></a>user 質問への reflex 統合

「~~~ 印欄ない?」 「~~~ 承認印は?」 等の form 構造に関する質問は **即 [`seal-diff-with-template`](#seal-diff-with-template) sweep 実行 + 結果 expose**。 推測 / memory base で「無いと思います」 と回答しない (= 「不確実性を expose」 reflex の form structure domain 適用)。

加えて、 「無い」 と確認できた場合も **sweep range + keyword + confidence** を明示 (= 「全 sheet (visible + hidden) で keyword N 種類 grep、 0 hit、 confidence high」 等)。

### <a id="seal-image-generation-embed"></a>認印画像の生成 + xlsx 埋め込み (= 印影が必要な認印レベル様式)

押印済み原本を電子提出する運用で、 **物理 朱肉でなく認印画像を印影として埋める**ことがある (= 認印が許される内部様式向け。 実印・登録印には使わない、 leak 時 偽造リスクあり。 本人/委任の認可下で運用)。

- **認印 PNG 生成** (= PIL): 朱色 `(202,48,38)` 等の outer ring (= `ImageDraw.ellipse(outline=red, width=24)`) + 縦書き氏名 (= 2 char なら上 char を `y≒0.30*S`、 下 char を `0.70*S` に centering) を CJK font で描画。 macOS の CJK font path: `/System/Library/Fonts/Hiragino Sans GB.ttc` / `PingFang.ttc` (= 篆書はないので Gothic で代替)。 透過 RGBA、 500×500 程度。
- **xlsx 埋め込み** (= openpyxl): `from openpyxl.drawing.image import Image as XLImage; xi=XLImage(png); xi.width=46; xi.height=46; xi.anchor='AH10'; ws.add_image(xi)` (= 46px ≒ 1.2cm、 anchor は氏名 cell の右端)。
- ⚠️ **openpyxl は reload で `img.width/height` を読むと PNG ネイティブ size (= 500) を返す**ので表示 size の verify には使えない (= 誤判定 trap)。 **実表示 size は drawing XML の `<ext cx cy>` (= EMU 単位、 9525 EMU = 1px)** で確認: `zipfile` で `xl/drawings/drawing1.xml` を読み `cx/9525` px 換算。 最終 verify は [`pdf-visual-confirm`](#pdf-visual-confirm) PDF visual で印影の位置・はみ出しを目視 (= 認印が氏名に重なる / 右余白からはみ出していないか)。

---

## <a id="related-repos"></a>関連リポ

- 実例: ある grant 申請 repo の specific 助成事業 dir 内の `fill_xlsx.py` (= 様式 1 xlsx 自動 fill)
- docx 自動 fill 実例: 同 dir の `fill_forms.py` (= 様式 0 + 様式 2 docx fill、 [`docx-fill-xml-edit`](#docx-fill-xml-edit) のリファレンス実装)
- ヘルパ抽出元: 同上 `fit_cell` 関数 (内部、 上記 [`wrap-text-needs-row-height`](#wrap-text-needs-row-height) のリファレンス実装)
- 業績選定の連携先: ある物理研究 repo の `papers/grant_pubs.py` (INSPIRE 連携)
