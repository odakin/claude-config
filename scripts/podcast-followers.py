#!/usr/bin/env python3
"""Read podcast follower counts using owner-supplied sessions, without a browser.

API reads use the standard library; history charts optionally use matplotlib.
No browser-cookie discovery; no credential output.
save-auth accepts hidden interactive input. Keep auth-dir outside version control.
Session expiry requires the owner to sign in and replace the saved fields.
Between re-entries the reads keep the saved state fresh: cookies a successful read
receives (Set-Cookie) are folded back into the saved fields, and Amazon's short-lived
csrf-token is re-minted the way the dashboard does it (a bounce through the amazon.com
sign-in page back to /auth/csrf, with the saved cookies; a password form there means the
amazon.com login itself is gone). An unattended job can write refreshed state to
--auth-overlay (a machine-local directory) instead of a distributed/read-only auth-dir;
whichever copy is newer is read, so a re-entered auth-dir wins again.
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
         "amazon": {"podcasters.amazon.com", "www.amazon.com"}, "apple": {"podcastsconnect.apple.com"}}
SPOTIFY_CLIENT = "05a1371ee5194c27860b3ff3ff3979d2"  # Public dashboard client
# The Amazon dashboard mints its csrf-token by sending the browser through the amazon.com sign-in page and back
# to /auth/csrf, which answers with a redirect carrying ?csrf-token=... (read from the dashboard bundle). A saved
# token stops working after a day or two; replaying the same hops with the saved cookies mints a fresh one.
AMAZON_SIGNIN = ("https://www.amazon.com/ap/signin?openid.ns=http://specs.openid.net/auth/2.0"
                 "&openid.claimed_id=http://specs.openid.net/auth/2.0/identifier_select"
                 "&openid.identity=http://specs.openid.net/auth/2.0/identifier_select"
                 "&pageId=amzn_ziggy_ui&openid.assoc_handle=amzn_podcaster_portal_us&language=en_US"
                 "&openid.mode=checkid_setup"
                 "&openid.return_to=https://podcasters.amazon.com/auth/csrf?path=https://podcasters.amazon.com/podcasts")
REDIRECTS = (301, 302, 303, 307, 308)
MAX_HOPS = 6


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


def parse_cookies(header):
    """'a=1; b=2' -> {'a': '1', 'b': '2'} (order kept, malformed pairs dropped)."""
    jar = {}
    for part in header.split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name:
            jar[name] = value
    return jar


def format_cookies(jar):
    return "; ".join(f"{k}={v}" for k, v in jar.items())


def set_cookie_pair(header):
    """Name and value of a Set-Cookie header (attributes dropped); None when malformed, empty (a deletion) or not
    printable ASCII."""
    name, sep, value = header.split(";", 1)[0].partition("=")
    name, value = name.strip(), value.strip()
    if not sep or not name or not value or any(ord(c) < 33 or ord(c) > 126 for c in name + value):
        return None
    return name, value


def refreshed_fields(site, fields, set_cookies):
    """The saved fields with what a successful read received folded in: Amazon's cookie string merged by name
    (the re-minted csrf-token is already in fields), the other sites' named cookies replaced when the server sent
    a new value. Only after success: a failed read may have been handed anonymous replacement cookies."""
    out = dict(fields)
    if site == "amazon":
        jar = parse_cookies(out["cookie"])
        jar.update(set_cookies)
        out["cookie"] = format_cookies(jar)
    else:
        for key in FIELDS[site]:
            if key in set_cookies:
                out[key] = set_cookies[key]
    return validate_fields(site, out)


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


def auth_source(root, site, overlay=None):
    """Which copy to read: the newer of root/<site>.json and overlay/<site>.json (a tie goes to the overlay).
    The overlay is a machine-local directory an unattended job writes refreshed state to, so a distributed or
    read-only root is never modified; when the owner re-enters the root it is newer and wins again."""
    auth_root(root)
    path = root / (site + ".json")
    if overlay is None:
        return path
    alt = Path(overlay) / (site + ".json")
    try:
        alt_mtime = alt.lstat().st_mtime
    except FileNotFoundError:
        return path
    try:
        if path.lstat().st_mtime > alt_mtime:
            return path
    except FileNotFoundError:
        pass
    auth_root(Path(overlay))
    return alt


def save_auth(root, site, fields, overlay=None):
    fields = validate_fields(site, fields)
    serialized = json.dumps({"version": 1, "site": site, "fields": fields})
    if len(serialized.encode()) > 65536:
        raise ReadError("auth_file_too_large")
    root = Path(overlay) if overlay is not None else Path(root)
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


def load_auth(root, site, overlay=None):
    path = auth_source(Path(root), site, overlay)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
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
        self.set_cookies = {}   # name -> value handed back by responses; folded into the saved fields after a successful read

    def _check(self, url):
        p = urllib.parse.urlsplit(url)
        if p.scheme != "https" or p.hostname not in HOSTS[self.site] or p.port not in (None, 443) or p.username:
            raise ReadError("destination_rejected")
        return p

    def _absorb(self, headers):
        get_all = getattr(headers, "get_all", None)
        for line in (get_all("Set-Cookie") if get_all else None) or []:
            pair = set_cookie_pair(line)
            if pair:
                self.set_cookies[pair[0]] = pair[1]

    def hop(self, url, headers=None):
        """One request without following redirects: (status, absolute Location or None). The request and every
        Location must stay on the site's hosts; cookies the response sets are absorbed. Used for sign-in bounces."""
        self._check(url)
        h = {"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en-US,en;q=0.9"}
        h.update(headers or {})
        req = urllib.request.Request(url, headers=h)
        try:
            with self.opener.open(req, timeout=30) as r:
                self._absorb(getattr(r, "headers", None))
                r.read(2_000_001)
                return getattr(r, "status", 200), None
        except urllib.error.HTTPError as e:
            self._absorb(e.headers)
            if e.code in REDIRECTS:
                location = e.headers.get("Location") if e.headers else None
                if not location:
                    raise ReadError("auth_flow_changed") from None
                absolute = urllib.parse.urljoin(url, location)
                self._check(absolute)
                return e.code, absolute
            if e.code in (401, 403):
                raise ReadError("login_required_or_access_denied") from None
            raise ReadError(f"http_{e.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ReadError("network_error") from None

    def request(self, url, headers=None, body=None, form=False, text=False):
        self._check(url)
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
                self._absorb(getattr(r, "headers", None))
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
            self._absorb(e.headers)
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


def amazon_refresh_csrf(client, fields):
    """Mint a fresh csrf-token the way the dashboard does: www.amazon.com/ap/signin (with the saved cookies)
    -> podcasters.amazon.com/auth/csrf?...openid.mode=id_res -> podcasters.amazon.com/podcasts?csrf-token=...
    Every hop stays on HOSTS["amazon"] (client.hop enforces it); cookies set on the way join the jar. A 200 page
    at the sign-in host is the password form = the amazon.com login itself is gone (login_required)."""
    jar = parse_cookies(fields["cookie"])
    url = AMAZON_SIGNIN
    for _ in range(MAX_HOPS):
        status, location = client.hop(url, {"Cookie": format_cookies(jar)})
        jar.update(client.set_cookies)
        if status in REDIRECTS and location:
            p = urllib.parse.urlsplit(location)
            if p.hostname == "podcasters.amazon.com":
                # the dashboard reads the token from the query and turns the decoded spaces back into '+'
                token = urllib.parse.parse_qs(p.query).get("csrf-token", [""])[0].replace(" ", "+")
                if token:
                    if not re.fullmatch(r"[A-Za-z0-9+/=_-]{16,4096}", token):
                        raise ReadError("auth_response_changed")
                    fields["csrf_token"] = token
                    fields["cookie"] = format_cookies(jar)
                    return
            url = location
            continue
        if status == 200 and urllib.parse.urlsplit(url).hostname == "www.amazon.com":
            raise ReadError("login_required")
        raise ReadError("auth_flow_changed")
    raise ReadError("auth_flow_changed")


def amazon(client, fields, show, start, today):
    """Read with the saved csrf-token; when the dashboard denies it, re-mint the token and read once more.
    fields is updated in place (token, cookies) so the caller can persist it after success."""
    try:
        return amazon_read(client, fields, show, start, today)
    except ReadError as e:
        if str(e) != "login_required_or_access_denied" or not callable(getattr(client, "hop", None)):
            raise
    amazon_refresh_csrf(client, fields)
    n, note = amazon_read(client, fields, show, start, today)
    return n, note + "; csrf-token re-minted via sign-in"


def amazon_read(client, fields, show, start, today):
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
    all_time = obj.get("allTimeFollowers")
    all_count = all_time.get("all") if isinstance(all_time, dict) else None
    if not isinstance(all_count, dict) or "current" not in all_count:
        raise ReadError("metric_missing")
    # Apple requires five unique playing users for analytics, not five followers.
    # A present null supplies no numeric upper bound on followers.
    return "-" if all_count["current"] is None else count(all_count["current"])


def apple(client, fields, show, start, today):
    query = urllib.parse.urlencode({"showId": show, "start": start, "end": today,
        "mode": "ALL_TIME", "seriesMode": "DAILY", "metric": "FOLLOWERS", "dimension": "BY_COUNTRY"})
    cookie = "; ".join(k + "=" + fields[k] for k in FIELDS["apple"])
    obj = client.request("https://podcastsconnect.apple.com/podcasts/pcc/v1/analytics/showTrendsV2?" + query,
                         {"Cookie": cookie})
    n = apple_count(obj)
    return n, ("API: follower count not disclosed (null; no numeric bound)" if n == "-"
               else "API: allTimeFollowers.all.current")


def persist_refresh(site, root, before, fields, set_cookies, overlay=None):
    """After a successful read, save what the session handed back (re-minted token, rotated cookies) so the next
    run starts from the freshest state. Nothing to save, or a save that fails, leaves the read's result as is."""
    try:
        after = refreshed_fields(site, fields, set_cookies)
    except ReadError:
        return False
    if after == before:
        return False
    try:
        save_auth(root, site, after, overlay)
    except (ReadError, OSError):
        return False
    return True


def collect(site, root, show, start="2017-09-19", today=None, client=None, overlay=None):
    try:
        if site not in FIELDS or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", show):
            raise ReadError("show_id_invalid")
        today = today or dt.datetime.now(dt.timezone.utc).date().isoformat()
        if dt.date.fromisoformat(start) >= dt.date.fromisoformat(today):
            raise ReadError("date_range_invalid")
        fields = load_auth(Path(root), site, overlay)
        before = dict(fields)
        client = client or Client(site)
        n, note = {"spotify": spotify, "amazon": amazon, "apple": apple}[site](client, fields, show, start, today)
        if persist_refresh(site, Path(root), before, fields, getattr(client, "set_cookies", {}), overlay):
            note += " (saved auth refreshed)"
        return {"site": site, "count": n, "status": "not_disclosed" if n == "-" else "ok", "note": note}
    except ReadError as e:
        return {"site": site, "count": None, "status": str(e)}
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError):
        return {"site": site, "count": None, "status": "response_shape_changed"}


