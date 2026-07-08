# macOS post-update slowdown: 診断 + 撃退 playbook

macOS のメジャー / マイナー update 直後 (= 特に Sonoma → Tahoe のような bundle 一新のケース) に体感が「バカみたいに重い」 状態に陥ることが繰り返し起きる。 background daemon の再構築 / index 再生成 / cache 再肥大 / login item 復活 / AI 系 subsystem 有効化 / 削除アプリの launch plist 残置 等の要因が**同時多発**するため、 「主犯 1 匹」 でなく「疑わしい 5-10 匹を順に絞る」 playbook が必要。

本 doc は現場で使える診断 + 撃退手順を top-down で記す。 「まず 24-48h 待つ」「index 再構築中は仕方ない」 のような**正常な忙しさ**と、 「Apple Intelligence が respawn する `suggestd` が 100% CPU」 のような**病的な忙しさ**の切り分けが要点。

---

## <a id="first-wait"></a>まず 24-48h 待つ (正常な post-update ロード)

update 直後は以下が同時に走る、 これは正常:

- `mds_stores` / `mdworker` (Spotlight 再 index)
- `photoanalysisd` (写真 App の顔認識 / シーン解析 再実行)
- `cloudd` / `bird` (iCloud 全 sync 再確認)
- `backupd` (Time Machine 初回 post-update backup)
- `mediaanalysisd` (Music / Photos の再解析)
- `softwareupdated` (ポイントリリースの追加 DL)

これらは殺しても respawn する = **待つのが正解**。 Activity Monitor の CPU タブで上位に居ても、 24-48h で自然に沈静化する。

「まだ重いか?」 は `uptime` の load average が `[CPU core 数]` を下回るまで待つのが目安 (= M シリーズなら `sysctl -n hw.ncpu` で確認、 典型 8-10 core)。

---

## <a id="diagnostic-sequence"></a>Diagnostic sequence (最初の 30 秒で回す)

```bash
uptime                                    # load average
df -h /System/Volumes/Data | tail -1      # disk (85% 超は APFS thrashing)
sysctl vm.swapusage                       # swap 頻発なら memory 逼迫
memory_pressure 2>&1 | head -8            # pages free / 圧縮量
ps -Ao pcpu,pmem,rss,comm | sort -rn | head -12  # top offenders
```

観測ポイント:

