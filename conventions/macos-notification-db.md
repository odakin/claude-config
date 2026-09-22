<!-- doc-meta
when: API を持たないアプリ (個人向けメッセンジャー・業務アプリ) で「届いたものを読む」 機械経路が要るとき + macOS の通知センター DB を script から読むとき + 読めずに Operation not permitted が出たとき
category: macos
summary: API の無いアプリでも、 macOS の通知として表示された内容 (題・副題・本文・時刻) は通知センターの SQLite DB に残る → 写しを取って読めば「受信を読む」 を段 4 に降ろせる (#mechanism、 engine = scripts/macos-notification-db.py)。 DB は TCC の下 = 起動側 app にフルディスクアクセス、 読めない時は exit 3 で 0 件と区別 (#tcc)。 限界 = app が起動していた間の通知だけ・消した通知は消える・本文は切れる (#limits)。 アプリは必要時に背景起動 (#launch-on-demand)。 個人アカウントのプロトコルを模倣する非公式 client は使わない (#no-unofficial-client)。 定期の surface は「見た印」 の台帳と組にする (#seen-ledger)
-->
# macOS の通知センター DB から、 API の無いアプリの受信を読む

API を持たないアプリでも、 **macOS の通知として表示された内容は通知センターの DB に残る**。 これを読めば
「届いたものを読む」 だけは経路 ladder の段 4 (自作経路) に降ろせる
(ladder = [`machine-route-first.md#route-ladder`](machine-route-first.md#route-ladder))。
送る側はこの経路では扱えない = 送信は人の指のまま (不可逆操作でもある)。

engine = [`scripts/macos-notification-db.py`](../scripts/macos-notification-db.py)
(`--list-apps` / `--app <bundle id>` / `--since 48h` / `--json` / `--selftest`)。
アプリ固有の既定 (bundle id・起動・見た印) は各自の層で shim にする。

## <a id="mechanism"></a>機構

- DB = `~/Library/Group Containers/group.com.apple.usernoted/db2/db` (SQLite、 WAL あり)。
- **本物を開かず、 DB + `-wal` + `-shm` を一時 dir に写してから読む** (通知 daemon を lock しない・
  checkpoint されていない新しい通知も読む)。
- 形 (実測 = macOS 26。 他の版は初回に `--list-apps` で表と件数が出るかを見る):
  表 `app` (app_id, identifier = bundle id) と `record` (app_id, uuid, `data` = binary plist,
  `delivered_date` = 2001-01-01 起算の秒)。 plist の `req` に `titl` (題 = 多くは送り主) / `subt` / `body`。
- `app` 表に行がある = 通知の登録がある、 だけ。 record が 0 件なら「まだ 1 件も残っていない」
  (起動していない・届いていない・消された・OS の通知設定で止まっている、 の区別はつかない)。
- 形が違う record は 1 件だけ落として続ける (全体を落とさない)。

## <a id="tcc"></a>TCC (フルディスクアクセス)

- DB は TCC の保護下。 付与が無いと dir の一覧すら `Operation not permitted`。
  ⚠️ `Path.exists()` は EPERM を False に畳む = 「無い」 と「読めない」 が同じに見える →
  `os.listdir(parent)` の `PermissionError` で区別する。
- 読めない時は **exit 3 + 理由 1 行** (= 検査が走っていない合図。 0 件の 0 とも違反の 1 とも別の値、
  [`convention-design-principles.md#failure-exit-equals-violation-exit`](../docs/convention-design-principles.md#failure-exit-equals-violation-exit))。
  定期の surface 側はこれを「未チェック」 として見せる (黙って 0 件にしない)。
- 付与の対象 = **script を起動した側の app** (Terminal / Claude Code desktop / IDE)。 launchd から読むなら
  狭い applet に付与する ([`launchd-cloudstorage-tcc.md`](launchd-cloudstorage-tcc.md) の A' pattern)。
- <a id="tcc-responsible-process"></a>**「起動した側」 は親 process を辿って確かめる** (推測で app 本体に付けない):
  `p=$$; while [ "$p" -gt 1 ]; do ps -o pid=,ppid=,comm= -p $p; p=$(ps -o ppid= -p $p); done`。
  実測: Claude Code desktop の Bash は app 本体 (`/Applications/Claude.app`) でなく、
  `~/Library/Application Support/Claude/claude-code/<版>/claude.app` の helper から起動されていて、
  app 本体に付与済みでも読めず、 helper 側の付与で読めた。 ⚠️ path に版番号が入る = **版が上がると
  付与が切れる可能性がある** (設定画面に同名の項目が版の数だけ並ぶのがその痕跡)。 exit 3 が戻ったら親を辿り直す。
- 付与はシステム設定の操作 = **人が 1 回**。 実測では起動中の process にも再起動なしで効いた
  (効かなければ起動側 app を再起動してから確かめる)。 設定画面を直接開く =
  `open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"`。

## <a id="limits"></a>限界 (出力の読み方に効く)

- **そのアプリが起動していた間**に表示された通知しか無い。
- 通知センターで消した (×) 通知は DB からも消える。 古い通知も OS が捨てる。
- 本文は通知に載った長さで切れる。 アプリ側に「通知に内容を表示しない」 設定があると本文が定型文になる →
  全件が定型文なら設定を疑う 1 行を出す。
- 同じメッセージがバナーと通知センターで重複することは無い (1 record) が、 アプリが既読化で通知を
  取り下げると消える。 **「DB に無い」 は「届いていない」 ではない** — アプリの画面が正本。

## <a id="launch-on-demand"></a>アプリは必要な時に背景起動する

- 普段アプリを起動していないなら、 読みたい時に `open -g -a <App>` (背景起動) → 同期を数十秒待って読む。
- **閉じていた間に届いた分が、 起動時に通知として出るかはアプリ次第** = 1 回実測して shim の docstring に書く。
  出ないアプリなら、 その分は画面で読むしかない (起動しっぱなしにするかは持ち主の判断)。
- SessionStart hook や dashboard からは GUI アプリを起こさない (起動は読みたい時の明示操作)。

## <a id="no-unofficial-client"></a>非公式 client は使わない

個人アカウントのメッセンジャーには、 PC 版の内部プロトコルを模倣する非公式ライブラリがあることが多い。
技術的には CLI から読み書きできるが、 **利用規約違反でアカウント停止の実例が多く**・E2EE の復号も非公式実装頼み・
プロトコル変更で突然壊れる。 家族や取引先との連絡が載る個人アカウントを賭ける価値は無い → 読むのは本 doc の経路、
送るのは人。

## <a id="seen-ledger"></a>定期の surface は「見た印」 の台帳と組にする

SessionStart / dashboard で「新着」 を出すなら、 record の uuid → 見た日時 の台帳 (machine-local) を持ち、
**記録に落としたら `--mark-seen`** で消す。 台帳が無いと同じ通知が毎 session 出て壁紙になる。
「見た」 は「記録に落とした」 の意味で、 返信済みの意味ではない。
