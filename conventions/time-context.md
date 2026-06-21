# Time context — currentDate anchor 規律

Claude は session 開始時に `# currentDate` context を持っているが、 multi-turn / multi-day session で user 発話の「今日 / 明日 / 今夜 / 明朝」 等の時刻 deictic 表現を、 **会話の流れで暗黙に旧 frame (= 「前ターンの仮想 today」) で解釈する reflex failure** を起こすことがある。

> 本 file は時刻 **frame** に関する 2 つの規律を扱う: **(1) currentDate anchor**（以下、 user 発話の deictic を currentDate で再翻訳）と **(2) タイムゾーン跨ぎの日付照合**（末尾、 別 TZ で記録/表示された date を変換せず比較しない）。 両者は「時刻の frame を expose せずに結論へ飛ぶ」 同族の失敗。

## 規律

**1.** Claude (= 私) は user 発話の時刻 deictic 表現を解釈する際、 **必ず currentDate を起算点**として再翻訳する。 「会話の流れ」 「前ターンの仮想 today」 「session 開始時に想定した today」 等の暗黙 frame で解釈しない。

**2.** 「今日 / 明日 / 昨日 / 今夜 / 明朝 / 明後日 / 先日 / 翌日 / 今週 / 来週 / 先週 / today / tomorrow / yesterday / tonight / last week / next week / in N days / N days ago」 等の表現を user が使ったとき、 chat 応答で **何月何日 (曜日) に対応するか明示**する。 暗黙に解釈して進めない。

**3.** session 開始時に必ず currentDate を意識する。 `# currentDate` context を blanket statement として読み流さず、 user 発話の時刻 deictic を読む瞬間に **明示的に currentDate を再参照**する reflex を持つ。

## 設計理由 (= 2026-05-19→20 RCA)

ある session で、 currentDate = 2026-05-20 だったが、 Claude (= 私) は前ターンの user 発話「今日はもう帰るけど、 あした相手にメール書こう」 を 5/19 frame で受け取り、 「明日 = 5/20、 明朝の draft 着手で十分」 等と発話した。 真実は currentDate = 5/20 で「今日 = 5/20、 明日 = 5/21」、 時刻 frame が 1 日ずれていた。 その締切メールの〆切は実は 5/20 (= 今日) で 切迫していたのを user 指摘「もうその明日や」 で発覚。

これは「単一観察 (= 単一情報源の null / positive) を、 その frame を expose しないまま結論に変換する」 という一般的な failure trait の **時刻 domain での現れ**: 「user 発話の『明日』」 という単一観察 (= 言語表現) を、 currentDate context を bypass して「会話流れ」 で解釈 (= cell 埋め)、 実際の時刻 anchor (= currentDate) を expose せず暗黙化。 「不確実性を expose か隠すか」 の問いで「隠す」 を選んだ assertion。

## 設計史: 機械的 enforcement の段階的調整 (2026-05-20)

本規律 §1-3 を wording (= 散文の指示) で書いても reflex で skip される risk (= aspirational instruction risk) があるため、 機械的 enforcement layer の hook 化を試行。 同日に 3 段階で調整:

### Stage 1: UserPromptSubmit + SessionStart 両 hook 試行 (3c0e6f6)
`hooks/currentdate-anchor.py` で UserPromptSubmit + SessionStart の両 event を hook 化。 UserPromptSubmit は prompt に時刻 deictic 表現が含まれていたら currentDate + relative dates を inject する設計、 false positive 許容方針で広めの pattern。

### Stage 2: 全 hook 退役 (e97eef6)
user 指摘で全退役:
- false positive 許容方針 (= 「明日香」 等の地名で偶発 hit でも実害低い) は **Claude 視点のみ評価で user 視点を欠いていた**
- system reminder は **user の chat UI にも表示される** (= 私の発話「Claude が 1 回多く見るだけ」 は誤り、 user も毎回見る)
- false positive のコスト分布: Claude 1 / user 1 で対称
- 毎回 inject されると「狼少年」 効果で機械的 enforcement の effectiveness 自体が劣化

### Stage 3: SessionStart のみ復活 (commit TBD)
user 判断 (= 「セッションのはじめに今がいつかを確認する、 というのは自動化しても良い気がする」)。 UserPromptSubmit と SessionStart の性質差で cost-benefit が逆転:

