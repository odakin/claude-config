#!/usr/bin/env python3
"""campussquare-client.py — 大学の教務システム CampusSquare for WEB を **browser session cookie で script から読む** (画面 drive 不要)。

背景: 学内 SSO (Shibboleth SP + 外部 IdP) の奥にあり、 user が発行できる API credential が無い。 残る機械経路 =
user が browser でログイン済みの session cookie を再利用する (= `chromium-cookies.py`)。 形は `garoon-client.py`
と同じ (切れ判定 → 起動中の browser に裏で入り直させる → 1 回だけ撃ち直す)。 入り直しの部品 = scripts/lib/sso_cookie_session.py
(入り直せた = 読み直した cookie を server が受け入れた時だけ)、 一般則 = conventions/machine-route-first.md#sso-session-recovery。
script はパスワードも OTP も扱わない。

subcommand:
  syllabus-search [--year Y] [--code C] [--name 科目名] [--teacher 教員名] [--word 語]   シラバス検索 (一覧)
  syllabus <時間割番号> [--year Y] [--html]                                           シラバス 1 件の本文 (text)
  roster-csv --out-dir DIR [--year Y] [--exam 1]                                      全担当科目の履修者名簿 CSV を DIR に保存 (成績登録画面の CSV 一括ダウンロード)
  dl-list [--folder 語] [--from D] [--to D]                                           ダウンロードセンターの配布資料の一覧 (フォルダ | fileId | ファイル名 | 登録日 | サマリ)
  dl-get <fileId>... --out-dir DIR [--extract] [--from D] [--to D]                    配布資料を DIR に保存 (--extract = zip を DIR/<zip の stem>/ に展開、 パスワード付きの PDF は暗号化を外した写しを同じ所に。 パスワードはサマリ欄から)
  dl-missing --have DIR [--have DIR] [--folder 語] [--match 正規表現] [--from D] [--to D]  手元に無い配布資料 (名前の鍵 = NFKC・拡張子なし・空白なし で突き合わせ。 無ければ無出力)
  schedule [--from YYYY-MM] [--months N] [--days]                                    自分のスケジュール (時間割のコマと教室)。 既定 = 曜日・時限・科目・教室ごとの回数、 --days = 1 日 1 行 (TSV)
  get <path>                                                                         任意 path を GET (debug 用)
  status                                                                            いま読めるか (GET 1 本、 切れていれば復帰を試す)
  doctor                                                                             配線だけ (cookie を復号できて値が壊れていないか。 network なし、 健全なら無言)
  probe [path ...]                                                                   切れ方の採取 (cookie なし・偽の session id で撃ち、 302 の行き先・Set-Cookie の名前・切れ判定を並べる)

共通 option: --base https://<host> (env CAMPUSSQUARE_BASE)  --browser brave|chrome  --profile Default
             --browser-refresh off|keep|close (env CAMPUSSQUARE_BROWSER_REFRESH)  --wait-login 秒  --trace

画面の仕組み (Spring Web Flow・シラバス検索の form・教員ログイン時の担当者欄の罠・CSV の形式) = conventions/campussquare.md。
切れの判定 = 3xx で別 host (IdP) / `Shibboleth.sso` / `login` か `ssologin` の path へ、 または 200 でログイン画面か「認証エラー」 の title。
  未ログインの portal は ssologin.do への 302 と一緒に未認証の JSESSIONID を配る (実測、 `probe` で見える)。
  ⚠️ CampusSquare 本体の timeout 画面の形は未実測 (出たら expired() に足して selftest に回帰を足す)。

⚠️ 出力に cookie / flow key / 配布資料のパスワードを出さない (dl-list はサマリ欄のパスワードを *** に伏せる)。
  取得した学生情報 (名簿・成績) と配布資料は private 層にしか置かない。 書き込み (成績登録・資料の登録等) は射程外。
"""
import argparse
import html as htmllib
import io
import os
import re
import sys
import time
import unicodedata
import zipfile
import zlib
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote_to_bytes, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib.browser_tab import BROWSER_APPS, selftest_cases as _tab_selftest_cases  # noqa: E402
from lib.sso_cookie_session import (  # noqa: E402
    EX_LOGIN, CookieSession, LoginRequired, doctor as _doctor, print_probe, probe_anonymous,
    selftest_cases as _session_selftest_cases, site_selftest_cases)

CTX = "/campusweb"
PORTAL = CTX + "/campusportal.do?page=main"
FLOW = CTX + "/campussquare.do"
SYLLABUS_FLOW = "SYW0001000-flow"
GRADE_FLOW = "SIW0001000-flow"  # 成績登録 / 履修者名簿ダウンロード
DL_FLOW = "SDW0001000-flow"  # ダウンロードセンター (フォルダごとの配布資料の一覧)
DL_FILE_FLOW = "SDW-filerefer-flow"  # 配布資料 1 本 (&fileId=<N>、 302 → 200 の attachment)
SCHEDULE_FLOW = "PTW0001200-flow"  # スケジュール管理 (自分の時間割のコマ・休講・補講の月表示。 教室つき)
PROBE_PATHS = [PORTAL, f"{FLOW}?_flowId={SYLLABUS_FLOW}"]


def _say(msg):
    sys.stdout.flush()  # 標準出力の行 (保存した path) と順序が入れ替わらないように
    print(f"CampusSquare: {msg}", file=sys.stderr, flush=True)


def expired(code, location, text, base_host):
    """HTTP 応答が「ログイン切れ」 なら理由、 そうでなければ None。"""
    if code in (301, 302, 303, 307):
        u = urlparse(location)
        if u.hostname and u.hostname != base_host:
            return "SSO redirect"
        # 未ログインの portal は同じ host の ssologin.do へ 302 (実測) = /login だけを見ると「読める」 と誤る
        if "Shibboleth.sso" in u.path or re.search(r"/(sso)?login\b", u.path, re.I):
            return "login redirect"
    if code == 200 and re.search(r"<title>[^<]*(ログイン|Login)", (text or "")[:3000], re.I):
        return "login page"
    # session 切れの flow は 200 で「認証エラー」 画面 (form authorizationError) を返す (2026-09-19 実測)
    if code == 200 and re.search(r'<title>\s*認証エラー|<form[^>]*name="authorizationError"', (text or "")[:3000]):
        return "auth error page"
    if code in (401, 403):
        return str(code)
    return None


def inside(url, base_host):
    u = urlparse(url)
    return u.scheme == "https" and u.hostname == base_host and u.path.startswith(CTX) and "Shibboleth.sso" not in u.path


def html_to_text(page):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"</(tr|p|div|h\d|li)>", "\n", t, flags=re.I)
    t = re.sub(r"</t[dh]>", " | ", t, flags=re.I)
    t = htmllib.unescape(re.sub(r"<[^>]+>", "", t))
    return "\n".join(line.strip() for line in t.splitlines() if line.strip() and line.strip() != "|")


def form_fields(page, form_name):
    """name=form_name の form の hidden/text input を {name: value} で返す (select は value="" 扱い)。"""
    m = re.search(r'<form[^>]*name="%s"[^>]*>(.*?)</form>' % re.escape(form_name), page, re.S)
    if not m:
        raise SystemExit(f"form {form_name} が見つからない (= 画面構造の変化か未ログイン)")
    out = {}
    for tag in re.findall(r"<input[^>]*>", m.group(1)):
        n = re.search(r'name="([^"]+)"', tag)
        if n and not re.search(r'type="(button|reset|submit)"', tag):
            v = re.search(r'value="([^"]*)"', tag)
            out[n.group(1)] = htmllib.unescape(v.group(1)) if v else ""
    return out


