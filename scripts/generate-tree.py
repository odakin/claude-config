#!/usr/bin/env python3
"""generate-tree.py — CLAUDE.md 構造 tree (conventions/hooks/scripts) + CONVENTIONS.md 冒頭列挙 +
conventions/README.md (カテゴリ index) を単一 source から自動生成 (= 三重手動同期の design-out)。

源 (single source of truth):
  * conventions/*.md   … 各 file 冒頭の doc-meta HTML comment frontmatter:
                             <!-- doc-meta
                             when: <いつ読むか 1 行>
                             category: <harness-core|office|mail|paper|macos|research-domain|web|infra>
                             summary: <1 行説明 (長くて良い)>
                             -->
                         `X.ja.md` で `X.md` が実在するものは翻訳 variant (doc-meta 不要、親 entry に併記)。
                         README.md (= 本 script の生成物) は対象外。
  * hooks/ scripts/ scripts/lib/ … 各 file header の説明 1 行目
                         (.py = module docstring 1 行目 / .sh 等 = shebang 直後の最初の # comment /
                          .mjs .js 等 = shebang 直後の最初の // comment /
                          .html = 先頭 3 行内の <!-- --> comment。 いずれも先頭の "<basename> — " prefix は strip)。

生成先 (3 箇所、 いずれも marker で機械管理 — 手編集禁止):
  1. CLAUDE.md          … <!-- AUTO-TREE:<name> BEGIN --> 〜 <!-- AUTO-TREE:<name> END -->
                          (name = conventions / hooks / scripts、 構造 tree の code fence 内)
  2. CONVENTIONS.md     … <!-- AUTO-ENUM BEGIN --> 〜 <!-- AUTO-ENUM END --> (冒頭の全列挙 blockquote)
  3. conventions/README.md … file 全体を生成 (カテゴリ別 index)

新規 file を足すとき: conventions/*.md なら doc-meta を書く / scripts・hooks なら header 1 行目に説明を
書く → `git add` → `--write` で 3 箇所へ同時反映。 忘れても `--check` (CI = run-all-checks.sh /
pre-commit = .claude/pre-commit-extra.sh) が drift を検出する。
⚠️ 源は **git-tracked (cached/staged) file のみ** (git 不在時は disk fallback): untracked file
(= 並列 session の未 commit 作業・一時 file) を tree に載せると、 committed checkout で --check を
回す CI と結果が割れるため。 新 file が tree に出ないときはまず `git add`。

Usage:
  generate-tree.py --write      # 3 生成物を再生成 (in place)
  generate-tree.py --check      # 再生成せず比較、 drift があれば exit 1 (源の validation error は exit 2)
  generate-tree.py --selftest   # hermetic fixture (tempdir) による回帰テスト

public-safe / stdlib only / macOS・Linux 両対応 (CI から呼ばれる)。
"""
import ast
import difflib
import re
import sys
from pathlib import Path

CATEGORIES = [
    ("harness-core", "Claude Code / harness 運用"),
    ("office", "Office 様式・事務書類"),
    ("mail", "メール"),
    ("paper", "論文・発表・研究文書"),
    ("macos", "macOS"),
    ("research-domain", "研究ドメイン"),
    ("web", "Web・公開プラットフォーム"),
    ("infra", "エンジニアリング一般"),
]
VALID_CATS = {c for c, _ in CATEGORIES}

DOC_META_OPEN = "<!-- doc-meta"
SEP_RE = r"(?:—|–|--|-)"
ALIGN_CAP = 36  # tree 内の name 列揃え幅の上限 (これより長い name は 1 space 区切り)


def _force_utf8_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


# ---------------------------------------------------------------- sources

def strip_name_prefix(desc: str, name: str) -> str:
    """'<basename> — <desc>' / '<stem> -- <desc>' 形式の先頭 prefix を strip。"""
    stem = name.rsplit(".", 1)[0]
    for cand in (name, stem):
        m = re.match(rf"^{re.escape(cand)}\s*{SEP_RE}\s*", desc)
        if m:
            return desc[m.end():]
    return desc


