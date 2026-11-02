#!/usr/bin/env bash
# commit-msg-leak-guard-runner.sh — git commit-msg hook（BLOCK mode）: 全 repo = 学生の識別子 (2026-09-29) + 個人層が宣言すれば検出語 (sensitive-terms.txt) / 公開 repo = leak 検出 (2026-05-26 追加。 shared matcher library を source。 claude-code 2.1.x harness invoke bug の修復 option B）
# commit-msg-leak-guard-runner.sh — git native commit-msg hook (BLOCK mode)
#
# 正本: claude-config/scripts/commit-msg-leak-guard-runner.sh (layer 1)
# 各 public repo の .git/hooks/commit-msg に 1 行 stub が入り、本 script を
# absolute path で exec する (install-public-commit-msg.sh 参照)。
#
# 動作:
#   1. git が $1 に COMMIT_EDITMSG path、 $2 に message source ("message"
#      "template" "merge" "squash" "commit") を渡す (= git commit-msg hook
#      spec)
#   2. merge commit / fixup / squash 等は scope 外 (= 通常 reword 不可)、
#      $2 で skip 判定
#   3. message を読み、 shared matcher (= claude-config/scripts/lib/
#      commit-msg-leak-matcher.sh) で leak 候補検出
#   4. hit があれば exit 1 で commit を reject、 詳細を stderr に出す
#   5. `--no-verify` で bypass 可能 (git 標準の escape hatch)
#
# Mode: BLOCK (= claude-code 側 PreToolUse Bash hook の WARN mode と相補)。
#   理由 = WARN だと §5.1 single-viewpoint trap で hook output を読み流す
#   risk があり、 git 層で BLOCK にすると harness が抜けても止まる (=
#   2026-05-26 confirmed root cause = claude-code 2.1.x harness invoke bug
#   の修復 option B、 詳細 `conventions/hook-authoring.md#delivery-audit-4-axes (d) 軸`)。
#
# Gating: Stage 0 (学生の識別子、 2026-09-29) は全 repo で走る = private repo にも
#   `install-public-commit-msg.sh --any-repo` が同じ stub を置く。 Stage 0b (検出語) は
#   marker 不在の repo で、 個人層の `commit-msg-literal-scope.txt` に `all` の行があるときに走る
#   (下の Stage 0b の節)。 Stage 1 以降 (公開 repo の leak 検出) は `.claude/public-repo.marker`
#   を持つ repo だけ = 本 runner の marker の safety net が marker 不在の repo を Stage 0b の後で
#   silent pass させる。
#
# 設計思想:
#   既存 `public-precommit-runner.sh` (= file 本文 Tier A 検出) と本 runner
#   (= commit message Tier A + B 検出) は 2 layer 防御。 stage 済 file の
#   本文と、 commit message を独立に gate (= file 本文 OK だが commit
#   message に leak の事例が過去 5+ 件、 leak-incidents.md 参照)。
#   matcher logic は claude-code hook (= warn mode) と共通 library で DRY。
#
# 依存: bash 3.2 (= macOS stock)、 grep、 sed、 wc

set -uo pipefail

MSG_FILE="${1:-}"
MSG_SOURCE="${2:-}"

# ----------------------------------------------------------------------
# scope filter: 通常の commit (= 新規入力 + amend reword) のみ対象
# ----------------------------------------------------------------------
# git commit-msg hook の $2 ($GIT_COMMIT_SOURCE):
#   message  = -m / -F で渡された (= 我々の主 target)
#   template = .gitmessage 等 (= editor 起動、 我々の主 target)
#   merge    = merge commit の auto-generated message (skip)
#   squash   = squash merge (skip)
#   commit   = amend (= reword、 target)
#   ""       = 新規 commit + editor 起動 (= target)
case "$MSG_SOURCE" in
  merge|squash) exit 0 ;;
esac

[ -n "$MSG_FILE" ] || exit 0
[ -r "$MSG_FILE" ] || exit 0

