#!/usr/bin/env python3
"""検査 script の出力を「証跡 file」 として残す helper (= 後から「いつ何を出したか」 を再構成できるようにする)。

由来 (2026-09-12): 提出物の入力後検収で事故が起きた RCA で、**検査がいつ何を出したかの記録が
どこにも無く**、RCA の中心部分 (= 人が何を見て何を無効化したか) が推定でしか書けなかった。
検査は走っていたが、出力は端末に流れて消えていた。

∴ **検査の出力は artifact にする**。人の記憶も、session の transcript も carrier ではない
(transcript は消える — 実際に当該 session は検索 store に残っていなかった)。
一般則 = docs/convention-design-principles.md#human-memory-not-a-carrier /
#measured-vs-inferred-provenance (= 後で「測ったのか説明したのか」 を切り分けられるようにする)。

使い方:

    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[N] / "claude-config/scripts/lib"))
    from run_log import start_log
    ...
    start_log(args.dir, "verify-web-entry")     # 以降の print が file にも落ちる

⚠️ **拡張子を `.log` にしない**。多くの repo の `.gitignore` が `*.log` を落とすので、
証跡が commit されず「次回は推定不要」 という目的が果たせない (= 2026-09-12 に一度踏んだ)。
本 helper は `.txt` を使う。
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path


class Tee:
    """stdout を画面と file の両方へ。 close は明示しない (= process 終了に任せる)。"""

    def __init__(self, path: Path):
        self.f = open(path, "a", encoding="utf-8")
        self.o = sys.stdout

    def write(self, s):  # noqa: D102
        self.o.write(s)
        self.f.write(s)

    def flush(self):  # noqa: D102
        self.o.flush()
        self.f.flush()


def start_log(dirpath, tag: str, *, header: str = "") -> Path | None:
    """`<dirpath>/run-<日時>-<tag>.txt` に以後の stdout を複製する。

    dirpath が dir でなければ **何もしない** (= 検査そのものを止めない fail-open)。
    戻り値 = 書いている path (無効なら None)。
    """
    d = Path(dirpath)
    if not d.is_dir():
        return None
    now = datetime.datetime.now()
    path = d / f"run-{now:%Y%m%d-%H%M%S}-{tag}.txt"
    sys.stdout = Tee(path)
    print(f"# {now:%Y-%m-%d %H:%M:%S}  {tag}  dir={d}" + (f"  {header}" if header else ""))
    return path


if __name__ == "__main__":  # 簡易 selftest
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        real = sys.stdout
        p = start_log(td, "selftest")
        print("hello")
        sys.stdout = real
        assert p is not None and p.exists() and p.suffix == ".txt", p
        body = p.read_text(encoding="utf-8")
        assert "hello" in body and "selftest" in body, body
        assert start_log(Path(td) / "nope", "x") is None, "存在しない dir では fail-open"
    print("run_log selftest OK: .txt に書く / 存在しない dir では何もしない")
