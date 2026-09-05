<!-- doc-meta
when: アカウント × マシン × 端末の複数セル運用を設計・診断するとき
category: harness-core
summary: アカウント × マシン × 端末 (desktop app / スマホ remote) の 2×2×2 を全部シームレスにする設計原理 (= 3 軸の本質差・切替 mechanics・seamless invariant I1-I9・破れの検出・cross-machine 不可視の正直な限界。 RC server / multi-machine-state / scheduled-tasks の全体像 doc)
-->
# multi-account-machine-surface.md — アカウント × マシン × 端末 の 2×2×2 を全部シームレスにする

複数の Claude アカウント (= 例: 個人 A / 予備 B) と複数のマシン (= 例: 常時起動のデスクトップ機 / 可搬でスリープするラップトップ) と複数の端末 surface (= Claude for Mac などの desktop app / スマホ・web からのリモート) を併用するとき、 **2×2×2 = 8 セルのどこにいても仕事が始められ・続けられ・移れる** ための設計原理。 個別機構の正本は各 doc にあり (下の cross-ref)、 本 doc は**全体像と invariant** を持つ。

## <a id="three-axes"></a>3 軸は本質が全部違う

| 軸 | 本質 | 切替が意味すること |
|---|---|---|
| **アカウント** | quota pool + 名義 (= rate limit 到達時の逃げ道、 会話履歴・environment 登録の namespace) | 「どの財布と登録簿を使うか」。 データ・ファイルは動かない |
| **マシン** | 計算資源 + ファイル + 常駐 server の所在 (= 常時起動 vs スリープの可用性差) | session は machine-bound で移動しない。 **仕事の実体は git で同期**され、 別マシンで新 session を開けば続きができる |
| **端末 (surface)** | 同じマシンへの driver の違い (= 手元の app か、 スマホ / web の遠隔か) | スマホは計算機を持たない = **どこかのマシン上の session の遠隔操作**。 surface を替えてもマシンとアカウントは替わらない |

軸を混同すると事故になる (= 「desktop app でアカウントを切替えたから無人ルーチンも切替わったはず」 → CLI 土台は独立で切替わっていない、 等)。

## <a id="axis-mechanics"></a>各軸の切替 mechanics (surface 別)

**アカウント切替**は surface ごとに独立した 3 経路がある:

