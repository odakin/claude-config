"""書き換えられた (force-push された) 履歴に手元の clone を **中身で** 揃え、 古い世代の commit / blob の push を止める共有部品。

使い手 = scripts/git-rewrite-follow.py (CLI: follow / sweep / guard / guard-head / audit / forbidden / facts /
ensure-prepush / status / map)、
scripts/repo-sync-sweep.sh (session 開始の同期 engine: diverged の repo にだけ呼ぶ)、
scripts/fleet-heartbeat.py (毎時の無人 commit+push: rebase の前に forced update を見る + 全 repo に pre-push stub を置き、
repo ごとの事実を点呼の材料として載せる)。
判定をここ 1 か所に置き、 呼び手が同じ述語で話す。 直接実行 = selftest (fixture: 書き換え 2 種 + manifest なしの書き換え +
通常の分岐 + guard + stub を通した本物の push + audit + 点呼)。

なぜ在るか (実測 2026-09-29): 履歴を書き換えた repo の追従 script が、 書き換えられる側の repo (個人層) の中に
在った。 その repo 自身を書き換えると、 古い履歴の Mac は追従 script を pull できず、 毎時の無人 job は
`pull --rebase` で古い commit を新しい履歴に積み直しうる (= 消した中身が push で remote に戻る)。 追従の判定を
**書き換えられない層 (本 repo) に** 置き、 repo 自身が運ぶ manifest (`.rewrite-follow/`) と tree の一致だけで
決めるようにした。 一般則 = conventions/multi-machine-state.md#history-rewrite-follow。

不変条件 (= この部品が守るもの):
  I1  ref を動かすのは「手元の committed content が upstream に在る」 と確かめた時だけ。 `git reset --keep`
      (未 commit の変更は保つ。 書き換えで変わった file に未 commit の変更が重なれば git が止める = そのまま止まる)。
  I2  `pull` / `merge` / `rebase` はしない。 揃えられない repo は 1 行で止まったと言う (exit 1)。
  I3  push 側: 対応表の旧 sha / 旧世代にしか無い blob を含む push を拒む (pre-push stub、 rebase で sha が変わっても
      blob で当たる)。
  I4  読むのは fetch 済みの remote-tracking ref (`<remote>/<branch>:<path>`) = worktree の pull 状態に依らない
      (conventions/hook-authoring.md#parallel-hooks-no-ordering)。
  I5  push の検査は、 知らせが届いているかに依らない (実測: 書き換えの知らせを別の経路で配ると、 届く前の clone は
      「する事が無い」 と区別がつかない)。 判定の材料は 2 つとも push の時点で手元に在る:
      (a) **remote の今の先頭** = git が pre-push に渡す remote 側の sha。 手元の remote-tracking ref と違う / 手元に
          無い object なら、 判定の前に fetch する (= 追従前の clone からの `push --force` も、 manifest を読んでから判定)。
      (b) **この clone 自身の記憶** = remote-tracking ref の reflog。 過去に remote に在って今はどの ref からも届かない
          commit (forced update で捨てられた履歴) と、 そこにしか無い tree・blob を、 manifest が無くても拒む
          (discarded_objects。 書き換えの直後で manifest がまだ置かれていない窓と、 manifest を置かない書き換えを覆う。
          reflog の entry は expire する = 定期 job が、 覚えているうちに object の一覧を clone の中に書き (repo_facts → stale_branches
          が discarded_objects を呼ぶ = 点呼の走査に畳む、 別の書き手を持たない)、
          expire の後は guard と audit がその記録を読む (remembered_discarded)。 manifest の無い repo の、 reflog より長い網)。
  I6  commit 側: HEAD が捨てられた履歴の commit の上にある clone では commit を始めさせない (head_violations。
      pre-commit の段が呼ぶ = 追従前の clone で仕事を積ませない)。
  I7  remote 側の検出: upstream (と remote の他の branch) に対応表の旧 sha / forbidden の object / この clone が記録した
      捨てられた履歴の commit が戻っていないかを読む (audit_repo。 manifest が無くても、 記録が在れば見る。 hook を持たない clone・host 上の merge から戻った分は、 ここでしか分からない)。
  I8  push 範囲の中身の検査 (書き換えに依らない。 content_violations): remote の中身についての不変条件は、 remote への
      入口で検査しないと網にならない (commit 時の検査は、 rebase・merge・cherry-pick で運ばれる commit を通らない)。
      (1) git-crypt の対象の path に平文の blob を push しない = 暗号化の対象を広げた .gitattributes が届く前の clone で
          commit された file を止める (判定は今の worktree の attr。 空の file は対象外)
      (2) commit message の識別子の検査 (commit-msg と同じ engine) を、 push 範囲の新しい commit にも当てる
          (識別子の一覧の在る machine でだけ。 1 回の push で新しい方から 50 commit まで)
  I9  追従を人にも session の開始にも頼らない: 無人の定期 job (fleet-heartbeat の --repos-follow) が、 全 repo を fetch して
      follow_repo を回す。 「書き換えた後、 各 machine で 1 回」 は、 session を開かない machine では誰も実行しない (実測)。
  I10 順序の検査: remote の既定 branch を fast-forward でなく動かす push (= 履歴の書き換えそのもの) の前に、 複製の側の備え
      (push の検査の stub・無人の追従) が全 machine に在るかを外の command に聞く (ready_gate。 command = env
      GIT_REWRITE_READY_HOOK か ~/.claude/rewrite-ready-check、 引数 = repo の path)。 exit 1 + 「NOT READY」 = 止める /
      exit 0 = 通す / それ以外 = 点呼が走らなかったと 1 行出して通す。 command が無ければ何もしない。 入口で聞くので、
      書き換えの道具にも手で打った push --force にも同じに効く (I5 までは「書き換えた後」 の網、 これは「書き換える前」 の網)。
      備えの無い複製が在るまま進めるのは持ち主の判断 = GIT_REWRITE_READY_OVERRIDE=1。

公開 repo には manifest を置かない: 対応表の旧 sha と forbidden の sha は、 host が旧 object を gc するまで、 消した中身を
sha で取り出す鍵になる (host は、 どの ref からも届かない commit も sha を知っていれば見せる)。 公開 repo の網は、 clone 自身の
reflog の記憶と、 それを書き留めた clone の中の記録 (I5 b)、 外から渡す対応表 (非公開の置き場。 `--map` / maps file / env) にする。

push の検査が止める object の集合から、 中身を持たない object (空の blob・改行 1 つの blob・空の tree = TRIVIAL_OBJECTS) は外す
(誰でも作れる = 「消した中身」 の印にならない。 記憶は期限なく残るので、 外さないと空 file を足す push が永久に止まる)。
止まった object が、 消した中身でなく同じ中身の新しい file だった時の出口 = その object を名指しする (env GIT_REWRITE_FOLLOW_ALLOW に
sha、 7 桁以上の前方一致)。 検査を丸ごと切らず、 名指しした object だけがその push で通り、 guard-allow として記録に残る
(定期 job が machine ごとの記録に載せる)。 止めた文面に、 止まった object の sha とこの出口を書く。

別の pre-push hook が在る clone (ensure_prepush / _prepush_plan): その hook を残したまま、 検査を先に通す。
  - pdf-publish の hook (templates/shared-project/pdf-publish) は、 自分の後に `pre-push.before-pdf-publish` を呼ぶ作り =
    その口に stub を置く (hook 自体は触らない。 hook の dir が track されていても置け、 clone の info/exclude に足す)
  - それ以外 (LFS・独自の hook) は、 元の hook を `pre-push.rewrite-follow-chained` に写してから stub に替える。 stub は検査が
    通った後に、 同じ引数と stdin で元の hook を呼び、 その終了値で push が決まる (検査が走らなかった時も元の hook は呼ぶ)
  - 自分の path ($0 など) から隣の file を引く hook は包まない (包むと hook の名前が変わる)。 以前の版が包んでしまったものは元に戻す
  - 包んだ stub が、 後から入った pdf-publish の installer に鎖の口へ移された時も、 stub は前の名前の退避を呼ぶ (次の回に口の名前へ付け替える)
  - 置けないのは、 hook の dir が repo に track されていて pre-push を持たない clone だけ (worktree に pre-push を書くと、
    repo が後で自分の pre-push を足した時に pull が止まる)。 包まない = env GIT_REWRITE_FOLLOW_CHAIN=0 /
    その clone で `git config rewritefollow.chain false`

追従の判定 (follow_repo):
  0. upstream が無い / detached / merge・rebase 進行中 → 触らない。 HEAD が upstream の祖先 (= behind か同じ) →
     無音 (通常の同期の仕事)。 upstream が HEAD の祖先 (= ahead だけ) → 無音 (push の仕事)。 それ以外 = diverged。
  1. **対応表** (旧 sha → 新 sha): upstream の `.rewrite-follow/commit-map*` (書き換えの後に通常 commit で置く) と、
     外から渡す glob (`--map`、 `~/.claude/rewrite-follow-maps.txt`、 env GIT_REWRITE_FOLLOW_MAPS)。 HEAD か、 HEAD から
     first-parent で MAP_WALK 個まで遡った祖先 A が表に在り、 A..HEAD の差分が全部 **volatile path** (upstream の
     `.rewrite-follow/ignore-paths`、 例 = 無人 job が書く status file) なら、 表を最後まで辿った新 sha が upstream の
     祖先である時に揃える。
  2. **tree の一致**: upstream の直近 MAX 個の commit に HEAD と同じ tree id が在れば揃える (対応表が無い書き換え、
     1 commit 1 回の rev-list で済む)。
  3. **volatile を除いた tree の一致**: ignore-paths が宣言されていれば、 その path を除いた署名で 2 と同じ比較
     (無人 job の commit が古い履歴の上に載っている Mac)。
  2 と 3 で探すのは、 HEAD と upstream の共通の祖先 **より後** の upstream の commit だけ (実測: 共通の祖先までの
  commit と tree が一致するのは、 手元の未 push の commit が古い状態へ戻しただけの時 = revert。 それを「upstream に
  同じ中身が在る」 と読むと、 書き換えの無い通常の分岐で未 push の revert を黙って捨てる)。 共通の祖先から HEAD までの
  差分が volatile path だけなら、 tree を探すまでもなく揃える (how = volatile-only)。
  4. どれも当たらない → 手元にしか無い commit に**書き換えの痕跡**があれば止まる (stopped = 「書き換えられた」。 中身を確かめてから
     人が揃える)。 痕跡 = その commit が forced-update で捨てられた upstream の先頭から届く (forced_update_trace) か、 対応表の旧 sha・
     forbidden の object を抱える (_local_rewrite_trace)。 痕跡が無ければ通常の分岐 (diverged = 呼び元の従来の扱い)。 forced-update の
     記録・対応表が「在る」 だけでは痕跡にしない (実測: 書き換えの後も残り続けるので、 その repo の通常の分岐を全部「書き換えられた」 と止めていた)。
  揃えた後、 旧 sha を持つ手元の他 branch を名指しする (消さない = push しないよう知らせるだけ)。

forced update の証拠 (heartbeat が rebase の前に見る): remote-tracking ref の reflog に `forced-update` の
entry が在るか (fetch がその場で書く。 unreachable になった entry は既定 30 日で expire = それより後の判定は
証拠を失う。 その窓は heartbeat の defer が beat を止め fleet の 🔴 で人に届く、 かつ I3 の pre-push が最後の網)。
「その repo で書き換えがあった」 (forced_update_seen) と「この clone の手元の commit が捨てられた世代のもの」 (forced_update_trace =
follow_repo の止まる理由) は別の問い。 前者は repo 単位の旗で、 後者は分岐した clone ごとに答える。

manifest (`<repo>/.rewrite-follow/`、 repo 自身が運ぶ。 読むのは upstream の版):
  ignore-paths      volatile な path (1 行 1 つ、 dir は末尾 `/`、 `#` 以降は注釈)。 書き換えの **前** に通常 commit で置く
  commit-map*       filter-repo が出す `old new` (先頭に `old new` の見出し行があってもよい)。 書き換えの **後** に置く
  forbidden-blobs*  旧世代にしか無い blob の sha1 (書き換えで消した平文の版)。 pre-push が push 範囲の object と突合する
                    (tree の sha も置ける = 消した file 名は tree に在る。 作り方 = forbidden_from_local / CLI forbidden)
manifest は reflog の記憶 (I5 b) が消えた後と、 旧履歴を見たことのない clone のための網。 書き換えの直後は manifest が
まだ無くても I5 が効くが、 置くまでが書き換えの 1 単位 (実測: 対応表だけを置き forbidden を置かなかった repo では、 消した
中身を新しい sha で運ぶ push 〔rebase・cherry-pick〕 が manifest の網を通った)。

古い branch の中身 (stale_branches / branch_unique): 捨てられた履歴を抱えた手元の branch は消さず、 名前と「その branch にしか
無い commit・blob の数」 を事実として載せる (0 / 0 = 古い履歴の写し。 消すかを決める材料を、 その machine を開かずに読む)。

点呼 (repo_facts / judge_fact): 各 machine は判定せず事実 (HEAD・見ている upstream) だけを載せ、 最新を fetch した machine が
判定する。 「追従した」 という報告を集めても、 報告の無い machine は「追従の必要が無い」 と区別がつかない (実測) = 分母
(全 machine × 書き換えた repo) を読む側が持つ。
"""
from __future__ import annotations

import glob as globmod
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

MANIFEST_DIR = ".rewrite-follow"
MAP_WALK = 64            # HEAD から first-parent で遡って対応表を探す上限 (= 無人 job の commit が積もる数の上限)
DEFAULT_MAX = 300        # tree 比較の探索幅 (rev-list --max-count)
FETCH_TIMEOUT = 20
STUB_MARK = "git-rewrite-follow pre-push stub"
MAPS_FILE_ENV = "GIT_REWRITE_FOLLOW_MAPS_FILE"
MAPS_ENV = "GIT_REWRITE_FOLLOW_MAPS"
LOG_ENV = "GIT_REWRITE_FOLLOW_LOG"
ZERO = "0" * 40
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


# ---------------------------------------------------------------- git helpers

def _env():
    e = dict(os.environ)
    e.setdefault("GIT_TERMINAL_PROMPT", "0")
    e.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=5")
    e["LC_ALL"] = "C"
    return e


def git(repo, *args, check=True, timeout=60, input=None):
    """stdout (str, rstrip)。 check=True で失敗なら RuntimeError (stderr の 1 行目)。"""
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=_env(),
                       timeout=timeout, input=input)
    if check and r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[0][:200] if (r.stderr or r.stdout).strip()
                           else f"git {' '.join(args)} failed rc={r.returncode}")
    return r.stdout.rstrip("\n")


def git_ok(repo, *args, timeout=60):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, env=_env(),
                          timeout=timeout).returncode == 0


def is_ancestor(repo, a, b):
    return git_ok(repo, "merge-base", "--is-ancestor", a, b)


def rev(repo, r):
    try:
        return git(repo, "rev-parse", "--verify", "-q", r + "^{commit}")
    except RuntimeError:
        return ""


def upstream_of(repo):
    """現在の branch の upstream (例 'origin/main')。 無ければ ''。 detached でも ''。"""
    try:
        if git(repo, "symbolic-ref", "-q", "HEAD", check=False) == "":
            return ""
        return git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    except RuntimeError:
        return ""


def in_progress(repo):
    gd = Path(git(repo, "rev-parse", "--git-dir"))
    if not gd.is_absolute():
        gd = Path(repo) / gd
    return any((gd / n).exists() for n in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD"))


def forced_update_seen(repo, upstream, n=30):
    """remote-tracking ref の reflog の直近 n entry に forced-update が在るか (fetch が書く)。"""
    if not upstream:
        return False
    out = git(repo, "reflog", "show", "--format=%gs", f"-n{n}", f"refs/remotes/{upstream}", check=False)
    return "forced-update" in out


def _forced_update_olds(repo, upstream, n=30):
    """remote-tracking ref の reflog の直近 n entry のうち forced-update の entry の「更新の前の値」 (= 捨てられた先頭) の list。
    None = forced-update は在るが前の値が分からない。 前の値は reflog の file の各行の第 1 欄 (git reflog show は後の値しか出さず、
    clone の直後は remote-tracking ref の reflog が無いので「1 つ前の entry」 では引けない = 実測)。 file が無い ref の保存形式
    (reftable) では git reflog show の 1 つ前の entry で代える。"""
    gd = git(repo, "rev-parse", "--git-common-dir", check=False)
    if gd:
        p = Path(gd) if Path(gd).is_absolute() else Path(repo) / gd
        lf = p / "logs" / "refs" / "remotes" / upstream
        if lf.is_file():
            try:
                lines = lf.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
            except OSError:
                return None
            olds = []
            for ln in lines:
                head_part, _, msg = ln.partition("\t")
                f = head_part.split(" ")
                if "forced-update" in msg and len(f) >= 2 and _SHA_RE.match(f[0]) and f[0] != ZERO:
                    olds.append(f[0])
            return olds
    out = git(repo, "reflog", "show", "--format=%H %gs", f"-n{n + 1}", f"refs/remotes/{upstream}", check=False)
    rows = [ln.split(" ", 1) for ln in out.splitlines() if ln.strip()]
    olds = []
    for i, row in enumerate(rows[:n]):
        if len(row) < 2 or "forced-update" not in row[1]:
            continue
        if i + 1 >= len(rows):
            return None
        olds.append(rows[i + 1][0])
    return olds


def forced_update_trace(repo, head, up_sha, upstream, n=30):
    """手元にしか無い commit (HEAD から届き upstream から届かない) が、 forced-update で捨てられた upstream の先頭から届くか。
    remote-tracking ref の reflog の直近 n entry の forced-update ごとに、 更新の前の値 (= 捨てられた先頭) を取り、
    `HEAD --not up` と `HEAD --not up <捨てられた先頭>` の数が違えば、 手元にしか無い commit の一部は捨てられた世代のもの = 書き換えの痕跡。
    forced-update の記録が在るだけでは痕跡にしない: 書き換えに追従した後の通常の分岐 (新しい世代の上の手元の commit + upstream の前進) は、
    reflog の直近に forced-update が残っている間ずっと「書き換えられた」 と止まっていた (実測 = 更新の少ない repo では数週間残る)。
    捨てられた先頭が分からない・object が引けない時は判定できない = 安全側 (痕跡あり)。"""
    if not upstream or not head or not up_sha:
        return False
    olds = _forced_update_olds(repo, upstream, n)
    if olds is None:
        return True
    if not olds:
        return False
    for o in olds:
        if not git_ok(repo, "cat-file", "-e", o + "^{commit}"):
            return True
    try:
        base = int(git(repo, "rev-list", "--count", head, "--not", up_sha) or "0")
        if base == 0:
            return False
        cut = int(git(repo, "rev-list", "--count", head, "--not", up_sha, *olds) or "0")
    except (RuntimeError, ValueError, subprocess.TimeoutExpired):
        return True
    return cut != base


# ---------------------------------------------------------------- manifest / maps

def upstream_manifest_files(repo, upstream):
    """upstream の .rewrite-follow/ の file 名 → 中身 (str)。 無ければ {}。"""
    if not upstream:
        return {}
    out = git(repo, "ls-tree", "--name-only", upstream, MANIFEST_DIR + "/", check=False)
    files = {}
    for p in out.splitlines():
        name = p.rsplit("/", 1)[-1]
        body = git(repo, "show", f"{upstream}:{p}", check=False)
        files[name] = body
    return files


def manifest_tree(repo, upstream):
    """upstream の .rewrite-follow/ の tree の sha ('' = manifest 無し)。 中身を読まずに「在るか」「変わったか」 を 1 回の
    git 呼び出しで答える (全 repo を回る sweep が、 manifest の無い repo で file を読みに行かないため)。"""
    if not upstream:
        return ""
    out = git(repo, "rev-parse", "--verify", "-q", f"{upstream}:{MANIFEST_DIR}", check=False).strip()
    return out if _SHA_RE.match(out) else ""


def parse_ignore_paths(text):
    out = []
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line.lstrip("/"))
    return out


def parse_map(text):
    """`old new` 行 → {old: new}。 見出し行と壊れた行は飛ばす。"""
    m = {}
    for line in (text or "").splitlines():
        a = line.split()
        if len(a) == 2 and _SHA_RE.match(a[0]) and _SHA_RE.match(a[1]):
            m[a[0]] = a[1]
    return m


def parse_shas(text):
    return {l.strip() for l in (text or "").splitlines() if _SHA_RE.match(l.strip())}


def extra_map_paths(cli_globs=()):
    """外から渡す対応表の file 一覧 (CLI glob + maps file + env)。 値は path。"""
    globs = list(cli_globs)
    mf = os.environ.get(MAPS_FILE_ENV) or os.path.join(os.path.expanduser("~"), ".claude", "rewrite-follow-maps.txt")
    try:
        with open(mf, encoding="utf-8") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if line:
                    globs.append(os.path.expanduser(line))
    except OSError:
        pass
    for g in (os.environ.get(MAPS_ENV) or "").split(":"):
        if g.strip():
            globs.append(os.path.expanduser(g.strip()))
    paths = []
    for g in globs:
        for p in sorted(globmod.glob(g)):
            if os.path.isfile(p) and p not in paths:
                paths.append(p)
    return paths


class Generation:
    """旧世代の知識 = 対応表の集合 + 旧世代にしか無い blob + volatile path。"""

    def __init__(self, maps, forbidden, ignore):
        self.maps = maps                 # list[dict old→new]
        self.forbidden = forbidden       # set[sha]
        self.ignore = ignore             # list[str]

    @property
    def old_shas(self):
        s = set()
        for m in self.maps:
            s.update(o for o, n in m.items() if o != n)
        return s

    def chase(self, sha):
        """表を最後まで辿る (chain)。 変わらなければ元の sha。"""
        cur = sha
        for _ in range(len(self.maps) + 1):
            nxt = None
            for m in self.maps:
                if cur in m and m[cur] != cur:
                    nxt = m[cur]
                    break
            if nxt is None:
                break
            cur = nxt
        return cur

    @staticmethod
    def load(repo, upstream, cli_globs=()):
        files = upstream_manifest_files(repo, upstream)
        maps, forb = [], set()
        for name in sorted(files):
            if name.startswith("commit-map"):
                m = parse_map(files[name])
                if m:
                    maps.append(m)
            elif name.startswith("forbidden-blobs"):
                forb |= parse_shas(files[name])
        ignore = parse_ignore_paths(files.get("ignore-paths", ""))
        for p in extra_map_paths(cli_globs):
            try:
                with open(p, encoding="utf-8") as f:
                    m = parse_map(f.read())
            except OSError:
                continue
            if m:
                maps.append(m)
            fb = p + ".forbidden-blobs"
            if os.path.isfile(fb):
                try:
                    with open(fb, encoding="utf-8") as f:
                        forb |= parse_shas(f.read())
                except OSError:
                    pass
        return Generation(maps, forb, ignore)


