"""browser_tab.py — 起動中の Chromium 系 browser に裏で tab を 1 枚開かせ、 行き先を見て、 自分が開いた tab だけを閉じる (macOS)。 SSO 保護サイトの login 切れからの復帰用

使いどころ: browser の session cookie を再利用して script から読むサイト (conventions/machine-route-first.md#session-cookie-reuse) で、
サイト本体のセッションだけが切れた時に、 browser 自身に入り直させる。 script は認証に触れない。 設計の要点と理由 =
conventions/machine-route-first.md#sso-session-recovery、 AppleScript の機構 = conventions/macos-gui-app-automation.md#chromium-tab-scripting。

    tab = BrowserTab("Brave Browser")            # BROWSER_APPS の値。 起動中かは BrowserTab.running(app) で先に見る
    tab.open("https://app.example/")             # 裏で開く。 前面の tab は元に戻す。 browser は前面に出さない
    end, saw_login, at = watch(tab.where, cookie_changed, is_inside, wait_login=0)
    tab.close("https://app.example/")            # まだその prefix の下に居る時だけ閉じる

約束:
  - 見るのは「query と fragment を落とした URL」 と「読み込み中か」 だけ。 落とすのは AppleScript の中 (= script には渡らない)。
    ページの中身は読まない。
  - 開く窓は通常の窓だけ (incognito 等は SSO のログインを共有していない)。 窓が無ければ新しい窓を作る。
  - `tell application` は起動していない app を起動してしまう → 呼ぶ前に running() を見る。 本 module は app を起動も activate もしない。
  - 閉じるのは自分が開いた tab (id で特定) で、 閉じる直前に場所を確かめる (本人が別の場所へ使い回した tab は本人のもの)。
  - AppleScript が使えない (自動操作の許可が無い / 無人実行 / 応答しない) 時は `open -g` で開くだけに落ちる。
    その時 where() は None を返し、 watch は state_changed だけを上限つきで待つ。

`python3 browser_tab.py` (直接実行) = selftest: watch の結末判定を偽の tab と時計で通す (browser・network なし)。
"""
from __future__ import annotations

import subprocess
import sys
import time

BROWSER_APPS = {"brave": "Brave Browser", "chrome": "Google Chrome", "chromium": "Chromium"}
REFRESH_WAIT_S = 40     # 入り直しを待つ上限 (tab の行き先が見えない時はこれだけが頼り)
FLUSH_WAIT_S = 35       # tab が中に着いてから、 browser が cookie を disk に書き出すのを待つ上限 (Chromium は最大 30 秒ほど遅れる)
POLL_S = 1.5
LOGIN_STABLE_POLLS = 3  # 同じ「外」 に読み込み完了のまま止まっているのを何回見たらログイン画面と判断するか (SSO の通過は一瞬)


def _say(msg):
    print(msg, file=sys.stderr, flush=True)