| surface | アカウント切替の方法 | 影響範囲 |
|---|---|---|
| desktop app | app 内のアカウントスイッチャ | その app の対話 session のみ。 **CLI 土台・無人ルーチン・RC server には一切影響しない** |
| スマホ / web | app / site のアカウント切替 | 見える environment 群が切替わる (= environment 登録はアカウント namespace) |
| CLI / 無人ルーチン | `CLAUDE_CONFIG_DIR` で config dir を選ぶ | auth は config-dir 束縛 ([remote-control-server.md #account-auth-keychain](remote-control-server.md#account-auth-keychain))。 file copy では移らない |

**マシン切替** = git push → 別マシンで pull → 新 session。 session そのものは移らない (= 移す必要がない設計にする: 状態は repo の SESSION.md / plans / commit に置く)。

**surface 切替** = 2 種類を区別する:
- **新規 session を遠隔で生やす** → そのマシンに常駐する remote-control server ([remote-control-server.md](remote-control-server.md))
- **手元で開いた session の続きを遠隔でやる** → `remoteControlAtStartup: true` (machine-local `~/.claude/settings.json`) が対話 session を自動でリモート続行可能にする

## <a id="seamless-invariants"></a>Seamless の invariant (= 8 セル + セル間移動が全部生きている条件)

以下 9 つが**全マシンで**成立していれば、 8 セルのどこからでも仕事が始められ・続けられる。 各 invariant は機械 check 可能にする (= 固定表に書いた「はず」 ではなく live 状態から検証する。 固定表は現実と drift する):

| # | invariant | 破れの症状 | 検出 / 修復 |
|---|---|---|---|
| I1 | 各マシンに RC server をアカウントごとに 1 本 (= 2 本) 常駐、 **アカウント固定の pinned config dir に載せる** (= 既定 `~/.claude/` は account が可変なので載せない。 pinned 方式なら interactive OAuth はマシン × アカウントごとに 1 回だけで永続 = account 切替が coverage に波及しない) | スマホで片方のアカウントにするとそのマシンが出てこない / 既定 dir の account 切替で片セル silent 消失 | session 開始時の coverage check が自動配備 + 未 auth なら 1 回きり OAuth 手順を surface ([remote-control-server.md #multi-account-servers](remote-control-server.md#multi-account-servers)) |
| I2 | alt config dir に `settings.json` / `skills` の guard-rail symlink | alt 名義 session だけ hooks / guard が効かない | alt server の install wrapper が symlink を self-healing |
| I3 | `remoteControlAtStartup: true` を全マシンに | そのマシンの手元 session がスマホから続行できない (= 新規は作れるのに続きができない非対称) | settings.json を machine ごとに確認 (machine-local ゆえ git 同期されない点に注意) |
| I4 | CLI 土台アカウントは **live fact** (固定 design にしない) + **マシン間でアカウントを分散** | 全マシンの土台が同一アカウントだと、 そのアカウントの rate limit 到達で全マシンの無人ルーチンが同時死する | 土台の現在値は `claude auth status` / 切替 helper で live 導出。 分散していれば「アカウント枯渇 failover = マシン failover」 が 1 動作になる |
| I5 | 無人ルーチンは active-host 台帳に bind + drift 検出 | 「切替えたつもり」 のアカウントとルーチンが実際に消費するアカウントの乖離 | [multi-machine-state.md #account-host-failover](multi-machine-state.md#account-host-failover) の台帳 + drift 検出 |
| I6 | pinned config dir は **headless-ready** (= workspace trust + RC 初回同意の flag が seed 済。 install script が install 時に自動 seed するので通常は自動成立、 残る interactive 段は OAuth 1 回のみ) | OAuth 済なのに server が dialog 待ちで exit-1 永久 cycling (= loaded だが process 無し) → そのマシン × アカウントの mobile セルが **silent 消失** | fleet-heartbeat の log marker (`trust_error` / `consent_pending`) を reader が 🔴/🟠 surface。 heal = install script 再実行 ([remote-control-server.md #ts-workspace-trust](remote-control-server.md#ts-workspace-trust)) |
| I7 | session は**自分の worker host + account を会話ログに自己申告**する (= SessionStart hook が hostname / surface / **account** / session-id を注入し、 最初の返信の冒頭に 1 行 stamp。 account は harness metadata でなく whoami probe で引く 〔= §典型的な破れかた「session の自己アカウント同定を harness metadata で行う誤り」、 2026-08-28 追加〕。 stamp は会話ログに残るので **bridge が死んだ後も scroll-back で読める**。 タイトルには頼れない — RC の auto-name は hostname prefix 既定だが AI 自動タイトルが上書きすると消える 〔2026-07-02 実測〕) | bridged session が切断した時 (= [remote-control-server.md #ts-desktop-bridge-4090](remote-control-server.md#ts-desktop-bridge-4090)) 「どのマシンに行けば復旧できるか」 が UI から分からず、 host 特定が transcript / reflog の forensics になる (2026-07-02 実測 ~30 分) | 注入 hook は personal layer に配線。 ⚠️ desktop app は注入を drop ([hook-authoring.md #frontend-dependent-cowork](hook-authoring.md#frontend-dependent-cowork)) ゆえ CLI / RC session のみ有効 — **Desktop session の最初の tool call で whoami probe (`claude-session-whoami.py --stamp`) を実行**し、 その 1 行 (`🖥 <host> · <desktop|cli|rc>/<label> = <account> · session <id8>`) をそのまま最初の返信の冒頭に置く。 ⚠️ `hostname -s` 単独では account 軸が抜け、 harness の userEmail を信じて誤同定する (2026-08-28 + 2026-09-05 の 2 回、 後者は拡張の署名 account との一致判定まで誤り permission 障害の切り分けを 1 段飛ばした)。 surface 軸は 2026-09-05 から `rc/<label>` (= Remote Control server 配下、 プロセス祖先の cmdline で判定、 fail-open で `cli/`) を区別 — 「リモートか手元か」 も冒頭 1 行で読める。 surface file は補助であり、当該 tool result が worker host / account の ground truth。⚠️ 検証結果を **public surface** (公開 repo の file / commit message / issue) に書く時は hostname literal でなく属性 (「MacBook 側」 等) で書き、 具体値は個人層に置く (= 機器名はしばしば人名を含む。 2026-09-01 実 leak → force-push 修正の再発防止) |
| I8 | **無人ジョブは launchd + CLI 認証 only** — desktop app の scheduled task に置かない (= registry が account × app-install scoped で、 アカウント切替が旧 registry の enabled task を**黙って復活**させ、 移行済ジョブと二重実行 + session 一覧 noise になる。 2026-07-04 実測: swap から発覚まで 2 日 silent) | account swap 後に旧 scheduled task が並走 (= 同一ジョブの heartbeat 二重打刻 / recents に routine session が数十件積み上がる) | fleet-heartbeat が全 account registry の enabled task id を毎時収集、 reader が `--warn-desktop-tasks` で 🔴 surface ([multi-machine-state.md #fleet-heartbeat](multi-machine-state.md#fleet-heartbeat))。 解除 = 該当マシンの desktop app で enabled:false 化 ([scheduled-tasks.md #registrable-session-types](scheduled-tasks.md#registrable-session-types)) |
| I9 | **「picker に見える environment 群 = 常に現スマホ account のもの」 を運用知識として保持** (= 各マシン × account に env は 1 つずつ、 4 セル同時表示は platform 上あり得ない。 「どの account か」 の判別軸は env 名でなく**スマホアプリの現アカウント**) | 「意図しない account の session に入った」 と感じる (実際はスマホの現 account の env に正しく入っている = account 自覚の欠落、 2026-07-04 実測) / 「4 つ見えない」 と誤診 | ⚠️ **env の表示名は hostname 固定で configurable でない** (2026-07-04 実測: installer が `--name` + session-name-prefix に `<host>-<alias>` を焼いた server で env を fresh 登録させても label は hostname のまま。 flags は spawn session の**初期名**にのみ効き、 それも AI 自動タイトルが上書きし得る = I7)。 ゆえに機械対策は無く、 本 invariant は knowledge ([remote-control-server.md #multi-account-servers](remote-control-server.md#multi-account-servers)) |

## <a id="failure-modes"></a>典型的な破れかたと検出

- **auth 失効で server 群が silent 死**: launchd KeepAlive は process は再起動できるが auth は直せない。 長時間気づかない事故になりやすい → 無人成果物の heartbeat 監視 + session 開始時 coverage check が網
- **virgin config dir の headless 死 (I6)**: OAuth を通しても trust / consent の dialog flag が virgin だと launchd server は dialog を出せず exit-1 cycling。 「OAuth 1 回で開通」 の裏に interactive 段が 2 つ隠れていた (2026-07-02 実測) → install 時自動 seed で design-out 済 + heartbeat `trust_error` marker が backstop ([remote-control-server.md #ts-workspace-trust](remote-control-server.md#ts-workspace-trust))
- **desktop app 切替 ≠ CLI 切替の認知乖離**: app で B に切替えても無人ルーチンは A のまま消費 → I5 の drift 検出が surface
- **session の自己アカウント同定を harness metadata で行う誤り (2026-08-28 実測)**: desktop app の session に harness が注入する userEmail と、 `~/.claude.json` の `oauthAccount` は、 どちらも **CLI 認証層** (= `claude auth login` した account) を映す — desktop app が別 account でログインしていても、 である (機構: app は bundled CLI に自 account の `CLAUDE_CODE_OAUTH_TOKEN` を env で渡すだけで、 CLI はメタデータを自分の config から組む)。 CLI login ≠ desktop login のマシンでは **desktop の全 session が誤った user email を注入され**、 Claude がそれを信じて自分を別 account と誤同定する。 信じてよい signal は process env (`CLAUDE_CODE_ENTRYPOINT` が `claude-desktop` か / `CLAUDE_CODE_HOST_SESSION_ID`) + app の per-account session registry (`~/Library/Application Support/Claude/claude-code-sessions/<accountUuid>/…/<hostSessionId>.json` = path が account を運ぶ)。 **同定 probe = [`scripts/claude-session-whoami.py`](../scripts/claude-session-whoami.py)** (= registry → cmdline fallback → CLI config の順、 fail-open で「未同定」 を email で埋めない。 logic 詳細 = script docstring。 I7 stamp の account 軸もこれで引く)。 なお app 内 MCP の session metadata (`get_session`) には account field が無い (2026-08-28 実測) = MCP 経路では同定できない
- **ブラウザ拡張 (Claude in Chrome) の署名 account ≠ session account、 および再ログイン後の stale 接続 (2026-09-05 実測)**: 拡張は自分の account で署名され、 session と食い違っていても **MCP tool は繋がる** (= 「不一致なら繋がらないはず」 は誤り、 2026-08-29 の仮説を棄却)。 症状は navigate だけ通り read / screenshot / click が全部 `Permission denied for this action on this domain`、 かつ permission prompt が (旧署名側に飛ぶので) user に見えない = 「prompt render バグ」 と区別がつかない。 さらに拡張を正しい account で入り直しても、 session は**旧接続を掴んだまま** (`list_connected_browsers` に旧・新 2 本) で症状が続く。 切り分け順 = ① whoami で session account ② 拡張 options の署名 account と比較 (userEmail で比較しない) ③ `list_connected_browsers` で `connectedAt` 最新を `select_browser` → 新 tab group が user の窓に開き prompt も出る (recipe = [web-tools.md #chrome-domain-permission-model](web-tools.md#chrome-domain-permission-model) の How to apply)。 拡張の account 切替は接続と tab group を増殖させる副作用も持つ (旧 group は閉じて可)
- **pinned config dir の alias と実 auth の乖離 (= mobile セルの名義取り違え)**: I1 の pinned dir は「dir 名 = account」 が運用前提だが、 OAuth 時に browser が別 account を選ぶと **別名義で auth された server がラベルどおりの顔で動き続ける** (= picker には両方「生きて」 見えるので silent)。 検出 = セル状態 check が dir 名と実 auth の email を突合して mismatch を 🔴 surface。 修復 = その dir で `claude auth login` をやり直し → server を kickstart — ⚠️ この OAuth が乖離の発生機構そのもの: **account 選択画面を出さず browser の claude.ai cookie の account で無言で通る**。 正しい account で認可する手順の正本 = [remote-control-server.md #oauth-grabs-browser-account](remote-control-server.md#oauth-grabs-browser-account)
- **古い CLI が PATH 反転で優先解決され RC が死ぬ**: [remote-control-server.md #troubleshooting](remote-control-server.md#troubleshooting) の 3 パターン (version mismatch / API key 混入 / path_helper 反転)
- **auth の file-copy 誤解**: `.claude.json` を copy してもアカウントは移らない ([remote-control-server.md #account-auth-keychain](remote-control-server.md#account-auth-keychain))
- **ブラウザ拡張 (Claude in Chrome) のアカウント軸の見落とし (2026-08-20 実測)**: 拡張は Claude アカウントに署名して動き、 MCP 側の domain 許可・接続の観察は**拡張の署名アカウント**に紐づく。 session のアカウントと拡張の署名アカウントが食い違うと、 (a) 片方のアカウントで確認した権限設定が実際に動いている拡張には効いておらず、 (b) tool の失敗が `Permission denied for this action on this domain` / `Navigation to this domain is not allowed` と**ドメイン名指し**で返るため「このドメインはカテゴリ的にブロックされる (政府系 / 金融系)」 という**もっともらしい誤診**に誘導される (実測 = 官公庁系申請システムで誤診)。 第一手 = domain policy を疑う前に**拡張の署名アカウントを確認** (拡張アイコン → アカウント表示、 session 側は whoami probe — ⚠️ userEmail は desktop session では CLI 土台を映す嘘になり得る = 上の「harness metadata」 bullet)。 副作用 = 署名切替をまたいで接続し直すと **MCP タブグループが接続ごとに増殖** (旧 group が会話タイトル名で遺物として残る) — 旧 group のタブは閉じて良い。 なお claude.ai web タブのアカウント (= cookie) は拡張の署名とも session とも独立の**第 3 の軸**で、 「どの面がどのアカウントか」 は面ごとに個別確認が要る。 **MCP 接続の成立要件 (2026-08-29 RCA)** = 拡張の署名 account == **session の実 account** (`list_connected_browsers` は account-scoped の cloud relay を「this account」 で query する。 desktop session の実 account は app ログイン側 = whoami probe で同定、 claude.ai サイトの cookie login は無関係)。 拡張サイドパネルの警告「You're signed into claude.ai as a different account…」 は**サイト cookie vs パネル/拡張**の軸の話で、 MCP 接続要件 (= session vs 拡張) の診断根拠にしない — 実測事故: 警告文を接続障害の原因と誤読 + session 側を `.claude.json` 直読 (= CLI 土台の嘘) で誤同定した結果、 「account 一致なのに繋がらない」 という**偽の謎**と**逆方向の拡張切替誘導**が同時発生した。 診断は必ず ① whoami で session 実 account → ② 拡張 icon で署名 account → ③ 不一致なら拡張側を合わせる、 の順。 ①② 一致でも `[]` の場合は **relay 登録層の故障** (= パネルのチャットが正常でも automation bridge は別経路で未登録でありうる。 `switch_browser` broadcast が待機なしで「No other browsers available」 = relay にその account の拡張 instance ゼロ) → 復旧 runbook = [mcp.md #runbook-root-cause-checklist](mcp.md#runbook-root-cause-checklist)

## <a id="honest-limits"></a>正直な限界

- **マシン間の state は直接見えない**: マシン 1 から マシン 2 の server 稼働は直接 query できない。 見える経路は (a) スマホ / web の environment 一覧 (= そのアカウントに登録済みの生きた server が全部出る = 事実上の fleet view)、 (b) git-commit された台帳 / heartbeat。 「別マシンも動いているはず」 は必ずこのどちらかで verify する。 (b) を体系化した bounded-staleness の fleet view = [multi-machine-state.md #fleet-heartbeat](multi-machine-state.md#fleet-heartbeat) (= 毎時の自己報告 + role 別 staleness 判定。 「直接見えない」 が「数時間以内の異常は自動 surface される」 に狭まる)
- **スリープ中のマシンのセルは死んでいる**: 可搬機は蓋を閉じれば environment から消える。 これは仕様 (= 常時起動機を本番、 可搬機を best-effort と役割分けする)
- **remoteControlAtStartup の適用範囲**: CLI の対話 session に効くことは実測済。 desktop app 内 session への適用は環境により要実測 (= 設定後に新 session を開いて web / スマホの一覧に出るかで確認)

## Cross-refs

- RC server の機構・複数アカウント構成・auth の keychain 束縛・troubleshooting: [remote-control-server.md](remote-control-server.md)
- マシン間 state の規律・active-host failover: [multi-machine-state.md](multi-machine-state.md)
- 並列 session の race 防御 (= 同マシン内の別軸): [multi-session-coordination.md](multi-session-coordination.md)
- 無人ルーチンの登録機構: [scheduled-tasks.md](scheduled-tasks.md)
