#!/usr/bin/env python3
"""claude-app-bundle.py — Claude desktop app の挙動を、 docs や推測でなく app 本体 (画面の JS bundle・翻訳・main process の app.asar・埋込 engine) から確かめる検索道具

使い方 (手順と落とし穴 = conventions/claude-app-bundle-reading.md):
  claude-app-bundle.py version                          app と埋込 engine の版 (読んだ版を記録に残す)
  claude-app-bundle.py i18n "見つかりませんでした"        画面の文言 → 翻訳 key と英語原文
  claude-app-bundle.py grep FRHpsQyd2G                    key や語を画面の bundle から探す (--where asar|engine も可)
  claude-app-bundle.py resolve cd2efac6e-DdNhqOhn.js Se   minified 名がどの chunk のどの関数かを辿る
  claude-app-bundle.py asar-ls index.chunk                app.asar の中の file 一覧 (部分一致で絞る)
  claude-app-bundle.py --selftest

なぜ grep でなく本 script か: bundle は 1 行が MB 級の minified JS で、 `grep -o '.{0,80}X.{0,200}'` は
時間切れになる (実測)。 python の re で bytes を読み、 前後だけ切り出す。 app.asar は独自形式で、 中の
main process の file は展開しないと読めない。
"""
from __future__ import annotations

import argparse
import glob
import json
import mmap
import os
import re
import struct
import subprocess
import sys
import tempfile

DEFAULT_APP = "/Applications/Claude.app"
ENGINE_GLOB = "~/Library/Application Support/Claude/claude-code/*/claude.app/Contents/MacOS/claude"


def paths(app: str) -> dict:
    res = os.path.join(app, "Contents", "Resources")
    return {
        "assets": os.path.join(res, "ion-dist", "assets"),
        "i18n": os.path.join(res, "ion-dist", "i18n"),
        "asar": os.path.join(res, "app.asar"),
        "info": os.path.join(app, "Contents", "Info.plist"),
    }


def engine_path(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    cands = glob.glob(os.path.expanduser(ENGINE_GLOB))

    def key(p):
        v = p.split("/claude-code/")[1].split("/")[0]
        return [int(x) if x.isdigit() else 0 for x in re.split(r"[.-]", v)]

    return max(cands, key=key) if cands else None


# ---- asar ---------------------------------------------------------------------------

def asar_read_header(path: str) -> tuple[dict, int]:
    """(header の JSON, data 部の開始 offset)。 形式 = uint32 4 / uint32 header pickle size / uint32 / uint32 JSON 長 / JSON。"""
    with open(path, "rb") as f:
        head = f.read(16)
        size = struct.unpack("<I", head[4:8])[0]
        strlen = struct.unpack("<I", head[12:16])[0]
        header = json.loads(f.read(strlen))
    return header, 8 + size


def asar_files(header: dict, prefix: str = "") -> list[tuple[str, dict]]:
    out = []
    for name, node in (header.get("files") or {}).items():
        p = f"{prefix}/{name}"
        if "files" in node:
            out.extend(asar_files(node, p))
        else:
            out.append((p, node))
    return out


def asar_read(path: str, node: dict, base: int) -> bytes | None:
    if node.get("unpacked"):
        return None  # app.asar.unpacked/ 側に実体がある
    with open(path, "rb") as f:
        f.seek(base + int(node["offset"]))
        return f.read(int(node["size"]))


def asar_write(path: str, files: dict[str, bytes]) -> None:
    """selftest 用の最小 asar 書き出し (平らな file 群だけ)。"""
    entries, blob, off = {}, b"", 0
    for name, data in files.items():
        entries[name] = {"size": len(data), "offset": str(off)}
        blob += data
        off += len(data)
    js = json.dumps({"files": entries}).encode()
    pad = (4 - len(js) % 4) % 4
    pickle = struct.pack("<II", 4 + len(js) + pad, len(js)) + js + b"\0" * pad
    with open(path, "wb") as f:
        f.write(struct.pack("<II", 4, len(pickle)) + pickle + blob)


# ---- 検索 -----------------------------------------------------------------------------

def snippet(buf, start: int, end: int, ctx: int) -> str:
    return bytes(buf[max(0, start - ctx):end + ctx]).decode("utf-8", "replace").replace("\n", " ")


def grep_sources(where: str, app: str, engine: str | None):
    """(表示名, bytes 相当) を順に返す。"""
    p = paths(app)
    if where == "renderer":
        for fp in sorted(glob.glob(os.path.join(p["assets"], "**", "*.js"), recursive=True)):
            with open(fp, "rb") as f:
                yield os.path.relpath(fp, p["assets"]), f.read()
    elif where == "asar":
        header, base = asar_read_header(p["asar"])
        for name, node in asar_files(header):
            if name.endswith((".js", ".cjs", ".mjs", ".json")):
                data = asar_read(p["asar"], node, base)
                if data is not None:
                    yield "app.asar:" + name, data
    elif where == "engine":
        ep = engine_path(engine)
        if ep:
            label = ep.split("/claude-code/")[1].split("/")[0] if "/claude-code/" in ep else os.path.basename(ep)
            with open(ep, "rb") as f:
                yield "engine:" + label, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)


