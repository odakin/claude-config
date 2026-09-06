<!-- doc-meta
when: 外部 service / アプリを操作・データ取得する経路を選ぶとき (画面 drive を検討し始めた瞬間)
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
6. **画面 drive** — user が**その対象について「画面でやって」** と言った時、 または 1〜5 が全滅の時のみ。 ⚠️ user の「見て」「やって」「任せる」 は経路の指定ではない (= 上位で実行せよの意) — それを GUI 許可と読むのが最頻の滑り方 (実例 2026-08-21 / 2026-09-05)

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

recipe (2026-09-05 家計簿カテゴリ一括修正で確立):

1. **推測で組まず、 実 UI 操作 1 回分を捕捉する** — page context で `XMLHttpRequest.prototype.open/send/setRequestHeader` と `fetch` を一時 hook し、 対象操作を **1 回だけ・冪等な値で** (= 現在値を再選択する等) UI から実行して method / URL / header / body の field 名を取る。 method 違い (POST vs PUT) や encoding 違い (multipart vs urlencoded) は 404 で沈黙するので、 捕捉なしの試行は時間を溶かす。 CSRF token は `meta[name=csrf-token]` 等から取り、 log には残さない (`<redacted>`)。
2. **id の類は DOM から実行時に解決する** (カテゴリ id ↔ 名前 等)。 hard-code すると相手側の変更で silent に別物を書く。 menu が lazy 生成 (一度開くまで DOM に無い) / 行の種別で中身が違う (支出行と収入行) といった罠は実測で潰す。
3. **rules → dry-run → apply の 3 段**: 変更対象を宣言的 rules (店名 regex → 目標値) で与え、 既定は dry-run で対象行を全部列挙、 user が読んでから apply。 rules は**具体名の列挙**にする — 業種語だけの regex (「薬局」) はドラッグストアを巻き込む (実測: 3 件誤変更 → 即 revert)。 巻き込み範囲は処理月数に比例して増える。
4. **書いた後は再読込して実状態を読む** — 自前 `fetch` の応答 (UI が eval する前提の JS 等) は画面を再描画しないので、 DOM の旧値を見て「変わっていない」 と誤診しない。 サーバ session が表示状態 (月等) を保持していれば reload 後も同じ画面に戻る。
5. **agent の browser tool の制約に合わせる**: 1 call の timeout (45 s 級) を超えないよう処理単位を分割 (timeout 後も page 内 script は走り続ける = 同値 PUT の冪等性で二重実行を無害化)、 出力は tool 側 filter に掛からない形で返す (詳細 = [`web-tools.md` javascript_tool gotcha](web-tools.md#javascript-tool-gotchas))。
6. **rules の正本と tool は別 file** に置く (rules は個人情報を含みうる → 暗号化側、 tool は平文で公開可能)。 auto-load 面への記録は #build-the-route-first と同じ。

線引き: これは **user 本人の session で user が UI からできる操作を、 同じ endpoint で機械化するだけ** (= 所有者権限の範囲内)。 bot 保護の回避・無人化・他人のデータ・利用規約が禁じる自動取得には使わない (#実例 2026-08-28 の注と同じ線)。

## 実例

2026-08-21: Dropbox 共有リンクの取得を Finder 右クリックの画面 drive で実施 → 対象フォルダの取り違え + user のマシン拘束が同時に起き、 user から経路選択そのものへの否定 feedback。 API 経路 (scoped app + PKCE、 [`dropbox-api-access.md`](dropbox-api-access.md)) の実装は初回 setup 込み ~15 分で、 以後は 1 コマンド ~2 秒になった。 「画面で 1 分 vs 実装で 15 分」 の比較は 1 回分しか見ていない — 経路は残り、 画面は残らない。

2026-08-28: claude.ai の共有会話を Claude Code に渡す経路が無く (WebFetch / curl / headless 全滅)、 スマホでは 1 message ずつの手動コピペしかなかった → **経路を 2 本実装**: ① in-app Browser pane での share URL 直読 (= agent 側の最短経路、 実は既存 tool が素通しだった) ② page-context API fetch のブックマークレット (= user 側 1 click export)。 手動コピペは消え、 経路は全 session の資産になった。 recipe = [`web-tools.md #claude-share-page-access`](web-tools.md#claude-share-page-access)。 注: bot 保護持ちサイトでは「経路を実装する」 と「保護を回避する」 の線引きが要る — 実ブラウザ + user click は前者、 headless 化・無人化は後者 (やらない)。

2026-09-05: 家計簿 SaaS (公開 API 無し) の明細カテゴリ誤分類を、 まず画面 drive で 2 件直した (dropdown 開閉 × 2 段 × 2 件 + 誤 click 1 回、 ~10 round-trip) → user 「GUI のダサいやり方じゃなくて API 的に」 → XHR hook で UI 操作 1 回を捕捉し `PUT /cf/update` (urlencoded + CSRF) と判明、 rules-driven の dry-run/apply tool を実装。 以後は 4 手 (rules 読む → dry-run → 目視 → apply + reload 確認) で月をまたいで一括、 click ゼロ。 同時に業種語 regex の巻き込み (3 件) を経験し recipe 3 に焼いた。 recipe = #internal-endpoint-replay。

2026-09-05 (同日 2 例目): 専攻主任が Drive に置いた「各自記入」 xlsx (他人 owner、 6 名記入済) に自分の行を書く作業を claude-in-chrome の cell click + type で実施 → name box click が cell 選択に化けて**注記行と見出し行を自分の値で上書き** (undo で救出)、 再試行では先頭 keystroke が食われ名前 cell 空 + 規則文の先頭欠けが保存された。 screenshot は stale で保存状態が読めず、 API の revision download でしか truth が分からなかった。 user 「ダサい GUI 的なやり方でなく自動化で」 → full `drive` scope の別 token を 1 consent で発行し、 revision download → openpyxl → `files.update` → 再 download verify の経路を実装 (~20 分)。 以後は 1 コマンド。 recipe = [`google-api-direct-access.md #drive-xlsx-inplace-update`](google-api-direct-access.md#drive-xlsx-inplace-update)、 規律 = #shared-document-write。

2026-09-07: groupware (Cybozu Garoon) の規程集を読む経路は既に在り (= [`garoon.md`](garoon.md)、 別マシンで実証済) だったが、 この機械の browser 拡張では `Permission denied for reading page content on this domain` → 最初の turn は「規程集は未読 = 未 verify」 と scope 外宣言して終えた。 user 「接続できないと今後も困るからしっかり整備して (配線がないときは配線を作る、 という努力目標も正本と参照を)」 → 診断 (`list_connected_browsers` 2 本 = stale 接続 → 最新を `select_browser` → それでも denied = domain allow-list 層) → user 段 (Always allow click) を 1 画面で依頼 + 機械別配線状態を personal 層に表で記録 + carrier TODO。 規律 = #wiring-gap-is-a-task (本例が起点)。 **同日の続き**: user 「本来は GUI のダサいやり方じゃなくて API 的な自動接続で」 → REST password auth は SAML-only で admin 限定・OAuth も admin 登録要と doc で確定 → **browser session cookie の再利用**を経路として実装 (`scripts/chromium-cookies.py` + `scripts/garoon-client.py`、 全文検索の内部 API `fts/api/search` は JS を読んで param を復元 = #internal-endpoint-replay の型)。 以後 GAROON の検索・掲示・添付は 1 コマンド、 browser MCP は fallback。 recipe = [`garoon.md #garoon-script-route`](garoon.md#garoon-script-route)。

関連: [`google-api-direct-access.md`](google-api-direct-access.md) (Google の API 直叩き pattern) / [`dropbox-api-access.md`](dropbox-api-access.md) (Dropbox) / [`mcp.md`](mcp.md) (MCP 使い分け)
