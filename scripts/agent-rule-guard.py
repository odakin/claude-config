#!/usr/bin/env python3
"""Protect agent-governance documents, enforcement configuration and declared gates; compatible approval/scan entry point.

# agent-authority:file

Normative owner: conventions/agent-rule-ownership.md. This module owns the
vendor-neutral authority predicate. The manuscript dispatcher imports it, so
Claude, Codex and Git keep one predicate and one approval store. Existing hook
commands remain compatible; this CLI forwards operational commands to that
dispatcher. --selftest exercises the generic predicate without real user data.

Built-in control paths are conservative: changing an instruction document or
permission/CI definition needs a reviewed candidate, even for a benign edit.
Ordinary application code and status/index prose are not blanket-protected.
Repositories add enforcement implementation paths in .agent-rule-guard.json;
the manifest has no exclusion/disable switch. Callers must union HEAD, index
and worktree declarations. A code file that mentions an engine is locked as a
whole unless every mention sits inside an explicit begin/end block; then the
blocks carry the lock and the rest is ordinary code (decision record and the
holes this leaves: conventions/agent-rule-ownership.md#wiring-scope). This is
not isolation from a malicious agent with write access to the checker/runtime
itself and does not interpret all prose.

Two exceptions apply only to built-in prose instruction documents (CLAUDE.md /
AGENTS.md / CONVENTIONS.md / conventions/*.md, not the guard's own rule docs,
not marker files, not manifest-declared patterns; the dispatcher also requires
a Git repository): an `agent-free` zone the owner declared is masked out of the
file lock, and a change that does not loosen a rule by proxy, whatever its form
(append, rewrite, deletion, move), is exempt from prior approval: its added
sentences carry no relaxation vocabulary or hiding markup, an edited sentence
carries no relaxing term it did not carry before, no existing sentence is moved
into a fence or comment, no new heading files the lines under it as history, the
document is not emptied, and it is not a brand-new entry document (judge_change).
Removed, replaced and flipped sentences pass; the dispatcher logs every such
change for the owner to read afterwards. Whether an edit strengthens or weakens a rule is not
decided here; the inserted-only shape and the vocabulary tripwire are proxies
with known holes (conventions/agent-rule-ownership.md#additive-and-free-zones).
Callers pass manifest patterns as extra_paths, never the expanded set of every
protected path (that set contains every tracked rule document).
"""
from __future__ import annotations

from collections import Counter
import difflib
import fnmatch
import json
from pathlib import Path, PurePosixPath
import re
import runpy
import shlex
import sys

MANIFEST_REL = ".agent-rule-guard.json"
RULE_REF_TOKENS = tuple(name + "#rule" for name in (
    "agent-rule-ownership.md", "manuscript-claim-ownership.md",
))
ENGINE_TOKENS = ("agent-rule-guard", "agent_rule_guard",
                 "manuscript-claim-guard", "manuscript_claim_guard")
WIRING_SUFFIXES = {".py", ".sh", ".js", ".ts", ".json", ".toml", ".yaml", ".yml", ".rules", ""}
ENTRYPOINT_NAMES = {"AGENTS.md", "AGENTS.override.md", "CLAUDE.md", "CONVENTIONS.md"}
CONTROL_PATTERNS = (
    "conventions/*.md", ".claude/settings*.json", ".codex/config*.toml",
    ".codex/hooks.json", ".codex/rules/*.rules", ".github/workflows/*.yml",
    ".github/workflows/*.yaml", ".pre-commit-config.yaml", ".pre-commit-config.yml",
    ".git/config", ".git/hooks/*", ".claude/hooks/*", ".codex/hooks/*",
    MANIFEST_REL,
)
MARK_FILE_RE = re.compile(r"^\s*(?:#|//|%|<!--)\s*agent-authority:file\b", re.M)
MARK_BEGIN_RE = re.compile(r"^\s*(?:#|//|%|<!--)\s*agent-authority:begin\s+id=([A-Za-z0-9._-]+)", re.M)
MARK_END_TMPL = r"^\s*(?:#|//|%|<!--)\s*agent-authority:end\s+id={id}\b"
# Owner-declared non-rule zones (status lists, generated blocks) inside prose instruction documents.
FREE_BEGIN_RE = re.compile(r"^[ \t]*<!--[ \t]*agent-free:begin[ \t]+id=([A-Za-z0-9._-]+)[ \t]*-->[ \t]*$", re.M)
FREE_END_TMPL = r"^[ \t]*<!--[ \t]*agent-free:end[ \t]+id={id}[ \t]*-->[ \t]*$"
GUARD_RULE_DOCS = {"agent-rule-ownership.md", "manuscript-claim-ownership.md"}
# Inserted text containing any of these falls back to prior approval. Substring match; the list
# over-matches on purpose (a false hit costs one approval, a miss lets an exception in unread).
RELAX_TERMS_JA = (
    "ただし", "但し", "例外", "除く", "除いて", "除外", "不要", "要らない", "いらない", "省略", "省く", "省いて",
    "省け", "免除", "適用しない", "適用外", "適用されない", "対象外", "対象としない", "任意", "構わない",
    "かまわない", "差し支えない", "限らない", "に限る", "に限って", "に限り", "のみに適用", "だけに適用",
    "してよい", "しても良い", "してもよい", "でよい", "でもよい", "て良い", "ても良い", "で良い", "なくてよい",
    "なくても", "しなくて", "ずに済", "ずとも", "優先する", "優先して", "優先させ", "上書き", "無効", "廃止",
    "撤回", "撤廃", "取り消", "緩め", "緩和", "無視", "従わな", "読まなくて", "聞かずに", "確認なし", "確認せず",
    "承認なし", "承認せず", "許可なし", "自己判断", "裁量で", "素通し", "規則ではない", "義務ではない",
    "必須ではない", "強制ではない", "効力", "拘束", "努力目標", "推奨に", "目安に", "にとどめ", "に留め",
    "なしで", "外せる", "ていい", "てもいい", "許され", "以外は", "しない限り", "でない限り", "で足りる", "で十分",
    "てよい", "てよく", "改定", "改訂", "に代えて", "に代わ", "に限った", "に限定", "だけの話", "のみの話",
    # redefinition, precedence, historicising, scope and discretion (an independent review's bypasses)
    "とは", "優先", "勝つ", "更新)", "時点の記録", "記録である", "歴史", "当時の", "参考情報", "扱うのは",
    "自分の判断", "の判断で", "独断",
)
RELAX_TERMS_EN = (
    "unless", "except", "exception", "exempt", "optional", "optionally", "skip", "not required",
    "no longer", "need not", "needn't", "don't need", "do not need", "override", "overrides", "supersede",
    "supersedes", "ignore", "disregard", "disable", "disabled", "deprecated", "obsolete", "bypass", "waive",
    "allowed to", "permitted", "omit", "relax", "loosen", "only applies", "only apply", "does not apply",
    "doesn't apply", "not apply", "no-verify", "without",
)
# Markup that hides or demotes text, and invisible characters that make a changed sentence look unchanged.
RELAX_MARKUP = ("<!--", "-->", "~~", "<div", "<span", "<details", "<style", "<script", "<template", "<noscript",
                "<iframe", "​", "‌", "‍", "⁠", "﻿", "­")
_RELAX_EN_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(t) for t in RELAX_TERMS_EN) + r")(?![A-Za-z])", re.I)
# English listed terms that are also ordinary words count only in a relaxing position: a permission or imperative to
# skip / ignore / override / disable a check or rule, "is optional", "an exception to". A name inside an anchor id,
# a link target or a hashtag is not a sentence about a rule and is dropped first (measured on two months of
# committed additions: git's ignore, a skip flag, "optional content", a namespace override, an anchor id
# "exception-by-category" and "discovery disabled" were the hits).
_EN_NOISE = re.compile(r'id="[^"]*"|\]\([^)]*\)|(?<![A-Za-z0-9])#[A-Za-z][A-Za-z0-9_-]*')
_EN_MAY = r"(?:may|can|could|should|might|allowed to|ok to|okay to|safe to|free to|just|simply|to)\s+"
_EN_GATE = (r"(?:(?:the|this|that|a|an|any|all|every|these|those|our|its)\s+)?(?:pre-?commit\s+)?"
            r"(?:checks?|reviews?|tests?|gates?|approvals?|verification|confirmation|validation|hooks?|rules?|steps?|"
            r"guards?|lint|linter|scans?|policy|policies|restrictions?|locks?|protection|prompts?|nudges?|reminders?|"
            r"warnings?|errors?|failures?|findings?|results?|deny|block|limits?|defaults?|settings?|conventions?|"
            r"instructions?)\b")
RELAX_FORMS_EN: dict[str, re.Pattern] = {
    "skip": re.compile(_EN_MAY + r"skip\b|\bskip(?:s|ped|ping)?\s+" + _EN_GATE, re.I),
    "ignore": re.compile(_EN_MAY + r"ignore\b|\bignor(?:e|es|ed|ing)\s+" + _EN_GATE, re.I),
    "optional": re.compile(r"\boptional\b(?!\s+[a-z])", re.I),  # "is optional." relaxes; "optional content" describes
    "override": re.compile(_EN_MAY + r"override\b|\boverrid(?:e|es|den|ing)\s+" + _EN_GATE, re.I),
    "exception": re.compile(r"\b(?:an|the|as an|is an|make an|makes an|made an|grant(?:ed|s)? an|allow(?:ed|s)? an|"
                            r"with an|with the)\s+exception\b|\bexceptions?\s+(?:to|for|is|are|:)", re.I),
    "disable": re.compile(_EN_MAY + r"disabl(?:e|ing)\b|\bdisabl(?:e|es|ed|ing)\s+" + _EN_GATE + r"|" + _EN_GATE +
                          r"\s+(?:is|are|was|were|be|being|can be|may be|should be|remains?|stays?)\s+disabled\b", re.I),
}
RELAX_FORMS_EN["overrides"] = RELAX_FORMS_EN["override"]
RELAX_FORMS_EN["without"] = re.compile(
    r"\bwithout\s+(?:(?:the|a|an|any|this|that|prior|my|our|their)\s+)?(?:asking|permission|consent|ruling|approvals?|"
    r"reviews?|confirmation|verification|validation|checks?|tests?|gates?|hooks?|sign-?off)\b", re.I)
