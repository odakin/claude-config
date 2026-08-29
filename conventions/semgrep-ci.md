<!-- doc-meta
when: Semgrep を CI で運用する・finding を読む/消す・false positive を nosemgrep 注記するとき
category: infra
summary: SARIF は suppress 済み finding も残す (#sarif-suppressions を filter しないと「注記が効かない」と誤読)。 nosemgrep は match 開始行の行末 or 直前の純粋 comment 行のみ有効 — Python の multi-line call は match が引数行に anchor して trailing 注記が届かない (#nosemgrep-placement)。 local 再現は CI と同一 rule pack が必須 + 毒入り fixture で検出能力自体を検証 (#local-repro)
-->
# Semgrep CI 運用 (finding の読み方・消し方)

> workflow の**配置・repo baseline・Dependabot merge 運用**は sibling
> [`github-security-automation.md`](github-security-automation.md) — 本 doc は
> 配置済み Semgrep の finding を読む・triage する・FP を注記する側。

Semgrep を CI に置く典型形は 「`semgrep ci --sarif --output=… || true` + SARIF を artifact 保存」。
この形では **workflow の success/fail は finding の有無を語らない** — finding は SARIF を
取得して parse するまで見えない (`gh run download <id> -n <artifact名>`)。

## <a id="sarif-suppressions"></a>SARIF は suppress 済み finding も残す

nosemgrep で抑制した finding は SARIF から消えず、
`"suppressions": [{"kind": "inSource"}]` 付きで**残る** (= SARIF 仕様)。
parse 時に suppressions 非空を除外しないと 「注記したのに残っている = 効いていない」 と
誤読する (2026-08-29 に実際に一度誤読)。 live finding = `suppressions` が無い result のみ。
severity は `runs[].tool.driver.rules[].defaultConfiguration.level` (error / warning / note)
を ruleId で引く。

## <a id="nosemgrep-placement"></a>nosemgrep 注記の置き方

有効な位置は 2 つだけ: **match 開始行の行末** trailing、 または **直前行の純粋 comment 行**。

- rule ID は SARIF の `ruleId` 全文 (full path 形式) をそのまま使う。
- **directive の後ろに説明文を続けない** — `# nosemgrep: <id>` の id token に prose が
  混入して照合が壊れる。 理由説明は別の comment 行に書く。
- ⚠️ **Python の multi-line 呼び出しは match 開始行が引数行になる** rule がある
  (例: `subprocess.run(\n    [cmd], …)` は 2 行目が match 開始)。 この場合
  `run(` 行の trailing 注記も、 その直前行の comment も届かない — **呼び出しを
  1 行に畳んで trailing 注記**が確実 (2026-08-29 実測)。
- 注記は「FP と検証した証拠 + 理由 1 行」 とセットで書く (= 将来の読者が再検証できる形)。

## <a id="local-repro"></a>local 再現 — push して CI を待たない

`pip install semgrep` → CI の workflow が指定する **rule pack と同一構成**で
`semgrep scan --config p/… <file>` を回す。 pack が 1 つでも欠けると当該 rule ごと
消えて「再現しない」 になる (= rule は pack 所属、 finding 再現には構成一致が必須)。

**「0 件」 は 「検出器が働いた上での 0 件」 と 「検出器が寝ている 0 件」 を区別できない** —
config 破損や flag 相違は「クラッシュ + stdout 空」 で clean と誤読されうる。 わざと
違反を含む毒入り fixture を 1 つ流して flag されることを確認してから本番 file の 0 件を
信じる (yamllint 等の他 linter でも同じ discipline が効く)。

## triage の目安

- **error 級 (defaultConfiguration.level = error) から**。 warning 級は audit rule 由来の
  定型 noise (依存設定の推奨 / mutable action tag / 取り込んだ外部データ内のリンク等) が
  大半を占めやすい — 直すか、 FP なら注記、 自作 code でない vendored データは
  `.semgrepignore` で path ごと除外 (= 実 finding の S/N を保つのが目的)。
- 判定に迷う finding は該当行を**読んで**から決める (rule 名だけで机上判定しない)。
