<!-- doc-meta
when: 同じ様式 (申請書・請求書・届) を人や回ごとに何度も出す作業を仕組みにするとき + 提出した書類を新しい書類の base にしてしまう / 提出済みの file を黙って上書きする事故を止めたいとき + 同じ規則が手順書・案件メモ・README に書き写されて食い違うのを止めたいとき + 様式の一部の頁だけを作り直したいとき
category: office
summary: 様式の案件 pipeline (formcase) の規約 — 規則の home は 1 つ + 他は生成 view / 提出状態を案件ごとの data (document → group → issue) に持つ / 凍結は content-addressed (sha256 + 書式 fingerprint) / 紙と記録の関係を field で持つ / 出力を書く前に gate。 engine = scripts/formcase/ (汎用)、 様式と案件は呼び元の repo。 導入手順と限界 (言い換えは lint の外 / fingerprint の射程 / 字の切れ gate の死角) つき
-->
# 様式の案件 pipeline (formcase)

同じ**様式** (institution が配る Excel / Word の申請書・請求書・届) に、 人や回ごとに値を入れて紙や PDF で
出す作業を仕組みにするための規約。 engine の実装 = [`scripts/formcase/`](../scripts/formcase/) + CLI
[`scripts/formcase.py`](../scripts/formcase.py) (どちらも汎用。 様式・案件・人は呼び元の repo が持つ)。

入口マップからの位置づけ = [`office-files.md`](office-files.md) (様式仕事の router)。 個々の罠の症例集 =
[`office-automation.md`](office-automation.md)、 考え方 = [`office-automation-principles.md`](office-automation-principles.md)。
本 doc はその上に乗る**運用の形**を決める。

---

## <a id="problems"></a>1. 何を解く仕組みか

3 つの失敗が、 どれも「同じ様式を何度も出す」 という形そのものから出てくる。

| 失敗 | なぜ起きるか | 手作業・散文では止まらない理由 |
|---|---|---|
| **規則が食い違う** | 「この欄は空で出す」 のような規則が、 手順書・案件メモ・案件 README・過去の driver に**書き写される**。 規則が変わると 1 か所だけ直る | 写しは正しい形をしているので読んでも気づけない。 grep しても、 言い換えた写しは同じ語を含まない |
| **提出物が base にされる / 黙って上書きされる** | 次の案件を作るとき、 手近にある「前に通った file」 を copy するのが一番速い。 生成 script を再実行すると同じ path に書く | 受理された ≠ 正しい (窓口が手で直したものが通っていることがある)。 上書きは差分が出ないので事故として見えない |
| **一部だけ作り直せない** | 1 つの workbook から事前に出す頁と後で出す頁を刷る様式で、 全部を作り直すと**既に出した頁まで作り直す** | 「今どこまで出したか」 が人の記憶と folder の見た目にしかない |

## <a id="model"></a>2. 形 (5 つの決め)

### <a id="manifest"></a>2.1 提出状態は案件ごとの data (`submission.yaml`)

案件 (= 1 つの folder) ごとに 1 つ置く。 3 階層:

```
document   1 つの workbook (+ そこから作る出力) の単位 = 1 人 1 様式の書類
group      spec の groups: が定める page のまとまり (例: 先に出す p.1-4 / 後で出す p.5-6)
issue      group を 1 回発行した記録。 current が今、 previous が過去
```

`issue.state` = `draft` / `printed` / `sent` / `submitted` / `unknown`。 **`draft` 以外は凍結**。
`unknown` は「記録が無い / 分からない」 を書ける状態で、 何が分からないかの `note` を要求する
(= 分からないことを「たぶん draft」 に丸めない)。

⚠️ **状態を手で書き換えない** — `freeze` / `annotate` / `reopen` を通す (digest を取り直すため)。
schema の実行系 = [`formcase/manifest.py`](../scripts/formcase/manifest.py)。

### <a id="frozen"></a>2.2 凍結は content-addressed

