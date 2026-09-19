<!-- doc-meta
when: 機密を持つ repo と remote を持つ repo の境界を機械で守るとき — 暗号化を入れる前 (#2) / file 名に識別子が出ていると気づいたとき (#1) / 別 process への通知に要約を書こうとしたとき (#3) / 流出検査を設計するとき (#4) / fail-open な gate を足したとき (#5) / 公開 repo に未公開文書の文が入らない gate を設計・調整するとき (#unpublished-text-public-gate) / 公開 repo の tree 棚卸しの finding を決着させるとき (#tree-finding-resolution) / 公開 repo の gate の検出語や判定を変えたとき (#gate-change-replays-unattended-writers) / 触れない dir の中身を機械で処理する必要が出たとき (#work-on-a-copy-not-by-lowering-the-gate)
category: infra
summary: 暗号化は中身しか守らない (file 名・commit message・path は平文) ので識別子入り dir は暗号化 tar に畳む (連番+対応表は対応表が単一障害点で不可)、 保存しない > 暗号化する (通知に payload を載せず schema で縛る、 死んだ複製は削除)、 逐語の指紋照合は写しを捕まえるが言い換えは原理的に不可なので経路ごとに制御を変える (閾値は全件集計で決める = 誤検知 6800→24→0 の実測)、 fail-open な gate は必ずカナリアで実効性を毎回確かめ ARMED/NOT ARMED/対象外 の 3 状態を出す (沈黙を作らない)、 是正は go-forward にしか効かず履歴は別問題として人間の判断に委ねる、 公開 repo には未公開文書の逐語 gate を別に置く (漏れる例示は引用符に入った短い断片なので quoted span が主、 全履歴 replay で誤検出 0 を確かめて採用)、 gate が target の pre-commit で実際に走っているかは target ごとに確かめる、 触れない dir の中身を機械で処理する必要が出ても deny を外して戻す形にしない (外れている間は dir 全体が無関係な call にも開く) = user が 1 file だけ許可 scope に複製 → 作業 → 複製と中間生成物を消す、 複製は元の SoT から分岐し記録には file 名も中身も書かない
-->
# 機密の境界を機械で守る — 暗号化・file 名・通知・検査

機密を「置いてよい場所」 と「置いてはいけない場所」 の境界を、 規律ではなく機械で守るための規約。
起源は 2026-09-12 の一連の事故と是正 (未公開の試験問題・学生の個人情報・別 session への返送 marker)。

関連: [`secret-handoff.md`](secret-handoff.md) (= 値そのものの受け渡し) /
[`debugging-discipline.md`](debugging-discipline.md) (= 検査を書くときの罠) /
[`multi-session-coordination.md`](multi-session-coordination.md) (= session 間の返送)。

---

## 1. 暗号化は「中身」 しか守らない

git-crypt のような透過暗号は **file の中身だけ**を暗号化する。 次はすべて remote に平文で残る:

- **file 名・dir 名** (= ツリーに一覧として見える)
- **commit message**
- **追跡されている path そのもの** (`.gitignore` の行を含む)

∴ 識別子を名前に持つ file (`answers/A00X0001-1.jpg`、 `records_2025_A00X0002_surname.docx`) は、
中身を暗号化しても **「誰が居たか」 の一覧を公開したまま**になる。

### 直し方: 1 個の暗号化コンテナに畳む

dir ごと 1 個の `tar` にして、 その tar を暗号化対象に載せる。 ツリーに見えるのは tar 1 個で、
**中の file 名は tar の内部に保たれる**。

採ってはいけない対案: **連番化 + 対応表**。 対応表が単一障害点になり、 壊れた瞬間に
「どれが誰のものか」 が永久に失われる。 リネーム工程が毎期の手作業として増え、 file 名を key に
している配管すべてに波及する。 tar なら対応表が要らない。

実装 = [`scripts/pack-pii-dirs.sh`](../scripts/pack-pii-dirs.sh) (`pack` / `unpack` / `check` / `check-all`)。
対象 dir は **各 repo の `.pii-pack-dirs`** が宣言する (= 機構側に repo 固有の知識を持たない)。

⚠️ **畳む前に、 展開して 1 file ずつ byte 比較する**。 検証に失敗したら tar を捨てて何も変更しない。
⚠️ **dir 名自体に識別子が入っているなら先に rename する** (= そうしないと tar 名と `.gitignore` の行に残る)。
⚠️ 畳んだ後、 新しい file は `.gitignore` により **git に入らなくなる**。 期末に畳むまでバックアップが
   無い状態になるので、 `check` (tar より新しい file があるか) を定期検査に載せる。
⚠️ **履歴には旧 file 名が残る**。 畳むのは「これ以上広げない」 操作であって、 過去を無かったことには
   しない。

検出 = [`scripts/check-pii-filenames.py`](../scripts/check-pii-filenames.py)。
識別子の形は `~/.claude/pii-filename-patterns.txt` が宣言する (= 形自体が組織固有で、 かつ
それ自体漏らしたくない情報になりうるので script に書かない)。

---

## 2. 「暗号化する」 より「保存しない」 が上位

暗号化は **保存せざるを得ないもの**を守る技術で、 鍵管理と「鍵の無いマシンで静かに壊れる」
failure mode が必ず付いてくる。 保存しなくて済むなら、 そちらが強い。

判断の順序:

1. **そもそも書かないで済むか** (= 通知に payload を載せない、 要約を別の場所に置く) → schema で縛る
2. **死んだ複製ではないか** (= 誰も読んでいない残骸なら削除が最善)
3. 残ったものを暗号化する

### file 名が漏れる対象に暗号化を足しても、 偽の安心しか増えない

暗号化が効くのは **「中身が価値で、 名前が無害」** なもの。 名前のほうが情報を持っている対象
(= 作業内容が token 名に出ている通知 file 等) は、 中身を暗号化しても名前で分かるので、
**schema を縛るほうを選ぶ**。

---

## <a id="notification-is-not-a-report"></a>3. 通知は報告書ではない

別 session や別 process への「終わった」 通知 (marker / status file) に、 結果の要約を書き始めると、
その要約が payload になって境界を越える。 通知の contract を機械で縛る:

- **要約の長さに上限を置き、 超えたら書かずに失敗する** (= 報告書化を止める)
- **成果物が機密なら、 task / summary / 成果物の path を中立な文言に置き換えて記録する** — 判定は
  「成果物が機密として宣言された dir の配下か」 と **「成果物の本文が機密索引に一致するか」**
- 落とした内容は **呼び出し元に返し、 人間に口頭 (chat) で伝えさせる**
- 明示的な opt-out を 1 つだけ用意し、 判定不能は縛らない (= fail-open)

⚠️ 判定を「成果物の path が作業ルートの外か」 のような**位置**で決めると、 sandbox worker の
成果物受け渡しのような正当な機能まで巻き添えにする。 **中身で判定する**。

---

## 4. 逐語の照合は「写し」 しか捕まえない

機密の流出検査には 2 種類あり、 **守れる範囲が違う**:

| 方式 | 捕まえるもの | 捕まえないもの |
|---|---|---|
| **指紋照合** (= 機密文書の本文を索引にし、 一致を探す) | 逐語の写し (copy-paste)、 引用 | 言い換え・要約 |
| **pattern 照合** (= 識別子の正規表現) | file 名・ID・固有の token | 上と同じく言い換え |

**言い換えは原理的に検出できない。** 実測: 別 session への返送 marker に書いた「要約」 は、
元の成果物と指紋一致 **0** だった (自分の言葉で書き下ろしたため)。

∴ **経路ごとに制御を変える**。 copy-paste の経路は content 検査で、 人が書き下ろす経路は
schema (= そもそも書けなくする) で守る。 片方で両方を守ろうとしない。

実装 = [`scripts/check-confidential-leak.py`](../scripts/check-confidential-leak.py) (pre-commit BLOCK)。
機密文書の置き場所と索引範囲は machine-local の一覧 file が宣言する (= script には書かない)。

<a id="paraphrase-reading-list"></a>**言い換えは gate にできないが、 読む候補は語彙の重なりで出せる** (2026-09-14)。 自分の言葉で書き直した例示も、
その文書に固有の語 (模型名・macro・parameter の値) を運んでいることが多い。 [`scripts/scan-private-vocabulary.py`](../scripts/scan-private-vocabulary.py)
`--scan <公開 repo>` が「公開 repo と非公開 repo が共有し、 他の repo ではほとんど使われない語」 を file:回数 付きで出す
(`--staged` / `--diff A..B` なら追加行だけ = hoist の commit 前、 `--source-ext .tex --kinds word,control,decimal` で原稿由来に絞る。
実測で公開 2 repo が 76 行 / 241 行)。 **出力は finding でなく読む候補** (公刊文献と原稿は語彙を共有する)、 しかも非公開 repo 名と
語彙そのものを含むので端末に留める。 ⚠️ 評価の文章 (査読所見・模擬審査の指摘) は普通の語で書かれるので、 語彙の重なりにも
出ない = 過程の語で別に走査する ([`convention-design-principles.md#sweep-null-needs-per-form-control`](../docs/convention-design-principles.md#sweep-null-needs-per-form-control))。

### 指紋の閾値は測って決める

実測 (2026-09-12、 追跡 file 830,786 行に対して。 空白を除いた連続 24 文字を 1 断片):

| 索引に入れる条件 | 誤検知 |
|---|---|
| 制限なし | **6,800 行** — LaTeX の定型 (`\documentclass` `\begin{tikzpicture}`) と共有された path |
| 日本語 1 文字以上 | **24 行** — `\newtheorem{theorem}{定理}` のような、 定型に 1 語混じったもの |
| **日本語 4 文字以上** | **0 行** ← 採用。 実際の本文 1 文は 24 断片で一致する |

⚠️ **サンプルを数件見て原因を決めない**。 最初 12 件を見て「区切り線が原因」 と判断したが、
実際はその 1/3 で、 残りは定型と path だった。 出どころ別に**全件**集計して初めて分かった。

⚠️ ASCII だけの識別子 (file 名等) は日本語比率の下限で落ちる。 そこは pattern 照合が担当する
= **役割分担**であって、 片方の閾値を緩めて両方を拾おうとしない。

### <a id="unpublished-text-public-gate"></a>公開 repo には「未公開文書の逐語」 の gate を別に置く (2026-09-13)

上の指紋照合は「local-only repo の実体」 を remote 付き repo に入れない gate で、 日本語だけを索引にする。
**英文の原稿**と、 **remote は持つが公開ではない repo** (= 共著者と共有する原稿 repo) の本文は、 その索引の外にある。
公開 repo の規約の「実例」 に未公開原稿の文をほぼ逐語で写した commit が 1 週間で 3 回 landed したのは、 この隙間だった。

- **target は公開 repo だけ** (`.claude/public-repo.marker`)。 原稿 repo や決定台帳は原稿を引くのが仕事なので対象にしない。
- **源の宣言は個人層**: `discover: ~/Claude .tex` (= 非公開 repo の `.tex` 全部。 新しい原稿 repo も自動で入る) と、
  公刊済み・第三者の本文を外す `exclude:`。 script には置き場所を書かない。
- **検出は 2 つ**。 較正で分かったのは、 漏れた例示の大半が**引用符に入った 5〜9 語の短い断片**だったこと
  (内容語の shingle だけでは 7 語で 1 件も拾えなかった):
  - **quoted span** = backtick か二重引用符の中の、 空白区切りで 5 語以上 (内容語 3 以上) の文で、 5 語の窓が全部源に在るもの。
  - **prose run** = 引用符なしで、 内容語 6 個の連続が源と一致するもの (markdown の fence の中は除く)。
- **正規化**: LaTeX の comment・数式・preamble・引用 key・制御綴り・謝辞の節を除き、 日本語は run を切る。
  3 つ以上の top-level dir に現れる shingle は定型として捨てる。 索引は hash だけを cache に置く。
- **較正** (公開 2 repo の全履歴 1,667 commit に replay):

| 設定 | 検出 | 内訳 |
|---|---|---|
| 内容語 shingle のみ、 7 語 | 0 | 漏れた例示も拾えない |
| 内容語 shingle のみ、 5 語 | 9 | 半分が TikZ の option・path・公的機関の名前・よくある物理の句 |
| quoted span、 語を letter の塊で数える | 26 | 大半が backtick の path (`a/b-c.md` が 5 語に数えられた) |
| **quoted span (空白区切りで 5 語) + prose run 6 語 + 謝辞の除外** | **10 (4 commit)** | **全件が原稿由来、 誤検出 0** ← 採用 |

- **捕まえないもの = 言い換え** (上の表どおり)。 未公開の結果を自分の言葉で書いた例示は通るので、
  規律 ([`CLAUDE.md#non-identifier-content-leak`](../CLAUDE.md#non-identifier-content-leak)) はそのまま要る。
- ⚠️ **gate を作ったことと、 target の commit で走っていることは別の事実**。 同じ日に、 指紋 + pattern の gate
  (`check-confidential-leak.py`) が層3 の chain にだけ配線され、 公開 repo の pre-commit (`public-precommit-runner.sh`)
  からは呼ばれていなかったと分かった = 一番守るべき target で走っていなかった。 両方を public runner の Tier D にした。
  配線は target の種類ごとに、 実際の commit (一時 repo で可) で止まることを確かめる (#5 のカナリアと同じ)。
- ⚠️ **公開 repo の gate の唯一のスイッチは `.claude/public-repo.marker`**。 同じ日に、 GitHub で public の clone 7 本が marker を
  持たず、 Tier A-D のどれも走っていなかったと分かった (新規 repo の setup 経路は marker を書くが、 他所で作られた repo の clone は
  一度も通らない)。 点検 = [`scripts/check-public-marker.py`](../scripts/check-public-marker.py) (GitHub の visibility と marker と
  hook を突き合わせる。 marker を pull した直後の別マシンは `--hooks-only --fix-hooks` が hook を揃える)。
- **配線の確認は 2 段**: `--check-wiring` = 本番の索引でカナリアが止まるか。 `--check-wiring --through-hooks` = 一時の公開 repo に両 hook を入れ、 引用を含む stage と message が実際の commit で拒否され、 平文の commit が通るか。 後者は runner の配線切れや設定の解決失敗まで捕まえる (約 5 秒)。
- 止まったときは file と行と源の名前だけを出し、 一致した本文は出さない。 公刊版に在る文だと確かめた場合だけ
  `CLAUDE_UNPUBLISHED_GUARD=0` で 1 回通す。

---

## 5. fail-open な gate は、 効いているかを毎回確かめる

検査は fail-open (= 設定不足・source 不達・正規表現破損で黙って素通り) に作るのが正しい。
gate 自身の不調で作業全体を止めないためである。 しかしその代償として
**「効いていないことに気づけない」** — 「gate が在る」 という誤った安心だけが残る。

∴ **fail-open な gate には必ず、 実効性を毎回確かめる別の検査を付ける**:

- 設定 file が **カナリア** (= 無害な合言葉) を宣言する
- 検査は **本番の設定のまま** 一時 repo を作り、 カナリアを実際に BLOCK できるか試す
- 結果を **必ず 1 行出す**。 沈黙という状態を作らない:
  `ARMED` / `NOT ARMED` (理由つき、 FAIL) / `対象外` (= 宣言された対象に実体が無い) /
  `未配線` (= 対象の宣言そのものが無い)

⚠️ <a id="not-configured-is-not-nothing-to-protect"></a>**`対象外` と `未配線` を混ぜない** — 対象を宣言する設定が空 / 不在のとき、
検査は「守るべきものが無い」 と **確かめずに断定**できてしまう (= 空の設定が「対象なし」 と同じ顔をする、
[`docs/convention-design-principles.md#detector-config-must-be-derived`](../docs/convention-design-principles.md#detector-config-must-be-derived))。
設定が無いなら、 そのマシンに実体が在るかは **未確認**であって、 無いことの証明ではない。
2 つは別の語で出し、 `未配線` では「在るなら宣言するまで gate は走らない」 まで書く
(= 読んだ人が「自分の環境は守られている」 と誤読しないところまでが報告)。

⚠️ **カナリアの値を engine 側に literal で書かない** — 書くと engine 自身の commit が自分の
gate に弾かれる。 値の home は設定 file だけにし、 engine は directive 名だけを持つ。

同じ理由で、 **暗号化を入れたら「このマシンで実際に読めるか」 の検査も必ず付ける**
([`scripts/check-gitcrypt-readable.py`](../scripts/check-gitcrypt-readable.py))。
ロックされたマシンでは暗号文がそのまま読め、 fail-open な呼び出し側は **黙って 0 件**を返す。
「1 件も無い」 と「読めていない」 が区別できなくなるのが最悪の壊れ方。
鍵を持たない環境 (CI 等) は **SKIP を宣言して緑にしない**。

### <a id="protected-dir-access-guard"></a>読むだけでも触らせない dir は、 path rule でなく PreToolUse hook で守る

**罠**: settings の `Read(path)` / `Edit(path)` の ask / deny rule は、 Bash では file を名指しする読み方 (`cat` など) にしか効かない ([`claude-code-permissions.md#file-rule-tools`](claude-code-permissions.md#file-rule-tools))。 **上位 dir から再帰する検索は、 保護 dir の名前を 1 度も書かずに中へ届く** (実測: repo を横断して探す sweep が上位 dir からの `find` で保護 dir を拾い、 続く loop の `git -C` と相対 path の `grep` が中を読んだ。 確認は 0 回)。 Grep / Glob tool を上位 dir から走らせたときに path rule が効くかは未検証 (確かめるには保護 dir を検索することになる) なので、 同じ hook で先に塞ぐ。

**機構** = [`hooks/protected-dir-access-guard.py`](../hooks/protected-dir-access-guard.py) (PreToolUse `Bash|Grep|Glob`、 **ask**):

- 確認を出す = path の名指し (実体 path / home 直下の symlink 別名 / `~` / `$HOME` / `親/名前` / 親の直後の glob) ・ 上位 dir を名指しした再帰 (find / grep -r / rg / du / os.walk / `**/` …) ・ cwd が中 ・ cwd が上位 dir で再帰 ・ cwd が親で名前か glob ・ Grep / Glob の起点が中か上位 dir
- 出さない = 名前を含む文 (commit message・規約の grep) ・ 再帰しない一覧 ・ 保護 dir の外の具体的な dir への再帰
- 保護 dir そのものには触れない (親だけを実体化して比べる)
- **宣言** = `~/.claude/protected-dirs.txt` と `~/.claude/leak-pattern-sources.txt` (§4 の作業リポ登録)。 remote に出してはいけない実体の置き場は、 触ってもいけない dir でもある — 別の list にすると片方だけが更新される ([`docs/convention-design-principles.md#detector-config-must-be-derived`](../docs/convention-design-principles.md#detector-config-must-be-derived))
- <a id="swap-the-new-gate-in-first"></a>⚠️ **どちらも machine-local なので、 二重の門を入れ替えるときは順序が要る**: この一覧 file は**即時**に効き、 settings の rule は**次 session から**効く。 だから path rule の kind を緩める (`deny` → `ask`) ときは **先に一覧を配り、 後から rule を外す**。 逆にすると、 file を名指ししない読み方が確認なしで通る窓が開く。 一覧を git の宣言から配る engine = [`scripts/sync-protected-dirs.py`](../scripts/sync-protected-dirs.py) (足すだけ・冪等。 宣言に無い行と他経路の一覧は消さない)、 rule 側は [`multi-machine-state.md#gate-rules-reassert-every-session`](multi-machine-state.md#gate-rules-reassert-every-session)。 ⚠️ 一覧が空のマシンでは hook は何も守らない (fail-open) ので、 **緩める前にそのマシンの `--canary` が保護 dir を数えているか**を見る
- **この hook 自体は deny にしない**: その dir の作業 session では中で作業するのが正当。 止まるのは仕様。 ⚠️ **ただし settings 側に `deny` を重ねている環境がある** (= 作業 session でも Claude には触らせない、 と決めた dir)。 hook の ask と deny rule が同じ command に当たると **hook の理由だけが返って deny は見えない** ので、 拒否の原因を hook だと読み違える ([`claude-code-permissions.md#hook-masks-deny`](claude-code-permissions.md#hook-masks-deny))。 deny を重ねてあるかは settings の `permissions.deny` を読んで確かめる (hook の挙動からは分からない)
- fail-open なので §5 のとおり `--canary` で毎回確かめる (ARMED / NOT ARMED / 未配線 / 対象外)
- ⚠️ 射程外 = 変数に分けて組み立てた path、 script file の中の走査。 目的は事故の防止で回避への対策ではないので、 **横断の検索・sweep を書く側の規律**と併用する: 対象は repo の一覧 (registry) から取り、 上位 dir からの `find` で発見しない

### <a id="work-on-a-copy-not-by-lowering-the-gate"></a>触れない dir の中身を処理する必要が出たら、 gate を下げずに「1 file だけ外に出してもらう」

`deny` で守った dir の file を Claude に処理させたくなる場面はある (機械でしかできない検査・変換・印刷の前処理など)。 このとき **deny を外して作業して戻す**のは最悪の選択肢 — 外れている間は**その dir 全体**が、 当の作業に関係しない call にも開く。 外し忘れれば boundary は黙って消える。

⚠️ **「作業のたびに本人が許可する dir」 は、 下げて戻すのではなく最初から `ask` にする** (= 別の判断)。 本人が中で作業する dir を `deny` にすると、 許可を出しても通らず、 通すために毎回 gate を触ることになる (= 上の最悪の選択肢を常態化させる)。 その dir は `ask` にして **1 操作ごとに確認を出す** — dir が開きっぱなしにならず、 許可は操作ごとに本人が出す。 ⚠️ `ask` は kind を変える恒久的な判断なので、 **git に載せた宣言で全マシンを揃える** ([`multi-machine-state.md#gate-rules-reassert-every-session`](multi-machine-state.md#gate-rules-reassert-every-session))。 file を名指ししない読み方 (`find` / `grep -r` / script の中の走査) は path rule の射程外なので、 [`#protected-dir-access-guard`](#protected-dir-access-guard) を併せて配線する。 以下は「本人も触らせるつもりがない dir」 の話。

**順序**:

1. **やらずに済ませられないかを先に見る**: 出力だけが要るなら、 手順を user に渡して user の手元で実行してもらう (= 中身が Claude の context にも tool 結果にも入らない。 **最も安全**)
2. それでも Claude が処理する必要があるなら、 **user が対象 file だけを許可 scope の dir に複製**する。 露出が「1 file・1 回」 に限られ、 boundary の設定は動かない。 **複製は user が行う** (Claude が copy すると、 保護 dir を読む操作そのものが deny に当たるうえ、 「Claude が勝手に外へ出した」 形になる)
3. 終わったら**複製と中間生成物を消す**。 消す対象を作業の最後に 1 行で列挙する (temp dir の中間 file・render した画像・抽出した部分 file は忘れられやすい)

**⚠️ 複製した瞬間に増える risk** (= 「1 file だけ」 は無害の意味ではない):

- **複製は元の SoT から分岐する**: 元が直っても複製は直らない。 複製から作った成果物 (印刷物・変換結果) は、 **どの版から作ったか**を残さないと後から照合できない ([`office-automation.md#printed-artifact-staleness`](office-automation.md#printed-artifact-staleness) と同じ構造)
- **複製先が backup・同期・索引の対象だと露出が伸びる**: home 直下の同期 folder に置くと、 消す前に別の場所へ渡ることがある。 置き場は同期されない local dir を選ぶ
- **記録に中身を書かない**: 作業の記録・別 session への通知・commit message には、 **file 名も中身も書かない** (= 記録は remote に乗る。 [`#notification-is-not-a-report`](#notification-is-not-a-report) の「通知は報告書ではない」 と同じ)。 書くのは「1 件処理した」 までで、 所在は口頭 (chat) で渡す

**これを「回避の手口」 にしない**: 2 の判断をするのは user であって Claude ではない。 Claude 側の既定は 1 で、 2 は user が明示的に選んだときだけ成立する。 Claude が「こうすれば通ります」 と先に手を動かす形にすると、 gate は事実上無い。

---

## 6. 過去の分は別問題として扱う

ここまでの操作はすべて **go-forward** にしか効かない。 既に commit / push されたものは
履歴に残る。 是正のたびに次を明示する:

- **今回の操作で止まるもの** (= 今後の書き込み)
- **止まらないもの** (= 履歴、 既に配られた copy、 別 session の transcript)
- 履歴の書き換えを行うかは、 clone を壊す不可逆操作なので **必ず人間の判断**に委ねる

既存の記録を新しい基準で棚卸しする口を用意しておくと、 基準を変えた時に遡れる
(= 「後から機密と分かったもの」 を中立化する操作も含めて)。

公開 repo の未公開文書の逐語は、 gate (追加行だけを見る) とは別に `scripts/check-unpublished-quote.py --scan-tree <repo>` で現在の全 file を棚卸しできる (2026-09-13 に公開 2 repo を走査し、 残っていた 1 件を一般形に直して 0 件)。

### <a id="gate-installed-after-history"></a>gate を入れても、 入れる前から在った中身は検査されていない

pre-commit gate は **staged 差分 (= これから足す行) しか見ない**。 だから **既に履歴のある repo に
gate を後から入れても、 その repo の中身は一度も検査されないまま**残る。 「gate を入れた」 は
「検査した」 ではなく、 設置直後の finding 0 は *在庫を見ていないから 0* でしかない。
一般則 = [`docs/convention-design-principles.md#detector-installed-after-the-stock`](../docs/convention-design-principles.md#detector-installed-after-the-stock)。

∴ **gate を設置したら、 同じ turn に tree 全体を 1 回通すまでが 1 単位**:
[`scripts/scan-public-tree.sh`](../scripts/scan-public-tree.sh) が tracked file を temp dir に展開して
fresh な index に置き、 **全 file が「追加行」 に見える状態**で同じ runner を走らせる (= Tier A-E が
そのまま tree 全体に当たる)。 `--all` で marker つき repo を横断、 結果は machine-local の台帳に記録し、
**finding があった repo は「走査済」 にしない**。

既に公開されていて「見た上で残す」 と決めたものは、 repo の `.claude/public-tree-accept.txt` に
理由つきで 1 行書く。 この受理は **棚卸しにだけ効き、 commit gate には効かない** (= 新しい書き込みは
今までどおり止まる)。 受理できるのは token を名指しできる Tier A だけで、 件数と file 名しか出ない
Tier B/C (= 実名・非公開 repo 名) は受理させない — 寝かせてよい物を型で絞る。

⚠️ 射程は **現在の tree** まで。 過去の commit の中身と commit message は別
(= message の棚卸しは `check-unpublished-quote.py --replay`、 履歴の書き換えは人間の判断)。

⚠️ **vendored / 生成物の dir を名前で走査から外さない**。 実測: 大量の finding の出元が他人の package cache に
見えた repo で、 中身を分けると実体の大半は **build tool の生成物に焼かれた、 共同作業者の開発機の home path**
(= owner 側の漏洩) だった。 dir 名で外していたらそれごと隠れる。 生成物を追跡しているなら直し方は
**追跡を外す** (+ 標準の `.gitignore`) で、 除外ではない。

#### <a id="published-metadata-is-public"></a>公刊済みの著作の書誌は、 構造で検出器から外す

arXiv / DOI で公開された著作の **題名・著者・要旨**は定義上もう公開されている。 ところが論文を記録する bot の
archive は著者名をそのまま持ち、 自分の論文が載った日には要旨が手元の原稿と逐語で一致する。 実測: その archive を
stage すると実名 (Tier B) と逐語 (Tier D) が必ず落ち、 **無人の自動 commit が毎回止まる** (= 止める物は無いのに
transport が黙って壊れる)。 README の参考文献 link も、 改稿中の原稿と同じ題名で Tier D に当たる。

許可 list で逃がすと論文が増えるたびに古くなる。 書誌は行の構造で見分けられるので構造で外す
([`scripts/lib/published_metadata.py`](../scripts/lib/published_metadata.py)、 runner の Tier A-C と Tier D / E の engine が共有):
- JSON: arXiv id か arXiv / DOI / INSPIRE の URL を持つ object の `title` / `abstract` / `authors` の**値の行**
  (pretty-print のときだけ。 1 行 JSON は外さない = 鳴る側)
- Markdown: 公開先 URL への link **だけ**で出来ている行
- **外さない**: 同じ object の `reason` / `summary` 等 (= 書き手の文) と、 link の外に語がある行。
  ⚠️ 書き手の文を AI が生成する bot では、 生成の指示に「購読者・共同研究者の名前を書かない」 を入れる
  (= 構造で外せない側の文は、 源で書かせない)

#### <a id="name-compound-allow"></a>姓の短い term が地名などに当たるときは、 複合語だけを許可する

実名 gate の term には姓の 2 字 prefix も入る (= 本文では姓だけで書かれるため)。 その 2 字が地名・歴史上の人物名の
一部に現れると、 公開の地図や冗談の文言で鳴る。 prefix ごと stoplist に落とすと「X さん」 も止まらなくなる。
∴ **その複合語だけ**を個人層の設定 (`compound_allow`) に書き、 照合の前に本文から消す
(行の種類の正本 = [`scripts/lib/sensitive-terms.sh`](../scripts/lib/sensitive-terms.sh)、 commit gate・commit-msg・週次監査で共通)。
builder は **3 字以上の term や ASCII term を含む複合語を拒否**する (= 氏名を消す抜け道にしない)。 同じ行に
姓だけの言及が残れば今までどおり止まる。 足すのは中身を読んで人を指さないと確認したときだけ。

#### <a id="generated-data-declaration"></a>外部の公開データを機械が変換して置いた file は、 生成元つきで宣言して棚卸しから外す

官公庁の公開データを CI が毎日 JSON に直す、 のような file は第三者の公開記録で、 人名・連絡先・日付と件数が数千行並ぶ。
実名・連絡先・活動の事実の棚卸しが全部鳴り、 行ごとの承認もデータ更新のたびに失効する。 受理一覧に
`generated: <glob>  # <生成元>` と書くと、 **棚卸しからだけ**外れる (commit gate には効かない)。
path 単位の除外は後から入った本物も黙らせる ([`#semantic-detector-ack-ratchet`](../docs/convention-design-principles.md#semantic-detector-ack-ratchet)) ので、 代償を型で絞る
([`scripts/lib/public_tree_accept.py`](../scripts/lib/public_tree_accept.py)): 宣言できるのは **データ形式の file だけ** (文章・code が 1 つでも当たれば宣言ごと無効)、
glob は tracked file に当たること、 生成元を書くこと、 外した数を走査のたびに表示すること。

#### <a id="tree-finding-resolution"></a>棚卸しの finding を決着させる判定表

finding は「直す」 か「見た上で残す」 のどちらかで閉じるが、 残し方は finding の種類で口が違う。 **上から順に当てる**
(= 直せるものを残す口に流さない):

| finding の中身 | 決着のさせ方 |
|---|---|
| owner 側が書いた識別子・非公開 repo 名・未公開の文 | **本文を一般形に直す** (Tier B/C は受理できない) |
| 開発機の home path が設定・build spec に焼かれている | **bug fix として直す** ([`#personal-path-is-also-a-portability-bug`](#personal-path-is-also-a-portability-bug)) |
| IDE / game engine 等が生成する cache・log・user 設定を追跡している | **追跡を外す** + その tool の標準 `.gitignore` (dir を名前で走査から外すのではない) |
| upstream (fork 元・同梱 runtime・exporter) の連絡先・例示 path・版番号 | Tier A の **受理** (token + 理由) |
| IP に見える版番号 (browser の User-Agent の `Chrome/<major>.0.0.0`・assembly の `Version=<n>.0.0.0` 等) | Tier A の **受理** |
| 姓の短い term が地名・歴史上の人物名・普通語の一部に当たる | 個人層の **`compound_allow`** ([`#name-compound-allow`](#name-compound-allow)) |
| arXiv / DOI の書誌 (題名・著者・要旨)、 公開論文への link だけの行 | 何もしない (runner が構造で外す = [`#published-metadata-is-public`](#published-metadata-is-public))。 残るなら構造 (id / URL) が無い |
| 外部の公開データを機械が変換した file | **`generated:` 宣言** ([`#generated-data-declaration`](#generated-data-declaration)) |
| 名前が公開 repo 自身の identity の一部 (公開 mirror の源の名前など) | 非公開 repo 名の例外 list (owner 判断、 criterion は層1 の安全規則) |

- どの種類の term が当たったかは gate の出力から分からない (件数と file 名だけ) — [`scripts/explain-sensitive-hits.py`](../scripts/explain-sensitive-hits.py) `--repo` が同じ除外を当てた後の残りを種類つき・term を伏せて出す
- **archived の公開 repo** は push できない。 受理一覧を入れるなら unarchive → commit (message に `[skip ci]` = 古い CI を起こさない) → push → すぐ archive に戻し、 戻ったことを確認する
- 決着させたら **本番の台帳で** `scan-public-tree.sh --repo <repo> --force` を 1 回通す (= temp の台帳で確かめただけでは進捗にならない)

#### <a id="gate-change-replays-unattended-writers"></a>gate を締めたら、 その前に立つ無人の書き手の過去の出力を通し直す

検出語の再生成・Tier の追加・runner の修正は、 **公開 repo に自動で commit する routine** (日次の archive 等) を黙って止めうる。
書き手は失敗を warning で握りつぶす設計のことが多く、 その日の出力に偶然当たる語が無ければ、 当たる出力が出る日まで表に出ない。
実測: 検出語を締めた後、 論文を記録する bot の archive が共著者名と手元の原稿と同じ要旨で必ず止まる状態になっていたが、 締めた当日の出力は通っていた。

∴ gate を変えた turn に、 無人の書き手の直近の commit を **今の** gate に通す: [`scripts/replay-public-gate.sh`](../scripts/replay-public-gate.sh)
`--repo <repo> --path <書き手の出力先> --since "14 days ago"` (C が変えた file だけを temp repo に置き、 親の版 → C の版の差分として runner を回す)。
止まる commit があれば、 誤検知なら検出器側を直し ([上の判定表](#tree-finding-resolution))、 本物なら書き手の出力 (生成の指示) を直す。
定期実行にも載せる (= gate の変更と書き手の出力の変化のどちらからでも鳴るように)。 一般則 =
[`docs/convention-design-principles.md#detector-change-breaks-downstream-writers`](../docs/convention-design-principles.md#detector-change-breaks-downstream-writers)。

### <a id="visibility-decided-at-publish-time"></a>公開にするかは、 中身が出来てから・公開する直前に決める

repo を作る時点の「公開してよいか」 は、 **まだ書かれていない中身についての予測**でしかない。
実際に書かれるもの — とくに **設計判断の記録** — は、 他の repo との比較や没案の理由を含むので、
**非公開の対象への参照が自然に生える**。 その参照は削れば判断の記録が読めなくなる種類のもので、
「公開のために薄める」 と資料の価値そのものが落ちる。

∴ visibility は **初回 push の直前にもう一度判定する**。 判定材料は、 上の tree 全体の走査結果が
そのまま使える (= Tier C が出るなら、 その repo は公開に向いていない、 という情報)。

- 非公開への参照が **消せるなら**消して公開する
- 参照が **判断の記録そのもの**なら、 repo を非公開にする方が安い
- 公開を選ぶなら、 その repo は以後すべての commit が gate を通る (= 毎回の税) ことも見込む

⚠️ 公開 → 非公開へ倒しても、 **公開されていた間のことは取り消せない** (= 公開 event は外部の
記録に残りうる)。 「短時間だから無かったこと」 にはせず、 何が外に出たかを書き残す。
visibility の **判断基準そのもの** (何を公開する人なのか) は個人の層に属する。

### <a id="personal-path-is-also-a-portability-bug"></a>個人の環境に依存する literal は、 漏洩であると同時に移植性のバグ

成果物に焼かれた **home 直下の絶対 path・machine 名・個人の dir 構成** は、 識別子が漏れるだけでなく
**書いた本人以外の環境では解決しない**。 つまりこの class の是正は「公開のために我慢して薄める」 のではなく、
**直して初めて正しく動く**。

- build spec の `pathex`、 3D モデルの texture 参照、 project file の library path、 IDE の設定 — いずれも
  他人の clone では**その path が存在しない**ので、 既に壊れているか、 黙って fallback している
- ∴ 見つけたら「漏洩の是正」 ではなく **bug fix として直す**。 実行時に解決する形 (= 成果物の置き場所から
  相対で引く / tool が注入する変数を使う) に置き換えると、 識別子も消え、 どの clone でも動くようになる
- ⚠️ 直す前に **その literal が今も使われているか**を確かめる (= 参照する側の code を読む)。 使われていないなら
  消すだけでよく、 使われているなら「今どのマシンでも解決していない」 ことを確認してから置き換える
  (= 動いているものを壊さない。 実測では、 壊れていた方が普通だった)

**別 OS で書かれた成果物にも同じものが在る** — 検出側が 1 つの OS の表記しか見ていないと素通りする
([`docs/convention-design-principles.md#sweep-null-needs-per-form-control`](../docs/convention-design-principles.md#sweep-null-needs-per-form-control))。

公開層に上げてしまった物を**非公開へ戻す**ときは、 消すのでなく移す: ① 非公開 repo へ verbatim で写す (anchor id も同じに) →
② 公開側は一般則だけに書き直す (script なら結果を実装した関数を非公開の module へ、 汎用の道具は残す) → ③ 非公開側の呼び元
(shim・検査・文献台帳) を新しい置き場所へ付け替え、 検査を回す → ④ 公開側の転送表・索引から消えた anchor の行を削る。 履歴には残るので、
履歴を書き換えるかは owner の判断 (既定 = 書き換えない)。

<a id="cleanup-record-by-location"></a>**是正の記録は、 消した文言を書き写さずに所在で書く** (2026-09-14)。 結果表や漏洩の台帳を diff を読みながら埋めると、
消したはずの文言が記録の側に移り、 そこから commit message へ運ばれる。 [`scripts/commit-hunk-anchors.py`](../scripts/commit-hunk-anchors.py)
`<commit | A..B>` が hunk ごとに file・新しい側の行・直前の anchor (Markdown の `<a id>`、 Python は def/class) だけを出す
(本文も見出しの文字列も出さない。 `--summary` で file × 節ごとの件数)。 公開 2 repo の是正 92 行の表をこれで埋めた。

---

## 7. この規約を実装している script

| script | 役割 | 設定の home |
|---|---|---|
| [`check-confidential-leak.py`](../scripts/check-confidential-leak.py) | 指紋 + pattern で pre-commit BLOCK / 配線監査 (カナリア) | `~/.claude/leak-pattern-sources.txt` / `~/.claude/leak-candidate-dirs.txt` / 各機密 repo の `.leak-patterns` |
| [`check-pii-filenames.py`](../scripts/check-pii-filenames.py) | 追跡 file 名の識別子を検出 | `~/.claude/pii-filename-patterns.txt` |
| [`pack-pii-dirs.sh`](../scripts/pack-pii-dirs.sh) | 識別子入り dir を暗号化 tar に畳む / 畳み忘れ検出 | 各 repo の `.pii-pack-dirs` |
| [`check-gitcrypt-readable.py`](../scripts/check-gitcrypt-readable.py) | 暗号化 file がこのマシンで読めるか (全 repo) | `.gitattributes` の `filter=git-crypt` 宣言 |
| [`check-public-marker.py`](../scripts/check-public-marker.py) | 公開 repo の gate が入っているか: public なのに marker 無し / private なのに marker / marker があるのに hook 無し | GitHub の visibility (gh) と各 clone の marker・hook |
| [`check-unpublished-quote.py`](../scripts/check-unpublished-quote.py) | 未公開文書の逐語 (quoted span / prose run) を公開 repo の commit と message で BLOCK / 配線監査 (カナリア 2 本、 `--through-hooks` で実 hook) / 現在の tree の棚卸し (`--scan-tree`) | 個人層の `unpublished-sources.txt` (public runner が渡す) |
| [`check-activity-facts.py`](../scripts/check-activity-facts.py) | owner の非公開の活動の事実 (応募・採否・事務の指摘・推薦の時期と件数と固有名) を公開 repo の commit と message で見る: 固有語 = BLOCK / 出来事の語 × 日付・件数 = 警告 / `--scan-tree` = 承認済み一覧つきの棚卸し ([`CLAUDE.md#owner-activity-facts`](../CLAUDE.md#owner-activity-facts)) | 個人層の `activity-fact-terms.txt` と承認済み一覧 |
| [`scan-private-vocabulary.py`](../scripts/scan-private-vocabulary.py) | 公開 repo が非公開 repo と共有する珍しい語の一覧 (言い換えを読む候補、 gate ではない。 tree 全体 / `--staged` / `--diff`) | 無し (`.claude/public-repo.marker` の有無で公開・非公開を分ける、 `--source` / `--exclude` で絞る) |
| [`commit-hunk-anchors.py`](../scripts/commit-hunk-anchors.py) | commit の hunk の所在 (file・行・直前の anchor / def) だけを出す = 是正の記録を本文なしで書く | 無し |
| [`scan-public-tree.sh`](../scripts/scan-public-tree.sh) | 公開 repo の tree 全体を pre-commit gate の全 Tier に通す (= gate は差分しか見ないので、 gate より古い中身はこれでしか見つからない)。 `--all` で横断、 台帳で 1 repo 1 回 | 各 repo の `.claude/public-tree-accept.txt` (棚卸しでだけ効く受理一覧) |
| [`hooks/protected-dir-access-guard.py`](../hooks/protected-dir-access-guard.py) | 保護 dir へ Bash / Grep / Glob で触れうる操作の前に確認を出す (PreToolUse、 ask) / `--canary` で本番配線の実効性 ([§5 の節](#protected-dir-access-guard)) | `~/.claude/protected-dirs.txt` / `~/.claude/leak-pattern-sources.txt` |

いずれも **機密文字列も個人の配置も script 側に持たない**。 設定 file が無い環境では
「対象外」 として何もしない (= 他の利用者の環境を壊さない)。
