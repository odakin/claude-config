<!-- doc-meta
when: 大学の教務システム CampusSquare for WEB (シラバス・履修者名簿・成績登録) を読む・扱うとき + 名簿 CSV を科目別に分けるとき + 成績を CSV で一括登録するとき + 内蔵 browser でログイン画面が出て「読めない」 と言いそうになったとき + 配られた授業計画表の xlsx で自分の登録 (開講期・曜時) を照合するとき (#plan-table-xlsx) + ダウンロードセンターの配布資料 (会議資料・手引き・様式) を一覧・取得・展開するとき (#download-center) + 掲示板 (お知らせ) を読むとき・案内された「お知らせ」 の資料が見つからないとき (#bulletin-board) + 自分の授業の実施教室・コマを確かめるとき (#teacher-schedule)
category: web
summary: CampusSquare は学内 SSO の奥だが browser の session cookie 再利用で script から読める (scripts/campussquare-client.py、 シラバス検索・本文・履修者名簿 CSV・ダウンロードセンターの配布資料) / 画面は Spring Web Flow = hidden の _flowExecutionKey と _eventId を POST → 302 → GET / 教員でログインするとシラバス検索の担当者欄に本人名が既定で入る / 名簿・成績 CSV は CP932・CRLF・全 field quoted・評語は末尾から 2 列目 / アップロードと「提出」 は別操作 / 授業計画表 xlsx は曜日ごとの 5 列の組が横に並ぶ = 組ごとに読む、 照合 = scripts/campussquare-plan-table.py (旧課程の別名の行・年次の書き方の違いに注意) / ダウンロードセンター = 一覧 (flow SDW0001000-flow、 公開期間の窓で絞られる) の各行の fileId を GET (file 名は Content-Disposition の URLEncoder 形 = + が空白)、 zip のパスワードはその行のサマリ欄・中の file 名は UTF-8 flag なしの CP932 (client の dl-list / dl-get --extract) / 掲示板 = flow KJW0001100-flow (最初は未読だけ、 既読込みはジャンルの一覧 dispKeijiListGenre = client の bulletin)、 ポータルの Home のお知らせ欄 (portlet) は script から読めない / 自分の時間割と教室 = スケジュール管理 (flow PTW0001200-flow) の月表示、 client の schedule (シラバスに教室が無くてもここにある)
-->
# CampusSquare for WEB (教務システム) の自動化

日本の大学で使われる教務システム **CampusSquare for WEB** (context path `/campusweb`) の機構 fact 集。 学内 SSO (Shibboleth SP + 外部 IdP) の奥にあり、 user が発行できる API credential は無い。 経路の選び方の一般則は [`machine-route-first.md`](machine-route-first.md)。 すべて実測 (導入先 1 件)。 導入先ごとに画面構成・CSV の列が違いうる箇所は ⚠️。

## <a id="script-route"></a>読む経路 = browser の session cookie 再利用

- [`scripts/campussquare-client.py`](../scripts/campussquare-client.py): `syllabus-search` (年度・時間割番号・科目名・担当者・語) / `syllabus <時間割番号>` (本文を text で) / `roster-csv --out-dir <dir>` (全担当科目の名簿 CSV = [#roster-csv-download](#roster-csv-download)) / `dl-list [--folder <語>]` と `dl-get <fileId>... --out-dir <dir> [--extract]` (ダウンロードセンターの配布資料 = [#download-center](#download-center)) / `schedule [--from YYYY-MM] [--months N]` (自分の時間割と教室 = [#teacher-schedule](#teacher-schedule)) / `status` / `doctor`。 host は `--base` (env `CAMPUSSQUARE_BASE`) で与え、 個人層の入口 script が注入する ([`script-layer-placement.md`](script-layer-placement.md))
- cookie = host の `JSESSIONID` (CampusSquare) と `_shibsession_*` (SP)。 IdP の cookie は読まない。 CampusSquare 本体の session は短い (30 分程度) が、 IdP のログインが browser に生きていれば、 起動中の browser に裏で開かせて入り直す (= [`garoon.md#garoon-session-recovery`](garoon.md#garoon-session-recovery) と同じ仕組み、 部品 = [`scripts/lib/sso_cookie_session.py`](../scripts/lib/sso_cookie_session.py))
- 同じ組織の別サイト (groupware 等) が同じ IdP で cookie 再利用に乗っているなら、 CampusSquare もほぼそのまま乗る
- <a id="auth-error-page"></a>⚠️ **本体の session が切れると、 flow の GET は 302 でなく 200 で「認証エラー」 画面を返すことがある** (title が「認証エラー」、 form `authorizationError` を JavaScript で親画面へ POST し直すだけの画面)。 切れ判定を「302 か login 画面か」 だけにすると、 この画面を普通の画面として読み、 次の form が無いという別のエラーに化ける。 client の `expired()` はこの画面も切れとして扱い、 入り直す (実測)
- <a id="portal-ssologin-redirect"></a>⚠️ **未ログインの portal (`campusportal.do`) は同じ host の `ssologin.do` への 302 を返し、 同時に未認証の `JSESSIONID` を配る** (実測)。 切れ判定が `/login` の path だけを見ていると、 この 302 を「読める」 と読む (`status` が切れているのに「読める (302 )」 と答えた)。 また browser が portal を開いただけで cookie DB が変わるので、 それを「入り直せた」 と読むと未認証の cookie で撃ち直して失敗する。 client は `ssologin` も切れとして扱い、 入り直しは読み直した cookie を server が受け入れた時だけとする (= [`garoon.md#login-page-mints-session-cookie`](garoon.md#login-page-mints-session-cookie) と同じ罠。 client の `probe` でこの 2 つの形がそのまま見える)

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
- <a id="roster-two-shapes"></a>**名簿 CSV は 2 つの形がある** (実測): 全担当科目を 1 file にしたものは学生氏名カナの列を持ち、 科目 1 つの画面から落としたものはカナの列が無い。 後者には同じ授業に付いた旧課程の別番号の学生も入る (新課程の番号の行 → 旧課程の番号の行の順、 file 名は慣習的に `<年度>_<新課程の番号>.csv`)。 header は `"…" ,"…"` と引用符の後ろに空白が入る形。 前者から後者の形を作る = [`scripts/campussquare-roster-split.py`](../scripts/campussquare-roster-split.py) (`--course <書き先>=<新課程の番号>,<旧課程の番号>…` を科目ごとに、 カナの field を除いて行の bytes はそのまま、 既にある file は上書きしない)
- **旧課程・新課程で同じ授業に別の時間割番号 (科目名まで違うことがある) が付く** → 科目別に分けるときは科目名や番号でなく **曜日・時限** で束ねる
- 埋め方 = 対象行の評語欄だけを書き換え、 他の行はバイト不変にする。 照合 = 変更した行数 = 埋めた人数、 評語以外の差分ゼロ、 分布が確定値と一致
- 評語欄が空の行は無害: upload するとエラー CSV (これも CP932) に「既に成績の入力状態が変更されています」 (= 画面で手入力済みの科目、 手入力が残る) や「中間成績の登録が不要な時間割です / 成績登録期間外」 (= 通年科目の前期など) が出るだけで、 評語の入った行の取り込みは止まらない
- upload 後の検算 = 一覧画面の「評価割合 (%)」 を確定した分布の人数比 (四捨五入) と突合
- **提出確定は upload と別の操作**: 各科目の「提出」 にチェック → 「提出済み（全員）」 → 更新。 全科目が提出済みになると一括更新欄が空になる
- 評価不能 (X) も CSV で通る
- <a id="roster-csv-download"></a>**名簿の download は script で取れる** (実測): `campussquare-client.py roster-csv --out-dir <dir>`。 成績登録の flow (`SIW0001000-flow`) の form `downloadForm` を `_eventId=outputCsvAll` / `nendo=<年度>` / `shikenKbnCd=1` で POST → 302 → GET で `text/csv` の attachment (`regis<YYYYMMDD>.csv`、 全担当科目 1 file の形) が返る。 画面の「CSV一括ダウンロード」 ボタンと同じ操作 = 読むだけで、 学期は画面が開いた時点の学期。 学期途中の履修登録の追加を拾うときは、 取り直して前の版と学生番号で突き合わせる
- 成績登録の flow の画面の JavaScript が使う event (form `downloadForm`。 画面の source から読んだだけで、 実行して確かめたのは `outputCsvAll` だけ): 科目ごとの名簿 = `outputCsv` (`nendo` / `jikanwariShozokuCd` / `jikanwariCd` / `shikenKbnCd` / `chukanSeisekiFlg` / `chukanFlg` を埋める)、 同じ引数の PDF = `outputPdf`、 一括 upload の画面へ進む = `csvInputAll`。 同じ tab に成績提出 (`SIW0001020-flow`) と成績確認表出力 (`SIW0401400-flow`) の flow もある = upload (書き込み) を足すときの入口
- 成績の upload は今も画面。 書き込みを足すときは読み戻し照合までを 1 単位にする ([`web-form-automation.md#step-driver-harness`](web-form-automation.md#step-driver-harness))

## <a id="download-center"></a>ダウンロードセンター (配布資料) を script で取る

事務の各課が教員向けに配る資料 (会議資料・手引き・様式) の置き場。 画面ではフォルダを開いて 1 本ずつ落とすが、 一覧と取得は script でできる (実測)。 client = `campussquare-client.py dl-list [--folder <語>] [--from/--to <日付>]` / `dl-get <fileId>... --out-dir <dir> [--extract]` / `dl-missing --have <dir> [--folder <語>] [--match <正規表現>]` (保存漏れ = [#download-missing-check](#download-missing-check))。

- **一覧** = flow `SDW0001000-flow` を開いた最初の画面。 全フォルダの中身が HTML 1 枚 (数百 KB) に入っていて、 フォルダの開閉は JavaScript で隠しているだけ
  - フォルダの見出し行 = `<tr id="folder<N>">` の `td.accordion` 4 つ (フォルダ名 / 公開期間 / オーナー = 配った課 / サマリ)。 中身 = 直後の `<tbody id="detail<N>">`
  - ファイル行 = `<table id="fileTable<N>">` の中の `<tr class="fileRecord">` = (削除の checkbox の欄) / `<a href="…?_flowId=SDW-filerefer-flow&fileId=<id>">ファイル名</a>` / 登録日 / サマリ
  - ⚠️ **下位フォルダは親の `detail<親>` の中の入れ子の表に並び、 親のファイルの表はその後ろに来る** = 行の並び順で帰属を決めると、 親のファイルが最後の下位フォルダに付く。 ファイルの表の id (`fileTable<フォルダ id>`) で決める
  - ⚠️ ページの JavaScript に、 upload 後に行を足すための `<tr class="fileRecord">` の雛形の文字列がある = 正規表現で数えると 1 件多い。 HTML parser で script の外だけを読む
  - ⚠️ **一覧は公開期間で絞られている**: 画面の既定の窓は今日の前後 1 か月 (form `conditionForm` の `dayFrom` / `dayTo`)。 窓を変える = 同じ form を `_eventId=listup` と `dayFrom` / `dayTo` (書式 `2026年09月01日`) で POST (画面の「表示」 と同じ。 client の `--from` / `--to`)。 窓を前年度に動かすとフォルダの数が変わる (実測)。 どの条件で出るか (窓と公開期間が重なるフォルダか) は推定
- **取得** = `GET /campusweb/campussquare.do?_flowId=SDW-filerefer-flow&fileId=<id>` → 302 → 200 の attachment。 flow key は要らない (fileId だけ)。 `Content-Type` は file の種類 (`application/x-zip-compressed` / `application/pdf` など)
  - <a id="download-filename-urlencoder"></a>⚠️ **file 名 = `Content-Disposition: attachment; filename="<名前>"`、 名前は Java の URLEncoder の形**: UTF-8 を percent-encode し、 空白は `+`、 `+` そのものは `%2B`。 ASCII だけの名前でも空白は `+` で来る (実測) = 「percent-encode されている時だけ + を空白に」 とすると ASCII の名前に `+` が残る。 値が URLEncoder の出力の文字 (英数字 `. - * _ +` と `%XX`) だけなら + を空白に戻してから decode する
- <a id="download-zip-password"></a>**zip のパスワードは、 一覧のその file の行のサマリ欄に書いてある** (実測の形 = 「パスワード「…」」「パスワードは「…」です」、 説明なしで値だけを書いた欄もある)。 配る課が決まった書式 (日付を埋め込んだ固定形など) を使っていた時期があっても、 今はファイルごとに違う = 書式から推測せず、 サマリ欄から読む
  - 実測した zip の暗号は従来の ZipCrypto (Python の `zipfile` で読める)。 AES の zip が来たら `zipfile` では開けない (client は「方式に未対応」 で止まる)
  - ⚠️ **zip の中の file 名は UTF-8 flag (0x800) なしの CP932** = `zipfile` が cp437 として読んで化ける。 `info.filename.encode("cp437").decode("cp932")` で直す (flag の立った名前はそのまま)
  - ⚠️ サマリ欄をそのまま一覧に出すとパスワードが出力に残る = `dl-list` は値を `***` に伏せ、 `dl-get --extract` が内部で使う (どの候補で開けたかも値は出さない)
- <a id="download-pdf-password"></a>**パスワード付きの PDF も配られる** (議事録など、 zip でなく PDF 1 本にパスワード。 パスワードは同じくサマリ欄)。 `--extract` は PDF なら暗号化を外した写しを作る (PyMuPDF の `authenticate` → `tobytes(encryption=PDF_ENCRYPT_NONE)`)。 手元に置くのは写しの方 = 検索・抽出で毎回パスワードを要らなくする。 置き場所が暗号化されていることを先に確かめる
- 保存は名簿 CSV と同じ流儀 = 同名で中身が違えば上書きせず別名。 `--extract` は `<dir>/<stem>/` に展開・復号し、 `__MACOSX` と `..` を落とす。 取った資料は学内限定の配布物 = private 層にしか置かない
- <a id="download-missing-check"></a>**保存漏れは機械で拾う**: 会議の資料を「通知が来たら取りに行く」 だけで回すと、 取りに行く起点が無かった回の資料が保存されないまま残る。 `dl-missing --folder <語> --have <手元の dir> [--match <正規表現>]` = 一覧のファイル行のうち、 手元の名前に一致するものが無い行だけを出す (一致の鍵 = NFKC で全角・半角の括弧を同じに、 拡張子 `.zip` / `.pdf` と空白を無視 = 展開したフォルダ名・置き直した名前とも突き合う)。 無ければ無出力なので、 session 開始の hook や一覧画面に載せて出し続けられる。 読むたびにログインの入り直しが起きうる (browser が裏で開く) ので、 結果を状態 file に持って間隔を空ける

## <a id="bulletin-board"></a>掲示板 (お知らせ) を script で読む

- 掲示板 = flow `KJW0001100-flow` (GET → 302 → title「掲示板」 の画面)。 最初の画面は**未読の一覧**だけ = 一度開いた掲示は出ない (実測)。
- 既読も含む一覧 = その画面の link `_eventId=dispKeijiListGenre&keijitype=<区分>&genrecd=<ジャンル>` を GET する (ジャンル = 課ごとの「〜からのお知らせ」、 一覧は全件を 1 画面で返した)。 ⚠️ keijitype・genrecd の値は導入先ごとに違う = 値は未読一覧の画面の link から拾う。 ⚠️ **link は最初の画面に書かれた `_flowExecutionKey` のまま開く** = 直前に開いたジャンルの画面の key に差し替えると、 1 つおきに一覧でない画面 (件数の行が無い) が返った (実測。 最初の画面の key のままなら全ジャンルが開けた)。
- 道具 = client の `bulletin [--genre 語] [--grep 正規表現]` (全ジャンルを既読込みで 1 行ずつ = 掲載日時 | 掲示期間 | seqNo | 表題、 ジャンルごとに全件数。 一覧でない画面が返ったジャンルは flow を開き直して 1 回だけ撃ち直す。 件数より行が少なければ「次の頁は読まない」 と出す)。 「お知らせに載っていない」 と書く前の照合はこれ 1 本 (見た範囲 = 掲示板の全ジャンル。 下の Home の欄は含まない)。
- 本文 = 一覧の各行の link (`_eventId=confirm` / 未読一覧からは `displayMidoku`、 + `seqNo`)。
- ⚠️ **ポータルの Home の「お知らせ」 欄 (portlet) は script から読めなかった** (実測、 原因は未確認): 画面はこの欄を `campusportal.do?page=main&action=rwf&tabId=home&wfId=<menuId>&rwfHash=<ポータルの HTML の portalConf の値>` で AJAX に読む (menuId は同じ HTML の menus の `information` / `information_s` 〔職員向け〕 など) が、 同じ cookie に `X-Requested-With` と Referer を付けても「SYSTEM ERROR」 の断片が返った。 案内文が「Home のお知らせに掲載」 と言う資料が掲示板の全ジャンルに無いことがある = その時は本人に画面で開いてもらう (内蔵 browser は学内 SSO の cookie を持たない)。

## <a id="teacher-schedule"></a>自分の時間割と教室 (スケジュール管理) を script で読む

授業の実施教室は、 シラバスにも学科の時間割表にも書かれていないことがある (実測)。 教員の「スケジュール管理」 の月表示に、 自分のコマが教室つきで並ぶ。 client = `campussquare-client.py schedule [--from YYYY-MM] [--months N] [--days]` (読むだけ)。

- **画面** = flow `PTW0001200-flow` (ポータルのメニューの「スケジュール管理」)。 最初の画面は今月の月表示。 各日の欄 (`td`) に「予定を足す」 link `addSchedule(YYYYMMDD)` があり、 そこから日付が取れる。 コマは 1 行ずつ `N限:科目名@教室` の文字列で並び、 行を包む要素の class が種別 (開講は `kaiko`、 休講・補講は別の class = 凡例の色分け)。 科目名・教室は全角の英数字で来る = NFKC で半角にする
- **月を送る** = 同じ画面の form `ScheduleListForm` を `_eventId=setNextMonth` / `setPrevMonth` で POST (画面の「next / prev」 と同じ)。 送った後の見出し (`YYYY年M月`) で着いた月を確かめる
- 旧課程と新課程で時間割番号が 2 つある授業は、 同じ「N限:科目名@教室」 が 2 行出る (別の科目名で出ることもある) = 日付ごとに重複を落として数える
- 研究室で行うコマは、 教室の欄が「研究室」 などの語で来る
- 同じ情報は「休講補講教室変更登録」 (flow `KHW0001000-flow`) の週の一覧にも時間割番号つきで出るが、 そちらは書き込みの画面 = 読むだけなら月表示を使う
- 既定の表示が週単位に設定されている場合の形は未実測 (月の見出しが見つからなければ client は止まる)

## <a id="plan-table-xlsx"></a>授業計画表 (xlsx 出力) で自分の登録を照合する

教務の画面から、 科目グループ (学科・課程) ごとの「授業計画表」 を xlsx で出力できる。 学科の取りまとめ役がこれを配り、 各教員に自分のコマ (特に前期・後期) の確認を頼む運用がある (実測)。 画面を開かずに照合できる。

- **形**: 表題 (「授業計画表」・年度・科目グループ) の後に見出し行 `NO | 開講期 | 曜時 | 科目名 | 担当者 | 選必 | 年次 | 曜時2 | 科目名2 | …` = **曜日ごとの 5 列の組が横に 5 つ並ぶ**。 1 行に複数の曜日の組が入るので、 行でなく組ごとに読む。 担当者名は姓と名の間が全角空白。 末尾に曜時も担当者も空の行 (曜時が未設定の枠) が並ぶことがある
- **照合** = [`scripts/campussquare-plan-table.py`](../scripts/campussquare-plan-table.py): 科目グループの file を全部渡し、 `--teacher <名前>` と、 予定を `--expect "開講期 曜時 科目名"` で 1 件ずつ。 ✅ 一致 / ❌ 予定にあるのに登録が無い / ➕ 登録にあるのに予定に無い、 で出る (不一致があれば exit 1)
- ⚠️ **読み方の罠** (実測):
  - 「年次」 は履修できる年次の範囲 (例 `2・3・4`) で、 学科の時間割表に書く配当年次 (例 `(2)`) と書き方が違う。 食い違って見えても登録の誤りではない
  - 旧課程と新課程の合同開講は、 **旧課程の科目グループに、 同じ曜時で別の科目名の行が出る** (新課程の「X（基礎）」 が旧課程では「X」 など)。 予定に旧課程側の名前も書く (書かないと ➕ で出る)
  - 全教員で担当する演習・講究の類は、 全員分が同じ曜時に 1 行ずつ並ぶ = 自分の行があるかだけを見る
  - 開講期「通年」 の行は前期・後期の行とは別に出る (予定も「通年」 で書く)
