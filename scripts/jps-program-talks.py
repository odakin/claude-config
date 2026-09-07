#!/usr/bin/env python3
"""jps-program-talks.py — 日本物理学会 (JPS) 年次大会 / 春季大会の Web program を機械で読む。

用途: 講演番号 → 開始時刻の確定 (conventions/jps-talk-submission.md#program-slot-lookup)、 日程表から
特定日・午前/午後の全 session を一覧、 全領域の題目を keyword で横断検索 (聴講計画 / 自分の関心に
近い講演の発掘 = #program-triage-by-interest-profile)。 2026 秋 (2026au) で確立、 URL 構造が同じ大会なら
`--meeting` を変えるだけ。

subcommand (すべて `--meeting 2026au` 等を取る、 default = env JPS_MEETING or 2026au):
  sessions --day 15 [--slot a|p]          日程表 (timetable.html) から当日の session 一覧 (会場 / 時刻 / 領域 / 名前 / program file)
  talks <anchor> [<anchor>...]            session の講演 list + **計算した開始時刻** (例 j16pE532、 j15aG721)
  grep <regex> [--files programsr,programu] 全 (or 指定) 領域 file の題目を横断検索、 hit を session/時刻付きで
  slot <講演番号>                          講演番号 (16pE532-11) → 日時・会場・題目 (= talks の 1 行版)
  --cache-dir DIR                          取得 HTML の置き場 (default: ~/.cache/jps-program/<meeting>/、 再取得は --refresh)

機構 fact (2026-09-07 実測):
  - base = https://onsite.gakkai-web.net/jps/jps_search/<meeting>/program/date/
    timetable.html = 会場 × (日 × 午前/午後) の table。 cell 内の <a href="program<領域>.html#j<日><a|p><会場>"> が
    session anchor、 `<sup>＊</sup>` 付きは招待・企画講演を含む。 program file 名 = 領域 code (sr=素粒子論, u=宇宙線・宇宙物理,
    sj=素粒子実験, jk=実験核物理, rk=理論核物理, kb=計算物理, si=ビーム物理, 01-13=領域 N, _s=シンポジウム一覧、
    ps*=ポスター)。 合同 session は複数 file に同じ anchor で載る (= 重複を id で潰す)。
  - session block = `<a name="jNN[ap]ROOM" id="...">` から次の `class="roundframe mtspace"` まで。 講演 = `<li>`、
    休憩 = `<div class="roundframe spaces">休憩 （hh:mm〜hh:mm)</div>`、 小見出し = `<h3 class="skew-line">`。
    各 `<li>` は 「（シンポジウム講演）題目　（NN分）<br><small>所属</small><br><small>著者 (○ = 登壇者)</small>」。
  - **開始時刻は program に無い** → session 開始時刻から `（NN分）` を積算し休憩で jump する (= 本 script の計算)。
    講演番号の末尾 -N = N 番目の `<li>` (取消講演も `<li>` として残り「取消」 と書かれるので番号はずれない)。
  - 題目内の LaTeX は `!LaTeX$...$` で埋め込まれる (= そのまま表示)。
  - 概要集 (abstract) 本文は WEB 版 (index.html、 参加者 ID/PW で login) にしか無い = 本 script は題目までで、
    login は agent が代行しない (ID/PW は「参加票及び講演概要集」 mail に載るが使わない)。
  - WebFetch の要約は講演を 1 件落として番号をずらしたことがある (2026 実測) → 必ず生 HTML を数える (= 本 script)。

⚠️ 出力は公開情報 (program) のみ。 自分の聴講計画・calendar id 等は private 層 (conferences/events.yaml 等) に書く。
"""
import argparse
import html
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

AREA = {"sr": "素粒子論", "u": "宇宙線・宇宙物理", "sj": "素粒子実験", "jk": "実験核物理", "rk": "理論核物理",
        "kb": "計算物理", "si": "ビーム物理", "_s": "シンポジウム一覧"}


def base(meeting):
    return f"https://onsite.gakkai-web.net/jps/jps_search/{meeting}/program/date/"


