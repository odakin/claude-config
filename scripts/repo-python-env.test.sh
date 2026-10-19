#!/usr/bin/env bash
# repo-python-env.test.sh — repo の Python の入口 (templates/shared-project/python-env/py = 各 repo の tools/py) の検査。 偽の interpreter と偽の uv で、 venv を作る・追従させる・版が無ければ止まる・作り直しの失敗で元に戻す・機械の arch (arm64 / Intel / 見ない) に合わない候補を起動しない・lock・Windows (Git Bash) と Linux (WSL・Debian・musl) を REPO_PY_OS で模した挙動を確かめる
#
# 規約 = conventions/python-env.md (環境ごとの表 = #python-env-environments。 表の「確かめ方」 の列が本 file の番号を引く)。
# network は使わない。 最後の 1 件だけ実機の python3 で本物の venv を作る (python3 が無い機では飛ばす)。 bash 3.2 (macOS の
# /bin/bash) でも回る。 Windows・Linux は OS (uname) と、 その OS の python の振る舞い (Scripts/python.exe・CRLF・Store の
# alias・ensurepip の無い python) を模しただけで、 その OS の実機では走らせていない。
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../templates/shared-project/python-env/py"
PASS=0; FAIL=0
ok() { PASS=$((PASS+1)); echo "  PASS: $1"; }
ng() { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
LOG="$TMP/log"; : > "$LOG"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1

# 偽の python: 版を答える / -m venv で自分の写しを venv に置く / -m pip install -r を記録する
# (requirements に "fail-on-<major.minor>" があればその版では失敗) / -m pip freeze は venv の freeze.txt / それ以外は RAN を出す
# arch = arm64 (既定) / x86_64 / universal / win (Windows の python = 出力が CRLF・venv が Scripts/python.exe・machine が AMD64)。
# 4 つめに novenv = venv の部品 (ensurepip) の無い python (Debian・Ubuntu で python3.X-venv を入れていない状態)
mkpy() {  # mkpy <path> <version> [<arch>] [novenv]
  mkdir -p "$(dirname "$1")"
  cat > "$1" <<EOF
#!/bin/bash
V="$2"; A="${3:-arm64}"; NOVENV="${4:-}"; LOG="$LOG"
MM="\${V%.*}"
me="\$0"
NL='\n'; [ "\$A" = win ] && NL='\r\n'
echo "exec \$me" >> "\$LOG"; echo "run-arch \$A" >> "\$LOG"
if [ "\${1:-}" = -c ]; then
  M="\$A"; [ "\$A" = universal ] && M="\${REPO_PY_NATIVE_ARCH:-arm64}"; [ "\$A" = win ] && M=AMD64
  case "\$2" in
    *platform*) printf "%s %s\$NL" "\$V" "\$M"; exit 0 ;;
    *sys.executable*) printf "%s\$NL" "\$me"; exit 0 ;;
    *version_info*) echo "\$V"; exit 0 ;;
  esac
  echo "C \$V \$2"; exit 0
fi
if [ "\${1:-}" = -m ] && [ "\${2:-}" = venv ]; then
  if [ -n "\$NOVENV" ]; then echo "Error: The virtual environment was not created successfully because ensurepip is not available." >&2; exit 1; fi
  d="\$3"; b=bin; py=python; [ "\$A" = win ] && { b=Scripts; py=python.exe; }
  mkdir -p "\$d/\$b"; cp "\$me" "\$d/\$b/\$py"; chmod +x "\$d/\$b/\$py"
  echo "home = \$(dirname "\$me")" > "\$d/pyvenv.cfg"
  echo "venv \$V" >> "\$LOG"; exit 0
fi
if [ "\${1:-}" = -m ] && [ "\${2:-}" = pip ]; then
  vdir="\$(cd "\$(dirname "\$me")/.." && pwd)"
  case "\${3:-}" in
    install)
      req=""; while [ \$# -gt 0 ]; do [ "\$1" = -r ] && req="\$2"; shift; done
      echo "pip \$V" >> "\$LOG"
      grep -q "fail-on-\$MM" "\$req" && { echo "ERROR: Could not find a version that satisfies the requirement x==1 (stub)" >&2; exit 1; }
      grep -vE '^[[:space:]]*(#|\$)' "\$req" >> "\$vdir/freeze.txt"; exit 0 ;;
    freeze) cat "\$vdir/freeze.txt" 2>/dev/null; exit 0 ;;
  esac
  exit 0
fi
echo "RAN \$V \$*"
EOF
  chmod +x "$1"
}

# 偽の uv: python find / python install (pending/ から store/ へ移す) / venv --seed --python B DIR / pip install --python P -r R
# 偽の file: 偽の python の arch の印 (A=) を Mach-O の arch として答える。 印の無い file は script と答える
cat > "$TMP/fakefile" <<'EOF'
#!/bin/bash
for f; do :; done
if grep -q '^V=.*A="x86_64"' "$f" 2>/dev/null; then echo "Mach-O 64-bit executable x86_64"
elif grep -q '^V=.*A="universal"' "$f" 2>/dev/null; then echo "Mach-O universal binary with 2 architectures: [x86_64:Mach-O 64-bit executable x86_64] [arm64]"
elif grep -q '^V=.*A="arm64"' "$f" 2>/dev/null; then echo "Mach-O 64-bit executable arm64"
else echo "Bourne-Again shell script text executable, ASCII text"; fi
EOF
chmod +x "$TMP/fakefile"

