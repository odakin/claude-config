<!-- doc-meta
when: ChatGPT app (Codex desktop) の task が 401 / auth error で止まったとき + 「Incorrect API key provided: sk-svcacct…」 が出たとき + Codex の hook が走らない・監査が untrusted と言うとき + app の更新で Codex の binary の path が変わったとき + 承認 CLI が「本人の発言が無い」 と言うとき + task の結果の要約が見当たらず最後の message が完了 gate への返事のとき + ChatGPT desktop の不具合を公式フィードバックへ送るとき
category: harness-core
summary: Codex desktop の auth error は client の鍵でなく backend 側のことが多い (= 手元に sk-svcacct は無い、 status page を見る、 再ログインしない) / 切り分けの読み方 (auth.json の auth_mode、 logs_2.sqlite の feedback_tags、 rollout の task_complete) / hook の信頼は hooks.json の定義 hash に束縛され TUI の /hooks で付け直す (agent は書かない) / app 同梱 binary の path は更新で動く = process から探す / 承認の引用元は生成文を除く / 結果が見当たらないときは rollout で gate の差し戻しの直前を読む / 公式フィードバックは操作ツールの制約とアプリの機能を分け、本人への貼付本文・添付範囲・送信識別子を引き継ぐ
-->
# Codex desktop の切り分け (auth error / hook 信頼 / binary の path)

ChatGPT app に同梱された Codex (desktop) で起きる、 手元では直せないもの・手元でしか直せないものを見分ける。 いずれも**読取だけ**で切り分けられる (auth / trust / config を agent が書き換える手順は無い)。

## <a id="auth-401-backend"></a>401「Incorrect API key provided: sk-svcacct…」 は backend 側

症状 = task が `unexpected status 401 Unauthorized: Incorrect API key provided: sk-svcacct***…, url: https://chatgpt.com/backend-api/codex/responses` で止まる。 **その service account key は手元のどこにも無い** (実測: shell env / launchd env / rc file / `~/.codex/auth.json` / `config.toml` / app の process 環境 / Codex の log 本体のどこにも無く、 出てくるのは server の返答の中だけ)。 ChatGPT ログインの client は access token を送っており、 backend が内部で使う鍵の側が拒否している = **OpenAI 側の障害** (同時刻の status page に Codex の incident が出ていた、 実測)。

切り分け (読むだけ、 値は出さない):

```bash
# 1. ログインの種類 (chatgpt = 正常。 OPENAI_API_KEY の欄が null か)
python3 -c "import json,os;d=json.load(open(os.path.expanduser('~/.codex/auth.json')));print(d.get('auth_mode'),d.get('OPENAI_API_KEY') is None,d.get('last_refresh'))"
# 2. env に鍵が混ざっていないか (login shell と launchd の両方)
zsh -lic 'echo ${OPENAI_API_KEY:+set}'; launchctl getenv OPENAI_API_KEY
# 3. Codex 自身の log: その turn の auth_mode と、 refresh の成否
#    (~/.codex/logs_2.sqlite の logs.feedback_log_body、 auth_mode="Chatgpt" / auth_env_openai_api_key_present=false / "Refreshing token" / auth_recovery_outcome)
# 4. rollout の task_complete.error に同じ文があるか (session を特定するだけ、 本文は転記しない)
```

判定: `auth_mode=chatgpt` ∧ env に鍵なし ∧ log の `auth_env_openai_api_key_present=false` ∧ 同じ turn で token refresh が成功している (`auth.json` の `last_refresh` がその時刻) なら手元は正常。 **やらないこと** = 再ログイン・`auth.json` や `config.toml` の手直し (原因でないので別の問題を作る)。 やること = status page を見て待ち、 同じ thread で送り直す。 app を再起動しても信頼・ログインは失われない (どちらも file に永続化されている)。

## <a id="hook-trust"></a>hook の信頼は定義の hash に束縛され、 落ちても黙っている

