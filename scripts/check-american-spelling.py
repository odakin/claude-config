#!/usr/bin/env python3
"""Reject curated British spellings in live LaTeX prose and figure text.

Canonical layer-1 source:
https://github.com/odakin/claude-config/blob/main/scripts/check-american-spelling.py
Distribution contract:
https://github.com/odakin/claude-config/blob/main/conventions/shared-repo.md#style-checker-mirror
Project copies are generated mirrors so collaborators and CI can run the gate
offline without an owner-specific repository or machine path. A project must
adopt its American-English rule in its own shared instructions; this script is
a backstop, not the policy source.

Scanned:
  * **/*.tex outside archive, notes, external, vendor, build, and dist trees,
    excluding TeX comments and verbatim-like environments;
  * string literals, f-string text, and docstrings in fig/**/*.py.

Deliberately not scanned:
  * refs.bib and generated bibliography files, because source titles retain
    their published spelling;
  * archive and working-note trees;
  * TeX identifier arguments such as labels, citations, references, URLs,
    package names, and included paths;
  * a source line carrying the exact ``brit-ok`` pragma, for an external
    quotation, proper name, or external identifier that must stay unchanged.

The word list is curated rather than a blanket ``-ise`` rule. Extend it and
its positive/negative selftests when a new missed spelling class appears.

Usage:
  python3 scripts/check-american-spelling.py
  python3 scripts/check-american-spelling.py --selftest
  python3 scripts/check-american-spelling.py --root PATH
"""

from __future__ import annotations

import argparse
import ast
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path


EXCLUDED_DIR_NAMES = (
    ".git", "archive", "archives", "build", "dist", "external", "externals",
    "notes", "plans", "vendor", "vendors",
)

IZ_SUFFIX = r"(?=(?:e|ed|es|er|ers|ing|ingly|ation|ations|able|ability)\b)"
IZ_STEMS = (
    "normalis", "organis", "symmetris", "antisymmetris", "factoris",
    "parametris", "parameteris", "renormalis", "regularis", "quantis",
    "diagonalis", "minimis", "maximis", "summaris", "generalis",
    "specialis", "stabilis", "localis", "linearis", "discretis",
    "initialis", "standardis", "characteris", "recognis", "utilis",
    "harmonis", "idealis", "visualis", "trivialis", "canonicalis",
    "formalis", "realis", "prioritis", "categoris", "serialis",
    "synchronis", "polaris", "densitis", "dualis", "hermitis",
    "rationalis",
)
WORD_PATTERNS = (
    r"analys(?=(?:e|ed|er|ers|ing)\b)",
    r"catalys(?=(?:e|ed|ing)\b)",
    r"paralys(?=(?:e|ed|ing)\b)",
    r"emphasis(?=(?:e|ed|es|ing)\b)",
    r"synthesis(?=(?:e|ed|es|ing)\b)",
    r"colour", r"behaviour", r"flavour", r"favour", r"honour",
    r"neighbour", r"endeavour", r"vapour", r"labour", r"armour",
    r"harbour", r"humour", r"rigour", r"vigour", r"savour",
    r"\bcentre(s|d)?\b", r"\bcentring\b", r"\bfibre(s)?\b",
    r"\bmetre(s)?\b", r"\bkilometre(s)?\b", r"\bcentimetre(s)?\b",
    r"\blitre(s)?\b", r"\bcalibre\b", r"\bspectre\b", r"\btheatre\b",
    r"\bmanoeuvr", r"\b(?:mis|re)?labell(?:ed|ing)\b",
    r"\bmodell(?:ed|ing)\b",
    r"\bcancell(ed|ing)\b", r"\btravell(ed|ing|er)",
    r"\blevell(ed|ing)\b", r"\bsignall(ed|ing)\b",
    r"\btunnell(ed|ing)\b", r"\bchannell(ed|ing)\b",
    r"\btotall(ed|ing)\b", r"\bequall(ed|ing)\b",
    r"artefact", r"\bgrey\b", r"\bamongst\b", r"\bwhilst\b",
    r"\btowards\b", r"\bcatalogue", r"defence", r"offence",
    r"licenc", r"pretence", r"sceptic", r"\bprogramme(s)?\b",
    r"\bfocuss(ed|es|ing)\b", r"sulphur", r"\banalogue(s)?\b",
)

