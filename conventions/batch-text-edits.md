<!-- doc-meta
when: 同一 file に 3 箇所以上の text 置換をまとめて当てるとき (= Edit tool を N 回叩く代わりに script で一括適用するとき)
category: infra
summary: plain-text source への一括置換 script の契約 (= (old, new) pair 列 + 各 old は正確に 1 回 match の assert + read→全 assert→全 replace→単一 write) と 4 つの実測失敗モード (assert の verdict は下流の compile/commit に伝わらない / count==1 は match の一意性を保証するが span の十分性は保証しない = 複数行段落の先頭行だけ置換して新旧両方が印字 / 目視で同じでも trailing space で不一致 / count==0 は typo でなく並行編集による適用済みでもありうる)
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

- **契約**: 各 `old` は file 中に**正確に 1 回** match する。 0 件 (= typo / 既適用 / 別 file) も 2 件以上 (= 誤爆) も abort。 これは Edit tool の「唯一 match 保証」を N 件へ拡張したもの。
- **順序が本質**: read → **全 assert** → 全 replace → **単一 write**。 loop 内で write したり `sed -i` を逐次実行すると、 途中で失敗したとき「半分だけ当たった file」が disk に残る。

**使い分け**:

| 規模 | 手段 | 理由 |
|---|---|---|
| 1-2 箇所 | Edit tool | 差分がそのまま可視になり人間 review が効く |
| 3 箇所以上 / 長い string / 系統的 sweep | 本 pattern | 手数と転記ミスが線形に増えるのを止める |

## <a id="batch-text-failure-modes"></a>4 つの失敗モード

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

### <a id="zero-count-is-ambiguous"></a>4. count==0 は「typo」とは限らない

**症状**: assert fail を「`old` の typo」と解釈して pattern を書き直したが、 実際は**同じ file を人間がエディタで直接編集していて既に適用済み**だった。

**0 と 2 以上は別の病気**なので、 診断を分ける:

| count | 意味 | 次の手 |
|---|---|---|
| `0` | その形では file に存在しない | typo / whitespace (= モード 3) / **既に適用済み** / そもそも別 file、 を grep で切り分ける |
| `≥2` | anchor が非特異 | 周辺 context を足して一意化する (件数指定で誤魔化さない) |

🚫 **anti-pattern**: fail を「緩めて」通すこと (`replace(old, new, 1)` に変える / 全置換に切り替える / regex を広げる)。 **loud failure を silent な誤置換に変換する**のが最悪の手で、 モード 2 の残骸もこの経路で生まれる。

**対策**: fail したら機械的に retry せず、 まず grep で現物を確認する。 並行編集がありうる環境 (= 人間が同じ file を開いている / 並列 session) では適用直前に `git fetch` と working tree の確認を挟む。

## <a id="batch-text-verification"></a>適用後の検証

1. **再 build が通る** (LaTeX なら error 0 + 頁数が期待どおり)
2. **旧断片の grep が 0 件** (= モード 2 の後段、 assert では代替できない)
3. **意図した箇所数と実 diff が一致** (`git diff --stat` の hunk 数を目で突き合わせる)

## <a id="batch-text-adjacent"></a>隣接 kernel (別 domain、 混同しない)

- **Edit tool との関係**: 本 pattern は「Edit の唯一 match 契約を**尊重したまま**量産する」ためのもので、 契約を外した全置換の免罪符ではない (= モード 4 の anti-pattern)。
- **並行編集の race** = [multi-session-coordination.md](multi-session-coordination.md) (= モード 4 の上流予防)。
- **byte 単位の文字列切り詰め** = [shell-multibyte-truncation.md](shell-multibyte-truncation.md)。 同じ「byte で見ろ」でも kernel は truncation であって matching ではない。
- **docx / xlsx の中身を XML 文字列で置換する場合** = [office-automation.md#docx-fill-xml-edit](office-automation.md#docx-fill-xml-edit)。 binary container 固有の罠 (run 分割・宣言・rels 整合) が別途あるので、 本 doc の契約だけでは足りない。

origin: 2026-07 の LaTeX 原稿改訂 session で本 pattern を約 10 回実戦投入 (最大 66 箇所を 1 pass) し、 上記 4 モードすべてを同日中に実測した。
