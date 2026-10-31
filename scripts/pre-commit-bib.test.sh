#!/usr/bin/env bash
# pre-commit-bib.test.sh — pre-commit-bib (全 repo 共通の git pre-commit) の配線 test: SESSION.md の形の gate・変数の直後の全角文字の gate・学生の識別子の gate が commit を止める / 通す / escape hatch で通る + path 指定の commit で .bib を自動修正したら止めて打ち直させる (hermetic)
#
# 正本: claude-config/scripts/pre-commit-bib.test.sh
# 実行: bash scripts/pre-commit-bib.test.sh (run-all-checks.sh が自動発見)
#
# 述語と閾値の SoT = check-session-shape.py docstring (selftest がそこを持つ)。 ここは**配線**の固定 =
# .git/hooks/pre-commit → pre-commit-bib の symlink を張った一時 repo で、 日付を見出しにした節を SESSION.md に足す commit が
# 止まる (exit ≠ 0 かつ engine の見出しが stderr に出る) / 案件の pointer 行は通る / CLAUDE_SESSION_SHAPE_GUARD=0 で通る
# (= 止めたのがこの gate だという証拠)。 個人層の chain hook は HOME を偽の dir にして外す (他 user と同じ状態で測る)。
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/pre-commit-bib"
[ -f "$HOOK" ] || { echo "FAIL: not found: $HOOK"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 不在 — test 省略"; exit 0; }
command -v git >/dev/null 2>&1 || { echo "SKIP: git 不在 — test 省略"; exit 0; }

pass=0; fail=0
ok() { pass=$((pass+1)); echo "  PASS  $1"; }
ng() { fail=$((fail+1)); echo "  FAIL  $1"; }

TMP="$(mktemp -d "${TMPDIR:-/tmp}/pre-commit-bib-test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
FAKE_HOME="$TMP/home"; mkdir -p "$FAKE_HOME"
REPO="$TMP/repo"; mkdir -p "$REPO"
(
  cd "$REPO" && git init -q -b main && git config user.email t@example.invalid && git config user.name t \
  && ln -sf "$HOOK" .git/hooks/pre-commit \
  && printf '# S\n\n- 案件 A — 次 = X → [正本](DESIGN.md)\n' > SESSION.md && git add SESSION.md \
  && HOME="$FAKE_HOME" git commit -q -m init
) >/dev/null 2>&1 || { echo "FAIL: 一時 repo の初期化"; exit 1; }

try_commit() { # <file content> [env...] → stderr を $OUT に、 rc を返す
  local content="$1"; shift
  printf '%s' "$content" > "$REPO/SESSION.md"
  (cd "$REPO" && git add SESSION.md && env HOME="$FAKE_HOME" "$@" git commit -q -m t 2>"$TMP/err" >/dev/null)
  local rc=$?
  OUT="$(cat "$TMP/err")"
  (cd "$REPO" && git reset -q --hard HEAD) >/dev/null 2>&1
  return $rc
}

if try_commit $'# S\n\n## 2026-09-28 — 何をした\n- y\n'; then
  ng "日付の節を足す commit が通ってしまった"
else
  case "$OUT" in *"check-session-shape:"*) ok "日付の節を足す commit を pre-commit-bib が止める (engine の見出しつき)";; *) ng "止まったが engine の見出しが無い (別の gate?): $(printf '%s' "$OUT" | head -3)";; esac
fi

if try_commit $'# S\n\n- 案件 A — 次 = Y → [正本](DESIGN.md)\n'; then ok "案件の pointer 行の commit は通る"; else ng "pointer 行の commit が止まった: $(printf '%s' "$OUT" | head -3)"; fi

if try_commit $'# S\n\n## 2026-09-28 — 何をした\n' CLAUDE_SESSION_SHAPE_GUARD=0; then ok "escape hatch (CLAUDE_SESSION_SHAPE_GUARD=0) で通る = 止めたのはこの gate"; else ng "escape hatch でも止まる: $(printf '%s' "$OUT" | head -3)"; fi

