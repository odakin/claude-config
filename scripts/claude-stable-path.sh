#!/bin/sh
# claude-stable-path.sh — native installer の Claude Code CLI を版に依らない固定の場所へ複製して保つ (macOS のフォルダ等の許可を版上げのたびに聞き直さないため。 sync / --print / --print-stable / --check / --install-agent / --uninstall-agent、 macOS 限定、 conventions/macos-claude-code-tcc-recurring-prompt.md#stable-cli-path)
#
# なぜ: native installer の CLI は `~/.local/bin/claude` → `~/.local/share/claude/versions/<版>` の symlink で、
#   版が上がるたびに新しい file が置かれる。 launchd の定期 job など、 CLI が自分で許可の責任者になる起動では、
#   macOS はデスクトップ・書類・ダウンロード・cloud storage の許可を「実行 file の path」 に記録する
#   (記録の要件は署名の identifier + Team ID = 版を跨いで同じ)。 path が版ごとに変わるので、 版上げのたびに
#   全部聞き直しになり、 答えるまでその run は止まる (実測)。 path を固定すれば、 一度の許可が次の版にも当たる。
#
# 仕組み:
#   固定の場所 = $CLAUDE_STABLE_DIR/claude (既定 ~/.local/share/claude-stable/claude)。 launcher の指す版を
#   APFS の clone (`cp -c` = 容量を食わない) で一時名に置き、 署名を確かめてから `mv` で差し替える
#   (= 走っている process は古い file を持ったまま壊れない)。 hard link にしないのは、 同じ file に名前が
#   2 つあると、 macOS が process の path をどちらの名前で報告するかが保証されないため (clone なら別の file = 曖昧さが無い)。
#   版の名前・大きさ・更新時刻を $CLAUDE_STABLE_DIR/.source に書き、 一致すれば何もしない (= 毎回呼んでも安い)。
#   launcher (~/.local/bin/claude) は触らない = 上流の自動更新・古い版の掃除はそのまま動く。
#   差し替えの契機 = launchd の WatchPaths (~/.local/bin と versions/ の変化) + 呼び出し側の --print / --print-stable
#   (= 見張りが取りこぼしても、 使う直前に揃う)。
#
# usage:
#   sh claude-stable-path.sh [sync]          固定の場所を launcher の版に揃える (揃っていれば何もしない)
#   sh claude-stable-path.sh --print         揃えてから、 起動に使う path を出す (固定の場所が使えなければ launcher)
#   sh claude-stable-path.sh --print-stable  揃えてから、 固定の場所が使えるときだけその path を出す (使えなければ何も出さず exit 1)
#   sh claude-stable-path.sh --check         状態を 1 行 (current / stale / missing / no-launcher) + 見張りの有無。 変えない
#   sh claude-stable-path.sh --install-agent 見張り (launchd agent) を入れる・plist が変わっていれば入れ直す + 揃える。 冪等、 変えた時だけ 1 行
#   sh claude-stable-path.sh --uninstall-agent  見張りを外す (固定の場所の file は残す)
#   sh claude-stable-path.sh --agent-plist   見張りの plist を stdout に出す (test 用)
# 終了値: 0 = 成功 / 1 = 固定の場所が使えない (--print-stable) / 3 = launcher が実行 file を指していない /
#   4 = 証明書つきの署名でない (= 固定しても許可は版を跨がない) / 5 = 署名の主が前の版と違う / 6 = 署名の検証に落ちた /
#   7 = 複製・差し替えに失敗。 macOS 以外では何もせず 0 (--print は launcher を出す)。
# env: CLAUDE_STABLE_DIR / CLAUDE_NATIVE_LAUNCHER (既定 ~/.local/bin/claude) / CLAUDE_NATIVE_VERSIONS
#   (既定 ~/.local/share/claude/versions) / CLAUDE_STABLE_AGENT_DIR (既定 ~/Library/LaunchAgents)
# test: claude-stable-path.test.sh

LAUNCHER="${CLAUDE_NATIVE_LAUNCHER:-$HOME/.local/bin/claude}"
VERSIONS_DIR="${CLAUDE_NATIVE_VERSIONS:-$HOME/.local/share/claude/versions}"
STABLE_DIR="${CLAUDE_STABLE_DIR:-$HOME/.local/share/claude-stable}"
STABLE="$STABLE_DIR/claude"
STAMP="$STABLE_DIR/.source"
LABEL="com.claude-config.claude-stable-path"
AGENT_DIR="${CLAUDE_STABLE_AGENT_DIR:-$HOME/Library/LaunchAgents}"
PLIST="$AGENT_DIR/$LABEL.plist"
LOG="$HOME/Library/Logs/$LABEL.log"
SELF="$(cd "$(dirname "$0")" 2>/dev/null && pwd)/$(basename "$0")"

src_of() { readlink -f "$LAUNCHER" 2>/dev/null; }
stamp_of() { printf '%s %s\n' "$(basename "$1")" "$(stat -f '%z %m' "$1" 2>/dev/null)"; }
sig_field() { codesign -dv "$1" 2>&1 | sed -n "s/^$2=//p" | head -1; }

state() {
  src="$(src_of)"
  if [ -z "$src" ] || [ ! -x "$src" ]; then echo no-launcher; return; fi
  if [ ! -x "$STABLE" ]; then echo missing; return; fi
  if [ "$(cat "$STAMP" 2>/dev/null)" = "$(stamp_of "$src")" ]; then echo current; else echo stale; fi
}

