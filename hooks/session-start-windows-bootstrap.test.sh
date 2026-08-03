#!/usr/bin/env bash
# session-start-windows-bootstrap.test.sh — self-tests for session-start-windows-bootstrap.sh
#
# POSIX (macOS/Linux) 上で stub 環境により hook logic を検証する (実 Windows 不要):
#   T1 非 Windows uname → 即 silent exit 0
#   T2 forced-Windows + 壊れた環境 → autocrlf fix + python3 shim copy + setx + 報告出力
#   T3 healthy 2 回目 → stamp fast path で silent
#   T4 shim 消失 → 自己治癒 (再 copy + 報告)
# ⚠️ 実 Windows での end-to-end は未検証 (hook header の marker 参照)

set -u
HOOK="$(cd "$(dirname "$0")" && pwd)/session-start-windows-bootstrap.sh"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "✅ $1"; }
miss() { FAIL=$((FAIL+1)); echo "❌ $1"; }

TEST_ROOT="$(mktemp -d -t winboot-test.XXXXXX)"
trap 'rm -rf "$TEST_ROOT"' EXIT
mkdir -p "$TEST_ROOT/home" "$TEST_ROOT/bin" "$TEST_ROOT/pybin"

# --- stubs (bin = git/setx/python3-Store-stub、 pybin = python 実体役) ---
cat > "$TEST_ROOT/bin/git" <<EOF
#!/bin/sh
# get: config --global core.autocrlf → "true" を返す (壊れた状態を演じる)
if [ "\$#" -eq 3 ] && [ "\$1 \$2 \$3" = "config --global core.autocrlf" ]; then echo "true"; exit 0; fi
if [ "\$#" -eq 4 ] && [ "\$1 \$2 \$3 \$4" = "config --global core.autocrlf false" ]; then touch "$TEST_ROOT/autocrlf.set"; exit 0; fi
exit 0
EOF
cat > "$TEST_ROOT/bin/setx" <<EOF
#!/bin/sh
echo "\$1=\$2" >> "$TEST_ROOT/setx.log"
exit 0
EOF
# Store stub 役: 実行せず「Python」 と印字するだけ (windows-msys.md #python3-missing-store-stub)
cat > "$TEST_ROOT/bin/python3" <<'EOF'
#!/bin/sh
echo "Python"
exit 0
EOF
# python 実体役 (pybin を PATH 先頭に置く = shim copy 後はこちらの python3 が解決される)
cat > "$TEST_ROOT/pybin/python" <<'EOF'
#!/bin/sh
[ "$1" = "-c" ] && echo "1"
exit 0
EOF
chmod +x "$TEST_ROOT/bin/"* "$TEST_ROOT/pybin/"*

run_hook() {  # $1 = forced OS ("" = real uname)
  CLAUDE_WINBOOT_FORCE_OS="$1" HOME="$TEST_ROOT/home" \
    PATH="$TEST_ROOT/pybin:$TEST_ROOT/bin:/usr/bin:/bin" \
    PYTHONUTF8= PYTHONIOENCODING= LOCALAPPDATA= \
    bash "$HOOK" 2>&1
}

# --- T1: 非 Windows → 即 silent exit 0 ---
out="$(CLAUDE_WINBOOT_FORCE_OS= HOME="$TEST_ROOT/home" bash "$HOOK" 2>&1)"; rc=$?
[ $rc -eq 0 ] && [ -z "$out" ] && ok "T1 非 Windows は silent exit 0" || miss "T1 (rc=$rc out='$out')"

# --- T2: forced-Windows + 壊れた環境 → 3 修復 + 報告 ---
out="$(run_hook "MINGW64_NT-10.0")"; rc=$?
[ $rc -eq 0 ] || miss "T2 rc=$rc"
[ -f "$TEST_ROOT/autocrlf.set" ] && ok "T2 autocrlf を false に修復" || miss "T2 autocrlf 未修復"
[ -x "$TEST_ROOT/pybin/python3" ] && ok "T2 python3 shim を copy" || miss "T2 shim 未作成"
grep -q "PYTHONUTF8=1" "$TEST_ROOT/setx.log" 2>/dev/null && ok "T2 PYTHONUTF8 setx" || miss "T2 PYTHONUTF8 未設定"
case "$out" in *"自動修復した"*) ok "T2 修復報告を出力" ;; *) miss "T2 報告なし: '$out'" ;; esac
[ -f "$TEST_ROOT/home/.claude/surface/windows-bootstrap.txt" ] && ok "T2 surface file 副作用" || miss "T2 surface なし"
[ -s "$TEST_ROOT/home/.claude/.windows-env-bootstrap.done" ] && ok "T2 stamp (healthy)" || miss "T2 stamp なし"

# --- T3: healthy 2 回目 → fast path silent ---
out="$(run_hook "MINGW64_NT-10.0")"; rc=$?
[ $rc -eq 0 ] && [ -z "$out" ] && ok "T3 2 回目は stamp fast path で silent" || miss "T3 (rc=$rc out='$out')"

# --- T4: shim 消失 → 自己治癒 ---
rm -f "$TEST_ROOT/pybin/python3"
out="$(run_hook "MINGW64_NT-10.0")"; rc=$?
[ -x "$TEST_ROOT/pybin/python3" ] && ok "T4 shim 消失を自己治癒" || miss "T4 未復活"
case "$out" in *"python3 shim を復活"*) ok "T4 復活を報告" ;; *) miss "T4 報告なし: '$out'" ;; esac

echo ""
echo "--- session-start-windows-bootstrap.test: PASS=$PASS FAIL=$FAIL ---"
[ $FAIL -eq 0 ]
