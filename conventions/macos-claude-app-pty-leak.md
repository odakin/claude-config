<!-- doc-meta
when: macOS で forkpty: Device not configured が出たとき
category: macos
summary: macOS で Claude.app が `kern.tty.ptmx_max=511` を独占 → Terminal 等で `forkpty: Device not configured` 発生時の段階的 sysctl bump workaround (hard ceiling ~960、 root 対処は Claude.app restart、 Anthropic bug report 候補)
-->
# macOS Claude.app pty leak workaround

**症状**: Claude.app desktop プロセス (= `/Applications/Claude.app/Contents/MacOS/Claude`、 Electron parent) が **`/dev/ptmx` master fd を解放せず蓄積**し、 `kern.tty.ptmx_max` (= macOS default 511) に達すると **system 全体の pty 確保が枯渇**。 新規 Terminal.app / iTerm2 / VS Code 等が `forkpty: Device not configured` (= 「新しいプロセスを作成して擬似 tty を開くことができませんでした。」) で起動不可になる。 Claude.app 自身は normal app に見えるので Terminal 側の故障と誤認しやすいが、 **Terminal は無罪**。

**蓄積機構**: 各 Claude Code の Bash tool 実行が pty (node-pty) を 1 個 allocate し、 完了後も master fd が Electron parent に残る。 長時間 session / 多数の Bash 実行で単調増加し、 数時間〜2-3 日で上限に到達する。

## 確認済み事実 (= 推察ではない)

### 再現環境 (cross-OS / cross-arch)

| 観測日 | OS | arch | 観測値 |
|---|---|---|---|
| 2026-05-15 | Ventura 13.7.x | Intel | 511/511 (旧 default 上限ぴったりを Claude が独占) |
| 2026-06-08 | Sonoma 14.7.4 | arm64 (Apple Silicon) | 590/958 で **単調増加中** (= bump 後も leak 継続)、 同 PID が leak を蓄積 |

→ 特定 OS / chip 固有ではなく、 Claude.app (Electron + node-pty) 共通の bug。

### upstream (anthropics/claude-code) の認識状況

- **報告は多数**: pty/ptmx leak の issue が十数件 (2026-05-09〜06-07)。 canonical = #47909、 最も議論があるのは #57580 (10 comments)。 他 open: #62378 / #63131 / #63169 / #65090 / #65995。
- **Anthropic スタッフの応答なし**: #57580 のコメントは全て外部ユーザー (author_association: NONE)。 唯一の Anthropic 由来の動きは **bot による重複自動 close + 自動クローズ予約**。 5 月中旬の closed 数件 (#58263 / #59544 / #59839 / #61124 / #61358) は **修正でなく重複整理**。
- **fix / target version / assignee いずれも無し** (2026-06-08 時点)。 **最新版へ上げても直らない** (報告群 2.1.138〜156、 当方 2.1.165 でも leak 確認)。

### 同根の cross-tool bug (= node-pty 共通)

