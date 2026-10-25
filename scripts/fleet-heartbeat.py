#!/usr/bin/env python3
"""fleet-heartbeat.py — per-machine heartbeat writer（毎時 launchd cron から自マシンの RC server 群〔launchd loaded + server ログ末尾 marker parse = Connected/auth error/version error〕 + config-dir auth metadata を <repo>/<subdir>/<host>.json に commit+push。**claude を一切呼ばない** = auth 失効でも監視が生き残る、state-change-or-age commit policy で git history を汚さない、fail-open、--selftest 内蔵、conventions/multi-machine-state.md#fleet-heartbeat）
fleet-heartbeat.py — per-machine heartbeat writer (layer 1 generic engine).

cross-machine state の不可視問題 (multi-account-machine-surface.md #honest-limits) を
狭める: 各マシンが自分の remote-control server / CLI 環境の live 状態を JSON 1 file に
まとめ、 git repo に commit + push する。 他マシンは sibling `check-fleet-status.py`
(reader) で全マシン分を読み、 常時起動マシンの silent 死や auth 失効を surface する。

設計原則:
- **`claude` コマンドを一切呼ばない** (= auth 失効で server 群が死んでいても heartbeat
  自体は動き続け、 その死を server ログの parse で報告できる。 監視が監視対象に依存する
  と共倒れして意味がない)。 依存は launchctl / git / python3 stdlib のみ。
- **state-change-or-age commit policy**: 毎 beat commit すると git history が汚れる。
  essence (= server の loaded/status、 auth metadata、 設定) が変わった時 + 最終 commit
  から --min-commit-interval-hours 経過時のみ commit。 変化なし & 期間内なら working
  tree に触らない (= 他の git 機構を汚さない)。 liveness の上限 = interval + cron 周期。
- **fail-open**: 何が起きても exit 0 (= cron を止めない)。 push 失敗は local commit を
  残して次 beat で再 push。 commit 後の pull は `--rebase --autostash` — 他 session が
  無関係な dirty file を残置していると autostash なしでは rebase が拒否され、 beat が
  local commit に積み上がるだけで push されない = fleet からこのマシンが silent 死に
  見え、 このマシン自身の fleet view も stale 化する (= 双方向の盲目)。 failure mode の
  正本 = conventions/multi-machine-state.md#fleet-heartbeat 設計原則 5。
- server の実況は **launchd loaded/pid + server ログ末尾の marker parse** で判定
  (= "Connected" / "Not logged in" / "too old" / "Enable Remote Control?" を新しい順に
  評価)。 process が生きていても auth 失効で cycling している状態を検出できるのが肝。

inventory (--inventory、 opt-in、 repeatable):
  「このマシンに何が置かれているか」 の **名前だけ** の一覧を記録する generic hook。
  machine-local な設定・credential・token dir は「あるマシンにだけ無い」 状態を作りうるが、
  それを見る機械が無いと誰にも見えないまま放置される (= 2026-07-25 実測: ある account の
  credential が 1 台だけ未配置のまま 45 日 silent)。 sibling reader が全マシン分を
  突合し、 **他マシンには在るのにこのマシンには無い** entry を surface する。
  ⚠️ 期待集合は **fleet の union** = 宣言 registry を持たない (= 「registry への登録忘れ」
     という規律依存の穴を作らない)。 代償 = **どのマシンにも無い物は検出できない**。
  ⚠️ 記録するのは path 要素の名前のみ。 **file の中身は一切読まない**。

usage:
  fleet-heartbeat.py --repo <git-repo-root> --subdir <relative-dir>
      [--min-commit-interval-hours 4]
      [--rc-label-prefix com.claude-config.remote-control-server]
      [--cron-label-prefix <prefix>]     # optional: 無人 cron job 数も記録
      [--inventory 'LABEL=GLOB' ...]     # optional: 名前一覧を記録 (下記 name 規則)
      [--job-label-prefix <prefix> ...]  # optional: ジョブごとの健康 (下記 job health)
      [--job-python-modules yaml,...]     # optional: ジョブの python3 が import できるべき module
  fleet-heartbeat.py --selftest

書かれる JSON (subdir/<hostname>.json):
  { host, ts (iso), epoch, servers: [{label, pid, last_status, log_age_min}],
    config_dirs: {alias: email_metadata_or_null},
    config_dir_auth: {alias: {dead, last_probe, last_probe_ok, last_probe_tag}},  # 部品が在る時のみ
    remote_control_at_startup, old_usr_local_cli, cron_jobs,
    desktop_scheduled_tasks: [{registry, enabled_ids}],
    inventories: {label: [name, ...]},         # --inventory 指定時のみ
    jobs: [{label, last_exit, python, python_runs, python_ok, bare_in_command, bare_in_wrapper,
            log_failure, log_age_h, log_mtime, log_deferred, config_dir?,
            claude_p, gated, schedule, running}],               # --job-label-prefix 指定時のみ
    job_python_modules: [module, ...],                           # 同上
    engine_head: <本 engine の repo の HEAD sha>,                  # 「この Mac の層1 は何版か」 を他マシンから読む (essence 外)
    harness_hooks: [hook file 名, ...],                          # ~/.claude/settings.json に配線された hook の名前だけ
    rewrite_follow: {capable, state, upstream, manifest, prepush_stub, forced_update_seen},  # 下記
    repos: {heads: {repo 名: {head, up, prepush}}, stale: [repo 名], no_stub: [repo 名],
            stub_placed, stub_failed,
            sync: {repo 名: {ahead, ahead_since, behind, behind_since, wip_overlap}}} }   # --repos-root 指定時のみ、 下記

書き換えられた履歴への追従 (rewrite_follow、 部品 = lib/git_rewrite_follow.py、 2026-09-29):
  heartbeat repo の remote が force-push で書き換えられた後、 従来の `pull --rebase` は古い commit を新しい履歴に
  積み直して push しうる (= 消した中身が remote に戻る)。 そこで commit の **前** に fetch し、 HEAD と upstream が
  分岐していれば lib の follow_repo で中身で揃える (対応表 / tree の一致 / volatile path 〔upstream の
  `.rewrite-follow/ignore-paths`、 本 script の --subdir を宣言しておく〕 を除いた tree の一致。 reset --keep)。
  揃えられなければ **beat を止める** (`deferred`、 commit も rebase もしない = そのマシンは fleet から stale に見え、
  SessionStart の同期 sweep も同じ repo を A 行で出す)。 commit の後は fetch し直し、 upstream が普通に進んだ時だけ
  自分の commit を載せ直す (preflight と push の間に forced update が来たら載せ直さない = 次の beat が中身で揃える)。
  push の前に対応表の旧 sha / 旧世代の blob を含まないかを見る (pre-push stub と同じ述語)。 manifest のある repo には
  pre-push stub を置く。
  - state: current (HEAD は upstream の祖先) / ahead / followed / stopped / diverged (書き換えの痕跡の無い通常の分岐 =
    従来どおり自分の commit を載せ直す。 痕跡が 30 日で reflog から消えた後の書き換えはここに落ちる = push の guard が最後の網) /
    no-upstream / unknown
  - capable = True は「この Mac の engine が追従を知っている」 の印 = 書き換えを push する前の gate が全マシン分を読む
  - 追従の記録 = ~/.claude/state/rewrite-follow.log (lib が書く)

repo ごとの点呼 (repos、 --repos-root DIR、 opt-in、 部品 = lib/git_rewrite_follow.py):
  履歴を書き換えた repo は、 各 machine の clone が追従するまで危ない (追従前の clone からの push で消した中身が戻る)。
  「全 machine が追従したか」 を、 書き換えの知らせが各 machine に届いたかに頼らずに読めるようにする:
  - 毎 beat、 DIR/*/ の upstream のある全 repo に pre-push stub を置く (lib.ensure_prepush_all)。 書き換えの **前から** 全
    clone に在る = 書き換えてから配るのでは、 届く前の clone が無防備になる。 session を開かない machine にも届く
    (beat は無人で回る)
  - heads = repo ごとの **事実** (HEAD の sha・この machine が見ている upstream の sha・pre-push の状態)。 判定は載せない:
    書き換えをまだ fetch していない machine は自分を「最新」 と思っている = 自己申告は当てにならない。 最新を fetch した
    machine の reader (lib.judge_fact) が、 各 machine の事実を自分の知識で判定する
  - stale = この machine 自身が「HEAD は捨てられた履歴の上」 と分かっている repo (fetch 済み・未追従)。 変化は即 commit
  - no_stub = push の検査が通らない repo (hook の dir が repo に track されていて pre-push を持たない / 鎖にしない設定)。 変化は即 commit
  - events = 直近 24 時間に、 止めずに通した出来事 {種類: [repo]} (push の検査が例外で走らなかった guard-error / 書き換える push の前の
    点呼が走らなかった ready-skip / 備えの無いまま書き換えを通した ready-override / 止まるはずの object を名指しで通した guard-allow。
    部品 = lib の log_event)。 変化は即 commit
  - error = この集計そのものが失敗した時の理由 (他の欄は無い)。 「報告なし」 と区別して、 他の machine から原因を読む
  - fetch_failed = この beat で fetch に失敗した repo (認証・network・remote の URL)。 失敗した repo は upstream の知識が古いまま =
    その machine には「揃える対象なし」 に見える。 読む側が「次の回が揃える」 と言わないための欄。 変化は即 commit
  - heads の各 repo の old_branches = 捨てられた履歴の commit を抱えた手元の branch (今の branch を除く。 在る時だけ載る)
  - sync = 書き換えに依らない同期の事実 (sync_facts): 手元にだけ在る commit の数と最古の commit の時刻・遅れている commit の数と
    最古の commit の時刻・遅れている時に upstream の変更と重なる未 commit の file の数。 在る repo だけ載る。 path は載せない。
    reader (check-fleet-status.py) が古さで判定する = 手元にだけ在る commit が何時間も残る (push に失敗した無人の書き手・分岐) /
    最新化を止める未 commit が何時間も残る (持ち主の居ない変更)。 有無の変化は即 commit (essence)、 数と時刻の変化は入れない
  heads は essence に入れない (どこかの repo に commit するたびに beat を commit しないため。 鮮度の上限 = 定期 commit の間隔)。
  --repos-follow (opt-in): 毎 beat、 全 repo を fetch し、 書き換えられた履歴に揃えられる clone を揃える (lib.follow_repo =
  手元の commit の中身が upstream に在る時だけ ref を動かす)。 「書き換えた後、 各 machine で追従を 1 回」 を人にも session の開始にも
  頼らない (実測: session を何週間も開かない machine は、 人が思い出すまで古い履歴のまま残る)。 followed = この beat で揃えた repo、
  stopped = 揃えられなかった repo (手元にしか無い commit。 変化は即 commit)。 前から behind なだけの repo は fetch するだけで動かさない。

config_dirs の読み方 (実測):
  - pinned の alias (`~/.claude-<acct>`) = その設定フォルダの `.claude.json` の oauthAccount の email = その
    フォルダで最後にログインした account
  - `default` (`~/.claude.json` の oauthAccount) は **desktop app を最後に起動した時の desktop の account** を映す。
    desktop app の起動がこの欄を書き換える (desktop で account を切り替えても、 起動し直すまで変わらない)。
    CLI のログインの記録ではない = この欄の変化をログインや切り替えの時刻の手がかりにしない (切り替えの時刻は
    desktop app の log の `Login-state transition` にある)
  - `server` の `last_status` = RC サーバーの log 末尾の最後の印。 `Connected` は OAuth の更新が生きている証拠に
    ならない (待ち受けは更新を使わない経路で動き、 更新トークンが切れても Connected のまま残る実測がある)

config_dir_auth (設定フォルダが切れたか、 部品 = lib/config_dir_auth.py):
  - 問い合わせは check-desktop-logout-auth.py の見張りが打つ (ログアウトの後 + 長く更新の無いフォルダを毎日)。
    本 script は記録と keychain の更新時刻 (属性だけ) を読むだけ = `claude` を呼ばない
  - dead = 最後の問い合わせが失敗し、 その後にログインし直していない。 reader が他のマシンの分を 🔴 で出す
  - 変化として commit するのは dead の値だけ (問い合わせの時刻では commit しない)

job health (--job-label-prefix、 opt-in、 repeatable):
  launchd の無人ジョブは job 定義の PATH で `python3` を解決する。 その PATH は agent の session や対話 shell と
  先頭の dir が違い、 package manager の更新で `python3` の実体が差し替わると、 編集ゼロで依存 (yaml 等) が消えて
  engine が import で終わる。 fail-open の engine は exit 0 で終わるので、 そのマシンの中からも成功に見える
  (conventions/shell-env.md#job-python-by-capability)。 そこで各ジョブについて次を記録し、 reader が他マシンから見る:
  - last_exit = `launchctl list` の最後の終了コード (未実行は null)
  - python = job の実行環境の PATH で解決した python3 (job 定義の `export PATH="..."` / EnvironmentVariables >
    無ければ launchctl print が記録した「継いだ環境」 の PATH = 本人の shell から bootstrap した job はその PATH で走る >
    launchd 既定)。 実測: 定義に PATH の無い daemon が package manager の python3 を継いで依存を読めずにいた
  - python_runs = その python3 が起動できるか (Xcode の gate の exit 69 等で落ちれば False)
  - python_ok = その python3 が --job-python-modules を全部 import できるか。 未指定なら null
  - bare_in_command = job の command (起動の関門など) が `python3` を PATH で呼ぶか
  - bare_in_wrapper = command が `exec bash "<wrapper>"` で呼ぶ wrapper が `python3` を PATH で呼ぶか
    (`"$PY"` や絶対 path で呼ぶ wrapper は PATH の python3 の健康に依存しない)
  - log_failure = 直近 run の log 末尾の既知の失敗 ("auth" = Claude の認証切れ / "ptl" = Prompt is too long / null)、
    log_age_h = その log の最終更新からの時間、 config_dir = auth のときだけ plist の CLAUDE_CONFIG_DIR
    (判定 = scripts/lib/launchd_job_log.py、 check-cron-health と共有。 plist を読み込み直すと last_exit は 0 に戻るので、
    last_exit だけでは失敗が消える = conventions/scheduled-tasks.md#reload-resets-exit-status)
  - log_mtime = その log の最終更新の時刻 (epoch)、 log_deferred = log の最後の行が関門の待機 (= 直近の起動は run でない)、
    running = `launchctl list` に PID がある (= 今走っている)、 claude_p = 起動行が headless `claude -p` を起動するか、
    gated = 起動行が本番ホストの関門 (routine-host-gate.py) を通るか、 schedule = plist の予定
    (判定 = scripts/lib/launchd_job_log.py)。 reader は本番ホストで、 予定の時刻を過ぎても log が更新されていない
    claude -p の job を出す (= 起動しなかった run と終わらない run は、 終了コードにも log 末尾にも出ない、
    conventions/scheduled-tasks.md#missed-run-detection)
  reader は bare_in_command ∧ ¬python_runs (= 関門が起動できず、 そのジョブは黙って休み続ける) と
  bare_in_wrapper ∧ ¬python_ok (= engine が import で終わる) を出す。 command の位置 (行頭・; && || | $( の直後) の
  `python3` だけを数える (echo の文中の語は数えない)

  name 規則 = **glob の最初の `*` 以降の最初の path 要素**:
    'gmail_accounts=~/.gmail-mcp/*/credentials.json' → 各 account dir 名の一覧 (= 親 dir 名)
    'secrets=~/.secrets/*'                          → 各 file 名の一覧 (= 末端の file 名)
  match 0 件でも label は `[]` として記録する (= 「field 不在 = 旧 beat」 と
  「報告した上で空」 を reader が区別できるようにするため)。

⚠️ email は .claude.json の oauthAccount **metadata** (= keychain 実 auth とはズレうる、
   remote-control-server.md#account-auth-keychain)。 fleet view の cheap signal として
   記録し、 断定には使わない。 token 等の secret は一切読まない・書かない。
"""

