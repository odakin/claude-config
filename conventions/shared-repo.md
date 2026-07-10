<!-- doc-meta
when: 共同編集者がいるリポで作業するとき
category: infra
summary: 共有リポ固有規約
-->
# 共有リポ規約 — Shared Project Layer

共同編集者がいるリポで適用。CLAUDE.md から参照: `~/Claude/claude-config/conventions/shared-repo.md`

このファイルは Claude Code 4 層モデルの **layer 2（共有プロジェクト層）** の規約。詳しい層モデルは [`docs/personal-layer.md`](../docs/personal-layer.md) を参照。

## Git workflow（必須）

### <a id="session-start"></a>セッション開始時
「作業開始」「スタート」等の合図があったら:
1. `git status` で状態チェック
   - **未コミット変更あり** → 「前回の変更が未 commit です。先に commit & push しますか？」
   - **未 push コミットあり** → 「前回の commit が未 push です。先に push しますか？」
2. `git pull` でリモートと同期（コンフリクト発生時はユーザーと解決）
3. **他所からの open PR を確認**: `gh pr list --search "-author:@me"` で自分以外が著者の open PR を一覧。0 件なら次へ。1 件以上ならタイトル・著者・更新日を提示し、「先にレビューしますか？それとも今のタスクを進めますか？」とユーザーに判断を仰ぐ。レビュー先行を選ばれたら `gh pr view <num>` / `gh pr diff <num>` で内容を確認し、所見を提示する。
   - **判断材料**: PR が触るファイルと今のタスクの重なり（競合可能性）、CI 失敗・reviewer unblock 待ちの緊急度
4. リマインダー表示: **「作業が終わったら commit & push を忘れずに！」**

### <a id="session-end"></a>セッション終了時
「おわり」「終了」「今日はここまで」等の合図、またはお礼・挨拶があったら:
- `git status` を実行し、未コミット/未 push があればリマインドする
- クリーンなら「変更なし。お疲れさまでした。」

### Branching strategy

共有リポでは **default branch (`main`) が共著者にとっての真実**。共著者は `git pull` で最新を取得できることを暗黙の前提とする (= 別 branch を checkout する前提を共著者に課さない)。

#### 原則

- **main 上で進める**: 通常の編集作業は `main` 直接 commit + push。WIP でも compile pass (LaTeX なら中間ファイル `.aux` `.bbl` 等を ignore し、最新 PDF を track して「現在の見え方」を pull で再現できる状態) を維持する
- **feature branch は短命前提**: 同日中に main へ merge できる粒度のリファクタ・実験のみ。24 時間以上を見込む変更は branch しない (= main 上で commit を分けて進める)
- **大改造で branch せざるを得ない場合**: 以下 3 点を**全部**やる
  1. 共著者全員に branch 名 + checkout 手順を **out-of-band** で通知 (Discord / Slack / メール)
  2. その branch の SESSION.md / README.md の冒頭に「⚠️ 共著者は `git checkout <branch>` してから pull」 マーカー
  3. `main` の README / SESSION.md に「現在 `<branch>` で大改造中、main は古いまま」 と明記 (= main を見た共著者に状況が伝わる)

#### Watchdog (session 開始時)

セッション開始時の git fetch + ahead/behind 確認に加えて、**default branch との divergence** も確認する:

```bash
DEFAULT=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's,refs/remotes/origin/,,')
[ -z "$DEFAULT" ] && DEFAULT=main
AHEAD_FROM_DEFAULT=$(git rev-list --count "$DEFAULT..HEAD" 2>/dev/null)
echo "default=$DEFAULT, ahead from default=$AHEAD_FROM_DEFAULT"
```

非 default branch で `AHEAD_FROM_DEFAULT >= 5` または最古 commit から **24 時間以上経過** していたら、**merge を最優先タスクに格上げ**する。Phase 進行・レビュー gate を branch 維持の justification に流用しない (レビューは main 上で進めればよい — 「merge 前に review 完了」 は branch 必須化の根拠にならない)。

#### artifact 配信経路の依存

