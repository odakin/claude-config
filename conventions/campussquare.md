<!-- doc-meta
when: 大学の教務システム CampusSquare for WEB (シラバス・履修者名簿・成績登録) を読む・扱うとき + 名簿 CSV を科目別に分けるとき + 成績を CSV で一括登録するとき + 内蔵 browser でログイン画面が出て「読めない」 と言いそうになったとき
category: web
summary: CampusSquare は学内 SSO の奥だが browser の session cookie 再利用で script から読める (scripts/campussquare-client.py、 シラバス検索・本文) / 画面は Spring Web Flow = hidden の _flowExecutionKey と _eventId を POST → 302 → GET / 教員でログインするとシラバス検索の担当者欄に本人名が既定で入る / 名簿・成績 CSV は CP932・CRLF・全 field quoted・評語は末尾から 2 列目 / アップロードと「提出」 は別操作
-->
# CampusSquare for WEB (教務システム) の自動化

日本の大学で使われる教務システム **CampusSquare for WEB** (context path `/campusweb`) の機構 fact 集。 学内 SSO (Shibboleth SP + 外部 IdP) の奥にあり、 user が発行できる API credential は無い。 経路の選び方の一般則は [`machine-route-first.md`](machine-route-first.md)。 すべて実測 (導入先 1 件)。 導入先ごとに画面構成・CSV の列が違いうる箇所は ⚠️。

## <a id="script-route"></a>読む経路 = browser の session cookie 再利用

- [`scripts/campussquare-client.py`](../scripts/campussquare-client.py): `syllabus-search` (年度・時間割番号・科目名・担当者・語) / `syllabus <時間割番号>` (本文を text で) / `status` / `doctor`。 host は `--base` (env `CAMPUSSQUARE_BASE`) で与え、 個人層の入口 script が注入する ([`script-layer-placement.md`](script-layer-placement.md))
- cookie = host の `JSESSIONID` (CampusSquare) と `_shibsession_*` (SP)。 IdP の cookie は読まない。 CampusSquare 本体の session は短い (30 分程度) が、 IdP のログインが browser に生きていれば、 起動中の browser に裏で開かせて入り直す (= [`garoon.md#garoon-session-recovery`](garoon.md#garoon-session-recovery) と同じ仕組み、 部品 = `scripts/lib/browser_tab.py`)
- 同じ組織の別サイト (groupware 等) が同じ IdP で cookie 再利用に乗っているなら、 CampusSquare もほぼそのまま乗る

## <a id="web-flow"></a>画面の仕組み (Spring Web Flow)

- 画面を開く = `GET /campusweb/campussquare.do?_flowId=<FLOW>` → 302 → `?_flowExecutionKey=...` の画面
- 操作 = その画面の form の hidden `_flowExecutionKey` と `_eventId` を付けて `POST /campusweb/campussquare.do` → **302 → GET** で次の画面が返る (POST の応答そのものは本文が空)。 key は画面ごとに変わるので、 毎回直前の画面から取る
- ポータル = `GET /campusweb/campusportal.do?page=main` (生きていれば 200。 軽い生存確認に使える)
- シラバス検索 = flow `SYW0001000-flow`、 form `SearchForm` を `_eventId=search` で POST (field: `nendo` / `kaikoKubunCode` / `kyokannm` / `kaikoKamokunm` / `jikanwaricd` / `yobi` / `jigen` / `freeWord` / `_displayCount`)
  - ⚠️ **教員でログインしていると `kyokannm` (担当者) に本人の氏名が既定で入っている** = 画面の値をそのまま送ると自分の担当だけに絞られる。 他人の科目を探すなら空にする
  - 結果の各行 = `refer('<年度>','<時間割所属コード>','<時間割番号>','<locale>')` → form `ReferForm` を `_eventId=input` で POST すると「シラバス参照」 画面 (読むだけ。 保存の操作は無い)
- 公開シラバス検索の URL でも、 未ログインだと IdP のログイン画面に飛ぶ導入先がある

## <a id="roster-grade-csv"></a>履修者名簿・成績の CSV

成績登録画面から全担当科目の名簿 CSV を 1 file で download でき、 評語を埋めて upload すると一括登録になる。

- **形式 = CP932 (Shift-JIS)、 CRLF、 全 field quoted**。 先頭行が header (日英併記)
- ⚠️ 列数は科目で揺れる (カナ列の有無など) → 評語欄は index 固定でなく **末尾から 2 列目** (最後が mail) で扱う
- **旧課程・新課程で同じ授業に別の時間割番号 (科目名まで違うことがある) が付く** → 科目別に分けるときは科目名や番号でなく **曜日・時限** で束ねる
- 埋め方 = 対象行の評語欄だけを書き換え、 他の行はバイト不変にする。 照合 = 変更した行数 = 埋めた人数、 評語以外の差分ゼロ、 分布が確定値と一致
- 評語欄が空の行は無害: upload するとエラー CSV (これも CP932) に「既に成績の入力状態が変更されています」 (= 画面で手入力済みの科目、 手入力が残る) や「中間成績の登録が不要な時間割です / 成績登録期間外」 (= 通年科目の前期など) が出るだけで、 評語の入った行の取り込みは止まらない
- upload 後の検算 = 一覧画面の「評価割合 (%)」 を確定した分布の人数比 (四捨五入) と突合
- **提出確定は upload と別の操作**: 各科目の「提出」 にチェック → 「提出済み（全員）」 → 更新。 全科目が提出済みになると一括更新欄が空になる
- 評価不能 (X) も CSV で通る
- 現状の script は読むだけ (名簿の download・成績の upload は画面)。 書き込みを足すときは読み戻し照合までを 1 単位にする ([`web-form-automation.md#step-driver-harness`](web-form-automation.md#step-driver-harness))
