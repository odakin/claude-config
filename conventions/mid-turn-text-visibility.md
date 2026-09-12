<!-- doc-meta
when: ツール呼び出しを含むターンで user に見せる文面・結論・訂正を出すとき / 応答に機械向けの marker・sentinel を埋め込もうとするとき
category: harness-core
summary: user に見える提示面はターン最終テキストメッセージ (+ 明示的な file 提示) だけ — mid-turn テキストは表示されないことがあり (Claude Code desktop で実測、同一 session 内 2 連発)、tool 入力 (Bash heredoc / Edit content) や書き込んだ file はそもそも提示面でない (2026-08-29 再発で確定した変種)。文面 deliverable・結論・訂正は必ずターン最終メッセージに全文置く。「上の文面」「先ほどの訂正」と自ターン内を指す行為自体が事故 signal。逆向きの取り違えとして、最終メッセージの HTML comment は隠れず literal 表示される (2026-09-12 desktop 実測) ため、hook 用 marker 等の機械向け signal は提示面でなく tool 入力に置く
-->
# ツール呼び出しターンのテキスト可視性 — deliverable は最終メッセージに全文

## 現象

ツール呼び出しを含むターンでは、**ツール呼び出しの前・間に出力したテキストが
user に表示されないことがある**。harness の一般仕様として「between tool calls の
テキストは表示されない可能性がある」と明記されているが、実測では**ツール呼び出し
「前」の冒頭テキストも落ちる** (= frontend 依存、少なくとも Claude Code desktop で確認)。

実測 (2026-08-19、同一 session 内 2 連発): コピペ用の文面 draft を「冒頭テキストで
提示 → 記録・commit のツール呼び出し → 最終メッセージで『上の N 項版が最終形』と
参照」の形で 2 ターン連続出力した結果、**user には文面が一度も表示されず**、
「最終文面とやらが私には提示されてない」と 2 回指摘された。1 回目の指摘後に
「先ほどの訂正で削除済み」と mid-turn テキストを再参照して 2 回目を踏んだ
(= 訂正の宛先も表示されていなかった)。

## 変種 (2026-08-29 再発): tool 入力はそもそも提示面ではない

上記ルールの存在下で 10 日後に同型が再発した。transcript 検証で判明した機序は
text block の表示落ちではなく、**より深い取り違え**だった: コピペ用テキストの
全文が現れたのは byte 検算の Bash heredoc と正本 file への Edit content
(= **tool 入力の中**) だけで、**どの text block にも一度も出力されないまま**、
最終メッセージが「上の圧縮版 (491 字…) を貼れば通ります」とそれを参照した。
tool 入力は UI では折り畳まれた tool chip の中身であり、表示可否以前に
**提示面ではない**。

一般化すると: **Claude の context window に在る ≠ user に提示された**。
モデルの主観では「上に出した」テキスト (tool 入力・file 書き込み・mid-turn
text) が context に鮮明に在るため参照が自然に感じられるが、user に見える面は
その真部分集合 — **ターン最終テキストメッセージと、明示的に提示した file
(link / render) だけ**である。terminal への text dump を「見せた」に数えない
規律 (chat の file 提示規約) も同じ核の別 instance。

## <a id="html-comment-not-hidden"></a>逆向きの取り違え: 提示面は raw で出る — 「user に見えない印」 を最終メッセージに埋め込めない (2026-09-12)

上の 2 節は「context に在るのに提示されない」 側だが、 同じ境界には逆向きの取り違えがある: **最終メッセージに置いた HTML comment (`<!-- ... -->`) は、 Claude Code の chat renderer では literal に表示される** (2026-09-12 desktop 実測 = user が応答末尾の marker を指して「こういうのが表示されるんのはなんで？」)。 GitHub 等の web markdown renderer で消えることを根拠に、 「user には不可視の印」 として最終メッセージに埋め込む設計は成立しない。 frontend 依存の可能性はあるが、 **消えることを前提にしてはならない**: 消えなかったときに user の画面が毎ターン汚れ、 しかも**それを Claude 側から観測できない** (= 表示落ちと同じ非対称で、 user の指摘まで分からない)。