def lookup(repo, shas, upstream=None, cli_globs=()):
    """旧 sha → 今の sha を、 upstream の manifest (と外から渡す表) で引く。 記録 (掲示板・受信の記録・TODO) に残る
    書き換え前の sha を後から読むための道具 (CLI = git-rewrite-follow.py map)。 7 文字以上の短縮を受ける。
    返り値 = [(入力, 状態, 今の sha, 説明)]。 状態 = mapped (表で辿れた) / current (表に無く今の履歴に在る =
    書き換えで変わっていない sha) / ambiguous (短縮が表の複数に当たる) / dropped (書き換えで消えた commit) /
    unknown (表にも今の履歴にも無い = 別 repo の sha か、 表を置いていない書き換え)。"""
    upstream = upstream or upstream_of(repo)
    gen = Generation.load(repo, upstream, cli_globs)
    keys = set()
    for m in gen.maps:
        keys.update(m)
    rows = []
    for raw in shas:
        s = raw.strip().lower()
        hits = sorted(k for k in keys if k.startswith(s)) if re.fullmatch(r"[0-9a-f]{7,40}", s) else []
        if len(hits) > 1:
            rows.append((raw, "ambiguous", "", f"表の {len(hits)} 件に当たる = もっと長く渡す"))
            continue
        if hits and gen.chase(hits[0]) != hits[0]:
            new = gen.chase(hits[0])
            if new == ZERO:
                rows.append((raw, "dropped", "", "書き換えで消えた commit (中身が空になった等)"))
                continue
            subj = git(repo, "log", "-1", "--format=%s", new, check=False) if git_ok(repo, "cat-file", "-e", new + "^{commit}") else ""
            where = ("今の " + upstream + " に在る") if upstream and is_ancestor(repo, new, upstream) else \
                ("手元に在るが " + (upstream or "upstream") + " の外 (PR の ref・別 branch の commit など)" if subj else
                 "手元に無い (main 以外の ref の commit = fetch していない)")
            rows.append((raw, "mapped", new, f"{where}" + (f" / {subj[:80]}" if subj else "")))
            continue
        full = rev(repo, s) if re.fullmatch(r"[0-9a-f]{4,40}", s) else ""
        if full and upstream and is_ancestor(repo, full, upstream):
            rows.append((raw, "current", full, "書き換えで変わっていない (今の履歴の sha) / "
                         + git(repo, "log", "-1", "--format=%s", full, check=False)[:80]))
        elif hits:
            rows.append((raw, "current", hits[0], "表では自分 → 自分 (書き換えで変わっていない)"))
        else:
            rows.append((raw, "unknown", "", "表にも今の履歴にも無い (別 repo の sha / 表を置いていない書き換え / 短縮が短すぎる)"))
    return rows


# ---------------------------------------------------------------- tree signatures

def _under_ignore(path, ignore):
    for ig in ignore:
        if ig.endswith("/"):
            if path == ig[:-1] or path.startswith(ig):
                return True
        elif path == ig:
            return True
    return False


def _ignore_touches(prefix, ignore):
    """prefix (dir、 末尾 '/' 無し) の下に ignore の path が在るか (= 掘る必要があるか)。"""
    p = prefix + "/"
    return any(ig.startswith(p) for ig in ignore)


def tree_signature(repo, tree, ignore, prefix=""):
    """ignore を除いた tree の署名。 ignore の path に触れる dir だけ掘る (= 大きい tree でも git 呼び出しは深さ分)。"""
    if not ignore:
        return tree
    h = hashlib.sha1()
    for line in git(repo, "ls-tree", tree).splitlines():
        meta, name = line.split("\t", 1)
        mode, typ, sha = meta.split()
        path = prefix + name
        if _under_ignore(path, ignore) or (typ == "tree" and _under_ignore(path + "/", ignore)):
            continue
        if typ == "tree" and _ignore_touches(path, ignore):
            sha = tree_signature(repo, sha, ignore, path + "/")
        h.update(f"{mode} {typ} {sha}\t{path}\n".encode("utf-8", "surrogateescape"))
    return h.hexdigest()


def diff_only_ignored(repo, a, b, ignore):
    """a..b の差分の path が全部 ignore の下か (空の差分も True)。"""
    if not ignore:
        return False
    out = git(repo, "diff", "--name-only", a, b, check=False)
    return all(_under_ignore(p, ignore) for p in out.splitlines())


# ---------------------------------------------------------------- follow

class Result:
    """state: current / ahead / followed / stopped / diverged (通常の分岐 = 追従の対象外) / skipped。 line = 人向けの 1 行 (無音なら '')。"""

    def __init__(self, state, line="", how="", target="", exit_code=0, extra=()):
        self.state, self.line, self.how, self.target, self.exit_code = state, line, how, target, exit_code
        self.extra = list(extra)  # 追加の行 (旧 branch の名指し等)


def _find_target(repo, head, upstream, gen, max_count):
    """(target sha, how) か (None, None)。"""
    up_sha = rev(repo, upstream)
    # 1. 対応表 (HEAD か、 volatile だけの差で遡れる祖先)
    if gen.maps:
        walk = git(repo, "rev-list", "--first-parent", f"--max-count={MAP_WALK}", head).splitlines()
        for a in walk:
            new = gen.chase(a)
            if new == a:
                continue
            if a != head and not diff_only_ignored(repo, a, head, gen.ignore):
                break   # 遡った先に手元だけの中身がある = これ以上遡っても揃えられない
            if rev(repo, new) and is_ancestor(repo, new, up_sha):
                return new, ("map" if a == head else "map+volatile")
            break
    # 共通の祖先 (無ければ '' = 根から書き換えられた)。 ここまでは手元と upstream が同じ履歴 = ここから先だけが「相手にしか無い」
    mb = git(repo, "merge-base", head, up_sha, check=False).splitlines()
    mb = mb[0] if mb and _SHA_RE.match(mb[0]) else ""
    # 1.5 共通の祖先から HEAD までの差分が volatile path だけ = 手元にしか無い中身は無い (無人 job の commit だけ)
    if mb and gen.ignore and diff_only_ignored(repo, mb, head, gen.ignore):
        return up_sha, "volatile-only"
    # 2. tree の一致 / 3. volatile を除いた tree の一致。 探すのは共通の祖先より後の upstream の commit だけ
    #    (共通の祖先までの commit との一致は、 手元の未 push の commit が古い状態へ戻しただけ = 揃えると黙って捨てる)
    rl = ["rev-list", f"--max-count={max_count}", "--format=%H %T", up_sha] + (["^" + mb] if mb else [])
    lines = git(repo, *rl).splitlines()
    pairs = [l.split() for l in lines if not l.startswith("commit ")]
    head_tree = git(repo, "rev-parse", head + "^{tree}")
    for c, t in pairs:
        if t == head_tree:
            return c, "tree"
    if gen.ignore:
        want = tree_signature(repo, head_tree, gen.ignore)
        for c, t in pairs:
            if tree_signature(repo, t, gen.ignore) == want:
                return c, "tree-ignoring-volatile"
    return None, None


def _replay_hint(repo, head, upstream, gen):
    """止まった時に添える 1 文: 手元だけの commit を新しい履歴へ載せ直す command (分かる時だけ)。
    土台 A = HEAD の祖先のうち、 かつて remote に在った最後の commit (対応表の旧 sha か、 reflog から求めた fork point)。
    `rebase --onto <upstream> A` は A より後の commit だけを運ぶ = 古い履歴は合流しない (`rebase <upstream>` と違う)。"""
    try:
        base = ""
        for a in git(repo, "rev-list", "--first-parent", f"--max-count={MAP_WALK}", head).splitlines()[1:]:
            new = gen.chase(a)
            if new != a and rev(repo, new) and is_ancestor(repo, new, upstream):
                base = a
                break
        if not base:
            fp = git(repo, "merge-base", "--fork-point", "refs/remotes/" + upstream, head, check=False).strip()
            if _SHA_RE.match(fp) and fp != head and not is_ancestor(repo, fp, upstream):
                base = fp
        if not base:
            return ""
        n = git(repo, "rev-list", "--count", f"{base}..{head}", check=False).strip() or "?"
        return (f"。 手元だけの commit は {n} 個 ({base[:7]} より後)。 中身に消したものが無ければ、 それだけを載せ直す:"
                f" git -C {repo} rebase --onto {upstream} {base[:12]}")
    except (RuntimeError, subprocess.TimeoutExpired, OSError):
        return ""


def old_branches(repo, gen, upstream, current_branch):
    """upstream に無い commit のうち旧 sha を持つ手元 branch の名前 (current は除く)。"""
    olds = gen.old_shas
    if not olds:
        return []
    names = []
    for b in git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/", check=False).splitlines():
        if not b or b == current_branch:
            continue
        shas = set(git(repo, "rev-list", b, "--not", upstream, check=False).split())
        if shas & olds:
            names.append(b)
    return names


def crypt_key_mismatch(repo, target, head=None, limit=3):
    """この clone が git-crypt の鍵で unlock 済みなのに、 target の tree の暗号化 blob をその鍵で復号できなければ、 その path を返す
    (無ければ None)。 鍵を付け替えた repo の古い clone が追従すると、 smudge が失敗して作業 tree の file が消えたまま止まる (実測 =
    reset --keep が rc 128 で HEAD は動かず、 変わった暗号化 file が削除された状態で残る)。 だから reset の前に、 head と違う暗号化
    blob を limit 個まで試しに復号する。 lock 中 (鍵が無い) の clone は filter が無いので暗号文のまま揃う = 検査しない。"""
    try:
        key = git(repo, "rev-parse", "--git-path", "git-crypt/keys/default")
    except RuntimeError:
        return None
    key_path = Path(key) if os.path.isabs(key) else Path(repo) / key
    if not key_path.is_file() or not shutil.which("git-crypt") or not _crypt_declared(repo):
        return None
    if git(repo, "config", "--get", "filter.git-crypt.smudge", check=False) == "":
        return None
    try:
        if head:
            names = git(repo, "diff", "--name-only", "-z", head, target).split("\0")
        else:
            names = git(repo, "ls-tree", "-r", "--name-only", "-z", target).split("\0")
    except RuntimeError:
        return None
    tried = 0
    for path in (n for n in names if n):
        try:
            blob = git(repo, "rev-parse", f"{target}:{path}")
        except RuntimeError:
            continue
        data = subprocess.run(["git", "-C", str(repo), "cat-file", "-p", blob], capture_output=True, env=_env()).stdout
        if not data.startswith(CRYPT_MAGIC):
            continue
        r = subprocess.run(["git-crypt", "smudge"], cwd=str(repo), input=data, capture_output=True, env=_env())
        if r.returncode != 0:
            return path
        tried += 1
        if tried >= limit:
            break
    return None


def _age_text(sec):
    h = max(0, int(sec)) // 3600
    return f"{h} 時間前" if h < 48 else f"{h // 24} 日前"


def divergence_summary(repo, head, up_sha):
    """分岐した clone の 1 行の材料: 「手元にしか無い commit N (最古 X 前)・upstream にだけ在る commit M」。 読めなければ空に近い文。"""
    try:
        times = [int(t) for t in git(repo, "log", "--format=%ct", f"{up_sha}..{head}").split()]
        m = int(git(repo, "rev-list", "--count", f"{head}..{up_sha}") or "0")
    except (RuntimeError, ValueError, subprocess.TimeoutExpired):
        return "手元にしか無い commit と upstream の commit の数は読めなかった"
    oldest = f" (最古 {_age_text(time.time() - min(times))})" if times else ""
    return f"手元にしか無い commit {len(times)}{oldest}・upstream にだけ在る commit {m}"


def _local_rewrite_trace(repo, head, up_sha, gen):
    """手元にしか無い commit (HEAD から届き upstream から届かない) が、 書き換えで捨てた世代の commit か消した版の blob を
    抱えているか。 対応表を運ぶ repo でも、 新しい世代の上の通常の分岐 (手元の commit + upstream の前進) は痕跡にしない
    (2026-10-26 実測: email-office は 9/29 の書き換えの対応表を持ち続けるので、 対応表が在るだけで痕跡と見ると、
    受付当番の未 push の commit 3 つと upstream の前進が「書き換えられた」 と報告され、 人が揃えるまで止まった)。"""
    if not (gen.old_shas or gen.forbidden):
        return False
    ids = _range_ids(repo, head, [up_sha], objects=bool(gen.forbidden), timeout=60) - TRIVIAL_OBJECTS
    return bool(ids & (gen.old_shas | gen.forbidden))


def follow_repo(repo, cli_globs=(), fetch=True, max_count=DEFAULT_MAX, dry_run=False, log=True):
    repo = Path(repo)
    name = repo.name
    if not (repo / ".git").exists():
        return Result("skipped", "", exit_code=0)
    upstream = upstream_of(repo)
    if not upstream:
        return Result("skipped", "", exit_code=0)
    if fetch:
        remote = upstream.split("/", 1)[0]
        try:
            git(repo, "fetch", "-q", remote, timeout=FETCH_TIMEOUT)
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            return Result("stopped", f"{name}: fetch に失敗 (通信) = 今回は止まる、 次に再試行: {str(exc)[:120]}", exit_code=1)
    if in_progress(repo):
        return Result("stopped", f"{name}: merge / rebase が進行中 = 触らない (片付けてから)", exit_code=1)
    head = rev(repo, "HEAD")
    up_sha = rev(repo, upstream)
    if not head or not up_sha:
        return Result("skipped", "", exit_code=0)
    if is_ancestor(repo, head, up_sha):
        return Result("current")
    if is_ancestor(repo, up_sha, head):
        return Result("ahead")
    gen = Generation.load(repo, upstream, cli_globs)
    target, how = _find_target(repo, head, upstream, gen, max_count)
    # 書き換えの痕跡 = 手元にしか無い commit が、 forced-update で捨てられた upstream の先頭から届く / 対応表の旧世代・消した blob を抱える
    # (forced-update の記録や対応表が在るだけでは痕跡にしない = 書き換えの後の通常の分岐を「書き換え」 と言わない)
    trace = forced_update_trace(repo, head, up_sha, upstream) or _local_rewrite_trace(repo, head, up_sha, gen)
    if not target:
        if trace:
            # 書き換えの痕跡がある = 揃えられない理由は手元だけの中身
            hint = _replay_hint(repo, head, upstream, gen)
            return Result("stopped",
                          f"{name}: upstream ({upstream}) は書き換えられ、 手元の HEAD ({head[:7]}) と同じ中身の commit が新しい履歴に無い"
                          f" = 手元にしか無い commit がある。 中身を確かめてから人が揃える (git pull / merge / rebase {upstream} はしない"
                          f" = 古い履歴が合流して消した中身が push で戻る)" + hint, exit_code=1)
        # 痕跡が無い = 通常の分岐 (手元の commit + upstream の前進)。 追従の仕事ではない = 呼び元の従来の扱いに返す。
        # 数と古さを添える: 手元にだけ在る commit が何時間も残っているなら、 誰かが手元に閉じ込めた (無人の書き手の push の失敗など)
        return Result("diverged", f"{name}: upstream ({upstream}) と分岐 (diverged、 書き換えの痕跡は無い = 通常の分岐): "
                                  + divergence_summary(repo, head, up_sha)
                                  + " → 手元の branch を退避し、 upstream に無い分を載せ直してから reset --keep で揃える"
                                  " (conventions/multi-session-coordination.md#ordinary-divergence-replay)", exit_code=1)
    branch = git(repo, "symbolic-ref", "--short", "-q", "HEAD", check=False)
    if dry_run:
        return Result("followed", f"{name}: [dry-run] 揃える: HEAD {head[:7]} → 新履歴の {target[:7]} ({how}) → {upstream} {up_sha[:7]}",
                      how=how, target=target)
    bad = crypt_key_mismatch(repo, up_sha, head)
    if bad:
        return Result("stopped",
                      f"{name}: 新しい履歴の暗号化 file ({bad}) をこの clone の git-crypt の鍵で復号できない (鍵が付け替えられた)"
                      f" = 追従すると作業 tree の file が消えたまま止まるので触らない。 新しい鍵を置いてから:"
                      f" git-crypt lock → 追従をやり直す → git-crypt unlock <新しい鍵> (docs/git-crypt-guide.ja.md#rotate-key)", exit_code=1)
    if not git_ok(repo, "reset", "-q", "--keep", up_sha):
        return Result("stopped", f"{name}: reset --keep が止まった (未 commit の変更が書き換えで変わった file に重なる) = 手で揃える"
                                 f" (git status で file を見て、 退避してから再実行)", exit_code=1)
    if how == "volatile-only" and not trace:
        # 書き換えではない: 手元にだけ在った commit は無人 job の書く path の差分だけ → upstream に揃えた、 と事実のとおりに言う
        line = (f"{name}: 手元にだけ在った commit は volatile な path の差分だけ = upstream に揃えた"
                f" (手元の HEAD {head[:7]} → {branch or 'HEAD'} = {up_sha[:7]})")
    else:
        line = (f"{name}: 書き換えられた履歴に追従した (手元の HEAD {head[:7]} → 新履歴の {target[:7]} 〔{how}〕、"
                f" {branch or 'HEAD'} = {up_sha[:7]})")
    res = Result("followed", line, how=how, target=target)
    olds = old_branches(repo, gen, upstream, branch)
    if olds:
        res.extra.append(f"  ⚠️ {name}: 古い履歴の commit を持つ手元 branch = {' '.join(olds)} (push しない。 要らなければ人が消す)")
    if log:
        _log(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} followed {repo} {head} -> {up_sha} via {how}")
    return res


def _log(line):
    p = os.environ.get(LOG_ENV) or os.path.join(os.path.expanduser("~"), ".claude", "state", "rewrite-follow.log")
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


EVENT_KINDS = ("guard-error", "ready-skip", "ready-override", "guard-allow")
# 中身を持たない object (空の blob・改行 1 つの blob・空の tree)。 誰でも作れるので「消した中身」 の印にならない = 検査の集合から外す
# (外さないと、 旧履歴にしか無かった空 file のせいで、 後で空 file を足す push が止まる。 記憶は期限なく残るので、 永久に)
TRIVIAL_OBJECTS = frozenset({
    "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391",
    "8b137891791fe96927ad78e64b0aad7bded08bdc",
    "4b825dc642cb6eb9a060e54bf8d69288fbee4904",
})
ALLOW_ENV = "GIT_REWRITE_FOLLOW_ALLOW"   # 止まった object の sha (7 桁以上の前方一致、 空白か , 区切り) を、 その push に限って通す


def _allowed(ids):
    """ALLOW_ENV に書かれた sha に当たる ids の部分集合 (消した中身を戻すのでなく、 同じ中身の file を新しく足した push の出口。
    object を名指しする = 検査を丸ごと切らない。 通した分は guard-allow として記録に残る)。"""
    pats = [x for x in re.split(r"[\s,]+", os.environ.get(ALLOW_ENV, "").strip().lower()) if re.fullmatch(r"[0-9a-f]{7,40}", x)]
    return {i for i in ids if any(i.startswith(q) for q in pats)} if pats else set()


