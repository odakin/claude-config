# 機密情報を含む git リポの設計パターン

> **English version**: [sensitive-repo-patterns.md](sensitive-repo-patterns.md)

特定組織・特定インシデント・運用 IP・内部トポロジ等、**外部に漏らしたくないデータを git で管理したい** ケースの設計パターン集。具体的には:

- 職場や顧客先ネットワークの調査ノート (NAT 構造、到達可能エンドポイント等)
- 金融・会計データ
- 共同研究者 DB、共有してはいけない個人情報
- 運用アラートの postmortem に含まれる固有名詞
- 外部 SaaS の認証情報 (ただし鍵そのものは別途 secret manager 推奨)

git-crypt 等の暗号化ツールの**使い方**は [git-crypt-guide.ja.md](git-crypt-guide.ja.md) を参照。本文書はその**一段上の設計判断**、つまり「何を・どこに・どういう形で置けば、暗号化の外で情報が漏れないか」のパターン集である。

実際の実装経験から抽出したものだが、汎用的に適用できるよう抽象化してある。

---

## <a id="part-1-public-surface"></a>Part 1: 暗号化の "外" を意識する

### <a id="pattern-1-1"></a>パターン 1-1: 暗号化は中身だけ。それ以外は全部見える

git-crypt (及び類似ツール) が守るのは**ファイルの中身**だけ。以下は**全て平文のまま git 履歴に残り**、private repo でも collaborator 招待や誤 public 化で露出しうる:

| 公開される情報 | 具体例 |
|---|---|
| ファイル名・ディレクトリ構造 | `notes/tokyo-office-a.md` のような slug が組織名を示唆 |
| commit message | `"Investigate intermittent VPN failures at Tokyo office"` |
| commit author・email・timestamp | 内部のタイムゾーン・勤務時間帯が推定可能 |
| `.gitattributes` の filter パターンとコメント | 「なぜここを暗号化しているか」の理由自体が運用情報 |
| `.gitignore` | 「こういうログファイルがある」といったインフラ痕跡 |
| リポ名・description・topics | GitHub の repo metadata |
| リポの存在そのもの | collaborator や API が一覧できる |
| ブランチ名 | `feature/customer-X-incident-response` など |
| tag 名 | 同上 |

**含意**: ファイル中身以外の全ての要素を**「公開面 (public surface)」**として明示的に設計する必要がある。

### <a id="pattern-1-2"></a>パターン 1-2: 公開面のフルリストを持つ

リポを作るとき、以下を全て洗い出して「これ公開して大丈夫か?」を 1 つずつ確認する:

```
□ repo name
□ repo description
□ repo topics
□ branch names (main / feature branches)
□ tag names
□ file/directory names (git ls-tree -r HEAD --name-only で列挙)
□ commit messages (git log --all --pretty=format:"%s%n%b")
□ commit authors (git log --pretty=format:"%an %ae")
□ .gitattributes の内容
□ .gitignore の内容
□ 平文として残すその他ファイル (README 等)
```

実装者の感覚では 3-4 項目で止まりがちだが、公開面は 10 項目以上ある。チェックリストを持つほうが漏れにくい。

---

## <a id="part-2-encryption"></a>Part 2: 暗号化の設定

### <a id="pattern-2-1"></a>パターン 2-1: Default-encrypt を第一選択に

暗号化対象を allow-list 方式で書くと、後でファイルを追加したときに `.gitattributes` 更新を忘れて**平文で push してしまう**事故が構造的に起きる。代わりに default-encrypt パターンを使う:

```gitattributes
* filter=git-crypt diff=git-crypt
.gitattributes !filter !diff
.gitignore !filter !diff
README.md !filter !diff
```

**利点**:

1. **Secure by default**: 新規ファイルは何もしなくても暗号化される。人間の規律に依存しない
2. **情報量が最小**: 「3 ファイルだけ plain、他は全部暗号化」という事実しか漏らさない
3. **監査が楽**: plain 側は 3 ファイルしかないので、leak scan の対象が絞れる
4. **コメント不要**: allow-list 方式では「なぜここを暗号化するか」のコメントを書きたくなるが、そのコメント自体が leak 源になる。default-encrypt では不要

