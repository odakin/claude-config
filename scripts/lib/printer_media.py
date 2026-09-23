"""printer_media — CUPS の queue の先にある印刷機本体に、 トレイの用紙を IPP で聞く (pdf-print-preflight.py の --printer と --hook が使う)。

なぜ: `lp -o media=A4` や PageSize の指定は、 本体 (操作パネル) の用紙サイズ設定を上書きしない機種がある (実測 = A4 の job が
本体設定どおり別サイズの紙に出た)。 IPP の Get-Printer-Attributes が返す media-ready / media-col-ready は、 本体が自分の
トレイについて持っている用紙サイズ = 機械で読める。 合わない設定のまま刷るのを、 user に確かめてもらう前に機械で止める
(user への確認の代わりにはしない = 下の限界。 conventions/office-automation.md#printer-media-ipp)。

読み方 (限界):
- 報告値は本体の設定であって、 紙を測った値とは限らない (トレイにサイズ検知の無い機種は設定をそのまま返す)。 一致は
  「本体の設定が PDF と同じ」 までで、 トレイの紙が本当にそのサイズかは言わない。 実測は「報告 A4 → A4 で出た」 の一致だけ
  = 本体の設定を変えたときに報告が追従するかは未検証。 違うサイズで出たと言われたら本体を見てもらう、 は変えない。
- queue の device-uri が機種の独自 backend (scheme が ipp / ipps でない) のときは、 URI から host と `/ipp/` の path を拾って
  ipp:// に組み直す (実測 = 独自 backend の queue でも本体は素の ipp:// に答えた)。 組めない (dnssd 等) ・答えが無い・ipptool が
  無いときは「未確認」 を返し、 止めない (fail-open)。
- 両面の既定は、 本体の sides-default と CUPS の queue の既定 (driver 独自の option) が食い違うことがある (実測 = 本体は片面、
  queue は両面)。 紙に効くのは queue の側 = lpoptions -l の既定を併せて出す。
"""
import os
import re
import subprocess
import tempfile

TOLERANCE_MM = 2

REQUEST = """{
  OPERATION Get-Printer-Attributes
  GROUP operation-attributes-tag
  ATTR charset attributes-charset utf-8
  ATTR naturalLanguage attributes-natural-language en
  ATTR uri printer-uri $uri
  ATTR keyword requested-attributes media-ready,media-col-ready,media-default,sides-default,printer-state,printer-state-reasons
}
"""

# 寸法 (mm を丸めた短辺・長辺) → 名前 (pdf-print-preflight.PAPER_NAMES と同じ表を持つと drift するので、 呼び元から渡せるようにする)
DEFAULT_NAMES = {(210, 297): "A4", (148, 210): "A5", (297, 420): "A3", (182, 257): "B5 JIS", (176, 250): "B5 ISO",
                 (257, 364): "B4 JIS", (216, 279): "Letter", (100, 148): "はがき"}
ONE_SIDED_VALUES = {"none", "one-sided", "off", "false", "simplex"}


def _run(argv, timeout):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, type(e).__name__
    if r.returncode != 0:
        return None, ((r.stderr or "").strip().splitlines() or [f"rc={r.returncode}"])[0][:120]
    return r.stdout, ""


def device_uri(queue=None, run=_run):
    """queue (None = 既定の送信先) の device-uri。 lpoptions の出力は locale に依らない。"""
    out, why = run(["lpoptions"] + (["-p", queue] if queue else []), 5)
    if out is None:
        return None, f"lpoptions が失敗 ({why})"
    m = re.search(r"(?:^|\s)device-uri=(\S+)", out)
    return (m.group(1), "") if m else (None, "queue に device-uri が無い")


def ipp_uri(dev):
    """device-uri → 本体に直に聞く ipp:// の URI (組めなければ None)。"""
    if not dev:
        return None
    if re.match(r"ipps?://", dev):
        return dev
    if dev.startswith("dnssd://"):
        return None  # Bonjour 名の解決が要る = ここでは聞かない
    m = re.search(r"(?P<host>(?:\d{1,3}\.){3}\d{1,3}|[A-Za-z0-9][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+)*\.local)"
                  r"(?::(?P<port>\d+))?(?P<path>/ipp/[^\s?#]*)?", dev.split("://", 1)[-1])
    if not m:
        return None
    return f"ipp://{m.group('host')}" + (f":{m.group('port')}" if m.group("port") else "") + (m.group("path") or "/ipp/print")


