"""doc の中の generated view (規則の表・checklist・セル定数表) を spec から描く。

doc 側の書き方 (中身は生成物。 手で書き換えると views --check が FAIL)::

    <!-- formcase:view kind=table rules=<form>/<rule>,<form>/<rule> -->
    …(生成)…
    <!-- /formcase:view -->

kind:
  table      規則の表 (項目 / 何を書くか / 様式・セル / 経緯)
  checklist  提出前 checklist (- [ ] 項目: 規則)
  cells      セルの値の表 (form=<id> refs=G10,V10,…)。 fixed の値 + summary (無ければ label)
  status     案件 README の状態表 (その dir の submission.yaml の document / group ごとの state・日付・紙との関係 +
             案件の TODO)。 README に状態を手で書かないための受け皿。 manifest を変える freeze / annotate /
             reopen / new が描き直す。 手で manifest を直したら views --write
経緯の区間 (古い規則の言い回しを残してよい所) の書き方::

    <!-- formcase:history -->
    …
    <!-- /formcase:history -->
"""
from __future__ import annotations

import re
from pathlib import Path

from . import config as CF
from . import rules as R

# marker は「行の中で backtick に挟まれていない」 もの、 かつ code fence の外のものだけを数える
# (= doc が marker の書き方を説明している箇所を marker と誤認しない)。
BEGIN_RE = re.compile(r"(?<!`)<!-- formcase:view (?P<args>[^>]*?) -->(?!`)")
END_RE = re.compile(r"(?<!`)<!-- /formcase:view -->(?!`)")
END = "<!-- /formcase:view -->"
NOTE = "<!-- 生成物 (formcase.py views --write)。 手で直さない — 規則はお手本 spec (reference/*.yaml) を直す -->"
NOTE_STATUS = ("<!-- 生成物 (submission.yaml から。 freeze / annotate / reopen が描き直す)。 手で直さない — "
               "状態は formcase.py freeze / annotate で manifest に書く -->")
HIST_BEGIN_RE = re.compile(r"(?<!`)<!-- formcase:history -->(?!`)")
HIST_END_RE = re.compile(r"(?<!`)<!-- /formcase:history -->(?!`)")


def _fences(text: str):
    out, start, off = [], None, 0
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            if start is None:
                start = off
            else:
                out.append((start, off + len(line)))
                start = None
        off += len(line) + 1
    return out


def _live(matches, fences):
    return [m for m in matches if not any(s <= m.start() < e for s, e in fences)]


def _args(s: str) -> dict:
    out = {}
    for tok in s.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v
    return out


def _esc(s) -> str:
    return " ".join(str(s).split()).replace("|", "\\|")


def _where(r: dict) -> str:
    if r["kind"] == "cell":
        refs = r["refs"]
        shown = ", ".join(refs[:3]) + ("…" if len(refs) > 3 else "")
        return f"`{r['form']}` {shown}"
    if r["kind"] == "nittei":
        return f"`{r['form']}` 日程表"
    return f"`{r['form']}` 横断"


PAPER_MARK = {"same": "= 同じ", "differs": "≠ 違う", "unverified": "? 不明"}


def _status(case_dir) -> str:
    """案件 README の状態表。 値は manifest から (手で書かない)。 詳細 (出力 file・紙との差の説明・note) は status コマンド。"""
    from . import manifest as M

    if case_dir is None or not (Path(case_dir) / M.MANIFEST_NAME).exists():
        raise ValueError("kind=status は submission.yaml のある案件 dir の README にだけ置ける")
    m = M.load(case_dir)
    rows = ["| document | 様式 | group | 状態 | 日付 | 記録と紙 |", "|---|---|---|---|---|---|"]
    for doc_id, doc, gid, g in m.iter_groups():
        cur = g.get("current") or {}
        st = cur.get("state") or ""
        mark = "🧊 " if st in M.FROZEN_STATES else "✏️ "
        rows.append(f"| {_esc(doc_id)} | {_esc(doc.get('form', ''))} | {_esc(gid)} | {mark}{_esc(st)} | "
                    f"{_esc(cur.get('date', ''))} | {PAPER_MARK.get(cur.get('paper'), '')} |")
    todo = m.data.get("todo") or []
    todo = [todo] if isinstance(todo, str) else list(todo)
    rows.append("")
    rows.append(f"出力 file・紙との差・note = `formcase.py status {CF.show_path(case_dir)}`"
                + (" / 案件の TODO = " + " / ".join(f"`{t}`" for t in todo) if todo else ""))
    return "\n".join(rows)


def render(args: dict, all_rules=None, case_dir=None) -> str:
    kind = args.get("kind", "table")
    if kind == "status":
        return _status(case_dir)
    if kind == "cells":
        form = args.get("form")
        refs = [x for x in args.get("refs", "").split(",") if x]
        rows = ["| セル | 欄 | 値 | 規則 |", "|---|---|---|---|"]
        for ref, e in R.cells_of(form, refs):
            val = e.get("value") if e.get("state") == "fixed" else f"({e.get('state')})"
            rows.append(f"| {ref} | {_esc(e.get('label', ''))} | **{_esc(val)}** | "
                        f"{_esc(e.get('summary') or '')} |")
        return "\n".join(rows)
    allr = all_rules if all_rules is not None else R.all_rules()
    ids = [x for x in args.get("rules", "").split(",") if x]
    missing = [i for i in ids if i not in allr]
    if missing:
        raise ValueError(f"規則 id が spec に無い: {missing}")
    if kind == "table":
        rows = ["| 項目 | 何を書くか (規則) | 様式・セル | 経緯 |", "|---|---|---|---|"]
        for i in ids:
            r = allr[i]
            rows.append(f"| {_esc(r.get('label') or i)} | {_esc(r['summary'])} | {_where(r)} | "
                        f"{_esc(r.get('history', ''))} |")
        return "\n".join(rows)
    if kind == "checklist":
        return "\n".join(f"- [ ] {_esc(allr[i].get('label') or i)}: {_esc(allr[i]['summary'])} "
                         f"(`{i}`)" for i in ids)
    raise ValueError(f"未知の kind {kind!r}")


