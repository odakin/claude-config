<!-- doc-meta
when: アカウント × マシン × 端末の複数セル運用を設計・診断するとき
category: harness-core
summary: アカウント × マシン × 端末 (desktop app / スマホ remote) の 2×2×2 を全部シームレスにする設計原理 (= 3 軸の本質差・切替 mechanics・seamless invariant I1-I10・同じマシンの設定フォルダを跨ぐ session の発見と知らせと会話記録の読み・他の人も login する account に仕事を置かないための露出と切り方 (#shared-account-exposure)・破れの検出・cross-machine 不可視の正直な限界。 RC server / multi-machine-state / scheduled-tasks の全体像 doc)
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

以下 10 個が**全マシンで**成立していれば、 8 セルのどこからでも仕事が始められ・続けられる。 各 invariant は機械 check 可能にする (= 固定表に書いた「はず」 ではなく live 状態から検証する。 固定表は現実と drift する):

| # | invariant | 破れの症状 | 検出 / 修復 |
|---|---|---|---|
| I1 | 各マシンに RC server をアカウントごとに 1 本 (= 2 本) 常駐、 **アカウント固定の pinned config dir に載せる** (= 既定 `~/.claude/` は account が可変なので載せない。 pinned 方式なら interactive OAuth はマシン × アカウントごとに 1 回だけで永続 = account 切替が coverage に波及しない) | スマホで片方のアカウントにするとそのマシンが出てこない / 既定 dir の account 切替で片セル silent 消失 | session 開始時の coverage check が自動配備 + 未 auth なら 1 回きり OAuth 手順を surface ([remote-control-server.md #multi-account-servers](remote-control-server.md#multi-account-servers)) |
| I2 | pinned config dir へ、 既定 dir が持つ道具を**全部**持ち込む: `settings.json` / `skills` / `agents` の symlink、 auto-memory (`projects/<cwd>/memory`) の symlink、 MCP 登録の複製 (`.claude.json` は auth と同じ file なので file ごと共有できない = 中の MCP 登録だけを足す)。 **install 時だけでなく毎 session 当て直す** (= 後から足した持ち込み物は、 既に動いている server の dir に届かない) | pinned dir の session (= スマホから始めた session) だけ hooks / guard が効かない・メールの MCP が無い・agent や memory が無い。 片方の account の dir だけ欠けると、 その account のスマホ session だけ道具が少ない (実測: 片方の dir の MCP が 0 件) | SessionStart の bootstrap が存在する pinned dir ごとに持ち込みを当て直す (冪等・変えた時だけ出力)。 セル状態の check が dir ごとに持ち込みの欠けを表示 |
| I3 | `remoteControlAtStartup: true` を全マシンに (desktop app の自動接続は別の設定で、 値を入れるとそちらで決まる。 他の人も login する account を desktop で使う機械では off にする = [#desktop-remote-control-switch-per-machine](#desktop-remote-control-switch-per-machine)) | そのマシンの手元 session がスマホから続行できない (= 新規は作れるのに続きができない非対称) | settings.json を machine ごとに確認 (machine-local ゆえ git 同期されない点に注意) |
| I4 | CLI 土台アカウントは **live fact** (固定 design にしない) + **マシン間でアカウントを分散** | 全マシンの土台が同一アカウントだと、 そのアカウントの rate limit 到達で全マシンの無人ルーチンが同時死する | 土台の現在値は `claude auth status` / 切替 helper で live 導出。 分散していれば「アカウント枯渇 failover = マシン failover」 が 1 動作になる |
| I5 | 無人ルーチンは active-host 台帳に bind + drift 検出 | 「切替えたつもり」 のアカウントとルーチンが実際に消費するアカウントの乖離 | [multi-machine-state.md #account-host-failover](multi-machine-state.md#account-host-failover) の台帳 + drift 検出 |
| I6 | pinned config dir は **headless-ready** (= workspace trust + RC 初回同意の flag が seed 済。 install script が install 時に自動 seed するので通常は自動成立、 残る interactive 段は OAuth 1 回のみ) | OAuth 済なのに server が dialog 待ちで exit-1 永久 cycling (= loaded だが process 無し) → そのマシン × アカウントの mobile セルが **silent 消失** | fleet-heartbeat の log marker (`trust_error` / `consent_pending`) を reader が 🔴/🟠 surface。 heal = install script 再実行 ([remote-control-server.md #ts-workspace-trust](remote-control-server.md#ts-workspace-trust)) |
| I7 | session は**自分の worker host + account を会話ログに自己申告**する (= SessionStart hook が hostname / surface / **account** / session-id を注入し、 **この session で最初に書く text (途中経過の 1 行・harness の状況促しへの返答を含む) の 1 行目**に 1 行 stamp。 account は harness metadata でなく whoami probe で引く 〔= §典型的な破れかた「session の自己アカウント同定を harness metadata で行う誤り」、 2026-08-28 追加〕。 stamp は会話ログに残るので **bridge が死んだ後も scroll-back で読める**。 タイトルには頼れない — RC の auto-name は hostname prefix 既定だが AI 自動タイトルが上書きすると消える 〔2026-07-02 実測〕) | bridged session が切断した時 (= [remote-control-server.md #ts-desktop-bridge-4090](remote-control-server.md#ts-desktop-bridge-4090)) 「どのマシンに行けば復旧できるか」 が UI から分からず、 host 特定が transcript / reflog の forensics になる (2026-07-02 実測 ~30 分) | 機構 = 3 段の hook (SessionStart 注入 / 最初の prompt 直後の再注入 / 最初の turn 終わりの Stop 検査) + 事後 audit、 Claude と Codex で共通 = [#first-reply-stamp-mechanism](#first-reply-stamp-mechanism)。 ⚠️ desktop app は注入を drop すると観測されていた ([hook-authoring.md #frontend-dependent-cowork](hook-authoring.md#frontend-dependent-cowork)。 2026-09-11: 少なくとも一部は root 限定の `disableAllHooks` が原因 = [#disableallhooks-kill-switch](hook-authoring.md#disableallhooks-kill-switch)。 届くかどうかを前提にしない) ので、 注入が無くても成り立つよう — **Desktop session の最初の tool call で whoami probe (`claude-session-whoami.py --stamp`) を実行**し、 その 1 行 (`🖥 <host> · <desktop|cli|rc>/<label> = <account> · session <id8>`) をそのまま最初の返信の冒頭に置く。 ⚠️ `hostname -s` 単独では account 軸が抜け、 harness の userEmail を信じて誤同定する (2026-08-28 + 2026-09-05 の 2 回、 後者は拡張の署名 account との一致判定まで誤り permission 障害の切り分けを 1 段飛ばした)。 surface 軸は 2026-09-05 から `rc/<label>` (= Remote Control server 配下、 プロセス祖先の cmdline で判定、 fail-open で `cli/`) を区別 — 「リモートか手元か」 も冒頭 1 行で読める。 surface file は補助であり、当該 tool result が worker host / account の ground truth。⚠️ 検証結果を **public surface** (公開 repo の file / commit message / issue) に書く時は hostname literal でなく属性 (「MacBook 側」 等) で書き、 具体値は個人層に置く (= 機器名はしばしば人名を含む。 2026-09-01 実 leak → force-push 修正の再発防止) |
| I8 | **無人ジョブは launchd + CLI 認証 only** — desktop app の scheduled task に置かない (= registry が account × app-install scoped で、 アカウント切替が旧 registry の enabled task を**黙って復活**させ、 移行済ジョブと二重実行 + session 一覧 noise になる。 2026-07-04 実測: swap から発覚まで 2 日 silent) | account swap 後に旧 scheduled task が並走 (= 同一ジョブの heartbeat 二重打刻 / recents に routine session が数十件積み上がる) | fleet-heartbeat が全 account registry の enabled task id を毎時収集、 reader が `--warn-desktop-tasks` で 🔴 surface ([multi-machine-state.md #fleet-heartbeat](multi-machine-state.md#fleet-heartbeat))。 解除 = 該当マシンの desktop app で enabled:false 化 ([scheduled-tasks.md #registrable-session-types](scheduled-tasks.md#registrable-session-types)) |
| I9 | **「picker に見える environment 群 = 常に現スマホ account のもの」 を運用知識として保持** (= 各マシン × account に env は 1 つずつ、 4 セル同時表示は platform 上あり得ない。 「どの account か」 の判別軸は env 名でなく**スマホアプリの現アカウント**) | 「意図しない account の session に入った」 と感じる (実際はスマホの現 account の env に正しく入っている = account 自覚の欠落、 2026-07-04 実測) / 「4 つ見えない」 と誤診 | ⚠️ **env の表示名は hostname 固定で configurable でない** (2026-07-04 実測: installer が `--name` + session-name-prefix に `<host>-<alias>` を焼いた server で env を fresh 登録させても label は hostname のまま。 flags は spawn session の**初期名**にのみ効き、 それも AI 自動タイトルが上書きし得る = I7)。 ゆえに機械対策は無く、 本 invariant は knowledge ([remote-control-server.md #multi-account-servers](remote-control-server.md#multi-account-servers)) |
| I10 | **同じマシンの別の設定フォルダで動く session どうしが、 互いを見つけて知らせられ、 会話記録を読む道具 (検索・監査・集計) にも全部が出る** (= desktop の session と、 アカウント固定の設定フォルダで動くスマホ発の session・無人 routine) | スマホから始めた session が、 desktop の session の兄弟一覧・二重起動の検出・宛先の model の確認に出ない。 ListAgents に互いが出ず、 名前の SendMessage が「reachable でない」 で失敗する (実測)。 会話記録の検索・監査・集計から黙って抜ける (実測) | 機構と道具 = [#peer-discovery-across-config-dirs](#peer-discovery-across-config-dirs) |

**I7 の Codex mapping (2026-09-11)**: Codex でも startup / resume / clear 後の最初の返信を自己同定 stamp で始める。現行の公式 Hook input から session id と model、local hook process から host、観測できた app-process signal から desktop surface までは取る。account と未観測 surface/effort は推測せず `unknown` と表示する。Hook 注入が届かなければ最初の tool call で `~/.codex/claude-config-hooks/session_stamp.py` を実行し、その出力を冒頭へ置く。技術正本と取得境界は [`codex/PARITY.md#conversation-start-stamp`](../codex/PARITY.md#conversation-start-stamp)。Claude CLI auth や config default を Codex Desktop の account/実効値へ流用しない。

## <a id="first-reply-stamp-mechanism"></a>I7 の機構: 最初の返信の stamp を 3 段の hook + 事後 audit で支える

**規約だけでは足りなかった (2026-09-11 実測、 1 マシン・desktop・60 日分の transcript)**: 規約が有効な期間でも、 最初の text の 1 行目に stamp が出たのは 13/31、 最初の turn のどこかに出たのも 26/31 だった。 失敗の型は 3 つ (worker 定型の prompt かどうかは差にならなかった):

- **注入 stamp が不完全**: SessionStart hook は desktop の account を app の session registry file から引くが、 その file は session 作成から ~2 秒以内には無いことが多い (hook が届いた session の 18/20 が「account 未同定」)。 未同定の stamp を受けたモデルは probe の結果を待ち、 その前に前置き text を書く。 account まで埋まった注入を受けた session は 7/8 が冒頭に出した
- **状況報告の促し**: harness が「user が待っている、 数語で状況を」 と促すと、 その返答が最初の text になる (促しが最初の text より先に来た session では 1/7)
- **予告だけの前置き**: 「まず自己同定 stamp を読みます」 と書いて stamp を出さない (最初の text で落ちた 18 件中 8 件)

**3 段 + 事後 audit** (判定 logic の正本 = [`scripts/first_reply_stamp.py`](../scripts/first_reply_stamp.py)、 Claude / Codex 共通):

| 段 | Claude | Codex | 役割 |
|---|---|---|---|
| SessionStart 注入 | `hooks/session-start-host-stamp.sh` | `codex/hooks/resume_context.py` | stamp と定義を session の最初に置く。 whoami の `--wait 3` で registry の出現を待つ |
| 最初の prompt の直後に再注入 | `hooks/first-prompt-stamp.py` (UserPromptSubmit の additionalContext) | `codex/hooks/first_prompt_stamp.py` | 最初の text を書く直前の位置に完全な stamp を置く = **主対策**。 session に 1 回 |
| 最初の turn の終わりの検査 | `hooks/first-turn-stamp-check.py` (Stop) | `codex/hooks/first_turn_stamp_check.py` | その turn のどの返信の 1 行目にも無ければ、 observe = 記録 / block = 1 回だけ差し戻して stamp 1 行を出させる。 位置は直せない = 床 |
| 事後 audit | [`scripts/check-first-reply-stamp.py`](../scripts/check-first-reply-stamp.py) | 同 (Codex rollout も読む) | hook の外の物差し。 hook が止まっても率の劣化と「未同定」 の再発が見える |

**「最初の返信の冒頭」 の定義**: この session で最初に書く text の 1 行目。 途中経過の 1 行・状況報告への返答も含む。 ⚠️ 途中経過の行は会話記録に残らないことがある (実測: tool call の合間に書いた途中経過の 1 行目の stamp が記録に無く、 Stop の検査は stamp 無しと読んで差し戻した) = 途中経過に置いた場合も、 最初の turn の最後の返事の冒頭にもう一度置く。 「stamp を確認します」 という予告は stamp の代わりにならない。 注入 stamp の account が埋まっていればそのまま出してよい (whoami は照合用)。 「未同定」 なら最初の text の前に whoami を実行する。

**範囲**: workspace base (= 本 repo の親 dir) の外の cwd では全段が黙る — 盲検 sandbox は base の外に作る規約 ([cold-eyes-isolation.md](cold-eyes-isolation.md)) なので注入が汚染源にならない。 Claude の headless (`CLAUDE_CODE_ENTRYPOINT=sdk-*`) と Codex の sub-agent rollout は後ろ 2 段の対象外。 全段の opt-out = env `FIRST_REPLY_STAMP=off`。

**Stop 段の mode**: `DEFAULT_STOP_MODE` (導入時 = observe、 observe の記録に誤発火が無いのを確かめて block に上げた) を env `FIRST_REPLY_STAMP_STOP` (off / observe / block) で上書きできる。 observe の記録は `<config dir>/state/first-reply-stamp/stop-log.jsonl` (Codex は `~/.codex/state/claude-config-first-reply-stamp/`)。 block に上げるのは、 記録と audit で誤発火が無いのを確かめてから (= 値の変更を commit で残す)。 1 session につき評価は最初の Stop の 1 回だけで、 以後の turn では transcript を読まない。

<a id="stamp-text-missing-from-transcript"></a>**誤発火の 1 つの型 — 最初の途中経過の text が transcript に残らない** (実測、 desktop、 原因未確認): 最初の turn の最初の text (stamp の 1 行で始まる途中経過の文) が transcript の file に無く、 同じ turn の後の途中経過の文は残っていた。 Stop 段は transcript だけを読むので、 stamp を出していても「無い」 と差し戻す。 差し戻されたら指示どおり stamp の 1 行だけを出せば済む (中身の出し直しは要らない)。 疑うときは transcript で最初の turn の assistant の text を数え、 画面に出した最初の文が入っているかを見る。 2 回目が出たら、 Stop 段が `last_assistant_message` 以外に途中経過の text を拾う経路を持てるかを調べる。

**desktop で届くもの・届かないもの** (2026-09-11 実測 = [hook-authoring.md #desktop-hook-honor-remeasure](hook-authoring.md#desktop-hook-honor-remeasure)): UserPromptSubmit の additionalContext と Stop の block は届く。 `systemMessage` は会話に表示されないので、 user 向けの表示には使えない。 `sessionTitle` (hook 出力) は CLI が受け付けるが、 desktop の題名に反映されるかは未確認で、 AI 自動題名や spawn の題名を潰すので採らない。

**使ってはいけない信号**: transcript 先頭の `bridge-session.ownerAccountUuid` は session の account ではない (registry の account と 42/95 で食い違った)。

**Codex の限界**: CLI (`codex exec`、 0.159.2) では、 hook の trust を承認した後の新しい task で SessionStart と UserPromptSubmit の context が model に届き、 返事の冒頭に stamp が出て、 Stop の hook も走った (2026-10-07 実測、 1 台)。 desktop で届くかは未実測 ([codex/PARITY.md#conversation-start-stamp](../codex/PARITY.md#conversation-start-stamp))。

## <a id="peer-discovery-across-config-dirs"></a>I10: 同じマシンの別の設定フォルダの session を見つけて知らせ、 会話記録も全部読む

**事実 (実測)**:

- desktop app の session は、 app のアカウントに依らず既定の設定フォルダ (`~/.claude`) を使う。 アカウント固定の Remote Control server (I1) から生えた session (= スマホから始めた session) と、 `CLAUDE_CONFIG_DIR` を付けた CLI・無人 job は、 その設定フォルダ (`~/.claude-<alias>`) を使う
- harness は生きている session を設定フォルダの `sessions/<pid>.json` に刻印し、 transcript を `projects/` に書く。 **会話記録を読む道具が `~/.claude/projects` だけを読むと、 スマホから始めた session と無人 routine の session が検索・監査・集計から黙って抜ける** (0 件・少ない件数が「無い」 に見える)。 **ListAgents が出す同じマシンの session は、 自分の設定フォルダの刻印の分だけ**。 別の設定フォルダの session は、 アカウントが同じでも出ず、 名前の SendMessage は「reachable でない」 で失敗する (既定 → 固定、 固定 → 既定、 同じアカウントの固定 → 既定、 の 3 通りで実測)
- 刻印には session の socket (`messagingSocketPath`、 置き場は設定フォルダに依らず共通) が書いてある。 **SendMessage の `to` に `uds:<socket>` を書くと、 設定フォルダとアカウントを跨いで届き、 返事も `from` の宛先で戻る** (両方向で実測)
- 他のマシンの session: ListAgents は、 同じアカウントの Remote Control session を他のマシンの分も `bridge:` の宛先で出す作り (CLI 本体の読み、 未実測)。 アカウントもマシンも違う相手への直接の道は無い = 掲示板の thread を見張る ([multi-session-coordination.md #board-watch-live-session](multi-session-coordination.md#board-watch-live-session))

**道具** (どれもその機械の全部の設定フォルダを読む = [`scripts/lib/claude_config_dirs.py`](../scripts/lib/claude_config_dirs.py)。 列挙 = `config_dirs` / `sessions_dirs` / `projects_dirs`、 会話記録 = `transcript_files` / `transcript_paths` / `find_transcript`。 道具ごとに列挙を書き直さず、 これを呼ぶ):

- 生きている session と宛先:
  - [`scripts/list-live-sessions.py`](../scripts/list-live-sessions.py): 兄弟ごとに設定フォルダと `uds:` 宛先。 SessionStart の兄弟の表示では、 自分と別の設定フォルダの兄弟にだけ宛先を付ける
  - [`scripts/session-model.py`](../scripts/session-model.py): 宛先の model と `SendMessage to=uds:…`
  - 掲示板の投稿 (ai-collaboration `board/board.py`): 次に動く session がこの機械で生きていれば、 投稿の後にその `uds:` 宛先を 1 行出す
  - 二重起動の検出 ([`scripts/lib/spawn_dedupe.py`](../scripts/lib/spawn_dedupe.py)) も、 全部の設定フォルダの刻印と transcript を読む
- 会話記録の検索・監査・集計 (既定で全部の設定フォルダ。 `--claude-dir` / `--projects-dir` / `--glob` を渡すとその場所だけ。 `~/.claude` 以外の session には設定フォルダの名を付けて出す): [`search-agent-transcripts.py`](../scripts/search-agent-transcripts.py) (agent の欄が `claude[<名>]`) / [`permission-dialog-audit.py`](../scripts/permission-dialog-audit.py) / [`injection-reach-audit.py`](../scripts/injection-reach-audit.py) / [`count-malformed-tool-call-events.py`](../scripts/count-malformed-tool-call-events.py) / [`calibrate-bash-command-pattern.py`](../scripts/calibrate-bash-command-pattern.py) / [`calibrate-final-message-pattern.py`](../scripts/calibrate-final-message-pattern.py) / [`check-first-reply-stamp.py`](../scripts/check-first-reply-stamp.py) / [`subagent-reports.py`](../scripts/subagent-reports.py) / [`headless-worker-reports.py`](../scripts/headless-worker-reports.py)。 session id の先頭で 1 本を引く [`transcript-images.py`](../scripts/transcript-images.py) / [`transcript-tool-result.py`](../scripts/transcript-tool-result.py) も全部から引く
- 見張りと、 hook・参照の点検: memory の見張り ([`hooks/memory-guard.sh`](../hooks/memory-guard.sh) / [`hooks/memory-guard-bash.sh`](../hooks/memory-guard-bash.sh) = どの設定フォルダの `projects/<cwd>/memory/` の path も対象。 アカウント固定の設定フォルダの memory は既定の memory への symlink なので、 path の形で漏らすと同じ実体への書き込みが素通りする) / hook の発火の監査 ([`scripts/hook-liveness-audit.py`](../scripts/hook-liveness-audit.py) = user tier は設定フォルダごとの `settings.json`、 集計は (設定フォルダ, root) ごと) / ファイル参照の点検の較正 ([`scripts/lib/chat_file_refs.py`](../scripts/lib/chat_file_refs.py) の `calibrate`)
- その設定フォルダだけを見るのが正しいもの: desktop app の画面を診断する [`claude-app-thinking-diagnose.py`](../scripts/claude-app-thinking-diagnose.py) の既定 (desktop の session は `~/.claude` にしか書かない。 `--session` で id を名指ししたときは全部から引く) / desktop の一覧を写す [`claude-app-account-mirror.py`](../scripts/claude-app-account-mirror.py) (desktop の configDir = `~/.claude`) / hook が入力で受け取る自分の `transcript_path` を読むもの / 設定フォルダごとの state (`<config>/state/…`、 認証、 plist の pin) を扱うもの

**写しと重複** (`transcript_files` の扱い = 道具の間で揃える):

- 同じ file に 2 つの道で届く (アカウント固定の設定フォルダの `projects/<cwd>/memory` は既定の memory への symlink、 設定フォルダ自体の symlink) → 1 回。 memory を数える道具が二重に数えない
- 同じ session id が 2 つの設定フォルダに在る (写し) → 新しい方を 1 回。 transcript と、 その設定フォルダの横の state (`<config>/state/…`) を突き合わせる道具は、 写しを全部読む (`copies="all"`、 例 = headless-worker-reports.py の受領の記録 = 受領の無い写しが、 受領の在る元を隠さない)
- desktop app の `imported-staging/` (claude-app-account-mirror.py が置く別 account の session の写し) は設定フォルダの外 = 数えない (元の session は既に数えている)。 写しを app で開くと新しい session id で `projects/` に移る (app 本体の読み、 実 app では未確認) = 別の session として数える (前半は元の turn の繰り返し)

**捨てた案**: 固定の設定フォルダの `sessions/` を既定の `sessions/` への symlink にして、 ListAgents に全部を出させる — harness の内部状態 (同じ dir に pid ごとの通信の鍵 `<pid>.<hash>.key` も在る) をアカウント間で共有することになり、 副作用を確かめる手段が無い。 宛先を読む道具の側で跨ぐ。

**注意**: 届いたことは読まれたことではない (permission mode の違う session は人の承認待ちに置くことがある = SendMessage の説明)。 記録は掲示板が先 ([multi-session-coordination.md #board-receipt-carrier](multi-session-coordination.md#board-receipt-carrier))。 socket は process ごとで、 session を開き直すと変わる = 送る直前に引く。

## <a id="codex-peers"></a>I10 の Codex 版: 同じ機械の Codex の thread を見つけて知らせる

**事実 (実測、 Codex CLI 0.159.2・1 台)**:

- Codex の thread には SendMessage が無い。 Codex CLI の `codex queue --thread <thread id> --message <文>` が、 既存の thread に user の message を積む。 動いている client に読み込まれている thread では、 今の turn が終わった直後に、 その message が新しい turn として始まった。 `codex exec` の thread は 1 turn で終わる作りなので、 始まった turn はすぐ中断された。 どの client にも開かれていない thread では message が積まれたまま残った (次に開いた時に届くのは製品の作りからの推論)
- `codex queue` が届くのは、 この機械の state DB (`threads`) に rollout を持つ thread だけ。 掲示板の event の `actor.session_id` に Codex の thread id が書かれていても、 その thread が手元に無いことがある (ChatGPT app の agent が掲示板に書いた thread で起きた。 手元に無い理由は未確認) — そのとき `codex queue` は `no rollout found for thread id` で失敗し、 返事の経路は掲示板だけになる (相手が読みに来る)。 送る前に `lib/codex_threads.py` の `thread_rows(ids=[<id>])` が行を返すかで確かめる (`resolve` は完全な id を照合せずにそのまま返す)
- 生きている thread = Codex の home の `thread-writer-locks/<thread id>.lock` を process が開いている (`lsof` で読む)。 thread の cwd・題・model・effort は Codex の手元の state DB (`state_*.sqlite` の threads) に在る。 どちらも公開の契約でない手元の配置なので、 読む道具は読めなければ「不明」 を返す (「生きていない」 にしない)
- Codex の sandbox (workspace-write) の中には network が無い = `--sync` と掲示板への投稿は承認を経る。 Codex の home も書けない = Codex から打った `codex queue` は state DB の書き込みで失敗した。 読むだけの道具 (`list-live-sessions.py` / `lib/codex_threads.py` / 会話記録の検索) は Codex の sandbox の中でも動いた
- Codex の session から Claude の session への直接の道は無い (`uds:` の宛先は SendMessage の宛先で、 Codex は SendMessage を持たない)。 Codex は掲示板に書き、 Claude 側は request・claim・submit の後に回している watch で起こされる

**道具** (読むだけ・何も書かない):

- [`scripts/lib/codex_threads.py`](../scripts/lib/codex_threads.py): 生きている thread・cwd・model、 thread id の解決 (8 文字の先頭から)、 `codex queue` の 1 行。 CLI は app 同梱の版を先に使う (PATH の `codex` は古いことがあり、 `queue` を持たないかもしれない)
- [`scripts/list-live-sessions.py`](../scripts/list-live-sessions.py): Claude の兄弟と並べて Codex の生きている thread を出す (SessionStart の兄弟の表示では同じ cwd の thread だけ)
- 掲示板の投稿 (ai-collaboration `board/board.py`): 次に動くのがこの機械の Codex の thread なら、 投稿の後に `codex queue` の 1 行を出す (役割 id は claim の名前の先頭 8 文字から thread を引く)。 `request` は宛先の Codex の thread の model も出す。 Codex が投稿したときは SendMessage を頼まず、 相手の Claude の watch で届くことを出す

**別の機械の Codex**: 直接の道は無い = 掲示板。 Codex の desktop では task に heartbeat を付けて掲示板を読み直すのが製品の道 (未実測、 [`codex/PARITY.md#native-automation-routing`](../codex/PARITY.md#native-automation-routing))。 手元の写しを読むなら承認の画面は出ず、 `--sync` は毎回承認を経る。 掲示板の側の約束 = ai-collaboration [`board/CONTRACT.md#codex-reach`](../../ai-collaboration/board/CONTRACT.md#codex-reach)。

## <a id="shared-account-exposure"></a>他の人も login する account (共用) に仕事を置かない

ある account に他の人も自分の端末から login するなら、 その account に紐づくものは全部その人に見える。 塞ぐのは「その account の session がこの機械に立つ・載る」 経路と、 account 側の connector (実測)。

- **見えるもの**: claude.ai のチャット・artifact、 Code の session 一覧 (Remote Control に繋いだ session = 会話の中身ごと、 続きの操作も。 繋がない desktop の session は、 同じ account のスマホの Code の一覧に出なかった = 実測。 web の一覧は見ていない)、 Remote Control の環境、 connector、 push 通知の宛先の端末。
- **いちばん広い入口 = その account の Remote Control サーバーが機械に常駐していること**: スマホの Code から機械の上に新しい session を立てられ、 その機械の local の MCP (メールなど) と file に届く。 local の MCP は account に紐づかないので、 その account の session が機械に立たない限り届かない。
- **connector は claude.ai の普通のチャットから使え、 Claude Code の hook は効かない**: メールの connector は読むだけでなく送信・転送もでき、 手元の送信の確認・止めの hook を通らない。 GitHub の connector は、 つないだ GitHub の account が読める private repo を読ませる (暗号化していない file はそのまま読める)。
- **見えないもの**: headless の `claude -p` を session を保存せず (`--no-session-persistence`) Remote Control も切って走らせた実行は、 一覧にも残らない ([scheduled-tasks.md#headless-session-persistence](scheduled-tasks.md#headless-session-persistence))。 使用量の枠は共用なので減り、 run の中の push 通知はその account の端末へ向かう作りのまま。
- **機械で切る形**: 共用の account を宣言する一覧を個人層に 1 つ置き、 session 開始の自動設定 (毎回冪等) が、 その account の Remote Control サーバーを外す・無人実行の config dir の pin を別の account へ差し替える (移し先が login 済みで、 email が移し先の名と一致するときだけ。 実行中の job は次回 = [multi-machine-state.md](multi-machine-state.md) の bootout の項)・session 一覧の写し (#session-list-per-account) を止める・その account の session が Remote Control に繋がる形のとき (desktop app の自動接続が off でない desktop の session と、 CLI の session) と CLI の既定 (`~/.claude.json`) がその account のときに毎回警告する。 サーバーを立てる installer も一覧の account を拒否する。 account の側に物を置く tool (artifact の公開・artifact の database への書き込み・Docs connector の作成と変更・push 通知・ファイル送付・claude.ai の routine・session の cloud 移動・Remote Control を on にする操作) は、 PreToolUse hook が whoami の account を一覧と照らして、 その account の session でだけ止める (読むだけの action と、 Remote Control を off にする操作は止めない)。 人の手が要るのは、 connector を外す (claude.ai の設定画面)・desktop app の Remote Control の自動接続 (下)・ブラウザ拡張の署名・既にある履歴の扱い。
- <a id="desktop-remote-control-switch-per-machine"></a>**desktop app の Remote Control の自動接続は機械に 1 つ (account ごとではない、 app 本体で確認)**: 設定 → Claude Code の「Connect new sessions to Remote Control」 は、 app の設定 file (`claude_desktop_config.json` の `preferences.ccRemoteControlDefaultEnabled`) に 1 つだけ保存される。 値を入れると、 desktop の session はこの値で決まり、 settings.json の `remoteControlAtStartup` は見られない。 同じ file の account ごとの設定は名前に `ByAccount` が付き、 これには付かない ([claude-app-bundle-reading.md](claude-app-bundle-reading.md))。 ∴ 共用の account の session だけを切ることはできず、 切ると機械の全 account の desktop session が自動では繋がらない (続けたい session だけ画面上部のスイッチで on。 session ごとの切替は app の `set_remote_control`)。
- **判断**: 共用の account の session を Remote Control に繋ぐと、 会話がその account の一覧に載り、 他の人の端末から読め・操作できる (操作はこの機械の local の MCP と file に届く)。 共用の account で対話の作業をするなら、 その機械の desktop app の自動接続を off にし (上)、 または on のまま、 その account の session が繋がって始まったら最初の返事で切るかを本人に聞かせて、 答えに従い `set_remote_control` でその session だけを切る (session 開始の自動設定がこの指示を出す。 聞いて切るまでの間は一覧に載る)。 その account の session では Remote Control・artifact・push 通知・ファイル送付を使わない (どれも account の側に置かれる。 上の「機械で切る形」 の hook が止める)。 CLI の session は settings.json の `remoteControlAtStartup` で繋がるので、 共用の account では CLI を使わない。 繋がない desktop の session がその account のスマホの Code の一覧に出ないことは実測で確かめた (上の「見えるもの」)。 app の更新で振る舞いが変わりうるので、 使い始める機械では 1 回、 その account の別の端末の Code の一覧で同じことを見る。 経路を最も少なくするなら、 共用をやめて仕事用の account を別に用意する。 共用のまま確実に見えないのは上の「見えないもの」 (保存しない無人実行)。

## <a id="failure-modes"></a>典型的な破れかたと検出

- **auth 失効で server 群が silent 死**: launchd KeepAlive は process は再起動できるが auth は直せない。 長時間気づかない事故になりやすい → 無人成果物の heartbeat 監視 + session 開始時 coverage check が網
- **virgin config dir の headless 死 (I6)**: OAuth を通しても trust / consent の dialog flag が virgin だと launchd server は dialog を出せず exit-1 cycling。 「OAuth 1 回で開通」 の裏に interactive 段が 2 つ隠れていた (2026-07-02 実測) → install 時自動 seed で design-out 済 + heartbeat `trust_error` marker が backstop ([remote-control-server.md #ts-workspace-trust](remote-control-server.md#ts-workspace-trust))
- **desktop app 切替 ≠ CLI 切替の認知乖離**: app で B に切替えても無人ルーチンは A のまま消費 → I5 の drift 検出が surface
- **session の自己アカウント同定を harness metadata で行う誤り (2026-08-28 実測)**: desktop app の session に harness が注入する userEmail と、 `~/.claude.json` の `oauthAccount` は、 どちらも **CLI 認証層** (= `claude auth login` した account) を映す — desktop app が別 account でログインしていても、 である (機構: app は bundled CLI に自 account の `CLAUDE_CODE_OAUTH_TOKEN` を env で渡すだけで、 CLI はメタデータを自分の config から組む)。 CLI login ≠ desktop login のマシンでは **desktop の全 session が誤った user email を注入され**、 Claude がそれを信じて自分を別 account と誤同定する。 信じてよい signal は process env (`CLAUDE_CODE_ENTRYPOINT` が `claude-desktop` か / `CLAUDE_CODE_HOST_SESSION_ID`) + app の per-account session registry (`~/Library/Application Support/Claude/claude-code-sessions/<accountUuid>/…/<hostSessionId>.json` = path が account を運ぶ)。 **同定 probe = [`scripts/claude-session-whoami.py`](../scripts/claude-session-whoami.py)** (= registry → cmdline fallback → CLI config の順、 fail-open で「未同定」 を email で埋めない。 logic 詳細 = script docstring。 I7 stamp の account 軸もこれで引く)。 なお app 内 MCP の session metadata (`get_session`) には account field が無い (2026-08-28 実測) = MCP 経路では同定できない
- **ブラウザ拡張 (Claude in Chrome) の署名 account ≠ session account、 および再ログイン後の stale 接続 (2026-09-05 実測)**: 拡張は自分の account で署名され、 session と食い違っていても **MCP tool は繋がる** (= 「不一致なら繋がらないはず」 は誤り、 2026-08-29 の仮説を棄却)。 症状は navigate だけ通り read / screenshot / click が全部 `Permission denied for this action on this domain`、 かつ permission prompt が (旧署名側に飛ぶので) user に見えない = 「prompt render バグ」 と区別がつかない。 さらに拡張を正しい account で入り直しても、 session は**旧接続を掴んだまま** (`list_connected_browsers` に旧・新 2 本) で症状が続く。 切り分け順 = ① whoami で session account ② 拡張 options の署名 account と比較 (userEmail で比較しない) ③ `list_connected_browsers` で `connectedAt` 最新を `select_browser` → 新 tab group が user の窓に開き prompt も出る (recipe = [web-tools.md #chrome-domain-permission-model](web-tools.md#chrome-domain-permission-model) の How to apply)。 拡張の account 切替は接続と tab group を増殖させる副作用も持つ (旧 group は閉じて可)
- **pinned config dir の alias と実 auth の乖離 (= mobile セルの名義取り違え)**: I1 の pinned dir は「dir 名 = account」 が運用前提だが、 OAuth 時に browser が別 account を選ぶと **別名義で auth された server がラベルどおりの顔で動き続ける** (= picker には両方「生きて」 見えるので silent)。 検出 = セル状態 check が dir 名と実 auth の email を突合して mismatch を 🔴 surface。 修復 = その dir で `claude auth login` をやり直し → server を kickstart — ⚠️ この OAuth が乖離の発生機構そのもの: **account 選択画面を出さず browser の claude.ai cookie の account で無言で通る**。 正しい account で認可する手順の正本 = [remote-control-server.md #oauth-grabs-browser-account](remote-control-server.md#oauth-grabs-browser-account)
- <a id="metadata-email-after-logout"></a>**login が切れても `.claude.json` の email は残る (実測)**: config dir の `.claude.json` の `oauthAccount.emailAddress` は、 keychain の token が消えて `claude auth status` が `loggedIn: false` を返した後もそのまま残る。 これを読んでセルを ✅ と出す表示は、 login 切れを隠す (Remote Control のサーバーも loaded のまま動いて見える)。 login の有無は、 その dir を `CLAUDE_CONFIG_DIR` にして `claude auth status` の `authMethod` が `claude.ai` かで見る (`loggedIn` だけを見ると API key の混入に騙される = [remote-control-server.md#local-auth-triage](remote-control-server.md#local-auth-triage))。 email は「どの account の dir か」 の印としてだけ使う
- **古い CLI が PATH 反転で優先解決され RC が死ぬ**: [remote-control-server.md #troubleshooting](remote-control-server.md#troubleshooting) の 3 パターン (version mismatch / API key 混入 / path_helper 反転)
- **auth の file-copy 誤解**: `.claude.json` を copy してもアカウントは移らない ([remote-control-server.md #account-auth-keychain](remote-control-server.md#account-auth-keychain))
- **ブラウザ拡張 (Claude in Chrome) のアカウント軸の見落とし (2026-08-20 実測)**: 拡張は Claude アカウントに署名して動き、 MCP 側の domain 許可・接続の観察は**拡張の署名アカウント**に紐づく。 session のアカウントと拡張の署名アカウントが食い違うと、 (a) 片方のアカウントで確認した権限設定が実際に動いている拡張には効いておらず、 (b) tool の失敗が `Permission denied for this action on this domain` / `Navigation to this domain is not allowed` と**ドメイン名指し**で返るため「このドメインはカテゴリ的にブロックされる (政府系 / 金融系)」 という**もっともらしい誤診**に誘導される (実測 = 官公庁系申請システムで誤診)。 第一手 = domain policy を疑う前に**拡張の署名アカウントを確認** (拡張アイコン → アカウント表示、 session 側は whoami probe — ⚠️ userEmail は desktop session では CLI 土台を映す嘘になり得る = 上の「harness metadata」 bullet)。 副作用 = 署名切替をまたいで接続し直すと **MCP タブグループが接続ごとに増殖** (旧 group が会話タイトル名で遺物として残る) — 旧 group のタブは閉じて良い。 なお claude.ai web タブのアカウント (= cookie) は拡張の署名とも session とも独立の**第 3 の軸**で、 「どの面がどのアカウントか」 は面ごとに個別確認が要る。 **MCP 接続の成立要件 (2026-08-29 RCA)** = 拡張の署名 account == **session の実 account** (`list_connected_browsers` は account-scoped の cloud relay を「this account」 で query する。 desktop session の実 account は app ログイン側 = whoami probe で同定、 claude.ai サイトの cookie login は無関係)。 拡張サイドパネルの警告「You're signed into claude.ai as a different account…」 は**サイト cookie vs パネル/拡張**の軸の話で、 MCP 接続要件 (= session vs 拡張) の診断根拠にしない — 実測事故: 警告文を接続障害の原因と誤読 + session 側を `.claude.json` 直読 (= CLI 土台の嘘) で誤同定した結果、 「account 一致なのに繋がらない」 という**偽の謎**と**逆方向の拡張切替誘導**が同時発生した。 診断は必ず ① whoami で session 実 account → ② 拡張 icon で署名 account → ③ 不一致なら拡張側を合わせる、 の順。 ①② 一致でも `[]` の場合は **relay 登録層の故障** (= パネルのチャットが正常でも automation bridge は別経路で未登録でありうる。 `switch_browser` broadcast が待機なしで「No other browsers available」 = relay にその account の拡張 instance ゼロ) → 復旧 runbook = [mcp.md #runbook-root-cause-checklist](mcp.md#runbook-root-cause-checklist)

- <a id="extension-one-account"></a>**ブラウザ拡張の署名 ≠ session で、 それまで一度も繋いでいない場合 (実測)**: `list_connected_browsers` は `[]`、 `switch_browser` はすぐに「No other browsers available」 を返す = 繋がらない。 上の「署名が食い違っていても MCP tool は繋がる」 は、 旧い署名のときの接続が残っている場合の話として読む (新しいマシン・新しい profile では残る接続が無い)。 拡張の署名は desktop app のアカウント切替と別のログイン = 連動する前提で扱わない。 **1 つの拡張が持てる署名は 1 アカウント**だが、 browser の profile を分けて各 profile の拡張に別アカウントで署名しても解にならない (2026-09-25 実測): `list_connected_browsers` の deviceId は profile ごとでなく**その機械に 1 つ**で、 一覧には常に 1 台しか出ず、 最後に中継へ入り直した profile の拡張が使われる (もう片方の拡張をトグルすると、 その瞬間にそちらへ切り替わる)。 しかも session の account と拡張の署名が食い違う組でも list / navigate / read が通った (両方向で実測) = **署名の一致は接続の要件ではない**。 上の「一度も繋いでいない場合の `[]`」 は署名でなく中継への未登録と読み直す (復旧 = [mcp.md #runbook-root-cause-checklist](mcp.md#runbook-root-cause-checklist))。 署名が効くのはサイドパネルのチャットの account。 app のアカウントを切り替えて使う人は profile 1 つ・署名 1 つでよい。 ⚠️ 同じ deviceId の別 instance (消した profile の拡張) が落ちた直後は、 残った profile の拡張をトグル・パネル開放・browser 再起動しても登録が戻らないことがある (実測)。 **新しいマシンへの新規 install の直後にも同じ詰まりが起きる** (実測: 復旧の梯子の 4 段すべてが効かず `[]` が続いた)。 このとき **session の account を拡張の署名に揃えても登録は起きない** (実測) = 「署名の一致は接続の要件ではない」 は逆向きにも成り立ち、 **account 軸は登録の梯子の外**。 ∴ `[]` の診断で account を替える手は段に数えず、 中継側を疑う段へ進む。

## <a id="honest-limits"></a>正直な限界

- **マシン間の state は直接見えない**: マシン 1 から マシン 2 の server 稼働は直接 query できない。 見える経路は (a) スマホ / web の environment 一覧 (= そのアカウントに登録済みの生きた server が全部出る = 事実上の fleet view)、 (b) git-commit された台帳 / heartbeat。 「別マシンも動いているはず」 は必ずこのどちらかで verify する。 (b) を体系化した bounded-staleness の fleet view = [multi-machine-state.md #fleet-heartbeat](multi-machine-state.md#fleet-heartbeat) (= 毎時の自己報告 + role 別 staleness 判定。 「直接見えない」 が「数時間以内の異常は自動 surface される」 に狭まる)
- **スリープ中のマシンのセルは死んでいる**: 可搬機は蓋を閉じれば environment から消える。 これは仕様 (= 常時起動機を本番、 可搬機を best-effort と役割分けする)
- <a id="session-list-per-account"></a>**desktop app の session 一覧はアカウントごと → 写しの道具で両方の一覧に出す**: app は session の登録を account ごとの dir (`<userData>/claude-code-sessions/<account>/<org>/local_*.json`) に持ち、 今の account の分だけを一覧に出す (dir を読み直すのは account の切替と再起動の時だけ = 表示中の account の dir に外から足しても、 次に読み直すまで出ない)。 スマホから見える desktop session も、 その session を開いた account の側にだけ出る。 会話記録 (CLI の transcript) は desktop の configDir (`~/.claude`) の `projects/` に入るので、 一覧に出なくても中身は相互に読める。 app の「インポート」 は、 別 account の session を企業向けの local-storage 構成でしか取り込まず、 CLI session の取り込みはどれかの account が既に持つ session を除く (= 別 account の desktop session は候補に出ない。 app 本体で確認 = [claude-app-bundle-reading.md](claude-app-bundle-reading.md))。
  - **道具 = [`scripts/claude-app-account-mirror.py`](../scripts/claude-app-account-mirror.py)** (常駐 = [`scripts/install-claude-app-account-mirror.sh`](../scripts/install-claude-app-account-mirror.sh)、 launchd が session dir の変化と 5 分ごとに回す)。 別 account の session を、 公式インポートが disk に書くのと同じ形 (最小の record + 同じ変換をした会話記録を `imported-staging/` に) の「インポートした session」 として写し、 題名の頭に元 account の印を付ける。 写しを開くと app が再開を確かめて会話記録を `projects/` へ移す (app 本体の読み。 実 app での最初の確認はまだ) = 元と別の会話記録を持つ独立した session (両方の account で同時に開いても元は壊れない)。 書くのは app が表示していない account の dir だけ。 範囲・差し替え・消す条件・台帳・止め方の正本 = script の冒頭。
  - **限界**: (1) 写しはその時点の写し = 開いて続けた分は元に戻らない (枝分かれする。 開いた写しの続きは逆向きに写る) (2) 表示中の account の dir には書かない = そちらへの写しは account を切り替えるまで (または app を終了するまで) 遅れる (3) app の非公開の仕組みに依存 = app の版が変わるたびに本体 (app.asar) を点検し、 前提が 1 つでも欠けたら写すのを止めて状態に出す (4) 写した会話記録の分だけ disk を使う (5) スマホから新しく始めた session (desktop の一覧に載らない) と、 マシンをまたぐことは範囲外
  - ⚠️ **Claude (auto mode) からは `--apply` も install も実行しない**: 登録 file を別 account の dir に書く操作は、 classifier が session 記録の改ざんとして止める (実測) = 本人が terminal で入れる。 dry-run・`--status`・`--notice` は読むだけで、 何も書かない
- <a id="connector-per-account"></a>**アプリ内蔵の connector (claude.ai のコネクタ) は claude.ai の account 単位**: どの機械から繋いでも、 同じ account の全機械に出る (実測: 別の機械から繋ごうとすると「もう繋がっています」)。 Google の connector は種類ごとに別々に認可するので、 種類ごとに別の Google アカウントを選べる。 **棚卸しは account ごとに claude.ai の設定 → コネクタ → 「自分のもの」 で数え、 Code の session のツール一覧では数えない** = つないだ connector が届くのはつないだ後に始めた session (と一部の開いている session) で、 開始済みの session のツール一覧には出ないことがある (実測)。 設定画面の一覧も、 別の機械で繋いだ直後は古いまま出ることがある (実測)。 画面で account を見分ける手がかり = 左下の表示名 (設定画面にメールアドレスは出ない)
- **remoteControlAtStartup の適用範囲**: CLI の対話 session に効くことは実測済。 desktop app 内 session への適用は環境により要実測 (= 設定後に新 session を開いて web / スマホの一覧に出るかで確認)

## Cross-refs

- RC server の機構・複数アカウント構成・auth の keychain 束縛・troubleshooting: [remote-control-server.md](remote-control-server.md)
- マシン間 state の規律・active-host failover: [multi-machine-state.md](multi-machine-state.md)
- 並列 session の race 防御 (= 同マシン内の別軸): [multi-session-coordination.md](multi-session-coordination.md)
- 無人ルーチンの登録機構: [scheduled-tasks.md](scheduled-tasks.md)
