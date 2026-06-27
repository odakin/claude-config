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

## 関連

- 同じ system に対する別マシンの観察結果を比較する経路は、各 repo の `DESIGN.md` に「<date> の machine-X observation」の節を立て、別マシンでの観察を追記する形で蓄積するのが追跡しやすい (「audit を上書きする」のではなく「audit に scope qualifier と別マシン観察を追加する」アプローチ)
- 定期ジョブの機構選択 (launchd / cron / scheduled task / GitHub Actions) は [`scheduled-tasks.md` execution-locus-selection](scheduled-tasks.md#execution-locus-selection)。 hook の配信正常性 audit は [hook-authoring.md](hook-authoring.md)
- マシン横断の repo pull 経路は各ユーザーの個人レイヤーで決める (例: 個人スクリプト `pull-all.sh` を持つ等) — 本リポ public 共通規約には組み込まない
- マシン固有の install 不可な package (= `brew install foo` の試行失敗) の蓄積規律は [`install-failures.md`](install-failures.md) — layer 4 (machine-local memory) に試行結果を貯めて再試行コストを回避する pattern
