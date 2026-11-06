#!/usr/bin/env python3
"""採点の記録 (YAML / JSON の list) から、 全体に知らせる統計 (人数・平均・中央値・標準偏差・最小最大・問ごとの平均・分布) を出す。

    python3 score-stats.py <grades.yaml|json> --total scores.total \
        [--part 問1=scores.q1 --part 問2=scores.q2 ...] [--items <top-level の key>] [--bin 5] [--json]
    python3 score-stats.py --selftest

- 入力 = 1 人 1 entry の list (top-level が dict なら --items でその key の list)。 値の場所は dotted path (`scores.total`)。
- 値が null・無い entry (受けていない人) は数えない = 人数と一緒に除いた件数を出す。
- 標準偏差は 2 つ出す: n で割る (受けた全員 = その集団そのものを記述する。 クラスに知らせるのはこちら) と、
  n−1 で割る (受けた人を、 より大きな集団からの標本と見て推定するとき)。 どちらを知らせたかを記録に書く。
- 知らせる数値はこの出力から写す (手で計算し直さない)。 規則 = conventions/exam-grading-return.md#class-summary。
"""
import argparse
import json
import math
import statistics as st
import sys


def dig(entry, path):
    cur = entry
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def load(path, items=None):
    text = open(path, encoding="utf-8").read()
    if path.endswith(".json"):
        data = json.loads(text)
    else:
        try:
            import yaml
        except ImportError:
            sys.exit("score-stats: YAML には PyYAML が要る = pip install pyyaml (JSON なら要らない)")
        data = yaml.safe_load(text)
    if isinstance(data, dict):
        if not items:
            sys.exit("score-stats: top-level が dict = --items <list の key> を渡す")
        data = data[items]
    if not isinstance(data, list):
        sys.exit("score-stats: 1 人 1 entry の list が要る")
    return data


def describe(vals):
    n = len(vals)
    out = {"n": n}
    if not n:
        return out
    out.update(mean=st.mean(vals), median=st.median(vals), min=min(vals), max=max(vals),
               sd_n=st.pstdev(vals), sd_n1=st.stdev(vals) if n > 1 else None)
    return out


def histogram(vals, width, top=None):
    if not vals:
        return []
    hi = top if top is not None else max(vals)
    edges = list(range(0, int(math.floor(hi / width)) * width + width, width))
    rows = []
    for lo in edges:
        last = lo == edges[-1]
        c = sum(1 for v in vals if lo <= v < lo + width or (last and v >= lo))
        rows.append((lo, lo + width, c))
    return rows


def stats(entries, total, parts=(), bin_width=5):
    tv = [float(dig(e, total)) for e in entries if dig(e, total) is not None]
    res = {"total": describe(tv), "missing": len(entries) - len(tv), "parts": {}, "histogram": histogram(tv, bin_width)}
    for label, path in parts:
        pv = [float(dig(e, path)) for e in entries if dig(e, total) is not None and dig(e, path) is not None]
        res["parts"][label] = describe(pv)
    return res


def fmt(x, d=2):
    return "-" if x is None else (str(int(x)) if float(x).is_integer() else f"{x:.{d}f}")


def report(res):
    t = res["total"]
    lines = [f"人数 n = {t['n']} (値の無い {res['missing']} 件を除いた)"]
    if t["n"]:
        lines.append(f"平均 {fmt(t['mean'])} / 中央値 {fmt(t['median'])} / 標準偏差 (n で割る) {fmt(t['sd_n'])}"
                     f" / (n−1 で割る) {fmt(t['sd_n1'])} / 最小 {fmt(t['min'])} / 最大 {fmt(t['max'])}")
    for label, p in res["parts"].items():
        if p["n"]:
            lines.append(f"{label}: 平均 {fmt(p['mean'])} / 中央値 {fmt(p['median'])} (n = {p['n']})")
    if res["histogram"]:
        lines.append("分布: " + " / ".join(f"{lo}〜{hi}: {c}" for lo, hi, c in res["histogram"]))
    return "\n".join(lines)


def selftest():
    fails = []

    def check(cond, name, detail=""):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)
            if detail:
                print("     " + str(detail))

    ents = [{"s": {"t": v, "a": a}} for v, a in ((2, 1), (4, 2), (4, 1), (4, 0), (5, 3), (5, 2), (7, 4), (9, 5))]
    ents += [{"s": {"t": None, "a": None}}, {"x": 1}]
    r = stats(ents, "s.t", [("A", "s.a")], bin_width=5)
    t = r["total"]
    check(t["n"] == 8 and r["missing"] == 2, "null と値の無い entry を除いて数える", (t["n"], r["missing"]))
    check(abs(t["mean"] - 5.0) < 1e-12 and t["median"] == 4.5, "平均と中央値 (偶数個は真ん中 2 つの平均)", t)
    check(abs(t["sd_n"] - 2.0) < 1e-12, "n で割る標準偏差 = 2 (教科書の例)", t["sd_n"])
    check(abs(t["sd_n1"] - math.sqrt(32 / 7)) < 1e-12, "n−1 で割る標準偏差 = √(32/7)", t["sd_n1"])
    check(abs(r["parts"]["A"]["mean"] - 2.25) < 1e-12, "問ごとの平均は合計のある人だけで", r["parts"]["A"])
    check(r["histogram"] == [(0, 5, 4), (5, 10, 4)], "分布は幅ごと、 最後の区間は上端を含む", r["histogram"])
    check(stats([{"s": {"t": 3}}], "s.t")["total"]["sd_n1"] is None, "1 人なら n−1 の標準偏差は出さない")
    txt = report(r)
    check("中央値 4.5" in txt and "(n で割る) 2" in txt, "報告の文に中央値と n で割る標準偏差が出る", txt)
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "g.json")
        json.dump({"entries": ents}, open(p, "w"))
        check(len(load(p, "entries")) == 10, "top-level が dict なら --items の list を読む")
    print(f"\n{'FAIL' if fails else 'OK'}: {len(fails)} failure(s)")
    return 1 if fails else 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--selftest"]:
        return selftest()
    ap = argparse.ArgumentParser(description="採点の記録から全体に知らせる統計を出す")
    ap.add_argument("file")
    ap.add_argument("--total", required=True, help="合計の dotted path (例 scores.total)")
    ap.add_argument("--part", action="append", default=[], help="<表示名>=<dotted path> (問ごと、 複数可)")
    ap.add_argument("--items", default=None)
    ap.add_argument("--bin", type=int, default=5, help="分布の幅 (点)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    parts = []
    for p in a.part:
        if "=" not in p:
            ap.error(f"--part は <表示名>=<path>: {p}")
        parts.append(tuple(p.split("=", 1)))
    res = stats(load(a.file, a.items), a.total, parts, a.bin)
    print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else report(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