### <a id="pattern-2-2"></a>パターン 2-2: `.gitattributes` と `.gitignore` は構造的に平文

- `.gitattributes`: git-crypt が「どのファイルを暗号化するか」を決めるために読む必要がある → 暗号化すると chicken-and-egg で破綻 → **必ず平文**
- `.gitignore`: 一般的に平文で OK。中身が汎用的 (`.DS_Store`, `*.log` 等) なら leak なし。ただし実在サーバー名やカスタムツール名を含める場合は注意

これらが平文であることを**前提として受け入れ**、中身を最小化・汎用化する。コメントは削除。

### <a id="pattern-2-3"></a>パターン 2-3: コメントは leak 源

`.gitattributes` にコメントを書くと、そのコメントが leak する:

```gitattributes
# ❌ BAD: これ自体が leak 情報
# 顧客 A の機密データは encrypted 側
customer_a/** filter=git-crypt diff=git-crypt
# SESSION.md は高頻度更新で固有名混入のリスクが高いので暗号化
SESSION.md filter=git-crypt diff=git-crypt
```

「高頻度更新で固有名混入のリスクが高い」というメタ情報から、reader は「このリポには固有名を含む機密情報が入っている」と推測できてしまう。

```gitattributes
# ✅ GOOD: コメントなし、default-encrypt
* filter=git-crypt diff=git-crypt
.gitattributes !filter !diff
.gitignore !filter !diff
README.md !filter !diff
```

---

## <a id="part-3-minimize"></a>Part 3: 公開面の最小化

### <a id="pattern-3-1"></a>パターン 3-1: slug 設計 — 識別情報をファイル名に入れない

複数の機密対象 (顧客・組織・環境・インシデント) を 1 リポで扱うとき、対象識別名をファイル名に入れたくなる。しかし git-crypt はファイル名を暗号化しないので、**ツリー構造だけで内部が推定可能**になる。

```
❌ BAD                        ✅ GOOD
notes/                        notes/
├── acme-corp.md              ├── a.md
├── tokyo-branch.md           ├── b.md
├── customer-xyz-2026-q1.md   ├── c.md
└── INDEX.md                  └── INDEX.md    (← 暗号化側)
```

**slug → 実名のマッピングは暗号化された INDEX ファイル 1 つに集約**する。slug 自体は単一文字の連番 (`a`, `b`, ...) か、意味を持たない識別子 (`n1`, `env3` 等) にする。意味のある略語 (`ac`, `tok`, `bnk`) は組合せで特定されうるので避ける。

### <a id="pattern-3-2"></a>パターン 3-2: commit message は汎用ラベルのみ

commit message は**永続に git log に残る**。後から rewrite しても GitHub の pack/reflog に痕跡が残る可能性がある。**具体的な環境・組織・調査結果・観測事実を書かない**:

```
❌ BAD
    "Investigate NAT traversal failure at Acme's Tokyo office"
    "Add finding: their firewall blocks UDP 3478 but allows 443/TLS"
    "Update customer-xyz contact info after Q1 meeting"

✅ GOOD
    "Add note"
    "Update note"
    "Refine skeleton"
    "Reorganize"
    "Update meta"
```

**中身の変更の詳細は、暗号化されているファイル内部 (例えばそのノート自体か `SESSION.md`) に書く**。commit message には「ノートを追加した/更新した」という操作種別だけを残す。

変更が複数ある場合も、具体を出さない汎用ラベルで統一する。これは「何を commit したか分からなくなる」トレードオフを生むが、中身の変更履歴はファイル内部のセクション追記で残せる。公開面の簡潔さを優先する。

### <a id="pattern-3-3"></a>パターン 3-3: 平文 README を構造的に守る

clone 直後の reader (別マシンの自分、新規 collaborator) のために、**unlock 方法を伝える最小限の README** が必要。しかし README は平文なので、そこに書いた内容は全て公開される。

**問題**: README は時間経過とともに "ちょっとだけ context を足す" の繰り返しで drift する。「この repo の目的は…」「過去の調査で…」と書き足されていき、いつの間にか公開されるべきでない情報が混入する。