| | UserPromptSubmit | SessionStart |
|---|---|---|
| fire 頻度 | user prompt 毎 (多数回) | session 起動時 1 回 |
| user UI 汚染 | 毎ターン累積 → 深刻 | 1 回、 起動 phase の期待情報 |
| false positive コスト | 「明日香」 等で multiplier | trigger 不問 = false positive 概念なし |
| 「狼少年」 効果 | 高 | 低 |
| 救えるケース | session 内全時点 | new session 起動時のみ |
| 救えないケース | (なし) | multi-day session 中の day change |

SessionStart hook は session 起動時 1 回だけ fire、 user UI 汚染は許容範囲。 multi-day session 中の day change は救えないが、 これは規律 §3 (= user 発話読時に currentDate を明示的再参照する reflex) で対処。

### メタ規律: 機械的 enforcement の cost 分布

- 機械的 enforcement layer は cost 分布を確認しないと user 側に押し付けが発生する。 「false positive 許容 = 実害低い」 と評価する前に、 inject 内容が user の chat UI / context window に乗ることを意識する
- 同じ hook でも fire 頻度が違えば cost-benefit が大きく変わる (= UserPromptSubmit vs SessionStart の差)。 fire 頻度を含めた設計判断が必要

## 日付の照合: タイムゾーンを跨ぐ前に必ず変換する (= 別 frame の date を変換せず比較しない)

別々の時間 frame で記録 / 表示された日付どうしを、 **変換せずに突き合わせて「ズレている / 存在しない」 と結論しない**。 ローカル時刻で記録された日付 (= イベントの現地開催日 等) と、 別タイムゾーンで表示される日付 (= JST 表示のカレンダー 等) は最大 1 日ずれる (= 東のタイムゾーンほど日付が先行する。 夜の出来事は東側では翌日になりやすい)。 二つの dataset の date を比べる前に、 必ず同一タイムゾーンに正規化する。

### 典型の罠 = 幽霊の不一致 / 不在

「source X に M 月 D 日の項目が無い → だから別ソースの M 月 D 日の項目は誤り」 のような **absence / mismatch 主張**で起きやすい。 X が現地日付・もう一方が別 TZ 表示だと、 同一の実体が X では前日 (or 翌日) に載っているだけなのに「無い」 「ズレている」 に見える。 これは本 file 冒頭の currentDate anchor 失敗と同族 = 「単一観察を、 その frame (= ここでは TZ) を expose しないまま結論に変換する」 失敗の時刻 domain 版。 変換という安価な検証を回さずに飛んだ assertion。

### reflex

- date を跨 dataset で照合する前に、 各 date が **どの frame か (現地 / UTC / 表示先 TZ)** を 1 つずつ言語化し、 同一 frame に正規化してから比べる。
- 「片方に無い / ズレている」 を「実在しない / 誤り」 に変換する前に、 **±1 日 (= TZ ズレの最大幅) を必ず確認**する。 一致を主張するときも同様に変換してから。
- 「夜の出来事 → 東の TZ では翌日」 を既定で疑う。

実例: 現地開催日で記録した試合データと JST 表示のカレンダーを突き合わせ、 現地 22:00 = JST 翌日 13:00 のキックオフを「その JST 日付に試合が無い」 と現地日付のまま誤読し、 正しいカレンダーを「誤り」 と flag した誤検知が起きた。 真因は現地日付を JST と混同しただけの変換漏れ。 データセットごとに「date はどの TZ 基準か」 を header / schema に明記しておくと、 この種の混同を構造的に防げる。

## 関連

- 一般 failure trait「単一情報源の観察を、 その frame を expose せず結論に変換する」 の時刻 domain instance (= 本 file「設計理由」 節参照)
- `claude-config/hooks/currentdate-anchor.py` (= SessionStart 専用 hook、 現行運用)
- `claude-config/hooks/pdf-read-fallback-nudge.sh` (= 別軸で機械的 enforcement が valid な前例、 PostToolUse Read で local error symptom にのみ反応するため user UI 汚染なし)
- 設計史 commit history: `git log --all -- hooks/currentdate-anchor.py conventions/time-context.md`