# ----------------------------------------------------------------------
# Stage 0 (2026-09-29、 全 repo): 学生の識別子 (学籍番号の形・氏名) が message に入っていないか。
# 公開 repo に限らない = private repo にも stub を置く (install-public-commit-msg.sh --any-repo)。 下の marker の
# safety net より前に置く = private repo でもここまでは走る。 値の一覧は machine-local、 無い機械では何もしない。
# 述語・escape hatch (CLAUDE_STUDENT_ID_GUARD=0) の SoT = check-student-identifiers.py docstring。
# 止めるのは「exit 1 かつ engine の BLOCK 見出し」 のときだけ。 見出しの無い非 0 (engine の異常終了) は 1 行出して通す。
# ----------------------------------------------------------------------
SID_ENGINE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/check-student-identifiers.py"
if [ -f "$SID_ENGINE" ] && command -v python3 >/dev/null 2>&1; then
  sid_rc=0
  sid_out="$(python3 "$SID_ENGINE" --commit-msg "$MSG_FILE" 2>&1)" || sid_rc=$?
  [ -n "$sid_out" ] && printf '%s\n' "$sid_out" >&2
  if [ "$sid_rc" -eq 1 ] && printf '%s' "$sid_out" | grep -q 'check-student-identifiers: BLOCK'; then
    echo "[commit-msg-leak-guard-runner] commit rejected (student identifiers). 1 回だけ通す: CLAUDE_STUDENT_ID_GUARD=0" >&2
    exit 1
  fi
  if [ "$sid_rc" -ne 0 ] && ! printf '%s' "$sid_out" | grep -q 'check-student-identifiers:'; then
    echo "⚠️ commit-msg: 学生の識別子の検査が異常終了した (rc=${sid_rc}) — この commit では走っていない (commit は止めない)。 確認: python3 ${SID_ENGINE} --selftest" >&2
  fi
fi

# ----------------------------------------------------------------------
# Stage 0b: 公開の印の無い repo の commit message の検出語 (個人層が範囲を宣言したとき)
#
# commit message は暗号化されない平文で履歴に残る (git-crypt は file の中身だけを守る) =
# 非公開の repo でも、 hosting の事業者・共同編集者・後から access を得た人に読める。
# 個人層の `commit-msg-literal-scope.txt` に `all` の行 (# の行と空行は読まない) があれば、
# 個人層の sensitive-terms.txt の語 (matcher の (a)) を、 公開の印の無い repo でも止める。
# 宣言が無ければ従来どおり (= 印の無い repo は Stage 0 だけ)。 印のある repo は下の Stage 1 が全 tier で止める。
#
# 警告だけにしない理由 (実測): commit の前の警告は、 commit と push を 1 回の command で打つ
# agent には commit の後に届き、 「push 済みなので受容」「非公開なので誤検出」 と読まれて
# 同じ語が繰り返し入った。 commit を止めれば、 書き直す前に履歴へ入らない。
#
# 1 回だけ通す: CLAUDE_COMMIT_NAME_GUARD=0 (拒否の出力には書かない = 「誤検出」 と自分で
# 決めて通す流れを作らない。 人名・機関名でない語に当たったら、 持ち主が sensitive-terms の
# 許可の複合語 `!<語>` を足すのが直し方)
# ----------------------------------------------------------------------
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$REPO_ROOT" ] && [ ! -f "$REPO_ROOT/.claude/public-repo.marker" ] \
    && [ "${CLAUDE_COMMIT_NAME_GUARD:-1}" != "0" ]; then
  S0B_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
  if [ -r "$S0B_DIR/lib/find-personal-layer.sh" ] && [ -r "$S0B_DIR/lib/commit-msg-leak-matcher.sh" ]; then
    # shellcheck source=/dev/null
    . "$S0B_DIR/lib/find-personal-layer.sh"
    S0B_LAYER="$(find_personal_layer 2>/dev/null || true)"
    if [ -n "$S0B_LAYER" ] && [ -f "$S0B_LAYER/commit-msg-literal-scope.txt" ] \
        && grep -v '^[[:space:]]*#' "$S0B_LAYER/commit-msg-literal-scope.txt" 2>/dev/null | grep -qx '[[:space:]]*all[[:space:]]*'; then
      S0B_MESSAGE="$(grep -v '^#' "$MSG_FILE" 2>/dev/null || true)"
      if [ -n "$S0B_MESSAGE" ]; then
        # shellcheck source=/dev/null
        . "$S0B_DIR/lib/commit-msg-leak-matcher.sh"
        run_leak_matcher "$S0B_MESSAGE"
        if [ "${LEAK_MATCHER_LITERAL_COUNT:-0}" -gt 0 ]; then
          cat >&2 << EOF
[commit-msg-leak-guard-runner] commit rejected: commit message の ${LEAK_MATCHER_LITERAL_COUNT} 行に検出語 (個人層の sensitive-terms.txt = 人名・機関名) がある。

