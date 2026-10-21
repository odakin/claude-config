<!-- doc-meta
when: session の終わりに、 その session (と委ねた agent・子 session・別 session) で得た知見・手順・使い捨ての script を正本へ上げ、 正本と参照・SESSION・TODO を整えて commit するとき (= 締めの sweep・仕上げ) + 締めの sweep を個人層の skill や定型の指示にするとき
category: harness-core
summary: 締めの sweep (仕上げ) の手順の正本 — 集める (会話記録・委ねた先の 5 つの口) → 層を決める (1 件を分けて置く・2 回目は仕組みに・公開層の境界) → 並列の締めと分担 → 正本と参照 → SESSION・TODO → commit → 横断と報告 (「残り」 に入れる前に会話で決まっていないかを確かめる)。 誰でも使える `/wrap` = skills/wrap (この doc を順に読ませる)、 個人層の同名の skill はそれを正本として指し、 道具の path と本人の決めごとだけを持つ (#personal-skill)。 層1 に置くものは claude-config に PR で出す (#upstream-pr)
-->
# 締めの sweep (仕上げ) — 知見を正本へ上げて整える手順

session の終わりに「全ての知見・手順・script をなるべく上の層に上げ、 session・正本・参照を整える」 作業の手順の正本。
各段の規則の本文はそれぞれの正本にあり、 ここは順番と入口だけを持つ (= 規則を複製しない)。
skill としての入口 = 誰でも使える `/wrap` ([`../skills/wrap/SKILL.md`](../skills/wrap/SKILL.md))、 個人の値の持ち方 = [#personal-skill](#personal-skill)。 層1 に置くものの出し方 = [#upstream-pr](#upstream-pr)。

以下の `<id8>` = その session の id の先頭 8 文字 (Claude Code の記録 file 名の uuid)、 道具の path は本 repo からの相対。

## <a id="scope"></a>0. 範囲を決める

- 対象 = **この session で起きたこと** (変えた file、 user の訂正、 分かった壊れ方、 その場で書いた一回きりの command・script、
  研究の知見、 設計の考え方 = 返事にしか無いものを含む。 文脈圧縮より前の分も含む = 0.3) **+ この session から委ねた先で得られたもの** (0.5)。
  それ以外の session の作業・未着手の案件には手を出さない。
- 事故の 3 条件 (文脈圧縮の直後・session の終わり・同じ file への並列作業) は、 公開層に owner や第三者の事実・未公表の結果が漏れやすい条件 (実測)。
  当たるなら、 **公開層に上げる文のうち事実を含みうるもの**を絞り、 残りは plan か TODO に積んで次の session に回す。
  これは漏洩の対策であって作業量の上限ではない = 技術の仕組み (道具・hook・検査) や手順の一般形を作ることは、 この条件でも絞らない。
  同じ時間帯に走っている他の締めとは、 1.5 の宣言で書く file を分ける。

## <a id="collect-from-transcript"></a>0.3 会話の全体から集める (文脈圧縮の前も)

文脈圧縮の後に手元にあるのは要約だけで、 圧縮より前の user の訂正・分かった壊れ方・打った command は要約から落ちていることがある。
会話記録 (transcript) は圧縮の後も全体が file に残っているので、 要約でなく記録から集める。 圧縮が起きていなければ、 user の発言と研究の中身は context で足りる。
**その場で書いた script は、 圧縮の有無に関わらず下の道具で一覧を出す** — context から思い出すと file に残らない形 (heredoc で interpreter に流した code・`-c` の code) を数え落とす (実測: file の script だけを数え、 結果を記録の根拠に使った heredoc の code を落とした)。

| 集めるもの | 引き方 |
|---|---|
| user の発言 (訂正・決定・依頼) | `python3 scripts/search-agent-transcripts.py --session <id8> --role user --regex .` (圧縮の前も含めて時刻順に全部) |
| その場で書いた script (file に書いたもの + heredoc・`-c` で流したもの) | `python3 scripts/session-scripts-report.py <id8>` = 1 本ずつ、 commit 済み (✅) / repo の中で未 commit (🟡) / repo の外 (⚠️) / 流しただけで file に無い (⚠️) を出す。 ✅ でないものは 1 本ずつ、 1 の表の [#evidence-scripts](#evidence-scripts) の行で決める |
| 根拠の無い検算の主張と先送り (返事と記録に書いた文) | `python3 scripts/session-claims-report.py <id8>` = 「手で確かめて一致」「独立に再現」 のうち根拠の file を指さない行 (A) と、 「次に〜とき」「後で」 のうち carrier を指さない行 (B)。 誤検出は出るので 1 行ずつ読み、 A は 1 の表の [#unbacked-checks](#unbacked-checks)、 B は 3 の [#deferrals](#deferrals) で決める |
| 打った command・commit | `python3 scripts/search-agent-transcripts.py --session <id8> --tool-runs --regex '<語>'` (例 = `git commit`。 2 回以上打った command は 1 の表の「再利用できる script」 の候補) |
| agent の報告 | 0.5 の表の 1 行目 |
| 研究の中身 | 会話を頭から読み、 返事に書いた計算結果・導出・読み・見積もり・否定的な結果・「確かめていない」 の一覧と、 agent の報告の検算済み・未検証の一覧を 1 件ずつ拾う (返事にしか無いものは session が終わると消える) |
| 考え方 (メタの知見) | 同じく会話を頭から読み、 返事に書いた比較・判断の理由・捨てた案とその理由・壊れ方の推論 (なぜ起きたか) と、 user が述べた考え方・好みを拾う。 user の分は言葉のまま |

- 拾った user の訂正は、 1 の表の「user の訂正」 の行どおり、 訂正された規則の文を記録にある user の言葉で言い直す。
- <a id="numbers-not-recorded"></a>**締めの道具の 🔢 の行は、 研究の中身の行の入力にする** — `session-scripts-report.py` と Codex の inventory が、 実行出力と記録を照合した候補。拾い方・探す記録・丸め・解釈の限界の正本 = [`scripts/lib/output_numbers.py`](../scripts/lib/output_numbers.py) 冒頭。
  1 件ずつ、 note に書く (数値を出した code も根拠として隣に置く) か、 書かない理由 (置き換えた後の値が記録にある、 形式の確かめだけ) を報告に書く。
  向きは `session-claims-report.py` の逆 (あちらは記録に書いた主張に根拠の code が無いもの、 こちらは code が出した数値が記録に無いもの) = 両方を回す。
  code が「保存済み (✅)」 でも、 その code が出した数値を記録に書いたとは限らない (実測: code は残したのに、 code が出した計算結果を note に書かずに締めた)。

## <a id="collect-from-delegates"></a>0.5 委ねた先から集める (agent・子 session・別 session への依頼)

委ねた先の報告は user に見えず、 委ねた側が拾わないとどこにも残らない。 5 つの口を全部見る (委ねられた側として引き受けた依頼も含む)。

| 口 | 見る場所 |
|---|---|
| この session の agent (subagent、 前景も background も) | **context にあっても** `python3 scripts/subagent-reports.py <id8> --max-chars 0` で記録から引き直す。 出るもの = 受け渡しの報告の全部 (再開した agent は再開のたびに 1 本 = 最後の 1 本だけ読むと前の回の発見が落ちる) と、 その agent が書いた file の一覧 (= 「二重に上げない」 の照合と上げ漏れの点検に使う)。 0 件 = agent を使っていない、 見た dir も出る |
| この session が共有の掲示板に出した依頼 (子 session・別 vendor の agent・動いている別 session) | 掲示板の道具 (engine = `ai-collaboration/board/board.py`、 契約 = `ai-collaboration/board/CONTRACT.md`) の `inbox --sync` の検収待ち・返事 → `show --thread <id>` で提出物。 検収待ちは先に検収 (accept / revise) する |
| この session が worker として引き受けた依頼 | 同じ `inbox --sync` で、 引き受けた request を全部 `submit` したか (成果物の path + commit)。 出していなければ出し、 出せないなら理由を note に書く |
| Bash から起こした worker (headless の `claude -p` / `codex exec` と、 Codex アプリに出る起動の道具 `codex-app-launch.py start` / `continue` = 掲示板がこの道具で起こした Codex の worker も。 封じた sandbox の盲検 reviewer を含む) | `python3 scripts/headless-worker-reports.py <id8> --max-chars 0` で起動を記録から数え上げる (他の口には現れない)。 実行位置・注入記録・起動の出力の thread id を持つ候補と、 引用や未対応構文の文字列候補は別の件数 = 文字列候補は元の tool call を確認する。 出るもの = 起動ごとの作業 dir・model・effort、 記録の約束の根拠、 作業 dir の成果物 (HANDOFF・結果・教訓候補) の本文、 worker が書いた script の一覧、 worker 自身の会話記録の場所 (Codex アプリの起動は thread の rollout)。 起動の道具の起動文には記録の約束が自動では入らない = 起動文 file か sandbox の AGENTS.md に書いてあるかを見る。 sandbox なら受領がまだかを確かめ (`ai-collaboration/scripts/make-review-sandbox.py collect` → `inspect-review-sandbox.py receipt`)、 走らせ直した回 (同じ dir に起動が 2 件以上、 `continue` を含む) は全部の回を見る |
| file や token で受け渡す子 (掲示板に出さない区分の依頼) | spec に書いた決まった path の成果物と、 受領の印 (個人層の受け渡しの道具) |

拾ったものの扱い:

- **報告は検証前の主張** — 正本 (特に層1) に書く前に、 報告が指す commit・file・出力を 1 回見て裏を取る。 裏が取れないものは「未確認」 と書いて queue。
- **子がすでに上げたものは二重に上げない** — 子の repo の `git log` を先に見る。 子の hoist が公開層の境界 (1 の ⚠️) を破っていたら直す。
- <a id="live-child-hoists-own-findings"></a>**まだ動いている子の file には触らず、 子の発見は子の締めで上げさせる** (並列作業 = 事故の条件)。 親は子の報告・提出物に書かれた手順・壊れ方・規則を、 自分で正本 (特に層1) に上げない。
  上げる前の検証に要るもの (子がその場で書いた code・試した経路・数値の出どころ) は子の会話記録にしか無く、 親が 0.3 の道具を自分の id で回しても出ない (実測: 親が子の報告から規則を先に層1 に上げた後、 子の締めで、 子が使い捨ての code で済ませていた読み方に既存の道具があり、 その道具が壊れていたことと、 根拠の code が file に無かったことが見つかった)。
  親の持ち場は 2 つ: (1) 検収 (accept) の時点で、 報告の主張を再現できる command で 1 回裏を取る ([`multi-session-coordination.md#review-handoff`](multi-session-coordination.md#review-handoff)) (2) 子の締めの後に、 発見が正本に上がったかを子の commit で確かめる (上がっていなければ子に 1 行頼む)。
  相手に届く経路 (`SendMessage` など) があれば「終わったら締めを」 と 1 行頼み、 無ければ queue。 子がもう居ない (落ちた・閉じた) ときだけ、 親が子の記録を引いて (`search-agent-transcripts.py <request id か role id> --role any`、 `session-scripts-report.py <子の id8>`) 自分で上げる。
- **機密の区分を引き継ぐ** — 掲示板に出さない区分の依頼・機密フォルダの成果は中身を上げない (公開層へは方法だけ。 区分の正本 = 掲示板の契約 `ai-collaboration/board/CONTRACT.md` の Source-classification gate)。
- 子 session の transcript は `search-agent-transcripts.py <request id か role id> --role any` で引ける (報告に書かれなかった壊れ方・user の訂正を拾うとき)。 この session の agent の記録も `--session <id8> --role any '<語>'` で引ける (agent の発言は `assistant(agent)`、 親が渡した指示は `parent` = `--role user` には入らない)。
- ⚠️ **agent の「考え中」 は記録に中身が残らない** (実測: すべて空) = agent が考えたこと (捨てた案・途中で気づいた壊れ方・確かめていないこと) は、 報告か成果物に書かれた分しか後から引けない。 **書かせるのは委ねる瞬間** (締めの時点では agent はもう考え終わっている): Agent tool への委任は hook [`delegation-record-clause.py`](../hooks/delegation-record-clause.py) が指示の末尾に約束の段を自動で足し、 掲示板の依頼と別 session への依頼は spec に書く。 headless の起動は hook [`headless-record-clause-nudge.py`](../hooks/headless-record-clause-nudge.py) の自動注入経路と sandbox の HANDOFF 要件を確かめる ([`multi-session-coordination.md#worker-record-clause`](multi-session-coordination.md#worker-record-clause))。 締めでは報告と成果物のその段 (捨てた案・途中の発見・未検証) を読み、 1 の表で置き場所を決める。

## <a id="any-os"></a>0.9 どの OS でも同じに動かす

- 集める道具は全部 Python (標準 library だけ) なので、 macOS・Linux・Windows (Git Bash / PowerShell) で同じ command が通る。
  shell の glob・`find`・`sed -i` のような OS で振る舞いが違う書き方を、 この手順や skill に足さない。
- `python3` が動かないとき: Windows は Store の偽物が「Python」 とだけ出して成功で終わる → `py -3` で同じ command ([`windows-msys.md#python3-missing-store-stub`](windows-msys.md#python3-missing-store-stub))。
  Mac で終了値 69 なら Xcode のライセンス未同意 ([`shell-env.md#system-python3-is-xcode-gated`](shell-env.md#system-python3-is-xcode-gated))。
- skill を link でなく copy で置く環境 (Windows など) では、 repo の skill を直しても今の session は古い copy を読んでいることがある。
  疑いがあれば repo の SKILL.md とこの doc を直接読む (copy は次の session 開始で作り直される作りにしておく)。

## <a id="codex"></a>0.95 Codex で回すとき

明示的に選んだ個人層の正本skillをCodexにも登録し、この手順を参照する。手順の写しは作らない。
登録名がwrapの場合、アプリの `/wrap` skill選択、`$wrap`、個人層の自然文triggerから同じ正本skillへ入る。slash selectorの画面描画は利用環境で別に確認する。
配置と不足の検出は、選択済みpersonal layerの `codex/skills.json` と層1のCodex installer・SessionStart・auditが持つ。
技術上の正本 = [`../codex/PARITY.md#wrap-workflow-integration`](../codex/PARITY.md#wrap-workflow-integration)。

| 口 | Codexで行うこと |
|---|---|
| 0.3の会話・道具・変更file | SessionStartで渡された**完全なsession ID**を使い、`python3 scripts/codex-wrap-inventory.py <full-id> --section messages --max-chars 0` と `--section commands` を読む。長い1件は `--call-id <id> --max-chars 0`。利用者向けに公開された `reasoning.summary` も回収し、要約が提供されない場合を明示する。非公開の内部思考・raw content・暗号化された思考本文は回収しない。userMessageという搬送上のラベルを本人の承認とは扱わない |
| 0.5のnative/hosted subagent、headless worker | 同じ道具の `--section workers --max-chars 0`。再開した回の報告も全件。APIで結び付くnative子と、worker側hookの観測したturn・Claudeログ範囲を読む。型の不明・履歴の不在・ephemeral・環境が消された起動はUNAVAILABLEを確認し、元のcommand出力と明示された成果物も読む。0件と同一視しない |
| hostedのcollaboration tool | 利用可能なら `collaboration.list_agents` でこの親のtreeを照合する。native hookの発火を仮定せず、委ねるpromptに最初から記録条項を入れる。報告が現在のcontextに無ければ、inventoryのagentThreadIdでnative readerへ、または記録したtool input/resultを確認する。回収不能は理由を残す |
| 掲示板 | `--agent codex --session <native-id>` に加え、inventoryのboard routeが示すこのsessionで使ったrole aliasもinbox/showで同期する。閉じた依頼を未処理へ戻さず、提出・検収を別々に確かめる |
| 別sessionのapp tool | inventoryのother-session routeにある作成・fork・送信の結果から、実際のthreadId/hostIdで `read_thread` 等を使う。clientThreadIdの段階は未解決として追う。先行するforkの写しを今回の発見に数えない |
| token方式 | inventoryにあるこのsessionの `--record` / tokenだけを0.5の道具で照合する。他sessionのmarkerを消費しない |

- `--section summary` / `--section commands` の 🔢 も、 [0.3 の数値の候補](#numbers-not-recorded)として研究の中身の拾い出しに使う。
- 委ねるpromptには3項目を最初から入れる。Codexのnative子とCodex環境を引き継ぐheadless子にはworker側hookも渡す。
  親のCLIをrunnerで包んで許可判定を変える方式は使わない。通常のCLI入力を保ち、hookを止めるflagや環境の消去がある場合は
  到達を仮定せず記録・報告から確かめる。実装と機械別の限界は上のPARITYへ。
- worker観測を回収して正本へ記録した後に、`codex-wrap-inventory.py <full-id> --mark-collected <記録先またはcommit>`。
  `--prune-collected` は回収済みのmetadataだけを保存期間後に整理する。未回収のものは残す。
- inventoryはCodexのsandbox (workspace-write) の中では動かない: 起動するapp-serverが `CODEX_HOME` に状態を書けず、起動直後に終わる (実測)。inventoryのcommandは最初からsandboxの外での実行 (承認を求める実行) で回す。その場合の失敗には、道具が原因と直し方を出す。
- APIが使えない場合は `search-agent-transcripts.py --agent codex --session <id>` と `--tool-runs` を補助にする。
  Claude専用readerの0件をCodexの不在証明にしない。未確認の口を明記する。
- 掲示板から来た作業で保護対象の候補ができたら、対象・差分・影響をこのchatでまとめて提示し、本人の具体的な裁定を使う。
  案内文・他agentの引用・「続けて」等を、まだ見せていない候補の承認として代用しない。承認の照合規則は変更しない。
- 個人overlayや宣言を編集したMacでも、installerのrefreshを同じturnで当てる。pullを待つ手順は残さない。

## <a id="placement"></a>1. 何をどの層へ

1 件ずつ、 4 層のゲートで置き場所を決める (正本 = [`../docs/personal-layer.md`](../docs/personal-layer.md))。
表の「個人層」 の具体的な file (作業の規律・文体・文献台帳・経路台帳・Office の運用) は、 個人層の入口 (CLAUDE.md の読み込み必須の表) から辿る = skill に一覧を写さない (写すと入口の表と食い違う)。

| 見つけたもの | 置き場所 |
|---|---|
| 誰にでも効く手順・道具の壊れ方・一般則 | 層1 `conventions/` (AI 協働の検証系は `ai-collaboration/`)。 壊れ方のエラー文が決まっているなら、 その文を [`hooks/known-errors.json`](../hooks/known-errors.json) にも 1 件足す (次に同じエラーが出た瞬間に節が出る = [`debugging-discipline.md#known-error-lookup`](debugging-discipline.md#known-error-lookup)) |
| 規約・仕組みの設計の考え方 (なぜその形にしたか、 効かなかった形とその理由) | 層1 [`../docs/convention-design-principles.md`](../docs/convention-design-principles.md) (節を足したら同じ dir の `convention-design-principles.index.yaml` に slug)。 個人の作業の規律は個人層 |
| 個人の流儀・個人の事実・machine 別の差 | 個人層 (該当の規約 file)。 user が述べた考え方・好み (研究の趣味・文体を含む) も該当の規約 file に言葉のまま |
| その project の決定・手順 | その repo の DESIGN / CLAUDE / docs (判断の理由と捨てた案も = 返事にしか無い比較を残す) |
| 研究の中身 (計算結果・導出・物理の読み・見積もり・否定的な結果・検算した範囲と未検証の一覧・残る課題の評価) | その研究 project の repo の note (数値は出した script と出力を根拠として同じ repo に)。 **会話の返事にしか無いものを 1 件も残さない**。 確かめていない読みは「未導出」「未検算」 と書いて同じ note に。 user が「やらない」 と決めた検証も言葉のまま記録する。 note は repo の索引 (README) と DESIGN から指す。 **agent の読みと著者の判断を分ける** = 著者の判断は発言のまま note の判断の節に ([`manuscript-value-triage.md`](manuscript-value-triage.md))。 2 つ以上の project に効く結果は、 出た project の note を正本にして他方の索引から指す (写さない)。 公開層に上げるのは方法だけ |
| 研究の方法の教訓 (分野を問わない推論の罠・検算の手・記法の規律) | [`paper-audit.md`](paper-audit.md) (主張と推論の検査) / [`physics-notes.md`](physics-notes.md) (ノートの書き方) / `ai-collaboration/conventions/physics-verification-cycle.md` (検証の仕組み) の該当節。 方法だけ = 結果・数値・project 名を持ち込まない |
| 文献についての知見 (その論文が何を示したか、 受け止められ方、 どの project に効くか) | 個人層の文献台帳 |
| Office の様式・紙の書類で分かった壊れ方・訂正・窓口の指摘 | 一般形 = [`office-automation.md`](office-automation.md) (Office の罠) / [`form-case-pipeline.md`](form-case-pipeline.md) (様式の案件の仕組み)、 機械と運用の差 = 個人層、 様式ごとの規則 = 案件の instance の spec と規則の doc。 道具 (build・検査) で止められる形にできるなら、 文を足すより先にそうする |
| user の訂正 | 訂正された規則の文そのものを**言い直す** (追記して古い文と同居させない) |
| その場で 2 回以上打った command・使い捨て script | 再利用できる script にして正しい層の `scripts/` へ (冒頭に説明、 生成索引を作り直す) |
| <a id="evidence-scripts"></a>その場で書いた script で、 file として残っていないもの (0.3 の `session-scripts-report.py` の ✅ 以外) | 1 本ずつ決める: (a) **出力を記録・note・規約・報告の根拠に使った** (「実測: …」 と書いた、 数値を写した、 結論の理由にした) → 1 回きりでも、 その記録の隣に file として置き、 記録から指す (根拠の再現の手段が記録と一緒に残る)。 一時 dir から消えていたら (❌ もう無い) `python3 scripts/replay-session-scripts.py <id8> --out <記録の隣の dir> <名前>` で会話記録の Write / Edit から戻す (Bash で直した分は戻らない = 道具が印を出すので、 置く前に読んで直す) (b) 他でも使える → 上の行 (c) 根拠に使っていない一度きり (形式の確かめ・file を直すための置換) → 置かず、 報告に「置かない・理由」 を 1 行 |
| <a id="unbacked-checks"></a>検算・照合の主張で、 script も出力も無いもの (頭の中で計算して「一致」「再現」 と書いた) | 記録に残すなら、 その場で script にして回し、 記録の隣に置いて記録から指す (通らなければ主張を直す)。 手計算は記録の根拠にならない = 書いた本人にも後から再現できない。 置かないなら主張を記録と返事から消す。 書く瞬間の規則: 受領・検品の記録に「独立に確かめた」 と書く前に script を書く (実測: 受領の記録に手計算の検算を書き、 script にしたら道具の側の偽の失敗と本物の一致が分かれた) |
| agent・worker が書いた script (subagent の成果物、 sandbox の `checks/`・`scratch/`、 子 session の使い捨て) | 一覧を道具で出し (`subagent-reports.py` / `headless-worker-reports.py`)、 1 本ずつ決める: (a) その研究・案件に固有 → その project の repo に置き、 索引から指す。 独立な実装であること自体が証拠なので、 起票側の code に混ぜず元の形で残す (b) 分野や案件を問わず使える → 一般化して正しい層の `scripts/` へ (selftest をつけ、 元の script を動かして同じ値が出ることを確かめてから。 公開層へは下の ⚠️ の境界を当てる) (c) 一度きりで再現に要らない → 置かない、 と報告に書く。 worker の HANDOFF が各 script の汎用性を書いていれば、 判断の入力にする (検証前の主張として) |
| 外部 service の新しい経路 | 個人層の経路台帳 ([`machine-route-first.md`](machine-route-first.md)) |

- **「なるべく上層に」 = 1 件を分けて置く** — 仕組み・壊れ方・方法の一般形を上げられる一番上の層へ、 固有の事例 (名前・数値・日付) は下の層に残して一般形を指す。
  丸ごと 1 層に置かない (上へ丸ごとは漏洩、 下へ丸ごとは埋没)。 下の ⚠️ の「迷ったら書かない」 は事例の側にかかる。 一般形は境界を通る形に書いて上げる。
- <a id="protected-files-need-ruling"></a>**規則・検査・hook・設定の保護された file は、 締めの中でも本人の項目ごとの裁定が要る** — 直す前に候補の全文を一時 dir に作り、 diff を本人に見せ、 承認の発言を記録してから当てる (記録と適用の道具・判定の正本 = [`agent-rule-ownership.md`](agent-rule-ownership.md))。
  先に書いてから commit すると commit の gate で止まり、 同じ commit に入れた別の file も止まる (実測)。 下の [#upstream-pr](#upstream-pr) の「1 件ごとに聞かない」 はこの file には掛からない。
- **2 回目なら仕組みにするかを決める** — 同じ壊れ方・同じ訂正がこの session で 2 回目なら、 文を足して終えず、
  検出器・hook・script にするかを決める。 その場で作らないなら、 理由と一緒に plan か TODO に積む。

⚠️ **公開層 (層1・公開 repo) に書く 1 文ごとに境界を当てる** — 判定の問い =
「この一文から、 owner または特定の第三者について、 いつ・何を・何件・どうなったかが分かるか」。
分かるなら書かない (来歴は「実測」 とだけ)。 迷ったら書かない。 境界の全文 = [`../CLAUDE.md#owner-activity-facts`](../CLAUDE.md#owner-activity-facts) / [`#non-identifier-content-leak`](../CLAUDE.md#non-identifier-content-leak) / [`#third-party-facts`](../CLAUDE.md#third-party-facts)。
commit 前に `git diff --cached` を 1 回読み、 `scripts/check-activity-facts.py` (Tier E) の WARN 行を読む。

## <a id="concurrent"></a>1.5 同時に走る締めと分担する (掲示板の touch)

締めが同じ時間帯に何本も走ると、 同じ共有 file (入口の CLAUDE.md・生成索引・層1 の規約) で互いの hunk が混ざり、
同じ知見が別々の file に二重に上がる。 **書き始める前に、 書く file を掲示板に宣言する**。 先に宣言した側がその file を持つ
(一般則 = [`multi-session-coordination.md#concurrent-closing-sweeps`](multi-session-coordination.md#concurrent-closing-sweeps)、 道具 = 掲示板の engine の `touching` / `touch` / `untouch`)。

1. **他の締めを見る** — `board.py touching --sync --thread <その日の締めの thread>` で、 同じ知見を別の file に上げようとしている相手がいないか題の行を読む。
2. **宣言する** — 1 の表で決めた置き場所を全部 (再生成する索引・README・正本の登録簿も) `touch --path …` に並べ、 `--summary` に題を 1 行、
   `--session-name` に相手が message を送れるこの session の名前を書く。
   - 🟢 = 書いてよい。 🔴 = 先に宣言した締めが持っている。 その file には書かない:
     同じ知見なら自分では書かず、 足りない根拠だけを持ち主に渡す。
     別の知見なら `touching --path <file> --wait` を background で回し、 起きたら file を読み直してから書く
     (並列中の「まだ無い」 は数分で腐る = [`multi-session-coordination.md#absence-check-staleness`](multi-session-coordination.md#absence-check-staleness))。
   - 持ち主が居ない (落ちた session) なら待たない。 file を読み直し、 相手の未 commit の hunk が混ざっていれば
     [`multi-session-coordination.md#temp-index-commit`](multi-session-coordination.md#temp-index-commit) で自分の分だけを commit する。
   - 途中で書く file が増えたら、 書く前に同じ command で足す。
3. **手放す** — 4 の push の後に、 commit を `untouch --reference '<repo>@<commit>'` に並べて手放す。
   - 「次の持ち主 = X」 と出たら X に 1 行送る (掲示板は push しない)。
   - 「最後の 1 本」 と出たら、 その日の締め全員の分の横断を 1 回だけ回す。 生成物は clean な tree で `--check`
     ([`multi-session-coordination.md#regenerated-docs-foreign-untracked`](multi-session-coordination.md#regenerated-docs-foreign-untracked))、 壊れた link・消した語の残りを確かめる。

## <a id="sot-and-refs"></a>2. 正本と参照

- 同じ内容は 1 か所 (正本) にだけ書き、 他は pointer にする。 「正本は X」 と書いたら正本の登録簿に登録する (登録簿を持つ repo)。
- **正本を README・SESSION に置かない** — 正本の置き場所は CLAUDE.md / DESIGN.md / conventions / 台帳 / 案件の note / script の冒頭。
  README は入口の link か生成した索引、 SESSION は案件ごとの現在地 1〜2 行と正本への link だけ。
  「README / SESSION が正本」 と書いた行を見つけたら、 中身を正本へ移し、 その行は移した先を正本と書き直す
  (公開 repo の build / deploy の手順は README に利用者向けの写しを残してよいが、 正本は CLAUDE.md)。
  契約 = [`../CONVENTIONS.md#session-no-durable-record`](../CONVENTIONS.md#session-no-durable-record) / [`#readme-style`](../CONVENTIONS.md#readme-style)、
  gate に止められたときの直し方 = [`memory-file-slimming.md#session-shape-gate`](memory-file-slimming.md#session-shape-gate)。
- 節を移した・名前を変えたら、 その節を指す参照を同じ commit で直す。
- 生成物は手で直さず生成し直す。 手で書く file の一部だけが生成区画 (`AUTO-… BEGIN` と `END` の印で囲まれた区画) のときも同じで、 区画の中に足した文は次の作り直しで消える (実測 = 共有 repo に配る規則を区画に直接足して消えた)。 区画に入れたい規則は生成の元に足して作り直す: 本 repo に file を足した・doc-meta を変えたら `python3 scripts/generate-tree.py --write` (新しい file は `git add` の後) → `--check` が 0。 他の repo の生成索引も、 その repo の生成器で。
- 道具の振る舞いを変えたら、 その道具を説明している doc (repo の CLAUDE.md・使い方の節・層1 規約) を全部直す。 grep は関係 repo 全体に
  (Bash tool の素の `grep -r` は ignore された dir を飛ばす = `command grep -r`、 [`shell-env.md#bash-tool-grep-ignores-gitignore`](shell-env.md#bash-tool-grep-ignores-gitignore))。

## <a id="session-todo"></a>3. SESSION・TODO

- SESSION.md は案件ごとの現在地を**置き換える** (日付つきの節・commit hash・経緯を足さない。 中身の置き場所 = 2 の「正本を README・SESSION に置かない」)。
- 動いた TODO は現在地の欄を上書きし、 期限と status を実態に合わせる (自分の番が残るなら「待ち」 にしない)。
- 掲示板の依頼の状態 (誰の番か・閉じたか) を SESSION・入口の一覧・TODO に書く前も、 5 の報告と同じく `show --request <id> --sync` で読み直す (実測: 提出した数分後に相手が受け取って閉じていたのに、 手元の記憶から「相手の番」 と書いて commit し、 書き直しの commit が要った)。
- メールを送った・受けたなら記録の道具で記録する。
- <a id="deferrals"></a>この session が記録や返事に書いた先送り (「次に〜するとき」「後で」「推す = 〜 (次の機会に)」) は、 締めの中で今やるか、 期限つきの TODO・plan・掲示板の依頼に載せる。 記録の中の「次に〜とき」 は carrier ではない (次の session はその文を探さない)。 返事の中で自分に約束した先送り (「返事が来たら、 次にこの session で見たときに伝えます」) も同じで、 session は持ち主が閉じる = 待ちを運ぶのは session の外の carrier (新着を拾う surface・期限つき TODO) で、 返事ではその carrier を名指しする (実測)。 拾い方 = 0.3 の `session-claims-report.py` の B
- 一時 dir (scratchpad・`/tmp`) に置いた成果 (候補・証拠・出力) は、 残すなら repo に移して所在を正本に書き、 要らないなら消す (一時 dir は session の後にだれも見つけられない)。 個人情報を含む複製 (記入済みの様式・刷った PDF) は必ず消す。

## <a id="commit"></a>4. commit + push

- repo ごとに `git fetch` → behind 0 を確かめ、 **`git commit -- <自分の path>`** (他 session の staged を巻き込まない)。
  commit 前に `git diff -U0 -- <path> | grep -c '^@@'` で自分の分だけか数える ([`multi-session-coordination.md#staging-window-race`](multi-session-coordination.md#staging-window-race))。
- 自分が触っていない dirty file (credential・他 session の作業) は commit しない。
- push の後に 1.5 の 3 で手放す。

## <a id="report"></a>5. 横断 sweep と報告

- 最後の commit の後に 1 回、 error を見つけるつもりで横断を見る (変えた関数の他の呼び元、 消した語の残り、 壊れた link)。
  壊れた link は手書きの検査を書かず道具で見る: `python3 scripts/fix-md-links.py --base <作業ルート> --files <変えた md> --list` (0 件なら `missing target: 0`)。
- 最終 message に書くもの:
  - 何を・どこへ移したか (repo と file の link、 1 行ずつ。 出所 = この session / agent / 子 session を添える)
  - 研究の中身を扱った session なら、 拾った知見の件数と置いた note (会話にしか無かったものを何件記録したか)。 考え方 (0.3 の表の行) も同じく件数と置き場所
  - その場で書いた script の一覧 (0.3 の道具) の ✅ 以外 1 本ずつの扱い (置いた先か、 置かない理由 = 1 の [#evidence-scripts](#evidence-scripts))
  - `session-claims-report.py` の A (根拠の無い検算) と B (先送り) を 1 行ずつどうしたか (script にした先・消した・やった・載せた carrier)
  - 2 回目の壊れ方・訂正があれば、 仕組みにしたか、 しなかった理由と積んだ先
  - 委ねた先のうち、 まだ動いている・検収していない・裏が取れなかったもの。 掲示板の状態 (検収待ち・誰の番か) を書く直前に、 その request を `board.py show --request <id> --sync` で読み直す
    (手元の checkout と数分前の表示は古い。 並列の session が検収役を移している・検収を済ませていることがある = 古い状態のまま「本人の一言が要る」 と報告し、 要らない判断を求めた実測がある)
  - 見た範囲 / 見ていない範囲 (「完了」「✓ pass」 で締めない)
  - 今回は上げずに queue したもの (理由と置き場所)
  - 公開層に上げなかったもの (理由 = 1 の ⚠️ の境界のどれに当たるか)
  - 他の締めに譲った・待った file (1.5 の 🔴) と、 その中身を誰に渡したか
  - 規則の文書を変えたことを記録する検査が書くよう求めた行があれば、 そのまま ([`agent-rule-ownership.md#additive-and-free-zones`](agent-rule-ownership.md#additive-and-free-zones))
- ⚠️ <a id="leftovers-check"></a>**「残り」 に入れる前に、 その件がもう会話で決まっていないかを確かめる** — 「残り」 は今の状態 (済んでいない・送っていない) から組みがちで、
  そうすると会話の中で扱いが出ていた件まで未決として戻り、 「残りもぜんぶやって」 で実行に回る (実測 = agent が「しなくてよい」 と勧めた件を残りに入れ、 実行しかけた)。 1 件ずつ:
  1. **会話を引く** — その件についての user の言葉と、 agent の推奨とその後の user の反応を探す。 文脈圧縮の後は要約に残っていないことがあるので、 件の語で会話記録を引く (0.3 の道具)。
  2. **user が言葉で決めていた** → 残りに入れない。 決定として記録先 (その件の TODO など) に user の言葉のまま書く。
  3. **agent が勧め、 user が異を唱えずに次へ進んだ** → 推奨どおりに扱い、 残りには入れない。 報告では別枠に「推奨どおり〜 (違えば一言)」 と 1 行。
     記録には user の決定としてでなく「推奨・異論なし」 と書く (黙っていたことを user の言葉にしない)。
  4. **会話に出ていない** → 残りに入れる。 「残りを全部やって」 がかかるのはこの群だけ。
  - 予防 = 勧めた turn で、 その件の記録に推奨を書いておく (後の一覧を記録から組める)。 決定の書き方の一般則 = [`actor-attribution.md#decision-state-at-record-time`](actor-attribution.md#decision-state-at-record-time)。

## <a id="personal-skill"></a>`/wrap` skill — 誰でも使える版と、 個人の値

- claude-config は誰でも使える `/wrap` を [`../skills/wrap/SKILL.md`](../skills/wrap/SKILL.md) に持つ (本文 = 「この doc を 0 から 5 まで順に」 + 誰にでも同じ値 + [#upstream-pr](#upstream-pr))。
  配線 = [`../scripts/install-shared-skills.sh`](../scripts/install-shared-skills.sh) (Claude Code の `~/.claude/skills/` と Codex の `~/.codex/skills/` に置く。 macOS・Linux は symlink、 Windows は copy で、 元が変われば作り直す)。
  呼ぶのは `setup.sh`・pull の post-merge・個人層の session 開始の bootstrap (どれも [`../scripts/sync-hook-settings.sh`](../scripts/sync-hook-settings.sh) 経由) と Codex の [`../scripts/setup-codex.sh`](../scripts/setup-codex.sh) = 人が覚えて入れる手順は無い
- 個人層に同名の skill (`~/.claude/skills/wrap`、 Codex は個人層の `codex/skills.json` の宣言) を置くと、 そちらが起動する (配線の script は個人層・本人の skill を置き換えない)。
  その skill の本文は「手順の正本 = 誰でも使える版 (`skills/wrap/SKILL.md`) → この doc」 を指す 1 行と、 その人に固有の値だけを持つ:
  個人層の道具の path と引数 (どの掲示板・どの thread で宣言するか、 file 受け渡しの道具、 生成索引の生成器、 正本の登録簿)、 本人の決めごとのうち一般形を持たないもの (言葉のまま、 日付つき)。
  個人層の置き場所の一覧は持たない (= 1 の冒頭どおり入口から辿る)。
- 手順そのものを skill に写さない (2 か所が食い違う)。 手順を直すときはこの doc を直す。 個人の決めごとが誰にでも効く一般形を持つなら、 一般形をこの doc に置いて skill からは消す
  (本人が skill に置くよう言った言葉は残す)。 OS ごとの罠・Codex の入口と読み替え・合成 file の作り直しも 0.9 / 0.95 が持つ = skill に書かない。

## <a id="upstream-pr"></a>claude-config への改善案は PR で出す

1 の表で層1 (claude-config) に置くと決めたもの (誰にでも効く手順・道具の壊れ方・規約の穴・雛形の不足) は、 手元 (個人層・作業 repo) だけに置かず claude-config に入れる。
claude-config に push できない人は fork から PR を出す。 誰でも使える `/wrap` はこれを既定にしている = 1 件ごとに user に可否を聞かない (止めるのは user が止めたとき)。 保護された file (規則・検査・hook・設定) は、 [#protected-files-need-ruling](#protected-files-need-ruling) のとおり本人の裁定を先に取る。

1. **一般形にする** — 1 の ⚠️ の境界 (識別子・本人や第三者の活動の事実・未公開の中身・個人の path) を 1 文ずつ当てる。 PR の本文・diff・commit message・branch 名・commit の author は公開される。 author は GitHub の noreply (`git config user.email` が `@users.noreply.github.com` か確かめる)。 なぜ気づいたか (個人の事例) は自分の個人層・作業 repo の記録に残す
2. **1 PR = 1 つの改善** — 本文 = 何が困ったか (一般形)・何を変えたか・どう確かめたか
3. **確かめる** — claude-config の root で `bash scripts/run-all-checks.sh` を回し、 落ちた検査が自分の変更か既存か (main でも落ちるか) を本文に書く。 OS の違いが関わる変更は、 確かめた OS を書く (PR では Linux の CI = `.github/workflows/checks.yml` も回る)。 Windows・Codex の罠は [§0.9](#any-os) / [§0.95](#codex) とそこから辿る正本
4. **出す** — claude-config の clone で `gh repo fork --remote --remote-name fork` (fork が既にあれば不要) → branch を切る → `git push fork <branch>` → `gh pr create`。 push できる人 (所有者) は fork せず [4](#commit) の規則で直接 commit する
5. **報告** — 出した PR の link と要約を最終 message に書く
