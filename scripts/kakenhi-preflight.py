#!/usr/bin/env python3
"""kakenhi-preflight.py — 科研費 研究計画調書の「機関事務が必ず突く点」を提出前に機械検出（様式骨格の生存 / 埋め込み指示の抽出 / 表記 lint / 経費明細の粒度・費目帰属、kakenhi-proposal.md#office-review-loop）

なぜ必要か
----------
調書を **様式 docx のまま書かず LaTeX 等で組み直す** と、様式に印字されていた見出し・
表ラベル・記述欄が「自分が打った文字列」に変わり、改訂のたびに **黙って消える**。
様式 docx を埋める運用なら `diff-form-docx.py` が LABEL_OVERWRITE / 見出し消失で捕まえるが、
組み直し運用ではその網が丸ごと外れる。実例 (2026-09): 「研究計画最終年度前年度応募」欄の
見出し 2 行と研究期間セルが消えた状態で提出し、機関事務に「元の様式にあった部分が消えている、
様式の改変は認められない」と差し戻された。**様式 docx にはその指示自体が印字されていた**
(「該当しない場合は記述欄を削除することなく、空欄のまま提出すること。」)。

同じ提出回の赤字 28 箇所を類型化すると、大半は **様式・記入要領に既に書いてあることの未適用**か、
**年に依らない定型チェック** (経費明細の粒度・費目帰属・表記) だった。本 script はその年非依存の
部分を機械化する。年ごとの中身 (must / must_not 語) は各年の staging gate が持てばよい。

検査
----
[FORM]  --form <様式.docx> [--pdf <調書.pdf>]
  🔴 SKELETON_LOST     様式が「削除することなく」等で明示保護した欄の label が PDF に無い
  🟠 SKELETON_MISSING  その他の pre-printed 見出し・表ラベルが PDF に無い
  🔴 INSTRUCTION_RESIDUE 様式が「提出時に削除せよ」と言った注意書きが提出版に残っている
  🟠 BLANK_SECTION_FILLED 様式が「空欄のまま提出」と指定した欄に書いてしまっている
  🟠 COLORED_TEXT      提出版 PDF に有彩色の文字 (記入要領の色字 / 著者注の消し忘れ)
                       ⚠️ --pdf に渡してよいのは **提出物そのもの** だけ。公募要領・論文・見積書
                       等の参考資料に当てても意味がない (色は最初から意味を持っている)。
  ℹ️ INSTRUCTION       様式に埋め込まれた指示文の一覧 (category 別、1 つずつ適用を verify する)
[PDF]   --pdf <調書.pdf>
  🔴 ENTITY            HTML 実体参照の残置 (&#12316; 等)
  🟠 ABBREV            官公庁・機関名の略称 (文科省 → 文部科学省 等)
  🟠 BARE_NUMBER       裸の括弧数字 (「（160）」= 被引用数の単位落ち)
[ID]    --identity <identity.yaml>   (値は呼ぶ側が持つ — 下の「層」を参照)
  🔴 IDENTITY_STALE     誤りと確定した旧 ID (機関コード等) が提出物の中身か file 名に残っている
  🔴 IDENTITY_FILENAME  提出 file 名に埋まったコードが宣言値と違う (別の ID を書いた / 旧値のまま)
[CSV]   --keihi <経費明細.csv>   (cp932 / utf-8 どちらも可)
  🔴 KEIHI_FIELD_BYTES  「事項」が 72 バイト超 (一時保存で全画面が保存されない)
  🔴 KEIHI_WAVEDASH     波ダッシュ (確認用 PDF に実体参照が焼かれる)
  🟠 KEIHI_CATEGORY     費目帰属の誤り (サブスク・ライセンス・API・クラウド・業者委託 → その他 等)
  🟠 KEIHI_DOUBLE_COUNT 二重計上の疑い (「その他」の行に滞在費・旅費)
  🟠 KEIHI_SPEC_MISSING 設備備品費の「品名・仕様」に型番・仕様が無い
  🟠 KEIHI_TRAVEL_DETAIL 旅費の「事項」に場所・回数・日数・人数が無い
  🟠 KEIHI_MULTI_ITEM   1 行に異種の事項 (「論文投稿料、クラウド計算資源」等)
  🟠 KEIHI_AMOUNT_VARY  同じ事項が年度によって違う金額 (理由を必要性欄に書いていないと必ず突かれる)

使い方
------
    kakenhi-preflight.py --form forms/s-13.docx --pdf build/chosho.pdf --keihi KEIHIMEISAI.csv
    kakenhi-preflight.py --keihi KEIHIMEISAI.csv          # 経費だけ
    kakenhi-preflight.py --form forms/s-74.docx           # 骨格 + 指示の一覧だけ (起草前に 1 回)
    # 種目が複数様式を持つとき (挑戦的研究 = 概要版 + 本文) は --form / --pdf を繰り返す。
    # 骨格と PDF text は和集合で突き合わせるので、片方だけ渡すと偽の SKELETON_MISSING が出る。
    kakenhi-preflight.py --form forms/s-42-1.docx --form forms/s-42-2.docx \
                         --pdf gaiyou.pdf --pdf honbun.pdf
    kakenhi-preflight.py --selftest

終了コード: 0 = 🔴 なし (🟠 は残っていてもよい) / 1 = 🔴 あり / 2 = 実行エラー。
🟠 は「事務が突く可能性が高い」であって誤検出もある — 潰すか、理由を書いて残すかを人が決める。

層: 本 script は **ID の値を持たない**。「誰の機関コードが何番か」は本 script の観客
(= 全ユーザー) にとって true でないため。判定ロジックと形式規則だけを持ち、値は
`--identity` で受ける (呼ぶ側が自分の層で正本を持つ)。値自体は公開情報だが、
層の判定は audience であって機密性ではない。

正本: claude-config/conventions/kakenhi-proposal.md
  #office-review-loop (指摘の類型) / #form-template-integrity (様式骨格) /
  #keihi-meisai-granularity (粒度) / #keihi-meisai-expense-category (費目帰属) /
  #keihi-meisai-field-limits (byte 上限) / #textfield-wavedash-entity (実体参照)
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

# ── 様式 docx から骨格を拾うための規則 ────────────────────────────────────────
# 「この欄を消すな」と様式自身が書いている印。ここに掛かる見出しは 🔴 扱いにする。
PROTECTED_MARKERS = ("削除することなく", "削除しないこと", "動かさないこと", "削除せず")
# 様式の注意書きブロック (作成時に消す前提のもの) は骨格ではない。
# ⚠️ 骨格から外すだけでなく、**提出版に残っていないか**の検出源でもある
# (2026-06 LOTUS: 事務が削除を求めた記入要領が提出版に残り、2 度の検証をすり抜けた)。
DROP_MARKERS = ("このテキストボックスごと削除", "本留意事項の内容を十分に確認")
DELETE_MARKERS = ("削除すること", "削除の上", "提出時に削除", "削除してください", "を削除")
# 様式が「該当しなければ**空欄で出せ**」と言っている印。⚠️ 別の欄では逆に「その旨記述せよ」
# と言うので、欄ごとに読む必要がある (2024 実測: 空欄指定の欄に「該当しない。」と書いて
# 「トル / 空欄のまま提出するため」と赤字)。
BLANK_MARKERS = ("空欄のまま提出", "空欄で提出", "空欄のまま")
# 番号付き大見出し: 「２　応募者の研究遂行能力及び研究環境」「４ 研究計画最終年度前年度応募…」
HEADING_RE = re.compile(r"^[0-9０-９]{1,2}[\s　]+\S")

# 埋め込み指示の分類 (scan-form-instructions.py の docx 版。keyword → category)
INSTRUCTION_PATTERNS = [
    ("削除することなく", "欄の保持", "記述欄・見出しを消さない (該当なしでも空欄で残す)"),
    ("削除しないこと", "欄の保持", "空白頁が生じても削除しない"),
    ("動かさないこと", "欄の保持", "各頁上部のタイトル・指示書きを動かさない"),
    ("頁以内", "分量", "指定頁数を超えない (下限側は #office-review-loop の 7 割)"),
    ("超えない", "分量", "指定の上限を超えない"),
    ("字以内", "分量", "字数上限 (Web 欄は byte 換算に注意)"),
    ("ポイント以上", "書式", "本文の最小文字サイズ"),
    ("下線", "書式", "指定された下線 (本人・代表者・分担者) を全 entry に機械付与"),
    ("掲載が確定しているものに限", "業績", "未掲載を業績として並べない (引用文献として掲載状態ラベルを付ける)"),
    ("同定するに十分な情報", "業績", "誌名・巻号・頁・発表年まで書く (arXiv 番号だけにしない)"),
    ("の順で記載", "業績", "書誌情報の**並び順**が様式で指定されている (例: 著者名→題名→誌名→巻号→開始頁-最終頁→発行年)"),
    ("開始頁", "業績", "開始頁−最終頁まで書く (article number だけにしない)"),
    ("とは異なります", "ID", "似た別 ID との取り違え注意が様式に印字されている (機関番号 ⇄ 機関コード等)"),
    ("スペース", "書式", "氏名等の区切り文字が指定されている (半角 1 スペース等)"),
    ("具体的かつ明確に記述", "内容", "指示された小項目 (1)(2)… を漏れなく立てる"),
    ("役割を記述", "内容", "研究代表者・研究分担者の具体的な役割を書く"),
    # ⚠️ 「該当しない場合」の扱いは**欄ごとに逆**。人権の欄は「その旨記述」= 書く、
    #    最終年度前年度応募の欄は「削除することなく空欄のまま提出」= **書かない**。
    #    2024 実測: 欄4 に「該当しない。」と書いて「トル / 空欄のまま提出するため」と赤字。
    ("その旨記述", "内容", "この欄は該当しない場合も「該当しない」と書く (⚠️ 別の欄では逆に空欄が正解)"),
    ("空欄のまま提出", "欄の保持", "この欄は該当しなければ**空欄で出す** (「該当しない」と書かない)"),
    ("参考にすること", "内容", "参照先の規程・要領に literal 正対させる"),
]

# ── 表記 lint ────────────────────────────────────────────────────────────────
# 官公庁・機関の略称。調書は正式名称で書く (2026-09 に「文科省」を全件赤字指摘)。
# ⚠️ 略称が正式名称の**部分文字列**になる組があるので、位置で除外する
# (「振興会」を素の entry にすると正しい「日本学術振興会」を毎回叩く = 2026 年度の
#  申請書で実測した偽陽性。正式名称の一部でしかない断片は entry にしない)。
ABBREV_MAP = {
    "文科省": "文部科学省",
    "厚労省": "厚生労働省",
    "経産省": "経済産業省",
    "農水省": "農林水産省",
    "国交省": "国土交通省",
    "学振": "日本学術振興会",
}
ENTITY_RE = re.compile(r"&#\d+;|&[a-zA-Z]{2,8};")
# 「（160）」型の裸の数字 = 単位・意味が落ちた数 (2026-09 に被引用数を「(160)」と書いて赤字)。
BARE_NUMBER_RE = re.compile(r"[（(](\d{2,4})[）)]")

# ── 経費明細 lint ────────────────────────────────────────────────────────────
CAT_NAMES = {"A": "設備備品費", "B": "消耗品費", "C": "国内旅費", "D": "外国旅費",
             "E": "人件費・謝金", "F": "その他"}
# keyword → 載せるべき費目。事務が「行を分けて」「その他に」と赤字にする定番。
CATEGORY_RULES = [
    (re.compile(r"サブスクリプション|ライセンス|API利用|API 利用|クラウド|使用料|利用料|保守|レンタル|リース"), "F",
     "サブスクリプション等の利用料・保守は「その他」"),
    (re.compile(r"業者委託|委託|校閲|校正|英文校閲"), "F", "業者委託 (英文校閲等) は「その他」"),
    (re.compile(r"謝金|RA|アルバイト|人件費|研究員|補助者"), "E", "謝金・人件費は「人件費・謝金」"),
    (re.compile(r"投稿料|掲載料|出版"), "F", "論文投稿料・掲載料は「その他」"),
    (re.compile(r"登録料|参加費|参加登録"), "F", "学会・国際会議の参加登録料は「その他」 (旅費に混ぜない)"),
    (re.compile(r"専門書|文献|図書|消耗品|文具"), "B", "書籍・消耗品は「消耗品費」"),
]
# 「その他」に旅費相当が紛れる = 旅費との二重計上 (2026-09 に「滞在費は外国旅費に含まれるため削除」)
DOUBLE_COUNT_RE = re.compile(r"滞在費|宿泊費|渡航費|航空券|交通費|旅費")
# 逆向き: 旅費の行に「その他」費目のものが混ざる (2026-07 に「登録料はその他の費用に計上して下さい」)
TRAVEL_MISFIT_RE = re.compile(r"登録料|参加費|参加登録|投稿料|掲載料")
# 旅費の事項に必要な粒度
TRAVEL_DETAIL_RE = re.compile(r"\d+\s*回|\d+\s*泊|\d+\s*日間|\d+\s*名|年\d+|各\d+")
# 設備の品名・仕様に型番・仕様が入っている印
SPEC_RE = re.compile(r"[A-Za-z0-9]|相当|メモリ|GB|TB|コア")
WAVEDASH_RE = re.compile(r"[〜～]")
# 1 行に異種を詰めた印: 読点で並んだ両側が別々の CATEGORY_RULES に当たる
SPLIT_RE = re.compile(r"[、,・]")


def die(msg: str) -> "NoReturn":          # noqa: F821 — docstring の終了コード契約 (2 = 実行エラー)
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(2)


# PDF テキスト抽出は約物を字形の近い別コードに落とすことがある (埋め込み font 依存)。
# NFKC はこれらを同一視しないので、比較の前に代表字へ畳む。
# 実測: 中黒「・」(U+30FB) が「·」(U+00B7) として抽出され、様式の文と一致しなかった。
_PUNCT_FOLD = str.maketrans({
    "·": "・", "•": "・", "･": "・", "‧": "・",          # 中黒の変種
    "〜": "~", "～": "~",                                  # 波ダッシュ
    "－": "-", "−": "-", "–": "-", "—": "-", "‐": "-", "―": "-",   # ダッシュ/ハイフン
    "’": "'", "‘": "'", "“": '"', "”": '"',
})


def nfkc(s: str) -> str:
    """比較用の正規化: NFKC + 約物の畳み込み + 空白全除去。

    全角/半角・和欧間空白の揺れに加え、PDF 抽出で起きる約物の字形置換も吸収する
    (両側に同じ変換を掛けるので、畳み込みで偽一致が増える心配はほぼ無い)。
    """
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s).translate(_PUNCT_FOLD))


def nbytes(s: str) -> int:
    """電子申請システムの byte 換算 (全角 2 / 半角 1)。"""
    return sum(2 if ord(c) > 127 else 1 for c in s)


# ── docx 読み取り ────────────────────────────────────────────────────────────
_WT = re.compile(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", re.S)
_WP = re.compile(r"<w:p(?:\s[^>]*)?>.*?</w:p>", re.S)
_WTC = re.compile(r"<w:tc(?:\s[^>]*)?>.*?</w:tc>", re.S)
_TXBX = re.compile(r"<w:txbxContent>.*?</w:txbxContent>", re.S)


def _runs(xml: str) -> str:
    return "".join(m.group(1) for m in _WT.finditer(xml))


def read_form(path: Path) -> dict:
    """様式 docx から (骨格候補, 保護欄, 指示文) を取り出す。

    骨格候補 = ① 番号付き大見出し ② 表のヘッダセル (短い label)。
    注意書きテキストボックス (作成時に削除する前提) は骨格から除く。

    「削除することなく」等の保護マーカーは、**それが書かれた見出しの配下** (= 文書順で
    次の見出しが来るまで) に効く。マーカーと見出しは別ノードなので、文書順に走査して
    欄 scope で紐付ける (同一ノードの文字列一致で判定すると 2026-09 の実例を取り逃す)。
    """
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8")
    except FileNotFoundError:
        die(f"様式が見つからない: {path}")
    except (zipfile.BadZipFile, KeyError):
        die(f"docx として読めない (.doc 形式 / 破損 / 別 file?): {path}")
    body = _TXBX.sub("", xml)          # 骨格判定からテキストボックスを外す
    all_text = _runs(xml)              # 指示文の抽出はテキストボックスも含めて拾う

    # 「提出時に消す」ブロックの中の文 = 提出版に残っていたら差し戻し事由。
    # ⚠️ 色 (青字等) では拾わない — docx の run 色は style 継承で嘘をつくので、
    #    色の判定は提出 PDF の render span を ground truth にする (check_colored_text)。
    delete_sigs: list[str] = []
    for m in _TXBX.finditer(xml):
        blk = _runs(m.group(0))
        if not any(k in blk for k in DELETE_MARKERS):
            continue
        for sent in re.split(r"(?<=。)|(?<=：)", blk):
            sent = sent.strip()
            if len(sent) >= 10 and not any(k in sent for k in DROP_MARKERS):
                delete_sigs.append(sent)

    # 文書順のノード列 (段落 / 表セル) を作る
    nodes = []
    for m in re.finditer(r"<w:p(?:\s[^>]*)?>.*?</w:p>|<w:tc(?:\s[^>]*)?>.*?</w:tc>", body, re.S):
        kind = "cell" if m.group(0).startswith("<w:tc") else "para"
        t = _runs(m.group(0)).strip()
        if t and not any(d in t for d in DROP_MARKERS):
            nodes.append((kind, t))

    headings, cells, protected_labels = [], [], set()
    section = None                      # 直近の見出し
    section_labels: list[str] = []       # その見出し配下の骨格 label
    guarded = False                      # その見出し配下に保護マーカーが出たか

    def flush():
        if section and guarded:
            protected_labels.add(section)
            protected_labels.update(section_labels)

    for kind, t in nodes:
        if kind == "para" and HEADING_RE.match(t):
            flush()
            section, section_labels, guarded = t, [], False
            headings.append(t)
            continue
        if any(k in t for k in PROTECTED_MARKERS):
            guarded = True
        # 表ヘッダ = 短いラベル。長文セル (記述欄の指示書き) は骨格に数えない。
        if kind == "cell" and len(t) <= 24:
            cells.append(t)
            section_labels.append(t)
    flush()

    # 指示文は **どの欄のものか** を付けて拾う。1 文が複数の義務を負うことがあるので
    # 先勝ちで break しない (⚠️ 実測: 「削除することなく、空欄のまま提出すること」が
    # 「削除することなく」 だけに当たり、「空欄のまま提出」 の hint が死にコードになっていた)。
    instructions: list[tuple] = []
    blank_sections: list[str] = []
    section = ""
    for kind, t in nodes:
        if kind == "para" and HEADING_RE.match(t):
            section = t
        for sent in re.split(r"(?<=。)", t):
            sent = sent.strip()
            if not sent:
                continue
            for kw, cat, hint in INSTRUCTION_PATTERNS:
                if kw in sent:
                    instructions.append((section, cat, hint, sent[:120]))
            if any(k in sent for k in BLANK_MARKERS) and section:
                blank_sections.append(section)

    # 空の様式に印字されている全 text node (= これが「在って正常」な文字の全体)。
    # 空欄判定は「様式に在る文字を引いた残りがあるか」で行う (欄名を焼き込まない)。
    form_texts = sorted({t for _k, t in nodes if len(t) >= 4}, key=len, reverse=True)
    return dict(headings=headings, cells=cells, protected=sorted(protected_labels),
                instructions=instructions, delete_sigs=sorted(set(delete_sigs)),
                blank_sections=sorted(set(blank_sections)), form_texts=form_texts)


def read_pdf_text(path: Path) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("⚠️  PyMuPDF 未導入のため PDF 検査を skip (pip install pymupdf)", file=sys.stderr)
        return ""
    if not path.exists():
        die(f"PDF が見つからない: {path}")
    try:
        doc = fitz.open(path)
    except Exception as e:                      # noqa: BLE001 — fitz は多様な例外を投げる
        die(f"PDF として読めない: {path} ({e})")
    return "".join(page.get_text() for page in doc)


# ── 検査本体 ─────────────────────────────────────────────────────────────────
def check_form_skeleton(form: dict, pdf_text: str) -> list[tuple]:
    """様式に印字されていた見出し・ラベルが、組み直した PDF に生き残っているか。

    様式が「削除することなく」等で明示保護した欄 (= `protected`) の消失は 🔴。
    それ以外の見出し・表ラベルの消失は 🟠 (意図的に持たない様式構成もあるため)。
    """
    out = []
    if not pdf_text:
        return out
    hay = nfkc(pdf_text)
    protected = {nfkc(p) for p in form["protected"]}

    def missing(label: str) -> bool:
        n = nfkc(label)
        return len(n) >= 4 and n not in hay

    seen = set()
    for label in form["headings"] + form["cells"]:
        if label in seen:
            continue
        seen.add(label)
        if not missing(label):
            continue
        if nfkc(label) in protected:
            out.append(("🔴", "SKELETON_LOST",
                        f"様式が削除を禁じた欄が PDF に無い: 「{label[:60]}」"))
        else:
            out.append(("🟠", "SKELETON_MISSING",
                        f"様式の見出し・ラベルが PDF に無い: 「{label[:60]}」"))
    return out


def check_instruction_residue(form: dict, pdf_text: str) -> list[tuple]:
    """様式が「提出時に削除せよ」と言っているブロックが、提出版に残っていないか。

    [#form-template-integrity](kakenhi-proposal.md) の裏返し — 骨格は消してはいけないが、
    注意書き・記入要領は**消さなければいけない**。組み直し運用では前者が、様式を埋める
    運用では後者が起きる。2026-06 の実例では、事務が削除を求めた記入要領が提出版に残り、
    phrase list ベースの検証を 2 度すり抜けた (list に無い文言は見えない)。
    """
    out = []
    if not pdf_text or not form.get("delete_sigs"):
        return out
    hay = nfkc(pdf_text)
    for sig in form["delete_sigs"]:
        if nfkc(sig) in hay:
            out.append(("🔴", "INSTRUCTION_RESIDUE",
                        f"様式が削除を求めた注意書きが提出版に残っている: 「{sig[:60]}」"))
    return out


def _is_chromatic(color: int, min_chroma: int = 40) -> bool:
    """「意味を持つ色」だけを拾う (= 無彩色を捨てる)。

    黒だけを除くと本文まで拾ってしまう — markdown 由来 PDF の本文は #111111、
    スキャン誌面は #231f20、arXiv の stamp は #7f807f、白抜きは #ffffff。
    どれも「色で意味を持つ要素」ではないので、彩度 (max-min) で切る。
    赤 #ff0000 = 255 / 青 #0070c0 = 192 は通り、上記の無彩色は落ちる。
    """
    r, g, b = (color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF
    return max(r, g, b) - min(r, g, b) >= min_chroma


def check_colored_text(paths: list[Path]) -> list[tuple]:
    """提出版 PDF に非黒の文字が無いか (= 記入要領の色字・著者注・消し忘れ)。

    色で意味を持つ要素の検証は **PDF render の span 色を ground truth** にする。
    docx 側の run 属性は style 継承で嘘をつく (2026-06 実例: 段落 style が色を定義し
    run には `w:color` が無いため、run 色だけを見る判定が 10 段落を見落とした)。
    審査はモノクロ配布なので、色を残す利得はそもそも無い。

    ⚠️ 対象は **提出物** に限る。公募要領・受領論文・見積書に当てると当然すべて発火する
    (それらは色で意味を持つのが正常)。呼ぶ側が渡す PDF を提出物に絞ること。
    """
    out = []
    try:
        import fitz
    except ImportError:
        return out
    for path in paths:
        buckets: dict[int, list[str]] = {}
        for page in fitz.open(path):
            for blk in page.get_text("dict")["blocks"]:
                for line in blk.get("lines", []):
                    for sp in line.get("spans", []):
                        if sp["text"].strip() and _is_chromatic(sp["color"]):
                            buckets.setdefault(sp["color"], []).append(sp["text"].strip())
        for color, texts in buckets.items():
            uniq = list(dict.fromkeys(texts))
            out.append(("🟠", "COLORED_TEXT",
                        f"{path.name}: 有彩色の文字 #{color:06x} × {len(uniq)} 種 "
                        f"(例「{uniq[0][:30]}」) — 記入要領の色字 / 著者注の消し忘れでないか"))
    return out


def check_blank_sections(form: dict, pdf_text: str) -> list[tuple]:
    """様式が「空欄のまま提出」と指定した欄に、書いてしまっていないか。

    ⚠️ 「該当しない場合」の扱いは**欄ごとに逆**。人権の欄は「その旨記述」= 書く、
    最終年度前年度応募の欄は「空欄のまま提出」= 書かない。**丁寧に埋めたことが誤りになる**
    欄があるので、様式のどの文がどの欄を支配しているかを見て判定する
    (欄名を焼き込まない = 様式が変わっても効く)。

    判定: 当該見出しから次の見出しまでを PDF から切り出し、**様式自身が持つラベル**
    (研究種目名 / 課題番号 等) を除いた残りに実質的な文字が残っていれば flag。
    """
    out = []
    if not pdf_text or not form.get("blank_sections"):
        return out
    hay = nfkc(pdf_text)
    heads = [(nfkc(h), h) for h in form["headings"]]
    positions = []
    for norm, orig in heads:
        i = hay.find(norm)
        if i >= 0:
            positions.append((i, norm, orig))
    positions.sort()

    # 「在って正常」= 空の様式に印字されている文字すべて (見出し・ラベル・指示書き)。
    # ⚠️ 短いラベルだけを引くと、様式自身の**指示書き**が残って偽陽性になる (実測)。
    known = sorted({nfkc(t) for t in form.get("form_texts", [])}
                   | {nfkc(c) for c in form.get("cells", [])},
                   key=len, reverse=True)
    for idx, (start, norm, orig) in enumerate(positions):
        if orig not in form["blank_sections"]:
            continue
        end = positions[idx + 1][0] if idx + 1 < len(positions) else len(hay)
        region = hay[start + len(norm):end]
        for kn in known:                      # 様式に在る文字は引く (長い順)
            if len(kn) >= 4:
                region = region.replace(kn, "")
        # 残った断片から、様式の記入枠が持つ定型 (年度表記・記号) を落とす
        region = re.sub(r"[\s　0-9０-９年度令和～~\-・.,、。()（）「」【】：:]+", "", region)
        if len(region) >= 4:
            out.append(("🟠", "BLANK_SECTION_FILLED",
                        f"様式が「空欄のまま提出」と指定した欄に記述がある: "
                        f"「{orig[:40]}」 → 「{region[:40]}」 "
                        f"(⚠️「該当しない」と書くのも誤り。別の欄では逆に書くのが正解)"))
    return out


def check_pdf_text(pdf_text: str, label: str = "") -> list[tuple]:
    """表記 lint。label = どの PDF 由来かを message 頭に出す (--pdf は複数取れるため)。"""
    out = []
    if not pdf_text:
        return out
    tag = f"{label}: " if label else ""
    flat = nfkc(pdf_text)
    for m in ENTITY_RE.finditer(pdf_text):
        out.append(("🔴", "ENTITY", f"{tag}HTML 実体参照の残置: {m.group(0)}"))
    for ab, full in ABBREV_MAP.items():
        # 正式名称の内側に現れた分は略称ではない (= 位置で除外)
        covered = []
        if full and ab in full:
            start = 0
            while (i := flat.find(full, start)) != -1:
                covered.append((i, i + len(full)))
                start = i + 1
        start = 0
        while (i := flat.find(ab, start)) != -1:
            start = i + 1
            if any(lo <= i and i + len(ab) <= hi for lo, hi in covered):
                continue
            out.append(("🟠", "ABBREV", f"{tag}略称「{ab}」が本文にある → 「{full}」"))
            break
    for m in BARE_NUMBER_RE.finditer(pdf_text):
        n = int(m.group(1))
        if 1900 <= n <= 2100 or len(m.group(1)) < 3:
            continue          # 年号・2 桁は対象外
        if _is_symbol_label(pdf_text, m.start()):
            continue          # 粒子名の質量ラベル Δ(1232) / N(1440) / f(500) 等
        out.append(("🟠", "BARE_NUMBER", f"{tag}裸の括弧数字「{m.group(0)}」= 何の数か書く (例: 被引用 {n})"))
    return out


def _is_symbol_label(text: str, idx: int) -> bool:
    """括弧の直前が「記号」なら、中の数はラベル (粒子の質量等) であって裸の数ではない。

    物理の調書では Δ(1232) / N(1440) / f(500) が必ず出るので、CJK・かな以外の
    文字 (ラテン・ギリシャ・数学記号 ∆ U+2206 等) が直前に来る場合は対象外にする。
    """
    j = idx - 1
    while j >= 0 and text[j] in " \u3000":
        j -= 1
    if j < 0:
        return False
    c = text[j]
    if "\u3040" <= c <= "\u30ff" or "\u4e00" <= c <= "\u9fff":
        return False          # かな・漢字の直後は日本語の丸括弧 = 対象
    return c.isalpha() or unicodedata.category(c).startswith("S")


def load_identity(path: Path) -> dict:
    """ID 値の宣言を読む (schema は docstring の [ID] 節)。

    現行値・旧値 (誤りと確定したもの)・提出 file 名に埋めるコードを受け取る。
    ⚠️ 旧値を**消さずに宣言し続ける**のが要点 — 消すと「提出物に旧値が残っていないか」を
    機械が見られなくなる (捨てた情報は検査できない)。
    """
    if not path.exists():
        die(f"identity file が見つからない: {path}")
    try:
        import yaml
    except ImportError:
        die("identity file を読むには PyYAML が要る (pip install pyyaml)")
    data = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("identity") or {}
    if not data.get("current") and not data.get("superseded"):
        die(f"{path.name}: identity.current も identity.superseded も無い")
    return data


# 提出 file 名に埋め込まれたコード (例 「様式1_研究計画調書_<機関コード>_<氏名>.xlsx」)。
# 区切りは全角アンダースコアもある。
# ⚠️ **桁数では判定しない** — staging の file 名には日付 (`_20260908_`) や hash が入るので、
#    「N 桁の数字」を ID とみなすと 🔴 の偽陽性で提出が止まる (実測)。
#    判定は **宣言された ID 値と一致するか** で行う (= 値駆動、形式駆動にしない)。
_FNAME_TOKEN_RE = re.compile(r"[_＿]([0-9A-Za-z]{4,12})[_＿]")


def check_identity(ident: dict, pdf_texts: list[tuple], csv_paths: list[Path],
                   all_paths: list[Path]) -> list[tuple]:
    """誤りと確定した ID が提出物に残っていないか / file 名のコードが宣言値か。

    2026 年度に 2 度起きた: ① 科研費の機関番号 (5 桁) を e-Rad 機関コード欄と file 名に書いた
    ② 口頭指示から推定した 10 桁が誤りで、そのまま提出・受理された。どちらも「値を突き合わせれば
    機械で分かる」類。
    """
    out = []
    stale = ident.get("superseded") or []
    haystacks = [(name, nfkc(text)) for name, text in pdf_texts]
    for c in csv_paths:
        try:
            haystacks.append((c.name, nfkc(_decode_csv(c))))
        except SystemExit:
            continue
    for sp in stale:
        val = str(sp.get("value", "")).strip()
        if not val:
            continue
        label = sp.get("label") or "旧 ID"
        for name, hay in haystacks:
            if nfkc(val) in hay:
                out.append(("🔴", "IDENTITY_STALE",
                            f"{name}: 誤りと確定した{label} 「{val}」 が中身に残っている"))
        for path in all_paths:
            if val in path.name:
                out.append(("🔴", "IDENTITY_STALE",
                            f"{path.name}: file 名に誤りと確定した{label} 「{val}」"))

    want = ident.get("filename_code")
    if want:
        # 「宣言された別の ID」が file 名のコード位置に入っている = 種類の取り違え。
        # superseded は上で IDENTITY_STALE として報告済なのでここでは扱わない (二重報告の回避)。
        others = {str(v): k for k, v in (ident.get("current") or {}).items()
                  if str(v) != str(want)}
        for path in all_paths:
            for m in _FNAME_TOKEN_RE.finditer(path.name):
                tok = m.group(1)
                if tok in others:
                    out.append(("🔴", "IDENTITY_FILENAME",
                                f"{path.name}: file 名のコード位置に 「{tok}」 "
                                f"(= {others[tok]}) が入っている — ここは 「{want}」"))
    return out


def _decode_csv(path: Path) -> str:
    if not path.exists():
        die(f"経費明細 CSV が見つからない: {path}")
    raw = path.read_bytes()
    for enc in ("cp932", "utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    die(f"CSV のエンコーディングを判定できない: {path}")


def check_keihi(path: Path) -> list[tuple]:
    """経費明細 CSV の粒度・費目帰属・byte 上限。

    列は電子申請システムの取込フォーマット:
      費目区分 / 年度 / 品名・仕様 / 設置機関 / 事項 / 数量 / 単価 / 金額
    """
    out = []
    rows = list(csv.reader(io.StringIO(_decode_csv(path))))
    if not rows:
        return [("🔴", "KEIHI_EMPTY", f"{path.name}: 行が無い")]
    body = rows[1:] if rows[0] and "費目" in rows[0][0] else rows
    if not any(len(r) >= 8 and r[0].strip() for r in body):
        return [("🔴", "KEIHI_SCHEMA",
                 f"{path.name}: 取込フォーマット (8 列: 費目区分/年度/品名・仕様/設置機関/"
                 f"事項/数量/単価/金額) の行が 1 つも無い — 別 file か、列がずれている")]
    amount_rows: list[tuple] = []
    for i, r in enumerate(body, start=1):
        if len(r) < 8 or not r[0].strip():
            continue
        cat, fy, spec, _inst, item = r[0].strip(), r[1].strip(), r[2].strip(), r[3].strip(), r[4].strip()
        amount_rows.append((cat, fy, item, r[7].strip()))
        where = f"{path.name} {fy} {CAT_NAMES.get(cat, cat)} 行{i}"
        text = spec or item

        if item and nbytes(item) > 72:
            out.append(("🔴", "KEIHI_FIELD_BYTES",
                        f"{where}: 事項 {nbytes(item)} バイト > 72 「{item}」"))
        if WAVEDASH_RE.search(text):
            out.append(("🔴", "KEIHI_WAVEDASH", f"{where}: 波ダッシュ 「{text}」"))

        if cat == "A":
            if not spec:
                out.append(("🟠", "KEIHI_SPEC_MISSING", f"{where}: 設備備品費に品名・仕様が無い"))
            elif not SPEC_RE.search(spec):
                out.append(("🟠", "KEIHI_SPEC_MISSING",
                            f"{where}: 品名・型番まで書く 「{spec}」 (例: 「〜用計算機・〈製品名/メモリ〉相当」)"))
        if cat in ("C", "D") and item and not TRAVEL_DETAIL_RE.search(item):
            out.append(("🟠", "KEIHI_TRAVEL_DETAIL",
                        f"{where}: 旅費の事項に場所・回数・日数・人数が無い 「{item}」"))
        if cat in ("C", "D") and item and TRAVEL_MISFIT_RE.search(item):
            out.append(("🟠", "KEIHI_CATEGORY",
                        f"{where}: 旅費の行に旅費でないもの 「{item}」 "
                        f"(= 参加登録料・投稿料は「その他」へ)"))
        if cat == "F" and item and DOUBLE_COUNT_RE.search(item):
            out.append(("🟠", "KEIHI_DOUBLE_COUNT",
                        f"{where}: 「その他」に旅費相当 「{item}」 (旅費との二重計上)"))
        if item:
            for rx, want, why in CATEGORY_RULES:
                if rx.search(item) and cat != want:
                    if want == "F" and cat == "D" and DOUBLE_COUNT_RE.search(item):
                        continue  # 招聘旅費に含まれる渡航・滞在費は D で正しい
                    out.append(("🟠", "KEIHI_CATEGORY",
                                f"{where}: {why} — 現在は「{CAT_NAMES.get(cat, cat)}」 「{item}」"))
                    break
            parts = [p for p in SPLIT_RE.split(item) if p.strip()]
            if len(parts) >= 2:
                hits = {want for p in parts for rx, want, _ in CATEGORY_RULES if rx.search(p)}
                if len(hits) >= 2:
                    out.append(("🟠", "KEIHI_MULTI_ITEM",
                                f"{where}: 1 行に異種の事項 「{item}」 (行を分ける)"))
    out += check_keihi_amount_consistency(amount_rows, path)
    return out


def check_keihi_amount_consistency(rows: list[tuple], path: Path) -> list[tuple]:
    """同じ事項なのに年度で金額が違う行を拾う。

    事務は必ず「同一日数ですが旅費が異なりますが、よろしいでしょうか。**異なる理由は
    必要性の欄に**ご記入ください」「前年までと異なりますが、最終年度のためでしょうか」と聞く
    (2025-09 実測)。金額が合っていても説明が無ければ差し戻し事由になる。

    ⚠️ 「違うのが誤り」ではない — **理由が書いてあるか**が論点なので 🟠 に留める。
    """
    out = []
    by_item: dict[tuple, dict[str, set]] = {}
    for cat, fy, item, amt in rows:
        if not item or not amt:
            continue
        by_item.setdefault((cat, nfkc(item)), {}).setdefault("amts", set()).add(amt)
        by_item[(cat, nfkc(item))].setdefault("fys", set()).add(fy)
    for (cat, item), d in sorted(by_item.items()):
        if len(d["amts"]) > 1 and len(d["fys"]) > 1:
            amts = ", ".join(sorted(d["amts"], key=lambda x: int(x) if x.isdigit() else 0))
            out.append(("🟠", "KEIHI_AMOUNT_VARY",
                        f"{path.name} {CAT_NAMES.get(cat, cat)}: 同じ事項が年度で違う金額 "
                        f"({amts}) 「{item[:34]}」 — 異なる理由を必要性欄に書いたか"))
    return out


# ── 出力 ─────────────────────────────────────────────────────────────────────
def load_acks(path: Path) -> list[dict]:
    """🟠 を明示的に受理した記録を読む。

    schema (yaml):
        acks:
          - code: ABBREV                 # finding の code (必須)
            match: 略称「文科省」          # message の部分一致 (必須、空文字は不可)
            reason: YYYY-MM-DD ...        # なぜ直さないか (必須)
            scope: kiban_b.pdf            # 任意。message に含まれること (= 種目に縛る)
            until: 'YYYY-MM-DD'           # 任意。この日を過ぎたら ack 失効 = 再び fail
    🔴 は ack できない (= 様式違反・保存不能・実体参照は必ず直す)。
    ⚠️ scope を書かないと **別種目の同じ指摘まで黙る** — PDF 由来の finding は常に由来 file 名を
       持つので、種目ごとに直すつもりなら scope に file 名を書く (over-broad は下で警告する)。
    """
    if not path.exists():
        die(f"ack file が見つからない: {path}")
    try:
        import yaml
    except ImportError:
        die("ack file を読むには PyYAML が要る (pip install pyyaml)")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    acks = data.get("acks") or []
    for i, a in enumerate(acks, 1):
        for k in ("code", "match", "reason"):
            if not str(a.get(k, "")).strip():
                die(f"{path.name}: acks[{i}] に `{k}` が無い "
                    f"(理由の書かれていない ack は受け付けない)")
    return acks


def apply_acks(findings: list[tuple], acks: list[dict], today: str) -> tuple[list, list, list]:
    """findings を (未 ack, ack 済, 使われなかった ack) に分ける。

    ⚠️ ack 済も出力からは消さない (= 見えなくなったら「直した」と区別がつかない)。
    """
    live, acked = [], []
    used = set()
    for sev, code, msg in findings:
        hit = None
        for j, a in enumerate(acks):
            if a["code"] != code or a["match"] not in msg:
                continue
            if a.get("scope") and str(a["scope"]) not in msg:
                continue
            if a.get("until") and str(a["until"]) < today:
                continue                      # 期限切れ ack = 効かない
            hit = (j, a)
            break
        if hit and sev != "🔴":               # 🔴 は ack 不可
            used.add(hit[0])
            acked.append((sev, code, msg, hit[1]))
        else:
            live.append((sev, code, msg))
    stale = [a for j, a in enumerate(acks) if j not in used]
    return live, acked, stale


def overbroad_acks(acked: list[tuple]) -> list[tuple]:
    """1 つの ack が複数の対象 (= 別 PDF 由来) を黙らせていないか。

    「この種目は見送る」つもりの ack が、scope 未指定のせいで別種目の同じ指摘まで
    受理してしまう事故を検出する (= 種目間の横展開漏れを ack 自身が作る)。
    """
    by_reason: dict[str, set] = {}
    for _sev, _code, msg, a in acked:
        if a.get("scope"):
            continue
        src = msg.split(":", 1)[0] if ":" in msg else ""
        by_reason.setdefault(a["match"] + "|" + a["reason"], set()).add(src)
    return [(k.split("|")[0], srcs) for k, srcs in by_reason.items() if len(srcs) > 1]


def report(findings: list[tuple], instructions: list[tuple] | None,
           acks: list[dict] | None = None, strict: bool = False,
           today: str | None = None) -> int:
    if instructions:
        print("── 様式に埋め込まれた指示 (1 つずつ適用を verify する) " + "─" * 20)
        seen = set()
        for section, cat, hint, sent in instructions:
            key = (section, cat, hint)
            if key in seen:
                continue
            seen.add(key)
            where = f"{section[:28]} / " if section else ""
            print(f"  ℹ️ [{where}{cat}] {hint}")
            print(f"     └ 様式: {sent}")
        print()
    today = today or __import__("datetime").date.today().isoformat()
    acked, stale = [], []
    if acks is not None:
        findings, acked, stale = apply_acks(findings, acks, today)

    if acked:
        print("── 受理済 (ack file に理由つきで記録された 🟠) " + "─" * 16)
        for sev, code, msg, a in acked:
            print(f"  🤝 {code}: {msg}")
            print(f"     └ {a['reason']}" + (f" [期限 {a['until']}]" if a.get("until") else ""))
        print()
    for match, srcs in overbroad_acks(acked):
        print(f"  🧨 ack 「{match}」 が複数の対象を黙らせている: {', '.join(sorted(srcs))}")
        print("     → 種目ごとに直すなら ack に `scope: <PDF file 名>` を足して分ける\n")
    if stale:
        print("── 使われなかった ack (= 直ったのに記録が残っている / match が古い) " + "─" * 4)
        for a in stale:
            print(f"  🧹 {a['code']}: 「{a['match']}」 — {a['reason']}")
        print("  → 直ったなら ack file から消す (残すと次の本物を隠す)\n")

    if not findings:
        print("✅ 未処理の検出なし" + (" (受理済を除く)" if acked else ""))
        return 0
    hard = [f for f in findings if f[0] == "🔴"]
    soft = len(findings) - len(hard)
    print("── 検出 " + "─" * 52)
    for sev, code, msg in sorted(findings, key=lambda f: (f[0] != "🔴", f[1])):
        print(f"  {sev} {code}: {msg}")
    print(f"\n🔴 {len(hard)} 件 / 🟠 {soft} 件")
    if strict:
        print("⛔ --strict: 🟠 も「直す」か「ack file に理由つきで記録する」まで提出しない "
              "(= 2026-09 に 🟠 相当の指摘を種目間で横展開し損ねた再発防止)")
        return 1 if findings else 0
    print("🟠 は誤検出もある — 潰すか、理由を書いて残すかを人が決める "
          "(正本: kakenhi-proposal.md#office-review-loop)")
    return 1 if hard else 0


# ── selftest (2026-09 の差し戻し実例を before/after で回帰させる) ─────────────
def selftest() -> int:
    import tempfile

    ok = True

    def expect(name, got_codes, want, forbid=()):
        nonlocal ok
        miss = [w for w in want if w not in got_codes]
        extra = [f for f in forbid if f in got_codes]
        if miss or extra:
            ok = False
            print(f"  ✗ {name}: 欠 {miss} / 余 {extra} (got {sorted(set(got_codes))})")
        else:
            print(f"  ✓ {name}")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)

        # --- 経費明細: 差し戻し前 (赤字を受けた形) ---
        before = td / "before.csv"
        before.write_text(
            "費目区分,年度,品名・仕様,設置機関,事項,数量,単価,金額\n"
            "A,2027,数値計算用計算機,東京都内,,1,1000,1000\n"
            "B,2027,,,数式処理ソフトウェアライセンス,,,60\n"
            "C,2027,,,国内研究会での成果発表,,,250\n"
            "E,2027,,,英文校閲・RA謝金,,,70\n"
            "F,2027,,,研究会開催費（会場費・招聘者滞在費）,,,150\n"
            "F,2027,,,論文投稿・掲載料、クラウド計算資源利用料,,,100\n"
            "C,2027,,,国際共同研究の相互訪問に伴う研究打合せおよび成果発表のための出張旅費（年2回、各3泊4日、1名）,,,200\n",
            encoding="utf-8")
        codes = [c for _, c, _ in check_keihi(before)]
        expect("経費 before: 品名・型番なし", codes, ["KEIHI_SPEC_MISSING"])
        expect("経費 before: ライセンスが消耗品費", codes, ["KEIHI_CATEGORY"])
        expect("経費 before: 旅費に日数・人数なし", codes, ["KEIHI_TRAVEL_DETAIL"])
        expect("経費 before: その他に滞在費 (二重計上)", codes, ["KEIHI_DOUBLE_COUNT"])
        expect("経費 before: 1 行に異種", codes, ["KEIHI_MULTI_ITEM"])
        expect("経費 before: 事項 72 バイト超", codes, ["KEIHI_FIELD_BYTES"])

        # --- 経費明細: 差し戻し後 (修正した形) ---
        after = td / "after.csv"
        after.write_text(
            "費目区分,年度,品名・仕様,設置機関,事項,数量,単価,金額\n"
            "A,2027,ワークステーション（数値計算用）・Xeon w5/メモリ128GB 相当,○○大学,,1,1000,1000\n"
            "B,2027,,,専門書・文献,,,45\n"
            "C,2027,,,国内研究会での成果発表（年3回、各2泊3日、1名）,,,250\n"
            "D,2027,,,海外研究者の招聘旅費（欧州から1名、7日間：航空券・滞在費）,,,200\n"
            "E,2027,,,数値計算補助のRA謝金（博士後期課程学生）,,,40\n"
            "F,2027,,,英文校閲（業者委託）,,,30\n"
            "F,2027,,,論文投稿料,,,30\n"
            "F,2027,,,クラウド計算資源利用料,,,40\n"
            "F,2027,,,研究会開催費（会場費）,,,150\n",
            encoding="utf-8")
        codes = [c for _, c, _ in check_keihi(after)]
        expect("経費 after: 全 clean", codes, [],
               forbid=["KEIHI_SPEC_MISSING", "KEIHI_CATEGORY", "KEIHI_TRAVEL_DETAIL",
                       "KEIHI_DOUBLE_COUNT", "KEIHI_MULTI_ITEM", "KEIHI_FIELD_BYTES"])

        # --- 表記 lint ---
        codes = [c for _, c, _ in check_pdf_text(
            "本研究は文科省の事業で……ヒッグス・インフレーション[12]（160）……令和９(2027)年度……")]
        expect("表記: 略称", codes, ["ABBREV"])
        expect("表記: 裸の括弧数字", codes, ["BARE_NUMBER"])
        codes = [c for _, c, _ in check_pdf_text("文部科学省の事業。被引用 160。(2027) 年度。")]
        expect("表記: 正しい形は clean", codes, [], forbid=["ABBREV", "BARE_NUMBER"])
        # 略称が正式名称の部分文字列になる組 (2026 年度の申請書で踏んだ偽陽性)
        codes = [c for _, c, _ in check_pdf_text("独立行政法人日本学術振興会の特別研究員制度。")]
        expect("表記: 正式名称の内側は略称でない", codes, [], forbid=["ABBREV"])
        codes = [c for _, c, _ in check_pdf_text("学振の特別研究員を受け入れる。")]
        expect("表記: 素の略称は拾う", codes, ["ABBREV"])
        # 粒子名の質量ラベルは裸の数字ではない (物理の調書で必ず出る偽陽性)
        codes = [c for _, c, _ in check_pdf_text(
            "Δ(1232) 等のハドロン共鳴、N(1440)、∆(1232) も同様。")]
        expect("表記: 粒子名は偽陽性にしない", codes, [], forbid=["BARE_NUMBER"])
        codes = [c for _, c, _ in check_pdf_text("経費は 1&#12316;2 万円")]
        expect("表記: 実体参照", codes, ["ENTITY"])

        # --- 様式骨格: 欄が消えた PDF を検出できるか ---
        form = dict(
            headings=["４　研究計画最終年度前年度応募を行う場合の記述事項",
                      "２　応募者の研究遂行能力及び研究環境"],
            cells=["研究種目名", "課題番号", "研究期間"],
            protected=["４　研究計画最終年度前年度応募を行う場合の記述事項", "研究期間"],
            instructions=[])
        lost = check_form_skeleton(form, "２ 応募者の研究遂行能力及び研究環境\n本文……")
        expect("骨格: 保護欄の消失は 🔴", [c for _, c, _ in lost], ["SKELETON_LOST"])
        expect("骨格: 表ラベルの消失", [c for _, c, _ in lost], ["SKELETON_MISSING"])
        # 色の判定: 無彩色 (本文の #111111 / スキャンの #231f20 / 白 / 灰) を拾わない
        for c, want in [(0x000000, False), (0x111111, False), (0x231f20, False),
                        (0x7f807f, False), (0xffffff, False),
                        (0xff0000, True), (0x0070c0, True)]:
            got = _is_chromatic(c)
            expect(f"色: #{c:06x} は {'拾う' if want else 'skip'}",
                   ["ok"] if got == want else [], ["ok"])

        # 「空欄のまま提出」欄に書いてしまう (2024 実測: 「該当しない。」→「トル」)
        # ⚠️ 欄名は焼き込まない。様式のどの文がどの欄を支配しているかで判定する。
        form_blank = dict(
            headings=["３　人権の保護", "４　最終年度前年度応募を行う場合の記述事項", "５　次の欄"],
            cells=["研究種目名", "課題番号"], protected=[], instructions=[], delete_sigs=[],
            blank_sections=["４　最終年度前年度応募を行う場合の記述事項"],
            form_texts=["該当しない場合は記述欄を削除することなく、空欄のまま提出すること。",
                        "本研究の研究代表者が行っている継続研究課題について記述すること。"])
        clean_pdf = ("３ 人権の保護\n該当しない。\n"
                     "４ 最終年度前年度応募を行う場合の記述事項\n"
                     "本研究の研究代表者が行っている継続研究課題について記述すること。\n"
                     "研究種目名 課題番号\n５ 次の欄\n")
        expect("空欄欄: 空のままなら clean",
               [c for _, c, _ in check_blank_sections(form_blank, clean_pdf)], [],
               forbid=["BLANK_SECTION_FILLED"])
        bad_pdf = clean_pdf.replace("研究種目名 課題番号", "研究種目名 課題番号\n該当しない。")
        expect("空欄欄: 「該当しない」と書いたら 🟠",
               [c for _, c, _ in check_blank_sections(form_blank, bad_pdf)],
               ["BLANK_SECTION_FILLED"])
        expect("空欄欄: 別の欄 (その旨記述) は対象外",
               [m for _, _, m in check_blank_sections(form_blank, bad_pdf) if "人権" in m], [])

        # 記入要領の消し忘れ (2026-06 LOTUS 型): 様式が削除を求めた文が提出版に残る
        form_del = dict(headings=[], cells=[], protected=[], instructions=[],
                        delete_sigs=["以下の内容を熟読・理解の上、研究計画調書を作成すること。",
                                     "本文は11ポイント以上の大きさの文字等を使用すること。"])
        res = check_instruction_residue(
            form_del, "……概要……\n以下の内容を熟読・理解の上、研究計画調書を作成すること。\n……")
        expect("消し忘れ: 残存を 🔴 で検出", [c for _, c, _ in res], ["INSTRUCTION_RESIDUE"])
        expect("消し忘れ: 1 文だけ残っていたら 1 件", ["n%d" % len(res)], ["n1"])
        res = check_instruction_residue(form_del, "……概要……本文は 12 ポイントで組んだ……")
        expect("消し忘れ: 消してあれば clean", [c for _, c, _ in res], [],
               forbid=["INSTRUCTION_RESIDUE"])
        expect("消し忘れ: 約物の字形置換を吸収する (・ → ·)",
               [c for _, c, _ in check_instruction_residue(
                   form_del, "以下の内容を熟読·理解の上、研究計画調書を作成すること。")],
               ["INSTRUCTION_RESIDUE"])
        expect("消し忘れ: 空白の揺れを吸収する",
               [c for _, c, _ in check_instruction_residue(
                   form_del, "本文は 11 ポイント 以上 の 大きさ の 文字等 を 使用すること。")],
               ["INSTRUCTION_RESIDUE"])

        kept = check_form_skeleton(form, "４ 研究計画最終年度前年度応募を行う場合の記述事項\n"
                                         "２ 応募者の研究遂行能力及び研究環境\n"
                                         "研究種目名 課題番号 研究期間")
        expect("骨格: 全部あれば clean", [c for _, c, _ in kept], [],
               forbid=["SKELETON_LOST", "SKELETON_MISSING"])

        # 2025-09 の実例: 同じ事項が年度で違う金額 (旅費 240/430、OA 250→200) を
        # 「異なる理由は必要性の欄に」と問われた
        vary = td / "vary.csv"
        vary.write_text(
            "費目区分,年度,品名・仕様,設置機関,事項,数量,単価,金額\n"
            "D,2027,,,国際会議での成果発表（欧州、7日間、1名）,,,240\n"
            "D,2028,,,国際会議での成果発表（欧州、7日間、1名）,,,430\n"
            "C,2027,,,学会発表（年2回、各2泊3日、1名）,,,250\n"
            "C,2028,,,学会発表（年2回、各2泊3日、1名）,,,250\n", encoding="utf-8")
        codes = [c for _, c, _ in check_keihi(vary)]
        expect("経費: 同じ事項が年度で違う金額を拾う", codes, ["KEIHI_AMOUNT_VARY"])
        n = len([1 for _, c, _ in check_keihi(vary) if c == "KEIHI_AMOUNT_VARY"])
        expect("経費: 金額が同じ年度違いは拾わない", ["n%d" % n], ["n1"])

        # 2026-07 の実例: 旅費の行に参加登録料が混ざっていた
        mis = td / "misfit.csv"
        mis.write_text(
            "費目区分,年度,品名・仕様,設置機関,事項,数量,単価,金額\n"
            "D,2027,,,国際会議発表 1 件（登録料・渡航・滞在、7日間、1名）,,,450\n"
            "F,2027,,,参加登録料,,,50\n", encoding="utf-8")
        codes = [c for _, c, _ in check_keihi(mis)]
        expect("経費: 旅費行の参加登録料を拾う", codes, ["KEIHI_CATEGORY"])
        ok_f = "KEIHI_CATEGORY" not in [c for _, c, m in check_keihi(mis) if "行2" in m]
        expect("経費: 「その他」の参加登録料は正当", ["ok"] if ok_f else [], ["ok"])

        # --- identity: 2026 年度に 2 度起きた ID 取り違えの回帰 ---
        IDENT = dict(current={"e-Rad 所属機関コード": "1234567890",
                              "機関番号 (科研費)": "55555"},
                     filename_code="1234567890",
                     superseded=[dict(value="9876543210", label="旧 e-Rad 所属機関コード",
                                      note="後に誤りと確定")])

        def ident(pdfs=(), files=()):
            return [c for _, c, _ in check_identity(
                IDENT, list(pdfs), [], [Path(f) for f in files])]

        # ① 推定した 10 桁が誤りで、そのまま提出・受理された
        expect("ID: 旧値が中身に残る → 🔴",
               ident(pdfs=[("chosho.pdf", "機関コード 9876543210 ○○大学")]),
               ["IDENTITY_STALE"])
        expect("ID: 旧値が file 名に残る → 🔴",
               ident(files=["様式1_研究計画調書_9876543210_Name.xlsx"]),
               ["IDENTITY_STALE"])
        # ② 科研費の機関番号を e-Rad 機関コードの位置 (file 名) に書いた
        expect("ID: file 名に別 ID を書いた → 🔴",
               ident(files=["様式1_研究計画調書_55555_Name.xlsx"]),
               ["IDENTITY_FILENAME"])
        expect("ID: 全角アンダースコアの file 名も見る",
               ident(files=["様式0＿申請様式チェックリスト＿55555＿Name.docx"]),
               ["IDENTITY_FILENAME"])
        # 🔴 の偽陽性は提出を止めるので、桁数では判定しない (staging の日付・hash)
        expect("ID: file 名の日付・hash を ID と誤認しない",
               ident(files=["S-13_kiban_b_20260908_fc1f7257.pdf",
                            "S-74_gakuhen_26A204_20260908_69a992c6.pdf"]),
               [], forbid=["IDENTITY_FILENAME", "IDENTITY_STALE"])
        expect("ID: 旧値は STALE のみ (FILENAME と二重に出さない)",
               ident(files=["様式1_研究計画調書_9876543210_Name.xlsx"]),
               ["IDENTITY_STALE"], forbid=["IDENTITY_FILENAME"])
        # 正しい形
        expect("ID: 正しい値なら clean",
               ident(pdfs=[("chosho.pdf", "機関コード 1234567890")],
                     files=["様式1_研究計画調書_1234567890_Name.xlsx"]),
               [], forbid=["IDENTITY_STALE", "IDENTITY_FILENAME"])
        # 機関番号 32652 は本文中では正当 (= 素の出現を叩かない)
        expect("ID: 現行の別 ID が本文にあるのは正当",
               ident(pdfs=[("chosho.pdf", "科研費 機関番号 55555 の○○大学")]),
               [], forbid=["IDENTITY_STALE", "IDENTITY_FILENAME"])

        # --- ack / strict: 「🟠 を素通りさせない」機構の回帰 ---
        import io as _io, contextlib as _ctx

        def run_report(fs, acks, strict, today="2026-09-10"):
            buf = _io.StringIO()
            with _ctx.redirect_stdout(buf):
                rc = report(list(fs), None, acks, strict, today)
            return rc, buf.getvalue()

        F_SOFT = [("🟠", "ABBREV", "略称「文科省」が本文にある → 「文部科学省」")]
        F_HARD = [("🔴", "SKELETON_LOST", "様式が削除を禁じた欄が PDF に無い: 「研究期間」")]
        ACK_OK = [dict(code="ABBREV", match="略称「文科省」", reason="2026-09-10 user 判断")]

        rc, _ = run_report(F_SOFT, None, False)
        expect("ack: 🟠 のみ + 非 strict → 0", ["rc%d" % rc], ["rc0"])
        rc, out = run_report(F_SOFT, [], True)
        expect("ack: 🟠 + strict + ack 無し → 1", ["rc%d" % rc], ["rc1"])
        ok_strict = "⛔" in out
        expect("ack: strict は理由を表示", ["msg"] if ok_strict else [], ["msg"])
        rc, out = run_report(F_SOFT, ACK_OK, True)
        expect("ack: 受理済なら strict でも 0", ["rc%d" % rc], ["rc0"])
        expect("ack: 受理済も出力に残る (消さない)",
               ["shown"] if "🤝" in out else [], ["shown"])
        rc, out = run_report(F_HARD, [dict(code="SKELETON_LOST", match="研究期間",
                                           reason="ごまかし")], True)
        expect("ack: 🔴 は ack できない", ["rc%d" % rc], ["rc1"])
        rc, out = run_report(F_SOFT, [dict(code="ABBREV", match="略称「文科省」",
                                           reason="期限切れ", until="2026-09-01")], True)
        expect("ack: until を過ぎた ack は失効", ["rc%d" % rc], ["rc1"])
        rc, out = run_report([], ACK_OK, True)
        expect("ack: 直ったのに残る ack は 🧹 で報告",
               ["stale"] if "🧹" in out else [], ["stale"])
        # scope: 種目を跨いで黙らせる ack を検出できるか
        F_TWO = [("🟠", "ABBREV", "kiban_b.pdf: 略称「文科省」が本文にある → 「文部科学省」"),
                 ("🟠", "ABBREV", "houga.pdf: 略称「文科省」が本文にある → 「文部科学省」")]
        rc, out = run_report(F_TWO, ACK_OK, True)
        expect("ack: scope 無しで 2 種目を黙らせたら 🧨",
               ["broad"] if "🧨" in out else [], ["broad"])
        ACK_SCOPED = [dict(code="ABBREV", match="略称「文科省」", scope="kiban_b.pdf",
                           reason="2026-09-10 基盤B のみ見送り")]
        rc, out = run_report(F_TWO, ACK_SCOPED, True)
        expect("ack: scope 付きなら他種目は残る (rc=1)", ["rc%d" % rc], ["rc1"])
        expect("ack: scope 付きは 🧨 を出さない",
               [] if "🧨" not in out else ["broad"], [], forbid=["broad"])
        expect("ack: scope 外の種目が検出に残る",
               ["kept"] if "houga.pdf" in out.split("── 検出")[-1] else [], ["kept"])

    print("\n" + ("✅ selftest PASS" if ok else "❌ selftest FAIL"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--form", type=Path, action="append", default=[],
                    help="様式 docx (骨格・埋め込み指示の source)。種目が複数様式を持つなら繰り返す")
    ap.add_argument("--pdf", type=Path, action="append", default=[],
                    help="組み上がった調書 PDF。様式が複数なら対応する PDF を全部渡す")
    ap.add_argument("--keihi", type=Path, action="append", default=[], help="経費明細 CSV (複数可)")
    ap.add_argument("--identity", type=Path,
                    help="ID 値の宣言 (yaml)。値は呼ぶ側の層が持つ — 本 script は持たない")
    ap.add_argument("--ack", type=Path,
                    help="🟠 を理由つきで受理した記録 (yaml)。🔴 は ack できない")
    ap.add_argument("--strict", action="store_true",
                    help="未 ack の 🟠 が 1 件でも残っていたら exit 1 (= 提出手順に挟む形)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if not (a.form or a.pdf or a.keihi):
        ap.print_help()
        return 2

    findings, instructions = [], None
    # 種目によって様式は複数ある (挑戦的研究の S-42-1 概要版 + S-42-2 本文 等)。
    # 骨格も PDF text も **和集合**で突き合わせる — 概要版の見出しを本文 PDF に探すと
    # 偽の SKELETON_MISSING が出るため、片側だけ渡す運用にしない。
    pdf_texts = [(q.name, read_pdf_text(q)) for q in a.pdf]
    pdf_text = "\n".join(t for _, t in pdf_texts)
    if a.form:
        forms = [read_form(q) for q in a.form]
        merged = dict(headings=[h for f in forms for h in f["headings"]],
                      cells=[c for f in forms for c in f["cells"]],
                      protected=[p for f in forms for p in f["protected"]],
                      instructions=[i for f in forms for i in f["instructions"]])
        merged["delete_sigs"] = sorted({d for f in forms for d in f["delete_sigs"]})
        merged["blank_sections"] = sorted({b for f in forms for b in f["blank_sections"]})
        merged["form_texts"] = sorted({t for f in forms for t in f["form_texts"]},
                                      key=len, reverse=True)
        instructions = merged["instructions"]
        findings += check_form_skeleton(merged, pdf_text)
        findings += check_instruction_residue(merged, pdf_text)
        findings += check_blank_sections(merged, pdf_text)
    for name, t in pdf_texts:
        findings += check_pdf_text(t, name)   # 常に由来を付ける (ack を種目に縛れるように)
    findings += check_colored_text(a.pdf)
    for c in a.keihi:
        findings += check_keihi(c)
    if a.identity:
        findings += check_identity(load_identity(a.identity), pdf_texts, a.keihi,
                                   list(a.pdf) + list(a.keihi))
    acks = load_acks(a.ack) if a.ack else (
        [] if a.strict else None)      # --strict のみ = 空の ack file と同じ扱い
    return report(findings, instructions, acks, a.strict)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
