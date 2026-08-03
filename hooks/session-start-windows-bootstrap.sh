#!/usr/bin/env bash
# session-start-windows-bootstrap.sh — SessionStart hook (layer 1): Windows 環境の毎 session 自動自己修復
#
# 正本: ~/Claude/claude-config/hooks/session-start-windows-bootstrap.sh
# 配信: claude-config/setup.sh install_hooks (= ~/.claude/hooks/ へ symlink 〔Windows は copy〕 +
#       settings.json SessionStart に登録、 matcher なし)。 ⚠️ 新規追加 hook の settings.json
#       登録は post-merge では走らない = 各マシン 1 回 setup.sh 再実行が必要
#
# 動作 (= 非 block、 副作用系):
#   非 Windows (macOS / Linux) は uname 1 発で即 silent exit 0。 Windows (MSYS/MINGW/Cygwin)
#   では conventions/windows-msys.md の予防可能な地雷を session 冒頭に自己点検し、 壊れて
#   いれば自動修復する:
#     (1) git core.autocrlf != false → false に設定 (#autocrlf-corrupts-scripts。
#         opt-out = CLAUDE_WINBOOT_KEEP_AUTOCRLF=1)
#     (2) python3 が不在 / Store stub (= 実行せず「Python」 と印字するだけの偽物) → 実体
#         python.exe を探して同 dir に python3.exe shim を copy (#python3-missing-store-stub)。
#         python 再インストールで shim が消えても次 session で自動復活する (= 自己治癒)
#     (3) PYTHONUTF8 / PYTHONIOENCODING 未設定 → setx で User 環境変数に設定
#         (#console-encoding-cp932。 反映は新 process から)
#   全 step 冪等。 健全なら stamp (= shim path を記録) を置き、 以後は「stamp の指す file が
#   生きているか」 の filesystem check のみの fast path で即 exit (= subprocess 起動なし)。
#
# 出力経路:
#   stdout = 修復があった時のみ <system-reminder> で修復内容を inject (CLI path)
#   副作用 = 修復そのもの + ~/.claude/surface/windows-bootstrap.txt (= desktop は stdout が
#            dropped されるが副作用は走る、 hook-authoring.md#frontend-dependent-cowork)
#
# ⚠️ 2026-08-03 起草時点で Windows 実機未検証 (起草環境 = macOS、 logic は同名 .test.sh の
#    stub 環境で検証)。 scripts/bootstrap-windows.ps1 (= git 導入前の virgin 機用 1 行) の
#    sibling — あちらが「最初の 1 回」、 本 hook が「以後の毎 session 自己治癒」 を担う。
#
# 設計動機: 2026-08-03 Windows 11 onboarding RCA (= git gate 門前払い + windows-msys.md
#   全地雷の実測。 上流 FR = anthropics/claude-code#83539)。

set -u

# ---------- 0. OS gate (非 Windows は即退場。 CLAUDE_WINBOOT_FORCE_OS は test 用) ----------
OS_KIND="${CLAUDE_WINBOOT_FORCE_OS:-$(uname -s 2>/dev/null || echo unknown)}"
case "$OS_KIND" in
  MINGW*|MSYS*|CYGWIN*) ;;
  *) exit 0 ;;
esac

STAMP="$HOME/.claude/.windows-env-bootstrap.done"

# ---------- fast path: stamp の指す shim が生きていれば何もしない ----------
if [ -f "$STAMP" ]; then
  SHIM_PATH="$(cat "$STAMP" 2>/dev/null || true)"
  if [ -n "$SHIM_PATH" ] && [ -f "$SHIM_PATH" ]; then
    exit 0
  fi
  # shim が消えた (= python 再インストール等) → slow path へ落ちて再修復
fi

FIXES=""
note() { FIXES="${FIXES}  - $1
"; }

py3_ok() {
  # Store stub は実行せず「Python」 と印字するだけ → 実際に print(1) が通るかで判定。
  # hash -r: 同 process 内で shim を作った直後の再判定が古い解決先を掴まないように
  hash -r 2>/dev/null || true
  [ "$(python3 -c 'print(1)' 2>/dev/null)" = "1" ]
}

# ---------- 1. core.autocrlf ----------
if [ "${CLAUDE_WINBOOT_KEEP_AUTOCRLF:-}" != "1" ] && command -v git >/dev/null 2>&1; then
  cur="$(git config --global core.autocrlf 2>/dev/null || true)"
  if [ "$cur" != "false" ]; then
    if git config --global core.autocrlf false 2>/dev/null; then
      note "git core.autocrlf: '${cur:-unset}' -> false (= clone した shell script の CRLF 化を防止)"
    fi
  fi
fi

# ---------- 2. python3 shim ----------
if ! py3_ok; then
  CAND=""
  p="$(command -v python 2>/dev/null || true)"
  case "$p" in
    *WindowsApps*|"") ;;  # Store stub / 不在は候補にしない
    *) [ "$("$p" -c 'print(1)' 2>/dev/null)" = "1" ] && CAND="$p" ;;
  esac
  if [ -z "$CAND" ] && [ -n "${LOCALAPPDATA:-}" ]; then
    for p in "$LOCALAPPDATA"/Programs/Python/Python3*/python.exe; do
      [ -f "$p" ] || continue
      [ "$("$p" -c 'print(1)' 2>/dev/null)" = "1" ] && CAND="$p" && break
    done
  fi
  if [ -n "$CAND" ]; then
    dir="$(dirname "$CAND")"; base="$(basename "$CAND")"
    case "$base" in *.exe) shim="$dir/python3.exe" ;; *) shim="$dir/python3" ;; esac
    if cp "$CAND" "$shim" 2>/dev/null && py3_ok; then
      note "python3 shim を復活: $shim (= Store stub / python 再インストール消失対策)"
    else
      note "python3 が不在のまま (実体 $CAND から shim copy 失敗 = 書込権限?)。 手動で python3.exe として copy すること"
    fi
  else
    note "python 実体が見つからない — scripts/bootstrap-windows.ps1 で導入すること"
  fi
fi

# ---------- 3. UTF-8 env (cp932 対策) ----------
if command -v setx >/dev/null 2>&1; then
  if [ "${PYTHONUTF8:-}" != "1" ]; then
    setx PYTHONUTF8 1 >/dev/null 2>&1 && note "PYTHONUTF8=1 (User env、 新 process から反映)"
  fi
  if [ -z "${PYTHONIOENCODING:-}" ]; then
    setx PYTHONIOENCODING utf-8 >/dev/null 2>&1 && note "PYTHONIOENCODING=utf-8 (User env、 新 process から反映)"
  fi
fi

# ---------- 4. stamp (= 健全時のみ。 不健全なら毎 session 再試行) ----------
mkdir -p "$HOME/.claude" 2>/dev/null || true
if py3_ok; then
  printf '%s' "$(command -v python3 2>/dev/null || true)" > "$STAMP" 2>/dev/null || true
else
  rm -f "$STAMP" 2>/dev/null || true
fi

# ---------- 5. 報告 (修復があった時のみ) ----------
if [ -n "$FIXES" ]; then
  MSG="[windows-bootstrap] Windows 環境を自動修復した (詳細 = claude-config/conventions/windows-msys.md):
$FIXES"
  SURFACE_DIR="$HOME/.claude/surface"
  mkdir -p "$SURFACE_DIR" 2>/dev/null || true
  printf '%s\n' "$MSG" > "$SURFACE_DIR/windows-bootstrap.txt" 2>/dev/null || true
  printf '<system-reminder>\n%s</system-reminder>\n' "$MSG"
fi

exit 0
