# GitHub Security Automation

Repo 群を横断する **Dependabot / CodeQL / Semgrep / auto-merge** 系の自動化 + 関連 gotcha の規約。 ある GitHub user / org が一定数 (= ~10+) の repo を抱えるようになった時点から有用。

## 1. Baseline 構成 (= 全 repo 共通)

```
[1] Dependabot alerts (= vulnerability-alerts) ─── 全 plan 無料、 全 repo に有効化
[2] Dependabot security updates (= automated-security-fixes) ── 全 plan 無料、 自動 PR
[3] Dependabot version updates (= .github/dependabot.yml) ──── code repo に monthly schedule
[4] CodeQL Default (= 公開 repo は無料、 private は GHAS 必要) ── 公開 code repo に対し有効化
[5] Semgrep workflow (= .github/workflows/semgrep.yml) ─────── private code repo に対し配置
[6] Dependabot auto-merge workflow ─── github-actions + patch/minor を自動 merge
[7] branch protection (= main の force-push / delete 禁止) ── 公開 repo は無料、 private は Pro 必要
[8] Push protection + Private vulnerability reporting ────── 公開 repo は無料
```

各 step は **idempotent** に design すること (= 既設定なら no-op)、 新 repo 作成時の reproducibility を担保。

## 2. Free plan の silent rejection に注意

GitHub Free plan + private repo で **API は 200 を返すが設定は反映されない** silent rejection が複数機能で発生:

| API | Free private 挙動 | 対処 |
|---|---|---|
| `PATCH repos/{r} -F allow_auto_merge=true` | 200 OK だが state は false のまま | verify-after-write (= GET で実 state 確認) |
| `PUT repos/{r}/branches/{b}/protection` | 403 "Upgrade to GitHub Pro" | error 期待、 set +e / set -e で wrap |
| `PATCH repos/{r}/code-scanning/default-setup -F state=configured` | 403 "Advanced Security must be enabled" | error 期待 |
| `PATCH repos/{r} -F security_and_analysis[secret_scanning_push_protection][status]=enabled` | 200 OK だが state は disabled | verify-after-write |

**規律**: setting 変更系 API は必ず write 後に read で verify、 報告は実 state ベース。 「API が 200 返したから success」 を rely しない。

## 3. Auto-merge workflow の設計

### Trigger 選定

```yaml
on: pull_request_target
```

`pull_request` ではなく `pull_request_target` を使う。 理由:

- `pull_request` = fork PR で secrets 不可、 Dependabot bot もこれに該当
- `pull_request_target` = base branch context で動作、 `GITHUB_TOKEN` の write 権限あり

**Security note**: `pull_request_target` は PR の HEAD コードを `actions/checkout` で取り込むと untrusted code 実行リスク (= GitHub Actions security docs 頻出警告)。 本 pattern は **checkout なし**で `gh pr merge` のみ呼ぶため typical vuln を構造的に回避。

### Capability check で Free private 対応

`allow_auto_merge=false` な repo で `gh pr merge --auto` を呼ぶと "Auto-merge is not allowed" で job fail → user が毎 PR で red X を見る。 これを notice 化:

```yaml
- name: Check auto-merge capability
  id: capability
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    available=$(gh api "repos/${{ github.repository }}" --jq '.allow_auto_merge')
    echo "available=$available" >> "$GITHUB_OUTPUT"
    if [ "$available" != "true" ]; then
      echo "::notice::auto-merge unavailable (likely Free plan + private). PR will remain open for manual merge."
    fi

- name: Auto-merge safe updates
  if: |
    steps.capability.outputs.available == 'true' && (
      steps.meta.outputs.update-type == 'version-update:semver-patch' ||
      steps.meta.outputs.update-type == 'version-update:semver-minor' ||
      steps.meta.outputs.package-ecosystem == 'github-actions'
    )
  run: gh pr merge --auto --squash --delete-branch "$PR_URL"
```

Pro / 公開 repo では auto-merge 動作、 Free private では notice + 手動 merge。

### Auto-merge 対象の safety cutoff

- 全 `github-actions` ecosystem (= deterministic action name + version 変更のみ)
- 他 ecosystem の `patch` + `minor` semver update

`major` は **review に残す** (= semver で breaking 可)。 composite (= 1 PR で複数 package) も判定不能なので残す。

## 4. Workflow permissions: explicit declaration

CodeQL の `actions/missing-workflow-permissions` 警告は **default token が write 過剰** なため。 minimum 権限を explicit に宣言:

```yaml
permissions:
  contents: read   # 読み取りのみ workflow
  # または
  contents: write  # commit/release/tag が必要なら
  pull-requests: write  # PR コメント / merge
  security-events: write  # SARIF upload
```

