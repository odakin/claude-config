# 運用Tips

[claude-config](../README.ja.md) を使った20以上のプロジェクトの実運用で見つけた実践パターン。

> **English version**: [usage-tips.md](usage-tips.md)

## 1. 毎回新規セッションで「〜を再開」

長い会話を続けない。毎回新しいセッションを立ち上げて「〇〇プロジェクトを再開」と言う。Claude が CLAUDE.md → SESSION.md を読んで、前回の続きから作業を再開する。autocompact のリスクがゼロになる。

**前提:** SESSION.md が常に最新であること（CONVENTIONS.md §3 の自動更新プロトコルが必須）。

## 2. push 前の呪文

push の前に毎回こう言う:

> 「整合性、無矛盾性、効率性をチェック。プッシュ。」

Claude がドキュメントとコードの齟齬を見つけて直す。 **ほぼ毎回何か見つかる**: 古い件数、循環参照、見出し重複、ステータスの陳腐化など。

public リポでは「安全性」を追加:

> 「整合性、無矛盾性、効率性、安全性をチェック。プッシュ。」

個人情報・非公開リポ名・メールアドレス等の漏洩を grep でチェックしてくれる。

## 3. 「深く検討して」で浅い回答を防ぐ

Claude はデフォルトでさっさと答える。「深く検討して」と言うと、トレードオフ分析・代替案の比較・エッジケースの考慮が出てくる。正解が1つでない判断（設計、機能の要否、UIの配置など）で使う。

## 4. 決定事項の WHY を日付付きで記録

機能の採用/不採用を決めたら、 **理由を含めて** SESSION.md に記録する:

```markdown
# 悪い例
- 「現在営業中」フィルターは実装しない

# 良い例
- 「現在営業中」フィルターは実装しない（2026-03-21）
  — 根拠が二次加工（パーサー推定、カバー率97.1%）で
  約290件が判定不能、代替なし、除外しなくても害がない
```

日付がないと、状況が変わっても永久に有効な不文律のようになってしまう。

## 5. 競合比較で機能のアイデア出し

Claude に競合サイトを分析させ、「何が負けているか」を聞く。ただし「負けている」= 実装すべきとは限らない。各項目について「深く検討して」を使い、本当に実装すべきかを検証する。

## 6. フィードバックは正本規約と hook に投資する（memory ではない）

