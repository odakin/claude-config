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
    --set key=value   値は YAML の二重引用の文字列として書く。 改行を含む値は block scalar (`|-` / `|`) で書く (読める形を保つ。
                      block で同じ値に読めない値 = 先頭の行が空白で始まる・行末に空白・tab・改行以外の制御文字・末尾に 2 つ以上の改行、 は
                      二重引用で改行を \\n で書く)。 key が無ければ足す (--after <key> の直後、 無ければ末尾)
                      ⚠️ 値を自分で引用符に包まない = 引用符は道具が付ける。 shell で `'key="…"'` と書くと値の両端に " が残り、
                      file には `\"…\"` が入る (実測 2 回)。 両端が " の値は止める (本当にその値なら --allow-quoted-value)
                      ⚠️ `--set flag=false` は `flag: "false"` (文字列) になり、 読み手が bool() で読むと真になる (実測 2 回以上)
                      = 値が真偽・null に読める形 (true/false/yes/no/null/~ など) なら止める。 本当に文字列なら --allow-bool-string。
                      `#` で始まる値 (YAML では comment = null) は文字列として通す (引用して書くので comment にならない)
                      ⚠️ list の key には使わない (1 本の文字列になる) = その key は text で 1 行足して、 読み直して他の key が不変かを確かめる
    --set-literal key=value  値を真偽・null・数として引用なしで書く (`--set-literal waiting_party=false`)。 文字列になる値と `#` で始まる値は止める
    --comment key=text  --set した行の末尾に「   # text」 を付ける
    --append key=text   文字列の key の末尾に text を改行で足す (notes に段落を 1 つ足すとき)。 値が block scalar (`|`) なら
                      形を保ってその字下げで行を足し、 引用・素の文字列なら「旧い値 + 改行 + text」 の二重引用で書き直す。
                      key が無ければ足す (--set と同じ)。 list・mapping・数の key は止める。 書いた後に読み直し、 足した後の値と
                      ほかの key の不変を確かめる (前は `--set` で丸ごと書き直すと block の notes が 1 行の引用文字列に変わった = 実測 2 回。
                      今は --set も改行を含む値を block で書く)
    --drop key        その key をまとまりごと消す (無ければ何もしない)
    --dry-run         書かずに差分だけ出す (守る key を失う書き方なら「上書きの鍵」 も出す)
    --replaces key=鍵  守る key の今の値を読んだ印 (dry-run が「上書きの鍵」 として見せる 8 桁)。 守る key が 1 つなら `--replaces 鍵` でも可
    --guard key       この呼び出しで守る key を足す (ふだんは下の git 属性で宣言する)
守る key (読んだ印): file の git 属性 `yaml-set-guard` (カンマ区切りの key 名、 例 = 台帳の repo の `.gitattributes` に
    `todo/*.yaml yaml-set-guard=status_context`) か `--guard` で名指した key は、 今の値が空でなく、 その値を失う書き方
    (旧い値を含まない値への --set / --set-literal / --drop) をするとき、 dry-run が見せる鍵 (`--replaces key=<8 桁>`) を求める。
    鍵が無い・読んだ後に値が変わった = 書かずに exit 1 で、 最後の 1 行に今の値を全文出す (出力を `tail -1` に絞っても届く)。
    旧い値を含む値への --set と --append は失うものが無いので鍵は要らない。 渡された鍵は守る key でなくても照合する。
    鍵の式は record-reply.py の現在地の鍵と同じ (前後の空白を除いた値の sha1 の先頭 8 桁) = どちらの dry-run の鍵も通る。
    なぜ: 欄を丸ごと置き換える書き手が自分の記憶から新しい値を作ると、 間に別の書き手が記録した中身が消える (実測 = 案件を持つ
    session が別件で現在地を書き直し、 別の session が記録した相手の返事を消した。 編集の道具の「読んだ後に file が変わった」
    という注記は出ていた)。 一般形 = docs/convention-design-principles.md#overwrite-needs-read-token
