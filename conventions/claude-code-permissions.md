<!-- doc-meta
when: Claude Code の permission prompt 削減・deny/ask/allow 設計を触るとき
category: harness-core
summary: Claude Code CLI の permission プロンプト削減 (= cwd 外 file 〔`~/Downloads` 等〕の Read/Edit/Write が毎回確認される症状を `additionalDirectories` で cwd 同様に無確認化、 bare tool allow は cwd 外を素通ししない observed〔docs 解釈と食い違い〕、 deny > ask > allow で機密は `deny` 優先、 setup.sh `configure_permissions` は `allow` のみ触る = additionalDirectories/deny は直書き永続、 settings 反映は安全側に次セッション〔allow 追加と disableAllHooks 除去は desktop 2.1.260 で同 session 即時を実測〕、 #chat-link-rendering-scope = chat 応答内の markdown link `[label](path)` を click した右パネル rendering も同 scope〔session cwd + additionalDirectories〕に従い scope 外は「読み取れませんでした / 作業ディレクトリの外」 表示〔#rc-chat-panel-no-render = Remote Control 閲覧では scope 通過でも同一 error で render 不可 = file が worker host 側にのみ在る、 唯一 RC で完結する対処 = 内容を chat 本文に出させる、 observed n=1〕、 frontend 3 系統切り分け〔CLI settings.json / Claude Code デスクトップ Tool policy / macOS TCC〕、 §always-approve-tools = permission 設定で抑止できない always-prompt tool class〔`ccd_session_mgmt__search_session_transcripts` 等 cross-session tool は `allow` 登録でも承認チップが出る = 経路を外す以外に消せない、 token-handshake 返送への含意込み〕、 #ask-pattern-action-anchor = 高 stakes Bash gate の ask パターンは file 名 substring でなく不可逆 action の実行形〔`--send` 等の explicit flag〕に anchor〔ask > allow ゆえ allow で例外を彫れない = パターン絞りが唯一の手段・tool 側は fail-safe 既定・gate 対象 invocation は chain 禁止〕、 #desktop-permission-dialog-log = desktop の承認 dialog は app log に 1 件 2 行 〔Emitted / Received〕 で残る → scripts/permission-dialog-audit.py で tool 別集計と main / sub-agent 振り分け、 #monitor-needs-own-allow = Monitor は Bash の allow にも内容 ask rule にも掛からない独立 tool、 #agent-launch-no-prompt = Agent 起動は allow 済なら dialog 無し 〔「背景作業で聞かれる」 = Monitor / spawn chip / Workflow / 中身の ask gate〕、 #protected-settings-edit = Claude による .claude/settings*.json 等 protected path の編集は default mode では毎回 dialog 〔allow rule で消せない = 公式 docs、 auto は classifier 判定〕・Bash で迂回しない・「毎回」 と言われたら先に dialog 内訳を実測・desktop のモード選択はフォルダごとに defaultMode より優先、 #symlink-both-paths = symlink の path と実体 path の両方を登録、 #file-rule-tools = path rule を見るのは Read/Edit だけ 〔Write/Glob の rule は参照されない、 名指ししない間接読みは塞げない = sandbox〕、 #always-allow-persists-literal = 「常に許可」 は command 文字列を settings.local.json に保存 → secret を command に書かない、 #long-command-falls-back-to-ask = 長すぎる Bash は auto の自動承認から外れて dialog になり pattern 化できないので「常に許可」 も出ない 〔実測 2,111 通過 / 4,272 dialog、 backstop = hooks/long-bash-command-guard.sh が閾値超を block して分割・file 経由へ誘導、 guard の自己参照は自分の source/test/doc だけ除外〕、 承認 dialog の原因切り分けは scripts/permission-dialog-audit.py --diagnose が hook / fixed / length / rule / unmatched に自動分類)
-->
# Claude Code の permission プロンプトを減らす (additionalDirectories と working directory 境界)

Claude Code CLI で「**ファイル操作のたびにアクセス権を聞かれて鬱陶しい**」を構造的に解消するための規約。とくに作業ルート (cwd) の外にあるファイル (GUI の置き場 `~/Downloads` / `~/Desktop` / `~/Documents` など) を弄らせるときに毎回確認が出る症状が対象。

## 症状

cwd 配下のファイルは確認なしで編集できるのに、cwd の**外**のファイルを Read / Edit / Write させると操作ごとに「Allow / Deny」を選ばされる。スプレッドシートやダウンロードした添付など、cwd 外に落ちているファイルを処理させると連続して聞かれる。

## 核心: working directory 境界は tool allow とは別レイヤー

- `permissions.allow` に **bare tool name** (`"Read"` / `"Edit"` / `"Write"` / `"Bash"`、パラメータ無し) を入れると「そのツールを使ってよいか」は許可される。
- だが対象**ファイルパスが cwd の外**だと、それとは別の file-access 境界チェックが走り、確認が出る。
- ⚠️ **docs と実挙動の食い違い**: 公式 docs ([permissions](https://code.claude.com/docs/en/permissions) の "Working directories") は「`additionalDirectories` 配下は cwd と同じ扱い」と書く一方、bare allow が cwd 外をどこまで素通しするかは曖昧。**実運用 (observed) では bare `"Read"` allow があっても cwd 外ファイルで確認が出て、path 別 allow (`Read(//abs/path/**)`) か `additionalDirectories` 登録が必要だった**。
  → 教訓: 「bare allow を入れたから cwd 外も通る」と仮定しない。cwd 外は `additionalDirectories` で**明示登録**する。
- 補足 (要検証): Bash tool 経由 (`cat`/`grep` 等) は cwd 外パスでも通りやすい一方、Read/Edit/Write tool は cwd 外で止まりやすい、という非対称が観察された。docs は両者を同 scope と説明しており食い違うため、機構は断定しない。実用上は「cwd 外を確実に無確認化したいなら additionalDirectories」で済む。

## 対処: additionalDirectories

`~/.claude/settings.json` の `permissions.additionalDirectories` に cwd 外の作業ディレクトリを**絶対パス**で登録すると、その配下は cwd と同じ扱いになり Read/Edit/Write が無確認になる。

```json
{
  "permissions": {
    "additionalDirectories": ["/Users/<you>/Downloads", "/Users/<you>/Desktop"]
  }
}
```

- `/add-dir` コマンドは **runtime の動的追加** (その session 内のみ)。永続させたいなら settings.json の `additionalDirectories`。
- <a id="symlink-both-paths"></a>macOS で `~/Dropbox` 等が **symlink** の場合は、 **symlink の path と実体 path の両方**を登録する (`ls -ld` で実体を確認)。 Claude は同じ file を symlink 経由でも実体 path でも指すので、 片方だけだと、 もう片方の形で開いた file が scope 外として毎回 dialog になる (2026-09-12 実測: `~/Dropbox` だけ登録していて、 `~/Library/CloudStorage/Dropbox/...` の形で開いた file の編集が dialog になった)。 allow / ask / deny の path rule も両方の形で書く (公式 docs: allow rule は symlink の path と実体の両方が一致したときだけ効く)。

## 機密は deny で守る (deny > ask > allow)

- rule の評価順は **deny → ask → allow**。最初に match した rule が勝つので、**deny が最強**。
- `additionalDirectories` で広いディレクトリ (例: home の `Documents` や `Dropbox` 全体) を開けても、その中の機密サブフォルダは `permissions.deny` で個別 block できる。deny の方が優先されるので、「広く開けて一部だけ塞ぐ」が成立する。
- <a id="file-rule-tools"></a>file の path rule を見るのは **`Read(path)` と `Edit(path)` だけ** (公式 docs `permissions`、 Claude Code v2.1.210 以降)。 `Write(...)` / `NotebookEdit(...)` / `Glob(...)` の path rule は受け付けられるが**参照されない** (起動時に警告が出る) — 書き込みは `Edit(...)` で、 Glob は `Read(...)` で塞ぐ。 `Read` / `Edit` の deny rule は、 Claude Code が Bash の中で認識する file コマンド (`cat` / `head` / `tail` / `sed`) と redirect 先 (`> file` / `< file`) にも効く。 ただし **file を名指ししない読み方** (その dir での `grep -r pattern .`、 script が中で file を開く) には効かない。 全 process を止める OS レベルの遮断は sandbox (公式 docs `sandboxing`)。 `Bash(*/abs/secret*)` のような内容 rule は、 path を直接書いたコマンドだけを捕まえる歯止め。

## 反映タイミング

settings.json はセッション開始時に読まれる。**途中変更が即反映されるかは docs に明記が無い**ので、安全側に「**次セッションから有効**」と考える。書き換え後は次の実作業で「もう聞かれない」ことを確認する。

**実測 (2026-09-11、 desktop 埋込 2.1.260)**: `permissions.allow` への追加 (例 `Monitor`) と `disableAllHooks` の除去は、 **同じ session の次の tool call から**有効になった (allow 追加直後の Monitor 呼び出しで dialog が出ず、 app log にも承認要求が記録されなかった)。 ∴ 少なくともこの 2 種は「次セッションから」 ではない。 他の key (deny / ask / additionalDirectories / defaultMode) は未測定なので、 安全側の既定は変えず、 変えたら次の実作業で 1 回確かめる。

## このリポ (claude-config) の setup.sh との関係

`setup.sh` の `configure_permissions()` は `permissions.allow` に安全ツール (Bash/Read/Edit/Write/Glob/Grep/WebFetch/WebSearch) の**不足分を足すだけ**で、`additionalDirectories` と `deny` には**一切触らない**。
→ `~/.claude/settings.json` に直書きした `additionalDirectories` / `deny` は **setup 再走でも消えない** (永続)。バックアップを取ってから jq で書き換えるのが安全。

## <a id="chat-link-rendering-scope"></a>chat 右パネルの markdown link rendering も同 scope に従う

Claude Code (desktop app / VS Code 拡張の chat panel) は、応答本文内の markdown link `[label](path/to/file.md)` を click すると右パネルで file を render する。この rendering は **Read/Edit/Write tool と同じ permission scope** (= session cwd + `additionalDirectories`) を通し、**scope 外の path は render 拒否**される (= 同じ working directory 境界の別 surface)。

**症状**: chat 内の link を click した右パネルに以下いずれかが表示される (file 実在にも関わらず):

> このファイルを読み取れませんでした — 削除または移動された可能性があるか、作業ディレクトリの外に存在する可能性があります

**診断**:

0. **Remote Control 経由で見ていないか** (→ 下の「Remote Control 経由では scope 通過でも render 不可」)。RC なら 1-3 は無関係 — scope を直しても解決しない。
1. session の実 cwd を確認 (session 起動時に選んだ folder — `pwd` 相当)。
2. click した link の href (相対 path なら cwd 基準で解決) の絶対 path を求める。
3. `~/.claude/settings.json` の `permissions.additionalDirectories` に、その絶対 path の**祖先 dir** が登録されているか。

祖先が登録されていなければ scope 外 = rendering 拒否される (= 期待通りの enforcement)。file 実在・path form (相対 / 絶対) は原因ではない。

**対処**: 該当 path の親 dir を `additionalDirectories` に追加 (§対処 / §機密は deny で守る と同じ手順)。**反映は次 session から** (§反映タイミング)。

**応急 (現 session で見たい)**: chat 右パネル rendering は諦め、`open <path>` で外部アプリ (Preview / エディタ) に投げる。OS 経由なので Claude Code の permission scope を通らない。

⚠️ **診断反射の落とし穴**: error message は「削除または移動された可能性」 を並列で提示するため、**path form 誤り (相対 vs 絶対、typo、リネーム) を先に疑って retry する**引力が強い。file 実在・form 正しい状態で失敗が続いたら、次に触る仮説は **scope 外**であって別 form の retry ではない (= 単一情報源〔error message〕null からの結論飛躍防止)。1 コマンドで確認できる: `jq '.permissions.additionalDirectories' ~/.claude/settings.json`。

**frontend 差**: この rendering scope 挙動は **chat 右パネルを持つ frontend** (= desktop app、VS Code 拡張の chat panel) で発生する。CLI-only session には右パネル rendering 自体が無いので該当しない。scope 判定機構自体は harness 側で共通 (= Read/Edit/Write tool と同じ layer)。

### <a id="rc-chat-panel-no-render"></a>Remote Control 経由では scope 通過でも render 不可

**scope 診断 (上の 1-3) を全部通過しているのに拒否される**ケースがある: session を **Remote Control で別端末から閲覧している**とき。file は worker host のディスクにあり、**閲覧している端末側には存在しない**ため、右パネルは render できない。error message は scope 外のときと**同一文言** (「削除または移動された可能性があるか、作業ディレクトリの外に存在する可能性」) なので、**scope 問題だと誤誘導される** (= 「作業ディレクトリの外」はどちらの原因でも表示される)。

- **見分け方**: scope 3 段が全部 ✅ なのに拒否 → 次に疑うのは「この画面は RC か」。session の worker host は冒頭の自己同定 stamp ([multi-account-machine-surface.md I7](multi-account-machine-surface.md)) か `hostname` 1 発で確認できる。
- **対処**: worker host 側の画面で開く / `open <path>` を worker host で実行して OS アプリに出す (RC 画面には届かない) / **内容を chat 本文に出させる** (= text は bridge を通るので RC でも読める。唯一 RC 画面で完結する手)。
- ⚠️ observed n=1 (2026-07-27、user 側の切り分けによる同定。scope 3 段通過 + file 実在 + RC 閲覧の組で再現、worker host 側での表示は未検証)。

**Bash 経由との非対称**: 上記 §核心 / §対処 の Bash tool は cwd 外 path でも通りやすい観察と同型 (= Bash は permission 判定が緩い、Read/Edit/Write と chat rendering は厳しい)。「Bash で `cat <path>` は通ったのに chat link は落ちる」という非対称は、この scope 差の同じ現れ。

## <a id="frontend-split"></a>frontend 切り分け (同じ症状でも 3 系統)

「いちいちアクセス権を聞かれる」は別系統の原因がありうる。**対処の前にどのフロントエンドか切り分ける** (Claude は CLI / デスクトップアプリ / IDE 拡張の 3 経路で使われうる):

1. **Claude Code CLI** — `~/.claude/settings.json` の permission (本ドキュメント)。
2. **Claude デスクトップアプリ (local agent mode)** — アプリ内の**別設定系統**。settings.json をいじっても変わらない。減らすには: 承認ダイアログ `Allow Claude to use {toolName}?` で「常に許可」を選ぶ / 設定の `Tool policy`・`Lock the approval state for specific tools` で事前承認 / `Allowed workspace folders` に作業フォルダ登録 / (最終手段) `bypass permissions mode`。skill 本体は `~/Library/Application Support/Claude/local-agent-mode-sessions/.../skills/<name>/SKILL.md` に展開されるので、ここに skill があれば「デスクトップアプリ経由」のサイン。
   - **設定 / UI 仕様の調べ方**: 設定キーは `~/Library/Application Support/Claude/config.json` / `claude_desktop_config.json` (例: `coworkUserFilesPath` = Claude Code (desktop) の作業ルート)。 UI ダイアログ文言は `strings /Applications/Claude.app/Contents/Resources/app.asar | grep -oE 'defaultMessage:"[^"]+"'` で抽出できる (= 上記の `Allow Claude to use {toolName}?` 等はこの方法で確認した)。
   - ⚠️ **誤診注意**: `config.json` の `dxt:allowlistEnabled` は **組織レベルの desktop 拡張 (DXT / MCP) のインストール許可管理** (`is_desktop_extension_allowlist_enabled`) であって、 **ツール実行の承認プロンプトとは無関係**。 これを「毎回聞かれる原因」と単一手がかりで推測しないこと (= 実際に一度そう誤推測 → app.asar 精読で別物と判明し訂正した。 inline §3「単一情報源で結論に飛躍しない」の Claude Code (desktop) domain 事例)。
   - ⚠️ **「settings.json をいじっても変わらない」 の例外 = `deny` (2026-06-13 実測)**: desktop でも `~/.claude/settings.json` の `permissions.deny` は **honor される** (= 無害な deny 対象コマンドを叩くと block された)。 desktop で効かないのは **hook 出力** (= [`hook-authoring.md` frontend-dependent-cowork](hook-authoring.md#frontend-dependent-cowork)) と **`defaultMode: bypassPermissions` 下の ask** (= bypass は全 tool auto-approve なので ask が void)。 **だが `defaultMode: default` なら settings.json の `permissions.ask` は desktop でも効く** (= 2026-06-13 実証: send_email を ask にすると内容表示つき承認 dialog が出て拒否で送信ブロック。 下記「desktop で特定 tool に確認を課す」)。 ∴ desktop UI の「バイパス権限モードを許可」 トグルは lever ではなく、 **settings.json の `defaultMode` が実効モードを支配**する (= トグル OFF だけでは gate されない)。 ⚠️ **2026-09-11 注**: 「desktop で hook 出力が効かない」 の観測の少なくとも一部は、 作業 root の project-local に入っていた `disableAllHooks: true` が原因だった ([`hook-authoring.md#disableallhooks-kill-switch`](hook-authoring.md#disableallhooks-kill-switch))。 除去後の desktop では PreToolUse の ask / PostToolUse の additionalContext が効いた。
3. **macOS TCC** (OS のフォルダアクセス許可、Desktop/Documents/Downloads 等の保護) — macOS システムダイアログで、Claude 側の設定では消えない。Claude.app が versioned path に置かれる影響で再 prompt される構造的症状は [`macos-claude-code-tcc-recurring-prompt.md`](macos-claude-code-tcc-recurring-prompt.md) 参照。

## <a id="desktop-per-tool-gate"></a>desktop で特定 tool に確認を課す (= hook 不可な frontend での per-tool gate、 2026-06-13)

PreToolUse hook (mail 誤送信 guard 等) は desktop で出力 honor されず inert と観測されていた (= §frontend 切り分け 2 / [`hook-authoring.md` frontend-dependent-cowork](hook-authoring.md#frontend-dependent-cowork)。 ⚠️ 2026-09-11: その少なくとも一部は root 限定の `disableAllHooks` が原因 = [`hook-authoring.md#disableallhooks-kill-switch`](hook-authoring.md#disableallhooks-kill-switch)。 hook が効く surface でも、 本 recipe の declarative ask は hook と独立に効く第二の層として有効)。 desktop で「特定の高 stakes tool だけ実行前に人間が一拍」 を機械的に課す working recipe は **settings.json の permission のみ** (= hook 不要、 2026-06-13 実証):

1. `permissions.defaultMode` を `bypassPermissions` → **`default`** か **`auto`** に (= bypass は ask を void するので外す)。 `auto` でも ask rule は dialog を強制する (公式 docs `permission-modes`)。 ただし auto に入ると bare `Bash` 等の広い allow は外れ、 allow 外の操作は classifier 判定になる。 `auto` は `~/.claude/settings.json` (user scope) に書かないと効かない (project の `.claude/settings*.json` では無視される)。
2. `permissions.ask` に確認したい tool を列挙 (例: `mcp__gmail-personal__send_email` 等)。 → 呼出のたび **引数 (to/subject/body) を全表示する承認 dialog** が出て、 拒否で実行ブロック (= 内容確認つきの一拍)。
3. `permissions.allow` に **日常 tool を server-level で列挙** (= `mcp__gmail-personal` 等の MCP server 名、 + bare `Bash`/`Read`/`Edit`/`Write` 等)。 default mode は allow リスト外を prompt するので、 これが無いと全 MCP が毎回確認になる。 precedence **deny > ask > allow** なので server-level allow があっても `ask` の特定 tool だけは確認が残る (= 「mail だけ確認・他は素通り」)。

⚠️ 注意:
- **machine-local** (`~/.claude/settings.json` は git 非同期 = §個人ごとの適用)。 別マシンで desktop 運用するなら各自設定。
- desktop UI 「バイパス権限モードを許可」 は **OFF 維持** (ON だと session が bypass に入り ask が void)。
- allow リスト外の稀な MCP tool は prompt が出る (= 「常に許可」 で都度解消 or allow に追加)。
- hook の完全代替ではない (= draft 全文提示 + autonomy 禁則の文面までは再現せず「内容表示 + 人間承認」 まで)。 一次防御は CLAUDE.md の discipline (全 frontend で読まれる)、 本 recipe は機械の一拍を足す第二視点。
- 一般原理 (= enforcement surface の frontend 生存性) は [`docs/convention-design-principles.md §8.15`](../docs/convention-design-principles.md#enforcement-surface-frontend-survival)。

## <a id="ask-pattern-action-anchor"></a>ask パターンは「tool への言及」でなく「不可逆 action の実行形」に anchor する (2026-07-03)

高 stakes 操作 (メール送信等) を `permissions.ask` の Bash パターンで gate するときの設計規約。

**なぜ ask パターン自体を狭くするしかないか**: precedence は deny > ask > allow で、**ask は allow に勝つ**。つまり「広い ask を張って、無害ケースだけ allow で例外を彫る」は構造的に組めない。誤爆を消す手段は ask パターンの絞り込み**だけ**。

**誤爆の失敗モード**: 対象 script の file 名 substring に match するパターン (例: `Bash(*send_mail.py*)`) は、不可逆 action だけでなく「file 名に言及するだけの無害コマンド」全部に発火する — syntax check (py_compile) / git add / grep / (実行前に必須とされる) dry-run。すると ① 承認ダイアログが「危険操作の合図」でなく「開発ノイズ」になり、② user が反射で承認する習慣がつき、③ 本物の dialog も反射承認される = **gate の信号価値が壊れて実質死ぬ** (実例 2026-07-03: syntax check + commit + push の chain に送信 gate が発火し続け、user が「いちいち聞かれてうざい」と flag)。

**設計 3 点 set**:

1. **tool 側を fail-safe 既定にする**: 不可逆 action に explicit flag (例: `--send`) を必須にし、flag 無しは常に dry-run。flag を忘れた時の事故方向が「実行されない」になる。
2. **ask は action flag の実行形に anchor**: 例 `Bash(*send_mail.py*--send*)`。不可逆 invocation だけが ask を踏み、開発・記録・検証系コマンドは素通り。
3. **gate 対象 invocation は chain しない**: ask の match は Bash command 文字列単位なので、`&&` chain の 1 成分が match すると **dialog は chain 全体を表示**する (= 承認対象がぼやける + 無関係な成分に確認が伝染)。逆も然りで、「commit + push を atomic に chain する」類の良規律と広い ask パターンは正面衝突する。gate を踏むコマンドは単体で打ち、dialog = action そのものにする。

⚠️ **移行順序は「tool の fail-safe 化が先・ask の絞り込みが後」厳守**: 「絞った ask (flag anchor) + 旧 default-実行 tool」の組合せは、flag 無しの実行が ask に match せず**素通りで実行される** (= 唯一の危険な遷移順)。逆順 (旧 broad ask + 新 fail-safe tool) は誤爆が残るだけで安全。複数マシン運用では、tool が git 同期・settings.json が machine-local なため**マシンごとにこの順序ずれが起きうる** — 必ず tool 側の pull を確認してから ask を絞る。

⚠️ **この gate の限界 (= 過信しない)**: ask の match は「typed command 文字列」への glob なので、変数間接 (`S=<path>; python3 $S --send`) や glob 表記で literal を外すと素通りする。敵対的回避への防御ではなく、**good-faith な呼び出しに機械の一拍を課す speed bump**。最終防御は呼び出し側の規律 (draft 提示 + user 明示承認) と、hook が生きている surface での hook 層。

反映は session 起動時ロード (§反映タイミング) なので、パターン変更後も**既存 session には旧パターンが残る**。domain 実例 (メール送信の --send 化) は [`gmail-sending.md`](gmail-sending.md#permission-gate-anchor)。

## <a id="always-approve-tools"></a>permission 設定で抑止できない tool (= always-prompt class、 2026-06-28)

一部の tool は **tool 側が「毎回明示承認を要求する」と宣言**しており、 settings.json の permission layer (`allow` / `defaultMode`) では**抑止できない**。 承認 dialog にこの一文が出る:

> This tool requires explicit approval **regardless of permission mode.**

**観測 (2026-06-28)**: `mcp__ccd_session_mgmt__search_session_transcripts` が、 `permissions.allow` に **明示登録済** (= `mcp__ccd_session_mgmt` も `mcp__ccd_session_mgmt__search_session_transcripts` も列挙済) かつ `defaultMode: default` の状態でも承認チップを出した。 ∴ この class は **deny > ask > allow の precedence の外**にある tool-level の always-ask で、 **`allow` に入れても素通りにならない**。

- **settings.json では消せない**。 `bypassPermissions` でも出る想定 (= dialog の "regardless of permission mode" 文言どおり。 ただし bypass 下の実測は未取得ゆえ「想定」)。 precedence 最強の `deny` だけは**ブロック (= 実行自体を不可)** にはできるが silent-allow にはできない (= deny 挙動も未実測)。
- **回避は「呼ばないこと」**: チップを踏みたくなければ、 その tool を経路から外す (= 抑止設定でなく経路設計で避ける)。
- **該当が確認できている tool**: `ccd_session_mgmt__search_session_transcripts` (= 直接観測のみ)。 同 server の cross-session 系 (`send_message` / `archive_session` 等) も同機構で同挙動と**推定**されるが直接観測は search のみ。 `list_sessions` も allow 済だが挙動は未観測 (= 過度に一般化しない、 inline §3「単一観測を universal に飛躍させない」)。

**token-handshake 返送への含意** ([`multi-session-coordination.md §7`](multi-session-coordination.md#spawn-handoff-token-return)): 返送の **optional live-push** (`search_session_transcripts(<token>)` → `send_message`) はこの always-prompt class を必ず通るので、 **起票元へ返すたびにチップが出る** (= allow-list で消せない)。 チップを踏まずに結果を届けたいなら、 §7 の **required spine = "results inbox" marker** (= 子の完了 action で marker を 1 個落とし、 surfacing 機構が拾う) に寄せる。 marker 経路は cross-session tool を呼ばないのでチップが出ない。

## <a id="desktop-permission-dialog-log"></a>desktop の承認 dialog は app log に残る — 体感でなく数える (2026-09-11)

「いちいち聞かれる」 の対処は、 **どの tool の dialog が何件か**を数えてから決める (= allow に足すのか、 仕様で消せない class か、 gate として残すべきか)。 desktop app は dialog ごとに `~/Library/Logs/Claude/main*.log` へ次の 2 行を書く (同じ行が 2 回ずつ出ることがあるので request id で数える):

```text
<YYYY-MM-DD HH:MM:SS> [info] Emitted tool permission request <id> for <tool> in session <local_id>
<YYYY-MM-DD HH:MM:SS> [info] Received permission response for <id>: once|always|deny (tool: <tool>)
```

- 時刻は local time。 Emitted → Received の差がそのまま user の応答待ち時間 (= 席を外していた間、 作業が止まっていた時間)。
- **道具**: [`scripts/permission-dialog-audit.py`](../scripts/permission-dialog-audit.py) — tool 別件数・decision 内訳・待ち時間。 `--attribute` で transcript の tool_use と時刻突合して **main session / sub-agent / 不明**に振り分け、 Edit/Read/Write は path の上位 2 階層、 Bash は先頭語で束ねる (= どの folder の ask gate が鳴っているかが見える)。 log の無い環境 (CLI) は `--from-transcripts` で「通常すぐ返る tool が長く止まった」 箇所を候補として出す。
- **mode を疑う前に hook を疑う**: PreToolUse hook が `permissionDecision: "ask"` を返すと、 `acceptEdits` / `auto` でも dialog が出る (= mode では消えない)。 dialog の出た tool call の入力をその hook に流し直せば、 どの hook のどの判定かが確定する。 **この切り分けは毎回同じ手順なので `--diagnose` が自動でやる**: `permission-dialog-audit.py --diagnose --latest 10` が transcript から当時の tool 入力を復元し、 matcher の当たる PreToolUse hook に流し直して、 **hook** (今も ask) / **fixed** (今は exit 2 で block = dialog は出ない) / **length** ([#long-command-falls-back-to-ask](#long-command-falls-back-to-ask)) / **rule** (hook 無反応 = allow・cwd scope・protected path 側) / **unmatched** に分類し、 消し方を 1 行で出す。 ⚠️ hook を実際に実行するので、 副作用のある PreToolUse hook を書いているなら `--no-run-hooks`。 ⚠️ 出るのは「**今の**設定に当時の入力を流した結果」 = 過去の原因の再生ではない (hook を直した後は「もう出ない」 と読む)。 実例 (2026-09-12): 公開 repo への Write の dialog 5 件のうち 4 件は、 leak guard が test fixture の `@example.invalid` 等を email として拾った誤発火だった (commit 時の gate は RFC 2606 の例示 domain を通すのに、 編集時の hook だけ通さなかった) → 両 gate の allowlist を揃え、 一致を test で固定。
- **実例 (2026-09-11)**: 6 週間分 約 280 件を数えたところ、 sub-agent の tool call 由来と Agent 起動そのものは **0 件**。 「背景作業を立ち上げるたびに聞かれる」 の正体は allow に入っていなかった `Monitor` (5 件、 うち 1 件は 40 分待ち) で、 残りの大半は意図して置いた ask gate (特定 folder への Edit/Read・メール送信) と browser 系の初回許可だった。

## <a id="monitor-needs-own-allow"></a>Monitor は独立した tool — Bash の allow も ask も掛からない

`Monitor` (背景で command を走らせて出力を監視する tool) はシェルを実行するが、 **permission rule は tool 名単位で照合される**ので:

- bare `Bash` を allow していても Monitor は allow されない → 起動のたびに dialog が出る (背景作業のつもりで席を外すと、 そこで止まったまま待つ)。 使うなら `permissions.allow` に `"Monitor"` を足す。
- 逆に Monitor を allow すると、 `Bash(*send_mail.py*--send*)` のような **Bash の内容 rule による ask gate は、 Monitor 経由の実行には掛からない** ([#ask-pattern-action-anchor](#ask-pattern-action-anchor) の gate が素通り)。 高 stakes の action を Bash の ask で守っているなら、 それを Monitor で実行しない規律にするか、 tool 側の gate (MCP tool への ask 等) に寄せる。 MCP tool への ask は tool 呼び出しそのものなので、 Monitor の allow とは無関係に残る。

## <a id="agent-launch-no-prompt"></a>Agent (sub-agent) の起動は allow 済みなら dialog を出さない

`Agent` / `Task` の起動そのものは、 allow に入っていれば承認を求めない (2026-09-11、 6 週間分の app log で起動由来の dialog 0 件)。 sub-agent の中の tool call も main と同じ permission 設定で判定され、 同期間に sub-agent 由来の dialog は 0 件だった。 「背景作業を始めると聞かれる」 ときに疑うのは:

1. **Monitor** (上節) — allow に無ければ毎回 dialog
2. **spawn_task の chip** — 別 session の起動は user のクリックが仕様 (自動で起動する設定は無い)
3. **Workflow** — 起動時に確認が出る
4. その背景作業が触る **ask gate** (特定 folder・送信系) — 起動でなく中身の tool call が鳴っている

## <a id="protected-settings-edit"></a>Claude が `.claude/settings*.json` を編集すると毎回 dialog が出る (保護 file)

Claude Code は `.claude/` (= `~/.claude/settings.json` / `<root>/.claude/settings.json` / `settings.local.json` を含む。 例外は `.claude/worktrees`) と `.git` / `.vscode` / `.idea` 等を **protected path** として扱う。 そこへの Edit / Write は **allow rule で事前承認できない** (公式 docs: この安全検査は settings の allow より先に走る = `Edit(.claude/**)` を allow に書いても結果は変わらない)。 mode ごとの挙動 (公式 docs `permission-modes#protected-paths`、 2026-09-11 確認):

| mode | protected path への書込 |
|---|---|
| `default` / `acceptEdits` | 毎回 dialog |
| `auto` | classifier が判定 (dialog は出ない) |
| `dontAsk` | 拒否 |
| `bypassPermissions` | 素通り |

- CLI の dialog には「この session 中は settings の編集を許可」 の選択肢があるが、 **desktop の dialog は「拒否 / 一度だけ許可」 だけ**で、 Edit 1 回ごとに出る (2026-09-11、 desktop で観測)。
- ∴ `default` mode のまま、 この dialog だけを消す設定は無い。 消すには mode を変えるしかない: `auto` は ask rule (送信 gate 等) を残したまま settings 編集を classifier 判定に回せるが、 他の操作も classifier 判定になる (= [`tool-call-robustness.md#classifier-session-block`](tool-call-robustness.md#classifier-session-block) のリスクを負う)。 `bypassPermissions` は ask gate ごと消えるので不可 ([§desktop で特定 tool に確認を課す](#desktop-per-tool-gate))。
- `auto` mode では、 Claude による settings 編集は dialog でなく classifier 判定になる。 **自分の権限を広げる編集 (`defaultMode` の変更 + `additionalDirectories` の追加) は block された** (2026-09-11 observed、 n=1)。 ∴ auto で運用するなら、 権限を広げる設定変更は user が手で行う (Claude が Bash で書き換えるのは block の迂回になるのでやらない)。
- 「毎回聞かれる」 と言われたら、 対処を選ぶ前に `scripts/permission-dialog-audit.py --attribute` で dialog の内訳を測る。 体感の「毎回」 には、 意図して置いた ask gate や、 cwd / additionalDirectories 外の path への dialog が混ざっていることが多い (2026-09-11 実測: 40 日間の Edit / Write dialog 91 件のうち、 settings file 宛ては 4 件)。
- desktop のモード選択は**フォルダごとに記憶**され、 そのフォルダでは `defaultMode` より優先される (公式 docs `permission-modes`、 Plan は例外)。 `defaultMode` を変えたのに効かないフォルダがあれば、 そこのモード選択を疑う。
- 設定変更を頼まれたら、 **変更する file の数だけ dialog が出る**ことを先に伝え、 1 file の変更は 1 回の Edit にまとめる。
- **session 中に Bash (sed / python / jq) で書き換えて dialog を迂回しない**。 保護は「設定変更を人間が 1 回見る」 ための仕組みで、 迂回するとその意味が消える (= 自分の権限を自分で広げる経路になる)。 git に載って人間が review した bootstrap script が、 owner が明示した値を他マシンへ伝播するのは別扱い (= [`multi-machine-state.md#one-shot-settings-propagation`](multi-machine-state.md#one-shot-settings-propagation))。

## <a id="always-allow-persists-literal"></a>「常に許可」 は command をそのまま settings.local.json に保存する — secret を command に書かない (2026-09-11)

Bash の承認 dialog で「Yes, and don't ask again」 (desktop では「常に許可」) を選ぶと、 その command の文字列が allow rule として repo root の `.claude/settings.local.json` に保存される (公式 docs `permissions`)。 token や password を command に直接書いた Bash を常に許可すると、 **secret が平文の allow rule として残る** (実例: 外部 service の API token を含む curl / export の行が 11 行、 数ヶ月残っていた。 file からは消せても、 その command を実行した session の transcript には残る)。

- secret は command に書かず、 file か環境変数から読ませる (例 `curl -H "Authorization: Bearer $(cat ~/.secrets/x)"` = 保存される文字列に値が現れない)。 受け渡しの一般則 = [`secret-handoff.md`](secret-handoff.md)。
- 見つけたら allow の該当行を消す (protected path なので dialog 1 回)。 値は漏れた前提で扱い、 必要なら rotate する ([`secret-handoff.md#rotation-labor-split`](secret-handoff.md#rotation-labor-split))。
- 棚卸しは `settings.local.json` の長い allow 行を見るのが早い (secret は長い英数字列として出る)。

## <a id="long-command-falls-back-to-ask"></a>長すぎる Bash command は自動承認から外れて dialog になる (2026-09-12)

`auto` mode の Bash 自動承認は classifier 判定だが、 **command が長くなると判定から外れて user への確認 dialog にフォールバックする**。 しかも長大 command は pattern 化できないため dialog に「常に許可」 が出ず ([#always-allow-persists-literal](#always-allow-persists-literal) の保存が効かない)、 同じ形を打つたびに毎回止まる。 user 側の体感は「同じ作業で毎回・何度も聞かれる」。

**実測** (desktop app の dialog log × transcript 突合、 同一 session・同一 cwd・同一 settings):

| command 長 (文字) | 結果 |
|---|---|
| 1,917 / 2,104 / 2,111 (heredoc 含む) | 通過 |
| 4,272 / 8,916 (heredoc 含む) | **dialog** |

同 session の Bash 56 回のうち dialog が出たのはこの長大 2 回だけで、 hook 由来ではない (= 当該 command を全 PreToolUse(Bash) hook に流し直して無反応を確認済み)。 ∴ 閾値は 2,100〜4,200 文字のどこか。 **真の境界は測っていない** — 下の backstop の既定 3,000 は安全側に寄せた値なので、 2,100〜3,000 の command は「通るはずなのに書き直させている」 可能性がある (= 過剰な制止。 うるさければ `CLAUDE_LONG_BASH_LIMIT` で上げる)。

**切り分け**: 長さ以外の要因 (hook・cwd・mode) と混ざりやすい。 同 session の Bash 呼び出しを transcript から長さつきで一覧し、 dialog の時刻 ([#desktop-permission-dialog-log](#desktop-permission-dialog-log)) と突合すると、 「長いものだけが鳴っている」 かが 1 目で分かる。 hook 由来との区別は当該 tool_input を hook に流し直すのが確実 (= [#desktop-permission-dialog-log](#desktop-permission-dialog-log) の「mode を疑う前に hook を疑う」)。

**対処 (書く側)**: これは危険だから止まっているのではなく、 **同じ結果をより短く書けば dialog 自体が発生しない**。

1. 単位で分割する (= N 件の追記を数回に割る)
2. 本文を scratchpad の file に書いてから、 短い command で流す (`cat <scratchpad>/chunk >> <target>`)
3. file 編集が目的なら Edit / Write tool を使う (= path 単位の判定になり command 長は関係しない)

**機械 backstop**: [`hooks/long-bash-command-guard.sh`](../hooks/long-bash-command-guard.sh) — PreToolUse(Bash) で閾値 (既定 3,000 文字、 `CLAUDE_LONG_BASH_LIMIT` で上書き / `0` で無効) を超えた command を **exit 2 で block** し、 上の 3 つを stderr で案内する。 block は Claude にしか見えないので、 user には dialog も待ちも発生しない (= 「聞かれる」 が「Claude が短く書き直す」 に置き換わる)。 長さは byte でなく codepoint で測る (= 日本語の command で閾値が 1/3 になるのを避ける)。

⚠️ **guard の自己参照**: この種の guard を書く / 直すときは、 guard 自身の source・test・規約 doc が検出対象の pattern を literal で持つため、 **guard を直そうとするたびに guard に止められる**。 実例 (2026-09-12): URL guard の test fixture に意図的な違反 URL を 1 行足す Edit が、 その URL guard 自身に ask された。 → guard 側に自己参照の除外を持たせる。 ⚠️ 除外は **その guard を説明・検証している file だけ**に絞る (= 自分の source・自分の test・自分の規約 doc)。 `*/hooks/*.sh` のように dir 単位へ広げると、 将来 同じ pattern を出力する別 hook の検査が **silent に効かなくなる** (= 除外は穴で、 穴は検出されない)。 「別 hook の source は検査対象のまま」 を test に固定しておく。 test fixture の誤発火一般は [`hook-authoring.md`](hook-authoring.md)。

## 個人ごとの適用

「どのフォルダを additionalDirectories に登録するか」は各ユーザー / 各マシンの選好なので、本 public 規約には書かず、各自の personal config (machine-local の `~/.claude/settings.json`) に置く。`~/.claude/settings.json` は git 同期されないため、複数マシンで揃えたい場合は各マシンで設定するか、各自の setup 機構に組み込む。

## 関連

- **Excel / Word / PDF ファイルの実作業** (openpyxl での様式 fill / docx 編集 / PDF 化 / 様式改変防止 / 検証スクリプト) は [`office-automation.md`](office-automation.md) が正本。 cwd 外の office file を弄るときは本ドキュメント (permission) と office-automation.md (手順) の両方を参照する。
