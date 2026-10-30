#!/usr/bin/env python3
"""check-fleet-status.py — fleet heartbeat の reader（全マシン分の beat を読み role 別に異常 surface = always-on の heartbeat 停止 🔴 / best-effort のスリープは仕様で silent / beat が新鮮な時の server auth/version error 🔴。finding 0 件 silent、fetch しない = 呼び出し側が鮮度担保、--selftest 内蔵、conventions/multi-machine-state.md#fleet-heartbeat）
check-fleet-status.py — fleet heartbeat の reader (layer 1 generic)。

sibling `fleet-heartbeat.py` (writer) が各マシンから git repo に commit する
`<dir>/<hostname>.json` を全部読み、 マシン役割 (role) に応じて異常を surface する。
finding 0 件なら silent (= dashboard / SessionStart hook 統合前提)。

役割 semantics:
- always-on   : 常時起動マシン。 heartbeat が --stale-hours を超えて停止 = 🔴
                (マシン / ネットワーク / launchd / git のどれかが死んでいる)。
                beat file 自体が無い = ℹ️ (install 待ち)。
- best-effort : スリープする可搬マシン。 staleness は仕様なので silent。
                beat が新鮮なとき (= 起きている) の server 異常のみ報告。

server 異常 (どの役割でも beat が新鮮なら報告):
- last_status auth_error      → 🔴 auth 失効で cycling (claude auth login が要る)
- last_status version_error   → 🔴 CLI が古い (remote-control-server.md#ts-version-mismatch)
- last_status consent_pending → 🟠 初回同意プロンプト待ちで進めない
- pid 無し (loaded but dead)  → 🟠

設定フォルダの認証 (writer の config_dir_auth、 追加設定不要):
  最後の問い合わせが失敗し、 その後ログインし直していない pinned の設定フォルダ = 🔴 (他のマシンの分だけ。 自分の分は
  check-desktop-logout-auth.py が出す)。 server の Connected は OAuth の更新が生きている証拠にならないので、 こちらで見る。
  ⚠️ config_dirs の `default` は desktop app を最後に起動した時の account = ログインの記録ではない (writer の docstring)。

inventory parity (writer 側 --inventory の対、 追加設定不要):
  writer が記録した `inventories: {label: [name...]}` を全マシン分で突合し、 **他マシンには
  在るのにこのマシンには無い** entry を 🟠 で surface する。 期待集合は **fleet の union** =
  宣言 registry を持たない (= 登録忘れという規律依存の穴を作らない)。 = 「あるマシンにだけ
  設定・credential が無い」 状態が誰にも見えないまま放置される問題への対処
  (2026-07-25 実測: ある account の credential が 1 台だけ未配置のまま 45 日 silent)。
  - label を報告していないマシンは比較対象外 (= 旧 beat / 未設定を「全部欠落」 と誤判定しない)
  - 報告マシンが 1 台だけなら silent (= union == self で比較の意味がない)
  - stale な beat も比較に入れる (= inventory は liveness でなく持ち物の状態。 ただし
    finding に beat 年齢を併記し、 断定でなく「疑い」 として渡す)
  - **限界: どのマシンにも無い物は検出できない** (= union が空)。 宣言集合を持つ検出器
    (例: mail 検出器の ACCOUNTS) との相補関係で埋める

coverage check (--expect-account、 repeatable):
  pinned per-account 構成 (= remote-control-server.md#multi-account-servers の推奨形:
  server はアカウントごとの pinned config dir + suffix label で立てる) を前提に、
  **beat が新鮮なマシンに expected account の suffix server が loaded されているか** を検査。
  欠けていれば 🟠 (= そのマシンのその account の mobile セルが未開通)。
  suffix と account の対応は label 末尾 (= `<rc-prefix>.<acct>`) で判定。
  同じ account 名で **config dir の取り違え** も検査する: beat の config_dirs で `~/.claude-<acct>` が
  別の account (email の local part が <acct> でない) でログインしていれば 🔴 (= 再ログインの時に
  ブラウザが別 account だった、 remote-control-server.md#oauth-grabs-browser-account。 その dir を使う
  server / 無人 job は名前と違う account で動き続け、 他の検査は黙る)。 account 名が email の local part
  でない命名なら `--expect-account <acct>=<email>` で対応を明示する。

予定の run が log に残っていない (--routine-ledger、 job health の claude_p / gated / schedule / log_mtime):
  本番ホスト (routine-host-gate.py の台帳の host) で、 headless `claude -p` を起動する job の最後の予定の時刻から
  MISSED_GRACE_H 時間たっても log が更新されていなければ出す (1 本 = 🟠、 2 本以上 = 🔴 = 無人の仕事がまとめて止まっている)。
  起動しなかった run と、 終わらずに止まっている run (claude -p は終わる時にしか log を書かない) は、 終了コード
  (= 前回の run のまま) にも log 末尾にも出ない (conventions/scheduled-tasks.md#missed-run-detection、 判定 =
  lib/launchd_job_log.py の missed_fire)。
  - 関門つきの job は本番ホストの分だけ、 台帳の since (本番になった時刻) より後の予定だけを見る
    (本番でない機械では関門が待機の 1 行を log に書く = log の新しさは run の証拠にならない)。 本番ホストでも
    log の最後の行が関門の待機 (log_deferred) なら run ではない (= 関門が別の機械を本番と読んだ)。
    関門なしの job は always-on の機械の分だけ見る。 今走っている job (running) には「実行中」 と添える
  - beat の時刻の状態で判定する (= commit の間引きで beat が古くても、 その時点の log と予定を比べる)
  - 旧 writer の beat (claude_p / schedule 欄なし) は、 この機械の同じ label の plist の予定で読む
  - 台帳の host は --role に無ければ always-on とみなす (= 本番ホストの heartbeat の停止も 🔴)
  - 自分の機械の分も出す (check-cron-health は予定を見ない)

clone の同期 (writer の --repos-root の repos.stopped / repos.sync、 追加設定不要):
  beat が新鮮なマシンの clone ごとに、 追従が止まった (🔴) / upstream と分岐したまま SYNC_UNPUSHED_H 時間以上 (🔴 = 手元の commit は
  他の machine に届いていない) / push されていない commit が SYNC_UNPUSHED_H 時間以上 (🟠) / SYNC_BLOCKED_H 時間以上遅れたまま
  upstream の変更と重なる未 commit が在る (🟠 = 最新化できない、 古さは遅れの最古の commit の時刻) を出す。 自分のマシンの分も出す (session 開始の同期の 1 行は古さを言わない)。
  path は writer が載せない = どの file かはそのマシンで見る。 実測の動機: 無人の書き手の commit が本番の機械に閉じ、 その機械の
  記録は毎時「止まっている」 を載せていたが、 人が使っていた別の機械には何も出なかった (= 書き手の log と、 session を開かない機械の
  session 開始の 1 行にしか出ていなかった)。

usage:
  check-fleet-status.py --dir <fleet-status-dir> [--role HOST=always-on ...]
      [--stale-hours 6] [--expect-account <acct> ...] [--routine-ledger <active-routine-host.json>]
  check-fleet-status.py --selftest

⚠️ 読むのは git working tree = 「最後に pull した時点の他マシン状態」。 呼び出し側の
   dashboard / sync-sweep が fetch/pull を担う前提 (= 本 script は fetch しない)。
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
try:
    from launchd_job_log import HIDDEN_FAIL_DAYS as _HFD   # 書き手 (fleet-heartbeat) と同じ閾値
except Exception:
    _HFD = 3
try:
    import launchd_job_log as _jl
except Exception:
    _jl = None
_HIDDEN_FAIL_H = _HFD * 24
_CAUSE = {"auth": "Claude の認証切れ", "ptl": "Prompt is too long (context 超過)"}

BAD = {
    "auth_error": ("🔴", "auth 失効で cycling 中 (= そのマシンで `claude auth login`。 remote-control-server.md#ts-api-key-conflict / #account-auth-keychain)"),
    "version_error": ("🔴", "CLI が古くて RC 不能 (remote-control-server.md#ts-version-mismatch)"),
    "consent_pending": ("🟠", "初回同意プロンプト待ちで進めない (= install script 再実行で自動 seed、 remote-control-server.md#ts-workspace-trust)"),
    "trust_error": ("🔴", "workspace trust 未承認で exit-1 cycling (= install script 再実行で自動 seed、 remote-control-server.md#ts-workspace-trust)"),
}


def inventory_findings(beats):
    """全マシンの inventories を union と突合し、 このマシンだけ欠けている entry を surface。

    beats = [(host, data, age_h)]。 期待集合 = fleet の union (= 宣言 registry 不要)。
    label を報告していない host は比較対象外、 報告 host が 1 台なら silent。
    """
    per_label = {}
    for host, d, age_h in beats:
        inv = d.get("inventories")
        if not isinstance(inv, dict):
            continue  # 旧 beat / --inventory 未設定 = 比較対象外 (「全部欠落」 と誤判定しない)
        for label, names in inv.items():
            if not isinstance(names, list):
                continue
            per_label.setdefault(label, {})[host] = (set(map(str, names)), age_h)
    out = []
    for label in sorted(per_label):
        hosts = per_label[label]
        if len(hosts) < 2:
            continue  # 比較の基準が無い (= union == self)
        union = set().union(*(v[0] for v in hosts.values()))
        for host in sorted(hosts):
            names, age_h = hosts[host]
            missing = sorted(union - names)
            if not missing:
                continue
            others = sorted(h for h, v in hosts.items() if set(missing) & v[0])
            out.append(
                f"🟠 {host}: inventory {label} に {', '.join(missing)} が無い "
                f"(他マシンには在る: {', '.join(others)}) = このマシンだけ未配置の疑い "
                f"[beat {age_h:.0f}h 前] — 該当マシンで配置するか、 意図的な差なら "
                f"writer の --inventory から除外 (multi-machine-state.md#fleet-heartbeat)"
            )
    return out


def job_findings(host, d, self_host=None):
    """1 マシンの beat の jobs から finding を作る (writer の --job-label-prefix、 docstring = fleet-heartbeat.py §job health)。
    - 🔴 command (起動の関門など) が PATH の python3 を呼ぶのに、 その python3 が起動できない = ジョブは黙って休み続ける
    - 🟠 wrapper が PATH の python3 を呼ぶのに、 必要な module を import できない = engine が起動直後に終わる
    - 🟠 最後の終了コードが 0 でない (自分のマシンの分は check-cron-health が出すので出さない)。 直近 run の log 末尾が
      既知の失敗なら原因を添える (log_failure、 判定 = lib/launchd_job_log.py)
    - 🟠 終了コードは 0 でも、 直近 run の log 末尾が既知の失敗で log が新しい (= plist の読み込み直しで 0 に戻った、
      conventions/scheduled-tasks.md#reload-resets-exit-status)
    - 🔴 Claude の認証切れで失敗している job がある config dir ごとに 1 行 + そのマシンでの login の command
      (conventions/scheduled-tasks.md#headless-auth-expiry)
    旧 beat (jobs 欄なし / log_failure 欄なし) は、 その欄の分だけ何も言わない。"""
    out = []
    auth: dict[str, int] = {}
    mods = ", ".join(d.get("job_python_modules") or []) or "必要な module"
    for j in d.get("jobs") or []:
        lab = j.get("label", "?")
        py = j.get("python") or "(PATH に python3 が無い)"
        if j.get("bare_in_command") and j.get("python_runs") is False:
            out.append(f"🔴 {host}: job {lab} の起動行が PATH の python3 ({py}) を呼ぶが、 それが起動できない "
                       f"= 関門の失敗が「待機」 と同じに扱われ黙って休み続ける (shell-env.md#job-python-by-capability)")
        elif j.get("bare_in_wrapper") and j.get("python_ok") is False:
            out.append(f"🟠 {host}: job {lab} の wrapper が PATH の python3 ({py}) を呼ぶが {mods} を import できない "
                       f"= engine が起動直後に終わる (exit 0 なら成功に見える)。 wrapper で pick_python を使う "
                       f"(shell-env.md#job-python-by-capability)")
        le = j.get("last_exit")
        if host == self_host:
            continue   # 自分の分は check-cron-health が同じ判定で出す
        lf, age_h = j.get("log_failure"), j.get("log_age_h")
        cause = _CAUSE.get(lf or "", "")
        fresh = isinstance(age_h, (int, float)) and 0 <= age_h < _HIDDEN_FAIL_H
        failing = False
        if isinstance(le, int) and le != 0:
            failing = True
            out.append(f"🟠 {host}: job {lab} の最後の終了コード = {le}"
                       f"{f' — 直近 run の log 末尾 = {cause}' if cause else ''} (そのマシンの ~/Library/Logs/{lab}.log)")
        elif le == 0 and cause and fresh:
            failing = True
            out.append(f"🟠 {host}: job {lab} は終了コード 0 だが直近 run の log 末尾 = {cause}"
                       f" (= plist の読み込み直しで 0 に戻った、 scheduled-tasks.md#reload-resets-exit-status)")
        if failing and lf == "auth":
            cd = j.get("config_dir") or "<その job の plist の CLAUDE_CONFIG_DIR>"
            auth[cd] = auth.get(cd, 0) + 1
    for cd, n in auth.items():
        out.append(f"🔴 {host}: Claude の認証切れで無人 job {n} 本が失敗 ({cd}) = そのマシンの terminal で"
                   f" `CLAUDE_CONFIG_DIR={cd} claude auth login` (再ログイン済みなら次の run で消える、"
                   f" scheduled-tasks.md#headless-auth-expiry)")
    return out


def _same_host(a, b):
    n = lambda x: (x or "").lower().split(".")[0]
    return bool(a) and bool(b) and n(a) == n(b)


def load_routine(path):
    """routine-host-gate.py の台帳から {"host", "since" (epoch か None)}。 読めない = None (= 関門つき job は判定しない)。"""
    try:
        d = json.load(open(Path(path).expanduser()))
    except Exception:
        return None
    if not isinstance(d, dict) or not d.get("host"):
        return None
    since = None
    try:
        import datetime as _dt
        since = _dt.datetime.fromisoformat(str(d.get("since"))).timestamp() if d.get("since") else None
    except Exception:
        since = None
    return {"host": str(d["host"]), "since": since}


def missed_run_findings(host, d, role, routine=None, plist_dir=None):
    """予定の時刻を過ぎても log が更新されていない claude -p の job (docstring §予定の run)。 1 マシン 1 行。"""
    epoch = d.get("epoch")
    if _jl is None or not isinstance(epoch, (int, float)):
        return []
    active = bool(routine) and _same_host(host, routine.get("host"))
    missed = []
    for j in d.get("jobs") or []:
        lab = j.get("label", "?")
        local = None
        if not all(k in j for k in ("claude_p", "gated", "schedule")) and plist_dir:
            local = _jl.load_plist(Path(plist_dir).expanduser() / f"{lab}.plist")   # 旧 writer の beat
        claude_p = j["claude_p"] if "claude_p" in j else (local is not None and _jl.runs_claude_p(local))
        gated = j["gated"] if "gated" in j else (local is not None and _jl.is_gated(local))
        sched = j["schedule"] if "schedule" in j else _jl.schedule_of(local)
        if not claude_p or not sched:
            continue
        if (gated and not active) or (not gated and role != "always-on"):
            continue
        lm = j.get("log_mtime")
        if lm is None and isinstance(j.get("log_age_h"), (int, float)):
            lm = epoch - j["log_age_h"] * 3600
        deferred = bool(gated and j.get("log_deferred"))
        fire = _jl.missed_fire(sched, None if deferred else lm, epoch, since=routine.get("since") if gated else None)
        if fire is not None:
            note = "、 最後の起動で関門が待機を選んだ" if deferred else ""
            note += "、 実行中" if j.get("running") else ""
            missed.append((lab, fire, lm, note))
    if not missed:
        return []
    fmt = lambda t: time.strftime("%-m/%-d %H:%M", time.localtime(t))
    items = ", ".join(f"{lab.rsplit('.', 1)[-1]} (予定 {fmt(f)}、 log の最後 {fmt(lm) if lm else 'なし'}{note})"
                      for lab, f, lm, note in missed)
    pre = ".".join(missed[0][0].split(".")[:-1]) if len(missed) > 1 else missed[0][0]
    mark = "🔴" if len(missed) >= 2 else "🟠"
    return [f"{mark} {host}: 予定の時刻を {_jl.MISSED_GRACE_H}h 過ぎても log が更新されていない無人 job {len(missed)} 本"
            f" [beat {fmt(epoch)} 時点] = 起動していないか、 claude -p が終わらずに止まっている (終了コードにも log 末尾にも"
            f"出ない): {items}。 そのマシンで `launchctl list | grep {pre}` の PID 列と"
            f" `ps -axo pid,lstart,etime,command | grep 'claude.*-p'` を見る (居座っていれば画面の許可ダイアログか"
            f" `sample <pid>`、 scheduled-tasks.md#missed-run-detection)"]


def auth_findings(host, d, self_host=None):
    """1 マシンの beat の config_dir_auth から finding を作る (writer の判定 = lib/config_dir_auth.py、 問い合わせは
    check-desktop-logout-auth.py の見張り)。 🔴 = 最後の問い合わせが失敗し、 その後ログインし直していない設定フォルダ。
    自分のマシンの分は check-desktop-logout-auth.py が同じ判定で出すので出さない。 旧 beat (欄なし) は黙る。
    時刻は失敗が続いた最初の問い合わせ (first_fail)。 この欄の無い beat は最後の問い合わせで出す。"""
    if host == self_host:
        return []
    out = []
    for alias, a in sorted((d.get("config_dir_auth") or {}).items()):
        if isinstance(a, dict) and a.get("dead"):
            since = (f"{a['first_fail']} の問い合わせから失敗が続き" if a.get("first_fail")
                     else f"{a.get('last_probe') or '?'} の問い合わせ〔{a.get('last_probe_tag') or '?'}〕が失敗し")
            out.append(f"🔴 {host}: 設定フォルダ ~/.claude-{alias} が切れた ({since}、 その後ログインし直していない) = そのマシンの terminal で"
                       f" `CLAUDE_CONFIG_DIR=~/.claude-{alias} claude auth login` (scheduled-tasks.md#headless-auth-expiry)")
    return out


SYNC_UNPUSHED_H = 3    # 手元にだけ在る commit がこれより古ければ出す (session の途中で push 前の数分は出さない)
SYNC_BLOCKED_H = 12    # 最新化を止める未 commit がこれより古ければ出す (持ち主が居ない疑い)


def _ago(sec):
    h = max(0, int(sec)) // 3600
    return f"{h} 時間" if h < 48 else f"{h // 24} 日"


def sync_findings(host, d, now, age_h=0.0):
    """1 マシンの beat の repos.stopped / repos.sync から finding を作る (writer の事実 = fleet-heartbeat.py の sync_facts)。
    - 🔴 stopped = 追従が止まった (手元にしか無い commit が書き換えで捨てられた世代のもの)
    - 🔴 分岐したまま SYNC_UNPUSHED_H 時間以上 (手元にだけ在る commit + upstream の前進) = 手元の commit は他の machine に届いていない
    - 🟠 push されていない commit が SYNC_UNPUSHED_H 時間以上 (遅れてはいない)
    - 🟠 遅れて SYNC_BLOCKED_H 時間以上 (遅れの最古の commit の時刻で測る)、 upstream の変更と重なる未 commit が在る = 最新化できない
      (持ち主の居ない変更の疑い。 file の更新時刻は使わない = よく書かれる台帳の file は何日止まっていても新しく見える)。
      writer が読むだけの試走をしていれば (trial = lib/intersect_sync の verdict) その結果を行に添える
    なぜ (実測): 無人の書き手の commit が本番の機械の clone に閉じ、 同期の止まった表示は session を開かないその機械の上にしか
    出なかった。 毎時の記録は「止まっている」 を載せていたが、 読む側が出していなかった = 人が使っている別の機械に届く面に出す。"""
    rp = d.get("repos") or {}
    out = []
    note = f" [beat {age_h:.0f}h 前]" if age_h >= 1 else ""
    stopped = {x for x in (rp.get("stopped") or []) if isinstance(x, str)}
    for name in sorted(stopped):
        out.append(f"🔴 {host}: {name} の追従が止まっている = 手元にしか無い commit が書き換えで捨てられた世代のもの"
                   f" (pull / rebase をしない。 そのマシンの clone で git log @{{u}}..HEAD を見て揃える = "
                   f"multi-machine-state.md#history-rewrite-follow){note}")
    for name, v in sorted((rp.get("sync") or {}).items()):
        if name in stopped or not isinstance(v, dict):
            continue
        a, b, k = v.get("ahead") or 0, v.get("behind") or 0, v.get("wip_overlap") or 0
        since, ws = v.get("ahead_since"), v.get("behind_since")
        if a and isinstance(since, (int, float)) and now - since >= SYNC_UNPUSHED_H * 3600:
            if b:
                out.append(f"🔴 {host}: {name} が upstream と分岐したまま {_ago(now - since)} (手元にだけ在る commit {a}・"
                           f"upstream にだけ在る commit {b}) = 手元の commit は他の machine に届いていない。 そのマシンの clone で"
                           f" git log @{{u}}..HEAD を見て、 退避 → upstream に無い分を載せ直す → 揃える"
                           f" (multi-session-coordination.md#ordinary-divergence-replay){note}")
            else:
                out.append(f"🟠 {host}: {name} に push されていない commit {a} (最古 {_ago(now - since)}前) = 他の machine に"
                           f"届いていない。 そのマシンの clone で git log @{{u}}..HEAD を見て push する (無人の書き手なら push の失敗を"
                           f"疑う = multi-session-coordination.md#unattended-writer-stale-base){note}")
            continue
        if b and k and isinstance(ws, (int, float)) and now - ws >= SYNC_BLOCKED_H * 3600:
            tr = v.get("trial")
            tnote = (" [試走: 道具なら衝突も欠けも無く解ける見込み]" if tr == "clean"
                     else f" [試走: 道具では解けない = {tr}]" if isinstance(tr, str) and tr else "")
            out.append(f"🟠 {host}: {name} が {b} commit 遅れたまま最新化できない (未 commit の変更 {k} file が upstream の変更と"
                       f"重なる、 遅れの最古 {_ago(now - ws)}前) = 持ち主の session に commit させる / 居なければ"
                       f" multi-session-coordination.md#owner-gone-intersect-sync{tnote}{note}")
    return out


def scan(dir_, roles, stale_hours, now=None, expect_accounts=None, warn_desktop_tasks=False, self_host=None,
         routine=None, plist_dir=None):
    now = now or time.time()
    expect_accounts = expect_accounts or []
    roles = dict(roles)
    if routine and not any(_same_host(h, routine["host"]) for h in roles):
        roles[routine["host"]] = "always-on"   # 本番ホストは常時起動 (heartbeat の停止も 🔴)
    findings = []
    seen = set()
    beats = []
    for f in sorted(dir_.glob("*.json")):
        try:
            d = json.load(open(f))
        except Exception:
            findings.append(f"🟠 {f.name}: parse 不能 (壊れた heartbeat file)")
            continue
        host = d.get("host", f.stem)
        seen.add(host)
        role = next((v for h, v in roles.items() if _same_host(h, host)), "best-effort")
        age_h = (now - d.get("epoch", 0)) / 3600
        fresh = age_h <= stale_hours
        # inventory は「持ち物の状態」 で liveness ではないので stale な beat も比較に入れる
        # (= スリープ中のマシンの欠落こそ、 起きている側から見えるべき情報)
        beats.append((host, d, age_h))
        if role == "always-on" and not fresh:
            findings.append(
                f"🔴 {host} (always-on): heartbeat が {age_h:.1f}h 停止 (threshold {stale_hours:g}h) "
                f"= マシン / ネットワーク / launchd / git push / **読み手 clone の behind** のどれか。 "
                f"結論前に heartbeat repo を git fetch + pull して再実行 (= 読み手側 stale による"
                f"偽アラーム排除、 multi-machine-state.md#fleet-heartbeat 原則 4)。 "
                f"実 stale ならスマホの environment 一覧でも server 生存を cross-check"
            )
            continue
        if not fresh:
            continue  # best-effort の staleness は仕様 (スリープ)
        for s in d.get("servers", []):
            st = s.get("last_status")
            if st in BAD:
                mark, desc = BAD[st]
                findings.append(f"{mark} {host}: server {s.get('label')} = {st} — {desc}")
            elif s.get("pid") is None:
                findings.append(f"🟠 {host}: server {s.get('label')} が loaded だが process 無し")
        findings.extend(job_findings(host, d, self_host))
        findings.extend(missed_run_findings(host, d, role, routine, plist_dir))
        findings.extend(auth_findings(host, d, self_host))
        findings.extend(sync_findings(host, d, now, age_h))
        if role == "always-on" and not d.get("servers"):
            findings.append(f"🟠 {host} (always-on): RC server が 1 本も loaded されていない")
        # coverage check: expected account の suffix server (= label 末尾 .<acct>) が居るか
        for spec in expect_accounts:
            acct = spec.split("=", 1)[0]
            if not any(s.get("label", "").endswith(f".{acct}") for s in d.get("servers", [])):
                findings.append(
                    f"🟠 {host}: {acct} の per-account server 無し = このマシンの {acct} mobile セル未開通 "
                    f"(1 回の OAuth + suffix server install で永続開通)"
                )
        # config dir の取り違え: ~/.claude-<acct> が別 account でログインしている (= 再ログイン時に
        # ブラウザが別 account だった)。 beat の email は .claude.json の metadata = 確認はそのマシンで
        # `claude auth status`。
        dirs = d.get("config_dirs") or {}
        for spec in expect_accounts:
            acct, _, want = spec.partition("=")
            email = dirs.get(acct)
            if not email:
                continue
            ok_acct = (email.lower() == want.lower()) if want else (email.split("@")[0].lower() == acct.lower())
            if not ok_acct:
                findings.append(
                    f"🔴 {host}: config dir ~/.claude-{acct} が {email} でログインしている (名前は {acct}) "
                    f"= その dir を使う server / 無人 job は {acct} でなく {email} で動いている。 そのマシンの"
                    f"ブラウザの claude.ai を {acct} に切り替えてから `CLAUDE_CONFIG_DIR=~/.claude-{acct} claude auth login`、"
                    f" `claude auth status` で email を確かめ、 その dir の server を再起動 "
                    f"(remote-control-server.md#oauth-grabs-browser-account)"
                )
        # desktop scheduled task の復活検出 (= opt-in。 「無人ジョブは launchd only」 方針の
        # マシンで、 account 切替が旧 registry の enabled task を黙って復活させ launchd 移行済
        # ジョブと二重実行する事故を surface。 2026-07-04 実測: swap から発覚まで 2 日 silent)
        if warn_desktop_tasks:
            for reg in d.get("desktop_scheduled_tasks", []) or []:
                ids = reg.get("enabled_ids")
                if ids:
                    findings.append(
                        f"🔴 {host}: desktop scheduled task {len(ids)} 件 enabled "
                        f"(registry {reg.get('registry')}: {', '.join(ids)}) — "
                        f"launchd 移行方針下では account-swap 復活の疑い = 二重実行 + session 一覧 noise。 "
                        f"該当マシンの desktop app で enabled:false 化 (scheduled-tasks.md#registrable-session-types)"
                    )
    for host, role in roles.items():
        if role == "always-on" and not any(_same_host(host, x) for x in seen):
            findings.append(f"ℹ️ {host} (always-on): heartbeat 未開始 (= そのマシンで fleet-heartbeat の install 待ち)")
    findings.extend(inventory_findings(beats))
    return findings


def selftest():
    import tempfile
    ok = 0
    now = 1_800_000_000
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)

        def write(host, epoch, servers):
            json.dump({"host": host, "epoch": epoch, "servers": servers},
                      open(d / f"{host}.json", "w"))

        # 1: always-on stale → 🔴
        write("srv", now - 10 * 3600, [])
        f = scan(d, {"srv": "always-on"}, 6, now)
        assert any("🔴 srv" in x and "停止" in x for x in f), f
        ok += 1
        # 2: best-effort stale → silent
        write("lap", now - 48 * 3600, [{"label": "x", "pid": "1", "last_status": "auth_error"}])
        f = scan(d, {"srv": "always-on"}, 6, now)
        assert not any("lap" in x for x in f), f
        ok += 1
        # 3: fresh + auth_error → 🔴 (best-effort でも)
        write("lap", now - 600, [{"label": "x", "pid": "1", "last_status": "auth_error"}])
        f = scan(d, {}, 6, now)
        assert any("lap" in x and "auth_error" in x for x in f), f
        ok += 1
        # 3b: fresh + trust_error → 🔴 (= virgin config dir の headless 死)
        write("lap", now - 600, [{"label": "x", "pid": None, "last_status": "trust_error"}])
        f = scan(d, {}, 6, now)
        assert any("lap" in x and "trust_error" in x and "🔴" in x for x in f), f
        ok += 1
        # 4: fresh + connected → silent
        write("lap", now - 600, [{"label": "x", "pid": "1", "last_status": "connected"}])
        write("srv", now - 600, [{"label": "y", "pid": "2", "last_status": "connected"}])
        f = scan(d, {"srv": "always-on"}, 6, now)
        assert f == [], f
        ok += 1
        # 4b: coverage check — expected account の suffix server 欠け → 🟠、 両方あれば silent
        write("lap", now - 600, [{"label": "p.a1", "pid": "1", "last_status": "connected"}])
        write("srv", now - 600, [
            {"label": "p.a1", "pid": "2", "last_status": "connected"},
            {"label": "p.a2", "pid": "3", "last_status": "connected"}])
        f = scan(d, {}, 6, now, expect_accounts=["a1", "a2"])
        assert any("lap" in x and "a2" in x and "未開通" in x for x in f), f
        assert not any("srv" in x for x in f), f
        ok += 1
        # 4c: config dir の取り違え — ~/.claude-a2 が a1 の email → 🔴、 一致なら silent、 = 形式で明示も可
        beat = {"host": "srv", "epoch": now - 600,
                "servers": [{"label": "p.a1", "pid": "2", "last_status": "connected"},
                            {"label": "p.a2", "pid": "3", "last_status": "connected"}],
                "config_dirs": {"default": "a1@example.org", "a1": "a1@example.org", "a2": "a1@example.org"}}
        (d / "srv.json").write_text(json.dumps(beat))
        (d / "lap.json").unlink()
        f = scan(d, {}, 6, now, expect_accounts=["a1", "a2"])
        assert any("🔴" in x and "~/.claude-a2" in x and "a1@example.org" in x for x in f), f
        assert not any("~/.claude-a1 " in x for x in f), f
        f = scan(d, {}, 6, now, expect_accounts=["a1", "a2=a1@example.org"])
        assert not any("~/.claude-a2" in x for x in f), f
        beat["config_dirs"]["a2"] = "a2@example.org"
        (d / "srv.json").write_text(json.dumps(beat))
        f = scan(d, {}, 6, now, expect_accounts=["a1", "a2"])
        assert f == [], f
        ok += 1
        # 5: always-on で beat file 不在 → ℹ️
        f = scan(d, {"ghost": "always-on"}, 6, now)
        assert any("ghost" in x and "未開始" in x for x in f), f
        ok += 1
        # 6: loaded but pid 無し → 🟠
        write("lap", now - 600, [{"label": "x", "pid": None, "last_status": "connected"}])
        f = scan(d, {}, 6, now)
        assert any("process 無し" in x for x in f), f
        ok += 1
        # 7: desktop scheduled task enabled → flag ON なら 🔴、 OFF なら silent、 空 [] は常に silent
        beat = {"host": "lap", "epoch": now - 600,
                "servers": [{"label": "x", "pid": "1", "last_status": "connected"}],
                "desktop_scheduled_tasks": [
                    {"registry": "deadbeef", "enabled_ids": ["old-task-a", "old-task-b"]},
                    {"registry": "cafebabe", "enabled_ids": []}]}
        (d / "lap.json").write_text(json.dumps(beat))
        f = scan(d, {}, 6, now, warn_desktop_tasks=True)
        assert any("desktop scheduled task 2 件" in x and "old-task-a" in x and "🔴" in x for x in f), f
        assert not any("cafebabe" in x for x in f), f
        f = scan(d, {}, 6, now)
        assert f == [], f
        ok += 1
        # 8: field 不在 (旧 heartbeat) は flag ON でも silent
        write("lap", now - 600, [{"label": "x", "pid": "1", "last_status": "connected"}])
        f = scan(d, {}, 6, now, warn_desktop_tasks=True)
        assert f == [], f
        ok += 1

        # 9-13: inventory parity (= 2026-07-25 「1 台だけ account 未認証が 45 日 silent」 RCA)
        def winv(host, epoch, inv):
            j = {"host": host, "epoch": epoch,
                 "servers": [{"label": "x", "pid": "1", "last_status": "connected"}]}
            if inv is not None:
                j["inventories"] = inv
            (d / f"{host}.json").write_text(json.dumps(j))

        # 9: 片方だけ欠落 → 欠落側のみ 🟠 (= 実 incident の形)
        winv("srv", now - 600, {"accts": ["a1", "a2", "a3"]})
        winv("lap", now - 600, {"accts": ["a1", "a3"]})
        f = scan(d, {}, 6, now)
        assert any("lap" in x and "a2" in x and "🟠" in x for x in f), f
        assert not any(x.startswith("🟠 srv") for x in f), f
        ok += 1
        # 10: 一致 → silent
        winv("lap", now - 600, {"accts": ["a1", "a2", "a3"]})
        assert scan(d, {}, 6, now) == [], scan(d, {}, 6, now)
        ok += 1
        # 11: 片方が label 未報告 (旧 beat / 未設定) → 「全部欠落」 と誤判定せず silent
        winv("lap", now - 600, None)
        assert scan(d, {}, 6, now) == [], scan(d, {}, 6, now)
        ok += 1
        # 12: 報告マシンが 1 台だけ → 比較基準が無いので silent
        (d / "lap.json").unlink()
        assert scan(d, {}, 6, now) == [], scan(d, {}, 6, now)
        ok += 1
        # 13: stale な beat も比較に入る (= 寝ているマシンの欠落を起きている側から見る)
        winv("lap", now - 96 * 3600, {"accts": ["a1"]})
        f = scan(d, {}, 6, now)
        assert any("lap" in x and "a2" in x and "a3" in x and "96h" in x for x in f), f
        ok += 1
        # 16: job health (旧 beat は黙る / 関門が起動できない = 🔴 / engine が import できない = 🟠 / 他マシンの非 0 終了 = 🟠)
        beat_j = {"job_python_modules": ["yaml"], "jobs": [
            {"label": "j.gate", "python": "/x/python3", "python_runs": False, "python_ok": False,
             "bare_in_command": True, "bare_in_wrapper": False, "last_exit": 69},
            {"label": "j.wrap", "python": "/b/python3", "python_runs": True, "python_ok": False,
             "bare_in_command": False, "bare_in_wrapper": True, "last_exit": 0},
            {"label": "j.pick", "python": "/b/python3", "python_runs": True, "python_ok": False,
             "bare_in_command": False, "bare_in_wrapper": False, "last_exit": 0}]}
        fj = job_findings("host-a", beat_j, self_host="host-b")
        assert any(x.startswith("🔴 host-a: job j.gate") for x in fj), fj
        assert any(x.startswith("🟠 host-a: job j.wrap") and "yaml" in x for x in fj), fj
        assert any("j.gate の最後の終了コード = 69" in x for x in fj), fj
        assert not any("j.pick" in x for x in fj), "pick_python の wrapper は PATH の python3 の健康に依存しない"
        assert not any("終了コード" in x for x in job_findings("host-b", beat_j, self_host="host-b")), "自分の分は cron-health に任せる"
        assert job_findings("old", {"servers": []}) == [], "旧 beat は黙る"
        ok += 1
        # 17: 直近 run の log 末尾 (認証切れ = 原因つき 🟠 + config dir ごとに 🔴 1 行 / exit 0 に隠れた失敗 / 古い log は黙る)
        beat_a = {"jobs": [
            {"label": "j.a1", "last_exit": 1, "log_failure": "auth", "log_age_h": 2, "config_dir": "/c/.claude-x"},
            {"label": "j.a2", "last_exit": 0, "log_failure": "auth", "log_age_h": 5, "config_dir": "/c/.claude-x"},
            {"label": "j.old", "last_exit": 0, "log_failure": "auth", "log_age_h": 24 * 10, "config_dir": "/c/.claude-x"},
            {"label": "j.p", "last_exit": 1, "log_failure": "ptl", "log_age_h": 1},
            {"label": "j.ok", "last_exit": 0, "log_failure": None, "log_age_h": 1}]}
        fa = job_findings("host-a", beat_a, self_host="host-b")
        assert any("j.a1 の最後の終了コード = 1 — 直近 run の log 末尾 = Claude の認証切れ" in x for x in fa), fa
        assert any("j.a2 は終了コード 0 だが" in x for x in fa), fa
        assert not any("j.old" in x or "j.ok" in x for x in fa), fa
        assert any("j.p" in x and "Prompt is too long" in x for x in fa), fa
        assert [x for x in fa if x.startswith("🔴")] == [
            "🔴 host-a: Claude の認証切れで無人 job 2 本が失敗 (/c/.claude-x) = そのマシンの terminal で"
            " `CLAUDE_CONFIG_DIR=/c/.claude-x claude auth login` (再ログイン済みなら次の run で消える、"
            " scheduled-tasks.md#headless-auth-expiry)"], fa
        assert job_findings("host-b", beat_a, self_host="host-b") == [], "自分の分は cron-health に任せる"
        ok += 1
        # 19: 設定フォルダが切れた (writer の config_dir_auth) = 他のマシンの分だけ 🔴 + login の command / 旧 beat は黙る
        beat_c = {"config_dir_auth": {"x": {"dead": True, "last_probe": "2000-01-02 03:04", "last_probe_tag": "stale-check"},
                                      "y": {"dead": False, "last_probe": "2000-01-02 03:04"}}}
        fc = auth_findings("host-a", beat_c, self_host="host-b")
        assert len(fc) == 1 and fc[0].startswith("🔴 host-a: 設定フォルダ ~/.claude-x が切れた") and "stale-check" in fc[0] \
            and "CLAUDE_CONFIG_DIR=~/.claude-x claude auth login" in fc[0], fc
        assert auth_findings("host-b", beat_c, self_host="host-b") == [], "自分の分は check-desktop-logout-auth に任せる"
        assert auth_findings("old", {"servers": []}) == [], "旧 beat は黙る"
        beat_f = {"config_dir_auth": {"x": {"dead": True, "last_probe": "2000-01-09 03:04", "last_probe_tag": "stale-check",
                                            "first_fail": "2000-01-02 03:04"}}}
        ff = auth_findings("host-a", beat_f, self_host="host-b")
        assert len(ff) == 1 and "2000-01-02 03:04 の問い合わせから失敗が続き" in ff[0] and "2000-01-09" not in ff[0], ff
        ok += 1
        # 20: 予定の run が log に残っていない (本番ホストの関門つき claude -p だけ / 1 本 🟠・2 本以上 🔴 / since より前は見ない)
        import datetime as _dt
        T = lambda *a: _dt.datetime(*a).timestamp()
        bt = T(2030, 1, 5, 12, 0)
        cal = {"cal": [{"Hour": 7, "Minute": 30}]}
        jm = lambda lab, lm, **kw: dict({"label": lab, "last_exit": 0, "claude_p": True, "gated": True,
                                         "schedule": cal, "log_mtime": lm}, **kw)
        beat_m = {"host": "mini", "epoch": bt, "servers": [], "jobs": [
            jm("p.cron.a", T(2030, 1, 3, 7, 40)),
            jm("p.cron.b", None),
            jm("p.cron.ok", T(2030, 1, 5, 7, 50)),
            jm("p.cron.cmd", None, claude_p=False),
            jm("p.cron.free", None, gated=False)]}
        rt = {"host": "Mini.local", "since": T(2030, 1, 2, 16, 0)}
        fm = missed_run_findings("mini", beat_m, "always-on", rt)
        assert len(fm) == 1 and fm[0].startswith("🔴 mini:") and "3 本" in fm[0] and "a (予定 1/5 07:30" in fm[0] \
            and "b (予定 1/5 07:30、 log の最後 なし)" in fm[0] and "launchctl list | grep p.cron`" in fm[0] \
            and "free" in fm[0] and "ok (予定" not in fm[0] and "cmd" not in fm[0], fm
        fm1 = missed_run_findings("mini", dict(beat_m, jobs=beat_m["jobs"][:1]), "best-effort", rt)
        assert len(fm1) == 1 and fm1[0].startswith("🟠 mini:") and "1 本" in fm1[0], fm1
        assert missed_run_findings("other", dict(beat_m, host="other"), "always-on", rt) \
            and not any("a (" in x for x in missed_run_findings("other", dict(beat_m, host="other"), "always-on", rt)), \
            "本番でない機械の関門つき job は見ない (関門なしは always-on なら見る)"
        assert missed_run_findings("other", dict(beat_m, host="other"), "best-effort", rt) == []
        assert missed_run_findings("mini", beat_m, "always-on", dict(rt, since=T(2030, 1, 5, 8, 0))) \
            and "a (" not in missed_run_findings("mini", beat_m, "always-on", dict(rt, since=T(2030, 1, 5, 8, 0)))[0], \
            "本番になる前の予定は見ない"
        assert missed_run_findings("mini", beat_m, "always-on", None)[0].count("(予定") == 1, "台帳なし = 関門つきは見ない"
        # 本番ホストで最後の行が関門の待機 = 新しい log でも run ではない / 今走っている job には「実行中」
        bd = {"host": "mini", "epoch": bt, "jobs": [jm("p.cron.d", T(2030, 1, 5, 7, 30), log_deferred=True),
                                                    jm("p.cron.r", T(2030, 1, 4, 7, 50), running=True)]}
        fd = missed_run_findings("mini", bd, "always-on", rt)
        assert "d (予定 1/5 07:30、 log の最後 1/5 07:30、 最後の起動で関門が待機を選んだ)" in fd[0] \
            and "r (予定 1/5 07:30、 log の最後 1/4 07:50、 実行中)" in fd[0], fd
        assert missed_run_findings("other", dict(bd, host="other"), "always-on", rt) == [], "本番でない機械の待機は仕様"
        # 旧 writer の beat (欄なし) は、 この機械の同じ label の plist の予定で読む / log_age_h から log の時刻
        import plistlib
        pdir = d / "LaunchAgents"
        pdir.mkdir()
        with open(pdir / "p.cron.old.plist", "wb") as fh:
            plistlib.dump({"ProgramArguments": ["/bin/sh", "-c", 'python3 "routine-host-gate.py" r l && exec claude -p x'],
                           "StartCalendarInterval": {"Hour": 7, "Minute": 30}}, fh)
        old = {"host": "mini", "epoch": bt, "jobs": [{"label": "p.cron.old", "last_exit": 0, "log_age_h": 50.0}]}
        assert missed_run_findings("mini", old, "always-on", rt, pdir)[0].startswith("🟠 mini:"), "旧 beat は手元の plist で"
        assert missed_run_findings("mini", dict(old, jobs=[dict(old["jobs"][0], log_age_h=4.0)]), "always-on", rt, pdir) == []
        assert missed_run_findings("mini", old, "always-on", rt, None) == [], "plist も無ければ黙る"
        # scan: 台帳の host は always-on 扱い (heartbeat の停止も 🔴) + 予定の行が出る
        for f_ in d.glob("*.json"):
            f_.unlink()
        (d / "mini.json").write_text(json.dumps(dict(beat_m, epoch=now - 600)))
        fs = scan(d, {}, 6, now, routine=dict(rt, since=None))
        assert any("無人 job" in x for x in fs), fs
        (d / "mini.json").write_text(json.dumps(dict(beat_m, epoch=now - 10 * 3600)))
        assert any("🔴 mini (always-on)" in x for x in scan(d, {}, 6, now, routine=rt)), "本番ホストの停止"
        assert not any("mini" in x for x in scan(d, {}, 6, now)), "台帳なしは best-effort のまま"
        ok += 1
        # clone の同期 (repos.stopped / repos.sync): 分岐したまま 3 時間以上 = 🔴 / push されていない commit だけ = 🟠 /
        # 遅れたまま重なる未 commit 12 時間以上 = 🟠 / それより新しいものは出さない / stopped の repo は stopped の行だけ
        h = 3600
        sb = {"host": "mini", "epoch": now - 600, "repos": {"stopped": ["rw"], "sync": {
            "eo": {"ahead": 3, "ahead_since": now - 20 * h, "behind": 35},
            "un": {"ahead": 1, "ahead_since": now - 5 * h},
            "new": {"ahead": 1, "ahead_since": now - 600, "behind": 2},
            "pr": {"behind": 15, "wip_overlap": 1, "behind_since": now - 44 * h, "trial": "clean"},
            "pc": {"behind": 3, "wip_overlap": 1, "behind_since": now - 13 * h, "trial": "conflict"},
            "fresh_wip": {"behind": 1, "wip_overlap": 2, "behind_since": now - 2 * h},
            "rw": {"ahead": 2, "ahead_since": now - 50 * h, "behind": 1}}}}
        fs = sync_findings("mini", sb, now)
        assert any(x.startswith("🔴 mini: eo が upstream と分岐したまま 20 時間") and "手元にだけ在る commit 3" in x
                   and "#ordinary-divergence-replay" in x for x in fs), fs
        assert any(x.startswith("🟠 mini: un に push されていない commit 1 (最古 5 時間前)") for x in fs), fs
        assert any(x.startswith("🟠 mini: pr が 15 commit 遅れたまま最新化できない") and "遅れの最古 44 時間前" in x
                   and "#owner-gone-intersect-sync" in x and "[試走: 道具なら衝突も欠けも無く解ける見込み]" in x for x in fs), fs
        assert any(x.startswith("🟠 mini: pc が 3 commit") and "[試走: 道具では解けない = conflict]" in x for x in fs), fs
        assert any(x.startswith("🔴 mini: rw の追従が止まっている") for x in fs), fs
        assert not any(" new " in x or "mini: new" in x or "fresh_wip" in x for x in fs), f"新しいものは出さない: {fs}"
        assert sum("mini: rw" in x for x in fs) == 1, f"stopped の repo は stopped の行だけ: {fs}"
        assert len(fs) == 5, fs
        assert sync_findings("mini", {"host": "mini", "repos": {"error": "x"}}, now) == [], "集計の失敗だけの beat は黙る"
        assert sync_findings("mini", {"host": "mini"}, now) == [], "旧 beat (repos 欄なし) は黙る"
        for f_ in d.glob("*.json"):
            f_.unlink()
        (d / "mini.json").write_text(json.dumps(dict(sb, epoch=now - 2 * h)))
        fs = scan(d, {}, 6, now)
        assert any("mini: eo が upstream と分岐" in x and "[beat 2h 前]" in x for x in fs), fs
        (d / "mini.json").write_text(json.dumps(dict(sb, epoch=now - 10 * h)))
        assert not any("eo" in x for x in scan(d, {}, 6, now)), "寝ている machine の古い beat の同期の事実は出さない"
        ok += 1
    print(f"selftest: {ok}/21 PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir")
    ap.add_argument("--role", action="append", default=[])
    ap.add_argument("--stale-hours", type=float, default=6)
    ap.add_argument("--expect-account", action="append", default=[])
    ap.add_argument("--warn-desktop-tasks", action="store_true",
                    help="enabled な desktop scheduled task を 🔴 surface (= 無人ジョブ launchd-only 方針のマシン向け opt-in)")
    ap.add_argument("--routine-ledger",
                    help="routine-host-gate.py の台帳 (= 本番ホスト。 予定の run が log に残っているかを見る、 docstring)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return
    if not args.dir:
        sys.exit(0)
    roles = {}
    for r in args.role:
        if "=" in r:
            h, v = r.split("=", 1)
            roles[h] = v
    dir_ = Path(args.dir).expanduser()
    if not dir_.is_dir():
        sys.exit(0)  # fleet 未開始 = silent (fail-open)
    try:
        import socket
        me = socket.gethostname().split(".")[0]
        routine = load_routine(args.routine_ledger) if args.routine_ledger else None
        findings = scan(dir_, roles, args.stale_hours, expect_accounts=args.expect_account,
                        warn_desktop_tasks=args.warn_desktop_tasks, self_host=me,
                        routine=routine, plist_dir=Path.home() / "Library/LaunchAgents")
    except Exception:
        sys.exit(0)
    if findings:
        print("🛰 fleet heartbeat findings (= cross-machine 状態、 multi-machine-state.md#fleet-heartbeat):")
        for x in findings:
            print(f"  {x}")
    sys.exit(0)


if __name__ == "__main__":
    main()
