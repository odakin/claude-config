# Email surface pattern (= 重要送信者・ML トピックの見落とし防止)

特定の送信者 (= 重要部署・取引先・上長) や ML 上のトピック (= 入試・会議・人事) を**機械的に検出して Claude セッション開始時に必ず surface する**仕組み。 「見落とした」 を「規律違反」 ではなく「仕組み不足」 と捉えて構造化する。 CLAUDE.md から参照: `~/Claude/claude-config/conventions/email-surface-pattern.md`

## 動機 (= 規律 vs 仕組み)

「重要メールを見落とさないように気をつける」 は規律で、 失敗すると user / Claude の責任に帰される。 一方:

- Gmail filter が自動で「重要」 ラベル + STARRED + IMPORTANT を付ける
- セッション開始時に必ず走らせる dashboard script が「重要」 ラベル付き未読を最優先で表示する

の組み合わせなら、 規律に依存せず構造的に検出される。 規律と機械的検出は補完関係で、 機械的検出が「規律の負担を下げる」 ことに価値がある。 関連事例として `conventions/expensive-intermediate-artifacts.md` (= `/tmp` への artifact 永続化 reflex を hook で機械的検出) や `conventions/google-url.md` (= `/u/N/` URL 禁止を hook で検出) も同型の「reflex を hook で構造化する」 pattern。

## 構成 (= 3 layer)

### Layer 1: Gmail filter (= 自動ラベル付け)

Gmail filter で 2 種類のパターンを catch:

**Pattern A: 送信元 address による検出** (= 特定の部署 / 取引先 / 上長)
```
from:(<addr1> OR <addr2> OR <addr3>)
→ addLabels: [<重要送信者ラベル>, STARRED, IMPORTANT]
```

例: 入試運営部署の 3 メールアドレスから来るメール全てに「<部署名>」 ラベル + 黄色星 + 重要マーク自動付与。

**Pattern B: ML + subject keyword による検出** (= 学科 ML 等での重要トピック)
```
to:<ml-address> AND (subject:keyword1 OR subject:keyword2 OR ...)
→ addLabels: [<トピックラベル>, IMPORTANT]
```

例: 学科 ML での「入試 / 運営委員 / 作問 / 学科会議」 等 subject に対し「学科業務」 ラベル + 重要マーク。

注意:
- Pattern A は STARRED + IMPORTANT 両方付ける (= 強い signal)、 Pattern B は IMPORTANT のみ (= ML は数多いので STARRED は noise になる)
- subject keyword に too greedy なものを含めない (= 「入学」 だと「入学式」 「入学予定者数」 等の false positive)、 一方で narrow すぎると洩れる。 false positive を許容して洩れ防止優先が運用上は筋

### Layer 2: Retroactive labeling (= 既存メールへの遡及適用)

Gmail filter は**新規メールにのみ適用される**。 setup 後の filter は過去メールに作用しないため、 過去 1 年分等の既存メールには別途 batch_modify でラベル付与:

```python
# Pseudocode
msg_ids = search("<filter と同じ query>", max_results=N)
batch_modify(messageIds=msg_ids, addLabelIds=[<同 label ids>])
```

setup 直後の dashboard surface で既存の未読も一斉に visible になるので、 過去の見落としを retroactive に発見できる。 これが filter のみ (= 新規メール) と batch_modify (= 過去) の両輪。

### Layer 3: Dashboard surface (= セッション開始時の最優先表示)

セッション開始時の dashboard script で「重要」 ラベル付き **未読のみ**を取得して件名・送信者・経過時間で表示。 0 件なら無音 (= dashboard を散らかさない)。

```python
# Pseudocode
service = build_gmail_service(creds)
for label_name in ["<重要送信者ラベル>", "<トピックラベル>"]:
    label_id = resolve_label_id(service, label_name)
    msgs = list_messages(service, labelIds=[label_id, "UNREAD"], max=20)
    if msgs:
        print(f"=== 🚨 {label_name}: {len(msgs)} 件未読 ===")
        for m in msgs:
            print(f"  • {m.sender_short:30s} ({m.age}) {m.subject[:60]}")
```

dashboard 全体の末尾で呼び出し (= 既存 TODO 表示等の後)、 user / Claude が「最も新しい関心事」 として認識する位置に配置。

## リポ間の連携

```
gmail filter setup    -> 各 user の MCP 設定リポ + Gmail コンソール
batch_modify code     -> 各 user の odakin-prefs 等個人層の scripts/
dashboard surface     -> 個人層 scripts の <surface-name>.py を
                         unified-dashboard.py 末尾から subprocess invoke
session-start step    -> 該当業務リポの CLAUDE.md §「セッション開始時 (自動実行)」
                         で「dashboard を必ず走らせる + surface セクションを
                         最優先で対処」 を明記
ラベル運用注釈        -> 該当業務リポの contacts.yaml (or 同等の住所録) entry
                         に「filter で自動ラベル付け対象」 を記録 (= 削除時の
                         手当て根拠)
```

## false positive / false negative の trade-off

- **filter が too greedy** (= 例: subject に「入学」 を含む全 ML) → 入学式・入学予定者数等の false positive、 ラベルが noisy。 軽微、 見落とし防止優先で許容
- **filter が too narrow** (= 例: subject に「入試問題」 のみ) → 「入試運営委員」 「作問」 関連を取りこぼし、 見落とし発生。 重大、 false negative は許容しない
- **判定原則**: false positive を許容して false negative を防ぐ方向で設計

ラベル名の選択も「狭めすぎない」 がベター (= 「入試-ML」 より「学科業務-ML」 で会議・人事等も catch する余地)。 ただしラベル名が広すぎると surface 件数が爆発する trade-off あり、 user の実情に合わせて調整。

## 失敗からの導入 RCA (= 規律ではなく仕組みで防ぐ)

過去事例 (= 2026-05): 重要部署からのメール 1 通を「あとで対応」 して数日見落とし、 同テーマの ML 議論が並行して走っていることにも気付かず、 user 指摘で発覚。 規律 (= 「重要部署メールはすぐ対応」) は守っていたつもりでも、 humanly 5 日も経つと埋没する。

導入後: filter + dashboard surface で session 開始毎に「重要部署未読 N 件 / ML 重要トピック未読 M 件」 が画面に出るようになり、 構造的に reflex 化される。 規律負担を下げ、 同時に過去の埋没メールも retroactive labeling で一斉発見できる。