Claude が同じミスを繰り返した時、memory (`~/.claude/` の memory 機能) に feedback として保存するのが反射的な対応だが、**しない**。このリポの `memory-guard.sh` hook が memory directory への feedback 系書き込みを実際に deny する。理由は precedent-as-training-data — memory に書かれた feedback は毎セッション load されて pattern-match を強化し、是正より反復の方向に働く。詳細な理論は [`convention-design-principles.md` §8.3](convention-design-principles.md#precedent-as-training-data)。

durable な修正先は**マシン・セッションを越えて残る場所**に置く:

- **一般化できるルールは [CONVENTIONS.md](../CONVENTIONS.md) または `conventions/*.md`** — git 同期、全 session で load、編集可能、CLAUDE.md から pointer で参照される。「常に X をする」「Y を絶対にしない」類の rule の正当な置き場。
- **catastrophic 級のリスク（データ破壊・secret leak・不可逆な外部通信）は hook** — PreToolUse `deny` / pre-commit ブロック / permission allowlist。§8.2 が介入強度のランキング、§8.4 が「どんな written rule より機械的強制の方が構造的に強い」理由を説明。
- **annoyance 級のミス（数文字の訂正で済むもの）はどこにも書かない** — in-session correction で受容して終わる（§9.1 triage）。ここで memory に手が伸びるのは、工学的判断ではなく不安応答であることが多い（§8.5）。

元の観察 — 修正ばかりだと Claude が過度に慎重になる — は依然有効。非自明だがうまく機能したパターンは「やるな」ルールと並べて同じ正本規約に書き添える。修正例と成功例のバランスは正本規約の中で取る — memory に置くと load-and-repeat ループが密度の高い側を増幅してしまう。

## 7. 正本を1つに決め、循環参照を潰す

情報の置き場所を1つだけ決め、他は参照にする。参照先はセクション名まで明記する:

```markdown
# 悪い例（循環参照）
CONVENTIONS.md: 「リポ一覧の正本は MEMORY.md」
MEMORY.md: 「リポ一覧は CONVENTIONS.md §1 が正本」

# 良い例（正本が1つ）
CONVENTIONS.md: 「リポ一覧の正本は MEMORY.md の『リポ一覧（正本）』セクション」
MEMORY.md → [実際のリポ一覧テーブルがここにある]
```

## 8. サブプロジェクトの CLAUDE.md チェーンに注意

Claude Code は作業ディレクトリから親方向に `CLAUDE.md` を全て auto-load する。`~/Claude/repo/sub/` で作業すると、`~/Claude/CLAUDE.md`・`~/Claude/repo/CLAUDE.md`・`~/Claude/repo/sub/CLAUDE.md` の 3 つが同時に載る。これは特に 200K コンテキストモデルで効いてくる — autocompact が 167K トークン付近で発火するため、チェーンが膨らむとセッション開始前に余裕を食い潰してしまう。

各階層を役割ごとに分離する:

- **トップレベル `~/Claude/CLAUDE.md`** — 身元・全体規約・リポ索引。
- **リポ `CLAUDE.md`** — リポの概要・起動方法・詳細への pointer。
- **サブプロジェクト `CLAUDE.md`** — コマンド・特有の注意・アーキ超要約（5〜8 項目 × 1 行 + `docs/architecture.md` への pointer）。80〜100 行目安。

重い narrative・パラメータ表・設計根拠は `docs/`（auto-load されない）に置いて pointer で参照する。原則と事例は `convention-design-principles.md` [§10.10](convention-design-principles.md#claudemd-chain-nested-autoload)–[§10.11](convention-design-principles.md#super-summary-pattern)。

## 9. プロジェクト docs の role 分離: 「同じ知見を 5 箇所に書かない」

CONVENTIONS.md §3 の「SESSION.md ~80 行」 target を守るには、 各 docs artifact に **role を明確に割り当てて重複を avoid する** のが鍵。 §7 「正本を1つに決め」 が「reference data の正本」 軸なら、 本 §9 は「**作業 narrative の role**」 軸 — 同じ fix を説明するときに、 detail を repo の docs 全部に書くと SESSION.md が肥大する。

各 artifact の role と temporal scope を分離:

| artifact | role | temporal scope | consumer |
|---|---|---|---|
| **commit message** | 「このコミットの why + 実装決定の根拠」 | 永続 (= git log) | 後で blame / log で読む人 |
| **plan (`plans/YYYY-MM-DD-*.md`)** | 「大きな refactor の stage 別 design + Q&A + audit log」 | 永続 (= 該当 refactor の history) | 同 refactor を deep dive する人 |
| **DESIGN.md** | 「設計思想 + 対称表 + 永続 invariant + 採用案 vs 棄却案」 | 永続 (= リポ life cycle) | code レビューで思想を確認する人 |
| **docstring** | 「関数の正本 (= 公式 + ガード理由 + 値選定根拠)」 | code に coupled | code 上で関数を理解する人 |
| **SESSION.md** | 「事実 + commit ref + verify status + 詳細 link」 のみ | 揮発 (= autocompact で消失、 ~80 行 target) | 次セッションで作業を resume する人 |

**SESSION.md には書かない**: 物理 detail / 設計対称表 / 数学公式 / 値選定根拠 / 詳細 stage 別経緯 — これらは上の 4 artifact のいずれかに置いて SESSION から link する。 SESSION の役割は「**この変更があった、 status はこう、 詳細はここ**」 を 1 行で示すこと。

**棚卸しの規律 (= CONVENTIONS.md §3「長ければ棚卸し」 の operationalize)**:

- push 前 SESSION.md 確認で、 自分が直前に追加した entry の長さを measure する
- 18 行とか書いてしまった場合、 「detail がどこかに重複しているはず」 と疑う (= DESIGN.md / commit message と inevitably 重複)
- 「事実 1 行 + status 1 行 + 詳細 link 1 行」 の **3 行 template** に圧縮可能か audit
- 既存 entry が deploy 済 + verified なら **1 line summary に圧縮 + 詳細は git log + plan path 委譲**
- ~~strikethrough done~~ entry は CONVENTIONS §3「完了 [x] を除去」 に従い削除

**実例 (2026-05-05 LorentzArena Rule B exit margin、 棚卸し怠慢)**: SESSION.md が既に 188 行 (~80 行 target の 2.4x 超) の状態で、 私 (Claude) は 18 行の detail entry を追加して 204 行に押し上げた。 user 「コードを深く 4 軸チェック」 で post-deploy 棚卸しを initiate された結果、 5/2-5/5 の deploy 済 + verified entries (= 5 session 分) が詳細のまま残存していると判明、 全面棚卸しで 204 → 104 行 (= 49% 削減) に圧縮。 entry detail は DESIGN.md / docstring / commit message に既存していたため SESSION からは link のみで sufficient だった (= 重複の典型)。 詳細: [LorentzArena commit `ddcd0d6`](https://github.com/sogebu/LorentzArena/commit/ddcd0d6)

## 10. plan / DESIGN の checkbox `[x]` は **実装済のみ** で使う

### Why

`[x]` の semantic を「実装済」 と「実装予定 (forward-look)」 で **混用すると、 別 session の Claude が plan を読んだ時に reflex 解釈で誤る**。 「実装予定」 を `[x]` で書いてしまった forward-look entry を、 後で別 session が「実装済」 として skip した結果、 該当 task が永遠に欠落する事故が発生する。 逆に、 実装済の `[x]` を未着手と勘違いして重複実装するケースも起きる ([`multi-session-coordination.md §2`](../conventions/multi-session-coordination.md))。

### How to apply

| マーカー | 意味 | 別 session が読んだ時の解釈 |
|---|---|---|
| `[ ]` | 未着手 | 「これから実装する」 |
| `[ ] (実装中: <hash>)` | 部分実装、 完了でない | 「commit はあるが意図を満たしていない、 続きを引き受ける」 |
| `[x]` | **実装済 + main 取り込み済 + 意図を満たす** | 「無条件 skip して次の task へ」 |

forward-look (= 「次にやる予定」) は `[x]` を使わない。 plan の別 section (= 「次にやる」 / 「Phase 2 予定」 等) に分離して、 checkbox 軸は「実装済 / 未着手」 の 2 値に保つ。 mixed semantics は別 session の reflex で必ず誤読される。

session 開始時に plan を読んで `[x]` を見たら、 該当 task が **対応する commit を含むか** を `git log --oneline -- <relevant-file>` で 1 回確認する習慣を入れる (= 同日内の self-trust の罠の防御)。 commit が存在しなければ forward-look の疑い、 plan 著者 (= user) に確認するか自分で実装する。

### Anti-pattern

- **session 切れる直前に「予定として `[x]`」 を書く**: 次 session の自分 (or 別 Claude session) が誤読の温床。 切れる前に `[ ] (next session で実装)` の方が明示的
- **`[x] (forward-look)` 等のラベル付き forward-look**: 機械的 grep / reflex 解釈で label を見落として誤読される。 forward-look は `[ ]` のままで運用
