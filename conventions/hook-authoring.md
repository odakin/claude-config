# Claude Code hooks の作成 + 配信規律
<!-- slug index: hook-authoring.index.yaml — cross-ref sections by #slug (stable), not §-number. See convention-design-principles §14.2 / §14.7. -->

> 適用対象: `claude-config/hooks/` (= layer 1) + 個人層の `<personal-layer>/hooks/` (= layer 3) の hook script 全般。 hook 作成・配信・audit の **3 種類の構造的 trap** を扱う。
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

---

## <a id="bash32-heredoc-parser-bug"></a>§1. bash 3.2 の `$(...)` + heredoc body の quote escape parser bug

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

### <a id="bash32-debug-difficulty"></a>Debug が困難な理由 / メタ規律

- minimal isolated test (= heredoc 1 個を `$(...)` 無しで実行) は通る → 「block の中身が壊れた」 と reflex 判定しがち。 真因は **block 間 interaction** (= 外側 parser が内側 body を scan する parser bug)
- 「error 報告行」 と「真因行」 が大きく乖離する → 修正対象を誤特定して時間を溶かす

**メタ規律**: hook を書いた直後に `/bin/bash -n <hook>` で syntax check + minimal stdin で 1 回 fire 確認。 homebrew bash で書いて満足しない。 macOS stock bash で fail する書き方を完成形と認識する事故を予防。

---

## <a id="delivery-audit-4-axes"></a>§2. hook 配信正常性の 4 軸 audit (= 1 軸欠けて silent malfunction)

### <a id="delivery-audit-problem"></a>問題

claude-code が hook を起動するには **4 軸全てが揃う必要**:

| 軸 | 配信先 / 確認方法 | 失敗時の症状 |
|---|---|---|
| (a) **symlink target 健全性** | `~/.claude/hooks/<name>.sh` が存在し target も存在 (= `[ -e <path> ]` が true) | hook spawn 即 fail。 claude-code は exit code を log するが user 通常見ない |
| (b) **settings.json entry** | `~/.claude/settings.json` の `hooks.PreToolUse[]` (または PostToolUse) に該当 command path が登録 | claude-code が hook を invoke しない。 stderr 不在で気付かない |
| (c) **logic 健全性** | realistic JSON stdin で hook 起動 + 期待出力 (= ask JSON / warn 出力 / silent) 確認 | (a)(b) OK でも logic bug で空振り、 false negative |
| (d) **harness invoke 経路の生死** | hook 先頭に trace block 投入 → 実 tool call → trace log 作成確認 | (a)(b)(c) 全 OK でも claude-code 側の bug で hook が起動しない silent failure。 既存 audit-hooks.sh script は (a)(b)(c) のみ check するので green でも (d) は fail し得る |

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
0. **`echo $CLAUDE_CODE_ENTRYPOINT` を確認** — `claude-desktop` なら **hook 出力がモデルに反映されない** (= hook は実行されるが harness が出力を honor しない、 §9.3)。 desktop session での「効かない / 非発火に見える」 は配線の問題ではないので、 1-4 を audit する前にここを見る (= 誤帰責の最頻原因)。
1. `[ -e ~/.claude/hooks/<name>.sh ]` (= symlink target 健全?)
2. `jq -e --arg c "<name>.sh" '.hooks.PreToolUse[] | select(.hooks[]?.command | contains($c))' ~/.claude/settings.json` (= entry 存在?)
3. realistic JSON stdin で hook 起動 → 期待出力 確認 (= logic 健全?)
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

**audit script の現状**: `claude-config/scripts/audit-hooks.sh` は (a)(b)(c) 3 軸の sweep を実装済 (= `setup.sh` Step 3 後の delivery 検証 + dashboard 統合)。 (d) 軸 は trace 投入 / revert の atomic 化が必要なので別段の implementation が要、 本 file (2026-05-21) では未実装で manual protocol のみ documented。

