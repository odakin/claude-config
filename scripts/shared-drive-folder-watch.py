#!/usr/bin/env python3
"""shared-drive-folder-watch.py — 他人から共有された Google Drive folder を台帳で監視し、 版の差分だけを手元の写しに落とす (標準ライブラリだけで動く)

一般則 = conventions/google-api-direct-access.md#shared-folder-watch
(共有を受けた account の token / 台帳 / id + modifiedTime の差分 / 知らせる面と取る面の分離 / 共有通知の照合)。

台帳 (.json は標準ライブラリだけで読む。 それ以外は YAML として読み、 PyYAML が要る)
  folders[]            読みに行く folder
    id                 表示用の短い名前 (必須)
    folder_id          Drive の folder ID (必須。 共有通知から取り、 推測で埋めない)
    account            共有を受けた account の名前 (= credentials の key。 省くと default_account)
    mirror             写しの置き場 (必須。 git に入れない dir にする)
    shared_by / project / note   表示用 (任意)
    exclude            名前 (写しの中の相対 path) にこの語を含む file は監視も取り込みもしない (任意)
  credentials          account → {path: refresh token を持つ JSON,
                                  auth: token が無い / 失効したときに出す承認の案内文,
                                  oauth_keys: OAuth client の JSON (任意。 無ければ top-level の oauth_keys),
                                  git_tracked: true なら token が git 管理下にあるかも見る (複数マシンで同じ token を配る運用のとき)}
  oauth_keys           OAuth client の JSON (installed か web の client_id / client_secret)
  default_account      account を省いた entry に使う名前 (任意)
  share_mail.ignore_ids   共有通知に出ても知らせない id (任意。 share_mail の他の key は呼び出し側が使う)

呼び出し側 (個人層の shim など) は main() の引数で 台帳 path / credentials / oauth_keys / default_account /
sync の案内文 を注入できる (台帳の値より優先)。 共有通知メールを取ってくる部分は engine に持たない:
呼び出し側が share_notice_source(registry, lines) を渡し、 その中で extract_drive_ids と share_notice を使う。

使い方:
  shared-drive-folder-watch.py --registry R            状態を表示 (知らせることが無ければ無出力)
  shared-drive-folder-watch.py --registry R --surface  SessionStart hook 用 (Drive から消えた file の件数は出さない)
  shared-drive-folder-watch.py --registry R --sync [--only 語]   未取得・更新された file を写しに落とす
  shared-drive-folder-watch.py --registry R --list     登録 folder の中身を一覧する (落とさない)
  shared-drive-folder-watch.py --registry R --fetch-to DIR --only 語   語を含む file を DIR に落とす
                       (写しと state は変えない。 exclude した file も対象 = 取り込まないと決めた file の奥付だけ見る等)
  --no-mail            共有通知の照合 (share_notice_source が渡されたときだけ走る) を省く
  --selftest           合成データだけで検査する (network に出ない)

出す行:
  🔑 その account の token が無い → 承認の案内文 (人が 1 回やる。 承認されるまで出続ける)
  🔒 token が git 管理下に無い (git_tracked: true のときだけ)
  ❓ folder が見えない (404 / 403 = 共有が外れた、 または別 account 宛て)
  🆕 未取得・更新 N 件 → sync の案内文
  ℹ️ Drive から消えた file の件数 (写しからは消さない。 消すかは人が決める)
  📨 共有通知のうち台帳にも ignore_ids にも無い id (share_notice_source 経由)

state (= どの版を取ったか) は写しの中の _shared_drive_state.json。 写しも state もマシンごとに持つ。
download は `.part` に書き、 読み終えてから名前を変える (切れた写しを完成品と取り違えない)。
fail-open: API / network の失敗は ⚠️ 1 行にして他の entry を続ける。 exit は常に 0 (selftest を除く)。
access token は in-memory で refresh し、 credential file に書き戻さない。
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

STATE_NAME = "_shared_drive_state.json"
TIMEOUT = 20
DOWNLOAD_TIMEOUT = 180  # listing と別に長く取る: 大きなスキャン PDF は数十秒の timeout で同じ file の取得が続けて切れた (実測)
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/drive/v3/"

FOLDER_MIME = "application/vnd.google-apps.folder"
EXPORT_MAP = {
    "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
}
DRIVE_ID_RE = re.compile(
    r"(?:drive\.google\.com/(?:drive/(?:u/\d+/)?folders/|file/d/|open\?id=)"
    r"|docs\.google\.com/(?:document|spreadsheets|presentation|forms)/d/)"
    r"([A-Za-z0-9_-]{10,})")


# ---------------------------------------------------------------- pure helpers

def load_registry(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {"folders": [], "share_mail": {}}
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        data = json.loads(text) if text.strip() else {}
    else:
        import yaml  # YAML の台帳だけ PyYAML を使う
        data = yaml.safe_load(text)
    data = data or {}
    data["folders"] = data.get("folders") or []
    data["share_mail"] = data.get("share_mail") or {}
    return data


def _expand(p) -> Path:
    return Path(os.path.expanduser(str(p)))


def resolve_credentials(reg: dict, injected: dict | None = None, oauth_keys=None) -> dict[str, dict]:
    """台帳の credentials に注入分を重ねる (注入が勝つ)。 値が path だけの形も受ける。"""
    out: dict[str, dict] = {}
    for source in (reg.get("credentials") or {}, injected or {}):
        for account, spec in source.items():
            if not isinstance(spec, dict):
                spec = {"path": spec}
            merged = dict(out.get(account, {}))
            merged.update(spec)
            out[account] = merged
    top_keys = oauth_keys or reg.get("oauth_keys")
    for spec in out.values():
        spec["path"] = _expand(spec["path"]) if spec.get("path") else None
        keys = spec.get("oauth_keys") or top_keys
        spec["oauth_keys"] = _expand(keys) if keys else None
        spec["auth"] = spec.get("auth") or ""
        spec["git_tracked"] = bool(spec.get("git_tracked"))
    return out


def safe_name(name: str) -> str:
    """Drive の名前は '/' を含みうる。 path 区切りと衝突しないよう置換し、 '.' / '..' を避ける。"""
    s = name.replace("/", "／").replace("\x00", "").strip()
    if s in ("", ".", ".."):
        s = "_"
    return s


def target_name(f: dict) -> str:
    name = safe_name(f["name"])
    if f.get("mimeType") in EXPORT_MAP:
        ext = EXPORT_MAP[f["mimeType"]][1]
        if not name.lower().endswith(ext):
            name += ext
    return name


def diff_listing(listing: list[dict], state: dict) -> tuple[list[dict], list[str]]:
    """listing (= 今の Drive) と state (= 取った版) を比べる。
    戻り値 = (取るべき file = 新規 or modifiedTime が変わった, Drive から消えた id)。"""
    have = state.get("files", {})
    todo = [f for f in listing
            if f["id"] not in have or have[f["id"]].get("modifiedTime") != f.get("modifiedTime")]
    live = {f["id"] for f in listing}
    gone = [fid for fid in have if fid not in live]
    return todo, gone


def extract_drive_ids(text: str) -> list[str]:
    """本文から folder / file / Docs 系の id を出現順・重複なしで抜く。"""
    seen, out = set(), []
    for m in DRIVE_ID_RE.finditer(text or ""):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            out.append(m.group(1))
    return out


def known_share_ids(reg: dict) -> set[str]:
    """知らせなくてよい id = 台帳の folder_id + share_mail.ignore_ids。"""
    cfg = reg.get("share_mail") or {}
    return ({str(e.get("folder_id")) for e in reg.get("folders") or []}
            | {str(x) for x in cfg.get("ignore_ids") or []})


def share_notice(source: str, subject: str, sender: str, ids: list[str], known: set[str],
                 registry_name: str) -> str | None:
    """共有通知 1 通ぶん。 ids のうち known に無いものがあれば知らせる 1 行を返し、 known に足す
    (同じ id を 2 回知らせない)。 sender は From ヘッダのままでよい (<address> は落とす)。"""
    new = [i for i in ids if i not in known]
    if not new:
        return None
    known.update(new)
    name = re.sub(r"\s*<.*>$", "", sender or "").strip('" ')
    return (f"📨 {source}: 台帳に無い Drive 共有「{(subject or '')[:60]}」"
            f" ({name}、 id {new[0]}) → {registry_name} に足すか ignore_ids へ")


# ---------------------------------------------------------------- Drive REST

class DriveError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


class RestDrive:
    """Drive v3 を標準ライブラリで叩く (client library の無い hook 環境でも動く)。"""

    def access_token(self, cred: dict) -> str:
        tok = json.loads(Path(cred["path"]).read_text())
        if not cred.get("oauth_keys"):
            raise ValueError("oauth_keys が未設定")
        raw = json.loads(Path(cred["oauth_keys"]).read_text())
        keys = raw.get("installed") or raw.get("web") or {}
        data = urllib.parse.urlencode({
            "client_id": keys["client_id"],
            "client_secret": keys["client_secret"],
            "refresh_token": tok["refresh_token"],
            "grant_type": "refresh_token",
        }).encode()
        # urlopen 先は固定の token endpoint (外部入力なし) — audit rule の FP、 以下 nosemgrep
        with urllib.request.urlopen(TOKEN_URL, data, timeout=TIMEOUT) as r:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            return json.load(r)["access_token"]

    def _get(self, url: str, token: str, timeout: int = TIMEOUT):
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            return urllib.request.urlopen(req, timeout=timeout)  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        except urllib.error.HTTPError as e:
            raise DriveError(e.code, f"HTTP {e.code}") from None

    def drive_json(self, path: str, params: dict, token: str) -> dict:
        with self._get(API_BASE + path + "?" + urllib.parse.urlencode(params), token) as r:
            return json.load(r)

    def folder_meta(self, folder_id: str, token: str) -> dict:
        return self.drive_json(f"files/{folder_id}", {
            "fields": "id,name,mimeType,owners(displayName),modifiedTime",
            "supportsAllDrives": "true"}, token)

    def list_tree(self, folder_id: str, token: str) -> list[dict]:
        """folder 以下を再帰で列挙。 file ごとに rel (= 写しの中の相対 path) を付ける。"""
        out, queue = [], [(folder_id, "")]
        while queue:
            fid, prefix = queue.pop(0)
            page = None
            while True:
                params = {
                    "q": f"'{fid}' in parents and trashed = false",
                    "fields": "nextPageToken, files(id,name,mimeType,modifiedTime,size)",
                    "pageSize": "200", "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
                }
                if page:
                    params["pageToken"] = page
                resp = self.drive_json("files", params, token)
                for f in resp.get("files", []):
                    if f["mimeType"] == FOLDER_MIME:
                        queue.append((f["id"], prefix + safe_name(f["name"]) + "/"))
                    elif f["mimeType"].startswith("application/vnd.google-apps.") and f["mimeType"] not in EXPORT_MAP:
                        continue  # form / shortcut 等は落とせない
                    else:
                        f["rel"] = prefix + target_name(f)
                        out.append(f)
                page = resp.get("nextPageToken")
                if not page:
                    break
        return out

    def download(self, f: dict, token: str, dest: Path) -> int:
        if f["mimeType"] in EXPORT_MAP:
            url = (API_BASE + f"files/{f['id']}/export?"
                   + urllib.parse.urlencode({"mimeType": EXPORT_MAP[f["mimeType"]][0]}))
        else:
            url = (API_BASE + f"files/{f['id']}?"
                   + urllib.parse.urlencode({"alt": "media", "supportsAllDrives": "true"}))
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        n = 0
        with self._get(url, token, DOWNLOAD_TIMEOUT) as r, open(tmp, "wb") as out:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                n += len(chunk)
        tmp.replace(dest)
        return n


# ---------------------------------------------------------------- checks

def git_tracked(path: Path) -> bool:
    try:
        r = subprocess.run(["git", "-C", str(path.parent), "ls-files", "--error-unmatch", path.name],
                           capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def commit_hint(path: Path) -> str:
    """token を git に入れる案内。 置き場が repo の中なら「<repo 名> で <相対 path> を commit + push」。"""
    try:
        r = subprocess.run(["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            top = Path(r.stdout.strip())
            rel = os.path.relpath(os.path.realpath(path), os.path.realpath(top))
            return f"{top.name} で {rel} を commit + push"
    except Exception:
        pass
    return f"{path} を git 管理の置き場に移して commit + push"


def read_state(mirror: Path) -> dict:
    try:
        return json.loads((mirror / STATE_NAME).read_text(encoding="utf-8"))
    except Exception:
        return {"files": {}}


def entry_label(entry: dict) -> str:
    return f"{entry.get('id')} ({entry.get('shared_by', '?')} から共有、 {entry.get('project', '-')})"


def check_folder(entry: dict, mode: str, lines: list[str], cfg: dict,
                 only: list[str] | None = None, drive: RestDrive | None = None) -> None:
    """entry 1 つを見て lines に足す。 mode = check / surface / list / sync / fetch。
    cfg = {credentials: resolve_credentials() の戻り値, default_account, sync_command, fetch_to (fetch のとき)}。"""
    drive = drive or RestDrive()
    label = entry_label(entry)
    account = entry.get("account") or cfg.get("default_account")
    if not account:
        lines.append(f"⚠️ {label}: account が未指定")
        return
    cred = (cfg.get("credentials") or {}).get(account)
    if not cred or not cred.get("path"):
        lines.append(f"⚠️ {label}: 未対応の account '{account}'")
        return
    cred_path, auth_cmd = cred["path"], cred.get("auth") or ""
    if not cred_path.exists():
        how = f"1 回だけ承認: {auth_cmd}" if auth_cmd else f"承認して {cred_path} に置く"
        lines.append(f"🔑 {label}: {account} の Drive 読み取り token が無い → {how}")
        return
    if cred.get("git_tracked") and not git_tracked(cred_path):
        lines.append(f"🔒 {label}: token が git に入っていない (他のマシンで読めない) → {commit_hint(cred_path)}")
    try:
        token = drive.access_token(cred)
        drive.folder_meta(entry["folder_id"], token)
        listing = drive.list_tree(entry["folder_id"], token)
    except DriveError as e:
        if e.status in (403, 404):
            lines.append(f"❓ {label}: folder が見えない (HTTP {e.status} = 共有が外れた / {account} 宛てでない)")
        else:
            lines.append(f"⚠️ {label}: Drive API {e}")
        return
    except Exception as e:  # network / invalid_grant 等
        msg = str(e)
        hint = f" → 再承認: {auth_cmd}" if auth_cmd and ("invalid_grant" in msg or "400" in msg) else ""
        lines.append(f"⚠️ {label}: {type(e).__name__}: {msg[:120]}{hint}")
        return

    full = listing
    excl = [str(x) for x in entry.get("exclude") or []]
    if excl:
        listing = [f for f in listing if not any(w in f["rel"] for w in excl)]
    mirror = _expand(entry["mirror"])
    state = read_state(mirror)
    todo, gone = diff_listing(listing, state)
    if only and mode == "sync":
        todo = [f for f in todo if any(w in f["rel"] for w in only)]

    if mode == "fetch":
        # 写しと state に触らず、 名前に語を含む file を別の dir に落とす (exclude した file も対象)。
        # 用途 = 取り込まないと決めた本の奥付だけ確かめる、 など 1 回きりの下見。
        dest_dir = _expand(cfg["fetch_to"])
        hits = [f for f in full if any(w in f["rel"] for w in only or [])]
        if not hits:
            lines.append(f"ℹ️ {label}: 語に合う file が無い ({', '.join(only or [])})")
        for f in hits:
            try:
                n = drive.download(f, token, dest_dir / f["rel"])
            except Exception as e:
                lines.append(f"⚠️ {label}: {f['rel']} を取れない: {e}")
                continue
            lines.append(f"⬇️ {f['rel']} ({n:,} B) → {dest_dir}")
        return

    if mode == "list":
        lines.append(f"📂 {label}: {len(listing)} file → mirror {entry['mirror']}")
        have = state.get("files", {})
        for f in listing:
            mark = "  " if f["id"] in have and have[f["id"]].get("modifiedTime") == f.get("modifiedTime") else "🆕"
            size = f.get("size")
            lines.append(f"   {mark} {f['rel']}  ({int(size):,} B)" if size else f"   {mark} {f['rel']}  (native)")
        return

    if mode == "sync":
        if not todo:
            lines.append(f"✅ {label}: 最新 ({len(listing)} file、 {entry['mirror']})")
        files = state.setdefault("files", {})
        for f in todo:
            try:
                n = drive.download(f, token, mirror / f["rel"])
            except Exception as e:
                lines.append(f"⚠️ {label}: {f['rel']} を取れない: {e}")
                continue
            files[f["id"]] = {"rel": f["rel"], "modifiedTime": f.get("modifiedTime"),
                              "mimeType": f["mimeType"], "bytes": n}
            lines.append(f"⬇️ {f['rel']} ({n:,} B)")
        state["folder_id"] = entry["folder_id"]
        state["synced_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        mirror.mkdir(parents=True, exist_ok=True)
        (mirror / STATE_NAME).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        if todo:
            lines.append(f"📁 {label}: mirror = {entry['mirror']}")
        return

    if todo:
        names = ", ".join(f["rel"] for f in todo[:5]) + (" …" if len(todo) > 5 else "")
        lines.append(f"🆕 {label}: 未取得・更新 {len(todo)} 件 ({names}) → {cfg.get('sync_command')}")
    if gone and mode != "surface":
        lines.append(f"ℹ️ {label}: Drive から消えた file {len(gone)} 件 (mirror には残してある)")


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None, *, registry=None, credentials: dict | None = None, oauth_keys=None,
         default_account: str | None = None, sync_command: str | None = None,
         share_notice_source=None, prog: str | None = None, description: str | None = None,
         drive: RestDrive | None = None) -> int:
    ap = argparse.ArgumentParser(prog=prog, description=description or __doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--surface", action="store_true")
    g.add_argument("--sync", action="store_true")
    g.add_argument("--list", action="store_true")
    g.add_argument("--selftest", action="store_true")
    ap.add_argument("--registry", help="台帳 (YAML / JSON)。 呼び出し側が注入していれば省ける")
    ap.add_argument("--no-mail", action="store_true", help="共有通知の照合を省く")
    ap.add_argument("--only", action="append", default=[], help="--sync で名前にこの語を含む file だけ落とす (複数可)")
    g.add_argument("--fetch-to", metavar="DIR",
                   help="--only の語を含む file を DIR に落とす。 写しと state は変えず、 exclude した file も対象 (1 回きりの下見用)")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.fetch_to and not a.only:
        ap.error("--fetch-to には --only が要る (folder 丸ごとは --sync で)")
    reg_path = _expand(a.registry) if a.registry else (Path(registry) if registry else None)
    if reg_path is None:
        ap.error("--registry が要る")
    mode = ("sync" if a.sync else "fetch" if a.fetch_to else "list" if a.list
            else "surface" if a.surface else "check")
    try:
        reg = load_registry(reg_path)
        cfg = {
            "credentials": resolve_credentials(reg, credentials, oauth_keys),
            "default_account": default_account or reg.get("default_account"),
            "sync_command": sync_command or f"python3 {Path(__file__).resolve()} --registry {reg_path} --sync",
            "fetch_to": a.fetch_to,
        }
    except Exception as e:
        print(f"⚠️ {reg_path.name} を読めない: {e}")
        return 0
    lines: list[str] = []
    for entry in reg["folders"]:
        try:
            check_folder(entry, mode, lines, cfg, a.only, drive)
        except Exception as e:  # 台帳の書き損じ等で 1 entry が落ちても他を続ける
            lines.append(f"⚠️ {entry_label(entry) if isinstance(entry, dict) else entry}: "
                         f"{type(e).__name__}: {str(e)[:120]}")
    if share_notice_source and not a.no_mail and mode in ("check", "surface"):
        share_notice_source(reg, lines)
    if lines:
        print("\n".join(lines))
    return 0


# ---------------------------------------------------------------- selftest

class _FakeDrive(RestDrive):
    """network に出ない Drive。 listings = {folder_id: [file dict]}、 errors = {folder_id: 例外}。"""

    def __init__(self, listings: dict, errors: dict | None = None, payload: bytes = b"xyz"):
        self.listings, self.errors, self.payload = listings, errors or {}, payload
        self.downloaded: list[str] = []

    def access_token(self, cred: dict) -> str:
        return "fixture-token"

    def folder_meta(self, folder_id: str, token: str) -> dict:
        if folder_id in self.errors:
            raise self.errors[folder_id]
        return {"id": folder_id}

    def list_tree(self, folder_id: str, token: str) -> list[dict]:
        return [dict(f, rel=f.get("rel") or target_name(f)) for f in self.listings[folder_id]]

    def download(self, f: dict, token: str, dest: Path) -> int:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.payload)
        self.downloaded.append(f["rel"])
        return len(self.payload)


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def selftest() -> int:
    ok = True

    def check(cond, name):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name)
        ok = ok and bool(cond)

    # -- 差分と名前
    listing = [
        {"id": "a", "name": "p1.pdf", "mimeType": "application/pdf", "modifiedTime": "t1"},
        {"id": "b", "name": "p2.pdf", "mimeType": "application/pdf", "modifiedTime": "t2"},
        {"id": "c", "name": "memo", "mimeType": "application/vnd.google-apps.document", "modifiedTime": "t3"},
    ]
    state = {"files": {"a": {"modifiedTime": "t1"}, "b": {"modifiedTime": "t0"}, "z": {"modifiedTime": "t9"}}}
    todo, gone = diff_listing(listing, state)
    check([f["id"] for f in todo] == ["b", "c"], "diff: 更新 (b) と新規 (c) を取り、 同版 (a) は取らない")
    check(gone == ["z"], "diff: Drive から消えた id を返す")
    check(diff_listing(listing, {"files": {}})[0] == listing, "diff: state 無し = 全件")
    check(target_name(listing[2]) == "memo.pdf", "native doc は .pdf で書き出す")
    check(safe_name("a/b") == "a／b" and safe_name("..") == "_", "名前の '/' と '..' を無害化")

    # -- 共有通知
    fid1, fid2, fid3 = "fixtureFolderId0001", "fixtureDocId0002", "fixtureFileId0003"
    body = (f"scan\nhttps://drive.google.com/drive/folders/{fid1}?usp=sharing&ts=1\n"
            f"https://docs.google.com/document/d/{fid2}/edit 同じ "
            f"https://drive.google.com/drive/folders/{fid1}\n"
            f"https://drive.google.com/file/d/{fid3}/view short https://drive.google.com/file/d/tooShort/")
    check(extract_drive_ids(body) == [fid1, fid2, fid3], "本文から folder / doc / file の id を重複なしで抜く (短すぎる id は拾わない)")
    reg = {"folders": [{"folder_id": fid1}], "share_mail": {"ignore_ids": [fid3]}}
    known = known_share_ids(reg)
    check(known == {fid1, fid3}, "既知 id = 台帳の folder_id + ignore_ids")
    line = share_notice("src", "S" * 80, '"Fixture Sender" <sender@example.invalid>', [fid1, fid2], known, "reg.yaml")
    check(line == f"📨 src: 台帳に無い Drive 共有「{'S' * 60}」 (Fixture Sender、 id {fid2}) → reg.yaml に足すか ignore_ids へ",
          "通知 1 行: 未知 id・件名 60 字・差出人の表示名")
    check(fid2 in known and share_notice("src", "x", "y", [fid2], known, "reg.yaml") is None,
          "同じ id は 2 回知らせない")
    check(share_notice("src", "x", "y", [fid1, fid3], known_share_ids(reg), "r") is None, "既知 id だけなら知らせない")

    with tempfile.TemporaryDirectory(prefix="sdfw-selftest-") as tmp:
        root = Path(tmp)

        # -- 台帳と credential
        check(load_registry(root / "none.json") == {"folders": [], "share_mail": {}}, "台帳が無ければ空")
        (root / "null.json").write_text('{"folders": null}', encoding="utf-8")
        check(load_registry(root / "null.json")["folders"] == [], "folders: null を空として読む")
        reg_json = {"credentials": {"acct-a": {"path": "~/x.json", "auth": "old"}, "acct-b": "/tmp/b.json"},
                    "oauth_keys": "/tmp/keys.json"}
        creds = resolve_credentials(reg_json, {"acct-a": {"auth": "new", "git_tracked": True}})
        check(creds["acct-a"]["auth"] == "new" and creds["acct-a"]["git_tracked"]
              and creds["acct-a"]["path"] == Path.home() / "x.json", "credential: 注入が台帳に勝ち、 ~ を展開")
        check(creds["acct-b"]["path"] == Path("/tmp/b.json") and creds["acct-b"]["oauth_keys"] == Path("/tmp/keys.json")
              and not creds["acct-b"]["git_tracked"], "credential: path だけの形 + top-level oauth_keys")
        check(resolve_credentials(reg_json, oauth_keys="/tmp/other.json")["acct-b"]["oauth_keys"] == Path("/tmp/other.json"),
              "credential: 注入した oauth_keys が台帳の top-level に勝つ")

        # -- check_folder (fake Drive)
        cred_file = root / "cred.json"
        cred_file.write_text("{}", encoding="utf-8")
        cfg = {"credentials": resolve_credentials({}, {"acct-a": {"path": cred_file, "auth": "AUTH-CMD"},
                                                        "acct-missing": {"path": root / "nope.json", "auth": "AUTH-CMD"},
                                                        "acct-git": {"path": cred_file, "git_tracked": True}}),
               "default_account": "acct-a", "sync_command": "SYNC-CMD"}
        mirror = root / "mirror"
        files = [
            {"id": "f1", "name": "one.pdf", "mimeType": "application/pdf", "modifiedTime": "t1", "size": "1234"},
            {"id": "f2", "name": "two", "mimeType": "application/vnd.google-apps.document", "modifiedTime": "t2"},
            {"id": "f3", "name": "skip-me.pdf", "mimeType": "application/pdf", "modifiedTime": "t3", "size": "9"},
        ]
        fake = _FakeDrive({"F": files}, {"GONE": DriveError(404, "HTTP 404"), "BAD": ValueError("invalid_grant")})
        base = {"id": "fx", "shared_by": "someone", "project": "proj", "folder_id": "F",
                "mirror": str(mirror), "exclude": ["skip-me"]}

        def run(entry, mode, only=None):
            out: list[str] = []
            check_folder(entry, mode, out, cfg, only, fake)
            return out

        label = "fx (someone から共有、 proj)"
        check(run(dict(base, account="acct-x"), "check") == [f"⚠️ {label}: 未対応の account 'acct-x'"], "未対応の account")
        check(run(dict(base, account="acct-missing"), "check")
              == [f"🔑 {label}: acct-missing の Drive 読み取り token が無い → 1 回だけ承認: AUTH-CMD"], "token が無い → 承認の案内")
        check(run(dict(base, folder_id="GONE"), "check")
              == [f"❓ {label}: folder が見えない (HTTP 404 = 共有が外れた / acct-a 宛てでない)"], "404 → 見えない (account 省略は default)")
        check(run(dict(base, folder_id="BAD"), "check")
              == [f"⚠️ {label}: ValueError: invalid_grant → 再承認: AUTH-CMD"], "invalid_grant → 再承認の案内")
        got = run(dict(base, account="acct-git"), "surface")
        check(len(got) == 2 and got[0].startswith(f"🔒 {label}: token が git に入っていない")
              and "commit + push" in got[0], "git_tracked: true で git 外の token を知らせる")
        check(run(base, "check") == [f"🆕 {label}: 未取得・更新 2 件 (one.pdf, two.pdf) → SYNC-CMD"],
              "check: 未取得を件数と名前で出し、 exclude の語を含む file は数えない")
        listed = run(base, "list")
        check(listed == [f"📂 {label}: 2 file → mirror {mirror}", "   🆕 one.pdf  (1,234 B)", "   🆕 two.pdf  (native)"],
              "list: 中身と未取得の印")
        synced = run(base, "sync", only=["one"])
        check(fake.downloaded == ["one.pdf"] and synced[0] == "⬇️ one.pdf (3 B)", "sync --only: 語を含む file だけ落とす")
        st = read_state(mirror)
        check(set(st["files"]) == {"f1"} and st["folder_id"] == "F", "sync: 取った版を state に書く")
        run(base, "sync")
        check(run(base, "sync") == [f"✅ {label}: 最新 (2 file、 {mirror})"], "sync: 取り終えたら最新")
        fetch_dir = root / "fetched"
        state_before = json.dumps(read_state(mirror), sort_keys=True)
        fake.downloaded.clear()
        out_fetch: list[str] = []
        check_folder(base, "fetch", out_fetch, dict(cfg, fetch_to=str(fetch_dir)), ["skip-me"], fake)
        check(fake.downloaded == ["skip-me.pdf"] and (fetch_dir / "skip-me.pdf").exists()
              and out_fetch == [f"⬇️ skip-me.pdf (3 B) → {fetch_dir}"],
              "fetch: exclude した file も語で指定すれば別 dir に落とす")
        check(json.dumps(read_state(mirror), sort_keys=True) == state_before and not (mirror / "skip-me.pdf").exists(),
              "fetch: 写しと state は変えない")
        out_none: list[str] = []
        check_folder(base, "fetch", out_none, dict(cfg, fetch_to=str(fetch_dir)), ["no-such"], fake)
        check(out_none == [f"ℹ️ {label}: 語に合う file が無い (no-such)"], "fetch: 合う file が無ければ 1 行で知らせる")
        fake.listings["F"] = files[:1]
        check(run(base, "check") == [f"ℹ️ {label}: Drive から消えた file 1 件 (mirror には残してある)"]
              and run(base, "surface") == [], "消えた file は check で件数だけ、 surface では出さない")

        # -- RestDrive.download: 経路の選び分けと .part
        dest = root / "dl" / "doc.pdf"
        seen_during_read: list[bool] = []

        class _Watched(_FakeResponse):
            def read(self, *a):
                seen_during_read.append(dest.exists())
                return super().read(*a)

        class _Captured(RestDrive):
            def __init__(self):
                self.urls: list[str] = []

            def _get(self, url, token, timeout=TIMEOUT):
                self.urls.append(url)
                return _Watched(b"payload")

        cap = _Captured()
        n = cap.download({"id": "D1", "mimeType": "application/vnd.google-apps.document"}, "t", dest)
        cap.download({"id": "B1", "mimeType": "application/pdf"}, "t", root / "dl" / "bin.pdf")
        check(n == 7 and dest.read_bytes() == b"payload" and not dest.with_name("doc.pdf.part").exists()
              and seen_during_read and not seen_during_read[0],
              "download: 読み終えるまで本名の file を作らず、 .part を本名に変える")
        check("/files/D1/export?" in cap.urls[0] and "alt=media" in cap.urls[1], "download: native は export、 他は alt=media")

        # -- main: 台帳の読み込みと通知 source の呼び分け
        reg_file = root / "reg.json"
        reg_file.write_text(json.dumps({"folders": [], "share_mail": {}}), encoding="utf-8")
        calls: list[str] = []

        def source(r, lines):
            calls.append("x")
            lines.append("📨 fixture")

        def run_main(*argv, **kw):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(list(argv), registry=reg_file, share_notice_source=source, **kw)
            return rc, buf.getvalue()

        rc, out = run_main("--surface")
        check(rc == 0 and out == "📨 fixture\n" and calls == ["x"], "main: surface で通知 source を呼ぶ")
        run_main("--surface", "--no-mail")
        run_main("--list")
        check(calls == ["x"], "main: --no-mail と --list では通知 source を呼ばない")
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                main(["--registry", str(reg_file), "--fetch-to", str(root / "x")])
            refused = False
        except SystemExit:
            refused = True
        check(refused, "main: --fetch-to は --only なしを断る (folder 丸ごとを別 dir に落とさない)")
        broken = root / "broken.json"
        broken.write_text("{", encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--registry", str(broken)])
        check(rc == 0 and buf.getvalue().startswith("⚠️ broken.json を読めない"), "main: 壊れた台帳は ⚠️ 1 行で exit 0")
        reg_file.write_text(json.dumps({"folders": [{"id": "no-mirror", "folder_id": "F", "account": "acct-a"}]}),
                            encoding="utf-8")
        rc, out = run_main("--no-mail", credentials={"acct-a": {"path": cred_file}}, drive=_FakeDrive({"F": files}))
        check(rc == 0 and out.startswith("⚠️ no-mirror (? から共有、 -): KeyError"), "main: 書き損じた entry は ⚠️ にして続ける")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
