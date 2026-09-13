<!-- doc-meta
when: 機密を持つ repo と remote を持つ repo の境界を機械で守るとき — 暗号化を入れる前 (#2) / file 名に識別子が出ていると気づいたとき (#1) / 別 process への通知に要約を書こうとしたとき (#3) / 流出検査を設計するとき (#4) / fail-open な gate を足したとき (#5) / 公開 repo に未公開文書の文が入らない gate を設計・調整するとき (#unpublished-text-public-gate)
category: infra
summary: 暗号化は中身しか守らない (file 名・commit message・path は平文) ので識別子入り dir は暗号化 tar に畳む (連番+対応表は対応表が単一障害点で不可)、 保存しない > 暗号化する (通知に payload を載せず schema で縛る、 死んだ複製は削除)、 逐語の指紋照合は写しを捕まえるが言い換えは原理的に不可なので経路ごとに制御を変える (閾値は全件集計で決める = 誤検知 6800→24→0 の実測)、 fail-open な gate は必ずカナリアで実効性を毎回確かめ ARMED/NOT ARMED/対象外 の 3 状態を出す (沈黙を作らない)、 是正は go-forward にしか効かず履歴は別問題として人間の判断に委ねる、 公開 repo には未公開文書の逐語 gate を別に置く (漏れる例示は引用符に入った短い断片なので quoted span が主、 全履歴 replay で誤検出 0 を確かめて採用)、 gate が target の pre-commit で実際に走っているかは target ごとに確かめる
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

## 3. 通知は報告書ではない

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
  `ARMED` / `NOT ARMED` (理由つき、 FAIL) / `対象外` (= 守るべきものがこのマシンに無い)

⚠️ **カナリアの値を engine 側に literal で書かない** — 書くと engine 自身の commit が自分の
gate に弾かれる。 値の home は設定 file だけにし、 engine は directive 名だけを持つ。

同じ理由で、 **暗号化を入れたら「このマシンで実際に読めるか」 の検査も必ず付ける**
([`scripts/check-gitcrypt-readable.py`](../scripts/check-gitcrypt-readable.py))。
ロックされたマシンでは暗号文がそのまま読め、 fail-open な呼び出し側は **黙って 0 件**を返す。
「1 件も無い」 と「読めていない」 が区別できなくなるのが最悪の壊れ方。
鍵を持たない環境 (CI 等) は **SKIP を宣言して緑にしない**。

---

## 6. 過去の分は別問題として扱う

ここまでの操作はすべて **go-forward** にしか効かない。 既に commit / push されたものは
履歴に残る。 是正のたびに次を明示する:

- **今回の操作で止まるもの** (= 今後の書き込み)
- **止まらないもの** (= 履歴、 既に配られた copy、 別 session の transcript)
- 履歴の書き換えを行うかは、 clone を壊す不可逆操作なので **必ず人間の判断**に委ねる

既存の記録を新しい基準で棚卸しする口を用意しておくと、 基準を変えた時に遡れる
(= 「後から機密と分かったもの」 を中立化する操作も含めて)。

---

## 7. この規約を実装している script

| script | 役割 | 設定の home |
|---|---|---|
| [`check-confidential-leak.py`](../scripts/check-confidential-leak.py) | 指紋 + pattern で pre-commit BLOCK / 配線監査 (カナリア) | `~/.claude/leak-pattern-sources.txt` / `~/.claude/leak-candidate-dirs.txt` / 各機密 repo の `.leak-patterns` |
| [`check-pii-filenames.py`](../scripts/check-pii-filenames.py) | 追跡 file 名の識別子を検出 | `~/.claude/pii-filename-patterns.txt` |
| [`pack-pii-dirs.sh`](../scripts/pack-pii-dirs.sh) | 識別子入り dir を暗号化 tar に畳む / 畳み忘れ検出 | 各 repo の `.pii-pack-dirs` |
| [`check-gitcrypt-readable.py`](../scripts/check-gitcrypt-readable.py) | 暗号化 file がこのマシンで読めるか (全 repo) | `.gitattributes` の `filter=git-crypt` 宣言 |
| [`check-public-marker.py`](../scripts/check-public-marker.py) | 公開 repo の gate が入っているか: public なのに marker 無し / private なのに marker / marker があるのに hook 無し | GitHub の visibility (gh) と各 clone の marker・hook |
| [`check-unpublished-quote.py`](../scripts/check-unpublished-quote.py) | 未公開文書の逐語 (quoted span / prose run) を公開 repo の commit と message で BLOCK / 配線監査 (カナリア 2 本) | 個人層の `unpublished-sources.txt` (public runner が渡す) |

いずれも **機密文字列も個人の配置も script 側に持たない**。 設定 file が無い環境では
「対象外」 として何もしない (= 他の利用者の環境を壊さない)。
