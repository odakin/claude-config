#!/usr/bin/env python3
"""check-sot-drift.py — 「規則の正本は 1 か所、 他所は参照だけ」 を目印の文字列で機械検査する (registry 駆動)

registry (YAML) に topic ごとに次を登録する:
  home            正本の file (root からの相対 path)
  home_section    正本の節 (見出し文字列か anchor id)
  anchor_tokens   目印 = 正本にある「規約を定義する文」 の固有の言い回し (語そのものは置かない)
  pointer_patterns 「参照あり」 とみなす文字列 (正本と結び付く形 = anchor id / topic 名 / file 名)
  allow_globs     書き写しが正当な場所 (履歴・生成物・下流の実装など)
  superseded      (任意) 旧規則の語と、 それを探す glob = 転換後も手順書に旧規則が生きていないか
  audit_ack       (任意) 点検 (audit_registry) で正当と読んで判断したもの {対象: 理由}

検出 (scan):
  目印が正本の外に「参照なし」 で出たら flag する。 窓 (前後 window_lines 行) に参照文字列・
  正本の file 名・節名があれば参照ありとみなす。 正本の file 名が走査対象で一意でない (`README.md` 等)
  ときは、 bare な名前は「正本と同じ repo の中から」 か「窓に repo 名がある」 ときだけ参照とみなし、
  それ以外は「親 dir/名前」 の形を要求する。 自動生成 block (`<!-- AUTO-* BEGIN/END -->`・先頭に
  AUTO-GENERATED) と `*.index.yaml` は生成物なので走査しない。

点検 (audit_registry、 既定で scan と一緒に回る):
  never-fires / missing-in-home / broad-pointer / term-like-anchor の 4 つ。 語の一覧は持たず、
  構造 (参照判定との包含・正本との結び付き) と実データ (出現回数・頻度) で判定する。

判定の原則と、 finding を直すときの順序 (本文でなく registry 側を直す場合がある) =
  claude-config/docs/convention-design-principles.md#literal-anchor-detector
  claude-config/docs/convention-design-principles.md#flagged-text-is-not-the-defect
⚠️ 射程: 登録 topic の文字列一致だけ。 言い換えた書き写しと未登録の重複は見えない
  (= convention-design-principles.md#proxy-blind-spot)。

使い方:
  check-sot-drift.py --registry REG.yaml [--root DIR] [--no-audit]   # finding 0 件なら無出力、 常に exit 0
  check-sot-drift.py --selftest
登録は sot-registry-add.py (書く前に同じ点検を通す)。
"""

from __future__ import annotations

import argparse
import collections
import fnmatch
import os
import re
import sys
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML が必要: pip install pyyaml")


SCAN_EXT = (".md", ".yaml", ".yml")
SKIP_DIR_PARTS = {".git", "node_modules", ".obsidian"}


def iter_files(root: Path):
    """root 配下の *.md / *.yaml を yield (.git / symlink / 重複 resolve は skip)。

    symlink を skip する理由: 作業 root 直下の入口 file が各 repo の実体への symlink になっている構成
    (例: <root>/CONVENTIONS.md → <repo>/CONVENTIONS.md) では、 file symlink を
    辿ると同一 real file を二重 scan し、 findings が二重計上される。 real file は
    自身の canonical path 経由で別途 scan されるので symlink は飛ばしてよい。
    belt-and-suspenders で resolve 済 path の dedup も併用 (= symlink dir 経由の
    二重も防ぐ)。
    """
    seen: set[Path] = set()
    # ⚠️ rglob("*") は SKIP_DIR_PARTS の中 (.git / node_modules 等) まで降りてから捨てるので、
    #    enumerate だけで 11 秒かかっていた (実測)。os.walk で **降りる前に刈る**。
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # git worktree は repo の写しであって別の正本ではない。 降りると home file の写しを
        # 「home 外の重複」 として拾う (実測: 置き場が `<repo>/.claude/worktrees/` と `<root>/.worktrees/` の
        #  2 つあるので dir 名で刈る)。
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIR_PARTS
                       and d != ".worktrees"
                       and not (d == "worktrees" and os.path.basename(dirpath) == ".claude")
                       and not os.path.islink(os.path.join(dirpath, d))]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.is_symlink():
                continue
            if p.suffix not in SCAN_EXT or not p.is_file():
                continue
            if p.name.endswith(".index.yaml"):
                # auto-generated slug index (generate-doc-index.py) — echoes the home
                # doc's own section titles, so any topic whose title names its concept
                # would FP on its own index. Derived artifact, never a real SoT home.
                continue
            if SKIP_DIR_PARTS & set(p.parts):
                continue
            rp = p.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            yield p