BRIT_OK = re.compile(r"\bbrit-ok\b")
VERBATIM_BEGIN = re.compile(r"\\begin\{(?:verbatim\*?|lstlisting|minted)\}")
VERBATIM_END = re.compile(r"\\end\{(?:verbatim\*?|lstlisting|minted)\}")

# Arguments denote identifiers or external material rather than printed prose.
IDENTIFIER_COMMANDS = {
    "bibliography", "bibliographystyle", "Cref", "cref", "cite", "citep",
    "citet", "documentclass", "eqref", "externaldocument", "href",
    "includegraphics", "input", "label", "labelcref", "pageref", "path",
    "ref", "url", "usepackage",
}
COMMAND_START = re.compile(r"\\([A-Za-z]+)\*?(?:\s*\[[^\]]*\])?\s*\{")


@dataclass(frozen=True)
class Hit:
    path: Path
    line: int
    word: str
    context: str


def build_patterns() -> tuple[re.Pattern[str], ...]:
    patterns = [re.compile(stem + IZ_SUFFIX, re.I) for stem in IZ_STEMS]
    patterns.extend(re.compile(pattern, re.I) for pattern in WORD_PATTERNS)
    return tuple(patterns)


def strip_tex_comment(line: str) -> str:
    index = 0
    while index < len(line):
        if line[index] == "\\" and index + 1 < len(line):
            index += 2
            continue
        if line[index] == "%":
            return line[:index]
        index += 1
    return line


def mask_identifier_arguments(line: str) -> str:
    chars = list(line)
    cursor = 0
    while True:
        match = COMMAND_START.search(line, cursor)
        if match is None:
            break
        cursor = match.end()
        if match.group(1) not in IDENTIFIER_COMMANDS:
            continue
        depth = 1
        index = match.end()
        while index < len(line) and depth:
            if line[index] == "\\":
                index += 2
                continue
            if line[index] == "{":
                depth += 1
            elif line[index] == "}":
                depth -= 1
            if depth:
                chars[index] = " "
            index += 1
        cursor = index
    return "".join(chars)


def first_british(text: str, patterns: tuple[re.Pattern[str], ...]) -> str | None:
    matches = [match for pattern in patterns if (match := pattern.search(text))]
    if not matches:
        return None
    return min(matches, key=lambda match: match.start()).group(0)


def scan_tex(path: Path, patterns: tuple[re.Pattern[str], ...]) -> list[Hit]:
    hits: list[Hit] = []
    in_verbatim = False
    source_lines = path.read_text(encoding="utf-8").splitlines()
    body_start = next(
        (index for index, source in enumerate(source_lines) if r"\begin{document}" in source),
        -1,
    )
    for line_number, source in enumerate(source_lines[body_start + 1:], body_start + 2):
        if BRIT_OK.search(source):
            continue
        if VERBATIM_BEGIN.search(source):
            in_verbatim = True
            continue
        if in_verbatim:
            if VERBATIM_END.search(source):
                in_verbatim = False
            continue
        prose = mask_identifier_arguments(strip_tex_comment(source))
        if word := first_british(prose, patterns):
            hits.append(Hit(path, line_number, word, source.strip()[:120]))
    return hits


def scan_python(path: Path, patterns: tuple[re.Pattern[str], ...]) -> list[Hit]:
    source = path.read_text(encoding="utf-8")
    source_lines = source.splitlines()
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [Hit(path, exc.lineno or 1, "<syntax-error>", exc.msg)]
    hits: list[Hit] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        start = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", start)
        original = "\n".join(source_lines[start - 1:end])
        if BRIT_OK.search(original):
            continue
        for offset, value_line in enumerate(node.value.splitlines() or [node.value]):
            if word := first_british(value_line, patterns):
                hits.append(Hit(path, start + offset, word, value_line.strip()[:120]))
                break
    return hits