migration 時の判定:
- workflow が `git push` / `gh release create` / `gh pr create` / `peter-evans/create-pull-request` / `EndBug/add-and-commit` 等 write 系 keyword を含む → `contents: write`
- それ以外 (= checkout + test + upload-artifact) → `contents: read` で足りる

upload-artifact は contents 権限と独立 (= 必要なら `actions: write` を別途)。

## 5. Monorepo dependabot.yml

サブディレクトリに manifest がある (= e.g. `package.json` が `/sheets/`, `/classroom/` 等に分散) repo は `directory: "/"` 単独では検出不能。 `directories:` (= plural、 list) + `groups:` で対処:

```yaml
version: 2
updates:
  - package-ecosystem: "npm"
    directories:
      - "/sheets"
      - "/classroom"
      - "/photos-picker"
    schedule:
      interval: "monthly"
    open-pull-requests-limit: 10
    groups:
      monorepo-minor-patch:
        applies-to: version-updates
        update-types:
          - "minor"
          - "patch"

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "monthly"
```

`groups:` で minor/patch を 1 PR に集約、 major は個別 PR でレビュー。 limit を 10 程度に上げる (= subdir × ecosystem × group で PR 数増加するため)。

## 6. Dependabot PR review tier discipline

PR を流入させた時の **risk 分類 + 判断基準**:

| Tier | 内容 | 判断 |
|---|---|---|
| 1 | patch / constraint update (= 例: `>=6.0 → >=6.0.3`) | semver 後方互換、 即 merge OK |
| 2 | github-actions major (= 例: `actions/checkout 4→6`) | release notes で output 互換確認後 merge。 通常 backward compat |
| 3 | 同 major 内 minor/patch composite (= 複数 package を 1 PR で) | diff が lock file のみなら merge、 source 変更含むなら manual review |
| 3 | huge version jumps (= 例: `googleapis 144→171`) で **同 monorepo 内の sibling subdir に migration 適用済**な場合 | migration pattern proven、 merge |
| 4 | library 自体の major 移行 (= 例: `Eleventy 2→3`、 `Express 4→5`) | **local build test 必須**、 必要なら backwards-compatible normalizer を先 land + Dependabot PR は後追い merge |

Tier 4 の例:
- `@11ty/eleventy-plugin-rss` v2 → v3 で ESM 化、 `require()` が `{default: fn}` 返す → `addPlugin(obj)` reject
- Fix: `const x = raw.default || raw;` で normalize (= v2 でも v3 でも動く)
- 順序: 1) normalizer fix を main に commit、 2) Dependabot PR merge で実バンプ、 3) normalizer の fallback が活きる

### Tier 4 の「local build test」 が build を持たない project (= 自作 MCP server 等) では何を指すか

