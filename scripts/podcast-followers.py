#!/usr/bin/env python3
"""Read podcast follower counts using owner-supplied sessions, without a browser.

Standard library only. No browser-cookie discovery; no credential output.
save-auth accepts hidden interactive input. Keep auth-dir outside version control.
Session expiry requires the owner to sign in and replace the saved fields.
Unofficial routes and schemas: openpodcast/spotify-connector (authentication,
metadata), openpodcast/apple-connector (showTrendsV2), openpodcast/api
(fixtures/appleTrendsFollowers*.json). Amazon uses the dashboard's
POST /api/metrics/podcast with followsAggregate. API errors are never zero.
"""
from __future__ import annotations
import argparse
import base64
import datetime as dt
import hashlib
import json
import math
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

FIELDS = {"spotify": ("sp_dc", "sp_key"), "amazon": ("cookie", "csrf_token"),
          "apple": ("myacinfo", "itctx")}
HOSTS = {"spotify": {"accounts.spotify.com", "generic.wg.spotify.com"},
         "amazon": {"podcasters.amazon.com"}, "apple": {"podcastsconnect.apple.com"}}
SPOTIFY_CLIENT = "05a1371ee5194c27860b3ff3ff3979d2"  # Public dashboard client


class ReadError(Exception):
    """Only static, non-sensitive messages belong in this exception."""


def api_has_error(obj):
    error = obj.get("error")
    # Amazon includes this empty envelope even on a successful metrics response.
    if error == {"errors": []}:
        error = None
    return bool(error or obj.get("errors"))


