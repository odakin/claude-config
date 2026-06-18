#!/bin/bash
# .claude/pre-commit-extra.sh — claude-config 固有の pre-commit 規律 (検査 1-2 = 警告のみ / 検査 3 legacy gate = BLOCK)
#
# public-precommit-runner.sh が leak gate を pass 後に chain で呼ぶ (= 既存 channel への
# 相乗り。 新規 standalone 検出器 / dashboard 項目を増やさない)。 exit code は親に透過するが、
# 本 hook は **warning のみで常に exit 0** にして commit を止めない (= drift は annoyance 級で、
# convention-design-principles.md §9.1 の triage に従い catastrophic 級の block を当てない)。
#
# 検査: CONVENTIONS.md 冒頭の conventions/ 全列挙 と CLAUDE.md 構造 tree の conventions/ block が、
#       実体 `conventions/*.md` と一致しているか。 不一致なら「その commit の瞬間・その本人」に
#       warning を出す (= doc 記載の recall 依存 trigger 〔§8.12 最弱発火面〕 を機械発火に格上げ)。
#       .ja.md 翻訳 variant も列挙内に variant link として現れるため実体集合と一致する。
#
# 由来: DESIGN.md 2026-06-13「CONVENTIONS.md 冒頭の conventions/ 列挙」 の格上げ trigger の実体。
#       35→56 file の列挙 drift が ~2.5 ヶ月 silent 累積した RCA に対する発火面の機械化。
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONV="$REPO_ROOT/CONVENTIONS.md"
CLAUDE_MD="$REPO_ROOT/CLAUDE.md"
DIR="$REPO_ROOT/conventions"

[ -d "$DIR" ] || exit 0

# 実体: conventions/*.md の basename (名前順)
actual="$(cd "$DIR" && ls -1 ./*.md 2>/dev/null | sed 's#^\./##' | sort -u)"
[ -n "$actual" ] || exit 0

warned=0

# --- 検査 1: CONVENTIONS.md 冒頭の全列挙 ---
if [ -f "$CONV" ]; then
  enum_line="$(grep -m1 'ドメイン固有規約は' "$CONV" || true)"
  enumerated="$(printf '%s\n' "$enum_line" \
    | grep -oE 'conventions/[a-zA-Z0-9._-]+\.md' | sed 's#conventions/##' | sort -u)"
  miss="$(comm -23 <(printf '%s\n' "$actual") <(printf '%s\n' "$enumerated"))"
  extra="$(comm -13 <(printf '%s\n' "$actual") <(printf '%s\n' "$enumerated"))"
  if [ -n "$miss" ] || [ -n "$extra" ]; then
    echo "⚠️  [claude-config] CONVENTIONS.md 冒頭の conventions/ 全列挙が実体と drift:" >&2
    [ -n "$miss" ]  && echo "    列挙漏れ (実体にあり列挙になし): $(echo $miss)"  >&2
    [ -n "$extra" ] && echo "    列挙過剰 (列挙にあり実体になし): $(echo $extra)" >&2
    warned=1
  fi
fi

# --- 検査 2: CLAUDE.md 構造 tree の conventions/ block ---
# branch marker (├──/└──) anchor で tree entry のみ抽出 (= 説明文中の .md cross-ref を拾わない)
if [ -f "$CLAUDE_MD" ]; then
  tree_listed="$(awk '/├── conventions\//{f=1;next} /├── hooks\//{f=0} f' "$CLAUDE_MD" \
    | grep -oE '[├└]── [a-zA-Z0-9._-]+\.md' | sed -E 's/^[├└]── //' | sort -u)"
  if [ -n "$tree_listed" ]; then
    tmiss="$(comm -23 <(printf '%s\n' "$actual") <(printf '%s\n' "$tree_listed"))"
    textra="$(comm -13 <(printf '%s\n' "$actual") <(printf '%s\n' "$tree_listed"))"
    if [ -n "$tmiss" ] || [ -n "$textra" ]; then
      echo "⚠️  [claude-config] CLAUDE.md 構造 tree の conventions/ block が実体と drift:" >&2
      [ -n "$tmiss" ]  && echo "    tree 漏れ:  $(echo $tmiss)"  >&2
      [ -n "$textra" ] && echo "    tree 過剰:  $(echo $textra)" >&2
      warned=1
    fi
  fi
fi

if [ "$warned" -eq 1 ]; then
  echo "    → 名前順で同期してください (CONVENTIONS.md §8 行 / CLAUDE.md tree、 DESIGN.md 2026-06-13 参照)。" >&2
  echo "    (警告のみ・commit は継続)" >&2
fi

# --- 検査 3: legacy append-only (= 上の warn-only 群と違い BLOCK する例外) ---
# catastrophic 級: published §-number の転送先 (slug index の legacy 値) を黙って落とすと、
# 下層 repo / 他ユーザ / 過去メモの §-ref が永久に解決不能になる (= 回収不可)。 §9.1 triage で
# block。 staged の *.index.yaml を HEAD と比較し、 legacy が縮んでいたら commit を止める。 意図的な
# 節削除は `LEGACY_RETIRE_OK=1 git commit ...` で明示 override (= 消すのは可・黙っては不可)。
# 正本: scripts/check-legacy-append-only.py / convention-design-principles §14.7。
GATE="$REPO_ROOT/scripts/check-legacy-append-only.py"
if [ -f "$GATE" ]; then
  if ! python3 "$GATE" --staged >&2; then
    exit 1
  fi
fi

exit 0