node-pty が `posix_spawn` 失敗時に PTY master を開いたまま `child_process` fallback して fd を close しないのが root と特定済 (gemini-cli #15945)。 同症状: Cursor / opencode (#11016) 等、 node-pty を使う Electron 系 CLI 全般。 → **Anthropic 単独でなく node-pty 層の問題**だが、 当面 Claude.app 側でも未対処。

## Quick install (claude-config 同梱の 1 コマンド)

macOS で claude-config を使っているなら、 同梱 installer で緩和を配線できる (idempotent、 macOS 以外は no-op):

```bash
# (1) watchdog のみ (sudo 不要): 枯渇前に macOS 通知
bash scripts/install-pty-leak-mitigation.sh

# (2) + 即 bump + reboot 後も 958 維持 (admin password 1 回)
bash scripts/install-pty-leak-mitigation.sh --persist
```

- watchdog = `scripts/pty-leak-watch.sh` を LaunchAgent `com.claude-config.pty-leak-watch` (5 分毎、 85%/93% で通知) として配線。 launchd 直起動なので **watchdog 自身は pty を消費しない**。
- `--persist` = LaunchDaemon `com.claude-config.ptmx-bump` を install。 bootstrap 時に RunAtLoad で **即 511→958 bump** + 以後 boot ごとに維持。
- 個人ラベル等からの移行は `--replace-agent <label>` / `--replace-daemon <label>` (= 旧を bootout+rm してから新を入れる、 admin dialog は 1 回)。
- **これらは緩和** (= 壁の手前で時間を稼ぐ)。 唯一の回収は Claude.app restart (下記)。

⚠️ **SoT note**: 実行可能な実体 — 段階 bump の数列 / LaunchDaemon plist / watchdog ロジック / 通知閾値 — は **`scripts/install-pty-leak-mitigation.sh` + `scripts/pty-leak-watch.sh` が単一の正本**。 以下の節は**原理と判断材料のみ**を説明し、 数列・plist・script 本体は doc に複製しない (= drift 防止)。

## Diagnosis

```bash
# system 上限
sysctl -n kern.tty.ptmx_max          # default 511 / bump 後 958

# 使用中の /dev/ptmx master fd 数 (= device 指定 lsof が速い)
lsof /dev/ptmx 2>/dev/null | grep -c /dev/ptmx
# → 上限付近なら枯渇

# どのプロセスが何個か (= Claude が大多数なら確定)
lsof /dev/ptmx 2>/dev/null | grep /dev/ptmx | awk '{print $1, $2}' | sort | uniq -c | sort -rn | head
# → "559 Claude 60976" のような出力 = Claude.app が独占
```

**leak vs burst の判別**: `/dev/ttys*` (slave 側、 zsh 終了で解放) でなく **`/dev/ptmx` (master 側、 Electron parent が保持)** を見ること。 ttys だけ見ると「9 本しか開いてない」 と誤診する。 同 PID の保持数が時間で**単調増加**するのが leak の signature。

## 段階 bump の原理 (= 実行は installer、 ここは説明のみ)

`kern.tty.ptmx_max` は runtime で write 可能だが **増加量に kernel 制約** (= 1 回で current の `~1.2 倍`まで)。 一気に 511 → 2048 は `Invalid argument` で reject されるので段階的に上げる。 **実行する段階列 (511→958) と LaunchDaemon plist の正本は `scripts/install-pty-leak-mitigation.sh`** (= `--persist` で bootstrap 時に即 bump + reboot 後も維持。 plist の inline は guard `[ "$n" -gt "$cur" ]` で「現在値より上だけ set」 = 冪等)。 ここでは上限と判断材料のみ示し、 数列は doc に複製しない。

### 実測 hard ceiling (2026-05-15 Ventura 13.7.8)

| from → to | ratio | result |
|---|---|---|
| 511 → 512 → 514 → … (指数的 +2,+4,…,+128) → 894 → 958 | ≤1.2 | OK |
| 896 → 960 | 1.071 | OK |
| 960 → 1024 | 1.067 | **NG (Invalid argument)** |

**Hard ceiling ~960-1023** (= kernel-locked、 SIP 関連)。 これ以上は上げられない。 `sysctl -w` は揮発 (reboot で 511 復帰) なので恒久化には `--persist` の LaunchDaemon が要る。 **緩和であって治癒ではない** (= leak は続くので 958 もいずれ食い潰す)。

### ⚠️ 重要 caveat: 完全枯渇後は bump 自体が不能

`sysctl` の admin 昇格 (osascript ダイアログ) や shell 起動自体が pty を要するため、 **958/958 まで使い切ってからでは bump コマンドが走らない** (= deadlock、 upstream #57580 で報告済)。 必ず**壁に着く前**に bump (or restart) すること。 watchdog (下記) で閾値手前に警告するのが実効的。

## watchdog の原理 (= 実装は scripts/pty-leak-watch.sh)

枯渇後 bump 不能 (上記 caveat) なので、 閾値手前に通知して restart を促す。 実装は `scripts/pty-leak-watch.sh` (= `lsof /dev/ptmx` の使用率を読み、 閾値超で macOS 通知)、 `installer` が LaunchAgent `com.claude-config.pty-leak-watch` (`StartInterval` 300) として配線する。 **LaunchAgent は launchd 直起動なので watchdog 自身は pty を消費しない** (= leak を増やさない)。 通知文・閾値・ロジックは script が正本 (= doc に複製しない)。

## 真の対策: Claude.app restart (= 唯一の回収手段)

leak した master fd を外部から個別 close する手段は無い (= 他プロセスの fd を強制 close する API 無し)。 **回収は Claude.app を完全 quit して全 fd を release させる一択**。 ただし実行中の Claude Code session は消える (= chat history は desktop 永続化されるので restart 後復元可、 但し model の working memory はリセット)。

restart 方法 (= terminal が開けない状態でも可):
1. **Activity Monitor** を Cmd+Space → 起動
2. 検索バーに `Claude` → CPU タブで filter
3. `/Applications/Claude.app/Contents/MacOS/Claude` プロセスを select
4. 左上「ⓧ Stop」 → 「強制終了」
5. Terminal.app を試す (= 復活確認)
6. Claude.app 再起動 → conversation 再開

## How to apply

1. `forkpty: Device not configured` を見たら、 まず `lsof /dev/ptmx | grep -c /dev/ptmx` で count を取り、 上限付近なら pty 枯渇を確認
2. `/dev/ptmx` (master) を見る。 `/dev/ttys` (slave) ではない
3. **まだ余裕があるうち**に対処 (= 枯渇後は bump 不能)。 即 bump + 恒久化 + watchdog 配線 = `bash scripts/install-pty-leak-mitigation.sh --persist`、 根本回収は Claude.app restart
4. 予防は watchdog の閾値警告 (= installer が配線)、 reboot 後の 511 復帰回避は `--persist` の LaunchDaemon

## 関連

- upstream: anthropics/claude-code #47909 (canonical) / #57580 (議論最多) — **Anthropic 未対応** (= 2026-06-08 時点、 #57580 の全 comment は外部 user [author_association: NONE]、 staff 応答なし / bot の重複自動 close のみ / fix・target version・assignee いずれも無し)。 #57580 に **v2.1.165 still-affected の実測 data point 投稿済** (2026-06-08、 Anthropic 反応あれば follow-up 候補)。 報告を増やすと優先度向上に寄与
- root cause: node-pty `posix_spawn` fallback の fd leak (gemini-cli #15945 で特定)
- sibling: `macos-claude-code-tcc-recurring-prompt.md` (= 同じく Claude.app の versioned path 由来の構造的症状、 Anthropic 側 fix 待ち)
- macOS pty pool 上限は kernel-locked (= ~960 が hard ceiling、 SIP 関連)
- 実装 SoT: `scripts/install-pty-leak-mitigation.sh` (= 段階列 / plist / 配線) + `scripts/pty-leak-watch.sh` (= watchdog 本体)
