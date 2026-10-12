#!/usr/bin/env python3
"""git-scrub-history.py — 履歴の全ての版の path 名・平文の中身・commit message から識別子 (ID・氏名・旧 path) を置き換える書き換えを、 設定 1 つで今の tree の先行改名・他 repo の参照の置換・予行演習・検証・本人の push の command・push の後の ref の点検まで通す。--selftest 内蔵。

## 兄弟の道具との分担

- file の全版を履歴から **落とす** = [`git-drop-path-history.py`](git-drop-path-history.py) (rehearse / apply / follow / shrink)。
- file は残して、 **path 名・平文の中身・commit message の中の識別子を置き換える** = 本 script。
- 他の machine の clone を新しい履歴に揃える = [`git-rewrite-follow.py`](git-rewrite-follow.py)。 本 script は追従を持たない。
  filter-repo の commit-map (`old new` の見出し + sha の対だけ) を `<work>/<name>.final.commit-map` に書く。 filter-repo は同じ
  repo での 2 回目の実行で前回の表と合成する = pass 2 の表は **元 → 最終** (合成されていなければ本 script が合成して書く)。
  旧世代にしか無い blob (置き換えた平文の版・暗号化し直した平文の版) = `<work>/<name>.final.commit-map.forbidden-blobs`
  (追従の pre-push guard が対応表の隣から読む)。 file 名は git-drop-path-history.py の `<name>.commit-map` と分けてある。
  同じ work に同じ name の mirror が在り、 本 script の印 (`refs/scrub-history/original`) が無ければ rehearse は消さずに止まる。
- 手順と理由の正本 = [`docs/sensitive-repo-patterns.ja.md#pattern-2-5`](../docs/sensitive-repo-patterns.ja.md#pattern-2-5)。
  消す一覧の作り方と、 検証を一覧から独立させる理由 =
  [`conventions/confidential-repo-boundary.md#history-scrub-identity-from-all-versions`](../conventions/confidential-repo-boundary.md#history-scrub-identity-from-all-versions)。

## 順序 (上から)

    python3 git-scrub-history.py plan-current --config C [--list] [--apply --message-file M]
        1. 今の tree に同じ規則 (改名・平文の中身) を dry-run。 --apply = git mv と中身の書き込み (commit はしない) の後、
           path を明示した commit の command (1 本 ≤ batch_bytes) を印字 → 1 本ずつ打つ。 改名の旧と新は同じ command に入る
    python3 git-scrub-history.py refs --config C [--root DIR] [--repo NAME] [--show] [--apply --message-file M]
        2. 旧 path・旧 id (改名した file の名前) への参照を refs_root 配下の全 repo (同じ repo も) で探す。 既定 dry-run
    python3 git-scrub-history.py rehearse --config C [--message-diff FILE]
        3. remote から mirror clone (origin は外す) → pass 1 = --filename-callback (改名だけ) → pass 2 = --file-info-callback
           (平文の中身・暗号化し直し) + --message-callback → verify。 remote と手元の checkout には触らない。 **やり直しもこの 1 行**
    python3 git-scrub-history.py verify --config C [--show] [--report FILE]
        rehearse の結果を検査する (rehearse が呼ぶ。 単独でも)。 1 つでも落ちれば exit 1
    python3 git-scrub-history.py push-command --config C
        4. remote が予行演習のときのままか・検証が PASS か・設定が同じかを確かめ、 本人が terminal で打つ控え (bundle) と
           force-with-lease の push (URL 明示 + refs/heads/<branch>:refs/heads/<branch>) を印字する。 本 script は push しない
    python3 git-scrub-history.py after-push --config C
        5. remote の branch が新しい先頭か + 旧履歴を抱えたままの ref (他の branch・tag・pull request の ref) と扱い
    python3 git-scrub-history.py --selftest            filter-repo を使わない部分 (合成の repo、 plumbing で作った書き換え)
    python3 git-scrub-history.py --selftest-rewrite    filter-repo を通す経路 (合成の repo、 本人の terminal で)

## 設定 (JSON。 旧 path の literal を含みうる = repo の外に置く。 repo の中なら警告)

  name (必須) / remote / local (手元の clone: plan-current の対象・暗号化し直しの鍵) / branch (既定 main) /
  work (mirror と対応表の置き場。 git の work tree の中なら止まる) / identity_file (下) /
  id_shape (識別子の形の正規表現。 英数字の境界で囲んで使う。 既定は大文字小文字を区別しない = id_shape_ignore_case) /
  id_shape_verify (検証だけに使う緩い形。 既定 = id_shape) / hex_exclusion ("lower" 既定 = 16 進の小文字だけの token は
  git の短い hash と見なして形から外す。 数字だけの token は外さない = 番号の消し残しを防ぐ / "any" / "none") / id_replacement (既定 "<ID>") / name_replacement (既定 "<NAME>") /
  path_rules [{"literal"|"re", "to"}] (順に path へ。 pass 1) / path_id_token (例 "s{n:03d}"。 規則の後の path に残る識別子を
  履歴の path の識別子の集合の順位で番号にする = 同じ履歴なら同じ番号。 履歴にしか無い file 用。 今の tree の path が
  これに落ちると plan-current は止まる = 明示の規則を足す) / content_rules [{"literal"|"re", "to", "paths"?}] (平文の中身) /
  message_rules [{"literal"|"re", "to"}] / scrub_ids / scrub_names / scrub_path_refs (既定 true。 中身と message の中の
  識別子・氏名・旧 path を置き換える) / path_ref_pairs [[旧, 新]] (文字だけの 1 語の旧 token は自動では置き換えない = 姓と
  同じ語を巻き込む。 置き換えるならここに明示) / blob_allow [path の正規表現] (中身に触らない) / reencrypt [path の正規表現]
  (平文だった版を `git-crypt clean` で暗号化し直す。 local は unlock 済み、 鍵を読むだけ) / crypt {"clean": [...], "smudge": [...]}
  (既定 git-crypt。 試験用) / protected [literal] (置き換えも検出もしない語。 例 = 教科書の著者名) /
  reviewed_paths [[path の正規表現, 理由]] (姓の token を含むが識別子でないと判断した path) / surname_min_latin (既定 3) /
  surname_min_cjk (既定 2) / surname_ignore [語] / surname_gate (既定 ["paths"]。 "messages" / "blobs" を足すと姓の当たりも
  FAIL にする) / name_min_cjk_full (既定 3) / refs_root (既定 = local の親) / syntax_check (既定 true) / batch_bytes (既定 2400)。
  path の条件 (content_rules.paths / blob_allow / reencrypt) は **改名の後の path** に当てる (pass 2 は改名後の path を見る)。
  `_` で始まる key は注釈として読み飛ばす。

## 識別子の file (identity_file。 machine-local の JSON。 **git の work tree の中に在ると止まる** = repo に入れない)

  {"ids": [既知の識別子], "names": [[姓, 名], "区切りの無い氏名", ...], "surnames": [検証用の姓 (台帳の全ての版から)]}
  [姓, 名] はラテン文字なら姓名・名姓の両順、 区切り = 空白 / カンマ / 下線 / ハイフン、 大文字小文字を区別しない。
  漢字の [姓, 名] と文字列は字の間の空白 (全角を含む) を許し、 大文字小文字を区別する。 [姓, 名] の姓は検証の姓にも入る。
  姓だけは置き換えない (教員など同じ姓の別人を巻き込む) = 検証で数えて人が見る。

## 教訓 (実測。 各行は selftest か verify が機械で見る)

- 改名は `--filename-callback` で行う。 `--file-info-callback` で改名すると後の commit の削除が旧名のまま残り、 消えたはずの
  file が最新の版に復活する (selftest-rewrite が再現を試し、 verify (2)(3) が捕まえる)。
- filter-repo は `--filename-callback` と `--file-info-callback` を同じ実行で受け付けない = 2 pass。
- 検証は置き換えの一覧から独立させる: 識別子は **形** で全 path・全 message・全平文 blob を走査し、 姓は台帳の **全部の姓** で
  走査する。 置き換えと同じ一覧で検証すると、 一覧が見落としたものは検証も見落とす (自己参照)。
- git の短い hash は識別子の形に当たる = 16 進だけの token は形から外す (既知の識別子の一覧に在るものは外さない)。
- code が読む file (label・key) の中身を置き換えると code が壊れうる: 改名後の HEAD で変わった .py / .sh / .json / .yaml を
  構文検査する (前に通って後に通らない = FAIL、 JSON / YAML の key の集合が変わった = 警告)。 plan-current も同じ検査をする。
- lease は予行演習の後に誰かが push すると拒まれる = やり直しは `rehearse --config C` の 1 行 (push-command が気づいて印字する)。
- push の後も、 main 以外の branch (dependabot 等) と pull request の ref (`refs/pull/*/head`) は旧履歴を抱えたまま残る
  = after-push が `git ls-remote` で列挙し、 branch は消す・作り直す、 PR の ref は host の support に消してもらう、 と出す。
- 共同作業者の clone も旧履歴を持つ (pull すると旧 commit が戻る) = 取り直してもらう。

## 限界

- `rehearse` は `git filter-repo` が要る (`pip install --user git-filter-repo`)。 Claude Code の auto mode は scratch の複製に
  対してでも filter-repo を破壊的な git 操作として止めることがある (実測) = rehearse は本人が terminal で走らせてよい。
- 検証の (7) と暗号化し直しは local の unlock 済みの clone で `git-crypt clean/smudge` を呼ぶ (鍵を読むだけ)。
- remote の旧 object は host の gc まで sha で取れる。 PR の ref は利用者から消せない。
- 出力は件数が基本。 path・token を出すのは `--show` / `--list` と止まる理由の行だけ (= 手元の terminal 用。 記録に写さない)。
"""
from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import warnings
from collections import Counter, defaultdict
from pathlib import Path

SELF = os.path.abspath(__file__)
ENC_MAGIC = b"\x00GITCRYPT"
GIT_ENV_DROP = ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES")
ANCHOR = "refs/scrub-history/original"
SYNTAX_EXT = (".py", ".sh", ".json", ".yaml", ".yml")
MASK_L, MASK_R, NEWTOK = "", "", ""


class Stop(Exception):
    """人に見せて止まる (exit 2。 code で変える)。"""

    def __init__(self, msg, code=2):
        super().__init__(msg)
        self.code = code


# ---------------------------------------------------------------- git helpers

def _env(extra=None):
    """hook から呼ばれても別 repo の index を読まない (hook-authoring.md#hook-git-env-cross-repo)。"""
    env = {k: v for k, v in os.environ.items() if k not in GIT_ENV_DROP}
    if extra:
        env.update(extra)
    return env


def _dec(b: bytes) -> str:
    return b.decode("utf-8", "surrogateescape")


def _enc(s: str) -> bytes:
    return s.encode("utf-8", "surrogateescape")


def run(cmd, *, cwd=None, input=None, env=None, check=True):
    r = subprocess.run(cmd, cwd=cwd, input=input, capture_output=True, env=env or _env())
    if check and r.returncode != 0:
        raise Stop(f"{' '.join(str(c) for c in cmd[:5])}: {_dec(r.stderr).strip()[:400]}")
    return r


def gitb(repo, *args, input=None, check=True, env=None) -> bytes:
    return run(["git", "-C", str(repo), "-c", "core.quotepath=false", *args], input=input, env=env, check=check).stdout


def gits(repo, *args, **kw) -> str:
    return _dec(gitb(repo, *args, **kw))


def zsplit(b: bytes):
    return [_dec(x) for x in b.split(b"\0") if x]


def rev(repo, spec):
    return gits(repo, "rev-parse", "--verify", "-q", spec, check=False).strip()


def ls_tree(repo, rv):
    out = []
    for e in gitb(repo, "ls-tree", "-r", "-z", rv).split(b"\0"):
        if not e:
            continue
        meta, p = e.split(b"\t", 1)
        mode, typ, sha = meta.decode().split()
        out.append((mode, typ, sha, _dec(p)))
    return out


def all_history_paths(repo, rv):
    return sorted(set(zsplit(gitb(repo, "log", rv, "--no-renames", "-m", "--format=", "--name-only", "-z"))))


def is_ancestor(repo, a, b):
    return run(["git", "-C", str(repo), "merge-base", "--is-ancestor", a, b], check=False).returncode == 0