UVSTORE="$TMP/uvstore"; mkdir -p "$UVSTORE/pending"
cat > "$TMP/uv" <<EOF
#!/bin/bash
LOG="$LOG"; S="$UVSTORE"
case "\$1 \$2" in
  "python find") [ -x "\$S/python\$3" ] && { echo "\$S/python\$3"; exit 0; }; exit 1 ;;
  "python install") [ -e "\$S/pending/python\$3" ] || exit 1; mv "\$S/pending/python\$3" "\$S/python\$3"; echo "uv-install \$3" >> "\$LOG"; exit 0 ;;
esac
if [ "\$1" = venv ]; then
  b=""; d=""; shift; while [ \$# -gt 0 ]; do case "\$1" in --python) b="\$2"; shift ;; --seed) ;; *) d="\$1" ;; esac; shift; done
  echo "uv-venv" >> "\$LOG"; exec "\$b" -m venv "\$d"
fi
if [ "\$1 \$2" = "pip install" ]; then
  p=""; r=""; shift 2; while [ \$# -gt 0 ]; do case "\$1" in --python) p="\$2"; shift ;; -r) r="\$2"; shift ;; esac; shift; done
  echo "uv-pip" >> "\$LOG"; exec "\$p" -m pip install -r "\$r"
fi
exit 2
EOF
chmod +x "$TMP/uv"

mkpy "$TMP/py/3.9/python3.9" 3.9.6
mkpy "$TMP/py/3.13/python3.13" 3.13.5
mkpy "$TMP/py/3.14/python3.14" 3.14.1
mkpy "$TMP/py/3.15/python3.15" 3.15.0

newrepo() {  # newrepo <name> → $R に git repo + tools/py の写し
  R="$TMP/$1"; mkdir -p "$R/tools"; git init -q "$R"; cp "$SRC" "$R/tools/py"; chmod +x "$R/tools/py"
}
count() { grep -c "^$1" "$LOG"; }
P9="$TMP/py/3.9/python3.9"; P13="$TMP/py/3.13/python3.13"; P14="$TMP/py/3.14/python3.14"; P15="$TMP/py/3.15/python3.15"
export REPO_PY_UV=none REPO_PY_NATIVE_ARCH=arm64 REPO_PY_FILE_CMD="$TMP/fakefile"

# 1. 宣言が無い
newrepo r1
out="$("$R/tools/py" -c 1 2>&1)"; rc=$?
[ $rc -eq 3 ] && printf '%s' "$out" | grep -q "宣言が無い" && ok "R1 宣言 (.python-version) が無ければ exit 3 で理由を言う" || ng "R1 rc=$rc out=$out"
out="$("$R/tools/py" --venv-check 2>/dev/null)"; rc=$?
[ $rc -eq 1 ] && printf '%s' "$out" | grep -q "❌" && ok "R2 --venv-check は宣言が無いと ❌ で 1" || ng "R2 rc=$rc out=$out"

# 2. 宣言の版も新しい版も無い = 止まって入れ方を言う、 venv を作らない
newrepo r2; echo 3.13 > "$R/.python-version"; echo "numpy==9.9" > "$R/requirements.txt"
out="$(REPO_PY_SEARCH="$P9" "$R/tools/py" x.py 2>&1)"; rc=$?
[ $rc -eq 3 ] && printf '%s' "$out" | grep -q "Python 3.13" && printf '%s' "$out" | grep -q "3.9.6" \
  && printf '%s' "$out" | grep -q "tools/py --venv-ensure" && [ ! -e "$R/.venv" ] \
  && ok "R3 合う Python が無ければ見つかった版と入れ方を出して exit 3、 venv は作らない (黙って 3.9 で作らない)" || ng "R3 rc=$rc out=$out"
out="$(REPO_PY_SEARCH="$P9" "$R/tools/py" --venv-check 2>/dev/null)"; rc=$?
[ $rc -eq 1 ] && printf '%s' "$out" | grep -q "^❌ Python: venv が無く" && ok "R4 --venv-check は人の手が要るとき ❌ を 1 行" || ng "R4 rc=$rc out=$out"

# 3. 同じ minor があれば作って実行、 2 回目は作らない
out="$(REPO_PY_SEARCH="$P9:$P14:$P13" "$R/tools/py" --venv-check 2>&1)"; rc=$?
[ $rc -eq 0 ] && [ -z "$out" ] && ok "R5 --venv-check は自動で作れる状態なら黙って 0" || ng "R5 rc=$rc out=$out"
v0=$(count venv)
out="$(REPO_PY_SEARCH="$P9:$P14:$P13" "$R/tools/py" a.py arg 2>/dev/null)"; rc=$?
[ $rc -eq 0 ] && [ "$out" = "RAN 3.13.5 a.py arg" ] && [ -f "$R/.venv/.tools-py-stamp" ] \
  && ok "R6 新しい版 (3.14) より宣言と同じ 3.13 を選んで venv を作り、 引数をそのまま渡す" || ng "R6 rc=$rc out=$out"
v1=$(count venv); p1=$(count pip)
out="$(REPO_PY_SEARCH="$P9:$P14:$P13" "$R/tools/py" b.py 2>&1)"
[ "$out" = "RAN 3.13.5 b.py" ] && [ "$(count venv)" = "$v1" ] && [ "$(count pip)" = "$p1" ] && [ $((v1 - v0)) = 1 ] \
  && ok "R7 2 回目は作らず追従もしない (速い道、 stderr も黙る)" || ng "R7 out=$out venv=$v0/$v1/$(count venv)"

# 4. requirements が変われば pip install だけ (作り直さない)
echo "scipy==9.9" >> "$R/requirements.txt"
out="$(REPO_PY_SEARCH="$P13" "$R/tools/py" c.py 2>&1)"
[ "$(count venv)" = "$v1" ] && [ "$(count pip)" = $((p1 + 1)) ] && printf '%s' "$out" | grep -q "requirements が前回から変わった" \
  && printf '%s' "$out" | grep -q "RAN 3.13.5 c.py" && ok "R8 requirements が変われば venv を作り直さず pip install で追従" || ng "R8 out=$out"

# 5. 新しい minor だけある = 宣言に近い方を告知して使う / REPO_PY_EXACT=1 なら止まる
newrepo r5; echo 3.13 > "$R/.python-version"; echo "numpy==9.9" > "$R/requirements.txt"
out="$(REPO_PY_EXACT=1 REPO_PY_SEARCH="$P15:$P14" "$R/tools/py" x.py 2>&1)"; rc=$?
[ $rc -eq 3 ] && [ ! -e "$R/.venv" ] && ok "R9 REPO_PY_EXACT=1 なら新しい minor に逃げず止まる" || ng "R9 rc=$rc out=$out"
out="$(REPO_PY_SEARCH="$P15:$P14" "$R/tools/py" x.py 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q "より新しい 3.14.1" && printf '%s' "$out" | grep -q "RAN 3.14.1 x.py" \
  && ok "R10 同じ minor が無ければ宣言に最も近い新しい minor (3.15 でなく 3.14) を 1 行告知して使う" || ng "R10 rc=$rc out=$out"

# 6. 新しい版で依存が入らない = 作りかけを消して止まる。 前の venv があれば元に戻す
newrepo r6; echo 3.13 > "$R/.python-version"; printf 'numpy==9.9\n# fail-on-3.14\n' > "$R/requirements.txt"
printf 'numpy==9.9\nfail-on-3.14\n' > "$R/requirements.txt"
out="$(REPO_PY_SEARCH="$P14" "$R/tools/py" x.py 2>&1)"; rc=$?
[ $rc -eq 3 ] && [ ! -e "$R/.venv" ] && printf '%s' "$out" | grep -q "版を外して入れずに" \
  && ok "R11 依存が入らなければ作りかけの venv を消して exit 3 (版を外せとは言わない)" || ng "R11 rc=$rc out=$out"
"$P9" -m venv "$R/.venv"; echo "oldextra==1.0" > "$R/.venv/freeze.txt"
out="$(REPO_PY_SEARCH="$P14" "$R/tools/py" x.py 2>&1)"; rc=$?
[ $rc -eq 3 ] && [ "$("$R/.venv/bin/python" -c version_info)" = 3.9.6 ] && [ ! -e "$R/.git/tools-py-prev-venv" ] \
  && ok "R12 作り直しが失敗したら前の venv (3.9) を元の場所に戻す" || ng "R12 rc=$rc out=$out"

# 7. 古い版の venv は作り直す。 前の venv にだけあった package の名前を言う
printf 'numpy==9.9\n' > "$R/requirements.txt"
out="$(REPO_PY_SEARCH="$P13" "$R/tools/py" y.py 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q "3.9.6 で作られていて" && printf '%s' "$out" | grep -q "前の venv にあって今は無い package: oldextra" \
  && printf '%s' "$out" | grep -q "RAN 3.13.5 y.py" && ok "R13 宣言より古い venv は作り直し、 手で入れた package の名前を 1 行出す" || ng "R13 rc=$rc out=$out"

# 8. 合わない venv を明示で使う = 毎回 ⚠️、 何も直さない。 点検は ⚠️ で 1
newrepo r8; echo 3.13 > "$R/.python-version"; echo "numpy==9.9" > "$R/requirements.txt"
"$P9" -m venv "$R/.venv"; v8=$(count venv)
out="$(REPO_PY_ACCEPT_VENV=1 REPO_PY_SEARCH="$P9" "$R/tools/py" z.py 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q "⚠️" && printf '%s' "$out" | grep -q "RAN 3.9.6 z.py" && [ "$(count venv)" = "$v8" ] \
  && ok "R14 REPO_PY_ACCEPT_VENV=1 は合わない venv を直さずに使い、 毎回 ⚠️ を出す" || ng "R14 rc=$rc out=$out"
out="$(REPO_PY_ACCEPT_VENV=1 REPO_PY_SEARCH="$P9" "$R/tools/py" --venv-check 2>/dev/null)"; rc=$?
[ $rc -eq 1 ] && printf '%s' "$out" | grep -q "^⚠️" && ok "R15 --venv-check は宣言外の venv を使っている間 ⚠️ で 1 (session ごとに出る)" || ng "R15 rc=$rc out=$out"
out="$(REPO_PY_SEARCH="$P9" "$R/tools/py" --venv-check 2>/dev/null)"; rc=$?
[ $rc -eq 1 ] && printf '%s' "$out" | grep -q "3.9.6 で作られていて宣言より古く" && ok "R16 古い venv しか無く作り直せないときの ❌" || ng "R16 rc=$rc out=$out"

# 9. REPO_PYTHON が宣言を満たさなければ止まる (黙って別の候補に逃げない)
out="$(REPO_PYTHON="$P9" REPO_PY_SEARCH="$P13" "$R/tools/py" --venv-rebuild 2>&1)"; rc=$?
[ $rc -eq 3 ] && printf '%s' "$out" | grep -q "満たさない" && ok "R17 REPO_PYTHON が宣言より古ければ exit 3" || ng "R17 rc=$rc out=$out"

# 10. uv: 宣言の版が無ければ uv が入れ、 uv で venv を作る
newrepo r10; echo 3.13 > "$R/.python-version"; echo "numpy==9.9" > "$R/requirements.txt"
mkpy "$UVSTORE/pending/python3.13" 3.13.9
out="$(REPO_PY_UV="$TMP/uv" REPO_PY_SEARCH="$P9:$P14" "$R/tools/py" --venv-check 2>&1)"; rc=$?
[ $rc -eq 0 ] && ok "R18 uv があれば --venv-check は 0 (初回の実行で取ってくる)" || ng "R18 rc=$rc out=$out"
out="$(REPO_PY_UV="$TMP/uv" REPO_PY_SEARCH="$P9:$P14" "$R/tools/py" u.py 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q "RAN 3.13.9 u.py" && grep -q "uv-install 3.13" "$LOG" && grep -q "uv-venv" "$LOG" && grep -q "uv-pip" "$LOG" \
  && ok "R19 宣言の版が無く uv があれば、 新しい 3.14 より先に uv で 3.13 を入れて venv を作る" || ng "R19 rc=$rc out=$out"

# 11. 壊れた venv (python が起動しない) は作り直す / --venv-path
newrepo r11; echo 3.13 > "$R/.python-version"
mkdir -p "$R/.venv/bin"; printf '#!/bin/sh\nexit 126\n' > "$R/.venv/bin/python"; chmod +x "$R/.venv/bin/python"
out="$(REPO_PY_SEARCH="$P13" "$R/tools/py" --venv-path 2>/dev/null)"; rc=$?
[ $rc -eq 0 ] && [ "$out" = "$(cd "$R" && pwd -P)/.venv/bin/python" ] && [ "$("$R/.venv/bin/python" -c version_info)" = 3.13.5 ] \
  && ok "R20 起動しない venv は作り直す (requirements が無くても作る) + --venv-path が path を出す" || ng "R20 rc=$rc out=$out"

# 12. lock: 死んだ process の lock は取り上げる
newrepo r12; echo 3.13 > "$R/.python-version"
mkdir -p "$R/.git/tools-py.lock"; echo 999999 > "$R/.git/tools-py.lock/pid"
out="$(REPO_PY_SEARCH="$P13" "$R/tools/py" l.py 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q "RAN 3.13.5 l.py" && [ ! -e "$R/.git/tools-py.lock" ] \
  && ok "R21 居ない process の lock は取り上げて進め、 終われば lock を消す" || ng "R21 rc=$rc out=$out"

# 13. git でない dir (再現用の束など) でも、 tools/ の 1 つ上を root にする
B="$TMP/bundle"; mkdir -p "$B/tools"; cp "$SRC" "$B/tools/py"; echo 3.13 > "$B/.python-version"
out="$(REPO_PY_SEARCH="$P13" "$B/tools/py" k.py 2>/dev/null)"; rc=$?
[ $rc -eq 0 ] && [ "$out" = "RAN 3.13.5 k.py" ] && [ -d "$B/.venv" ] && ok "R22 git でない dir でも動く (venv = tools の 1 つ上)" || ng "R22 rc=$rc out=$out"

# 14. 宣言が変わり、 venv がまだ満たすなら作り直さず印だけ更新 / 満たさなくなれば作り直す
R="$TMP/r2"; vb=$(count venv)
echo 3.12 > "$R/.python-version"
out="$(REPO_PY_SEARCH="$P13" "$R/tools/py" d.py 2>&1)"
[ "$(count venv)" = "$vb" ] && printf '%s' "$out" | grep -q "RAN 3.13.5 d.py" && grep -q "^declared=3.12" "$R/.venv/.tools-py-stamp" \
  && ok "R23 宣言を下げても venv (3.13) が満たすなら作り直さない" || ng "R23 out=$out"
echo 3.14 > "$R/.python-version"
out="$(REPO_PY_SEARCH="$P13:$P14" "$R/tools/py" e.py 2>&1)"
[ "$(count venv)" = $((vb + 1)) ] && printf '%s' "$out" | grep -q "RAN 3.14.1 e.py" && ok "R24 宣言を上げて venv が古くなれば作り直す" || ng "R24 out=$out"

# 15. 機械の arch × 候補の arch。 arm64 の機械 (Apple Silicon、 Rosetta の有無に依らない) / Intel の機械 / arch を見ない機械 を
#     REPO_PY_NATIVE_ARCH で模す。 候補 = arm64 だけ・x86_64 だけ・universal2。 合わない候補は起動しない
#     (= 起動した印 "exec <path>" が log に無い。 起動すると Apple Silicon では Rosetta の通知、 Rosetta が無ければ Bad CPU type)
A64="$TMP/m/arm/python3.13"; X86="$TMP/m/x86/python3.13"; UNI="$TMP/m/uni/python3.13"
mkpy "$A64" 3.13.5 arm64; mkpy "$X86" 3.13.6 x86_64; mkpy "$UNI" 3.13.7 universal
not_run() { ! grep -qxF "exec $1" "$LOG"; }
mrun() {  # mrun <machine arch> <search> <args...> → out / rc (log は毎回空にして、 起動した印を見る)
  local arch="$1" search="$2"; shift 2
  : > "$LOG"; rm -rf "$R/.venv"
  out="$(REPO_PY_NATIVE_ARCH="$arch" REPO_PY_SEARCH="$search" "$R/tools/py" "$@" 2>&1)"; rc=$?
}
newrepo r27; echo 3.13 > "$R/.python-version"
# arm64 の機械
mrun arm64 "$X86:$A64" m.py
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q "RAN 3.13.5 m.py" && not_run "$X86" \
  && ok "R27 arm64 の機械: x86_64 だけの候補は起動せず、 arm64 の候補を使う" || ng "R27 rc=$rc out=$out"
mrun arm64 "$X86:$UNI" m.py
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q "RAN 3.13.7 m.py" && not_run "$X86" \
  && ok "R28 arm64 の機械: universal2 は arm64 を含むので使う (x86_64 だけの候補は起動しない)" || ng "R28 rc=$rc out=$out"
mrun arm64 "$X86" --venv-check
[ $rc -eq 1 ] && printf '%s' "$out" | grep -q "x86_64 版 = 使わない、 起動していない" && printf '%s' "$out" | grep -q "arm64 版を入れる" \
  && not_run "$X86" && ok "R29 arm64 の機械に x86_64 版しか無い: 起動せずに ❌、「arm64 版を入れる」 と言う" || ng "R29 rc=$rc out=$out"
if [ "$(uname -s)" = Darwin ] && command -v brew >/dev/null 2>&1; then
  printf '%s' "$out" | grep -q "/opt/homebrew/bin/brew install" && ok "R30 arm64 の機械の入れ方の案内は /opt/homebrew" || ng "R30 out=$out"
else
  ok "R30 brew の無い機では飛ばす"
fi
# Intel の機械
mrun x86_64 "$A64:$X86" m.py
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q "RAN 3.13.6 m.py" && not_run "$A64" \
  && ok "R31 Intel の機械: x86_64 版は本来の版なので使い、 arm64 だけの候補は起動しない" || ng "R31 rc=$rc out=$out"
mrun x86_64 "$A64:$UNI" m.py
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q "RAN 3.13.7 m.py" && not_run "$A64" \
  && ok "R32 Intel の機械: universal2 は x86_64 を含むので使う" || ng "R32 rc=$rc out=$out"
mrun x86_64 "$A64" --venv-check
[ $rc -eq 1 ] && printf '%s' "$out" | grep -q "arm64 版 = 使わない、 起動していない" && printf '%s' "$out" | grep -q "x86_64 版を入れる" \
  && not_run "$A64" && ok "R33 Intel の機械に arm64 版しか無い: 起動せずに ❌、「x86_64 版を入れる」 と言う" || ng "R33 rc=$rc out=$out"
if [ "$(uname -s)" = Darwin ] && command -v brew >/dev/null 2>&1; then
  printf '%s' "$out" | grep -q "/usr/local/bin/brew install" && ok "R34 Intel の機械の入れ方の案内は /usr/local" || ng "R34 out=$out"
else
  ok "R34 brew の無い機では飛ばす"
fi
# arch を見ない機械 (macOS 以外)
mrun any "$X86" m.py
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q "RAN 3.13.6 m.py" && ok "R35 arch を見ない機械: x86_64 の候補もそのまま使う" || ng "R35 rc=$rc out=$out"
mrun any "$A64" m.py
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q "RAN 3.13.5 m.py" && ok "R36 arch を見ない機械: arm64 の候補もそのまま使う" || ng "R36 rc=$rc out=$out"
# 合わない arch で作られた venv は、 venv の python を起動せずに作り直す
newrepo r37; echo 3.13 > "$R/.python-version"; "$X86" -m venv "$R/.venv"; : > "$LOG"
out="$(REPO_PY_SEARCH="$A64" "$R/tools/py" j.py 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q "x86_64 版の python (起動していない) で作られていて" && printf '%s' "$out" | grep -q "RAN 3.13.5 j.py" \
  && ! grep -qx "run-arch x86_64" "$LOG" \
  && ok "R37 arm64 の機械で x86_64 版の python で作られた venv は、 起動せずに理由を言って作り直す" || ng "R37 rc=$rc out=$out"
# REPO_PYTHON に合わない arch を指しても起動しない
: > "$LOG"
out="$(REPO_PYTHON="$X86" "$R/tools/py" --venv-rebuild 2>&1)"; rc=$?
[ $rc -eq 3 ] && printf '%s' "$out" | grep -q "x86_64 版で、 この機械 (arm64) では使わない" && not_run "$X86" \
  && ok "R38 REPO_PYTHON が合わない arch なら起動せずに exit 3" || ng "R38 rc=$rc out=$out"
# 組み込みの探し場所の script (pyenv の shim など、 中身の arch が分からない) は起動しない
SHIMDIR="$TMP/shims"; mkdir -p "$SHIMDIR"; printf '#!/bin/bash\necho "exec %s/python3.13" >> "%s"\necho 3.13.1\n' "$SHIMDIR" "$LOG" > "$SHIMDIR/python3.13"; chmod +x "$SHIMDIR/python3.13"
newrepo r39; echo 3.13 > "$R/.python-version"; : > "$LOG"
out="$(PATH="$SHIMDIR:$PATH" REPO_PY_SEARCH= "$R/tools/py" --venv-check 2>/dev/null)"
not_run "$SHIMDIR/python3.13" && ok "R39 組み込みの探し場所では script の候補 (shim) を起動しない" || ng "R39 log=$(cat "$LOG")"

# 16. Windows (Git Bash) と Linux (WSL・Debian・musl・CI) を REPO_PY_OS で模す。 組み込みの探し場所を通す件は、 PATH を
#     最小の道具 (MINBIN) と偽の python の dir だけにし、 HOME も空の dir にして、 この機械の本物の python を起動しない
MINBIN="$TMP/minbin"; mkdir -p "$MINBIN"
for t in bash git dirname uname sed grep shasum sha256sum cksum cut head tr sort mkdir rm mv cat sleep cp chmod; do
  p="$(command -v "$t" 2>/dev/null)" && [ -n "$p" ] && ln -sf "$p" "$MINBIN/$t"
done
GITENV="GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1"
WIN_OS="MINGW64_NT-10.0-22631"
W13="$TMP/win/Python313/python.exe"; mkpy "$W13" 3.13.4 win
# Windows の Store の alias: 起動すると「Python」 とだけ出して成功で終わる (版を答えない)
mkdir -p "$TMP/WindowsApps"
for n in python python3; do
  printf '#!/bin/bash\necho "exec %s/%s" >> "%s"\necho Python\n' "$TMP/WindowsApps" "$n" "$LOG" > "$TMP/WindowsApps/$n"; chmod +x "$TMP/WindowsApps/$n"
done
# 偽の py launcher: py -3.13 だけを知っている (Windows の native の出力 = CRLF は python の側が出す)
mkdir -p "$TMP/winbin"
cat > "$TMP/winbin/py" <<EOF
#!/bin/bash
echo "exec-launcher \$*" >> "$LOG"
case "\$1" in
  -3.13) shift; exec "$W13" "\$@" ;;
  *) echo "No suitable Python runtime found" >&2; exit 103 ;;
