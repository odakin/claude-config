#!/usr/bin/env bash
# link-secrets.sh — 個人層の secrets-repos.txt に並べた repo の secrets/* を ~/.secrets/<名前> に symlink で張る (setup.sh Step 5d の本体、 毎 session の自動適用からも呼ぶ)
#
# 使い方:
#   bash scripts/link-secrets.sh [--claude-dir DIR] [--layer DIR] [--pull] [--header TEXT]
#     --claude-dir DIR  repo を並べた base (既定 = この repo の親 dir)
#     --layer DIR       個人層 (既定 = scripts/lib/find-personal-layer.sh で探す。 無ければ何もしない)
#     --pull            張る前に各 secrets repo を fast-forward pull する (別の機械で足した・rotate した秘密を取り込む)
#     --header TEXT     何か張る・知らせるときだけ、 最初に 1 回出す見出し
#   bash scripts/link-secrets.sh --selftest
#
# 何をするか:
#   - 既に正しい symlink は黙って飛ばす = 変えたときだけ出力する (毎 session 呼んでも静か)
#   - ~/.secrets/ に同じ名前の普通の file があれば、 中身が secrets/ の正本と一致するときだけ symlink に置き換える
#     (= 別経路で運んだ token を git-crypt の経路へ移す)。 中身が違えば置き換えず知らせるだけ
#   - git-crypt が無い機械 (= secrets/ が暗号文のまま) と、 個人層・secrets-repos.txt が無い機械では何もしない
# なぜ独立の script か: 張るのが setup.sh だけだと、 後から secrets repo に足した秘密が他の機械に張られない
#   (実測: 張られていない秘密が 9 本あって道具が止まった。 予備の path で直接読む道具は欠けに気づかなかった)。
# 正本 = conventions/secret-handoff.md#placement-and-durability
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
LAYER=""
LAYER_GIVEN=0
PULL=0
HEADER=""
DEST_DIR="${LINK_SECRETS_DEST:-$HOME/.secrets}"

selftest() {
  local t pass=0 fail=0
  t="$(mktemp -d)"
  trap 'rm -rf "$t"' RETURN
  mkdir -p "$t/base/prefs" "$t/base/vault/secrets" "$t/dest"
  printf 'vault  # comment\n\n' > "$t/base/prefs/secrets-repos.txt"
  printf 'a\n' > "$t/base/vault/secrets/one.txt"
  printf 'b\n' > "$t/base/vault/secrets/two.txt"
  printf 'c\n' > "$t/base/vault/secrets/three.txt"
  printf 'x\n' > "$t/base/vault/secrets/.hidden"
  printf 'b\n' > "$t/dest/two.txt"        # same content = migrated
  printf 'other\n' > "$t/dest/three.txt"  # different = kept, warned
  check() { if [ "$2" = 1 ]; then pass=$((pass + 1)); echo "PASS: $1"; else fail=$((fail + 1)); echo "FAIL: $1"; fi; }
  out="$(LINK_SECRETS_DEST="$t/dest" LINK_SECRETS_ASSUME_CRYPT=1 bash "$SCRIPT_DIR/link-secrets.sh" --claude-dir "$t/base" --layer "$t/base/prefs" --header HDR)"
  check "new secret is linked" "$([ "$(readlink "$t/dest/one.txt")" = "$t/base/vault/secrets/one.txt" ] && echo 1 || echo 0)"
  check "same-content regular file becomes a link" "$([ -L "$t/dest/two.txt" ] && echo 1 || echo 0)"
  check "different-content regular file is kept" "$([ ! -L "$t/dest/three.txt" ] && [ "$(cat "$t/dest/three.txt")" = other ] && echo 1 || echo 0)"
  check "different-content file is reported" "$(printf '%s' "$out" | grep -q 'three.txt' && echo 1 || echo 0)"
  check "dot files are not linked" "$([ ! -e "$t/dest/.hidden" ] && echo 1 || echo 0)"
  check "header is printed once when something changed" "$([ "$(printf '%s\n' "$out" | grep -c '^HDR$')" = 1 ] && echo 1 || echo 0)"
  rm -f "$t/dest/three.txt"; printf 'c\n' > "$t/dest/three.txt"
  LINK_SECRETS_DEST="$t/dest" LINK_SECRETS_ASSUME_CRYPT=1 bash "$SCRIPT_DIR/link-secrets.sh" --claude-dir "$t/base" --layer "$t/base/prefs" >/dev/null
  out2="$(LINK_SECRETS_DEST="$t/dest" LINK_SECRETS_ASSUME_CRYPT=1 bash "$SCRIPT_DIR/link-secrets.sh" --claude-dir "$t/base" --layer "$t/base/prefs" --header HDR)"
  check "second run is silent" "$([ -z "$out2" ] && echo 1 || echo 0)"
  out3="$(LINK_SECRETS_DEST="$t/dest2" LINK_SECRETS_ASSUME_CRYPT=1 bash "$SCRIPT_DIR/link-secrets.sh" --claude-dir "$t/base" --layer "$t/nolayer")"
  check "no personal layer does nothing" "$([ -z "$out3" ] && [ ! -e "$t/dest2" ] && echo 1 || echo 0)"
  echo "passed=$pass failed=$fail"
  [ "$fail" = 0 ]
}

