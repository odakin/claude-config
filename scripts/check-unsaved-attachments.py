#!/usr/bin/env python3
"""check-unsaved-attachments.py — 近い予定・期限を持つ開いた項目に結ばれた便の、 保存していない添付を出す engine (読むだけ)。

規約 = conventions/mail-thread-ledger.md#attachment-substance。 書式と状態の述語 = lib/attachment_record.py
(書き手 = scripts/record-reply.py と同じ部品)。 台帳の場所・予定の写し・account は下の層の shim が渡す (本 file に個人の値は無い)。

なぜ (一般形、 実測は下の層の記録):
  本文が「詳細は添付」 の便を、 要約に「添付にある」 と書いて記録し、 添付を開かないまま当日を迎えた。 本人が当日の事実を
  尋ねたとき、 記録にも予定の説明にも答えが無かった。 記録の道具の止め (record-reply の --attachments-*) は、 これから
  記録する便にしか効かない。 既に記録した便と、 止めを入れる前の記録を、 当日の前に拾う網がこれ。

述語:
  対象の項目 = 開いている (status が --closed-status に無い) ∧ 次のどちらかが今日から --window-days 日以内
    (a) 予定の写し (--events の JSON = [{date, end_date?, title, notes?, location?}]) のうち、 題・説明・場所がその項目の id を
        名指す予定の日 (終日の複数日の予定は end_date まで掛かる)
    (b) 項目の期限 (deadline / deadline_hard / deadline_soft の YYYY-MM-DD)
  その項目に結ばれた便 = lib/todo_thread_links.resolve_threads の thread (cross_ref の inbox 参照 / email_ref / related_todo の逆引き)
    を threadId に持つ entry と、 related_todo でその項目を名指す entry
  出す (🔴) = entry の attachments: の状態 (attachment_record.state_of) が
    locked (暗号化 zip が未展開)、 または
    absent (欄が無い) で、 添付の写し (--cache、 --refresh-cache が Gmail で作る = message id → 添付の名前の列) がその entry の
      message に添付があると言うか、 写しに entry の message が無く要約・件名に添付の語がある (attachment_record.mentions_attachment)
  出さない = saved / skipped / none / noted、 または写しが entry の全 message を「添付なし」 と言う

mode:
  (既定) --list    全件 (1 件 2 行)
  --digest         session の一覧用の行 (0 件なら何も出さない。 最大 --max-rows 行 + 残りの件数)
  --refresh-cache  対象の項目に結ばれた、 欄の無い entry の message の添付を Gmail で引いて --cache に書く (読むだけ。 shim の見張りが回す)
  --sweep          過去の分の洗い出し: 保存していない添付がある entry × 開いた項目 (日付を問わない、 判定は上と同じ =
                   写しがあれば Gmail の添付、 無ければ要約・件名の語)。 近い予定・期限の順 (今日以降を先に、 日付の無い項目は後)。
                   写しを全部の開いた項目に広げるのは --refresh-cache --all
  --selftest       fixture (項目・entry・予定・写し) で述語を固定する

伏せる語 (--mask-word、 複数): 項目の id・entry の id・件名・予定の題にこの語がある行は、 中身を出さずに件数の行にする
  (= 機微な予定の題や日付を一覧に写さない。 shim が語を渡す)。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))
import attachment_record  # noqa: E402
from recorded_ids import harvest_message_ids  # noqa: E402
from todo_ledger import load_todos  # noqa: E402
from todo_thread_links import harvest_todo_refs, resolve_threads, thread_ids  # noqa: E402

try:
    import yaml
    _Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
except ImportError:  # pragma: no cover
    yaml = None
    _Loader = None

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
DEADLINE_FIELDS = ("deadline", "deadline_hard", "deadline_soft")


# ============================================================
# 読み (台帳・予定・写し)
# ============================================================
def load_inbox(root: Path, ledgers: list[str]) -> list[dict]:
    out = []
    for name in ledgers:
        for f in sorted((root / name / "inbox").glob("*.yaml")):
            try:
                data = yaml.load(f.read_text(encoding="utf-8"), Loader=_Loader) or []
            except Exception:
                continue
            for e in data if isinstance(data, list) else []:
                if isinstance(e, dict) and e.get("id"):
                    out.append(dict(e, _ledger=name, _file=f.name))
    return out


def load_open_todos(root: Path, ledgers: list[str], closed: set[str]) -> list[dict]:
    out = []
    for name in ledgers:
        try:
            todos = load_todos(root / name)
        except Exception:
            continue
        for t in todos:
            if isinstance(t, dict) and t.get("id") and str(t.get("status") or "") not in closed:
                out.append(dict(t, _ledger=name))
    return out


def load_events(path: Path | None) -> list[dict]:
    if not path or not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [e for e in (data if isinstance(data, list) else data.get("events", [])) if isinstance(e, dict)]


def load_cache(path: Path | None) -> dict:
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("messages", {}) if isinstance(data, dict) else {}
    except Exception:
        return {}


# ============================================================
# 純関数 (結び・日付・判定)
# ============================================================
def _d(s) -> date | None:
    m = DATE_RE.search(str(s or ""))
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def todo_dates(todo: dict, events: list[dict], today: date) -> list[tuple[date, str]]:
    """項目に掛かる日 = [(日, 由来)]。 予定は項目の id を名指すもの (今日に掛かっている複数日の予定は今日)。"""
    tid = str(todo["id"])
    out: list[tuple[date, str]] = []
    for ev in events:
        blob = " ".join(str(ev.get(k) or "") for k in ("title", "notes", "description", "location"))
        if tid not in blob:
            continue
        s, e = _d(ev.get("date") or ev.get("start")), _d(ev.get("end_date"))
        if s is None:
            continue
        on = today if (e and s < today <= e) else s
        out.append((on, f"予定「{str(ev.get('title') or '')[:40]}」"))
    for f in DEADLINE_FIELDS:
        d = _d(todo.get(f))
        if d:
            out.append((d, f))
    return sorted(out)


def entries_of(todo: dict, entries: list[dict], inbox_by_id: dict, inverse: dict) -> list[dict]:
    tids = {t for t, _a in resolve_threads(todo, inbox_by_id, inverse)}
    want = set(inverse.get(str(todo["id"]), ()))
    return [e for e in entries if e["id"] in want or (set(thread_ids(e.get("threadId"))) & tids)]


def entry_messages(e: dict) -> set[str]:
    return set(harvest_message_ids(e))


def entry_inbound(e: dict, out_categories: set[str]) -> bool:
    """相手から届いた便を含む mail の entry か (純関数)。 索引 messages[] があればその向き (← = 相手発) で、 無ければ category と id の
    末尾 (-sent / -posted) で決める。 mail の id を持たない記録 (チャットの記録など) は False。
    自分が送った便の添付は手元に原本がある = 網の対象にしない。"""
    if not entry_messages(e):
        return False
    lines = [str(x) for x in (e.get("messages") or []) if isinstance(x, str)]
    if lines:
        return any(" ← " in x for x in lines)
    if str(e.get("category") or "") in out_categories:
        return False
    return not re.search(r"-(sent|posted)$", str(e.get("id") or ""))


MSG_DIR_RE = re.compile(r"^mid:([0-9a-f]+)\s.*?\s(←|→)\s")


def inbound_messages(e: dict) -> set[str]:
    """相手発の message の id (純関数)。 索引 messages[] の向き (←) で決め、 索引が無ければ entry の全 message。
    自分が送った message の添付 (送った様式・領収書の写し) は手元に原本がある = 数えない。"""
    lines = [str(x) for x in (e.get("messages") or []) if isinstance(x, str)]
    got = {m.group(1) for m in (MSG_DIR_RE.match(x) for x in lines) if m and m.group(2) == "←"}
    return got if lines else entry_messages(e)


def entry_finding(e: dict, cache: dict) -> dict | None:
    """この entry に保存していない添付があれば {kind, names, why}。 無ければ None (純関数)。"""
    st = attachment_record.state_of(e.get("attachments"))
    if st == "locked":
        return {"kind": "locked", "names": [], "why": "暗号化 zip が未展開 (パスワードの便を待つ)"}
    if st != "absent":
        return None
    mids = inbound_messages(e)
    known = {m: cache[m] for m in mids if m in cache}
    names = list(dict.fromkeys(n for v in known.values() for n in (v or [])))
    if names:
        return {"kind": "gmail", "names": names, "why": f"添付 {len(names)} 件の保存の記録が無い"}
    if known and len(known) == len(mids):
        return None   # 写しが全 message を「添付なし」 と言う
    if attachment_record.mentions_attachment(e.get("summary"), e.get("subject")):
        return {"kind": "mention", "names": [], "why": "要約・件名に添付の語があり、 保存の記録 (attachments:) が無い"}
    return None


def build_index(entries: list[dict]) -> tuple[dict, dict]:
    inbox_by_id = {e["id"]: {"threadId": e.get("threadId"), "account": e.get("account")} for e in entries}
    inverse: dict[str, list[str]] = {}
    for e in entries:
        for t in harvest_todo_refs(e):
            inverse.setdefault(t, []).append(e["id"])
    return inbox_by_id, inverse


def findings(todos: list[dict], entries: list[dict], events: list[dict], cache: dict, today: date,
             window_days: int = 7, out_categories: set[str] | None = None) -> list[dict]:
    inbox_by_id, inverse = build_index(entries)
    end = today + timedelta(days=window_days)
    out = []
    for t in todos:
        near = [(d, why) for d, why in todo_dates(t, events, today) if today <= d <= end]
        if not near:
            continue
        for e in entries_of(t, entries, inbox_by_id, inverse):
            if not entry_inbound(e, out_categories or set()):
                continue
            f = entry_finding(e, cache)
            if f:
                out.append(dict(f, todo=t["id"], ledger=t["_ledger"], entry=e["id"], subject=str(e.get("subject") or ""),
                                on=near[0][0], via=near[0][1]))
    return sorted(out, key=lambda x: (x["on"], x["todo"], x["entry"]))


def sweep(todos: list[dict], entries: list[dict], events: list[dict], today: date,
          out_categories: set[str] | None = None, cache: dict | None = None) -> list[dict]:
    """過去の分: 保存していない添付がある entry × 開いた項目 (日付を問わず、 近い日の順)。 判定は entry_finding と同じ =
    添付の写し (cache) があれば Gmail の添付で、 無い message は要約・件名の語で。 写しが「添付なし」 と言う entry は出さない。"""
    inbox_by_id, inverse = build_index(entries)
    out = []
    for t in todos:
        ds = [d for d, _w in todo_dates(t, events, today) if d >= today]
        for e in entries_of(t, entries, inbox_by_id, inverse):
            if not entry_inbound(e, out_categories or set()):
                continue
            f = entry_finding(e, cache or {})
            if not f:
                continue
            out.append({"todo": t["id"], "ledger": t["_ledger"], "entry": e["id"], "subject": str(e.get("subject") or ""),
                        "state": f["kind"], "on": min(ds) if ds else None})
    return sorted(out, key=lambda x: (x["on"] is None, x["on"] or date.max, x["todo"], x["entry"]))


def _masked(f: dict, words: list[str]) -> bool:
    blob = " ".join(str(f.get(k) or "") for k in ("todo", "entry", "subject", "via"))
    return any(w and w in blob for w in words)


def digest_rows(fs: list[dict], max_rows: int = 3, mask_words: list[str] | None = None, tool: str = "") -> list[str]:
    if not fs:
        return []
    words = mask_words or []
    shown = [f for f in fs if not _masked(f, words)]
    hidden = len(fs) - len(shown)
    rows = []
    for f in shown[:max_rows]:
        rows.append(f"  🔴 📎 保存していない添付 {f['on'].strftime('%m/%d')} ({f['via']}) TODO {f['todo']} ← 便 {f['entry']}: {f['why']}")
    rest = len(shown) - len(rows)
    if rest > 0:
        rows.append(f"  🔴 📎 ほかに保存していない添付 {rest} 件")
    if hidden:
        rows.append(f"  🔴 📎 伏せた項目に保存していない添付 {hidden} 件")
    if tool:
        rows.append(f"     → 開いて保存し、 当日に要る事実を要約と予定の説明に書く (一覧 = {tool} --list)")
    return rows


# ============================================================
# Gmail で添付を引く (--refresh-cache)
# ============================================================
def refresh_cache(cache_path: Path, todos: list[dict], entries: list[dict], events: list[dict], today: date, window_days: int,
                  accounts: list[str], creds_dir: Path, out_categories: set[str] | None = None, sweep_too: bool = False) -> int:
    import gmail_read
    inbox_by_id, inverse = build_index(entries)
    end = today + timedelta(days=window_days)
    targets: dict[str, str] = {}
    for t in todos:
        near = [d for d, _w in todo_dates(t, events, today) if today <= d <= end]
        if not near and not sweep_too:
            continue
        for e in entries_of(t, entries, inbox_by_id, inverse):
            if attachment_record.state_of(e.get("attachments")) == "absent" and entry_inbound(e, out_categories or set()):
                for m in inbound_messages(e):
                    targets.setdefault(m, str(e.get("account") or ""))
    old = {}
    if cache_path.exists():
        try:
            old = json.loads(cache_path.read_text(encoding="utf-8")).get("messages", {})
        except Exception:
            old = {}
    svcs: dict[str, object] = {}
    got = dict(old)
    for mid, acct in targets.items():
        if mid in old:
            continue
        for a in ([acct] if acct in accounts else []) + [x for x in accounts if x != acct]:
            if a not in svcs:
                svcs[a] = gmail_read.service_for(creds_dir, a, label="check-unsaved-attachments")
            svc = svcs[a]
            if svc is None:
                continue
            try:
                m = svc.users().messages().get(userId="me", id=mid, format="full").execute()
            except Exception:
                continue
            got[mid] = [x["filename"] for x in gmail_read.attachment_parts(m.get("payload", {}))]
            break
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"refreshed": datetime.now().isoformat(timespec="seconds"), "messages": got},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


# ============================================================
# selftest
# ============================================================
def _selftest() -> int:
    import tempfile
    fails = []

    def check(cond, name):
        print(("  PASS: " if cond else "  FAIL: ") + name)
        if not cond:
            fails.append(name)

    today = date(2030, 11, 15)
    todo = {"id": "2030-08-01-duty", "status": "待ち", "deadline": "2030-12-01", "_ledger": "L",
            "email_ref": "threadId:aaaa000000000001"}
    e_unsaved = {"id": "2030-11-10-notice-received", "subject": "当日のご連絡", "threadId": "aaaa000000000001",
                 "messageId": "aaaa000000000001", "messages": ["mid:aaaa000000000001 2030-11-10 16:12 ← 事務"],
                 "summary": "当日の段取り。 詳細は添付の zip (パスワードは別便)", "related_todo": ["2030-08-01-duty"]}
    e_saved = dict(e_unsaved, attachments="保存済み: 案内.zip → docs/x/")
    ev = [{"date": "2030-11-21", "end_date": "2030-11-21", "title": "当日の業務", "notes": "SoT: L/todo/2030-08-01-duty.yaml"}]
    fs = findings([todo], [e_unsaved], ev, {}, today)
    check(len(fs) == 1 and fs[0]["kind"] == "mention" and fs[0]["on"] == date(2030, 11, 21) and fs[0]["via"].startswith("予定"),
          "未保存の添付の便 (要約に添付の語・欄なし) × 7 日以内の予定が名指す項目 = 出す")
    check(findings([todo], [e_saved], ev, {}, today) == [], "保存済みの印 (attachments:) があれば消える")
    check(findings([todo], [dict(e_unsaved, attachments="保存済み: 案内.zip → docs/x/ (暗号化 zip・未展開 = パスワードの便を待つ)")],
                   ev, {}, today)[0]["kind"] == "locked", "暗号化 zip が未展開なら出す")
    check(findings([todo], [e_unsaved], ev, {}, date(2030, 11, 1)) == [], "予定も期限も窓 (7 日) の外なら出さない")
    check(len(findings([dict(todo, deadline="2030-11-18")], [e_unsaved], [], {}, today)) == 1, "予定が無くても期限が窓の中なら出す")
    check(findings([todo], [e_unsaved], ev, {"aaaa000000000001": []}, today) == [], "写しが全 message を添付なしと言えば出さない")
    g = findings([todo], [dict(e_unsaved, summary="当日の段取り")], ev, {"aaaa000000000001": ["案内.zip"]}, today)
    check(len(g) == 1 and g[0]["kind"] == "gmail" and g[0]["names"] == ["案内.zip"], "写しが添付ありと言えば、 要約に語が無くても出す")
    check(findings([todo], [dict(e_unsaved, attachments="なし")], ev, {}, today) == [], "「なし」 は出さない")
    other = dict(e_unsaved, id="x", threadId="bbbb000000000009", messageId="bbbb000000000009", messages=[], related_todo=[])
    check(findings([todo], [other], ev, {}, today) == [], "項目に結ばれていない便は出さない")
    sent = dict(e_unsaved, messages=["mid:aaaa000000000001 2030-11-10 16:12 → 事務"])
    sent_noidx = dict(e_unsaved, messages=None, category="送信済")
    chat = dict(e_unsaved, messageId=None, threadId=None, messages=None)
    check(findings([todo], [sent], ev, {}, today) == []
          and findings([todo], [sent_noidx], ev, {}, today, out_categories={"送信済"}) == []
          and findings([todo], [chat], ev, {}, today) == [],
          "自分発だけの便 (索引の向き → / 索引が無ければ category)・mail の id の無い記録は出さない")
    mixed = dict(e_unsaved, summary="返事", messages=["mid:aaaa000000000001 2030-11-10 16:12 → 事務",
                                                      "mid:aaaa000000000002 2030-11-11 09:00 ← 事務"])
    check(findings([todo], [mixed], ev, {"aaaa000000000001": ["送った様式.docx"], "aaaa000000000002": []}, today) == []
          and findings([todo], [mixed], ev, {"aaaa000000000001": [], "aaaa000000000002": ["返事の別紙.pdf"]}, today)[0]["names"]
          == ["返事の別紙.pdf"],
          "自分が送った message の添付は数えず、 相手から届いた message の添付だけを数える")
    multi = [{"date": "2030-11-14", "end_date": "2030-11-16", "title": "連日", "notes": "2030-08-01-duty"}]
    check(findings([dict(todo, deadline=None)], [e_unsaved], multi, {}, today)[0]["on"] == today, "今日に掛かる複数日の予定は今日")
    rows = digest_rows(fs, tool="check-unsaved-attachments.py")
    check(rows[0].startswith("  🔴 📎 保存していない添付 11/21") and "TODO 2030-08-01-duty" in rows[0] and "--list" in rows[-1],
          "digest の行 (日・由来・項目・便・理由と、 一覧の入口)")
    check(digest_rows(fs, mask_words=["業務"]) == ["  🔴 📎 伏せた項目に保存していない添付 1 件"],
          "伏せる語のある行は件数だけ")
    check(digest_rows([]) == [], "0 件なら何も出さない")
    sw = sweep([dict(todo, deadline=None)], [e_unsaved, e_saved, dict(e_unsaved, id="y", summary="会議の日程")], [], today)
    check([s["entry"] for s in sw] == ["2030-11-10-notice-received"] and sw[0]["on"] is None,
          "洗い出し: 添付の語のある欄なしの便だけ、 日付の無い項目も出す")
    check(sweep([dict(todo, deadline=None)], [e_unsaved], [], today, cache={"aaaa000000000001": []}) == []
          and sweep([dict(todo, deadline=None)], [dict(e_unsaved, summary="返事")], [], today,
                    cache={"aaaa000000000001": ["案内.zip"]})[0]["state"] == "gmail",
          "洗い出し: 写しが添付なしと言う便は出さず、 写しが添付ありと言えば語が無くても出す")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "L" / "inbox").mkdir(parents=True)
        (root / "L" / "todo").mkdir()
        (root / "L" / "todo" / "2030-08-01-duty.yaml").write_text(
            'id: "2030-08-01-duty"\nstatus: "待ち"\nemail_ref: "threadId:aaaa000000000001"\n', encoding="utf-8")
        (root / "L" / "todo" / "2030-01-01-done.yaml").write_text('id: "2030-01-01-done"\nstatus: "完了"\n', encoding="utf-8")
        (root / "L" / "inbox" / "2030-11.yaml").write_text(
            '- id: "2030-11-10-notice-received"\n  subject: "当日のご連絡"\n  threadId: "aaaa000000000001"\n'
            '  messageId: "aaaa000000000001"\n  summary: |\n    詳細は添付の zip\n', encoding="utf-8")
        evp = root / "ev.json"
        evp.write_text(json.dumps(ev, ensure_ascii=False), encoding="utf-8")
        ts = load_open_todos(root, ["L"], {"完了"})
        es = load_inbox(root, ["L"])
        check([t["id"] for t in ts] == ["2030-08-01-duty"] and len(es) == 1 and len(load_events(evp)) == 1,
              "台帳の読み (閉じた項目は除く)・予定の写しの読み")
        check(len(findings(ts, es, load_events(evp), load_cache(root / "none.json"), today)) == 1, "file から読んだ fixture で出す")
        (root / "L" / "inbox" / "2030-11.yaml").write_text(
            (root / "L" / "inbox" / "2030-11.yaml").read_text(encoding="utf-8") + '  attachments: "保存済み: 案内.zip → L/docs/x/"\n',
            encoding="utf-8")
        check(findings(ts, load_inbox(root, ["L"]), load_events(evp), {}, today) == [], "file に保存の印を書けば消える")
    print(f"selftest: {'ALL PASS' if not fails else 'FAIL ' + str(len(fails))}")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--ledger", action="append", default=[])
    ap.add_argument("--closed-status", default="", help="閉じた項目の status (comma 区切り)")
    ap.add_argument("--out-category", default="sent", help="自分発の entry の category (comma 区切り、 索引の無い entry の向きに使う)")
    ap.add_argument("--events", help="予定の写し (JSON の list)")
    ap.add_argument("--cache", help="添付の写し (--refresh-cache が書く JSON)")
    ap.add_argument("--window-days", type=int, default=7)
    ap.add_argument("--max-rows", type=int, default=3)
    ap.add_argument("--mask-word", action="append", default=[])
    ap.add_argument("--accounts", default="")
    ap.add_argument("--creds-dir", default=str(Path.home() / ".gmail-mcp"))
    ap.add_argument("--tool-name", default="", help="digest の行に出す一覧の入口 (shim の path)")
    ap.add_argument("--today", help="YYYY-MM-DD (試験用)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--list", action="store_true")
    g.add_argument("--digest", action="store_true")
    g.add_argument("--refresh-cache", action="store_true")
    ap.add_argument("--all", action="store_true", help="--refresh-cache で、 期限・予定の窓の外の開いた項目の便も引く (過去分の洗い出し用)")
    g.add_argument("--sweep", action="store_true")
    g.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    if yaml is None:
        print("PyYAML が無い (exit 3)", file=sys.stderr)
        return 3
    root = Path(args.root).expanduser()
    today = date.fromisoformat(args.today) if args.today else date.today()
    closed = {x for x in args.closed_status.split(",") if x}
    outc = {x for x in args.out_category.split(",") if x}
    todos = load_open_todos(root, args.ledger, closed)
    entries = load_inbox(root, args.ledger)
    events = load_events(Path(args.events).expanduser() if args.events else None)
    cache_path = Path(args.cache).expanduser() if args.cache else None
    if args.refresh_cache:
        if not cache_path:
            print("--refresh-cache には --cache が要る (exit 1)", file=sys.stderr)
            return 1
        return refresh_cache(cache_path, todos, entries, events, today, args.window_days,
                             [x for x in args.accounts.split(",") if x], Path(args.creds_dir).expanduser(), outc,
                             sweep_too=args.all)
    if args.sweep:
        rows = sweep(todos, entries, events, today, outc, load_cache(cache_path))
        print(f"# 保存していない添付がある便 × 開いた項目 = {len(rows)} 件 (近い日の順。 [gmail] = 写しが添付ありと言う / [mention] = 写しが無く要約・件名に添付の語 / [locked] = 暗号化 zip が未展開)")
        for r in rows:
            masked = _masked({"todo": r["todo"], "entry": r["entry"], "subject": r["subject"]}, args.mask_word)
            on = r["on"].isoformat() if r["on"] else "日付なし"
            if masked:
                print(f"- {on} (伏せた項目) [{r['state']}]")
            else:
                print(f"- {on} TODO {r['ledger']}:{r['todo']} ← 便 {r['entry']} [{r['state']}] 「{r['subject'][:50]}」")
        return 0
    fs = findings(todos, entries, events, load_cache(cache_path), today, args.window_days, outc)
    if args.digest:
        for line in digest_rows(fs, args.max_rows, args.mask_word, args.tool_name):
            print(line)
        return 0
    print(f"# 保存していない添付 (開いた項目 × {args.window_days} 日以内の予定・期限) = {len(fs)} 件")
    for f in fs:
        if _masked(f, args.mask_word):
            print(f"- {f['on'].isoformat()} (伏せた項目)")
            continue
        print(f"- {f['on'].isoformat()} {f['via']} TODO {f['ledger']}:{f['todo']}\n    ← 便 {f['entry']} 「{f['subject'][:50]}」: {f['why']}"
              + (f" ({', '.join(f['names'])})" if f["names"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
