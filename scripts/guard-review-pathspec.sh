#!/bin/bash
# Independent acceptance cases for the manuscript-claim-guard pathspec fix (mock repos only).
set -u
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK="${GUARD_REVIEW_HOOK:-$SCRIPT_DIR/../hooks/manuscript-claim-guard.py}"
SCALE_FILES="${GUARD_REVIEW_SCALE_FILES:-3000}"
case "$SCALE_FILES" in *[!0-9]*|'') echo "GUARD_REVIEW_SCALE_FILES must be a nonnegative integer" >&2; exit 2;; esac
T="$(mktemp -d "${TMPDIR:-/tmp}/mcg-accept.XXXXXX")"; T="$(cd "$T" && pwd -P)"
trap 'rm -rf "$T"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.invalid GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.invalid
export MANUSCRIPT_CLAIM_GUARD_STATE_DIR="$T/state" MANUSCRIPT_CLAIM_GUARD_HOME="$T/home"
P=0; F=0
dec() {  # $1=cwd $2=command -> allow / deny:<reason head>
  local out
  out="$(jq -n --arg cmd "$2" --arg c "$1" '{hook_event_name:"PreToolUse", tool_name:"Bash", session_id:"acc-1", cwd:$c, tool_input:{command:$cmd}}' | python3 "$HOOK" 2>/dev/null)"
  if printf '%s' "$out" | grep -q '"permissionDecision": "deny"'; then
    printf '%s' "$out" | grep -q 'inspection unavailable' && echo "deny:unavailable" || echo "deny:protected"
  else echo allow; fi
}
chk() { if [ "$2" = "$3" ]; then P=$((P+1)); echo "  ok   $1 -> $2"; else F=$((F+1)); echo "  NG   $1 -> got $2, want $3"; fi; }
tex() { printf '%s\n' '\title{T}' '\begin{abstract}' 'We find X.' '\end{abstract}' '\begin{equation}' "$1" '\end{equation}' > "$2"; }

# --- non-manuscript repos (the original false deny) ---
git init -q "$T/alpha"; printf 'items:\n- id: a\n' > "$T/alpha/TODO.yaml"; git -C "$T/alpha" add -A; git -C "$T/alpha" commit -qm i
git init -q "$T/beta"; printf 'x\n' > "$T/beta/README.md"; git -C "$T/beta" add -A; git -C "$T/beta" commit -qm i
mkdir -p "$T/beta/data/forms-2026" "$T/beta/data/only-ignored"
printf '%%PDF-1.4\n\001bin' > "$T/beta/data/forms-2026/scan.pdf"; printf 'k: v\n' > "$T/beta/data/forms-2026/meta.yaml"
printf '*.log\n' > "$T/beta/.gitignore"; printf 'x' > "$T/beta/data/only-ignored/a.log"
FULL="cd $T/alpha && python3 - <<'PY'
p = open('TODO.yaml').read()  # don't
PY
python3 -c \"import yaml\"
git commit -q -m \"update\" -- TODO.yaml && git push -q
cd $T/beta && git add data/forms-2026/ && git commit -q -m \"add\" -- data/forms-2026/ && git push -q"
echo "== non-manuscript"
chk "original compound (heredoc + 2 cd + untracked dir)" "$(dec "$T" "$FULL")" allow
chk "dir with only ignored files" "$(dec "$T/beta" "git commit -m x -- data/only-ignored/")" allow
chk "git add -A && commit (untracked binaries)" "$(dec "$T/beta" "git add -A && git commit -m x")" allow
chk "dir name with space" "$(mkdir -p "$T/beta/my dir"; printf 'y\n' > "$T/beta/my dir/n.md"; dec "$T/beta" "git add 'my dir/' && git commit -m x -- 'my dir/'")" allow

