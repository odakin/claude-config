#!/usr/bin/env bash
# clip-copy.sh — 貼り付け用の文面をクリップボードに入れ、読み戻して一致を確かめる (macOS。 日本語などの非 ASCII も通す)
#
#   clip-copy.sh FILE        # FILE の中身を入れる
#   some-cmd | clip-copy.sh  # 標準入力を入れる
#   clip-copy.sh --selftest  # クリップボードを退避 → ASCII と日本語で確かめる → 元に戻す
#
# ⚠️ なぜ要るか (実測): locale が空の環境 (Claude Code の Bash など、 LANG / LC_ALL / LC_CTYPE が未設定) で
#   非 ASCII の文字列を pbcopy に流すと、 exit 0 のまま**空のクリップボード**になる (ASCII だけなら通る)。
#   `cat file | pbcopy` の結果を確かめずに「入れました」 と渡すと、 相手は空を貼る。 ここでは UTF-8 の locale を
#   明示して入れ、 pbpaste で読み戻して byte 一致を確かめる。 一致しなければ exit 1 (= 渡す前に気づく)。
# 手順の正本 = conventions/paste-destined-plain-text.md (② delivery)。
set -u
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 LC_CTYPE=en_US.UTF-8

copy_and_verify() {  # $1 = 入れる文面の file
  pbcopy < "$1" || return 1
  local got; got=$(mktemp)
  pbpaste > "$got"
  if cmp -s "$1" "$got"; then rm -f "$got"; return 0; fi
  # pbpaste は末尾の改行を落とさないが、 貼り付け先の都合で末尾改行だけの差は許す
  if [ "$(cat "$1")" = "$(cat "$got")" ]; then rm -f "$got"; return 0; fi
  rm -f "$got"; return 1
}

selftest() {
  if ! command -v pbcopy >/dev/null 2>&1; then echo "SKIP: pbcopy が無い (macOS 以外) — 検査していない"; return 0; fi
  local saved t fails=0; saved=$(mktemp); t=$(mktemp)
  pbpaste > "$saved"
  printf 'plain ascii line\n' > "$t"
  if copy_and_verify "$t"; then echo "PASS ASCII を入れて読み戻せる"; else echo "FAIL ASCII を入れて読み戻せる"; fails=1; fi
  printf '日本語の文面テスト。\n２行目（全角）\n' > "$t"
  # 呼び出し元の locale が空でも通ることを見る (= 上の export が効いているか)
  if env -u LANG -u LC_ALL -u LC_CTYPE bash "$0" "$t" >/dev/null 2>&1 && [ "$(pbpaste)" = "$(cat "$t")" ]; then
    echo "PASS locale が空の呼び出しでも日本語を入れて読み戻せる"
  else
    echo "FAIL locale が空の呼び出しでも日本語を入れて読み戻せる"; fails=1
  fi
  pbcopy < "$saved"; rm -f "$saved" "$t"
  echo "clip-copy selftest: $([ $fails -eq 0 ] && echo 'ALL PASS' || echo FAIL)"
  return $fails
}

case "${1:-}" in
  --selftest) selftest; exit $? ;;
  -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
esac

src="${1:-}"
tmp=""
if [ -z "$src" ]; then tmp=$(mktemp); cat > "$tmp"; src="$tmp"; fi
[ -f "$src" ] || { echo "❌ file が無い: $src" >&2; exit 2; }
if copy_and_verify "$src"; then
  echo "✅ クリップボードに入れた ($(wc -m < "$src" | tr -d ' ') 文字、読み戻して一致)"
  rc=0
else
  echo "❌ クリップボードに入れた内容が読み戻しと一致しない — 貼り付けを頼まない" >&2
  rc=1
fi
[ -n "$tmp" ] && rm -f "$tmp"
exit $rc