def result_rows(page):
    """検索結果の表 → [{cells:[...], refer:(年度, 所属, 番号, locale) | None}]。"""
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [htmllib.unescape(re.sub(r"<[^>]+>|\s+", " ", c)).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        ref = re.search(r"refer\('(\d+)','([^']*)','([^']+)','([^']+)'\)", tr)
        if cells and ref:
            rows.append({"cells": cells, "refer": ref.groups()})
    return rows


# ── 自分のスケジュール (conventions/campussquare.md#teacher-schedule) ──
_SLOT = re.compile(r"^(\d+)限:(.+)@([^@]+)$")
_WEEKDAY = "月火水木金土日"


def schedule_parse(page):
    """スケジュール管理の月表示 → [{date, period, course, room, kind}]。 時限つきの行だけ (「[休日 ]日曜日」 の行は捨てる)。
    日付は各日の「予定を足す」 link (addSchedule(YYYYMMDD)) から取る。 科目名・教室は NFKC (全角の数字・英字を半角に)。
    kind = 行の span の class (開講 = kaiko。 休講・補講は別の class = 画面の凡例の色分け)。"""
    out = []
    for td in re.findall(r"<td[^>]*>(.*?)</td>", page, re.S):
        d = re.search(r"addSchedule\((\d{8})\)", td)
        if not d:
            continue
        ymd = d.group(1)
        for kind, text in re.findall(r'<span class="([^"]*)">(.*?)</span>', td, re.S):
            t = unicodedata.normalize("NFKC", htmllib.unescape(re.sub(r"<[^>]+>", "", text))).strip()
            m = _SLOT.match(t)
            if m:
                out.append({"date": f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}", "period": m.group(1),
                            "course": m.group(2).strip(), "room": m.group(3).strip(), "kind": kind})
    return out


def schedule_month(page):
    """月表示の見出しの (年, 月)。 無ければ画面構造の変化として止める。"""
    m = re.search(r"(\d{4})年(\d{1,2})月", html_to_text(page))
    if not m:
        raise SystemExit("スケジュール管理の月の見出しが見つからない (= 画面構造の変化か、 週単位の表示になっている)")
    return int(m.group(1)), int(m.group(2))


def schedule_summary(rows):
    """行 → 曜日・時限・科目・教室・種別ごとに [(曜日, 時限, 科目, 教室, 種別, 回数, 初回, 最終)]。 同じ日の同じ行は 1 回と数える
    (旧課程・新課程で時間割番号が 2 つある授業は、 同じ「時限:科目@教室」 が 2 行出る)。"""
    from datetime import date as _date
    days = {}
    for r in rows:
        wd = _WEEKDAY[_date.fromisoformat(r["date"]).weekday()]
        days.setdefault((wd, r["period"], r["course"], r["room"], r["kind"]), set()).add(r["date"])
    order = {c: i for i, c in enumerate(_WEEKDAY)}
    return [(*k, len(v), min(v), max(v)) for k, v in sorted(days.items(), key=lambda kv: (order[kv[0][0]], kv[0][1:]))]


# ── ダウンロードセンター (conventions/campussquare.md#download-center) ──
_WS = re.compile(r"[ \t\r\n\f\v\xa0]+")  # \s は全角空白も潰すので使わない (フォルダ名に全角空白が入る)


