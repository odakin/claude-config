#!/usr/bin/env python3
"""gmail_read.py — Gmail を**読むだけ**の最小 helper (service の組み立て / thread の message 列 / 本文の取り出し)。

なぜ存在するか:
  台帳に mail を記録する道具と、 未記録の返事を見張る検出器は、 同じ「thread を引いて message を日付順に並べ、
  本文を text にする」 を要る。 それぞれが Gmail API の呼び方を持つと、 HTML-only の mail を「本文空」 と読む
  (text/plain が無い = 空、 の飛躍) ような取りこぼしが片方にだけ残る。 読む側の最小の共通部品を 1 か所に置く。

前提 (= 認証の置き場): <creds_dir>/<account>/credentials.json (access/refresh token) と
  <creds_dir>/<account>/gcp-oauth.keys.json (無ければ <creds_dir>/gcp-oauth.keys.json) — OAuth の "installed" client。
  google-api-python-client / google-auth が要る (無い環境では build_service が None を返す = 呼び手は fail-open)。

使い方:
    from gmail_read import load_account_creds, build_service, service_for, thread_messages, thread_of_message, walk_text
    svc = build_service(load_account_creds(Path.home() / ".gmail-mcp", "alias"))
    svc = service_for(Path.home() / ".gmail-mcp", "alias", label="my-detector")   # 失敗は stderr に 1 行、 None (検出器向け)
    msgs = thread_messages(svc, thread_id, full=True)   # None = 引けなかった (404 / auth / 一時失敗)
    python3 gmail_read.py                                # selftest (API に触らない = 本文の取り出しと並べ替えだけ)
"""
from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path

TOKEN_URI_DEFAULT = "https://oauth2.googleapis.com/token"


def _read_creds(creds_dir: Path, account: str) -> dict:
    """{cred, oauth} を読む (読めなければ例外)。 OAuth client は account の dir に無ければ creds_dir 直下の共有 file、
    形は "installed" (desktop app) でも "web" でも受ける。"""
    d = Path(creds_dir) / account
    cred = json.loads((d / "credentials.json").read_text(encoding="utf-8"))
    kp = d / "gcp-oauth.keys.json"
    if not kp.exists():
        kp = Path(creds_dir) / "gcp-oauth.keys.json"
    data = json.loads(kp.read_text(encoding="utf-8"))
    oauth = data.get("installed") or data.get("web") or {}
    return {"cred": cred, "oauth": oauth}


def load_account_creds(creds_dir: Path, account: str) -> dict | None:
    """{cred, oauth} を読む。 file が無い・読めなければ None (= この machine にその account の認証が無い)。"""
    try:
        return _read_creds(creds_dir, account)
    except Exception:
        return None


def build_service(blob: dict | None):
    """gmail v1 の service。 認証 blob が無い / client library が無い → None。"""
    if not blob:
        return None
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        return None
    cred, oauth = blob["cred"], blob["oauth"]
    scope = cred.get("scope")
    creds = Credentials(token=cred.get("access_token"), refresh_token=cred.get("refresh_token"),
                        token_uri=oauth.get("token_uri") or TOKEN_URI_DEFAULT,
                        client_id=oauth.get("client_id"), client_secret=oauth.get("client_secret"),
                        scopes=scope.split(" ") if isinstance(scope, str) and scope else None)
    if not creds.valid and creds.refresh_token:   # access token が無い / 期限切れと分かっている時だけ先に更新する
        from google.auth.transport.requests import Request
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def service_for(creds_dir: Path, account: str, label: str | None = None, raise_errors: bool = False):
    """検出器向けの 1 行版。 認証 file が無ければ None (= その account はこの machine に無い、 黙って skip)。
    読めない・組み立てに失敗したら stderr に `⚠️  <label>: <account> 認証失敗 (<理由>)` を 1 行出して None
    (= 1 account の失敗で検出器全体を落とさない)。 raise_errors=True なら例外をそのまま上げる (書き込む道具向け)。"""
    if not (Path(creds_dir) / account / "credentials.json").exists():
        return None
    try:
        return build_service(_read_creds(creds_dir, account))
    except Exception as e:
        if raise_errors:
            raise
        print(f"⚠️  {label or 'gmail_read'}: {account} 認証失敗 ({e})", file=sys.stderr)
        return None


def header(msg: dict, name: str) -> str:
    for h in msg.get("payload", {}).get("headers", []) or []:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def strip_html(markup: str) -> str:
    """依存なしの最小 de-tag (読める text にするだけ、 描画はしない)。"""
    from html import unescape
    markup = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", markup)
    markup = re.sub(r"(?i)<(?:br|/p|/div|/tr|/li|/h[1-6])\s*/?>", "\n", markup)
    text = unescape(re.sub(r"(?s)<[^>]+>", "", markup))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def walk_text(payload: dict) -> str:
    """payload を再帰して本文を取り出す。 text/plain を優先し、 無ければ text/html を de-tag して返す
    (= HTML-only / S/MIME 署名 mail を「本文空」 と読まない)。"""
    plain: list[str] = []
    html: list[str] = []

    def _walk(p: dict) -> None:
        mime = p.get("mimeType", "")
        data = p.get("body", {}).get("data")
        if data and (mime.startswith("text/plain") or mime.startswith("text/html")):
            try:
                txt = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "ignore")
            except Exception:
                txt = ""
            (plain if mime.startswith("text/plain") else html).append(txt)
        for part in p.get("parts", []) or []:
            _walk(part)

    _walk(payload or {})
    if "\n".join(plain).strip():
        return "\n".join(x for x in plain if x)
    if "\n".join(html).strip():
        return strip_html("\n".join(x for x in html if x))
    return ""