**解決**: README の役割を**固定**し、**構造的制約**を機械で検査する:

1. **役割固定**: README は「unlock 手順だけ」と宣言する。warning コメントで "他の内容はここに書くな" と明示
2. **size cap**: 例えば 800 バイト以下。drift が物理的に不可能な上限を設ける
3. **ASCII only**: 日本語や非 ASCII 文字を全部禁止 (日本語の固有名詞を物理的に排除)
4. **IP pattern block**: IPv4/IPv6 dotted quad のパターンを検出して reject
5. **FQDN allowlist**: `github.com` 等の汎用ドメインのみ許可、それ以外は reject
6. **URL スキーム allowlist**: `https?://` もホスト部が allowlist に入ったもののみ許可

これらを pre-commit hook として実装し、違反があれば commit を reject する。hook script **本体は暗号化側に置く** (script 中の allowlist や条件ロジック自体が leak 源になるのを防ぐため)。インストールは clone 後の初期セットアップの一部として行う。

**重要**: hook は guardrail (ガードレール) であって壁ではない。`git commit --no-verify` で bypass 可能。しかし bypass 操作は物理的に自覚的な行為 (`--no-verify` をタイプする必要がある) なので、reflex レベルの事故は防げる。

**例**: 筆者が実際に使っている hook の構造:

```bash
#!/bin/bash
# Enforces structural constraints on README.md
set -e

f="$(git rev-parse --show-toplevel)/README.md"

fail() { echo "pre-commit FAIL: $1" >&2; exit 1; }

# (1) Size cap
[ "$(wc -c < "$f")" -le 800 ] || fail "README.md exceeds 800-byte cap"

# (2) ASCII only (portable: count non-ASCII bytes)
nonascii=$(LC_ALL=C tr -d '\000-\177' < "$f" | wc -c | tr -d ' ')
[ "$nonascii" -eq 0 ] || fail "README.md contains non-ASCII"

# (3) No IPv4 dotted quad
grep -qE '[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}' "$f" \
  && fail "README.md contains IP-like pattern"

# (4) FQDN allowlist
bad=$(grep -oE '[a-z0-9][a-z0-9.-]+\.(com|org|net|edu|io|dev)' "$f" \
  | sort -u | grep -vE '^(github\.com|example\.com)$' || true)
[ -z "$bad" ] || fail "README.md contains unapproved FQDN: $bad"

exit 0
```

**構造制約の設計思想**: 特定のキーワードを blacklist するのではなく、「サイズ・エンコーディング・パターン」の構造条件で検査する。blacklist 方式は (a) メンテナンスが要る、(b) blacklist 自体が leak 源になる、(c) 新しい固有名詞に追随できない、という問題がある。構造条件ならメンテナンス不要、leak しない、新規ケースも捕捉できる。

---

## <a id="part-4-bootstrap"></a>Part 4: ブートストラップの設計

### <a id="pattern-4-1"></a>パターン 4-1: 新マシンから zero → readable の経路を全て文書化

別の端末で初めてこのリポを開くときの手順を、**最初の authn からノート閲覧可能になるまで**、途切れなく書く。よくある抜け:

- clone した後 unlock に必要な鍵がどこから来るかが書かれていない
- 鍵が暗号化バックアップされている場合、そのパスフレーズが何で・どう伝達されるかが書かれていない
- hook 等の追加セットアップ手順が暗号化側にしか書かれておらず、unlock 前には読めない (chicken-and-egg)

**経路全体の例**:

```
[新マシン]
  1. git client + 暗号化ツール (git-crypt 等) をインストール
  2. GitHub 等への認証 (OAuth / SSH key)
  3. git clone <repo>                        ← ここまでは平文 README だけ見える
  4. 鍵ファイルを取得
     4a. Dropbox / 1Password 等から暗号化鍵を dl
     4b. out-of-band で受け取ったパスフレーズで復号
     4c. 復号した鍵を ~/.secrets/ 等に配置 (0600)
  5. git-crypt unlock ~/.secrets/<key>
  6. 暗号化側のファイル ( CLAUDE.md / setup script 等) が読める
  7. setup script を走らせて hooks をインストール
  8. ノートを読める
```