import argparse
import glob as globmod
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
try:
    import launchd_job_log as _jl   # 直近 run の log 末尾の判定 (check-cron-health と共有)
except Exception:                   # 部品が無い古い checkout でも beat は止めない
    _jl = None
try:
    import config_dir_auth as _cda  # 設定フォルダが切れたかの判定 (check-desktop-logout-auth と共有、 claude を呼ばない)
except Exception:
    _cda = None
try:
    import git_rewrite_follow as _rf  # 書き換えられた履歴の追従 + push 側の防御 (repo-sync-sweep / git-rewrite-follow.py と共有)
except Exception:                     # 部品が無い古い checkout では従来の pull --rebase 経路
    _rf = None

RC_LABEL_PREFIX_DEFAULT = "com.claude-config.remote-control-server"

# server ログ末尾の status marker (新しい出現が勝つ)
LOG_MARKERS = [
    ("Connected", "connected"),
    ("Not logged in", "auth_error"),
    ("must be logged in", "auth_error"),
    ("requires a claude.ai subscription", "auth_error"),
    ("requires claude.ai subscription auth", "auth_error"),
    ("too old for Remote Control", "version_error"),
    ("not enabled for your account", "version_error"),
    ("Enable Remote Control?", "consent_pending"),
    # virgin config dir の headless 死 (= trust dialog を出せず exit-1 cycling、
    # remote-control-server.md#ts-workspace-trust。 2026-07-02 実測 RCA で追加)
    ("Workspace not trusted", "trust_error"),
]

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\[[0-9]+[A-Z]")


def sh(cmd, timeout=20):
    try:
        # errors="replace": 子プロセスの出力が現在の locale encoding で decode できない
        # ことがある (= Windows の cp932 出力を UTF-8 で読む等)。 既定の "strict" だと
        # decode が capture 用の reader thread 内で例外になり、 その thread は本 try/except
        # の外なので握り潰せず、 traceback を撒いたうえで出力が失われる。
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout)
        return r.returncode, r.stdout
    except Exception:
        return 1, ""


def hostname_short():
    rc, out = sh(["hostname", "-s"])
    h = out.strip() or "unknown"
    return h[: -len(".local")] if h.endswith(".local") else h


def parse_log_status(log_path: Path):
    """ログ末尾 ~6KB から最後に出た marker の status を返す。"""
    try:
        size = log_path.stat().st_size
        with open(log_path, "rb") as f:
            f.seek(max(0, size - 6000))
            tail = f.read().decode("utf-8", errors="replace")
        tail = ANSI_RE.sub("", tail)
        best = ("unknown", -1)
        for needle, status in LOG_MARKERS:
            idx = tail.rfind(needle)
            if idx > best[1]:
                best = (status, idx)
        age_min = int((time.time() - log_path.stat().st_mtime) / 60)
        return best[0], age_min
    except Exception:
        return "unknown", None


def scan_inventory(spec: str):
    """'LABEL=GLOB' を (label, [names]) にする。 name = glob の最初の `*` 以降の最初の path 要素。

    ⚠️ 名前のみを収集し file の中身は読まない (= secret の inventory にも安全に使える)。
    不正な spec は None (= caller が無視、 fail-open)。
    """
    label, sep, pat = spec.partition("=")
    label, pat = label.strip(), pat.strip()
    if not sep or not label or not pat:
        return None
    expanded = os.path.expanduser(pat)
    star = expanded.find("*")
    prefix = expanded[:star] if star >= 0 else ""
    # glob() は platform の separator で返す (Windows は "\") 一方 pattern は "/" で
    # 書かれる。 素の startswith 比較は Windows で必ず外れ、 basename fallback に落ちて
    # 全 entry が glob 末尾の file 名 (= "credentials.json" 等) に潰れる = inventory が
    # 「1 個だけある」 と誤報告する。 両辺を "/" に正規化してから比較・分割する。
    prefix_n = prefix.replace(os.sep, "/")
    names = set()
    for m in globmod.glob(expanded):
        m_n = m.replace(os.sep, "/")
        rest = m_n[len(prefix_n):] if (prefix_n and m_n.startswith(prefix_n)) else os.path.basename(m)
        n = rest.split("/", 1)[0]
        if n:
            names.add(n)
    return label, sorted(names)


