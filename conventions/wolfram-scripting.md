<!-- doc-meta
when: wolframscript を書く・debug するとき
category: research-domain
summary: wolframscript の Print[NumberForm] literal stringification + ToString wrap helper、 SetDirectory[DirectoryName[$InputFileName]] の空文字 fallback、 PDF Plaintext import を secondary fallback として活用 (= scientific-computing.md の数値 silent failure とは別 scope の Wolfram tool semantics gotcha 集)
-->
# Wolfram / wolframscript scripting conventions

Wolfram Language を script モード (= `wolframscript -file foo.wl` / `wolframscript -code ...`) で使うときの gotcha を集約する。 対象 = 数値解析・記号計算・図生成・PDF 抽出 等で wolframscript を CLI として叩く全般のリポ。 notebook (`.nb`) では起きない、 **script 特有の semantic 差** が大半なので、 notebook で動いていた code を script に移植する場面で踏みやすい。

scope 補足: 「数値計算が silently 壊れる patterns (= scale-dependent default, explicit-Euler 発散等)」 は [`scientific-computing.md`](scientific-computing.md) で扱う。 本ファイルは **Wolfram の tool semantics 起因** の gotcha (= notebook と script で `Print` が違う等) に絞る。

---

## <a id="numberform-literal"></a>1. `Print[NumberForm[x, spec]]` は script モードで literal 化する

### 問題

```mathematica
Print["mu = ", NumberForm[N[mu], {6, 4}]];
```

を notebook で実行すると `mu = 0.8169` と正しく formatted されるが、 wolframscript の console 出力は

```
mu = NumberForm[0.8169, {6, 4}]
```

と **literal stringification** される。 `Print` が format function を解釈せず、 `NumberForm` の wrapped expression をそのまま `ToString` する。 これは Wolfram の documented behavior: `Print` は最後に `OutputStream` へ `ToString[expr, OutputForm]` を流すが、 `OutputForm` は notebook の StandardForm/TraditionalForm renderer を経由しないため `NumberForm` の format function が発火しない。

console の table を読み手に提示する用途で発覚することが多く、 大量の数値出力で全部 literal 化されると output が unusable になる。

### 解決策: ToString で wrap

```mathematica
(* helper を script 冒頭で 1 行定義 *)
fmt[x_, spec_] := ToString[NumberForm[x, spec]];

(* 以後 NumberForm 直書きを fmt に置換 *)
Print["mu = ", fmt[N[mu], {6, 4}]];
(* → "mu = 0.8169" 正常 format *)
```

`ToString` が StandardForm 経由で format function を発火させる。 `NumberForm` 以外 (= `ScientificForm`, `EngineeringForm`, `AccountingForm`, `PaddedForm` 等) も同症状なので、 `fmt[x, spec]` helper を `Print` 前に必ず通す習慣にする。

### Alternative: `WriteString` + `ToString`

複雑な行を組み立てる時は

```mathematica
WriteString[$Output, "mu = " <> ToString[NumberForm[mu, {6, 4}]] <> "\n"];
```

`WriteString` は `Print` のような自動 newline / 自動 stringification がなく、 全て explicit に組み立てるため diagnostic 出力で安定。 重い loop の中で `Print` の overhead を避けたい時にも有効。

### Anti-pattern

- **notebook で動いたから script でも動くと assume**: notebook の Print は StandardForm renderer 経由なので format function が発火する。 script は OutputForm 経由で発火しない。 同 code が different semantic を持つ
- **数値が「ほぼ正しく見える」 ので literal 化を見落とす**: 数値部分が literal の中に埋まっているので、 `0.8169` を期待していると `NumberForm[0.816870378..., {6, 4}]` の中に `0.816...` が見えて「format spec が効いていないだけ」 と誤読しがち。 実際には spec を含めて何も発火していない
- **`Print[N[NumberForm[...]]]` で逃げる**: `N` は numeric evaluation で format には関係なし、 NumberForm が外にあるので literal 化は同じ