def render_history_chart(points, series, output_stem, *, title, subtitle="", footnote="", unit="Followers"):
    """Write deterministic SVG + PNG small multiples from dated numeric observations.

points: [{date: ISO date, values: {series_key: number or None}, assumed: [keys]}]
series: [(key, display label), ...]. Missing values break lines; hollow markers
identify supplied assumptions. Policy and ledger parsing belong to the caller.
Matplotlib is only required when drawing; SVG embeds glyph paths for portability.
"""
    cache = Path(tempfile.gettempdir()) / ("podcast-followers-mpl-" + str(os.getuid()))
    cache.mkdir(mode=0o700, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache))
    try:
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib import dates as mdates, font_manager, pyplot as plt, ticker
    except ImportError:
        raise RuntimeError("Chart generation requires matplotlib: python3 -m pip install matplotlib") from None
    if not series:
        raise ValueError("At least one chart series is required")
    dates = [dt.date.fromisoformat(p["date"]) for p in points]
    if dates != sorted(set(dates)):
        raise ValueError("Chart dates must be unique and increasing")
    numbers = [v for p in points for k, _ in series if (v := p["values"].get(k)) is not None]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in numbers):
        raise ValueError("Chart values must be nonnegative numbers or None")
    available = {f.name for f in font_manager.fontManager.ttflist}
    family = next((f for f in ("Hiragino Sans", "Noto Sans CJK JP", "Noto Sans JP", "IPAexGothic") if f in available), "DejaVu Sans")
    if family == "DejaVu Sans" and re.search(r"[\u3040-\u9fff]", title + subtitle + footnote + unit + "".join(v for _, v in series)):
        raise RuntimeError("Japanese charts require a Japanese font, e.g. Noto Sans CJK JP")
    columns = min(2, len(series))
    rows = math.ceil(len(series) / columns)
    colors = ("#233b5d", "#167d8d", "#23965b", "#cb8024", "#8463a8", "#cc5263")
    rc = {"font.family": family, "text.usetex": False, "svg.fonttype": "path",
          "svg.hashsalt": "podcast-follower-history", "axes.unicode_minus": False,
          "font.size": 10, "axes.edgecolor": "#c9d1dc", "xtick.color": "#566274", "ytick.color": "#566274"}
    with matplotlib.rc_context(rc):
        fig, grid = plt.subplots(rows, columns, figsize=(11, 1.25 + 2.3 * rows), squeeze=False)
        fig.set_facecolor("#f5f7fb")
        fig.subplots_adjust(left=.075, right=.97, top=.83, bottom=.14, hspace=.60, wspace=.21)
        fig.suptitle(title, x=.075, y=.97, ha="left", fontsize=19, weight="bold", color="#20334e")
        fig.text(.075, .91, subtitle, color="#566274", fontsize=10)
        fig.text(.075, .035, footnote, fontsize=9, color="#566274", linespacing=1.6)
        ticks = ticker.MaxNLocator(nbins=4, integer=True).tick_values(0, max(1, max(numbers, default=0) * 1.1))
        ticks = [t for t in ticks if t >= 0]
        ceiling = max(ticks)
        try:
            for i, ax in enumerate(grid.flat):
                if i >= len(series):
                    ax.set_axis_off()
                    continue
                key, label = series[i]
                color = colors[i % len(colors)]
                values = [p["values"].get(key) for p in points]
                latest = values[-1] if values else None
                latest_text = "—" if latest is None else f"{latest:g}"
                if points and key in points[-1].get("assumed", []):
                    latest_text += "*"
                ax.set_title(f"{label}   {latest_text}", loc="left", fontsize=12, weight="bold", color=color, pad=10)
                ax.set_facecolor("white")
                ax.spines["top"].set_visible(False)
                ax.spines["right"].set_visible(False)
                ax.grid(axis="y", color="#e3e8ef", linewidth=.8)
                ax.set_axisbelow(True)
                ax.set_yticks(ticks)
                ax.set_ylim(-ceiling * .06, ceiling)
                ax.set_ylabel(unit, fontsize=9)
                if dates:
                    ax.plot(dates, values, color=color, linewidth=2.2, marker="o", markersize=5, zorder=3)
                    assumed = [j for j, p in enumerate(points) if key in p.get("assumed", []) and values[j] is not None]
                    if assumed:
                        ax.scatter([dates[j] for j in assumed], [values[j] for j in assumed],
                                   facecolors="white", edgecolors=color, s=40, linewidths=1.6, zorder=4)
                    tick_count = min(6 if dates[0].year == dates[-1].year else 4, len(dates))
                    selected = sorted({round(j * (len(dates) - 1) / max(1, tick_count - 1))
                                       for j in range(tick_count)})
                    ax.set_xticks([dates[j] for j in selected])
                    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d" if dates[0].year == dates[-1].year else "%y/%m/%d"))
                    lo, hi = mdates.date2num(dates[0]), mdates.date2num(dates[-1])
                    pad = max(.3, (hi - lo) * .07)
                    ax.set_xlim(lo - pad, hi + pad)
                    ax.tick_params(axis="x", labelsize=9)
                else:
                    ax.set_xticks([])
                    ax.text(.5, .5, "No observations yet", ha="center", va="center", transform=ax.transAxes, color="#677489")
            stem = Path(output_stem)
            stem.parent.mkdir(parents=True, exist_ok=True)
            targets = {ext: stem.with_suffix("." + ext) for ext in ("svg", "png")}
            with tempfile.TemporaryDirectory(prefix=".follower-chart-", dir=stem.parent) as tmp:
                for ext in targets:
                    metadata = {"Title": title, "Description": footnote}
                    if ext == "svg":
                        metadata.update({"Date": None, "Creator": "podcast-followers"})
                    fig.savefig(Path(tmp) / ("chart." + ext), format=ext, dpi=160, metadata=metadata)
                for ext, target in targets.items():
                    os.replace(Path(tmp) / ("chart." + ext), target)
            return targets
        finally:
            plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--auth-dir", type=Path)
    ap.add_argument("--auth-overlay", type=Path, help="machine-local directory where refreshed auth is written and, when newer, read from")
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
        out = collect(a.check, a.auth_dir, a.show, a.start, overlay=a.auth_overlay)
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
            for n, expected in ((108.0, 108), (0, 0), (4, 4), (None, "-")):
                self.assertEqual(apple_count({"measure": "FOLLOWERS", "allTimeFollowers": {"all": {"current": n}}}), expected)
            for obj in ({}, {"measure": "LISTENERS"}, {"measure": "FOLLOWERS", "allTimeFollowers": {"all": {}}}):
                with self.assertRaises(ReadError):
                    apple_count(obj)
        def test_history_chart(self):
            import importlib.util
            if importlib.util.find_spec("matplotlib") is None:
                self.skipTest("optional matplotlib is not installed")
            with tempfile.TemporaryDirectory() as td:
                stem = Path(td) / "history"
                points = [{"date": "2026-01-01", "values": {"a": 0}, "assumed": ["a"]},
                          {"date": "2026-01-03", "values": {"a": None}},
                          {"date": "2026-01-10", "values": {"a": 3}}]
                files = render_history_chart(points, [("a", "Series A")], stem, title="History")
                svg = files["svg"].read_bytes()
                self.assertIn(b"<svg", svg)
                self.assertTrue(files["png"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
                render_history_chart(points, [("a", "Series A")], stem, title="History")
                self.assertEqual(files["svg"].read_bytes(), svg)
                render_history_chart([], [("a", "Series A")], stem, title="Empty history")
                self.assertIn(b"No observations yet", files["svg"].read_bytes())
                with self.assertRaises(ValueError):
                    render_history_chart([points[0], points[0]], [("a", "Series A")], stem, title="Invalid")
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
        def test_cookie_helpers(self):
            self.assertEqual(parse_cookies("a=1; b=2=3; junk; =x"), {"a": "1", "b": "2=3"})
            self.assertEqual(format_cookies({"a": "1", "b": "2"}), "a=1; b=2")
            self.assertEqual(set_cookie_pair("sess=abc; Path=/; Secure; HttpOnly"), ("sess", "abc"))
            for bad in ("sess=; Max-Age=0", "nameonly", "x=a b", "x=a\r\nY"):
                self.assertIsNone(set_cookie_pair(bad))
            self.assertEqual(refreshed_fields("amazon", {"cookie": "a=1; b=2", "csrf_token": "t"}, {"b": "9", "c": "3"}),
                             {"cookie": "a=1; b=9; c=3", "csrf_token": "t"})
            self.assertEqual(refreshed_fields("apple", {"myacinfo": "m", "itctx": "old"}, {"itctx": "new", "other": "x"}),
                             {"myacinfo": "m", "itctx": "new"})
        def test_amazon_refresh(self):
            class Bounce:
                def __init__(self):
                    self.set_cookies, self.hops, self.reads = {}, [], 0
                def hop(self, url, headers=None):
                    self.hops.append(url)
                    assert "Cookie" in (headers or {})
                    if len(self.hops) == 1:
                        assert url == AMAZON_SIGNIN
                        self.set_cookies["session-token"] = "rotated"
                        return 302, "https://podcasters.amazon.com/auth/csrf?path=https://podcasters.amazon.com/podcasts&openid.mode=id_res&openid.sig=synthetic"
                    return 302, "https://podcasters.amazon.com/podcasts?csrf-token=abcdefghijklmnop+qrs%3D"
                def request(self, url, headers=None, body=None, **kw):
                    self.reads += 1
                    if headers.get("csrf-token") != "abcdefghijklmnop+qrs=":
                        raise ReadError("login_required_or_access_denied")
                    assert "session-token=rotated" in headers["Cookie"] and "a=b" in headers["Cookie"]
                    return {"error": {"errors": []}, "data": {"followsAggregate": [{"id": "SHOW", "total": 3}]}}
            client, fields = Bounce(), {"cookie": "a=b; session-token=old", "csrf_token": "stale"}
            n, note = amazon(client, fields, "SHOW", "2020-01-01", "2026-10-17")
            self.assertEqual((n, client.reads, len(client.hops)), (3, 2, 2))
            self.assertIn("re-minted", note)
            self.assertEqual(fields, {"cookie": "a=b; session-token=rotated", "csrf_token": "abcdefghijklmnop+qrs="})
            class LoginForm(Bounce):
                def hop(self, url, headers=None):
                    return 200, None   # the password form at www.amazon.com = the amazon.com login is gone
            with self.assertRaisesRegex(ReadError, "^login_required$"):
                amazon(LoginForm(), {"cookie": "a=b", "csrf_token": "stale"}, "SHOW", "2020-01-01", "2026-10-17")
            class Loop(Bounce):
                def hop(self, url, headers=None):
                    return 302, "https://www.amazon.com/ap/signin?again=1"
            with self.assertRaisesRegex(ReadError, "^auth_flow_changed$"):
                amazon(Loop(), {"cookie": "a=b", "csrf_token": "stale"}, "SHOW", "2020-01-01", "2026-10-17")
            class NoHop:   # the plain fakes of the other tests: a denied read stays denied
                def request(self, *a, **kw):
                    raise ReadError("login_required_or_access_denied")
            with self.assertRaisesRegex(ReadError, "^login_required_or_access_denied$"):
                amazon(NoHop(), {"cookie": "a=b", "csrf_token": "stale"}, "SHOW", "2020-01-01", "2026-10-17")
        def test_hop_and_overlay(self):
            import email, io
            def failing(code, header_text):
                class Opener:
                    def open(self, req, timeout):
                        raise urllib.error.HTTPError(req.full_url, code, "synthetic", email.message_from_string(header_text), io.BytesIO(b""))
                return Opener()
            client = Client("amazon")
            client.opener = failing(302, "Location: /ap/signin?again=1\nSet-Cookie: sid=1; Path=/\nSet-Cookie: gone=; Max-Age=0\n")
            self.assertEqual(client.hop("https://www.amazon.com/ap/signin?x=1"), (302, "https://www.amazon.com/ap/signin?again=1"))
            self.assertEqual(client.set_cookies, {"sid": "1"})
            client.opener = failing(302, "Location: https://example.com/steal\n")
            with self.assertRaisesRegex(ReadError, "^destination_rejected$"):
                client.hop("https://www.amazon.com/ap/signin")
            with self.assertRaisesRegex(ReadError, "^destination_rejected$"):
                client.hop("https://example.com/")
            client.opener = failing(403, "")
            with self.assertRaisesRegex(ReadError, "^login_required_or_access_denied$"):
                client.hop("https://www.amazon.com/ap/signin")
            with tempfile.TemporaryDirectory() as td:
                root, overlay = Path(td) / "base", Path(td) / "state"
                save_auth(root, "apple", {"myacinfo": "m", "itctx": "old"})
                class Fake:
                    set_cookies = {"itctx": "new", "other": "x"}
                    def request(self, url, headers=None, **kw):
                        assert "itctx=old" in headers["Cookie"]
                        return {"measure": "FOLLOWERS", "allTimeFollowers": {"all": {"current": 4}}}
                out = collect("apple", root, "123", client=Fake(), overlay=overlay)
                self.assertEqual((out["status"], out["count"]), ("ok", 4))
                self.assertIn("refreshed", out["note"])
                self.assertEqual(load_auth(root, "apple"), {"myacinfo": "m", "itctx": "old"})            # the base is untouched
                self.assertEqual(load_auth(root, "apple", overlay), {"myacinfo": "m", "itctx": "new"})   # the newer overlay is read
                self.assertEqual((overlay / "apple.json").stat().st_mode & 0o777, 0o600)
                later = (overlay / "apple.json").stat().st_mtime + 10
                os.utime(root / "apple.json", (later, later))                                           # re-entered base wins again
                self.assertEqual(load_auth(root, "apple", overlay), {"myacinfo": "m", "itctx": "old"})
                class Denied:
                    set_cookies = {"itctx": "anonymous"}
                    def request(self, *a, **kw):
                        raise ReadError("login_required_or_access_denied")
                (overlay / "apple.json").unlink()
                self.assertEqual(collect("apple", root, "123", client=Denied(), overlay=overlay)["status"], "login_required_or_access_denied")
                self.assertFalse((overlay / "apple.json").exists())                                      # a failed read saves nothing
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
