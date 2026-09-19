#!/bin/bash
# protected-dir-access-guard.test.sh — 保護 dir の名指し・上位 dir の再帰・cwd・Grep/Glob に確認が出て、 無関係な操作には出ないか + 設定の読み方 + カナリア
#
# 偽の HOME に実体 dir と home 直下の symlink 別名 (Dropbox → Library/CloudStorage/Dropbox) を作り、 保護 dir は
# 架空の「部署/機密作業」 (保護 dir そのものは作らない = hook が中に触れずに判定することも確かめる)。
# foil = 実際に起きた 2 形 (上位 dir からの find / loop での名指し)。
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/protected-dir-access-guard.py"
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 が無い環境"; exit 0; }
command -v jq >/dev/null 2>&1 || { echo "SKIP: jq が無い環境"; exit 0; }
T="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/pdag-test.XXXXXX")" && pwd -P)"
trap 'rm -rf "$T"' EXIT
CS="$T/Library/CloudStorage/Dropbox"
mkdir -p "$CS/部署" "$CS/Physics" "$T/Claude" "$T/.claude"
ln -s "$CS" "$T/Dropbox"
printf '# 作業リポ\n~/Dropbox/部署/機密作業\n' > "$T/.claude/leak-pattern-sources.txt"
F="$CS/部署/機密作業"
PASS=0; FAIL=0

_run() {  # $1=tool $2=json tool_input $3=cwd -> ask / none
  jq -n --arg t "$1" --argjson i "$2" --arg c "$3" '{tool_name:$t, tool_input:$i, cwd:$c}' \
    | env -u CLAUDE_PROTECTED_DIRS HOME="$T" python3 "$HOOK" 2>/dev/null | grep -q '"permissionDecision": "ask"' && echo ask || echo none
}
_check() {  # $1=label $2=got $3=expect
  if [ "$2" = "$3" ]; then PASS=$((PASS+1)); echo "  ok: $1"; else FAIL=$((FAIL+1)); echo "  NG: $1 (expected $3, got $2)"; fi
}
_bash() { _check "$1" "$(_run Bash "$(jq -n --arg c "$2" '{command:$c}')" "${4:-$T/Claude}")" "$3"; }
_tool() { _check "$1" "$(_run "$2" "$3" "${5:-$T/Claude}")" "$4"; }

echo "=== ask: 名指し ==="
_bash "loop で P/B を名指し (実際に起きた形)" 'for d in "./部署/機密作業" "./Physics/x"; do git -C "$d" ls-files; done' ask
_bash "~/Dropbox 別名で名指し" 'ls ~/Dropbox/部署/機密作業/' ask
_bash "実体 path で名指し" "cat \"$F/a.md\"" ask
_bash "\$HOME 形" 'ls $HOME/Dropbox/部署/機密作業' ask
_bash "親の直後の glob" 'ls ~/Dropbox/部署/*' ask
_bash "親の直後の前方一致 glob" 'ls ~/Dropbox/部署/機密*' ask

echo "=== ask: 上位 dir の再帰 ==="
_bash "Dropbox の根から find (実際に起きた形)" 'cd ~/Library/CloudStorage/Dropbox 2>/dev/null || cd ~/Dropbox; find . -maxdepth 7 -name .git -print' ask
_bash "find 実体の根" "find $CS -name .git" ask
_bash "grep -rn 親" 'grep -rn foo ~/Dropbox/部署' ask
_bash "rg \$HOME/Dropbox" 'rg foo $HOME/Dropbox' ask
_bash "find ~" "find ~ -name '*.tex'" ask
_bash "du -sh ~/Dropbox/" 'du -sh ~/Dropbox/' ask
_bash "find /" 'find / -name x 2>/dev/null' ask
_bash "python os.walk" "python3 -c \"import os; [print(r) for r,_,_ in os.walk(os.path.expanduser('~/Dropbox'))]\"" ask

echo "=== ask: cwd ==="
_bash "cwd が中 (実体)" 'ls' ask "$F/sub"
_bash "cwd が中 (別名)" 'ls' ask "$T/Dropbox/部署/機密作業/sub"
_bash "cwd が根 + find ." 'find . -name .git' ask "$CS"
_bash "cwd が別名の根 + grep -r" 'grep -r foo .' ask "$T/Dropbox"
_bash "cwd が親 + 名前" 'ls 機密作業' ask "$CS/部署"
_bash "cwd が親 + glob" 'ls *' ask "$CS/部署"