### 適用範囲

wolframscript の `-file` および `-code` 両方で発生。 notebook (`.nb` を CLI で実行する `-script` を含まない普通の interactive eval) では発生しない。 jupyter 上の Wolfram カーネルでも StandardForm 経由なので発生しない。 純粋に「OutputForm 経由か否か」 で決まる。

---

## <a id="inputfilename-empty-fallback"></a>2. `SetDirectory[DirectoryName[$InputFileName]]` で `$InputFileName` が空文字の fallback

### 問題

script 冒頭の慣用パターン

```mathematica
SetDirectory[DirectoryName[$InputFileName]];
Get["my_package.wl"];
```

は `$InputFileName` が常に set されていることを前提とする。 ところが wolframscript の起動経路によっては (例: `-code` 経由、 stdin pipe、 一部の hook 環境) `$InputFileName` が **空文字 `""`** になり、 `DirectoryName[""]` も `""` を返して `SetDirectory[""]` が

```
SetDirectory::badfile: The specified argument should be a valid string or File.
```

を出す。 関連 `Get` も current directory に対して resolve するので、 unrelated path の package を loading したり not-found で fall through する。

### 解決策: `$ScriptCommandLine` への fallback

```mathematica
SetDirectory[DirectoryName[
  If[$InputFileName =!= "", $InputFileName, First[$ScriptCommandLine]]]];
Get["my_package.wl"];
```

`$ScriptCommandLine` は wolframscript の引数を保持し、 `-file foo.wl` 起動時は `First[...]` で `foo.wl` の絶対 or 相対 path が取れる。 `$InputFileName` が空のときの fallback として安定。

`-code` 起動時は両方とも空になるので、 その場合は script を `-file` で起動するよう運用側で揃える。 `-code` での short one-liner を許容するなら `SetDirectory` 自体を skip して `Get` に絶対 path を渡す。

### Anti-pattern

- **`SetDirectory[NotebookDirectory[]]`**: notebook での慣用だが script では `NotebookDirectory[]` が undefined で fall through。 同 code を notebook / script 両方で使うときも `$InputFileName` fallback の方が portable
- **try-catch で `SetDirectory::badfile` を握り潰す**: warning は出ないが `Get` が想定外の場所から load するので、 silent な misload になる
- **`Get[FileNameJoin[{DirectoryName[$ScriptCommandLine[[1]]], "package.wl"}]]` で bare filename invocation の root path fail** (= 2026-05-25 RCA): wolframscript を script と同 dir から `wolframscript -file run_xxx.wl` で起動すると `$ScriptCommandLine[[1]] = "run_xxx.wl"` (= path prefix なし)、 `DirectoryName["run_xxx.wl"] = ""`、 `FileNameJoin[{"", "package.wl"}] = "/package.wl"` (= filesystem root 絶対パス) で `Get` が silent fail。 cascade で全 function 未定義、 後続呼び出しが unevaluated form のまま続行 (= `KeyExistsQ::invrl` 等の cryptic error 経由で発覚)。 解決: `SetDirectory[DirectoryName[...]] + Get["package.wl"]` pattern に統一 (= 上 §「解決策」 の form、 cwd 既に script dir なら `SetDirectory[""]` が badfile error 出しても Get は cwd で resolve して成功)。 `FileNameJoin` 形は path 拼接の保証なしに silent fail する点で `SetDirectory + Get` より fragile。 「`$InputFileName` 空 → `$ScriptCommandLine` fallback」 (= 上 §「解決策」) だけでは不十分、 「fallback して `DirectoryName` が空文字 でも `FileNameJoin` の左端 empty がルート扱いされる」 二重防衛が必要

---

## <a id="pdf-plaintext-import"></a>3. PDF text 抽出の secondary fallback としての `Import["...pdf", "Plaintext"]`

### 位置付け