# --- manuscript repo: protected change inside dirs / globs must still be denied ---
git init -q "$T/gamma"; mkdir -p "$T/gamma/paper.v2" "$T/gamma/paperdir/sub"
tex 'f = g + h' "$T/gamma/paper.v2/main.tex"; tex 'f = g + h' "$T/gamma/paperdir/sub/main.tex"
git -C "$T/gamma" add -A; git -C "$T/gamma" commit -qm i
python3 - "$T/gamma/paper.v2/main.tex" "$T/gamma/paperdir/sub/main.tex" <<'PYEDIT'
from pathlib import Path
import sys
for name in sys.argv[1:]:
    p = Path(name)
    p.write_text(p.read_text().replace('g + h', 'g - h'))
PYEDIT
echo "== manuscript: protected change"
chk "dotted dir pathspec" "$(dec "$T/gamma" "git commit -m x -- paper.v2/")" deny:protected
chk "plain dir pathspec (nested file)" "$(dec "$T/gamma" "git commit -m x -- paperdir/")" deny:protected
chk "glob '*.tex'" "$(dec "$T/gamma" "git commit -m x -- '*.tex'")" deny:protected
chk "commit -- ." "$(dec "$T/gamma" "git commit -m x -- .")" deny:protected
chk "from subdir: cd paperdir && commit -- sub/" "$(dec "$T/gamma" "cd paperdir && git commit -m x -- sub/")" deny:protected
chk "relative up: cd paperdir/sub && commit -- ../../paper.v2" "$(dec "$T/gamma" "cd paperdir/sub && git commit -m x -- ../../paper.v2")" deny:protected
chk "magic :(glob)**/*.tex" "$(dec "$T/gamma" "git commit -m x -- ':(glob)**/*.tex'")" deny:protected
chk "exclude magic hides nothing protected: -- . ':!paperdir'" "$(dec "$T/gamma" "git commit -m x -- . ':!paperdir'")" deny:protected
git -C "$T/gamma" checkout -q -- paper.v2/main.tex
chk "exclude magic: only excluded dir changed -> allow" "$(dec "$T/gamma" "git commit -m x -- . ':!paperdir'")" allow
git -C "$T/gamma" checkout -q -- .
echo "== manuscript: new / deleted"
tex 'a = b' "$T/gamma/new-paper.tex"
chk "git add -A with new untracked manuscript" "$(dec "$T/gamma" "git add -A && git commit -m x")" deny:protected
chk "git add . with new untracked manuscript" "$(dec "$T/gamma" "git add . && git commit -m x")" deny:protected
chk "git commit -a (untracked NOT included)" "$(dec "$T/gamma" "git commit -a -m x")" allow
rm "$T/gamma/new-paper.tex"
git -C "$T/gamma" rm -rq paperdir
chk "deleted dir holding a manuscript: commit -- paperdir" "$(dec "$T/gamma" "git commit -m x -- paperdir")" deny:protected
git -C "$T/gamma" reset -q --hard
echo "== unprotected change in manuscript repo"
printf 'notes\n' > "$T/gamma/paperdir/README.md"
chk "new non-tex file in manuscript dir" "$(dec "$T/gamma" "git add paperdir/ && git commit -m x -- paperdir/")" allow
echo "== fail-closed"
chk "invalid pathspec magic -> not silently allowed" "$(dec "$T/gamma" "git commit -m x -- ':(nonsense)x'")" deny:unavailable
if [ "$SCALE_FILES" -gt 0 ]; then
echo "== scale"
mkdir -p "$T/beta/big"; for i in $(seq 1 "$SCALE_FILES"); do printf 'x' > "$T/beta/big/f$i.txt"; done
s=$(python3 -c 'import time; print(time.time())')
r="$(dec "$T/beta" "git add big/ && git commit -m x -- big/")"
e=$(python3 -c "import time; print(round(time.time()-$s,1))")
chk "$SCALE_FILES untracked text files in dir (took ${e}s)" "$r" allow
fi
echo "PASS=$P FAIL=$F"