**hook 配信 drift の根本因**: setup.sh が periodic 実行されないと、 claude-config に新 hook を commit / 既存 hook の symlink target を変更しても、 各マシンの `~/.claude/hooks/` への配信は遅延する。 対処の候補:
- (i) setup.sh を post-merge git hook で auto-run (= 既存 Step 6 で claude-config 自身の post-merge は導入済、 hook install step もここで毎回 idempotent 再実行する余地)
- (ii) dashboard に delivery 3 軸 (= (a)(b)(c)) audit を組み込み、 drift を session 開始時に surface
- (iii) hook ごとに self-test を持たせ、 hook 自身が起動時に自分の配信状態を log

setup.sh 自体は idempotent design なので (i) は実装コスト低。 但し `git pull` のたびに走るとうるさい場合あり、 trade-off は user 判断。

### <a id="tool-matcher-coverage-boundary"></a>§2 補足: tool-matcher の coverage boundary — Bash/script write は Edit/Write guard を素通りする

配信が健全 (= (a)(b)(c) 全 green) でも、 PreToolUse hook は **登録した matcher の tool にしか fire しない**。 `PreToolUse(Edit|Write|MultiEdit)` guard は **Bash / script (`python ... open(w)` / `cat > f` 等) で書いた file を一切見ない** (= それらは Edit/Write tool call でないため)。 bug ではなく matcher の設計境界 (§2 (d) の harness-invoke-bug 〔Bash matcher が bug で fire しない〕 とは別軸)。 guard を分類すると塞ぎ方が決まる:

