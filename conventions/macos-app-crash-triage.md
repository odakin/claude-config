<!-- doc-meta
when: macOS で「(アプリ) が予期しない理由で終了しました」 が出たとき + 同じアプリが繰り返し落ちるとき + crash の原因を「ベンダーの不具合」「自動化のせい」 と言う前
category: macos
summary: macOS アプリの crash を、 .ips report・Chromium の Crashpad crash key・unified log の 3 つの証拠で型 (更新中の bundle 差し替えと再起動の競合 / window server に登録できない起動 / 起動直後 / 稼働中) に分け、 原因を誰かに帰属する前に環境側の要因を除外台帳で潰す。 道具 = scripts/macos-crash-triage.py (読むだけ)
-->
# macOS アプリの crash を型に分ける

「予期しない理由で終了しました」 は結果の表示であって、 原因の種類を何も言っていない。 同じダイアログでも、
アプリ自身の更新処理・自動化による起動・稼働中の不具合では対処が全く違う。 推測で原因を言う前に、 証拠を揃えて型に分ける。

## <a id="first-look"></a>最初の 1 コマンド

```bash
python3 scripts/macos-crash-triage.py --app "<report file 名の先頭 = process 名>" --log
```

[`macos-crash-triage.py`](../scripts/macos-crash-triage.py) は読むだけで、 アプリの起動・終了・設定変更をしない。
report ごとに 起動→落ちるまでの秒数 / report の版番号・crash key の版・今入っている版 / 例外 / 親 process /
faulting thread の先頭 frame / 起動引数 (Chromium 系) / 型 / 起動 5 秒以内のものは unified log の窓 を出す。
型の判定は手がかりであって結論ではない。 帰属を言う前に [#exclusion-before-vendor-blame](#exclusion-before-vendor-blame) を通す。

## <a id="crash-report-sources"></a>証拠の置き場と読み方の罠

- **`.ips`** = `~/Library/Logs/DiagnosticReports/<App>-<日時>.ips` (system 側 `/Library/Logs/DiagnosticReports` は読めないものがある)。
  1 行目が header JSON、 2 行目以降が本体 JSON で、 **本体の後ろに別の JSON が続くことがある** = 全体を `json.loads` すると
  `Extra data` で落ちる。 本体は `json.JSONDecoder().raw_decode` で先頭の 1 個だけ読む。
  本体の `procLaunch` と `captureTime` の差が「起動から何秒で落ちたか」。
- **header の `app_version` が空** = report を書いた瞬間に bundle の `Info.plist` が読めなかった。 通常の crash では埋まる。
  起動直後の crash でこれが空なら、 bundle が差し替え中だった強い印 ([#update-relaunch-race](#update-relaunch-race))。
- **Chromium 系の Crashpad dump** = `~/Library/Application Support/<vendor>/<product>/Crashpad/completed/*.dmp`。
  printable な文字列を並べると crash key が「key の直後に value」 で出る: `ver` (実際に動いていたコードの版) /
  `ptype` (`browser` = 本体) / `switch-N` (起動引数) / `[...:FATAL:<file>.cc:<line>] <message>` (CHECK 失敗の理由)。
  `ver` が report の版と違えば、 bundle と違うコードが動いていた。 dump と report は時刻で対応づける (数秒ずれる)。
- **unified log** = `/usr/bin/log show`。 zsh では素の `log` が組み込み関数に取られて `too many arguments` になるので full path で呼ぶ。
  `--start` / `--end` は小数秒を受けない (`%Y-%m-%d %H:%M:%S`)。 保持期間を過ぎた行は消えるので、 **該当行ゼロは「起きなかった」 の証拠にならない**。
  見る行: 更新器の process (Sparkle なら `Autoupdate`、 subsystem `org.sparkle-project.Sparkle`) / runningboardd の `LS launch <bundle id>` (起動要求) /
  AppKit の `_kLSApplicationWouldBeTerminatedByTALKey=1` (窓が全部閉じた) と `=0` / WindowServer の `Process death: ... (<名前>) ... pid: N` (誰が死んだかを名前つきで出す)。
- **署名の検査は strict を使わない**: `codesign --verify --deep --strict` は bundle 内の file の拡張属性 (FinderInfo 等) だけで
  `resource fork, Finder information, or similar detritus not allowed` と落ちる。 壊れの判定は `codesign --verify --deep` と `spctl -a -vv` で行う。

## <a id="crash-shape-classes"></a>型

| 型 (`class`) | 印 | 最初に疑うこと |
|---|---|---|
| `startup-during-bundle-replacement` | 起動 5 秒以内 + report の版番号が空、 または crash key の版 ≠ report の版 | アプリの自動更新と再起動の競合 → [#update-relaunch-race](#update-relaunch-race) |
| `startup-abort-app-registration` | 起動直後に HIServices の `RegisterApplication` / `TransformProcessType` で `abort()` | window server に登録できない文脈からの起動 → [#startup-abort-app-registration](#startup-abort-app-registration) |
| `startup-crash` | 起動 5 秒以内、 上の印なし | profile・拡張・GPU 設定の読み込み。 crash key の FATAL 行を読む |
| `runtime-crash` | しばらく動いてから | 何をしていたか。 symbol の無い frame しか無ければ原因は特定できないと書く |

親 process が `launchd` でない (`Python` / `Exited process` 等) なら、 アプリを別の program が起動している。

## <a id="update-relaunch-race"></a>更新中の bundle 差し替えと再起動の競合

Sparkle で自己更新する Chromium 系ブラウザで実測した連鎖:

1. 更新器が新しい版を取得して、 終了時に入れる形で待たせる (`defaults read <bundle id>` の `SULastCheckTime` が取得の時刻、 `SUAutomaticallyUpdate = 1` なら黙って入れる設定)。
2. 最後の窓が閉じる (`_kLSApplicationWouldBeTerminatedByTALKey=1`)。
3. 約 60 秒後、 **アプリ自身が**更新の署名を検査して (syspolicyd への接続) 普通に終了する (exit handler が走る)。
4. ほぼ同時に 再起動の起動要求 (`LS launch`、 起動引数に `--no-startup-window`) と 更新器 (`Autoupdate` の `PID to listen: <旧 pid>`) が並走する。
5. 再起動された process が**旧版のコード**で動き (crash key の `ver` が旧版)、 差し替えで消えかけの旧版の resource を読めずに 1 秒以内に落ちる。 report の版番号は空。

- **後始末は不要**: 差し替えが終われば普通に起動できる。 Chromium 系なら user-data-dir の `Last Version` file が新しい版に進めば起動成功、 profile は壊れていない。
- **機序は推定**: 5. で旧版のコードが動いた経路 (起動要求が旧 bundle を指したまま解決された等) は log からは確証できない。
  上流の同型の報告 = [brave/brave-browser#25576](https://github.com/brave/brave-browser/issues/25576) (再起動に 2 経路があり、 更新保留の有無で選び分けていない)。 同一の不具合かは別途確認が要る。
- **macOS の自動終了ではないことの確かめ方**: `Info.plist` に `NSSupportsAutomaticTermination` が無ければ、 窓が閉じた後に OS が黙って終了させることはない (3. はアプリ側の動作)。
- **予防策は未検証**: 更新を黙って入れる設定を切る (更新が遅れる代償) / 更新待ちの間は窓を全部閉じたまま放置しない、 はどちらも効果を実測していない。 効くと書く前に試す。

## <a id="startup-abort-app-registration"></a>window server に登録できない起動

`RegisterApplication` / `TransformProcessType` の `abort()` は、 GUI アプリの実行 file が window server に接続できない文脈
(sandbox の中の agent、 GUI session の外、 headless のつもりで GUI bundle を起動した等) から起動されたときに出る。 短時間に同じ report が並ぶなら自動化が再試行している。

- 親 process と起動時刻を、 その時刻に動いていた自動化 (agent の tool 実行・launchd の routine) と突き合わせる ([`debugging-discipline.md#execution-path-attribution`](debugging-discipline.md#execution-path-attribution))。
- 既に動いている browser と同じ user-data-dir で二度目を起動していないかを見る。 復旧の手順と禁止する短絡は [`debugging-discipline.md#recovery-state-dispatch`](debugging-discipline.md#recovery-state-dispatch) が正本。

## <a id="exclusion-before-vendor-blame"></a>「ベンダーの不具合」 と言う前の除外台帳

型が `startup-during-bundle-replacement` でも、 それだけで「アプリ側だけの不具合」 とは言えない。 引き金と並走した要因を、 証拠つきで 3 つの欄に分けてから答える:

| 欄 | 書くもの |
|---|---|
| 確認して外した | 何を・どの範囲で見て外したか (例: 「その時刻に動いていた agent session の記録 N 本に、 そのアプリを触る操作が無い」) |
| 外せていない | 見られなかった範囲・証明できなかった関与 (log の保持切れ、 省電力モードでの遅延、 アプリ内で動く拡張の native host 等) |
| 推定 | 機序のうち log から確証できない部分 |

確かめる候補:

- **agent の操作**: 落ちた時刻の前後に動いていた Claude Code / Codex の記録に、 そのアプリ・その bundle・`open -a`・`osascript`・`killall` を含む操作があるか。 記録の横断検索 = [`search-agent-transcripts.py`](../scripts/search-agent-transcripts.py)。
- **定期的な kill**: 同時刻の `killall` 等は、 WindowServer の `Process death` の名前で誰が死んだかを確かめる (別の常駐処理の kill が偶然重なっただけのことがある)。
- **OS の自動終了**: `NSSupportsAutomaticTermination` の有無。
- **更新器の設定と時刻**: `defaults read <bundle id>` の更新関係の key。
- **電源状態**: `pmset -g` の `lowpowermode`。 遅延で競合の窓が広がる可能性は、 否定も肯定もできないなら「外せていない」 に置く。

「絶対に」「だけ」 は、 外せていない欄が空のときにしか書かない。 一般則 = [`debugging-discipline.md#execution-path-attribution`](debugging-discipline.md#execution-path-attribution)。