echo "=== ask: Grep / Glob ==="
_tool "Grep path=~/Dropbox" Grep '{"pattern":"x","path":"~/Dropbox"}' ask
_tool "Grep path=中" Grep "$(jq -n --arg p "$F/review" '{pattern:"x",path:$p}')" ask
_tool "Grep path 無し + cwd が親" Grep '{"pattern":"x"}' ask "$CS/部署"
_tool "Glob 絶対 ** from 根" Glob "$(jq -n --arg p "$CS/**/*.py" '{pattern:$p}')" ask
_tool "Glob pattern が P/B" Glob '{"pattern":"~/Dropbox/部署/機密作業/**"}' ask
_tool "Grep path=home" Grep "$(jq -n --arg p "$T" '{pattern:"x",path:$p}')" ask

echo "=== none: 触れないもの ==="
_bash "規約を読む grep (語だけ)" 'grep -n "機密作業" CLAUDE.md' none
_bash "commit message の語" 'git commit -m "CLAUDE.md 機密作業: 横断検索から外す" -- CLAUDE.md' none
_bash "親を再帰せず一覧" 'ls ~/Dropbox/部署' none
_bash "外の dir への再帰" 'grep -rn foo ~/Dropbox/Physics/x' none
_bash "find ~/Dropbox/Physics" 'find ~/Dropbox/Physics -name "*.py"' none
_bash "find ~/Claude" "find ~/Claude -name '*.py'" none
_bash "sed の / は根ではない" "sed 's/a/b/' f.txt" none
_bash "cwd ~/Claude + find ." 'find . -name x' none
_bash "cwd が根でも再帰しない ls" 'ls Physics' none "$CS"
_bash "cwd が親でも名前も glob も無い" 'echo hello' none "$CS/部署"
_tool "Grep path=~/Claude" Grep '{"pattern":"x","path":"~/Claude"}' none
_tool "Glob 相対 (cwd ~/Claude)" Glob '{"pattern":"**/*.md"}' none
_tool "Glob に語だけ (起点が外)" Glob '{"pattern":"**/機密作業/**"}' none
_tool "Read の file が中" Read "$(jq -n --arg p "$F/a.md" '{file_path:$p}')" ask
_tool "Edit の file が中" Edit "$(jq -n --arg p "$F/a.md" '{file_path:$p}')" ask
_tool "Read の file が外" Read "$(jq -n --arg p "$T/other/a.md" '{file_path:$p}')" none
_bash "空 command" '' none

echo "=== 設定の読み方 ==="
got=$(jq -n '{tool_name:"Bash",tool_input:{command:"ls ~/Dropbox/部署/機密作業"},cwd:"/"}' | env -u CLAUDE_PROTECTED_DIRS HOME="$T/nohome" python3 "$HOOK" 2>/dev/null | grep -c ask)
_check "宣言が無ければ何もしない" "$got" 0
mkdir -p "$T/h2/.claude" "$T/h2/w/部署"
printf '%s\n' "$T/h2/w/部署/機密作業" > "$T/h2/.claude/protected-dirs.txt"
got=$(jq -n --arg c "cat $T/h2/w/部署/機密作業/x" '{tool_name:"Bash",tool_input:{command:$c},cwd:"/"}' | env -u CLAUDE_PROTECTED_DIRS HOME="$T/h2" python3 "$HOOK" 2>/dev/null | grep -q ask && echo ask || echo none)
_check "protected-dirs.txt から読む" "$got" ask
got=$(jq -n '{tool_name:"Bash",tool_input:{command:"ls ~/Dropbox/部署/機密作業"},cwd:"/"}' | CLAUDE_PROTECTED_DIRS="$T/other/x" HOME="$T" python3 "$HOOK" 2>/dev/null | grep -q ask && echo ask || echo none)
_check "CLAUDE_PROTECTED_DIRS は file より優先" "$got" none
out=$(printf 'not json' | HOME="$T" python3 "$HOOK" 2>&1); rc=$?
_check "壊れた入力で死なない (rc 0・無出力)" "$rc:$out" "0:"

