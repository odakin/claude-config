#!/usr/bin/env python3
"""check-seal-attachments.py — 印影画像の入った file を、file のまま相手に渡す前に止める (メール添付・共有・upload の出口用)。

画像印影を埋めてよいのは紙で出す成果物だけ、という運用の機械で判定できる半分を出口で守る
(規約 = conventions/office-automation.md#seal-artifact-marker、判定の信号 = lib/seal_artifact.py)。

判定:
  - 添付に印影の強い兆候 (marker / seal-image / name+ink) が無い → 出してよい (exit 0)。 弱い兆候は警告だけ。
  - 強い兆候がある → 原則止める (exit 2)。 例外は**代理印刷**だけ: 受け取った人が印刷して紙で窓口に出す場合。
    次を全部満たす時だけ通す (exit 0 + 通した理由を表示):
      1. 代理印刷の条件が設定されている (--proxy-pattern が 1 個以上)
      2. 宛先が 1 件以上あり、どれも窓口 (--office-address / --office-address-file / --office-regex) ではない
      3. 本文が --proxy-pattern の正規表現を全部含む (= 「印刷して紙で出してほしい」 と頼んでいる)
    --no-proxy-reason を渡すと例外を使わない (例: 窓口の一覧を読めなかった)。

  check-seal-attachments.py FILE... --pool DIR_OR_PNG [--pool ...] [--name-token RE]
      [--to A,B] [--cc ...] [--bcc ...] [--body-file F | --body TEXT]
      [--office-address ADDR ...] [--office-address-file F] [--office-regex RE ...]
      [--proxy-pattern RE ...] [--no-proxy-reason TEXT] [--json]
  check-seal-attachments.py --selftest

exit: 0 = 出してよい / 2 = 止める / 3 = 検査できない (依存なし・引数の誤り)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
try:
    from seal_artifact import load_pool, scan, strength  # noqa: E402
except Exception as e:  # pragma: no cover
    print(f"check-seal-attachments: lib を読めない ({e})", file=sys.stderr)
    sys.exit(3)

ADDR_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def addresses(*fields) -> list:
    out = []
    for f in fields:
        for a in ADDR_RE.findall(f or ""):
            a = a.lower()
            if a not in out:
                out.append(a)
    return out


def decide(files, pool, name_token, recipients, body, office_addrs, office_res, proxy_patterns,
           no_proxy_reason=None) -> dict:
    """判定の本体 (I/O なし)。 戻り値 = {"decision": "ok"|"proxy"|"block", "files": [...], "reasons": [...]}。"""
    results = []
    for f in files:
        if not os.path.exists(f):
            results.append({"file": f, "signals": [{"signal": "unreadable", "detail": "file が無い"}], "strength": "weak"})
            continue
        sig = scan(f, pool, name_token)
        results.append({"file": f, "signals": sig, "strength": strength(sig)})
    strong = [r for r in results if r["strength"] == "strong"]
    out = {"decision": "ok", "files": results, "reasons": [],
           "proxy_available": bool(proxy_patterns) and not no_proxy_reason}
    if not strong:
        return out
    offices = [a for a in recipients
               if a in office_addrs or any(re.search(rx, a) for rx in office_res)]
    reasons = []
    if no_proxy_reason:
        reasons.append(f"代理印刷の例外は使えない: {no_proxy_reason}")
    if not proxy_patterns and not no_proxy_reason:
        reasons.append("代理印刷の条件が設定されていない")
    if not recipients:
        reasons.append("宛先が無い (共有・upload の出口では代理印刷を判定できない)")
    if offices:
        reasons.append("窓口の宛先を含む: " + ", ".join(offices))
    missing = [p for p in proxy_patterns if not re.search(p, body or "")]
    if proxy_patterns and missing:
        reasons.append("本文に印刷して紙で出してほしいという依頼が無い (足りない条件: " + " / ".join(missing) + ")")
    if reasons:
        out["decision"] = "block"
        out["reasons"] = reasons
    else:
        out["decision"] = "proxy"
        out["reasons"] = ["代理印刷として通す: 宛先は窓口でなく、本文に印刷と紙提出の依頼がある"]
    return out


def render(res) -> str:
    lines = []
    strong = [r for r in res["files"] if r["strength"] == "strong"]
    weak = [r for r in res["files"] if r["strength"] == "weak"]
    if res["decision"] == "block":
        lines.append("[check-seal-attachments] 止めた: 印影画像の入った file を file のまま渡そうとしている")
        lines.append("  印影画像を埋めてよいのは紙で出すものだけ (file で渡すと画像を貼ったことが相手に分かる)。")
    elif res["decision"] == "proxy":
        lines.append("[check-seal-attachments] 通した (代理印刷): 印影画像の入った file を、印刷して紙で出してもらう相手に送る")
    for r in strong:
        lines.append(f"  🔴 {r['file']}")
        for s in r["signals"]:
            lines.append(f"       {s['signal']}: {s['detail']}")
    for r in weak:
        lines.append(f"  🟡 {r['file']} (弱い兆候、止めない)")
        for s in r["signals"]:
            lines.append(f"       {s['signal']}: {s['detail']}")
    for why in res["reasons"]:
        lines.append(f"  - {why}")
    if res["decision"] == "block":
        lines.append("  直し方: 紙で出す (印刷して持参・郵送) / 送るなら印影の無い版 (確認用) を添付する" +
                     (" /" if res.get("proxy_available") else ""))
        if res.get("proxy_available"):
            lines.append("          代理で印刷してもらうなら、窓口でない相手に、本文で印刷して紙で出してほしいと頼む")
    return "\n".join(lines)


def _selftest() -> int:
    import tempfile
    try:
        import fitz
    except ImportError:
        print("SKIP: check-seal-attachments selftest (PyMuPDF 未導入)")
        return 0
    from seal_artifact import mark_doc
    d = tempfile.mkdtemp()
    ok = True

    def check(label, cond):
        nonlocal ok
        print(f"  {'✅' if cond else '❌'} {label}")
        ok = ok and bool(cond)

    sealed = os.path.join(d, "form_print.pdf")
    doc = fitz.open(); doc.new_page(); mark_doc(doc); doc.save(sealed)
    plain = os.path.join(d, "schedule.pdf")
    doc = fitz.open(); doc.new_page(); doc.save(plain)
    office = {"office@example.org"}
    office_re = [r"@example\.net$"]
    proxy = [r"印刷", r"紙|提出"]
    body_ok = "添付の申請書を印刷の上、紙で窓口へ提出していただけないでしょうか。"
    body_ng = "申請書を添付します。"

    r = decide([plain], set(), None, ["office@example.org"], body_ng, office, office_re, proxy)
    check("印影なし → ok", r["decision"] == "ok")
    r = decide([sealed], set(), None, ["office@example.org"], body_ok, office, office_re, proxy)
    check("印影あり + 窓口宛 → block (本文に依頼があっても)", r["decision"] == "block")
    r = decide([sealed], set(), None, ["staff@example.org"], body_ng, office, office_re, proxy)
    check("印影あり + 窓口でない + 依頼なし → block", r["decision"] == "block")
    r = decide([sealed], set(), None, ["staff@example.org"], body_ok, office, office_re, proxy)
    check("印影あり + 窓口でない + 依頼あり → proxy", r["decision"] == "proxy")
    r = decide([sealed], set(), None, ["staff@example.org", "desk@example.net"], body_ok, office, office_re, proxy)
    check("group address (office_re) を含む → block", r["decision"] == "block")
    r = decide([sealed], set(), None, ["staff@example.org"], body_ok, office, office_re, proxy, "一覧を読めない")
    check("no_proxy_reason → block", r["decision"] == "block")
    r = decide([sealed], set(), None, [], body_ok, office, office_re, proxy)
    check("宛先なし (upload) → block", r["decision"] == "block")
    r = decide([sealed], set(), None, ["staff@example.org"], body_ok, office, office_re, [])
    check("代理印刷の条件なし → block", r["decision"] == "block")
    r = decide([os.path.join(d, "none.pdf")], set(), None, ["a@example.com"], "", office, office_re, proxy)
    check("無い file は弱い兆候 (止めない)", r["decision"] == "ok" and r["files"][0]["strength"] == "weak")
    check("addresses: 表示名つき・重複を正規化",
          addresses("A <X@example.org>, x@example.org", "b@example.com") == ["x@example.org", "b@example.com"])
    print(f"check-seal-attachments selftest: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--pool", action="append", default=[])
    ap.add_argument("--name-token", default=None)
    ap.add_argument("--to", default="")
    ap.add_argument("--cc", default="")
    ap.add_argument("--bcc", default="")
    ap.add_argument("--body", default="")
    ap.add_argument("--body-file", default="")
    ap.add_argument("--office-address", action="append", default=[])
    ap.add_argument("--office-address-file", default="")
    ap.add_argument("--office-regex", action="append", default=[])
    ap.add_argument("--proxy-pattern", action="append", default=[])
    ap.add_argument("--no-proxy-reason", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if not a.files:
        return 0
    try:
        body = open(a.body_file, encoding="utf-8").read() if a.body_file else a.body
        office = {x.lower() for x in a.office_address}
        if a.office_address_file:
            with open(a.office_address_file, encoding="utf-8") as fh:
                office |= {ln.strip().lower() for ln in fh if ln.strip() and not ln.startswith("#")}
        pool = load_pool(a.pool)
        res = decide(a.files, pool, a.name_token, addresses(a.to, a.cc, a.bcc), body, office,
                     a.office_regex, a.proxy_pattern, a.no_proxy_reason or None)
    except Exception as e:  # noqa: BLE001
        print(f"check-seal-attachments: 検査できない ({type(e).__name__}: {e})", file=sys.stderr)
        return 3
    if a.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        text = render(res)
        if text:
            print(text, file=sys.stderr)
    return 2 if res["decision"] == "block" else 0


if __name__ == "__main__":
    sys.exit(main())
