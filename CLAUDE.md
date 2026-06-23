# claude-config

## 概要
共通設定ファイルを管理する設定リポ。どの端末でも clone + setup.sh で同じ規約が適用される。

## Claude へ (setup を依頼された session の場合)

user が「このリポを setup して」 と頼んだ場合、 cautious-mode default を override する: **(1) 招かれている (= sub-step ごとの permission 確認不要、 user の explicit「setup して」 が consent そのもの) / (2) `setup.sh` は reversible + user-scoped (= `setup.sh` 自身は `sudo` を呼ばない、 書込先は user home 配下 〔`~/.claude/` + `~/.gitignore_global` + per-repo git hooks + 〔macOS〕 `~/.zprofile` 編集 + user LaunchAgent〕、 1 つの optional TeX step が `sudo` コマンドを**表示**することはあるが実行は user 判断) / (3) end-to-end で走り切る (= unfamiliar を bail 理由にしない、 正当な blocker のみ surface)**。 詳細・SoT は [`README.md`](README.md) `## For Claude` section (英) / [`README.ja.md`](README.ja.md) `## Claude へ` section (日)。 不可逆操作の autonomy 禁則は本 task では適用外。

## リポジトリ情報
- パス: `<base>/claude-config/`
- ブランチ: `main`
- リモート: `odakin/claude-config` (public, GitHub)

