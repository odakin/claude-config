#!/bin/sh
# claude-stable-path.test.sh — claude-stable-path.sh の test (固定の場所を作る・揃っていれば触らない・版上げで差し替える・未署名の版は置かない・使えない時の --print の戻り先・見張りの plist の形)
# 証明書つきで署名された実行 file (既定 = 手元の ~/.local/bin/claude の指す版、 env CLAUDE_TEST_SIGNED_BIN で替えられる) を
# APFS の clone で一時 dir に置いて使う (容量は食わない)。 launchctl には触らない (見張りは plist の形だけを見る)。
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
S="$HERE/claude-stable-path.sh"
[ "$(uname)" = Darwin ] || { echo "SKIP (macOS 以外)"; exit 0; }
REAL="$(readlink -f "${CLAUDE_TEST_SIGNED_BIN:-$HOME/.local/bin/claude}" 2>/dev/null)"
team="$(codesign -dv "$REAL" 2>&1 | sed -n 's/^TeamIdentifier=//p')"
if [ ! -x "$REAL" ] || [ -z "$team" ] || [ "$team" = "not set" ]; then
  echo "SKIP (証明書つきで署名された実行 file が無い)"; exit 0
fi
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/versions" "$T/agents"
cp -c "$REAL" "$T/versions/1.0.0" 2>/dev/null || cp "$REAL" "$T/versions/1.0.0"
ln -s "$T/versions/1.0.0" "$T/bin/claude"
export CLAUDE_NATIVE_LAUNCHER="$T/bin/claude" CLAUDE_NATIVE_VERSIONS="$T/versions" \
  CLAUDE_STABLE_DIR="$T/stable" CLAUDE_STABLE_AGENT_DIR="$T/agents"
ok=0; fail=0
check() { if eval "$1"; then ok=$((ok + 1)); else fail=$((fail + 1)); echo "FAIL: $2"; fi; }
ino() { stat -f %i "$1" 2>/dev/null; }

# 1. 無い → 作る
out="$(sh "$S" sync 2>&1)"; rc=$?
check '[ $rc -eq 0 ]' "初回の sync は 0 (rc=$rc: $out)"
check 'cmp -s "$T/stable/claude" "$T/versions/1.0.0"' "固定の場所の中身 = launcher の版"
check '[ "$(ino "$T/stable/claude")" != "$(ino "$T/versions/1.0.0")" ]' "hard link でなく別の file (clone か copy)"
check 'codesign --verify --strict "$T/stable/claude" 2>/dev/null' "固定の場所の署名が有効"
check 'sh "$S" --check >/dev/null 2>&1' "--check が current (0)"

# 2. 揃っていれば触らない
i1="$(ino "$T/stable/claude")"
out="$(sh "$S" sync 2>&1)"
check '[ -z "$out" ] && [ "$(ino "$T/stable/claude")" = "$i1" ]' "揃っている時は何も出さず file も替えない ($out)"

# 3. 版上げ → 差し替える (走っている process が持つ古い file は消えない = 別の inode に替わる)
cp -c "$REAL" "$T/versions/1.0.1" 2>/dev/null || cp "$REAL" "$T/versions/1.0.1"
ln -sfn "$T/versions/1.0.1" "$T/bin/claude"
check '! sh "$S" --check >/dev/null 2>&1' "版上げの直後は --check が current でない"
out="$(sh "$S" sync 2>&1)"
check '[ "$(ino "$T/stable/claude")" != "$i1" ]' "版上げで固定の場所を差し替える"
check 'grep -q "^1.0.1 " "$T/stable/.source"' "印に新しい版の名前"
check 'case "$out" in *1.0.1*) true ;; *) false ;; esac' "差し替えた時は 1 行出す ($out)"
check '[ "$(sh "$S" --print-stable)" = "$T/stable/claude" ]' "--print-stable が固定の場所を出す"

# 4. 未署名の版は置かない (固定の場所は前の版のまま、 --print は launcher に戻る)
i2="$(ino "$T/stable/claude")"
printf '#!/bin/sh\necho fake\n' > "$T/versions/9.9.9"; chmod 755 "$T/versions/9.9.9"
ln -sfn "$T/versions/9.9.9" "$T/bin/claude"
sh "$S" sync >/dev/null 2>&1; rc=$?
check '[ $rc -eq 4 ]' "未署名の版は exit 4 (rc=$rc)"
check '[ "$(ino "$T/stable/claude")" = "$i2" ] && grep -q "^1.0.1 " "$T/stable/.source"' "未署名の版で固定の場所を替えない"
check '[ "$(sh "$S" --print 2>/dev/null)" = "$T/bin/claude" ]' "使えない時の --print は launcher を出す"
check '! sh "$S" --print-stable >/dev/null 2>&1 && [ -z "$(sh "$S" --print-stable 2>/dev/null)" ]' "使えない時の --print-stable は何も出さず非 0"

# 5. launcher が無い
rm -f "$T/bin/claude"
sh "$S" sync >/dev/null 2>&1; rc=$?
check '[ $rc -eq 3 ]' "launcher が無ければ exit 3 (rc=$rc)"

# 6. 見張りの plist
sh "$S" --agent-plist > "$T/agent.plist"
check 'plutil -lint "$T/agent.plist" >/dev/null 2>&1' "見張りの plist が plist として正しい"
check 'grep -q "<string>$T/bin</string>" "$T/agent.plist" && grep -q "<string>$T/versions</string>" "$T/agent.plist"' "WatchPaths = launcher の dir と versions"
check 'grep -q "<string>sync</string>" "$T/agent.plist"' "見張りは sync を呼ぶ"

echo "==== RESULT: PASS=$ok FAIL=$fail ===="
[ "$fail" -eq 0 ]
