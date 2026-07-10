<!-- doc-meta
when: 5 分以上かかる生成物の出力先を決めるとき + snapshot artifact を命名するとき
category: infra
summary: `-output /tmp/...` reflex 防止 (= OCR / ML / 数値計算で 5 分以上要する artifact をリポ内永続化、 hooks/expensive-tmp-guard.sh で機械的検出) + snapshot artifact の命名規約 (= 日付〔同日複数なら時分〕+ 入力状態 ID 〔git 由来は commit range〕 を filename に焼く、 snapshot vs view の名前区別、 #snapshot-artifact-naming)
-->
# Expensive intermediate artifacts は `/tmp` に置かない

> 適用対象: OCR / ML training / 数値シミュレーション / 重い CI ビルド等で「再生成に **5 分以上** かかる」 中間成果物を扱うリポ。
>
> 関連 hook: `claude-config/hooks/expensive-tmp-guard.sh` (PreToolUse Bash で `Audiveris ... -output /tmp/...` 等のパターンを機械的に検出)

---

## 問題

CLI tool (`Audiveris -output <path>`、`oemer -o <path>`、ML 学習 script の `--checkpoint-dir <path>`、数値シム の `-OUTPUT_DIR=<path>` 等) に出力先を渡すとき、 reflex で `/tmp/<dir>/` を書きがち。 これは:

- (a) **scratch (= 数秒〜分単位で再生成可)** にとっては合理的
- (b) **expensive intermediate artifact (= 再生成に 5 分以上、かつ input state — DPI / version / override constants — が再現に必要)** にとっては運用ミス

(b) を `/tmp` に置くと:
- macOS reboot で消える (= macOS は `/tmp` を起動時に sweep)
- 数日経過で `tmpcleaner` 系の OS ジョブが消す可能性
- 容量逼迫時に他プロセスから割を食う
- 「数時間後の自分」 が path を忘れて再生成する羽目になる
- **session 圧縮 / autocompact 後の Claude が文書中の `/tmp/...` 参照を「意味のある永続 path」 と誤解** (= リポ内文書から /tmp 配下を pointer として参照する自体が design smell)

---

## 実例 (2026-05-10、 楽譜分析 OCR pipeline)

Audiveris OCR を 1200/2400/4800/9600 DPI で実験中、 4 通り × 2 page = 8 retry を `/tmp/audiveris-{2400,4800}dpi-{p1,p12}-{retry,override}/` に出力。 各 `.omr` の生成に **10〜90 分** (= 4800 DPI BEAMS step 単独で 17 分、 全 step で 90 分超)、 `maxPixelCount` / `sheetStepTimeOut` の `-constant` override が必要。 8 hours 後に user 指摘「永続化されとらんやん」 — 当該リポの `SESSION.md` / `plans/` が `/tmp/audiveris-2400dpi-p12-retry/p-12.omr` を後段 GUI 編集の入力素材として参照しており、 reboot 後は再生成 ~15 min 必要な状態だった。

復旧: リポ内 `scores/<work>-ocr-experiments/{2400dpi-p1-control,2400dpi-p12-retry,4800dpi-p1-regression,4800dpi-p12-success}/` 4 サブディレクトリへ計 6.3 MB を `cp` 永続化、 全文書の `/tmp/...` 参照を新 path へ書き換え、 `*.log` の global gitignore に repo-local exception を追加 (= debug log は GUI 編集の reference 価値ありで track 必須)。

詳細 RCA は personal layer の reflex-trap 文書 + 当該リポの experiment dir README に記載 (= 「関連」 セクションの pointer 参照)。

---

## 防止策の階層

### ゲート質問 (= 着手前に必ず通す)

CLI tool に出力先 path を渡す前に問う:

> **「この出力、 reboot 後に再生成すると **5 分以上** かかるか? かつ input state (= 入力 file の DPI / version / override constants 等) が再現困難か?」**

- **No** (= 数秒〜数分で再生成、 input state も自明) → `/tmp/<dir>/` で OK
- **Yes** → リポ内に永続 placement、 + experiment context を記述する README.md 必須

### 配置先の決め方

リポ内の既存ディレクトリ規約に従う。 一般則:

| リポタイプ | 永続化先の例 |
|---|---|
| 楽譜・楽曲解析 | `scores/<work>-<engine>-experiments/` |
| ML training | `data/checkpoints/<run-id>/` または `experiments/<run-id>/` |
| 数値シミュレーション | `data/runs/<config-hash>/` または `outputs/<run-id>/` |
| OCR 一般 (= 文献 PDF, 画像 archive) | `data/ocr-<engine>/<source>/` |

実際の path は repo の `DESIGN.md` / `CLAUDE.md` に明記。 規約が無いリポなら **規約を作るタイミング** (= DESIGN.md に subdirectory pattern を documented してから配置)。

### Per-experiment README.md (必須)

永続化したサブディレクトリには README.md を置き、 以下を記述:

- **なぜ persist しているか** (= 再生成コスト + input state 再現困難性)
- **ディレクトリ構成** (= experiment 別役割表 — 各サブディレクトリの内容と意味づけ)
- **関連 plan / SESSION での参照箇所** (= どの doc が当該 artifact を pointer として参照しているか)
- **何が verify 済か** (= データから引き出した結論、 後の reader が同 artifact を再解釈する負担を減らす)
- **再生成手順** (= 万が一壊れた / 紛失した時の rebuild commands、 input state — DPI / `-constant` override 等 — を含めて再現可能に)

### `.gitignore` の global ignore に注意

`*.log` 等 global gitignore で除外される拡張子を experiment dir で track したい場合は、 リポローカル `.gitignore` で `!<dir>/**/*.log` exception を追加。 OCR / ML 系 log は debug trace (NPE / warning / metric) を含むため reference 価値あり、 安易に ignore しない。

---

## <a id="snapshot-artifact-naming"></a>Snapshot artifact の命名 (= 入力状態を filename に焼く)

永続化する artifact が「ある時点の入力状態を凍結した snapshot」 (= latexdiff PDF / 特定 commit のビルド成果物 / 外部サービスの membership dump / 実測データ等。 再生成が安価な snapshot にも適用してよい naming 一般則) の場合、 filename に次の 2 つを焼く:

1. **日付 `YYYY-MM-DD`** — 常に。 同日に複数回生成し得る種類なら **時分 `HHMM`** も付ける
2. **入力状態の識別子** — snapshot が「何を」 凍結したか:
   - **git 状態由来** (latexdiff / 特定時点のビルド) → **commit hash (range)** が正確な identity。 日付は人間用の staleness 可視化として併記する (= hash だけでは古さが読めない)
   - **外界由来** (membership dump / 実測データ / API response) → timestamp 自体が identity (= 日付粒度で足りることが多い)

例:

- `latexdiff-2026-07-03-1647-a1b2c3d-to-e4f5a6b.pdf` (= git 由来 + レビュー中の同日再生成があり得るので時分付き)
- `members-snapshot-2026-07-03.yaml` (= 外界由来、 daily 粒度で十分)

**理由**: 入力状態が名前に無い snapshot (`diff-latest.pdf` / `diff-since-<base>.pdf` 等) は (a) 後から「何に対する snapshot か」 を再構成できない (b) 同日の再生成で silent 上書きされ、 受け手が新旧を区別できない (c) stale 化しても誰も気づかない。

**snapshot vs view の区別**: 「常に最新へ追従する固定名 mirror」 を意図する場合 (= 例: ビルド成果物の `<paper>-latest.pdf` 自動 publish) は **view** であって snapshot ではなく、 固定名が正しい。 凍結するなら日付+識別子、 追従するなら固定名 — どちらの意図かを名前で宣言するのが本質。

**disposal 条件**: 使い捨て snapshot は「いつ消してよいか」 (= レビュー完了後 / 次回 release 後 等) を commit message か README に 1 行残す (= 後の session / collaborator が削除判断できる)。

関連: [`docs/convention-design-principles.md` §2.5 (= #sot-duplication-trichotomy)](../docs/convention-design-principles.md#sot-duplication-trichotomy) — snapshot は「派生可能な値は格納しない」 原則の明示的例外であり、 例外だからこそ marker (= 名前の日付 + 入力識別子) を必須にする。

---

## Anti-pattern

- **「実験中だから /tmp で十分」**: 実験成功直後の判断は valid だが、 user feedback が入った瞬間に「再現入力素材」 に昇格する。 移行のタイミングを逃すと永久に /tmp。 対策: feedback turn で permanence を再評価する習慣
- **「reboot しなければ大丈夫」**: macOS は不定期に sleep / wake / kernel panic / forced restart で reboot する。 「数日触ってないから永続的だろう」 と判断するのは経験則違反
- **文書から `/tmp/...` を pointer として参照**: SESSION.md / plans/ 等で `/tmp/audiveris-2400dpi-p12-retry/p-12.omr` のように書くと、 別セッションの Claude が「この path は意味がある」 と誤解する。 リポ内 path のみ pointer として valid
- **「後でまとめて移す」**: 8 hours 後の user 指摘で初めて気付くパターン。 移行コストは 5 分でも、 引き伸ばすほど「どれが価値ある artifact か」 の判断が劣化する

---

## 関連

- 機械的検出: `claude-config/hooks/expensive-tmp-guard.sh` (= PreToolUse Bash で `Audiveris ... -output /tmp/...` 等のパターンを `permissionDecision: ask` で警告)
- 類縁規約: `claude-config/conventions/scientific-computing.md` (= 数値計算の silent bug)、 `claude-config/conventions/dropbox-refs.md` (= 共有 PDF の参照規約)
- owner の personal layer (= layer 3、 collaborator は access 不要) には本規約の application 例 / 反例 / 個人特有の reflex-trap 規律が記録されている。 本 file が universal な核 (= 規約として完結)、 personal layer は個人の歴史的事例 + reflex 規律 (suppl reference、 必須参照ではない)
