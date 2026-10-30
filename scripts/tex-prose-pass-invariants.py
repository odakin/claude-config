#!/usr/bin/env python3
"""英文だけを直した pass の前後で、 LaTeX 原稿の数式・引用 (\\cite)・引用文・参照・label・数値が変わっていないかを数える — 2 つの git revision の多重集合を比べ、 増えた・減ったものを出す (書き換えた文を新旧の対で並べる --pairs つき)。

なぜ (実測): 共著者や AI が入れた英語の直し (言い換え・短文化・ぶつ切りの文のまとめ直し) を検品するとき、
「数値・式・引用は変えていない」 を diff を目で追って確かめると、 hunk の数だけ見落としの機会がある。
多重集合で比べれば 1 回で全体を押さえられ、 目で読むのは機械にできない部分 (限定の係り先・指示語の指す先・主張の強さ)
だけになる (読み方 = conventions/writing-discipline.md#merge-back-checks)。 まとめ直した文は長くなりやすいので、
変わった行に始まる長い文の一覧も同じ command で出す (数え方 = tex-sentence-lengths.py)。

使い方 (git repo の中で):
    python3 tex-prose-pass-invariants.py --base <rev> [--head <rev>] paper.tex [more.tex ...]
        [--display-macro NAME ...] [--quote-macro NAME ...] [--over 40] [--pairs] [--json]
    python3 tex-prose-pass-invariants.py --base <rev> --head-file <写しの path> paper.tex [--over 40]
    python3 tex-prose-pass-invariants.py --selftest

  - `--head` を省くと作業 tree の file と比べる。 file の path は今の dir から。
  - `--head-file PATH` = head を revision でも作業 tree でもなく別の file から読む (repo の外の写しで直し、 原稿に書き込む前に
    確かめるとき = 著者が editor で原稿を開いている間など)。 比べる file は 1 つ。 `--over` の変わった行は 2 つの本文の差から出す。
  - 比べるもの (`%` のコメント行と行末コメントを除いた全文):
      inline math (`$...$` と `\\(...\\)`) / display (math 環境・`\\[...\\]`・`$$...$$`・`--display-macro` の `\\NAME{...}`) /
      `\\cite` 類のキー / `\\ref` 類 (ref・eqref・cref・Cref・autoref・labelcref・pageref・nameref・vref) のキー / `\\label` のキー /
      散文の数値 (上のどれにも入らない所の数字)。 数式は空白を詰めて比べる (改行の位置だけの違いは差にしない)。
      引用文 = `\\begin{document}` 以降の ``…'' と、 `--quote-macro NAME` の `\\NAME{…}` の中身 (空白を詰めた字句)。
      引用を ``…'' から `\\enquote{…}` や斜体の macro に包み直しただけなら同じ引用として数える (前置きの macro 定義の
      ``…'' は数えない)。 原文から引いた引用の字句が変わっていないかを、 1 字単位で確かめる (実測: 読みやすさの書き直しで
      引用を斜体の macro に包み直した版で、 字句が 1 字も変わっていないことをこの比べ方で示した)。
  - 位置は比べない (引用が同じ文に付いたままかは目で見る)。 題名・要旨のような固定した文は `grep -c` で別に確かめる。
  - `--over N` = head で変わった行 (`git diff -U0`) に始まる文のうち N 語を超えるもの。 文の途中の行だけが変わった文は出ない (概数)。
  - `--pairs` = base の文のうち head にそのままは無いものを、 head にしか無い文のうち一番近いものと並べる (似ている度合い
    0〜1 つき、 引用符と空白の違いは無視)。 書き換え・分割・移動した文を新旧で読み合わせ、 主張が落ちていないかを 1 文ずつ
    確かめるための一覧 (相手が見つからない・似ていない文は削除の候補)。 文の切り方 = tex-sentence-lengths.py (数式は MATH)。
    数値・式の変更は上の多重集合が受け持つ。 exit の値には効かない。
exit: 0 = 全項目が同じ / 1 = どこかが違う (差を出す) / 2 = 入力の誤り (revision・file が無い)。
"""
from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

MATH_ENVS = r"equation|align|alignat|gather|multline|eqnarray|flalign|displaymath|math"
CITE = re.compile(r"\\[cC]ite[a-zA-Z]*\*?\s*(?:\[[^\]]*\]\s*){0,2}\{([^}]*)\}")
REF = re.compile(r"\\(?:ref|eqref|cref|Cref|crefrange|Crefrange|autoref|labelcref|pageref|nameref|vref)\*?\s*\{([^}]*)\}")
LABEL = re.compile(r"\\label\s*(?:\[[^\]]*\])?\{([^}]*)\}")
NUMBER = re.compile(r"(?<![A-Za-z\\])\d+(?:\.\d+)?")
QUOTE = re.compile(r"``(.*?)''", re.S)
CATEGORIES = ("inline math", "display", "cite keys", "ref keys", "labels", "numbers", "quotes")


