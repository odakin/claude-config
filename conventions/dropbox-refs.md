# Dropbox 共有 PDF への参照規約

複数の git リポから「Dropbox 上の特定フォルダにある参照 PDF」を、リポ内の安定した相対 path で参照したいときの標準パターン。

> 関連スクリプト:
> - `scripts/dropbox-root.sh` — Dropbox install root を OS 横断で resolve
> - `scripts/setup-dropbox-refs.sh` — 後述の YAML を読んで symlink を作る
>
> Dropbox 以外のクラウド (OneDrive / Google Drive) への応用は §10。

---

## <a id="pattern-a-vs-b"></a>0. まず決める: Pattern A (Dropbox-direct) か Pattern B (このファイル)

Dropbox にある PDF を git リポから触りたいとき、採りうる戦略は 2 つ。このファイルが詳述するのは Pattern B。Pattern A のほうが適合するケースも少なくないので、着手前に必ず選択する。

### Pattern A: Dropbox-direct working tree

実 git 作業ツリーを Dropbox 内に置き、`<base>/<repo>/` はそこへの symlink にする。参照 PDF・notebook 等の asset は作業ツリーと**同じディレクトリに同居**させ、`./foo.pdf` や `../sibling/` で素朴な相対 path 参照する。

```
$DBROOT/<subpath>/<repo>/          ← 実 working tree、.git/ もここ
├── paper.tex
├── refs.bib
├── external_ref_1.pdf             ← gitignored asset
├── notebook.nb                    ← gitignored asset
└── .gitignore                     ← 上記 asset を ignore

<base>/<repo>  →  symlink to $DBROOT/<subpath>/<repo>/
```

### Pattern B: Independent clone + `dropbox-refs/` symlink (このファイルの主題)

実 git 作業ツリーを `<base>/<repo>/` に置き (通常の clone)、Dropbox 上の asset folder は per-machine の gitignored な `./dropbox-refs/` symlink 経由で参照する。詳細は §1 以降。

### どちらを選ぶか

| 条件 | 推奨 | 根拠 |
|---|---|---|
| 共同編集者と Dropbox folder を共有し、複数 machine で同時に `.git/` を触る可能性あり | **B** | Dropbox 同期 race が `.git/` object store を壊すリスクが実在 |
| リポが multi-machine で同時編集される (solo でもラップトップ + デスクトップ併用等) | **B** | 同上 |
| 共同編集者はいるが git push/pull 経由のみ (Dropbox folder は share しない)、かつ同時編集マシンは実質 1 台 | **A** | Dropbox 同期 race が発生しえない。A のほうが path が単純 |
| solo 運用で Dropbox が自分の素材置き場 | **A** | 同上 |
| arXiv cite だけで完結し Dropbox の参照 PDF を触らない | どちらでもない | 普通の `<base>/<repo>` clone で十分 |

**trade-off の本質**: Pattern B は `.git/` を Dropbox の外に出すことで同期 race を根本排除する代わりに、source と asset の場所が分離して `dropbox-refs` symlink という layer が増える (= 詳細は §9 「Pattern B のメンタルモデル」)。Pattern A は layer が少なく mental model が単純だが、Dropbox 同期が `.git/` を触る前提 — 複数 machine が同じ `.git/` を同時に書くと壊れるので、同時編集の有無が分水嶺。

設計時の思考過程と経緯は `DESIGN.md` 「dropbox-refs convention」セクション参照。

### Pattern A の setup と運用

```bash
# 1. Dropbox 内に clone (または既存 working tree を受け入れる)
cd "$DBROOT/<subpath>"
gh repo clone <owner>/<repo>

# 2. <base>/<repo> を symlink にする
ln -s "$DBROOT/<subpath>/<repo>" <base>/<repo>
```

CLAUDE.md には「実 git 作業ツリーは `$DBROOT/<subpath>/<repo>/`、`<base>/<repo>` は symlink」と明記する。`dropbox-collabs.yaml` への entry は **不要** (dropbox-refs を使わないので)。`.gitignore` に `/dropbox-refs` 行を入れる必要も無い。

### Pattern A ↔ B の migration

#### A → B (Dropbox から分離する)

複数 machine 同時編集が必要になった、共同編集者を Dropbox folder に招きたい、といった場合:

```bash
# 1. <base>/<repo> が Dropbox への symlink なら外す
rm <base>/<repo>
# 2. 独立 clone
cd <base> && gh repo clone <owner>/<repo>
# 3. Dropbox 側の .git/ を削除 (= asset folder 化)
rm -rf "$DBROOT/<subpath>/<repo>/.git"
# 4. personal-layer の dropbox-collabs.yaml に entry 追加
# 5. claude-config/scripts/setup-dropbox-refs.sh を実行
# 6. <repo>/.gitignore に /dropbox-refs を追加
# 7. <repo>/CLAUDE.md に dropbox-refs 案内セクションを追加 (§3.4 テンプレ)
```

#### B → A (Dropbox 内に戻す)

共同編集が git 経由だけに落ち着いた、duplicate の混乱を避けたい、といった場合:

```bash
# 1. working tree を clean にしておく (uncommitted なし)
# 2. .git/ を Dropbox tree にコピー
cp -R <base>/<repo>/.git "$DBROOT/<subpath>/<repo>/.git"
# 3. Dropbox tree 側で tracked file を復元 (以前 deleted にしてたもの全部)
cd "$DBROOT/<subpath>/<repo>" && git checkout -- .
# 4. 古い <base>/<repo> を削除して symlink に置き換え
rm -rf <base>/<repo>
ln -s "$DBROOT/<subpath>/<repo>" <base>/<repo>
# 5. /dropbox-refs symlink と .gitignore の /dropbox-refs 行を削除
rm <base>/<repo>/dropbox-refs
# (.gitignore を編集)
# 6. personal-layer の dropbox-collabs.yaml から entry を削除
# 7. CLAUDE.md を Pattern A 用に書き直す
# 8. commit + push
```

落とし穴:

- step 3 の `git checkout -- .` を忘れると、以前の移行で Dropbox 側から削除した tracked file (`.gitignore`, `.gitattributes`, `CLAUDE.md` 等) が git status で "deleted" として残る
- step 5 の `dropbox-refs` 行を残したまま `/dropbox-refs` symlink 自体を削除すると、symlink は不在なのに `.gitignore` だけ古い、という不整合になる
- step 7 の CLAUDE.md の記述が古いと、次に Claude/自分が来たとき Pattern B だと誤解する

---

## <a id="what"></a>1. What

各リポの直下に gitignored な `dropbox-refs/` symlink を置き、そのターゲットを Dropbox 内の subpath にする。スクリプト・notebook・TeX・ノートからは `./dropbox-refs/foo.pdf` という相対 path で参照する。

```
~/Claude/<repo>/
├── .gitignore        ← `/dropbox-refs` を含む
├── CLAUDE.md         ← 「共同 PDF」セクションで dropbox-refs/ の存在を案内
├── dropbox-refs/     ← per-machine の symlink (gitignored)
│                       → $DBROOT/<subpath>/
└── ...
```

`dropbox-refs/` 自体は per-machine で作られる symlink なので git には入らない。リポをチェックアウトしたユーザーは、後述の setup を経て自分の machine 用 symlink を作る。

---

## <a id="why"></a>2. Why

- Dropbox のインストール先 (`~/Dropbox`, `~/Library/CloudStorage/Dropbox`, `~/Library/CloudStorage/Dropbox-Personal`, …) は OS / Dropbox バージョン / multi-account 構成によって違う。共有リポに絶対パスを書けない
- 共同編集者ごとに Dropbox 内のフォルダ階層も違う可能性があるため、symlink の target も per-user で決める
- 「PDF 置き場の場所」をリポ自身のドキュメント (CLAUDE.md) と並べて 1 箇所に集約できる
- 同パターンを複数の共同研究で再利用できる
- リポ内で相対 path (`./dropbox-refs/...`) で参照できるので、TeX や notebook の include/load 系がそのまま動く

---

## <a id="how"></a>3. How

### <a id="registry"></a>3.1 Personal layer の registry (`dropbox-collabs.yaml`)

各 user は自分の personal layer (例: `~/Claude/<personal-layer>/`) に `dropbox-collabs.yaml` を置く。Schema:

```yaml
# <personal-layer>/dropbox-collabs.yaml
# Map collaboration name → Dropbox-relative subpath. Per-user, per-machine.
collaborations:
  <repo-name>:
    subpath: <Dropbox からの相対 path>
    description: 自由記述 (optional)
```

具体例 (架空):

```yaml
collaborations:
  combined-results:
    subpath: Shared/Research/CombinedResults/refs
    description: 共同研究 PDF 置き場
```

`subpath` は **その user の Dropbox install root からの相対 path**。machine / user / OS で違う可能性があるため、personal layer に閉じ込める。共有リポ (claude-config) には書かない。

