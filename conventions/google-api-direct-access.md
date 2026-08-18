<!-- doc-meta
when: Google API を Python から直接叩く setup をするとき
category: infra
summary: Google API を Python から直接アクセスする setup pattern (= GCP project の 3 layer 構造、 API enable + propagate、 OAuth scope 設計、 mimeType 判別 Sheets vs xlsx、 Drive folder 一括 download 〔list pagination + native-export map + 再帰 + manifest、 #drive-folder-bulk-download〕、 Gmail 一括掃除 〔batchModify TRASH 30日undo + レビュー済み ID list 駆動 + 送信者別集計 + 本文入り通知の salvage、 判断基準 = 唯一の機械検索可能な記録か、 #gmail-bulk-cleanup〕、 storage quota 監視 〔Drive about.get storageQuota = Gmail+フォト+Drive 合算容量の唯一の API 監視点、 最小 scope drive.metadata.readonly、 反映ラグ + ゴミ箱 usage 込みの解釈 gotcha、 #storage-quota-monitoring〕、 Cloud Identity Groups API は group OWNER level で memberships CRUD 可能で Admin SDK の Workspace admin 制約を回避、 loopback OAuth consent フローの CSRF/横取り対策 〔state nonce + PKCE S256 + request-loop + 手動貼付の state 検証 + 補償制御 hard-fail + 識別子 charset 検証、 #oauth-loopback-hardening〕)
-->
# Google API を Python から直接アクセスする setup

MCP では cover できない (= bulk 操作・xlsx parse・特殊 scope) Google API call を Python から直接行うときの setup と運用規約。 個別 MCP (Gmail / Calendar / Classroom 等) と並存して動かす想定。 CLAUDE.md から参照: `~/Claude/claude-config/conventions/google-api-direct-access.md`

関連: [`mcp.md` api-direct-access](mcp.md#api-direct-access) (= 使い分け基準)、 [`google-url.md` gcp-project-management](google-url.md#gcp-project-management) (= URL 規約)。

## 全体像 (= 3 layer)

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: GCP project (= 全 owner 操作の単位)               │
│   project_id / project_number / owner email                 │
│   各 API は project レベルで個別 enable 必要 (Sheets/Drive)│
│   project owner にしか API enable・OAuth client 編集不可    │
├─────────────────────────────────────────────────────────────┤
│ Layer 2: OAuth client (= consent UI を出す主体)            │
│   1 つの GCP project に複数 OAuth client 可、 通常 1 つで充分│
│   gcp-oauth.keys.json を file system に保管                 │
│   複数アカウント (個人 + Workspace) の token 発行に共有可  │
├─────────────────────────────────────────────────────────────┤
│ Layer 3: Account token (= 各 Google アカウントの承諾結果) │
│   {account}-credentials.json として保管 (= access + refresh)│
│   scope 別に複数 token 並存可 (= Gmail scope vs Sheets scope)│
│   refresh_token で永続使用、 access_token は自動更新       │
└─────────────────────────────────────────────────────────────┘
```

**重要な区別**: project 管理 (= layer 1) と token 発行 (= layer 3) は別 layer。 owner アカウント (= layer 1) が個人 Google で、 token 発行 (= layer 3) を Workspace アカウントで行う構成は normal。

## まず: そもそも OAuth API が要るか (= published sheet は no-auth CSV で取れる)

read-only でよく、 対象の Google Sheet が **「ウェブに公開 (publish to web)」** 済なら、 OAuth も GCP project も**一切不要**で CSV を取れる。 publish 済 sheet の URL 形 `…/d/e/2PACX-…/pubhtml` に対し、 tab ごとに:

```
https://docs.google.com/spreadsheets/d/e/<published-id>/pub?gid=<gid>&single=true&output=csv
```

を `curl` / `urllib` で GET すれば CSV が返る (= 認証なし、 誰でも)。 他人が公開している sheet (= 自分が owner でない upstream) を mirror source にする時に特に有用。

- 見つけ方: 対象が GitHub Pages 等に sheet を iframe 埋め込みしているなら、 その `iframe src` の `…/pub?…` URL から `<published-id>` と各 `gid` を拾える。 `pubhtml` (gid なし) は全 tab を返す。
- 保守: tab (= 年度別シート等) ごとに `gid` が違うので、 必要な gid を script に小さな map で持つ (= 1 行/tab)。 publish が解除されると endpoint は HTML error を返すので、 取得失敗は silent skip にして pipeline を止めない。
- 制約: read-only かつ「公開済」 が前提。 private sheet / write / 細かい権限が要るなら下記の OAuth API 経由。

## GCP project の API enable

各 Google API (Gmail / Sheets / Drive / Calendar / Classroom / etc.) は GCP project ごとに**個別 enable 必要**。 1 つ enable しても他は別。

**URL 規約** (= [`google-url.md` gcp-project-management](google-url.md#gcp-project-management)):
```
https://console.developers.google.com/apis/api/{api}.googleapis.com/overview?project={projectNumber}&authuser=<project_owner_email>
```

- `authuser=` は project owner のメールアドレス。 active account が違うと「project が見つかりません」 で弾かれる
- API enable 後は **propagate 5-10 分** かかる場合あり (= typical は 1-2 分、 上限近い retry が必要なケースあり)。 立て続けに 403 `SERVICE_DISABLED` が返るのは propagate 待ち中の signal

**propagate 中の polling pattern** (Bash で背景 retry):
```bash
until python3 -c "<API call test>; sys.exit(0)" 2>/dev/null; do
  echo "$(date +%H:%M:%S) - not yet, sleeping 30s..."; sleep 30
done
```

通れば background 完了通知が返る。 sleep 90 のような単発長 sleep は harness が block するケースあり、 until-loop で polling する。

## OAuth scope の設計

### scope を最小化する原則

各 token は **必要最小限の scope** で発行する。 Drive 全体読み放題の `drive.readonly` よりも `drive.metadata.readonly` (= ファイル名・サイズ等のみ) や `drive.file` (= picker UI で grant されたファイルのみ) を優先。

ただし**読みたい対象が xlsx (= Office file) を含む**場合は `drive.readonly` が必須 (= `drive.metadata.readonly` では binary download 不可)。 Sheets native のみなら `spreadsheets.readonly` で済む。

### 既存 OAuth client に scope 追加 vs 新規 client

| 選択 | Pros | Cons |
|---|---|---|
| 既存 client + 既存 token に scope 追加 | OAuth client が 1 つで管理シンプル | 全 token が scope 拡大、 影響範囲不明、 既存 token は再 reauth 必要 |
| 既存 client + 別 scope set で新 token (separate directory) | 既存 token に影響なし、 用途別に独立 | directory + reauth 1 回ずつ、 token が増える |
| 新 OAuth client + 新 token | 完全独立 | GCP コンソールで client 作成必要、 user 承諾の consent screen も別物 |

**推奨**: 既存 client + 別 directory + 別 scope token (= 中段)。 既存 MCP の動作に影響を与えず、 用途別に独立管理。

### scope 増やし方の手順

1. 新 directory を `<mcp-config-repo>/<service>/` に作成 (例: `sheets/`)
2. `gcp-oauth.keys.json` を既存 directory (= 同じ GCP project の OAuth client) からコピー
3. `auth.mjs` (node.js) または auth Python script を作成
   - SCOPES を必要分のみ列挙
   - 既存 directory と被らない localhost port (e.g. 8370/8371/8372 → 新規 8373)
   - login_hint に対象アカウントを指定
4. node auth.mjs 実行 → ブラウザで承諾 → callback で token 保存
5. token は git-crypt で encrypt して commit (= `.gitattributes` で filter=git-crypt 指定)

### Scope 不足の error message

```
HttpError 403: ... insufficient_scope ...
```

→ scope 追加 + reauth が必要。 既存 token を上書きする (= 同じ credentials.json path を再書き込み)。

## mimeType による分岐 (= Sheets vs xlsx)

Google Drive 上のスプレッドシートには 2 形式がある:

| mimeType | 形式 | 読み方 |
|---|---|---|
| `application/vnd.google-apps.spreadsheet` | Google Sheets native | Sheets API (`spreadsheets().values().get`) |
| `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` | xlsx (= Excel アップロード) | Drive API `files().get_media` で download → `openpyxl` で parse |
| `application/vnd.ms-excel` | xls (= 旧 Excel) | Drive API download → `xlrd` 等で parse (= openpyxl 不可) |

**Sheets API は xlsx に対して `FAILED_PRECONDITION` を返す** (= "The document must not be an Office file.")。 mimeType を見て分岐する code path が必要。

**URL からの事前 hint**: 共有 URL に `?rtpof=true&sd=true` が付いている = 「Retain the original format」 = xlsx (= 元 file 形式を保持して開いている) の signal。

### Pattern: 統一 reader

```python
drive = build("drive", "v3", credentials=creds, cache_discovery=False)
meta = drive.files().get(fileId=file_id, fields="mimeType,name").execute()
mime = meta["mimeType"]

if mime == "application/vnd.google-apps.spreadsheet":
    # Sheets API
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    data = sheets.spreadsheets().values().get(spreadsheetId=file_id, range="A1:Z500").execute()
elif mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
    # Drive download + openpyxl parse
    import io, openpyxl
    from googleapiclient.http import MediaIoBaseDownload
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, drive.files().get_media(fileId=file_id))
    done = False
    while not done: _, done = downloader.next_chunk()
    buf.seek(0)
    wb = openpyxl.load_workbook(buf, data_only=True)
    # wb.sheetnames + wb[name].iter_rows(values_only=True)
```

## <a id="drive-folder-bulk-download"></a>Drive folder の一括 download (= list + native-export map + 再帰)

配布資料が「Drive folder ごと」 で来る場合 (= 説明会資料・様式 template 一式・委員会配布物 等) に、 folder 内の全 file を local に落として保存する recipe。 scope は `drive.readonly` で足りる (= write token 不要)。 手で 1 file ずつ開いて DL するより速く、 provenance (= いつの版を取ったか) が manifest に残る。

### 手順の骨格 (= 4 step、 このまま実装できる)

1. **folder listing** (pagination 必須):
   ```python
   resp = drive.files().list(
       q=f"'{folder_id}' in parents and trashed = false",
       fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)",
       pageSize=200, pageToken=page,
       supportsAllDrives=True, includeItemsFromAllDrives=True,  # 共有 drive 対応
   ).execute()
   # nextPageToken が尽きるまで loop
   ```
2. **file 種別で download 経路を分岐**:
   - Google native (= mimeType が `application/vnd.google-apps.*`) → `files().export_media(fileId=…, mimeType=<export 先>)` (= binary 実体を持たないため export 必須、 下表)
   - それ以外 (= PDF / xlsx / docx 等の binary) → `files().get_media(fileId=…, supportsAllDrives=True)`
   - どちらも `MediaIoBaseDownload` で chunk 読み → `BytesIO` → file 書き出し
3. **subfolder** (= mimeType `application/vnd.google-apps.folder`) は download せず**再帰** (dest 側にも同名 dir を掘る)。
4. **manifest 保存**: listing の json を dest に `_drive_manifest.json` として落とす (= file 名・id・modifiedTime の provenance。 後日「更新されたか」 の diff 基準になる)。

### native → export の対応表

| Google native mimeType | export mimeType | 拡張子 |
|---|---|---|
| `…google-apps.document` | `application/pdf` (or docx) | `.pdf` |
| `…google-apps.spreadsheet` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` | `.xlsx` |
| `…google-apps.presentation` | `…presentationml.presentation` | `.pptx` |

