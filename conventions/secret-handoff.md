<!-- doc-meta
when: secret を user から受け取る・別マシンへ運ぶとき + **token を rotate するとき** (= 分業と主体照合、 #rotation-labor-split) + **暗号化 backup を作る/パスフレーズを失ったとき** (#backup-round-trip / #passphrase-loss-is-recoverable)
category: infra
summary: Secret を clipboard 経由で安全に運ぶ手順 (chat に literal を貼らせない原則と clipboard 1 個競合の回避、 配置先と cross-machine 耐久性、 mode 衛生 〔cp -p / git / open() は 0600 を運ばず dir 755 も露出面 = 生成側で冪等矯正、 #mode-hygiene〕、 shell rc に複製しない 〔perm 644 + 全 audit の射程外 + os.environ 優先で正本を上書きし rotate が silent に効かなくなる、 #no-shell-rc-copies〕、 backup は往復検証してから差し替える 〔#backup-round-trip〕、 パスフレーズ喪失は平文が 1 台に残っていれば全件再暗号化で復旧 〔#passphrase-loss-is-recoverable〕、 rotate の分業 = 人間は再発行のみ・残りは script で値を AI context に載せない + 主体照合必須 〔#rotation-labor-split〕)
-->
# secret-handoff: Secret をユーザーの clipboard 経由で安全に運ぶ手順

Token / API key / SSH 鍵 / 各種 credential を Claude がユーザーに `~/.secrets/<name>` 等のローカル配置先へ書き込ませる場面で、**chat に literal を貼らせない原則** (例: [`discord-bot.md` bot-token-handling](discord-bot.md#bot-token-handling)) と組み合わさったとき、ユーザーは secret を **clipboard 経由で** ブラウザ → ターミナルに運ぶことになる。このときに発生する再現性の高い罠と回避手順。

## <a id="clipboard-single-resource"></a>The trap: clipboard は 1 個しかない

「ブラウザで secret コピー → Claude が出したコマンドを chat からコピー → ターミナルに貼って Enter」 という流れだと、**Claude のコマンドを clipboard にコピーした時点で secret は消えている**。特に `pbpaste > ~/.secrets/<name>` のように clipboard 内容そのものをファイルに書く方式は完全に破綻する — ファイルには **Claude が提示したコマンド文字列がそのまま書き込まれる**。

判定: ファイル長 ≈ 提示したコマンド長 になっていたら、ほぼ確実にこの罠を踏んでいる。`wc -c` の数字が secret の想定長 (例: Discord Bot Token なら 70-72) でなく、3 桁オーダーの中途半端な値 (160 前後等) になる。

この罠は構造的で、reflex で何度も再発する (2026-05-01、Discord Bot Token を `~/.secrets/<bot>-token` に運ぶ手順で Claude が同セッション内で 2 回連続して `pbpaste` 系を提示してしまい、ファイル内容は両方とも提示コマンド文字列そのものだった)。

## <a id="terminal-stdin-first"></a>Fix: ターミナル側を先に「stdin 待ち」 状態にする

正しい順序は **「先にターミナルでコマンド受付状態を作る → ブラウザに切り替えて secret コピー → ターミナルに戻って Cmd+V」**。これなら clipboard は 1 回だけ secret 専用に使われ、競合しない。

⚠️ **配置先の注意**: 以下のパターンは例として `~/.secrets/<name>` を使うが、これは clipboard 作法を示すためのもの。**複数マシンで使う secret (= ほぼ全ての token / key) は揮発する `~/.secrets/<name>` でなく canonical (`<secrets-repo>/secrets/<name>`) に handoff する** — 配置先の判断は後述 §配置先と耐久性 を必ず読むこと (= ここで `~/.secrets` に直書きしたまま耐久化を忘れるのが再発する decouple)。

### パターン A: `cat > file` (シンプル、画面 echo 許容)

```bash
cat > ~/.secrets/<name>
```

→ Enter で stdin 待ちになる (プロンプトが返らないのが正しい状態)。ブラウザに切替えて secret コピー → ターミナルに戻り Cmd+V → Enter (paste の改行) → Ctrl+D で確定。

副作用: paste 時に secret が **画面に echo される** (1 行表示)。物理画面に他人が見えない前提なら許容、共用作業環境では下のパターン B を使う。

### パターン B: `read -rs` (画面に echo されない)

```bash
read -rs SECRET < /dev/tty && printf '%s' "$SECRET" > ~/.secrets/<name> && unset SECRET
```

→ 1 行で stdin 待ちになり、Cmd+V → Enter で完了 (Ctrl+D 不要)。secret は画面に出ない。`unset SECRET` で shell 変数からも消す。

`-r` は backslash escape 無効化、`-s` は echo 抑制。`printf '%s'` は末尾改行を入れないので、`tr -d` 系の trim を後から呼ばなくて済む (curl の `Authorization` header に直接渡せる)。

### permission

書き込み直後に `chmod 600`:

```bash
chmod 600 ~/.secrets/<name>
```

ディレクトリは事前に `mkdir -p ~/.secrets && chmod 700 ~/.secrets`。作成→ chmod の race は single-user macOS の `~/.secrets/` (700) 配下では実害ないが、過敏な環境では `(umask 077; cat > ~/.secrets/<name>)` で atomic にできる。

### 検証は別ブロックで

```bash
wc -c ~/.secrets/<name>
```

これは **必ず別ブロックで提示する**。書き込みコマンドと `&&` で連結すると、ユーザーがその 1 行を clipboard コピーした時点で secret が消える同じ罠を踏ませる。

## <a id="placement-and-durability"></a>配置先と耐久性: handoff は「配置」 の半分でしかない

上記までは **handoff の作法** (= clipboard 競合を避けて secret をローカルに書き込む) を扱う。これは独立した第 2 の問いを残す: **その secret はこの 1 台が壊れても / 別マシンでも生き残るか (= cross-machine 耐久性)**。両者は別 concern で、handoff だけ済ませて耐久化を忘れる decouple が再発する。

### 罠: 「今動く配置」 ≠ 「耐久な配置」

`~/.secrets/<name>` への直書きは **その 1 台でしか有効でない揮発配置**。secret を複数マシンで使う (= ほぼ全ての bot token / API key) なら、**canonical は「private secrets repo に git-crypt 暗号化で commit したファイル」** であるべきで、各マシンの `~/.secrets/<name>` はそこへの **symlink** (= repo の setup が自動生成) にする。

decouple の失敗形: 「今動かす配置」 (= `~/.secrets` へ直書き) だけ実行し、「耐久化」 (= canonical へ commit) を別ステップとして doc に意図だけ書いて実行しない。**同一マシンの動作確認 (例: API の `GET /me` が通る) は揮発配置でも成功するため、作成したマシン上では耐久性の欠落が構造的に見えない** — 別マシンで読もうとして初めて露見する。これは「条件付き発火 mechanism の非活性は可視信号化せよ」 (= [`convention-design-principles.md §8.13`](../docs/convention-design-principles.md#conditional-firing-visibility)) の secrets domain での現れ。

### 耐久な secret を作るときの順序 (= handoff の配置先を canonical にする)

1. **stdin-wait の配置先を canonical にする** — `cat > ~/.secrets/<name>` ではなく `cat > <secrets-repo>/secrets/<name>` (= git-crypt 暗号化対象 path) に handoff する。これで「配置」 と「耐久化」 が 1 動作になり、揮発場所への直書きが起きない。
2. **commit 前に leak gate** — staged blob が実際に暗号化されているか確認する (= git-crypt なら stored blob 先頭が `\0GITCRYPT\0` magic、 openssl `.enc` なら `Salted__`。平文のまま commit すると private repo でも GitHub 上に literal が乗る)。⚠️ **確認は magic の boolean 判定で行い、 先頭バイトを画面に印字しない**:
   ```bash
   git cat-file -p :<path> | head -c 9 | grep -qa GITCRYPT && echo encrypted || echo "PLAINTEXT — abort"
   ```
   `xxd` / `od` で先頭を**印字**すると、 もし暗号化が失敗して中身が平文だった場合 (= まさに検出したい失敗) その先頭バイト = secret の prefix を leak する。 boolean check なら平文でも何も出力されない。`encrypted` を確認してから push。
3. **commit + push** → 別マシンは pull + setup で `~/.secrets/<name>` symlink が自動生成。
4. **(任意) オフライン暗号化 backup** — repo 喪失時の最後の砦。ただし git-crypt 経路があれば自動復元は既に成立するので必須ではない。

### <a id="mode-hygiene"></a>耐久化の副作用: copy と VCS は mode を運ばない

canonical / symlink 化で耐久性を満たしても、**file mode は別に落ちる**。3 つの実測パターン:

1. **`cp -p` は旧 mode を保存する** — 「backup を取ってから置換」 の rotation は、置換前 file が緩い mode だとその緩さごと backup に転写する。secret の backup は **必ず明示 `chmod 600`** を置換直後に打つ (`cp -p` に任せない)。実例: OAuth client secret を含む backup が 0644 のまま数週間残っていた (2026-08-18)。
2. **git は mode を保存しない (実行ビット以外)** — git-crypt canonical を pull した直後の mode は umask 依存。canonical を使う側の setup script が **毎回 `chmod 600` で矯正**する (冪等な自己修復にする、初回だけ直す設計にしない)。
3. **`open(path,'w')` は umask 依存の窓を作る** — 新規 secret file は「644 で生まれてから chmod 600」 の一瞬がある。`os.open(path, O_WRONLY|O_CREAT|O_TRUNC, 0o600)` で **born-0600** にする。

+ **dir も対象**: secret 置き場の dir が 755 だと、同一マシンの別 local user が **list できる** (= file 名から alias / account 構成が読める) し、緩い mode の file があれば読める。secret dir は 700 に矯正する (`$HOME` 自体が group-traversable な OS 構成がありうる — home が守ってくれる前提を置かない)。

⚠️ **どれも「動作確認」 では検出できない** (= 自分が読める限りテストは通る)。前節の機械 audit に **mode 検査を含める**か、生成する側の script に冪等な矯正を焼き込むのが唯一の防御。

### doc は「実状態」 を書く + 機械が現実を照合する

secret の保管 doc に「canonical / backup / 登録済」 と書く前に **それが実在するか** を確認する。未構築なら「未整備」 と明示マーカーを付ける (= 完成して見える表は gap を覆い隠し、後から読む者〔検証する自分自身を含む〕 が気づけない)。

ただし「正直にマーカーを付ける」 こと自体が reflex なので、最終的な backstop は **doc の自己申告でなく現実を見る機械 audit** — 各マシンの `~/.secrets/*` を走査して「symlink→canonical (耐久) / 平文+暗号化 backup あり (復元可) / どちらも無い (= 単一マシン地雷)」 に分類し、地雷を継続的に surface する。⚠️ その audit は backup の所在を **doc から読んで複数経路を照合** すること (= backup は単一 dir に限らない〔共有鍵 / 個人鍵 / 別鍵流用〕。単一 dir を仮定して不在を断定すると偽陽性を量産する)。

## <a id="anti-pattern"></a>Anti-pattern (使ってはいけない)

```bash
pbpaste > ~/.secrets/<name>             # 罠: Claude のこの行をコピーした瞬間に secret が消える
echo "$(pbpaste)" > ~/.secrets/<name>   # 同上
some_cmd "$(pbpaste)"                   # 同上、clipboard を読む全コマンドが該当
```

`pbpaste` (macOS) / `xclip -o` / `wl-paste` (Linux) を **secret 取り込みに使う案を Claude が出した時点で誤り**。Claude のコマンド文字列で clipboard が確実に上書きされている。

## <a id="how-to-apply"></a>Claude への指示 (How to apply)

Secret を `~/.secrets/<name>` 系に運ぶ手順を提示する時は **必ず stdin-wait 先行 pattern** を使う:

1. 最初に `cat > file` または `read -rs ... < /dev/tty ...` を提示 (= ターミナルを入力待ちに)
2. その上で「ブラウザで secret コピー → Cmd+V → Enter → Ctrl+D」 の順序を文章で明示
3. 検証 (`wc -c`) と permission (`chmod 600`) は **必ず別ブロック**で並べる
4. `pbpaste` を使うコマンド案が頭をよぎったら、それは clipboard 競合の罠 — 即破棄

## <a id="why-recurs"></a>なぜ繰り返すのか (構造的バイアス)

「ユーザーが secret を clipboard で運ぶ」 と「Claude がコマンドを clipboard 経由で提示する」 を独立に扱ってしまう reflex。両者が同じ clipboard を競合する事実が見えない。`pbpaste > file` の **見た目の単純さ** が、その内側で `pbpaste` が実行される時点では clipboard が既に汚染されている事実を覆い隠す。

検出経路: 「ユーザーに『これをコピペして実行して』 と提案するコマンドが、その実行結果として clipboard 内容に依存する」 → 矛盾、即破綻。提案前にこの 1 行を自問する。

## 関連

- [`discord-bot.md` bot-token-handling](discord-bot.md#bot-token-handling) — Token を chat に貼らせない原則 (本ファイルの前提条件)
- `~/Claude/CONVENTIONS.md §5「安全規則」` — secret 全般の git/ chat への流出禁止

## <a id="no-binary-inspection"></a>Secret file の binary inspection 禁止

⚠️ **secret file (`~/.secrets/*`、 `gcp-oauth.keys.json`、 `.env` 等) に対して `xxd` / `od` / `hexdump` 等の binary inspection コマンドを実行しない。**

これらは secret の **部分文字列を chat 出力に流す** リスクがある。 たとえ partial 表示 (= 末尾 8 文字等) でも、 token / Bot Token / API key の **同定性** や **brute-force 範囲縮小** の手がかりになり、 secret rotate が要求される。

代わりに:
- 存在確認: `ls -la <file>` で permissions / size
- format check: `head -c 4 <file>` で prefix のみ (= `olp_` / `GOCSPX-` 等 known prefix の有無)
- byte count: `wc -c <file>`
- 改行有無の検証: `tr -d '\n' < <file> | wc -c` (= 末尾改行込み vs 込まずの diff)

**禁止例**:
- `xxd ~/.secrets/overleaf-token` (= 全文出力)
- `xxd ~/.secrets/overleaf-token | tail -1` (= 末尾出力、 これでも token の一部が leak、 同定性高)
- `od -c ~/.secrets/discord-bot-token` (= 全文出力)
- 任意の binary inspector を「token format 確認」 を名目に実行

**実例 (= 2026-05-19 (該当 private paper repo) session で発生)**:
- Overleaf token (= `~/.secrets/overleaf-token`) を `xxd ~/.secrets/overleaf-token | tail -1` で format 確認した結果、 末尾 8 文字 (= 40 char token の 20%) が chat 出力に流出
- 直接的 impact は限定的 (= 8/40 文字で brute-force 範囲縮小は微小、 user の判断で rotate 不要となった) だが、 user に rotate 推奨を伝える必要が発生、 paper 作業の流れを中断
- もし「`xxd` で確認したい」 という reflex が起こったら、 `wc -c` + `head -c 4` + `tr -d '\n' | wc -c` の 3 段で代替

### 例外: 暗号文 (ciphertext) の format magic 確認は可 — ただし boolean で

secret を git-crypt / openssl で **暗号化したことの確認** (= leak gate、 §配置先と耐久性 step 2) は、 暗号文の先頭 magic (`\0GITCRYPT\0` / `Salted__`) を見る操作で、 これは secret 本体ではなく「暗号化されているか」 の判定。 これは可。

⚠️ ただし **`grep -qa` / `cmp` の boolean で判定し、 `xxd` / `od` で印字しない**: もし暗号化が失敗して中身が平文だった場合 (= leak gate がまさに検出したい状態)、 先頭を印字すると平文 secret の prefix が leak する (= 上の 2026-05-19 と同型を、 暗号化検証の名目で踏む)。 boolean check (`… | head -c 9 | grep -qa GITCRYPT`) なら平文でも何も出力されない。 = 「暗号文の magic 確認」 と「平文 secret の inspection」 は別だが、 失敗時に後者へ化けるので boolean に固定する。

## <a id="secret-handling-discipline"></a>Claude への規律 (secret 取扱の根本)

「secret file の内容を chat に流す可能性のある操作」 を見たら、 まず **「partial でも leak の手がかりになるか?」** を自問する。 partial leak でも:
- token 全体の同定性 (= どの token かが特定できる)
- format 確認 (= 末尾文字パターンから token type 推測)
- collision search の範囲縮小

の手がかりになる。 partial = 安全という reflex は誤り。

これは「安価な操作で expensive な操作を bypass する」 trait family の secret 取扱 domain での現れ。 `xxd` は「token 確認」 という目的に対して **安価すぎる手段** で、 「partial だから OK」 という illusion で leak risk を覆い隠す。

## <a id="no-shell-rc-copies"></a>secret を shell rc に複製しない

`~/.zshrc` / `~/.zshenv` / `~/.zprofile` に `export SECRET=...` を置くと、 正本が別にあっても
3 つの理由で壊れる。 3 つ目が最も見えにくい:

1. **perm が弱い** — rc file の既定は 644 (world-readable)。 secret 置き場の 600 より緩い
2. **どの網にも掛からない** — gitignore・暗号化 backup・`~/.secrets` を走査する durability
   audit のいずれの射程にも入らない (= 「安全」 と報告されている間に平文が別の場所で腐る)
3. 🔴 **正本を上書きして rotate が silent に効かなくなる** — `.env` loader の多くは
   「`os.environ` に**無い** key だけ埋める」 実装なので、 shell の export が**勝つ**。
   ∴ 正本を rotate しても、 対話 shell から走らせる限り古い値が使われ続ける
   (= 「rotate したのに直らない」 の典型原因。 しかも成功したように見える)

**点検** (値を出さず件数のみ、 各マシンで。 期待 = すべて 0):

```sh
grep -c -E '^export [A-Z_]*(TOKEN|SECRET|KEY|PASSWORD)=' ~/.zshrc ~/.zshenv ~/.zprofile
```

実例 (2026-09-09): 5 ヶ月間 rc file に平文 token が置かれ、 正本の `.env` を上書きしていた。
発見は無関係な作業 (rc file の別行を編集) の副産物 = **専用の検出器はどれも見ていなかった**。

## <a id="backup-round-trip"></a>暗号化 backup は「往復検証」 してから差し替える

`openssl enc` で backup を作ったら、 **その場で復号し直して元と byte 一致するか確かめてから**
既存 backup を置き換える。 一致しなければ新 backup を破棄して古い方を残す。

理由: backup の失敗は**次に必要になる日まで発覚しない** (= 平時は誰も復号しない)。
「作った」 と「開ける」 は別の主張で、 前者だけ確認して後者を確認しない運用は、
**開けない backup を安全だと信じて持ち続ける**状態を生む。

## <a id="passphrase-loss-is-recoverable"></a>パスフレーズを忘れても、平文が手元にあれば詰みではない

パスフレーズで暗号化した backup 群のパスフレーズを失っても、 **平文の実体がどれか 1 台に
残っていれば、 新しいパスフレーズで全部作り直せる** (= 思い出す必要はない)。 復旧手順:

1. 全 backup の「平文 source → `.enc` target」 の対応表を作る (= 既存の restore script が
   あればその登録簿が正本)
2. 新パスフレーズを 1 回だけ不可視入力し、 全件を再暗号化 (+ 上記の往復検証)
3. **backup が 1 つも無かった secret をこの機会に洗い出して同時に追加する**
   (= 棚卸しの好機。 durability audit の 🔴 がそのまま作業リストになる)
4. 新パスフレーズの保管先を記録する — ⚠️ **値でなく場所だけ**を、 secret 置き場の doc に

⚠️ **保管先は「その機械が壊れたとき」 に読めるか**で選ぶ。 このパスフレーズが要るのは
まさに機械を失ったときなので、 **その機械の中だけに置くと必ず間に合わない**
(= CLI で OS の keychain に入れる方式は同期しないことがある。 同期する保管先 + 紙 の
2 系統が堅い)。

## <a id="rotation-labor-split"></a>token rotate の分業 — 人間は「再発行」 だけ、 残りは script

多くの token rotate は次の leg に分解できる:

| leg | 誰がやるか |
|---|---|
| service にログインして再発行ボタンを押す | **人間のみ** (= 認証・アカウント設定変更) |
| 新 token の有効性と**主体**の検証 (API) | 機械 |
| 正本 (`.env` 等) の atomic 置換 + mode 矯正 | 機械 |
| 暗号化 backup の再作成 | 機械 |
| CI/Actions の secret 更新 | 機械 |
| 旧 token の失効確認 | 機械 |

→ **「認証が要るから全部人間」 と丸めない** (= 機械にできる 8 割まで押し付けることになる)。
逆に AI が新 token を手で扱うと、 **値が AI の context と transcript に載る**。
∴ 最適解は「人間が再発行 → script が不可視入力 (`read -rs`) で受けて残り全部」 で、
これは**手作業より漏れる面が少ない** (= [machine-route-first.md](machine-route-first.md#route-ladder)
「経路を先に作る」 の instantiation)。

⚠️ script 側に **投稿主体 / 所有者の照合**を必ず入れる (= 別アカウントで発行した token を
気づかず投入すると、 認証は通るのに**別名義で動く**。 API の `verify_credentials` 相当で
期待する主体と一致しなければ書き込み前に中止する)。
