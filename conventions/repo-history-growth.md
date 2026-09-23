<!-- doc-meta
when: build した PDF・図・様式の出力を commit しようとするとき + git-crypt で暗号化した file を頻繁に書き足す台帳にするとき + 自動生成の data を定期 job で commit するとき + repo (.git) が大きい・clone や fetch が重いと気づいたとき + check-history-growth.py の 🟠 / commit 時の ⚠️ を見たとき
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
   ([`latex.md#built-pdf-phone-sync`](latex.md#built-pdf-phone-sync))。 共同編集者に渡すなら release やメールの添付
3. **控えとして残す必要がある版だけ commit する** — 投稿した版・提出した版など節目だけ。 版は tag で指す
   (file 名に版番号を入れない = [`CONVENTIONS.md`](../CONVENTIONS.md#git-conventions))。 途中の build は commit しない

- ⚠️ **暗号化された提出書類の PDF も生成物** — 暗号化は差分をさらに効かなくするだけで、 扱いは同じ
- ⚠️ **追跡をやめるときは** `git rm --cached <file>` + `.gitignore`。 共同編集者のいる repo では、 PDF を git で見ている人がいないか先に一声かける (配り方を 2 に切り替える)
- ⚠️ **自動生成の data を定期 job で commit する場合**、 変わった時だけ commit する (中身が同じなら commit しない)。 大きな 1 file なら分割するか、 追跡をやめて生成を build の段に回す
- 追跡をやめても、 それまでの版は履歴に残る ([#already-accumulated](#already-accumulated))

## <a id="encrypted-ledgers"></a>暗号化して書き足す台帳 — 1 entry 1 file

git-crypt で暗号化した 1 つの list file に書き足し続けると、 1 commit ごとに file 全体の暗号文が積まれ、
並列の書き手の間で 3-way merge もできない。 1 entry 1 file に分ければ 1 commit の増分は触った entry の大きさ (数 KB) になる。
移し方 (宣言を先に・YAML を dump し直さない・読み手を 1 つの loader に寄せてから移す・前後を集合と順序で比べる) の正本 =
[`docs/sensitive-repo-patterns.ja.md#pattern-2-4`](../docs/sensitive-repo-patterns.ja.md#pattern-2-4)。

月ごとの file (受信の記録など) でも、 月末には数百 KB になり、 1 日に何度も書くなら同じ増え方をする。
分けるかは書く頻度 × 月末の大きさで決める ([#detection](#detection) の数字で判断する)。

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
- 100 MiB を超える file をどうしても版管理するなら Git LFS (保存量と転送量に別の上限がある)。 まず「git に置く必要があるか」 を問う

## <a id="already-accumulated"></a>既に積まれた分 — 落とすのは所有者の判断

増え方を止めても、 それまでの版は履歴に残り repo は縮まない。 落とすには履歴を書き換えて force-push するしかなく、
**不可逆**で、 全 clone が新しい履歴に追従する必要がある (追従しない clone は分岐して止まる)。 やるかは所有者が決める。

- 手順の正本 = [`docs/sensitive-repo-patterns.ja.md#pattern-2-4`](../docs/sensitive-repo-patterns.ja.md#pattern-2-4) の後半 (予行演習は mirror clone で / 空になった commit も残す / 本番は予行演習の後に何も進んでいないことを確かめて / 他の machine は後から 1 回追従)
- 道具 = [`scripts/git-drop-path-history.py`](../scripts/git-drop-path-history.py) (rehearse / apply / follow / shrink)
- 他の machine の追従を人の記憶に頼らない = [`multi-machine-state.md#history-rewrite-follow`](multi-machine-state.md#history-rewrite-follow)
- 共同編集者のいる repo では、 相手の clone も追従が要る = 書き換えの前に合意を取る
