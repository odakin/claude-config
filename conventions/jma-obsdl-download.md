<!-- doc-meta
when: 気象庁の過去観測データ (時別値・日別値等) をスクリプトで一括取得したいとき
category: infra
summary: 気象庁「過去の気象データ・ダウンロード」(obsdl) の機械取得 recipe — show/table POST の現行フィールド (#show-table-post、 旧 recipe の interAnnualFlag は現行 interAnnualType で 400 になる)、 element/地点 ID の動的発見 (#element-station-discovery)、 44,000 値制限に合わせた block 設計と politeness (#volume-limit-politeness)、 CSV の位相・エンコーディング・品質列 gotcha (#csv-format-gotchas)、 protocol はページ自身の JS から読む一般技法 (#protocol-from-page-js)、 取得物は既知データと突合してから使う (#validate-before-use)
-->
# 気象庁 obsdl の機械取得 (過去の気象データ・ダウンロード)

気象庁の過去観測データの一括取得は「過去の気象データ・ダウンロード」(<https://www.data.jma.go.jp/risk/obsdl/>) の form POST を再現するのが機械経路 (= [`machine-route-first.md`](machine-route-first.md) の instantiation)。認証・セッション cookie は不要で、Python stdlib (urllib) だけで完結する (2026-08-29 実測)。

⚠️ ページ自身に「自動化ツール等による過度のアクセスはお控えください」の注意がある。**#volume-limit-politeness の設計 (リクエスト数の最小化 + 間隔) を必ず守る**。

## <a id="show-table-post"></a>show/table POST (ダウンロードの本体)

`POST https://www.data.jma.go.jp/risk/obsdl/show/table` に application/x-www-form-urlencoded で:

| field | 例 / 意味 |
|---|---|
| `stationNumList` | `'["s47607"]'` (JSON 文字列。官署は `s`+地点番号) |
| `aggrgPeriod` | `9`=時別値, `1`=日別値 (radio 値は index.php の DOM 参照) |
| `elementNumList` | `'[["101",""]]'` (要素番号と option の組の配列。時別値の降水量=101、気温=201) |
| `interAnnualType` | `1` (連続期間) ⚠️ **ネット上の旧 recipe の `interAnnualFlag` は現行 protocol に無く、送ると HTTP 400** |
| `ymdList` | `'["1976","1979","1","12","1","31"]'` = [開始年, 終了年, 開始月, 終了月, 開始日, 終了日] |
| `downloadFlag` | `true` (false なら HTML 表示用) |
| `csvFlag` `rmkFlag` `disconnectFlag` `ymdLiteral` | `1` |
| `kijiFlag` `youbiFlag` `fukenFlag` `jikantaiFlag` | `0` |
| `jikantaiList` | `'[]'` (時別で時間帯指定なし)、`optionNumList` = `'[]'` |

PHPSESSID 等のセッションは不要。response は Shift_JIS の CSV。

## <a id="element-station-discovery"></a>要素番号・地点 ID の動的発見

ハードコードされた対応表に頼らず、UI が使う AJAX を直接叩いて調べる:

- 要素一覧: `POST /risk/obsdl/top/element` に `{aggrgPeriod: 9}` → HTML 内の `<input name="element" value="101">降水量` 等から番号を読む
- 地点一覧: `POST /risk/obsdl/top/station` に `{pd: <都道府県番号>}` (富山=55, 長野=48, 岐阜=52, 三重=53) → 各 station div 内の `<input name="stid" value="s47607">` が ID。`kansoku` (観測種目 bitmask) で当該要素の観測有無も分かる

## <a id="volume-limit-politeness"></a>データ量制限と politeness 設計

- 1 リクエストの上限 ≈ **44,000 値** (ページ JS の `seigen` 変数)。時別 1 要素 1 地点なら **4 年ブロック (≤35,065 値) が安全マージン付きの最大単位** — 例: 4 地点 × 50 年 = 52 リクエストで済む
- リクエスト間隔は数秒以上あける。失敗時はより長く待って再試行。冪等設計 (取得済み file は skip) にして再実行を安全にする
- 取得は一括 1 回で済ませてローカルに保存し、再解析で再取得しない (politeness の本体はリクエスト総数の最小化)

## <a id="csv-format-gotchas"></a>CSV の gotcha

- **時刻は「1:00〜24:00」表記で、値は前 1 時間の積算** — 0:00 起点の連続グリッドに載せるには index を −1 時間シフトする
- エンコーディングは **Shift_JIS** (UTF-8 で decode すると化ける)。ヘッダは 4〜5 行
- 値列に加えて **現象なし情報・品質情報・均質番号**列が付く。品質情報 <8 は不完全値、**均質番号の変化 = 観測条件の断絶** (移転等) なので、長期解析ではまず均質番号が単一かを確認する — これらは手作業ダウンロードでは見落としがちな資産
- 出典明記で利用可 (気象庁ホームページの利用規約に従う)

## <a id="protocol-from-page-js"></a>protocol はページ自身の JS から読む (一般技法)

form POST が 400 で拒否されたら、**ネット上の recipe を変えて再試行する前に、ページが読み込む JS (ここでは `web/js/top.*.js`) の ajax 呼び出し部を読む**。field 名・既定値・制限値 (`seigen`) は全部そこに書いてあり、protocol 改版 (例: `interAnnualFlag`→`interAnnualType`) にも追従できる。UI を in-app browser で操作して network capture から学ぶのは第二の経路 (こちらは UI の状態機械が絡んで遠回りになりがち)。

## <a id="validate-before-use"></a>取得物は既知データと突合してから使う

取得経路を信じる前に、**同一区間の既知データ (過去に手作業で取った CSV 等) と値を突合**して経路を検証する (位相ずれ・単位・欠測表現の取り違えはここで露見する)。突合が取れて初めて多年一括取得に進む。