sync_stable() {
  src="$(src_of)"
  if [ -z "$src" ] || [ ! -x "$src" ]; then
    echo "claude-stable-path: $LAUNCHER が実行 file を指していない" >&2; return 3
  fi
  want="$(stamp_of "$src")"
  if [ -x "$STABLE" ] && [ "$(cat "$STAMP" 2>/dev/null)" = "$want" ]; then return 0; fi
  [ "$src" = "$STABLE" ] && return 0
  id="$(sig_field "$src" Identifier)"
  team="$(sig_field "$src" TeamIdentifier)"
  case "$team" in
    ''|'not set')
      echo "claude-stable-path: $src は証明書つきで署名されていない (TeamIdentifier=${team:-無し}) = 固定しても許可は版を跨がないので置かない" >&2
      return 4 ;;
  esac
  if [ -x "$STABLE" ]; then
    oid="$(sig_field "$STABLE" Identifier)"
    oteam="$(sig_field "$STABLE" TeamIdentifier)"
    if [ "$oid $oteam" != "$id $team" ]; then
      echo "claude-stable-path: 署名の主が前の版と違う ($oid $oteam → $id $team) = 差し替えない" >&2
      return 5
    fi
  fi
  if ! codesign --verify --strict "$src" 2>/dev/null; then
    echo "claude-stable-path: $src の署名の検証に落ちた = 差し替えない" >&2; return 6
  fi
  mkdir -p "$STABLE_DIR" || return 7
  tmp="$STABLE_DIR/.claude.new.$$"
  if ! { cp -c "$src" "$tmp" 2>/dev/null || cp "$src" "$tmp"; }; then
    rm -f "$tmp"; echo "claude-stable-path: $src を複製できない" >&2; return 7
  fi
  chmod 755 "$tmp"
  if ! codesign --verify --strict "$tmp" 2>/dev/null; then
    rm -f "$tmp"; echo "claude-stable-path: 複製の署名の検証に落ちた = 差し替えない" >&2; return 6
  fi
  if ! mv -f "$tmp" "$STABLE"; then
    rm -f "$tmp"; echo "claude-stable-path: $STABLE に差し替えられない" >&2; return 7
  fi
  printf '%s\n' "$want" > "$STAMP.tmp.$$" && mv -f "$STAMP.tmp.$$" "$STAMP"
  echo "claude-stable-path: $STABLE ← $(basename "$src")"
}

agent_plist() {
  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>$SELF</string>
    <string>sync</string>
  </array>
  <key>WatchPaths</key>
  <array>
    <string>$(dirname "$LAUNCHER")</string>
    <string>$VERSIONS_DIR</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
}

agent_loaded() { launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; }

install_agent() {
  # native installer の launcher が無い機械 (npm で入れた CLI など = 実行 file の path が版を跨いで変わらない) では
  # 見張りも固定の場所も要らない = 何も出さずに終わる (毎 session 呼ばれるので、 使えない見張りを入れない・知らせを出さない)
  [ "$(state)" = no-launcher ] && return 0
  case "$SELF$LAUNCHER$VERSIONS_DIR$LOG" in
    *[\&\<\>\"]*) echo "claude-stable-path: path に XML で使えない文字がある" >&2; return 7 ;;
  esac
  mkdir -p "$AGENT_DIR" "$HOME/Library/Logs" || return 7
  new="$(agent_plist)"
  if [ -f "$PLIST" ] && [ "$(cat "$PLIST")" = "$new" ] && agent_loaded; then
    sync_stable; return $?
  fi
  printf '%s\n' "$new" > "$PLIST.tmp.$$" && mv -f "$PLIST.tmp.$$" "$PLIST" || return 7
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
  launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl bootstrap "gui/$(id -u)" "$PLIST" || return 7
  echo "claude-stable-path: 見張り ($LABEL) を入れた"
  sync_stable
}

[ "$(uname)" = Darwin ] || { [ "${1:-}" = --print ] && echo "$LAUNCHER"; exit 0; }

case "${1:-sync}" in
  sync) sync_stable ;;
  --print)
    sync_stable >/dev/null
    if [ "$(state)" = current ]; then echo "$STABLE"; else echo "$LAUNCHER"; fi ;;
  --print-stable)
    sync_stable >/dev/null
    [ "$(state)" = current ] || exit 1
    echo "$STABLE" ;;
  --check)
    st="$(state)"
    if agent_loaded; then ag="見張り あり"; else ag="見張り なし"; fi
    echo "$st $STABLE ($(cat "$STAMP" 2>/dev/null | cut -d' ' -f1)) / launcher → $(basename "$(src_of)") / $ag"
    case "$st" in current) exit 0 ;; stale) exit 1 ;; missing) exit 2 ;; *) exit 3 ;; esac ;;
  --install-agent) install_agent ;;
  --uninstall-agent)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
    rm -f "$PLIST"
    echo "claude-stable-path: 見張り ($LABEL) を外した ($STABLE は残す)" ;;
  --agent-plist) agent_plist ;;
  -h|--help) sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) echo "usage: claude-stable-path.sh [sync|--print|--print-stable|--check|--install-agent|--uninstall-agent]" >&2; exit 2 ;;
esac
