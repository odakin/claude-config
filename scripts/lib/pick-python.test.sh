#!/usr/bin/env bash
# pick-python.test.sh — pick-python.sh (無人ジョブの python3 を import できるかで選ぶ) の検査
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/pick-python.sh"
PASS=0; FAIL=0
ok() { PASS=$((PASS+1)); echo "  PASS: $1"; }
ng() { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# 偽の python: 与えた module 名だけ import できる / 起動自体が exit 69 で落ちる
mkpy() {  # path, "module ..." | GATED
  mkdir -p "$(dirname "$1")"
  if [ "$2" = "GATED" ]; then
    printf '#!/bin/sh\necho "You have not agreed to the Xcode license" >&2\nexit 69\n' > "$1"
  else
    cat > "$1" <<EOF
#!/bin/sh
# -c "import sys; import a; import b" の module が全部 "$2" に含まれれば 0
code="\$2"
for m in \$(printf '%s' "\$code" | tr ';' '\n' | sed -n 's/^ *import //p'); do
  [ "\$m" = sys ] && continue
  case " $2 " in *" \$m "*) : ;; *) exit 1 ;; esac
done
exit 0
EOF
  fi
  chmod +x "$1"
}
mkpy "$TMP/brew/python3" "json"
mkpy "$TMP/sys/python3" "json yaml"
mkpy "$TMP/gated/python3" "GATED"
mkpy "$TMP/other/python3" "json yaml googleapiclient"

got="$(PICK_PYTHON_CANDIDATES="$TMP/brew/python3:$TMP/sys/python3" pick_python yaml)"
[ "$got" = "$TMP/sys/python3" ] && ok "P1 PATH の順で先に来ても module が無い候補は飛ばす" || ng "P1 got=$got"
got="$(PICK_PYTHON_CANDIDATES="$TMP/gated/python3:$TMP/sys/python3" pick_python yaml)"
[ "$got" = "$TMP/sys/python3" ] && ok "P2 起動できない候補 (exit 69) も飛ばす" || ng "P2 got=$got"
got="$(PICK_PYTHON_CANDIDATES="$TMP/brew/python3:$TMP/gated/python3" pick_python yaml)"; rc=$?
[ $rc -eq 1 ] && printf '%s' "$got" | grep -q "yaml を import できる python3 が無い" && printf '%s' "$got" | grep -q "brew/python3" \
  && ok "P3 候補が全部駄目なら 1 + 試した候補を stdout に" || ng "P3 rc=$rc got=$got"
got="$(PICK_PYTHON="$TMP/brew/python3" PICK_PYTHON_CANDIDATES="$TMP/sys/python3" pick_python yaml)"; rc=$?
[ $rc -eq 1 ] && printf '%s' "$got" | grep -q "PICK_PYTHON" && ok "P4 明示指定が import できなければ失敗 (黙って別の候補に逃げない)" || ng "P4 rc=$rc got=$got"
got="$(PICK_PYTHON_CANDIDATES="$TMP/sys/python3:$TMP/other/python3" pick_python yaml googleapiclient)"
[ "$got" = "$TMP/other/python3" ] && ok "P5 複数 module は全部 import できる候補だけ" || ng "P5 got=$got"
ln -s "$TMP/brew/python3" "$TMP/link-python3"
got="$(PICK_PYTHON_CANDIDATES="$TMP/link-python3:$TMP/brew/python3:$TMP/sys/python3" pick_python yaml)"
[ "$got" = "$TMP/sys/python3" ] && ok "P6 同じ実体 (symlink) を重ねて試しても結果は同じ" || ng "P6 got=$got"
got="$(PICK_PYTHON_CANDIDATES="$TMP/gated/python3:$TMP/brew/python3" pick_python)"
[ "$got" = "$TMP/brew/python3" ] && ok "P7 module なしなら「起動できるか」 だけで選ぶ" || ng "P7 got=$got"
# 実機: 何かしら python3 が選べる (= 本物の候補列が壊れていない)
got="$(pick_python)" && [ -x "$got" ] && ok "P8 実機の候補列で起動できる python3 が選べる ($got)" || ng "P8 got=$got"

echo "==== RESULT: PASS=$PASS FAIL=$FAIL ===="
[ "$FAIL" -eq 0 ]