esac
EOF
chmod +x "$TMP/winbin/py"

# Windows: venv は Scripts/python.exe、 python の出力の CRLF を落として版を読む
newrepo r42; echo 3.13 > "$R/.python-version"; echo "numpy==9.9" > "$R/requirements.txt"; : > "$LOG"
out="$(REPO_PY_OS="$WIN_OS" REPO_PY_NATIVE_ARCH= REPO_PY_SEARCH="$W13" "$R/tools/py" w.py 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q "RAN 3.13.4 w.py" && [ -x "$R/.venv/Scripts/python.exe" ] && [ ! -e "$R/.venv/bin" ] \
  && grep -qx "python=3.13.4" "$R/.venv/.tools-py-stamp" \
  && ok "R42 Windows: venv の python は Scripts/python.exe、 CRLF の出力から版を読み、 その venv で走る" || ng "R42 rc=$rc out=$out"
v42=$(count venv)
out="$(REPO_PY_OS="$WIN_OS" REPO_PY_NATIVE_ARCH= REPO_PY_SEARCH="$W13" "$R/tools/py" --venv-path 2>/dev/null)"; rc=$?
[ $rc -eq 0 ] && [ "$out" = "$(cd "$R" && pwd -P)/.venv/Scripts/python.exe" ] && [ "$(count venv)" = "$v42" ] \
  && ok "R43 Windows: 2 回目は作らず、 --venv-path は Scripts/python.exe を出す" || ng "R43 rc=$rc out=$out"