class BrowserTab:
    _OPEN = """on run argv
  set u to item 1 of argv
  tell application "@APP@"
    set w to missing value
    repeat with i from 1 to (count of windows)
      if mode of window i is "normal" then
        set w to window i
        exit repeat
      end if
    end repeat
    if w is missing value then
      set w to make new window
      set t to active tab of w
      set URL of t to u
    else
      set prev to active tab index of w
      set t to make new tab at end of tabs of w with properties {URL:u}
      set active tab index of w to prev
    end if
    return ((id of w) as text) & " " & ((id of t) as text)
  end tell
end run"""

    _FIND = """on run argv
  set wid to (item 1 of argv) as integer
  set tid to (item 2 of argv) as integer
  tell application "@APP@"
    try
      set t to tab id tid of window id wid
      set u to URL of t
      set ld to loading of t
    on error
      return "gone"
    end try
@ACT@
  end tell
  repeat with d in {"?", "#"}
    set AppleScript's text item delimiters to (d as text)
    set u to text item 1 of u
  end repeat
  set AppleScript's text item delimiters to ""
  return u & " " & (ld as text)
end run"""

    _CLOSE_ACT = """    if u starts with (item 3 of argv) then
      close t
      return "closed"
    end if"""

    def __init__(self, app):
        if app not in BROWSER_APPS.values():  # app 名は AppleScript の本文に入る = 固定の一覧からだけ
            raise ValueError(f"unknown browser app: {app}")
        self.app, self.ids = app, None

    @staticmethod
    def running(app):
        return subprocess.run(["pgrep", "-xq", app]).returncode == 0

    def _osa(self, script, *args, timeout=15):
        try:
            r = subprocess.run(["osascript", "-e", script.replace("@APP@", self.app), *args],
                               capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
        return r.stdout.strip() if r.returncode == 0 else None

    def open(self, url):
        out = self._osa(self._OPEN, url)
        if out and len(out.split()) == 2:
            self.ids = out.split()
        else:  # AppleScript 不可 → 開くだけ
            subprocess.run(["open", "-g", "-a", self.app, url], check=False)

    def where(self):
        """None = 見えない / "gone" = tab が無くなった / (query なしの URL, 読み込み中か)。"""
        if not self.ids:
            return None
        out = self._osa(self._FIND.replace("@ACT@", ""), *self.ids)
        if out is None:
            return None
        if out == "gone":
            return "gone"
        url, _, loading = out.rpartition(" ")
        return url, loading == "true"

    def close(self, prefix):
        """自分が開いた tab が今も prefix の下に居る時だけ閉じる。 閉じたら True。"""
        return bool(self.ids) and self._osa(self._FIND.replace("@ACT@", self._CLOSE_ACT), *self.ids, prefix) == "closed"


def watch(where, state_changed, is_inside, wait_login=0, clock=time.time, sleep=time.sleep, say=_say):
    """browser に開かせた tab と、 script 側から見える状態 (cookie DB 等) を見て、 入り直しの結末を返す (判定だけ)。

    where()         → BrowserTab.where と同じ形
    state_changed() → script が読む状態が、 手元に読んだ時から変わったか (例: cookie DB の session cookie の時刻)。
                      ⚠️ "fresh" を「入り直せた」 と扱うなら、 時刻の変化だけでなく **server が受け入れること**まで
                      この中で確かめる (ログイン画面そのものが未認証の session cookie を配るサイトがある = 時刻だけだと
                      IdP が切れていても fresh になる。 実装例 = garoon-client.py の `_renewed`、
                      一般則 = conventions/machine-route-first.md#sso-session-recovery)
    is_inside(url)  → その URL がサイトの中か (ログイン画面でも別 host でもない)
    wait_login      → 0 = ログイン画面で止まったらすぐ返す / N = 本人がログインし終えるのを N 秒まで待つ

    → (結末, ログイン画面を見たか, 最後に見た tab の場所)。 結末 = "fresh" 状態が更新された / "stale" tab は中に着いたが
    状態は変わらなかった / "login" ログイン画面で止まった (wait_login=0 の時だけ) / "timeout"。
    """
    deadline = clock() + max(REFRESH_WAIT_S, wait_login)
    arrived = None
    saw_login = False
    last, still = None, 0
    if wait_login and where() is None:
        say(f"ログイン待ち (最大 {wait_login} 秒)。 browser でログインすると続きから進む")
    while clock() < deadline:
        sleep(POLL_S)
        if state_changed():
            return "fresh", saw_login, last
        at = where()
        if not isinstance(at, tuple):
            continue  # 見えない / tab が無くなった → 状態の変化だけが頼り
        url, loading = at
        if not loading and is_inside(url):
            if arrived is None:
                arrived = clock()
                deadline = max(deadline, arrived + FLUSH_WAIT_S)
            elif clock() - arrived >= FLUSH_WAIT_S:
                return "stale", saw_login, url
            last = url
            continue
        arrived = None
        still = still + 1 if (not loading and url == last) else 0
        last = url
        if still >= LOGIN_STABLE_POLLS - 1 and not saw_login:
            saw_login = True
            if not wait_login:
                return "login", True, url
            say(f"ログイン画面で止まった = 本人のログインが要る。 ログイン待ち (最大 {wait_login} 秒)、 終われば続きから進む")
    return ("stale" if arrived else "timeout"), saw_login, last


def _fake_run(script, changed_at=None, wait_login=0):
    """selftest 用: tab の行き先の台本 (1 poll に 1 つ、 尽きたら最後を繰り返す) と状態が変わる時刻で watch を回す。"""
    t = [0.0]
    said = []

    def where():
        return script[min(int(t[0] / POLL_S), len(script) - 1)]

    def sleep(sec):
        t[0] += sec

    end = watch(where, lambda: changed_at is not None and t[0] >= changed_at,
                lambda u: u.startswith("https://app.example/") and not u.endswith("/login"), wait_login,
                clock=lambda: t[0], sleep=sleep, say=said.append)
    return end[:2], t[0], said


def selftest_cases():
    """[(名前, 通ったか)]。 呼び元の --selftest に混ぜられるように list で返す。"""
    G, L, A = ("https://app.example/portal", False), ("https://idp.example/auth/session", False), \
        ("https://idp.example/auth/saml2/x/assertions", False)
    loading = ("https://app.example/", True)
    return [
        ("SSO を素通り → 状態の更新で fresh、 ログイン画面は見ていない", _fake_run([loading, A, G], changed_at=12)[0] == ("fresh", False)),
        ("ログイン画面で止まる → 数秒で login (上限まで待たない)", (lambda r: r[0] == ("login", True) and r[1] <= 6)(_fake_run([loading, L]))),
        ("途中で一瞬 IdP を通るだけならログイン画面と見ない", _fake_run([A, A, G], changed_at=9)[0] == ("fresh", False)),
        ("wait-login: ログイン画面 → 本人がログイン → fresh、 ログイン画面を見た印が立つ",
         (lambda r: r[0] == ("fresh", True) and len(r[2]) == 1)(_fake_run([L] * 20 + [G], changed_at=45, wait_login=300))),
        ("wait-login: 誰もログインしなければ上限で timeout", (lambda r: r[0] == ("timeout", True) and 299 <= r[1] <= 302)(
            _fake_run([L], wait_login=300))),
        ("中に着いたのに状態が変わらない → stale (撃ち直して決める)", _fake_run([G])[0] == ("stale", False)),
        ("tab が見えない (AppleScript 不可) → 状態の更新だけで fresh", _fake_run([None], changed_at=20)[0] == ("fresh", False)),
        ("tab が見えず状態も変わらない → timeout", (lambda r: r[0] == ("timeout", False) and r[1] <= 42)(_fake_run([None]))),
        ("tab を本人が閉じた → 状態の更新だけを待つ", _fake_run([loading, "gone"], changed_at=10)[0] == ("fresh", False)),
        ("tab が見えない wait-login は最初に 1 回だけ言う", len(_fake_run([None], changed_at=30, wait_login=300)[2]) == 1),
        ("app 名は固定の一覧からだけ (AppleScript の本文に入るため)", _rejects_unknown_app()),
    ]


def _rejects_unknown_app():
    try:
        BrowserTab('Evil" & (do shell script "x") & "')
    except ValueError:
        return True
    return False


if __name__ == "__main__":  # 直接実行 = selftest (scripts/lib の module の流儀。 run-all-checks が引数なしで呼ぶ)
    ok = True
    for name, good in selftest_cases():
        ok &= bool(good)
        print("PASS" if good else "FAIL", name)
    print("selftest", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