def parse_attrs(text):
    """ipptool -tv の出力 → {属性名: 値の文字列}。"""
    attrs = {}
    for line in (text or "").splitlines():
        m = re.match(r"^\s*([a-z][a-z0-9-]*) \([^)]*\) = (.*)$", line)
        if m and m.group(1) != "requested-attributes":
            attrs[m.group(1)] = m.group(2).strip()
    return attrs


def query(uri, timeout=4, run=_run):
    """本体に Get-Printer-Attributes を投げる → (attrs, 理由)。 答えが無ければ ({}, 理由)。"""
    d = tempfile.mkdtemp(prefix="printer-media-")
    test = os.path.join(d, "get-printer-attributes.test")
    with open(test, "w") as f:
        f.write(REQUEST)
    try:
        out, why = run(["ipptool", "-T", str(timeout), "-tv", uri, test], timeout + 3)
    finally:
        try:
            os.remove(test); os.rmdir(d)
        except OSError:
            pass
    if out is None:
        return {}, f"ipptool が失敗 ({why})"
    attrs = parse_attrs(out)
    return attrs, ("" if attrs else "本体の答えに属性が無い")


def _collections(value):
    """'{..},{..}' を深さ 0 の collection ごとに分ける。"""
    out, depth, cur = [], 0, ""
    for ch in value or "":
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        cur += ch
        if depth == 0 and ch == "}":
            out.append(cur.strip(", ")); cur = ""
    return out


def ready_sizes(attrs):
    """トレイの用紙 → [(短辺 mm, 長辺 mm, トレイ名)]。 media-col-ready (寸法つき) を優先し、 無ければ media-ready の名前から。"""
    sizes = []
    for col in _collections(attrs.get("media-col-ready", "")):
        m = re.search(r"media-size=\{x-dimension=(\d+) y-dimension=(\d+)\}", col)
        if not m:
            continue
        w, h = int(m.group(1)) / 100, int(m.group(2)) / 100
        src = re.search(r"media-source=([\w-]+)", col)
        sizes.append((min(w, h), max(w, h), src.group(1) if src else ""))
    if sizes:
        return sizes
    for kw in (attrs.get("media-ready") or "").split(","):
        m = re.search(r"_(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)(mm|in)$", kw.strip())
        if m:
            k = 25.4 if m.group(3) == "in" else 1
            w, h = float(m.group(1)) * k, float(m.group(2)) * k
            sizes.append((min(w, h), max(w, h), ""))
    return sizes


def _name(short, long_, names):
    for (s, l), nm in names.items():
        if abs(s - short) <= TOLERANCE_MM and abs(l - long_) <= TOLERANCE_MM:
            return nm
    return ""


def _label(short, long_, names, src=""):
    nm = _name(short, long_, names)
    return (nm + " " if nm else "") + f"({round(short)}×{round(long_)} mm" + (f", {src})" if src else ")")


def duplex_defaults(queue=None, run=_run):
    """CUPS の queue の両面 option の既定 → [(option 名, 既定値)] (driver 独自の名前も拾う)。"""
    out, _ = run(["lpoptions"] + (["-p", queue] if queue else []) + ["-l"], 5)
    found = []
    for line in (out or "").splitlines():
        key = re.split(r"[/:]", line, 1)[0].strip()
        if re.search(r"duplex|sides", key, re.I):
            m = re.search(r"\*(\S+)", line)
            if m:
                found.append((key, m.group(1)))
    return found


