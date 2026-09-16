#!/usr/bin/env python3
"""published_metadata.py — 公刊済みの著作の書誌 (題名・著者・要旨) の行を、 leak 検出器の対象から外す。

正本: claude-config/scripts/lib/published_metadata.py
規律: conventions/confidential-repo-boundary.md#published-metadata-is-public

Why: 公開 repo の gate は「実名 (Tier B)」 と「未公開原稿の逐語 (Tier D)」 を探す。 ところが arXiv / DOI で
既に公開された著作の書誌は **定義上もう公開されている**。 共同研究者の論文を記録する bot (arXiv digest の
archive) は著者名と要旨をそのまま持ち、 自分の論文が載った日には要旨が手元の原稿 (.tex) と逐語で一致する。
実測: その archive を stage すると、 著者名で Tier B、 要旨で Tier D が必ず落ち、 **無人の自動 commit が
毎回止まる** (= 止めるべき物は何も無いのに、 transport が黙って壊れる)。 README の参考文献 link も、
改稿中の原稿と同じ題名なので Tier D に当たっていた。
許可 list で逃がすと論文が増えるたびに古くなる。 書誌は **行の構造** (公開先の識別子・URL を伴う) で
見分けられるので、 構造で外す (= 設定を持たない。 一般則 = docs/convention-design-principles.md#detector-config-must-be-derived)。

外すもの (行単位。 行全体が書誌のときだけ):
  1. JSON: arXiv id、 または arXiv / DOI / INSPIRE の URL を持つ object の、 title / abstract / authors / author の
     値の行。 pretty-print (= 1 値 1 行) のときだけ効く。 1 行に詰めた JSON は外さない (= 鳴る側に倒れる)。
  2. Markdown: 公開先 URL への link だけで出来ている行 (list marker と区切り記号を除くと link 以外に語が無い)。
外さないもの: 同じ object の reason / summary / note 等 (= 書き手が書いた文。 ここに実名を書けば今までどおり止まる)。
  link の外に語がある行 (「共同研究者の X さんの [題名](url)」 は止まる)。

使い方:
  python3 published_metadata.py --filter-added BUF    # runner 用: "<path>\\t<text>" の行から書誌の行を除いて stdout へ
                                                      #   path の中身は index (`git show :path`) から読む
  python3 published_metadata.py --selftest

  from published_metadata import metadata_line_numbers   # engine 用: {1-based 行番号}
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Iterable

PUBLISHED_URL_RE = re.compile(
    r"https?://(?:www\.|export\.)?(?:arxiv\.org/(?:abs|pdf)/|(?:dx\.)?doi\.org/10\.|inspirehep\.net/literature/)",
    re.I)
ARXIV_ID_RE = re.compile(r"^(?:arXiv:)?(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?$", re.I)
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
ID_KEYS = ("arxiv_id", "arxiv", "eprint", "arXiv")
URL_KEYS = ("url", "link", "abs_url", "pdf_url", "doi", "doi_url", "id")
META_KEYS = ("title", "abstract", "authors", "author")
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
MD_SUFFIXES = (".md", ".markdown")


def _is_published_record(d: dict) -> bool:
    for k in ID_KEYS:
        v = d.get(k)
        if isinstance(v, str) and ARXIV_ID_RE.match(v.strip()):
            return True
    for k in URL_KEYS:
        v = d.get(k)
        if isinstance(v, str) and (PUBLISHED_URL_RE.search(v) or DOI_RE.match(v.strip())):
            return True
    return False


def _encodings(s: str) -> set:
    return {json.dumps(s, ensure_ascii=False), json.dumps(s, ensure_ascii=True)}


def _collect(node, kv: dict, elems: set) -> None:
    if isinstance(node, dict):
        if _is_published_record(node):
            for k in META_KEYS:
                v = node.get(k)
                if isinstance(v, str):
                    kv.setdefault(k, set()).update(_encodings(v))
                elif isinstance(v, list):
                    for e in v:
                        if isinstance(e, str):
                            elems.update(_encodings(e))
        for v in node.values():
            _collect(v, kv, elems)
    elif isinstance(node, list):
        for v in node:
            _collect(v, kv, elems)


_KV_LINE = re.compile(r'^"(%s)"\s*:\s*(.+?)\s*,?\s*$' % "|".join(META_KEYS))


def _json_metadata_lines(text: str) -> set:
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return set()
    kv, elems = {}, set()
    _collect(data, kv, elems)
    if not kv and not elems:
        return set()
    out = set()
    for i, line in enumerate(text.split("\n"), 1):
        s = line.strip()
        if not s:
            continue
        m = _KV_LINE.match(s)
        if m and m.group(2) in kv.get(m.group(1), ()):
            out.add(i)
            continue
        if s.rstrip(",").rstrip() in elems:
            out.add(i)
    return out


def _md_metadata_lines(text: str) -> set:
    out = set()
    for i, line in enumerate(text.split("\n"), 1):
        links = MD_LINK_RE.findall(line)
        if not links or not all(PUBLISHED_URL_RE.search(url) for _, url in links):
            continue
        rest = MD_LINK_RE.sub(" ", line)
        rest = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", " ", rest)
        if not re.search(r"[A-Za-z0-9぀-ヿ一-鿿]", rest):
            out.add(i)
    return out


def metadata_line_numbers(path: str, text: str | None) -> set:
    """1-based line numbers of `text` (the whole file) that are bibliographic metadata of a published work."""
    if not text:
        return set()
    if path.endswith(".json"):
        return _json_metadata_lines(text)
    if path.endswith(MD_SUFFIXES):
        return _md_metadata_lines(text)
    return set()


def applies_to(path: str) -> bool:
    return path.endswith((".json",) + MD_SUFFIXES)


def metadata_texts(path: str, text: str | None) -> set:
    if not text:
        return set()
    lines = text.split("\n")
    return {lines[i - 1] for i in metadata_line_numbers(path, text)}


def _staged_text(path: str) -> str | None:
    # blob は worktree に出したときの中身で読む (git-crypt の暗号化 path も平文) = 同じ dir の git_blob.py
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from git_blob import read_blob_text
    return read_blob_text(f":{path}")


def filter_added(buf_lines: Iterable[str], read=_staged_text) -> list:
    """buf line = "<path>\\t<text>". Drops the lines that are metadata of a published work."""
    cache: dict = {}
    kept = []
    for raw in buf_lines:
        line = raw.rstrip("\n")
        path, sep, text = line.partition("\t")
        if sep and applies_to(path):
            if path not in cache:
                cache[path] = metadata_texts(path, read(path))
            if text in cache[path]:
                continue
        kept.append(line)
    return kept


def _selftest() -> int:
    fails = 0

    def expect(name, cond):
        nonlocal fails
        print(("PASS " if cond else "FAIL ") + name)
        fails += 0 if cond else 1

    rec = {"total": 1, "scored_papers": [{
        "arxiv_id": "2609.14627", "title": "A Study of Something", "authors": ["Jane Roe", "Taro Yamada"],
        "url": "https://arxiv.org/abs/2609.14627", "abstract": "We compute the thing in full detail here.",
        "score": 90, "reason": "Jane Roe の新作", "summary": "short"}]}
    text = json.dumps(rec, ensure_ascii=False, indent=2)
    lines = text.split("\n")
    got = {lines[i - 1].strip() for i in _json_metadata_lines(text)}
    expect("json: authors elements are metadata", '"Jane Roe",' in got and '"Taro Yamada"' in got)
    expect("json: title / abstract are metadata",
           any(s.startswith('"title"') for s in got) and any(s.startswith('"abstract"') for s in got))
    expect("json: reason (written by the author of the file) is NOT metadata", not any(s.startswith('"reason"') for s in got))
    expect("json: the url / score lines are not touched", not any(s.startswith('"url"') or s.startswith('"score"') for s in got))
    norec = dict(rec["scored_papers"][0]); norec.pop("arxiv_id"); norec["url"] = "https://example.org/x"
    t2 = json.dumps({"p": [norec]}, ensure_ascii=False, indent=2)
    expect("json: foil = no published identifier -> nothing is dropped", _json_metadata_lines(t2) == set())
    expect("json: foil = one-line JSON is not dropped (the name shares the line with other fields)",
           _json_metadata_lines(json.dumps(rec, ensure_ascii=False)) == set())
    expect("json: broken JSON -> nothing is dropped", _json_metadata_lines(text[:-5]) == set())
    md = "\n".join([
        "## refs",
        "- [A Study of Something](https://www.arxiv.org/abs/2408.05481v3)",
        "* [Other](https://doi.org/10.1103/PhysRevD.1.1)",
        "- 共同研究者 X さんの [A Study](https://arxiv.org/abs/2408.05481)",
        "- [A Study](https://example.org/a)",
        "- [A](https://arxiv.org/abs/1) and [B](https://example.org/b)",
    ])
    expect("md: a line that is only published links is metadata", _md_metadata_lines(md) == {2, 3})
    buf = [f"archive/a.json\t{l}" for l in lines] + ["README.md\tplain Jane Roe"]
    kept = filter_added(buf, read=lambda p: text if p.endswith(".json") else "plain Jane Roe")
    expect("filter-added: author line dropped, reason kept, other files untouched",
           not any('"Jane Roe",' in k for k in kept) and any('"reason"' in k for k in kept)
           and "README.md\tplain Jane Roe" in kept)
    expect("filter-added: unreadable file -> nothing dropped", len(filter_added(buf, read=lambda p: None)) == len(buf))
    print(f"published_metadata selftest: {'OK' if fails == 0 else f'{fails} FAIL'}")
    return 1 if fails else 0


def main(argv: list) -> int:
    if "--selftest" in argv:
        return _selftest()
    if len(argv) == 2 and argv[0] == "--filter-added":
        with open(argv[1], encoding="utf-8", errors="replace") as fh:
            kept = filter_added(fh)
        sys.stdout.write("".join(k + "\n" for k in kept))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