各ステップを**平文 README か別の cross-reference 可能な場所**に書く。暗号化側にだけ書いてあると 6 に到達できない reader が詰む。

### <a id="pattern-4-2"></a>パターン 4-2: "X は here ではない" と書いたら必ず "X は there" も書く

「個人鍵はこのファイルには記録しない」とだけ書いてあると、reader は「じゃあどこ?」と迷う。

```
❌ BAD
# 共有鍵マッピング
| project | key path |
|---|---|
| shared-repo-A | ~/.secrets/shared-a.key |

## 注意
- 個人鍵 ~/.secrets/personal.key はここには記録しない
```

```
✅ GOOD
## 注意
- 個人鍵 ~/.secrets/personal.key はここには記録しない。
  保管場所・バックアップ・復元手順は `secret-config/` の該当 doc を参照
```

negative pointer (X はここではない) と positive pointer (X はそこ) は必ずセットにする。**単独の negative pointer は reader を迷子にする antipattern**。

### <a id="pattern-4-3"></a>パターン 4-3: Cross-machine vs machine-local の軸を意識する

以下のものは**マシンローカル**になりがち:

- IDE や LLM アシスタントの memory / cache / workspace state
- OS の keychain / keyring
- 特定のパスに置いた設定ファイル (`~/.config/...`)
- 特定端末でのみ立ち上げたサービスの state

これらに「別マシンでも必要な情報」を保存してしまうと、別マシンでは見えない。再発防止策:

**ゲート質問を固定化する**: 何かを保存しようとした瞬間に、以下を問う:

> **「この情報、別の端末で新規セッションを開いたときに見えるか?」**

- 見えない → machine-local な保存先は不適切。git 同期された場所 (または同等のクラウド同期) に書く
- 見える (= machine-specific な事実、例: 特定 Mac の macOS 設定の癖) → machine-local で OK

このゲート質問を CLAUDE.md 等の常駐ドキュメント (AI アシスタント使用時は特に) に書いておき、**保存の reflex の瞬間に目に入る**ようにする。

---

## <a id="part-5-discipline"></a>Part 5: 運用規律

### <a id="pattern-5-1"></a>パターン 5-1: Forcing functions > discipline

人間 (あるいは AI) が繰り返し同じミスをする領域には、**規律 ("気をつけよう") ではなく構造的な forcing function を置く**。以下の事象が観察されたら規律の限界を疑う:

- 同じ種類のミスが 3 回以上起きている
- 「書くべきでない場所にうっかり書いてしまう」類のミス
- 直後にフィードバックがない (後で別マシンで露呈する等)

Forcing function の例:

| 対策 | 例 |
|---|---|
| Default を安全側にする | default-encrypt `.gitattributes` |
| pre-commit hook で機械的に検査 | 本文書 Part 3 の README hook |
| 常駐ドキュメント (LLM の system prompt 等) にゲート質問を書く | 「別マシンで見えるか?」 |
| 設計レベルで不可能にする | ファイル名に意味を持たせない slug 方式 |
| size cap / 上限 | README 800 バイト |

Forcing function 自身が leak 源にならないよう注意 (hook script 本体は暗号化側に置く等)。

### <a id="pattern-5-2"></a>パターン 5-2: 新規ルールと既存違反の同日 sweep

新しいルールを追加したとき、**既存の違反を audit して同日に修正する**。そうしないと:

- 「ルールを立てただけで既存違反は放置」という状態になる
- ルール自体の信頼性が落ちる
- 既存違反は時間経過で `ルールを知らない人` 扱いに昇格し、修正タイミングを失う

作業単位は「新規ルール設置 → 既存違反 audit → 一括移行 → commit」を 1 セットとする。例: 新規に「機密は暗号化側」ルールを作ったら、その場で既存の平文機密を grep して全部移動する。

### <a id="pattern-5-3"></a>パターン 5-3: 実装直後の 4 軸レビュー

