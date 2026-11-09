#!/usr/bin/env bash
# session-start-upstream-pr.sh — SessionStart: 層1 の repo (claude-config・ai-collaboration) に upstream へ入っていない手元の変更があり、 その人が push できない (所有者でない) ときだけ、 PR にする道を 1 block で出す + 出した PR の後片付け (engine = scripts/upstream-pr.py の status と after)。 所有者の機械・変更の無い clone では何も出さない
#
# なぜ在るか: 人の手の書き換えと、 前の session が残した変更は、 turn の終わりの促し (session-commit-nudge.sh) に
# 乗らない。 session の開始はその取りこぼしの網 (PR の本文は書き換えた session でないと書けないので、 主な入口は
# turn の終わりの側)。 方針 = 層1 の repo の手元の変更を PR に運ぶ道具の docstring (scripts/upstream-pr.py)。
#
# 出力: engine の status の出力 (変更が無い・所有者なら無出力) と、 after の出力 (merge された PR の手元の branch を
# 消した・merge されずに閉じた PR の 1 回の知らせ) を <system-reminder> の 1 block で。 両方空なら完全沈黙。
# 所有者の判定・層1 の線・network の上限は engine が持つ (ここに述語を書かない)。
# fail-open: python3 / engine 不在・例外は無出力 exit 0 (engine の network は 1 回 8 秒まで)。
#
# env:
#   CLAUDE_UPSTREAM_PR=0          本 hook を止める (kill switch)
#   CLAUDE_UPSTREAM_PR_FORCE=1    stdin の SessionStart 判定を skip (test 用)
#   UPSTREAM_PR_ENGINE            engine の path (test 用、 既定 = 本 repo の scripts/upstream-pr.py)
# test = hooks/session-start-upstream-pr.test.sh

set -u
[ "${CLAUDE_UPSTREAM_PR:-1}" = "0" ] && exit 0
command -v python3 >/dev/null 2>&1 || exit 0

if [ "${CLAUDE_UPSTREAM_PR_FORCE:-0}" != "1" ]; then
  raw="$(cat 2>/dev/null || true)"
  case "$raw" in
    *'"SessionStart"'*) : ;;
    *) exit 0 ;;
  esac
fi

# symlink (~/.claude/hooks/ → <base>/claude-config/hooks/) を辿って repo を特定する
SELF="${BASH_SOURCE[0]}"
while [ -L "$SELF" ]; do
  LINK="$(readlink "$SELF")"
  case "$LINK" in /*) SELF="$LINK" ;; *) SELF="$(dirname "$SELF")/$LINK" ;; esac
done
REPO="$(cd "$(dirname "$SELF")/.." 2>/dev/null && pwd -P)" || exit 0
ENGINE="${UPSTREAM_PR_ENGINE:-$REPO/scripts/upstream-pr.py}"
[ -f "$ENGINE" ] || exit 0

status_out="$(python3 "$ENGINE" status --quiet-errors --timeout 8 2>/dev/null || true)"
after_out="$(python3 "$ENGINE" after --timeout 8 2>/dev/null || true)"
[ -z "$status_out" ] && [ -z "$after_out" ] && exit 0

printf '<system-reminder>\n'
printf '📤 層1 の repo の手元の変更 (層1 session-start-upstream-pr、 engine = scripts/upstream-pr.py)\n'
[ -n "$status_out" ] && printf '%s\n' "$status_out"
[ -n "$after_out" ] && printf '%s\n' "$after_out"
printf '</system-reminder>\n'
exit 0