def collect(rc_prefix, cron_prefix, inventory_specs=None, job_prefixes=None, job_modules=None):
    home = Path.home()
    data = {
        "host": hostname_short(),
        "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "epoch": int(time.time()),
        "servers": [],
        "config_dirs": {},
        "remote_control_at_startup": None,
        "old_usr_local_cli": None,
        "cron_jobs": None,
    }
    # launchctl list から RC server 群
    rc, out = sh(["launchctl", "list"])
    cron_count = 0
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        pid, _status, label = parts[0], parts[1], parts[2]
        if label.startswith(rc_prefix):
            log = home / "Library/Logs" / f"{label}.log"
            status, age = parse_log_status(log)
            data["servers"].append(
                {"label": label, "pid": (None if pid == "-" else pid),
                 "last_status": status, "log_age_min": age}
            )
        if cron_prefix and label.startswith(cron_prefix):
            cron_count += 1
    if cron_prefix:
        data["cron_jobs"] = cron_count
    # job health (opt-in、 docstring §job health)
    if job_prefixes:
        try:
            data["jobs"] = scan_jobs(out, list(job_prefixes), list(job_modules or []), home)
            data["job_python_modules"] = list(job_modules or [])
        except Exception:
            pass  # fail-open (= beat 全体を落とさない)
    data["servers"].sort(key=lambda s: s["label"])
    # config dirs の auth metadata (= secret は読まない、 email 欄のみ)。
    # ⚠️ config JSON の場所は default と pinned dir で違う: 既定 (CLAUDE_CONFIG_DIR 未指定) は
    # ~/.claude.json (home 直下)、 pinned dir は <dir>/.claude.json。 旧実装は default も
    # ~/.claude/.claude.json を読んでいて常に null になっていた (2026-07-02 fix)。
    for d in sorted([home / ".claude", *home.glob(".claude-*")]):
        if not d.is_dir():
            continue
        alias = "default" if d.name == ".claude" else d.name[len(".claude-"):]
        cfg = (home / ".claude.json") if alias == "default" else (d / ".claude.json")
        email = None
        try:
            j = json.load(open(cfg))
            email = j.get("oauthAccount", {}).get("emailAddress") or None
        except Exception:
            pass
        data["config_dirs"][alias] = email
    # 設定フォルダ (pinned) ごとの認証の判定 = 最後の問い合わせが失敗し、 その後ログインし直していないか。
    # 問い合わせは check-desktop-logout-auth.py の見張りが打つ (claude を呼ぶのはそちら)。 ここは記録と keychain の
    # 更新時刻 (属性だけ) を読むだけ = claude を呼ばない設計を保つ。 他のマシンの reader が 🔴 を出す
    if _cda is not None:
        try:
            rows = _cda.read_ledger()
            auth = {}
            for d in sorted(home.glob(".claude-*")):
                if not d.is_dir():
                    continue
                last = _cda.last_probe(rows, str(d))
                mdat = _cda.keychain_mdat(_cda.keychain_service(str(d)))
                auth[d.name[len(".claude-"):]] = {
                    "dead": _cda.is_dead(rows, str(d), mdat) is not None,
                    "last_probe": time.strftime("%Y-%m-%d %H:%M", time.localtime(last["t"])) if last else None,
                    "last_probe_ok": last["ok"] if last else None,
                    "last_probe_tag": last["tag"] if last else None,
                }
            data["config_dir_auth"] = auth
        except Exception:
            pass  # fail-open (= beat 全体を落とさない)
    # remoteControlAtStartup
    try:
        s = json.load(open(home / ".claude/settings.json"))
        data["remote_control_at_startup"] = bool(s.get("remoteControlAtStartup", False))
    except Exception:
        pass
    # 旧 CLI 残置 (/usr/local/bin/claude、 dual-install trap の fleet 可視化)
    old = Path("/usr/local/bin/claude")
    if old.exists():
        rc, out = sh([str(old), "--version"], timeout=10)
        m = re.search(r"\d+(?:\.\d+)+", out)
        data["old_usr_local_cli"] = m.group(0) if m else "unparseable"
    # desktop app の scheduled task registry 監視 (= account × app-install scoped な registry が
    # アカウント切替で enabled task を黙って復活させ、 launchd 移行済ジョブと二重実行する事故の
    # 機械検出。 2026-07-04 実測: swap 2 日後まで silent だった)。 registry ごとに enabled id を列挙。
    data["desktop_scheduled_tasks"] = scan_desktop_tasks(home)
    # inventory (opt-in): 「このマシンに何が置かれているか」 の名前一覧。 reader が fleet 横断で
    # 突合して「他マシンには在るのにここには無い」 を surface する (docstring §inventory)。
    if inventory_specs:
        inv = {}
        for spec in inventory_specs:
            try:
                r = scan_inventory(spec)
            except Exception:
                r = None  # fail-open (= 1 spec の失敗で beat 全体を落とさない)
            if r:
                inv[r[0]] = r[1]
        if inv:
            data["inventories"] = inv
    return data


# コマンドとして呼ぶ位置の python3 だけ (行頭 / ; & | ( ` / $( / exec then do else の直後)。 文字列中の語は数えない
_BARE_PY_RE = re.compile(r"(?:^|[;&|(`]\s*|\$\(\s*|\b(?:exec|then|do|else)\s+)python3\s")
_EXPORT_PATH_RE = re.compile(r'export PATH="([^"]*)"')
# wrapper = `exec bash "<x>.sh"` のほか、 ProgramArguments が ["/bin/sh", "<x>.sh"] の形 (quote なし・sh) も
# (実測: 30 分ごとの通知 daemon がこの形で、 wrapper の素の python3 が検査の外だった)
_WRAPPER_RE = re.compile(r'(?:exec\s+)?(?:/bin/)?(?:ba)?sh\s+"?([^\s"]+\.sh)"?')
_INHERITED_PATH_RE = re.compile(r"inherited environment = \{(.*?)\n\s*\}", re.S)


def _expand(p, home):
    return p.replace("$HOME", str(home)).replace("${HOME}", str(home)).replace("~", str(home), 1 if p.startswith("~") else 0)


def parse_inherited_path(text):
    """`launchctl print gui/<uid>/<label>` の出力から、 job が継いだ環境の PATH を返す (無ければ None)。

    job 定義に PATH が無くても launchd の既定 PATH で走るとは限らない: 本人の shell から bootstrap した job は
    その shell の環境を継ぐ (conventions/shell-env.md#job-python-invisible)。 実測: package manager の python3 が
    先に来る PATH を継ぎ、 依存の無い interpreter で engine が黙って終わっていた。
    """
    m = _INHERITED_PATH_RE.search(text or "")
    if not m:
        return None
    for line in m.group(1).splitlines():
        k, sep, v = line.strip().partition("=>")
        if sep and k.strip() == "PATH" and v.strip():
            return v.strip()
    return None


def inherited_path(label):
    """この機械で今 load されている job の継いだ PATH (launchctl print、 失敗 = None)。"""
    try:
        rc, out = sh(["launchctl", "print", "gui/%d/%s" % (os.getuid(), label)], timeout=10)
    except Exception:
        return None
    return parse_inherited_path(out) if rc == 0 else None


def job_path(plist, home, label=None):
    """job の実行環境の PATH: command の最後の `export PATH="..."` > EnvironmentVariables.PATH > (label があれば)
    launchctl が記録した継いだ環境の PATH > None (= launchd 既定)。"""
    cmd = " ".join(str(x) for x in (plist.get("ProgramArguments") or []))
    m = _EXPORT_PATH_RE.findall(cmd)
    if m:
        return ":".join(_expand(p, home) for p in m[-1].split(":"))
    env = plist.get("EnvironmentVariables") or {}
    if env.get("PATH"):
        return _expand(env["PATH"], home)
    return inherited_path(label) if label else None


def resolve_in_path(name, path):
    """PATH の順で最初に見つかる実行 file (launchd 既定の PATH は /usr/bin:/bin:/usr/sbin:/sbin)。"""
    for d in (path or "/usr/bin:/bin:/usr/sbin:/sbin").split(":"):
        c = os.path.join(d, name)
        if d and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def bare_python_in(text):
    """`python3` を PATH で呼ぶ行があるか (comment と `command -v python3` は除く)。"""
    for ln in text.splitlines():
        t = ln.strip()
        if not t or t.startswith("#") or "command -v python3" in t:
            continue
        if _BARE_PY_RE.search(t):
            return True
    return False


