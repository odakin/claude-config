"""Word の操作は全部ここ (staging 経由・前面に出さない・1 回に 1 文書)。 D6 (2026-09-25): docx の欄に値を **Word で** 書く。

python-docx で run を書き換えると、 段落に run が無い欄 (空欄) は既定の書式の run になり (rFonts = 明朝 → 既定、 sz が落ちる)、
run の中の図・field・記号も消える (docx_form.object_loss)。 Word に書かせると、 段落記号の書式 (雛形の作者が欄に付けた
font・大きさ) が新しい字に付く = 雛形どおり。

- ``write_paragraphs(docx, edits, expect)``: docx (staged copy) を Word で開き、 段落番号 (Word の Paragraphs の 1 始まり) で
  字を差し替える / 段落を足す / 字の大きさを変える。 expect = {段落番号: 雛形の字} を書く前に照合し、 ずれていれば何も書かずに
  止める (= 段落番号の写像の前提 〔表の行末の記号も段落〕 が崩れた雛形を黙って通さない)。 保存は同じ file (docx)。
- Word の起動・終了・前面は lib/office_staging の app guard に任せる (Stage の最初の file が .docx なら word)。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from office_staging import Stage, office_app  # noqa: E402


class WordError(RuntimeError):
    """Word (osascript) の失敗。 文に osascript の標準エラーを逐語で含む。"""


def _q(s: str) -> str:
    """AppleScript の文字列。 改行 (python-docx の run.text の \\n = 段落内の改行 w:br) は Word では ASCII 11 (段落を分けない
    改行) = content に書くのも、 雛形の字と照合するのも同じ形。"""
    parts = str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\x0b", "\n").split("\n")
    return " & (ASCII character 11) & ".join(f'"{p}"' for p in parts)


def available() -> bool:
    """macOS で Word が入っていて、 環境変数 FORMCASE_DOCX_WRITER が python でない。"""
    if sys.platform != "darwin" or os.environ.get("FORMCASE_DOCX_WRITER", "").lower() == "python":
        return False
    r = subprocess.run(["osascript", "-e", 'tell application "Finder" to exists application file id "com.microsoft.Word"'],
                       capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip().lower() == "true"


def _open_in_word(path: str, timeout: float = 90.0) -> None:
    """Word を背景で起こし、 `open -g` で開かせ (前面に出さない)、 文書として見えるまで待つ (docx-to-pdf.sh の render_word と同じ。
    Word の full name は HFS path で返ることがあるので、 照合は app guard の has-path に任せる)。"""
    office_app("launch", "word")
    if office_app("has-path", "word", path).returncode == 0:
        raise WordError(f"Word が既にこの文書を開いている: {path} (閉じてから)")
    subprocess.run(["open", "-g", "-a", "Microsoft Word", path], check=True)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if office_app("has-path", "word", path).returncode == 0:
            time.sleep(2.0)                                   # 開いた直後の layout の落ち着き (docx-to-pdf.sh と同じ)
            return
        time.sleep(0.5)
    raise WordError(f"Word が {os.path.basename(path)} を {timeout:.0f} 秒で開かない")


def _script(path: str, edits, expect: dict) -> str:
    """edits = [(index, kind, value)] (index 降順で当てる)。 kind = text / insert_after / size / bold。"""
    checks = "\n".join(
        f'      set got to (content of text object of paragraph {i} of d) as text\n'
        f'      if my strip(got) is not {_q(t)} then error "段落 {i} の字が雛形と違う: " & got'
        for i, t in sorted(expect.items()))
    lines = []
    for i, kind, val in sorted(edits, key=lambda e: (-e[0], e[1] != "text")):
        if kind == "text":
            lines.append(f"      my setText(d, {i}, {_q(val)})")
        elif kind == "insert_after":
            # 段落の字の末尾に段落記号 + 値を書く = 新しい段落 (元の段落の書式を引き継ぐ。 Word の `insert paragraph after` は
            # text object を受け付けない = 実測 -1708)。 python-docx の _add_par (段落の deepcopy + 太字なし) と同じ形
            text, size = (val if isinstance(val, tuple) else (val, None))
            lines.append(f"      set cur to my strip((content of text object of paragraph {i} of d) as text)")
            lines.append(f"      my setText(d, {i}, cur & return & {_q(text)})")
            lines.append(f"      set bold of font object of text object of paragraph {i + 1} of d to false")
            if size:
                lines.append(f"      set font size of font object of text object of paragraph {i + 1} of d to {float(size)}")
        elif kind == "size":
            lines.append(f"      set font size of font object of text object of paragraph {i} of d to {float(val)}")
        elif kind == "bold":
            lines.append(f"      set bold of font object of text object of paragraph {i} of d to {'true' if val else 'false'}")
        else:
            raise WordError(f"未知の編集 {kind!r}")
    body = "\n".join(lines)
    return f'''
on strip(s)
  -- 段落記号 (return)・cell の記号 (ASCII 7)・改頁 (ASCII 12) を末尾から落とす = python-docx の段落の字と同じ形に
  set t to s as text
  repeat while t is not "" and (character -1 of t is return or character -1 of t is (ASCII character 7) or character -1 of t is (ASCII character 12))
    if (length of t) is 1 then
      set t to ""
    else
      set t to text 1 thru -2 of t
    end if
  end repeat
  return t
end strip

on setText(d, i, v)
  tell application id "com.microsoft.Word"
    set r to text object of paragraph i of d
    set s to start of content of r
    set e to (end of content of r) - 1
    set rr to create range d start s end e
    set content of rr to v
  end tell
end setText

on run argv
  set docPath to item 1 of argv
  with timeout of 300 seconds
    tell application id "com.microsoft.Word"
      set d to missing value
      repeat with k from 1 to (count of documents)
        set fn to (full name of document k) as text
        if fn does not start with "/" and fn contains ":" then set fn to POSIX path of fn
        if fn is docPath then set d to document k
      end repeat
      if d is missing value then error "document not open in Word: " & docPath
{checks}
{body}
      save d
      close d saving no
    end tell
  end timeout
end run
'''


def write_paragraphs(docx_path, edits, expect: dict) -> None:
    """docx_path (Word に開かせる copy) の段落に書く。 失敗は WordError (osascript の標準エラーを逐語で)。"""
    docx_path = str(Path(docx_path).resolve())
    with Stage(docx_path) as st:
        sx = st.paths[0]
        _open_in_word(sx)
        r = subprocess.run(["osascript", "-e", _script(sx, edits, expect), sx], capture_output=True, text=True)
        if r.returncode != 0:
            err = (r.stderr or r.stdout).strip()
            try:
                office_app("close-ours", "word", sx)
            except OSError:
                pass
            raise WordError(f"Word への書込みが失敗 (osascript exit {r.returncode}): {err}")
        if st.active:
            st.copy_back(sx, docx_path)
