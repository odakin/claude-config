#!/usr/bin/env python3
"""mark-handled-read.py — 見張っている Gmail ラベルの未読のうち、 「対応済み」 と記録で言えるものだけを既読にする engine。

対応済み = 次のどちらか。 どちらでもない未読は触らず、 仕分けの対象として一覧に出す:
  (a) messageId か threadId が記録の台帳に在る (harvester = lib/recorded_ids.py = 他の網と同じ関数)
  (b) 「見て対応不要と決めた」 ack の台帳 (YAML、 `ack: [{id, reason}]`) に在る。 reason は「YYYY-MM-DD 理由」 の形だけが効く
      (= 見て決めた記録。 理由の無い行は無視)

外すのは UNREAD だけ (ほかのラベル・削除・移動はしない)。 既定は dry-run、 書くのは --apply。
一般則 = conventions/email-surface-pattern.md#record-bound-mark-read。 個人の構成 (ラベル・台帳の場所) は呼び出し側が渡す。

使い方:
  mark-handled-read.py --label lab:SomeLabel [--label ...] --ledger-glob '~/repo/inbox/*.yaml' [...] \
      [--ack ack.yaml] [--gmail-dir ~/.gmail-mcp] [--apply | --ack-snippet]
  mark-handled-read.py --selftest

  --label ACCOUNT:NAME   見るラベル (account = gmail_read.service_for の alias)。 repeat 可
  --ledger-glob G        記録の台帳 (YAML) の glob。 repeat 可。 ~ を展開する
  --ack FILE             ack の台帳 (無ければ (b) は空)
  --ack-snippet          未対応の thread を ack に足す形で出す (件名を見て判断してから reason を書く = 見ずに貼らない。
                         貼る形は id と account / ラベルだけ = 件名・差出人は台帳に写さない)
  --exact-message        message の id が記録に在るものだけを既読にする (thread の id・ack では既読にしない)。
                         受信箱 (--label <account>:INBOX) に使う = 記録済みの thread に後から届いた未記録の返事を既読にしない
                         (未記録の続報を拾う網は未読を手がかりにしているので、 thread 単位の既読化はその網を黙らせる)
  --newer-than-days N    この日数より新しい message だけを見る (受信箱の古い未読を毎回数えない)
  --no-list              未対応の message を 1 通ずつ出さない (件数だけ。 受信箱では 1 通ごとの metadata 取得を省く)

設計 (実測から):
  - 未読を鍵にした見張りの段は、 記録を付けても UNREAD が残るので対応済みの mail で膨らみ、 本物が埋もれる。
  - auto mode では、 その場で書いた一括の既読化は外部への書き込みとして止められる → 判定を記録に束縛した狭い道具にし、
    道具の path だけを allow に宣言する。
  - ack の台帳は「既読にしてよい」 の許可そのもの。 止められた操作を通すために agent が自分で ack を書くと
    自己承認として止められる → ack を書くのは本人の OK の後。
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
REASON_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \S")


def _yaml_safe_load(stream):  # yaml.safe_load と同じ結果を C 版 (libyaml) で返す = 約 10 倍速 (run-all-checks の fast YAML loader)
    import yaml
    return yaml.load(stream, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))


def acked_ids(text: str | None) -> set[str]:
    """ack の台帳 text から、 reason が「YYYY-MM-DD 理由」 の形の id だけを返す。"""
    if not text:
        return set()
    data = _yaml_safe_load(text) or {}
    out = set()
    for row in data.get("ack", []) or []:
        if not isinstance(row, dict):
            continue
        rid, reason = str(row.get("id", "")).strip(), str(row.get("reason", "")).strip()
        if rid and REASON_RE.match(reason):
            out.add(rid)
    return out


def handled(msg: dict, known: set[str], exact: bool = False) -> bool:
    """exact = message id だけで判定する (thread の id では判定しない)。 受信箱のように thread の続報が来る場所では、
    記録済みの thread に後から届いた未記録の message まで既読にしてしまうので exact を使う。"""
    if exact:
        return msg.get("id") in known
    return msg.get("id") in known or msg.get("threadId") in known


def recorded_ids(ledger_globs: list[str]) -> set[str]:
    sys.path.insert(0, str(HERE / "lib"))
    import recorded_ids as ri
    paths: list[str] = []
    for g in ledger_globs:
        paths += glob.glob(os.path.expanduser(g))
    ids = set(ri.harvest_yaml_files(paths))
    text = "".join(Path(p).read_text(encoding="utf-8", errors="ignore") for p in paths)
    return ids | ri.harvest_thread_ids(text)


def recorded_message_ids(ledger_globs: list[str]) -> set[str]:
    """記録の台帳に message の id として載っているものだけ (thread の id は含めない)。"""
    sys.path.insert(0, str(HERE / "lib"))
    import recorded_ids as ri
    out: set[str] = set()
    for g in ledger_globs:
        for p in glob.glob(os.path.expanduser(g)):
            try:
                data = _yaml_safe_load(Path(p).read_text(encoding="utf-8"))
            except Exception:
                continue   # 読めない台帳は飛ばす = 未記録側に倒れる (既読にしない側)
            for e in (data if isinstance(data, list) else [data]):
                out |= ri.harvest_message_ids(e)
    return out


def parse_labels(items: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for it in items:
        acct, sep, name = it.partition(":")
        if not sep or not acct or not name:
            raise SystemExit(f"--label は ACCOUNT:NAME の形: {it!r}")
        out.setdefault(acct, []).append(name)
    return out


def selftest() -> int:
    known = {"aaa", "ttt"}
    assert handled({"id": "aaa", "threadId": "x"}, known)
    assert handled({"id": "b", "threadId": "ttt"}, known)
    assert not handled({"id": "b", "threadId": "y"}, known)
    # exact: 記録済みの thread に届いた未記録の message は既読にしない
    assert handled({"id": "aaa", "threadId": "x"}, known, exact=True)
    assert not handled({"id": "b", "threadId": "ttt"}, known, exact=True)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        Path(td, "inbox.yaml").write_text(
            '- id: "e1"\n  threadId: "t9"\n  messages:\n    - "mid:abc123 2030-01-01 10:00 ← A"\n', encoding="utf-8")
        Path(td, "todo.yaml").write_text('id: "x"\nemail_ref: "messageId:def456"\n', encoding="utf-8")
        got = recorded_message_ids([str(Path(td, "*.yaml"))])
        assert got == {"abc123", "def456"}, got   # thread の id (t9) は入らない
    txt = "ack:\n  - id: \"t1\"\n    reason: \"2030-01-01 見た\"\n  - id: \"t2\"\n    reason: \"理由なし\"\n  - id: \"t3\"\n  - \"bare\"\n"
    assert acked_ids(txt) == {"t1"}, acked_ids(txt)
    assert acked_ids("") == set()
    assert parse_labels(["a:X", "a:Y Z", "b:W"]) == {"a": ["X", "Y Z"], "b": ["W"]}
    try:
        parse_labels(["nocolon"])
        raise AssertionError("ACCOUNT:NAME でない --label は止まる")
    except SystemExit:
        pass
    print("selftest ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", action="append", default=[])
    ap.add_argument("--ledger-glob", action="append", default=[])
    ap.add_argument("--ack")
    ap.add_argument("--gmail-dir", default="~/.gmail-mcp")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--ack-snippet", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--exact-message", action="store_true",
                    help="message の id が記録に在るものだけ (thread の id と ack では既読にしない)。 受信箱 (INBOX) に使う")
    ap.add_argument("--newer-than-days", type=int, default=0, help="この日数より新しい message だけを見る (0 = 制限なし)")
    ap.add_argument("--no-list", action="store_true", help="未対応の message を 1 通ずつ出さない (件数だけ)")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    labels = parse_labels(a.label)
    if not labels or not a.ledger_glob:
        raise SystemExit("--label と --ledger-glob が要る (個人の構成は呼び出し側が渡す)")
    sys.path.insert(0, str(HERE / "lib"))
    import gmail_read as gr

    ack_text = Path(os.path.expanduser(a.ack)).read_text(encoding="utf-8") if a.ack and Path(os.path.expanduser(a.ack)).is_file() else None
    if a.exact_message:
        known = recorded_message_ids(a.ledger_glob)
    else:
        known = recorded_ids(a.ledger_glob) | acked_ids(ack_text)
    query = f"newer_than:{a.newer_than_days}d" if a.newer_than_days > 0 else None
    total = 0
    snippet: list[str] = []
    for acct, names in labels.items():
        svc = gr.service_for(Path(os.path.expanduser(a.gmail_dir)), acct, label="mark-handled-read")
        if svc is None:
            print(f"⚪ {acct}: 認証が無い = 未チェック")
            continue
        lab_ids = {x["name"]: x["id"] for x in svc.users().labels().list(userId="me").execute().get("labels", [])}
        for name in names:
            lid = lab_ids.get(name)
            if not lid:
                print(f"⚪ {acct} / {name}: ラベルが無い")
                continue
            msgs, tok = [], None
            while True:
                kw = {"q": query} if query else {}
                r = svc.users().messages().list(userId="me", labelIds=[lid, "UNREAD"], maxResults=100, pageToken=tok, **kw).execute()
                msgs += r.get("messages", []) or []
                tok = r.get("nextPageToken")
                if not tok:
                    break
            done = [m for m in msgs if handled(m, known, a.exact_message)]
            rest = [m for m in msgs if not handled(m, known, a.exact_message)]
            print(f"== {acct} / {name}: 未読 {len(msgs)} = 対応済み {len(done)} + 未対応 {len(rest)}")
            seen: set[str] = set()
            for m in ([] if a.no_list else rest):
                md = svc.users().messages().get(userId="me", id=m["id"], format="metadata",
                                                metadataHeaders=["From", "Subject", "Date"]).execute()
                h = {x["name"]: x["value"] for x in md["payload"]["headers"]}
                print(f"   ? thr={m['threadId']} {h.get('Date', '')[:16]} | {h.get('From', '')[:26]} | {h.get('Subject', '')[:64]}")
                if m["threadId"] not in seen:
                    seen.add(m["threadId"])
                    # 件名は上の「?」 の行で見る。 台帳 (平文のことが多い) に貼る形には件名・差出人を入れない
                    snippet.append(f"  - id: \"{m['threadId']}\"   # {acct} / {name}\n    reason: \"YYYY-MM-DD <見て決めた理由 (件名を写さず種類で)>\"")
            if a.apply and done:
                ids = [m["id"] for m in done]
                for i in range(0, len(ids), 500):
                    svc.users().messages().batchModify(userId="me", body={"ids": ids[i:i + 500], "removeLabelIds": ["UNREAD"]}).execute()
                total += len(ids)
                print(f"   ✓ 対応済み {len(ids)} 件を既読にした")
    if a.ack_snippet and snippet:
        print("\n# --- ack の台帳に足す候補 (件名を見て判断してから reason を書く) ---")
        print("\n".join(snippet))
    print(f"\n合計 {total} 件を既読にした" if a.apply else "\n(dry-run。 既読にするなら --apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