build step を持たない runtime project (= 自作 MCP server、 CLI、 script 群) の major dep bump では「build test」 の中身を明示する必要がある。 特に **自作 MCP server は API client (`googleapis` 等) を lazy 構築する** (= 初回 `tools/call` まで未構築) ため、 stdio `initialize` handshake は server boot + protocol negotiation のみ確認し、 **その依存を一切 exercise しない**。 → handshake PASS は major dep bump の検証として **不十分**、 read-only な `tools/call` を投げて**実 API round-trip**まで確認する (= 手順は [`mcp.md` handshake-not-dependency-check](mcp.md#handshake-not-dependency-check))。 staged verification (= 1 dir bump → bump 前と live 結果比較 → 全 dir 展開) で blast radius 最小化。

### Dependabot security-update PR は monorepo の全 manifest を cover しないことがある

`directories:` 設定の monorepo で、 同一脆弱 package が複数 subdir の lockfile に出ても、 Dependabot の **security-update PR は一部 dir のみ生成される** ことがある (= rate-limit / batching)。 partial PR だけ merge すると残 dir の alert を見逃す。 → **全 affected dir 横断の local `npm audit fix` (non-`--force`) の方が完全**。 local fix → push → 残った partial PR は supersede として close、 が確実 (= §10 cascading loop に乗せて PR を 1 件ずつ追う より速い)。

## 7. ESM migration backwards-compatible normalizer

CommonJS → ESM library で `require()` の戻り型が変わる (= bare function → `{default: fn, ...}`) ケースに reusable な pattern:

```javascript
// v1 (CommonJS): module.exports = pluginFn  →  require() returns pluginFn
// v3 (ESM):      export default pluginFn      →  require() returns {default: pluginFn, ...}
const raw = require('@some/library');
const usable = raw.default || raw;
```

`raw.default || raw` で:
- v1 (= old CJS): `raw.default` is undefined、 fallback to `raw` (= bare function) ✓
- v3 (= new ESM): `raw.default` is the function ✓

**Edge case (= 知っていれば足りる)**: `.default` が falsy 値 (= 0 / null / "" 等) を取る ESM module では fallthrough して raw 全体を返す。 plugin library で `.default` が function 以外になることは実務的に稀だが、 numerical / data library で `.default` に数値を export している場合は `raw.default ?? raw` (= nullish coalescing) や明示的 `'default' in raw ? raw.default : raw` で対処。

**運用順序**:

1. Backwards-compatible normalizer を main に先 land (= 現在の v1 でも動く)
2. local で v3 + normalizer の組み合わせを build test (= 動くことを確認)
3. Dependabot PR (= v3 への bump) を merge
4. Normalizer の `.default` 側 fallback が活性化、 build 通る

逆順 (= bumping PR を先 merge) だと CI 落ちる + 修正の commit が分かれて不便。

## 8. `gh` CLI の subtle な gotcha

### `users/X/repos` vs `gh repo list X`

`gh api users/<user>/repos` は **public 限定** (= owner authenticated でも public のみ)。 自分の private repo 含めるには:

```bash
gh repo list <owner> --limit 200 --no-archived --json nameWithOwner
```

Cross-repo automation で repo 列挙する時、 `users/X/repos` を使うと private が漏れる silent bug。

### `gh pr merge` mergeStateStatus = UNKNOWN の対処

`gh pr view N --json mergeStateStatus` が `UNKNOWN` を返す時、 これは「merge 不能」 ではなく **「GitHub が mergeability を計算中」**。 主要 cause:

1. PR 作成直後 (= 数秒〜数分で CLEAN/UNSTABLE/DIRTY に確定)
2. base branch が動いた直後 (= Dependabot PR は自動 rebase されるが、 数十秒〜分かかる)
3. 同 repo の他 PR が merge された直後 (= sibling re-eval)

**対処**: `sleep 30` 〜 `sleep 60` の retry loop。 5 iteration くらいで converge。

```bash
state=$(gh pr view $n -R $r --json mergeStateStatus --jq '.mergeStateStatus')
if [ "$state" = "CLEAN" ] || [ "$state" = "UNSTABLE" ] || [ "$state" = "HAS_HOOKS" ]; then
  gh pr merge $n -R $r --squash --delete-branch
fi
```

`CLEAN`, `UNSTABLE`, `HAS_HOOKS` は merge 可。 `DIRTY` は conflict (= 別対応)、 `BLOCKED` は required check failing (= 別対応)。

### `gh search prs --author=app/dependabot` で横断検索

`gh pr list` は単一 repo 専用。 複数 repo 横断で Dependabot PR を集約するなら:

```bash
gh search prs --author "app/dependabot" --state open \
  --owner <user1> --owner <user2> \
  --json repository,number,title --limit 100
```

`--owner` は repeat 可 (= 複数 user/org 跨ぐ)。 dashboard 系 script で頻出。

## 9. Bash `set -e` + heredoc + `$(...)` の interaction

`set -euo pipefail` 下で heredoc 入りの `$(...)` を書くと、 内部 command の非 0 終了で `set -e` が trip する場合がある (= bash version + `inherit_errexit` shopt 依存)。

**Anti-pattern**:

```bash
set -e
out=$(gh api ... <<EOF
{ ... }
EOF
)
# ↑ gh api が non-zero で exit すると set -e 発火、 以降のコードが走らない
```

**Fix** (= 明示的 bracket):

```bash
set +e
out=$(gh api ... <<EOF
{ ... }
EOF
)
set -e
# ここで $out parse して error message を判定
```

`if ... then ... else ... fi` で wrap する方法もあるが、 heredoc + 複数行 + 出力 capture が絡むと syntax が読みにくくなる。 set +e / set -e bracketing が最も読みやすい。

## 10. Cascading Dependabot PR の convergence loop

Monorepo + `directories:` 設定で 1 PR を merge すると、 **sibling subdir で同 package の同 version bump PR が次々に開く** (= 1 merge → main 動く → Dependabot scan → 別 subdir で同 vuln 検出 → PR open)。

複数 iteration 必要:

```bash
iter=0
while [ $iter -lt 5 ]; do
  iter=$((iter+1))
  prs=$(gh search prs --author "app/dependabot" --state open --owner ... --json repository,number)
  [ "$prs" = "[]" ] && break
  # process each PR
  sleep 30  # let rebase settle
done
```

5 iteration で typically converge。 alert count が一定値以下になったら手動 review に shift。

## 11. Cross-references

- 各 user の repo 集合に対する具体 baseline 適用は **layer 3** (= 個人 prefs) で記録 (= 各自の personal layer に、 例えば security-automation.md のような file を置く)
- 新 repo onboarding script の template は **layer 3** で保持 (= 各自の personal layer、 例えば scripts/secure-new-repo.sh + scripts/templates/)
- visibility 判断 framework も **layer 3** (= 各自の personal layer、 例えば repo-visibility-criteria.md)
- 本 file (= layer 1) は generic pattern + tool-level gotcha のみ
