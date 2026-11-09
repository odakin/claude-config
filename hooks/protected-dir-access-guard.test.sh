#!/bin/bash
# protected-dir-access-guard.test.sh — 保護 dir の名指し・上位 dir の再帰・cwd・Grep/Glob に確認が出る・止まるか、 除外つき・文中の語・無関係な操作には何もしないか + 設定の読み方 + カナリア
#
# 偽の HOME に実体 dir と home 直下の symlink 別名 (Dropbox → Library/CloudStorage/Dropbox) を作り、 保護 dir は
# 架空の「部署/機密作業」 (保護 dir そのものは作らない = hook が中に触れずに判定することも確かめる)。
# foil = 実際に起きた形 (上位 dir からの find / loop での名指し / 文中の語・引用符の / の誤検出) を架空の path で。
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

_run() {  # $1=tool $2=json tool_input $3=cwd -> ask / stop (exit 2 + 直し方の stderr) / none
  local out rc err
  err="$T/.err"
  out=$(jq -n --arg t "$1" --argjson i "$2" --arg c "$3" '{tool_name:$t, tool_input:$i, cwd:$c}' \
    | env -u CLAUDE_PROTECTED_DIRS HOME="$T" python3 "$HOOK" 2>"$err"); rc=$?
  if [ "$rc" = 2 ]; then
    # 直し方 = Bash は除外の書き方 (prune)、 Grep は glob の除外、 Glob は起点を絞る行
    grep -qE 'prune|!\*\*/|起点をその dir の外' "$err" && echo stop || echo stop-without-hint
  elif grep -q '"permissionDecision": "ask"' <<< "$out"; then echo ask
  else echo none; fi
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
_bash "除外を添えても名指しは名指し (tar)" "tar czf o.tgz --exclude='*.tmp' ~/Dropbox/部署/機密作業" ask
_bash "除外を添えても名指しは名指し (rsync)" 'rsync -a --exclude .git ~/Dropbox/部署/機密作業/ /tmp/x/' ask
_bash "起点が中の find の -prune" 'find ~/Dropbox/部署/機密作業 -name .git -prune -o -print' ask
_bash "ls -x の後の名指し" 'ls -x ~/Dropbox/部署/機密作業/' ask
_bash "cd の後の相対の名指し" 'cd ~/Dropbox/部署 && ls 機密作業' ask
_bash "echo の向き先が中" 'echo x > ~/Dropbox/部署/機密作業/f.txt' ask
_bash "代入した path を使う" 'F=~/Dropbox/部署/機密作業; ls "$F"' ask
_bash "python の heredoc の本文が中の file を開く" $'python3 - <<\'EOF\'\nimport os\nprint(open(os.path.expanduser(\'~/Dropbox/部署/機密作業/a.md\')).read())\nEOF' ask
_bash "tar の展開先が中" 'tar xzf a.tgz -C ~/Dropbox/部署/機密作業' ask

echo "=== stop: 上位 dir の再帰 (本人に確認を出さず、 直し方を返して止める) ==="
_bash "Dropbox の根から find (実際に起きた形)" 'cd ~/Library/CloudStorage/Dropbox 2>/dev/null || cd ~/Dropbox; find . -maxdepth 7 -name .git -print' stop
_bash "find 実体の根" "find $CS -name .git" stop
_bash "grep -rn 親" 'grep -rn foo ~/Dropbox/部署' stop
_bash "rg \$HOME/Dropbox" 'rg foo $HOME/Dropbox' stop
_bash "find ~" "find ~ -name '*.tex'" stop
_bash "du -sh ~/Dropbox/" 'du -sh ~/Dropbox/' stop
_bash "find /" 'find / -name x 2>/dev/null' stop
_bash "python os.walk" "python3 -c \"import os; [print(r) for r,_,_ in os.walk(os.path.expanduser('~/Dropbox'))]\"" stop
_bash "find ~/Claude ~/Dropbox (2 つ目の起点が上位)" 'find ~/Claude ~/Dropbox -maxdepth 6 -name "x*"' stop
_bash "xargs の後の grep -r" 'printf "a\0" | xargs -0 -n 1 grep -rl foo ~/Dropbox' stop
_bash "mdfind (-onlyin 無し = 全体)" 'mdfind -name 報告' stop
_bash "mdfind -onlyin 上位" 'mdfind -onlyin ~/Dropbox 報告' stop
_bash "zsh の再帰 glob" 'ls ~/Dropbox/**/*.pdf' stop
_bash "sudo + 環境変数 + timeout の後の find" 'LC_ALL=C sudo timeout 30 find ~ -name x' stop
echo "=== stop: 除外に見えて中身を除かない形・起点の読み方 (照合で見つかった素通り) ==="
_bash "find -not -name B は dir だけ除く" 'find ~/Dropbox/部署 -not -name 機密作業' stop
_bash "find -not -path */B は dir だけ除く" "find ~/Dropbox/部署 -not -path '*/機密作業'" stop
_bash "grep --exclude=B は file の名前" 'grep -r --exclude=機密作業 foo ~/Dropbox/部署' stop
_bash "名を検索語に + 無関係な --exclude" 'grep -r --exclude=*.log 機密作業 ~/Dropbox' stop
_bash "find -L (前置きの option)" 'find -L ~/Dropbox -name x' stop
_bash "find -H -E" 'find -H -E ~/Dropbox -name x' stop
_bash "\\ 改行で継いだ find" $'find \\\n  ~/Dropbox -name x' stop
_bash "rg --files (検索語が無い)" 'rg --files ~/Dropbox' stop
_bash "ag -g (検索語は -g の値)" 'ag -g x ~/Dropbox' stop
_bash "nice -n の後の find" 'nice -n 10 find ~/Dropbox -name x' stop
_bash "stdbuf の後の find" 'stdbuf -oL find ~/Dropbox -name x' stop
_bash "caffeinate の後の find" 'caffeinate -i find ~/Dropbox -name x' stop
_bash "sudo -u の後の find" 'sudo -u root find ~ -name x' stop
_bash "du の起点の glob が上位に広がる" 'du -sh ~/Dropbox/*' stop
_bash "du の glob が D そのものに広がる" 'du -sh ~/Dropbox/*/*' stop
_bash "cat の glob が名を書かずに中へ" 'cat ~/Dropbox/*/*/x.md' stop
_bash "for の並びの glob を変数で find" 'for d in ~/Dropbox/*/; do find "$d" -name x; done' stop
_bash "代入した上位 dir を変数で find" 'r=~/Dropbox; find "$r" -name x' stop
_bash "\$() の起点" 'find $(echo ~/Dropbox) -name x' stop
_bash "xargs に流した起点" 'echo ~/Dropbox | xargs find' stop
_bash "cd に変数で上位 dir、 find ." 'd=~/Dropbox; cd "$d" && find . -name x' stop
_bash "bash -c の中" 'bash -c "find ~/Dropbox -name x"' stop
_bash "eval の中" 'eval "find ~/Dropbox -name x"' stop
_bash "bash に流す heredoc の中" $'bash <<EOF\nfind ~/Dropbox -name x\nEOF' stop
_bash "ugrep -r" 'ugrep -r foo ~/Dropbox' stop
_bash "ditto の元が上位" 'ditto ~/Dropbox/部署 /tmp/y' stop
_bash "scp -r の元が上位" 'scp -r ~/Dropbox host:/tmp/' stop
_bash "tar -C 上位 + ." 'tar -C ~/Dropbox -czf /tmp/o.tgz .' stop
_bash "python の copytree" "python3 -c \"import shutil, os; shutil.copytree(os.path.expanduser('~/Dropbox'), '/tmp/z')\"" stop
_bash "python3.12 の Path.home().rglob" "python3.12 -c \"from pathlib import Path; list(Path.home().rglob('*.pdf'))\"" stop
_bash "uv run python の heredoc の走査" $'uv run --with x python - <<EOF\nimport os\nos.walk(os.path.expanduser(\'~/Dropbox\'))\nEOF' stop
_tool "Grep 上位 + 除かない glob" Grep '{"pattern":"x","path":"~/Dropbox","glob":"*.md"}' stop
_tool "Glob */*/* が名を書かずに中へ" Glob '{"pattern":"*/*/*","path":"~/Dropbox"}' stop

echo "=== cwd ==="
_bash "cwd が中 (実体)" 'ls' ask "$F/sub"
_bash "cwd が中 (別名)" 'ls' ask "$T/Dropbox/部署/機密作業/sub"
_bash "cwd が根 + find ." 'find . -name .git' stop "$CS"
_bash "cwd が別名の根 + grep -r" 'grep -r foo .' stop "$T/Dropbox"
_bash "cwd が根 + 引数の無い rg" 'rg foo' stop "$CS"
_bash "cwd が親 + 名前" 'ls 機密作業' ask "$CS/部署"
_bash "cwd が親 + glob" 'ls *' ask "$CS/部署"

echo "=== Grep / Glob ==="
_tool "Grep path=~/Dropbox" Grep '{"pattern":"x","path":"~/Dropbox"}' stop
_tool "Grep path=中" Grep "$(jq -n --arg p "$F/review" '{pattern:"x",path:$p}')" ask
_tool "Grep path 無し + cwd が親" Grep '{"pattern":"x"}' stop "$CS/部署"
_tool "Glob 絶対 ** from 根" Glob "$(jq -n --arg p "$CS/**/*.py" '{pattern:$p}')" stop
_tool "Glob pattern が P/B" Glob '{"pattern":"~/Dropbox/部署/機密作業/**"}' ask
_tool "Grep path=home" Grep "$(jq -n --arg p "$T" '{pattern:"x",path:$p}')" stop

echo "=== none: 保護 dir を除く書き方を添えた走査 ==="
_bash "find -prune で除く" "find ~/Dropbox -path '*/機密作業' -prune -o -name '*.tex' -print" none
_bash "find の -prune に実体 path" "find ~/Dropbox -path ~/Dropbox/部署/機密作業 -prune -o -name x -print" none
_bash "grep --exclude-dir=" 'grep -rn --exclude-dir=機密作業 foo ~/Dropbox' none
_bash "rg -g !" "rg -g '!**/機密作業/**' foo ~/Dropbox" none
_bash "find -not -path" "find ~/Dropbox -name x -not -path '*機密作業*'" none
_bash "mdfind -onlyin 外" 'mdfind -onlyin ~/Claude 報告' none
_bash "除外は片ごと (別の片の走査は止める)" "grep -rn --exclude-dir=機密作業 foo ~/Dropbox; find ~ -name x" stop
_bash "find -iname -prune" "find ~/Dropbox -iname '機密作業' -prune -o -print" none
_bash "find -not -path */B/* (中身を除く)" "find ~/Dropbox -not -path '*/機密作業/*' -name x" none
_bash "ls -R --ignore=B" 'ls -R --ignore=機密作業 ~/Dropbox/部署' none
_bash "tree -I B" "tree -I '機密作業|x' ~/Dropbox" none
_bash "du --exclude=B" 'du -sh --exclude=機密作業 ~/Dropbox/部署' none
_bash "zip -x で中身を除く" "zip -r /tmp/o.zip ~/Dropbox -x '*/機密作業/*'" none
_bash "rsync --exclude=B" 'rsync -a --exclude=機密作業 ~/Dropbox/部署/ /tmp/y/' none
_bash "fd -E B" 'fd -E 機密作業 x ~/Dropbox' none
_bash "python の走査で dirs[:] から B を除く" $'python3 -c "import os\nfor r,d,f in os.walk(os.path.expanduser(\'~/Dropbox\')):\n    d[:] = [x for x in d if x != \'機密作業\']"' none
_tool "Grep 上位 + glob !**/B/**" Grep '{"pattern":"x","path":"~/Dropbox","glob":"!**/機密作業/**"}' none
_tool "Grep 上位 + glob !親" Grep '{"pattern":"x","path":"~/Dropbox","glob":"!部署"}' none

echo "=== none: 文中の語・引用符の / (実際に誤検出した形を架空の path で) ==="
_bash "loop の find \"\$r\" + awk の \"/\"" 'for r in ~/Claude/*/; do command find "$r" -path "$r/.git" -prune -o -name "*.md" -print; done | awk -F/ '"'"'{print $1"/"$2}'"'"' | sort | uniq -c' none
_bash "commit message の tree と /" 'git commit -m "構造 tree の行を直した。 setup.sh / CLAUDE.md の touch を解放" -- CLAUDE.md' none
_bash "grep -r の検索語が /" 'grep -rn "/" ~/Claude/x' none
_bash "python の split(\"/\") (走査は ~/Claude)" "python3 -c \"import os; [print(p.split('/')[-1]) for p,_,_ in os.walk(os.path.expanduser('~/Claude'))]\"" none
_bash "heredoc の本文の find と /" "python3 - <<'EOF'
# find omitted text
s = a.split('/')[0]
EOF" none
_bash "tr の / と find ~/Claude" "find ~/Claude -name x | tr '/' '_'" none
_bash "ack の語が文の中" 'echo "ack は送らない / 返事だけ"' none
_bash "file を書くだけの heredoc の本文の走査" $'cat > /tmp/x.py <<X\nimport os\nfor r in os.walk(os.path.expanduser("~/Dropbox")): pass\nX' none
_bash "file を書くだけの heredoc の本文の path" $'cat > /tmp/n.md <<\'EOF\'\nsee ~/Dropbox/部署/機密作業/a.md\nEOF' none
_bash "python の heredoc の規則の文 (P/B が / の後)" $'python3 - <<\'EOF\'\nr = f"Write(/${{HOME}}/{base}/部署/機密作業/**)"\nEOF' none
_bash "commit message の頭が D の path" "git commit -m '~/Dropbox/部署/機密作業/a.md を直した'" none
_bash "grep の検索語が D の path" "grep -rn '~/Dropbox/部署/機密作業' ~/Claude/docs" none
_bash "cp の写し先が上位 dir" 'cp -r ~/Claude/x ~/Dropbox/' none
_bash "rsync の写し先が上位 dir" 'rsync -a ~/Claude/x/ ~/Dropbox/' none
_bash "ls の glob が 1 段 (名前だけ)" 'ls ~/Dropbox/*' none
_bash "親の glob が B に当たらない" 'ls ~/Dropbox/部署/*.pdf' none
_bash "cd ~ の後の for の並びを変数で find (設定 dir)" 'cd ~ && for d in .claude .claude-x; do find "$d/projects" -name "*.jsonl"; done' none
_bash "for の並びの glob が上位に届かない" 'cd ~ && for d in ~/.claude*/projects; do find "$d" -name "*.jsonl"; done | xargs grep -l x' none
_bash "値の読めない変数 + tr の /" 'for r in a/b c/d; do n=$(echo $r | tr "/" "_"); du -sh "$n"; done' none
_bash "python の Path.home() / 下の dir の走査" $'python3 - <<\'EOF\'\nfrom pathlib import Path\nimport os\nroot = Path.home() / "sandbox"\nfor dp, dn, fn in os.walk(root): pass\nEOF' none
_tool "Glob * を親で (名前だけ)" Glob '{"pattern":"*","path":"~/Dropbox/部署"}' none
_tool "Glob */* を上位で (D そのものまで)" Glob '{"pattern":"*/*","path":"~/Dropbox"}' none

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
_tool "NotebookEdit の file が中" NotebookEdit "$(jq -n --arg p "$F/a.ipynb" '{notebook_path:$p}')" ask
_tool "Grep の glob が名を書く (上位から)" Grep '{"pattern":"x","path":"~/Dropbox","glob":"**/機密作業/**"}' ask
_tool "Glob の ** に名 (上位から)" Glob '{"pattern":"**/機密作業/**","path":"~/Dropbox"}' ask
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
_ev PostToolUse sess-A Read "$IN" >/dev/null
n=$(wc -l < "$T/.claude/protected-dir-unlock/sess-A" | tr -d " ")
_check "記録は二重にしない (= 2 回目の PostToolUse)" "$n" 1
_check "同じ session は Bash も allow" "$(_ev PreToolUse sess-A Bash "$(jq -n --arg c "ls $F" '{command:$c}')")" allow
_check "別 session はまた ask" "$(_ev PreToolUse sess-B Read "$IN")" ask
_check "session_id が無ければ ask のまま" "$(_ev PreToolUse "" Read "$IN")" ask
_check "PostToolUse でも session_id 無しは記録しない" "$(_ev PostToolUse "" Read "$IN")" none
[ ! -e "$T/.claude/protected-dir-unlock/_" ] && _check "空 session の記録を作らない" ok ok || _check "空 session の記録を作った" bad ok
_check "保護 dir の外は PostToolUse でも記録しない" "$(_ev PostToolUse sess-C Read "$(jq -n --arg p "$T/other/a.md" '{file_path:$p}')")" none
[ ! -e "$T/.claude/protected-dir-unlock/sess-C" ] && _check "外の file で unlock しない" ok ok || _check "外の file で unlock した" bad ok
_ev PostToolUse sess-D Bash "$(jq -n '{command:"find ~/Dropbox -name x"}')" >/dev/null
[ ! -e "$T/.claude/protected-dir-unlock/sess-D" ] && _check "上位からの走査 (止める) で unlock しない" ok ok || _check "走査で unlock した" bad ok
_ev PostToolUse sess-E Bash "$(jq -n '{command:"git commit -m \"~/Dropbox/部署/機密作業/a.md を直した\""}')" >/dev/null
[ ! -e "$T/.claude/protected-dir-unlock/sess-E" ] && _check "commit message の path で unlock しない" ok ok || _check "commit message で unlock した" bad ok
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