def body(text: str) -> str:
    lines = [l for l in text.split("\n") if not l.lstrip().startswith("%")]
    return "\n".join(re.sub(r"(?<!\\)%.*", "", l) for l in lines)


def _norm(s: str) -> str:
    """数式の空白は意味を持たないので詰める。 英字どうしの間 (`\\alpha b`) だけは 1 つ残す。"""
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"(?<=[^A-Za-z]) | (?=[^A-Za-z])", "", s)


def _cut(t: str, pattern: str, bag: list[str], flags: int = 0) -> str:
    def repl(m: re.Match) -> str:
        bag.append(_norm(m.group(0)))
        return " "
    return re.sub(pattern, repl, t, flags=flags)


def _cut_macro(t: str, name: str, bag: list[str]) -> str:
    key, out, i = "\\" + name + "{", [], 0
    while (j := t.find(key, i)) >= 0:
        out.append(t[i:j])
        k, depth = j + len(key), 1
        while k < len(t) and depth:
            depth += {"{": 1, "}": -1}.get(t[k], 0)
            k += 1
        bag.append(_norm(t[j:k]))
        out.append(" ")
        i = k
    out.append(t[i:])
    return "".join(out)


def _macro_args(t: str, name: str) -> list[str]:
    """`\\NAME{...}` の中身の list (括弧の釣り合いを数える。 `\\{`・`\\}`・`\\\\` は 2 字で 1 つとして飛ばす)。"""
    key, out, i = "\\" + name + "{", [], 0
    while (j := t.find(key, i)) >= 0:
        k, depth = j + len(key), 1
        while k < len(t) and depth:
            if t[k] == "\\":
                k += 2
                continue
            depth += {"{": 1, "}": -1}.get(t[k], 0)
            k += 1
        out.append(t[j + len(key):k - 1])
        i = k
    return out


def quotations(text: str, quote_macros: list[str]) -> list[str]:
    """引用文の list = 本文 (`\\begin{document}` 以降) の ``…'' と `\\NAME{…}` (NAME = quote_macros) の中身、 空白を詰めた字句。"""
    t = body(text)
    if "\\begin{document}" in t:
        t = t.split("\\begin{document}", 1)[1]
    found = [q for name in quote_macros for q in _macro_args(t, name)]
    found += [m.group(1) for m in QUOTE.finditer(t)]
    return [re.sub(r"\s+", " ", q).strip() for q in found]


def extract(text: str, macros: list[str], quote_macros: list[str] | tuple = ()) -> dict[str, Counter]:
    quotes = Counter(quotations(text, list(quote_macros)))
    t = body(text).replace("\\$", "\x01")
    keys = lambda rx, s: [k.strip() for m in rx.finditer(s) for k in m.group(1).split(",") if k.strip()]
    cites, refs, labels = keys(CITE, t), keys(REF, t), keys(LABEL, t)  # 数式の中の label・参照も数える
    disp: list[str] = []
    t = _cut(t, rf"\\begin\{{({MATH_ENVS})\*?\}}.*?\\end\{{\1\*?\}}", disp, re.S)
    t = _cut(t, r"\\\[.*?\\\]", disp, re.S)
    t = _cut(t, r"\$\$.*?\$\$", disp, re.S)
    for name in macros:
        t = _cut_macro(t, name, disp)
    inline: list[str] = []
    t = _cut(t, r"\\\(.*?\\\)", inline, re.S)
    t = _cut(t, r"\$[^$]+\$", inline)
    rest = LABEL.sub(" ", REF.sub(" ", CITE.sub(" ", t)))  # 散文の数値 = 数式とキーの外
    return {"inline math": Counter(inline), "display": Counter(disp), "cite keys": Counter(cites),
            "ref keys": Counter(refs), "labels": Counter(labels), "numbers": Counter(NUMBER.findall(rest)),
            "quotes": quotes}


def compare(a: dict[str, Counter], b: dict[str, Counter]) -> dict:
    out = {}
    for c in CATEGORIES:
        removed, added = a[c] - b[c], b[c] - a[c]
        out[c] = {"base": sum(a[c].values()), "head": sum(b[c].values()),
                  "removed": dict(removed), "added": dict(added)}
    return out


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def changed_lines(base: str, head: str | None, path: str) -> set[int]:
    diff = git("diff", "-U0", base, *([head] if head else []), "--", path)
    lines: set[int] = set()
    for m in re.finditer(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", diff, re.M):
        start, n = int(m.group(1)), int(m.group(2) or 1)
        lines.update(range(start, start + n))
    return lines


def changed_lines_text(old: str, new: str) -> set[int]:
    """old → new で書き換えた・足した new の行番号 (1 始まり)。 `--head-file` の `--over` 用 (git diff を使わない)。"""
    lines: set[int] = set()
    sm = difflib.SequenceMatcher(None, old.split("\n"), new.split("\n"), autojunk=False)
    for tag, _i1, _i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "insert"):
            lines.update(range(j1 + 1, j2 + 1))
    return lines


