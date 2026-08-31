<!-- doc-meta
when: config file に ID/PII (Discord ID 等) を置く設計をするとき
category: infra
summary: Identity-in-Config 規約（Discord 等 PII-in-disguise、layer 2 + env var bridge）
-->
# Identity-in-Config 規約

**対象**: 設定ファイル (`*.yaml` / `*.toml` / `*.json` / `.env` / 等) に埋め込まれる、実在する特定個人を指す identifier の取扱い。

## 問題: "PII-in-disguise"

下のような field は **application config のフォルトラインに紛れこんだ PII** で、email や phone number と同等の識別子として扱う必要がある。しかし field 名が innocent (timeout や retry_count と同クラス) のため、書き手の認識が起動しない。

| 形式 | プラットフォーム | 例（placeholder） |
|---|---|---|
| `<@NNNNNNNNNNNNNNNNN>` | Discord (user mention) | `<@USER_ID>` |
| `<@&NNNNNNNNNNNNNNNNN>` | Discord (role mention) | `<@&ROLE_ID>` |
| `UXXXXXXXXXX` / `WXXXXXXXXXX` | Slack (user ID) | `U01A2B3C4D5` |
| `@user:server.tld` | Matrix | (既存 email regex で拾う) |
| `@user@instance.tld` | Mastodon / ActivityPub | (既存 email regex で拾う) |
| 数値のみ (int64) | Telegram / LINE chat ID | regex で拾えない — field 名から推測するしかない |

> **例示の書き方**: 上表および後述の diagram では、例示を `<@USER_ID>` や `<18-digit snowflake>` のように **regex に非マッチな形**で書く。17-20 桁の実数字を例に使うと hook / audit が自分自身の convention doc を false positive として flag する（self-reference 問題）。将来 editor が「例なんだから数字にしよう」と修正したくなっても、**ここはあえて非数字のまま**にするのが正しい。

### なぜ危険か

Discord 数値 ID 単体の危険度は低いが、**実名・所属・役職・所属コミュニティと並列されると dox (doxxing) 素材価値が跳ね上がる**。public repo の profile / config / docs にこれらの情報が隣接して存在するのが最悪パターン。

加えて、これらの ID は一度 public に push されると:

- force-push で main から外しても、GitHub が orphan commit を SHA 直接アクセスで serve し続ける (自然 GC まで数日〜数ヶ月)
- 本人が ID を変更することは困難 (Discord は user ID 不変、Slack は workspace 固定)
- archive.org / fork / clone されていたら完全除去不能

## 対策: layer 2 + env var bridge パターン

odakin の 4 層アーキテクチャ (`docs/personal-layer.md`) に従って、identity-in-config は **layer 2 (collaborator registry)** を canonical source とし、public tool (layer 1) 側は **env 変数名のみ**を保持する:

```
┌─────────────────────────────────────────────────────────────────┐
│ layer 2 (private, git-crypt)                                    │
│   research-collab/collaborators.yaml                            │
│   - id: alice                                                   │
│     discord_id: "<18-digit snowflake>"  ← 正本                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │ odakin が手動 (or sync script で)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ runtime (local, gitignored)                                     │
│   <tool>/.env                                                   │
│   DISCORD_MENTION_ALICE=<@USER_ID>                              │
└──────────────────────────┬──────────────────────────────────────┘
                           │ os.environ[...] at load time
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ layer 1 (public)                                                │
│   <tool>/profiles/alice/config.yaml                             │
│     mention_target_env: DISCORD_MENTION_ALICE   ← env 名のみ   │
└─────────────────────────────────────────────────────────────────┘
```

### 実装ルール

1. **public repo の config.yaml / profile には identity 数値 ID を直接書かない**。`mention_target_env: DISCORD_MENTION_<NAME>` のように env 変数**名**のみ保持する
2. **canonical source は layer 2**。`collaborators.yaml` (git-crypt) の `discord_id` field に置く (`conventions/collaborators.md` 参照)
3. **runtime 側は `.env` (gitignored)** が実値を保持。`load_dotenv()` 等で env に展開
4. **Cross-machine sync**: 新 Mac では `git-crypt unlock` 後に helper script (例: `tools/sync_mentions.py`) で `collaborators.yaml` → `.env` を再生成。Dropbox 暗号化 backup は不要 (layer 2 git-crypt が backup も兼ねる)
5. **Fail-soft**: env 未設定時に tool が crash しない設計にする。mention なしで送信 + warning log が無難

## 自動検出

- **`hooks/public-leak-guard.sh`** の tier A pattern `discord_mention` が `<@&?[0-9]{17,20}>` を検出 → PreToolUse で `permissionDecision=ask`
- **`scripts/audit-public-repos.sh`** が同 regex で既存 repo を遡及 scan → `### [tier-a/discord_mention]` section に report

## 他プラットフォームの扱い

現時点で regex 化しているのは Discord のみ。理由と今後の方針:

- **Slack (`UXXXXXXXXXX`)**: `\b[UW][A-Z0-9]{8,}\b` は false positive が多すぎる (大文字始まり英数識別子は一般的)。Slack 統合が実際に発生し leak 事例が出た時点で追加。それまでは convention doc でのみ規範化
- **Matrix / Mastodon**: `@user:server.tld` と `@user@instance` は既存 email regex で拾われる (tier-a/email に分類される)
- **Telegram / LINE chat ID**: 数値のみで regex 識別不能。field 名ベースで検出するには lint 層が必要、overengineering につき見送り
- **GitHub user ID (数値)**: 公開情報、PII 扱いしない

## <a id="homonym-author-id"></a>Homonym 注意: author ID (INSPIRE BAI 等) の取り違え

INSPIRE BAI (`T.Kono.1`, `H.Otsu.4` のような形式の author ID。 例は架空) は **同姓同名の別著者を別 ID として管理する**が、setup 時に検索結果から **同姓の誰か別人**を選んでしまうと、「subscriber は実際 A さんなのに INSPIRE profile は A' さんのもの」という状態になる。公開リポに BAI を書くことで:

- 第三者の共同研究者リスト (Super-K collaboration 15 名等) がその subscriber の profile として公開される
- arxiv-digest の scorer が A' さんの研究分野で採点するため、本来の A さんの興味と乖離する
- subscriber が「知らない人の研究リスト」で scoring される気持ち悪い状態になる

### 対策

- **setup_inspire 実行時の検証**: 最初の検索結果をそのまま採用せず、本人に以下を確認:
  - 最近の論文タイトル 2-3 件が本人の研究と一致するか
  - affiliation 履歴が本人の経歴と一致するか
  - 共著者 list の top 5 が知り合いか
- **不一致を発見した場合**: `inspire_id: null` に戻し、`inspire_profile.txt` を削除、`collaborators.yaml` の該当 entry の `notes` に homonym 訂正経緯を記録する (実事例あり: 2026-04-14 に subscriber 1 名の homonym 誤同定を訂正)
- **どうしても BAI が特定できない場合**: `inspire_id: null` のまま運用。scorer は `interest_profile.txt` のみを使う (精度は少し落ちるが誤同定リスクはゼロ)

## 変更履歴

- 2026-04-14 作成。`arxiv-digest` の複数 user profile で Discord 数値 ID が public config.yaml に直書きされていた leak を根本原因まで遡った結果として、identity-in-config カテゴリを独立規約として分離。事例記録は owner の private layer の leak-incidents 記録の 2026-04-14 entry (ε + β 類型、force-push 修正)
