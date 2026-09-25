<!-- doc-meta
when: Cybozu Garoon (サイボウズ Garoon) の掲示板・ファイル管理・ポータルを読む/探すとき + ワークフローを再利用・作成・申請するとき + 申請した後の承認・差し戻し・コメントを script で確かめるとき (#garoon-workflow-status-read) + login 切れで読めないとき / SSO 保護サイトの login 切れからの復帰を組むとき (#garoon-session-recovery)
category: infra
summary: Garoon cloud の自動化 (= SSO でも logged-in session 越しに読める、 read は cookie 再利用 script が第一選択、 login 切れは browser に開かせた tab の行き先を見て復帰・本人のログインが要る時だけ頼む、 workflow write は承認済み申請再利用 → 値の全読み戻し → 経路確認 → owner 明示 OK → 送信一覧検証、 download token の期限切れ = login page 化)
-->
# Cybozu Garoon の自動化

日本の組織で広く使われる groupware **Cybozu Garoon** (cloud 版 = `https://<org>.cybozu.com/g/`) を AI から扱うときの機構 fact 集。SSO (Shibboleth 等) 保護でも、user の logged-in browser session を介して read/write 経路は作れる — 「SSO だから AI 経路無し」と pre-conclude しない。**read は cookie 再利用 script が第一選択**、**workflow write は現時点でログイン済み browser + site driver**。file 取得は別権限帯 ([web-tools.md#browser-download-automation](web-tools.md#browser-download-automation))。

## <a id="garoon-script-route"></a>第一選択 = script 経路 (browser session cookie 再利用、 画面 drive 不要)

SAML-only 組織では REST の password auth が admin 限定・OAuth client も admin 登録要 = user 側で発行できる credential が無い。 残る機械経路 = **user が browser で login 済みの session cookie を script が再利用する**: [`scripts/chromium-cookies.py`](../scripts/chromium-cookies.py) (macOS Keychain "Brave Safe Storage" → AES-128-CBC 復号、 Chromium 130+ の SHA-256 prefix 対応) + [`scripts/garoon-client.py`](../scripts/garoon-client.py) (全文検索 / 掲示板 REST / 添付 download / 任意 GET)。 2026-09-07 実測 (Garoon 6.31 cloud):

| 操作 | 機構 |
|---|---|
| 全文検索 (= UI の検索 box と同じ) | `POST /g/fts/api/search?csrf_ticket=<t>` + JSON `{"keyword","apps":["bulletin"\|"cabinet"],"start"}`、 cabinet は `cabinetFolderId:"1"` + `fileOnly:true` 必須 (無いと `GRN_FTS_00001` 520)。 応答 `result.docs[]` = title / url / snippet / modifiedTime / file{title,downloadUrl,size} |
| csrf ticket | `/g/cabinet/search.csp` 等の inline `grn.__PRELOADED_DATA__.csrfTicket` (portal は 302 なので注意) |
| 掲示板 REST | `GET /g/api/v1/bulletin/categories` 等、 cookie + `X-Requested-With: XMLHttpRequest` で session auth |
| 添付 download | `GET /g/bulletin/file_download.csp/-/<name>?fid=F` は session 内 GET で 200 (application/pdf)。 cabinet の `download.csp/-/<name>?fid=F` も session 内 GET で 200 (application/pdf) = UI が付ける time= token は要らない (実測) |
| login 切れ | 302 → `<org>.ex-tic.com` (SSO) / **302 → `<org>.cybozu.com/login?redirect=…` (cybozu 自身の login)** / login page HTML / REST API の 401 `GRN_REST_API_00003` → 下の [#garoon-session-recovery](#garoon-session-recovery) を 1 回試し、 だめなら user が browser で 1 回 login (script はパスワード・OTP を代行しない)。 ⚠️ 死活検査で「SSO への 302 だけ切れ、 他の 302 は健全」 と書くと、 自前 login への 302 で切れているのに silent になる (実測) 。 ⚠️ **login 直後は browser が cookie DB (SQLite) に新しい session cookie を書くまで遅れがある** (数秒〜30 秒ほどで一定しない、 下の「Garoon 固有の実測」) = login の直後に 1 回目の検査が「切れ」 のままでも、 少し待って読み直す |

### <a id="garoon-session-recovery"></a><a id="garoon-browser-reauth"></a>login 切れからの復帰 (手順)

Garoon のセッション切れは 2 層ある: **Garoon 本体のセッション** (JSESSIONID) と **IdP のログイン** (SSO 側)。 本体だけが切れていて IdP が生きていれば、 browser で Garoon を開くだけでパスワードも OTP もなしに入り直せる。 IdP も切れていれば本人のログインが要る。 `garoon-client.py` は切れを見た時、 次の順で 1 回だけ復帰を試す:

1. **手元の cookie が古いだけ**なら読み直す (browser は既に入り直していて、 cookie DB への書き出しが遅れていた場合。 browser には触らない)。
2. `--browser-refresh keep|close` (env `GAROON_BROWSER_REFRESH`) を指定していれば、 **起動中の** browser に tab を 1 枚、 裏で開かせる (AppleScript。 前面の tab は開いた直後に元へ戻し、 browser を前面に出さない。 起動していなければ何もしない)。 そのうえで **tab の行き先を見る**:
   - cookie DB が変わった、 または Garoon の中に着いた → cookie を読み直し、 **server が受け入れた時だけ**入り直せたとして撃ち直す (GET 1 本で確かめる)。 `close` なら自分が開いたその tab を閉じる。 受け入れられなければ tab を見続ける。
   - Garoon の外 (ログイン画面) で数秒止まった = **本人のログインが要る** → exit 75。 `close` ならそのログイン画面の tab も閉じる (失敗のたびに tab が溜まらない)。

   <a id="login-page-mints-session-cookie"></a>⚠️ **cookie DB が変わった ≠ 入り直せた**: Garoon のログイン画面 (`/login`) は開かれるたびに**未認証の** JSESSIONID を配る (実測、 cookie なしで `/g/` に来た時の 302 も配る)。 IdP が切れていても、 browser がログイン画面を通るだけで cookie DB は変わる。 変わったことを「入り直せた」 と読むと、 未認証の cookie で撃ち直して失敗し、 本人のログインが要ることも言えない (実例: 「入り直した (11 秒)」 の直後に「復帰できなかった」、 exit 75 の案内が出ない)。 cookie DB の書き出しが速い時ほど、 ログイン画面で止まるのを見届ける前にこの cookie を掴むので、 機械・時刻によって出たり出なかったりする。 SAML が済むと同じ cookie のまま認証済みになることもある (= その後 DB は変わらない) ので、 未認証の cookie を掴んだ後は間隔を空けて確かめ直す。
3. 本人のログインが要る時は、 agent が user に 1 行で頼み、 同じ command を `--wait-login <秒>` つき (subcommand の前でも後でも効く) ・background で実行し直す。 ログイン画面の tab が開いたままになり、 本人がログインし終えたら続きから進む (= user は「終わった」 と報告しなくてよい)。 本人がログインに使った tab は閉じない。

**設計の要点と理由 (見積もらずに見る / 通常の周期を警告にしない / IdP を延命しない / browser に触る副作用は opt-in / 既存の tab を使い回さない / browser の中で読む経路に寄せない理由) の正本 = [`machine-route-first.md#sso-session-recovery`](machine-route-first.md#sso-session-recovery)** (別の SSO 保護サイトで同じ形を組む時もそこから)。 復帰の部品 = [`scripts/lib/sso_cookie_session.py`](../scripts/lib/sso_cookie_session.py) (tab の駆動 = [`scripts/lib/browser_tab.py`](../scripts/lib/browser_tab.py))。

利用者の入口は数行の wrapper で足りる (org と流儀を 1 箇所で決める。 組織名を含むので private 層に置く):

```bash
#!/usr/bin/env bash
exec env GAROON_ORG=<org> GAROON_BROWSER_REFRESH="${GAROON_BROWSER_REFRESH:-close}" \
  python3 "$HOME/<base>/claude-config/scripts/garoon-client.py" "$@"
```

Garoon 固有の実測:

- Garoon を開いたままの tab は、 ページ移動なしに裏の通信で JSESSIONID を差し替えることがある (理由は未確認)。 script は起動時に読んだ cookie を長く持ち続けず、 実行のたびに読み直す。
- Chromium の cookie DB 書き出しの遅れは一定しない = 数秒で出ることも、 30 秒ほどかかることもある (実測)。 遅い側では login 直後の 1 回目が「切れ」 に見え、 速い側ではログイン画面が配った未認証の cookie が認証より先に DB に出る。 どちらも書き出しの速さで結末を決めず、 server に確かめて決める ([#login-page-mints-session-cookie](#login-page-mints-session-cookie))。
- 本体セッションの寿命を測るときは、 途中で IdP をログアウトしないこと (ログアウト後に切れていても寿命の証拠にならない)。
- 切れ方の採取 = client の `probe` (cookie なし・偽の JSESSIONID で `/g/` 等を撃つ。 未認証の JSESSIONID を配ることと、 `expired()` が全部を切れと判定することがその場で見える)。 復帰の途中を見る = `--trace` (実測: `/g/` → IdP の assertions → `/saml/acs` → `/g/index.csp` と進み、 cookie DB の更新は tab が中に着いてから数秒後)。
- 死活監視は `doctor` (配線だけ・network なし) に留める。 `status` は読む前に 1 回だけ (user が席を外す前に、 ログインが要るかをその場で知るため)。

⚠️ **`search.csp` の HTML 自体は結果を含まない** (JS が上の API を叩いて描画、 no-data 文言は template に常在) — HTML を grep して「0 件」 と結論しない。 browser MCP の `get_page_text` も描画前に読むと同じ罠。
⚠️ 「規程集」 のような**外部 site への link** (= Basic 認証の別 host) は cookie 再利用の射程外 = ID/PW は user 専権 (script も agent も入力しない)。

## <a id="garoon-workflow-write"></a>Workflow write = 承認済み申請の再利用 + 3 段照合 + 送信一覧検証

`garoon-client.py` の現行射程は **read / search / download / 任意 GET** で、workflow の作成・送信は持たない。
近い将来の write を「GET があるから script で送れる」と拡張解釈せず、公開 API / 内部 endpoint replay を実測で構築するまでは
**ログイン済み browser の form 経路**を使う。同じフォームを反復するなら、クリック手順を毎回再現せず
[`web-form-automation.md#step-driver-harness`](web-form-automation.md#step-driver-harness) の site-specific driver にする。

**安全な再利用手順**:

1. **値の SoT を画面の外に持つ**: 日付・金額・会場・備考・人数等を project/case 側 YAML に置く。画面の一時状態と SESSION は正本にしない。
2. **同フォームの直近承認済み申請を開く**: 詳細画面の「再利用して申請する」は、新規申請画面へ正しい form / path を持ち越す最短経路。ただし「過去に承認された」は現在値の正しさの証拠ではない ([`#acceptance-is-not-specification`](../docs/convention-design-principles.md#acceptance-is-not-specification))。
3. **内容入力 → 経路設定 → 内容確認を3段として扱う**: 再利用値は SoT で全て上書き、radio/checkbox は click でなく値を直接設定。経路画面で step 名と処理者を読み、確認画面で全項目を SoT と diff する。
4. **最終送信は owner の明示 OK 後に 1 回だけ**: 提示は少なくとも申請者・標題・日時・主要値・備考・添付の有無・処理経路を含む。承認前に「申請する」を押さない。
5. **成功画面で閉じない**: 申請後は「送信一覧」を開き、新しい行の **申請番号 / フォーム名 / 標題 / 状況 / 現在の処理者 / 申請時刻**を確認する。レスポンス画面でなく server-side list が成否の正 ([`web-form-automation.md#submit-truth-is-server-state`](web-form-automation.md#submit-truth-is-server-state))。
6. **ID と現在地を case SoT に回収する**: 申請番号・内部 pid・送信時状態・URL を案件側に保存。workflow は申請時点で閉じず、承認 / 差し戻し / 取り消しの終端まで追う。

<a id="garoon-workflow-form-quirks"></a>**画面で入力するときの罠** (driver の無いフォームを browser MCP で埋めるとき、実測):

- **「申請する」 の 1 回目の click で画面が変わらないことがある**。押し直す前に**別 tab で送信一覧を開き、新しい行が無いことを確かめてから**押し直す (= 押し直しは二重申請の入口。結果画面でなく server 側の一覧が成否の正、上の 5. と同じ)。
- **入力欄の name は `item_<数字>`** (日付は `_year` / `_month` / `_day` / `_hour` / `_minute` の 5 つに分かれる)。label は同じ行の `th` から引いて対応表を作ってから値を入れる。
- **select は値を入れたら `change` を発火する**: 年・月を変えると日の選択肢 (曜日つき) が作り直される。年 → 月 → 日の順に入れ、最後に表示文字列を読み戻す。
- **browser MCP の JS 実行結果は、cookie や query string らしい文字列を含むと丸ごと伏せられる** (同一 origin への fetch の結果を返す等)。一覧や結果は page text の取得で読み、JS は「name と値だけ」 を返す形にする。
- 「実施日」 のような radio (指定あり / 指定なし) は、前回承認された申請の選択をそのまま引き継いで、隣の日付欄の値も通ることがある。どちらを選ぶかは値の SoT 側で決め、画面の既定に任せない。

<a id="garoon-workflow-status-read"></a>**申請後の状態を script で追う (read、 実測)**: 承認 / 差し戻し / コメントは全文検索に出ず (下の「App 別 URL」 の ⚠️)、 通知メールも来るとは限らない。 `garoon-client.py get` で読む:

1. `get "/g/workflow/index.csp"` の HTML の左メニューに、 最新一覧 / 受信一覧 / 送信一覧 / 下書き の `index.csp?fid=<N>` link が並ぶ (fid の値は組織ごと = 一度読んで案件側の台帳に写す)。 `send_list.csp` のような推測 URL は存在しない (エラー FW00051)。
2. 送信一覧 `get "/g/workflow/index.csp?fid=<送信一覧>"` の HTML には申請ごとに `view.csp?fid=<N>&pid=<内部 id>` の link が 2 本 (フォーム名と標題) 出る。 **`pid` は内部 id で、 画面に出る申請番号 No. とは別の数**。 申請直後に手順 6 で両方を回収しておくと、 後で一覧を引かずに済む。
3. `get "/g/workflow/view.csp?fid=<N>&pid=<内部 id>"` が申請内容と進行状況 (経路 step ごとに 結果 / 日時 / 処理者 / コメント) を持つ。 HTML なので `<script>` / `<style>` を落として tag を剥がしてから読む。 **未処理の判定** = 担当 step に結果と日時が無く、 画面に「申請を取り戻す」 が出ている。 担当課の「貸出は N 週間まで」 のような条件は承認のコメント欄に書かれるので、 結果だけでなくコメントまで読む。 ⚠️ **一覧の状況「進行中」 は未承認の意味ではない** (実測): 担当課の step が承認済み (コメントに「予約済み」 等) でも、 後段の決裁者や回覧が残っている間は一覧に「進行中」 と出続け、 それが数日続く。 用件が成立したかは一覧の状況語でなく、 担当課の step の結果とコメントで判断する。

**接続の実務**: 自動選択が未 login の in-app browser を開く一方、同じマシンの external Chromium に SSO session が残っていることがある。その場合は再 login の前に接続済み browser 一覧を取り、最新のログイン済み tab を claim する。画面 title/URL の一時的な「ログイン」表示で判定せず、DOM 内の user 名 / portal / workflow を読んで session 実状態を判定する。

## App 別 URL (= browser MCP で読むときの入口。 script 経路が使えない環境向け)

| app | URL | 備考 |
|---|---|---|
| ポータル | `/g/index.csp` | 掲示板の新着数件・通知一覧が 1 ページに出る = 巡回の入口 |
| 掲示板 | `/g/bulletin/index.csp` | ルート category は空に見える (= 掲示は subcategory 配下) |
| **掲示板 検索** | `/g/bulletin/search.csp?cid=1&text=<urlencoded>` | **本文全文検索**。 keyword で掲示 + 添付 PDF 内文まで hit する |
| ファイル管理 | `/g/cabinet/index.csp` | 各種申請書・様式の配布場所 |
| **ファイル管理 検索** | `/g/cabinet/search.csp?text=<urlencoded>` | file 名 + **file 内文**を検索 (= doc/pdf の中身も hit) |
| file download | `/g/cabinet/download.csp/-/<name>?fid=<N>&time=<token>` | ⚠️ 下記 token 期限 |
| **施設予約** (スケジュール内) | `/g/schedule/facility_index.csp` | 施設のグループ週表示。 施設の存在確認は左上の施設グループ dropdown か「ユーザー/施設」検索 box |
| **ワークフロー** | `/g/workflow/index.csp` | 申請・送信一覧・受信一覧・下書き。write は [#garoon-workflow-write](#garoon-workflow-write) |

- ページ内検索 box への type は UI 状態依存で空振りしやすい — **search.csp への直 navigate が確実**。
- ⚠️ **全文検索 (`/g/fts/search.csp`) の scope は掲示板 + ファイル管理のみ** — 施設予約・スケジュール・ワークフローは hit しない (結果ページ自身が「その他のアプリケーションは各アプリケーション内から検索」 と明記)。 fts の 0 件を「施設が存在しない」 等の absence 証明にしない (= scope 違いの null)。 施設の不在を言うには施設予約画面の施設リスト側で確認する。
- ⚠️ **組織の敷地内にある建物でも、 運営主体が別法人 (同窓会・生協・組合会館 等) の施設は Garoon の施設リストに載らない**ことがある — 「リストに無い = 予約不能」 でなく、 別系統 (当該法人の事務局への電話等) を疑う。
- 検索結果は掲示/file の **snippet 込み**で返るので、 get_page_text だけで内容の大半が取れることが多い。

## Download token の期限切れ (= 200 + login page)

`download.csp` の URL は **`time=` 署名 token 付きで短時間で失効**する。 失効後の fetch は error でなく **HTTP 200 + login page HTML** (数 KB) を返す = サイズと `<title>ログイン</title>` で判別。 検索結果ページを reload して fresh な token を取り直してから扱う。 file の実取得自体は scripted download が silent block されるため [web-tools.md#browser-download-automation](web-tools.md#browser-download-automation) の fallback ladder (user click / cloud 共有リンク / メール添付) で運ぶ。

## <a id="garoon-wiring-gap"></a>接続が通らない時 (= 配線 gap、 「読めない」 で終えない)

`navigate` は通るのに `get_page_text` / screenshot が `Permission denied for reading page content on this domain` を返すのは **Garoon 側の制限ではなく browser 拡張側の配線** (= [web-tools.md #chrome-domain-permission-model](web-tools.md#chrome-domain-permission-model) の 2 層目 = AI-driven domain allow-list、 または stale 接続)。 切り分け順 = ① `list_connected_browsers` が 2 本以上なら `connectedAt` 最新を `select_browser` ② それでも denied なら user のサイドパネルに出ている「Permission required: <org>.cybozu.com」 で **Always allow** を押してもらう ③ prompt が出なければ既知 render バグ → 同 doc の workaround。 **配線状態は機械 × account ごとに違う** (= 片方のマシンで実証済でも他方では未許可) ので、 通した機械を personal 層の環境 doc に表で残す。 一般則 = [machine-route-first.md #wiring-gap-is-a-task](machine-route-first.md#wiring-gap-is-a-task)。

## 運用上の含意

- **「掲示板にしか出ない告知」 は mail 監視の構造的圏外** — 制度の募集 (期限付き機会) や全社通知は Garoon 掲示板が一次 channel のことがある。 不在主張 (「告知されていない」) の前に掲示板検索を回す。
- **ワークフローの承認・差し戻しも mail 監視の圏外になりうる** — 組織の通知設定によっては承認の連絡がメールに来ず Garoon の中にだけ出る (実測)。 mail の null で「まだ承認されていない」 と結論しない。 承認待ちの案件を「返事待ち」 として mail の着信に任せて寝かせず、 見に行く日を決めて [#garoon-workflow-status-read](#garoon-workflow-status-read) で読む。 一般則 = [convention-design-principles.md#absence-channel-coverage](../docs/convention-design-principles.md#absence-channel-coverage)。
- 掲示は**掲示期間**付き (= 期限後に消える)。 重要な掲示は本文を自リポの SoT に転記してから参照する。
- 組織固有の value (= subdomain / どの app に何があるか / folder 構成) は private 層に書く — 本 doc は機構 fact のみ。
