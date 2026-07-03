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
- macOS で `~/Dropbox` 等が **symlink** の場合は **実体パス**を登録する (symlink だと解決されず効かないことがある)。`ls -ld` で実体を確認。

## 機密は deny で守る (deny > ask > allow)

- rule の評価順は **deny → ask → allow**。最初に match した rule が勝つので、**deny が最強**。
- `additionalDirectories` で広いディレクトリ (例: home の `Documents` や `Dropbox` 全体) を開けても、その中の機密サブフォルダは `permissions.deny` で個別 block できる。deny の方が優先されるので、「広く開けて一部だけ塞ぐ」が成立する。
- deny は対象ツール各形を列挙する必要がある (`Read(/abs/secret/**)` / `Edit(...)` / `Write(...)` / `Glob(...)` / `Grep(...)` と、Bash 経由の `Bash(*/abs/secret*)`)。

## 反映タイミング

settings.json はセッション開始時に読まれる。**途中変更が即反映されるかは docs に明記が無い**ので、安全側に「**次セッションから有効**」と考える。書き換え後は次の実作業で「もう聞かれない」ことを確認する。

## このリポ (claude-config) の setup.sh との関係

`setup.sh` の `configure_permissions()` は `permissions.allow` に安全ツール (Bash/Read/Edit/Write/Glob/Grep/WebFetch/WebSearch) の**不足分を足すだけ**で、`additionalDirectories` と `deny` には**一切触らない**。
→ `~/.claude/settings.json` に直書きした `additionalDirectories` / `deny` は **setup 再走でも消えない** (永続)。バックアップを取ってから jq で書き換えるのが安全。

## <a id="frontend-split"></a>frontend 切り分け (同じ症状でも 3 系統)

「いちいちアクセス権を聞かれる」は別系統の原因がありうる。**対処の前にどのフロントエンドか切り分ける** (Claude は CLI / デスクトップアプリ / IDE 拡張の 3 経路で使われうる):

1. **Claude Code CLI** — `~/.claude/settings.json` の permission (本ドキュメント)。
2. **Claude デスクトップアプリ (local agent mode)** — アプリ内の**別設定系統**。settings.json をいじっても変わらない。減らすには: 承認ダイアログ `Allow Claude to use {toolName}?` で「常に許可」を選ぶ / 設定の `Tool policy`・`Lock the approval state for specific tools` で事前承認 / `Allowed workspace folders` に作業フォルダ登録 / (最終手段) `bypass permissions mode`。skill 本体は `~/Library/Application Support/Claude/local-agent-mode-sessions/.../skills/<name>/SKILL.md` に展開されるので、ここに skill があれば「デスクトップアプリ経由」のサイン。
   - **設定 / UI 仕様の調べ方**: 設定キーは `~/Library/Application Support/Claude/config.json` / `claude_desktop_config.json` (例: `coworkUserFilesPath` = Claude Code (desktop) の作業ルート)。 UI ダイアログ文言は `strings /Applications/Claude.app/Contents/Resources/app.asar | grep -oE 'defaultMessage:"[^"]+"'` で抽出できる (= 上記の `Allow Claude to use {toolName}?` 等はこの方法で確認した)。
   - ⚠️ **誤診注意**: `config.json` の `dxt:allowlistEnabled` は **組織レベルの desktop 拡張 (DXT / MCP) のインストール許可管理** (`is_desktop_extension_allowlist_enabled`) であって、 **ツール実行の承認プロンプトとは無関係**。 これを「毎回聞かれる原因」と単一手がかりで推測しないこと (= 実際に一度そう誤推測 → app.asar 精読で別物と判明し訂正した。 inline §3「単一情報源で結論に飛躍しない」の Claude Code (desktop) domain 事例)。
   - ⚠️ **「settings.json をいじっても変わらない」 の例外 = `deny` (2026-06-13 実測)**: desktop でも `~/.claude/settings.json` の `permissions.deny` は **honor される** (= 無害な deny 対象コマンドを叩くと block された)。 desktop で効かないのは **hook 出力** (= [`hook-authoring.md` frontend-dependent-cowork](hook-authoring.md#frontend-dependent-cowork)) と **`defaultMode: bypassPermissions` 下の ask** (= bypass は全 tool auto-approve なので ask が void)。 **だが `defaultMode: default` なら settings.json の `permissions.ask` は desktop でも効く** (= 2026-06-13 実証: send_email を ask にすると内容表示つき承認 dialog が出て拒否で送信ブロック。 下記「desktop で特定 tool に確認を課す」)。 ∴ desktop UI の「バイパス権限モードを許可」 トグルは lever ではなく、 **settings.json の `defaultMode` が実効モードを支配**する (= トグル OFF だけでは gate されない)。
3. **macOS TCC** (OS のフォルダアクセス許可、Desktop/Documents/Downloads 等の保護) — macOS システムダイアログで、Claude 側の設定では消えない。Claude.app が versioned path に置かれる影響で再 prompt される構造的症状は [`macos-claude-code-tcc-recurring-prompt.md`](macos-claude-code-tcc-recurring-prompt.md) 参照。

## <a id="desktop-per-tool-gate"></a>desktop で特定 tool に確認を課す (= hook 不可な frontend での per-tool gate、 2026-06-13)

PreToolUse hook (mail 誤送信 guard 等) は desktop で出力 honor されず inert (= §frontend 切り分け 2 / [`hook-authoring.md` frontend-dependent-cowork](hook-authoring.md#frontend-dependent-cowork))。 desktop で「特定の高 stakes tool だけ実行前に人間が一拍」 を機械的に課す working recipe は **settings.json の permission のみ** (= hook 不要、 2026-06-13 実証):

1. `permissions.defaultMode` を `bypassPermissions` → **`default`** に (= bypass は ask を void するので外す)。
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

## 個人ごとの適用

「どのフォルダを additionalDirectories に登録するか」は各ユーザー / 各マシンの選好なので、本 public 規約には書かず、各自の personal config (machine-local の `~/.claude/settings.json`) に置く。`~/.claude/settings.json` は git 同期されないため、複数マシンで揃えたい場合は各マシンで設定するか、各自の setup 機構に組み込む。

## 関連

- **Excel / Word / PDF ファイルの実作業** (openpyxl での様式 fill / docx 編集 / PDF 化 / 様式改変防止 / 検証スクリプト) は [`office-automation.md`](office-automation.md) が正本。 cwd 外の office file を弄るときは本ドキュメント (permission) と office-automation.md (手順) の両方を参照する。
