"""git_crypt_paths — staged の path のうち git-crypt で暗号化される path を判定する (pre-commit の警告が見本を伏せるため)。

staged_diff.py は textconv で git-crypt の file を平文に戻して読む。 その行をそのまま警告の見本として stderr に出すと、
暗号化した値 (口座番号・電話など) が端末と会話の記録に写る (実測)。 警告は検査を続け、 見本の表示だけを伏せる。
使う側 = pre-commit-sot-declaration-warn.py / pre-commit-google-url-warn.py ほか (見本を出す警告は全部)。
"""
from __future__ import annotations

import subprocess

# 暗号化される file の行を見本に出すときの代わりの文字列
MASKED_SAMPLE = "<暗号化される file の行 = 本文は出さない>"


def encrypted_paths(paths, cwd: str | None = None) -> set[str]:
    """paths のうち `.gitattributes` で filter=git-crypt の path。 判定できないときは全部 (= 伏せる側に倒す)。"""
    paths = [p for p in dict.fromkeys(paths) if p]
    if not paths:
        return set()
    try:
        result = subprocess.run(["git", "check-attr", "--stdin", "-z", "filter"], cwd=cwd, capture_output=True,
                                input="\0".join(paths).encode("utf-8"), check=False, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return set(paths)
    if result.returncode != 0:
        return set(paths)
    out = result.stdout.decode("utf-8", "replace").split("\0")
    return {out[i] for i in range(0, len(out) - 2, 3) if out[i + 2] == "git-crypt"}