def log_event(kind, repo, detail=""):
    """検査が走らなかった・点呼を飛ばした、 を追従の記録 (LOG_ENV の file) に 1 行残す。 止めずに通した出来事は、 その場の 1 行を
    誰も読まなければ無かったことになる = 無人の定期 job が recent_events で拾い、 machine ごとの記録に載せて他の machine から読む。
      guard-error     push の検査が例外で走らなかった (stub は通した)
      ready-skip      履歴を書き換える push の前の点呼が走らなかった (通した)
      ready-override  備えの無い複製が在るまま、 履歴を書き換える push を通した (GIT_REWRITE_READY_OVERRIDE=1)
      guard-allow     止まるはずの object を、 名指し (GIT_REWRITE_FOLLOW_ALLOW) で通した"""
    _log(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {kind} {Path(str(repo)).name} {detail}".rstrip())


def recent_events(hours=24):
    """記録の直近 hours 時間の log_event を {kind: [repo 名 (出た順、 重複なし)]} で返す (該当なしは {})。"""
    p = os.environ.get(LOG_ENV) or os.path.join(os.path.expanduser("~"), ".claude", "state", "rewrite-follow.log")
    since = time.time() - hours * 3600
    out = {}
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                a = line.split()
                if len(a) < 3 or a[1] not in EVENT_KINDS:
                    continue
                try:
                    ts = time.mktime(time.strptime(a[0], "%Y-%m-%dT%H:%M:%S"))
                except ValueError:
                    continue
                if ts >= since and a[2] not in out.setdefault(a[1], []):
                    out[a[1]].append(a[2])
    except OSError:
        return {}
    return out


STUB_ALL_ENV = "GIT_REWRITE_FOLLOW_STUB_ALL"   # "1" = sweep が manifest の無い repo にも stub を置く (既定は manifest のある repo だけ)


def ensure_prepush_all(root):
    """root/*/ の upstream のある全 repo に pre-push stub を置く / 更新する (書き換えの **前から** 全 clone に在る状態にする)。
    別の pre-push hook が在る clone では、 その hook を残したまま検査を先に通す (ensure_prepush)。 置けないのは、 hook の dir が
    repo に track されている clone だけ。 (置いた・更新した repo 名の list, 置けなかった行の list)。
    無人の定期 job が毎回呼ぶ = session を開かない machine にも届く。"""
    placed, failed = [], []
    for gd in sorted(globmod.glob(os.path.join(str(root), "*", ".git"))):
        repo = Path(gd).parent
        try:
            if ensure_prepush(repo, only_with_manifest=False, quiet_foreign=True):
                placed.append(repo.name)
        except Exception as exc:  # 1 つの repo の失敗で、 残りの repo を止めない
            failed.append(f"{repo.name}: pre-push stub を置けなかった ({type(exc).__name__}: {str(exc)[:100]})")
    return placed, failed


def sweep(root, cli_globs=(), fetch=False, max_count=DEFAULT_MAX, dry_run=False, prepush=True, audit=True, stub_all=None):
    """root/*/ の repo を順に。 (Result, prepush line) の list。
    - pre-push stub は manifest のある repo に置く。 stub_all=True (か env GIT_REWRITE_FOLLOW_STUB_ALL=1) なら upstream のある
      全 repo に置き、 manifest の無い repo の分は 1 件ずつ言わず末尾の 1 行にまとめる (初回は repo の数だけ出るため)。
    - manifest のある repo は remote 側も読む (audit_repo): 消した世代が戻っていれば stopped の行として返す。"""
    out = []
    if stub_all is None:
        stub_all = os.environ.get(STUB_ALL_ENV, "0") == "1"
    quiet = []
    for gd in sorted(globmod.glob(os.path.join(str(root), "*", ".git"))):
        repo = Path(gd).parent
        try:
            r = follow_repo(repo, cli_globs, fetch=fetch, max_count=max_count, dry_run=dry_run)
        except (RuntimeError, subprocess.TimeoutExpired, OSError) as exc:
            r = Result("stopped", f"{repo.name}: 追従の判定で失敗 ({type(exc).__name__}: {str(exc)[:120]})", exit_code=1)
        pl = ""
        has_manifest = False
        if r.state != "skipped":
            try:
                has_manifest = bool(manifest_tree(repo, upstream_of(repo)))
            except (RuntimeError, subprocess.TimeoutExpired, OSError):
                has_manifest = False
        if prepush and r.state != "skipped" and not dry_run:
            try:
                if has_manifest:
                    pl = ensure_prepush(repo, only_with_manifest=True)
                elif stub_all:
                    if ensure_prepush(repo, only_with_manifest=False, quiet_foreign=True):
                        quiet.append(repo.name)
            except (RuntimeError, OSError) as exc:
                pl = f"{repo.name}: pre-push stub を置けなかった ({str(exc)[:100]})"
        out.append((r, pl))
        if audit and (has_manifest or (_common_dir(repo) / REMOVED_CACHE).is_dir()):
            try:
                for line in audit_repo(repo, cli_globs):
                    out.append((Result("stopped", line, exit_code=1), ""))
            except (RuntimeError, subprocess.TimeoutExpired, OSError):
                pass
    if quiet:
        eg = "、 ".join(quiet[:3]) + (" ほか" if len(quiet) > 3 else "")
        out.append((Result("skipped"), f"古い世代の push を止める pre-push stub を {len(quiet)} repo に置いた / 更新した"
                                        f" (書き換えの前から全 clone に置く。 {eg})"))
    return out


# ---------------------------------------------------------------- discarded history (この clone 自身の記憶)

REMOVED_CACHE = "rewrite-follow-discarded"    # <git common dir>/ の下。 捨てられた履歴にしか無い object の一覧の cache
REMOVED_CACHE_KEEP = 8       # 世代の数。 file は reflog の entry が expire した後も残り、 remembered_discarded が記憶として読む
AUDIT_CACHE = "rewrite-follow-audit.json"     # <git common dir>/ の下。 audit_repo が最後に見た ref の状態と結果
GUARD_HEADLINE = "push を止めた"               # pre-push stub がこの見出しで「違反」 と「検査の故障」 を見分ける
HEAD_HEADLINE = "[rewrite-follow] BLOCK"      # pre-commit の段が同じ用途で見る


def _common_dir(repo):
    gd = Path(git(repo, "rev-parse", "--git-common-dir"))
    return gd if gd.is_absolute() else Path(repo) / gd


def _has(repo, sha, typ="commit"):
    return bool(sha) and git_ok(repo, "cat-file", "-e", f"{sha}^{{{typ}}}")


def _existing_commits(repo, shas):
    """shas のうち、 手元に commit として在るもの (gc 済み・別の型は落とす)。"""
    shas = sorted(shas)
    if not shas:
        return []
    out = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch-check=%(objectname) %(objecttype)"],
                         input="\n".join(shas) + "\n", capture_output=True, text=True, env=_env(), timeout=120).stdout
    return [l.split()[0] for l in out.splitlines() if l.endswith(" commit")]


def tracked_refs(repo, remote):
    """「remote の履歴」 として記憶を引く remote-tracking ref (full name)。 remote の既定 branch (`<remote>/HEAD` の指す先、
    無ければ main / master のうち在るもの、 それも無ければ今の branch の upstream)。 既定 branch だけを見るのは、
    作業 branch の rebase + force-push (普通の運用) を「捨てられた履歴」 と読まないため。"""
    refs = []

    def add(r):
        if r and r not in refs and rev(repo, r):
            refs.append(r)

    add(git(repo, "symbolic-ref", "-q", f"refs/remotes/{remote}/HEAD", check=False).strip())
    if not refs:
        for b in ("main", "master"):
            add(f"refs/remotes/{remote}/{b}")
    if not refs:
        up = upstream_of(repo)
        if up and up.split("/", 1)[0] == remote:
            add("refs/remotes/" + up)
    return refs


def _reflog_values(repo, ref):
    """ref がこれまでに指した sha の集合。 reflog の各行の **前の値と後の値の両方** を読む (実測: clone は remote-tracking ref
    の最初の値を entry として残さない = 最初の forced update の「前の値」 は、 その entry の前の値の欄にしか無い)。
    reflog の file を直接読み、 無ければ (別の ref 保存形式) `git reflog show` の後の値だけで代える。"""
    vals = set()
    try:
        with open(_common_dir(repo) / "logs" / ref, encoding="utf-8", errors="replace") as f:
            for line in f:
                a = line.split(" ", 2)
                if len(a) >= 2:
                    vals.update(s for s in a[:2] if _SHA_RE.match(s) and s != ZERO)
        return vals
    except OSError:
        out = git(repo, "reflog", "show", "--format=%H", ref, check=False)
        return {l for l in out.splitlines() if _SHA_RE.match(l)}


def discarded_commits(repo, refs):
    """refs の reflog に残る過去の値から届き、 今の refs からは届かない commit (= forced update で remote から捨てられた履歴)。
    (commit の list, 今の値の list)。 forced update が無ければ ([], 今の値)。 gc 済みの entry は飛ばす。"""
    cur = [c for c in (rev(repo, r) for r in refs) if c]
    seen = set()
    for r in refs:
        seen.update(_reflog_values(repo, r))
    seen -= set(cur)
    if not seen or not cur:
        return [], cur
    have = _existing_commits(repo, seen)
    if not have:
        return [], cur
    out = git(repo, "rev-list", "--stdin", input="\n".join(have + ["^" + c for c in cur]) + "\n", check=False, timeout=120)
    return [l for l in out.splitlines() if _SHA_RE.match(l)], cur


def _all_objects(repo, tips, timeout=900):
    """tips (commit の sha の list) から届く全 object (commit・tree・blob) の sha の set。 否定の rev を渡さない全 walk。"""
    if not tips:
        return set()
    out = git(repo, "rev-list", "--objects", "--stdin", input="\n".join(tips) + "\n", check=False, timeout=timeout)
    return {l.split(" ", 1)[0] for l in out.splitlines() if l and _SHA_RE.match(l.split(" ", 1)[0])}


def _objects_only_in(repo, old_tips, new_tips):
    """old_tips から届き、 new_tips からは **どの commit を通っても** 届かない object の set (厳密な差集合)。
    `rev-list --objects OLD ^NEW` で済ませない: 否定側の tree / blob は境界の commit の分しか除かれないので、 新しい履歴の
    途中の版にだけ在る object (後で変わった・消えた file の版) が「旧にしか無い」 側に混ざる (実測: この形で作った一覧の
    3〜8 割が今の履歴にも在る object で、 file を以前の版に戻す正当な push を止め、 remote 側の検出が偽の「戻っている」 を
    出した)。 2 回の全 walk の差を取る。"""
    return _all_objects(repo, old_tips) - _all_objects(repo, new_tips)


def _clean_remote_tips(repo, remote, removed_commits, base):
    """「今の履歴」 として数える commit の list = base (既定 branch の今の値) + remote の他の branch のうち、 removed_commits
    (捨てられた / 旧世代の commit) を 1 つも抱えていないもの。 旧履歴を抱えたままの branch を今の履歴に数えると、
    消した object が「今も在る」 ことになって網から外れる。"""
    tips = list(base)
    out = git(repo, "for-each-ref", "--format=%(objectname) %(objecttype) %(symref)", f"refs/remotes/{remote}/", check=False)
    for line in out.splitlines():
        a = line.split()
        if len(a) != 2 or a[1] != "commit" or a[0] in tips:      # symref (<remote>/HEAD) は 3 欄
            continue
        if not (_range_ids(repo, a[0], base, objects=False, timeout=120) & removed_commits):
            tips.append(a[0])
    return tips


def discarded_objects(repo, refs):
    """(捨てられた履歴の commit の set, そこにしか無い object 〔commit・tree・blob〕 の sha の set)。 object の一覧は、 捨てられた
    commit の集合を鍵に cache する (集合が変わらない間は walk し直さない。 今の履歴が進んでも「捨てられた履歴にしか無い」
    は変わらない)。 **sha だけを持つ** (path は持たない・出さない = 消した file 名そのものが消した中身のことがある。
    実測: 止めた理由に path を添えたら、 識別子の入った旧 file 名が端末と log に出た)。"""
    commits, cur = discarded_commits(repo, refs)
    if not commits:
        return set(), set()
    key = hashlib.sha1("\n".join(sorted(commits)).encode()).hexdigest()
    cdir = _common_dir(repo) / REMOVED_CACHE
    cf = cdir / key
    objs = set()
    try:
        with open(cf, encoding="ascii", errors="replace") as f:
            for line in f:
                sha = line.split(None, 1)[0] if line.strip() else ""   # 行頭の sha だけを読む (後ろに何か付いた行でも落とさない)
                if _SHA_RE.match(sha):
                    objs.add(sha)
    except OSError:
        remote = refs[0][len("refs/remotes/"):].split("/", 1)[0] if refs and refs[0].startswith("refs/remotes/") else ""
        objs = _objects_only_in(repo, commits, _clean_remote_tips(repo, remote, set(commits), cur) if remote else cur)
        try:
            cdir.mkdir(parents=True, exist_ok=True)
            tmp = cdir / (key + ".tmp")
            with open(tmp, "w", encoding="ascii") as f:
                f.write("".join(s + "\n" for s in sorted(objs)))
            os.replace(tmp, cf)
            old = sorted((p for p in cdir.iterdir() if p.name != key and not p.name.endswith(".tmp")),
                         key=lambda p: p.stat().st_mtime, reverse=True)
            for p in old[REMOVED_CACHE_KEEP - 1:]:
                p.unlink()
        except OSError:
            pass
    return set(commits), objs


def remembered_discarded(repo):
    """この clone が以前に「remote から捨てられた履歴にしか無い」 と記録した object の sha の set (cache の file 全部の和)。
    reflog の entry は expire する (unreachable は既定 30 日) が、 この file は残る = manifest の無い repo の、 reflog より長い記憶
    (公開 repo には manifest を置かないので、 そこではこれが唯一の長い網)。 捨てられた object が remote に正当に戻された後は、
    push の範囲 (remote に既に在る分を除く) に入らないので、 この記憶で止まることは無い。"""
    out = set()
    cdir = _common_dir(repo) / REMOVED_CACHE
    try:
        files = [q for q in cdir.iterdir() if q.is_file() and not q.name.endswith(".tmp")]
    except OSError:
        return out
    for q in files:
        try:
            with open(q, encoding="ascii", errors="replace") as f:
                for line in f:
                    sha = line.split(None, 1)[0] if line.strip() else ""
                    if _SHA_RE.match(sha):
                        out.add(sha)
        except OSError:
            continue
    return out - TRIVIAL_OBJECTS


# ---------------------------------------------------------------- push guard

def _range_ids(repo, positive, negative, objects=True, timeout=600):
    """positive (sha) から届き negative (sha の list) から届かないものの sha の set。 objects=True なら commit・tree・blob、
    False なら commit だけ。 path は読み捨てる (discarded_objects の注記)。"""
    args = ["rev-list"] + (["--objects"] if objects else []) + [positive]
    if negative:
        args += ["--not"] + list(negative)
    out = git(repo, *args, check=False, timeout=timeout)
    return {l.split(" ", 1)[0] for l in out.splitlines() if l}


def _range_objects(repo, positive, negative, timeout=600):
    """positive から届き negative から届かない object の [(sha, path)] (commit は path ''。 path は中身の検査が file を
    名指しするためだけに使い、 「捨てられた履歴」 の側には渡さない)。"""
    args = ["rev-list", "--objects", positive]
    if negative:
        args += ["--not"] + list(negative)
    out = []
    for line in git(repo, *args, check=False, timeout=timeout).splitlines():
        sha, _, path = line.partition(" ")
        if sha:
            out.append((sha, path))
    return out


def push_violations(repo, local_sha, exclude, gen, discarded=None, ids=None, remembered=None):
    """local_sha までの commit のうち exclude に無いものが、 旧 sha / 旧世代の blob / 捨てられた履歴の object を含むか。
    違反の説明 list。 exclude = sha か sha の list ('' / [] = remote のどの ref にも無いもの全部)。
    discarded = discarded_objects の返り値 (無ければ manifest だけで判定)。 ids = 呼び手が既に求めた範囲の sha の set。"""
    if isinstance(exclude, str):
        exclude = [exclude] if exclude else []
    if ids is None:
        ids = _range_ids(repo, local_sha, exclude or ["--remotes"])
    ids = set(ids) - TRIVIAL_OBJECTS
    hits = []
    olds = ids & gen.old_shas
    if olds:
        hits.append(f"書き換え前の世代の commit {len(olds)} 個 (例 {sorted(olds)[0][:7]})")
    fb = ids & gen.forbidden
    if fb:
        hits.append(f"書き換えで消した版の blob {len(fb)} 個 (例 {sorted(fb)[0][:7]})")
    if discarded and discarded[0]:
        dcommits, dobjs = discarded
        dc = (ids & dcommits) - olds
        if dc:
            hits.append(f"remote から捨てられた履歴の commit {len(dc)} 個 (この clone の fetch の記録から、 例 {sorted(dc)[0][:7]})")
        do = (ids & dobjs) - dcommits - fb
        if do:
            # path は出さない (消した file 名そのものが消した中身のことがある)。 どの file かは手元で: git rev-list --objects <local> | grep <sha>
            hits.append(f"捨てられた履歴にしか無い tree / blob {len(do)} 個 (例 {sorted(do)[0][:7]})")
    if remembered:
        seen = set(discarded[0]) | set(discarded[1]) if discarded else set()
        rm = (ids & remembered) - gen.old_shas - gen.forbidden - seen
        if rm:
            hits.append(f"この clone が以前に「remote から捨てられた履歴にしか無い」 と記録した object {len(rm)} 個 (例 {sorted(rm)[0][:7]})")
    return hits


def _remote_moved(repo, remote, rows):
    """push の行 (lref lsha rref rsha) から見て、 remote の今の状態が手元の知識と違うか。 新しい ref の push (rsha = 0) は
    比べる相手が無い = 既定 branch の知識が今かどうか分からないので、 違うものとして扱う (fetch してから判定)。"""
    for _lref, _lsha, rref, rsha in rows:
        if rsha == ZERO or not _has(repo, rsha):
            return True
        if rref.startswith("refs/heads/"):
            tr = rev(repo, f"refs/remotes/{remote}/{rref[len('refs/heads/'):]}")
            if tr and tr != rsha:
                return True
    return False


# ---------------------------------------------------------------- 履歴を書き換える push の前の点呼 (順序の検査)
#
# 「正本を先に変え、 追従を後から配る」 の順序を、 正本が変わる瞬間 (既定 branch を fast-forward でなく動かす push) に検査する。
# 複製の側の備え (push の検査の stub・無人の追従) が全 machine に在るかは、 この engine には分からない (fleet の記録は呼ぶ側の層が
# 持つ) = 外の command に聞く。 入口で聞くので道具に依らない (書き換えの道具でも、 手で打った push --force でも、 同じ所を通る)。

READY_HOOK_ENV = "GIT_REWRITE_READY_HOOK"          # 点呼の command の path。 "0" = 呼ばない。 既定 = ~/.claude/rewrite-ready-check
READY_OVERRIDE_ENV = "GIT_REWRITE_READY_OVERRIDE"  # "1" = 備えの無い複製が在っても通す (持ち主の判断を受けた時だけ)
READY_HEADLINE = "NOT READY"
READY_TIMEOUT = 120
READY_MAX_LINES = 20


def _ready_hook():
    v = os.environ.get(READY_HOOK_ENV, "")
    if v == "0":
        return None
    hook = Path(v) if v else Path.home() / ".claude" / "rewrite-ready-check"
    return hook if hook.is_file() else None


def rewrites_default_branch(repo, remote, rows, refs=None):
    """push の行 (lref lsha rref rsha) のうち、 remote の既定 branch を fast-forward でなく動かすもの (= 履歴の書き換え) の
    remote ref の list。 既定 branch だけを見る (作業 branch の rebase + force-push は普通の運用)。 remote の今の値が手元に
    無ければ判定しない (fetch できなかった = その push 自体が同じ理由で失敗する)。"""
    refs = tracked_refs(repo, remote) if refs is None else refs
    head = f"refs/remotes/{remote}/"
    names = {r[len(head):] for r in refs if r.startswith(head)}
    out = []
    for _lref, lsha, rref, rsha in rows:
        if rsha == ZERO or not rref.startswith("refs/heads/") or rref[len("refs/heads/"):] not in names:
            continue
        if _has(repo, rsha) and not is_ancestor(repo, rsha, lsha):
            out.append(rref)
    return out


def ready_gate(repo, rrefs):
    """履歴を書き換える push の前に、 複製の側の備えを点呼する command (READY_HOOK、 引数 = repo の path) を呼ぶ。
    (止めるか, 行の list)。 契約: exit 1 かつ出力に READY_HEADLINE = 備えの無い複製が在る → 止める。 exit 0 = 揃っている。
    それ以外 (起動できない・timeout・他の終了値) = 点呼が走らなかった → 1 行出して通す (点呼の故障で push を止めない)。
    command が無ければ何もしない。"""
    hook = _ready_hook()
    if hook is None:
        return False, []
    repo = Path(repo)
    try:
        r = subprocess.run([str(hook), str(repo)], capture_output=True, text=True, timeout=READY_TIMEOUT, env=dict(os.environ))
    except (OSError, subprocess.TimeoutExpired) as exc:
        log_event("ready-skip", repo, type(exc).__name__)
        return False, [f"{repo.name}: 履歴を書き換える push の前の点呼が走らなかった ({type(exc).__name__}) = 点呼なしで通す"]
    out = [l for l in (r.stdout + "\n" + r.stderr).splitlines() if l.strip()]
    if r.returncode == 1 and any(READY_HEADLINE in l for l in out):
        body = "\n".join("    " + l for l in out[:READY_MAX_LINES])
        if os.environ.get(READY_OVERRIDE_ENV) == "1":
            log_event("ready-override", repo, " ".join(rrefs))
            return False, [f"{repo.name}: 備えの無い複製が在るまま、 履歴を書き換える push を通す ({READY_OVERRIDE_ENV}=1):\n{body}"]
        return True, [f"{repo.name}: {GUARD_HEADLINE} ({' '.join(rrefs)}): この push は remote の既定 branch の履歴を書き換える"
                      f" (fast-forward でない)。 備え (push の検査・無人の追従) の無い複製が在る:\n{body}\n"
                      f"  備えは各 machine の定期 job が置く = 揃うのを待つ。 待てない時は、 持ち主の判断を受けてから"
                      f" {READY_OVERRIDE_ENV}=1 を付けて push する"]
    if r.returncode != 0:
        log_event("ready-skip", repo, f"rc={r.returncode}")
        return False, [f"{repo.name}: 履歴を書き換える push の前の点呼が走らなかった (rc={r.returncode}) = 点呼なしで通す"]
    return False, []


