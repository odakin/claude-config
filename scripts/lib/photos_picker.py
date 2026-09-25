#!/usr/bin/env python3
"""photos_picker.py — Google Photos Picker API の client (session を作る → 本人が URL を開いて写真を選ぶ → 選ばれた写真を列挙・download。 python3 photos_picker.py で selftest)

Google Photos の Library API は外部 app から本人の写真を列挙できない (2025-03-31 以降、 app が作った写真だけ)。
手元に写真を持ってくる唯一の API 経路が Picker = 本人が画面で選んだ写真だけが読める。 流れ:

  1. create_session()        → pickerUri を本人に渡す (その Google アカウントでログインしたブラウザで開く)
  2. wait(...)               → 本人が選んで「完了」 を押すまで poll (session の期限は API が返す timeoutIn)
  3. media_items(sid)        → 選ばれた項目 (既定は写真だけ、 動画は除く)。 createTime は UTC の ISO 文字列
  4. download(base_url)      → 原寸の bytes (baseUrl に "=d" を付ける)

token は node の googleapis 形式 (access_token / refresh_token / expiry_date [ms] / scope) の json を
load_credentials() で読む。 ⚠️ google-auth の Credentials に expiry を渡さないと、 期限切れの token でも
valid 扱いになって refresh されず 401 になる (実測) = expiry_date を必ず渡す。

使い方 (呼び出し側):
  creds = load_credentials(token_path, oauth_path, "token の発行手順")
  pk = Picker(lambda: creds.token)
  s = pk.create_session(); print(s["pickerUri"]); pk.wait(s["id"], s["poll_s"], time.time() + s["timeout_s"])
  for it in pk.media_items(s["id"]): data = pk.download(it["baseUrl"])

通信 (requests 互換の get/post) は引数で差し替えられる = selftest は偽の通信で回す。
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

BASE = "https://photospicker.googleapis.com/v1"


def load_credentials(token_path: Path, oauth_path: Path, auth_hint: str, write_back: bool = True):
    """googleapis 形式の token json から Credentials を作り、 期限切れなら refresh する。

    write_back=True なら refresh した access_token と expiry_date を token file に書き戻す。
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token_path, oauth_path = Path(token_path), Path(oauth_path)
    if not token_path.exists():
        sys.exit(f"OAuth token 未発行: {token_path}\n  先に: {auth_hint}")
    tok = json.loads(token_path.read_text())
    oauth = json.loads(oauth_path.read_text())["installed"]
    expiry = None
    if tok.get("expiry_date"):
        expiry = dt.datetime.fromtimestamp(tok["expiry_date"] / 1000, tz=dt.timezone.utc).replace(tzinfo=None)
    creds = Credentials(
        token=tok.get("access_token"), refresh_token=tok.get("refresh_token"),
        token_uri=oauth.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=oauth["client_id"], client_secret=oauth["client_secret"],
        scopes=(tok.get("scope") or "").split(), expiry=expiry,
    )
    if not creds.valid:
        creds.refresh(Request())
        if write_back:
            tok["access_token"] = creds.token
            if creds.expiry:
                tok["expiry_date"] = int(creds.expiry.replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
            token_path.write_text(json.dumps(tok, indent=2))
    return creds


def seconds(duration: str) -> float:
    """API の duration 文字列 ("5s" / "1800.5s") を秒に。"""
    return float(str(duration).rstrip("s"))


class Picker:
    def __init__(self, token_fn, http=None):
        if http is None:
            import requests as http  # 使う時だけ読む
        self.http = http
        self.token_fn = token_fn

    def _h(self, extra: dict | None = None) -> dict:
        h = {"Authorization": f"Bearer {self.token_fn()}"}
        if extra:
            h.update(extra)
        return h

    def create_session(self) -> dict:
        r = self.http.post(f"{BASE}/sessions", headers=self._h({"Content-Type": "application/json"}),
                           json={}, timeout=30)
        r.raise_for_status()
        s = r.json()
        pc = s.get("pollingConfig", {})
        s["poll_s"] = seconds(pc.get("pollInterval", "5s"))
        s["timeout_s"] = seconds(pc.get("timeoutIn", "600s"))
        return s

    def wait(self, session_id: str, poll_s: float, deadline: float, sleep=time.sleep, now=time.time) -> dict:
        """本人が選び終わる (mediaItemsSet) まで poll。 deadline (epoch 秒) を過ぎたら TimeoutError。

        通信の一時的な失敗 (接続・TLS handshake の timeout) は次の poll で読み直す = 1 回の失敗で
        session ごと捨てない (session id は呼び出し側に残らないので、 落ちると本人が選び直しになる。
        実測)。 requests の例外は OSError の子。 HTTP の error 応答 (401 等) は下の
        raise_for_status で従来どおり止まる。
        """
        while now() < deadline:
            try:
                r = self.http.get(f"{BASE}/sessions/{session_id}", headers=self._h(), timeout=30)
            except OSError as e:
                print(f"  (poll の通信が失敗、 次の poll で読み直す: {type(e).__name__})", file=sys.stderr, flush=True)
                sleep(poll_s)
                continue
            r.raise_for_status()
            s = r.json()
            if s.get("mediaItemsSet"):
                return s
            sleep(poll_s)
        raise TimeoutError("Picker の選択が期限内に終わらなかった (URL を開き直すなら session から作り直す)")

    def media_items(self, session_id: str, photos_only: bool = True) -> list[dict]:
        out: list[dict] = []
        token = None
        while True:
            params = {"sessionId": session_id, "pageSize": 100}
            if token:
                params["pageToken"] = token
            r = self.http.get(f"{BASE}/mediaItems", headers=self._h(), params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            for it in data.get("mediaItems", []):
                if photos_only and it.get("type") != "PHOTO":
                    continue
                mf = it.get("mediaFile", {})
                out.append({"id": it["id"], "createTime": it["createTime"], "type": it.get("type"),
                            "filename": mf.get("filename"), "baseUrl": mf.get("baseUrl"),
                            "mimeType": mf.get("mimeType")})
            token = data.get("nextPageToken")
            if not token:
                return out

    def download(self, base_url: str) -> bytes:
        r = self.http.get(f"{base_url}=d", headers=self._h(), timeout=120)
        r.raise_for_status()
        return r.content


def taken_at(item: dict, tz) -> dt.datetime:
    """createTime (UTC の ISO、 末尾 Z) を tz の aware datetime に。 python 3.9 の fromisoformat は Z を読めない。"""
    return dt.datetime.fromisoformat(item["createTime"].replace("Z", "+00:00")).astimezone(tz)


# ---------------------------------------------------------------- selftest

class _Resp:
    def __init__(self, data=None, content=b""):
        self._d, self.content = data, content

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


class _FakeHttp:
    """URL と pageToken で応答を返す偽の通信。 呼ばれた URL を記録する。"""

    def __init__(self, polls_until_set=2, poll_failures=0):
        self.calls, self.polls, self.until, self.fail = [], 0, polls_until_set, poll_failures

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("POST", url, headers))
        return _Resp({"id": "S1", "pickerUri": "https://example.invalid/pick/S1",
                      "pollingConfig": {"pollInterval": "5s", "timeoutIn": "1799.5s"}})

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append(("GET", url, dict(params or {})))
        if url.endswith("/sessions/S1"):
            if self.fail:
                self.fail -= 1
                raise TimeoutError("handshake timed out")  # socket.timeout と同じ OSError の子
            self.polls += 1
            return _Resp({"mediaItemsSet": self.polls >= self.until})
        if url.endswith("/mediaItems"):
            page2 = (params or {}).get("pageToken") == "P2"
            items = ([{"id": "c", "createTime": "2030-01-02T03:04:05Z", "type": "PHOTO",
                       "mediaFile": {"filename": "c.jpg", "baseUrl": "https://example.invalid/c", "mimeType": "image/jpeg"}}]
                     if page2 else
                     [{"id": "a", "createTime": "2030-01-02T01:00:00Z", "type": "PHOTO",
                       "mediaFile": {"filename": "a.jpg", "baseUrl": "https://example.invalid/a", "mimeType": "image/jpeg"}},
                      {"id": "v", "createTime": "2030-01-02T01:30:00Z", "type": "VIDEO",
                       "mediaFile": {"filename": "v.mp4", "baseUrl": "https://example.invalid/v", "mimeType": "video/mp4"}}])
            return _Resp({"mediaItems": items, **({} if page2 else {"nextPageToken": "P2"})})
        if url.endswith("=d"):
            return _Resp(content=b"BYTES:" + url.encode())
        raise AssertionError(f"想定外の URL {url}")


def selftest() -> int:
    fails = []

    def check(cond, name):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    http = _FakeHttp(polls_until_set=3)
    pk = Picker(lambda: "TKN", http=http)
    s = pk.create_session()
    check(s["pickerUri"].endswith("/S1") and s["poll_s"] == 5.0 and abs(s["timeout_s"] - 1799.5) < 1e-9,
          "session の pickerUri と poll 間隔・期限を秒で返す")
    check(http.calls[0][2]["Authorization"] == "Bearer TKN", "token を Bearer で付ける")
    slept = []
    pk.wait("S1", 5.0, deadline=10**12, sleep=slept.append)
    check(http.polls == 3 and slept == [5.0, 5.0], "選び終わる (mediaItemsSet) まで poll し、 その間だけ待つ")
    flaky, slept2 = _FakeHttp(polls_until_set=1, poll_failures=2), []
    Picker(lambda: "T", http=flaky).wait("S1", 5.0, deadline=10**12, sleep=slept2.append)
    check(flaky.polls == 1 and slept2 == [5.0, 5.0], "poll の通信の一時的な失敗は待って読み直す (session を捨てない)")
    clock = iter([0.0, 1.0, 2.0, 3.0])
    try:
        Picker(lambda: "T", http=_FakeHttp(polls_until_set=99)).wait("S1", 1.0, deadline=2.5,
                                                                     sleep=lambda s: None, now=lambda: next(clock))
        check(False, "期限を過ぎたら TimeoutError")
    except TimeoutError:
        check(True, "期限を過ぎたら TimeoutError")
    items = pk.media_items("S1")
    check([i["id"] for i in items] == ["a", "c"], "nextPageToken が尽きるまで読み、 写真以外 (動画) は除く")
    check(len(pk.media_items("S1", photos_only=False)) == 3, "photos_only=False なら動画も返す")
    check(pk.download("https://example.invalid/a") == b"BYTES:https://example.invalid/a=d", "原寸は baseUrl に =d を付けて取る")
    jst = dt.timezone(dt.timedelta(hours=9))
    check(taken_at(items[1], jst).strftime("%Y-%m-%d %H:%M") == "2030-01-02 12:04", "createTime (Z 付き UTC) を現地時刻に直す")
    print("photos_picker selftest:", "ALL PASS" if not fails else f"FAIL {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(selftest())