def inside_worktree(path) -> bool:
    d = os.path.abspath(os.path.expanduser(str(path)))
    if not os.path.isdir(d):
        d = os.path.dirname(d)
    while d and not os.path.isdir(d):
        d = os.path.dirname(d)
    r = subprocess.run(["git", "-C", d or "/", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True,
                       env=_env())
    return r.returncode == 0 and r.stdout.strip() == "true"


def filter_repo_bin():
    found = shutil.which("git-filter-repo")
    if found:
        return found
    for base in sorted((Path.home() / "Library/Python").glob("*/bin/git-filter-repo")):
        return str(base)
    return None


class Objects:
    """git cat-file --batch (1 process)。"""

    def __init__(self, repo):
        self.p = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, env=_env())

    def get(self, spec: str) -> bytes | None:
        self.p.stdin.write(_enc(spec) + b"\n")
        self.p.stdin.flush()
        h = self.p.stdout.readline().split()
        if not h or h[-1] == b"missing":
            return None
        data = self.p.stdout.read(int(h[2]))
        self.p.stdout.read(1)
        return data

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=10)
        except Exception:
            self.p.kill()


def hid(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def commit_message(raw: bytes) -> bytes:
    i = raw.find(b"\n\n")
    return raw[i + 2:] if i >= 0 else b""


def load_map(path):
    d = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            a = line.split()
            if len(a) == 2 and a[0] != "old":
                d[a[0]] = a[1]
    return d


def write_map(path, m):
    with open(path, "w", encoding="utf-8") as f:
        f.write("old new\n")
        for o, n in m.items():
            f.write(f"{o} {n}\n")


def compose_maps(m1, m2):
    """pass 1 の表と pass 2 の表 → 元 → 最終。 filter-repo が合成済み (鍵の集合が同じ) ならそのまま。"""
    if not m1:
        return dict(m2)
    if set(m2) == set(m1):
        return dict(m2)
    return {o: m2.get(x, x) for o, x in m1.items()}


# ---------------------------------------------------------------- config

DEFAULTS = {
    "name": None, "remote": None, "local": None, "branch": "main", "work": None, "identity_file": None,
    "id_shape": None, "id_shape_verify": None, "id_shape_ignore_case": True, "hex_exclusion": "lower",
    "id_replacement": "<ID>", "name_replacement": "<NAME>",
    "path_rules": [], "path_id_token": None, "content_rules": [], "message_rules": [],
    "scrub_ids": True, "scrub_names": True, "scrub_path_refs": True, "path_ref_pairs": [],
    "blob_allow": [], "reencrypt": [], "crypt": None, "protected": [], "reviewed_paths": [],
    "surname_min_latin": 3, "surname_min_cjk": 2, "surname_ignore": [], "surname_gate": ["paths"],
    "name_min_cjk_full": 3, "refs_root": None, "syntax_check": True, "batch_bytes": 2400,
}
PATH_KEYS = ("local", "work", "identity_file", "refs_root")


def load_config(path, *, warn=True):
    path = os.path.abspath(os.path.expanduser(path))
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    unknown = [k for k in raw if k not in DEFAULTS and not k.startswith("_")]
    if unknown:
        raise Stop(f"設定に知らない key: {', '.join(sorted(unknown))} (綴りを確かめる。 注釈は _ で始める)")
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in raw.items() if not k.startswith("_")})
    base = os.path.dirname(path)
    for k in PATH_KEYS:
        if cfg[k]:
            p = os.path.expanduser(cfg[k])
            cfg[k] = p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))
    if not cfg["name"] or not re.fullmatch(r"[A-Za-z0-9._\-]+", cfg["name"]):
        raise Stop("設定の name は必須 (英数字 . _ - だけ = work の file 名の頭)")
    if cfg["hex_exclusion"] not in ("lower", "any", "none"):
        raise Stop("hex_exclusion は lower / any / none")
    bad = set(cfg["surname_gate"]) - {"paths", "messages", "blobs"}
    if bad:
        raise Stop(f"surname_gate に知らない値: {sorted(bad)}")
    cfg["_path"] = path
    if warn and inside_worktree(path):
        print(f"⚠️  設定が git の work tree の中に在る ({path})。 旧 path の literal を含むなら repo の外へ", file=sys.stderr)
    return cfg


def config_fingerprint(cfg):
    h = hashlib.sha256()
    for p in (cfg["_path"], cfg.get("identity_file")):
        if p and os.path.isfile(p):
            h.update(open(p, "rb").read())
        h.update(b"\0")
    return h.hexdigest()


def load_identity(path):
    if not path:
        return {"ids": [], "names": [], "surnames": []}
    if inside_worktree(path):
        raise Stop(f"identity_file が git の work tree の中に在る: {path}\n"
                   "  識別子と氏名の一覧は repo に入れない (machine-local の repo の外へ移す)")
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    unknown = set(d) - {"ids", "names", "surnames"} - {k for k in d if k.startswith("_")}
    if unknown:
        raise Stop(f"identity_file に知らない key: {sorted(unknown)}")
    out = {"ids": list(d.get("ids", [])), "names": list(d.get("names", [])), "surnames": list(d.get("surnames", []))}
    for n in out["names"]:
        if not isinstance(n, str) and not (isinstance(n, list) and len(n) == 2 and all(isinstance(x, str) for x in n)):
            raise Stop("identity_file の names: [姓, 名] か、 区切りの無い氏名の文字列")
    return out


def compile_rule(r, where):
    if not isinstance(r, dict) or "to" not in r or (("literal" in r) == ("re" in r)):
        raise Stop(f"{where}: 各規則は {{\"literal\" か \"re\", \"to\"}} (+ content_rules は \"paths\")")
    extra = set(r) - {"literal", "re", "to", "paths", "why", "id", "tier"} - {k for k in r if k.startswith("_")}
    if extra:
        raise Stop(f"{where}: 知らない key {sorted(extra)}")
    if r.get("paths") is not None and not isinstance(r["paths"], str):
        raise Stop(f"{where}: paths は正規表現の文字列 1 つ (list ではない。 複数なら | でつなぐ)")
    paths = re.compile(r["paths"]) if r.get("paths") else None
    if "literal" in r:
        if not r["literal"]:
            raise Stop(f"{where}: literal が空 (= 全ての文字の間に挿入する暴走)")
        return ("lit", r["literal"], r["to"], paths)
    rx = re.compile(r["re"])
    if rx.search("") is not None:
        raise Stop(f"{where}: 正規表現 {r['re']!r} が空文字列に当たる (= 全ての位置に挿入する暴走)")
    return ("re", rx, r["to"], paths)


def apply_rule(rule, text):
    kind, pat, to, _p = rule
    return text.replace(pat, to) if kind == "lit" else pat.sub(to, text)


def rule_hits(rule, text):
    kind, pat, to, _p = rule
    if kind == "lit":
        return text.replace(to, NEWTOK).count(pat) if to and pat not in to else text.count(pat)
    if "\\" not in to and to:
        text = text.replace(to, NEWTOK)
    return len(pat.findall(text))


# ---------------------------------------------------------------- rules engine

def _specific(tok: str) -> bool:
    """文字だけの 1 語 (= 姓と同じ語になりうる) でなく、 4 字以上。"""
    return len(tok) >= 4 and not re.fullmatch(r"[^\W\d_]+", tok)


class Rules:
    def __init__(self, cfg):
        self.cfg = cfg
        ident = load_identity(cfg.get("identity_file"))
        flags = re.I if cfg["id_shape_ignore_case"] else 0
        wrap = r"(?<![A-Za-z0-9])(?:%s)(?![A-Za-z0-9])"
        for k in ("id_shape", "id_shape_verify"):
            if cfg[k] and re.compile(cfg[k]).fullmatch("") is not None:
                raise Stop(f"{k} が空文字列に当たる")
        self.id_rx = re.compile(wrap % cfg["id_shape"], flags) if cfg["id_shape"] else None
        vs = cfg["id_shape_verify"] or cfg["id_shape"]
        self.id_rx_verify = re.compile(wrap % vs, flags) if vs else None
        ids = sorted({i for i in ident["ids"] if i}, key=len, reverse=True)
        self.known = {i.upper() for i in ids}
        self.known_rx = re.compile(wrap % "|".join(map(re.escape, ids)), re.I) if ids else None
        self.hex_rx = {"lower": re.compile(r"[0-9a-f]+"), "any": re.compile(r"[0-9a-fA-F]+"), "none": None}[cfg["hex_exclusion"]]
        # 氏名
        self.names = []  # (trigger, latin?, rx)
        families = []
        for n in ident["names"]:
            if isinstance(n, str):
                full = re.sub(r"[\s　]+", "", n)
                if len(full) >= cfg["name_min_cjk_full"]:
                    self.names.append((full[0], False, re.compile(r"[\s　]*".join(map(re.escape, full)))))
                continue
            fam, giv = n
            families.append(fam)
            if re.search(r"[A-Za-z]", fam + giv):
                if giv and len(fam) >= 2:
                    f, g = re.escape(fam), re.escape(giv)
                    self.names.append((fam.lower(), True, re.compile(
                        r"(?<![A-Za-z])(?:%s[\s,_\-]+%s|%s[\s,_\-]+%s)(?![A-Za-z])" % (f, g, g, f), re.I)))
            else:
                full = fam + giv
                if giv and len(full) >= cfg["name_min_cjk_full"]:
                    self.names.append((full[0], False, re.compile(r"[\s　]*".join(map(re.escape, full)))))
        # 姓 (検証用、 置き換えない)
        ign = {w.lower() for w in cfg["surname_ignore"]}
        sn = set(ident["surnames"]) | set(families)
        latin = sorted({s.lower() for s in sn if re.fullmatch(r"[A-Za-z'\-]+", s) and len(s) >= cfg["surname_min_latin"]}
                       - ign, key=len, reverse=True)
        cjk = sorted({s for s in sn if not re.search(r"[A-Za-z]", s) and len(s) >= cfg["surname_min_cjk"]}
                     - set(cfg["surname_ignore"]), key=len, reverse=True)
        self.sn_latin = re.compile(r"(?<![a-z])(%s)(?![a-z])" % "|".join(map(re.escape, latin)), re.I) if latin else None
        self.sn_cjk = re.compile("|".join(map(re.escape, cjk))) if cjk else None
        self.n_surnames = len(latin) + len(cjk)
        # 規則
        self.path_rules = [compile_rule(r, "path_rules") for r in cfg["path_rules"]]
        self.content_rules = [compile_rule(r, "content_rules") for r in cfg["content_rules"]]
        self.message_rules = [compile_rule(r, "message_rules") for r in cfg["message_rules"]]
        for r in self.path_rules + self.message_rules:
            if r[3] is not None:
                raise Stop("paths は content_rules だけに書ける")
        self.allow = [re.compile(x) for x in cfg["blob_allow"]]
        self.reenc = [re.compile(x) for x in cfg["reencrypt"]]
        self.reviewed = [(re.compile(x), why) for x, why in cfg["reviewed_paths"]]
        self.protected = sorted({p for p in cfg["protected"] if p}, key=len, reverse=True)
        crypt = cfg.get("crypt") or {}
        self.crypt_clean = crypt.get("clean") or ["git-crypt", "clean"]
        self.crypt_smudge = crypt.get("smudge") or ["git-crypt", "smudge"]
        self._clean_cache = {}

    # --- 守る語
    def mask(self, text):
        masks = {}
        for i, p in enumerate(self.protected):
            if p in text:
                tok = MASK_L + chr(0xE100 + i) + MASK_R
                text = text.replace(p, tok)
                masks[tok] = p
        return text, masks

    @staticmethod
    def unmask(text, masks):
        for tok, p in masks.items():
            text = text.replace(tok, p)
        return text

    # --- 識別子
    def _is_hex(self, tok):
        # 数字だけの token は 16 進の形にも当たるが、 外すと 7 桁以上の番号 (受付・口座・納付) が message に残る (実測)。
        # hash と見なすのは a-f の文字を 1 つ以上含む token だけ (数字だけの短い hash が置き換わる方へ倒す = 漏れより安全)
        return bool(self.hex_rx and self.hex_rx.fullmatch(tok) and not tok.isdigit())

    def id_tokens(self, text, verify=False):
        """(種類, token) の list。 種類 = known (一覧) / shape (形。 16 進だけの token と一覧のものは除く)。"""
        out = []
        if self.known_rx:
            out += [("known", m.group(0)) for m in self.known_rx.finditer(text)]
        rx = self.id_rx_verify if verify else self.id_rx
        if rx:
            for m in rx.finditer(text):
                t = m.group(0)
                if t.upper() not in self.known and not self._is_hex(t):
                    out.append(("shape", t))
        return out

    def sub_ids(self, text, repl=None):
        repl = self.cfg["id_replacement"] if repl is None else repl
        if self.known_rx:
            text = self.known_rx.sub(repl if callable(repl) else (lambda m: repl), text)
        if self.id_rx:
            def f(m):
                t = m.group(0)
                if self._is_hex(t):
                    return t
                return repl(m) if callable(repl) else repl
            text = self.id_rx.sub(f, text)
        return text

    # --- 氏名
    def name_hits(self, text):
        out, tl = [], text.lower()
        for trig, latin, rx in self.names:
            if trig in (tl if latin else text):
                out += [m.group(0) for m in rx.finditer(text)]
        return out

    def sub_names(self, text):
        repl = self.cfg["name_replacement"]
        for trig, latin, rx in self.names:
            if trig in (text.lower() if latin else text):
                text = rx.sub(repl, text)
        return text

    def surname_tokens(self, text):
        out = []
        if self.sn_latin:
            out += [m.group(0).lower() for m in self.sn_latin.finditer(text)]
        if self.sn_cjk:
            out += [m.group(0) for m in self.sn_cjk.finditer(text)]
        return out

    # --- path
    def explicit_path(self, p):
        for r in self.path_rules:
            p = apply_rule(r, p)
        return p

    def path_map(self, paths):
        """{旧 path: 新 path} (変わるものだけ) と、 番号に落ちた path の集合。 2 つの旧 path が同じ新 path に落ちたら止まる。"""
        explicit = {p: self.explicit_path(p) for p in paths}
        numbered = set()
        tok = self.cfg["path_id_token"]
        if tok:
            ids = sorted({t.upper() for q in explicit.values() for _k, t in self.id_tokens(q)})
            idx = {i: n for n, i in enumerate(ids, 1)}

            def num(m):
                return tok.format(n=idx[m.group(0).upper()])
            for p, q in explicit.items():
                q2 = self.sub_ids(q, repl=num)
                if q2 != q:
                    numbered.add(p)
                    explicit[p] = q2
        out = {p: q for p, q in explicit.items() if p != q}
        inv = {}
        for p, q in sorted(out.items()):
            if q in inv:
                raise Stop(f"path の衝突 (2 つの旧 path が同じ新 path に落ちる):\n  {inv[q]}\n  {p}\n  → {q}")
            inv[q] = p
        return out, numbered

    # --- blob
    def is_reenc(self, path):
        return any(r.search(path) for r in self.reenc)

    def is_allowed(self, path):
        return any(r.search(path) for r in self.allow)

    def class_key(self, path):
        return (self.is_reenc(path), self.is_allowed(path),
                tuple(i for i, r in enumerate(self.content_rules) if r[3] is None or r[3].search(path)))

    def clean(self, data):
        k = hid(data)
        if k not in self._clean_cache:
            r = subprocess.run(self.crypt_clean, cwd=self.cfg["local"], input=data, capture_output=True, env=_env())
            if r.returncode != 0 or not r.stdout.startswith(ENC_MAGIC):
                raise Stop(f"暗号化し直しに失敗 ({' '.join(self.crypt_clean)} in {self.cfg['local']}: unlock 済みか)")
            self._clean_cache[k] = r.stdout
        return self._clean_cache[k]

    def smudge(self, data):
        r = subprocess.run(self.crypt_smudge, cwd=self.cfg["local"], input=data, capture_output=True, env=_env())
        if r.returncode != 0:
            raise Stop("復号に失敗 (smudge)")
        return r.stdout

    def transform_blob(self, path, data, scr):
        """(新しい中身, 種類)。 種類 = None (変えない) / "reencrypt" / "scrub"。 path = 改名の後の path。"""
        if data.startswith(ENC_MAGIC):
            return data, None
        if self.is_reenc(path):
            return self.clean(data), "reencrypt"
        if b"\0" in data[:8000] or self.is_allowed(path):
            return data, None
        t = _dec(data)
        n = scr.scrub(t, "content", path)
        if n == t:
            return data, None
        return _enc(n), "scrub"

    def text_scrubber(self, pathmap):
        return TextScrubber(self, pathmap)