def read_lines(p: Path) -> list[str]:
    """file を行 list で返す。 自動生成 block (`<!-- AUTO-* BEGIN -->`〜`<!-- AUTO-* END -->`、
    例 = 索引生成 script の AUTO-TREE / AUTO-ENUM) 内は空行に置換して除外する —
    生成物は源 metadata の view であって authoritative 記述になり得ず (§2.5 派生データ)、
    列挙行が registry の anchor token を機械的に含むだけで drift ではない
    (実測)。
    行番号を保つため削除でなく空行置換。"""
    try:
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    # whole-file 型: 先頭 3 行以内に AUTO-GENERATED marker を持つ file は全体が生成物
    # (例: conventions/README.md = generate-tree.py 産物、 *.index.yaml と同じ地位)。
    # block 型 marker (BEGIN/END) を持たないので、 ここで file ごと除外する。
    if any("AUTO-GENERATED" in ln for ln in lines[:3]):
        return []
    # ⚠️ marker 判定は regex で構造 match する (= 旧 substring 判定 `"<!-- AUTO-" in ln and
    # "BEGIN" in ln` は、 prose が marker を説明で引用しただけの行 (例: CLAUDE.md の
    # 「生成物は scan 除外 = `<!-- AUTO-* BEGIN/END -->` block」) を block 開始と誤認し、
    # END 不在のため **その行以降の file 全体を blank 化**していた (実測: 引用行より後ろに anchor を持つ
    # home で、 偽の「token 無し」 警告が出た)。 実 marker は `AUTO-` の直後が
    # 英字の識別子 (AUTO-TREE 等)、 prose 引用は `AUTO-*` (記号) なので識別可能)。
    _begin = re.compile(r"<!--\s*AUTO-[A-Za-z][\w:-]*\b.*\bBEGIN\b")
    _end = re.compile(r"<!--\s*AUTO-[A-Za-z][\w:-]*\b.*\bEND\b")
    out, in_auto = [], False
    for ln in lines:
        if _begin.search(ln):
            in_auto = True
            out.append("")
            continue
        if in_auto and _end.search(ln):
            in_auto = False
            out.append("")
            continue
        out.append("" if in_auto else ln)
    return out


def load_files(root: Path, registry_path: Path | None = None) -> list[tuple[str, list[str], str]]:
    """scan 対象を一度だけ読む: (rel, lines, text)。 registry 自身は除外 (= 構造的 self-flag 防止)。"""
    reg_resolved = registry_path.resolve() if registry_path else None
    files: list[tuple[str, list[str], str]] = []
    for p in iter_files(root):
        if reg_resolved and p.resolve() == reg_resolved:
            continue
        rel = str(p.relative_to(root))
        lines = read_lines(p)
        # ⚠️ 以前は (topic × file × token) ごとに全行を走査していた。
        #    file 全文への `in` を先に 1 回通すと、当たらない大多数で行 loop に入らずに済む
        #    (実測で桁違いに速くなった)。意味は変わらない (同じ token の有無を見る)。
        files.append((rel, lines, "\n".join(lines)))
    return files


def pointer_context(t: dict, basename_count: collections.Counter) -> dict:
    """topic の pointer 判定の材料 (scan と audit が同じものを使う = 判定が 2 箇所で食い違わない)。

    home の file 名を pointer とみなすのは、 その名前が scan 対象の中で一意なときだけ。
    `CLAUDE.md` / `SESSION.md` / `README.md` のように複数 repo に同名 file があると、 窓に
    「CLAUDE.md」 と書いてあるだけで (別 repo の CLAUDE.md の話でも) pointer 扱いになり、
    書き写した規則が永久に鳴らなかった (実測)。 同名が複数あるときは
    「親 dir/名前」 の形、 home と同じ repo の中からの bare な名前、 窓に「<home の repo>/」 がある
    bare な名前だけを pointer にする。
    """
    home = t.get("home", "")
    home_section = t.get("home_section", "")
    patterns = list(t.get("pointer_patterns", []) or [])
    home_name = Path(home).name if home else ""
    home_repo = home.split("/", 1)[0] if home else ""
    same_repo_only = ""
    if home_name:
        if basename_count[home_name] > 1:
            # registry に明示で home 名 (bare) を書いた topic も同じ扱いにする (= 明示側から穴を開け直さない)
            patterns = [pp for pp in patterns if pp != home_name]
            patterns.append(str(Path(*Path(home).parts[-2:])))
            same_repo_only = home_name
        else:
            patterns.append(home_name)
    if home_section:
        patterns.append(home_section)
    return {"patterns": patterns, "same_repo_only": same_repo_only, "home_repo": home_repo}


def window_has_pointer(win: str, rel: str, ctx: dict) -> bool:
    if any(pp and pp in win for pp in ctx["patterns"]):
        return True
    bare = ctx["same_repo_only"]
    if not bare or bare not in win:
        return False
    return rel.split("/", 1)[0] == ctx["home_repo"] or (ctx["home_repo"] + "/") in win


