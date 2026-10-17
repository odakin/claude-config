#!/usr/bin/env bash
# install-snapshot-path-fix.sh — shell snapshot の PATH 修正係 (hooks/fix-snapshot-path-patch.sh) の launchd agent を、 設定フォルダ全部の snapshot を見張る形に揃える (macOS のみ・冪等)
#
# usage: install-snapshot-path-fix.sh [--check] [--quiet]
#   --check  書かずに、 plist が揃っていなければ理由を出して exit 1 (揃っていれば 0。 macOS 以外・修正係が無い機械も 0)
#   --quiet  変えたときだけ 1 行出す
#
# 何をするか:
#   ~/.claude と、 CLAUDE_CONFIG_DIR で分けた設定フォルダ (~/.claude-<name>) の shell-snapshots/ を全部 WatchPaths に
#   並べた plist を作り、 今の plist と中身が違うか agent が読み込まれていないときだけ入れ直す (unload → 書く → load)。
#   入れ直したら修正係を 1 回走らせ、 既にある snapshot も直す。 設定フォルダを新しく作ったら、 次の呼び出しで足される。
#   設定フォルダと見なすのは settings.json・projects/・shell-snapshots/ のどれかを持つ dir だけ (~/.claude-<name> の名前の
#   別物に shell-snapshots/ を作らない)。 見張る dir は無ければ作る (WatchPaths は在る path を見張る)。
#
# なぜ (実測): plist が ~/.claude/shell-snapshots だけを見ていて、 分けた設定フォルダの session の snapshot は一度も直らず、
#   その session の Bash には Homebrew の bin と ~/.local/bin が無かった (gh・git-lfs が見えず、 LFS の pre-push が push を
#   止めた)。 正本 = conventions/shell-env.md#snapshot-fix-per-config-dir
#
# 呼び元: setup.sh Step 2b / scripts/sync-hook-settings.sh (= setup.sh・post-merge・個人層の session 開始 bootstrap)
# 環境変数 (test 用): SNAPSHOT_FIX_PLIST (plist の置き場) / SNAPSHOT_FIX_SCRIPT (修正係の path) /
#   SNAPSHOT_FIX_LAUNCHCTL (launchctl の代わりに呼ぶ command)。 代役を渡さずに HOME を差し替えた呼び出しは何もしない
#   (= 偽の HOME の test が本物の launchd に plist を読み込ませない)
# 依存: bash 3.2 compatible。

set -u

CHECK=0
QUIET=0
for arg in "$@"; do
  case "$arg" in
    --check) CHECK=1 ;;
    --quiet) QUIET=1 ;;
    -h|--help) sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "install-snapshot-path-fix: 知らない引数 $arg" >&2; exit 2 ;;
  esac
done

[ "$(uname -s)" = "Darwin" ] || exit 0

LABEL="com.user.claude-snapshot-fix"
PLIST="${SNAPSHOT_FIX_PLIST:-$HOME/Library/LaunchAgents/$LABEL.plist}"
PATCH="${SNAPSHOT_FIX_SCRIPT:-$HOME/.claude/hooks/fix-snapshot-path-patch.sh}"
LAUNCHCTL="${SNAPSHOT_FIX_LAUNCHCTL:-launchctl}"
[ -f "$PATCH" ] || exit 0
# HOME を差し替えた test (偽の ~/.claude) から本物の launchd に偽の plist を読み込ませない:
# launchctl の代役を渡していないのに HOME が account の home と違うなら何もしない
REAL_HOME="$(eval echo "~$(id -un)")"
if [ -z "${SNAPSHOT_FIX_LAUNCHCTL:-}" ] && [ "$HOME" != "$REAL_HOME" ]; then
  exit 0
fi

xml_escape() { printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g'; }

dirs=()
for d in "$HOME/.claude" "$HOME"/.claude-*; do
  [ -d "$d" ] || continue
  [ -f "$d/settings.json" ] || [ -d "$d/projects" ] || [ -d "$d/shell-snapshots" ] || continue
  dirs+=("$d/shell-snapshots")
done
[ "${#dirs[@]}" -gt 0 ] || exit 0

watch=""
for s in "${dirs[@]}"; do
  watch="$watch        <string>$(xml_escape "$s")</string>
"
done

new="$(cat <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>WatchPaths</key>
    <array>
${watch}    </array>
    <key>ProgramArguments</key>
    <array>
        <string>$(xml_escape "$PATCH")</string>
    </array>
</dict>
</plist>
PLIST_EOF
)"

same=0
[ -f "$PLIST" ] && [ "$(cat "$PLIST")" = "$new" ] && same=1
loaded=0
"$LAUNCHCTL" list "$LABEL" >/dev/null 2>&1 && loaded=1
if [ "$same" -eq 1 ] && [ "$loaded" -eq 1 ]; then
  [ "$QUIET" -eq 1 ] || echo "install-snapshot-path-fix: OK (${#dirs[@]} 個の snapshot dir を見張っている)"
  exit 0
fi

if [ "$CHECK" -eq 1 ]; then
  [ "$same" -eq 1 ] || echo "install-snapshot-path-fix: plist が設定フォルダの一覧と違う ($PLIST)"
  [ "$loaded" -eq 1 ] || echo "install-snapshot-path-fix: $LABEL が読み込まれていない"
  exit 1
fi

for s in "${dirs[@]}"; do mkdir -p "$s"; done
mkdir -p "$(dirname "$PLIST")"
[ "$loaded" -eq 1 ] && "$LAUNCHCTL" unload "$PLIST" >/dev/null 2>&1
printf '%s\n' "$new" > "$PLIST"
"$LAUNCHCTL" load "$PLIST" >/dev/null 2>&1
if "$LAUNCHCTL" list "$LABEL" >/dev/null 2>&1; then
  echo "install-snapshot-path-fix: 入れ直した (${PLIST}、 ${#dirs[@]} 個の snapshot dir を見張る)"
else
  echo "install-snapshot-path-fix: WARNING: $LABEL を読み込めなかった ($PLIST)" >&2
fi
"$PATCH" >/dev/null 2>&1 || true
exit 0
