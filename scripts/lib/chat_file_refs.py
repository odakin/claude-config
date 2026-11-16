"""chat_file_refs.py — chat の最終発話にある file 参照 (markdown link の href と、 path に見える inline code) を、 Claude Code desktop app の右パネルと同じ基準で解決し、 開けないものに正しい path を添えて返す共通部品 (Stop hook chat-file-ref-enforce.sh と校正が共用)

解決の規則 (desktop app の bundle で確認、 正本 = conventions/claude-code-permissions.md#chat-link-resolution-base):
- 相対 path は **まず session を始めたときに選んだ folder** に連結する。 Bash の cd で harness が通知する
  「Primary working directory」 が変わっても、 この基準は変わらない。 app 5.11492.5 は、 そこで見つからない相対 path を
  shell が入った folder (始めた folder の中のもの) と app で足した folder でも探すが、 その段は遠隔の停止スイッチの下にあり
  版でも変わるので写さない (= 止めすぎの側。 書き直しの先の絶対 path は版に依らず開く)。
- 絶対 path はそのまま、 `~/` は home に展開する。
- **開くかは file の実体で決まる** (app の main process の containToGrantedRoots): symlink を解いた実体 path が、 根
  (始めた folder と app で session に足した folder) の実体のどれかの中のときだけ開く。 `~/Claude/<repo>` が同期 folder への
  symlink の repo では、 書いた path が中に見えても開かない (表示は「見つかりませんでした」)。 settings の
  `permissions.additionalDirectories` は根に入らない。 transcript の environment snapshot の追加 folder にはそれも入って
  いるので、 settings の folder を引いて app で足した folder を近似する (panel_extra_dirs)。
- inline code の中身も、 `/` を含み拡張子で終わる形なら、 file が実在しなくても link として描かれる (実測。
  `CLAUDE.md` のような区切りの無い名前と `dir/` は描かれない)。 link の label の中の inline code は別の link に
  ならない (押すと href が開く) ので拾わない。
- 基準フォルダが git repo のとき、 app の本体は連結した先に file が無いと `git ls-files` (無ければ untracked) で
  path の末尾一致を探し、 1 件に決まればそれを開く。 この第 1 段を写している (git_suffix_matches)。 複数一致のときの
  本体の絞り込み (変更中の file に近いものを選ぶ) は写さず、 開けない側に数える。
- worktree に入った session で本体が worktree の path を先に試す挙動は写していない (正本の同節)。

検出の条件 (= 誤検出を避けるため狭くとる):
  (a) 開けない (基準 folder に連結すると存在しない / 基準の外に出る) ∧ 別の folder に連結すると存在する。
      別の folder = transcript に出た cwd (新しい順) → 基準 folder の直下の dir。
      どこにも無い path (例示の `path/to/file.md` など) は拾わない。
  (b) 意図と違う file が開く (reason = shadowed): 基準 folder に連結すると file が在るが、 直近の cwd (≠ 基準) にも
      同じ相対 path の別の file が在る (例: 親フォルダと repo の両方に在る CLAUDE.md を repo の中で書いた)。
  (c) href を山括弧で囲んだ link (reason = angle): `[x](<path>)` は CommonMark では正しいが、 app は山括弧ごと path に
      する (実測 = 「見つかりませんでした」 の path 欄に `<…>` が付いた)。 中身の path が在るときだけ拾い、 囲まずに
      空白・丸括弧を `%20`・`%28`・`%29` にした形を示す (href は decodeURI してから解釈される)。 濁点の形も違えば
      (reason = angle_nfd) disk 上の綴りで示す。
  (d) 濁点の形だけが disk 上の名前と違う (reason = nfd): 実在する file への参照で、 path のある成分が disk 上の名前と
      Unicode の正規化 (NFC / NFD) だけ違う。 macOS の file system は正規化を問わず開けるので exists は通るが、 app の
      表示要求は解決できないことがある (実測 = Dropbox の NFD の file 名)。 disk 上の綴りを示す。
  (c)(d) は絶対 path・`~/` の参照も見る (開くかどうかが基準フォルダに依らない形)。
  (e) 音声・動画が右パネルで鳴らない (reason = media_outside / media_large): 右パネルの再生器が読むのは基準フォルダ
      (と scratchpad) の中の 25 MB 以下の file だけ (app 4.4212.0 の本体 = 正本 claude-code-permissions.md
      #chat-panel-media-playback)。 実在する音声・動画への参照 (絶対 path も、 (a) で示す候補も) で、 近くに聞く・見るの語が
      ある (listen_intent = 置き場所の記録は除く) ものがその外か上限超なら拾い、 link への書き直しでなく、 流して聞かせる
      ことを案内する。 語の無い参照は従来どおり (a)〜(d) だけを見る。 外かどうかは実体の path で決める (app と同じ)。
      settings の追加フォルダ (同期フォルダなど) は右パネルの範囲に入らないので中に数えない。 その turn の Bash で
      同じ file を afplay・open などで流していれば拾わない (drop_played。 `open -R` は Finder で見せるだけなので数えない)。
  (f) 実体が session の folder の外 (reason = outside_real): 実在する file への参照 (絶対 path・`~/`・相対 path のどれも) で、
      実体が根の外のもの。 書き直しの先 (別の folder に連結すると在る候補) が全部その外のときも、 書き直しを勧めずにこれを
      出す (書き直しても開かない)。 scratchpad の形の path は外に数えない (show_pane で解決を通る = 実測)。
      直し方は、 その file の実体の folder を session に 1 回足す (mcp__ccd_directory__request_directory) こと。 足す folder
      (add_dir) = 外を指す最初の symlink の実体 (symlink の repo・dropbox-refs)、 無ければ git の work tree の最上段かその folder。
      足した folder は transcript の次の environment snapshot に入るので、 足した後の turn では拾わない (実測)。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import unicodedata
from urllib.parse import unquote

# session の基準フォルダ・cwd・追加フォルダ・entrypoint の読み出しは transcript の共通部品が持つ
from transcript_turns import (session_additional_dirs, session_entrypoint,  # noqa: F401
                              session_root_and_cwds)

# fence の前置きは桁数を問わず、 引用の `>` も許す (list の中で 4 桁以上 indent された fence と、 引用の中の fence も
# 描画上は code block。 広く取る側 = 検出が減る側なので、 取りすぎても誤検出にはならない)
# backtick の fence は info (同じ行の残り) に backtick を書けない = 行頭の inline な 3 連 backtick (```code``` は…) は
# fence ではない。 fence と取り違えると、 次の fence か末尾までの本物の参照を見逃す
FENCE_RE = re.compile(r"^[ \t>]*(`{3,}(?=[^`\n]*\n)|~{3,})[^\n]*\n.*?(?:^[ \t>]*\1[ \t]*$|\Z)", re.S | re.M)
CODE_SPAN_RE = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)")
LINK_RE = re.compile(r"\[[^\]\n]*\]\(\s*<([^>\n]+)>[^)\n]*\)|\[[^\]\n]*\]\(\s*([^)\s]+)(?:\s+\"[^\"\n]*\")?\s*\)")
# scheme の判定は app と同じ式 (bundle の file 参照 parser)。 `SESSION.md:42` のような「区切りの無い名前 + 行番号」 は
# scheme ではなく file + 行番号 (class に `.` が無い + 行番号の後置は scheme にしない)
SCHEME_RE = re.compile(r"^[a-z][a-z0-9+-]+:(?!\d+(?:[-:]\d+)?$)", re.I)
# inline code を link として描く形 = app の file 参照 parser の式を写したもの (読んだ版は正本の同節):
#   ^([L.()[\]-]*(?:/[L.()[\]-]+)*/[L()[\]-]*\.\w[\w.-]*)(?::(\d+)(?:-(\d+)|:\d+)?)?$   L = \p{L}\p{N}\p{M}_ 、 \w は ASCII
# 使える文字は文字・数字・結合文字・`_` `.` `-` `(` `)` `[` `]` だけ (空白・`~`・`@`・`+`・`$`・`*` を含むと link にならない)。
# python の re に \p{…} は無いので、 L = \w (Unicode の文字・数字・_) + 主な結合文字の範囲で近似する。
_L = r"\w\u0300-\u036F\u1AB0-\u1AFF\u1DC0-\u1DFF\u20D0-\u20FF\u3099\u309A\uFE20-\uFE2F"
CODE_PATH_RE = re.compile(
    rf"^[{_L}.()\[\]-]*(?:/[{_L}.()\[\]-]+)*/[{_L}()\[\]-]*\.[A-Za-z0-9_][A-Za-z0-9_.-]*(?::\d+(?:-\d+|:\d+)?)?$")
LINE_SUFFIX_RE = re.compile(r":\d+(?:[-:]\d+)?$")
ANGLE_HREF_RE = re.compile(r"\]\(\s*<")  # `[x](<path>)` = href を山括弧で囲んだ link
# 右パネルが再生器で開く拡張子 (app の画面の音声の式 + 動画の MIME の表) と、 main process が読む上限
# (SESSION_PANEL_MEDIA_MAX_BYTES、 超えると読まない)。 読んだ版 = 正本の #chat-panel-media-playback
MEDIA_EXT_RE = re.compile(r"\.(?:mp3|m4a|aac|wav|flac|opus|ogg|oga|mp4|webm|mov|m4v|ogv)$", re.I)
PANEL_MEDIA_MAX_BYTES = 26214400
SCRATCHPAD_RE = re.compile(r"^/(?:private/)?tmp/claude-[^/]+/.+/scratchpad(?:/|$)")  # 右パネルの解決を通る (実測)
PLAY_CMD_RE = re.compile(r"\b(?:afplay|qlmanage|ffplay|mpv|vlc|open(?!\s+-R\b))\b")
# 聞いて・見てもらうつもりの参照か (参照の前 200 字〜後 80 字)。 置き場所の記録 (講義の動画の置き場・写した先) は拾わない
# (校正: 14 日の desktop で音声・動画の参照 14 turn のうち、 この語の無い 10 turn は置き場所の記録だった)
LISTEN_RE = re.compile(r"聞|聴|試聴|視聴|listen", re.I)


def _blank(m: re.Match) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def extract_refs(text: str) -> list[tuple[str, str, str]]:
    """最終発話 → [(kind, raw, path)]。 kind = "link" | "code"。 fenced block の中は描かれないので見ない。"""
    body = FENCE_RE.sub(_blank, text or "")
    blanked = CODE_SPAN_RE.sub(_blank, body)  # code span の中の [..](..) は link として描かれない (長さは保つ)
    links = [m for m in LINK_RE.finditer(blanked) if (m.group(1) or m.group(2) or "").strip()]
    refs: list[tuple[str, str, str]] = []
    for m in CODE_SPAN_RE.finditer(body):
        inner = m.group(2).strip()
        if not CODE_PATH_RE.match(inner):
            continue
        # link の label の中の inline code は別の link にならない (app は anchor の子を「link の中」 として描き、
        # 押すと href が開く)。 [`dir/file.md`](/絶対/path) を code の側で拾わない
        if any(lm.start() <= m.start() < lm.end() for lm in links):
            continue
        refs.append(("code", m.group(0), inner))
    for m in links:
        refs.append(("link", m.group(0), (m.group(1) or m.group(2)).strip()))
    return refs


def normalize(path: str) -> str | None:
    """href / code span → file system 上の相対 path。 対象外 (URL・anchor のみ・絶対・~/) は None。"""
    p = path.strip()
    if not p or p.startswith("#"):
        return None
    if SCHEME_RE.match(p) or p.startswith("//"):
        return None  # http: / mailto: / file: など
    p = p.split("#", 1)[0].split("?", 1)[0]
    p = LINE_SUFFIX_RE.sub("", p)
    p = unquote(p)
    if not p or p.startswith("/") or p == "~" or p.startswith("~/"):
        return None
    return p


def local_target(path: str) -> str | None:
    """href / code span → 絶対 path (絶対 path はそのまま、 `~/` は home に展開)。 相対・URL・anchor のみは None。"""
    p = path.strip()
    if not p or p.startswith("#") or SCHEME_RE.match(p) or p.startswith("//"):
        return None
    p = unquote(LINE_SUFFIX_RE.sub("", p.split("#", 1)[0].split("?", 1)[0]))
    if p.startswith("~/"):
        return os.path.expanduser(p)
    return p if p.startswith("/") else None


def disk_spelling(path: str) -> str | None:
    """実在する path の各成分を disk 上の名前と文字列で比べ、 正規化 (NFC / NFD) だけが違う成分があれば disk 上の綴りの
    path を返す。 違いが無い・成分が見つからない・候補が 1 つに決まらないときは None (= 拾わない側に倒す)。"""
    parts = [x for x in os.path.normpath(path).split(os.sep) if x]
    cur, changed = os.sep, False
    for part in parts:
        try:
            names = os.listdir(cur)
        except OSError:
            return None
        if part not in names:
            want = unicodedata.normalize("NFC", part)
            hits = [n for n in names if unicodedata.normalize("NFC", n) == want]
            if len(hits) != 1:
                return None
            part, changed = hits[0], True
        cur = os.path.join(cur, part)
    return cur if changed else None


def _href_form(path: str) -> str:
    """囲まずに書ける href の形 = 空白と丸括弧を % で符号化 (app は decodeURI してから解釈する。 丸括弧を残すと link が切れる)。"""
    return path.replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def _form_finding(kind: str, raw: str, shown: str, target: str, angle: bool) -> dict | None:
    """実在する target への参照の書き方の問題 = 山括弧 (c) か濁点の形 (d)、 または両方。 無ければ None。
    山括弧の提案も disk 上の綴りで出す (囲みを外しても濁点の形が違えば開かない = 2026-10-13 の実例は両方だった)。"""
    disk = disk_spelling(target)
    if angle:
        reason = "angle_nfd" if disk else "angle"
        return {"kind": kind, "raw": raw, "path": shown, "reason": reason, "candidates": [_href_form(disk or target)]}
    if disk:
        return {"kind": kind, "raw": raw, "path": shown, "reason": "nfd", "candidates": [disk]}
    return None


def _inside(path: str, root: str) -> bool:
    rel = os.path.relpath(path, root)
    return rel != ".." and not rel.startswith(".." + os.sep)


def listen_intent(text: str, raw: str) -> bool:
    """参照の近く (前 200 字〜後 80 字) に聞く・見るの語があるか = 置き場所の記録でなく、 聞いて・見てもらう参照か。"""
    i = text.find(raw)
    return i >= 0 and LISTEN_RE.search(text[max(0, i - 200):i + len(raw) + 80]) is not None


def media_block(path: str, root: str) -> str | None:
    """実在する音声・動画を右パネルが鳴らせない理由 (media_outside / media_large)。 鳴らせるか、 音声・動画でなければ None。"""
    if not MEDIA_EXT_RE.search(path) or not os.path.isfile(path):
        return None
    real = os.path.realpath(path)
    if not (_inside(real, os.path.realpath(root)) or SCRATCHPAD_RE.match(real) or SCRATCHPAD_RE.match(path)):
        return "media_outside"
    try:
        return "media_large" if os.path.getsize(real) > PANEL_MEDIA_MAX_BYTES else None
    except OSError:
        return None


def settings_additional_dirs(root: str | None) -> set[str]:
    """settings の permissions.additionalDirectories (user の設定フォルダと、 基準 folder の project の .claude/)。
    Read/Edit/Write の範囲には入るが、 右パネルの根には入らない。"""
    cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    paths = [os.path.join(cfg, n) for n in ("settings.json", "settings.local.json")]
    if root:
        paths += [os.path.join(root, ".claude", n) for n in ("settings.json", "settings.local.json")]
    out: set[str] = set()
    for sp in paths:
        try:
            with open(sp, encoding="utf-8") as f:
                dirs = (json.load(f).get("permissions") or {}).get("additionalDirectories") or []
        except Exception:
            continue
        for d in dirs:
            if isinstance(d, str) and d:
                out.add(os.path.normpath(os.path.expanduser(d)))
    return out


def panel_extra_dirs(extra_roots: list[str] | None, root: str | None) -> list[str]:
    """右パネルの根に入る追加の folder = app で session に足した folder の近似 = snapshot の追加 folder − settings の folder。
    両方に在る folder は外に数える (= 止めすぎの側。 代償は書き直し 1 回)。"""
    s = settings_additional_dirs(root)
    s_real = {os.path.realpath(d) for d in s}
    out: list[str] = []
    for d in extra_roots or []:
        n = os.path.normpath(os.path.expanduser(d))
        if n in s or os.path.realpath(n) in s_real or n in out:
            continue
        out.append(n)
    return out


WORKTREE_ROOT_RE = re.compile(r"^(.+)/\.claude/worktrees/[^/]+/?$")


def panel_real_roots(root: str, panel_extras: list[str]) -> list[str]:
    """右パネルの根の実体 (app は根の realpath と file の realpath を比べる)。 app の根には session の元の folder (originCwd) も
    入る = desktop の worktree (`<repo>/.claude/worktrees/<名>`) で始めた session では元の repo も根に数える
    (snapshot に originCwd は無いので path の形から取る)。"""
    dirs = [root, *panel_extras]
    m = WORKTREE_ROOT_RE.match(root or "")
    if m:
        dirs.append(m.group(1))
    return [os.path.realpath(d) for d in dirs if d]


def opens_in_panel(path: str, real_roots: list[str]) -> bool:
    """実在する file が右パネルの根の中か (実体 path で判定 = app の containToGrantedRoots)。 scratchpad の形は中に数える。"""
    real = os.path.realpath(path)
    if SCRATCHPAD_RE.match(real) or SCRATCHPAD_RE.match(path):
        return True
    return any(_inside(real, r) for r in real_roots)


def folder_to_add(path: str, root: str, real_roots: list[str]) -> str:
    """実体が根の外の file / folder を右パネルで開けるようにするために session に足す folder (実体の path)。
    基準 folder の中に見える path なら、 外を指す最初の symlink の実体 (= symlink の repo や dropbox-refs の実体)。
    それ以外は、 その file の在る folder から上へ探した git の work tree の最上段、 無ければその folder。"""
    p = os.path.normpath(path)
    if _inside(p, root) and p != root:
        cur = root
        for part in os.path.relpath(p, root).split(os.sep):
            cur = os.path.join(cur, part)
            if os.path.islink(cur):
                real = os.path.realpath(cur)
                if not any(_inside(real, r) for r in real_roots):
                    return real
    d = os.path.realpath(p if os.path.isdir(p) else os.path.dirname(p))
    cur = d
    while True:
        if os.path.exists(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return d
        cur = parent


def candidate_dirs(root: str, seen_cwds: list[str] | None = None) -> list[str]:
    """別の基準の候補。 transcript に出た cwd (呼び出し側が新しい順に渡す) → root 直下の dir。 重複は除く。
    session の追加フォルダは呼び出し側 (find_broken) が最後に足す。"""
    out: list[str] = []
    for d in (seen_cwds or []):
        if d and os.path.isdir(d) and os.path.normpath(d) != os.path.normpath(root):
            out.append(os.path.normpath(d))
    try:
        for name in sorted(os.listdir(root)):
            if name.startswith("."):
                continue
            d = os.path.join(root, name)
            if os.path.isdir(d):
                out.append(os.path.normpath(d))
    except OSError:
        pass
    uniq: list[str] = []
    for d in out:
        if d not in uniq:
            uniq.append(d)
    return uniq


def git_listing(root: str) -> tuple[list[str], list[str]] | None:
    """基準フォルダが git の work tree なら (tracked, untracked) の相対 path、 違えば None。 app と同じ
    `git -c core.quotepath=false ls-files` (untracked は `--others --exclude-standard`) を基準フォルダで打つ。"""
    out = []
    for extra in ([], ["--others", "--exclude-standard"]):
        try:
            r = subprocess.run(["git", "-C", root, "-c", "core.quotepath=false", "ls-files", *extra],
                               capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        if r.returncode != 0:
            return None
        out.append(r.stdout.split("\n"))
    return out[0], out[1]


def git_suffix_matches(listing: tuple[list[str], list[str]] | None, p: str) -> list[str]:
    """app の末尾一致の第 1 段: tracked で `p` に等しいか `/p` で終わる path、 無ければ untracked で同じ。"""
    if listing is None:
        return []
    r = p[2:] if p.startswith("./") else p
    tail = "/" + r
    for names in listing:
        hits = sorted({n for n in names if n == r or n.endswith(tail)})
        if hits:
            return hits
    return []


def find_broken(text: str, root: str, seen_cwds: list[str] | None = None, limit: int = 3,
                extra_roots: list[str] | None = None, git_cache: dict | None = None,
                panel_extras: list[str] | None = None) -> list[dict]:
    """開けない参照のうち、 別の基準なら存在するもの + 意図と違う file が開くもの + 実体が session の folder の外のもの。
    [{kind, raw, path, reason, candidates}] (reason = missing | outside | shadowed | outside_real ほか、 candidates は絶対 path。
    outside_real の candidates は file の実体 path = 置き場所)。
    extra_roots = transcript の snapshot の追加 folder (settings の folder を含む) = 書き直しの候補を探す場所。
    panel_extras = 右パネルの根に入る追加 folder (app で足した folder)。 省けば extra_roots − settings の folder。
    `../` で基準の外に出ても、 連結した先の実体が根の中なら app は開くので拾わない。"""
    if not root or not os.path.isdir(root):
        return []
    root = os.path.normpath(root)
    extras = [os.path.normpath(os.path.expanduser(d)) for d in (extra_roots or []) if d]
    pextras = panel_extras if panel_extras is not None else panel_extra_dirs(extras, root)
    real_roots = panel_real_roots(root, pextras)
    cur = next((os.path.normpath(d) for d in (seen_cwds or []) if d), None)  # 直近の cwd
    dirs = None
    listing: tuple[list[str], list[str]] | None | bool = False  # False = まだ引いていない
    findings: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for kind, raw, ref in extract_refs(text):
        angle = kind == "link" and ANGLE_HREF_RE.search(raw) is not None
        absolute = local_target(ref)
        p = normalize(ref)
        key = (kind, p if p is not None else absolute)
        if key[1] is None or key in seen:
            continue
        seen.add(key)
        if absolute is not None:
            # 絶対 path・~/ は基準フォルダに依らず解決する。 書き方の問題 (山括弧・濁点の形)・音声・動画と、 実体の場所を見る
            if os.path.exists(absolute):
                f = _form_finding(kind, raw, ref.strip(), os.path.normpath(absolute), angle)
                media = None if f or not listen_intent(text, raw) else media_block(absolute, root)
                if f:
                    findings.append(f)
                elif media:
                    findings.append({"kind": kind, "raw": raw, "path": ref.strip(), "reason": media,
                                     "candidates": [os.path.normpath(absolute)]})
                elif os.path.isfile(absolute) and not opens_in_panel(absolute, real_roots):
                    # 中に見える path でも実体が外 (symlink の repo の file / 同期 folder の file) = 書き直しても開かない
                    findings.append({"kind": kind, "raw": raw, "path": ref.strip(), "reason": "outside_real",
                                     "candidates": [os.path.realpath(absolute)],
                                     "add_dir": folder_to_add(absolute, root, real_roots)})
            continue
        target = os.path.normpath(os.path.join(root, p))
        if not _inside(target, root):
            if os.path.isfile(target) and opens_in_panel(target, real_roots):
                continue
            reason = "outside"
        elif os.path.exists(target):
            f = _form_finding(kind, raw, p, target, angle)
            if f:
                findings.append(f)
                continue
            media = media_block(target, root) if listen_intent(text, raw) else None
            if media:  # 開くが鳴らない (repo の中の同期フォルダへの symlink の先 / 25 MB 超)
                findings.append({"kind": kind, "raw": raw, "path": p, "reason": media, "candidates": [target]})
                continue
            if os.path.isfile(target) and not opens_in_panel(target, real_roots):
                # 基準 folder からの正しい path だが、 途中の symlink が外を指す (実例 = 同期フォルダへの symlink の repo)
                findings.append({"kind": kind, "raw": raw, "path": p, "reason": "outside_real",
                                 "candidates": [os.path.realpath(target)],
                                 "add_dir": folder_to_add(target, root, real_roots)})
                continue
            # 開くが、 直近の cwd に同じ相対 path の別の file が在る = repo の中からの path のつもりで書いた可能性
            other = os.path.normpath(os.path.join(cur, p)) if cur and cur != root else None
            if (other and os.path.isfile(target) and os.path.isfile(other)
                    and os.path.realpath(other) != os.path.realpath(target)):
                findings.append({"kind": kind, "raw": raw, "path": p, "reason": "shadowed", "candidates": [other]})
            continue
        else:
            reason = "missing"
        if dirs is None:
            # 追加フォルダも候補に入れる: そこを起点に書いた path (例 = 同期フォルダを追加した session の `<sub>/…/x.pdf`) は
            # 基準フォルダにも cwd にも無く、 入れないと「どこにも無い例示の path」 として素通りする (実測)
            dirs = candidate_dirs(root, seen_cwds)
            dirs += [d for d in extras if os.path.isdir(d) and d not in dirs]
        # 基準の外に出た先が実在するなら、 それ自体が正しい相手 (絶対 path で示す)
        cands: list[str] = [target] if reason == "outside" and os.path.exists(target) else []
        for d in dirs:
            c = os.path.normpath(os.path.join(d, p))
            if os.path.exists(c) and c not in cands:
                cands.append(c)
                if len(cands) >= limit:
                    break
        if not cands:
            continue
        if reason == "missing":
            # git は候補が在る参照にだけ、 1 回の判定につき 1 度だけ聞く (例示の path や git でない基準では呼ばない / すぐ戻る)
            if listing is False:
                if git_cache is not None and root in git_cache:
                    listing = git_cache[root]
                else:
                    listing = git_listing(root)
                    if git_cache is not None:
                        git_cache[root] = listing  # 校正用 (同じ基準フォルダを何百 turn も引くので 1 回にする)
            if len(git_suffix_matches(listing, p)) == 1 and not angle:
                continue  # 基準フォルダが git repo で末尾一致が 1 件 = app はそれを開く (山括弧つきは囲みごと探すので開かない)
        media = None if angle or not listen_intent(text, raw) else media_block(cands[0], root)
        openable = [c for c in cands if opens_in_panel(c, real_roots)]
        add_dir = None
        if media:  # 書き直しても鳴らない = 書き直しでなく流すことを案内する
            reason = media
        elif not openable:  # 候補が全部、 実体が根の外 (settings だけの追加 folder・symlink の先) = 書き直しても開かない
            add_dir = folder_to_add(cands[0], root, real_roots)
            reason, cands = "outside_real", [os.path.realpath(c) for c in cands]
        else:
            cands = openable
            if angle:  # 置き場所も山括弧も直す = 囲まずに、 候補の path で
                reason, cands = "angle", [_href_form(c) for c in cands]
        finding = {"kind": kind, "raw": raw, "path": p, "reason": reason, "candidates": cands}
        if add_dir:
            finding["add_dir"] = add_dir
        findings.append(finding)
    return findings


def panel_place_fast(cwd: str, transcript_path: str, max_lines: int = 200) -> str:
    """事前の知らせ (hooks/chat-path-base-nudge.sh) 用: cwd の実体が右パネルの根の中か。 transcript の先頭だけ読む。
    "inside" (始めた folder か app で足した folder の中) / "scratchpad" / "outside\\t<足す folder>" / 読めなければ ""。
    足す folder = folder_to_add (symlink の repo なら実体の repo、 それ以外は git の work tree の最上段かその folder)。"""
    import transcript_turns as tt

    snap = None
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if isinstance(e, dict):
                    snap = next((s for s in tt._env_snapshots([e]) if isinstance(s.get("workingDirectory"), str)), None)
                    if snap:
                        break
    except OSError:
        return ""
    if not snap or not cwd:
        return ""
    root = os.path.normpath(snap["workingDirectory"])
    extras = [d for d in snap.get("additionalWorkingDirectories") or [] if isinstance(d, str)]
    real = os.path.realpath(cwd)
    if SCRATCHPAD_RE.match(real) or SCRATCHPAD_RE.match(cwd):
        return "scratchpad"
    roots = panel_real_roots(root, panel_extra_dirs(extras, root))
    if any(_inside(real, r) for r in roots):
        return "inside"
    return "outside\t" + folder_to_add(cwd, root, roots)


# ---- hook / 校正の入口 -------------------------------------------------------------

# 右パネルで file を開く frontend。 CLI (端末) には右パネルが無いので対象外。
PANEL_ENTRYPOINTS = ("claude-desktop", "claude-desktop-3p", "claude-vscode")  # 名前は engine の entrypoint 一覧で確認
DOC = "claude-config/conventions/claude-code-permissions.md#chat-link-resolution-base"
BT = chr(96)  # backtick


def _show(path: str, root: str) -> str:
    return os.path.relpath(path, root) if _inside(path, root) else path


def drop_played(findings: list[dict], turn: list[dict]) -> list[dict]:
    """音声・動画の finding のうち、 同じ turn の Bash で流した (afplay・open など) file のものを除く。"""
    cmds = []
    for e in turn:
        if e.get("type") != "assistant":
            continue
        for b in (e.get("message") or {}).get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Bash":
                cmd = str((b.get("input") or {}).get("command") or "")
                if PLAY_CMD_RE.search(cmd):
                    cmds.append(cmd)
    played = "\n".join(cmds)
    return [f for f in findings
            if not (f["reason"].startswith("media_") and os.path.basename(f["candidates"][0]) in played)]


# 実体が外の file の参照の直し方 = その file の実体の folder を session に 1 回足してから link を出す (足すと、 その folder の
# file は symlink の path でも実体の path でも右パネルの解決を通る = 実測 app 5.11492.5)。 足せないときの見せ方も並べる
OUTSIDE_FIX = (
    "実体が外の file は、 そのままでは link でも inline code でも右パネルで開きません。 上の「足すフォルダ」 を "
    "mcp__ccd_directory__request_directory (path にそのフォルダ) でこの session に 1 回足してから、 同じ link を出してください "
    "(足すと、 そのフォルダの file は書いた path のままで開きます。 本人に確認の画面が 1 回出ることがあります)。 "
    "足せなかった (断られた・止められた) ときは、 PDF は open で Preview に出したと書き、 md・text は中身を本文に出し、 "
    "置き場所は fenced code block の中に書く (本文の絶対 path と inline code の path はリンクとして描かれる)。 "
    "直した部分だけを短い追記として出してください (最終メッセージ全体は出し直さない)。 "
    "正本 = claude-config/conventions/claude-code-permissions.md#chat-link-rendering-scope")


def build_reason(findings: list[dict], root: str) -> str:
    shadowed = any(f["reason"] == "shadowed" for f in findings)
    media = [f for f in findings if f["reason"].startswith("media_")]
    outside = [f for f in findings if f["reason"] == "outside_real"]
    what = ("右パネルで鳴りません" if len(media) == len(findings) else
            "右パネルでは開きません (file の実体が session のフォルダの外)" if len(outside) == len(findings) else
            "右パネルで開けないか、 意図と違う file を開きます" if shadowed else "右パネルで開けません")
    lines = [
        f"🔗 chat-file-ref: 最終メッセージの file 参照 {len(findings)} 件が、 {what}。 "
        f"desktop app は相対 path をまず session を始めたフォルダ ({root}) に連結します "
        f"(Bash の cd で変わる「作業ディレクトリ」 ではありません。 cd した先でも探す版がありますが、 "
        f"その段は版と遠隔の設定で変わるので頼らない)。 "
        f"開くのは file の実体 (symlink を解いた先) が session のフォルダ (始めたフォルダと app で足したフォルダ) の"
        f"中のときだけです。 inline code の {BT}dir/file.ext{BT} もリンクとして描かれます。",
    ]
    where_of = {"outside": "フォルダの外", "missing": "存在しない",
                "outside_real": "実体が session のフォルダの外 (symlink の先・同期フォルダ。 settings の追加フォルダは数えない) "
                                "= 絶対 path でも開かない。 実体は",
                "shadowed": "上のフォルダの同名の別 file が開く。 作業中のフォルダの file を指すなら",
                "angle": "href を山括弧 <…> で囲んでいる = 山括弧ごと path になり開けない。 囲まずに、 空白・丸括弧は %20・%28・%29 で",
                "angle_nfd": "href を山括弧 <…> で囲んでいて、 file 名の濁点の形 (NFC / NFD) も disk 上の名前と違う。 "
                             "ASCII の名前の写しに link するか SendUserFile で渡すのが確実。 書くなら囲まずに disk 上の綴りで",
                "nfd": "file 名の濁点の形 (NFC / NFD) が disk 上の名前と違い、 開けないことがある。 "
                       "ASCII の名前の写しに link するか SendUserFile で渡す。 disk 上の名前は",
                "media_outside": "音声・動画。 右パネルは session のフォルダ (と scratchpad) の外の file を鳴らさない",
                "media_large": "音声・動画。 右パネルが鳴らすのは 25 MB 以下だけ"}
    for f in findings[:8]:
        kind = "link" if f["kind"] == "link" else "inline code"
        cands = " / ".join(_show(c, root) for c in f["candidates"])
        where = where_of[f["reason"]]
        if f["reason"] == "media_large":
            try:
                where += f"で、 これは {os.path.getsize(f['candidates'][0]) / 1048576:.1f} MB"
            except OSError:
                pass
        add = f" (足すフォルダ = {f['add_dir']})" if f.get("add_dir") else ""
        lines.append(f"- {BT}{f['path']}{BT} ({kind}、 {where}) → {cands}{add}")
    if media:
        lines.append(
            "🔊 音声・動画は link に書き直しても鳴りません。 聞いて・見てもらうなら、 相手がこの Mac の前にいれば "
            "afplay (短い切り出しを 1 本ずつ、 何の所かを先に告げる) か open (既定の再生アプリ) で流し、 "
            "流したことを短い追記で書いてください (最終メッセージ全体は出し直さない)。 右パネルで聞かせたいなら "
            "25 MB 以下の写しを scratchpad に置いて link する。 相手が別の端末にいるなら、 同期フォルダの中の場所を "
            "inline code にせず文で書く。 正本 = claude-config/conventions/claude-code-permissions.md#chat-panel-media-playback")
        if len(media) == len(findings):
            return "\n".join(lines)
    if outside:
        lines.append("🚫 " + OUTSIDE_FIX)
        if len(media) + len(outside) == len(findings):
            return "\n".join(lines)
    lines.append(
        "直し方: link の href は絶対 path か上のフォルダからの path に、 inline code は上のフォルダからの path に"
        "書き直した参照だけを短い追記として出してください (最終メッセージ全体は出し直さない = 返事が 2 通並ぶ。"
        " 候補が複数なら意図した方)。 "
        "フォルダの外の file は絶対 path でも右パネルで開けないことがあります — "
        "その場合は内容を本文に出すか open で開く。 "
        "開けない形を例として見せたいだけなら fenced code block に入れる。 "
        f"正本 = {DOC}"
    )
    return "\n".join(lines)


def hook_reason(transcript_path: str) -> str:
    """Stop hook 用: 開けない参照があれば reason 文、 無ければ空文字。"""
    import transcript_turns as tt

    entries = tt.load_entries(transcript_path)
    if session_entrypoint(entries) not in PANEL_ENTRYPOINTS:
        return ""
    final, _ = tt.current_turn_final(entries)
    root, cwds = session_root_and_cwds(entries)
    if not final or not root:
        return ""
    findings = find_broken(final, root, cwds, extra_roots=session_additional_dirs(entries))
    findings = drop_played(findings, tt.current_turn(entries))
    return build_reason(findings, os.path.normpath(root)) if findings else ""


def calibrate_files(days: float) -> list[str]:
    """calibrate が読む transcript (新しい順)。 この機械の全部の設定フォルダ (~/.claude と、 アカウント固定の ~/.claude-<名>。
    panel の entrypoint の session は ~/.claude の外にも在る = 実測。 列挙と重複の扱い = claude_config_dirs.py)。"""
    import glob
    import time

    try:
        import claude_config_dirs as ccd
        paths = ccd.transcript_paths()
    except Exception:
        paths = glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))
    cut = time.time() - days * 86400
    return sorted((f for f in paths if os.path.getmtime(f) >= cut), key=os.path.getmtime, reverse=True)


def calibrate(days: float, show: int = 40, context: bool = False) -> None:
    """過去の transcript の各 turn の最終発話に当て、 発火数と中身を出す (hook-authoring.md#text-pattern-stop-hook)。
    新しい session から順に show 件。 context=True で参照の前後の文も出す (目で仕分けるとき)。
    ⚠️ transcript は local の private data — 出力を公開の場所に貼らない。 file system は今の状態で判定する。"""
    from collections import Counter

    import transcript_turns as tt

    files = calibrate_files(days)
    n_turns = n_fire = n_link = shown = 0
    reasons: Counter = Counter()
    git_cache: dict = {}
    for f in files:
        entries = tt.load_entries(f)
        if session_entrypoint(entries) not in PANEL_ENTRYPOINTS:
            continue
        upto: list[dict] = []
        for turn in tt.turns(entries):
            upto.extend(turn)
            final, _ = tt.summarize(turn)
            if not final:
                continue
            n_turns += 1
            root, cwds = session_root_and_cwds(upto)
            fs = find_broken(final, root, cwds, extra_roots=session_additional_dirs(upto),
                             git_cache=git_cache) if root else []
            fs = drop_played(fs, turn)
            if not fs:
                continue
            n_fire += 1
            n_link += any(x["kind"] == "link" for x in fs)
            reasons.update(f"{x['kind']}/{x['reason']}" for x in fs)
            if shown < show:
                shown += 1
                print(os.path.basename(f)[:8], [(x["kind"], x["reason"], x["path"], len(x["candidates"])) for x in fs])
                if context:
                    for x in fs:
                        i = final.find(x["raw"])
                        print("    …" + final[max(0, i - 80):i + len(x["raw"]) + 50].replace("\n", " ⏎ ") + "…")
    print(f"transcripts={len(files)} turns={n_turns} fired={n_fire} (link を含む {n_link}) 内訳={dict(reasons)}")


if __name__ == "__main__":
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    if len(sys.argv) == 3 and sys.argv[1] == "hook":
        try:
            out = hook_reason(sys.argv[2])
        except Exception:
            out = ""  # fail-open
        if out:
            print(out)
    elif len(sys.argv) == 4 and sys.argv[1] == "place":
        try:
            print(panel_place_fast(sys.argv[2], sys.argv[3]))
        except Exception:
            print("")  # fail-open = 知らせは従来の文
    elif len(sys.argv) in (3, 4) and sys.argv[1] == "calibrate" and sys.argv[3:] in ([], ["--context"]):
        calibrate(float(sys.argv[2]), context=bool(sys.argv[3:]))
    else:
        print("usage: chat_file_refs.py hook <transcript.jsonl> | place <cwd> <transcript.jsonl> | calibrate <days> [--context]",
              file=sys.stderr)
        sys.exit(2)