`<repo-name>` は canonical 名。setup スクリプトは `<base-dir>/<repo-name>/dropbox-refs` に symlink を作るので、ローカル checkout のディレクトリ名と一致させる必要がある。

### <a id="setup-script"></a>3.2 Setup script

**前提**: Python 3 + PyYAML (`python3 -c "import yaml"` で確認可能)。macOS は Homebrew 経由の Python 3 で `pip3 install pyyaml`、Linux は `pip install pyyaml` または distro パッケージ (`python3-yaml`) で導入。

```bash
~/Claude/claude-config/scripts/setup-dropbox-refs.sh \
    ~/Claude/<personal-layer>/dropbox-collabs.yaml
```

これで YAML の各 entry について `<base-dir>/<name>/dropbox-refs` symlink が `$DBROOT/<subpath>` を指すよう作成される。

特性:

- **idempotent**: 既存 symlink が同じ target なら何もしない (silent)
- **change のみ表示**: CREATED / UPDATED / WARN のみ stderr / stdout に出力
- **non-fatal warnings**: repo dir 不在 / Dropbox target 不在は WARN で skip、exit 0
- **non-clobber**: 既存の通常ファイルやディレクトリが destination にあれば error で停止 (ユーザーデータを上書きしない)

### <a id="auto-run"></a>3.3 自動実行

`claude-config/setup.sh` は personal layer を検出した後、その中に `dropbox-collabs.yaml` があれば自動で setup-dropbox-refs.sh を呼ぶ。さらに personal layer の `.git/hooks/post-merge` に同スクリプトを呼ぶ hook を install するため、`git pull` で YAML を更新したら symlink が自動で再生成される。

新マシンへの bootstrap も既存リポでの YAML 更新も、明示的な手動 setup なしで symlink が最新に保たれる。

### <a id="per-repo-config"></a>3.4 各リポへの設定

リポ root に以下を追加:

- `.gitignore` に `/dropbox-refs` 行
- `CLAUDE.md` に「共同 PDF 置き場」セクション

CLAUDE.md セクションのテンプレート:

```markdown
## 共同 PDF 置き場

参照論文 (PDF) は Dropbox の `<subpath>/` にあり (collaborator
ごとの subpath は personal layer の `dropbox-collabs.yaml` を参照)。

- ローカル symlink: `./dropbox-refs/`
- セットアップ: `~/Claude/claude-config/scripts/setup-dropbox-refs.sh
                ~/Claude/<personal-layer>/dropbox-collabs.yaml`
- 詳細規約: `~/Claude/claude-config/conventions/dropbox-refs.md`
```

`<subpath>` は **collaborator 同士で合意した Dropbox 内の場所**を書く (例: `Shared/Project/refs`)。これにより、自分用の registry を持っていない collaborator も Dropbox を Finder で navigate して同じ場所にたどり着ける。

さらに collaborator (および将来の自分) が「2 つの sync チャネルの境界」 を誤解しないよう、 §9 のメンタルモデル節を SETUP.md (or CLAUDE.md) に inline するか参照することを推奨する。

---

## <a id="dropbox-root-resolution"></a>4. Dropbox install root の解決

`scripts/dropbox-root.sh` は以下の優先順で resolve する:

1. `$DROPBOX_ROOT` 環境変数 (override)
2. `~/.dropbox/info.json` の `personal.path`
3. 同 `business.path`
4. `~/Dropbox`
5. `~/Library/CloudStorage/Dropbox`
6. `~/Library/CloudStorage/Dropbox-Personal`

すべて失敗すれば非 0 終了で stderr エラー。Linux / macOS legacy / macOS Sonoma+ / multi-account 構成を概ねカバー。Windows-WSL は (1)(4) 経由で動く。Windows-native は別途 `%APPDATA%\Dropbox\info.json` 対応が必要 (現時点 unsupported)。

---

## <a id="when-to-use"></a>5. When to use

- 共同研究のリポで、共著者と Dropbox 上の参照 PDF folder を共有しているとき
- 自分が複数 machine で同じ参照 PDF folder を使いたいとき
- 参照 PDF が大量で git に commit すると bloat する場合
- 参照 PDF が non-arXiv (preprint, 非公開 draft, journal proof, スライド等) で、何らかの共有手段が必要な場合

## <a id="when-not-to-use"></a>6. When NOT to use

