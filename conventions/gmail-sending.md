<!-- doc-meta
when: Gmail でメールを送信する経路・MIME 実装を選ぶとき
category: mail
summary: Gmail 送信の経路選択と MIME 落とし穴 (= 返信は RFC 5322 Message-ID が要り MCP read では取れない → API 直送 script + 親 id 1 個で 3 点 set 自動解決を推奨 / 非 ASCII 添付 filename は RFC 2231 kwarg 必須〔f-string 直書きは noname 化〕 / 添付付き送信は送信後 MIME 検証まで 1 単位 / dry-run 先頭 truncate 罠 / Bash sandbox の network 遮断 / 承認 gate は script 名でなく実送信 flag に anchor〔fail-safe 既定 + ask パターン誤爆防止〕 / #double-confirmation-design = chat 承認〔規律層 = 内容〕と harness chip〔backstop = 未承認送信〕は別の脅威モデル — chip の品質 3 条件〔実行形 anchor・1 送信 1 個・dialog = 内容〕、 うざい chip の治療は廃止でなく anchor 絞り、 宣言配線は silent 消失しうる = 登録直後 verify + documented ⊆ live の機械 audit、 並走 gate 層〔宣言 ask・hook・fail-safe〕は同じ実送信-flag anchor を共有〔片層だけ script 名 match だと dry-run に誤爆 chip / argparse prefix 短縮は allow_abbrev=False で殺す〕 / #draft-approval-single-source = chat 提示 draft と送信 body-file の 2 度書きは乖離源 — body-file 先行 Write + chat は view、 承認後の変更は再提示、 全外部発信に適用)
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

## <a id="draft-approval-single-source"></a>9. 承認対象と実送信 body の single-source 原則 (= chat 提示 draft と body-file の 2 度書き乖離)

§8 の規律層 (= draft 全文 chat 提示 → user 承認 → 送信) には暗黙の前提がある: **user が chat で見た文面 = 実際に送信される文面**。 この前提は、 draft を chat 用 text と送信用 body-file で**別々に 2 度書きすると壊れる** — 片方だけに typo・編集漏れが混入し、 「承認された文面」 と「送った文面」 が乖離する = 承認 flow の完全性が崩れる (実例 2026-07: chat 提示 draft に助詞 typo が混入し user はその typo 版を見て承認、 実送信 file は偶然正しかった。 今回は無害な向きだったが、 **逆向き 〔file 側だけに typo / 編集反映漏れ〕 なら user が承認していない文面が外部に出ていた** — 発覚経路も user が送信後に typo に気づいた偶然で、 機械検出は無い)。

原則:

1. **draft は 1 source から導出**: 送信 body-file を**先に Write** し、 chat 提示はその file 内容を read した結果を貼る (= file が SoT、 chat は view)。 逆順 (chat で起草 → 承認後に file 化) になった場合は、 **送信前 dry-run の decoded body を chat 提示文と突合**してから送る (= §5 の dry-run truncation に注意、 末尾まで比較する)。
2. **承認後の文面変更は再提示**: 承認済み draft に 1 字でも手を入れたら (typo 修正・改行調整含む) 再提示 + 再承認。 「良くなる方向の修正だから」 は skip の理由にならない (= user が見た物と違う物を送らない)。
3. **mail に限らず全外部発信に適用**: Discord 投稿・issue comment・公開 site へ載せる text 等、 「draft 承認 → 送信」 flow を踏む全てで同じ 2 度書き乖離が起きうる (= content-file 経由の送信 tool は全部同型)。

## 関連

- MCP の scope / capability (send tool 不在 ≠ 送信不能): [`mcp.md`](mcp.md)
- Google API を Python から直接叩く setup 一般: [`google-api-direct-access.md`](google-api-direct-access.md)
- 送信内容の記録・分類: [`research-email.md`](research-email.md)
- 具体実装の例: 個人層側の Gmail 直送 script (= 本 doc の §2 自動解決 + §4 自動検証を実装したもの) を各自の private 層に置き、そこから本 doc を参照する
