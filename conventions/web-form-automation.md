<!-- doc-meta
when: 過負荷・レガシー・validation の噛み合わない web サイトの入力フォームを browser automation (Chrome MCP 等) で代行するとき
category: web
summary: flaky web form 入力の一般則 — 送信結果はレスポンスページで判断しない (過負荷サイトは POST 成功後にエラーページを返す、重複確認画面 = 前回送信成功の証拠、#submit-truth-is-server-state)、公開 read API の cache による false negative (#read-api-cache-lag)、radio/checkbox は click より form_input 直接設定 (#form-input-over-click)、動的 combobox は form_input 不可、多言語ペア validation の非対称発火と「同値を両欄に焼く」回避 (#language-pair-validation)、metadata 自動取り込みの著者順 verify (#imported-metadata-verify)、リトライ規律 (フォーム状態は保存されない前提で SoT から再入力)
-->
# flaky web form への browser-automation 入力の一般則

過負荷・レガシー・validation の癖が強い web サイト (研究者 DB、行政ポータル、学会申込システム等) のフォーム入力を browser automation (Chrome MCP 等) で代行するときの、サイト非依存の一般則。個別サイトの gotcha は各層の運用 doc に置き、ここには「どのサイトでも起こる失敗形」だけを置く。

隣接 doc: [`google-forms-automation.md`](google-forms-automation.md) (= Google Forms 固有の構造解析・prefill)、[`office-automation.md`](office-automation.md) (= 様式 xlsx/PDF の file 入力)、[`data-pipeline-automation.md`](data-pipeline-automation.md)。本 file は「ブラウザ越しの対話的 form」domain。

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
