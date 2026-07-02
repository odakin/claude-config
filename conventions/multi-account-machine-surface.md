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

以下 6 つが**全マシンで**成立していれば、 8 セルのどこからでも仕事が始められ・続けられる。 各 invariant は機械 check 可能にする (= 固定表に書いた「はず」 ではなく live 状態から検証する。 固定表は現実と drift する):

| # | invariant | 破れの症状 | 検出 / 修復 |
|---|---|---|---|
| I1 | 各マシンに RC server をアカウントごとに 1 本 (= 2 本) 常駐、 **アカウント固定の pinned config dir に載せる** (= 既定 `~/.claude/` は account が可変なので載せない。 pinned 方式なら interactive OAuth はマシン × アカウントごとに 1 回だけで永続 = account 切替が coverage に波及しない) | スマホで片方のアカウントにするとそのマシンが出てこない / 既定 dir の account 切替で片セル silent 消失 | session 開始時の coverage check が自動配備 + 未 auth なら 1 回きり OAuth 手順を surface ([remote-control-server.md #multi-account-servers](remote-control-server.md#multi-account-servers)) |
| I2 | alt config dir に `settings.json` / `skills` の guard-rail symlink | alt 名義 session だけ hooks / guard が効かない | alt server の install wrapper が symlink を self-healing |
| I3 | `remoteControlAtStartup: true` を全マシンに | そのマシンの手元 session がスマホから続行できない (= 新規は作れるのに続きができない非対称) | settings.json を machine ごとに確認 (machine-local ゆえ git 同期されない点に注意) |
| I4 | CLI 土台アカウントは **live fact** (固定 design にしない) + **マシン間でアカウントを分散** | 全マシンの土台が同一アカウントだと、 そのアカウントの rate limit 到達で全マシンの無人ルーチンが同時死する | 土台の現在値は `claude auth status` / 切替 helper で live 導出。 分散していれば「アカウント枯渇 failover = マシン failover」 が 1 動作になる |
| I5 | 無人ルーチンは active-host 台帳に bind + drift 検出 | 「切替えたつもり」 のアカウントとルーチンが実際に消費するアカウントの乖離 | [multi-machine-state.md #account-host-failover](multi-machine-state.md#account-host-failover) の台帳 + drift 検出 |
| I6 | pinned config dir は **headless-ready** (= workspace trust + RC 初回同意の flag が seed 済。 install script が install 時に自動 seed するので通常は自動成立、 残る interactive 段は OAuth 1 回のみ) | OAuth 済なのに server が dialog 待ちで exit-1 永久 cycling (= loaded だが process 無し) → そのマシン × アカウントの mobile セルが **silent 消失** | fleet-heartbeat の log marker (`trust_error` / `consent_pending`) を reader が 🔴/🟠 surface。 heal = install script 再実行 ([remote-control-server.md #ts-workspace-trust](remote-control-server.md#ts-workspace-trust)) |

## <a id="failure-modes"></a>典型的な破れかたと検出

- **auth 失効で server 群が silent 死**: launchd KeepAlive は process は再起動できるが auth は直せない。 長時間気づかない事故になりやすい → 無人成果物の heartbeat 監視 + session 開始時 coverage check が網
- **virgin config dir の headless 死 (I6)**: OAuth を通しても trust / consent の dialog flag が virgin だと launchd server は dialog を出せず exit-1 cycling。 「OAuth 1 回で開通」 の裏に interactive 段が 2 つ隠れていた (2026-07-02 実測) → install 時自動 seed で design-out 済 + heartbeat `trust_error` marker が backstop ([remote-control-server.md #ts-workspace-trust](remote-control-server.md#ts-workspace-trust))
- **desktop app 切替 ≠ CLI 切替の認知乖離**: app で B に切替えても無人ルーチンは A のまま消費 → I5 の drift 検出が surface
- **古い CLI が PATH 反転で優先解決され RC が死ぬ**: [remote-control-server.md #troubleshooting](remote-control-server.md#troubleshooting) の 3 パターン (version mismatch / API key 混入 / path_helper 反転)
- **auth の file-copy 誤解**: `.claude.json` を copy してもアカウントは移らない ([remote-control-server.md #account-auth-keychain](remote-control-server.md#account-auth-keychain))

## <a id="honest-limits"></a>正直な限界

- **マシン間の state は直接見えない**: マシン 1 から マシン 2 の server 稼働は直接 query できない。 見える経路は (a) スマホ / web の environment 一覧 (= そのアカウントに登録済みの生きた server が全部出る = 事実上の fleet view)、 (b) git-commit された台帳 / heartbeat。 「別マシンも動いているはず」 は必ずこのどちらかで verify する。 (b) を体系化した bounded-staleness の fleet view = [multi-machine-state.md #fleet-heartbeat](multi-machine-state.md#fleet-heartbeat) (= 毎時の自己報告 + role 別 staleness 判定。 「直接見えない」 が「数時間以内の異常は自動 surface される」 に狭まる)
- **スリープ中のマシンのセルは死んでいる**: 可搬機は蓋を閉じれば environment から消える。 これは仕様 (= 常時起動機を本番、 可搬機を best-effort と役割分けする)
- **remoteControlAtStartup の適用範囲**: CLI の対話 session に効くことは実測済。 desktop app 内 session への適用は環境により要実測 (= 設定後に新 session を開いて web / スマホの一覧に出るかで確認)

## Cross-refs

- RC server の機構・複数アカウント構成・auth の keychain 束縛・troubleshooting: [remote-control-server.md](remote-control-server.md)
- マシン間 state の規律・active-host failover: [multi-machine-state.md](multi-machine-state.md)
- 並列 session の race 防御 (= 同マシン内の別軸): [multi-session-coordination.md](multi-session-coordination.md)
- 無人ルーチンの登録機構: [scheduled-tasks.md](scheduled-tasks.md)
