# Google 系サービスの URL 書式

Gmail / Drive / Photos / Classroom / Calendar / Docs / Sheets / Slides 等の Google 系サービスで Claude がチャットや文書に URL を出力するときの規約。CLAUDE.md から参照: `~/Claude/claude-config/conventions/google-url.md`

## 核となる規則

**2 つの規律を併用する**:

1. **`/u/N/` 書式 (account slot index) を生成しない** — ブラウザの account 追加順依存で壊れる
2. **Account-sensitive な URL には `?authuser=<email>` を付ける** — ブラウザに複数 Google アカウントがログインしている場合、 stable ID だけでは active account 依存で壊れる (権限なし → 404 / 別 view が開く)

**scope**: 規律 2 (= `authuser=` 必須) は **自分 (= 規約 owner = URL の生成者) が click する URL** が対象。 他人 (= メール受信者 / chat 相手 / 共有 doc / Discord 投稿 等) が click する URL では `authuser=` の意味が逆転して壊れる (= 詳細は §How to apply (d))。

NG 例:

- `https://mail.google.com/mail/u/0/#inbox` ← `/u/N/` 違反
- `https://classroom.google.com/u/2/c/...` ← `/u/N/` 違反
- `https://drive.google.com/drive/u/1/...` ← `/u/N/` 違反
- `https://classroom.google.com/c/{classId}` ← stable ID だけ、 authuser= 抜け、 別 account active 時は 404
- `https://docs.google.com/document/d/{docId}/edit` ← 同上

OK 例 (stable ID + `?authuser=<email>` 併用):

- `https://classroom.google.com/c/{classId}?authuser=<email>`
- `https://docs.google.com/document/d/{docId}/edit?authuser=<email>`
- `https://mail.google.com/mail/u/?authuser=<email>#inbox`

## Why

### `/u/N/` を避ける理由

`/u/N/` の N は **ブラウザセッションでの Google アカウント追加順** に依存。

- user がアカウントを追加・削除すると N がずれる
- 別マシンで開くと N が違う
- 一度ログアウトして再ログインすると順序変更される

Claude が生成した `/u/N/` URL は、user の環境が変わった瞬間に壊れる link になる。「書いた時点では正しい」では不十分 — 後から読んだときに壊れている可能性が高い。

### `?authuser=<email>` を併記する理由

stable ID 形式 (`classroom.google.com/c/{id}` 等) は account 非依存に **見える** が、 ブラウザに複数の Google アカウントがログインしているときは active account の view で開く:

- 別 account が active で当該 ID への権限が無い → 404 / access denied
- 別 account が active で同 ID にも別 view (= 別 role) で参加している → 意図と違う view

`?authuser=<email>` を付ければブラウザが対象アカウントに切替えて開く (= 決定論的)。 single-account user でも明示する方が forward-compatible (後で multi-account になっても壊れない、 共著者・共同研究者に URL を渡したときも各自の `<email>` で開ける感覚的整合性)。

## How to apply

### (a) Stable identifier + `?authuser=<email>` を使う (推奨)

Google 系サービスは多くの場合、 account-independent な stable URL を持つ。 これに **`?authuser=<email>` を併記** する:

| サービス | Stable URL 形式 (with authuser=) |
|---|---|
| Gmail (thread) | *stable URL 不在*。 Thread ID / Draft ID / Message ID を提供して user navigation に任せる (次項) |
| Drive (file) | `https://drive.google.com/file/d/{fileId}/view?authuser=<email>` |
| Drive (folder) | `https://drive.google.com/drive/folders/{folderId}?authuser=<email>` |
| Docs / Sheets / Slides | `https://docs.google.com/document/d/{docId}/edit?authuser=<email>` (sheets / presentation も同) |
| Photos (album) | `https://photos.google.com/share/{shareId}?authuser=<email>` (共有 link がある場合) |
| Classroom | `https://classroom.google.com/c/{classId}?authuser=<email>` |
| Calendar (event) | `https://www.google.com/calendar/event?eid={eventId}&authuser=<email>` |
| Calendar (view) | `https://calendar.google.com/calendar/r?authuser=<email>` |
| Meet | `https://meet.google.com/{code}?authuser=<email>` |
| **GCP project 管理** (API enable / Quota / OAuth client / consent screen) | `https://console.developers.google.com/apis/api/{api}.googleapis.com/overview?project={projectNumber}&authuser=<project_owner_email>` |
| **GCP console root** | `https://console.cloud.google.com/?authuser=<project_owner_email>&project={projectId}` |