def scan(
    root: Path, registry: dict, registry_path: Path | None = None,
    files: list[tuple[str, list[str], str]] | None = None,
) -> tuple[list[dict], list[str]]:
    """(findings, config_warnings) を返す。

    findings: {topic, rel, lineno, token, home}
    config_warnings: registry が stale な可能性の文字列 (= home が anchor を含まない等)

    registry_path: 指定すると scan 対象から除外する。 registry 自身は anchor_tokens を
      構造的に含む (= フィールド値そのもの) ため、 scan すると必ず self-flag する。
    files: load_files() の結果を渡すと再読込しない (= audit と共有)。
    """
    window = int(registry.get("window_lines", 15))
    topics = registry.get("topics", []) or []
    findings: list[dict] = []
    config_warnings: list[str] = []

    if files is None:
        files = load_files(root, registry_path)
    basename_count = collections.Counter(Path(rel).name for rel, _, _ in files)

    for t in topics:
        topic = t.get("topic", "?")
        home = t.get("home", "")
        home_section = t.get("home_section", "")
        anchors = t.get("anchor_tokens", []) or []
        allow_globs = t.get("allow_globs", []) or []
        ctx = pointer_context(t, basename_count)

        if not anchors:
            config_warnings.append(f"{topic}: anchor_tokens 未設定 (= 検出不能)")
            continue

        # home sanity: home に anchor が 1 つも無ければ registry が stale の疑い。
        # ⚠️ scan 対象外拡張子 (= SCAN_EXT 不一致、 例: code-as-SoT で .py が home) は
        # files list に乗らないので、 disk 直 read で anchor check を行う (= 不在判定は
        # 「scan で見つからない」 でなく「disk 上に無い」 でする = false stale 警告を防ぐ)。
        home_lines = next((ls for rel, ls, _ in files if rel == home), None)
        if home_lines is None:
            home_path = (root / home) if home else None
            if home_path and home_path.is_file():
                try:
                    home_text = home_path.read_text(encoding="utf-8", errors="replace")
                except OSError as e:
                    # read 失敗を silent skip すると registry stale を見逃すので warn
                    config_warnings.append(
                        f"{topic}: home `{home}` の read に失敗 ({e!s}) — anchor 検査不能"
                    )
                    home_text = None
                if home_text is not None:
                    if not home_text:
                        # 0 byte home は silent skip すると registry stale を見逃すので warn
                        config_warnings.append(
                            f"{topic}: home `{home}` が空 (0 byte) — anchor 検査不能"
                        )
                    elif not any(a in home_text for a in anchors):
                        config_warnings.append(
                            f"{topic}: home `{home}` に anchor token が無い "
                            f"(= token 改名 or home 移動の可能性、 registry 更新要)"
                        )
            else:
                config_warnings.append(f"{topic}: home `{home}` が root 配下に不在")
        else:
            home_text = "\n".join(home_lines)
            if not any(a in home_text for a in anchors):
                config_warnings.append(
                    f"{topic}: home `{home}` に anchor token が無い "
                    f"(= token 改名 or home 移動の可能性、 registry 更新要)"
                )

        for rel, lines, text in files:
            if rel == home:
                continue  # home = SoT、 anchor を含むのが正常
            # ⚠️ 判定は安い順に。fnmatch (regex) を全 (topic × file) で回すと 83 万回になる。
            #    token の `in` は C の substring 検索で桁違いに安く、しかも大多数が外れる。
            hits = [tok for tok in anchors if tok in text]
            if not hits:
                continue
            if any(fnmatch.fnmatch(rel, g) for g in allow_globs):
                continue
            text_joined_cache: dict[tuple[int, int], str] = {}
            for token in hits:
                for i, line in enumerate(lines):
                    if token not in line:
                        continue
                    lo = max(0, i - window)
                    hi = min(len(lines), i + window + 1)
                    key = (lo, hi)
                    win = text_joined_cache.get(key)
                    if win is None:
                        win = "\n".join(lines[lo:hi])
                        text_joined_cache[key] = win
                    if window_has_pointer(win, rel, ctx):
                        continue  # pointer 付き mention → §7 許容
                    findings.append(
                        {
                            "topic": topic,
                            "rel": rel,
                            "lineno": i + 1,
                            "token": token,
                            "home": home,
                            "home_section": home_section,
                        }
                    )

    findings += _scan_superseded(files, topics)

    return findings, config_warnings


# ---- registry 自体の点検 (= 目印が鳴るか・語に見えるか・pointer が広すぎないか) ----------------
# 語の一覧は持たない。 判定は構造 (pointer 判定との包含・home との結び付き) と実データ (出現回数・頻度) だけ。
# 閾値は実データの分布で決めた (実測): 定義文の anchor はほぼ home に 1 回、 語の anchor は home で
# 繰り返し使われる / home と無関係な問題の pointer (節番号・repo 名などの一般語) は scan 対象の 1% を大きく超えて出る。
# registry の規模が違えば分布を測り直す。
AUDIT_HOME_REPEAT = 3
AUDIT_POINTER_FREQ_RATIO = 0.01
# 識別子の形 (= 空白を含まない ASCII / code 記号 / 拡張子つき)。 識別子は home で繰り返されても正当。
IDENTIFIER_SHAPE = re.compile(r"^[\x21-\x7e]+$|[_`/\\{}\[\]$<>=]|\.\w{1,5}\b")
FOIL_REL = "__sot_audit_foil__/foil.md"


def _home_text(root: Path, home: str, files) -> str | None:
    for rel, _lines, text in files:
        if rel == home:
            return text
    p = root / home if home else None
    if p and p.is_file():
        try:
            return p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    return None