# 暗号化の一致: SESSION.md に filter が付いた repo で、 filter の無い SESSION-archive.md を足す commit を止める
# (filter の driver は設定しない = 属性の食い違いだけで止まることを見る)。 CLAUDE_SESSION_CRYPT_GUARD=0 で通る = この gate が止めた証拠。
CREPO="$TMP/crepo"; mkdir -p "$CREPO"
(
  cd "$CREPO" && git init -q -b main && git config user.email t@example.invalid && git config user.name t \
  && ln -sf "$HOOK" .git/hooks/pre-commit \
  && printf 'SESSION.md filter=selftestcrypt\n' > .gitattributes \
  && printf '# S\n\n- 案件 A — 次 = X → [正本](DESIGN.md)\n' > SESSION.md && git add .gitattributes SESSION.md \
  && HOME="$FAKE_HOME" git commit -q -m init
) >/dev/null 2>&1 || { echo "FAIL: 暗号化の一時 repo の初期化"; exit 1; }
CINIT="$(git -C "$CREPO" rev-parse HEAD)"
try_archive() { # [env...] → stderr を $OUT に、 rc を返す
  printf '# SESSION-archive\n\n## 2026-01-01 — 移した節\n- x\n' > "$CREPO/SESSION-archive.md"
  (cd "$CREPO" && git add SESSION-archive.md && env HOME="$FAKE_HOME" "$@" git commit -q -m t 2>"$TMP/err" >/dev/null)
  local rc=$?
  OUT="$(cat "$TMP/err")"
  (cd "$CREPO" && git reset -q --hard "$CINIT" && git clean -qfd) >/dev/null 2>&1  # 通ってしまった commit も戻す
  return $rc
}
if try_archive; then
  ng "暗号化された SESSION.md の隣に平文の archive を足す commit が通ってしまった"
else
  case "$OUT" in *"check-session-shape:"*"archive-plaintext"*) ok "平文の archive を足す commit を pre-commit-bib が止める (engine の見出しつき)";; *) ng "止まったが engine の見出しが無い: $(printf '%s' "$OUT" | head -3)";; esac
fi
if try_archive CLAUDE_SESSION_CRYPT_GUARD=0; then ok "escape hatch (CLAUDE_SESSION_CRYPT_GUARD=0) で通る = 止めたのはこの gate"; else ng "escape hatch でも止まる: $(printf '%s' "$OUT" | head -3)"; fi

# README / SESSION を正本と書いた行: 非公開 repo の README / SESSION 以外の file でも止める
printf '# D\n\n- 手順は README.md §How to build が正本。\n' > "$REPO/DESIGN.md"
if (cd "$REPO" && git add DESIGN.md && env HOME="$FAKE_HOME" git commit -q -m t 2>"$TMP/err" >/dev/null); then
  ng "「README が正本」 の行を足す commit が通ってしまった"
else
  case "$(cat "$TMP/err")" in *"check-session-shape:"*"sot-claim"*) ok "「README が正本」 の行を足す commit を止める (engine の見出しつき)";; *) ng "止まったが engine の見出しが無い: $(head -3 "$TMP/err")";; esac
fi
(cd "$REPO" && git reset -q --hard HEAD && git clean -qfd) >/dev/null 2>&1

