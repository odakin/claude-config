#!/usr/bin/env python3
"""YAML の file の top-level の key を、 行頭で見つけて置き換える・消す (ほかの key は 1 文字も変えず、 読み直して確かめてから書く)。

なぜ要るか: 台帳 (TODO の 1 entry 1 file など) を閉じるとき、 status や status_context を書き換えるのに
`s.index("ask:")` のような文字列探しを使うと、 `task:` の末尾に一致して間の field をまとめて消す (実測 2 回 =
conventions/batch-text-edits.md の先頭の側の罠)。 YAML を load → dump し直すと comment・引用・block scalar の形が崩れる。
ここでは text のまま、 **行頭から始まる** `key:` の行とそれに続く字下げ行 (block scalar・list) をひとまとまりとして扱い、
置き換えた後に YAML として読み直して「指定した key だけが変わり、 ほかの key の値はすべて同じ」 を確かめてから書く。
確かめられなければ何も書かずに exit 1。

使い方:
    python3 yaml-set-top-keys.py <file.yaml> --set status=完了 --set status_context="…" --drop ask --drop ask_default \\
        [--after asked] [--comment status="2026-10-12: …"] [--dry-run]
    python3 yaml-set-top-keys.py --selftest
    --set key=value   値は YAML の二重引用の文字列として書く (改行は \\n で入る)。 key が無ければ足す (--after <key> の直後、 無ければ末尾)
                      ⚠️ 値を自分で引用符に包まない = 引用符は道具が付ける。 shell で `'key="…"'` と書くと値の両端に " が残り、
                      file には `\"…\"` が入る (実測 2 回)。 両端が " の値は止める (本当にその値なら --allow-quoted-value)
                      ⚠️ `--set flag=false` は `flag: "false"` (文字列) になり、 読み手が bool() で読むと真になる (実測 2 回以上)
                      = 値が真偽・null に読める形 (true/false/yes/no/null/~ など) なら止める。 本当に文字列なら --allow-bool-string。
                      `#` で始まる値 (YAML では comment = null) は文字列として通す (引用して書くので comment にならない)
                      ⚠️ list の key には使わない (1 本の文字列になる) = その key は text で 1 行足して、 読み直して他の key が不変かを確かめる
    --set-literal key=value  値を真偽・null・数として引用なしで書く (`--set-literal waiting_party=false`)。 文字列になる値と `#` で始まる値は止める
    --comment key=text  --set した行の末尾に「   # text」 を付ける
    --drop key        その key をまとまりごと消す (無ければ何もしない)
    --dry-run         書かずに差分だけ出す
⚠️ top-level だけを扱う (入れ子の key は対象外)。 file 全体が mapping でなければ止める。 git-crypt の file は worktree の平文を読む。
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import tempfile
from pathlib import Path

import yaml

_SAFE_LOADER = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)


def _yaml_safe_load(text):
    return yaml.load(text, Loader=_SAFE_LOADER)


def blocks(lines: list[str]) -> list[tuple[str | None, int, int]]:
    """top-level の key ごとの (key, 開始行, 終了行の次) を返す。 key の前の空行・comment 行は key=None の塊。"""
    out: list[tuple[str | None, int, int]] = []
    i = 0
    while i < len(lines):
        m = re.match(r"([A-Za-z_][\w-]*):(\s|$)", lines[i])
        if m:
            j = i + 1
            while j < len(lines) and (lines[j].startswith((" ", "\t", "- ")) or lines[j].strip() == "" and
                                      j + 1 < len(lines) and lines[j + 1].startswith((" ", "\t"))):
                j += 1
            out.append((m.group(1), i, j))
            i = j
        else:
            out.append((None, i, i + 1))
            i += 1
    return out


def quote(v) -> str:
    if isinstance(v, bool):  # --set-literal の値 (bool は int の部分型なので先に見る)
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return repr(v)
    return json.dumps(v, ensure_ascii=False)  # JSON の文字列は YAML の二重引用の文字列として読める


def edit(text: str, sets: dict[str, str], drops: list[str], after: str | None, comments: dict[str, str]) -> str:
    lines = text.split("\n")
    bl = blocks(lines)
    keys = [k for k, _, _ in bl if k]
    dup = {k for k in keys if keys.count(k) > 1}
    if dup:
        raise SystemExit(f"❌ top-level の key が重複している: {sorted(dup)}")
    new: list[str] = []
    done = set()
    for k, a, b in bl:
        if k in drops:
            continue
        if k in sets:
            c = f"   # {comments[k]}" if k in comments else ""
            new.append(f"{k}: {quote(sets[k])}{c}")
            done.add(k)
        else:
            new.extend(lines[a:b])
        if after is not None and k == after:  # after 無しで None (空行・comment の塊) に一致させない
            for nk, nv in sets.items():
                if nk not in keys and nk not in done:
                    c = f"   # {comments[nk]}" if nk in comments else ""
                    new.append(f"{nk}: {quote(nv)}{c}")
                    done.add(nk)
    tail = "" if new and new[-1] == "" else None
    if tail is not None:
        new.pop()
    for nk, nv in sets.items():
        if nk not in done:
            c = f"   # {comments[nk]}" if nk in comments else ""
            new.append(f"{nk}: {quote(nv)}{c}")
    if tail is not None:
        new.append("")
    return "\n".join(new)


def verify(before: str, after_text: str, sets: dict[str, str], drops: list[str]) -> list[str]:
    a, b = _yaml_safe_load(before), _yaml_safe_load(after_text)
    if not isinstance(a, dict) or not isinstance(b, dict):
        return ["file 全体が mapping でない"]
    errs = []
    for k in set(a) | set(b):
        if k in sets:
            if b.get(k) != sets[k]:
                errs.append(f"{k}: 置き換えた値が読み直しと合わない ({b.get(k)!r})")
        elif k in drops:
            if k in b:
                errs.append(f"{k}: 消したはずが残っている")
        elif a.get(k) != b.get(k) or (k in a) != (k in b):
            errs.append(f"{k}: 触っていない key の値が変わった")
    return errs


def selftest() -> int:
    src = ('id: "x"\ntask: |\n  一行目 ask: これは本文\n  二行目\nstatus: 待ち   # 旧\nstatus_context: "前"\n'
           'ask: "問い"\nask_default: "推し"\nasked: "2030-01-02"\ncross_ref:\n  - "a"\n  - "b"\n')
    sets = {"status": "完了", "status_context": "閉じた", "decided": "2030-01-03 本人「OK」"}
    out = edit(src, sets, ["ask", "ask_default"], "status_context", {"status": "2030-01-03"})
    assert verify(src, out, sets, ["ask", "ask_default"]) == [], verify(src, out, sets, ["ask", "ask_default"])
    d = _yaml_safe_load(out)
    assert d["task"] == "一行目 ask: これは本文\n二行目\n" and d["cross_ref"] == ["a", "b"], d
    assert "status: \"完了\"   # 2030-01-03" in out and list(d).index("decided") == list(d).index("status_context") + 1, out
    assert "ask" not in d and "ask_default" not in d and d["asked"] == "2030-01-02", d
    # 素朴な文字列探しは task: の中を指す = この道具はそれをしない (task の本文は残る)
    assert src.index("ask:") < src.index("status:") and d["task"].startswith("一行目")
    # 確かめ: 触っていない key が変わったら verify が拾う
    assert verify(src, src.replace('asked: "2030-01-02"', 'asked: "2030-01-09"'), {}, []) == \
        ["asked: 触っていない key の値が変わった"]
    # --after 無しで無い key を足す = 末尾に足し、 末尾の改行を保つ (空行・comment の塊の後ろに入れない。
    # 実測 = 空行の塊に一致して、 最後の改行の手前に足し file 末尾の改行が消えた)
    src2 = '# 頭の comment\nid: "x"\nnotes: |\n  a\n'
    out2 = edit(src2, {"updated": "X"}, [], None, {})
    assert out2 == src2 + 'updated: "X"\n', repr(out2)
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "t.yaml"
        p.write_text(src, encoding="utf-8")
        assert main([str(p), "--set", "status=完了", "--drop", "ask"]) == 0
        assert _yaml_safe_load(p.read_text(encoding="utf-8"))["status"] == "完了"
        # 値を自分で引用符に包んだ形 (shell の '…' の中の "…") は止める = file に \"…\" が入るのを防ぐ (実測 2 回)
        before = p.read_text(encoding="utf-8")
        try:
            main([str(p), "--set", 'status_context="閉じた"'])
            raise AssertionError("両端が \" の値を止めなかった")
        except SystemExit as e:
            assert "引用符は道具が付ける" in str(e), e
        assert p.read_text(encoding="utf-8") == before
        assert main([str(p), "--set", 'status_context="閉じた"', "--allow-quoted-value"]) == 0
        assert _yaml_safe_load(p.read_text(encoding="utf-8"))["status_context"] == '"閉じた"'
        # 真偽値・null を --set に渡すと文字列 "false" になり読み手の bool() で真 = 止める (実測 2 回以上)
        before = p.read_text(encoding="utf-8")
        for bad in ("waiting_party=false", "flag=True", "x=null", "y=~", "z=no"):
            try:
                main([str(p), "--set", bad])
                raise AssertionError(f"{bad} を止めなかった")
            except SystemExit as e:
                assert "--set-literal" in str(e), e
        assert p.read_text(encoding="utf-8") == before
        assert main([str(p), "--set", "deadline=2030-01-05", "--set", "count=3", "--set", "memo=[未定 {x"]) == 0  # 日付・数字・YAML で読めない文字列は従来どおり
        d = _yaml_safe_load(p.read_text(encoding="utf-8"))
        assert d["deadline"] == "2030-01-05" and d["count"] == "3" and d["memo"] == "[未定 {x", d
        assert main([str(p), "--set-literal", "waiting_party=false", "--comment", "waiting_party=返事は不要"]) == 0
        t = p.read_text(encoding="utf-8")
        assert "waiting_party: false   # 返事は不要" in t and _yaml_safe_load(t)["waiting_party"] is False, t
        try:
            main([str(p), "--comment", "deadline=値を変えない注釈"])
            raise AssertionError("--set の無い --comment が通った")
        except SystemExit as e:
            assert "--comment" in str(e), e
        assert p.read_text(encoding="utf-8") == t
        for bad in ("w=完了", "w=[a]", "w=[未定", "w=#3 を相談する"):
            try:
                main([str(p), "--set-literal", bad])
                raise AssertionError(f"--set-literal {bad} を止めなかった")
            except SystemExit as e:
                assert "--set で渡す" in str(e), e
        assert main([str(p), "--set", "flag=false", "--allow-bool-string"]) == 0
        assert _yaml_safe_load(p.read_text(encoding="utf-8"))["flag"] == "false"
        assert main([str(p), "--set", "note=#3 を相談する"]) == 0  # # で始まる値は null でなく文字列 (引用して書く)
        assert _yaml_safe_load(p.read_text(encoding="utf-8"))["note"] == "#3 を相談する"
    print("yaml-set-top-keys selftest: ALL PASS (行頭の key だけを置き換え・本文の中の同じ語は触らない・ほかの key は不変を確かめる)")
    return 0


def kv(items: list[str] | None, allow_quoted: bool = True, allow_bool_string: bool = True) -> dict[str, str]:
    out = {}
    for it in items or []:
        k, sep, v = it.partition("=")
        if not sep or not re.fullmatch(r"[A-Za-z_][\w-]*", k):
            raise SystemExit(f"❌ key=value の形でない: {it!r}")
        if not allow_quoted and len(v) >= 2 and v[0] == v[-1] == '"':
            raise SystemExit(f"❌ {k} の値の両端に \" がある = 引用符は道具が付ける。 外して渡す "
                             f"(shell の '…' の中に \"…\" を書かない)。 本当に両端が \" の値なら --allow-quoted-value")
        if not allow_bool_string and v.strip() and _reads_as_bool_or_null(v):
            raise SystemExit(f"❌ {k}={v} は --set だと文字列 \"{v}\" になる (読み手の bool() では \"false\" も真)。 "
                             f"真偽値・null として書くなら --set-literal {k}={v}、 本当に文字列なら --allow-bool-string")
        out[k] = v
    return out


def _reads_as_bool_or_null(v: str) -> bool:
    if v.lstrip().startswith("#"):  # YAML は comment として null に読むが、 --set は引用して書くので文字列 (実測: 項目番号で始まる値 「#N …」 を null と誤判定し、 勧める --set-literal では値が null で書かれる)
        return False
    try:
        val = _yaml_safe_load(v)
    except yaml.YAMLError:  # 「[未定」 のように YAML として読めない文字列は文字列のまま書く
        return False
    return val is None or isinstance(val, bool)


def literals(items: list[str] | None) -> dict[str, object]:
    """--set-literal: 値を YAML の真偽・null・数として読み、 引用なしで書く (文字列になる値は止める)。"""
    out: dict[str, object] = {}
    for k, v in kv(items).items():
        try:
            val = _yaml_safe_load(v) if v.strip() else None
        except yaml.YAMLError:
            val = v
        if v.lstrip().startswith("#"):  # YAML は comment として null に読む = 黙って null を書くと値が消える (実測)
            val = v
        if isinstance(val, str) or not (val is None or isinstance(val, (bool, int, float))):
            raise SystemExit(f"❌ --set-literal {k}={v} は真偽・null・数でない = 文字列は --set で渡す")
        out[k] = val
    return out


def main(argv: list[str]) -> int:
    if argv[:1] == ["--selftest"]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file")
    ap.add_argument("--set", action="append", dest="sets")
    ap.add_argument("--drop", action="append", default=[])
    ap.add_argument("--after")
    ap.add_argument("--comment", action="append", dest="comments")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--set-literal", action="append", dest="set_literals")
    ap.add_argument("--allow-quoted-value", action="store_true")
    ap.add_argument("--allow-bool-string", action="store_true")
    a = ap.parse_args(argv)
    p = Path(a.file)
    before = p.read_text(encoding="utf-8")
    sets = kv(a.sets, allow_quoted=a.allow_quoted_value, allow_bool_string=a.allow_bool_string)
    lits = literals(a.set_literals)
    if set(sets) & set(lits):
        raise SystemExit(f"❌ 同じ key を --set と --set-literal の両方に渡した: {sorted(set(sets) & set(lits))}")
    sets.update(lits)
    comments = kv(a.comments)
    if set(comments) - set(sets):
        raise SystemExit(f"❌ --comment は --set した行にだけ付く = 黙って捨てない (同じ key の --set も渡す): {sorted(set(comments) - set(sets))}")
    after_text = edit(before, sets, a.drop, a.after, comments)
    errs = verify(before, after_text, sets, a.drop)
    sys.stdout.writelines(difflib.unified_diff(before.splitlines(True), after_text.splitlines(True), str(p), str(p)))
    if errs:
        print("❌ 書かなかった: " + " / ".join(errs))
        return 1
    if not a.dry_run:
        p.write_text(after_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
