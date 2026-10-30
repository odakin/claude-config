#!/usr/bin/env python3
"""downloaded-file-scan.py — ネット由来の file (PDF・zip・Office・script など) を repo や作業 dir に取り込む前に、 来歴 (quarantine)・中身の種類・能動要素・埋め込み・署名 scan (ClamAV が在れば) を検査し、 取り込み先に残す記録の 1 行を出す。 --selftest 内蔵。 conventions/downloaded-file-scan.md#scan-before-import

使い方:
  downloaded-file-scan.py <file|dir> ...        # 検査の結果 + 記録の 1 行。 検査の記録を state に残す (hook が読む)
  downloaded-file-scan.py --record <file> ...   # 記録の 1 行だけ (取り込み先の note・来歴の欄に貼る)
  downloaded-file-scan.py --json <file> ...     # 機械向け
  downloaded-file-scan.py --no-state ...        # state に残さない (試すだけ)
  downloaded-file-scan.py --selftest

終了値: 0 = 要確認なし / 1 = 要確認あり (取り込む前に本人に見せる) / 3 = 検査できなかった部分がある
  (暗号化・読めない・大きすぎる・PyMuPDF が無い) / 2 = 使い方の誤り。 故障と違反を同じ値にしない
  (docs/convention-design-principles.md#failure-exit-equals-violation-exit)。

見るもの (段ごとの意味と限界の正本 = conventions/downloaded-file-scan.md#scan-ladder):
  1. 来歴: macOS の com.apple.quarantine 属性 (flags;時刻;取得した app;id) と kMDItemWhereFroms の取得元の host。
     flags の 0x0001 = ダウンロードの印 (実測: browser で落とした file には立ち、 Preview が書き出した file には立たない)。
  2. 種類: 拡張子でなく先頭の bytes で決める。 拡張子と食い違えば要確認。 実行形式・script・disk image・installer は要確認。
  3. PDF: PyMuPDF で全 object を読み、 能動要素 (/JavaScript /JS /Launch /AA /EmbeddedFile /RichMedia /XFA
     /SubmitForm /ImportData /GoToR /GoToE) の数、 埋め込み file、 link (/URI)、 /OpenAction の中身を数える。
     名前の #xx escape は PyMuPDF が解いてから数える。 開けないときは生の bytes を数え、 未検査の部分ありとする。
  4. zip (Office の OOXML を含む): entry の一覧、 展開先の外を指す path、 symlink、 実行形式、 暗号化、 圧縮比、
     入れ子 (1 段まで)。 Office = macro (vbaProject.bin・macroEnabled)、 ActiveX、 OLE の埋め込み、 外へ取りに行く
     relationship、 外部 link・DDE。 OLE2 (.doc/.xls/.ppt) は stream 名を探すだけ。 RTF = \\object。 SVG = script。
  5. 署名 scan: clamscan が在れば回す (無ければ「未実施」、 入れ方 = 規約の #clamav-install)。
  6. 機械: xprotect status / version (XProtect には file を指定して検査させる CLI が無い = 状態だけを出す)。

検査の記録 (hook が読む): ~/.claude/state/downloaded-file-scan/ に、 path・大きさ・更新時刻の key と中身の sha256 の
  key の 2 つで 1 file 1 json (並列の session が同じ file を書いても壊れないよう tmp + os.replace)。 置き場は
  env DOWNLOADED_FILE_SCAN_STATE で変える (test 用)。 180 日より古い記録は書くついでに消す。

hook の述語 (hooks/downloaded-file-import-guard.py が読む): find_issues(command, cwd, home) -> list。
  Bash の command のうち cp / mv / ditto / rsync / install / ln / unzip / tar の展開が、 ネット由来の file
  (Downloads の下か、 ダウンロードの印つき) を git の作業 tree (HOME 自身を除く) に入れ、 その file の検査の
  記録が無い・要確認・未検査の部分ありなら、 その file を返す。 command に `downloaded-file-scan: accepted <理由>`
  があれば返さない。 heredoc の本文と引用符の中は command と読まない (hook-authoring.md#command-reads-file-tokenize)。
  校正用 = shape_issues(command) (state と属性を見ず、 Downloads を指す取り込みの形だけを当てる。
  calibrate-bash-command-pattern.py --hook <この file> --func shape_issues)。
  射程外 = curl / wget で repo に直接落とす、 python の shutil、 redirect (cat x > y)、 Finder での移動、
  未解決の変数に入った path。

stdlib + PyMuPDF (PDF の段だけ。 無ければその段を未検査にする)。 公開層 (個人の値を持たない)。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import glob as _glob
import hashlib
import io
import json
import os
import plistlib
import random
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from urllib.parse import urlparse

VERSION = 1
SOT = "claude-config/conventions/downloaded-file-scan.md"
TOOL = "downloaded-file-scan.py"
ACCEPT = re.compile(r"downloaded-file-scan:\s*accepted[ \t]+\S")
MAX_STRUCT_BYTES = 2 * 1024 ** 3      # これより大きい file は構造を読まない (未検査にする)
MAX_WALK = 5000                       # dir を検査するときの file 数の上限
NESTED_MAX = 64 * 1024 ** 2           # zip の中の entry を開いて読む大きさの上限
NESTED_TOTAL = 512 * 1024 ** 2        # zip 1 つで中身を読む合計の上限
RECORD_TTL_DAYS = 180
CLAMSCAN_TIMEOUT = 300

PDF_ACTIVE = ["JavaScript", "JS", "Launch", "AA", "EmbeddedFile", "RichMedia", "XFA",
              "SubmitForm", "ImportData", "GoToR", "GoToE"]
PDF_INFO = ["URI", "OpenAction", "AcroForm", "ObjStm"]

# 中身を持ち込むと実行されうる形 (zip の entry・単体の file の拡張子)
RED_EXT = {"exe", "dll", "scr", "com", "cpl", "msi", "msp", "lnk", "hta", "wsf", "wsh", "vbs", "vbe",
           "jse", "ps1", "psm1", "bat", "cmd", "command", "pkg", "mpkg", "dmg", "iso", "jar", "apk",
           "xpi", "crx", "scpt", "workflow", "kext", "dylib", "so", "reg", "action", "app"}
# source code として配られることが多い script (zip の中では数えるだけ、 単体なら要確認)
SCRIPT_EXT = {"sh", "bash", "zsh", "csh", "ksh", "fish", "py", "pl", "rb", "php", "js", "mjs", "applescript"}
ARCHIVE_EXT = {"zip", "jar", "epub", "docx", "xlsx", "pptx", "docm", "xlsm", "pptm", "odt", "ods", "odp"}
EXEC_KINDS = {"macho", "pe", "elf", "script", "dmg", "xar"}
EXT_KIND = {
    "pdf": {"pdf"},
    "zip": {"zip"}, "epub": {"zip"}, "jar": {"zip"},
    "docx": {"zip", "office-enc"}, "xlsx": {"zip", "office-enc"}, "pptx": {"zip", "office-enc"},
    "docm": {"zip", "office-enc"}, "xlsm": {"zip", "office-enc"}, "pptm": {"zip", "office-enc"},
    "odt": {"zip"}, "ods": {"zip"}, "odp": {"zip"},
    "doc": {"ole2", "rtf", "office-enc", "html"}, "xls": {"ole2", "office-enc"}, "ppt": {"ole2", "office-enc"},
    "msg": {"ole2"},
    "rtf": {"rtf"},
    "png": {"png"}, "jpg": {"jpeg"}, "jpeg": {"jpeg"}, "gif": {"gif"}, "webp": {"webp"},
    "tif": {"tiff"}, "tiff": {"tiff"}, "heic": {"heic"},
    "svg": {"svg", "xml", "text"},
    "txt": {"text"}, "csv": {"text"}, "tsv": {"text"}, "md": {"text"}, "tex": {"text"}, "bib": {"text"},
    "json": {"text"}, "yaml": {"text"}, "yml": {"text"},
    "html": {"html", "xml", "text"}, "htm": {"html", "xml", "text"}, "xml": {"xml", "text", "svg", "html"},
    "gz": {"gzip"}, "tgz": {"gzip"}, "bz2": {"bzip2"}, "xz": {"xz"}, "7z": {"7z"}, "rar": {"rar"},
    "tar": {"tar"}, "pkg": {"xar"},
}
KIND_LABEL = {
    "pdf": "PDF", "zip": "zip", "ooxml": "Office (OOXML)", "ole2": "Office 旧形式 (OLE2)", "rtf": "RTF",
    "office-enc": "Office (password で暗号化)",
    "macho": "実行形式 (Mach-O)", "pe": "実行形式 (Windows PE)", "elf": "実行形式 (ELF)",
    "script": "script (#!)", "gzip": "gzip", "bzip2": "bzip2", "xz": "xz", "7z": "7z", "rar": "rar",
    "tar": "tar", "dmg": "disk image (dmg)", "xar": "installer (xar/pkg)", "png": "PNG", "jpeg": "JPEG",
    "gif": "GIF", "webp": "WebP", "tiff": "TIFF", "heic": "HEIC", "svg": "SVG", "html": "HTML",
    "xml": "XML", "text": "text", "empty": "空", "unknown": "不明",
}


# ---------------------------------------------------------------- 種類

def sniff(head: bytes, tail: bytes = b"") -> str:
    """先頭 (と末尾) の bytes から中身の種類を返す。"""
    if not head:
        return "empty"
    if head.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "zip"   # PDF より先 (無圧縮の zip は中の PDF の %PDF- を先頭近くに持つ)
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "ole2"
    if head.startswith(b"{\\rtf"):
        return "rtf"
    if head[:4] in (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe",
                    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"):
        return "macho"
    if head.startswith(b"MZ"):
        return "pe"
    if head.startswith(b"\x7fELF"):
        return "elf"
    if head.startswith(b"#!"):
        return "script"
    if b"%PDF-" in head[:1024]:
        return "pdf"
    if head.startswith(b"xar!"):
        return "xar"
    if head.startswith(b"\x1f\x8b"):
        return "gzip"
    if head.startswith(b"BZh"):
        return "bzip2"
    if head.startswith(b"\xfd7zXZ\x00"):
        return "xz"
    if head.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "7z"
    if head.startswith(b"Rar!\x1a\x07"):
        return "rar"
    if len(head) > 262 and head[257:262] == b"ustar":
        return "tar"
    if head.startswith(b"\x89PNG"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if head[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1"):
        return "heic"
    if tail[-512:].startswith(b"koly"):
        return "dmg"
    if b"\x00" not in head[:4096]:
        try:
            text = head[:8192].decode("utf-8")
        except UnicodeDecodeError:
            text = head[:8192].decode("latin-1")
            if sum(1 for c in text if ord(c) < 9 or 13 < ord(c) < 32) > 8:
                return "unknown"
        low = text.lstrip("\ufeff \t\r\n").lower()
        if low.startswith(("<!doctype html", "<html")) or "<html" in low[:2048]:
            return "html"   # SVG より先 (inline の <svg> を持つ HTML の頁)
        if "<svg" in low[:4096]:
            return "svg"
        if low.startswith("<?xml"):
            return "xml"
        return "text"
    return "unknown"


def _ext(name: str) -> str:
    base = os.path.basename(name.rstrip("/"))
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""


# ---------------------------------------------------------------- 来歴 (macOS)

def _getxattr(path: str, name: str) -> bytes | None:
    if sys.platform != "darwin":
        return None
    try:
        import ctypes
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        fn = libc.getxattr
        fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t,
                       ctypes.c_uint32, ctypes.c_int]
        fn.restype = ctypes.c_ssize_t
        p, n = os.fsencode(path), name.encode()
        size = fn(p, n, None, 0, 0, 0)
        if size < 0:
            return None
        buf = ctypes.create_string_buffer(max(size, 1))
        got = fn(p, n, buf, size, 0, 0)
        return buf.raw[:got] if got >= 0 else None
    except Exception:
        try:
            out = subprocess.run(["xattr", "-px", name, path], capture_output=True, text=True, timeout=5)
            if out.returncode != 0:
                return None
            return bytes.fromhex("".join(out.stdout.split()))
        except Exception:
            return None


def parse_quarantine(raw: bytes | None) -> dict | None:
    """com.apple.quarantine の値 (flags;時刻 16 進;取得した app;id) を読む。 0x0001 = ダウンロードの印。"""
    if not raw:
        return None
    parts = raw.decode("utf-8", "replace").strip("\x00").split(";")
    try:
        flags = int(parts[0], 16)
    except (ValueError, IndexError):
        return {"raw": raw[:80].decode("utf-8", "replace"), "flags": None, "download": False,
                "agent": "", "time": "", "event": False}
    when = ""
    if len(parts) > 1:
        try:
            when = _dt.datetime.fromtimestamp(int(parts[1], 16)).strftime("%Y-%m-%d %H:%M")
        except (ValueError, OverflowError, OSError):
            when = ""
    return {"flags": flags, "download": bool(flags & 0x0001),
            "agent": parts[2] if len(parts) > 2 else "", "time": when,
            "event": bool(len(parts) > 3 and parts[3].strip())}


def where_from_hosts(path: str) -> list[str]:
    raw = _getxattr(path, "com.apple.metadata:kMDItemWhereFroms")
    if not raw:
        return []
    try:
        urls = plistlib.loads(raw)
    except Exception:
        return []
    hosts = []
    for u in urls if isinstance(urls, list) else []:
        try:
            h = urlparse(str(u)).hostname
        except Exception:
            h = None
        if h and h not in hosts:
            hosts.append(h)
    return hosts


def origin_of(path: str) -> dict:
    q = parse_quarantine(_getxattr(path, "com.apple.quarantine"))
    return {"quarantine": q is not None, "download": bool(q and q.get("download")),
            "agent": (q or {}).get("agent", ""), "time": (q or {}).get("time", ""),
            "hosts": where_from_hosts(path) if q else []}


def xprotect_state() -> dict | None:
    exe = "/usr/bin/xprotect"
    if sys.platform != "darwin" or not os.path.exists(exe):
        return None
    st: dict = {}
    try:
        out = subprocess.run([exe, "status"], capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            low = line.lower()
            if "launch scans" in low:
                st["launch"] = "enabled" in low
            elif "background scans" in low:
                st["background"] = "enabled" in low
        out = subprocess.run([exe, "version"], capture_output=True, text=True, timeout=10).stdout
        m = re.search(r"Version:\s*(\S+)", out)
        if m:
            st["version"] = m.group(1)
        m = re.search(r"Installed:\s*(\d{4}-\d{2}-\d{2})", out)
        if m:
            st["installed"] = m.group(1)
    except Exception:
        pass
    return st


# ---------------------------------------------------------------- 署名 scan

def find_clamscan() -> str | None:
    env = os.environ.get("DOWNLOADED_FILE_SCAN_CLAMSCAN")
    if env:
        return None if env == "none" else env
    hit = shutil.which("clamscan")
    if hit:
        return hit
    for p in ("/opt/homebrew/bin/clamscan", "/usr/local/bin/clamscan", "/usr/bin/clamscan"):
        if os.access(p, os.X_OK):
            return p
    return None


def clamav_scan(path: str, exe: str | None) -> tuple[str, str]:
    """(状態, 詳細)。 状態 = clean / found / missing / error。"""
    if not exe:
        return "missing", ""
    try:
        out = subprocess.run([exe, "--no-summary", "--stdout", "--", path], capture_output=True,
                             text=True, timeout=CLAMSCAN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return "error", "時間切れ"
    except OSError as e:
        return "error", type(e).__name__
    if out.returncode == 0:
        return "clean", ""
    if out.returncode == 1:
        sigs = [ln.rsplit(":", 1)[-1].replace("FOUND", "").strip()
                for ln in out.stdout.splitlines() if ln.rstrip().endswith("FOUND")]
        return "found", ", ".join(s for s in sigs if s) or "FOUND"
    msg = (out.stderr or out.stdout).strip().splitlines()
    return "error", (msg[-1][:160] if msg else f"rc={out.returncode}")


# ---------------------------------------------------------------- 結果の器

class Result:
    def __init__(self, path: str):
        self.path = path
        self.kind = "unknown"
        self.size = 0
        self.sha256 = ""
        self.origin: dict = {}
        self.findings: list[tuple[str, str]] = []   # (level, 文) level = red / incomplete / note / info
        self.pdf: dict | None = None
        self.zip: dict | None = None
        self.clamav: tuple[str, str] = ("missing", "")

    def add(self, level: str, what: str) -> None:
        if (level, what) not in self.findings:
            self.findings.append((level, what))

    @property
    def verdict(self) -> str:
        levels = {lv for lv, _ in self.findings}
        if "red" in levels:
            return "findings"
        if "incomplete" in levels:
            return "incomplete"
        return "clean"

    def as_dict(self) -> dict:
        return {"path": self.path, "kind": self.kind, "size": self.size, "sha256": self.sha256,
                "origin": self.origin, "verdict": self.verdict,
                "findings": [{"level": lv, "what": w} for lv, w in self.findings],
                "pdf": self.pdf, "zip": self.zip, "clamav": list(self.clamav)}


# ---------------------------------------------------------------- PDF

def _count_names(text: str, names: list[str]) -> dict:
    return {n: len(re.findall(r"/" + re.escape(n) + r"(?![A-Za-z0-9#])", text)) for n in names}


def _unescape_names(data: bytes) -> bytes:
    def fix(m: re.Match) -> bytes:
        return b"/" + re.sub(rb"#([0-9A-Fa-f]{2})", lambda h: bytes([int(h.group(1), 16)]), m.group(1))
    return re.sub(rb"/([A-Za-z0-9#]+)", fix, data)


def _openaction_summary(text: str) -> tuple[str, bool]:
    """(要約, 危険か)。 text = OpenAction の値 (dict / array / 参照先の object)。"""
    t = text.strip()
    if t.startswith("["):
        return "頁を開くだけ (行き先の配列)", False
    m = re.search(r"/S\s*/([A-Za-z]+)", t)
    s = m.group(1) if m else ""
    if s == "GoTo":
        return "頁を開くだけ (/S /GoTo)", False
    if not s:
        return "中身を読めない (" + t[:40].replace("\n", " ") + ")", True
    return f"/S /{s}", True


def inspect_pdf(res: Result, prefix: str, path: str | None = None, data: bytes | None = None) -> None:
    label = prefix or "PDF"
    try:
        import fitz  # PyMuPDF
    except Exception:
        fitz = None
    counts: dict | None = None
    info: dict = {}
    if fitz is not None:
        try:
            doc = fitz.open(path) if path else fitz.open(stream=data, filetype="pdf")
        except Exception as e:
            doc = None
            res.add("incomplete", f"{label}: PyMuPDF で開けない ({type(e).__name__}) = 生の bytes だけを数えた")
        if doc is not None:
            if getattr(doc, "needs_pass", False):
                res.add("incomplete", f"{label}: 暗号化 (password が要る) = 中身を見ていない")
                res.pdf = {"encrypted": True}
                return
            text = []
            for x in range(1, doc.xref_length()):
                try:
                    text.append(doc.xref_object(x, compressed=False))
                except Exception:
                    continue
            try:
                text.append(doc.pdf_trailer())
            except Exception:
                pass
            joined = "\n".join(text)
            counts = _count_names(joined, PDF_ACTIVE + PDF_INFO)
            info["embedded_files"] = doc.embfile_count() if hasattr(doc, "embfile_count") else 0
            # link の kind (LINK_LAUNCH) では判定しない: MuPDF は scheme の無い URI (書き損じの「mailto;…」 など)
            # も LINK_LAUNCH に分ける (実測) = 本物の /Launch は上の名前の数で数える
            links = 0
            file_links = 0
            try:
                for page in doc:
                    for ln in page.get_links():
                        links += 1
                        if str(ln.get("uri") or "").lower().startswith("file:"):
                            file_links += 1
            except Exception:
                pass
            info["links"] = links
            if file_links:
                res.add("info", f"{label}: 手元の file を開く link (file:) {file_links} 個")
            try:
                typ, val = doc.xref_get_key(doc.pdf_catalog(), "OpenAction")
                if typ == "xref":
                    val = doc.xref_object(int(val.split()[0]), compressed=False)
                if typ != "null":
                    summary, bad = _openaction_summary(val)
                    info["openaction"] = summary
                    if bad:
                        res.add("red", f"{label}: 開いた瞬間に動く /OpenAction = {summary}")
            except Exception:
                pass
            info["pages"] = doc.page_count
            doc.close()
    if counts is None:
        try:
            raw = data if data is not None else open(path, "rb").read(min(os.path.getsize(path), 256 * 1024 ** 2))
        except OSError as e:
            res.add("incomplete", f"{label}: 読めない ({type(e).__name__})")
            return
        counts = _count_names(_unescape_names(raw).decode("latin-1"), PDF_ACTIVE + PDF_INFO)
        if fitz is None:
            res.add("incomplete", f"{label}: PyMuPDF が無い = 生の bytes だけを数えた (圧縮された object stream の中は見ていない)")
        m = re.search(r"/OpenAction\s*(<<.*?>>|\[[^\]]*\])", _unescape_names(raw).decode("latin-1"), re.S)
        if m:
            summary, bad = _openaction_summary(m.group(1))
            info["openaction"] = summary
            if bad:
                res.add("red", f"{label}: 開いた瞬間に動く /OpenAction = {summary}")
    active = {k: v for k, v in counts.items() if k in PDF_ACTIVE and v}
    if active:
        res.add("red", f"{label}: 能動要素 " + "・".join(f"/{k} {v}" for k, v in active.items()))
    if info.get("embedded_files"):
        res.add("red", f"{label}: 埋め込み file {info['embedded_files']} 個")
    info["counts"] = counts
    if res.pdf is None and not prefix:
        res.pdf = info


# ---------------------------------------------------------------- zip / Office

REL = re.compile(rb"<Relationship\b[^>]*>", re.I)
ATTR = re.compile(rb'(\w+)\s*=\s*"([^"]*)"')
DDE = re.compile(rb"DDEAUTO|ddeService|\bDDE\b", re.I)


def inspect_ooxml(res: Result, zf: zipfile.ZipFile, names: list[str], prefix: str) -> None:
    label = prefix or "Office"
    low = [n.lower() for n in names]
    if any(n.endswith("vbaproject.bin") for n in low):
        res.add("red", f"{label}: macro (vbaProject.bin)")
    try:
        ct = zf.read("[Content_Types].xml")
        if b"macroenabled" in ct.lower():
            res.add("red", f"{label}: macro 有効の形式 (Content_Types)")
    except Exception:
        pass
    if any("/activex/" in "/" + n for n in low):
        res.add("red", f"{label}: ActiveX")
    emb = [n for n in names if "/embeddings/" in "/" + n.lower()]
    if emb:
        res.add("info", f"{label}: 埋め込み object {len(emb)} 個 (中身は入れ子として見る = Packager・実行形式・macro なら要確認)")
    if any("externallinks/" in n for n in low):
        res.add("red", f"{label}: 他の file への外部 link (externalLinks)")
    hyper = 0
    for n in names:
        if not n.lower().endswith(".rels"):
            continue
        try:
            body = zf.read(n)
        except Exception:
            continue
        for m in REL.finditer(body):
            attrs = {k.decode().lower(): v.decode("utf-8", "replace") for k, v in ATTR.findall(m.group(0))}
            if attrs.get("targetmode", "").lower() != "external":
                continue
            typ = attrs.get("type", "").rsplit("/", 1)[-1]
            if typ == "hyperlink":
                hyper += 1
                continue
            target = attrs.get("target", "")
            u = urlparse(target)
            remote = (u.scheme.lower() in ("http", "https", "ftp") or target.startswith("\\\\")
                      or (u.scheme.lower() == "file" and bool(u.netloc)))
            if remote:
                host = u.hostname or target[:40]
                res.add("red", f"{label}: 開くと外へ取りに行く relationship ({typ} → {host})")
            else:
                res.add("info", f"{label}: 作った機械の file を指す relationship ({typ}) = 外へは取りに行かない形")
    read = 0
    for n in names:
        nl = n.lower()
        if nl.endswith(".xml") and (nl.startswith("word/") or nl.startswith("xl/worksheets/")
                                    or nl.startswith("xl/externallinks/")):
            try:
                body = zf.read(n)
            except Exception:
                continue
            read += 1
            if DDE.search(body):
                res.add("red", f"{label}: DDE ({n})")
            if read > 200:
                break
    if res.zip is not None and not prefix:
        res.zip["external_hyperlinks"] = hyper


def inspect_zip(res: Result, prefix: str, src, depth: int = 0) -> None:
    label = prefix or "zip"
    try:
        zf = zipfile.ZipFile(src)
    except (zipfile.BadZipFile, OSError, ValueError) as e:
        res.add("incomplete", f"{label}: zip として読めない ({type(e).__name__})")
        return
    with zf:
        infos = zf.infolist()
        names = [i.filename for i in infos]
        total_u = sum(i.file_size for i in infos)
        total_c = sum(i.compress_size for i in infos)
        enc, scripts, red_exec = [], 0, []
        for i in infos:
            n = i.filename
            parts = n.replace("\\", "/").split("/")
            if n.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", n) or ".." in parts:
                res.add("red", f"{label}: 展開先の外を指す entry ({n[:80]})")
            if ((i.external_attr >> 16) & 0o170000) == 0o120000:
                res.add("red", f"{label}: symlink の entry ({n[:80]})")
            if i.flag_bits & 0x1:
                enc.append(n)
            ext = _ext(n)
            if ext in RED_EXT or "/Contents/MacOS/" in n or n.rstrip("/").endswith(".app"):
                red_exec.append(n)
            elif ext in SCRIPT_EXT:
                scripts += 1
        if red_exec:
            res.add("red", f"{label}: 実行形式の entry {len(red_exec)} 個 (例 {red_exec[0][:60]})")
        if enc:
            res.add("incomplete", f"{label}: 暗号化された entry {len(enc)} 個 = 中身を見ていない")
        ratio = total_u / max(total_c, 1)
        if total_u > 4 * 1024 ** 3 or (ratio > 100 and total_u > 100 * 1024 ** 2):
            res.add("red", f"{label}: 展開すると {total_u // 1024 ** 2} MB (圧縮比 {ratio:.0f}) = zip bomb の疑い")
        if res.zip is None and not prefix:
            res.zip = {"entries": len(infos), "uncompressed": total_u, "scripts": scripts}
        if scripts:
            res.add("info", f"{label}: script の entry {scripts} 個 (実行する前に読む)")
        if "[Content_Types].xml" in names:
            if not prefix:
                res.kind = "ooxml"
            inspect_ooxml(res, zf, names, prefix)
        # 中身を開いて見る (取り込むと展開される = 1 段まで)
        if depth >= 1:
            return
        budget = NESTED_TOTAL
        for i in infos:
            if i.is_dir() or i.flag_bits & 0x1 or i.filename in ("[Content_Types].xml",):
                continue
            if "[Content_Types].xml" in names:
                if not (_ext(i.filename) in ("pdf", "zip") or "/embeddings/" in "/" + i.filename.lower()):
                    continue
            if i.file_size > NESTED_MAX or i.file_size > budget:
                res.add("incomplete", f"{label}: 大きい entry は開いていない ({i.filename[:60]})")
                continue
            try:
                blob = zf.read(i)
            except Exception as e:
                res.add("incomplete", f"{label}: entry を読めない ({i.filename[:60]}, {type(e).__name__})")
                continue
            budget -= len(blob)
            inspect_blob(res, f"{label} の {i.filename[:80]}", blob, i.filename, depth + 1)


ENC_PACKAGE = "EncryptedPackage".encode("utf-16-le")


def ole2_kind(data: bytes) -> str:
    """OLE2 のうち password で暗号化した Office (OOXML を EncryptedPackage に包んだ形) を分ける。"""
    return "office-enc" if ENC_PACKAGE in data else "ole2"


def inspect_ole2(res: Result, prefix: str, data: bytes) -> None:
    label = prefix or "OLE2"
    u16 = lambda s: s.encode("utf-16-le")  # noqa: E731
    if u16("_VBA_PROJECT") in data or u16("PROJECTwm") in data or u16("Macros") in data:
        res.add("red", f"{label}: macro の stream が在る")
    if u16("Ole10Native") in data or u16("ObjectPool") in data:
        res.add("red", f"{label}: 埋め込み object (Packager / ObjectPool)")
    res.add("note", "OLE2 は stream 名を探しただけ (macro の中身までは見ていない)")


def inspect_textlike(res: Result, prefix: str, kind: str, data: bytes) -> None:
    label = prefix or KIND_LABEL.get(kind, kind)
    low = data[:4 * 1024 ** 2].lower()
    if kind == "rtf":
        if re.search(rb"\\object|\\objdata|\\objupdate", low):
            res.add("red", f"{label}: 埋め込み object (\\object)")
    elif kind == "svg":
        if b"<script" in low or b"javascript:" in low or re.search(rb"\son[a-z]+\s*=", low):
            res.add("red", f"{label}: SVG に script")
    elif kind == "html":
        if b"<script" in low:
            res.add("info", f"{label}: HTML に script (browser で開くと動く)")
        if b"urn:schemas-microsoft-com:office" in low:
            res.add("info", f"{label}: Word / Excel の HTML 形式")


def check_ext_kind(res: Result, prefix: str, name: str, kind: str) -> None:
    ext = _ext(name)
    want = EXT_KIND.get(ext)
    if want and kind not in want and kind not in ("unknown", "empty"):
        res.add("red", f"{prefix or os.path.basename(name)}: 拡張子は .{ext} だが中身は {KIND_LABEL.get(kind, kind)}")
    if kind in EXEC_KINDS:
        res.add("red", f"{prefix or os.path.basename(name)}: {KIND_LABEL[kind]} = 取り込む理由を本人に聞く")
    elif not prefix and ext in RED_EXT | SCRIPT_EXT and kind in ("text", "unknown"):
        res.add("red", f"{os.path.basename(name)}: 実行される形 (.{ext}) = 取り込む理由を本人に聞く")


def inspect_blob(res: Result, prefix: str, data: bytes, name: str, depth: int) -> None:
    kind = sniff(data[:8192], data[-512:])
    if kind == "ole2":
        kind = ole2_kind(data)
    check_ext_kind(res, prefix, name, kind)
    if kind == "pdf":
        inspect_pdf(res, prefix, data=data)
    elif kind == "zip":
        inspect_zip(res, prefix, io.BytesIO(data), depth)
    elif kind == "ole2":
        inspect_ole2(res, prefix, data)
    elif kind == "office-enc":
        res.add("incomplete", f"{prefix}: password で暗号化された Office = 中身を見ていない")
    elif kind in ("rtf", "svg", "html"):
        inspect_textlike(res, prefix, kind, data)


# ---------------------------------------------------------------- 1 file

def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_file(path: str, clamscan: str | None) -> Result:
    res = Result(path)
    try:
        st = os.stat(path)
        res.size = st.st_size
        res.sha256 = _sha256(path)
        with open(path, "rb") as f:
            head = f.read(8192)
            tail = b""
            if st.st_size > 512:
                f.seek(-512, os.SEEK_END)
                tail = f.read(512)
    except OSError as e:
        res.add("incomplete", f"読めない ({type(e).__name__})")
        return res
    res.origin = origin_of(path)
    res.kind = sniff(head, tail)
    ole = None
    if res.kind == "ole2" and st.st_size <= MAX_STRUCT_BYTES:
        with open(path, "rb") as f:
            ole = f.read()
        res.kind = ole2_kind(ole)
    check_ext_kind(res, "", path, res.kind)
    if st.st_size > MAX_STRUCT_BYTES:
        res.add("incomplete", f"{st.st_size // 1024 ** 2} MB = 大きすぎて構造を読んでいない")
    elif res.kind == "pdf":
        inspect_pdf(res, "", path=path)
    elif res.kind == "zip":
        inspect_zip(res, "", path, 0)
    elif res.kind == "ole2":
        inspect_ole2(res, "", ole if ole is not None else b"")
    elif res.kind == "office-enc":
        res.add("incomplete", "password で暗号化された Office = 中身を見ていない"
                " (password を本人に聞いて開くか、 暗号化を外した版をもらってから検査する)")
    elif res.kind in ("rtf", "svg", "html"):
        with open(path, "rb") as f:
            inspect_textlike(res, "", res.kind, f.read(4 * 1024 ** 2))
    elif res.kind in ("gzip", "bzip2", "xz", "7z", "rar", "tar"):
        res.add("incomplete", f"{KIND_LABEL[res.kind]} の中身は見ていない (展開してから中身を検査する)")
    res.clamav = clamav_scan(path, clamscan)
    if res.clamav[0] == "found":
        res.add("red", f"ClamAV が検出: {res.clamav[1]}")
    elif res.clamav[0] == "error":
        res.add("incomplete", f"ClamAV が失敗: {res.clamav[1]}")
    elif res.clamav[0] == "missing":
        res.add("note", "署名 scan 未実施 (clamscan が無い)")
    return res


def iter_files(target: str) -> tuple[list[str], list[str]]:
    """(検査する file, 数え切れなかった・app bundle などの注記)。"""
    if not os.path.isdir(target):
        return [target], []
    out, notes = [], []
    for root, dirs, files in os.walk(target):
        dirs.sort()
        for d in dirs:
            if d.endswith(".app"):
                notes.append(os.path.join(root, d))
        for fn in sorted(files):
            out.append(os.path.join(root, fn))
            if len(out) >= MAX_WALK:
                notes.append(f"{target}: file が {MAX_WALK} を超えた = 残りは検査していない")
                return out, notes
    return out, notes


# ---------------------------------------------------------------- 記録 (state)

def state_dir(home: str | None = None) -> str:
    env = os.environ.get("DOWNLOADED_FILE_SCAN_STATE")
    if env:
        return env
    return os.path.join(home or os.path.expanduser("~"), ".claude", "state", "downloaded-file-scan")


def stat_key(path: str) -> str | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    rp = os.path.realpath(path)
    return hashlib.sha1(f"{rp}\0{st.st_size}\0{st.st_mtime_ns}".encode("utf-8", "surrogateescape")).hexdigest()


def _atomic_write(path: str, obj: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def write_record(res: Result, home: str | None = None) -> None:
    key = stat_key(res.path)
    if not key or not res.sha256:
        return
    d = state_dir(home)
    rec = {"v": VERSION, "path": os.path.realpath(res.path), "size": res.size, "sha256": res.sha256,
           "verdict": res.verdict, "scanned_at": int(time.time()),
           "findings": [w for lv, w in res.findings if lv in ("red", "incomplete")][:20]}
    _atomic_write(os.path.join(d, "by-stat", key + ".json"), rec)
    _atomic_write(os.path.join(d, "by-sha256", res.sha256 + ".json"), rec)
    if random.random() < 0.05:
        prune_records(d)


def prune_records(d: str) -> None:
    cutoff = time.time() - RECORD_TTL_DAYS * 86400
    for sub in ("by-stat", "by-sha256"):
        for p in _glob.glob(os.path.join(d, sub, "*.json")):
            try:
                if os.path.getmtime(p) < cutoff:
                    os.remove(p)
            except OSError:
                pass


def _read_json(p: str) -> dict | None:
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def lookup_record(path: str, home: str | None = None, by_content: bool = True) -> dict | None:
    d = state_dir(home)
    key = stat_key(path)
    if key:
        rec = _read_json(os.path.join(d, "by-stat", key + ".json"))
        if rec:
            return rec
    if by_content:
        try:
            if os.path.getsize(path) > MAX_STRUCT_BYTES:
                return None
            return _read_json(os.path.join(d, "by-sha256", _sha256(path) + ".json"))
        except OSError:
            return None
    return None


# ---------------------------------------------------------------- 記録の 1 行と表示

def _origin_text(o: dict) -> str:
    if not o:
        return "来歴 = 不明"
    if not o.get("quarantine"):
        return "来歴 = quarantine 属性なし"
    agent = o.get("agent") or "不明の app"
    mark = "ダウンロードの印あり" if o.get("download") else "ダウンロードの印なし"
    return f"来歴 = {agent} (quarantine あり・{mark})"


def _pdf_text(p: dict | None) -> str:
    if not p:
        return ""
    if p.get("encrypted"):
        return "PDF は暗号化 = 構造未検査"
    c = p.get("counts", {})
    active = sum(c.get(k, 0) for k in PDF_ACTIVE)
    s = f"能動要素 {active} ({'・'.join(PDF_ACTIVE)})"
    s += f" / 埋め込み {p.get('embedded_files', 0)} / link {p.get('links', c.get('URI', 0))}"
    if p.get("openaction"):
        s += f" / OpenAction = {p['openaction']}"
    return s


def _zip_text(z: dict | None) -> str:
    if not z:
        return ""
    return f"entry {z['entries']} 個 (展開 {z['uncompressed'] // 1024} KB)"


def record_line(res: Result, today: str | None = None) -> str:
    today = today or _dt.date.today().isoformat()
    parts = [f"{os.path.basename(res.path)} (sha256 {res.sha256[:12]})", KIND_LABEL.get(res.kind, res.kind),
             _origin_text(res.origin)]
    for t in (_pdf_text(res.pdf), _zip_text(res.zip)):
        if t:
            parts.append(t)
    cs, detail = res.clamav
    parts.append({"clean": "署名 scan = 該当なし (ClamAV)", "found": f"署名 scan = 検出 ({detail})",
                  "missing": "署名 scan 未実施 (ClamAV なし)", "error": f"署名 scan 失敗 ({detail})"}[cs])
    reds = [w for lv, w in res.findings if lv == "red"]
    inc = [w for lv, w in res.findings if lv == "incomplete"]
    if reds:
        parts.append(f"判定 = 要確認 {len(reds)} 件 ({'; '.join(reds)[:200]})")
    elif inc:
        parts.append(f"判定 = 未検査の部分あり ({'; '.join(inc)[:200]})")
    else:
        parts.append("判定 = 要確認なし")
    return f"安全検査 ({today}、 {TOOL}): " + " / ".join(parts)


def print_report(res: Result) -> None:
    mb = res.size / 1024 ** 2
    print(f"━ {res.path}  ({KIND_LABEL.get(res.kind, res.kind)}, {mb:.1f} MB, sha256 {res.sha256[:12]})")
    o = res.origin
    if o.get("quarantine"):
        hosts = f"、 取得元 host = {', '.join(o['hosts'])}" if o.get("hosts") else ""
        when = f" ({o['time']})" if o.get("time") else ""
        print(f"  来歴: {o.get('agent') or '不明の app'} で取得{when}、 "
              f"{'ダウンロードの印あり' if o.get('download') else 'ダウンロードの印なし'}{hosts}")
        print("        属性は外さない (開く・実行する時に Gatekeeper と XProtect が見る)")
    else:
        print("  来歴: quarantine 属性なし (git や Dropbox 経由・作り直した file は持たない)")
    for t, lab in ((_pdf_text(res.pdf), "PDF"), (_zip_text(res.zip), "zip")):
        if t:
            print(f"  {lab}: {t}")
    mark = {"red": "🔴 要確認", "incomplete": "⚪ 未検査", "note": "・", "info": "・"}
    for lv, w in res.findings:
        print(f"  {mark[lv]}: {w}")
    print(f"  記録: {record_line(res)}")


def print_machine(xp: dict | None, clamscan: str | None) -> None:
    if xp is not None:
        on = lambda v: "有効" if v else ("無効" if v is False else "不明")  # noqa: E731
        print(f"━ 機械: XProtect launch scan {on(xp.get('launch'))} / background scan {on(xp.get('background'))}"
              f" / 定義 {xp.get('version', '?')} ({xp.get('installed', '?')})"
              "  ※ XProtect に file を指定して検査させる CLI は無い")
    if not clamscan:
        print(f"━ ClamAV なし: 署名 scan を足すなら {SOT}#clamav-install")


# ---------------------------------------------------------------- hook の述語

QUOTED = re.compile(r"\"(?:\\.|[^\"\\])*\"|'[^']*'")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n[ \t]*\2[ \t]*(?=\n|$)", re.S)
SEP = re.compile(r"&&|\|\||;|\||&|\(|\)|\n")
LEADING = {"do", "then", "else", "elif", "if", "while", "until", "{", "!", "time", "command", "builtin",
           "sudo", "nohup", "env", "exec"}
ASSIGN = re.compile(r"^[A-Za-z_]\w*=")
COPY_OPS = {"cp", "mv", "ditto", "rsync", "install", "ln", "gcp", "gmv"}
VALUE_OPTS = {
    "cp": {"-t", "--target-directory", "-S", "--suffix"},
    "mv": {"-t", "--target-directory", "-S", "--suffix"},
    "install": {"-m", "-o", "-g", "-B", "-f", "-t", "--target-directory", "-S", "--suffix", "--mode",
                "--owner", "--group"},
    "ln": {"-t", "--target-directory", "-S", "--suffix"},
    "ditto": {"--arch", "--bom", "--zlibCompressionLevel", "--password"},
    "rsync": {"-e", "--rsh", "-f", "--filter", "--exclude", "--include", "--exclude-from", "--include-from",
              "--files-from", "-T", "--temp-dir", "--partial-dir", "--chmod", "--chown", "-M",
              "--remote-option", "--log-file", "--backup-dir", "--suffix", "--compare-dest", "--copy-dest",
              "--link-dest", "--max-size", "--min-size", "--timeout", "--bwlimit", "--port", "--password-file"},
}


def _blank(m: re.Match) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def _segments(cmd: str) -> list[str]:
    masked = QUOTED.sub(_blank, HEREDOC.sub(_blank, cmd))
    out, start = [], 0
    for m in SEP.finditer(masked):
        out.append((start, m.start()))
        start = m.end()
    out.append((start, len(cmd)))
    return [cmd[a:b].strip() for a, b in out if masked[a:b].strip()]


def _words(seg: str) -> list[str]:
    try:
        words = shlex.split(seg, comments=True)
    except ValueError:
        words = seg.split()
    while words and (words[0] in LEADING or ASSIGN.match(words[0])):
        words = words[1:]
    return words


def _assign_only(seg: str) -> dict | None:
    """代入だけの単純 command (`D=docs/x`) なら {名前: 値}。 command の前置きの代入 (`X=1 cmd`) は数えない。"""
    try:
        words = shlex.split(seg, comments=True)
    except ValueError:
        return None
    if not words or not all(ASSIGN.match(w) for w in words):
        return None
    return dict(w.split("=", 1) for w in words)


def _expand(token: str, here: str | None, home: str, env: dict | None = None) -> list[str]:
    """token を path に。 glob は展開する。 同じ command の中の代入は解く。 解決できない変数・置換は []。"""
    env = env or {}
    t = re.sub(r"\$\{(\w+)\}|\$(\w+)",
               lambda m: env.get(m.group(1) or m.group(2), m.group(0)), token)
    t = t.replace("${HOME}", home).replace("$HOME", home)
    if t == "~" or t.startswith("~/"):
        t = home + t[1:]
    if "$" in t or "`" in t or t.startswith("~"):
        return []
    if not os.path.isabs(t):
        if here is None:
            return []
        t = os.path.join(here, t)
    if any(c in t for c in "*?["):
        return sorted(_glob.glob(t))
    return [t]


def _split_args(op: str, words: list[str]) -> tuple[list[str], str | None]:
    """cp 型の command の (sources, dest)。"""
    vals = VALUE_OPTS.get(op, set())
    args, target, i, end_opts = [], None, 1, False
    while i < len(words):
        w = words[i]
        if not end_opts and w == "--":
            end_opts = True
        elif not end_opts and w.startswith("--target-directory="):
            target = w.split("=", 1)[1]
        elif not end_opts and w in ("-t", "--target-directory") and i + 1 < len(words):
            target = words[i + 1]
            i += 1
        elif not end_opts and w in vals:
            i += 1
        elif not end_opts and w.startswith("-") and w != "-":
            pass
        else:
            args.append(w)
        i += 1
    if target is not None:
        return args, target
    if len(args) < 2:
        return [], None
    return args[:-1], args[-1]


# unzip の展開先に書かない option (一覧 -l -v -Z / 試験 -t / 標準出力 -p -c / 注釈 -z)。 束ねた形 (-tq) も数える
UNZIP_NO_EXTRACT_FLAGS = set("lvZtpcz")


def _archive_args(op: str, words: list[str]) -> tuple[list[str], str | None, bool]:
    """unzip / tar の (archive, 展開先, 展開か)。 展開先が無ければ None (= 今の dir)。"""
    if op == "unzip":
        src, dest, extract, i = [], None, True, 1
        while i < len(words):
            w = words[i]
            if w == "-d" and i + 1 < len(words):
                dest = words[i + 1]
                i += 2
                continue
            if w.startswith("-d") and len(w) > 2:
                dest = w[2:]
            elif w in ("-x", "-P") and i + 1 < len(words):
                i += 2
                if w == "-x":
                    while i < len(words) and not words[i].startswith("-"):
                        i += 1
                continue
            elif not w.startswith("-") and not src:
                src.append(w)
            elif w.startswith("-") and not w.startswith("--") and set(w[1:]) & UNZIP_NO_EXTRACT_FLAGS:
                extract = False
            i += 1
        return src, dest, extract
    # tar
    src, dest, extract, i = [], None, False, 1
    while i < len(words):
        w = words[i]
        if w in ("-C", "--directory") and i + 1 < len(words):
            dest = words[i + 1]
            i += 2
            continue
        if w.startswith("--directory="):
            dest = w.split("=", 1)[1]
        elif w in ("--extract", "--get"):
            extract = True
        elif w.startswith("--file="):
            src.append(w.split("=", 1)[1])
        elif w == "--file" and i + 1 < len(words):
            src.append(words[i + 1])
            i += 2
            continue
        elif (w.startswith("-") and not w.startswith("--")) or (i == 1 and re.fullmatch(r"[A-Za-z]+", w)):
            letters = w.lstrip("-")
            if "x" in letters:
                extract = True
            if "f" in letters:
                rest = letters.split("f", 1)[1]
                if rest:
                    src.append(rest)
                elif i + 1 < len(words):
                    src.append(words[i + 1])
                    i += 2
                    continue
        i += 1
    return src, dest, extract


def import_ops(cmd: str, cwd: str | None, home: str) -> list[tuple[str, list[str], str]]:
    """(op, source の path たち, 取り込み先の path)。 path は解決済み。 解決できない語は捨てる。"""
    here = os.path.realpath(cwd) if cwd else None
    ops = []
    env: dict = {}
    for seg in _segments(cmd):
        asg = _assign_only(seg)
        if asg is not None:
            env.update(asg)
            continue
        words = _words(seg)
        if not words:
            continue
        op = os.path.basename(words[0])
        if op in ("cd", "pushd"):
            arg = next((w for w in words[1:] if not w.startswith("-")), "~")
            got = _expand(arg, here, home, env)
            here = os.path.realpath(got[0]) if got else None
            continue
        if op in COPY_OPS:
            srcs, dest = _split_args(op, words)
            if not srcs or dest is None or ":" in dest.split("/", 1)[0]:
                continue
            paths = [p for s in srcs if ":" not in s.split("/", 1)[0] for p in _expand(s, here, home, env)]
            dests = _expand(dest, here, home, env)
            if paths and dests:
                ops.append((op, paths, dests[0]))
        elif op in ("unzip", "tar"):
            srcs, dest, extract = _archive_args(op, words)
            if not extract or not srcs:
                continue
            paths = [p for s in srcs for p in _expand(s, here, home, env)]
            dests = _expand(dest, here, home, env) if dest else ([here] if here else [])
            if paths and dests:
                ops.append((op, paths, dests[0]))
    return ops


def download_dirs(home: str) -> list[str]:
    dirs = [os.path.join(home, "Downloads")]
    extra = os.environ.get("DOWNLOADED_FILE_SCAN_SOURCES", "")
    dirs += [os.path.expanduser(d) for d in extra.split(":") if d.strip()]
    return [os.path.realpath(d) for d in dirs]


def _under(path: str, roots: list[str]) -> bool:
    for cand in {os.path.abspath(path), os.path.realpath(path)}:
        for r in roots:
            if cand == r or cand.startswith(r.rstrip("/") + "/"):
                return True
    return False


def repo_root(dest: str, home: str) -> str | None:
    """dest (まだ無くてよい) を含む git の作業 tree の root。 HOME 自身・Downloads の下は None。"""
    p = os.path.realpath(dest)
    while not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent
    if os.path.isfile(p):
        p = os.path.dirname(p)
    if _under(p, download_dirs(home)):
        return None
    home_r = os.path.realpath(home)
    while True:
        if os.path.exists(os.path.join(p, ".git")):
            return None if p == home_r else p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


def net_origin_files(src: str, home: str) -> list[str]:
    """src (file か dir) のうち、 ネット由来とみなす file。"""
    roots = download_dirs(home)
    in_dl = _under(src, roots)
    if os.path.isdir(src):
        files, _ = iter_files(src)
        if in_dl:
            return files
        return [f for f in files[:500] if origin_of(f).get("download")]
    if not os.path.exists(src):
        return []
    if in_dl or origin_of(src).get("download"):
        return [src]
    return []


def find_issues(cmd: str, cwd: str | None = None, home: str | None = None) -> list[tuple[str, str, str]]:
    """hook が止める理由: (file, 状態, 取り込み先の repo)。 状態 = 未検査 / 要確認 / 未検査の部分あり。"""
    home = home or os.path.expanduser("~")
    if ACCEPT.search(cmd):
        return []
    issues = []
    for op, srcs, dest in import_ops(cmd, cwd, home):
        root = repo_root(dest, home)
        if not root:
            continue
        for s in srcs:
            for f in net_origin_files(s, home):
                rec = lookup_record(f, home)
                if rec is None:
                    issues.append((f, "未検査", root))
                elif rec.get("verdict") == "findings":
                    issues.append((f, "要確認", root))
                elif rec.get("verdict") == "incomplete":
                    issues.append((f, "未検査の部分あり", root))
    return issues


def shape_issues(cmd: str) -> list[tuple[str, str]]:
    """校正用: Downloads を指す取り込み (cp / mv / 展開) で、 取り込み先が今ある git の作業 tree のもの。"""
    home = os.path.expanduser("~")
    out = []
    for op, srcs, dest in import_ops(cmd, os.getcwd(), home):
        if repo_root(dest, home) and any(_under(s, download_dirs(home)) for s in srcs):
            out.append((op, dest))
    return out


def reason_text(issues: list[tuple[str, str, str]], engine_path: str) -> str:
    lines = ["[downloaded-file-import-guard] ネット由来の file を repo に取り込む前の検査が済んでいない:"]
    for f, state, root in issues[:12]:
        lines.append(f"  - {f} ({state}) → {root}")
    if len(issues) > 12:
        lines.append(f"  … ほか {len(issues) - 12} 件")
    todo = sorted({f for f, s, _ in issues if s == "未検査"})
    if todo:
        args = " ".join(shlex.quote(f) for f in todo[:12])
        lines.append(f"先に検査する: python3 {shlex.quote(engine_path)} {args}")
        lines.append("  (結果の「記録」 の 1 行を取り込み先の note か来歴の欄に書く。 検査の後に同じ command を打てば通る)")
    if any(s != "未検査" for _, s, _ in issues):
        lines.append("要確認・未検査の部分がある file は取り込まずに本人に見せる。 本人が取り込むと決めたら、 command に"
                     " `# downloaded-file-scan: accepted <理由>` を書いて打ち直す (理由は記録にも書く)。")
    lines.append(f"規約 = {SOT}#scan-before-import")
    return "\n".join(lines)


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--record", action="store_true", help="記録の 1 行だけを出す")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-state", action="store_true", help="検査の記録を state に残さない")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.paths:
        ap.error("検査する file か dir を渡す")
    clamscan = find_clamscan()
    results: list[Result] = []
    notes: list[str] = []
    for target in a.paths:
        if not os.path.exists(target):
            r = Result(target)
            r.add("incomplete", "無い path")
            results.append(r)
            continue
        files, ns = iter_files(target)
        notes += ns
        for f in files:
            results.append(scan_file(f, clamscan))
    for n in notes:
        if n.endswith(".app"):
            r = Result(n)
            r.kind = "macho"
            r.add("red", f"{os.path.basename(n)}: app bundle = 取り込む理由を本人に聞く")
            results.append(r)
        else:
            r = Result(n.split(":", 1)[0])
            r.add("incomplete", n)
            results.append(r)
    if not a.no_state:
        for r in results:
            try:
                write_record(r)
            except OSError:
                pass
    if a.json:
        print(json.dumps({"results": [r.as_dict() for r in results], "xprotect": xprotect_state(),
                          "clamscan": clamscan}, ensure_ascii=False, indent=1))
    elif a.record:
        for r in results:
            print(record_line(r))
    else:
        for r in results:
            print_report(r)
        print_machine(xprotect_state(), clamscan)
    verdicts = {r.verdict for r in results}
    if "findings" in verdicts:
        return 1
    if "incomplete" in verdicts:
        return 3
    return 0


# ---------------------------------------------------------------- selftest

def _set_encrypted_flag(zp: str, name: bytes) -> None:
    """test 用: zip の entry の「暗号化」 の flag (bit 0) を central directory と local header の両方で立てる。"""
    data = bytearray(open(zp, "rb").read())
    i = data.find(b"PK\x01\x02")
    while i != -1:
        nlen = int.from_bytes(data[i + 28:i + 30], "little")
        if bytes(data[i + 46:i + 46 + nlen]) == name:
            data[i + 8] |= 0x01
            off = int.from_bytes(data[i + 42:i + 46], "little")
            data[off + 6] |= 0x01
        i = data.find(b"PK\x01\x02", i + 4)
    with open(zp, "wb") as f:
        f.write(data)


def selftest() -> int:
    fails: list[str] = []

    def check(cond: bool, label: str) -> None:
        print(("  ok   " if cond else "  FAIL ") + label)
        if not cond:
            fails.append(label)

    tmp = tempfile.mkdtemp(prefix="dfs-selftest-")
    old_state = os.environ.get("DOWNLOADED_FILE_SCAN_STATE")
    old_clam = os.environ.get("DOWNLOADED_FILE_SCAN_CLAMSCAN")
    os.environ["DOWNLOADED_FILE_SCAN_STATE"] = os.path.join(tmp, "state")
    os.environ["DOWNLOADED_FILE_SCAN_CLAMSCAN"] = "none"
    try:
        home = os.path.join(tmp, "home")
        dl = os.path.join(home, "Downloads")
        repo = os.path.join(home, "work", "repo")
        os.makedirs(dl)
        os.makedirs(os.path.join(repo, ".git"))
        os.makedirs(os.path.join(repo, "docs"))

        def w(name: str, data: bytes, where: str = dl) -> str:
            p = os.path.join(where, name)
            with open(p, "wb") as f:
                f.write(data)
            return p

        def levels(r: Result) -> set:
            return {lv for lv, _ in r.findings}

        print("種類と来歴:")
        check(sniff(b"%PDF-1.7\n") == "pdf", "PDF の magic")
        check(sniff(b"MZ\x90\x00") == "pe", "PE の magic")
        check(sniff(b"<!DOCTYPE html><html>") == "html", "HTML の text")
        q = parse_quarantine(b"0281;6ad84f59;Brave;1611789E-2FC6")
        check(bool(q and q["download"] and q["agent"] == "Brave" and q["event"]), "quarantine: browser の取得 = 印あり")
        q = parse_quarantine(b"0082;6ac89b2c;Preview;")
        check(bool(q and not q["download"]), "quarantine: sandbox の app の書き出し = 印なし")
        check(parse_quarantine(None) is None, "quarantine: 属性なし")

        # 偽の拡張子
        r = scan_file(w("fake.pdf", b"MZ" + b"\x00" * 200), None)
        check(r.verdict == "findings" and any("拡張子" in x for _, x in r.findings), "実行形式を .pdf にした file = 要確認")
        r = scan_file(w("error-page.pdf", b"<!DOCTYPE html><html><body>403</body></html>"), None)
        check(any("中身は HTML" in x for _, x in r.findings), "HTML の頁を .pdf で保存 = 食い違い")
        r = scan_file(w("notes.txt", b"plain text\n"), None)
        check(r.verdict == "clean", "text = 要確認なし")
        r = scan_file(w("run.sh", b"#!/bin/sh\necho hi\n"), None)
        check(r.verdict == "findings", "単体の script = 要確認")

        print("PDF:")
        try:
            import fitz
        except Exception:
            fitz = None
        raw = (b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R /OpenAction << /S /J#61vaScript /JS (1) >> >>\n"
               b"endobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n"
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n")
        r = scan_file(w("escaped.pdf", raw), None)
        check(r.verdict == "findings" and any("/JavaScript" in x for _, x in r.findings),
              "名前を #61 で隠した /JavaScript を数える")
        check(any("OpenAction" in x for _, x in r.findings), "/OpenAction の JavaScript = 要確認")
        if fitz is None:
            print("  SKIP PyMuPDF が無い (PDF の残りの case)")
        else:
            d = fitz.open()
            d.new_page().insert_text((72, 72), "hello")
            d.xref_set_key(d.pdf_catalog(), "OpenAction", f"[{d[0].xref} 0 R /FitH 0]")
            p = os.path.join(dl, "clean.pdf")
            d.save(p)
            r = scan_file(p, None)
            check(r.verdict == "clean" and "頁を開くだけ" in (r.pdf or {}).get("openaction", ""),
                  "GoTo の OpenAction だけの PDF = 要確認なし")
            check(sum((r.pdf or {}).get("counts", {}).get(k, 0) for k in PDF_ACTIVE) == 0, "能動要素 0")
            d = fitz.open()
            d.new_page()
            d.embfile_add("a.txt", b"hello")
            p = os.path.join(dl, "emb.pdf")
            d.save(p)
            r = scan_file(p, None)
            check(any("埋め込み file" in x for _, x in r.findings), "埋め込み file = 要確認")
            d = fitz.open()
            d.new_page()
            p = os.path.join(dl, "locked.pdf")
            d.save(p, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
            r = scan_file(p, None)
            check(r.verdict == "incomplete", "暗号化 PDF = 未検査の部分あり")
            d = fitz.open()
            d.new_page()
            buf = d.tobytes()
            zp = os.path.join(dl, "papers.zip")
            with zipfile.ZipFile(zp, "w") as z:
                z.writestr("a.pdf", buf)
                z.writestr("b.pdf", raw)
            r = scan_file(zp, None)
            check(any("b.pdf" in x and "/JavaScript" in x for _, x in r.findings), "zip の中の PDF も数える")

        print("zip と Office:")
        zp = os.path.join(dl, "bad.zip")
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr("../escape.txt", "x")
            z.writestr("setup.exe", "MZ")
            z.writestr("secret.txt", "x")
            link = zipfile.ZipInfo("link")
            link.external_attr = (0o120777 << 16)
            z.writestr(link, "/etc/passwd")
        _set_encrypted_flag(zp, b"secret.txt")  # zipfile は書くときに flag を 0 に戻す = 後から bytes で立てる
        r = scan_file(zp, None)
        whats = " ".join(x for _, x in r.findings)
        check("展開先の外" in whats, "zip: ../ の entry")
        check("実行形式の entry" in whats, "zip: .exe の entry")
        check("暗号化された entry" in whats, "zip: 暗号化の印の entry")
        check("symlink" in whats, "zip: symlink の entry")
        ct = b'<?xml version="1.0"?><Types><Default Extension="xml" ContentType="application/xml"/></Types>'
        dp = os.path.join(dl, "macro.docx")
        with zipfile.ZipFile(dp, "w") as z:
            z.writestr("[Content_Types].xml", ct)
            z.writestr("word/document.xml", "<w:document/>")
            z.writestr("word/vbaProject.bin", "x")
        r = scan_file(dp, None)
        check(r.kind == "ooxml" and any("vbaProject" in x for _, x in r.findings), "docx の macro")
        dp = os.path.join(dl, "template.docx")
        rel = (b'<Relationships><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/'
               b'2006/relationships/attachedTemplate" Target="http://example.invalid/t.dotm" '
               b'TargetMode="External"/><Relationship Id="r2" Type="http://schemas.openxmlformats.org/'
               b'officeDocument/2006/relationships/hyperlink" Target="https://example.invalid/" '
               b'TargetMode="External"/></Relationships>')
        with zipfile.ZipFile(dp, "w") as z:
            z.writestr("[Content_Types].xml", ct)
            z.writestr("word/document.xml", "<w:document/>")
            z.writestr("word/_rels/settings.xml.rels", rel)
        r = scan_file(dp, None)
        reds = [x for lv, x in r.findings if lv == "red"]
        check(len(reds) == 1 and "attachedTemplate" in reds[0], "外の template を取りに行く relationship (hyperlink は数えない)")
        with zipfile.ZipFile(dp, "w") as z:
            z.writestr("[Content_Types].xml", ct)
            z.writestr("word/document.xml", "<w:document/>")
            z.writestr("word/_rels/settings.xml.rels", rel.replace(b"http://example.invalid/t.dotm",
                                                                    b"file:///Y:\\templates\\t.dotx"))
        check(scan_file(dp, None).verdict == "clean", "作った機械の template の path (file:///Y:) = 数えるだけ")
        r = scan_file(w("page.html", b"<!DOCTYPE html><html><body><svg></svg></body></html>"), None)
        check(r.kind == "html" and r.verdict == "clean", "inline の SVG を持つ HTML の頁 = HTML")
        dp = os.path.join(dl, "plain.docx")
        with zipfile.ZipFile(dp, "w") as z:
            z.writestr("[Content_Types].xml", ct)
            z.writestr("word/document.xml", "<w:document><w:t>hi</w:t></w:document>")
        check(scan_file(dp, None).verdict == "clean", "普通の docx = 要確認なし")
        ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64 + "_VBA_PROJECT".encode("utf-16-le")
        r = scan_file(w("old.doc", ole), None)
        check(any("macro の stream" in x for _, x in r.findings), "OLE2 の macro の stream 名")
        enc = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64 + "EncryptedPackage".encode("utf-16-le")
        r = scan_file(w("locked.xlsx", enc), None)
        check(r.kind == "office-enc" and r.verdict == "incomplete" and not any("拡張子" in x for _, x in r.findings),
              "password つきの xlsx (OLE2 の EncryptedPackage) = 未検査、 拡張子の食い違いにしない")
        pk = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64 + "Ole10Native".encode("utf-16-le")
        dp = os.path.join(dl, "deck.pptx")
        with zipfile.ZipFile(dp, "w") as z:
            z.writestr("[Content_Types].xml", ct)
            z.writestr("ppt/presentation.xml", "<p:presentation/>")
            z.writestr("ppt/embeddings/oleObject1.bin", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)
        r = scan_file(dp, None)
        check(r.verdict == "clean" and any("埋め込み object 1 個" in x for _, x in r.findings),
              "Office の普通の埋め込み object = 数えるだけ")
        with zipfile.ZipFile(dp, "a") as z:
            z.writestr("ppt/embeddings/oleObject2.bin", pk)
        r = scan_file(dp, None)
        check(r.verdict == "findings" and any("Packager" in x for _, x in r.findings), "Packager の埋め込み = 要確認")

        print("署名 scan (偽の clamscan):")
        fake = os.path.join(tmp, "clamscan")
        with open(fake, "w") as f:
            f.write('#!/bin/sh\nfor a; do last="$a"; done\necho "$last: Test-Signature FOUND"\nexit 1\n')
        os.chmod(fake, 0o755)
        r = scan_file(os.path.join(dl, "notes.txt"), fake)
        check(r.verdict == "findings" and r.clamav == ("found", "Test-Signature"), "clamscan の FOUND = 要確認")
        r = scan_file(os.path.join(dl, "notes.txt"), None)
        check(r.verdict == "clean" and any("署名 scan 未実施" in x for _, x in r.findings),
              "clamscan が無い = 注記だけ (判定は変えない)")
        check("署名 scan 未実施 (ClamAV なし)" in record_line(r), "記録の 1 行に未実施と書く")

        print("記録と hook の述語:")
        pdf = w("paper.txt", b"plain text of a downloaded note\n")  # PyMuPDF に依らない (偽の HOME では user site が消える)
        cp = f"cp ~/Downloads/paper.txt {repo}/docs/"
        got = find_issues(cp, repo, home)
        check(len(got) == 1 and got[0][1] == "未検査", "未検査の file を repo へ cp = 止める")
        write_record(scan_file(pdf, None), home)
        check(find_issues(cp, repo, home) == [], "検査の後の同じ cp = 通す")
        moved = os.path.join(home, "work", "elsewhere.txt")
        shutil.copy2(pdf, moved)
        check(lookup_record(moved, home) is not None, "同じ中身なら別の path でも記録を引ける (sha256)")
        with open(pdf, "ab") as f:
            f.write(b"\n")
        check(len(find_issues(cp, repo, home)) == 1, "中身が変わったら未検査に戻る")
        check(find_issues(cp + "  # downloaded-file-scan: accepted 本人が決めた", repo, home) == [],
              "accepted の印 = 通す")
        check(find_issues(f"cp ~/Downloads/paper.txt {tmp}/", repo, home) == [], "取り込み先が repo の外 = 見ない")
        check(find_issues(f"cp ~/Downloads/paper.txt {home}/x.pdf", repo, home) == [], "HOME 直下 = 見ない")
        check(len(find_issues(f"cd ~/Downloads && mv paper.txt {repo}/docs/", tmp, home)) == 1, "cd の後の mv")
        check(len(find_issues(f"cp ~/Downloads/*.txt {repo}/docs/", repo, home)) >= 1, "glob の cp")
        check(len(find_issues("D=docs/in; cp ~/Downloads/paper.txt $D/", repo, home)) == 1,
              "同じ command の代入に入れた取り込み先")
        check(find_issues(f"S={tmp}/scratch; cp ~/Downloads/paper.txt $S/", repo, home) == [],
              "代入に入れた行き先が repo の外 = 見ない")
        check(find_issues("cp ~/Downloads/paper.txt $UNSET/", repo, home) == [], "解けない変数 = 見ない (fail-open)")
        check(find_issues(f"echo 'cp ~/Downloads/paper.txt {repo}/'", repo, home) == [], "引用符の中 = 見ない")
        check(find_issues(f"cat > n.md <<'EOF'\ncp ~/Downloads/paper.txt {repo}/\nEOF", repo, home) == [],
              "heredoc の本文 = 見ない")
        check(find_issues(f"git commit -m 'cp ~/Downloads/paper.txt {repo}'", repo, home) == [], "commit message = 見ない")
        check(len(find_issues(f"unzip -q ~/Downloads/bad.zip -d {repo}/x", repo, home)) == 1, "unzip -d repo")
        check(len(find_issues("unzip -qo ~/Downloads/bad.zip", repo, home)) == 1, "unzip -qo (今の dir が repo) = 展開する")
        for flag in ("-l", "-tq", "-Z1", "-v", "-p"):
            check(find_issues(f"unzip {flag} ~/Downloads/bad.zip", repo, home) == [], f"unzip {flag} = 展開しない")
        check(len(find_issues(f"cd {repo} && tar -xzf ~/Downloads/bad.zip", tmp, home)) == 1, "tar -x (今の dir が repo)")
        check(find_issues(f"tar -czf ~/Downloads/out.tgz {repo}", repo, home) == [], "tar -c (作る側) = 見ない")
        check(len(find_issues(f"rsync -a --exclude .DS_Store ~/Downloads/ {repo}/in/", repo, home)) >= 1, "rsync の dir")
        write_record(scan_file(os.path.join(dl, "bad.zip"), None), home)
        got = find_issues(f"unzip ~/Downloads/bad.zip -d {repo}/x", repo, home)
        check(len(got) == 1 and got[0][1] == "要確認", "要確認の記録 = 止める (要確認と言う)")
        msg = reason_text(got, "/x/downloaded-file-scan.py")
        check("accepted" in msg and "本人" in msg, "止める文に本人に見せる手順")
        msg = reason_text([(pdf, "未検査", repo)], "/x/downloaded-file-scan.py")
        check("python3 /x/downloaded-file-scan.py" in msg, "止める文に検査の command")

        print("main の終了値:")
        os.environ["DOWNLOADED_FILE_SCAN_STATE"] = os.path.join(tmp, "state2")
        sink = io.StringIO()
        real = sys.stdout
        sys.stdout = sink
        try:
            rc_clean = main(["--record", os.path.join(dl, "notes.txt")])
            rc_red = main(["--record", os.path.join(dl, "bad.zip")])
            rc_inc = main(["--record", os.path.join(dl, "missing.pdf")])
        finally:
            sys.stdout = real
        check((rc_clean, rc_red, rc_inc) == (0, 1, 3), f"0 / 1 / 3 (実際 {rc_clean} / {rc_red} / {rc_inc})")
        check(os.path.isdir(os.path.join(tmp, "state2", "by-stat")), "検査の記録を state に残す")
    finally:
        for k, v in (("DOWNLOADED_FILE_SCAN_STATE", old_state), ("DOWNLOADED_FILE_SCAN_CLAMSCAN", old_clam)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp, ignore_errors=True)
    print(("selftest: FAIL " + str(len(fails))) if fails else "selftest: PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
