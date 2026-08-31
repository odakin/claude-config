<!-- doc-meta
when: 論文・研究ノートの主張を機械検査で守る体制を組むとき / 外部論文を検証読みするとき / 検証系 AI workflow (verify-to-learn・adversarial pass) を設計するとき
category: research-domain
summary: 物理主張の検証サイクル (= 生成 → 機械検査 → 独立した第二の目 → 人間の判断) の 8 kernel — 主張ごとの機械 anchor / foil (negative control) / 検証 tier 宣言 / claim 3 状態 / verify-to-learn / 第二の目の独立性 / rubric 事前登録 / 止まる規律。 数ヶ月の paper-anchored audit fleet 運用 + 2026-08 の散文主張 RCA からの hoist
-->
# 物理主張の検証サイクル (verification cycle)

> **位置づけと credit**: 本リポ維持者が自分の物理研究で運用している「主張を検査で守る」体制の一般則。 実 instance (個別 paper の audit script 群・claim ledger) は各 private paper repo に残置 (= kernel-up / instance-down)。 **着想・命名の一部 = 日高義将氏 (京都大学基礎物理学研究所) の公開講演「AI による理論物理研究の自動化」 (PPP2026、 2026-08)**: 4 station cycle の整理・**verify-to-learn** の名と手順 form・**FCIR** (Fibered Claim IR = 原文/読み方/前提/根拠) の読み多義分析・「根拠がない時に止まる」「確かめられなかった項目を分かったことにしない」 の標語・integrity ≠ efficacy の評価 form は同講演由来。 一方、 機械 anchor・foil・検証 tier・claim 3 状態は当方の運用が講演に先行して独立に発達したもので、 講演は収斂の確認と命名を与えた。 本 doc は自前運用で incident-backed になった kernel のみを書く (借り物の未検証手法は書かない — 例: FCIR の台帳 form 自体は氏の実演でも効果判定不能と報告されており、 採らない)。

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

**なぜ**: 検査は書いた瞬間の正しさでなく**将来の編集に対する正しさ**を守る。数ヶ月運用の実績 (該当 private paper repo、audit 20+ 本): 共著ノートの literal-copy 転記誤り (係数 2 ↔ −2、向き反転込み) を初稿レビューで即捕捉 / as-printed の最終恒等式が exact に −1 倍 (frame 順の swap が反対称部を flip、残差 4e-16) を機械が検出 / 人間と AI が両方誤った符号論争を一般接続 probe が裁定。

## <a id="foil-negative-control"></a>3. Foil (negative control) — 「検査に歯があること」を検査する

**ルール:** audit には**わざと壊した variant (foil)** を同梱し、foil が FAIL することを PASS 条件に含める。 sign foil (符号を反転して通らないこと) / swap foil (脚順・bracket 順を入れ替えて通らないこと) / 非不変 foil (対称性を破る入力で不変量検査が落ちること) / 正解を 1 箇所書き換えて検出されること。

**なぜ**: foil のない検査は「常に PASS する検査」と区別が付かない (= vacuous pass)。実例: parity 検査の初版が anchor 消失で **vacuous pass していた**のを anchor 死活検査の追加で発見 / 係数検査は commutator-sign foil・non-Lorentz foil を同梱して初めて「その次数を本当に見ている」と言える。

## <a id="verification-tier"></a>4. 検証 tier の宣言 — 転記と検証を混同しない

**ルール:** 外部資料 (論文・ノート・スライド・写真) から取り込んだ式・数値には tier を明示する: **🔧 machine-verified** (独立に計算して一致) / **👁 目視転記のみ** (見て写した、検証はしていない) / **📄 OCR** (機械抽出、誤読リスク別枠)。 tier 未宣言の転記を「検証済み」と扱わない。

