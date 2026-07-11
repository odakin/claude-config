<!-- doc-meta
when: launchd agent が ~/Library/CloudStorage/ 配下を読む script を書く前
category: macos
summary: launchd agent が ~/Library/CloudStorage/ (Dropbox / iCloud Drive / OneDrive / Box) 配下を読む script を書くための TCC 越え pattern (= 症状 Operation not permitted は手動実行なら通るが launchd 経由で失敗 / 3 択 A: /bin/zsh に FDA〔広すぎ非推奨〕 A': osacompile で狭い .app wrapper + narrow FDA〔推奨、 permission holder が narrow + 自己記述性〕 B: CloudStorage 外に mirror〔permission dance 不要〕 / A' 実装テンプレ = osacompile + open -g -a + EnvironmentVariables LANG + FDA panel での .app 選択 / gotcha = LANG 未設定で日本語 path 壊れる / open -a 非同期 / bundle ID 衝突)
-->
# launchd agent が `~/Library/CloudStorage/` を読むための TCC 越え pattern

macOS 15+ で launchd agent (`~/Library/LaunchAgents/*.plist`) から呼び出したシェル script が **`~/Library/CloudStorage/` 配下 (= Dropbox / iCloud Drive / OneDrive / Google Drive / Box 等の FileProvider 経路)** を読もうとすると `Operation not permitted` で失敗する。

Terminal から手動実行すれば通るのに launchd 経由だと失敗する = **TCC (Transparency, Consent, and Control) の Full Disk Access permission が invoker ごとに別評価**されるため。 Terminal.app / iTerm2 は既に FDA を持っていて terminal 経由 script はそれを継承する、 launchd 起動の process は継承元が無いのでゼロから TCC 判定される。

本 doc は「launchd → CloudStorage 読み」 の 3 種類の解決策とそれぞれの trade-off、 推奨 pattern の実装テンプレを記す。

---

## <a id="symptom-and-diagnosis"></a>症状と診断

### 症状

launchd 経由の script が次のようなエラーで止まる:

```
ls: /Users/<you>/Library/CloudStorage/Dropbox/<folder>: Operation not permitted
```

対応する launchd log (`~/Library/Logs/<agent>.log` 相当):

```
find: /Users/<you>/Library/CloudStorage/Dropbox/<folder>: Operation not permitted
```

手動で terminal から script を叩くと成功する = 決定的シグナル。

### 診断: script に diag ログを仕込む

```zsh
DIAG_CNT=$(ls -1 "$FOLDER" 2>/dev/null | wc -l | tr -d ' ')
DIAG_ERR=$(ls -1 "$FOLDER" 2>&1 >/dev/null)
echo "$(date '+%F %T') DIAG ls_count=$DIAG_CNT ls_err='$DIAG_ERR' user=$USER pwd=$PWD" >> "$LOG"
```

launchd 経由の実行で `ls_err='ls: <path>: Operation not permitted'` が出れば TCC 確定。

---

## <a id="solution-comparison"></a>解決策 3 種類 + trade-off

| 方式 | permission 範囲 | 実装コスト | attack surface | 推奨度 |
|---|---|---|---|---|
| A. `/bin/zsh` (or `/bin/bash`) に FDA | **全 zsh script** | 5 秒 GUI | 全 zsh 実行が FDA 継承 | ⚠️ 広すぎ |
| **A'. `osacompile` で狭い .app wrapper → その .app にだけ FDA** | この 1 app のみ | 5-10 分 | **この app のみ** | ⭐ 推奨 |
| B. CloudStorage 外に mirror | **permission 不要** | 5-10 分 | ゼロ | ◎ 最頑健 |

### 各 trade-off 詳細

**A の増分リスク**: Terminal.app は既に FDA 相当を持っているので、 terminal 経由 zsh script は既に事実上 FDA を持っている。 A が増分で許可するのは「Terminal を経由せず launchd / cron / 他アプリ子プロセスから起動された zsh」。 `curl | zsh` パターンを軽率に走らせない user なら実害は低いが、 permission holder が抽象的すぎて自己記述性を欠く。

**A' が優れる点**: 「WallpaperRotator.app に FDA」 なら **意味的に「これは wallpaper rotator である」と自己記述**され、 FDA panel を後日見直した時に「なぜ FDA 持ってる?」 が即座に分かる。 permission holder が narrow + 意図明示。

**B が最頑健な理由**: `~/Pictures/` `~/Documents/` 等の**通常フォルダは FDA 対象外** = TCC 判定を一切通らないので permission dance ゼロ。 mirror 元を Dropbox に置いたまま `rsync` で local に落とし、 script は local を読む構成。 CloudStorage 側の同期が壊れても local mirror は生き残る (= 独立性が高い)、 permission 変更に依存しない。 disk 二重消費 (13 GB クラスなら要検討) が唯一の trade-off。

---

## <a id="a-prime-implementation"></a>A' 推奨 pattern の実装テンプレ

CloudStorage 配下 photo フォルダから乱択して壁紙にする例で示す。 他用途 (= Dropbox 内の script 実行 / CloudStorage 内の csv を集計 / etc.) にも横展開可。