# Windows: py launcher (py -3.13) が知っている python を使う。 launcher の答えの path の CR を落とす
newrepo r44; echo 3.13 > "$R/.python-version"; : > "$LOG"
out="$(REPO_PY_OS="$WIN_OS" REPO_PY_NATIVE_ARCH= REPO_PY_SEARCH="$TMP/nowhere" REPO_PY_LAUNCHER="$TMP/winbin/py" "$R/tools/py" l.py 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q "RAN 3.13.4 l.py" && grep -q "^exec-launcher -3.13" "$LOG" \
  && ok "R44 Windows: py launcher の答え (CRLF つきの path) から宣言の版の python を使う" || ng "R44 rc=$rc out=$out log=$(cat "$LOG")"
# Windows の組み込みの探し場所: Store の alias (python・python3) は起動せず、 python.org の置き場所 (LOCALAPPDATA) の python を使う
WH="$TMP/winhome"; LAD="$WH/AppData/Local"; mkpy "$LAD/Programs/Python/Python313/python.exe" 3.13.2 win
newrepo r45; echo 3.13 > "$R/.python-version"; : > "$LOG"
out="$(env -i $GITENV HOME="$WH" PATH="$TMP/WindowsApps:$MINBIN" LOCALAPPDATA="$LAD" APPDATA="$WH/AppData/Roaming" \
  REPO_PY_OS="$WIN_OS" REPO_PY_UV=none REPO_PY_LAUNCHER=none "$MINBIN/bash" "$R/tools/py" s.py 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q "RAN 3.13.2 s.py" && not_run "$TMP/WindowsApps/python3" && not_run "$TMP/WindowsApps/python" \
  && ok "R45 Windows: Store の alias は起動せず、 python.org の置き場所 (LOCALAPPDATA\\Programs\\Python) の python を使う" || ng "R45 rc=$rc out=$out"
