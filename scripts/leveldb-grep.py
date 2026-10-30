#!/usr/bin/env python3
"""leveldb-grep.py — Chromium / Electron の Local Storage (LevelDB) を読むだけで検索する (圧縮された .ldb も、 追加の library なし)

なぜ: desktop app の保存 (サイドバーの状態・起動先の履歴など) は LevelDB の .ldb に Snappy で圧縮されて入り、
  素の grep では語が途中で切れて見つからない・読めない (実測)。 表の索引を辿って block を解凍してから検索する。
  書き込みはしない。 動いている app の dir をそのまま読んでよい (読むだけ、 lock を取らない)。

usage:
  leveldb-grep.py <dir か file ...> -e <語> [-e <語> ...] [--before 500] [--after 300]
  leveldb-grep.py --selftest

  例 (macOS の Claude desktop): leveldb-grep.py "$HOME/Library/Application Support/Claude/Local Storage/leveldb" -e environmentId

出力: 1 件ごとに file 名・key・語の前後。 .log (未圧縮の追記) は key を切り出さず、 file の中の位置で出す。
⚠️ 検索の語は file の byte 列と照合する = UTF-16 で保存された値 (Chromium の Local Storage の一部) は ASCII の語でも
   当たらないことがある。 0 件を「無い」 と読まない。 ⚠️ 中身に個人の情報が入りうる = 出力を公開層に貼らない。
"""

import argparse
import glob
import os
import re
import struct
import sys
import tempfile


def varint(b, i):
    r = s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        if c < 0x80:
            return r, i
        s += 7


def snappy(b):
    """Snappy の block を解凍する (raw format)。"""
    _, i = varint(b, 0)
    out = bytearray()
    while i < len(b):
        t = b[i]
        i += 1
        k = t & 3
        if k == 0:
            ln = t >> 2
            if ln >= 60:
                x = ln - 59
                ln = int.from_bytes(b[i:i + x], "little")
                i += x
            ln += 1
            out += b[i:i + ln]
            i += ln
            continue
        if k == 1:
            ln = ((t >> 2) & 7) + 4
            off = ((t >> 5) << 8) | b[i]
            i += 1
        elif k == 2:
            ln = (t >> 2) + 1
            off = int.from_bytes(b[i:i + 2], "little")
            i += 2
        else:
            ln = (t >> 2) + 1
            off = int.from_bytes(b[i:i + 4], "little")
            i += 4
        for _ in range(ln):
            out.append(out[-off])
    return bytes(out)


def block(d, off, size):
    raw = d[off:off + size]
    return snappy(raw) if d[off + size] == 1 else raw


def entries(b):
    """block の (key, value) を順に返す (key は前の key との共有部分を復元する)。"""
    nr = struct.unpack("<I", b[-4:])[0]
    end = len(b) - 4 - 4 * nr
    i = 0
    key = b""
    while i < end:
        sh, i = varint(b, i)
        ns, i = varint(b, i)
        vl, i = varint(b, i)
        key = key[:sh] + b[i:i + ns]
        i += ns
        yield key, b[i:i + vl]
        i += vl


def table_items(d):
    """.ldb の全 (key, value)。 footer → 索引 block → data block の順に辿る。"""
    foot = d[-48:]
    _, i = varint(foot, 0)
    _, i = varint(foot, i)
    index_off, i = varint(foot, i)
    index_size, i = varint(foot, i)
    for _, handle in entries(block(d, index_off, index_size)):
        off, j = varint(handle, 0)
        size, _ = varint(handle, j)
        yield from entries(block(d, off, size))


def windows(value, pats, before, after):
    for p in pats:
        for m in re.finditer(re.escape(p), value):
            yield value[max(0, m.start() - before):m.end() + after].decode("utf-8", "replace")


def scan_file(path, pats, before, after):
    """(key の表示, 語の前後) を返す。 読めない file は飛ばして stderr に出す。"""
    d = open(path, "rb").read()
    if path.endswith(".ldb"):
        try:
            for k, v in table_items(d):
                for w in windows(v, pats, before, after):
                    yield k[:80].decode("utf-8", "replace"), w
        except Exception as e:
            print(f"skip {path}: {e}", file=sys.stderr)
        return
    for w in windows(d, pats, before, after):
        yield "(log)", w


def expand(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            out += sorted(glob.glob(os.path.join(p, "*.ldb")) + glob.glob(os.path.join(p, "*.log")))
        else:
            out.append(p)
    return out


def main_scan(paths, pats, before, after):
    n = 0
    for f in expand(paths):
        for key, w in scan_file(f, pats, before, after):
            n += 1
            print(f"--- {os.path.basename(f)}  key={key!r}\n{w}\n")
    print(f"{n} 件", file=sys.stderr)
    return n


def selftest():
    # 合成の値 (実在の保存の中身は使わない)
    def enc(n):
        o = bytearray()
        while n >= 0x80:
            o.append((n & 0x7F) | 0x80)
            n >>= 7
        o.append(n)
        return bytes(o)

    assert snappy(enc(9) + bytes([8]) + b"abc" + bytes([0x09, 3])) == b"abcabcabc"

    def blk(items):
        body = b"".join(enc(0) + enc(len(k)) + enc(len(v)) + k + v for k, v in items)
        return body + struct.pack("<I", 0) + struct.pack("<I", 1)

    value = b'{"target":{"kind":"bridge","environmentId":"env_TEST"}}'
    data = blk([(b"key-a", value), (b"key-b", b"other")])
    raw = enc(len(data)) + bytes([(60 << 2), len(data) - 1]) + data   # 全体を literal の Snappy にした block
    trailer = b"\x01\0\0\0\0"
    index = blk([(b"key-b", enc(0) + enc(len(raw)))])
    index_off = len(raw) + len(trailer)
    foot = enc(0) + enc(0) + enc(index_off) + enc(len(index))
    foot += b"\0" * (40 - len(foot)) + b"\x57\xfb\x80\x8b\x24\x75\x47\xdb"
    table = raw + trailer + index + b"\0\0\0\0\0" + foot

    with tempfile.TemporaryDirectory() as td:
        ldb = os.path.join(td, "000001.ldb")
        log = os.path.join(td, "000002.log")
        open(ldb, "wb").write(table)
        open(log, "wb").write(b"....environmentId....")
        got = list(scan_file(ldb, [b"environmentId"], 20, 20))
        assert len(got) == 1 and got[0][0] == "key-a" and "env_TEST" in got[0][1], got
        assert list(scan_file(ldb, [b"absent"], 5, 5)) == []
        assert [k for k, _ in scan_file(log, [b"environmentId"], 2, 2)] == ["(log)"]
        assert expand([td]) == [ldb, log]
        broken = os.path.join(td, "000003.ldb")
        open(broken, "wb").write(b"\0" * 10)
        assert list(scan_file(broken, [b"x"], 1, 1)) == [], "壊れた file は飛ばして止まらない"
    print("leveldb-grep selftest: ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="*")
    ap.add_argument("-e", dest="pats", action="append", default=[])
    ap.add_argument("--before", type=int, default=500)
    ap.add_argument("--after", type=int, default=300)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return 0
    if not a.paths or not a.pats:
        ap.error("読む dir か file と、 -e の語が要る")
    return 0 if main_scan(a.paths, [p.encode() for p in a.pats], a.before, a.after) else 1


if __name__ == "__main__":
    sys.exit(main())
