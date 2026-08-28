<!-- doc-meta
when: WebSearch / WebFetch / browser 自動化の信頼性を判断するとき
category: web
summary: WebSearch / WebFetch の信頼性 caveat (summary hallucination、 事実値は source 直接確認) + CSR SPA は fetch に空シェル (200≠実在、 実ブラウザ描画で検証) + **claude.ai share ページは in-app Browser pane が素通し / page 内 same-origin fetch は snapshot API も 200 (= headless / curl は全滅、 #claude-share-page-access)** + **browser cookie replay は OAuth-token SPA を認証しない (= Box `/f/` 等 member 限定クラウドフォルダは無人 upload 不可、 session API 401 / shared-item 404 で spike 1 回で確定)** + Claude in Chrome MCP の 2 層 permission モデル + bug 53630 (sites/docs.google.com domain silent block)
-->
# Web ツール (WebSearch / WebFetch) の信頼性 caveat

WebSearch / WebFetch は便利だが post-processing 由来の落とし穴があり、**事実確認用途では補助検証が必須**。

> **関連**: tool result に外部由来の adversarial 指示文が混入する prompt injection の取扱は別規約 [prompt-injection.md](prompt-injection.md) に分離 (web tools 以外の MCP / Bash / Read にも横断するため)。

## <a id="websearch-summary-hallucinates"></a>WebSearch の summary は hallucinate する

WebSearch の result block 末尾に付く自然言語 summary は検索エンジンが推測した情報を含み、リンク先 source に存在しない値を捏造することがある。**事実値 (メールアドレス・電話番号・URL・固有名) は summary だけで採用してはいけない**。

### How to apply

- メールアドレス・電話番号・URL のような事実値は、リンクされた source ページ (公式サイト・PDF press release 等) を WebFetch / curl で直接確認してから採用する
- 複数の異なる値が出てきたら最新の公式 source を優先
- ヒットしたリンクのうち最も authoritative なもの (組織の公式 domain 等) を優先

### 典型パターン

ある組織の窓口メールアドレスを WebSearch で取得しようとすると、summary に「`<role>@<domain-A>`」 のような値が返ってくることがある。実際に source を確認すると、PDF (古い文書) には「`<role>@<domain-B>`」、現行公式 contact ページには「`<role>@<domain-C>`」 と書いてあって、summary に出た `<domain-A>` 版はどちらにも存在しない hallucination だった、というケース。検索エンジンが「`<role>` + 組織ドメインの慣用 prefix」 から推測しただけ。

## WebFetch は `<head>` 内 meta タグ・JSON-LD を落とす

WebFetch は HTML → markdown 変換 + 内部要約モデル処理を経るため、`<head>` 内の `<meta>` `<link>` `<script type="application/ld+json">` 等は実質的に削られる。「**Open Graph / Twitter Card / canonical / verification meta / JSON-LD / hreflang を確認したい**」 用途では WebFetch は使えない。

### How to apply

- meta / OG / JSON-LD / canonical / hreflang / verification token の検証は **`curl + sed` で生 HTML を取得して grep** する
- 例: `curl -sS https://example.com/ | sed -n '/<head>/,/<\/head>/p'`
- JSON-LD が body 内に出力されているケースもあるので、見つからなければ `curl ... | grep -A20 '"@type"'` で全文 grep
- WebFetch は記事本文抽出・要約・自然言語回答用途には適切 (= ナラティブ系コンテンツ向け)

### 典型パターン

WebFetch に「`<head>` 内の meta タグを抽出して」 と prompt しても「<head> セクションは提供されていません」 と返答するケースがある。post-processing で削られているため。代わりに `curl + sed` で head を取得して verification meta / Open Graph / JSON-LD を直接確認する。SEO 検証 (Search Console verification token / OG image / Event JSON-LD 等の live 確認) で典型的に発生する。

## CSR な SPA は WebFetch / fetch に空シェルしか返さない (= 200 ≠ ページ実在)

Client-side rendering の SPA (= JS が描画してから中身が入るサイト) は、**WebFetch も同一オリジンの `fetch()` も、実在 route と存在しない route に対して同一の空アプリシェル (HTTP 200・ほぼ同一バイト数・本文テキストなし) を返す**。サーバーが routing を JS に委ねており unknown route でも 404 を返さず shell を返すため。つまり **HTTP status 200 や fetch 成功は「その URL が実在し、その内容である」 ことの保証にならない** (= `mcp.md` / inline §3「tool の signal を guarantee と取り違えない」 の false-positive 版 — null を不在と短絡する裏返しで、 200 を実在と短絡する形)。

### How to apply

- SPA の URL の**実在・内容**を確認したいときは、**JS を実行する実ブラウザ (Claude in Chrome 等) で navigate して、描画後の DOM** (本文テキスト量・`<h1>`/見出し・期待語の有無) で判定する。`curl`/WebFetch の status や生 HTML では判別できない
- **404 の見分けは status でなく描画後の content** で行う: 実在ページは本文が十分長く期待トークン (固有名・見出し) を含む / 不在ページは別 fallback (極端に短い本文・無関係な見出し) に落ちる。両者を 1 件ずつ実測して閾値を掴んでから一括判定する
- 描画ツールが**無い**環境では「fetch では検証不能」 と正直に surface する (= search index が返す**そのページ自身の `<title>` + 一致するスコア/固有名**は弱い corroboration として使えるが、 live render 確認ではないと明示する)
- WebFetch は記事本文抽出・要約には有効 (= サーバーが本文を返す従来型ページ向け)。SPA の存在確認には不適

### 典型パターン

CSR SPA のニュース/結果ページの URL を多数検証する場面 (例: fifa.com の試合レポート URL を 40 本) で、`fetch` は実在 URL も故意の偽 URL も同一の空シェル (200・~4.5KB・本文/og:title なし) を返し status からは判別不能だった。実ブラウザで navigate すると、実在ページは本文数千字 + 該当見出しが描画され、不在ページは本文 ~140 字の無関係 fallback に落ちる明確な差が出た。**「200 が返った = ページがある」 と短絡せず描画後 DOM を読む**ことで全件を確定できた。

## <a id="claude-share-page-access"></a>claude.ai の share ページは in-app Browser pane なら読める (= headless / curl は全滅、 page 内 fetch なら API も通る)

`claude.ai/share/<uuid>` (= 会話の公開共有ページ) は前節の CSR SPA + Cloudflare bot 保護の複合で、 経路によって結果が全く違う (2026-08-24/28 実測):

| 経路 | 結果 |
|---|---|
| WebFetch / curl (browser UA でも) | 200 だが空シェル (本文なし) |
| curl で `/api/chat_snapshots/<id>` | 403 Cloudflare チャレンジ |
| headless ブラウザ (CDP) | 描画後も Cloudflare interstitial (= bot 判定) |
| **Claude Code 内蔵 Browser pane** | **✅ 完全レンダリング** — `get_page_text` で会話全文が読める |
| **ページ内 (page context) からの same-origin `fetch`** | **✅ snapshot API も 200** で JSON 全文 |

### How to apply

- **user が share URL を貼ったら、 内蔵 Browser pane で開いて読むのが最短** (`preview_start {url}` → `get_page_text`)。 login 不要。 会話 DOM は全文が実高さで layout される (= 中規模会話で非仮想化を実測、 超長会話は未検証)
- pane 内で blob download を発火させると macOS では `~/Downloads` に着地する (= agent 自身が export 動作を e2e 検証できる)。 ⚠️ 同名 file の再 download は隠し temp (`.XXXX.com.anthropic.…`) のまま確定しないことがある (n=1 観測) — 検証時は既存 file を先に消す
- 構造化 (message 単位・話者付き) が要るなら `javascript_tool` で page context から `fetch('/api/chat_snapshots/<id>?rendering_mode=messages')` — JSON schema の実測 gotcha: `chat_messages[].text` は**空**で、 本文は `content[]` の `type:"text"` block 群 / web 検索を含む会話には placeholder block (「\`\`\`This block is not supported on your current device yet.\`\`\`」 literal) が混入 / 引用は `<cite index="…">` タグが本文に埋まる (タグだけ strip) / message 単位の `truncated` flag あり
- ログイン済みの通常会話ページ (`/chat/<uuid>`) も同型: `/api/organizations` で org uuid → `/api/organizations/<org>/chat_conversations/<id>?tree=True&rendering_mode=messages` (= share 経路と違い login cookie が要る。 2026-08-28 時点で式のみ・未実測)
- **user 側の手元 export はブックマークレットが適形** (= 自分のブラウザ・自分のクリック = bot 保護の回避ではない)。 gotcha 3 つ: ① `javascript:` URL はアドレス欄ペーストで prefix が剥がされる → ブックマーク作成後に**編集画面の URL 欄**へ貼る (スマホも同じ、 実行はページを開いた状態でアドレス欄にブックマーク名を打って候補 tap) ② 生成 Blob は **UTF-8 BOM を付ける** — Android の text viewer は charset ヒント無し UTF-8 を Shift_JIS と誤判定して文字化け表示する (中身は健全なので気付きにくい) ③ `#` を含む文字列は `\x23` に escape (= URL fragment 切断対策)
- **線を守る**: 実ブラウザの画面 / user のクリックで閉じる形は正当。 これを headless 化・無人化・stealth flag で回すのは bot 保護の回避で、 やらない (session の他の操作まで permission guard に落ちる実害も観測済)

### 典型パターン

「claude.ai の会話を Claude Code に渡したい」: share URL を curl / WebFetch / headless で読もうとして全滅し、 bot 保護の回避に向かいそうになる — が、 正解は上の 2 経路 (pane 直読 / page 内 fetch)。 スマホからでも share ページ + ブックマークレット 1 tap で全文 `.md` が落とせる。

## <a id="cookie-replay-oauth-spa"></a>Browser cookie replay は OAuth-token SPA を認証しない (= member 限定クラウドフォルダは無人 upload 不可)

Chromium (Brave/Chrome) の cookie DB を復号して session cookie を replay すれば authenticated アクセスできる — これは **cookie-session 方式のサイト (伝統的サーバーセッション、 Slack の `d` cookie 等) にのみ成立**する。 **OAuth/token 方式の modern SPA (Box enterprise・多くの SaaS) では成立しない**: 認証本体は login 後に fetch される **in-memory の access token** で、 cookie DB には persist されないため、 cookie を全部そろえて replay しても API 呼び出しが 401 になる。

### How to apply

- **クラウドフォルダの共有 link の種別を最初に見分ける**: 公開共有 link (Box `/s/…`、 Drive の「リンクを知っている全員」) は anonymous / cookie 経路が効くことがある。 **member 限定フォルダ (Box `/f/{folder-id}`、 login required) は無人 upload の経路が構造的に無い** (= shared-item API は `sharedNotFound` 404、 cookie replay は session API が 401)
- member 限定フォルダへの提出を自動化しようとする前に、 **cookie replay が効くか 1 回 spike** して決める: session cookie を復号 → `common/session` 等の authenticated endpoint を叩く → 401 なら cookie 経路は死んでいると確定し、 深追いしない
- 残る automation 経路は **live authenticated browser を driving する** (Claude in Chrome MCP で file input に `file_upload`) のみ。 これは semi-manual (browser を開いた状態が要る) + SPA UI 変更に脆い。 payoff (= 5 秒の drag & drop) と天秤にかけ、 大抵は **user 手動 upload を正規手順**にするのが妥当
- API 直叩きの正道は OAuth App 登録だが、 **他組織 tenant (省庁・大学の Box 等) では tenant admin 承認が要る** = 現実的でないことが多い

### 典型パターン

省庁運営の Box enterprise (member 限定 `/f/` フォルダ) への書類提出を自動化しようとした場面。 Brave の `Brave Safe Storage` 鍵で box.com cookie (`z` session ほか) を復号・replay したが、 `common/session` が **401**、 `shared-item?sharedName=…` が **404 sharedNotFound** で、 cookie 経路は認証を carry しないと確定した (= `z` は httponly session cookie だが OAuth access token を含まない)。 Claude in Chrome も未接続だったため無人経路は不在と結論し、 user 手動 upload を正規手順として維持した。 **member 限定クラウドフォルダは「cookie を取れれば自動化できる」 という直感が成立しない**ことを最初の spike で確定させるのが、 深追いで時間を溶かさない鍵。

## Multi-national service の global と local entity は別 product line

Multi-national の regulated service (証券 broker / banking / payment / SaaS の地域版等) で「Service X が feature Y を提供しているか」 を user 居住国の文脈で確認するとき、**global parent の product page と local entity の product page を別々に検証する**。entity-level で product line が大きく異なり、global の宣伝に local が含まれていない sub-feature が頻繁にある。

### How to apply

- user の居住国に割当てられる **local entity の公式 product page を first source** として検証 (例: `*.co.jp`, `*.de` 等の domain)
- global parent の product page、broker comparison サイト、第三者 review は **outdated や誤情報の risk** が高い — 採用前に local entity の公式情報で confirm
- regulated service の典型 gotcha: account 開設は居住国 entity に固定 (regulatory requirement) で、global parent や別 entity への transfer は事実上不可な場合が多い

### 典型パターン

「Interactive Brokers が cash 個別債券を提供している」 は global IB (IBKR LLC) には true だが、Japan resident が assigned される IBSJ では cash bond は提供無し (entity-level product line drop)。同様に「Saxo Bank は global で cash bond 5,200+」 は true だが Saxo Bank Securities Japan は CFD のみで cash bond 0 件。日本居住者は別 entity に switch できない (居住国固定)。global の評判で実用判断すると、routing された local entity で実機能が無く戦略が崩壊する。

---

## Filter 条件は capture と一緒に metadata に記録

UI 上の filter (通貨選択、日付範囲、商品分類等) を適用して data を取った場合、**filter の正確な scope を snapshot metadata に記録する**。後で「この項目は 0 件だった」 と読み返したとき、それが (a) filter で除外していただけ なのか (b) 実 inventory が 0 だった のかが、metadata 無しで判別できなくなる。

### How to apply

- snapshot 保存時に `filter_applied: <verbatim>` を metadata block で記録 (例: 「米ドル除く 9 通貨選択」)
- UI に複数 filter dimension があるなら全部記録する (currency / date range / type / status 等)
- partial capture (lazy-load / pagination で全部取れていない) も同様に `partial: true` + `result_count_total / result_count_captured` で明示
- 全 data が必要なら filter 解除 + export 機能で再取得を優先 (`§ロックイン済 web app からのテーブル data 取得は scrape より export を優先` 参照)

### 典型パターン

複数通貨 filter を当てて非 USD 9 通貨を取得 → 「TRY/CNY/RUB は 0 件」 と結論 → 後日全 filter 解除で取り直すと TRY 6 件 / CNY 1 件 / RUB のみ実 0 件、と判明。**「filter で除外」 と「在庫 0」 を後の自分が判別できる metadata** を残しておけば、reasoning gap に気付ける。

---

## ロックイン済 web app からのテーブル data 取得は scrape より export を優先

認証済 web UI (broker / CRM / e-commerce / analytics dashboard 等) のテーブル view から data を取得するときは、**scrape を始める前に「CSV ダウンロード」 / "Export" / "Excel" ボタンの有無を確認する**。ある場合は scrape より遥かに早く正確で、ページ実装の癖に破綻しない。

### How to apply

- 認証済 web UI でテーブル data を見ている時、ページ上に "CSVダウンロード" / "Export" / "Download CSV" / "Excel" / "ダウンロード" 等のボタンが無いか先に探す
- 見つかった場合: それを使う。ファイルとして保存され、機械可読、virtual-scroll や lazy-load の影響を受けない
- 無い場合のみ scrape (DOM 抽出 / paste 経由) に移る
- export 結果のスコープは要確認 — 多くのアプリは「現在のフィルタ」 を反映するが、一部は**全 data** を出す (= フィルタした表示より広い)。1 度ダウンロードして件数を確認するだけで判別できる
- export を見落としたまま scrape に着手すると、後から「CSV あった」 で全 work がやり直しになる。**最初の 30 秒で UI を全体スキャンしてから方針を決める** のが結果的に速い

### 典型パターン

paste-and-transcribe で rendered DOM を写す方針を取った後で問題が複合する: lazy-load で見えていない行が rendered DOM に存在しない、virtual-scroll 領域外の行は paste できない、複数 dump 間で重複・脱漏が発生する、別フィルタの dump 同士で混乱、行のセル順序がブラウザ render 設定に依存して微妙にズレる、等。CSV export は raw 値ベースで一発取得できるためこれらが構造的に発生しない。

一方、UI badge ("NEW" / "保有中" / "在庫切れ" 等) は CSV に含まれないことが多い。**badge を本当に必要とする用途**では、CSV export を canonical source にし、DOM scrape を annotation overlay として **両方取る hybrid アプローチ**を採る (CSV で 95% の事実、DOM で 5% の UI 注釈)。

**Browser MCP の制約**: Claude in Chrome MCP は安全 rule で**証券 broker / trading platform の domain を navigate level で block** する (取引執行リスク予防)。block 確認は 1 navigate で済むので時間損失は小さいが、broker UI からの抽出方針を browser-based で立てる前に試行確認する価値はある。block されたら user paste / CSV download / API access に切り替える。

---

## <a id="raw-export-snapshot-3set"></a>外部 system からの snapshot は raw export + 構造化 + script の 3 点 set

外部 web app / SaaS / API から data の point-in-time snapshot を取るとき、**(a) raw export (CSV/Excel/JSON 等) + (b) 構造化 form (YAML/parquet 等) + (c) (a) → (b) の conversion script** を 3 点 set で保存する。後で再 derive、schema 拡張、問題追跡 (transcribe error 検出等) が可能になる。

### How to apply

- 取得経路の優先順: 外部 system の export ボタン > 公開 API > DOM scrape (`§ロックイン済 web app からのテーブル data 取得は scrape より export を優先` 参照)
- 保存場所: data ディレクトリ配下、private repo なら git-crypt 暗号化下、public repo なら .gitignore 必須
- 命名: `{source}_{YYYY-MM-DD}.{ext}` (e.g., `sbi_2026-05-04.csv` + `sbi_2026-05-04.yaml`)
- conversion script は repo に保存 (raw → 構造化 を再現可能に)。script が **user-specific overlay (held flag、annotation 等) を hardcode** している場合、機密情報を持つので git-crypt 対象に追加 (`.gitattributes` で `tools/<script>.py filter=git-crypt` 指定)
- snapshot は **append-only** / 上書き禁止: rotate するならファイル名に日付を入れて新規ファイル。schema 進化に伴う migration script は別途
- 構造化 YAML には raw export の filename + 取得時刻 + filter scope を metadata block で記録

### 典型パターン

manual transcribe で snapshot を作る方針は (a) transcription error、(b) partial capture (途中で疲れる、scroll-load 限界)、(c) 後から re-derive 不能 のいずれかで失敗する。raw export を保存しておけば script の bug 修正後に再 derive で済み、transcribe やり直しが要らない。逆に conversion script を repo に置かずに「一度きりの ad-hoc 変換」 で済ませると、schema が drift した後に「以前どう変換したか」 が grep 不能になる。

### 関連
- snapshot ディレクトリ構造の例: `<repo>/data/<source>_inventory/{source}_{date}.csv` (raw) + `.yaml` (構造化) + `<repo>/tools/{source}_csv_to_yaml.py` (conversion)

---

## 学術論文 PDF の WebFetch 限界と迂回路

学術文献の URL を素朴に WebFetch する典型失敗パターンと迂回路。

| ソース | 挙動 | 迂回路 |
|---|---|---|
| 古い scan PDF（例: 日本気象学会「天気」 1990 年代以前、CCITT FAX 圧縮の bitmap） | 本文テキスト抽出不可（画像 PDF） | CiNii / AGU 等の abstract page、後継論文の citation 中の要約 |
| Wiley Online Library / ResearchGate / Elsevier | 403 Forbidden | arXiv preprint、著者個人ページ、ADS abstract |
| ADS (`ui.adsabs.harvard.edu/abs/...`) | abstract 取得可 | 引用関係・要旨確認に有効 |
| arXiv (`arxiv.org/abs/...`) | フルテキスト OK | 物理・数学・CS 系の第一選択 |
| CiNii (`ci.nii.ac.jp/naid/...`) | 旧 `naid` URL は `cir.nii.ac.jp/crid/...` に 301 redirect | redirect 先で再 WebFetch |

### How to apply

- arXiv ID があれば arXiv → なければ ADS abstract → 後継論文の citation 経由、の順で確認する
- 古い和文論文は本文 PDF が画像形式なら諦めて、引用している後継論文の本文中要約を信用する
- 商用 publisher の paywall ページは内容が取れないので時間を浪費しない

---

## Claude in Chrome MCP の domain permission モデル

Claude in Chrome 拡張 (Chrome / Brave / 他 Chromium で動く Anthropic 公式拡張、 `mcp__Claude_in_Chrome__*` の MCP tools を提供) は **2 層の permission モデル** で動く。 設定間違いと混同しやすいので構造を理解しておく。

### 2 層の独立した permission

| 層 | 何 | 設定場所 |
|---|---|---|
| **(1) Chrome 標準の host_permissions** | content-script injection、 user-driven 操作時のページ読取 | `chrome://extensions/?id=<extId>` の「サイトへのアクセス」 (= 「すべてのサイト」 / 「特定のサイト」) |
| **(2) Claude in Chrome 独自の AI-driven domain allow-list** | MCP 経由で Claude が programmatic に navigate / click / type する場合の per-domain 許可 | 拡張の sidepanel 内 prompt (= **「Permission required」 dialog**) で domain 単位に Always allow / one-time / Decline を選択 |

**重要**: (1) を「すべてのサイト」 にしても (2) は domain ごとに別途許可が必要。 これは AI-driven 自動操作を user 確認下に置く意図的な安全機構。

### 期待される UX

MCP の `navigate` (or `left_click` / `type` 等) が未許可 domain に対して呼ばれると:
1. backend は `permission_required: <domain>` を return
2. **拡張の sidepanel に「Permission required: <domain>」 prompt が出る** (3 択: 「Allow this action」 / 「Always allow actions on this site」 / 「Decline」)
3. user が「Always allow actions on this site」 を選べば該当 domain が allow-list に追加 → 以降の MCP 経由操作は permission check pass

### 既知バグ: prompt が render されないことがある (= 詰む)

backend が `permission_required` を return しても、 **sidepanel の prompt UI が render されない** 既知バグがある ([GitHub claude-code #53630](https://github.com/anthropics/claude-code/issues/53630), [#57219](https://github.com/anthropics/claude-code/issues/57219))。 この状態だと user は「Always allow actions on this site」 を click する手段がなく、 MCP 操作が完全に詰む (= silent block)。

公式の「reset allowlist」 UI は無く、 報告されている workaround:
- 拡張を一度削除 → Chrome Web Store から再インストール (= storage clear)
- profile を変える / Chrome / Brave / Chromium を切り替える
- バグ報告 (上記 GitHub issue にコメントで repro 情報を添える)

### MCP tab group は user の手動タブと別

Claude in Chrome MCP は **自分専用の tab group** で動く。 user が手動で開いたタブと MCP が操作するタブは別管理:
- `tabs_context_mcp` は MCP の tab group 内のタブだけを返す (user の他タブは見えない)
- 「user が既にログイン済の sg-l タブ」 のような既存セッションを MCP から直接操作することは不可
- MCP は `tabs_create_mcp` で自分の tab group 内に新規タブを開いて navigate する

これは tab group ごとに permission state が独立する設計の帰結。 user が手動でタブを操作している間に MCP が裏で別ドメインに勝手に navigate するのを防ぐ。

### 公式ドキュメント

- [Claude in Chrome Permissions Guide](https://support.claude.com/en/articles/12902446-claude-in-chrome-permissions-guide) (= 公式 permission モデル説明)
- [Claude Code Permissions](https://code.claude.com/docs/en/permissions) (= MCP tool permission の上位概念)

### How to apply

- `permission_required: <domain>` を踏んだら、 まず sidepanel を user に見てもらい prompt の有無を確認 (= 既知バグかどうかの切り分け)
- prompt があれば「Always allow actions on this site」 を user に click してもらう
- prompt がなければ既知バグの可能性 → 拡張再インストール / 別 profile / スクショ共有 fallback を提案
- 「Chrome 標準の host_permissions が「すべてのサイト」 になっているのに動かない」 は誤解、 (1)(2) が独立であることを最初に user に説明する
- 既存 web ツール (`mcp__Claude_in_Chrome__*`) を新規ドメインで使う前に、 「permission prompt が出る前提」 で workflow を組む (= 1 回 prompt がかかる前提で批准点を設計)

### 関連

- broker UI の domain-level block: §「ロックイン済 web app からのテーブル data 取得は scrape より export を優先」 末尾の「Browser MCP の制約」 参照
- 個人の母艦ブラウザ選定 (Brave 等) は personal layer (個人 dev-environment) で書く

## <a id="browser-download-automation"></a>ブラウザ MCP からの file download は user gesture 必須 (= scripted download の silent block)

**現象**: browser MCP (Claude in Chrome 等) で page 内 JS から download を発火させても、 **保存が一切実行されない** — blob + `<a download>` の `.click()` も `location.assign(<content-disposition URL>)` も、 browser の download 履歴 (History DB の `downloads` table) に **record すら残らず** 無音で落ちる。 extension/CDP 経由の合成 click も user gesture 扱いにならず、 link click での download も発火しない (= 実測、 Chromium 系)。 `fetch()` 自体は page 内で成功する (= bytes は取れている) が、 **base64 で tool 結果に持ち出すのは MCP 側 filter が block する** — これは data-exfiltration guard なので**回避しない** (chunk 分割等での evasion は禁止)。

**診断**: 「DL したはずが落ちてこない」 時は、 保存先 dir の監視より先に **browser の download 履歴 DB を直接読む** (= 稼働中でも DB copy → sqlite で `downloads` table)。 record が無ければ「保存先違い」 ではなく「発火していない」 が確定する。 併せて download URL が**期限付き token** (`?time=...` 等の signed param) を持つ場合、 stale な page から取った URL の fetch は **200 + login page HTML** を返す (= サイズが数 KB の HTML なら token 切れ。 page を reload してから再試行)。

**How to apply** — fallback ladder (上から順に):

1. **user の手 click** (= 物理的に browser の前にいる人に依頼。 リモート操作中の user は click できないことに注意 — 「どの機械の browser を操作しているか」 と「user がどこにいるか」 は別物)。
2. **cloud 共有リンク経由**: user が手元マシンで DL → cloud storage の共有リンク (Dropbox folder link は `&dl=1` で zip 一括) を chat に貼ってもらい、 worker 側で `curl -L`。 zip の filename mangling は cp437 → utf-8 re-decode で復元 (= office-automation の `zip-cp932-filenames` と同じ手当)。
3. **メール添付経由**: user が自分宛に添付送信 → Gmail 系 MCP の attachment download で取得。

**典型パターン**: SSO 保護の社内 groupware (掲示板 / ファイル管理) を logged-in browser session 越しに読むのは成功するが、 file 取得だけが上記 block で落ちる — 読み (get_page_text / find) と取得 (download) は別権限帯だと思って設計する。