class _DLParser(HTMLParser):
    """ダウンロードセンターの一覧 HTML を歩く。 script の中身は data 扱い = JavaScript の行の雛形 (<tr class="fileRecord">) は拾わない。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.folders, self.files = [], []
        self._tbody, self._table = [], []  # 開いている tbody / table: フォルダの中身 (detail<N>) / ファイルの表 (fileTable<N>) なら N、 他は None
        self._folder = self._rec = self._cell = None

    @staticmethod
    def _push(stack, attr_id, prefix):
        m = re.fullmatch(prefix + r"(\d+)", attr_id or "")
        stack.append(m.group(1) if m else None)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if tag == "tbody":
            self._push(self._tbody, a.get("id"), "detail")
        elif tag == "table":
            self._push(self._table, a.get("id"), "fileTable")
        elif tag == "tr":
            self._close_row()
            m = re.fullmatch(r"folder(\d+)", a.get("id") or "")
            if m:
                parent = next((t for t in reversed(self._tbody) if t), None)
                self._folder = {"id": m.group(1), "parent": parent, "cells": []}
            elif "fileRecord" in cls and self._table and self._table[-1]:
                self._rec = {"folder_id": self._table[-1], "file_id": None, "at": None, "cells": []}
        elif tag == "td" and (self._rec is not None or (self._folder is not None and "accordion" in cls)):
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")
        elif tag == "a" and self._rec is not None and not self._rec["file_id"]:
            m = re.search(r"[?&]fileId=(\d+)", a.get("href") or "")
            if m:
                self._rec["file_id"], self._rec["at"] = m.group(1), len(self._rec["cells"])

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(_WS.sub(" ", data))

    def handle_endtag(self, tag):
        if tag == "td" and self._cell is not None:
            text = "\n".join(x.strip() for x in "".join(self._cell).split("\n") if x.strip())
            (self._rec if self._rec is not None else self._folder)["cells"].append(text)
            self._cell = None
        elif tag == "tr":
            self._close_row()
        elif tag == "table" and self._table:
            self._close_row()
            self._table.pop()
        elif tag == "tbody" and self._tbody:
            self._tbody.pop()

    def _close_row(self):
        self._cell = None
        if self._folder is not None:
            c = self._folder.pop("cells") + [""] * 4  # 列 = フォルダ名 / 公開期間 / オーナー / サマリ
            self._folder.update(name=c[0], period=c[1], owner=c[2], summary=c[3])
            self.folders.append(self._folder)
        if self._rec is not None and self._rec["file_id"]:
            c, i = self._rec.pop("cells"), self._rec.pop("at")  # 列 = (削除の checkbox) / ファイル名 / 登録日 / サマリ
            c += [""] * 3
            self._rec.update(name=c[i], date=c[i + 1], summary=c[i + 2])
            self.files.append(self._rec)
        self._folder = self._rec = None


def dl_parse(page):
    """ダウンロードセンターの一覧 HTML → (フォルダ, ファイル行)。 純関数。
    フォルダ = {id, parent, name, path, period, owner, summary} / ファイル行 = {folder_id, folder, file_id, name, date, summary}。
    下位フォルダは親フォルダの中身 (tbody detail<親>) の中の表に並び、 親のファイルの表はその後ろに来る (実測)
    = 行の並び順でなく、 ファイルの表の id (fileTable<フォルダ id>) で帰属を決める。"""
    p = _DLParser()
    p.feed(page)
    p.close()
    p._close_row()
    by_id = {f["id"]: f for f in p.folders}

    def path(f, seen):
        par = by_id.get(f["parent"])
        return (path(par, seen | {f["id"]}) + " / " if par and par["id"] not in seen else "") + f["name"]

    for f in p.folders:
        f["path"] = path(f, {f["id"]})
    for r in p.files:
        f = by_id.get(r["folder_id"])
        r["folder"] = f["path"] if f else f"(フォルダ {r['folder_id']})"
    return p.folders, p.files


def dl_window(page):
    """一覧の「公開期間から検索」 の窓 (dayFrom, dayTo)。 画面の既定は今日の前後 1 か月 (実測)。 見つからなければ None。"""
    f = [re.search(r'<input[^>]*id="%s"[^>]*value="([^"]*)"' % k, page) for k in ("dayFrom", "dayTo")]
    return (f[0].group(1), f[1].group(1)) if all(f) else None


def jp_date(s):
    """2026-09-01 / 2026/9/1 / 20260901 → 画面の書式 2026年09月01日。"""
    m = re.fullmatch(r"(\d{4})[-/.]?(\d{1,2})[-/.]?(\d{1,2})", s.strip())
    if not m:
        raise SystemExit(f"日付は YYYY-MM-DD で ({s})")
    return "%s年%02d月%02d日" % (m.group(1), int(m.group(2)), int(m.group(3)))


def _fold(s):
    return unicodedata.normalize("NFKC", s).casefold()


# 「パスワード「X」」「パスワードは「X」です」 (実測の 2 形) と「パスワード: X」 (PW / Password も同じ扱い)
_PW = re.compile(r"((?:パスワード|PW|[Pp]assword)[^「」\n]{0,8}「)([^」\n]+)(」)"
                 r"|((?:パスワード|PW|[Pp]assword)\s*(?:は)?\s*[:：]\s*)([\x21-\x7e]+)")


def _bare_secret(s):
    """サマリ欄の 1 行が 1 語の ASCII だけ (説明なしで値だけを書いた欄、 実測 1 件) = パスワードとみなす。
    文字・数字・記号のうち 2 種以上を含み URL でないものに限る (英単語 1 語の説明を伏せないため)。"""
    return (bool(re.fullmatch(r"[\x21-\x7e]{4,64}", s)) and not re.match(r"https?://", s)
            and sum(bool(re.search(c, s)) for c in (r"[A-Za-z]", r"\d", r"[^A-Za-z\d]")) >= 2)


def summary_passwords(summary):
    """サマリ欄に書かれたパスワードの候補 (書かれた順、 重複なし)。 無ければ []。"""
    found = [m.group(2) or m.group(5) for m in _PW.finditer(summary or "")]
    if not found:
        found = [x.strip() for x in (summary or "").split("\n") if _bare_secret(x.strip())]
    return list(dict.fromkeys(found))


def mask_summary(summary):
    """表示用: サマリ欄のパスワードを *** に伏せる (候補として拾うものと同じ範囲)。"""
    s = _PW.sub(lambda m: m.group(1) + "***" + m.group(3) if m.group(1) else m.group(4) + "***", summary or "")
    return "\n".join("***" if _bare_secret(x.strip()) else x for x in s.split("\n"))


def safe_name(name, fallback):
    """file 名から dir の部分と制御文字を落とす。 空・. ・.. なら fallback。"""
    n = re.sub(r"[\x00-\x1f\x7f]", "", (name or "").replace("\\", "/")).split("/")[-1].strip()
    return n if n not in ("", ".", "..") else fallback


def disposition_filename(disp):
    """Content-Disposition の file 名。 実測の形 = filename="<UTF-8 を percent-encode>"。 filename*= (RFC 5987) と、
    encode されずに生の bytes が来た場合 (requests は header を latin-1 で読む) も扱う。 dir の部分は落とす。 無ければ None。
    ⚠️ server は Java の URLEncoder の形 = 空白を + に、 + そのものを %2B にする (実測: ASCII だけの名前でも空白が + で来た)。
    値が URLEncoder の出力の文字 (英数字 . - * _ + %XX) だけなら + を空白に戻して decode する。 生の空白・非 ASCII を含む値は生のまま読む。"""
    m = re.search(r"filename\*\s*=\s*([\w-]+)'[^']*'([^;\s]+)", disp or "", re.I)
    if m:
        try:
            return safe_name(unquote_to_bytes(m.group(2).strip('"')).decode(m.group(1)), None)
        except (LookupError, UnicodeDecodeError):
            pass
    m = re.search(r'filename\s*=\s*(?:"([^"]*)"|([^;]+))', disp or "", re.I)
    if not m:
        return None
    raw = (m.group(1) if m.group(1) is not None else m.group(2)).strip()
    if re.fullmatch(r"(?:[A-Za-z0-9.*_+-]|%[0-9A-Fa-f]{2})+", raw):
        b = unquote_to_bytes(raw.replace("+", " "))
    else:
        try:
            b = raw.encode("latin-1")
        except UnicodeEncodeError:
            return safe_name(raw, None)
    for enc in ("utf-8", "cp932"):
        try:
            return safe_name(b.decode(enc), None)
        except UnicodeDecodeError:
            pass
    return safe_name(b.decode("utf-8", "replace"), None)


def zip_name(info):
    """zip の中の file 名。 UTF-8 flag (0x800) の無い名前は zipfile が cp437 で読むので、 CP932 として読み直す (実測 = CP932)。"""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("cp932")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def member_path(name):
    """zip の中の path → 展開先の中の相対 Path (.. と絶対 path を落とす)。 __MACOSX / .DS_Store は None。"""
    parts = [x for x in name.replace("\\", "/").split("/") if x not in ("", ".", "..")]
    if not parts or parts[0] == "__MACOSX" or parts[-1] == ".DS_Store":
        return None
    return Path(*parts)


def zip_encrypted(body):
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        return any(i.flag_bits & 1 for i in zf.infolist())


def zip_read_all(body, passwords, label="zip"):
    """zip の中身を全部読む (CRC まで検める)。 暗号化されていれば passwords を順に試す (従来の ZipCrypto。 AES は未対応)。
    返り値 = ([(相対 Path, bytes)], 開けた候補の index か None (暗号化なし))。 パスワードの値は出力しない。"""
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        infos = [(i, member_path(zip_name(i))) for i in zf.infolist() if not i.is_dir()]
        infos = [(i, rel) for i, rel in infos if rel is not None]
        if not any(i.flag_bits & 1 for i, _ in infos):
            return [(rel, zf.read(i)) for i, rel in infos], None
        if not passwords:
            raise SystemExit(f"{label}: 暗号化された zip だが、 サマリ欄にパスワードの記載が見つからない")
        for k, pw in enumerate(passwords):
            variants = [pw.encode("utf-8")]
            try:
                variants.append(pw.encode("cp932"))
            except UnicodeEncodeError:
                pass
            for b in dict.fromkeys(variants):
                try:
                    return [(rel, zf.read(i, pwd=b)) for i, rel in infos], k
                except NotImplementedError as e:  # RuntimeError の子 = 先に捕まえる (AES 等)
                    raise SystemExit(f"{label}: zip の暗号・圧縮の方式に未対応 ({e})")
                except (RuntimeError, zipfile.BadZipFile, zlib.error):
                    continue  # パスワード違い (header の検査で落ちるか、 偶然通って CRC で落ちる)
        raise SystemExit(f"{label}: サマリ欄のパスワード ({len(passwords)} 件) のどれでも開けない")


def pdf_needs_pass(body):
    """パスワードが無いと開けない PDF か。 PyMuPDF が要る (無ければ止まる)。"""
    try:
        import fitz
    except ImportError:
        raise SystemExit("PDF の復号には PyMuPDF (fitz) が要る")
    with fitz.open(stream=body, filetype="pdf") as doc:
        return bool(doc.needs_pass)


def pdf_decrypt(body, passwords, label="pdf"):
    """パスワード付きの PDF を、 passwords を順に試して開き、 暗号化を外した bytes にする (配布資料の議事録などがこの形)。
    返り値 = (bytes, 開けた候補の index)。 暗号化なしなら (None, None)。 パスワードの値は出力しない。 PyMuPDF が要る。"""
    if not pdf_needs_pass(body):
        return None, None
    if not passwords:
        raise SystemExit(f"{label}: パスワード付きの PDF だが、 サマリ欄にパスワードの記載が見つからない")
    import fitz
    with fitz.open(stream=body, filetype="pdf") as doc:
        for k, pw in enumerate(passwords):
            if doc.authenticate(pw):
                return doc.tobytes(encryption=fitz.PDF_ENCRYPT_NONE), k
    raise SystemExit(f"{label}: サマリ欄のパスワード ({len(passwords)} 件) のどれでも開けない")


def name_key(name):
    """配布資料の名前と手元の file・dir の名前を突き合わせる鍵: NFKC (全角括弧 → 半角) + 拡張子 .zip/.pdf を外す + 空白を消す。"""
    n = unicodedata.normalize("NFKC", name or "")
    n = re.sub(r"\.(zip|pdf)$", "", n.strip(), flags=re.I)
    return re.sub(r"\s+", "", n)


def missing_rows(rows, have_names, match=""):
    """一覧のファイル行のうち、 手元の名前 (have_names) に鍵が一致するものが無い行。 match = ファイル名への正規表現 (空なら全部)。"""
    have = {name_key(x) for x in have_names}
    return [r for r in rows if (not match or re.search(match, r["name"])) and name_key(r["name"]) not in have]


def save_no_clobber(out, body):
    """out に保存。 同名で中身が違えば上書きせず <stem>-HHMMSS<suffix> にする。 返り値 = (書いた path, "new"|"same"|"renamed")。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        if out.read_bytes() == body:
            return out, "same"
        out = out.with_name(f"{out.stem}-{time.strftime('%H%M%S')}{out.suffix}")
        out.write_bytes(body)
        return out, "renamed"
    out.write_bytes(body)
    return out, "new"