### <a id="gcp-project-management"></a>GCP project 管理操作の特殊性 (= token 発行 と project 管理は別 layer)

GCP コンソール (= console.cloud.google.com / console.developers.google.com) の URL は **project owner アカウント** でのみ作用する。

- **Token 発行 layer**: 各 Google アカウントが個別に OAuth flow で承諾 → credentials.json を取得。 複数アカウント (= 個人 Gmail + Workspace 複数) で並行運用可
- **Project 管理 layer**: API enable / quota / OAuth client 編集 / consent screen 編集 / billing は **project の owner 1 アカウントのみ**が実行可能

active account が project owner と異なる場合、 project ID のみの URL で開くと「project が見つかりません」 / access denied になる。 これは「stable ID + authuser= 必須」 ルールの典型的な発火事例 (= 2026-05 GCP API enable 操作中に再現)。

例 (NG → OK):
```
NG:  https://console.developers.google.com/apis/api/sheets.googleapis.com/overview?project=<projectNumber>
OK:  https://console.developers.google.com/apis/api/sheets.googleapis.com/overview?project=<projectNumber>&authuser=<project_owner_email>
```

**運用上の含意**: project owner アカウントは各個人の Claude 環境ごとに異なる (= 多くの場合は個人 Google アカウント、 ただし Workspace admin が許可した場合は workspace アカウントもあり得る)。 owner アカウントは個人層の secrets 関連 docs (= `<personal-layer>/CLAUDE.md` 等) に明記しておくと、 multi-account 持ちの user / Claude が混乱しない。

### (b) Stable URL がない場合 — ID を渡して navigation を user に任せる

Gmail のように stable URL が存在しないケースでは、 **URL を構築せず、 ID だけを提供**する:

```
Thread ID: 19d3e72ae4005b23
Draft ID:  r-5529726991427467827
```

user は自分の Gmail (すでにログイン中) で navigation する。 `/u/N/` を推測するより正確で、 user の環境に依存しない。 root URL が必要なら `?authuser=<email>` 付きで:

```
https://mail.google.com/mail/u/?authuser=<email>#inbox
```

### (c) どうしても account-less root URL が必要なら

「Google サービス全般を開く」 系の説明的 URL は、 account slot を含まない root のみ書く:

- `https://mail.google.com/mail/`
- `https://drive.google.com/`
- `https://classroom.google.com/`

ブラウザは current active account で開く。 決定論性は無い。

### (d) 他人に渡す URL では `authuser=` を削除する

メール本文 / chat 投稿 / 共有 doc 内のリンク / Discord 投稿 等、 **受信者が click する URL** では `?authuser=<self_email>` を**付けない**。 受信者のブラウザに「自分 (= 規約 owner) の account に切替えて開け」 と指示が飛ぶが、 受信者はその account を持たないため 401 / 403 / access denied で破綻する。

| URL の用途 | `authuser=` の扱い |
|---|---|
| 自分のメモ / chat で自分が click 用 | `?authuser=<self_email>` 必須 (= 上記 (a)) |
| メール本文 / chat / 共有 doc 等、 **他人**が click 用 | `authuser=` パラメータを**削除** (= 受信者の active account で開く、 標準的メール慣習) |
| 他人で、 かつ特定 account 強制が必要 (= recipient が複数 account 持ち + 特定 account からのみ permission あり) | `?authuser=<recipient_email>` (= 受信者の email、 自分のではない) |

`/u/N/` 禁止は他人視点でも継続適用 (= account slot は誰の視点でも壊れる)。

NG 例 (= 他人宛 URL に自分視点の authuser= が混入):
```
受信者 (= 同僚): メールで Drive folder URL を受け取り click
→ https://drive.google.com/drive/folders/{folderId}?authuser=<self_email>
→ 受信者ブラウザが <self_email> account への切替を試みる → 持っていない → access denied
```

OK 例:
```
https://drive.google.com/drive/folders/{folderId}
(= authuser= 削除、 受信者の active account で開く)
```