# 変数の直後の全角文字の gate (check-unbraced-multibyte-var.py): shell script に「$name + 読点」 を足す commit を止める
# (engine の BLOCK 見出しつき) / ${name} + 読点 は通る / CLAUDE_UNBRACED_MB_VAR_GUARD=0 で通る (= 止めたのがこの gate) /
# engine が見出しなしで異常終了しても commit は止めず 1 行出す (= 故障を違反と読まない)。 述語の SoT = engine の docstring。
# fixture の全角文字は printf の 8 進で書く (この file 自体が gate に当たらないように)。
UMV_BASE="$(git -C "$REPO" rev-parse HEAD)"
try_sh() { # <file content> [env...] → stderr を $OUT に、 rc を返す (通った commit も戻す)
  local content="$1"; shift
  printf '%s' "$content" > "$REPO/run.sh"
  (cd "$REPO" && git add run.sh && env HOME="$FAKE_HOME" "$@" git commit -q -m t 2>"$TMP/err" >/dev/null)
  local rc=$?
  OUT="$(cat "$TMP/err")"
  (cd "$REPO" && git reset -q --hard "$UMV_BASE" && git clean -qfd) >/dev/null 2>&1
  return $rc
}
UMV_BAD="$(printf '#!/usr/bin/env bash\necho "$name\343\200\201"\n')"
UMV_OK="$(printf '#!/usr/bin/env bash\necho "${name}\343\200\201"\n')"
if try_sh "$UMV_BAD"; then
  ng "「\$name + 読点」 を足す commit が通ってしまった"
else
  case "$OUT" in *"check-unbraced-multibyte-var: BLOCK"*) ok "「\$name + 読点」 を足す commit を pre-commit-bib が止める (engine の BLOCK 見出しつき)";; *) ng "止まったが engine の見出しが無い (別の gate?): $(printf '%s' "$OUT" | head -3)";; esac
