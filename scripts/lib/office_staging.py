"""office_staging.py — office-staging.sh の Python 鏡像 (同じ root 解決規則、 Excel / Word を osascript で駆動する python driver 用。 office-automation.md#office-pregranted-staging-dir)

macOS の Microsoft Office は App Sandbox で、 file を置いた folder へ書く瞬間に folder ごとの
「ファイル アクセスを許可」 dialog を出す。 Office 3 app が共有する App Group container
``~/Library/Group Containers/UBF8T346G9.Office/`` は sandbox の内側で grant 不要なので、
入力をそこへ copy → Office に触らせる → 結果を呼び出し元へ copy back する。
規則・env (``CLAUDE_OFFICE_STAGING`` / ``CLAUDE_OFFICE_STAGING_DIR``) は bash 版と同一 —
**root 解決の規則を変えるときは両方を直す** (drift は ``office-staging.test.sh`` が検出)。

使い方::

    from office_staging import Stage
    with Stage(book, image) as st:          # staging 不可なら st.paths == 元 path のまま (in-place)
        staged_book, staged_image = st.paths
        ... Excel に staged_book を触らせる ...
        st.copy_back(staged_book, book)     # 書き戻し (同 dir の tmp → os.replace で atomic)
    # 正常終了で subdir を削除、 例外時は残す (診断用)
"""
from __future__ import annotations

import os
import platform
import shutil
import tempfile
import time

ROOT_NAME = "claude-office-staging"
GROUP_CONTAINER = "Library/Group Containers/UBF8T346G9.Office"


def staging_root() -> str | None:
    """staging root (str) or None (= 無効 / 非 macOS / 不可 → in-place で続行)."""
    if os.environ.get("CLAUDE_OFFICE_STAGING", "1").strip().lower() in ("0", "no", "off", "false"):
        return None
    override = os.environ.get("CLAUDE_OFFICE_STAGING_DIR", "")
    if override:
        root = override
    else:
        if platform.system() != "Darwin":
            return None
        gc = os.path.join(os.environ.get("HOME") or os.path.expanduser("~"), GROUP_CONTAINER)
        if not os.path.isdir(gc):
            return None
        root = os.path.join(gc, ROOT_NAME)
    try:
        os.makedirs(root, exist_ok=True)
    except OSError:
        return None
    return root if os.access(root, os.W_OK) else None


def fallback_reason() -> str:
    """staging_root() が None になる理由を 1 語で (bash 版 office_staging_fallback_reason と同一分岐)。

    disabled / not-darwin / no-office / mkdir-failed / not-writable / ok
    """
    if os.environ.get("CLAUDE_OFFICE_STAGING", "1").strip().lower() in ("0", "no", "off", "false"):
        return "disabled"
    override = os.environ.get("CLAUDE_OFFICE_STAGING_DIR", "")
    if override:
        root = override
    else:
        if platform.system() != "Darwin":
            return "not-darwin"
        gc = os.path.join(os.environ.get("HOME") or os.path.expanduser("~"), GROUP_CONTAINER)
        if not os.path.isdir(gc):
            return "no-office"
        root = os.path.join(gc, ROOT_NAME)
    try:
        os.makedirs(root, exist_ok=True)
    except OSError:
        return "mkdir-failed"
    return "ok" if os.access(root, os.W_OK) else "not-writable"


def log_path() -> str:
    """fallback log の path (bash 版 office_staging_log_path と同一規則)."""
    return os.environ.get("CLAUDE_OFFICE_STAGING_LOG") or os.path.join(
        os.environ.get("XDG_STATE_HOME") or os.path.join(os.environ.get("HOME") or os.path.expanduser("~"), ".local", "state"),
        "claude-office-staging", "fallback.log")


def report_fallback(src: str = "") -> str:
    """予期せぬ fallback (mkdir-failed / not-writable / no-office) を stderr + log に出す。 戻り値 = reason。

    disabled / not-darwin / ok は沈黙 (= 意図的 or 該当なし)。 log 書込失敗は無視 (変換を止めない)。
    bash 版 office_stage_report_fallback と同契約 — 変えるときは両方。
    """
    import sys
    reason = fallback_reason()
    if reason in ("ok", "disabled", "not-darwin"):
        return reason
    override = os.environ.get("CLAUDE_OFFICE_STAGING_DIR", "")
    root = override or os.path.join(os.environ.get("HOME") or os.path.expanduser("~"), GROUP_CONTAINER, ROOT_NAME)
    print(f"⚠️  staging: UNAVAILABLE ({reason}: {root}) → in-place. Office の「ファイル アクセスを許可」 dialog が出うる",
          file=sys.stderr)
    print("    対処 = office-automation.md#office-pregranted-staging-dir (TCC 許可 or CLAUDE_OFFICE_STAGING_DIR=<dir> + 1 回 grant)",
          file=sys.stderr)
    try:
        lp = log_path()
        os.makedirs(os.path.dirname(lp), exist_ok=True)
        with open(lp, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\t{reason}\t{root}\t{src}\n")
    except OSError:
        pass
    return reason


def prune(days: int = 7) -> None:
    """root 直下の古い subdir を掃除 (失敗残骸の無限増殖防止)."""
    root = staging_root()
    if not root:
        return
    cutoff = time.time() - days * 86400
    for name in os.listdir(root):
        p = os.path.join(root, name)
        try:
            if os.path.isdir(p) and os.path.getmtime(p) < cutoff:
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass


class Stage:
    """copy files into a unique staging subdir; cleanup on clean exit, keep on exception."""

    def __init__(self, *files: str):
        self.sources = [os.path.abspath(f) for f in files]
        self.dir: str | None = None
        self.paths: list[str] = list(self.sources)
        self.active = False

    def __enter__(self) -> "Stage":
        root = staging_root()
        if not root:
            report_fallback(self.sources[0] if self.sources else "")  # 予期せぬ fallback は黙らせない
            return self  # in-place fallback
        prune(7)  # bash 版 (各 wrapper が office_stage_prune 7 を呼ぶ) と同じ契約
        self.dir = tempfile.mkdtemp(prefix=f"{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}-", dir=root)
        staged = []
        for src in self.sources:
            dst = os.path.join(self.dir, os.path.basename(src))
            shutil.copy2(src, dst)
            staged.append(dst)
        with open(os.path.join(self.dir, ".source"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(self.sources) + "\n")
        self.paths = staged
        self.active = True
        return self

    @staticmethod
    def copy_back(staged: str, dest: str) -> None:
        """staged → dest を同 dir の tmp 経由で atomic に書き戻す."""
        dest_dir = os.path.dirname(os.path.abspath(dest)) or "."
        fd, tmp = tempfile.mkstemp(prefix=".office-stage-", dir=dest_dir)
        os.close(fd)
        shutil.copy2(staged, tmp)
        os.replace(tmp, dest)

    def cleanup(self) -> None:
        if self.active and self.dir and os.path.isdir(self.dir):
            shutil.rmtree(self.dir, ignore_errors=True)
        self.active = False

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.cleanup()
        # 例外時は残す (= 診断用、 bash 版と同じ契約)
        return False
