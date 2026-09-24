<!-- doc-meta
when: mail を YAML の台帳に記録する道具を入れる・使うとき + 既存の台帳に「読んだ位置」 の印を機械で足すとき + 未記録の返事を見張る検出器と記録の道具が同じ id を別々に読んでいると気づいたとき
category: mail
summary: mail の記録は thread 1 つに entry 1 つ、 id は道具 (scripts/record-reply.py) だけが書き、 読んだ位置の印 recorded_upto と索引 messages[] で「どこまで記録したか」 を明示する。 台帳の形 (索引の名前は相手 = 自分発は宛先、 下書きは message でない)・手順 (dry-run → --apply、 --check、 --migrate は message として記録した id だけ、 --relabel で索引を今の規則に引き直す)・失敗の向き (再 parse で戻す / 引けない thread を未記録に倒さない / cache は移行専用)・shim の作り方。
-->
# mail の記録台帳 — thread 単位の entry と、 読んだ位置の印

原理は [`email-surface-pattern.md#single-writer-thread-cursor`](email-surface-pattern.md#single-writer-thread-cursor) (書き手を道具 1 つにする)。 本 doc はその道具の**台帳の形・手順・失敗の向き・導入**の正本。 実装 = [`scripts/record-reply.py`](../scripts/record-reply.py) (engine)、 kernel = [`scripts/lib/recorded_ids.py`](../scripts/lib/recorded_ids.py) (記録済み id の書式) / [`scripts/lib/todo_thread_links.py`](../scripts/lib/todo_thread_links.py) (項目 → thread の link) / [`scripts/lib/gmail_read.py`](../scripts/lib/gmail_read.py) (Gmail の読み)。 個人の台帳の場所・account・自分の address は下の層の shim が渡す (engine に個人の値は無い)。

## <a id="schema"></a>1. 台帳の形

台帳 = `<root>/<ledger>/inbox/<YYYY-MM>.yaml` (mail の entry の列) と `<root>/<ledger>/todo/<id>.yaml` (1 entry 1 file。 旧 `<root>/<ledger>/TODO.yaml` が残っていればそれも読む、 読み方 = `scripts/lib/todo_ledger.py`) (項目の列)。 複数の台帳を 1 つの道具が読む (= 「1 つの台帳だけ grep して未記録と誤る」 を design-out)。

entry (`record-reply.py --schema` が出す 1 例が正本。 既存の house style の**部分集合** = 既存の読み手が今のまま読める):

| field | 意味 | 誰が書くか |
|---|---|---|
| `id` | `<記録した最初の message の日付>-<相手 / 用件>-<received \| sent>` | 道具 (中央の語は `--slug`) |
| `subject` / `from` / `to` / `cc` / `account` / `received` or `sent` | 最初に記録した message の素性 | 道具 |
| `threadId` / `messageId` | thread と最初の message (互換のため残す) | 道具 |
| `recorded_upto` | `"messageId:<hex> (<YYYY-MM-DD HH:MM>)"` = **読んだ位置の印**。 索引の最新と一致 | 道具だけ |
| `messages` | 1 通 1 行 `"mid:<hex> <日時> ← <差出人>"` / `"mid:<hex> <日時> → <宛先>"` = **機械が書く索引**。 名前は常に**相手** (← 相手発 = 差出人 / → 自分発 = 宛先。 自分を除いた最初の宛先 + ` +N`、 To が自分だけなら Cc → Bcc)。 本文・snippet は書かない。 下書き (Gmail の DRAFT) は message ではない = 載せない | 道具だけ |
| `category` | message の素性 (received / sent)。 案件の状態は項目側 | 道具 (既存 entry は触らない) |
| `related_todo` | 結ぶ項目の id (裸) | 道具 (無ければ足す) |
| `summary` | 3 行まで。 事実の正本 (金額・日付・決定) は書かず pointer だけ | 人 / agent |

印と索引の値は harvester の契約の中の書式 (`messageId:` / `mid:` 接頭辞) で書く = 読み手を変えない。 道具の出力の形は harvester の fixture に載せて固定する。

項目側 (TODO): `status_context` = 現在地の 1 欄 (道具が `"<日付> <相手> の返事 (<件名>) → 次: <一手>"` の形で**上書き**、 template は shim が渡す。 template は記録した最新の message の向きと「返事か」 で 4 つから選ぶ = 相手発の返事 `--ctx-reply` / 相手発で返事でない `--ctx-new-in` / 自分発の返信 `--ctx-sent` / 自分発で返信でない `--ctx-new-out`。 「返事か」 = 件名の先頭が転送 (`Fwd:` / `Fw:` / `転送:`、 ML の `[tag]` の後も) でなく、 thread のそれより前に反対側の message が在るか。 新規の送信・追送・転送を「返信」 と書かない。 較正 = 台帳の全索引行を Gmail の header と突き合わせた実測で、 In-Reply-To は送信の道具が付けない / 道具に渡した直前の自分の mail を指すので使えず、 参加者 〔宛先が前に書いたか〕 は ML 宛ての返信を外す)、 `updated` = 今日、 `--status` があれば `status` (enum は shim が渡す)、 `email_ref` が無ければ `"threadId:<id>"` の 1 行。 notes には決定・事実・根拠だけを書き、 日付つきの進捗行を足さない (= 台帳が log になって肥大しない。 履歴は版管理)。

## <a id="procedure"></a>2. 手順

1. **dry-run** (既定): `record-reply.py <項目 id | threadId | messageId | entry id>` → thread の全 message を「この entry に在る / 他所で記録済み / 未記録」 に分けて出し、 未記録の本文 (引用行を除く) と書く予定の差分を見せる。 項目 → thread は 3 経路 (cross_ref の inbox 参照 / email_ref / related_todo の逆引き) を読む。
2. **--apply**: 台帳の月 file の home entry (結ぶ項目に link する最新の entry) に足す or 新規に作る (`--slug` か `--id`)、 結ぶ項目の現在地を `--next` で上書き。 書くのはこの 2 file だけ。 案件の正本・calendar・mail の label / 既読は書かない。
3. **--check**: 全 entry の印と索引の整合 (印の id が索引にある / 印 = 索引の最新 / 日付順 / round-trip)。 `印 ≠ 最新` は loud に出る側の失敗 (silent な抑制ではない)。
4. **--migrate <ledger>** (既存分): 印と索引を**追記**する。 索引に書くのは entry が **message として**記録した id (top-level messageId ∪ 全 string の `messageId:` / `mid:`) と一致する message だけ。 threadId と同値の root message は載せない (threadId は thread の記録であって root を読んだ記録ではない。 載せると message 専用の読み手の集合が変わる = 実測)。 散文は 1 字も変えず、 threadId / related_todo も足さない。 `--remigrate` は印のある entry の規則に外れる root の行だけ外す。 移行の前後で読み手の出力が変わらないことを実データで確かめてから commit する。
5. **--relabel <ledger>** (索引の書き方を変えたとき): 既存の索引の向きと相手を今の規則で Gmail から引き直す。 id と日時は元の行のまま、 下書きを記録していた行は外して印が指していれば残る最新の行へ戻す。 Gmail に無い id の行・並列 session が書いた直後の行はそのまま。 索引と印以外の field は変えない (再 parse で検証)。 冪等、 cache を使わない (下書きが後で送られたことを隠すため)。 索引の名前は id から毎回引き直せる = 規則を変えたらもう一度流せばよい。

## <a id="failure-modes"></a>3. 失敗の向き

- **書いた後に再 parse して検証、 外れたら元の text に戻す** (entry 数 / 対象 entry の field / round-trip = 書いた id が harvester で拾われる)。 exit 3 = 検査不能・故障、 exit 1 = 違反 (enum 外・id 未定・項目が無い) と分ける ([`#failure-exit-equals-violation-exit`](../docs/convention-design-principles.md#failure-exit-equals-violation-exit))。
- **引けない thread は「未記録」 に倒さない** (auth / 404 / 一時失敗は「引けなかった」 と出す)。 項目の `email_ref` が返信の messageId だと threads.get は 404 になる = messages.get で本当の thread を引き直す。
- <a id="drafts-are-not-messages"></a>**下書きは message ではない**: threads.get は未送信の下書きも thread の message として返す。 除かないと、 記録の道具は下書きを「自分が送った」 と書き、 返事を見張る検出器は「最後は自分発 = 返事済み」 と読んで相手の未返信の mail を隠す (実測 = 下書きのまま止まった返信が記録済みになっていた)。 除くのは読む部品 1 か所 (`lib/gmail_read.normalize_messages`、 既定) = 同じ部品を使う検出器にも効く。 下書きかを見たい呼び手 (`--relabel`) だけ `include_drafts=True`。
- **cache は移行の一括読み専用**。 通常の記録は毎回 Gmail を引く (古い cache が並列 session の新着を隠す)。 移行でも entry が知っている id が cache の thread に無ければ引き直す。
- **並列 session と同じ file を触る**: 書く直前に file を読み直し、 commit は path 指定 (`git commit -- <path>`)。 ⚠️ 相手が path 指定で commit しても、 作業ツリーにあった自分の差分ごと入る ([`multi-session-coordination.md#staging-window-race`](multi-session-coordination.md#staging-window-race)) = 移行のような大きな差分は短い窓で書いて即 commit する。
- **label を書く側の展開範囲は狭く保つ**: 記録済み id の読み手 (検出器) は全 string を読んでよいが、 mail に label を書く同期 script は id を持つ field だけを読む。 散文の引用まで thread 展開すると open 項目が引いた thread が全部「処理中」 になる (実測)。

## <a id="adoption"></a>4. 導入 (shim の作り方)

下の層に同名の shim を置き、 個人の値を option で渡して engine を `os.execv` する (= [`check-script-layering.py`](../scripts/check-script-layering.py) が shim と認める形)。 渡すもの: `--root` / `--ledger` (複数) / `--accounts` (試す順、 先頭 = 既定) / `--creds-dir` / `--owner-token` (自分発の判定) / `--status-enum` / `--category-in` `--category-out` / `--ctx-reply` `--ctx-sent` `--ctx-new-in` `--ctx-new-out` (現在地の template、 §1) / `--tz` / `--cache-dir` / `--month-header`。 shim の `--selftest` は配線の canary (台帳 dir の存在 / enum の parity / 層1 の file) を見てから engine の selftest を回す。 読み手の検出器は `lib/recorded_ids.py` を import し、 その一覧と delegation 検査を shim 側の selftest に持たせる ([`email-surface-pattern.md#recorded-id-notation`](email-surface-pattern.md#recorded-id-notation))。
