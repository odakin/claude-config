<!-- doc-meta
when: ネットから落とした file (browser で取得した PDF・zip・Office・script、 メールの添付、 curl / wget の取得物) を repo や作業 dir に取り込む前・開く前 + 取り込んだ file の来歴に安全検査の 1 行を書くとき + 「ウイルスチェックして」 と頼まれたとき + 取り込みを止める hook (downloaded-file-import-guard) に止められたとき + ClamAV を入れるか決めるとき
category: infra
summary: ネット由来の file は取り込む前に scripts/downloaded-file-scan.py で検査し、 結果を取り込み先に 1 行で残す。 検査の段 = 来歴 (quarantine 属性とダウンロードの印) / 中身の種類 (拡張子でなく先頭の bytes) / PDF の能動要素・埋め込み・OpenAction / zip と Office の macro・外へ取りに行く relationship・展開先の外を指す entry / 署名 scan (ClamAV が在れば) / XProtect の状態。 要確認・未検査の部分が出たら取り込まずに本人に見せる。 quarantine 属性は外さない。 網 = PreToolUse(Bash) の hook が Downloads から git の作業 tree への cp / mv / 展開を、 検査の記録が無ければ止める
-->
# ネット由来の file を取り込む前の安全検査

browser・メール・curl で手元に来た file を repo や作業 dir に入れる前に、 中身を検査して結果を記録する。
取り込んだ後は来歴が消える (git に入れて clone した file は macOS の quarantine 属性を持たない) ので、 検査したかどうかを後から確かめられるのは記録の 1 行だけになる。

## <a id="scan-before-import"></a>規則

