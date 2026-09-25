<!-- doc-meta
when: Gmail でメールを送信する経路・MIME 実装を選ぶとき
category: mail
summary: Gmail 送信の経路選択と MIME 落とし穴 (= 返信は RFC 5322 Message-ID が要り MCP read では取れない → API 直送 script + 親 id 1 個で 3 点 set 自動解決を推奨 / 非 ASCII 添付 filename は RFC 2231 kwarg 必須〔f-string 直書きは noname 化〕 / 添付付き送信は送信後 MIME 検証まで 1 単位 / dry-run 先頭 truncate 罠 / Bash sandbox の network 遮断 / 承認 gate は script 名でなく実送信 flag に anchor〔fail-safe 既定 + ask パターン誤爆防止〕 / #double-confirmation-design = chat 承認〔規律層 = 内容〕と harness chip〔backstop = 未承認送信〕は別の脅威モデル — chip の品質 3 条件〔実行形 anchor・1 送信 1 個・dialog = 内容〕、 うざい chip の治療は廃止でなく anchor 絞り、 宣言配線は silent 消失しうる = 登録直後 verify + documented ⊆ live の機械 audit、 並走 gate 層〔宣言 ask・hook・fail-safe〕は同じ実送信-flag anchor を共有〔片層だけ script 名 match だと dry-run に誤爆 chip / argparse prefix 短縮は allow_abbrev=False で殺す〕 / #draft-approval-single-source = chat 提示 draft と送信 body-file の 2 度書きは乖離源 — body-file 先行 Write + chat は view、 承認後の変更は再提示、 全外部発信に適用 / #quote-chain = 複数 message を新規メールに引用するときは新しい順の入れ子を header から組み、 最初の 1 通まで含め、 抜粋を原文と照合)
-->
# Gmail 送信の経路選択と MIME 落とし穴

Gmail でメールを 1 通送る作業が「経路探し → threading 用 header 探し → 送信 → 添付 filename 壊れ → 再送」という数十分の探索に化ける事故 (2026-07-03 実例) の再発防止 SoT。**送信前にこの file を読めば、探索なしで正しい 1 コマンドに到達できる**ことが目標 (= 能力の低い model でも同じ道を通れる)。

原則: **知識を prose で運ぶより、送信 script 側に落とし穴の回避を焼き込む** (= §2/§4 の自動化を自分の send script に実装する)。本 doc は「なぜそうなっているか」と「script が無い環境で手で組むときの正解」を持つ。

## <a id="route-map"></a>1. 経路選択 map (送信タスクの最初にここで分岐)

| 状況 | 経路 |
|---|---|
| 新規メール ∧ session に `mcp__gmail-<alias>__send_email` が wire 済 | MCP `send_email` (最短) |
| **返信 (= 既存 thread への reply)** | **Gmail API 直送 script** (§2)。MCP send_email は使わない |
| MCP send tool が session に無い (= desktop / bridge surface) | Gmail API 直送 script |

**返信で MCP send_email を使わない理由**: 正しい threading には RFC 5322 の `In-Reply-To` / `References` header (= `<一意トークン@送信元ドメイン>` 形式の Message-ID) が要るが、MCP の read 系 tool は **Gmail 内部 id (16 進) しか返さず RFC 5322 Message-ID を取得できない**。`inReplyTo` を空・内部 id で送ると受信側で thread が割れる (実事故 2026-07-01)。schema 上 `inReplyTo` を受けるからといって「MCP 単独 read → reply」は成立しない。

## <a id="reply-threading"></a>2. 返信の 3 点 set (In-Reply-To / References / threadId)

返信 mail に必要なもの:

1. **In-Reply-To** = 親 message の RFC 5322 Message-ID
2. **References** = 親の References + 親の Message-ID (空白区切りで連結)
3. **threadId** = Gmail 内部の thread id (= `messages.send` の body に渡すと Gmail 側の thread 表示が確実になる)

1 と 2 の取得は Gmail API の metadata fetch 1 回:

```python
meta = svc.users().messages().get(
    userId="me", id=<gmail内部id>, format="metadata",
    metadataHeaders=["Message-ID", "References", "Subject"]).execute()
# meta["payload"]["headers"] に Message-ID / References、meta["threadId"] に thread id
```

**推奨 (= 平滑化の本体)**: 送信 script に「親 message の Gmail 内部 id を 1 個渡すと 3 点 set + `Re:` 付き Subject を自動解決する」option を実装する (実装例: `--reply-to-message <gmail-id>`)。model が header を手で組み立てる工程そのものを消すのが最も確実。

<a id="reply-newer-in-thread"></a>**返信先より新しい相手の message を送信前に数える**: threading が正しくても、 返信先を決めた後に相手が同じ thread で返事をしていれば、 それを読まない続報 (答え済みの質問の聞き直し) になる (実測)。 返信 option は thread を取り、 返信先より新しく送信アカウント以外からの message を dry-run の先頭に出して実送信を止める。 通す flag には最新の相手 message の id を取らせる (= 読んだ証拠。 後から届けば id が変わり再び止まる)。 自分の判定は From だけでなく SENT label と Message-ID でも行う (ML が配り直した自分の投稿は From が ML 名義になる)。
判定と表示の実装は [`scripts/lib/newer_in_thread.py`](../scripts/lib/newer_in_thread.py) の 1 か所 (selftest + [mutants](../scripts/newer_in_thread.mutants.json))。 返信する CLI は thread を読んで row をこの engine に渡し、 文言・flag 名・exit code は templates と extra で差し替える (例 = [`reviewed_mail.py`](../scripts/reviewed_mail.py) の `check_newer`)。 新しい返信経路を作るときも判定を書き直さずにこれを呼ぶ。

## <a id="rfc2231-attachment-filename"></a>3. 非 ASCII 添付 filename は RFC 2231 (最重要の壊れ方)

Python email lib で header 値全体を f-string で渡すと壊れる:

```python
# ✗ 非 ASCII filename で header 値全体が quote され、受信側 parser が filename を認識できない
part.add_header("Content-Disposition", f'attachment; filename="{name}"')
# → Content-Disposition: "attachment; filename=\"...\""  (値全体が 1 個の quoted string)
# → Gmail API では filename: '' = 受信側で「noname」添付になる
```

正しくは kwarg 渡し (= email lib が RFC 2231 encode する) + MIME type 推定:

```python
ctype, _ = mimetypes.guess_type(p.name)
main, sub = (ctype or "application/octet-stream").split("/", 1)
part = MIMEBase(main, sub)
part.set_payload(p.read_bytes())
encoders.encode_base64(part)
part.add_header("Content-Disposition", "attachment", filename=p.name)  # kwarg → RFC 2231
part.set_param("name", p.name)  # Content-Type 側にも name= (Gmail 互換)
```

ASCII filename では両方動くため、**このバグはテストで見つからず本番の非 ASCII 名で初めて発火する**。発覚事例 (2026-07-03): ファイル名規定のある公式提出書類 2 点が noname で届く送信をしてしまい、送信後検証 (§4) で捕捉して同 thread に正名版を再送した。

## <a id="post-send-mime-verify"></a>4. 添付付き送信は「送信後 MIME 検証」までが 1 単位

添付付き mail を送ったら、**送信済み message を `messages.get(format="full")` で読み直し、parts の `filename` / `mimeType` が期待値であることを確認してから完了を宣言する**。§3 の壊れ方は送信 API が成功を返すので、検証しない限り気づけない。

```python
full = svc.users().messages().get(userId="me", id=sent_id, format="full").execute()
for p in full["payload"].get("parts", []):
    print(p.get("mimeType"), p.get("filename"))   # filename が '' なら noname 化している
```

これも送信 script の送信後処理に焼き込むのが正解 (= 手順書でなく機械が検証する)。

## <a id="dry-run-truncation"></a>5. dry-run 表示の truncation に注意

dry-run が `msg.as_string()[:N]` のような先頭 truncate だと、base64 本文の後ろにある**添付 part の header が表示されず**、「添付が入っていない」ようにしか見えない。truncate された MIME dump から「無い」を結論しない (= 不在主張は表示仕様を確認してから)。dry-run 実装は「header 全部 + part 構造 + 本文 decode」の構造表示にする。

## <a id="sandbox-network"></a>6. Claude Code の Bash sandbox は network を遮断する

sandbox 内の Python/network script が `socket.gaierror: nodename nor servname provided` で落ちても **machine の network 障害ではない** (curl も同様)。network を要する script は sandbox を外して実行する。外しても落ちる場合は一時的 DNS 失敗のことがあるので 1 回 retry してから実障害を疑う (2026-07-03 に両方を実測)。

## <a id="permission-gate-anchor"></a>7. 承認 gate は「script 名」でなく「実送信 flag」に anchor する

送信 script を `permissions.ask` で gate するときの mail-domain 適用形: ① script は **`--send` 必須の fail-safe 既定** (flag 無し = 常に dry-run) にし、② ask パターンは file 名 substring (`Bash(*send_mail.py*)`) でなく**実送信 invocation** (`Bash(*send_mail.py*--send*)`) に match させ、③ **実送信コマンドは chain せず単体で打つ** (= ダイアログ = 送信内容そのもの)。

file 名 substring パターンは「file 名に言及するだけの無害コマンド」 (py_compile / git add / grep / 送信前に必須の dry-run) に全部誤爆し、承認ダイアログの信号価値を壊す (2026-07-03 実例: syntax check + commit + push の chain で発火)。**一般則の正本 = [`claude-code-permissions.md`](claude-code-permissions.md#ask-pattern-action-anchor)** (= なぜ ask パターン自体を絞るしかないか 〔precedence 上 allow で ask の例外を彫れない〕 + 設計 3 点 set + 起動時ロードの注意)。hook が効かない surface (Claude Code desktop / bridge) では宣言 permission が唯一の機械 gate なので、この anchor 設計がそのまま送信 gate の品質になる。

## <a id="double-confirmation-design"></a>8. 二重確認の設計: chat 承認と harness chip は別の脅威モデル (= chip は減らすもの、 消すものではない)

送信の確認は 2 層あり、**役割が違う** — この区別を持たないと「chip がうざい → 消す」 か「不安 → 全部に chip」 の両極端に落ちる:

| 層 | gate | 守る脅威 |
|---|---|---|
| 規律層 (primary) | draft 全文の chat 提示 → user の **send-verb 明示承認** (「送って」等) → 送信 | 内容の誤り・宛先の誤り・そもそも送るべきでない判断 |
| harness 層 (backstop) | permission ask chip (宣言 `permissions.ask` / hook) | **chat 承認を経ない送信** = autonomy 拡張解釈・誤 invocation・prompt injection 由来の送信 |

設計原則:

1. **chip の品質 3 条件**: (a) 発火は**不可逆 action の実行形にのみ** (= §7 の anchor 設計、 誤爆ゼロ) (b) 頻度は実送信 1 回につき 1 個まで (c) ダイアログの中身 = 送信内容/コマンドそのもの (= 確認に情報価値がある)。 「うざい chip」 の正体はほぼ常に**誤爆** (broad pattern) か**同一 gate の重複** (同じ送信に複数 chip) であり、 治療は chip の廃止でなく anchor の絞り込み。
2. **chat 承認は chip を代替しない**: 規律層が守るのは「何を送るか」、 chip が守るのは「承認なしに送られない」 という invariant。 user が chat で承認済みでも、 chip は 「Claude が規律を破る / 騙される」 case の最後の機械防御として独立に意味を持つ。 逆に chip があっても draft 提示 + send-verb は省略できない (= chip は内容 review の場ではない)。
3. **frontend 非対称に注意**: hook 由来の ask は CLI でのみ honor される frontend がある (= [`hook-authoring.md`](hook-authoring.md#frontend-dependent-cowork))。 その frontend では**宣言 `permissions.ask` が唯一の機械 gate** — hook にだけ置いた gate は「ある」 ように見えて特定 frontend で不在になる。
4. **fail-safe 既定は chip の前提**: 送信 tool/script は「無指定 = 送らない」 (dry-run 既定 / `--send` 必須) にする。 chip が消えても (下記 5)、 誤 invocation では何も送られない床を作る。
5. **宣言配線は silent に消えうる = 「doc に書いた」 ≠ 「gate がある」**: `permissions.ask` は machine-local file で、 他の設定 UI / installer / 手編集に上書きされうる。 gate を doc に記録しただけでは守られない — **登録直後に実 invocation で chip 発火を verify** し、 高 stakes gate は「documented パターン ⊆ live settings」 を機械 audit する (実例 2026-07: 送信 gate の narrow ask パターンが記録上「登録済」 のまま live settings から消失しており、 送信 3 通が chip ゼロで通って初めて発覚 — 規律層 + fail-safe が守ったが、 backstop は不在だった)。
6. **並走する gate 層 (宣言 ask / hook / script fail-safe) は同じ anchor を共有する**: 送信 gate は複数層に住む (= `permissions.ask` パターン + PreToolUse hook + tool 側 fail-safe) が、 **発火条件 (= 実送信 flag) を全層で揃える**。 片層だけ「script 名 match」 のような広い述語で残ると、 dry-run / `--help` にも chip が出て条件 (a) 誤爆ゼロが破れる (実例 2026-07: tool 側を fail-safe 既定に反転した際、 hook の述語だけ script 名 anchor のまま未追随 → 1 通の送信で chip 3 個 — 検証 invocation への誤爆 2 + 引数エラーでの実送信形打ち直し 1。 anchor 統一 + 「dry-run で検証してから実送信 flag は 1 発」 の実行規律で 1 送信 1 chip に回復)。 ⚠️ anchor を flag に絞るなら **tool 側で argparse の prefix 短縮 (= `--sen` → `--send` 展開) を `allow_abbrev=False` で殺す** — 短縮形は literal flag pattern に match せず全 gate を素通りする。
   - <a id="mandated-dry-run-doubles-chip"></a>**「dry-run には chip が出るが軽微」 として残さない**: 手順が「送信前に dry-run で確かめる」 を必須にしている経路では、 dry-run が gate を踏むと**規律を守るほど毎回 1 送信 2 chip** になる (= 条件 (b) の恒常違反。 subcommand 名 〔`mailer.py <acct> send`〕 に anchor した gate で実測、 合成例)。 tool が fail-safe 既定 (flag 無し = 送信不能) なら、 全層の anchor を実送信 flag まで絞ってよい。
   - <a id="hook-keeps-ask-on-expansion"></a>**hook は flag が展開で入りうる形だけ保守的に ask を残す**: hook も宣言 ask も見ているのは typed command 文字列なので、 `$VAR` / `` `...` `` 経由の flag は literal 判定できない。 宣言 ask は glob しか書けないが、 hook は述語を書けるので「実送信 flag が literal に在る」 か「`$` / backtick を含む」 なら ask にする (= 検証用の dry-run は通し、 判定不能な形は止める)。
   - 複数マシンでは宣言 ask が machine-local なので、 絞った rule は旧 rule の置き換え表とともに auto-apply 層で各マシンに揃える ([`multi-machine-state.md#gate-rules-reassert-every-session`](multi-machine-state.md#gate-rules-reassert-every-session))。

## <a id="draft-approval-single-source"></a>9. 承認対象と実送信 body の single-source 原則 (= chat 提示 draft と body-file の 2 度書き乖離)

§8 の規律層 (= draft 全文 chat 提示 → user 承認 → 送信) には暗黙の前提がある: **user が chat で見た文面 = 実際に送信される文面**。 この前提は、 draft を chat 用 text と送信用 body-file で**別々に 2 度書きすると壊れる** — 片方だけに typo・編集漏れが混入し、 「承認された文面」 と「送った文面」 が乖離する = 承認 flow の完全性が崩れる (実例 2026-07: chat 提示 draft に助詞 typo が混入し user はその typo 版を見て承認、 実送信 file は偶然正しかった。 今回は無害な向きだったが、 **逆向き 〔file 側だけに typo / 編集反映漏れ〕 なら user が承認していない文面が外部に出ていた** — 発覚経路も user が送信後に typo に気づいた偶然で、 機械検出は無い)。

原則:

1. **draft は 1 source から導出**: 送信 body-file を**先に Write** し、 chat 提示はその file 内容を read した結果を貼る (= file が SoT、 chat は view)。 逆順 (chat で起草 → 承認後に file 化) になった場合は、 **送信前 dry-run の decoded body を chat 提示文と突合**してから送る (= §5 の dry-run truncation に注意、 末尾まで比較する)。
2. **承認後の文面変更は再提示**: 承認済み draft に 1 字でも手を入れたら (typo 修正・改行調整含む) 再提示 + 再承認。 「良くなる方向の修正だから」 は skip の理由にならない (= user が見た物と違う物を送らない)。
3. **mail に限らず全外部発信に適用**: Discord 投稿・issue comment・公開 site へ載せる text 等、 「draft 承認 → 送信」 flow を踏む全てで同じ 2 度書き乖離が起きうる (= content-file 経由の送信 tool は全部同型)。
4. <a id="draft-revisions-recoverable"></a>**直しの往復が続く draft は、 版を後から取り出せるようにしておく**: 本人が「2 回目ぐらいのがよかった」「さっき出していた案で」 と戻ることがある (実測)。 (a) 版を直すたびに draft file を commit する (commit message に何を変えたか 1 行) (b) chat で**代わりの言い回しを提案したら、 その案も draft file の末尾の「候補」 欄に書く** (chat だけに出した案は後で見つからない。 実測: 本人が覚えていた提案を agent が思い出せなかった) (c) 「何回目」 が一つに決まらないときは、 版ごとの該当段落を並べて番号で選んでもらう。 git-crypt で暗号化される path の旧版は `git show --textconv <rev>:<path>` で読む (`--textconv` が無いと暗号文が返る = [`hook-authoring.md#blob-read-git-crypt`](hook-authoring.md#blob-read-git-crypt))。

## <a id="reviewed-reply-bundle"></a>Reviewed reply bundle: preview, one send attempt, receipt

For repeated plain-text replies, use a dependency-free transaction rather than
rebuilding MIME and verification in each conversation. The generic implementation
is [`scripts/reviewed_mail.py`](../scripts/reviewed_mail.py); the account owner
supplies a gateway with `profile`, `get`, `send`, and `find` methods. The library
does not discover credentials, accounts, private rules, or agent history.
The gateway also supplies `thread` (the parent's thread as id / internal date /
labels / From / Message-ID rows) for the newer-reply check below.
The shared [CLI and Gmail gateway](../scripts/reviewed_mail_cli.py) accept an
injected account factory; account aliases and authentication stay in the owner's
binding. The [Codex installer](../scripts/codex_mail_install.py) takes explicit
skill/helper paths. Both their tests live in this shared repository and run in
the same `reviewed-mail.test.sh` suite. Compatibility wrappers may remain in
downstream repositories, but must not retain a second implementation.

The agent-facing sequence (including first-draft rule loading, scoped search,
final preview, approval and same-turn recording) is the
[shared mail procedure](../codex/skills/claude-config-operations/references/mail-workflow.md).
Owner skills supply only identity/style/ledger paths and the chosen launcher.

- `prepare` records the incoming parent, original quote, recipients, threading,
  selected signature, and existing project ledger path. Reply-all retains peers;
  a direct reply is an explicit caller decision.
- `preview` generates the exact body and envelope/body fingerprint. Show that
  artifact to the user. Style and fact checks still require the applicable SoT
  before drafting; a hash cannot perform them.
- `send` requires an explicit send flag and the current preview fingerprint.
  This checks equality, **not human consent**: the caller still needs explicit
  approval of the final text. Changed content invalidates the earlier review.
- `send` re-lists the parent's thread before its attempt. Messages from others
  newer than the parent refuse the send (CLI exit 6, no attempt recorded);
  `--ack-newer` with the newest one's id is the acknowledgement of having read
  them. `preview` lists them at the top. Usually prepare a new bundle on the
  newest message instead ([#reply-newer-in-thread](#reply-newer-in-thread)).
- An exclusive attempt file precedes the sole POST. After timeout or crash,
  `verify` reconciles by RFC Message-ID and checks the delivered headers, complete
  body, sent label, and thread. An ambiguous result stays unresolved; never
  delete evidence or create a replacement bundle to retry.
  Gmail may replace the supplied RFC Message-ID. When the POST response is
  saved, its Gmail message ID anchors verification; record both RFC IDs and
  still compare the full delivered content and envelope. If that response was
  lost and lookup by the requested RFC ID finds nothing, keep the outcome
  uncertain: ID rewriting makes a negative lookup insufficient to authorize retry.
- Delivery is saved before verification. The verified receipt stays pending
  until the owning ledger contains both message and thread IDs. Receipts are
  recovery evidence, not the correspondence SoT. The caller still owns accurate
  summaries, action status, encrypted persistence, and Git review.

Bundles are private runtime data (0700 directories / 0600 files), not public
fixtures. Synthetic tests run through `reviewed-mail.test.sh` in the aggregate
runner. Scope: plain-text replies with no outgoing attachments. The helper does
not control other mail clients or prevent an authorized local operator altering
its files. Use the relevant runbook for new mail, attachments, or inline images.

## <a id="inline-image-cid"></a>10. 数式・図を本文中に出すには inline 画像 (cid) — MCP では作れない

**状況:** plain text の mail で数式は読みにくい (`ρ_χ(end) = (3/2) V(x_end)` の羅列)。LaTeX で組版した PNG を**本文の流れの中に**表示させたい (= 添付ファイルとして開かせるのではなく)。

**事実:** MCP の `send_email` も plain-text + flat attachments の送信 script も、これを作れない。必要なのは `multipart/related` + `Content-ID` で、Gmail API 直接で組む:

```
multipart/mixed
├─ multipart/alternative
│   ├─ text/plain          ← 数式を平文で書き下した fallback (HTML 非対応環境用)
│   └─ multipart/related
│       ├─ text/html       ← <img src="cid:...">
│       └─ image/png       ← Content-ID, Content-Disposition: inline
└─ application/pdf 等      ← 通常の添付
```

Python の `email.message.EmailMessage` なら `set_content` (plain) → `add_alternative` (html) → html part に `add_related(..., cid=...)` → `add_attachment` の順で自動的にこの木になる。

- **cid は生成してから HTML に埋める** (= HTML に placeholder を置き、`make_msgid()` の値で置換してから build)。別々に書くと参照切れで画像が添付扱いに落ちる。
- **plain 版にも式を書き下す** (= HTML を表示しない受信環境への fallback。画像 alt では足りない)。
- 画像は幅 ~1400 px 目安 + `max-width` 指定 (受信側で縮小表示)。PDF を組版 → 余白 crop → PNG が確実 (画面 render と受信表示は概ね一致する — 印刷と違い raster 化の罠はない)。
- 送信後の構造検証は [#post-send-mime-verify](#post-send-mime-verify) と同じ。

**受信側の表示:** Gmail (web / mobile) と Apple Mail は cid inline を本文位置に表示する。実測 2026-08 (数式検算 note を研究者宛てに送信)。

## <a id="from-display-name"></a>11. From の表示名は Gmail 側の送信名で置き換わることがある

API 直送で MIME の From に表示名 (`"表示名" <addr>`) を入れても、 送信後の message の From は account の送信名設定の表示名になっていることがある (実測)。 表示名で相手に名前の表記を伝えたい (例: 相手が名前を誤記している) なら、 表示名に頼らず**署名**で示す。 送信名を変えたいなら Gmail の設定 (「名前」) の側で変える。

## <a id="quote-chain"></a>12. 過去のやりとりを新規メールに引用する: 新しい順の入れ子を header から組む

経緯を別の相手 (別組織の窓口など) に示すために、 複数の message の該当部分を新規メールの末尾に引用するときの形。

- **新しい message を最上段に置き、 1 通古くなるごとに引用を 1 段深くする**。 各段の頭に `On <日時>, <差出人> wrote:` を置き、 全段で同じ書式にする。
- **やりとりの最初の 1 通まで含める**。 起点の問いが無いと、 途中の返事が何に答えているかが読めない。
- **相手のメールソフトが作った引用の形を写さない**。 インライン返信の message をそのまま写すと、 古い発言が新しい返事より上に来て、 ソフトごとに違う `On … wrote:` 行 (言語・日時の書式) が混ざる (実測)。 各 message から抜粋だけを取り、 段は組み直す。
- **日時は header から機械で変換する**。 差出人の時差 (`-0500` など) を手で換算すると誤る。
- **抜粋は元の本文と照合する**。 手で写すと語尾の改変や取り違えが混ざる。 照合では空白・引用記号・HTML 由来の強調記号 (`*…*`) を無視する (= 相手のソフトの折り返しで行が一致しなくなるため)。

送信 script に持たせる形の例: spec = `[{"message": <id>, "lines": [抜粋, ...]}, ...]` を新しい順に並べて渡し、 script が各 message の header を引いて段を組み、 抜粋が本文に無ければ送信前に止める。 引用は本文の送信前検査 (HTML entity の混入など) の後に付ける (= 相手の原文を自分の本文の検査に巻き込まない)。

## <a id="standing-cc-inactive"></a>13. 定型の Cc の宛先が止まったら — 消さずに「休止」 にし、 入っていたら止める

ある種類のメールに毎回入れる宛先の一覧 (定型の Cc) の 1 人が、 アカウント停止の bounce (`550 5.2.1 The email account that you tried to reach is inactive`) で戻り始めたときの扱い。

- **一覧から黙って消さない**。 休止の欄に移し、 理由と戻す条件を書く (休職・異動の間の停止は復帰で戻る。 消すと戻すときに探し直しになる)。 停止の理由は bounce からは分からない = 分かる人に確かめてから書く。
- **送信前の検査は、 休止の宛先が Cc に入っていたら話題に依らず止める**。 定型の一覧を見る検査は話題の語で起動するので、 別の話題のメールに写した Cc は素通りする。
- **一覧の正本と同じ turn に、 文面の雛形に焼いた Cc 行も直す**。 起草は雛形から写すので、 正本だけ直すと次のメールに停止した宛先が戻る。
- 停止の前後に送ったメールを数えて bounce の通数と照合し、 どのメールがその人に届いていないかを記録に残す (他の宛先には届いている)。
- 停止と一時的な不達を bounce の文言で分ける: `5.2.1` + inactive = 停止、 `4xx` = 一時的 (再送で届きうる)。

## 関連

- MCP の scope / capability (send tool 不在 ≠ 送信不能): [`mcp.md`](mcp.md)
- Google API を Python から直接叩く setup 一般: [`google-api-direct-access.md`](google-api-direct-access.md)
- ML 宛に送るとき、 届けたい人が ML に入っているか (購読者一覧を読めない ML で、 入っていない人を過去のメールの宛先から見分けて個別に足す): [`google-api-direct-access.md#group-membership-without-owner`](google-api-direct-access.md#group-membership-without-owner)
- 送信内容の記録・分類: [`research-email.md`](research-email.md)
- 具体実装の例: 個人層側の Gmail 直送 script (= 本 doc の §2 自動解決 + §4 自動検証を実装したもの) を各自の private 層に置き、そこから本 doc を参照する