def parse_doc_meta(path: Path):
    """conventions/*.md 冒頭の doc-meta を dict で返す。 無ければ None。"""
    text = path.read_text(encoding="utf-8")
    if not text.startswith(DOC_META_OPEN):
        return None
    end = text.find("-->")
    if end < 0:
        return None
    meta = {}
    for line in text[len(DOC_META_OPEN):end].splitlines():
        m = re.match(r"^(when|category|summary):\s*(.+)$", line.strip())
        if m:
            meta[m.group(1)] = m.group(2).strip()
    return meta


def extract_header_desc(path: Path):
    """scripts/hooks file の説明 1 行目を返す (無ければ None)。"""
    name = path.name
    text = path.read_text(encoding="utf-8", errors="replace")
    if name.endswith(".py"):
        try:
            doc = ast.get_docstring(ast.parse(text))
        except SyntaxError:
            doc = None
        if doc:
            return strip_name_prefix(doc.splitlines()[0].strip(), name)
    if name.endswith(".html"):
        m = re.search(r"<!--\s*(.*?)\s*-->", "\n".join(text.splitlines()[:3]))
        return strip_name_prefix(m.group(1), name) if m else None
    for i, line in enumerate(text.splitlines()):
        if i == 0 and line.startswith("#!"):
            continue
        s = line.strip()
        if not s:
            continue
        if s.startswith("#") or s.startswith("//"):
            # .sh 等 = "# …" / .mjs .js 等 = "// …" (2026-08-29 追加)
            return strip_name_prefix(s.lstrip("#/").strip(), name) or None
        break
    return None


def is_variant(name: str, conv_dir: Path) -> bool:
    return name.endswith(".ja.md") and (conv_dir / (name[: -len(".ja.md")] + ".md")).exists()


def tracked_files(root: Path):
    """git-tracked (cached / staged) file の絶対 path set。 git 不在 / 非 repo なら None (= disk fallback)。

    源を tracked に限る理由: (1) CI は committed checkout で --check を回すため、 disk 上の
    untracked file (= 並列 session の未 commit 作業・一時 file) を tree に載せると commit と
    CI で結果が割れる (2) 新 file は `git add` した瞬間に源へ入る = commit 単位で自己整合。"""
    import subprocess
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "-z"], stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    return {(root / p).resolve() for p in out.decode("utf-8", "replace").split("\0") if p}


def _listed(path: Path, tracked) -> bool:
    return path.exists() and (tracked is None or path.resolve() in tracked)


def collect_conventions(root: Path, errors: list, tracked=None):
    """[(name, meta_or_None_for_variant)] を親→variant 隣接の名前順で返す。"""
    conv = root / "conventions"
    entries = []
    for p in sorted(conv.glob("*.md")):
        if p.name == "README.md" or not _listed(p, tracked):
            continue
        if is_variant(p.name, conv):
            entries.append((p.name, None))
            continue
        meta = parse_doc_meta(p)
        if meta is None:
            errors.append(f"conventions/{p.name}: doc-meta frontmatter が無い (file 冒頭に <!-- doc-meta … --> を書く)")
            continue
        for key in ("when", "category", "summary"):
            if not meta.get(key):
                errors.append(f"conventions/{p.name}: doc-meta に {key}: が無い")
        if meta.get("category") and meta["category"] not in VALID_CATS:
            errors.append(f"conventions/{p.name}: category '{meta['category']}' は不正 (有効: {sorted(VALID_CATS)})")
        entries.append((p.name, meta))
    # 並び: variant は親の直後 (素の sort だと 'x.ja.md' < 'x.md' で variant が先に来るため)
    def sort_key(e):
        name = e[0]
        if e[1] is None and name.endswith(".ja.md"):
            return (name[: -len(".ja.md")] + ".md", 1)
        return (name, 0)
    entries.sort(key=sort_key)
    return entries


