#!/usr/bin/env python3
"""macos-arch-audit.py — この Mac の CPU (Intel / Apple Silicon) を自動判定し、 ネイティブで動かないものを列挙する (読むだけ)。

正本 = conventions/macos-cpu-arch.md (判定の仕方・Homebrew の置き場所・PATH の並び・移行で壊れるものと直し方)。
本 script はその点検の機械化で、 Intel 機でも Apple Silicon 機でも同じに動く:
  - ハードウェアの arch を判定する (Rosetta 下の x86 shell から呼ばれても hw.optional.arm64 で本物を見る)
  - 「ネイティブ」 = その arch の slice を持つ binary。 Apple Silicon 機では x86_64 だけの binary、
    Intel 機では arm64 だけの binary が「異物」。 i386 / ppc だけの binary はどちらの機でも動かない
  - 異物は Rosetta が無ければ起動せず (Bad CPU type / EBADARCH / launchd exit 126)、
    Rosetta があれば黙って遅く動く (= 混在すると arm64 で入れ直した部品と噛み合わず import 等で落ちる)

PATH の外も見る: いま Rosetta で動いている process (常駐の自動更新係など)、 PATH に無い Framework 版の Python、
Intel 版の Python を base にした venv。 どれも普段の command では起動しないが、 版や名前だけで interpreter を探す道具や
常駐の更新係が Rosetta で起動し、 Apple Silicon では「Intel プロセッサ用アプリの対応は終了します」 の通知が出る (実測)。

使い方:
  python3 macos-arch-audit.py                       # 全項目
  python3 macos-arch-audit.py --repos-root ~/src    # その下の git repo の git-crypt filter path と venv も見る
  python3 macos-arch-audit.py --no-apps             # アプリの走査 (/Applications と Application Support の自動更新係) を省く (速い)
  python3 macos-arch-audit.py --fix-git-crypt-paths --repos-root ~/src
                                                    # git-crypt filter の絶対 path を今の git-crypt に書き換える
  python3 macos-arch-audit.py --selftest

終了値: 0 = 🔴 なし / 1 = 🔴 あり (ネイティブで動かないものが実行経路にある) / 2 = 使い方の誤り。
--fix-git-crypt-paths 以外は何も書き換えない。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
PREFIX = {"arm64": "/opt/homebrew", "x86_64": "/usr/local"}
COMMANDS = ["python3", "git", "node", "npm", "npx", "claude", "gh", "jq",
            "git-crypt", "git-lfs", "bash", "brew", "gs", "pdftoppm"]


# ---------------------------------------------------------------- 判定の部品
def sysctl(name: str) -> str:
    try:
        return subprocess.run(["sysctl", "-n", name], capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def hardware_arch() -> str:
    """ハードウェアの arch。 Rosetta 下の process でも hw.optional.arm64 は 1 を返す。"""
    return "arm64" if sysctl("hw.optional.arm64") == "1" else "x86_64"


def process_translated() -> bool:
    return sysctl("sysctl.proc_translated") == "1"


def rosetta_installed() -> bool:
    return Path("/Library/Apple/usr/libexec/oah/libRosettaRuntime").exists()


def archs_of(path: str) -> list[str] | None:
    """Mach-O の arch 一覧。 script・存在しない file は None。 arm64e は arm64 として数える。"""
    try:
        out = subprocess.run(["lipo", "-archs", path], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    return sorted({"arm64" if a == "arm64e" else a for a in out.stdout.split()})


def verdict(archs: list[str] | None, native: str) -> str:
    """'native' / 'foreign' (Rosetta で動く) / 'dead' (どの現行 Mac でも動かない) / 'script'。"""
    if archs is None:
        return "script"
    if native in archs:
        return "native"
    if "x86_64" in archs or "arm64" in archs:
        return "foreign"
    return "dead"


MARK = {"native": "✅", "foreign": "🔴", "dead": "⛔", "script": "·"}


# ---------------------------------------------------------------- 各項目
def check_commands(native: str, findings: list) -> list[str]:
    lines = []
    for cmd in COMMANDS:
        p = shutil.which(cmd)
        if not p:
            lines.append(f"  ·  {cmd:10} (PATH に無い)")
            continue
        real = os.path.realpath(p)
        v = verdict(archs_of(real), native)
        lines.append(f"  {MARK[v]} {cmd:10} {p}" + ("" if real == p else f" → {real}"))
        if v in ("foreign", "dead"):
            findings.append(f"PATH の {cmd} が {v}: {real}")
    return lines


def check_path_order(native: str, findings: list) -> list[str]:
    entries = os.environ.get("PATH", "").split(":")
    nat, oth = PREFIX[native] + "/bin", PREFIX["x86_64" if native == "arm64" else "arm64"] + "/bin"
    lines = []
    if nat in entries and oth in entries and entries.index(oth) < entries.index(nat):
        msg = f"PATH で {oth} が {nat} より前 (= 別 arch の Homebrew が先に選ばれる)"
        findings.append(msg)
        lines.append("  🔴 " + msg)
    else:
        lines.append(f"  ✅ PATH の Homebrew の並び ({nat} が先、 または片方だけ)")
    return lines


def check_homebrew(native: str, findings: list) -> list[str]:
    lines = []
    for arch, pre in PREFIX.items():
        brew = Path(pre) / "bin" / "brew"
        repo = Path(pre) / ("Homebrew" if arch == "x86_64" else ".")
        cellar = Path(pre) / "Cellar"
        if not brew.exists() and not cellar.exists():
            continue
        n = len(list(cellar.iterdir())) if cellar.is_dir() else 0
        tag = "ネイティブ" if arch == native else "別 arch"
        mark = "✅" if arch == native else "🟠"
        lines.append(f"  {mark} {pre} ({tag}、 formula {n} 個、 brew {'あり' if brew.exists() else 'なし'})")
        if arch != native and brew.exists():
            findings.append(f"別 arch の Homebrew が {pre} に残っている (brew {brew})")
    if not lines:
        lines.append("  ·  Homebrew なし")
    if not (Path(PREFIX[native]) / "bin" / "brew").exists():
        lines.append(f"  🟠 ネイティブの Homebrew ({PREFIX[native]}) が無い")
    return lines


def check_dirs(native: str, findings: list) -> list[str]:
    lines = []
    groups = {
        "~/.local/bin": sorted(glob.glob(str(HOME / ".local/bin/*"))),
        "nvm の node": sorted(glob.glob(str(HOME / ".nvm/versions/node/*/bin/node"))),
        "pyenv の python": sorted(glob.glob(str(HOME / ".pyenv/versions/*/bin/python3"))),
    }
    for label, paths in groups.items():
        bad = []
        for p in paths:
            v = verdict(archs_of(os.path.realpath(p)), native)
            if v in ("foreign", "dead"):
                bad.append(p)
        if not paths:
            continue
        if bad:
            findings.append(f"{label}: 別 arch {len(bad)} 件")
            lines.append(f"  🔴 {label}: {len(paths)} 件中 {len(bad)} 件が別 arch")
            lines += [f"       {b}" for b in bad[:8]]
        else:
            lines.append(f"  ✅ {label}: {len(paths)} 件すべてネイティブ")
    return lines


def check_python_user_site(native: str, findings: list) -> list[str]:
    py = shutil.which("python3")
    if not py:
        return ["  ·  python3 なし"]
    try:
        site = subprocess.run([py, "-c", "import site;print(site.getusersitepackages())"],
                              capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ["  ·  python3 を起動できない"]
    if not site or not Path(site).is_dir():
        return [f"  ·  user site なし ({site or '?'})"]
    sos = glob.glob(os.path.join(site, "**", "*.so"), recursive=True)
    bad = [s for s in sos if verdict(archs_of(s), native) in ("foreign", "dead")]
    if bad:
        pkgs = sorted({Path(b).relative_to(site).parts[0] for b in bad})
        findings.append(f"python user site の拡張 {len(bad)} 個が別 arch")
        return [f"  🔴 {site}: 拡張 {len(sos)} 個中 {len(bad)} 個が別 arch "
                f"(package: {', '.join(pkgs[:12])}{' …' if len(pkgs) > 12 else ''})",
                "       直し方 = pip freeze --user → pip install --user --force-reinstall --no-deps -r"]
    return [f"  ✅ {site}: 拡張 {len(sos)} 個すべてネイティブ"]


def check_npx_cache(native: str, findings: list) -> list[str]:
    other = "darwin-x64" if native == "arm64" else "darwin-arm64"
    hits = sorted(glob.glob(str(HOME / ".npm" / "_npx") + "/*/node_modules/**/*" + other + "*", recursive=True))
    dirs = sorted({str(Path(h).relative_to(HOME / ".npm/_npx")).split("/")[0] for h in hits})
    if dirs:
        findings.append(f"npx cache の {len(dirs)} 個が別 arch の部品 (*{other}*) を抱えている")
        return [f"  🟠 npx cache: {len(dirs)} 個 ({', '.join(dirs)}) — その dir を消せば次回 ネイティブで取り直す"]
    return ["  ✅ npx cache: 別 arch の platform 部品なし"]


def git_crypt_configs(root: Path) -> list[Path]:
    out = []
    for cfg in glob.glob(str(root / "*" / ".git" / "config")) + glob.glob(str(root / "*" / "*" / ".git" / "config")):
        try:
            if "git-crypt" in Path(cfg).read_text(errors="replace"):
                out.append(Path(cfg))
        except OSError:
            pass
    return out


GC_RE = re.compile(r'^(\s*(?:smudge|clean|textconv)\s*=\s*)"?([^"\s]*git-crypt)"?(\s.*)$', re.M)


def check_git_crypt(root: Path | None, native: str, findings: list, fix: bool) -> list[str]:
    if root is None:
        return ["  ·  --repos-root 未指定 (git-crypt filter の path は見ていない)"]
    target = shutil.which("git-crypt")
    stale = []
    cfgs = git_crypt_configs(root)
    for cfg in cfgs:
        text = cfg.read_text(errors="replace")
        paths = {m.group(2) for m in GC_RE.finditer(text)}
        broken = [p for p in paths if p.startswith("/") and
                  (not Path(p).exists() or verdict(archs_of(os.path.realpath(p)), native) != "native")]
        if broken:
            stale.append((cfg, broken))
    lines = [f"  ·  git-crypt を使う repo {len(cfgs)} 個 (下 {root})"]
    if not stale:
        lines.append("  ✅ filter の絶対 path はすべて存在するネイティブの git-crypt")
        return lines
    findings.append(f"git-crypt filter が無い / 別 arch の binary を指す repo {len(stale)} 個")
    for cfg, broken in stale:
        lines.append(f"  🔴 {cfg.parent.parent}: {', '.join(broken)}")
    if fix:
        if not target:
            lines.append("  ⛔ --fix: PATH に git-crypt が無いので書き換えない")
            return lines
        for cfg, broken in stale:
            text = cfg.read_text(errors="replace")
            for b in broken:
                text = text.replace(b, target)
            cfg.write_text(text)
        lines.append(f"  🔧 {len(stale)} 個の .git/config を {target} に書き換えた")
    else:
        lines.append(f"     直し方 = --fix-git-crypt-paths (今の git-crypt = {target or '無し'} に書き換え)")
    return lines


def check_launch_agents(native: str, findings: list) -> list[str]:
    nat = PREFIX[native] + "/bin"
    oth = PREFIX["x86_64" if native == "arm64" else "arm64"] + "/bin"
    lines, n = [], 0
    # /Library の 2 つは vendor の常駐 (更新係・helper) の置き場 = 移行で Intel 版がそのまま来る (実測: Java の更新係)
    plists = [p for d in (HOME / "Library/LaunchAgents", Path("/Library/LaunchAgents"), Path("/Library/LaunchDaemons"))
              for p in sorted(glob.glob(str(d / "*.plist")))]
    for pl in plists:
        try:
            d = plistlib.loads(Path(pl).read_bytes())
        except Exception:  # noqa: BLE001 — 壊れた plist は 1 行出して次へ
            lines.append(f"  ⚠️ 読めない plist: {Path(pl).name}")
            continue
        n += 1
        args = d.get("ProgramArguments") or ([d["Program"]] if d.get("Program") else [])
        blob = " ".join(map(str, args)) + " " + str((d.get("EnvironmentVariables") or {}).get("PATH", ""))
        probs = []
        if args and str(args[0]).startswith("/"):
            v = verdict(archs_of(os.path.realpath(str(args[0]))), native)
            if not Path(args[0]).exists():
                probs.append(f"起動する {args[0]} が無い")
            elif v in ("foreign", "dead"):
                probs.append(f"起動する {args[0]} が {v}")
        i_n, i_o = blob.find(nat), blob.find(oth)
        if i_o != -1 and (i_n == -1 or i_o < i_n):
            probs.append(f"PATH で {oth} が {nat} より前")
        if probs:
            findings.append(f"LaunchAgent {Path(pl).name}: {'; '.join(probs)}")
            lines.append(f"  🔴 {Path(pl).name}: {'; '.join(probs)}")
    lines.insert(0, f"  ·  LaunchAgents・LaunchDaemons {n} 個を見た (~/Library/LaunchAgents と /Library の 2 つ)")
    if len(lines) == 1:
        lines.append("  ✅ 起動 binary と PATH の並びに問題なし")
    return lines


def check_apps(native: str, findings: list) -> list[str]:
    roots = ["/Applications", str(HOME / "Applications")]
    foreign, dead = [], []
    for root in roots:
        # Unity Hub のエディタは <root>/Unity/Hub/Editor/<版>/Unity.app (深さ 5) = 3 段の glob に入らない (実測: Intel だけの古い版が漏れた)
        pats = [root + "/*.app", root + "/*/*.app", root + "/*/*/*.app", root + "/Unity/Hub/Editor/*/Unity.app"]
        for app in sorted({a for p in pats for a in glob.glob(p)}):
            info = Path(app) / "Contents" / "Info.plist"
            try:
                d = plistlib.loads(info.read_bytes())
            except Exception:  # noqa: BLE001
                continue
            exe = d.get("CFBundleExecutable")
            if not exe:
                continue
            v = verdict(archs_of(str(Path(app) / "Contents" / "MacOS" / exe)), native)
            if v == "foreign":
                foreign.append(app)
            elif v == "dead":
                dead.append(app)
    lines = []
    if foreign:
        findings.append(f"別 arch だけのアプリ {len(foreign)} 個")
        lines.append(f"  🟠 Rosetta 頼み (ネイティブ版に入れ替え候補) {len(foreign)} 個:")
        lines += [f"       {a}" for a in foreign]
    if dead:
        lines.append(f"  ⛔ どの現行 Mac でも起動しない (i386 / ppc だけ) {len(dead)} 個:")
        lines += [f"       {a}" for a in dead]
    updaters = foreign_support_bundles(native)
    if updaters:
        findings.append(f"別 arch の自動更新係・補助アプリ {len(updaters)} 個")
        lines.append(f"  🟠 /Applications の外の別 arch の bundle (自動更新係など) {len(updaters)} 個 — "
                     "Rosetta の下の更新係は別 arch として更新を取りに行き、 入れ替えたアプリを戻しうる "
                     "(直し方 = conventions/macos-cpu-arch.md#app-replacement):")
        lines += [f"       {a}" for a in updaters]
    if not lines:
        lines.append("  ✅ アプリはすべてネイティブ")
    return lines


def foreign_support_bundles(native: str) -> list[str]:
    """Application Support・Internet Plug-Ins・PreferencePanes と ~/Library/<vendor>/ に置かれた .app
    (自動更新係・補助) のうち別 arch だけのもの。

    移行アシスタントは旧機の arch の更新係を運ぶ。 本体を入れ替えても更新係が別 arch のままだと、
    更新係が自分の arch を名乗って更新を取り、 本体を旧 arch の版に戻しうる (実測)。 /Applications の走査では見えない。
    古い browser plug-in・設定 pane の中の更新係 (例: Java の plug-in の Java Updater) も同じ形で常駐する (実測)。
    """
    pats = []
    for base in ("/Library/Application Support", str(HOME / "Library/Application Support"),
                 "/Library/Internet Plug-Ins", str(HOME / "Library/Internet Plug-Ins"),
                 "/Library/PreferencePanes", str(HOME / "Library/PreferencePanes")):
        pats += [base + "/*/*.app", base + "/*/*/*.app", base + "/*/*/*/*.app"]
    pats.append(str(HOME / "Library") + "/*/*.app")
    seen, out = set(), []
    for app in sorted({a for p in pats for a in glob.glob(p)}):
        real = os.path.realpath(app)
        if real in seen or "/Script Editor/" in app:  # Apple の雛形 (droplet) は対象外
            continue
        seen.add(real)
        try:
            d = plistlib.loads((Path(app) / "Contents" / "Info.plist").read_bytes())
        except Exception:  # noqa: BLE001
            continue
        exe = d.get("CFBundleExecutable")
        if exe and verdict(archs_of(str(Path(app) / "Contents" / "MacOS" / exe)), native) == "foreign":
            out.append(app)
    return out


# Apple 自身の部品の中には x86_64 だけのものがあり、 古い plug-in を読むために Rosetta で動くのが正常
# (例: 古い音声 plug-in を調べる CarbonComponentScannerXPC、 古い printer の設定画面を出す RemotePDEService)。
APPLE_PREFIXES = ("/System/", "/usr/libexec/", "/usr/bin/", "/usr/sbin/", "/bin/", "/sbin/", "/Library/Apple/")


def apple_component(path: str) -> bool:
    return path.startswith(APPLE_PREFIXES)


def check_running(native: str, findings: list) -> list[str]:
    """いま動いている process のうち別 arch だけの binary (= Rosetta で動いている)。 Apple の部品は除く。"""
    try:
        comms = subprocess.run(["ps", "-axo", "comm="], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ["  ·  ps を起動できない"]
    paths = sorted({c.strip() for c in comms.splitlines() if c.strip().startswith("/")})
    bad = [p for p in paths if not apple_component(p) and os.path.isfile(p)
           and verdict(archs_of(p), native) == "foreign"]
    if not bad:
        return [f"  ✅ 動いている process ({len(paths)} 個の実行 file) に別 arch なし (Apple の部品は除く)"]
    findings.append(f"Rosetta で動いている process {len(bad)} 個")
    return [f"  🟠 Rosetta で動いている process {len(bad)} 個 — 常駐の更新係・旧版の残骸なら止めて退避する "
            "(直し方 = conventions/macos-cpu-arch.md#who-launched-intel):"] + [f"       {b}" for b in bad]


def venv_base(cfg_text: str) -> str | None:
    """pyvenv.cfg の中身から、 venv を作った interpreter の path。 `executable` が無ければ `home`/python3。"""
    kv = {}
    for line in cfg_text.splitlines():
        k, sep, v = line.partition("=")
        if sep:
            kv[k.strip()] = v.strip()
    if kv.get("executable"):
        return kv["executable"]
    if kv.get("home"):
        return kv["home"].rstrip("/") + "/python3"
    return None


def check_pythons(native: str, findings: list, repos_root: Path | None) -> list[str]:
    """PATH に無い Framework 版の Python と、 別 arch の (または消えた) Python を base にした venv。"""
    lines = []
    fw = []
    for base in ("/Library/Frameworks/Python.framework", str(HOME / "Library/Frameworks/Python.framework")):
        fw += [p for p in glob.glob(base + "/Versions/*/bin/python*") if re.search(r"/python\d(\.\d+)?$", p)]
    bad_fw = [p for p in sorted(set(fw)) if verdict(archs_of(os.path.realpath(p)), native) in ("foreign", "dead")]
    if bad_fw:
        findings.append(f"PATH の外の別 arch の Framework Python {len(bad_fw)} 個")
        lines.append(f"  🟠 PATH の外の別 arch の Framework Python {len(bad_fw)} 個 — 版で interpreter を探す道具が"
                     " 起動しうる (退避 = sudo で /Library/Frameworks の外へ):")
        lines += [f"       {p}" for p in bad_fw]
    elif fw:
        lines.append(f"  ✅ Framework Python {len(fw)} 個すべてネイティブ")
    cfgs = [HOME / ".venv" / "pyvenv.cfg"]
    if repos_root is not None:
        for pat in ("*/.venv/pyvenv.cfg", "*/*/.venv/pyvenv.cfg", "*/venv/pyvenv.cfg", "*/*/venv/pyvenv.cfg"):
            cfgs += [Path(p) for p in glob.glob(str(repos_root / pat))]
    bad_venv, n = [], 0
    for cfg in sorted({c for c in cfgs if c.is_file()}):
        n += 1
        try:
            base = venv_base(cfg.read_text(errors="replace"))
        except OSError:
            continue
        if not base:
            continue
        real = os.path.realpath(base)
        if not os.path.exists(real):
            bad_venv.append(f"{cfg.parent}: base の {base} が無い (venv は起動しない = 作り直す)")
        elif verdict(archs_of(real), native) in ("foreign", "dead"):
            bad_venv.append(f"{cfg.parent}: base の {real} が別 arch (Rosetta で動く = ネイティブの python で作り直す)")
    scope = "~/.venv" + (f" と {repos_root} の下 2 階層" if repos_root else " だけ (--repos-root で repo の venv も見る)")
    if bad_venv:
        findings.append(f"別 arch・消えた Python を base にした venv {len(bad_venv)} 個")
        lines.append(f"  🟠 venv {n} 個中 {len(bad_venv)} 個の base が別 arch か無い (見た範囲 = {scope}):")
        lines += [f"       {b}" for b in bad_venv]
    else:
        lines.append(f"  ✅ venv {n} 個の base はネイティブ (見た範囲 = {scope})")
    return lines


# ---------------------------------------------------------------- 本体
# 🟠 (入れ替え・退避の候補) の指摘。 終了値の 🔴 (= 普段の command・ジョブの実行経路が別 arch) に数えない
NOT_RED = ("別 arch だけのアプリ", "別 arch の自動更新係", "npx cache", "別 arch の Homebrew",
           "Rosetta で動いている process", "PATH の外の別 arch の Framework Python", "別 arch・消えた Python を base")


def run(args) -> int:
    native = hardware_arch()
    findings: list[str] = []
    out = [f"# macOS arch audit — この Mac = {'Apple Silicon (arm64)' if native == 'arm64' else 'Intel (x86_64)'}",
           f"  ネイティブの Homebrew prefix = {PREFIX[native]} / この process は "
           f"{'Rosetta で変換中 (x86_64 shell)' if process_translated() else 'ネイティブ'}"]
    if native == "arm64":
        out.append(f"  Rosetta = {'入っている' if rosetta_installed() else '入っていない (x86_64 binary は起動しない)'}")
    sections = [
        ("PATH 上の主な道具", check_commands(native, findings)),
        ("PATH の並び", check_path_order(native, findings)),
        ("Homebrew", check_homebrew(native, findings)),
        ("user の bin / 版管理の runtime", check_dirs(native, findings)),
        ("Python user site の拡張", check_python_user_site(native, findings)),
        ("npx cache", check_npx_cache(native, findings)),
        ("git-crypt filter の path", check_git_crypt(
            Path(os.path.expanduser(args.repos_root)) if args.repos_root else None,
            native, findings, args.fix_git_crypt_paths)),
        ("LaunchAgents", check_launch_agents(native, findings)),
        ("動いている process", check_running(native, findings)),
        ("PATH の外の Python と venv", check_pythons(
            native, findings, Path(os.path.expanduser(args.repos_root)) if args.repos_root else None)),
    ]
    if not args.no_apps:
        sections.append(("アプリ", check_apps(native, findings)))
    for title, lines in sections:
        out.append(f"\n## {title}")
        out += lines
    red = [f for f in findings if not f.startswith(NOT_RED)]
    out.append(f"\n{'🔴 実行経路に別 arch あり ' + str(len(red)) + ' 件' if red else '✅ 実行経路に別 arch なし'}"
               f" (アプリ・cache・残置 Homebrew・常駐 process・PATH の外の Python を含む指摘は全 {len(findings)} 件)。"
               " 直し方 = conventions/macos-cpu-arch.md")
    if args.json:
        print(json.dumps({"native": native, "findings": findings, "red": red}, ensure_ascii=False, indent=1))
    else:
        print("\n".join(out))
    return 1 if red else 0


def selftest() -> int:
    ok = True
    cases = [
        (["x86_64"], "arm64", "foreign"), (["arm64"], "arm64", "native"),
        (["arm64", "x86_64"], "x86_64", "native"), (["i386", "ppc7400"], "arm64", "dead"),
        (None, "arm64", "script"), (["arm64"], "x86_64", "foreign"),
    ]
    for archs, native, want in cases:
        got = verdict(archs, native)
        ok &= got == want
        print(f"  {'✅' if got == want else '❌'} verdict({archs}, {native}) = {got}")
    m = GC_RE.search('[filter "git-crypt"]\n\tclean = "/usr/local/bin/git-crypt" clean\n')
    ok &= bool(m) and m.group(2) == "/usr/local/bin/git-crypt"
    print(f"  {'✅' if m and m.group(2) == '/usr/local/bin/git-crypt' else '❌'} git-crypt filter の path を拾う (quote あり)")
    m2 = GC_RE.search("\tsmudge = /opt/homebrew/bin/git-crypt smudge\n")
    ok &= bool(m2) and m2.group(2) == "/opt/homebrew/bin/git-crypt"
    print(f"  {'✅' if m2 else '❌'} git-crypt filter の path を拾う (quote なし)")
    vcases = [
        ("home = /opt/x/bin\nversion = 3.13.1\nexecutable = /opt/x/bin/python3.13\n", "/opt/x/bin/python3.13"),
        ("home = /usr/local/opt/python@3.14/bin\ninclude-system-site-packages = false\n",
         "/usr/local/opt/python@3.14/bin/python3"),
        ("version = 3.9.6\n", None),
    ]
    for text, want in vcases:
        got = venv_base(text)
        ok &= got == want
        print(f"  {'✅' if got == want else '❌'} venv_base → {got} (executable が先、 無ければ home/python3)")
    acases = [("/System/Library/Frameworks/X.framework/XPCServices/Y.xpc/Contents/MacOS/Y", True),
              ("/usr/libexec/z", True),
              ("/Library/Internet Plug-Ins/P.plugin/Contents/Resources/U.app/Contents/MacOS/U", False),
              ("/Library/Application Support/V/U.app/Contents/MacOS/U", False)]
    for path, want in acases:
        got = apple_component(path)
        ok &= got == want
        print(f"  {'✅' if got == want else '❌'} apple_component({path.split('/')[1]}/…{path[-12:]}) = {got}")
    if sys.platform == "darwin":
        a = archs_of("/bin/ls")
        ok &= a is not None and hardware_arch() in a
        print(f"  {'✅' if a and hardware_arch() in a else '❌'} /bin/ls はこの Mac でネイティブ ({a})")
    else:
        # lipo と Mach-O は macOS だけ。 他の OS (CI の Linux) では、 上の述語の検査だけを見る
        print(f"  ⏭  /bin/ls の arch の検査は macOS だけ (この機は {sys.platform})")
    print("selftest:", "ALL PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repos-root", help="git-crypt filter と venv を見る repo 群の親 dir (2 階層まで)")
    ap.add_argument("--no-apps", action="store_true", help="アプリ (/Applications と Application Support の自動更新係) を走査しない")
    ap.add_argument("--fix-git-crypt-paths", action="store_true",
                    help="git-crypt filter の古い絶対 path を PATH 上の git-crypt に書き換える")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.fix_git_crypt_paths and not a.repos_root:
        print("--fix-git-crypt-paths には --repos-root が要る", file=sys.stderr)
        return 2
    return run(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
