<!-- doc-meta
when: Claude Code の App Management TCC dialog が繰り返し出るとき + 版番号 (2.1.NNN) だけのポップアップ・process 名を見たとき + CLI の版が上がるたびにデスクトップ・書類・ダウンロード・cloud storage の許可を聞き直される・無人の run が許可待ちで止まるとき (#stable-cli-path) + 自作 CLI の TCC 許可ダイアログが「許可」 を押しても出直すとき (#half-signed-universal-binary)
category: macos
summary: Claude Code の app bundle が `~/Library/Application Support/Claude/claude-code/<version>/claude.app` という versioned path に置かれているため、 App Management TCC 権限が auto-update 毎に invalidate されて dialog が再 prompt される構造的症状 (= sibling pty-leak と同じく Anthropic 側 fix 待ち候補、 stable launcher path 化が root 対策)。 CLI 版 (実行 file の名前が版番号) は手元で直せる = 版に依らない固定の場所に複製してそこから起動する (#stable-cli-path)
-->
# macOS Claude Code app-bundle versioned-path → TCC App Management recurring prompt

**症状**: macOS Ventura 以降で Claude Code 起動時 (= 内部で CLI 同梱 `.app` を起動するタイミング) に **「"claude.app" がほかのアプリからのデータへのアクセスを求めています。」** (英: `"claude.app" wants access to data from other apps`) という macOS App Management 権限 dialog が **繰り返し** 表示される。 「許可」 を押しても、 後日同じ dialog が再び出る。

これは Claude Code が auto-update されるたびに発生する **構造的** な症状で、 user 操作の押し間違いではない。 sibling 事象 `macos-claude-app-pty-leak.md` と同じく Anthropic 側 fix 待ち候補。

## 構造原因

Claude Code は自身の app bundle を **versioned path** に install する:

```
~/Library/Application Support/Claude/claude-code/<version>/claude.app
```

例: `~/Library/Application Support/Claude/claude-code/2.1.149/claude.app`

macOS の **App Management** TCC 権限 (= `kTCCServiceSystemPolicyAppData`、 macOS Ventura 13.0 で導入、 他 app の container / Application Support 配下を読み書きしようとした時に発火) は **`(bundle absolute path, code signature)`** をキーとして TCC db に登録される。

Claude Code が auto-update されると subdir 名が `2.1.149` → `2.1.150` → ... と変わるため、 **新 path に対する TCC エントリは未登録扱い** になり、 dialog が再 prompt される。 前 version の許可 record は db 内に残るが、 新 path と一致しないので参照されない (= 孤立 entry の累積)。

注: ダイアログの **"claude.app" 小文字表記** は CLI 同梱の bundle (`com.anthropic.claude-code`) を指す。 `/Applications/Claude.app` (= Desktop app、 bundle id `com.anthropic.claudefordesktop`) とは **別バンドル** で、 Desktop app 側の TCC 設定を触っても解決しない。

## Diagnosis

```bash
# 1. versioned subdir 構造の確認 (= 症状 prerequisite)
ls -la "$HOME/Library/Application Support/Claude/claude-code/"
# → drwx... 2.1.149  のような semver subdir があれば該当

# 2. bundle 同定 (= identifier と Team ID)
codesign -dv "$HOME/Library/Application Support/Claude/claude-code/"*/claude.app 2>&1 | \
  grep -E 'Identifier|TeamIdentifier'
# Identifier=com.anthropic.claude-code
# TeamIdentifier=Q6L2SF6YDW

# 3. /Applications/Claude.app との別バンドル性確認 (= 混同防止)
codesign -dv /Applications/Claude.app 2>&1 | grep Identifier
# Identifier=com.anthropic.claudefordesktop  ← Desktop は別

# 4. System Settings > Privacy & Security > App Management に
#    過去 version の claude entry が累積しているか目視
#    (= 同じ "claude" 名で複数行ある場合は孤立 entry が溜まっている兆候)
```

## Workaround

### 1. 一貫してどちらかを押して sticky 化

「許可」 を一度押すと **同一 version path に対しては** sticky 化する (= 同 version 中は再 prompt されなくなる) ことは実証済 (2026-05-26 odakin 観察)。 「許可しない」 側の sticky 化は TCC 仕様上同様に期待されるが本 doc 時点では未実証 — 試すなら機能影響 (= 何が壊れるか) を観察すること。

機能影響が無い (= 拒否で実害なし) と確認できれば、 user が press する手間を減らす意味では「拒否」 で sticky 化するのが軽い。 不明なら「許可」 で sticky 化が安全側。

ただしどちらにせよ **次の Claude Code 更新で新 path が出てまた prompt される** のは同じ (= 構造原因が同じ)。 単に「同 version 中の repeat を止める」 効果だけ。

### 2. System Settings で明示的に整理

System Settings > Privacy & Security > App Management:
- 「claude」 entry が複数並んでいたら過去 version の残骸 — 不要なものを 「−」 で削除
- 現 version の entry を ON にする

これも **次の更新までしか持たない** (= 構造的 root 対策ではない)。

### 3. 個別 prompt を許容して放置

Anthropic 側 fix を待つ前提なら、 dialog が出たときだけ押す運用も合理的。 user に余計な reflex を求めない。

## upstream への報告候補

構造的に root 対策は upstream (= claude-code) でしか出来ない:
- app bundle を versioned subdir でなく **stable launcher path** (例: `~/Library/Application Support/Claude/claude-code/current/claude.app` を versioned 実体への symlink にする) に置く
- または App Management 不要な設計に改修

[anthropics/claude-code](https://github.com/anthropics/claude-code/issues) 等に「claude-code's bundled .app at versioned path causes recurring TCC App Management prompts after every update」 で issue を上げる価値あり。

## なぜ気づきにくいか

- dialog 文言は generic — どの app の data へアクセスしようとしたかは出ない
- 「許可」 を押した直後は許可された (= 当該 version path で TCC 登録成功) ように見えるので、 後日再 prompt が来ると「なぜまた?」 と困惑する
- `/Applications/Claude.app` (Desktop) の TCC 設定を見ても症状解消しない (= 別バンドル) ことを user は容易に見抜けない
- App Management の TCC entry は System Settings の **App Management** subsection に出るが、 「Full Disk Access」 等の隣接 subsection と混同しやすい

## How to apply

- macOS で claude.app 関連の TCC dialog が **繰り返し** 出たら、 まず `ls "$HOME/Library/Application Support/Claude/claude-code/"` で versioned subdir 構造を確認 — 同じ症状なら同じ path 構造が原因
- System Settings > Privacy & Security > App Management で過去 version の claude entry が累積していないか確認、 累積していれば整理
- 個別 prompt は許可 / 拒否で sticky 化する (= 同一 version 中の repeat は止まる)、 ただし **次の更新で再発する構造**
- 同種の versioned-bundle-path 構造は他の auto-updating Mac app 全般で起こりうる pattern で、 Claude Code 固有 bug ではなく **macOS App Management の path-binding 特徴**

## <a id="cli-binary-named-by-version"></a>姉妹: CLI 版は実行 file の名前そのものが版番号

- ターミナルの `claude` (native installer) は `~/.local/bin/claude` → `~/.local/share/claude/versions/<版>` の symlink で、 **実行 file の名前が `2.1.NNN` という版番号そのもの** (app bundle ではない)。
- ∴ macOS が process 名を出す面 (一時的なポップアップ・権限 dialog・Activity Monitor・unified log の `pid[名前]`) には `2.1.NNN` とだけ出て、 Claude だと読めない。 **版番号だけのポップアップを見たら、 まずこれを疑う** (実測)。
- 切り分け: `readlink ~/.local/bin/claude` の版と一致するか → `/usr/bin/log show --last 2h --style compact --predicate 'eventMessage CONTAINS "<版>"'` で同名 process の起動時刻を見て、 hook・定期実行・session 開始が `claude` を呼んだ時刻と突き合わせる。 ⚠️ 通知センターの DB (`$(getconf DARWIN_USER_DIR)com.apple.notificationcenter/db2/db`) は閉じた通知の record が消えることがある = 「DB に無い」 は通知でなかった証明にならない。
- desktop アプリの Code タブは同梱の別版 (上の versioned `claude.app`) を使う = **CLI と desktop の版が違うのは正常** (CLI は単体で自動更新、 同梱版はアプリの更新でだけ上がる)。 同梱版の path に付けた権限 (フルディスクアクセス等) は、 同梱版が上がると付け直しになりうる。
- 版番号だけの名前の **許可 dialog が版上げのたびに出る** なら、 次節の形 (CLI が自分で許可の責任者) — 直し方 = [`#stable-cli-path`](#stable-cli-path)。

## <a id="stable-cli-path"></a>CLI 版: 版上げのたびに許可を聞き直す → 版に依らない固定の場所から起動する

- **症状**: launchd の定期 job・常駐の server など、 CLI が**自分で**許可の責任者になる起動 (= 親が app でない。 中継が責任を手放して起動した子も同じ) で、 版が上がるたびにデスクトップ・書類・ダウンロード・cloud storage (File Provider) の許可を全部聞き直す。 dialog の主は版番号の名前。 端末や desktop アプリから起動した CLI は親の app が責任者なので出ない
- **dialog は答えるまで呼び出しを止める** (実測: 次の folder の要求は、 前の folder に答えた直後に出る = 順に待っている)。 誰もいない時間の無人の run はそこで止まり、 次の予定の run も来ない (launchd は走っている job を重ねて起動しない)
- **原因**: macOS はこの形の client を **実行 file の path** で記録する (unified log の tccd の行が `identifier_type=Path, identifier=<…/versions/<版>>`)。 記録と照合する要件は署名の designated requirement = **identifier + Team ID** で、 版を跨いで同じ (log の `kTCCCodeIdentityAuthority = kTCCCodeIdentityDesignatedRequirementAuthority`)。 = path さえ変わらなければ、 一度の許可が次の版にも当たる。 native installer は版ごとに新しい file を置いて launcher の symlink を付け替えるので、 path が毎回変わる
- **直し方**: launcher の指す版を **版に依らない固定の場所に複製**し、 責任者になる起動をそこから行う。 道具 = [`scripts/claude-stable-path.sh`](../scripts/claude-stable-path.sh) (既定 `~/.local/share/claude-stable/claude`)
  - **複製は APFS の clone** (`cp -c` = 容量を食わない)。 hard link にしない (= 同じ file に名前が 2 つあると、 process の path がどちらで報告されるか保証されない)
  - **差し替えは一時名に置いて `mv`** (= 走っている process は古い file を持ったまま壊れない)。 差し替える前に署名を確かめ、 署名の主 (identifier + Team ID) が前の版と違えば差し替えない
  - **launcher は触らない** = 上流の自動更新・古い版の掃除はそのまま動く。 固定の場所から起動した CLI も `claude doctor` で native の install と認識される (実測)
  - **対象は native installer の CLI だけ**: npm で入れた CLI は実行 file の path が版を跨いで同じ (版上げは同じ path の file を置き換える) = 固定の場所は要らない見込み (許可が版を跨いで保たれるかは未確認)。 道具は native の launcher が無い機械では見張りを入れず、 何も出さない
  - **揃える契機を 2 つ**: launchd の `WatchPaths` (launcher の dir と versions/ の変化) と、 使う直前の確認 (起動の中継が揃えてから起動する)。 見張りが取りこぼしても run は古い版で走らない
  - **呼び出し側**: 定期 job の起動行の絶対 path と `PATH` の先頭 (= script の中で `claude` を呼ぶ job も同じ file)、 常駐の server の plist の `PATH` の先頭。 常駐の server は止めず、 plist の file だけを直して次の起動から (層1 の engine = [`install-launchd-cron.sh`](../scripts/install-launchd-cron.sh) / [`install-remote-control-server.sh`](../scripts/install-remote-control-server.sh) / [`claude-stream-log.py`](../scripts/claude-stream-log.py))
- **切り替えた直後に 1 回ずつ** 聞かれる (固定の場所は新しい path)。 これが最後 = 以後の版では出ない。 誰もいない時間の run で初めて出ると止まるので、 切り替えたら人がいる時に一度起こして答えておく
- **届かないもの**:
  - **background session (`claude --bg`)**: CLI が自分の daemon を launcher の path で起動し、 worker を versions/ の path から起こす (実測) = 呼ぶ側の path では変わらない (上流の範囲)
  - **無人の run だけ folder を除く形**: `--settings` の `permissions.additionalDirectories` は既存の list に足されるだけで、 list から消すことはできない (実測)。 `--setting-sources` で user の設定を読まない形なら list から消えるが、 user の agent と skill も読まなくなる (実測) = 固定の場所の許可で止めるほうが副作用が無い
  - **カレンダー等の個人情報**: hardened runtime の CLI に entitlement が無い service は prompt すら出ず黙って拒否される (log に `Policy disallows prompt`) = path では直らない。 その service を持つ app 経由で読む
- **確かめ方**: 版上げの後、 `/usr/bin/log show --last 2h --style compact --predicate 'subsystem == "com.apple.TCC" AND eventMessage CONTAINS "AUTHREQ_PROMPTING"'` に固定の場所の path の行が無いこと (zsh では `log` が組み込みに取られる = [`shell-env.md#zsh-log-builtin`](shell-env.md#zsh-log-builtin))

## <a id="half-signed-universal-binary"></a>姉妹: 片 slice だけ署名した universal binary は許可が残らない

- **症状**: 自作の CLI (EventKit でカレンダーを読む等) の TCC 許可ダイアログが、 「許可」 を押しても次の起動でまた出る。 ダイアログには CLI 自身の名前が出る (= 許可の帰属先が CLI 自身)。 launchd の定期ジョブから起動した時に出やすく、 端末や Claude から起動すると親 app の許可で通るので手元では再現しない
- **原因**: arch ごとに build して `lipo -create` で合成すると、 arm64 の linker は ad-hoc 署名 (`flags=…(adhoc,linker-signed)`) を自動で付けるが、 x86_64 には付けない。 TCC が許可時に記録する要件 (`csreq`) は file から作った `cdhash H"…" or cdhash H"…"` の形で、 片側が未署名だと実行中の arm64 の cdhash がどちらとも一致しない = 毎回「未許可」 に戻る (実測)
- **診断**: `codesign -dvvv --arch x86_64 <bin>` が `not signed at all` で、 `--arch arm64` には署名がある → 該当。 TCC.db の行の cdhash (`sqlite3 ~/Library/Application\ Support/com.apple.TCC/TCC.db "select hex(csreq) from access where client like '%<bin>%'"`、 読むにはフルディスクアクセスが要る) と `codesign -dvvv --arch arm64 <bin>` の `CDHash=` を突き合わせる。 ダイアログで止まった起動は unified log で `process == "<bin>"` の行が数行だけ (`Requesting full access` で途切れる) になるので、 何時に出ていたかを後から数えられる (`/usr/bin/log show`、 zsh では `log` が組み込みに取られる = [`shell-env.md#zsh-log-builtin`](shell-env.md#zsh-log-builtin))
- **直し方**: `lipo` の後に `codesign -s - -f -i <逆ドメインの識別子> <bin>` で両 slice を署名し直し、 build script にも同じ行を入れる。 署名し直すと中身が変わるので、 各マシンで 1 回だけ許可し直す (以後は残る)。 ⚠️ build し直すたびに cdhash が変わる = そのたびに 1 回ずつ出る (ad-hoc 署名の限界。 証明書つきの署名なら要件が識別子になり、 build を跨いで残る)
- **出始めるきっかけ**: 呼び出す側の interpreter を替えると、 許可の帰属先が親から CLI 自身へ移る = [`shell-env.md#job-python-switch-moves-tcc`](shell-env.md#job-python-switch-moves-tcc)。 定期ジョブの実行環境を替えた後にダイアログが出始めたら、 まずこれを疑う

## 関連

- `macos-claude-app-pty-leak.md` (= sibling、 Claude.app Desktop 側の別 pty leak 症状、 同じく Anthropic side fix 待ち)
- `launchd-cloudstorage-tcc.md` (= 別型の TCC 症状 — launchd 経由の script が `~/Library/CloudStorage/` を読めない、 invoker 単位で TCC 判定される macOS 15+ の permission 継承挙動が原因。 本 doc が「versioned path で TCC db entry 無効化」 なのに対し、 sibling は「invoker の TCC identity 不足」 が root)
- macOS App Management TCC service: `kTCCServiceSystemPolicyAppData` (Ventura 13.0+)
