# Office ファイル (Excel / Word / PDF / PowerPoint) ハンドリング — 入口マップ

行政・学術様式の Excel / Word / PDF / PowerPoint を機械で扱う作業の **最初に開く単一の入口 (router)**。
中身の正本は各 home file に置き、 本 file は「**どこに何があるか**」 の pointer に徹する
(= [`docs/convention-design-principles.md` §2](../docs/convention-design-principles.md#no-duplicate-rules) 「定義は1箇所、 他はポインタ」)。

> **なぜ専用の入口が要るか**: office files の処理は (a) **見た目が契約** (= reviewer は rendered PDF を見る、 値が正しくても layout が崩れれば差し戻される) / (b) **道具ごとに守れる地層が違う** (= openpyxl は drawing を破壊、 python-docx は破損 docx を作りうる) / (c) **lossy な解釈器の連鎖** (= xlsx → openpyxl → Excel → PDF → printer の各段で別パーサが別解釈) — の 3 性質ゆえに 1 章だけ読んでも安全に書けない。 規約・道具・原則が複数 file に分かれているのを束ねる入口が要る。

---

## <a id="pre-flight-checklist"></a>0. 弄る前のチェックリスト (参照順)

| # | 問い | 参照先 (層 1) |
|---|---|---|
| ⓪ **考え方** | 初見の様式 / slug の無い罠 / 道具選択に迷う? | [`office-automation-principles.md`](office-automation-principles.md) (= 様式=見た目が契約 / file=地層 / lossy 解釈器連鎖 / 道具選択の梯子 / 検証 3 層モデル / 「記入後は審査員の目で閉じる」 / 人間系原則 〔既知情報 prefill・print-last・記入分担 4 区分・受理側で閉じる〕) |
| ① **権限** | その file は作業ルート (cwd) の外 (`~/Downloads` / `~/Desktop` / `~/Documents` / `~/Dropbox` 等) か? | [`claude-code-permissions.md`](claude-code-permissions.md) (= `additionalDirectories` の 3 frontend 切り分け 〔CLI settings.json / Claude Code デスクトップ Tool policy / macOS TCC〕)。 ⚠️ Word の `/tmp` sandbox 許可ダイアログは別系統 → [`docx-tmp-sandbox-deny`](office-automation.md#docx-tmp-sandbox-deny) (docx は必ず project 配下で開く) |
| ② **skill か手動か** | 単純な読み書き・整形・形式変換か / 行政学術様式の精密 fill か | [下記 §3](#skill-vs-manual) |
| ③ **手順・落とし穴** | openpyxl / python-docx / 様式改変防止 / 検証 | **本丸** = [`office-automation.md`](office-automation.md)。 まず [症状 → 対処 早見表 (`#symptom-index`)](office-automation.md#symptom-index) で逆引き (= Excel crash / 日付 serial 印字 / 標題消失 / PDF -50/-1712/-609 等を症状から slug・既存 script に飛べる)。 各 subsection は安定 slug-anchor を持ち、 全 slug ↔ title ↔ related は併設 [`office-automation.index.yaml`](office-automation.index.yaml) (validator で dangling/orphan 0) |
| ④ **PDF 化** | xlsx / docx / pptx → 提出 PDF | [下記 §2](#pdf-conversion) |
| ⑤ **記入後の機械監査** | 様式に値を fill した後、 ラベル上書き / 空欄 / 配置崩れが残っていないか? | [下記 §4](#completion-audit) (原則 + script) |
| ⑥ **e-Rad 経由** | JST / 科研費 / 財団等の研究費応募で e-Rad に書類を上げる? | [`erad-submission.md`](erad-submission.md) (= 制度横断で効く e-Rad 挙動・字数・書式・つまずきどころ) |
| ⑦ **入手・提出の経路** | 雛形が Google Drive folder 配布? / 提出先が Google Form? | 入手 = [`google-api-direct-access.md#drive-folder-bulk-download`](google-api-direct-access.md#drive-folder-bulk-download) (folder 一括 DL + manifest)。 提出 = [`google-forms-automation.md#respondent-side-constraints`](google-forms-automation.md#respondent-side-constraints) (= **提出前にリポへ snapshot 保存** / 回答回数制限 = 再回答不可・訂正は別経路 / account domain 縛り) |

---

## <a id="traps-procedures-home"></a>1. 罠と手順の正本 = `office-automation.md`

[`office-automation.md`](office-automation.md) が全 gotcha の正本。 まず [`#symptom-index`](office-automation.md#symptom-index) で症状逆引き。 主要カテゴリ:

- **開始前**: [`form-dump-first`](office-automation.md#form-dump-first) (推測で書かず構造を全 dump) / [`template-provenance-check`](office-automation.md#template-provenance-check) (= テンプレ・前例の素性確認: 記入済み混入 / 旧版 stale / drawing 喪失の 3 罠)
- **openpyxl の罠**: [`merged-cell-write-topleft`](office-automation.md#merged-cell-write-topleft) / [`datetime-cell-hash-overflow`](office-automation.md#datetime-cell-hash-overflow) / [`xlsx-locked-by-excel`](office-automation.md#xlsx-locked-by-excel) / [`openpyxl-destroys-drawings`](office-automation.md#openpyxl-destroys-drawings) (= 標題 textbox 全消失、 様式 fill は Excel osascript 経由が default) / [`openpyxl-clears-formula-cache`](office-automation.md#openpyxl-clears-formula-cache)
- **Excel (osascript) write の罠**: [`excel-osascript-cell-write`](office-automation.md#excel-osascript-cell-write) (= -609 回避) / [`excel-write-string-autoconvert`](office-automation.md#excel-write-string-autoconvert) (= 日付文字列→serial、 apostrophe prefix)
- **様式改変の主因**: [`label-vs-input-antipattern`](office-automation.md#label-vs-input-antipattern) / [`label-overwrite-bug`](office-automation.md#label-overwrite-bug) / [`diff-form-xlsx-detection`](office-automation.md#diff-form-xlsx-detection) (= xlsx 機械検出、 fill 後必須) / [`diff-form-docx-detection`](office-automation.md#diff-form-docx-detection) (= **docx 機械検出**、 ラベル欄上書き / 見出し消失 / 箇条書き空欄 / labeled 列空) / [`embedded-instruction-in-label`](office-automation.md#embedded-instruction-in-label)
- **docx**: [`docx-fill-xml-edit`](office-automation.md#docx-fill-xml-edit) / [`docx-checkbox-content-control`](office-automation.md#docx-checkbox-content-control) / [`docx-pdf-stale-cache`](office-automation.md#docx-pdf-stale-cache) (= 再生成後は Word quit) / [`docx-password-roundtrip-edit`](office-automation.md#docx-password-roundtrip-edit) (= PW 暗号化 form の 5 step round-trip)
- **PDF / 視認義務**: [`pdf-visual-confirm`](office-automation.md#pdf-visual-confirm) (= 全変換 1 回ごとに目視) / [`image-budget-exhaustion`](office-automation.md#image-budget-exhaustion) / [`pdf-text-match-nfkc`](office-automation.md#pdf-text-match-nfkc) (= 互換字形 false negative 回避) / [`excel-pdf-bottom-border-drop`](office-automation.md#excel-pdf-bottom-border-drop) (= 枠が下に開く → `close-pdf-form-boxes.py`)
- **紙印刷**: [`pdf-prefill-direct`](office-automation.md#pdf-prefill-direct) (= 紙だけ要る時は雛形 PDF + fitz 印字、 汎用 engine = `pdf_form_fill.py`) / [`print-raster-pdf`](office-automation.md#print-raster-pdf) (= 600dpi ラスタ化で printer font 化け回避)
- **押印・署名**: [`signature-not-stamp`](office-automation.md#signature-not-stamp) / [`physical-seal-required`](office-automation.md#physical-seal-required)
- **多 sheet**: [`all-sheet-sweep`](office-automation.md#all-sheet-sweep)

## <a id="pdf-conversion"></a>2. PDF 化 (層 1 wrapper)

| 変換 | wrapper | 機構の正本 |
|---|---|---|
| xlsx → PDF | [`scripts/xlsx-to-pdf.sh`](../scripts/xlsx-to-pdf.sh) (= LibreOffice soffice → macOS Excel osascript fallback) | [`office-automation.md#xlsx-to-pdf-script`](office-automation.md#xlsx-to-pdf-script) |
| docx → PDF | [`scripts/docx-to-pdf.sh`](../scripts/docx-to-pdf.sh) (= macOS では Word AppleScript 駆動が default、 `--pages` で明示 Pages、 非 macOS は LibreOffice) | [`office-automation.md#docx-to-pdf-pages`](office-automation.md#docx-to-pdf-pages) + [`docx-pdf-stale-cache`](office-automation.md#docx-pdf-stale-cache) (= stale cache / cold-start 対処) |
| pptx → PDF | [`scripts/pptx-to-pdf.sh`](../scripts/pptx-to-pdf.sh) (= PowerPoint native export 優先、 LibreOffice fallback) | [`office-automation.md#pptx-to-pdf-powerpoint`](office-automation.md#pptx-to-pdf-powerpoint) (= 網掛け / pattern fill を潰さない要件は native 一択) |

⚠️ **docx は「Word 体裁が契約」 の正式書類が大半** ゆえ Pages re-typeset は重なり artifact を生む。 default を Word に倒している (2026-06 反転)。 詳細・新規 docx automation script を書く時の reflex は [`office-automation-principles.md` tool-selection-ladder](office-automation-principles.md#tool-selection-ladder) 参照。

⚠️ **提出は xlsx/docx 本体、 PDF は確認・印刷・後参照用** ([`pdf-snapshot-xlsx-submission`](office-automation.md#pdf-snapshot-xlsx-submission))。

## <a id="skill-vs-manual"></a>3. skill vs 手動の使い分け

判断表 (一般処理は skill / 様式精密 fill は手動 / PDF 抽出は pdf skill / 提出 PDF 化は §2 wrapper) は [`office-automation-principles.md` tool-selection-ladder](office-automation-principles.md#tool-selection-ladder) の `⚙️ skill が使える環境では` 表を参照。

## <a id="completion-audit"></a>4. 記入後は「審査員の目」 で閉じる (= 機械監査と最終確認)

- 原則: [`office-automation-principles.md` reviewer-eye-completion](office-automation-principles.md#reviewer-eye-completion) 「記入後は『審査員の目』 で閉じる」
- xlsx 機械監査: [`scripts/diff-form-xlsx.py`](../scripts/diff-form-xlsx.py)
- docx 機械監査: [`scripts/diff-form-docx.py`](../scripts/diff-form-docx.py)

## <a id="scripts-list"></a>5. 検証・変換 script 一覧 (層 1: `claude-config/scripts/`)

| script | 用途 / 機構正本 |
|---|---|
| [`diff-form-xlsx.py`](../scripts/diff-form-xlsx.py) | 様式 xlsx の label 上書き (= 様式改変) を雛形 diff で検出 (`LABEL_OVERWRITE=exit1`)。 fill 後必ず実行 → [`#diff-form-xlsx-detection`](office-automation.md#diff-form-xlsx-detection) |
| [`diff-form-docx.py`](../scripts/diff-form-docx.py) | 様式 docx の記入ミスを blank diff で検出 (ラベル欄上書き / 見出し消失 = HARD、 空の箇条書き / 全空 labeled 列 = surface)。 `--selftest` 内蔵 → [`#diff-form-docx-detection`](office-automation.md#diff-form-docx-detection) |
| [`scan-form-instructions.py`](../scripts/scan-form-instructions.py) | label 内 embedded instruction を category 別抽出 → [`#embedded-instruction-in-label`](office-automation.md#embedded-instruction-in-label) |
| [`xlsx-to-pdf.sh`](../scripts/xlsx-to-pdf.sh) | xlsx → PDF (soffice → Excel fallback) |
| [`docx-to-pdf.sh`](../scripts/docx-to-pdf.sh) | docx → PDF (macOS Word 忠実版 default、 `--pages` で Pages、 非 mac LibreOffice) |
| [`pptx-to-pdf.sh`](../scripts/pptx-to-pdf.sh) | pptx → PDF (PowerPoint native 優先、 LibreOffice fallback) |
| [`close-pdf-form-boxes.py`](../scripts/close-pdf-form-boxes.py) | Excel→PDF で落ちた下罫線 (= 承認/印影欄の box が開く) を全検出して閉じる → [`#excel-pdf-bottom-border-drop`](office-automation.md#excel-pdf-bottom-border-drop) |
| [`pdf_form_fill.py`](../scripts/pdf_form_fill.py) | 雛形 PDF への直接印字 engine (= anchor 印字 / NFKC 照合 / 600dpi ラスタ化 / 内蔵検証)、 紙単票向け → [`#pdf-prefill-direct`](office-automation.md#pdf-prefill-direct) |
| [`check-docx-integrity.py`](../scripts/check-docx-integrity.py) | docx の Word「破損」 判定 (Word 不要・決定論) → [`#docx-checkbox-content-control`](office-automation.md#docx-checkbox-content-control) |
| [`check-xlsx-integrity.py`](../scripts/check-xlsx-integrity.py) | xlsx の Excel「破損」 判定 (Excel 不要・決定論)、 zip 直編集 xlsx の納品前 gate |
| [`normalize-docx-decl.py`](../scripts/normalize-docx-decl.py) / [`docx_decl_patch.py`](../scripts/docx_decl_patch.py) | docx XML 宣言を Word 形式へ正規化 (= 厳格 Word の「破損」 回避) |
| [`check-office-automation-index.py`](../scripts/check-office-automation-index.py) | `office-automation.md` の slug ↔ `index.yaml` の dangling/orphan 検証 |

## <a id="env-specific-overflow"></a>6. 環境固有・個別実装の追補 (層 1 では持たない)

以下は機械別の install 状態・特定マシンの観察・実装例 (個別 project の生成 driver) など、 universal でない情報。 個人層・project 層が home:

- **作業ルート外フォルダの permission**: `additionalDirectories` の機械別登録状態 → 個人層 `dev-environment.md` 等
- **app の install 状態 / 機種別 automation 権限の付与状況**: `dev-environment.md` 等
- **生成 driver の実装例**: 各 project の `scripts/` (= 単票 PDF 直印字・多項目 workbook 一括生成・印刷セット checklist 等)
- **過去の事故 incident 記録**: `staging-incidents.md` 等

---

## 関連

- 考え方の正本: [`office-automation-principles.md`](office-automation-principles.md)
- 罠の正本: [`office-automation.md`](office-automation.md) + [`office-automation.index.yaml`](office-automation.index.yaml)
- 権限の正本: [`claude-code-permissions.md`](claude-code-permissions.md)
- e-Rad: [`erad-submission.md`](erad-submission.md)
- 4 層モデル: [`docs/personal-layer.md`](../docs/personal-layer.md) (= layer 1 の本 file は layer 3 を参照しない設計、 環境固有は各層側に追補)
