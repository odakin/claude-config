#!/bin/sh
# install-hook.sh — pdf-publish を git push で発火させる pre-push hook を置く (clone ごとに 1 回、 何度走らせてもよい)。
#
# 正本 = claude-config/templates/shared-project/pdf-publish/ (repo の tools/pdf-publish/ はその写し)。
# 置き場所 = git が hook を探す dir (core.hooksPath があればそこ = repo で共有、 無ければ .git/hooks = この clone だけ)。
# 既に別の pre-push があれば <名前>.before-pdf-publish に退避して鎖でつなぐ (その hook の結果で push は止まる)。
# hook は push を待たせない: 範囲を読んで pdf-publish.sh を背景で起動するだけ。 確かめる: sh install-hook.sh --check

ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "git repo の中で実行する"; exit 1; }
HOOKS=$(cd "$ROOT" && git rev-parse --git-path hooks) || exit 1
case "$HOOKS" in /*) ;; *) HOOKS="$ROOT/$HOOKS" ;; esac
HOOK="$HOOKS/pre-push"
MARK="# pdf-publish pre-push hook"

if [ "${1:-}" = "--check" ]; then
  if [ -f "$HOOK" ] && grep -qF "$MARK" "$HOOK"; then echo "ok: $HOOK"; exit 0; fi
  echo "未導入: $HOOK (sh tools/pdf-publish/install-hook.sh)"; exit 1
fi

mkdir -p "$HOOKS" || exit 1
if [ -f "$HOOK" ] && ! grep -qF "$MARK" "$HOOK"; then
  mv "$HOOK" "$HOOK.before-pdf-publish" || exit 1
  echo "既存の pre-push を $HOOK.before-pdf-publish に退避して鎖でつないだ"
fi
cat > "$HOOK" <<'EOF'
#!/bin/sh
# pdf-publish pre-push hook — push される範囲の文書の PDF を、 push を待たせずに背景で共有フォルダへ写す。
# 置いたのは tools/pdf-publish/install-hook.sh (正本 = claude-config/templates/shared-project/pdf-publish/)。
ROOT=$(git rev-parse --show-toplevel)
PUB="$ROOT/tools/pdf-publish/pdf-publish.sh"
IN=$(mktemp 2>/dev/null || mktemp -t prepush)
cat > "$IN"
ARGS=""
while read -r lref lsha rref rsha; do
  case "$lsha" in ''|0000000000000000000000000000000000000000) continue ;; esac
  case "$rsha" in
    0000000000000000000000000000000000000000) ARGS="$ARGS --new $lsha" ;;
    *) ARGS="$ARGS --range $rsha..$lsha" ;;
  esac
done < "$IN"
if [ -f "$PUB" ] && [ -n "$ARGS" ] && [ "${PDF_PUBLISH:-1}" != "0" ]; then
  if [ "${PDF_PUBLISH_FOREGROUND:-0}" = "1" ]; then sh "$PUB" $ARGS </dev/null
  else ( sh "$PUB" $ARGS </dev/null >/dev/null 2>&1 & ) </dev/null >/dev/null 2>&1
  fi
fi
if [ -x "$0.before-pdf-publish" ]; then
  "$0.before-pdf-publish" "$@" < "$IN"; rc=$?; rm -f "$IN"; exit $rc
fi
rm -f "$IN"
exit 0
EOF
chmod +x "$HOOK"
echo "置いた: $HOOK"
