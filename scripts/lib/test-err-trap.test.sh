#!/usr/bin/env bash
# test-err-trap.test.sh — test-err-trap.sh の self-test (hermetic、 走らせた bash で fixture を実行)
# 実行: bash scripts/lib/test-err-trap.test.sh   (bash 3.2 / 5.x の両方で PASS すること)
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
LIB="$HERE/test-err-trap.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); }
miss() { FAIL=$((FAIL+1)); echo "  MISS: $1"; }

# fixture は 1 行目 shebang / 2 行目 set -euo pipefail / 3 行目 source で、 本体は 4 行目から
fixture() { # <name> (本体は stdin)
  { printf '%s\n' '#!/usr/bin/env bash' 'set -euo pipefail' ". \"$LIB\""; cat; } > "$TMP/$1.sh"
}
run() { # <name> — 同じ bash で実行して exit / stderr を保存
  "$BASH" "$TMP/$1.sh" > /dev/null 2> "$TMP/$1.err"
  echo $? > "$TMP/$1.rc"
}
expect() { # <name> <exit> <stderr (完全一致)>
  run "$1"
  [ "$(cat "$TMP/$1.rc")" = "$2" ] && ok || miss "$1: exit $(cat "$TMP/$1.rc"), expected $2"
  [ "$(cat "$TMP/$1.err")" = "$3" ] && ok || miss "$1: stderr [$(cat "$TMP/$1.err")], expected [$3]"
}

# 1. top-level の失敗 = その行 + command。 $(...) 内の失敗は外側の 1 行だけ
fixture top <<'EOF'
f() { [ "$1" = ok ]; }
f ok
[ "$(false)" = y ]
echo "not reached"
EOF
expect top 1 'top.sh: FAIL at line 6: [ "$(false)" = y ]'

# 2. 関数内の失敗 = 呼び出し行 + 関数名。 if の条件で呼んだ期待どおりの失敗は出さない
fixture fn <<'EOF'
f() {
  [ "$1" = ok ]
}
if f bad; then exit 9; fi
f bad
EOF
expect fn 1 'fn.sh: FAIL at line 8 (in f): [ "$1" = ok ]'

# 3. 入れ子の関数 = main の呼び出し行 + 呼び出し経路
fixture nested <<'EOF'
inner() { [ "$1" = ok ]; }
outer() {
  inner "$1"
}
outer bad
EOF
expect nested 1 'nested.sh: FAIL at line 8 (in outer > inner): [ "$1" = ok ]'

# 4. 複数行 command は 1 行目 + " ..." (行は bash 5 = 先頭 / 3.2 = 末尾)。 exit status は保つ
fixture multi <<'EOF'
sh -c '
exit 3'
EOF
run multi
[ "$(cat "$TMP/multi.rc")" = 3 ] && ok || miss "multi: exit $(cat "$TMP/multi.rc"), expected 3"
case "$(cat "$TMP/multi.err")" in
  "multi.sh: FAIL at line 4: sh -c ' ..."|"multi.sh: FAIL at line 5: sh -c ' ...") ok ;;
  *) miss "multi: stderr [$(cat "$TMP/multi.err")]" ;;
esac

# 5. 通る test は何も出さない (期待失敗の if / || true を含む)
fixture pass <<'EOF'
f() { [ "$1" = ok ]; }
if f bad; then exit 9; fi
x="$(false || true)"
f ok
EOF
expect pass 0 ''

echo ""
echo "=== Result: PASS=$PASS FAIL=$FAIL (bash $BASH_VERSION) ==="
[ "$FAIL" -eq 0 ]
