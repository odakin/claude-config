#!/usr/bin/env bash
# prune-retired-hooks.test.sh — 退役 hook の掃除 (scripts/lib/prune-retired-hooks.sh) の test
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=prune-retired-hooks.sh
. "$HERE/prune-retired-hooks.sh"

PASS=0; FAIL=0
ok() { if [ "$2" = "$3" ]; then echo "  PASS: $1"; PASS=$((PASS+1)); else echo "  FAIL: $1 (want=$2 got=$3)"; FAIL=$((FAIL+1)); fi; }

T="$(mktemp -d "${TMPDIR:-/tmp}/prune-retired.XXXXXX")"
trap 'rm -rf "$T"' EXIT
SRC="$T/src"; DST="$T/dst"; SET="$T/settings.json"; REG="$T/retired.txt"
mkdir -p "$SRC" "$DST"
printf '#!/bin/bash\n' > "$SRC/live.sh"
ln -s "$SRC/live.sh" "$DST/live.sh"
ln -s "$SRC/old.sh" "$DST/old.sh"            # 指す先が消えた symlink (= 退役後の姿)
ln -s "$SRC/old-anchor.py" "$DST/old-anchor.py"
cat > "$SET" <<'EOF'
{"model": "x",
 "hooks": {
  "SessionStart": [
   {"hooks": [{"type": "command", "command": "~/.claude/hooks/live.sh"}]},
   {"hooks": [{"type": "command", "command": "~/.claude/hooks/old.sh"},
              {"type": "command", "command": "~/.claude/hooks/neighbor.sh"}]}
  ],
  "UserPromptSubmit": [
   {"hooks": [{"type": "command", "command": "python3 /abs/.claude/hooks/old-anchor.py --flag"}]}
  ],
  "Stop": [
   {"hooks": [{"type": "command", "command": "~/.claude/hooks/not-old.sh track"}]}
  ]
 }}
EOF
printf '# 退役 registry\nold.sh          # 理由\nold-anchor.py\nlive.sh   # 書き間違い: まだ在る\n\n' > "$REG"

echo "=== T1: --check は書かずに残骸を数える ==="
before="$(cat "$SET")"
out="$(prune_retired_hooks "$REG" "$SRC" "$DST" "$SET" --check)"; rc=$?
ok "--check: 残骸ありで return 1" 1 "$rc"
ok "--check: old.sh と old-anchor.py の 2 行" 2 "$(printf '%s\n' "$out" | grep -c '退役 hook の残骸')"
ok "--check: repo に在る live.sh は残骸に数えない" 0 "$(printf '%s\n' "$out" | grep -c 'live.sh')"
ok "--check: settings を書き換えない" "$before" "$(cat "$SET")"

echo "=== T2: 外す ==="
out="$(prune_retired_hooks "$REG" "$SRC" "$DST" "$SET")"; rc=$?
ok "外した後は return 0" 0 "$rc"
ok "old.sh の symlink が消える" 0 "$([ -L "$DST/old.sh" ] && echo 1 || echo 0)"
ok "引数つき・python 起動の command も外れる" 0 "$(grep -c 'old-anchor.py' "$SET")"
ok "同じ entry に同居する他の hook は残る" 1 "$(grep -c 'neighbor.sh' "$SET")"
ok "名前が後ろだけ一致する別の hook (not-old.sh) は残る" 1 "$(grep -c 'not-old.sh' "$SET")"
ok "空になった event は key ごと消える" 0 "$(jq '.hooks | has("UserPromptSubmit")' "$SET" | grep -c true)"
ok "hooks 以外の設定は残る" '"x"' "$(jq -c '.model' "$SET")"
ok "repo に在る名前は外さず WARN" 1 "$(printf '%s\n' "$out" | grep -c 'WARN: live.sh')"
ok "生きている hook の symlink と entry は残る" "1 1" "$([ -L "$DST/live.sh" ] && echo 1 || echo 0) $(grep -c '/live.sh' "$SET")"

echo "=== T3: 2 回目は何もしない (冪等) ==="
before="$(cat "$SET")"
out="$(prune_retired_hooks "$REG" "$SRC" "$DST" "$SET")"
ok "2 回目は settings 不変" "$before" "$(cat "$SET")"
ok "2 回目は RETIRED 行なし" 0 "$(printf '%s\n' "$out" | grep -c 'RETIRED')"
prune_retired_hooks "$REG" "$SRC" "$DST" "$SET" --check >/dev/null; ok "外した後の --check は return 0" 0 "$?"

echo "=== T3b: Event:file 名 = その event からだけ外す (file は別の event で現役) ==="
printf '#!/usr/bin/env python3\n' > "$SRC/anchor.py"; ln -s "$SRC/anchor.py" "$DST/anchor.py"
SET2="$T/settings2.json"
cat > "$SET2" <<'EOF'
{"hooks": {
  "SessionStart": [{"hooks": [{"type": "command", "command": "~/.claude/hooks/anchor.py"}]}],
  "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "~/.claude/hooks/anchor.py"}]}]}}
EOF
printf 'UserPromptSubmit:anchor.py   # 毎 prompt 版だけ退役\n' > "$T/retired2.txt"
prune_retired_hooks "$T/retired2.txt" "$SRC" "$DST" "$SET2" --check >/dev/null; ok "scoped: --check が残骸を見つける" 1 "$?"
prune_retired_hooks "$T/retired2.txt" "$SRC" "$DST" "$SET2" >/dev/null
ok "scoped: 指定 event から外れる" false "$(jq '.hooks | has("UserPromptSubmit")' "$SET2")"
ok "scoped: 別の event の同じ file は残る" 1 "$(jq '.hooks.SessionStart | length' "$SET2")"
ok "scoped: symlink は触らない" 1 "$([ -L "$DST/anchor.py" ] && echo 1 || echo 0)"
prune_retired_hooks "$T/retired2.txt" "$SRC" "$DST" "$SET2" --check >/dev/null; ok "scoped: 外した後の --check は return 0" 0 "$?"

echo "=== T4: registry / settings が無い ==="
prune_retired_hooks "$T/none.txt" "$SRC" "$DST" "$SET"; ok "registry 不在は return 0" 0 "$?"
prune_retired_hooks "$REG" "$SRC" "$DST" "$T/none.json"; ok "settings 不在でも落ちない" 0 "$?"

echo "--- prune-retired-hooks.test: PASS=$PASS FAIL=$FAIL ---"
[ "$FAIL" -eq 0 ]