RELAX_FORMS_EN["disabled"] = RELAX_FORMS_EN["disable"]
# Listed terms that are also everyday words count only in the position where they relax a rule (measured on two
# months of committed additions: the bare substring fired on a form's revision, a file overwrite, a Python exception,
# a physics constraint, "X とは違う", "…てよい種類"). The position is decided per unit (sentence), not by shrinking the
# list; a term absent from this table keeps the plain substring match (over-matching on purpose).
_NOUN_NEXT = r"(?=[一-鿿ァ-ヺA-Za-z0-9])"  # the term modifies a following noun (attributive) — not a statement
_RULE_NOUN = r"(?:規則|規約|ルール|方針|本節|本書|本 ?file|この節|上の節|前の節|手順|設定|指示|検査|gate|hook|rule|policy)"
_OBLIGATION = r"(?:確認|承認|裁定|許可|同意|OK|検査|記録|報告|連絡|返事|返送|review|test|verify|承諾)"
_NOT_NEEDED = r"(?:" + _OBLIGATION + r"|" + _RULE_NOUN + r")(?:は|も|が|の|を)?"  # what is "not needed" is a duty or a rule
_CONDITION = r"(?:時は|ときは|場合は|場合には|なら|であれば|限り)"  # "…なら不要" = the rule is waived in a case
RELAX_FORMS: dict[str, re.Pattern] = {
    # a permission is a predicate; before a noun it is an attribute ("減ってよい種類")
    **{t: re.compile(re.escape(t) + r"(?![一-鿿ァ-ヺA-Za-z0-9])") for t in (
        "してよい", "しても良い", "してもよい", "でよい", "でもよい", "て良い", "ても良い", "で良い", "なくてよい",
        "てよい", "ていい", "てもいい")},
    "とは": re.compile(r"(?<!こ)とは[、,]?[^。．]*?(?:を指す|をいう|を言う|である|の意味|を意味|と定義|と呼ぶ|の略|のこと)"),
    "改訂": re.compile(r"^\s*#{1,6}\s.*改訂|改訂版|[(（]\s*(?:\d{4}-\d{2}-\d{2}\s*)?改訂|" + _RULE_NOUN + r"[^。．]{0,12}改訂|改訂(?:して|しても)?(?:よい|良い|いい|可)"),
    "改定": re.compile(r"^\s*#{1,6}\s.*改定|改定版|[(（]\s*(?:\d{4}-\d{2}-\d{2}\s*)?改定|" + _RULE_NOUN + r"[^。．]{0,12}改定|改定(?:して|しても)?(?:よい|良い|いい|可)"),
    "更新)": re.compile(r"[(（]\s*(?:\d{4}-\d{2}-\d{2}\s*)?更新\s*[)）]"),
    "例外": re.compile(r"(?<!想定外の)例外(?!なし|無し|なく|を認めない|は無い|はない|ではない|の型|を catch|を捕|が出|で落ち|を投げ|が上が|を握)"),
    "上書き": re.compile(_RULE_NOUN + r"(?:を|は|も|ごと)?[^。．]{0,4}上書き"),
    "除外": re.compile(r"^\s*#{1,6}\s.*除外|(?:" + _RULE_NOUN + r"|対象|範囲|保護|lock|禁止|必須|要件|条件)(?:を|から|は|も)[^。．]{0,4}除外"),
    "除く": re.compile(r"(?:" + _RULE_NOUN + r"|対象|範囲|保護|lock|禁止|必須|要件|条件)(?:を|から|は|も)[^。．]{0,4}除く"),
    "除いて": re.compile(r"(?:" + _RULE_NOUN + r"|対象|範囲|保護|lock|禁止|必須|要件|条件)(?:を|から|は|も)[^。．]{0,4}除いて"),
    "なしで": re.compile(_OBLIGATION + r"\s*なしで"),
    "限らない": re.compile(r"(?<!と)(?<!とは)限らない"),  # "に限らない" widens scope; "とは限らない" is epistemic
    "無視": re.compile(r"無視(?:する。|する$|してよい|して良い|していい|できる|可|し、|して、)"),
    "拘束": re.compile(r"拘束(?:しない|されない|されず|力|は無い|はない|を外|を解)"),
    "無効": re.compile(r"無効(?:に|と)(?:する|して|なる)|無効化(?:する|して|できる|可)"),
    "任意": re.compile(r"任意(?![一-鿿ァ-ヺA-Za-z0-9])(?!の)"),
    "優先": re.compile(r"優先(?!順|度|化|席|権|的)"),
    # "not needed" relaxes when what is not needed is an obligation or a rule ("確認は不要", "承認不要"), or when it
    # follows a condition ("急ぐ時は不要"); a tool fact ("ログイン不要"), a quantity ("不要な中間量") or a document
    # part ("caveat 節ごと不要になる") passes (measured: 16 of 16 committed uses were the latter)
    "不要": re.compile(_NOT_NEEDED + r"[^。．]{0,6}?不要|" + _CONDITION + r"[^。．]{0,4}?不要|不要(?:とする|にする|でよい|で良い|でいい)"),
    "要らない": re.compile(_NOT_NEEDED + r"[^。．]{0,6}?要らない|" + _CONDITION + r"[^。．]{0,4}?要らない"),
    "いらない": re.compile(_NOT_NEEDED + r"[^。．]{0,6}?いらない|" + _CONDITION + r"[^。．]{0,4}?いらない"),
    # "without X" relaxes only as a permission or sufficiency ("読まなくてもよい / 済む / 足りる"); "読まなくても分かる" describes
    "なくても": re.compile(r"なくても\s*(?:よい|良い|いい|構わない|かまわない|足りる|通る|可|済む|済ませ|済み|OK|問題ない|支障ない)"),
}


def _relax_term_in_unit(term: str, unit: str) -> bool:
    form = RELAX_FORMS.get(term)
    if form is None:
        return term in unit
    if term not in unit:
        return False
    return form.search(unit) is not None
_SENTENCE_END_RE = re.compile(r"(?<=[。．])")
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t#]*$")
_FENCE_RE = re.compile(r"^[ \t]*(```|~~~)")


def parse_manifest(text: str | None) -> list[str]:
    """None means absent. Malformed or weakening-shaped declarations fail closed."""
    if text is None:
        return []
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) - {"version", "protect_paths"}:
        raise ValueError("invalid agent-rule guard manifest fields")
    if type(value.get("version")) is not int or value["version"] != 1:
        raise ValueError("unsupported agent-rule guard manifest version")
    paths = value.get("protect_paths")
    if not isinstance(paths, list) or any(not isinstance(p, str) or not p or
            p.startswith(("/", "~")) or "\\" in p or ".." in PurePosixPath(p).parts for p in paths):
        raise ValueError("protect_paths must be repository-relative patterns")
    return paths


def protected_path(path: str, extra_paths: tuple[str, ...] | list[str] = ()) -> bool:
    rel = path.replace("\\", "/")
    if PurePosixPath(rel).name in ENTRYPOINT_NAMES:
        return True
    for pattern in CONTROL_PATTERNS:
        if fnmatch.fnmatchcase(rel, pattern) or fnmatch.fnmatchcase(rel, "*/" + pattern):
            return True
    return any(fnmatch.fnmatchcase(rel, p) for p in extra_paths)


def authority_regions(text: str, path: str, extra_paths: tuple[str, ...] | list[str] = ()) -> dict[str, str]:
    """Extract protected authority content without guessing whether an edit is good.

    Return stable region ids for the shared approval engine. Byte-sensitive
    content preserves code indentation/control flow. Compare old AND new maps
    so deleting a marker, reference, gate or manifest does not remove protection.
    """
    out: dict[str, str] = {}
    if text and (MARK_FILE_RE.search(text) or protected_path(path, extra_paths)):
        out["authority:file"] = mask_free_zones(text) if prose_policy_doc(path, (text,), extra_paths) else text
    blocks: list[tuple[int, int]] = []  # body spans of explicit blocks (marker lines excluded)
    for begin in MARK_BEGIN_RE.finditer(text):
        rid = begin.group(1)
        end = re.compile(MARK_END_TMPL.format(id=re.escape(rid)), re.M).search(text, begin.end())
        stop = end.start() if end else len(text)
        key, n = "authority:" + rid, 2
        while key in out:  # a repeated id protects every block, not only the last one
            key, n = f"authority:{rid}~{n}", n + 1
        out[key] = text[begin.end():stop] if end else text[begin.end():] + "\n<<unterminated>>"
        blocks.append((begin.end(), stop))
    refs = sorted(re.sub(r"\s+", " ", line).strip() for line in text.splitlines()
                  if any(token in line for token in RULE_REF_TOKENS))
    if refs:
        out["authority:rule-ref"] = "\n".join(refs)
    if Path(path).suffix.lower() in WIRING_SUFFIXES and any(t in text for t in ENGINE_TOKENS):
        if not wiring_inside_blocks(text, blocks):
            out["authority:wiring"] = text
    if path.replace("\\", "/").endswith(".claude/manuscript-guard.json"):
        try:
            out["config"] = json.dumps(json.loads(text or "{}"), sort_keys=True)
        except ValueError:
            out["config"] = text
    return out


def wiring_inside_blocks(text: str, blocks: list[tuple[int, int]]) -> bool:
    """True when every engine-name mention lies inside the body of an explicit block.

    The blocks are regions of their own, so they carry the wiring lock and the
    rest of the file is ordinary code. A mention outside every block body,
    including one inside a marker line (for example in the block id), keeps the
    whole-file lock. Moving a file into this shape is itself a locked change.
    Bypasses that stay outside the block (an earlier exit, a replaced helper,
    a swallowed exit status) are not prevented here; the canary's liveness
    record surfaces them (conventions/agent-rule-ownership.md#wiring-scope).
    """
    if not blocks:
        return False
    for token in ENGINE_TOKENS:
        for hit in re.finditer(re.escape(token), text):
            if not any(start <= hit.start() and hit.end() <= stop for start, stop in blocks):
                return False
    return True


