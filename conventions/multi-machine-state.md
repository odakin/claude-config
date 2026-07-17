<!-- doc-meta
when: 複数マシンで同じ Claude Code setup を運用・audit するとき
category: harness-core
summary: 複数マシンで同じ Claude Code セットアップを使うときの規律 (audit scope 明示・実機検証・idempotent setup.sh)
-->
# multi-machine-state: 複数マシンで同じ Claude Code セットアップを使うときの規律

複数マシン (家・職場、ノート・デスクトップ等) で同じ `~/Claude/` (または等価な base dir) を運用する場合、**マシンごとに state が drift する** 前提で設計・記録・audit する。

## State の分類: 何が同期され、何がしないか

| 種類 | 例 | 同期手段 |
|---|---|---|
| Repo content | 各 repo の commit 内容 | `git pull` (repo ごと) |
| 共通設定 | `~/.gitignore_global` / Claude Code hooks / CONVENTIONS.md symlink | `claude-config/setup.sh` Step 6 の post-merge hook で claude-config pull 後に自動同期 |
| マシンローカル state | `~/.claude.json` (MCP 登録) / OAuth tokens / アプリの Local Storage 等 | **同期されない**。マシンごとに独立。各 repo の冪等な `setup.sh` を再走して揃える |

「同期されない」カテゴリの存在を意識しないと、片方のマシンで commit した doc 変更が反映されても、ローカル state は古いまま、という drift が静かに広がる。

## Audit 結論には scope を明示する

「実態を再検証した」「全件確認した」と書く audit セッションは、**観察したマシン (どの machine で実行したか) と観察した時刻** を結論文に明記する。書き忘れると、別マシン上の Claude が結論を canonical と誤読し、別マシンの state を上書きしてしまう。

NG:

> 監査の結果、X は不在で、Y パッケージは一度も install されていなかった。

OK:

> [<machine-A> 上で <date> に実行した] 監査の結果、本マシンでは X は不在で、Y パッケージはこのマシンでは install されていなかった。他マシンの state は別途検証が必要。

audit を実行するマシン名は事後の commit message にも書いておくと、後で git log を遡る時に scope を取り違えない。

## 「実装は走らなかった」「patch は no-op だった」型の断定は実機検証してから書く

Audit narrative で **implementation reality を否定する断定** (「実装されていない」「target file が存在しないので空打ち」「該当箇所は走らなかった」等) は、narrative 推論ではなく `ls` + `stat` (mtime / size) / 実機ファイル内容で確認してから書く。「推定」とコメントを添える時点で、推定対象の実機検証を踏むコストは ls 1 回分しかない — 必ず踏む。

narrative 推測のまま canonical doc に書くと、別マシン上で覆る (= drift) 可能性が高く、結果として「過去の自分が書いた audit 結論」と「今の実機状態」がループ的に矛盾する状況に陥る。

## マシン間 drift の reconciliation 経路: idempotent setup.sh

State drift が起きうる箇所 (= 上の「マシンローカル state」) では、**idempotent な `setup.sh` を canonical reproducer として用意**する。各マシンで再走すれば差分だけ埋まる、という経路を確保しておく。

冪等化のキー:

- **既存 state を検出して skip**: 例として、トークンが既に配置されているならコピーと OAuth フローを skip。「上書きしてからやり直し」ではなく「足りないものだけ補う」を default にする
- **旧 state を検出して migrate**: 古いパッケージ登録を `remove` してから新パッケージを `add`、のような「state machine の遷移」を script に閉じ込める
- **target を引数 / 環境変数で明示できるようにする**: cwd 依存にしない (cf. 同ディレクトリの [`mcp.md` claude-mcp-project-resolution](mcp.md#claude-mcp-project-resolution))。スクリプト冒頭で `cd "$TARGET"` する形にして、cwd 暗黙依存をなくす

これが揃うと、drift 検出時の reconciliation はマシンごとに `setup.sh` を再走するだけで完了する。再走が destructive (token を破壊する等) だと「念のため再走」をしづらく、drift の発見も遅れる — 冪等性は drift 検出の前提条件でもある。

## machine-local 定期ジョブのホスト判定 (= どのマシンで走らせるか)

launchd / cron の定期ジョブは **登録したマシンでだけ走る**。 フリートに複数マシンがあると「常時起動でジョブを担うべきホスト」 を 1 台に決め、 そこだけに登録する (= ノート等の non-always-on マシンには登録しない)。

ジョブ script 側で「自分は稼働ホストか」 を判定したい時 (= 非ホストでは沈黙する surface 等) は **arch (`uname -m` / `platform.machine()`) や hostname を programmatic discriminator** に使う。 arch はフリートが arch で割れている場合 (例: 常時起動機 = x86_64 / ノート = arm64) に簡潔で堅牢。

- **判定は config 値に外出し + env で override 可能に**する (= 別 arch のマシンから両分岐を test できる)。 例: `host_arch` を config に置き、 `platform.machine()` と比較、 test 用に env `..._HOST_ARCH` で上書き
- arch 判定は fleet 構成 (= どのマシンが何 arch か) に依存する **cross-machine な比較 fact**。 これは個人レイヤー (= 各 user の machine 構成 doc) に置く。 本 public 規約には具体 arch を hardcode しない
- 将来 arch が揃う (例: 全マシン Apple Silicon 化) と arch discriminator は効かなくなる → hostname / 明示 marker file へ移行

### <a id="account-host-failover"></a>account / host failover: active-routine-host 台帳 + gate

上の「1 台に決める」 は、 その 1 台の**土台アカウントが使えなくなる** (= 週間 usage 制限・障害・別作業に枠を回したい) と全ルーチンが止まる single point。 別マシン / 別アカウントへ **素早く・繰り返し** failover したいときは、 候補マシン全部にジョブを (gate 付きで) install しておき、 **git-commit した台帳 1 ファイルが「今の本番ホスト」 を決める** 構成にする:

- **台帳** (例 `active-routine-host.json`、 同期 repo 内) = `{"host": "<hostname-short>", "account": "...", "since": ..., "reason": ...}`。 load-bearing は `host` だけ (= gate が見るのはこれ)、 残りは人間 / 監視 surface 用。
- 各ジョブの wrapper は実行頭で **gate** (`scripts/routine-host-gate.py <repo> <ledger-relpath>`) を呼び、 台帳の `host` が自分でなければ静かに **defer** (exit 0、 = ジョブを走らせない)。
- gate は **fail-open**: 台帳が無い / 壊れている / host 欄が空なら「ゲート無し」 として普通に走る。 = 台帳の事故で全ルーチンが沈黙することはない (= 安全網は止めない側に倒す)。
- gate は最新の **committed** 台帳を読む (best-effort `git fetch` → working-tree fallback)。 standby マシンは新台帳が push された瞬間に従う (= 手動 pull 不要)。
- **failover = 台帳の `host` を書き換えて push するだけ** (install / uninstall 不要)。 launchd cron engine ([`scheduled-tasks.md` launchd-cron-engine](scheduled-tasks.md#launchd-cron-engine)) の `--gate "<snippet>"` が wrapper に gate を焼く (`cd && <gate> || exit 0; exec <routine>`)。
- ⚠️ gate は **両マシンの plist に焼かれて初めて両方向対称**。 旧 install (gate 無し) のマシンは台帳に関係なく走るので、 そのマシンを standby にしたいなら一度 install し直して gate を焼く (それまでは「そのマシンの土台アカウントが止まっている」 ことに依存)。
- ⚠️ **headless 実行アカウントには `claude auth login` で確立した generation-capable な CLI OAuth が要る**。 Claude Code desktop app が対話シェルに注入する session token は **launchd には来ない**。 `claude auth status` が `loggedIn:true` を返しても、 env token 無しの headless 生成は **401 になりうる** (= keychain の credential が refresh 切れ等で生成に使えない)。 → **failover 先マシンでは事前に `claude auth login` を済ませて headless 401 が出ないことを確認する** (= 実 launchd で 1 回 kickstart して log を見るのが確実、 対話シェルからの nested `claude -p` は別 session guard / env 汚染で当てにならない)。

## zero-setup な cross-machine surfacing (= 別マシンの「やるべきこと」 を浮上させる)

「マシン B でやるべき作業 (= 例: machine-local job の install)」 を **マシン B で何も setup していない段階から**自動で浮上させたい時、 surface 機構を **マシン B で既に配線済 ∧ source が git-synced** な経路に相乗りさせる。 そうすれば `git pull` だけでマシン B に届く (= 新規 wiring 不要)。

- ✅ 相乗り可: **既存の SessionStart hook** (= source が synced repo にあり、 マシン B では symlink で配線済) の中身を編集 → pull で反映 / 既に統合済の dashboard 等の surface 経路
- ❌ chicken-and-egg: **新規 hook を足す**と、 マシン B で hook installer の再実行 (= symlink 作成 + settings 配線) が要る = それ自体が「マシン B でやるべき setup」 → 「setup する前に setup を促したい」 が回らない
- 判定ロジックは 1 実装に集約し (= 例 `<tool> --install-check` が「ホスト ∧ 未 install ∧ repo synced」 を判定して 1 行返す or 空)、 既配線の複数 surface (SessionStart hook + dashboard) から呼ぶ。 install 完了で機械的に沈黙する条件 (= job が登録されたか launchctl 等で検出) を入れる
- 既配線 hook に相乗りする時は、 その hook の既存 test を壊さないようガード (= test harness が立てる env flag では追加 surface を skip する等)

## <a id="fleet-heartbeat"></a>Fleet heartbeat — cross-machine state の bounded 可視化

マシン A からマシン B の launchd server / auth 状態は直接 query できない ([multi-account-machine-surface.md #honest-limits](multi-account-machine-surface.md#honest-limits))。 この不可視を **各マシンの自己報告を git 経由で集約**する pattern で bounded staleness の fleet view に変える:

- **writer** = [`scripts/fleet-heartbeat.py`](../scripts/fleet-heartbeat.py) (generic engine): 毎時の launchd cron が自マシンの remote-control server 群 (launchd loaded + **server ログ末尾の marker parse** = "Connected" / auth error / version error) + config-dir auth metadata + **desktop app 全 account registry の enabled scheduled task id** (= account 切替による旧 task 復活の監視、 2026-07-04 追加) + 設定を `<repo>/<subdir>/<hostname>.json` にまとめて commit + push
- **reader** = [`scripts/check-fleet-status.py`](../scripts/check-fleet-status.py): 全マシン分を読み、 role 別に異常を surface (always-on マシンの heartbeat 停止 = 🔴 / best-effort マシンのスリープ = 仕様で silent / どのマシンも beat が新鮮な時の server 異常 = 🔴 / `--warn-desktop-tasks` 指定時は enabled な desktop scheduled task = 🔴 〔= launchd-only 方針マシン向け opt-in、 [multi-account-machine-surface.md](multi-account-machine-surface.md) I8〕)

設計原則 (詳細 = 各 script docstring が SoT):

1. **監視が監視対象に依存しない**: writer は `claude` コマンドを一切呼ばない (launchctl / log parse / git のみ)。 auth 失効で server 群が全滅しても heartbeat は動き続け、 その全滅をログ marker で報告できる (= auth 失効 → 数時間内に他マシンで 🔴、 という検出線。 実 incident: 常時起動機の auth expire で server + cron 群が ~19.5h silent 死、 検出は成果物 staleness の間接信号頼みだった)
2. **state-change-or-age commit policy**: essence が変わった時 + 一定時間経過時のみ commit (= git history を汚さない。 liveness 上限 = interval + cron 周期)。 ⚠️ **読み手への注意 — beat の欠落を即異常と誤読しない**: beat は「毎時」 ではない。 状態変化がなければ commit 間隔は最悪 interval + cron 周期 (既定 4h + 1h ≒ 5h、 境界判定が interval 未満と判定して 1 周期余分に skip する off-by-one 込み) まで開くのが**正常動作**。 実例 (2026-07-02): 「毎時 beat」 前提で 4 回連続の欠落を『heartbeat 停止 = マシン死の疑い』 と 2 度誤診したが、 実際は全て設計どおりの skip で系は終始健全だった。 reader の `--stale-hours` はこの上限より大きく取る (既定 6h > 5h)
3. **gate 対象外**: [account/host failover](#account-host-failover) の gate は「本番ホストだけが走る」 ためのものだが、 heartbeat は**全マシンが各自を報告してこそ意味がある** → gate を掛けず、 label prefix も分離する (= gate 検査機構の「gate 無し二重実行」 警告と衝突させない。 全マシン同時実行は仕様: 各マシンが別 file に書くので競合しない)
4. **reader は fetch しない**: 読むのは working tree = 呼び出し側 (dashboard の一斉 fetch / session 開始時の pull) が鮮度を担う。 ⚠️ **系 (= 逆向き偽アラーム)**: heartbeat repo の local clone が behind / diverged のまま reader が走ると、 実際には健在な**他マシン**が「heartbeat 停止 = silent 死」 に見える (= 自分の同期不全が**相手の死**として表示される、 向きが反転するのが罠)。 always-on マシンの 🔴 を結論する前に、 heartbeat repo 自体を `git fetch` + behind/ahead 確認する 1 コマンド verify を挟む (実 incident 2026-07-10: 片マシンの divergence が反対マシンの偽 125h-silent 🔴 を生んだ — 「死んだ」 とされた側は健在で通常稼働中、 偽アラームは ~20 分事実として扱われた)。 この verify 手順は reader の 🔴 finding 文面自体に焼き込んである (= 消費点に routing を運ぶ、 2026-07-17)。 ⚠️ **偽アラームの第 3 形態 = 読み手側の surface file 残留**: reader の finding を SessionStart hook が surface file に cache する構成では、 findings 解消後も**古い 🔴 が file に残留**しうる (= cleanup path が early-exit で dead code 化する ordering bug、 実 incident 2026-07-17: 解消済み finding が 9 日間残留し「heartbeat 停止中」 と誤読される状態だった)。 write-or-delete ordering の一般則 = [hook-authoring.md #surface-file-cleanup-ordering](hook-authoring.md#surface-file-cleanup-ordering)。 clone staleness (= 本原則) と surface staleness (= 第 3 形態) は独立に起きる — 🔴 を見たら「finding の生成時刻はいつか」 も疑う
5. **writer の push 経路は他 session の残置に耐える (= `pull --rebase --autostash`)**: autostash なしだと、 他 session が残した**無関係な dirty file** で rebase が拒否される → beat は local commit に積み上がるだけで push されず、 (a) fleet からこのマシンが silent 死に見える (= 監視機構自身が監視対象と同じ症状を呈する) + (b) このマシン自身の fleet view も stale 化する (= 双方向の盲目、 原則 4 の逆向き偽アラームの発生源)。 `--autostash` は dirty をまたいで beat を流す (残余 risk = stash pop conflict だが、 dirty で 100% wedge する旧挙動より strictly better、 fail-open 契約内)。 実測 RCA (2026-07-10、 dirty 残置 2 日で divergence 76/12 commit まで雪だるま化) の詳細 = `fleet-heartbeat.py` 内 comment

## 関連

- 同じ system に対する別マシンの観察結果を比較する経路は、各 repo の `DESIGN.md` に「<date> の machine-X observation」の節を立て、別マシンでの観察を追記する形で蓄積するのが追跡しやすい (「audit を上書きする」のではなく「audit に scope qualifier と別マシン観察を追加する」アプローチ)
- 定期ジョブの機構選択 (launchd / cron / scheduled task / GitHub Actions) は [`scheduled-tasks.md` execution-locus-selection](scheduled-tasks.md#execution-locus-selection)。 hook の配信正常性 audit は [hook-authoring.md](hook-authoring.md)
- マシン横断の repo pull 経路は各ユーザーの個人レイヤーで決める (例: 個人スクリプト `pull-all.sh` を持つ等) — 本リポ public 共通規約には組み込まない
- マシン固有の install 不可な package (= `brew install foo` の試行失敗) の蓄積規律は [`install-failures.md`](install-failures.md) — layer 4 (machine-local memory) に試行結果を貯めて再試行コストを回避する pattern