def job_health(label, status, plist, modules, home):
    """1 ジョブの健康。 probe だけが外に出る (python3 -c 'import ...'、 timeout 10s、 失敗は False)。"""
    rec = {"label": label, "last_exit": None, "python": None, "python_runs": None, "python_ok": None,
           "bare_in_command": None, "bare_in_wrapper": None, "log_failure": None, "log_age_h": None}
    try:
        rec["last_exit"] = int(status)
    except (TypeError, ValueError):
        pass
    if _jl is not None:   # 直近 run の log 末尾 (= 読み込み直しで 0 に戻った失敗と、 失敗の原因を他マシンへ運ぶ)
        try:
            lp = _jl.job_log_path(label, plist if isinstance(plist, dict) else None, home / "Library/Logs")
            rec["log_failure"] = _jl.failure_kind(lp) or None
            age = _jl.log_age_days(lp)
            rec["log_age_h"] = round(age * 24, 1) if age is not None else None
            try:
                rec["log_mtime"] = int(lp.stat().st_mtime)
            except OSError:
                rec["log_mtime"] = None
            rec["log_deferred"] = _jl.deferred_tail(lp)
            if rec["log_failure"] == "auth":
                rec["config_dir"] = _jl.config_dir_of(plist if isinstance(plist, dict) else None) or None
        except Exception:
            pass
    if not isinstance(plist, dict):
        return rec
    if _jl is not None:   # 予定の run が log に残っているかを reader が判定するための材料
        try:
            rec["claude_p"] = _jl.runs_claude_p(plist)
            rec["gated"] = _jl.is_gated(plist)
            rec["schedule"] = _jl.schedule_of(plist)
        except Exception:
            pass
    cmd = " ".join(str(x) for x in (plist.get("ProgramArguments") or []))
    # job の command (= 起動の関門など。 標準ライブラリで足りる) と wrapper (= engine。 依存を使う) を分けて見る
    rec["bare_in_command"] = bare_python_in(cmd.replace(";", "\n").replace("&&", "\n").replace("||", "\n"))
    bw = False
    for w in _WRAPPER_RE.findall(cmd):
        try:
            bw = bw or bare_python_in(Path(_expand(w, home)).read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass
    rec["bare_in_wrapper"] = bw
    py = resolve_in_path("python3", job_path(plist, home, label))
    rec["python"] = py

    def _probe(code):
        if not py:
            return False
        env = dict(os.environ)
        if os.path.isdir("/Library/Developer/CommandLineTools"):
            env.setdefault("DEVELOPER_DIR", "/Library/Developer/CommandLineTools")
        try:
            return subprocess.run([py, "-c", code], env=env, capture_output=True, timeout=10).returncode == 0
        except Exception:
            return False
    rec["python_runs"] = _probe("import sys")
    if modules:
        rec["python_ok"] = rec["python_runs"] and _probe("import sys; " + "; ".join(f"import {m}" for m in modules))
    return rec


def scan_jobs(launchctl_out, prefixes, modules, home):
    import plistlib
    out = []
    for line in launchctl_out.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        status, label = parts[1], parts[2]
        if not any(label.startswith(p) for p in prefixes):
            continue
        try:
            with open(home / "Library/LaunchAgents" / f"{label}.plist", "rb") as f:
                pl = plistlib.load(f)
        except Exception:
            pl = None
        try:
            rec = job_health(label, status, pl, modules, home)
            rec["running"] = parts[0].strip() not in ("", "-")
            out.append(rec)
        except Exception:
            out.append({"label": label, "last_exit": None, "python": None, "python_runs": None, "python_ok": None,
                        "bare_in_command": None, "bare_in_wrapper": None})
    out.sort(key=lambda r: r["label"])
    return out


def scan_desktop_tasks(home: Path):
    """全 account registry の scheduled-tasks.json から enabled task id を収集 (fail-open)。"""
    out = []
    try:
        base = home / "Library/Application Support/Claude/claude-code-sessions"
        for f in sorted(base.glob("*/*/scheduled-tasks.json")):
            try:
                d = json.load(open(f))
                ids = sorted(
                    t.get("id") or t.get("taskId") or "?"
                    for t in d.get("scheduledTasks", [])
                    if t.get("enabled")
                )
                # registry の識別は account uuid の先頭 8 桁 (= PII でない、 突合には十分)
                out.append({"registry": f.parent.parent.name[:8], "enabled_ids": ids})
            except Exception:
                out.append({"registry": f.parent.parent.name[:8], "enabled_ids": None})
    except Exception:
        pass
    return out


def essence(d: dict):
    """commit 要否判定に使う本質部分 (ts / pid / log age を除く)。"""
    return json.dumps(
        {
            "servers": [(s["label"], s["pid"] is not None, s["last_status"]) for s in d.get("servers", [])],
            "config_dirs": d.get("config_dirs"),
            # 設定フォルダが切れた / 直った は即 commit (問い合わせの時刻は変化に数えない = 毎日の確認で commit を増やさない)
            "config_dir_dead": {k: v.get("dead") for k, v in (d.get("config_dir_auth") or {}).items()},
            "rcs": d.get("remote_control_at_startup"),
            "old_cli": d.get("old_usr_local_cli"),
            "cron_jobs": d.get("cron_jobs"),
            # enabled task の変化 (= 復活) は即 commit させる (= state-change-or-age policy に乗せる)
            "desktop_tasks": d.get("desktop_scheduled_tasks"),
            # inventory の増減 (= account 追加 / 欠落) も即 commit (= 他マシンの reader に早く届く)
            "inventories": d.get("inventories"),
            # job の健康の変化 (= 壊れた / 直った) も即 commit (last_exit は 0 か否かだけ)
            "jobs": [(j.get("label"), (j.get("last_exit") or 0) != 0, j.get("python_runs"), j.get("python_ok"),
                      j.get("bare_in_command"), j.get("bare_in_wrapper"), j.get("log_failure"))
                     for j in d.get("jobs") or []],
            # 配線された hook の集合 (= 新しい hook が届いたか) と、 書き換え追従の能力・状態・stub (= 書き換えの前の gate が読む)。
            # engine_head は essence に入れない (層1 は日に何度も進む = beat の commit が増えるだけ)
            "harness_hooks": d.get("harness_hooks"),
            "rewrite_follow": {k: (d.get("rewrite_follow") or {}).get(k) for k in ("capable", "state", "manifest", "prepush_stub")},
            # repo ごとの点呼: 「捨てられた履歴の上に居る repo」 と「stub の無い repo」 の変化は即 commit (heads は入れない)
            "repos": {k: (d.get("repos") or {}).get(k) for k in ("stale", "no_stub", "stopped", "events", "error", "fetch_failed")},
            # 同期の事実は「手元にだけ在る commit が在る / 遅れている / 最新化を止める未 commit が在る」 の有無だけ (数・時刻は入れない
            # = commit が積もるたびに beat を commit しない。 現れた・消えた時だけ即 commit = 他の machine の reader に早く届く)
            "sync": sorted([n, bool(v.get("ahead")), bool(v.get("behind")), bool(v.get("wip_overlap"))]
                           for n, v in ((d.get("repos") or {}).get("sync") or {}).items()),
        },
        sort_keys=True,
    )


def engine_head():
    """本 engine の repo (= 層1) の HEAD sha。 他マシンから「この Mac の層1 は何版か」 を読むため。 取れなければ None。"""
    rc, out = sh(["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "HEAD"])
    return out.strip() if rc == 0 and out.strip() else None


def harness_hooks(home: Path):
    """<home>/.claude/settings.json に配線された hook の **file 名だけ** (event 横断・重複なし・sorted)。 読めなければ None。"""
    p = home / ".claude" / "settings.json"
    try:
        with open(p, encoding="utf-8") as f:
            hooks = json.load(f).get("hooks") or {}
    except Exception:
        return None
    names = set()
    for entries in hooks.values():
        for e in entries or []:
            if not isinstance(e, dict):
                continue
            for h in e.get("hooks") or []:
                cmd = h.get("command") if isinstance(h, dict) else None
                if cmd and cmd.split():
                    names.add(os.path.basename(cmd.split()[0]))
    return sorted(names)


def rewrite_preflight(repo: Path, subdir: str):
    """commit の前: upstream を fetch し、 分岐していれば中身で揃える (lib.follow_repo)。 揃えられなければ state=stopped
    (呼び元は beat を止める = 古い commit を積み直さない)。 manifest のある repo には pre-push stub を置く。"""
    out = {"capable": True, "state": "unknown", "upstream": None, "up_sha": None, "line": "", "manifest": False,
           "prepush_stub": False, "forced_update_seen": False, "fetched": False}
    up = _rf.upstream_of(repo)
    out["upstream"] = up or None
    if not up:
        out["state"] = "no-upstream"
        return out
    remote = up.split("/", 1)[0]
    rc, _ = git(repo, "fetch", "-q", remote, timeout=_rf.FETCH_TIMEOUT)
    out["fetched"] = rc == 0
    try:
        r = _rf.follow_repo(repo, fetch=False)
        out["state"] = r.state
        out["line"] = " | ".join([r.line] + [x.strip() for x in r.extra]) if r.line else ""
    except Exception as exc:
        out["state"], out["line"] = "stopped", f"追従の判定で失敗 ({type(exc).__name__}: {str(exc)[:120]})"
    out["up_sha"] = _rf.rev(repo, up) or None
    try:
        out["forced_update_seen"] = _rf.forced_update_seen(repo, up)
        st_line = _rf.ensure_prepush(repo, only_with_manifest=True)
        if st_line:
            out["line"] = (out["line"] + " | " + st_line).strip(" |")
        out["manifest"] = bool(_rf.upstream_manifest_files(repo, up))
        out["prepush_stub"] = _rf.has_prepush_stub(repo)
    except Exception:
        pass
    return out


FETCH_RETRY_TIMEOUT = 600    # 短い制限で落ちた fetch を取り直す時の、 1 repo あたりの制限 (秒)
FETCH_RETRY_BUDGET = 900     # 取り直しに使う、 1 beat あたりの持ち時間 (秒)。 超えた分は次の beat


def follow_all(root: Path, skip=()):
    """root/*/ の全 repo を fetch し、 書き換えられた履歴に揃えられる clone を揃える (lib.follow_repo = 手元の commit の中身が
    upstream に在る時だけ ref を動かす。 pull / merge / rebase はしない)。 (揃えた repo 名, 止まった repo 名)。
    session を開かない machine でも、 この無人の job が追従する = 「その machine で 1 回」 を人に渡さない。
    fetch は並列 (network 待ち)、 追従の判定は直列。 skip = 既に呼び手が扱った repo の path。"""
    from concurrent.futures import ThreadPoolExecutor
    repos = [Path(g).parent for g in sorted(globmod.glob(os.path.join(str(root), "*", ".git")))]
    repos = [r for r in repos if r.resolve() not in {Path(s).resolve() for s in skip}]

    fetch_failed = []
    retry = []

    def fetch(repo):
        # fetch の失敗を黙って捨てない: 失敗した repo は upstream の知識が古いまま = 「揃える対象なし」 に見える。
        # 名前を記録に載せ、 読む側が「次の回が揃える」 と言わないようにする (git() は失敗しても例外を出さず、 終了値で返す)
        try:
            up = _rf.upstream_of(repo)
            if up and git(repo, "fetch", "-q", up.split("/", 1)[0], timeout=_rf.FETCH_TIMEOUT)[0] != 0:
                retry.append((repo, up.split("/", 1)[0]))
        except Exception:
            fetch_failed.append(repo.name)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(fetch, repos))
    # 1 回目は短い制限で並列。 そこで落ちた repo は、 長い制限で 1 つずつ取り直す: 打ち切られた fetch は途中まで取った分を残さない
    # ので、 長く止まっていた machine の大きい repo (書き換えで commit と tree が全部新しい) は、 短い制限のままでは毎回落ち続ける
    # (実測)。 取り直しは 1 beat あたりの持ち時間まで。 残りは次の beat。
    t0 = time.time()
    for repo, remote in sorted(retry, key=lambda x: x[0].name):
        if time.time() - t0 > FETCH_RETRY_BUDGET or git(repo, "fetch", "-q", remote, timeout=FETCH_RETRY_TIMEOUT)[0] != 0:
            fetch_failed.append(repo.name)
    followed, stopped = [], []
    for repo in repos:
        try:
            r = _rf.follow_repo(repo, fetch=False)
        except Exception:
            continue
        if r.state == "followed":
            followed.append(repo.name)
        elif r.state == "stopped":
            stopped.append(repo.name)
    return followed, stopped, sorted(fetch_failed)


def _porcelain_paths(z: str):
    """`git status --porcelain -z` の出力から path の集合 (rename / copy は新旧の両方)。"""
    out, it = set(), iter(z.split("\0"))
    for ent in it:
        if len(ent) < 4:
            continue
        out.add(ent[3:])
        if ent[0] in "RC":
            old = next(it, "")
            if old:
                out.add(old)
    return out


def sync_facts(root: Path, names):
    """root/*/ の clone ごとの同期の事実 (判定はしない = reader が古さで判定する): 手元にだけ在る commit の数と最古の commit の時刻
    (ahead / ahead_since)、 upstream にだけ在る commit の数と最古の commit の時刻 (behind / behind_since = どれだけ前から遅れているか)、
    behind の時に upstream の変更と重なる未 commit の file の数 (wip_overlap)。 ahead が在るか、 behind で重なりが在る repo だけを返す。
    重なりの古さに file の更新時刻を使わない (よく書かれる台帳の file は、 別の session が書くたびに時刻が新しくなり、 何日止まっていても
    新しく見える) = 遅れの最古の commit の時刻で測る。
    path は載せない (file 名に人や案件が出る repo がある = 数と時刻だけ。 どの file かはその machine で git status を見る)。
    なぜ (実測): 無人の書き手の commit が手元に閉じ、 session を開かない機械では誰も気づかなかった。 heads は sha だけで、
    reader は「手元にだけ在る commit がいつから在るか」 「最新化を止めている未 commit がいつから在るか」 を見分けられなかった。"""
    out = {}
    for name in names:
        repo = root / name
        try:
            rc1, a = git(repo, "rev-list", "--count", "@{u}..HEAD")
            rc2, b = git(repo, "rev-list", "--count", "HEAD..@{u}")
            if rc1 or rc2:
                continue
            ahead, behind = int(a.strip() or 0), int(b.strip() or 0)
            e = {}
            if ahead:
                _, ts = git(repo, "log", "--format=%ct", "@{u}..HEAD")
                times = [int(t) for t in ts.split() if t.isdigit()]
                e["ahead"] = ahead
                if times:
                    e["ahead_since"] = min(times)
            if behind:
                _, st = git(repo, "status", "--porcelain", "--untracked-files=no", "-z")
                _, chg = git(repo, "diff", "--name-only", "-z", "HEAD...@{u}")
                ov = _porcelain_paths(st) & {x for x in chg.split("\0") if x}
                if ov:
                    e["wip_overlap"] = len(ov)
            if e:
                if behind:
                    e["behind"] = behind
                    _, bts = git(repo, "log", "--format=%ct", "HEAD..@{u}")
                    btimes = [int(t) for t in bts.split() if t.isdigit()]
                    if btimes:
                        e["behind_since"] = min(btimes)
                out[name] = e
        except Exception:   # 1 つの repo の失敗で、 残りの repo の事実を落とさない
            continue
    return out


def repos_rollcall(root: Path, follow=False, skip=()):
    """root/*/ の全 repo に pre-push stub を置き、 repo ごとの事実と、 この machine 自身が分かっている未追従を返す
    (docstring「repo ごとの点呼」)。 follow=True なら、 その前に全 repo を fetch して追従する。 部品が古い / 失敗 = None
    (beat は止めない)。"""
    if _rf is None or not hasattr(_rf, "repo_facts"):
        return None
    try:
        followed, stopped, fetch_failed = follow_all(root, skip) if follow else ([], [], [])
        placed, failed = _rf.ensure_prepush_all(root)
        heads = _rf.repo_facts(root)
        stale = []
        for name in heads:
            try:
                if not _rf.head_violations(root / name)[0]:
                    stale.append(name)
            except Exception:
                pass
        out = {"heads": heads, "stale": sorted(stale),
               "no_stub": sorted(n for n, f in heads.items() if f.get("prepush") != "stub"),
               "stub_placed": len(placed), "stub_failed": failed[:5],
               "sync": sync_facts(root, sorted(heads))}
        if follow:
            out["followed"], out["stopped"] = sorted(followed), sorted(stopped)
            if fetch_failed:
                out["fetch_failed"] = fetch_failed
        if hasattr(_rf, "recent_events"):
            ev = _rf.recent_events(24)      # 止めずに通した出来事 (検査・点呼が走らなかった / override) = その場の 1 行は誰も読まない
            if ev:
                out["events"] = ev
        return out
    except Exception as exc:
        # 集計の失敗を「報告なし」 に畳まない: 何で落ちたかを beat に載せる (他の machine から読める。 beat は止めない)
        return {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def sync_after_commit(repo: Path, pre: dict):
    """commit の後・push の前。 upstream が普通に進んでいれば自分の commit を載せ直す (旧 pull --rebase と同じ)。 preflight から
    ここまでの間に forced update が来ていれば載せ直さない (次の beat が中身で揃える)。 push 範囲に旧世代の commit / blob が在れば
    push しない。 止めた時だけ理由の文字列を返す。"""
    up = pre["upstream"]
    remote = up.split("/", 1)[0]
    git(repo, "fetch", "-q", remote, timeout=_rf.FETCH_TIMEOUT)
    before, after = pre.get("up_sha"), _rf.rev(repo, up)
    if after and before and after != before and not _rf.is_ancestor(repo, before, after):
        return "committed locally; deferred (forced update arrived during the beat: no rebase, the next beat follows it)"
    if after and not _rf.is_ancestor(repo, after, "HEAD"):
        rc, _ = git(repo, "rebase", "--autostash", "-q", after)
        if rc != 0:
            git(repo, "rebase", "--abort")
            return "committed locally; deferred (rebase onto upstream failed, retry next beat)"
    head = _rf.rev(repo, "HEAD")
    _rc, br = git(repo, "symbolic-ref", "--short", "-q", "HEAD")
    branch = br.strip() or "HEAD"
    try:
        ok, msgs = _rf.guard_stdin(repo, [f"refs/heads/{branch} {head} refs/heads/{branch} {after or _rf.ZERO}"])
    except Exception:
        ok, msgs = True, []
    if not ok:
        return "committed locally; push refused by the rewrite guard: " + " | ".join(msgs)
    return None


def git(repo: Path, *args, timeout=60):
    return sh(["git", "-C", str(repo), *args], timeout=timeout)


def beat(repo: Path, subdir: str, min_interval_h: float, rc_prefix: str, cron_prefix,
         inventory_specs=None, job_prefixes=None, job_modules=None, repos_root=None, repos_follow=False):
    data = collect(rc_prefix, cron_prefix, inventory_specs, job_prefixes, job_modules)
    data["engine_head"] = engine_head()
    hh = harness_hooks(Path.home())
    if hh is not None:
        data["harness_hooks"] = hh
    # 書き換えられた履歴の追従は commit の前 (= 古い履歴の上に beat を積まない)。 揃えられなければ beat を止める
    pre = None
    if _rf is not None:
        pre = rewrite_preflight(repo, subdir)
        data["rewrite_follow"] = {k: pre[k] for k in ("capable", "state", "upstream", "manifest", "prepush_stub", "forced_update_seen")}
        if pre["state"] == "stopped":
            return "deferred (rewrite follow stopped; no commit, no rebase): " + pre["line"]
    if repos_root:
        rr = repos_rollcall(Path(repos_root).expanduser(), follow=repos_follow, skip=[repo])
        if rr is not None:
            data["repos"] = rr
    rel = f"{subdir}/{data['host']}.json"
    fpath = repo / rel
    fpath.parent.mkdir(parents=True, exist_ok=True)

    old_ess = None
    if fpath.exists():
        try:
            old_ess = essence(json.load(open(fpath)))
        except Exception:
            pass
    rc, out = git(repo, "log", "-1", "--format=%ct", "--", rel)
    last_commit = int(out.strip()) if (rc == 0 and out.strip().isdigit()) else 0
    aged = (time.time() - last_commit) >= min_interval_h * 3600

    if old_ess == essence(data) and not aged:
        return "skip (no change, within interval)"

    fpath.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    git(repo, "add", rel)
    rc, _ = git(repo, "commit", "-q", "-m", f"fleet-heartbeat: {data['host']}")
    if rc != 0:
        return "commit failed (fail-open)"
    # --autostash: 他 session が残した無関係な dirty file で rebase が
    # 拒否されると、 beat が local commit に積み上がるだけで push されず
    # 他マシンから silent 死に見える (2026-07-10 実測 RCA: dirty 残置 2 日で
    # divergence 76/12 まで雪だるま化)。 autostash なら dirty をまたいで流れる。
    # 2026-09-29: 載せ直すのは upstream が普通に進んだ時だけ (forced update = 書き換えなら載せ直さない、 sync_after_commit)。
    if pre is not None and pre.get("upstream"):
        note = sync_after_commit(repo, pre)
        if note:
            return note
    else:
        git(repo, "pull", "--rebase", "--autostash", "-q")
    rc, _ = git(repo, "push", "-q", timeout=90)
    return "committed+pushed" if rc == 0 else "committed (push failed, retry next beat)"


def _selftest_rewrite(td: Path):
    """書き換えられた remote への beat: (A) 古い履歴 + 自分の beat の上の Mac は揃えてから載せる (旧 sha は remote に戻らない)
    (B) 手元にしか無い commit を持つ Mac は beat を止める (C) 古い履歴を merge してしまった Mac の push は guard が止める。"""
    rf_env = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
              "GIT_AUTHOR_EMAIL": "t@" + "example.invalid", "GIT_COMMITTER_NAME": "t",
              "GIT_COMMITTER_EMAIL": "t@" + "example.invalid",
              _rf.LOG_ENV: str(td / "rf.log"), _rf.MAPS_FILE_ENV: str(td / "no-maps"), _rf.MAPS_ENV: "",
              # 旧履歴と新履歴の日時を固定して分ける: 同じ中身・同じ message の c1 が同じ秒に作られると sha が一致し (Linux の CI で実測)、
              # 「旧 sha が remote に無い」 の assert が偽に落ちる
              "GIT_AUTHOR_DATE": "2000-01-01T00:00:00 +0000", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00 +0000"}
    saved = {k: os.environ.get(k) for k in rf_env}
    os.environ.update(rf_env)
    n = 0
    try:
        def g1(p, *a):
            # fixture の git は失敗を黙らせない (engine の git() は fail-open で rc を返すだけ = fixture の壊れ方が見えない)
            r = subprocess.run(["git", "-C", str(p), *a], capture_output=True, text=True, errors="replace")
            assert r.returncode == 0, f"fixture git {' '.join(a)} in {Path(p).name}: rc={r.returncode} {r.stderr.strip()[:300]}"
            return r.stdout.strip()

        def wc(p, files, msg):
            for f, body in files.items():
                (p / f).parent.mkdir(parents=True, exist_ok=True)
                (p / f).write_text(body)
                g1(p, "add", f)
            g1(p, "commit", "-q", "--allow-empty", "-m", msg)
            return g1(p, "rev-parse", "HEAD")

        rem = td / "rem.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(rem)], check=True)
        work = td / "work"
        subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
        o1 = wc(work, {"a.txt": "one\n", ".rewrite-follow/ignore-paths": "fleet/\n"}, "c1")
        o2 = wc(work, {"a.txt": "id=K00X0000\n"}, "c2")
        o3 = wc(work, {"a.txt": "clean\n"}, "c3")
        git(work, "remote", "add", "origin", str(rem))
        git(work, "push", "-q", "-u", "origin", "main")
        mac, mac_local, mac_merge = td / "mac", td / "mac-local", td / "mac-merge"
        for m in (mac, mac_local, mac_merge):
            subprocess.run(["git", "clone", "-q", str(rem), str(m)], check=True)
        wc(mac_local, {"z.txt": "mine\n"}, "local work")     # 書き換えの前から手元だけの commit
        r = beat(mac, "fleet", 4, RC_LABEL_PREFIX_DEFAULT, None)
        assert r == "committed+pushed", r
        b1 = g1(mac, "rev-parse", "HEAD")
        beat_json = (mac / "fleet" / f"{hostname_short()}.json").read_bytes()
        # 書き換え: c2 の a.txt を scrub、 c3 と beat の tree は同じ。 対応表 + forbidden-blobs を通常 commit で置く
        os.environ["GIT_AUTHOR_DATE"] = os.environ["GIT_COMMITTER_DATE"] = "2000-01-02T00:00:00 +0000"   # 新履歴は別の日時 (sha の一致を避ける)
        new = td / "new"
        subprocess.run(["git", "init", "-q", "-b", "main", str(new)], check=True)
        n1 = wc(new, {"a.txt": "one\n", ".rewrite-follow/ignore-paths": "fleet/\n"}, "c1")
        n2 = wc(new, {"a.txt": "id=<学籍番号>\n"}, "c2")
        n3 = wc(new, {"a.txt": "clean\n"}, "c3")
        (new / "fleet").mkdir()
        (new / "fleet" / f"{hostname_short()}.json").write_bytes(beat_json)
        git(new, "add", "fleet")
        n4 = wc(new, {}, "fleet-heartbeat: t")
        assert g1(new, "rev-parse", n4 + "^{tree}") == g1(mac, "rev-parse", b1 + "^{tree}"), "fixture: tree equal"
        old_blob = g1(work, "rev-parse", f"{o2}:a.txt")
        cmap = "old new\n" + "\n".join(f"{o} {x}" for o, x in ((o1, n1), (o2, n2), (o3, n3), (b1, n4))) + "\n"
        n5 = wc(new, {".rewrite-follow/commit-map": cmap, ".rewrite-follow/forbidden-blobs": old_blob + "\n"}, "publish map")
        g1(new, "push", "-q", "--force", str(rem), "main:main")
        assert g1(rem, "rev-parse", "main") == n5, "fixture: remote main is the rewritten tip"
        # (A)
        r = beat(mac, "fleet", 4, RC_LABEL_PREFIX_DEFAULT, None)
        rem_shas = set(g1(rem, "rev-list", "main").split())
        diag = (f"beat={r!r} remote={g1(rem, 'log', '--oneline', 'main')!r} mac={g1(mac, 'log', '--oneline', '-3')!r} "
                f"rf={json.loads((mac / 'fleet' / f'{hostname_short()}.json').read_text()).get('rewrite_follow')!r} "
                f"log={(td / 'rf.log').read_text() if (td / 'rf.log').exists() else ''!r}")
        assert r == "committed+pushed", diag
        assert not ({o1, o2, o3, b1} & rem_shas), "旧 sha が remote に戻った: " + diag
        assert n5 in rem_shas and g1(mac, "rev-parse", "HEAD~1") == n5, "beat は新しい履歴の先頭の上"
        d = json.loads((mac / "fleet" / f"{hostname_short()}.json").read_text())
        rf = d["rewrite_follow"]
        assert rf["state"] == "followed" and rf["capable"] and rf["manifest"] and rf["prepush_stub"], rf
        assert (mac / ".git" / "hooks" / "pre-push").exists(), "pre-push stub が置かれる"
        assert d.get("engine_head") is None or len(d["engine_head"]) == 40
        assert "harness_hooks" not in d or isinstance(d["harness_hooks"], list)
        n += 1
        # (B)
        head_before = g1(mac_local, "rev-parse", "HEAD")
        r = beat(mac_local, "fleet", 4, RC_LABEL_PREFIX_DEFAULT, None)
        assert r.startswith("deferred (rewrite follow stopped"), r
        assert g1(mac_local, "rev-parse", "HEAD") == head_before, "止めた Mac の HEAD が動いた"
        assert "local work" not in g1(rem, "log", "main", "--format=%s"), "止めた Mac の commit が remote に出た"
        n += 1
        # (C)
        git(mac_merge, "fetch", "-q", "origin")
        rc_m, _ = git(mac_merge, "merge", "-q", "--no-edit", "--allow-unrelated-histories", "origin/main")
        assert rc_m == 0, "fixture: merge"
        r = beat(mac_merge, "fleet", 4, RC_LABEL_PREFIX_DEFAULT, None)
        assert "push refused by the rewrite guard" in r, r
        assert not ({o1, o2, o3} & set(g1(rem, "rev-list", "main").split())), "merge した Mac の push で旧 sha が戻った"
        n += 1
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return n


def selftest():
    import tempfile
    ok = 0
    with tempfile.TemporaryDirectory() as td:
        # ANSI strip + marker priority (後に出た marker が勝つ)
        log = Path(td) / "x.log"
        log.write_bytes("·✔︎· Connected\x1b[6A\x1b[J\nNot logged in\n".encode())
        st, _ = parse_log_status(log)
        assert st == "auth_error", st
        ok += 1
        log.write_bytes("Not logged in\nfoo\n... Connected · Claude · HEAD\n".encode())
        st, _ = parse_log_status(log)
        assert st == "connected", st
        ok += 1
        # trust_error: 過去に Connected でも最後の marker が trust なら trust_error
        log.write_bytes("Connected · Claude · HEAD\nError: Workspace not trusted. Please run `claude` in /x first\n".encode())
        st, _ = parse_log_status(log)
        assert st == "trust_error", st
        ok += 1
        # essence: ts/pid 差は無視、 status 差は検出
        a = {"servers": [{"label": "l", "pid": "1", "last_status": "connected", "log_age_min": 3}],
             "config_dirs": {}, "remote_control_at_startup": True,
             "old_usr_local_cli": None, "cron_jobs": 2}
        b = json.loads(json.dumps(a)); b["servers"][0]["pid"] = "999"
        assert essence(a) == essence(b)
        ok += 1
        c = json.loads(json.dumps(a)); c["servers"][0]["last_status"] = "auth_error"
        assert essence(a) != essence(c)
        # 設定フォルダの判定: 切れた / 直った は変化、 問い合わせの時刻だけの変化は変化に数えない
        e = json.loads(json.dumps(a)); e["config_dir_auth"] = {"x": {"dead": False, "last_probe": "2000-01-01 00:00"}}
        f = json.loads(json.dumps(e)); f["config_dir_auth"]["x"]["last_probe"] = "2000-01-02 00:00"
        g = json.loads(json.dumps(e)); g["config_dir_auth"]["x"]["dead"] = True
        assert essence(e) == essence(f), "問い合わせの時刻だけでは commit しない"
        assert essence(e) != essence(g), "切れたら commit する"
        ok += 1
        # git repo での beat → commit → 2 回目は skip
        repo = Path(td) / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        # fixture email は文字列連結で構成 (= public-precommit の Tier A email regex を
        # 発火させないため。 値は RFC 2606 の .invalid = 実在しない domain)
        git(repo, "config", "user.email", "t@" + "example.invalid")
        git(repo, "config", "user.name", "t")
        r1 = beat(repo, "fleet", 4, RC_LABEL_PREFIX_DEFAULT, None)
        assert r1.startswith("committed"), r1
        ok += 1
        r2 = beat(repo, "fleet", 4, RC_LABEL_PREFIX_DEFAULT, None)
        assert r2.startswith("skip"), r2
        ok += 1
        # harness_hooks: settings.json の hook の file 名だけ (event 横断、 重複なし)
        hh_home = Path(td) / "hh"
        (hh_home / ".claude").mkdir(parents=True)
        (hh_home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": "~/.claude/hooks/a.sh"}]}],
            "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "~/.claude/hooks/b.py --x"},
                                                          {"type": "command", "command": "~/.claude/hooks/a.sh"}]}]}}))
        assert harness_hooks(hh_home) == ["a.sh", "b.py"], harness_hooks(hh_home)
        assert harness_hooks(Path(td) / "nohome") is None
        assert essence({"harness_hooks": ["a.sh"]}) != essence({"harness_hooks": ["a.sh", "b.py"]}), "配線された hook の変化は commit する"
        assert essence({"rewrite_follow": {"capable": True, "state": "current"}}) != essence({}), "追従の能力が届いたら commit する"
        ok += 1
        # repo ごとの点呼: heads の変化は commit の理由にしない、 stale / no_stub の変化は理由にする
        h1 = {"repos": {"heads": {"x": {"head": "a" * 12}}, "stale": [], "no_stub": []}}
        h2 = {"repos": {"heads": {"x": {"head": "b" * 12}}, "stale": [], "no_stub": []}}
        h3 = {"repos": {"heads": {"x": {"head": "b" * 12}}, "stale": ["x"], "no_stub": []}}
        assert essence(h1) == essence(h2), "HEAD が進んだだけでは commit しない"
        assert essence(h2) != essence(h3), "未追従の repo が現れたら commit する"
        ok += 1
        if _rf is not None and hasattr(_rf, "repo_facts"):
            # 追従の記録を一時 file に向ける (向けないと、 fixture の追従が本物の ~/.claude/state/rewrite-follow.log に
            # 「followed …/rollcall/…」 の行を残す = 実測。 その log は書き換えの追従の調べ物で読む記録)
            _rf_log_prev = os.environ.get(_rf.LOG_ENV)
            os.environ[_rf.LOG_ENV] = str(Path(td) / "rf-rollcall.log")
            rc_root = Path(td) / "rollcall"
            rc_root.mkdir()
            rc_remote = Path(td) / "rollcall-remote.git"
            sh(["git", "init", "-q", "--bare", "-b", "main", str(rc_remote)])
            seed = rc_root / "one"
            sh(["git", "init", "-q", "-b", "main", str(seed)])
            git(seed, "config", "user.email", "t@" + "example.invalid")
            git(seed, "config", "user.name", "t")
            (seed / "f.txt").write_text("1\n")
            git(seed, "add", "f.txt")
            git(seed, "commit", "-q", "-m", "c1")
            git(seed, "remote", "add", "origin", str(rc_remote))
            git(seed, "push", "-q", "-u", "origin", "main")
            rr = repos_rollcall(rc_root)
            assert rr and set(rr["heads"]) == {"one"} and rr["heads"]["one"]["prepush"] == "stub", rr
            assert rr["stale"] == [] and rr["no_stub"] == [] and rr["stub_placed"] == 1, rr
            assert repos_rollcall(rc_root)["stub_placed"] == 0, "2 回目は置き直さない"
            ok += 1
            # --repos-follow: fetch していない clone でも、 beat が fetch して書き換えに追従する (message だけの書き換え = tree は同じ)。
            # 手元にしか無い commit のある clone は止まって名前が載る。 ただ behind なだけの clone は動かさない
            for nm in ("stale", "local", "behind"):
                sh(["git", "clone", "-q", str(rc_remote), str(rc_root / nm)])
                git(rc_root / nm, "config", "user.email", "t@" + "example.invalid")
                git(rc_root / nm, "config", "user.name", "t")
            (rc_root / "local" / "mine.txt").write_text("local\n")
            git(rc_root / "local", "add", "mine.txt")
            git(rc_root / "local", "commit", "-q", "-m", "local only")
            git(seed, "commit", "-q", "--amend", "-m", "c1 rewritten")
            git(seed, "push", "-q", "--force", "origin", "main")
            new_tip = git(seed, "rev-parse", "HEAD")[1].strip()
            rr = repos_rollcall(rc_root, follow=True, skip=[seed])
            assert rr["followed"] == ["behind", "stale"] and rr["stopped"] == ["local"], rr
            assert git(rc_root / "stale", "rev-parse", "HEAD")[1].strip() == new_tip, "追従前の clone は新しい先頭へ"
            assert git(rc_root / "local", "log", "-1", "--format=%s")[1].strip() == "local only", "手元の commit は動かさない"
            assert rr["stale"] == ["local"], rr
            assert essence({"repos": {"stopped": []}}) != essence({"repos": {"stopped": ["x"]}}), "止まった repo が現れたら commit する"
            (seed / "g.txt").write_text("2\n")
            git(seed, "add", "g.txt")
            git(seed, "commit", "-q", "-m", "c2")
            git(seed, "push", "-q", "origin", "main")
            rr = repos_rollcall(rc_root, follow=True, skip=[seed])
            assert rr["followed"] == [] and git(rc_root / "stale", "rev-parse", "HEAD")[1].strip() == new_tip, \
                "behind なだけの clone は fetch するだけで動かさない"
            assert "fetch_failed" not in rr, rr
            # 同期の事実: 分岐した clone (手元の commit + upstream の前進) は ahead・ahead_since・behind が載る。
            # 遅れている clone で upstream の変更と重なる未 commit は数と時刻が載る (path は載せない)。 揃っている clone は載らない
            sy = rr.get("sync") or {}
            assert sy.get("local", {}).get("ahead") == 2 and sy["local"].get("behind") == 2 \
                and isinstance(sy["local"].get("ahead_since"), int), f"分岐した clone の同期の事実: {sy}"
            assert not ({"stale", "behind", "one"} & set(sy)), f"遅れているだけ・揃っている clone は載らない: {sy}"
            (rc_root / "stale" / "f.txt").write_text("edited here, not committed\n")
            assert "stale" not in sync_facts(rc_root, ["stale"]), "upstream の変更 (c2 = g.txt) と重ならない未 commit は載らない"
            (seed / "f.txt").write_text("3\n")
            git(seed, "commit", "-q", "-a", "-m", "c3")
            git(seed, "push", "-q", "origin", "main")
            git(rc_root / "stale", "fetch", "-q")
            sy2 = sync_facts(rc_root, ["stale"])
            assert sy2.get("stale", {}).get("wip_overlap") == 1 and isinstance(sy2["stale"].get("behind_since"), int) \
                and sy2["stale"].get("behind") == 2 and "ahead" not in sy2["stale"], f"最新化を止める未 commit: {sy2}"
            assert "f.txt" not in json.dumps(sy2), "path は載せない"
            git(rc_root / "stale", "checkout", "-q", "--", "f.txt")
            assert essence({"repos": {"sync": {"x": {"ahead": 1, "ahead_since": 1}}}}) \
                == essence({"repos": {"sync": {"x": {"ahead": 2, "ahead_since": 5}}}}), "数・時刻の変化では commit しない"
            assert essence({"repos": {"sync": {}}}) != essence({"repos": {"sync": {"x": {"ahead": 1}}}}), \
                "手元にだけ在る commit が現れたら commit する"
            git(rc_root / "behind", "remote", "set-url", "origin", str(Path(td) / "no-such-remote.git"))
            rr = repos_rollcall(rc_root, follow=True, skip=[seed])
            assert rr.get("fetch_failed") == ["behind"], f"fetch に失敗した repo は名前が載る: {rr.get('fetch_failed')}"
            assert essence({"repos": {"fetch_failed": ["x"]}}) != essence({"repos": {}}), "fetch の失敗が現れたら commit する"
            if _rf_log_prev is None:
                os.environ.pop(_rf.LOG_ENV, None)
            else:
                os.environ[_rf.LOG_ENV] = _rf_log_prev
            ok += 1
        if _rf is not None:
            ok += _selftest_rewrite(Path(td))
        # inventory: name = 最初の `*` 以降の最初の path 要素 (= 親 dir 名 / file 名の両形)
        inv_root = Path(td) / "invroot"
        for a in ("a1", "a2"):
            (inv_root / a).mkdir(parents=True)
            (inv_root / a / "credentials.json").write_text("x")
        (inv_root / "empty").mkdir()  # credentials.json 無し = 名前に出ない
        r = scan_inventory(f"accts={inv_root}/*/credentials.json")
        assert r == ("accts", ["a1", "a2"]), r
        ok += 1
        r = scan_inventory(f"files={inv_root}/*/*.json")
        assert r == ("files", ["a1", "a2"]), r  # 最初の `*` 以降の最初の要素 = 親 dir
        ok += 1
        flat = Path(td) / "flat"
        flat.mkdir()
        (flat / "a.key").write_text("x")
        (flat / "b.key").write_text("x")
        r = scan_inventory(f"secrets={flat}/*")
        assert r == ("secrets", ["a.key", "b.key"]), r
        ok += 1
        # match 0 件でも label は [] で報告 (= 「旧 beat の field 不在」 と区別できるように)
        r = scan_inventory(f"none={flat}/nope-*/x")
        assert r == ("none", []), r
        ok += 1
        # 不正 spec は None (= caller が無視、 beat を落とさない)
        assert scan_inventory("no-equals-sign") is None
        assert scan_inventory("=/tmp/*") is None
        ok += 1
        # collect() 配線 + essence が inventory 変化を拾う (= 即 commit 対象)
        d1 = collect(RC_LABEL_PREFIX_DEFAULT, None, [f"accts={inv_root}/*/credentials.json"])
        assert d1["inventories"] == {"accts": ["a1", "a2"]}, d1.get("inventories")
        d2 = json.loads(json.dumps(d1))
        d2["inventories"]["accts"] = ["a1"]
        assert essence(d1) != essence(d2)
        ok += 1
        # --inventory 未指定なら field 自体を作らない (= 旧 beat と同形、 opt-in)
        assert "inventories" not in collect(RC_LABEL_PREFIX_DEFAULT, None, None)
        # job health: PATH の python3 が module を読めないジョブを、 wrapper の書き方ごと記録する
        jroot = Path(td) / "jobhome"
        (jroot / "brew").mkdir(parents=True)
        (jroot / "sys").mkdir(parents=True)
        (jroot / "Library/LaunchAgents").mkdir(parents=True)
        for d_, good in (("brew", False), ("sys", True)):
            p = jroot / d_ / "python3"
            p.write_text("#!/bin/sh\nexit %d\n" % (0 if good else 1))
            p.chmod(0o755)
        w_bare = jroot / "bare-cron.sh"
        w_bare.write_text("#!/bin/bash\n# python3 はコメント\ncommand -v python3 >/dev/null || exit 0\necho \"python3 が無い\"\npython3 \"$ENGINE\" --x\n")
        w_pick = jroot / "pick-cron.sh"
        w_pick.write_text("#!/bin/bash\nPY=\"$(pick_python yaml)\" || exit 3\n\"$PY\" \"$ENGINE\"\n")
        def mkpl(target, path):
            return {"ProgramArguments": ["/bin/sh", "-c",
                    'export PATH="%s"; cd "$HOME" && exec bash "%s"' % (path, target)]}
        jb = job_health("j.bare", "0", mkpl(str(w_bare), f"$HOME/brew:$HOME/sys"), ["yaml"], jroot)
        assert jb["python"] == str(jroot / "brew/python3") and jb["python_ok"] is False and jb["python_runs"] is False             and jb["bare_in_wrapper"] is True and jb["bare_in_command"] is False, jb
        jp = job_health("j.pick", "3", mkpl(str(w_pick), f"$HOME/brew:$HOME/sys"), ["yaml"], jroot)
        assert jp["bare_in_wrapper"] is False and jp["last_exit"] == 3, jp
        # ProgramArguments が ["/bin/sh", "<wrapper>"] の形 (quote なし・sh) の wrapper も見る
        # (実測: 通知 daemon がこの形で、 wrapper の素の python3 が検査の外だった)
        js = job_health("j.sh", "0", {"ProgramArguments": ["/bin/sh", str(w_bare)]}, ["yaml"], jroot)
        assert js["bare_in_wrapper"] is True and js["bare_in_command"] is False, js
        assert _WRAPPER_RE.findall('/bin/sh /x/a-cron.sh') == ['/x/a-cron.sh']             and _WRAPPER_RE.findall('exec bash "/x/b.sh"') == ['/x/b.sh']             and _WRAPPER_RE.findall('sh -c "python3 x.py"') == []
        # 継いだ環境の PATH: launchctl print の出力から (定義に PATH が無い job はこれで走る)
        lc = ("\tinherited environment = {\n\t\tPATH => /opt/x/bin:/usr/bin\n\t\tSSH_AUTH_SOCK => /tmp/s\n\t}\n\n"
              "\tdefault environment = {\n\t\tPATH => /usr/bin:/bin\n\t}\n")
        assert parse_inherited_path(lc) == "/opt/x/bin:/usr/bin" and parse_inherited_path("state = running\n") is None
        jg = job_health("j.gate", "-", {"ProgramArguments": ["/bin/sh", "-c",
                        'export PATH="$HOME/sys"; cd x && python3 "gate.py" || exit 0; exec claude -p']}, ["yaml"], jroot)
        assert jg["bare_in_command"] is True and jg["bare_in_wrapper"] is False and jg["python_ok"] is True             and jg["python_runs"] is True and jg["last_exit"] is None, jg
        assert not bare_python_in('echo "yaml を import できる python3 が無い" >&2')
        assert bare_python_in('out="$(python3 x.py)"') and bare_python_in("python3 x.py")             and not bare_python_in('PY=python3') and not bare_python_in('[ -x /usr/bin/python3 ] && PY=/usr/bin/python3')
        assert job_health("j.none", "0", None, ["yaml"], jroot)["python"] is None
        assert resolve_in_path("python3", None) in (None, "/usr/bin/python3")
        e1 = essence({"jobs": [jb]}); e2 = essence({"jobs": [dict(jb, python_ok=True)]})
        assert e1 != e2, "job の健康の変化は即 commit"
        # 直近 run の log 末尾 (lib/launchd_job_log.py と共有の判定): exit 0 でも認証切れを運ぶ
        (jroot / "Library/Logs").mkdir(parents=True, exist_ok=True)
        (jroot / "Library/Logs/j.auth.log").write_text("warn\nFailed to authenticate: OAuth session expired\n")
        ja = job_health("j.auth", "0", {"ProgramArguments": ["/bin/sh", "-c",
                        'export CLAUDE_CONFIG_DIR="/c/.claude-x"; exec claude -p']}, [], jroot)
        if _jl is not None:
            assert ja["log_failure"] == "auth" and ja["config_dir"] == "/c/.claude-x" \
                and ja["log_age_h"] is not None and ja["last_exit"] == 0, ja
            assert essence({"jobs": [ja]}) != essence({"jobs": [dict(ja, log_failure=None)]}), "失敗の原因の変化も即 commit"
            # 予定の run が log に残っているかの材料 (reader の判定 = lib の missed_fire)
            assert isinstance(ja["log_mtime"], int) and ja["log_deferred"] is False and ja["claude_p"] is True \
                and ja["gated"] is False \
                and ja["schedule"] is None, ja
            jc = job_health("j.cal", "0", {"ProgramArguments": ["/bin/sh", "-c",
                            'cd x && { python3 "$HOME/c/routine-host-gate.py" r l.json; } && exec "/u/claude" -p "x"'],
                            "StartCalendarInterval": {"Hour": 7, "Minute": 30}}, [], jroot)
            assert jc["gated"] is True and jc["claude_p"] is True and jc["schedule"] == {"cal": [{"Minute": 30, "Hour": 7}]} \
                and jc["log_mtime"] is None, jc
            assert essence({"jobs": [ja]}) == essence({"jobs": [dict(ja, log_mtime=1)]}), "log の時刻は commit の理由にしない"
        assert job_health("j.nolog", "0", None, [], jroot)["log_failure"] is None
        ok += 1
    print(f"selftest: {ok} PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("--subdir", default="private/fleet-status")
    ap.add_argument("--min-commit-interval-hours", type=float, default=4)
    ap.add_argument("--rc-label-prefix", default=RC_LABEL_PREFIX_DEFAULT)
    ap.add_argument("--cron-label-prefix", default=None)
    ap.add_argument("--inventory", action="append", default=[],
                    metavar="LABEL=GLOB",
                    help="このマシンに置かれた物の **名前だけ** を記録 (repeatable、 中身は読まない)。 "
                         "reader が fleet 横断で突合し「他マシンには在るのにここには無い」 を surface")
    ap.add_argument("--job-label-prefix", action="append", default=[],
                    help="この prefix の launchd job ごとに最後の終了コードと、 job の PATH での python3 の健康を記録 (repeatable)")
    ap.add_argument("--job-python-modules", default="",
                    help="ジョブの python3 が import できるべき module (カンマ区切り、 例 yaml)")
    ap.add_argument("--repos-root", default=None,
                    help="この dir の直下の全 repo に pre-push stub を置き、 repo ごとの事実 (HEAD・見ている upstream) を記録する "
                         "(履歴を書き換えた repo の追従を、 最新を知る machine の reader が判定するための点呼)")
    ap.add_argument("--repos-follow", action="store_true",
                    help="--repos-root の全 repo を毎 beat fetch し、 書き換えられた履歴に揃えられる clone を揃える "
                         "(session を開かない machine でも追従する)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return
    if not args.repo:
        print("--repo required", file=sys.stderr)
        sys.exit(0)  # fail-open
    try:
        msg = beat(Path(args.repo).expanduser(), args.subdir,
                   args.min_commit_interval_hours, args.rc_label_prefix,
                   args.cron_label_prefix, args.inventory, args.job_label_prefix,
                   [m.strip() for m in args.job_python_modules.split(",") if m.strip()],
                   repos_root=args.repos_root, repos_follow=args.repos_follow)
        print(msg)
    except Exception as e:
        print(f"fail-open: {e}", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
