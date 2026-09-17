#!/usr/bin/env python3
"""drive-download-folder.py — Google Drive folder を再帰で一括 download する (native は export、 各 dir に manifest、 token と OAuth client は引数で受ける)

recipe・gotcha の正本 = conventions/google-api-direct-access.md#drive-folder-bulk-download。
継続して読みに行く共有 folder は shared-drive-folder-watch.py (標準ライブラリだけ、 版の差分だけ取る) を使う。

使い方:
    python3 drive-download-folder.py <folder-id-or-URL> --dest <dir> \\
        --credentials <token.json> --oauth-keys <client.json> [--auth-hint '<token の発行手順>']
    python3 drive-download-folder.py --selftest     (合成の Drive で検査。 network にも client library にも触れない)

認証: --credentials = refresh_token (あれば access_token / scope も) を持つ JSON。 scope は drive.readonly で足りる。
      共有された folder は共有を受けた account の token でしか見えない (別 account では 404)。
      --oauth-keys = OAuth client の JSON (installed か web の client_id / client_secret)。
      account 名 → token の対応を持つ呼び出し側 (個人層の shim など) は build_service(token, client, hint) と
      run(drive, folder, dest) を直接呼ぶ。

挙動:
    - folder を paginated list (supportsAllDrives) → file は get_media、
      Google native (docs/sheets/slides) は export_media (PDF/xlsx/pptx)
    - subfolder は同名 dir を掘って再帰
    - 各 dir に _drive_manifest.json (= id/name/mimeType/modifiedTime/size/webViewLink の
      provenance snapshot) を保存
    - file 名は原名保持 (= 「〜のコピー」 含む)、 衝突時のみ ` (2)` suffix
    - export ~10 MB 上限で fail した file は [ERROR] 表示して続行 (= fail-loud、 全体は止めない)、
      1 件でも失敗があれば exit 1
    - google-api-python-client は使う時点で読む (無ければその時点で案内して exit)
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    _GOOGLE_IMPORT_ERROR: ImportError | None = None
except ImportError as e:  # selftest と import だけなら client library は要らない
    Request = Credentials = build = MediaIoBaseDownload = None
    _GOOGLE_IMPORT_ERROR = e

FOLDER_MIME = "application/vnd.google-apps.folder"
# Google native mime -> (export mime, 拡張子)
EXPORT_MAP = {
    "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
}


def _require_google() -> None:
    if _GOOGLE_IMPORT_ERROR is not None:
        sys.exit(f"google-api-python-client が必要: {_GOOGLE_IMPORT_ERROR}")


def extract_folder_id(arg: str) -> str:
    """folder ID そのもの or Drive URL から ID を抽出。"""
    m = re.search(r"/folders/([A-Za-z0-9_-]+)", arg)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([A-Za-z0-9_-]+)", arg)
    if m:
        return m.group(1)
    return arg.strip()


def build_service(cred_path, oauth_keys, auth_hint: str = ""):
    """token JSON と OAuth client JSON から Drive v3 service を作る (access token は必要なら refresh、 file には書き戻さない)。"""
    cred_path, oauth_keys = Path(cred_path).expanduser(), Path(oauth_keys).expanduser()
    if not cred_path.exists():
        sys.exit(f"❌ {cred_path} が無い。" + (f" setup: {auth_hint}" if auth_hint else ""))
    _require_google()
    tok = json.loads(cred_path.read_text())
    raw = json.loads(oauth_keys.read_text())
    inst = raw.get("installed") or raw.get("web") or {}
    creds = Credentials(
        token=tok.get("access_token"),
        refresh_token=tok.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=inst.get("client_id"),
        client_secret=inst.get("client_secret"),
        scopes=tok.get("scope", "").split(" "),
    )
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def list_folder(drive, folder_id: str) -> list[dict]:
    files, page = [], None
    while True:
        resp = drive.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id, name, mimeType, modifiedTime, size, webViewLink)",
            pageSize=200,
            pageToken=page,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        files.extend(resp.get("files", []))
        page = resp.get("nextPageToken")
        if not page:
            return files


def unique_path(dest_dir: Path, name: str) -> Path:
    """原名保持、 衝突時のみ ' (2)' 等の suffix。"""
    p = dest_dir / name
    if not p.exists():
        return p
    stem, suffix = p.stem, p.suffix
    for i in range(2, 100):
        q = dest_dir / f"{stem} ({i}){suffix}"
        if not q.exists():
            return q
    raise RuntimeError(f"名前衝突を解決できない: {name}")


def download_file(drive, f: dict, dest_dir: Path) -> Path | None:
    if MediaIoBaseDownload is None:
        _require_google()
    fid, name, mime = f["id"], f["name"], f["mimeType"]
    if mime in EXPORT_MAP:
        export_mime, ext = EXPORT_MAP[mime]
        out_name = name if name.lower().endswith(ext) else name + ext
        request = drive.files().export_media(fileId=fid, mimeType=export_mime)
        tag = "EXPORT"
    else:
        out_name = name
        request = drive.files().get_media(fileId=fid, supportsAllDrives=True)
        tag = "BINARY"
    dest = unique_path(dest_dir, out_name)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    dest.write_bytes(buf.getvalue())
    print(f"[{tag}] {name} -> {dest.name} ({dest.stat().st_size:,} bytes)")
    return dest


def process_folder(drive, folder_id: str, dest_dir: Path, label: str = "root") -> tuple[int, int]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    files = list_folder(drive, folder_id)
    print(f"\n=== {label}: {len(files)} entries -> {dest_dir}")
    ok = err = 0
    subfolders = []
    for f in files:
        if f["mimeType"] == FOLDER_MIME:
            subfolders.append(f)
            continue
        try:
            download_file(drive, f, dest_dir)
            ok += 1
        except Exception as e:
            print(f"[ERROR] {f['name']}: {e}", file=sys.stderr)
            err += 1
    (dest_dir / "_drive_manifest.json").write_text(
        json.dumps(files, ensure_ascii=False, indent=2))
    for sf in subfolders:
        s_ok, s_err = process_folder(drive, sf["id"], dest_dir / sf["name"], sf["name"])
        ok += s_ok
        err += s_err
    return ok, err


def run(drive, folder: str, dest) -> int:
    """folder (ID or URL) を dest に落として件数を表示。 戻り値 = exit code (失敗が 1 件でもあれば 1)。"""
    folder_id = extract_folder_id(folder)
    ok, err = process_folder(drive, folder_id, Path(dest).expanduser())
    print(f"\n✅ downloaded {ok} files" + (f" / ❌ {err} errors" if err else ""))
    return 1 if err else 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder", help="Drive folder ID or URL")
    ap.add_argument("--dest", required=True, help="保存先 dir")
    ap.add_argument("--credentials", required=True, help="refresh_token を持つ token JSON")
    ap.add_argument("--oauth-keys", required=True, help="OAuth client の JSON (installed / web)")
    ap.add_argument("--auth-hint", default="", help="token が無いときに出す発行手順")
    args = ap.parse_args(argv)
    drive = build_service(args.credentials, args.oauth_keys, args.auth_hint)
    return run(drive, args.folder, args.dest)


# ---------------------------------------------------------------- selftest

class _Req:
    def __init__(self, data: bytes, fail: bool = False):
        self.data, self.fail = data, fail


class _FakeDownloader:
    def __init__(self, buf, request):
        if request.fail:
            raise RuntimeError("export limit")
        self.buf, self.request = buf, request

    def next_chunk(self):
        self.buf.write(self.request.data)
        return None, True


class _FakeFiles:
    def __init__(self, tree: dict):
        self.tree, self.calls, self.page_tokens = tree, [], []

    def list(self, q, fields, pageSize, pageToken, supportsAllDrives, includeItemsFromAllDrives):
        folder_id = q.split("'")[1]
        pages = self.tree[folder_id]
        i = int(pageToken or 0)
        self.page_tokens.append(pageToken)
        resp = {"files": pages[i]}
        if i + 1 < len(pages):
            resp["nextPageToken"] = str(i + 1)

        class _Exec:
            def execute(self):
                return resp
        return _Exec()

    def export_media(self, fileId, mimeType):
        self.calls.append(("export", fileId, mimeType))
        return _Req(b"EXPORTED", fail=fileId.startswith("too-big"))

    def get_media(self, fileId, supportsAllDrives):
        self.calls.append(("media", fileId, supportsAllDrives))
        return _Req(b"BINARY")


class _FakeDrive:
    def __init__(self, tree: dict):
        self._files = _FakeFiles(tree)

    def files(self):
        return self._files


def selftest() -> int:
    ok = True

    def check(cond, name):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name)
        ok = ok and bool(cond)

    check(extract_folder_id("https://drive.google.com/drive/folders/Fixture_Id-01?usp=sharing") == "Fixture_Id-01"
          and extract_folder_id("https://drive.google.com/open?id=FixtureId02") == "FixtureId02"
          and extract_folder_id("  FixtureId03 ") == "FixtureId03", "folder ID: URL (folders / open?id=) と ID そのもの")

    global MediaIoBaseDownload
    saved = MediaIoBaseDownload
    MediaIoBaseDownload = _FakeDownloader
    try:
        with tempfile.TemporaryDirectory(prefix="ddf-selftest-") as tmp:
            root = Path(tmp)
            (root / "c").mkdir()
            (root / "c" / "a.pdf").write_text("x")
            (root / "c" / "a (2).pdf").write_text("x")
            check(unique_path(root / "c", "a.pdf").name == "a (3).pdf" and unique_path(root / "c", "b.pdf").name == "b.pdf",
                  "名前衝突だけ連番 suffix")

            tree = {
                "ROOT": [[{"id": "b1", "name": "same.pdf", "mimeType": "application/pdf"},
                          {"id": "s1", "name": "table", "mimeType": "application/vnd.google-apps.spreadsheet"},
                          {"id": "sub", "name": "Inner", "mimeType": FOLDER_MIME}],
                         [{"id": "b2", "name": "same.pdf", "mimeType": "application/pdf"},
                          {"id": "too-big", "name": "deck", "mimeType": "application/vnd.google-apps.presentation"}]],
                "sub": [[{"id": "d1", "name": "note.pdf", "mimeType": "application/vnd.google-apps.document"}]],
            }
            drive = _FakeDrive(tree)
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = run(drive, "https://drive.google.com/drive/folders/ROOT", root / "dest")
            dest = root / "dest"
            got = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())
            check(got == ["Inner/_drive_manifest.json", "Inner/note.pdf", "_drive_manifest.json",
                          "same (2).pdf", "same.pdf", "table.xlsx"],
                  "再帰 + native は拡張子を足して export + 同名は (2) + 各 dir に manifest")
            check(drive._files.page_tokens[:2] == [None, "1"], "listing は nextPageToken が尽きるまで読む")
            check([c[0] for c in drive._files.calls] == ["media", "export", "media", "export", "export"],
                  "binary は get_media、 native は export_media")
            manifest = json.loads((dest / "_drive_manifest.json").read_text())
            check([f["id"] for f in manifest] == ["b1", "s1", "sub", "b2", "too-big"], "manifest = listing そのまま (folder も含む)")
            check(rc == 1 and "[ERROR] deck: export limit" in err.getvalue()
                  and out.getvalue().rstrip().endswith("✅ downloaded 4 files / ❌ 1 errors"),
                  "失敗は [ERROR] にして続け、 件数を出して exit 1")
            check("[EXPORT] table -> table.xlsx (8 bytes)" in out.getvalue()
                  and "[BINARY] same.pdf -> same (2).pdf (6 bytes)" in out.getvalue(), "1 file 1 行の表示")
            with contextlib.redirect_stdout(io.StringIO()):
                rc0 = run(_FakeDrive({"E": [[{"id": "x1", "name": "x.pdf", "mimeType": "application/pdf"}]]}), "E", root / "d2")
            check(rc0 == 0, "失敗が無ければ exit 0")
            try:
                build_service(root / "missing.json", root / "keys.json", "HOW-TO-ISSUE")
                msg = "no exit"
            except SystemExit as e:
                msg = str(e.code)
            check(msg == f"❌ {root / 'missing.json'} が無い。 setup: HOW-TO-ISSUE", "token が無ければ発行手順を出して止まる")
    finally:
        MediaIoBaseDownload = saved
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
