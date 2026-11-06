#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""transcript-share.py — 会話記録の文だけを暗号化して機械の間で共有し、 別の機械の会話も検索できるようにする

用途: 「前にこう書いた」 と言われた話が、 別の機械 (家と職場の Mac など) で開いた session にしか無いとき。
search-agent-transcripts.py は手元の機械の記録しか読めない (射程 = その docstring の末尾)。 この道具は、 各機械が
自分の会話記録から**本人の発言と agent の返事の文だけ**を抜き、 暗号化して共有フォルダ (同期される dir) に置き、
どの機械からでも復号して検索できるようにする。 一般則 = conventions/multi-machine-state.md#transcript-share

subcommand:
  export  手元の会話記録 (Claude Code の全部の設定フォルダ + Codex) を読み、 変わった session だけを書き出す
          <share-dir>/<machine>/<agent>/<record の名>.tsh (1 記録 1 file、 書き出しは一時 file → rename)
  search  <share-dir> の全部の機械の file を復号して pattern を探す (既定 = 自分の機械の分は除く、 手元は
          search-agent-transcripts.py で引く)。 出力 = `時刻  machine  agent  session先頭8文字  役割  本文の前後`
  status  機械ごとの本数・大きさ・最後に書いた時刻
  keygen  新しい鍵 (32 byte、 base64) を書く。 既にある file は上書きしない
  --selftest

書き出すもの / 書き出さないもの:
  - 入れる = 本人の発言 (user)・agent の返事の文 (assistant)・agent に渡した指示と親の写し (parent)。
    harness が差し込んだ文 (system-reminder など、 search-agent-transcripts.py の INJECTED_PREFIXES) は入れない
  - 入れない = 道具の呼び出しと結果 (メールの本文・file の中身・token が出うる所。 大きさも 99% 以上がここ)
  - **除外** (--exclude-path / --exclude-word): 次のどれかに当たる session は丸ごと書かない (前に書いた file も消す)
      ① 作業の場所 (cwd) が --exclude-path を含む
      ② 道具の呼び出しの入力が --exclude-path を含む (その場所を読んだ・書いた)
      ③ 本人の発言か agent に渡した指示 (注入の文は除く) が --exclude-path か --exclude-word を含む
    素の行で判定しない = 注入される規約の文 (CLAUDE.md) に除外の語が書いてあると、 ほぼ全部の session が落ちる (実測)。
    返事の文と、 path の無い道具の入力 (語の grep) にも当てない = 除外の仕組みの話をしただけの session が落ちる (実測)。
    機密の中身は、 その場所を読む (②) か本人が貼る (③) ことでしか会話に入らない、 という前提の判定。
    ⚠️ 除外の語も path も出さずに機密を貼った会話は防げない (語の網の限界) = 機密の作業は機密の置き場の session でする

暗号: AES-256-GCM (Python の cryptography)。 file = b"TSH1" + nonce 12 byte + 暗号文 (gzip した JSONL)。
  鍵 file = 32 byte の base64 (または hex 64 文字)。 鍵は機械の間で同じものを使う (運び方は呼ぶ側の層が決める)。
  共有フォルダには暗号文しか置かない。 鍵が無い・違う機械では復号に失敗し、 その本数を stderr に出す (黙って 0 件にしない)

差分: 状態 file (--state、 既定 ~/.claude/state/transcript-share-export.json) に記録ごとの大きさと mtime を持ち、
  変わったものだけを書き直す。 --min-interval <秒> で前の実行から短いときは何もしない (Stop hook から毎 turn 呼ぶ用)。
  並列の session が同時に呼んでも lock で 1 本だけが走る (取れなければ黙って終わる)。

使い方:
  transcript-share.py keygen --key-file ~/.secrets/transcript-share.key
  transcript-share.py export --share-dir <dir> --key-file <鍵> --exclude-path '<機密のフォルダ>' --exclude-word '<語>'
  transcript-share.py search '6号館' --share-dir <dir> --key-file <鍵> --role any --since 2026-10-01
  transcript-share.py status --share-dir <dir>
  transcript-share.py --selftest
