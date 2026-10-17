<!-- doc-meta
when: build した PDF・図・様式の出力を commit しようとするとき + git-crypt で暗号化した file を頻繁に書き足す台帳にするとき + 自動生成の data を定期 job で commit するとき + repo (.git) が大きい・clone や fetch が重いと気づいたとき + repo は小さいのに fetch・push・ls-remote が毎回数秒かかるとき (#slow-round-trip) + git-crypt の repo を一時 clone して unlock する道具を書くとき + check-history-growth.py の 🟠 / commit 時の ⚠️ を見たとき
category: infra
summary: git は text の版を差分で詰めるが、 暗号化 blob と binary (PDF・画像・Office) は詰められないので、 版の数 × 大きさがそのまま履歴に積まれる (#mechanism)。 縮めるには履歴の書き換え (不可逆) しかないので、 増え方の段階で置き方を変える。 3 種類で対策が違う (#three-kinds): 生成物は作り直すたびに commit しない = 追跡から外すか節目だけ (#generated-binaries) / 暗号化して書き足す台帳は 1 entry 1 file (#encrypted-ledgers) / 素材は 1 回置いて変えない。 見つけ方 = scripts/check-history-growth.py (定期の一覧 + commit 時の警告、 #detection)。 GitHub は 1 file 100 MiB 超を push で拒否する = commit 時に止める (#hosting-limits)。 既に積まれた分は所有者の判断で scripts/git-drop-path-history.py (#already-accumulated)
-->
# git の履歴を置き方で太らせない

## <a id="mechanism"></a>機構 — 差分の効かない file は版ごとにまるごと積まれる

git は text の版どうしを差分で詰めて保存するので、 大きな text file を何度 commit しても履歴はあまり増えない。
しかし **暗号化された blob (git-crypt) と binary (PDF・画像・zip・docx / xlsx / pptx) は差分で詰められない**
(暗号文は 1 文字の変更で全体が変わる。 PDF・Office は中身が圧縮済み)。
= **1 commit ごとに file の大きさがそのまま履歴に足される**。

- 合成例: 1 MB の file を 1 日 60 回 commit すると 1 日 60 MB、 1 か月で 1.8 GB。 30 MB の PDF を 30 回作り直して commit すれば 900 MB
- repo の大きさは clone・fetch・gc・backup・machine 間の同期の全部に効く
- **縮めるには履歴の書き換えしかない** (不可逆・全 clone の追従が要る = [#already-accumulated](#already-accumulated))
- ∴ **置き方で決まる**。 大きくなってからでなく、 増え方の段階で見つけて置き方を変える (実測: 数か月で GB 単位まで育った repo が複数あった)

## <a id="three-kinds"></a>3 種類 — 対策が違う

| 種類 | 例 | 対策 |
|---|---|---|
| 生成物 | build した PDF (原稿・ノート・提出書類)、 図の書き出し、 様式の出力、 自動生成の data | 作り直すたびに commit しない ([#generated-binaries](#generated-binaries)) |
| 書き足す台帳 | 暗号化した TODO・受信の記録・連絡の記録 | 1 entry 1 file ([#encrypted-ledgers](#encrypted-ledgers)) |
| 素材 | 受け取った資料・写真・scan | 1 回置いて変えない (変えないなら問題にならない) |

迷ったら「**この file は source から作り直せるか**」 を問う。 作り直せるなら生成物。

## <a id="generated-binaries"></a>生成物 — 作り直すたびに commit しない

source (`.tex` / script / 元の data) が repo にあるなら、 生成物は source から作り直せる。 選択肢:

1. **追跡しない** (`.gitignore` に書く) — 既定。 source だけを commit する
2. **読むために置いているなら別の経路で配る** — 携帯で読む・手元で最新を見るのが目的なら同期フォルダへ写す
   ([`latex.md#built-pdf-phone-sync`](latex.md#built-pdf-phone-sync)、 git から外した PDF も写り、 共同編集者が source だけ push した文書は手元で組み直してから写す)。
   **共同編集の repo では、 各自の git push で発火する仕組みを repo に仕込む** ([`templates/shared-project/pdf-publish/`](../templates/shared-project/pdf-publish/)、 配る = [`scripts/install-pdf-publish.py`](../scripts/install-pdf-publish.py)):
   pre-push hook が push した文書の PDF を (古ければ組み直して) 共有フォルダへ背景で写す。 発火が各自の手元の push なので、 無人の定期実行
   (launchd は同期フォルダに書けない = [`launchd-cloudstorage-tcc.md`](launchd-cloudstorage-tcc.md)) も新しい API 権限も要らない。
   共同編集者は claude-config を持たないので、 repo には単体で動く写しを置く (drift は `install-pdf-publish.py check`)
   ⚠️ push の直後に同じ文書を手元で組むと、 hook が背景で走らせている組み直しと aux・PDF を取り合って失敗する (実測: 終了値 12 で PDF が 0 頁、 別の回は PDF が無い状態で終わった)。 push の直後に組むときは、 背景の `latexmk` / `lualatex` が終わるのを待ってから組む (`pgrep -f 'latexmk|lualatex'` が空になるまで)
3. **控えとして残す必要がある版だけ commit する** — 投稿した版・提出した版など節目だけ。 版は tag で指す
   (file 名に版番号を入れない = [`CONVENTIONS.md`](../CONVENTIONS.md#git-conventions))。 途中の build は commit しない。
   <a id="milestone-commit-gate"></a>**機械で守るなら pre-commit で止める**: 止めるのは、 同じ dir に同じ名前の `.tex` がある `.pdf` (= build した PDF) を stage した commit。 節目の commit だけ環境変数 (例 `MILESTONE=1`) で通す。 図・様式・受け取った資料のように `.tex` と対にならない PDF は build の入力なので、 変えたら commit する。 repo ごとに「毎回 commit する path」 の一覧を持てるようにする: **git で配っている生成物** (別の機械の定期ジョブが checkout から拾って公開する、 など) は毎回 commit しないと届かない (実測)。 すでに追跡している PDF は追跡したまま門を掛ければ、 共同編集者の手元は変わらない

- ⚠️ **暗号化された提出書類の PDF も生成物** — 暗号化は差分をさらに効かなくするだけで、 扱いは同じ
- ⚠️ **追跡をやめるときは** `git rm --cached <file>` + `.gitignore`。 共同編集者のいる repo では、 PDF を git で見ている人がいないか先に一声かける (配り方を 2 に切り替える)。 `.gitignore` の `/dir/*.pdf` は `dir` 直下だけで、 サブフォルダの PDF は `dir/**/*.pdf` と書かないと追跡される (実測)。 外す commit は path 指定でなく index 経由で ([multi-session-coordination.md#pathspec-commit-ignores-index](multi-session-coordination.md#pathspec-commit-ignores-index))
- ⚠️ **自動生成の data を定期 job で commit する場合**、 変わった時だけ commit する (中身が同じなら commit しない)。 大きな 1 file なら分割するか、 追跡をやめて生成を build の段に回す
- 追跡をやめても、 それまでの版は履歴に残る ([#already-accumulated](#already-accumulated))

## <a id="encrypted-ledgers"></a>暗号化して書き足す台帳 — 1 entry 1 file

git-crypt で暗号化した 1 つの list file に書き足し続けると、 1 commit ごとに file 全体の暗号文が積まれ、
並列の書き手の間で 3-way merge もできない。 1 entry 1 file に分ければ 1 commit の増分は触った entry の大きさ (数 KB) になる。
移し方 (宣言を先に・YAML を dump し直さない・読み手を 1 つの loader に寄せてから移す・前後を集合と順序で比べる) の正本 =
[`docs/sensitive-repo-patterns.ja.md#pattern-2-4`](../docs/sensitive-repo-patterns.ja.md#pattern-2-4)。

月ごとの file (受信の記録など) でも、 月末には数百 KB になり、 1 日に何度も書くなら同じ増え方をする。
分けるかは書く頻度 × 月末の大きさで決める ([#detection](#detection) の数字で判断する)。

書き足すだけで直さない記録 (通知・log の写し) は、 束ねるたびに**新しい file** にして、 書いた file を二度と書き換えない
(= 履歴の大きさ = 中身の大きさ)。 細かい間隔の写しは git 管理外の spool に溜め、 一定時間ごとに束ねて commit する。
file 名を時刻にするなら、 同じ名前が既にあれば連番を足す (秒で名付けた束を同じ秒に 2 回作ると、 後の束が前の束を
上書きした = 実測)。 例 = [`macos-notification-db.md#always-on-archive`](macos-notification-db.md#always-on-archive)。

## <a id="detection"></a>見つけ方 — 定期の一覧と commit 時の警告

道具 = [`scripts/check-history-growth.py`](../scripts/check-history-growth.py) (閾値は script の定数だけが持つ)。

- **定期の一覧** (`--root <dir>`): 直近 30 日に、 差分の効かない版が多く・大きく積まれた path と repo を出す。 健全なら何も出さない。
  dashboard など、 所有者の目に届く面で回す
- **commit 時の警告** (`--staged`): commit しようとしている版が直近 30 日の何版目かを数え、 頻繁なら ⚠️ を 1 行出す。 止めるのは push できない大きさ (1 file 100 MiB 超、 [#hosting-limits](#hosting-limits)) だけ。
  pre-commit に配線する (書いた瞬間に置き方を問う)。 ⚠️ pre-commit の中では `git commit -- <path>` の一時 index を読む必要がある
  (`GIT_INDEX_FILE` を捨てない = 別 repo を触る時の逆、 [`hook-authoring.md#hook-git-env-cross-repo`](hook-authoring.md#hook-git-env-cross-repo))
- 既に大きい repo の内訳は `--days` を伸ばして見る (既定の窓は「今の増え方」 だけ)

## <a id="hosting-limits"></a>hosting の上限 — 1 file と repo の大きさ

GitHub の上限 (公式 docs: [About large files on GitHub](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github) / [Repository limits](https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits)):

- **1 file**: 50 MiB を超えると警告、 **100 MiB を超えると push を拒否** — 拒否は push の時に起きるので、 commit した後では履歴から消すまで同期が止まる
- **repo**: 1 GB 未満が理想、 5 GB 未満を強く推奨 (大きすぎると GitHub から是正を求められることがある)。 1 回の push は 2 GB まで

- ⚠️ **上限の直前の file は、 作り直して少し増えただけで越える** (暗号化は大きさをわずかに増やす)。 高解像度の印刷用 raster PDF がこの大きさになりやすい = 印刷用の raster は生成物として追跡しない
- 越える前に止める = commit 時の検査が 100 MiB 超を止め、 50 MiB 超に残りの余白を出す ([#detection](#detection))
- ⚠️ **50 MiB 超の警告は、 素材を 1 回置くだけの commit でも、 push の前に止まって置き場所を決める合図** — 暗号化した file と binary は詰められないので、 その大きさが消すまで全 clone の履歴に残り、 消すには書き換え ([#already-accumulated](#already-accumulated)) が要る。 原本は git の外 (共有フォルダなど) に置き、 repo には用途に足る縮めた版を置く。 実測: 警告を読んだまま push し、 後から書き換えで落とした
- 前例 (前の回と同じ置き場所) を写すときは、 大きさも前例と比べる — 置き場所が同じでも、 大きさが 1 桁違えば別の判断になる
- 100 MiB を超える file をどうしても版管理するなら Git LFS (保存量と転送量に別の上限がある)。 まず「git に置く必要があるか」 を問う

## <a id="slow-round-trip"></a>repo は小さいのに fetch・push が遅い — 時間は握手と復号にある

履歴の大きさより先に、 1 回の操作の時間がどこに出ているかを測る (`time git ls-remote origin <branch>` と、 道具の段ごとの時間)。

- **往復の大半は host への SSH の握手** (実測: 1 往復 約 2 秒、 転送する中身が小さくても同じ)。 host の block に
  `ControlMaster auto` / `ControlPath ~/.ssh/cm-%r@%h-%p` / `ControlPersist 10m` を足すと、 2 回目から既存の接続を使い回して
  1 秒未満になる (実測)。 `~/.ssh/config` は機械ごとなので、 手で直さず、 setup か session 開始の自動適用に「効いていなければ足す」 段を置く
  (効いているかは `ssh -G <host>` の `controlmaster` の行で見る)。
- **git-crypt の repo を一時 dir に clone して `git-crypt unlock` する道具は、 file 数に比例して遅くなる** — unlock は tracked file
  1 本ごとに filter の process を起こす (実測: 1 本 数十 ms、 千件で数十秒)。 毎回読む道具は clone をやめ、 手元の checkout に `fetch`
  して、 要る blob だけ `git cat-file --filters <rev>:<path>` で復号し、 blob id で cache する (暗号文は中身で決まる id なので cache は古くならない)。
  書く側も作業 tree と index を使わない形にする: `hash-object -w --path <path>` (path の clean filter が暗号化) → 一時 index
  (`GIT_INDEX_FILE`) で `read-tree` + `update-index --cacheinfo` → `write-tree` → `commit-tree -p <fetched>` → `push <sha>:refs/heads/<branch>`。
  拒否された push は「他の書き手が先に入った」 なので、 fetch して検証し直してから作り直す。 実装例 = ai-collaboration [`board/board_transport.py`](../../ai-collaboration/board/board_transport.py)。
- ⚠️ repo の subdir を対象にする plumbing は、 repo の top で root からの path を渡す — `git -C <subdir>` だと pathspec・`ls-tree` の出力・
  `hash-object --path` が cwd 相対になり、 黙って空や別の path になる (実測)。 `ls-tree` は `--full-tree` も付ける。

## <a id="already-accumulated"></a>既に積まれた分 — 落とすのは所有者の判断

増え方を止めても、 それまでの版は履歴に残り repo は縮まない。 落とすには履歴を書き換えて force-push するしかなく、
**不可逆**で、 全 clone が新しい履歴に追従する必要がある (追従しない clone は分岐して止まる)。 やるかは所有者が決める。

- 手順の正本 = [`docs/sensitive-repo-patterns.ja.md#pattern-2-4`](../docs/sensitive-repo-patterns.ja.md#pattern-2-4) の後半 (予行演習は mirror clone で / 空になった commit も残す / 本番は予行演習の後に何も進んでいないことを確かめて / 他の machine は後から 1 回追従)
- 道具 = [`scripts/git-drop-path-history.py`](../scripts/git-drop-path-history.py) (rehearse / apply / follow / shrink)
- 他の machine の追従を人の記憶に頼らない = [`multi-machine-state.md#history-rewrite-follow`](multi-machine-state.md#history-rewrite-follow)
- 共同編集者のいる repo では、 相手の clone も追従が要る = 書き換えの前に合意を取る
