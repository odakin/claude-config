<!-- doc-meta
when: Claude desktop app (Code タブ等) の画面の挙動・文言の原因を、 docs や推測でなく app 本体で確かめたいとき + hook や規約が desktop の挙動を前提にする前 + 読んだ結論を user の画面で裏付ける実験を頼むとき
category: harness-core
summary: Claude desktop app の挙動を本体から確かめる手順。 置き場所 (画面 = Resources/ion-dist の minified JS と i18n JSON / main process = app.asar / 埋込 engine = Application Support の claude-code/<版>) と、 文言 → 翻訳 key → 描画 chunk → minified 名の import/export 付け替えを辿る → main process の順。 道具 = scripts/claude-app-bundle.py (version / i18n / grep --where renderer|asar|engine / resolve / slice / asar-ls)。 落とし穴 = 素の grep -o は MB 級の 1 行で時間切れ・名前は chunk ごとに付け替わる・版依存 (読んだ版を記録)・条件が複数 chunk に散ると読み切れない → user の画面 1 回で判別する実験 (仮説ごとに結果が分かれる入力を並べる + 答えの形を指定)。 実例 = claude-code-permissions.md#chat-link-resolution-base / macos-claude-app-notifications.md#app-notification-model
-->
# Claude desktop app の挙動を本体から確かめる

desktop app の画面の挙動 (リンクの開き方、 通知、 エラー文言の出し分け) は docs に書かれていないことが多い。 推測で規約や hook を書く前に、 **app 本体を読んで確かめる**。 本体は手元に全部あり、 読むだけなら何も壊さない。

## <a id="where"></a>置き場所 (macOS)

| 何 | どこ | 中身 |
|---|---|---|
| 画面 (renderer) | `/Applications/Claude.app/Contents/Resources/ion-dist/assets/**/*.js` | minified の JS chunk。 1 行が MB 級 |
| 画面の文言 | `…/Resources/ion-dist/i18n/<locale>.json` (`ja-JP` / `en-US` 等) | 翻訳 key → 文言。 key は chunk の中に `id:"<key>"` で現れる |
| main process | `…/Resources/app.asar` | 独自形式の archive。 session の設定 (作業フォルダ等) を決める側 |
| 埋込 engine (Claude Code) | `~/Library/Application Support/Claude/claude-code/<版>/claude.app/Contents/MacOS/claude` | 単一 binary。 文字列として JS が入っている (entrypoint の一覧など) |

道具 = [`scripts/claude-app-bundle.py`](../scripts/claude-app-bundle.py)。 読んだ結論には **`version` の出力 (app と engine の版) を添える** — 挙動は版で変わる。

## <a id="trace-from-screen-text"></a>画面の文言から原因を辿る

1. **文言 → 翻訳 key**: `claude-app-bundle.py i18n "このファイルが見つかりませんでした"` → key と英語原文。
2. **key → 描画 chunk**: `claude-app-bundle.py grep <key>` → どの chunk のどこで出しているか。 前後を読むと、 その文言を出す条件 (エラーの分類名など) が見える。
3. **分類を決める関数 → minified 名を辿る**: 条件の関数は別 chunk から `import{Gt as Se}from"./shared-….js"` のように**名前を付け替えて**持ち込まれている。 `claude-app-bundle.py resolve <chunk> <名前>` が import → export → 定義まで辿る (付け替えは段ごとに違うので、 手で grep すると別の関数に着く)。
4. **値の出どころ → main process**: 画面が受け取る値 (session の作業フォルダ等) を誰が決めるかは `grep <語> --where asar`。 関数を丸ごと読むときは `slice <asar の中の file 名> --where asar --find "async <関数名>(" --len 3000` (grep は前後の数百 bytes しか出さない。 grep が出した位置からなら `--at <offset>`)。
5. **engine 側の定数**: `grep <語> --where engine` (例: 環境変数が取りうる値の一覧)。

## <a id="pitfalls"></a>落とし穴

- **素の `grep -o '.{0,80}X.{0,200}'` は時間切れになる** (実測: 120 秒で終わらない)。 1 行が MB 級なので、 python の `re` で bytes に当てて前後だけ切り出す (本道具がそうしている)。 ugrep は長い正規表現で `exceeds complexity limits` になることもある。
- **同じ関数でも chunk ごとに名前が違う**。 ある chunk の `Se` と別 chunk の `Se` は無関係。 必ず import を辿る。
- **「コードにそう書いてある」 ≠ 「画面でそうなる」**。 条件が複数 chunk の plugin に散っていると、 読み切れないことがある。 読み切れない・結論が load-bearing なら、 次の実験で画面 1 回に決めさせる。
- **「見つからない」 ≠ 「読めない」 — 探す語を変える**。 実測: inline code をリンクにする条件は、 markdown の plugin 側から探して見つからず画面実験で決めたが、 後の検収で **描画する側** (mdast の node 型名 `inlineCode` と、 描画した要素の `data-…` 属性名を grep → その component が呼ぶ parser を `resolve`) から入ると、 数 KB の 1 chunk に正規表現ごと読めた。 入口の候補 = 画面の文言 (i18n) / node 型名 / DOM の属性名 / log に出る文言 (main process は失敗を `[…] could not resolve` のように log へ書くので、 **app の log の文言を `--where asar` で探す**と解決関数に直接着く)。
- **renderer の判定と main process の解決は別物**。 画面側 (renderer) は path の形で「中か外か」 を決めるだけで、 実際に file を探すのは main process の関数。 fallback (別の基準での再試行など) は main process 側にしか無いので、 renderer だけ読んで「解決の規則」 を書くと抜ける (実測: [`claude-code-permissions.md#chat-link-resolution-base`](claude-code-permissions.md#chat-link-resolution-base) の「本体が持つ fallback」)。
- **本体の log は実測の台帳になる**。 `~/Library/Logs/Claude/main*.log` に、 解決に失敗した path と試した基準が残る = 「実際に押されて開けなかった」 件数と形を、 会話記録からの推定でなく数えられる。

## <a id="screen-experiment"></a>読み切れないときは、 画面 1 回で決まる実験を頼む

- **仮説ごとに結果が分かれる入力を並べる**: 「形だけで判定」 と「実在を見て判定」 を分けたいなら、 **実在する path と実在しない path** を同じ形で並べて見てもらう。 1 つだけだと、 どちらの仮説でも同じ結果になりうる。
- **答えの形を指定する**: 確認を 2 つ以上頼むときの書き方 = [`concise-output.md#decision-questions`](concise-output.md#decision-questions) (実測: 短い返事「1」 が「1 つ目だけ」 とも「問い 1 は OK」 とも読めた)。
- 実験の入力を最終メッセージに置くときは、 自分の Stop hook に引っかからない形を選ぶ (例: [`hooks/chat-file-ref-enforce.sh`](../hooks/chat-file-ref-enforce.sh) は「どこにも無い path」 と「基準フォルダから在る path」 を拾わない)。

## <a id="instances"></a>実例

- chat のリンクの解決基準 (相対 path は session を始めたフォルダ、 Bash の cd に追従しない / 表示文言と原因の対応) = [`claude-code-permissions.md#chat-link-resolution-base`](claude-code-permissions.md#chat-link-resolution-base)
- 通知音の仕様 (完了通知は常に無音 等) = [`macos-claude-app-notifications.md#app-notification-model`](macos-claude-app-notifications.md#app-notification-model)
- hook が frontend を見分ける値 (engine の entrypoint 一覧) = [`hook-authoring.md#entrypoint-values`](hook-authoring.md#entrypoint-values)