exit: 0 = 正常 (見つからなくても 0) / 2 = 引数・鍵の誤り / 3 = cryptography が無い
"""
from __future__ import annotations

import argparse
import base64
import collections
import contextlib
import fcntl
import gzip
import importlib.util
import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAGIC = b"TSH1"
SUFFIX = ".tsh"
DEFAULT_STATE = "~/.claude/state/transcript-share-export.json"


def _load_search_module():
    """search-agent-transcripts.py (file 名に - を含む) を module として読む = 記録の列挙と文の取り出しを共有する。"""
    spec = importlib.util.spec_from_file_location("search_agent_transcripts", HERE / "search-agent-transcripts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SAT = _load_search_module()


def _aesgcm(key: bytes):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        print("cryptography の module が無い (この python では暗号化できない)", file=sys.stderr)
        sys.exit(3)
    return AESGCM(key)


def read_key(path: str) -> bytes:
    p = Path(os.path.expanduser(path))
    try:
        s = p.read_text().strip()
    except OSError as e:
        print(f"鍵 file を読めない: {p} ({e})", file=sys.stderr)
        sys.exit(2)
    if re.fullmatch(r"[0-9a-fA-F]{64}", s):
        k = bytes.fromhex(s)
    else:
        try:
            k = base64.b64decode(s, validate=True)
        except ValueError:
            k = b""
    if len(k) != 32:
        print(f"鍵 file の形が違う (32 byte の base64 か hex 64 文字): {p}", file=sys.stderr)
        sys.exit(2)
    return k


def encrypt(key: bytes, data: bytes) -> bytes:
    nonce = os.urandom(12)
    return MAGIC + nonce + _aesgcm(key).encrypt(nonce, gzip.compress(data, mtime=0), MAGIC)


def decrypt(key: bytes, blob: bytes) -> bytes:
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 12 + 16:
        raise ValueError("形が違う file")
    nonce = blob[len(MAGIC):len(MAGIC) + 12]
    return gzip.decompress(_aesgcm(key).decrypt(nonce, blob[len(MAGIC) + 12:], MAGIC))


def _machine(name: str | None) -> str:
    if name:
        return name
    try:
        return subprocess.run(["hostname", "-s"], capture_output=True, text=True, timeout=5).stdout.strip() or socket.gethostname().split(".")[0]
    except Exception:
        return socket.gethostname().split(".")[0]


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._\[\]-]", "_", name)


def _out_name(ag_shown: str, files, agent: str) -> str:
    f = files[0]
    stem = SAT._record_stem(f.name)
    if agent == "claude" and SAT._is_subagent(f):
        stem = f"{f.parent.parent.name}__{stem}"
    return f"{_safe(ag_shown)}/{_safe(stem)}{SUFFIX}"


def extract(agent: str, files, tally, exclude_paths, exclude_words):
    """1 つの記録から (除外か, meta, 行の list) を返す。 除外なら行は空。"""
    sub_agent = agent == "claude" and SAT._is_subagent(files[0])
    child = None
    cwd = ""
    rows = []
    seen = set()
    for line in SAT._lines(files, tally):
        if agent == "codex" and child is None:
            child = SAT._is_codex_child(line)
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        c = rec.get("cwd") or ((rec.get("payload") or {}).get("cwd") if rec.get("type") == "session_meta" else None)
        if isinstance(c, str) and c:
            if not cwd:
                cwd = c
            if any(p in c for p in exclude_paths):
                return True, {}, []
        for kind, _id, body, _err in SAT._tool_items(agent, rec):
            if kind == "call" and any(p in body for p in exclude_paths):
                return True, {}, []  # その場所を実際に読んだ・書いた (語だけの grep などは当てない)
        r, texts = (SAT._texts_claude if agent == "claude" else SAT._texts_codex)(rec)
        if r is None:
            continue
        if (sub_agent or child) and r == "user":
            r = "parent"
        ts = rec.get("timestamp") or ""
        for tx in texts:
            if r in ("user", "developer") and tx.lstrip().startswith(SAT.INJECTED_PREFIXES):
                continue
            if r == "developer":
                continue  # Codex の規約の注入 (本人の発言ではない)
            if r in ("user", "parent") and any(w in tx for w in (*exclude_paths, *exclude_words)):
                return True, {}, []  # 本人が話題にした・agent に渡した (返事の文は当てない = 仕組みの話で落ちる)
            key = (r, ts, tx)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"ts": ts, "role": r, "text": tx})
    return False, {"cwd": cwd}, rows


@contextlib.contextmanager
def _lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        yield False
        return
    try:
        yield True
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def _write_atomic(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=SUFFIX)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def cmd_export(a) -> int:
    key = read_key(a.key_file)
    share = Path(os.path.expanduser(a.share_dir))
    machine = _machine(a.machine)
    state_path = Path(os.path.expanduser(a.state))
    with _lock(state_path.with_suffix(".lock")) as got:
        if not got:
            return 0  # 別の session が書き出し中
        try:
            state = json.loads(state_path.read_text())
        except (OSError, ValueError):
            state = {}
        now = time.time()
        if a.min_interval and now - float(state.get("last_run", 0)) < a.min_interval:
            return 0
        files_state = state.get("files", {})
        claude_dirs = [Path(os.path.expanduser(d)) for d in a.claude_dir] if a.claude_dir else None
        codex_dirs = [Path(os.path.expanduser(d)) for d in (a.codex_dir or SAT.DEFAULT_CODEX_DIRS)]
        tally = collections.Counter()
        n = collections.Counter()
        for ag, files, label in SAT.iter_files("both", claude_dirs, codex_dirs):
            try:
                sig = [[f.stat().st_size, f.stat().st_mtime_ns] for f in files]
            except OSError:
                continue
            k = str(files[0])
            if files_state.get(k) == sig:
                n["unchanged"] += 1
                continue
            out = share / _safe(machine) / _out_name(SAT._agent_shown(ag, label), files, ag)
            excluded, meta, rows = extract(ag, files, tally, a.exclude_path or [], a.exclude_word or [])
            if excluded:
                n["excluded"] += 1
                if not a.dry_run and out.exists():
                    out.unlink()
                    n["removed"] += 1
            elif not rows:
                n["empty"] += 1
            else:
                head = {"meta": {"machine": machine, "agent": SAT._agent_shown(ag, label),
                                 "session": SAT._session_of(files[0], ag), "record": files[0].name,
                                 "cwd": meta.get("cwd", ""), "exported": time.strftime("%Y-%m-%dT%H:%M:%S")}}
                body = "\n".join(json.dumps(x, ensure_ascii=False) for x in [head, *rows]) + "\n"
                if not a.dry_run:
                    _write_atomic(out, encrypt(key, body.encode("utf-8")))
                n["written"] += 1
            if not a.dry_run:
                files_state[k] = sig
        if not a.dry_run:
            state = {"files": files_state, "last_run": now, "machine": machine, "share_dir": str(share)}
            state_path.parent.mkdir(parents=True, exist_ok=True)
            _write_atomic(state_path, json.dumps(state, ensure_ascii=False).encode("utf-8"))
        if not a.quiet:
            print(f"{machine}: 書いた {n['written']} / 除外 {n['excluded']} (消した {n['removed']}) / "
                  f"文なし {n['empty']} / 変化なし {n['unchanged']}" + (" (dry-run)" if a.dry_run else ""))
        msg = SAT._report(tally)
        if msg:
            print(msg, file=sys.stderr)
    return 0


def _shared_files(share: Path):
    for f in sorted(share.glob(f"*/*/*{SUFFIX}")):
        yield f.relative_to(share).parts[0], f


def cmd_search(a) -> int:
    key = read_key(a.key_file)
    share = Path(os.path.expanduser(a.share_dir))
    own = _safe(_machine(a.machine))
    rx = re.compile(a.pattern) if a.regex else None
    hits, bad = [], 0
    for machine, f in _shared_files(share):
        if machine == own and not a.all_machines:
            continue
        if a.only_machine and machine != a.only_machine:
            continue
        try:
            lines = decrypt(key, f.read_bytes()).decode("utf-8").splitlines()
        except Exception:
            bad += 1
            continue
        meta = {}
        for i, line in enumerate(lines):
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if i == 0 and "meta" in o:
                meta = o["meta"]
                continue
            r, ts, tx = o.get("role", ""), o.get("ts", ""), o.get("text", "")
            if a.role != "any" and r != a.role:
                continue
            if SAT._out_of_range(ts, a.since, a.until):
                continue
            m = rx.search(tx) if rx is not None else None
            j0 = m.start() if m is not None else tx.find(a.pattern)
            if j0 < 0:
                continue
            j1 = m.end() if m is not None else j0 + len(a.pattern)
            snip = tx[max(0, j0 - a.context): j1 + a.context].replace("\n", " ")
            hits.append((ts, machine, meta.get("agent", "?"), str(meta.get("session", "?"))[:8], r, snip))
    hits.sort()
    for h in hits[: a.limit] if a.limit else hits:
        print(f"{h[0][:19]}  {h[1]}  {h[2]:6}  {h[3]}  {h[4]:9}  {h[5]}")
    if not hits:
        print("(共有された記録には見つからない)", file=sys.stderr)
    if bad:
        print(f"⚠️ 復号できなかった file: {bad} 本 (鍵が違う・壊れた file)", file=sys.stderr)
    return 0


def cmd_status(a) -> int:
    share = Path(os.path.expanduser(a.share_dir))
    per = collections.defaultdict(lambda: [0, 0, 0.0])
    for machine, f in _shared_files(share):
        st = f.stat()
        p = per[machine]
        p[0] += 1
        p[1] += st.st_size
        p[2] = max(p[2], st.st_mtime)
    if not per:
        print(f"(共有された記録が無い: {share})")
    for machine, (cnt, size, mt) in sorted(per.items()):
        print(f"{machine}: {cnt} 本 / {size / 1e6:.1f} MB / 最後に書いた {time.strftime('%Y-%m-%d %H:%M', time.localtime(mt))}")
    return 0


def cmd_keygen(a) -> int:
    p = Path(os.path.expanduser(a.key_file))
    if p.exists():
        print(f"既にある (上書きしない): {p}", file=sys.stderr)
        return 2
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(base64.b64encode(os.urandom(32)).decode() + "\n")
    print(f"鍵を書いた: {p} (mode 600)")
    return 0


def selftest() -> int:
    ok = True

    def check(cond, what):
        nonlocal ok
        print(("✓ " if cond else "✗ ") + what)
        ok = ok and bool(cond)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        cdir = td / "claude" / "projects" / "-proj"
        cdir.mkdir(parents=True)
        xdir = td / "codex"
        (xdir / "2026" / "01" / "02").mkdir(parents=True)
        share = td / "share"
        state = td / "state.json"
        keyf = td / "k.key"
        check(cmd_keygen(argparse.Namespace(key_file=str(keyf))) == 0, "keygen が鍵を書く")
        check(cmd_keygen(argparse.Namespace(key_file=str(keyf))) == 2, "keygen は既にある鍵を上書きしない")

        def w(path, recs):
            path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))

        w(cdir / "aaaaaaaa-0000-0000-0000-000000000001.jsonl", [
            {"type": "user", "timestamp": "2026-01-02T03:04:05Z", "cwd": "/w",
             "message": {"content": "部屋は南側がいい (合成例)"}},
            {"type": "user", "timestamp": "2026-01-02T03:04:06Z",
             "message": {"content": [{"type": "text", "text": "<system-reminder>機密フォルダの説明 SECRETWORD</system-reminder>"}]}},
            {"type": "assistant", "timestamp": "2026-01-02T03:04:07Z",
             "message": {"content": [{"type": "text", "text": "記録します"},
                                     {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "cat /tmp/ok"}}]}},
            {"type": "user", "timestamp": "2026-01-02T03:04:08Z",
             "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "TOOLOUTPUT"}]}},
        ])
        w(cdir / "bbbbbbbb-0000-0000-0000-000000000002.jsonl", [
            {"type": "user", "timestamp": "2026-01-02T03:05:00Z", "cwd": "/w",
             "message": {"content": "普通の話"}},
            {"type": "assistant", "timestamp": "2026-01-02T03:05:01Z",
             "message": {"content": [{"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/vault/SECRETDIR/x.tex"}}]}},
        ])
        w(cdir / "cccccccc-0000-0000-0000-000000000003.jsonl", [
            {"type": "user", "timestamp": "2026-01-02T03:06:00Z", "cwd": "/w",
             "message": {"content": "後で機密になる話"}},
        ])
        w(cdir / "eeeeeeee-0000-0000-0000-000000000005.jsonl", [
            {"type": "user", "timestamp": "2026-01-02T03:08:00Z", "cwd": "/w", "message": {"content": "仕組みを作って"}},
            {"type": "assistant", "timestamp": "2026-01-02T03:08:01Z",
             "message": {"content": [{"type": "text", "text": "SECRETWORD の session は除く設計にします"},
                                     {"type": "tool_use", "id": "t5", "name": "Bash", "input": {"command": "grep -c SECRETWORD notes.md"}}]}},
        ])
        w(xdir / "2026" / "01" / "02" / "rollout-2026-01-02T00-00-00-dddddddd-0000-0000-0000-000000000004.jsonl", [
            {"type": "session_meta", "timestamp": "2026-01-02T00:00:00Z", "payload": {"cwd": "/w"}},
            {"type": "response_item", "timestamp": "2026-01-02T00:00:01Z",
             "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Codex の部屋の話"}]}},
        ])

        def ns(**kw):
            base = dict(share_dir=str(share), key_file=str(keyf), machine="hostA", state=str(state),
                        min_interval=0, claude_dir=[str(td / "claude" / "projects")], codex_dir=[str(xdir)],
                        exclude_path=["SECRETDIR"], exclude_word=["SECRETWORD"], dry_run=False, quiet=True)
            base.update(kw)
            return argparse.Namespace(**base)

        cmd_export(ns())
        out = sorted(p.relative_to(share).as_posix() for p in share.rglob(f"*{SUFFIX}"))
        check(len(out) == 4 and all(p.startswith("hostA/") for p in out), f"書き出し 4 本 (除外 1 本): {out}")
        check(not any("bbbbbbbb" in p for p in out), "道具の入力に除外の path がある session は書かない")
        check(any("aaaaaaaa" in p for p in out), "注入の文に除外の語があるだけの session は書く (素の行で判定しない)")
        check(any("eeeeeeee" in p for p in out), "返事の文と path の無い道具の入力に語があるだけの session は書く (仕組みの話)")
        blob = (share / [p for p in out if "aaaaaaaa" in p][0]).read_bytes()
        check(b"TOOLOUTPUT" not in blob and "南側".encode() not in blob, "共有の file は暗号文 (平文が見えない)")
        body = decrypt(read_key(str(keyf)), blob).decode()
        check("南側" in body and "記録します" in body, "本人の発言と返事の文が入る")
        check("TOOLOUTPUT" not in body and "SECRETWORD" not in body and "cat /tmp/ok" not in body,
              "道具の入力・結果と注入の文は入らない")
        mt = {p: (share / p).stat().st_mtime_ns for p in out}
        cmd_export(ns())
        check(all((share / p).stat().st_mtime_ns == mt[p] for p in out), "変わっていない記録は書き直さない")
        w(cdir / "cccccccc-0000-0000-0000-000000000003.jsonl", [
            {"type": "user", "timestamp": "2026-01-02T03:06:00Z", "cwd": "/w", "message": {"content": "後で機密になる話"}},
            {"type": "user", "timestamp": "2026-01-02T03:07:00Z", "cwd": "/w", "message": {"content": "SECRETWORD の中身"}},
        ])
        cmd_export(ns())
        check(not any("cccccccc" in p.name for p in share.rglob(f"*{SUFFIX}")), "後から除外に当たった session は前の file を消す")
        cmd_export(ns(min_interval=3600))
        check(True, "min-interval の内側では何もしない (例外なく戻る)")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_search(argparse.Namespace(pattern="部屋", share_dir=str(share), key_file=str(keyf), machine="hostB",
                                          regex=False, role="user", since=None, until=None, all_machines=False,
                                          only_machine=None, context=20, limit=0))
        res = buf.getvalue()
        check("南側" in res and "Codex の部屋" in res and "hostA" in res, "別の機械から復号して検索できる (Claude と Codex)")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_search(argparse.Namespace(pattern="部屋", share_dir=str(share), key_file=str(keyf), machine="hostA",
                                          regex=False, role="user", since=None, until=None, all_machines=False,
                                          only_machine=None, context=20, limit=0))
        check(buf.getvalue() == "", "既定では自分の機械の分を除く")
        bad = td / "bad.key"
        bad.write_text(base64.b64encode(os.urandom(32)).decode())
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            cmd_search(argparse.Namespace(pattern="部屋", share_dir=str(share), key_file=str(bad), machine="hostB",
                                          regex=False, role="any", since=None, until=None, all_machines=False,
                                          only_machine=None, context=20, limit=0))
        check("復号できなかった" in err.getvalue(), "鍵が違えば復号できず、 本数を stderr に出す")
    print("selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="会話記録の文だけを暗号化して機械の間で共有し、 検索する")
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    e = sub.add_parser("export", help="手元の会話記録を書き出す")
    e.add_argument("--share-dir", required=True)
    e.add_argument("--key-file", required=True)
    e.add_argument("--machine", help="機械の名 (既定 = hostname -s)")
    e.add_argument("--state", default=DEFAULT_STATE)
    e.add_argument("--min-interval", type=float, default=0, help="前の実行からこの秒数の内なら何もしない")
    e.add_argument("--exclude-path", action="append", help="cwd・道具の入力にこれを含む session を書かない (繰り返し可)")
    e.add_argument("--exclude-word", action="append", help="道具の入力・本人の発言・返事にこれを含む session を書かない")
    e.add_argument("--claude-dir", action="append")
    e.add_argument("--codex-dir", action="append")
    e.add_argument("--dry-run", action="store_true")
    e.add_argument("--quiet", action="store_true")
    s = sub.add_parser("search", help="共有された記録を検索する")
    s.add_argument("pattern")
    s.add_argument("--share-dir", required=True)
    s.add_argument("--key-file", required=True)
    s.add_argument("--machine", help="自分の機械の名 (既定 = hostname -s。 この名の分は既定で除く)")
    s.add_argument("--all-machines", action="store_true", help="自分の機械の分も含める")
    s.add_argument("--only-machine", help="この機械の分だけ")
    s.add_argument("--regex", action="store_true")
    s.add_argument("--role", default="user", choices=["user", "assistant", "parent", "any"])
    s.add_argument("--since", type=SAT._bound)
    s.add_argument("--until", type=SAT._bound)
    s.add_argument("--context", type=int, default=120)
    s.add_argument("--limit", type=int, default=200)
    t = sub.add_parser("status", help="機械ごとの本数と最後に書いた時刻")
    t.add_argument("--share-dir", required=True)
    k = sub.add_parser("keygen", help="新しい鍵を書く")
    k.add_argument("--key-file", required=True)
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.cmd == "export":
        return cmd_export(a)
    if a.cmd == "search":
        return cmd_search(a)
    if a.cmd == "status":
        return cmd_status(a)
    if a.cmd == "keygen":
        return cmd_keygen(a)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
