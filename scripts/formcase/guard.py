"""凍結出力を守る 2 つの入口: 旧 driver の冒頭 guard と pre-commit の staged guard。

- ``legacy_guard(__file__)``: 案件ごとの旧 driver (gen-pdf-*.py / houkoku-*.py / *.sh) の冒頭で呼ぶ。
  manifest の ``drivers:`` に宣言された group のどれかが凍結なら、 Excel を起こす前に止める。
  manifest の無い dir では何もしない (旧案件の互換)。 宣言されていない driver は止める
  (= その driver が何を書くか manifest が知らない = 凍結出力を上書きしうる)。
- ``staged_findings(repo)``: pre-commit から。 凍結出力の staged 変更・削除 / 凍結 sheet の値の変更 /
  manifest の構造 FAIL を BLOCK 理由として返す。 HEAD の manifest で凍結だった出力は、 staged の
  manifest で状態を書き換えても BLOCK (= 状態の手書き改変で保護を外せない。 作り直しは新しい file 名)。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import check as C
from . import config as CF
from . import manifest as M
from . import specs as S


def find_manifest_dir(start: Path, max_up: int = 3):
    d = Path(start).resolve()
    if d.is_file():
        d = d.parent
    for _ in range(max_up + 1):
        if (d / M.MANIFEST_NAME).exists():
            return d
        if d.parent == d:
            break
        d = d.parent
    return None


def legacy_guard(driver_file, groups=None) -> None:
    """旧 driver 用。 凍結 group を書く driver なら SystemExit(3)。"""
    drv = Path(driver_file).resolve()
    mdir = find_manifest_dir(drv.parent)
    if mdir is None:
        return
    try:
        m = M.load(mdir)
    except M.Locked:
        sys.exit(f"🔴 formcase: {mdir / M.MANIFEST_NAME} が git-crypt locked = 凍結状態を確認できないので止める")
    hits = m.drivers_of(drv.name)
    if not hits:
        sys.exit(f"🔴 formcase: {drv.name} は {mdir.name}/{M.MANIFEST_NAME} の drivers に宣言されていない = "
                 "何を書く driver か分からないので止める。 manifest に宣言するか、 "
                 f"build を使う ({CF.usage_doc()})")
    if groups:
        hits = [(d, g) for d, g in hits if g in groups]
    frozen = []
    for doc_id, gid in hits:
        cur = m.group(doc_id, gid).get("current") or {}
        if cur.get("state") in M.FROZEN_STATES:
            frozen.append(f"{doc_id}/{gid} = {cur.get('state')} {cur.get('date', '')}".strip())
    if frozen:
        sys.exit("🔴 formcase: この driver は凍結済みの group の出力を書く → Excel を起こす前に止めた\n"
                 + "".join(f"   🧊 {x}\n" for x in frozen)
                 + f"   draft の group だけ作る: python3 {CF.cli()} build <case> --doc <doc> --group <group>\n"
                 + "   凍結 group を作り直す (差し戻し等): formcase.py reopen <case> <doc> <group> --reason …")


# ---------------------------------------------------------------------------
# pre-commit
# ---------------------------------------------------------------------------
def _git(repo, *args, check=True) -> bytes:
    r = subprocess.run(["git", "-C", str(repo), "-c", "core.quotepath=off", *args],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace"))
    return r.stdout


def _staged_changes(repo):
    out = _git(repo, "diff", "--cached", "--name-status", "-z", "-M").split(b"\0")
    i, res = 0, []
    while i < len(out) and out[i]:
        st = out[i].decode()
        if st[0] in "RC":
            res.append((st[0], out[i + 1].decode(), out[i + 2].decode()))
            i += 3
        else:
            res.append((st[0], out[i + 1].decode(), None))
            i += 2
    return res


def _manifest_paths(repo, treeish):
    if treeish == ":":
        names = _git(repo, "ls-files", "-z").split(b"\0")
    else:
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "-q", "HEAD"],
                           stdout=subprocess.PIPE)
        if r.returncode != 0:
            return []
        names = _git(repo, "ls-tree", "-r", "-z", "--name-only", "HEAD").split(b"\0")
    return [n.decode() for n in names if n.decode().endswith("/" + M.MANIFEST_NAME)]


def _read(repo, spec) -> bytes:
    return _git(repo, "cat-file", "--filters", spec)


def staged_findings(repo) -> list:
    repo = Path(repo).resolve()
    changes = _staged_changes(repo)
    if not changes:
        return []
    touched = {}
    for st, a, b in changes:
        touched[a] = st
        if b:
            touched[b] = "A"
    blocks = []
    manifests = {}
    for label, treeish in (("HEAD", "HEAD:"), ("staged", ":")):
        for rel in _manifest_paths(repo, treeish.rstrip(":") or ":"):
            try:
                raw = _read(repo, f"{treeish}{rel}")
            except RuntimeError:
                continue
            if raw.startswith(M.GITCRYPT_MAGIC):
                continue
            try:
                m = M.loads(raw.decode("utf-8"), repo / Path(rel).parent)
            except Exception as e:  # noqa: BLE001
                if label == "staged":
                    blocks.append(f"{rel}: manifest が YAML として読めない ({e})")
                continue
            manifests.setdefault(rel, {})[label] = m
    for rel, pair in manifests.items():
        case_rel = str(Path(rel).parent)
        # 1) 凍結出力の staged 変更・削除 (HEAD と staged の両方の manifest で凍結なら対象)
        frozen = {}
        for m in pair.values():
            for ap, info in m.frozen_outputs().items():
                frozen[os.path.relpath(ap, repo)] = info
        for path, st in touched.items():
            if path in frozen and st in ("M", "D", "R", "T"):
                doc, gid, state = frozen[path]
                blocks.append(f"{path}: 凍結出力 ({doc}/{gid} = {state}) を {'削除' if st == 'D' else '変更'}"
                              " しようとしている — 提出物は上書きしない。 作り直すなら formcase.py reopen "
                              "(新しい file 名に書く)")
        sm = pair.get("staged")
        if sm is None:
            continue
        # 2) manifest の構造
        if rel in touched:
            for lv, where, msg in M.validate(sm, S.get, check_files=False):  # file 実在は check が見る
                if lv == M.FAIL:
                    blocks.append(f"{rel}: {where}: {msg}")
        # 3) 凍結 group の sheet の値 (staged の workbook blob で判定)
        for doc_id, doc, gid, g in sm.iter_groups():
            cur = g.get("current") or {}
            fr = cur.get("frozen") or {}
            wb_rel = doc.get("workbook")
            if cur.get("state") not in M.FROZEN_STATES or not M.has_source_digest(fr) or not wb_rel:
                continue
            wb_path = str(Path(case_rel) / wb_rel)
            if touched.get(wb_path) != "M":
                continue
            with tempfile.NamedTemporaryFile(suffix=Path(wb_rel).suffix or ".xlsx", delete=False) as tf:
                tf.write(_read(repo, f":{wb_path}"))
                tmp = tf.name
            try:
                vals, fmts = M.frozen_sheet_changes(fr, tmp)
            finally:
                os.unlink(tmp)
            changed = vals + [f"{s} (書式)" for s in fmts]
            if changed:
                blocks.append(f"{wb_path}: {doc_id}/{gid} は {cur.get('state')} {cur.get('date', '')} で凍結なのに "
                              f"sheet {changed} の値が変わっている — 提出記録の改変 / 旧紙の発生。 意図した訂正なら "
                              f"先に formcase.py reopen {case_rel} {doc_id} {gid} --reason … を同じ commit に")
    return blocks


def repo_toplevel(path=".") -> Path | None:
    r = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 else None


__all__ = ["legacy_guard", "staged_findings", "find_manifest_dir", "repo_toplevel", "C"]