class CampusSquare(CookieSession):
    label = "CampusSquare"
    entry_path = PORTAL
    alive_path = PORTAL  # 生きていれば 200 の portal、 切れていれば ssologin.do への 302
    close_path = CTX

    def expired(self, code, location, text):
        return expired(code, location, text, self.host)

    def inside(self, url):
        return inside(url, self.host)

    def _follow(self, r):
        """flow 内の 302 (同じ host。 別 host なら _request が切れとして先に捕まえている) を追って画面 HTML にする。"""
        for _ in range(4):
            if r.status_code not in (301, 302, 303):
                break
            r = self._request("GET", urlparse(r.headers["Location"])._replace(scheme="", netloc="").geturl())
        if r.status_code != 200:
            raise SystemExit(f"{r.request.method} {urlparse(r.url).path} {r.status_code}")
        return r.text

    def open_flow(self, flow_id):
        """flow を開始して最初の画面 HTML を返す。"""
        return self._follow(self._request("GET", f"{FLOW}?_flowId={flow_id}"))

    def post_flow(self, data):
        """form を POST して次の画面 HTML を返す (Web Flow は POST → 302 → GET で画面を返す)。"""
        return self._follow(self._request("POST", FLOW, data=data))

    def syllabus_search(self, year, code="", name="", teacher="", word=""):
        page = self.open_flow(SYLLABUS_FLOW)
        f = form_fields(page, "SearchForm")
        f.update({"_eventId": "search", "nendo": str(year), "kaikoKubunCode": "", "kyokannm": teacher,
                  "kaikoKamokunm": name, "jikanwaricd": code, "yobi": "", "jigen": "", "freeWord": word,
                  "_displayCount": "200"})
        page = self.post_flow(f)
        return page, result_rows(page)

    def syllabus(self, year, code):
        page, rows = self.syllabus_search(year, code=code)
        hits = [r for r in rows if r["refer"][2] == code]
        if not hits:
            raise SystemExit(f"{year} 年度の時間割番号 {code} が検索で見つからない")
        y, shozoku, jcd, locale = hits[0]["refer"]
        f = form_fields(page, "ReferForm")
        f.update({"_eventId": "input", "nendo": y, "jikanwariShozokuCode": shozoku, "jikanwaricd": jcd, "locale": locale})
        return self.post_flow(f)

    def roster_csv(self, year, exam="1"):
        """成績登録画面の「CSV一括ダウンロード」 = 全担当科目の履修者名簿 (bytes は CP932 のまま)。 読むだけ。
        画面の downloadAllCsv(年度, 試験区分) と同じ POST。 年度・学期は画面が開いた時点の学期で決まる。"""
        page = self.open_flow(GRADE_FLOW)
        f = form_fields(page, "downloadForm")
        f.update({"_eventId": "outputCsvAll", "nendo": str(year), "shikenKbnCd": exam})
        r = self._request("POST", FLOW, data=f)
        for _ in range(4):
            if r.status_code not in (301, 302, 303):
                break
            r = self._request("GET", urlparse(r.headers["Location"])._replace(scheme="", netloc="").geturl())
        disp = r.headers.get("Content-Disposition", "")
        if r.status_code != 200 or "csv" not in (r.headers.get("Content-Type", "") + disp).lower():
            title = re.search(r"<title>(.*?)</title>", r.text, re.S)
            raise SystemExit(f"名簿 CSV が返らなかった ({r.status_code} {title.group(1).strip() if title else ''})")
        name = re.search(r'filename="?([^";]+)', disp)
        return r.content, (name.group(1) if name else f"regis{time.strftime('%Y%m%d')}.csv")

    def dl_list(self, day_from=None, day_to=None):
        """ダウンロードセンターの一覧画面 HTML。 公開期間の窓を変える時だけ、 画面の「表示」 と同じ POST (event listup) をする。"""
        page = self.open_flow(DL_FLOW)
        if day_from or day_to:
            f = form_fields(page, "conditionForm")
            f["_eventId"] = "listup"
            if day_from:
                f["dayFrom"] = jp_date(day_from)
            if day_to:
                f["dayTo"] = jp_date(day_to)
            page = self.post_flow(f)
        return page

    def schedule(self, start=None, months=1):
        """自分のスケジュールを start (YYYY-MM、 既定 = 今月) から months か月分 = schedule_parse の行 (その月の外の日は捨てる)。
        月は画面の「prev / next」 と同じ POST (form ScheduleListForm、 event setPrevMonth / setNextMonth) で送る。 読むだけ。"""
        page = self.open_flow(SCHEDULE_FLOW)
        cur = schedule_month(page)
        want = tuple(map(int, start.split("-"))) if start else cur
        index = lambda ym: ym[0] * 12 + ym[1] - 1
        month_of = lambda i: (i // 12, i % 12 + 1)

        def move(page, k):
            f = form_fields(page, "ScheduleListForm")
            f["_eventId"] = "setNextMonth" if k > 0 else "setPrevMonth"
            expect = month_of(index(schedule_month(page)) + k)
            page = self.post_flow(f)
            if schedule_month(page) != expect:
                raise SystemExit(f"月を送れなかった ({f['_eventId']} の後が {schedule_month(page)}、 期待 {expect})")
            return page

        while schedule_month(page) != want:
            page = move(page, 1 if index(want) > index(schedule_month(page)) else -1)
        rows, seen = [], set()
        for i in range(months):
            if i:
                page = move(page, 1)
            y, m = schedule_month(page)
            for r in schedule_parse(page):
                key = tuple(r.values())
                if r["date"][:7] == f"{y:04d}-{m:02d}" and key not in seen:
                    seen.add(key)
                    rows.append(r)
        return rows

    def dl_get(self, file_id):
        """配布資料 1 本 = (bytes, file 名, Content-Type)。 GET → 302 → 200 の attachment (file 名は Content-Disposition)。"""
        r = self._request("GET", f"{FLOW}?_flowId={DL_FILE_FLOW}&fileId={int(file_id)}")
        for _ in range(4):
            if r.status_code not in (301, 302, 303):
                break
            r = self._request("GET", urlparse(r.headers["Location"])._replace(scheme="", netloc="").geturl())
        ctype, disp = r.headers.get("Content-Type", ""), r.headers.get("Content-Disposition", "")
        if r.status_code != 200 or ("attachment" not in disp.lower() and "html" in ctype.lower()):
            title = re.search(r"<title>(.*?)</title>", r.text[:5000], re.S) if "html" in ctype.lower() else None
            raise SystemExit(f"fileId {file_id} の file が返らなかった ({r.status_code} {ctype} "
                             f"{title.group(1).strip() if title else ''})")
        return r.content, disposition_filename(disp) or f"file-{int(file_id)}", ctype


def doctor(browser, profile, base):
    """script 経路の配線だけを見る (cookie を復号できて値が壊れていないか)。 network なし。 健全・対象外なら []。"""
    if not base:
        return []
    return _doctor("CampusSquare", browser, profile, [urlparse(base).hostname])


def _zipcrypto_zip(name_bytes, data, pwd):
    """selftest 用: 従来の ZipCrypto で暗号化した stored の 1 本入り zip を組む (zipfile は暗号化して書けない)。
    file 名は bytes のまま入れ、 UTF-8 flag は立てない (= 実測の CP932 の名前の形)。"""
    import struct
    crc = zlib.crc32(data) & 0xFFFFFFFF
    k = [0x12345678, 0x23456789, 0x34567890]

    def upd(c):
        k[0] = zlib.crc32(bytes([c]), k[0] ^ 0xFFFFFFFF) ^ 0xFFFFFFFF
        k[1] = ((k[1] + (k[0] & 0xFF)) * 134775813 + 1) & 0xFFFFFFFF
        k[2] = zlib.crc32(bytes([k[1] >> 24]), k[2] ^ 0xFFFFFFFF) ^ 0xFFFFFFFF

    for c in pwd:
        upd(c)

    def enc(buf):
        out = bytearray()
        for c in buf:
            t = (k[2] | 2) & 0xFFFF
            out.append(c ^ (((t * (t ^ 1)) >> 8) & 0xFF))
            upd(c)
        return bytes(out)

    body = enc(bytes(11) + bytes([crc >> 24])) + enc(data)
    lh = struct.pack("<4s5H3L2H", b"PK\x03\x04", 20, 1, 0, 0, 0, crc, len(body), len(data), len(name_bytes), 0) + name_bytes
    cd = struct.pack("<4s6H3L5H2L", b"PK\x01\x02", 20, 20, 1, 0, 0, 0, crc, len(body), len(data), len(name_bytes),
                     0, 0, 0, 0, 0, 0) + name_bytes
    return lh + body + cd + struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 1, 1, len(cd), len(lh) + len(body), 0)