def normalize_messages(raw_messages: list[dict], full: bool) -> list[dict]:
    """API の thread.messages → [{id, from, to, cc, bcc, subject, date, internalDate, body}] を internalDate 昇順で。

    bcc は自分発の控えにだけ残る header (= 宛先が Bcc だけの送信で相手を知る唯一の手がかり)。
    """
    out = []
    for m in raw_messages or []:
        out.append({
            "id": m.get("id"), "internalDate": m.get("internalDate", "0"),
            "from": header(m, "From"), "to": header(m, "To"), "cc": header(m, "Cc"), "bcc": header(m, "Bcc"),
            "subject": header(m, "Subject") or "(no subject)", "date": header(m, "Date"),
            "body": walk_text(m.get("payload", {})) if full else "",
        })
    out.sort(key=lambda x: int(x.get("internalDate") or 0))
    return out


def thread_messages(service, thread_id: str, full: bool = True,
                    metadata_headers=("From", "To", "Cc", "Subject", "Date")) -> list[dict] | None:
    """thread の message 列 (昇順)。 None = 引けなかった (404 / 認証 / 一時失敗 = 呼び手は「未記録」 に倒さない)。"""
    if service is None:
        return None
    kwargs = {"userId": "me", "id": thread_id, "format": "full" if full else "metadata"}
    if not full:
        kwargs["metadataHeaders"] = list(metadata_headers)
    try:
        raw = service.users().threads().get(**kwargs).execute()
    except Exception:
        return None
    return normalize_messages(raw.get("messages", []) or [], full)


def thread_of_message(service, message_id: str) -> str | None:
    """message id → その message の threadId (失敗 = None)。 返信の messageId で threads.get すると 404 になるので、 その引き直し用。"""
    if service is None:
        return None
    try:
        m = service.users().messages().get(userId="me", id=message_id, format="minimal").execute()
        t = m.get("threadId")
        return t if isinstance(t, str) and t else None
    except Exception:
        return None


def selftest() -> int:
    fails = []

    def expect(label, cond):
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
        if not cond:
            fails.append(label)

    def b64(s: str) -> str:
        return base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii").rstrip("=")

    plain = {"mimeType": "multipart/alternative", "parts": [
        {"mimeType": "text/plain", "body": {"data": b64("本文\n> 引用")}},
        {"mimeType": "text/html", "body": {"data": b64("<p>本文</p>")}}]}
    expect("walk_text: text/plain を優先", walk_text(plain) == "本文\n> 引用")
    html_only = {"mimeType": "text/html", "body": {"data": b64("<div>Hello<br>World</div><style>x{}</style>")}}
    expect("walk_text: HTML-only は de-tag して返す (本文空にしない)", walk_text(html_only) == "Hello\nWorld")
    expect("walk_text: 空 payload は空", walk_text({}) == "")
    raw = [{"id": "b", "internalDate": "200", "payload": {"headers": [{"name": "From", "value": "B <b@x>"}, {"name": "Subject", "value": "s"}]}},
           {"id": "a", "internalDate": "100", "payload": {"headers": [{"name": "from", "value": "A <a@x>"}]}}]
    msgs = normalize_messages(raw, full=False)
    expect("normalize_messages: internalDate 昇順・header 名は大小無視・件名の既定", [m["id"] for m in msgs] == ["a", "b"]
           and msgs[0]["from"] == "A <a@x>" and msgs[0]["subject"] == "(no subject)" and msgs[1]["body"] == "")
    expect("thread_messages / thread_of_message: service 無しは None", thread_messages(None, "x") is None and thread_of_message(None, "x") is None)
    expect("load_account_creds: 無い account は None", load_account_creds(Path("/nonexistent-dir-for-selftest"), "x") is None)
    import io
    import tempfile
    from contextlib import redirect_stderr
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "acct-a").mkdir()
        (root / "acct-a" / "credentials.json").write_text('{"access_token": "t", "refresh_token": "r"}', encoding="utf-8")
        (root / "gcp-oauth.keys.json").write_text('{"web": {"client_id": "c", "client_secret": "s"}}', encoding="utf-8")
        blob = load_account_creds(root, "acct-a")
        expect("load_account_creds: 共有の OAuth client (web 形) を読む", blob is not None and blob["oauth"].get("client_id") == "c")
        expect("service_for: 認証 file の無い account は黙って None", service_for(root, "acct-missing", label="t") is None)
        (root / "acct-b").mkdir()
        (root / "acct-b" / "credentials.json").write_text("{broken", encoding="utf-8")
        err = io.StringIO()
        with redirect_stderr(err):
            got = service_for(root, "acct-b", label="selftest")
        expect("service_for: 壊れた認証は stderr に 1 行 + None", got is None and "selftest: acct-b 認証失敗" in err.getvalue())
        raised = False
        try:
            service_for(root, "acct-b", raise_errors=True)
        except Exception:
            raised = True
        expect("service_for: raise_errors=True は例外を上げる", raised)
    print(f"selftest: {'ALL PASS' if not fails else 'FAIL ' + str(len(fails))}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(selftest())
