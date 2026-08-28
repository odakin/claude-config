<!-- doc-meta
when: researchmap (researchmap.jp、JST の研究者業績 DB) の閲覧・入力・自動化を扱うとき (業績調査シーズンの一括入力、論文・講演の登録代行、公開 API での確認)
category: web
summary: researchmap 固有の機構と gotcha — write 経路は実質 web UI のみ (公開 API は read-only・write API は利用申請制、#write-paths)、/settings/imports の json/csv/zip 一括インポート (#bulk-import)、論文は ORCID 連携で自動反映・手動登録は非 DOI 系と講演のみ (#orcid-autofeed)、DOI 取り込みボタンと CrossRef metadata の癖 (#doi-import)、類似データ確認画面の 4 択 (#duplicate-screen)、タイトル日本語必須 + 言語ペア validation と「同値焼き」実務解 (#title-validation)、講演の会議種別の選び方 (#presentation-category)、radio は form_input 直接設定 (#radio-quirk)、混雑・公開 API cache lag (#congestion)、/mypage は他人の permalink であって自分のポータルではない (#mypage-permalink-trap)
-->
# researchmap の機構と gotcha

researchmap (researchmap.jp、JST 運営の研究者業績 DB) を browser automation で入力代行・確認するときの、**researchmap 固有**の機構と罠。サイト非依存の一般則 (エラーページ ≠ 送信失敗、リトライ規律等) は [`web-form-automation.md`](web-form-automation.md) が正本で、本 file は researchmap での具体的な現れ方と researchmap にしかない機構を持つ。

多くの大学の教員業績システムが researchmap と連携しており (researchmap 更新 → 大学システムへの反映は日単位の遅延あり)、年度の業績調査では researchmap 側を先に整えるのが効率的。

## <a id="write-paths"></a>1. 書き込み経路は実質 web UI のみ

| 経路 | 可否 | 備考 |
|---|---|---|
| web UI (ログイン後の add/edit フォーム) | ✅ | 実質唯一の随時 write path |
| 一括インポート `/{permalink}/settings/imports` | ✅ | json/csv/zip、複数件向け (§2) |
| 公開 API `api.researchmap.jp/{permalink}/...` | read-only | 認証不要。published_papers / presentations 等を JSON で返す。**cache lag あり** (§8) |
| write API (V2、JWT client credentials) | 申請制 | 利用申請 + 審査。機関システム連携向けで、個人が即日使える経路ではない |

## <a id="bulk-import"></a>2. 一括インポート (`/settings/imports`)

「研究者・業績データ インポート」でファイル (zip / json / csv) をアップロード →「整合性チェック」→ エラーなしなら自動インポート。ファイル定義は researchmap の「仕様書類」ページ。**複数件の登録はフォーム連打よりこちらが堅い** (1 リクエストで済み、過負荷の影響を受けにくい)。単発〜数件はフォームの方が速い (ファイル定義の調査コストが上回る)。

## <a id="orcid-autofeed"></a>3. 論文は ORCID 連携で自動反映される

ORCID 連携を設定済みの研究者では、論文 (published_papers) は ORCID 経由で自動流入する (編集一覧に「自動反映」バッジ + 「登録: ORCID」表示)。**手動登録が必要になるのは自動経路に乗らないもの**:

- DOI が CrossRef 系に無い / ORCID に入っていない proceedings (例: PoS などの会議録)
- 講演・口頭発表等 (presentations) — 自動反映経路が無く、常に手動 (or インポート)
- preprint を published 前に載せたい場合

⚠️ preprint を手動登録した後に同論文が published になると ORCID 経由で別 entry が流入して二重化しうる (マージは類似データ確認 §5 で処理される場合もある)。急ぎでなければ **acceptance 後の自動反映を待つ**方が管理が楽。

## <a id="doi-import"></a>4. DOI 取り込みボタン

論文 add フォーム冒頭の「検索する DOI」に DOI を入れて「外部システムからの取り込み」を押すと、書誌が自動 populate される。ただし [`web-form-automation.md#imported-metadata-verify`](web-form-automation.md#imported-metadata-verify) の通り **registry metadata は紙面と一致しない**ことがある。researchmap で実測した具体例:

- **著者順**: PoS (Proceedings of Science) の CrossRef metadata は speaker-first で、紙面 (アルファベット順等) と違った → 出版社公式ページで verify して著者欄を直す
- **誌名**: 「Proceedings of Proceedings of the ...」の二重接頭で入ってきた → 「Proceedings of Science (PoS)」等に整形
- 巻 (PoS なら `CORFU2024` のような会議 tag) は取り込まれない → 手入力

## <a id="duplicate-screen"></a>5. 類似データ確認画面 (= 重複検出)

add の送信内容が既存 entry と類似すると「類似データ確認」画面が出る。選択肢は 4 つ:

| ボタン | 意味 |
|---|---|
| 入力データを主にマージ | 今回の入力で既存を上書きマージ |
| 類似データを主にマージ | 既存を優先してマージ |
| 入力データを強制追加 | **二重登録になる**。ほぼ選ばない |
| 編集リストへ / 再編集する | 今回の入力を破棄 / 修正 |

**この画面が出た = 前回の送信が (エラーページ表示にもかかわらず) 成功していたサイン**であることが多い ([`web-form-automation.md#submit-truth-is-server-state`](web-form-automation.md#submit-truth-is-server-state))。既存 entry (右列) の「登録日時・登録者」を見て、内容が意図どおりなら「編集リストへ」で破棄が正解。

## <a id="title-validation"></a>6. タイトル (日本語) 必須 + 言語ペア validation

- **「タイトル (日本語)」は必須欄** (アスタリスク付き)
- さらに「他の (英語) の項目を入力した場合、タイトル (英語) を必ず入力してください」型の**言語ペア validation** がある ([`web-form-automation.md#language-pair-validation`](web-form-automation.md#language-pair-validation) の instance): 講演者 (英語) など英語欄を 1 つでも埋めると英語 title が必須化する
- **英題しか存在しない業績** (英語 seminar 等) の実務解: **日本語 title 欄にも同じ英題を焼く** (+ 講演者・会議名も日英対称に埋める)。表示は英文のままで、validation を全て通過する

## <a id="presentation-category"></a>7. 講演・口頭発表等の「会議種別」の選び方

| 種別 (value) | 使い所 |
|---|---|
| 口頭発表 (招待・特別) `invited_oral_presentation` | **招待セミナー・招待講演はこれ** |
| 口頭発表 (一般) `oral_presentation` | 学会の一般講演 |
| 口頭発表 (基調) `keynote_oral_presentation` | keynote |
| 公開講演，セミナー，チュートリアル，講習，講義等 `public_discourse` | **市民向け・アウトリーチ**。研究セミナーには使わない |

「招待の有無」radio は会議種別とは独立に存在する — 招待講演は**両方**設定する (種別 = 招待・特別 + 招待の有無 = 有り)。

## <a id="radio-quirk"></a>8. radio が click に反応しないことがある

「招待の有無」等の radio は、browser automation の click が無反応になる場合がある (click 報告は成功、UI は未選択のまま)。**form_input による値の直接設定 (radio へ `true`) が確実** ([`web-form-automation.md#form-input-over-click`](web-form-automation.md#form-input-over-click))。送信前に screenshot で選択状態を目視確認する。

なお「記述言語」「国名」等の**動的 combobox は form_input 不可** (options が JS populate)。任意項目なので skip して良い。

## <a id="congestion"></a>9. 混雑と確認の作法

- 「アクセスが集中しております」ページが頻発する (特に年度の業績調査シーズン = 7 月下旬〜8 月)。**POST 成功後にこのページが返ることがある** → 送信成否は必ず `/{permalink}/published_papers/edit` 等の**編集一覧** (件数 + 「登録: 本人 HH:MM」表示) で確認
- 公開 API (`api.researchmap.jp`) は cache lag があり、UI 一覧に出ている entry が API に数十分現れないことがある ([`web-form-automation.md#read-api-cache-lag`](web-form-automation.md#read-api-cache-lag))。**API 不在を理由に再送信しない**
- `/add` への直接 navigate は未認証・混雑時に一覧へ redirect されることがある。フォームが出るまで wait + 再 navigate (10〜60 秒の波)

## <a id="mypage-permalink-trap"></a>10. 「/mypage」は自分のページではない

`researchmap.jp/mypage` は**「mypage」という permalink を取得した一般研究者の公開プロフィール**であって、ログイン中の自分のポータルを指す永続 URL ではない (実測 2026-08-29: 別分野の研究者ページが表示され「別人アカウントでログイン済み」と誤認しかけた)。自分のページ・編集画面へは `researchmap.jp/{自分の permalink}/…` か、トップページのログイン後 UI から入る。**ログイン状態の判定は編集系 URL への navigate で行う** (`/{permalink}/presentations/edit` 等は未ログインならログイン画面へ redirect する = redirect の有無が判定になる)。公開プロフィールの表示はログイン状態について何も語らない。