### 1. shell script を書く

`~/.local/bin/rotate-wallpaper.sh`:

```zsh
#!/bin/zsh
FOLDER="${WALLPAPER_FOLDER:-$HOME/Library/CloudStorage/Dropbox/<subpath>}"
LOG="$HOME/Library/Logs/wallpaper-rotate.log"

if [[ ! -d "$FOLDER" ]]; then
  echo "$(date '+%F %T') ERR folder missing: $FOLDER" >> "$LOG"
  exit 1
fi

IMAGE=$(find "$FOLDER" -maxdepth 1 -type f \
  \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.heic" \) \
  -size +1k 2>/dev/null | sort -R | head -1)

if [[ -z "$IMAGE" ]]; then
  echo "$(date '+%F %T') ERR no image in $FOLDER" >> "$LOG"
  exit 1
fi

/usr/bin/osascript -e \
  "tell application \"System Events\" to tell every desktop to set picture to \"$IMAGE\"" 2>>"$LOG"
RC=$?
if [[ $RC -eq 0 ]]; then
  echo "$(date '+%F %T') set $(basename "$IMAGE")" >> "$LOG"
else
  echo "$(date '+%F %T') ERR osascript rc=$RC image=$IMAGE" >> "$LOG"
fi
exit $RC
```

```bash
chmod +x ~/.local/bin/rotate-wallpaper.sh
```

### 2. `osacompile` で wrapper .app を作る

```bash
mkdir -p ~/Applications
osacompile -o ~/Applications/WallpaperRotator.app \
  -e 'do shell script "'"$HOME"'/.local/bin/rotate-wallpaper.sh"'
```

`osacompile` 生成物は正規の `.app` bundle (= `Info.plist` に bundle identifier + code signature、 TCC 的に 1 個の identity として認識される)。 内部の AppleScript が `do shell script` で外部 script を呼び出す構造 = **TCC 判定は wrapper .app 全体で 1 回、 子プロセスも継承する**。

### 3. launchd plist を書く

`~/Library/LaunchAgents/com.<you>.wallpaper-rotate.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.<you>.wallpaper-rotate</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/open</string>
    <string>-g</string>
    <string>-a</string>
    <string>/Users/<you>/Applications/WallpaperRotator.app</string>
  </array>
  <key>StartInterval</key>
  <integer>60</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>EnvironmentVariables</key>
  <dict>
    <key>LANG</key>
    <string>en_US.UTF-8</string>
    <key>LC_ALL</key>
    <string>en_US.UTF-8</string>
    <key>PATH</key>
    <string>/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StandardOutPath</key>
  <string>/Users/<you>/Library/Logs/wallpaper-rotate.stdout.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/<you>/Library/Logs/wallpaper-rotate.stderr.log</string>
</dict>
</plist>
```