def _sentences(text: str, macros: list[str]) -> list[tuple[int, int, str]]:
    """(語数, 行番号, 整えた文) = tex-sentence-lengths.py の切り方。"""
    spec = importlib.util.spec_from_file_location("tsl", Path(__file__).with_name("tex-sentence-lengths.py"))
    tsl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tsl)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.tex"
        p.write_text(text, encoding="utf-8")
        return tsl.sentences(p, macros)


def long_changed(text: str, lines: set[int], macros: list[str], over: int) -> list[dict]:
    sents = _sentences(text, macros)
    return [{"words": w, "line": n, "text": c} for w, n, c in sorted(sents, reverse=True) if w > over and n in lines]


def _plain(s: str) -> str:
    """文の比べ方: 引用符と空白の違いを消す (引用を macro に包み直しただけの文を同じ文と見る)。"""
    s = re.sub(r"\s+", " ", re.sub(r"``|''|[\"“”]", "", s))
    return re.sub(r" (?=[,.;:!?)])", "", s).strip()  # macro を外した跡の「 ,」


def sentence_pairs(old: str, new: str, macros: list[str]) -> list[dict]:
    """old の文のうち new にそのままは無いもの (old の順) と、 new にしか無い文のうち一番近いもの。"""
    so, sn = _sentences(old, macros), _sentences(new, macros)
    old_set, new_set = {_plain(c) for _, _, c in so}, {_plain(c) for _, _, c in sn}
    only_new = [(n, c) for _, n, c in sn if _plain(c) not in old_set]
    ratio = lambda a, b: difflib.SequenceMatcher(None, _plain(a), _plain(b), autojunk=False).ratio()
    out = []
    for _, n, c in so:
        if _plain(c) in new_set:
            continue
        best = max(only_new, key=lambda x: ratio(c, x[1]), default=None)
        out.append({"old_line": n, "old": c, "new_line": best[0] if best else None,
                    "new": best[1] if best else "", "ratio": round(ratio(c, best[1]), 2) if best else 0.0})
    return out


