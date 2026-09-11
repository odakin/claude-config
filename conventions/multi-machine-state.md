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
- <a id="machine-gated-pending-action"></a>**特定マシンでしかできない残作業は「ホスト ∧ 未完了」 の条件で既配線の発火面に載せる** (2026-09-12 追加) — 例: 別マシンで作って push し忘れた repo。 条件 = `[ "$(hostname -s)" = "<host>" ] && ! <完了の機械的判定>` (完了判定の例 = `git -C <dir> rev-parse --verify -q '@{u}'` = upstream が付いたか)。 (1) 対象マシンでだけ、 完了するまで毎 session 出て、 完了で自然に止まる (= 消し忘れの無い carrier) (2) 対象 dir が無い場合も**出る**向きに書く (= `git -C` の失敗を「未完了」 側に倒す。 dir 名の取り違えで黙って沈黙しない) (3) host 名は fleet heartbeat と同じ `hostname -s` で取る (4) 検証は PATH の先頭に偽の `hostname` を置いて本物の発火経路を回し、 対象外マシンで沈黙することも確かめる (5) 発火面が repo の data を読むより先に同じ session 開始の auto-pull が済むとは限らない ([`hook-authoring.md#parallel-hooks-no-ordering`](hook-authoring.md#parallel-hooks-no-ordering)) = 1 回目の session は取りこぼしうる。 条件を書く field と発火面の実装は owner の個人層 (instance-down)。
- <a id="no-remember-once-steps"></a>**別マシンで「1 回だけ実行」 する手順を user に渡さない** (2026-09-12 追加) — 一般則 = [`convention-design-principles.md#human-memory-not-a-carrier`](../docs/convention-design-principles.md#human-memory-not-a-carrier) の複数マシン版 (人は覚えていられない)。 渡す前に、 その作業がすでに既配線の auto-apply 層 (= git pull の後の session 開始で冪等に再走する hook。 例: hook 配線の installer) に載っていないかを確かめる。 載っていれば手順は書かず「次の session 開始で自動」 とだけ言う。 載っていなければ auto-apply 層に足すか、 [#machine-gated-pending-action](#machine-gated-pending-action) の形で対象マシンの session に自動で出す。 実例: 新規 hook を足した直後に「別マシンで installer を 1 回」 と user に書いたが、 installer は既に毎 session 冪等に再走していた (= 手順自体が不要で、 覚えさせる負担だけを渡していた)。
- <a id="one-shot-settings-propagation"></a>**machine-local な settings の値を他マシンへ届けるのは、 auto-apply 層の one-shot step** (2026-09-12 追加) — `~/.claude/settings.json` は git 非同期なので、 あるマシンで owner が決めた値 (既定 model / permission mode / allow / additionalDirectories 等) は他マシンに届かない。 既配線の SessionStart bootstrap に step を足す: (1) marker file が無いマシンでだけ適用し、 marker を書く (= one-shot。 pin にしない = 後から user が変えても再上書きしない) (2) JSON 破損等で失敗したら marker を書かず、 次の session で再試行する (3) 適用した回だけ session 冒頭に出す (4) 制限を強める追加 (ask / deny) は安全側。 権限を広げる変更は owner が明示した値だけにする — auto mode では Claude による settings の直接編集は classifier に block されるので ([`claude-code-permissions.md#protected-settings-edit`](claude-code-permissions.md#protected-settings-edit))、 git で review される bootstrap が正規の経路になる (5) symlink を含む path 設定は実体 path も足す ([`#symlink-both-paths`](claude-code-permissions.md#symlink-both-paths))。 同じ auto-apply 層は「installer が setup.sh 実行時にしか走らない」 種類の修復にも使える ([`hook-authoring.md#installer-tracked-stub`](hook-authoring.md#installer-tracked-stub) の heal)。 実装は owner の個人層 (instance-down)。

## <a id="fleet-heartbeat"></a>Fleet heartbeat — cross-machine state の bounded 可視化

マシン A からマシン B の launchd server / auth 状態は直接 query できない ([multi-account-machine-surface.md #honest-limits](multi-account-machine-surface.md#honest-limits))。 この不可視を **各マシンの自己報告を git 経由で集約**する pattern で bounded staleness の fleet view に変える:

- **writer** = [`scripts/fleet-heartbeat.py`](../scripts/fleet-heartbeat.py) (generic engine): 毎時の launchd cron が自マシンの remote-control server 群 (launchd loaded + **server ログ末尾の marker parse** = "Connected" / auth error / version error) + config-dir auth metadata + **desktop app 全 account registry の enabled scheduled task id** (= account 切替による旧 task 復活の監視、 2026-07-04 追加) + 設定を `<repo>/<subdir>/<hostname>.json` にまとめて commit + push
- **reader** = [`scripts/check-fleet-status.py`](../scripts/check-fleet-status.py): 全マシン分を読み、 role 別に異常を surface (always-on マシンの heartbeat 停止 = 🔴 / best-effort マシンのスリープ = 仕様で silent / どのマシンも beat が新鮮な時の server 異常 = 🔴 / `--warn-desktop-tasks` 指定時は enabled な desktop scheduled task = 🔴 〔= launchd-only 方針マシン向け opt-in、 [multi-account-machine-surface.md](multi-account-machine-surface.md) I8〕 / **inventory の欠落 = 🟠** 〔下記原則 6〕)

設計原則 (詳細 = 各 script docstring が SoT):

1. **監視が監視対象に依存しない**: writer は `claude` コマンドを一切呼ばない (launchctl / log parse / git のみ)。 auth 失効で server 群が全滅しても heartbeat は動き続け、 その全滅をログ marker で報告できる (= auth 失効 → 数時間内に他マシンで 🔴、 という検出線。 実 incident: 常時起動機の auth expire で server + cron 群が ~19.5h silent 死、 検出は成果物 staleness の間接信号頼みだった)
2. **state-change-or-age commit policy**: essence が変わった時 + 一定時間経過時のみ commit (= git history を汚さない。 liveness 上限 = interval + cron 周期)。 ⚠️ **読み手への注意 — beat の欠落を即異常と誤読しない**: beat は「毎時」 ではない。 状態変化がなければ commit 間隔は最悪 interval + cron 周期 (既定 4h + 1h ≒ 5h、 境界判定が interval 未満と判定して 1 周期余分に skip する off-by-one 込み) まで開くのが**正常動作**。 実例 (2026-07-02): 「毎時 beat」 前提で 4 回連続の欠落を『heartbeat 停止 = マシン死の疑い』 と 2 度誤診したが、 実際は全て設計どおりの skip で系は終始健全だった。 reader の `--stale-hours` はこの上限より大きく取る (既定 6h > 5h)
3. **gate 対象外**: [account/host failover](#account-host-failover) の gate は「本番ホストだけが走る」 ためのものだが、 heartbeat は**全マシンが各自を報告してこそ意味がある** → gate を掛けず、 label prefix も分離する (= gate 検査機構の「gate 無し二重実行」 警告と衝突させない。 全マシン同時実行は仕様: 各マシンが別 file に書くので競合しない)
4. **reader は fetch しない**: 読むのは working tree = 呼び出し側 (dashboard の一斉 fetch / session 開始時の pull) が鮮度を担う。 ⚠️ **系 (= 逆向き偽アラーム)**: heartbeat repo の local clone が behind / diverged のまま reader が走ると、 実際には健在な**他マシン**が「heartbeat 停止 = silent 死」 に見える (= 自分の同期不全が**相手の死**として表示される、 向きが反転するのが罠)。 always-on マシンの 🔴 を結論する前に、 heartbeat repo 自体を `git fetch` + behind/ahead 確認する 1 コマンド verify を挟む (実 incident 2026-07-10: 片マシンの divergence が反対マシンの偽 125h-silent 🔴 を生んだ — 「死んだ」 とされた側は健在で通常稼働中、 偽アラームは ~20 分事実として扱われた)。 この verify 手順は reader の 🔴 finding 文面自体に焼き込んである (= 消費点に routing を運ぶ、 2026-07-17)。 ⚠️ **偽アラームの第 3 形態 = 読み手側の surface file 残留**: reader の finding を SessionStart hook が surface file に cache する構成では、 findings 解消後も**古い 🔴 が file に残留**しうる (= cleanup path が early-exit で dead code 化する ordering bug、 実 incident 2026-07-17: 解消済み finding が 9 日間残留し「heartbeat 停止中」 と誤読される状態だった)。 write-or-delete ordering の一般則 = [hook-authoring.md #surface-file-cleanup-ordering](hook-authoring.md#surface-file-cleanup-ordering)。 clone staleness (= 本原則) と surface staleness (= 第 3 形態) は独立に起きる — 🔴 を見たら「finding の生成時刻はいつか」 も疑う
5. **writer の push 経路は他 session の残置に耐える (= `pull --rebase --autostash`)**: autostash なしだと、 他 session が残した**無関係な dirty file** で rebase が拒否される → beat は local commit に積み上がるだけで push されず、 (a) fleet からこのマシンが silent 死に見える (= 監視機構自身が監視対象と同じ症状を呈する) + (b) このマシン自身の fleet view も stale 化する (= 双方向の盲目、 原則 4 の逆向き偽アラームの発生源)。 `--autostash` は dirty をまたいで beat を流す (残余 risk = stash pop conflict だが、 dirty で 100% wedge する旧挙動より strictly better、 fail-open 契約内)。 実測 RCA (2026-07-10、 dirty 残置 2 日で divergence 76/12 commit まで雪だるま化) の詳細 = `fleet-heartbeat.py` 内 comment
6. **inventory parity — 「あるマシンにだけ無い」 を union で検出する (= 宣言 registry を持たない)**: heartbeat は本来 liveness の監視だが、 同じ transport で **持ち物の突合**もできる。 writer の `--inventory 'LABEL=GLOB'` (opt-in、 repeatable) が match した path 要素の **名前だけ** を beat に載せ (= 中身は読まない ∴ credential dir にも安全に使える)、 reader が全マシン分の **union** を期待集合として「他マシンには在るのにこのマシンには無い」 を 🟠 で surface する。 ⚠️ **設計の核心は期待集合を宣言しないこと**: 「共有すべき物の一覧」 を registry に持たせると *登録忘れ* という規律依存の穴が残る (= 一覧型 audit の implicit-scope 盲点、 [convention-design-principles.md #proxy-blind-spot](../docs/convention-design-principles.md#proxy-blind-spot))。 union なら「1 台でも持っていれば期待される」 ので登録行為が要らない。 代償は **どのマシンにも無い物は検出できない** (= union が空) — この残余は宣言集合を持つ別の検出器 (= その物を使う script 自身が持つ一覧) と相補で埋める。 例: `--inventory 'gmail_accounts=~/.gmail-mcp/*/credentials.json'` は per-account credential の欠落を拾う。 実 incident (2026-07-25): machine-local な OAuth credential dir がどの機械 audit の射程にも入っておらず、 ある account の credential が 1 台だけ未配置のまま **45 日 silent** だった (= その account を使う機能は per-account fail-open で静かに skip され、 doc に残タスクとして書かれていただけだった)。 ⚠️ **配線時の順序 hazard**: 呼び出し shim だけが先に配布されたマシンで engine が未知 flag を受けると argparse が exit 2 で **heartbeat 自体が死ぬ** (= 監視の silent 死)。 呼び出し側で engine の対応を検出してから渡す (= capability probe。 例: engine source を `grep -q -- '--inventory'` して真なら追加。 併せて glob は quote して渡す — 展開は engine の仕事で、 shell に展開させると複数 path に割れて壊れる)
7. **監視 layer の分界 — heartbeat は「agent の生死」 だけを見る**: launchd job が「生きて」 いて**毎回失敗している** (= `launchctl list` の LastExitStatus ≠ 0) 状態は heartbeat の射程外 — job は定刻に走り、 beat も打たれ続けるからである。 実 incident (2026-07-29): 日次 routine 5 本が context 超過で 4-5 日連続 exit 1 だったが、 exit status を見る機械が無く沈黙した ([scheduled-tasks.md #headless-context-budget](scheduled-tasks.md#headless-context-budget))。 監視は 3 層で相補する: ① agent/machine の生死 = heartbeat (本 pattern) ② **job の exit status** = LastExitStatus watcher (機械実装は各層) ③ 成果物の鮮度 = 各 routine 固有の heartbeat file (= exit 0 で内容が壊れる silent 論理故障を拾う)。 1 層でも欠けるとその class の失敗が黙る

## 関連

- 同じ system に対する別マシンの観察結果を比較する経路は、各 repo の `DESIGN.md` に「<date> の machine-X observation」の節を立て、別マシンでの観察を追記する形で蓄積するのが追跡しやすい (「audit を上書きする」のではなく「audit に scope qualifier と別マシン観察を追加する」アプローチ)
- 定期ジョブの機構選択 (launchd / cron / scheduled task / GitHub Actions) は [`scheduled-tasks.md` execution-locus-selection](scheduled-tasks.md#execution-locus-selection)。 hook の配信正常性 audit は [hook-authoring.md](hook-authoring.md)
- マシン横断の repo pull 経路は各ユーザーの個人レイヤーで決める (例: 個人スクリプト `pull-all.sh` を持つ等) — 本リポ public 共通規約には組み込まない
- マシン固有の install 不可な package (= `brew install foo` の試行失敗) の蓄積規律は [`install-failures.md`](install-failures.md) — layer 4 (machine-local memory) に試行結果を貯めて再試行コストを回避する pattern