def audit_registry(
    root: Path, registry: dict, registry_path: Path | None = None,
    files: list[tuple[str, list[str], str]] | None = None,
) -> list[dict]:
    """registry の各 topic を点検し、 {level, topic, kind, subject, detail} の list を返す。

    kind:
      never-fires       🔴 anchor が pointer 判定に含まれ、 home 外に書き写しても永久に鳴らない
                           (= home と無関係な場所に anchor だけの 1 行を置いた foil で確かめる)
      missing-in-home   🟠 anchor が home に無い (全部無いときは scan の config 警告。 ここは 1 個ずつ)
      broad-pointer     🟠 pointer_patterns が home と結び付かず (file 名の stem・home_section・topic・
                           home 内の anchor id のどれも含まない)、 scan 対象の 1% を超える file に出る
                           = 近くにその語があるだけで書き写しが黙認される
      term-like-anchor  🟡 識別子の形でない anchor が home で 3 回以上使われている = 規約の語そのものを
                           目印にしている疑い (定義文なら home に 1 回)
    topic の `audit_ack: {<anchor か pointer>: <理由>}` に載せたものは報告しない
    (= 読んで正当と判断したものだけを載せる。 層1 convention-design-principles.md#semantic-detector-ack-ratchet)。
    """
    if files is None:
        files = load_files(root, registry_path)
    basename_count = collections.Counter(Path(rel).name for rel, _, _ in files)
    n_files = max(len(files), 1)
    freq_cache: dict[str, int] = {}
    out: list[dict] = []
    for t in registry.get("topics", []) or []:
        topic = t.get("topic", "?")
        home = t.get("home", "")
        ack = t.get("audit_ack") or {}
        anchors = [str(a) for a in (t.get("anchor_tokens") or [])]
        ctx = pointer_context(t, basename_count)
        htext = _home_text(root, home, files)
        if htext is None:
            continue  # home 不在・読めない = scan の config 警告が扱う
        ids = set(re.findall(r'<a id="([^"]+)"', htext))

        def add(level, kind, subject, detail):
            if subject not in ack:
                out.append({"level": level, "topic": topic, "kind": kind, "subject": subject, "detail": detail})

        present = [a for a in anchors if a in htext]
        if present:  # 全部無いときは scan の config 警告に任せる (二重に出さない)
            for a in anchors:
                if a not in htext:
                    add("🟠", "missing-in-home", a, f"home `{home}` に無い")
        for a in present:
            if window_has_pointer(a, FOIL_REL, ctx):
                hit = [pp for pp in ctx["patterns"] if pp and pp in a] or [ctx["same_repo_only"]]
                add("🔴", "never-fires", a, f"pointer 判定 {hit} を含むので、 書き写しても鳴らない")
            count = htext.count(a)
            if count >= AUDIT_HOME_REPEAT and not IDENTIFIER_SHAPE.search(a):
                add("🟡", "term-like-anchor", a, f"home で {count} 回使われている (定義文なら 1 回)")
        stem = Path(home).stem
        for pp in t.get("pointer_patterns") or []:
            s = str(pp)
            tied = (stem and stem in s) or s == t.get("home_section") or s == topic or any(i in s for i in ids)
            if tied:
                continue
            if s not in freq_cache:
                freq_cache[s] = sum(1 for _r, _l, text in files if s in text)
            if freq_cache[s] > n_files * AUDIT_POINTER_FREQ_RATIO:
                add("🟠", "broad-pointer", s,
                    f"home と結び付かない語が {freq_cache[s]} file ({freq_cache[s] * 100 // n_files}%) に出る")
    return out


# 旧規則の記述が「歴史として書かれている」 ことを示す語 (= window 内にあれば flag しない)。
# ⚠️ 語の列挙は収束しない前提 — 漏れた表現は FP として出るので、 その時は marker を足すか
#    当該 path を allow_globs に入れる (= 判断は人間、 検出器は候補を出すだけ)。
_HISTORICAL_MARKERS = (
    "supersede", "スーパーシード", "旧運用", "旧記述", "旧方針", "履歴", "撤回",
    "errata", "起票時記述", "当時", "〜まで", "以前は", "だった",
)