fi
if try_sh "$UMV_OK"; then ok "「\${name} + 読点」 の commit は通る"; else ng "「\${name} + 読点」 の commit が止まった: $(printf '%s' "$OUT" | head -3)"; fi
if try_sh "$UMV_BAD" CLAUDE_UNBRACED_MB_VAR_GUARD=0; then ok "escape hatch (CLAUDE_UNBRACED_MB_VAR_GUARD=0) で通る = 止めたのはこの gate"; else ng "escape hatch でも止まる: $(printf '%s' "$OUT" | head -3)"; fi
# 偽の scripts dir = hook は写し (readlink の解決先をここにする)、 他は本物への symlink、 この engine だけ見出しなしの rc 1 で落ちる stub
FAKE_SCRIPTS="$TMP/fake-scripts"; mkdir -p "$FAKE_SCRIPTS"
for f in "$HERE"/*; do ln -s "$f" "$FAKE_SCRIPTS/$(basename "$f")"; done
rm -f "$FAKE_SCRIPTS/pre-commit-bib" "$FAKE_SCRIPTS/check-unbraced-multibyte-var.py"
cp "$HOOK" "$FAKE_SCRIPTS/pre-commit-bib"
printf 'import sys\nsys.exit(1)\n' > "$FAKE_SCRIPTS/check-unbraced-multibyte-var.py"
ln -sf "$FAKE_SCRIPTS/pre-commit-bib" "$REPO/.git/hooks/pre-commit"
if try_sh "$UMV_BAD"; then
  case "$OUT" in *"異常終了"*) ok "engine が見出しなしで落ちても commit は通り、 1 行出る";; *) ng "engine の故障で commit は通ったが 1 行が出ない";; esac
else
  ng "engine の故障で commit が止まった: $(printf '%s' "$OUT" | head -3)"
fi
ln -sf "$HOOK" "$REPO/.git/hooks/pre-commit"

# 学生の識別子の gate (check-student-identifiers.py): この test だけの架空の一覧を env で渡し、 学生の姓を含む新しい path /
# 氏名と学籍番号を足した行を止める / 識別子の無い commit は通る / CLAUDE_STUDENT_ID_GUARD=0 で通る (= 止めたのがこの gate) /
# engine が見出しなしで落ちても commit は止めず 1 行出す / 壊れた一覧 (exit 3 + 見出し) では止めない。 述語の SoT = engine の docstring。
# 学籍番号の形の値は実行時に組み立てる (この file 自体が gate に当たらないように)。
SID_LIST="$TMP/student-identity.json"
cat > "$SID_LIST" <<'SID_EOF'
{"schema": 1, "full_names_cjk": ["仮野 名子"], "full_names_latin": [["karino", "nako"]],
 "surnames_latin": ["karino"], "surnames_cjk": ["仮野"]}
SID_EOF
SID_PAT="$TMP/pii-patterns.txt"
printf '%s\n' '(?i)(?<![0-9a-z])[a-z][0-9]{2}[a-z][0-9]{3,4}(?![0-9a-z])' > "$SID_PAT"
SID_ID="$(printf 'A%02dX%s' 12 3456)"
SID_BASE="$(git -C "$REPO" rev-parse HEAD)"
try_sid() { # <path> <content> [env...] → stderr を $OUT に、 rc を返す (通った commit も戻す)
  local path="$1" content="$2"; shift 2
  mkdir -p "$REPO/$(dirname "$path")"
  printf '%s\n' "$content" > "$REPO/$path"
  (cd "$REPO" && git add -- "$path" && env HOME="$FAKE_HOME" CLAUDE_STUDENT_IDENTITY="$SID_LIST" \
    CLAUDE_PII_FILENAME_PATTERNS="$SID_PAT" "$@" git commit -q -m t 2>"$TMP/err" >/dev/null)
  local rc=$?
  OUT="$(cat "$TMP/err")"
  (cd "$REPO" && git reset -q --hard "$SID_BASE" && git clean -qfd) >/dev/null 2>&1
  return $rc
}
if try_sid "todo/2026-01-01-karino-renraku.yaml" "id: x"; then
  ng "学生の姓を含む新しい path の commit が通ってしまった"
else
  case "$OUT" in *"check-student-identifiers: BLOCK"*) ok "学生の姓を含む新しい path を pre-commit-bib が止める (engine の BLOCK 見出しつき)";; *) ng "止まったが engine の見出しが無い (別の gate?): $(printf '%s' "$OUT" | head -3)";; esac
  case "$OUT" in *karino*) ng "BLOCK の出力に値が素のまま出ている";; *) ok "BLOCK の出力は値を伏せる";; esac
fi
if try_sid "notes.md" "連絡: 仮野 名子 ($SID_ID)"; then
  ng "氏名と学籍番号を足した行の commit が通ってしまった"
else
  case "$OUT" in *"check-student-identifiers: BLOCK"*"notes.md:1"*) ok "平文 file の足した行の氏名と学籍番号を止める";; *) ng "止まったが engine の見出しか行が無い: $(printf '%s' "$OUT" | head -3)";; esac
fi
if try_sid "todo/2026-01-01-renraku.yaml" "id: x"; then ok "識別子を含まない path と本文の commit は通る"; else ng "識別子の無い commit が止まった: $(printf '%s' "$OUT" | head -3)"; fi
if try_sid "todo/2026-01-01-karino-renraku.yaml" "id: x" CLAUDE_STUDENT_ID_GUARD=0; then ok "escape hatch (CLAUDE_STUDENT_ID_GUARD=0) で通る = 止めたのはこの gate"; else ng "escape hatch でも止まる: $(printf '%s' "$OUT" | head -3)"; fi
if try_sid "todo/2026-01-01-karino-renraku.yaml" "id: x" CLAUDE_STUDENT_IDENTITY="$TMP/none.json" CLAUDE_PII_FILENAME_PATTERNS="$TMP/none.txt"; then
  ok "一覧も形の設定も無い機械では何もしない (他の user と同じ)"
else
  ng "設定の無い機械で止まった: $(printf '%s' "$OUT" | head -3)"
fi
printf '{broken' > "$TMP/bad-identity.json"
if try_sid "todo/2026-01-01-karino-renraku.yaml" "id: x" CLAUDE_STUDENT_IDENTITY="$TMP/bad-identity.json"; then
  case "$OUT" in *"check-student-identifiers: 検査が走っていない"*) ok "壊れた一覧 (exit 3 + 見出し) では止めず、 見出しの 1 行が出る";; *) ng "壊れた一覧で commit は通ったが見出しが出ない";; esac
else
  ng "壊れた一覧で commit が止まった (故障を違反と読んだ): $(printf '%s' "$OUT" | head -3)"
fi
# 偽の scripts dir = hook は写し、 他は本物への symlink、 この engine だけ見出しなしの rc 1 で落ちる stub
SID_FAKE="$TMP/fake-scripts-sid"; mkdir -p "$SID_FAKE"
for f in "$HERE"/*; do ln -s "$f" "$SID_FAKE/$(basename "$f")"; done
rm -f "$SID_FAKE/pre-commit-bib" "$SID_FAKE/check-student-identifiers.py"
cp "$HOOK" "$SID_FAKE/pre-commit-bib"
printf 'import sys\nsys.exit(1)\n' > "$SID_FAKE/check-student-identifiers.py"
ln -sf "$SID_FAKE/pre-commit-bib" "$REPO/.git/hooks/pre-commit"
if try_sid "todo/2026-01-01-karino-renraku.yaml" "id: x"; then
  case "$OUT" in *"学生の識別子の検査が異常終了"*) ok "engine が見出しなしで落ちても commit は通り、 1 行出る";; *) ng "engine の故障で commit は通ったが 1 行が出ない";; esac
else
  ng "engine の故障で commit が止まった: $(printf '%s' "$OUT" | head -3)"
fi
ln -sf "$HOOK" "$REPO/.git/hooks/pre-commit"

# pathspec commit (git commit -- <path>) で fixer が直す .bib: 作業木だけを直して止め、 打ち直しで通る = main の index に
# 修正前の版が残らない (latex.md#autofix-with-pathspec-commit)。 普通の commit (git add の後) は従来どおり直して re-stage して通る。
BREPO="$TMP/brepo"; mkdir -p "$BREPO"
(
  cd "$BREPO" && git init -q -b main && git config user.email t@example.invalid && git config user.name t \
  && ln -sf "$HOOK" .git/hooks/pre-commit \
  && printf '@article{K,\n  title = "{a--b}",\n}\n' > x.bib && git add x.bib && HOME="$FAKE_HOME" git commit -q -m init
) >/dev/null 2>&1 || { echo "FAIL: bib の一時 repo の初期化"; exit 1; }
printf '@article{K,\n  title = "{a–b}",\n  note = "{n1}",\n}\n' > "$BREPO/x.bib"
if (cd "$BREPO" && HOME="$FAKE_HOME" git commit -q -m p -- x.bib 2>"$TMP/err" >/dev/null); then
  ng "pathspec commit が直したうえで通った (main の index に修正前の版が残る形)"
else
  if grep -q 'pathspec commit' "$TMP/err" && grep -q 'a--b' "$BREPO/x.bib" && (cd "$BREPO" && git diff --cached --quiet); then
    ok "pathspec commit: 作業木を直して止める (main の index は HEAD のまま)"
  else
    ng "pathspec commit の止まり方が違う: $(head -3 "$TMP/err")"
  fi
  if (cd "$BREPO" && HOME="$FAKE_HOME" git commit -q -m p -- x.bib 2>"$TMP/err" >/dev/null) \
     && (cd "$BREPO" && git diff --cached --quiet && git diff --quiet); then
    ok "打ち直しで通り、 index・作業木・HEAD が揃う"
  else
    ng "打ち直しが通らない / index が揃わない: $(head -3 "$TMP/err")"
  fi
fi
printf '@article{K,\n  title = "{a–b}",\n  note = "{n2}",\n}\n' > "$BREPO/x.bib"
if (cd "$BREPO" && git add x.bib && HOME="$FAKE_HOME" git commit -q -m q 2>"$TMP/err" >/dev/null) \
   && (cd "$BREPO" && git diff --cached --quiet) && git -C "$BREPO" show HEAD:x.bib | grep -q 'a--b'; then
  ok "普通の commit は従来どおり直して re-stage して通る"
else
  ng "普通の commit の自動修正が変わった: $(head -3 "$TMP/err")"
fi
echo "pre-commit-bib.test: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
