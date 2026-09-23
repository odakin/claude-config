<!-- doc-meta
when: 外部 service / アプリを操作・データ取得する経路を選ぶとき (画面 drive を検討し始めた瞬間) + browser の cookie を再利用する script が login 切れで止まる・本人が毎回ログインに呼ばれるとき / ログインの切れを予告・監視しようとしたとき (#sso-session-recovery)
category: harness-core
summary: 経路 ladder (dedicated MCP → API 直 → CLI → 経路を実装 → user 依頼 → 画面 drive) — 画面 drive は最終手段で、経路が無いときは「実装するのが先」 (#build-the-route-first = 実装した経路を auto-load 面に記録するまでが 1 単位)。 画面 drive の 3 重コスト (unreliable click / user のマシン拘束 / 対象取り違え) と許容例外。 **他人 owner の共有 document (sheet / form / doc) への書込は画面 drive 禁止級** (#shared-document-write = blast radius が自分の外、 xlsx は API in-place update、 native Sheets は Sheets API、 経路が無ければ user 依頼が先)。 公開 API の無い web app は #internal-endpoint-replay (= XHR hook で UI 操作 1 回を捕捉 → 同 endpoint を page context から叩く → rules/dry-run/apply → reload で確認)
-->
# 機械経路 first (画面 drive は最終手段)

外部 service やアプリへの操作・データ取得には大抵複数の経路がある。 agent は「自分の手で画面を動かす」 (= computer-use / ブラウザ拡張の UI 操作) に流れやすいが、 それは**最弱の経路**であり、 選択には順序がある。

## <a id="route-ladder"></a>経路 ladder

上から順に検討し、 上位が使えるなら下位に降りない:

1. **dedicated MCP** — 対象 service 専用の MCP が繋がっているならそれ (API-backed で速く正確)
2. **API 直叩き** — 公式 HTTP API を curl / Python stdlib で。 token 整備が未了でもここで止まって下に降りず、 #build-the-route-first へ
3. **CLI** — 公式 / 定番 CLI tool
4. **経路を実装する** (= #build-the-route-first) — 1〜3 が存在しないなら、 画面に進む前に**経路を作る**
5. **user 依頼** — one-off で実装が割に合わない時のみ。 平文手順を渡して user に操作してもらう (実 UI の確認・操作は所有者が最速)
6. **画面 drive** — user が**その対象について「画面でやって」** と言った時、 または 1〜5 が全滅の時のみ。
   ⚠️ ここに落ちたサイトを**繰り返し**打つなら、 手動 click を重ねずに操作列を生成物にする
   ([`web-form-automation.md#step-driver-harness`](web-form-automation.md#step-driver-harness) = 値の正本 → steps → 読み戻し照合)。 ⚠️ user の「見て」「やって」「任せる」 は経路の指定ではない (= 上位で実行せよの意) — それを GUI 許可と読むのが最頻の滑り方 (実例 2026-08-21 / 2026-09-05)

## <a id="screen-drive-costs"></a>画面 drive が最下位である理由

- **unreliable**: click 精度・画面読みは API 応答より誤りやすく、 対象取り違え等の error が混入する
- **user のマシンを拘束する**: drive 中 user は自分の環境を使えない。 この拘束コストは操作が成功しても常に発生する
- **遅い**: screenshot round-trip の積み重ねは API call の数十倍かかる

許容される例外は **read-only の screenshot で状態を確認するだけ**の場合 (それも API / export で読めるなら API) と、 user が対象を指して画面操作を明示した時。 GUI の見え方確認はそもそも user に依頼する方が速い ([`office-automation.md` visual-check-by-user](office-automation.md#visual-check-by-user))。

## <a id="build-the-route-first"></a>build-the-route-first (経路が無ければ実装が先)

MCP / API / CLI の経路が**存在しない**と分かった時、 それは画面 drive に降りる理由ではなく**経路を実装する trigger**。 経路の実装は scope creep ではなく task の一部 — one-off の画面操作は消えるが、 実装した経路は以後のすべての session の資産になる。

実装の分業:

- **agent 側**: script / API wrapper の実装、 token の保管設計 (暗号化 + cross-machine 同期)、 冪等化、 selftest
- **user 側に切り出すのは認証境界だけ**: developer console での app 作成、 OAuth consent の Allow click 等、 agent が代行してはならない部分。 手順を番号付きで渡し、 済んだら agent が続きを引き取る

**実装した経路は auto-load される記憶面 (CLAUDE.md の scripts index 等) に記録するまでが 1 単位** — 経路は「次の session が見つけられる」 ことで初めて画面 drive を置換する。 記録がなければ次の session は再び画面に流れる。

OAuth を伴う実装では loopback consent の hardening 4 点 set ([`google-api-direct-access.md` oauth-loopback-hardening](google-api-direct-access.md#oauth-loopback-hardening)) を最初から適用する。

## <a id="wiring-gap-is-a-task"></a>配線 gap は task の一部 (= 経路が「あるはずなのに通らない」 時も、 諦めて scope 外にしない)

#build-the-route-first の姉妹。 あちらは**経路が存在しない**時の話、 こちらは**経路は存在するがこの機械・この account・この domain で配線が通っていない**時の話 (= MCP 未登録 / 拡張の domain allow-list 未許可 / stale 接続 / token 失効 / credential が別マシンにしか無い)。 どちらも「画面 drive に降りる」「未 verify と書いて終わる」 の理由にならない。

**規律**: 配線 gap を踏んだ turn で、 次の 3 つを同 turn 内に済ませるまで「未確認」 報告に降りない:

1. **診断**: どの層で落ちたかを既存 runbook で切り分ける (= browser 拡張なら [web-tools.md #chrome-domain-permission-model](web-tools.md#chrome-domain-permission-model) の 2 層 + stale 接続 / MCP なら [mcp.md #runbook-root-cause-checklist](mcp.md#runbook-root-cause-checklist))。 「Permission denied」 1 行で scope 外宣言しない。
2. **修復 or 最小 user 手順**: agent 側で直せる段 (= `select_browser` で最新接続を掴む / 拡張 toggle / token 再取得 / MCP 再登録) は自分で回す。 user にしか押せない段 (= allow-list の「Always allow」 click / OAuth consent / 拡張の再ログイン) は **番号付き 1 画面**で渡し、 押されたら同 turn で続きを引き取る。
3. **carrier + 記録**: 同 turn で閉じなければ、 配線完成を運ぶ TODO (user_action 付き) を立て、 **機械別の配線状態を personal 層の環境 doc に表で残す** (= 「iMac は通る / MacBook は allow-list 未許可」 のように。 どの機械で通るかは次の session が最初に見る事実)。 配線が通ったら同 doc を更新するまでが 1 単位。

<a id="agent-browser-login-is-not-a-gap-verdict"></a>**agent 専用の browser でログイン画面が出たのは、 経路が無い証拠ではない**: 内蔵の Browser pane など agent が開く browser は user のログインを持っていない。 そこでログイン画面が出ても「この pane が未ログイン」 というだけで、 user の browser には同じ IdP のログインが生きていることが多い。 パスワードを打てないからと「読めない」 で止めず、 同じ IdP の別サイトで cookie 再利用の経路が通っているか ([`garoon.md#garoon-script-route`](garoon.md#garoon-script-route)) を見て、 同じ部品で降りる (実測: 教務システムのシラバスがこれで 1 turn で読めた = [`campussquare.md`](campussquare.md))。

**なぜ**: 配線 gap は再発する (= 機械 × account × domain の組合せごとに 1 回ずつ踏む)。 1 回目に「未 verify」 で流すと、 次の session も同じ gap で同じ scope 外宣言をし、 経路は永久に通らない。 gap を踏んだ瞬間が最も安く直せる (= 症状が目の前にある)。 これは努力目標であって強制 gate ではない — ただし「未確認」 と書く前に 1-3 を回したかを自問する floor。

## <a id="shared-document-write"></a>他人 owner の共有 document への書込は画面 drive しない (= blast radius が自分の外)

ladder 6 (画面 drive) の中でも、 **他人が owner の共有 document** (= 主任が配る「各自記入」 sheet、 committee の集計表、 共同編集 doc / form の回答欄) に**値を書く**操作は別格に扱う。 自分の file なら画面 drive の失敗は自分の損で済むが、 共有 document では **1 回の誤 click が他人の記入・見出し・注記を上書きし、 気づかれないまま集計に流れる**。 read-only の画面確認 (screenshot で状態を見る) は従来どおり許容、 **書込だけは画面でやらない**。

画面 drive の書込が壊れる機構 (2026-09-05 実測、 Google Sheets の Office 編集 mode):

- **focus の取り違え**: name box / 数式 bar への click が cell 選択に化け、 続く `type` が active cell (= 注記行・見出し行) を上書きする。 range 選択 (cmd+a) が sheet 全体に効く等、 keyboard shortcut の効き先も画面状態で変わる
- **先頭 keystroke の欠落**: cell 選択直後の type は edit mode 遷移中に先頭数文字が食われ、 **部分的に正しい値** (= 一見それらしい) が保存される。 名前 cell が空・規則文の先頭欠け、 の形で残った
- **画面が保存済 truth を映さない**: screenshot は scroll 前の stale 画像を返し、 autosave は数十秒遅れ、 undo が「保存済か」 は画面から分からない。 verify は API で保存済 revision を読む以外に無い
- 救えたのは **undo (= revision に残る)** と、 API 側の revision 履歴 — つまり回復手段は最初から API 側にあった

正しい順序 (ladder をこの class に特化):

1. **対象の形式を先に判定** — native Sheets → Sheets API (`values.update`)、 xlsx を Drive に置いたもの → [`google-api-direct-access.md #drive-xlsx-inplace-update`](google-api-direct-access.md#drive-xlsx-inplace-update) (= revision download → 編集 → `files.update` → 再 download verify)、 Form → Forms API か user 依頼
2. **token の scope が足りなければそこで止まって #build-the-route-first** (= `drive.file` は他人 owner の file に無力、 full `drive` を**別 token** に分離して 1 回 consent)。 「認証は user、 操作は agent」 の分業で、 consent click だけ user に渡す
3. 経路が作れない (= API が無い / 権限が出ない) なら **ladder 5 (user 依頼) を画面 drive より先に**提案する — 所有者本人の 1 分の操作は、 agent の画面 drive より速くて安全
4. 画面 drive に降りるのは user が「画面でやって」 と**この対象について**明示した時だけ。 その場合も 1 cell ずつ・書く前に name box を zoom で verify・書いた後は API で保存済 revision を読む

## <a id="internal-endpoint-replay"></a>公開 API の無い web app: 内部 endpoint 再現 (= ladder 4 の一形態)

公式 API も CLI も無い web app (家計簿 SaaS 等の消費者向け web app に多い) でも、 **UI が裏で叩いている内部 endpoint を、 ログイン済み page の context から同じ形で叩く**経路は大抵作れる。 画面 drive (座標 click・dropdown 開閉・スクロール) より速く、 行数・レイアウトに依存せず、 dry-run が自然に組める。 認証は browser session (cookie) をそのまま使うので token 整備が不要 = 「ログインだけ user、 操作は agent」 の分業がそのまま成立する。

recipe (家計簿カテゴリ一括修正で確立):

1. **推測で組まず、 実 UI 操作 1 回分を捕捉する** — page context で `XMLHttpRequest.prototype.open/send/setRequestHeader` と `fetch` を一時 hook し、 対象操作を **1 回だけ・冪等な値で** (= 現在値を再選択する等) UI から実行して method / URL / header / body の field 名を取る。 method 違い (POST vs PUT) や encoding 違い (multipart vs urlencoded) は 404 で沈黙するので、 捕捉なしの試行は時間を溶かす。 CSRF token は `meta[name=csrf-token]` 等から取り、 log には残さない (`<redacted>`)。
2. **id の類は DOM から実行時に解決する** (カテゴリ id ↔ 名前 等)。 hard-code すると相手側の変更で silent に別物を書く。 menu が lazy 生成 (一度開くまで DOM に無い) / 行の種別で中身が違う (支出行と収入行) といった罠は実測で潰す。
3. **rules → dry-run → apply の 3 段**: 変更対象を宣言的 rules (店名 regex → 目標値) で与え、 既定は dry-run で対象行を全部列挙、 user が読んでから apply。 rules は**具体名の列挙**にする — 業種語だけの regex (「薬局」) はドラッグストアを巻き込む (実測: 3 件誤変更 → 即 revert)。 巻き込み範囲は処理月数に比例して増える。
4. **書いた後は再読込して実状態を読む** — 自前 `fetch` の応答 (UI が eval する前提の JS 等) は画面を再描画しないので、 DOM の旧値を見て「変わっていない」 と誤診しない。 サーバ session が表示状態 (月等) を保持していれば reload 後も同じ画面に戻る。
5. **agent の browser tool の制約に合わせる**: 1 call の timeout (45 s 級) を超えないよう処理単位を分割 (timeout 後も page 内 script は走り続ける = 同値 PUT の冪等性で二重実行を無害化)、 出力は tool 側 filter に掛からない形で返す (詳細 = [`web-tools.md` javascript_tool gotcha](web-tools.md#javascript-tool-gotchas))。
6. **rules の正本と tool は別 file** に置く (rules は個人情報を含みうる → 暗号化側、 tool は平文で公開可能)。 auto-load 面への記録は #build-the-route-first と同じ。

線引き: これは **user 本人の session で user が UI からできる操作を、 同じ endpoint で機械化するだけ** (= 所有者権限の範囲内)。 bot 保護の回避・無人化・他人のデータ・利用規約が禁じる自動取得には使わない (#実例 2026-08-28 の注と同じ線)。

<a id="read-only-endpoint-discovery"></a>**読むだけなら捕捉は要らない** (実測): 画面が店や条件を選ぶまで値を出さない SPA (注文サイトのメニュー価格など) で、 公開されている値を一覧で読みたいだけのときは、 上の recipe 1 の hook を仕掛けなくても降りられる。

- **URL**: page を 1 回開いた後、 page context で `performance.getEntriesByType('resource')` を読み、 `xmlhttprequest` / `fetch` の URL を並べる。 分析 tag を除けば、 一覧の API はすぐ見つかる
- **header**: そのまま `fetch` すると「client が要る」「言語が要る」 で 400 になることがある。 値は app の bundle の中にある (axios なら `defaults.headers.common.<名前> = "…"` を grep)。 これは全訪問者の browser に配られる公開の識別子で、 本人の認証情報ではない
- **条件の切替**: query の 1 つ (宅配 / 持ち帰り、 店の code) を変えて取り直すと、 画面で選び直さずに別の条件の値が並ぶ。 店の code を変えても値が同じなら「全店共通」 と言ってよいが、 **その code がどの店かは別に確かめる** (id の見た目で店を推測しない)
- **線引き**: 誰でも画面で見られる値を、 画面と同じ頻度で読むだけにする。 認証の要る data・大量取得・定期巡回には使わない

## <a id="session-cookie-reuse"></a>credential を発行できない web app: browser session cookie の再利用 (= ladder 4 のもう 1 形態)

#internal-endpoint-replay は「ログイン済み page の context から叩く」 = browser MCP がまだ要る。 もう一段上が **browser の session cookie を script 側に持ち出して、 browser も拡張も無しに HTTP を撃つ**経路。 SAML/SSO-only の groupware・学内 portal のように「API の password 認証は admin 限定 / OAuth client は admin 登録要 / user が発行できる token が無い」 環境で、 残る唯一の機械経路になる。

recipe (2026-09-07 Cybozu Garoon で確立、 部品 = [`scripts/chromium-cookies.py`](../scripts/chromium-cookies.py) + [`scripts/garoon-client.py`](../scripts/garoon-client.py)):

1. **cookie は browser の暗号化 DB から復号する** (macOS Chromium 系 = sqlite `Cookies` を copy → Keychain "<Browser> Safe Storage" → PBKDF2 → AES-128-CBC、 Chromium 130+ は host_key SHA-256 prefix)。 **Keychain 読み出しの初回 dialog だけが user 段** (= 「常に許可」 で以後 silent)。 password も token も新たに発行しない = 認証境界を増やさない。
2. **API の形は JS を読んで復元する** — search box が叩く endpoint (`fts/api/search` 等) は HTML には無く、 minified JS の `makeSearchParam` に param 名が全部ある。 必須 param が欠けると 5xx で沈黙する (= cabinet に `cabinetFolderId` + `fileOnly` が要る等) ので、 推測せず JS を grep する。 csrf ticket は page の inline `__PRELOADED_DATA__` から。
3. **HTML を grep して「0 件」 と言わない** — 検索結果 page は template に「該当なし」 文言を常在させ、 結果は JS が後から描画する。 browser MCP の `get_page_text` も描画前に読めば同じ罠 (= 実測: 3 query 連続で偽の no-data)。 API の JSON を正とする。
4. **login 切れの判定を script に持たせる** (302 → IdP / 200 + login page HTML)。 script が login を代行しない (= SSO の credential は user 専権)。 切れたら「browser で 1 回 login して」 と言って止まる前に、 **本体だけの切れなら browser に入り直させて復帰する** = 下の [#sso-session-recovery](#sso-session-recovery)。 切れが頻繁と言われたら、 対策の前にどの層がどう切れているかを測る = [`debugging-discipline.md#login-lifetime-measurement`](debugging-discipline.md#login-lifetime-measurement)。
5. **別 host の Basic 認証 (規程集の類) は射程外** — cookie は host 単位、 ID/PW 入力は agent 禁則 → user 依頼 (ladder 5) に戻す。 「cookie で全部読める」 と過信しない。
6. **auto-load 面に「第一選択 = script 経路」 と書くまでが 1 単位** (#build-the-route-first と同じ)。 browser MCP 経路は fallback として残す。

線引きは #internal-endpoint-replay と同じ (= user 本人の session で user が UI からできる read を機械化するだけ、 無人化・他人の session・bot 保護回避には使わない)。 cookie 値は secret (= session hijack 可能) — chat / log / commit に出さない。

### <a id="sso-session-recovery"></a>login 切れからの復帰 — 見積もらずに見る・使う時にだけ・本人に頼むのは要る時だけ

recipe 4 の中身。 部品 = [`scripts/lib/browser_tab.py`](../scripts/lib/browser_tab.py) (browser に裏で tab を開かせ、 行き先を見て、 自分の tab だけ閉じる) + 結末の判定 `watch()`。 初例の手順 = [`garoon.md#garoon-session-recovery`](garoon.md#garoon-session-recovery)。

SSO 保護サイトの切れは 2 層ある: **サイト本体のセッション**と **IdP のログイン**。 本体だけが切れていて IdP が生きていれば、 browser がそのサイトを開くだけで (パスワードも追加認証もなしに) 入り直せる。 IdP も切れていれば本人のログインが要る。 script の復帰は次の順:

1. 手元の cookie が古いだけなら読み直す (browser は既に入り直していて、 cookie の disk への書き出しが遅れていた場合。 browser に触らない)。
2. 起動中の browser に tab を 1 枚、 裏で開かせ、 **tab の行き先を見る**。 サイトの中に着いた = 入り直せた → cookie の更新を待って読み直し、 撃ち直す / 外 (ログイン画面) で数秒止まった = 本人のログインが要る → 専用の exit code で止まる。
3. 本人のログインが要る時は、 agent が user に 1 行で頼み、 同じ command を「ログイン完了を待つ」 option つき・background で実行し直す。 本人がログインし終えたら続きから進む = [完了は報告させず、 機械が状態で見る](../docs/convention-design-principles.md#completion-by-observation)。

設計の要点と理由:

- **見積もらずに見る** ([原則](../docs/convention-design-principles.md#observe-dont-estimate))。 「IdP がまだ生きているか」 は、 有効期間の推定 (閲覧履歴の最後のログイン + 期間) でも当てられるが、 推定は組織ごとの値が要り、 期間が放置型か絶対時間型かで外れ、 別端末のログインを知らない。 tab の行き先なら数秒で**観測**でき、 待ち方も「上限まで盲目に poll」 から「結末が見えた時点で終わる」 に変わる (実測: ログイン切れの判定が上限待ちの数十秒 → 数秒)。 観測の代償 = browser が IdP に 1 回触れること。 だから観測は読む用事がある時にだけ行う。
- **通常の周期を警告にしない** ([原則](../docs/convention-design-principles.md#steady-state-is-not-a-finding))。 IdP の有効期間より利用の間隔が長い使い方では「切れている」 が通常の状態で、 session 開始や dashboard で知らせても、 先にログインしておく意味が無い (次に使う時にはまた切れている)。 **死活監視に載せるのは配線の故障だけ** (cookie を復号できない等、 network なしで見られるもの)。 切れは使う時に見て、 その場で復帰する。 監視のために組織へ定期的に撃つこともなくなる。
- **IdP の有効期間は組織の方針** — 定期アクセスで延ばす仕組みは作らない。 減らせるのは「作業の途中で止まること」 と「本人の手数」 で、 ログインの回数ではない。
- **見るのは tab の URL (query と fragment を落としたもの) と読み込み中かだけ**。 ページの中身・認証応答 (SAML 等) は読まず、 IdP の cookie も読まない。 query は AppleScript の中で落とし、 script に渡さない。 入り直すのは browser 自身で、 script は認証に触れない。
- **人の browser に触る副作用は opt-in**。 公開の client の既定は「何も開かない」。 開かせる・閉じるは、 利用者が自分の入口 (org と流儀を env で渡す数行の wrapper) で選ぶ。 閉じるのは自分が開いた tab だけで、 閉じる直前に「まだ自分が開いた場所に居るか」 を確かめる。 本人がログインに使った tab、 ログイン待ちが時間切れになった tab (入力の途中かもしれない) は閉じない。 待たずに止まる時はログイン画面の tab も閉じる (失敗のたびに tab が溜まらない)。
- **既に開いている同じサイトの tab を使い回さない**。 reload は本人の入力中の form を壊しうる。 tab の id を run をまたいで覚える案も、 「その tab は今も自分のものか」 を判定できないので採らない (= 状態を持たない)。
- **ログイン画面の判定は「外に、 読み込み完了のまま、 数回続けて同じ場所」**。 SSO の通過は一瞬 IdP の URL を通るので、 1 回見ただけでは決めない。 サイトの外かどうかは host と path で決め、 IdP ごとの URL の形は持たない (= 組織固有の値が client に要らない)。
- AppleScript が使えない環境 (自動操作の許可が無い・無人実行) では「開くだけ」 に落ち、 cookie の更新だけを上限つきで待つ。 incognito 等の窓には開かない (SSO のログインを共有していない)。 機構 = [`macos-gui-app-automation.md#chromium-tab-scripting`](macos-gui-app-automation.md#chromium-tab-scripting)。
- **browser の中で読む経路 (browser MCP) に寄せない理由**: SSO は browser が面倒を見てくれるが、 拡張の接続と domain 許可が機械 × account ごとの配線になり、 無人の検査から使えず、 1 回の読み取りが tool call 数回になる。 cookie 再利用を第一選択のまま、 入り直しだけを browser に任せるのが両者の良い所取り。

## 実例

2026-08-21: Dropbox 共有リンクの取得を Finder 右クリックの画面 drive で実施 → 対象フォルダの取り違え + user のマシン拘束が同時に起き、 user から経路選択そのものへの否定 feedback。 API 経路 (scoped app + PKCE、 [`dropbox-api-access.md`](dropbox-api-access.md)) の実装は初回 setup 込み ~15 分で、 以後は 1 コマンド ~2 秒になった。 「画面で 1 分 vs 実装で 15 分」 の比較は 1 回分しか見ていない — 経路は残り、 画面は残らない。

2026-08-28: claude.ai の共有会話を Claude Code に渡す経路が無く (WebFetch / curl / headless 全滅)、 スマホでは 1 message ずつの手動コピペしかなかった → **経路を 2 本実装**: ① in-app Browser pane での share URL 直読 (= agent 側の最短経路、 実は既存 tool が素通しだった) ② page-context API fetch のブックマークレット (= user 側 1 click export)。 手動コピペは消え、 経路は全 session の資産になった。 recipe = [`web-tools.md #claude-share-page-access`](web-tools.md#claude-share-page-access)。 注: bot 保護持ちサイトでは「経路を実装する」 と「保護を回避する」 の線引きが要る — 実ブラウザ + user click は前者、 headless 化・無人化は後者 (やらない)。

実測: 家計簿 SaaS (公開 API 無し) の明細カテゴリ誤分類を、 まず画面 drive で数件直した (dropdown 開閉 × 2 段 × 件数 + 誤 click、 round-trip 十回ほど) → user 「GUI のダサいやり方じゃなくて API 的に」 → XHR hook で UI 操作を一度捕捉し `PUT /cf/update` (urlencoded + CSRF) と判明、 rules-driven の dry-run/apply tool を実装。 以後は 4 手 (rules 読む → dry-run → 目視 → apply + reload 確認) で月をまたいで一括、 click ゼロ。 同時に業種語 regex の巻き込み (数件) を経験し recipe 3 に焼いた。 recipe = #internal-endpoint-replay。

2026-09-05 (同日 2 例目): 専攻主任が Drive に置いた「各自記入」 xlsx (他人 owner、 6 名記入済) に自分の行を書く作業を claude-in-chrome の cell click + type で実施 → name box click が cell 選択に化けて**注記行と見出し行を自分の値で上書き** (undo で救出)、 再試行では先頭 keystroke が食われ名前 cell 空 + 規則文の先頭欠けが保存された。 screenshot は stale で保存状態が読めず、 API の revision download でしか truth が分からなかった。 user 「ダサい GUI 的なやり方でなく自動化で」 → full `drive` scope の別 token を 1 consent で発行し、 revision download → openpyxl → `files.update` → 再 download verify の経路を実装 (~20 分)。 以後は 1 コマンド。 recipe = [`google-api-direct-access.md #drive-xlsx-inplace-update`](google-api-direct-access.md#drive-xlsx-inplace-update)、 規律 = #shared-document-write。

2026-09-07: groupware (Cybozu Garoon) の規程集を読む経路は既に在り (= [`garoon.md`](garoon.md)、 別マシンで実証済) だったが、 この機械の browser 拡張では `Permission denied for reading page content on this domain` → 最初の turn は「規程集は未読 = 未 verify」 と scope 外宣言して終えた。 user 「接続できないと今後も困るからしっかり整備して (配線がないときは配線を作る、 という努力目標も正本と参照を)」 → 診断 (`list_connected_browsers` 2 本 = stale 接続 → 最新を `select_browser` → それでも denied = domain allow-list 層) → user 段 (Always allow click) を 1 画面で依頼 + 機械別配線状態を personal 層に表で記録 + carrier TODO。 規律 = #wiring-gap-is-a-task (本例が起点)。 **同日の続き**: user 「本来は GUI のダサいやり方じゃなくて API 的な自動接続で」 → REST password auth は SAML-only で admin 限定・OAuth も admin 登録要と doc で確定 → **browser session cookie の再利用**を経路として実装 (`scripts/chromium-cookies.py` + `scripts/garoon-client.py`、 全文検索の内部 API `fts/api/search` は JS を読んで param を復元 = #internal-endpoint-replay の型)。 以後 GAROON の検索・掲示・添付は 1 コマンド、 browser MCP は fallback。 recipe = [`garoon.md #garoon-script-route`](garoon.md#garoon-script-route)。

2026-09-12: 購読している Substack の有料記事 (公開 API は抜粋しか返さない) の全文取得。 メールで届くログインリンクを開いて session を作る案は [`academic-program-verification.md#magic-link-handoff`](academic-program-verification.md#magic-link-handoff) により不採用、 GAROON 用に作った `scripts/chromium-cookies.py` がそのまま使えた (= **部品を一度作ると、 次のサイトは数分で降りられる**)。 初回の cookie 読み取りは Claude Code の自動許可判定で止まり、 user が自分のターミナルで 1 回実行 → 以後は user の明示許可で agent から。 同じ turn で一覧 API の途中切れと日本語の全文判定の罠も踏み、 道具 ([`scripts/substack-fetch.py`](../scripts/substack-fetch.py)) と規約 ([`substack.md#archive-pagination`](substack.md#archive-pagination)) に焼いた。

関連: [`google-api-direct-access.md`](google-api-direct-access.md) (Google の API 直叩き pattern) / [`dropbox-api-access.md`](dropbox-api-access.md) (Dropbox) / [`mcp.md`](mcp.md) (MCP 使い分け)
