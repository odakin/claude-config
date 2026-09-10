#!/usr/bin/env python3
"""check-markup-artifacts.py — 赤入れ・校正済み現物の台帳漏れ / 未読 / 書き起こし消失を surface（config 駆動、スキャンは grep に掛からないので file 単位で持つ）

なぜ必要か (2026-09-10 の実害)
------------------------------
他人が紙に書き込んで返してくる物 — 事務の赤入れ、査読の校正、契約書のマークアップ — は
**スキャン PDF で text 層を持たない** ことが多い。
つまり grep にも、提出物検査器 (kakenhi-preflight.py) にも**かからない**。
「文字で検索できるものだけ」を読んで過去の指摘を棚卸ししたつもりになると、
開いていない PDF の分が丸ごと落ちる。実際に 2 本を開いたら新類型が 5 つ出て、
うち 1 つは「同じ赤字を 1 年前に受けていた」の発見だった (= 再発を再発と認識できていなかった)。

そこで **台帳を正本にし、現物の側から台帳の穴を突く**。台帳・走査対象・除外は config で渡す
(= 本 script は特定の repo / 制度を知らない):
  🔴 MISSING     台帳に載っているのに file が実在しない (移動 / 消去)
  🟠 UNREGISTERED  赤入れらしい PDF が台帳にも not_artifacts にも無い (= 受け取ったが記録していない)
  🟠 UNREAD      台帳に read: false のまま残っている (= 受け取ったが読んでいない)
  🔴 TRANSCRIPT_MISSING 書き起こし (transcript:) が実在しない (= 文言が失われた)
  🟠 NO_TRANSCRIPT      読了なのに書き起こしが無い (= 要約しか残らず、次に読む人が同定できない)

赤入れらしさの判定 (= 現物の性質で見る、file 名に頼らない):
  - 文書全体の text 層が薄い (スキャン)  かつ
  - どれかの頁に**有彩色**の画素がまとまってある (= 赤/青のペン)
  ⚠️ 図・宛名ラベル等も引っかかるので、構造的除外 (/fig/ 等) + 台帳の not_artifacts で落とす。
     「候補を出して人が仕分ける」設計であって、自動判定ではない。

使い方:
    check-office-review-artifacts.py [--root DIR] [--json] [--selftest]
終了コード 0 固定 (= surface のみ、dashboard を殺さない)。
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

# config で渡すもの (呼び側が自分の層で持つ):
#   registry: <root からの台帳 path>
#   registry_base: <台帳内の相対 path の基準 repo>
#   scan: [{root: <絶対 or root 相対>, rel_base: <path 表示の基準>}, ...]
#   exclude_parts / ink_min / text_max / max_pages: 任意 (既定は下の定数)
# 構造的に赤入れではない場所 (生成物の図・素材)
EXCLUDE_PARTS = ("/fig/", "/fig-mock/", "/figures/", "/sources/", "/templates/",
                 "/reviews/", "/referee-copy-map/", "/upload/", "/submitted/")
INK_MIN = 0.0005        # 有彩色画素の割合 (1 頁あたり)
TEXT_MAX = 800          # 文書全体の text 長がこれ未満 = スキャン扱い
MAX_PAGES = 10          # 走査する先頭頁数
# 走査は 1 file ~0.1s。毎回全 file を raster 化すると dashboard に載せるには重いので、
# (size, mtime) を key に結果を machine-local に cache する (= 中身が変われば自動で再走査)。
CACHE = Path.home() / ".local/state/claude-office-review/redink-cache.json"


def nfc(x) -> str:
    """macOS の file 名は NFD、yaml に書く文字列は NFC になりがちで、素の == が外れる。

    ⚠️ 実測: 「【<担当者>コメント】<氏名>.pdf が台帳に在るのに UNREGISTERED として出た。
    path 比較は必ずこれを通す。
    """
    return unicodedata.normalize("NFC", str(x))


def load_registry(root: Path, registry: str) -> dict | None:
    p = root / registry
    if not p.exists():
        return None
    try:
        import yaml
    except ImportError:
        return None
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return None


def _cache_load() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _cache_save(c: dict) -> None:
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(c), encoding="utf-8")
    except Exception:
        pass


def looks_like_redink(pdf: Path, cache: dict | None = None) -> float | None:
    """赤入れらしさ = 有彩色画素の最大割合。スキャンでなければ None。"""
    key = None
    if cache is not None:
        try:
            st = pdf.stat()
            key = f"{pdf}|{st.st_size}|{int(st.st_mtime)}"
            if key in cache:
                v = cache[key]
                return None if v is None else float(v)
        except OSError:
            pass
    v = _scan_redink(pdf)
    if key is not None:
        cache[key] = v
    return v


def _scan_redink(pdf: Path) -> float | None:
    try:
        import fitz
        import numpy as np
    except ImportError:
        return None
    try:
        doc = fitz.open(pdf)
        if doc.page_count == 0:
            return None
        if sum(len(pg.get_text().strip()) for pg in doc) > TEXT_MAX:
            return None                       # text 層が厚い = スキャンでない
        best = 0.0
        for i in range(min(doc.page_count, MAX_PAGES)):
            pm = doc[i].get_pixmap(dpi=72)
            a = (np.frombuffer(pm.samples, dtype=np.uint8)
                 .reshape(pm.height, pm.width, pm.n)[:, :, :3].astype(int))
            mx, mn = a.max(2), a.min(2)
            best = max(best, ((mx - mn >= 60) & (mx >= 90)).sum() / (a.shape[0] * a.shape[1]))
        return best
    except Exception:
        return None


def audit(root: Path, config: dict | None = None) -> list[tuple]:
    config = config or {}
    reg = load_registry(root, config.get("registry", ""))
    if reg is None:
        return []                              # fail-open (repo 不在 / PyYAML 無し)
    findings: list[tuple] = []
    arts = reg.get("artifacts") or []
    registered = {nfc(a.get("path", "")) for a in arts}
    ignored = [nfc(n.get("path", "")) for n in (reg.get("not_artifacts") or []) if n.get("path")]

    base = root / config.get("registry_base", "")
    roots = {r.get("name", ""): Path(r["rel_base"]).expanduser()
             for r in (config.get("scan") or []) if r.get("name")}

    def resolve(a: dict) -> Path:
        return roots.get(a.get("root", ""), base) / a.get("path", "")

    for a in arts:
        rel = a.get("path", "")
        if rel and not resolve(a).exists():
            findings.append(("🔴", "MISSING",
                             f"{a.get('id', rel)}: 台帳の file が実在しない — {rel}"))
        tr = a.get("transcript")
        if tr and not (base / tr).exists():
            findings.append(("🔴", "TRANSCRIPT_MISSING",
                             f"{a.get('id', rel)}: 書き起こしが実在しない — {tr} "
                             f"(= 事務の文言が失われると『前年の赤入れを読む』ができなくなる)"))
        if a.get("read") and not tr:
            findings.append(("🟠", "NO_TRANSCRIPT",
                             f"{a.get('id', rel)}: 読了なのに書き起こしが無い — "
                             f"shared/office-review/<制度>.md に文言を残す"))
        if not a.get("read"):
            findings.append(("🟠", "UNREAD",
                             f"{a.get('id', rel)} ({a.get('date', '?')}, {a.get('scheme', '?')}): "
                             f"未読のまま — 色領域走査で読む "
                             f"(手順 = kakenhi-proposal.md#office-review-loop)"))

    cache = _cache_load()
    n0 = len(cache)
    # 登録済 path は root をまたいで名前で照合する (Dropbox / repo で同じ file 名の複製がある)
    reg_names = {nfc(Path(a.get("path", "")).name) for a in arts if a.get("path")}

    scan_roots = []
    for r in (config.get("scan") or []):
        sc = Path(r["root"]).expanduser()
        if not sc.is_absolute():
            sc = root / r["root"]
        scan_roots.append((sc, Path(r["rel_base"]).expanduser()))
    for scan, rel_base in scan_roots:
        if not scan.exists():
            continue
        findings += _scan_tree(scan, rel_base, registered, reg_names, ignored, cache)
    if len(cache) != n0:
        _cache_save(cache)
    return findings


def _scan_tree(scan: Path, rel_base: Path, registered: set, reg_names: set,
               ignored: list, cache: dict) -> list[tuple]:
    findings: list[tuple] = []
    for pdf in sorted(list(scan.rglob("*.pdf")) + list(scan.rglob("*.PDF"))):
        try:
            rel = nfc(pdf.relative_to(rel_base))
        except ValueError:
            continue
        if rel in registered or nfc(pdf.name) in reg_names:
            continue
        if any(x in "/" + pdf.as_posix() for x in EXCLUDE_PARTS) or any(ig in rel for ig in ignored):
            continue
        ink = looks_like_redink(pdf, cache)
        if ink is not None and ink > INK_MIN:
            findings.append(("🟠", "UNREGISTERED",
                             f"赤入れらしい PDF が台帳に無い ({ink*1000:.1f}‰): {rel} "
                             f"→ artifacts に登録するか not_artifacts に理由つきで除外"))
    return findings


def selftest() -> int:
    import tempfile
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("  ✓ " if cond else "  ✗ ") + name)
        ok = ok and cond

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        app = root / "grant-applications" / "applications" / "x"
        app.mkdir(parents=True)
        (root / "grant-applications" / "shared").mkdir(parents=True)
        (root / "grant-applications" / "shared" / "office-review-artifacts.yaml").write_text(
            "artifacts:\n"
            "  - id: gone\n    path: applications/x/missing.pdf\n    read: true\n"
            "  - id: todo\n    path: applications/x/present.pdf\n    date: '2026-01-01'\n"
            "    scheme: test\n    read: false\n"
            "not_artifacts: []\n", encoding="utf-8")
        try:
            import fitz
            d = fitz.open(); d.new_page(); d.save(app / "present.pdf")
        except ImportError:
            (app / "present.pdf").write_bytes(b"%PDF-1.4\n")
        cfg = dict(registry="grant-applications/shared/office-review-artifacts.yaml",
                   registry_base="grant-applications",
                   scan=[{"root": "grant-applications/applications",
                          "rel_base": str(root / "grant-applications")}])
        codes = [c for _, c, _ in audit(root, cfg)]
        check("実在しない登録を 🔴 MISSING", "MISSING" in codes)
        check("read: false を 🟠 UNREAD", "UNREAD" in codes)

        # registry が無い repo では黙る (fail-open)
        check("registry 不在なら silent", audit(root / "nowhere", cfg) == [])

        # transcript の実在検査も config なしで効く
        (root / "grant-applications" / "shared" / "office-review-artifacts.yaml").write_text(
            "artifacts:\n"
            "  - id: t\n    path: applications/x/present.pdf\n    read: true\n"
            "    transcript: shared/gone.md\n"
            "not_artifacts: []\n", encoding="utf-8")
        codes = [c for _, c, _ in audit(root, cfg)]
        check("書き起こしが実在しなければ 🔴", "TRANSCRIPT_MISSING" in codes)
    print("\n" + ("✅ selftest PASS" if ok else "❌ selftest FAIL"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=Path, default=Path.home() / "Claude")
    ap.add_argument("--config", type=Path, help="台帳 / 走査対象の config (yaml)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    try:
        cfg = {}
        if a.config and a.config.exists():
            import yaml
            cfg = yaml.safe_load(a.config.read_text(encoding="utf-8")) or {}
        f = audit(a.root, cfg)
    except Exception as e:                      # noqa: BLE001 — dashboard を殺さない
        print(f"(check-office-review-artifacts: skip — {e})", file=sys.stderr)
        return 0
    if a.json:
        print(json.dumps([{"severity": s, "code": c, "message": m} for s, c, m in f],
                         ensure_ascii=False, indent=2))
        return 0
    if not f:
        return 0                                # healthy silent
    print("📕 赤入れ・校正済み現物の台帳 (= スキャンは grep に掛からないので file 単位で持つ)")
    for sev, code, msg in sorted(f, key=lambda x: (x[0] != "🔴", x[1])):
        print(f"   {sev} {code}: {msg}")
    print("   台帳 = config の registry / 読み方 = conventions/kakenhi-proposal.md#office-review-loop")
    return 0


if __name__ == "__main__":
    sys.exit(main())