# Windows の組み込みの探し場所でも py launcher に聞く (REPO_PY_SEARCH を指さない普段の形)
newrepo r56; echo 3.13 > "$R/.python-version"; : > "$LOG"
out="$(env -i $GITENV HOME="$WH" PATH="$TMP/WindowsApps:$MINBIN" REPO_PY_OS="$WIN_OS" REPO_PY_UV=none REPO_PY_LAUNCHER="$TMP/winbin/py" \
  "$MINBIN/bash" "$R/tools/py" p.py 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q "RAN 3.13.4 p.py" && grep -q "^exec-launcher -3.13" "$LOG" && not_run "$TMP/WindowsApps/python3" \
  && ok "R56 Windows の組み込みの探し場所: py launcher が答える python を使う" || ng "R56 rc=$rc out=$out"
# Windows で合う python が無い: Store の alias は数えず、 winget の入れ方を言う
newrepo r46; echo 3.13 > "$R/.python-version"; : > "$LOG"
out="$(env -i $GITENV HOME="$WH" PATH="$TMP/WindowsApps:$MINBIN" REPO_PY_OS="$WIN_OS" REPO_PY_UV=none REPO_PY_LAUNCHER=none \
  "$MINBIN/bash" "$R/tools/py" --venv-check 2>/dev/null)"; rc=$?