- 参照論文がすべて arXiv 公開: refs.bib に `eprint` を入れるだけで足りる。共著者は自分で arXiv から取得すれば良い
- リポ全体を Dropbox に置きたい: 「リポ root 自身を Dropbox folder への symlink にする」whole-repo Dropbox パターンのほうがフィット
- 共同編集者と共有しない、純粋に個人の参照ライブラリ: per-user キャッシュ (例: 物理研究系 user の `<repo>/refs/pdfs/` 等) で足りる
- Dropbox を使っていない user: setup script は personal layer に YAML がなければ何もしないので skip される

---

## <a id="collaborator-same-mechanism"></a>7. Collaborator が同じ機構を使う場合

同じパターンが任意の user に適用できる。各 user が:

1. 自分の personal layer (private repo or local-only directory) を作る
2. その中に `dropbox-collabs.yaml` を置く (canonical 名は collaborator 同士で合意、subpath は自分の Dropbox 構造に合わせる)
3. claude-config を導入し、`./setup.sh` を実行 (もしくは setup-dropbox-refs.sh を直接呼ぶ)

これだけで自分の machine に symlink が生成される。共有リポ側には canonical 名 1 つだけが現れるので、collaborator 全員にとって `./dropbox-refs/` という同じ path で参照できる。

注意点:

- canonical 名は **共有リポのディレクトリ名** に合わせる (例: `<base>/foo/` というリポなら canonical 名も `foo`)
- subpath は user ごとに異なる可能性がある。共有リポの CLAUDE.md には「Dropbox 上で `<subpath>` を探してね」というヒントを書いておくと、registry を持たない collaborator もたどり着ける
- 共有 Dropbox folder の invite (Dropbox UI 上の操作) は機構の対象外。各 user が手動で accept する必要がある

---

## <a id="constraints-known-issues"></a>8. 制約と既知の問題

- **Selective sync**: Dropbox の選択同期で folder を除外していると、target は存在するが中身が "online-only" になる。symlink は問題なく作られるが、ファイル read 時に Dropbox が download を試みる
- **同期競合**: PDF を read-only 運用すれば衝突は起きにくい。複数 user が同じ folder で notebook を同時編集する場合は別途注意 (Dropbox の conflict copy が増える)
- **Path に space や非 ASCII**: scripts は quote 厳守で対応済み。TeX 等で参照する際にも `dropbox-refs/...` (ASCII) を経由するので問題は出にくい
- **Dropbox 解約 / 移行**: 別 cloud に移った場合は `dropbox-root.sh` 相当の resolver を別途書き、setup-dropbox-refs.sh を変更するか、汎用化版に置き換える
- **Windows-native**: 現状 unsupported。WSL なら (1) DROPBOX_ROOT または (4) ~/Dropbox 経由で動く

---

## <a id="pattern-b-mental-model"></a>9. Pattern B のメンタルモデル: 「同一 file への 2 つの access path」 と「同期チャネル 2 系統」

Pattern B では collaborator (および将来の自分) に **2 つの mental confusion 源** が生まれる。 §0 trade-off 表で「mental model layer が増える」 と書いた具体内容がこれ。 Pattern B を採用した repo の CLAUDE.md / SETUP.md には、 以下 2 点を明示することを推奨する。

### <a id="junction-two-paths"></a>9.1 junction = 「同一 file への 2 つの access path」 (= コピーではない)

`<repo>/dropbox-refs/` は **symlink (POSIX) または junction (Windows)** で、 ターゲットは `$DBROOT/<subpath>/`。 すなわち:

```
<repo>/dropbox-refs/foo.tex
≡ $DBROOT/<subpath>/foo.tex   (同一 file への 2 つの path)
```

これは **コピーではない**。 どちらの path で開いても同じ file を編集している。 保存タイミングのズレも同期競合も構造的に起き得ない (= junction の本質)。

初見の collaborator は「Dropbox にもあるし repo にもある = 2 つのコピーを sync する仕組みが要るのか?」 と誤解しやすい。 「junction = 近道、 本体は Dropbox 側 1 つ」 と説明するのが mental model 上有効。

### <a id="two-sync-channels"></a>9.2 同期チャネル 2 系統の table

