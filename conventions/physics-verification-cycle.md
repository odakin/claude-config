<!-- doc-meta
when: 論文・研究ノートの主張を機械検査で守る体制を組むとき / 外部論文を検証読みするとき / 検証系 AI workflow (verify-to-learn・adversarial pass) を設計するとき / 検証 campaign の repo・ledger・spec・第二の目・繰り越しを整備するとき / 連続 outcome の rank-one POVM の極値性・joint 一意性を検証するとき
category: research-domain
summary: 物理主張の検証サイクル (= 生成 → 機械検査 → 独立した第二の目 → 人間の判断) — 主張ごとの機械 anchor / foil (negative control) / 検証 tier 宣言 / claim 3 状態 / verify-to-learn / 第二の目の独立性 / rubric 事前登録 / 止まる規律 / cross-vendor 盲検 (= 同系統 AI の N 実装一致は独立でない) / campaign 運用 (ledger schema・2 段階第二の目・👁 繰り越し・cadence gate・git 由来 stats・efficacy proxy) / 近似階層の妥当性は判断でなく計算 / 外部 AI 査読レポートの前提検証 pass / verify-to-learn campaign の実測 kernel (certificate ベース定性判定・正規化検査・無限次元 supp→range・問いと主張の refuted 分離・foil の前提・WLOG 分岐・連続 rank-one POVM の極値性→joint 一意性)。 数ヶ月の paper-anchored audit fleet 運用 + 2026-08 の散文主張 RCA + 2026-09 campaign からの hoist
-->
# 物理主張の検証サイクル (verification cycle)

> **位置づけと credit**: 本リポ維持者が自分の物理研究で運用している「主張を検査で守る」体制の一般則。 実 instance (個別 paper の audit script 群・claim ledger) は各 private paper repo に残置 (= kernel-up / instance-down)。 **命名・提示 form の一部 = 日高義将氏 (京都大学基礎物理学研究所) の公開講演「AI による理論物理研究の自動化」 (PPP2026、 2026-08)**: **verify-to-learn** の名と scratch 隔離の detail・**FCIR** (Fibered Claim IR = 原文/読み方/前提/根拠) の読み多義分析・「根拠がない時に止まる」「確かめられなかった項目を分かったことにしない」 の標語・integrity ≠ efficacy の評価 form・4 station の compact な図式化は同講演由来。 一方、 **実践の大半は当方の運用が講演に先行して独立に発達した収斂** (git 記録で確認済): 機械 anchor と各 station の実践 (2026-05 月〜)・foil (初出 2026-07-01)・外部論文の抽出 → 分類 → 1 件ずつ機械検査 → ledger の手順 (2026-08-08 の検証読みで運用)・検証 tier (同日)・claim 3 状態 (refuted 追跡 + 未検証 marker、 2026-06 月〜) — 講演はこれらに収斂の確認と一部の命名を与えた。 過剰帰属も過小帰属もしない (= credit も主張であり、 検証してから書く)。 本 doc は自前運用で incident-backed になった kernel のみを書く (借り物の未検証手法は書かない — 例: FCIR の台帳 form 自体は氏の実演でも効果判定不能と報告されており、 採らない)。

## <a id="cycle-shape"></a>1. サイクルの形 — 4 station + 「1 つでも fail したら進めない」

```
調べる・生成 (文献の選定と検証読み・計算・導出・散文)
  → 機械検査 (standing audit: 式・係数・引用・数値を決めた方法で確かめる)
  → 独立した第二の目 (別 pass / 別 session の AI が疑う: 抜け・飛躍・偽主張)
  → 人間の判断 (意味・価値・公表可否 — ここだけは人間が引き受ける)
```