def guard_stdin(repo, lines, cli_globs=(), remote=None, fetch=True):
    """git pre-push の stdin (local_ref local_sha remote_ref remote_sha) を検査。 (ok, messages)。
    remote = pre-push の第 1 引数 (remote 名。 URL だけの push では無い = upstream の remote を使う)。
    remote の今の先頭 (rsha) が手元の知識と違えば、 判定の前に fetch する (fetch=False で止める = test と、 直前に
    fetch した呼び手)。 fetch の失敗は判定を止めない (その push 自体が同じ理由で失敗する)。"""
    repo = Path(repo)
    upstream = upstream_of(repo) or "origin/HEAD"
    rows = []
    for line in lines:
        a = line.split()
        if len(a) == 4 and a[1] != ZERO:   # lsha = 0 は ref の削除
            rows.append(a)
    if not rows:
        return True, []
    rname = remote if (remote and git_ok(repo, "remote", "get-url", remote)) else upstream.split("/", 1)[0]
    if fetch and git_ok(repo, "remote", "get-url", rname) and _remote_moved(repo, rname, rows):
        try:
            git(repo, "fetch", "-q", rname, timeout=FETCH_TIMEOUT)
        except (RuntimeError, subprocess.TimeoutExpired):
            pass
    gen = Generation.load(repo, upstream if rev(repo, upstream) else "", cli_globs)
    refs = tracked_refs(repo, rname)
    try:
        discarded = discarded_objects(repo, refs) if refs else (set(), set())
    except (RuntimeError, subprocess.TimeoutExpired, OSError):
        discarded = (set(), set())
    remembered = remembered_discarded(repo)
    rewritten = bool(gen.maps or gen.forbidden or discarded[0] or remembered)
    base = [c for c in (rev(repo, r) for r in refs) if c]
    msgs = []
    notes = []      # 止めない知らせ (stub が表示して通す)
    forced = rewrites_default_branch(repo, rname, rows, refs)
    if forced:
        try:
            stop, said = ready_gate(repo, forced)
        except Exception as exc:  # 点呼の故障は push を止めない
            log_event("ready-skip", repo, type(exc).__name__)
            stop, said = False, [f"{repo.name}: 履歴を書き換える push の前の点呼が走らなかった ({type(exc).__name__}) = 点呼なしで通す"]
        (msgs if stop else notes).extend(said)
    for _lref, lsha, rref, rsha in rows:
        # 既に remote に在る分は範囲から除く。 rsha が手元に無い (fetch できなかった) / 新しい ref なら、 既定 branch の今の値を除く
        exclude = [rsha] if (rsha != ZERO and _has(repo, rsha)) else base
        objs = _range_objects(repo, lsha, exclude or ["--remotes"])
        if rewritten:
            idset = {s for s, _p in objs} - TRIVIAL_OBJECTS
            known = gen.old_shas | gen.forbidden | set(discarded[0]) | set(discarded[1]) | remembered
            allow = _allowed(idset) & known
            if allow:
                log_event("guard-allow", repo, " ".join(sorted(x[:12] for x in allow))[:200])
                notes.append(f"{repo.name}: 止まるはずの object {len(allow)} 個を、 {ALLOW_ENV} の名指しで通す ({rref})")
            hits = push_violations(repo, lsha, exclude, gen, discarded, ids=idset - allow, remembered=remembered)
            if hits:
                flagged = sorted((idset - allow) & known)
                shown = " ".join(x[:12] for x in flagged[:5]) + (f" ほか {len(flagged) - 5} 個" if len(flagged) > 5 else "")
                msgs.append(f"{repo.name}: {GUARD_HEADLINE} ({rref}): {'、 '.join(hits)} = 古い履歴が混ざっている。 "
                            f"追従 (git-rewrite-follow.py follow --repo {repo}) してから、 必要な commit だけ cherry-pick で載せ直す。\n"
                            f"  止まった object: {shown}\n"
                            f"  消した中身を戻すのでなく、 同じ中身の file を新しく足しただけなら、 持ち主の判断を受けてから"
                            f" {ALLOW_ENV}=<その sha> を付けて push する (名指しした object だけが通り、 記録に残る)")
        try:
            extra = content_violations(repo, lsha, exclude, objs)
        except (RuntimeError, subprocess.TimeoutExpired, OSError, UnicodeError):
            extra = []
        if extra:
            msgs.append(f"{repo.name}: {GUARD_HEADLINE} ({rref}): {'、 '.join(extra)}")
    return (not msgs), msgs + notes


# ---------------------------------------------------------------- push 範囲の中身の検査 (書き換えに依らない)
#
# remote の中身についての不変条件は、 remote への入口 (push) で検査しないと網にならない: commit 時の検査は、 rebase・merge・
# cherry-pick で運ばれる commit と、 hook の無い clone で作られた commit を通らない。 ここでは 2 つだけを見る:
#   (1) git-crypt の対象の path に、 平文の blob を push しない (暗号化の対象を広げた attr が届く前の clone で commit した file)
#   (2) commit message の識別子の検査 (commit-msg と同じ engine) を、 push 範囲の新しい commit にも当てる

CRYPT_MAGIC = b"\x00GITCRYPT"
CRYPT_GUARD_ENV = "CLAUDE_CRYPT_PUSH_GUARD"          # "0" で (1) を止める
MSG_GATE_ENV = "GIT_REWRITE_FOLLOW_MSG_GATE"          # (2) の engine の path を差し替える (test 用)。 "0" で止める
MSG_GATE_HEADING = "check-student-identifiers: BLOCK"
MSG_GATE_MAX = 50                                     # 1 回の push で見る commit の上限 (新しい方から)


def _crypt_declared(repo):
    """worktree の .gitattributes のどれかが git-crypt の filter を宣言しているか (宣言の無い repo で検査の process を起こさない)。"""
    names = git(repo, "ls-files", "--", ".gitattributes", "*/.gitattributes", check=False).splitlines()
    for n in names or [".gitattributes"]:
        try:
            if "filter=git-crypt" in (Path(repo) / n).read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            continue
    return False


def crypt_plaintext(repo, objs):
    """objs = [(sha, path)] (push 範囲の新しい object)。 path が今の .gitattributes で filter=git-crypt なのに、 中身が git-crypt の
    暗号文でない blob の [(sha, path)]。 空の file は対象外 (git-crypt は空の file を暗号化しない)。"""
    if os.environ.get(CRYPT_GUARD_ENV, "1") == "0" or not _crypt_declared(repo):
        return []
    cands = [(s, p) for s, p in objs if p]
    if not cands:
        return []
    paths = sorted({p for _s, p in cands})
    r = subprocess.run(["git", "-C", str(repo), "check-attr", "-z", "--stdin", "filter"], input="\0".join(paths) + "\0",
                       capture_output=True, text=True, env=_env(), timeout=120)
    f = r.stdout.split("\0")
    crypt = {f[i] for i in range(0, len(f) - 2, 3) if f[i + 2] == "git-crypt"}
    if not crypt:
        return []
    cands = [(s, p) for s, p in cands if p in crypt]
    chk = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"],
                         input="\n".join(sorted({s for s, _p in cands})) + "\n", capture_output=True, text=True, env=_env(),
                         timeout=120).stdout
    blobs = {a[0] for a in (l.split() for l in chk.splitlines()) if len(a) == 3 and a[1] == "blob" and a[2] != "0"}
    bad = []
    for s, p in cands:
        if s not in blobs:
            continue
        pr = subprocess.Popen(["git", "-C", str(repo), "cat-file", "blob", s], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=_env())
        try:
            head = pr.stdout.read(len(CRYPT_MAGIC))
        finally:
            pr.stdout.close()
            pr.kill()
            pr.wait()
        if head != CRYPT_MAGIC:
            bad.append((s, p))
    return bad


def _msg_gate_engine():
    """commit message の識別子の検査の engine の path ('' = 当てない)。 識別子の一覧が machine に無ければ当てない
    (一覧は machine ごとの file。 無い machine で commit ごとに process を起こさない)。"""
    v = os.environ.get(MSG_GATE_ENV)
    if v == "0":
        return ""
    if v:
        return v if os.path.isfile(v) else ""
    eng = Path(__file__).resolve().parent.parent / "check-student-identifiers.py"
    home = Path(os.path.expanduser("~")) / ".claude"
    if eng.is_file() and ((home / "student-identity.json").is_file() or (home / "pii-filename-patterns.txt").is_file()):
        return str(eng)
    return ""


def message_gate(repo, local_sha, exclude):
    """push 範囲の新しい commit の message を、 commit-msg と同じ engine に通す。 止められた commit の sha の list。
    commit-msg の hook は rebase・cherry-pick で運ばれる commit には走らない = 消した識別子入りの message が、 新しい sha で戻る。"""
    eng = _msg_gate_engine()
    if not eng:
        return []
    import tempfile
    args = ["rev-list", f"--max-count={MSG_GATE_MAX}", local_sha] + (["--not"] + list(exclude) if exclude else ["--not", "--remotes"])
    bad = []
    with tempfile.TemporaryDirectory(prefix="grf-msg-") as td:
        mf = os.path.join(td, "COMMIT_EDITMSG")
        for c in git(repo, *args, check=False, timeout=120).split():
            with open(mf, "w", encoding="utf-8", errors="surrogateescape") as f:
                f.write(git(repo, "log", "-1", "--format=%B", c, check=False) + "\n")
            r = subprocess.run([sys.executable or "python3", eng, "--commit-msg", mf], cwd=str(repo),
                               capture_output=True, text=True, timeout=60)
            if r.returncode == 1 and MSG_GATE_HEADING in (r.stderr + r.stdout):
                bad.append(c)
    return bad


def content_violations(repo, local_sha, exclude, objs):
    """push 範囲の中身の検査 (上の 2 つ)。 違反の説明 list。"""
    hits = []
    pl = crypt_plaintext(repo, objs)
    if pl:
        hits.append(f"git-crypt の対象の path に平文の blob {len(pl)} 個 (例 {pl[0][1]}) = 暗号化されずに commit されている。"
                    f" その file を今の .gitattributes の下で commit し直す (git rm --cached <file> && git add <file>、"
                    f" 平文の版を含む commit は push しない)。 意図した平文なら {CRYPT_GUARD_ENV}=0")
    bm = message_gate(repo, local_sha, exclude)
    if bm:
        hits.append(f"commit message に識別子の検査で止まるものが {len(bm)} 個 (例 {bm[0][:7]}) = message を直してから push する"
                    f" (確かめる: git log -1 --format=%B {bm[0][:7]})")
    return hits


def head_violations(repo, cli_globs=()):
    """HEAD が、 upstream に無い commit として、 書き換えで捨てられた履歴の commit を抱えているか (= 追従前の clone)。
    (ok, message)。 fetch はしない (commit のたびに呼ばれる = 今 remote-tracking ref が示す状態だけで判定する)。"""
    repo = Path(repo)
    upstream = upstream_of(repo)
    if not upstream or not rev(repo, upstream):
        return True, ""
    local = _range_ids(repo, "HEAD", [upstream], objects=False, timeout=60)
    if not local:
        return True, ""
    gen = Generation.load(repo, upstream, cli_globs)
    dcommits = set(discarded_commits(repo, tracked_refs(repo, upstream.split("/", 1)[0]))[0])
    hits = local & (gen.old_shas | dcommits)
    if not hits:
        return True, ""
    return False, (f"{HEAD_HEADLINE}: {repo.name} の HEAD は、 remote から捨てられた (書き換えられた) 履歴の commit {len(hits)} 個の上に"
                   f"ある (例 {sorted(hits)[0][:7]})。 この上に commit を積んでも push できない。 先に追従する:"
                   f" python3 {engine_cli_path()} follow --repo {repo}")


# ---------------------------------------------------------------- remote 側の検出 (消したものが戻っていないか)

def audit_repo(repo, cli_globs=(), use_cache=True):
    """manifest のある repo の remote-tracking ref を読み、 消した世代が戻っていないかを見る。 finding の行の list ([] = 無し)。
      🔴 upstream に対応表の旧 sha の commit / forbidden の object が在る (= 戻った。 hook を持たない clone からの push・
         host 上の merge は、 ここでしか分からない)
      🟠 remote の他の branch が旧 sha の commit を抱えている (= merge すれば戻る)
    fetch はしない (読むのは今の remote-tracking ref)。 ref の状態が前回と同じなら前回の結果を返し、 前回きれいだった
    upstream は、 その先頭から先だけを見る。"""
    import json
    repo = Path(repo)
    upstream = upstream_of(repo)
    up_sha = rev(repo, upstream) if upstream else ""
    if not up_sha:
        return []
    mtree = manifest_tree(repo, upstream)
    extra = extra_map_paths(cli_globs)
    cdir = _common_dir(repo) / REMOVED_CACHE
    try:
        mem_names = sorted(q.name for q in cdir.iterdir() if q.is_file() and not q.name.endswith(".tmp"))
    except OSError:
        mem_names = []
    if not mtree and not extra and not mem_names:
        return []
    rname = upstream.split("/", 1)[0]
    refs = {}
    fmt = "--format=%(refname) %(objectname) %(symref)"
    for line in git(repo, "for-each-ref", fmt, f"refs/remotes/{rname}/", check=False).splitlines():
        a = line.split()
        if len(a) == 2:          # symref (<remote>/HEAD) は 3 欄 = 飛ばす
            refs[a[0]] = a[1]
    # 鍵 = remote の ref の状態 + manifest の tree (+ 外から渡す対応表の名前)。 一致すれば対応表を読まずに前回の結果を返す
    mkey = mtree + "|" + "|".join(extra) + "|" + ",".join(mem_names)
    state = "\n".join(f"{r} {s}" for r, s in sorted(refs.items())) + "\n" + mkey
    key = hashlib.sha1(state.encode()).hexdigest()
    cf = _common_dir(repo) / AUDIT_CACHE
    prev = {}
    if use_cache:
        try:
            with open(cf, encoding="utf-8") as f:
                prev = json.load(f)
        except (OSError, ValueError):
            prev = {}
        if prev.get("key") == key:
            return list(prev.get("findings") or [])
    gen = Generation.load(repo, upstream, cli_globs)
    remembered = (remembered_discarded(repo) - gen.old_shas - gen.forbidden) if mem_names else set()
    if not gen.old_shas and not gen.forbidden and not remembered:
        return []
    name = repo.name
    findings = []
    since = prev.get("clean_upto") or ""
    neg = [since] if (since and not prev.get("findings") and prev.get("manifest") == mkey
                      and _has(repo, since) and is_ancestor(repo, since, up_sha)) else []
    ids = set(_range_ids(repo, up_sha, neg, objects=bool(gen.forbidden)))
    back = ids & gen.old_shas
    if back:
        findings.append(f"🔴 {name}: {upstream} に、 書き換えで消した世代の commit が {len(back)} 個在る (例 {sorted(back)[0][:7]}) = 戻っている。"
                        f" どの push で入ったかを見る: git -C {repo} log --oneline --merges -5 {upstream}")
    fb = ids & gen.forbidden
    if fb:
        findings.append(f"🔴 {name}: {upstream} に、 書き換えで消した版の object が {len(fb)} 個在る (例 {sorted(fb)[0][:7]}) = 戻っている")
    rb = (ids & remembered) - TRIVIAL_OBJECTS
    if rb:
        findings.append(f"🔴 {name}: {upstream} に、 この clone が「remote から捨てられた」 と記録した履歴の commit / object が {len(rb)} 個在る"
                        f" (例 {sorted(rb)[0][:7]}) = 戻っている (意図して戻したのでなければ、 どの push で入ったかを見る:"
                        f" git -C {repo} log --oneline --merges -5 {upstream})")
    for ref, sha in sorted(refs.items()):
        if sha == up_sha or ref == "refs/remotes/" + upstream:
            continue
        c = _range_ids(repo, sha, [up_sha], objects=False, timeout=120) & (gen.old_shas | remembered)
        if c:
            short = ref[len("refs/remotes/"):]
            findings.append(f"🟠 {name}: remote の branch {short} が書き換え前の履歴を抱えている (commit {len(c)} 個) = merge すれば戻る。"
                            f" 要らなければ remote から消す、 要るなら新しい履歴に載せ直す")
    if use_cache:
        try:
            tmp = cf.with_name(cf.name + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"key": key, "findings": findings, "clean_upto": "" if findings else up_sha,
                           "manifest": mkey}, f, ensure_ascii=False)
            os.replace(tmp, cf)
        except OSError:
            pass
    return findings


def forbidden_from_local(repo, cli_globs=()):
    """対応表の旧 sha のうち手元に在る commit から届き、 upstream からは届かない tree / blob (= 旧世代にしか無い object) を集める。
    (sha の sorted list, 手元に在った旧 commit の数, 対応表の旧 sha の数)。 書き換えた clone (旧 object がまだ在る) で回し、
    結果を `.rewrite-follow/forbidden-blobs*` に置く。 旧 commit が手元に無い分は拾えない = 数を見て被覆を判断する。"""
    repo = Path(repo)
    upstream = upstream_of(repo)
    up_sha = rev(repo, upstream) if upstream else ""
    if not up_sha:
        return [], 0, 0
    gen = Generation.load(repo, upstream, cli_globs)
    olds = gen.old_shas
    if not olds:
        return [], 0, 0
    have = _existing_commits(repo, olds)
    if not have:
        return [], 0, len(olds)
    # 厳密な差集合 (_objects_only_in の注記)。 remote の他の branch に在る object も除く (そこから正当に届く object を禁じない)
    only_old = _objects_only_in(repo, have, _clean_remote_tips(repo, upstream.split("/", 1)[0], set(olds), [up_sha]))
    commits = set(git(repo, "rev-list", "--stdin", input="\n".join(have) + "\n", check=False, timeout=300).split())
    objs = sorted(only_old - commits)
    return objs, len(have), len(olds)


CHAIN_SUFFIX = ".rewrite-follow-chained"        # 包んだ元の hook の退避先 (<stub の file 名> + これ)
CHAIN_ENV = "GIT_REWRITE_FOLLOW_CHAIN"          # "0" = 別の pre-push hook を包まない (従来どおり触らない)
CHAIN_CONFIG = "rewritefollow.chain"            # clone ごとの opt-out: git config rewritefollow.chain false
PDFPUB_MARK = "# pdf-publish pre-push hook"     # templates/shared-project/pdf-publish/install-hook.sh が置く hook の印
PDFPUB_SLOT = ".before-pdf-publish"             # その hook が、 在れば自分の後に呼ぶ「前から在った hook」 の置き場
PDFPUB_SLOT_CALL = '"$0.before-pdf-publish" "$@"'


def stub_text(engine_path, repo):
    """pre-push stub。 止めるのは「engine が exit 1 かつ違反の見出しを出した」 時だけ = engine の故障 (python の異常終了も
    exit 1) を違反と読んで全 push を止めない。 検査が走らなかった時は 1 行出して通し、 追従の記録にも残す (guard-error。
    その場の 1 行は誰も読まない = 定期 job が recent_events で拾う)。
    `<この file>.rewrite-follow-chained` が在れば (= 前からそこに在った別の hook)、 検査が通った後に同じ引数と stdin で呼び、
    その終了値で push が決まる。 検査が走らなかった時 (python3・engine・一時 file が無い) も、 元の hook は必ず呼ぶ。"""
    import shlex
    chained = '"$CH"'
    name = shlex.quote(Path(str(repo)).name)
    return (
        "#!/bin/sh\n"
        f"# {STUB_MARK} — installed by git-rewrite-follow.py ensure-prepush (do not edit; re-run ensure-prepush)\n"
        "# Refuses a push that carries commits / objects of a rewritten-away generation "
        "(conventions/multi-machine-state.md#history-rewrite-follow).\n"
        f"# A pre-push hook that was here before lives on as <this file>{CHAIN_SUFFIX}: it runs after the check passes,\n"
        "# with the same arguments and stdin, and its exit status decides the push.\n"
        f'LOG="${{{LOG_ENV}:-$HOME/.claude/state/rewrite-follow.log}}"\n'
        "skipped() {\n"
        '  echo "rewrite-follow pre-push: $1" >&2\n'
        "  { mkdir -p \"$(dirname \"$LOG\")\" && printf '%s guard-error %s %s\\n' \"$(date +%Y-%m-%dT%H:%M:%S)\" "
        f'{name} "$2" >> "$LOG"; }} 2>/dev/null\n'
        "  return 0\n"
        "}\n"
        f'CH="$0{CHAIN_SUFFIX}"\n'
        "# moved into another hook's chain slot after it wrapped a hook: the kept hook still carries the old name\n"
        f'if [ ! -x "$CH" ]; then case "$0" in *{PDFPUB_SLOT}) CH="${{0%{PDFPUB_SLOT}}}{CHAIN_SUFFIX}" ;; esac; fi\n'
        'IN="$(mktemp 2>/dev/null || mktemp -t prepush 2>/dev/null)"\n'
        'if [ -z "$IN" ]; then\n'
        "  skipped '一時 file を作れないので検査せず通す' no-tmpfile\n"
        f'  if [ -x {chained} ]; then exec {chained} "$@"; fi\n'
        "  exit 0\n"
        "fi\n"
        'cat > "$IN"\n'
        "if ! command -v python3 >/dev/null 2>&1; then\n"
        "  skipped 'python3 が無いので検査せず通す' no-python3\n"
        f'elif [ ! -f "{engine_path}" ]; then\n'
        "  skipped 'engine が無いので検査せず通す' no-engine\n"
        "else\n"
        f'  out="$(python3 "{engine_path}" guard --repo "{repo}" --hook "$@" < "$IN" 2>&1)"\n'
        "  rc=$?\n"
        "  [ -n \"$out\" ] && printf '%s\\n' \"$out\" >&2\n"
        f"  if [ \"$rc\" -eq 1 ]; then case \"$out\" in *'{GUARD_HEADLINE}'*) rm -f \"$IN\"; exit 1 ;; esac; fi\n"
        '  [ "$rc" -eq 0 ] || skipped "検査が走らなかった (rc=$rc) ので通す" "rc=$rc"\n'
        "fi\n"
        f'if [ -x {chained} ]; then\n'
        f'  {chained} "$@" < "$IN"; rc=$?; rm -f "$IN"; exit $rc\n'
        "fi\n"
        'rm -f "$IN"\n'
        "exit 0\n"
    )


def hooks_dir(repo):
    p = Path(git(repo, "rev-parse", "--git-path", "hooks"))
    return p if p.is_absolute() else Path(repo) / p


def engine_cli_path():
    return str(Path(__file__).resolve().parent.parent / "git-rewrite-follow.py")


def _hooks_tracked_in_worktree(repo):
    """core.hooksPath が repo の中 (相対 path) を指すか = hook が git に track されている repo。 そこへ機械ごとの絶対 path を
    持つ stub を pre-push として書くと worktree を汚す (commit されれば他の clone で壊れる。 repo が後で自分の pre-push を
    足せば pull が止まる) = 置かない。"""
    hp = git(repo, "config", "--get", "core.hooksPath", check=False).strip()
    return bool(hp) and not os.path.isabs(os.path.expanduser(hp))


def _read_text(p):
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


SELF_PATH_RE = re.compile(r"\$0|\$\{0|BASH_SOURCE|__file__|PROGRAM_NAME|argv\[0\]")


def _uses_own_path(text):
    """hook が自分の path ($0 など) から隣の file を引く書き方か。 包むと hook の名前が変わるので、 そういう hook は包まない。"""
    return bool(SELF_PATH_RE.search(text))


def _chain_allowed(repo):
    if os.environ.get(CHAIN_ENV, "1") == "0":
        return False
    return git(repo, "config", "--get", CHAIN_CONFIG, check=False).strip().lower() not in ("false", "0", "no", "off")