### gotchas

- **native file は listing の `size` が None**: 「空 file」 と誤判定しない (= binary 実体を持たないだけで中身はある)。
- **`export_media` は ~10 MB 上限**: 超える native doc は export が fail する — その時は UI 経由等の代替に切り替え (無理に chunk しても回避できない)。
- **file 名は原名のまま保存** (= 「〜のコピー」 等の重複 suffix 含む): rename すると manifest との対応が切れる。 名前衝突時のみ連番 suffix。
- **DL した様式はそのまま雛形として保存し、 fill は copy に対して行う** (= [`office-files.md`](office-files.md) の template-provenance 原則。 提出物で雛形を上書きすると再 fill・diff 検証が死ぬ)。

worked example: 配布 folder 30 file (root 6 + subfolder 24、 PDF + xlsx 混在) を 1 script で取得し、 repo docs/ に binary + manifest を保存 (2026-07)。

## <a id="gmail-bulk-cleanup"></a>Gmail 一括掃除 (= batchModify TRASH + 送信者別集計 + 本文入り通知の salvage)

storage 満杯対策等で Gmail を数千〜数万通単位で掃除するときの安全 pattern。 query 一発の削除より 1 段精密な「集計 → レビュー → ID list 削除 → salvage」 の流れ。

### 安全機構 (= 不可逆にしない)