- 保存場所 = `~/.codex/config.toml` の `[hooks.state."<hooks.json の path>:<event>:<group>:<idx>"] trusted_hash`。 **hooks.json の定義 (command 文字列) が変わると、 その entry の信頼は落ちる** = hook は走らない (PreToolUse の gate は効いていても Stop の報告が効かない、 という片落ちが起きる)。 script の中身が変わっても定義が同じなら信頼は残る (実測)。
- 読み方 = `scripts/audit-codex-hook-runtime.py --codex auto` (app-server の `hooks/list` を読み、 必要な面 = PreToolUse の Bash / apply_patch + Stop が trusted か。 `not_armed` + `missing` / 検査不能 = exit 3)。 発火面への載せ方 (dashboard が監査して cache、 SessionStart は cache を読むだけ) は owner の層で配線する。
- 付け直しは本人の操作 = terminal で **app 同梱の binary** の TUI を起動 → 起動時の「Hooks can run outside the sandbox after you trust them」 の dialog か `/hooks` → trust all。 手順の正本 = [`codex/PARITY.md#restore-hook-trust`](../codex/PARITY.md#restore-hook-trust)。 **agent は信頼を書かない** (config の編集も trust の RPC も)。
- ⚠️ 動いている task は信頼を読み直さないことがある = 付けた後は新しい task で確かめる。 実 Stop の発火は監査 (構成) と別の証拠。

## <a id="binary-path-moves"></a>app 同梱 binary の path は更新で動く

`/Applications/ChatGPT.app/Contents/Resources/codex` が、 同じ日の app 更新で `…/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex` に移った (実測)。 path を決め打ちした script は `FileNotFoundError` = 検査不能になる。 探す順 = ① 動いている process (`pgrep -f 'Contents/MacOS/codex'`) ② 既知の bundle path (新 → 旧) ③ PATH の `codex` (npm 版は別物で版が古いことがある = 出力に注記)。 TUI を起動するときも同じ binary を使う (PATH の codex で信頼を付けても、 hash の算法や hooks.json の解釈が版で違いうる)。

## <a id="approval-source"></a>承認の引用元に生成文が混ざる

Codex の rollout では、 Stop hook の差し戻し文 (`<hook_prompt …>`) や環境の注入 (`<environment_context>`、 `<turn_aborted>` ほか) が **user role の message として**入る。 本人の発言を読む側 (承認 CLI の `--latest` / `--quote`) は、 先頭が tag 形の message を生成文とみなして除き、 本人の形だけを通す (実装 = `scripts/manuscript-claim-guard.py` の `human_text_segments`、 集計 = `scripts/approval-source-census.py` = 本文を出さず先頭の tag 名だけ数える)。 「本人の発言が無い」 と言われたら、 診断行の tag 名を見る (本文は出ない)。 規則の正本 = [`agent-rule-ownership.md`](agent-rule-ownership.md) の引用元の定義。

## <a id="result-before-completion-gate"></a>結果の要約が見当たらず、 最後の message が完了 gate への返事

症状 = task は終わっているのに、 画面の最後の message が「push してから終える」 型の差し戻しへの返事 (push できない理由の説明) で、 結果の要約が見当たらない。 表示が「作業中」 のまま残ることもある (実測。 表示の残りの原因が gate かは未確認)。

- **読み方**: rollout (`~/.codex/sessions/<年>/<月>/<日>/rollout-…jsonl`) を末尾から読む。 `<hook_prompt …>` で始まる user message の直前の agent message が本当の結果 (時刻を `task_complete` と並べる)。 成果物は commit・file に残っているので、 画面が壊れて見えても作り直さない。
- **原因の一つ**: 完了 gate ([`codex/hooks/session_touch.py`](../codex/hooks/session_touch.py) の `nudge`) は、 remote を持つ repo で HEAD が remote の先頭と違うと終了を 1 回差し戻す (remote が 0 本なら黙る)。 push しない仕事では満たせないので、 worker は理由を述べてもう 1 turn 使って終わる。 その turn も利用枠を食う。 push 先が手元の作業ツリーの checkout 中の branch (git が push を拒む = 手元の repo から clone した写し) なら、 gate は head を比べない。
- **予防**: push しない仕事を渡す写しで remote が手元の作業ツリー以外 (GitHub など) を指すなら、 渡す前に remote を外す (手順 = ai-collaboration [`physics-verification-cycle.md#cross-vendor-repo-copy`](../../ai-collaboration/conventions/physics-verification-cycle.md#cross-vendor-repo-copy) の 1)。

## <a id="official-feedback-handoff"></a>アプリ内の公式フィードバックと本人操作への引き継ぎ

**ツールの操作制限とアプリの機能を分けて記録する。** computer-use が対象アプリの操作を安全制限で拒否しても、アプリにフィードバック機能が存在するかは別に確かめる。拒否された操作経路を別の操作技術で迂回せず、公式資料と本人の画面から最小手順を用意する。

- **窓口を確認する**: [公式の slash command 一覧](https://learn.chatgpt.com/docs/reference/slash-commands) は ChatGPT desktop の `/feedback` を記載している。候補の表示は環境と権限に依存するため、実画面の候補・メニューも確かめる。CLI の同名コマンドの記憶を desktop の根拠にしない。
- **本人が操作できるときは本文を渡す**: 作成欄で `/` → フィードバック → 「バグ」 → 貼付本文 → 添付範囲の点検 → 送信。本人が「コピペをくれ」と言った後は本人が操作を持ち、agent は追加送信や並行操作を止める。
- **添付の既定値を確認する**: フォームの「診断ログ」「すべてのブラウザータブとブラウザーログ」が選択済みで表示される場合がある (実測)。本文だけの報告範囲なら、双方のチェックを外す手順を本文と一緒に渡す。状態を読み戻していない送信では、実際の添付内容を断定しない。既存セッション共有の選択とログの選択も別々に確認する。
- **報告本文を絞る**: 事象、期待する動作、時刻とタイムゾーン、該当メッセージの ID、エラー文、アプリ・OS の版、再現の有無と未確認範囲を書く。本人の観察、通知や返り値、agent の直接観察を分け、食い違いの原因を推測で埋めない。版番号の確認は app bundle の Info.plist と `sw_vers` などの限定した metadata から行う。
- **ヘルプ窓口へ引き継ぐ**: [公式サポートへの連絡方法](https://help.openai.com/ja-jp/articles/6614161-how-can-i-contact-support) は [Help Center](https://help.openai.com/) 右下のチャット吹き出しを案内している。記事の評価・翻訳へのフィードバックは問い合わせ窓口と分ける。認証を本人が行った browser と agent が先に開いた browser は、ログイン状態と会話の連続性を個別に確かめる。
- **送信状態を分ける**: [公式の Feedback and logs](https://learn.chatgpt.com/docs/reference/troubleshooting#feedback-and-logs) は、送信後にチームへ共有できる session ID を案内している。本文の入力、送信後の表示、ID の共有、担当の受付、調査開始、修正を別の状態として記録する。session ID を受付番号や新規 issue の番号と言い換えず、サポートが参照可能と回答した状態を調査開始の確約に広げない。
- **公開先への変更を確かめる**: サポートが公開 GitHub issue を提案しても、非公開窓口への送信承認を公開への承認に読み替えない。掲載する本文と識別子、公開先の製品との適合を確かめ、公開範囲への本人の明示指示を得る。

フォームの保持や承認状態の不整合の報告と、ルール内容が安全要件を満たすかの審査は別の論点として記録する。許可可能との断定や安全要件の解除を、UI の不具合報告に混ぜない。