def _prepush_plan(repo):
    """stub の置き場を決める。 (kind, dst, 理由)。
      'direct'  hooks/pre-push に stub (hook が無い / 既に本部品の stub)
      'slot'    pdf-publish の hook が在る → その hook が自分の後に呼ぶ口 (pre-push.before-pdf-publish) に stub。 元の hook は
                触らない (その hook 自身の鎖の仕組みに載る)。 hook の dir が track されていても置ける (口の名前は repo の file と
                衝突しない。 clone の .git/info/exclude に足して status に出さない)
      'wrap'    別の hook が在る → dst の今の中身を dst + CHAIN_SUFFIX に写し、 dst を stub に替える (stub が検査の後に呼ぶ)
      'blocked' 置けない (dst = None、 理由つき): track された hooks dir の pre-push / 鎖を切った clone"""
    hd = hooks_dir(repo)
    hook = hd / "pre-push"
    tracked = _hooks_tracked_in_worktree(repo)
    if not hook.exists():
        if tracked:
            return "blocked", None, "hook が repo に track されている (core.hooksPath)"
        return "direct", hook, ""
    cur = _read_text(hook)
    if STUB_MARK in cur:
        return "direct", hook, ""
    if PDFPUB_MARK in cur and PDFPUB_SLOT_CALL in cur:
        slot = hd / ("pre-push" + PDFPUB_SLOT)
        if not slot.exists() or STUB_MARK in _read_text(slot):
            return "slot", slot, ""
        if tracked or not _chain_allowed(repo):
            return "blocked", None, "pdf-publish の hook の鎖の口に、 別の hook が既に在る"
        if _uses_own_path(_read_text(slot)):
            return "blocked", None, "鎖の口に在る hook が自分の path ($0 など) を使う = 包むと隣の file を引けなくなる"
        return "wrap", slot, ""
    if tracked:
        return "blocked", None, "track された hooks dir に別の pre-push hook が在る"
    if not _chain_allowed(repo):
        return "blocked", None, "既存の pre-push hook がある (鎖にしない設定)"
    if _uses_own_path(cur):
        return "blocked", None, "既存の pre-push hook が自分の path ($0 など) を使う = 包むと隣の file を引けなくなる"
    return "wrap", hook, ""


def prepush_state(repo):
    """'stub' (push の検査が通る: 本部品の stub、 または pdf-publish の hook の鎖の口に置いた stub) /
    'foreign' (別の pre-push か、 track された hooks dir で、 検査が通らない) / 'none'。"""
    try:
        hd = hooks_dir(repo)
        p = hd / "pre-push"
        if p.exists():
            cur = _read_text(p)
            if STUB_MARK in cur:
                return "stub"
            if PDFPUB_MARK in cur and PDFPUB_SLOT_CALL in cur and STUB_MARK in _read_text(hd / ("pre-push" + PDFPUB_SLOT)):
                return "stub"
            return "foreign"
        return "foreign" if _hooks_tracked_in_worktree(repo) else "none"
    except (OSError, RuntimeError):
        return "none"


def _place_executable(dst, text):
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".rewrite-follow.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o755)
    os.replace(tmp, dst)


def _exclude_local(repo, path):
    """worktree の中に置いた clone だけの file を、 その clone の info/exclude に足す (status に出さない・add されない)。"""
    try:
        top = Path(git(repo, "rev-parse", "--show-toplevel")).resolve()
        rel = "/" + path.resolve().relative_to(top).as_posix()
    except (ValueError, RuntimeError, OSError):
        return
    ex = _common_dir(repo) / "info" / "exclude"
    cur = _read_text(ex)
    if rel in cur.splitlines():
        return
    ex.parent.mkdir(parents=True, exist_ok=True)
    with open(ex, "a", encoding="utf-8") as f:
        f.write(("" if (not cur or cur.endswith("\n")) else "\n") + rel + "\n")


def ensure_prepush(repo, only_with_manifest=True, engine=None, quiet_foreign=False):
    """pre-push stub を置く / 更新する。 置いた・更新した時だけ 1 行、 それ以外は ''。 置けない clone は 1 行
    (quiet_foreign=True なら無音 = 毎回名指ししない)。
    only_with_manifest=False = manifest の無い repo にも置く (書き換えの **前から** 全 clone に在る = 書き換えてから配る
    のでは、 届く前の clone が無防備になる)。 upstream の無い repo には置かない (push 先が無い)。
    別の pre-push hook が在る clone (LFS・独自の確認・PDF の公開など) にも検査を通す (_prepush_plan): その hook は消さず、
    検査の後に同じ引数と stdin で呼ぶ。 元の hook を写してから stub に替えるので、 途中で hook が無い瞬間は無い。
    戻し方 = `mv pre-push.rewrite-follow-chained pre-push`。 包まない = env GIT_REWRITE_FOLLOW_CHAIN=0 か、 その clone で
    `git config rewritefollow.chain false`。 hook の管理道具 (`git lfs install --force` など) が stub を上書きしたら、 次の回に
    包み直す (退避は今の hook で置き換える)。"""
    import shutil
    repo = Path(repo)
    if not (repo / ".git").exists():
        return ""
    upstream = upstream_of(repo)
    if not upstream:
        return ""
    if only_with_manifest and not manifest_tree(repo, upstream):
        return ""
    engine = engine or engine_cli_path()
    # 既に包んだ hook が自分の path を使う書き方だった時は、 元に戻す (包んだままだと、 その hook は隣の file を引けずに壊れている)
    hd0 = hooks_dir(repo)
    for base in ("pre-push", "pre-push" + PDFPUB_SLOT):
        stubp, keptp = hd0 / base, hd0 / (base + CHAIN_SUFFIX)
        if keptp.exists() and STUB_MARK in _read_text(stubp) and _uses_own_path(_read_text(keptp)):
            os.replace(keptp, stubp)
            return f"{repo.name}: 包んでいた pre-push hook は自分の path ($0 など) を使う = 包むのをやめて元に戻した ({stubp})"
    kind, dst, why = _prepush_plan(repo)
    if kind == "blocked":
        return "" if quiet_foreign else f"{repo.name}: rewrite-follow の stub を置けない ({why}。 {hooks_dir(repo)})"
    want = stub_text(engine, str(repo))
    if kind == "wrap":
        chained = dst.with_name(dst.name + CHAIN_SUFFIX)
        tmp = chained.with_name(chained.name + ".tmp")
        if tmp.exists() or tmp.is_symlink():
            tmp.unlink()
        shutil.copy2(dst, tmp, follow_symlinks=False)       # 中身と mode を保つ (symlink は link のまま。 実行の印が無かった hook は無いまま)
        os.replace(tmp, chained)
        _place_executable(dst, want)
        return f"{repo.name}: 既存の pre-push hook を残し ({chained.name})、 push の検査を先に通す stub を置いた ({dst})"
    moved = False
    if kind == "slot":
        # 包んだ stub が、 後から入った pdf-publish の installer に口へ移された clone: stub は「自分の名前 + CHAIN_SUFFIX」 を呼ぶので、
        # 前の名前で残った退避 (pre-push.rewrite-follow-chained) は呼ばれなくなる = 元の hook が黙って止まる。 口の名前に付け替える
        orphan = dst.with_name("pre-push" + CHAIN_SUFFIX)
        mine = dst.with_name(dst.name + CHAIN_SUFFIX)
        if (orphan.exists() or orphan.is_symlink()) and not (mine.exists() or mine.is_symlink()):
            os.replace(orphan, mine)
            moved = True
    if dst.exists() and _read_text(dst) == want:
        return f"{repo.name}: 包んでいた元の pre-push hook の退避を、 鎖の口の名前に付け替えた ({dst.name}{CHAIN_SUFFIX})" if moved else ""
    _place_executable(dst, want)
    if kind == "slot":
        if _hooks_tracked_in_worktree(repo):
            _exclude_local(repo, dst)
        return f"{repo.name}: pdf-publish の hook の鎖の口に、 古い世代の push を止める stub を置いた ({dst})"
    return f"{repo.name}: 古い世代の push を止める pre-push stub を置いた ({dst})"


def has_prepush_stub(repo):
    return prepush_state(repo) == "stub"


def status(repo, cli_globs=()):
    """JSON 向けの状態 (heartbeat / gate が読む)。 fetch はしない。"""
    repo = Path(repo)
    up = upstream_of(repo) if (repo / ".git").exists() else ""
    d = {"repo": str(repo), "upstream": up, "manifest": False, "prepush_stub": has_prepush_stub(repo),
         "prepush": prepush_state(repo), "forced_update_seen": False, "relation": "unknown", "on_discarded_history": False}
    if up and rev(repo, up):
        d["manifest"] = bool(upstream_manifest_files(repo, up))
        d["forced_update_seen"] = forced_update_seen(repo, up)
        head, u = rev(repo, "HEAD"), rev(repo, up)
        if head and u:
            d["relation"] = ("current" if is_ancestor(repo, head, u) else "ahead" if is_ancestor(repo, u, head) else "diverged")
        try:
            d["on_discarded_history"] = not head_violations(repo, cli_globs)[0]
        except (RuntimeError, subprocess.TimeoutExpired, OSError):
            pass
    return d


# ---------------------------------------------------------------- 点呼 (各 machine の事実を、 知っている側が判定する)

def repo_facts(root):
    """root/*/ の repo ごとの事実 (判定はしない): {name: {head, up (この machine が見ている upstream の sha), prepush}}。
    無人の定期 job がこれを毎回 machine ごとの記録に載せる。 判定は読む側 (最新を fetch した machine) が judge_fact で行う
    = 書き換えをまだ知らない machine の自己申告 (「最新です」) を当てにしない。 sha は 12 桁。"""
    out = {}
    for gd in sorted(globmod.glob(os.path.join(str(root), "*", ".git"))):
        repo = Path(gd).parent
        try:
            up = upstream_of(repo)
            if not up:
                continue
            out[repo.name] = {"head": rev(repo, "HEAD")[:12], "up": rev(repo, up)[:12], "prepush": prepush_state(repo)}
            ob = stale_branches(repo)
            if ob:
                out[repo.name]["old_branches"] = ob
                try:
                    bu = branch_unique(repo, ob)
                except (RuntimeError, subprocess.TimeoutExpired, OSError, ValueError):
                    bu = {}
                if bu:
                    out[repo.name]["old_branch_unique"] = bu
        except Exception:   # 1 つの repo の失敗で、 残りの repo の事実を落とさない
            continue
    return out


def stale_branches(repo, cli_globs=()):
    """手元の branch (今の branch を除く) のうち、 upstream に無い commit として、 書き換えで捨てられた履歴の commit を抱えているものの
    名前。 push しなければ害は無い (push は検査が止める) が、 どの machine に残っているかは、 その machine を開くまで誰にも見えない
    = 事実として点呼に載せる。 書き換えの痕跡 (manifest か、 この clone の reflog の forced update) の無い repo は見ない
    (外から渡す対応表だけでは見ない = 全 repo で表を読むことになるため)。"""
    repo = Path(repo)
    upstream = upstream_of(repo)
    if not upstream or not rev(repo, upstream):
        return []
    refs = tracked_refs(repo, upstream.split("/", 1)[0])
    dc = set(discarded_commits(repo, refs)[0])
    if dc:
        try:
            discarded_objects(repo, refs)   # reflog が覚えているうちに、 object の一覧を clone の中に書いておく (remembered_discarded が読む)
        except (RuntimeError, subprocess.TimeoutExpired, OSError):
            pass
    if not dc and not manifest_tree(repo, upstream):
        return []
    removed = Generation.load(repo, upstream, cli_globs).old_shas | dc
    if not removed:
        return []
    cur = git(repo, "symbolic-ref", "--short", "-q", "HEAD", check=False).strip()
    names = []
    for b in git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/", check=False).splitlines():
        if b and b != cur and (_range_ids(repo, "refs/heads/" + b, [upstream], objects=False, timeout=60) & removed):
            names.append(b)
    return names


BRANCH_CACHE = "rewrite-follow-branches.json"   # <git common dir>/ の下。 branch_unique の結果 (branch の先頭 + 捨てられた履歴が鍵)
BRANCH_CACHE_TTL = 86400


def _object_types(repo, shas):
    """{sha: 型}。 手元に無い sha は落とす。"""
    shas = sorted(shas)
    if not shas:
        return {}
    out = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch-check=%(objectname) %(objecttype)"],
                         input="\n".join(shas) + "\n", capture_output=True, text=True, env=_env(), timeout=300).stdout
    return {a[0]: a[1] for a in (l.split() for l in out.splitlines()) if len(a) == 2 and _SHA_RE.match(a[0])}