[ $rc -eq 1 ] && printf '%s' "$out" | grep -q "winget install --id=astral-sh.uv" && printf '%s' "$out" | grep -q "winget install Python.Python.3.13" \
  && printf '%s' "$out" | grep -q "見つかった: なし" && not_run "$TMP/WindowsApps/python3" \
  && ok "R46 Windows で合う python が無い: Store の alias を数えず、 uv と python.org の winget の入れ方を言う" || ng "R46 rc=$rc out=$out"
# 版を答えない interpreter (明示で指した Store の alias) は使わず、 版の比較で落ちない
newrepo r55; echo 3.13 > "$R/.python-version"
out="$(REPO_PY_OS="$WIN_OS" REPO_PY_NATIVE_ARCH= REPO_PY_SEARCH="$TMP/WindowsApps/python3" "$R/tools/py" --venv-check 2>&1)"; rc=$?
[ $rc -eq 1 ] && printf '%s' "$out" | grep -q "見つかった: なし" && ! printf '%s' "$out" | grep -q "integer expression" \
  && ok "R55 版を答えない interpreter (「Python」 とだけ出す) は候補に数えない" || ng "R55 rc=$rc out=$out"
# Windows の checkout で .python-version が CRLF でも宣言を読む
newrepo r47; printf '3.13\r\n' > "$R/.python-version"
out="$(REPO_PY_OS="$WIN_OS" REPO_PY_NATIVE_ARCH= REPO_PY_SEARCH="$W13" "$R/tools/py" c.py 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q "RAN 3.13.4 c.py" && ok "R47 CRLF の .python-version を読む" || ng "R47 rc=$rc out=$out"

