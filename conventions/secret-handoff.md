# secret-handoff: Secret をユーザーの clipboard 経由で安全に運ぶ手順

Token / API key / SSH 鍵 / 各種 credential を Claude がユーザーに `~/.secrets/<name>` 等のローカル配置先へ書き込ませる場面で、**chat に literal を貼らせない原則** (例: [`discord-bot.md` bot-token-handling](discord-bot.md#bot-token-handling)) と組み合わさったとき、ユーザーは secret を **clipboard 経由で** ブラウザ → ターミナルに運ぶことになる。このときに発生する再現性の高い罠と回避手順。

## The trap: clipboard は 1 個しかない

「ブラウザで secret コピー → Claude が出したコマンドを chat からコピー → ターミナルに貼って Enter」 という流れだと、**Claude のコマンドを clipboard にコピーした時点で secret は消えている**。特に `pbpaste > ~/.secrets/<name>` のように clipboard 内容そのものをファイルに書く方式は完全に破綻する — ファイルには **Claude が提示したコマンド文字列がそのまま書き込まれる**。

判定: ファイル長 ≈ 提示したコマンド長 になっていたら、ほぼ確実にこの罠を踏んでいる。`wc -c` の数字が secret の想定長 (例: Discord Bot Token なら 70-72) でなく、3 桁オーダーの中途半端な値 (160 前後等) になる。

この罠は構造的で、reflex で何度も再発する (2026-05-01、Discord Bot Token を `~/.secrets/<bot>-token` に運ぶ手順で Claude が同セッション内で 2 回連続して `pbpaste` 系を提示してしまい、ファイル内容は両方とも提示コマンド文字列そのものだった)。

## Fix: ターミナル側を先に「stdin 待ち」 状態にする

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

## 配置先と耐久性: handoff は「配置」 の半分でしかない

上記までは **handoff の作法** (= clipboard 競合を避けて secret をローカルに書き込む) を扱う。これは独立した第 2 の問いを残す: **その secret はこの 1 台が壊れても / 別マシンでも生き残るか (= cross-machine 耐久性)**。両者は別 concern で、handoff だけ済ませて耐久化を忘れる decouple が再発する。

### 罠: 「今動く配置」 ≠ 「耐久な配置」

`~/.secrets/<name>` への直書きは **その 1 台でしか有効でない揮発配置**。secret を複数マシンで使う (= ほぼ全ての bot token / API key) なら、**canonical は「private secrets repo に git-crypt 暗号化で commit したファイル」** であるべきで、各マシンの `~/.secrets/<name>` はそこへの **symlink** (= repo の setup が自動生成) にする。

decouple の失敗形: 「今動かす配置」 (= `~/.secrets` へ直書き) だけ実行し、「耐久化」 (= canonical へ commit) を別ステップとして doc に意図だけ書いて実行しない。**同一マシンの動作確認 (例: API の `GET /me` が通る) は揮発配置でも成功するため、作成したマシン上では耐久性の欠落が構造的に見えない** — 別マシンで読もうとして初めて露見する。これは「条件付き発火 mechanism の非活性は可視信号化せよ」 (= [`convention-design-principles.md §8.13`](../docs/convention-design-principles.md)) の secrets domain での現れ。

### 耐久な secret を作るときの順序 (= handoff の配置先を canonical にする)

1. **stdin-wait の配置先を canonical にする** — `cat > ~/.secrets/<name>` ではなく `cat > <secrets-repo>/secrets/<name>` (= git-crypt 暗号化対象 path) に handoff する。これで「配置」 と「耐久化」 が 1 動作になり、揮発場所への直書きが起きない。
2. **commit 前に leak gate** — staged blob が実際に暗号化されているか確認する (= git-crypt なら stored blob 先頭が `\0GITCRYPT\0` magic、 openssl `.enc` なら `Salted__`。平文のまま commit すると private repo でも GitHub 上に literal が乗る)。⚠️ **確認は magic の boolean 判定で行い、 先頭バイトを画面に印字しない**:
   ```bash
   git cat-file -p :<path> | head -c 9 | grep -qa GITCRYPT && echo encrypted || echo "PLAINTEXT — abort"
   ```
   `xxd` / `od` で先頭を**印字**すると、 もし暗号化が失敗して中身が平文だった場合 (= まさに検出したい失敗) その先頭バイト = secret の prefix を leak する。 boolean check なら平文でも何も出力されない。`encrypted` を確認してから push。
3. **commit + push** → 別マシンは pull + setup で `~/.secrets/<name>` symlink が自動生成。
4. **(任意) オフライン暗号化 backup** — repo 喪失時の最後の砦。ただし git-crypt 経路があれば自動復元は既に成立するので必須ではない。

### doc は「実状態」 を書く + 機械が現実を照合する

secret の保管 doc に「canonical / backup / 登録済」 と書く前に **それが実在するか** を確認する。未構築なら「未整備」 と明示マーカーを付ける (= 完成して見える表は gap を覆い隠し、後から読む者〔検証する自分自身を含む〕 が気づけない)。

ただし「正直にマーカーを付ける」 こと自体が reflex なので、最終的な backstop は **doc の自己申告でなく現実を見る機械 audit** — 各マシンの `~/.secrets/*` を走査して「symlink→canonical (耐久) / 平文+暗号化 backup あり (復元可) / どちらも無い (= 単一マシン地雷)」 に分類し、地雷を継続的に surface する。⚠️ その audit は backup の所在を **doc から読んで複数経路を照合** すること (= backup は単一 dir に限らない〔共有鍵 / 個人鍵 / 別鍵流用〕。単一 dir を仮定して不在を断定すると偽陽性を量産する)。

## Anti-pattern (使ってはいけない)

```bash
pbpaste > ~/.secrets/<name>             # 罠: Claude のこの行をコピーした瞬間に secret が消える
echo "$(pbpaste)" > ~/.secrets/<name>   # 同上
some_cmd "$(pbpaste)"                   # 同上、clipboard を読む全コマンドが該当
```

`pbpaste` (macOS) / `xclip -o` / `wl-paste` (Linux) を **secret 取り込みに使う案を Claude が出した時点で誤り**。Claude のコマンド文字列で clipboard が確実に上書きされている。

## Claude への指示 (How to apply)

Secret を `~/.secrets/<name>` 系に運ぶ手順を提示する時は **必ず stdin-wait 先行 pattern** を使う:

1. 最初に `cat > file` または `read -rs ... < /dev/tty ...` を提示 (= ターミナルを入力待ちに)
2. その上で「ブラウザで secret コピー → Cmd+V → Enter → Ctrl+D」 の順序を文章で明示
3. 検証 (`wc -c`) と permission (`chmod 600`) は **必ず別ブロック**で並べる
4. `pbpaste` を使うコマンド案が頭をよぎったら、それは clipboard 競合の罠 — 即破棄

## なぜ繰り返すのか (構造的バイアス)

「ユーザーが secret を clipboard で運ぶ」 と「Claude がコマンドを clipboard 経由で提示する」 を独立に扱ってしまう reflex。両者が同じ clipboard を競合する事実が見えない。`pbpaste > file` の **見た目の単純さ** が、その内側で `pbpaste` が実行される時点では clipboard が既に汚染されている事実を覆い隠す。

検出経路: 「ユーザーに『これをコピペして実行して』 と提案するコマンドが、その実行結果として clipboard 内容に依存する」 → 矛盾、即破綻。提案前にこの 1 行を自問する。

## 関連

- [`discord-bot.md` bot-token-handling](discord-bot.md#bot-token-handling) — Token を chat に貼らせない原則 (本ファイルの前提条件)
- `~/Claude/CONVENTIONS.md §5「安全規則」` — secret 全般の git/ chat への流出禁止

## Secret file の binary inspection 禁止

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

## Claude への規律 (secret 取扱の根本)

「secret file の内容を chat に流す可能性のある操作」 を見たら、 まず **「partial でも leak の手がかりになるか?」** を自問する。 partial leak でも:
- token 全体の同定性 (= どの token かが特定できる)
- format 確認 (= 末尾文字パターンから token type 推測)
- collision search の範囲縮小

の手がかりになる。 partial = 安全という reflex は誤り。

これは「安価な操作で expensive な操作を bypass する」 trait family の secret 取扱 domain での現れ。 `xxd` は「token 確認」 という目的に対して **安価すぎる手段** で、 「partial だから OK」 という illusion で leak risk を覆い隠す。
