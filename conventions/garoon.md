<!-- doc-meta
when: Cybozu Garoon (サイボウズ Garoon) の掲示板・ファイル管理・ポータルを Claude から読む/探すとき
category: infra
summary: Garoon cloud の browser-MCP 自動化 (= SSO でも logged-in session 越しに読める、 app 別 search URL 直叩き、 download token の期限切れ = login page 化、 file 取得は user gesture 必須)
-->
# Cybozu Garoon の browser-MCP 自動化

日本の組織で広く使われる groupware **Cybozu Garoon** (cloud 版 = `https://<org>.cybozu.com/g/`) を Claude から扱うときの機構 fact 集。 SSO (Shibboleth 等) 保護でも、 **user が logged-in している browser を browser MCP (Claude in Chrome 等) で駆動すれば読み取りは全部できる** — 「SSO だから Claude 経路無し」 と pre-conclude しない。 書き込み・file 取得だけが別権限帯 ([web-tools.md#browser-download-automation](web-tools.md#browser-download-automation))。

## App 別 URL (= UI を click で辿るより直 navigate が速い)

| app | URL | 備考 |
|---|---|---|
| ポータル | `/g/index.csp` | 掲示板の新着数件・通知一覧が 1 ページに出る = 巡回の入口 |
| 掲示板 | `/g/bulletin/index.csp` | ルート category は空に見える (= 掲示は subcategory 配下) |
| **掲示板 検索** | `/g/bulletin/search.csp?cid=1&text=<urlencoded>` | **本文全文検索**。 keyword で掲示 + 添付 PDF 内文まで hit する |
| ファイル管理 | `/g/cabinet/index.csp` | 各種申請書・様式の配布場所 |
| **ファイル管理 検索** | `/g/cabinet/search.csp?text=<urlencoded>` | file 名 + **file 内文**を検索 (= doc/pdf の中身も hit) |
| file download | `/g/cabinet/download.csp/-/<name>?fid=<N>&time=<token>` | ⚠️ 下記 token 期限 |

- ページ内検索 box への type は UI 状態依存で空振りしやすい — **search.csp への直 navigate が確実**。
- 検索結果は掲示/file の **snippet 込み**で返るので、 get_page_text だけで内容の大半が取れることが多い。

## Download token の期限切れ (= 200 + login page)

`download.csp` の URL は **`time=` 署名 token 付きで短時間で失効**する。 失効後の fetch は error でなく **HTTP 200 + login page HTML** (数 KB) を返す = サイズと `<title>ログイン</title>` で判別。 検索結果ページを reload して fresh な token を取り直してから扱う。 file の実取得自体は scripted download が silent block されるため [web-tools.md#browser-download-automation](web-tools.md#browser-download-automation) の fallback ladder (user click / cloud 共有リンク / メール添付) で運ぶ。

## 運用上の含意

- **「掲示板にしか出ない告知」 は mail 監視の構造的圏外** — 制度の募集 (期限付き機会) や全社通知は Garoon 掲示板が一次 channel のことがある。 不在主張 (「告知されていない」) の前に掲示板検索を回す。
- 掲示は**掲示期間**付き (= 期限後に消える)。 重要な掲示は本文を自リポの SoT に転記してから参照する。
- 組織固有の value (= subdomain / どの app に何があるか / folder 構成) は private 層に書く — 本 doc は機構 fact のみ。