repo: $REPO_ROOT
この repo に公開の印は無いが、 commit message は暗号化されない平文で履歴に残る
(個人層の commit-msg-literal-scope.txt = all)。

直し方: 人は役割の語 (本人・共著者・事務の担当・講師・学生 A など)、 機関は「本学」「相手の機関」
に直して打ち直す。 誰のことかは暗号化される中身 (台帳・記録) に書く。
検出語が人名・機関名でない (地名など) と思ったら、 打ち直さずに持ち主に聞く。
EOF
          exit 1
        fi
      fi
    fi
  fi
fi

# ----------------------------------------------------------------------
# repo marker safety net: marker 不在なら silent pass
# (= 主な gating は install-public-commit-msg.sh、 本 check は double-safe)
# ----------------------------------------------------------------------
if [ -n "$REPO_ROOT" ] && [ ! -f "$REPO_ROOT/.claude/public-repo.marker" ]; then
  exit 0
fi

# ----------------------------------------------------------------------
# Read message (= comment lines stripped; git scrubs them at commit time
# but reading filtered version mirrors what git will actually store)
# ----------------------------------------------------------------------
# `git stripspace --strip-comments` を使うのが ideal だが、 全ての git
# version で同 flag があるとは限らないので sed で `^#` 行を除外
MESSAGE="$(grep -v '^#' "$MSG_FILE" 2>/dev/null || true)"

# 空 message なら git 側が後で reject するので skip
[ -n "$MESSAGE" ] || exit 0

# ----------------------------------------------------------------------
# matcher invoke (shared library)
# ----------------------------------------------------------------------
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
MATCHER_LIB="$SELF_DIR/lib/commit-msg-leak-matcher.sh"
if [ ! -r "$MATCHER_LIB" ]; then
  # library 不在 = claude-config 配置異常、 fail-open (= 既存 commit flow を
  # 壊さない)。 user に visibility が無いので stderr に notice
  echo "[commit-msg-leak-guard-runner] WARNING: matcher library missing: $MATCHER_LIB (leak check skipped)" >&2
  exit 0
fi
# shellcheck source=/dev/null
. "$MATCHER_LIB"

run_leak_matcher "$MESSAGE"
HITS="${LEAK_MATCHER_HITS:-}"

# ----------------------------------------------------------------------
# Tier D (2026-09-13): 未公開文書の逐語が message に入っていないか (engine = check-unpublished-quote.py、
# 源 = 個人層の unpublished-sources.txt)。 「exit 1 かつ engine 自身の見出し」 のときだけ止める。
# escape hatch: CLAUDE_UNPUBLISHED_GUARD=0。 規律 = conventions/confidential-repo-boundary.md#unpublished-text-public-gate
# ----------------------------------------------------------------------
UQ_ENGINE="$SELF_DIR/check-unpublished-quote.py"
if [ -z "$HITS" ] && [ "${CLAUDE_UNPUBLISHED_GUARD:-1}" != "0" ] && [ -f "$UQ_ENGINE" ] \
    && [ -r "$SELF_DIR/lib/find-personal-layer.sh" ] && command -v python3 >/dev/null 2>&1; then
  # shellcheck source=/dev/null
  . "$SELF_DIR/lib/find-personal-layer.sh"
  UQ_LAYER="$(find_personal_layer 2>/dev/null || true)"
  if [ -n "$UQ_LAYER" ] && [ -f "$UQ_LAYER/unpublished-sources.txt" ]; then
    uq_rc=0
    uq_out="$(python3 "$UQ_ENGINE" --config "$UQ_LAYER/unpublished-sources.txt" --message-file "$MSG_FILE" 2>&1)" || uq_rc=$?
    [ -n "$uq_out" ] && printf '%s\n' "$uq_out" >&2
    if [ "$uq_rc" -eq 1 ] && printf '%s' "$uq_out" | grep -q '\[unpublished-quote\] the commit message contains'; then
      echo "[commit-msg-leak-guard-runner] commit rejected (unpublished-quote). bypass once: CLAUDE_UNPUBLISHED_GUARD=0" >&2
      exit 1
    fi
  fi
fi

