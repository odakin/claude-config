"""relay_check.py — surface した item を「この session で人に伝えたか」 と「同じ案件かもしれない別の item」 を判定する共通部品

session 開始時の注入は agent の文脈にだけ入り、 人の画面には出ない。 期限の近い item を人に伝えずに
session を閉じようとしたら Stop hook で止める、 という使い方をする (= 伝達の検査)。 また、 1 件を処分させる
ときに、 件名の語を共有する未処理 item を並べて「別件名で届いた後続」 を見落とさせない (= 案件単位の結合)。

- 伝えたかの判定 = この session の assistant の text に、 件名の語 (固有の 4 字 / 6 文字以上の英単語) が 1 つでも出たか。
  件名と無関係な言い換えで伝えると「未伝達」 と判定する (= 誤判定の cost は最大 1 turn の余計な block)
- 結合 = 件名の語を共有する item。 多くの件名に出る語 (年度・学期など) では結び付けない (df の上限)
- 読めない transcript・壊れた行は空として扱う。 呼び出し側の hook は import 失敗も含めて fail-open にする

原則 = docs/convention-design-principles.md#surface-reader-is-not-the-owner / #lapse-claim-is-absence-claim、
使い方 = conventions/hook-authoring.md#injection-digest-and-relay。 selftest: python3 relay_check.py --selftest
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# 件名に広く出て案件を識別しない語 (= 語の抽出前に落とす)
GENERIC = ("につきまして", "について", "のご連絡", "ご連絡", "のお願い", "お願い", "ご案内",
           "お知らせ", "ご報告", "ご確認", "確認")

_PREFIX_RE = re.compile(r"^(\s*(re|fwd?|fw)\s*[:：]\s*)+", re.I)
_ML_TAG_RE = re.compile(r"\[[^\]]*:\d+\]")
_BRACKETS_RE = re.compile(r"[【】\[\]（）()「」『』]")
_JA_RUN_RE = re.compile(r"[一-龥々ァ-ヶーぁ-ん]{4,}")
_STRONG2_RE = re.compile(r"[一-龥々ァ-ヶー]{2}")
_EN_WORD_RE = re.compile(r"[A-Za-z]{6,}")


def subject_grams(subject: str) -> set[str]:
    """件名 → 識別に使う語の集合 (漢字・カタカナを 2 字以上含む 4 字の窓 + 6 文字以上の英単語の小文字)。"""
    s = _PREFIX_RE.sub("", subject or "")
    s = _ML_TAG_RE.sub(" ", s)
    s = _BRACKETS_RE.sub(" ", s)
    for g in GENERIC:
        s = s.replace(g, " ")
    out: set[str] = set()
    for run in _JA_RUN_RE.findall(s):
        for i in range(len(run) - 3):
            w = run[i:i + 4]
            if _STRONG2_RE.search(w):
                out.add(w)
    for word in _EN_WORD_RE.findall(s):
        out.add(word.lower())
    return out


def session_assistant_text(transcript_path) -> str:
    """transcript (jsonl) の assistant の text block を全部つないで返す。 読めなければ空。"""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from transcript_turns import load_entries
        entries = load_entries(transcript_path)
    except Exception:
        return ""
    parts = []
    for e in entries:
        if e.get("type") != "assistant":
            continue
        c = (e.get("message") or {}).get("content")
        for b in c if isinstance(c, list) else []:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text") or "")
    return "\n".join(parts)


def mentioned(subject: str, text: str) -> bool:
    """件名の語が text に 1 つでも出たか。 語が 1 つも取れない件名は判定できないので True (= 止めない側)。"""
    grams = subject_grams(subject)
    if not grams:
        return True
    low = text.lower()
    return any((w in low) if w.isascii() else (w in text) for w in grams)


def related(target_subjects: list[str], items: list[dict], exclude_ids: set, df_max: int = 3,
            subject_key: str = "subject", id_key: str = "id") -> list[tuple[dict, str]]:
    """target の件名と語を共有する item を (item, 共有した語) で返す。 多くの件名に出る語 (df > df_max) は使わない。"""
    target: set[str] = set()
    for s in target_subjects:
        target |= subject_grams(s)
    df: dict[str, int] = {}
    for it in items:
        for w in subject_grams(it.get(subject_key, "")):
            df[w] = df.get(w, 0) + 1
    out = []
    for it in items:
        if it.get(id_key) in exclude_ids:
            continue
        shared = {w for w in subject_grams(it.get(subject_key, "")) & target if df.get(w, 0) <= df_max}
        if shared:
            out.append((it, sorted(shared)[0]))
    return out


def _selftest() -> int:
    import json
    import tempfile
    npass = nfail = 0

    def check(cond, name):
        nonlocal npass, nfail
        if cond:
            npass += 1
            print(f"  PASS: {name}")
        else:
            nfail += 1
            print(f"  FAIL: {name}")

    # 合成例 (実在の件名ではない)
    a = "Re: 受付手続きについてのご連絡"
    b = "Re: 2027年度前期受付手続き不備の方につきまして"
    check("受付手続" in subject_grams(a) and "受付手続" in subject_grams(b), "件名の語: 汎用句を落として 4 字の窓を取る")
    check(not any(w.isdigit() or "につき" in w for w in subject_grams(b)), "数字だけの窓・汎用句は語にしない")
    check(subject_grams("Re: Invitation to review manuscript") >= {"invitation", "manuscript"}, "英語は 6 文字以上の単語")
    check(mentioned(a, "受付手続の件 (9/9 まで) が来ています") and not mentioned(a, "リポを最新にしました"),
          "伝えたか = 件名の語が assistant の文に出たか")
    check(mentioned("Re: ご連絡", "何も"), "語が取れない件名は判定しない (= 止めない側)")
    items = [{"id": "1", "subject": a}, {"id": "2", "subject": b}, {"id": "3", "subject": "夏の合宿のご案内"}]
    rel = related([a], items, {"1"})
    check([it["id"] for it, _ in rel] == ["2"] and rel[0][1] in subject_grams(a) & subject_grams(b),
          "結合 = 件名の語を共有する別 item だけ (共有した語を返す)")
    many = [{"id": str(i), "subject": f"年度後期の書類その{i}"} for i in range(6)]
    check(related(["年度後期の予定"], many, set()) == [], "多くの件名に出る語では結び付けない (df の上限)")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td, "t.jsonl")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "user", "message": {"content": "pull して"}}, ensure_ascii=False) + "\n")
            fh.write("{broken\n")
            fh.write(json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash"}, {"type": "text", "text": "受付手続の件を伝えます"}]}},
                ensure_ascii=False) + "\n")
        txt = session_assistant_text(p)
        check("受付手続" in txt and "pull" not in txt, "transcript の assistant の text だけを読む (壊れた行は飛ばす)")
        check(session_assistant_text(Path(td, "none.jsonl")) == "", "読めない transcript は空")
    print(f"\n==== RESULT: PASS={npass} FAIL={nfail} ====")
    return 1 if nfail else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