def count(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ReadError("metric_missing")
    if isinstance(value, str) and not re.fullmatch(r"[0-9]+", value):
        raise ReadError("metric_invalid")
    n = float(value)
    if not math.isfinite(n) or n < 0 or n != int(n):
        raise ReadError("metric_invalid")
    return int(n)


def validate_fields(site, fields):
    if site not in FIELDS or not isinstance(fields, dict) or set(fields) != set(FIELDS[site]):
        raise ReadError("auth_fields_invalid")
    for key, value in fields.items():
        if not isinstance(value, str) or not value or len(value) > 50000:
            raise ReadError("auth_fields_invalid")
        if any(ord(c) < 32 or ord(c) > 126 for c in value) or (key != "cookie" and ";" in value):
            raise ReadError("auth_fields_invalid")
    return dict(fields)


def auth_root(root, create=False):
    if root.is_symlink():
        raise ReadError("auth_dir_symlink")
    if create:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        st = root.stat()
    except FileNotFoundError:
        raise ReadError("auth_missing") from None
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ReadError("auth_dir_permissions")


def save_auth(root, site, fields):
    fields = validate_fields(site, fields)
    serialized = json.dumps({"version": 1, "site": site, "fields": fields})
    if len(serialized.encode()) > 65536:
        raise ReadError("auth_file_too_large")
    auth_root(root, create=True)
    path = root / (site + ".json")
    repo = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if repo.returncode == 0:
        ignored = subprocess.run(["git", "-C", repo.stdout.strip(), "check-ignore", "--quiet", str(path.absolute())])
        if ignored.returncode:
            raise ReadError("auth_path_not_git_ignored")
    if path.is_symlink():
        raise ReadError("auth_file_symlink")
    fd, tmp = tempfile.mkstemp(prefix=".pending-", dir=root)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(serialized)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_auth(root, site):
    auth_root(root)
    try:
        fd = os.open(root / (site + ".json"), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd) as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
                raise ReadError("auth_file_permissions")
            if st.st_size > 65536:
                raise ReadError("auth_file_invalid")
            obj = json.load(f)
        if obj.get("version") != 1 or obj.get("site") != site:
            raise ReadError("auth_file_invalid")
        return validate_fields(site, obj.get("fields"))
    except FileNotFoundError:
        raise ReadError("auth_missing") from None
    except (OSError, ValueError, AttributeError):
        raise ReadError("auth_file_invalid") from None


def hidden_input(prompt):
    """Read long ASCII credentials without canonical terminal line limits or echo.

macOS canonical input (including getpass) stalls on multi-kilobyte cookies.
Keep signal handling, support erase/Ctrl-U, and always restore the terminal.
"""
    if not sys.stdin.isatty():
        raise ReadError("interactive_terminal_required")
    import termios
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    new = old[:]
    new[6] = old[6][:]
    new[3] &= ~(termios.ECHO | termios.ECHONL | termios.ICANON)
    new[6][termios.VMIN] = 1
    new[6][termios.VTIME] = 0
    value = bytearray()
    try:
        termios.tcsetattr(fd, termios.TCSAFLUSH, new)
        print(prompt, end="", file=sys.stderr, flush=True)
        while True:
            char = os.read(fd, 1)
            if not char or char == b"\x04":
                raise EOFError
            if char in (b"\r", b"\n"):
                break
            if char in (b"\x7f", b"\x08"):
                value = value[:-1]
            elif char == b"\x15":
                value.clear()
            else:
                value.extend(char)
            if len(value) > 50000:
                raise ReadError("auth_input_too_long")
    finally:
        termios.tcsetattr(fd, termios.TCSAFLUSH, old)
        print(file=sys.stderr, flush=True)
    try:
        return value.decode("ascii")
    except UnicodeError:
        raise ReadError("auth_fields_invalid") from None


def prompt_auth(root, site):
    if not sys.stdin.isatty():
        raise ReadError("interactive_terminal_required")
    print(f"{site}: paste the requested fields from your own signed-in dashboard.")
    print("Input is hidden. Saved locally; values are never printed.")
    fields = {k: hidden_input(k + ": ").strip() for k in FIELDS[site]}
    save_auth(root, site, fields)
    print(f"{site}: saved (directory 0700, file 0600)")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward Cookie/Authorization to another destination.


class Client:
    def __init__(self, site):
        self.site = site
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, url, headers=None, body=None, form=False, text=False):
        p = urllib.parse.urlsplit(url)
        if p.scheme != "https" or p.hostname not in HOSTS[self.site] or p.port not in (None, 443) or p.username:
            raise ReadError("destination_rejected")
        h = {"User-Agent": "Mozilla/5.0",
             "Accept": "text/html,application/xhtml+xml" if text else "application/json"}
        h.update(headers or {})
        data = None
        if body is not None:
            data = (urllib.parse.urlencode(body) if form else json.dumps(body)).encode()
            h["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
        req = urllib.request.Request(url, headers=h, data=data)
        try:
            with self.opener.open(req, timeout=30) as r:
                raw = r.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ReadError("response_too_large")
            if text:
                return raw.decode("utf-8")
            obj = json.loads(raw)
            if not isinstance(obj, dict):
                raise ReadError("response_shape_changed")
            if api_has_error(obj):
                raise ReadError("api_error")
            return obj
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308, 401, 403):
                raise ReadError("login_required_or_access_denied") from None
            raise ReadError(f"http_{e.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ReadError("network_error") from None
        except (ValueError, UnicodeError):
            raise ReadError("response_not_json_or_login_page") from None


def spotify_code(page, state):
    if re.search(r"""["'](?:login_required|consent_required|interaction_required)["']""", page):
        raise ReadError("login_required")
    def field(key):
        matches = re.findall(r"""["']?""" + key + r"""["']?\s*:\s*["']([A-Za-z0-9_-]+)["']""", page)
        if len(matches) != 1:
            raise ReadError("auth_response_changed")
        return matches[0]
    if field("state") != state:
        raise ReadError("auth_state_mismatch")
    return field("code")


def spotify(client, fields, show, start, today):
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {"response_type": "code", "client_id": SPOTIFY_CLIENT,
        "scope": "streaming ugc-image-upload user-read-email user-read-private",
        "redirect_uri": "https://podcasters.spotify.com", "code_challenge": challenge,
        "code_challenge_method": "S256", "state": state, "response_mode": "web_message", "prompt": "none"}
    cookie = "; ".join(k + "=" + fields[k] for k in FIELDS["spotify"])
    page = client.request("https://accounts.spotify.com/oauth2/v2/auth?" + urllib.parse.urlencode(params),
                          {"Cookie": cookie}, text=True)
    tok = client.request("https://accounts.spotify.com/api/token", body={
        "grant_type": "authorization_code", "client_id": SPOTIFY_CLIENT, "code": spotify_code(page, state),
        "redirect_uri": "https://podcasters.spotify.com", "code_verifier": verifier}, form=True)
    access = tok.get("access_token")
    if not isinstance(access, str) or not access or "\n" in access or "\r" in access:
        raise ReadError("auth_response_changed")
    obj = client.request("https://generic.wg.spotify.com/podcasters/v0/shows/" + show + "/metadata",
                         {"Authorization": "Bearer " + access})
    if obj.get("id") != show:
        raise ReadError("show_mismatch")
    return count(obj.get("followers")), "API: metadata.followers (all time)"


def amazon(client, fields, show, start, today):
    obj = client.request("https://podcasters.amazon.com/api/metrics/podcast",
        {"Cookie": fields["cookie"], "csrf-token": fields["csrf_token"], "locale": "en-US"},
        body={"startTime": start + "T00:00:00.000Z", "endTime": today + "T00:00:00.000Z",
            "pagination": {"pageSize": 50},
            "followsAggregate": {"groupByProperties": ["PODCAST_ID"], "calculationsIncluded": ["TOTAL"]}})
    if api_has_error(obj):
        raise ReadError("api_error")
    found = [r for r in obj.get("data", {}).get("followsAggregate", []) if r.get("id") == show]
    if len(found) != 1:
        raise ReadError("show_missing_or_pagination")
    return count(found[0].get("total")), f"API: {start} to {today} 00:00 UTC"


def apple_count(obj):
    if obj.get("measure") != "FOLLOWERS":
        raise ReadError("metric_mismatch")
    n = count(obj.get("allTimeFollowers", {}).get("all", {}).get("current"))
    return "-" if n < 5 else n  # A numeric zero can be privacy-censored.


def apple(client, fields, show, start, today):
    query = urllib.parse.urlencode({"showId": show, "start": start, "end": today,
        "mode": "ALL_TIME", "seriesMode": "DAILY", "metric": "FOLLOWERS", "dimension": "BY_COUNTRY"})
    cookie = "; ".join(k + "=" + fields[k] for k in FIELDS["apple"])
    obj = client.request("https://podcastsconnect.apple.com/podcasts/pcc/v1/analytics/showTrendsV2?" + query,
                         {"Cookie": cookie})
    return apple_count(obj), "API: allTimeFollowers.all.current (small counts kept as 0–4)"


def collect(site, root, show, start="2017-09-19", today=None, client=None):
    try:
        if site not in FIELDS or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", show):
            raise ReadError("show_id_invalid")
        today = today or dt.datetime.now(dt.timezone.utc).date().isoformat()
        if dt.date.fromisoformat(start) >= dt.date.fromisoformat(today):
            raise ReadError("date_range_invalid")
        fields = load_auth(Path(root), site)
        n, note = {"spotify": spotify, "amazon": amazon, "apple": apple}[site](
            client or Client(site), fields, show, start, today)
        return {"site": site, "count": n, "status": "ok", "note": note}
    except ReadError as e:
        return {"site": site, "count": None, "status": str(e)}
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError):
        return {"site": site, "count": None, "status": "response_shape_changed"}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--auth-dir", type=Path)
    ap.add_argument("--save-auth", choices=FIELDS)
    ap.add_argument("--check", choices=FIELDS)
    ap.add_argument("--show")
    ap.add_argument("--start", default="2017-09-19")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.auth_dir:
        ap.error("--auth-dir is required (local directory excluded from Git)")
    if a.save_auth:
        try:
            prompt_auth(a.auth_dir, a.save_auth)
            return 0
        except (ReadError, EOFError, KeyboardInterrupt) as e:
            print(str(e) if isinstance(e, ReadError) else "cancelled", file=sys.stderr)
            return 2
    if a.check and a.show:
        out = collect(a.check, a.auth_dir, a.show, a.start)
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out["status"] == "ok" else 2
    ap.error("choose --save-auth SITE or --check SITE --show ID")