def _dl_selftest_cases():
    """ダウンロードセンターの純関数の回帰 (合成の HTML と zip。 実在の資料名・パスワードは入れない)。"""
    import tempfile
    rec = ('<tr class="fileRecord"><td class="delCheckTd"></td><td><a href="/campusweb/campussquare.do?_flowId='
           'SDW-filerefer-flow&amp;fileId={id}">{name}</a></td><td>{date}</td><td>{summ}</td></tr>')
    head = ('<tr id="folder{id}"><td class="accordion"{st}><img src="x.gif">{name} </td><td class="accordion"{st}>'
            '2026年4月1日&nbsp;-&nbsp;2027年3月31日</td><td class="accordion"{st}>{owner}</td>'
            '<td class="accordion"{st}>{summ}</td><td><form name="folderForm{id}"></form></td></tr>')
    page = (
        '<script>var row = \'<tr class="fileRecord"><td><a href="/campusweb/campussquare.do?_flowId=SDW-filerefer-flow'
        '&fileId=\' + res.fileId + \'">\' + res.fileName + \'</a></td>\';</script>'
        '<form name="conditionForm" method="post" action="/campusweb/campussquare.do">'
        '<input type="hidden" name="_flowExecutionKey" value="_cA_kB"><input type="hidden" name="_eventId">'
        '<input id="dayFrom" name="dayFrom" class="datepicker" type="text" value="2026年09月01日">'
        '<input id="dayTo" name="dayTo" class="datepicker" type="text" value="2026年11月01日">'
        '<input type="button" value="表示" onclick="return listUp()"></form>'
        '<table class="simpleTable"><th>フォルダ名</th>'
        + head.format(id=10, st="", name="会議資料", owner="事務課", summ="クリックするとフォルダが開きます。")
        + '<tbody class="innerSimpleTable hidden" id="detail10"><tr><td id="tdHead" colspan="5"></td></tr><tr><td colspan="5">'
          '<div><table class="simpleTable recursiveSimpleTable"><tr><th>フォルダ名</th></tr>'
        + head.format(id=11, st=' style="background:#f0f0f0"', name="分科会　A", owner="事務課", summ="分科会")
        + '<tbody class="innerSimpleTable hidden" id="detail11"><tr><td colspan="5">'
          '<table class="innerSimpleTable" id="fileTable11"><th>ファイル名</th>'
          '<tr id="fileNotFound"><td colspan="4">ファイルは登録されていません</td></tr></table></td></tr></tbody>'
          '</table></div></td></tr>'
          '<tr><td colspan="5"><table class="innerSimpleTable" id="fileTable10"><th></th><th>ファイル名</th>'
        + rec.format(id=101, name="第1回資料&amp;別紙.zip", date="2026年4月10日 09:00:00", summ="パスワード「Ab1-cd」")
        + rec.format(id=102, name="第2回資料.zip", date="2026年5月10日 09:00:00", summ="説明の行<br>パスワードは「Zz9_yy」です。")
        + rec.format(id=103, name="案内.zip", date="2026年6月1日 10:00:00", summ="q7&amp;Wx2#k")
        + rec.format(id=104, name="日程.pdf", date="2026年6月2日 10:00:00", summ="")
        + '</table></td></tr></tbody>'
        + head.format(id=20, st="", name="別の資料", owner="人事課", summ="別の資料")
        + '<tbody class="innerSimpleTable hidden" id="detail20"><tr><td colspan="5">'
          '<table class="innerSimpleTable" id="fileTable20"><th>ファイル名</th>'
        + rec.format(id=201, name="手引き.pdf", date="2026年4月2日 08:00:00", summ="Handbook")
        + '</table></td></tr></tbody></table>')
    folders, files = dl_parse(page)
    by = {r["file_id"]: r for r in files}
    paths = {f["id"]: f["path"] for f in folders}
    # zip: 暗号化 (CP932 の名前・候補の 1 本目は外れ) と、 暗号化なし (__MACOSX と .. を含む)
    enc = _zipcrypto_zip("資料.pdf".encode("cp932"), b"%PDF-1.4 synthetic", b"Zz9_yy")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a/b.txt", "x")
        zf.writestr("__MACOSX/a/._b.txt", "junk")
        zf.writestr("../evil.txt", "y")
    plain = buf.getvalue()
    got_enc = zip_read_all(enc, ["wrong-1", "Zz9_yy"])
    aes = bytearray(enc)  # 圧縮方式の欄 (local header の 8 byte 目・central directory の 10 byte 目) を 99 = AES の印に
    cd = aes.find(b"PK\x01\x02")
    aes[8:10] = aes[cd + 10:cd + 12] = (99).to_bytes(2, "little")
    unsupported = None
    try:
        zip_read_all(bytes(aes), ["Zz9_yy"])
    except SystemExit as e:
        unsupported = str(e)
    got_plain = zip_read_all(plain, [])
    no_pw = wrong_pw = None
    try:
        zip_read_all(enc, [])
    except SystemExit as e:
        no_pw = str(e)
    try:
        zip_read_all(enc, ["wrong-1"])
    except SystemExit as e:
        wrong_pw = str(e)
    with tempfile.TemporaryDirectory() as d:
        t = Path(d) / "x.zip"
        s1, s2, s3 = save_no_clobber(t, b"1"), save_no_clobber(t, b"1"), save_no_clobber(t, b"2")
        clobber_ok = (s1 == (t, "new") and s2 == (t, "same") and s3[1] == "renamed" and s3[0] != t
                      and t.read_bytes() == b"1" and s3[0].read_bytes() == b"2")
    utf8 = "%E8%B3%87%E6%96%99"  # 資料
    # PDF: 合成のパスワード付き PDF を候補の 2 本目で開く / 暗号化なし / 外れだけ (PyMuPDF が無ければ skip = PASS 扱いにしない)
    try:
        import fitz
        d0 = fitz.open(); d0.new_page().insert_text((72, 72), "minutes synthetic"); plain_pdf = d0.tobytes(); d0.close()
        d1 = fitz.open(stream=plain_pdf, filetype="pdf")
        enc_pdf = d1.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="Oo9-owner", user_pw="Uu1-pw"); d1.close()
        dec, k = pdf_decrypt(enc_pdf, ["bad-1", "Uu1-pw"])
        with fitz.open(stream=dec, filetype="pdf") as d2:
            pdf_ok = k == 1 and not d2.needs_pass and "minutes synthetic" in d2[0].get_text()
        pdf_plain_ok = pdf_decrypt(plain_pdf, ["x"]) == (None, None)
        try:
            pdf_decrypt(enc_pdf, ["bad-1"]); pdf_wrong = None
        except SystemExit as e:
            pdf_wrong = str(e)
        pdf_cases = [
            ("pdf_decrypt: パスワード付きの PDF = 候補を順に試し、 暗号化を外した写しは開ける", pdf_ok),
            ("pdf_decrypt: 暗号化なし = (None, None) / 外れだけ = 止まり、 値を出さない", pdf_plain_ok and bool(pdf_wrong)
             and "Uu1-pw" not in pdf_wrong and "bad-1" not in pdf_wrong),
        ]
    except ImportError:
        print("SKIP pdf_decrypt (PyMuPDF なし)")
        pdf_cases = []
    have = ["第1回資料（一般）", "第2回 資料.zip", "記録/"]
    miss_rows = [{"name": n, "file_id": str(i)} for i, n in enumerate(
        ["第1回資料(一般).zip", "第2回資料.zip", "第3回資料(一般).zip", "2025年度 第9回資料.zip", "記録.pdf"])]
    got_miss = [r["name"] for r in missing_rows(miss_rows, have)]
    return pdf_cases + [
        ("name_key / missing_rows: 全角括弧・空白・拡張子の違いは同じ物、 手元に無いものだけ残す",
         got_miss == ["第3回資料(一般).zip", "2025年度 第9回資料.zip", "記録.pdf"]
         and [r["name"] for r in missing_rows(miss_rows, have, "第3回")] == ["第3回資料(一般).zip"]),
        ("dl_parse: script の中の行の雛形は拾わず、 フォルダ 3 / ファイル 5", len(folders) == 3 and len(files) == 5),
        ("dl_parse: 下位フォルダの path (親 / 子、 全角空白を残す)", paths.get("11") == "会議資料 / 分科会　A"),
        ("dl_parse: 親のファイルの表が下位フォルダの後ろにあっても親に帰属", all(by[i]["folder_id"] == "10" for i in
                                                                    ("101", "102", "103", "104")) and by["201"]["folder_id"] == "20"),
        ("dl_parse: 名前の entity・登録日・<br> のサマリ", by["101"]["name"] == "第1回資料&別紙.zip"
         and by["101"]["date"] == "2026年4月10日 09:00:00" and by["102"]["summary"].split("\n")[0] == "説明の行"),
        ("dl_parse: フォルダの公開期間 (&nbsp;) とオーナー", folders[0]["period"] == "2026年4月1日 - 2027年3月31日"
         and folders[0]["owner"] == "事務課"),
        ("dl_window: 公開期間の検索の窓", dl_window(page) == ("2026年09月01日", "2026年11月01日")),
        ("jp_date: 画面の書式に揃える", jp_date("2026-9-1") == "2026年09月01日" and jp_date("20261107") == "2026年11月07日"),
        ("summary_passwords: 「パスワード「X」」「パスワードは「X」です」 と値だけの欄",
         summary_passwords(by["101"]["summary"]) == ["Ab1-cd"] and summary_passwords(by["102"]["summary"]) == ["Zz9_yy"]
         and summary_passwords(by["103"]["summary"]) == ["q7&Wx2#k"] and summary_passwords("パスワード: Qq1234") == ["Qq1234"]
         and summary_passwords("資料の説明\nKk7#mm2") == ["Kk7#mm2"] and summary_passwords("PW「Pp1-qq」") == ["Pp1-qq"]),
        ("summary_passwords: 説明だけ・空・英単語 1 語は候補にしない", summary_passwords("") == []
         and summary_passwords(by["201"]["summary"]) == [] and summary_passwords("https://example.com/x1") == []),
        ("mask_summary: 値を出さず、 説明は残す", mask_summary(by["101"]["summary"]) == "パスワード「***」"
         and "Zz9_yy" not in mask_summary(by["102"]["summary"]) and "説明の行" in mask_summary(by["102"]["summary"])
         and mask_summary(by["103"]["summary"]) == "***" and mask_summary("Handbook") == "Handbook"
         and mask_summary("資料の説明\nKk7#mm2") == "資料の説明\n***"),
        ("disposition_filename: URLEncoder の形 (+ = 空白、 %2B = +、 ASCII だけの名前も) / 生の値はそのまま",
         disposition_filename(f'attachment; filename="{utf8}+%281%29%2B.zip"') == "資料 (1)+.zip"
         and disposition_filename('attachment; filename="Guide+for+Staff.pdf"') == "Guide for Staff.pdf"
         and disposition_filename('attachment; filename="a b+c.pdf"') == "a b+c.pdf"),
        ("disposition_filename: filename*= / 生の UTF-8 bytes / dir の部分を落とす",
         disposition_filename(f"attachment; filename*=UTF-8''{utf8}.pdf") == "資料.pdf"
         and disposition_filename('attachment; filename="' + "資料.pdf".encode().decode("latin-1") + '"') == "資料.pdf"
         and disposition_filename('attachment; filename="..%2F..%2Fx.zip"') == "x.zip"
         and disposition_filename("inline") is None),
        ("zip_read_all: 暗号化 = 候補を順に試して 2 本目で開く・CP932 の名前を直す",
         got_enc[1] == 1 and [(str(p), b) for p, b in got_enc[0]] == [("資料.pdf", b"%PDF-1.4 synthetic")]),
        ("zip_read_all: 暗号化なし = __MACOSX を落とし、 .. を外す", got_plain[1] is None
         and sorted(str(p) for p, _ in got_plain[0]) == ["a/b.txt", "evil.txt"]),
        ("zip_read_all: 候補なし・外れだけ = 止まり、 値を出さない", bool(no_pw) and bool(wrong_pw)
         and "Zz9_yy" not in (no_pw + wrong_pw) and "wrong-1" not in wrong_pw),
        ("zip_read_all: AES 等の未対応の方式はパスワード違いと読まず「未対応」 で止まる",
         bool(unsupported) and "未対応" in unsupported),
        ("save_no_clobber: 同じ中身は same、 違えば別名 (元を上書きしない)", clobber_ok),
    ]