def branch_unique(repo, names, cli_globs=()):
    """names (stale_branches の返り値) の branch ごとに、 その branch にしか無い中身の数 {name: {"commits": n, "blobs": m}}。
    「その branch にしか無い」 = 今の remote の履歴 (既定 branch + 旧履歴を抱えていない他の branch) にも、 remote から捨てられた
    履歴 (書き換えで意図して消した側) にも無い object。 0 / 0 = その branch は古い履歴の写しで、 消しても失うものが無い。
    消すかを決める材料を、 その machine を開かずに読めるようにする (判断はしない)。 全 walk が要るので、 branch の先頭と
    捨てられた履歴の集合を鍵に 1 日 cache する (その間に upstream が進んでも「そこにしか無い」 は減るだけ = 古い値は多めに出る)。"""
    import json
    repo = Path(repo)
    upstream = upstream_of(repo)
    if not names or not upstream:
        return {}
    remote = upstream.split("/", 1)[0]
    refs = tracked_refs(repo, remote)
    dcommits, dobjs = discarded_objects(repo, refs)
    gen = Generation.load(repo, upstream, cli_globs)
    removed = set(dcommits) | gen.old_shas
    cur = [c for c in (rev(repo, r) for r in refs) if c] or [rev(repo, upstream)]
    cpath = _common_dir(repo) / BRANCH_CACHE
    try:
        cache = json.loads(cpath.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    dkey = hashlib.sha1("\n".join(sorted(removed)).encode()).hexdigest()[:16]
    now = time.time()
    out, keep, base_objs = {}, {}, None
    for b in names:
        tip = rev(repo, "refs/heads/" + b)
        if not tip:
            continue
        key = f"{tip}:{dkey}"
        ent = cache.get(b) if isinstance(cache, dict) else None
        if not (isinstance(ent, dict) and ent.get("key") == key and now - float(ent.get("at", 0)) < BRANCH_CACHE_TTL):
            if base_objs is None:
                base_objs = _all_objects(repo, _clean_remote_tips(repo, remote, removed, cur))
            only = _all_objects(repo, [tip]) - base_objs - dobjs - removed - gen.forbidden
            types = _object_types(repo, only)
            ent = {"key": key, "at": now, "commits": sum(1 for t in types.values() if t == "commit"),
                   "blobs": sum(1 for t in types.values() if t == "blob")}
        keep[b] = ent
        out[b] = {"commits": int(ent.get("commits", 0)), "blobs": int(ent.get("blobs", 0))}
    try:
        tmpf = cpath.with_suffix(".tmp")
        tmpf.write_text(json.dumps(keep), encoding="utf-8")
        os.replace(tmpf, cpath)
    except OSError:
        pass
    return out


def judge_fact(repo, fact, cli_globs=(), _memo=None):
    """別の machine が載せた事実 (repo_facts の 1 件) を、 この clone の今の知識で判定する。 (状態, 説明)。
      followed   その machine の HEAD は今の upstream の履歴の上 (追従済み、 または書き換えの後に clone した)
      unpushed   HEAD はこの clone に無いが、 その machine の見ている upstream は今の履歴の上 (新しい履歴の上の未 push)
      stale      HEAD かその machine の見ている upstream が、 捨てられた履歴の commit (= 未追従。 up も古ければ未 fetch)
      unknown    どちらも判定できない (この clone が古い / その machine にしか無い commit)
    書き換えの痕跡 (対応表か、 この clone の reflog の forced update) が無い repo は ('n/a', '')。"""
    repo = Path(repo)
    upstream = upstream_of(repo)
    up_sha = rev(repo, upstream) if upstream else ""
    if not up_sha:
        return "n/a", ""
    memo = _memo if _memo is not None else {}
    key = str(repo)
    if key not in memo:
        gen = Generation.load(repo, upstream, cli_globs)
        dc = set(discarded_commits(repo, tracked_refs(repo, upstream.split("/", 1)[0]))[0])
        memo[key] = gen.old_shas | dc
    removed = memo[key]
    if not removed:
        return "n/a", ""

    def full(short):
        return rev(repo, short) if short else ""

    def in_removed(short):
        return bool(short) and any(s.startswith(short) for s in removed)

    head, up = fact.get("head") or "", fact.get("up") or ""
    hf, uf = full(head), full(up)
    if in_removed(head) or in_removed(up):
        return "stale", ("未追従 (remote の書き換えをまだ fetch していない)" if in_removed(up) else "未追従 (fetch 済み、 HEAD が古い履歴の上)")
    if hf and is_ancestor(repo, hf, up_sha):
        return "followed", ""
    if uf and is_ancestor(repo, uf, up_sha):
        return "unpushed", "新しい履歴の上に未 push の commit"
    return "unknown", "この clone からは判定できない (先に fetch。 それでも不明なら、 その machine にしか無い commit)"


# ---------------------------------------------------------------- selftest

def _selftest():
    import json
    import tempfile
    fails = []

    def check(label, ok, detail=""):
        print(("  ok: " if ok else "  NG: ") + label + (f"  [{detail}]" if (detail and not ok) else ""))
        if not ok:
            fails.append(label)

    td = tempfile.mkdtemp(prefix="grf-selftest-")
    os.environ.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
                       "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
                       "GIT_COMMITTER_EMAIL": "t@example.invalid", LOG_ENV: os.path.join(td, "follow.log"),
                       MAPS_FILE_ENV: os.path.join(td, "no-maps.txt"), MAPS_ENV: "",
                       MSG_GATE_ENV: "0",     # machine の識別子の一覧に依らせない (message の検査は専用の fixture で差し替えて見る)
                       READY_HOOK_ENV: "0",   # machine に置かれた点呼の command に依らせない (専用の fixture で差し替えて見る)
                       # 旧履歴の日時を固定 (新履歴は別の日時 = 同じ中身・message の commit が同じ秒で同じ sha になるのを避ける、 Linux の CI で実測)
                       "GIT_AUTHOR_DATE": "2000-01-01T00:00:00 +0000", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00 +0000"})
    tmp = Path(td)

    def init(p):
        subprocess.run(["git", "init", "-q", "-b", "main", str(p)], check=True, env=_env())

    def commit(p, files, msg):
        for f, body in files.items():
            fp = p / f
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(body)
            git(p, "add", f)
        git(p, "commit", "-q", "--allow-empty", "-m", msg)
        return rev(p, "HEAD")

    # --- 旧履歴: 3 commit、 2 つ目が「学生の id」 を含む。 status/x.json は volatile
    remote = tmp / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True, env=_env())
    src = tmp / "src"
    init(src)
    o1 = commit(src, {"a.txt": "one\n", "status/x.json": "{}\n"}, "c1")
    o2 = commit(src, {"b.txt": "id=K00X0000 (old)\n"}, "c2 mentions K00X0000")
    o3 = commit(src, {"b.txt": "id=<学籍番号>\n", "c.txt": "3\n"}, "c3 cleaned")
    git(src, "remote", "add", "origin", str(remote))
    git(src, "push", "-q", "origin", "main")
    old_blob_b2 = git(src, "rev-parse", f"{o2}:b.txt")

    def clone(name, at=None):
        p = tmp / name
        subprocess.run(["git", "clone", "-q", str(remote), str(p)], check=True, env=_env())
        if at:
            git(p, "reset", "-q", "--hard", at)
        return p

    # 手元の clone 群 (書き換えの前に作る)
    a_msg = clone("a-msg")                       # message だけの書き換えに揃える
    a_cont = clone("a-cont")                     # 中身の書き換え (今の tree は同じ) に揃える
    a_unp = clone("a-unpushed")                  # 未 push の commit → 止まる
    a_dirty = clone("a-dirty", at=o2)            # behind (b.txt は書き換えで変わる) ∧ その file が dirty → 止まる
    a_cur = clone("a-current")                   # 既に最新 (書き換え後に ff)
    a_beat = clone("a-beat")                     # 無人 job の commit が古い履歴の上に載る
    a_behind = clone("a-behind", at=o2)          # 書き換えの前から behind (tree は変わる) → 対応表で揃う
    a_dirty_other = clone("a-dirty-other")       # 変わっていない file が dirty → 揃う (reset --keep が保つ)
    (a_unp / "z.txt").write_text("mine\n")
    git(a_unp, "add", "z.txt")
    git(a_unp, "commit", "-q", "-m", "unpushed local")
    (a_dirty / "b.txt").write_text("edited locally\n")
    (a_dirty_other / "a.txt").write_text("edited locally, not touched by the rewrite\n")
    commit(a_beat, {"status/x.json": '{"beat": 1}\n'}, "heartbeat")
    commit(a_beat, {"status/x.json": '{"beat": 2}\n'}, "heartbeat")

    # --- 書き換え 1: message だけ (tree は全部同じ)。 新履歴は別の日時で作る
    os.environ["GIT_AUTHOR_DATE"] = os.environ["GIT_COMMITTER_DATE"] = "2000-01-02T00:00:00 +0000"
    new1 = tmp / "new1"
    init(new1)
    n1 = commit(new1, {"a.txt": "one\n", "status/x.json": "{}\n"}, "c1")
    n2 = commit(new1, {"b.txt": "id=K00X0000 (old)\n"}, "c2 mentions <学籍番号>")
    n3 = commit(new1, {"b.txt": "id=<学籍番号>\n", "c.txt": "3\n"}, "c3 cleaned")
    check("fixture: message-only rewrite keeps every tree", git(new1, "rev-parse", n3 + "^{tree}") == git(src, "rev-parse", o3 + "^{tree}"))
    git(new1, "push", "-q", "--force", str(remote), "main:main")
    r = follow_repo(a_msg)
    check("message-only rewrite: followed via tree", r.state == "followed" and r.how == "tree", r.line)
    check("message-only rewrite: HEAD = new tip", rev(a_msg, "HEAD") == n3)
    check("forced update is visible in the reflog", forced_update_seen(a_msg, "origin/main"))
    r = follow_repo(a_msg)
    check("already current: silent", r.state == "current" and r.line == "")
    # 書き換えた後に ff で最新になった clone (= 何もしない)
    git(a_cur, "fetch", "-q")
    git(a_cur, "reset", "-q", "--hard", "origin/main")
    check("current clone: silent", follow_repo(a_cur).state == "current")

    # --- 書き換え 2: 中身も変える (c2 の b.txt を scrub、 今の tree は同じ) + manifest (ignore-paths は書き換えの前から)
    # 手元の a-cont / a-unpushed / a-dirty / a-beat / a-behind / a-dirty-other は旧履歴 (o*) のまま
    for p in (a_cont, a_unp, a_dirty, a_beat, a_behind, a_dirty_other):
        check(f"precondition: {p.name} still on the old history", rev(p, "HEAD") in (o3, o2) or rev(p, "HEAD~1") == o3 or rev(p, "HEAD~2") == o3)
    check("precondition: the dirty clone is behind at the commit whose file the rewrite changes", rev(a_dirty, "HEAD") == o2)
    new2 = tmp / "new2"
    init(new2)
    m1 = commit(new2, {"a.txt": "one\n", "status/x.json": "{}\n", ".rewrite-follow/ignore-paths": "# volatile\nstatus/\n"}, "c1")
    m2 = commit(new2, {"b.txt": "id=<学籍番号> (old)\n"}, "c2 mentions <学籍番号>")
    m3 = commit(new2, {"b.txt": "id=<学籍番号>\n", "c.txt": "3\n"}, "c3 cleaned")
    # 「書き換えの前に ignore-paths を置いた」 状態を旧履歴側にも作る: 旧履歴に通常 commit で ignore-paths を足し、 それを土台に
    git(src, "fetch", "-q", "origin")
    os.environ["GIT_AUTHOR_DATE"] = os.environ["GIT_COMMITTER_DATE"] = "2000-01-01T00:00:00 +0000"   # 旧履歴側の commit
    o0 = commit(src, {".rewrite-follow/ignore-paths": "# volatile\nstatus/\n"}, "add manifest")
    os.environ["GIT_AUTHOR_DATE"] = os.environ["GIT_COMMITTER_DATE"] = "2000-01-02T00:00:00 +0000"   # 新履歴側に戻す
    # 旧側は o1..o3 + o0。 新側 = m1..m3 + 同じ manifest commit 相当 (tree が o0 と同じになるよう c.txt/b.txt を揃える)
    m0 = commit(new2, {}, "add manifest")  # allow-empty: tree は m3 と同じ = ignore-paths 込み
    check("fixture: content rewrite keeps HEAD tree", git(new2, "rev-parse", m0 + "^{tree}") == git(src, "rev-parse", o0 + "^{tree}"))
    check("fixture: content rewrite changes the c2 tree", git(new2, "rev-parse", m2 + "^{tree}") != git(src, "rev-parse", o2 + "^{tree}"))
    # 旧履歴を remote に戻して (= 書き換えの前の状態に、 manifest commit 込み)、 手元の clone を o0 に進める
    git(src, "push", "-q", "--force", "origin", "main:main")
    for p in (a_cont, a_unp, a_dirty_other):
        git(p, "fetch", "-q")
    git(a_cont, "merge", "-q", "--ff-only", "origin/main")
    git(a_dirty_other, "merge", "-q", "--ff-only", "origin/main")
    # a_unp: 手元 commit を o0 の上に載せ直す (通常の rebase = 書き換えの前だから正当)
    git(a_unp, "rebase", "-q", "origin/main")
    # a_dirty は o2 のまま (behind) で b.txt が dirty = 新履歴の先頭では b.txt が違う → reset --keep が止める
    # a_beat: o3 + 2 heartbeat commits (o0 はまだ pull していない = behind ∧ volatile 差)
    # 対応表 (旧 → 新) と forbidden blob を新履歴に通常 commit で置く
    cmap = "old new\n" + "\n".join(f"{o} {n}" for o, n in ((o1, m1), (o2, m2), (o3, m3), (o0, m0))) + "\n"
    mf = commit(new2, {".rewrite-follow/commit-map": cmap, ".rewrite-follow/forbidden-blobs": old_blob_b2 + "\n"}, "publish map")
    git(new2, "push", "-q", "--force", str(remote), "main:main")

    r = follow_repo(a_cont)
    check("content rewrite, HEAD tree equal: followed via map", r.state == "followed" and r.how == "map", f"{r.state} {r.how} {r.line}")
    check("content rewrite: HEAD = new tip (map commit included)", rev(a_cont, "HEAD") == mf)
    # lookup (CLI の map): 旧 sha → 今の sha を upstream の表で引く
    got = {r[0]: r for r in lookup(a_cont, [o2, o2[:8], m1, "0123456789abcdef"])}
    check("lookup: an old sha maps to the new sha on upstream", got[o2][1] == "mapped" and got[o2][2] == m2 and "に在る" in got[o2][3], got[o2])
    check("lookup: a 7+ char prefix of an old sha maps the same way", got[o2[:8]][1] == "mapped" and got[o2[:8]][2] == m2, got[o2[:8]])
    check("lookup: a sha of the current history is reported as unchanged", got[m1][1] == "current" and got[m1][2] == m1, got[m1])
    check("lookup: an unknown sha is reported as unknown", got["0123456789abcdef"][1] == "unknown", got["0123456789abcdef"])
    r = follow_repo(a_unp)
    check("unpushed local commit: stopped, ref untouched", r.state == "stopped" and r.exit_code == 1
          and git(a_unp, "log", "-1", "--format=%s") == "unpushed local", r.line)
    r = follow_repo(a_dirty)
    check("dirty worktree on a changed file: stopped (reset --keep refuses)", r.state == "stopped" and "reset --keep" in r.line, r.line)
    check("dirty worktree: local edit preserved, ref untouched", (a_dirty / "b.txt").read_text() == "edited locally\n" and rev(a_dirty, "HEAD") == o2)
    r = follow_repo(a_dirty_other)
    check("dirty worktree on an untouched file: followed", r.state == "followed", r.line)
    check("dirty worktree on an untouched file: edit preserved", (a_dirty_other / "a.txt").read_text().startswith("edited locally"))
    r = follow_repo(a_beat)
    check("heartbeat commits on old history: followed via map+volatile (old commits not revived)",
          r.state == "followed" and r.how == "map+volatile", f"{r.state} {r.how} {r.line}")
    check("heartbeat clone: HEAD = new tip, no old sha in the branch",
          rev(a_beat, "HEAD") == mf and not ({o1, o2, o3} & set(git(a_beat, "rev-list", "HEAD").split())))
    r = follow_repo(a_behind)
    check("clone behind the rewrite point (its tree was changed): followed via map", r.state == "followed" and r.how == "map", r.line)
    check("behind clone: HEAD = new tip", rev(a_behind, "HEAD") == mf)
    # 対応表も tree も当たらない: 手元だけの commit を含む別 branch を持つ clone → その branch の名指し
    a_br = clone("a-branch")
    git(a_br, "branch", "-q", "oldwork", o2)
    git(a_br, "reset", "-q", "--hard", o0) if git_ok(a_br, "cat-file", "-e", o0) else None
    r = follow_repo(a_br) if rev(a_br, "HEAD") == o0 else Result("skipped")
    if r.state != "skipped":
        check("old-history local branch is named after following", r.state == "followed" and any("oldwork" in x for x in r.extra), " ".join(r.extra))
    # dry-run は ref を動かさない
    a_dry = clone("a-dry")
    git(a_dry, "reset", "-q", "--hard", o3) if git_ok(a_dry, "cat-file", "-e", o3) else None
    if rev(a_dry, "HEAD") == o3:
        r = follow_repo(a_dry, dry_run=True)
        check("dry-run reports and does not move", r.state == "followed" and rev(a_dry, "HEAD") == o3, r.line)

    # --- guard: 古い commit を含む push / 旧世代の blob を rebase で運ぶ push / 正当な push
    gen = Generation.load(a_cont, "origin/main")
    check("generation: old shas from the map exclude identity rows", gen.old_shas == {o1, o2, o3, o0} - {m1, m2, m3, m0})
    check("generation: forbidden blob loaded", old_blob_b2 in gen.forbidden)
    check("generation: ignore-paths loaded", gen.ignore == ["status/"])
    # (i) 旧履歴を merge した状態 (= 追従前の clone で git pull した形)
    a_merge = clone("a-merge")
    if git_ok(a_merge, "cat-file", "-e", o0):
        git(a_merge, "reset", "-q", "--hard", o0)
        git(a_merge, "merge", "-q", "--no-edit", "--allow-unrelated-histories", "origin/main")  # 本物の書き換えは先頭の commit が同じなので related、 fixture は全部変わる
        ok, msgs = guard_stdin(a_merge, [f"refs/heads/main {rev(a_merge, 'HEAD')} refs/heads/main {mf}"])
        check("guard: merged old history is refused (old commit shas)", not ok and msgs and "世代の commit" in msgs[0], " ".join(msgs))
    # (ii) 旧の中身を新履歴に cherry-pick (sha は新しい、 blob は旧) = rebase の形
    a_cp = clone("a-cherry")
    if git_ok(a_cp, "cat-file", "-e", o2):
        git(a_cp, "reset", "-q", "--hard", "origin/main")
        (a_cp / "b.txt").write_text("id=K00X0000 (old)\n")   # 旧 c2 の blob と同じ中身
        git(a_cp, "add", "b.txt")
        git(a_cp, "commit", "-q", "-m", "revived content with a fresh sha")
        ok, msgs = guard_stdin(a_cp, [f"refs/heads/main {rev(a_cp, 'HEAD')} refs/heads/main {mf}"])
        check("guard: revived old content under a new sha is refused (forbidden blob)", not ok and msgs and "blob" in msgs[0], " ".join(msgs))
    # (iii) 正当な新しい commit は通る
    a_ok = clone("a-legit")
    (a_ok / "d.txt").write_text("new work\n")
    git(a_ok, "add", "d.txt")
    git(a_ok, "commit", "-q", "-m", "legit")
    ok, msgs = guard_stdin(a_ok, [f"refs/heads/main {rev(a_ok, 'HEAD')} refs/heads/main {mf}"])
    check("guard: a legitimate new commit passes", ok and not msgs)
    ok, msgs = guard_stdin(a_ok, [f"refs/heads/main {ZERO} refs/heads/main {mf}"])
    check("guard: a ref deletion passes", ok)
    # (iv) manifest の無い repo では guard は何も言わない
    plain_remote = tmp / "plain.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(plain_remote)], check=True, env=_env())
    plain = tmp / "plain"
    init(plain)
    commit(plain, {"p.txt": "p\n"}, "p")
    git(plain, "remote", "add", "origin", str(plain_remote))
    git(plain, "push", "-q", "-u", "origin", "main")
    ok, msgs = guard_stdin(plain, [f"refs/heads/main {rev(plain, 'HEAD')} refs/heads/main {ZERO}"])
    check("guard: repo without a manifest passes", ok)
    check("follow: repo without divergence is silent", follow_repo(plain, fetch=False).state in ("current", "ahead"))

    # --- ensure-prepush: manifest のある repo にだけ、 foreign な hook は触らない、 冪等
    line = ensure_prepush(a_ok, only_with_manifest=True, engine="/x/engine.py")
    check("ensure-prepush: installs on a manifest repo", "置いた" in line and has_prepush_stub(a_ok), line)
    check("ensure-prepush: idempotent", ensure_prepush(a_ok, only_with_manifest=True, engine="/x/engine.py") == "")
    check("ensure-prepush: skips a repo without a manifest", ensure_prepush(plain, only_with_manifest=True) == "" and not has_prepush_stub(plain))
    hd = hooks_dir(plain)
    hd.mkdir(parents=True, exist_ok=True)
    (hd / "pre-push").write_text("#!/bin/sh\nexit 0\n")
    os.environ[CHAIN_ENV] = "0"
    line = ensure_prepush(plain, only_with_manifest=False, engine="/x/engine.py")
    check("ensure-prepush: with chaining switched off, a foreign pre-push is left alone", "置けない" in line and "exit 0" in (hd / "pre-push").read_text())
    os.environ.pop(CHAIN_ENV)
    (hd / "pre-push").unlink()
    st = status(a_ok)
    check("status: manifest + stub + relation", st["manifest"] and st["prepush_stub"] and st["relation"] == "ahead", json.dumps(st))
    # 書き換えの後の通常の分岐: 対応表を運ぶ repo でも、 新しい世代の上の手元の commit + upstream の前進は diverged
    # (= 「書き換えられた」 で止めない。 2026-10-26 email-office の実測)
    a_adv = clone("a-advance")
    (a_adv / "e.txt").write_text("remote advance\n")
    git(a_adv, "add", "e.txt")
    git(a_adv, "commit", "-q", "-m", "remote advance after the rewrite")
    git(a_adv, "push", "-q", "origin", "main")
    r = follow_repo(a_ok, log=False)
    check("ordinary divergence on the new generation of a manifest repo: diverged, not stopped as a rewrite",
          r.state == "diverged" and "書き換えられ" not in r.line, r.line)
    check("ordinary divergence on the new generation: ref untouched", git(a_ok, "log", "-1", "--format=%s") == "legit")
    git(a_adv, "push", "-q", "--force", "origin", f"{mf}:main")   # 後の検査は remote の先頭 = mf を前提にする

    # --- 通常の分岐 (書き換えの痕跡なし): stopped でなく diverged (= 呼び元の従来の扱い)
    od_remote = tmp / "od.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(od_remote)], check=True, env=_env())
    od = tmp / "od"
    init(od)
    commit(od, {"f.txt": "1\n"}, "f1")
    git(od, "remote", "add", "origin", str(od_remote))
    git(od, "push", "-q", "-u", "origin", "main")
    od_other = tmp / "od-other"
    subprocess.run(["git", "clone", "-q", str(od_remote), str(od_other)], check=True, env=_env())
    commit(od_other, {"f.txt": "2\n"}, "remote advance")
    git(od_other, "push", "-q", "origin", "main")
    commit(od, {"h.txt": "local\n"}, "local")
    r = follow_repo(od)
    check("ordinary divergence (no forced-update trace): state diverged, not stopped", r.state == "diverged" and r.exit_code == 1, r.line)
    check("ordinary divergence: ref untouched", git(od, "log", "-1", "--format=%s") == "local")

    # --- sweep: root/*/ を回し、 followed は 1 行、 current は無音
    root = tmp / "root"
    root.mkdir()
    for nm, at in (("r-old", o0), ("r-cur", None)):
        p = root / nm
        subprocess.run(["git", "clone", "-q", str(remote), str(p)], check=True, env=_env())
        if at and git_ok(p, "cat-file", "-e", at):
            git(p, "reset", "-q", "--hard", at)
    res = sweep(root, fetch=False)
    states = {r.state for r, _ in res}
    check("sweep: visits both, follows the old one silently passes the current", "current" in states and ("followed" in states or "current" in states))
    check("sweep: the followed clone landed on the new tip", rev(root / "r-old", "HEAD") == mf)
    check("follow log written", os.path.exists(os.environ[LOG_ENV]) and "followed" in open(os.environ[LOG_ENV]).read())

    def bare(name):
        p = tmp / name
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(p)], check=True, env=_env())
        return p

    def clone_of(rem, name):
        p = tmp / name
        subprocess.run(["git", "clone", "-q", str(rem), str(p)], check=True, env=_env())
        return p

    def run_git(p, *args):
        return subprocess.run(["git", "-C", str(p), *args], capture_output=True, text=True, env=_env(), timeout=120)

    # --- 通常の分岐で、 未 push の commit が古い状態へ戻しただけ (revert) の時: tree の一致で捨てない
    rv_remote = bare("rv.git")
    rv_a = tmp / "rv-a"
    init(rv_a)
    commit(rv_a, {"f.txt": "1\n"}, "r1")
    commit(rv_a, {"f.txt": "2\n"}, "r2")
    git(rv_a, "remote", "add", "origin", str(rv_remote))
    git(rv_a, "push", "-q", "-u", "origin", "main")
    rv_b = clone_of(rv_remote, "rv-b")
    commit(rv_b, {"f.txt": "1\n"}, "revert r2 locally (tree = r1)")
    commit(rv_a, {"other.txt": "x\n"}, "r3")
    git(rv_a, "push", "-q", "origin", "main")
    r = follow_repo(rv_b)
    check("unpushed revert on an ordinary divergence is not dropped (tree equals a commit of the shared history)",
          r.state == "diverged" and git(rv_b, "log", "-1", "--format=%s").startswith("revert r2"), f"{r.state} {r.line}")

    # --- 通常の分岐で、 手元だけの commit が volatile path の差分だけ: upstream が中身で進んでいても揃える (書き換えとは言わない)
    vo_remote = bare("vo.git")
    vo_a = tmp / "vo-a"
    init(vo_a)
    commit(vo_a, {"a.txt": "1\n", "status/x.json": "{}\n", ".rewrite-follow/ignore-paths": "status/\n"}, "v1")
    git(vo_a, "remote", "add", "origin", str(vo_remote))
    git(vo_a, "push", "-q", "-u", "origin", "main")
    vo_b = clone_of(vo_remote, "vo-b")
    commit(vo_b, {"status/x.json": '{"beat": 1}\n'}, "beat (volatile only)")
    v2 = commit(vo_a, {"a.txt": "2\n"}, "v2 real work upstream")
    git(vo_a, "push", "-q", "origin", "main")
    r = follow_repo(vo_b)
    check("volatile-only local commits on an ordinary divergence: aligned to upstream, reported as such",
          r.state == "followed" and r.how == "volatile-only" and rev(vo_b, "HEAD") == v2 and "volatile" in r.line and "書き換え" not in r.line,
          f"{r.state} {r.how} {r.line}")

    # --- 捨てられた履歴を clone 自身の reflog から知る (manifest なしの書き換え)
    os.environ["GIT_AUTHOR_DATE"] = os.environ["GIT_COMMITTER_DATE"] = "2000-01-03T00:00:00 +0000"
    dx_remote = bare("dx.git")
    dx = tmp / "dx-src"
    init(dx)
    d1 = commit(dx, {"a.txt": "one\n"}, "d1")
    d2 = commit(dx, {"secret.txt": "plaintext that the rewrite drops\n", "b.txt": "b\n"}, "d2")
    d3 = commit(dx, {"c.txt": "c\n"}, "d3")
    git(dx, "remote", "add", "origin", str(dx_remote))
    git(dx, "push", "-q", "-u", "origin", "main")
    s_merge, s_revive, s_force, s_branch, s_stub, s_head, s_local = (
        clone_of(dx_remote, n) for n in ("s-merge", "s-revive", "s-force", "s-branch", "s-stub", "s-head", "s-local"))
    commit(s_local, {"mine.txt": "local work\n"}, "local work on the old history")
    os.environ["GIT_AUTHOR_DATE"] = os.environ["GIT_COMMITTER_DATE"] = "2000-01-04T00:00:00 +0000"
    git(dx, "reset", "-q", "--hard", d1)
    commit(dx, {"b.txt": "b\n"}, "d2")
    commit(dx, {"c.txt": "c\n"}, "d3")
    e4 = commit(dx, {"e.txt": "e\n"}, "d4 after the rewrite")
    git(dx, "push", "-q", "--force", "origin", "main")          # manifest は置かない
    check("fixture: the rewrite shares its root with the old history and has no manifest",
          is_ancestor(dx, d1, e4) and not upstream_manifest_files(dx, "origin/main"))
    # (a) 古い履歴を merge した push
    git(s_merge, "fetch", "-q")
    git(s_merge, "merge", "-q", "--no-edit", "origin/main")
    dc, _cur = discarded_commits(s_merge, tracked_refs(s_merge, "origin"))
    check("discarded history is read from the clone's own reflog", set(dc) == {d2, d3}, " ".join(x[:7] for x in dc))
    ok, msgs = guard_stdin(s_merge, [f"refs/heads/main {rev(s_merge, 'HEAD')} refs/heads/main {e4}"], fetch=False)
    check("guard without a manifest: a merge of the discarded history is refused", not ok and "捨てられた履歴の commit" in " ".join(msgs), " ".join(msgs))
    check("discarded-object list is cached under the git dir", any((_common_dir(s_merge) / REMOVED_CACHE).iterdir()))
    ok2, msgs2 = guard_stdin(s_merge, [f"refs/heads/main {rev(s_merge, 'HEAD')} refs/heads/main {e4}"], fetch=False)
    check("guard: same verdict from the cache", not ok2 and msgs2 == msgs)
    # (b) 消した中身が新しい sha で戻る (rebase / cherry-pick の形)
    git(s_revive, "fetch", "-q")
    git(s_revive, "reset", "-q", "--hard", "origin/main")
    commit(s_revive, {"secret.txt": "plaintext that the rewrite drops\n"}, "revived under a fresh sha")
    ok, msgs = guard_stdin(s_revive, [f"refs/heads/main {rev(s_revive, 'HEAD')} refs/heads/main {e4}"], fetch=False)
    check("guard without a manifest: dropped content under a fresh sha is refused (blob only in the discarded history)",
          not ok and "tree / blob" in " ".join(msgs), " ".join(msgs))
    check("guard: the refusal names no path (a dropped file name can itself be the dropped content)",
          "secret.txt" not in " ".join(msgs)
          and "secret.txt" not in "".join(p.read_text() for p in (_common_dir(s_revive) / REMOVED_CACHE).iterdir()))
    commit(s_revive, {"secret.txt": "new, different content\n"}, "a new file with the same name is fine")
    git(s_revive, "reset", "-q", "--hard", "origin/main")
    commit(s_revive, {"fresh.txt": "new work\n"}, "legit")
    ok, msgs = guard_stdin(s_revive, [f"refs/heads/main {rev(s_revive, 'HEAD')} refs/heads/main {e4}"], fetch=False)
    check("guard without a manifest: a legitimate commit on the new history passes", ok and not msgs, " ".join(msgs))
    # (c) fetch していない clone からの force push: remote の今の先頭 (pre-push が渡す) が手元に無い → fetch してから判定
    ok, _m = guard_stdin(s_force, [f"refs/heads/main {d3} refs/heads/main {e4}"], remote="origin", fetch=False)
    check("precondition: without fetching, a never-fetched clone knows nothing (this is why the guard fetches)", ok)
    ok, msgs = guard_stdin(s_force, [f"refs/heads/main {d3} refs/heads/main {e4}"], remote="origin")
    check("guard: a force push from a never-fetched clone is refused (fetches when the remote tip is unknown)",
          not ok and GUARD_HEADLINE in " ".join(msgs), " ".join(msgs))
    # (d) fetch していない clone が古い履歴を新しい branch として push
    ok, msgs = guard_stdin(s_branch, [f"refs/heads/backup {d3} refs/heads/backup {ZERO}"], remote="origin")
    check("guard: pushing the old history as a new branch from a never-fetched clone is refused", not ok, " ".join(msgs))
    # (e) 本物の git push を stub 越しに (manifest の無い repo にも stub を置く)
    line = ensure_prepush(s_stub, only_with_manifest=False)
    check("ensure-prepush: installs without a manifest when asked", "置いた" in line and prepush_state(s_stub) == "stub", line)
    pr = run_git(s_stub, "push", "--force", "origin", "main")
    check("stub end to end: git push --force from a stale clone fails with the headline and the remote is untouched",
          pr.returncode != 0 and GUARD_HEADLINE in pr.stderr and rev(dx, "origin/main") == e4
          and git(dx, "ls-remote", "origin", "refs/heads/main").split()[0] == e4, pr.stderr[-300:])
    fake = tmp / "fake-engine.py"
    fake.write_text("import sys\nsys.exit(1)\n")
    s_fake = clone_of(dx_remote, "s-fake")
    commit(s_fake, {"g.txt": "g\n"}, "legit with a broken engine")
    hooks_dir(s_fake).mkdir(parents=True, exist_ok=True)
    (hooks_dir(s_fake) / "pre-push").write_text(stub_text(str(fake), str(s_fake)))
    os.chmod(hooks_dir(s_fake) / "pre-push", 0o755)
    pr = run_git(s_fake, "push", "origin", "main")
    check("stub: an engine failure (exit 1 without the headline) does not block the push, and says so",
          pr.returncode == 0 and "検査が走らなかった" in pr.stderr, pr.stderr[-300:])
    e5 = git(dx, "ls-remote", "origin", "refs/heads/main").split()[0]
    # (f) commit 側: 追従前の clone は HEAD が捨てられた履歴の上
    git(s_head, "fetch", "-q")
    ok, msg = head_violations(s_head)
    check("head check: a stale clone (fetched, not followed) is refused before committing", not ok and HEAD_HEADLINE in msg, msg)
    check("head check: a clone on the new history passes", head_violations(s_revive)[0])
    check("status reports the stale clone", status(s_head)["on_discarded_history"] and not status(s_revive)["on_discarded_history"])
    # (g) 止まった時の載せ直しの案内: 手元だけの commit を土台 (かつて remote に在った最後の commit) から運ぶ
    r = follow_repo(s_local)
    check("stopped with a local commit on the old history: the message carries a rebase --onto command",
          r.state == "stopped" and f"rebase --onto origin/main {d3[:12]}" in r.line, r.line)
    pr = run_git(s_local, "rebase", "-q", "--onto", "origin/main", d3)
    lh = rev(s_local, "HEAD")
    check("the suggested rebase carries only the local commit and the push passes the guard",
          pr.returncode == 0 and git(s_local, "rev-list", "--count", "origin/main..HEAD") == "1"
          and guard_stdin(s_local, [f"refs/heads/main {lh} refs/heads/main {rev(s_local, 'origin/main')}"], fetch=False)[0], pr.stderr[-200:])

    # --- 「捨てられた履歴にしか無い」 は厳密な差集合: 新しい履歴の途中の版にだけ在る object を含めない
    #     (旧 x2・x3 と新 y2・y3 が同じ blob を持ち、 新の先頭 y4 でその file が変わる = 境界の tree には無い)
    ex_remote = bare("ex.git")
    ex = tmp / "ex-src"
    init(ex)
    x1 = commit(ex, {"a.txt": "one\n"}, "x1")
    commit(ex, {"shared.txt": "kept by the rewrite\n", "secret.txt": "dropped by the rewrite\n"}, "x2")
    x3 = commit(ex, {"c.txt": "c\n"}, "x3")
    git(ex, "remote", "add", "origin", str(ex_remote))
    git(ex, "push", "-q", "-u", "origin", "main")
    shared_blob, secret_blob = git(ex, "rev-parse", f"{x3}:shared.txt"), git(ex, "rev-parse", f"{x3}:secret.txt")
    s_ex = clone_of(ex_remote, "s-ex")
    git(ex, "reset", "-q", "--hard", x1)
    commit(ex, {"shared.txt": "kept by the rewrite\n"}, "y2")
    commit(ex, {"c.txt": "c\n"}, "y3")
    y4 = commit(ex, {"shared.txt": "changed later\n"}, "y4")
    git(ex, "push", "-q", "--force", "origin", "main")
    git(s_ex, "fetch", "-q")
    naive = {l.split(" ", 1)[0] for l in git(s_ex, "rev-list", "--objects", x3, "^" + y4).splitlines()}
    check("fixture: `rev-list --objects OLD ^NEW` over-reports (a blob that lives in an inner commit of the new history)", shared_blob in naive)
    only = _objects_only_in(s_ex, [x3], [y4])
    check("objects only in the old history: exact difference (inner-commit blob excluded, dropped blob included)",
          shared_blob not in only and secret_blob in only)
    _dc, dobjs = discarded_objects(s_ex, tracked_refs(s_ex, "origin"))
    check("discarded objects exclude what the new history also holds", shared_blob not in dobjs and secret_blob in dobjs)
    git(s_ex, "reset", "-q", "--hard", "origin/main")
    commit(s_ex, {"shared.txt": "kept by the rewrite\n"}, "put the file back to an earlier version of the new history")
    ok, msgs = guard_stdin(s_ex, [f"refs/heads/main {rev(s_ex, 'HEAD')} refs/heads/main {y4}"], fetch=False)
    check("guard: restoring a version that the new history also holds is not refused", ok and not msgs, " ".join(msgs))

    # --- sweep: manifest の無い repo にも stub (まとめて 1 行)、 track された hooks dir と foreign は触らない、 kill switch
    root2 = tmp / "root2"
    root2.mkdir()
    for nm in ("p-plain", "p-tracked", "p-foreign"):
        subprocess.run(["git", "clone", "-q", str(dx_remote), str(root2 / nm)], check=True, env=_env())
    git(root2 / "p-tracked", "config", "core.hooksPath", ".githooks")
    (hooks_dir(root2 / "p-foreign")).mkdir(parents=True, exist_ok=True)
    (hooks_dir(root2 / "p-foreign") / "pre-push").write_text("#!/bin/sh\nexit 0\n")
    git(root2 / "p-foreign", "config", "rewritefollow.chain", "false")     # この clone は鎖にしない (clone ごとの opt-out)
    res = sweep(root2, fetch=False)
    check("sweep: by default a repo without a manifest gets no stub and no line",
          prepush_state(root2 / "p-plain") == "none" and not [pl for _r, pl in res if pl])
    res = sweep(root2, fetch=False, stub_all=True)
    lines = [pl for _r, pl in res if pl]
    check("sweep(stub_all): stub on a repo without a manifest, summarised in one line",
          prepush_state(root2 / "p-plain") == "stub" and len(lines) == 1 and "1 repo" in lines[0], " | ".join(lines))
    check("sweep(stub_all): a repo whose hooks are tracked (core.hooksPath inside the worktree) gets no stub file",
          not (root2 / "p-tracked" / ".githooks").exists() and prepush_state(root2 / "p-tracked") == "foreign")
    check("sweep(stub_all): a foreign pre-push in a clone that opted out of chaining is left alone, silently",
          "exit 0" in (hooks_dir(root2 / "p-foreign") / "pre-push").read_text() and prepush_state(root2 / "p-foreign") == "foreign")
    check("sweep(stub_all): second run is silent", not [pl for _r, pl in sweep(root2, fetch=False, stub_all=True) if pl])
    root3 = tmp / "root3"
    root3.mkdir()
    subprocess.run(["git", "clone", "-q", str(dx_remote), str(root3 / "q-plain")], check=True, env=_env())
    os.environ[STUB_ALL_ENV] = "1"
    sweep(root3, fetch=False)
    os.environ.pop(STUB_ALL_ENV, None)
    check("sweep: the env switch turns the all-repo stub on", prepush_state(root3 / "q-plain") == "stub")
    root5 = tmp / "root5"
    root5.mkdir()
    for nm in ("u-plain", "u-foreign"):
        subprocess.run(["git", "clone", "-q", str(dx_remote), str(root5 / nm)], check=True, env=_env())
    hooks_dir(root5 / "u-foreign").mkdir(parents=True, exist_ok=True)
    (hooks_dir(root5 / "u-foreign") / "pre-push").write_text("#!/bin/sh\nexit 0\n")
    os.chmod(hooks_dir(root5 / "u-foreign") / "pre-push", 0o755)
    placed, failed = ensure_prepush_all(root5)
    check("ensure_prepush_all: places on every repo with an upstream (a foreign hook is kept and chained), idempotent",
          placed == ["u-foreign", "u-plain"] and not failed and ensure_prepush_all(root5) == ([], [])
          and prepush_state(root5 / "u-foreign") == "stub", f"{placed} {failed}")

    # --- forbidden の生成: 旧 object が残る clone から、 旧世代にしか無い tree / blob を集める
    objs, have, total = forbidden_from_local(a_cont)
    check("forbidden_from_local: finds the old blob and counts coverage", old_blob_b2 in objs and have == total == len(gen.old_shas),
          f"{len(objs)} objs, {have}/{total}")
    check("forbidden_from_local: lists no commit", not (set(objs) & {o1, o2, o3, o0}))

    # --- push 範囲の中身の検査 (書き換えに依らない): git-crypt の対象の path の平文 / commit message の検査
    cr_remote = bare("cr.git")
    cr = tmp / "cr"
    init(cr)
    k1 = commit(cr, {".gitattributes": "secret/** filter=git-crypt diff=git-crypt\n", "a.txt": "a\n"}, "k1")
    git(cr, "remote", "add", "origin", str(cr_remote))
    git(cr, "push", "-q", "-u", "origin", "main")
    commit(cr, {"secret/plain.txt": "committed without the filter\n"}, "k2")
    ok, msgs = guard_stdin(cr, [f"refs/heads/main {rev(cr, 'HEAD')} refs/heads/main {k1}"], fetch=False)
    check("content: plaintext under a git-crypt path is refused at push (no rewrite involved)",
          not ok and "git-crypt の対象" in " ".join(msgs) and "secret/plain.txt" in " ".join(msgs), " ".join(msgs))
    os.environ[CRYPT_GUARD_ENV] = "0"
    check("content: the switch turns the git-crypt check off",
          guard_stdin(cr, [f"refs/heads/main {rev(cr, 'HEAD')} refs/heads/main {k1}"], fetch=False)[0])
    os.environ.pop(CRYPT_GUARD_ENV, None)
    git(cr, "reset", "-q", "--hard", k1)
    (cr / "secret").mkdir(exist_ok=True)
    (cr / "secret" / "enc.bin").write_bytes(CRYPT_MAGIC + b"\x00" + b"x" * 24)
    (cr / "secret" / "empty.txt").write_bytes(b"")
    (cr / "other.txt").write_text("plain is fine outside the path\n")
    git(cr, "add", "-A")
    git(cr, "commit", "-q", "-m", "k2 encrypted")
    ok, msgs = guard_stdin(cr, [f"refs/heads/main {rev(cr, 'HEAD')} refs/heads/main {k1}"], fetch=False)
    check("content: an encrypted blob, an empty file and a file outside the path pass", ok and not msgs, " ".join(msgs))
    fake_gate = tmp / "fake-msg-gate.py"
    fake_gate.write_text("import sys\nm = open(sys.argv[sys.argv.index('--commit-msg') + 1]).read()\n"
                         "if 'FORBIDDEN-TOKEN' in m:\n    print('" + MSG_GATE_HEADING + " fixture', file=sys.stderr)\n    sys.exit(1)\n"
                         "sys.exit(0)\n")
    os.environ[MSG_GATE_ENV] = str(fake_gate)
    k2 = rev(cr, "HEAD")
    bad_c = commit(cr, {"n.txt": "n\n"}, "a message that carries FORBIDDEN-TOKEN")
    commit(cr, {"m.txt": "m\n"}, "a fine message")
    ok, msgs = guard_stdin(cr, [f"refs/heads/main {rev(cr, 'HEAD')} refs/heads/main {k2}"], fetch=False)
    check("content: a commit message that the commit-msg gate refuses is refused at push (rebase / cherry-pick skip that hook)",
          not ok and "commit message" in " ".join(msgs) and bad_c[:7] in " ".join(msgs), " ".join(msgs))
    ok, msgs = guard_stdin(cr, [f"refs/heads/main {rev(cr, 'HEAD')} refs/heads/main {rev(cr, 'HEAD~1')}"], fetch=False)
    check("content: commits already on the remote are not re-checked", ok and not msgs, " ".join(msgs))
    os.environ[MSG_GATE_ENV] = "0"

    # --- 点呼: 別の machine の事実を、 最新を知っている clone が判定する
    reader = clone_of(dx_remote, "reader")
    git(reader, "fetch", "-q")
    check("judge: no rewrite trace in this clone → n/a (a fresh clone has no memory and no manifest)",
          judge_fact(reader, {"head": d3[:12], "up": d3[:12]})[0] == "n/a")
    memo = {}
    check("judge: a machine still on the discarded history and unaware of the rewrite → stale (not fetched)",
          judge_fact(s_merge, {"head": d3[:12], "up": d3[:12]}, _memo=memo) == ("stale", "未追従 (remote の書き換えをまだ fetch していない)"))
    check("judge: fetched but not followed → stale", judge_fact(s_merge, {"head": d3[:12], "up": e4[:12]}, _memo=memo)[0] == "stale")
    check("judge: on the new history → followed", judge_fact(s_merge, {"head": e4[:12], "up": e4[:12]}, _memo=memo)[0] == "followed")
    check("judge: unknown head on a known new upstream → unpushed",
          judge_fact(s_merge, {"head": "0123456789ab", "up": e4[:12]}, _memo=memo)[0] == "unpushed")
    check("judge: nothing known → unknown", judge_fact(s_merge, {"head": "0123456789ab", "up": "ba9876543210"}, _memo=memo)[0] == "unknown")
    git(s_merge, "branch", "-q", "keep-old", d3)
    check("stale_branches: a local branch that still carries the discarded history is named (the current branch is not)",
          stale_branches(s_merge) == ["keep-old"], str(stale_branches(s_merge)))
    check("stale_branches: silent in a clone with no rewrite trace", stale_branches(reader) == [])
    git(s_merge, "checkout", "-q", "-b", "keep-work", d3)
    commit(s_merge, {"only-here.txt": "work that exists nowhere else\n"}, "local only, on the discarded history")
    git(s_merge, "checkout", "-q", "main")
    bu = branch_unique(s_merge, stale_branches(s_merge))
    check("branch_unique: a plain copy of the discarded history holds nothing of its own; a branch with local work is counted",
          bu == {"keep-old": {"commits": 0, "blobs": 0}, "keep-work": {"commits": 1, "blobs": 1}}, json.dumps(bu))
    check("branch_unique: the result is cached under the git dir", (_common_dir(s_merge) / BRANCH_CACHE).is_file()
          and branch_unique(s_merge, ["keep-work"]) == {"keep-work": {"commits": 1, "blobs": 1}})

    # --- 履歴を書き換える push の前の点呼 (既定 branch の forced update の時だけ、 外の command に聞く)
    rg = clone_of(dx_remote, "rg")
    rg_tip = rev(rg, "HEAD")
    ff = commit(rg, {"ff.txt": "fast-forward\n"}, "ordinary commit on top")
    check("rewrites_default_branch: a fast-forward push is not a rewrite",
          rewrites_default_branch(rg, "origin", [["refs/heads/main", ff, "refs/heads/main", rg_tip]]) == [])
    git(rg, "reset", "-q", "--hard", rg_tip)
    git(rg, "commit", "-q", "--amend", "-m", "the tip reworded = a rewrite of the default branch")
    rw = rev(rg, "HEAD")
    row = ["refs/heads/main", rw, "refs/heads/main", rg_tip]
    check("rewrites_default_branch: a non-fast-forward update of the default branch is named",
          rewrites_default_branch(rg, "origin", [row]) == ["refs/heads/main"])
    check("rewrites_default_branch: a forced update of a work branch, and a new branch, are not",
          rewrites_default_branch(rg, "origin", [["refs/heads/topic", rw, "refs/heads/topic", rg_tip],
                                                 ["refs/heads/main", rw, "refs/heads/main", ZERO]]) == [])

    def hook(name, body, mode=0o755):
        hp = tmp / name
        hp.write_text("#!/bin/sh\n" + body)
        hp.chmod(mode)
        return str(hp)

    line = " ".join(row)
    check("ready gate: off (no command) → a rewriting push passes silently", guard_stdin(rg, [line], fetch=False) == (True, []))
    os.environ[READY_HOOK_ENV] = hook("ready-no", "echo \"NOT READY: $(basename \"$1\")\"; echo '  - mac-b: no report'; exit 1\n")
    ok, msgs = guard_stdin(rg, [line], fetch=False)
    check("ready gate: NOT READY stops the rewriting push, with the roll call and the way out",
          not ok and GUARD_HEADLINE in msgs[0] and "NOT READY: rg" in msgs[0] and "mac-b" in msgs[0] and READY_OVERRIDE_ENV in msgs[0],
          " | ".join(msgs))
    ok, msgs = guard_stdin(rg, [f"refs/heads/main {ff} refs/heads/main {rg_tip}"], fetch=False)
    check("ready gate: the command is not asked for a fast-forward push", ok and not msgs, " | ".join(msgs))
    os.environ[READY_OVERRIDE_ENV] = "1"
    ok, msgs = guard_stdin(rg, [line], fetch=False)
    check("ready gate: the override passes and says so", ok and len(msgs) == 1 and READY_OVERRIDE_ENV in msgs[0] and GUARD_HEADLINE not in msgs[0],
          " | ".join(msgs))
    os.environ.pop(READY_OVERRIDE_ENV)
    os.environ[READY_HOOK_ENV] = hook("ready-yes", "echo READY; exit 0\n")
    check("ready gate: READY passes silently", guard_stdin(rg, [line], fetch=False) == (True, []))
    os.environ[READY_HOOK_ENV] = hook("ready-crash", "echo boom >&2; exit 1\n")
    ok, msgs = guard_stdin(rg, [line], fetch=False)
    check("ready gate: a failing command (exit 1 without the headline) does not stop the push, and is reported",
          ok and len(msgs) == 1 and "点呼が走らなかった (rc=1)" in msgs[0], " | ".join(msgs))
    os.environ[READY_HOOK_ENV] = hook("ready-noexec", "exit 1\n", mode=0o644)
    ok, msgs = guard_stdin(rg, [line], fetch=False)
    check("ready gate: a command that cannot be started does not stop the push, and is reported",
          ok and len(msgs) == 1 and "点呼が走らなかった" in msgs[0], " | ".join(msgs))
    ev = recent_events()
    check("events: a roll call that could not run and an override are recorded, and read back by kind and repo",
          ev.get("ready-skip") == ["rg"] and ev.get("ready-override") == ["rg"], json.dumps(ev))
    check("events: a push that the stub let through unchecked (engine failure, exit 1 without the headline) is recorded by the stub itself",
          "s-fake" in ev.get("guard-error", []), json.dumps(ev))
    log_event("guard-error", "/somewhere/else/repo-x", "ValueError")
    check("events: only recent ones are returned, by repo name",
          "repo-x" in recent_events().get("guard-error", []) and recent_events(hours=-1) == {})
    # 本物の git push を stub 越しに: 備えが揃うまで remote の履歴は動かない / 揃えば通る
    ensure_prepush(rg, only_with_manifest=False)
    os.environ[READY_HOOK_ENV] = hook("ready-no-e2e", "echo 'NOT READY: fixture'; echo '  - mac-b: no stub'; exit 1\n")
    pr = run_git(rg, "push", "--force", "origin", "main")
    check("stub end to end: a push that rewrites the default branch is refused while a replica is not ready (remote untouched)",
          pr.returncode != 0 and GUARD_HEADLINE in pr.stderr and "mac-b" in pr.stderr
          and git(rg, "ls-remote", "origin", "refs/heads/main").split()[0] == rg_tip, pr.stderr[-300:])
    os.environ[READY_HOOK_ENV] = hook("ready-yes-e2e", "exit 0\n")
    pr = run_git(rg, "push", "--force", "origin", "main")
    check("stub end to end: the same push goes through once the roll call says ready",
          pr.returncode == 0 and git(rg, "ls-remote", "origin", "refs/heads/main").split()[0] == rw, pr.stderr[-300:])
    os.environ[READY_HOOK_ENV] = "0"
    facts = repo_facts(root2)
    check("repo_facts: one entry per repo with head / up / prepush",
          set(facts) == {"p-plain", "p-tracked", "p-foreign"} and facts["p-plain"]["prepush"] == "stub"
          and facts["p-foreign"]["prepush"] == "foreign" and len(facts["p-plain"]["head"]) == 12, json.dumps(facts))

    # --- remote 側の検出: hook を通らずに戻った旧世代を、 remote-tracking ref から読む
    aud_before = audit_repo(a_ok)
    check("audit: a clean remote yields nothing", aud_before == [], " | ".join(aud_before))
    if rev(a_merge, "HEAD") != mf and git_ok(a_merge, "cat-file", "-e", o0):
        git(a_merge, "push", "-q", str(remote), f"{o2}:refs/heads/leftover")  # 旧履歴を抱えた別 branch (main はまだきれい)
        git(a_ok, "fetch", "-q")
        aud = audit_repo(a_ok)
        check("audit: a remote branch carrying the old history is named (upstream itself still clean)",
              len(aud) == 1 and aud[0].startswith("🟠") and "leftover" in aud[0], " | ".join(aud))
        git(a_merge, "push", "-q", str(remote), "HEAD:main")                 # hook を持たない clone からの push を模す
        git(a_ok, "fetch", "-q")
        aud = audit_repo(a_ok)
        check("audit: old-generation commits back on upstream are reported",
              any(x.startswith("🔴") and "commit" in x for x in aud), " | ".join(aud))
        check("audit: the forbidden object back on upstream is reported", any(x.startswith("🔴") and "object" in x for x in aud), " | ".join(aud))
        check("audit: unchanged refs answer from the cache", audit_repo(a_ok) == aud and (_common_dir(a_ok) / AUDIT_CACHE).exists())
        root4 = tmp / "root4"
        root4.mkdir()
        subprocess.run(["git", "clone", "-q", str(remote), str(root4 / "r-back")], check=True, env=_env())
        res = sweep(root4, fetch=False)
        check("sweep: a resurrection on the remote surfaces as a stopped line", any(r.state == "stopped" and "🔴" in r.line for r, _ in res))

    # --- 別の pre-push hook が在る clone: 元の hook を残したまま、 検査を先に通す
    ch_remote = bare("ch.git")
    ch_src = tmp / "ch-src"
    init(ch_src)
    commit(ch_src, {"a.txt": "one\n"}, "h1")
    git(ch_src, "remote", "add", "origin", str(ch_remote))
    git(ch_src, "push", "-q", "-u", "origin", "main")

    def foreign_hook(repo, log, note="a hook that was here first", mode=0o755):
        hp = hooks_dir(repo) / "pre-push"
        hp.parent.mkdir(parents=True, exist_ok=True)
        hp.write_text(f'#!/bin/sh\n# {note}\n{{ echo "args=$*"; cat; }} >> "{log}"\nexit "${{CHAINED_RC:-0}}"\n')
        os.chmod(hp, mode)
        return hp

    cw = clone_of(ch_remote, "c-wrap")
    wlog = tmp / "chained-wrap.log"
    hk = foreign_hook(cw, wlog)
    line = ensure_prepush(cw, only_with_manifest=False)
    kept = hk.with_name("pre-push" + CHAIN_SUFFIX)
    check("chain: a foreign pre-push is kept next to the stub, and the clone counts as guarded",
          "残し" in line and prepush_state(cw) == "stub" and "was here first" in kept.read_text() and os.access(kept, os.X_OK), line)
    check("chain: idempotent", ensure_prepush(cw, only_with_manifest=False) == "")
    w1 = commit(cw, {"w.txt": "w\n"}, "ordinary work")
    pr = run_git(cw, "push", "origin", "main")
    body = wlog.read_text() if wlog.exists() else ""
    check("chain end to end: an ordinary push passes the check, then the original hook runs with the same arguments and stdin",
          pr.returncode == 0 and "args=origin " in body and f"refs/heads/main {w1} refs/heads/main" in body, pr.stderr[-300:] + body)
    commit(cw, {"w2.txt": "w\n"}, "more work")
    os.environ["CHAINED_RC"] = "1"
    pr = run_git(cw, "push", "origin", "main")
    os.environ.pop("CHAINED_RC")
    check("chain end to end: the original hook's refusal still stops the push",
          pr.returncode != 0 and git(cw, "ls-remote", "origin", "refs/heads/main").split()[0] == w1, pr.stderr[-200:])
    wlog.unlink()
    git(cw, "reset", "-q", "--hard", w1)
    git(cw, "commit", "-q", "--amend", "-m", "reworded = a rewrite of the default branch")
    os.environ[READY_HOOK_ENV] = hook("ready-no-chain", "echo 'NOT READY: fixture'; exit 1\n")
    pr = run_git(cw, "push", "--force", "origin", "main")
    os.environ[READY_HOOK_ENV] = "0"
    check("chain end to end: when the check refuses, the original hook is not run",
          pr.returncode != 0 and GUARD_HEADLINE in pr.stderr and not wlog.exists(), pr.stderr[-300:])
    foreign_hook(cw, wlog, note="reinstalled by its own tool")
    line = ensure_prepush(cw, only_with_manifest=False)
    check("chain: when the hook's own tool overwrites the stub, the next run wraps the new hook (the stale copy is replaced)",
          "残し" in line and "reinstalled by its own tool" in kept.read_text() and prepush_state(cw) == "stub", line)

    ce = clone_of(ch_remote, "c-noengine")
    elog = tmp / "chained-noengine.log"
    foreign_hook(ce, elog)
    ensure_prepush(ce, only_with_manifest=False, engine="/nonexistent/engine.py")
    commit(ce, {"e.txt": "e\n"}, "work in a clone whose engine is gone")
    pr = run_git(ce, "push", "origin", "main")
    check("chain end to end: with the engine missing the push is not checked, says so, and the original hook still runs",
          pr.returncode == 0 and "engine が無い" in pr.stderr and elog.exists() and "args=origin " in elog.read_text(), pr.stderr[-300:])
    check("stub: a push that went through unchecked is recorded for the periodic job to pick up",
          "c-noengine" in recent_events().get("guard-error", []), json.dumps(recent_events()))

    cn = clone_of(ch_remote, "c-noexec")
    nlog = tmp / "chained-noexec.log"
    nh = foreign_hook(cn, nlog, mode=0o644)          # 実行の印が無い hook = git は呼ばない
    ensure_prepush(cn, only_with_manifest=False)
    commit(cn, {"n.txt": "n\n"}, "work in a clone whose old hook was inactive")
    pr = run_git(cn, "push", "origin", "main")
    check("chain: a hook that git was ignoring (not executable) is not brought to life by the wrap",
          pr.returncode == 0 and not nlog.exists() and not os.access(nh.with_name("pre-push" + CHAIN_SUFFIX), os.X_OK), pr.stderr[-200:])

    pdf_installer = Path(__file__).resolve().parent.parent.parent / "templates" / "shared-project" / "pdf-publish" / "install-hook.sh"
    if pdf_installer.is_file():
        cp = clone_of(ch_remote, "c-pdf")
        subprocess.run(["sh", str(pdf_installer)], cwd=str(cp), capture_output=True, env=_env())
        php = hooks_dir(cp) / "pre-push"
        before = php.read_text() if php.exists() else ""
        line = ensure_prepush(cp, only_with_manifest=False)
        slot = php.with_name("pre-push" + PDFPUB_SLOT)
        check("pdf-publish hook: the stub goes into that hook's own chain slot; the hook itself is untouched",
              PDFPUB_MARK in before and "鎖の口" in line and slot.exists() and STUB_MARK in slot.read_text() and php.read_text() == before
              and prepush_state(cp) == "stub" and ensure_prepush(cp, only_with_manifest=False) == "", line)
        tip_p = git(cp, "ls-remote", "origin", "refs/heads/main").split()[0]
        git(cp, "commit", "-q", "--amend", "-m", "reworded through the pdf-publish hook")
        os.environ[READY_HOOK_ENV] = hook("ready-no-pdf", "echo 'NOT READY: fixture'; exit 1\n")
        pr = run_git(cp, "push", "--force", "origin", "main")
        os.environ[READY_HOOK_ENV] = "0"
        check("pdf-publish hook end to end: the check runs through the chain slot and its refusal stops the push",
              pr.returncode != 0 and GUARD_HEADLINE in pr.stderr and git(cp, "ls-remote", "origin", "refs/heads/main").split()[0] == tip_p,
              pr.stderr[-300:])
        ct = clone_of(ch_remote, "c-tracked-pdf")
        git(ct, "config", "core.hooksPath", ".githooks")
        subprocess.run(["sh", str(pdf_installer)], cwd=str(ct), capture_output=True, env=_env())
        git(ct, "add", ".githooks/pre-push")
        git(ct, "commit", "-q", "-m", "the repo tracks its hooks dir")
        line = ensure_prepush(ct, only_with_manifest=False)
        check("pdf-publish hook in a tracked hooks dir: the slot file is placed and kept out of git status (info/exclude)",
              (ct / ".githooks" / ("pre-push" + PDFPUB_SLOT)).exists() and prepush_state(ct) == "stub"
              and git(ct, "status", "--porcelain") == "", line + " | " + git(ct, "status", "--porcelain"))
    if pdf_installer.is_file():
        cl = clone_of(ch_remote, "c-wrap-then-pdf")
        llog = tmp / "chained-then-pdf.log"
        foreign_hook(cl, llog)
        ensure_prepush(cl, only_with_manifest=False)                         # まず包む (LFS などの hook が先に在った clone)
        subprocess.run(["sh", str(pdf_installer)], cwd=str(cl), capture_output=True, env=_env())   # 後から pdf-publish が入る
        commit(cl, {"l0.txt": "l\n"}, "work right after the second tool was installed (before the periodic job looks)")
        pr0 = run_git(cl, "push", "origin", "main")
        check("wrapped first, pdf-publish installed later: the original hook still runs at once (the moved stub finds the kept hook under its old name)",
              pr0.returncode == 0 and llog.exists() and "args=origin " in llog.read_text(), pr0.stderr[-200:])
        llog.unlink()
        line = ensure_prepush(cl, only_with_manifest=False)
        commit(cl, {"l.txt": "l\n"}, "work after both tools were installed")
        pr = run_git(cl, "push", "origin", "main")
        check("wrapped first, pdf-publish installed later: the kept original hook is re-attached to the stub's new name and still runs",
              "付け替えた" in line and prepush_state(cl) == "stub" and pr.returncode == 0 and llog.exists() and "args=origin " in llog.read_text(),
              line + " | " + pr.stderr[-200:])
    ck = clone_of(ch_remote, "c-tracked-plain")
    git(ck, "config", "core.hooksPath", ".githooks")
    check("tracked hooks dir without a pre-push: nothing is written into the worktree (a later pre-push of the repo's own would collide)",
          "置けない" in ensure_prepush(ck, only_with_manifest=False) and not (ck / ".githooks").exists() and prepush_state(ck) == "foreign")

    # --- reflog の記憶が消えた後も、 この clone の記録 (cache の file) で止める / remote 側で検出する (manifest なし)
    os.environ["GIT_AUTHOR_DATE"] = os.environ["GIT_COMMITTER_DATE"] = "2000-01-05T00:00:00 +0000"
    mm_remote = bare("mm.git")
    mm = tmp / "mm-src"
    init(mm)
    m1 = commit(mm, {"a.txt": "one\n"}, "m1")
    commit(mm, {"secret.txt": "content the rewrite removes\n", "b.txt": "b\n"}, "m2")
    m3 = commit(mm, {"c.txt": "c\n"}, "m3")
    git(mm, "remote", "add", "origin", str(mm_remote))
    git(mm, "push", "-q", "-u", "origin", "main")
    mm_c = clone_of(mm_remote, "mm-clone")           # 書き換えの前から在る clone
    mm_o = clone_of(mm_remote, "mm-outside")         # 検査を持たない clone (fleet の外)
    os.environ["GIT_AUTHOR_DATE"] = os.environ["GIT_COMMITTER_DATE"] = "2000-01-06T00:00:00 +0000"
    git(mm, "reset", "-q", "--hard", m1)
    commit(mm, {"b.txt": "b\n"}, "m2")
    n3 = commit(mm, {"c.txt": "c\n"}, "m3")
    git(mm, "push", "-q", "--force", "origin", "main")
    git(mm_c, "fetch", "-q")
    repo_root_mm = tmp / "root-mm"
    repo_root_mm.mkdir()
    check("memory: nothing is remembered before the periodic job has looked", remembered_discarded(mm_c) == set())
    stale_branches(mm_c)                              # 定期 job の経路 (repo_facts → stale_branches)
    mem = remembered_discarded(mm_c)
    check("memory: the periodic job writes the discarded history down while the reflog still knows it", m3 in mem and n3 not in mem and len(mem) >= 3,
          str(len(mem)))
    lg = _common_dir(mm_c) / "logs" / "refs" / "remotes" / "origin" / "main"
    lg.write_text("")                                 # reflog の entry が expire した後を模す
    check("memory fixture: with the reflog gone the clone no longer derives the discarded history",
          discarded_commits(mm_c, tracked_refs(mm_c, "origin"))[0] == [])
    git(mm_c, "merge", "-q", "--no-edit", "origin/main")
    ok, msgs = guard_stdin(mm_c, [f"refs/heads/main {rev(mm_c, 'HEAD')} refs/heads/main {n3}"], fetch=False)
    check("memory: after the reflog expired, a push that carries the discarded history is still refused (no manifest)",
          not ok and "以前に" in " ".join(msgs) and "secret.txt" not in " ".join(msgs), " ".join(msgs))
    git(mm_c, "reset", "-q", "--hard", "origin/main")
    commit(mm_c, {"new.txt": "legit\n"}, "legit work on the new history")
    ok, msgs = guard_stdin(mm_c, [f"refs/heads/main {rev(mm_c, 'HEAD')} refs/heads/main {n3}"], fetch=False)
    check("memory: ordinary work on the new history passes", ok and not msgs, " ".join(msgs))
    git(mm_c, "reset", "-q", "--hard", "origin/main")
    same = commit(mm_c, {"elsewhere.txt": "content the rewrite removes\n"}, "a new file whose content equals a removed one")
    blob = git(mm_c, "rev-parse", f"{same}:elsewhere.txt")
    row_mm = [f"refs/heads/main {same} refs/heads/main {rev(mm_c, 'origin/main')}"]
    ok, msgs = guard_stdin(mm_c, row_mm, fetch=False)
    check("allow: removed content coming back under a new path is refused, and the message names the object and the way out",
          not ok and blob[:12] in " ".join(msgs) and ALLOW_ENV in " ".join(msgs), " ".join(msgs))
    os.environ[ALLOW_ENV] = blob[:10]
    ok, msgs = guard_stdin(mm_c, row_mm, fetch=False)
    os.environ.pop(ALLOW_ENV)
    check("allow: naming that object lets this push through, says so, and leaves a record",
          ok and len(msgs) == 1 and ALLOW_ENV in msgs[0] and "mm-clone" in recent_events().get("guard-allow", []), " ".join(msgs))
    os.environ[ALLOW_ENV] = "0000000"
    ok, _m = guard_stdin(mm_c, row_mm, fetch=False)
    os.environ.pop(ALLOW_ENV)
    check("allow: naming some other object does not open the gate", not ok)
    git(mm_c, "reset", "-q", "--hard", "origin/main")
    check("memory audit: a clean remote yields nothing", audit_repo(mm_c) == [], " | ".join(audit_repo(mm_c)))
    git(mm_o, "pull", "-q", "--no-rebase", "--no-edit", "origin", "main")     # 外の clone が古い履歴を merge して push する
    git(mm_o, "push", "-q", "origin", "main")
    git(mm_c, "fetch", "-q")
    aud = audit_repo(mm_c)
    check("memory audit: discarded history that came back through a clone without the check is reported (no manifest)",
          any(x.startswith("🔴") and "戻っている" in x for x in aud), " | ".join(aud))
    git(mm_c, "merge", "-q", "--ff-only", "origin/main")
    commit(mm_c, {"after.txt": "work on top of what is now on the remote\n"}, "work after the remote took the old history back")
    ok, msgs = guard_stdin(mm_c, [f"refs/heads/main {rev(mm_c, 'HEAD')} refs/heads/main {rev(mm_c, 'origin/main')}"], fetch=False)
    check("memory: once the remote itself holds those objects again, a push on top is not refused for them", ok, " ".join(msgs))

    # --- 検収で出た 3 点: 誰でも作れる object / 止まった object を名指しで通す道 / 自分の path を使う hook
    cache_dir = _common_dir(mm_c) / REMOVED_CACHE
    with open(sorted(cache_dir.iterdir())[0], "a", encoding="ascii") as f:
        f.write("".join(x + "\n" for x in sorted(TRIVIAL_OBJECTS)))
    git(mm_c, "reset", "-q", "--hard", "origin/main")
    emp = commit(mm_c, {"empty.txt": "", "newline.txt": "\n"}, "an empty file and a one-newline file")
    ok, msgs = guard_stdin(mm_c, [f"refs/heads/main {emp} refs/heads/main {rev(mm_c, 'origin/main')}"], fetch=False)
    check("trivial objects: an empty file or a single newline is never treated as removed content, even if the record lists them",
          ok and not (remembered_discarded(mm_c) & TRIVIAL_OBJECTS), " ".join(msgs))

    cs = clone_of(ch_remote, "c-selfpath")
    sp = hooks_dir(cs) / "pre-push"
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text('#!/bin/sh\n. "$(dirname "$0")/_/helper.sh"\nexit 0\n')
    os.chmod(sp, 0o755)
    line = ensure_prepush(cs, only_with_manifest=False)
    check("self-path hook: a hook that finds its neighbours through $0 is not wrapped (wrapping would rename it)",
          "置けない" in line and "$0" in line and 'dirname "$0"' in sp.read_text() and prepush_state(cs) == "foreign"
          and not sp.with_name("pre-push" + CHAIN_SUFFIX).exists(), line)
    cu = clone_of(ch_remote, "c-unwrap")
    foreign_hook(cu, tmp / "unwrap.log")
    ensure_prepush(cu, only_with_manifest=False)
    kept_u = hooks_dir(cu) / ("pre-push" + CHAIN_SUFFIX)
    kept_u.write_text('#!/bin/sh\n. "$(dirname "$0")/_/helper.sh"\nexit 0\n')     # 以前の版が、 そういう hook を包んでしまった状態
    line = ensure_prepush(cu, only_with_manifest=False)
    check("self-path hook: one that an earlier version had already wrapped is put back as it was",
          "元に戻した" in line and 'dirname "$0"' in (hooks_dir(cu) / "pre-push").read_text() and not kept_u.exists()
          and prepush_state(cu) == "foreign", line)

    # --- 鍵の付け替え: 古い鍵で unlock 済みの clone は、 新しい鍵の履歴に追従しない (作業 tree を壊さない)
    if shutil.which("git-crypt"):
        kr = tmp / "crypt-remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(kr)], check=True, env=_env())
        ka = tmp / "crypt-a"
        init(ka)
        subprocess.run(["git-crypt", "init"], cwd=str(ka), capture_output=True, check=True)
        commit(ka, {".gitattributes": "s.txt filter=git-crypt diff=git-crypt\n", "s.txt": "v1\n"}, "k1")
        git(ka, "remote", "add", "origin", str(kr))
        git(ka, "push", "-q", "origin", "main")
        old_key = tmp / "crypt-old.key"
        subprocess.run(["git-crypt", "export-key", str(old_key)], cwd=str(ka), capture_output=True, check=True)
        kb = tmp / "crypt-b"
        subprocess.run(["git", "clone", "-q", str(kr), str(kb)], check=True, env=_env())
        subprocess.run(["git-crypt", "unlock", str(old_key)], cwd=str(kb), capture_output=True, check=True)
        plain = (ka / "s.txt").read_text()
        subprocess.run(["git-crypt", "lock"], cwd=str(ka), capture_output=True, check=True)
        shutil.rmtree(Path(git(ka, "rev-parse", "--absolute-git-dir")) / "git-crypt")
        subprocess.run(["git-crypt", "init"], cwd=str(ka), capture_output=True, check=True)
        (ka / "s.txt").write_text(plain)
        git(ka, "add", "--renormalize", ".")
        git(ka, "commit", "-q", "--amend", "-m", "k1 rewritten")
        git(ka, "push", "-q", "-f", "origin", "main")
        kmap = tmp / "crypt.commit-map"
        kmap.write_text("old new\n" + git(kb, "rev-parse", "HEAD") + " " + git(ka, "rev-parse", "HEAD") + "\n")
        r = follow_repo(kb, cli_globs=[str(kmap)], fetch=True, log=False)
        check("key rotated: a clone unlocked with the old key is stopped before reset (worktree intact)",
              r.state == "stopped" and "鍵" in r.line and (kb / "s.txt").read_text() == "v1\n"
              and git(kb, "status", "--porcelain") == "", r.line)
    else:
        print("  skip: key-rotation case (git-crypt not installed)")

    # --- forced-update の後の通常の分岐 (manifest なし): 追従した clone の新しい世代の上の手元の commit + upstream の前進は diverged。
    #     捨てられた世代の上の手元の commit は stopped (forced-update の記録が reflog に在るだけでは止めない)
    fu_remote = tmp / "fu.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(fu_remote)], check=True, env=_env())
    fu_src = tmp / "fu-src"
    init(fu_src)
    commit(fu_src, {"p.txt": "1\n"}, "p1")
    commit(fu_src, {"p.txt": "2\n"}, "p2")
    git(fu_src, "remote", "add", "origin", str(fu_remote))
    git(fu_src, "push", "-q", "origin", "main")

    def fu_clone(name):
        p = tmp / name
        subprocess.run(["git", "clone", "-q", str(fu_remote), str(p)], check=True, env=_env())
        return p

    fu_new = fu_clone("fu-follows")        # 書き換えに追従してから手元で commit する
    fu_old = fu_clone("fu-stays-old")      # 捨てられた世代のまま手元で commit する
    fu_rw = tmp / "fu-rw"                  # manifest を置かない書き換え (message だけ変えて force push)
    init(fu_rw)
    commit(fu_rw, {"p.txt": "1\n"}, "p1 (rewritten)")
    commit(fu_rw, {"p.txt": "2\n"}, "p2 (rewritten)")
    git(fu_rw, "push", "-q", "--force", str(fu_remote), "main:main")
    r = follow_repo(fu_new)
    check("forced-update fixture: the clone follows the rewrite via tree", r.state == "followed", r.line)
    check("forced-update fixture: the forced update is in the reflog", forced_update_seen(fu_new, "origin/main"))
    commit(fu_new, {"mine.txt": "local\n"}, "local commit on the new generation")
    commit(fu_old, {"mine.txt": "local\n"}, "local commit on the discarded generation")
    fu_adv = fu_clone("fu-advance")
    commit(fu_adv, {"q.txt": "upstream advance\n"}, "upstream advance")
    git(fu_adv, "push", "-q", "origin", "main")
    r = follow_repo(fu_new)
    check("ordinary divergence after a forced update (no manifest): diverged, not stopped as a rewrite",
          r.state == "diverged" and "書き換えられ" not in r.line, r.line)
    check("ordinary divergence: the line counts both sides and points at the replay recipe",
          "手元にしか無い commit 1 (最古" in r.line and "upstream にだけ在る commit 1" in r.line
          and "#ordinary-divergence-replay" in r.line, r.line)
    check("ordinary divergence after a forced update: forced_update_trace is False",
          not forced_update_trace(fu_new, rev(fu_new, "HEAD"), rev(fu_new, "origin/main"), "origin/main"))
    check("ordinary divergence after a forced update: ref untouched",
          git(fu_new, "log", "-1", "--format=%s") == "local commit on the new generation")
    r = follow_repo(fu_old)
    check("local commit on the discarded generation (no manifest): stopped as a rewrite",
          r.state == "stopped" and "書き換えられ" in r.line, r.line)
    check("local commit on the discarded generation: ref untouched",
          git(fu_old, "log", "-1", "--format=%s") == "local commit on the discarded generation")

    print(f"selftest: {'PASS' if not fails else 'FAIL'} ({len(fails)} failing)")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(_selftest())