**なぜ**: 転記は正しさを運ばない。実例: 外部論文 6 本の読解ノートで tier 区別を強制した結果、🔧 化の過程で初稿の literal-copy 誤り 1 件が即捕捉された (👁 のままなら残っていた)。数値検証の一般則は [`scientific-computing.md#verify-independent-derivation`](scientific-computing.md#verify-independent-derivation) (= 一致合わせは検証でない) + [`#sympy-verify-transcript`](scientific-computing.md#sympy-verify-transcript)。

## <a id="claim-states"></a>5. Claim の 3 状態 — 確かめられなかった項目を分かったことにしない

**ルール:** 検証作業の出力は **verified / refuted / unverified の 3 状態**で ledger に残す。 unverified を結論の根拠に使わない。 sweep・audit の完了報告は「検査した範囲 / NOT 検査した範囲 / 確信境界」を明示し、「✓ 全部 OK」で終わらせない。

**なぜ**: 「検査した」の暗黙 scope 拡大が、単一情報源 null の結論飛躍と同型の事故を作る。 refuted の記録も消さない (= 何が落ちたかは検査資産。 [`convention-design-principles.md#errata-on-preserved-records`](../docs/convention-design-principles.md#errata-on-preserved-records))。

**成果物の拡張 — 「確かめ直せる材料」も研究成果**: 論文と並んで、 検証 record (audit script・check 結果・出典・**失敗と未解決**・人が判断した理由) を「次の人 / AI が確かめ直して続きを始められる形」 で repo に残す。 判断理由の残し方 = [`convention-design-principles.md#design-snapshot-operation`](../docs/convention-design-principles.md#design-snapshot-operation) (DESIGN.md snapshot 運用)。

## <a id="verify-to-learn"></a>6. Verify-to-learn — 外部論文の検証読み (名と手順 form = 日高氏講演)

**ルール:** 外部論文を「使う」前提で読むときは、(1) 式・主張を item 化して抽出 → (2) 機械検査可能 (式・極限・数値・コード) と根拠追加が要る (散文主張) に分類 → (3) 機械検査可能分を 1 item ずつ独立導出で check → (4) 3 状態 ledger に記録、の順で読む。初回 run は**隔離した scratch ledger** で行い、本番の知識ベースへは verified のみ昇格させる。

- **他者の論文の誤り finding は default 非公開**: 検証で誤り (misprint・係数・式) を見つけたら、公開の前に (a) 自前の独立導出で refuted を確定 (b) 著者・管理元へ報告 (c) 先方の応答 / 訂正を経てから公開の順。実例: 標準的参照文献の式の誤りを機械検証 → 報告 → 管理元が承認し web 版修正、の全 flow が通った。引用・再利用する側の防御は「既知 misprint の SoT (RETRACTIONS 相当) を repo に持ち、その式を引く前に必読」。
- 読み方の多義で真理値が変わる主張 (「N 大なら補正小」型) は、読みを 1 つに決める前に候補読みを列挙して各々の帰結を分ける — 強い結論は全候補読みで確認できた時だけ ([`paper-audit.md#claim-strength-three-tests`](paper-audit.md#claim-strength-three-tests) が自著側の同型)。

## <a id="independent-second-eye"></a>7. 独立した第二の目 — 自己検査は独立検証ではない

**ルール:** 重要な検証 (RCA・投稿前・誤り疑い) は**書いた pass と別の pass** に出す — 別 session の cold-eyes AI に、named error class + 反証 framing (「この主張を落とせ」) で渡す。書いた本人の self-check は同じ盲点を継ぐ (= 偽主張は書いた本人には毎回もっともらしく見える)。**相関した agent 同士の一致も独立検証ではない** (同 model class の 2 pass は誤りの相関を持ち得る — 独立性の最終保証は機械検査と人間)。

**なぜ**: 実測で、生成 pass が見落とした同 class エラーを、同じ model の directed sweep pass が同日 6 件捕捉した — 独立性は model を替えることより **pass を分けて検査対象を named にする**ことから先に効く。handoff の機構 (spawn / token / 返送 spine) は [`multi-session-coordination.md`](multi-session-coordination.md)。

## <a id="rubric-before-run"></a>8. 評価基準は走らせる前に決める — 判定不能は判定不能と言う

**ルール:** 手法・対策の効果を主張したいなら、**評価基準 (指標・成功条件・判定不能条件) を実行前に事前登録**する。走らせた後に基準を選ぶと、どんな結果でも「効いた」ことにできる。基準を満たすデータが集まらない場合は「判定不能」と記録する — 記録の integrity (再現・保存一致) と手法の efficacy は別物で、前者の PASS を後者の証拠にしない (この峻別の評価 form = 日高氏講演の実演 2)。**成果物の存在も正しさの証拠にしない** — PDF ができたこと・審査を通ったことは物理・引用・新規性・再現性の証拠でない ([`convention-design-principles.md#acceptance-is-not-specification`](../docs/convention-design-principles.md#acceptance-is-not-specification))。改善が効くのは **AI 本体でなく手順と検査** — session を越えて persist するのはシステム改変のみ ([`convention-design-principles.md#agent-learning-illusion`](../docs/convention-design-principles.md#agent-learning-illusion))。

**なぜ**: 対策の多くは event が稀で統計が立たない (= 判定不能で終わる公算をあらかじめ書くのが誠実)。実例: 散文エラー対策の効果判定を「次の手術 event ≥2 回で捕捉半減、6 ヶ月で event <2 なら判定不能と記録」と事前登録した。

## <a id="stop-when-no-grounds"></a>9. 止まる規律 — 根拠がない時は進めず人間に渡す (標語 = 日高氏講演)

検証で根拠が足りない・読みが複数残る・仮説が決めきれない時は、**分かったことにして進めず、判定不能のまま人間の判断に送って止まる**。自動化の価値は走り続けることでなく、止まるべき所で止まること (= 「根拠がない時に止まる」)。散文の不確実性は「不確実性を expose する操作 (display 化・機械 probe・1 query 検証) を先に回す」が第一手。

## <a id="sibling-routing"></a>10. 隣接 doc への routing

自著の投稿前検査 = [`paper-audit.md`](paper-audit.md) / ノートの書き方 = [`physics-notes.md`](physics-notes.md) / 数値検証 kernel = [`scientific-computing.md`](scientific-computing.md) / 審査側 = [`peer-review-workflow.md`](peer-review-workflow.md) / 文脈手術時の散文 sweep = [`paper-audit.md#relocation-rebinding-sweep`](paper-audit.md#relocation-rebinding-sweep) / 検出失敗 RCA の方法論 = [`convention-design-principles.md#detection-zero-location`](../docs/convention-design-principles.md#detection-zero-location) / 委譲・cold-eyes の機構 = [`multi-session-coordination.md`](multi-session-coordination.md)。