def _schedule_selftest_cases():
    page = ('<div>2026年10月</div><table><tr><td class="kyujitsu"><div><a onclick="addSchedule(20261004);"></a>'
            '<div class="cal-content"><span class="kaiko">[休日 ]日曜日</span></div></div></td>'
            '<td class="day"><div><a onclick="addSchedule(20261005);"></a><div class="cal-content">'
            '<span class="kaiko">2限:物理学Ａ@９１０１</span><br><span class="kaiko">2限:物理学Ａ@９１０１</span><br>'
            '<span class="kyuko">4限:Ｍ_演習Ｉ@研究室</span></div></div></td>'
            '<td class="day"><div><a onclick="addSchedule(20261012);"></a><div class="cal-content">'
            '<span class="kaiko">2限:物理学Ａ@９１０１</span></div></div></td></tr></table>')
    rows = schedule_parse(page)
    return [
        ("schedule_parse: 休日の行を捨て、 全角を NFKC で半角に", [r["room"] for r in rows] == ["9101", "9101", "研究室", "9101"]
         and rows[0] == {"date": "2026-10-05", "period": "2", "course": "物理学A", "room": "9101", "kind": "kaiko"}
         and rows[2]["kind"] == "kyuko"),
        ("schedule_month: 見出しの年月", schedule_month(page) == (2026, 10)),
        ("schedule_summary: 同じ日の重複は 1 回・曜日つき", schedule_summary(rows) == [
            ("月", "2", "物理学A", "9101", "kaiko", 2, "2026-10-05", "2026-10-12"),
            ("月", "4", "M_演習I", "研究室", "kyuko", 1, "2026-10-05", "2026-10-05")]),
    ]