def selftest():
    import unittest
    class Checks(unittest.TestCase):
        def test_values(self):
            self.assertEqual(count(0), 0)
            for bad in (None, True, -1, 1.2, "NaN", float("inf"), "secret"):
                with self.assertRaises(ReadError):
                    count(bad)
            for n, expected in ((108.0, 108), (0, "-"), (4, "-")):
                self.assertEqual(apple_count({"measure": "FOLLOWERS", "allTimeFollowers": {"all": {"current": n}}}), expected)
            for obj in ({}, {"measure": "LISTENERS"}, {"measure": "FOLLOWERS", "allTimeFollowers": {"all": {"current": None}}}):
                with self.assertRaises(ReadError):
                    apple_count(obj)
        def test_state(self):
            self.assertEqual(spotify_code('{response:{state:"abc",code:"xyz"}};', "abc"), "xyz")
            for page in ('{state:"wrong",code:"xyz"}', '{state:"abc",error:"login_required"}', '<html>Login</html>'):
                with self.assertRaises(ReadError):
                    spotify_code(page, "abc")
        def test_auth_storage(self):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td) / "auth"
                fields = {"myacinfo": "synthetic-cookie", "itctx": "synthetic-context"}
                save_auth(root, "apple", fields)
                self.assertEqual(load_auth(root, "apple"), fields)
                self.assertEqual((root / "apple.json").stat().st_mode & 0o777, 0o600)
                self.assertEqual(collect("spotify", root, "SHOW")["status"], "auth_missing")
                (root / "apple.json").chmod(0o644)
                with self.assertRaises(ReadError):
                    load_auth(root, "apple")
                (root / "apple.json").unlink()
                (root / "apple.json").symlink_to(Path(td) / "outside")
                with self.assertRaises(ReadError):
                    save_auth(root, "apple", fields)
                with self.assertRaises(ReadError):
                    validate_fields("apple", dict(fields, myacinfo="x\r\nHost: evil"))
        def test_destinations(self):
            client = Client("apple")
            for url in ("https://example.com/", "http://podcastsconnect.apple.com/", "https://podcastsconnect.apple.com:444/"):
                with self.assertRaises(ReadError):
                    client.request(url, {"Cookie": "synthetic"})
            self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com/"))
        def test_amazon_body(self):
            class Fake:
                def request(self, url, headers, body):
                    assert body["startTime"] == "2020-01-01T00:00:00.000Z"
                    assert body["endTime"] == "2026-10-17T00:00:00.000Z"
                    return {"error": {"errors": []}, "data": {"followsAggregate": [{"id": "OTHER", "total": 999}, {"id": "SHOW", "total": 2}]}}
            self.assertEqual(amazon(Fake(), {"cookie": "x=y", "csrf_token": "x"}, "SHOW", "2020-01-01", "2026-10-17")[0], 2)
            class Error:
                def request(self, *a, **kw):
                    return {"error": {"errors": [{"exception": "synthetic"}]}, "data": {"followsAggregate": []}}
            with self.assertRaises(ReadError):
                amazon(Error(), {"cookie": "x=y", "csrf_token": "x"}, "SHOW", "2020-01-01", "2026-10-17")
        def test_redaction(self):
            import io
            class Failing:
                def open(self, req, timeout):
                    raise urllib.error.HTTPError(req.full_url, 403, "sensitive", {}, io.BytesIO(b"secret"))
            client = Client("apple")
            client.opener = Failing()
            with self.assertRaisesRegex(ReadError, "^login_required_or_access_denied$"):
                client.request("https://podcastsconnect.apple.com/", {"Cookie": "secret"})
        def test_html_accept(self):
            import io
            class HTML:
                def open(self, req, timeout):
                    assert "text/html" in req.get_header("Accept")
                    return io.BytesIO(b'<html>synthetic</html>')
            client = Client("spotify")
            client.opener = HTML()
            self.assertEqual(client.request("https://accounts.spotify.com/oauth2/v2/auth", text=True), "<html>synthetic</html>")
        def test_empty_error_envelope(self):
            import io
            class JSON:
                def open(self, req, timeout):
                    return io.BytesIO(b'{"error":{"errors":[]},"data":{"followsAggregate":[]}}')
            client = Client("amazon")
            client.opener = JSON()
            self.assertEqual(client.request("https://podcasters.amazon.com/api/metrics/podcast")["error"], {"errors": []})
            self.assertTrue(api_has_error({"error": {"errors": [{"exception": "synthetic"}]}}))
        def test_long_terminal_input(self):
            import pty
            import select
            import time
            master, slave = pty.openpty()
            code = "import runpy,termios; m=runpy.run_path(" + repr(__file__) + "); old=termios.tcgetattr(0); n=len(m['hidden_input']('probe: ')); assert termios.tcgetattr(0)==old; print('length='+str(n),flush=True)"
            proc = subprocess.Popen([sys.executable, "-c", code], stdin=slave, stdout=slave, stderr=slave)
            os.close(slave)
            try:
                output = b""
                end = time.monotonic() + 5
                while b"probe: " not in output and time.monotonic() < end:
                    if select.select([master], [], [], .1)[0]:
                        output += os.read(master, 65536)
                self.assertIn(b"probe: ", output)
                payload = b"synthetic-" * 800
                os.write(master, payload + b"\n")
                while b"length=" not in output and time.monotonic() < end:
                    if select.select([master], [], [], .1)[0]:
                        try:
                            output += os.read(master, 65536)
                        except OSError:
                            break
                self.assertIn(b"length=8000", output)
                self.assertNotIn(b"synthetic-", output)  # Terminal must not echo the cookie.
                self.assertEqual(proc.wait(timeout=5), 0)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                os.close(master)
        def test_git_exclusion(self):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                subprocess.run(["git", "init", "-q", str(root)], check=True)
                fields = {"myacinfo": "synthetic", "itctx": "synthetic"}
                with self.assertRaisesRegex(ReadError, "^auth_path_not_git_ignored$"):
                    save_auth(root / "auth", "apple", fields)
                self.assertFalse((root / "auth/apple.json").exists())
                (root / ".gitignore").write_text("/auth/\n")
                save_auth(root / "auth", "apple", fields)
                self.assertEqual(load_auth(root / "auth", "apple"), fields)
        def test_spotify_flow(self):
            class Fake:
                def request(self, url, headers=None, body=None, **kwargs):
                    if "/oauth2/" in url:
                        self.state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
                        assert headers == {"Cookie": "sp_dc=cookie; sp_key=key"}
                        return '{response:{state:"' + self.state + '",code:"code"}}'
                    if "/api/token" in url:
                        assert body["code"] == "code" and body["code_verifier"]
                        return {"access_token": "synthetic"}
                    assert headers == {"Authorization": "Bearer synthetic"}
                    return {"id": "SHOW", "followers": 10, "listeners": 999}
            self.assertEqual(spotify(Fake(), {"sp_dc": "cookie", "sp_key": "key"}, "SHOW", "", "")[0], 10)
        def test_apple_request(self):
            class Fake:
                def request(self, url, headers):
                    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
                    assert q["showId"] == ["123"] and q["metric"] == ["FOLLOWERS"] and q["mode"] == ["ALL_TIME"]
                    assert headers == {"Cookie": "myacinfo=c; itctx=x"}
                    return {"measure": "FOLLOWERS", "allTimeFollowers": {"all": {"current": 108}}}
            self.assertEqual(apple(Fake(), {"myacinfo": "c", "itctx": "x"}, "123", "2020-01-01", "2026-10-17")[0], 108)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