- **削除は `messages.delete` でなく `messages.batchModify` の `addLabelIds:["TRASH"]`** (= 30 日間 undo 可能、 `removeLabelIds:["TRASH"]` で復元。 完全削除 = ゴミ箱を空にする、 は user の手操作に残す)。 batchModify は 1 call 1,000 ids 上限。
- **削除対象はレビュー済み ID list で駆動する** (= 集計時に sender→message-ids を JSON 保存し、 削除はその ids に対して実行。 削除時に fresh query し直すと「レビューした集合」 と乖離しうる)。 trash 前に件数 assert、 trash 後に元 query 0 件 + ゴミ箱件数一致を検証。
- **`from:` query の限界**: `+` 付き alias アドレス (`noreply+xxx@…`) に `from:` 部分一致が効かないことがある / 古いメールで query が実在数より少なく返る観測例あり (= 機構未検証)。 「残す」 と決めた送信者は事後に `in:trash from:X` で取りこぼし点呼するのが安全。

### 集計 → bucket → 承認

metadata batch fetch (= 本 doc §Batch request、 429 retry 込み) で From + sizeEstimate を集め、 **送信者別に件数 + 合計 MB** を出す (= サイズ帯別 〔larger:/smaller: の排他帯〕 も並用)。 削除判断は送信者 bucket 単位で人間の承認を取る。