def selftest():
    host = "cs.example.ac.jp"
    cases = [
        ((302, "https://idp.example.com/auth/saml2/x?SAMLRequest=z", ""), "SSO redirect"),
        ((302, "https://cs.example.ac.jp/Shibboleth.sso/Login?target=x", ""), "login redirect"),
        ((302, "/campusweb/login.do", ""), "login redirect"),
        ((302, "/campusweb/ssologin.do", ""), "login redirect"),
        ((200, "", "<html><head><title>ログイン</title>"), "login page"),
        ((200, "", '<title>認証エラー</title><form name="authorizationError" method="post">'), "auth error page"),
        ((302, "/campusweb/campussquare.do?_flowExecutionKey=_cX_kY", ""), None),
        ((200, "", "<title>CampusSquare for WEB</title>"), None),
    ]
    ok = True
    for (code, loc, text), want in cases:
        got = expired(code, loc, text, host)
        ok &= got == want
        print("PASS" if got == want else "FAIL", code, loc[:40], "->", got)
    page = ('<form name="ReferForm" action="/campusweb/campussquare.do"><input type="hidden" name="_flowExecutionKey" '
            'value="_cA_kB"><input type="hidden" name="_eventId" value="input"><input type="hidden" name="secchikbncd">'
            '</form><table><tr><td>1</td><td>学科</td><td>後期</td><td>金2</td><td>123456</td><td>科目&amp;名</td><td>'
            '<a onclick="refer(\'2026\',\'99\',\'123456\',\'ja_JP\');">参照</a></td></tr></table>')
    rows = result_rows(page)
    b = "https://cs.example.ac.jp"
    checks = _tab_selftest_cases() + _session_selftest_cases() + site_selftest_cases(
        CampusSquare, b, entry=(b + "/campusweb/campusportal.do", True), login=(b + "/campusweb/ssologin.do", False),
        idp=("https://idp.example.com/auth/session", False), back=(b + "/campusweb/campusportal.do", False)) + [
        ("form_fields: hidden と値なし hidden を拾う", form_fields(page, "ReferForm") ==
         {"_flowExecutionKey": "_cA_kB", "_eventId": "input", "secchikbncd": ""}),
        ("result_rows: refer の引数と entity 解決", len(rows) == 1 and rows[0]["refer"] == ("2026", "99", "123456", "ja_JP")
         and "科目&名" in rows[0]["cells"]),
        ("inside: 別 host・Shibboleth・context 外は外", inside("https://cs.example.ac.jp/campusweb/x.do", host)
         and not inside("https://cs.example.ac.jp/Shibboleth.sso/SAML2/POST", host)
         and not inside("https://idp.example.com/campusweb/", host) and not inside("https://cs.example.ac.jp/", host)),
    ] + _dl_selftest_cases() + _schedule_selftest_cases()
    for name, good in checks:
        ok &= bool(good)
        print("PASS" if good else "FAIL", name)
    print("selftest", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default=os.environ.get("CAMPUSSQUARE_BASE"), help="https://<host> (env CAMPUSSQUARE_BASE)")
    ap.add_argument("--browser", default="brave")
    ap.add_argument("--profile", default="Default")
    ap.add_argument("--browser-refresh", choices=("off", "keep", "close"),
                    default=os.environ.get("CAMPUSSQUARE_BROWSER_REFRESH", "off"))
    ap.add_argument("--wait-login", type=int, default=0, metavar="秒")
    ap.add_argument("--trace", action="store_true",
                    help="入り直しの途中の tab の行き先・cookie DB の変化・受け入れの確認を秒つきで stderr に出す (値は出さない)")
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("syllabus-search")
    p.add_argument("--year", default=time.strftime("%Y")); p.add_argument("--code", default="")
    p.add_argument("--name", default=""); p.add_argument("--teacher", default=""); p.add_argument("--word", default="")
    p = sub.add_parser("syllabus"); p.add_argument("code"); p.add_argument("--year", default=time.strftime("%Y"))
    p.add_argument("--html", action="store_true")
    p = sub.add_parser("roster-csv"); p.add_argument("--year", default=time.strftime("%Y"))
    p.add_argument("--exam", default="1", help="試験区分 (画面の既定 = 1)")
    p.add_argument("--out-dir", required=True, help="保存先 dir (file 名は server が付ける regisYYYYMMDD.csv)")
    win = argparse.ArgumentParser(add_help=False)  # 公開期間の窓 (dl-list / dl-get 共通)
    win.add_argument("--from", dest="day_from", metavar="YYYY-MM-DD", help="公開期間の検索の始め (既定 = 画面の既定)")
    win.add_argument("--to", dest="day_to", metavar="YYYY-MM-DD", help="公開期間の検索の終わり (既定 = 画面の既定)")
    p = sub.add_parser("dl-list", parents=[win], help="ダウンロードセンターの一覧 (パスワードは *** に伏せる)")
    p.add_argument("--folder", default="", help="フォルダ名 (親 / 子 の path) の部分一致で絞る")
    p = sub.add_parser("dl-get", parents=[win], help="配布資料を保存 (同名で中身が違えば上書きしない)")
    p.add_argument("file_ids", nargs="+", metavar="fileId", type=lambda x: str(int(x)))
    p.add_argument("--out-dir", required=True, help="保存先 dir (file 名は Content-Disposition)")
    p.add_argument("--extract", action="store_true",
                   help="zip を <out-dir>/<zip の stem>/ に展開、 パスワード付きの PDF は暗号化を外した写しを同じ所に。 パスワードは一覧のその行のサマリ欄から (無ければ無しで試す)")
    p = sub.add_parser("dl-missing", parents=[win], help="手元に無い配布資料 (一覧の名前と手元の file・dir の名前を突き合わせる)")
    p.add_argument("--folder", default="", help="フォルダ名 (親 / 子 の path) の部分一致で絞る")
    p.add_argument("--have", action="append", required=True, metavar="DIR",
                   help="手元の置き場 (直下の file・dir の名前を見る。 複数可)")
    p.add_argument("--match", default="", help="ファイル名への正規表現 (例: 2026年度)")
    p = sub.add_parser("schedule", help="自分のスケジュール (時間割のコマと教室)")
    p.add_argument("--from", dest="start", metavar="YYYY-MM", help="始めの月 (既定 = 今月)")
    p.add_argument("--months", type=int, default=1, help="何か月分 (既定 1)")
    p.add_argument("--days", action="store_true", help="1 日 1 行の TSV (日付 曜日 時限 科目 教室 種別)")
    p = sub.add_parser("get"); p.add_argument("path")
    sub.add_parser("status")
    sub.add_parser("doctor")
    p = sub.add_parser("probe", help="切れ方の採取 (cookie を使わない)")
    p.add_argument("paths", nargs="*", help=f"既定 = {' '.join(PROBE_PATHS)}")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if not a.cmd:
        ap.error("subcommand が要る")
    if a.cmd == "doctor":
        for line in doctor(a.browser, a.profile, a.base):
            print(line)
        return
    if not a.base:
        raise SystemExit("--base か env CAMPUSSQUARE_BASE が要る (= 組織の host、 private 層の入口 script が与える)")
    if a.cmd == "probe":  # browser の cookie を使わない = CampusSquare() を作らない
        host = urlparse(a.base).hostname
        print_probe(probe_anonymous(a.base, a.paths or PROBE_PATHS, lambda c, l, t: expired(c, l, t, host)))
        return
    try:
        cs = CampusSquare(a.base, a.browser, a.profile, refresh=a.browser_refresh, wait_login=a.wait_login, trace=a.trace)
        run(a, cs)
    except LoginRequired as e:
        app = BROWSER_APPS.get(a.browser, a.browser)
        if e.observed:
            _say(f"学内ログインが切れている = 本人のログインが要る。 `--wait-login 600` を subcommand の前に付けて"
                 f" (例 = `… --wait-login 600 {a.cmd} …`、 後ろに付けると引数の誤りで止まる) 実行し直すと、 "
                 f"{app} にログイン画面を開いたまま、 ログインし終えるのを待って続きから進む")
        else:
            _say(f"session 切れ ({e.why}) から復帰できなかった → {app} で {a.base}{PORTAL} を開いてログインしてから再実行"
                 + ("" if a.browser_refresh != "off" else " (`--browser-refresh keep|close` で browser に入り直させられる)")
                 + " / 途中を見るなら `--trace`")
        sys.exit(EX_LOGIN)


