#!/usr/bin/env python3
"""claude-app-bundle.py — Claude desktop app の挙動を、 docs や推測でなく app 本体 (画面の JS bundle・翻訳・main process の app.asar・埋込 engine) から確かめる検索道具

使い方 (手順と落とし穴 = conventions/claude-app-bundle-reading.md):
  claude-app-bundle.py version                          app と埋込 engine の版 (読んだ版を記録に残す)
  claude-app-bundle.py i18n "見つかりませんでした"        画面の文言 → 翻訳 key と英語原文
  claude-app-bundle.py grep FRHpsQyd2G                    key や語を画面の bundle から探す (--where asar|engine も可)
  claude-app-bundle.py resolve cd2efac6e-DdNhqOhn.js Se   minified 名がどの chunk のどの関数かを辿る
  claude-app-bundle.py asar-ls index.chunk                app.asar の中の file 一覧 (部分一致で絞る)
  claude-app-bundle.py slice index.chunk-X.js --where asar --find "async someFunction(" --len 3000
                                                          関数を丸ごと読む (grep が出した位置からなら --at <offset>)
  claude-app-bundle.py --selftest

なぜ grep でなく本 script か: bundle は 1 行が MB 級の minified JS で、 `grep -o '.{0,80}X.{0,200}'` は
時間切れになる (実測)。 python の re で bytes を読み、 前後だけ切り出す。 app.asar は独自形式で、 中の
main process の file は展開しないと読めない。

画面側 (renderer の JS と翻訳) の置き場所は版で違う: 旧い版 = Resources/ion-dist/ の dir、 新しい版 = Resources/ion-dist.asar
(実測、 app 4.4212.0)。 さらに新しい版は両方を持ち、 dir の中は index.html だけ (実測、 app 5.1231.2)。 だから dir は
assets/ に JS があるときだけ使い、 そうでなく asar があれば、 i18n・grep (renderer)・slice (renderer)・resolve の初回に
~/Library/Caches/claude-app-bundle/ (env CLAUDE_APP_BUNDLE_CACHE で変更) へ 1 回展開して使う (asar の大きさと mtime が
変われば作り直し、 古い展開は消す)。 version・asar-ls・--where asar|engine は展開しない。 grep は読んだ source の本数を
stderr に出し、 0 本なら exit 2 (exit 1 = 読んだが当たり 0)。 i18n は翻訳の file が無ければ exit 2。
"""
from __future__ import annotations

import argparse
import glob
import json
import mmap
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile

DEFAULT_APP = "/Applications/Claude.app"
CACHE_ROOT = "~/Library/Caches/claude-app-bundle"
ENGINE_ROOT = "~/Library/Application Support/Claude/claude-code"
# 版の dir の直下 (旧) と、 版の下に hash の dir を 1 段挟む形 (claude-code/<版>/<hash>/claude.app、 実測 2.1.29x) の両方
ENGINE_GLOBS = ("*/claude.app/Contents/MacOS/claude", "*/*/claude.app/Contents/MacOS/claude")


def paths(app: str) -> dict:
    res = os.path.join(app, "Contents", "Resources")
    return {
        "assets": os.path.join(res, "ion-dist", "assets"),
        "i18n": os.path.join(res, "ion-dist", "i18n"),
        "asar": os.path.join(res, "app.asar"),
        "info": os.path.join(app, "Contents", "Info.plist"),
    }


def engine_path(explicit: str | None = None, root: str | None = None) -> str | None:
    if explicit:
        return explicit
    base = os.path.expanduser(root or ENGINE_ROOT)
    cands = [p for g in ENGINE_GLOBS for p in glob.glob(os.path.join(glob.escape(base), g))]

    def key(p):
        v = os.path.relpath(p, base).split(os.sep)[0]
        try:
            mtime = os.path.getmtime(p)
        except OSError:
            mtime = 0.0
        return ([int(x) if x.isdigit() else 0 for x in re.split(r"[.-]", v)], mtime)

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


def _has_js(assets: str) -> bool:
    """assets の下に .js が 1 本でもあるか (最初の 1 本で止める)。"""
    for _root, _dirs, names in os.walk(assets):
        if any(n.endswith(".js") for n in names):
            return True
    return False


