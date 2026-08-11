<!-- doc-meta
when: referee・審査委員として他者の paper / 申請書を評価するとき
category: paper
summary: 他者の paper / 申請書を referee・審査委員として評価する時の規律 (= invitation intake 〔依頼は失効型義務、 noise blocklist に査読 domain を入れない〕・SoT 4 file pattern・引用文献の現物 verify・framework calibration・scoring scale 整合・既送信 score の不可逆性。 paper-audit / rebuttal-letter / erad-submission の sibling で方向違い)
-->
# Peer Review Workflow (= as a reviewer of external proposals / papers)

reviewer として外部の grant proposal / scientific paper / 申請書 等を評価する work flow の SoT 構造と規律。 reviewer 側 (= 自分が referee / 審査委員) の workflow。 sibling 3 doc 関係:

- 自分の paper 内部の structure audit = [`paper-audit.md`](paper-audit.md) (= forward refs, duplicates, structure)
- 自分が referee report に返信 (= author response) = [`rebuttal-letter.md`](rebuttal-letter.md)
- 自分が grant 申請書を提出 = [`erad-submission.md`](erad-submission.md)
- **本 doc = 自分が referee / reviewer として他者の proposal / paper を評価** (= 上記 3 と direction が異なる sibling)

---

## TOC

- [Invitation intake (= 依頼受信 → 即応。 lifecycle の入口)](#invitation-intake)
- [SoT 4 file pattern (= 1 review case の source 分離)](#sot-four-file-pattern)
- [Source 分離 (= AI analysis vs reviewer judgment)](#source-separation)
- [Frontmatter discipline (= 各 file の metadata)](#frontmatter-discipline)
- [引用文献の現物 verify (= 申請主張 wording の overclaim 検出)](#citation-verify)
- [Framework calibration (= 申請の性質ごとに評価軸を調整)](#framework-calibration)
- [Scoring scale calibration (= 項目別 vs 総合の scale 不整合)](#scoring-scale-calibration)
- [Scan PDF → markdown transcription discipline](#scan-pdf-transcription)
- [提出済 score の不可逆性 + audit-trail](#submitted-score-irreversibility)
- [Cross-references](#cross-references)

---

## <a id="invitation-intake"></a>Invitation intake (= 依頼受信 → 即応。 lifecycle の入口)

本 doc の以降の節は「review を引き受けた後」 の規律だが、 lifecycle はその前の
**依頼 mail の受信**から始まる。 ここが最も落ちやすい (= 2026-08 実例: 依頼→督促→
5 日で自動取消 / 別誌では督促 5 通の末に referee 解任。 いずれも依頼 mail が
surface 機構の noise filter に落ちて人間に届かなかった)。

- **査読依頼は失効型期限つきの義務 class**: 応答しないまま数日〜数週で自動取消・
  referee 解任に至る。 「後で考える」 = 実質辞退 + editor の時間浪費 + 信用毀損。
  受諾でも辞退でも**返答すること自体が義務** (辞退 link の 1 click が editor の
  次候補打診を早める)。
- **認識した同 turn で hard-deadline つき task 化**: 期限 = 依頼文の応答期限、 明記
  なければ受信 +3 日を仮置き (仮置きであることを task に明記)。 受諾/辞退の判断は
  人間、 期限管理は機械。
- **mail surface 機構の noise blocklist に査読 platform の domain を入れない**:
  出版勧誘 spam と査読依頼が**同一 domain** から来る publisher が多く (bucket 混在)、
  domain 単位の suppress は義務 mail を silent drop する。 spam を抑制したい場合は
  義務 class の subject pattern (例: `(?i)invitation to review` / `(?i)review request`)
  を blocklist より**優先する override** として設計する (= allowlist-over-blocklist)。
  editorial office 系 domain (義務密度がほぼ 100% の sender) はそもそも登録しない。
  一般則 (= 査読以外の義務 class にも共通する signal 共有の構造) =
  [`convention-design-principles.md#noise-obligation-signal-sharing`](../docs/convention-design-principles.md#noise-obligation-signal-sharing)。
- **取消・解任通知も記録**: 「取り消されたから対応不要」 で流さない — 無応答による
  解任は incident として記録し、 どの filter / 経路で落ちたかを RCA してから閉じる。

---

## <a id="sot-four-file-pattern"></a>SoT 4 file pattern (= 1 review case の source 分離)

1 proposal / 1 paper の review work で **以下 4 種類の file に source を分離**する。 同 file に混在させると AI 解説と reviewer 判断の境界が曖昧化、 audit-trail も汚染される。

| file | role | author | 性質 |
|---|---|---|---|
| `proposal.md` (or `paper.md`) | 申請書 / paper 全文 transcription | AI (= scan PDF / image から) | input、 不変 (= 原本 mirror) |
| `analysis.md` | AI による解説 + 強み/弱み観察 | AI | input、 reviewer 判断に対する draft |
| `scores.md` | 評点 + 審査意見 + 判断 rationale | reviewer (= 人間) | **正本**、 audit-trail |
| `refs/` (= directory) | 引用文献の本体 PDF + 精読 notes | AI fetch + 人間判断 | input |

**source 分離の根拠**: AI analysis (= analysis.md) は **draft / input** であり、 人間 reviewer の判断 (= scores.md) は **独立の SoT**。 同 file に書くと「AI 推奨をそのまま採用したか / reviewer が独立判断したか」 が unclear、 後年 audit でも tangled。 [`convention-design-principles.md §2 (= #no-duplicate-rules)`](../docs/convention-design-principles.md#no-duplicate-rules) の applied form (= role 別 SoT)。

**directory layout 例** (= 1 proposal あたり):

```
<review-session-dir>/
  <proposal-id>-<applicant-slug>/
    proposal.md      ← AI transcription
    analysis.md      ← AI 解説 (caveat 明示)
    scores.md        ← reviewer 判断 (正本)
    refs/
      arxiv-<id>-<authors>.pdf       ← 引用文献本体
      arxiv-<id>-<authors>-notes.md  ← 精読 notes
    <source-screenshots>             ← 原本 image (option)
```

private / 機密性が高い review (= grant peer review 等) は git-crypt で暗号化。

---

## <a id="source-separation"></a>Source 分離 (= AI analysis vs reviewer judgment)

`analysis.md` (= AI 解説) と `scores.md` (= reviewer 判断) は **絶対に同 file に混ぜない**。 理由:

- **AI 解説は推奨を含むが、 reviewer judgment は user の責任**で出すもの。 同 file だと「AI 推奨 → ✓」 と自動同意した形になり、 reviewer が **independent judgment を行ったか曖昧**。
- 後年 (= 数年後) の audit で「この評点は AI が出したのか reviewer が出したのか」 を区別不能。
- AI 解説の bias / error が reviewer の最終判断にどう影響したか trace 不能。

**運用**: `analysis.md` を読んで reviewer が **自分の言葉** で `scores.md` の評点 + 審査意見を書く。 同意なら同意、 反対なら反対理由を `scores.md` 内に明示。 後年「reviewer が AI 推奨に乗っただけか」 を判別できる形を保つ。

---

## <a id="frontmatter-discipline"></a>Frontmatter discipline (= 各 file の metadata)

各 file は YAML frontmatter で metadata を declared:

### `proposal.md`

```yaml
---
proposal_id: <id>           # 申請 ID / 整理番号
applicant: {name, affiliation, position, ...}
title: ...
budget_breakdown: {...}
source_files:
  - "scan-page-1.png — cover"
  - "scan-page-2.png — section 1"
  # ...
transcription_date: YYYY-MM-DD
transcription_note: |
  scan PDF 解像度限定で §N 経費 table の cell に read unclear 多め、
  user 照合推奨
---
```

### `analysis.md`

```yaml
---
target_proposal: <proposal-slug>
author: "AI (= model: <model-name>)"
created: YYYY-MM-DD
purpose: |
  reviewer の review 準備用解説。 申請内容の整理 + 強み/弱み観点提示。
  審査スコア / 評点ではなく explanation + 論点提示。
scope: ...
caveat: |
  - 本 file は AI 解説であり、 reviewer の最終判断 (= 電子審査システムへの入力内容) とは別物
  - §「気になる点」 は AI 視点の論点提示、 最終評価は reviewer judgment
  - 推測を含む observation は user verify 推奨と明示
related_files:
  - "proposal.md (= 申請書 transcription)"
  - "refs/... (= 引用文献本体 + notes)"
---
```

### `scores.md`

```yaml
---
target_proposal: <proposal-slug>
scoring_session: <session-id>
author: "<reviewer 本人>"
created: YYYY-MM-DD
purpose: |
  reviewer の電子審査システム入力前の判断記録 SoT。
  AI 解説 (= analysis.md) は input、 本 file は audit-trail で **user decision の正本**。
note: |
  本 file は user 本人の確定判断を date 付きで記録するもの。
  AI による解説や推奨スコアとは別 layer (= source 分離)。
  評点変更時は更新履歴に追記。
related_files: [analysis.md, proposal.md, refs/...]
---
```

### `refs/<paper-slug>-notes.md`

```yaml
---
arxiv_id: <id>
title: ...
authors: [...]
read_purpose: |
  申請の差別化主張 (= 「[N] は simplified treatment」 等) の verify。
  実際の論文 scope を確認、 wording overclaim を検出。
read_date: YYYY-MM-DD
pages: <N>
related_files:
  - "../analysis.md (= 親 analysis で要点引用)"
  - "../proposal.md (= [N] として引用)"
---
```

---

## <a id="citation-verify"></a>引用文献の現物 verify (= 申請主張 wording の overclaim 検出)

申請書が「先行研究 [N] は **simplified treatment** / **limited scope** / **subset of relevant interactions**」 等の差別化主張を含む時、 [N] の現物を fetch + 精読して **wording の妥当性を独立検証**する。

### Fetch 経路

1. **arXiv ID 等から URL 構築**: `https://arxiv.org/pdf/<id>` (= PDF direct、 cookie / auth 不要)
2. **`curl -sL -o <path> <url>`** で `refs/` に保存
3. **PyMuPDF で metadata + page text 抽出**:
   ```python
   import fitz
   d = fitz.open(path)
   print(d.metadata)  # title, authors, etc.
   for page in d:
       print(page.get_text())
   ```
4. **abstract + intro + relevant sections のみ精読** (= 全文不要)、 未読部分は notes 末尾で正直に declared

### Wording の overclaim 判定

申請書の disparaging label (= 「simplified」 「limited」 「subset」 等) を [N] 本体と照合:

- **真**: [N] が技術的に limited scope であり、 申請がそこを extend する正当な niche → wording 妥当
- **偽**: [N] が **その framework 内で comprehensive** であり、 申請の wording が underestimate → overclaim
- **「subset」 の解釈幅**: [N] が EFT framework で 1 operator focus なら「subset」 は技術的に弁護可能だが、 [N] の本来 scope を理解した上での評価としては不公正

検証結果を `analysis.md §X` に reflect。 申請の真の novelty (= 残る gap) を狭く evaluation し直す根拠とする。

### 関連: 「単一 source trust 禁則」 family の related axes

申請書 wording (= 単一情報源) で結論せず引用元現物で 2 情報源化する本節の規律は、 「single source = false confidence」 family の **citation 軸 wording** instance。 layer 1 で近接する **related axes** (= 同じ mechanism family、 ただし domain / mechanism は各々異なる):

- [`convention-design-principles.md §8.14 (= #single-field-identity-corroboration)`](../docs/convention-design-principles.md#single-field-identity-corroboration) = 「mechanism が 2 store 照合する時の identity 主張に corroboration 要求」 (= **identity 軸**、 outreach 域での再演は [`research-email.md §pre-outreach-identity-check`](research-email.md#pre-outreach-identity-check))
- [`convention-design-principles.md §8.16 (= #absence-channel-coverage)`](../docs/convention-design-principles.md#absence-channel-coverage) = 「ある事実の不在断定前に全 channel category sweep」 (= **channel 軸** absence)

各 sibling は mechanism / domain が異なる related axis (= 「sibling」 framing は marginal、 strict 1-to-1 mapping ではない)。 本節 (= citation 軸 wording) の直接の layer 1 anchor は存在せず、 本節がその新 niche を埋める。

---

## <a id="framework-calibration"></a>Framework calibration (= 申請の性質ごとに評価軸を調整)

同じ審査区分 / 同じ field 内でも、 **申請の性質によって適用 framework は変えるべき**:

⚠️ **field-dependent (= 下記 examples は physics / 数理科学 系の慣例)**: biology / 社会科学 / 人文 系等では別 categorization (= 例: 実証研究 vs 理論研究 / 質的 vs 量的 / 介入 vs 観察) が適切。 reviewer の domain expertise で field-specific framework を選ぶ。 下記表は **pattern の例示**であって全分野 universal な categorization ではない。

| 申請性質 | 適切な評価軸 | 不適切な criteria 持ち込み |
|---|---|---|
| **Pure theory** | mathematical / structural significance、 理論的位置付け、 後続研究の足場 | 「実験 phenomenology 接続」 「短期 SM 拡張 prediction」 (= category error) |
| **Phenomenology** | 実験 cross-check、 prediction の testability、 collider impact | 「純数学的 elegance」 のみで評価 |
| **Experiment** | 実験設計、 system sensitivity、 background control | 「理論 originality」 のみで評価 |
| **Consolidation work (= 整理研究)** | 領域整理の need、 後続研究の足場価値 | 「直接の新規 discovery」 (= consolidation の意義を defeat) |

### Trap: 同区分内 N 件 連続 review 時の framework 引きずり

同区分内で複数申請を順 review する時、 **1 件目の criteria を 2 件目に無批判 transfer する反射**が起きる。 例:

- (1 件目) = phenomenology 申請 → 「実験 cross-check」 が valid criteria → 4 score
- (2 件目) = pure theory 申請 → 「実験 cross-check」 を持ち込んで 2 score を出す ← **category error**

各申請を **独立 evaluate** する。 申請性質を identify した上で適切な framework を選ぶ。 これは [`convention-design-principles.md §4 (= #orient-before-act)`](../docs/convention-design-principles.md#orient-before-act) の applied form。

### 関連: AI による review draft の framework error

AI が複数申請を続けて draft する時、 同じ framework が転用される bias が強い。 reviewer は AI 解説を読む時、 「この申請性質に framework は合っているか」 を **明示的に check** する。 framework error が見つかれば AI に再評価 request、 もしくは reviewer が独立 judgment。

---

## <a id="scoring-scale-calibration"></a>Scoring scale calibration (= 項目別 vs 総合の scale 不整合)

⚠️ **scope caveat**: 本節 pattern は主に **日本の grant peer review system** (= 科研費 / 学振 / 各種財団 等) で observed。 international journal peer review (= 「accept / minor revision / major revision / reject」 等の 4 段階で項目別なし) では構造が異なる。 reviewer は自分の system で scale 設計を毎回確認、 本節 pattern が適用可能か判断。

(observed pattern as follows) — 多くの (日本系) peer review system で **項目別評点と総合評点で scale の意味が異なる**:

- 項目別 4 = "outstanding aspect" 程度
- 総合 4 = "exceptional overall" (= 1 段階上の reservation)

例 (= 一般的 4 段階):

| score | 項目別 label | 総合 label |
|---|---|---|
| 4 | 優れている (outstanding aspect) | 非常に優れている (exceptional overall) |
| 3 | 良好 (good aspect) | 優れている (strong overall) |
| 2 | やや不十分 | 普通 (average) |
| 1 | 不十分 | 劣っている |

### Trap: arithmetic inconsistent patterns

reviewer が item 評点を出した後、 総合評点を「平均ぽく」 出す reflex で **arithmetic inconsistent な pattern** を作りやすい:

- **項目 4,4,4 + 総合 3** = 「全 aspect 優れているが総合は 1 段下」 → 不自然 (= items が max なのに total が下)
- **項目 3,3,3 + 総合 4** = 「全 aspect 良好だが総合は exceptional」 → 不自然 (= items が good で total が exceptional は jump)
- **項目 3,3,4 + 総合 3** = 「主に良好 + 1 件 outstanding + 総合 strong」 → 一貫
- **項目 3,4,4 + 総合 4** = 「2 件 outstanding + 総合 exceptional」 → 一貫
- **項目 4,4,4 + 総合 4** = 全 outstanding + exceptional total → 一貫

### 規律

- 評点を出す前に **scale の意味を毎回読み直す** (= memory に頼らない)
- 項目別と総合の **整合性 pattern を明示 check**
- 「平均ぽく」 でなく、 reviewer の overall holistic judgment を反映
- 同 case 内で複数の評価 軸が混在する時 (= 例: applicant 経歴 + project content + 計画妥当性 等)、 各 axis を独立に評価 + 総合は holistic synthesis

---

## <a id="scan-pdf-transcription"></a>Scan PDF → markdown transcription discipline

申請書 / paper が scan PDF / image 形式の時、 markdown transcription を作る:

### 手順

1. 各 page を画像として Read (= LLM の vision で読む)
2. markdown structure で原本を mirror (= sections / tables / lists)
3. YAML frontmatter で source files + transcription_date + 不確実 cell の marker
4. 数値 (= budget 等) は table 形式で preserve
5. 図 (figure) は内容説明のみ placeholder (= 画像本体は別 file 参照)

### 不確実 cell の marker

scan 解像度限定で読み取り不能 / 不確実な cell は **`(read unclear)`** marker:

```markdown
| 年度 | 事項 | 金額 |
|---|---|---|
| Y1 | (国内学会出張、 read unclear) | 110 |
| Y1 | (read unclear) | 80 |
| Y1 | (計) | **250** |  ← 列計は明確に読めた場合のみ確定
```

reviewer 側で原本 (= PDF / 紙原本) を直接照合する際の **flag** として機能。

### 関連: 既存 layer 1 doc

- `office-files.md` (= 入口) = Excel / Word / PDF / pptx の handling 全般
- `office-automation.md#scan-pdf-pixel-anchor-overlay` = scan PDF に文字 overlay する別 work flow
- 本節は **scan PDF を読んで markdown 化する work flow** = 上記 2 doc とは scope 直交

---

## <a id="submitted-score-irreversibility"></a>提出済 score の不可逆性 + audit-trail

電子審査システム / online portal に評点 + 審査意見を submit すると **通常不可逆** (= 訂正は事務担当者経由の特殊 procedure)。

### 規律

- submit **前** に `scores.md` で確定記録 (= reviewer 判断の正本化)
- submit **後** は `scores.md` が permanent audit-trail
- 後年 (= 数年後) の自分が「あの review で何を judgment したか」 を再現可能な形で残す
- 評点変更時 (= rare) は `scores.md` の更新履歴に追記、 旧 version を削除しない

### 守秘義務との両立

peer review の resourcing は通常 confidentiality 要件あり (= 審査委員であること自体 / 知り得た情報を第三者に漏らさない)。 `scores.md` 等の SoT は:

- private repo + git-crypt 暗号化で local 保管 (= GitHub 上 ciphertext)
- 第三者 (= 他 reviewer / 申請者 / 公衆) への漏洩は厳格に維持
- AI への入力可否は review system / agency の規約に従う (= 一部 system で「審査資料を生成 AI に入力しない」 という要望あり、 単なる要望 ≠ 守秘義務本体、 user 判断で運用)

---

## <a id="cross-references"></a>Cross-references

### Sibling docs (= 直接関連)

- **自分の paper 内部の structure audit**: [`paper-audit.md`](paper-audit.md) (= forward refs, duplicates, structure)
- **自分が rebuttal letter を書く (= author response)**: [`rebuttal-letter.md`](rebuttal-letter.md)
- **自分が grant 申請書を提出**: [`erad-submission.md`](erad-submission.md)
- **自分の paper を journal / arXiv 投稿ポータル経由で提出**: [`paper-submission.md`](paper-submission.md)
- **メール身元確認 (= 受信側 verify)**: [`research-email.md §pre-outreach-identity-check`](research-email.md#pre-outreach-identity-check)

### 一般則 (= meta level)

- **SoT 重複避ける + role 別分離**: [`convention-design-principles.md §2 (= #no-duplicate-rules)`](../docs/convention-design-principles.md#no-duplicate-rules)
- **単一情報源 null 結論飛躍**: [`convention-design-principles.md §3 (= #rule-addition-criteria)`](../docs/convention-design-principles.md#rule-addition-criteria)
- **Framework calibration の一般則**: [`convention-design-principles.md §4 (= #orient-before-act)`](../docs/convention-design-principles.md#orient-before-act)
- **規約は文脈 / メカニズムは制御**: [`convention-design-principles.md §8 (= #rule-vs-mechanism)`](../docs/convention-design-principles.md#rule-vs-mechanism)

### Scan / file handling

- **Office files 入口**: [`office-files.md`](office-files.md)
- **PDF / Excel / Word 自動化 gotchas**: [`office-automation.md`](office-automation.md)