- **load average >> CPU core 数** → 何か暴走中
- **disk 85%+** → APFS 自体が遅くなる (= 消せる物を消せば緩和、 [§disk-cleanup](#disk-cleanup))
- **swap 数 GB 使用** → memory 逼迫、 常駐アプリを削るのが根治
- **pages free < 数百** かつ compressor 数 GB → 深刻な memory 圧、 SSD 寿命にも効く
- **top CPU に見慣れないやつ** → 下記 §病的パターン と照合

---

## <a id="corespotlightd-not-in-mdutil"></a>`mdutil -a -i off` は `corespotlightd` を止めない

Spotlight 停止を目的に `sudo mdutil -a -i off` を実行しても **`corespotlightd` は別 daemon** として動き続ける。 `mdutil` が制御するのは **volume ごとの metadata index (`mds` / `mds_stores`)** であって、 `corespotlightd` (= 検索 suggestion + system-wide search index) は別軸で launchd に管理される。

観測される症状: `mdutil -a -s` で `Indexing disabled` なのに `ps` で `corespotlightd` が数十 %+ CPU を食う。

### 完全停止したい場合

```bash
sudo launchctl disable system/com.apple.corespotlightd
sudo killall corespotlightd
```

⚠️ `launchctl disable` を打っても、 **上位 preference (= Spotlight / Siri Suggestions 設定) が ON のままだと macOS が respawn する** ([§suggestd-respawn](#suggestd-respawn) と同じ機構)。 GUI 側:

- **System Settings → Spotlight → 検索結果**: すべての「Siri 提案」 系チェック OFF
- **System Settings → Spotlight → 関連コンテンツを表示**: OFF

### `.metadata_never_index` per-directory 除外

GUI の privacy list に載せる代わりに、 対象ディレクトリ直下に空 file `.metadata_never_index` を置くと Spotlight が index skip する。 sudo 不要、 移動追従、 GUI list と併用可 (= 二重防御は害無し):

```bash
touch ~/Library/.metadata_never_index
touch ~/Documents/GitHub/.metadata_never_index
touch /opt/homebrew/.metadata_never_index
```

Homebrew / node_modules / git repo / Xcode DerivedData 等の重い場所には最初から仕込むと index 再構築コストが小さくなる。

---

## <a id="suggestd-respawn"></a>Apple Intelligence が `suggestd` を XPC 経由で respawn する

macOS 15+ (特に Tahoe) で最も厄介な CPU 消費源が `suggestd` (= CoreSuggestions daemon、 Siri / Apple Intelligence の提案 backend)。 100% CPU に張り付きやすい。

`launchctl disable gui/<UID>/com.apple.suggestd` で disabled リスト入りしても、 **Apple Intelligence backend が XPC でサービス要求すると launchd は respawn を強制する** (= `launchctl` の disable より上位の preference が勝つ)。 `kill -9` しても数秒で復活する。

### 唯一の根治: GUI で Apple Intelligence + Siri Suggestions を OFF

**System Settings → Apple Intelligence と Siri**:

- 最上部の **Apple Intelligence トグル OFF** (Tahoe で最重要、 これが respawn 源)
- **Siri トグル OFF**

**System Settings → プライバシーとセキュリティ → 解析と改善**:

- 「Siri と辞書入力を改善」 OFF
- 「Apple Intelligence レポートを共有」 OFF

これで `suggestd` の respawn が止まる (= XPC 要求元が消える)、 `launchctl disable` の効果が初めて発現する。

### SIP に注意

`sudo launchctl bootout` は SIP 保護 daemon に対しては `Operation not permitted while System Integrity Protection is engaged` (errno 150) を返す。 `disable` + `signal kill` が SIP 越しでも通る唯一の userland ルート。

---

## <a id="wallpaper-cache-bloat"></a>動画壁紙が `WallpaperImageExtension` を常時 30-50% CPU で回す + cache が 100 GB+ に育つ

macOS Sonoma+ の Aerial 系動画壁紙 (= 4K 240fps `.mov` を desktop background として再生する機能) には次の**既知バグ**:

1. **`WallpaperImageExtension.appex` が動画を常時デコード → 30-50% CPU を張り付く**
2. **`~/Library/Containers/com.apple.wallpaper.agent/Data/Library/Caches` が延々肥大する** (= 過去に選んだ動画壁紙が GC されず溜まる、 100 GB 超え事例あり)

### 診断

```bash
du -sh ~/Library/Containers/com.apple.wallpaper.agent/Data/Library/Caches
defaults read com.apple.wallpaper SystemWallpaperURL
ps -Ao pcpu,rss,comm | grep -i wallpaper | grep -v grep
```

`SystemWallpaperURL` が `.mov` を指していれば動画壁紙、 cache が数十 GB あれば bloat 発生中。

### 対処

**cache 撲滅** (= sandbox container 内なので sudo 不要):

```bash
rm -rf ~/Library/Containers/com.apple.wallpaper.agent/Data/Library/Caches
rm -rf ~/Library/Containers/com.apple.wallpaper.extension.image/Data/Library/Caches
rm -rf ~/Library/Application\ Support/com.apple.wallpaper
```

**動画壁紙 → 静止画切替** (= 再発防止):

- System Settings → 壁紙 → 一番下の「カラー」 (= ▶️ アイコン無しの単色) をクリック
- or 自分の写真 (静止画 JPG/PNG/HEIC)
- ▶️ アイコンがある候補 (= Aerial / Mac (色) / 空撮をシャッフル 等) は**全部動画**、 選ぶと再発

⚠️ 静止画に切替後も、 System Settings の壁紙パネルが loading spinner で止まる場合がある (= wallpaper agent の state 破損)。 復旧:

```bash
killall WallpaperAgent Dock 2>/dev/null
```

or CLI で強制設定 (= GUI がフリーズしても動く):

```bash
defaults write com.apple.wallpaper SystemWallpaperURL -string \
  "file:///System/Library/Desktop%20Pictures/Solid%20Colors/Black.png"
killall WallpaperAgent Dock
```

---

## <a id="softwareupdated-background-dl"></a>`softwareupdated` が背景で 2-4 GB を DL 中

「再起動したら急に重くなった」 の典型原因。 再起動が引き金で macOS 自体が **次のポイントリリースの自動 DL** を開始する (= 2-4 GB、 数十分〜数時間 CPU 消費)。

### 確認

```bash
ps -Ao pcpu,comm | grep softwareupdated
softwareupdate --list                     # 何を DL 中か
```

### 一時停止 (= 週末の手動 update に回す運用)

**System Settings → 一般 → ソフトウェア・アップデート → ⓘ (自動アップデート横) → 「新しいアップデートがあるときにダウンロード」 OFF**

これで `softwareupdated` の background 活動が止まる。 手動当てるときだけ ON に戻す。

### 運用原則

- `.0` / `.1` メジャー版直後は **`.2` 出るまで待つ** (= Sonoma → Tahoe 直後の 26.5.0/26.5.1 は問題多い、 26.5.2/26.5.3 で当てる)
- update 前後は disk **30% 以上空ける** (= .ipsw + swap + snapshot で意外に食う)

---

## <a id="wallpaperextension-avg-residue"></a>3rd-party AV アンインストール後の launch plist 残置

AVG / Avast / Norton / Sophos 等をアンインストールしても、 **`/Library/LaunchDaemons/` `/Library/LaunchAgents/` に launch plist が残置される**ケースが多発する。 残置 plist は再起動のたびに helper process を起動しようとして `opendirectoryd` を叩き続ける (= 40%+ CPU の主因になり得る)。

### 検出

```bash
find /Library/LaunchDaemons /Library/LaunchAgents -maxdepth 1 -iname "*avg*" -o -iname "*avast*" -o -iname "*norton*" -o -iname "*sophos*" 2>/dev/null
find /Library/Application\ Support -maxdepth 1 -iname "*avg*" -o -iname "*avast*" 2>/dev/null
```

### 撃退

```bash
sudo launchctl bootout system/com.avg.hub.xpc 2>/dev/null
sudo launchctl bootout system/com.avg.hub.schedule 2>/dev/null
sudo rm -f /Library/LaunchAgents/com.avg.hub.plist
sudo rm -f /Library/LaunchDaemons/com.avg.hub.xpc.plist
sudo rm -f /Library/LaunchDaemons/com.avg.hub.schedule.plist
sudo rm -rf /Library/Application\ Support/AVGHUB
```

(AVG 以外は plist 名を該当 vendor に読み替え)

### そもそも 3rd-party AV は要る?

macOS 15+ は XProtect + Gatekeeper + Notarization + endpointsecurityd の built-in 防御があり、 **通常 user では 3rd-party AV は害の方が大きい** (= 全 file IO を hook する分の重さ、 誤検出、 update loop、 uninstall 残置)。 特別な理由 (= 企業 policy / compliance) が無ければ**アンインストール推奨**。

---

## <a id="apptranslocation-zombie-plist"></a>`AppTranslocation/` を指す zombie LaunchAgent

未署名 or quarantined な `.app` を **Applications フォルダに移さず** 一度でも double-click で起動すると、 macOS は `/private/var/folders/.../T/AppTranslocation/<UUID>/d/<app>.app` に一時 copy を作って隔離実行する (= App Translocation 機能)。 起動時に user LaunchAgent を登録する類のアプリ (= Baidu Netdisk 等) は、 この**一時 path を指す plist** を `~/Library/LaunchAgents/` に書き込む。

**再起動後 tmp が消えても plist は残る** = 存在しない path を指す zombie LaunchAgent が毎起動で失敗し続ける。

### 検出

```bash
grep -rE "AppTranslocation|/private/var/folders" ~/Library/LaunchAgents 2>/dev/null
```

### 撃退

```bash
launchctl unload ~/Library/LaunchAgents/<zombie>.plist 2>/dev/null
rm ~/Library/LaunchAgents/<zombie>.plist
```

user LaunchAgent なので sudo 不要。

---

## <a id="containermanagerd-protected-residue"></a>`~/Library/Containers/*` は sudo でも消せない (macOS 15+)

macOS 15+ で `containermanagerd` が sandbox container 全体を保護するようになった。 sandbox app をアンインストールしても **container が残る**、 `sudo rm -rf` しても `.com.apple.containermanagerd.metadata.plist: Operation not permitted` で拒否される。

### 部分回収 (= 中身データだけ削除、 metadata shell は残す)

```bash
sudo find ~/Library/Containers/com.<vendor>.* -type f \
  ! -name ".com.apple.containermanagerd.metadata.plist" -delete
```

これで **container 内の実データ (= 数百 MB あることも) は回収できる**、 metadata shell (~数十 KB / 個) だけ残る。 shell は auto-launch 元にならないので無害。

### 完全削除

recovery mode で SIP を切って `~/Library/Containers/` を消す以外に user-land ルートは無い (= 事実上、 諦めるのが実用解)。

### App Store 経由 install の `.app` は `/Applications` からも消えない

WeChat 等の App Store install app は `/Applications/` からの `sudo rm` が拒否される場合がある。 **Finder で右クリック → 「ゴミ箱に入れる」** が最短ルート (= LaunchServices 経由の App Store 認識 uninstall が走る)。

---

## <a id="disk-cleanup"></a>Disk cleanup targets (優先度順)

disk 85% 超えると APFS 自体が遅くなる = disk 掃除は CPU 対策と同じくらい効く。 常設 target list:

### 大物 (数 GB〜数十 GB)

1. **動画壁紙 cache**: `~/Library/Containers/com.apple.wallpaper.agent/Data/Library/Caches` — [§wallpaper-cache-bloat](#wallpaper-cache-bloat) 参照、 100 GB 超え事例あり
2. **`~/Downloads/*.dmg`**: install 済み App の installer DMG は全部ゴミ、 200 MB / 個 × 十数個で 数 GB
3. **`~/Documents/Zoom/`**: Zoom cloud 録画のローカル copy、 講義録画で 10 GB 超えやすい
4. **不使用 browser の Application Support**: `~/Library/Application Support/{Google,Vivaldi,Firefox}` — Brave 一本に絞ってるなら数 GB
5. **`~/Library/Application Support/Slack`**: workspace cache、 1 GB+
6. **CoreSimulator Devices**: `~/Library/Developer/CoreSimulator/Devices/` — iOS Simulator 、 使ってないなら Xcode 環境設定で削除 or 手動 rm、 数 GB
7. **`/Library/Application Support/com.apple.idleassetsd/Customer/`**: Aerial 動画壁紙の system 側 cache、 現壁紙分だけ残る (SIP 保護、 除去は sudo 必要)

### 中物 (数百 MB〜数 GB)

- `~/Library/Caches/{Homebrew,BraveSoftware,Google,Vivaldi,pip,ms-playwright}`: **注意** — 動作中のアプリの Cache を削るのは避ける (= Brave 動いてる時に BraveSoftware 削らない)
- `~/Library/Caches/com.apple.python`
- `~/Library/Group Containers/*/{LINE,Office,Podcasts}`

### 掃除コマンド定形

```bash
brew cleanup -s                                # Homebrew 全 tap + old bottle
python3 -m pip cache purge                     # pip
rm -rf ~/.Trash/* ~/.Trash/.[!.]*             # ゴミ箱空
```

### snapshot 確認

「消したのに空きが増えない」 と感じたら Time Machine local snapshot を疑う:

```bash
tmutil listlocalsnapshots /
sudo tmutil deletelocalsnapshots <YYYY-MM-DD-HHMMSS>
```

---

## <a id="reboot-commit-point"></a>再起動が「変更の commit point」

上記の `launchctl disable` / plist 削除 / cache 削除 の効果は**再起動後に本格的に反映**される (= 動いていた daemon が停止した状態で新規起動する)。 一連の対処後、 **login items から不要 App の「開いた時に開く」 と「再ログイン時にウインドウを再度開く」 を OFF にしてから再起動**するのが最も clean な commit。

### 再起動時に必ず確認

**System Settings → 一般 → ログイン項目とバックグラウンド機能拡張**:

- 「開いた時に開く」 に不要 App (= Zoom / Slack / Discord 等) が居ないか
- 「バックグラウンドで許可」 の 3rd-party を吟味 (= 使わないなら OFF)
- **再ログイン時のウインドウ復元をオフに**

これをやらないと消したはずの重い App が全部復活する = 「再起動しても重い」 の 8 割はこれ。

---

## 関連

- 動的 launchd + `~/Library/CloudStorage/` の TCC 越え pattern: [`launchd-cloudstorage-tcc.md`](launchd-cloudstorage-tcc.md)
- Dropbox online-only placeholder の 0 byte 診断: [`dropbox-placeholder-diagnosis.md`](dropbox-placeholder-diagnosis.md)
- Homebrew install 失敗の記録運用: [`install-failures.md`](install-failures.md)