### Salvage pattern (= 一括削除の必須の対、 削除前後に回す)

機械送信者のカテゴリ一括削除は「**通知メールに本文が埋まっているもの**」 を巻き込む。 purge 前にゴミ箱内の件名を pattern スキャンして外科的に復元する:

- SNS 通知に **DM / メッセージ本文** (= 旧 Twitter / Facebook の「〜さんからメッセージ」 通知は本文入り。 platform 側アカウントが消えるとメールが唯一の記録。 実測で SNS 通知の過半が DM 通知だった例あり)
- noreply 送信者に**購入レシート** (= note 等は宣伝と購入完了通知を同一アドレスから送る)
- **全文入りのブログ更新通知** (= WordPress 系。 ブログが消えると唯一のアーカイブ)

**残す / 消すの判断基準 = 「そのメールは唯一の機械検索可能な記録か」**: サービス側 (注文履歴・web) に正本があっても、 **agent がログイン必須のサイト側履歴に確実にアクセスできるとは限らない** — mail box は agent にとって最も確実な検索経路なので、 タイムライン記録 (購入・旅行・予約・人とのやりとり) は容量僅少なら残す。 配達通知のような「鮮度が命」 の類は「直近 1 ヶ月だけ残す」 折衷が効く。

quota への反映 (= ゴミ箱 purge・ラグ) は次節 #storage-quota-monitoring 参照。

## <a id="storage-quota-monitoring"></a>Storage quota 監視 (= about.get、 アカウント容量の唯一の機械監視点)

Google アカウントの保存容量 (= Gmail + フォト + Drive の**合算** 15GB 等) を API で監視する recipe。 満杯になると**メールの送受信が止まる**ため、 溢れやすいアカウント (= フォト backup 専用サブアカウント・長年運用の主アカウント) は閾値監視の価値が高い。

### 機構 fact

- **Drive API `about.get` の `storageQuota` が合算 usage の唯一の API 取得点**: `GET https://www.googleapis.com/drive/v3/about?fields=storageQuota,user` → `{limit, usage, usageInDrive, usageInDriveTrash}`。 Gmail 単体 / フォト単体の内訳 field は **API に存在しない** (= 内訳は storage 管理 UI でしか見えない)。 API で分離できるのは `usage - usageInDrive` (= Gmail + フォトの合算) まで。
- **Photos Library API は 2025-03-31 以降 app-created content 限定**: フォトの中身 (= 列挙・削除・整理) は外部 app から API 不可 → フォト起因の容量問題も **storageQuota 経由の監視が唯一の機械化点** (= 取り込み側は Picker API = user が UI で選択する半自動のみ)。
- **最小 scope = `drive.metadata.readonly`**: about.get はこれで足りる (= file 中身への access なし)。 監視専用 token は write 系 scope と分けて発行する (= least privilege、 §OAuth scope の設計)。
- **`limit` は GiB 基準**: 無料 15 GB plan の `limit` は `16106127360` bytes (= 15 × 2³⁰)。 10⁹ 割りで表示すると「16.1 GB」 に見える — 表示単位の混同に注意。

### Gotchas (= 監視値の解釈)