# WSL・Linux: 同じ checkout に Windows の python が作った venv (Scripts/python.exe) がある = 起動も削除もせずに止まる
newrepo r48; echo 3.13 > "$R/.python-version"; "$W13" -m venv "$R/.venv"; : > "$LOG"
out="$(REPO_PY_OS=Linux REPO_PY_NATIVE_ARCH= REPO_PY_SEARCH="$P13" "$R/tools/py" x.py 2>&1)"; rc=$?
[ $rc -eq 3 ] && printf '%s' "$out" | grep -q "Windows の python で作られている" && printf '%s' "$out" | grep -q "REPO_PY_VENV" \
  && [ -x "$R/.venv/Scripts/python.exe" ] && [ ! -e "$R/.venv/bin" ] && not_run "$R/.venv/Scripts/python.exe" \
  && ok "R48 WSL・Linux: Windows の venv は起動も作り直しもせず、 REPO_PY_VENV を言って止まる" || ng "R48 rc=$rc out=$out"
out="$(REPO_PY_OS=Linux REPO_PY_NATIVE_ARCH= REPO_PY_SEARCH="$P13" "$R/tools/py" --venv-check 2>/dev/null)"; rc=$?
[ $rc -eq 1 ] && printf '%s' "$out" | grep -q "^❌ Python: venv" && ok "R49 その状態の --venv-check は ❌ (人の手が要る)" || ng "R49 rc=$rc out=$out"
out="$(REPO_PY_OS=Linux REPO_PY_NATIVE_ARCH= REPO_PY_SEARCH="$P13" REPO_PY_VENV="$R/.venv-wsl" "$R/tools/py" x.py 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q "RAN 3.13.5 x.py" && [ -x "$R/.venv-wsl/bin/python" ] && [ -x "$R/.venv/Scripts/python.exe" ] \
  && ok "R50 REPO_PY_VENV で別の場所を指せば、 Windows の venv を残したまま Linux の venv を作る" || ng "R50 rc=$rc out=$out"

# Linux (Debian・Ubuntu): python に venv の部品 (ensurepip) が無い = venv の失敗として言い、 python3.X-venv を案内する
D13="$TMP/deb/python3.13"; mkpy "$D13" 3.13.3 arm64 novenv
mkdir -p "$TMP/aptbin" "$TMP/dnfbin"
printf '#!/bin/sh\nexit 0\n' > "$TMP/aptbin/apt-get"; printf '#!/bin/sh\nexit 0\n' > "$TMP/dnfbin/dnf"; chmod +x "$TMP/aptbin/apt-get" "$TMP/dnfbin/dnf"
newrepo r51; echo 3.13 > "$R/.python-version"; echo "numpy==9.9" > "$R/requirements.txt"
out="$(env -i $GITENV HOME="$TMP/linhome" PATH="$TMP/aptbin:$MINBIN" REPO_PY_OS=Linux REPO_PY_LIBC=glibc REPO_PY_UV=none REPO_PY_SEARCH="$D13" \
  "$MINBIN/bash" "$R/tools/py" x.py 2>&1)"; rc=$?
[ $rc -eq 3 ] && printf '%s' "$out" | grep -q -- "-m venv が失敗した" && printf '%s' "$out" | grep -q "sudo apt install python3.13-venv" \
  && ! printf '%s' "$out" | grep -q "固定した依存が" && [ ! -e "$R/.venv" ] \
  && ok "R51 Debian 系: venv の部品が無い python は「venv が作れない」 と言い、 python3.13-venv を案内する (依存の話にしない)" || ng "R51 rc=$rc out=$out"
