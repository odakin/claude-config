<!-- doc-meta
when: 同一 file に 3 箇所以上の text 置換をまとめて当てるとき (= Edit tool を N 回叩く代わりに script で一括適用するとき) + 編集 tool で source に `\uXXXX` の escape を書くとき (#tool-arg-unicode-escape)
category: infra
summary: plain-text source への一括置換 script の契約 (= (old, new) pair 列 + 各 old は正確に 1 回 match の assert + read→全 assert→全 replace→単一 write) と 9 つの実測失敗モード (assert の verdict は下流の compile/commit に伝わらない / count==1 は match の一意性を保証するが span の十分性は保証しない = 複数行段落の先頭行だけ置換して新旧両方が印字 / 目視で同じでも trailing space で不一致 / count==0 は typo でなく並行編集による適用済みでもありうる / 1 回一致は prefix 形の key (path・識別子) を守らない = 長い別物の先頭に 1 回だけ一致して誤置換、 終端の区切りまで含めるか構文解析した単位で置換 / 挿入型の pair (new が old を含む) は再実行しても count==1 のまま通って二重に入る = 適用済み検査を足す / TARGET が symlink だと test 用の写しは link 越しに実体へ書き、 一時 file + os.replace は link を普通の file に置き換える = 先に実体の path へ解決する / macOS 付属の python 3.9 は 1023 byte を超える多バイト行を source として読めず Non-UTF-8 の SyntaxError で落ちる = 長い文面は別 file に置いて読む / 計算で作った old 〔slice〕 は終点の anchor が前にも在ると空になり `replace('', new)` が全文字の間に挿入して file が数百倍に膨れる = 終点は始点より後ろで探し、 計算した old にも assert old and count==1、 書いた後に行数の桁を見る、 commit gate = scripts/check-degenerate-text.py。 機械化 = scripts/apply-text-pairs.py)
-->
# Batch text surgery — 一括置換 script の契約と失敗モード

同じ file の複数箇所を `(old, new)` の pair 列で一括置換するときの規約。 対象は plain-text source (`.tex` / `.md` / `.py` / `.yaml` 等) 全般。 核心 = **各 old は file 中に正確に 1 回だけ match する**という契約を、 適用前に全件検査してから初めて書く。

## <a id="batch-text-contract"></a>pattern と契約

```python
txt = open(path, encoding="utf-8").read()
for old, new in pairs:
    n = txt.count(old)
    assert n == 1, f"MATCH {n}: {old[:60]!r}"
    txt = txt.replace(old, new)
open(path, "w", encoding="utf-8").write(txt)
```

- **契約**: 各 `old` は file 中に**正確に 1 回** match する。 0 件 (= typo / 既適用 / 別 file) も 2 件以上 (= 誤爆) も abort。 これは Edit tool の「唯一 match 保証」を N 件へ拡張したもの。 ⚠️ 「既適用なら 0 件」 は置換型の pair でしか成り立たない (挿入型 = [モード 6](#insertion-pair-rerun))。
- **順序が本質**: read → **全 assert** → 全 replace → **単一 write**。 loop 内で write したり `sed -i` を逐次実行すると、 途中で失敗したとき「半分だけ当たった file」が disk に残る。
- **機械化** = [`scripts/apply-text-pairs.py`](../scripts/apply-text-pairs.py) `TARGET PAIRS.py`: 本契約 + [モード 5](#prefix-shaped-key) (old の端が長い token の途中) + [モード 6](#insertion-pair-rerun) (挿入型 pair の再実行) を検査し、 `--test CMD` なら patch 後の写しで test を通してから原子的に書く。 TARGET は必須引数 (既定の path を持たない) で、 最初に実体の path へ解決する ([モード 7](#symlink-target))。

**使い分け**:

| 規模 | 手段 | 理由 |
|---|---|---|
| 1-2 箇所 | Edit tool | 差分がそのまま可視になり人間 review が効く |
| 3 箇所以上 / 長い string / 系統的 sweep | 本 pattern | 手数と転記ミスが線形に増えるのを止める |

## <a id="batch-text-failure-modes"></a>9 つの失敗モード

### <a id="assert-does-not-gate-downstream"></a>1. assert の verdict は下流に伝わらない

**症状**: script が assert で abort したのに後続の compile と commit がそのまま走り、 **変更を主張する message を持つが実体のない commit** が生まれた。

**なぜ起きるか**: shell の**行分離は gate ではない**。 別 statement (agent 環境では別 Bash 呼び出しも) は前段の exit status を見ない。

⚠️ **契約との関係 — 2 つの保証は独立で、片方が他方を代替しない**。 上の atomic write は **file を守る**が、**下流を守らない**。 被害の重さはこう分岐する:

- atomic write **あり** → file は無傷、 被害は「実体のない変更を主張する記録」 (= false record) に限定
- atomic write **なし** (loop 内 write / 逐次 `sed -i`) → 半端に編集された file がそのまま compile を通り commit される

つまり `&&` chain は atomic write の上に重ねる冗長な belt ではなく、 **assert の verdict を下流の行動に接続する唯一の線**。

**対策**: `python3 apply.py && <build> && git commit …` を**単一の `&&` chain** にする。 chain が Bash 呼び出しを跨ぐと切れるので、 1 呼び出しに収めるか exit status を明示的に確認してから次へ進む。

### <a id="span-not-line"></a>2. 置換単位は「行」でなく意味単位

**症状**: 複数行に跨る段落の**先頭行だけ**を置換し、 後半の行が残骸として生き残って、 **新旧両方が出力 (PDF) に印字**された。 発見したのは機械でなく人間の読者。

**なぜ契約が守ってくれないか** (= 本質): `count == 1` が保証するのは **match の一意性**であって **span の十分性**ではない。 先頭行は実際に 1 回しか出現しないので assert は正常に通る。 この失敗モードは契約の**外側**にある。

**対策**: `old` には置き換えたい**意味単位の全域**を入れる (段落なら段落全体)。 加えて適用後に**旧断片を grep して 0 件**を確認する — assert が原理的に cover しない側なので、 検証 sweep から外さない。

### <a id="invisible-whitespace-mismatch"></a>3. 目視で同じ ≠ byte で同じ

**症状**: trailing space 1 個の差で match 失敗 (同一 session 中に 2 回)。

**対策 (予防 — こちらが上流)**: `old` を**手で打ち直さず file から機械的に取る** (= 読み込んだ内容を slice して pair へ渡す)。 目視転記は trailing space・全角空白・NBSP・改行位置を静かに落とす。

**対策 (診断)**: 不一致したら byte を見る (`od -c` / python の `repr()` / `grep -n` で前後を出す)。 **「同じに見える」は証拠にならない**。

<a id="tool-arg-unicode-escape"></a>**書く側の同じ罠 — 編集 tool の引数に書いた `\uXXXX` は実文字になる** (実測): Edit / Write の引数は JSON の文字列なので、 `\u0300` と書くと JSON の escape として解釈され、 file には**結合文字そのもの**が入る (backslash を 2 つ重ねた時だけ escape 表記が残る)。 source の正規表現の文字 class に結合文字や不可視の文字が実文字で入ると、 動作は同じでも、 読めない・diff で見えない・次の `old` の照合が byte で外れる (実測: 後から「その行を 1 回だけ含むはず」 の検査が 0 回になって気づいた)。 escape 表記を file に残したいときは、 **script で行を組み立てて書く** (escape を文字列の連結で作る) か、 書いた後に**その行の非 ASCII を検査する** (`grep -nP '[^\x00-\x7F]' <file>` を正規表現の行に当てる)。

### <a id="zero-count-is-ambiguous"></a>4. count==0 は「typo」とは限らない

**症状**: assert fail を「`old` の typo」と解釈して pattern を書き直したが、 実際は**同じ file を人間がエディタで直接編集していて既に適用済み**だった。

**0 と 2 以上は別の病気**なので、 診断を分ける:

| count | 意味 | 次の手 |
|---|---|---|
| `0` | その形では file に存在しない | typo / whitespace (= モード 3) / **既に適用済み** / そもそも別 file、 を grep で切り分ける |
| `≥2` | anchor が非特異 | 周辺 context を足して一意化する (件数指定で誤魔化さない) |

🚫 **anti-pattern**: fail を「緩めて」通すこと (`replace(old, new, 1)` に変える / 全置換に切り替える / regex を広げる)。 **loud failure を silent な誤置換に変換する**のが最悪の手で、 モード 2 の残骸もこの経路で生まれる。

**対策**: fail したら機械的に retry せず、 まず grep で現物を確認する。 並行編集がありうる環境 (= 人間が同じ file を開いている / 並列 session) では適用直前に `git fetch` と working tree の確認を挟む。

### <a id="prefix-shaped-key"></a>5. 「正確に 1 回」 は prefix 形の key を守らない (2026-09-13)

**症状**: link の path を直す一括置換で `old = "](DESIGN.md"` とした。 本物の `](DESIGN.md)` は file に無く、 別の正しい link `](DESIGN.md.local)` だけが在った。 count は 1 なので契約の assert を**通り**、 正しい link を壊した。 count ≥ 1 で走らせていた版では、 短い key の置換が長い key の link まで書き換え、 後続の assert が 0 件で落ちた (= 途中の file だけ書かれていた)。

**なぜ起きるか**: 契約が数えるのは部分文字列の出現で、 `old` が**トークンの終わり**まで含むことは保証しない。 path・識別子・URL のように「長い別物の先頭」 になりうる key では、 1 回一致が正しい 1 回とは限らない。

**対処**: `old` に**終端の区切り**まで含める (`](DESIGN.md)` / `](DESIGN.md#`)、 正規表現なら先読みで終端を要求する (`\]\(DESIGN\.md(?=[)#])`)。 構造を持つ対象 (markdown の link、 LaTeX の命令) は、 文字列置換でなく**構文解析した単位が完全一致した時だけ**書き換える道具を使う (link なら [`scripts/fix-md-links.py`](../scripts/fix-md-links.py)、 selftest に「素朴な `str.replace` が正しい sibling link を壊す」 foil)。 文字列置換のまま進めるなら、 old の両端が識別子・path の途中でないことを検査する ([`scripts/apply-text-pairs.py`](../scripts/apply-text-pairs.py) は既定で拒否)。

### <a id="insertion-pair-rerun"></a>6. 挿入型の pair は再実行しても「正確に 1 回」 を通る (2026-09-13)

**症状**: 関数を足す patch を `old = "def selftest() -> int:\n"`、 `new = <足す関数> + old` の形で書いた。 同じ patch script を写しに当てるつもりで再実行し、 target の引数を付け忘れて本物の file に当てた。 **全 assert を通って 2 回目が入り**、 argparse の option が二重登録になって、 その CLI は起動時に落ちた。 同じ file を module として import する側は動き続けたので、 CLI を叩くまで気づけない形だった (約 1 分で写しから戻した)。

**なぜ起きるか**: 置換型の pair は適用後に `old` が消えるので、 再実行は count==0 で止まる (契約の「0 件 = 既適用」)。 挿入型の pair は `new` の中に `old` が残るので、 適用後も count==1 のまま。 契約は 2 回目を区別できない。 さらに patch script が live な file を**既定の target** にしていると、 引数の付け忘れがそのまま本物への再適用になる。

**対処**: (1) `old` が `new` に含まれる pair は、 **`new` が既に在れば拒否**する (適用済み検査)。 (2) patch script は target を必須引数にし、 既定値を持たせない。 (3) 書く前に patch 後の写しで test を通す ([hook-authoring.md#engine-edit-is-deploy](hook-authoring.md#engine-edit-is-deploy))。 3 つとも [`scripts/apply-text-pairs.py`](../scripts/apply-text-pairs.py) が実装し、 selftest に「素朴な契約は再実行を通す」 foil がある。

### <a id="symlink-target"></a>7. TARGET が symlink だと、 test 用の写しも原子的な書込みも実体を外す (2026-09-14)

**症状**: 絶対 path の symlink を TARGET にして、 構文を壊す patch を「写しで test を通してから書く」 道具で当てた。 道具は test の失敗を検出して「何も書いていない」 と表示したが、 **link 先の実体には壊れた版が入っていた**。 test が通る patch では逆に、 link が普通の file に置き換わり、 実体は変わらなかった。 どちらも error は出ない。

**なぜ起きるか**: 2 つの操作が link を別々に扱う。 (1) test 用に dir を写すとき link を link のまま写す (`shutil.copytree(..., symlinks=True)` など) と、 絶対 path の link は写しの中でも元の実体を指すので、 「写しの TARGET」 への書込みがそのまま実体に届く。 (2) 一時 file + `os.replace(tmp, target)` の原子的な書込みは、 target の path に在る**link そのもの**を置き換え、 link 先には書かない。 使う側の path が symlink で実体は repo の中、 という配置 (install 済みの hook など) で踏む。

**対処**: 読む・写す・書く前に TARGET を 1 回だけ実体の path へ解決する (`os.path.realpath`)。 写しの dir の中の他の link は link のまま写してよい (辿って写すと、 repo root に在る共有 folder への dir link まで丸ごと複製する)。 ただしその場合に守られるのは TARGET だけで、 test command が絶対 link や絶対 path を通して書く副作用は写しでは隔離されない。 [`scripts/apply-text-pairs.py`](../scripts/apply-text-pairs.py) が実装し、 selftest に「絶対 link 越しの壊れた patch が実体に届かない」「link 越しに書いても link が残る」 foil がある。 **道具の「書いていない」 という報告は、 書き先の実体を読むまで証拠にならない** (この事例は実体を読み直して初めて見えた)。 同じ一手で、 相対 path の不具合も片付く: 写し先を「一時 dir / 親 dir の name」 で作ると、 `Path("tool.py").parent.name` は空文字なので一時 dir そのもの、 `Path("../tool.py").parent.name` は `..` なので一時 dir の親を指す (前者は複製が `FileExistsError` で落ち、 後者は一時 dir の外へ写そうとする。 同日実測)。

### <a id="system-python-long-multibyte-line"></a>8. macOS 付属の python は、 長い多バイト行を source として読めない (2026-09-17)

**症状**: 置換 script の中に日本語の長い文字列を 1 行で書いて `/usr/bin/python3` (Xcode 付属の 3.9.6) で走らせると、 `SyntaxError: Non-UTF-8 code starting with '\xe3' in file …, but no encoding declared` で落ちる。 file は正しい UTF-8 で、 encoding 宣言を足しても直らない。 heredoc (`python3 - <<'EOF'`) に書いても同じ。 同じ file を新しい python (Homebrew の 3.14) で走らせると通る。

**なぜ起きるか**: この版は source を 1023 byte ずつ読み、 区切りが多バイト文字の途中に落ちると、 残りの断片を不正な UTF-8 として拒否する。 実測: `x = "` の後に 3 byte の文字を並べた 1 行は、 300 字 (906 byte) では通り、 341 字 (1028 byte) では落ちた。 行頭を 5 → 6 → 7 byte と変えると、 落ちる・通る・落ちると入れ替わった (1023 byte 目が文字の境界に当たるかどうかで決まる)。 1 行が 1023 byte 以下なら起きない。

**対処**: 長い非 ASCII の文字列を Python の source に直接書かない。 (1) 文面は別の text file に置き、 script は `io.open(path, encoding='utf-8')` で読む (pair 列なら 1 件 1 file か、 tab 区切りの 1 行 1 件)。 (2) source に書くなら、 隣り合う文字列 literal に割って 1 行を短く保つ。 (3) 走らせる python を固定できるなら新しい版にする ([shell-env.md#bound-command-runtime](shell-env.md#bound-command-runtime))。 error 文は encoding 宣言の不足を疑わせるが、 宣言を足しても直らないのが見分け方になる。

### <a id="computed-old-empty"></a>9. 計算で作った old は空になりうる — `replace('', new)` は全文字の間に挿入する (2026-09-22)

**症状**: 節を差し替える script が `old = s[s.index('### lint'):s.index('### 理由')]` と切り出した。 `### 理由` はその file でもっと前の 4 節にも在ったので終点が始点より前になり、 slice は**空文字列**。 続く `s.replace(old, new)` は Python の仕様どおり「先頭・各文字の間・末尾」 に new を差し込み、 数百行の doc が十数万行 (数 MB) になった。 error は出ない。 同じ heredoc の他の pair には `assert s.count(old)==1` が付いていたが、 計算で作ったこの old だけ検査が無かった。 直後の確認 grep は (文字が分断されて) 0 件だったが読まれず、 `git commit -q … | tail -3` で stat も見えないまま push された。 見つかったのは別 session が別件でその file を開いたときで、 それまでどの検出器も鳴らなかった (肥大検出器は CLAUDE/SESSION.md 限定、 切り詰め検出器は縮小しか見ない、 pre-commit にサイズの門が無かった)。

**なぜ契約が守ってくれないか**: 契約 (各 old は正確に 1 回) は **literal の old** を前提にしている。 old を file から slice で作ると、 (1) 終点の anchor が始点より前にも一致すれば空、 (2) 終点が別の節に一致すれば意図より長い span、 のどちらも**それ自身は正しい 1 回一致に見える**。 空文字列は `count` が len+1 なので assert が在れば落ちるが、 計算で作った old には assert を付け忘れやすい。 `str.replace` は空の old を error にしない。 復元できたのは、 壊れた file の block と block の間に元の本文が 1 文字ずつ残っていたから (= 挿入型の壊れは元を保存する。 上書き型なら git の直前の版だけが頼り)。 その再構成は [`scripts/check-degenerate-text.py`](../scripts/check-degenerate-text.py) `--recover PATH` が機械でやる (最頻行の 2 回目の出現までを block と推定し、 split した断片が全部 1 文字であることを検証してから連結。 意図した block は別途 1 回だけ当て直す)。

**対処**: (1) 終点は始点より後ろで探す — `s.index(B, s.index(A) + 1)` (2 引数目で範囲を絞る)。 anchor は見出しの**行頭からの一意な形** (`\n### lint\n`) にする。 (2) 計算で作った old にも同じ assert を当てる = `assert old and s.count(old) == 1` ([`scripts/apply-text-pairs.py`](../scripts/apply-text-pairs.py) は空の old を拒否する)。 (3) **書いた後に形を測る**: `wc -l` の前後差か `git diff --stat` を同じ command 行で出し、 意図した箇所数と桁が合うことを見る (下の検証 5)。 (4) commit の stat を捨てない — `git commit -q` の後に `git show --stat HEAD | tail -1` を同じ行に置く。 (5) 機械の門 = [`scripts/check-degenerate-text.py`](../scripts/check-degenerate-text.py) `--staged` が全 repo の pre-commit (pre-commit-bib と public stub) で「1 行の異常な繰り返し」「HEAD 比 10 倍以上かつ +1,000 行以上」 を止め、 既定の fleet scan が commit をすり抜けた壊れを見つける (閾値は fleet の実測から、 SoT = その docstring)。 門は形しか見ないので (1)-(4) の代わりにはならないが、 (1)-(4) は多 commit・並行 session の圧力下で skip されるので門も外さない。

## <a id="batch-text-verification"></a>適用後の検証

1. **再 build が通る** (LaTeX なら error 0 + 頁数が期待どおり)
2. **旧断片の grep が 0 件** (= モード 2 の後段、 assert では代替できない)
3. **意図した箇所数と実 diff が一致** (`git diff --stat` の hunk 数を目で突き合わせる)
4. **戻したら、 戻した箇所の `git diff` が空になることを確かめる**。 戻す pair は、 当てた pair の old と new を入れ替えたものにする (手で書いた削除の pair は、 隣の改行まで削りうる)。 実例 (2026-09-14): 別 session が足した 1 文を取り消した後、 直後の空行も消えていて、 次の段落が箇条書きの続きとして描画される形になっていた (取り消しに使った手段は未確認)。
5. **形を測る** (= モード 9 の後段): 書いた直後に `wc -l` の前後差か `git diff --stat` を**同じ command 行**で出し、 意図した箇所数と桁が合うか見る。 数百行の file の差分が数千行なら、 old が空か二重挿入。 commit の後も `git show --stat HEAD | tail -1` を同じ行に置く (`-q` と `| tail` で捨てない)。

## <a id="batch-text-adjacent"></a>隣接 kernel (別 domain、 混同しない)

- **Edit tool との関係**: 本 pattern は「Edit の唯一 match 契約を**尊重したまま**量産する」ためのもので、 契約を外した全置換の免罪符ではない (= モード 4 の anti-pattern)。
- **並行編集の race** = [multi-session-coordination.md](multi-session-coordination.md) (= モード 4 の上流予防)。
- **byte 単位の文字列切り詰め** = [shell-multibyte-truncation.md](shell-multibyte-truncation.md)。 同じ「byte で見ろ」でも kernel は truncation であって matching ではない。
- **docx / xlsx の中身を XML 文字列で置換する場合** = [office-automation.md#docx-fill-xml-edit](office-automation.md#docx-fill-xml-edit)。 binary container 固有の罠 (run 分割・宣言・rels 整合) が別途あるので、 本 doc の契約だけでは足りない。

origin: 2026-07 の LaTeX 原稿改訂 session で本 pattern を約 10 回実戦投入 (最大 66 箇所を 1 pass) し、 上記 4 モードすべてを同日中に実測した。 モード 5・6 は 2026-09-13 (fleet の link 修正と script の hoist) で実測して追加。 モード 7 は 2026-09-14 (相対 path の不具合を直す途中で symlink の TARGET を試して) 実測して追加。 モード 9 は 2026-09-22 (設計 doc の節の差し替えで終点の見出しが前の節にも在り、 file が全文字の間に膨れた) に実測して追加、 同時に commit gate と fleet scan を機械化。