def process(text: str, all_rules=None, case_dir=None):
    """(new_text, n_blocks, problems)。 problems = 描けなかった block の理由。 case_dir = kind=status が読む案件 dir。"""
    out, pos, n, problems = [], 0, 0, []
    fences = _fences(text)
    ends = _live(END_RE.finditer(text), fences)
    for m in _live(BEGIN_RE.finditer(text), fences):
        if m.start() < pos:
            continue
        end = next((e.start() for e in ends if e.start() > m.end()), -1)
        if end < 0:
            problems.append(f"L{text.count(chr(10), 0, m.start()) + 1}: 閉じ ({END}) が無い")
            break
        n += 1
        try:
            body = render(_args(m.group("args")), all_rules, case_dir)
        except (ValueError, KeyError) as e:
            problems.append(f"L{text.count(chr(10), 0, m.start()) + 1}: {e}")
            body = text[m.end():end].strip("\n")
            out.append(text[pos:end])
            pos = end
            continue
        out.append(text[pos:m.end()])
        note = NOTE_STATUS if _args(m.group("args")).get("kind") == "status" else NOTE
        out.append("\n" + note + "\n" + body + "\n")
        pos = end
    out.append(text[pos:])
    return "".join(out), n, problems


def spans(text: str):
    """generated view と history 区間の (start, end) offset。 lint が除外する。"""
    res = []
    fences = _fences(text)
    for b_re, e_re in ((BEGIN_RE, END_RE), (HIST_BEGIN_RE, HIST_END_RE)):
        ends = _live(e_re.finditer(text), fences)
        for m in _live(b_re.finditer(text), fences):
            e = next((x.end() for x in ends if x.start() >= m.end()), None)
            res.append((m.start(), e if e is not None else len(text)))
    return res


def region_problems(text: str) -> list:
    """区間 marker (generated view / history) の対応の崩れ = [(行, 説明)]。 区間は入れ子にできない: spans() は開きから
    次の閉じまでを区間にするので、 区間の中に開きを書くと内側の閉じで外側が閉じ、 その後ろの行が黙って lint の対象に戻り、
    外側の閉じは宙に浮く (実測: 見出しを強調する空の区間を経緯の中に差し込んだ案件 README)。"""
    fences = _fences(text)
    evs = []
    for kind, b_re, e_re in (("view", BEGIN_RE, END_RE), ("history", HIST_BEGIN_RE, HIST_END_RE)):
        evs += [(m.start(), kind, "open") for m in _live(b_re.finditer(text), fences)]
        evs += [(m.start(), kind, "close") for m in _live(e_re.finditer(text), fences)]

    def ln(o):
        return text.count("\n", 0, o) + 1

    out, cur = [], None   # cur = (kind, offset) の開いている区間
    for off, kind, what in sorted(evs):
        if what == "open":
            if cur is None:
                cur = (kind, off)
            else:
                out.append((ln(off), f"{kind} の開きが L{ln(cur[1])} で開いた {cur[0]} 区間の中にある"
                                     f" (区間は入れ子にできない = 内側の閉じで外側が閉じる)"))
        elif cur is None:
            out.append((ln(off), f"{kind} の閉じに対応する開きが無い (入れ子で先に閉じた区間の残りか)"))
        else:
            if cur[0] != kind:
                out.append((ln(off), f"L{ln(cur[1])} で開いた {cur[0]} 区間を {kind} の閉じで閉じている"))
            cur = None
    if cur is not None:
        out.append((ln(cur[1]), f"{cur[0]} の開きに閉じが無い (file の末尾まで区間になる)"))
    return out


def refresh_case(case_dir) -> str | None:
    """manifest を変えた後に案件 README の generated view を描き直す (freeze / annotate / reopen / new が呼ぶ)。
    README が無い・view が無いなら何もしない。 戻り値 = 表示する 1 行 (無ければ None)。"""
    readme = Path(case_dir) / "README.md"
    if not readme.exists():
        return None
    raw = readme.read_bytes()
    if raw.startswith(b"\x00GITCRYPT") or b"formcase:view kind=" not in raw:
        return None
    (_p, st, detail), = check_files([readme], write=True)
    if st == "written":
        return f"✏️  README の状態表を描き直した ({readme})"
    if st == "error":
        return f"🔴 README の view を描けない ({readme}): {detail}"
    return None


def check_files(paths, write=False):
    """[(path, status, detail)]。 status = ok / stale / written / error。"""
    allr = R.all_rules()
    res = []
    for p in paths:
        p = Path(p)
        raw = p.read_bytes()
        if raw.startswith(b"\x00GITCRYPT"):
            res.append((p, "locked", ""))
            continue
        text = raw.decode("utf-8")
        new, n, problems = process(text, allr, p.parent)
        if problems:
            res.append((p, "error", "; ".join(problems)))
            continue
        if new == text:
            res.append((p, "ok", f"{n} view"))
        elif write:
            p.write_text(new, encoding="utf-8")
            res.append((p, "written", f"{n} view"))
        else:
            res.append((p, "stale", f"{n} view のどれかが spec と違う"))
    return res
