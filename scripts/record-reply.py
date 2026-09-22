#!/usr/bin/env python3
"""record-reply.py — mail を thread 単位で台帳に記録する engine (entry に印と索引、 結ぶ項目の現在地。 既定 dry-run)。

台帳の場所・account・自分の address 等は shim (下の層) が CLI option で渡す (本 file に個人の値は無い)。
規約 = conventions/mail-thread-ledger.md (台帳の形・手順・失敗の向き)、 原理 = conventions/email-surface-pattern.md
#single-writer-thread-cursor。 記録済み id の書式 = lib/recorded_ids.py、 項目→thread の link = lib/todo_thread_links.py、
Gmail の読み = lib/gmail_read.py。

なぜ存在するか (一般形):
  返事 1 通の記録に file を 3〜4 触り id を手で写す運用は、 記録が高いので未記録が溜まり、 「記録済みか」 の判定を
  書き手が正しく行うには共有 harvester を呼ぶしかない (1 つの台帳だけ grep して誤る)。 根は書き手にある =
  **id を書くのは道具だけ**にし、 thread 1 つに entry 1 つ、 読んだ位置の印 (`recorded_upto`) と機械が書く索引
  (`messages[]`) で「どこまで記録したか」 を明示する。

何をするか:
  1. 対象 (項目 id / threadId / messageId / entry id) から thread を解決する (項目 → thread は 3 経路 = lib)。
  2. Gmail から thread の全 message を取り (読むだけ)、 **全台帳** の entry と項目から記録済み id を集め、
     message ごとに「この entry に在る / 他所で記録済み / 未記録」 に分ける。
  3. dry-run (既定) では未記録の本文 (引用行を除く) と書く予定の差分を出す。 `--apply` で書く。
  4. 書くもの (= この 2 file だけ): 台帳の月 file (thread の home entry を作る or 足す = `threadId` 〔無ければ〕・
     `recorded_upto`・`messages[]`・`related_todo` 〔結ぶ項目が無ければ〕) と、 結ぶ項目 (`status_context` を上書き、
     `updated`、 `--status`、 `email_ref` が無ければ `threadId:<id>` の 1 行)。 `--next` は項目を書くとき必須。
  書かないもの: 案件の正本・calendar・Gmail の label と既読・`notes` field・既存 entry の `category`。

失敗の向き:
  - 書いた後に YAML を再 parse して entry 数・対象 entry の field・round-trip (書いた id が harvester で拾われる) を
    確かめ、 外れたら元の text に戻して exit 3 (= 検査不能 / 故障。 違反 = exit 1 と分ける)。
  - Gmail が引けない thread は「引けなかった」 と出して未記録扱いにしない。 認証の無い account は飛ばす。
  - cache (`--cache-dir`) は `--migrate` の一括読み専用。 通常の記録は毎回 Gmail を引く (古い cache が新着を隠す罠)。
    移行でも entry が知っている id が cache の thread に無ければ引き直す。

移行 (`--migrate <ledger>`): 既存 entry に印と索引を**追記**する。 索引に書くのは entry が **message として**記録した id
  (top-level messageId ∪ 全 string の messageId: / mid:) と一致する message だけ。 threadId と同値の root message は
  載せない (threadId は thread の記録であって root を読んだ記録ではない。 載せると message 専用の読み手の集合が
  変わる = 実測)。 散文は 1 字も変えず、 threadId / related_todo も足さない。 `--remigrate` は印のある entry も対象にし、
  規則に外れる root の行だけ外す (通常の記録で足した行は残す)。

使い方 (shim が option を足す):
  record-reply.py <対象> [--todo <id>] [--account <alias>] [--next "<次の一手>"] [--status <enum>]
                  [--summary "<3 行まで>"] [--slug <romaji>|--id <entry id>] [--ledger-for-new <name>] [--no-todo] [--apply]
  record-reply.py --check | --schema | --migrate <ledger> [--remigrate] [--apply] [--limit N] [--only <id>] | --selftest
  設定 option: --root DIR --ledger NAME (複数) --accounts a,b,c --creds-dir DIR --owner-token TOKEN (複数)
              --status-enum a,b,c --category-in / --category-out --ctx-reply / --ctx-sent (template) --tz NAME
              --cache-dir DIR --month-header "<template>"

selftest (= 偽の Gmail + 2 台帳の fixture、 API に触らない): t1 legacy 4 書式から未記録 = 全 message − harvester の集合 /
  t2 片方の台帳にしか無い entry を辿る / t3 書いた id の round-trip / t4 dry-run は byte 不変 / t5 項目の現在地・updated・
  email_ref / t6 --check が印 ≠ 最新を赤に / t7 notes を作らない・summary 4 行目 warn・enum 外を拒む / t8 再 parse 失敗で
  戻す / t9 status_context は 1 行の JSON 文字列 / t10 移行は message として記録した id だけ / t11 root を載せない /
  t12 --remigrate は root の行だけ外す。
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))
from recorded_ids import MSGID_RE, THREADID_RE, harvest_entry, harvest_message_ids  # noqa: E402
from todo_thread_links import harvest_todo_refs, norm_account, owner_from, resolve_threads, thread_ids  # noqa: E402
import gmail_read  # noqa: E402

SUMMARY_MAX_LINES = 3
HEX_RE = re.compile(r"^[0-9a-f]{16,}$")
MSG_LINE_RE = re.compile(r"^mid:([0-9a-f]{16,}) (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) ([←→]) (.*)$")
UPTO_RE = re.compile(r"^messageId:([0-9a-f]{16,}) \((\d{4}-\d{2}-\d{2} \d{2}:\d{2})\)$")
ENTRY_START_RE = re.compile(r'^- id: "?([^"\n]+?)"?\s*(#.*)?$')

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML が必要: pip install pyyaml")


@dataclass
class Config:
    """台帳の場所と、 記録に要る個人の値 (= shim が渡す。 engine に既定の個人値は無い)。"""
    root: Path
    ledgers: list[str]                       # <root>/<name>/inbox/*.yaml + <root>/<name>/TODO.yaml
    accounts: tuple[str, ...] = ()           # 試す順。 先頭 = 既定
    creds_dir: Path = Path.home() / ".gmail-mcp"
    owner_tokens: tuple[str, ...] = ()       # From にこれを含めば自分発 (→)
    status_enum: set[str] | None = None      # None = 検査しない
    category_in: str = "received"
    category_out: str = "sent"
    ctx_reply: str = "{date} reply from {name} ({subj}) → next: {next}"
    ctx_sent: str = "{date} sent to {name} ({subj}) → next: {next}"
    tz: str = "local"
    cache_dir: Path = Path.home() / ".cache" / "record-reply"
    month_header: str = "# {year}-{month:02d} mail ledger"

    def tzinfo(self):
        if self.tz == "local":
            return datetime.now().astimezone().tzinfo
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(self.tz)
        except Exception:
            return timezone.utc


# ============================================================
# 台帳 (全 ledger の inbox + TODO) — 読み
# ============================================================
class Ledger:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.inbox: list[tuple[str, Path, dict]] = []      # (ledger, path, entry)
        self._harv: list[set[str]] = []
        self.todos: dict[str, tuple[str, Path, dict]] = {}  # todo id → (ledger, path, todo)
        self.by_id: dict[str, tuple[str, Path, dict]] = {}
        self.known: set[str] = set()
        self.meta: dict[str, dict] = {}
        self.inverse: dict[str, list[str]] = {}
        self.broken: list[str] = []
        for name in cfg.ledgers:
            d = cfg.root / name / "inbox"
            for p in sorted(d.glob("*.yaml")) if d.exists() else []:
                for e in self._load_list(p):
                    eid = e.get("id")
                    self.inbox.append((name, p, e))
                    self._harv.append(harvest_entry(e))
                    if isinstance(eid, str):
                        self.by_id[eid] = (name, p, e)
                        tid, acct = e.get("threadId"), e.get("account")
                        self.meta[eid] = {"threadId": tid if isinstance(tid, str) else None,
                                          "account": acct if isinstance(acct, str) else None}
                        for t in harvest_todo_refs(e):
                            self.inverse.setdefault(t, []).append(eid)
                    self.known |= self._harv[-1]
            tp = cfg.root / name / "TODO.yaml"
            if tp.exists():
                for t in self._load_list(tp):
                    if isinstance(t.get("id"), str):
                        self.todos[t["id"]] = (name, tp, t)
                    self.known |= harvest_entry(t)

    def _load_list(self, p: Path) -> list[dict]:
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception as e:
            self.broken.append(f"{p}: {str(e).splitlines()[0] if str(e) else 'parse error'}")
            return []
        return [x for x in (data if isinstance(data, list) else []) if isinstance(x, dict)]

    def entries_for_thread(self, tid: str, msg_ids: set[str]) -> list[tuple[str, Path, dict]]:
        return [(n, p, e) for (n, p, e), h in zip(self.inbox, self._harv)
                if tid in thread_ids(e.get("threadId")) or (h & msg_ids)]


# ============================================================
# Gmail (読むだけ)。 cache は移行専用。 selftest では差し替える
# ============================================================
class Gmail:
    def __init__(self, cfg: Config, use_cache: bool = False):
        self.cfg = cfg
        self.use_cache = use_cache
        self._svc: dict[str, object] = {}

    def service(self, account: str):
        if account not in self._svc:
            self._svc[account] = gmail_read.build_service(gmail_read.load_account_creds(self.cfg.creds_dir, account))
        return self._svc[account]

    def thread(self, account: str, tid: str, full: bool = True, refresh: bool = False) -> list[dict] | None:
        svc = self.service(account)
        if svc is None:
            return None
        cache = self.cfg.cache_dir / account / f"{tid}.{'full' if full else 'meta'}.json"
        self.last_tid = tid   # 呼び手が「本当の thread id」 を知るため (404 → 引き直しで変わる)
        if self.use_cache and not refresh and cache.exists():
            try:
                return json.loads(cache.read_text(encoding="utf-8"))
            except Exception:
                pass
        out = gmail_read.thread_messages(svc, tid, full=full)
        if out is None:
            # 返信の messageId で threads.get すると 404 = 本当の thread を引き直す
            real = gmail_read.thread_of_message(svc, tid)
            if not real or real == tid:
                return None
            return self.thread(account, real, full, refresh)
        if self.use_cache:
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
        return out

    def thread_of_message(self, account: str, mid: str) -> str | None:
        return gmail_read.thread_of_message(self.service(account), mid)


# ============================================================
# 純関数 (表示・生成・判定)
# ============================================================
def stamp(cfg: Config, internal_ms) -> str:
    try:
        return datetime.fromtimestamp(int(internal_ms) / 1000, tz=cfg.tzinfo()).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "0000-00-00 00:00"


def from_display(from_hdr: str) -> str:
    s = (from_hdr or "").strip()
    name = s.split("<")[0].strip().strip('"').strip()
    if name:
        return name
    m = re.search(r"<([^>]+)>", s)
    return (m.group(1) if m else s) or "(unknown)"


def message_line(cfg: Config, m: dict) -> str:
    arrow = "→" if owner_from(m.get("from", ""), cfg.owner_tokens) else "←"
    return f"mid:{m['id']} {stamp(cfg, m.get('internalDate'))} {arrow} {from_display(m.get('from', ''))}"


def upto_value(cfg: Config, m: dict) -> str:
    return f"messageId:{m['id']} ({stamp(cfg, m.get('internalDate'))})"


def strip_quotes(body: str, limit: int = 2500) -> str:
    text = "\n".join(l for l in (body or "").splitlines() if not l.lstrip().startswith(">")).strip()
    return text[:limit] + (" …" if len(text) > limit else "")


def classify(msgs: list[dict], entry: dict | None, known: set[str]) -> dict[str, str]:
    in_entry = harvest_entry(entry) if entry else set()
    return {m["id"]: ("entry" if m["id"] in in_entry else ("known" if m["id"] in known else "new")) for m in msgs}


def pick_home(cands: list[tuple[str, Path, dict]], todo_id: str | None) -> tuple[str, Path, dict] | None:
    """home entry = 結ぶ項目に link する entry > 印を持つ entry > id の日付が新しい entry。"""
    if not cands:
        return None

    def key(c):
        e = c[2]
        return (1 if (todo_id and todo_id in harvest_todo_refs(e)) else 0,
                1 if isinstance(e.get("recorded_upto"), str) else 0, str(e.get("id", "")))
    return sorted(cands, key=key, reverse=True)[0]


def yaml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def render_new_entry(cfg: Config, entry_id: str, msgs: list[dict], record_ids: list[str], account: str,
                     todo_ids: list[str], summary: str, tid: str) -> str:
    rec = [m for m in msgs if m["id"] in record_ids]
    anchor, latest = rec[0], rec[-1]
    ours = owner_from(anchor.get("from", ""), cfg.owner_tokens)
    lines = [f'- id: "{entry_id}"', f"  subject: {yaml_str(anchor.get('subject', '') or '(no subject)')}",
             f"  from: {yaml_str(anchor.get('from', ''))}"]
    if anchor.get("to"):
        lines.append(f"  to: {yaml_str(anchor['to'])}")
    if anchor.get("cc"):
        lines.append(f"  cc: {yaml_str(anchor['cc'])}")
    lines += [f"  account: {account}",
              f"  {'sent' if ours else 'received'}: \"{stamp(cfg, anchor.get('internalDate'))}\"",
              f'  threadId: "{tid}"', f'  messageId: "{anchor["id"]}"',
              f"  recorded_upto: {yaml_str(upto_value(cfg, latest))}", "  messages:"]
    lines += [f"    - {yaml_str(message_line(cfg, m))}" for m in rec]
    lines.append(f"  category: {cfg.category_out if owner_from(latest.get('from', ''), cfg.owner_tokens) else cfg.category_in}")
    if todo_ids:
        lines.append("  related_todo:")
        lines += [f'    - "{t}"' for t in todo_ids]
    lines.append("  summary: |")
    lines += [f"    {l}" for l in (summary.strip().splitlines() or ["(summary not written)"])]
    return "\n".join(lines) + "\n"


def find_block(lines: list[str], entry_id: str) -> tuple[int, int] | None:
    starts = [i for i, l in enumerate(lines) if l.startswith("- id:")]
    for k, i in enumerate(starts):
        m = ENTRY_START_RE.match(lines[i])
        if m and m.group(1).strip() == entry_id:
            return i, (starts[k + 1] if k + 1 < len(starts) else len(lines))
    return None


def field_span(lines: list[str], s: int, e: int, fld: str) -> tuple[int, int] | None:
    pat = re.compile(rf"^  {re.escape(fld)}:(\s|$)")
    for i in range(s, e):
        if pat.match(lines[i]):
            j = i + 1
            while j < e and (lines[j].startswith("    ") or lines[j].startswith("  -") or not lines[j].strip()):
                if not lines[j].strip() and (j + 1 >= e or not (lines[j + 1].startswith("    ") or lines[j + 1].startswith("  -"))):
                    break
                j += 1
            return i, j
    return None


def _block_tail(lines: list[str], s: int, e: int) -> int:
    j = e
    while j > s and not lines[j - 1].strip():
        j -= 1
    return j


def update_entry_text(cfg: Config, text: str, entry_id: str, msgs: list[dict], record_ids: list[str],
                      todo_id: str | None, add_thread: bool, tid: str, reset: bool = False) -> str:
    """既存 entry に threadId (無ければ) / recorded_upto / messages / related_todo を書く (置換か挿入)。

    reset=False (通常の記録): 索引 = 既存の行 ∪ この entry が持つ id (threadId と同値の root を含む = agent が今 thread を
      見て記録している) ∪ 今回記録する id。
    reset=True (移行): 索引 = record_ids ∪ 既存の行。 ただし thread の root は record_ids に無ければ載せない。
      残る id が無ければ印と索引を外す。
    """
    lines = text.split("\n")
    span = find_block(lines, entry_id)
    if span is None:
        raise KeyError(entry_id)
    s, e = span
    entry = yaml.safe_load("\n".join(lines[s:e])) or [{}]
    entry = entry[0] if isinstance(entry, list) else entry
    by_id = {m["id"]: m for m in msgs}
    existing = [x for x in (entry.get("messages") or []) if isinstance(x, str)]
    have = {MSG_LINE_RE.match(x).group(1) for x in existing if MSG_LINE_RE.match(x)}
    new_lines = [x for x in existing if not any(x.startswith(f"mid:{mid} ") for mid in by_id)]  # thread に無い行は残す
    if reset:
        root = msgs[0]["id"] if msgs else None
        keep = {mid for mid in have if not (mid == root and mid not in record_ids)}
        want_ids = [mid for mid in [m["id"] for m in msgs] if mid in record_ids or mid in keep]
    else:
        own = harvest_entry(entry) & set(by_id)
        want_ids = [mid for mid in [m["id"] for m in msgs] if mid in have or mid in own or mid in record_ids]
    for mid in want_ids:
        old = next((x for x in existing if x.startswith(f"mid:{mid} ")), None)
        new_lines.append(old if old is not None else message_line(cfg, by_id[mid]))
    latest = by_id[want_ids[-1]] if want_ids else None
    edits = []
    if reset and not want_ids and not new_lines:
        for f in ("recorded_upto", "messages"):
            fs = field_span(lines, s, e, f)
            if fs:
                edits.append((fs[0], fs[1], []))
        for a, b, rep in sorted(edits, key=lambda x: (x[0], x[1]), reverse=True):
            lines[a:b] = rep
        return "\n".join(lines)
    upto_line = f"  recorded_upto: {yaml_str(upto_value(cfg, latest))}" if latest else None
    sp = field_span(lines, s, e, "recorded_upto")
    if sp and upto_line:
        edits.append((sp[0], sp[1], [upto_line]))
    msp = field_span(lines, s, e, "messages")
    mblock = ["  messages:"] + [f"    - {yaml_str(x)}" for x in new_lines]
    if msp:
        edits.append((msp[0], msp[1], mblock))
    ins = None
    for f in ("email_ref", "messageId", "dup_messageId", "threadId"):
        fs = field_span(lines, s, e, f)
        if fs and (ins is None or fs[1] > ins):
            ins = fs[1]
    if ins is None:
        for f in ("category", "related_todo", "cross_ref", "summary", "notes", "log"):
            fs = field_span(lines, s, e, f)
            if fs:
                ins = fs[0]
                break
    if ins is None:
        ins = _block_tail(lines, s, e)
    insert_lines = []
    if add_thread and not thread_ids(entry.get("threadId")):
        insert_lines.append(f'  threadId: "{tid}"')
    if not sp and upto_line:
        insert_lines.append(upto_line)
    if not msp:
        insert_lines += mblock
    if insert_lines:
        edits.append((ins, ins, insert_lines))
    if todo_id and todo_id not in harvest_todo_refs(entry):
        rsp = field_span(lines, s, e, "related_todo")
        if rsp:
            edits.append((rsp[1], rsp[1], [f'    - "{todo_id}"']))
        else:
            pos = None
            for f in ("cross_ref", "summary", "notes", "log"):
                fs = field_span(lines, s, e, f)
                if fs:
                    pos = fs[0]
                    break
            pos = _block_tail(lines, s, e) if pos is None else pos
            edits.append((pos, pos, ["  related_todo:", f'    - "{todo_id}"']))
    for a, b, rep in sorted(edits, key=lambda x: (x[0], x[1]), reverse=True):
        lines[a:b] = rep
    return "\n".join(lines)


def update_todo_text(text: str, todo_id: str, context: str, today: str, status: str | None, tid: str | None) -> str:
    lines = text.split("\n")
    span = find_block(lines, todo_id)
    if span is None:
        raise KeyError(todo_id)
    s, e = span
    entry = yaml.safe_load("\n".join(lines[s:e]))[0]
    edits = []
    ctx_line = f"  status_context: {yaml_str(context)}"
    sp = field_span(lines, s, e, "status_context")
    if sp:
        edits.append((sp[0], sp[1], [ctx_line]))
    else:
        st = field_span(lines, s, e, "status")
        pos = st[1] if st else _block_tail(lines, s, e)
        edits.append((pos, pos, [ctx_line]))
    up = field_span(lines, s, e, "updated")
    up_line = f'  updated: "{today}"'
    if up:
        edits.append((up[0], up[1], [up_line]))
    else:
        cr = field_span(lines, s, e, "created")
        pos = cr[1] if cr else _block_tail(lines, s, e)
        edits.append((pos, pos, [up_line]))
    if status:
        st = field_span(lines, s, e, "status")
        if st:
            edits.append((st[0], st[1], [f"  status: {status}"]))
    er = entry.get("email_ref")
    if tid and (er is None or (isinstance(er, str) and not er.strip())):
        es = field_span(lines, s, e, "email_ref")
        er_line = f'  email_ref: "threadId:{tid}"'
        if es:
            edits.append((es[0], es[1], [er_line]))
        else:
            src = field_span(lines, s, e, "source")
            pos = src[1] if src else _block_tail(lines, s, e)
            edits.append((pos, pos, [er_line]))
    for a, b, rep in sorted(edits, key=lambda x: (x[0], x[1]), reverse=True):
        lines[a:b] = rep
    return "\n".join(lines)


def append_entry_text(text: str, entry_text: str) -> str:
    base = text.rstrip("\n")
    return (base + "\n\n" if base else "") + entry_text


def check_entry(entry: dict) -> list[str]:
    """印と索引の整合 (--check の 1 entry 分)。 問題の list (空 = OK)。"""
    probs = []
    upto, msgs = entry.get("recorded_upto"), entry.get("messages")
    if upto is None and msgs is None:
        return probs
    if upto is None or msgs is None:
        return ["recorded_upto と messages は対で書く (片方だけ)"]
    um = UPTO_RE.match(str(upto))
    if not um:
        return [f"recorded_upto の書式: {upto!r}"]
    mids, stamps = [], []
    for x in msgs if isinstance(msgs, list) else []:
        m = MSG_LINE_RE.match(str(x))
        if not m:
            probs.append(f"messages 行の書式: {x!r}")
            continue
        mids.append(m.group(1))
        stamps.append(m.group(2))
    if not mids:
        return probs + ["messages が空"]
    if um.group(1) not in mids:
        probs.append("recorded_upto の id が messages に無い")
    if stamps and um.group(2) != max(stamps):
        probs.append(f"recorded_upto {um.group(2)} ≠ messages の最新 {max(stamps)} (印の進め忘れ or 手書き)")
    if stamps != sorted(stamps):
        probs.append("messages が日付順でない")
    if not set(mids) <= harvest_entry(entry):
        probs.append("round-trip: messages の id が harvester で拾われない")
    return probs


# ============================================================
# 書き込み (= 読み直し → 書く → 再 parse → 検証 → 外れたら戻す)
# ============================================================
class WriteFailed(Exception):
    pass


def write_verified(path: Path, new_text: str, verify) -> None:
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_text, encoding="utf-8")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        why = verify(data if isinstance(data, list) else None)
    except Exception as e:
        why = f"再 parse 失敗: {str(e).splitlines()[0] if str(e) else e}"
    if why:
        path.write_text(old, encoding="utf-8")
        raise WriteFailed(f"{path}: {why} — 元の text に戻した")


def _verify_inbox(entry_id: str, n_before: int, created: bool, want_mids: set[str]):
    def v(data):
        if data is None:
            return "list として読めない"
        if len(data) != n_before + (1 if created else 0):
            return f"entry 数が {n_before} → {len(data)} (期待 {n_before + (1 if created else 0)})"
        e = next((x for x in data if isinstance(x, dict) and x.get("id") == entry_id), None)
        if e is None:
            return f"entry {entry_id} が無い"
        probs = check_entry(e)
        if probs:
            return "; ".join(probs)
        if not want_mids <= harvest_entry(e):
            return "round-trip: 書いた mid が harvester で拾われない"
        return None
    return v


def _verify_todo(todo_id: str, n_before: int, context: str, today: str, status: str | None):
    def v(data):
        if data is None or len(data) != n_before:
            return "entry 数が変わった / 読めない"
        t = next((x for x in data if isinstance(x, dict) and x.get("id") == todo_id), None)
        if t is None:
            return f"項目 {todo_id} が無い"
        if t.get("status_context") != context:
            return "status_context が期待と違う"
        if str(t.get("updated")) != today:
            return "updated が期待と違う"
        if status and t.get("status") != status:
            return "status が期待と違う"
        return None
    return v


# ============================================================
# 1 回の記録 (plan → 表示 → apply)
# ============================================================
def resolve_target(cfg: Config, target: str, ledger: Ledger, gmail, account_opt: str | None):
    notes = []
    default = cfg.accounts[0] if cfg.accounts else ""
    if target in ledger.todos:
        _, _, todo = ledger.todos[target]
        pairs = resolve_threads(todo, ledger.meta, ledger.inverse, known_accounts=cfg.accounts, default_account=default)
        if account_opt:
            pairs = [(t, account_opt) for t, _ in pairs]
        if not pairs:
            notes.append(f"項目 {target} からは thread を辿れない (cross_ref の inbox 参照 / email_ref / related_todo の逆引きが空)")
        return pairs, target, notes
    if target in ledger.by_id:
        _, _, e = ledger.by_id[target]
        acct = account_opt or norm_account(e.get("account"), cfg.accounts) or default
        tids = thread_ids(e.get("threadId"))
        if tids:
            return [(t, acct) for t in tids], None, notes
        for mid in sorted(harvest_entry(e)):
            t = gmail.thread_of_message(acct, mid)
            if t:
                return [(t, acct)], None, notes
        notes.append(f"entry {target} に threadId が無く、 id から thread を引けなかった")
        return [], None, notes
    if HEX_RE.match(target):
        for _, _, e in ledger.inbox:
            if target in thread_ids(e.get("threadId")) or target in harvest_entry(e):
                acct = account_opt or norm_account(e.get("account"), cfg.accounts) or default
                if target in thread_ids(e.get("threadId")):
                    return [(target, acct)], None, notes
                t = gmail.thread_of_message(acct, target)
                if t:
                    return [(t, acct)], None, notes
        for acct in ([account_opt] if account_opt else list(cfg.accounts)):
            if gmail.service(acct) is None:
                continue
            t = gmail.thread_of_message(acct, target)
            if t:
                if not account_opt:
                    notes.append(f"account は {acct} と推定 (最初に当たった account。 違えば --account)")
                return [(t, acct)], None, notes
            if gmail.thread(acct, target, full=False):
                if not account_opt:
                    notes.append(f"account は {acct} と推定 (最初に当たった account。 違えば --account)")
                return [(target, acct)], None, notes
        notes.append(f"{target} はどの account でも引けない (項目 id / entry id でもない)")
        return [], None, notes
    notes.append(f"{target} は項目 id / entry id / 16 進 id のどれでもない")
    return [], None, notes


def plan_thread(cfg: Config, tid: str, account: str, msgs: list[dict], ledger: Ledger, todo_id: str | None, args) -> dict:
    ids = {m["id"] for m in msgs}
    cands = ledger.entries_for_thread(tid, ids)
    home = pick_home(cands, todo_id)
    state = classify(msgs, home[2] if home else None, ledger.known)
    new_ids = [m["id"] for m in msgs if state[m["id"]] == "new"]
    known_ids = [m["id"] for m in msgs if state[m["id"]] == "known"]
    record_ids = [m["id"] for m in msgs if state[m["id"]] != "entry"]
    p = {"tid": tid, "account": account, "msgs": msgs, "state": state, "home": home, "cands": cands,
         "new": new_ids, "known_elsewhere": known_ids, "record": record_ids, "warn": [], "create": None}
    if home is None:
        name = args.ledger_for_new or (ledger.todos[todo_id][0] if todo_id and todo_id in ledger.todos else cfg.ledgers[0])
        anchor = next((m for m in msgs if m["id"] in record_ids), msgs[0] if msgs else None)
        if anchor is None:
            return p
        if args.id:
            eid = args.id
        elif args.slug:
            kind = "sent" if owner_from(anchor.get("from", ""), cfg.owner_tokens) else "received"
            eid = f"{stamp(cfg, anchor.get('internalDate'))[:10]}-{args.slug}-{kind}"
        else:
            eid = None
            p["warn"].append("新規 entry になる = --slug <romaji> か --id <entry id> が要る (apply しない)")
        if eid and eid in ledger.by_id:
            p["warn"].append(f"entry id {eid} は既に在る (--id で別の id を)")
            eid = None
        if eid:
            p["create"] = {"ledger": name, "path": cfg.root / name / "inbox" / f"{eid[:7]}.yaml", "id": eid}
            if not record_ids:
                p["record"] = [m["id"] for m in msgs]
    return p


def show_plan(cfg: Config, p: dict, out=print) -> None:
    h = p["home"]
    where = (f"{h[0]}/{h[1].name}:{h[2].get('id')}" if h else
             (f"新規 → {p['create']['ledger']}/{p['create']['path'].name}:{p['create']['id']}" if p["create"] else "新規 (id 未定)"))
    out(f"\n● thread {p['tid']} ({p['account']}) — {len(p['msgs'])} 通 / 未記録 {len(p['new'])} / 他所で記録済み {len(p['known_elsewhere'])} / home = {where}")
    if len(p["cands"]) > 1:
        out(f"  (この thread の entry は {len(p['cands'])} 件: " + ", ".join(f"{c[0]}:{c[2].get('id')}" for c in p["cands"]) + " — home に足す。 他は触らない)")
    for m in p["msgs"]:
        tag = {"entry": "  記録済 ", "known": "  他所済 ", "new": "★ 未記録 "}[p["state"][m["id"]]]
        out(f"  {tag} {message_line(cfg, m)}  {(m.get('subject') or '')[:60]}")
    for m in p["msgs"]:
        if p["state"][m["id"]] == "new" and m.get("body"):
            out(f"\n  ── 未記録 {m['id']} {from_display(m.get('from', ''))} {stamp(cfg, m.get('internalDate'))} ──")
            out("  " + strip_quotes(m["body"]).replace("\n", "\n  "))
    for w in p["warn"]:
        out(f"  ⚠️ {w}")


def compose_context(cfg: Config, p: dict, today: str, nxt: str) -> str:
    rec = [m for m in p["msgs"] if m["id"] in p["record"]]
    latest = rec[-1] if rec else p["msgs"][-1]
    name, subj = from_display(latest.get("from", "")), (latest.get("subject") or "")[:40]
    tpl = cfg.ctx_sent if owner_from(latest.get("from", ""), cfg.owner_tokens) else cfg.ctx_reply
    return tpl.format(date=today, name=name, subj=subj, next=nxt)


def apply_plan(cfg: Config, p: dict, ledger: Ledger, todo_id: str | None, args, today: str, out=print) -> list[Path]:
    written = []
    tid, msgs, rec_ids = p["tid"], p["msgs"], p["record"]
    if p["home"]:
        _, path, entry = p["home"]
        text = path.read_text(encoding="utf-8")  # 書く直前に読み直す (並列 session)
        n_before = len([x for x in (yaml.safe_load(text) or []) if isinstance(x, dict)])
        new_text = update_entry_text(cfg, text, entry["id"], msgs, rec_ids, todo_id, add_thread=True, tid=tid)
        if new_text != text:
            want = set(rec_ids) | (harvest_entry(entry) & {m["id"] for m in msgs})
            write_verified(path, new_text, _verify_inbox(entry["id"], n_before, False, want))
            written.append(path)
        else:
            out(f"  (entry {entry['id']} は変更なし)")
    elif p["create"]:
        c = p["create"]
        y, mo = int(c["id"][:4]), int(c["id"][5:7])
        text = c["path"].read_text(encoding="utf-8") if c["path"].exists() else cfg.month_header.format(year=y, month=mo) + "\n"
        n_before = len([x for x in (yaml.safe_load(text) or []) if isinstance(x, dict)])
        entry_text = render_new_entry(cfg, c["id"], msgs, rec_ids, p["account"], [todo_id] if todo_id else [], args.summary or "", tid)
        write_verified(c["path"], append_entry_text(text, entry_text), _verify_inbox(c["id"], n_before, True, set(rec_ids)))
        written.append(c["path"])
    if todo_id and not args.no_todo:
        _, tpath, _ = ledger.todos[todo_id]
        text = tpath.read_text(encoding="utf-8")
        n_before = len([x for x in (yaml.safe_load(text) or []) if isinstance(x, dict)])
        ctx = compose_context(cfg, p, today, args.next)
        write_verified(tpath, update_todo_text(text, todo_id, ctx, today, args.status, tid),
                       _verify_todo(todo_id, n_before, ctx, today, args.status))
        written.append(tpath)
    return written


def run_record(cfg: Config, args, ledger: Ledger, gmail, today: str, out=print) -> int:
    if ledger.broken:
        for b in ledger.broken:
            out(f"⚠️ 読めない台帳: {b}")
        out("→ 台帳が壊れている間は書かない (exit 3)")
        return 3
    if args.status and cfg.status_enum is not None and args.status not in cfg.status_enum:
        out(f"--status は {sorted(cfg.status_enum)} のどれか (exit 1)")
        return 1
    if args.summary and len(args.summary.strip().splitlines()) > SUMMARY_MAX_LINES:
        out(f"⚠️ summary が {SUMMARY_MAX_LINES} 行を超えている = 事実は案件の正本か項目の notes へ、 entry は pointer に")
    pairs, todo_from_target, notes = resolve_target(cfg, args.target, ledger, gmail, args.account)
    todo_id = args.todo or todo_from_target
    for n in notes:
        out(f"  ℹ️ {n}")
    if todo_id and todo_id not in ledger.todos:
        out(f"項目 {todo_id} がどの台帳にも無い (exit 1)")
        return 1
    if not pairs:
        out("thread が決まらない (exit 1)")
        return 1
    plans = []
    seen_roots: set[str] = set()
    for tid, acct in pairs:
        msgs = gmail.thread(acct, tid, full=True)
        if msgs is None:
            out(f"\n● thread {tid} ({acct}) — Gmail から引けなかった (auth / 404 / 一時失敗)。 未記録扱いにはしない")
            continue
        if not msgs:
            out(f"\n● thread {tid} ({acct}) — message 0 通")
            continue
        if msgs[0]["id"] in seen_roots:
            continue  # 返信の messageId から引き直した先が既に見た thread (= 同じ thread を 2 度出さない)
        seen_roots.add(msgs[0]["id"])
        tid = getattr(gmail, "last_tid", None) or tid   # 返信の messageId から引き直した場合は本当の thread id
        p = plan_thread(cfg, tid, acct, msgs, ledger, todo_id, args)
        show_plan(cfg, p, out)
        plans.append(p)
    if not plans:
        out("記録できる thread が無い (exit 3)")
        return 3
    if todo_id and not args.no_todo and not args.next:
        out("\n結ぶ項目の現在地を書くには --next \"<次の一手 1 行>\" が要る (項目を触らないなら --no-todo)")
        if args.apply:
            return 1
    if not args.apply:
        out("\n(dry-run。 書くなら --apply)")
        return 0
    creates = [p for p in plans if p["home"] is None]
    if any(p["create"] is None for p in creates):
        out("新規 entry の id が決まらない thread がある = --slug / --id (exit 1)")
        return 1
    if len(creates) > 1:
        out("新規 entry が 2 つ以上になる = thread を 1 つずつ (threadId を渡す) (exit 1)")
        return 1
    written: list[Path] = []
    try:
        for p in plans:
            written += apply_plan(cfg, p, ledger, todo_id, args, today, out)
    except WriteFailed as e:
        out(f"\n✗ {e} (exit 3)")
        return 3
    for w in dict.fromkeys(written):
        out(f"✓ 書いた: {w}")
    return 0


# ============================================================
# --check / --schema / --migrate
# ============================================================
def run_check(ledger: Ledger, out=print, quiet: bool = False) -> int:
    """印と索引の整合。 quiet=True (dashboard 用) は問題がある時だけ出力する (= 0 件なら無音)。"""
    n_ok = n_bad = 0
    for name, p, e in ledger.inbox:
        if e.get("recorded_upto") is None and e.get("messages") is None:
            continue
        probs = check_entry(e)
        if probs:
            n_bad += 1
            out(f"🔴 {name}/{p.name}:{e.get('id')}: " + "; ".join(probs))
        else:
            n_ok += 1
    if n_bad or ledger.broken or not quiet:
        out(f"check: 印つき entry {n_ok + n_bad} 件、 問題 {n_bad} 件" + (" (台帳が読めない: " + "; ".join(ledger.broken) + ")" if ledger.broken else ""))
    return 1 if n_bad or ledger.broken else 0


SCHEMA_EXAMPLE = '''- id: "2026-01-15-example-payment-received"      # 命名 = 記録した最初の message の日付 + 相手 + 用件 (+ received / sent)
  subject: "Re: Registration and Payment"
  from: "Example Admin <admin@example.org>"        # 最初に記録した message の差出人
  to: "owner@example.org"
  account: acct-a
  received: "2026-01-15 21:25"
  threadId: "0000000000000001"
  messageId: "0000000000000002"                    # 最初に記録した message (互換)
  recorded_upto: "messageId:0000000000000003 (2026-01-22 16:56)"   # 読んだ位置の印。 道具だけが進める
  messages:                                        # 機械が書く索引 (1 通 1 行、 ← 相手発 / → 自分発)
    - "mid:0000000000000001 2026-01-03 10:00 → Owner Example"
    - "mid:0000000000000002 2026-01-15 21:25 ← Example Admin"
    - "mid:0000000000000003 2026-01-22 16:56 ← Example Admin"
  category: received                               # message の素性だけ (案件の状態は項目側)
  related_todo:
    - "2026-01-30-example-payment"                 # 裸 id
  summary: |                                       # 3 行まで。 事実の正本は書かない (pointer だけ)
    参加費の支払いと領収書のやりとり (領収書の中身 = 案件の正本が持つ)。
'''


def _without_marks(e: dict) -> dict:
    return {k: v for k, v in e.items() if k not in ("recorded_upto", "messages")}


def run_migrate(cfg: Config, name: str, ledger: Ledger, gmail, apply: bool, limit: int | None, only: str | None,
                out=print, remigrate: bool = False) -> int:
    if name not in cfg.ledgers:
        out(f"台帳は {cfg.ledgers} のどれか")
        return 1
    if ledger.broken:
        out("台帳が壊れている間は書かない: " + "; ".join(ledger.broken))
        return 3
    per_file: dict[Path, list[tuple[dict, list[dict], list[str]]]] = {}
    stats = {"done": 0, "skip_has": 0, "no_ids": 0, "no_match": 0, "fetch_fail": 0}
    n = 0
    for r, p, e in [(r, p, e) for r, p, e in ledger.inbox if r == name and (only is None or e.get("id") == only)]:
        if limit is not None and n >= limit:
            break
        marked = e.get("recorded_upto") is not None or e.get("messages") is not None
        if marked and not remigrate:
            stats["skip_has"] += 1
            continue
        base = _without_marks(e)
        ids = harvest_entry(base)
        msg_ids = harvest_message_ids(base)
        if not ids:
            stats["no_ids"] += 1
            continue
        n += 1
        acct = norm_account(e.get("account"), cfg.accounts)
        accounts = [acct] if acct else list(cfg.accounts)
        tids = thread_ids(e.get("threadId")) or sorted(set(THREADID_RE.findall("\n".join(map(str, base.values())))))
        msgs = None
        for a in accounts:
            if gmail.service(a) is None:
                continue
            cand_tids = list(tids)
            if not cand_tids:
                for mid in sorted(ids):
                    t = gmail.thread_of_message(a, mid)
                    if t:
                        cand_tids.append(t)
                        break
            for t in cand_tids:
                msgs = gmail.thread(a, t, full=False)
                if msgs:
                    have_lines = {MSG_LINE_RE.match(x).group(1) for x in (e.get("messages") or []) if isinstance(x, str) and MSG_LINE_RE.match(x)}
                    known = {k for k in (msg_ids | have_lines) if HEX_RE.match(k)}
                    if known - {m["id"] for m in msgs}:
                        msgs = gmail.thread(a, t, full=False, refresh=True) or msgs
                    acct = a
                    break
            if msgs:
                break
        if not msgs:
            stats["fetch_fail"] += 1
            out(f"  ⚠️ {p.name}:{e.get('id')}: thread を引けなかった (account={acct or '?'} ids={len(ids)})")
            continue
        rec = [m["id"] for m in msgs if m["id"] in msg_ids]
        if not rec and not marked:
            stats["no_match"] += 1
            out(f"  · {p.name}:{e.get('id')}: message として記録した id が thread に無い (threadId だけ?) = 印なし")
            continue
        per_file.setdefault(p, []).append((e, msgs, rec))
        stats["done"] += 1
    out(f"\nmigrate {name}: 追記 {stats['done']} / 既に印あり {stats['skip_has']} / id 無し {stats['no_ids']} / "
        f"一致なし {stats['no_match']} / 引けず {stats['fetch_fail']}")
    if not apply:
        shown = 0
        for p, items in per_file.items():
            text = p.read_text(encoding="utf-8")
            new_text = text
            for e, msgs, rec in items:
                new_text = update_entry_text(cfg, new_text, e["id"], msgs, rec, None, add_thread=False, tid="", reset=True)
            if shown < 2:
                diff = list(difflib.unified_diff(text.split("\n"), new_text.split("\n"), lineterm="", n=1))
                out(f"\n--- 差分の例 {p.name} ({len(items)} entry, 先頭 40 行) ---")
                out("\n".join(diff[:40]))
                shown += 1
        out("\n(dry-run。 書くなら --apply)")
        return 0
    for p, items in per_file.items():
        text = p.read_text(encoding="utf-8")
        n_before = len([x for x in (yaml.safe_load(text) or []) if isinstance(x, dict)])
        new_text = text
        for e, msgs, rec in items:
            new_text = update_entry_text(cfg, new_text, e["id"], msgs, rec, None, add_thread=False, tid="", reset=True)

        def verify(data, items=items, n_before=n_before):
            if data is None or len(data) != n_before:
                return "entry 数が変わった / 読めない"
            byid = {x.get("id"): x for x in data if isinstance(x, dict)}
            for e, msgs, rec in items:
                x = byid.get(e["id"])
                if x is None:
                    return f"{e['id']} が無い"
                pr = check_entry(x)
                if pr:
                    return f"{e['id']}: " + "; ".join(pr)
                base = _without_marks(e)
                if not (harvest_entry(base) <= harvest_entry(x) <= harvest_entry(e)):
                    return f"{e['id']}: harvest 集合が変わった (追記だけのはず)"
                hm_b, hm_x, hm_e = harvest_message_ids(base), harvest_message_ids(x), harvest_message_ids(e)
                if not (hm_b <= hm_x <= hm_e):
                    return f"{e['id']}: message 集合が変わった (message として記録した id しか索引に書かないはず)"
                root = msgs[0]["id"] if msgs else None
                if root and root in hm_x and root not in hm_b:
                    return f"{e['id']}: threadId 由来の root message が索引に載った"
                if thread_ids(x.get("threadId")) != thread_ids(e.get("threadId")):
                    return f"{e['id']}: threadId が変わった"
            return None
        try:
            write_verified(p, new_text, verify)
        except WriteFailed as ex:
            out(f"✗ {ex} (exit 3)")
            return 3
        out(f"✓ 書いた: {p} ({len(items)} entry)")
    return 0


# ============================================================
# selftest (= 偽の Gmail + 2 台帳の fixture)
# ============================================================
class FakeGmail:
    def __init__(self, threads: dict[tuple[str, str], list[dict]], accounts=("acct-a", "acct-b")):
        self.threads, self.accounts = threads, set(accounts)

    def service(self, account):
        return object() if account in self.accounts else None

    def thread(self, account, tid, full=True, refresh=False):
        m = self.threads.get((account, tid))
        return [dict(x) for x in m] if m is not None else None

    def thread_of_message(self, account, mid):
        for (a, t), msgs in self.threads.items():
            if a == account and any(m["id"] == mid for m in msgs):
                return t
        return None


def _selftest() -> int:
    import shutil
    fails = 0

    def check(cond, name):
        nonlocal fails
        print(("  PASS: " if cond else "  FAIL: ") + name)
        if not cond:
            fails += 1

    def msg(mid, ts, frm, subj="Re: test", body="本文\n> 引用"):
        return {"id": mid, "internalDate": str(ts), "from": frm, "to": "owner@example.org", "cc": "",
                "subject": subj, "date": "", "body": body}

    T = 1790035200000  # = 2026-09-22 00:00 UTC の epoch ms (1 時間おきに 5 通)
    OW, CP = "Owner Example <owner@example.org>", "Counter Part <cp@example.org>"
    m1, m2, m3, m4, m5 = "aaaa000000000001", "aaaa000000000002", "aaaa000000000003", "aaaa000000000004", "aaaa000000000005"
    threads = {("acct-a", m1): [msg(m1, T, OW), msg(m2, T + 3600000, CP), msg(m3, T + 7200000, CP),
                                msg(m4, T + 10800000, CP, body="返事の本文です\n> 前の引用"), msg(m5, T + 14400000, OW)],
               ("acct-a", "bbbb000000000001"): [msg("bbbb000000000001", T, CP), msg("bbbb000000000002", T + 1000, CP)]}
    td = Path(tempfile.mkdtemp(prefix="record-reply-selftest-"))
    cfg = Config(root=td, ledgers=["ledger-a", "ledger-b"], accounts=("acct-a", "acct-b"), owner_tokens=("owner@",),
                 status_enum={"open", "waiting", "doing", "done"}, tz="UTC", cache_dir=td / "cache")
    try:
        (td / "ledger-a" / "inbox").mkdir(parents=True)
        (td / "ledger-b" / "inbox").mkdir(parents=True)
        (td / "ledger-a" / "inbox" / "2026-09.yaml").write_text(
            '# ledger\n\n- id: "2026-09-20-e1"\n  subject: "Re: test"\n  account: acct-a\n  threadId: "aaaa000000000001"\n'
            f'  messageId: "{m1}"\n  category: sent\n  related_todo:\n    - "2026-09-30-todo-a"\n  summary: |\n    sent.\n\n'
            '- id: "2026-09-21-e4"\n  subject: "x"\n  account: acct-a\n  category: fyi\n  notes: |\n    same thread (threadId:cccc000000000001).\n',
            encoding="utf-8")
        (td / "ledger-b" / "inbox" / "2026-09.yaml").write_text(
            '- id: "2026-09-21-e3"\n  subject: "Re: test"\n  account: acct-a\n  category: received\n'
            f'  email_ref: "messageId:{m2}"\n  log:\n    - "follow-up (mid:{m3})"\n  summary: |\n    recorded in ledger-b.\n',
            encoding="utf-8")
        (td / "ledger-a" / "TODO.yaml").write_text(
            '- id: "2026-09-30-todo-a"\n  task: |\n    wait for reply\n  source: email\n  email_ref: null\n  deadline: "2026-09-30"\n'
            '  status: waiting\n  priority: mid\n  created: "2026-09-20"\n  updated: "2026-09-20"\n  notes: |\n    history.\n',
            encoding="utf-8")
        (td / "ledger-b" / "TODO.yaml").write_text('- id: "2026-10-01-todo-b"\n  task: "b"\n  status: open\n  priority: mid\n  created: "2026-09-01"\n', encoding="utf-8")
        gm = FakeGmail(threads)
        out_lines: list[str] = []
        pr = out_lines.append
        ns = argparse.Namespace(target="2026-09-30-todo-a", todo=None, account=None, next="read and answer", status=None,
                                summary=None, slug=None, id=None, ledger_for_new=None, no_todo=False, apply=False)
        before = {p: p.read_text(encoding="utf-8") for p in td.rglob("*.yaml")}
        rc = run_record(cfg, ns, Ledger(cfg), gm, "2026-09-22", pr)
        text = "\n".join(out_lines)
        check(rc == 0 and "未記録 2" in text and f"★ 未記録  mid:{m4}" in text and f"★ 未記録  mid:{m5}" in text,
              "t1 legacy 4 書式から未記録 = 全 message − harvester の集合 (m4, m5)")
        check("home = ledger-a/2026-09.yaml:2026-09-20-e1" in text and "entry は 2 件" in text,
              "t2 片方の台帳にしか無い entry (ledger-b の e3) も thread の entry として見つける")
        check("返事の本文です" in text and "> 前の引用" not in text, "dry-run は未記録の本文を引用行抜きで出す")
        check(before == {p: p.read_text(encoding="utf-8") for p in td.rglob("*.yaml")}, "t4 dry-run は file を byte 単位で変えない")
        ns.apply = True
        out_lines.clear()
        check(run_record(cfg, ns, Ledger(cfg), gm, "2026-09-22", pr) == 0, "apply が exit 0")
        eo = yaml.safe_load((td / "ledger-a" / "inbox" / "2026-09.yaml").read_text(encoding="utf-8"))
        e1 = next(x for x in eo if x["id"] == "2026-09-20-e1")
        check(set(harvest_entry(e1)) >= {m1, m2, m3, m4, m5}, "t3 書いた entry の全 id が harvest_entry で拾われる (round-trip)")
        check(e1.get("recorded_upto") == f"messageId:{m5} (2026-09-22 04:00)", "recorded_upto = 最新の message (tz の刻印)")
        check(e1.get("messages", [None])[0] == f"mid:{m1} 2026-09-22 00:00 → Owner Example" and len(e1.get("messages", [])) == 5,
              "messages = legacy field の id も含めて thread の全 5 通、 日付順、 自分発は →")
        check(not check_entry(e1) and "notes" not in e1 and e1.get("category") == "sent" and len(eo) == 2,
              "t7 notes を作らず category を触らない、 entry 数は不変")
        todo = yaml.safe_load((td / "ledger-a" / "TODO.yaml").read_text(encoding="utf-8"))[0]
        check(todo.get("status_context") == "2026-09-22 sent to Owner Example (Re: test) → next: read and answer",
              "t5 status_context を上書き (最新は自分発 = ctx_sent template)")
        check(str(todo.get("updated")) == "2026-09-22" and todo.get("email_ref") == "threadId:aaaa000000000001",
              "t5 updated と email_ref (無かったので threadId 1 行)")
        raw_todo = (td / "ledger-a" / "TODO.yaml").read_text(encoding="utf-8")
        ctx_line = next(l for l in raw_todo.splitlines() if l.startswith("  status_context:"))
        check(json.loads(ctx_line.split(":", 1)[1].strip()) == todo["status_context"], "t9 status_context は 1 行の JSON 文字列")
        out_lines.clear()
        check(run_record(cfg, ns, Ledger(cfg), gm, "2026-09-22", pr) == 0 and "未記録 0" in "\n".join(out_lines), "2 回目は未記録 0 (冪等)")
        p = td / "ledger-a" / "inbox" / "2026-09.yaml"
        good, stale = f"messageId:{m5} (2026-09-22 04:00)", f"messageId:{m4} (2026-09-22 03:00)"
        p.write_text(p.read_text(encoding="utf-8").replace(good, stale), encoding="utf-8")
        out_lines.clear()
        check(run_check(Ledger(cfg), pr) == 1 and "印の進め忘れ" in "\n".join(out_lines), "t6 --check が印 ≠ 最新を赤にする")
        p.write_text(p.read_text(encoding="utf-8").replace(stale, good), encoding="utf-8")
        out_lines.clear()
        check(run_check(Ledger(cfg), pr) == 0, "t6 戻せば --check は緑")
        out_lines.clear()
        check(run_record(cfg, argparse.Namespace(**{**vars(ns), "status": "closed", "apply": False}), Ledger(cfg), gm, "2026-09-22", pr) == 1,
              "t7 enum 外の --status を拒む (exit 1)")
        out_lines.clear()
        run_record(cfg, argparse.Namespace(**{**vars(ns), "summary": "1\n2\n3\n4", "apply": False}), Ledger(cfg), gm, "2026-09-22", pr)
        check("summary が 3 行を超えている" in "\n".join(out_lines), "t7 summary 4 行目で warn")
        out_lines.clear()
        ns4 = argparse.Namespace(target="bbbb000000000001", todo="2026-10-01-todo-b", account="acct-a", next="propose dates", status="doing",
                                 summary="scheduling (facts live elsewhere).", slug=None, id=None, ledger_for_new=None, no_todo=False, apply=True)
        check(run_record(cfg, ns4, Ledger(cfg), gm, "2026-09-22", pr) == 1 and "--slug" in "\n".join(out_lines), "新規 entry は --slug / --id 無しで apply しない")
        ns4.slug = "cp-dates"
        out_lines.clear()
        rc = run_record(cfg, ns4, Ledger(cfg), gm, "2026-09-22", pr)
        ts = yaml.safe_load((td / "ledger-b" / "inbox" / "2026-09.yaml").read_text(encoding="utf-8"))
        new = next((x for x in ts if str(x.get("id", "")).endswith("-cp-dates-received")), None)
        check(rc == 0 and new is not None and new["threadId"] == "bbbb000000000001" and new["related_todo"] == ["2026-10-01-todo-b"]
              and len(new["messages"]) == 2 and not check_entry(new) and new["category"] == "received",
              "新規 entry を項目の台帳 (ledger-b) の月 file に作る (threadId / related_todo / messages / category)")
        tb = yaml.safe_load((td / "ledger-b" / "TODO.yaml").read_text(encoding="utf-8"))[0]
        check(tb.get("status") == "doing" and tb.get("email_ref") == "threadId:bbbb000000000001", "--status と email_ref を項目に書く")
        check(new is not None and set(harvest_entry(new)) >= {"bbbb000000000001", "bbbb000000000002"}, "t3 新規 entry も round-trip")
        pth = td / "ledger-a" / "inbox" / "2026-09.yaml"
        orig = pth.read_text(encoding="utf-8")
        try:
            write_verified(pth, orig + "\n- id: [broken\n", lambda d: None)
            check(False, "t8 壊れた YAML で例外")
        except WriteFailed:
            check(pth.read_text(encoding="utf-8") == orig, "t8 再 parse 失敗で元の text に戻す (exit 3 相当)")
        (td / "ledger-a" / "inbox" / "2026-08.yaml").write_text(
            f'- id: "2026-08-01-legacy"\n  subject: "old"\n  account: acct-a\n  email_ref: "messageId:{m2}"\n  category: received\n  summary: |\n    old record.\n',
            encoding="utf-8")
        out_lines.clear()
        rc = run_migrate(cfg, "ledger-a", Ledger(cfg), gm, apply=True, limit=None, only="2026-08-01-legacy", out=pr)
        old = yaml.safe_load((td / "ledger-a" / "inbox" / "2026-08.yaml").read_text(encoding="utf-8"))[0]
        check(rc == 0 and old.get("messages") == [f"mid:{m2} 2026-09-22 01:00 ← Counter Part"] and "threadId" not in old
              and old.get("recorded_upto") == f"messageId:{m2} (2026-09-22 01:00)" and harvest_entry(old) == {m2},
              "t10 移行は entry 自身の message id だけを索引に書き、 threadId を足さない (harvest 集合は不変)")
        out_lines.clear()
        rc = run_migrate(cfg, "ledger-a", Ledger(cfg), gm, apply=True, limit=None, only="2026-08-01-legacy", out=pr)
        check(rc == 0 and "既に印あり 1" in "\n".join(out_lines), "移行は冪等 (印のある entry を飛ばす)")
        (td / "ledger-a" / "inbox" / "2026-07.yaml").write_text(
            f'- id: "2026-07-01-thread-only-root"\n  subject: "r"\n  account: acct-a\n  threadId: "{m1}"\n'
            f'  email_ref: "messageId:{m3}"\n  category: received\n  summary: |\n    root not read.\n', encoding="utf-8")
        out_lines.clear()
        rc = run_migrate(cfg, "ledger-a", Ledger(cfg), gm, apply=True, limit=None, only="2026-07-01-thread-only-root", out=pr)
        pth7 = td / "ledger-a" / "inbox" / "2026-07.yaml"
        tr = yaml.safe_load(pth7.read_text(encoding="utf-8"))[0]
        check(rc == 0 and tr.get("messages") == [f"mid:{m3} 2026-09-22 02:00 ← Counter Part"] and harvest_message_ids(tr) == {m3},
              "t11 移行は threadId 由来の root を索引に載せない (message 集合が不変)")
        pth7.write_text(pth7.read_text(encoding="utf-8").replace(
            f'  messages:\n    - "mid:{m3} 2026-09-22 02:00 ← Counter Part"',
            f'  messages:\n    - "mid:{m1} 2026-09-22 00:00 → Owner Example"\n    - "mid:{m3} 2026-09-22 02:00 ← Counter Part"\n'
            f'    - "mid:{m4} 2026-09-22 03:00 ← Counter Part"').replace(
            f"messageId:{m3} (2026-09-22 02:00)", f"messageId:{m4} (2026-09-22 03:00)"), encoding="utf-8")
        out_lines.clear()
        rc = run_migrate(cfg, "ledger-a", Ledger(cfg), gm, apply=True, limit=None, only="2026-07-01-thread-only-root", out=pr, remigrate=True)
        tr = yaml.safe_load(pth7.read_text(encoding="utf-8"))[0]
        check(rc == 0 and tr.get("messages") == [f"mid:{m3} 2026-09-22 02:00 ← Counter Part", f"mid:{m4} 2026-09-22 03:00 ← Counter Part"]
              and tr.get("recorded_upto") == f"messageId:{m4} (2026-09-22 03:00)",
              "t12 --remigrate は root の行だけ外し、 通常の記録で足した行 (m4) は残す")
        out_lines.clear()
        rc = run_migrate(cfg, "ledger-a", Ledger(cfg), gm, apply=True, limit=None, only="2026-07-01-thread-only-root", out=pr, remigrate=True)
        check(rc == 0 and yaml.safe_load(pth7.read_text(encoding="utf-8"))[0] == tr, "t12 --remigrate は冪等")
    finally:
        shutil.rmtree(td, ignore_errors=True)
    print(f"selftest: {'ALL PASS' if not fails else f'FAIL {fails}'}")
    return 1 if fails else 0


# ============================================================
# main
# ============================================================
def build_config(args) -> Config:
    cfg = Config(root=Path(args.root).expanduser(), ledgers=list(args.ledger or []),
                 accounts=tuple(x for x in (args.accounts or "").split(",") if x),
                 creds_dir=Path(args.creds_dir).expanduser(), owner_tokens=tuple(args.owner_token or ()),
                 status_enum=(set(x for x in args.status_enum.split(",") if x) if args.status_enum else None),
                 category_in=args.category_in, category_out=args.category_out,
                 ctx_reply=args.ctx_reply, ctx_sent=args.ctx_sent, tz=args.tz,
                 cache_dir=Path(args.cache_dir).expanduser(), month_header=args.month_header)
    return cfg


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="mail を thread 単位で台帳に記録する (既定 dry-run)")
    ap.add_argument("target", nargs="?", help="項目 id / threadId / messageId / entry id")
    ap.add_argument("--todo", help="結ぶ項目 id (target が項目 id ならそれ)")
    ap.add_argument("--account")
    ap.add_argument("--next", help="次の一手 1 行 (項目の status_context に書く)")
    ap.add_argument("--status", help="項目の status (enum を渡していれば検査)")
    ap.add_argument("--summary", help="新規 entry の summary (3 行まで)")
    ap.add_argument("--slug", help="新規 entry の id の中央 (romaji)")
    ap.add_argument("--id", help="新規 entry の id (完全指定)")
    ap.add_argument("--ledger-for-new", help="新規 entry を置く台帳 (既定 = 項目の台帳、 無ければ最初の台帳)")
    ap.add_argument("--no-todo", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="--check で問題が無ければ何も出さない (dashboard 用)")
    ap.add_argument("--schema", action="store_true")
    ap.add_argument("--migrate", metavar="LEDGER")
    ap.add_argument("--remigrate", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only")
    ap.add_argument("--selftest", action="store_true")
    # 設定 (= shim が足す)
    ap.add_argument("--root", default=".")
    ap.add_argument("--ledger", action="append", help="台帳の dir 名 (root 直下、 複数可)")
    ap.add_argument("--accounts", default="", help="Gmail の account alias を試す順 (comma 区切り、 先頭 = 既定)")
    ap.add_argument("--creds-dir", default=str(Path.home() / ".gmail-mcp"))
    ap.add_argument("--owner-token", action="append", help="From にこれを含めば自分発 (複数可)")
    ap.add_argument("--status-enum", default="", help="項目の status の enum (comma 区切り。 空 = 検査しない)")
    ap.add_argument("--category-in", default="received")
    ap.add_argument("--category-out", default="sent")
    ap.add_argument("--ctx-reply", default="{date} reply from {name} ({subj}) → next: {next}")
    ap.add_argument("--ctx-sent", default="{date} sent to {name} ({subj}) → next: {next}")
    ap.add_argument("--tz", default="local")
    ap.add_argument("--cache-dir", default=str(Path.home() / ".cache" / "record-reply"))
    ap.add_argument("--month-header", default="# {year}-{month:02d} mail ledger")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    if args.schema:
        print(SCHEMA_EXAMPLE, end="")
        return 0
    cfg = build_config(args)
    if not cfg.ledgers:
        ap.error("--ledger を 1 つ以上 (shim が渡す)")
    ledger = Ledger(cfg)
    if args.check:
        return run_check(ledger, quiet=args.quiet)
    if args.migrate:
        return run_migrate(cfg, args.migrate, ledger, Gmail(cfg, use_cache=True), args.apply, args.limit, args.only, remigrate=args.remigrate)
    if not args.target:
        ap.print_help()
        return 1
    today = datetime.now(tz=cfg.tzinfo()).strftime("%Y-%m-%d")
    return run_record(cfg, args, ledger, Gmail(cfg, use_cache=False), today)


if __name__ == "__main__":
    sys.exit(main())