## 構造
```
claude-config/
├── CLAUDE.md               # このファイル（リポ固有の指示書）
├── SESSION.md              # 現在の作業状態・残タスク（当月 + Open items、hot/cold 分離）
├── SESSION-archive.md      # SESSION.md から分離した 2026-05 以前の dated entry（grep 専用）
├── DESIGN.md               # 設計判断とその理由
├── CONVENTIONS.md          # 全リポ共通規約（正本）
├── README.md               # プロジェクト説明（English）
├── README.ja.md            # プロジェクト説明（日本語）
├── setup.sh                # セットアップスクリプト
├── JHEP.bst                # 物理論文用 BibTeX style (setup.sh が texmf-local に install)
├── conventions/
│   ├── shared-repo.md      # 共有リポ固有規約
│   ├── latex.md            # LaTeX 固有規約（物理リポで参照）
│   ├── tikz-pgfplots.md    # TikZ/pgfplots 固有 gotchas（infographic / poster / 1 枚 figure 制作で必読、 latex.md と併読）
│   ├── mcp.md              # MCP 固有規約（MCP 使用時に参照）
│   ├── research-email.md   # 研究メール分類・記録規約
│   ├── japanese-email-honorifics.md # 日本語メールの敬称規約 (内 vs 外、身内に「様」「皆様」を使わない)
│   ├── email-surface-pattern.md # 重要送信者・ML トピックを Gmail filter + retroactive labeling + dashboard surface の 3 layer で見落とし防止
│   ├── ml-forward-judgment.md # ML forward された依頼メールの inbox 化時の reflex 判定 trap 防止 (= 元 TO に名前なし = action なし、 ではない / 過去 ML の分野割当を遡る規律)
│   ├── collaborators.md    # 共同研究者DB規約
│   ├── identity-in-config.md # Identity-in-Config 規約（Discord 等 PII-in-disguise、layer 2 + env var bridge）
│   ├── scheduled-tasks.md  # Scheduled Tasks 規約（SKILL.md 二重構造・同期ルール）
│   ├── claude-ai-routines.md # claude.ai routines (= RemoteTrigger API、 旧「scheduled remote agents」) の知識集 — cloud 側に CCR session を spawn する cron / one-time trigger、 local 機構の scheduled-tasks.md との区別、 操作は RemoteTrigger tool / /schedule skill 経由
│   ├── substack.md         # Substack 規約（入稿: Markdown→リッチテキスト変換手順 / 取得: notes・コメントの Gmail MCP + WebFetch 経由回収）
│   ├── zenn.md             # Zenn.dev 記事執筆規約（platform 仕様: タイトル 70 字 / HTML サニタイズ / `:::message`系 / 文字数見積もり、 GFM bold×全角句読点 等の執筆落とし穴。 substack.md の対、 zenn-cli 運用は各リポ CLAUDE.md 側）
│   ├── shell-env.md        # シェル環境（PATH 二層防御: .zprofile 修正 + スナップショットパッチ、macOS deny ルール）
│   ├── dropbox-refs.md     # 共同 PDF を Dropbox に置いてリポから symlink で参照する規約 (§10 で OneDrive / Google Drive 等の他クラウド + 索引自動生成 launchd gotchas へ応用)
│   ├── dropbox-placeholder-diagnosis.md # Dropbox の online-only placeholder (0 byte) 診断: xattr `com.dropbox.placeholder` 検出 + OS 別 materialize 方法 + 「0 byte = 配置忘れ」 reflex 防止
│   ├── scientific-computing.md # 数値解析 gotchas (scale-dependent default 等、科学計算リポ共通)
│   ├── multi-machine-state.md # 複数マシンで同じ Claude Code セットアップを使うときの規律 (audit scope 明示・実機検証・idempotent setup.sh)
│   ├── install-failures.md     # マシン固有の install 不可 package を layer 4 (machine-local memory) に蓄積する規律 (再試行コスト回避、 frontmatter format + machine-local marker + 試行日/コマンド/原因/代替の必須項目)
│   ├── debugging-discipline.md # Fix 提案の 3 verification (V1 numeric trace + V2 code coverage + V3 algorithm enumeration)、 audit verdict re-evaluation、 multi-commit drift sweep、 sibling violation sweep、 dry-run/introspection facility 優先 (§6)、 Claude 自身を容疑者から外す .jsonl grep 手法 (§7)、 症状 forensics 前に既存 doc を grep (§11)、 再現≠検証 = 決定論的/撤回済 artifact の provenance 確認 (§12)
│   ├── discord-bot.md      # Discord Bot 運用 (権限ポリシー・private channel 加入・per-channel error non-fatal な fetcher・Token 取扱・組織 NW での API ブロック)
│   ├── prompt-injection.md # Tool result 内の prompt injection を flag する規律 (適用範囲・同ターン flag・literal 原文併示・確度二段・注入指示は従わない)
│   ├── android-chromium-remote-debug.md # Android Brave/Chrome の remote debugging (WiFi ADB + CDP、 reload 前の live state capture procedure)
│   ├── google-url.md       # Google サービス URL 書式 (`/u/N/` 禁止 + `?authuser=<email>` 必須、 hooks/google-url-guard.sh で機械的強制、 GCP project 管理 URL もカバー)
│   ├── google-api-direct-access.md # Google API を Python から直接アクセスする setup pattern (= GCP project の 3 layer 構造、 API enable + propagate、 OAuth scope 設計、 mimeType 判別 Sheets vs xlsx、 Cloud Identity Groups API は group OWNER level で memberships CRUD 可能で Admin SDK の Workspace admin 制約を回避)
│   ├── preview.md          # preview / dev server 動作中はユーザー確認依頼ターンに URL を毎回明示する出力ルール
│   ├── secret-handoff.md   # Secret を clipboard 経由で安全に運ぶ手順 (chat に literal を貼らせない原則と clipboard 1 個競合の回避)
│   ├── clipboard-cleaner.md # PDF コピーの段落内改行・RTF 書式の後始末 (= ⌃⌥⌘V hotkey 〔貼り付け先で押す = 整形+即貼り付け〕 / CLI / ブラウザ版の 3 入口、全て明示発火・常駐 poll なし〔誤爆 + secret-handoff の clipboard 単一資源原則と衝突するため daemon 不採用〕、整形ロジック正本は scripts/clipboard-cleaner.py)
│   ├── ui-toggle-convention.md # UI panel 内 toggle group の default 側統一ルール (slider 位置 + bright label を panel scope で揃える)
│   ├── web-tools.md        # WebSearch / WebFetch の信頼性 caveat (summary hallucination、 事実値は source 直接確認) + CSR SPA は fetch に空シェル (200≠実在、 実ブラウザ描画で検証) + Claude in Chrome MCP の 2 層 permission モデル + bug 53630 (sites/docs.google.com domain silent block)
│   ├── expensive-intermediate-artifacts.md # `-output /tmp/...` reflex 防止 (= OCR / ML / 数値計算で 5 分以上要する artifact をリポ内永続化、 hooks/expensive-tmp-guard.sh で機械的検出)
│   ├── data-pipeline-automation.md # データ単一ソース化・forward-only schema migration・judgment-required placeholder pattern・script input validation・自動化機構の validity 検証 (= reproduce by script) を bundle
│   ├── github-security-automation.md # 全 repo 横断の Dependabot/CodeQL/Semgrep/auto-merge baseline + Free plan silent rejection + Dependabot PR tier-based merge discipline + ESM migration backwards-compatible normalizer + `gh` CLI gotcha (= users/X/repos public-only / mergeStateStatus UNKNOWN retry) + bash set -e + heredoc + $() interaction fix + monorepo dependabot.yml directories+groups + cascading PR convergence loop
│   ├── macos-claude-app-pty-leak.md # macOS で Claude.app が `kern.tty.ptmx_max=511` を独占 → Terminal 等で `forkpty: Device not configured` 発生時の段階的 sysctl bump workaround (hard ceiling ~960、 root 対処は Claude.app restart、 Anthropic bug report 候補)
│   ├── macos-claude-code-tcc-recurring-prompt.md # Claude Code の app bundle が `~/Library/Application Support/Claude/claude-code/<version>/claude.app` という versioned path に置かれているため、 App Management TCC 権限が auto-update 毎に invalidate されて dialog が再 prompt される構造的症状 (= sibling pty-leak と同じく Anthropic 側 fix 待ち候補、 stable launcher path 化が root 対策)
│   ├── macos-ime-ascii-layout.md # macOS で「直接入力=非 US 配列、IME 中=US 配列」を共存させる gotchas (= IME のキー変換は MRU ASCII-capable layout 従属 / TISSetInputMethodKeyboardLayoutOverride は外部から効かない / 無効化 layout は MRU 候補外 / CGEvent 書き換え 2 経路は IME バイパス・mozc の Option=ALT 扱いで不成立 / 成立解 = IME 切替検知 + US layout 動的有効化+瞬間選択〔権限不要〕 / CLI バイナリの tap は .app bundle 化で TCC 安定)
│   ├── remote-control-server.md # Claude Code Remote Control サーバーモードの launchd 常駐 (= スマホ / claude.ai/code から自マシンに新規セッションを生やす待ち受け。 要件 = claude.ai OAuth 〔managed key 不可〕 + 初回同意 y、 ⚠️ PTY 経由は stdin EOF cycling、 モバイル UI のリポ選択は same-dir で cwd 不変、 cloud session との見分け = 緑ドット computer icon。 install SoT は scripts/install-remote-control-server.sh)
│   ├── claude-code-permissions.md # Claude Code CLI の permission プロンプト削減 (= cwd 外 file 〔`~/Downloads` 等〕の Read/Edit/Write が毎回確認される症状を `additionalDirectories` で cwd 同様に無確認化、 bare tool allow は cwd 外を素通ししない observed〔docs 解釈と食い違い〕、 deny > ask > allow で機密は `deny` 優先、 setup.sh `configure_permissions` は `allow` のみ触る = additionalDirectories/deny は直書き永続、 settings 反映は次セッション、 frontend 3 系統切り分け〔CLI settings.json / デスクトップ Cowork Tool policy / macOS TCC〕)
│   ├── google-forms-automation.md # Google Forms の `FB_PUBLIC_LOAD_DATA_` HTML scrape で entry id 抽出 (= Forms API は entry id を返さない)、 prefill URL は単 section form のみ動作 (多 section で section navigation 後に prefill 失効)、 完全自動化は Selenium/Playwright + cookie 経由
│   ├── office-automation.md # 研究費/教務/学術様式の Excel xlsx を openpyxl で fill + 生成物 PDF 化 / TTS の落とし穴集 (= form 構造 dump 必須・label vs input 改変防止・rich text underline・docx XML 宣言由来の Word 破損 §2-5b・**Word docx→PDF の stale in-memory cache + cold-start 失敗の対処 §2-4b**・**記入要領削除は構造保持+content-control も走査+双方向検証 §2-5c (青字ガイダンスは effective-color〔run→rStyle→pStyle の style 継承〕で strip + PDF span 色=非黒0 で検証)**・**Pages は横並び表を重ねて出す artifact = docx 不具合と誤認するな (Word render で確認・creator metadata で判別)**・PDF visual confirmation 義務・**画像読みすぎで image budget 枯渇時の text-first 検証 §6-5**・印影/署名の電子可否・多 sheet form sweep)
│   ├── office-automation-principles.md # ↑の原則編 (= 考え方)。 様式=「見た目が契約」/ file=地層 / 処理=lossy 解釈器の連鎖 の枠組み、 道具選択の梯子 (成果物は何か × 雛形にどの層があるか)、 検証 3 層モデル (機械/視覚/実機 — 相互代替不可 + 異常は print-blocker)、 文字列照合 NFKC 必須、 座標は label anchor から導出、 人間系原則 (既知情報 prefill / print-last / 記入分担 4 区分表 / 受理側で閉じる)、 新しい罠の体系への拡張手順。 **新しい様式・slug の無い罠ではまずこちら**
│   ├── erad-submission.md  # e-Rad 経由の研究費応募 (JST・科研費・財団等) のフォーム固有制限・書式ルール・つまずきどころ (= 制度横断で効く e-Rad 挙動のみ、 制度個別値 〔費目・字数上限・締切〕 は各公募要領 + 応募管理リポが正)
│   ├── sensitive-data-pass-through.md # 受信した URL / file を別 recipient に forward する前に「依頼の scope」 と「届いた data の scope」 を必ず照合する規律 (= over-share / permission mismatch / scope downscope 機会損失の 3 失敗モード回避)
│   ├── wolfram-scripting.md # wolframscript の Print[NumberForm] literal stringification + ToString wrap helper、 SetDirectory[DirectoryName[$InputFileName]] の空文字 fallback、 PDF Plaintext import を secondary fallback として活用 (= scientific-computing.md の数値 silent failure とは別 scope の Wolfram tool semantics gotcha 集)
│   ├── multi-session-coordination.md # 同 user の並列 Claude session が同 file path を race する防御 (= session 開始 git fetch + log + plan read、 Write 前 ls/find、 Edit 前 Read 強制、 plan checkbox [x] は実装済のみ semantics、 prev session の commit を「他人 commit」 として cold-read)
│   ├── time-context.md     # multi-turn / multi-day session で「今日・明日・今夜」等の時刻 deictic を旧 frame (= 前ターンの仮想 today) で解釈する reflex failure 防止 — 必ず currentDate を起算点に再翻訳
│   ├── hook-authoring.md   # Claude Code hooks 作成 + 配信規律 (= bash 3.2 の $(...) + heredoc body quote escape parser bug + hook 配信正常性 3 軸 audit 〔symlink + settings.json + try-fire〕 + PreToolUse warn mode 出力 spec uncertainty + partial install state + §9 hook 挙動の build 依存 〔新規 hook は同 session 非発火=session 開始時 snapshot、 docs の hot-reload 記述は build 依存 / permissionDecisionReason silent-skip / updatedInput〕)
│   ├── personal-skills.md  # personal skill (= ~/.claude/skills/、 全 session 常時可視の auto-discover) を規律の発火面として使う規約 — 機構 fact 〔symlink 可・session 開始時 discovery〕 + description の書き方 + 多 machine 配線 〔explicit allowlist registry〕 + 検証作法 〔trigger test → discovery test の汚染回避順序、 headless claude -p の制約〕
│   ├── tool-call-malformed-paste.md # 別 session 貼り付け用 malformed バグ概要 (= 正本 tool-call-robustness.md の短縮版、 現象 + 真因 + 報告先 issue 一覧 + 緩和策 6 + poisoned 時の対処を 1 file に凝縮、 別 session が初対面で即理解できる self-contained memo)
│   ├── tool-call-robustness.md # Claude の tool call が「malformed and could not be parsed」 で壊れるのを防ぐ (= 真因は Anthropic backend の Opus 4.8 1M-context model serialization bug 〔canonical evidence = #64774 = 6/2 開設・~1万ターン統計・model 別失敗率 Opus 4.8 のみ ~1.5% / Opus 4.7・4.6・Sonnet 4.6・Haiku 4.5 すべて 0、 CLI 横断 = model 起因、 76% が text→tool_use 切り替え瞬間、 OPEN 未修正・area:model、 occurrence 報告は #64774 へコメント。 ⚠️ 旧版が canonical hub と書いた #62123 は別 variant = Opus 4.7 + VS Code 系で「4.7 = 0%」 と矛盾するため別扱い、 衛星 #64684/#64955/#64235 は duplicate〕 で書き方の問題ではない、 特殊文字密集/並列 tool call/非 ASCII/装飾過多は発生確率を上げる副次トリガー、 副次緩和 = 1 ターン 1 tool call / 複雑ロジックは Write でファイル化 / tool call ターンは本文プレーン / malformed 連発は新 session / **model 切替が最優先**・本命 Opus 4.7 1M 〔`/model claude-opus-4-7[1m]` = 賢さ最大 × バグ 0%〕、 Sonnet 4.6 は次善 / poisoned したら work tool を subagent 委譲 + 残作業 spec ファイル化して別 session へ平文 handoff、 root は backend fix 待ち、 2026-06-05 RCA + 2026-06-16 canonical 訂正 + rotted-session 回収手順 〔transcript salvage / git log / stale-handoff-plan vs working-tree の罠〕、 hook-authoring §1 の bash 3.2 parser bug とは別 layer)
│   ├── overleaf-integration.md # Overleaf↔GitHub 連携 (= canonical は Overleaf web UI の GitHub linking、 sync script 契約 〔--status が ahead/behind を出す + PROJECT_ID hardcode = ID の SoT〕、 新規連携 checklist + ID 回収 runbook、 drift 検出は scripts/check-overleaf-drift.py)
│   ├── paper-audit.md      # multi-paper merger 等の forward ref / 重複 subsection / structure issue を Phase1 機械検出 + Phase2 section-by-section AI 精読 + findings.yaml で体系 audit
│   ├── rebuttal-letter.md  # referee report への point-by-point 返信 (= author response) 作成 6 reflex (= 回答は本文 grep 照合・起源でない文献は see e.g.・referee 誤記は静かに正す・自己否定語回避・全 comment フル引用・旧式番号は submission 版基準)、 paper-audit.md と相補
│   ├── physics-notes.md    # 物理・数理ノートの 3 規約 (= 添字は常に全部顕に / 規約表セルは「宣言の引用」か「推定の明記」/ ノートは snapshot で歴史は md + git 側) — odakin 個人流儀を全プロジェクト横断で一貫させるための公開層配置
│   ├── giving-talks.md     # 講演のしかた (= Robert Geroch "Suggestions For Giving Talks" arXiv:gr-qc/9703019 の own-words ダイジェスト、 主題選択 / 3-4 メッセージ構成 / 導入は全体の 1-5 / 視覚資料は図>言葉>式 / 1h で非自明な式 5 本・スライド 10 枚 / 質問は完全に正直に 等。 セミナー・JC・卒論発表の準備時に読む、 英語本体)
│   ├── giving-talks.ja.md  # ↑ giving-talks.md の日本語版
│   ├── beamer-slides.md    # Beamer/metropolis 研究スライドの技術規約 (= install 不要フォント〔Fira/Harano Aji〕・配色・[shrink] の横縮小罠・standout の \\ 落とし穴・セクション扉を全 TOC+現在強調・PDF ページラベル重複の後処理修正〔page 番号振り直し〕・再現ビルド build.sh・視覚 QA ループ・matplotlib 図生成〔日本語/CIE 厳密スペクトル〕・論文図の領域レンダ抽出・.key 不可。giving-talks.md〔中身/作法〕と相補)
│   ├── claude-app-cwd-pin.md # Claude.app (Cowork desktop) の新セッション folder picker 起点を `<base>` に固定する launchd エージェント (= NSNavLastRootDirectory を 1 秒間隔で書き戻し、 picker の drift 防止。 setup.sh Step 2b2 が macOS で default-ON install〔ただし desktop アプリ未使用の CLI 専用 Mac は skip〕、 drift 時のみ書込〔read-first〕、 opt-out marker `~/.claude/pin-claude-cwd.off` / `CLAUDE_PIN_CWD=0` で稼働中 job も停止、 launchd ThrottleInterval=10s 罠の対処込み)
│   └── chalkboard-close-up-merge.md # 板書写真 PDF で「広域 + close-up annotation」 2 枚を 1 page に統合する手順 (= Keynote 手作業経路 〔黒板 theme + 透過 chalk PNG overlay〕 を推奨、 PIL inline composite は anchor 明確時のみ。 free-form 配置は user が掴んでドラッグ、 AppleScript で .key auto 生成 + slide PNG export までを台本化、 chalk-only RGBA mask threshold 100-140 + Gaussian blur 1.5 px の標準値、 lectures 板書 reflex の延長)
├── hooks/
│   ├── memory-guard.sh             # メモリ書き込みガード — Edit/Write 用（§8 feedback deny + escape hatch: machine-local marker）
│   ├── memory-guard-bash.sh        # メモリ書き込みガード — Bash 用（§8 feedback deny + escape hatch）
│   ├── public-leak-guard.sh        # 公開リポ leak 防止 — PreToolUse(Edit|Write|MultiEdit) Tier A 構造制約 regex
│   ├── google-url-guard.sh         # Google URL 安定性ガード — PreToolUse(Edit|Write|MultiEdit|Bash): /u/N/ 禁止 + `?authuser=<email>` 必須
│   ├── expensive-tmp-guard.sh      # PreToolUse(Bash): Audiveris / oemer / ML training 系の -output /tmp/ パターンを検出して `permissionDecision: ask`
│   ├── git-state-nudge.sh          # PostToolUse(Bash): 直近 commit の未 push 検出 + first-sighting で fetch+stale 検出
│   ├── pdf-read-fallback-nudge.sh  # PostToolUse(Read): Read tool が .pdf を `pdftoppm is not installed` で fail した時に PyMuPDF 1-liner を system reminder で injection (= 2026-05-18 RCA、 規律 wording に依存しない機械的 enforcement layer)
│   └── fix-snapshot-path-patch.sh   # PATH スナップショット自動パッチ（REQUIRED_PATHS 方式、launchd WatchPaths から呼ばれる）
├── hammerspoon/
│   └── init.lua                # Hammerspoon 設定（Claude Cmd+Q 誤終了防止 + ⌃⌥⌘V クリップボード整形+貼り付け hotkey〔conventions/clipboard-cleaner.md〕+ 末尾で ~/.hammerspoon/local.lua を読む個人層拡張 hook〔hooks の layer-3 chain と同じ発想、無ければ no-op〕）
├── scripts/
│   ├── pin-claude-cwd.sh               # Claude.app folder picker 起点固定 (= NSNavLastRootDirectory を `$1` に固定、 read-first で drift 時のみ write、 setup.sh Step 2b2 の launchd から 1 秒間隔で呼ばれる、 macOS 限定、 conventions/claude-app-cwd-pin.md)
│   ├── fix-bib-unicode.py              # Unicode→LaTeX 変換スクリプト
│   ├── pre-commit-bib                  # Git pre-commit hook（上記を呼ぶ）
│   ├── public-precommit-runner.sh      # 公開リポ pre-commit gate（Tier A + sensitive-terms.txt ephemeral）
│   ├── install-public-precommit.sh     # 各 public repo に pre-commit stub を冪等配置
│   ├── commit-msg-leak-guard-runner.sh # 公開リポ commit-msg hook（BLOCK mode、 2026-05-26 追加。 shared matcher library を source。 claude-code 2.1.x harness invoke bug の修復 option B）
│   ├── commit-msg-leak-guard-runner.test.sh # 上記 runner の self-test（15 case、 BLOCK / PASS / merge skip 等）
│   ├── install-public-commit-msg.sh    # 各 public repo に commit-msg stub を冪等配置（marker check + core.hooksPath cascade）
│   ├── audit-public-repos.sh           # 全 public repo の leak 定期監査（週次 scheduled-task 対象）
│   ├── diff-form-xlsx.py               # 様式 xlsx の label 上書き (= 様式改変) を雛形 diff で検出（office-automation.md#diff-form-xlsx-detection）
│   ├── scan-form-instructions.py       # 様式 xlsx の label 内 embedded instruction を category 別に抽出（office-automation.md#embedded-instruction-in-label）
│   ├── xlsx-to-pdf.sh                   # spreadsheet → PDF 変換（LibreOffice soffice 優先 → macOS Excel osascript fallback、office-automation.md#xlsx-to-pdf-script）
│   ├── pdf_form_fill.py                 # 雛形 PDF への直接印字エンジン（library。anchor 印字 / NFKC 照合 / #+ redact / font subset / 内蔵検証 / 600dpi ラスタ化、office-automation.md#pdf-prefill-direct の汎用実装。単票向け — 派生 sheet 数式導出付き workbook は excel-osascript 経路）
│   ├── docx-to-pdf.sh                   # Word docx/doc → PDF 変換（macOS 既定 Pages → --word で Word 忠実版 → 非 macOS LibreOffice、office-automation.md#docx-to-pdf-pages）
│   ├── docx_decl_patch.py              # python-docx の Document.save() を auto-patch し XML 宣言を Word 形式(double-quote+CRLF)で書く（厳格 Word の「破損」回避、 save 時 source 修正・lazy import hook、 office-automation.md#docx-checkbox-content-control）
│   ├── install-docx-decl-patch.sh      # 上記 patch を user site-packages に `.pth`+symlink で install（setup.sh Step 9、 全 python3 起動で auto-load、 idempotent）
│   ├── normalize-docx-decl.py          # 既存 docx の XML 宣言を Word 形式へ後追い正規化する CLI（docx_decl_patch の path-based 版、 office-automation.md#docx-checkbox-content-control）
│   ├── check-docx-integrity.py         # docx の Word「破損」判定源を Word 不要・決定論で検出（single-quote 宣言 / checkbox 状態↔グリフ / bookmark / table grid / dangling r:id 等、 office-automation.md#docx-checkbox-content-control）
│   ├── check-xlsx-integrity.py         # xlsx の Excel「破損」判定源を Excel 不要・決定論で検出（XML well-formed〔unbound prefix〕/ rels 両方向参照整合 / rId 重複 / Content_Types coverage。 zip 直編集 xlsx の納品前 gate、 office-automation.md#openpyxl-destroys-drawings）
│   ├── dropbox-root.sh                 # Dropbox install root を OS 横断で resolve（dropbox-refs 規約用）
│   ├── setup-dropbox-refs.sh           # personal layer の dropbox-collabs.yaml を読んで symlink を生成
│   ├── pty-leak-watch.sh               # macOS Claude.app pty leak watchdog（LaunchAgent、枯渇前に macOS 通知、conventions/macos-claude-app-pty-leak.md）
│   ├── install-pty-leak-mitigation.sh  # ↑ watchdog + persistent bump LaunchDaemon を現ユーザに 1 コマンド install（--persist / --replace-agent / --replace-daemon、idempotent、macOS 限定）
│   ├── install-remote-control-server.sh # Remote Control サーバーモードを launchd 常駐化（--dir / --replace-agent / --status / --uninstall、KeepAlive 60s 自動復帰、preflight で auth/同意の欠落を案内、idempotent、macOS 限定、conventions/remote-control-server.md）
│   ├── check-overleaf-drift.py         # Overleaf 正本 repo の drift / 整備漏れ検出（各 repo の scripts/overleaf-sync.sh --status を並列実行、 ID 未設定=CRITICAL / behind>0=WARN / DEPRECATED=silent / ahead-expected marker で恒常 ahead INFO 抑制、 finding 0 件 silent、 --selftest 内蔵。 個人層 dashboard 末尾から呼ぶ、 conventions/overleaf-integration.md §Sync script 契約）
│   ├── install-overleaf-sync.sh        # Overleaf 連携 repo に sync script を 1 コマンド設置（template 展開 + URL から ID 抽出・焼き込み + --merge-opts / --ahead-expected + token があれば --status smoke、 冪等・別 ID は --force、 conventions/overleaf-integration.md §新規連携 checklist）
│   ├── clipboard-cleaner.py            # クリップボード一発整形 CLI（PDF コピーの段落内改行除去 + pbcopy 書き戻しで RTF 書式除去、明示発火のみ・常駐なし、--selftest 内蔵、hammerspoon ⌃⌥⌘V から呼ばれる、conventions/clipboard-cleaner.md）
│   ├── pdf-cleaner.html                # ↑のブラウザ版 fallback（非 macOS / pbcopy なし環境用、整形ロジックの正本は clipboard-cleaner.py で両実装を同期）
│   └── lib/                            # sourceable helper (個人層検出の共通化)
│       ├── find-personal-layer.sh      # `.claude-personal-layer` marker 検出 (setup.sh Step 5a と sync、 foreign user は空を返す)
│       └── commit-msg-leak-matcher.sh  # commit message leak matcher (= sensitive-terms.txt + repos.md private list - 6 allowlist の (a)(b)(c) check)、 claude-code hook + git-side runner の両方が source する DRY 実装
├── templates/                          # 個人層 / 共有プロジェクトの bootstrap skeleton 一式
│   ├── root-CLAUDE.md.default          # 個人層なしのデフォルト ~/Claude/CLAUDE.md (setup.sh が配置)
│   ├── overleaf-sync.sh.template       # Overleaf 連携 repo 用 sync script template（PROJECT_ID hardcode = ID の SoT、 --status/--merge、 conventions/overleaf-integration.md §Sync script 契約）
│   ├── personal-layer/                 # 個人層 (layer 3) bootstrap skeleton
│   │   ├── README.md
│   │   ├── CLAUDE.md.template
│   │   ├── repos.md.template
│   │   ├── user-profile.md.template
│   │   ├── shared-project-keys.md.template
│   │   └── dropbox-collabs.yaml.template
│   └── shared-project/                 # 共有プロジェクト (layer 2) bootstrap skeleton
│       ├── README.md
│       ├── CLAUDE.md.template
│       ├── README.md.template
│       ├── SETUP.md.template           # 共同編集者 onboarding walkthrough
│       └── AUDIT.md.template
├── docs/
│   ├── usage-tips.md                 # 運用Tips（English）
│   ├── usage-tips.ja.md              # 運用Tips（日本語）
│   ├── git-crypt-guide.md            # git-crypt 暗号化ガイド（English）
│   ├── git-crypt-guide.ja.md         # git-crypt 暗号化ガイド（日本語）
│   ├── sensitive-repo-patterns.md    # 機密情報を含むリポの設計パターン（English overview）
│   ├── sensitive-repo-patterns.ja.md # 機密情報を含むリポの設計パターン（日本語、本編）
│   ├── convention-design-principles.md # 規約設計の原則（メタレベル）
│   └── personal-layer.md             # 4 層モデルの正本 (audience size 順 numbering、 layer 1-4 の責務と依存規則)
├── gitignore_global        # グローバル gitignore（~/.gitignore_global に symlink）
├── gfm-rules.md            # GFM レンダリング落とし穴リファレンス（CJK bold × 全角句読点 / 裸 URL を `**…**` で囲むと autolink が壊れる 等）
├── LICENSE                  # MIT
└── .gitignore
```