一般化すると: **提示面に置けるのは人間向けの出力だけ**。 機械向けの signal (hook が grep する marker、 machine-readable tag、 自動処理用の sentinel) を最終メッセージに混ぜると、 そのまま user のノイズになる。

### <a id="machine-marker-in-tool-input"></a>機械向け marker は tool 入力に置く

置き場所は上の §変種 の裏返しで決まる。 **tool 入力は提示面ではないが転写には残る** — ∴ 検出側が turn の転写を grep する形であれば、 **Bash command の comment に marker を書けば機械には届き、 user には見えない**:

```
<実際のコマンド>   # <marker>
```

hook を書く側の含意が 2 つある。

1. **marker の検出は turn の転写全体を走査する形にする** (= assistant text + `tool_use` の `.input.command` + `tool_result`)。 assistant text だけを見る検出にすると、 呼ぶ側には「可視面を汚す」 以外に marker を出す手段が無くなる。
2. **marker が必要な turn を最小化する**。 hook の発火条件が狭ければ marker が要る turn も狭い。 呼ぶ側が毎 turn reflex で marker を出しているなら、 発火条件を満たさない turn では純粋な noise であり、 規律側の bug (実例: 「生成した ∧ 応答本文がその名前に触れた」 の両方が成った turn だけ発火する hook に対し、 無関係な turn まで marker を出していた)。

## 規律

1. **user が受け取るべきもの (文面 deliverable・結論・判断材料・訂正) は、
   ターンの最終メッセージに全文置く**。最終メッセージの後にツール呼び出しを
   置かない (= 置いた時点でそのテキストは「最終」でなくなる)。
2. **「上の文面」「先ほどの訂正」「前述の通り」と自ターン内を指す行為自体が
   事故 signal**。referent が mid-turn text でも tool 入力でも file でも同罪 —
   指したくなったら、その内容を最終メッセージに再掲する。
3. ツール呼び出し前の冒頭テキストは**進捗の短報に限る** (= 消えても実害がない
   もの)。deliverable をそこに置かない。
4. 作業 (記録・commit 等) と文面提示が同居するターンでは、**順序 =
   ツール呼び出し先行 → 最終メッセージで文面全文**。逆順にしない。
5. **SoT 記録・commit は提示の代替にならない**。「正本 file に書いて link を
   貼った」はコピペ用 deliverable の提示ではない (user に file を開かせて
   該当箇所を発掘させる = 機械が手間を消す方向の逆)。記録と提示は両方やる。
6. **機械向けの signal を最終メッセージに書かない**。HTML comment も
   raw 表示されうる — hook 用 marker 等は tool 入力側に置く
   ([#machine-marker-in-tool-input](#machine-marker-in-tool-input))。
7. **「この印は user には見えない」と doc に書くなら、実際にその frontend で
   確認してから書く**。未確認の不可視前提は、破れても Claude 側から観測できない。

## なぜ滑りやすいか

自然な思考順序が「文面を作る → ついでに記録する」であるため、出力も
文面 → ツールの順になりがち。また 1 回目の表示失敗は Claude 側から観測できない
(= エラーも警告も出ず、user の指摘まで分からない) ため、同型を連発しやすい。
2026-08-29 の再発はさらに、記録系の規律 (SoT 更新・同 turn commit+push) が
強く内面化されているほど**最終メッセージが bookkeeping 報告で埋まり、user 向け
提示が「上の」1 行に圧縮される**という転位を示した — 提示 step は価値の 100% が
user の目に行き agent のループに何も返さないため、多部分作業で構造的に
落ちやすい (motivated-substitution の verification family と同根)。
ターン構成の反射として「deliverable は最後・全文」を焼き込むしかないが、
規律単独では再発した実績があるため、Stop hook で「最終メッセージの
『上の◯◯版/文面』型参照 ∧ tool call を含む turn」を検出して self-check を
注入する機械 backstop が有効 (述語は転写 log で校正可能 — 実測では参照句 +
deliverable 名詞の近接に絞ると誤検出ゼロで過去事故を全件 retroactive 検出した)。