凍結 issue は、 出力 file の **sha256** と、 その group が刷る sheet の **値の digest + 書式の
fingerprint** を持つ。 これが「史実の記録」 になり、 3 面で守られる:

1. `build` は凍結 group の出力を**作らない**
2. 案件 folder に残る旧 driver は冒頭 1 行 (`legacy_guard`) で Excel を起こす前に止まる
3. pre-commit が凍結出力の staged 変更・凍結 sheet の値や書式の変更を BLOCK する
   (⚠️ HEAD の manifest で凍結だった出力は、 staged の manifest で状態を書き換えても BLOCK = **状態の
   手書き改変で保護を外せない**)

作り直すのは `reopen` (= 新しい draft issue を、 出力名に `_r2` をつけて作る)。 **前の file は残る**。

### <a id="paper"></a>2.3 紙と記録の関係を field で持つ

凍結の記録は「freeze した時の tree」 で、 **実際に刷った / 送った / 出したものと同じとは限らない**
(窓口で手書き訂正されることがある / どの版を刷ったか分からなくなることがある)。 だから紙になった
issue は `paper: same | differs | unverified` を必須にする。

- `differs` / `unverified` は `paper_diff` (何が違う / 何が分からないか) が必須
- `same` の根拠は `paper_basis`、 紙の版が分かるなら `paper_commit`
- `differs` / `unverified` は 📄 の行として **常に見せる** (問題の件数にも exit code にも入れない = 毎回の
  催促にしない。 しかし `--quiet` でも黙らせない)

これが無いと「記録 = 紙」 という**無根拠の同一視**が既定になる。 分からないことを書ける場所を作るのが要点で、
`date: unknown` に対する `date_ack` (本人に確認して分からなかった記録)・出力 file の記録が無い凍結 issue に
対する `outputs_ack` (どこを探して無かったか) も同じ働き = **聞き直さないための記録**。

### <a id="views"></a>2.4 規則の home は spec 1 つ、 doc に載るのは生成 view

規則 (何をどう書くか) の本文は**お手本 spec (yaml) にだけ**置く。 doc 側は marker で囲んだ区間を持ち、
中身は spec から描く:

```
<!-- formcase:view kind=table rules=<form>/<rule>,<form>/<rule> -->
…(生成)…
<!-- /formcase:view -->
```

`kind` = `table` (規則の表) / `checklist` (提出前 checklist) / `cells` (セルの値の表) /
`status` (案件 README の状態表 = manifest から)。 手で書き換えると `views --check` が stale と言う。
経緯・理由として古い言い回しを残す区間は `<!-- formcase:history -->` で囲む。

⚠️ **区間は入れ子にできない** — 入れると内側の閉じで外側が閉じ、 後ろの行が黙って検査に戻る / 外れる。
崩れは承認できない finding として出る。

### <a id="gates"></a>2.5 出力を書く前に gate

`build` は、 gate が通らなければ**何も書かない**。 段は 4 つ:

1. **記入内容 gate** (spec ⊢ workbook): 埋める欄 / 空が正の欄 / 排他選択 / 数式 cache の生存。
   凍結 group の sheet は今日の spec で裁かず 🧊 と表示する (= 過去の提出物を今の規則で FAIL にしない)