## セットアップ（新しい端末で）
```bash
mkdir -p <base> && cd <base>
gh repo clone odakin/claude-config
cd claude-config && ./setup.sh
```

setup.sh が自動で行うこと:
1. `<base>/CONVENTIONS.md` → `claude-config/CONVENTIONS.md` の symlink（Windows は cp）
2. `~/.gitignore_global` → `claude-config/gitignore_global` の symlink + `git config --global core.excludesfile` 設定
3. Claude Code hooks を `~/.claude/hooks/` に symlink + `settings.json` に設定マージ
4. *(macOS のみ)* PATH 消失防止（`.zprofile` の重複 `brew shellenv` 修正 + スナップショット自動パッチ用 launchd エージェント）+ **Claude.app の新セッション folder picker を `<base>` に固定する launchd エージェント**（default-ON = **デスクトップアプリ使用時のみ** install〔CLI 専用 Mac は skip〕、 1 秒間隔だが drift 時のみ書込 = steady-state は read のみ、 opt-out 可 = `touch ~/.claude/pin-claude-cwd.off` or `CLAUDE_PIN_CWD=0`。 詳細・除去手順は `conventions/claude-app-cwd-pin.md`）
5. Claude Code パーミッション設定 — 安全なツール（Bash, Read, Edit, Write, Glob, Grep, WebFetch, WebSearch）を自動許可
6. git post-merge hook をインストール（`git pull` 後に hooks と CONVENTIONS.md を自動同期）
7. 認証ユーザーの全リポを `<base>/` 以下に clone（未取得のもののみ）
   - *(条件付き)* 個人層 (`.claude-personal-layer` マーカーファイルを持つディレクトリ) を `<base>/` 直下から検出し、見つかれば `<base>/CLAUDE.md` をそのディレクトリの `CLAUDE.md` への symlink にする。`CLAUDE_PERSONAL_LAYER` 環境変数で明示指定可（`none` で無効化）。検出ロジックの詳細は `docs/personal-layer.md` 参照
   - *(条件付き)* 個人層が見つからない場合は `templates/root-CLAUDE.md.default` をデフォルトの `<base>/CLAUDE.md` として設置
   - *(条件付き)* 個人層に `dropbox-collabs.yaml` があれば `scripts/setup-dropbox-refs.sh` を呼んで `<base>/<repo>/dropbox-refs` symlink を生成 + 個人層 `.git/hooks/post-merge` に同スクリプトを install（次回 `git pull` で symlink 自動再生成）。詳細は `conventions/dropbox-refs.md` 参照
   - *(条件付き、macOS のみ)* 個人層に `scripts/setup-file-associations.sh` があれば実行（Launch Services のファイル拡張子別デフォルトアプリ設定）