echo "=== session 内の 1 回限り許可 ==="
_ev() {  # $1=event $2=session_id $3=tool $4=json input -> ask / allow / none
  jq -n --arg e "$1" --arg s "$2" --arg t "$3" --argjson i "$4" --arg c "$T/Claude" \
     '{hook_event_name:$e, session_id:$s, tool_name:$t, tool_input:$i, cwd:$c}' \
    | env -u CLAUDE_PROTECTED_DIRS HOME="$T" python3 "$HOOK" 2>/dev/null \
    | { out=$(cat); case "$out" in *'"permissionDecision": "allow"'*) echo allow ;; *'"permissionDecision": "ask"'*) echo ask ;; *) echo none ;; esac; }
}
IN=$(jq -n --arg p "$F/a.md" '{file_path:$p}')
_check "許可前は ask" "$(_ev PreToolUse sess-A Read "$IN")" ask
_check "PostToolUse は決定を返さない" "$(_ev PostToolUse sess-A Read "$IN")" none
[ -s "$T/.claude/protected-dir-unlock/sess-A" ] && _check "許可が記録される" ok ok || _check "許可が記録されない" bad ok
_check "同じ session は以後 allow" "$(_ev PreToolUse sess-A Read "$IN")" allow
_check "同じ session は Bash も allow" "$(_ev PreToolUse sess-A Bash "$(jq -n --arg c "ls $F" '{command:$c}')")" allow
_check "別 session はまた ask" "$(_ev PreToolUse sess-B Read "$IN")" ask
_check "session_id が無ければ ask のまま" "$(_ev PreToolUse "" Read "$IN")" ask
_check "PostToolUse でも session_id 無しは記録しない" "$(_ev PostToolUse "" Read "$IN")" none
[ ! -e "$T/.claude/protected-dir-unlock/_" ] && _check "空 session の記録を作らない" ok ok || _check "空 session の記録を作った" bad ok
_check "保護 dir の外は PostToolUse でも記録しない" "$(_ev PostToolUse sess-C Read "$(jq -n --arg p "$T/other/a.md" '{file_path:$p}')")" none
[ ! -e "$T/.claude/protected-dir-unlock/sess-C" ] && _check "外の file で unlock しない" ok ok || _check "外の file で unlock した" bad ok
rm -rf "$T/.claude/protected-dir-unlock"

echo "=== カナリア ==="
S="$T/.claude/settings.json"
jq -n --arg h "$HOOK" '{hooks:{PreToolUse:[{matcher:"Bash",hooks:[{type:"command",command:$h}]},{matcher:"Grep|Glob|Read|Edit|Write",hooks:[{type:"command",command:$h}]}]}}' > "$S"
out=$(env -u CLAUDE_PROTECTED_DIRS HOME="$T" python3 "$HOOK" --canary 2>&1); rc=$?
case "$rc:$out" in "0:ARMED"*"1 回限り許可は未配線"*) _check "PostToolUse 未配線 → ARMED + 警告" ok ok ;; *) _check "PostToolUse 未配線の警告 ($out)" "$rc" 0 ;; esac
jq -n --arg h "$HOOK" '{hooks:{PreToolUse:[{matcher:"Bash|Grep|Glob|Read|Edit|Write",hooks:[{type:"command",command:$h}]}],PostToolUse:[{matcher:"Bash|Grep|Glob|Read|Edit|Write",hooks:[{type:"command",command:$h}]}]}}' > "$S"
out=$(env -u CLAUDE_PROTECTED_DIRS HOME="$T" python3 "$HOOK" --canary 2>&1); rc=$?
case "$rc:$out" in "0:ARMED"*"1 回限り許可は未配線"*) _check "両方配線 → 警告なし ($out)" bad ok ;; "0:ARMED"*) _check "両方配線 → ARMED (警告なし)" ok ok ;; *) _check "両方配線 ($out)" "$rc" 0 ;; esac
jq -n --arg h "$HOOK" '{hooks:{PreToolUse:[{matcher:"Bash",hooks:[{type:"command",command:$h}]}]}}' > "$S"
out=$(env -u CLAUDE_PROTECTED_DIRS HOME="$T" python3 "$HOOK" --canary 2>&1); rc=$?
case "$rc:$out" in "1:NOT ARMED"*Grep*) _check "Grep/Glob の配線が無い → NOT ARMED" ok ok ;; *) _check "Grep/Glob 欠落 ($out)" "$rc" 1 ;; esac
out=$(env -u CLAUDE_PROTECTED_DIRS HOME="$T/nohome" python3 "$HOOK" --canary 2>&1); rc=$?
case "$rc:$out" in "0:未配線"*) _check "宣言が無い → 未配線 (FAIL にしない)" ok ok ;; *) _check "未配線 ($out)" "$rc" 0 ;; esac
[ ! -e "$F" ] && _check "判定の間に保護 dir を作っていない" ok ok || _check "保護 dir が作られた" bad ok

echo ""
echo "=== $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ]
