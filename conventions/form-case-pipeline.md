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

`build` は、 gate が通らなければ**何も書かない**。 段は 5 つ:

1. **記入内容 gate** (spec ⊢ workbook): 埋める欄 / 空が正の欄 / 排他選択 / 数式 cache の生存。
   凍結 group の sheet は今日の spec で裁かず 🧊 と表示する (= 過去の提出物を今の規則で FAIL にしない)
2. **体裁** ([下記 §3](#layout-3)) を使い捨ての temp にだけ当てて Excel に PDF を作らせる
3. **字の切れ・はみ出し gate** を PDF に当て、 引っかかった欄を折り返し → 行を伸ばして刷り直す (上限つき)。
   残れば出力を書かずに止める
4. **刷る頁の宣言** ([下記 §4](#page-roles)) を出力に書き込む
5. **雛形との照合** ([下記 §14](#fidelity)): 雛形の図形の字が紙に無ければ出力を書かずに止め、 書き換えていない cell の見出し・素刷りとの画像の数の差・temp の census を行に出す

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

<a id="drawings-survive-temp"></a>**図形は temp でも紙に出す**: openpyxl で temp を保存すると図形 (標題・「外部資金」 などの区分の枠・
様式番号・㊞ の丸・線) が落ちる。 temp を openpyxl で作る recipe は、 保存のたびに**読み込み元の workbook から
同名 sheet の図形を移し直す** (engine `formcase/drawings.py`、 [`office-automation.md#openpyxl-destroys-drawings`](office-automation.md#openpyxl-destroys-drawings)
の回避 2 を移植の 4 条件つきで)。 移せない図形 (画像等を参照する) は止める。 form control (checkbox) は
移さない (VML・ctrlProps と対なので片方だけでは壊れる = 該当側の label に文字 ☑ を書く規則で扱う)。
移した図形が紙で悪さをする雛形の欠陥 (cell と同じ字の textbox が重なって二重に刷られる、 書き方の規則と
合わない選択の丸) は spec の `render:` の `drop_shape` で名指しして刷らない (上の表の 1 の一種、 理由つき)。 1 行の label が
枠に字幅ぎりぎりで作られて Excel の丸めで 1 字落ちる (clip の枠では消える) 時は、 枠の余白だけを縮める。
⚠️ 図形が落ちても値・罫線の gate は全部通る = 紙から様式番号が消えたまま提出物が作られ続けた (実測)。
build の後の目視 (👁) で、 様式の見出しと区分の枠が紙に在るかを見る。
build は group ごとに [`scripts/check-form-static-text.py`](../scripts/check-form-static-text.py) を回し、 雛形の図形の字
(区分の枠・様式番号・標題・㊞) が group の PDF に無ければ**出力を書かずに止める** (2026-09-24 は warn で入れ、
2026-09-25 から block = [§14](#fidelity))。 雛形を刷っても字が出ない狭い枠の図形は射程外。 字の無い図形 (選択の丸・線・
checkbox の箱) は素刷りとの画像の数の差で行に出す ([§14](#fidelity))、 位置は目視が残る。

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
   案件を探す root / gate の script / lint の走査対象 / 生成物に入る文 / 押印の扱い (`seal_mode`) と画像を出す command
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

   入口 CLI (`<forms dir>/formcase.py`) を置くなら、 **engine の読み込みを丸ごと try で囲み、
   失敗を 3 で返す** ([下記 §10.6](#adopt) の終了値の約束)。 `import` だけを囲って
   `exec_module` を外に出すと、 engine が書きかけ・pull 途中・依存欠けのときに
   traceback の 1 で終わり、 pre-commit がそれを「違反」 と読んで**無関係な commit まで止める**
   (実測)。
3. **お手本 spec を書く** (`<spec_dir>/*.yaml`): `meta` (id / 雛形 / 主 sheet) / `groups` / `cells` /
   `render` / `page_roles` / 必要なら `nittei` (1 日 1 block の表) と `cross_checks`
4. **様式ごとの recipe を書いて register する** ([下記 §11](#recipe))
5. **gate の script を宣言する**: 記入内容を spec と照合する gate は instance のもの (= 様式の記入規則は
   institution のもの)。 設定の `gates` に script を書き、 様式ごとにどれを回すかを `gates_by_form` か
   spec の `meta.gates` で決める
6. **配線する**: pre-commit から `guard --staged` と `lint --staged`、 日々の発火面から `audit`

   **終了値の約束** (= 呼び元と engine の契約。 守らないと commit が全部止まる):

   | 値 | 意味 | 呼び元 |
   |---|---|---|
   | 0 | 問題なし | 通す |
   | 1 | **違反** (凍結の記録を変える / 案件 README に状態を書いた) | 止める |
   | 2 | manifest の構造が壊れている | 止めない (内容を出す) |
   | 3 | **検査が走っていない** (engine 不在・読み込み失敗・内部エラー) | 止めない + 「走っていない」 と出す |

   pre-commit 側は **1 だけを止める**。 engine 側は、 pre-commit の入口 (`guard` /
   `lint --staged`) で想定外の例外を 3 に落とす (対話の入口は例外のまま = 本当の欠陥を隠さない)。
   engine が git-crypt で暗号化される運用なら、 呼び元は **locked を先に判定して engine を
   起動しない** (暗号文を処理系に渡すと版によって 1 で落ち、 違反と区別できない)。
   一般則 = [`docs/convention-design-principles.md#failure-exit-equals-violation-exit`](../docs/convention-design-principles.md#failure-exit-equals-violation-exit)。

   ⚠️ **配線の test は「止まったこと」 でなく「この検査が止めたこと」 まで見る** — 一律に止まる
   故障のとき、 違反を止める段だけが**偽の緑**になり、 症状が 2 方向に割れて見える。 engine を
   壊した状態で「無関係な commit は通り、 走っていないと出る」 段も置く。

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

<a id="seal-mode"></a>**押印を重ねるか紙に押すかは設定の `seal_mode` で決める** (recipe は位置だけを持つ)。
`image` (既定) = print 版に印影の画像を重ね、 紙専用の印を書く ([`office-automation.md#seal-artifact-marker`](office-automation.md#seal-artifact-marker))。
`physical` = 重ねない。 押印欄は空のまま出力し、 build が「✋ 実押印 (group): N 頁目の「印」 の欄」 の行で押す場所を列挙する
(= 刷ってから紙に実物で押す)。 紙の窓口が印刷の印影を見分ける組織は `physical` にする
([`office-automation.md#physical-seal-required`](office-automation.md#physical-seal-required))。 recipe の `seals` は両方の mode で使う
(image では重ねる位置、 physical では案内する位置) ので、 mode を切り替えても recipe は書き換えない。

## <a id="limits"></a>12. 分かっている限界

| 限界 | 何が見えないか | どう埋めるか |
|---|---|---|
| **lint は宣言した語彙と形だけ** ([§6](#lint-reach)) | 言い換えた写し・行をまたぐ主張・番地も語も無い文 | 紙を決めるのは gate 側。 doc の写しが見つかったら、 その言い回しを spec の `superseded` / `claims` に足して次から捕まえる |
| **fingerprint は sheet 単位・宣言した性質だけ** ([§8](#fingerprint-noise)) | 未測定の font での初回保存の揺れ / digest に入れていない性質 (色の微差など) | 誤検出が出たら実測して格子の表に足す。 「閾値を緩める」 方向には動かさない |
| **字の切れ gate は既知の失敗形だけ** | 切れていないが読めない (重なり・薄さ・体裁の破綻) | 出力の後に **人が render を目視する** 1 段を手順に残す (gate は目視の代わりではない) |
| **刷る頁の推定は語の当たり** ([§4](#page-roles)) | 語を持たない説明書き頁 / 様式本体に見える控え | `submit` の頁は anchor で中身を照合する = 推定でなく宣言に寄せる |
| **凍結は記録であって紙ではない** ([§2.3](#paper)) | 窓口で手書き訂正された紙 | `paper: differs` + `paper_diff` に書く。 書かない限り「記録 = 紙」 の主張になる |
| **gate は Excel / Word を通す** | app が無い / 応答しない環境では build ができない | 状態の検査 (`check` / `audit`) は app なしで動く = 記録の健全性だけは常に見られる |

## <a id="values-and-handover"></a>13. 値の出どころと、 当事者に渡す形

<a id="public-schedule-derived-values"></a>**公開の日程から組む値は出典のある値**。 研究会・学会など公開の program がある出張では、 出席日・会期と出張期間の時刻・日程表の時刻を当事者に聞かず、 program (会期・各日の session の開始と終了・本人の講演枠) と、 発着地と会場の間の標準の所要から組む。 「記録に無い値を推測で埋めない」 に反しない (出典があるから)。 出典 (program の URL か記録の行) は案件の README に書く。 当事者に聞くのは program から決まらないものだけ (宿泊の有無・懇親会の後泊・財源・分かっている欠席)。 聞く段を残すと、 実際の出入りの時刻という誰も照合しない粒度で書類が止まる (実測)。 institution の規則としての置き場 = spec の規則 1 本 (他の様式は `same_as`)。

<a id="participants-at-intake"></a>**参加を決めた時点で、 同行者の書類の carrier も立てる**。 1 人の参加の決定が、 同行する人 (学生など) の事前の書類を生むことがある。 その書類はどの人の受信箱にも期限つきで届かない (期限は規則と出発日にしかない) ので、 決めた turn で参加者 1 人に 1 本の TODO を、 規則が定める提出期限 (出発の N 日前) を hard にして立てる。 事前の束に当事者の押印が要るなら、 その往復の分だけ前に渡す。 近場・日帰りでも、 手続きの有無は規則で確かめる (宿泊費が出ないことと、 手続きの有無は別の問い)。

<a id="recipient-send-version"></a>**当事者に送るのは「全部刷って、 本人が埋める欄を埋めて出す」 で完結する 1 本だけ**。 様式が頁ごとに扱いを分けている (例: 「この頁の原本は本人が持ち、 窓口にはコピーを出す」) とき、 その区別を当事者にさせない: 窓口に行く頁の見た目 (コピーなら白黒の raster) で束に入れ、 原本・確認用・別添のコピーは送らない。 送る便の指示は「刷って、 埋めて、 窓口に紙で出す」 だけにする。 recipe では印刷用の束から派生する出力 role として作る (`derive` から engine の `recipes.with_copy_page(<押印済みの束>, <plain>, <頁>, <出力>, anchor=<頁の目印>)` を呼ぶ = 頁の差し替え・認印の画像の印・刷る頁の宣言の引き継ぎはそこが持つ)。 案件ごとに手で作らない。

<a id="one-packet-per-recipient"></a>**1 人 1 便**。 当事者の束には本人の住所・口座が入る。 同じ行事の複数人でも宛先を 1 通にまとめない (まとめると互いの個人情報を配る)。 窓口の担当を Cc に入れたい連絡 (依頼・報告) は、 認印の画像入りの束とは別便にする (デジタルのまま窓口に届けない = 紙で出すものだけに印影を入れる運用と矛盾する)。

<a id="pii-runtime-source"></a>**個人情報は stub に書かず、 実行時に読む**。 住所・口座は workbook の欄にだけ入れる。 その値を既に持つ workbook (本人が前に出して受理された様式、 案件の置き場の xlsx) があれば、 stub の行を `value_from(<その xlsx>, <sheet>, <cell>)` にする (実装 = [`scripts/formcase/fill.py`](../scripts/formcase/fill.py))。 stub に残るのは出所の path と cell だけ。 読めない・空なら止まる (空欄のまま紙にしない)。

<a id="pii-runtime-source-text"></a>本人の回答が workbook でなく text の記録 (暗号化した markdown の台帳など) にしか無いときは、 stub の行を `value_from_text(<file>, <正規表現>, <group>)` にする (同じ [`scripts/formcase/fill.py`](../scripts/formcase/fill.py))。 当たりが 1 件でなければ止まる (書式が変わった・同じ語が 2 か所にある = どれを取ったか分からない値を紙に出さない)。

<a id="add-group-to-existing-case"></a>**先の group だけで作った案件に後の group を足す = `formcase.py add-group CASE --doc D --group G`**。 同じ workbook の別 sheet に業務後の書類を書く様式で、 group の区切りを持たない時期に作った案件 (manifest に先の group しか無い) を続ける入口。 manifest に draft + recipe の既定の出力名を足し、 その group の欄だけの stub `fill_<D>_<G>.py` を作る。 workbook は作らない・触らない (先の group の凍結 sheet はそのまま)。 manifest と stub を手で書かない (出力名が recipe の既定から外れる / 欄の漏れ)。 stub が並べるのは spec で必須の欄なので、 本人が書く欄 (住所・口座など、 回答があれば当方が書く欄) は回答があれば行を足し、 値は `value_from` / `value_from_text` で読む。

<a id="conditional-label-cell"></a>**記入欄の label が条件を持つ欄は、 条件を満たす時だけ書く** (例: 「左記と異なる場合に記入」 = 同じなら空のまま)。 書くと値が label の末尾に重なり、 字の切れ gate は label との重なりを見ない (実測)。 条件は spec のその欄の規則に書く (stub の comment は spec の写し)。

## <a id="fidelity"></a>14. 様式の忠実性 (= 記入欄以外が紙から黙って消える・変わるのを、 様式が何であっても止める)

同じ機構 (openpyxl の保存が図形を落とす) の別の現れ (標題・checkbox・区分の枠・様式番号・㊞) が、 症状の名前ごとに
別々に見つかっては別々に直され、 紙から見出しが消えたまま提出物が作られ続けた (実測)。 消え方の名前を
検査に持つ限り、 様式が新しくなっても・初めての様式でも・道具が変わっても次の名前で同じことが起きる。 ∴ 検査は
**様式が何であっても成り立つ不変条件**から組む:

> **出力 (紙になる PDF) と、 雛形を道具を通さず同じ app で刷った素刷りとの差は、 記入の宣言で説明できるものしか無い。**
> 差 = 消えた / 増えた / 変わった / 動いた。 説明できない差が 1 つでもあれば出力を書かない。

### 14.1 参照は 3 つ (どれも「前の出力」 ではない)

| 参照 | 何か | どう作るか |
|---|---|---|
| 雛形の宣言 (M) | 雛形 file が紙に出すつもりのもの = 印刷範囲の cell の字・図形 (字と数)・画像・form control・罫線・印刷設定 | 雛形の zip の XML を**道具に依らない parser** で読む ([`scripts/lib/office_census.py`](../scripts/lib/office_census.py)。 openpyxl / python-docx は読む時点で図形・form control を捨てる = 消す道具の目で数えない) |
| 雛形の素刷り (R0) | 雛形を**道具を通さず** app (Excel / Word) がそのまま刷った PDF。 印刷範囲・sheet の選択も app の操作で当てる | `formcase.py bind <form>` が Excel で 1 回刷り、 雛形の sha256 で cache する (`~/.cache/formcase/blank/`) |
| 記入の宣言 (F) | 案件が変える場所と変え方 | **雛形との差から導く** (人が番地を書かない): 記入欄 = 案件 workbook で雛形と値が違う cell / 導出欄 = 数式 cell (期待値 = app が保存した計算済みの値) / 体裁 = spec の `render:` と値の長さで伸ばした行 / 刷らない図形 = `render: drop_shape` (理由つき) / 受け入れる損失 = `meta.accept_loss` (理由つき) |

M と R0 の差 = **雛形自身の欠陥** (app が刷らない字・`=TODAY()` の `####`。 実測: 枠に字幅ぎりぎりの様式番号は素刷りでも末尾が切れる)。
`bind` が 1 回出し、 `render:` で直すか窓口に確かめるか受け入れるかを決める = build のたびに人が見るものではない。
前の出力を参照にしない理由 = [`docs/convention-design-principles.md#parity-against-own-output`](../docs/convention-design-principles.md#parity-against-own-output)。

### 14.2 どこで何を数えるか (層)

| 層 | 検査 | 実装 |
|---|---|---|
| T 雛形の identity | spec の bind の記録 (`<spec>.bind.json` の sha256) と build が読む雛形が同じか。 違えば ⚠️ = 雛形が新しくなった (差し替わった) → `bind` し直して差を見る | `formcase/fidelity.py` `bind_lines` (build の冒頭に行) |
| W workbook の census | temp (openpyxl で保存) の「紙に出るもの」 (図形の字・form control・画像・条件付き書式) が読み込み元より減っていないか。 減ることを受け入れる種類は `meta.accept_loss` に理由つきで宣言する | `recipes._save` → `fidelity.temp_census_lines` (⚠️ の行)。 他人の xlsx に書く道具・formcase の外の生成器も同じ census (`office_census.losses`) |
| R 出力 PDF | (a) 雛形の図形の字が在るか = **無ければ止める** (b) 書き換えていない cell の見出しが在るか (⚠️) (c) 素刷りより画像 (= Excel は checkbox の箱を画像として描く、 実測) が少なくないか (⚠️) (d) 雛形にも記入値にも無い字 (⚪) | [`scripts/check-form-static-text.py`](../scripts/check-form-static-text.py) `--filled` (体裁を当てた temp) `--blank` (素刷り)、 build が group ごとに回す |
| P 紙 | 刷る直前の preflight が、 出力 PDF の宣言 (`PrintPages` の `fidelity` = 雛形の path・対象・drop・素刷り) から同じ照合を回す。 図形の字が無ければ lp を止める、 雛形がその機械に無ければ ⚪ (照合できない、 と言って通す) | [`scripts/pdf-print-preflight.py`](../scripts/pdf-print-preflight.py) `fidelity_check` (`--hook` / `--template-xlsx`) |

**道具の損失は 2 段で消す**: (a) file を書く道具を**その形式を所有する app** (Excel / Word) だけにする = 損失が構造的に起きない
(Excel の AppleScript で cell の値・行高・結合・罫線・sheet の非表示・印刷範囲は当てられる = 実測。 openpyxl は読むだけ) /
(b) それでも残る損失 (app 自身の描画の癖、 未知の道具) を上の検査が止める。 (a) が本命、 (b) が網。 temp を openpyxl で
作る recipe は (b) だけで守られている = 図形は移植で戻るが form control の箱は戻らない (`accept_loss` で宣言し、 素刷りとの
画像の差として毎回 ⚠️ に出る)。

(2026-09-25 追記) 各段の運用と (a) の実装: T = 雛形が bind の記録と違えば**止める** (`formcase.py bind` で記録し直してから build)。
R の (c) 素刷りより画像が少ない = **止める** (openpyxl の temp で箱を落とすと `meta.accept_loss` に宣言した様式だけ ⚠️)。
R に段階 2 = **位置の写像**を足した: 素刷りと出力を label の位置の組で対応づけ (x は 1 次、 y は組の間の区分線形)、 画像の位置・
label の組に挟まれた帯の中の水平の罫線・同じ label の二重刷りを比べる (warn。 帯の外 = 値で行を潰す表 = 圏外と言って本数を出す)。
出力にも素刷りにも無い図形の字 = 雛形自身の欠陥 (⚪、 止めない)。 (a) の実例 = temp を作らず、 案件の workbook の copy に Excel で
体裁の差分 (結合・折り返し・揃え・字の大きさ・表示書式・上下の罫線 〔行ごとの range〕・行高・白黒・図形の削除・図形の枠の余白 =
`layout.excel_ops` + `drawings.single_line_insets`) と刷らない sheet の非表示・印刷範囲・1 枚を当てて刷る recipe
(`recipes.excel_chunks_pdf` / `hide_lines` / `fit_shape_lines`)。 docx は Word に段落ごとに書く ([`formcase/word.py`](../scripts/formcase/word.py)、
段落番号の写像 = 本文 → 表の cell の段落 → 行末の記号、 書く前に雛形の字と照合)、 書いた後に欄の run の書式を雛形と照合する
(`docx_form.run_format_lines`、 python-docx の `run.text` は空欄で既定の run を作り font・大きさが落ちる = 実測)。 build ごとの照合の
結果は設定 `fidelity_log` (jsonl) に残す (見出しの ⚠️ を止める段に上げる判断の材料)。 formcase の外で openpyxl で保存する生成器は
保存の直後に `office_census.assert_no_paper_loss` (紙に出るものが減れば止める、 減ると知って出すときは `OFFICE_CENSUS_ALLOW_LOSS=1`)。

(2026-09-25 追記 = form control の箱) 様式の checkbox が Excel の form control (VML + `xl/ctrlProps/*`) のとき、 選択は**箱の値**で表し、 label の cell は雛形の字のまま (文字の ☑ / ○ を前置しない)。 宣言 = spec の `controls:` (sheet / `anchor` = 箱が載る cell 〔controlPr の from〕 / `index` / `state: "on"` | `"off"`。 名前 "Check Box N" で決め打ちしない = 雛形の改訂で名前が変わっても cell で対応が付く。 ⚠️ YAML は裸の on / off を bool に読むので quote する)。 fill は cell の値と同じ Excel の 1 回で箱の値を書き ([`formcase/fill.py`](../scripts/formcase/fill.py) `control_edits`)、 zip の `ctrlProp` の `checked` で読み戻す。 照合は 3 段: ① 記入内容 gate が `checked` を spec と照合する (anchor に箱が無ければ 雛形が spec と違う = 止める) ② build が出力の箱の画像を画素で数え ([`check-form-static-text.py`](../scripts/check-form-static-text.py) `box_pixels` = 4 辺の濃い帯が辺、 内側の濃い画素が印)、 印のある箱の数が on の数と違えば止める (`--expect-checked`) ③ 辺が欠けた箱は、 素刷りにも欠ければ雛形自身の欠陥 (⚪、 `bind` で 1 回見る類)、 出力だけ欠ければ ⚠️。 欠けの原因 (実測) = Excel は control を枠の大きさ (pt) のまま raster にするので、 枠が描く箱より小さいと辺が切れる (枠 ≤ 16pt で右辺が欠け、 ≥ 17pt で 4 辺が出る) → Excel の経路の recipe は刷る前に枠を `recipes.CONTROL_FRAME_PT` (18pt) まで広げる (`control_frame_min` op = `fit_control_lines`)。 箱の値は案件の workbook に入るので、 凍結の fingerprint (VML の Checked) がそれを含む = 凍結した issue を読み直しても同じ紙。

(2026-09-25 追記 2 = 箱の印の読みやすさ) Excel (Mac) の form control の ✓ は、 control の枠を raster にした画像の中の数 px の灰色にしかならず、 紙では約 1 mm の点で読めない (実測、 検収で見つかった)。 build は印の入った箱 (画像の bitmap に control 自身の ✓ が在る箱) の外枠の内側を白で塗って太い黒の ✓ を PDF の vector で重ね (`check-form-static-text.py --mark-checked` = `fidelity.mark_boxes`)、 照合は「印のある箱の数」 に加えて「紙で読める印の数」 (箱の内側を render した黒の面積比 `box_ink` ≥ `INK_READABLE`) も選んだ数と比べる (合わなければ止める)。 箱の外枠は画像の SMask (透明の余白) から取る (alpha を落として読むと余白が黒に見える = 実測)。 素刷りが無くても出力の箱は数え (期待の照合は素刷りに依らない)、 素刷りがある時は素刷りの箱の位置に在る画像だけを箱に数える (印影・図などの小さい画像を箱にしない)。

(2026-09-26 追記 3 = 箱の縦ズレ) 枠を広げるのは**幅だけ** = 高さを足すと Excel は枠の中で箱を縦に中央に描くので箱が下がる (実測: +4pt で +1.4pt、 点線に跨った)。 画像の置き場の照合 (位置の写像) は画像の中の箱の移動を見ないので、 置き場から見た箱の上端・左端の offset を素刷りと比べ、 0.5pt を超えれば止める (`box_shifts`、 対応づけは同じ label の写像で = 行が伸びて箱ごと下がるのは正常)。

### 14.3 記入欄の宣言 (= 人が番地を書かない)

- 記入欄は**案件と雛形の差**で決まる (spec の `cells:` は「何を・なぜ書くか」 の規則で、 検査の地図ではない)。 雛形が変われば
  記入欄も変わり、 ずれた番地に書けば「雛形の見出しが消えた」 として現れる
- 宣言するのは 3 種だけ、 全部理由つき: `drop_shape` (刷らない図形。 理由に**雛形の中の衝突か、 自分の spec の規則との衝突か**を
  書く = 前の欠けを雛形の欠陥と読み違えた実測から) / `accept_loss` (temp で減ることを受け入れる種類) / `render:` (雛形の欠陥の体裁直し)
- 雛形が新しくなれば sha256 が bind の記録と違って気づく。 新しい雛形で spec の番地の意味が変わっていないかは `bind` の後の**素刷りの差** (見出し・図形・
  画像の数) と記入内容 gate で見る。 番地を label の anchor から再導出する段 (spec の番地を cache にする) は段階 2

### 14.4 限界 (= 人に残るもの)

| 見えないもの | 理由 | 埋め方 |
|---|---|---|
| 図形・画像の**位置**のずれ、 二重刷り、 重なり | 検査は在るか・数だけを見る (位置に依らない = 行を伸ばしても誤検出しない、 の裏) | 段階 2 (素刷りと label の位置で対応づけて比べる)。 それまでは build 末尾の「素刷りとの差」 の行を見て目視 |
| 雛形自身の欠陥 (素刷りでも切れる字・####) | 参照 R0 が同じ癖を持つ | `bind` の M∖R0 の一覧 = 採用時に 1 回人が決める |
| 相手の機械で刷る xlsx の描画 (font の有無・字幅の丸め) | こちらの app の外 | 紙はこちらで刷る。 xlsx を渡す経路は「刷って見せてもらう」 しか無い |
| 値の中身 (正しい日付か・所属が最新か) | 忠実性は「雛形 + 記入の宣言」 の外を見ない | 記入内容 gate (spec) と人 |