def _scan_superseded(files, topics) -> list[dict]:
    """**旧規則の生存**を検出する (= anchor 検出の鏡像)。

    通常の drift 検出は「今の規則が home 外で重複していないか」 を見る。 だが運用が
    転換された (= supersede) とき、 **旧規則を書いた下流 doc は誰にも見られないまま
    生き残る** — 転換は上流 1 箇所に landing し、 手順書は自動では知らないため。
    その生存は「重複」 ではないので anchor 検出には原理的に映らない (実測: 運用の転換後も手順書が
    旧規則を書き続け、 読んだ人がその旧規則を適用した)。

    scan 範囲は topic が **明示宣言した glob だけ** (= 規則が書かれる面。 TODO / inbox /
    plans / SESSION の歴史記録は宣言しなければ触らない)。 window 内に歴史 marker が
    あれば「旧運用の説明」 とみなして flag しない。
    """
    out: list[dict] = []
    for t in topics:
        sup = t.get("superseded") or {}
        tokens = sup.get("tokens") or []
        scan_globs = sup.get("scan_globs") or []
        if not tokens or not scan_globs:
            continue
        home = t.get("home", "")
        allow = t.get("allow_globs", []) or []
        window = 6
        for rel, lines, text in files:
            if rel == home:
                continue
            if not any(fnmatch.fnmatch(rel, g) for g in scan_globs):
                continue
            if not any(tok in text for tok in tokens):
                continue          # 全文に 1 つも無ければ行 loop に入らない
            if any(fnmatch.fnmatch(rel, g) for g in allow):
                continue
            for token in tokens:
                for i, line in enumerate(lines):
                    if token not in line:
                        continue
                    lo = max(0, i - window)
                    hi = min(len(lines), i + window + 1)
                    win = "\n".join(lines[lo:hi])
                    if any(m in win for m in _HISTORICAL_MARKERS):
                        continue
                    out.append(
                        {
                            "topic": t.get("topic", "?"),
                            "rel": rel,
                            "lineno": i + 1,
                            "token": token,
                            "home": home,
                            "home_section": t.get("home_section", ""),
                            "superseded": True,
                            "note": sup.get("note", ""),
                        }
                    )
    return out


def report(findings: list[dict], config_warnings: list[str]) -> None:
    if not findings and not config_warnings:
        return  # silent (= dashboard 慣習)

    print()
    print("=" * 64)
    print("📌 SoT drift (= 運用ルールの authoritative 記述が home 外に pointer なしで重複)")
    print("=" * 64)

    if findings:
        # topic 別に group
        by_topic: dict[str, list[dict]] = {}
        for f in findings:
            by_topic.setdefault(f["topic"], []).append(f)
        for topic, fs in by_topic.items():
            home = fs[0]["home"]
            sec = fs[0]["home_section"]
            print(f"\n🚨 topic `{topic}` ({len(fs)} 件)")
            print(f"   SoT = {home}" + (f" §「{sec}」" if sec else ""))
            live = [f for f in fs if not f.get("superseded")]
            dead = [f for f in fs if f.get("superseded")]
            for f in live:
                print(
                    f"   - {f['rel']}:{f['lineno']}  「{f['token']}」 を pointer なしで記述"
                )
            if live:
                print(
                    "   → まず判定: その行は規約の**複製**か、 規約どおりの**語の使用** (呼称・訳語・定義語) か。\n"
                    "     使用なら**本文は変えない** (= 原文を検出器に合わせて書き換えない) — 直すのは registry 側で、\n"
                    "     anchor を home の「規約を定義する文」 の言い回しへ移す (convention-design-principles.md#literal-anchor-detector)。\n"
                    "     複製なら home 外の記述を削除し pointer 化 するか、 deferral なら "
                    f"`{Path(home).name}` への参照を同 block 内に併記"
                )
            for f in dead:
                print(
                    f"   - ⏳ **旧規則の生存**: {f['rel']}:{f['lineno']}  「{f['token']}」"
                )
            if dead:
                note = dead[0].get("note") or ""
                print(
                    "   → supersede された規則が下流 doc に生きている (= 読んだ人が旧規則を"
                    "適用する)。 現行規則へ書き換えるか、 歴史なら「旧運用」 等と明示する"
                    + (f"\n     note: {note}" if note else "")
                )

    if config_warnings:
        print("\n⚠️  registry config 警告 (= 登録内容が stale の疑い):")
        for w in config_warnings:
            print(f"   - {w}")

    print()
    print(
        "scope: 本検出は registry の登録 topic のみ。 未登録の重複と言い換えた書き写しは見えない "
        "(= convention-design-principles.md#proxy-blind-spot)。"
    )
    print()