def renderer_dirs(app: str, cache_root: str | None = None) -> dict:
    """画面側の {"assets": …, "i18n": …}。 Resources/ion-dist/assets に JS があればその dir、 無くて ion-dist.asar が在れば
    cache に展開した dir (冒頭の説明)。 どちらも無ければ dir の path をそのまま返す (呼ぶ側が「無い」 を出す)。
    実測 (app 5.1231.2): dir (中は index.html だけ) と asar の両方があり、 dir を選んで JS を 0 本読み、 grep が空振りした。"""
    p = paths(app)
    base = os.path.dirname(p["assets"])
    if not _has_js(os.path.join(base, "assets")) and os.path.isfile(base + ".asar"):
        base = ion_dist_extracted(base + ".asar", cache_root)
    return {"assets": os.path.join(base, "assets"), "i18n": os.path.join(base, "i18n")}


def ion_dist_extracted(asar: str, cache_root: str | None = None) -> str:
    st = os.stat(asar)
    root = os.path.expanduser(cache_root or os.environ.get("CLAUDE_APP_BUNDLE_CACHE") or CACHE_ROOT)
    out = os.path.join(root, f"ion-dist-{st.st_size}-{int(st.st_mtime)}")
    if os.path.exists(os.path.join(out, ".complete")):
        return out
    for old in glob.glob(os.path.join(glob.escape(root), "ion-dist-*")):
        if old != out:
            shutil.rmtree(old, ignore_errors=True)
    print(f"ion-dist.asar を展開する ({st.st_size // 1_000_000} MB、 初回だけ): {out}", file=sys.stderr)
    header, base = asar_read_header(asar)
    for name, node in asar_files(header):
        if "offset" not in node:  # symlink の node など
            continue
        data = asar_read(asar, node, base)
        if data is None:
            continue
        fp = os.path.join(out, name.lstrip("/"))
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "wb") as f:
            f.write(data)
    open(os.path.join(out, ".complete"), "w").close()
    return out


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
        assets = renderer_dirs(app)["assets"]
        for fp in sorted(glob.glob(os.path.join(assets, "**", "*.js"), recursive=True)):
            with open(fp, "rb") as f:
                yield os.path.relpath(fp, assets), f.read()
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


def cmd_slice(args) -> int:
    """名前が一致する source 1 本から、 位置 (--at) か語 (--find、 --nth 番目) 以降を --len bytes 切り出す。
    grep は前後の数百 bytes しか出さないので、 関数を丸ごと読むときはこちら。"""
    hits = [(n, b) for n, b in grep_sources(args.where, args.app, args.engine)
            if args.where == "engine" or n.endswith(args.name)]
    if len(hits) != 1:
        print(f"source が 1 本に定まらない ({len(hits)} 本): {args.name}", file=sys.stderr)
        return 2
    name, buf = hits[0]
    start = args.at
    if args.find is not None:
        start = -1
        for _ in range(args.nth + 1):
            start = buf.find(args.find.encode(), start + 1)
            if start < 0:
                print(f"見つからない: {args.find!r} ({name})", file=sys.stderr)
                return 1
    if start is None:
        print("--at か --find のどちらかを指定する", file=sys.stderr)
        return 2
    print(f"{name}:{start}")
    print(bytes(buf[start:start + args.len]).decode("utf-8", "replace"))
    return 0


def cmd_grep(args) -> int:
    try:
        rx = re.compile(args.pattern.encode())
    except re.error as e:
        print(f"正規表現が不正: {e} (括弧などの記号そのものを探すなら \\ で escape する)", file=sys.stderr)
        return 2
    n = srcs = 0
    for name, buf in grep_sources(args.where, args.app, args.engine):
        srcs += 1
        per = 0
        for m in rx.finditer(buf):
            print(f"{name}:{m.start()}: {snippet(buf, m.start(), m.end(), args.context)}")
            n += 1
            per += 1
            if per >= args.per_file or n >= args.max:
                break
        if n >= args.max:
            break
    place = source_place(args.where, args.app, args.engine)
    if not srcs:
        # 「当たり 0」 (exit 1) と分ける。 実測: JS の無い dir を探して 0 本読み、 出力 0 行・exit 1 で「無い」 に見えた
        print(f"読む source が 0 本 ({place}) = 「見つからない」 ではない。 置き場所を確かめる (冒頭の説明)", file=sys.stderr)
        return 2
    print(f"-- source {srcs} 本を読んだ ({place})", file=sys.stderr)
    return 0 if n else 1