1. **ネット由来の file は、 repo・作業 dir に置く前 (cp / mv / 展開の前) に検査する。** 道具 = `python3 <base>/claude-config/scripts/downloaded-file-scan.py <file か dir>…`。 対象は browser で落とした file、 メールの添付を保存した file、 curl / wget の取得物、 それらを展開した中身。 Preview・Office・browser で開くのも検査の後にする。
2. **結果を取り込み先に 1 行で残す。** 形は道具の「記録」 の行 (`--record` でその行だけが出る)。 置き場 = その file を使う note の来歴の欄、 書誌の台帳の notes、 取り込み先の dir の README のどれか ([#scan-record](#scan-record))。
3. **要確認が出たら取り込まない。** 何が出たかを本人に見せ、 取り込むと本人が決めたら、 その判断と理由も記録の行に書く。
4. **検査できなかった部分は「未検査」 と書く。** 暗号化された PDF・password つきの Office・暗号化された zip の entry・大きすぎる file は中身を見ていない。 「問題なし」 に丸めない。 署名 scan をしていない (ClamAV が無い) ことも記録の行に残る。
5. **quarantine 属性を外さない** (`xattr -d com.apple.quarantine` / `xattr -c` をしない)。 属性が残っていれば、 開く・実行するときに Gatekeeper と XProtect が見る。 外すと実行 file の起動時の検査が飛ぶ。
6. **道具は自分の置き場の path で起動し、 落とした file は引数で渡す。** 落とした file の dir に cd して Python を起動しない (その dir の `json.py` などが標準 library より先に import される)。 道具に `python3 -I` は付けない: user site の PyMuPDF が切れて PDF の段が回らない ([`python-env.md#isolated-mode-drops-user-site`](python-env.md#isolated-mode-drops-user-site))。 script として起動すれば sys.path の先頭は道具の dir になり、 落とした file は sys.path に入らない。

## <a id="scan-ladder"></a>検査の段

道具は上から順に見る。 どの段も「既知の仕掛けがあるか」 を数えるもので、 0 は安全の証明ではない ([#scan-limits](#scan-limits))。

| 段 | 何を見るか | 要確認になるもの |
|---|---|---|
| 1. 来歴 | macOS の `com.apple.quarantine` 属性 (`flags;時刻;取得した app;id`) と、 取得元の URL の記録 (`kMDItemWhereFroms`、 表示は host だけ) | — (記録に残すだけ) |
| 2. 種類 | 拡張子でなく先頭の bytes | 拡張子と中身の食い違い (`.pdf` の実体が実行形式・HTML の頁など)、 実行形式 (Mach-O・PE・ELF)、 `#!` の script、 disk image、 installer、 `.app` |
| 3. PDF | PyMuPDF で全 object を読んで数える = `/JavaScript` `/JS` `/Launch` `/AA` `/EmbeddedFile` `/RichMedia` `/XFA` `/SubmitForm` `/ImportData` `/GoToR` `/GoToE`、 埋め込み file、 link、 `/OpenAction` の中身 | 能動要素が 1 つでもある、 埋め込み file、 `/OpenAction` が頁を開く (`/S /GoTo` か行き先の配列) 以外 |
| 4. zip と Office | entry の一覧、 展開先の外を指す path (`../`・絶対 path)、 symlink の entry、 実行形式の entry、 暗号化された entry、 圧縮比、 中の PDF と zip (1 段まで)。 Office (docx / xlsx / pptx は zip) = macro、 ActiveX、 埋め込み object の中身、 外部 link、 DDE、 外へ取りに行く relationship | macro (`vbaProject.bin`・macro 有効の形式)、 ActiveX、 Packager の埋め込み、 http・https・UNC を指す relationship (開くと外の template などを取りに行く)、 外部 link、 DDE、 展開先の外を指す entry、 zip bomb の疑い |
| 5. 古い形式 | OLE2 (.doc / .xls / .ppt) は stream の名前を探すだけ。 RTF = `\object`。 SVG = script | macro の stream・Packager、 RTF の埋め込み object、 SVG の script |
| 6. 署名 scan | ClamAV の `clamscan` が在れば回す | 検出 |
| 7. 機械の状態 | `xprotect status` (launch scan・background scan が有効か) と `xprotect version` (定義の版と日付) | — (表示だけ) |

段ごとの注意:

- <a id="quarantine-download-bit"></a>**quarantine の flags の最下位 bit (0x0001) がダウンロードの印。** 実測: browser で落とした file には立ち、 sandbox の app (Preview など) が書き出した file には立たない (どちらも属性そのものは持つ)。 属性の有無だけで「ネット由来」 と決めると、 手元の app で作った file まで拾う。 macOS の `cp` (`-p` なしでも) と `mv` は拡張属性も写すので、 一度 scratch に写した file も印を持ったままになる (実測)。
- **PDF の名前の `#xx` escape** (`/J#61vaScript`) は PyMuPDF が解いてから数える。 PyMuPDF で開けない file は生の bytes を数えるが、 圧縮された object stream の中は見ないので「未検査の部分あり」 にする。
- **PDF の link の種類で起動の判定をしない。** 実測: MuPDF は scheme の無い URI (書き損じた `mailto;…` など) も「起動する link」 に分ける。 本物の起動は `/Launch` の数で数える。
- **password つきの Office は OLE2 の容れ物になる** (中身の OOXML を `EncryptedPackage` に包む)。 実測: `.xlsx` の実体が OLE2 だった file はこれだった。 拡張子の食い違いではなく「暗号化 = 未検査」 として扱う。
- **Office の埋め込み object** (数式・表・グラフ) は普通にある。 数えるだけにして、 中身が Packager・実行形式・macro のときに要確認にする。 relationship が作った機械の path (`file:///Y:\…`) を指すだけなら外へは取りに行かない。
- **`xprotect check` は file の検査ではない** (XProtect の更新が在るかを聞く命令、 実測)。 XProtect に file を指定して検査させる CLI は無い (見た範囲 = `xprotect help` の subcommand 5 つ)。 XProtect は開く・実行する時と background で働くので、 道具は状態だけを出す。

## <a id="scan-record"></a>記録の形

道具の「記録」 の行をそのまま写す。 例 (合成):

```
安全検査 (YYYY-MM-DD、 downloaded-file-scan.py): example.pdf (sha256 0123456789ab) / PDF / 来歴 = Brave (quarantine あり・ダウンロードの印あり) / 能動要素 0 (JavaScript・JS・Launch・AA・EmbeddedFile・RichMedia・XFA・SubmitForm・ImportData・GoToR・GoToE) / 埋め込み 0 / link 0 / OpenAction = 頁を開くだけ (/S /GoTo) / 署名 scan 未実施 (ClamAV なし) / 判定 = 要確認なし
```

- sha256 の先頭 12 桁で、 記録と取り込んだ file を結びつける。 取得元の host は記録の行に入れない (画面の表示だけ。 公開の repo に取り込む file でも記録の行が行き先を漏らさないため)。
- **file だけを置いて記録を書かない形にしない。** clone した先では属性が消えるので、 検査したかを確かめる手がかりが残らない。
- 本人が要確認の file を取り込むと決めたときは、 記録の行の後に「取り込みは本人の判断 (理由 …)」 を足す。

## <a id="import-net"></a>網 (hook)

[`hooks/downloaded-file-import-guard.py`](../hooks/downloaded-file-import-guard.py) (PreToolUse Bash) が、 Bash の command のうち `cp` / `mv` / `ditto` / `rsync` / `install` / `ln` / `unzip` / `tar` の展開で、 ネット由来の file を git の作業 tree に入れるものを見る。

- **ネット由来とみなす file** = `~/Downloads` の下 (env `DOWNLOADED_FILE_SCAN_SOURCES` に `:` 区切りで足せる) か、 ダウンロードの印の付いた file。
- **取り込み先** = git の作業 tree の中 (HOME そのものが git の作業 tree でも HOME は数えない。 Downloads の中への移動は数えない)。
- **止める条件** = その file の検査の記録が無い、 要確認が出ている、 未検査の部分がある。 止める文に検査の command が出る。 検査を回せば、 同じ command が次は通る。
- **検査の記録** = 道具が `~/.claude/state/downloaded-file-scan/` に、 path・大きさ・更新時刻の key と中身の sha256 の key で残す (同じ中身なら、 一度 scratch に写した file からでも通る)。 記録は machine-local = 別の Mac で取り込むときは、 その Mac で検査し直す。
- **本人が取り込むと決めた file** は、 command に `# downloaded-file-scan: accepted <理由>` を書いて打ち直す。 理由は記録の行にも書く。 この印は agent が自分の判断で付けない。
- heredoc の本文、 引用符の中、 commit message の中の `cp` は command と読まない。 同じ command の中の代入 (`D=docs; cp … $D/`) は解く。 解けない変数は見ない (fail-open)。 `for` の変数と `xargs` の置き換えも見ない。 同じ command の中で一度 scratch へ写してから repo へ写す 2 段も見えない (hook は command の実行前に走るので、 2 段目の元の file がまだ無い)。 別の command に分ければ、 ダウンロードの印の付いた file は scratch でも印を持ったままなので止まる。
- 校正: 判定の形 (`shape_issues`) を手元の全期間の Bash command に当てると、 当たったものは全部 Downloads から git の作業 tree への本当の取り込みで、 誤検出は 0 だった。 見逃しの側は、 Downloads と取り込みの命令を含む command を広い正規表現で拾って読み、 当たらなかったものは全部、 行き先が scratch・一時 dir・ゴミ箱・Downloads 自身だった (実測。 手順 = [`hook-authoring.md#command-guard-calibration`](hook-authoring.md#command-guard-calibration)、 再現 = `calibrate-bash-command-pattern.py --hook scripts/downloaded-file-scan.py --func shape_issues` と `--pattern`)。
- **射程外** = curl / wget で repo に直接落とす、 python の `shutil` などの script の中の copy、 redirect (`cat x > y`)、 Finder での移動、 メールの添付を script で repo に直接保存する、 Codex の session (網は Claude Code の hook だけ)。 これらは規則 1 を自分で当てる。

## <a id="clamav-install"></a>ClamAV の入れ方 (macOS・Homebrew)

ClamAV は既知の検体を署名で探す。 入れるかは本人が決める (定義は 100 MB 余り、 定義の更新を定期に回す)。 道具 = `bash <base>/claude-config/scripts/install-clamav.sh` (足りないものだけ揃える。 `--check` = 確かめるだけ、 `--update` = 定義の更新)。 やること = `brew install clamav`、 `freshclam.conf.sample` の `Example` の行を外して `freshclam.conf` に、 `freshclam` で定義の取得 (Homebrew の案内 = `brew info clamav` の caveats と同じ)。 `brew install` の前に [`install-failures.md`](install-failures.md) を読む。

入れた後は、 検査の道具が `clamscan` を見つけて自動で回す (PATH に無ければ `/opt/homebrew/bin` と `/usr/local/bin` も探す)。 file ごとに `clamscan` が定義を読むので、 1 file に数秒かかる (実測)。 常駐の `clamd` は使わない。

- **定義の更新**: 定義が古いままだと新しい検体を拾わない。 `install-clamav.sh --update` を呼ぶ shim を定期 job に載せる ([`install-launchd-cron.sh`](../scripts/install-launchd-cron.sh) の cmd routine。 label と時刻は呼び出し側の層が決める)。 Agent の登録は常駐の仕組みの追加なので、 本人が決めてから入れる。
- **効いているかの確かめ方**: 無害な検査用の文字列 EICAR の file を scratch に作って検査の道具に渡すと、 `Eicar-Test-Signature` が出て要確認になる (zip の中でも出る、 実測)。 定義の署名は `sigtool --info=<定義の dir>/daily.cvd` の `Verification OK`。
- 定義の download のときに `ERROR: NULL X509 store` が出ることがある (実測: 終了値は 0 で定義は取れ、 `sigtool` の検証は OK。 原因は見ていない)。

## <a id="scan-limits"></a>保証の境界

- 構造の検査は既知の仕掛け (能動要素・macro・埋め込み・外への relationship) の有無を数えるだけ。 開く app (PDF の viewer・Office) の脆弱性を突く file は、 仕掛けを持たなくても害になりうる。 開く app を新しく保つ。
- 署名 scan は既知の検体だけを拾う。
- 暗号化された中身、 入れ子の 2 段目より深い archive、 tar・gzip・7z・rar の中身は見ない (展開してから中身を検査する)。
- OLE2 は stream の名前を探すだけで、 macro の中身までは読まない (詳しく見るなら oletools の `olevba` を別に使う)。
- 網は Bash の command の形しか見ない。 射程外の経路は規則 1 を自分で当てる。
- 検査の記録は machine-local の file で、 同じ OS 権限の agent は直接書ける。 網が保証するのは「検査を回さずに取り込む」 を止めるところまでで、 記録の偽造は止めない。 網を外す `CLAUDE_DOWNLOAD_IMPORT_GUARD=0` は本人の明示の指示があるときだけ使う ([`agent-rule-ownership.md#guard-escape-hatch`](agent-rule-ownership.md#guard-escape-hatch))。

## <a id="related"></a>関連

- 外から来た tool の結果に指示文が紛れる問題 = [`prompt-injection.md`](prompt-injection.md)
- 受け取った URL・file を別の人に渡す前 = [`sensitive-data-pass-through.md`](sensitive-data-pass-through.md)
- PDF の読み取りの道具 = [`office-files.md`](office-files.md)
- hook の書き方と校正 = [`hook-authoring.md`](hook-authoring.md)
