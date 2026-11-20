#!/usr/bin/env python3
"""attachment_record.py — mail の台帳の entry に書く `attachments:` 欄の書式と、 その状態の読み方 (書き手と読み手の単一 home)。

なぜ存在するか (一般形、 実測は下の層の記録):
  本文が「詳細は添付」 の便は、 添付を開かないと当日に要る事実 (服装・集合・担当・提出) が記録のどこにも入らない。
  記録の要約に「添付にある」 と書いただけの entry は、 後で本人が事実を尋ねたとき、 記録を探しても答えが出ない
  (実測 = 添付は暗号化 zip、 パスワードは別便で届いていたのに開いていなかった)。 書き手 (scripts/record-reply.py) は
  添付つきの便の記録を「保存した」 か「保存しない理由」 が無いと止め、 その結果をこの書式で `attachments:` に書く。
  読み手 (scripts/check-unsaved-attachments.py) は同じ述語で「保存していない添付」 を読む。 書式を別々に持つと、
  書き手が書いた値を読み手が「未保存」 と読み続ける (= recorded_ids.py と同じ理由で 1 か所に寄せる)。

書式 (= value_for が書く。 規約 = conventions/mail-thread-ledger.md#attachment-substance):
  保存した:      "保存済み: <名前>, <名前> → <保存先>"
  暗号化 zip を保存したが、 パスワードが未着で開いていない:
                 "保存済み: <名前> → <保存先> (暗号化 zip・未展開 = パスワードの便を待つ)"
  保存しない:    "保存しない (<理由>): <名前>, <名前>"
  添付が無い:    欄を書かない (既存の台帳には "なし" と書いた entry もある = state_of が読む)

state_of (欄の値 → 状態):
  absent  = 欄が無い (道具が書く前の記録。 添付があったかは他の手がかり = 要約の語・Gmail で見る)
  none    = "なし" / "無し" / "none" / 空
  skipped = "保存しない" で始まる
  locked  = "未展開" を含む (= 開いていない。 読み手は未保存と同じに扱う)
  saved   = "保存済み" で始まる、 または "→" を含む (手で「<名前> → <置き場所>」 と書いた既存の記録)
  noted   = それ以外の文 (手で名前や説明だけを書いた既存の記録 = 人が何かを書いた = 読み手は出さない)

mentions_attachment (要約・件名に添付を示す語があるか): 添付 / 別紙 / 別便 / zip / パスワード / attach / enclosed。
  欄の無い古い entry で「添付があったはず」 を Gmail を引かずに知る手がかり (過去分の洗い出しも同じ語で回す)。
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

SAVED = "保存済み"
SKIPPED = "保存しない"
LOCKED_MARK = "暗号化 zip・未展開 = パスワードの便を待つ"
NONE_VALUES = {"", "なし", "無し", "none", "None", "n/a"}
MENTION_RE = re.compile(r"添付|別紙|別便|zip|ZIP|パスワード|パスワ-ド|attach|enclosed|password", re.IGNORECASE)


def _names(atts: list[dict]) -> str:
    return ", ".join(dict.fromkeys(str(a.get("filename") or "?") for a in atts))


def value_for(atts: list[dict], saved_dir: str | None = None, skip_reason: str | None = None, locked: bool = False) -> str:
    """atts (= gmail_read.attachment_parts の dict 列) の記録の値。 saved_dir か skip_reason のどちらか 1 つ。"""
    if skip_reason is not None:
        return f"{SKIPPED} ({skip_reason.strip()}): {_names(atts)}"
    v = f"{SAVED}: {_names(atts)} → {saved_dir}"
    return v + (f" ({LOCKED_MARK})" if locked else "")


def state_of(value) -> str:
    if value is None:
        return "absent"
    s = str(value).strip()
    if s in NONE_VALUES:
        return "none"
    if s.startswith(SKIPPED):
        return "skipped"
    if "未展開" in s:
        return "locked"
    if s.startswith(SAVED) or "→" in s:
        return "saved"
    return "noted"


def mentions_attachment(*texts) -> bool:
    return any(MENTION_RE.search(str(t or "")) for t in texts)


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def missing_in_dir(atts: list[dict], d: Path) -> list[str]:
    """保存先 d に無い添付の名前 (macOS の file 名は NFD のことがある = NFC にそろえて比べる)。 d が無ければ全部。"""
    if not d.is_dir():
        return [str(a.get("filename") or "?") for a in atts]
    have = {_nfc(p.name) for p in d.iterdir()}
    return [str(a.get("filename") or "?") for a in atts if _nfc(Path(str(a.get("filename") or "?")).name) not in have]


def extracted_beside(atts: list[dict], d: Path) -> bool:
    """保存先に添付そのもの以外の file があるか (= 暗号化 zip を開いた中身が隣にある、 と読む)。"""
    if not d.is_dir():
        return False
    names = {_nfc(Path(str(a.get("filename") or "")).name) for a in atts}
    return any(_nfc(p.name) not in names and not p.name.startswith(".") for p in d.iterdir())


def selftest() -> int:
    import tempfile
    fails = []

    def expect(label, cond):
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
        if not cond:
            fails.append(label)

    atts = [{"filename": "案内.zip"}, {"filename": "別紙.pdf"}, {"filename": "案内.zip"}]
    v_saved = value_for(atts, saved_dir="docs/x/")
    v_locked = value_for(atts[:1], saved_dir="docs/x/", locked=True)
    v_skip = value_for(atts, skip_reason="同じ資料を別便で受領済み")
    expect("value_for: 保存した・名前は重ねない", v_saved == "保存済み: 案内.zip, 別紙.pdf → docs/x/")
    expect("value_for: 保存しない", v_skip == "保存しない (同じ資料を別便で受領済み): 案内.zip, 別紙.pdf")
    expect("state_of: 書いた値を書いたとおりに読む (round-trip)",
           (state_of(v_saved), state_of(v_locked), state_of(v_skip)) == ("saved", "locked", "skipped"))
    expect("state_of: 既存の手書きの形 (なし / 名前 → 置き場所 / 名前だけ) と欄が無い",
           (state_of("なし"), state_of("a.zip (2 本) → grant/x/"), state_of("a.xlsx (= 参考)"), state_of(None))
           == ("none", "saved", "noted", "absent"))
    expect("mentions_attachment: 添付・zip・別便・パスワードの語", mentions_attachment("詳細は添付の zip")
           and mentions_attachment(None, "パスワードは別便") and not mentions_attachment("会議の日程", None))
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / unicodedata.normalize("NFD", "案内.zip")).write_bytes(b"x")
        expect("missing_in_dir: NFD の file 名も同じ名前と読む・無い名前を返す", missing_in_dir(atts, d) == ["別紙.pdf"])
        expect("extracted_beside: 添付だけなら False", not extracted_beside(atts, d))
        (d / "中身.pdf").write_bytes(b"y")
        expect("extracted_beside: 隣に別の file があれば True", extracted_beside(atts, d))
        expect("missing_in_dir: 保存先が無ければ全部", missing_in_dir(atts[:2], d / "nope") == ["案内.zip", "別紙.pdf"])
    print(f"selftest: {'ALL PASS' if not fails else 'FAIL ' + str(len(fails))}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(selftest())