- **反映ラグ**: ゴミ箱 purge / 大量削除後、 usage への反映は数分〜最大 48h 遅れる。 「消したのに減らない」 の第一仮説はラグ (= 慌てて追加削除しない)。
- **ゴミ箱も usage に乗る**: Gmail もフォトも「ゴミ箱へ移動」 では解放されない (= 空にして初めて減る。 Gmail trash は 30 日で自動 purge されるので放置でも最終的には解放)。
- **token の account 検証**: about.get 応答の `user.emailAddress` を期待 account と照合する (= 下記 §OAuth token のアカウント検証 の about.get 版。 サブアカウント運用 = 同一ブラウザに複数 account が並ぶ環境では consent 画面の選択ミスが silent に残るので、 発行直後の 1 query 検証を必須にする)。

### 運用 pattern

発行は本 doc の通常手順 (= installed-app flow + localhost redirect + refresh_token 保存)。 check script は `--warn <pct>` (= 閾値超で exit 非 0) を付けておくと cron / dashboard 統合が 1 行で済む。 実装 instance (= 対象 account・保管場所・port 割当) は personal layer 側の各 API 設定リポに置く。

## Token refresh の運用

`google-auth` の `Credentials.refresh(Request())` で access_token を自動更新する。 refresh_token は通常 rotate しないが、 まれに Google 側で rotate される場合あり (= 7 日以上の長期未使用後等)。 rotate された場合は古い token が invalid_grant になるので、 再 reauth が必要。

実装パターン:
```python
import datetime as dt
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# token file の expiry_date (ms epoch UTC) を naive UTC datetime に変換
expiry = None
if tok.get("expiry_date"):
    expiry = dt.datetime.fromtimestamp(
        tok["expiry_date"] / 1000, tz=dt.timezone.utc
    ).replace(tzinfo=None)

creds = Credentials(
    token=tok["access_token"], refresh_token=tok["refresh_token"],
    token_uri=oauth["token_uri"], client_id=oauth["client_id"],
    client_secret=oauth["client_secret"], scopes=tok["scope"].split(" "),
    expiry=expiry,  # ← 必須。 渡さないと creds.valid が永久 True 扱いとなり refresh 起動しない
)
if not creds.valid:
    creds.refresh(Request())
# 必要なら更新後の creds.token / creds.expiry を file に書き戻す
```

### ⚠️ Pitfall: `expiry` kwarg 不在 → refresh path が dead code

`Credentials()` 構築時に `expiry` を渡し忘れると、 内部の `self.expiry = None` 状態となり `creds.expired` が False を返す (= None 比較が False)。 結果 `creds.valid = (not creds.expired) and (token is not None)` が **常に True**、 「if not creds.valid: creds.refresh(...)」 の refresh path が永久 dead code となる。 token file 内に `expiry_date` (ms epoch) を保存していても、 Credentials object に渡されなければ意味がない。

**症状**: stale token (= 数日〜数週経過) で API 呼び出しが `401 Unauthorized` で fail、 script 内の「自動 refresh」 は無動作、 手動 `creds.refresh(Request())` を独立 1-liner で呼ぶと復旧する。 手動 refresh で復旧するため「token が rotate された」 と誤診しがちだが、 root は expiry kwarg 不在で refresh path が起動していないだけ。

**実証** (= 2026-05-26、 `fetch-board-photos.py` で観察): 11 日経過の token で Picker session create が 401、 手動 `creds.refresh(Request())` で正常復帰 → root は load_credentials() の `Credentials()` 構築で expiry を渡していなかった。 expiry kwarg を追加した修正後、 21:11 JST に stale token (= expiry 13:11 UTC = 22:11 JST 前) で load を呼ぶと expired 判定 → refresh trigger → 新 expiry が token に書き戻される動作を smoke test で確認。

**確認手段**: 既存 google-auth 利用 script の `Credentials(` 呼び出しを grep、 `expiry=` kwarg が指定されているか sweep。 大量にある場合は wrapper 関数化を検討。

MCP server と Python script の同時実行で refresh が競合する可能性は理論上ある (= 両方が同時に refresh を試みて、 Google が新 refresh_token を rotate した瞬間に片方が古い token をファイルに書き戻す)。 実害は希だが、 long-running script 中は MCP 経由の同 account 操作を避けるのが安全。

## Batch request で round-trip 削減 + 429 rate-limit handling