def cmd_grep(args) -> int:
    rx = re.compile(args.pattern.encode())
    n = 0
    for name, buf in grep_sources(args.where, args.app, args.engine):
        per = 0
        for m in rx.finditer(buf):
            print(f"{name}:{m.start()}: {snippet(buf, m.start(), m.end(), args.context)}")
            n += 1
            per += 1
            if per >= args.per_file or n >= args.max:
                break
        if n >= args.max:
            break
    return 0 if n else 1


def i18n_lookup(i18n_dir: str, text: str, locale: str, en: str = "en-US") -> list[tuple[str, str, str]]:
    def load(loc):
        try:
            with open(os.path.join(i18n_dir, f"{loc}.json"), encoding="utf-8") as f:
                return json.load(f)
        except OSError:
            return {}

    src, eng = load(locale), load(en)
    return [(k, v, eng.get(k, "")) for k, v in src.items() if isinstance(v, str) and text in v]


def cmd_i18n(args) -> int:
    rows = i18n_lookup(paths(args.app)["i18n"], args.text, args.locale)
    for k, v, e in rows:
        print(f"{k}\t{v}\t{e}")
    return 0 if rows else 1


EXPORT_RE = re.compile(r"export\s*\{([^}]*)\}\s*;?\s*$")
IMPORT_RE = re.compile(r"import\s*\{([^}]*)\}\s*from\s*\"([^\"]+)\"")


def _pairs(spec: str) -> list[tuple[str, str]]:
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        a, _, b = part.partition(" as ")
        out.append((a.strip(), (b or a).strip()))
    return out


def definition(src: str, name: str) -> str | None:
    e = re.escape(name)
    m = re.search(rf"function {e}\(|(?<![\w$.]){e}=(?!=)", src)
    return src[m.start():m.start() + 400] if m else None


def resolve(assets: str, chunk: str, name: str, depth: int = 4) -> list[str]:
    """chunk 内の名前を、 import を辿って定義まで追う。 各段の説明行を返す。"""
    lines = []
    cur, ident = chunk, name
    for _ in range(depth):
        fp = cur if os.path.isabs(cur) else next(iter(glob.glob(os.path.join(assets, "**", os.path.basename(cur)), recursive=True)), None)
        if not fp:
            lines.append(f"{cur}: 見つからない")
            break
        with open(fp, encoding="utf-8", errors="replace") as f:
            src = f.read()
        found = None
        for m in IMPORT_RE.finditer(src[:60000]):
            for exported, local in _pairs(m.group(1)):
                if local == ident:
                    found = (exported, m.group(2))
        if found:
            lines.append(f"{os.path.basename(fp)}: {ident} = import {found[0]} from {found[1]}")
            cur = os.path.join(os.path.dirname(fp), found[1])
            with open(cur, encoding="utf-8", errors="replace") as f:
                src2 = f.read()
            ex = EXPORT_RE.search(src2)
            loc = dict((b, a) for a, b in _pairs(ex.group(1))).get(found[0]) if ex else None
            if not loc:
                lines.append(f"{found[1]}: export {found[0]} が見つからない")
                break
            lines.append(f"{os.path.basename(cur)}: export {found[0]} = local {loc}")
            ident = loc
            d = definition(src2, loc)
            if d:
                lines.append(f"  定義: {d.replace(chr(10), ' ')}")
                break
            continue  # 定義が無い = さらに別 chunk からの re-export
        d = definition(src, ident)
        lines.append(f"{os.path.basename(fp)}: {ident} " + (f"の定義: {d}" if d else "の定義が見つからない"))
        break
    return lines


def cmd_resolve(args) -> int:
    for line in resolve(paths(args.app)["assets"], args.chunk, args.name):
        print(line)
    return 0


def cmd_asar_ls(args) -> int:
    asar = paths(args.app)["asar"]
    header, _ = asar_read_header(asar)
    rows = [(n, node.get("size", 0)) for n, node in asar_files(header) if args.filter in n]
    for n, s in rows:
        print(f"{s}\t{n}")
    return 0 if rows else 1


def cmd_version(args) -> int:
    try:
        v = subprocess.run(["defaults", "read", paths(args.app)["info"].rsplit(".plist", 1)[0], "CFBundleShortVersionString"],
                           capture_output=True, text=True).stdout.strip()
    except Exception:
        v = ""
    ep = engine_path(args.engine)
    label = (ep.split("/claude-code/")[1].split("/")[0] if "/claude-code/" in ep else ep) if ep else "?"
    print(f"app\t{v or '?'}\nengine\t{label}")
    return 0