# Linux (musl): 依存が入らないとき、 musllinux の wheel が無いことを足して言う。 glibc では言わない
newrepo r52; echo 3.13 > "$R/.python-version"; printf 'numpy==9.9\nfail-on-3.13\n' > "$R/requirements.txt"
out="$(REPO_PY_OS=Linux REPO_PY_NATIVE_ARCH= REPO_PY_LIBC=musl REPO_PY_SEARCH="$P13" "$R/tools/py" x.py 2>&1)"; rc=$?
out2="$(REPO_PY_OS=Linux REPO_PY_NATIVE_ARCH= REPO_PY_LIBC=glibc REPO_PY_SEARCH="$P13" "$R/tools/py" x.py 2>&1)"
[ $rc -eq 3 ] && printf '%s' "$out" | grep -q "musllinux の wheel" && ! printf '%s' "$out2" | grep -q "musl" && [ ! -e "$R/.venv" ] \
  && ok "R52 musl: 依存が入らなければ musllinux の wheel の話を足す (glibc では足さない)" || ng "R52 rc=$rc out=$out"
# Linux で合う python が無い: uv を先に、 package manager ごとの入れ方を言う
newrepo r53; echo 3.13 > "$R/.python-version"
out="$(env -i $GITENV HOME="$TMP/linhome" PATH="$TMP/aptbin:$MINBIN" REPO_PY_OS=Linux REPO_PY_LIBC=glibc REPO_PY_UV=none REPO_PY_SEARCH="$P9" \
  "$MINBIN/bash" "$R/tools/py" --venv-check 2>/dev/null)"; rc=$?
out2="$(env -i $GITENV HOME="$TMP/linhome" PATH="$TMP/dnfbin:$MINBIN" REPO_PY_OS=Linux REPO_PY_LIBC=glibc REPO_PY_UV=none REPO_PY_SEARCH="$P9" \
  "$MINBIN/bash" "$R/tools/py" --venv-check 2>/dev/null)"
# musl の文は UTF-8 の locale の bash 3.2 でも出す (変数の直後の全角文字を変数名に取り込まない = ${var} で書いてある)
B32="$MINBIN/bash"; [ -x /bin/bash ] && /bin/bash -c '[ "${BASH_VERSINFO[0]}" -lt 4 ]' && B32=/bin/bash
out3="$(env -i $GITENV HOME="$TMP/linhome" PATH="$MINBIN" LC_ALL=en_US.UTF-8 REPO_PY_OS=Linux REPO_PY_LIBC=musl REPO_PY_UV=none REPO_PY_SEARCH="$P9" \
  "$B32" "$R/tools/py" --venv-check 2>/dev/null)"
[ $rc -eq 1 ] && printf '%s' "$out" | grep -q "uv を入れる (https://docs.astral.sh/uv/" && printf '%s' "$out" | grep -q "sudo apt install python3.13 python3.13-venv" \
  && printf '%s' "$out2" | grep -q "sudo dnf install python3.13" && printf '%s' "$out3" | grep -q "musl (Alpine など)" \
  && ok "R53 Linux で合う python が無い: uv を先に、 apt (venv の package つき) / dnf / musl ごとに入れ方を言う" || ng "R53 rc=$rc out=$out / $out2 / $out3"
# Linux の組み込みの探し場所: PATH の python3.13 (CI の setup-python・Docker の python image と同じ形) を使う
LB="$TMP/linbin"; mkpy "$LB/python3.13" 3.13.8 x86_64; mkpy "$LB/python3" 3.12.1 x86_64
newrepo r54; echo 3.13 > "$R/.python-version"; : > "$LOG"
out="$(env -i $GITENV HOME="$TMP/linhome" PATH="$LB:$MINBIN" REPO_PY_OS=Linux REPO_PY_UV=none "$MINBIN/bash" "$R/tools/py" c.py 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q "RAN 3.13.8 c.py" && not_run "$LB/python3" \
  && ok "R54 Linux: PATH の python3.13 を使い (arch は見ない)、 汎用の python3 (3.12) は起動しない" || ng "R54 rc=$rc out=$out"

# 17. bash 3.2 (macOS の /bin/bash) でも同じに動く
if [ -x /bin/bash ] && /bin/bash -c '[ "${BASH_VERSINFO[0]}" -lt 4 ]'; then
  newrepo r15; echo 3.13 > "$R/.python-version"; echo "numpy==9.9" > "$R/requirements.txt"
  out="$(REPO_PY_SEARCH="$P9:$P13" /bin/bash "$R/tools/py" f.py 2>/dev/null)"; rc=$?
  [ $rc -eq 0 ] && [ "$out" = "RAN 3.13.5 f.py" ] && ok "R40 bash 3.2 で動く" || ng "R40 rc=$rc out=$out"
else
  ok "R40 bash 3.2 の無い機では飛ばす"
fi

# 18. 実機: 本物の python3 で本物の venv を作る (依存なし、 network なし)
real="$(python3 -c 'import sys; print(sys.executable)' 2>/dev/null)"
if [ -n "$real" ] && [ -x "$real" ]; then
  newrepo r16; "$real" -c 'import sys; print("%d.%d" % sys.version_info[:2])' > "$R/.python-version"
  out="$(REPO_PY_NATIVE_ARCH= REPO_PY_FILE_CMD=file REPO_PY_SEARCH="$real" "$R/tools/py" -c 'import sys; print(sys.prefix)' 2>/dev/null)"; rc=$?
  want="$(cd "$R" && pwd -P)/.venv"
  [ $rc -eq 0 ] && [ "$(cd "$out" 2>/dev/null && pwd -P)" = "$want" ] && ok "R41 実機の python3 ($real) で本物の venv を作り、 その中で走る" || ng "R41 rc=$rc out=$out want=$want"
else
  ok "R41 python3 の無い機では飛ばす"
fi

echo "repo-python-env.test.sh: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