def ref_pairs(pathmap, extra=(), stems=False):
    """旧 path・その basename・同じ深さの dir の要素 (・stem) → 新。 文字だけの 1 語は自動では入れない (skipped)。
    同じ旧 token が別々の新 token に落ちるもの (曖昧) は入れない (conflicts)。"""
    pairs, skipped, conflicts = {}, set(), set()

    def add(o, n):
        if o == n:
            return
        if not _specific(o):
            skipped.add(o)
            return
        if o in pairs and pairs[o] != n:
            conflicts.add(o)
            return
        pairs[o] = n
    for o, n in pathmap.items():
        ob, nb = o.rsplit("/", 1)[-1], n.rsplit("/", 1)[-1]
        add(ob, nb)
        od, nd = o.split("/")[:-1], n.split("/")[:-1]
        if len(od) == len(nd):
            for a, b in zip(od, nd):
                add(a, b)
        if stems:
            so, sn = os.path.splitext(ob)[0], os.path.splitext(nb)[0]
            if len(so) >= 8:
                add(so, sn)
    for o in conflicts:
        pairs.pop(o, None)
    for o, n in pathmap.items():
        pairs[o] = n
    for o, n in extra:
        pairs[o] = n
    return pairs, skipped, conflicts


class TextScrubber:
    """中身と message の置き換え: 守る語を隠す → 規則 → 旧 path → 識別子 → 氏名 → 守る語を戻す。"""

    def __init__(self, rules, pathmap):
        self.r = rules
        pairs, self.skipped, self.conflicts = ref_pairs(pathmap, rules.cfg["path_ref_pairs"]) if rules.cfg["scrub_path_refs"] \
            else ({}, set(), set())
        self.pd = pairs
        alts = "|".join(re.escape(o) for o in sorted(pairs, key=len, reverse=True))
        self.old_rx = re.compile(r"(?<![A-Za-z0-9_])(?:%s)(?![A-Za-z0-9_])" % alts) if pairs else None
        self.new_tokens = sorted(set(pairs.values()), key=len, reverse=True)

    def _rules_for(self, kind, path):
        if kind == "message":
            return self.r.message_rules
        return [r for r in self.r.content_rules if r[3] is None or (path is not None and r[3].search(path))]

    def scrub(self, text, kind, path=None):
        text, masks = self.r.mask(text)
        for rule in self._rules_for(kind, path):
            text = apply_rule(rule, text)
        if self.old_rx:
            text = self.old_rx.sub(lambda m: self.pd[m.group(0)], text)
        if self.r.cfg["scrub_ids"]:
            text = self.r.sub_ids(text)
        if self.r.cfg["scrub_names"]:
            text = self.r.sub_names(text)
        return self.r.unmask(text, masks)

    def residual(self, text, kind, path=None):
        """置き換えの後に残るもの (検証用): OLD / RULE / ID(shape = 形、 known = 一覧) / NAME。"""
        text, _m = self.r.mask(text)
        hits = []
        if self.old_rx:
            t2 = text
            for n in self.new_tokens:
                t2 = t2.replace(n, NEWTOK)
            hits += ["OLD"] * len(self.old_rx.findall(t2))
        for rule in self._rules_for(kind, path):
            hits += ["RULE"] * rule_hits(rule, text)
        hits += ["ID:" + k for k, _t in self.r.id_tokens(text, verify=True)]
        hits += ["NAME"] * len(self.r.name_hits(text))
        return hits


# ---------------------------------------------------------------- syntax check

def _key_paths(obj, pre=()):
    out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(pre + (str(k),))
            out |= _key_paths(v, pre + (str(k),))
    elif isinstance(obj, list):
        for v in obj:
            out |= _key_paths(v, pre + ("[]",))
    return out


def check_syntax(path, old: bytes, new: bytes):
    """"ok" / "broken" (前は通り後は通らない) / "keys-changed" (JSON・YAML の key の集合が変わった) / "skip:<理由>"。"""
    ext = os.path.splitext(path)[1].lower()
    if ext not in SYNTAX_EXT:
        return "skip:ext"

    def parse(data):
        if ext == ".py":
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                compile(data, path, "exec")
            return None
        if ext == ".json":
            return json.loads(data.decode("utf-8"))
        if ext in (".yaml", ".yml"):
            import yaml  # noqa: PLC0415  (C 版 = run-all-checks の fast YAML loader の規則)
            return list(yaml.load_all(data.decode("utf-8"), Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader)))
        with tempfile.NamedTemporaryFile(suffix=".sh") as f:
            f.write(data)
            f.flush()
            if subprocess.run(["bash", "-n", f.name], capture_output=True).returncode != 0:
                raise ValueError("bash -n")
        return None
    try:
        po = parse(old)
    except ImportError:
        return "skip:no-parser"
    except Exception:
        return "skip:old-unparsable"
    try:
        pn = parse(new)
    except Exception:
        return "broken"
    if ext in (".json", ".yaml", ".yml") and _key_paths(po) != _key_paths(pn):
        return "keys-changed"
    return "ok"


# ---------------------------------------------------------------- work files

class Work:
    def __init__(self, cfg, require=True):
        if not cfg["work"]:
            raise Stop("設定に work が無い")
        self.dir = cfg["work"]
        n = cfg["name"]
        self.mirror = os.path.join(self.dir, f"{n}.git")
        self.old = os.path.join(self.dir, f"{n}.old")
        self.remote = os.path.join(self.dir, f"{n}.remote")
        self.map1 = os.path.join(self.dir, f"{n}.pass1.commit-map")
        self.map2 = os.path.join(self.dir, f"{n}.pass2.commit-map")
        self.map = os.path.join(self.dir, f"{n}.final.commit-map")  # git-drop-path-history の <name>.commit-map と別の名前
        self.forbidden = self.map + ".forbidden-blobs"
        self.vjson = os.path.join(self.dir, f"{n}.verify.json")
        self.vtxt = os.path.join(self.dir, f"{n}.verify.txt")
        self.bundle = os.path.join(self.dir, f"{n}-pre-scrub.bundle")
        if require and not (os.path.isdir(self.mirror) and os.path.isfile(self.old)):
            raise Stop(f"予行演習の結果が無い ({self.mirror} / {self.old})。 先に rehearse")

    def old_sha(self):
        return open(self.old).read().strip()

    def commit_map(self):
        m2 = load_map(self.map2) if os.path.isfile(self.map2) else (load_map(self.map) if os.path.isfile(self.map) else None)
        if m2 is None:
            raise Stop("commit-map が無い (rehearse の途中で止まった?)")
        m1 = load_map(self.map1) if os.path.isfile(self.map1) else {}
        return compose_maps(m1, m2)


# ---------------------------------------------------------------- filter-repo callbacks

_CB = None


def _cb_state():
    """filter-repo の callback から 1 回だけ作る (module は sys.modules に 1 回だけ読まれる)。"""
    global _CB
    if _CB is None:
        cfg = load_config(os.environ["GIT_SCRUB_HISTORY_CONFIG"], warn=False)
        rules = Rules(cfg)
        pm = json.load(open(os.environ["GIT_SCRUB_HISTORY_PATHMAP"], encoding="utf-8"))
        st = {"rules": rules, "bpm": {_enc(k): _enc(v) for k, v in pm.items()}, "scr": rules.text_scrubber(pm),
              "cache": {}, "n": Counter()}
        out = os.environ.get("GIT_SCRUB_HISTORY_STATS")
        if out:
            atexit.register(lambda: open(out, "w").write(json.dumps(dict(st["n"]))))
        _CB = st
    return _CB


def cb_rename(filename):
    st = _cb_state()
    new = st["bpm"].get(filename)
    if new is None:
        return filename
    st["n"]["renamed"] += 1
    return new


def cb_file_info(filename, mode, blob_id, value):
    if mode not in (b"100644", b"100755") or blob_id is None:
        return (filename, mode, blob_id)
    st = _cb_state()
    path = _dec(filename)
    key = (blob_id, st["rules"].class_key(path))
    if key not in st["cache"]:
        data = value.get_contents_by_identifier(blob_id)
        new, kind = st["rules"].transform_blob(path, data, st["scr"])
        st["cache"][key] = blob_id if kind is None else value.insert_file_with_contents(new)
        if kind:
            st["n"]["blobs_" + kind] += 1
    return (filename, mode, st["cache"][key])


def cb_message(msg):
    st = _cb_state()
    t = _dec(msg)
    n = st["scr"].scrub(t, "message")
    if n == t:
        return msg
    st["n"]["messages"] += 1
    return _enc(n)


def _cb_body(fn, args):
    return ("import os, sys, types\n"
            "m = sys.modules.get('git_scrub_history_cb')\n"
            "if m is None:\n"
            "    p = os.environ['GIT_SCRUB_HISTORY_SELF']\n"
            "    m = types.ModuleType('git_scrub_history_cb')\n"
            "    m.__file__ = p\n"
            "    sys.modules['git_scrub_history_cb'] = m\n"
            "    exec(compile(open(p, encoding='utf-8').read(), p, 'exec'), m.__dict__)\n"
            f"return m.{fn}({args})\n")


# ---------------------------------------------------------------- rehearse

