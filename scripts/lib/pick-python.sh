#!/usr/bin/env bash
# pick-python.sh — 無人ジョブ (launchd / cron) の wrapper が使う python3 を、 PATH の順でなく「必要な module を import できるか」 で選ぶ (source して pick_python を呼ぶ)
#
# なぜ (正本 = conventions/shell-env.md#job-python-by-capability):
#   素の `python3` は発火面ごとに別の interpreter になる。 agent の session は設定の env の PATH、 対話 shell は rc の
#   PATH、 launchd のジョブは job 定義の PATH で解決し、 それぞれ先頭に来る dir が違う。 package manager の更新で
#   PATH 上の `python3` が新しい版に差し替わると、 編集が 1 つも無いのにジョブの interpreter から依存 (yaml 等) が
#   消え、 engine は import で終わる。 fail-open に書いた engine は exit 0 で終わるので、 ジョブは成功に見える
#   (実測: 通知のジョブが 1 度も通知を出さないまま、 launchd の記録は毎日「終了コード 0」 だった)。
#
# 使い方 (wrapper の中で):
#   . "$HOME/Claude/claude-config/scripts/lib/pick-python.sh" || exit 3
#   PY="$(pick_python yaml)" || { echo "$PY" >&2; exit 3; }     # 失敗時の stdout = 試した候補と理由
#   "$PY" "$ENGINE" ...
#
# 候補の順 (= 最初に全 module を import できたもの。 同じ実体は 1 回だけ試す):
#   1. $PICK_PYTHON (明示指定。 これが import できなければ失敗 = 指定を黙って無視しない)
#   2. /Library/Developer/CommandLineTools/usr/bin/python3 (Xcode の shim を通らない system python)
#   3. /usr/bin/python3 (CommandLineTools があれば DEVELOPER_DIR をそこへ向けて Xcode の gate を避ける)
#   4. PATH 上の python3 を順に (= それでも見つからないときの最後の手段)
#   test 用: $PICK_PYTHON_CANDIDATES (":" 区切り) で 2-4 を差し替える
#
# 返り値: 0 = stdout に interpreter の path / 1 = 候補なし (stdout に理由 1 行)。 起動できない候補
# (Xcode のライセンス未同意の exit 69 等) は import 失敗と同じく飛ばす。 module 無しで呼べば「起動できるか」 だけを見る。
# test = scripts/lib/pick-python.test.sh

pick_python() {
  if [ -d /Library/Developer/CommandLineTools ] && [ -z "${DEVELOPER_DIR:-}" ]; then
    export DEVELOPER_DIR=/Library/Developer/CommandLineTools
  fi
  local _code="import sys"
  local _m
  for _m in "$@"; do _code="$_code; import $_m"; done
  if [ -n "${PICK_PYTHON:-}" ]; then
    if "$PICK_PYTHON" -c "$_code" >/dev/null 2>&1; then
      printf '%s\n' "$PICK_PYTHON"; return 0
    fi
    printf '%s\n' "pick_python: 指定の PICK_PYTHON=$PICK_PYTHON が起動できないか ${*:-(module なし)} を import できない"
    return 1
  fi
  local _cands
  if [ -n "${PICK_PYTHON_CANDIDATES:-}" ]; then
    _cands="$PICK_PYTHON_CANDIDATES"
  else
    _cands="/Library/Developer/CommandLineTools/usr/bin/python3:/usr/bin/python3"
    local _p
    for _p in $(type -a -p python3 2>/dev/null); do _cands="$_cands:$_p"; done
  fi
  local _tried="" _c _real _seen=":"
  local IFS=":"
  for _c in $_cands; do
    [ -n "$_c" ] && [ -x "$_c" ] || continue
    _real="$(cd "$(dirname "$_c")" 2>/dev/null && pwd -P)/$(basename "$_c")"
    case "$_seen" in *":$_real:"*) continue ;; esac
    _seen="$_seen$_real:"
    if "$_c" -c "$_code" >/dev/null 2>&1; then
      printf '%s\n' "$_c"; return 0
    fi
    _tried="$_tried $_c"
  done
  printf '%s\n' "pick_python: ${*:-(module なし)} を import できる python3 が無い (試した:${_tried:- なし})"
  return 1
}
