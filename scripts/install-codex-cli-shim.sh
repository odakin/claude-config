#!/bin/sh
# install-codex-cli-shim.sh — ChatGPT アプリ同梱の Codex CLI を、 端末で `codex` と打って起動できるようにする (PATH 上の dir に小さな入口を置く。 冪等、 変えないときは無出力。 --selftest)
#
# なぜ: ChatGPT アプリは Codex の CLI を app の中 (Contents/Resources/codex-cli/CodexCLI.app/…) に同梱するだけで PATH に
#   置かない。 端末で `codex` が command not found になり、 /hooks の信頼のような CLI の操作を本人に頼めない (実測)。
#   app の更新で同梱の path が変わったこともある (conventions/codex-desktop-triage.md) ので、 入口は 1 つの path を焼かず、
#   起動のたびに候補を順に探す。 順は監査 (audit-codex-hook-runtime.py の discover_codex) と同じ = ① 動いている app の
#   実行系 (/hooks の信頼は版で hash が違いうるので、 app が使う版で付ける) ② app の同梱 (新 → 旧) ③ app が落とした実行系の新しいもの。
# 置き場: 既に在って PATH に載っている ~/.local/bin → ~/.npm-global/bin → ~/bin の最初の dir。 PATH のどこかに入口でない
#   codex (npm で入れたものなど) が在れば何もしない (置いた入口が残っていれば外す = 本物を隠さない)。 入口は 2 行目の印で見分ける。
# 止める: ~/.claude/codex-cli-shim.off を置く。 毎 session の自動適用 (個人層の config-bootstrap) から呼ぶ想定。
# 正本 = conventions/codex-desktop-triage.md#cli-on-path
set -u

MARK='# claude-config: codex-cli-shim'
HOME_DIR="${CODEX_SHIM_HOME:-$HOME}"
SEARCH_PATH="${CODEX_SHIM_PATH:-$PATH}"
APP_BINS="${CODEX_SHIM_APP_BINS:-/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex /Applications/ChatGPT.app/Contents/Resources/codex}"
PS_CMD="${CODEX_SHIM_PS_CMD:-ps -axo comm=}"
OFF="$HOME_DIR/.claude/codex-cli-shim.off"

shim_text() {
  printf '#!/bin/sh\n'
  printf '%s (claude-config の scripts/install-codex-cli-shim.sh が置いた入口。 ChatGPT アプリの Codex CLI を探して起動する)\n' "$MARK"
  printf 'p="$(%s 2>/dev/null | grep -m1 -E '"'"'[.]app/Contents/(MacOS|Resources)/codex$'"'"')"\n' "$PS_CMD"
  printf '[ -n "$p" ] && [ -x "$p" ] && exec "$p" "$@"\n'
  printf 'for c in %s; do\n' "$APP_BINS"
  printf '  [ -x "$c" ] && exec "$c" "$@"\n'
  printf 'done\n'
  printf 'for c in $(ls -d "$HOME"/.codex/packages/app-server-daemon/releases/*/CodexCLI.app/Contents/MacOS/codex 2>/dev/null | sort -r); do\n'
  printf '  [ -x "$c" ] && exec "$c" "$@"\n'
  printf 'done\n'
  printf 'echo "codex: ChatGPT アプリ同梱の Codex CLI が見つからない (ChatGPT アプリを入れるか更新する)" >&2\n'
  printf 'exit 127\n'
}

is_shim() { [ -f "$1" ] && sed -n 2p "$1" 2>/dev/null | grep -qF "$MARK"; }