def excluded(path: Path, root: Path) -> bool:
    parts = path.relative_to(root).parts[:-1]
    return any(
        part in EXCLUDED_DIR_NAMES or part.startswith("archive-")
        for part in parts
    )


def target_files(root: Path) -> tuple[list[Path], list[Path]]:
    tex_files = sorted(
        path for path in root.rglob("*.tex")
        if path.is_file() and not excluded(path, root)
    )
    figure_root = root / "fig"
    if figure_root.is_dir():
        python_files = sorted(
            path for path in figure_root.rglob("*.py")
            if path.is_file() and not excluded(path, root)
        )
    else:
        python_files = []
    return [path for path in tex_files if path.is_file()], python_files


def collect_hits(root: Path) -> list[Hit]:
    patterns = build_patterns()
    tex_files, python_files = target_files(root)
    hits: list[Hit] = []
    for path in tex_files:
        hits.extend(scan_tex(path, patterns))
    for path in python_files:
        hits.extend(scan_python(path, patterns))
    return hits


def run(root: Path) -> int:
    hits = collect_hits(root)
    if not hits:
        return 0
    print(f"check-american-spelling: {len(hits)} finding(s) in live prose/figure text")
    for hit in hits:
        try:
            relative = hit.path.relative_to(root)
        except ValueError:
            relative = hit.path
        print(f"  {relative}:{hit.line}: {hit.word!r} | {hit.context}")
    return 1


def selftest() -> int:
    patterns = build_patterns()

    for british in (
        "Packet centre", "centred at the detector", "towards the detector",
        "labelled curve", "no classical analogue", "normalisation factor",
        "coloured region", "the grey artefact",
    ):
        assert first_british(british, patterns), british
    for american in (
        "Packet center", "centered at the detector", "toward the detector",
        "labeled curve", "no classical analog", "normalization factor",
        "otherwise", "exercise", "comprise", "precise", "cancellation",
        "compelled", "controlled", "fulfilled", "the analysis",
    ):
        assert first_british(american, patterns) is None, american

    with tempfile.TemporaryDirectory(prefix="american-spelling-") as temporary:
        root = Path(temporary)
        (root / "paper-energy").mkdir()
        (root / "paper-deficiency").mkdir()
        (root / "fig").mkdir()
        (root / "notes").mkdir()
        (root / "archive-old").mkdir()
        (root / "time-energy-head-on.tex").write_text(
            "A clean center.\n"
            "A source title says centre. % brit-ok\n"
            "\\label{normalisation-anchor}\n",
            encoding="utf-8",
        )
        (root / "paper-energy/main.tex").write_text(
            "The packet is centred here.\n", encoding="utf-8"
        )
        (root / "paper-deficiency/main.tex").write_text(
            "\\begin{verbatim}\ncolour\n\\end{verbatim}\n", encoding="utf-8"
        )
        (root / "fig/diagram.tex").write_text(
            "\\node {A labelled curve};\n% packet centre\n", encoding="utf-8"
        )
        (root / "fig/plot.py").write_text(
            'label = "Packet centre"\nexternal = "colour-id"  # brit-ok\n',
            encoding="utf-8",
        )
        (root / "refs.bib").write_text(
            "title={The Colour Centre}\n", encoding="utf-8"
        )
        (root / "notes/old.tex").write_text(
            "The archived colour centre.\n", encoding="utf-8"
        )
        (root / "archive-old/old.tex").write_text(
            "The archived colour centre.\n", encoding="utf-8"
        )
        hits = collect_hits(root)
        found = sorted((hit.path.relative_to(root).as_posix(), hit.word.lower()) for hit in hits)
        assert found == [
            ("fig/diagram.tex", "labelled"),
            ("fig/plot.py", "centre"),
            ("paper-energy/main.tex", "centred"),
        ], found

    print("check-american-spelling selftest: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    return run(args.root.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
