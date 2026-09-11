<!-- doc-meta
when: 過負荷・レガシー・validation の噛み合わない web サイトの入力フォームを browser automation (Chrome MCP 等) で代行するとき
category: web
summary: flaky web form 入力の一般則 — 送信結果はレスポンスページで判断しない (過負荷サイトは POST 成功後にエラーページを返す、重複確認画面 = 前回送信成功の証拠、#submit-truth-is-server-state)、公開 read API の cache による false negative (#read-api-cache-lag)、radio/checkbox は click より form_input 直接設定 (#form-input-over-click)、動的 combobox は form_input 不可、多言語ペア validation の非対称発火と「同値を両欄に焼く」回避 (#language-pair-validation)、metadata 自動取り込みの著者順 verify (#imported-metadata-verify)、リトライ規律 (フォーム状態は保存されない前提で SoT から再入力)、upload POST だけの 503 はサイズ原因と早断定しない (#upload-only-503)、**同じサイトを繰り返し打つなら操作列を生成物にする step driver harness (#step-driver-harness = 値の正本 → steps → 読み戻し照合の 3 層、 実体 scripts/lib/web_driver.py、 element 不在は throw せず missing / 往復には wait / 生 HTML を返さない / 行狙いは literal 一致、 消えない人間の 4 段 = login・upload・送信・CAPTCHA)**
-->
# flaky web form への browser-automation 入力の一般則

過負荷・レガシー・validation の癖が強い web サイト (研究者 DB、行政ポータル、学会申込システム等) のフォーム入力を browser automation (Chrome MCP 等) で代行するときの、サイト非依存の一般則。個別サイトの gotcha はサイト別 doc に置き、ここには「どのサイトでも起こる失敗形」だけを置く。

隣接 doc:
- サイト固有 doc (本 file の一般則の instance を持つ): [`researchmap.md`](researchmap.md) (= researchmap 固有の write 経路・DOI 取り込み・類似データ確認・言語ペア validation の現れ方)、[`google-forms-automation.md`](google-forms-automation.md) (= Google Forms 固有の構造解析・prefill・提出制約)、[`garoon.md#garoon-workflow-write`](garoon.md#garoon-workflow-write) (= Garoon workflow の再利用・3段照合・送信一覧検証)
- 別 domain: [`office-automation.md`](office-automation.md) (= 様式 xlsx/PDF の file 入力)、[`data-pipeline-automation.md`](data-pipeline-automation.md)。本 file は「ブラウザ越しの対話的 form」domain。

## <a id="submit-truth-is-server-state"></a>1. 送信結果はレスポンスページで判断しない — 真実はサーバー側の一覧

過負荷サイトは **POST を正常処理した後でもエラーページ (「アクセスが集中しています」等) を返すことがある**。逆に成功風の画面遷移でも validation で棄却されていることがある。レスポンス画面は送信成否の証拠として信用できない。

- **成否は必ずデータ側で確認する**: 登録一覧ページ / 編集一覧の件数・タイムスタンプ / 公開 API。「登録日時 + 登録者」表示が出れば確定
- **重複確認画面 (「類似データが既に登録されています」等) が出たら、それは前回送信が成功していた証拠**。読まずに「強制追加」すると二重登録になる。前回分の内容が意図どおりなら今回分は破棄が正解
- エラーページ後の盲目リトライは二重送信リスク。**確認 → 不在なら再送信** の順を崩さない

実測 (2026-07-22 researchmap、業績調査シーズンの慢性過負荷): 論文追加 POST → エラーページ表示で「失敗」と誤認 → 2 回目送信も同画面 → 3 回目で重複確認画面が出て **2 回目が silent 成功していた**と判明。3 回目を破棄して二重登録を回避。

## <a id="read-api-cache-lag"></a>2. 公開 read API の cache による false negative

書き込みは web UI、確認は公開 read API という分担をするとき、**API 側の cache/反映ラグで「未反映 = 未保存」と誤結論する**罠がある。同実測で、UI の編集一覧には反映済みの entry が公開 API には数十分現れなかった。

- 保存確認の authoritative は**ログイン済み UI の編集一覧** (= 書き込みと同じ経路)。API は補助
- API 未反映を理由に再送信しない (= §1 の二重登録に直結)

## <a id="form-input-over-click"></a>3. radio / checkbox は click より値の直接設定

JS が絡む form では、要素への click が **event handler の都合で無反応になる** ことがある (click 報告は成功、実 UI は未選択のまま)。DOM の値を直接設定する経路 (Chrome MCP なら `form_input` に radio へ `true`) の方が確実で、設定後の状態が返り値で確認できる。

- click で選択したつもりの radio が送信時に未選択でエラー、という形で発覚する。**送信前 screenshot で radio/checkbox の視覚状態を必ず確認**
- テキスト欄も `form_input` の返り値 (previous 値) で「意図した欄に書いたか」を毎回 verify できる — ラベルが同名の欄 (「(英語)」等) が複数あるページで特に有効
- **ref がそもそも取れない場合の fallback**: 長大 page では accessibility tree (read_page) が途中で切れ、fold 下の欄に ref が付かないことがある。まず検索系 tool (find) を試す (= 全 page を走査して fold 下でも ref を返す)。多数欄の一括入力なら JS 実行で `el.value = …` + `input`/`change` event dispatch が `form_input` と同等に働く (レガシー form で実測。React 系 SPA では効かない場合あり) — **設定後に全欄の値を read-back して verify し、radio は screenshot 目視も併用**

## <a id="dynamic-combobox"></a>4. 動的 combobox (select2 系) は値の直接設定が効かない

options を JS が遅延 populate する combobox (select2 等) は、直接設定しようとすると「Option not found. Available: ""」になる。click で開いてから選ぶ必要がある。**任意項目なら skip も選択肢** — 粘って全体を遅らせない。

## <a id="language-pair-validation"></a>5. 多言語ペア validation の非対称発火

日英など多言語欄を持つサイトには「**ある言語の項目を 1 つでも入力すると、同言語の必須項目 (title 等) が発火する**」形の validation がある (例: 「他の (英語) の項目を入力した場合、タイトル (英語) を必ず入力してください」)。

- 片言語のみで登録したい entry ではその言語の列だけで完結させる (もう片方の言語の欄に 1 つでも値を入れると連鎖する)
- 必須欄 (title 等) が全言語必須のサイトでは、**存在しない言語の欄に同じ値を焼く** のが実務解 (例: 英題オンリーの講演は日本語 title 欄にも同じ英題を入れる)。方針判断は所有者に確認してから
- ref が失効した状態でエラー → 再入力、を繰り返すと片言語だけ欠けた非対称状態を作りやすい。送信前に**言語ペアの対称性**を screenshot で確認

## <a id="imported-metadata-verify"></a>6. metadata 自動取り込み (DOI 等) の内容は原典と照合してから確定

DOI 入力で CrossRef 等から書誌を自動取り込みできるサイトは多いが、**registry metadata は紙面と一致しない場合がある**:

- **著者順**: proceedings 系は speaker-first で登録されていることがある (実測: PoS の CrossRef metadata は講演者が筆頭、紙面はアルファベット順)。出版社の公式ページで紙面の著者順を verify してから修正
- 誌名の二重接頭 (「Proceedings of Proceedings of ...」) 等の機械的汚れも混入する
- 自動取り込みは「入力の手間削減」であって「正しさの保証」ではない。取り込み後の全 field を目視してから送信

## <a id="retry-discipline"></a>7. リトライ規律 — フォーム状態は保存されない前提で設計する

- **入力値の SoT を手元に持ってから始める** (yaml / メール原文等)。サイト側のフォーム状態はエラーページ 1 枚で全損する
- 過負荷は波がある。10〜60 秒 wait → reload で回復することが多い。連打はしない
- ページ再ロード・エラーページ経由で **DOM 参照 (ref) は失効する**。参照は都度取り直し、古い ref への操作が「No element found」を返したら黙って同じ ref を再試行しない
- 1 entry 完了ごとに §1 の保存確認を挟む。複数 entry の一括入力で最後にまとめて確認、は失敗の切り分けを不能にする

## <a id="upload-only-503"></a>8. upload POST だけの 503 — サイズ原因と早断定しない

file upload だけが 503 (generic な "Service Unavailable"、maintenance / capacity 文言) を返し、同じサイトの GET (閲覧) は正常というとき、仮説は 2 つ: (a) request body のサイズ上限 (reverse proxy)、(b) upload backend の混雑・一時不調。実測例 (2026-08、Indico 系会議サイト): 22.6 MB と 12.9 MB の PDF が連続で 503 → 数時間後に 13 MB がそのまま通った = 混雑が原因で、サイズ削減は不要だった。

- 切り分け順: ① 時間を置いて**同じ file** で再試行 (混雑説) → ② 半分以下のサイズで再試行 (上限説)
- **品質を落とした縮小版を作り込むのは ② が確定してから**。ただし縮小版を先に用意しておくこと自体は安い保険 (両建て)
- GET 正常の確認が切り分けの前提 (サイト全体が落ちていれば単に待つ)

## <a id="step-driver-harness"></a>9. step driver harness — 「値の正本 → 操作列」 を決定的に出す

§1-8 は 1 枚のフォームを人手 (agent の手動 click / form_input) で通すときの一般則。 これに対し
**同じサイトを毎年・毎学期・多項目で打ち続ける**なら、 操作そのものを生成物にする方が安い。
実体 = [`scripts/lib/web_driver.py`](../scripts/lib/web_driver.py) (`--selftest` 内蔵)。

### いつここへ来るか

経路 ladder ([`machine-route-first.md#route-ladder`](machine-route-first.md#route-ladder)) を降りて、
**公式 API も CLI も内部 endpoint replay も無い**と確定したときだけ。 上位段があるならそちらが速く安全で、
本 harness は「それでも画面しか無い」 レガシー web app (JSP / frameset / 行政ポータル) の受け皿。

### 3 層に割る

| 層 | 置き場 | 中身 |
|---|---|---|
| A. 値の正本 | site 側 (yaml 等) | 課題名・金額・日付…。 **画面を正本にしない** — これが無い自動化は「速く間違える」 だけ |
| B. 操作列 | 本 harness | SoT → `[{label, js, wait, expect, human}]` を決定的に生成。 agent は流すだけ |
| C. 読み戻し照合 | site 側 parser + `diff_readback` | 打った後に画面を読み、 SoT と**全項目** diff してから人間に渡す |

C を省くと A と B の意味が消える。 送信可否の判断は「差分ゼロ」 を見てから人間が出す。

### サイトごとに要るもの = 実測台帳 1 枚

field 名 / 保存関数名 / 画面遷移 / 行追加関数 を **1 回実測して literal で残す** (script の docstring が定位置)。
採取は **1 コマンドで定形が出る**:

    python3 claude-config/scripts/lib/web_driver.py --probe --url <URL>

7 段 = ① login (人間) ② frame 構造 (`js_frame_probe`、 frameset なら main の index が決まる)
③ 画面 API (`js_handler_dump`) ④ field 名 (`js_field_dump`) ⑤⑥ 内部 endpoint の捕捉と読み
(`js_capture_xhr`、 [#internal-endpoint-replay](machine-route-first.md#internal-endpoint-replay) の step 1)
⑦ 語彙 (保存成功文言とエラー語)。 **⑤⑥ で endpoint が見えたら段 4 へ昇格でき、 画面 driver を書かずに済む**
(= 降りすぎの防止。 probe を先に流す一番の理由がこれ)。
**どの probe も値は返さない** — 個人情報と browser tool の出力 filter の両方を避けるため。

### どのサイトでも効く 4 つの契約

1. **element 不在は throw せず `{missing: [...]}`** — 年度差・様式改訂・種目差は「無い field」 として現れる。
   例外にすると step 列が途中で死んで原因が読めない。 missing なら次の実行で SoT に足せる。
2. **server 往復の後は待つ** — 保存 / 行追加は `lockButton` + `setTimeout` で submit することが多く、
   連続呼びは 2 回目以降が黙って捨てられる。 `audit_steps()` が wait 欠落を機械で検出する。
3. **返り値に生 HTML を混ぜない** — 出力 filter に潰される
   ([`web-tools.md#javascript-tool-gotchas`](web-tools.md#javascript-tool-gotchas))。 名前・件数・短文だけ返す。
4. **行を狙う handler は literal 一致** — `onUpdate('20260908231617499'` のような引数付き handler は
   `(` `'` を含み正規表現として壊れる。 `literal=True` で部分文字列照合に切り替える。

### 消えない人間の 4 段 (技術的限界ではなく設計上の線)

- **ログイン / 2FA** — ID/PW は agent が打たない。 画面を出して所有者が打つ
- **file upload** — page の JS はローカルディスクを読めない。 tool 側に upload 機能が無ければ人間 1 操作
- **最終送信** — 外部への不可逆操作は所有者の明示 OK が要る
- **CAPTCHA / bot 保護** — 実ブラウザ + 人の click は可、 headless 無人化はしない (回避と自動化の線)

### 採算

経路を作る価値があるのは **同じサイトを 2 回以上触る**か、 **1 回でも高リスク・多項目**のとき。
一発で項目も少ないなら ladder 5 (所有者に手順を渡す) の方が速い。 判断を先送りせず、 着手前に
「来年も打つか」 を 1 行で決める。

### 検証

`audit_steps()` が site 非依存の不変条件 (JS 構文 / 往復の wait / 生 HTML / async IIFE / JSON 化) を検査し、
harness 自身の `--selftest` は生成 JS を **node の stub DOM 上で実際に走らせて**契約 1-4 を確認する。
site 側 driver の selftest からは `audit_steps(steps)` を呼ぶだけでこの層が乗る。

初例 = 科研費電子申請システム (frameset + 引数付き保存関数 + 6 表の行追加、 2026-09-08 に実機で
往復・読み戻し・削除まで検証)。 サイト固有の台帳は
[`kakenhi-proposal.md#ai-write-route`](kakenhi-proposal.md#ai-write-route) と当該 driver の docstring。