def run(a, cs):
    if a.cmd == "syllabus-search":
        _, rows = cs.syllabus_search(a.year, a.code, a.name, a.teacher, a.word)
        print(f"# {a.year} 年度 シラバス検索: {len(rows)} 件")
        for r in rows:
            print(" | ".join(c for c in r["cells"] if c))
    elif a.cmd == "syllabus":
        page = cs.syllabus(a.year, a.code)
        print(page if a.html else html_to_text(page))
    elif a.cmd == "schedule":
        if a.start and not re.fullmatch(r"\d{4}-\d{1,2}", a.start):
            raise SystemExit("--from は YYYY-MM")
        rows = cs.schedule(a.start, max(a.months, 1))
        if a.days:
            from datetime import date as _date
            for r in rows:
                print("\t".join([r["date"], _WEEKDAY[_date.fromisoformat(r["date"]).weekday()], r["period"],
                                 r["course"], r["room"], r["kind"]]))
        else:
            print(f"# 自分のスケジュール: {len(rows)} 行 (曜日時限 | 科目 | 教室 | 回数 (初回〜最終)。 種別が開講 〔kaiko〕 以外なら末尾に)")
            for wd, per, course, room, kind, n, first, last in schedule_summary(rows):
                print(f"{wd}{per} | {course} | {room} | {n} 回 ({first}〜{last})" + ("" if kind == "kaiko" else f" | {kind}"))
    elif a.cmd == "roster-csv":
        body, name = cs.roster_csv(a.year, a.exam)
        out, _ = save_no_clobber(Path(a.out_dir).expanduser() / Path(name).name, body)  # 同じ日の取り直しは上書きしない
        rows = max(body.count(b"\n") - 1, 0)
        print(f"{out} ({len(body)} bytes, {rows} 行)")  # 中身 (個人情報) は出さない
    elif a.cmd == "dl-missing":
        folders, files = dl_parse(cs.dl_list(a.day_from, a.day_to))
        key = _fold(a.folder) if a.folder else ""
        ids = {f["id"] for f in folders if key in _fold(f["path"])}
        rows = [r for r in files if r["folder_id"] in ids]
        have = [x.name for d in a.have for x in Path(d).expanduser().iterdir()] if all(
            Path(d).expanduser().is_dir() for d in a.have) else None
        if have is None:
            raise SystemExit("--have の dir が無い: " + ", ".join(d for d in a.have if not Path(d).expanduser().is_dir()))
        miss = missing_rows(rows, have, a.match)
        for r in miss:  # 無ければ無出力 (hook / dashboard 用)。 件数は stderr
            print(" | ".join([r["folder"], r["file_id"], r["name"], r["date"]]))
        _say(f"手元に無い {len(miss)} 件 / 照合 {sum(1 for r in rows if not a.match or re.search(a.match, r['name']))} 件")
    elif a.cmd == "dl-list":
        page = cs.dl_list(a.day_from, a.day_to)
        folders, files = dl_parse(page)
        key = _fold(a.folder) if a.folder else ""
        pick = [f for f in folders if key in _fold(f["path"])]
        rows = {f["id"]: [r for r in files if r["folder_id"] == f["id"]] for f in pick}
        win = dl_window(page)
        print(f"# ダウンロードセンター: {len(pick)} フォルダ / {sum(map(len, rows.values()))} 件"
              + (f" (--folder {a.folder}。 全体 = {len(folders)} フォルダ / {len(files)} 件)" if key else "")
              + (f" / 公開期間の検索 = {win[0]}〜{win[1]}" if win else ""))
        print("# フォルダ | fileId | ファイル名 | 登録日 | サマリ (パスワードは *** に伏せる。 dl-get --extract が使う)")
        for f in pick:
            print(f"## {f['path']} | 公開期間 {f['period']} | {f['owner']} | {len(rows[f['id']])} 件")
            for r in rows[f["id"]]:
                print(" | ".join([f["path"], r["file_id"], r["name"], r["date"],
                                  mask_summary(r["summary"]).replace("\n", " / ")]))
    elif a.cmd == "dl-get":
        out_dir = Path(a.out_dir).expanduser()
        summaries = None
        for fid in a.file_ids:
            body, name, ctype = cs.dl_get(fid)
            out, how = save_no_clobber(out_dir / name, body)
            print(f"{out} ({len(body)} bytes, {ctype}"
                  + {"new": "", "same": "、 同じ中身が既にあった", "renamed": "、 同名で中身が違うので別名"}[how] + ")")
            if not a.extract:
                continue

            def passwords_for(fid):
                nonlocal summaries
                if summaries is None:  # パスワードは一覧のその行のサマリ欄にある (dl-get 1 回に一覧 1 回)
                    summaries = {r["file_id"]: r["summary"] for r in dl_parse(cs.dl_list(a.day_from, a.day_to))[1]}
                if fid not in summaries:
                    _say(f"fileId {fid} が一覧 (公開期間の窓) に無い → サマリ欄のパスワードを拾えない (--from/--to で窓を広げる)")
                return summary_passwords(summaries.get(fid, ""))

            if body[:5] == b"%PDF-":  # パスワード付きの PDF = 暗号化を外した写しを <out-dir>/<stem>/<名前> に
                if not pdf_needs_pass(body):
                    _say(f"fileId {fid} はパスワードの無い PDF → 展開不要")
                    continue
                data, _ = pdf_decrypt(body, passwords_for(fid), f"fileId {fid}")
                path, how = save_no_clobber(out_dir / out.stem / out.name, data)
                print(f"復号: {path} (パスワード = サマリ欄の記載で開けた"
                      + {"new": "", "same": "、 同じ中身が既にあった", "renamed": "、 中身が違うので別名"}[how] + ")")
                continue
            if not zipfile.is_zipfile(io.BytesIO(body)):
                _say(f"fileId {fid} は zip でも PDF でもない → 展開しない")
                continue
            pws = passwords_for(fid) if zip_encrypted(body) else []
            members, used = zip_read_all(body, pws, f"fileId {fid}")
            dest = out_dir / out.stem
            done = [save_no_clobber(dest / rel, data) for rel, data in members]
            same = sum(h == "same" for _, h in done)
            renamed = sum(h == "renamed" for _, h in done)
            print(f"展開: {len(members)} 本 → {dest}/ ("
                  + ("暗号化なし" if used is None else "パスワード = サマリ欄の記載で開けた")
                  + (f"、 同じ中身が既にあった {same} 本" if same else "")
                  + (f"、 中身が違うので別名 {renamed} 本" if renamed else "") + ")")
            for path, _ in done:
                print(f"  {path}")
    elif a.cmd == "get":
        print(cs._request("GET", a.path).text)
    elif a.cmd == "status":
        r = cs._request("GET", PORTAL)
        title = re.search(r"<title>(.*?)</title>", r.text, re.S)
        print(f"読める ({r.status_code} {title.group(1).strip() if title else ''})"
              + {None: "", "reload": " (cookie を読み直した)", "refresh": " (browser に入り直させた)"}[cs.recovered_by])


if __name__ == "__main__":
    main()