### 4. bootstrap

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.<you>.wallpaper-rotate.plist
launchctl list | grep wallpaper-rotate                        # 存在確認
launchctl kickstart -k gui/$(id -u)/com.<you>.wallpaper-rotate  # 即発火
```

### 5. FDA を **wrapper .app** に付与

**System Settings → プライバシーとセキュリティ → フルディスクアクセス**:

1. `+` ボタン
2. `⌘⇧G` で path 入力: `~/Applications/WallpaperRotator.app` (or 絶対 path)
3. `.app` 選択 → 「開く」
4. リストに追加された WallpaperRotator トグルを **ON**
5. パスワード or Touch ID で承認

これで launchd 経由の script が CloudStorage 読める。

### 6. 動作確認

```bash
launchctl kickstart -k gui/$(id -u)/com.<you>.wallpaper-rotate
tail -3 ~/Library/Logs/wallpaper-rotate.log
```

`set <filename>` が出れば成功、 `ERR no image` or `Operation not permitted` なら FDA 未反映 (= System Settings で ON になってるか再確認、 一度 OFF/ON し直すと効くこともある)。

---

## <a id="gotchas"></a>Gotcha 集

### `LANG` 未設定で日本語 path が壊れる

launchd 環境はデフォルトで **`LANG` / `LC_ALL` が空**。 日本語文字 (or 他の非 ASCII) を含む path は `find` / `ls` に渡した瞬間 encoding 判定を失敗して "No such file" 相当の結果を返す (= エラー無し、 file が見つからないだけ)。 plist の `EnvironmentVariables` に必ず:

```xml
<key>LANG</key>       <string>en_US.UTF-8</string>
<key>LC_ALL</key>     <string>en_US.UTF-8</string>
```

を入れる。 忘れると症状が「TCC が原因かと思ったら実は locale が原因だった」 になり、 診断が難航する。

### `open -a` は非同期 (= 待たない)

`open -a <app>` は LaunchServices に要求を投げて即座に返る。 launchd はその瞬間 process を「終了した」 と見なす。 これは短時間 script (数秒) では問題ないが、 script が数十秒以上かかる & interval を短くしすぎると多重起動する。 大概 `StartInterval` を **script 実行時間の 3-5 倍以上**にしておけば安全。

`-g` flag は「前面に持ってこない」 (= background 起動)、 GUI が奪われない。 rotation 系はこれを必ず付ける。

### `osacompile` 生成の .app は AppleScript 実行時にも user confirmation ダイアログを出すことがある

初回起動時に「"WallpaperRotator" が "System Events" を制御しようとしています」 のダイアログが出る = **Automation permission** の要求。 「OK」 で通す。 一度承認すれば以後出ない。 launchd 経由で初回起動された場合もダイアログが出るので、 手動で一度 `open -a ~/Applications/WallpaperRotator.app` して承認を通すのが確実。

### FDA トグルは **絶対 path で照合されている**

`.app` を `~/Applications/` から別 path に move すると FDA が無効化される。 リビルドで path が変わるなら `~/Applications/` 直下に置く運用が安定 (= osacompile で `-o` に指定した path が canonical)。

### bundle ID の重複に注意

`osacompile` は生成物の bundle ID を **`com.apple.ScriptEditor.id.<applet-name>`** に自動設定する (= applet 名部分は input file 名から派生)。 同じ system 上に複数の osacompile wrapper を作るとき、 `.app` name を別々にしないと bundle ID conflict で TCC 判定が混線する。

### <a id="tahoe-app-data-per-process-gotcha"></a>macOS Tahoe (26+) の `kTCCServiceSystemPolicyAppData` は per-process semantic

Tahoe 26.5.1 で **`~/Library/Application Support/<app>/`** (= 他アプリのデータ dir) への書込みが `kTCCServiceSystemPolicyAppData` の TCC prompt を発火するようになった。 System Settings → プライバシーとセキュリティ → アプリ管理 で明示 grant しても **grant が persist しない** (2026-07-11 実測)、 `StartInterval` 経由の launchd 発火だと毎回 new process spawn ゆえ **60 秒ごとに TCC prompt が繰り返し表示される**。

**回避策**: launchd を **daemon mode** に = `StartInterval` 削除 + `KeepAlive=true` + `RunAtLoad=true`、 script 内で `while true; sleep N; done` の rotation loop。 → applet プロセスが 1 個だけ常駐、 TCC prompt は起動時 1 回のみ。 script は `trap 'exit 0' TERM INT` で SIGTERM に clean 対応 (bootout で最終 rotation 途中でも安全 exit)。

⚠️ **再起動 / logout / `launchctl bootout` で prompt 復活** (新 process = 新 grant)。 起動時に 1 回押す運用で受容。 詳細と wallpaper 系の Tahoe API 全罠は [`macos-tahoe-wallpaper.md`](macos-tahoe-wallpaper.md) 参照。

---

## <a id="option-b-mirror"></a>Option B: CloudStorage 外に mirror する場合

`rsync` で local mirror を作り、 script は mirror を読む構成。 FDA 一切不要。

### mirror script `~/.local/bin/mirror-wallpaper-source.sh`:

```zsh
#!/bin/zsh
SRC="$HOME/Library/CloudStorage/Dropbox/<subpath>/"
DST="$HOME/Pictures/Wallpapers/"
mkdir -p "$DST"
rsync -a --delete "$SRC" "$DST"
```

launchd plist で 1 時間おき等の低頻度で `mirror-wallpaper-source.sh` を叩く (この launchd agent 自体は CloudStorage 読むので FDA or A' 必要)。 rotation script は `$DST` を読む (= 通常フォルダなので FDA 不要)。

CloudStorage 側の同期壊れても mirror 側は生き残る = 独立性 ◎。 disk 二重消費が唯一の trade-off。

---

## <a id="design-motivation"></a>設計動機

`~/Library/CloudStorage/` 配下は macOS Ventura 以降で FileProvider extension 経由の cloud storage の canonical 置き場になり、 macOS 15+ で TCC 保護がさらに厳格化された。 legacy な `~/Dropbox` symlink は削除される流れ、 script 側は CloudStorage path に対応する必要がある一方で、 permission model は launchd invoker の識別を厳しくしている = **script 一つ動かすのに TCC の考え方を理解しないと詰む**構造になった。

`/bin/zsh` への一律 FDA (= 昔の常套手段) は「zsh が動く場所すべて」 に FDA を配ることになり、 permission の意味的 hygiene として粗い。 `osacompile` wrapper + narrow FDA は「この用途のためのこの .app」 という **1:1 対応の permission holder** を作る pattern で、 security posture として素直、 System Settings の FDA panel を後日眺めた時の可読性も高い。

---

## 関連

- macOS post-update slowdown の総合 playbook: [`macos-post-update-slowdown.md`](macos-post-update-slowdown.md)
- Dropbox online-only placeholder の 0 byte 診断: [`dropbox-placeholder-diagnosis.md`](dropbox-placeholder-diagnosis.md)
- Claude Code の versioned path TCC 再 prompt (別型の TCC 問題): [`macos-claude-code-tcc-recurring-prompt.md`](macos-claude-code-tcc-recurring-prompt.md)
