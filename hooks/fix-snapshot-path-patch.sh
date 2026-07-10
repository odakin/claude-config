#!/bin/zsh
# fix-snapshot-path-patch.sh — PATH スナップショット自動パッチ（REQUIRED_PATHS 方式、launchd WatchPaths から呼ばれる）
# Claude Code のシェルスナップショットの PATH を自動パッチ
# launchd WatchPaths から呼ばれる（~/.claude/shell-snapshots を監視）
#
# 問題: Claude Code がスナップショット生成時に shell init を走らせるが、
# .zprofile の brew shellenv 二重実行等で PATH が不完全になることがある。
# このスクリプトは必須 PATH エントリを補完する。
#
# スナップショット生成完了を待ってからパッチ
sleep 1

# 古いスナップショットの cleanup（最新 20 個だけ保持）
# Claude Code は snapshot を蓄積し続けるので bloat を防ぐ。
# 注意: ファイルの mtime は patch 実行で更新されてしまうので、
# ファイル名に埋め込まれた UNIX ms タイムスタンプで判定する。
# 形式: snapshot-zsh-<unix_ms>-<random>.sh
#
# subshell で cd してから ls することで basename だけ扱う:
# フルパスを sort -t- すると親ディレクトリの "shell-snapshots" の '-' で
# フィールドがずれて -k3 が zsh を指してしまうため。
SNAPSHOT_DIR="$HOME/.claude/shell-snapshots"
SNAPSHOT_KEEP=20
if [ -d "$SNAPSHOT_DIR" ]; then
  (cd "$SNAPSHOT_DIR" && ls -1 snapshot-*.sh 2>/dev/null) \
    | sort -t- -k3 -nr \
    | tail -n +$((SNAPSHOT_KEEP + 1)) \
    | sed "s|^|$SNAPSHOT_DIR/|" \
    | xargs rm -f 2>/dev/null
fi

# 必須 PATH エントリ（存在チェックして追加）
# Intel Mac (/usr/local) と Apple Silicon (/opt/homebrew) の両方を列挙。
# 存在チェックで該当しない方は自動的にスキップされる。
#
# 順序の意味: 配列の後ろのエントリほど、最終的な PATH の先頭に来る
# （for ループで順次 prepend するため）。慣例に沿って:
#   1. システム特殊 (X11, TeX) → 配列の前 = PATH の末尾近く
#   2. brew (homebrew/local) と Python 系 → 配列の中
#   3. ユーザー個人 bin (~/.local/bin) → 配列の最後 = PATH の頭
REQUIRED_PATHS=(
  "/opt/X11/bin"
  "/Library/TeX/texbin"
  "/opt/homebrew/opt/python@3.12/libexec/bin"
  "$HOME/Library/Python/3.9/bin"
  "$HOME/.npm-global/bin"
  "/opt/homebrew/sbin"
  "/usr/local/sbin"
  "/opt/homebrew/bin"
  "/usr/local/bin"
  "$HOME/.local/bin"
)

for f in ~/.claude/shell-snapshots/snapshot-*.sh; do
  [ -f "$f" ] || continue

  current_path=$(grep '^export PATH=' "$f" | sed 's/^export PATH=//' | sed 's/\\:/:/g')
  [ -z "$current_path" ] && continue

  modified=false
  for p in "${REQUIRED_PATHS[@]}"; do
    # ディレクトリが実在し、かつスナップショットの PATH に含まれていなければ追加
    if [ -d "$p" ] && ! echo "$current_path" | tr ':' '\n' | grep -qxF "$p"; then
      current_path="$p:$current_path"
      modified=true
    fi
  done

  if $modified; then
    # バックスラッシュエスケープ版とプレーン版の両方に対応
    escaped_path=$(echo "$current_path" | sed 's/:/\\:/g')
    if grep -q '\\:' "$f"; then
      sed -i '' "s|^export PATH=.*|export PATH=${escaped_path}|" "$f"
    else
      sed -i '' "s|^export PATH=.*|export PATH=${current_path}|" "$f"
    fi
    echo "$(date): Patched $f (added missing paths)" >> /tmp/claude-snapshot-fix.log
  fi
done