def check(queue, pdf_sizes, lp_opts=(), names=None, run=_run, attrs=None):
    """→ (findings, infos)。 pdf_sizes = {(短辺 mm, 長辺 mm)}。 本体の報告が PDF のどの寸法とも合わなければ 🔴。
    attrs を渡すと本体に聞かない (selftest 用)。"""
    names = names or DEFAULT_NAMES
    findings, infos = [], []
    who = f"queue {queue}" if queue else "既定の queue"
    why = ""
    if attrs is None:
        dev, why = device_uri(queue, run)
        uri = ipp_uri(dev)
        if uri:
            attrs, why = query(uri, run=run)
        else:
            attrs, why = {}, why or f"device-uri から ipp:// を組めない = {dev}"
    sizes = ready_sizes(attrs)
    if not attrs:
        infos.append(f"⚪ 本体の用紙: 未確認 ({who}: {why}) — 本体の用紙サイズとトレイの紙を user に確認")
    elif not sizes:
        infos.append(f"⚪ 本体の用紙: 本体がトレイの用紙を報告しない ({who}) — 本体の用紙サイズとトレイの紙を user に確認")
    else:
        ready = ", ".join(_label(s, l, names, src) for s, l, src in sizes)
        miss = [(s, l) for s, l in pdf_sizes
                if not any(abs(s - rs) <= TOLERANCE_MM and abs(l - rl) <= TOLERANCE_MM for rs, rl, _ in sizes)]
        if miss:
            findings.append(f"🔴 本体の用紙: 本体が報告するトレイの用紙 = {ready} / PDF = "
                            + ", ".join(_label(s, l, names) for s, l in sorted(miss))
                            + " → 本体の用紙サイズ設定とトレイの紙を PDF に合わせてから刷る (lp の media 指定は本体の設定を上書きしない)")
        else:
            infos.append(f"本体の用紙: {ready} ✓ ({who} の本体の報告 = 本体の設定で、 紙の実測ではない → トレイの紙は user に確認)")
    state = attrs.get("printer-state", "")
    reasons = attrs.get("printer-state-reasons", "")
    if (state and state != "idle") or reasons not in ("", "none"):
        infos.append(f"本体の状態: {state or '?'} / {reasons or '?'}")
    opts = {o.split("=", 1)[0].lower() for o in lp_opts if "=" in o}
    for key, val in duplex_defaults(queue, run):
        if key.lower() in opts or "sides" in opts:
            continue  # lp で明示している = その指定が効く
        if val.lower() not in ONE_SIDED_VALUES:
            infos.append(f"⚠️ queue の既定は両面 ({key}={val}) — 片面なら lp -o {key}=<片面の値> "
                         f"(値は lpoptions{' -p ' + queue if queue else ''} -l で確認。 本体の sides-default とは別物)")
    return findings, infos


def _selftest():
    assert ipp_uri("ipp://printer.local:631/ipp/print") == "ipp://printer.local:631/ipp/print"
    assert ipp_uri("vendorbackend://ippSP/10.0.0.10/ipp/print") == "ipp://10.0.0.10/ipp/print"
    assert ipp_uri("socket://10.0.0.11") == "ipp://10.0.0.11/ipp/print"
    assert ipp_uri("dnssd://Some%20Printer._ipp._tcp.local./?uuid=x") is None and ipp_uri(None) is None
    out = ("        requested-attributes (1setOf keyword) = media-ready,media-col-ready\n"
           "        printer-state (enum) = idle\n"
           "        printer-state-reasons (keyword) = none\n"
           "        media-col-ready (1setOf collection) = {media-size={x-dimension=21000 y-dimension=29700} "
           "media-source=tray-1 media-type=stationery},{media-size={x-dimension=18200 y-dimension=25700} media-source=manual}\n"
           "        media-ready (1setOf keyword) = iso_a4_210x297mm,jis_b5_182x257mm\n")
    a = parse_attrs(out)
    assert "requested-attributes" not in a and a["printer-state"] == "idle"
    assert ready_sizes(a) == [(210.0, 297.0, "tray-1"), (182.0, 257.0, "manual")], ready_sizes(a)
    assert tuple(round(x, 1) for x in ready_sizes({"media-ready": "na_letter_8.5x11in"})[0][:2]) == (215.9, 279.4)
    nodup = lambda argv, t: ("", "")  # noqa: E731 - lpoptions -l に両面 option が無い queue
    f, i = check("Q", {(210, 297)}, attrs=a, run=nodup)
    assert not f and any("A4" in x and "✓" in x for x in i), (f, i)
    b5 = parse_attrs("  media-ready (keyword) = jis_b5_182x257mm\n  printer-state (enum) = idle\n")
    f, i = check("Q", {(210, 297)}, attrs=b5, run=nodup)
    assert f and "B5 JIS" in f[0] and "A4" in f[0], f
    f, i = check("Q", {(210, 297)}, attrs={"printer-state": "idle"}, run=nodup)
    assert not f and any(x.startswith("⚪") for x in i), i
    dup = lambda argv, t: ("VendorDuplex/Print Style: None *DuplexFront\nPageSize/Page Size: *A4 B5\n", "")  # noqa: E731
    _, i = check("Q", {(210, 297)}, attrs=a, run=dup)
    assert any("両面" in x and "VendorDuplex=DuplexFront" in x for x in i), i
    _, i = check("Q", {(210, 297)}, lp_opts=["VendorDuplex=None"], attrs=a, run=dup)
    assert not any("両面" in x for x in i), i
    down = lambda argv, t: (None, "TimeoutExpired")  # noqa: E731 - 本体に届かない = 未確認で通す
    f, i = check("Q", {(210, 297)}, run=down)
    assert not f and i[0].startswith("⚪"), (f, i)
    return "printer_media selftest: PASS"