# ----------------------------------------------------------------------
# Tier E (2026-09-14): owner の非公開の活動の事実が message に入っていないか (engine = check-activity-facts.py、
# 固有語 = 個人層 activity-fact-terms.txt → BLOCK、 出来事の語 × 日付・件数 → 警告だけ)。
# escape hatch: CLAUDE_ACTIVITY_FACTS_GUARD=0。 規律 = CLAUDE.md#owner-activity-facts
# ----------------------------------------------------------------------
AF_ENGINE="$SELF_DIR/check-activity-facts.py"
if [ -z "$HITS" ] && [ "${CLAUDE_ACTIVITY_FACTS_GUARD:-1}" != "0" ] && [ -f "$AF_ENGINE" ] && command -v python3 >/dev/null 2>&1; then
  af_rc=0
  af_out="$(python3 "$AF_ENGINE" --message-file "$MSG_FILE" 2>&1)" || af_rc=$?
  [ -n "$af_out" ] && printf '%s\n' "$af_out" >&2
  if [ "$af_rc" -eq 1 ] && printf '%s' "$af_out" | grep -q '\[activity-facts\] the commit message contains a literal'; then
    echo "[commit-msg-leak-guard-runner] commit rejected (activity-facts). bypass once: CLAUDE_ACTIVITY_FACTS_GUARD=0" >&2
    exit 1
  fi
fi

# ----------------------------------------------------------------------
# Tier F (2026-10-19): owner が暗号化して持つ値 (電話・口座・生年月日・住所) が message に入っていないか
# (engine = check-value-index.py、 源 = 個人層の value-index.txt が指す索引の節。 出力は行番号だけ)。
# escape hatch: CLAUDE_VALUE_INDEX_GUARD=0
# ----------------------------------------------------------------------
VI_ENGINE="$SELF_DIR/check-value-index.py"
if [ -z "$HITS" ] && [ "${CLAUDE_VALUE_INDEX_GUARD:-1}" != "0" ] && [ -f "$VI_ENGINE" ] \
    && [ -r "$SELF_DIR/lib/find-personal-layer.sh" ] && command -v python3 >/dev/null 2>&1; then
  # shellcheck source=/dev/null
  . "$SELF_DIR/lib/find-personal-layer.sh"
  VI_LAYER="$(find_personal_layer 2>/dev/null || true)"
  if [ -n "$VI_LAYER" ] && [ -f "$VI_LAYER/value-index.txt" ]; then
    vi_rc=0
    vi_out="$(python3 "$VI_ENGINE" --config "$VI_LAYER/value-index.txt" --message-file "$MSG_FILE" 2>&1)" || vi_rc=$?
    [ -n "$vi_out" ] && printf '%s\n' "$vi_out" >&2
    if [ "$vi_rc" -eq 1 ] && printf '%s' "$vi_out" | grep -q '\[value-index\] the commit message contains'; then
      echo "[commit-msg-leak-guard-runner] commit rejected (value-index). bypass once: CLAUDE_VALUE_INDEX_GUARD=0" >&2
      exit 1
    fi
  fi
fi

# ----------------------------------------------------------------------
# 判定
# ----------------------------------------------------------------------
if [ -z "$HITS" ]; then
  exit 0  # silent pass
fi

# BLOCK mode: stderr に詳細 + exit 1 で git commit を reject
cat >&2 << EOF
[commit-msg-leak-guard] commit rejected: leak candidate in commit message.

repo:         $REPO_ROOT
message file: $MSG_FILE
hits:$HITS

本 repo は .claude/public-repo.marker で public と宣言されています。
commit message に非例外 private repo 名 または sensitive-terms.txt の
literal term が含まれます (= git log で grep 可能な public surface)。

対処:
  - 該当 repo 名を抽象化 (= "上流リポ" / "研究 LaTeX project" /
    "個人層" 等) して new commit message で再 commit
  - 既に push 済の修復は force push せず leak-incidents.md に記録
    (= claude-config/CLAUDE.md §「安全規則」 + odakin-prefs/leak-incidents.md
    の運用と整合)

例外 list (= mention OK な非公開 repo) の正本:
  claude-config/CLAUDE.md §「例外 list と criterion」
  (matcher の LEAK_MATCHER_ALLOWLIST と同期)

意図的に commit したい場合は \`git commit --no-verify\` で bypass 可能
(escape hatch)。 但し意図的 bypass は leak-incidents.md に記録推奨。

詳細規約:
  - claude-config/CLAUDE.md §「安全規則 (公開リポ)」
  - odakin-prefs/leak-incidents.md (事例集計)
  - claude-config/conventions/hook-authoring.md#delivery-audit-4-axes (d) (= 2026-05-26 root
    cause + 本 hook の設計動機)
EOF

exit 1