PDF / 成果物を Dropbox 等で**別経路配信**している共有リポでは、**共著者側の sync が未セットアップだと git pull が唯一の経路**になる。この依存関係を CLAUDE.md / SESSION.md で明示し、未セットアップの共著者がいる間は `main` が最新であることを死守する責任が生じる (= branching policy の原則「main = collaborator's truth」 と直結)。共著者の sync 状況は CLAUDE.md / SESSION.md に明記しておくのが安全 (例: 「Windows side 未セットアップ」 等)。

#### Pre-merge revert anchor

長期 branch を main へ merge する前に、merge 直前の main 位置に tag (`main-pre-<branch>-merge` 等) を打って push する。FF merge は revert が `git reset --hard <tag>` で可能だが、tag 不在だと「pre-merge の main がどこだったか」 を後から特定するコストが高くなる。

## .gitignore

共同編集者が `~/.gitignore_global` を設定しているとは限らない。共有リポでは `.gitignore` に全パターンを明記する:
```
.DS_Store
*~
*.swp
*.swo
```
LaTeX リポの場合は [conventions/latex.md](latex.md) の .gitignore セクションも参照。

## パスの記述
CLAUDE.md・SESSION.md 等でローカルパスを書くときは `~` 表記を使う（`/Users/<user>/` は共同編集者の環境で壊れる）。

## 4 層モデルの依存ルール

claude-config の 4 層モデル (audience の広さ順に numbering、`public ⊃ collaborator set ⊃ owner ⊃ machine-local`):

| # | 層 | 例 | Audience | 依存可能先 |
|---|---|---|---|---|
| 1 | 共通規約 | claude-config | public / shared | — |
| 2 | 共有プロジェクト層 (このリポ) | private repo with collaborators | collaborator set | **layer 1 のみ** |
| 3 | 個人層 (secret 配置を含む) | `<owner>-prefs/` / 個人 secret repo / `~/.secrets/` | owner only | layers 1, 2 |
| 4 | 揮発メモリ | `~/.claude/.../memory/` | local machine | any |

> [`docs/personal-layer.md`](../docs/personal-layer.md) §「What is the personal layer?」 が canonical、本表は reading mirror (= 後述の §機能 literal と reading mirror の区別 の慣例に従う)。新規列追加・layer 番号変更時は personal-layer.md 側を真正本として更新する。
>
> **「依存可能先」の読み方**: ここで列挙されているのは **rule 上参照してよい上限** (= audience containment で許される上限) であって、**実際にどこまで依存するか** は各リポの judgment call。例えば layer 3 (個人層) は rule 上 layer 1 + 2 に依存可能だが、現実には layer 1 (claude-config) のみ参照しているケースが普通 (= 自分のリポを personal layer から自分の collaborator リポに参照する必要は少ない)。「依存可能」 ≠ 「実依存」 なので混同しない。

**Core rule**: each layer may only depend on layers whose audience contains its own (= 番号が小さい層を参照できる、大きい層は参照できない)。

具体的に共有プロジェクト層 (= layer 2) は **layer 1 (共通規約) のみ依存可、layer 3 (個人層) と layer 4 (揮発メモリ) には依存禁止**。理由: 共同編集者は所有者の個人層も machine-local memory も見られないため、依存すると collaborator 環境で動作が破綻する。

「**依存 (depend)**」 と「**名指し (mention)**」 の区別が canonical: [`docs/personal-layer.md` §「What \"depend\" means: structural dependency vs. mention」](../docs/personal-layer.md#what-depend-means-structural-dependency-vs-mention) 参照。 要約すると:

- ❌ **依存** = collaborator が L3 にアクセスしないと本リポが standalone で成立しない (= 違反)
- ✅ **名指し** = collaborator は本リポ範囲で完結、 boundary 明示付きで upstream の存在を informational に書く (= 許容)

CLAUDE.md / DESIGN.md / README.md など共同編集者が触れるファイルに以下を **絶対に書かない (= 依存形)**:

- **L3 内部 file path** (例: `<owner>-prefs/something.md`)。 repo 名単独 (例: `<owner>-prefs`) は名指しで OK だが、 `/` 以降の path は dependency 形に格上げされる (= 「name it, don't path into it」)
- 所有者個人のメール文体・身元情報のインライン (= layer 3 のデータ)
- 所有者個人のカレンダー ID・アカウント ID (= layer 3 のデータ)
- 所有者個人の secret 配置の絶対パス (例: `~/.secrets/<owner-specific>-token`、所有者固有のクラウドストレージ path) — secret は layer 3 のサブセット
- `/Users/<owner>/` のような絶対パス
- 揮発メモリへの参照 (= layer 4、machine-local。collaborator は持っていない)

これらは layer 3 (個人層、cascade 経由で勝手に上書き) または layer 4 (memory) に置く。共有プロジェクト層は **standalone で成立する** こと (= 操作的定義は次節 「『standalone で成立』 の操作的定義」 参照)。

#### L2 における「名指し」 の適用 (boundary 明示付き)

L3 repo 名そのものを L2 doc に書くのは許容、 ただし以下を **同じ場所で併記** (= canonical 原則は personal-layer.md、 本節は L2 における具体化):

1. **boundary 文を併記**: 「collaborator は本リポ範囲で完結 / 上記 upstream に直接アクセスする必要は無い」 等の文を `()` 内 or 同 bullet 内に書く
2. **責務境界 / 取り込み手順 等 explanatory section に限る**: 通常の運用文書 (= setup 手順 / build 手順) 内に L3 名を書くと、 collaborator が必要だと誤読する。 explanatory 文脈に限定

「**name it, don't path into it**」 の compact rule は personal-layer.md 側に書いてある通り。 内部 path (= `<owner>-prefs/<file>`) は名指し例外に入らず依存形扱い。

### 公開前の Audit

共同編集者にリポを渡す前に、以下の grep を実施:

```bash
# 所有者個人の他リポ参照 (= warning、 false-positive 可)
#   hit したら boundary 文を併記しているか目視確認。 boundary 明示付きの
#   名指しは許容 (= 上記 §「L2 における「名指し」 の適用 (boundary 明示付き)」 参照)
grep -rn '<owner>-prefs\|<other-private-repo-1>\|<other-private-repo-2>' --exclude-dir=.git .

# 所有者個人の絶対パス (= 絶対 0 件)
grep -rn "/Users/<owner>" --exclude-dir=.git .

# 所有者個人のメール・カレンダー識別子 (= 絶対 0 件)
grep -rE '<owner-personal-calendar-id>|<owner-personal-email>' --exclude-dir=.git .

# L3 file path 直接参照 (= 絶対 0 件、 boundary 文があっても NG)
#   repo 名のみは OK、 path は NG。 例: "physics-research" は許容、
#   "physics-research/papers/talks.yaml" は禁止
grep -rE '<other-private-repo>/[a-z]' --exclude-dir=.git .
```

`<owner>` 等は実際の所有者・リポ名に置き換える。所有者は自分の個人層に「公開禁止のキーワード一覧」を持っておくと監査が楽。 **2 種類の severity**: (a) repo 名 hit = warning (= boundary 文の有無を目視)、 (b) file path hit + 絶対 path hit + identifier hit = block (= 即修正)。

> **Note**: 上記の手動 audit は hook 未導入の共同編集者向けの fallback。
> 個人運用では `hooks/public-leak-guard.sh` (PreToolUse) と
> `scripts/public-precommit-runner.sh` (pre-commit) で自動化済み。
> 設計詳細は `DESIGN.md` §公開リポ leak 防止。
>
> **カバレッジ ギャップ**: 上の hook chain は **public** リポを対象とする (`.claude/public-repo.marker` の有無で判定)。**private shared** リポ (= collaborator あり、public marker なし) では fire しないため、layer-2 違反 (= owner literal) は session-end / push-time の手動 audit に依存する。private shared リポで新規 file に絶対パスを焼き付ける commit を書いた直後は、`grep -rn "/Users/<owner>"` を 4 軸 sweep の整合性軸に組み込むのが安全。

## macOS LaunchAgent / launchd plist の literal-path trap

macOS の **LaunchAgent / LaunchDaemon plist は `~` も `$HOME` も自然展開しない** (= `ProgramArguments` / `WatchPaths` 等の path は literal でなければ launchd に loaded されない)。共有リポに plist をそのまま commit すると、所有者の絶対パス (`/Users/<owner>/…`) が file に焼き付き、上記 §「公開前の Audit」 の grep に hit する layer-2 違反になる。

### 解法: template + setup.sh

- `<label>.plist.template` … `__HOME__` placeholder で commit (= 絶対パスは入らない)
- `setup.sh` … template から plist を生成・配置・登録 (冪等):
  ```sh
  TEMPLATE="$SCRIPT_DIR/<label>.plist.template"
  DEST="$HOME/Library/LaunchAgents/<label>.plist"
  launchctl bootout "gui/$(id -u)/<label>" 2>/dev/null || true
  sed "s|__HOME__|${HOME}|g" "$TEMPLATE" > "$DEST"
  launchctl bootstrap "gui/$(id -u)" "$DEST"
  launchctl kickstart -k "gui/$(id -u)/<label>"
  ```
- `uninstall.sh` … 対称操作 (`launchctl bootout` + `rm $DEST`)

label 名にも owner literal を入れない (例: `local.<owner>.foo` ではなく `local.foo`)。LaunchAgent は per-user domain (`gui/$(id -u)/`) でロードされるので、user 識別は domain 側が担う。

### 同種 trap が起きる他の場面

- launchd LaunchDaemon plist (system domain だが同じく path 展開なし)
- Hammerspoon Lua 設定など、OS 固有の「読み手側で path 展開しない」 設定ファイル全般

### 他 OS は ネイティブで展開する (= template 不要)

- Linux systemd の `.service`: `%h` で `$HOME` 展開、`User=` 指定で per-user 切り替え
- Windows Task Scheduler XML / PowerShell スクリプト: `$env:USERPROFILE` / `$HOME` を runtime 展開

template 化 (sed substitution) が必要なのは macOS plist のみ (経験上)。

## <a id="standalone-operational-definition"></a>「standalone で成立」 の操作的定義

「standalone で成立」は **完全自己完結** ではなく、**標準 dev environment + 明示された外部依存** で動作する状態を指す。

### 標準 dev environment

claude-config が想定する標準 dev environment:

- macOS or Linux + git + git-crypt + GitHub CLI
- claude-config の `setup.sh` が走る (= 主要依存 tool が揃う)

Windows は `cp` + post-merge hook で claude-config 自体は動くが、shell 系スクリプトの動作保証は別途 (各 shared リポで明示)。

### 許容される外部依存と doc 明示義務

shared 層が依存していい外部リソースと、その doc 明示義務:

| 依存先 | 例 | 明示義務 |
|---|---|---|
| 第三者 SaaS | GitHub Actions / Discord API / Google Calendar | 落ちた時の制約と回避策を CLAUDE.md に明記 |
| layer 3 (個人層 / secret) への interface | 環境変数名 / GitHub Actions secret 名 / generic な path 表現 (`~/.secrets/<service>-token`) | 具体 owner literal は layer 3 に隔離、shared 層には interface 名のみ |
| OS 固有機能 | macOS only スクリプト (Hammerspoon, launchd 等) | リポの CLAUDE.md / README に「macOS 限定」明示 |
| 帯域・Network 制約 | 組織 NW での外部 API ブロック | 制約と回避策 (例: GitHub Actions 経由) を明示 |

### 判定基準

**共同編集者が clone → setup.sh を走らせた時、何が動いて何が動かないかが doc から判断できる** ことが standalone 要件の本質:

- ✅ 動く例: cron 駆動の自動 job (= GitHub Actions)、yaml/script 編集 + push、機能サマリの参照
- ⚠️ 制約付きで動く例: secret 必要操作 (owner 依頼経路に従う、具体的には [`discord-bot.md` token-sharing-protocol](discord-bot.md#token-sharing-protocol) 参照)、macOS only スクリプト (他 OS では skip)
- ❌ doc 不明示で動かない = layer 違反: 共同編集者がトラブルシュートで詰む状態

### operational 完結性の文書化義務

「standalone で成立」は **動作要件**であり、**operational 完結性 (= collaborator 単独で全操作可能) とは別**。secret 等を要する操作を意図的に owner-only にしている場合、共有層の CLAUDE.md に「< 該当操作 > は owner 依頼経路」と明記すれば、standalone 要件と矛盾しない (= 共同編集者が「自分は何ができないか」を doc から判別できる)。明記がないと collaborator が試行錯誤で行き止まりを発見する cost が発生する。

## 機能 literal と reading mirror の区別

共有層の literal は 2 種類あり、混同すると drift リスクが発生する:

| 種類 | 例 | 性質 |
|---|---|---|
| **機能 literal** | workflow yaml の identifier dict / script の URL / 設定ファイルの key | 機械が読むので変更すると動作が壊れる = 真正本 |
| **reading mirror** | CLAUDE.md / README.md の identifier テーブル | 人間 reading 用、機能上は不要だが doc としてあると便利 |

### drift 対策

reading mirror には **真正本ポインタ** を併記する:

```markdown
| Channel | ID |
|---|---|
| #foo | 1234 |

> `discord-fetch.yml` の `channels` dict が canonical、本テーブルは reading mirror。
> 新規追加・rename 時は yaml 側を真正本として更新する。
```

これで次に編集する人が「真正本 → mirror」の順で更新できる。mirror が drift しても致命傷にはならないが、grep で検出しにくいバグ源。

### 多層 mirror

同じ identifier が 機能 literal + shared mirror + personal mirror の 3 段に重複する場合 (例: Discord channel ID = workflow yaml + shared CLAUDE.md + personal layer の reference doc) は mirror を 1 段に絞ることを優先検討する。ただし「auto-load される doc に書いておけば Claude が即参照できる」便宜と weight する — 残す場合は各 mirror に真正本ポインタを忘れず付ける。

## Collaborator の招待（GitHub）

GitHub UI 経由でも可だが、`gh` CLI で 1 行で完結する:

```bash
# write 権限（一般的な共同編集者）
gh api -X PUT repos/<owner>/<repo>/collaborators/<username> -f permission=push

# read 権限のみ
gh api -X PUT repos/<owner>/<repo>/collaborators/<username> -f permission=pull

# admin (鍵管理者など)
gh api -X PUT repos/<owner>/<repo>/collaborators/<username> -f permission=admin
```

実行後、対象ユーザーには GitHub から invite メールが届き、accept すると collaborator になる。状態確認:

```bash
# 受諾済みの collaborator 一覧
gh api repos/<owner>/<repo>/collaborators

# 未受諾の pending invitations
gh api repos/<owner>/<repo>/invitations
```

`permission` の選択指針: 卒論・共同論文等の write 必要なケースは `push`。`maintain` は branch 保護や release 管理を任せる場合のみ。`admin` は鍵管理者か co-owner だけ。

## 共有 git-crypt 鍵パターン

共有プロジェクトを git-crypt で暗号化したい場合、**個人鍵とは別の鍵**を作って共同編集者と共有する。**鍵配布は openssl 暗号化 backup をクラウドストレージ (Dropbox 等) に置き、`.claude/git-crypt-backup` + `setup.sh` Step 5b-pre による全自動復元を canonical にする** (詳細: [`docs/git-crypt-guide.ja.md`](../docs/git-crypt-guide.ja.md) §共有リポでの自動復元)。

### 鍵の生成 + 配布 (initiator 側、初回のみ)

1. リポで `git-crypt init` → 内部鍵生成
2. `git-crypt export-key /tmp/<project-name>.key && chmod 600 /tmp/<project-name>.key`
3. 鍵を openssl で暗号化してクラウドストレージ共有フォルダに配置:
   ```bash
   /usr/bin/openssl enc -aes-256-cbc -pbkdf2 -salt \
     -in /tmp/<project-name>.key \
     -out <shared-storage>/<project-name>.key.enc
   shred -u /tmp/<project-name>.key   # 平文を即削除
   ```
4. 強いパスフレーズを共同編集者に **out-of-band で共有** (対面 / Signal 等。GitHub / クラウドストレージ / メール経由は禁止)
5. リポに `.claude/git-crypt-backup` を作成、暗号化ファイル名 (= `<project-name>.key.enc`) を 1 行で記載 ← これが setup.sh の検索キー
6. `~/.secrets/<project-name>.key` をローカルに配置して `git-crypt unlock` で動作確認

### 共同編集者向けの SETUP.md

共同編集者が新マシンで onboarding するための walkthrough は、**`SETUP.md` (リポ root)** に置く。CLAUDE.md は毎セッション auto-load されるため full walkthrough を入れるとコスト増、cold reference として SETUP.md に分離する。

- テンプレ: [`templates/shared-project/SETUP.md.template`](../templates/shared-project/SETUP.md.template) を copy → このリポ固有のパラメータ (encrypted backup ファイル名 / Dropbox path / local key path / passphrase 受領経路 / plaintext test file) を埋める
- 配置: **必ずリポ root**。`docs/**` を git-crypt 暗号化対象にしている場合、`docs/SETUP.md` だと未 unlock の collaborator が読めない catch-22
- CLAUDE.md 側の git-crypt セクションは **SETUP.md への 1-2 行ポインタ + 反パターン警告 (手動 openssl から始めない) のみ**。例:
  ```markdown
  **git-crypt 有効** (`<encrypted-paths>` のみ暗号化)。
  - 復号後の日常運用: `git-crypt unlock ~/.secrets/<project-name>.key`
  - **新マシン初回セットアップ → [SETUP.md](SETUP.md) を必ず読んでから進める**。`cd ~/Claude/claude-config && ./setup.sh` で全自動。⚠️ **手動 `openssl enc -d ...` から始めない** (path 誤りで bad-decrypt 残骸事故が過去あり、SETUP.md §反パターン警告 参照)
  ```

SETUP.md.template は復号失敗事故 (`docs/git-crypt-guide.ja.md` §共有リポでの自動復元 「共同編集者向け運用」項の手動経路 anti-pattern bullet 群) の 5 段アンチパターン全てに対する防御 (反パターン警告 + 推奨経路 setup.sh 最優先 + 手動 fallback の Step 0 事前確認 / Step 2 事後確認) を組み込んでいる。**項目を削らず内容だけ埋める**こと。

### 暗号化スコープ最小化を検討する

`.gitattributes` を `private/** filter=git-crypt diff=git-crypt` 1 行に絞ると、機微な情報のみ `private/` に入れて他は平文で扱える。鍵管理コストと audit のしやすさが大きく改善される。**逆に `docs/**` を暗号化対象にすると、SETUP.md を `docs/` に置けない catch-22 になるため SETUP.md は必ず repo root** (上記 §共同編集者向けの SETUP.md 参照)。詳細は [`docs/git-crypt-guide.md`](../docs/git-crypt-guide.md) 参照。

### 鍵のローカルパスは共同編集者ごとに異なる (補助的、レガシー)

`setup.sh` Step 5b-pre が `.claude/git-crypt-backup` + クラウドストレージ find で鍵を自動配置するため **path 知識自体が不要** になっており、これが canonical recovery 経路。

ただし個人層 (e.g., `<your>-prefs/`) を持つユーザは補助的に `shared-project-keys.md` レジストリで「自分のマシンに何の鍵があるか」を管理してもよい。schema:

```markdown
| Project | Local key path | `.claude/git-crypt-backup` の中身 |
|---|---|---|
| <project-name> | ~/.secrets/<project-name>.key | <project-name>.key.enc |
```

このレジストリは Claude が「どの鍵が手元にあるか」を一覧把握する用途であり、unlock 自体は setup.sh が自動で行うため依存ではない (**共有プロジェクト層は個人層に依存しない** 4 層モデルが守られる)。個人層の placeholder (`<workplace_short>` 等) は path 解決には**使わない** (誤展開事故防止 — `docs/git-crypt-guide.ja.md` §共有リポでの自動復元 参照)。