app_present() {
  for c in $APP_BINS; do [ -x "$c" ] && return 0; done
  for c in "$HOME_DIR"/.codex/packages/app-server-daemon/releases/*/CodexCLI.app/Contents/MacOS/codex; do
    [ -x "$c" ] && return 0
  done
  return 1
}

install() {
  [ -e "$OFF" ] && return 0
  [ "${CODEX_SHIM_OS:-$(uname -s)}" = Darwin ] || return 0
  shim=""; foreign=""
  old_ifs="$IFS"; IFS=:
  for d in $SEARCH_PATH; do
    [ -n "$d" ] && [ -x "$d/codex" ] || continue
    if is_shim "$d/codex"; then [ -z "$shim" ] && shim="$d/codex"; else [ -z "$foreign" ] && foreign="$d/codex"; fi
  done
  IFS="$old_ifs"
  if [ -n "$foreign" ]; then
    if [ -n "$shim" ]; then
      rm -f "$shim" && echo "[ok] codex の入口 ($shim) を外した: PATH に本物の codex がある ($foreign)"
    fi
    return 0
  fi
  app_present || return 0
  if [ -n "$shim" ]; then
    target="$shim"
  else
    target=""
    for d in "$HOME_DIR/.local/bin" "$HOME_DIR/.npm-global/bin" "$HOME_DIR/bin"; do
      [ -d "$d" ] || continue
      case ":$SEARCH_PATH:" in *":$d:"*) target="$d/codex"; break ;; esac
    done
    if [ -z "$target" ]; then
      echo "⚠️ 端末で codex と打てない: 入口を置ける dir (~/.local/bin・~/.npm-global/bin・~/bin) が PATH に無い = ~/.local/bin を作って PATH に入れる (止める = touch $OFF)"
      return 0
    fi
  fi
  tmp="$(mktemp "${target}.XXXXXX")" || return 1
  shim_text > "$tmp"
  if [ -n "$shim" ] && cmp -s "$tmp" "$shim"; then rm -f "$tmp"; return 0; fi
  chmod 755 "$tmp" && mv -f "$tmp" "$target" || { rm -f "$tmp"; return 1; }
  if [ -n "$shim" ]; then
    echo "[ok] codex の入口を書き直した: $target"
  else
    echo "[ok] 端末で codex と打てるようにした: $target → ChatGPT アプリ同梱の Codex CLI"
  fi
}

selftest() {
  t="$(mktemp -d)"; pass=0; fail=0
  ok() { pass=$((pass + 1)); echo "PASS: $1"; }
  ng() { fail=$((fail + 1)); echo "FAIL: $1"; }
  mkdir -p "$t/home/.local/bin" "$t/home/.claude" "$t/app" "$t/other"
  printf '#!/bin/sh\necho "fake-codex $*"\n' > "$t/app/codex"; chmod 755 "$t/app/codex"
  mkdir -p "$t/run/X.app/Contents/MacOS"
  printf '#!/bin/sh\necho "running-codex $*"\n' > "$t/run/X.app/Contents/MacOS/codex"; chmod 755 "$t/run/X.app/Contents/MacOS/codex"
  printf '#!/bin/sh\necho /usr/bin/true\n' > "$t/ps-none"; chmod 755 "$t/ps-none"
  printf '#!/bin/sh\necho /usr/bin/true; echo "%s"\n' "$t/run/X.app/Contents/MacOS/codex" > "$t/ps-run"; chmod 755 "$t/ps-run"
  run() { CODEX_SHIM_HOME="$t/home" CODEX_SHIM_PATH="$1" CODEX_SHIM_APP_BINS="$t/missing $t/app/codex" CODEX_SHIM_PS_CMD="${2:-$t/ps-none}" CODEX_SHIM_OS=Darwin sh "$0"; }
  P="$t/home/.local/bin:/usr/bin:/bin"
  out="$(run "$P")"
  case "$out" in "[ok] 端末で codex と打てるようにした: $t/home/.local/bin/codex"*) ok "installs into ~/.local/bin on PATH" ;; *) ng "install: $out" ;; esac
  [ "$("$t/home/.local/bin/codex" --version)" = "fake-codex --version" ] && ok "the shim execs the app's CLI with the arguments" || ng "shim exec"
  rm -f "$t/home/.local/bin/codex"; run "$P" "$t/ps-run" >/dev/null
  [ "$("$t/home/.local/bin/codex" x)" = "running-codex x" ] && ok "a running app executable comes first" || ng "running first"
  rm -f "$t/home/.local/bin/codex"; run "$P" >/dev/null
  [ -z "$(run "$P")" ] && ok "second run is silent" || ng "second run spoke"
  printf '\n# edited\n' >> "$t/home/.local/bin/codex"
  case "$(run "$P")" in "[ok] codex の入口を書き直した"*) ok "a changed shim is rewritten" ;; *) ng "rewrite" ;; esac
  printf '#!/bin/sh\necho real\n' > "$t/other/codex"; chmod 755 "$t/other/codex"
  case "$(run "$P:$t/other")" in "[ok] codex の入口 ($t/home/.local/bin/codex) を外した"*) ok "a real codex on PATH removes the shim" ;; *) ng "foreign" ;; esac
  [ ! -e "$t/home/.local/bin/codex" ] && [ -z "$(run "$P:$t/other")" ] && ok "with a real codex, nothing is installed" || ng "foreign install"
  touch "$t/home/.claude/codex-cli-shim.off"
  [ -z "$(run "$P")" ] && [ ! -e "$t/home/.local/bin/codex" ] && ok "the off marker stops it" || ng "off marker"
  rm -f "$t/home/.claude/codex-cli-shim.off"
  case "$(run "/usr/bin:/bin")" in "⚠️ 端末で codex と打てない"*) ok "no candidate dir on PATH warns" ;; *) ng "no dir" ;; esac
  mkdir -p "$t/home/.npm-global/bin"; rmdir "$t/home/.local/bin"
  case "$(run "$t/home/.npm-global/bin:/usr/bin")" in *"$t/home/.npm-global/bin/codex"*) ok "falls back to ~/.npm-global/bin" ;; *) ng "npm-global" ;; esac
  rm -f "$t/home/.npm-global/bin/codex"
  [ -z "$(CODEX_SHIM_HOME="$t/home" CODEX_SHIM_PATH="$t/home/.npm-global/bin" CODEX_SHIM_APP_BINS="$t/missing" CODEX_SHIM_OS=Darwin sh "$0")" ] \
    && [ ! -e "$t/home/.npm-global/bin/codex" ] && ok "without the app, nothing is installed" || ng "no app"
  [ -z "$(CODEX_SHIM_HOME="$t/home" CODEX_SHIM_PATH="$t/home/.npm-global/bin" CODEX_SHIM_APP_BINS="$t/app/codex" CODEX_SHIM_OS=Linux sh "$0")" ] \
    && ok "not macOS: nothing" || ng "linux"
  rm -rf "$t"
  echo "passed=$pass failed=$fail"
  [ "$fail" = 0 ]
}

case "${1:-}" in
  --selftest) selftest ;;
  "") install ;;
  *) echo "usage: $0 [--selftest]" >&2; exit 2 ;;
esac