def prose_policy_doc(path: str, texts: tuple[str, ...], extra_paths: tuple[str, ...] | list[str] = ()) -> bool:
    """True for a built-in prose instruction document where free zones and the change exemption apply.

    Excluded: the guard's own rule documents, files carrying the whole-file
    marker (in any of the given versions) and paths a manifest declared.
    """
    rel = path.replace("\\", "/")
    p = PurePosixPath(rel)
    if p.suffix.lower() != ".md" or p.name in GUARD_RULE_DOCS:
        return False
    if any(fnmatch.fnmatchcase(rel, x) for x in extra_paths):
        return False
    if any(t and MARK_FILE_RE.search(t) for t in texts):
        return False
    return p.name in ENTRYPOINT_NAMES or any(
        fnmatch.fnmatchcase(rel, pat) for pat in ("conventions/*.md", "*/conventions/*.md"))


def free_zones(text: str) -> list[tuple[str, int, int]]:
    """(id, body start, body end) of each terminated zone.

    Frees nothing for an unterminated begin, a marker inside an HTML comment, a
    zone whose begin and end sit on different sides of a code fence boundary (a
    fence cannot carry a zone out of or into it), or a repeated id (only the
    first zone with an id counts, so a second one cannot widen it). A zone whose
    two markers sit in the same code fence frees the lines between them only:
    the generated trees the owner declared live inside a fence, and the earlier
    rule (no marker inside a fence counts) had kept them from ever working
    (owner ruling 2026-09-24). Adding or moving a marker stays a file change.
    """
    if "agent-free:" not in text:
        return []
    starts, pos, run, prev_in = [], 0, -1, False
    for ctx, line in zip(_line_contexts(text), text.split("\n")):
        in_fence, in_comment = ctx[1], ctx[2]
        if in_fence and not prev_in:
            run += 1  # a new fence block (its opening line is outside, its closing line inside)
        prev_in = in_fence
        starts.append((pos, in_comment, run if in_fence else None))
        pos += len(line) + 1
    where = lambda at: next(((c, f) for s, c, f in reversed(starts) if s <= at), (True, None))
    zones: list[tuple[str, int, int]] = []
    seen: set[str] = set()
    pos = 0
    while True:
        begin = FREE_BEGIN_RE.search(text, pos)
        if not begin:
            return zones
        zid = begin.group(1)
        end = re.compile(FREE_END_TMPL.format(id=re.escape(zid)), re.M).search(text, begin.end())
        if not end:
            return zones
        (b_comment, b_fence), (e_comment, e_fence) = where(begin.start()), where(end.start())
        if zid not in seen and not b_comment and not e_comment and b_fence == e_fence:
            zones.append((zid, begin.end(), end.start()))
        seen.add(zid)
        pos = end.end()


def mask_free_zones(text: str) -> str:
    """Replace zone bodies with a placeholder; the marker lines stay, so adding or moving a zone is a change."""
    out, pos = [], 0
    for zid, start, stop in free_zones(text):
        out.append(text[pos:start] + f"\n<<agent-free:{zid}>>\n")
        pos = stop
    out.append(text[pos:])
    return "".join(out)



def relax_terms(unit: str) -> list[str]:
    """Every relaxation-shaped term a sentence carries in a relaxing position (RELAX_FORMS / RELAX_FORMS_EN), plus
    hiding markup and, for a heading, a word that files the lines under it as history. First found first."""
    out: list[str] = []
    hm = _HEADING_RE.match(unit)
    if hm:
        hh = _HISTORICISING_HEAD.search(_EN_NOISE.sub(" ", hm.group(2)))  # the anchor id is not the heading's words
        if hh:
            out.append(hh.group(0))
    out.extend(term for term in RELAX_MARKUP if term in unit)
    out.extend(term for term in RELAX_TERMS_JA if _relax_term_in_unit(term, unit))
    plain = _EN_NOISE.sub(" ", unit)
    for m in _RELAX_EN_RE.finditer(plain):
        form = RELAX_FORMS_EN.get(m.group(1).lower())
        if form is None or form.search(plain):
            out.append(m.group(1))
    return out


def relax_hit(text: str | list[str]) -> str | None:
    """First relaxation-shaped term in inserted text, or None (a list is judged unit by unit)."""
    for unit in ([text] if isinstance(text, str) else text):
        terms = relax_terms(unit)
        if terms:
            return terms[0]
    return None


def _units(text: str) -> list[tuple[str, int]]:
    """(unit, line number) sequence: sentences split after 。/．, with a "\\n" unit at each line break.

    The first unit of a line keeps its indentation, so nesting changes are not
    insertions; line breaks are units, so joining or splitting lines is not one.
    """
    units: list[tuple[str, int]] = []
    for i, line in enumerate(text.split("\n")):
        if i:
            units.append(("\n", i))
        first = True
        for part in _SENTENCE_END_RE.split(line):
            s = part.rstrip() if first else part.strip()
            if s.strip():
                units.append((s, i))
                first = False
    return units