多数の id を 1 件ずつ `service.users().messages().get()` (等) で逐次取得すると **HTTP round-trip 数がそのまま律速**になる (= 特に LibreSSL 等で TLS handshake が遅い環境では 1 件 ~200ms、 数百件 × 複数 account で分単位。 実例: dashboard が 540s timeout)。 `service.new_batch_http_request()` で **1 batch 最大 100 件**を 1 HTTP にまとめると round-trip を ~50-100 分の 1 にできる。

```python
def batch_get(service, ids, headers, batch_size=50):
    results, pending, attempt = {}, list(range(len(ids))), 0
    while pending and attempt <= 6:
        retry = []
        def cb(rid, resp, exc, _r=retry):
            i = int(rid)
            if exc is None: results[i] = resp
            else:
                st = getattr(getattr(exc, "resp", None), "status", None)
                if st in (429, 500, 502, 503, 504) or st is None: _r.append(i)
        for s in range(0, len(pending), batch_size):
            chunk = pending[s:s + batch_size]
            b = service.new_batch_http_request(callback=cb)
            for i in chunk:
                b.add(service.users().messages().get(userId="me", id=ids[i],
                      format="metadata", metadataHeaders=headers), request_id=str(i))
            try: b.execute()
            except Exception: retry.extend(chunk)   # batch 全体の transport 失敗 → chunk 丸ごと
        pending = retry; attempt += 1
        if pending: time.sleep(min(0.5 * 2 ** attempt, 4.0))
    return [results[i] for i in range(len(ids)) if i in results]   # 入力順を保つ
```

### ⚠️ 核心の pitfall: 429 で **半分が silent drop** → retry 必須

Gmail API は **per-user 250 quota units/sec**、 `messages.get` = 5 units。 batch 100 件 = 500 units を一度に投げると **超過分 (= 約半分) が `429 rateLimitExceeded` で個別失敗**する (= 実測 288 件中 112 件)。 `new_batch_http_request` の callback は失敗を **例外として渡すだけで自動 retry しない**ため、 素朴に書くと**出力件数が黙って減る** (= 「逐次版と一致」 が壊れる)。 → 429 / 5xx / transport 失敗を callback で集めて**指数 backoff で retry** し全件取得を保証 (実測 retry で 288/288 収束)。

- **batch_size は 100 ではなく 50** が良い: 単発 batch を 250 units 以下に抑えると初回 429 が減り retry round が減って **wall-time はむしろ速い** (実測 50: 5.7s/3round < 100: 9.8s/4round)。
- **入力順保持**: callback は順不同発火なので `request_id` に入力 index を渡し最後に index 順で reassemble。
- **fail-open**: retry 上限超過の未取得 id は drop (= 逐次版の get 例外 drop と同等)。 1 batch ≤ 100 を超えると batch 全体が HTTP 400。
- **fmt 使い分け**: header 不要で id↔threadId 解決だけなら `format="minimal"` (= metadataHeaders 不要)、 header 要なら `format="metadata"` + metadataHeaders。
- **検証の落とし穴**: live data を触る refactor なので「変更前 run の出力 vs 変更後 run の出力」 の件数 diff は新着 mail / slide する date 窓 / 並行 session の triage で揺れ、 真の regression と churn を区別できない。 → **同一 id 集合を逐次版と batch 版で fetch して正規化 record を同一プロセス内で比較**するのが drift-free (= message の threadId は不変なので churn 非依存)。

## OAuth token のアカウント検証 (= account 取り違えの silent 化を防ぐ)

OAuth token JSON (= credentials.json) には **どの account の token か** が記録されない (= access_token / refresh_token / scope のみ)。 そのため reauth フローで consent 画面のアカウント選択を誤ると、 alias と中身の乖離 (= 「業務用」 dir に「個人用」 token が入る) が **silent に残り**、 後から file を見ても判別できない。 実害: その alias を使う検索・送信が全部別 account に対して実行され、 「検索しても 0 件」 (= 別 account を見ているから当然) を「source 不在」 と誤結論する。

### 防止策 (2 段)

