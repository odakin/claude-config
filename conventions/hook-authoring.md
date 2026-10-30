<!-- doc-meta
when: Claude Code hook を作成・配信・debug するとき + bash script / `.test.sh` を書くとき + app や tool の挙動を当てる hook を書くとき (#imitate-target-predicate) + 事後の block の手前に事前の知らせを置くとき (#counter-notice-at-injection) + hook を消す・event から外すとき (#additive-wiring-needs-retirement) + git commit が「hook ... died of signal 9」 で止まったとき (#killed-hook-stub) + 返事に書くべき行を Stop で確かめる hook を書くとき (#stop-hook-addendum-not-reemission) + 並列の session の hook が同じ state file を読み書きするとき (#shared-state-file-merge) + command の option を当てる hook を書くとき (#command-flag-normalization) + command が file を読むかを当てる hook を書くとき (#command-reads-file-tokenize) + SessionStart の一覧が大きくなったとき・予算と警報を置くとき (#digest-size-budget) + git の履歴の fixture を作る test を書くとき (#git-fixture-pinned-dates) + 並列の commit の race (HEAD が動く窓) を test で再現するとき (#git-race-fixture-via-hooks) + Stop hook が会話記録から「今の turn」 を探すとき (#transcript-user-message-shape) + 会話記録から本人の発言と別 session の message を見分けるとき (#transcript-human-vs-peer-message) + 層1 に新しい hook を足す変更の承認を取るとき (#new-hook-protected-bundle) + hook の matcher を書く・直すとき・tool が改名されたとき (#matcher-regex-partial-match) + model が書いた script を起動の前に空回しする hook を書くとき (#dry-run-model-authored-script) + Stop hook の block を繰り返させない仕組みを書くとき・他の hook の差し戻しの後の返事を判定するとき (#stop-hook-active-other-hooks) + 人の発言から判定を外す条件を引く hook を書くとき (#exemption-not-inherited-by-event-turns)
category: harness-core
summary: Claude Code hooks 作成 + 配信規律 (= bash 3.2 の $(...) + heredoc body quote escape parser bug と runtime backtick 展開を区別 + hook 配信正常性 3 軸 audit 〔symlink + settings.json + try-fire〕 + PreToolUse warn mode 出力 spec uncertainty + partial install state + §9 hook 挙動の build 依存 〔新規 hook の同 session 発火も build 依存 = 2026-06 は session / app 起動時 snapshot、 desktop 2.1.266 は Stop hook を hot-reload → 足した直後に discriminator で測る / permissionDecisionReason silent-skip / updatedInput〕 + **§0 補足 4 gate hook は読めない入力で死んではいけない (#gate-hook-unreadable-input = 1 file の異常が repo 全体の commit を止める、 encoding 明示 + READ_SKIP で 1 行報告して続行)** + **§0 補足 5 set -e の test は落ちた行を自己申告 (#set-e-test-failure-report = scripts/lib/test-err-trap.sh、 ERR trap の bash 3.2 / 5 実測表、 BSD/GNU の手元再現 = scripts/with-gnu-userland.sh)** + **§2 補足 2 #disableallhooks-kill-switch = root 限定の disableAllHooks が「frontend 差」 に化ける 〔自 session では検出不能 = 外側から scripts/hook-liveness-audit.py、 audit-hooks.sh の (d) 自動部分〕** + **test-root-not-parent-dir = test は自分の repo を checkout の親 dir 経由で指さない 〔worktree で落ち・live を検査・python shim は CI でも空振り = 一時 root に symlink 1 本 + 兄弟 repo は正規 layout + 不在は SKIP + mutation で確かめる〕** + **§12 #text-pattern-stop-hook = 最終発話の句で当てる Stop hook は過去の最終発話で校正してから入れる 〔scripts/calibrate-final-message-pattern.py + 共通部品 scripts/lib/transcript_turns.py〕・引用の例示を除く・block は 1 回・fail-open** + **§14 #opt-in-side-effect-hook = 人に向けた副作用だけの hook (音・通知) は層1 に既定 off で置き marker で opt-in、 surface の許可 list は実測値だけ、 実行の証拠を state file に残す** + **#command-guard-calibration = command を見る PreToolUse guard も過去の Bash command で校正 (scripts/calibrate-bash-command-pattern.py) し、 わざと該当する無害な command で live 確認** + **§15 #injection-digest-and-relay = SessionStart の注入は期限の近い item の 1 ブロックに畳み (副作用は止めない・行数で切らない・自分で決めた期日と条件発火は畳まない)、 短い窓の item は伝えたかを Stop で問う 〔scripts/lib/relay_check.py〕**)
-->
# Claude Code hooks の作成 + 配信規律
<!-- slug index: hook-authoring.index.yaml — cross-ref sections by #slug (stable), not §-number. See convention-design-principles §14.2 / §14.7. -->

> 適用対象: `claude-config/hooks/` (= layer 1) + 個人層の `<personal-layer>/hooks/` (= layer 3) の hook script 全般。 hook 作成・配信・audit の **3 種類の構造的 trap** を扱う。 §0 の補足群 (shebang / set・BSD/GNU 差・ERR trap・test の失敗自己申告・test の root の決め方) は hook に限らず repo 内の bash script / `.test.sh` 全般に適用する。
>
> 関連 hook: `claude-config/hooks/*.sh` (= 既存 8 hooks)、 hook 配信機構の正本は `claude-config/setup.sh` Step 2 (= `install_hooks()` 関数)

---

## <a id="hook-category-intro"></a>概論: hook は他の script と質的に異なる category

普通の utility script は:
- (i) 実行環境を作者が選べる (= `#!/usr/bin/env python3` 等で modern runtime を assume 可)
- (ii) 失敗時は exit code + stderr で expose される
- (iii) 1 行で起動できる (= command path 1 個指せば動く)

claude-code hook は **3 つとも逆**:
- (i) **macOS stock `/bin/bash` (= 3.2.57) で起動**。 homebrew bash 5.x で書いて動かしただけでは ship 不可
- (ii) **配信不全は silent**。 symlink broken / settings.json entry 欠落の各 mode で stderr 不在
- (iii) **配信が 2 段** (= filesystem symlink + settings.json 登録) で、 1 段だけ揃っても起動しない

→ hook 作成者は **特殊な category の作業をしている** という認識から始める。 普通の bash convention で十分と思った瞬間に下記 3 trap のどれかを踏む。

---

## <a id="naming-convention"></a>§0. naming convention: suffix で behavior を区別

hook script の filename suffix で **block するか否か** を機械的に区別する:

| suffix | behavior | 終了経路 | 例 |
|---|---|---|---|
| `-nudge` | **non-blocking** (= informational injection only) | exit 0 + stdout に `<system-reminder>...` または `additionalContext` JSON | `pdf-read-fallback-nudge.sh`, `git-state-nudge.sh` |
| `-guard` | **blocking via PreToolUse permissionDecision** (= ask / deny) | exit 0 + stdout に `{"permissionDecision": "ask"\|"deny"}` JSON | `memory-guard.sh`, `google-url-guard.sh`, `expensive-tmp-guard.sh`, `public-leak-guard.sh`, `commit-msg-leak-guard.sh` |
| `-enforce` | **blocking via Stop / Pre*ToolUse 非 ask 経路** (= 別 phase での block) | exit 2 または stdout に `{"decision": "block"}` JSON | (⚠️ かつての例 `pdf-open-enforce.sh` は 2026-06-23 に side-effect action へ転換 = 下記注。現在 active な `-enforce` hook は無し) |

suffix と behavior の対応がずれている (= 例: `-nudge` 接尾辞だが実際は block する) hook は、 後の audit / 縮退判断 (= §6) で「nudge だから止めても安全」 「enforce だから drift しても catastrophic」 等の reflex 判断と整合が取れず事故の元。

新 hook 命名時の判定:
1. block (= 該当 flow を止める) する? → No なら `-nudge`、 Yes なら 2 へ
2. block 経路は PreToolUse の `permissionDecision: ask|deny`? → Yes なら `-guard`、 No (= Stop / 他 phase / 直接 `decision: block`) なら `-enforce`

既存 hook の rename は不要 (= 命名規約導入以前の hook は behavior が `-nudge` / `-guard` のいずれかで揃っており suffix と整合済)、 新規 hook からこの規約を follow する。 初出: `pdf-open-enforce.sh` (= 2026-05-21、 Stop hook で `{"decision": "block"}` を返す初の hook)。

⚠️ **`pdf-open-enforce.sh` の suffix は 2026-06-23 から grandfathered (= suffix↔behavior 不一致)**: 同 hook は **block (`-enforce`) から side-effect ACTION (= hook 自身が `open <pdf>` を実行、 block せず always exit 0) へ転換**した。理由 = block 型は §9.3 の desktop-hook-gap で死ぬ (= Stop の `decision:block` が honれない) ため、 §9.3 の「side effect は走る」 非対称を使って hook が直接 `open` する形に変えた (= RCA `<personal-layer>/plans/2026-06-23-pdf-preview-discipline-rca.md`)。**side-effect action は本 §0 の 3 suffix のどれにも当てはまらない 4 つ目の behavior class** だが、 rename の blast radius (= settings.json + symlink + manifest + test + cross-doc ref) を避けて filename を据え置いた。新規に side-effect action hook を作るなら `-open` / `-action` 等の suffix を検討し、 本 hook も将来 pass で rename 余地あり。audit (§6) で「`-enforce` だから block する」 と reflex 判定しないこと (= 本 hook は exit 0 / 非 block)。

### <a id="shebang-set-policy"></a>§0 補足: shebang / set 方針

repo 内 shell script (hooks/ + scripts/ + setup.sh) の統一方針 (2026-07-10):

- **shebang 標準 = `#!/usr/bin/env bash`**。 `/bin/bash` 直指定は macOS で bash 3.2 に固定される — 3.2 互換で**書く**規律 (§1) と、 PATH 上の新しい bash でも**動く**ことは両立するので、 env 経由を標準とする。
- **`#!/bin/sh` は POSIX 徹底が確認できた script のみ** (= bashism ゼロ + `sh -n` pass を確認してから)。 該当は launchd から呼ばれる install / watchdog 系 (`install-launchd-cron.sh` / `install-pty-leak-mitigation.sh` / `install-remote-control-server.sh` / `pin-claude-cwd.sh` / `pty-leak-watch.sh`) — 最小 shell 前提の文脈で意図的。 bashism を足したくなったら shebang ごと bash に切り替える (= sh のまま bashism 混入が最悪)。
- **例外: `fix-snapshot-path-patch.sh` は `#!/bin/zsh`** (= zsh 環境の PATH snapshot を patch する対象整合で zsh、 launchd WatchPaths 起動)。 shebang が zsh でも run-all-checks の `bash -n (all shell scripts)` は全 `.sh` を bash の構文で読むので、 zsh の script にも zsh 固有の書き方 (glob 修飾子 `(N/)`・`${^arr}`) を書かず、 `setopt null_glob` と普通の `for` で同じ動きにする (実測 = CI が赤になった)。
- **層1 (claude-config) の置き場を引く変数は `CLAUDE_CONFIG_ROOT` (既定 `~/Claude/claude-config`)。 `CLAUDE_CONFIG_DIR` を使わない** = これは Claude Code 自身の設定フォルダ (`~/.claude-<name>`) を指す変数で、 設定フォルダを分けた session では値が入っている。 取り違えると、 その session でだけ部品が見つからず処理が黙って空振りする (実測 = 退役した hook を外す段が空振りした)。
- **hook (hooks/*.sh) は `set -uo pipefail` を標準**。 `set -e` は**使わない** — hook 内の grep / git は「no match」 等で正当に非ゼロ exit するので、 -e は最初のそれで hook を殺す (git-state-nudge.sh header の設計 note 参照)。 optional な env / 変数は `${VAR:-default}` で明示するのが -u との契約。
- **set -u を既存 script に後付けする時は、 先に .test.sh で挙動を固定してから** (= unbound 参照が実行 path 依存で潜んでいることがあり、 挙動変化 (途中死) が silent に起きるため。 hooks/ の guard hook は全数 .test.sh 持ち)。
- **日本語の直前の変数は `${var}` と書く** — UTF-8 の locale では bash 3.2 が全角文字の先頭 byte を変数名に取り込み、 `set -u` なら落ち、 無ければ値が黙って消える ([`shell-multibyte-truncation.md#unbraced-var-before-multibyte`](shell-multibyte-truncation.md#unbraced-var-before-multibyte))。 書いた script は [`scripts/check-unbraced-multibyte-var.py`](../scripts/check-unbraced-multibyte-var.py) `--paths <file>` で確かめる (C locale の test は通るので test の緑では分からない)。
- <a id="empty-array-under-set-u"></a>**空になりうる配列は `${arr[@]+"${arr[@]}"}` で展開する** — macOS の `/bin/bash` (3.2) は `set -u` の下で空の配列の `"${arr[@]}"` を unbound として止める (bash 4.4 以降は通る = 新しい bash で回した test では分からない)。 実測: 引数の一部を env で渡す test の時だけ hook の配列が空になり、 hook は fail-open で黙って何も出さなかった (test の失敗でしか見えなかった)。
- scripts/ 側の `set` は script の性質で選ぶ (fail-open が契約の surface 系は敢えて緩くする場合がある) が、 新規 script は `set -u` 以上を default とする。

### <a id="substitution-fallback-stdout-mixing"></a>§0 補足 2: `$(a || b)` fallback は「a の部分 stdout」 を混入させる — BSD/GNU 分岐は exit code でなく出力検証で

**罠**: `VAL="$(cmd_bsd 2>/dev/null || cmd_gnu 2>/dev/null || echo default)"` の fallback idiom は、 **cmd_bsd が「失敗しつつ stdout に何か吐く」 場合に壊れる** — command substitution は chain 中の**全 command の stdout を連結**するので、 VAL には「cmd_bsd のゴミ + cmd_gnu の正解」 が混ざる。 `2>/dev/null` は stderr しか殺さない。

**実例 (2026-07-10、 CI 初回走行で検出)**: `stat -f %m <file>` は BSD (macOS) では file mtime を返すが、 **GNU (Linux) では「%m という filesystem」 の照会と解釈され、 exit 1 を返しながら stdout に filesystem 情報数行を dump する**。 `$(stat -f %m F || stat -c %Y F || echo 0)` の結果は Linux で「FS dump + 正しい mtime」 の複数行文字列になり、 後段の `$((NOW - VAL))` が算術エラーで script ごと死ぬ。 この idiom で `stale-read-nudge.sh` と `git-state-nudge.sh` が**全 Linux ユーザー環境で silent 死**していた (macOS では正常なので owner 環境では不可視 = CI が初めて露出させた)。 **変種 (2026-08-29)**: 混入がクラッシュせず**値として通ってしまう**場合はさらに悪い — FS dump には Free blocks 等の**呼ぶたび変わる数値**が含まれるため、 これを dedup key の hash 種に使うと「毎回 key が変わって dedup が一度も効かない」 silent 動作不全になる (crash しない分、 test の n 回数比較まで気付けない)。

**正しい形 = 出力の数値検証で分岐** (exit code を信用しない):

```bash
VAL="$(stat -f %m "$F" 2>/dev/null)"
case "$VAL" in ''|*[!0-9]*) VAL="$(stat -c %Y "$F" 2>/dev/null)" ;; esac
case "$VAL" in ''|*[!0-9]*) VAL=0 ;; esac
```

**一般則**: 出力を後段で使う fallback chain は、 「前段が失敗した」 の判定を **exit code でなく出力の形 (数値・非空・pattern) の検証**で行う。 exit code 分岐が安全なのは「失敗時に stdout が確実に空」 と分かっている command のみ — 他人の実装 (特に GNU/BSD 両生類の coreutils) にその保証を仮定しない。 適用実例: `hooks/stale-read-nudge.sh` (cache TTL) / `hooks/git-state-nudge.sh` (marker mtime ×2)。

**実例 2 (2026-09-11、 test の helper)**: 225 push 連続 red の原因 (`stat -f '%Lp'` の assertion、 経緯は [§0 補足 5](#set-e-test-failure-report)) を直した bbc1b62 の helper は `if stat -f '%Lp' F >/dev/null 2>&1; then stat -f '%Lp' F; else stat -c '%a' F; fi` = **exit code 分岐**だった。 GNU 側が exit 1 になるのは `%Lp` という名前の file が cwd に無いからにすぎず、 在れば GNU でも exit 0 で FS 情報を返す (GNU coreutils 9.10 で実測。 `ci-local-repro.sh --userland both -- sh -c 'touch %Lp && bash scripts/setup-codex.test.sh'` で GNU 側だけが落ちた)。 本節の一般則どおり、 GNU 形を先に試して出力が mode の形 (3-4 桁の 8 進) でなければ BSD 形に落ちる分岐に直した。 CI の遡り方 = [`debugging-discipline.md#ci-red-streak-forensics`](debugging-discipline.md#ci-red-streak-forensics)。

**兄弟形 = pipe 越しの成否判定** (同 kernel「見かけの exit code を信用しない」): `if cmd | sed 's/^/  /'; then` は **sed の exit code** を test している — cmd が失敗しても sed が成功すれば偽 success。 表示整形の pipe を挟むなら判定は `{ cmd 2>&1 | sed 's/^/  /'; exit "${PIPESTATUS[0]}"; }` の subshell 形で **PIPESTATUS[0]** に anchor する (`set -o pipefail` は「どれかが失敗した」 しか言えず「どれが」 を区別しない点に注意)。 実例: setup.sh の git-crypt unlock 判定が sed の exit code を見て失敗を success 計上していた (2026-07-10 修正)。 **第 3 形 = 前段の rc を見てしまう形** (`writer | hook` で書き手が SIGPIPE で死ぬ) = [§0 補足 10](#hook-stdin-pipe-sigpipe)。

### <a id="err-trap-inline-conditional-substitution"></a>§0 補足 3: `trap 'exit 0' ERR` × 条件付き inline 置換 = 値が空の環境でだけ hook が silent 死

**罠**: fail-open hook の定番 `trap 'exit 0' ERR` の下で、 optional な値を `msg="... $([ -n "$x" ] && printf ' (%s)' "$x") ..."` のように **command substitution 内の条件で整形**すると、 値が空のとき置換の exit status 1 が **assignment (= simple command) に伝播して ERR trap が発火**し、 hook がそこで silent 終了する。 素の `[ -n "$x" ] && cmd` の失敗は ERR trap 免除 (= && list 内) だが、 **それを含む置換の status を受け取った assignment は免除されない**のが非対称の罠。

**実例 (2026-07-10、 CI 初回走行で検出)**: session の worker host を自己申告する SessionStart hook が、 config metadata から email を読めた環境 (= owner の常用機) では正常、 **email の無い環境 (= 未 auth の config dir / fresh マシン) でだけ無出力で死んでいた** — マシン判別が一番要る状況でこそ stamp が消える倒錯。 author 環境では test 全 pass なので構造的に不可視 (= §0 補足 2 と同じく CI が初めて露出させた class)。

**正しい形 = 条件整形は if で組む** (置換の中に条件を入れない):

```bash
x_part=""
if [ -n "$x" ]; then x_part=" (${x})"; fi
msg="prefix${x_part} suffix"
```

**一般則**: `trap ... ERR` 下では「**空でありうる値**を条件付きで整形する command substitution」 が全て地雷 — 値が空の環境でだけ発火し、 author の環境では再現しない。 grep 検査: trap ERR 持ち hook に対して `grep -n '\$(\[ ' hooks/*.sh`。

---

### <a id="gate-hook-unreadable-input"></a>§0 補足 4: gate hook は「読めない入力」 で死んではいけない — 1 file の異常が repo 全体の commit を止める

commit gate (pre-commit) が staged file を舐めて検査する形は定石だが、 **検査対象が「読める」 前提で書かれていると、 1 file の異常が repo 全体の commit を止める**。 しかも止まり方が生の traceback なので、 呼び出し元 (人間 / agent) には「自分の変更のどこが悪いのか」 が見えない。

**実例 (2026-09-10)**: yaml corruption scanner が `open(path)` を encoding 指定なしで開き `yaml.YAMLError` だけを捕まえていた。 **並列 session が書き込み途中の yaml** を掴んで `UnicodeDecodeError` が素通りし、 hook が異常終了 → **その repo の commit が全部通らなくなった**。 自分の staged file は全て健全だったので原因特定に数往復かかった (= **検査対象は自分の file とは限らない**、 が盲点)。

規律:

- **encoding を明示する** (`open(path, encoding="utf-8")`)。 locale 依存にすると環境で挙動が変わる
- **「読めない」 は検査結果ではなく検査不能** — 例外を捕まえて専用の状態 (`READ_SKIP` 等) で返し、 **1 行報告して続行**する (= 黙って通さない / 落ちもしない。 [`convention-design-principles.md#silent-probe-false-healthy`](../docs/convention-design-principles.md#silent-probe-false-healthy) の pattern 3 と同じ形)。 鍵の無い機械で暗号のまま (git-crypt) の file は error を出さずに暗号文が読めてしまう = 先頭の `\0GITCRYPT` を見て同じ検査不能に数える (実測: link の anchor の検査が暗号文を本文として読み、 その file の anchor を全部「無い」 と報告した)
- **それを corruption に数えない** — 他 session の書き込み途中で自分の commit を止めるのは gate の役目ではない
- 呼び出し側で [`multi-session-coordination.md#staging-window-race`](multi-session-coordination.md#staging-window-race) の `git commit -- <path>` を使うと **hook が見る範囲が自分の path だけになり**、 この巻き込み自体が起きない (= 上流での design-out)
- <a id="staged-diff-binary"></a>**`git diff --cached` を `text=True` で読まない** — git の binary 判定は「先頭 8KB に NUL があるか」 だけなので、 NUL を含まない binary (PDF など) と textconv (git-crypt 等) で平文に戻した binary は text として diff に出て、 `UnicodeDecodeError` になる。 warn-only の hook は commit を通すので、 **同じ commit の text file の検査が黙って走らない** (`--numstat` の `-\t-` でも見分けられない)。 実測: 暗号化 repo に PDF を 1 本 commit しただけで warn hook 2 本と、 fail-open 扱いの BLOCK gate 1 本が落ちた
  - **warn 検査** = [`scripts/lib/staged_diff.py`](../scripts/lib/staged_diff.py) の `staged_added_lines()` (bytes で受けて file ごとに厳密 decode。 既知の binary 拡張子と NUL 入りは飛ばし、 UTF-8 → cp932 の順に読めた file は読む = Shift_JIS の旧来 text も検査に残る。 textconv は残す)。 binary は検査の対象外であって「読めない入力」 ではないので、 上の 1 行報告は出さない (PDF を含む commit のたびに出る報告は壁紙になる)
  - **BLOCK gate** = `encoding="utf-8", errors="replace"` で全部読む (binary に平文で残った語も止める側に倒す。 例 = `check-confidential-leak.py` / `check-activity-facts.py`)
  - どちらも `--selftest` に「一時 repo に binary + trigger を含む text を stage して、 検出が出る」 case を置く (run-all-checks が自動で拾うので、 読み方が退行すると CI が落ちる)
- <a id="blob-read-git-crypt"></a>**staged / commit の blob を `git show :<path>` / `git show <rev>:<path>` で読まない** — blob がそのまま返るので、 git-crypt で暗号化される path では暗号文 (先頭 `\0GITCRYPT`) になり、 検査は binary として飛ばすか別物として読み、 **暗号化が既定の repo では中身を見ずに通す** (実測: 行頭 conflict marker の gate が素通りした / markdown link 検査が段数ずれを見逃した / baseline 比較が `UnicodeDecodeError` で落ちた)。 **Python は [`scripts/lib/git_blob.py`](../scripts/lib/git_blob.py) の `read_blob()` / `read_blob_text()`** (`git cat-file --filters` = smudge を通す、 失敗なら `git show` に戻す、 LFS は取りに行かない)、 **bash は [`scripts/lib/staged-conflict-markers.sh`](../scripts/lib/staged-conflict-markers.sh) の形** (filter=git-crypt の path だけ `cat-file --filters`)。 `git diff --cached` は `diff=git-crypt` の textconv で平文になるので、 この罠は diff でなく blob を直接読む箇所にだけある ⚠️ **selftest を平文の一時 repo だけで書くと、 この誤りは test を通る** (実測: 暗号化された ledger の commit gate が、 入れた時から実 repo では全件素通りで、 平文 fixture の selftest は緑だった)。 git-crypt が無くても同じ class は作れる = 一時 repo に可逆な clean / smudge filter (`tr 'A-Za-z' 'N-ZA-Mn-za-m'` の rot13 を両方に) を `.gitattributes` で掛けると、 index の blob は clean 後の形になり `git show` は別物を返す (例 = [`scripts/lib/git_blob.py`](../scripts/lib/git_blob.py) の selftest)。 gate の selftest にこの case を 1 つ置き、 修正前の読み方で落ちることを 1 回見る。 ⚠️ rot13 の出力は UTF-8 のままなので「blob の decode で例外 → fail-open で素通り」 の型は再現しない = clean を先頭 `\0GITCRYPT\0` + 非 UTF-8 の 1 byte にした filter (smudge で外す) も置き、 fail-open の gate では判定に加えて stderr に内部エラーが出ないことも見る (例 = [`hooks/manuscript-claim-guard.test.sh`](../hooks/manuscript-claim-guard.test.sh) の git-crypt 相当の節)。 fail-open の表示に例外の `repr` を出さない (`UnicodeDecodeError` の repr は blob の bytes を丸ごと含み、 暗号文が stderr に数十 KB 出た) = 型名 + 切り詰めた `str` を 1 行で。 多数の blob は `git cat-file --batch --filters` 1 回で読む (入力は `<object> <path>` を**空白で区切る** = 空白を含む path は `-z` でも入力に書けないので 1 件ずつに残す。 実測 300 blob: 1 件ずつ 2.0 s → batch 0.02 s。 例 = [`scripts/manuscript-claim-guard.py`](../scripts/manuscript-claim-guard.py) の `prefetch_blobs()`、 batch が失敗したら 1 件ずつに戻る)。 ⚠️ **batch の header の size は filter を通す前の object の大きさ** (git-crypt の blob = 平文 + 22 byte、 CRLF 変換も同じ) で、 中身は通した後が出る = size で切ると後ろがずれる。 切った直後が改行で、 次の行が header の形かを確かめ、 合わなければその batch を捨てて 1 件ずつに戻る (実測: 暗号化の repo で承認済みの変更の hash が合わず commit が止まった。 長さを変えない filter の fixture では歯が無い = test は長さの変わる filter で) / **古い版を worktree に戻すときも同じ罠** = `git show <rev>:<path> > <path>` は暗号文で file を上書きする (以後 text として読めず、 編集の guard も止まる)。 戻すなら `git restore --source <rev> -- <path>` か `git checkout <rev> -- <path>` (smudge が通る、 実測)
- <a id="locked-engine-interpreter-rc"></a>**gate が呼ぶ engine 自体が git-crypt で暗号化される path にあるなら、 起動する前に先頭の `\0GITCRYPT` を見て飛ばす** — locked のマシンでは暗号文を interpreter に渡すことになり、 反応が版で違う (実測: CPython 3.9 は NUL で source を読み止めて **rc 0 = 何も検査せず素通り**、 3.12 以降は `SyntaxError` で **rc 1 = 「rc 1 だけ止める」 gate が無関係な commit を止める**)。 どちらも「engine の故障で commit を止めない / 黙って通さない」 の両方に反する。 engine 不在と同じ扱いで両方の block を飛ばし、 run-all-checks 側は SKIP を宣言する。 ⚠️ 配線 test は手元の python の版で結果が変わるので、 **常に rc 1 を返す偽の `python3` を PATH の先頭に置き、 暗号文の engine を偽の HOME に置いて** 「走らせない」 を版に依らず確かめる (修正前の hook で落ちることを 1 回見る)。 ⚠️ Claude が Bash tool で `head -c 9 <file> | grep -q GITCRYPT` と確かめると、 tool の `grep` 関数 (ugrep の `-I`) が binary 入力に一致せず **rc 1 = 「locked ではない」 と誤る** — script の中の bash (`/usr/bin/grep`) では rc 0。 手で確かめるときは `command grep -q` ([`shell-env.md#bash-tool-grep-ignores-gitignore`](shell-env.md#bash-tool-grep-ignores-gitignore))
- <a id="warn-check-crash-visible"></a>**chain から warn-only の検査を呼ぶときは `|| true` で潰さない** — 異常終了の traceback は流れて消え、 その commit で検査が走らなかったことに誰も気づかない。 **commit は止めずに、 非 0 終了なら「<検査名> が異常終了 (rc=N) — この commit では走っていない」 と 1 行出す** (確認用の `--selftest` コマンドも添える)。 test は「落ちる検査を置いた一時 HOME で chain を回し、 commit が通り 1 行が出る / 正常・不在の検査では何も出ない」 の 3 case

- <a id="mktemp-template-suffix"></a>**`mktemp` の template は X を末尾に置く** — GNU は `name-XXXXXX.md` の X を置換するが、 **BSD (macOS) は末尾の X しか置換しない**。 後ろに拡張子があると literal の名前で作られ、 1 回目は成功、 2 回目以降は「File exists」 で空の path が返り、 その先の書き込みが全部失敗する (同時に走る 2 本は同じ file を奪い合う)。 Linux の CI では再現しない。 実測: 無人の週次監査が 2 回目以降ずっと報告を書けないまま exit 1 を返していた。 拡張子が要るときは `d="$(mktemp -d)"` の中に固定名で作る。 機械 = [`scripts/check-mktemp-template.py`](../scripts/check-mktemp-template.py) (run-all-checks から。 `--root` で複数 repo を横断)

### <a id="set-e-test-failure-report"></a>§0 補足 5: `set -e` の test は落ちた行を自己申告させる — 無言の exit 1 は CI log に test 名しか残さない

**罠**: `set -euo pipefail` の test で bare な `[ ... ]` / `grep -q` を assertion にすると、 落ちた瞬間に**何も言わずに exit 1** する。 集計 runner (`scripts/run-all-checks.sh`) は test 名しか出さないので、 CI log には `✗ test: <name>` だけが残り、 どの assertion が落ちたか読めない。

**実例 (2026-09-01〜09-11)**: `setup-codex.test.sh` に足された BSD 専用の `[ "$(stat -f '%Lp' F)" = "600" ]` が ubuntu runner で落ちた (GNU では `-f` = filesystem 照会で、 `%Lp` は file 名として扱われる)。 red は初回の push から CI に出ていたが、 main の checks は **push 225 回連続で red** のまま 10 日続いた。 macOS では通るので owner の手元は緑 (= §0 補足 2 / 3 と同じく CI だけが露出させる class)、 しかも log に行が出ないので原因の特定が遅れた。

**規律**:

- bare assertion を書く `set -e` の test は [`scripts/lib/test-err-trap.sh`](../scripts/lib/test-err-trap.sh) を source する (`set -euo pipefail` の後、 最初の assertion より前)。 落ちると stderr に 1 行 — `<test>: FAIL at line <N>: <command の 1 行目>`、 関数の中なら `FAIL at line <呼び出し行> (in run_setup): <command>`。 exit status は変えない。 挙動は `test-err-trap.test.sh` が CI の bash で固定している
- 自前の `assert` 関数や PASS/FAIL 集計で失敗を名指す test (hooks/*.test.sh の大半) は対象外 — 既に自己申告している
- 期待どおりの失敗は `if cmd; then echo "expected ..." >&2; exit 1; fi` の形で書く (if 条件の中は trap の対象外なので誤報しない)
- **BSD/GNU 差は push 前に手元で潰す**: [`scripts/with-gnu-userland.sh`](../scripts/with-gnu-userland.sh) `bash scripts/<name>.test.sh` (`--clean-env` で HOME を空にし、 git の system config も読ませない)。 `--clean-env` は pip `--user` の site-packages も隠すので、 python の selftest を含む一式ではなく shell test 単体に使う。 Homebrew の GNU 版 (`<prefix>/opt/<pkg>/libexec/gnubin`) だけを PATH 先頭に差し、 python3 などは動かさない ([`debugging-discipline.md#one-variable-per-arm`](debugging-discipline.md#one-variable-per-arm))。 `uname` で BSD/GNU を選ぶ script は macOS 上では BSD 側を選ぶので、 この wrapper では GNU 側の分岐を試せない — そこは CI が唯一の検証
- **test で作る git repo は branch 名を明示する** (`git init -b main`、 または clone 直後に `git symbolic-ref HEAD refs/heads/main`)。 macOS の Apple Git (2.39.5 で実測) は system config で `init.defaultBranch=main` を持ち、 HOME を空にしても `main` になるが、 CI の ubuntu の git は `master` になる。 手元で CI 側の既定を再現するなら `GIT_CONFIG_NOSYSTEM=1` (`--clean-env` は付ける)。 実例 (2026-09-11): `codex-hooks.test.sh` の `git branch --set-upstream-to=origin/main main` が CI でだけ落ちて main が 12 push 連続 red — 本 helper が CI log で初めて名指した失敗 (`codex-hooks.test.sh: FAIL at line 136: ...`)。 `--clean-env` は当初 system config を読んでいたので、 この test を手元で緑と誤判定していた

**ERR trap の実測** (bash 3.2.57 = macOS の `/bin/bash`、 5.3.9 = Homebrew。 CI の 5.2.21 では self-test が通ることを確認):

| 状況 | bash 3.2 | bash 5.x | helper の扱い |
|---|---|---|---|
| 関数の中で失敗 (`set -E` なし) | trap が動かず無言で exit | 同左 | `set -E` を立てる |
| `[ "$(cmd)" = x ]` の cmd が失敗 (`set -E` あり) | command により 1〜2 回 | subshell 側と外側で 2 回 | `BASH_SUBSHELL > 0` では出さない |
| 関数の中の失敗の `$LINENO` | **関数定義の行** | 失敗した行 | 行は出さず、 呼び出し行 (`BASH_LINENO`) と関数名を出す |
| top-level の `if` / `while` / `for` の本体で失敗 | その複合 command の末尾行 (`for` は先頭行) | 失敗した行 | command 文字列で特定できる |
| 複数行の command (継続行・heredoc) | 末尾の行 | 先頭の行 | 1 行目だけ出して ` ...` を付ける |
| top-level の `( ... )` の中で失敗 | **親の trap が動かず無言** | 親で出る | 既知の穴 (該当する test は無い) |
| if 条件・`&&` `\|\|`・`!` の中 (そこから呼んだ関数の中も) | 動かない | 動かない | — (期待どおりの失敗を誤報しない) |
| pipeline の失敗 (`pipefail`) | `$BASH_COMMAND` は最後の要素 | 同左 | 行番号は正しい |
| trap の後の exit status | 元の値のまま | 同左 | — |

**一般則**: 集計する側が名前しか出さないなら、 **失敗の中身を名指すのは test 自身の責務** (= `run-all-checks.sh` header の「SKIP 理由は test 自身が出力する」 と同じ契約の失敗版)。 無言の失敗は「どこかが赤い」 以上の情報を運ばないので、 直す人が原因を掘り直すことになる。

### <a id="replay-real-tool-output"></a>§0 補足 5b: 新しい hook の test — 件数が 0 でも通る集計にしない、 合成の入力に加えて実際の tool の出力も流す

- **集計の関数を pipeline の右に置くと、 数えた値が消えて 0 件のまま通る** — `make_input … | check …` と書くと、 `check` は subshell で走り、 中で足した `pass` / `fail` は親に戻らない。 最後の `[ "$fail" = 0 ]` は 0 件でも真になり、 test は何も確かめずに exit 0 で終わる (実測: `pass=0 fail=0` と出て成功で終わった)。 入力は引数で渡すか (`check <label> <期待> "$(make_input …)"`)、 `check … < <(make_input …)` にする。 末尾で走った件数も確かめる (例 = `[ "$pass" -gt 0 ]`)。 関連 = 書き手の SIGPIPE で exit code が化ける形 ([§0 補足 10](#hook-stdin-pipe-sigpipe))
- **PostToolUse の hook は、 会話記録にある実際の tool の結果を入力に組んで流す** — 合成の入力は書いた人の想定どおりの形になり、 想定の外の行 (本文の中の header と同じ形の行、 content block の配列、 前置きの文) を持たない。 実測: 合成の入力の test は全部通ったのに、 実際の出力では本文の行に引っかかって黙る hook だった。 道具 = [`scripts/transcript-tool-calls.py`](../scripts/transcript-tool-calls.py) `<session id> --tool '<tool 名の正規表現>'` (PostToolUse の入力と同じ形の JSON を出す、 `--list` でどれを流すか選ぶ)。 出力は会話記録の中身なので一時 dir に置き、 test の fixture には写さない (fixture は合成で、 実際の出力で見つかった形を合成で書き直して足す)
- **hook の file の冒頭 comment の 1 行目 (`# <name> — <説明>`) の説明が `hooks/README.md` の説明欄になる** — 何をするか (どの tool の何を見て、 何を出すか) を書く。 「PostToolUse hook (layer 1)」 のような種類だけの説明は、 索引から用途が読めない (実測)

### <a id="test-root-not-parent-dir"></a>§0 補足 6: test は自分の repo を「checkout の親 dir」 経由で指さない — worktree で落ち、 live を検査する

**罠**: hook / script が `$ROOT/<repo>/...` を組み立てる設計 (ROOT = 正規 layout の base、 既定 `~/Claude`) で、 test が ROOT に「test を含む checkout の親」 (`$(dirname "$0")/../..`) を渡す。 checkout の dir 名が repo 名と違う所 (= `git worktree add <tmp>` の置き場所) では payload が見つからず、 fail-open の hook が黙って exit 0 → 出力が空で test が落ちる。 **dir 名が一致しても**、 その親に別の checkout (= live tree) が居れば test は live の script を検査し、 変更中の copy を検査しない。 ROOT を渡さず `$HOME/<base>` に fallback させる test も同じく live を読む。

python の shim が兄弟 repo (層1 engine 等) を `Path(__file__).resolve().parents[N]` で探すのも同型で、 こちらは**落ちずに空振りする**: `resolve()` 後の親は worktree でも CI (`/home/runner/work/<repo>`) でも base ではないので、 engine 不在の fail-open で selftest が**何も検査せずに PASS** する。

**規律**:

- test は一時 dir に `<repo 名> -> <この checkout の実 path>` の symlink を 1 本置き、 それを ROOT に渡す (helper 1 本にまとめる。 例 = odakin-prefs `hooks/lib-test-root.sh` の `make_test_root`)。 兄弟 repo が要る test は fixture をその root の下に作る
- 兄弟 repo は正規 layout (`Path.home() / "<base>"`) か明示の `--root` で引く。 CI は正規 layout を再現してから検査を回す = **base dir を checkout の親 dir への symlink にし、 依存 repo をその中 (= checkout の隣) に clone する**。 base dir に自 repo だけを symlink する形では、 `resolve()` で自分の実体から兄弟を引く code (`<repo>/../<依存 repo>`) に依存 repo が見えず、 依存 repo の lib / engine を読む検査がまとめて落ちる (実測)。 どちらの引き方の code も同じ実体に着く形にする
- 依存が**無い**ので検査できないなら selftest は `SKIP: <理由>` を出して exit 0 (= §0 補足 5 と同じく黙って通らない)。 依存が**在るのに壊れている**なら FAIL のまま = SKIP の条件は不在そのものに絞る (例: 依存 repo が未 clone = SKIP / repo は在るのに読む dir が無い = FAIL、 暗号化の鍵が無い機械で暗号のまま = SKIP / 鍵が在るのに暗号のまま = FAIL、 履歴を要る検査が浅い clone の上 = SKIP)。 条件を広く取ると、 実機の配線切れまで「検査不能」 に化ける。 通常実行 (dashboard 等の消費側) の fail-open は沈黙のままでよい
- **test root を渡しても、 hook が呼ぶ module が別の root 変数か `Path.home()` から兄弟 repo の data を引くと live を読む** — その module の root も fixture に向ける (実測: 予定の重なりを出す module が自分の env で base を引き、 兄弟 repo の無い CI では「data が無い = 未チェック」 の 1 行を足して、 沈黙を期待する test を落とした。 手元では本物の data で通るので気づけない)
- **editable install した venv も live を向く**: `pip install -e` の finder は通常の path 探索の後ろに入るので、 cwd (= `sys.path` の先頭) が package の親 dir でない限り、 worktree で回した test も live の tree の package を import する (2026-09-12 実測: 同じ venv の python で、 cwd = package の親なら worktree の copy、 repo root なら live の copy)。 worktree では package の親 dir から回すか、 `PYTHONPATH=<worktree 側の package の親>` を付ける
- **test が変更中の copy を見ているかは mutation で確かめる**: worktree 側だけ payload を退避する / lib に偽の関数を足す → 落ちれば変更中の copy を検査している。 「worktree で PASS」 だけでは証明にならない (live を読んで通っている可能性が残る)

**実例 (2026-09-12)**: odakin-prefs の SessionStart hook test 6 本が使い捨て worktree でだけ落ちた (payload 不在)。 同じ前提の test がさらに 4 本、 worktree でも通っていたが live の `lib-surface.sh` を source していた。 python の shim 2 本は worktree だけでなく **CI でも**空振りしていた。 層1 でも、 stub installer の test が `$HOME` の外に置いた worktree でだけ落ちた (`"$HOME/..."` 形と絶対 path 形が同じ文字列になり、 fixture が差分を作れない) — 置き場所への依存は root の導き方以外からも入る。 並列 session を避ける worktree 運用 ([multi-session-coordination.md#foreign-wip-scratch-worktree](multi-session-coordination.md#foreign-wip-scratch-worktree)) を使って初めて露出した class。

### <a id="surface-filter-keeps-errors"></a>§0 補足 7: 自動適用の出力を絞って surface する hook は、 stderr を合流させてエラーの行も拾う

SessionStart 等で installer / 同期 script を回し、 その出力を `grep` で絞って「何をしたか」 だけを注入する hook は、 **成功の行だけを拾い stderr を捨てると、 失敗が「何もしなかった」 と同じ見え方になる**。 script は spec の誤りを 1 行の ERROR として stderr に出すのが普通なので、 `2>/dev/null` の時点で唯一の信号が消える (実測: 読めない設定のまま登録されず、 session 開始時には何も出なかった)。

- 起動は `2>&1` で合流させ、 拾う正規表現に `ERROR` / `WARN` を入れる。 複数の wrapper を回すなら正規表現は 1 か所に置く
- 見出しを「追加した」 だけにしない (= エラーの行が成功の見出しの下に並ぶと読み違える)。 「追加 / 更新 / 要対応」 のように書く
- test は偽の wrapper で、 更新の行・stderr の ERROR・拾わない雑音の行を出し、 前 2 つが surface され雑音が出ないことを見る。 旧版に当てて落ちることも確かめる (= 歯)

### <a id="fake-platform-commands-in-path"></a>§0 補足 8: macOS 専用の installer は偽の platform command を PATH の先頭に置いて test する

`launchctl` や `uname` の判定を持つ installer は、 そのままだと Linux の CI で `[skip]` に落ちて何も検査されない。 偽物を PATH の先頭に置くと install の流れを丸ごと通せる。

- `uname` = `Darwin` を返すだけ。 `launchctl` = 一時 dir に file を置いて `bootstrap` / `bootout` / `print` を模す (「実行中」 などの状態も file の有無で出し分ける)
- ⚠️ **本物に触らないことを test の冒頭で確かめる**: `command -v launchctl` が偽物でなければ中止する。 書き先 (plist dir・log dir・state dir) は env の override で一時 dir に向ける
- 「定常状態では X を起動しない」 は、 X (例: `python3`) を「起動したら印を残して失敗する偽物」 に差し替えて証明する。 時間の計測より確実で、 CI の揺れにも強い
- engine を `sh` で起動すると CI では dash で回る = POSIX の検査を兼ねる。 ただし bash 3.2 固有の癖 ([置換の中の `case`](#bash32-case-in-command-substitution)) は macOS の `/bin/sh` で回すまで見えないので、 手元でも回す
- 実機に効く自動移行 (登録済みの物を書き換える等) は、 出荷前に**実機の状態の写し**を一時 dir に置き、 同じ偽物で 1 回再現する。 変わるのが想定した物だけで、 2 回目が無言なことを見る ([`debugging-discipline.md#violation-e2e-on-a-copy`](debugging-discipline.md#violation-e2e-on-a-copy) と同じ「複製で試す」)

### <a id="exec-probe-test-techniques"></a>§0 補足 9: exec の可否を本体を走らせずに調べる・OS の kill を test で再現する・旧版で歯を確かめる

hook や installer が「この file は exec できるか」 を見る必要があるとき (macOS の exec kill = [`macos-exec-policy-kill.md`](macos-exec-policy-kill.md)) の技法。

- **本体を走らせない検査**: bash は非対話で script を起動すると 1 行目より前に `$BASH_ENV` を読む。 `exit 0` だけの file を渡すと、 exec が通るかだけが分かる (137 = SIGKILL)。 `#!/bin/sh` は読まないので対象外
- **`$BASH_ENV` の中では `$0` は `bash`** (script の path ではない)。 path が要るなら `set -- $(ps -ww -o args= -p $$)` の `$2` (shebang 経由の起動は `bash <path>` の形で残る)
- **OS の kill を test で再現する**: 偽の `$BASH_ENV` に「`ls -iL` で出した inode が一覧にあれば `kill -9 $$`」 を書く。 inode ごとに判定を覚える挙動がそのまま再現でき、 Linux の CI でも同じ経路を通る。 「作り直しても直らない」 場合は path の一覧で kill する (例 = `scripts/install-hook-stubs.test.sh` の冒頭)。 ⚠️ **印を付けた inode は hard link で控えを取って生かす**: Linux の fs (ext4) は空いた inode 番号をすぐ再利用するので、 作り直しで空いた番号が次の一時 file に付き、 別の file の判定を引き継ぐ (2026-09-22 CI の T13 / T17 で実測。 APFS は再利用しないので macOS の手元では出ない)
- **bash の `Killed: 9` の表示**は、 kill された子を待っている側の shell が出す。 検査の出力を汚さないなら `{ cmd; } 2>/dev/null` で囲む (cmd 自体の redirect では消えない)
- **旧版で歯を確かめるのに stash を使わない**: 並列 session や SessionStart の自動 pull (stash → ff → pop) とぶつかる。 `git archive HEAD scripts | tar -x -C <tmp>` で旧版を一時 dir に展開し、 新しい test だけ上書きして回す (新しい確認が旧版で落ち、 新版で通るのを見る)。 test が兄弟 file (設定・偽物の置き場) に頼るなら、 その分の無関係な失敗は数から除いて報告する
- **commit せずに hook を git と同じ呼び方で走らせる**: `git hook run <name> -- <引数>` (git 2.36 以降。 `core.hooksPath` を反映)。 prepare-commit-msg なら一時の message file と `message` を渡す。 ⚠️ pre-commit は index に対する本物の検査が走る
- <a id="fixture-keeps-incident-shape"></a>**検出器の test の再現例は、 起点の実例の形を保つ。 通ったら実物に 1 回流す**: 合成の fixture は名前を短く・きれいにしがちで、 そのとき実例の決め手 (空白・丸括弧・Unicode の正規化・長さ) が落ちる。 旧版で落ち新版で通る歯があっても、 実例では効かない (実測 = file 名に空白と丸括弧のある実物で、 検出器の示す直し方がそのままでは開けない形だった。 test の例は記号の無い短い名前だった)。 起点の実物 (file・会話記録の発話) が手元にあるなら、 完成した検出器をそれに当て、 出た診断どおりに直して解決するかまで見る

### <a id="hook-stdin-pipe-sigpipe"></a>§0 補足 10: hook に stdin を pipe で渡す test は、 書き手の死に方を hook の判定として読む (`pipefail` × SIGPIPE = 141)

**罠**: `printf '<JSON>' | bash hook.sh; echo $?` は、 hook が **stdin を読まずに exit する経路**で嘘の値を返す。 hook 側で stdin を読まない経路は普通に在る — 無効化の env switch、 安価な前段の filter (tool 名・path で先に落とす)、 引数だけで決まる早期 return。 その時 hook が閉じた読み口へ書いた `printf` が **SIGPIPE で死に**、 `set -o pipefail` の下では pipeline の exit code が書き手の 141 になる。 test は hook の判定 (0 = 通す / 2 = 止める) を見ているつもりで、 **書き手の死に方**を見る。

- 症状の形: hook 単体を手で叩くと期待どおりなのに、 test だけが落ちる / 「無効化した時は通す」 の 1 件だけが 141 で落ちる / stderr は空。
- **`stdout` と `exit code` で症状が分かれる**: stdout を取る helper (`$(...)`) は書き手の死が出力に出ないので通り、 exit code を取る helper だけが落ちる = 「同じ入力で片方の test だけ落ちる」 の指紋。
- **直し方**: 書き手を pipeline の外に出す。 `bash hook.sh < <(payload)` (process substitution) なら `printf` は pipeline の要素ではないので、 その死は pipeline の rc に混ざらない。 payload を 1 度だけ file に書いて `< "$f"` で渡すのも同じ効果 (bash 3.2 でも動く)。
- hook を**書く側**の対処 = 早期 return の前に stdin を捨てる (`cat >/dev/null 2>&1 || true`) 手もあるが、 無効化の経路まで入力を読むのは本末転倒 (= 止めたい処理の手前で読む)。 **呼ぶ側を直すのが既定**。
- 一般則としては [§0 補足 2](#substitution-fallback-stdout-mixing) の「見かけの exit code を信用しない」 族の第 3 形: 補足 2 = fallback chain が前段の stdout を混ぜる / 同節の兄弟形 = `cmd | sed` が **後段**の rc を見る / 本節 = `writer | hook` が **前段**の rc を見る。 pipeline を挟んだら「その rc は誰のものか」 を毎回問う。
- **逆向きの形 = hook が stdin を読み切るのに、 test が stdin を渡さずに呼ぶ**: 書き手の EPIPE を避けるために入力を最後まで読む hook (SessionStart 等) を、 test の helper が stdin を指定せずに呼ぶと、 呼び元の stdin を継ぐ。 それが閉じない non-tty (agent の shell の socket 等) だと hook は入力待ちで止まり、 test 全体が timeout まで返らない (手元の terminal は tty なので、 `isatty` で読みを飛ばす実装では再現しない)。 **直し方**: helper で必ず `</dev/null` か payload を渡す。 hook 側で読むのをやめるのは上の EPIPE 対策を壊すので既定にしない。

origin: 印刷の gate hook の test で、 無効化の env switch を立てた 1 件だけが 141 で落ちた (実測)。 hook は switch を見て stdin を読まずに exit しており、 test の `printf` が SIGPIPE で死んでいた。 逆向きの形も実測 = SessionStart の生存確認 hook の test が、 agent の shell から回した時だけ止まった。

---

### <a id="test-isolates-live-machine-state"></a>§0 補足 11: test は、 本番の run と共有する machine-global な資源を自分専用にする

- Stop / SessionStart hook は、 同じ機械の全 session で毎 turn 裏で走る。 engine が tempdir の lock・state dir・cache のような machine-global な資源を使うとき、 test が同じ資源を使うと、 **本番の run と重なった回だけ落ちる** (engine は lock を見て黙って退き、 test は「写っていない」 で落ちる)。 単独で何度回しても通るので flaky に見える ([`debugging-discipline.md#flaky-is-a-symptom`](debugging-discipline.md#flaky-is-a-symptom) の (d) 資源)
- 対策: `.test.sh` の冒頭で `export TMPDIR="$TMP"` とし、 state dir の env も使い捨ての dir に向ける。 engine の `--selftest` も `tempfile.tempdir` を selftest 用の dir に差し替える。 確かめ方 = 本番の lock を手で作った状態で test を回し、 緑になること
- **hook が人や別の process に向けて書く出力 file も同じ資源** (session の冒頭に読む一覧、 通知の見張りが読む file): 書き先を test で差し替えないと、 test が走るたびに fixture の行が本物を上書きする (実測: 一覧の file が test の 1 行になり、 次の定時の書き直しまでそのまま読まれていた)。 対策 = 共通の test helper が、 書き先の env が未指定なら test の一時 dir に向ける (test が自分で向けていればそれを使う)。 回帰の検査 = 「出力 file を書く hook の test が、 書き先を指定するか helper を読み込んでいるか」 を静的に見る test を 1 本置く (新しい hook の test が helper を使わずに書かれても落ちる)
- **本番の状態を変える command も同じ資源** (定期 job の設定の書き換え、 台帳の commit + push): hook の段がこうした command を呼ぶなら、 test の既定でその command・対象の file・判定の gate を偽物か一時 dir に向ける (env を 1 つ指定し忘れた test が、 本物の台帳を書き換えて push しうる)。
- <a id="live-hook-edit-runs-elsewhere"></a>**書いている途中の hook も、 同じ機械の別の session が走らせる**: session 開始・turn ごとの hook は、 その機械で次に始まる session が作業 tree の file をそのまま読む。 本番の状態を変える段 (上の行) を持つ hook をその場で何回にも分けて書き換えると、 試験が済む前の版が別の session の開始で走る (実測: 書きかけの段が別の session の開始で走り、 本番の定期 job の設定の差し替えと台帳の commit + push まで行った)。 直し方は定期 job の script と同じ = 別の場所で作って試し、 同じ dir から rename で入れる ([`scheduled-tasks.md#live-script-replace`](scheduled-tasks.md#live-script-replace))。 その場で直したなら、 直している間に他の session が始まっていないか (本番の状態が変わっていないか) を commit の前に確かめる。 **git の pre-commit・commit-msg の連鎖が呼ぶ engine も同じ** = 同じ機械の全 repo の commit が作業 tree の file を読む (実測: 検査の engine を Edit で何回かに分けて直している途中、 読む側と受ける側の形が食い違った数分間に別の session の commit が走り、 検査が異常終了した。 fail-open なので commit は通り、 その commit は検査されなかった)。 1 回の Write で全文を置き換えるか、 上の rename で入れる。 機械 = [`hooks/live-engine-edit-guard.py`](../hooks/live-engine-edit-guard.py) (settings の hook と git hook から辿った一覧 = [`scripts/live-engine-paths.py`](../scripts/live-engine-paths.py) にある file を、 session で初めて Edit するとき止め、 止めた Edit の中身を控える。 1 か所の直しなら同じ Edit を打ち直す = 控えた中身と同じ再送だけが通り、 その file は以後止まらない。 **再送の前に来た同じ file への別の Edit は止め続ける** = 同じ message に並べた 2 本目以降も止まる。 止めた後に file が写しからの `mv -f` などで変われば、 控えを捨てて次の Edit を改めて止める)。 2026-10-21 までは止めるのが初めての 1 本だけで、 同じ file への Edit を 1 つの message に並べると 2 本目以降が通り、 前の段を欠いた途中の形の file が作業 tree に残った (実測 2 回: 引数を 1 つ増やす呼び出し側だけが入り、 受ける側の関数が古いままになった)。 2 か所以上を直すなら、 初めから `.wip` の写しに重ねて `mv -f` で入れる。 写しを試すときは、 一時 dir に wrapper・写し (本来の file 名に戻して)・test を並べて回す (test は自分の dir の wrapper を呼び、 wrapper は隣の本体を読む形なら、 そのまま写しを試せる)。 写しを module として読み込む校正の script は、 `.wip` の拡張子では `importlib.util.spec_from_file_location` が None を返すので `importlib.machinery.SourceFileLoader` で読む (実測)。 互いに import し合う file を何本か入れるときは、 呼ばれる側 (新しい名前を持つ module) から rename で入れる (逆の順では、 その間に走った別の session が無い名前で落ちる)。 dir を一時 dir に写して試すと隣の dir が無いので、 `../` を読む selftest は写しの中では落ちる = それは本体に入れた後に本体の tree で回す (実測)。
- <a id="cleanup-own-pids"></a>**process も同じ資源**: test や手元の検証の後片付けで process を止めるときは、 起動したときに控えた pid (pid file・`Popen` の pid・`$!`) だけを止める。 `pkill -f '<形>'` / `killall <名前>` は、 並列の session や本番の run が同じ形で動かしている process も止める (実測: 検証の後片付けで `sleep` の形の pkill を打ち、 他の session の process を巻き込んだかを後から確かめられなかった)。 偽の process を test に使うなら、 偽の process 自身に pid を file へ書かせて、 その pid で止める (実装例 = [`scripts/html-print-pdf.py`](../scripts/html-print-pdf.py) の selftest)。 GUI app の場合 = [`macos-gui-app-automation.md`](macos-gui-app-automation.md) 冒頭
- lock の書き方: **取れずに退く判定を `try:` の中に置かない** — `finally:` の unlink が他の run の lock を消し、 次の起動と 2 本が並走する。 退く判定は `try` の前に置き、 取得は `os.open(..., O_CREAT | O_EXCL)` で行う (実装例 = [`scripts/sync-built-pdfs.py`](../scripts/sync-built-pdfs.py) の `take_lock`)

### <a id="hook-cost-per-item"></a>§0 補足 12: hook の処理時間を入力の件数に比例させない — 件ごとに外部 process を呼ばない

- PreToolUse hook には settings の `timeout` (秒) がある。 commit・一括編集の検査で**件ごとに git を呼ぶ** (1 件ずつ pathspec を展開し直す、 1 file ずつ `git show` / `cat-file` / `ls-tree` する) と、 数百件で timeout を越える (実測: 1 件あたり git 約 5 回で、 数千 file の dir の commit が timeout の数倍かかった。 対象外として読み飛ばす binary の file も、 展開の段で同じだけ払っていた)
- 書き方: 集合は 1 回で聞く — pathspec はまとめて 1 回展開し、 既に具体名になった file は展開し直さない。 中身は `git cat-file --batch` や、 path をまとめた `git ls-tree` の 1 回で読む。 件数に比例してよいのは python の中の処理だけ
- 測り方: `cProfile` で `subprocess.run` の呼び出し回数を件数で割る (件数に比例していたら直す)。 旧版との比較は、 旧版を別名で置いて同じ入力を当てる ([`debugging-discipline.md#performance-fix-discipline`](debugging-discipline.md#performance-fix-discipline))
- timeout を越えたとき hook が止める側に倒れるか素通りするかは、 推測で書かずに実測して、 その gate の doc に書く (どちらでも利用者には誤動作に見える)

### <a id="pretooluse-timeout-fail-open"></a>§0 補足 13: PreToolUse hook の timeout 超過は素通り (実測) — 測り方と、 hook file が読み込みで死ぬ場合も同じ

- **実測 (Claude Code CLI 2.1.198、 2026-09-22)**: project settings に「4 秒待ってから deny の JSON を返す」 PreToolUse hook を `timeout: 1` で置くと、 tool (`touch`) は実行された。 `timeout: 10` なら止まった。 desktop の埋込 engine 2.1.275 の hook runner も、 打ち切り (abort) を `status 1・stdout なし・aborted` に畳む同じ経路 (= exit 1 の非 block 扱い)。 公式 docs は timeout の既定 (600 s、 prompt hook 30 s、 agent hook 60 s) と「cancel する」 までしか書かず、 通るか止まるかを書いていない。 §0 補足 12 の「timeout を越えたときの挙動は実測して gate の doc に書く」 の答え = **素通り**。 Codex の hook は未測定。
- **測り方** (headless 1 往復 × 2、 auth を消費する): 一時 dir に `.claude/settings.json` (matcher `Bash`、 command = `sleep 4; printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"late deny"}}'`、 `timeout` を 1 と 10 の 2 通り) を置き、 `CLAUDE_CONFIG_DIR=<login 済みの config dir> claude -p "Run exactly this shell command and nothing else, then reply done: touch <marker>" --model haiku --setting-sources project --allowedTools "Bash(touch:*)" --max-turns 3 </dev/null` を走らせ、 marker file の有無を見る。 **`--setting-sources project` で user 層の hook を全部外す**ので、 本番の hook・state・surface に副作用が無い。 対照 (timeout 10 = 止まる) を必ず一緒に見る (= deny の JSON 自体が効いていることの陽性対照)。 既定の `~/.claude` が login していない machine では `auth status` が `loggedIn: true` かつ `authMethod: claude.ai` の config dir を使う。
- **帰結**: (1) 件数に比例する検査は timeout で黙って通る (§0 補足 12)。 (2) **hook file が読み込みの段階で例外を出しても同じ** — deny JSON を出す `try` の外なので出力なし = 素通り。 実測: macOS の `/usr/bin/python3` (3.9) で `def f() -> dict | None:` を `from __future__ import annotations` 無しに書いた hook が import で `TypeError` になり、 全 Edit / commit が素通りした (test の fixture が全部 `none` になって気づいた。 canary も NOT ARMED を出す)。 hook file の python は 3.9 の文法で書き、 型注釈に `|` を使うなら future import を先頭に置く。 (3) 素通りは配線の監査 (symlink・settings の entry) では見えず、 **合成例を流して deny を確かめる canary** でしか見えない (= 配線の生存を state に残す canary の向き、 [`agent-rule-ownership.md#wiring-scope`](agent-rule-ownership.md#wiring-scope))。

### <a id="hook-git-env-cross-repo"></a>§0 補足 14: hook から別 repo に git を打つときは `GIT_INDEX_FILE` を外す

- **罠**: git は hook に `GIT_INDEX_FILE` を渡す。 `git commit -- <path>` や `commit -a` の中では**一時 index の絶対 path** が入る。 hook の中から `git -C <別 repo> diff --cached` を打つと、 その環境変数が効いて**別 repo が commit 中の repo の index を読む**。 別 repo に無い file が全部「新規追加」 に見える。
- **実測**: 全 repo の pre-commit から呼ばれる個人層の検査が、 既定で特定の 1 repo を見る作りだった。 他の repo で path 指定の commit をすると、 その repo にしか無い script を「新規」 と誤判定し、 commit を止めた (普通の `git add` + `commit` では `GIT_INDEX_FILE` が相対 path で、 たまたま正しい index を指すので出ない = 気づきにくい)。
- **直し方**: (1) 別 repo を見る検査は、 commit している repo がその repo のときだけ回す (`git rev-parse --show-toplevel` を比べる)。 (2) 本当に別 repo を読むなら、 子 process の env から `GIT_INDEX_FILE` / `GIT_DIR` / `GIT_WORK_TREE` / `GIT_OBJECT_DIRECTORY` を外す。 **再現** = 別 repo の index の path を `GIT_INDEX_FILE` に入れて、 対象 repo で `git diff --cached --name-only` を打つ。

### <a id="tmp-path-not-absence-marker"></a>§0 補足 12: test の一時 dir の path を「無いこと」 の印にしない — Linux の `mktemp -d` は `/tmp` の下

- 「旧版の `/tmp/…` の path が残っていない」 を確かめるのに `! grep -q /tmp/ "$file"` と書くと、 macOS (一時 dir = `/var/folders/…`) では通り、 Linux の CI (一時 dir = `/tmp/tmp.XXXX`) では、 test が作った正しい path 自体が `/tmp/` を含むので常に落ちる (実測)。 消えたはずの**値そのもの** (例 `<string>/tmp/old.log</string>`) を `grep -qF` で見る。
- test の中で file を書き換えるときも `sed -i ''` (BSD) / `sed -i` (GNU) の差で片方が落ちる (GNU では `sed: can't read s#…` = 空の引数を script と取り、 script を file 名と取る)。 一時 file に書いて `mv` する。 push 前に GNU の挙動で回す道具 = [`scripts/with-gnu-userland.sh`](../scripts/with-gnu-userland.sh) ([#set-e-test-failure-report](#set-e-test-failure-report))。

## <a id="bash32-heredoc-parser-bug"></a>§1. bash 3.2 の `$(...)` + heredoc body の quote escape parser bug

- <a id="hook-git-env-same-repo"></a>**逆向き = commit しようとしている同じ repo の staged を読む段は `GIT_INDEX_FILE` を残す**。 捨てると main の index を読み、 `git commit -- <path>` の一時 index にだけある staged を見落とし、 commit されない file を数える (実装例 = `scripts/check-history-growth.py` の `staged_warnings`、 一時 index を捨てる実装では落ちる test つき)。 1 本の script に両方の段があるなら、 git を呼ぶ関数を 2 つに分けて env の扱いを名前で区別する

### <a id="bash32-problem"></a>問題

`$(...)` command substitution 内に heredoc を置き、 heredoc body に literal `"` または `'` (= 例えば Python regex の `[\"']` パターン) を含めると、 bash 3.2 の parser が外側 `$(...)` の閉じ `)` を find する際に body 内の quote を一部 consume、 **遥か後の行 で `syntax error near unexpected token '('`** を報告する。

quoted heredoc 開始 token (`<<'PYEOF'`) は body を no-expansion にする contract のはずだが、 bash 3.2 の `$(...)` parser は **その contract を無視して body を scan する** (= 既知の bash 3.2 限界、 5.x で修正)。

### <a id="bash32-reproducer"></a>Reproducer (= 2026-05-20 実遭遇)

```bash
HEREDOC_MSG="$(
  python3 - <<'PYEOF' 2>/dev/null
import re
# このパターン内の \" \' で bash 3.2 が confusion
pat = re.compile(r"<<-?\s*[\"']?([A-Z]+)[\"']?\s*")
PYEOF
)"
```

- `bash` (homebrew 5.x): 通る
- `/bin/bash` (macOS stock 3.2.57): `syntax error near unexpected token '('` を 50〜100 行先で報告

### <a id="bash32-workaround"></a>回避策

heredoc body 内の literal quote を **hex escape で書き換える**:

```bash
pat = re.compile(r"<<-?\s*[\x22\x27]?([A-Z]+)[\x22\x27]?\s*")
#                          ↑ "          ↑ '
```

`\x22` = `"`、 `\x27` = `'`。 Python (および大半の regex engine) は同 escape を理解するので semantics 不変。 bash 3.2 parser は body 内 quote を見ないので heredoc 終端 (`PYEOF`) で正しく停止できる。

別解: 中間 file に書き出す (= `python3 -c '...'` への移行は引用問題が増えるので非推奨、 heredoc を `>/tmp/script.py` で先に書いて `python3 /tmp/script.py` で呼ぶのは clean だが手数が増える)。

### <a id="bash32-case-in-command-substitution"></a>`$(...)` の中の `case` のパターンは `(` を前置する (`-n` を通り、 実行時にだけ落ちる)

同じ bash 3.2 の `$(...)` parser の弱点の別の形。 置換の中に `case` を置き、 パターンを `a)` / `*)` と書くと、 閉じ括弧を置換の終わりと取り違える。

```sh
x="$(printf 'a\n' | while read -r v; do
  case "$v" in
    a) printf 'A' ;;      # ← bash 3.2 はここで置換が閉じたと読む
    *) printf '?' ;;
  esac
done)"
```

- **症状**: macOS の `/bin/sh` と `/bin/bash` (3.2) で、 その置換だけが `command substitution: line N: syntax error near unexpected token` を stderr に出して失敗する。 **script は止まらない**。 値は空のまま処理が進むので、 `set -u` なら離れた場所で unbound variable として見える (実測)
- **`sh -n` / `bash -n` は通る** (置換の中身は実行時に読まれる)。 bash 5・dash・zsh では起きないので、 Linux の CI は緑のまま = 手元の macOS で test を `/bin/sh` 経由で回すまで見えない
- **回避**: パターンを `(a) ...;;` / `(*) ...;;` と書く (POSIX の書き方で、 どの shell でも同じ意味)。 または `case` を関数に出し、 置換の中からは関数を呼ぶだけにする
- **検出**: 静的に拾うには shell の字句解析 (quote・入れ子・heredoc) が要り、 正規表現の近似は誤検出だらけになる (実測)。 macOS 向けの script は test を `/bin/sh` で回すのが安い網

### <a id="bash32-brace-expansion-in-cmdsub"></a>`"$(f "...")"` の中の二重引用の文字列が brace 展開される (test の入力 JSON が黙って壊れる)

同じ bash 3.2 の `$(...)` の弱点の 3 つめの形。 二重引用の置換の中で、 さらに二重引用した文字列に `{` `,` `}` が並ぶと、 bash 3.2 はその文字列を brace 展開して複数の語に割る。 引用されているのに展開される。

```sh
run() { printf '%s' "$1"; }
echo "$(run "{\"a\":1,\"b\":2}")"   # bash 3.2 → "a":1 "b":2  (bash 5 → {"a":1,"b":2})
J="{\"a\":1,\"b\":2}"; echo "$(run "$J")"   # どちらの bash でも {"a":1,"b":2}
```

- **症状**: hook の `.test.sh` で合成の JSON を `"$(run "{\"tool_name\":...}")"` の形で渡すと、 hook は JSON でない入力を受け取る。 入力が壊れたら止める側に倒す hook (fail-closed) では、 **「止まるはず」 の case が入力の壊れで止まり、 test は緑のまま** = 判定を一度も通っていない (実測。 判定を抜いた版で赤くなるかを見て初めて分かる)。
- **`bash -n` は通り、 bash 5 の CI では起きない** = macOS の `/bin/bash` で test を回す時だけ出る。
- **回避**: 入力は `printf` の関数で組む (`mk() { printf '{"tool_name":"%s","tool_input":%s}' "$1" "$2"; }`) か、 先に変数に入れてから `"$(run "$J")"` で渡す。 `$(...)` の中に引用の入れ子を書かない。
- **test の側の防御**: 止まった case は終了値だけでなく、 止めた理由の文言 (その検査が出す語) まで照合する = 入力の壊れで止まった偽の合格を拾う (一般則 = [「止まった」 は対照にならない](../docs/convention-design-principles.md#failure-exit-equals-violation-exit))。

### <a id="bash32-vs-runtime-backtick-expansion"></a>bash 3.2 parser bug と runtime backtick 展開を同じ事故にしない

どちらも「backtickを含む文面が壊れた」と見えるが、発生時点・症状・修復先が異なる。

| class | 何が起きるか | signature | 修復 |
|---|---|---|---|
| **bash 3.2 parser bug** | `$(...)` 内のquoted heredoc bodyを外側parserが誤走査し、literal quote/backtickで構文解析が壊れる | commandは開始前にsyntax error。報告行は真因より数十行後になり得る。`/bin/bash -n`で再現 | heredoc bodyのliteralをhex/`chr(...)`等へ置換、またはcommand substitution外へ分離 |
| **runtime command substitution** | double-quoted CLI argument内の `` `token` `` / `$()` をshellが正しく実行し、そのstdoutで元文字列を置換する | command自体は成功し得るが、引数・投稿・記録から文字が消える。empty backticks等がfingerprint | user-authored値はsingle quote、argv配列、またはfile/stdinで渡し、送信前validatorで欠落fingerprintを拒否 |

前者はshell実装のparser limitation、後者はshell仕様どおりの評価である。前者を「掲示板や送信先の不具合」と報告したり、後者をbash更新で直そうとしない。最初の分岐は **`bash -n` が実行前に落ちるか / commandは走ってpayloadだけ欠けたか**。 ⚠️ 例外 = [`$(...)` の中の `case`](#bash32-case-in-command-substitution) は parser bug なのに `-n` を通り、 走って値だけ欠ける。 stderr に `command substitution: ... syntax error` が出ていれば parser 側。

### <a id="bash32-debug-difficulty"></a>Debug が困難な理由 / メタ規律

- minimal isolated test (= heredoc 1 個を `$(...)` 無しで実行) は通る → 「block の中身が壊れた」 と reflex 判定しがち。 真因は **block 間 interaction** (= 外側 parser が内側 body を scan する parser bug)
- 「error 報告行」 と「真因行」 が大きく乖離する → 修正対象を誤特定して時間を溶かす

**メタ規律**: hook を書いた直後に `/bin/bash -n <hook>` で syntax check + minimal stdin で 1 回 fire 確認 (`-n` だけでは [置換の中の `case`](#bash32-case-in-command-substitution) を見逃すので、 fire 確認は省かない)。 homebrew bash で書いて満足しない。 macOS stock bash で fail する書き方を完成形と認識する事故を予防。

---

## <a id="delivery-audit-4-axes"></a>§2. hook 配信正常性の 4 軸 audit (= 1 軸欠けて silent malfunction)

### <a id="delivery-audit-problem"></a>問題

claude-code が hook を起動するには **4 軸全てが揃う必要**:

| 軸 | 配信先 / 確認方法 | 失敗時の症状 |
|---|---|---|
| (a) **symlink target 健全性** | `~/.claude/hooks/<name>.sh` が存在し target も存在 (= `[ -e <path> ]` が true) | hook spawn 即 fail。 claude-code は exit code を log するが user 通常見ない |
| (b) **settings.json entry** | `~/.claude/settings.json` の `hooks.PreToolUse[]` (または PostToolUse) に該当 command path が登録 | claude-code が hook を invoke しない。 stderr 不在で気付かない |
| (c) **logic 健全性** | realistic JSON stdin で hook 起動 + 期待出力 (= ask JSON / warn 出力 / silent) 確認 | (a)(b) OK でも logic bug で空振り、 false negative |
| (d) **harness invoke 経路の生死** | hook 先頭に trace block 投入 → 実 tool call → trace log 作成確認 | (a)(b)(c) 全 OK でも hook が起動しない silent failure (= claude-code 側の bug / settings の kill switch)。 audit-hooks.sh は (d) の自動部分 (= kill switch の settings 走査 + transcript 上の SessionStart 発火証拠、 `hook-liveness-audit.py`) まで回す。 個別 hook の trace は manual |

4 軸全て silent failure mode を持つ。 「symlink 作った」 「settings.json 直した」 「テスト書いた」 「invoke 経路も確認した」 のどれか 1〜3 つで「fix 完了」 と claim するのは error。

### <a id="delivery-audit-example"></a>実例 (= 2026-05-20 retroactive 発覚)

| 失敗 mode | 詳細 | 観測された機能停止期間 |
|---|---|---|
| (a) broken symlink | `~/.claude/hooks/google-url-guard.sh -> <non-existent path>` の状態 (= 過去の personal-layer hook 試行残骸、 target dir 不在) | **約 1 ヶ月** (link mtime から逆算)。 この間、 機械的 enforcement layer 不在 → user 規約違反の retroactive audit 対象に |
| (b) settings.json entry 欠落 | `~/.claude/hooks/expensive-tmp-guard.sh` symlink は存在、 但し `settings.json` の PreToolUse list に未登録 | 不明 (= setup.sh 直近実行時に partial 完了した可能性) |
| partial install (= §4 参照) | symlink だけ手動修復 + settings.json は手付かず → (a) 解消、 (b) は残存 | (b) 軸単独の silent malfunction が継続 |
| **(d) harness invoke 死亡 (= 2026-05-21 追加)** | claude-code 2.1.x で **`PostToolUse[Bash]` + `PreToolUse[Bash]` 両 hook が harness invoke されない** silent failure。 (a)(b)(c) 全 green、 manual invoke で hook script が正しく動作するにもかかわらず実 Bash tool call で hook が fire しない (= 他 matcher 〔Write / Read / SessionStart 等〕 は同 session で fires fine、 Bash matcher 限定) | **少なくとも 2026-05-21 朝以降** persistent (= arm64 + Intel x86_64 の異 arch + 異 macOS version 2 machine 両方で再現 + Claude.app restart 後も dead)。 Anthropic 既存 issue [#52715](https://github.com/anthropics/claude-code/issues/52715) + [#59513](https://github.com/anthropics/claude-code/issues/59513) で同症状を CLI 2.1.53 → VSCode 拡張 2.1.145 の version range で報告済。 **2026-05-26 mitigation 投入**: leak 防御に特化した workaround として **git native commit-msg hook** を `claude-config/scripts/commit-msg-leak-guard-runner.sh` (BLOCK mode) で投入、 全 public repo の `.git/hooks/commit-msg` に `install-public-commit-msg.sh` で配信。 git 層は harness を経由しないので bypass されない (= matcher logic は claude-code hook と shared library `lib/commit-msg-leak-matcher.sh` で DRY)。 Anthropic fix 完了後も BLOCK mode のほうが §5.1 single-viewpoint trap を回避するので継続維持予定。 設計詳細 (= 4 案 evaluation + Resolution + なぜ BLOCK + なぜ matcher を layer 1 + 反省) は [`DESIGN.md §2026-05-26`](../DESIGN.md) |

### <a id="delivery-audit-method"></a>防止策 / audit method

**ゲート質問** (= hook 配信を「fix した」 と claim する前):
0. **まず kill switch を疑う** ([#disableallhooks-kill-switch](#disableallhooks-kill-switch)) — `python3 scripts/hook-liveness-audit.py` (= settings 全 tier の `disableAllHooks` + root ごとの発火記録)。 root 限定の kill switch は「この frontend では効かない」 に見える (= 2026-06〜09 の「desktop は hook を honor しない」 診断の少なくとも一部はこれだった)。 frontend 差 ([§9.3](#frontend-dependent-cowork)) を疑うのはその後で、 それも前提にせずその session で測る。
1. `[ -e ~/.claude/hooks/<name>.sh ]` (= symlink target 健全?)
2. `jq -e --arg c "<name>.sh" '.hooks.PreToolUse[] | select(.hooks[]?.command | contains($c))' ~/.claude/settings.json` (= entry 存在?)
3. realistic JSON stdin で hook 起動 → 期待出力 確認 (= logic 健全?)。 realistic = harness が渡す key を全部持つ形 (`hook_event_name`・`tool_name`・`tool_input` …)。 1 本の engine が event と tool で振り分ける hook は、 `hook_event_name` の無い入力を黙って通す = 「止まらなかった」 が logic の誤りか入力の欠けかを区別できない (実測: 止めるはずの呼び出しの合成入力が exit 0 で通り、 `hook_event_name` を足すと止まった)。 合成で書くより、 会話記録の実際の呼び出しを流す方が欠けない ([#replay-real-tool-output](#replay-real-tool-output))
4. **(d) trace technique** (= 後述): hook 先頭 (shebang+1) に trace block 投入 → 任意の matching tool call → trace log 作成確認 → trace revert (= harness invoke alive?)

4 つとも yes でない限り「動く」 と claim しない。

#### (d) 軸の trace technique

hook script の shebang 直下 (= line 2 推奨、 `set -e` / 全 logic より前で「process spawn 即」 の事実を捉える) に:

```bash
{ echo "$(date '+%H:%M:%S') pid=$$ ppid=$PPID cwd=$(pwd)"; } >> /tmp/hook-trace.log 2>/dev/null
```

を追加。 任意の matching tool call (= `PostToolUse[Bash]` 軸を audit するなら任意の Bash call で OK、 `PreToolUse[Edit]` なら任意の Edit) を 1 回打つ。 直後に:

```sh
ls -la /tmp/hook-trace.log    # 存在すれば harness invoke alive、 不在なら dead
cat /tmp/hook-trace.log       # 起動時 cwd / pid も同時 audit
```

**必須 cleanup**: trace block を必ず revert (= 残置すると将来の session で /tmp に蓄積、 noise + log file 蓄積)。 manual edit を 2 段 (= 投入 → tool call → 確認 → revert) で扱う protocol が必要なので、 単発 script に閉じない。 atomic 化 (= 投入 + revert を 1 unit) する script の design plan あり (= odakin-prefs 側 plan、 layer 1 への将来 contribution として議論中、 Anthropic fix 完了後に implementation trigger)。

**audit script の現状**: `claude-config/scripts/audit-hooks.sh` は (a)(b)(c) 3 軸 + **(d) の自動部分**を回す (= `setup.sh` Step 3 後の delivery 検証 + dashboard 統合)。 (d) の自動部分 = `scripts/hook-liveness-audit.py --findings-only` (settings 全 tier の `disableAllHooks` / `allowManagedHooksOnly` + transcript 上で直近 N session 連続して SessionStart hook の発火記録が無い root、 2026-09-11 追加)。 個別 hook の invoke を確かめる上記 trace は、 投入 / revert の atomic 化が要るので manual protocol のまま。

**hook 配信 drift の根本因**: setup.sh が periodic 実行されないと、 claude-config に新 hook を commit / 既存 hook の symlink target を変更しても、 各マシンの `~/.claude/hooks/` への配信は遅延する。 対処の候補:
- (i) setup.sh を post-merge git hook で auto-run (= 既存 Step 6 で claude-config 自身の post-merge は導入済、 hook install step もここで毎回 idempotent 再実行する余地)
- (ii) dashboard に delivery 3 軸 (= (a)(b)(c)) audit を組み込み、 drift を session 開始時に surface
- (iii) hook ごとに self-test を持たせ、 hook 自身が起動時に自分の配信状態を log

setup.sh 自体は idempotent design なので (i) は実装コスト低。 但し `git pull` のたびに走るとうるさい場合あり、 trade-off は user 判断。

**実装例 (2026-09-01、 Codex integration の生成 composite で (i)+(ii) 型を landing)**: local に生成される合成 instruction file が上流 source の pull で stale になる同型問題に対し、 (i) 型 = 関係 repo の post-merge から refresh script を呼ぶ + (ii) 型 = audit script (`audit-codex-integration.sh`) が **配信済み instance** (= 各マシンの `.git/hooks/` の実体) に refresh 呼び出しが在るかを検査し、 不在なら「setup.sh を再実行」 と remediation を名指しする。 核心の教訓 3 つ:
- **template 更新 ≠ 配信**: 修正を installer の hook template に入れても、 各マシンには installer 再実行まで届かない。 audit は source (template) でなく **installed instance** を見る。
- **同一 managed 生成物に writer path が複数あるなら、 機械可読 marker を全 path で統一 + 各 path を fixture で test**: 新規作成 path と既存 hook への追記 path が別々の heredoc を持ち、 audit が grep する marker literal が片方に欠けていた (= 新規作成 path 経由のマシンだけ audit が偽 MISSING を出す潜在 bug。 検収時に足した composite fixture が発掘)。
- **実マシン状態を読む audit の test は env override で hermetic に**: audit が実 repo の hook file を読む検査は、 test 側で path override (`CLAUDE_CONFIG_POST_MERGE` 型) を渡さないとマシンの導入状態に依存して flake する。

### <a id="installer-tracked-stub"></a>installer は git が track している file を書き換えない (2026-09-12)

`core.hooksPath` を repo 内 (例: `scripts/hooks`) に向けた repo では、 hook stub が **repo の中身** (track 済み file) になる。 そこへ installer が「自分の形式」 で上書きすると、 意味が同じでも worktree が汚れ続け、 SessionStart の自動 pull (stash → ff → pop) と繰り返し衝突する (実例: repo は `"$HOME/..."` 形の stub を track、 installer は解決済みの absolute path で毎回上書き → stash pop conflict)。 規則 (実装 = `scripts/lib/hook-stub.sh`、 stub installer 3 本 + `install-precommit-bib.sh` が共有):

- **同じ runner を指す stub は書かない** (`$HOME` を展開して `-ef` で比較。 mtime も動かさない)。
- **track 済み file の内容は書かない**: 別の場所を指していても警告だけ出す (直すのは repo 側の commit)。 stub でない自前の hook も、 退避・上書きしない。
- **過去の installer が書いた差分は戻す**: track 済み stub の worktree 側が installer の書く 4 行 (shebang / header / Do not edit / exec) そのままで、 track 版の exec 先が実在するときだけ `git checkout --` で track 版に戻す (1 行でも手で足してあれば触らない)。 installer は setup.sh 実行時にしか走らないので、 既に汚れた他マシンの worktree は `scripts/heal-hook-stubs.sh <base>` を SessionStart から呼んで直す。
- **repo 内 hooksPath に置く untrack の stub は `.git/info/exclude` に載せる** (clone ごとの設定。 共有 repo の status に `??` を出し続けず、 他人の clone に無い stub を commit させない)。
- **symlink は link 先で判定する** (2026-09-16): `.git/hooks/pre-commit` → repo の track 済み hook という link は repo の中身。 link を track 判定の外に置くと、 installer の「stub を最新化」 が link 越しに track 済み file 本体を書き換える (再現済み: 旧 lib で `install-public-precommit.sh` が repo の hook を stub に置き換えた)。
- **共通 hook を全 repo に配る installer は、 自分が置いたものだけを最新化する** (2026-09-16、 setup.sh Step 6 = `scripts/install-precommit-bib.sh`)。 自分が置いたと言えるのは「自分の実体への link / 別の場所にある同名の実体への link (base を移した後の古い link) / 旧版のコピー」 だけ。 それ以外は chain の有無を表示して残す。 旧 Step 6 は link 先が自分でなければ付け替え、 通常 file は `.bak` に退避して置き換えていたので、 repo の installer が張った link (検査 gate を走らせてから共通 hook を chain する hook) も区別されず、 gate が黙って無効になっていた。 **「chain しているなら残す」 では足りない**: pre-commit-bib を chain しない repo の hook も同じく置き換えられていた (実測)。
- **repo が自前の hook を宣言していれば、 空いた slot を共通 hook で埋めない。 repo の hook も自動では有効化しない**: 宣言 = track 済みの `hooks/pre-commit` / `.githooks/pre-commit` / pre-commit に触れる `install-hooks.sh`。 空いた slot を埋めると、 新しい clone で repo の hook が入らないまま気づかれない。 逆に installer が repo の hook を張ると、 共同研究者が push できる code を clone ごとの同意 (repo の installer を走らせること) なしに git hook にする。 → finding として repo 側の入れ方を出し、 直るまで毎 session 出す (`install-precommit-bib.sh --check`。 installer は setup.sh 実行時にしか走らないので、 過去に置き換えられた他マシンの状態はこちらで拾う)。
- test = `scripts/install-hook-stubs.test.sh` (stub installer + symlink) / `scripts/install-precommit-bib.test.sh` (共通 hook の installer)。

### <a id="killed-hook-stub"></a>macOS に exec で kill される hook は、 同じ中身の新しい inode に作り直す (2026-09-19)

**症状**: `git commit` が `.git/hooks/<name> died of signal 9` で止まる。 同じ中身・同じ xattr・同じ mtime の stub が、 repo によって通ったり kill されたりする。 `bash <runner>` で runner を直接呼ぶと通る。 pre-commit / prepare-commit-msg / commit-msg / pre-push / post-merge のどれにも起きる。 **macOS 側の仕組み (判定は inode ごと・syspolicyd が詰まると scan の失敗が kill として残る)・実測と推定の区別・診断の道具は [`macos-exec-policy-kill.md`](macos-exec-policy-kill.md) が正本**。 ここには hook を配る側の規則だけを置く。

規則 (実装 = `scripts/lib/hook-stub.sh`):
- **stub は一時 file + `mv` で新しい inode に書く** (`hook_stub_put`)。 同じ inode への上書きでは覚えた判定が残る
- **既存の stub が最新でも exec を検査し、 kill されるなら同じ bytes・同じ mode で作り直す** (`hook_exec_heal_chain` = stub と、 stub が exec する runner)。 **中身は変えない** ので track 済み file でも git の差分は出ない ([#installer-tracked-stub](#installer-tracked-stub) と両立)。 symlink は実体を作り直し、 link は残す
- **作り直しても kill されるなら WARNING を出して止める。 繰り返さない**: syspolicyd がまだ詰まっているか、 本当に malware と判定されたかのどちらかで、 どちらも installer が回り込んでよいものではない。 **macOS の設定 (Gatekeeper・XProtect) にも xattr にも触らない**。 作り直した file も macOS がもう一度 scan する = 検査を外したことにはならない
- **検査は hook を 1 行も走らせない** (`$BASH_ENV` に `exit 0` だけの file を渡す = [`macos-exec-policy-kill.md#exec-probe`](macos-exec-policy-kill.md#exec-probe))。 bash 以外の shebang と macOS 以外は検査しない
- **発火面は SessionStart と setup**: `scripts/heal-hook-stubs.sh` が全 repo の、 git が実際に使う hooks dir (`core.hooksPath` を反映) の hook と runner を実体ごとに 1 回ずつ検査して直す (hook 180 本規模で、 段 1 と合わせて約 2 秒。 検査が足すのは約 0.7 秒)。 SessionStart から `--surface` で毎回呼べば commit が止まる前に直り、 結果は「戻した / 作り直した / 要対応」 の 3 見出しで出る (個人層の bootstrap hook から呼ぶ形。 見出しと振り分けは script が持つ = 呼ぶ側は出力をそのまま出すだけ)。 setup.sh は Step 8c で同じものを呼ぶ (Step 8b は installer の出力を捨てているため、 直らなかった WARNING をここで見せる)
- **session の途中で `died of signal 9` が出たら** `bash <base>/claude-config/scripts/heal-hook-stubs.sh` を 1 回走らせる。 手で `cat > x && mv` しない (installer と同じ判定・報告を通す)。 書かずに一覧だけ見るなら `--check` (kill されるものがあれば exit 1)
- 射程外: bash 以外の hook / runner がさらに exec する script (python は `python3 x.py` で起動すれば exec の判定を受けない) / syspolicyd 自体の不調 (hook を作り直しても、 詰まっている間に初めて exec される file は同じ目に遭いうる)
- test = `scripts/install-hook-stubs.test.sh` T11–T18 (inode ごとの判定の再現 = [#exec-probe-test-techniques](#exec-probe-test-techniques))。 修正前の code では 10 項目が落ちることを確かめた。 偽の kill 一覧は inode 番号なので、 印を付けた inode は hard link で生かす (Linux の fs は番号を再利用する = 上の技法の ⚠️)。 設計の判断 = [`DESIGN.md#killed-hook-recreate-design`](../DESIGN.md#killed-hook-recreate-design)

### <a id="tool-matcher-coverage-boundary"></a>§2 補足: tool-matcher の coverage boundary — Bash/script write は Edit/Write guard を素通りする

配信が健全 (= (a)(b)(c) 全 green) でも、 PreToolUse hook は **登録した matcher の tool にしか fire しない**。 `PreToolUse(Edit|Write|MultiEdit)` guard は **Bash / script (`python ... open(w)` / `cat > f` 等) で書いた file を一切見ない** (= それらは Edit/Write tool call でないため)。 bug ではなく matcher の設計境界 (§2 (d) の harness-invoke-bug 〔Bash matcher が bug で fire しない〕 とは別軸)。 guard を分類すると塞ぎ方が決まる:

- **path-based guard は Bash matcher を足せる**: `memory-guard.sh` (Edit/Write) + `memory-guard-bash.sh` (Bash) は「memory dir への write か」 を **path** で判定するので Bash 版が作れる。 `google-url-guard.sh` も Edit/Write/MultiEdit/**Bash** を cover。
- **content-based guard は commit-time が authoritative layer**: `public-leak-guard.sh` は Edit/Write/MultiEdit のみ (Bash matcher なし) → **public repo の file を Bash/script で書くと PreToolUse leak-guard を素通りする**。 これは設計上むしろ正しい — leak 判定は**書かれる content** を見る必要があり、 Bash-write の content は command 内で生成・埋込されて静的 scan が困難。 backstop は **commit 時の `public-precommit-runner.sh` + `commit-msg-leak-guard-runner.sh`** (= materialize 済の staged content を scan するので書き方を問わず cover)。 = **public repo leak gate の真の layer は commit-time git hook、 PreToolUse leak-guard は早期 catch の best-effort**。
- 実例 (2026-06-10): SESSION.md を python script で hot/cold split した際、 PreToolUse leak-guard は不発火、 commit-time gate + 手動 grep で安全確認した。

→ guard を設計するとき「守りたい write は Edit/Write だけか、 Bash も含むか」 を明示する。 path-based なら Bash matcher を追加、 content-based なら commit-time gate に backstop を置く (= PreToolUse 単独で content leak を完全には塞げない)。

### <a id="disableallhooks-kill-switch"></a>§2 補足 2: `disableAllHooks` kill switch — root 限定で入ると「frontend 差」 に化ける

**症状**: ある場所で開いた session では hook が 1 本も効かず (SessionStart の注入なし・PreToolUse の ask / deny 素通り・PostToolUse の nudge なし)、 別の場所で開いた session では普通に効く。 (a)(b)(c) の配信 audit は全部 green。

**機構**: settings の `disableAllHooks: true` は、 その settings file が効く範囲の **command hook を全部止める** (user tier なら全 session、 managed なら machine 全体、 project / project-local なら **その root を開いた session だけ**)。 host が SDK 経由で登録する callback hook (desktop app の案内文等) は止まらないので、 transcript に hook 由来らしい記録が少し残り「hook は動いている」 と錯覚しやすい。 CLI の内部文言は "Policy disableAllHooks: skipping configured hooks … (SDK callback hooks still run)"、 `/hooks` 画面にも "To re-enable hooks, remove "disableAllHooks" from settings.json" と出る。 同じ見え方をする他の候補 = managed の `allowManagedHooksOnly` / workspace trust 未承認 (後者は未検証の候補)。

**潜む場所**: 主作業 root の `.claude/settings.local.json` (= git 非同期・machine-local・普段開かない file)。 同じ file には desktop app の「常に許可」 が allow rule を書き足すので mtime は頻繁に動き、 mtime から「いつ入ったか」 は分からない。

**なぜ誤診されるか**: 主に使う frontend と主に開く root が重なっていると、 root の差がそのまま frontend の差に見える。 実例 (2026-09-11 判明): owner の主作業 root の project-local に kill switch が**少なくとも 2.5 ヶ月**入っており、 その root で開いた session では user hook 約 60 本 (SessionStart / PreToolUse / PostToolUse / UserPromptSubmit / Stop) が 1 本も走っていなかった。 この間の「desktop app は hook 出力を honor しない」 という観測 ([§9.3](#frontend-dependent-cowork)) の少なくとも一部はこの root で測ったもので、 frontend の性質の証拠にならない。 いつ誰が入れたかは記録が残っていない。

**自分では検出できない**: kill switch 下の session は SessionStart hook も止まるので、 「hook が止まっている」 と知らせる hook 自体が走らない。 検出は外側に置く — dashboard (別 process)、 別 root の session、 定期実行。

**判別 (transcript)**:
- user の command hook が走った session には `attachment.hookEvent == "SessionStart"` かつ `attachment.command` が hook の path である record (hookName `SessionStart:startup|resume|compact`) が残り、 `system/stop_hook_summary` の `hookInfos[].command` に hook の path が並ぶ
- kill switch 下は stop summary の command が `callback` だけ。 desktop の callback が出す `hook_additional_context` は command を持たないので user hook の証拠に数えない

**道具**: [`scripts/hook-liveness-audit.py`](../scripts/hook-liveness-audit.py) — settings 全 tier (user / managed / 各 root の project と project-local) の `disableAllHooks` と `allowManagedHooksOnly` を見て、 transcript を root ごとに集計し「SessionStart hook が設定されているのに直近 N session 連続で発火記録が無い root」 を出す (連続で見るので、 除去後に 1 本でも発火すれば消える)。 `audit-hooks.sh` が `--findings-only` を回すので dashboard から毎 session 見える。

**除去**: 該当行を消せば**同じ session の次の tool call から** hook が走る (desktop 埋込 2.1.260 で実測。 [§9.1](#new-hook-session-snapshot) の snapshot 規則はこの変更には当てはまらなかった)。 ただし理由があって入れた可能性があるので、 検出しても自動では消さず owner に判断を渡す。 除去すると ask / deny を返す guard 群も一斉に復活して確認 dialog が増えるので、 それを先に伝える。

---

### <a id="marker-detection-scan-whole-turn"></a>§2 補足 3: 抑止 marker は turn の転写全体から拾う — assistant text だけを見ると呼ぶ側が可視面を汚す

hook に「この turn は見逃せ」 と伝える escape-hatch marker を設計するとき、 検出を **assistant の text block だけ**に限ると、 呼ぶ側は marker を最終メッセージに書くほかなくなる。 ところが **Claude Code の chat renderer は HTML comment を literal 表示する** (2026-09-12 実測) ので、 「不可視 marker」 のつもりが毎 turn user の画面に出る (= 呼ぶ側からは観測できないまま蓄積する)。

∴ 検出は turn の転写全体 (assistant text + `tool_use` の `.input.command` + `tool_result`) を走査する形にし、 呼ぶ側が Bash command の comment 等、 **提示面でない場所**に marker を置けるようにする。 併せて hook の発火条件を狭く保つ (= marker が要る turn を最小化する)。 正本 = [`mid-turn-text-visibility.md#machine-marker-in-tool-input`](mid-turn-text-visibility.md#machine-marker-in-tool-input)。

⚠️ 裏返し: 転写全体を見る hook は、 **その turn で hook 自身の source や説明を読むと** tool_result に marker の語が入り、 no-op になる (実測)。 その hook の実地確認は、 source を読んでいない新しい turn でやる ([`../docs/convention-design-principles.md#detector-fires-on-its-own-signal`](../docs/convention-design-principles.md#detector-fires-on-its-own-signal) の一形)。

### <a id="matcher-regex-partial-match"></a>§2 補足 4: matcher の当たり方 — 英数字と `|` 以外の字が 1 つあると正規表現の部分一致になり、 tool の改名では黙って死ぬ

Claude Code 本体の当て方 (本体を読んで確かめた、 実測):

- matcher が英数字・`_`・`|`・`,`・空白・`-` だけなら**名の列挙**で、 1 つずつ完全一致で当てる。 旧い tool 名は今の名に直してから当てる (例 = `Task` → `Agent`)。
- それ以外の字 (`.` `*` `(` `^` など) を 1 つでも含むと、 matcher 全体が**正規表現**になる。 先頭と末尾に固定しない部分一致で、 今の名と旧名の両方に当てる。
  - 例 = `mcp__.*__start_session|Agent|Task` は `.*` のせいで正規表現になる。 `Agent` が `ListAgents` に、 `Task` が `TaskStop`・`TaskList` に当たる。
  - 狙った名だけにするなら `^(mcp__.*__start_session|Agent|Task)$` と固定する。 固定しても旧名の `Task` で来た呼び出しは `Agent` に当たる。
  - hook の engine が tool 名を完全一致で振り分けていれば、 害は余分な起動だけで済む。 engine の側も部分一致で振り分けていると、 関係のない tool で誤って動く。 固定した後は、 止めるべき呼び出しを 1 回実際に投げて、 今も止まることを確かめる。
- **tool が改名されると、 列挙の matcher は新しい名に当たらず黙って死ぬ** (実測 = 改名の後、 二重起動を止める hook が一度も発火していなかった)。 [§2](#delivery-audit-4-axes) の配信の audit は全部 green のまま。
  - 確かめる道具 = [`scripts/hook-matcher-liveness.py`](../scripts/hook-matcher-liveness.py)。 会話記録に出た tool 名を各 settings の matcher に当て、 「何にも当たらない」「途中で消えた」「部分一致で別の名にも当たる」 を出す。 dashboard では [`scripts/audit-hooks.sh`](../scripts/audit-hooks.sh) の (e) が回す。 当て方の写しは script の中にあり、 本体の版が変わったら [`scripts/claude-app-bundle.py`](../scripts/claude-app-bundle.py) `grep --where engine 'Invalid regex pattern in hook matcher'` (当てる関数) と `'Task:"Agent"'` (旧名の表) で読み直す ([`claude-app-bundle-reading.md`](claude-app-bundle-reading.md))。
  - 直し方 = 新しい名の行を足す。 古い名の行は、 全部の機械でこの道具が「途中で消えた」 と出してから外す (古い app の機械ではまだ古い名で来る)。

## <a id="warn-mode-spec-uncertainty"></a>§3. PreToolUse warn mode 出力の spec uncertainty

### <a id="warn-mode-problem"></a>問題

claude-code hook の PreToolUse phase で **warn** (= block しないが user / Claude に message を surface) を実装するとき、 spec 上 visible になる経路が複数あり version 依存:

| 出力経路 | 仕様確度 | surface 経路 |
|---|---|---|
| **stderr** | 高 (= `permissionDecision: ask` 時の error message 経路として確立) | `ask` / `deny` 時は user 可視。 `allow` (= 通常 flow) 時は spec 不明確 |
| **stdout JSON `hookSpecificOutput.additionalContext`** | 中 (= PostToolUse の system-reminder と類似 model) | 次ターン Claude に inject される (が、 user に直接 surface するかは別) |
| **stdout JSON top-level `systemMessage`** | 低 (= 旧 spec field の可能性、 deprecated 候補) | version 依存、 fallback として残す |

`ask` / `deny` (= block 系) は spec 確立済で stderr が確実に surface する。 warn (= 通すが message 出す) は claude-code 内部の通常 permission flow に乗せるため、 message 経路が spec で明確に定義されていない。

### <a id="warn-mode-implementation"></a>実装推奨

warn 用途では **3 経路を defensive に併用** (= どれが surface しても OK):

```bash
# stderr (= log + ask/deny 時の確実経路、 allow 時は best-effort)
printf '%s\n' "$WARN_TEXT" >&2

# stdout JSON: 通常 permission flow + additionalContext で次ターン inject
jq -n --arg msg "$WARN_TEXT" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": $msg
  },
  "systemMessage": $msg
}'

exit 0
```

`permissionDecision` field は **出さない** (= 通常 permission flow に流す = ユーザー設定の auto-allow / ask を override しない)。 `permissionDecision: "allow"` を出すと user の手動許可 flow を bypass する副作用があるので warn 用途では不適切。

### <a id="warn-mode-dry-run"></a>Dry-run 観察事項 (= warn hook 投入後に user に依頼)

warn hook を MVP で投入したら、 一定期間 (= 数週間〜1 ヶ月) 観察して以下を decide:
- どの経路 (stderr / additionalContext / systemMessage) が **実際 surface したか** (= claude-code 当該 version での実 spec)
- false-positive 率 (= 「surface したが実 leak ではない」 の比率)
- escalation (= `permissionDecision: "ask"` 化) の可否

surface しなかった場合: 残り 2 経路に依存している、 または warn hook の effect が user 観察に届いていない、 のどちらか。 後者なら escalation を検討、 前者なら simplify する余地。

---

## <a id="partial-install-state"></a>§4. Partial install state (= §2 の specific failure mode、 注意喚起)

### <a id="partial-install-problem"></a>問題

§2 の delivery 3 軸 (= (a)(b)(c))を分離して扱った時の典型 failure mode (= 「一部だけ直した」 が「全部直した」 と誤認):

- 手動 `ln -s` だけ実行 → symlink あり / settings.json entry 不在 = silent malfunction
- setup.sh の途中で fail → 直前まで完了した step は残るが後続 step が skip = partial state
- 個人層 hook (= layer 3) を ad hoc に install → settings.json merge を忘れがち

setup.sh の `install_hooks()` 関数内の **「symlink 配置 → settings.json への jq merge」 dual-step は atomic な 1 unit として扱う** (= 関数内で逐次実行、 該当 logic の正本は `claude-config/setup.sh`)。 これを分離して片方だけ実行すると partial state を produce する。

### <a id="partial-install-prevention"></a>防止策

hook 配信を「fix した」 と claim する前に **§2 の delivery 3 軸 (= (a)(b)(c))ゲート質問を独立に通す**。 「`ln -s` 通った」 「config に書き足した」 のどちらか単独では不十分。

**規律**: hook 配信修復 task では、 必ず symlink + settings.json + try-fire の 3 step を **同じ作業 unit に bundle** する。 分離すると次の作業者 (= 別 session の Claude / 別マシンの自分) が partial state を canonical と誤認する。

### <a id="additive-wiring-needs-retirement"></a>§4 補足: 足すだけの配線には、 退役の経路が別に要る

hook の配線 (hooks dir の symlink + `settings.json` の entry) は「無いものを足すだけ」 で作る — 他の層や利用者が足した entry を壊さないためで、 これ自体は正しい。 その裏面として、 **hook を repo から消しても各マシンの配線は残る**。 残った entry は、 その event のたびに「file が無い」 command として走り、 失敗し続ける (壊れた symlink は `ls` では見えても hook 一覧の検査では「配線済み」 に見えることがある)。

- **退役は registry に書く**: 1 行 1 file 名の text file (`hooks/retired-hooks.txt`) に名前と理由を書き、 毎 session 走る sync 経路が同じ関数で外す = [`scripts/lib/prune-retired-hooks.sh`](../scripts/lib/prune-retired-hooks.sh) (層1 は [`scripts/sync-hook-settings.sh`](../scripts/sync-hook-settings.sh) が呼ぶ。 個人層の installer は自分の registry を同じ関数に渡す)。 **hook を消す commit = list から抜く + registry に足す、 を同じ commit で**。
- **掃除を install script の hardcode にしない**: 「この名前を settings から消す」 を installer の本文に書くと、 その installer を再実行しないマシンでは永久に残る (pull だけで新しい hook が配線される経路を作ったなら、 退役も同じ経路に載せる)。
- **event だけの退役**: 同じ file を別の event で使い続けるなら `Event:file 名` と書く (その event の entry だけを外し、 symlink は触らない)。
- **安全側の既定**: registry に名前が在っても、 hook の実体が repo にまだ在れば外さない (書き間違いで生きている hook を消さない)。 消すのは symlink だけで、 entry は「command の語のどれかが `/<file 名>` で終わる hook」 だけを抜く (同じ entry に同居する他の hook・他の層の entry は残す)。 `--check` は残骸を不足と同じ「配線のずれ」 として数える。
- **list と registry の矛盾は test で止める**: 同じ名前が両方に在ると、 毎回足して毎回外す (= [`scripts/sync-hook-settings.test.sh`](../scripts/sync-hook-settings.test.sh) が検査)。
- **個人層の hook を層1 へ上げるときは file 名を変える**: 同じ名前のまま個人層で退役し層1 で新設すると、 退役の prune (symlink を消す) と層1 の sync (symlink を作る) が hooks dir の同じ path を取り合う (実測、 別名にして回避)。 退役の registry の理由には行き先の名前を書く。
- **settings の entry を持たない symlink だけの配線 (custom agent 定義・skill 等) は registry なしで外せる**: 外す対象を「自分の source dir の中を指し、 その先がもう無い link」 に限れば所有が明らかで、 書き間違いで生きているものを消す経路も無い (他所を指す壊れた link は触らない)。 定義を消した後の壊れた link は、 次の session の registry 読み込みで「読めない定義」 として残り続ける (実測: 版を切り替えて旧 agent の定義を消した後、 各マシンに壊れた link が残っていた)。 installer の `--check` はこの残骸も配線のずれに数える

origin: hook を 1 本消した時に、 各マシンの `settings.json` に command が残る形だと分かった (実測)。 同じ型の掃除が installer に hardcode で在り、 構造上、 その installer を再実行しないマシンには届かない形だった。

### <a id="new-hook-protected-bundle"></a>§4 補足 2: 層1 に新しい hook を足す変更は保護された file の束 — 候補を写しで置き、 再生成した索引も 1 件として承認を取る

本 repo が規則保護の guard (正本 = [`agent-rule-ownership.md`](agent-rule-ownership.md)) を配線している環境では、 新しい hook を足す変更のうち次が保護領域になり、 本人の項目ごとの承認が要る:
`hooks/` に足す file 全部 (hook 本体・語や設定の一覧・test)、 配線の `hooks/settings-entries.json`、 **それらを足した後に再生成する `hooks/README.md`**、 個人層の installer。
`scripts/` に置く engine は保護されないので先に置けるが、 **code の file に guard の engine の名前を書くと、 test の例の文字列であっても file 全体が配線の lock になる** (実測: selftest の例に guard の名前を使った新しい script が書けなかった) = 例に使わない。

1. engine を `scripts/` に置き、 hook 本体・一覧・test は個人層や作業 repo の plan に**候補の写し**として置く。 test は候補の dir からも回る形にする (engine を env か層1 の checkout から探す) = 承認の前に全部を試せる。 Bash の command を見る engine には module level に `find_issues(command) -> list` を持たせる = §12 の校正の道具がそのまま呼べる (実測: 持たせずに作り、 校正に使い捨ての script を書いた)。
2. 校正の数字 ([§12](#text-pattern-stop-hook)) と候補の場所を本人に見せ、 **1 つの返事で、 足す file・配線・installer の変更・再生成する索引を全部名指して**承認を頼む。 承認の発言は本人が次に発言するまで複数 file に効く。 ボタンで答えてもらうなら、 その文が長さで切られない長さにする ([`mid-turn-text-visibility.md#turn-closing-question-box`](mid-turn-text-visibility.md#turn-closing-question-box))。 校正で止まった件の数と中身は、 本人の会話記録から数えた本人の活動の件数でもある = 本人に見せ、 個人層の記録に置き、 公開 repo の commit message と本文には形 (誤検出の数・校正の道具・読んだ範囲) だけを書く (実測: 止まった件の数と、 それが何の起動だったかを公開の commit message に書き、 活動の事実の検査も鳴らなかった。 境界 = [`../CLAUDE.md#owner-activity-facts`](../CLAUDE.md#owner-activity-facts))。
3. 承認の発言を最新の発言として引き、 1 file ずつ当てる (配線の json・installer は全文の候補を一時 dir に作ってから)。
4. 新しい file を `git add` してから索引を作り直し、 **変わった `hooks/README.md` も候補として 1 件当てる**。 忘れると commit の gate で止まり、 同じ commit に入れた他の file も止まる (実測)。 既にある hook に検査を足すときも、 hook や test の説明の 1 行目を直せば索引の行が変わる = 同じく候補の束に入れる (生成器の `extract_header_desc` で候補の 1 行目から行を作り、 索引の候補と一致するかを当てる前に確かめる)。 engine の docstring の 1 行目を直したときは `scripts/README.md` も変わる (保護の外 = 当てた後に `--write`)。
5. 写しは消す (層1 と二重にしない。 経緯は plan に 1 段落)。 配線の後に、 配線した command の path で hook を直接呼んで発火を確かめる ([§9.1](#new-hook-session-snapshot) = 同じ session で harness からの発火は build 依存)。

---

## <a id="hook-architectural-rationale"></a>§5. hook の架構的根拠 — 第 2 視点としての harness

§1-4 は hook を **書くときの実装 gotcha** を扱った。 §5 は hook の **存在理由** を architectural に明示する section。 規律 (= prompt-level instruction / CLAUDE.md convention) で代替できない領域を hook が引受ける、 という分担を Claude / user が mental model として持つことの value。

### <a id="self-reference-impossibility"></a>5.1 単一視点 self-reference の geometric 不能

Claude の generation は forward token stream で、 自分の生成物を **同じ stream 内で外から見る** ことは geometric に不能。 単一カメラで depth perception ができないのと同質の問題で、 algorithm の改善で解決しない (= 第 2 視点が必要)。

具体的に hook で代替できる典型例:
- `git commit -m "..."` を実行する瞬間に commit message を「読み返す」 step は同じ Bash 呼び出しに含まれず、 generation stream 内に挿入できない → PreToolUse(Bash) hook で外側 gate
- file edit 後に「この edit は規律違反していないか」 を自問する step は同 stream 内に reflex として埋まらない → PreToolUse(Edit|Write|MultiEdit) hook で外側 gate
- 大きな出力 file を `/tmp/...` に書く判断を実行直前に再考する step は同 stream で起動しない → PreToolUse(Bash) hook で pattern match して `ask`

これらは「Claude が規律を覚えていれば防げる」 という framing で語られがちだが、 **覚えていても同 stream 内で自己 gate できない**ことが本質。 規律で言う「pre-output 自己問い」 を毎回 reliably に起動できないのは attention shape の問題で、 規律の書き方を工夫しても根本解決しない。 hook = harness 側の view = 第 2 視点が **geometric necessity**。

### <a id="narrative-vs-mechanism-visibility"></a>5.2 narrative-vs-mechanism の非対称 visibility

規律本体 (= CLAUDE.md / convention narrative) と hook は 2 種類の防御 layer だが、 **decay 検出の visibility が非対称**:

| | visibility | decay 検出 |
|---|---|---|
| narrative (= 規律本体) | 高 — 読めば見える | user が読まなくなれば失効、 ただし user 自身に visible |
| hook (= mechanism) | 低 — 実行されないと分からない | symlink broken / config 欠落で silent malfunction、 invisible |

→ user / Claude の mental model 上は narrative + hook が「redundant 防御として対称」 に扱われがちだが、 **実際は非対称**。 hook 失効は narrative より検出が遅れる (= §2 で言及した「symlink broken silent malfunction」 が代表例、 1 ヶ月単位の detect 遅延が起こり得る)。

含意:
- hook を書いたら「機能している前提で narrative を縮退する」 reflex は危険 (= §6 で詳述)
- hook の存在を「visible」 と reflex で扱わない、 定期 audit (= §2 の delivery 3 軸 (= (a)(b)(c)) audit) で動作を継続確認する運用 mechanism が必要

### <a id="discipline-cannot-replace-hook"></a>5.3 規律で hook を代替できない (= 逆も真)

逆も同様: narrative 規律で hook の代替を試みると失敗する。 「Claude が規律を読んで自己 gate する」 は §5.1 の geometric 制約で reliability が確保できない。 規律と hook は **代替関係ではなく補完関係**:

- 規律 = **Claude が読むと判断 quality が上がる** layer (= 高 visibility、 low reliability)
- hook = **判断を bypass しても止まる** layer (= 低 visibility、 high reliability)

両方が必要、 どちらか一方では穴が残る。

---

## <a id="discipline-narrative-reduction"></a>§6. hook 投入後の規律 narrative 縮退判定

機械的 enforcement (= hook) が新規投入されたとき、 同 rule を文書化した narrative (= CLAUDE.md / convention) を縮退するか維持するかの判定 framework。 hook と narrative が同じ rule を扱う場合、 attention budget 観点では narrative の縮退余地があるが、 §5.2 の非対称 visibility が縮退判断を複雑にする。

### <a id="defense-equation"></a>6.1 4 状態の防御 equation

| hook 状態 | narrative 状態 | 防御 layer |
|---|---|---|
| working | present | 二重 (= redundant) |
| working | absent | 単独 (= hook reliability に依存、 縮退想定状態) |
| **broken (silent)** | present | 単独 narrative carry (= acceptable but invisible) |
| **broken (silent)** | **absent** | **ゼロ** (= catastrophic) |

縮退 (= narrative absent) は hook reliability を前提にするが、 §5.2 の通り hook は silent decay する (= §2 で言及した broken symlink の 1 ヶ月 detect 遅延が実例)。 **縮退と silent decay が重なる瞬間に防御 layer がゼロになる**。

これは attention budget 圧迫 (= narrative 累積) を交換に「**silent regression risk**」 を抱え込む構造で、 単純な負荷減ではなく **risk の質的 transformation**。 「規律を減らす」 = 「気付ける失敗を減らす + 気付けない失敗を増やす」 という非対称な trade、 と認識する必要がある。

### <a id="reduction-prerequisites"></a>6.2 縮退の前提条件 — (P1) + (P2) 両必須

- **(P1) 現時点の hook 健全性**: 該当 hook 全件で §2 の delivery 3 軸 (= (a)(b)(c)) audit (= symlink + settings.json + try-fire) が pass
- **(P2) 継続監視 mechanism**: hook の silent decay (= 配信失効 + matcher 失効 の両方) が dashboard 等で **session 開始時に毎回 surface** される運用が established

(P1) は one-shot check、 (P2) は continuous infrastructure。 (P2) を欠いて (P1) だけで縮退すると、 任意 timing の silent decay でゼロ防御に陥る。

縮退の判定者 (= cold session / user) は (P2) infrastructure が無い状態を「縮退の盲点」 として認識し、 縮退着手前に (P2) を establish するか、 (P2) 無しで縮退 risk を accept するかを **明示判断**する。 reflex で「hook あるから縮退 OK」 と進めない。

### <a id="reduction-procedure"></a>6.3 段階的縮退の推奨手順

(P1)(P2) 両方 establish 後も、 一気に大量の narrative を縮退するのは risky。 推奨:

1. **影響最小の 1 個から試験的縮退**: 機構が単純な hook (= 例: 単一 tool / 単一 pattern で gate するもの) を選ぶ
2. **1 週間〜1 ヶ月の運用観察**: hook で実際に該当 case が catch されているか、 false positive 率はどうか、 user / Claude の reflex はどう変化したか
3. **問題なければ次の 1 個に進む**: 段階的 progress、 大量変更を避ける
4. **silent decay の検出能力が dashboard で実証されたら**、 縮退 pace を上げる判断余地

### <a id="reduction-factors"></a>6.4 縮退判定で考慮する factor

- **規律 narrative の memory aid 価値**: user / Claude が読んだとき context を喚起する効果。 「過去事例の歴史的価値」 「条件分岐 / edge case の説明価値」 等
- **hook の機構の単純さ**: 単純な機構ほど silent decay リスクが低い (= regex 1 本 < script 10 行 < script 100 行 + 外部 dependency)
- **hook の機構の覆う range**: 全ての該当 case を catch しているか、 部分 cover か。 部分 cover なら narrative 縮退は危険
- **narrative の更新頻度**: ほぼ更新されない安定 narrative は縮退して pointer 化しても損失小、 頻繁に追記される narrative は in-place の方が attention 効率良好

→ 規律全体を一律縮退するのではなく、 「機構が単純 + 全範囲 cover + 規律が安定 + (P1)(P2) pass」 を満たす項目のみ縮退候補に上げる、 が安全側設計。

---

## <a id="shared-matcher-mock-pattern"></a>§7. Shared matcher library + mock-personal-layer test pattern

### <a id="shared-matcher-problem"></a>問題

2 種類の hook (= claude-code PreToolUse / git native commit-msg) が同じ matcher logic (= 「commit message に非例外 private repo 名が含まれるか」 等) を必要とすることがある。 単純に 2 hook で logic を duplicate すると drift する (= matcher rule が片方だけ update + 片方が stale という failure mode)。 共通 library 化したいが、 library が **layer 3 data (= 個人層の `repos.md` / `sensitive-terms.txt` 等)** を参照する場合、 library 本体の test を **layer 1 (= public claude-config)** に置く design challenge がある: 実 layer 3 data を test fixture に embed すると public leak になる。

### <a id="shared-matcher-pattern"></a>Pattern

**(a) Shared library を layer 1 に置く**: library source 自体は algorithm のみで public-safe (= allowlist 名は既に layer 1 で公開済の場合に限る、 そうでなければ allowlist literal も layer 3 に外出し)、 layer 3 data 参照は `lib/find-personal-layer.sh` の cascade で動的解決。 foreign user (= 個人層なし) では fail-open (= matcher が hit 0 を返す = `commit-msg-leak-guard-runner.sh` で実装済)。

**(b) Layer 3 hook と layer 1 runner が両方 library を source**: claude-code hook (= layer 3、 warn mode、 stdin JSON) + git native hook (= layer 1 runner、 BLOCK mode、 $1 file path) が異なる入出力 contract を持ちつつ、 matcher core は library 経由で共通化。

**(c) Layer 1 test file は mock-personal-layer pattern**: test 実行時に `CLAUDE_PERSONAL_LAYER` env var を temp dir に向け、 dir 内に **偽の** `repos.md` + `sensitive-terms.txt` を provisioning。 test case は mock literal (= `mockpriv-foo` / `MOCK_SECRET_TERM_ALPHA` 等) で matcher logic を検証。 実 layer 3 data の literal は **layer 3 test file 側** (= 個人層 hook の test) に閉じ込める。

### <a id="placement-flowchart"></a>配置決定 flowchart

```
matcher logic を共通化したい?
  └── Yes
       │
       ├── matcher source 自体が public-safe? (= allowlist literal が
       │   既に layer 1 で公開済、 etc.)
       │     ├── Yes → library を layer 1 (claude-config/scripts/lib/) に配置
       │     └── No  → library も layer 3 (個人層 scripts/lib/) に配置、
       │              layer 1 hook からは「library 不在なら fail-open」 で対応
       │
       └── library が layer 3 data を参照する?
            ├── Yes → find-personal-layer.sh cascade で動的解決、
            │        foreign user は fail-open。
            │        layer 1 test は mock-personal-layer pattern (= 下記 (c))
            └── No  → 通常の layer 1 test (= mock 不要)
```

### <a id="mock-personal-layer-fixture"></a>Mock-personal-layer test fixture の最小実装 (= bash)

```bash
# test 開始時に temp dir で偽 layer 3 を構築
MOCK_LAYER="$(mktemp -d)/mock-personal-layer"
mkdir -p "$MOCK_LAYER"
# find_personal_layer() の検出条件を満たす marker 2 file
touch "$MOCK_LAYER/.claude-personal-layer"
echo "# mock" > "$MOCK_LAYER/CLAUDE.md"

# 偽 repos.md (= 実 layer 3 と同 schema、 mock literal で埋める)
cat > "$MOCK_LAYER/repos.md" << 'REPOS_EOF'
| repo | desc | visibility |
|---|---|---|
| `mockpriv-foo/` | mock private repo foo | private |
| `mockpriv-bar/` | mock private repo bar | private |
REPOS_EOF

# 偽 sensitive-terms.txt
echo "MOCK_SECRET_TERM_ALPHA" > "$MOCK_LAYER/sensitive-terms.txt"

# env var で library に injection
export CLAUDE_PERSONAL_LAYER="$MOCK_LAYER"

# 以降 test case は mock literal で matcher を test
# (= 実 private repo 名は test file source に embed しない)
```

### <a id="shared-matcher-motivation"></a>設計動機 (= 2026-05-26 RCA)

本 pattern は `commit-msg-leak-guard-runner.sh` 実装時に **self-leak event** で学習。 当初 layer 1 test file の test case literal に **実 private repo 名 (= 4 種) を直接 embed** していた (= 「過去事例の reproduce」 を目的化、 mock 化 reflex を skip)。 hook 自身は file body を scope 外として通過 → public commit に焼き付き → 4 軸 sweep 安全性軸で発覚 → mock-personal-layer pattern に refactor (= 詳細 [`DESIGN.md §2026-05-26`](../DESIGN.md) 反省 section)。

→ **layer 1 test file は最初から mock pattern で書く reflex** が implementer 側に必要。 hook の覆える scope の外で leak しないよう「自分の change が hook scope OUTSIDE 経由で leak しないか」 を実装時に問う。

### <a id="leak-prevention-rules"></a>関連 leak prevention rule

claude-config `CLAUDE.md §「安全規則 (公開リポ)」` に **「layer 1 test file での private repo 名 literal は禁止、 mock-personal-layer pattern で代替」** rule あり (= 本 §7 と相補、 §7 = how、 安全規則 = what)。

---

## <a id="chain-hook-early-exit"></a>§8. chain hook は primary hook の early-exit で silent skip される

hook A が末尾で hook B を呼ぶ (= chain) 構造で、 A が **自身の no-op 条件**で early-exit すると B に到達しない。 B は呼ばれないだけで error を出さず silent dead になる (= §2 の silent malfunction の chain 版、 [`docs/convention-design-principles.md §8.8`](../docs/convention-design-principles.md#proxy-blind-spot) の false confidence)。

### <a id="chain-hook-example"></a>実例 (2026-06-06 RCA)

pre-commit hook A (= LaTeX Unicode fixer) が「対象 file (LaTeX) が staged されてなければ exit 0」 と early-exit。 A は末尾で layer-3 chain hook B (= yaml/data gate) を呼ぶ設計だったが、 対象外 file のみの commit (= data file のみ) では A が early-exit して B に未到達。 B にした gate が **silent dead**。 B が catch すべき violation を仕込んだ commit が reject されず通る **実 commit e2e で初めて発覚** (= logic 確認・syntax 確認・関数シミュレートは全て pass していた、 実 e2e のみが expose した)。

### <a id="chain-hook-prevention"></a>防止策

- chain hook を呼ぶ primary は **自身の no-op 条件で early-exit しない**。 primary の処理を `if [[ 条件 ]]; then ...; fi` で囲み、 chain は無条件に末尾で呼ぶ (= chain は primary の関心事と独立に走るべき)。
- **chain reachability を実 e2e で verify** (= §2 の 4 軸 audit に加える 5 軸目)。 chain B が catch すべき violation を実際に仕込み、 primary A の no-op path (= A が何もしない commit) でも B が発火するか確認する。 logic / syntax / シミュレートでは expose できない (= 本 RCA がまさにそれらを通過していた)。


### <a id="engine-failure-must-not-block"></a>§8.1 engine を呼ぶ BLOCK は exit code だけで止めない — 壊れた engine が全 repo の commit を止める (2026-09-13)

全 repo に連鎖する pre-commit が検査 engine (python 等) を呼び `python3 engine || exit 1` で BLOCK すると、 **engine 自身の構文エラー・import 失敗・未捕捉例外も exit 1** になり、 finding と区別がつかない。 engine を 1 行壊しただけで、 連鎖している全 repo の全 commit が止まる (実測: 構文エラーの python は exit 1)。

- 止める条件は **「exit 1 かつ engine が finding の見出し行を出した」** にする。 見出しは engine 側で固定の文言にし、 hook はその文言を照合する。
- engine 内部の失敗は別の exit code (例: 3) で返し、 hook は WARN を出して通す。 未捕捉例外や読み込み失敗まで engine 側で拾い切れないので、 **見出し照合が最後の防壁**になる。
- engine が無いマシン (他端末・CI の単独 checkout) は素通りにする。
- test には「構文エラーの engine では止めない」「engine 不在では止めない」 を foil として入れる。 exit code だけの実装だと前者で落ちる。
- 例外は「止め損ねの害が誤って止める害より大きい」 gate (機密 leak 等) で、 fail-closed を**選んだと明記**する。

実装例 = 個人層 chain の markdown link BLOCK と公開 repo runner の同 guard (engine = [`scripts/fix-md-links.py`](../scripts/fix-md-links.py) `--staged`、 test = `scripts/public-precommit-runner.test.sh` の md_case)。

### <a id="engine-edit-is-deploy"></a>§8.2 git hook の engine は作業ツリーから呼ばれる — 保存した瞬間が配布、 commit は配布 gate ではない (2026-09-13)

各 repo の `.git/hooks/pre-commit` は stub で、 実体は `~/Claude/<層>/scripts/` の**作業ツリーの file** を path で呼ぶ。 したがって engine や chain script を**保存した瞬間**に、 その machine の全 repo と、 そこで動いている**他の session の次の commit** にまで効く。 commit や push は「配布」 ではなく記録でしかない (実測: 新しい BLOCK を chain に足した直後、 commit 前の段階で、 別 session が作業中の repo の commit がもう新しい guard を通っていた)。

- engine を直すときは、 **保存する前に** selftest を scratch の copy で回すか、 まず fail-open 側 (WARN / 内部失敗は止めない = [#engine-failure-must-not-block](#engine-failure-must-not-block)) で入れてから BLOCK にする。
- 途中の壊れた版を保存しない。 大きな書き換えは別名 file で作って test を通し、 最後に 1 回で置き換える。
- **規則保護の guard の engine (`manuscript-claim-guard.py` / `agent-rule-guard.py`) の scratch の copy は、 別の file 名で置いて回す**: [`hooks/guard-cli-form-guard.py`](../hooks/guard-cli-form-guard.py) は engine を file 名で見分け、 正本の絶対 path でない呼び出しを止める (承認の CLI を allow に当たる形にさせる hook なので、 同じ名前の scratch の copy も止まる。 実測)。 copy の隣には engine が読む file を symlink で置く (同じ dir の `agent-rule-guard.py` と `lib/`、 selftest が一つ上の dir から読む `conventions/`)。 直す前の版も同じ置き方で回し、 結果の差だけを見る (置き方で落ちる検査を自分の変更と取り違えない)。 scratch で「古い版では落ちる」 と確かめた foil は次に直す人が再現できないので、 残すなら [#hook-test-foil-teeth](#hook-test-foil-teeth) の spec にする。
- **engine と呼び元 (dispatcher) を同時に変えるときは、 候補の呼び元で両方を続けて写す** (呼び元は隣の engine を import するので、 engine だけ先に写すと、 その machine の全 session の Edit / commit が「inspection unavailable」 で fail-closed に止まる。 実測: 数分の窓で 2 つの session が止まった。 候補の tree に置いた呼び元は自分の隣の候補 engine を読むので、 それで本番の呼び元と engine を続けて写せば窓は秒になる)。
- 機械化 = [`scripts/apply-text-pairs.py`](../scripts/apply-text-pairs.py) `TARGET PAIRS.py --test 'python3 {} --selftest'` (親 dir ごと一時 dir に写した版で test を通し、 通った時だけ一時 file + `os.replace` で置き換える。 写すのは親 dir だけなので、 repo root を前提にする `*.test.sh` は `--test` では回らない = 制約の正本は同 script の docstring。 install 先の symlink の path を渡しても実体に解決して書く = [batch-text-edits.md#symlink-target](batch-text-edits.md#symlink-target))。 2026-09-13 の実例: engine の patch script を写しに当てるつもりで再実行し、 target の引数を付け忘れて本物に二重に入った ([batch-text-edits.md#insertion-pair-rerun](batch-text-edits.md#insertion-pair-rerun))。 module として import する pre-commit 経路は動き続け、 CLI として呼ぶ suite 側だけが約 1 分落ちていた = 壊れ方が経路で分かれるので、 片方の経路が緑でも安全の証拠にならない。
- 配線した直後に、 **他 session が今 stage している内容**が新しい guard に止められないかを読み取りだけで確かめる (`python3 <engine> --staged` を相手の repo で実行、 書き込みはしない)。
- **止められた側** (別 session の commit): pre-commit が engine の `SyntaxError` や import 失敗で止まったら、 自分で engine を直す前に、 その engine の repo で `git status --short -- <engine>` と `python3 -m py_compile <engine>` を見る。 相手の未 commit の変更があり、 今は compile が通るなら、 相手が保存した途中の版に当たっただけ = 同じ commit を打ち直す。 相手の作業中の file を自分で直さない (相手の次の保存と衝突する)。 fail-closed を選んだ gate ([#engine-failure-must-not-block](#engine-failure-must-not-block) の最後の項) では、 この型が全 repo の commit を止める。 実測: 無関係な repo の記録の commit が止まり、 数十秒後に打ち直すと通った。

---

## <a id="build-dependent-behavior"></a>§9. hook の挙動は build 依存 — 同 session snapshot + feature 差 (= upstream docs を鵜呑みにしない)

claude-code の hook 関連挙動は **running build によって docs と乖離する**。 最新 docs を読んだだけで「こう動くはず」 と assert すると、 古い build で silent に外れる。 inline §3 (= 単一情報源で結論に飛躍しない) の hook domain instance。

### <a id="new-hook-session-snapshot"></a>9.1 新規 hook は同 session で live 発火しない (= session 開始時 snapshot)

> 🔄 **build 依存 (2026-09-12 追記)**: 本項の snapshot 挙動は 2026-06 の build の実測。 desktop 埋込 2.1.266 では mid-session に足した Stop hook が同じ session で発火した (= 本項末の 🔄)。 2.1.271 でも同じ (Edit で settings に足した Stop entry が、 次の turn 終わりで block を返した)。 「新 session / app 再起動が要る」 と決め打ちせず、 足した直後に下の discriminator で測る。

**実測 (2026-06-10、 Opus 4.8 1M harness)**: settings.json に hook を **mid-session で追加しても、 その session 中は発火しない**。 = この build は hook 設定を **session 開始時に snapshot** する。

**discriminator** (= 「snapshot build か hot-reload build か」 を実測): throwaway hook (= `echo fired >> /tmp/x`) を **`Read` (または `Write`/`Edit`) matcher** で mid-session 登録 → 該当 tool を 1 回叩いて `/tmp/x` を確認 → **不在 = 未発火 = snapshot build**。 ⚠️ **discriminator に `Bash` matcher を使わない**: §2(d) の harness-invoke bug で Bash hook は snapshot と無関係に発火しないことがあり結果が交絡する (= 2026-06-10 に最初 Bash で試して confound に気付き、 `Read` matcher で取り直して snapshot を clean に確定した)。

⚠️ 最新 docs は逆 (=「settings files を watch して `hooks` も hot-reload する」) と記載。 つまり **reload timing は build 依存**。 docs の hot-reload 記述を根拠に「今 足した hook が今 効く」 と assume しない。

**§2 / §6 の verification への含意** (= 重要):
- §2 (c) logic 健全性 (= realistic JSON を stdin で hook を直接起動) は **同 session で可** (= harness 配線と独立に script を実行)。 hook を書いたら必ずこれで logic verify。
- §2 (d) trace / 実 tool call での live 発火 verify は、 **新規 hook では同 session で不能** (= snapshot ゆえ未配線)。 **新 session を開いてから** verify する。 同 session の非発火を「matcher bug」 等と誤判定しない (= 2026-06-10 に実際この誤帰責を一度した)。
- §6 (P1) の「該当 hook 全件で try-fire pass」 gate も、 新規追加 hook は新 session 必須。
- **新規 hook 追加の作法**: ① stdin JSON で logic unit-test (同 session) → ② install + (a)(b) 配線 audit (同 session) → ③ live 発火は次 session で確認。

⚠️ **frontend で snapshot 粒度が違う — desktop app は *app 起動時* snapshot (2026-06-27 実測)**: 上記 ③「次 session で確認」 は CLI (= session 単位 snapshot) の作法。 **Claude Code の desktop app (`CLAUDE_CODE_ENTRYPOINT=claude-desktop`、 = Claude for Mac の Code) は hook list を *app 起動時* に snapshot する** ので、 既に起動している app の中で「新しい session を開く」 だけでは、 後から settings.json に足した hook は **発火しない**。 → desktop で新規 hook を活かす・live verify するには **app を quit + 再起動**してから新 session を開く (= ③ は desktop では「app 再起動 → 次 session」)。 実測 (2026-06-27 probe): 13:03 に追加した SessionStart hook が、 13:25 に *起動済 app 内で* 開いた fresh session で**非発火** — 一方、 同じ fresh session で *app 起動前から settings.json に在った* 他 ~10 個の SessionStart hook は全て発火 (= それぞれの surface file が当該時刻に新規書込)。 ∴ 非発火は hook 不良でなく **app-launch snapshot 未収載**が原因 (logic は手動実行で健全確認済)。 これは §9.3 (= 出力が honor されない) とは**別軸の desktop 制約** (= §9.3「載った hook の出力が届くか」 / 本項「そもそも snapshot に載るか」)。

⚠️ **settings の変更がすべて snapshot に縛られるわけではない** (2026-09-11、 desktop 埋込 2.1.260 で実測): `disableAllHooks` の除去と `permissions.allow` への追加は、 **同じ session の次の tool call から**有効になった。 snapshot されるのは hook の一覧で、 kill switch や permission rule は都度読まれている可能性がある (機構は未確認)。 どの変更が即時でどれが snapshot かは、 変更の種類ごとに 1 回測る。

🔄 **hook の一覧も読み直す build がある** (2026-09-12、 desktop 埋込 2.1.266 で実測): installer で `settings.json` に Stop hook を足した直後の turn 終了 (約 40 秒後) に、 その hook が発火して block した。 transcript 上、 最後の SessionStart (resume) は足す 1 時間以上前で、 間に SessionStart は無い (= app の再起動も session の再開も挟んでいない)。 上の 2026-06-10 (CLI、 session 開始時 snapshot) と 2026-06-27 (desktop、 app 起動時 snapshot) はそれぞれの build についての事実で、 この build には当てはまらない。 2 例目 (同日・同 build・別 session): 配線 list に足した副作用だけの Stop hook を `scripts/sync-hook-settings.sh` で `settings.json` に入れた turn の終了時に発火した (hook 自身が書く state file の時刻 = その turn の終了時刻、 [§14](#opt-in-side-effect-hook))。 3 例目 = **PreToolUse も即時** (同日・同 build・同じ session): 配線 list に足した PreToolUse(Bash) の guard (`hooks/zsh-word-split-guard.py`) を `sync-hook-settings.sh` で入れた直後、 次の turn で同じ session の Bash が deny された (わざと該当する無害な command を打って確認)。 4 例目 = **app の tool への PreToolUse も即時** (2026-10-25、 desktop 埋込 2.1.308): session の途中で settings に足した `mcp__ccd_turn__wrap_up` の deny の hook が、 直後の呼び出しで効いた ([desktop の再確認](#desktop-hook-honor-remeasure)の印の形)。 5 例目 = **PostToolUse も即時** (2026-10-29、 desktop 埋込 2.1.309): session の途中で installer が settings に足した matcher `*` の PostToolUse の hook が、 次の tool の呼び出しで走った (hook 自身が書く session ごとの state file がその時刻にできた)。 観測は Stop 2 本 + PreToolUse 2 本 + PostToolUse 1 本なので、 他 event (SessionStart は性質上 session 開始時のみ / UserPromptSubmit) の即時性は未確認。 → 足した直後に discriminator で測り、 発火すれば live verify (上の ③) も同じ session で済む。

### <a id="build-dependent-docs-drift"></a>9.2 同種の「docs と乖離」 build 依存 feature

| feature | 最新 docs | 実測された乖離 | robust な cross-build 選択 |
|---|---|---|---|
| settings.json hook の hot-reload | する | 2026-06-10 build は snapshot / 2026-09-12 desktop 2.1.266 は Stop hook を hot-reload (§9.1) | 同 session で discriminator、 だめなら新 session で live-verify |
| PreToolUse の `permissionDecisionReason` field | 支持 | 2026-05-29 build は JSON に含めると **hook 出力ごと silent skip** (= mail-send-guard RCA) | narrative → stderr、 stdout は minimal JSON (= `permissionDecision` のみ)。 既存 convention |
| PreToolUse で止めた理由の届き方 | JSON の deny + reason / exit 2 の stderr が model に届く | JSON で `permissionDecision: deny` だけ返すと tool 結果は「denied this tool」 の一語で、 理由は届かない (実測、 desktop)。 `permissionDecisionReason` を付けた deny の文言は届く build がある (実測) | **理由を model に届けたい block は exit 2 + stderr** (JSON 解釈に依らず止まり、 stderr が tool 結果に出る)。 実装例 = 一時 dir の使い捨て送信 script を止める mail guard / 印刷前 gate ([`scripts/pdf-print-preflight.py`](../scripts/pdf-print-preflight.py) `--hook`、 desktop 埋込 build で exit 2 の block と頁の一覧が tool 結果に届くことを実測 = 確認 〔ask〕 だった版は理由が誰にも届かなかった) |
| PreToolUse ask の stderr narrative | user に表示 | desktop では承認 dialog にも tool 結果にも出ない (実測) | ask の説明文で model や user を誘導しようとしない。 誘導が要るなら止めて理由を返すか、 事前の注入に書く |
| PreToolUse の `additionalContext` | model に inject | その tool call の**結果と一緒に**届く = 実行の後 (実測) | 実行前に効かせたいなら block を使う (案内だけでは最初の 1 回を防げない) |
| PreToolUse `updatedInput` で tool 引数 rewrite (= default 注入) | 支持 (= allow/ask + 全 field 含め replace)。 docs が書くのは `allow` (prompt を飛ばして通す。 deny・ask rule は残る、 auto mode の classifier を飛ばすかは未記載) と `ask` (auto mode でも prompt を強制) との組だけで、 **判断を付けない形は未記載** (無視とも error とも書いていない) | 古い build での support 未確認。 **判断なしの形は desktop の Code タブ (engine 2.1.295) で効いた** (実測: Bash の `echo ======; echo after` を quote した形に書き換えて返すと、 書き換えた方が走って 2 行とも出た。 同じ出力の `additionalContext` も結果と一緒に届いた。 Agent の指示に段を足す [`hooks/delegation-record-clause.py`](../hooks/delegation-record-clause.py) も前から同じ形で、 委ねた agent の報告にその段が現れている) | 書き換えた入力を**通常の許可の判定**に回したいときは、 判断を付けずに `updatedInput` だけを返す (`allow` は判定を飛ばして自動で通す、 `ask` は毎回聞く。 permission rule は書き換えた後の入力に当たる = docs)。 その形を測っていない build では deny + 再発行 (= `<personal-layer>/hooks/calendar-reminder-guard.sh` が deny を選んだ理由)。 ⚠️ **同じ tool に `updatedInput` を返す hook を 2 本置かない** — hook は並列に走り、 最後に終わった 1 本の書き換えだけが効く (順序は決まらない = docs)。 実装例 = [`hooks/zsh-word-split-guard.py`](../hooks/zsh-word-split-guard.py) の `equals_rewrite` (Bash) / `delegation-record-clause.py` (Agent) |

**メタ規律**: hook 挙動を docs だけで assert せず、 ① logic は stdin で unit-test、 ② live 発火・新 field は **実測** (= throwaway hook / 実 tool call / 新 session)、 ③ 不確実な feature は **古い build でも動く path** を選ぶ (= stderr narrative / deny / new-session verify)。

### <a id="rewritten-input-execution-receipt"></a>書き換えた入力・実行の記録・モデルの受領を分ける

`updatedInput` が実行へ届いても、親の会話記録には元の tool input が残ることがある (実測)。
事後に「書き換え後の文字列が会話記録にあるはず」と探す検査は、その形式を実 tool call で照合してから使う。
再現には [`probe-headless-record-clause.py`](../scripts/probe-headless-record-clause.py) の手動 probe を使える。
実 CLI を loopback の固定応答で駆動し、偽 worker の argv と保存された親の tool input を両方見る。
CLI の送信内容・hook の発火・記録の対応を測る方法であり、外部モデルの受領や遵守の検証ではない。

- **意図と実行を結ぶ**: 別の実行記録を作るときは、親 session・tool call・元入力の hash・起動位置を鍵にする。
  同じ cwd や近い時刻だけで他の worker の記録を借りない。再試行は別 attempt として選び直す。
- **証拠の段階を残す**: hook の選択、runner の準備、stdin の送達、起動失敗、worker の報告を区別する。
  遅れて着く成功が同じ attempt の失敗を消す競合と、複写されたログが証拠のある側を隠す順序依存を反例にする。
- **読み手の範囲から保持を決める**: 事後検査が読む親ログがある間は対応する証拠を残す。
  古さだけで切らず、由来と親ログの不在を照合する。読めない記録や対応不明を「不要な記録」と推測しない。
  起動の hook と全記録の整理は処理時間を分け、整理が注入の時間切れを起こさない配置にする。

### <a id="command-rewrite-hook-checks"></a>Bash の command を書き換えて通す hook — 文字として書いた語を書き換えない・当てる前に shell で構文を見る

PreToolUse の `updatedInput` で command の一部を書き換えて通す hook は、 止める hook と違って誤りが目に見えない (書き換えた結果で実行される)。 次の 4 点を作る段で確かめる:

- **展開されない文字は書き換えない** — single quote の中・heredoc の本文に加えて、 `\$` で escape した形 (double quote の中の `\${VAR}`) も文字。 commit message や echo の説明にその語を書いた command が当たる (実測: 書き換える hook を当てた直後、 その hook の説明を書いた commit message の中の語を書き換えた = 自分の commit が最初に当たる)。 当てた直後に、 対象の語を説明に含む commit を 1 回打って確かめる
- **heredoc で消すのは本文と終わりの行だけ** — 始まりの行の残り (`cmd <<'EOF' 2>&1 | tail; echo …`) は shell の code。 始まりの行ごと消す正規表現 (`<<'EOF'[^\n]*\n…`) だと、 その行の後半を見逃す (実測: 較正で見逃しが出て直した)
- **会話記録の command で較正し、 書き換えた後の command を shell の構文検査に通す** — 対象の語を含む過去の Bash を集め、 書き換える / 止める / 何もしない の件数と例を出し、 書き換えた全部を `zsh -n -c '<command>'` (bash なら `bash -n`) に通す。 何もしない側の例は 1 件ずつ読む (見逃しはここに出る)
- **書き換えの意味が決まらない形は止める** — 書き換え先が一意に決まる形 (定数の添字など) だけを書き換え、 決まらない形 (変数の添字など) は直し方を付けて止める。 書き換えを推測で広げない

実装例 = [`hooks/zsh-word-split-guard.py`](../hooks/zsh-word-split-guard.py) の PIPESTATUS の述語 (`pipestatus_rewrite`)。 通る形と止める形の出力の作り方 (判断の field を付けない) は同 file の冒頭と [§9.2](#build-dependent-docs-drift) の `updatedInput` の行。

### <a id="frontend-dependent-cowork"></a>9.3 frontend 依存 — desktop app の hook 出力 honor は**反転して見えた (主因は root 限定の kill switch)。 前提にせず session ごとに測れ**

hook の効きは build だけでなく **frontend (= terminal CLI / IDE 拡張 / desktop app)** にも依存する。 **ただしこの依存は固定の性質ではなく、 同じ version 文字列のまま反転した実績がある** — 下の 2026-09-09 実測を参照。 ⚠️ **2026-09-11**: 反転に見えたものの大部分は、 作業 root に入っていた `disableAllHooks` だった ([#disableallhooks-kill-switch](#disableallhooks-kill-switch))。

> 🔄 <a id="desktop-hook-honor-remeasure"></a>**2026-09-09 実測 (desktop 埋込 build 2.1.260、 `entrypoint=claude-desktop`) — 3 面すべて honor された** (= 2026-06-13 / 2026-09-05 の観測と**逆**):
>
> | 面 | 2026-06-13 / 09-05 の観測 | 2026-09-09 の実測 | 証拠 |
> |---|---|---|---|
> | SessionStart の context injection | 届かない | **届く** | 当 session が SessionStart hook 16 本の `<system-reminder>` を実受領。 別 desktop session でも 15 本受領し、 **whoami probe を走らせる前に** hook 由来の自己同定 stamp を出力した (= 注入を読んでいなければ書けない文字列) |
> | PreToolUse の `permissionDecision: deny` | 素通し | **enforce される** | marker 無しの memory 書込みを Bash で試行 → guard の deny 文言で tool が実行前に停止、 probe file も生成されず |
> | PostToolUse の `hookSpecificOutput.additionalContext` | (未測定) | **届く** | 検索 null nudge が tool_result 末尾に付与され、 両 session の transcript に literal で残存 |
>
> **追加の実測 (2026-09-11、 desktop 埋込 build 2.1.266、 kill switch 除去後)**:
>
> | 面 | 実測 | 証拠 |
> |---|---|---|
> | UserPromptSubmit の `hookSpecificOutput.additionalContext` | **届く** | prompt の直後に hook の文面を受領 / 同じ機の transcript に UPS の `hook_additional_context` record が在る (実測) |
> | Stop の `decision: block` | **効く** | 既存の Stop hook の発火条件を最終 message でわざと満たした → transcript に meta の user 行 `Stop hook feedback: …` と `hook_blocking_error` (Stop) が残り、 同じ turn が続いた |
> | hook の `systemMessage` | **会話に表示されない** | UPS hook が `systemMessage` を出した session で、 owner の画面にその行は無かった (目視)。 transcript には `hook_system_message` として残る = 記録はされるが user には見えない |
>
> **再確認 (2026-10-07、 desktop 埋込 build 2.1.287)**: UserPromptSubmit の additionalContext を prompt の直後に受領 (transcript に `hook_additional_context` / UserPromptSubmit)。 Stop の block は 1 turn に 3 本 (別々の hook) が同時に返り、 3 本とも feedback として届いて同じ turn が続いた (`hook_blocking_error` / Stop × 3)。 表の 2 面は変わらず。
>
> **再確認 (2026-10-25、 desktop 埋込 build 2.1.308)**: PreToolUse の JSON の `permissionDecision: deny` で tool は動かない。 marker の無い memory への Write でも、 app の tool (`mcp__ccd_turn__wrap_up` = turn を閉じる欄) でも同じで、 欄は画面に出なかった。 欄の側は、 決まった印を含むときだけ deny する使い捨ての hook を足し、 印を入れた欄で呼んで確かめた (効かなくても出るのは印つきの無害な欄だけ)。 会話記録の tool_result は `is_error: true`、 中身は `PreToolUse:<Tool> hook error: <理由>` = 後の hook は「この呼び出しは deny された」 を is_error で読める。 ⚠️ **何も出さない hook の実行は会話記録に残らない** (`hook_success` などの記録は出力のあった hook だけ) = 黙って通した hook が読み込まれていたかは、 記録からは確かめられない (確かめるなら上の印の形で 1 回 deny させる)。
>
> 帰結: desktop でも「model に届ける」 手段 (additionalContext / block) は使えるが、 「user に見せる」 手段として `systemMessage` は使えない。 実装例 = [`multi-account-machine-surface.md#first-reply-stamp-mechanism`](multi-account-machine-surface.md#first-reply-stamp-mechanism)。
>
> **原因の大部分は kill switch と判明 (2026-09-11)**: owner の主作業 root の project-local に `disableAllHooks: true` が入っていた ([#disableallhooks-kill-switch](#disableallhooks-kill-switch))。 その root で開いた desktop session は 9/1 以降すべて SessionStart の発火記録 0、 同期間に別 root で開いた session は発火していた。 09-05 の再測定もその root の session だった**可能性が高い** (同日の同 root の session はすべて発火記録 0)。 09-09 の測定 session の root は記録から特定できていないが、 同 root の session はすべて 0 なので別 root だったと**推論**できる (推論であって確認ではない)。 決め手 = 同じ desktop session で、 除去前は PreToolUse の ask が出ず (jq はあり fail-open ではない)、 除去直後は PostToolUse の additionalContext が届いた = frontend でなく設定の差。 06-13 の観測がこれで説明できるかは記録が無く未確定 (06-13 には SessionStart hook がプロセスとして走った trace があり、 全停止とは完全には合わない)。
>
> **設計上の帰結 (重要)**: 「desktop だから hook は効かない」 を**対策見送りの根拠にしない**。 この前提は
> ① 実際に反転した ② 反転しても誰も気づかない (= 前提が doc に焼かれると再測定の trigger が消える) の 2 点で危険。
> hook 前提の対策を採否判定する turn では、 **その session で 1 回測る** (下の判別) — 測定コストは数秒で、
> 誤った前提で数ヶ月 backlog を凍らせるコストより桁で安い。
>
> **1 session 分の判別レシピ** (= 3 面それぞれ独立):
> - SessionStart 注入 = session 冒頭に hook 由来の `<system-reminder>` を受領しているか (= 受領していれば注入は生きている)。 transcript 側の裏取りは `attachment.type == "hook_success"` かつ `hookEvent == "SessionStart"` の record
> - PreToolUse deny = 既知の deny 対象 (= 無害・可逆なもの) を 1 回叩いて block されるか
> - PostToolUse additionalContext = 既知の nudge を 1 回発火させ、 tool_result 末尾に文言が付くか
> - UserPromptSubmit additionalContext = prompt の直後に hook の文面を受領しているか (transcript 側は `attachment.type == "hook_additional_context"` かつ `hookEvent == "UserPromptSubmit"`)
> - Stop の `decision: block` = 既存の Stop hook の発火条件を最終 message でわざと満たして終わる (配線不要)。 transcript に meta の user 行 `Stop hook feedback: …` と `hook_blocking_error` (Stop) が残り、 同じ turn が続けば効いている。 続かなければ turn がそこで終わるので、 試すのは作業をすべて終えた後の最終 message で
> - `systemMessage` (user 向けの表示) = 出した session の画面に行が出たかを user に 1 回見てもらう。 transcript の `hook_system_message` は記録であって表示の証拠ではない

**旧観測 (2026-06-13、 desktop 埋込 build 2.1.170。 初回 session = PreToolUse 非効きを発見、 同日の cold-eyes 再検証 session で機構を精緻化)** — **上記のとおり 2026-09-09 には再現しない**。 build/時期依存の記録として残す:

- **SessionStart hook**: desktop でも **プロセスとして実行される** (= 撤去前提の trace hook 〔stdin + 親プロセス path を記録〕 を SessionStart に仕込み、 desktop が `source:startup` の session を生成するたびに発火するのを確認。 親プロセス = 埋込 build 2.1.170)。 **だがその出力 (stdout / `additionalContext`) はモデルの文脈に注入されない** (= 同 hook に unique marker を載せ、 fresh な desktop session に「marker が見えるか」 と問うと「ない」。 加えて検証 session 自身が session 開始時に currentdate-anchor 〔無条件出力〕 や horizon の reminder を一切受領していない)。 ∴ **副作用 (file 書込等) は起きるが、 context injection は捨てられる**。
- **PreToolUse hook**: その **permissionDecision (deny/ask) が honor されない** (= session 開始時から snapshot に在る memory-guard 〔marker 無し memory write を hard-deny するはず〕 が desktop で素通り。 deny 型ゆえ `bypassPermissions` でも隠れない零交絡で確定)。 execution 自体の有無は未分離 (= 初回 session の §2(d) trace 不在は **mid-session 追加による §9.1 snapshot 交絡**の可能性があり、 「実行されない」 と断定しない。 確実なのは「効果が届かない」)。
- **正確な像** = **「desktop は hook を実行はするが、 モデルに向かう出力 (SessionStart の context injection / PreToolUse の permission 判定) を harness が honor しない」**。 旧版の「hook を一切実行しない」 / 「SessionStart も発火しない兆候 (cache stale)」 は **不正確** (= cache stale は SessionStart hook が呼ぶ calendar 取得補助 〔EventKit 経由の外部 binary〕 側の失敗 〔Terminal の TCC 不足等〕 が原因で、 hook 非実行の証拠ではなかった)。
- **再測定 (2026-09-05、 desktop 埋込 build 2.1.260)**: 状況は不変 — SessionStart の stamp 注入は session に届かず (= 自己同定 hook が走っているのに冒頭 stamp が無い)、 PreToolUse deny (memory-guard) は marker 無し write を素通し (probe file を作って即削除で実測)。 ∴ 「desktop では hook 出力はモデルに届かない」 は 3 ヶ月後も有効な前提として設計する。 desktop で頼れる自己同定は**最初の tool call で probe を実行して結果を冒頭に出す** discipline のみ ([multi-account-machine-surface.md I7](multi-account-machine-surface.md#seamless-invariants))。 ⚠️ **2026-09-11 注**: この再測定は kill switch が入った root の session だった可能性が高く ([上](#desktop-hook-honor-remeasure))、 frontend の性質の証拠としては使えない。 probe discipline 自体は、 注入が届いても害が無いので維持してよい。
- **declarative permission との非対称**: 同じ desktop でも `~/.claude/settings.json` の `permissions.deny` は **honor される** (= 無害な deny 対象コマンドを叩いて block を実測)。 honor されないのは hook 出力と承認フロー (ask)。 詳細は [`claude-code-permissions.md` frontend-split](claude-code-permissions.md#frontend-split)。

- ⚠️ **以下 3 項 (docs 乖離 / 有効化する手段 / 判別) は superseded (2026-09-11)**: 「desktop では hook の効果がモデルに届かない」 は kill switch を見落とした測定に基づく ([#disableallhooks-kill-switch](#disableallhooks-kill-switch))。 kill switch を除いた desktop (埋込 2.1.260) では SessionStart 注入・PreToolUse の ask / deny・PostToolUse の additionalContext が届いた。 記録として残すが、 判別に使うのは[上の 1 session 分の判別レシピ](#desktop-hook-honor-remeasure)と kill switch の確認だけにする。
- ⚠️ **公式 docs の「Hooks … apply to both 〔CLI and Desktop〕」 は実機と乖離** (= desktop では hook の効果がモデルに届かない。 hook は走るが出力が honor されないため実質「効かない」)。 docs を根拠に「desktop でも hook が効く」 と assume しない (= §9 冒頭「docs を鵜呑みにしない」 の frontend instance)。
- **有効化する手段は無い** (2026-06-13 確認): hook を desktop で on にする setting / CLI flag / env var は存在しない (`--output-format` は出力形式の制御で hook 実行とは無関係)。 desktop-native で最も近い機構は MCP server の `toolPolicy` (= 許可 tool の gating のみ、 PreToolUse のように **script を走らせる pre-tool-call は不可**)。 managed `allowManagedHooksOnly` は enterprise の管理制御で execution 保証ではない。
- **判別**: `echo $CLAUDE_CODE_ENTRYPOINT` が `claude-desktop` なら **hook 出力はモデルに届かない** (= SessionStart injection も PreToolUse 判定も無効。 SessionStart は実行自体は起きるが出力が捨てられる)。 親プロセスが `Claude.app` 配下か、 embedded build が PATH の CLI build と別番かでも判る。

**設計含意 (重要)**: hook は「Claude が滑った時に機械的に捕まえる第二視点」 (§5)。 desktop で**その第二視点が消える期間がある**と、 guard は「Claude が規律を自力で守る」 単一視点 (§5.1) に degrade する (⚠️ 2026-09-09 実測では消えていない = [上の再測定](#desktop-hook-honor-remeasure)。 「消えている」 を既定にせずその session で測る)。 degrade しうること自体は変わらないので、 ∴ **不可逆な事故を防ぐ guard ほど frontend 非依存の層に置く**:
- **public leak 防止** = commit-time の **git native hook** (`.git/hooks/pre-commit` + `commit-msg`) に置く (= frontend を経由せず `git commit` で必ず発火。 §2 補足「真の層は commit-time git hook」 と同じ理由 + §2(d) Bash harness-bug も同時に回避)。 ← desktop でも生きる class。
- **無人定期の surfacing** = launchd / scheduled task + OS 通知 (= frontend 非依存)。 **補足 (2026-06-13)**: SessionStart hook は desktop でも実行される (出力注入は捨てられるが副作用は走る) ので、 「SessionStart hook が surface を file に書く → Claude が起動時にそれを読む 〔CLAUDE.md / skill description は desktop でも読まれる〕」 という橋渡しも成立 (= launchd と並ぶ生成側の選択肢。 死んでいるのは注入だけで、 file 経由なら通常の tool call で読めるため)。
  - <a id="surface-file-cleanup-ordering"></a>⚠️ **surface file は「最新 findings の写像」 契約 — write-or-delete を空 early-exit より先に置く**: この橋渡しの surface file は「今の findings」 として読まれるため、 findings が空になった beat では **file を削除する** (= 書くか消すか、 必ずどちらかが毎回走る)。 hook の典型形 `[ -z "$out" ] && exit 0` を surface 書込みより**前**に置くと、 findings 解消後に cleanup が dead code 化し、 **解消済みの古い 🔴 finding が file に残留** → 後続 session がそれを現在の障害として誤読する (実 incident 2026-07-17: fleet-heartbeat の解消済み finding が 9 日間残留、 sibling hook 群は write-first で正しく、 1 本だけ ordering が逆だった)。 検査 reflex = surface 書込みを持つ hook を新設 / review する時、 「空 finding の実行で file が消えるか」 を 1 回実走して確認する (`echo '{"hook_event_name":"SessionStart"}' | bash <hook> && ls <surface-file>`)。
- **介入型 guard** (= tool 引数を見て deny / rewrite。 mail 誤送信確認・calendar reminder 強制・memory 誤書き込み防止 等) は tool-call 境界が必須で git native 化できない → desktop では不能と考えていた (⚠️ 2026-09-11 注: kill switch を除いた desktop では PreToolUse の deny / ask が効いた = 「原理的」 ではなかった。 それでも hook が効くかは前提にせず測り、 frontend 非依存の層に置けるものは置く)。

---

## <a id="hook-no-go-judgment"></a>§10. hook を見送る判定 — trigger が「意図」 を識別できないなら chronic false positive が fleet を毀損する

### <a id="hook-no-go-problem"></a>問題

hook の matcher / 条件は tool call の**表層** (command 文字列・file path・引数) しか見えない。
同じ表層で意図が分岐する操作に hook を書くと false positive が恒常化する。 典型例:
「context を探すための grep」 と 「file 整備のための grep」 は command 上は同一で、
前者だけに nudge したくても機械条件では分離できない。

nudge (= 非 deny の reminder) は「無害」 に見えるが、 噪音は当該 hook だけでなく
**hook 出力という機構全体への注意を磨耗させる** — 狼少年 effect は hook 単位でなく
fleet 単位で効く。 deny 型なら誤 block の作業中断がそのまま実害になる。

### <a id="no-go-judgment-criteria"></a>判定

hook 起案時に 1 問: **「この trigger 条件は、 介入すべき呼び出しだけを機械的に識別できるか?」**

- Yes → hook で良い (§0-§9 の作法へ)
- No → hook を見送り、 **発火面を変える**:
  - 「正しい瞬間に手順を想起する」 が問題 → **personal skill** ([`personal-skills.md`](personal-skills.md)。 description が全 session 常時可視 = recall を harness が肩代わり。 非発火時 noise ゼロ、 worst case = 現状維持の非対称 upside)
  - 無人定期 → scheduled task ([`scheduled-tasks.md` execution-locus-selection](scheduled-tasks.md#execution-locus-selection))
- skill は発火が確率的 (model 判断) なので、 **不発の実害が再発したら hook へ格上げ**する
  escalation trigger を導入時に書き残す (= evidence-driven の双方向切替)

⚠️ trigger が識別できても、 **signal が literal 文字列なら検出器は自分の保守で鳴く** (= source /
test / doc を読んだ出力に signal が載る)。 走査型なら自分の file を path 除外、 tool 出力を見る型は
signal の**構造** (= 発行元 prefix まで含めた形) に anchor する。 正本 =
[`convention-design-principles.md#detector-fires-on-its-own-signal`](../docs/convention-design-principles.md#detector-fires-on-its-own-signal)。

### <a id="no-go-example"></a>実例 (2026-06-13)

「内部 context 検索の前に横断 lookup script を回す」 規律の機械化で、 記録系 yaml への
grep を検出する PreToolUse nudge hook 案を検討 → grep の意図 (context-hunting vs
maintenance) が表層から識別不能、 当該 repo の整備 session では常時発火と判定 →
personal skill (description dispatch) に切替。 skill 名を含まない自然な質問に対する
初手 `Skill(...)` 発火を新 session の trace で確認 (検証作法 = [`personal-skills.md` verification-procedure](personal-skills.md#verification-procedure))。

---

## <a id="parallel-hooks-no-ordering"></a>§11. 同一 event の hook 群は並列に走る — 他 hook の副作用 (pull / 生成 file) を前提にした hook は stale data を読む

### <a id="parallel-hooks-problem"></a>問題

Claude Code は同じ event (= SessionStart 等) に登録された hook を **並列**に起動する (= settings.json の配列順は実行順ではない)。 「A hook が repo を pull → B hook がその repo の file を読んで surface する」 という暗黙の順序依存は成立せず、 **B は A の pull 前の working tree を読みうる**。 fleet が大きくなるほど (= A が全 repo を順に fetch/pull して数分かかる) B が stale を読む確率は上がる。 stale の読みは silent (= 古い data で「該当なし」 が出るだけ) なので、 検出器が「見落とした」 事実は user が別経路で気づくまで露出しない。

### <a id="parallel-hooks-example"></a>実例 (2026-09-05)

SessionStart で sync-sweep (全 repo auto-pull) と Discord 未転記 surfacer が並列起動。 surfacer は 13:39 に working tree の json (最終 pull 9/2) を読み 9/3 の投稿を「存在しない」 と判定、 sync-sweep の該当 repo pull は 13:45 に着地。 検出器の述語は正しかったが、 **data 鮮度が他 hook の副作用に依存していた**。 user が Discord を直接見て発覚。

### <a id="parallel-hooks-prevention"></a>防止策

1. **hook は自分が読む data の鮮度を自分で担保する**: repo data なら hook 自身が `git fetch` して **remote-tracking ref から読む** (`git show origin/HEAD:<path>`、 git-crypt file なら `| git-crypt smudge` を pipe。 = working tree の pull 状態から独立、 並列 fetch と lock 競合しても相手の fetch が ref を更新するので fresh)。 生成 file なら自分で生成するか、 mtime を見て古ければ「未チェック」 と明示する。
2. **順序依存を書きたくなったら 1 hook に束ねる** (= A→B を 1 script の sequential step にする)。 hook 間の順序制御は harness に無いものとして設計する。
3. **「前回 pull で fresh」 は時点情報**: session 冒頭に clean/fresh を確認しても、 並列に走る他 hook や他 session が状態を変える。 hook 内で読み直す。

### <a id="parallel-hooks-related"></a>関連

- `#chain-hook-early-exit` (§8) = 同一 hook 内の順序依存の別 failure mode (early-exit で chain が silent skip)。 本 § は hook **間**の順序依存。
- 検出器 fleet の一般則 = `convention-design-principles.md#surfaced-not-consumed` (産出と消費の境界)。 本 § は**産出**側の stale。

---

## <a id="text-pattern-stop-hook"></a>§12. 発話を見る Stop hook — 句で当てる前に過去の発話で校正し、 引用の例示を除く

turn 終了時 (Stop) に最終 assistant 発話を読み、 決まった句 (例: 同じ turn の中を指す「上の◯◯」、 人に後でやらせる「あとで 1 回実行して」) が出たら 1 回だけ block して見直させる hook は、 散文の規律 (= 発火面の最弱層、 [`convention-design-principles.md#firing-surface-hierarchy`](../docs/convention-design-principles.md#firing-surface-hierarchy)) を安く機械で支える。 ただし句の一致は意図を識別しない ([§10](#hook-no-go-judgment)) ので、 次を踏む:

1. **導入前に過去の transcript で校正する** — 直近 N session の各 turn の最終発話に句を当て、 検出を目で読んで誤検出を数える。 道具 = [`scripts/calibrate-final-message-pattern.py`](../scripts/calibrate-final-message-pattern.py) (`--pattern` / `--skip-quoted` / `--exclude-sentence-with`)。 turn の境界と最終発話の取り出しは hook と同じ部品 [`scripts/lib/transcript_turns.py`](../scripts/lib/transcript_turns.py) を使い、 校正と本番で述語がずれないようにする。 ⚠️ transcript は local の private data なので、 校正の出力 (文脈の抜粋) を公開の場所に貼らない。 述語が句でなく file system の状態で決まる hook は、 判定の部品に校正の入口を同居させる (例: [`scripts/lib/chat_file_refs.py`](../scripts/lib/chat_file_refs.py) `calibrate <days>` = [`hooks/chat-file-ref-enforce.sh`](../hooks/chat-file-ref-enforce.sh) と同じ関数で数える)。
   - <a id="calibrate-full-history"></a>**直近の N session で誤検出 0 でも、 手元にある全期間にもう 1 回当てる** — 直近の session は仕事の種類が偏る (実測: 直近の session では誤検出 0 だった述語が、 全期間では、 直近に無かった種類の会話で誤検出の型を 2 つ出した)。 誤検出の型が出たら、 その型の会話を固定した test を足してから述語を直す。
   - **述語の比べ方: 前処理と特徴量を分けて測る** — 「何を数えないか」 (引用・file 名・code・markup の除去) と「何で分けるか」 (比・閾値) を同時に変えると、 隙間を開いたのがどちらか分からなくなる。 特徴量を換えた理由を記録に書く前に、 最終の前処理のまま古い特徴量でも測り直す (実測: 特徴量を換えたおかげと書いた隙間が、 実は前処理を足したおかげで、 古い特徴量でも同じ発火になった)。 比べる script は記録の隣に置く ([`closing-sweep.md#evidence-scripts`](closing-sweep.md#evidence-scripts))。
   - <a id="calibrate-label-by-next-human-reply"></a>**当たりかどうかは、 鳴った返事への次の人の発言で分け、 その時刻も並べる** — 校正の script に、 鳴った turn ごとの次の人の発言 (差し戻し・task 通知・別 session の message・skill の起動文を除いた最初の発言) と時刻を出させると、 1 件ずつ記録を開かずに当たりを分けられ、 分け方を後から再現できる。 時刻を見ないと、 返事の後に別件を挟んだ発言を、 その返事への反応と数える (実測: 間に別の turn と error を挟んだ「分からない」 が、 直後の反応に見えた)。 同じ返事に続く差し戻しの追記も別の turn として鳴るので、 本番で黙る続き ([#stop-hook-active-other-hooks](#stop-hook-active-other-hooks)) は数えから外して報告する。
2. **自分を説明する文で一度は誤検出する** — hook を入れたことを報告する文は、 検出する句を例として引く。 match が 「」 / 『』 の中に丸ごと収まるなら除外し、 その文を regression test に固定する。 括弧の中で始まって外まで続く match は除外しない (= 過剰除外の防止も test に置く)。 実例 2026-09-12: 導入前の校正 (約 2000 turn) では誤検出 0 だったが、 導入直後に同じ session で hook を説明した返信が自分の例示句で止まった → 除外を足し、 同じ道具で再校正して誤検出 0 (検出 5 → 4)。
3. **block は 1 回だけ** — 自分の block がこの続き (直前の人・event の発言から後) に既にあれば exit 0。 reason には「条件を満たしているなら同じ内容で終了してよい」 を書き、 誤検出のコストを 1 turn に抑える。
   - <a id="stop-hook-active-other-hooks"></a>⚠️ **今の turn の返事を判定する hook は、 `stop_hook_active` が true なだけで即 exit 0 にしない** (session 全体の text を見る検査 = [伝えたかの検査](#injection-digest-and-relay) などは、 次の Stop で同じ text を見直すので、 即 exit しても見ない turn は残らない) — true は「どれかの Stop hook が差し戻した続き」 で、 同じ Stop に hook が並んでいると、 他の hook の差し戻しの後に書いた返事 (追記・書き直し) を一度も判定しない (実測: 並んだ hook のどれかが差し戻した後の返事は、 返事の言語の hook の判定から毎回抜けていた)。 差し戻しの理由は会話記録に `Stop hook feedback:` で始まる `isMeta` の user 行として入るので、 今の turn の user 行から遡って差し戻しの行だけを辿り、 自分の印 (reason に必ず入れる anchor など) を探す。 今の turn が差し戻しの行で始まっていない (形が分からない) ときは黙る。 実装例 = 個人層の返事の言語の hook の `own_block_in_chain`、 test は「他の hook の差し戻しの後 = 判定する」 と「自分が一度差し戻した続き = 黙る」 の 2 つを置く。
   - <a id="exemption-not-inherited-by-event-turns"></a>**人の発言から引いた「見ない条件」 を、 人でない始まりの turn に引き継がない** — 「直近の発言が英文の下書きの依頼なら最終発話の言語を見ない」 のように、 直近 N 個の人の発言で判定を外す hook は、 今の turn が task 通知・別 session の message・hook の差し戻し・圧縮の後で始まったときに、 その条件を当てない。 そういう turn の最終発話は人が頼んだもの (下書き) でなく、 自動の event への報告 (実測: 英文の作業の印が直近の発言にある会話で、 見張りの通知と worker の message で始まった turn の報告が規則を外れ、 その条件のために全部素通りした)。 もう 1 つ、 **「人の発言」 には別 session の brief・人が貼った外の文・app の再開の文が混じる** = 発言の言語や形から本人の頼みを推さず、 判定を外す条件は頼みの語 (「英語で答えて」 など) で立てる (実測: 「人が英語で書いた turn は英語で返す」 とした条件が、 英語の brief や貼り付けで起こした session の返事を通していた)。
4. **fail-open** — transcript 不在・parse 失敗・部品の import 失敗は沈黙する。 部品を別 repo から読む hook は、 その repo を CI でも clone してから test する (= 手元だけで通る test にしない)。
5. **導入直後に同じ session で実発火を確かめる** — 足した hook が走行中の session に効くかは build 依存 ([§9.1](#new-hook-session-snapshot))。

<a id="tool-input-reply-surface"></a>**本人に出る tool の引数も返事の面** (実測): turn を閉じる欄 (Claude desktop の `mcp__ccd_turn__wrap_up` の recap・ask・ボタン) と選択肢 UI (`AskUserQuestion`) の文は tool の引数として書かれ、 最終発話より先に画面に出る。 最終発話だけを見る Stop hook はここを見ず、 block しても欄は直らない。 しかも検査の無い面は、 前の turn の自分の欄を真似て崩れたまま続く (実測: 最終発話は規則どおりのまま、 欄だけが規則を外れて続き、 一度も止まらなかった)。 最終発話と同じ述語を 2 か所に当てる:
- **PreToolUse** (matcher `AskUserQuestion|mcp__.*__wrap_up`) で引数の文を単位 (要約・問い・ボタン) に分けて判定し、 外れていれば `permissionDecision: deny` で書き直させる。 本人に出る前に止まるのはここだけ。 判定に transcript が要る hook でも、 引数だけで外れが無いと分かる呼び出しでは transcript を読まない (turn ごとに呼ばれる)。 desktop で wrap_up への deny は効き、 欄は出ない ([desktop の再確認](#desktop-hook-honor-remeasure))。
- **Stop** では、 今の turn の欄のうち tool_result が error でないもの (= deny を通って画面に出たもの。 deny された呼び出しは is_error の tool_result で残る) も判定し、 外れていれば最終発話の判定と同じ 1 回の block に入れて書き足させる。 Stop は hook の file を毎回読むので、 PreToolUse の配線を読み込まない build で動いている session ([§9.1](#new-hook-session-snapshot)) にも効く。 最終発話と欄の両方が外れたときは理由を 1 つの指示にする (「全文を書き直す」 と「全文は出し直さない」 を並べない、 実測)。
- 作業側の語を見る [`hooks/decision-question-jargon-nudge.sh`](../hooks/decision-question-jargon-nudge.sh) が同じ 3 面 (最終発話の問い・選択肢 UI・欄) を見る前例。 校正も 3 面それぞれの過去の入力に当てる。

<a id="midturn-text-reply-surface"></a>**途中経過の text も返事の面 — PostToolUse で読み、 読んだ位置を session ごとに持つ** (実測): turn の途中で tool の呼び出しの前に書く text (途中経過の 1 行) は、 desktop では本人の画面に出るのに、 最終発話を見る Stop hook の判定の外にある (実測: 最終発話と欄の判定を直した後も、 途中経過の行だけが規則を外れて続いた)。 PostToolUse (matcher `*`) の時点では、 今の turn の text は全部、 後に tool の呼び出しが続く = 途中経過なので、 そこで読む:
- **transcript の書き出しは tool の終わりに間に合わないことがある** — 呼び出しの最中に transcript を読むと、 その呼び出しの行 (と直前の text) がまだ無い時と、 すぐ有る時があった (実測)。 「今の呼び出しの直前の text」 を探す形にすると、 書き出しの遅れた行を二度と見ない (実測: text の直後の呼び出しではその text が読めず、 次の呼び出しで拾った)。 読んだ位置 (byte の offset) を session ごとの state に持ち、 毎回その後の完全な行だけを読む = 遅れた行は次の呼び出しで見る。 matcher `*` は app の MCP tool (turn の欄・task list) の呼び出しにも走る (実測 = その呼び出しの直後に state の更新時刻が進んだ)。 遅れの測り方 = Bash の command の末尾に毎回ちがう印を置き、 その印を持つ行が transcript に現れるまで poll する。 1 つの message の並列の呼び出しでは PostToolUse も並列に走る ([§11](#parallel-hooks-no-ordering)) ので、 state の読み書きを flock で 1 本ずつにする (同じ行を 2 回言わない)。
- **前の turn の最終発話は数えない** — 新しい turn の最初の呼び出しで読む差分には、 前の turn の最終発話 (Stop の受け持ち) が入る。 差分の中の最後の人・event の発言 ([`is_real_user`](#transcript-user-message-shape)) より後の text だけを見る。
- **止めずに `additionalContext` で次の行から直させる** — 書いた行は消せず、 PostToolUse は済んだ tool を止められない。 文面は「書いた行の書き直しは要らない」 まで言う (書き直しを求めると途中経過が倍になる)。 効き目 (実測): 知らせの後の最初の text は大半が規則に戻ったが、 知らせは session・turn の**最初の 1 行**を防げない (外れの行の多くは最初の途中経過だった) = 最初の 1 行は事前の知らせ (SessionStart・圧縮の直後の注入、 [#counter-notice-at-injection](#counter-notice-at-injection)) の受け持ち。 効き目は「知らせの後の最初の text が規則どおりか」 を会話記録で数えて測る。
- **処理時間**: 全部の tool の呼び出しで走るので、 差分の text だけで決まる安い判定で外れが無ければ transcript の全体を読まない (人の発言から決める期待の値は、 外れの行が出たときだけ全体を読んで決める)。 外れの無い呼び出しの費用は wrapper と解釈系の起動がほぼ全部 (python の hook で数十 ms、 実測)。
- **subagent の呼び出しは見ない** — payload に `agent_id` があるか transcript が `/subagents/` の下なら黙る (subagent の text は本人の画面に出ない)。 session ごとに state の file が増えるので、 session の最初の呼び出しで古いものを消す。
- 実装例 = 個人層の返事の言語の hook の `midturn_main`。 校正は過去の途中の text (後に tool_use が続く text の block) の全部に同じ述語を当てて目で仕分ける。 test は「書き出しの遅れた行を次の呼び出しで見る」「並列の呼び出しで 1 回だけ」「前の turn の最終発話を数えない」 の 3 つを置く。

<a id="transcript-user-message-shape"></a>**「今の turn」 の境界は、 user 行の 2 つの形を両方数える** (実測): desktop の会話記録は、 打ち込んだ発言を `message.content` = **文字列**で記録する。 配列になるのは画像つきの発言と tool_result の行で、 Stop hook の block の理由も文字列の user 行として入る。 境界を「配列で text block を持つ user 行」 だけで探すと、 turn の窓が最後に画像を貼った発言まで伸びる (画像が無ければ空 = hook が黙って何もしない)。 定義は層1 の [`scripts/lib/transcript_turns.py`](../scripts/lib/transcript_turns.py) の `is_real_user` (= type が user で tool_result の行でない) に揃える。 jq なら `select(.type == "user") | select(((.message.content | type) == "string") or ([.message.content[]? | select(.type == "tool_result")] | length == 0))`。 test の fixture は文字列の発言と配列の発言の両方を入れ、 古い画像の発言が窓を伸ばさないことも確かめる。 逆に、 **本人が読んだ返事** (校正・事後の分析で、 本人の発話から次の本人の発話まで) を取り出すときは、 block の理由の行 (isMeta) でも turn が割れるので、 本人の発話の turn まで遡って束ねる (出し直しの turn だけを読むと、 最初の返事の本文と画面下の欄が抜ける。 実測)。

<a id="transcript-human-vs-peer-message"></a>**本人の発言と、 別 session の message・turn の途中に打った発言を見分ける** (desktop の会話記録、 実測): 本人が打った user 行は `origin.kind == "human"` を持つ (hook の差し戻しの行・`isMeta` の行は持たない)。 別 session からの message (`SendMessage`) は、 受け手が idle なら `isMeta` の user 行、 busy なら `attachment.type == "queued_command"` の行で入り、 `origin.kind` は `peer` か無し (subagent の受け渡し `<agent-message from=…>` も `peer`。 実測)。 本文は **先頭に app の system-reminder (「Linked sessions now …」 など、 数百字) が付き、 その後に `<cross-session-message from="local_…">` が来る** (送り手が相手の `uds:/…sock` の宛先に送った message は `from="uds:…"` で、 送り手の session は `from-session="local_…"` にある = `from` だけを引くと、 その送り手の message を数え落とす。 実測) = 本文の先頭の数百字で印を探す判定は素通りして、 別 session の message を本人の発言と数える (実測: 「止めた後に本人が発言したら通す」 gate が、 別 session の message でも通る形だった)。 **origin が human でも本人の発言でない行が 2 つある** (実測): session の最初の prompt (起こした側が渡した起動文 = CLI・SDK の起動も desktop の start_session も。 desktop の記録の親の有無では分けられない) と、 古い版で desktop の send_message が届けた message (本文が `<cross-session-message … encoded="1">` で始まる)。 「本人が今この session と話しているか」 を決める判定は、 最初の prompt と、 本文が `<cross-session-message` で始まる行を数えない (実装例 = [`scripts/owner-window-notice.py`](../scripts/owner-window-notice.py) の `is_human` / `last_human`)。 形は版で変わる = 判定を書く前と app の版が上がった後に [`scripts/transcript-line-shapes.py`](../scripts/transcript-line-shapes.py) で数え直す (行の種類・isMeta・origin・entrypoint × 本文の種類を例つきで出す)。 turn の途中に打った本人の発言は user 行でなく、 `type == "attachment"` の `attachment.type == "queued_command"` (`attachment.origin.kind == "human"`、 prompt は配列で先頭に reminder) として入る = user 行だけを数えると落ちる。 判定は `origin.kind` があればそれで決め (human でも上の 2 つの行は本人の発言にしない)、 無い行は `<system-reminder>…</system-reminder>` を取り除いてから印を探す。 **app の再試行も本人の発言ではない**: API の誤り (接続が切れた等) の応答の行 (assistant、 `isApiErrorMessage: true`) の直後に、 `origin` を持たない user 行で本文が「Try again」 (先頭に reminder) が入る = 上の取り除き方では本人の発言に数えてしまう。 直前の assistant 行が誤りのときの「Try again」 だけを外す (直前に誤りが無ければ本人が打ったもの、 実測)。 実装例 = [`scripts/busy-worker-stop-check.py`](../scripts/busy-worker-stop-check.py) の `_human_text` (reminder を取り除いてから印を探し、 queued_command は origin で見る) と、 それを使う [`scripts/child-wrap-check.py`](../scripts/child-wrap-check.py)。

<a id="transcript-request-copy-lines"></a>**会話記録の API 送信の写しの行 (`type` = `api-request-blob`) は、 前の tool call と結果をもう一度載せる** (実測): 時刻を持たず、 command は送信した時の形 (harness が前に足した `cd <dir> &&` を含む) なので、 記録した command と文字列も hash も合わない。 tool call を数える・command で照合する道具がこの行を読むと、 同じ tool call を 2 回数え、 写しの側は注入記録などの照合先と結び付かない。 tool call を読む道具は `type` が `api-request-blob` の行を飛ばす (例 = [`scripts/headless-worker-reports.py`](../scripts/headless-worker-reports.py) の `COPY_TYPES`)。 行を `type` (user / assistant) で選ぶ [`scripts/lib/transcript_turns.py`](../scripts/lib/transcript_turns.py) は影響を受けない。

<a id="command-guard-calibration"></a>**command を見る PreToolUse guard も同じ手順** (2026-09-12、 [`hooks/zsh-word-split-guard.py`](../hooks/zsh-word-split-guard.py) で実施):
- **過去の Bash command で校正する** = [`scripts/calibrate-bash-command-pattern.py`](../scripts/calibrate-bash-command-pattern.py) `--hook <file>` (hook の `find_issues(command)` をそのまま当てる。 同じ command 文字列は 1 回だけ数える)。 hit を全部読み、 本当の誤用と誤検出を数える。 1 つの hook に述語を足したときは、 その述語を `--func <名前>` で単独に当てる (例 = zsh-word-split-guard の素の `log show` の述語は `--func log_issues`)。 その場の使い捨ての script で較正すると、 docstring に書いた較正の数字を後から誰も再現できない (実測)。
- **時刻と相手の会話記録に依る述語は、 engine に専用の校正の mode を持たせる** — 「宛先が今だれと話しているか」 のように、 command の文字列でなく送った時点の相手の記録で決まる述語は、 上の道具 (command を当てるだけ) では校正できない。 送信を**受け手の側**から数えると、 過去の宛先の解決が要らない (`uds:` の socket は session が終わると解けない = 送り手の側だけで数えると大半を落とす)。 送り手の側でしか見えない経路 (desktop の send_message・掲示板の投稿) は、 その時刻の記録 (desktop の記録・claim) で解いて足す。 例 = [`scripts/owner-window-notice.py`](../scripts/owner-window-notice.py) `--calibrate --all` (知らせる / 間引き / 報告の向きで外す / 該当しない、 の判定つきで全件)。
- **誤検出の型を見て述語を狭める** — 例: `$(…)` の出力を「複数語」 の根拠にするのは分割が目的の文脈 (`for` / `set --`) だけにした (1 行の値を git に渡す誤検出が消えた)。 残る誤検出の型 (同名変数の再利用など) は hook の docstring と規約に書いておく。
- **deny の reason に直し方を入れる** — 誤検出のコストを書き直し 1 回に抑える。

<a id="content-gate-calibration"></a>**file 本文を見る gate も同じ 3 手順** (2026-09-12、公開 repo の commit 本文を検査する gate で実施):
- **go-forward にする (= staged の追加行だけを見る)** — 全文検査にすると過去分で常時 block して gate ごと無視される。既存の記述は grandfather され、新規の混入だけ止まる。副作用として**誤検出も自然に減る**: 誤検出しやすい語 (= 検査 list に普通の英単語と同綴りの項目がある場合) は古い本文には在っても追加行には滅多に現れない。
- **git history の追加行に replay して較正する** — `git log --format=%h -n N` → 各 commit の `git show --unified=0 | grep '^+'` に matcher を当て、**発火数と発火率 (= 何日に 1 回 block されるか)** を出す。頻度は commit/日 に換算して初めて判断材料になる。
- **発火数でなく発火行の性質を数える** — 「N 件発火」 では足りない。1 件ずつ読んで**真陽性 / 誤検出**に仕分ける。仕分けた結果が「全部誤検出の語」 と「全部真陽性の語」 に割れたら、gate を弱めるのでなく **list 側を語ごとに直す** (= 前者は除外、後者は出現側を一般化)。実測例: 600 commit の replay で発火 5 = 5 件とも真陽性、除外候補 4 語のうち 1 語だけが 100% 誤検出だった。
- **配線した直後に、 わざと該当する無害な command を打つ** — deny が返れば、 配線と「足した hook が同じ session で効くか」 ([§9.1](#new-hook-session-snapshot)) を同時に確かめられる。
- <a id="side-effect-tool-live-fire"></a>**副作用のある tool (送信・下書き・書き込み) の guard は、 hook が効かなくても tool 自身が失敗する入力で試す** — 例: 添付の大きさを見る guard には、 中身ゼロの大きな file (sparse) を読めない権限 (`chmod 000`) にして渡す = stat は大きさを返すので guard は判定でき、 tool は読めずに失敗する。 宛先や中身を見ない guard には、 不正な宛先・不正な中身を渡す。 deny が返れば発火の確認になり、 返らなくても何も作られない (実測)。 外へ出て戻せない送信そのものは、 この形でも試さず、 単体テストと宣言の deny で担保する。

<a id="entrypoint-values"></a>**frontend で挙動を変える hook は entrypoint を見る**: engine は起動元を env `CLAUDE_CODE_ENTRYPOINT` に持ち、 transcript の各行にも `entrypoint` として記録する (Stop hook は transcript から読めば env に頼らなくてよい)。 値 (engine の一覧、 実測): `cli` / `claude-desktop` / `claude-desktop-3p` / `claude-vscode` / `sdk-cli` / `sdk-ts` / `sdk-py` / `mcp` / `bench` / `local-agent` / `claude-code-github-action` / `remote` / `remote_desktop` / `remote_mobile` / `remote_cowork` / `remote_trigger` / `claude-in-slack` / `claude-in-teams` / `ssh-remote` ほか。 版で増えるので読み直す = `scripts/claude-app-bundle.py grep '"claude-desktop-3p"' --where engine` ([`claude-app-bundle-reading.md`](claude-app-bundle-reading.md))。 ⚠️ 自己申告の値なので子 process に継承・漏れうる ([`debugging-discipline.md#firing-probe-execute-vs-honor`](debugging-discipline.md#firing-probe-execute-vs-honor) の 2) = 誤判定のコストが小さい用途 (1 回の block・表示の切り替え) に限る。 実例 = [`hooks/chat-file-ref-enforce.sh`](../hooks/chat-file-ref-enforce.sh) (右パネルを持つ `claude-desktop` / `claude-desktop-3p` / `claude-vscode` だけ検査)。

<a id="imitate-target-predicate"></a>**別の program の挙動を判定する hook は、 その program の述語を写す** (実測。 実例 = 上の hook と [`scripts/lib/chat_file_refs.py`](../scripts/lib/chat_file_refs.py)):
- **近似の正規表現で始めない**。 「app がこれを link にするか」「app がこの path を開けるか」 のように相手の挙動を当てる hook は、 相手の判定式を本体から読み ([`claude-app-bundle-reading.md`](claude-app-bundle-reading.md))、 同じ式を写す。 近似で始めた版は、 相手が対象にしない形を拾い (誤検出)、 相手が救済する入力を「失敗する」 と言い (誤検出)、 相手と違う分類で対象を落としていた (見逃し) — 3 つとも、 相手の式を読めば 1 回で揃った。
- **相手の判定は 2 段あることが多い**: 画面側の「形の判定」 と、 実際に処理する側の「解決 (fallback つき)」。 片方だけ読んで規則を書くと、 もう片方の fallback が抜ける。
- **写せない部分は header の限界に書き、 どちらに倒したかを明記する** (例: 相手の絞り込みが実行時の状態に依存するなら写さず、 「失敗する側に数える」 と書く)。 相手の式は版で変わるので、 読んだ版を正本に残す。
- **校正は 2 本立て**: 「検出が正しいか」 (過去の発話に当てて目で仕分ける) と「実害が何件あったか」。 相手が失敗を log に書くなら、 その log が実害の台帳になる。 検出率と実害の件数を並べて初めて、 block の費用 (足りない分の追記がもう 1 通、 §17) に見合うかを判断できる。

<a id="counter-notice-at-injection"></a>**間違いの元が harness や tool の通知なら、 その通知が入った瞬間に反対の事実を 1 回入れる** (事前の知らせ + 事後の網):
- Stop の block は、 書いた後にもう 1 通 (足りない分の追記) を書かせるので高い (全文を出し直させる形は §17 で廃した)。 間違いが「tool call の結果として入る前提」 (例: 作業ディレクトリが変わったという通知) から来るなら、 PostToolUse でその直後に反対の事実を additionalContext で入れる方が安い。
- **効いたかは事前の知らせ単体では見えない**。 事後の網を残し、 その発火率の前後比較で測る (= 2 本は競合でなく、 網が計器を兼ねる)。 比較の基準値と判定の目安は、 導入した turn で carrier (期限つきの観察項目) に書く。
- **頻度は session × 状態ごとに 1 回** (同じ作業ディレクトリで何度も言わない)。 状態は `$TMPDIR` の session id 名の file で足りる (再起動で消えてよい)。 session id は file 名に使う前に文字種を検査する。
- **tool call のたびに走る hook は transcript を全部読まない**。 session を始めたフォルダは先頭の数十行に在る = [`scripts/lib/transcript_turns.py`](../scripts/lib/transcript_turns.py) `session_root_fast`。 2 回目以降は状態 file に控えた値を使い、 解釈系 (python) を起こさない。
- 実例 = [`hooks/chat-path-base-nudge.sh`](../hooks/chat-path-base-nudge.sh) (事前) + [`hooks/chat-file-ref-enforce.sh`](../hooks/chat-file-ref-enforce.sh) (事後)。

<a id="hook-test-foil-teeth"></a>**hook の test にも歯の検査を置く**: 判定を `scripts/lib/` の部品に切り出した hook は、 `scripts/<部品>.mutants.json` に「修正を 1 つ外した版では該当 case が落ち、 隣の case は通る」 を宣言し、 [`scripts/check-foil-teeth.py`](../scripts/check-foil-teeth.py) (run-all-checks が毎回回す) に載せる。 test は `hooks/` に在るので spec の `run` は `{spec_dir}` で元の場所を指し、 部品の写しの dir を env で渡す (test 側は、 その env が在れば写しの dir から hook の読む root を一時 dir に組む)。 **scratch で「修正前の版では落ちた」 と確かめただけでは、 次に直す人が再現できない** (一般則 = ai-collaboration [`physics-verification-cycle.md#scratch-foil-not-bundled`](../../ai-collaboration/conventions/physics-verification-cycle.md#scratch-foil-not-bundled))。 実例 = [`scripts/chat_file_refs.mutants.json`](../scripts/chat_file_refs.mutants.json) (mutant 9 本)。 **assert は理由の文の定型部分にも出る語で書かない**: hook の出力が「何が起きたか」 と「どうすればよいか」 の定型の指示文を合わせて持つと、 指示文の語 (例 = `local HEAD`) はどの結果にも入るので、 その語の有無では判定が付かない (実測)。 可変部の形 (例 = 食い違いを表す `!= origin/`) で判定し、 修正前の版で落ちることを確かめる。 **「出てはいけないものが出ない」 の assert は、 その時の文言でなく禁じた中身で書く**: 失敗の表示から秘密 (blob の bytes・credential・原稿の文) が漏れないことを「その時の見出しの語が無い」 (`grep -q '<見出し>'` の不在) で確かめると、 engine がその見出しを別の語に書き替えた日に assert は黙って真になり、 検査は緑のまま歯を失う (実測: 表示の見出しの語で書いた 2 本が、 engine 側でその語が消えた後も通り続けた)。 **禁じた中身そのもの** (秘密の byte 列が出力に含まれないこと・表示が 1 行であること) で判定し、 その中身を持つ例外を投げる偽の engine を噛ませた回で落ちることを 1 回見る。

---

## <a id="cross-session-hook-concurrency"></a>§13. 並列 session の同じ hook は同時に走る — 状態を書き換える hook は資源ごとの lock を取り、 取れなければ skip と言う

### <a id="cross-session-hook-problem"></a>問題

[§11](#parallel-hooks-no-ordering) は 1 session の中の hook 同士の話。 別の軸として、 **session を複数同時に始めると (desktop の resume と新規、 複数 window) 同じ hook が session の数だけ同時に走る**。 読むだけの hook なら害は無いが、 repo の HEAD / tree / stash、 生成 file、 共有の surface file を書き換える hook は互いの途中状態を読んで壊す。 一方の失敗は他方の成功の後始末として現れるので、 出力が実態と食い違い、 原因の見当が付かない。

### <a id="cross-session-hook-example"></a>実例 (2026-09-12)

session 開始時の auto-pull hook (全 repo を fetch → behind なら ff、 tracked-dirty なら stash → ff → pop) が 2 session で同時に走り、 後発の空振り stash の後の pop が先発の stash を pop、 先発は「stash に残っている」 と誤報した (機構 = [multi-session-coordination.md#stash-push-noop](multi-session-coordination.md#stash-push-noop))。 同じ起動で同時 fetch の ref lock 衝突 ([#concurrent-fetch-ref-lock](multi-session-coordination.md#concurrent-fetch-ref-lock)) も起き、 「fetch 未完了 (timeout)」 と原因を誤って報告していた。

### <a id="cross-session-hook-prevention"></a>防止策

1. **書き換える区間だけを資源単位の lock の内側で行う**。 macOS 標準で動く原子的な操作 = `mkdir <lockdir>` (repo なら `<git common dir>/<name>.lock`。 stash は worktree 間で共有なので common dir)。 lock を取ったら状態を**読み直す** (取るまでの間に相手が済ませているかもしれない)。
2. **取れなければ待たずに skip し、 skip したと出す** (holder の pid と経過秒 + 確認コマンド)。 相手の hook が同じ仕事をしているので session 開始を待たせない。 黙って落とすと「その repo は見た」 と誤読される。
3. **古い lock を拾う**: owner file に `<pid> <epoch> <乱数>` を書き、 pid が死んでいる (`kill -0` 失敗) か取得から一定秒を超えたら古いとみなす。 除去は rename で原子的に行い、 動かした中身が判定時の owner と一致した時だけ消す (不一致なら戻して譲る = 判定から除去までの間に取り直された lock を消さない)。 除去したことも出す。
4. **解放は EXIT trap で**。 lock を `$(...)` / `( )` の subshell で取ると subshell には EXIT trap が継がれないので、 取った path を一時 file に書き、 親の EXIT / TERM / INT trap で「owner の pid が自分」 のものだけ消す。 SIGKILL で残った分は 3. で拾う。
5. **lock だけに頼らない**: 同じ資源を hook 以外の process (人手の git、 別 tool) も触る。 自分の成果物を自分で特定する検査 (stash なら固有 tag + sha で pop) を lock と独立に置く。 実測で、 lock を外しても stash 側の検査だけで最終状態は守られた (二重の防御)。
6. **test は窓を決定的に開ける**: test mode の時だけ効く env (例: 書き換え区間の直前 / 直後で lock を持ったまま N 秒止まる) を足し、 「先発が止まっている間に後発を起動」「途中で外部の actor が状態を変える」 を再現する。 完全同時起動 ×数回の不変条件 test も併置する (同時 fetch のような確率的な事故を拾う)。 test が空振りしていないことは、 旧実装と、 検査を 1 つずつ外した mutation で落ちることで確かめる。
7. **共有 file (surface / cache) は後に書いた側が残る**。 合成が要るなら file 単位の lock、 要らないなら「相手の結果は相手の出力に出る」 と skip 行に書く。

### <a id="cross-session-hook-related"></a>関連

- [§11 #parallel-hooks-no-ordering](#parallel-hooks-no-ordering) (1 session 内の hook 間の順序) / [multi-session-coordination.md#pull-fetch-head-race](multi-session-coordination.md#pull-fetch-head-race) (FETCH_HEAD の並列書換え)。
- 参照実装 = [`scripts/repo-sync-sweep.sh`](../scripts/repo-sync-sweep.sh) + [`scripts/repo-sync-sweep.test.sh`](../scripts/repo-sync-sweep.test.sh)。

---

## <a id="opt-in-side-effect-hook"></a>§14. 人に向けた副作用だけの hook (音・通知) は層1 に既定 off で置き、 marker で opt-in

block も model 向け出力もせず、 人に向けた副作用 (音を鳴らす・OS 通知を出す) だけをする hook。 好みが分かれるので**既定では何もしない**形で層1 に置き、 使う machine だけが有効にする。 参照実装 = [`hooks/turn-complete-sound-nudge.sh`](../hooks/turn-complete-sound-nudge.sh) (応答の終わりに音、 [`macos-claude-app-notifications.md#turn-complete-sound-hook`](macos-claude-app-notifications.md#turn-complete-sound-hook))。

- **opt-in は machine-local の marker file**: `~/.claude/<name>.on` で有効、 `.off` が在れば無効 (off が優先)。 配線 list (`hooks/settings-entries.json`) には全員分入れてよい (marker が無ければ即 exit 0)。 env (`<NAME>=1|0`) は marker より優先 (test と一時的な切替用)。
- **owner の全 machine に配るのは個人層の session 開始 bootstrap**: 「`.on` も `.off` も無ければ `.on` を置く」 だけで冪等になる (done marker が要らない。 user が `.off` を置けば二度と触らない) = [`multi-machine-state.md#one-shot-settings-propagation`](multi-machine-state.md#one-shot-settings-propagation) の「user の変更を上書きしない」 を marker の 2 値で満たす形。
- **surface で gate する** (`CLAUDE_CODE_ENTRYPOINT`) — headless (`claude -p` の routine) で夜中に鳴らさないため。 **許可 list の既定は実測で確かめた値だけ**にする: 2026-09-12 に手元の transcript 196 本を数えたら全部 `claude-desktop` で、 CLI / headless の値は手元に標本が無かった → 既定 = `claude-desktop` だけ、 他は env で足す。 推測した値を既定に入れると、 外れたとき夜中に鳴る向きに倒れる。
- **`stop_hook_active` なら何もしない** (別の Stop hook が block して turn が続いた後の 2 回目)。 その結果、 同じ turn に block する hook が居ると、 副作用は最初の Stop (実際の終わりより少し早い) で 1 回だけ出る。
- **副作用の process は前景で待つ** (上限つき、 例 `afplay -t 3`)。 background に投げると hook の終了とともに切られる可能性がある (検証していない用心。 数秒で終わる副作用なら前景で困らない)。
- **動いた証拠を自分で残す**: 実行したら時刻を `~/.claude/state/<name>.last` に書く。 live 確認と、 他 machine の確認 TODO の完了判定 ([`multi-machine-state.md#machine-gated-pending-action`](multi-machine-state.md#machine-gated-pending-action) の (6)) がこれを読む。
- 命名: block しないので [§0](#naming-convention) の `-nudge` (§0 の表は model 向け出力を想定しているが、 副作用だけの hook も「block しない」 側に入れる)。
- test は副作用の実体を差し替える (再生コマンドを引数を書き出すだけの偽物に、 `$HOME` を一時 dir に) = CI (Linux、 再生コマンドが無い) でも回る。

## <a id="injection-digest-and-relay"></a>§15. SessionStart の注入を 1 ブロックに畳み、 期限の近い item は人に伝えたかを Stop で問う

SessionStart hook の注入は agent の文脈にだけ入り、 人の画面には出ない ([`#surface-reader-is-not-the-owner`](../docs/convention-design-principles.md#surface-reader-is-not-the-owner))。 hook を足すたびに注入の量が増え、 1 件の依頼が他の行に埋もれて agent も人も読まなくなる (実測)。 検出器を増やすのでなく、 **注入を「人が動く・期限が外から決まっている・近い」 item の 1 ブロックに畳み、 短い窓の item は伝えたかを session の終わりに問う** 形にする。 共通部品 = [`scripts/lib/relay_check.py`](../scripts/lib/relay_check.py)。

**畳み方 (digest)**

- **1 本の digest hook だけが注入する**。 他の hook は注入を止めるが、 **副作用 (surface file・台帳・OS 通知・警告行) は止めない** — 共通の出力 helper に「畳む hook 名の list (設定 file)」 を読ませ、 該当なら注入だけを捨てる。 設定が読めなければ畳まない (fail-open = 注入が増える側に倒す)
- **行数の上限で切らない**。 上限を超えた分は読まれない。 条件を絞ったうえで**全件を見出し 1 行ずつ**出す (中身は正本への id で辿る)
- <a id="digest-size-budget"></a>**届く面の大きさにも上限がある**: 注入は一定の大きさを超えると先頭の短い preview だけが文脈に入り、 保険として最初の 1 コマンドで一覧の file を出力させても、 tool の出力は真ん中が切り詰められる (実測。 切り詰めの印は出力に出ていたが、 読み直されなかった)。 行数で切らない代わりに、 届く大きさより小さい**字数の予算**を置き、 超えたら **1 行目**に字数と「file を読み取りの道具で末尾まで読む」 を出す (先頭は preview にも出力の頭にも残る)。 同じ判定 (file の字数) で、 その file を shell で読んだ直後にも読み直しを促す hook を置く (harness の切り詰めの規則は実測で一定しないので、 判定に使わない。 読んだかの判定 = [§19](#command-reads-file-tokenize))。 予算に収めるときは、 最初の返答で伝える段を先頭側に寄せ、 既に伝えた行と自分で置いた期日の再掲から件数に畳む (古い順の先頭の id を残す、 全件を出す command を添える)。 警報の行頭は、 同じ file を読む通知の見張りが拾う印にしない (agent 向けの警報が人の通知に出る)
- **検索の窓 (期間) を出た未処分も件数で残す**: 一覧を「直近 N 日」 の検索で作ると、 窓を出た未処分は件数にも残らず消える。 窓を出る瞬間に前回の一覧から拾って持ち続け、 記録か返信で消す ([`#age-fold-hides-the-stalest`](../docs/convention-design-principles.md#age-fold-hides-the-stalest))
- **畳んだ class は件数だけ 1 行に出す** (「ほかは一覧で: 超過 N / 返事待ち N …」)。 件数行に無い class は黙って消える = hook を畳むときは件数行にも足すまでが 1 単位。 **条件の外に落ちたもの** (±N 日より前に過ぎた等) も件数に入れる ([`#narrowing-makes-input-load-bearing`](../docs/convention-design-principles.md#narrowing-makes-input-load-bearing))。 **種類で分岐する述語は、 どの枝にも入らない組み合わせが無いかを表で確かめる** (実測: 「新規の依頼」 と「既に関わっている会話の続報」 で分け、 続報は期限の近いものだけ行に出していたので、 期限の語が無い続報が行にも件数にも入らなかった = 相手の答えが読まれない)
- **畳んだ hook の出力に新しい段を足すときも、 digest に行を足すまでが 1 単位**。 畳まれた surface に足した段は注入されず、 件数行の 1 つに埋もれる (実測)。 近い item の段なら digest の行に出し (期限の近いものは緊急の印)、 そうでなければ件数行の数え方 (行頭の印) に載るかを確かめる。 例 = [`calendar-conflict-detection.md#folded-injection`](calendar-conflict-detection.md#folded-injection)
- **件数に畳む surface に道具自身の異常の行が混ざるなら、 その行は件数に数えず行で出す**: 件数行の名前は surface の主題 (「新着」 など) なので、
  「動いていない・読めない」 の行が「新着 1」 に見え、 開かれない (実測: 定期の記録係が設置から失敗し続けたのに、 その行が新着の件数に畳まれて気づかれなかった)。
  surface ごとに異常の行の印 (🔴 / ⚠️ など) を宣言し、 digest はその行を件数から外して「道具が動いていない」 の段に行のまま出す。
  同じ係が異常を「前回と違うときだけ」 別経路 (スマホ・chat) に送る形なら、 最初の 1 回が届かなかった異常は二度と送られない =
  送信の結果を確かめる (送信の道具が「送らなかった」 を成功の終了値で返すことがある、 実測)
- **畳んではいけない class** = 自分で決めた期日の reminder (期日当日から数日) と、 条件で発火する reminder (「この日に観察する」 型)。 「外から決まった期限だけ」 に絞ると、 これらが一度も出なくなる。 **日付を差し替えて描画する env** (例 `*_TODAY=YYYY-MM-DD`) を用意し、 発火させたい日付で描いて確かめる。 一般には、 畳む変更を入れる turn に同じ入力で旧表示と新表示を並べ、 旧にあって新に無い行を 1 回列挙する (同 §8.59 の 2。 これを飛ばすと上の 2 class が消えたことに気づけない = 実測)
- **絞るときの既定を件数にしない**: 「急ぎと機械が証明できたものだけ行で出し、 残りは件数」 にすると、 読まなければ急ぎと分からないものは、 だれかが一覧の全体を開くまで読まれない (件数は開かれない、 実測)。 人が 1 人に宛てて書いたものは、 証明できなくても名前を出す ([`#unclassified-defaults-to-loud`](../docs/convention-design-principles.md#unclassified-defaults-to-loud))。 一覧の計算が落ちた回は、 直前に計算できた結果を古さつきで出す ([`#unstaffed-intake-queue`](../docs/convention-design-principles.md#unstaffed-intake-queue))
- **読む主体を置いたら、 読んだ結果を行に出す**: 定時の当番が本文を読んで用件と期限を書き出す形にしたら、 その結果 (受付メモ) を digest の行に付け、 メモの期限を印の計算に入れる。 メモは処分ではないので、 行列からは出さない。 メモの文は本文から来るので、 行の印に見える文字と改行を落とし、 長さを切る (本文を書いた人が一覧の行を偽装できないように。 実装 = [`scripts/lib/mail_intake.py`](../scripts/lib/mail_intake.py) の `make_note` / `apply_notes`)
- **開始時に外部の API を引く hook は、 計算を定時の job に移す**: 同じ event の hook は並列に走るので、 混む回は時間切れになり、 その session に一覧が届かない (実測)。 受け手ごとの定時の job が計算して cache に書き、 開始時の hook は新しい cache を読むだけにする。 cache が古い (job が止まっている) 回は従来どおり開始時に引き、 それも落ちた回は古い cache を計算の時刻つきで出す (時間で失効させて新着を黙って隠す cache にしない)。 cache の行は読むたびに「処理済み」 の台帳で引き直す (job の後に処理したものを出さない)。 取得できなかった部分は前回の行を持ち越し、 全部取れなかった回は cache を書き換えない。 表示回数の台帳に数えるのは開始時の経路だけ (下の「数え方」)
- hook の test root では digest を無効にする (env 1 本)。 そうしないと他の hook の test が注入を見られず落ちる

**数え方**

- 「何 session 表示したか」 の台帳は**注入の経路からだけ記録する** (env で記録を許可)。 dashboard や手動実行からも記録すると、 人に 1 回も見せていないのに回数が増え、 回数で上げる強制が早く発火する (実測)。 用事を受け持つ session へ台帳の上で渡す形 ([`multi-session-coordination.md#designated-handler-session`](multi-session-coordination.md#designated-handler-session)) は、 回数を増やさず、 受け持つ session を「表示した session」 の列に足す (回数は注入の経路が数えたまま)

**伝えたかの検査 (Stop)**

- 対象は**本文の期限まで短い窓 (例 2 日以内) の item だけ**。 期限は経過時間でなく**残り時間**で判定する (経過時間の緊急印は短い窓で逆転する = [`#elapsed-time-urgency-inversion`](../docs/convention-design-principles.md#elapsed-time-urgency-inversion))
- 判定 = この session の assistant の text に、 item の件名の語 (固有の 4 字 / 長い英単語) が 1 つでも出たか。 出ていなければ block して「1 行伝える」 を求める。 **処分 (返信・TODO 化) までは求めない** (初回表示で処分を強制すると印が壁紙になる = [`#surfaced-not-consumed`](../docs/convention-design-principles.md#surfaced-not-consumed))
- 誤判定の cost を 1 block に抑える: `stop_hook_active` なら即 exit 0 / 語が取れない件名は判定しない (止めない側) / import や transcript の読み取り失敗は黙る (fail-open)。 transcript は長い session で大きいので、 対象 item がある時だけ読む
- **伝えても記録されない列には、 2 session 目から処分を問う**: 人から直接届いた mail の行列の最も古い印の行は、 出続けて伝えられても、 行列から出す操作 (記録) がされなかった (実測)。 今も行列にいて未記録で、 2 session 以上見せたものだけ、 処分 (記録か返信) を 1 session に 1 回問い、 行に記録の command を添える
- **workspace の外で動く session (封じた review sandbox など) では止めない** (cwd で gate、 env で外せる) — 隔離した session に外の item を持ち込むと隔離が壊れる
- 句で当てる Stop hook なので、 語の抽出を変えたら過去の transcript で校正する ([§12](#text-pattern-stop-hook))
- 一覧の用事を受け持つ session を 1 つに決める運用なら、 ほかの session には問わず claim もせず、 表示の台帳の上で受け持つ session に渡す ([`multi-session-coordination.md#designated-handler-session`](multi-session-coordination.md#designated-handler-session))

**案件単位で見せる**

- 1 件を処分させるときは、 件名の語を共有する未処理 item を並べる (`relay_check.related`、 多くの件名に出る語では結ばない)。 件名を変えて届いた後続を見ないまま「失効した」 と判定するのは不在の主張 ([`#lapse-claim-is-absence-claim`](../docs/convention-design-principles.md#lapse-claim-is-absence-claim))
- 「返事を待っている義務」 と「その返事が届いた」 のように対になる 2 つの検出を別々の見出しで出さない。 結ぶ鍵 (義務 → スレッド) を持つ検出器の側で、 義務の行に届いた返事を付けて最上段に 1 行で出し、 元の見出しからは外す。 片方の取得失敗を「なし」 と返さない ([`#paired-signals-join-at-render`](../docs/convention-design-principles.md#paired-signals-join-at-render))
- <a id="join-when-reply-outdates-item"></a>**結んで最上段に出す条件を、 待っている項目の急ぎ (期限が近い) で絞らない**: 返事が来ると、 期限に関係なく項目の現在地が古くなる (記録しなければ項目は「返事待ち」 と言い続ける)。 条件 = 返事が項目の最終更新より新しい (日付だけの欄なら、 同じ日は本文に返事の id が無いとき)。 記録すれば消えるので量は増えない (実測: 期限で絞った条件の外にいた返事が、 表示され続けても記録されなかった)。 最上段に出さなかった返事の行にも項目の id と記録の command を付ける (id が行から消えると、 読んだ側は伝えるだけで止まる)。 記録済みでも項目の現在地が返事より古いなら、 項目の行に「返事あり」 を付ける
- <a id="skip-assumption-bound-by-test"></a>**ある部品が「それは別の段に出る」 を前提に処理を見送るなら、 その前提を test で縛る**: 見送る側の test が出す側の述語を import して (写しを持たない)、 見送った item がその段の条件を満たすことを確かめる。 実行時も同じ関数で確かめ、 偽なら 1 行出す (実測: 受付の係は続報の記録を「返事の段に出る」 前提で見送り、 返事の段は期限の近い項目だけを出していた = 期限の遠い続報はどこでも記録されなかった。 部品ごとの test はどちらも通っていた)。 失敗の後に出す「次の回で入る」 も同じ形の前提 = 回復を約束する行を出すなら、 その経路が**その種類の取り残し**を実際に拾うことを test で確かめる (実測: 自分の変更だけを 3-way で commit する無人の書き手は、 commit が落ちた回に「次の回で入る」 と出していたが、 次の回の 3-way は前の回の取り残しを相手の変更として外す。 当てはまったのは書き手だけが書く 1 file だけで、 残りは誰の担当でもないまま作業 tree に残った。 拾い直す形 = [`multi-session-coordination.md#unattended-writer-pending-retry`](multi-session-coordination.md#unattended-writer-pending-retry))

**届いているかの確認**

- 注入も Stop も hook が生きていることが前提。 root 限定の kill switch で全 hook が止まっても session の中からは見えない ([§2 補足 2](#disableallhooks-kill-switch)) ので、 hook と独立した経路 (定期実行の OS 通知など) で「hook の最終実行が古い」 を出す。 注入がどの session に届き、 どの印で出たかは transcript から数える ([`scripts/injection-reach-audit.py`](../scripts/injection-reach-audit.py)、 [`#surface-reader-is-not-the-owner`](../docs/convention-design-principles.md#surface-reader-is-not-the-owner))

---

## <a id="typed-confirmation-in-git-hook"></a>§16. git hook の「打ち込みで確認」 は、 機械で確かめられる事実なら機械で確かめる

### <a id="typed-confirmation-problem"></a>問題

push 先が非公開か・送り先が正しいか のような事実を、 hook が「YES と打て」 と人に確かめさせる形は 3 つの壊れ方をする (実測):

1. **入力を待つあいだ接続が開いたまま** — pre-push は remote への接続を張った後に走る。 人が打つまでの間に相手側が無通信の接続を切り、 確認が通っても送信は失敗する。
2. **入力が届かない端末がある** — agent が開いた端末の tab で、 打鍵が hook の `read </dev/tty` に届かず確認が待ち続けた (原因は未確定)。 人から見ると止まらない処理に見え、 手で process を止めることになる。
3. **端末の無い実行 (agent の shell・無人 job) では必ず止まる** — hook の中止メッセージが検査を飛ばす flag を案内していると、 それが次の手になる (= gate を外す操作を hook 自身が教える)。

### <a id="typed-confirmation-prevention"></a>防止策

- 確かめたい事実を API で読む (例: GitHub の repo の公開設定 = `gh repo view <owner>/<repo> --json visibility`)。 期待どおりなら通し、 違えば止める。
- 読めないとき (API の無い remote・CLI が無い・呼び出しの失敗) だけ打ち込みの確認に倒れ、 端末が無ければ止める (= 読めないことを「確かめた」 に畳まない)。
- 中止メッセージには「何が確かめられなかったか」 と「どう直すか」 を書き、 検査を飛ばす flag は書かない。
- 変えたら、 期待どおりの値・違う値・存在しない対象・API の無い remote・CLI の無い PATH の 5 通りを hook 単体に引数で渡して確かめる (pre-push は `$1` = remote 名・`$2` = URL で直接呼べる。 終了値は pipe の後ろの command でなく hook 自身のものを見る)。

---

## <a id="stop-hook-addendum-not-reemission"></a>§17. Stop hook は返事の「全文の出し直し」 を要求しない — 不足の追記だけ、 または返事の前に要求を出す (2026-09)

Stop hook が「この行が無い → 返事の全文を出し直す」 と止めると、 assistant は 1 行足した全文を再送し、 本人の画面には**同じ返事が
2 通** (2 回止まれば 3 通) 並ぶ。 要求される行が返事を書く前に分からない種類 (他 session が残した記録、 処理済み判定が外れて再要求
される行) だと、 1 回目で正しく書いて避けることができず、 **毎 turn 構造的に重複する** (実測: 1 turn に 2〜3 回)。

形の規則:
- **不足の行だけを短い追記として要求する** (本文の再送を求めない)。 受理の照合の条件は「repo/file と引用が同じ行にある」 に置き、
  注釈が付いても・折り畳んだ区画の中でも当てる。
- **返事の前に知らせられる要求は前に出す** (UserPromptSubmit / PreToolUse で「この turn の返事に入れる行」 を注入 = SessionStart の
  一覧と同じ内容を毎 turn 先出し)。 Stop は最後の網であって、 最初の通知面ではない。 **要求を生む書き込みの経路を全部数えて、
  どの経路にも先出しを付ける** (編集 tool / Bash の commit / 道具自身の CLI 〔候補を写す・記録を足す subcommand〕)。 1 経路でも
  抜けると、 その経路の変更だけが Stop で差し戻され返事が 2 通になる (実測: 道具自身の CLI で写した変更だけ先出しが無かった)。
  PreToolUse の additionalContext は transcript に `hook_additional_context` の record として残る = 変更の tool の直後にその
  record が無ければ、 先出しは出ていない (経路の抜けはこれで数える)。
- **Stop で受理した行は同じ turn で処理済みに書く**。 次の turn・次の session で同じ行を再要求したら、 それは処理済み判定の欠陥で、
  本人に何度も同じ行を読ませる。 selftest に「1 度受理した行は再要求されない」 を入れる。
- 本人に読ませる量に上限を置く (件数 or file 単位の集約)。 chat の返事は本人が読む面で、 台帳ではない = 一覧が長いなら file に
  書いて pointer を出す。
- §12 (発話を見る Stop hook) と同じ校正を要る = 過去の返事で「同じ行を書いたのに再要求された」 turn を数えてから配線する。
- **差し戻しの直後の Stop (`stop_hook_active=true`) でも照合は回す** (差し戻さないだけ)。 そこで即 exit すると、 追記に書いた行が
  処理済みにならない (実測: 追記でだけ書かれた行が、 別の session の開始で再要求された)。
- <a id="deictic-after-addendum"></a>**追記を読んだ本人の次の短い指示は、 追記でなく本題を指すことが多い** (受け手の assistant の側の規則):
  追記は本人が頼んでいない一覧で、 返事の最後に来る。 本人が指示語だけの短い指示 (「その旨」「それで」「じゃあそれ」) を返したとき、
  画面で最後に読んだ追記の項目に結ばず、 本人が始めた本題に結ぶ。 決めかねるなら、 返事の 1 行目でどちらと読んだかを言う
  (実測: 追記の最後の項目に向けて下書きを作り、 本題の側だと訂正された。 1 行目に解釈を書いていたので 1 往復で戻れた)。
- **照合の順序**: 印字した行そのものを持つ返事の行を、 先にその記録へ当てる。 残りを緩い条件 (引用の冒頭の一致など) で当てる
  (冒頭が同じ別の記録に行を取られない)。 前の返事を出し直した再送の中の同じ行は 1 本に数える (再送で別の記録を処理済みに
  しない)。 表示がまったく同じになる記録は 1 行 (×N) で全部 (本人にとって同じ情報を何度も読ませない)。
- **文面の点検は「出し直す」 の語だけで探さない**: 「最終メッセージに〜を書いて」「最終メッセージの先頭に〜」「同じ内容で
  終了」 を促す文、「〜に書き直してから終了」 も全文の再送を招く (実測: 「出し直」 で grep して文面を揃えた後も、 これらの
  文面の Stop hook で同じ返事が 2 通並んだ)。 求める形は「短い追記に〜を書く」 と明示する。 受理の判定が session (か turn) の
  assistant の文の全部を読む形なら、 追記でそのまま受理される。
- <a id="stop-block-reason-delivered-twice"></a>**block の理由は model に 2 通届く (harness 側の挙動、 hook では消せない)**:
  1 回の block につき transcript に meta の user 行 `Stop hook feedback:\n<reason>` と attachment `hook_blocking_error`
  (`rendered` = `Stop hook blocking error from command: "<command>": <reason>`) が 1 組ずつ残り、 継続の request に両方が入る
  (transcript の組は 2.1.266〜2.1.286 の desktop と `claude -p` で実測。 継続の request に両方が入るのは 2.1.286 の desktop で
  model の側から実測し、 同じ版の本体で、 Stop の処理が attachment を継続の messages に積み、 同じ理由から作った meta の行も
  積むことを読んだ。 TaskCompleted / TeammateIdle の hook も同じ形)。 hook の二重実行と取り違えない =
  `stop_hook_summary` の `hookInfos` に同じ command が 1 回・`hookErrors` が 1 件なら hook は 1 回しか走っていない
  (配線の重複を疑う前にここを数える)。 帰結: 理由文は 2 倍の context を食う前提で短く書く。 user の画面に同じ返事が
  2 通並ぶのはこれとは別の原因で、 全文の出し直しを求める文面から来る (この節の冒頭と 1 つ上の項)。
- **挙動は transcript で実測する**: `hook_blocking_error` と meta の `Stop hook feedback` 行 → 書き直した返事 → `stop_hook_summary`
  の並びを、 hook が書く state の時刻と突き合わせる (実測: 処理済みの記録時刻が「差し戻しの後の Stop」 でなく、 その後に別の通知で
  走った Stop に揃っていたことで、 差し戻しの後の照合の抜けが分かった)。
- **照合の不具合を直したら、 溜まった誤った状態は証拠から照合し直す** (state を手で書き換えない) = [`convention-design-principles.md#reconcile-from-evidence`](../docs/convention-design-principles.md#reconcile-from-evidence)。

## <a id="shared-state-file-merge"></a>§18. 並列の session の hook が同じ state file を読んで書くなら、 lock の中で読み直して合わせる (2026-09)

hook の state (処理済みの記録・割り当て・既読) を「読む → 判定する (transcript を読むので秒かかる) → 全体を書き戻す」 と、
その間に別の session の hook が書いた分を古い読みで上書きして消す (lost update)。 並列の session は普通にあるので、 窓は小さく
ても起きる (実測: 古い読みで書く 24 並列の試験で、 lock なしの版は 24 件中 2 件しか残らなかった)。

形の規則:
- 書く直前に lock (`fcntl.flock` を state の隣の `.lock` file に) を取り、 **lock の中で file を読み直して合わせてから**書く。
  判定に使う他の file (記録の log など) も lock の中で読む。
- 足すだけの欄 (処理済み) は和。 付け替える欄 (割り当て) は **3 方向**で合わせる = 読んだ時点の写しを持ち、 読んだ後に**自分が
  変えた key だけ**を上に重ね、 自分が外した key だけを外す (全体を重ねると、 別の session の新しい付け替えを古い値に戻す)。
- 型の壊れた欄は読まずに上書きして直す (読むところで落ちると、 その hook は以後ずっと書けない)。
- tmp の file 名は process ごとに分け (`<name>.<pid>.tmp`)、 書きかけは `finally` で消す。
- selftest に「古い読みで書いても、 間に別の session が書いた分が残る」 と「付け替えを戻さない」 を入れる (並列の fork で数える)。

## <a id="command-flag-normalization"></a>§19. command の option を当てる hook は、 略形と同じ効果の別経路まで正規化してから当てる

- **git の long option は一意な前置の略形を受け付ける** (hook を飛ばす option も、 途中まで打った略形で同じく効き、 hook が走らない = 実測)。 綴りどおりの照合はこれをすり抜ける。 当てる前に、 その subcommand の option 表から一意な前置を正規の形へ展開する
- **同じ効果の別経路も当てる**: `-c core.hooksPath=…`、 `git config core.hooksPath`、 `GIT_CONFIG_PARAMETERS` / `GIT_CONFIG_KEY_n`、 検査が読む環境変数の上書き
- **当て切れない経路は docstring に列挙する** (変数に入れた command、 script file の中、 git alias、 `.git/hooks` の直接の編集)。 書いていない穴は「守られているつもり」 になる
- <a id="command-reads-file-tokenize"></a>**command が file を読む (書く) かを当てる hook は、 heredoc の本文と引用符の中を command と読まない**: command の全文から「読む語 … file 名」 を正規表現で探すと、 heredoc で文書に追記した本文・commit message・`echo` の文字列の中の同じ並びで発火する (実測: 誤発火を直す確認の command の中の python の heredoc でも発火した)。 heredoc の本文 (`<<'EOF'` の次の行から終端の行まで) を除き、 shlex などで `; & | ( )` と改行を区切りに単純 command へ分け、 先頭の語 (`X=1` の代入・`command`・`sudo` などの前置きを除く) と引数で判定する。 `cd … &&` の後・pipe の前・`<` の入力・引用符で囲んだ path は読む側に数える

## <a id="git-fixture-pinned-dates"></a>§20. test の git fixture は日付を固定する — 同じ秒に作った 2 つの履歴は同じ sha になる

履歴の書き換え・追従・分岐を test する fixture で、 「旧い履歴」 と「新しい履歴」 を同じ秒の中で作ると、 中身と日付が同じ commit は同じ sha になり、 分岐していないように見える (速い CI の runner でだけ再現し、 手元では通る = 実測)。 `GIT_AUTHOR_DATE` / `GIT_COMMITTER_DATE` を commit ごとに別の固定値にする。

## <a id="autofix-hook-path-commit-stale-index"></a>§21. 自動修正して再 stage する pre-commit と `git commit -- <path>` を合わせると、 本当の index に修正前の版が残る

並列の session と同じ repo を触るときは `git commit -- <path>` で index を経由せずに commit する ([`multi-session-coordination.md#staging-window-race`](multi-session-coordination.md#staging-window-race))。 このとき git は一時の index で commit を作るので、 pre-commit が file を書き直して `git add` した分は、 一時の index と commit には入るが、 本当の index には修正前の版が staged のまま残る (実測: commit = 修正後、 index = 修正前、 working tree = 修正後、 `git status --short` は `MM`)。 残った staged の差分は「修正を戻す変更」 なので、 次に誰か (並列の session を含む) が path を指定せずに commit すると、 修正が消える。

- 自動修正する pre-commit がある repo では、 path 指定の commit の後に `git status --short -- <path>` を見る。 `MM` か `M ` が出たら `git reset -q -- <path>` で index だけを HEAD に戻す (working tree は hook が直した版 = HEAD と同じなので触らない。 これで消えることを確かめた)
- hook を書く側: 自動修正したら、 直した path を 1 行出す (path 指定の commit をした人が index を見直すきっかけになる)

## <a id="git-race-fixture-via-hooks"></a>§22. git の race (HEAD が動く窓) を test で決定的に再現する — fixture の repo の hook に相手の commit を打たせる

並列の session が同じ repo に commit する race を直す道具は、 窓を sleep で狙っても再現しない。 fixture の repo の hook に「相手の commit」 を 1 回だけ打たせると、 窓を決定的に開けられる (実測 = 一時 index で commit する道具の selftest、 実装例 = [`../scripts/git-commit-own-hunk.py`](../scripts/git-commit-own-hunk.py) の `move_head_in_hook` / `late_commit_on_top`)。

| 開けたい窓 | 置く場所 | 起きること |
|---|---|---|
| `git commit` が HEAD を読んだ後、 ref を更新する前 | pre-commit の中で commit する | 外側の commit は `fatal: cannot lock ref 'HEAD': is at X but expected P` で止まる (commit は入らない) |
| 自分の commit の直後 (道具が HEAD を読み直す前) | post-commit の中で commit する | HEAD が相手の commit になる = commit の後に HEAD を読み直して自分の commit とする道具の誤りが出る |
| 道具が版を作った後、 `git commit` を打つ前 | 道具に test 専用の環境変数で shell を 1 回走らせる口を持たせる (この窓には git の hook が無い) | commit の直前に親を照合しない道具は、 相手の変更を戻した commit を作る |

- **1 回だけ打たせる**: 中の commit を打つ前に marker file (`.git/<名前>-once`) を書き、 marker があれば何もしない (中の commit でも同じ hook が走るので、 2 回目はここで止まる)。 post-commit には件名などで「外側の commit の時だけ」 の条件も付ける
- ⚠️ **hook の中の commit は `GIT_INDEX_FILE` を外して打つ** — git は hook に、 外側の commit が使っている index (一時 index ならその path) を `GIT_INDEX_FILE` で渡す。 外さないと相手の commit が外側の index に入る
- ⚠️ **外側が一時 index で commit した直後は、 本当の index が新しい HEAD より古い** — post-commit の中でそのまま `git add` + commit すると、 相手の commit が外側の変更を戻す (`--allow-empty` も空の commit にならない。 実測 = fixture の誤りを道具の誤りと取り違えかけた)。 相手の commit の前に `git reset -q` で index を HEAD に揃える。 本物の並列でも同じ形で起きる (共有 index の race = [`multi-session-coordination.md#temp-index-commit`](multi-session-coordination.md#temp-index-commit) の ⑥)
- 古い実装でその test が落ちることを先に確かめる (fixture が窓を開けていなければ、 直した道具でも古い道具でも通る)

## <a id="dry-run-model-authored-script"></a>§23. model が書いた script を hook が空回しするとき、 node の `vm` は隔離にならない — 起動の flag で閉じる

起動の前に、 model が書いた script (Workflow の script など) を偽の関数の上で空回しして本数・形を数える hook は、 その script を外から来た code と同じに扱う。 hook は user の権限で走るので、 script が hook の process に届けば file も別の process も手に入る。

- **`vm` の別 context は隔離ではない**: `vm.runInNewContext` に渡した関数・object の `constructor` を 2 段辿ると host の `Function` に届き、 `Function('return process')()` で host の `process` を取れる (実測 = 空回しの selftest に置いた脱出の例が host の process を読めた)。 Node の文書も `vm` を安全の仕組みとしては使うなと書く
- **閉じ方 = node を起こす flag**: `--disallow-code-generation-from-strings` (文字列から code を作る `Function` / `eval` を止める) と permission model (`--permission --allow-fs-read=<runner の file>` = 読めるのは runner だけ、 書き込み・子 process・worker も止まる。 node 20 は `--experimental-permission`)。 flag を知らない node (19 以下) では走らせずに「数えられなかった」 を返す — flag なしに落として回すと、 古い node の機械でだけ黙って隔離が外れる
- ⚠️ **macOS の一時 dir は symlink の下**: `tempfile` の dir は `/var/folders/…` で、 `/var` は `/private/var` への symlink。 `--allow-fs-read` に symlink の側の path を渡すと、 node が path を解決する途中で `/var` を読もうとして runner を開く前に止まる (`Access to this API has been restricted. Use --allow-fs-read …`、 resource = `/var` = 実測)。 path は `os.path.realpath()` を通して渡す
- **script と入力は stdin で渡す**: file で渡すと `--allow-fs-read` をその file まで広げることになる
- **selftest に脱出の例を 1 つ置く**: 上の `constructor` の形で `process` を取りにいく script を空回しし、 止まることを見る。 flag を外した版で脱出できることを 1 回見る (= test に歯がある)。 flag を知らない node は、 `bad option` を返す偽の node を `PATH` か環境変数で差して確かめる
- **hook は fail-open**: 空回しが失敗したら起動を止めずに通し、 数えられなかったことを 1 行出す (止めるのは数えて問題が出たときだけ = [`#engine-failure-must-not-block`](#engine-failure-must-not-block) と同じ)

実装例 = [`scripts/workflow-estimate.py`](../scripts/workflow-estimate.py) の `dry_run()` と selftest (配線 = [`hooks/workflow-fanout-check.sh`](../hooks/workflow-fanout-check.sh)、 規約 = [`multi-session-coordination.md#workflow-fan-out`](multi-session-coordination.md#workflow-fan-out))。

## <a id="related-docs"></a>関連

- `claude-config/setup.sh §Step 2 install_hooks()` — 配信機構の正本 (= delivery 軸 (a) symlink + (b) settings.json を atomic 化する reference implementation。 (c) logic は hook script 側、 (d) invoke 経路は claude-code harness 側で別 layer)
- `claude-config/hooks/*.sh` — 既存 hook 8 個 (= 本 file 作成時点)。 §1 (bash 3.2 trap) の audit 対象
- `conventions/multi-machine-state.md` — 多マシン audit 規律 (本 file と相補、 hook 配信が drift する具体例として cross-reference)
- `docs/personal-layer.md` — layer 3 個人層 hook の配置規律 (= claude-config 側 hook と layer 3 hook の責務分離)
