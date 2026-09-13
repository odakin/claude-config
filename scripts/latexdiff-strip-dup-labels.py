#!/usr/bin/env python3
r"""Drop \label{...} from the DELETED side of a latexdiff output, so each label survives only on the new text.

Why (2026-09-13, research paper repo): latexdiff prints a changed or moved block twice, the old copy
inside \DIFdelbegin ... \DIFdelend and the new copy outside it.  Both copies keep their \label, so
amsmath stops with "Multiple \label's: label 'X' will be lost" (4 errors in one real diff), and an engine
that treats any `^!` line as fatal refuses to deploy the PDF.  It happens

  * at --math-markup=whole (= 1, the engine default): every changed equation is printed whole twice;
  * at coarse for a verbatim MOVE of a block with equations (conventions/latex.md#latexdiff-move-artifacts).

Removing the labels of the deleted copy is the smallest fix: the new copy keeps the label, so references
in the new text resolve; only references that pointed at a label which exists solely in the old version
become undefined, which is correct for a diff.  Nothing outside \DIFdelbegin ... \DIFdelend is touched.

Usage:
  python3 latexdiff-strip-dup-labels.py DIFF.tex            # in place; prints the number of labels removed
  python3 latexdiff-strip-dup-labels.py --selftest
"""
import re
import sys

_DEL_BLOCK = re.compile(r'\\DIFdelbegin.*?\\DIFdelend', re.S)
_LABEL = re.compile(r'\\label\s*\{[^{}]*\}')


def strip(text: str) -> tuple[str, int]:
    count = 0

    def repl(m):
        nonlocal count
        block, k = _LABEL.subn('', m.group(0))
        count += k
        return block

    return _DEL_BLOCK.sub(repl, text), count


def selftest() -> int:
    src = (r"\DIFdelbegin \begin{align}a=b\label{eq:x}\end{align}\DIFdelend" "\n"
           r"\DIFaddbegin \begin{align}a=c\label{eq:x}\end{align}\DIFaddend" "\n"
           r"text \label{sec:y} \DIFdelbegin \DIFdel{old \label {eq:z}}\DIFdelend" "\n")
    out, n = strip(src)
    ok = (n == 2 and out.count(r'\label{eq:x}') == 1 and r'\DIFaddbegin \begin{align}a=c\label{eq:x}' in out
          and r'\label{sec:y}' in out and 'eq:z' not in out)
    out2, n2 = strip(r"no diff markup \label{eq:a}")
    ok &= n2 == 0 and out2 == r"no diff markup \label{eq:a}"
    print('selftest', 'OK' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    if len(sys.argv) == 2 and sys.argv[1] == '--selftest':
        sys.exit(selftest())
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    path = sys.argv[1]
    with open(path, encoding='utf-8') as f:
        src = f.read()
    out, n = strip(src)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(out)
    print(n)
