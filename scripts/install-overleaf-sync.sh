#!/usr/bin/env bash
# install-overleaf-sync.sh — Overleaf 連携 repo に sync script を 1 コマンド設置（template 展開 + URL から ID 抽出・焼き込み + --merge-opts / --ahead-expected + token があれば --status smoke、 冪等・別 ID は --force、 conventions/overleaf-integration.md#new-integration-checklist）
# install-overleaf-sync.sh — Overleaf 連携 repo に sync script を 1 コマンド設置。
#
# templates/overleaf-sync.sh.template を <repo>/scripts/overleaf-sync.sh に展開し、
# PROJECT_ID (= URL からの抽出可) / MERGE_OPTS / AHEAD_EXPECTED を焼き込んで chmod +x
# する。 設置後の commit と repo CLAUDE.md への mode + conflict 方針の明記は案内表示
# (= 規約 conventions/overleaf-integration.md#sync-script-contract)。
#
# Usage:
#   install-overleaf-sync.sh <repo_dir> <overleaf_url_or_24hex_id> [options]
#     <overleaf_url_or_24hex_id>: https://www.overleaf.com/project/<id> /
#       git.overleaf.com/<id> / 生の 24 桁 hex のどれでも可 (24 桁 hex を抽出する)
#   --merge-opts "<opts>"  conflict 方針 (既定 "-X theirs" = Overleaf 側採用)
#   --ahead-expected       恒常 ahead 運用 (= 管理 commit を Overleaf に push しない) の
#                          検出器 ahead INFO 抑制 marker を有効化
#   --force                既存 script の PROJECT_ID を別 ID で上書き
#
# 冪等: 既存 script が placeholder (FIXME_PROJECT_ID) なら ID を埋める。 同一 ID なら
# option のみ更新。 別 ID は --force が無ければ拒否 (= 誤った付け替え防止)。
# ⚠️ template 由来でない手書き script (= AHEAD_EXPECTED 変数等が無い) には option を
# 適用できないことがある → その場合は警告して該当 option を skip。

set -euo pipefail

usage() { sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; }

[ $# -ge 2 ] || { usage >&2; exit 2; }
REPO="$1"; shift
ID_ARG="$1"; shift
MERGE_OPTS_NEW=""
AHEAD_EXPECTED_NEW=""
FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --merge-opts) MERGE_OPTS_NEW="${2:?--merge-opts に値が必要}"; shift 2 ;;
    --ahead-expected) AHEAD_EXPECTED_NEW=1; shift ;;
    --force) FORCE=1; shift ;;
    *) echo "[install-overleaf-sync] 不明な option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -d "$REPO/.git" ] || { echo "[install-overleaf-sync] $REPO は git repo ではない。" >&2; exit 2; }

PROJECT_ID="$(printf '%s' "$ID_ARG" | grep -oE '[0-9a-f]{24}' | head -1 || true)"
[ -n "$PROJECT_ID" ] || {
  echo "[install-overleaf-sync] 24 桁 hex の project ID を抽出できない: $ID_ARG" >&2
  echo "[install-overleaf-sync] Overleaf web → 該当 project → Menu → Git の URL を渡す。" >&2
  exit 2
}

TEMPLATE="$(cd "$(dirname "$0")/.." && pwd)/templates/overleaf-sync.sh.template"
[ -f "$TEMPLATE" ] || { echo "[install-overleaf-sync] template が無い: $TEMPLATE" >&2; exit 2; }
DEST="$REPO/scripts/overleaf-sync.sh"

# sed -i の portable 化 (GNU/BSD 両対応)
sed_i() { sed -i.iosbak "$@" && rm -f "${@: -1}.iosbak"; }

if [ -f "$DEST" ]; then
  CUR_ID="$(grep -oE '^PROJECT_ID="[A-Za-z0-9_]+"' "$DEST" | head -1 | cut -d'"' -f2 || true)"
  if [ -z "$CUR_ID" ]; then
    echo "[install-overleaf-sync] 既存 script の PROJECT_ID 行を特定できない (手書き script?)。" >&2
    echo "[install-overleaf-sync] 手動で PROJECT_ID を記入してください。" >&2
    exit 1
  elif [ "$CUR_ID" = "$PROJECT_ID" ]; then
    echo "[install-overleaf-sync] 既存 script は同一 ID 設定済 (idempotent)。 option のみ更新。"
  elif [ "$CUR_ID" = "FIXME_PROJECT_ID" ]; then
    echo "[install-overleaf-sync] 既存 script の placeholder に ID を記入。"
    sed_i "s/^PROJECT_ID=\"FIXME_PROJECT_ID\"/PROJECT_ID=\"$PROJECT_ID\"/" "$DEST"
  elif [ "$FORCE" = "1" ]; then
    echo "[install-overleaf-sync] ⚠️ 既存 ID ($CUR_ID) を --force で上書き。"
    sed_i "s/^PROJECT_ID=\"$CUR_ID\"/PROJECT_ID=\"$PROJECT_ID\"/" "$DEST"
  else
    echo "[install-overleaf-sync] 既存 script に別 ID ($CUR_ID) が設定済。 付け替えは --force。" >&2
    exit 1
  fi
else
  mkdir -p "$REPO/scripts"
  cp "$TEMPLATE" "$DEST"
  sed_i "s/^PROJECT_ID=\"FIXME_PROJECT_ID\"/PROJECT_ID=\"$PROJECT_ID\"/" "$DEST"
  echo "[install-overleaf-sync] $DEST を新規設置 (PROJECT_ID = $PROJECT_ID)。"
fi

apply_var() {  # apply_var <VAR> <value>
  if grep -q "^$1=" "$DEST"; then
    sed_i "s|^$1=.*|$1=$2|" "$DEST"
    echo "[install-overleaf-sync] $1=$2 を設定。"
  else
    echo "[install-overleaf-sync] ⚠️ $DEST に $1 変数が無い (手書き script?)。 option を skip。" >&2
  fi
}
[ -n "$MERGE_OPTS_NEW" ] && apply_var MERGE_OPTS "\"$MERGE_OPTS_NEW\""
[ -n "$AHEAD_EXPECTED_NEW" ] && apply_var AHEAD_EXPECTED "1"

chmod +x "$DEST"

# token があれば smoke (= 設置直後に drift を一度可視化)
if [ -s "$HOME/.secrets/overleaf-token" ]; then
  echo "[install-overleaf-sync] smoke: --status 実行"
  bash "$DEST" --status || true
else
  echo "[install-overleaf-sync] token 未配置のため smoke は skip (~/.secrets/overleaf-token)。"
fi

cat <<'NEXT'
[install-overleaf-sync] 残り 2 手 (手動):
  1. git add scripts/overleaf-sync.sh && commit (= PROJECT_ID の SoT を恒久化)
  2. repo の CLAUDE.md に同期 mode + merge conflict 方針を明記
     (規約 = claude-config/conventions/overleaf-integration.md#sync-script-contract)
NEXT
