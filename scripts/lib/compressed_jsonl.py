#!/usr/bin/env python3
"""compressed_jsonl.py — 会話記録の .jsonl と、 zstd で圧縮した .jsonl.zst を、 同じ形で 1 行ずつ読む。

なぜ要るか: Codex は古くなった session の記録 (rollout-*.jsonl) を zstd で圧縮し、 `.jsonl.zst` に置き換える
(動いている session の記録は平文のまま = 実測)。 `*.jsonl` だけを glob する
読み手は圧縮された記録を黙って飛ばし、 何で引いても 0 件と出る (= 0 件が「記録に無い」 の証拠に見える)。

展開の手段 (上から順に、 最初に使えるもの):
  1. Python 3.14 以降の標準の `compression.zstd`
  2. Python の `zstandard` module (import できれば)
  3. `zstd` の command (PATH にあれば。 subprocess で `zstd -q -d -c -- <file>`)
  4. どれも無い → 読めない。 黙って空にせず、 呼び出し側が渡した tally (Counter) に "no-means" を数える
展開の途中で失敗した (壊れた file 等) ときは、 そこまでの行を返したうえで "failed" を数える。
module を pip で入れる手順は持たない (= 入れるかは各機械の持ち主が決める)。

使い方:
  tally = collections.Counter()
  with open_lines(path, tally=tally) as lines:   # path は .jsonl でも .jsonl.zst でもよい
      for line in lines: ...
  msg = report(tally)                            # 読めなかった本数の 1 行 (無ければ None)

平文の .jsonl を開けない (OSError) ときは、 これまでどおり例外を呼び出し側に返す (= 既存の読み手の扱いを変えない)。
stdlib only / 公開層 (個人の値を持たない)。 --selftest 内蔵。
"""
from __future__ import annotations

import collections
import contextlib
import io
import shutil
import subprocess
import sys

PLAIN = ".jsonl"
COMPRESSED = ".jsonl.zst"
# test 用: None = 手段を調べる / "stdlib" / "module" / "command" / "none" = その手段に固定する
FORCE: str | None = None


def is_record(name: str) -> bool:
    """会話記録の file 名か (平文 .jsonl か圧縮 .jsonl.zst)。"""
    return name.endswith(PLAIN) or name.endswith(COMPRESSED)


def base_name(name: str) -> str:
    """圧縮の拡張子を外した名 (`x.jsonl.zst` → `x.jsonl`)。 同じ記録の平文と圧縮を同じ鍵にする。"""
    return name[: -len(".zst")] if name.endswith(COMPRESSED) else name


def stem(name: str) -> str:
    """記録の拡張子 (.jsonl / .jsonl.zst) を外した名 = session id を含む部分。"""
    return base_name(name)[: -len(PLAIN)] if is_record(name) else name


def _stdlib():
    try:
        from compression import zstd  # type: ignore  # Python 3.14+
        return zstd
    except Exception:
        return None


def _module():
    try:
        import zstandard  # type: ignore
        return zstandard
    except Exception:
        return None


def means() -> str:
    """この機械で使える展開の手段 = "stdlib" / "module" / "command" / "none"。"""
    if FORCE is not None:
        return FORCE
    if _stdlib() is not None:
        return "stdlib"
    if _module() is not None:
        return "module"
    if shutil.which("zstd"):
        return "command"
    return "none"


def _plain_lines(fh):
    for line in fh:
        yield line