def fetch(meeting, name, cache_dir, refresh=False):
    d = Path(cache_dir) / meeting
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    if p.exists() and not refresh and p.stat().st_size > 1000:
        return p.read_text(encoding="utf-8", errors="replace")
    req = urllib.request.Request(base(meeting) + name, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        t = r.read().decode("utf-8", "replace")
    p.write_text(t, encoding="utf-8")
    return t


def _text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def sessions(meeting, day, slot, cache, refresh):
    t = fetch(meeting, "timetable.html", cache, refresh)
    out = []
    for tr in re.findall(r"<tr>(.*?)</tr>", t, re.S):
        room = re.search(r'table-headsection"><div>([^<]+)</div>', tr)
        if not room:
            continue
        for td in re.findall(r"<td>(.*?)</td>", tr, re.S):
            m = re.search(r'#j(%02d|%d)([ap])' % (day, day), td)
            if not m or (slot and m.group(2) != slot):
                continue
            time = re.search(r"(\d+:\d+〜\d+:\d+)", td)
            areas = re.findall(r'href="(program[^"]+)\.html#(j\d+[ap][A-Z]+\d+)"[^>]*>([^<]+)</a>', td)
            name = _text(td.split("<br />")[-1])
            star = "＊" if "<sup>＊</sup>" in td else " "
            out.append((room.group(1), time.group(1) if time else "", star, "/".join(a[2] for a in areas),
                        name, areas[0][0] if areas else "", areas[0][1] if areas else ""))
    return out


def session_block(t, anchor):
    i = t.find('id="%s"' % anchor)
    if i < 0:
        return None
    e = t.find('class="roundframe mtspace"', i + 10)
    return t[i:e if e > 0 else len(t)]


def talks(block):
    """yield (n, start, minutes, title, affiliations, authors, subheading) with computed start times."""
    head = _text(block[:900])
    hm = re.search(r"(\d+日 \S+会場\s+\S+\s+(\d+:\d+)〜(\d+:\d+))", head)
    cur = datetime.strptime(hm.group(2), "%H:%M") if hm else None
    n = 0
    sub = ""
    for li, br, sh in re.findall(r"<li>(.*?)</li>|<div class=\"roundframe spaces\">(.*?)</div>|<h3 class=\"skew-line\">(.*?)</h3>", block, re.S):
        if sh:
            sub = _text(sh)
            continue
        if br:
            mm = re.search(r"〜(\d+:\d+)", html.unescape(br))
            if mm:
                cur = datetime.strptime(mm.group(1), "%H:%M")
            continue
        n += 1
        txt = _text(li)
        mins = re.search(r"（(\d+)分）", txt)
        mins = int(mins.group(1)) if mins else 15
        title = re.sub(r"^（[^）]*講演）\s*", "", txt).split("（")[0].strip()
        smalls = [_text(x) for x in re.findall(r"<small>(.*?)</small>", li, re.S)]
        aff, au = (smalls + ["", ""])[:2]
        yield n, cur, mins, title, aff, au, sub, hm.group(1) if hm else ""
        if cur:
            cur += timedelta(minutes=mins)


def cmd_talks(meeting, anchors, cache, refresh, files=None):
    files = files or program_files(meeting, cache, refresh)
    for a in anchors:
        found = False
        for f in files:
            b = session_block(fetch(meeting, f, cache, refresh), a)
            if not b:
                continue
            found = True
            rows = list(talks(b))
            print(f"===== {rows[0][7] if rows else a} [{f}]")
            for n, cur, mins, title, aff, au, sub, _ in rows:
                st = cur.strftime("%H:%M") if cur else "--:--"
                print(f"  -{n:2d} {st} {mins:3d}分 {title} | {aff} | {au}" + (f"  [{sub}]" if sub else ""))
            break
        if not found:
            print(f"===== {a}: not found in {len(files)} files", file=sys.stderr)


def program_files(meeting, cache, refresh):
    t = fetch(meeting, "timetable.html", cache, refresh)
    return sorted(set(re.findall(r'href="(program[a-z0-9_]*\.html)', t)))


def cmd_grep(meeting, pattern, files, cache, refresh):
    pat = re.compile(pattern, re.I)
    seen = set()
    for f in files:
        t = fetch(meeting, f, cache, refresh)
        for b in re.split(r'(?=<a name="j\d+[ap][A-Z]+\d+")', t):
            m = re.search(r'id="(j\d+[ap][A-Z]+\d+)"', b)
            if not m:
                continue
            for n, cur, mins, title, aff, au, sub, head in talks(b):
                if pat.search(title) and (head, n) not in seen:
                    seen.add((head, n))
                    st = cur.strftime("%H:%M") if cur else "--:--"
                    print(f"{head} -{n} {st} {title} | {au or aff}" + (f"  [{sub}]" if sub else ""))


def cmd_slot(meeting, number, cache, refresh):
    m = re.match(r"(\d+)([ap])([A-Z]+\d+)-(\d+)", number)
    if not m:
        raise SystemExit("講演番号の形式: 16pE532-11")
    anchor = f"j{m.group(1)}{m.group(2)}{m.group(3)}"
    want = int(m.group(4))
    for f in program_files(meeting, cache, refresh):
        b = session_block(fetch(meeting, f, cache, refresh), anchor)
        if not b:
            continue
        for n, cur, mins, title, aff, au, sub, head in talks(b):
            if n == want:
                st = cur.strftime("%H:%M") if cur else "--:--"
                en = (cur + timedelta(minutes=mins)).strftime("%H:%M") if cur else "--:--"
                print(f"{number}: {head.split()[0]} {st}-{en} {head.split()[1]} | {title} | {aff} | {au}")
                return
    raise SystemExit(f"{number}: not found")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--meeting", default=os.environ.get("JPS_MEETING", "2026au"))
    ap.add_argument("--cache-dir", default=str(Path.home() / ".cache/jps-program"))
    ap.add_argument("--refresh", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sessions"); p.add_argument("--day", type=int, required=True); p.add_argument("--slot", choices=["a", "p"])
    p = sub.add_parser("talks"); p.add_argument("anchors", nargs="+"); p.add_argument("--files")
    p = sub.add_parser("grep"); p.add_argument("pattern"); p.add_argument("--files")
    p = sub.add_parser("slot"); p.add_argument("number")
    a = ap.parse_args()
    if a.cmd == "sessions":
        for room, time, star, areas, name, f, anc in sessions(a.meeting, a.day, a.slot, a.cache_dir, a.refresh):
            print(f"{room:6} {time:12} {star}{areas[:30]:30} {name[:40]:40} [{f} #{anc}]")
    elif a.cmd == "talks":
        files = a.files.split(",") if a.files else None
        cmd_talks(a.meeting, a.anchors, a.cache_dir, a.refresh, [x if x.endswith(".html") else x + ".html" for x in files] if files else None)
    elif a.cmd == "grep":
        files = [x if x.endswith(".html") else x + ".html" for x in a.files.split(",")] if a.files else program_files(a.meeting, a.cache_dir, a.refresh)
        cmd_grep(a.meeting, a.pattern, files, a.cache_dir, a.refresh)
    elif a.cmd == "slot":
        cmd_slot(a.meeting, a.number, a.cache_dir, a.refresh)


if __name__ == "__main__":
    main()
