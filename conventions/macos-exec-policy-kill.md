<!-- doc-meta
when: script や git hook の実行が SIGKILL で止まるとき (exit 137 / "Killed: 9" / git の "hook ... died of signal 9") + 同じ中身の script が場所によって kill されたりされなかったりするとき + syspolicyd が重い・メモリが膨らんでいるとき + 別のアプリの起動失敗が大量に続いた後に手元の script が動かなくなったとき
category: macos
summary: macOS は exec 時の malware 判定を file (inode) ごとに覚える。 syspolicyd が詰まって scan に失敗すると、 その判定が kill として残り、 以後その file の exec は即 SIGKILL になる。 中身は無関係なので、 同じ bytes・同じ mode の新しい inode に作り直すと scan し直されて通る (同じ inode への上書きでは直らない)。 診断 = scripts/macos-exec-kill-triage.py、 git hook の直し方 = hook-authoring.md#killed-hook-stub
-->
# macOS に exec で kill される script

script の実行が何も出力せずに止まり、 終了値が 137 (= SIGKILL) になる。 同じ中身の script が、 置いてある場所
によって動いたり動かなかったりする。 中身・権限・署名を疑う前に、 macOS が **その file に付けた判定** を疑う。

## <a id="symptom"></a>症状

- 終了値 137、 bash なら `Killed: 9`、 git なら `.git/hooks/<name> died of signal 9` (commit が止まる)
- 中身 (md5)・xattr (`com.apple.provenance`)・mtime が同じ file どうしで、 kill されるものとされないものがある
- `bash <script>` で**中身を読ませる**と通る (exec ではないので判定を受けない)
- kill は 0.00 秒で起き、 その exec について syspolicyd も kernel も何も記録しない

## <a id="first-look"></a>最初の 1 コマンド

```bash
python3 ~/Claude/claude-config/scripts/macos-exec-kill-triage.py --minutes 120 <kill される file> <通る file>
```

読むだけ。 syspolicyd の pid・起動時刻・RSS、 unified log の署名 6 種の分ごとの件数、 exec を拒否された path の上位、
引数の file ごとの判定 (kill / ok / 調べられない)・inode・xattr を出す。 時間帯を指定するなら `--start` / `--end`。

## <a id="measured"></a>実測したこと

- **判定は inode ごと**: 同じ inode の hard link は別の path でも kill される。 中身も xattr も同じ `cp -p` の複製 (新しい inode) は通る
- **同じ inode への上書き (`printf > file`、 `cat > file`) では直らない**。 一時 file に書いて `mv` で差し替えると直る
- 起きた時の unified log:
  - 別アプリ (Chromium 系ブラウザの `code_sign_clone`) の helper が拒否と再起動を繰り返し、 kernel の `ASP: Security policy would not allow process` が 2 分ほどで十数万件出ていた
  - 同じ時間に syspolicyd が `Error performing Yara scan ... Code=3` → `Terminating process due to Malware rejection` と、 `Failed to generate SecStaticCode ... error: 100024` を出していた (= Security framework の 100000 + errno。 24 = EMFILE、 file を開けない)
  - 30 分近く後も `ASP: Could not find reference ..., process must have died` (= 待っていた process が既に居ない依頼への返答) が続き、 syspolicyd の RSS は数 GB あった (起動から約 3 日。 数十分後には 1 GB を切った)
- kill される file は何もしなくても数十分で一部が通るようになったが、 いつ消えるかは読めない
- macOS の更新の直後ではなかった

## <a id="inferred"></a>推定 (未確認)

macOS は provenance 付きの script を exec するとき、 syspolicyd に XProtect の scan をさせ、 kernel
(AppleSystemPolicy) が結果を vnode に覚える。 syspolicyd が詰まって scan が失敗すると malware 側に倒して覚え
(fail-closed)、 以後その file の exec は syspolicyd に聞かずに SIGKILL になる。 詰まっていた間に**初めて**
exec された file だけが kill を覚えるので、 同じ中身でも、 それ以前に判定が付いていた file は通る。
自然に消えるのは vnode が回収されて覚えた判定が消えるため。 **再起動で全部消えるかは確かめていない**。

確かめ方 (次に起きたとき): kill される file を 1 本 hard link で控え (作り直しても控えは古い inode のまま)、
再起動の後に控えの exec が通るかを見る。

## <a id="remedy"></a>直し方

- **同じ bytes・同じ mode の新しい inode に作り直す** (`cp -p f f.tmp && mv -f f.tmp f`、 symlink なら実体を)。
  作り直した file も macOS がもう一度 scan するので、 検査を外したことにはならない
- 作り直しても kill されるなら繰り返さない。 syspolicyd がまだ詰まっているか、 本当に malware と判定された
  かのどちらかで、 どちらも回り込んでよいものではない
- **macOS の設定 (Gatekeeper・XProtect) を変えない。 `com.apple.provenance` などの xattr を剥がして回り込まない**
- 嵐の源 (拒否され続けているアプリ) が分かったら、 そのアプリを止める・更新を終わらせるのが先
- git hook なら `scripts/heal-hook-stubs.sh` が全 repo をまとめて検査・作り直す ([`hook-authoring.md#killed-hook-stub`](hook-authoring.md#killed-hook-stub))

## <a id="exec-probe"></a>本体を走らせずに exec の可否を調べる

bash は非対話で script を起動すると、 1 行目より前に `$BASH_ENV` の file を読む。 `exit 0` だけの file を渡すと
script は 1 行も走らず、 exec が通るかだけが分かる:

```bash
BASH_ENV=<exit 0 だけの file> <script>; echo $?    # 137 なら kill の判定が付いている
```

- 使えるのは shebang が bash の script だけ。 `#!/bin/sh` は非対話で `$ENV` / `$BASH_ENV` を読まない
- 同じ file の置き場所 = `scripts/lib/hook-exec-probe.bash`、 shell から使う関数 = `scripts/lib/hook-stub.sh` の `hook_exec_killed`
- bash の `Killed: 9` は待っている側の shell が出すので、 黙らせるなら `{ cmd; } 2>/dev/null`
- test で inode ごとの判定を再現する方法 = [`hook-authoring.md#exec-probe-test-techniques`](hook-authoring.md#exec-probe-test-techniques)

## <a id="log-reading"></a>unified log の読み方

- `/usr/bin/log show` と full path で呼ぶ (zsh では素の `log` が組み込みに取られる = [`shell-env.md#zsh-log-builtin`](shell-env.md#zsh-log-builtin))
- 署名は syspolicyd の `Yara scan` / `Malware rejection` / `100024` / `failed to call driver` と、 kernel の
  `would not allow process` / `Could not find reference`。 `--style compact` で時刻が先頭に来る
- ⚠️ **大量出力の後は行が落ちる**: 同じ時刻に画面で見えた行が、 後から時間を区切った集計には出なかった (実測)。
  件数は下限として読み、 0 件を「起きていない」 の証明にしない
- ⚠️ kill された個々の exec は記録されない。 どの file がいつ判定を覚えたかは log からは分からない

関連: アプリ自体の crash は [`macos-app-crash-triage.md`](macos-app-crash-triage.md)、 更新の後の全般的な重さは
[`macos-post-update-slowdown.md`](macos-post-update-slowdown.md)。