8. 全リポに pre-commit hook をインストール（Unicode→LaTeX 自動修正 + layer-3 chain hook）— hook 自体が staged file に `.tex/.bib/.bst/.cls/.sty` が無ければ **LaTeX fix 部分は no-op** なので、 LaTeX file 不在の repo にも install して問題ない。 ただし **末尾の layer-3 chain hook (= yaml/data gate) は LaTeX file 有無に関わらず常に実行する** (= LaTeX file 無しで early-exit すると chain した gate が silent dead になる、 2026-06-06 RCA は `conventions/hook-authoring.md §8` 参照)。 旧方式 (LaTeX file 検出経由) は時点依存で、 setup.sh 実行後に `.tex` 追加された repo で hook 未 install のまま事故になっていた (2026-05-14 RCA は `DESIGN.md` 参照)
9. *(条件付き)* JHEP.bst を texmf-local にインストール（odakin: 自動、他ユーザー: オプション表示）
9b. *(条件付き)* commit author email の privacy（Step 6c）— `user.email` が実 email（`@users.noreply.github.com` 以外）なら、各ユーザーの GitHub noreply（`<id>+<login>@users.noreply.github.com`、`gh api user` から導出 = ハードコードしない）を提示。odakin: 自動設定（冪等）/ 他ユーザー: 推奨コマンドを表示のみ（非破壊）。public commit に実 email を焼き付けないため
10. *(条件付き)* git-crypt 暗号化リポを自動 unlock。共有プロジェクト鍵 (`~/.secrets/<repo>.key`) があればそれを優先、なければ個人鍵 (`~/.secrets/git-crypt.key`) で fallback
11. *(条件付き)* Hammerspoon 設定をインストール（macOS + Hammerspoon インストール済みの場合のみ。Claude Cmd+Q 誤終了防止 + ⌃⌥⌘V クリップボード整形+貼り付け hotkey）