- **gate**: 用意した検査に 1 つでも fail したら自動では先へ進まない (fix → 再測 ALL PASS が前提)。 検査を持たない対象を通すときは **「検査なしで通した」 を記録に残して**通す — 検査の不在が沈黙と区別できない状態を作らない ([`convention-design-principles.md#conditional-firing-visibility`](../docs/convention-design-principles.md#conditional-firing-visibility))。
- **構造的な非対称を知って配る**: standing 機械検査は「登録済みの主張」しか守れない — 新規に書かれた主張は、書かれてから anchor 化されるまで**構造的に無防備** (= latency 窓)。この窓を受け持つのが第二の目と手術時 sweep ([`paper-audit.md#relocation-rebinding-sweep`](paper-audit.md#relocation-rebinding-sweep))。「機械が 0 件捕捉」を能力欠如と誤診しない ([`convention-design-principles.md#detection-zero-location`](../docs/convention-design-principles.md#detection-zero-location))。

## <a id="machine-anchor-per-claim"></a>2. 主張ごとの機械 anchor — 安定した主張は audit script に固定する

**ルール:** 論文・ノートの機械検査可能な主張 (係数・恒等式・終端/非終端・rank・符号・引用式の転記) は、安定した時点で **1 claim-cluster = 1 audit script** に固定する。

- **docstring が検証内容の SoT** (verdict・gate 構成・chain of trust を script 自身に書く。 index 側 doc は pointer のみ = 復唱しない)。
- **ALL PASS gate を merge / pull ごとに再測** (前回の compile / audit 結果を流用しない — 共著 live 編集は push に巻き込まれる)。
- **主張文の隣に machine pointer comment** を置く (`% machine-verified: <script> <check-id>` の類) — 読者 (含む未来の自分) が「この文は検査済みか」を文の場所で判別できる。
- **散文の exactness 主張 (terminates / vanishes / to all orders / unique) は display 化してから anchor** — prose は隠す、式と機械は暴く (実例: 「対称側は終端する」という偽主張が、display 化 → 実計算の要求で即座に露呈した。 [`paper-audit.md#relocation-rebinding-sweep`](paper-audit.md#relocation-rebinding-sweep) class (e))。
- <a id="identifier-anchor-coverage"></a>**anchor の coverage は式・数値だけでなく identifier (人名・引用 ID・記号) にも張る** — 生成された identifier は流暢で、 SoT と突合されない限り権威を偽装する。 実測: 派生文書 (研究費調書) の parity gate が式と数値だけを anchor していた時、 事故はちょうど un-anchored の 3 class で 1 件ずつ起きた (名指しの誤帰属 / 被引用数の arXiv ID 取り違え / SoT に存在しない記号が図に 2 週間)。 帰属主張の一般則 = [`actor-attribution.md#claim-target-attribution`](actor-attribution.md#claim-target-attribution)。

**なぜ**: 検査は書いた瞬間の正しさでなく**将来の編集に対する正しさ**を守る。数ヶ月運用の実績 (該当 private paper repo、audit 20+ 本): 共著ノートの literal-copy 転記誤り (係数 2 ↔ −2、向き反転込み) を初稿レビューで即捕捉 / as-printed の最終恒等式が exact に −1 倍 (frame 順の swap が反対称部を flip、残差 4e-16) を機械が検出 / 人間と AI が両方誤った符号論争を一般接続 probe が裁定。

## <a id="foil-negative-control"></a>3. Foil (negative control) — 「検査に歯があること」を検査する

**ルール:** audit には**わざと壊した variant (foil)** を同梱し、foil が FAIL することを PASS 条件に含める。 sign foil (符号を反転して通らないこと) / swap foil (脚順・bracket 順を入れ替えて通らないこと) / 非不変 foil (対称性を破る入力で不変量検査が落ちること) / 正解を 1 箇所書き換えて検出されること。

**同伴する双子 = membership check (2026-09)**: foil は「間違った入力で落ちるか」 を見る。 対になる問いは **「紙面が実際に使う配位が、 検査した族に入っているか」**。 実例: vierbein のパラメータ化を 53 checks で守っていた audit が、 群関係だけを検査し λ を 1 通りしか sample していなかったため、 **論文が展開に使う平坦背景そのものがその族に入らない** (符号条件が det を反転させる) ことを一度も試していなかった。 検査は全 PASS、 死角は無傷。 → anchor には「この族に、 本文が使う具体配位が属する」 を 1 行の gate として入れる。

**なぜ**: foil のない検査は「常に PASS する検査」と区別が付かない (= vacuous pass)。実例: parity 検査の初版が anchor 消失で **vacuous pass していた**のを anchor 死活検査の追加で発見 / 係数検査は commutator-sign foil・non-Lorentz foil を同梱して初めて「その次数を本当に見ている」と言える。

## <a id="verification-tier"></a>4. 検証 tier の宣言 — 転記と検証を混同しない

**ルール:** 外部資料 (論文・ノート・スライド・写真) から取り込んだ式・数値には tier を明示する: **🔧 machine-verified** (独立に計算して一致) / **👁 目視転記のみ** (見て写した、検証はしていない) / **📄 OCR** (機械抽出、誤読リスク別枠)。 tier 未宣言の転記を「検証済み」と扱わない。

**なぜ**: 転記は正しさを運ばない。実例: 外部論文 6 本の読解ノートで tier 区別を強制した結果、🔧 化の過程で初稿の literal-copy 誤り 1 件が即捕捉された (👁 のままなら残っていた)。数値検証の一般則は [`scientific-computing.md#verify-independent-derivation`](scientific-computing.md#verify-independent-derivation) (= 一致合わせは検証でない) + [`#sympy-verify-transcript`](scientific-computing.md#sympy-verify-transcript)。

## <a id="claim-states"></a>5. Claim の 3 状態 — 確かめられなかった項目を分かったことにしない

**ルール:** 検証作業の出力は **verified / refuted / unverified の 3 状態**で ledger に残す。 unverified を結論の根拠に使わない。 sweep・audit の完了報告は「検査した範囲 / NOT 検査した範囲 / 確信境界」を明示し、「✓ 全部 OK」で終わらせない。

**なぜ**: 「検査した」の暗黙 scope 拡大が、単一情報源 null の結論飛躍と同型の事故を作る。 refuted の記録も消さない (= 何が落ちたかは検査資産。 [`convention-design-principles.md#errata-on-preserved-records`](../docs/convention-design-principles.md#errata-on-preserved-records))。

**成果物の拡張 — 「確かめ直せる材料」も研究成果**: 論文と並んで、 検証 record (audit script・check 結果・出典・**失敗と未解決**・人が判断した理由) を「次の人 / AI が確かめ直して続きを始められる形」 で repo に残す。 判断理由の残し方 = [`convention-design-principles.md#design-snapshot-operation`](../docs/convention-design-principles.md#design-snapshot-operation) (DESIGN.md snapshot 運用)。

## <a id="verify-to-learn"></a>6. Verify-to-learn — 外部論文の検証読み (名 = 日高氏講演。 手順自体は当方の検証読み運用が先行)

**ルール:** 外部論文を「使う」前提で読むときは、(1) 式・主張を item 化して抽出 → (2) 機械検査可能 (式・極限・数値・コード) と根拠追加が要る (散文主張) に分類 → (3) 機械検査可能分を 1 item ずつ独立導出で check → (4) 3 状態 ledger に記録、の順で読む。初回 run は**隔離した scratch ledger** で行い、本番の知識ベースへは verified のみ昇格させる。

- **他者の論文の誤り finding は default 非公開**: 検証で誤り (misprint・係数・式) を見つけたら、公開の前に (a) 自前の独立導出で refuted を確定 (b) 著者・管理元へ報告 (c) 先方の応答 / 訂正を経てから公開の順。 **(a) の「自前」 は人間を含む** — AI pass が何本一致しても (別 session・別ベンダー・機械 anchor 付きでも) それは「AI-refuted」 であって、 著者に伝える根拠にはならない。 owner が自分の手で反例・導出を確認して初めて (b) に進める (2026-09-06 owner 判断「自分で確認したわけじゃない、 AI のみ。 言うのは無理」 — 独立 3 pass で決着した定理レベルの finding に対して)。 ledger の status は refuted のままでよいが、 対外発信の gate は別 (= 人間の独立確認)。 実務: 人間が 10-30 分で追える形 (反例を 1 頁、 使う定理は標準のもの 1-2 個) に worker が整えておくと、 この gate を通す cost が下がる。実例: 標準的参照文献の式の誤りを機械検証 → 報告 → 管理元が承認し web 版修正、の全 flow が通った。引用・再利用する側の防御は「既知 misprint の SoT (RETRACTIONS 相当) を repo に持ち、その式を引く前に必読」。
- 読み方の多義で真理値が変わる主張 (「N 大なら補正小」型) は、読みを 1 つに決める前に候補読みを列挙して各々の帰結を分ける — 強い結論は全候補読みで確認できた時だけ ([`paper-audit.md#claim-strength-three-tests`](paper-audit.md#claim-strength-three-tests) が自著側の同型)。

## <a id="independent-second-eye"></a>7. 独立した第二の目 — 自己検査は独立検証ではない

**ルール:** 重要な検証 (RCA・投稿前・誤り疑い) は**書いた pass と別の pass** に出す — 別 session の cold-eyes AI に、named error class + 反証 framing (「この主張を落とせ」) で渡す。書いた本人の self-check は同じ盲点を継ぐ (= 偽主張は書いた本人には毎回もっともらしく見える)。**相関した agent 同士の一致も独立検証ではない** (同 model class の 2 pass は誤りの相関を持ち得る — 独立性の最終保証は機械検査と人間)。

**なぜ**: 実測で、生成 pass が見落とした同 class エラーを、同じ model の directed sweep pass が同日 6 件捕捉した — 独立性は model を替えることより **pass を分けて検査対象を named にする**ことから先に効く。handoff の機構 (spawn / token / 返送 spine) は [`multi-session-coordination.md`](multi-session-coordination.md)。 **別 session を立てただけでは目は冷えない** — 起票側の結論が cwd 祖先の CLAUDE.md・hook 注入・spec・原稿内の注記・repo 記録から流れ込む。 隔離の recipe = [`cold-eyes-isolation.md`](cold-eyes-isolation.md) (2026-09-02)。

<a id="cross-vendor-red-team"></a>**Cross-vendor red-team (2026-08 実測)**: 「pass 分離が先」には上限もある — ある共同研究で、同 model の生成 + self-check を通過して配布 PDF まで達した致命的誤り 2 件 (不公平な量子/古典比較・位相基準の取り違え 〔= 主観測量の 49% 変化が artifact〕) を、**別ベンダーの独立運用 AI に repo 一式を渡した敵役 pass** が 2 回とも捕捉した (2/2、 いずれも撤回の直接契機。 当事者の教訓記録 = 「外部 red-team は 2 回とも効いた。 自力では見つけられなかった」)。 機能した protocol: (i) 散文の主張でなく **repo 一式を渡す** — 機械 anchor (#machine-anchor-per-claim) があるから敵役は「完全再現 → それから壊す」 の順に入れる / (ii) 敵役 memo は暫定 verdict + scope 限定 (「効果そのものの否定ではない」) + 人間による数式再確認の推奨を明記 / (iii) **受け手は敵役の code を走らせず一から独立再実装して確認** (= 一致合わせは検証でない、 #verification-tier) / (iv) 受け入れ後、 自分の返信・代替案にもう 1 周敵役を回す (= 実測でここから自己訂正が 1 件出た)。 位置づけ: 別ベンダー pass は同 model 盲点の安価な decorrelation であって、 機械検査と人間の代替ではない (n=2 の観察で、 fresh-eyes・反証 framing との交絡は分離できていない)。

## <a id="rubric-before-run"></a>8. 評価基準は走らせる前に決める — 判定不能は判定不能と言う

**ルール:** 手法・対策の効果を主張したいなら、**評価基準 (指標・成功条件・判定不能条件) を実行前に事前登録**する。走らせた後に基準を選ぶと、どんな結果でも「効いた」ことにできる。基準を満たすデータが集まらない場合は「判定不能」と記録する — 記録の integrity (再現・保存一致) と手法の efficacy は別物で、前者の PASS を後者の証拠にしない (この峻別の評価 form = 日高氏講演の実演 2)。**成果物の存在も正しさの証拠にしない** — PDF ができたこと・審査を通ったことは物理・引用・新規性・再現性の証拠でない ([`convention-design-principles.md#acceptance-is-not-specification`](../docs/convention-design-principles.md#acceptance-is-not-specification))。改善が効くのは **AI 本体でなく手順と検査** — session を越えて persist するのはシステム改変のみ ([`convention-design-principles.md#agent-learning-illusion`](../docs/convention-design-principles.md#agent-learning-illusion))。

**なぜ**: 対策の多くは event が稀で統計が立たない (= 判定不能で終わる公算をあらかじめ書くのが誠実)。実例: 散文エラー対策の効果判定を「次の手術 event ≥2 回で捕捉半減、6 ヶ月で event <2 なら判定不能と記録」と事前登録した。

<a id="efficacy-proxy-receiver-side"></a>**検証 campaign の efficacy proxy は受領側が記入する (2026-09)**: 対照実験 (同じ論文を手法なしで読む) は高価なので、最も安い proxy = 「**起票者が事前に知らなかった finding の数**」を ledger の field (例: `novel_to_requester: true|false`) で数える。**書いた側 (worker) には記入させない** — 書いた本人が「新しい」と申告すると integrity 指標 (check PASS / foil FAIL) が efficacy に化ける (= write-time 自己記入の循環)。受領時に起票側が refuted / 新結果 item ごとに判定して埋め、集計は機械 (git 由来の所要時間・items/commit と同じ表に並べる)。限界も事前に書く: 起票者の「知らなかった」は主観 + 事後判定なので、傾向指標であって効果の証拠ではない。同じ理由で **所要時間は自己申告させず git timestamp から機械算出**する (初回 campaign で「≈ 6 時間」の自己申告 vs git 64 分の食い違いを実測)。

## <a id="stop-when-no-grounds"></a>9. 止まる規律 — 根拠がない時は進めず人間に渡す (標語 = 日高氏講演)

検証で根拠が足りない・読みが複数残る・仮説が決めきれない時は、**分かったことにして進めず、判定不能のまま人間の判断に送って止まる**。自動化の価値は走り続けることでなく、止まるべき所で止まること (= 「根拠がない時に止まる」)。散文の不確実性は「不確実性を expose する操作 (display 化・機械 probe・1 query 検証) を先に回す」が第一手。

## <a id="cross-vendor-blind-verification"></a>10. Cross-vendor 盲検 — 同系統 AI の N 実装一致は独立性が本物でない (2026-09)

同一系統の AI (同 vendor の別 session・別 model tier) による複数実装の一致は、 系統的な共通バイアス (同じ学習分布・同じ公式の癖) を排除しない。 決定的にしたい数値主張には**別 vendor の AI に盲検で第 3 実装**をさせる。 recipe:

1. **盲検 spec を書く**: 物理の問題設定 (模型・規約・入力・観測値) だけを渡し、 **自分たちの実装も答えの数表も見せない** (clean directory で実行させ、 repo を読めなくする)。 同 vendor の別 session でも同じ隔離が要り、 その流入口 6 つと sandbox の切り方は [`cold-eyes-isolation.md`](cold-eyes-isolation.md)。
2. **最も不定性の大きい要素は指定せず自選させる**: 例 = horizon-matching 公式。 「標準公式を自分で選び、 出典と固有不定性を明記せよ」 と課すと、 公式選択の regime まで独立検証になる。
3. **一様 offset は物理でなく規約差の signature**: 突き合わせで全 scenario に共通の一定 offset が出たら、 差の値から規約の流儀差を同定する (例: (1/12)ln g_* = 0.39 の g_* 正規化差)。 同定できない offset だけが本物の不一致。
4. 検証者の「定式化への懸念」 も成果物として回収する — 盲検の第三者は依頼側の暗黙の前提 (例: 質量と potential の独立入力化) を独立に言い当てることがある。

§7 (独立した第二の目) の cross-vendor 深化。 起源 = 2026-09 private paper repo の e-folds 逆結合 finding (Claude 系 3 実装一致 → Codex 盲検で第 4 実装、 全点一致 + 規約差同定 + 暗黙前提の独立指摘)。

## <a id="approximation-tier-closure"></a>11. 近似階層の妥当性は判断でなく計算 — N 実装一致は「同じ理想化の中の一致」でしかない (2026-09)

複数の独立実装が一致しても、 全実装が**同じ近似階層** (leading order・同型の理想化・同じパッケージ公式) を共有していれば、 一致が保証するのは「その階層の中で正しい」 ことまで。 階層自体の誤差を「±N の係数不定性」 と仮置きして人間の判断に送る前に、 **理想化を 1 枚ずつ外した実装を 1 本作って誤差を計算に置換する**:

- 接続規約 (どこで phase を切り替えるか) → 系を通しで積分して規約自体を消す (物理連鎖から中間点が相殺する形に書く)
- 平均化仮定 (w̄ = const 等) → 平均前の系を解いて実効値を出力させる (仮定 → 計算値)
- パッケージ公式 → 保存則 (エントロピー等) の素の連鎖に展開する
- 摂動公式 → 高次項 + 少数点での exact 解 (mode 積分等) spot-check

仮置きの ±N が計算後に 1 桁小さい値に潰れることは珍しくない (起源事例: ±1–2 e-folds の仮置き → 計算値 +0.2)。 その場合、 残る softness は理論誤差から**入力の選択** (観測輪郭・データセット) に移動し、 人間 (共著者) の検証は「再導出」 から「物理設定の妥当性確認 + spot-check」 に軽量化される — これが検証依頼の縮小 ([`research-email.md #shrink-the-ask`](research-email.md#shrink-the-ask)) の計算版。

## <a id="external-ai-referee-premise-verification"></a>12. 外部 AI 査読レポートの前提検証 pass — 鵜呑みも防衛反射もしない (2026-09)

別 AI (別 vendor 可) に blind の cold review を書かせるのは §10 の実装として有効だが、 **受け取った report をそのまま改稿計画にしない**。 findings は改稿前に author 側で 1 回**前提検証 pass** を通す。 起源事例 (2026-09-01、 private paper repo): 15 findings の検証で、 本物の新規 catch 2 件 (パラメータ化の符号タイポ = 出版版まで遡る erratum 候補 / 候補項分類の反例 = audit fleet の coverage hole) と同時に、 過剰判定 4 件 (既存の qualifier を割り引かない refuted 判定) と blind ゆえの誤 unverified 2 件を検出した。

1. **Blind 査読の構造的盲点を知って読む**: 外部査読は原稿単体を読むため、 「紙面に根拠が無い」 (unverified) と 「主張が偽」 は正しく区別できても、 **author 側の機械 anchor (in-house で検証済みの事実) を知らない**。 unverified 判定の finding は 「主張を撤回する」 前に in-house anchor を確認する — 検証済みなら解は 「削除」 でなく 「掲載」 (起源事例: 対称性恒等式の全成分機械検証が in-house に既在し、 abstract の主張は真・紙面の提示だけが欠けていた)。
2. **診断カテゴリを混同しない**: 「枠組み・方程式の矛盾」 と 「叙述の過剰主張」 は別の病気で、 前者と誤診すると論文の再構成 (中心主張の変更) へ誘導される — 修正コストが桁で違う。 判定の問い = **「方程式を変えずに文だけ直して真になるか」**。 起源事例: bare action に許容項が残ることを受けた 「構造的不整合」 診断が、 著者の一言 (= その項が残ることこそ postulate の帰結) で 「叙述精密化」 に降格した。 検証 AI 自身もこの誤診をする (した) — 前提検証 pass は査読だけでなく**検証者の診断カテゴリ**も再判定の対象にする。
3. **前提検証は fan-out + verbatim 引用強制 + severity 再判定**: 1 finding = 1 agent で並列に、 (a) 原稿の該当箇所を **verbatim 引用**させる (report の行番号・要約を trust しない — 引用強制が 「premise が原稿に実在するか」 の機械的 gate になる) (b) 関連する in-house 機械 anchor・一次文献を読ませて counter-evidence を供給する (c) severity を fair / overstated / understated で**独立に再判定**させる。 disposition (受諾 / 部分受諾 / 却下) は検証結果を見て人間が決め、 finding ID で ledger に記録する (finding 本文の複製はしない)。

4. **自分が書いた handoff / spec も検証対象に入れる**: 前提検証 pass は「相手の主張」 を検証するよう設計されるので、 **検証者自身が実装者に渡した指示**が盲点になる。 実装者はそれを与件として読むため、 spec 内の誤りは原稿に直行する。 起源事例では handoff の「精密化 3 原則」 の 1 つが物理的に誤っており (既に bare action に対応項があるものを「ループ初生成」 と分類していた)、 実装者が一次資料と自前 note から気付いて訂正した — つまり**検証の向きが偶然逆流したから助かった**。 spec を渡す前に、 spec 中の物理主張を自前の機械 anchor に 1 度当てる。

5. **Blind report を freeze してから履歴を開く**: 同じ検証者に過去査読・author response・内部 TODO を最初から渡すと、再発検出と既知事項の追認が混ざる。第一 pass は対象原稿と一次資料だけで report を書き切り、hash と finding ID を固定する。第二 pass で raw の過去査読を照合して反復クラスターを作り、その後に内部 ledger を開いて provenance を分類する。起動規約などで先に内部情報が見えた場合は汚染を明記し、重要判定を fresh context で再現する。
6. **処置・確度・provenance を直交軸で持つ**: 一つの ✅/❌ に潰さず、(a) manuscript disposition = answered / partial / unanswered / withdrawn、(b) epistemic state = verified / refuted / unverified、(c) review provenance = strict-new payload / known / decisive extension、を別列にする。**withdrawn は answered ではない**。また in-house anchor で verified だが本文に証拠がない状態は、命題の refutation でなく manuscript-closure の欠落である。
7. **後日覆った finding は erratum で閉じる**: blind report の集計後に前提の飛躍や反例が見つかったら、元 report と上位 decision record の双方へ日付つき訂正を置く。監査証跡の番号や当時の件数を黙って書き換えず、「何を撤回し、どの finding に吸収し、何がなお残るか」を記録する。これで保存記録の再現性と current disposition を両立できる。
8. **決定的 finding は from-scratch の著者側 script で再導出してから採用する** (2026-09 実例): reviewer の script を再実行しても独立検証にならない。 別の近似 (matter-dominated envelope + 線形化質量項) で同じ結論 (線形成長 ≤ 数 e-fold vs 完了に必要な 20 超) が出た時点で採用し、 その script が書き直した主張の機械 anchor になる ([`scientific-computing.md#floquet-exact-background`](scientific-computing.md#floquet-exact-background))。 採用後の書き換えは「閾値 = regime の終わり」 の型 ([`paper-audit.md#threshold-is-not-regime-onset`](paper-audit.md#threshold-is-not-regime-onset))。

report 側の hygiene (hash-pinned reviewed_source / 行番号の有効範囲宣言 / findings の 3 状態 + 理由 tag / decision ledger の分離) は受け取る価値のある形式なので、 自分が review を書く側に回るときも踏襲する (§10 の記録規律と同じ)。

## <a id="definition-level-judge"></a>14. verify-to-learn の実測 kernel 追補 — 41 item campaign (2026-09) からの一般則

初回の本格 verify-to-learn (外部 2 論文 + 教科書応用の問い、 41 item = verified 31 / refuted 6 / unverified 4、 check 15 + foil 15。 実 instance は個人層の private 検証 repo) で、 §1-§9 に無かった kernel が 6 つ出た:

1. **定性判定は certificate、 量的値だけ solver** — 「間主観的か」 「極値か」 のような yes/no は、 局所 solver の最適値でなく、 **witness (非存在側は explicit dual certificate、 存在側は具体的構成) で判定**する。 solver に頼る量 (α の数値) と分け、 後者の外側 scan (状態 / 方向の格子) は evidence として confidence 境界に書く。 道具 = [`scripts/gpt_measurements.py`](../scripts/gpt_measurements.py)、 数値の recipe = [`scientific-computing.md#small-sdp-without-solver`](scientific-computing.md#small-sdp-without-solver)。
2. **恒等式検査が見えない typo を正規化検査が拾う** — 定理の構成式に符号 typo があっても、 その定理が主張する恒等式 (domain 上の確率再現) は両符号で成立することがある (余分な項が domain 上で期待値 0)。 「構成が測定であること (Σ = 1、 PSD)」 を恒等式とは**別 item** で必ず検査する。 実測: 統計だけ検査していたら見逃していた符号 typo を Σ = 1 の sympy 検査が捕捉。
3. **有限次元の直観は無限次元で「supp → range」 に変わる** — 「共通下界なし ⇔ supp の交わり自明」 は有限次元では正しく、 無限次元では ran(a^{1/2}) の交わりに置き換わる (Cauchy–Schwarz + Douglas の易しい向き、 文献不要の 10 行証明)。 supp は閉包なので稠密な operator range の対で破れる — **文献定理 (von Neumann の dom T ∩ dom U*TU = {0}) を引かず、 陽な対で 🔧 化できる**: L²(S¹) で a = Σe^{-2|n|}|eₙ⟩⟨eₙ| (平方根の値域 = 実解析クラス) と b = 弧の指示関数 P_I (値域 = L²(I))、 交わりは一致の定理で {0}、 閉 supp の交わりは L²(I)。 3-outcome POVM でも (a/2, d^{1/2}P_I d^{1/2}, d^{1/2}(1−P_I)d^{1/2}) で「平方根値域は pairwise 自明・閉 supp は重なる」 が起きる (2-outcome では不可能 = 可換性)。 無限次元版の item は有限次元 item と**別 tier**で扱い、 打ち切り (truncation) の数値を無限次元の evidence に使わない (compression の共通下界は元作用素の共通下界でない)。 道具 = `gpt_measurements.py` の `fourier_arc_gram` / `analytic_class_arc_povm` (docstring「Infinite-dimensional addendum」)。
4. **「問い」 の refuted と「論文の主張」 の refuted を集計で分ける** — 教科書側の問い (「この POVM は完全間主観的か」) が No に決着した item も ledger では refuted になる。 集計表と results の見出しで「論文の誤り N 件 / 問いの否定的決着 M 件」 と分けないと、 受け手が論文の誤り件数を誤読する。
5. **foil の前提も定理でなければならない** — 「decomposable な effect を使えば非 IS になるはず」 のような foil が、 実は定理でない前提に基づいていて UNEXPECTED PASS した (= foil が検査に歯が無いのではなく foil 自体が間違い)。 foil を書く時も「この壊し方で必ず落ちる」 の根拠を 1 行書く。 §3 の membership check の双子。
6. **証明の WLOG 分岐は機械で踏む** — LP が退化解 (λ, µ) = (1, 0) を返した瞬間に、 証明の「otherwise take λ = µ = ½」 が必要な分岐だと分かり、 その正当性 (max = 1 なら (½,½) も最大化点) を別 report 行で検査した。 「WLOG」 「明らかに」 の文は item 化して機械が通る経路にする。

第二の目 campaign (2 段階盲検、 無限次元 item 9 個、 62 分) で追加された kernel:

7. **定理の verdict は「読み」 ごとに出す** — 論文が未定義のまま使う語 (「supp」 = 閉値域か値域か) で定理の真偽が分かれるなら、 ledger の `readings` に読みを列挙し**各読みで 3 状態を別々に**書く (実測: 閉値域読みでは「⇒」 が偽で「⇐」 が真、 値域読みではその逆)。 「どちらの読みでも同値は成立しない」 が正しい結論で、 一方の読みだけで refuted / verified と書くと受け手が誤読する。 論文自身の用法 (証明中の記号) が default 読みを決める。
8. **証明の gap と言明の偽を分けて閉じる** — 証明の 1 step が偽 (射影束の meet は単調強極限と可換でない) でも言明は真かもしれない。 「gap = item」 「言明 = 別 item」 「経由補題 = 別 item」 とし、 言明の反例は**論文が試みた埋め込みが失敗する構造** (第 3 元が可逆になる) を読んでから設計する (実測: 第 3 元を非可逆な d^{1/2}(1−P)d^{1/2} に置いた瞬間に閉じた)。 反例には 2-outcome / ≥3-outcome の分岐が付く (2 元は可換性で守られる)。
9. **打ち切りは反例を見せない — 機構の減衰 trend を anchor し、 plateau は未解決と書く** — 有限次元では定理が真なので truncation に反例は現れない。 check が固定できるのは (a) POVM 性・supp 重なりの exact な有限事実 (b) 共通下界の certified 上界 [‖a:b‖, 2‖a:b‖] が N とともに減衰すること、 まで。 減衰が plateau に入ったら「切断 artefact か数値か未解決」 と docstring に書き、 閾値を plateau に合わせて緩めない (= cell 埋め)。 **compression の罠**: 射影を切断空間に圧縮すると射影でなくなり (P_N(1−P_N) ≠ 0)、 補元と O(1) の偽の共通下界を持つ — 分解の方を切断する (圧縮のスペクトルを 1/2 で切った射影)。
10. **exact な有限主張でも double では certify できないことがある** — 「弧の外で消える次数 ≤ N の三角多項式は無い」 = Gram 行列の正定値性、 だが λ_min は prolate 型で超指数減衰 (N=8 で 1e-19、 N=16 で 1e-38)。 float の固有値に 1e-12 閾値を当てると N ≥ 8 で偽 FAIL。 → mpmath 100 桁で certify (丸め 1e-100 ≪ λ_min)。 「主張は真だが double では見えない」 を「主張が偽」 と読まない。
11. **solver 無しの sandwich = 並列和** — 最大共通下界ノルムは ‖a:b‖ ≤ max‖c‖ ≤ 2‖a:b‖ (a:b = (a⁻¹+b⁻¹)⁻¹ は共通下界、 任意の共通下界は c ≤ 2 a:b)。 SLSQP なしで証明付きの区間が出る、 [`scientific-computing.md#small-sdp-without-solver`](scientific-computing.md#small-sdp-without-solver) 5。 固有値が 1e-8 を割る作用素は float の逆行列が壊れるので mpmath で。
12. **同じ note の heuristic を同 note の厳密事例で叩く** — 「距離が正の cell 対は共通下界を持たない (plausibly)」 という heuristic が、 同 note の厳密結果 (回転対称 cell = 非隣接でも共通下界あり) と矛盾していた (並走 pass が指摘)。 heuristic を書く時は手元の exact case に当ててから書く。 正しい機構は距離でなく**値域の幾何** (有界 cell は外側の環を含む cell と必ず共通下界: |F|² の劣調和性)。
13. **一般測度の cell に対する witness は ∂̄ で作る** — Husimi 粗視化の隣接 pair (1 つの円板を 2 cell だけが埋める) には h = e^{|z|²/2}∂̄φ が Stokes で V*h = 0 を満たし、 ψ = V*(1_{U_k}h) が両 cell の平方根値域の共通元、 ψ ≠ 0 は「指示関数は反正則になれない」 (∂̄ の楕円正則性) で保証 — 境界の滑らかさ不要、 Fock 成分は Gaussian が相殺して閉形式 × 1 次元求積。 残る「全 cell が全尺度で絡む可測分割」 は unverified のまま (教科書用途には不要)。 道具 = `husimi_dbar_witness` / `husimi_halfplane_matrix`。

同日の第二の目 campaign (新結果 1 件の盲検 → 攻撃、 6 item、 28 分) から 4 つ追加:

14. **連続主張の核心が有限次元の不等式なら、 それを機械 anchor にする** — 無限次元の証明に「打ち切り数値」 を evidence として付けると kernel 3 の罠 (compression の共通下界は元の共通下界でない) に落ちる。 代わりに証明の中で「任意の正作用素 X に対して成り立つ有限次元定理」 (例: Tr X (1−|⟨u|v⟩|) ≤ Tr(Q_u X) + Tr(Q_v Y)) を切り出し、 それを打ち切り空間で solver の primal (feasibility 再検査済) と突合し、 極限で効く scaling (RHS/Tr ~ s²) と打ち切り収束を別行で検査する。 spec の「N_max を上げても canonical のみか」 型の要求は有限 outcome では偽になり得る (cell 粗視化は非 IS) ので、 連続主張の**有限 shadow を先に定式化**してから anchor を書く。 汎用 dual solver が緩い (≈ Tr X + Tr Y) 時は、 問題の構造から明示 dual を組む ([`scientific-computing.md#small-sdp-without-solver`](scientific-computing.md#small-sdp-without-solver) 8)。 道具 = `gpt_measurements.py` の `nearly_rank_one_clb_bound` / `coherent_cell_matrix`。
15. **独立な第二の目の価値は verdict の一致でなく方法の差** — 盲検 pass が元の証明と別の道具立て (RN + Fourier 一意性 vs 有限加法性 + trace 不等式) で同じ結論に達したことが独立性の傍証で、 一致した後の確信境界は「両証明が共有する暗黙前提」 (σ-加法族の取り方、 effect の有界性) を列挙して書く。 方法が同じで結論だけ一致した第二の目は §7 の「相関した agent の一致」 に近い。
16. **note 内の heuristic 文は同 note の厳密結果と突合する** — 「plausibly 〜しない」 型の見立てが、 同じ note の別 § で既に証明された事実 (回転対称 cell は非隣接でも共通下界を持つ) と矛盾していた。 ledger item でない散文の見立ても、 反証 framing の pass では item 化して落としに行く (spec 外 id を足してよい)。 受領側はこの種の finding を並走 campaign へ申し送る (実測: 一般 cell 担当の並走 pass が「距離」 でなく別機構で証明する必要を先に知れた)。
17. **証明 note の省略は「埋まるか」 まで書く** — 攻撃 pass が「落ちない」 と判定した step でも、 一言で済まされた正当化 (可算稠密集合から全 vector への拡張 / 「Ĝ ≠ 0 ⇒ ĥ = 0」 は S′ で 1/Ĝ を掛けられない) は埋め方と出典 (定理番号) を ledger の note に残す。 「落ちない」 だけの verified は次の読者に同じ省略を読ませる。

spec 側の教訓 (= 起票者向け): 環境の道具の欠落 (SDP solver 不在) と代替 (linprog / 手計算) を spec に書いておくと worker が最初の 1 時間を tooling に溶かさない (実測は約 1.5 時間 = 全体の 1/4)。 起票者の仮説を deny list で隔離した結果、 worker は問い C-01(a) に論文にない証明 (Husimi POVM の間主観性) を出した — 独立性は verdict だけでなく **新規結果**も生む。

### <a id="continuous-rank-one-povm-extremality"></a>連続 rank-one POVM の「極値性 → self-joint 一意性」を閉じる recipe (campaign 2 cross-vendor pass から)

連続 outcome では有限 outcome の support-intersection 判定をそのまま持ち込まない。標準 Borel POVM の self-joint 一意性を示す再利用可能な順序は次の通り。

1. **存在を先に閉じる**: 対角写像 \(\Delta:x\mapsto(x,x)\) による像測度 \(B_0=A\circ\Delta^{-1}\) を作る。rectangle 上では \(B_0(U\times V)=A(U\cap V)\)。
2. **極値性を minimal dilation の injectivity に落とす**: \(A(U)=V^*P(U)V\) の最小 Naimark dilation を具体的に与え、\(D\in P'\), \(V^*DV=0\Rightarrow D=0\) を示す。multiplicity-one の場合 \(D=M_h\) なので、有界密度 \(h\) の積分変換の injectivity に帰着する。Husimi POVM では Fock matrix elements が \(h(z)e^{-|z|^2}d^2z/\pi\) の全 mixed moments を消し、Gaussian exponential integrability で冪級数と積分を交換し、Fourier--Stieltjes 一意性から \(h=0\) a.e. が従う。一般 moment problem の決定性を black box にする必要はない。
3. **専門的な operator-valued RN に一本依存させない**: rank-one density の場合は、凸分解の各 matrix-element measure に scalar/complex Radon--Nikodym を適用し、可算稠密部分空間上で null set を一つに揃える。rank-one domination で density を scalar 倍に因数分解し、同じ injectivity で極値性を直接再証明できる。非可算個の vector-dependent null set を無造作に共通化しない。
4. **joint の一意性を product \(\sigma\)-algebraまで運ぶ**: 極値 POVM と両立する self-joint は rectangle 上で一意になる。そこで止めず、各 vector-state の有限 scalar measure に \(\pi\)-\(\lambda\) 一意性を適用し、polarization で作用素等式へ戻す。standard Borel/second-countable の仮定と \(\mathcal B(X^2)=\mathcal B(X)\otimes\mathcal B(X)\) を明記する。
5. **読みと tier を分ける**: statewise / weak / strong / ultraweak の可算加法性は正の有界単調部分和では同じ結論を与える。一方、有限加法的 charge への拡張は別問題。有限 Fock 切断・quadrature・有限 test family の full rank は規格化と実装の 🔧 anchor に過ぎず、無限次元 injectivity の証拠に数えない。共通 anchor は [`scripts/gpt_measurements.py`](../scripts/gpt_measurements.py) の `coherent_resolution_matrix` / `coherent_bounded_moment_map` と内蔵 foil。

<a id="continuous-rank-one-povm-cell-route"></a>**第 2 経路 (盲検の第二の目、 同日): 極値性も RN も使わない cell 分割** — (i) self-joint B が canonical ⇔ B が対角集合 D の外で消える (B(E) = B(E∩D)、 A′(U) := B(Δ(U)) = B(U×ℂ) = A(U))。 (ii) 正の距離 d にある有界 U₁, U₂ を辺 s ≤ d/(2√2) の正方 cell V_k ∋ z_k, W_l ∋ w_l に分割し、 各 block X = B(E ∩ (V_k×W_l)) ≥ 0 に **有限次元定理** Tr X (1−|⟨z_k|w_l⟩|) ≤ Tr(Q_k^⊥ X) + Tr(Q_l^⊥ X) ≤ Tr(Q_k^⊥ A(V_k)) + Tr(Q_l^⊥ A(W_l)) を当てる (Q^⊥ = 1 − |z⟩⟨z|、 ‖p_z + p_w‖ = 1 + |⟨z|w⟩|)。 rank-one 密度ゆえ Tr(Q_k^⊥ A(V_k)) = (1/π)∫_{V_k}(1 − e^{−|z−z_k|²}) ≤ |V_k| s²/(2π) で、 総和は (|U₁| + |U₂|) s²/(2π) → 0、 一方 1 − |⟨z_k|w_l⟩| ≥ 1 − e^{−d²/8} > 0 は s に依らない ⇒ Tr B(E) = 0。 (iii) D^c は正の距離にある dyadic 正方形の対 Q×Q′ の可算和なので B(D^c) = 0。 使う性質は |⟨z|w⟩| < 1 (z ≠ w) と norm 連続性だけなので、 **norm 連続・pairwise 非平行な rank-one 族 × 局所有限測度の POVM 一般** (atom 可) に同じ証明が通る (= Thm 2 の rank-one 場合の連続 outcome 版、 第三者未検証の系)。 この経路の核不等式は上の有限 anchor (`nearly_rank_one_clb_bound`) そのもの (§14 kernel 14)。 経路 1 (極値性 + moment 一意性) との共有前提 = Borel(X²) = Borel(X) ⊗ Borel(X) と effect の有界性のみ。

**使用定理 / 出典候補の置き方**: load-bearing な theorem 名を ledger に書く (minimal-Naimark extremality criterion / scalar または POVM Radon--Nikodym / multiplication spectral measure の commutant / dominated convergence または Fubini--Tonelli / Fourier--Stieltjes uniqueness / \(\pi\)-\(\lambda\) uniqueness / polarization)。極値性 criterion の候補は Pellonpää, *J. Phys. A* **44** (2011) 085304、測度論は Folland, *Real Analysis* または Bogachev, *Measure Theory*、積測度一意性は Folland または Kallenberg。候補を挙げただけなら定理番号・適用条件を照合済みと書かない。

## <a id="campaign-tooling"></a>15. Verify-to-learn campaign の運用 kernel — ledger・2 段階第二の目・繰り越し・機械 gate (2026-09)

初回 campaign (外部論文 2 本、41 item、64 分、別 session worker) とその retro から。 **一般則はここ、 instance (campaign dir・check script・finding) は private repo に残置**。 道具の実体は層1 `scripts/`。

**A. ledger schema (1 item 1 entry、 3 状態)**: `id` / `source` (bibtex key + 論文内 label) / `statement` / `class` (machine | prose) / `tier` (🔧 | 👁 | 📄、 [§4](#verification-tier)) / `status` (verified | refuted | unverified、 [§5](#claim-states)) / `check` + foil の path / `readings` (読み多義の列挙、 [§6](#verify-to-learn)) / `note` / **`novel_to_requester`** (受領側記入、 [§8](#efficacy-proxy-receiver-side)) / **`second_eye`** (👁 が別 pass で閉じたら `"done <date> <where>"`)。 YAML の list で、 `- id:` を entry 先頭 key に (= 物理行数と parse 数を突合する gate に掛かる)。 状態の集計は機械 (`grep -c "status: unverified"`) で入口にする。

**B. 検証サイクルは未検証主張を生産する — 繰り越し台帳で「消えない・溜まらない」**: 自前導出 (👁) は machine anchor を持たないので、 campaign は verified と同時に「次に検証すべき主張」 を産む (初回: 13/41 が 👁、 うち 1 件は論文にない新結果)。 同 campaign 内で閉じようとすると再帰し、 放置すると消える。 → **`carryover.yaml` (生成物) = 全 campaign の 👁 ∧ 未 refuted ∧ `second_eye` 無し を集約し、 次 campaign の spec の C 群はここから引く**。 閉じたら元 ledger に `second_eye` を書いて消灯 (台帳は再生成)。 道具 = `scripts/verification-campaign-report.py --carryover --write`。

**C. 新結果の第二の目は 2 段階 (盲検 → 攻撃)**: 検証 pass 自身が出した新結果 (= 論文にない主張) を検証するとき、 第二の目に元の証明を先に読ませると同じ盲点を継ぐ ([§7](#independent-second-eye))。 → **stage 1 = statement だけ渡して自力導出、 commit してから stage 2 = 元の証明を開いて「落とせ」**。 stage 1 の commit が stage 2 より前にあることを rubric に入れる (= 盲検の証拠は git にある)。 spec には期待 verdict も「要注意 step」 も書かない ([`cold-eyes-isolation.md#spec-leakage`](cold-eyes-isolation.md#spec-leakage))。 cross-vendor pass ([§7 cross-vendor](#cross-vendor-red-team)) は同じ statement を別ベンダーに並走させ、 受領側が突合する。

**C′. 実測 (n=1、同日)**: 2 段階第二の目の worker が「deny list の file は開いていないが、 **auto-load 文脈** (個人層の projects 一覧 + 層1 kernel 追補) に verdict の方向が書かれていた」 と自己申告 — 証明の中身は盲検 (別経路の証明が出た)、 verdict は盲検でない。 → **検証 pass が産んだ新結果の第二の目は sandbox 方式** ([`cold-eyes-isolation.md#sealed-sandbox`](cold-eyes-isolation.md#sealed-sandbox)、 汚染経路 1 = cwd 祖先の CLAUDE.md は deny list で塞げない) + **進行中 campaign の verdict を projects 一覧・層1 追補に書かない** (書くのは受領・突合後)。 別ベンダー pass (AGENTS.md 入口、 個人層 CLAUDE.md を読まない) にはこの経路が無かった = cross-vendor の独立性の一因。 **n=2 (同日、 並走 worker)**: 許可 file に入れた層1 library の docstring 1 行 (前 campaign の finding を要約した「無限次元では ran(a^{1/2}) 交わりが判定条件」) が方向の示唆になった、 と worker が申告。 → **許可 file の docstring / README にも前 campaign の verdict を書かない** (書くなら受領後、 かつ第二の目の対象と分離)。 = 「深い知見を層1 に hoist する」 と「第二の目の盲検」 は同じ file を取り合う。 時間順で解く: hoist は受領・突合の**後**。

**D. 外部論文の検証読みでは sandbox でなく deny list で隔離が足りる** (= verdict が事前に存在しない場合に限る、 C′ 参照): 自著の盲検 ([`cold-eyes-isolation.md`](cold-eyes-isolation.md)) と違い、 汚染源は「起票者の仮説」 だけ。 spec に verdict を書かない + 起票者の note を deny list に入れる、 で実測は汚染 grep 0 hit、 worker は起票者の知らない結果を出した (n=1)。 再訪 trigger = 受領後の汚染 grep で hit。 **並走 worker は campaign dir を分ける** (= 同 repo の ledger / results の file race、 [`multi-session-coordination.md#file-path-race`](multi-session-coordination.md#file-path-race))。

**E. 「item ごとに commit」 は機械 gate にする**: 散文規律は cold worker に効かず (41 item / 2 commit)、 desktop client は hook 出力を model に渡さない — **git の exit code だけが全 surface で効く**。 → pre-commit で「1 commit の追加 entry ≤ N」 を refuse、 escape は env + 台帳隣の hygiene log に記録 (隠れない)。 道具 = `scripts/ledger-commit-cadence-gate.py` (repo 側は hooks/pre-commit から呼ぶ shim)。 output-cap 死 ([`output-cap-death-loop.md`](output-cap-death-loop.md) 予防 3) の機械化。

**F. stats は git から、 efficacy proxy は受領側から** ([§8](#efficacy-proxy-receiver-side)): 所要 = 最初の commit → results.md 初出、 entries/commit、 👁 残、 novel_to_requester 数を `scripts/verification-campaign-report.py <dir> --write` が results.md の AUTO block に焼く。 自己申告の数字を results に書かせない。**生成物自身を commit した瞬間に commit 数が +1 stale になる自己参照を除く**ため、campaign work commit 数は AUTO block だけの refresh commit を除外し、`--write` 前に substantive な campaign dirty change があれば次の 1 commit を先取りして数える (selftest で write → commit → 再集計の不変性を固定)。同じ理由で AUTO block に実行日などの wall-clock 値を入れない — campaign 内容が不変なら翌日の rerun も byte-identical でなければならない。

**G. 受領手順 (起票側)**: 汚染 grep → 主要 finding の独立再実装 (受け手は worker の script を走らせない、 [§7](#independent-second-eye)) → refuted / 新結果に `novel_to_requester` 記入 → stats + carryover 再生成 → 完了 marker consume → 下流 (教科書 / 論文 note) へ verdict 反映。 他者論文の誤り finding は default 非公開のまま ([§6](#verify-to-learn))、 著者報告は人間の判断。

**H. 別ベンダー pass の scope は spec だけでは縛れない (n=1)**: 「書くのは自分の campaign dir だけ、 promote は受領側」 と spec に書いても、 受け手の AGENTS 既定 (= 確定知見は owning project へ昇格) が勝ち、 別ベンダー worker が層1 library・規約・文献 SoT・repo の DESIGN へ直接 commit した。 中身は review で健全と判明し採用したが、 (i) 受領側が突合する前に SoT が動く (ii) 別 campaign の決着で即 stale になる (実測: 文献 note の「unverified」 が同夜 refuted に)。 → cross-vendor spec には **「promote 禁止、 提案は results.md に書く」 を AGENTS 既定より強い language で明記** し、 board の claim event を受領側が監視、 昇格は受領・突合の後に受領側が行う (C′ の「hoist は受領後」 と同じ時間順)。

**正直な限界**: 全部 n=1 (初回 campaign + retro)。 efficacy proxy は傾向指標。 cadence gate は「entries per commit」 しか見ない (時間・token は git に無い)。

## <a id="sibling-routing"></a>16. 隣接 doc への routing

自著の投稿前検査 = [`paper-audit.md`](paper-audit.md) / ノートの書き方 = [`physics-notes.md`](physics-notes.md) / 数値検証 kernel = [`scientific-computing.md`](scientific-computing.md) / 審査側 = [`peer-review-workflow.md`](peer-review-workflow.md) / 文脈手術時の散文 sweep = [`paper-audit.md#relocation-rebinding-sweep`](paper-audit.md#relocation-rebinding-sweep) / 検出失敗 RCA の方法論 = [`convention-design-principles.md#detection-zero-location`](../docs/convention-design-principles.md#detection-zero-location) / 委譲・cold-eyes の機構 = [`multi-session-coordination.md`](multi-session-coordination.md)。 campaign の道具 = 層1 [`scripts/ledger-commit-cadence-gate.py`](../scripts/ledger-commit-cadence-gate.py) + [`scripts/verification-campaign-report.py`](../scripts/verification-campaign-report.py) + [`scripts/gpt_measurements.py`](../scripts/gpt_measurements.py) (数学 library、 [§定義 level 判定](#definition-level-judge))。