def run_selftest() -> int:
    """内蔵 fixture で scan() の検出 / 非検出を検証。"""
    reg = {
        "window_lines": 5,
        "topics": [
            {
                # superseded (= 旧規則の生存) fixture
                "topic": "superseded-rule",
                # home 名は demo-rule (home/rule.md) と重ならない名前にする。 同名 file があると
                # bare な名前は pointer にならない ので、 無関係な fixture 同士が干渉する。
                "home": "docs/current-rule.md",
                "home_section": "",
                "anchor_tokens": ["NEW_RULE_OK"],
                "allow_globs": [],
                "pointer_patterns": ["current-rule.md"],
                "superseded": {
                    "tokens": ["OLD_RULE_FORBIDDEN"],
                    "scan_globs": ["manuals/*"],
                    "note": "旧規則",
                },
            },
            {
                "topic": "demo-rule",
                "description": "テスト用ルール",
                "home": "home/rule.md",
                "home_section": "ルール本体",
                "anchor_tokens": ["ANCHOR_TOKEN_X"],
                "allow_globs": ["arch/*"],
                "pointer_patterns": [],  # default で home filename + section 付与
            },
            {
                # 同名 file が複数 repo にある home (= CLAUDE.md) の pointer 判定。
                # bare な「CLAUDE.md」 は同じ repo の中からだけ pointer、 別 repo からは
                # 「親 dir/CLAUDE.md」 の形でなければ pointer にならない。
                "topic": "generic-name-home",
                "home": "repoA/CLAUDE.md",
                "home_section": "",
                "anchor_tokens": ["GENERIC_HOME_ANCHOR"],
                "allow_globs": [],
                # 明示で bare な home 名を書いても、 同名 file が複数あれば同じ判定になること
                "pointer_patterns": ["CLAUDE.md"],
            },
            {
                # code-as-SoT (= .py home、 SCAN_EXT 対象外) の home sanity check が
                # 「root 配下に不在」 false stale を出さず、 disk 直 read で anchor 検査
                # に fallback する code path の retroactive selftest。
                "topic": "code-home-rule",
                "description": ".py home (= code-as-SoT) の動作確認用",
                "home": "code/rule.py",
                "anchor_tokens": ["CODE_ANCHOR_Y"],
                "allow_globs": [],
                "pointer_patterns": ["rule.py"],
            },
            {
                # degenerate case: home が 0 byte の時に silent skip でなく warn する
                # ことを確認。
                "topic": "empty-home-rule",
                "description": "0 byte home が silent skip でなく warn することの確認",
                "home": "code/empty.py",
                "anchor_tokens": ["EMPTY_ANCHOR_Z"],
                "allow_globs": [],
                "pointer_patterns": ["empty.py"],
            },
        ],
    }
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "home").mkdir()
        (root / "evt").mkdir()
        (root / "arch").mkdir()
        (root / "code").mkdir()
        # home = SoT (anchor を含むのが正常 → flag されないべき)
        (root / "home/rule.md").write_text(
            "## ルール本体\n処理状況 ANCHOR_TOKEN_X では再提出不可。\n", encoding="utf-8"
        )
        # drift = anchor を pointer なしで記述 (→ flag されるべき)
        (root / "evt/drift.yaml").write_text(
            "note: |\n  ANCHOR_TOKEN_X のため作成者再提出不可と書いてしまった\n",
            encoding="utf-8",
        )
        # clean = anchor + 同 window 内に pointer (→ flag されないべき)
        (root / "evt/clean.yaml").write_text(
            "note: |\n  ANCHOR_TOKEN_X の扱いは rule.md 参照\n", encoding="utf-8"
        )
        # event-only = anchor なし (→ flag されないべき)
        (root / "evt/eventonly.yaml").write_text(
            "note: 差し戻し依頼を送信した\n", encoding="utf-8"
        )
        # archive = allow_glob (anchor あっても flag されないべき)
        (root / "arch/old.md").write_text("昔の ANCHOR_TOKEN_X 記述\n", encoding="utf-8")
        # code home (= .py、 SCAN_EXT 対象外) — anchor を含むので home sanity が
        # disk 直 read fallback で OK 判定する (= config 警告無し)。
        (root / "code/rule.py").write_text(
            '"""\n## ルール本体\nCODE_ANCHOR_Y は code 側の正本。\n"""\n', encoding="utf-8"
        )
        # code home の anchor が別 md に pointer 付きで出る (→ flag されないべき)。
        (root / "evt/code-pointer.md").write_text(
            "CODE_ANCHOR_Y の詳細は rule.py 参照\n", encoding="utf-8"
        )
        # code home の anchor が別 yaml に pointer なしで出る (→ flag されるべき)。
        (root / "evt/code-drift.yaml").write_text(
            "note: CODE_ANCHOR_Y を pointer なしで記述\n", encoding="utf-8"
        )
        # empty home (= 0 byte、 silent skip でなく warn が出るべき)。
        (root / "code/empty.py").write_text("", encoding="utf-8")
        # --- superseded (= 旧規則の生存) fixture 3 種 -------------
        (root / "manuals").mkdir()
        (root / "docs").mkdir()
        (root / "docs/current-rule.md").write_text(
            "## 現行\nNEW_RULE_OK が今の運用。\n", encoding="utf-8"
        )
        # (a) 手順書に旧規則が生きている (→ flag されるべき)
        (root / "manuals/live-stale.md").write_text(
            "手続き: OLD_RULE_FORBIDDEN で提出すること。\n", encoding="utf-8"
        )
        # (b) 同じ語だが歴史として書かれている (→ flag されないべき)
        (root / "manuals/historical.md").write_text(
            "旧運用 (移行前) は OLD_RULE_FORBIDDEN だった。 現在は supersede 済。\n",
            encoding="utf-8",
        )
        # (c) scan_globs 外 (= TODO 等の歴史記録) は触らない (→ flag されないべき)
        (root / "evt/old-record.yaml").write_text(
            "note: 当時は OLD_RULE_FORBIDDEN で出した\n", encoding="utf-8"
        )
        # AUTO 生成 block 内の anchor = view であり flag されないべき / block 外は従来通り
        (root / "evt/autogen.md").write_text(
            "<!-- AUTO-TREE:x BEGIN -->\n列挙 ANCHOR_TOKEN_X の生成行\n<!-- AUTO-TREE:x END -->\n",
            encoding="utf-8",
        )
        # whole-file 型 AUTO-GENERATED (BEGIN/END 無し、 例 = generate-tree.py 産物の
        # conventions/README.md) も file ごと view として flag されないべき。
        (root / "evt/autogen-whole.md").write_text(
            "<!-- AUTO-GENERATED by tool -->\n一覧 ANCHOR_TOKEN_X を含む生成行\n",
            encoding="utf-8",
        )
        # prose が AUTO marker を説明で引用しただけの行は block 開始と誤認しない
        # (旧 substring 判定は説明行を block 開始と誤認し、 END 不在で以降を全 blank 化していた。 本 fixture は引用行の後の anchor が
        # 正しく flag される (= blank 化されていない) ことで regex 判定を guard する)。
        (root / "evt/marker-prose.md").write_text(
            "生成物は scan 除外 = `<!-- AUTO-* BEGIN/END -->` block で除外される\n"
            "この行の ANCHOR_TOKEN_X は pointer なしで記述\n",
            encoding="utf-8",
        )

        # --- 同名 file の home -----------------------------------
        for sub in ("repoA", "repoB"):
            (root / sub).mkdir()
        (root / "repoA/CLAUDE.md").write_text("規則 GENERIC_HOME_ANCHOR が正本\n", encoding="utf-8")
        (root / "repoB/CLAUDE.md").write_text("別 repo の入口\n", encoding="utf-8")
        # 別 repo から bare な名前だけ (→ pointer にならず flag されるべき)
        (root / "repoB/copy-bare.md").write_text(
            "GENERIC_HOME_ANCHOR を書き写した (CLAUDE.md に書いてある)\n", encoding="utf-8")
        # 別 repo から「親 dir/名前」 (→ pointer、 flag されないべき)
        (root / "repoB/copy-qualified.md").write_text(
            "GENERIC_HOME_ANCHOR は repoA/CLAUDE.md 参照\n", encoding="utf-8")
        # 同じ repo から bare な名前 (→ pointer、 flag されないべき)
        (root / "repoA/notes.md").write_text(
            "GENERIC_HOME_ANCHOR は CLAUDE.md 参照\n", encoding="utf-8")
        # 別 repo だが窓で repo を名指ししてから bare な名前 (「~/x/repoA/ … its CLAUDE.md」 型、 → pointer)
        (root / "repoB/copy-repo-context.md").write_text(
            "`~/x/repoA/` is the board.\nFollow its `CLAUDE.md` and apply GENERIC_HOME_ANCHOR.\n",
            encoding="utf-8")

        findings, warns = scan(root, reg)
        flagged = {f["rel"] for f in findings}

        ok = True
        checks = [
            ("drift detected", "evt/drift.yaml" in flagged, True),
            ("clean not flagged", "evt/clean.yaml" in flagged, False),
            # 同名 file の home: 別 repo の bare 名は pointer でない / 親 dir 付き・同 repo は pointer
            ("generic home: other repo bare name flagged", "repoB/copy-bare.md" in flagged, True),
            ("generic home: qualified path not flagged", "repoB/copy-qualified.md" in flagged, False),
            ("generic home: same repo bare name not flagged", "repoA/notes.md" in flagged, False),
            ("generic home: repo named in window + bare name not flagged",
             "repoB/copy-repo-context.md" in flagged, False),
            ("home not flagged", "home/rule.md" in flagged, False),
            ("event-only not flagged", "evt/eventonly.yaml" in flagged, False),
            ("archive not flagged", "arch/old.md" in flagged, False),
            ("autogen block not flagged", "evt/autogen.md" in flagged, False),
            ("autogen whole-file not flagged", "evt/autogen-whole.md" in flagged, False),
            ("marker-prose still scanned (flagged)", "evt/marker-prose.md" in flagged, True),
            # code-as-SoT (.py home) 系
            ("code-home drift detected", "evt/code-drift.yaml" in flagged, True),
            ("code-home pointer not flagged", "evt/code-pointer.md" in flagged, False),
            # degenerate home (= 0 byte) → warn 出力。 healthy topic は warn 0 のまま。
            (
                "empty-home warning emitted",
                any("empty-home-rule" in w and "空" in w for w in warns),
                True,
            ),
            (
                "only the empty-home warning",
                len(warns),
                1,
            ),
            # --- superseded (= 旧規則の生存) 3 種 -----------------------------
            ("superseded live rule flagged", "manuals/live-stale.md" in flagged, True),
            (
                "superseded historical prose not flagged",
                "manuals/historical.md" in flagged,
                False,
            ),
            (
                "superseded outside scan_globs not flagged",
                "evt/old-record.yaml" in flagged,
                False,
            ),
        ]
        # --- registry 自体の点検 (audit_registry) -------------------------
        aroot = root / "audit"
        (aroot / "h").mkdir(parents=True)
        (aroot / "h/rule.md").write_text(
            '<a id="tied-id"></a>\n## SWALLOW sec\nSWALLOW sec の説明。 定義文 DEFINING_SENTENCE_OK はここだけ。\n'
            "くり返す語 / くり返す語 / くり返す語\nIDENT_TOKEN_Q IDENT_TOKEN_Q IDENT_TOKEN_Q\n"
            "許可済みの語 許可済みの語 許可済みの語\n", encoding="utf-8")
        for k in range(60):  # 「common」 は 60 file 中 60 に出る = 1% を大きく超える一般語
            (aroot / f"f{k}.md").write_text(f"common word {k}\n", encoding="utf-8")
        areg = {"topics": [{
            "topic": "audited", "home": "h/rule.md", "home_section": "SWALLOW sec",
            "anchor_tokens": ["DEFINING_SENTENCE_OK", "SWALLOW sec の説明", "消えた ANCHOR_GONE",
                              "くり返す語", "IDENT_TOKEN_Q", "許可済みの語"],
            "pointer_patterns": ["common", "tied-id", "audited"],
            "audit_ack": {"許可済みの語": "テスト用に承認"},
        }]}
        aud = {(a["kind"], a["subject"]) for a in audit_registry(aroot, areg)}
        checks += [
            ("audit: definition anchor clean", any(s == "DEFINING_SENTENCE_OK" for _k, s in aud), False),
            ("audit: anchor containing home_section never fires", ("never-fires", "SWALLOW sec の説明") in aud, True),
            ("audit: anchor missing from home", ("missing-in-home", "消えた ANCHOR_GONE") in aud, True),
            ("audit: repeated non-identifier anchor is term-like", ("term-like-anchor", "くり返す語") in aud, True),
            ("audit: repeated identifier-shaped anchor not term-like", ("term-like-anchor", "IDENT_TOKEN_Q") in aud, False),
            ("audit: audit_ack silences", ("term-like-anchor", "許可済みの語") in aud, False),
            ("audit: frequent unanchored pointer is broad", ("broad-pointer", "common") in aud, True),
            ("audit: pointer tied to home anchor id not broad", ("broad-pointer", "tied-id") in aud, False),
            ("audit: pointer equal to topic not broad", ("broad-pointer", "audited") in aud, False),
        ]

        for name, got, want in checks:
            status = "PASS" if got == want else "FAIL"
            if got != want:
                ok = False
            print(f"  [{status}] {name} (got={got}, want={want})")
        if warns:
            print(f"  config_warnings: {warns}")
        print("selftest:", "ALL PASS" if ok else "FAILURE")
        return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="SoT drift 検出")
    ap.add_argument("--root", type=Path, default=Path.cwd(), help="走査する root (既定 = cwd)")
    ap.add_argument("--registry", type=Path, help="registry YAML (必須、 --selftest 以外)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--no-audit", action="store_true",
                    help="registry 自体の点検 (audit_registry) を省く")
    args = ap.parse_args()

    if args.selftest:
        return run_selftest()
    if not args.registry:
        ap.error("--registry が必要")

    if not args.registry.exists():
        return 0  # registry 無ければ silent (= dashboard 連鎖を止めない)
    try:
        registry = yaml.safe_load(args.registry.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        print(f"[check-sot-drift] registry parse error: {e}", file=sys.stderr)
        return 0
    if not args.root.exists():
        return 0

    files = load_files(args.root, args.registry)
    findings, config_warnings = scan(args.root, registry, registry_path=args.registry, files=files)
    report(findings, config_warnings)
    if not args.no_audit:
        report_audit(audit_registry(args.root, registry, args.registry, files=files))
    return 0  # 報告のみ (= dashboard 連鎖を止めない)


AUDIT_ADVICE = {
    "never-fires": "anchor を home の別の言い回しへ移す (pointer 判定の語を含まない文)",
    "missing-in-home": "home の現行の文に合わせて anchor を直すか、 消えた anchor を外す",
    "broad-pointer": "pointer を home に結び付く形 (file 名・anchor id・topic) に絞る。 外すと隠れていた書き写しが出るので、 出たものは複製か使用かを判定する",
    "term-like-anchor": "語そのものなら anchor を定義文へ移す。 識別子・値・引用として正当なら topic の audit_ack に理由つきで載せる",
}


def report_audit(items: list[dict]) -> None:
    if not items:
        return
    print("\n" + "=" * 64)
    print("📌 sot-registry の点検 (= 目印が鳴るか / 語に見えるか / pointer が広すぎないか)")
    print("=" * 64)
    by_kind: dict[str, list[dict]] = {}
    for it in items:
        by_kind.setdefault(it["kind"], []).append(it)
    for kind in ("never-fires", "missing-in-home", "broad-pointer", "term-like-anchor"):
        its = by_kind.get(kind) or []
        if not its:
            continue
        print(f"\n{its[0]['level']} {kind} ({len(its)} 件) → {AUDIT_ADVICE[kind]}")
        for it in its:
            print(f"   - {it['topic']}: 「{it['subject']}」 {it['detail']}")
    print("\n   判定の基準 = claude-config/docs/convention-design-principles.md#literal-anchor-detector")


if __name__ == "__main__":
    sys.exit(main())
