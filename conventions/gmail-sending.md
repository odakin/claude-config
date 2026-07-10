<!-- doc-meta
when: Gmail でメールを送信する経路・MIME 実装を選ぶとき
category: mail
summary: Gmail 送信の経路選択と MIME 落とし穴 (= 返信は RFC 5322 Message-ID が要り MCP read では取れない → API 直送 script + 親 id 1 個で 3 点 set 自動解決を推奨 / 非 ASCII 添付 filename は RFC 2231 kwarg 必須〔f-string 直書きは noname 化〕 / 添付付き送信は送信後 MIME 検証まで 1 単位 / dry-run 先頭 truncate 罠 / Bash sandbox の network 遮断 / 承認 gate は script 名でなく実送信 flag に anchor〔fail-safe 既定 + ask パターン誤爆防止〕)
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

## 関連

- MCP の scope / capability (send tool 不在 ≠ 送信不能): [`mcp.md`](mcp.md)
- Google API を Python から直接叩く setup 一般: [`google-api-direct-access.md`](google-api-direct-access.md)
- 送信内容の記録・分類: [`research-email.md`](research-email.md)
- 具体実装の例: 個人層側の Gmail 直送 script (= 本 doc の §2 自動解決 + §4 自動検証を実装したもの) を各自の private 層に置き、そこから本 doc を参照する
