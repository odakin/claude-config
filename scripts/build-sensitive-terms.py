#!/usr/bin/env python3
"""build-sensitive-terms.py — 実名などの literal gate (Tier B) の term 一覧を SoT から生成する。

公開 repo の pre-commit は個人層の `sensitive-terms.txt` を literal 照合する (= Tier B)。
その一覧が**人手で維持されていると育たない**: 新しい同僚・共同研究者が増えても誰も足さず、
一覧が空でも hook は skip の 1 行を出して素通りする (= fail-open)。 その 1 行は毎 commit 出るので
noise に紛れる。 **実測**: 配線は在ったのに一覧に人名が 1 件も無く、 実在の氏名を公開 repo に
stage しても実 hook が rc=0 で通った。

対策 = 一覧を**連絡先などの SoT から生成**し、 ① SoT への追随 ② 実 hook で本当に止まるか
を毎回検査する。 一般則 = docs/convention-design-principles.md#detector-config-must-be-derived

⚠️ **layer 1 なので個人の source path も stoplist も持たない**。 個人層の
`sensitive-terms-sources.yaml` が持ち、 無ければ「対象外」 として静かに rc=0。

config (個人層 `sensitive-terms-sources.yaml`):
    sources: [contacts.md, ../other-repo/collaborators.yaml]   # 個人層からの相対 path
    cell_stoplist: [担当]        # 表の第 1 セルだが人名でない語
        # ⚠️ 連絡先 doc で 1 人分を `| 項目 | 値 |` の表で書くと、 項目名 (「住所」 等) が人名として拾われる (実測)。
        #    その doc は箇条書きにするか、 項目名をここに足す
    prefix_stoplist: [東京]      # 2 字 prefix が普通名詞になる語
    compound_allow: [東京駅前]   # term を含むが人名でない複合語 (地名等)。 照合の前に本文から消す (`!` 行で出力)
    commit_msg_sources: [../seminar/speakers.yaml]   # commit message だけに効く一覧 (個人層の commit-msg-terms.txt) の元
        # commit message の検査 (lib/commit-msg-leak-matcher.sh の (a)) は sensitive-terms.txt とこの一覧の両方を読み、
        # 公開 repo の本文の検査 (Tier B) はこの一覧を読まない = 公開の本文に普通に出る地名・公開データの名前で鳴らさずに、
        # commit message には人名を書かない運用を機械で守る。 読み方は sources より広い: yaml の `name_ja:` と list の
        # `- name:` も読み、 片仮名だけの名前は頭の字を語にしない (実測: 片仮名の名前の頭の 2 字が「ログイン」「ジョブ」 に当たった)

使い方:
  build-sensitive-terms.py --check    # SoT の名前が一覧に全部あるか (commit message だけの一覧も)
  build-sensitive-terms.py --write    # 生成 block を作り直す (commit message だけの一覧も)
  build-sensitive-terms.py --canary   # 実 hook で止まるかを temp の公開 repo で実測
  build-sensitive-terms.py --selftest
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

def _yaml_safe_load(stream):  # yaml.safe_load と同じ結果を C 版 (libyaml) で返す = 約 10 倍速 (2026-09-23)
    import yaml
    return yaml.load(stream, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))


HOME = Path.home()


def _personal_layer() -> Path | None:
    env = os.environ.get("CLAUDE_PERSONAL_LAYER")
    if env:
        return Path(env)
    base = HOME / "Claude"
    if not base.is_dir():
        return None
    for d in sorted(base.iterdir()):
        if (d / ".claude-personal-layer").exists():
            return d
    return None


PREFS = _personal_layer()
TERMS = (PREFS / "sensitive-terms.txt") if PREFS else None
CONFIG = (PREFS / "sensitive-terms-sources.yaml") if PREFS else None
CM_TERMS = (PREFS / "commit-msg-terms.txt") if PREFS else None   # commit message だけに効く一覧 (全体が生成物)

BEGIN = "# --- generated: SoT 由来の term (build-sensitive-terms.py --write。 手編集しない) ---"
END = "# --- end generated ---"

# 表の行頭 `| 漢字氏名 (Romaji ...)`
ROW_RE = re.compile(r"^\|\s*([\u3040-\u30ff\u4e00-\u9fff]{2,8})\s*[\uff08(]\s*([A-Za-z][A-Za-z .'-]{2,40})")
# 表の行頭 `| 漢字氏名 |` (= romaji 併記が無い行。 実測ではこちらが多数派)
PLAIN_RE = re.compile(r"^\|\s*([\u3040-\u30ff\u4e00-\u9fff]{2,8})\s*\|")
# 表の行頭 `| Romaji Name (漢字氏名)` (= 逆順)
REV_RE = re.compile(r"^\|\s*([A-Za-z][A-Za-z .'-]{3,40}?)\s*[\uff08(]\s*([\u3040-\u30ff\u4e00-\u9fff]{2,8})")
# yaml の `name: 漢字氏名`
YAML_RE = re.compile(r"^\s*(?:name|\u6c0f\u540d)\s*:\s*[\"']?([\u3040-\u30ff\u4e00-\u9fff]{2,8})")
# commit message だけの一覧の元に使う広い形: `name_ja:` と list の `- name:` も読む。 Tier B の元 (sources) には使わない
# = 公開 repo の本文の検査の語を変えない (広げると公開の本文の地名・公開データの名前に当たる = 実測)
YAML_WIDE_RE = re.compile(r"^\s*(?:-\s+)?(?:name|name_ja|\u6c0f\u540d)\s*:\s*[\"']?([\u3040-\u30ff\u4e00-\u9fff]{2,8})")
KATAKANA_RE = re.compile(r"^[\u30a0-\u30ff]+$")
CM_HEADER = ("# commit-msg-terms.txt — commit message だけに効く人名の一覧 (build-sensitive-terms.py --write が全体を作る。 手編集しない)\n"
             "# 読み手 = lib/commit-msg-leak-matcher.sh の (a) (sensitive-terms.txt と合わせて読む)。 公開 repo の本文の検査は読まない")

MIN_CJK_TERM = 2       # 1 字の姓は substring 照合で誤爆が多すぎる
MIN_ASCII_TERM = 4     # -w 照合。 短い romaji 姓は普通名詞と衝突する

DEFAULT_CELL_STOP = {"\u6c0f\u540d", "\u540d\u524d", "\u9805\u76ee", "\u62c5\u5f53",
                     "\u533a\u5206", "\u7a2e\u5225", "\u5099\u8003", "\u6240\u5c5e",
                     "\u9023\u7d61\u5148", "\u66dc\u65e5", "\u6642\u9650", "\u5185\u5bb9",
                     "\u5834\u6240", "\u65e5\u6642", "\u72b6\u614b", "\u5f79\u5272",
                     "\u5b66\u5e74", "\u30e1\u30e2", "\u6559\u54e1", "\u5b66\u751f",
                     "\u5352\u696d", "\u73fe\u5728"}

_CFG: dict | None = None


def load_config() -> dict | None:
    """個人層の config。 無ければ None (= 対象外)。"""
    global _CFG
    if _CFG is not None:
        return _CFG
    if not CONFIG or not CONFIG.exists():
        return None
    import yaml
    c = _yaml_safe_load(CONFIG.read_text()) or {}
    _CFG = {
        "sources": [(PREFS / s).resolve() for s in c.get("sources", [])],
        "cell_stoplist": set(c.get("cell_stoplist", [])) | DEFAULT_CELL_STOP,
        "prefix_stoplist": set(c.get("prefix_stoplist", [])),
        "compound_allow": [str(x).strip() for x in (c.get("compound_allow") or []) if str(x).strip()],
        "commit_msg_sources": [(PREFS / s).resolve() for s in c.get("commit_msg_sources", []) or []],
    }
    return _CFG


def extract_names(text: str, cell_stop: set[str] | None = None, wide: bool = False) -> tuple[set[str], set[str]]:
    """(CJK 名, ASCII 名) を返す。 file の形式は表 or yaml を想定。 wide = yaml の `name_ja:` と `- name:` も読む
    (commit message だけの一覧の元に使う)。"""
    yaml_re = YAML_WIDE_RE if wide else YAML_RE
    cjk, ascii_ = set(), set()
    # cell_stop は **全部の枝**に当てる。 PLAIN_RE の枝だけに当てていたので、
    # `| 見出し (english) | ... |` の形の表の見出し行が人名として拾われ、 その prefix
    # (= 普通名詞) が term になっていた。 括弧の中の英語も同じ行から来るので一緒に落とす。
    stop = cell_stop if cell_stop is not None else DEFAULT_CELL_STOP
    for line in text.splitlines():
        m = ROW_RE.match(line)
        if m:
            if m.group(1) not in stop:
                cjk.add(m.group(1))
                ascii_.add(" ".join(m.group(2).split()))
            continue
        m = REV_RE.match(line)
        if m:
            if m.group(2) not in stop:
                ascii_.add(" ".join(m.group(1).split()))
                cjk.add(m.group(2))
            continue
        m = PLAIN_RE.match(line)
        if m:
            if m.group(1) not in stop:
                cjk.add(m.group(1))
            continue
        m = yaml_re.match(line)
        if m and m.group(1) not in stop:
            cjk.add(m.group(1))
    return cjk, ascii_


def expand_cjk(name: str, prefix_stop: set[str] | None = None, katakana_whole: bool = False) -> set[str]:
    """氏名から term を作る。 **姓だけの表記も実際に書かれる**ので prefix も出す。

    姓と名の境界は CJK 連結名から確定できないため、 長さ 2..len-1 の prefix を全部出す。

    ⚠️ 「余分な prefix は実在しない語なので害が無い」 は **偽**。 短い prefix は普通名詞に
    なることがあり (実測: 2-4 字の prefix が公開 repo の 1 file あたり数十行に当たった)、
    そうなると gate の報告が過検出で埋まって**真の hit が表示窓から押し出される**。
    過検出の costs は 0 ではない = prefix_stoplist で落とす。
    規律 = docs/convention-design-principles.md#display-cap-is-not-the-count
    """
    out = {name}
    if katakana_whole and KATAKANA_RE.match(name):
        return out   # 片仮名だけの名前 (多くは名が先の外国の名前) は頭の字を語にしない = 普通の語の頭と重なる
    for k in range(MIN_CJK_TERM, len(name)):
        p = name[:k]
        if p not in (prefix_stop or set()):
            out.add(p)
    return out


def collect(sources=None, wide: bool = False) -> tuple[set[str], set[str], list[str]]:
    cfg = load_config()
    if cfg is None and sources is None:
        return set(), set(), []
    cell_stop = cfg["cell_stoplist"] if cfg else DEFAULT_CELL_STOP
    prefix_stop = cfg["prefix_stoplist"] if cfg else set()
    cjk, ascii_, seen = set(), set(), []
    for p in (sources if sources is not None else cfg["sources"]):
        p = Path(p)
        if not p.exists():
            continue
        seen.append(p.name)
        c, a = extract_names(p.read_text(errors="replace"), cell_stop, wide=wide)
        for n in c:
            cjk |= expand_cjk(n, prefix_stop, katakana_whole=wide)
        for n in a:
            if len(n) >= MIN_ASCII_TERM:
                ascii_.add(n)
    return cjk, ascii_, seen


def validate_compounds(compounds, terms) -> tuple[list[str], list[str]]:
    """(使える複合語, 問題) を返す。

    複合語の許可は「姓の 2 字 prefix が地名などに当たる」 誤検知だけを消す口 (= prefix を stoplist に落とすと
    「X さん」 も止まらなくなるので、 その複合語だけを許可する)。 **3 字以上の term (= 氏名に近い語) や ASCII の
    term を含む複合語は許可しない** — 許可すると氏名そのものを消す抜け道になる。 term を 1 つも含まない複合語は
    問題として返す (= 検出語の再生成で当たらなくなった許可が溜まらないように)。
    """
    ok, problems = [], []
    long_terms = [t for t in terms if not t.isascii() and len(t) >= 3]
    ascii_terms = [t for t in terms if t.isascii()]
    short_terms = [t for t in terms if not t.isascii() and len(t) < 3]
    for c in compounds:
        if c.startswith(("!", "#")):
            problems.append(f"{mask(c)}: 先頭が ! か # (= 行の種類の記号と衝突)")
        elif any(t in c for t in long_terms) or any(t.lower() in c.lower() for t in ascii_terms):
            problems.append(f"{mask(c)}: 3 字以上の term か ASCII の term を含む (= 氏名を消す抜け道になる)")
        elif not any(t in c for t in short_terms):
            problems.append(f"{mask(c)}: どの term も含まない (= 許可する意味が無い)")
        else:
            ok.append(c)
    return ok, problems


def mask(t: str) -> str:
    return t[0] + "…" if len(t) > 1 else "…"


def collect_commit_msg(main_terms: set[str]) -> tuple[list[str], list[str]]:
    """commit message だけの一覧の (語, 読んだ source)。 sensitive-terms.txt に既に在る語は入れない (二重にしない)。"""
    cfg = load_config()
    if not cfg or not cfg["commit_msg_sources"]:
        return [], []
    cjk, ascii_, seen = collect(cfg["commit_msg_sources"], wide=True)
    return sorted(cjk - main_terms) + sorted(ascii_ - main_terms), seen


def read_cm_terms() -> list[str]:
    if not CM_TERMS or not CM_TERMS.exists():
        return []
    return [l.strip() for l in CM_TERMS.read_text().splitlines() if l.strip() and not l.strip().startswith("#")]


def _zero_name_sources() -> list[str]:
    """宣言した Tier B の source のうち、 在るのに名前を 1 件も拾えないもの (= 形式が読めていない。 実測: yaml の
    `name_ja:` の台帳が宣言されたまま 0 件だった)。 Tier B の読み方は変えずに知らせる (広げると公開の本文で鳴る)。"""
    cfg = load_config()
    out = []
    for p in (cfg["sources"] if cfg else []):
        p = Path(p)
        if p.exists() and p.read_bytes()[:10] != b"\x00GITCRYPT\x00"[:10]:
            c, a = extract_names(p.read_text(errors="replace"), cfg["cell_stoplist"])
            if not c and not a:
                out.append(p.name)
    return out


def read_terms() -> tuple[list[str], list[str]]:
    """(手書き行, 生成 block の行) に割る。 file 不在なら空。"""
    if not TERMS or not TERMS.exists():
        return [], []
    lines = TERMS.read_text().splitlines()
    if BEGIN in lines and END in lines:
        b, e = lines.index(BEGIN), lines.index(END)
        return lines[:b] + lines[e + 1:], lines[b + 1:e]
    return lines, []


def cmd_write() -> int:
    if load_config() is None:
        print("対象外 [sensitive-terms]: 個人層に sensitive-terms-sources.yaml が無い")
        return 0
    cjk, ascii_, seen = collect()
    manual, _ = read_terms()
    compounds, problems = validate_compounds(load_config()["compound_allow"], cjk | ascii_)
    if problems:
        print("✗ compound_allow に使えない複合語がある (書き込まない):")
        for pr in problems:
            print("  " + pr)
        return 1
    block = sorted(cjk) + sorted(ascii_) + ["!" + c for c in sorted(compounds)]
    body = [l for l in manual if l.strip()] + [BEGIN] + block + [END]
    TERMS.write_text("\n".join(body) + "\n")
    print(f"wrote {TERMS.name}: 手書き {len([l for l in manual if l.strip()])} 行 + 生成 {len(block)} 件 "
          f"(CJK {len(cjk)} / ASCII {len(ascii_)}) from {', '.join(seen)}")
    print("  sample:", " ".join(mask(t) for t in block[:6]))
    main_terms = set(l.strip() for l in manual + block if l.strip() and not l.strip().startswith(("#", "!")))
    cm, cm_seen = collect_commit_msg(main_terms)
    if load_config()["commit_msg_sources"]:
        if CM_TERMS.is_symlink() and not CM_TERMS.resolve().parent.is_dir():
            print(f"skip [commit-msg-terms]: {CM_TERMS.name} の行き先の dir が無い (= その repo を clone していない)")
            return 0
        CM_TERMS.write_text(CM_HEADER + "\n" + "\n".join(cm) + "\n")
        print(f"wrote {CM_TERMS.name}: 生成 {len(cm)} 件 (commit message だけ) from {', '.join(cm_seen)}")
    for name in _zero_name_sources():
        print(f"⚠️  [sensitive-terms] 宣言した source {name} から名前を 1 件も拾えない (= 形式が読めていない。 Tier B の語は変えていない)")
    return 0


def cmd_check() -> int:
    if load_config() is None:
        print("対象外 [sensitive-terms]: 個人層に sensitive-terms-sources.yaml が無い")
        return 0
    cjk, ascii_, seen = collect()
    if not seen:
        print("skip [sensitive-terms]: 連絡先 SoT がこのマシンに無い (= 守る対象が無い)")
        return 0
    manual, gen = read_terms()
    have = set(l.strip() for l in manual + gen if l.strip() and not l.strip().startswith(("#", "!")))
    missing = sorted((cjk | ascii_) - have)
    compounds, problems = validate_compounds(load_config()["compound_allow"], cjk | ascii_)
    allowed_have = set(l.strip()[1:] for l in gen if l.strip().startswith("!"))
    if problems:
        print("BROKEN [sensitive-terms]: compound_allow に使えない複合語がある")
        for pr in problems:
            print("  " + pr)
        return 1
    if set(compounds) != allowed_have:
        print(f"STALE [sensitive-terms]: 許可複合語が設定と一致しない (設定 {len(compounds)} / 一覧 {len(allowed_have)})")
        print("  → python3 scripts/build-sensitive-terms.py --write")
        return 1
    if not TERMS.exists() or not have:
        print(f"NOT ARMED [sensitive-terms]: {TERMS.name} が空か不在 — "
              f"公開 repo の Tier B は素通りする。 --write で生成する")
        return 1
    if missing:
        print(f"STALE [sensitive-terms]: SoT の人名 {len(missing)} 件が一覧に無い "
              f"(= その名前は公開 repo に書いても止まらない)")
        print("  " + " ".join(mask(t) for t in missing[:12]))
        print(f"  → python3 scripts/build-sensitive-terms.py --write")
        return 1
    print(f"ARMED [sensitive-terms]: {len(have)} term ({', '.join(seen)} 由来 {len(cjk | ascii_)} 件を含む)")
    for name in _zero_name_sources():
        print(f"⚠️  [sensitive-terms] 宣言した source {name} から名前を 1 件も拾えない (= 形式が読めていない。 Tier B の語は変えていない)")
    if load_config()["commit_msg_sources"]:
        cm, cm_seen = collect_commit_msg(have)
        if not cm_seen:
            print("skip [commit-msg-terms]: commit message だけの一覧の元がこのマシンに無い")
            return 0
        have_cm = set(read_cm_terms())
        if not have_cm and cm:
            print(f"NOT ARMED [commit-msg-terms]: {CM_TERMS.name} が空か不在 — 一覧に無い人名は commit message に書いても止まらない。"
                  " --write で生成する")
            return 1
        miss = sorted(set(cm) - have_cm)
        if miss:
            print(f"STALE [commit-msg-terms]: 元の人名 {len(miss)} 件が一覧に無い → python3 scripts/build-sensitive-terms.py --write")
            print("  " + " ".join(mask(t) for t in miss[:12]))
            return 1
        print(f"ARMED [commit-msg-terms]: {len(have_cm)} term ({', '.join(cm_seen)} 由来)")
    return 0



def cmd_canary() -> int:  # noqa: C901
    """Tier B が **実際に commit を止めるか** を temp の公開 repo で毎回確かめる。

    今回の失敗は「一覧が空でも hook は `[tier-b/skip]` と出して素通りする」 (= fail-open) で、
    その 1 行は毎 commit 出るので noise に紛れていた。 **配線の死活は宣言でなく実測で持つ**。
    ⚠️ 一覧から取った実在の term を temp repo に書くので、 push しない dir でのみ行い、
       term は stdout に出さない。
    """
    import shutil
    import subprocess
    import tempfile

    if load_config() is None:
        print("対象外 [sensitive-terms/canary]: 個人層に sensitive-terms-sources.yaml が無い")
        return 0
    manual, gen = read_terms()
    terms = [l.strip() for l in gen if l.strip() and not l.strip().startswith(("#", "!"))]
    if not terms:
        print("NOT ARMED [sensitive-terms/canary]: 生成 block が空 — 止める対象が無い")
        return 1
    runner = HOME / "Claude" / "claude-config" / "scripts" / "public-precommit-runner.sh"
    if not runner.exists():
        print("skip [sensitive-terms/canary]: 層1 runner がこのマシンに無い")
        return 0
    probe = max(terms, key=len)          # 最も長い = 最も誤爆しにくい term
    d = Path(tempfile.mkdtemp())
    try:
        subprocess.run(["git", "init", "-q", str(d)], check=True)
        (d / ".claude").mkdir()
        (d / ".claude" / "public-repo.marker").touch()
        hooks = d / ".git" / "hooks"
        (hooks / "pre-commit").write_text('#!/bin/sh\nexec "%s" "$@"\n' % runner)
        (hooks / "pre-commit").chmod(0o755)
        for k, v in (("user.email", "canary@example.com"), ("user.name", "canary")):
            subprocess.run(["git", "-C", str(d), "config", k, v], check=True)

        def commit(path: Path, body: str) -> int:
            path.write_text(body)
            subprocess.run(["git", "-C", str(d), "add", path.name], check=True)
            r = subprocess.run(["git", "-C", str(d), "commit", "-m", "canary"],
                               capture_output=True, text=True)
            return r.returncode

        rc_bad = commit(d / "bad.txt", "x = %s\n" % probe)
        subprocess.run(["git", "-C", str(d), "reset", "-q"], check=True)
        rc_ok = commit(d / "ok.txt", "x = generic placeholder\n")
    finally:
        shutil.rmtree(d, ignore_errors=True)
    if rc_bad == 0:
        print("NOT ARMED [sensitive-terms/canary]: 人名を含む commit が通った (= Tier B が死んでいる)")
        return 1
    if rc_ok != 0:
        print("BROKEN [sensitive-terms/canary]: 人名を含まない commit まで止まった (= 誤爆)")
        return 1
    print("ARMED [sensitive-terms/canary]: 実 hook で人名 commit は reject、 通常 commit は通過 "
          "(%d term)" % len(terms))
    return 0

def selftest() -> int:
    ok = fail = 0

    def check(c, label):
        nonlocal ok, fail
        if c:
            ok += 1
            print(f"  PASS: {label}")
        else:
            fail += 1
            print(f"  FAIL: {label}")

    c, a = extract_names("| 甲野太郎 (Taro Kono) | x |\n| 乙野花子（Hanako Otsuno） | y |\n")
    check(c == {"甲野太郎", "乙野花子"}, "T1: 表の行から CJK 氏名 (全角/半角の括弧とも)")
    check("Taro Kono" in a and "Hanako Otsuno" in a, "T2: 括弧内の romaji")
    c2, _ = extract_names("  name: 丙野次郎\n")
    check(c2 == {"丙野次郎"}, "T3: yaml の name:")
    check(extract_names("| 甲 (Ko) |")[0] == set(), "T4: 1 字の CJK は拾わない")
    c3, _ = extract_names("| 丁野三郎 | 連絡先 |\n| 氏名 | x |\n")
    check(c3 == {"丁野三郎"}, "T4b: romaji 無しの素セルを拾い、 見出しは除く")
    c4, a4 = extract_names("| Taro Kono (甲野太郎) | x |\n")
    check(c4 == {"甲野太郎"} and "Taro Kono" in a4, "T4c: romaji(漢字) の逆順")
    check(extract_names("| 2026.09 | x |\n| 10:30–12:00 | y |\n")[0] == set(),
          "T4d: 日付・時刻セルは名前でない")
    # cell_stop は PLAIN_RE の枝だけでなく全部の枝に当たる (= 見出し行を人名にしない)。
    # 落ちていると、 見出しの prefix が普通名詞の term になって gate の報告を埋める。
    c5, a5 = extract_names("| 用途 (labeling) | アドレス |\n", {"用途"})
    check(c5 == set() and a5 == set(), "T4e: 見出し (CJK (english)) は CJK も括弧内も拾わない")
    c6, a6 = extract_names("| Labeling Note (用途) | x |\n", {"用途"})
    check(c6 == set() and a6 == set(), "T4f: 逆順の見出しも同じ")
    check(extract_names("  name: 用途\n", {"用途"})[0] == set(), "T4g: yaml の name: にも当たる")

    e = expand_cjk("甲野太郎", set())
    check("甲野太郎" in e and "甲野" in e, "T5: 全体と 2 字 prefix の両方")
    check("甲" not in e, "T6: 1 字 prefix は出さない (誤爆源)")
    check("東京" not in expand_cjk("東京太郎", {"東京"}), "T7: stoplist の prefix は出さない")
    check(expand_cjk("甲野", set()) == {"甲野"}, "T8: 2 字名は自身のみ")

    ok_c, pr_c = validate_compounds(["甲野町", "甲野太郎通り", "Kono Park", "乙町"], {"甲野", "甲野太郎", "Kono"})
    check(ok_c == ["甲野町"], "T11: 2 字 term を含む複合語だけ許可")
    check(len(pr_c) == 3, "T12: 3 字以上の term / ASCII term を含む・term を含まない複合語は拒否")
    check(mask("甲野太郎") == "甲…", "T9: mask は先頭 1 字だけ残す")
    check(len(mask("甲野")) == 2, "T10: mask 後の長さ")

    # commit message だけの一覧の広い読み方 (Tier B の読み方は変えない)
    check(extract_names("  name_ja: 丙野次郎\n")[0] == set(), "T13: 狭い読み方は name_ja: を読まない (Tier B の語を変えない)")
    check(extract_names("  name_ja: 丙野次郎\n", wide=True)[0] == {"丙野次郎"}, "T14: 広い読み方は name_ja: を読む")
    check(extract_names("  - name: 戊野四郎\n", wide=True)[0] == {"戊野四郎"}, "T15: 広い読み方は list の - name: を読む")
    check(extract_names("  name_ja: 丙野 次郎\n", wide=True)[0] == {"丙野"}, "T16: 姓と名の間に空白があれば姓だけ")
    check(expand_cjk("ホゲフガ", set(), katakana_whole=True) == {"ホゲフガ"}, "T17: 片仮名だけの名前は頭の字を語にしない")
    check("ホゲ" in expand_cjk("ホゲフガ", set()), "T18: Tier B の展開は変えない (片仮名の頭も従来どおり)")
    check("甲野" in expand_cjk("甲野太郎", set(), katakana_whole=True), "T19: 漢字の名前は広い読み方でも頭の字を語にする")

    print(f"\n==== RESULT: PASS={ok} FAIL={fail} ====")
    return 1 if fail else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--write", action="store_true")
    p.add_argument("--check", action="store_true")
    p.add_argument("--canary", action="store_true")
    p.add_argument("--selftest", action="store_true")
    a = p.parse_args()
    if a.selftest:
        return selftest()
    if a.write:
        return cmd_write()
    if a.check:
        return cmd_check()
    if a.canary:
        return cmd_canary()
    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