# ---- selftest ------------------------------------------------------------------------

def selftest() -> int:
    fails = []

    def check(label, cond):
        print(("ok   " if cond else "FAIL ") + label)
        if not cond:
            fails.append(label)

    with tempfile.TemporaryDirectory() as t:
        app = os.path.join(t, "Claude.app")
        p = paths(app)
        os.makedirs(os.path.join(p["assets"], "v1"))
        os.makedirs(p["i18n"])
        with open(os.path.join(p["i18n"], "ja-JP.json"), "w", encoding="utf-8") as f:
            json.dump({"KEY1": "このファイルが見つかりませんでした", "KEY2": "別の文言"}, f, ensure_ascii=False)
        with open(os.path.join(p["i18n"], "en-US.json"), "w", encoding="utf-8") as f:
            json.dump({"KEY1": "Couldn't find this file"}, f)
        view = os.path.join(p["assets"], "v1", "view-AAA.js")
        lib = os.path.join(p["assets"], "v1", "lib-BBB.js")
        with open(view, "w") as f:
            f.write('import{Gt as Se,in as Ne}from"./lib-BBB.js";let z=R.workingDir,er=Se(t,h);' + "x" * 5000 + 'id:"KEY1"')
        with open(lib, "w") as f:
            f.write('function Aw(e,t){return e.startsWith("~/")?t+e.slice(1):e}function jw(e,t){return e===t}export{Aw as Gt,jw as in};')

        rows = i18n_lookup(p["i18n"], "見つかりません", "ja-JP")
        check("i18n: 文言から key と英語原文", rows == [("KEY1", "このファイルが見つかりませんでした", "Couldn't find this file")])

        a = argparse.Namespace(pattern="KEY1", where="renderer", app=app, engine=None, context=20, per_file=5, max=10)
        hits = [(n, m.start()) for n, buf in grep_sources("renderer", app, None) for m in re.finditer(rb"KEY1", buf)]
        check("grep: minified の長い行でも位置を返す", hits and hits[0][0] == os.path.join("v1", "view-AAA.js"))
        check("grep: 見つからなければ exit 1", cmd_grep(argparse.Namespace(**{**vars(a), "pattern": "NOPE"})) == 1)

        lines = resolve(p["assets"], "view-AAA.js", "Se")
        check("resolve: import の付け替えを辿る", any("Se = import Gt from ./lib-BBB.js" in l for l in lines))
        check("resolve: export を local 名に戻して定義まで", any("function Aw(" in l for l in lines))

        asar = p["asar"]
        asar_write(asar, {"main.js": b"workingDir:u,originCwd:f", "readme.txt": b"x"})
        header, base = asar_read_header(asar)
        files = dict(asar_files(header))
        check("asar: header の file 一覧", set(files) == {"/main.js", "/readme.txt"})
        check("asar: 中身を offset から読む", asar_read(asar, files["/main.js"], base) == b"workingDir:u,originCwd:f")
        got = [n for n, buf in grep_sources("asar", app, None) if re.search(rb"originCwd", buf)]
        check("grep --where asar: main process の js を探す", got == ["app.asar:/main.js"])

        eng = os.path.join(t, "claude")
        with open(eng, "wb") as f:
            f.write(b"\0" * 100 + b'var _fn={cli:!0,"claude-desktop":!0}')
        got = [n for n, buf in grep_sources("engine", app, eng) if re.search(rb"claude-desktop", buf)]
        check("grep --where engine: binary を mmap で探す", len(got) == 1)

    print("ALL PASS" if not fails else f"{len(fails)} FAIL")
    return 1 if fails else 0


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["--selftest"]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--app", default=DEFAULT_APP)
    ap.add_argument("--engine", default=None, help="engine binary の path (既定 = 最新版を探す)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("version")
    s.set_defaults(fn=cmd_version)
    s = sub.add_parser("i18n")
    s.add_argument("text")
    s.add_argument("--locale", default="ja-JP")
    s.set_defaults(fn=cmd_i18n)
    s = sub.add_parser("grep")
    s.add_argument("pattern", help="python の正規表現 (bytes として当てる)")
    s.add_argument("--where", choices=["renderer", "asar", "engine"], default="renderer")
    s.add_argument("--context", type=int, default=160)
    s.add_argument("--per-file", type=int, default=3)
    s.add_argument("--max", type=int, default=20)
    s.set_defaults(fn=cmd_grep)
    s = sub.add_parser("resolve")
    s.add_argument("chunk", help="chunk の file 名 (assets 以下を探す)")
    s.add_argument("name", help="その chunk の中の minified 名")
    s.set_defaults(fn=cmd_resolve)
    s = sub.add_parser("asar-ls")
    s.add_argument("filter", nargs="?", default="")
    s.set_defaults(fn=cmd_asar_ls)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
