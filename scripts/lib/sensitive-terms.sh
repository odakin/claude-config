# sensitive-terms.sh — 実名 gate (Tier B) の検出語 file を読む共通部品 (source して使う、 bash 3.2 可)
#
# 正本: claude-config/scripts/lib/sensitive-terms.sh
# caller: public-precommit-runner.sh (Tier B。 scan-public-tree.sh と週次の audit-public-repos.sh もこの runner 経由) /
#         lib/commit-msg-leak-matcher.sh (a)
# 規律: conventions/confidential-repo-boundary.md#name-compound-allow
#
# 検出語 file (個人層の sensitive-terms.txt、 build-sensitive-terms.py が生成) の行の種類:
#   空行・`#` 行          … 無視
#   `!<語>`              … **許可する複合語** (例: 姓と同じ字で始まる地名)。 照合の前に本文から消す
#   ASCII だけの行        … `grep -wF` (単語境界)
#   それ以外 (日本語等)    … `grep -F` (部分一致。 CJK に単語境界は無い)
#
# なぜ複合語の許可が要るか: 姓は短い prefix (2 字) でも term にしている (= 本文では姓だけで書かれるため)。
# その 2 字が地名・歴史上の人物名の一部に現れると、 公開 repo の地図や冗談の文言で必ず鳴る (実測)。
# prefix ごと stoplist に落とすと「X さん」 も止まらなくなる。 **その複合語だけ**を許可すれば網は縮まない。
# 複合語に 3 字以上の term (= 氏名に近い語) が含まれる設定は build-sensitive-terms.py が拒否する。
#
# 古い caller は `!` 行を「! で始まる term」 として扱う = 本文に現れない文字列なので無害 (= 鳴る側に倒れる)。

# st_split <terms file> <ascii out> <non-ascii out> <allow out>
st_split() {
  : > "$2"; : > "$3"; : > "$4"
  [ -s "$1" ] || return 0
  awk -v a="$2" -v n="$3" -v w="$4" '
    /^[[:space:]]*$/ { next }
    /^[[:space:]]*#/ { next }
    /^!/            { sub(/^!/, ""); if (length($0) > 0) print > w; next }
    /^[ -~]+$/      { print > a; next }
                    { print > n }
  ' "$1"
}

# st_strip_allowed <allow file>  : stdin の各行から許可した複合語を空白に置き換えて stdout へ (行数は変えない)
st_strip_allowed() {
  if [ ! -s "$1" ]; then
    cat
    return 0
  fi
  awk 'NR == FNR { if (length($0) > 0) w[++k] = $0; next }
       {
         for (i = 1; i <= k; i++) {
           while ((p = index($0, w[i])) > 0) {
             $0 = substr($0, 1, p - 1) " " substr($0, p + length(w[i]))
           }
         }
         print
       }' "$1" -
}

# st_hit_line_numbers <ascii terms> <non-ascii terms> : stdin の行のうち term に当たる行の番号 (1 始まり、 昇順・重複なし)
st_hit_line_numbers() {
  local buf
  buf="$(mktemp)"
  cat > "$buf"
  {
    [ -s "$1" ] && grep -nwFf "$1" "$buf" 2>/dev/null | cut -d: -f1
    [ -s "$2" ] && grep -nFf "$2" "$buf" 2>/dev/null | cut -d: -f1
  } | sort -n -u
  rm -f "$buf"
}