2. **体裁** ([下記 §3](#layout-3)) を使い捨ての temp にだけ当てて Excel に PDF を作らせる
3. **字の切れ・はみ出し gate** を PDF に当て、 引っかかった欄を折り返し → 行を伸ばして刷り直す (上限つき)。
   残れば出力を書かずに止める
4. **刷る頁の宣言** ([下記 §4](#page-roles)) を出力に書き込む

## <a id="layout-3"></a>3. 体裁の出どころは 3 つだけ (過去の案件の形を持たない)

体裁 (行高・折り返し・印刷範囲・倍率) を recipe の定数に焼くと、 **提出まで通った案件の形**がそのまま
次の案件に移り、 値が長いと崩れる。 出どころを 3 つに分ける:

| # | 出どころ | 何を決めるか |
|---|---|---|
| 1 | **配布雛形の欠陥** = spec の `render:` (各 entry に理由) | 表示書式・結合・罫線・label の行高の下限・揃え・白黒・印刷範囲。 値で形が変わる欠陥は `when:` |
| 2 | **page** = 印刷範囲 × 雛形の手動改ページ | 1 まとまりを紙 1 枚に収める。 行を伸ばしても次の頁に溢れず全体が縮む |
| 3 | **値の長さ** | 結合セルに 1 行で入らない値は折り返し、 要る行数まで行を伸ばす (縮めない) |

見積りは**控えめ**にし、 真偽は PDF で決める (= 上の gate 3 が刷り直す)。 縮み過ぎ (= 行を伸ばし過ぎ / 値が
長過ぎ) は下限を決めて止める。 元の xlsx は触らない (体裁は temp / staged copy にだけ当てる)。

openpyxl で保存すると図形 (標題・checkbox) が落ちる雛形は、 体裁を openpyxl の読み込みの上で計算し、
**差分だけを Excel の操作として** staged copy に当てる。

## <a id="page-roles"></a>4. 窓口に出す頁だけを刷る

配布雛形には、 様式本体のほかに**説明書き・記載例・控え・マスタ・白紙**が付いてくる。 spec が頁の役割
(`page_roles`: `submit` / `instructions` / `example` / …) を宣言し、 `submit` の頁には**頁の目印
(anchor)** を書く。 build は group の頁を切り出し、 「全頁 = 窓口に出す頁」 の宣言を出力に書き込む
(= 刷る直前の preflight がそれを読む)。

- 宣言の無い頁に「記載例・控え・注意事項・白紙」 の推定が当たれば、 **出力を書かずに止める** = 出す頁なら
  `page_roles` に `submit` + anchor を書き、 出さないなら group の頁から外す、 を人が決める
- 雛形が改訂されて頁の中身がずれたら anchor が外れて止まる (= 黙って別の頁を刷らない)
- Word 様式は文書まるごとが 1 つの package なので **全頁に役割が要る**。 Excel 様式は刷る sheet の
  whitelist があるので役割は任意

## <a id="docx"></a>5. Word (docx) 様式

値が 2 か所に分かれる:

1. **docx に打つ値** = spec の `docx.fields`。 fill は**毎回 雛形から docx を作り直す** (段落を足す欄が
   あるので、 記入済みに書き足すと二重になる = 冪等にするため)
2. **PDF に重ねる値** = `docx.choices` (○ で囲む選択肢) / `docx.texts` (罫線の右に書く短い値)。 docx に
   打つと autofit の表の列幅が動いて頁がはみ出すため、 PDF の上に重ねる。 fill が sidecar の yaml に書く

凍結の digest は docx の**文字と書式**と、 重ねた値の yaml を見る。 Word の PDF の頁数が spec の宣言と
違えば止める (= 値の長さで頁がはみ出した)。 出力名の型は spec が持つ (= 名づけは呼び元のもの)。

## <a id="lint-reach"></a>6. 規則の書き写しを検出する (と、 その射程)

spec から**導出した** token で、 process doc (手順書・入口・案件 README) を走査する。 人が検出語の一覧を
書かないのが要点:

| kind | 何を見るか |
|---|---|
| `superseded` | 規則の**廃止した版**の言い回し (spec の `superseded:`) |
| `marker` | 規則を定義する固有の言い回し (spec の `markers:`) |
| `value` | 記号つきの固定値 (`○…` / `☑…`) の書き写し |
| `claim` | 規則の `claims:` (= about の語の**直後**に来る、 その規則と矛盾する数・否定・語) と、 cell の値の主張 (`<cell> = 『値』`) を spec と照合 |
| `statement` | 規則の形の文 (cell 番地・規則の語 × 値・否定) を規則の home の外に書いている行 (矛盾していなくても) |
| `state` | 案件 README に案件の**状態**を手で書いている行 |
| `region` | 区間 marker の入れ子・閉じ忘れ・宙に浮いた閉じ |

照合は正規化 (全角半角・空白・括弧・markdown・助詞・少数の送り仮名) の後。 値・yes/no の規則が `claims:`
を持たないと落ちる (= 網羅が黙って後退しない)。

⚠️ **射程は宣言した語彙と形だけ**: `about` に無い同義語・行をまたぐ主張・番地も規則の語も無い文は見えない。
これが致命的でないのは、 **紙を変えるのは spec で workbook を裁く gate であって doc ではない**から
(= doc の写しは人を誤らせるが、 出力は spec が決める)。 proxy の死角の一般則 =
[`docs/convention-design-principles.md#proxy-blind-spot`](../docs/convention-design-principles.md#proxy-blind-spot)。

## <a id="case-readme"></a>7. 案件 README に状態を書かない

「未提出 / 提出予定 / 印刷版 / 未決 / 返事待ち / 〆」 は**状態**で、 進むたびに写しが古くなる。 状態の正本は
`submission.yaml` (README には `kind=status` の生成表) と、 案件の TODO。 README が持つのは file の説明・
**値の出典**・経緯だけ。 状態の説明を書きたくなったら issue の `note` に書く (`annotate --note`)。

pre-commit は、 stage した案件 README の状態の写しと、 古い生成 view を BLOCK する。

## <a id="fingerprint-noise"></a>8. 書式の fingerprint の較正 (何を「同じ」 と見なすか)

「値は同じだが紙の見た目が違う」 改変を捕まえるには書式も digest に入れる。 ただし Excel 自身が保存の
たびに書式を揺らすので、 **揺れを実測して、 その app の分解能の上で比べる**:

- 行高・列幅は Excel が保存しうる**格子**に丸めてから比べる (閾値でなく app の分解能)
- 値の無い cell は**紙に出る性質だけ** (罫線・塗り・選択範囲内で中央) を見る。 font・表示書式・揃えは値が
  無ければ紙に出ない
- 図形・form control は**落ちたら本物の変化** (openpyxl の保存が落とす = 紙から標題や checkbox が消える)
- 凍結は「最後の保存 = その app」 の file だけに許す (別の app が最後だと、 次の保存で格子が丸め直されて
  誤検出になる)。 満たさなければ拒否して「開いて保存するだけ」 の手順を案内する

⚠️ **既存の凍結 issue を新しい版の射程で裁かない**: digest に版 (v1 / v2 / v3) を持ち、 sheet ごとに
**記録に在る一番新しい版**で比べる。 版を上げるときに古い issue を re-freeze すると、 その issue の
「史実」 が今の tree で上書きされる。

## <a id="scope"></a>9. 射程 (何を作れて、 何を作れないか)

- **spec に書ける様式** = 頁のまとまり (group) が定まり、 埋める欄と空が正の欄が cell 単位で言える様式
- **recipe が要る** = 雛形の頁構成・sheet の並べ方・押印の位置・出力名。 Word 様式は spec から全部読めるので
  汎用の recipe が扱う。 Excel 様式は呼び元が recipe を書く ([下記 §10](#adopt))
- **作れない group** は manifest の note に理由を書いて旧 driver に任せる (= 黙って空の出力を作らない)
- **spec の無い書類** (窓口に出すが様式でないもの) は `form: other` で bytes の凍結だけを持てる

## <a id="adopt"></a>10. 別の repo で使う

engine は instance (どの repo の / どの様式の / 誰の案件か) を一切持たない。 与えるのは設定 file 1 つ。

1. **設定を置く**: repo に `formcase.config.json` (key の一覧と既定 =
   [`scripts/formcase/config.py`](../scripts/formcase/config.py) の docstring)。 spec の dir / 雛形の base /
   案件を探す root / gate の script / lint の走査対象 / 生成物に入る文 / 押印の画像を出す command
2. **入口 package を置く** (任意だが、 案件 folder の driver から `formcase.*` を読めるようにするなら必要):

   ```python
   # <repo>/<forms dir>/formcase/__init__.py
   from pathlib import Path
   ENGINE = Path.home() / "Claude" / "claude-config" / "scripts" / "formcase"
   __path__.append(str(ENGINE))              # formcase.<module> を engine から読む
   from .config import configure             # noqa: E402
   configure(Path(__file__).resolve().parent.parent / "formcase.config.json")
   from .guard import legacy_guard           # noqa: F401,E402
   ```
3. **お手本 spec を書く** (`<spec_dir>/*.yaml`): `meta` (id / 雛形 / 主 sheet) / `groups` / `cells` /
   `render` / `page_roles` / 必要なら `nittei` (1 日 1 block の表) と `cross_checks`
4. **様式ごとの recipe を書いて register する** ([下記 §11](#recipe))
5. **gate の script を宣言する**: 記入内容を spec と照合する gate は instance のもの (= 様式の記入規則は
   institution のもの)。 設定の `gates` に script を書き、 様式ごとにどれを回すかを `gates_by_form` か
   spec の `meta.gates` で決める
6. **配線する**: pre-commit から `guard --staged` と `lint --staged`、 日々の発火面から `audit`

## <a id="recipe"></a>11. recipe の書き方 (様式ごと)

`Recipe` を継承し、 その様式に固有のものだけを書く。 共通の部品 (刷り直しの loop・字の切れ gate・押印・
頁の切り出しと宣言・raster 化) は engine が持つ。

```python
from formcase import recipes as RC

class MyForm(RC.Recipe):
    form = "<spec id>"
    outputs = {"<group>": {"print": "{stem}_…​.pdf", "confirm": "{stem}_…​.pdf"}}
    seals = {1: "anchor=…,occurrence=1,size=27"}     # package の頁 → 押す位置

    def package(self, workbook, tmp):                # 雛形を PDF にして全頁を並べる
        ...
    def post_group(self, m, doc_id, group, plain):   # その group の PDF に当てる gate
        ...
    def name_vars(self, stem):                       # 出力名の型に渡す変数 (既定 = {stem})
        return {"stem": stem, ...}

RC.register("<spec id>", MyForm)
```

⚠️ **押印の位置・sheet 名・出力名の型は recipe (= 呼び元) に置く**。 engine に入れると、 その様式を持たない
repo に institution の様式が漏れる。

## <a id="limits"></a>12. 分かっている限界

| 限界 | 何が見えないか | どう埋めるか |
|---|---|---|
| **lint は宣言した語彙と形だけ** ([§6](#lint-reach)) | 言い換えた写し・行をまたぐ主張・番地も語も無い文 | 紙を決めるのは gate 側。 doc の写しが見つかったら、 その言い回しを spec の `superseded` / `claims` に足して次から捕まえる |
| **fingerprint は sheet 単位・宣言した性質だけ** ([§8](#fingerprint-noise)) | 未測定の font での初回保存の揺れ / digest に入れていない性質 (色の微差など) | 誤検出が出たら実測して格子の表に足す。 「閾値を緩める」 方向には動かさない |
| **字の切れ gate は既知の失敗形だけ** | 切れていないが読めない (重なり・薄さ・体裁の破綻) | 出力の後に **人が render を目視する** 1 段を手順に残す (gate は目視の代わりではない) |
| **刷る頁の推定は語の当たり** ([§4](#page-roles)) | 語を持たない説明書き頁 / 様式本体に見える控え | `submit` の頁は anchor で中身を照合する = 推定でなく宣言に寄せる |
| **凍結は記録であって紙ではない** ([§2.3](#paper)) | 窓口で手書き訂正された紙 | `paper: differs` + `paper_diff` に書く。 書かない限り「記録 = 紙」 の主張になる |
| **gate は Excel / Word を通す** | app が無い / 応答しない環境では build ができない | 状態の検査 (`check` / `audit`) は app なしで動く = 記録の健全性だけは常に見られる |