def _line_contexts(text: str) -> list[tuple[tuple[str, ...], bool, bool]]:
    """Per line: (heading ancestry, inside a code fence, inside an HTML comment) at the line start."""
    out = []
    stack: list[tuple[int, str]] = []
    fence: str | None = None
    comment = False
    for line in text.split("\n"):
        hm = _HEADING_RE.match(line) if fence is None and not comment else None
        if hm:  # a heading's own context is its ancestors, so a section inserted before it moves nothing
            level = len(hm.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
        out.append((tuple(t for _, t in stack), fence is not None, comment))
        if hm:
            stack.append((level, hm.group(2)))
            continue
        if fence is not None:
            if line.lstrip().startswith(fence):
                fence = None
            continue
        fm = _FENCE_RE.match(line)
        if fm and not comment:
            fence = fm.group(1)
            continue
        pos = 0
        while True:
            j = line.find("-->" if comment else "<!--", pos)
            if j < 0:
                break
            pos = j + (3 if comment else 4)
            comment = not comment
    return out






# Directives and their polarity, for reporting where an addition sits next to an existing rule about the same thing.
_DIRECTIVE_NEG = re.compile(r"止めない|通さない|しない|せず|ずに|できない|要らない|不要|禁止|ならない|してはいけない|ない。|never|(?<![A-Za-z])not(?![A-Za-z])|(?<![A-Za-z])no(?![A-Za-z])")
_DIRECTIVE_POS = re.compile(r"止める|止まる|通す|必須|要る|拒否|deny|block|must|allow|する。|すること|"
                            r"(?<![A-Za-z])(?:required|require|requires|should|shall|ensure|always)(?![A-Za-z])")
_TOKEN_STRONG = re.compile(r"`([^`]+)`|\*\*([^*]+)\*\*|id=\"([^\"]+)\"|#([A-Za-z][A-Za-z0-9_-]{3,})")
_TOKEN_WORD = re.compile(r"[一-鿿ァ-ヺ]{2,}|[A-Za-z][A-Za-z0-9_-]{3,}")
_TOKEN_STOP = {"実測", "追記", "場合", "変更", "対象", "規則", "本人", "自分", "以下", "以上", "参照", "正本", "一般",
               "一般則", "確認", "記録", "判断", "操作", "経路", "結果", "目的", "実装", "宣言", "機構", "瞬間", "時間",
               "file", "path", "repo", "session", "tool", "hook", "script", "python", "commit", "agent", "claude",
               "claude-config", "conventions", "docs", "scripts", "plans", "json", "yaml", "settings", "readme"}
_LINK_TARGET = re.compile(r"\]\([^)]*\)")  # a link's path is not what the sentence is about
_HEADING_MARKUP = re.compile(r"<a id=\"[^\"]*\"></a>|[`*]")  # a heading's anchor and emphasis are not its words


def _tokens(unit: str) -> tuple[set[str], set[str]]:
    strong = {next(g for g in m.groups() if g) for m in _TOKEN_STRONG.finditer(unit)}
    plain = _LINK_TARGET.sub("]", unit)
    words: set[str] = set()
    for s in strong:
        plain = plain.replace(s, " ")
        # what a code span names is also a word: `\documentclass[a4paper]{...}` and `a4paper` are about the same option
        words |= {w for w in _TOKEN_WORD.findall(s) if w.lower() not in _TOKEN_STOP}
    words |= {w for w in _TOKEN_WORD.findall(plain) if w.lower() not in _TOKEN_STOP}
    return strong, words


_TRAILING_PAREN = re.compile(r"\s*[(（〔][^()（）〔〕]*[)）〕]\s*(?=[。．]?$)")


def _polarity(unit: str) -> int:
    """+1 directive, -1 negated directive, 0 no directive found (a trailing parenthetical does not hide the verb)."""
    core = _TRAILING_PAREN.sub("", unit)
    if _DIRECTIVE_NEG.search(core):
        return -1
    if _DIRECTIVE_POS.search(core):
        return 1
    return 0


def insertion_profile(old: str, new: str) -> list[dict]:
    """Where each sentence the change added sits, and the existing sentence about the same thing next to it (detection, not a verdict).

    Works for any change: a sentence is "kept" when the document had it before (anywhere), everything else the new
    document contains is "added" (an edited sentence counts as added). Each row: {"text", "line", "placement":
    "in-line" | "new-line" | "new-section", "near": existing unit text or "", "shared": sorted tokens both mention,
    "flip": both carry a directive of opposite polarity, "near_kind": "sentence" | "heading" | "same-line" | ""}.
    "in-line" = on a line that also has kept sentences; "new-line" = a new line under a heading that already
    existed; "new-section" = under a heading the change created. When no existing sentence shares the subject, a
    new line falls back to its section's heading (the sentence every line under it answers to: a heading that
    states a fact flatly is contradicted by a line adding the case where it fails) and an appended sentence falls
    back to the sentence before it on the same line. Empty when nothing was added.
    """
    ou, nu = _units(old), _units(new)
    oc, nc = _line_contexts(old), _line_contexts(new)
    left = Counter(u for u, _ in ou if u != "\n")
    kept: set[int] = set()
    for j, (u, _) in enumerate(nu):
        if u != "\n" and left[u] > 0:
            left[u] -= 1
            kept.add(j)
    kept_lines = {nu[j][1] for j in kept}
    old_heads = {ctx[0] for ctx in oc}
    existing = [(j, nu[j][0], nu[j][1]) for j in kept]
    rows = []
    for j, (u, ln) in enumerate(nu):
        if j in kept or u == "\n":
            continue
        head = nc[ln][0]
        placement = ("in-line" if ln in kept_lines else
                     "new-section" if head and head not in old_heads else "new-line")
        strong, words = _tokens(u)
        best, best_score, shared_best = "", 0, []
        for _, eu, eln in existing:
            if nc[eln][0] != head:
                continue
            es, ew = _tokens(eu)
            shared = sorted(strong & es) + sorted(words & ew)
            score = 3 * len(strong & es) + len(words & ew) - abs(eln - ln) / 100
            if score > best_score and (strong & es or len(words & ew) >= 2):
                best, best_score, shared_best = eu, score, shared
        hm = _HEADING_RE.match(u)
        if hm and head + (hm.group(2),) not in old_heads:
            placement = "new-section"  # a heading the change created belongs to its own new section, not to its parent
        kind = "sentence" if best else ""
        if not best and placement == "new-line" and head:
            ht = _HEADING_MARKUP.sub("", head[-1]).strip()
            hs, hw = _tokens(ht)
            shared = sorted(strong & hs) + sorted(words & hw)
            if shared:
                best, shared_best, kind = ht, shared, "heading"
        if not best and placement == "in-line":
            prev = next((nu[k][0] for k in range(j - 1, -1, -1) if nu[k][1] != ln or nu[k][0] == "\n" or k in kept), "")
            if prev and prev != "\n":
                best, kind = prev, "same-line"
        pu, pn = _polarity(u), _polarity(best) if best else 0
        rows.append({"text": u, "line": ln, "placement": placement, "near": best, "shared": shared_best,
                     "flip": bool(best) and pu != 0 and pn != 0 and pu != pn, "near_kind": kind})
    return rows




# Share of a removed sentence's characters an added sentence must keep, in order, to count as its edit. The pairing
# only decides how the record reads (「前」→「後」 versus 消した + 追記) and which terms an edit is new for; it is not
# a gate. Measured: at 0.5 a short sentence's boilerplate (" deploy する。") made an unrelated sentence count as an edit.
EDIT_KEEPS = 0.6
# A heading that files the lines under it as history or reference demotes them without touching a word.
_HISTORICISING_HEAD = re.compile(r"旧|参考|過去|以前|歴史|廃止|非推奨|deprecated|legacy|(?<![A-Za-z])old(?![A-Za-z])|obsolete|superseded", re.I)
def judge_change(old: str, new: str) -> tuple[bool, str, dict]:
    """(ok, reason, what) for a change to a rule document, judged by what it adds, not by its form.

    An append, a rewrite, a deletion and a move are held to the same line (an append-only rule made agents pile
    sentences up beside the ones they should have fixed, and a gate on replacing a rule sentence did the same in a
    smaller way; a form is not a meaning). The change passes when the sentences it adds carry no relaxing term in a
    relaxing position, an edited sentence carries no relaxing term it did not carry before (a sentence that already
    says ただし can be edited), no existing sentence is moved into a code fence or a comment, and no new heading
    files the lines under it as history. Removed, replaced and flipped sentences pass and are shown to the owner:
    what = {"added", "edited": [(old, new)], "removed", "moved"} is what the record and the reply carry. Meaning
    itself is not decided here: a rule deleted, flipped or loosened in unlisted words passes and is caught by the
    reply and the diff (the owner's ruling: a form cannot protect a meaning, reading does).
    """
    ou, nu = _units(old), _units(new)
    oc, nc = _line_contexts(old), _line_contexts(new)
    co = Counter(u for u, _ in ou if u != "\n")
    cn = Counter(u for u, _ in nu if u != "\n")
    removed = list((co - cn).elements())
    added = list((cn - co).elements())
    what: dict = {"added": [], "edited": [], "removed": [], "moved": []}
    if co and not cn:  # erasing a document is not an edit of it (a file deleted or emptied stays a ruling)
        return False, "文書の中身を全部消した", what
    # a kept sentence now inside a fence or a comment (the fence delimiters themselves are not sentences)
    ho = Counter(u for u, i in ou if u != "\n" and (oc[i][1] or oc[i][2]) and not _FENCE_RE.match(u))
    hn = Counter(u for u, i in nu if u != "\n" and (nc[i][1] or nc[i][2]) and not _FENCE_RE.match(u))
    for u in cn:
        if u in co and hn[u] > ho[u]:
            return False, "既存の文を code / comment の中に入れた: 「" + u[:30] + "」", what
    used: set[int] = set()
    # candidates for "the edit of r" = added sentences that share a word or start alike; keeps a big restructuring
    # (hundreds of sentences each way) from a quadratic pass of sequence matching inside a hook's timeout
    by_word: dict[str, set[int]] = {}
    by_head: dict[str, set[int]] = {}
    for k, a in enumerate(added):
        s, w = _tokens(a)
        for t in s | w:
            by_word.setdefault(t, set()).add(k)
        by_head.setdefault(a[:8], set()).add(k)
    for r in removed:
        # an edit = an added sentence that keeps at least EDIT_KEEPS of the removed one's characters, in order (several
        # removed sentences may be consolidated into one added sentence, each judged on its own retention)
        best, keep = -1, 0.0
        s, w = _tokens(r)
        cands: set[int] = set(by_head.get(r[:8], ()))
        for t in s | w:
            cands |= by_word.get(t, set())
        for k in sorted(cands):
            a = added[k]
            if len(a) < EDIT_KEEPS * len(r):
                continue
            sm = difflib.SequenceMatcher(None, r, a, autojunk=False)
            if sm.real_quick_ratio() * (len(r) + len(a)) < 2 * EDIT_KEEPS * len(r):  # upper bounds on the matched length
                continue
            if sm.quick_ratio() * (len(r) + len(a)) < 2 * EDIT_KEEPS * len(r):
                continue
            k_keep = sum(b.size for b in sm.get_matching_blocks()) / max(len(r), 1)
            if k_keep > keep:
                best, keep = k, k_keep
        if best >= 0 and keep >= EDIT_KEEPS:
            used.add(best)
            what["edited"].append((r, added[best]))
        else:
            what["removed"].append(r)
    what["added"] = [a for k, a in enumerate(added) if k not in used]
    hit = relax_hit(what["added"])
    if hit:
        return False, f"足した文に緩和の語「{hit}」がある", what
    for r, a in what["edited"]:
        had = {t.lower() for t in relax_terms(r)}
        fresh = [t for t in relax_terms(a) if t.lower() not in had]  # the same rules as for a new sentence, minus what it already said
        if fresh:
            return False, f"言い直しで緩和の語「{fresh[0]}」を足した: 「{r[:30]}」→「{a[:30]}」", what
    oh: dict[str, set] = {}
    nh: dict[str, set] = {}
    for u, i in ou:
        if u != "\n":
            oh.setdefault(u, set()).add(oc[i][0])
    for u, i in nu:
        if u != "\n":
            nh.setdefault(u, set()).add(nc[i][0])
    what["moved"] = [u for u in oh if u in nh and oh[u] != nh[u]]
    return True, "", what


def change_exemption(path: str, old: str, new: str,
                     extra_paths: tuple[str, ...] | list[str] = ()) -> dict | None:
    """Decide whether a change to a prose rule document skips prior approval. None = not a prose policy document.

    The line is drawn by what the change does to sentences (judge_change), not by its form: an append and a rewrite
    are treated alike. Returns {"ok", "reason", "inserted", "what", "free"}; "free" lists (zone id, term, text)
    for relaxation-shaped text written inside a free zone (logged, not blocked). Rule-reference lines may only be
    added, never changed or removed.
    """
    if not prose_policy_doc(path, (old, new), extra_paths):
        return None
    ok, reason, what = judge_change(mask_free_zones(old), mask_free_zones(new))
    if ok and not old and new and PurePosixPath(path.replace("\\", "/")).name in ENTRYPOINT_NAMES:
        # a new entry document is read automatically for a whole directory tree: a new scope of standing orders
        ok, reason = False, "新しい入口の文書 (CLAUDE.md / AGENTS.md 等) を作る"
    if ok:
        refs = [authority_regions(t, path, extra_paths).get("authority:rule-ref", "") for t in (old, new)]
        if Counter(x for x in refs[0].split("\n") if x) - Counter(x for x in refs[1].split("\n") if x):
            ok, reason = False, "正本を指す参照の行を変えた・消した"
    free = []
    old_bodies = {zid: old[a:b] for zid, a, b in free_zones(old)}
    for zid, a, b in free_zones(new):
        # a zone that did not exist before was created by a locked change (its markers need approval), so its
        # initial body is not "written into a free zone"
        if zid not in old_bodies or new[a:b] == old_bodies[zid]:
            continue
        before = Counter(u for u, _ in _units(old_bodies.get(zid, "")))
        written = " ".join((Counter(u for u, _ in _units(new[a:b]) if u != "\n") - before).elements())
        hit = relax_hit(written)
        if hit:
            free.append((zid, hit, written))
    return {"ok": ok, "reason": reason, "inserted": " ".join(what["added"]), "what": what, "free": free}


def shell_segments(command: str) -> list[list[str]]:
    """Tokenize the simple command forms we inspect, preserving quoted operators.

    Newlines outside quotes separate commands. Here-document bodies are data,
    not top-level commands. Expansion, aliases and arbitrary shell control flow
    are deliberately not evaluated. Raw quoting is removed only AFTER the
    operator/word distinction has been made.
    """
    segments: list[list[str]] = []
    current: list[str] = []
    raw: list[str] = []
    quote = None
    pending_docs: list[tuple[str, bool]] = []
    expect_doc: bool | None = None
    expect_target = False  # the next word is a redirection target, not an argument
    i = 0

    def flush_word():
        nonlocal expect_doc, expect_target
        if not raw:
            return
        parts = shlex.split("".join(raw), comments=False, posix=True)
        raw.clear()
        if len(parts) != 1:
            raise ValueError("unsupported shell token")
        if expect_doc is not None:
            pending_docs.append((parts[0], expect_doc))
            expect_doc = None
        elif expect_target:
            expect_target = False
        else:
            current.append(parts[0])

    def end_segment():
        flush_word()
        if expect_target:
            raise ValueError("incomplete redirection")
        if current:
            segments.append(current[:])
            current.clear()

    def redirect_target(pos: int) -> int:
        """After a redirection operator: `&fd` / `&-` duplicates are consumed here, a
        file name is the next word (dropped by flush_word). Redirections are not
        arguments: `2>/dev/null` after `commit -a` used to become a pathspec that
        matched nothing, so the commit was inspected as an empty selection."""
        nonlocal expect_target
        while pos < len(command) and command[pos] in " \t":
            pos += 1
        if pos < len(command) and command[pos] == "&":
            pos += 1
            while pos < len(command) and (command[pos].isdigit() or command[pos] == "-"):
                pos += 1
            return pos
        expect_target = True
        return pos

    while i < len(command):
        ch = command[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < len(command):
                if command[i + 1] != "\n":
                    raw.extend(command[i:i + 2])
                i += 2
                continue
            raw.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            raw.append(ch)
            i += 1
        elif ch == "\\" and i + 1 < len(command):
            if command[i + 1] != "\n":
                raw.extend(command[i:i + 2])
            i += 2
        elif ch in " \t\r":
            flush_word()
            i += 1
        elif ch == "#" and not raw:
            end = command.find("\n", i)
            i = len(command) if end < 0 else end
        elif ch == "\n":
            end_segment()
            i += 1
            for delimiter, strip_tabs in pending_docs:
                while i < len(command):
                    end = command.find("\n", i)
                    end = len(command) if end < 0 else end
                    line = command[i:end]
                    i = min(end + 1, len(command))
                    if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                        break
            pending_docs.clear()
        elif command.startswith("&>", i):  # &> file / &>> file (before & ends the segment)
            flush_word()
            i += 3 if command.startswith("&>>", i) else 2
            i = redirect_target(i)
        elif ch in ";&|()":
            end_segment()
            i += 1
        elif command.startswith("<<<", i):
            flush_word()
            current.append("<<<")
            i += 3
        elif command.startswith("<<", i):
            flush_word()
            strip_tabs = command.startswith("<<-", i)
            i += 3 if strip_tabs else 2
            expect_doc = strip_tabs
        elif ch in "<>":  # [fd]>, [fd]>>, >|, [fd]<, <> — then &fd or a target word
            if raw and "".join(raw).isdigit():
                raw.clear()  # an attached fd number belongs to the operator
            else:
                flush_word()
            two = command[i:i + 2]
            i += 2 if two in (">>", ">|", "<>") else 1
            i = redirect_target(i)
        else:
            raw.append(ch)
            i += 1
    if quote or expect_doc is not None:
        raise ValueError("incomplete shell quoting or heredoc")
    end_segment()  # flushes the last word (a pending redirection target is dropped there; a missing one raises)
    return segments


def executable_argv(segment: list[str]) -> tuple[list[str], list[str]]:
    """Remove ordinary assignment/env/command wrappers, not arbitrary arguments.

    Return argv plus env -C directory changes (local to this invocation).
    The commit scanner and bypass scanner share this executable-position test.
    """
    args = list(segment)
    directories = []
    while args:
        while args and re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", args[0]):
            args.pop(0)
        if not args:
            break
        executable = Path(args[0]).name
        if executable == "env":
            args.pop(0)
            while args and (args[0].startswith("-") or re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", args[0])):
                opt = args.pop(0)
                if opt == "--":
                    break
                if opt in ("-u", "--unset") and args:
                    args.pop(0)
                elif opt in ("-C", "--chdir") and args:
                    directories.append(args.pop(0))
                elif opt.startswith("--chdir="):
                    directories.append(opt.partition("=")[2])
            continue
        if executable == "command":
            args.pop(0)
            while args and args[0].startswith("-"):
                opt = args.pop(0)
                if opt in ("-v", "-V"):
                    return [], []
            continue
        break
    return args, directories


def shell_script(args: list[str]) -> str | None:
    if not args or Path(args[0]).name not in ("bash", "sh", "zsh"):
        return None
    for i, arg in enumerate(args[1:-1], 1):
        if arg.startswith("-") and "c" in arg[1:]:
            return args[i + 1]
    return None


def git_operation_options(operation: str, args: list[str]) -> tuple[set[str], list[str]]:
    """Selection flags and paths, without mistaking option values for options."""
    rest = list(args)
    flags: set[str] = set()
    paths = []
    value_options = {"-m", "--message", "-F", "--file", "-C", "-c", "--reuse-message",
                     "--reedit-message", "--author", "--date", "--template", "-t",
                     "--fixup", "--squash", "--pathspec-from-file", "--cleanup", "--trailer", "--repo"}
    long_flags = {"--no-verify": "no_verify", "--all": "all", "--only": "only",
                  "--include": "include", "--dry-run": "dry_run", "--interactive": "interactive",
                  "--patch": "interactive", "--update": "update", "--force": "force"}
    while rest:
        arg, rest = rest[0], rest[1:]
        if arg == "--":
            paths.extend(rest)
            break
        if arg == "--pathspec-from-file" or arg.startswith("--pathspec-from-file="):
            flags.add("pathspec_file")
        if arg in value_options:
            rest = rest[1:]
            continue
        if arg.startswith("--") and arg.partition("=")[0] in value_options:
            continue
        if arg in long_flags:
            flags.add(long_flags[arg])
        elif operation == "add" and arg.startswith("-") and not arg.startswith("--"):
            for letter in arg[1:]:
                if letter in "Aufnpei":
                    flags.add({"A": "all", "u": "update", "f": "force", "n": "dry_run",
                               "p": "interactive", "e": "interactive", "i": "interactive"}[letter])
        elif operation == "commit" and arg.startswith("-") and not arg.startswith("--"):
            for i, letter in enumerate(arg[1:], 1):
                if letter in "mFtcCS":
                    if i == len(arg) - 1 and letter != "S":
                        rest = rest[1:]
                    break
                if letter in {"n", "a", "o", "i", "p"}:
                    flags.add({"n": "no_verify", "a": "all", "o": "only", "i": "include", "p": "interactive"}[letter])
        elif not arg.startswith("-"):
            paths.append(arg)
    return flags, paths


def git_bypass_attempts(command: str, depth: int = 0) -> list[str]:
    """Recognize literal Git hook suppression, not arbitrary shell semantics.

    Only inspect executable positions, so printing/searching an example is not
    blocked. Standard shell -c wrappers are inspected with a bounded recursion.
    Computed commands and programs which spawn Git remain outside this parser.
    """
    if depth > 4:
        return []
    try:
        segments = shell_segments(command)
    except ValueError:
        return []
    findings = []
    for segment in segments:
        args, _ = executable_argv(segment)
        if not args:
            continue
        inner = shell_script(args)
        if inner is not None:
            findings.extend(git_bypass_attempts(inner, depth + 1))
            continue
        executable = Path(args.pop(0)).name
        if executable != "git":
            continue
        redirected = False
        while args and args[0].startswith("-"):
            opt = args.pop(0)
            if opt in ("-C", "-c", "--config-env", "--git-dir", "--work-tree", "--namespace", "--exec-path") and args:
                value = args.pop(0)
                redirected |= opt in ("-c", "--config-env") and value.split("=", 1)[0].lower() == "core.hookspath"
            elif opt.startswith("-c"):
                redirected |= opt[2:].split("=", 1)[0].lower() == "core.hookspath"
            elif opt.startswith("--config-env="):
                redirected |= opt.partition("=")[2].split("=", 1)[0].lower() == "core.hookspath"
        if not args or args[0] not in ("commit", "push", "merge", "am"):
            continue
        operation = args[0]
        if redirected:
            findings.append("Git の実行時に core.hooksPath を差し替える")
        flags, _ = git_operation_options(operation, args[1:])
        if "no_verify" in flags:
            findings.append("Git の --no-verify / commit -n で既存 gate を省く")
    return sorted(set(findings))


def selftest() -> int:
    failures = []
    def check(name, ok):
        print(("PASS: " if ok else "FAIL: ") + name)
        if not ok:
            failures.append(name)
    def changed(path, old, new, extra=()):
        return authority_regions(old, path, extra) != authority_regions(new, path, extra)

    for path in ("AGENTS.md", "src/AGENTS.override.md", "CLAUDE.md", "CONVENTIONS.md", "conventions/deployment.md"):
        check("unmarked instructions cannot self-relax: " + path,
              changed(path, "Review is required before deployment.\n", "Deploy without review.\n"))
        check("deleting instructions remains visible: " + path,
              changed(path, "Review is required before deployment.\n", ""))
    cases = [
        (".claude/settings.json", '{"permissions":{"deny":["Write"]}}', '{"permissions":{"deny":[]}}'),
        (".codex/config.toml", '[features]\nhooks=true\n', '[features]\nhooks=false\n'),
        (".codex/rules/policy.rules", 'decision="forbidden"', 'decision="allow"'),
        (".github/workflows/checks.yml", 'run: check-release\n', 'run: true\n'),
        (".codex/hooks.json", '{"hooks":{"PreToolUse":[{}]}}', '{"hooks":{}}'),
        (".pre-commit-config.yaml", 'repos: [gate]\n', 'repos: []\n'),
        (".git/config", '[core]\nhooksPath=.hooks\n', '[core]\nhooksPath=/dev/null\n'),
    ]
    for path, old, new in cases:
        check("enforcement configuration protected: " + path, changed(path, old, new))
    for path in ("README.md", "SESSION.md", "src/app.py", "docs/progress.md", "data/config.json"):
        check("ordinary content is not a control file: " + path, not changed(path, "Old value\n", "New value\n"))
    check("declared gate implementation protected", changed("scripts/check-release.py", "check()\n", "pass\n", ["scripts/check-*.py"]))
    check("additive declaration does not remove builtin protection", protected_path("AGENTS.md", []))
    marker = "<!-- agent-authority:begin id=retention -->\nKeep backups.\n<!-- agent-authority:end id=retention -->\n"
    check("marked rule survives marker deletion", changed("docs/storage.md", marker, "Keep backups.\n"))
    call = "python3 agent-rule-guard.py git-precommit\n"
    check("early exit cannot retain only the call line", changed("scripts/check.sh", call, "exit 0\n" + call))
    # Block-scoped wiring (agent-rule-ownership.md#wiring-scope): the block is the lock, the rest is ordinary.
    boxed = ("#!/bin/sh\nrun() { \"$@\"; }\n"
             "# agent-authority:begin id=guard-canary\n"
             "run python3 manuscript-claim-guard.py --canary\n"
             "# agent-authority:end id=guard-canary\n"
             "echo ordinary diagnostics\n")
    check("wiring inside an explicit block: the rest of the file is ordinary",
          not changed("scripts/diagnostics.sh", boxed, boxed.replace("ordinary diagnostics", "other diagnostics")))
    check("wiring inside an explicit block: the block itself stays protected",
          changed("scripts/diagnostics.sh", boxed, boxed.replace("--canary", "--canary || true")))
    check("wiring inside an explicit block: removing the markers is protected",
          changed("scripts/diagnostics.sh", boxed,
                  boxed.replace("# agent-authority:begin id=guard-canary\n", "").replace("# agent-authority:end id=guard-canary\n", "")))
    check("block-scoped wiring does not emit the whole-file region",
          "authority:wiring" not in authority_regions(boxed, "scripts/diagnostics.sh"))
    loose = boxed + "# see manuscript-claim-guard.py\n"
    check("a mention outside every block keeps the whole-file lock",
          changed("scripts/diagnostics.sh", loose, loose.replace("ordinary diagnostics", "other diagnostics")))
    check("a mention inside the marker id is outside the block body: whole-file lock",
          "authority:wiring" in authority_regions(boxed.replace("id=guard-canary", "id=manuscript-claim-guard-canary"),
                                                  "scripts/diagnostics.sh"))
    unterminated = boxed.replace("# agent-authority:end id=guard-canary\n", "")
    check("an unterminated block reaches the end of the file",
          changed("scripts/diagnostics.sh", unterminated, unterminated.replace("ordinary diagnostics", "other diagnostics")))
    check("block scoping never overrides a declared or built-in file lock",
          changed("hooks/diagnostics.sh", boxed, boxed.replace("ordinary diagnostics", "other diagnostics"), ["hooks/*"]))
    twice = marker + "Other text.\n" + marker.replace("Keep backups.", "Keep logs.")
    check("a repeated block id protects every block",
          changed("docs/storage.md", twice, twice.replace("Keep backups.", "Drop backups.")))
    check("a repeated block id keeps distinct regions",
          {"authority:retention", "authority:retention~2"} <= set(authority_regions(twice, "docs/storage.md")))
    check("canonical pointer removal is protected", changed("SESSION.md", RULE_REF_TOKENS[0], ""))
    good = '{"version":1,"protect_paths":["scripts/check-*.py"]}'
    check("valid additive manifest", parse_manifest(good) == ["scripts/check-*.py"])
    for raw in ('', '[]', '{"version":true,"protect_paths":[]}', '{"version":1,"protect_paths":[],"disabled":true}',
                '{"version":1,"protect_paths":[],"exclude":["AGENTS.md"]}',
                '{"version":1,"protect_paths":["../outside"]}'):
        try:
            parse_manifest(raw)
        except (ValueError, TypeError):
            check("malformed/weakening manifest rejected", True)
        else:
            check("malformed/weakening manifest rejected", False)
    for cmd in ("git commit --no-verify -m test", "/usr/bin/git -C /tmp/example push --no-verify",
                "git -c core.hooksPath=/dev/null commit -m test", "git -ccore.hooksPath=empty commit -m test",
                "git --config-env=core.hooksPath=HOOK_DIR commit -m test",
                "git --git-dir /tmp/example/.git commit --no-verify -m test",
                "echo preparing\ngit push --no-verify", "git commit -m ';' --no-verify",
                "cat <<< 'example'\ngit push --no-verify",
                "echo ready\n# comment\ngit commit --no-verify", "git \\\n push --no-verify",
                "bash -lc 'git commit -n -m test'", "git commit -an -m test",
                "env -u CODEX_THREAD_ID git commit --no-verify"):
        check("literal gate bypass is rejected: " + cmd, bool(git_bypass_attempts(cmd)))
    # Redirections are shell syntax, not arguments (an attached fd, a dup, a target word, &>).
    for cmd, expect in (("git commit -am x > log.txt 2>&1", [["git", "commit", "-am", "x"]]),
                        ("git commit -m x 2>/dev/null", [["git", "commit", "-m", "x"]]),
                        ("git commit -m x &>> log", [["git", "commit", "-m", "x"]]),
                        ("git commit -m x >log <in", [["git", "commit", "-m", "x"]]),
                        ("git commit -m x 1>&2", [["git", "commit", "-m", "x"]]),
                        ("git commit -m x 2>&1 | tee log", [["git", "commit", "-m", "x"], ["tee", "log"]]),
                        ("git commit -m 'a > b' -- '2>'", [["git", "commit", "-m", "a > b", "--", "2>"]])):
        check("redirections are not arguments: " + cmd, shell_segments(cmd) == expect)
    check("literal gate bypass is rejected behind a redirection",
          bool(git_bypass_attempts("git commit --no-verify -m x > /dev/null 2>&1")))
    for cmd in ("git commit -m x >", "git commit -m x 2>; echo"):
        try:
            shell_segments(cmd)
        except ValueError:
            check("incomplete redirection is rejected: " + cmd, True)
        else:
            check("incomplete redirection is rejected: " + cmd, False)
    for cmd in ("git commit -m 'mention --no-verify in a message'", "git commit -m --no-verify",
                "git commit -mmention", "git commit -man", "git commit -Fnotes.txt",
                "git commit -am --no-verify", "git commit -Ssigningkey -m test",
                "git commit -m --never", "git commit -- --no-verify", "echo git commit --no-verify",
                "printf '%s\\n' ';' git push --no-verify",
                "printf '%s\\n' '&&' git push --no-verify",
                "printf '%s\\n' 'first\ngit push --no-verify'",
                "cat <<'EOF'\ngit push --no-verify\nEOF\necho done",
                "rg -- '--no-verify' scripts", "git status", "git push origin main"):
        check("inspection or ordinary Git stays allowed: " + cmd, not git_bypass_attempts(cmd))

    # Changes that pass without a ruling (#additive-and-free-zones): judged by what they do to sentences, not by form.
    doc = ("# Rules\n\n## Deploy\n\nレビューを経てから deploy する。 手順は runbook。\n\n"
           "## Mail\n\n送信は本人の OK の後。\n")
    def exempt(path, old, new, extra=()):
        r = change_exemption(path, old, new, extra)
        return None if r is None else r["ok"]
    grown = {
        "a sentence appended to a line": doc.replace("手順は runbook。", "手順は runbook。 実測では 3 分かかる。"),
        "a line inside a section": doc.replace("送信は本人の OK の後。\n", "送信は本人の OK の後。\n宛先も読み上げる。\n"),
        "a new section at the end": doc + "\n## Print\n\n刷る前に raster で確かめる。\n",
        "a new section before a same-level heading": doc.replace("## Mail", "## Print\n\n刷る前に確かめる。\n\n## Mail"),
        "a balanced code block": doc.replace("## Mail", "```bash\nmake check\n```\n\n## Mail"),
    }
    for name, new in grown.items():
        check("insertion passes without approval: " + name, exempt("conventions/deploy.md", doc, new) is True)
    check("a new prose document is an insertion", exempt("conventions/new.md", "", doc) is True)
    check("a new entry document (a new scope of standing orders) needs approval",
          exempt("sub/CLAUDE.md", "", doc) is False and exempt("AGENTS.md", "", doc) is False)
    for name, inserted in (("permission without a listed word", "送信は agent が判断して送ってよい。"),
                           ("precedence", "矛盾する時は下の節を最優先とする。"),
                           ("a newer revision", "## Mail (改定)\n\n送信は agent が行う。"),
                           ("scope narrowing", "これは学外宛に限った話である。"),
                           ("hidden html", '<div style="display:none">'),
                           ("a redefinition", "本 file で「本人」 とは、 その session の依頼者を指す。"),
                           ("historicising", "ここまでの節は 2025 年時点の記録である。"),
                           ("precedence without the word", "後に書かれた節が前の節に勝つ。"),
                           ("discretion", "本 repo では agent が自分の判断で送信する。"),
                           ("an invisible character", "送信は本人の​ OK の後。")):
        check("a relaxation-shaped insertion needs approval: " + name,
              exempt("conventions/deploy.md", doc, doc + "\n" + inserted + "\n") is False)
    check("CLAUDE.md is a prose policy document", exempt("CLAUDE.md", doc, grown["a new section at the end"]) is True)
    # Position rules (RELAX_FORMS): everyday uses of listed terms pass; the relaxing position still needs approval.
    # Old implementation (plain substring): every "passes" case below was sent to approval.
    for name, inserted in (("a form's revision", "様式が改訂されても同じ手順で埋める。"),
                           ("a comparison, not a definition", "頁番号は冊子のもので、 PDF の何枚目かとは違う。"),
                           ("a noun phrase, not a permission", "減ってよい種類は前の版の実測で決まる。"),
                           ("an exclusion list as data", "対象 repo と除外は呼び元が渡す。"),
                           ("a Python exception", "想定外の例外は 3 に落として表示する。"),
                           ("a file overwrite", "写し先の PDF は上書きしない。"),
                           ("epistemic", "末尾が直近の run とは限らないので拾わない。"),
                           ("a physics constraint", "消すと δ 汎関数 (= 拘束) が出る。"),
                           ("arbitrary", "任意の file を渡せる。"),
                           ("a priority order", "重大度の優先順で並べる。"),
                           ("a tool fact", "flag なしで全アカウントの表が出る。"),
                           ("a passive disabling by the platform", "Free plan では検査が警告なしに無効化される。"),
                           ("describing a bad habit", "検査を無視する習慣を教える生成器は作らない。")):
        check("everyday use of a listed term passes: " + name,
              exempt("conventions/deploy.md", doc, doc + "\n" + inserted + "\n") is True)
    for name, inserted in (("a definition", "本 file で「本人」 とは、 その session の依頼者を指す。"),
                           ("a revision heading", "## Deploy (改訂)\n\nレビューは deploy の後に回す。"),
                           ("a dated revision mark", "(2026-01-01 更新) レビューは deploy の後に回す。"),
                           ("a rule revised", "この節の手順を改訂した。"),
                           ("a permission predicate", "急ぐ時は deploy してよい。"),
                           ("a permission before a conjunction", "急ぐ時は deploy してよいが、 後で見る。"),
                           ("an exception to the rule", "docs だけの変更は例外とする。"),
                           ("a rule overridden", "この節の規則は下の節が上書きする。"),
                           ("a scope excluded", "docs の変更は対象から除外する。"),
                           ("an obligation skipped", "review なしで deploy する。"),
                           ("scope widening", "この規則は本番に限らない。"),
                           ("ignoring a check", "警告は無視してよい。"),
                           ("non-binding", "この節は拘束しない。"),
                           ("disabling", "検査を無効にする。"),
                           ("optional", "レビューは任意。"),
                           ("precedence", "急ぐ deploy を優先する。")):
        check("relaxing position still needs approval: " + name,
              exempt("conventions/deploy.md", doc, doc + "\n" + inserted + "\n") is False)
    check("a unit list is judged unit by unit", relax_hit(["様式が改訂されても同じ。", "急ぐ時は deploy してよい。"]) == "してよい")
    # Second round of position rules: "not needed" / "without" and the English everyday words (measured on the
    # committed additions that the first round still sent to approval).
    for name, inserted in (("a tool fact: no login needed", "この URL はログイン不要で読める。"),
                           ("an unneeded quantity", "不要な中間量や重複を減らす。"),
                           ("a document part becoming unneeded", "定義を本文に書けば caveat 節ごと不要になる。"),
                           ("a document that is not needed", "定額の支給なら金額の書類は要らないのが普通。"),
                           ("describing what one can do without", "住所を入れなくても価格が取れる。"),
                           ("a look of being done", "読んでいなくても済んだ顔をする。"),
                           ("git's ignore", "親の repo が ignore している入れ子の clone は数えない。"),
                           ("a skip flag as a mechanism", "警告つき export や skip flag にすると FAIL は読まれない。"),
                           ("optional material", "Mark optional content plainly."),
                           ("an override as a namespace", "検証は namespace override の diff で見る。"),
                           ("an anchor id", '## <a id="exception-by-category"></a>既定と違う支給額を頼む'),
                           ("a platform feature disabled", "audit with interpreter discovery disabled."),
                           ("a bounce vocabulary", "`5.2.1` の inactive / disabled = 停止、 `4xx` = 一時的。")):
        check("everyday use of a listed term passes: " + name,
              exempt("conventions/deploy.md", doc, doc + "\n" + inserted + "\n") is True)
    for name, inserted in (("an obligation not needed", "小さな変更なら確認は不要。"),
                           ("a condition then not needed", "急ぐ時は不要。"),
                           ("a compound", "docs の変更は承認不要とする。"),
                           ("a permission not needed", "runner の許可は要らない。"),
                           ("without an obligation", "レビューを経なくてもよい。"),
                           ("without, then suffices", "本人に聞かなくても済む。"),
                           ("skipping a check", "You may skip the review when in a hurry."),
                           ("skipping a gate", "Deploys skip the pre-commit check."),
                           ("ignoring a warning", "Ignore the warning and continue."),
                           ("is optional", "The review is optional."),
                           ("overriding a rule", "This section overrides the rule above."),
                           ("an exception to", "Small fixes are an exception to the review rule."),
                           ("a check disabled", "The check is disabled on this branch."),
                           ("disabling a hook", "Disable the hook before pushing.")):
        check("relaxing position still needs approval: " + name,
              exempt("conventions/deploy.md", doc, doc + "\n" + inserted + "\n") is False)
    # Placement and same-object profile (detection, not a verdict): what the disclosure line shows.
    prof = insertion_profile(doc, doc.replace("手順は runbook。\n", "手順は runbook。\n急ぐ deploy はレビューを経ずに deploy する。\n"))
    check("profile: a new line beside the rule about the same thing with opposite polarity is a flip",
          len(prof) == 1 and prof[0]["placement"] == "new-line" and prof[0]["near"].startswith("レビューを経てから")
          and prof[0]["flip"] and "deploy" in prof[0]["shared"])
    prof = insertion_profile(doc, doc + "\n## Print\n\n刷る前に raster で確かめる。\n")
    check("profile: a new section's body is new-section and has no neighbor",
          [r["placement"] for r in prof if not r["text"].startswith("#")] == ["new-section"] and not any(r["near"] for r in prof))
    prof = insertion_profile(doc, doc.replace("手順は runbook。", "手順は runbook。 実測では 3 分かかる。"))
    check("profile: a sentence appended to an existing line shows the sentence before it on that line",
          len(prof) == 1 and prof[0]["placement"] == "in-line" and prof[0]["near"] == "手順は runbook。"
          and prof[0]["near_kind"] == "same-line" and not prof[0]["flip"])
    # The measured miss: a line added under a heading that states a fact flatly, about the same option as the lead
    # sentence, showed no neighbor (the option's name sat inside a code span; the heading was never a candidate).
    latex = ("# L\n\n## <a id=\"paper\"></a>用紙の指定は PDF に届かない (driver)\n\n"
             "`\\documentclass[a4paper]{...}` と書いても、 PDF の用紙は **driver の既定**で決まる。\n\n- 診断: 出力を測る\n")
    prof = insertion_profile(latex, latex + "- ⚠️ `hyperref` も driver が dvipdfmx なら既定で用紙の寸法を special として出す。\n")
    check("profile: a word inside a code span pairs the new line with the lead sentence",
          len(prof) == 1 and prof[0]["near"].startswith("`\\documentclass[a4paper]") and prof[0]["near_kind"] == "sentence"
          and "driver" in prof[0]["shared"])
    prof = insertion_profile(latex, latex + "- ⚠️ `geometry` を読むと用紙の指定は届く。\n")
    check("profile: with no sentence about the same thing, a new line falls back to its heading",
          len(prof) == 1 and prof[0]["near"] == "用紙の指定は PDF に届かない (driver)" and prof[0]["near_kind"] == "heading"
          and prof[0]["shared"] == ["指定", "用紙"])
    prof = insertion_profile(latex, latex + "\n## Fonts\n\n字体は埋め込む。\n")
    check("profile: a new section never falls back to a heading, and its heading is new-section too",
          all(not r["near"] and not r["near_kind"] and r["placement"] == "new-section" for r in prof))
    prof = insertion_profile(doc, doc.replace("送信は本人の OK の後。\n", "送信は本人の OK の後。\n宛先も読み上げる。\n"))
    check("profile: a new line about something else has no neighbor and no flip", len(prof) == 1 and not prof[0]["near"] and not prof[0]["flip"])
    prof = insertion_profile(doc, doc.replace("レビューを経てから", "急ぐ時は"))
    check("profile: a rewritten sentence counts as added on its existing line", len(prof) == 1 and prof[0]["placement"] == "in-line")
    check("profile: nothing added is empty", insertion_profile(doc, doc.replace("## Mail\n\n送信", "## Mail\n送信")) == [])
    # Rewrites that keep the meaning pass too (an append-only line only piled sentences up); the record says what changed.
    latex_old = ("# L\n\n## <a id=\"p\"></a>documentclass の用紙指定は PDF の用紙に届かない (driver)\n\n"
                 "`\\documentclass[a4paper]{...}` と書いても、 PDF の MediaBox は **driver の既定**で決まる。\n")
    latex_new = ("# L\n\n## <a id=\"p\"></a>documentclass の用紙指定は、 papersize special が出ないと PDF の用紙に届かない (driver)\n\n"
                 "`\\documentclass[a4paper]{...}` の用紙 option は版面の寸法を決めるだけで、 PDF の MediaBox は **papersize special** で決まる。\n")
    rewritten = {
        "a rule sentence edited, keeping most of it": doc.replace("レビューを経てから deploy する。", "レビューを経てから deploy する (実測: 3 分)。"),
        "a descriptive sentence removed": doc.replace(" 手順は runbook。", ""),
        "a descriptive sentence replaced": doc.replace("手順は runbook。", "手順は wiki にある。"),
        "a sentence moved to another section": doc.replace("\n送信は本人の OK の後。\n", "\n").replace("手順は runbook。\n", "手順は runbook。\n送信は本人の OK の後。\n"),
        "a heading reworded": doc.replace("## Deploy", "## Deploy の手順"),
        "lines joined (formatting only)": doc.replace("## Mail\n\n送信", "## Mail\n送信"),
        "indentation changed (formatting only)": doc.replace("\n送信は", "\n  送信は"),
        "a flat heading and its lead sentence rewritten to say when they hold": (latex_old, latex_new),
    }
    for name, new in rewritten.items():
        old_text, new_text = new if isinstance(new, tuple) else (doc, new)
        check("a rewrite that keeps the rules passes without approval: " + name,
              exempt("conventions/deploy.md", old_text, new_text) is True)
    what = judge_change(doc, rewritten["a rule sentence edited, keeping most of it"])[2]
    check("the record says which sentence was edited", what["edited"] == [("レビューを経てから deploy する。", "レビューを経てから deploy する (実測: 3 分)。")] and not what["added"])
    what = judge_change(doc, rewritten["a descriptive sentence removed"])[2]
    check("the record says which sentence was removed", what["removed"] == ["手順は runbook。"] and not what["edited"])
    what = judge_change(doc, rewritten["a sentence moved to another section"])[2]
    check("the record says which sentence moved", what["moved"] == ["送信は本人の OK の後。"] and not what["added"] and not what["removed"])
    check("a heading reworded moves the lines under it, in the record", "レビューを経てから deploy する。" in judge_change(doc, rewritten["a heading reworded"])[2]["moved"])
    check("the rewritten flat heading and lead sentence are two edits", len(judge_change(latex_old, latex_new)[2]["edited"]) == 2)
    # A rule sentence deleted, replaced or flipped passes (the owner's ruling: a form cannot protect a meaning, reading
    # does) and the record says what happened, so the reply can show it.
    disclosed = {
        "a rule sentence replaced by a different one": (doc.replace("レビューを経てから deploy する。", "deploy は担当が判断する。"),
                                                        lambda w: w["removed"] == ["レビューを経てから deploy する。"] and w["added"] == ["deploy は担当が判断する。"]),
        "a rule sentence deleted": (doc.replace("レビューを経てから deploy する。 手順は runbook。", "手順は runbook。"),
                                    lambda w: w["removed"] == ["レビューを経てから deploy する。"] and not w["added"]),
        "a rule flipped in place": (doc.replace("レビューを経てから deploy する。", "レビューを経ずに deploy する。"),
                                    lambda w: w["edited"] == [("レビューを経てから deploy する。", "レビューを経ずに deploy する。")]),
        "a directive edited into a choice": (doc.replace("レビューを経てから deploy する。", "レビューを経てから deploy するか決める。"),
                                             lambda w: len(w["edited"]) == 1 and not w["removed"]),
        "an existing sentence rewritten to loosen in unlisted words": (doc.replace("レビューを経てから deploy する。", "急ぐ時は deploy してから見る。"),
                                                                       lambda w: bool(w["removed"] or w["edited"])),
        "a sentence that already says ただし, edited": (doc.replace("手順は runbook。", "手順は runbook。 ただし急ぐ時は後でよい (実測)。"),
                                                       lambda w: len(w["edited"]) == 1),
    }
    base_tadashi = doc.replace("手順は runbook。", "手順は runbook。 ただし急ぐ時は後でよい。")
    for name, (new, cond) in disclosed.items():
        old_text = base_tadashi if name.startswith("a sentence that already says") else doc
        ok, _reason, what = judge_change(old_text, new)
        check("passes and the record says what changed: " + name, ok and cond(what)
              and exempt("conventions/deploy.md", old_text, new) is True)
    # Known hole, kept on purpose: a word slipped into a sentence in a non-relaxing position passes, exactly as the
    # same sentence would pass if appended (the line is the same for both forms).
    check("known hole: a listed word in a non-relaxing position slipped into a sentence passes",
          exempt("conventions/deploy.md", doc, doc.replace("本人の OK の後", "本人の OK の後でなくても")) is True)
    weakened = {
        "an English rule replaced by its opposite": ("# R\n\nReview is required before deployment.\n", "# R\n\nDeploy without review.\n"),
        "without an obligation": doc + "\nDeploy without prior approval when in a hurry.\n",
        "an edit that moves a listed word into a relaxing position": doc.replace("手順は runbook。", "手順は runbook (docs は例外とする)。"),
        "an edit that adds a permission to an existing sentence": doc.replace("送信は本人の OK の後。", "送信は本人の OK の後でよい。"),
        "an exception added": doc.replace("手順は runbook。", "手順は runbook。 ただし急ぐ時は後でよい。"),
        "an English exception added": doc + "\nReview is not required for docs.\n",
        "a sub-heading that re-parents lines": doc.replace("\nレビューを", "\n### 旧手順 (参考)\n\nレビューを"),
        "a comment wrapping a rule": doc.replace("\n送信は本人の OK の後。\n", "\n<!--\n送信は本人の OK の後。\n-->\n"),
        "a fence wrapping a rule": doc.replace("\n送信は本人の OK の後。\n", "\n```\n送信は本人の OK の後。\n```\n"),
        "an inline comment opened": doc.replace("レビューを経てから deploy する。", "<!--。 レビューを経てから deploy する。 -->。"),
        "strikethrough": doc.replace("送信は本人の OK の後。", "~~送信は本人の OK の後。~~"),
        "a free zone declared by the agent": doc + "\n<!-- agent-free:begin id=x -->\n<!-- agent-free:end id=x -->\n",
        "a rule reference changed": (f"See {RULE_REF_TOKENS[0]} for limits.\n",  # token built, not literal:
                                     f"See {RULE_REF_TOKENS[0]} for limits, and more.\n"),  # this file has no ref lines
    }
    for name, new in weakened.items():
        old_text, new_text = new if isinstance(new, tuple) else (doc, new)
        check("still needs approval: " + name, exempt("conventions/deploy.md", old_text, new_text) is False)
    check("a whole-file marker keeps the full lock",
          exempt("conventions/x.md", "<!-- agent-authority:file -->\n" + doc,
                 "<!-- agent-authority:file -->\n" + grown["a new section at the end"]) is None)
    check("the guard's own rule documents keep the full lock",
          exempt("conventions/agent-rule-ownership.md", doc, grown["a new section at the end"]) is None)
    check("manifest paths keep the full lock",
          exempt("docs/policy.md", doc, grown["a new section at the end"], ("docs/*",)) is None)
    check("settings are not prose policy documents", exempt(".claude/settings.json", "{}", '{"a": 1}') is None)
    check("a deletion of the document is not an insertion", exempt("conventions/deploy.md", doc, "") is False)
    check("the reason names what failed",
          "緩和の語「without」" in judge_change("# R\n\nReview is required before deployment.\n", "# R\n\nDeploy without review.\n")[1]
          and "言い直しで緩和の語「例外」" in judge_change(doc, weakened["an edit that moves a listed word into a relaxing position"])[1]
          and "言い直しで緩和の語「でよい」" in judge_change(doc, weakened["an edit that adds a permission to an existing sentence"])[1]
          and "code / comment" in judge_change(doc, weakened["a fence wrapping a rule"])[1]
          and relax_hit("### 旧手順 (参考)") in ("旧", "参考"))
    check("relax_terms lists every term of a sentence, in a relaxing position only",
          {"ただし", "してよい"} <= set(relax_terms("ただし急ぐ時は deploy してよい。")) and relax_terms("様式が改訂されても同じ。") == []
          and relax_terms("<!-- x") == ["<!--"])
    check("everyday use of a listed term passes: without a thing", exempt("conventions/deploy.md", doc, doc + "\nThe check works without a network.\n") is True)

    zoned = ("# P\n\n規則の文。\n\n<!-- agent-free:begin id=status -->\n- a: 進行中\n<!-- agent-free:end id=status -->\n"
             "\n<!-- agent-authority:begin id=gate -->\n門は下げない。\n<!-- agent-authority:end id=gate -->\n")
    def moved(old, new, path="CLAUDE.md"):
        a, b = authority_regions(old, path), authority_regions(new, path)
        return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    check("a free zone body is outside the file lock",
          moved(zoned, zoned.replace("- a: 進行中", "- a: 完了、 archive へ")) == [])
    check("a locked block keeps its lock next to a free zone",
          "authority:gate" in moved(zoned, zoned.replace("門は下げない。", "門は下げてよい。")))
    check("an insertion inside a locked block keeps the block lock",
          "authority:gate" in moved(zoned, zoned.replace("門は下げない。", "門は下げない。 実測あり。")))
    check("moving a zone marker is a file change",
          moved(zoned, zoned.replace("<!-- agent-free:begin id=status -->\n", "").replace(
              "\n規則の文。\n", "\n<!-- agent-free:begin id=status -->\n規則の文。\n")) == ["authority:file"])
    check("an unterminated zone frees nothing",
          moved("x\n<!-- agent-free:begin id=z -->\na\n", "x\n<!-- agent-free:begin id=z -->\nb\n") == ["authority:file"])
    fenced = "x\n```\n<!-- agent-free:begin id=z -->\na\n<!-- agent-free:end id=z -->\n```\n"
    check("a zone whose markers sit in one code fence frees the lines between them",
          moved(fenced, fenced.replace("\na\n", "\nb\n")) == [])
    tree = ("# R\n\n規則の文。\n\n```\nrepo/\n├── a.md\n<!-- agent-free:begin id=t -->\n├── scripts/  # 251 file\n"
            "<!-- agent-free:end id=t -->\n└── z.md\n```\n\n後の規則。\n")
    check("a generated tree line inside a fenced zone is free (the declared trees)",
          moved(tree, tree.replace("251 file", "252 file")) == [])
    check("a fenced zone does not free the fence lines outside its markers",
          moved(tree, tree.replace("├── a.md", "├── b.md")) == ["authority:file"])
    check("a fenced zone does not free the prose after the fence",
          moved(tree, tree.replace("後の規則。", "後の規則は無い。")) == ["authority:file"])
    crossing = "x\n```\n<!-- agent-free:begin id=z -->\na\n```\n<!-- agent-free:end id=z -->\nrule\n"
    check("a zone crossing a fence boundary frees nothing",
          moved(crossing, crossing.replace("\na\n", "\nb\n")) == ["authority:file"])
    two = "x\n```\n<!-- agent-free:begin id=z -->\na\n```\nrule\n```\n<!-- agent-free:end id=z -->\n```\n"
    check("a zone spanning two separate fences frees nothing",
          moved(two, two.replace("\nrule\n", "\nno rule\n")) == ["authority:file"])
    commented = "x\n<!-- hidden\n<!-- agent-free:begin id=z -->\na\n<!-- agent-free:end id=z -->\ny\n"
    check("a begin marker inside an HTML comment frees nothing",
          moved(commented, commented.replace("\na\n", "\nb\n")) == ["authority:file"])
    twice = zoned + "\n<!-- agent-free:begin id=status -->\n規則。\n<!-- agent-free:end id=status -->\n"
    check("a repeated zone id frees only its first zone",
          moved(twice, twice.replace("\n規則。\n", "\n規則でない。\n")) == ["authority:file"])
    r = change_exemption("CLAUDE.md", zoned, zoned.replace("- a: 進行中", "- a: 進行中、 確認不要"))
    check("relaxation words inside a free zone are logged, not blocked",
          r is not None and r["ok"] and r["free"] and r["free"][0][1] == "不要")
    unzoned = zoned.replace("<!-- agent-free:begin id=status -->\n", "").replace("<!-- agent-free:end id=status -->\n", "")
    r = change_exemption("CLAUDE.md", unzoned, zoned)
    check("creating a zone (a locked change) does not log its initial body as written into the zone",
          r is not None and not r["ok"] and r["free"] == [])
    print(f"agent-rule-guard selftest: {len(failures)} failure(s)")
    return bool(failures)


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        raise SystemExit(selftest())
    # The compatible dispatcher owns sessions, quote verification and tool/Git
    # reconstruction; there is no second approval implementation here.
    dispatcher = Path(__file__).with_name("manuscript-claim-guard.py")
    runpy.run_path(str(dispatcher), run_name="__main__")