def cmd_rehearse(cfg, message_diff=None, out=print):
    if not cfg["remote"]:
        raise Stop("設定に remote が無い")
    w = Work(cfg, require=False)
    if inside_worktree(cfg["work"]):
        raise Stop(f"work が git の work tree の中: {cfg['work']} (mirror と対応表は repo の外に置く)")
    if os.path.exists(w.mirror) and not rev(w.mirror, ANCHOR):
        raise Stop(f"work に同じ名前の mirror が在り、 本 script が作ったものでない ({ANCHOR} が無い): {w.mirror}\n"
                   "  name を変えるか、 中身を確かめてから手で退ける (別の道具の予行演習と対応表を消さない)")
    fr = filter_repo_bin()
    if not fr:
        raise Stop("git-filter-repo が無い (pip install --user git-filter-repo)")
    rules = Rules(cfg)
    if rules.reenc:
        if not cfg["local"] or not os.path.isdir(cfg["local"]):
            raise Stop("reencrypt には local (unlock 済みの clone) が要る")
        rules.clean(b"probe\n")
    os.makedirs(w.dir, exist_ok=True)
    for f in (w.map1, w.map2, w.map, w.forbidden, w.vjson, w.vtxt):
        if os.path.exists(f):
            os.remove(f)
    if os.path.exists(w.mirror):
        shutil.rmtree(w.mirror)
    run(["git", "clone", "-q", "--mirror", cfg["remote"], w.mirror])
    b = cfg["branch"]
    old = rev(w.mirror, f"refs/heads/{b}")
    if not old:
        raise Stop(f"remote に refs/heads/{b} が無い")
    open(w.old, "w").write(old + "\n")
    open(w.remote, "w").write(cfg["remote"] + "\n")
    gits(w.mirror, "update-ref", ANCHOR, old)
    refs = [r for r in gits(w.mirror, "for-each-ref", "--format=%(refname)").split() if r != ANCHOR]
    kinds = Counter(re.sub(r"^(refs/[^/]+)/.*", r"\1", r) for r in refs)
    out(f"########## {cfg['name']}")
    out(f"  土台 = remote の {b} {old[:12]} ({gits(w.mirror, 'rev-list', '--count', old).strip()} commits)、 "
        f"ref: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    hist = all_history_paths(w.mirror, old)
    pm, numbered = rules.path_map(hist)
    head_paths = {p for _m, t, _s, p in ls_tree(w.mirror, old) if t == "blob"}
    out(f"  path: 履歴の path {len(hist)} のうち改名 {len(pm)} (番号に落ちた {len(numbered)})、 "
        f"今の先頭で改名される path {len(head_paths & set(pm))}"
        + (" ← plan-current で先に通常の commit にする" if head_paths & set(pm) else ""))
    scr = rules.text_scrubber(pm)
    if scr.skipped or scr.conflicts:
        out(f"  中身・message の旧 token: 文字だけの 1 語で自動では置き換えない {len(scr.skipped)} / 曖昧で外した {len(scr.conflicts)}"
            " (要るなら path_ref_pairs に明示)")
    tmp = tempfile.mkdtemp(prefix="gsh-")
    os.chmod(tmp, 0o700)
    try:
        pmf = os.path.join(tmp, "pathmap.json")
        json.dump(pm, open(pmf, "w", encoding="utf-8"), ensure_ascii=False)
        env = _env({"PATH": str(Path(fr).parent) + os.pathsep + os.environ.get("PATH", ""),
                    "GIT_SCRUB_HISTORY_SELF": SELF, "GIT_SCRUB_HISTORY_CONFIG": cfg["_path"],
                    "GIT_SCRUB_HISTORY_PATHMAP": pmf})
        base = ["git", "-C", w.mirror, "filter-repo", "--force", "--quiet", "--refs", f"refs/heads/{b}",
                "--prune-empty", "never", "--prune-degenerate", "never"]
        m1 = {}
        if pm:
            env["GIT_SCRUB_HISTORY_STATS"] = os.path.join(tmp, "stats1.json")
            run(base + ["--filename-callback", _cb_body("cb_rename", "filename")], env=env)
            shutil.copy(os.path.join(w.mirror, "filter-repo", "commit-map"), w.map1)
            m1 = load_map(w.map1)
            out(f"  pass 1 (改名): {_stats(env['GIT_SCRUB_HISTORY_STATS'])}")
        env["GIT_SCRUB_HISTORY_STATS"] = os.path.join(tmp, "stats2.json")
        run(base + ["--file-info-callback", _cb_body("cb_file_info", "filename, mode, blob_id, value"),
                    "--message-callback", _cb_body("cb_message", "message")], env=env)
        shutil.copy(os.path.join(w.mirror, "filter-repo", "commit-map"), w.map2)
        out(f"  pass 2 (中身と message): {_stats(env['GIT_SCRUB_HISTORY_STATS'])}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    cmap = compose_maps(m1, load_map(w.map2))
    write_map(w.map, cmap)
    new = rev(w.mirror, f"refs/heads/{b}")
    if cmap.get(old) != new:
        raise Stop(f"対応表の旧先頭 → {cmap.get(old, '?')[:12]} が新しい先頭 {new[:12]} と違う (合成に失敗)")
    run(["git", "-C", w.mirror, "remote", "remove", "origin"], check=False)
    bo, bn = _blobs(w.mirror, old), _blobs(w.mirror, new)
    with open(w.forbidden, "w") as f:
        f.write("".join(s + "\n" for s in sorted(bo - bn)))
    changed_msgs = _message_diff(w.mirror, cmap, message_diff)
    out(f"  新しい先頭 = {new[:12]}。 message の変わった commit {changed_msgs}"
        f"{' (差分 = ' + message_diff + ')' if message_diff else ''}。 旧世代にしか無い blob {len(bo - bn)}")
    out(f"  対応表 (元 → 最終) = {w.map}")
    ok = cmd_verify(cfg, report=True, out=out)
    if ok:
        out(f"  予行演習 OK。 次 = python3 {shlex.quote(SELF)} push-command --config {shlex.quote(cfg['_path'])}")
    return 0 if ok else 1


def _stats(p):
    try:
        return ", ".join(f"{k} {v}" for k, v in sorted(json.load(open(p)).items())) or "変化なし"
    except (OSError, ValueError):
        return "?"


def _blobs(repo, ref):
    shas = [line.split(" ", 1)[0] for line in gits(repo, "rev-list", "--objects", ref).splitlines() if line]
    kinds = gits(repo, "cat-file", "--batch-check=%(objectname) %(objecttype)", input=_enc("\n".join(shas) + "\n"))
    return {line.split()[0] for line in kinds.splitlines() if line.endswith(" blob")}


def _message_diff(repo, cmap, out_file):
    if out_file and inside_worktree(out_file):
        raise Stop("--message-diff の出力先が git の work tree の中 (値を含む = repo の外へ)")
    ob = Objects(repo)
    n = 0
    f = open(out_file, "w", encoding="utf-8") if out_file else None
    try:
        for o, nw in cmap.items():
            a, b = commit_message(ob.get(o) or b""), commit_message(ob.get(nw) or b"")
            if a != b:
                n += 1
                if f:
                    f.write(f"=== {o[:10]} -> {nw[:10]}\n--- old\n{_dec(a)}\n+++ new\n{_dec(b)}\n")
    finally:
        ob.close()
        if f:
            f.close()
    return n


# ---------------------------------------------------------------- verify

def cmd_verify(cfg, report=False, show=False, report_file=None, out=print):
    """8 検査 (+ 構文): 1 つでも落ちれば False。"""
    rules = Rules(cfg)
    w = Work(cfg)
    repo, old = w.mirror, w.old_sha()
    b = cfg["branch"]
    new = rev(repo, f"refs/heads/{b}")
    if not rev(repo, old + "^{commit}"):
        raise Stop("旧先頭の commit が mirror に無い (gc された?) = rehearse をやり直す")
    M = w.commit_map()
    hist = all_history_paths(repo, old)
    PM, _numbered = rules.path_map(hist)
    scr = rules.text_scrubber(PM)
    ob = Objects(repo)
    lines, fail, summary = [], [], {}

    def say(s):
        lines.append(s)
        out(s)

    # (1)
    old_commits = gits(repo, "rev-list", old).split()
    new_commits = gits(repo, "rev-list", new).split()
    say(f"(1) commits: old={len(old_commits)} new={len(new_commits)}")
    if len(old_commits) != len(new_commits):
        fail.append("commit count")
    # (2)
    EXP, KIND = {}, {}
    changed, changed_paths = Counter(), defaultdict(set)

    def expected(sha, q):
        k = (sha, rules.class_key(q))
        if k not in EXP:
            data = ob.get(sha)
            nd, kind = rules.transform_blob(q, data, scr)
            EXP[k], KIND[k] = (hid(nd) if kind else sha), kind
            if kind:
                changed[kind] += 1
        if KIND[k]:
            changed_paths[KIND[k]].add(q)
        return EXP[k]
    bad = missing = 0
    exp_blobs = set()
    for c in old_commits:
        n = M.get(c)
        if not n:
            missing += 1
            continue
        t_old = []
        for mode, typ, sha, p in ls_tree(repo, c):
            q = PM.get(p, p)
            if typ == "blob" and mode in ("100644", "100755"):
                sha = expected(sha, q)
            if typ == "blob":
                exp_blobs.add(sha)
            t_old.append((mode, typ, sha, q))
        t_new = ls_tree(repo, n)
        if sorted(t_old) != sorted(t_new):
            bad += 1
            if bad <= 3:
                say(f"    mismatch at old {c[:10]}: only-old={len(set(t_old) - set(t_new))} "
                    f"only-new={len(set(t_new) - set(t_old))}")
    say(f"(2) per-commit tree = mapped old tree: mismatches={bad} unmapped={missing}; blob transforms: {dict(changed)} "
        f"(paths: " + ", ".join(f"{k}={len(v)}" for k, v in sorted(changed_paths.items())) + ")")
    if bad or missing:
        fail.append("per-commit tree")
    if M.get(old) != new:
        fail.append("old head does not map to the new head")
    # (3) 旧先頭 → 新先頭 の差 = 規則どおり (改名 = D+A、 中身だけ = M)
    head_old = {p: (mode, sha) for mode, typ, sha, p in ls_tree(repo, old) if typ == "blob"}
    want = Counter()
    content_head = []
    for p, (mode, sha) in head_old.items():
        q = PM.get(p, p)
        e = expected(sha, q) if mode in ("100644", "100755") else sha
        if q != p:
            want[("D", p)] += 1
            want[("A", q)] += 1
        elif e != sha:
            want[("M", p)] += 1
        if e != sha:
            content_head.append((p, q, sha, e))
    got = Counter()
    z = zsplit(gitb(repo, "diff", "--name-status", "--no-renames", "-z", old, new))
    for i in range(0, len(z) - 1, 2):
        got[(z[i][:1], z[i + 1])] += 1
    unexpected = sum((got - want).values())
    lacking = sum((want - got).values())
    n_ren = sum(1 for p in head_old if p in PM)
    n_head = len({p for p in head_old if p in PM} | {p for p, _q, _s, _e in content_head})
    say(f"(3) head diff: entries={sum(got.values())} unexpected={unexpected} missing={lacking} "
        f"(head paths the rules change = {n_head}: renamed {n_ren}, content {len(content_head)}"
        f"{'; 0 のはず = plan-current を先に' if n_head else ''})")
    summary["head_changes"] = n_head
    if unexpected or lacking:
        fail.append("head diff")
    # (4) blob の集合
    bo, bn = _blobs(repo, old), _blobs(repo, new)
    enc_o = {s for s in bo if (ob.get(s) or b"").startswith(ENC_MAGIC)}
    enc_n = {s for s in bn if (ob.get(s) or b"").startswith(ENC_MAGIC)}
    reenc_out = {EXP[k] for k in EXP if KIND[k] == "reencrypt"}
    say(f"(4) blobs: old={len(bo)} new={len(bn)} new==mapped(old): {bn == exp_blobs}; encrypted old={len(enc_o)} "
        f"new={len(enc_n)} old⊆new: {enc_o <= enc_n}; new−old = {len(enc_n - enc_o)} "
        f"(= re-encrypted outputs not already present: {len(reenc_out - enc_o)})")
    if bn != exp_blobs or not enc_o <= enc_n or (enc_n - enc_o) != (reenc_out - enc_o):
        fail.append("blob set")
    # (5) 残り (識別子は形で、 氏名、 旧 path、 規則)
    paths = set(all_history_paths(repo, new))
    old_renamed = set(PM) - set(PM.values())
    p_hits = [(p, r) for p in sorted(paths) if (r := [k for k in scr.residual(p, "path") if k != "RULE"])]
    still = paths & old_renamed
    m_hits = []
    for c in new_commits:
        msg = _dec(commit_message(ob.get(c) or b""))
        r = scr.residual(msg, "message")
        if r:
            m_hits.append((c, r))
    where = {}
    for line in gits(repo, "rev-list", "--objects", new).splitlines():
        a = line.split(" ", 1)
        if len(a) == 2:
            where.setdefault(a[0], a[1])
    pl_hits, nplain, plain_texts = [], 0, []
    for s in sorted(bn):
        d = ob.get(s) or b""
        if d.startswith(ENC_MAGIC) or b"\0" in d[:8000]:
            continue
        nplain += 1
        p = where.get(s, "?")
        if rules.is_allowed(p):
            continue
        t = _dec(d)
        plain_texts.append((p, t))
        r = scr.residual(t, "content", p)
        if r:
            pl_hits.append((p, r))
    say(f"(5) residual: paths={len(p_hits)} (of {len(paths)}) old-renamed-paths-present={len(still)} "
        f"messages={len(m_hits)} (of {len(new_commits)}) plaintext_text_blobs={len(pl_hits)} (of {nplain})")

    def kinds(r):
        return dict(Counter(r))
    for p, r in p_hits[:10]:
        say(f"    path residual kinds: {kinds(r)}" + (f"  {p}" if show else ""))
    for c, r in m_hits[:10]:
        say(f"    message {c[:10]} residual kinds: {kinds(r)}")
    for p, r in pl_hits[:10]:
        say(f"    plaintext blob residual kinds: {kinds(r)}" + (f"  {p}" if show else ""))
    if p_hits or still or m_hits or pl_hits:
        fail.append("residual")
    # (6) fsck
    r = subprocess.run(["git", "-C", repo, "fsck", "--full", "--no-progress"], capture_output=True, text=True, env=_env())
    txt = r.stdout + r.stderr
    fs = [x for x in txt.splitlines() if x and not x.startswith("dangling")]
    say(f"(6) fsck: rc={r.returncode} problems={len(fs)} dangling={txt.count('dangling')}")
    if r.returncode != 0 or fs:
        fail.append("fsck")
    # (7) 暗号化し直した blob の往復
    rt_bad = n_re = 0
    for (sha, _ck), e in EXP.items():
        if KIND[(sha, _ck)] != "reencrypt":
            continue
        n_re += 1
        if e not in bn or hid(rules.smudge(ob.get(e) or b"")) != sha:
            rt_bad += 1
    say(f"(7) re-encrypted blobs: {n_re}; smudge(new) == old plaintext: {n_re - rt_bad}/{n_re}")
    if rt_bad:
        fail.append("re-encrypt round trip")
    # (8) 姓 (台帳の全部の姓。 置き換えの一覧と独立)
    unrev = []
    for p in sorted(paths):
        t = rules.surname_tokens(rules.mask(p)[0])
        if t and not any(rx.search(p) for rx, _w in rules.reviewed):
            unrev.append((p, sorted(set(t))))
    sm = Counter()
    for c in new_commits:
        sm["messages"] += bool(rules.surname_tokens(rules.mask(_dec(commit_message(ob.get(c) or b"")))[0]))
    for _p, t in plain_texts:
        sm["blobs"] += bool(rules.surname_tokens(rules.mask(t)[0]))
    gate = set(cfg["surname_gate"])
    say(f"(8) surname tokens ({rules.n_surnames} surnames): unreviewed paths={len(unrev)}; "
        f"messages with a surname={sm['messages']} blobs with a surname={sm['blobs']} "
        f"(gate: {', '.join(sorted(gate)) or 'none'})")
    for p, t in unrev[:20]:
        say("    UNREVIEWED path" + (f" {','.join(t)}\t{p}" if show else f" ({len(t)} token)"))
    if (unrev and "paths" in gate) or (sm["messages"] and "messages" in gate) or (sm["blobs"] and "blobs" in gate):
        fail.append("surname tokens")
    # (9) code が読む file の構文
    syn = Counter()
    broken = []
    if cfg["syntax_check"]:
        for p, q, sha, e in content_head:
            new_data = ob.get(f"{new}:{q}")
            if new_data is None or new_data.startswith(ENC_MAGIC):
                continue
            s = check_syntax(q, ob.get(sha) or b"", new_data)
            syn[s.split(":")[0]] += 1
            if s in ("broken", "keys-changed"):
                broken.append((s, q))
    say(f"(9) syntax of head files the rules change: {dict(syn) or 'none'}"
        + (" (keys-changed = この file を読む code を確かめる。 --show で path)" if syn.get("keys-changed") and not show else ""))
    if show:
        for s, q in broken[:20]:
            say(f"    {s}  {q}")
    if syn.get("broken"):
        fail.append("syntax")
    ob.close()
    ok = not fail
    say("RESULT: " + ("PASS" if ok else "FAIL " + ", ".join(fail)))
    if report:
        with open(w.vtxt, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        json.dump({"result": "PASS" if ok else "FAIL", "failed": fail, "old": old, "new": new,
                   "config": config_fingerprint(cfg), **summary}, open(w.vjson, "w"), indent=1)
    if report_file:
        if inside_worktree(report_file):
            raise Stop("--report の出力先が git の work tree の中")
        open(report_file, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    return ok


# ---------------------------------------------------------------- plan-current

def batch_commands(repo, units, msg_file, limit):
    """path を明示した commit の command を limit byte 以下の束に (単位 = 改名の旧と新の組 / 1 path)。"""
    head = f"git -C {shlex.quote(str(repo))} commit -q -F {shlex.quote(str(msg_file))} --"
    cmds, cur = [], []
    for u in units:
        trial = head + " " + " ".join(shlex.quote(p) for p in cur + u)
        if cur and len(trial.encode()) > limit:
            cmds.append(head + " " + " ".join(shlex.quote(p) for p in cur))
            cur = []
        cur += u
        one = head + " " + " ".join(shlex.quote(p) for p in cur)
        if len(one.encode()) > limit:
            raise Stop(f"1 つの単位だけで {len(one.encode())} byte (上限 {limit}) = path が長すぎる")
    if cur:
        cmds.append(head + " " + " ".join(shlex.quote(p) for p in cur))
    return cmds


def plan_current(cfg, repo=None, out=print):
    """今の tree の計画: (renames [(旧, 新)], edits [(新 path, 旧 path, 新しい中身, 置き換え数, 構文)], stops [文])。"""
    rules = Rules(cfg)
    repo = repo or cfg["local"]
    if not repo or not os.path.isdir(repo):
        raise Stop("local (手元の clone) が無い")
    b = cfg["branch"]
    hist = all_history_paths(repo, b if rev(repo, b) else "HEAD")
    pm, numbered = rules.path_map(hist)
    scr = rules.text_scrubber(pm)
    files = zsplit(gitb(repo, "ls-files", "-z"))
    attrs = zsplit(gitb(repo, "check-attr", "-z", "filter", "--stdin", input=b"\0".join(_enc(f) for f in files) + b"\0"))
    crypted = {attrs[i] for i in range(0, len(attrs) - 2, 3) if attrs[i + 2] == "git-crypt"}
    ob = Objects(repo)
    renames, edits, stops = [], [], []
    try:
        for p in files:
            q = pm.get(p, p)
            if q != p:
                renames.append((p, q))
            if p in numbered:
                stops.append(f"今の tree の path が番号に落ちる (明示の path_rules を足す): {p}")
            elif rules.id_tokens(q, verify=True) or rules.name_hits(q):
                stops.append(f"規則の後も path に識別子・氏名が残る (path_rules を足す): {q}")
            data = ob.get(f"HEAD:{p}")
            if data is None:
                continue
            if rules.is_reenc(q) and not data.startswith(ENC_MAGIC):
                stops.append(f"暗号化と宣言した path の今の版が平文 (先に通常の commit で暗号化する): {p}")
                continue
            if p in crypted and not data.startswith(ENC_MAGIC):
                stops.append(f"filter=git-crypt なのに今の版が平文 (先に暗号化して commit する): {p}")
                continue
            fp = os.path.join(repo, p)
            if os.path.islink(fp):
                continue
            nd, kind = rules.transform_blob(q, data, scr)
            if kind == "scrub":
                n = len(scr.residual(_dec(data), "content", q))
                syn = check_syntax(q, data, nd) if cfg["syntax_check"] else "skip:off"
                edits.append((q, p, nd, n, syn))
                if syn == "broken":
                    stops.append(f"置き換えると構文が壊れる (規則を直す): {q}")
    finally:
        ob.close()
    return renames, edits, stops


def cmd_plan_current(cfg, apply=False, message_file=None, repo=None, listing=False, out=print):
    repo = repo or cfg["local"]
    if apply and not message_file:
        raise Stop("--apply には --message-file (commit message の file) が要る")
    if message_file and not os.path.isfile(message_file):
        raise Stop(f"--message-file が無い: {message_file}")
    up = run(["git", "-C", repo, "rev-list", "--left-right", "--count", "HEAD...@{u}"], check=False)
    if up.returncode == 0:
        ahead, behind = up.stdout.split()
        if behind != b"0":
            out(f"⚠️  手元が upstream より {behind.decode()} commit 遅れている (先に pull --ff-only)")
    renames, edits, stops = plan_current(cfg, repo, out)
    syn = Counter(e[4].split(":")[0] for e in edits)
    out(f"plan-current {os.path.basename(repo.rstrip('/'))}: 改名 {len(renames)} path / 中身の置き換え {len(edits)} file "
        f"({sum(e[3] for e in edits)} 箇所) / 構文 {dict(syn) or 'none'}")
    if listing:
        for p, q in renames:
            out(f"  R\t{p}\t{q}")
        for q, _p, _nd, n, s in edits:
            out(f"  C\t{q}\t{n}\t{s}")
    for s in stops:
        out("  STOP: " + s)
    for q, _p, _nd, _n, s in edits:
        if s == "keys-changed":
            out(f"  ⚠️ key の集合が変わる (この file を読む code を確かめる){': ' + q if listing else ''}")
    if stops:
        return 2
    ren_new = {q for _p, q in renames}
    units = [[p, q] for p, q in renames] + [[q] for q, *_r in edits if q not in ren_new]
    if not apply:
        if units:
            n = len(batch_commands(repo, units, message_file or "M", cfg["batch_bytes"]))
            out(f"  (dry-run。 --apply --message-file M で書き込み、 path を明示した commit の command {n} 本を印字する)")
        return 0
    touched = [p for p, _q in renames] + [p for _q, p, *_r in edits]
    st = gitb(repo, "status", "--porcelain", "-z", "--", *touched) if touched else b""
    if st.strip(b"\0"):
        raise Stop("置き換える path に未 commit の変更がある (別の session の作業?)。 先に片付けてから")
    for p, q in renames:
        os.makedirs(os.path.dirname(os.path.join(repo, q)) or repo, exist_ok=True)
        gits(repo, "mv", "--", p, q)
    for q, _p, nd, _n, _s in edits:
        with open(os.path.join(repo, q), "wb") as f:
            f.write(nd)
    cmds = batch_commands(repo, units, message_file, cfg["batch_bytes"])
    out(f"  書き込んだ (未 commit)。 次の {len(cmds)} 本を 1 本ずつ打つ (wrapper にまとめない):")
    for c in cmds:
        out(c)
    return 0


# ---------------------------------------------------------------- refs

def _repos(root, only=None):
    for d in sorted(os.listdir(root)):
        if only and d != only:
            continue
        p = os.path.join(root, d)
        if os.path.exists(os.path.join(p, ".git")):
            yield d, p


def cmd_refs(cfg, root=None, only=None, apply=False, message_file=None, show=False, out=print):
    rules = Rules(cfg)
    local = cfg["local"]
    if not local or not os.path.isdir(local):
        raise Stop("local (手元の clone) が無い")
    if apply and not message_file:
        raise Stop("--apply には --message-file が要る")
    root = root or cfg["refs_root"] or os.path.dirname(local.rstrip("/"))
    b = cfg["branch"]
    pm, _n = rules.path_map(all_history_paths(local, b if rev(local, b) else "HEAD"))
    pairs, skipped, conflicts = ref_pairs(pm, cfg["path_ref_pairs"], stems=True)
    out(f"refs: 置き換える token {len(pairs)} (文字だけの 1 語で入れない {len(skipped)} / 曖昧で外した {len(conflicts)})")
    if not pairs:
        return 0
    rx = re.compile(r"(?<![A-Za-z0-9_])(?:%s)(?![A-Za-z0-9_])" % "|".join(
        re.escape(o) for o in sorted(pairs, key=len, reverse=True)))
    tmp = tempfile.NamedTemporaryFile("wb", delete=False, prefix="gsh-pat-")
    tmp.write(b"\n".join(_enc(o) for o in pairs) + b"\n")
    tmp.close()
    total = 0
    try:
        for name, path in _repos(root, only):
            r = run(["git", "-C", path, "-c", "core.quotepath=false", "grep", "--untracked", "-I", "-z", "-n", "-F",
                     "-f", tmp.name], check=False)
            per_file = Counter()
            for line in r.stdout.split(b"\n"):
                parts = line.split(b"\0", 2)
                if len(parts) < 3:
                    continue
                per_file[_dec(parts[0])] += len(rx.findall(_dec(parts[2])))
            per_file = Counter({f: n for f, n in per_file.items() if n})
            tracked = set(zsplit(gitb(path, "ls-files", "-z"))) if per_file else set()
            locked = _locked_files(path)
            if not per_file and not locked:
                continue
            untracked = [f for f in per_file if f not in tracked]
            out(f"  {name}: file {len(per_file)} (未追跡 {len(untracked)} = 書かない) / 箇所 {sum(per_file.values())}"
                + (f" / 復号されていない暗号化 file {locked} = 読めていない" if locked else ""))
            if show:
                for f, n in sorted(per_file.items()):
                    out(f"    {f}\t{n}")
            total += sum(per_file.values())
            if not apply:
                continue
            todo = sorted(f for f in per_file if f in tracked)
            dirty = set(zsplit(gitb(path, "diff", "--name-only", "-z", "HEAD", "--", *todo))) if todo else set()
            written = []
            for f in todo:
                if f in dirty:
                    out(f"    skip (未 commit の変更がある): {f if show else '1 file'}")
                    continue
                fp = os.path.join(path, f)
                with open(fp, encoding="utf-8", errors="surrogateescape", newline="") as fh:
                    t = fh.read()
                n = rx.sub(lambda m: pairs[m.group(0)], t)
                if n != t:
                    with open(fp, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
                        fh.write(n)
                    written.append(f)
            if written:
                cmds = batch_commands(path, [[f] for f in written], message_file, cfg["batch_bytes"])
                out(f"    書いた {len(written)} file (未 commit)。 次の {len(cmds)} 本を 1 本ずつ:")
                for c in cmds:
                    out(c)
    finally:
        os.unlink(tmp.name)
    if not apply and total:
        out("  (dry-run。 --apply --message-file M で書き込む。 --show で file ごとの件数)")
    return 0


def _locked_files(path):
    files = zsplit(gitb(path, "ls-files", "-z"))
    if not files:
        return 0
    attrs = zsplit(gitb(path, "check-attr", "-z", "filter", "--stdin", input=b"\0".join(_enc(f) for f in files) + b"\0"))
    n = 0
    for i in range(0, len(attrs) - 2, 3):
        if attrs[i + 2] == "git-crypt":
            fp = os.path.join(path, attrs[i])
            try:
                with open(fp, "rb") as fh:
                    n += fh.read(len(ENC_MAGIC)) == ENC_MAGIC
            except OSError:
                pass
    return n


# ---------------------------------------------------------------- push-command / after-push

def _ls_remote(url, *patterns):
    r = run(["git", "ls-remote", url, *patterns], check=False)
    if r.returncode != 0:
        raise Stop(f"ls-remote に失敗 (通信?): {_dec(r.stderr).strip()[:200]}")
    out = {}
    for line in _dec(r.stdout).splitlines():
        sha, ref = line.split("\t", 1)
        out[ref] = sha
    return out


def _old_holders(repo, refs, new, old):
    """refs {ref: sha} のうち、 旧履歴にしか無い commit を抱えるもの → {ref: "old" / "unknown"}。"""
    old_only = set(gits(repo, "rev-list", old, "--not", new).split())
    res = {}
    for ref, sha in sorted(refs.items()):
        if not rev(repo, sha + "^{commit}"):
            res[ref] = "unknown"
            continue
        if set(gits(repo, "rev-list", sha, "--not", new).split()) & old_only:
            res[ref] = "old"
    return res


def _advice(ref, remote):
    if ref.startswith("refs/pull/"):
        return "pull request の ref = 利用者は消せない。 host の support に ref の削除と gc を頼む"
    if ref.startswith("refs/tags/"):
        return f"tag = 新しい履歴の commit に付け直すか消す (git push {shlex.quote(remote)} --delete {ref})"
    if ref.startswith("refs/heads/"):
        return (f"branch = 要らなければ消す (git push {shlex.quote(remote)} --delete {ref})、 要るなら新しい main の上に"
                " 作り直す (merge すると旧履歴が戻る)")
    return "その他の ref = 中身を確かめて消すか作り直す"


def cmd_push_command(cfg, out=print):
    w = Work(cfg)
    old, b = w.old_sha(), cfg["branch"]
    new = rev(w.mirror, f"refs/heads/{b}")
    remote = cfg["remote"] or open(w.remote).read().strip()
    redo = f"python3 {shlex.quote(SELF)} rehearse --config {shlex.quote(cfg['_path'])}"
    try:
        v = json.load(open(w.vjson))
    except (OSError, ValueError):
        v = {}
    if v.get("result") != "PASS" or v.get("new") != new or v.get("old") != old:
        out(f"❌ 検証が PASS でないか、 mirror と合わない。 やり直し = {redo}")
        return 1
    if v.get("config") != config_fingerprint(cfg):
        out(f"❌ 検証の後に設定か識別子の file が変わった。 やり直し = {redo}")
        return 1
    now = _ls_remote(remote, f"refs/heads/{b}").get(f"refs/heads/{b}", "")
    if now != old:
        out(f"❌ remote の {b} が予行演習の後に動いた ({old[:10]} → {now[:10] or '無い'}) = lease が拒む。 やり直し = {redo}")
        return 1
    local = cfg["local"]
    if local and os.path.isdir(local):
        head = rev(local, "HEAD")
        if head != old and not is_ancestor(local, head, old):
            out(f"❌ 手元の HEAD ({head[:10]}) に remote に無い commit がある = 先に通常どおり push してから やり直し = {redo}")
            return 1
    if v.get("head_changes"):
        out(f"⚠️  書き換えで先頭の tree が変わる ({v['head_changes']} path)。 他の clone の追従で差分が出る"
            " (plan-current で先に通常の commit にしておくと 0)")
    others = {r: s for r, s in _mirror_refs(w.mirror).items() if r != f"refs/heads/{b}"}
    hold = _old_holders(w.mirror, others, new, old)
    if hold:
        out(f"⚠️  remote の他の ref が旧履歴を抱えている ({len(hold)})。 push の後に after-push が扱いを出す")
    q = shlex.quote
    bundle = (f"git -C {q(w.mirror)} bundle create {q(w.bundle)} {ANCHOR}" if rev(w.mirror, ANCHOR)
              else f"git -C {q(local or '.')} bundle create {q(w.bundle)} --all")
    out("# 本人が terminal で (不可逆。 素の git push は mirror の全 ref を押すので打たない):")
    out(bundle)
    out(f"git -C {q(w.mirror)} push --force-with-lease=refs/heads/{b}:{old} {q(remote)} refs/heads/{b}:refs/heads/{b}")
    out(f"python3 {q(SELF)} after-push --config {q(cfg['_path'])}")
    out(f"# lease が拒んだら (誰かが push した) = {redo} からやり直す")
    return 0


def _mirror_refs(repo):
    out = {}
    for line in gits(repo, "for-each-ref", "--format=%(objectname) %(refname)").splitlines():
        sha, ref = line.split(" ", 1)
        if not ref.startswith("refs/scrub-history/"):
            out[ref] = sha
    return out


def cmd_after_push(cfg, out=print):
    w = Work(cfg)
    old, b = w.old_sha(), cfg["branch"]
    new = rev(w.mirror, f"refs/heads/{b}")
    remote = cfg["remote"] or open(w.remote).read().strip()
    refs = {r: s for r, s in _ls_remote(remote).items() if not r.endswith("^{}") and r != "HEAD"}
    main_now = refs.pop(f"refs/heads/{b}", "")
    ok = main_now == new
    out(f"remote の {b}: {'= 新しい先頭' if ok else '❌ 新しい先頭でない'} ({main_now[:10] or '無い'} / 新 {new[:10]})")
    hold = _old_holders(w.mirror, refs, new, old)
    kinds = Counter(re.sub(r"^(refs/[^/]+)/.*", r"\1", r) for r in refs)
    out(f"remote の他の ref: {dict(kinds) or 'なし'}。 旧履歴を抱える {sum(1 for v in hold.values() if v == 'old')}"
        f" / 中身を確かめられない (予行演習の後に作られた) {sum(1 for v in hold.values() if v == 'unknown')}")
    for ref, st in hold.items():
        out(f"  {'OLD' if st == 'old' else '???'} {ref}: {_advice(ref, remote) if st == 'old' else 'fetch して中身を確かめる'}")
    out("次:")
    out(f"  - 他の machine = git-rewrite-follow.py (対応表 {w.map} と {w.forbidden} を、 repo の .rewrite-follow/ に"
        " commit-map-<印> / forbidden-blobs-<印> として通常の commit で置く)")
    out("  - 共同作業者の clone も旧履歴を持つ = pull せず取り直してもらう (pull や merge で旧 commit が戻る)")
    out("  - remote の旧 object は host の gc まで sha で取れる。 急ぐなら host の support に頼む")
    return 0 if ok else 1


# ---------------------------------------------------------------- selftest

FAKE_CRYPT = r'''import sys
d = sys.stdin.buffer.read()
M = b"\x00GITCRYPT\x00"
if sys.argv[1] == "clean":
    sys.stdout.buffer.write(d if d.startswith(M) else M + d[::-1])
else:
    sys.stdout.buffer.write(d[len(M):][::-1] if d.startswith(M) else d)
'''


def _fx_env():
    env = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    os.environ.update(env)


def _fx_commit(repo, files, msg):
    for f, body in files.items():
        fp = os.path.join(repo, f)
        if body is None:
            gits(repo, "rm", "-q", "--", f)
            continue
        os.makedirs(os.path.dirname(fp) or repo, exist_ok=True)
        with open(fp, "wb") as fh:
            fh.write(body if isinstance(body, bytes) else body.encode())
        gits(repo, "add", "--", f)
    gits(repo, "commit", "-q", "--allow-empty", "-m", msg)


def _fx(tmp, crypt_py):
    """合成の remote (bare) と作業 clone。 氏名・識別子は全部架空。"""
    remote = os.path.join(tmp, "remote.git")
    src = os.path.join(tmp, "src")
    run(["git", "init", "-q", "--bare", "-b", "main", remote])
    run(["git", "init", "-q", "-b", "main", src])
    enc = lambda s: b"\x00GITCRYPT\x00" + s.encode()[::-1]  # noqa: E731  (FAKE_CRYPT の clean と同じ)
    _fx_commit(src, {
        "people/QZX31415/notes.md": "Met Alice Quuxley (QUUXLEY, Alice). LABEL_OLD. See ticket-quux-7.\n"
                                    "Ref Quuxley's Handbook. Hash abc16180 stays.\n",
        "data/roster.json": '{"Quuxley Alice": 1, "id": "qzx31415", "role": "x"}\n',
        "scripts/tool.py": 'OWNER = "Alice Quuxley"\nprint(OWNER)\n',
        "secret/list.txt": "架空 花子\n",
        "vendor/lib.txt": "Alice Quuxley vendored\n",
        "docs/zorblatt-method.md": "The Zorblatt method (a textbook name).\n",
    }, "add notes for Alice Quuxley QZX31415 (ticket-quux-7, abc16180)")
    _fx_commit(src, {"gone/QZX99001.txt": "temp\n", "notes/quuxley-mtg.md": "mtg\n"}, "c2 see people/QZX31415/notes.md")
    _fx_commit(src, {"gone/QZX99001.txt": None, "secret/list.txt": enc("架空 花子\n")}, "c3 drop gone file; encrypt secret")
    _fx_commit(src, {"people/QZX31415/notes.md": "Met Alice Quuxley again. fed27182 known.\n"}, "c4 update")
    gits(src, "remote", "add", "origin", remote)
    gits(src, "push", "-q", "origin", "main")
    ident = os.path.join(tmp, "ident.json")
    json.dump({"ids": ["QZX31415", "fed27182"], "names": [["Quuxley", "Alice"], "架空花子"],
               "surnames": ["Zorblatt"]}, open(ident, "w"))
    cfg_d = {"name": "fx", "remote": remote, "local": src, "work": os.path.join(tmp, "work"), "identity_file": ident,
             "id_shape": "[A-Z]{3}[0-9]{5}",
             "path_rules": [{"literal": "people/QZX31415/", "to": "people/s-a/"},
                            {"re": r"^notes/quuxley-", "to": "notes/"}],
             "path_id_token": "s{n:03d}",
             "content_rules": [{"literal": "LABEL_OLD", "to": "LABEL_NEW", "paths": r"\.md$"}],
             "message_rules": [{"re": r"ticket-quux-\d+", "to": "ticket-x"}],
             "blob_allow": ["^vendor/"], "reencrypt": ["^secret/"],
             "crypt": {"clean": [sys.executable, crypt_py, "clean"], "smudge": [sys.executable, crypt_py, "smudge"]},
             "protected": ["Quuxley's Handbook"],
             "reviewed_paths": [[r"^docs/zorblatt-method\.md$", "a method named after a book"]]}
    return remote, src, cfg_d


def _write_cfg(tmp, d, name="cfg.json"):
    p = os.path.join(tmp, name)
    json.dump(d, open(p, "w"), ensure_ascii=False)
    return load_config(p, warn=False)


def _sim_rewrite(cfg, *, resurrect=False, skip_msg_scrub=None):
    """filter-repo の 2 pass と同じ結果を plumbing で作る (selftest 用): remote の mirror → refs/heads/<b> を書き換える。
    resurrect = --file-info-callback で改名したときの欠陥 (削除が旧名のまま) を模す。"""
    rules = Rules(cfg)
    w = Work(cfg, require=False)
    os.makedirs(w.dir, exist_ok=True)
    if os.path.exists(w.mirror):
        shutil.rmtree(w.mirror)
    for f in (w.map1, w.map2, w.map, w.vjson):
        if os.path.exists(f):
            os.remove(f)
    run(["git", "clone", "-q", "--mirror", cfg["remote"], w.mirror])
    repo, b = w.mirror, cfg["branch"]
    old = rev(repo, f"refs/heads/{b}")
    open(w.old, "w").write(old + "\n")
    open(w.remote, "w").write(cfg["remote"] + "\n")
    gits(repo, "update-ref", ANCHOR, old)
    pm, _n = rules.path_map(all_history_paths(repo, old))
    scr = rules.text_scrubber(pm)
    ob = Objects(repo)
    cmap, cache, ghosts, prev = {}, {}, {}, {}
    idx = os.path.join(w.dir, "sim-index")
    for c in gits(repo, "rev-list", "--reverse", "--topo-order", old).split():
        entries = {}
        cur = {}
        for mode, typ, sha, p in ls_tree(repo, c):
            q = pm.get(p, p)
            if typ == "blob" and mode in ("100644", "100755"):
                k = (sha, rules.class_key(q))
                if k not in cache:
                    nd, kind = rules.transform_blob(q, ob.get(sha), scr)
                    cache[k] = gits(repo, "hash-object", "-w", "--stdin", input=nd).strip() if kind else sha
                sha = cache[k]
            entries[q] = (mode, sha)
            cur[p] = (q, mode, sha)
        if resurrect:
            for p, (q, mode, sha) in prev.items():
                if p not in cur and p != q:
                    ghosts[q] = (mode, sha)
            for q, v in ghosts.items():
                entries.setdefault(q, v)
        prev = cur
        env = _env({"GIT_INDEX_FILE": idx})
        gitb(repo, "read-tree", "--empty", env=env)
        info = b"".join(_enc(f"{m} {s}\t{q}") + b"\0" for q, (m, s) in sorted(entries.items()))
        if info:
            gitb(repo, "update-index", "-z", "--index-info", input=info, env=env)
        tree = gits(repo, "write-tree", env=env).strip()
        parents = gits(repo, "rev-list", "--parents", "-n1", c).split()[1:]
        meta = gits(repo, "log", "-1", "--date=raw", "--format=%an%x00%ae%x00%ad%x00%cn%x00%ce%x00%cd", c).rstrip("\n")
        an, ae, ad, cn, ce, cd = meta.split("\0")
        msg = _dec(commit_message(ob.get(c)))
        if skip_msg_scrub != c:
            msg = scr.scrub(msg, "message")
        args = ["commit-tree", tree]
        for p in parents:
            args += ["-p", cmap[p]]
        cenv = _env({"GIT_AUTHOR_NAME": an, "GIT_AUTHOR_EMAIL": ae, "GIT_AUTHOR_DATE": ad, "GIT_COMMITTER_NAME": cn,
                     "GIT_COMMITTER_EMAIL": ce, "GIT_COMMITTER_DATE": cd})
        cmap[c] = gits(repo, *args, "-F", "-", input=_enc(msg), env=cenv).strip()
    ob.close()
    if os.path.exists(idx):
        os.remove(idx)
    gits(repo, "update-ref", f"refs/heads/{b}", cmap[old])
    write_map(w.map2, cmap)
    write_map(w.map, cmap)
    run(["git", "-C", repo, "remote", "remove", "origin"], check=False)
    return old, cmap


def selftest():
    fails = []

    def check(label, ok, extra=""):
        print(("  ok: " if ok else "  NG: ") + label + (f" ({extra})" if extra and not ok else ""))
        if not ok:
            fails.append(label)

    quiet = lambda *_a, **_k: None  # noqa: E731
    _fx_env()
    with tempfile.TemporaryDirectory() as td:
        tmp = os.path.realpath(td)
        crypt_py = os.path.join(tmp, "fakecrypt.py")
        open(crypt_py, "w").write(FAKE_CRYPT)
        remote, src, cfg_d = _fx(tmp, crypt_py)
        cfg = _write_cfg(tmp, cfg_d)
        R = Rules(cfg)
        scr = R.text_scrubber({"people/QZX31415/notes.md": "people/s-a/notes.md"})
        scr0 = R.text_scrubber({})

        # --- 識別子・氏名・守る語 (純粋な部分)
        t = "Alice Quuxley, QUUXLEY Alice, quuxley_alice, 架空 花子, 架　空花子, Quuxley's Handbook, Quuxley alone"
        s = scr.scrub(t, "content", "x.md")
        check("氏名: 姓名・名姓・区切り (空白 / カンマ / 下線) と漢字の間の空白をどれも置き換える",
              s.count("<NAME>") == 5, s)
        check("守る語 (教科書の著者名など) は置き換えない", "Quuxley's Handbook" in s)
        check("姓だけは置き換えない (同じ姓の別人を巻き込まない)", "Quuxley alone" in s)
        s2 = scr0.scrub("QZX31415 qzx31415 abc16180 fed27182 abc1234 QZX314159", "message")
        check("識別子: 形 (大文字小文字を問わず) と既知の一覧を置き換える",
              s2.split()[:2] == ["<ID>", "<ID>"] and s2.split()[3] == "<ID>", s2)
        check("旧 path の dir 名 (英数字の識別子) は message で新しい名前に写る",
              scr.scrub("dir QZX31415 here", "message") == "dir s-a here")
        check("git の短い hash の形 (16 進の小文字だけ) は形から外す", "abc16180" in s2 and "abc1234" in s2)
        check("既知の一覧に在るものは 16 進に見えても置き換える", "fed27182" not in s2)
        Rd = Rules(dict(cfg, id_shape=r"\d{7,}", id_shape_verify=None))
        s3 = Rd.text_scrubber({}).scrub("受付番号1234567890 と 7654321 と abc1234 と 1a2b3c4d", "message")
        check("数字だけの token (番号) は 16 進に当たっても形から外さない (消し残さない)",
              "1234567890" not in s3 and "7654321" not in s3 and "abc1234" in s3 and "1a2b3c4d" in s3, s3)
        check("形の境界: 長い英数字の列の一部は識別子と見なさない", "QZX314159" in s2)
        r = scr.residual("see people/s-a/notes.md and notes.md", "content", "a.md")
        check("残りの検査: 新しい path の中の旧 token は数えない", "OLD" not in r, r)
        check("残りの検査: 旧 path は数える", scr.residual("see people/QZX31415/notes.md", "message").count("OLD") == 1)
        check("姓の走査は置き換えの一覧と独立 (台帳だけの姓も当たる)", R.surname_tokens("the Zorblatt file") == ["zorblatt"])
        pairs, skipped, _c = ref_pairs({"a/zorpish/x.md": "a/s-001/x.md", "b/2026-05-foo-qzx31415.md": "b/2026-05-foo.md"})
        check("旧 token: 文字だけの 1 語 (dir 名) は自動では置き換えない", "zorpish" in skipped and "zorpish" not in pairs)
        check("旧 token: 数字や記号を含む basename は置き換える", pairs.get("2026-05-foo-qzx31415.md") == "2026-05-foo.md")
        try:
            Rules(dict(cfg, path_rules=[{"re": r"-[ab]\.md$", "to": ".md"}])).path_map(["x-a.md", "x-b.md"])
            check("path の衝突で止まる", False)
        except Stop:
            check("path の衝突 (2 つの旧 path が同じ新 path) で止まる", True)
        cmds = batch_commands("/r", [["o" * 300 + str(i), "n" * 300 + str(i)] for i in range(10)], "/m", 2400)
        check("commit の束: 1 本 ≤ 2400 byte、 改名の旧と新を分けない",
              all(len(c.encode()) <= 2400 for c in cmds) and len(cmds) > 1
              and all(c.count("o" * 300) == c.count("n" * 300) for c in cmds))
        check("構文: JSON が壊れたら broken", check_syntax("a.json", b'{"a": 1}', b'{"a" 1}') == "broken")
        check("構文: key が変わったら keys-changed", check_syntax("a.json", b'{"a": 1}', b'{"b": 1}') == "keys-changed")
        check("構文: py が壊れたら broken", check_syntax("a.py", b"x = 1\n", b"x = = 1\n") == "broken")
        check("構文: sh が壊れたら broken", check_syntax("a.sh", b"echo hi\n", b"if then\n") == "broken")
        check("構文: 元から通らない file は判定しない", check_syntax("a.json", b"{", b"{{").startswith("skip"))
        try:
            import yaml  # noqa: F401,PLC0415
            check("構文: YAML が壊れたら broken", check_syntax("a.yaml", b"a: 1\n", b"a: [1\n") == "broken")
        except ImportError:
            print("  skip: PyYAML が無い (YAML の構文検査は判定しない)")
        for bad in ({"literal": "", "to": "x"}, {"re": "a*", "to": "x"}):
            try:
                compile_rule(bad, "t")
                check("空に当たる規則を拒む", False)
            except Stop:
                check(f"空に当たる規則を拒む ({list(bad)[0]})", True)
        try:
            json.dump({"ids": []}, open(os.path.join(src, "ident-in-repo.json"), "w"))
            Rules(dict(cfg, identity_file=os.path.join(src, "ident-in-repo.json")))
            check("identity_file が repo の中なら止まる", False)
        except Stop:
            check("identity_file が git の work tree の中なら止まる", True)
        finally:
            os.remove(os.path.join(src, "ident-in-repo.json"))
        fm = os.path.join(cfg["work"], "foreign.git")
        os.makedirs(cfg["work"], exist_ok=True)
        run(["git", "init", "-q", "--bare", fm])
        open(os.path.join(cfg["work"], "foreign.commit-map"), "w").write("old new\n")
        try:
            cmd_rehearse(dict(cfg, name="foreign"), out=quiet)
            check("rehearse: 印の無い mirror が在れば消さずに止まる", False, "止まらなかった")
        except Stop as e:
            check("rehearse: 同じ work・同じ name に印の無い mirror が在れば消さずに止まる (別の道具の結果を守る)",
                  ANCHOR in str(e) and os.path.isdir(fm) and os.path.isfile(os.path.join(cfg["work"], "foreign.commit-map")),
                  str(e)[:120])

        # --- plan-current (今の tree を先に)
        out = []
        rc = cmd_plan_current(dict(cfg, path_rules=cfg["path_rules"][1:]), out=out.append)
        check("plan-current: 今の path が番号に落ちるなら止まる (明示の規則を求める)",
              rc == 2 and any("番号" in x for x in out), " / ".join(out))
        out = []
        rc = cmd_plan_current(cfg, out=out.append)
        check("plan-current: dry-run は書かない", rc == 0 and not gits(src, "status", "--porcelain").strip(), " / ".join(out))
        check("plan-current: JSON の key が変わる file を警告する", any("key の集合" in x for x in out), " / ".join(out))
        msgf = os.path.join(tmp, "msg.txt")
        open(msgf, "w").write("neutral paths and plaintext\n")
        open(os.path.join(src, "people/QZX31415/notes.md"), "a").write("dirty\n")
        try:
            cmd_plan_current(cfg, apply=True, message_file=msgf, out=quiet)
            check("plan-current --apply: 未 commit の変更があれば止まる", False)
        except Stop:
            check("plan-current --apply: 置き換える path に未 commit の変更があれば止まる", True)
        gits(src, "checkout", "--", "people/QZX31415/notes.md")
        out = []
        rc = cmd_plan_current(cfg, apply=True, message_file=msgf, out=out.append)
        cmds = [x for x in out if x.startswith("git -C ")]
        for c in cmds:
            run(shlex.split(c))
        check("plan-current --apply: 印字した command で commit でき、 tree が片付く",
              rc == 0 and cmds and not gits(src, "status", "--porcelain").strip(), " / ".join(out))
        r2, e2, s2_ = plan_current(cfg)
        check("plan-current: commit の後は計画が空", not r2 and not e2 and not s2_, f"{len(r2)} {len(e2)} {s2_}")
        gits(src, "push", "-q", "origin", "main")

        # --- 書き換え (plumbing で模す) → verify
        old, cmap = _sim_rewrite(cfg)
        out = []
        ok = cmd_verify(cfg, report=True, out=out.append)
        check("verify: 規則どおりの書き換えは PASS", ok, " | ".join(out))
        w = Work(cfg)
        check("今の tree を先に直すと、 書き換えで先頭の tree が変わらない",
              rev(w.mirror, "refs/heads/main^{tree}") == rev(w.mirror, old + "^{tree}"))
        check("verify (3): 先頭で規則が変える path = 0", any("head paths the rules change = 0" in x for x in out))
        allp = all_history_paths(w.mirror, "refs/heads/main")
        check("書き換え後の履歴に旧 path が無い (履歴にしか無い識別子の path は番号に)",
              not any("QZX31415" in p or "QZX99001" in p for p in allp) and any(p.startswith("gone/s") for p in allp))
        msgs = gits(w.mirror, "log", "--format=%B", "refs/heads/main")
        check("message: 識別子・氏名・規則 (ticket) を置き換え、 hash の形は残す",
              "QZX31415" not in msgs and "Alice Quuxley" not in msgs and "ticket-x" in msgs and "abc16180" in msgs)
        obm = Objects(w.mirror)
        check("暗号化し直し: 平文だった版が暗号文に (履歴の secret/ に平文が無い)",
              all((obm.get(f"{c}:secret/list.txt") or ENC_MAGIC).startswith(ENC_MAGIC)
                  for c in gits(w.mirror, "rev-list", "refs/heads/main").split()))
        obm.close()
        vj = json.load(open(w.vjson))
        check("verify の記録 (PASS・新旧の先頭・設定の指紋)", vj["result"] == "PASS" and vj["old"] == old)

        # --- 負の試験 (verify が捕まえるか)
        def verify_fails(label, cfg_x, want, **kw):
            _sim_rewrite(cfg_x, **kw)
            out_x = []
            okx = cmd_verify(cfg_x, out=out_x.append)
            check(label, (not okx) and any(want in x for x in out_x if x.startswith("RESULT")), " | ".join(out_x[-3:]))
        # 改名の前の履歴 (今の tree を直す前) で、 file-info-callback 式の改名の欠陥 (削除が旧名のまま) を模す
        os.makedirs(os.path.join(tmp, "b"))
        remote_b, src_b, cfg_db = _fx(os.path.join(tmp, "b"), crypt_py)
        cfg_b = _write_cfg(os.path.join(tmp, "b"), cfg_db)
        _sim_rewrite(cfg_b)
        okb = cmd_verify(cfg_b, out=quiet)
        check("verify: 今の tree を直す前の履歴でも、 規則どおりなら PASS (先頭の差は改名と中身だけ)", okb)
        gits(src_b, "rm", "-q", "people/QZX31415/notes.md")
        gits(src_b, "commit", "-q", "-m", "remove the notes")
        gits(src_b, "push", "-q", "origin", "main")
        verify_fails("verify: 改名した file の削除が旧名のまま (復活) を捕まえる", cfg_b, "per-commit tree", resurrect=True)
        verify_fails("verify: message に残った識別子を捕まえる", cfg_b, "residual",
                     skip_msg_scrub=rev(src_b, "HEAD~4") or None)
        cfg_c = _write_cfg(os.path.join(tmp, "b"), dict(cfg_db, reviewed_paths=[]), "cfg-c.json")
        verify_fails("verify: 判定していない姓の path を捕まえる (姓の一覧 = 置き換えと独立)", cfg_c, "surname")
        cfg_s = _write_cfg(os.path.join(tmp, "b"), dict(cfg_db, content_rules=cfg_db["content_rules"] + [
            {"literal": '": ', "to": '" ', "paths": r"\.json$"}]), "cfg-s.json")
        verify_fails("verify: 置き換えで壊れた JSON を捕まえる (code が読む file)", cfg_s, "syntax")

        # --- refs
        other = os.path.join(tmp, "other")
        run(["git", "init", "-q", "-b", "main", other])
        _fx_commit(other, {"index.md": "see people/QZX31415/notes.md and quuxley-mtg.md\n"}, "o1")
        open(os.path.join(other, "scratch.md"), "w").write("people/QZX31415/notes.md\n")
        out = []
        cmd_refs(cfg_b, root=tmp, only="other", out=out.append)
        check("refs: dry-run は他の repo の参照を数える (書かない)",
              any("箇所 3" in x for x in out) and "QZX31415" in open(os.path.join(other, "index.md")).read(),
              " / ".join(out))
        out = []
        cmd_refs(cfg_b, root=tmp, only="other", apply=True, message_file=msgf, out=out.append)
        for c in [x for x in out if x.startswith("git -C ")]:
            run(shlex.split(c))
        body = open(os.path.join(other, "index.md")).read()
        check("refs --apply: 追跡 file を置き換え、 未追跡 file は書かない",
              "people/s-a/notes.md" in body and "and mtg.md" in body and "QZX31415" not in body
              and "QZX31415" in open(os.path.join(other, "scratch.md")).read(), body)

        # --- push-command / after-push (合成の remote に対してだけ)
        _sim_rewrite(cfg_b)
        cmd_verify(cfg_b, report=True, out=quiet)
        w = Work(cfg_b)
        old_b, new_b = w.old_sha(), rev(w.mirror, "refs/heads/main")
        gitb(remote_b, "update-ref", "refs/heads/dependabot/x", old_b)
        gitb(remote_b, "update-ref", "refs/pull/1/head", rev(remote_b, "main~1"))
        run(["git", "-C", w.mirror, "fetch", "-q", remote_b, "+refs/heads/dependabot/*:refs/heads/dependabot/*",
             "+refs/pull/*:refs/pull/*"])
        out = []
        rc = cmd_push_command(cfg_b, out=out.append)
        pcmd = [x for x in out if " push --force-with-lease=" in x]
        check("push-command: URL と refs/heads/main:refs/heads/main を明示した lease の push を印字",
              rc == 0 and len(pcmd) == 1 and f"--force-with-lease=refs/heads/main:{old_b}" in pcmd[0]
              and pcmd[0].endswith("refs/heads/main:refs/heads/main"), " / ".join(out))
        check("push-command: 他の ref が旧履歴を抱えることを先に言う", any("他の ref" in x for x in out))
        bcmd = [x for x in out if " bundle create " in x]
        run(shlex.split(bcmd[0]))
        check("push-command: 控えの bundle に旧先頭が入る",
              old_b in gits(w.mirror, "bundle", "list-heads", w.bundle))
        run(shlex.split(pcmd[0]))
        check("印字した push で remote の main が新しい先頭に", rev(remote_b, "refs/heads/main") == new_b)
        out = []
        rc = cmd_push_command(cfg_b, out=out.append)
        check("push-command: remote が動いていたら止まり、 やり直しの 1 行を出す",
              rc == 1 and any("rehearse --config" in x for x in out), " / ".join(out))
        out = []
        rc = cmd_after_push(cfg_b, out=out.append)
        check("after-push: main = 新しい先頭、 旧履歴を抱える branch と PR の ref を列挙し扱いを出す",
              rc == 0 and any("OLD refs/heads/dependabot/x" in x for x in out)
              and any("OLD refs/pull/1/head" in x and "support" in x for x in out), " / ".join(out))
        check("after-push: 共同作業者の clone に触れる", any("共同作業者" in x for x in out))
        json.dump(dict(json.load(open(w.vjson)), config="x"), open(w.vjson, "w"))
        out = []
        check("push-command: 検証の後に設定が変わったら止まる", cmd_push_command(cfg_b, out=out.append) == 1)
    print(f"selftest: {'FAILED ' + str(len(fails)) if fails else 'ALL PASS'}")
    return 1 if fails else 0


def selftest_rewrite():
    """filter-repo を通す経路 (本人の terminal で、 合成の repo だけを書き換える)。"""
    fr = filter_repo_bin()
    if not fr:
        print("SKIP: git-filter-repo が無い")
        return 0
    fails = []

    def check(label, ok, extra=""):
        print(("  ok: " if ok else "  NG: ") + label + (f" ({extra})" if extra and not ok else ""))
        if not ok:
            fails.append(label)
    _fx_env()
    with tempfile.TemporaryDirectory() as td:
        tmp = os.path.realpath(td)
        crypt_py = os.path.join(tmp, "fakecrypt.py")
        open(crypt_py, "w").write(FAKE_CRYPT)
        remote, src, cfg_d = _fx(tmp, crypt_py)
        gits(src, "rm", "-q", "people/QZX31415/notes.md")
        gits(src, "commit", "-q", "-m", "remove the notes")
        gits(src, "push", "-q", "origin", "main")
        cfg = _write_cfg(tmp, cfg_d)
        out = []
        rc = cmd_rehearse(cfg, out=out.append)
        check("rehearse (filter-repo 2 pass) → verify PASS", rc == 0, " | ".join(out[-12:]))
        w = Work(cfg)
        check("対応表: pass 1 と pass 2 と 元 → 最終", all(os.path.isfile(f) for f in (w.map1, w.map2, w.map)))
        m = load_map(w.map)
        check("filter-repo は 2 回目の表を合成する (pass 2 の鍵 = 元の commit)", set(load_map(w.map2)) == set(m))
        check("旧世代にしか無い blob の一覧を書く", os.path.getsize(w.forbidden) > 0)
        check("mirror の origin を外す (素の push を不可能に)", not gits(w.mirror, "remote").strip())
        head = {p for _m, _t, _s, p in ls_tree(w.mirror, "refs/heads/main")}
        check("--filename-callback の改名は削除も写す = 消した file が復活しない", not any(p.startswith("people/") for p in head),
              str(sorted(head)))
        # 教訓の再現 (filter-repo の挙動の記録。 変わっていても FAIL にしない)
        env = _env({"PATH": str(Path(fr).parent) + os.pathsep + os.environ.get("PATH", "")})
        lesson = os.path.join(tmp, "lesson.git")
        run(["git", "clone", "-q", "--mirror", remote, lesson])
        r = run(["git", "-C", lesson, "filter-repo", "--force", "--quiet", "--filename-callback", "return filename",
                 "--file-info-callback", "return (filename, mode, blob_id)"], env=env, check=False)
        print(f"  info: filename-callback と file-info-callback の同時指定 → exit {r.returncode}"
              f" ({'拒まれる = 2 pass が要る' if r.returncode else '受け付けた = filter-repo が変わった'})")
        body = ("return (filename.replace(b'people/QZX31415/', b'people/s-a/'), mode, blob_id)")
        r = run(["git", "-C", lesson, "filter-repo", "--force", "--quiet", "--refs", "refs/heads/main",
                 "--file-info-callback", body], env=env, check=False)
        head2 = {p for _m, _t, _s, p in ls_tree(lesson, "refs/heads/main")}
        print(f"  info: file-info-callback で改名すると削除が旧名のまま → 消した file が"
              f" {'復活した (教訓どおり)' if any(p.startswith('people/s-a/') for p in head2) else '復活しない (filter-repo が変わった?)'}")
    print(f"selftest-rewrite: {'FAILED ' + str(len(fails)) if fails else 'ALL PASS'}")
    return 1 if fails else 0


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--selftest-rewrite", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("rehearse", "verify", "plan-current", "refs", "push-command", "after-push"):
        p = sub.add_parser(name)
        p.add_argument("--config", required=True)
        if name == "rehearse":
            p.add_argument("--message-diff")
        if name in ("verify", "refs"):
            p.add_argument("--show", action="store_true")
        if name == "verify":
            p.add_argument("--report")
        if name in ("plan-current", "refs"):
            p.add_argument("--apply", action="store_true")
            p.add_argument("--message-file")
        if name == "plan-current":
            p.add_argument("--repo")
            p.add_argument("--list", action="store_true")
        if name == "refs":
            p.add_argument("--root")
            p.add_argument("--repo")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.selftest_rewrite:
        return selftest_rewrite()
    if not a.cmd:
        ap.print_help()
        return 2
    try:
        cfg = load_config(a.config)
        if a.cmd == "rehearse":
            return cmd_rehearse(cfg, message_diff=a.message_diff)
        if a.cmd == "verify":
            return 0 if cmd_verify(cfg, show=a.show, report_file=a.report) else 1
        if a.cmd == "plan-current":
            return cmd_plan_current(cfg, apply=a.apply, message_file=a.message_file, repo=a.repo, listing=a.list)
        if a.cmd == "refs":
            return cmd_refs(cfg, root=a.root, only=a.repo, apply=a.apply, message_file=a.message_file, show=a.show)
        if a.cmd == "push-command":
            return cmd_push_command(cfg)
        if a.cmd == "after-push":
            return cmd_after_push(cfg)
    except Stop as e:
        print(f"STOP: {e}", file=sys.stderr)
        return e.code
    return 2


if __name__ == "__main__":
    sys.exit(main())
