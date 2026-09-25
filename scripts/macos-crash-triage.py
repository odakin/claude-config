#!/usr/bin/env python3
"""macos-crash-triage.py — macOS のアプリ crash report (.ips) を、 Chromium の Crashpad crash key と unified log で裏付けて型に分ける (読むだけ)。--selftest 内蔵。 conventions/macos-app-crash-triage.md

用途: 「予期しない理由で終了しました」 が出たとき、 原因を言う前に証拠を 1 コマンドで揃える。
アプリの起動・終了・設定変更はしない。 型の意味と、 型が決まった後に確かめること (= ベンダーの
不具合と言う前の除外) は conventions/macos-app-crash-triage.md が正本。

読むもの:
  - <home>/Library/Logs/DiagnosticReports/<App>-*.ips と /Library/Logs/DiagnosticReports の読める分
    (.ips = 1 行目が header JSON、 2 行目以降が本体 JSON。 本体の後ろに別の JSON が続くことがあるので
    raw_decode で先頭の 1 個だけ読む)
  - Chromium 系の Crashpad dump (<home>/Library/Application Support/**/Crashpad/completed/*.dmp) の
    crash key (ver / ptype / switch-N) と FATAL 行。 report の時刻 ±10 秒の dump を対応づける
  - --log のとき unified log (/usr/bin/log。 zsh では素の `log` が組み込み関数に取られる) の、
    起動 90 秒前〜落ちた 2 秒後の 更新器・起動要求・窓の有無・process death
  - --app のとき、 report の有無に関わらず起動中の本体 process (ps + lsof)。 crash を残さない
    「開いても何も起きない」 型の印: headless-orphan (自動化の headless が親を失って残る) /
    stale-binary (更新で置き換わった旧版の binary のまま動いている) / no-startup-window (窓なしで起動された)

型 (class):
  startup-during-bundle-replacement  起動 5 秒以内に落ち、 report に版番号が無い (= report を書いた瞬間に
                                      bundle が読めなかった) か、 crash key の版が report の版と違う
  startup-abort-app-registration     起動直後に HIServices の RegisterApplication / TransformProcessType で abort
                                      (= window server に登録できない文脈から起動された)
  startup-crash                      起動 5 秒以内だが上の 2 つの印が無い
  runtime-crash                      しばらく動いてから落ちた

使い方:
  macos-crash-triage.py --app "Example Browser" [--days 14] [--log] [--json]
  macos-crash-triage.py --report path/to/App-2026-01-01-000000.ips [--log]
  macos-crash-triage.py --selftest

exit: 0 = 読めた (report 0 件も 0) / 2 = 引数・環境の誤り
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

STARTUP_SECONDS = 5.0
DUMP_MATCH_SECONDS = 10.0
LOG_BEFORE_SECONDS = 90
LOG_AFTER_SECONDS = 2
SYSTEM_REPORTS = Path("/Library/Logs/DiagnosticReports")
DOC = "conventions/macos-app-crash-triage.md"
CLASS_ANCHOR = {
    "startup-during-bundle-replacement": "#update-relaunch-race",
    "startup-abort-app-registration": "#startup-abort-app-registration",
    "startup-crash": "#crash-shape-classes",
    "runtime-crash": "#crash-shape-classes",
}
VERSION_RE = re.compile(r"^\d+(\.\d+){1,3}$")
TIME_FORMATS = ("%Y-%m-%d %H:%M:%S.%f %z", "%Y-%m-%d %H:%M:%S %z")


def parse_time(text: str | None) -> dt.datetime | None:
    if not text:
        return None
    for fmt in TIME_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_ips(text: str) -> tuple[dict, dict]:
    first, _, rest = text.partition("\n")
    header = json.loads(first)
    rest = rest.lstrip()
    if not rest:
        return header, {}
    try:
        body, _ = json.JSONDecoder().raw_decode(rest)
    except json.JSONDecodeError:
        body = {}
    return header, body if isinstance(body, dict) else {}


def app_bundle_of(proc_path: str | None) -> Path | None:
    if not proc_path or ".app/" not in proc_path:
        return None
    return Path(proc_path[: proc_path.index(".app/") + 4])


def bundle_info(bundle: Path | None) -> dict:
    if bundle is None:
        return {}
    try:
        with (bundle / "Contents" / "Info.plist").open("rb") as handle:
            return plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return {}


def top_frames(body: dict, limit: int = 8) -> list[str]:
    threads = body.get("threads") or []
    index = body.get("faultingThread")
    if not isinstance(index, int) or index >= len(threads):
        return []
    images = body.get("usedImages") or []
    frames = []
    for frame in threads[index].get("frames", [])[:limit]:
        image_index = frame.get("imageIndex")
        image = images[image_index].get("name", "?") if isinstance(image_index, int) and image_index < len(images) else "?"
        frames.append(f"{image} {frame.get('symbol', '?')}")
    return frames


def printable_strings(data: bytes) -> list[tuple[int, str]]:
    return [(m.start(), m.group().decode("ascii")) for m in re.finditer(rb"[\x20-\x7e]{2,}", data)]


def crashpad_keys(data: bytes) -> dict:
    """crash key は「key の文字列の直後に value の文字列」 で並ぶ。 value は形で検証する (雑音を拾わない)。"""
    strings = printable_strings(data)
    keys: dict = {"switches": [], "fatal": []}
    for i, (offset, text) in enumerate(strings):
        if ":FATAL:" in text and text not in keys["fatal"]:
            keys["fatal"].append(text[:300])
        if i + 1 >= len(strings):
            continue
        next_offset, value = strings[i + 1]
        if next_offset - (offset + len(text)) > 64:
            continue
        if text == "ver" and VERSION_RE.match(value) and "ver" not in keys:
            keys["ver"] = value
        elif text == "ptype" and re.match(r"^[a-z-]+$", value) and "ptype" not in keys:
            keys["ptype"] = value
        elif re.fullmatch(r"switch-\d+", text) and value.startswith("--"):
            keys["switches"].append((int(text.split("-")[1]), value))
    keys["switches"] = [value for _, value in sorted(set(keys["switches"]))]
    return keys


def crashpad_dirs(home: Path) -> list[Path]:
    base = home / "Library" / "Application Support"
    found: list[Path] = []
    for pattern in ("*/Crashpad/completed", "*/*/Crashpad/completed"):
        found.extend(p for p in base.glob(pattern) if p.is_dir())
    return sorted(set(found))


def match_dump(dirs: list[Path], captured: dt.datetime | None) -> Path | None:
    if captured is None:
        return None
    target = captured.timestamp()
    best: tuple[float, Path] | None = None
    for directory in dirs:
        for dump in directory.glob("*.dmp"):
            try:
                gap = abs(dump.stat().st_mtime - target)
            except OSError:
                continue
            if gap <= DUMP_MATCH_SECONDS and (best is None or gap < best[0]):
                best = (gap, dump)
    return best[1] if best else None


def classify(record: dict) -> tuple[str, list[str]]:
    reasons: list[str] = []
    parent = record.get("parent")
    if parent and parent != "launchd":
        reasons.append(f"parent process = {parent} (launchd でなく別の program から起動)")
    lifetime = record.get("lifetime_s")
    if lifetime is None or lifetime > STARTUP_SECONDS:
        return "runtime-crash", reasons
    frames = " ".join(record.get("top_frames", []))
    if "RegisterApplication" in frames or "TransformProcessType" in frames:
        reasons.insert(0, "faulting thread が RegisterApplication / TransformProcessType で abort")
        return "startup-abort-app-registration", reasons
    key_version = record.get("crash_keys", {}).get("ver")
    report_version = record.get("report_version")
    marks = []
    if not report_version:
        marks.append("report に版番号が無い (report を書いた瞬間に bundle の Info.plist が読めなかった)")
    elif key_version and key_version != report_version:
        marks.append(f"crash key の版 {key_version} ≠ report の版 {report_version} (bundle と違うコードが動いた)")
    if marks:
        if "--no-startup-window" in record.get("crash_keys", {}).get("switches", []):
            marks.append("--no-startup-window で起動 (窓なしの再起動)")
        return "startup-during-bundle-replacement", marks + reasons
    return "startup-crash", reasons


def build_record(path: Path, dump_dirs: list[Path]) -> dict | None:
    try:
        header, body = parse_ips(path.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    launched = parse_time(body.get("procLaunch"))
    captured = parse_time(body.get("captureTime")) or parse_time(header.get("timestamp"))
    exception = body.get("exception") or {}
    bundle = app_bundle_of(body.get("procPath"))
    info = bundle_info(bundle)
    record = {
        "report": str(path),
        "process": body.get("procName") or header.get("app_name"),
        "pid": body.get("pid"),
        "bundle_id": header.get("bundleID") or info.get("CFBundleIdentifier"),
        "launched": launched.isoformat() if launched else None,
        "captured": captured.isoformat() if captured else None,
        "lifetime_s": round((captured - launched).total_seconds(), 2) if launched and captured else None,
        "role": body.get("procRole"),
        "parent": body.get("parentProc"),
        "report_version": header.get("app_version") or "",
        "installed_version": info.get("CFBundleShortVersionString"),
        "exception": "/".join(x for x in (exception.get("type"), exception.get("signal")) if x),
        "termination": (body.get("termination") or {}).get("indicator"),
        "asi": [m for values in (body.get("asi") or {}).values() for m in values],
        "top_frames": top_frames(body),
        "crash_keys": {},
        "dump": None,
    }
    dump = match_dump(dump_dirs, captured)
    if dump is not None:
        try:
            record["crash_keys"] = crashpad_keys(dump.read_bytes())
            record["dump"] = str(dump)
        except OSError:
            pass
    record["class"], record["reasons"] = classify(record)
    record["next"] = DOC + CLASS_ANCHOR[record["class"]]
    return record


LOG_KEEP = ("Autoupdate", "sparkle", "LS launch", "TALKey", "exit handler", "Process death", "QUITTING")


def log_window(record: dict) -> list[str]:
    launched = record.get("launched") and dt.datetime.fromisoformat(record["launched"])
    captured = record.get("captured") and dt.datetime.fromisoformat(record["captured"])
    if not launched or not captured:
        return []
    start = (launched - dt.timedelta(seconds=LOG_BEFORE_SECONDS)).astimezone()
    end = (captured + dt.timedelta(seconds=LOG_AFTER_SECONDS)).astimezone()
    name = (record.get("process") or "").replace('"', "")
    bundle_id = (record.get("bundle_id") or "").replace('"', "")
    predicate = (
        'process == "Autoupdate" OR subsystem CONTAINS[c] "sparkle" '
        f'OR (process == "runningboardd" AND eventMessage CONTAINS "LS launch {bundle_id}") '
        'OR (process == "launchservicesd" AND eventMessage CONTAINS "QUITTING") '
        f'OR (process == "{name}" AND (eventMessage CONTAINS "TALKey" OR eventMessage CONTAINS "exit handler")) '
        'OR (process == "WindowServer" AND eventMessage CONTAINS "Process death")'
    )
    command = ["/usr/bin/log", "show", "--style", "compact",
               "--start", start.strftime("%Y-%m-%d %H:%M:%S"),  # log show は小数秒を受けない
               "--end", end.strftime("%Y-%m-%d %H:%M:%S"), "--predicate", predicate]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as error:
        return [f"(log show を実行できなかった: {error})"]
    return filter_log_lines(result.stdout.splitlines(), name)


def filter_log_lines(raw: list[str], name: str) -> list[str]:
    """更新器は最初の 1 行と sparkle の行だけ、 QUITTING は対象アプリ (と同名 helper) の pid だけ残す。"""
    lines = [line for line in raw if line[:4].isdigit() and any(key in line for key in LOG_KEEP)]
    app_pids = set(re.findall(r"Process death: \S+ \(" + re.escape(name) + r"[^)]*\) .*?pid: (\d+)", "\n".join(lines)))
    kept: list[str] = []
    seen_updater = False
    for line in lines:
        if " Autoupdate[" in line and "sparkle" not in line.lower():
            if seen_updater:
                continue
            seen_updater = True
        quitting = re.search(r"QUITTING: pid=(\d+)", line)
        if quitting and quitting.group(1) not in app_pids:
            continue
        kept.append(line[:220])
    if not kept:
        return ["(該当行なし — unified log の保持期間を過ぎた可能性。 null は「起きなかった」 の証拠にならない)"]
    return kept[:40]


def render(record: dict) -> None:
    keys = record["crash_keys"]
    print(f"== {record['captured']}  {record['process']}  lifetime={record['lifetime_s']}s  "
          f"role={record['role']}  parent={record['parent']}")
    print(f"  report: {record['report']}")
    print(f"  version: report={record['report_version'] or '(empty)'}  crash-key={keys.get('ver', '-')}  "
          f"installed now={record['installed_version'] or '-'}")
    print(f"  exception: {record['exception'] or '-'}  termination: {record['termination'] or '-'}  "
          f"asi: {'; '.join(record['asi']) or '-'}")
    if record["top_frames"]:
        print(f"  top frames: {' | '.join(record['top_frames'][:5])}")
    if keys.get("switches"):
        print(f"  switches: {' '.join(keys['switches'][:6])}")
    for fatal in keys.get("fatal", [])[:2]:
        print(f"  FATAL: {fatal}")
    print(f"  class: {record['class']}  → {record['next']}")
    for reason in record["reasons"]:
        print(f"    - {reason}")
    for line in record.get("log", []):
        print(f"    log| {line}")


# ---------------------------------------------------------------- 起動中の process (開いても何も起きない型)

LIVE_ANCHOR = DOC + "#launch-does-nothing"


def live_processes(app: str, ps_output: str, running_inode, disk_inode) -> list[dict]:
    """`ps -axo pid=,ppid=,etime=,args=` から、 <app>.app の本体 (helper でない) の起動中 process を拾って印を付ける。

    running_inode(pid, path) = その process が実行中の binary の inode (取れなければ None)、
    disk_inode(path) = 同じ path に今ある file の inode (無ければ None)。 test のため注入する。
    """
    exe = re.compile(rf"^(.*?/{re.escape(app)}\.app/Contents/MacOS/{re.escape(app)})(?=\s|$)")
    found = []
    for line in ps_output.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4 or not parts[0].isdigit():
            continue
        m = exe.match(parts[3])
        if not m:
            continue
        pid, path, args = int(parts[0]), m.group(1), parts[3][m.end():].split()
        marks = []
        if "--headless" in args:
            marks.append("headless-orphan" if parts[1] == "1" else "headless")
        running, on_disk = running_inode(pid, path), disk_inode(path)
        if running is not None and running != on_disk:
            marks.append("stale-binary")
        if "--no-startup-window" in args:
            marks.append("no-startup-window")
        found.append({"pid": pid, "ppid": int(parts[1]), "etime": parts[2], "path": path, "marks": marks,
                      "running_inode": running, "disk_inode": on_disk})
    return found


LIVE_MEANING = {
    "headless-orphan": "画面を持たない自動化の browser が、 呼び元が消えた後も残っている (Dock から開いても窓の無いこれが前に出る)",
    "headless": "画面を持たない自動化の browser (呼び元は生きている = 今走っている処理かもしれない)",
    "stale-binary": "実行中の binary が、 今 disk にある版と別物 (更新で置き換えられた旧版のまま動いている)",
    "no-startup-window": "窓を開かない指定で起動された (更新の再起動・背景の再起動の形)",
}


def _lsof_exe_inode(pid: int, path: str) -> int | None:
    try:
        out = subprocess.run(["/usr/sbin/lsof", "-a", "-p", str(pid), "-d", "txt", "-F", "in"],
                             capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    inode = None
    for line in out.splitlines():
        if line.startswith("i"):
            inode = line[1:]
        elif line.startswith("n") and line[1:] == path and inode and inode.isdigit():
            return int(inode)
    return None


def _disk_inode(path: str) -> int | None:
    try:
        return os.stat(path).st_ino
    except OSError:
        return None


def render_live(app: str) -> None:
    try:
        ps = subprocess.run(["/bin/ps", "-axo", "pid=,ppid=,etime=,args="], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"起動中の process: 見られなかった ({e})")
        return
    procs = live_processes(app, ps, _lsof_exe_inode, _disk_inode)
    if not procs:
        print(f"起動中の {app}: なし")
        return
    print(f"起動中の {app} (本体の process):")
    for p in procs:
        print(f"  pid {p['pid']}  ppid {p['ppid']}  経過 {p['etime']}  印: {', '.join(p['marks']) or '-'}")
        for mark in p["marks"]:
            print(f"    - {mark}: {LIVE_MEANING[mark]}")
    if any(m in ("headless-orphan", "stale-binary") for p in procs for m in p["marks"]):
        print(f"  → 開いても何も起きない型。 止める前に読むこと = {LIVE_ANCHOR}")


def collect(args: argparse.Namespace, home: Path, system_reports: Path) -> list[dict]:
    if args.report:
        paths = [Path(p) for p in args.report]
    else:
        cutoff = dt.datetime.now().timestamp() - args.days * 86400
        paths = []
        for directory in (home / "Library" / "Logs" / "DiagnosticReports", system_reports):
            try:
                candidates = list(directory.glob(f"{args.app}-*.ips"))
            except OSError:
                continue
            for path in candidates:
                try:
                    if path.stat().st_mtime >= cutoff and os.access(path, os.R_OK):
                        paths.append(path)
                except OSError:
                    continue
    dump_dirs = crashpad_dirs(home)
    records = [r for r in (build_record(p, dump_dirs) for p in paths) if r]
    records.sort(key=lambda r: r["captured"] or "")
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--app", help="report file 名の先頭 (= process 名、 例: 'Example Browser')")
    parser.add_argument("--report", action="append", help=".ips を直接指定 (複数可)")
    parser.add_argument("--days", type=float, default=14)
    parser.add_argument("--log", action="store_true", help="起動直後の crash (登録失敗の abort を除く) に unified log の窓を添える")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--home", type=Path, default=Path.home(), help=argparse.SUPPRESS)
    parser.add_argument("--system-reports", type=Path, default=SYSTEM_REPORTS, help=argparse.SUPPRESS)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.app and not args.report:
        parser.error("--app か --report が要る")
    records = collect(args, args.home, args.system_reports)
    if args.log:
        for record in records:
            if record["class"] in ("startup-during-bundle-replacement", "startup-crash"):  # 登録失敗の abort は更新器と無関係
                record["log"] = log_window(record)
    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return 0
    if not records:
        print(f"report 0 件 (見た場所 = {args.home}/Library/Logs/DiagnosticReports と {args.system_reports} の読める分、 直近 {args.days} 日)")
    else:
        for record in records:
            render(record)
        counts: dict[str, int] = {}
        for record in records:
            counts[record["class"]] = counts.get(record["class"], 0) + 1
        print("-- " + ", ".join(f"{name} {n}" for name, n in sorted(counts.items())))
    if args.app:  # report 0 件でも止めない = 「開いても何も起きない」 は crash を残さない
        render_live(args.app)
    return 0


# ---------------------------------------------------------------- selftest

def _write_ips(path: Path, header: dict, body: dict, trailing: bool = False) -> None:
    text = json.dumps(header) + "\n" + json.dumps(body, indent=1)
    if trailing:
        text += "\n" + json.dumps({"extra": "second object"})  # 実物の .ips には本体の後ろに別 object が続くことがある
    path.write_text(text)


def selftest() -> int:
    checks: list[tuple[str, bool]] = []
    with tempfile.TemporaryDirectory(prefix="macos-crash-triage-") as temporary:
        home = Path(temporary)
        reports = home / "Library" / "Logs" / "DiagnosticReports"
        reports.mkdir(parents=True)
        app = home / "Applications" / "Example Browser.app"
        (app / "Contents").mkdir(parents=True)
        with (app / "Contents" / "Info.plist").open("wb") as handle:
            plistlib.dump({"CFBundleShortVersionString": "2.1.2", "CFBundleIdentifier": "org.example.browser"}, handle)
        proc_path = str(app / "Contents" / "MacOS" / "Example Browser")
        frames_main = {"faultingThread": 0, "usedImages": [{"name": "Example Framework"}],
                       "threads": [{"frames": [{"imageIndex": 0, "symbol": "ChromeMain"}]}]}
        frames_reg = {"faultingThread": 0, "usedImages": [{"name": "HIServices"}],
                      "threads": [{"frames": [{"imageIndex": 0, "symbol": "_RegisterApplication"}]}]}
        base = {"procPath": proc_path, "procName": "Example Browser", "exception": {"type": "EXC_BREAKPOINT", "signal": "SIGTRAP"}}

        race = dict(base, procLaunch="2026-01-02 03:04:05.4644 +0900", captureTime="2026-01-02 03:04:06.1784 +0900",
                    procRole="Background", parentProc="launchd", **frames_main)
        _write_ips(reports / "Example Browser-race.ips", {"app_name": "Example Browser", "app_version": ""}, race, trailing=True)
        register = dict(base, procLaunch="2026-01-03 10:00:00.00 +0900", captureTime="2026-01-03 10:00:00.40 +0900",
                        parentProc="Python", asi={"libsystem_c.dylib": ["abort() called"]}, **frames_reg)
        _write_ips(reports / "Example Browser-register.ips", {"app_version": "2.1.1"}, register)
        runtime = dict(base, procLaunch="2026-01-04 08:00:00.0 +0900", captureTime="2026-01-04 13:00:00.0 +0900",
                       parentProc="launchd", **frames_main)
        _write_ips(reports / "Example Browser-runtime.ips", {"app_version": "2.1.1"}, runtime)
        plain = dict(base, procLaunch="2026-01-05 08:00:00.0 +0900", captureTime="2026-01-05 08:00:01.0 +0900",
                     parentProc="launchd", **frames_main)
        _write_ips(reports / "Example Browser-plain.ips", {"app_version": "2.1.1"}, plain)
        (reports / "Other App-race.ips").write_text(json.dumps({"app_version": ""}) + "\n{}")

        dumps = home / "Library" / "Application Support" / "Example" / "Example-Browser" / "Crashpad" / "completed"
        dumps.mkdir(parents=True)
        dump = dumps / "a.dmp"
        dump.write_bytes(b"\x00\x01ver\x00\x002.1.1\x00\x07switch-2\x00--disable-domain-reliability\x00"
                         b"switch-1\x00--no-startup-window\x00ptype\x00browser\x00noise ver\x00"
                         b"[1:2:0102/030406.1:FATAL:gpu/manager.cc:417] GPU process isn't usable. Goodbye.\x00")
        captured = parse_time(race["captureTime"]).timestamp()
        os.utime(dump, (captured + 3, captured + 3))
        far = dumps / "far.dmp"
        far.write_bytes(b"ver\x009.9.9\x00")
        os.utime(far, (captured + 3600, captured + 3600))

        args = argparse.Namespace(report=None, app="Example Browser", days=100000)
        records = {Path(r["report"]).stem.split("-")[-1]: r for r in collect(args, home, home / "no-system")}
        checks.append(("collect: --app の接頭辞だけ拾う (Other App を読まない)", set(records) == {"race", "register", "runtime", "plain"}))
        r = records.get("race", {})
        checks.append(("parse: 本体の後ろに別 JSON があっても読む + 小数 4 桁の時刻", r.get("lifetime_s") == 0.71))
        checks.append(("dump: ±10 秒の dump だけ対応づける", r.get("crash_keys", {}).get("ver") == "2.1.1"))
        checks.append(("keys: switch を番号順 + ptype", r.get("crash_keys", {}).get("switches") == ["--no-startup-window", "--disable-domain-reliability"]
                       and r.get("crash_keys", {}).get("ptype") == "browser"))
        checks.append(("keys: FATAL 行", any("GPU process isn't usable" in f for f in r.get("crash_keys", {}).get("fatal", []))))
        checks.append(("class: 版番号の無い起動直後 = bundle 差し替え中", r.get("class") == "startup-during-bundle-replacement"))
        checks.append(("class: 窓なし再起動を理由に添える", any("--no-startup-window" in x for x in r.get("reasons", []))))
        checks.append(("installed: procPath の bundle から今の版", r.get("installed_version") == "2.1.2"))
        g = records.get("register", {})
        checks.append(("class: RegisterApplication abort は版より先に判定", g.get("class") == "startup-abort-app-registration"))
        checks.append(("reasons: launchd 以外の親を出す", any("Python" in x for x in g.get("reasons", []))))
        checks.append(("class: 長く動いた後は runtime", records.get("runtime", {}).get("class") == "runtime-crash"))
        checks.append(("class: 印の無い起動直後は startup-crash (foil)", records.get("plain", {}).get("class") == "startup-crash"))
        mismatch = dict(records.get("plain", {}), report_version="2.1.1", crash_keys={"ver": "2.1.0", "switches": []}, reasons=[])
        checks.append(("class: crash key の版 ≠ report の版も差し替え中", classify(mismatch)[0] == "startup-during-bundle-replacement"))
        checks.append(("log: log show に小数秒を渡さない", "." not in (parse_time(race["captureTime"]).astimezone().strftime("%Y-%m-%d %H:%M:%S"))))
        checks.append(("next: 型ごとに正本の anchor", r.get("next") == DOC + "#update-relaunch-race"))
        sample = [
            "2026-01-02 03:04:05.1 Df WindowServer[1:2] x: Process death: 0x0-0x1 (Wallpaper) connectionID: A pid: 11 in session 0x101",
            "2026-01-02 03:04:05.2 Df launchservicesd[3:4] x: QUITTING: pid=11 asn=0x-0x1 foreground=0 wasFront=0",
            "2026-01-02 03:04:05.3 Df WindowServer[1:2] x: Process death: 0x0-0x2 (Example Browser) connectionID: B pid: 22 in session 0x101",
            "2026-01-02 03:04:05.4 Df launchservicesd[3:4] x: QUITTING: pid=22 asn=0x-0x2 foreground=1 wasFront=0",
            "2026-01-02 03:04:05.5 Df Autoupdate[5:6] x: activating connection",
            "2026-01-02 03:04:05.6 Df Autoupdate[5:6] x: activating another connection",
            "2026-01-02 03:04:05.7 Df Autoupdate[5:6] [org.sparkle-project.Sparkle:Sparkle] PID to listen: 22",
            "Timestamp               Ty Process[PID:TID]",
        ]
        kept = filter_log_lines(sample, "Example Browser")
        checks.append(("log filter: QUITTING は対象アプリの pid だけ", any("pid=22" in x for x in kept) and not any("pid=11" in x for x in kept)))
        checks.append(("log filter: 更新器は先頭 1 行 + sparkle 行", sum(" Autoupdate[" in x for x in kept) == 2 and any("PID to listen" in x for x in kept)))
        checks.append(("log filter: 他 process の death は残す (偶然の同時刻を見るため)", any("(Wallpaper)" in x for x in kept)))
        checks.append(("log filter: 空なら「null は証拠にならない」", "証拠にならない" in filter_log_lines(["Timestamp"], "X")[0]))
        exe = "/Applications/Example Browser.app/Contents/MacOS/Example Browser"
        helper = "/Applications/Example Browser.app/Contents/Frameworks/F.framework/Helpers/Example Browser Helper.app/Contents/MacOS/Example Browser Helper"
        ps = "\n".join([
            f"  101     1 19:39:04 {exe} --headless --print-to-pdf=/t/o.pdf --user-data-dir=/t/p",
            f"  102   500    01:00 {exe} --headless --print-to-pdf=/t/o2.pdf",
            f"  103     1    11:11 {exe} --no-startup-window --disable-domain-reliability",
            f"  104     1    00:25 {exe}",
            f"  105   104    00:25 {helper} --type=renderer",
            f"  106     1    00:01 /Applications/Example Browser Beta.app/Contents/MacOS/Example Browser Beta",
        ])
        inodes = {101: 7, 102: 7, 103: 5, 104: 7}
        live = {p["pid"]: p["marks"] for p in live_processes("Example Browser", ps, lambda pid, path: inodes.get(pid), lambda path: 7)}
        checks.append(("live: 本体だけ拾う (helper・名前の似た別アプリは拾わない)", set(live) == {101, 102, 103, 104}))
        checks.append(("live: 親を失った headless", live.get(101) == ["headless-orphan"]))
        checks.append(("live: 親が生きている headless は orphan と言わない", live.get(102) == ["headless"]))
        checks.append(("live: 更新で置き換わった旧版 + 窓なし起動", live.get(103) == ["stale-binary", "no-startup-window"]))
        checks.append(("live: 普通の起動は印なし (foil)", live.get(104) == []))
        unknown = live_processes("Example Browser", f"  107     1 00:01 {exe}", lambda pid, path: None, lambda path: 7)
        checks.append(("live: 実行中の inode が取れない時は stale と言わない", unknown and unknown[0]["marks"] == []))
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("PASS " if ok else "FAIL ") + name)
    print(f"selftest: {len(checks) - len(failed)}/{len(checks)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
