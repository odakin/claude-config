<!-- doc-meta
when: API を持たないアプリ (個人向けメッセンジャー・業務アプリ) で「届いたものを読む」 機械経路が要るとき + macOS の通知センター DB を script から読むとき + 読めずに Operation not permitted が出たとき
category: macos
summary: API の無いアプリでも、 macOS の通知として表示された内容 (題・副題・本文・時刻) は通知センターの SQLite DB に残る → 写しを取って読めば「受信を読む」 を段 4 に降ろせる (#mechanism、 engine = scripts/macos-notification-db.py)。 DB は TCC の下 = 起動側 app にフルディスクアクセス、 読めない時は exit 3 で 0 件と区別 (#tcc)。 限界 = app が起動していた間の通知だけ・消した通知は消える・本文は切れる (#limits)。 アプリは必要時に背景起動し、 自分が起こしたものは読み終わったら閉じる (#launch-on-demand / #close-what-you-launched)。 全部残すなら常時起動の機械 1 台で、 アプリが取り下げるより短い間隔 (変化の見張り) で写し取り、 暗号化した専用 repo に書き換えない束で積む (#always-on-archive / #retraction-window)。 取りこぼしは unified log の通知の要求と記録を時刻で突き合わせる定期の監査で機械が見る (#archive-audit)。 個人アカウントのプロトコルを模倣する非公式 client は使わない (#no-unofficial-client)。 定期の surface は「見た印」 の台帳と組にする (#seen-ledger)
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

- DB = `~/Library/Group Containers/group.com.apple.usernoted/db2/db` (SQLite、 WAL あり)。 ⚠️ 置き場所は macOS の版で違う (実測: 13 では `$(getconf DARWIN_USER_DIR)com.apple.notificationcenter/db2/db`)。 片方しか探さないと、 その版の機械では「DB が無い」 で黙る = engine の `default_db_path()` は在る方を使う。
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
  出ないアプリなら、 その分は画面で読むしかない。 届いたものを全部残したいなら、 必要時の起動でなく
  常時起動の機械で写し取る ([#always-on-archive](#always-on-archive))。
- SessionStart hook や dashboard からは GUI アプリを起こさない (起動は読みたい時の明示操作)。
- <a id="close-what-you-launched"></a>**自分が起こしたアプリは、 読み終わったら通常の終了で閉じる** (元から起動していたものは閉じない)。
  メッセンジャーには「PC 版を使っている間はスマホに通知しない」 類の設定があり、 起こしたまま放置すると
  持ち主のスマホに通知が来なくなる。 判定は「起動前に居なかったか」 で持ち、 終了の成否は AppleScript の戻り値でなく
  process が消えたかで見る (実測: quit に -128 を返しつつ実際には終了するアプリがある)。 kill はしない。
  quit は持ち主の環境への介入なので、 この設計自体を持ち主と決めてから入れる
  ([`macos-gui-app-automation.md#ask-before-quit`](macos-gui-app-automation.md#ask-before-quit))。

## <a id="always-on-archive"></a>全部残すなら: 常時起動の機械で写し取り、 暗号化した repo に積む

通知 DB は保存場所ではない (起動中の分だけ・消すと消える・OS が捨てる・アプリが取り下げる)。 届いたものを
全部残したいなら、 常時起動の機械 1 台でアプリを起動したままにし、 アプリが取り下げるより短い間隔で未記録の通知を写す
([#retraction-window](#retraction-window))。

- <a id="retraction-window"></a>**間隔は取り下げより短く (見張り + 1 分ごとの束)**: メッセンジャーは、 同じアカウントの別の端末
  (スマホ) で読まれたメッセージの通知を 1〜4 秒で取り下げることがある (実測) = 1 分ごとの写しではその分を落とす。
  DB と WAL の file の (mtime, size) を 0.5 秒ごとに stat し、 変わった時だけ DB を写して読む見張りを 1 本置く
  (stat は軽く、 読むのは変化の時だけ)。 束ねる・commit するのは 1 分ごとの側だけにする (commit の途中に束が増えない)。
  spool に足す側と束ねる側は同じ lock の下に置く (束ねている最中に足した行は、 索引にだけ載って二度と写されない)。
  見張りは heartbeat を書き、 1 分ごとの係が heartbeat の古さを見て起こし直す (2 本目は lock ですぐ抜ける)。
  applet を作り直すと付与が外れる (下の TCC) ので、 見張りは applet が毎回呼ぶ script が背景に起こす = 子は applet の
  フルディスクアクセスのまま読めた (実測)。 取りこぼしは人が突き合わせるのでなく、 下の監査が機械で見る ([#archive-audit](#archive-audit))。
- <a id="archive-audit"></a>**取りこぼしは定期の監査で機械が見る**: 写す係の失敗 (付与が無い・OS の通知の許可が無い・取り下げに
  間に合わない) はどれも「新着 0」 で黙る形になり、 人が気づくまで日が過ぎる (実測)。 写す係が 1 時間に 1 回、 背景で
  アプリの unified log (`log show --predicate 'process == "<App>" AND subsystem == "com.apple.UserNotifications"' --style compact`)
  を読み、 通知の要求 (`Adding notification request <id>`) の時刻と記録の時刻を数秒の幅で 1 対 1 に合わせる。
  `log show` は通知 DB と違い、 フルディスクアクセスの無い process からも読めた。 写す係の applet から起こした子でも読めた (どちらも実測)。
  要求の id は短縮された別の識別子で DB の uuid とは一致しない = 時刻で合わせる (DB の delivered の時刻との差は数十 ms 以内、 実測)。
  余った要求 (= アプリは通知を出したのに記録に無い) を手元の台帳に積み、 session の開始時の警告に出す。 同じ id の
  `Removing … delivered notifications with identifiers (` が続けば、 取り下げまでの秒も添える (見張りの間隔より短いかが分かる)。
  - unified log はこの subsystem だと数日で消える (実測) = 見つけた分は台帳に残し、 原因を確かめた印が付くまで警告を出し続ける。
  - `log show` は数秒〜数十秒かかる = session の開始時には回さず、 結果の file を読むだけにする。 1 時間ごとの起動は
    「起こした時刻」 で数える (監査が落ちても毎分は起こさない)。 監査そのものが止まった・失敗したときも警告に出す。
  - アプリの起動時の通知の許可の問い合わせの結果 (`Requested authorization [ didGrant: 0|1 ]`) も同じ log にある。
    OS の通知の許可が切れているとアプリは要求そのものを出さない = 要求と記録の突き合わせでは見えないので、 これで拾う
    (設定の plist は移行の後に古いまま残ることがあり、 今の設定を映さない = 実測)。 起動中に設定を変えた分は次の起動まで見えない。
  - 記録は束ねる係が動かしている最中に読むと、 束ねる途中の分が両方から消えて見える = spool と同じ lock の下で読む。
  - 台帳には時刻と要求の id だけを書く (送り主・本文は記録の repo にだけ置く)。
- **置き場**: 本文は持ち主と第三者のやりとり = 既定で全部暗号化した private repo (git-crypt の default-encrypt)。
  無人の commit を対話で使う repo に混ぜない (別 session の未 commit の変更で `pull --rebase` が止まる) = 専用の repo。
- **書き換えない束** (暗号文は差分が効かない = 理由と名付け方は [`repo-history-growth.md#encrypted-ledgers`](repo-history-growth.md#encrypted-ledgers)):
  毎分の写しは手元の spool (git 管理外) に溜め、 一定時間ごとに新しい file として束ねて commit する。
  重複は uuid の索引で除く (索引が消えても束から作り直せる形に)。
- **平文 push の防止**: commit した blob の先頭が暗号文の印 (`\0GITCRYPT`) かを確かめ、 違えば commit を戻して止める。
  unlock されていない clone では commit しない。 launchd の PATH には package manager の dir が無く、 filter の
  command が見つからないことがある = wrapper で PATH を足す。 試験 = 一時の bare remote に push する clone で、
  filter の clean を `cat` に差し替えて commit させ、 検出して commit を戻し push しないことを見る。
- **TCC**: 写す係は専用の applet にだけフルディスクアクセスを付ける ([`launchd-cloudstorage-tcc.md`](launchd-cloudstorage-tcc.md) の A')。
  applet を作り直すと ad-hoc 署名が変わって付与が外れる → やることは applet が毎回読む script に置き、 applet の source の
  hash を bundle に記録して、 変わった時だけ作り直す。
- **写す係は 1 台、 PC 版はその機械だけで使う**: メッセンジャーの PC 版は同時にログインできる台数が限られることがある (1 台など) = 別の機械で
  ログインすると写す係のアプリがログアウトされる。 持ち主が別の機械でも PC 版を使い続けると、 2 台が互いを追い出し、
  両方で再ログインを求められ続ける (実測)。 = PC 版を使う機械を写す係に決め、 写す係でない機械でそのアプリが起動していたら
  session の開始時に警告し、 そこからアプリを起こす道具は断る。 ログイン切れは機械で直接見えないので、 「記録の最新が N 日前」 を
  疑いとして出す (届いていないだけの可能性も併記)。 **記録が 0 件の間も同じ疑いを出す** (最新の時刻が無いと「古い」 の判定に乗らず黙る、 実測)。
  係そのものの停止は最終実行時刻で見る。
- **据え付けは最初の 1 件が記録に入るまで**: フルディスクアクセスの付け忘れ・アプリの未ログインは係のエラーの行にしか出ない。
  その行が一覧で件数に畳まれると、 係が設置から一度も写していなくても気づかれない (実測、 畳み方の規則 =
  [`hook-authoring.md#injection-digest-and-relay`](hook-authoring.md#injection-digest-and-relay))。 置いた turn で、 係の状態 (エラーの行が空・最終実行時刻) と
  最初の記録を確かめてから終える。 付与を待つなら、 エラーの行が消えるまで background で見張る。
- **読む側**: 記録の clone を読めば、 他の機械・フルディスクアクセスの無い session でも読める。 初めて読む機械で
  過去分が一気に出ないよう、 定期の surface は直近の窓だけにする。
- 起動したままにする以上 [#close-what-you-launched](#close-what-you-launched) のスマホ通知の設定を持ち主と確かめる
  (写す係の機械を普段だれも触らないなら、 「PC を使っていない時だけスマホに通知」 の類の設定でも実害は小さい)。

## <a id="no-unofficial-client"></a>非公式 client は使わない

個人アカウントのメッセンジャーには、 PC 版の内部プロトコルを模倣する非公式ライブラリがあることが多い。
技術的には CLI から読み書きできるが、 **利用規約違反でアカウント停止の実例が多く**・E2EE の復号も非公式実装頼み・
プロトコル変更で突然壊れる。 家族や取引先との連絡が載る個人アカウントを賭ける価値は無い → 読むのは本 doc の経路、
送るのは人。

## <a id="seen-ledger"></a>定期の surface は「見た印」 の台帳と組にする

SessionStart / dashboard で「新着」 を出すなら、 record の uuid → 見た日時 の台帳 (machine-local) を持ち、
**記録に落としたら `--mark-seen`** で消す。 台帳が無いと同じ通知が毎 session 出て壁紙になる。
「見た」 は「記録に落とした」 の意味で、 返信済みの意味ではない。
