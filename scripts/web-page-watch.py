#!/usr/bin/env python3
"""web-page-watch.py — 公開 web ページの本文が変わったら知らせる (台帳の URL を定期に読み、 目印で切り出した本文の差分を state に残して、 macOS 通知と SessionStart 用の行を出す。 標準ライブラリだけで動き、 YAML 台帳のときだけ PyYAML が要る)

用途: 受付の再開・日程の変更のように「いつ変わるか分からないが、 変わったらすぐ動く」 告知を、
人の記憶や「その頃に見る」 という予定に頼らずに拾う。 正本 = conventions/public-page-watch.md
(告知の正本の層 / 目印 / 今すぐやることを書く / 知らせる面の重ね方 / 表示側は state だけ読む / 経路の健康診断)。

台帳 (.json は標準ライブラリだけで読む。 それ以外は YAML として読む)
  targets[]
    id       短い名前 (必須。 --show / --ack で使う)
    url      読むページ (必須)
    label    表示名 (任意。 省くと id)
    start    本文の始まりの目印 (任意)。 この文字列を含む最初の行から切り出す
    end      本文の終わりの目印 (任意)。 start より後で最初にこの文字列を含む行の手前まで
             (目印の外 = ナビ・関連リンク・フッタの変化では知らせない)
    until    YYYY-MM-DD (任意)。 この日を過ぎたら読まない (= 期限つきの監視を台帳に置き忘れない)
    action   変わったら**今すぐ何をするか** (任意だが実質必須)。 「変わった」 だけでは人は動かないので、
             通知・ダイアログ・dashboard の行はすべて「→ 今すぐ: <action>」 を載せる
    urgent   true なら 🚨 で出し、 --alert (消えないダイアログ) と --on-change (スマホ等) の対象にする。
             false / 省略は 🔔 = バナー通知と行だけ
    signals  決め手の文言 (任意)。 [{"gone": "受付を中止しています", "say": "受付再開の可能性が高い"},
             {"appears": "日程を変更しました", "say": "日程が動いた"}] のように、 確認済みの本文と最新の本文を比べて
             消えた / 現れた文言があれば行と通知に「(「…」 が消えた = <say>)」 と出す
    note     補足 (任意。 案件の TODO id など。 行の末尾に [..] で添える)
  state      state file の path (任意。 既定 = ~/.local/state/web-page-watch/<台帳の名前>.json)
  stale_hours  最後の巡回からこの時間を超えたら ⏸️ を出す (任意。 既定 36)

使い方:
  web-page-watch.py --ledger L              全 target を読み、 変化を state に記録して行を出す (定期実行用)
  web-page-watch.py --ledger L --notify     同上 + 新しい本文を見つけたら macOS 通知 (バナー = 数秒で消える)
  web-page-watch.py --ledger L --alert      同上 + urgent の target は押すまで消えない警告ダイアログ (バナーだけでは見落とす)
  web-page-watch.py --ledger L --on-change CMD   urgent の target に新しい本文を見つけたら CMD を実行し、 引数の末尾に
                                            通知文 (変わった + 決め手 + 今すぐやること) を 1 つずつ足す
                                            (= スマホへの通知など、 別の経路を呼び出し側が差し込む口)
  web-page-watch.py --ledger L --probe CMD  巡回のたびに CMD (その経路の軽い健康診断) を実行し、 失敗中は ⚠️ を出す
  web-page-watch.py --ledger L --surface    network に出ず、 state から未確認の変化と異常だけを出す (SessionStart 用)
  web-page-watch.py --ledger L --show ID    未確認の変化の差分を出す
  web-page-watch.py --ledger L --ack ID     確認済みにする (今の本文を新しい基準にする)。 ID = all で全部
  web-page-watch.py --selftest              合成データだけで検査する (network に出ない)

出す行 (知らせることが無ければ無出力):
  🚨 / 🔔 <label> が変わった (<決め手>) → 今すぐ: <action> [<note>] (<最初に気づいた時刻>) / 差分 = --show <id>、 済んだら --ack <id>
  ⚠️ <label> を N 回続けて読めていない (<理由>)   … 3 回目から。 目印が見つからない (= ページの作りが変わった) は 1 回目から
  ⏸️ 最後の巡回が H 時間前 / まだ一度も巡回していない   … --surface だけ。 期限内の target があるときだけ
  ⚠️ 変化を知らせる追加の経路 (--on-change) が失敗した   … 次に成功するまで出続ける (= スマホ等に届かなかったことを黙らせない)
  ⚠️ 変化を知らせる追加の経路が使えない状態 (--probe)   … 巡回ごとの軽い検査が失敗している間 (= 変化が起きる前に直せる)
  ⌛ 期限 (until) を過ぎた target N 件 → 台帳から外す

state: target ごとに baseline (確認済みの本文) と latest (最後に読めた本文)。 初めて読んだ本文は基準にするだけで
知らせない。 変化は --ack するまで出続け、 本文が基準に戻れば消える。 通知は新しい本文を見たときに 1 回だけ
(= 未確認のままさらに変われば、 もう一度通知する)。 state はマシンごとに持つ (ack もマシンごと)。
fail-open: 読めない target は ⚠️ に数えて他の target を続ける。 exit は常に 0 (--selftest を除く)。
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

def _yaml_safe_load(stream):  # yaml.safe_load と同じ結果を C 版 (libyaml) で返す = 約 10 倍速 (2026-09-23)
    import yaml
    return yaml.load(stream, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))


TIMEOUT = 20
ERROR_THRESHOLD = 3
DEFAULT_STALE_HOURS = 36
USER_AGENT = "Mozilla/5.0 (compatible; web-page-watch)"


class MarkerMissing(Exception):
    pass


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def load_ledger(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        data = json.loads(text)
    else:
        import yaml  # noqa: PLC0415 (YAML 台帳のときだけ要る)
        data = _yaml_safe_load(text)
    data = data or {}
    for t in data.get("targets") or []:
        if not t.get("id") or not t.get("url"):
            raise ValueError(f"target に id と url が要る: {t!r}")
    return data


def default_state_path(ledger: Path) -> Path:
    return Path.home() / ".local" / "state" / "web-page-watch" / f"{ledger.stem}.json"


def state_path_of(ledger_path: Path, ledger: dict) -> Path:
    p = ledger.get("state")
    return Path(os.path.expanduser(str(p))) if p else default_state_path(ledger_path)


def read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"targets": {}}


def write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def fetch_url(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 (台帳の URL だけを読む)
        raw = r.read()
        charset = r.headers.get_content_charset()
    if not charset:
        m = re.search(rb'<meta[^>]+charset=["\']?([A-Za-z0-9_\-]+)', raw[:4096], flags=re.I)
        charset = m.group(1).decode("ascii") if m else "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def html_to_lines(src: str) -> list[str]:
    t = re.sub(r"<(script|style|noscript)\b.*?</\1\s*>", "", src, flags=re.S | re.I)
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    # block 要素は開きタグでも閉じタグでも改行にする (= 閉じタグの無い直前の文と次の段落が 1 行に繋がらない)
    t = re.sub(r"</?(p|h[1-6]|li|ul|ol|tr|td|th|div|dl|dt|dd|caption|table|section|article)\b[^>]*>", "\n", t,
               flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    lines = (re.sub(r"\s+", " ", ln).strip() for ln in t.split("\n"))
    return [ln for ln in lines if ln]


def extract(lines: list[str], start: str | None, end: str | None) -> list[str]:
    i = 0
    if start:
        i = next((k for k, ln in enumerate(lines) if start in ln), -1)
        if i < 0:
            raise MarkerMissing(f"始まりの目印「{start}」 が無い")
    j = len(lines)
    if end:
        j = next((k for k in range(i + 1, len(lines)) if end in lines[k]), -1)
        if j < 0:
            raise MarkerMissing(f"終わりの目印「{end}」 が無い")
    return lines[i:j]


def digest(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def expired(target: dict, today: dt.date) -> bool:
    until = target.get("until")
    if not until:
        return False
    try:
        return today > dt.date.fromisoformat(str(until))
    except ValueError:
        return False


def label_of(target: dict) -> str:
    return str(target.get("label") or target["id"])


def hours_since(iso: str | None, now: dt.datetime) -> float | None:
    if not iso:
        return None
    try:
        return (now - dt.datetime.fromisoformat(iso)).total_seconds() / 3600
    except ValueError:
        return None


def check(ledger: dict, state: dict, fetch=fetch_url, now: str | None = None) -> list[dict]:
    """全 target を読み state を更新する。 新しく見つけた本文 (= 通知すべきもの) の target を返す。"""
    now = now or now_iso()
    today = dt.datetime.fromisoformat(now).date()
    fresh: list[dict] = []
    st_targets = state.setdefault("targets", {})
    for t in ledger.get("targets") or []:
        if expired(t, today):
            continue
        s = st_targets.setdefault(t["id"], {})
        try:
            body = extract(html_to_lines(fetch(t["url"])), t.get("start"), t.get("end"))
        except MarkerMissing as e:
            s.update(errors=s.get("errors", 0) + 1, last_error=str(e), marker_missing=True)
            continue
        except Exception as e:  # noqa: BLE001 (fail-open: 読めない target は数えて次へ)
            s.update(errors=s.get("errors", 0) + 1, last_error=f"{type(e).__name__}: {e}"[:200],
                     marker_missing=False)
            continue
        h = digest(body)
        s.update(errors=0, last_error=None, marker_missing=False, last_ok=now)
        if "baseline" not in s:
            s.update(baseline=body, baseline_hash=h, latest=body, latest_hash=h)
            continue
        s.update(latest=body)
        if h == s.get("baseline_hash"):
            s.update(latest_hash=h, changed_at=None, notified_hash=None)
            continue
        if not s.get("changed_at"):
            s["changed_at"] = now
        s["latest_hash"] = h
        if s.get("notified_hash") != h:
            s["notified_hash"] = h
            fresh.append(t)
    state["last_run"] = now
    return fresh


def report(ledger: dict, state: dict, *, surface: bool, prog: str, ledger_arg: str,
           now: str | None = None) -> list[str]:
    now_dt = dt.datetime.fromisoformat(now or now_iso())
    today = now_dt.date()
    out: list[str] = []
    active = [t for t in ledger.get("targets") or [] if not expired(t, today)]
    gone = [t for t in ledger.get("targets") or [] if expired(t, today)]
    st_targets = state.get("targets") or {}
    for t in active:
        s = st_targets.get(t["id"]) or {}
        if s.get("changed_at") and s.get("latest_hash") != s.get("baseline_hash"):
            mark = "🚨" if t.get("urgent") else "🔔"
            out.append(f"{mark} {message_for(t, s)} ({s['changed_at'][:16].replace('T', ' ')})"
                       f" / 差分 = {prog} --ledger {ledger_arg} --show {t['id']}、 済んだら --ack {t['id']}")
        errs = s.get("errors", 0)
        if errs and (s.get("marker_missing") or errs >= ERROR_THRESHOLD):
            out.append(f"⚠️ {label_of(t)} を {errs} 回続けて読めていない ({s.get('last_error')}) — {t['url']}")
    if surface and active:
        stale = float(ledger.get("stale_hours") or DEFAULT_STALE_HOURS)
        age = hours_since(state.get("last_run"), now_dt)
        if age is None:
            out.append(f"⏸️ ページの見張りがまだ一度も巡回していない (定期実行が未配備の疑い。 台帳 = {ledger_arg})")
        elif age > stale:
            out.append(f"⏸️ ページの見張りの最後の巡回が {age:.0f} 時間前 (定期実行が止まっている疑い。 台帳 = {ledger_arg})")
    pe = state.get("probe_error")
    if pe and pe.get("error"):
        out.append(f"⚠️ 変化を知らせる追加の経路が使えない状態 ({str(pe.get('at'))[:16].replace('T', ' ')} の検査: {pe['error']})"
                   " = このまま変化が起きるとスマホ等に届かない")
    oce = state.get("on_change_error")
    if oce and oce.get("error"):
        out.append(f"⚠️ 変化を知らせる追加の経路 (--on-change) が {str(oce.get('at'))[:16].replace('T', ' ')} に失敗した"
                   f" = スマホ等に届いていない可能性 ({oce['error']})")
    if gone:
        out.append(f"⌛ 期限 (until) を過ぎた見張り {len(gone)} 件 ({', '.join(t['id'] for t in gone)}) → 台帳から外す")
    return out


def show(target: dict, state: dict) -> list[str]:
    s = (state.get("targets") or {}).get(target["id"]) or {}
    if not s.get("baseline"):
        return [f"{label_of(target)}: まだ本文を読めていない"]
    if s.get("latest_hash") == s.get("baseline_hash"):
        return [f"{label_of(target)}: 確認済みの本文から変わっていない"]
    head = [f"{label_of(target)} ({target['url']})", f"最初に気づいた時刻 = {s.get('changed_at')}"]
    return head + list(difflib.unified_diff(s["baseline"], s["latest"], "確認済み", "最新", lineterm="", n=1))


def ack(ledger: dict, state: dict, which: str) -> list[str]:
    done = []
    for t in ledger.get("targets") or []:
        if which not in ("all", t["id"]):
            continue
        s = (state.get("targets") or {}).get(t["id"])
        if not s or "latest" not in s:
            continue
        s.update(baseline=s["latest"], baseline_hash=s.get("latest_hash") or digest(s["latest"]),
                 changed_at=None, notified_hash=None)
        done.append(t["id"])
    return done


def fired_signals(target: dict, s: dict) -> list[str]:
    """確認済みの本文 (baseline) と最新の本文 (latest) を比べ、 決め手の文言の消失・出現を説明文にする。"""
    old = "\n".join(s.get("baseline") or [])
    new = "\n".join(s.get("latest") or [])
    out = []
    for sig in target.get("signals") or []:
        say = f" = {sig['say']}" if sig.get("say") else ""
        if sig.get("gone") and sig["gone"] in old and sig["gone"] not in new:
            out.append(f"「{sig['gone']}」 が消えた{say}")
        if sig.get("appears") and sig["appears"] not in old and sig["appears"] in new:
            out.append(f"「{sig['appears']}」 が出た{say}")
    return out


def message_for(target: dict, s: dict) -> str:
    """通知・ダイアログ・行に共通の文: 何が変わったか + 決め手 + 今すぐやること + 補足。"""
    msg = f"{label_of(target)} が変わった"
    sigs = fired_signals(target, s)
    if sigs:
        msg += f" ({' / '.join(sigs)})"
    if target.get("action"):
        msg += f" → 今すぐ: {target['action']}"
    if target.get("note"):
        msg += f" [{target['note']}]"
    return msg


def notify_macos(messages: list[str], alert: bool = False) -> None:
    """バナー通知 (数秒で消える) を出す。 alert=True なら押すまで消えない警告ダイアログも出す。

    ダイアログは待たずに切り離して起動する (= 定期実行を止めない。 人が居なくても画面に残り続ける)。
    """
    if sys.platform != "darwin" or not messages:
        return
    title = "ページが更新された — 今すぐ対応"
    msg = " / ".join(messages)
    # 投稿は claude-notify.sh へ一本化する (= 直に osascript を呼ぶとスクリプトエディタの
    # 通知になり、 押しても行き先が無い。 conventions/macos-clickable-notifications.md)
    notifier = Path(__file__).resolve().parent / "claude-notify.sh"
    if notifier.exists():
        cmd = ["sh", str(notifier), "--title", title, "--body", msg, "--sound", "Glass"]
    else:
        script = ['on run argv',
                  'display notification (item 2 of argv) with title (item 1 of argv) sound name "Glass"',
                  'end run']
        cmd = ["osascript"] + sum((["-e", ln] for ln in script), []) + [title, msg]
    try:
        subprocess.run(cmd, check=False, timeout=30, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        pass
    if not alert:
        return
    body = "\n\n".join(messages)
    ascript = ['on run argv', 'activate',
               'display alert (item 1 of argv) message (item 2 of argv) as critical buttons {"確認した"}',
               'end run']
    acmd = ["osascript"] + sum((["-e", ln] for ln in ascript), []) + [title, body]
    try:
        subprocess.Popen(acmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def run_on_change(command: str, messages: list[str], timeout: int = 300) -> str | None:
    """知らせる文があれば command を実行する (引数の末尾に通知文を 1 つずつ足す)。

    別の経路 (スマホへの通知など) を呼び出し側が差し込む口。 失敗しても巡回は続ける。
    """
    if not command or not messages:
        return None
    import shlex  # noqa: PLC0415
    try:
        r = subprocess.run(shlex.split(command) + list(messages), check=False, timeout=timeout,
                           capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return f"⚠️ web-page-watch: --on-change を実行できない ({type(e).__name__}: {e})"
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or [""]
        return f"⚠️ web-page-watch: --on-change が失敗 (exit {r.returncode}: {tail[0][:200]})"
    return None


def run_probe(command: str, timeout: int = 60) -> str | None:
    """--probe の CMD を実行する。 成功 (exit 0) なら None、 失敗なら理由 1 行。"""
    import shlex  # noqa: PLC0415
    try:
        r = subprocess.run(shlex.split(command), check=False, timeout=timeout, capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return f"実行できない ({type(e).__name__}: {e})"
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or [""]
        return f"exit {r.returncode}: {tail[0][:200]}"
    return None


def main(argv: list[str] | None = None, *, fetch=fetch_url, notifier=notify_macos, on_change=run_on_change,
         probe=run_probe, now: str | None = None, prog: str | None = None) -> int:
    ap = argparse.ArgumentParser(prog=prog, description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--surface", action="store_true", help="network に出ず state だけから出す")
    g.add_argument("--show", metavar="ID")
    g.add_argument("--ack", metavar="ID")
    g.add_argument("--selftest", action="store_true")
    ap.add_argument("--ledger", help="台帳 (YAML / JSON)")
    ap.add_argument("--notify", action="store_true", help="新しい本文を見つけたら macOS 通知")
    ap.add_argument("--alert", action="store_true", help="--notify に加えて、 押すまで消えない警告ダイアログを出す")
    ap.add_argument("--on-change", metavar="CMD", help="新しい本文を見つけたら CMD を実行 (引数の末尾に「label → note」)")
    ap.add_argument("--probe", metavar="CMD",
                    help="巡回のたびに CMD を実行し、 失敗なら「追加の経路が使えない状態」 を ⚠️ で出す "
                         "(= 変化が起きてから経路の故障に気づくのでは遅い。 CMD は token を使わない軽い検査にする)")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.ledger:
        ap.error("--ledger が要る")
    prog = prog or os.path.basename(sys.argv[0] or "web-page-watch.py")
    ledger_path = Path(os.path.expanduser(a.ledger))
    try:
        ledger = load_ledger(ledger_path)
    except Exception as e:  # noqa: BLE001 (fail-open)
        print(f"⚠️ web-page-watch: 台帳を読めない ({ledger_path}: {e})")
        return 0
    sp = state_path_of(ledger_path, ledger)
    state = read_state(sp)
    by_id = {t["id"]: t for t in ledger.get("targets") or []}
    if a.show:
        t = by_id.get(a.show)
        print("\n".join(show(t, state)) if t else f"台帳に無い id: {a.show}")
        return 0
    if a.ack:
        done = ack(ledger, state, a.ack)
        if done:
            write_state(sp, state)
        print(f"確認済みにした: {', '.join(done)}" if done else f"確認済みにできる変化が無い: {a.ack}")
        return 0
    if not a.surface:
        fresh = check(ledger, state, fetch=fetch, now=now)
        st_targets = state.get("targets") or {}
        all_msgs = [message_for(t, st_targets.get(t["id"]) or {}) for t in fresh]
        urgent_msgs = [message_for(t, st_targets.get(t["id"]) or {}) for t in fresh if t.get("urgent")]
        if a.notify or a.alert:
            notifier(all_msgs, alert=bool(a.alert and urgent_msgs))
        if a.on_change and urgent_msgs:
            err = on_change(a.on_change, urgent_msgs)
            # 追加の経路の失敗は log だけでなく state に残し、 surface / dashboard に出し続ける (= 黙って落ちない)。
            # 次に成功した時点で消える
            state["on_change_error"] = {"at": now or now_iso(), "error": err} if err else None
            if err:
                print(err)
        if a.probe:
            perr = probe(a.probe)
            state["probe_error"] = {"at": now or now_iso(), "error": perr} if perr else None
            if perr:
                print(perr)
        try:
            write_state(sp, state)
        except OSError as e:
            print(f"⚠️ web-page-watch: state を書けない ({sp}: {e})")
    lines = report(ledger, state, surface=a.surface, prog=prog, ledger_arg=a.ledger, now=now)
    if lines:
        print("\n".join(lines))
    return 0


def selftest() -> int:  # noqa: PLR0915
    fails: list[str] = []

    def ok(cond: bool, name: str) -> None:
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    def page(body: str, nav: str = "ナビ", foot: str = "フッタ") -> str:
        return (f"<html><head><style>.x{{}}</style><script>var t=1;</script></head><body><div>{nav}</div>"
                f"<p>更新日：2026年1月1日</p>{body}<p>お問い合わせ</p><div>{foot}</div></body></html>")

    # html_to_lines + extract: script / style を落とし、 目印の間だけ取る
    lines = html_to_lines(page("<p>受付を中止しています。</p><br>再開は本ページで"))
    body = extract(lines, "更新日", "お問い合わせ")
    ok(body == ["更新日：2026年1月1日", "受付を中止しています。", "再開は本ページで"], "extract between markers")
    ok(not any("var t" in ln for ln in lines), "script dropped")
    try:
        extract(lines, "存在しない", None)
        ok(False, "missing start marker raises")
    except MarkerMissing:
        ok(True, "missing start marker raises")

    with tempfile.TemporaryDirectory() as d:
        led = Path(d) / "watch.json"
        led.write_text(json.dumps({"state": str(Path(d) / "s.json"), "targets": [
            {"id": "a", "url": "u:a", "label": "ページA", "start": "更新日", "end": "お問い合わせ",
             "action": "申請する", "urgent": True, "note": "TODO-1",
             "signals": [{"gone": "受付を中止しています", "say": "受付再開の可能性"},
                         {"appears": "存在しない文言", "say": "出ない"}]},
            {"id": "b", "url": "u:b", "label": "ページB", "action": "日程を見る"},
            {"id": "old", "url": "u:old", "until": "2026-01-01"},
        ]}), encoding="utf-8")
        pages = {"u:a": page("<p>受付を中止しています。</p>"), "u:b": "<p>日程 10/9</p>"}
        fetched: list[str] = []
        notified: list[list[str]] = []

        def fetch(url: str) -> str:
            fetched.append(url)
            v = pages[url]
            if isinstance(v, Exception):
                raise v
            return v

        alerts: list[bool] = []
        hooked: list[tuple[str, list[str]]] = []

        def notifier(msgs: list[str], alert: bool = False) -> None:
            if msgs:
                notified.append(list(msgs))
                alerts.append(alert)

        def on_change(cmd: str, msgs: list[str]) -> str | None:
            if not msgs:
                return None
            hooked.append((cmd, list(msgs)))
            return "⚠️ 差し込み失敗" if cmd == "broken" else None

        def changed(o: str) -> bool:
            return "🚨" in o or "🔔" in o

        def run(*args: str, when: str = "2026-10-01T12:00:00+09:00") -> str:
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                main(["--ledger", str(led), *args], fetch=fetch, notifier=notifier, on_change=on_change,
                     probe=lambda cmd: "未ログイン" if cmd == "bad-probe" else None, now=when, prog="wpw")
            return buf.getvalue()

        out = run("--notify")
        ok(not changed(out) and not notified, "first read = baseline only")
        ok("u:old" not in fetched and "⌛" in out, "expired target skipped and reported")
        ok("⏸️" not in run("--surface"), "fresh run not stale")

        pages["u:a"] = page("<p>受付を中止しています。</p>", nav="ナビ変更", foot="フッタ変更")
        out = run("--notify")
        ok(not changed(out) and not notified, "change outside markers ignored")

        pages["u:a"] = page("<p>申請受付を再開しました。</p>")
        out = run("--notify", "--alert", "--on-change", "push-cmd")
        ok("🚨 ページA が変わった (「受付を中止しています」 が消えた = 受付再開の可能性) → 今すぐ: 申請する [TODO-1]" in out and len(notified) == 1, "urgent change line = signal + action + note")
        ok(alerts == [True], "--alert raises dialog for urgent target")
        ok(hooked == [("push-cmd", ["ページA が変わった (「受付を中止しています」 が消えた = 受付再開の可能性) → 今すぐ: 申請する [TODO-1]"])], "--on-change gets the full message")
        ok("出ない" not in out, "signal that did not fire is not shown")
        run("--notify", "--alert", "--on-change", "push-cmd")
        ok(len(notified) == 1 and len(hooked) == 1, "same new body not re-notified nor re-hooked")
        ok("🚨" in run("--surface"), "pending change persists in surface")
        diff = run("--show", "a")
        ok("-受付を中止しています。" in diff and "+申請受付を再開しました。" in diff, "show gives diff")

        pages["u:a"] = page("<p>申請受付を再開しました。残り 5 件</p>")
        out = run("--notify", "--on-change", "broken")
        ok(len(notified) == 2, "further change before ack re-notifies")
        ok("⚠️ 差し込み失敗" in out, "on-change failure printed")
        ok("追加の経路 (--on-change) が" in run("--surface"), "on-change failure persists in surface")

        pages["u:a"] = page("<p>受付を中止しています。</p>")
        out = run("--notify")
        ok(not changed(out), "reverting to baseline clears pending")

        pages["u:a"] = page("<p>申請受付を再開しました。</p>")
        run()
        ok("確認済みにした: a" in run("--ack", "a") and not changed(run("--surface")), "ack clears")
        run()
        ok(not changed(run("--surface")), "acked body is new baseline")
        ok("追加の経路" in run("--surface"), "on-change failure survives ack")
        pages["u:a"] = page("<p>申請受付を再開しました。予算の残りあり</p>")
        run("--notify", "--on-change", "push-cmd")
        ok("追加の経路" not in run("--surface"), "successful on-change clears the failure")
        run("--ack", "a")

        pages["u:a"] = OSError("timeout")
        run()
        run()
        ok("⚠️" not in run("--surface"), "two fetch errors stay quiet")
        run()
        ok("⚠️ ページA を 3 回続けて読めていない" in run("--surface"), "third fetch error warns")
        pages["u:a"] = page("<p>申請受付を再開しました。</p>")
        run()
        ok("⚠️" not in run("--surface"), "success resets error count")

        pages["u:a"] = "<html><body><p>作りが変わった</p></body></html>"
        run()
        ok("⚠️ ページA を 1 回続けて読めていない" in run("--surface"), "marker missing warns at once")

        out = run("--surface", when="2026-10-05T12:00:00+09:00")
        ok("⏸️" in out and "時間前" in out, "stale last_run warns in surface")
        ok("⏸️" not in run(when="2026-10-05T12:00:00+09:00"), "stale line only in surface")
        run("--probe", "bad-probe", when="2026-10-05T12:10:00+09:00")
        ok("使えない状態" in run("--surface", when="2026-10-05T12:20:00+09:00"), "failing probe warns before any change")
        run("--probe", "good-probe", when="2026-10-05T12:30:00+09:00")
        ok("使えない状態" not in run("--surface", when="2026-10-05T12:40:00+09:00"), "passing probe clears the warning")
        ok(run_probe("true") is None and "exit 1" in (run_probe("false") or ""), "run_probe maps exit status")

        n_before, h_before = len(notified), len(hooked)
        pages["u:b"] = "<p>日程 10/13</p>"
        out = run("--notify", "--alert", "--on-change", "push-cmd", when="2026-10-05T13:00:00+09:00")
        ok("🔔 ページB が変わった → 今すぐ: 日程を見る" in out, "non-urgent change = 🔔 with action")
        ok(len(notified) == n_before + 1 and alerts[-1] is False and len(hooked) == h_before,
           "non-urgent: banner only, no dialog, no on-change")

        led2 = Path(d) / "never.json"
        led2.write_text(json.dumps({"state": str(Path(d) / "s2.json"),
                                    "targets": [{"id": "b", "url": "u:b"}]}), encoding="utf-8")
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["--ledger", str(led2), "--surface"], fetch=fetch, now="2026-10-01T12:00:00+09:00", prog="wpw")
        ok("まだ一度も巡回していない" in buf.getvalue(), "never-run surface warns")
        ok(not (Path(d) / "s2.json").exists(), "surface does not write state")

    # run_on_change: 実コマンドの成否 (失敗は ⚠️ 1 行、 対象が無ければ呼ばない)
    t1 = ["X が変わった → 今すぐ: N"]
    ok(run_on_change("true", t1) is None, "on-change success is quiet")
    err = run_on_change("false", t1)
    ok(bool(err) and "exit 1" in err, "on-change failure reported")
    ok(run_on_change("false", []) is None, "on-change not called without changes")
    ok("実行できない" in (run_on_change("/nonexistent/cmd-xyz", t1) or ""), "on-change missing command reported")

    # 実際の state の既定の置き場は台帳ごとに分かれる
    ok(default_state_path(Path("/x/foo.yaml")).name == "foo.json", "default state path per ledger")
    # charset: meta の charset で decode する
    sj = '<meta charset="shift_jis"><p>受付</p>'.encode("shift_jis")

    class R:
        def __init__(self):
            self.headers = type("H", (), {"get_content_charset": staticmethod(lambda: None)})()

        def read(self):
            return sj

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    orig = urllib.request.urlopen
    urllib.request.urlopen = lambda *a, **k: R()  # type: ignore[assignment]
    try:
        ok("受付" in fetch_url("http://example.invalid/"), "meta charset decode")
    finally:
        urllib.request.urlopen = orig  # type: ignore[assignment]

    print(f"\n{'OK' if not fails else 'NG'}: {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