def selftest() -> int:
    base = ("\\begin{document}\n% a comment with $x$ and 3 numbers 4 5\n"
            "We use $a+b$ and \\cite{k1,k2} with 0.5 here, see \\cref{e1}. Price 3\\$ only.\n"
            "\\begin{equation} x = 1 \\label{e1} \\end{equation}\n"
            "The macro \\al{ y = 2 } stays. It has 12 items.\n\\end{document}\n")
    rewrapped = base.replace("We use $a+b$ and", "We use $a +\n b$ and")
    edited = base.replace("0.5", "0.6").replace("\\cite{k1,k2}", "\\cite{k2}")
    ok = True
    same = compare(extract(base, ["al"]), extract(rewrapped, ["al"]))
    if any(v["removed"] or v["added"] for v in same.values()):
        print(f"FAIL rewrap is not a change: {same}"); ok = False
    diff = compare(extract(base, ["al"]), extract(edited, ["al"]))
    if diff["numbers"]["removed"] != {"0.5": 1} or diff["numbers"]["added"] != {"0.6": 1}:
        print(f"FAIL number change: {diff['numbers']}"); ok = False
    if diff["cite keys"]["removed"] != {"k1": 1} or diff["cite keys"]["added"]:
        print(f"FAIL cite change: {diff['cite keys']}"); ok = False
    e = extract(base, ["al"])
    want = {"inline math": 1, "display": 2, "cite keys": 2, "ref keys": 1, "labels": 1, "numbers": 3, "quotes": 0}
    got = {c: sum(e[c].values()) for c in CATEGORIES}
    if got != want:  # コメント行の数字は数えない、 数式の中の数字は数値に入れない (label・参照は数える)、 \$ は数式にしない
        print(f"FAIL counts {got} (want {want})"); ok = False
    if sorted(e["numbers"]) != ["0.5", "12", "3"]:
        print(f"FAIL prose numbers {sorted(e['numbers'])}"); ok = False
    cl = changed_lines_text("a\nb\nc\n", "a\nB\nc\nd\n")
    if cl != {2, 4}:  # --head-file の --over = 書き換えた行と足した行 (new の行番号)
        print(f"FAIL changed_lines_text {cl}"); ok = False
    pre = "\\newcommand{\\qt}[1]{``\\textit{#1}''}\n\\begin{document}\n"
    q_old = pre + "He wrote ``a  b {c}'' and ``d''.\n\\end{document}\n"
    q_new = pre + "He wrote \\qt{a b {c}} and \\qt{d}.\n\\end{document}\n"
    qs = compare(extract(q_old, [], ["qt"]), extract(q_new, [], ["qt"]))["quotes"]
    if qs["removed"] or qs["added"] or qs["base"] != 2:  # 包み直しは差にしない、 前置きの定義は数えない
        print(f"FAIL rewrapped quotations {qs}"); ok = False
    qc = compare(extract(q_old, [], ["qt"]), extract(q_new.replace("{d}", "{e}"), [], ["qt"]))["quotes"]
    if qc["removed"] != {"d": 1} or qc["added"] != {"e": 1}:
        print(f"FAIL changed quotation {qc}"); ok = False
    doc = "\\begin{document}\nThe first sentence stays exactly as it is. The second sentence says %s here.\n\\end{document}\n"
    pairs = sentence_pairs(doc % "one thing", doc % "another thing", [])
    if len(pairs) != 1 or "one thing" not in pairs[0]["old"] or "another thing" not in pairs[0]["new"]:
        print(f"FAIL sentence_pairs {pairs}"); ok = False
    if sentence_pairs(doc % "``one'' thing", doc % "one thing", []):  # 引用符だけの違いは対にしない
        print("FAIL sentence_pairs counts quote marks as a change"); ok = False
    if sentence_pairs(doc % "``one'', thing", doc % "\\qt{one}, thing", []):  # macro に包み直しただけの文も
        print("FAIL sentence_pairs counts a rewrapped quotation as a change"); ok = False
    print("selftest:", "OK" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--base")
    ap.add_argument("--head")
    ap.add_argument("--head-file", type=Path, metavar="PATH")
    ap.add_argument("--display-macro", action="append", default=[], metavar="NAME")
    ap.add_argument("--quote-macro", action="append", default=[], metavar="NAME")
    ap.add_argument("--over", type=int)
    ap.add_argument("--pairs", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.base or not a.files:
        ap.error("--base <rev> と file を 1 つ以上")
    if a.head_file and (a.head or len(a.files) != 1):
        ap.error("--head-file は file 1 つと、 --head なしで")
    results, differ = [], False
    for f in a.files:
        try:
            old = git("show", f"{a.base}:./{f}")
            if a.head_file:
                new = a.head_file.read_text(encoding="utf-8")
            else:
                new = git("show", f"{a.head}:./{f}") if a.head else Path(f).read_text(encoding="utf-8")
        except (subprocess.CalledProcessError, OSError) as exc:
            print(f"{f}: 読めない ({a.base} / {a.head_file or a.head or '作業 tree'}): {getattr(exc, 'stderr', exc)}",
                  file=sys.stderr)
            return 2
        cmp_ = compare(extract(old, a.display_macro, a.quote_macro), extract(new, a.display_macro, a.quote_macro))
        differ |= any(v["removed"] or v["added"] for v in cmp_.values())
        r = {"file": f, "base": a.base, "head": str(a.head_file) if a.head_file else (a.head or "working tree"),
             "categories": cmp_}
        if a.over is not None:
            lines = changed_lines_text(old, new) if a.head_file else changed_lines(a.base, a.head, f)
            r["long_changed"] = long_changed(new, lines, a.display_macro, a.over)
        if a.pairs:
            r["pairs"] = sentence_pairs(old, new, a.display_macro)
        results.append(r)
    if a.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
        return 1 if differ else 0
    for r in results:
        print(f"== {r['file']} ({r['base']} → {r['head']})")
        for c, v in r["categories"].items():
            mark = "same" if not (v["removed"] or v["added"]) else f"removed={v['removed']} added={v['added']}"
            print(f"  {c:12s} {v['base']:5d} → {v['head']:5d}  {mark}")
        if "long_changed" in r:
            print(f"  変わった行に始まる {a.over} 語超の文: {len(r['long_changed'])}")
            for it in r["long_changed"]:
                print(f"    {it['words']:3d} 語  l.{it['line']}: {it['text'][:90]}…")
        if "pairs" in r:
            print(f"  旧版の文のうち新版にそのままは無いもの: {len(r['pairs'])} (新版にしか無い文のうち一番近いものと並べる)")
            for p in r["pairs"]:
                print(f"    [旧 l.{p['old_line']}] {p['old']}")
                print(f"    [新 l.{p['new_line']} 似 {p['ratio']}] {p['new']}")
    return 1 if differ else 0


if __name__ == "__main__":
    sys.exit(main())
