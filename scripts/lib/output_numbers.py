#!/usr/bin/env python3
"""output_numbers.py — 実行出力の数値と追跡済みの記録を照合する共通規則。--selftest。

数値照合の規則の唯一の正本。Claude / Codex の締めの道具から使う。
拾う数値は小数点以下が 2 桁以上か指数表記で、重複を除いて出現順に最大 8 個
(呼び手は result_numbers の k で変更可)。前後が語の文字・点・コロン・slash
なら拾わず、直前の hyphen も除く。時刻・版番号・file 名に埋め込まれた数や
arXiv の番号の形 (4 桁 . 4〜5 桁) は除く。これは文字の形の判定であり、
計算結果かどうかを意味で判断しない。整数だけ・小数 1 桁だけは拾わない。

記録を探すのは呼び手が渡す repo の追跡済み作業ツリー。対象の拡張子は
md / tex / txt / out / py / yaml / yml / sh / jl / R / wls / log。
json / csv の data や未追跡 file は探さない。git grep -F -w で語の単位で
探し、元の表記、末尾の 0 を落とした形、有効数字 4 桁に丸めた形を照合する。
3 桁まで丸めると無関係な数字に一致した (実測)。記録の意味や出所が同じか、
その記録が commit 済みかまでは確かめない。repo の選定は呼び手が担う。

🔢 は「探した範囲で照合できなかった数値」の候補であって、不在の証明では
ない。別の丸め・別の表記・対象外の file・探索上限により取りこぼす。
git の失敗も一致なしとして扱うため、空の結果は検査の成功を意味しない。
呼び手は探索範囲と候補を示し、記録するか、記録しない理由を人が確かめる。
本 module は記録を変更せず、候補の存在で締めを自動停止させない。
"""
import re
import subprocess


def _git(args, cwd):
    try:
        r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout
    except Exception:
        return 1, ""


NUMBER_RE = re.compile(r"(?<![\w.:/-])[-+]?\d+\.\d{2,}(?:[eE][-+]?\d+)?(?![\w.:/])"
                       r"|(?<![\w.:/-])[-+]?\d+(?:\.\d+)?[eE][-+]?\d+(?![\w.:/])")



ARXIV_ID_RE = re.compile(r"\d{4}\.\d{4,5}")



RECORD_PATHSPECS = ["*.md", "*.tex", "*.txt", "*.out", "*.py", "*.yaml", "*.yml", "*.sh", "*.jl", "*.R", "*.wls", "*.log"]



def result_numbers(out, k=8):
    """共通規則に従う (module 冒頭を参照)。"""
    seen = []
    for m in NUMBER_RE.finditer(out or ""):
        v = m.group(0).lstrip("+")
        if ARXIV_ID_RE.fullmatch(v):
            continue
        if v not in seen:
            seen.append(v)
    return seen[:k]



def _variants(num):
    """共通規則に従う (module 冒頭を参照)。"""
    out = {num}
    if "." in num and "e" not in num.lower():
        out.add(num.rstrip("0").rstrip("."))
    try:
        x = float(num)
    except ValueError:
        return out
    digits = len(re.sub(r"[^0-9]", "", num.lower().split("e")[0]).lstrip("0"))
    for sig in (4,):
        if digits > sig and x != 0:
            out.add(("%." + str(sig) + "g") % x)
    return {v for v in out if v}



def numbers_recorded(nums, repos):
    """共通規則に従う (module 冒頭を参照)。"""
    if not nums or not repos:
        return []
    want = {n: _variants(n) for n in nums}
    pats = sorted({v for vs in want.values() for v in vs})
    found = set()
    for repo in repos:
        args = ["grep", "-F", "-w", "-o", "-h", "--no-color"]   # -w = 0.5536 が 0.553612 の一部に一致しない
        for v in pats:
            args += ["-e", v]
        args += ["--"] + RECORD_PATHSPECS
        rc, out = _git(args, repo)
        if rc == 0:
            found.update(out.split())
    return [n for n, vs in want.items() if any(v in found for v in vs)]



def _number_fields(out, repos):
    nums = result_numbers(out)
    if not nums:
        return {}
    return {"numbers": nums, "recorded": numbers_recorded(nums, repos)}


def selftest():
    import tempfile
    from pathlib import Path

    sample = "w 0.23940 0.5615 at 07:46:54.329Z v2.1.287 file 1401.6700.pdf 7.6e-10"
    assert result_numbers(sample) == ["0.23940", "0.5615", "7.6e-10"]
    assert result_numbers("ids 2102.12032 and 1809.04285, value 0.0785") == ["0.0785"]
    assert result_numbers("+0.5615 0.5615 -0.5615 3 0.2") == ["0.5615", "-0.5615"]
    assert result_numbers(" ".join("0.%02d" % n for n in range(10))) == ["0.%02d" % n for n in range(8)]
    with tempfile.TemporaryDirectory() as tmp:
        assert _git(["init", "-q"], tmp)[0] == 0
        Path(tmp, "note.md").write_text("weight = 0.2394; rounded = 0.7895; longer = 0.561512\n", encoding="utf-8")
        Path(tmp, "data.json").write_text('{"value": 0.5615}\n', encoding="utf-8")
        Path(tmp, "data.csv").write_text("value\n0.5615\n", encoding="utf-8")
        Path(tmp, "untracked.md").write_text("0.5615\n", encoding="utf-8")
        assert _git(["add", "note.md", "data.json", "data.csv"], tmp)[0] == 0
        assert numbers_recorded(["0.23940", "0.5615", "0.789456"], [tmp]) == ["0.23940", "0.789456"]
        assert _number_fields(sample, [tmp]) == {
            "numbers": ["0.23940", "0.5615", "7.6e-10"], "recorded": ["0.23940"]}
        assert _number_fields("no result", [tmp]) == {}
        assert numbers_recorded(["0.5615"], []) == []
    print("selftest: PASS (extraction, cap, rounding, tracked records, excluded data and token boundaries)")
    return 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if not args.selftest:
        parser.error("use --selftest; import this module from a report reader")
    raise SystemExit(selftest())