while [ $# -gt 0 ]; do
  case "$1" in
    --claude-dir) CLAUDE_DIR="${2%/}"; shift ;;
    --layer) LAYER="${2%/}"; LAYER_GIVEN=1; shift ;;
    --pull) PULL=1 ;;
    --header) HEADER="$2"; shift ;;
    --selftest) selftest; exit $? ;;
    *) echo "usage: $0 [--claude-dir DIR] [--layer DIR] [--pull] [--header TEXT] | --selftest" >&2; exit 2 ;;
  esac
  shift
done

# git-crypt が無ければ secrets/ は暗号文のまま = 張っても読めない
if [ "${LINK_SECRETS_ASSUME_CRYPT:-0}" != 1 ] && ! command -v git-crypt >/dev/null 2>&1; then
  exit 0
fi

if [ "$LAYER_GIVEN" = 0 ] && [ -f "$SCRIPT_DIR/lib/find-personal-layer.sh" ]; then
  # shellcheck source=/dev/null
  . "$SCRIPT_DIR/lib/find-personal-layer.sh"
  LAYER="$(find_personal_layer "$CLAUDE_DIR" 2>/dev/null || true)"
fi
[ -n "$LAYER" ] && [ -f "$LAYER/secrets-repos.txt" ] || exit 0

REPOS=()
while IFS= read -r repo; do
  REPOS+=("$repo")
done < <(awk '{ sub(/#.*/, ""); gsub(/^[ \t]+|[ \t]+$/, ""); } NF > 0 { print }' "$LAYER/secrets-repos.txt")
[ "${#REPOS[@]}" -gt 0 ] || exit 0

install -d -m 700 "$DEST_DIR"

if [ "$PULL" = 1 ]; then
  # 失敗 (remote 不通 / divergence) は今の commit で続ける。 範囲は secrets repo だけ
  for repo in "${REPOS[@]}"; do
    [ -d "$CLAUDE_DIR/$repo/.git" ] || continue
    git -C "$CLAUDE_DIR/$repo" pull --ff-only --quiet 2>/dev/null || true
  done
fi

printed=0
say() {
  if [ "$printed" = 0 ] && [ -n "$HEADER" ]; then
    echo "$HEADER"
  fi
  printed=1
  echo "$1"
}

for repo in "${REPOS[@]}"; do
  src_dir="$CLAUDE_DIR/$repo/secrets"
  [ -d "$src_dir" ] || continue
  for src in "$src_dir"/*; do
    [ -e "$src" ] || continue
    name="$(basename "$src")"
    case "$name" in .*) continue ;; esac
    dest="$DEST_DIR/$name"
    if [ -L "$dest" ] && [ "$(readlink "$dest")" = "$src" ]; then
      continue
    fi
    if [ -e "$dest" ] && [ ! -L "$dest" ]; then
      if cmp -s "$dest" "$src"; then
        rm -f "$dest"
        ln -sfn "$src" "$dest"
        say "  Migrated: $dest → symlink (regular-file content matched canonical, replaced)"
      else
        say "  WARNING: $dest is a regular file with content differing from $src (manual migration required), skipping"
      fi
      continue
    fi
    ln -sfn "$src" "$dest"
    say "  Linked: $dest -> $src"
  done
done
exit 0