### <a id="public-surfaces-no-authuser"></a>(e) 公開 surface は `authuser=` 不要 (= 規律 2 の対象外)

規律 2 の対象は「開く account によって見え方が変わる URL」。 **誰がどの account で開いても同じ表示になる公開 surface** には `authuser=` を付けない (= 決定論性に寄与せず、 他人の公開ページを contact 情報として記録する用途では不自然なパラメータになる):

- **published Google Sites** (`sites.google.com/view/<name>`) — 研究者の公開ホームページ等。 ⚠️ `/view/` でも共有制限された site は存在し得る (= その場合は account-sensitive だが稀)。 **編集 URL (`sites.google.com/d/...`) と workspace domain 配下 (`sites.google.com/a/<domain>/...`) は常に account-sensitive** として扱う
- **Google Scholar** (`scholar.google.com/citations?user=...`) — 公開プロフィール
- **Google Maps** の場所 URL 等の公開 content

機械 guard の扱い: `hooks/google-url-guard.sh` は最初から **ID を持つ account-sensitive service path のみ**を case whitelist で対象にしており (= mail/classroom/drive/docs/calendar/photos/meet)、 公開 surface は元々 flag しない。 broad regex (= domain 一致) で downstream に別実装 (commit-time warn 等) を作る場合は、 published Sites `/view/` 等の公開 path を例外にして chronic false positive を避ける (= 2026-07-02: 研究者 DB に公開ホームページ URL を記録するたび warn が出た事例)。

## 例

**NG** (account-dependent、 壊れる):

```
Gmail lab thread を確認してください:
https://mail.google.com/mail/u/1/#all/19d3e72ae4005b23
```

**OK** (ID 提供、 navigation は user に任せる):

```
Gmail lab で thread 19d3e72ae4005b23 を確認してください。
(Gmail を開く → 適切な account に切替 → thread ID で検索または直接参照)
```

**NG** (stable ID のみ、 multi-account で active が違うと壊れる):

```
Classroom: https://classroom.google.com/c/{classId}
```

**OK** (stable ID + `?authuser=<email>`):

```
Classroom: https://classroom.google.com/c/{classId}?authuser=<email>
```

## 既存の具体例 (この規則が適用される箇所)

- 個人 Classroom 運用 repo の Classroom クラス一覧: stable URL `classroom.google.com/c/{ID}` を使用 (本規則の初出 context、 本ファイル新設の契機)。 ターン応答で URL を出すときは `?authuser=<email>` を併記する
- owner の personal layer の user profile 記述「ブラウザでアクセス」: 2026-04-16 に `/u/1/` → `authuser=<email>` 形式に修正済み (= 個人層、 collaborator access 不要)
- `claude-config/hooks/google-url-guard.sh`: PreToolUse hook (Edit / Write / MultiEdit / Bash) で **(A) `/u/N/` パターン** と **(B) account-sensitive な URL の authuser= 抜け** を検出して `permissionDecision=ask` で確認を仰ぐ。 setup.sh が ~/.claude/hooks/ に symlink を作成 + settings.json にマージ (2026-04-16 (A) 追加、 2026-05-09 (B) 追加 + claude-config 配下に移動)

## 失敗履歴

- **2026-04-16**: `/u/N/` パターンが 2 回再発。 規約と CLAUDE.md inline ルールが両方あったが Claude が読まず、 機械的ブロック (`/u/N/` 検出 hook) を導入
- **2026-05-09**: Classroom URL `https://classroom.google.com/c/{id}` を `?authuser=` 抜きで chat 出力。 active account 依存で壊れる risk を踏んでいた。 hook の検出範囲を「(B) account-sensitive な URL の authuser= 抜け」 まで拡張 + 本 convention に「stable ID だけでは不十分」 を明示
- **2026-05-27**: 同僚教員宛メール draft で Drive folder URL に `?authuser=<self_email>` を付けて提示 → user 「受信者が読めないじゃん」 指摘で削除版に修正して送信。 旧規約 (= 「stable ID + authuser= 必須」) が **自分視点** で書かれていて、 「他人視点では `authuser=<self>` が破綻」 の場合分けが明示されていなかったため発生。 本 commit で核となる規則に scope 明示 + §How to apply に (d) 新設 + 本 entry 追加