⚠️ top-level だけを扱う (入れ子の key は対象外)。 file 全体が mapping でなければ止める。 git-crypt の file は worktree の平文を読む。
"""
from __future__ import annotations

import argparse
import contextlib
import difflib
import hashlib
import io
import json
import os
import re
import subprocess
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


_BLOCK_BAD = re.compile(r"[\t\r\x00-\x08\x0b-\x1f\x7f]")


def block_ok(v) -> bool:
    """改行を含む文字列を block scalar で書けるか (書けば読み直して同じ値になる形だけ)。"""
    if not isinstance(v, str) or "\n" not in v or _BLOCK_BAD.search(v) or v.endswith("\n\n"):
        return False
    body = v[:-1] if v.endswith("\n") else v
    lines = body.split("\n")
    if not lines[0] or lines[0][0] == " " or any(ln != ln.rstrip(" ") for ln in lines):
        return False
    return True


def render(k: str, v, c: str = "") -> list[str]:
    """key の行 (block なら続く字下げの行も)。 改行を含む文字列は block scalar (`|-` = 末尾の改行なし / `|` = 1 つ)、
    それ以外は quote の 1 行。 書いた後の読み直し (verify) が同じ値かを確かめる。"""
    if block_ok(v):
        body = v[:-1] if v.endswith("\n") else v
        return [f"{k}: {'|' if v.endswith(chr(10)) else '|-'}{c}"] + [("  " + ln) if ln else "" for ln in body.split("\n")]
    return [f"{k}: {quote(v)}{c}"]


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
            new.extend(render(k, sets[k], c))
            done.add(k)
        else:
            new.extend(lines[a:b])
        if after is not None and k == after:  # after 無しで None (空行・comment の塊) に一致させない
            for nk, nv in sets.items():
                if nk not in keys and nk not in done:
                    c = f"   # {comments[nk]}" if nk in comments else ""
                    new.extend(render(nk, nv, c))
                    done.add(nk)
    tail = "" if new and new[-1] == "" else None
    if tail is not None:
        new.pop()
    for nk, nv in sets.items():
        if nk not in done:
            c = f"   # {comments[nk]}" if nk in comments else ""
            new.extend(render(nk, nv, c))
    if tail is not None:
        new.append("")
    return "\n".join(new)


def append_values(text: str, appends: dict[str, str]) -> tuple[str, dict[str, str], dict[str, str]]:
    """--append: block scalar の key は text のまま行を足し (戻り値の 1 つめ)、 それ以外は --set に回す値を返す (2 つめ)。
    3 つめ = 足した後に読み直したとき期待する値 (verify に渡す)。"""
    data = _yaml_safe_load(text) if text.strip() else {}
    if not isinstance(data, dict):
        raise SystemExit("❌ file 全体が mapping でない")
    lines = text.split("\n")
    to_set: dict[str, str] = {}
    expect: dict[str, str] = {}
    for k, add in appends.items():
        old = data.get(k)
        if k not in data:
            to_set[k] = expect[k] = add
            continue
        if not isinstance(old, str):
            raise SystemExit(f"❌ --append {k}: 値が文字列でない ({type(old).__name__}) = list は text で 1 行足す")
        span = next(((a, b) for kk, a, b in blocks(lines) if kk == k), None)
        head = lines[span[0]] if span else ""
        if span and re.match(rf"{re.escape(k)}:\s*\|[0-9]*\s*(#.*)?$", head):  # `|` (clip) の block scalar だけ形を保つ
            a, b = span
            while b > a + 1 and lines[b - 1].strip() == "":  # 塊の末尾の空行は block の後ろに残す
                b -= 1
            body = [ln for ln in lines[a + 1:b] if ln.strip()]
            ind = re.match(r"\s*", body[0]).group(0) if body else "  "
            lines[b:b] = [f"{ind}{ln}" if ln else "" for ln in add.split("\n")]
            expect[k] = (old if old.endswith("\n") else old + "\n") + add + "\n"
        else:
            to_set[k] = expect[k] = old.rstrip("\n") + "\n" + add
    return "\n".join(lines), to_set, expect


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


def value_sig(v) -> str:
    """値の鍵 (純関数) = 前後の空白を除いた文の sha1 の先頭 8 桁 (record-reply.py の context_sig と同じ式)。"""
    return hashlib.sha1(str(v if v is not None else "").strip().encode("utf-8")).hexdigest()[:8]


def guarded_keys(path: Path, extra=()) -> set[str]:
    """読んだ印を求める key = file の git 属性 `yaml-set-guard` (カンマ区切り) ∪ extra (--guard)。
    git の外・属性なし・git が無い = extra だけ (台帳の側が宣言して入れる網 = 宣言が無ければ従来どおり)。"""
    keys = {k for k in extra if k}
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE")}
    try:
        r = subprocess.run(["git", "-C", str(path.resolve().parent), "check-attr", "yaml-set-guard", "--", path.name],
                           capture_output=True, text=True, timeout=5, env=env)
    except (OSError, subprocess.SubprocessError):
        return keys
    val = r.stdout.strip().rsplit(": ", 1)[-1] if r.returncode == 0 else ""
    if val not in ("", "unspecified", "unset", "set"):
        keys |= {k.strip() for k in val.split(",") if k.strip()}
    return keys


def read_token_needs(before: dict, guarded: set[str], sets: dict, drops: list[str]) -> dict[str, str]:
    """守る key のうち、 今の値 (空でない) を失う書き方をするもの → 今の値の鍵。 旧い値を含む文字列への --set は要らない。"""
    need: dict[str, str] = {}
    for k in sorted(guarded):
        old = before.get(k)
        if old is None or not str(old).strip():
            continue  # 空の欄は失うものが無い
        if k in drops:
            need[k] = value_sig(old)
        elif k in sets:
            new = sets[k]
            if new == old or (isinstance(new, str) and isinstance(old, str) and old.strip() in new):
                continue
            need[k] = value_sig(old)
    return need


def read_token_refusals(before: dict, need: dict[str, str], given_items: list[str] | None) -> list[str]:
    """--replaces を照合し、 止める理由の行 (1 key 1 行、 今の値を全文) を返す。 空 = 書いてよい。
    渡された鍵は守る key でなくても照合する (読んだ後に変わったなら止める)。"""
    given: dict[str, str] = {}
    bare: list[str] = []
    for it in given_items or []:
        k, sep, v = it.partition("=")
        if sep:
            given[k.strip()] = v.strip()
        else:
            bare.append(it.strip())
    if bare:
        if len(bare) > 1 or len(need) != 1:
            raise SystemExit("❌ --replaces に鍵だけを渡せるのは、 鍵の要る key が 1 つのとき = `--replaces <key>=<鍵>` で渡す")
        given.setdefault(next(iter(need)), bare[0])
    out = []
    for k in sorted(set(need) | set(given)):
        now = value_sig(before.get(k))
        g = given.get(k)
        if g is not None and g == now:
            continue
        if g is None and k not in need:
            continue
        why = ("読んだ印 (--replaces) が無い" if g is None
               else f"読んだ後に値が変わった (渡した鍵 {g} ≠ 今の鍵 {now} = 別の書き手が間に書いた)")
        cur = str(before.get(k) if before.get(k) is not None else "").strip().replace("\n", " ⏎ ")
        out.append(f"✗ 書かなかった: {k} の{why}。 今の {k} = 「{cur}」 → これを読み直して新しい値を作り、"
                   f" --replaces {k}={now} を付けて打ち直す (鍵だけ写して打ち直さない)")
    return out


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
        # --append: block scalar は形を保って字下げで足す / 引用の文字列は改行で足す / 無い key は足す / list は止める
        p.write_text('id: "x"\nnotes: |\n  一段目\n  二段目\nsc: "前"\ntags:\n  - "a"\nstatus: 待ち\n', encoding="utf-8")
        assert main([str(p), "--append", "notes=三段目\n四段目", "--append", "sc=後", "--append", "memo=新"]) == 0
        t = p.read_text(encoding="utf-8")
        d = _yaml_safe_load(t)
        assert d["notes"] == "一段目\n二段目\n三段目\n四段目\n" and "  三段目\n  四段目\nsc:" in t, t  # block のまま
        assert d["sc"] == "前\n後" and d["memo"] == "新" and d["tags"] == ["a"] and d["status"] == "待ち", d
        before = t
        try:
            main([str(p), "--append", "tags=b"])
            raise AssertionError("list の key への --append を止めなかった")
        except SystemExit as e:
            assert "文字列でない" in str(e), e
        assert p.read_text(encoding="utf-8") == before
        # 末尾に空行のある block (次の key の前の空行) でも、 空行の手前に足す
        p.write_text('notes: |\n  a\n\nnext: "n"\n', encoding="utf-8")
        assert main([str(p), "--append", "notes=b"]) == 0
        d = _yaml_safe_load(p.read_text(encoding="utf-8"))
        assert d["notes"] == "a\nb\n" and d["next"] == "n", d
    # --set の改行を含む値は block で書く (読める形)、 block で同じ値に読めない値は二重引用 (実測 2 回 = block の欄が 1 行の引用に変わった)
    srcb = 'id: "x"\nhint: |\n  旧い 1\n  旧い 2\nafter: "a"\n'
    for val, head in (("一\n二\n  字下げ", "hint: |-"), ("一\n二\n", "hint: |"), ("一行", 'hint: "一行"'),
                      ("  先頭が空白\n二", 'hint: "  先頭が空白\\n二"'), ("tab\tあり\n二", 'hint: "tab\\tあり\\n二"'),
                      ("行末に空白 \n二", 'hint: "行末に空白 \\n二"'), ("二重\n\n", 'hint: "二重\\n\\n"')):
        outb = edit(srcb, {"hint": val}, [], None, {"hint": "c"} if head == "hint: |-" else {})
        assert verify(srcb, outb, {"hint": val}, []) == [], (val, outb)
        db = _yaml_safe_load(outb)
        assert db["hint"] == val and db["after"] == "a" and head in outb, (val, outb)
    assert "hint: |-   # c\n  一\n  二\n    字下げ\nafter:" in edit(srcb, {"hint": "一\n二\n  字下げ"}, [], None, {"hint": "c"})
    assert edit('a: "x"\n', {"new": "p\nq"}, [], None, {}) == 'a: "x"\nnew: |-\n  p\n  q\n'  # 無い key を足すときも block
    selftest_read_token()
    print("yaml-set-top-keys selftest: ALL PASS (行頭の key だけを置き換え・本文の中の同じ語は触らない・ほかの key は不変を確かめる"
          "・守る key は読んだ印が無いと書かない)")
    return 0


def _run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(argv)
    return rc, buf.getvalue()


def selftest_read_token() -> None:
    """守る key (読んだ印)。 再現 = 別の書き手が現在地に相手の返事を記録した後、 記憶から作った値で丸ごと置き換える。"""
    other = "2030-01-02 甲野さんの返事 (必要書類 3 点) → 次: 書類を送る / 並行: 事務の検討待ち"
    src = f'id: "x"\nstatus: "待ち"\nstatus_context: "{other}"\nnotes: |\n  a\n'
    sig = value_sig(other)
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        have_git = subprocess.run(["git", "init", "-q", str(repo)], capture_output=True).returncode == 0
        p = repo / "todo" / "x.yaml"
        p.parent.mkdir()
        if have_git:
            (repo / ".gitattributes").write_text("todo/*.yaml yaml-set-guard=status_context\n", encoding="utf-8")
            assert guarded_keys(p) == {"status_context"}, guarded_keys(p)
        guard = [] if have_git else ["--guard", "status_context"]
        p.write_text(src, encoding="utf-8")
        # 鍵なしの丸ごとの置き換え = 書かない。 最後の行に今の値の全文と鍵 (tail -1 でも届く)
        rc, out = _run([str(p), "--set", "status_context=記憶から書いた現在地 → 次: 書類を作る"] + guard)
        last = out.strip().splitlines()[-1]
        assert rc == 1 and other in last and f"--replaces status_context={sig}" in last, out
        assert p.read_text(encoding="utf-8") == src
        # dry-run は書かずに鍵を見せる
        rc, out = _run([str(p), "--set", "status_context=新しい現在地", "--dry-run"] + guard)
        assert rc == 0 and f"上書きの鍵 = --replaces status_context={sig}" in out and p.read_text(encoding="utf-8") == src, out
        # 鍵の形は key=鍵 と鍵だけの両方
        for rep in (f"status_context={sig}", sig):
            p.write_text(src, encoding="utf-8")
            rc, out = _run([str(p), "--set", "status_context=新しい現在地", "--replaces", rep] + guard)
            assert rc == 0 and _yaml_safe_load(p.read_text(encoding="utf-8"))["status_context"] == "新しい現在地", out
        # 読んだ後に別の書き手が値を変えた = 古い鍵では書かない
        rc, out = _run([str(p), "--set", "status_context=さらに新しい", "--replaces", f"status_context={sig}"] + guard)
        assert rc == 1 and "読んだ後に値が変わった" in out and "「新しい現在地」" in out, out
        # 失わない書き方は鍵が要らない (旧い値を含む --set / --append / 守らない key / 空の欄)
        p.write_text(src, encoding="utf-8")
        assert _run([str(p), "--set", f"status_context=2030-01-03 追記 / {other}"] + guard)[0] == 0
        assert _run([str(p), "--append", "status_context=もう 1 行"] + guard)[0] == 0
        assert _run([str(p), "--set", "status=対応中"] + guard)[0] == 0
        p.write_text('id: "x"\nstatus_context: ""\n', encoding="utf-8")
        assert _run([str(p), "--set", "status_context=最初の現在地"] + guard)[0] == 0
        # --drop と --set-literal も値を失う = 鍵が要る
        p.write_text(src, encoding="utf-8")
        assert _run([str(p), "--drop", "status_context"] + guard)[0] == 1
        assert _run([str(p), "--set-literal", "status_context=null"] + guard)[0] == 1
        assert p.read_text(encoding="utf-8") == src
        # 宣言の無い file (git の外・属性なし) は従来どおり鍵なしで書ける
        q = repo / "plain.yaml"
        q.write_text(src, encoding="utf-8")
        assert _run([str(q), "--set", "status_context=置き換え"])[0] == 0


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
    ap.add_argument("--append", action="append", dest="appends")
    ap.add_argument("--replaces", action="append", dest="replaces")
    ap.add_argument("--guard", action="append", default=[])
    a = ap.parse_args(argv)
    p = Path(a.file)
    before = p.read_text(encoding="utf-8")
    sets = kv(a.sets, allow_quoted=a.allow_quoted_value, allow_bool_string=a.allow_bool_string)
    lits = literals(a.set_literals)
    if set(sets) & set(lits):
        raise SystemExit(f"❌ 同じ key を --set と --set-literal の両方に渡した: {sorted(set(sets) & set(lits))}")
    sets.update(lits)
    appends = kv(a.appends)
    if set(appends) & set(sets):
        raise SystemExit(f"❌ 同じ key を --append と --set の両方に渡した: {sorted(set(appends) & set(sets))}")
    comments = kv(a.comments)
    if set(comments) - set(sets):
        raise SystemExit(f"❌ --comment は --set した行にだけ付く = 黙って捨てない (同じ key の --set も渡す): {sorted(set(comments) - set(sets))}")
    before_data = _yaml_safe_load(before) if before.strip() else {}
    before_data = before_data if isinstance(before_data, dict) else {}
    need = read_token_needs(before_data, guarded_keys(p, a.guard), sets, a.drop)
    if not a.dry_run:
        refusals = read_token_refusals(before_data, need, a.replaces)
        if refusals:  # 差分は出さない = 最後の行が今の値になる (出力を tail -1 に絞る呼び手にも届く)
            print("\n".join(refusals))
            return 1
    base, append_sets, expect = append_values(before, appends) if appends else (before, {}, {})
    after_text = edit(base, {**sets, **append_sets}, a.drop, a.after, comments)
    errs = verify(before, after_text, {**sets, **expect}, a.drop)
    sys.stdout.writelines(difflib.unified_diff(before.splitlines(True), after_text.splitlines(True), str(p), str(p)))
    if errs:
        print("❌ 書かなかった: " + " / ".join(errs))
        return 1
    if a.dry_run:
        for k, sig in need.items():
            print(f"上書きの鍵 = --replaces {k}={sig} (今の {k} を読んだ印。 書くときに付ける)")
    else:
        p.write_text(after_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