def collect_dir_files(root: Path, rel: str, errors: list, allow_dirs=(), tracked=None):
    """hooks/ scripts/ 等の [(name, desc)] (名前順) + 未知 subdir の検出。

    tracked が与えられた (= git repo) 場合は tracked file のみを源にし、 subdir 検出も
    tracked path から行う (= untracked な一時 dir / 並列 session 作業で error にしない)。"""
    d = root / rel
    files = []
    seen_dirs = set()
    for p in sorted(d.iterdir()):
        if p.name.startswith(".") or p.name == "__pycache__" or p.name.endswith(".pyc"):
            continue
        if p.is_dir():
            if tracked is None:
                seen_dirs.add(p.name)
            continue
        if not _listed(p, tracked):
            continue
        desc = extract_header_desc(p)
        if not desc:
            errors.append(f"{rel}/{p.name}: header に説明 1 行目が無い (docstring / # comment / <!-- --> を冒頭に書く)")
            desc = ""
        files.append((p.name, desc))
    if tracked is not None:
        prefix = (root / rel).resolve()
        for t in tracked:
            try:
                sub = t.relative_to(prefix)
            except ValueError:
                continue
            if len(sub.parts) > 1:
                seen_dirs.add(sub.parts[0])
    for name in sorted(seen_dirs):
        if name in ("__pycache__",) or name.startswith("."):
            continue
        if name not in allow_dirs:
            errors.append(f"{rel}/{name}/: 未知の subdirectory (generate-tree.py の allow_dirs へ追加要否を判断)")
    return files, sorted(n for n in seen_dirs if n in allow_dirs)


# ---------------------------------------------------------------- renderers

def _tree_lines(entries, child_prefix="│   ", last_closes=True):
    lines = []
    width = min(max((len(n) for n, _ in entries), default=0), ALIGN_CAP)
    for i, (name, desc) in enumerate(entries):
        branch = "└──" if (last_closes and i == len(entries) - 1) else "├──"
        pad = " " * max(width - len(name), 1)
        lines.append(f"{child_prefix}{branch} {name}{pad}# {desc}")
    return lines


def render_tree_conventions(entries):
    items = []
    for name, meta in entries:
        if meta is None:
            parent = name[: -len(".ja.md")] + ".md"
            items.append((name, f"{parent} の日本語版"))
        else:
            items.append((name, meta["summary"]))
    lines = ["├── conventions/          # ドメイン固有規約 (カテゴリ index = conventions/README.md、説明の源 = 各 file 冒頭の doc-meta)"]
    lines += _tree_lines(items)
    return lines


def render_tree_hooks(files):
    lines = ["├── hooks/                # Claude Code hooks (setup.sh が ~/.claude/hooks/ に symlink、説明の源 = 各 file header 1 行目)"]
    lines += _tree_lines(files)
    return lines


def render_tree_scripts(files, lib_files):
    lines = ["├── scripts/              # 運用 script 群 (説明の源 = 各 file header 1 行目)"]
    lines += _tree_lines(files, last_closes=False)
    lines.append("│   └── lib/                            # sourceable helper 群")
    lines += _tree_lines(lib_files, child_prefix="│       ")
    return lines


def render_enum(entries):
    links = []
    i = 0
    while i < len(entries):
        name, meta = entries[i]
        if meta is None:
            i += 1  # 孤立 variant (親 link に併記済みのはずだが防御)
            continue
        link = f"[{name}](conventions/{name})"
        if i + 1 < len(entries) and entries[i + 1][1] is None:
            va = entries[i + 1][0]
            link += f" (+ [ja](conventions/{va}))"
            i += 1
        links.append(link)
        i += 1
    return (
        "> ドメイン固有規約は `conventions/` に分離 (**全列挙** = `conventions/*.md` の全 file・名前順、 "
        "カテゴリ別 index = [conventions/README.md](conventions/README.md)。 本列挙・CLAUDE.md 構造 tree・README は "
        "`scripts/generate-tree.py` が各 file 冒頭の doc-meta frontmatter から自動生成 — 新規 file は doc-meta を書いて "
        "`--write` を回せば 3 箇所へ同時反映、 drift は CI / pre-commit の `--check` が検出。 "
        "`.ja.md` 翻訳 variant は親 entry に併記): " + ", ".join(links)
    )


