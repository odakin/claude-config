<!-- doc-meta
when: YAML を読む・書く・新規 data file の形式 (yaml/toml/json) を選ぶ・yamllint を設定するとき
category: infra
summary: YAML の脆さは parser CVE 軸と意味論軸 (仕様どおりの誤読 = Norway problem / colon 誤読 / dup key silent merge #hazard-classes) の 2 軸。 対処 = safe loader 常用 (#safe-loader) + 形式選択の 1 回の問い (#format-choice) + hazard rule 限定 yamllint (#yamllint-hazard-config、 extends:null crash と directive 純粋行の gotcha 込み)
-->
# YAML の脆さと対処 (safe loader / hazard lint / 形式選択)

YAML の「脆さ」 は独立な 2 軸に分解される。 軸ごとに対処の相場が違う。

1. **parser の security 軸** — 仕様が巨大 (anchor/alias の entity 爆発、 custom tag の
   code 実行、 implicit typing) で実装に穴が出続ける。 → safe loader 常用 (#safe-loader)
   で class ごと塞がる。
2. **意味論の軸** — parser は仕様どおりなのに人間の意図と乖離する (#hazard-classes)。
   CVE fix では消えない。 → 記法規律 + lint + schema gate。

## <a id="safe-loader"></a>safe loader を常用する

- Python: 常に `yaml.safe_load` (または `CSafeLoader`)。 `yaml.load` / `full_load` を
  新規 code に書かない。
- JS: js-yaml v4+ は default safe。
- XML でも同型: 外部入力の parse は defusedxml を第一選択 (stdlib ElementTree は
  entity 爆発に弱い)。

## <a id="yaml-11-vs-12"></a>YAML 1.1 と 1.2 で同じ file の意味が変わる

- **PyYAML = YAML 1.1**: `no` → False (Norway problem)、 `12:30` → 750 (60 進)、
  `0755` → 493 (8 進)。
- **js-yaml v4+ = YAML 1.2 core**: 上記は全部ただの文字列。
- ∴ 同じ file を Python と JS の両方が読む pipeline では、 **1.1 で化ける token を
  書かない**のが唯一の安全策 (どちらかの parser に合わせた workaround は他方で壊れる)。

## <a id="hazard-classes"></a>意味論 hazard の類型

| hazard | 化け方 | 防ぎ方 |
|---|---|---|
| truthy token (`no`/`yes`/`on`/`off`) | 1.1 parser で bool | key でも値でも `"no"` と quote |
| key 重複 | 後勝ち silent merge (先の値が機械から不可視) | lint (下記) + 編集時に注意 |
| 値中の「コロン + 空白」 | mapping に誤読 | 値全体を quote。 ⚠️ **valid YAML なので lint 不能** — 消したいなら schema/domain gate 側 |
| version 風 (`3.10`) | float 3.1 | quote |
| implicit octal (`0755`) | 493 | quote or `0o755` |

## <a id="format-choice"></a>形式選択 — 新規 data file を起こす瞬間に 1 回問う

> この file、 本当に YAML が要るか？ (= コメント・複数行文字列・人間の手編集のどれかが必須か？)

| 用途 | 形式 | 理由 |
|---|---|---|
| 人間が手編集する ledger (コメント・複数行 notes 必須) | YAML | コメント + block scalar + 可読性は YAML でしか揃わない。 脆さは本 doc の規律 + gate で受ける |
| flat な config | TOML | implicit typing の罠が無い。 Python 3.11+ は stdlib `tomllib` |
| 機械だけが読み書きする生成物・state | JSON | 曖昧さゼロ。 コメント不要なら YAML を選ぶ理由が無い |

既存 file の形式移行は原則やらない (= コメント喪失 + 移行事故 > 利益)。 隣の file との
pipeline 一貫性は正当な選択理由。

## <a id="yamllint-hazard-config"></a>yamllint は hazard rule 限定で運用する

stylistic rule (indent / line-length 等) を全部有効にすると既存 file への noise が実害
検出を埋める。 hazard 3 rule + syntax (= rule 無しでも常時報告) に絞る
(**実装 = 同 repo [`scripts/check-yaml-lint.py`](../scripts/check-yaml-lint.py)** — fleet の
tracked yaml を横断 lint、 git-crypt lock skip、 毒入り fixture selftest 内蔵。 定期発火面
〔run-all-checks / CI〕 への配線は各 user の personal layer 側):

```yaml
rules:
  key-duplicates: enable
  truthy: {allowed-values: ["true","false","True","False"], check-keys: true, level: error}
  octal-values: {forbid-implicit-octal: true, forbid-explicit-octal: false}
```

- <a id="yamllint-extends-null"></a>⚠️ **`extends: null` を書かない** — yamllint (1.37 実測) は
  extends キーが null だと **crash する** (rc=1 + stdout 空)。 これを「finding 0 件 = clean」
  と誤読しやすい (実際に一度誤読、 毒入り fixture selftest が捕捉)。 「指定 rule のみ」 に
  したいときは extends キーごと省略する。
- GitHub workflow の trigger key `on:` は truthy rule の有名 FP (GitHub parser は対応済み)
  → truthy rule だけ `ignore: [".github/"]` で除外 (dup-key / syntax は workflow にも効かせる)。
- <a id="yamllint-directive-purity"></a>**opt-out directive (`# yamllint disable …`) は純粋行で書く** —
  同一行に説明文を後置すると directive が parse されず silent に無効 (2026-08-29 実測。
  nosemgrep と同じ罠)。 理由説明は次の comment 行に書く。 rule 限定 opt-out は
  `# yamllint disable rule:<rule>` (file 全体は `# yamllint disable`)。
- linter の返り値解釈: rc≠0 ∧ stdout 空 ∧ stderr あり = **linter 自体の故障**であって
  clean ではない — loud に fail させる (semgrep-ci.md #local-repro の毒入り fixture
  discipline と同じ)。