@contextlib.contextmanager
def open_lines(path, *, errors: str = "ignore", tally: collections.Counter | None = None):
    """path の行 (str、 改行つき) を返す iterator を yield する。 圧縮なら展開して読む。"""
    name = str(path)
    if not name.endswith(COMPRESSED):
        with open(path, encoding="utf-8", errors=errors) as fh:
            yield _plain_lines(fh)
        return
    how = means()
    if how == "none":
        if tally is not None:
            tally["no-means"] += 1
        yield iter(())
        return
    if how in ("stdlib", "module"):
        with open(path, "rb") as raw:
            if how == "stdlib":
                reader = _stdlib().open(raw, "rt", encoding="utf-8", errors=errors)
            else:
                reader = io.TextIOWrapper(_module().ZstdDecompressor().stream_reader(raw), encoding="utf-8", errors=errors)

            def gen():
                try:
                    for line in reader:
                        yield line
                except Exception:
                    if tally is not None:
                        tally["failed"] += 1
            yield gen()
        return
    proc = subprocess.Popen([shutil.which("zstd") or "zstd", "-q", "-d", "-c", "--", name],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    state = {"eof": False}

    def gen():
        for line in io.TextIOWrapper(proc.stdout, encoding="utf-8", errors=errors):
            yield line
        state["eof"] = True
    try:
        yield gen()
    finally:
        if proc.poll() is None and not state["eof"]:
            proc.kill()  # 呼び出し側が途中でやめた = 残りは要らない (失敗とは数えない)
        proc.stdout.close()
        rc = proc.wait()
        if state["eof"] and rc != 0 and tally is not None:
            tally["failed"] += 1


def report(tally: collections.Counter, what: str = "圧縮した記録 (.jsonl.zst)") -> str | None:
    """読めなかった本数の 1 行。 読めなかったものが無ければ None。"""
    parts = []
    if tally.get("no-means"):
        parts.append(f"{tally['no-means']} 本は展開の手段が無い (Python 3.14 の compression.zstd も zstandard の module も"
                     " zstd の command も見つからない)")
    if tally.get("failed"):
        parts.append(f"{tally['failed']} 本は展開の途中で失敗した (そこまでの行だけ読んだ)")
    if not parts:
        return None
    return f"⚠️ {what} を読めなかった: " + " / ".join(parts) + "。 結果はその分だけ欠けている"


def compress_for_test(data: bytes) -> bytes | None:
    """selftest 用の圧縮。 手段が無ければ None。"""
    std = _stdlib()
    if std is not None:
        return std.compress(data)
    mod = _module()
    if mod is not None:
        return mod.ZstdCompressor().compress(data)
    exe = shutil.which("zstd")
    if exe:
        return subprocess.run([exe, "-q", "-c"], input=data, capture_output=True, check=True).stdout
    return None


def _selftest() -> int:
    import tempfile
    from pathlib import Path
    global FORCE
    results = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        results.append(bool(cond))

    body = "".join(f'{{"n": {i}, "t": "りんご {i}"}}\n' for i in range(3)).encode()
    packed = compress_for_test(body)
    with tempfile.TemporaryDirectory() as td:
        plain = Path(td) / "a.jsonl"
        plain.write_bytes(body)
        with open_lines(plain) as lines:
            check("平文の .jsonl を読む", "".join(lines).encode() == body)
        check("名の扱い", is_record("x.jsonl") and is_record("x.jsonl.zst") and not is_record("x.json")
              and base_name("x.jsonl.zst") == "x.jsonl" and stem("r-1.jsonl.zst") == "r-1" and stem("r-1.jsonl") == "r-1")
        z = Path(td) / "a.jsonl.zst"
        if packed is None:
            print("SKIP 圧縮した記録を読む (この機械に展開の手段が無い)")
        else:
            z.write_bytes(packed)
            for how in ("stdlib", "module", "command"):
                if ((how == "stdlib" and _stdlib() is None) or (how == "module" and _module() is None)
                        or (how == "command" and not shutil.which("zstd"))):
                    print(f"SKIP {how} で展開する (この機械に無い)")
                    continue
                FORCE = how
                try:
                    t = collections.Counter()
                    with open_lines(z, tally=t) as lines:
                        got = "".join(lines).encode()
                    check(f"{how} で展開して読む", got == body and not t)
                    t = collections.Counter()
                    with open_lines(z, tally=t) as lines:
                        first = next(iter(lines))
                    check(f"{how}: 途中でやめても失敗と数えない", first.startswith('{"n": 0') and not t)
                    bad = Path(td) / "bad.jsonl.zst"
                    bad.write_bytes(packed[: len(packed) // 2])
                    t = collections.Counter()
                    with open_lines(bad, tally=t) as lines:
                        list(lines)
                    check(f"{how}: 壊れた file は failed と数える", t == {"failed": 1})
                finally:
                    FORCE = None
        z.write_bytes(packed or b"x")
        FORCE = "none"
        try:
            t = collections.Counter()
            with open_lines(z, tally=t) as lines:
                check("手段が無いときは空を返し no-means と数える", list(lines) == [] and t == {"no-means": 1})
            msg = report(t)
            check("手段が無いときの 1 行に本数と理由", msg is not None and "1 本は展開の手段が無い" in msg)
        finally:
            FORCE = None
        check("読めなかったものが無ければ 1 行も出さない", report(collections.Counter()) is None)
    print(f"{sum(results)}/{len(results)} PASS")
    return 0 if all(results) else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(_selftest())
    print(__doc__)
