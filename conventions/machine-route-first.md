<!-- doc-meta
when: 外部 service / アプリを操作・データ取得する経路を選ぶとき (画面 drive を検討し始めた瞬間)
category: harness-core
summary: 経路 ladder (dedicated MCP → API 直 → CLI → 経路を実装 → user 依頼 → 画面 drive) — 画面 drive は最終手段で、経路が無いときは「実装するのが先」 (#build-the-route-first = 実装した経路を auto-load 面に記録するまでが 1 単位)。 画面 drive の 3 重コスト (unreliable click / user のマシン拘束 / 対象取り違え) と許容例外
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
6. **画面 drive** — user が明示的に「やって」 と言った時、 または 1〜5 が全滅の時のみ

## <a id="screen-drive-costs"></a>画面 drive が最下位である理由

- **unreliable**: click 精度・画面読みは API 応答より誤りやすく、 対象取り違え等の error が混入する
- **user のマシンを拘束する**: drive 中 user は自分の環境を使えない。 この拘束コストは操作が成功しても常に発生する
- **遅い**: screenshot round-trip の積み重ねは API call の数十倍かかる

許容される例外は **read-only の screenshot で状態を確認するだけ**の場合と、 user の明示指示。 GUI の見え方確認はそもそも user に依頼する方が速い ([`office-automation.md` visual-check-by-user](office-automation.md#visual-check-by-user))。

## <a id="build-the-route-first"></a>build-the-route-first (経路が無ければ実装が先)

MCP / API / CLI の経路が**存在しない**と分かった時、 それは画面 drive に降りる理由ではなく**経路を実装する trigger**。 経路の実装は scope creep ではなく task の一部 — one-off の画面操作は消えるが、 実装した経路は以後のすべての session の資産になる。

実装の分業:

- **agent 側**: script / API wrapper の実装、 token の保管設計 (暗号化 + cross-machine 同期)、 冪等化、 selftest
- **user 側に切り出すのは認証境界だけ**: developer console での app 作成、 OAuth consent の Allow click 等、 agent が代行してはならない部分。 手順を番号付きで渡し、 済んだら agent が続きを引き取る

**実装した経路は auto-load される記憶面 (CLAUDE.md の scripts index 等) に記録するまでが 1 単位** — 経路は「次の session が見つけられる」 ことで初めて画面 drive を置換する。 記録がなければ次の session は再び画面に流れる。

OAuth を伴う実装では loopback consent の hardening 4 点 set ([`google-api-direct-access.md` oauth-loopback-hardening](google-api-direct-access.md#oauth-loopback-hardening)) を最初から適用する。

## 実例

2026-08-21: Dropbox 共有リンクの取得を Finder 右クリックの画面 drive で実施 → 対象フォルダの取り違え + user のマシン拘束が同時に起き、 user から経路選択そのものへの否定 feedback。 API 経路 (scoped app + PKCE、 [`dropbox-api-access.md`](dropbox-api-access.md)) の実装は初回 setup 込み ~15 分で、 以後は 1 コマンド ~2 秒になった。 「画面で 1 分 vs 実装で 15 分」 の比較は 1 回分しか見ていない — 経路は残り、 画面は残らない。

2026-08-28: claude.ai の共有会話を Claude Code に渡す経路が無く (WebFetch / curl / headless 全滅)、 スマホでは 1 message ずつの手動コピペしかなかった → **経路を 2 本実装**: ① in-app Browser pane での share URL 直読 (= agent 側の最短経路、 実は既存 tool が素通しだった) ② page-context API fetch のブックマークレット (= user 側 1 click export)。 手動コピペは消え、 経路は全 session の資産になった。 recipe = [`web-tools.md #claude-share-page-access`](web-tools.md#claude-share-page-access)。 注: bot 保護持ちサイトでは「経路を実装する」 と「保護を回避する」 の線引きが要る — 実ブラウザ + user click は前者、 headless 化・無人化は後者 (やらない)。

関連: [`google-api-direct-access.md`](google-api-direct-access.md) (Google の API 直叩き pattern) / [`dropbox-api-access.md`](dropbox-api-access.md) (Dropbox) / [`mcp.md`](mcp.md) (MCP 使い分け)