Pattern B では何が git で運ばれて何が Dropbox で運ばれるかが分裂する。 collaborator にこれを明示する義務がある (= [`shared-repo.md` standalone-operational-definition](shared-repo.md#standalone-operational-definition) の operational 完結性に相当):

| チャネル | 何が運ばれるか | trigger |
|---|---|---|
| Dropbox client | `dropbox-refs/` 内の content (= asset folder = TeX 原稿 / 図 / 参考 PDF 等) | 保存と同時、 Dropbox client が常駐していれば即時 |
| git push / pull | `dropbox-refs/` 以外の repo content (= notes / drafts/ PDF snapshot / CLAUDE.md / DESIGN.md / SESSION.md 等) | 明示的 `git add` + `git commit` + `git push` |

**collaborator 視点の operating rule**:

1. `dropbox-refs/` 配下を編集 → Dropbox sync に任せる、 git は無視
2. それ以外 (notes / docs / PDF snapshot) を編集 → `git add` + `git commit` + `git push`
3. 「PDF snapshot を提出版として commit する」 ような cross-channel 操作のみ明示的に行う (`cp dropbox-refs/<output> drafts/<dated>.pdf && git add -f`)

### <a id="setup-md-template"></a>9.3 SETUP.md inline テンプレート

Pattern B repo の SETUP.md に以下を追加することを推奨:

```markdown
## ワークフロー早見表 (Pattern B 共通)

このリポは 2 つの同期チャネルを併用しています。 編集する file がどっち経由で
collaborator に届くかを把握しておくと事故が減ります。

junction = 「同一 file への近道」 です。 `dropbox-refs/<subpath>` と Dropbox 直
path (例 `~/Dropbox/<subpath>` ・ `~/Library/CloudStorage/Dropbox/<subpath>` 等) は
**同じ file** で、 どっちで開いても同じです。

| 編集対象 | 同期チャネル | 普段の操作 |
|---|---|---|
| (project 固有: 例 .tex / 図 / 参照 PDF) | Dropbox 自動 sync | 保存だけで OK |
| (project 固有: 例 notes / drafts/ PDF) | git push/pull | `git commit` + `git push` |

詳細規約: [`~/Claude/claude-config/conventions/dropbox-refs.md §9`](dropbox-refs.md#pattern-b-mental-model)
```

`(project 固有: ...)` は各 project の実 path を書く。 SETUP.md は collaborator 向け cold reference なので、 抽象 (= 「assets vs notes」) ではなく具体 path を書くこと。

---

## <a id="other-cloud-storage"></a>10. 他クラウドストレージへの応用 (OneDrive / Google Drive)

Pattern B の本質 (= 実 working tree と `.git/` をクラウド同期の外に置き、 asset folder へは gitignored な per-machine symlink で参照する) は Dropbox 固有ではない。OneDrive / Google Drive でも同型で使える。実証例: 授業教材 PDF を OneDrive に置いたまま、 個人リポから索引を git 管理する運用 (2026-06)。

- **命名**: symlink は `<provider>-refs/` (例: `onedrive-refs/`, `gdrive-refs/`)。`.gitignore` に `/<provider>-refs` 行を入れる
- **setup**: `dropbox-root.sh` 相当の resolver / YAML registry は無いので、 リポの CLAUDE.md に setup 1-liner を明記して per-machine 手動設置する。例 (macOS / OneDrive):

  ```bash
  ln -s "$HOME/Library/CloudStorage/OneDrive-<アカウント表示名>/<subpath>" onedrive-refs
  ```

  macOS の cloud storage は `~/Library/CloudStorage/<Provider>-<Account>/` に mount される。 同一 provider の複数アカウント (個人用 + 組織) が併存しうるため、 CLAUDE.md にはアカウント名まで書く
- **汎用化のトリガー**: 複数リポ・共同編集者で使い回す段になったら registry + setup script を provider 横断に汎用化する (§8 「Dropbox 解約 / 移行」 と同じ路線)。 1 リポ 1〜2 マシンのうちは 1-liner で十分

### クラウド asset の索引を自動生成する場合の gotchas (macOS launchd)

asset folder の索引 (一覧 markdown 等) をリポ内に自動生成 + auto-commit する構成 (launchd agent) での実証済み注意点:

- **WatchPaths はディレクトリ直下の変化しか発火しない**。 サブフォルダ内のファイル追加は検出されないので、 StartInterval (例: 1800s) をバックストップに併用する
- **auto-commit は生成物 file のみ `git add`** する (= 作業中の他 file を巻き込まない)。 「生成日」 行だけの diff を変化とみなすと daily noise commit が積まれるので、 `git diff -I '^<生成日行 pattern>'` で除外し、 その場合は `git checkout -- <file>` で working tree を clean に戻す
- push 失敗は放置でよい (= 次セッションの git-state-nudge hook が警告する)。 多重起動は mkdir lock で防ぐ