## How to Resume
1. SESSION.md を読む → 現在状態と残タスクを把握
2. 残タスクに従って作業継続
3. 変更後は commit + push（全リモートに）

## 安全規則（公開リポ）

**このリポは public** (= GitHub で誰でも閲覧可、 検索 index 対象)。 本節は **leak prevention 軸** の rule で、 [4 層 model の layer dependency 軸](docs/personal-layer.md#what-depend-means-structural-dependency-vs-mention) (= 「depend vs mention」) とは別 axis。 leak 軸では mention でも leak が完了するため、 「boundary 文を併記すれば OK」 という layer 軸の救済は **適用されない** (= public surface に名前が焼き付いた時点で覆らない)。

以下を絶対に **file 本文 / commit message / PR description / tag annotation / commit author email** のいずれにも書かない (= git history surface 全体が対象、 file 本文だけが対象ではない):
- 実名（GitHub ユーザー名 `odakin` は可）
- メールアドレス
- 非公開リポ名（→ 個人層の `repos.md` に記載）。 後述「§例外 list と criterion」 参照
- 金融データ・口座情報
- 所属機関名
- 他ユーザーのユーザー名

変更前に「公開リポに載せて問題ないか」を必ず確認すること。

### 例外 list と criterion

以下の非公開リポ名は本リポでの mention OK (= leak しても business / research specifics が漏れない category-level / function-level の name):

| repo name | category / function | mention OK の理由 |
|---|---|---|
| `gmail-mcp-config` | Gmail MCP server 運用設定 | 機能カテゴリ名、 odakin が Gmail MCP を使うことは tool 利用の事実のみ leak |
| `research-collab` | 研究 collaboration 管理 (= mail thread / project index) | カテゴリ名、 odakin が共同研究者を持つことは public profile から既知 |
| `email-office` | 学内事務メール処理 | 機能カテゴリ名 |
| `odakin-prefs` | personal layer (= L3 個人層) | 規約上の position name、 personal-layer.md で公開構造として説明済 |
| `secrets-config` | 秘密情報の保管経路 | 機能カテゴリ名 |
| `physics-research` | 物理研究 career DB | category 名、 odakin が物理学者であることは INSPIRE 等から公知 |
| `conferences` | 研究会・workshop 参加 lifecycle ledger | 一般語、 研究者が学会に参加・発表することは public profile (= CV / talks list) から既知 |

**criterion**: 名前が (1) category-level / function-level の一般語であり、 (2) 名前から推察される specifics が **既に public profile から得られる範囲を増やさない** なら例外 OK。 NG 例: `<institution-code>-<topic>` (= 所属 institution が public でも、 そこに紐付く具体 topic の組合せは更なる leak)、 `<project-codename-specific>` (= 個別 project codename)、 `<collaborator-name>-collab` (= 共著者名 leak)、 `<unpublished-result>-analysis` (= 未公開研究 leak)。

新規リポを例外 list に追加する判断は user が行う (= Claude が独断で追加しない)。 また「既に commit history に名前が出てしまった repo」 を追跡的に追加するのも user 判断 (= 過去 leak の追認 vs 「list に入れず history 内残置は許容」 の判断は user の risk 評価による、 Claude は自動 list 化しない)。

**commit message 拡張の根拠 (2026-05-13)**: file 本文では意識的に抽象化 (例: 「upstream リポ」) しても commit message で同 session の private repo 名を直書きする事故が複数 commit にわたって発生 (incident 集計は owner の private layer の leak-incidents 記録にあり)。 commit message は `git log` で grep 可能な public surface なので file 本文と同じ規律を適用する。 既存 `public-precommit-runner.sh` は file 本文の Tier A 検出のみで commit-msg は対象外だが、 2026-05-26 に `commit-msg-leak-guard-runner.sh` (BLOCK mode、 git native hook) で commit message scan を導入済 (= 設計詳細 [`DESIGN.md §2026-05-26`](DESIGN.md))。

### Test file の private repo 名 literal 禁止 (2026-05-26 追加)

layer 1 (= 本 repo) の **test file source code に実 private repo 名を literal で書かない**。 fixture / test case で「private repo 名を含む input」 を必要とする場合は **mock-personal-layer pattern** で代替する (= `CLAUDE_PERSONAL_LAYER` env var で temp dir 注入 + 偽 `repos.md` + mock literal で test、 詳細手順 [`conventions/hook-authoring.md §7`](conventions/hook-authoring.md))。

根拠 (= 2026-05-26 self-leak RCA): `commit-msg-leak-guard-runner.test.sh` 初版 (= commit `4f4e636`) で test case literal に実 private repo 名 4 種を embed していた self-leak event。 hook 自身は commit message scan のみで file body を scope 外として通過、 public commit に焼き付き → 4 軸 sweep 安全性軸で発覚 → `c7a9144` で mock pattern に refactor。 詳細経緯: [`DESIGN.md §2026-05-26`](DESIGN.md) 反省 section + [`hook-authoring.md §7`](conventions/hook-authoring.md) implementation pattern。

→ **implementer reflex**: layer 1 test file を書く瞬間に「この test data は public commit に焼き付く、 実 layer 3 data の literal が混入していないか?」 を問う。 過去事例の literal copy-paste は最も再演しやすい failure mode (= 「過去事例の reproduce」 が目的化される)。

⚠️ **2026-06-16 拡張 — test file に限らず「規約本文の例」 と「script の docstring / `--selftest` fixture」 も同じ**: layer 1 の convention 本文に書く**例**や script の selftest data も public surface。 trigger となった実 incident の **実人名・所属・固有値をそのまま例に使わず**、 架空データ (= 「甲野 太郎」 「架空大学」 等) に置換する。 2026-06-16 near-miss: office-automation の文字 clipping を整備中、 検出器 script の selftest と convention 本文の症状例へ **実セミナー講演者の氏名・所属 (= まさに結合セルで clip した当の値)** を literal で書き込み、 commit 直前の leak grep で検出して匿名化した。 = **incident を正確に記録しようとするほど実 PII を例に焼き込む引力が強い** (= 上記「過去事例の reproduce が目的化」 の PII 版)。 → commit 前に **変更 diff を実名 list で grep する** のを最終 gate にする (= 2026-06-16 はこれで救われた)。

### Layer 軸 vs Leak 軸の関係 (= 混同しないための table)

| | layer dependency 軸 | leak prevention 軸 (本節) |
|---|---|---|
| 何を防ぐ | smaller-audience layer に依存 → collaborator 環境破綻 | public surface に private 情報の永久記録化 |
| 適用範囲 | 任意の L_n → L_m (m > n) reference | claude-config 自身 (= L1 public) の全 surface |
| mention の扱い | boundary 明示付きで許容 | 例外 list 内 name のみ許容 (= boundary 文では救済不可) |
| 正本 doc | [`docs/personal-layer.md` §「depend vs mention」](docs/personal-layer.md#what-depend-means-structural-dependency-vs-mention) | 本節 |

## 運用ルール
- CONVENTIONS.md の正本はこのリポ内のファイル
- `<base>/CONVENTIONS.md` は symlink（setup.sh が作成。Windows は cp + post-merge hook で自動同期）
- CONVENTIONS.md を変更したらこのリポで commit + push
- 他端末では `git pull` で同期

## 自動更新ルール（必須）
以下を人間に言われなくても自動で行う:
- CONVENTIONS.md を変更したら → このリポで commit + push
- CLAUDE.md のルールの詳細は `<base>/CONVENTIONS.md` 参照
