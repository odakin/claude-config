#!/usr/bin/env python3
"""surface-spawn-results.py — file と token で渡した子 session の完了を、 人が次に居るどの session にも自動で届ける受け取りの道具。

受け渡しの約束の正本 = conventions/multi-session-coordination.md#spawn-handoff-token-return
(marker の mint・更新・consume の規律 = 同 #return-signal-economy、 締めでの集め方 = closing-sweep.md#collect-from-delegates)。

= なぜ在るか:
  独立した session に作業を渡したとき、 結果を呼び元に返す live-push (子が token で親の session を
  探して message を送る) は、 親が token を chat の本文に出していることが前提で、 spec (tool の引数)
  に入れただけでは検索に掛からない。 落ちると、 結果は決まった path に在るのに、 人が親の session
  を手で探すことになる (実測)。 「人が file を読みに行けばよい」 は機械から人へ手間を移す方向で逆。
  正しい形 = 結果が人の目に勝手に届く:
    1. 子は完了時に成果物を決まった path に書き、 marker を 1 つ落とす (`--record` 1 発)。
    2. 本 script が marker を拾い、 SessionStart hook・dashboard から「結果が届いた、 場所はここ」
       を出す (file を読む script の操作 = model の chat 出力に依らない)。
    3. live-push は効いたときの bonus。 落ちても本 surface が拾う。
  該当 0 件なら沈黙、 全 path で fail-open。

marker の契約 (子が `--record` で書く):
  <marker dir>/<token>.yaml:
    token:       <spec の token (= 一意の file 名)>
    status:      done | partial | failed
    task:        <何のために渡されたか、 人が読む 1 行>
    result_path: <成果物の決まった path (base からの相対か絶対)>
    summary:     <要旨 1-3 行>
    spawned_by:  <親の題、 任意>
    created:     <ISO8601、 --record が付ける。 同じ token の再 record では保つ>
    consumed:    false   # 受け取ったら true (--consume)。 false の間は出し続ける

  ⚠️ marker は「届いた」 を残す通知で、 報告書ではない: summary が 400 字を超えたら --record を拒む。
  ⚠️ 成果物が (a) 機密として宣言された作業 dir の下か (b) 本文が機密索引に一致するとき、 task・summary・
     result_path を中立な文言に置き換えて記録し、 落とした内容を呼び出し元に伝える (所在と内容は chat で
     人に口頭で伝える)。 判定は check-confidential-leak.py --match-path に委ねる。 明示的に残すなら
     --not-confidential。 判定不能は縛らない (fail-open)。 指紋の leak guard は逐語の写ししか捕まえず、
     要約は一致 0 になる (実測) ので、 この経路は中身の検査でなく schema で縛る。

設定 (個人層の配置は engine に書かない = 呼び元の shim か環境変数で渡す):
  CLAUDE_SPAWN_RESULTS_DIR    marker dir (既定 ~/.claude/spawn-results = この機械だけ。 複数の機械で
                              受け取るなら git で同期する dir を渡す)
  CLAUDE_SPAWN_RESULTS_BASE   相対の result_path を解決する基点 (既定 = この repo の親 dir = <base>)
  CLAUDE_SPAWN_RESULTS_CMD    surface の「受け取ったら」 行に出す起動の形 (既定 = この file を python3 で)
  CLAUDE_CONFIDENTIAL_LEAK_ENGINE  機密の判定に使う道具 (既定 = 同じ dir の check-confidential-leak.py)
  CLAUDE_LEAK_SOURCES         機密として宣言された作業 dir の一覧 (既定 ~/.claude/leak-pattern-sources.txt)
  CLAUDE_SPAWN_RESULTS_CAP    surface に出す上限 (既定 12)

使い方:
  python3 surface-spawn-results.py --record --token T --status done \\
      --task "SoT 監査" --result-path "<repo>/plans/...findings.md" --summary "監査完了。3 件 drift 検出。"
  python3 surface-spawn-results.py                 # surface (hook / dashboard が呼ぶ既定)
  python3 surface-spawn-results.py --consume T     # 受け取り済みにする
  python3 surface-spawn-results.py --list          # consumed を含む全件
  python3 surface-spawn-results.py --audit         # 既存 marker の棚卸し (機密一致があれば exit 1)
  python3 surface-spawn-results.py --neutralize T  # 後から機密と分かった marker の中身を中立にする
  python3 surface-spawn-results.py --selftest
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _yaml_safe_load(stream):  # yaml.safe_load と同じ結果を C 版 (libyaml) で返す = 約 10 倍速
    import yaml
    return yaml.load(stream, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))


def _default_dir():
    return Path(os.environ.get("CLAUDE_SPAWN_RESULTS_DIR")
                or Path.home() / ".claude" / "spawn-results")


def _base():
    b = os.environ.get("CLAUDE_SPAWN_RESULTS_BASE")
    return Path(os.path.expanduser(b)) if b else HERE.parent.parent


def _consume_cmd():
    return os.environ.get("CLAUDE_SPAWN_RESULTS_CMD") or f"python3 {Path(__file__).resolve()}"


def _leak_engine():
    e = os.environ.get("CLAUDE_CONFIDENTIAL_LEAK_ENGINE")
    return Path(os.path.expanduser(e)) if e else HERE / "check-confidential-leak.py"


CAP = int(os.environ.get("CLAUDE_SPAWN_RESULTS_CAP", "12"))

_EMOJI = {"done": "✅", "partial": "⚠️", "failed": "🆘"}
_WORD = {"done": "完了", "partial": "途中", "failed": "失敗"}


def _load_yaml(path):
    """marker を dict で返す。 壊れていたら None (= fail-open で 1 件 skip)。"""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            d = _yaml_safe_load(fh)
        return d if isinstance(d, dict) else None
    except Exception:
        # yaml 不在 or 破損 → 最小限の tolerant parse (key: value の 1 行物のみ)
        try:
            d = {}
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                if ":" in line and not line.startswith((" ", "\t", "#")):
                    k, _, v = line.partition(":")
                    d[k.strip()] = v.strip().strip("'\"")
            return d or None
        except Exception:
            return None


def _markers(d):
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.yaml")):
        m = _load_yaml(p)
        if not m or not m.get("token"):
            continue
        m["_file"] = p
        out.append(m)
    return out


def _truthy(v):
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _created_key(m):
    c = str(m.get("created", "") or "")
    return c or "0000"


def _first_line(s):
    s = str(s or "").strip()
    return s.splitlines()[0] if s else ""


def _handoff_path(rp):
    """result_path が dir で HANDOFF.md を含めばその path、 なければ ''。
    (封じた sandbox の worker が残す受け渡しの束 = 再利用 script / 一般則 / 参照 / 進め方の改善案。
    受け取る側の入口なので surface で存在を示す。 判定不能は '' = 表示しないだけ。)"""
    try:
        p = Path(os.path.expanduser(str(rp or "")))
        if p.is_dir() and (p / "HANDOFF.md").is_file():
            return str(p / "HANDOFF.md")
    except Exception:
        pass
    return ""


def surface(d=None, cap=CAP):
    """surface text を返す (= 未 consume の done/partial/failed)。 該当なしは ''。"""
    d = d if d is not None else _default_dir()
    pending = [m for m in _markers(d) if not _truthy(m.get("consumed", False))]
    if not pending:
        return ""
    # failed → partial → done、 その中で created 昇順 (古い未処理を上に)
    order = {"failed": 0, "partial": 1, "done": 2}
    pending.sort(key=lambda m: (order.get(str(m.get("status", "done")), 2), _created_key(m)))
    lines = []
    for m in pending[:cap]:
        st = str(m.get("status", "done"))
        emoji = _EMOJI.get(st, "✅")
        word = _WORD.get(st, "完了")
        task = str(m.get("task") or m.get("token"))
        rp = str(m.get("result_path") or "(result_path 未記載)")
        date = _created_key(m)[:10]
        summ = _first_line(m.get("summary"))
        line = f"{emoji} [{task}] {word} → {rp}"
        if date and date != "0000":
            line += f"  ({date})"
        if summ:
            line += f"\n      ↳ {summ}"
        hp = _handoff_path(rp)
        if hp:
            line += (f"\n      📎 HANDOFF.md あり → collect 後に読む (再利用 script / 一般則 / 参照 / "
                     f"process 改善案 = hoist station + retro の入口): {hp}")
        lines.append(line)
    if len(pending) > cap:
        lines.append(f"… 他 {len(pending) - cap} 件 (--list で全件)")
    lines.append(f"   受け取ったら: {_consume_cmd()} --consume <token>")
    return "\n".join(lines)


# ---- marker schema の縛り -------------------------------------------------
# marker は「届いた」 を残す通知であって報告書ではない (= 上の契約の ⚠️)。 summary が payload を
# 運び始めると、 marker dir を remote 付きの repo に置いている人の機密が載る (実測 = 要約は
# 言い換えなので、 逐語の写しを探す leak guard では一致 0)。 この経路は schema で縛る。
SUMMARY_MAX = 400          # marker は通知。 これを超える要旨は result_path に置く
CONFIDENTIAL_NOTE = "（機密のため marker には記録しない。所在と内容は chat で口頭伝達）"
CONFIDENTIAL_TASK = "機密作業（依頼元セッションからの spawn）"


def _confidential_dirs():
    """機密として宣言された作業 dir (= leak guard と同じ pointer を正本にする)。"""
    ptr = Path(os.environ.get("CLAUDE_LEAK_SOURCES")
               or Path.home() / ".claude" / "leak-pattern-sources.txt")
    out = []
    if ptr.is_file():
        for line in ptr.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                out.append(Path(os.path.expanduser(line)).resolve())
    return out


def classify_result_path(result_path):
    """機密扱いにすべき理由を返す。 通常の成果物なら None。"""
    rp = str(result_path or "").strip()
    if not rp:
        return None
    p = Path(os.path.expanduser(rp))
    if not p.is_absolute():
        return None                       # base からの相対 = 通常の成果物
    try:
        p = p.resolve()
    except OSError:
        return None
    for d in _confidential_dirs():
        if d == p or d in p.parents:
            return "機密として宣言された作業 dir 配下"
    # 成果物の中身が機密索引に一致するか (= sandbox でも中身で判定する。 path が base の外かどうかで
    # 一律に決めると、 sandbox worker の HANDOFF 表示など正当な機能まで潰れる)。 engine は subprocess
    # で呼ぶ (= importlib で古い .pyc を掴む事故を避ける)。
    engine = _leak_engine()
    if engine.is_file():
        try:
            r = subprocess.run([sys.executable, str(engine), "--match-path", str(p)],
                               capture_output=True, timeout=60)
            if r.returncode == 1:
                return "成果物の本文が機密索引に一致した"
        except Exception:
            pass                          # 判定不能は縛らない (= fail-open)
    return None


def record(d, token, status, task, result_path, summary, spawned_by,
           allow_confidential_text=False, notes=None):
    notes = notes if notes is not None else []
    if len(str(summary or "")) > SUMMARY_MAX:
        raise ValueError(
            f"summary が {len(str(summary))} 字 (上限 {SUMMARY_MAX})。 marker は「届いた」 を"
            " 残す通知で、 報告書ではない。 要旨は result_path の成果物に書き、 marker には"
            " 1-3 行の gist だけ残すこと。")
    reason = classify_result_path(result_path)
    if reason and not allow_confidential_text:
        notes.append(f"機密扱いにした ({reason})")
        notes.append(f"  marker から外した result_path: {result_path}")
        if str(summary or "").strip():
            notes.append("  marker から外した summary は、 chat 本文で人間に伝えること")
        notes.append("  意図的に本文を残すなら --not-confidential を明示する")
        result_path = ""
        summary = CONFIDENTIAL_NOTE
        task = CONFIDENTIAL_TASK
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{token}.yaml"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # 既存 created は保つ (= 再 record で時刻を上書きしない)
    created = now
    if f.exists():
        old = _load_yaml(f) or {}
        created = old.get("created") or now

    def esc(s):
        return str(s or "").replace("\\", "\\\\").replace('"', '\\"')

    body = (
        f'token: "{esc(token)}"\n'
        f'status: {status}\n'
        f'task: "{esc(task)}"\n'
        f'result_path: "{esc(result_path)}"\n'
        f'summary: |\n'
    )
    for ln in str(summary or "").splitlines() or [""]:
        body += f"  {ln}\n"
    if spawned_by:
        body += f'spawned_by: "{esc(spawned_by)}"\n'
    body += f'created: "{created}"\n'
    body += "consumed: false\n"
    f.write_text(body, encoding="utf-8")
    return f


def _resolve_result(rp):
    """marker の result_path を実 path に解決。 見つからなければ None。"""
    rp = str(rp or "").strip()
    if not rp:
        return None
    q = Path(os.path.expanduser(rp))
    if q.is_absolute():
        return q if q.exists() else None
    base = _base()
    try:
        cands = [base] + sorted(x for x in base.iterdir() if x.is_dir())
    except OSError:
        return None
    for b in cands:
        q = b / rp
        try:
            q.stat()  # exists() は版で読めない dir の扱いが違う (3.12 までは PermissionError、 3.14 は False)
        except OSError:
            continue  # 基点の下の読めない dir (他人の 700 の dir など) は飛ばして次を見る。 無い path も同じ
        return q
    return None


def audit(d):
    """既存 marker を現行基準で棚卸しする (読むだけ)。

    - 機密一致 … 成果物の本文が機密索引に一致する marker (= 本来 marker に残せない)
    - 上限超え … summary が SUMMARY_MAX 字超 (= marker の報告書化)
    - 未解決   … 成果物が現存せず中身を検査できない (= 判定不能をそう申告する)
    戻り値は機密一致の本数 (= 呼び出し元の exit code)。
    """
    engine = _leak_engine()
    conf, over, unres, targets, n = [], [], [], [], 0
    for f in sorted(Path(d).glob("*.yaml")):
        y = _load_yaml(f) or {}
        n += 1
        if len(str(y.get("summary") or "")) > SUMMARY_MAX:
            over.append((f.name, len(str(y.get("summary") or ""))))
        target = _resolve_result(y.get("result_path"))
        if target is None:
            unres.append((f.name, str(y.get("result_path") or "(空)")))
            continue
        targets.append((f.name, str(target)))
    if targets and engine.is_file():
        try:
            r = subprocess.run([sys.executable, str(engine), "--match-paths"],
                               input="\n".join(t for _n, t in targets),
                               capture_output=True, text=True, timeout=600)
            hit = set(r.stdout.split("\n"))
            conf = [(n_, t_) for n_, t_ in targets if t_ in hit]
        except Exception:
            unres += targets              # 判定不能はそう申告する
    elif targets:
        unres += targets                  # 判定の道具が無い = 判定していない
    print(f"── marker 棚卸し ({n} 本)")
    print(f"   🚫 機密索引に一致 : {len(conf)} 本")
    for name, tgt in conf:
        print(f"        {name} → {tgt}")
    print(f"   ⚠️ summary 上限({SUMMARY_MAX}字)超 : {len(over)} 本"
          + (f"  最長 {max(l for _n, l in over)} 字" if over else ""))
    for name, ln in sorted(over, key=lambda x: -x[1])[:5]:
        print(f"        {ln:>5} 字  {name}")
    if len(over) > 5:
        print(f"        … 他 {len(over) - 5} 本")
    print(f"   ? 成果物が現存せず検査不能 : {len(unres)} 本 (= 判定していない)")
    for name, tgt in unres[:5]:
        print(f"        {name} → {tgt}")
    if len(unres) > 5:
        print(f"        … 他 {len(unres) - 5} 本")
    return len(conf)


def neutralize(d, tokens, reason=""):
    """既存 marker の task / summary / result_path だけを中立文言に置き換える。

    後から機密と分かった marker を、 履歴ではなく **現在の file** から消すための操作。
    token / status / created / consumed / spawned_by は保つ (= 受領義務の状態を壊さない)。
    ⚠️ git 履歴には元の内容が残る。 これは「これ以上広げない」 ための操作であって、
       既に push 済のものを無かったことにする操作ではない。
    """
    done, missing = [], []
    for tok in tokens:
        f = Path(d) / f"{tok}.yaml"
        if not f.is_file():
            missing.append(tok)
            continue
        y = _load_yaml(f) or {}
        note = CONFIDENTIAL_NOTE if not reason else f"{CONFIDENTIAL_NOTE[:-1]}／{reason}）"
        body = (
            f'token: "{tok}"\n'
            f'status: {y.get("status", "done")}\n'
            f'task: "{CONFIDENTIAL_TASK}"\n'
            f'result_path: ""\n'
            f'summary: |\n  {note}\n'
        )
        if y.get("spawned_by"):
            body += f'spawned_by: "{y["spawned_by"]}"\n'
        if y.get("created"):
            body += f'created: "{y["created"]}"\n'
        body += f'consumed: {"true" if y.get("consumed") else "false"}\n'
        f.write_text(body, encoding="utf-8")
        done.append(tok)
    for tok in done:
        print(f"  中立化: {tok}")
    for tok in missing:
        print(f"  ⚠️ 見つからない: {tok}")
    if done:
        print("  ⚠️ git 履歴には元の内容が残る (= これ以上広げないための操作)")
    return 1 if missing else 0


def consume(d, token):
    f = d / f"{token}.yaml"
    if not f.exists():
        return False
    m = _load_yaml(f) or {}
    if _truthy(m.get("consumed", False)):
        return True  # 冪等
    txt = f.read_text(encoding="utf-8")
    if "consumed:" in txt:
        out = []
        for line in txt.splitlines():
            out.append("consumed: true" if line.strip().startswith("consumed:") else line)
        f.write_text("\n".join(out) + "\n", encoding="utf-8")
    else:
        f.write_text(txt.rstrip() + "\nconsumed: true\n", encoding="utf-8")
    return True


def list_all(d):
    rows = []
    for m in _markers(d):
        rows.append(f"{'✔' if _truthy(m.get('consumed')) else '·'} "
                    f"{_EMOJI.get(str(m.get('status')), '?')} {m.get('token')} "
                    f"[{m.get('task','')}] → {m.get('result_path','')}")
    return "\n".join(rows)


def selftest():
    """check ごとに `[PASS] <label>` / `[FAIL] <label>` を 1 行出す (歯の確かめ = 同じ dir の
    surface-spawn-results.mutants.json を check-foil-teeth.py が読む)。 文と値はすべて合成。"""
    import tempfile
    results = []

    def check(label, ok):
        results.append(bool(ok))
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")

    saved = {k: os.environ.get(k) for k in ("CLAUDE_LEAK_SOURCES", "CLAUDE_SPAWN_RESULTS_CMD",
                                             "CLAUDE_SPAWN_RESULTS_BASE")}
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        check("空の dir では何も出さない", surface(d) == "")
        record(d, "TOKA", "done", "SoT 監査", "plans/x.md", "3 件 drift 検出。", "依頼元")
        s = surface(d)
        check("done の marker を出す", "SoT 監査" in s)
        check("result_path を出す", "→ plans/x.md" in s)
        check("summary の 1 行目を出す", "3 件 drift 検出。" in s)
        check("consume すると出さない", consume(d, "TOKA") and surface(d) == "")
        check("consume は冪等", consume(d, "TOKA") is True)
        record(d, "TOKB", "done", "task B", "p/b.md", "ok", "")
        record(d, "TOKC", "failed", "task C", "p/c.md", "error: boom", "")
        s = surface(d)
        check("failed を done より上に並べる", s.index("task C") < s.index("task B"))
        # 「受け取ったら」 行は呼び元が渡した起動の形を出す (shim が自分の path を渡す)
        os.environ["CLAUDE_SPAWN_RESULTS_CMD"] = "python3 /x/shim.py"
        check("受け取りの案内に CLAUDE_SPAWN_RESULTS_CMD を使う",
              "python3 /x/shim.py --consume <token>" in surface(d))
        os.environ.pop("CLAUDE_SPAWN_RESULTS_CMD", None)
        (d / "broken.yaml").write_text(": : : not yaml\n\t- [", encoding="utf-8")
        check("壊れた marker を飛ばして残りを出す", "task C" in surface(d))
        check("無い token の consume は False", consume(d, "NOPE") is False)
        # result_path が dir で HANDOFF.md を含む → 📎 行が出る / 含まない dir → 出ない
        rd = d / "resultdir"; rd.mkdir()
        record(d, "TOKD", "done", "task D", str(rd), "sandbox review", "")
        check("HANDOFF.md が無ければ案内しない", "HANDOFF.md" not in surface(d))
        (rd / "HANDOFF.md").write_text("# handoff\n", encoding="utf-8")
        s = surface(d)
        check("HANDOFF.md があれば案内する", "📎 HANDOFF.md あり" in s and str(rd / "HANDOFF.md") in s)
        # 相対の result_path は CLAUDE_SPAWN_RESULTS_BASE の下 (とその直下の dir) で解決する
        (d / "repoA" / "plans").mkdir(parents=True)
        (d / "repoA" / "plans" / "r.md").write_text("x\n", encoding="utf-8")
        os.environ["CLAUDE_SPAWN_RESULTS_BASE"] = str(d)
        check("相対の result_path を基点の下で解決する",
              _resolve_result("plans/r.md") == d / "repoA" / "plans" / "r.md")
        # 基点の下に読めない dir があっても止まらずに次の dir を見る (Linux の /tmp の root の 700 の dir の形)
        locked = d / "locked"  # repoA より前に並ぶ名前
        locked.mkdir()
        locked.chmod(0)
        try:
            try:
                got = _resolve_result("plans/r.md")
            except OSError:
                got = None  # 例外で selftest を止めず、 この check の FAIL にする
            check("読めない dir が基点の下にあっても次の dir で解決する", got == d / "repoA" / "plans" / "r.md")
        finally:
            locked.chmod(0o755)
        os.environ.pop("CLAUDE_SPAWN_RESULTS_BASE", None)
    # ---- marker schema の縛り ----
    # 他の case と marker が混ざらないよう、専用の temp dir で回す。
    with tempfile.TemporaryDirectory() as td2:
        d2 = Path(td2)
        # 偽の「機密として宣言された作業 dir」 を仕立てる (= 実環境に依存しない)
        work = d2 / "work"; (work / "src").mkdir(parents=True)
        prose = "この段落は自己検査のためだけに組んだ合成の文で、どの実在の文書にも由来しない。" * 2
        (work / "src" / "q.tex").write_text(prose, encoding="utf-8")
        (work / "src" / "short.txt").write_text("x\n", encoding="utf-8")
        (work / ".leak-patterns").write_text("# index: **\n", encoding="utf-8")
        ptr = d2 / "sources.txt"; ptr.write_text(str(work) + "\n", encoding="utf-8")
        os.environ["CLAUDE_LEAK_SOURCES"] = str(ptr)

        nt = []
        record(d2, "TCONF", "done", "機密文書の盲検", str(work / "src" / "q.tex"),
               "重大 4 件。最重要は…", "", notes=nt)
        y = _load_yaml(d2 / "TCONF.yaml") or {}
        check("機密 dir の下の成果物は task・summary・result_path を落とす",
              not y.get("result_path") and "盲検" not in str(y.get("task"))
              and "重大" not in str(y.get("summary")))
        check("機密扱いにしたことを呼び出し元に伝える", bool(nt))
        # 中身が索引に当たらない短い file でも、 機密 dir の下なら path だけで縛る
        record(d2, "TSHORT", "done", "機密の短い file", str(work / "src" / "short.txt"), "要旨", "")
        check("機密 dir の下なら中身が索引に無くても縛る",
              not (_load_yaml(d2 / "TSHORT.yaml") or {}).get("result_path"))
        record(d2, "TNORM", "done", "SoT 監査", "some-repo/plans/x.md", "3 件検出。", "")
        y = _load_yaml(d2 / "TNORM.yaml") or {}
        check("相対の通常の成果物は縛らない",
              y.get("result_path") == "some-repo/plans/x.md" and "3 件検出" in str(y.get("summary")))
        try:
            record(d2, "TLONG", "done", "t", "some-repo/a.md", "あ" * (SUMMARY_MAX + 1), "")
            check("上限を超える summary を拒む", False)
        except ValueError:
            check("上限を超える summary を拒む", True)
        tgt = str(work / "src" / "q.tex")
        record(d2, "TOPT", "done", "検品", tgt, "要旨", "", allow_confidential_text=True)
        check("--not-confidential を尊重する", (_load_yaml(d2 / "TOPT.yaml") or {}).get("result_path") == tgt)
        # 機密 dir の外にある成果物でも、 中身が機密索引に一致すれば機密扱い
        # (= 判定の道具 check-confidential-leak.py が在る機械でだけ確かめる)
        out = d2 / "sandbox"; out.mkdir()
        (out / "R.md").write_text("メモ: " + prose[:60] + "\n", encoding="utf-8")
        record(d2, "TSAND", "done", "盲検", str(out / "R.md"), "要旨", "")
        if _leak_engine().is_file():
            check("中身が機密索引に一致する成果物は機密 dir の外でも縛る",
                  not (_load_yaml(d2 / "TSAND.yaml") or {}).get("result_path"))
        ok = d2 / "other"; ok.mkdir()
        (ok / "R.md").write_text("まったく無関係な調査の結論をここに書いた。\n", encoding="utf-8")
        record(d2, "TOK", "done", "別件", str(ok / "R.md"), "要旨", "")
        check("無関係な成果物は縛らない", bool((_load_yaml(d2 / "TOK.yaml") or {}).get("result_path")))
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    n_fail = results.count(False)
    print(f"SELFTEST {'PASS' if not n_fail else 'FAIL'} ({len(results) - n_fail}/{len(results)} checks)")
    return 1 if n_fail else 0


def main():
    ap = argparse.ArgumentParser(description="file と token で渡した子 session の完了を届ける受け取りの道具")
    ap.add_argument("--dir", default=None, help="marker dir (既定 = CLAUDE_SPAWN_RESULTS_DIR か ~/.claude/spawn-results)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--consume", metavar="TOKEN")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--token")
    ap.add_argument("--status", default="done", choices=["done", "partial", "failed"])
    ap.add_argument("--task", default="")
    ap.add_argument("--result-path", default="")
    ap.add_argument("--neutralize", nargs="+", metavar="TOKEN",
                    help="既存 marker の task/summary/result_path を中立文言に置換 "
                         "(= 後から機密と分かったとき。 状態 field は保つ)")
    ap.add_argument("--neutralize-reason", default="",
                    help="中立化の理由を summary に 1 語だけ添える")
    ap.add_argument("--audit", action="store_true",
                    help="既存 marker を現行基準で棚卸し (機密一致があれば exit 1)")
    ap.add_argument("--not-confidential", action="store_true",
                    help="成果物が機密 dir 配下・機密索引に一致でも、 task と summary と "
                         "result_path を marker にそのまま残す (= 明示的な opt-out)")
    ap.add_argument("--summary", default="")
    ap.add_argument("--spawned-by", default="")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())
    d = Path(os.path.expanduser(args.dir)) if args.dir else _default_dir()
    try:
        if args.record:
            if not args.token:
                print("--record は --token 必須", file=sys.stderr)
                sys.exit(2)
            notes = []
            try:
                f = record(d, args.token, args.status, args.task, args.result_path,
                           args.summary, args.spawned_by,
                           allow_confidential_text=args.not_confidential, notes=notes)
            except ValueError as e:
                print(f"marker を書きませんでした: {e}", file=sys.stderr)
                sys.exit(1)
            for n in notes:
                print(f"⚠️ {n}", file=sys.stderr)
            print(f"recorded: {f}")
            return
        if args.neutralize:
            sys.exit(neutralize(d, args.neutralize, args.neutralize_reason))
        if args.audit:
            sys.exit(1 if audit(d) else 0)
        if args.consume:
            ok = consume(d, args.consume)
            print("consumed" if ok else "no such token", file=sys.stderr)
            sys.exit(0 if ok else 1)
        if args.list:
            print(list_all(d))
            return
        out = surface(d)
        if out:
            print(out)
    except SystemExit:
        raise
    except Exception:
        # fail-open: dashboard / hook 連鎖を絶対に止めない
        sys.exit(0)


if __name__ == "__main__":
    main()