PDF text 抽出の **fallback chain**: **PyMuPDF (`import fitz`) が first-line** (= [`hooks/pdf-read-fallback-nudge.sh`](../hooks/pdf-read-fallback-nudge.sh) が Read tool の `pdftoppm is not installed` 失敗を検出して PyMuPDF 1-liner を system reminder で injection、 機械的に推奨)。 wolframscript の `Import "Plaintext"` は **secondary fallback** (= Mathematica 持ちで PyMuPDF まで届かない or 軽い 1 page 確認等)。 ほかに poppler `pdftotext` (品質高 + layout 保持、 ただし macOS Tier 2 で source build 失敗事故あり)、 sips (macOS 標準だが機能限定)、 arXiv HTML 版 fetch (arXiv 限定、 version 一致 caveat) が候補。

### 用途

Mathematica は PDF を text として読める built-in 機能を持つ:

```mathematica
(* 全 page を 1 つの String として返す *)
allText = Import["foo.pdf", "Plaintext"];

(* 個別 page (= paper page number に近いが、 cover offset で ±1-2 ずれることあり) *)
page67 = Import["foo.pdf", {"Plaintext", 67}];

(* 総 page 数 *)
n = Import["foo.pdf", "PageCount"];
```

### いつ wolframscript path を選ぶか

- Python venv setup が面倒で PyMuPDF まで届かない、 かつ Mathematica は既に install されている
- 1 page だけ確認したい等の軽い用途で、 layout 不要 + PyMuPDF を呼ぶための venv 起動コストを払いたくない
- poppler bottle 不在で `brew install poppler` が source build 失敗する環境 (= macOS Intel Tier 2、 古い CLT 抱え等) で PyMuPDF も install 不可な fallback 二段目

選ばない (= PyMuPDF や pdftotext を選ぶべき場面):
- 大量 page (> 30) を頻繁に抽出 — wolframscript のロードコストが高い (1 回 ~3-5 秒)
- 文字位置・font・table 構造が必要 — PyMuPDF / pdftotext の方が忠実
- 属性 (= bbox / link / form field) を取り出す — Wolfram の Plaintext は構造を捨てる

### page index の注意

`Import[..., {"Plaintext", n}]` の `n` は **PDF 内 page index** (= 1 始まり、 表紙含む) であり、 paper の本文 page 番号と通常 ±1〜数ずれる (= title page / TOC / front matter で offset)。 取り出した text の頭に paper page 番号が含まれているはずなので、 dump して照合してから本格抽出する。

### return 型に注意

`Import[..., "Plaintext"]` は **単一 `String`** を返し、 list of pages ではない。 `{"Plaintext", n}` で個別 page を取ると同じく String。 `Length[]` 等で list 操作しようとすると意味なく 0 を返すので、 `Head` で確認すると安全:

```mathematica
res = Import["foo.pdf", "Plaintext"];
If[Head[res] === List, Length[res], StringLength[res]]
```

### Anti-pattern

- **`Import["...pdf"]` を引数なしで実行**: default format で raster image list を返し、 OCR していない以上 text にならない。 必ず `"Plaintext"` を明示
- **page 単位の loop で毎回 `Import` 全文**: 全 page を String 1 個で受けて position split する方が桁外れに速い (= ファイル open 1 回で済む)

---

## 関連

- 数値計算の scale-dependent default 等 numerical silent failure: [`scientific-computing.md`](scientific-computing.md)
- マシン固有 install 不可 package の蓄積 (= poppler 等が source build 失敗した時の machine-local 記録): [`install-failures.md`](install-failures.md)
- PDF text 抽出の代替 tool (= PyMuPDF / sips / arXiv HTML) と環境別の選択順序は 個人層 (`<your>-prefs/`) の dev-environment 規約で machine 別に分岐表として持つのが筋 (= 「マシン A では PyMuPDF first / マシン B では wolframscript も候補」 のような machine-dependent fact は cross-machine 比較を含むので layer 3 行き、 cf. [`docs/personal-layer.md`](../docs/personal-layer.md))