def source_place(where: str, app: str, engine: str | None) -> str:
    """grep / slice が読む場所 (読んだ本数の報告と、 0 本のときの知らせに出す)。"""
    if where == "renderer":
        return renderer_dirs(app)["assets"]
    if where == "asar":
        return paths(app)["asar"]
    return engine_path(engine) or "埋込 engine が見つからない"


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
    i18n = renderer_dirs(args.app)["i18n"]
    if not os.path.isfile(os.path.join(i18n, f"{args.locale}.json")):
        print(f"翻訳の file が無い ({os.path.join(i18n, args.locale + '.json')}) = 「見つからない」 ではない。 置き場所か locale を確かめる",
              file=sys.stderr)
        return 2
    rows = i18n_lookup(i18n, args.text, args.locale)
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
    lines = resolve(renderer_dirs(args.app)["assets"], args.chunk, args.name)
    for line in lines:
        print(line)
    return 1 if not lines or "見つからない" in lines[-1] else 0


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

        root = os.path.join(t, "claude-code")
        for rel in ("2.1.100/claude.app", "2.1.295/aaa/claude.app", "2.1.299/bbb/claude.app"):
            d = os.path.join(root, rel, "Contents", "MacOS")
            os.makedirs(d)
            open(os.path.join(d, "claude"), "wb").close()
        check("engine の既定: 版の下に hash の dir を挟む形も探し、 いちばん新しい版を選ぶ",
              engine_path(None, root) == os.path.join(root, "2.1.299", "bbb", "claude.app", "Contents", "MacOS", "claude"))
        old = os.path.join(t, "claude-code-old")
        os.makedirs(os.path.join(old, "2.1.100", "claude.app", "Contents", "MacOS"))
        open(os.path.join(old, "2.1.100", "claude.app", "Contents", "MacOS", "claude"), "wb").close()
        check("engine の既定: 旧い形 (版の直下) だけでも見つける",
              engine_path(None, old) == os.path.join(old, "2.1.100", "claude.app", "Contents", "MacOS", "claude"))
        check("engine の既定: 無ければ None", engine_path(None, os.path.join(t, "nope")) is None)

        import contextlib
        import io
        ns = dict(app=app, engine=None, where="asar", name="main.js", at=None, find="originCwd", nth=0, len=12)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cmd_slice(argparse.Namespace(**ns))
        check("slice: app.asar の中の file を語の位置から切り出す", rc == 0 and out.getvalue().endswith("originCwd:f\n"))
        with contextlib.redirect_stderr(io.StringIO()):
            check("slice: 語が無ければ exit 1", cmd_slice(argparse.Namespace(**{**ns, "find": "NOPE"})) == 1)
            check("grep: 不正な正規表現は traceback でなく exit 2",
                  cmd_grep(argparse.Namespace(**{**vars(a), "pattern": "("})) == 2)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cmd_resolve(argparse.Namespace(app=app, chunk="nope.js", name="Se"))
        check("resolve: 見つからなければ exit 1", rc == 1)

        # 新しい配置: 画面側が Resources/ion-dist.asar に入っている (dir は無い)
        app2 = os.path.join(t, "Claude2.app")
        res2 = os.path.join(app2, "Contents", "Resources")
        os.makedirs(res2)
        asar2 = os.path.join(res2, "ion-dist.asar")
        asar_write(asar2, {
            "i18n/ja-JP.json": json.dumps({"KEY9": "このファイルはこのセッションのフォルダの外にあります"}, ensure_ascii=False).encode(),
            "i18n/en-US.json": json.dumps({"KEY9": "This file is outside this session's folders"}).encode(),
            "assets/v1/view-CCC.js": b'import{Gt as Se}from"./lib-DDD.js";' + b"y" * 3000 + b'id:"KEY9"',
            "assets/v1/lib-DDD.js": b'function Bq(e){return e}export{Bq as Gt};',
        })
        cache = os.path.join(t, "cache")
        saved = os.environ.get("CLAUDE_APP_BUNDLE_CACHE")
        os.environ["CLAUDE_APP_BUNDLE_CACHE"] = cache
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                d1 = renderer_dirs(app2)
                rows = i18n_lookup(d1["i18n"], "フォルダの外", "ja-JP")
                check("ion-dist.asar: 展開して i18n を引く",
                      rows == [("KEY9", "このファイルはこのセッションのフォルダの外にあります", "This file is outside this session's folders")])
                hits = [n for n, buf in grep_sources("renderer", app2, None) if re.search(rb"KEY9", buf)]
                check("ion-dist.asar: grep --where renderer が展開した chunk を探す", hits == [os.path.join("v1", "view-CCC.js")])
                check("ion-dist.asar: resolve も展開した chunk を辿る",
                      any("function Bq(" in l for l in resolve(d1["assets"], "view-CCC.js", "Se")))
                first = os.path.dirname(d1["assets"])
                check("ion-dist.asar: 2 回目は展開し直さない (同じ dir)", os.path.dirname(renderer_dirs(app2)["assets"]) == first)
                os.utime(asar2, (1_700_000_000, 1_700_000_000))
                second = os.path.dirname(renderer_dirs(app2)["assets"])
                check("ion-dist.asar: asar が変われば作り直し、 古い展開を消す",
                      second != first and os.path.isdir(second) and not os.path.exists(first))
                # さらに新しい配置: dir (index.html だけ) と asar の両方 = dir を選ばず asar を展開する
                app3 = os.path.join(t, "Claude3.app")
                res3 = os.path.join(app3, "Contents", "Resources")
                os.makedirs(os.path.join(res3, "ion-dist"))
                with open(os.path.join(res3, "ion-dist", "index.html"), "w") as f:
                    f.write("<html></html>")
                shutil.copy(asar2, os.path.join(res3, "ion-dist.asar"))
                hits3 = [n for n, buf in grep_sources("renderer", app3, None) if re.search(rb"KEY9", buf)]
                check("ion-dist の dir が index.html だけなら asar を展開して探す", hits3 == [os.path.join("v1", "view-CCC.js")])
                g3 = argparse.Namespace(pattern="KEY9", where="renderer", app=app3, engine=None, context=5, per_file=5, max=10)
                with contextlib.redirect_stdout(io.StringIO()):
                    check("grep: 当たれば exit 0 (両方を持つ配置)", cmd_grep(g3) == 0)
                # 置き場所に何も無い = 読む source が 0 本: 「当たり 0」 (exit 1) と分けて exit 2
                app4 = os.path.join(t, "Claude4.app")
                os.makedirs(os.path.join(app4, "Contents", "Resources", "ion-dist"))
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    rc4 = cmd_grep(argparse.Namespace(**{**vars(g3), "app": app4}))
                    rc4i = cmd_i18n(argparse.Namespace(app=app4, text="x", locale="ja-JP"))
                check("grep: 読む source が 0 本なら exit 2 で理由を言う", rc4 == 2 and "source が 0 本" in err.getvalue())
                check("i18n: 翻訳の file が無ければ exit 2", rc4i == 2 and "翻訳の file が無い" in err.getvalue())
            check("ion-dist.asar: version・--where asar は展開しない (paths は dir の形のまま)",
                  paths(app2)["assets"] == os.path.join(res2, "ion-dist", "assets"))
        finally:
            if saved is None:
                os.environ.pop("CLAUDE_APP_BUNDLE_CACHE", None)
            else:
                os.environ["CLAUDE_APP_BUNDLE_CACHE"] = saved

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
    s = sub.add_parser("slice")
    s.add_argument("name", help="source の名前の末尾 (chunk の file 名 / app.asar の中の path)。 --where engine では無視")
    s.add_argument("--where", choices=["renderer", "asar", "engine"], default="renderer")
    s.add_argument("--at", type=int, default=None, help="grep が出した位置 (bytes)")
    s.add_argument("--find", default=None, help="この語が現れる位置から")
    s.add_argument("--nth", type=int, default=0, help="--find の何番目の出現か (0 始まり)")
    s.add_argument("--len", type=int, default=2000)
    s.set_defaults(fn=cmd_slice)
    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except FileNotFoundError as e:
        print(f"app の file が無い: {e.filename} (--app で Claude.app の場所を指定する)", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