1. **reauth 時に login_hint で正しい account を事前選択**: consent URL に `&login_hint=<email>` を付けると Google が該当 account を事前選択し、 手動選択ミスを減らす (= email は平文 git に hardcode せず、 暗号化済 config から実行時取得)。
2. **token 取得後に getProfile で account 検証**: 保存した token で `users().getProfile(userId='me')` (gmail) / userinfo (他 API) を叩き、 emailAddress を期待値と照合。 不一致なら token を削除して fail させる (= silent 保存を構造的に防ぐ)。 token JSON に email が無いので、 この 1 query が唯一の判別手段。
   ⚠️ **この検証は hard-fail であること (= 空振り禁止)**: 期待 email の解決 (= 暗号化 config の読取り) や getProfile 呼び出しは「config が locked / 欠落」「network 一時失敗」で**黙って skip されがち** = 補償制御が自分で自分を無効化する。期待値を解決できない consent は**既定で中止**し (config unlock を案内)、 意図して未検証で進むときだけ明示 flag で override。 getProfile 失敗も quiet skip でなく retry + 「未検証」 の明示表示にする。 これは「条件付き発火 mechanism の非活性を可視信号化せよ」 ([`convention-design-principles.md#conditional-firing-visibility`](../docs/convention-design-principles.md#conditional-firing-visibility)) の security-control 版。

### 検索結果が「らしくない」 時の reflex

MCP / API の検索結果が期待と違う account の中身ばかり返る (= 業務 account のはずが個人購読 newsletter ばかり) なら、 token が別 account を指している疑い。 `getProfile` で接続先 account を直接確認する。 一般原則は [`debugging-discipline.md` mcp-zero-result-not-absence](debugging-discipline.md#mcp-zero-result-not-absence) 状態 (c) tool 接続先誤り。 reauth フローの login_hint + getProfile 検証の実装は各 MCP 設定リポ側 (= personal layer)。

## <a id="oauth-loopback-hardening"></a>OAuth consent フロー (loopback) の CSRF / code 横取り対策

デスクトップ / native app 型 OAuth は `http://127.0.0.1:<port>` に consent 結果を受ける loopback listener を立てる。この listener は **同一マシンの他プロセス / ブラウザ上の drive-by web page** から触れる (= `fetch("http://127.0.0.1:PORT/?code=…")` は cross-origin でも fire-and-forget で届く)。素朴実装は 3 つの穴を持つ:

- **偽 code の先着 (login-CSRF)**: consent 待ちの窓に攻撃者が自分の authorization code を先着させると、**攻撃者アカウントの token が user の alias に保存**され、以後の読み書きが攻撃者側 mailbox を向く (= data exfiltration)。
- **単発 listener の DoS**: `server.handle_request()` 1 回だけだと、無関係 / 偽 request 1 発で本物の callback も潰せる。
- **手動 URL 貼付 fallback の phishing**: 「localhost refused」 画面の URL を貼らせる経路は、別フロー / phishing された URL を貼らせる窓。

対策 (Python stdlib だけで実装可能):

1. **state nonce**: consent URL に `&state=<secrets.token_urlsafe(24)>` を付け、callback は **state 一致の request だけ受理**。不一致は 400 で無視し、**deadline まで本物を待ち続ける loop** にする (= per-request timeout を短くして `while` で回す。単発 `handle_request` にしない)。
2. **PKCE (S256)**: `code_verifier` (48B) + `code_challenge = BASE64URL(SHA256(verifier))` を consent に付け、token 交換に `code_verifier` を必須化。万一 code を横取りされても、verifier を知らない攻撃者は交換できない。
3. **手動貼付でも state を検証**: 貼られた URL の state を照合し、不一致は拒否 (= phishing URL は貼っても弾かれる)。
4. **補償制御は hard-fail**: 上記「account 検証」節の getProfile 照合が空振りする状態 (期待 email 未解決) では consent に進まない。

+ **入口で識別子を検証**: reauth engine は alias / account 名を **filesystem path** と **`pgrep -f "…/${alias}/…"` pattern** に流すことが多い。alias を plain token (`A-Za-z0-9_-`) に検証しないと、`..` で path traversal / `|` で pgrep の ERE が alternation 化し **kill 対象が任意プロセスに化ける** (confused-deputy)。引数は入口で charset 検証する。

実装済 reference: gmail MCP reauth engine ([`gmail-mcp-multiaccount.md`](gmail-mcp-multiaccount.md) invariant 7-8、hermetic test 付き)。**同型の loopback OAuth フローを他にも持つなら同じ hardening を横展開する** (どのフローが未対応かは公開面に書かず個人層で追跡)。

## documentation の義務

GCP project に紐づく以下の情報は**個人層 (= layer 3) の secrets-related docs に明記**しておく:

- **project owner email**: 管理操作 (API enable / OAuth client / quota / billing) に使うアカウント
- **project_id + project_number**: URL 組み立てに使う stable identifier
- **enable 済 API のリスト**: 新 setup 時の参考、 API 追加時の更新対象
- **OAuth client 共有 status**: 同じ client を複数 directory (e.g. gmail-mcp + calendar + classroom + sheets) で使い回す pattern なら、 client rotate 時の影響範囲

これがないと、 multi-account 持ち user / Claude が「どのアカウントで GCP コンソール開けばいいか」 で繰り返し混乱する。 owner email は public docs (= claude-config 等) では PII になるので、 個人層に書く。

## Cloud Identity Groups API (= group owner level CRUD)

Workspace 内の Google Groups (= ML) の購読者管理を **caller が Workspace admin でなくても group owner なら API 経由で実行できる**経路。 Admin SDK Directory API (= `admin.googleapis.com`) との分離を理解する。

### 2 API の使い分け

| API | endpoint | 権限要件 | 用途 |
|---|---|---|---|
| **Admin SDK Directory API** | `admin.googleapis.com` | **Workspace admin 必須** | 全 group / 全 user を横断管理 (= Workspace 全体) |
| **Cloud Identity Groups API** | `cloudidentity.googleapis.com` | group OWNER role で OK (= Workspace admin 不要) | 自分の所有 group の memberships を CRUD |

「Workspace admin 権限がない member が自分の所有 group を管理する」 use case では Admin SDK は使えないが、 Cloud Identity Groups API で代替できる。 **「Workspace admin = なし」 で諦めずに Cloud Identity 経路を試す**のが reflex。

### OAuth scope

- `https://www.googleapis.com/auth/cloud-identity.groups.readonly` — read only (= memberships.list 等)
- `https://www.googleapis.com/auth/cloud-identity.groups` — full read + write (= memberships.create / delete 含む)

owner level の write には `cloud-identity.groups` (= full) が必要だが、 caller の権限が「group OWNER」 なら scope は通る (= Workspace admin role は不要)。

### 主要 method

- `groups.lookup` (= email → group resource name): query param `groupKey.id` に group email を渡して `groups/{group_id}` 形式の resource name を取得
- `groups.memberships.list` (parent=`groups/{id}`): membership 一覧
- `groups.memberships.create` (parent=`groups/{id}`, body=`{preferredMemberKey: {id: <email>}, roles: [{name: "MEMBER"}]}`): add
- `groups.memberships.delete` (name=`groups/{id}/memberships/{membership_id}`): delete

### caveat

- **`memberships.list` の default view では `createTime` が返らない** (= 簡略 view、 `(no time)` で出力)。 詳細 view (`view=FULL` query param) で取れる可能性、 当面未検証
- **delivery 状態 (= 配信エラー有無) は API 経由では取得不能**: UI からの CSV export なら取れる。 audit には UI export を quarterly / yearly で取って diff 取る運用が推奨
- **`nickname` field (= UI 表示名 hint) も API 経由では取得不能**: 同上 CSV 経由

### 実証 / 動作確認パターン

新規 setup の検証は read → write の 2 段:

1. **read 実証**: `groups.lookup` + `memberships.list` で member 数が UI 表示と一致するか
2. **write 実証**: 自分の別 alias (= 副作用最小、 add → list 確認 → delete → list 確認の cycle) で create + delete が success するか、 ML state 原状復帰確認

caller permission が API server 側でどう扱われるか docs に明記されていない部分があるため、 試行で実証して確度を確定するのが効率的。 setup コスト ~30 分 vs UI 操作の生涯コストを比較すれば実証投資は ペイする。

### Admin SDK 経路が NG と判明したときの reflex

1. user 確認「Workspace admin か?」 → `admin.google.com` ログイン可否で判定 (= 「管理者アカウントでログインしてください」 表示なら admin なし)
2. admin なし → **Admin SDK Directory API の前に Cloud Identity Groups API を試す** (= 「admin なし = 全 API NG」 と短絡しない)
3. group の OWNER role を caller が持っていれば Cloud Identity 経路で write OK の可能性高、 試行で確定

これは「**user 確認 = mechanism 確定と短絡しない**」 reflex の典型 application (= confidence escalation 防止、 user の claim level fact 〔= 「admin かどうか」〕 から mechanism level 〔= 「全 API NG かどうか」〕 への jump を避ける)。