実装 (新規作成・大規模変更) の直後に、以下の 4 軸で自己レビューする:

| 軸 | 内容 |
|---|---|
| **整合性** | 変更ファイル間で数値・用語・参照先・セクション名が一致しているか |
| **無矛盾性** | 既存ルール・テンプレートと矛盾していないか |
| **効率性** | 重複がないか、ファイルサイズ制約を超えていないか、drift 源になっていないか |
| **安全性** | 個人情報・認証情報・組織固有情報が公開領域に含まれていないか |

「実装して完了」ではなく、「実装 + 4 軸レビュー + 指摘事項の修正 = 1 単位」として扱う。レビューを省くと、上記 4 項目のいずれかに必ず drift が残る。

### <a id="pattern-5-4"></a>パターン 5-4: DESIGN と examples の co-aging

ルールを書いた文書 (DESIGN.md 等) に具体例を入れると、**後日ルールが refine されたときに example だけが古くなる** ことがある。古い example は新ルールから見ると「ルール違反」として読めてしまい、自己矛盾になる。

refinement を書き加えるときには、**古い section の example が新しい判断軸で valid か**を確認する。valid でなければ:

- 例を削除する、または
- 「この例は 2026-MM-DD に refine された。古い判断軸での分類として読むこと」と注記する、または
- 例を新しい判断軸に合わせて修正する

選択は DESIGN.md の性格 (time-series 記録か、現在の判断まとめか) による。time-series 性格なら注記、現在の判断まとめ性格なら修正。

---

## <a id="appendix-a-new-repo"></a>Appendix A: リポ新設時チェックリスト

```
□ repo name / description / topics に固有名詞を含めない
□ visibility を private にし、意図せず public 化されないよう設定
□ .gitattributes は default-encrypt パターン、コメントなし
□ .gitignore は汎用 OS/editor ignore のみ
□ README.md は unlock 手順だけ、size cap + 構造制約 hook
□ 平文で残すファイルは grep で固有名 0 ヒットを確認
□ 暗号化されているはずのファイルが実際に暗号化されていることを blob magic で確認
□ 初期 commit message は neutral
□ slug は単一文字連番 or neutral。INDEX は暗号化側
□ 新マシンでの clone → unlock → read までの手順が平文 README or 外部 doc に書かれている
□ 暗号化鍵のバックアップ・復元経路が end-to-end で書かれている
□ 4 軸レビュー (整合性・無矛盾性・効率性・安全性)
```

## <a id="appendix-b-new-note"></a>Appendix B: 新規ノート追加時チェックリスト

```
□ ノートのファイル名は既存の slug 命名規則に従う (新規環境なら INDEX も更新)
□ ノート内容から新しい blocking pattern が生まれていないか確認 (hook に反映が要るか)
□ commit message は "Add note" "Update note" 等の汎用ラベル
□ 平文 README / .gitattributes / .gitignore に影響がないことを確認
□ push 前に git-crypt status で当該ファイルが encrypted 表記であることを確認
```

## <a id="appendix-c-audit"></a>Appendix C: 定期監査チェックリスト

```
□ 平文ファイルの grep 監査: 固有名・IP・URL・非 ASCII が混入していないか
□ commit log の監査: 最新 N 件の commit message が neutral ラベルのみか
□ git tree の監査: ファイル名に新しい固有名が混入していないか
□ .gitattributes の drift: default-encrypt ルールが壊れていないか
□ 鍵バックアップの新鮮さ: Dropbox 等の暗号化鍵が最新か
□ hook の動作確認: README にダミー違反を入れて pre-commit が reject するか
□ 新マシンシミュレーション: git ls-remote で認証経路が通るか、clone dry-run
```

---

## 関連ドキュメント

- [git-crypt-guide.ja.md](git-crypt-guide.ja.md) — git-crypt 自体の使い方 (install, init, export-key, 別端末セットアップ)
- [convention-design-principles.md](convention-design-principles.md) — 規約設計のメタレベル原則

## 更新履歴

- **2026-04-09**: 初版。私的な暗号化ノートリポの実装経験から抽出したパターンを公開共有可能な形に汎化