- **path-based guard は Bash matcher を足せる**: `memory-guard.sh` (Edit/Write) + `memory-guard-bash.sh` (Bash) は「memory dir への write か」 を **path** で判定するので Bash 版が作れる。 `google-url-guard.sh` も Edit/Write/MultiEdit/**Bash** を cover。
- **content-based guard は commit-time が authoritative layer**: `public-leak-guard.sh` は Edit/Write/MultiEdit のみ (Bash matcher なし) → **public repo の file を Bash/script で書くと PreToolUse leak-guard を素通りする**。 これは設計上むしろ正しい — leak 判定は**書かれる content** を見る必要があり、 Bash-write の content は command 内で生成・埋込されて静的 scan が困難。 backstop は **commit 時の `public-precommit-runner.sh` + `commit-msg-leak-guard-runner.sh`** (= materialize 済の staged content を scan するので書き方を問わず cover)。 = **public repo leak gate の真の layer は commit-time git hook、 PreToolUse leak-guard は早期 catch の best-effort**。
- 実例 (2026-06-10): SESSION.md を python script で hot/cold split した際、 PreToolUse leak-guard は不発火、 commit-time gate + 手動 grep で安全確認した。

→ guard を設計するとき「守りたい write は Edit/Write だけか、 Bash も含むか」 を明示する。 path-based なら Bash matcher を追加、 content-based なら commit-time gate に backstop を置く (= PreToolUse 単独で content leak を完全には塞げない)。

---

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

hook A が末尾で hook B を呼ぶ (= chain) 構造で、 A が **自身の no-op 条件**で early-exit すると B に到達しない。 B は呼ばれないだけで error を出さず silent dead になる (= §2 の silent malfunction の chain 版、 `docs/convention-design-principles.md §8.8` の false confidence)。

### <a id="chain-hook-example"></a>実例 (2026-06-06 RCA)

pre-commit hook A (= LaTeX Unicode fixer) が「対象 file (LaTeX) が staged されてなければ exit 0」 と early-exit。 A は末尾で layer-3 chain hook B (= yaml/data gate) を呼ぶ設計だったが、 対象外 file のみの commit (= data file のみ) では A が early-exit して B に未到達。 B にした gate が **silent dead**。 B が catch すべき violation を仕込んだ commit が reject されず通る **実 commit e2e で初めて発覚** (= logic 確認・syntax 確認・関数シミュレートは全て pass していた、 実 e2e のみが expose した)。

### <a id="chain-hook-prevention"></a>防止策

- chain hook を呼ぶ primary は **自身の no-op 条件で early-exit しない**。 primary の処理を `if [[ 条件 ]]; then ...; fi` で囲み、 chain は無条件に末尾で呼ぶ (= chain は primary の関心事と独立に走るべき)。
- **chain reachability を実 e2e で verify** (= §2 の 4 軸 audit に加える 5 軸目)。 chain B が catch すべき violation を実際に仕込み、 primary A の no-op path (= A が何もしない commit) でも B が発火するか確認する。 logic / syntax / シミュレートでは expose できない (= 本 RCA がまさにそれらを通過していた)。

---

## <a id="build-dependent-behavior"></a>§9. hook の挙動は build 依存 — 同 session snapshot + feature 差 (= upstream docs を鵜呑みにしない)

claude-code の hook 関連挙動は **running build によって docs と乖離する**。 最新 docs を読んだだけで「こう動くはず」 と assert すると、 古い build で silent に外れる。 inline §3 (= 単一情報源で結論に飛躍しない) の hook domain instance。

### <a id="new-hook-session-snapshot"></a>9.1 新規 hook は同 session で live 発火しない (= session 開始時 snapshot)

**実測 (2026-06-10、 Opus 4.8 1M harness)**: settings.json に hook を **mid-session で追加しても、 その session 中は発火しない**。 = この build は hook 設定を **session 開始時に snapshot** する。

**discriminator** (= 「snapshot build か hot-reload build か」 を実測): throwaway hook (= `echo fired >> /tmp/x`) を **`Read` (または `Write`/`Edit`) matcher** で mid-session 登録 → 該当 tool を 1 回叩いて `/tmp/x` を確認 → **不在 = 未発火 = snapshot build**。 ⚠️ **discriminator に `Bash` matcher を使わない**: §2(d) の harness-invoke bug で Bash hook は snapshot と無関係に発火しないことがあり結果が交絡する (= 2026-06-10 に最初 Bash で試して confound に気付き、 `Read` matcher で取り直して snapshot を clean に確定した)。

⚠️ 最新 docs は逆 (=「settings files を watch して `hooks` も hot-reload する」) と記載。 つまり **reload timing は build 依存**。 docs の hot-reload 記述を根拠に「今 足した hook が今 効く」 と assume しない。

**§2 / §6 の verification への含意** (= 重要):
- §2 (c) logic 健全性 (= realistic JSON を stdin で hook を直接起動) は **同 session で可** (= harness 配線と独立に script を実行)。 hook を書いたら必ずこれで logic verify。
- §2 (d) trace / 実 tool call での live 発火 verify は、 **新規 hook では同 session で不能** (= snapshot ゆえ未配線)。 **新 session を開いてから** verify する。 同 session の非発火を「matcher bug」 等と誤判定しない (= 2026-06-10 に実際この誤帰責を一度した)。
- §6 (P1) の「該当 hook 全件で try-fire pass」 gate も、 新規追加 hook は新 session 必須。
- **新規 hook 追加の作法**: ① stdin JSON で logic unit-test (同 session) → ② install + (a)(b) 配線 audit (同 session) → ③ live 発火は次 session で確認。

### <a id="build-dependent-docs-drift"></a>9.2 同種の「docs と乖離」 build 依存 feature

| feature | 最新 docs | 実測された乖離 | robust な cross-build 選択 |
|---|---|---|---|
| settings.json hook の hot-reload | する | 2026-06-10 build は snapshot (§9.1) | 新 session で live-verify |
| PreToolUse の `permissionDecisionReason` field | 支持 | 2026-05-29 build は JSON に含めると **hook 出力ごと silent skip** (= mail-send-guard RCA) | narrative → stderr、 stdout は minimal JSON (= `permissionDecision` のみ)。 既存 convention |
| PreToolUse `updatedInput` で tool 引数 rewrite (= default 注入) | 支持 (= allow/ask + 全 field 含め replace) | 古い build での support 未確認 | deny + 再発行 のほうが古い build でも確実 (= `<personal-layer>/hooks/calendar-reminder-guard.sh` が deny を選んだ理由) |

**メタ規律**: hook 挙動を docs だけで assert せず、 ① logic は stdin で unit-test、 ② live 発火・新 field は **実測** (= throwaway hook / 実 tool call / 新 session)、 ③ 不確実な feature は **古い build でも動く path** を選ぶ (= stderr narrative / deny / new-session verify)。

### <a id="frontend-dependent-cowork"></a>9.3 frontend 依存 — **Claude desktop (Cowork) app は hook を実行はするが、 その出力をモデルに honor しない**

hook の効きは build だけでなく **frontend (= terminal CLI / IDE 拡張 / desktop app)** にも依存する。 **実測 (2026-06-13、 desktop 埋込 build 2.1.170。 初回 session = PreToolUse 非効きを発見、 同日の cold-eyes 再検証 session で機構を精緻化)**:

- **SessionStart hook**: desktop でも **プロセスとして実行される** (= 撤去前提の trace hook 〔stdin + 親プロセス path を記録〕 を SessionStart に仕込み、 desktop が `source:startup` の session を生成するたびに発火するのを確認。 親プロセス = 埋込 build 2.1.170)。 **だがその出力 (stdout / `additionalContext`) はモデルの文脈に注入されない** (= 同 hook に unique marker を載せ、 fresh な desktop session に「marker が見えるか」 と問うと「ない」。 加えて検証 session 自身が session 開始時に currentdate-anchor 〔無条件出力〕 や horizon の reminder を一切受領していない)。 ∴ **副作用 (file 書込等) は起きるが、 context injection は捨てられる**。
- **PreToolUse hook**: その **permissionDecision (deny/ask) が honor されない** (= session 開始時から snapshot に在る memory-guard 〔marker 無し memory write を hard-deny するはず〕 が desktop で素通り。 deny 型ゆえ `bypassPermissions` でも隠れない零交絡で確定)。 execution 自体の有無は未分離 (= 初回 session の §2(d) trace 不在は **mid-session 追加による §9.1 snapshot 交絡**の可能性があり、 「実行されない」 と断定しない。 確実なのは「効果が届かない」)。
- **正確な像** = **「desktop は hook を実行はするが、 モデルに向かう出力 (SessionStart の context injection / PreToolUse の permission 判定) を harness が honor しない」**。 旧版の「hook を一切実行しない」 / 「SessionStart も発火しない兆候 (cache stale)」 は **不正確** (= cache stale は SessionStart hook が呼ぶ calendar 取得補助 〔EventKit 経由の外部 binary〕 側の失敗 〔Terminal の TCC 不足等〕 が原因で、 hook 非実行の証拠ではなかった)。
- **declarative permission との非対称**: 同じ desktop でも `~/.claude/settings.json` の `permissions.deny` は **honor される** (= 無害な deny 対象コマンドを叩いて block を実測)。 honor されないのは hook 出力と承認フロー (ask)。 詳細は [`claude-code-permissions.md`](claude-code-permissions.md) §frontend 切り分け。

- ⚠️ **公式 docs の「Hooks … apply to both 〔CLI and Desktop〕」 は実機と乖離** (= desktop では hook の効果がモデルに届かない。 hook は走るが出力が honor されないため実質「効かない」)。 docs を根拠に「desktop でも hook が効く」 と assume しない (= §9 冒頭「docs を鵜呑みにしない」 の frontend instance)。
- **有効化する手段は無い** (2026-06-13 確認): hook を desktop で on にする setting / CLI flag / env var は存在しない (`--output-format` は出力形式の制御で hook 実行とは無関係)。 desktop-native で最も近い機構は MCP server の `toolPolicy` (= 許可 tool の gating のみ、 PreToolUse のように **script を走らせる pre-tool-call は不可**)。 managed `allowManagedHooksOnly` は enterprise の管理制御で execution 保証ではない。
- **判別**: `echo $CLAUDE_CODE_ENTRYPOINT` が `claude-desktop` なら **hook 出力はモデルに届かない** (= SessionStart injection も PreToolUse 判定も無効。 SessionStart は実行自体は起きるが出力が捨てられる)。 親プロセスが `Claude.app` 配下か、 embedded build が PATH の CLI build と別番かでも判る。

**設計含意 (重要)**: hook は「Claude が滑った時に機械的に捕まえる第二視点」 (§5)。 desktop ではそれが消え、 guard は「Claude が規律を自力で守る」 単一視点 (§5.1) に degrade する。 ∴ **不可逆な事故を防ぐ guard ほど frontend 非依存の層に置く**:
- **public leak 防止** = commit-time の **git native hook** (`.git/hooks/pre-commit` + `commit-msg`) に置く (= frontend を経由せず `git commit` で必ず発火。 §2 補足「真の層は commit-time git hook」 と同じ理由 + §2(d) Bash harness-bug も同時に回避)。 ← desktop でも生きる class。
- **無人定期の surfacing** = launchd / scheduled task + OS 通知 (= frontend 非依存)。 **補足 (2026-06-13)**: SessionStart hook は desktop でも実行される (出力注入は捨てられるが副作用は走る) ので、 「SessionStart hook が surface を file に書く → Claude が起動時にそれを読む 〔CLAUDE.md / skill description は desktop でも読まれる〕」 という橋渡しも成立 (= launchd と並ぶ生成側の選択肢。 死んでいるのは注入だけで、 file 経由なら通常の tool call で読めるため)。
- **介入型 guard** (= tool 引数を見て deny / rewrite。 mail 誤送信確認・calendar reminder 強制・memory 誤書き込み防止 等) は tool-call 境界が必須で git native 化できない → **desktop では原理的に不能**。 該当操作は CLI で行うか、 規律運用に割り切る。

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
  - 無人定期 → scheduled task ([`scheduled-tasks.md §0`](scheduled-tasks.md))
- skill は発火が確率的 (model 判断) なので、 **不発の実害が再発したら hook へ格上げ**する
  escalation trigger を導入時に書き残す (= evidence-driven の双方向切替)

### <a id="no-go-example"></a>実例 (2026-06-13)

「内部 context 検索の前に横断 lookup script を回す」 規律の機械化で、 記録系 yaml への
grep を検出する PreToolUse nudge hook 案を検討 → grep の意図 (context-hunting vs
maintenance) が表層から識別不能、 当該 repo の整備 session では常時発火と判定 →
personal skill (description dispatch) に切替。 skill 名を含まない自然な質問に対する
初手 `Skill(...)` 発火を新 session の trace で確認 (検証作法 = `personal-skills.md §4`)。

---

## <a id="related-docs"></a>関連

- `claude-config/setup.sh §Step 2 install_hooks()` — 配信機構の正本 (= delivery 軸 (a) symlink + (b) settings.json を atomic 化する reference implementation。 (c) logic は hook script 側、 (d) invoke 経路は claude-code harness 側で別 layer)
- `claude-config/hooks/*.sh` — 既存 hook 8 個 (= 本 file 作成時点)。 §1 (bash 3.2 trap) の audit 対象
- `conventions/multi-machine-state.md` — 多マシン audit 規律 (本 file と相補、 hook 配信が drift する具体例として cross-reference)
- `docs/personal-layer.md` — layer 3 個人層 hook の配置規律 (= claude-config 側 hook と layer 3 hook の責務分離)