def render_readme(entries):
    by_cat = {c: [] for c in VALID_CATS}
    variants = {}
    for i, (name, meta) in enumerate(entries):
        if meta is None:
            parent = name[: -len(".ja.md")] + ".md"
            variants[parent] = name
        else:
            by_cat[meta["category"]].append((name, meta))
    n_docs = sum(len(v) for v in by_cat.values())
    lines = [
        "<!-- AUTO-GENERATED by scripts/generate-tree.py — 手編集禁止。",
        "     源 = 各 conventions/*.md 冒頭の doc-meta frontmatter (when / category / summary)。",
        "     再生成: python3 scripts/generate-tree.py --write / 同期検査: --check -->",
        "",
        "# conventions/ — カテゴリ別 index",
        "",
        f"layer 1 (public) のドメイン固有規約 {n_docs} file をカテゴリ別に列挙する。"
        "全 file の名前順 1 行列挙は [CONVENTIONS.md](../CONVENTIONS.md) 冒頭、"
        "リポ全体の構造 tree は [CLAUDE.md](../CLAUDE.md) を参照。",
        "",
    ]
    for cat, title in CATEGORIES:
        docs = by_cat[cat]
        if not docs:
            continue
        lines.append(f"## {title} (`{cat}`)")
        lines.append("")
        for name, meta in docs:
            head = f"- **[{name}]({name})** — {meta['when']}"
            if name in variants:
                head += f" (+ 日本語版: [{variants[name]}]({variants[name]}))"
            lines.append(head)
            lines.append(f"  - {meta['summary']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------- splicing

def splice(text: str, begin_tag: str, end_tag: str, new_body_lines, label: str, errors: list):
    """text 内の begin/end marker 行の間を new_body_lines に置換。 marker 不在は error。"""
    lines = text.splitlines()
    b = e = None
    for i, l in enumerate(lines):
        s = l.strip()
        if s.startswith("> "):  # blockquote 内 marker (CONVENTIONS.md の列挙は blockquote 中にある)
            s = s[2:]
        if s.startswith(begin_tag):
            b = i
        elif s.startswith(end_tag):
            e = i
            break
    if b is None or e is None or e <= b:
        errors.append(f"{label}: marker {begin_tag} … {end_tag} が見つからない")
        return text
    return "\n".join(lines[: b + 1] + list(new_body_lines) + lines[e:]) + ("\n" if text.endswith("\n") else "")


def build_outputs(root: Path):
    """{path: new_text} と validation errors を返す。"""
    errors = []
    tracked = tracked_files(root)
    conv_entries = collect_conventions(root, errors, tracked=tracked)
    hooks, _ = collect_dir_files(root, "hooks", errors, tracked=tracked)
    scripts, _ = collect_dir_files(root, "scripts", errors, allow_dirs=("lib",), tracked=tracked)
    lib, _ = collect_dir_files(root, "scripts/lib", errors, tracked=tracked)
    if errors:
        return {}, errors  # 源が不正なら render しない (不正 category 等で render が壊れるため)

    outputs = {}
    claude_md = root / "CLAUDE.md"
    text = claude_md.read_text(encoding="utf-8")
    text = splice(text, "<!-- AUTO-TREE:conventions BEGIN", "<!-- AUTO-TREE:conventions END",
                  render_tree_conventions(conv_entries), "CLAUDE.md", errors)
    text = splice(text, "<!-- AUTO-TREE:hooks BEGIN", "<!-- AUTO-TREE:hooks END",
                  render_tree_hooks(hooks), "CLAUDE.md", errors)
    text = splice(text, "<!-- AUTO-TREE:scripts BEGIN", "<!-- AUTO-TREE:scripts END",
                  render_tree_scripts(scripts, lib), "CLAUDE.md", errors)
    outputs[claude_md] = text

    conv_md = root / "CONVENTIONS.md"
    text = splice(conv_md.read_text(encoding="utf-8"), "<!-- AUTO-ENUM BEGIN", "<!-- AUTO-ENUM END",
                  [render_enum(conv_entries)], "CONVENTIONS.md", errors)
    outputs[conv_md] = text

    outputs[root / "conventions" / "README.md"] = render_readme(conv_entries)
    return outputs, errors


# ---------------------------------------------------------------- modes

def run(root: Path, check: bool) -> int:
    outputs, errors = build_outputs(root)
    if errors:
        print("❌ generate-tree.py: 源の validation error:")
        for e in errors:
            print(f"   - {e}")
        return 2
    drift = 0
    for path, new_text in outputs.items():
        rel = path.relative_to(root)
        old_text = path.read_text(encoding="utf-8") if path.exists() else ""
        if old_text == new_text:
            print(f"✅ {rel}: in sync")
            continue
        if check:
            drift += 1
            print(f"❌ {rel}: OUT OF SYNC (→ python3 scripts/generate-tree.py --write)")
            diff = list(difflib.unified_diff(old_text.splitlines(), new_text.splitlines(),
                                             str(rel), str(rel) + " (generated)", lineterm="", n=0))
            for l in diff[2:12]:
                print(f"     {l[:160]}")
            if len(diff) > 12:
                print(f"     … (+{len(diff) - 12} lines)")
        else:
            # newline="\n" 必須: 既定 (newline=None) は "\n" を os.linesep へ変換するため、
            # Windows で --write すると生成 3 file が丸ごと CRLF 化して全行 diff になる
            # (= 実測 850 行の phantom diff)。 open() 経由なのは Path.write_text の
            # newline 引数が 3.10+ のため。
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(new_text)
            print(f"📝 {rel}: regenerated")
    return 1 if (check and drift) else 0


def selftest() -> int:
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="gentree-selftest-"))
    ok = True

    def check(cond, label):
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + label)
        ok = ok and cond

    try:
        (tmp / "conventions").mkdir()
        (tmp / "hooks").mkdir()
        (tmp / "scripts" / "lib").mkdir(parents=True)
        (tmp / "conventions" / "alpha.md").write_text(
            "<!-- doc-meta\nwhen: alpha を使うとき\ncategory: infra\nsummary: alpha の規約\n-->\n# alpha\n", encoding="utf-8")
        (tmp / "conventions" / "beta.md").write_text(
            "<!-- doc-meta\nwhen: beta を書くとき\ncategory: paper\nsummary: beta の規約 (詳しめの説明)\n-->\n# beta\n", encoding="utf-8")
        (tmp / "conventions" / "beta.ja.md").write_text("# beta 日本語版\n", encoding="utf-8")
        (tmp / "hooks" / "h.sh").write_text("#!/bin/bash\n# h.sh — hook のテスト説明\n", encoding="utf-8")
        (tmp / "scripts" / "s.py").write_text('#!/usr/bin/env python3\n"""s.py — script のテスト説明"""\n', encoding="utf-8")
        (tmp / "scripts" / "lib" / "l.sh").write_text("#!/bin/bash\n# lib helper 説明\n", encoding="utf-8")
        (tmp / "CLAUDE.md").write_text("\n".join([
            "# fixture", "```",
            "<!-- AUTO-TREE:conventions BEGIN -->", "<!-- AUTO-TREE:conventions END -->",
            "<!-- AUTO-TREE:hooks BEGIN -->", "<!-- AUTO-TREE:hooks END -->",
            "├── hammerspoon/   # manual block",
            "<!-- AUTO-TREE:scripts BEGIN -->", "<!-- AUTO-TREE:scripts END -->",
            "```", "",
        ]), encoding="utf-8")
        (tmp / "CONVENTIONS.md").write_text("\n".join([
            "# 規約", "<!-- AUTO-ENUM BEGIN -->", "<!-- AUTO-ENUM END -->", "本文", "",
        ]), encoding="utf-8")

        # 1) write → 内容検証
        rc = run(tmp, check=False)
        check(rc == 0, "write が exit 0")
        claude = (tmp / "CLAUDE.md").read_text(encoding="utf-8")
        check("alpha.md" in claude and "# alpha の規約" in claude, "tree に conventions summary")
        check("beta.ja.md" in claude and "beta.md の日本語版" in claude, "tree に variant 行 (親の直後)")
        check(claude.index("beta.md ") < claude.index("beta.ja.md"), "variant が親の後")
        check("hook のテスト説明" in claude, "tree に hook desc (prefix strip 済)")
        check("script のテスト説明" in claude and "lib helper 説明" in claude, "tree に scripts + lib desc")
        check("hammerspoon/   # manual block" in claude, "手動 block は不変")
        enum = (tmp / "CONVENTIONS.md").read_text(encoding="utf-8")
        check("[beta.md](conventions/beta.md) (+ [ja](conventions/beta.ja.md))" in enum, "enum の variant 併記")
        readme = (tmp / "conventions" / "README.md").read_text(encoding="utf-8")
        check("AUTO-GENERATED" in readme and "alpha を使うとき" in readme, "README に when")
        check("エンジニアリング一般" in readme and "論文・発表・研究文書" in readme, "README にカテゴリ見出し")

        # 2) idempotent: 直後の check が clean
        check(run(tmp, check=True) == 0, "write 直後の --check が exit 0 (idempotent)")

        # 3) drift 検出
        (tmp / "CLAUDE.md").write_text(claude.replace("# alpha の規約", "# 手で書き換えた"), encoding="utf-8")
        check(run(tmp, check=True) == 1, "手編集 drift を --check が exit 1")
        run(tmp, check=False)

        # 4) 新規 conventions file の doc-meta 欠落 → exit 2
        (tmp / "conventions" / "gamma.md").write_text("# gamma (frontmatter なし)\n", encoding="utf-8")
        check(run(tmp, check=True) == 2, "doc-meta 欠落を --check が exit 2")
        (tmp / "conventions" / "gamma.md").write_text(
            "<!-- doc-meta\nwhen: x\ncategory: 不正カテゴリ\nsummary: y\n-->\n# gamma\n", encoding="utf-8")
        check(run(tmp, check=True) == 2, "不正 category を --check が exit 2")
        (tmp / "conventions" / "gamma.md").unlink()

        # 5) 新規 script の header 説明欠落 → exit 2 / 追加 → drift 検出
        (tmp / "scripts" / "naked.sh").write_text("#!/bin/bash\necho hi\n", encoding="utf-8")
        check(run(tmp, check=True) == 2, "header 説明の無い script を --check が exit 2")
        (tmp / "scripts" / "naked.sh").write_text("#!/bin/bash\n# naked.sh — 新 script\necho hi\n", encoding="utf-8")
        check(run(tmp, check=True) == 1, "新 script 追加 (tree 未反映) を --check が exit 1")
        run(tmp, check=False)
        check(run(tmp, check=True) == 0, "--write 後は clean")

        # 5b) .mjs の // header 説明も抽出される (2026-08-29)
        (tmp / "scripts" / "m.mjs").write_text(
            "#!/usr/bin/env node\n// m.mjs — mjs header 説明\n", encoding="utf-8")
        check(run(tmp, check=True) == 1, ".mjs (// header) は説明欠落 exit 2 でなく drift exit 1")
        run(tmp, check=False)
        check(run(tmp, check=True) == 0, ".mjs 反映後は clean")
        check("mjs header 説明" in (tmp / "CLAUDE.md").read_text(encoding="utf-8"),
              ".mjs の // 説明が tree に載る")

        # 6) 未知 subdir → exit 2
        (tmp / "scripts" / "mystery").mkdir()
        check(run(tmp, check=True) == 2, "scripts/ 未知 subdir を --check が exit 2")
        (tmp / "scripts" / "mystery").rmdir()

        # 7) git repo では tracked file のみが源 (untracked = 並列 session 作業を拾わない)
        import subprocess
        git_ok = True
        try:
            env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                   "GIT_COMMITTER_EMAIL": "t@t", "HOME": str(tmp), "PATH": __import__("os").environ["PATH"]}
            for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                        ["git", "commit", "-qm", "fixture"]):
                subprocess.run(cmd, cwd=tmp, check=True, env=env, capture_output=True)
        except Exception:
            git_ok = False
        if git_ok:
            (tmp / "scripts" / "untracked.sh").write_text("#!/bin/bash\necho no header\n", encoding="utf-8")
            (tmp / "scripts" / "junk-dir").mkdir()
            check(run(tmp, check=True) == 0, "untracked file / dir は源に入らない (--check clean のまま)")
            subprocess.run(["git", "add", "scripts/untracked.sh"], cwd=tmp, check=True, env=env, capture_output=True)
            check(run(tmp, check=True) == 2, "git add した瞬間に源へ入る (header 説明無し → exit 2)")
        else:
            print("  (skip: git が使えない環境のため tracked-source check を省略)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("selftest:", "ALL PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    _force_utf8_stdio()
    args = sys.argv[1:]
    root = Path(__file__).resolve().parent.parent
    if args == ["--write"]:
        sys.exit(run(root, check=False))
    if args == ["--check"]:
        sys.exit(run(root, check=True))
    if args == ["--selftest"]:
        sys.exit(selftest())
    print(__doc__.split("Usage:")[1] if "Usage:" in (__doc__ or "") else "usage: --write | --check | --selftest")
    sys.exit(64)


if __name__ == "__main__":
    main()
