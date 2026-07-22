<!-- doc-meta
when: macOS Tahoe (26.x) で wallpaper 変更を script/CLI/API から自動化しようとする前 + 起きてる wallpaper rotation が視覚的に効いてないと感じたとき
category: macos
summary: macOS Tahoe (26.5.1) で NSWorkspace.setDesktopImageURL と osascript "tell every desktop to set picture" が silent-fail する (rc=0 + Index.plist は更新するが display に届かない、 CocoaKit API 自体が dead)。 desktoppr / sindresorhus/wallpaper / Swift 直接 call も同一症状。 真の書換え path = ~/Library/Application Support/com.apple.wallpaper/Store/Index.plist を Python で再帰 walker により全 Desktop.Content.Choices 上書き (state は SystemDefault / Spaces × Displays / 個別 Displays の 8 箇所に分散、 1 箇所書きは respawn 時 self-repair)、 + killall -HUP cfprefsd + killall WallpaperAgent (SIGTERM) + killall Dock (SIGTERM) の triple kill、 + launchd は stay-open applet 常駐 (osacompile -s + on idle + KeepAlive=true / RunAtLoad=true / StartInterval なし、 applet binary 直接 exec) にして kTCCServiceSystemPolicyAppData の per-process 発火を 1 回のみに抑える (⚠️ 旧 v1 = 通常 applet の do shell script で script 内 sleep loop を永久 block する形は event loop に戻れず autorelease 非 drain で applet が ~120 MB/日 leak + 「応答なし」、 2026-07-22 実測で v2 に置換)。 CLI tools は現接続 NSScreen displayID を書くが Index.plist の stale UUID と mismatch = active display に効かない。 SIGKILL は /var/db/Wallpapers/<uuid>/Metadata.plist (root:wheel) から last-known-good 復元。 cache prune は 60s 間隔なら 100+ GB 肥大するので file-count cap で KEEP=1 に。 探索経路: notification-based reload や private XPC endpoint / debug listener enable / class-dump ImageFolder provider schema はすべて dead-end
-->

# macOS Tahoe (26.5.1) で wallpaper を CLI から変える技術 SoT

macOS 26 (Tahoe) で **wallpaper 変更を script / CLI / API から自動化する** ときの網羅ガイド。 2026-07-11 の半日探索で得た知見の SoT。 layer 3 の rotation 実装 (例: `wallpaper-rotation.md` 等) はこの SoT を参照して個別環境の paths だけ焼き込む形にする。

⚠️ **前提**: 本 doc の全知見は **macOS 26.5.1** での実測、 **26.5.2 (Build 25F84) でも 5 罠すべて同一挙動を再検証済** (2026-07-11、 osascript silent-fail 継続 / WallpaperImageExtension `CFBundleVersion=245.4.8` 変更なし / v1 常駐 recipe そのまま動作 〔※ 2026-07-22 に v1 の applet leak が判明、 §tahoe-app-data-per-process の v2 stay-open へ置換済〕)。 Apple は wallpaper subsystem を point release で touch していない = 完成 recipe は 26.5.x 系列で有効。 次 major update (27.x?) が出たら再検証すべき。

## <a id="tldr"></a>TL;DR

macOS 26 は wallpaper API を**完全に封じている**。 「動く」 recipe は 1 つだけ:

1. **`~/Library/Application Support/com.apple.wallpaper/Store/Index.plist`** の**全 8 箇所** の `Desktop.Content.Choices[0].Configuration` を **Python で再帰 walker** で target image を指す `imageFile` provider に上書き
2. **`killall -HUP cfprefsd`** + **`killall WallpaperAgent`** (SIGTERM) + **`killall Dock`** (SIGTERM) で強制 display refresh
3. **launchd 経路は stay-open applet 常駐** (`osacompile -s` + `on idle` + `KeepAlive=true` + `RunAtLoad=true`) で **kTCCServiceSystemPolicyAppData** の prompt を起動時 1 回に抑える (⚠️ 旧「do shell script で script 内 sleep loop を永久 block」 は applet leak、 §tahoe-app-data-per-process)

`osascript` / `desktoppr` / `sindresorhus/wallpaper` / **Swift の `NSWorkspace.setDesktopImageURL`** も**すべて silent-fail** する (rc=0 + Index.plist は更新するが display に届かない)。 これは CLI tool のバグでなく **Cocoa `setDesktopImageURL` API 自体が Tahoe で dead**。

---

## <a id="failed-approaches"></a>試して駄目な approaches (2026-07-11 半日探索の墓場)

| approach | 症状 | 判定 |
|---|---|---|
| `osascript -e 'tell app "System Events" to tell every desktop to set picture to ...'` | rc=0、 `defaults SystemWallpaperURL` は更新、 `get picture of every desktop` は指定値を返す、 でも **display 変わらず** | silent fail |
| `osascript -e 'tell app "Finder" to set desktop picture to POSIX file "..."'` | 同上 | silent fail |
| `desktoppr all <path>` (scriptingosx v0.5、 2024-07) | rc=0、 `Index.plist` の stale UUID (070FF924 等) には書くが **active display UUID には書かない**、 display 変わらず | 誤 target |
| `~/.local/bin/wallpaper set <path>` (sindresorhus/macos-wallpaper v2.3.4、 2026-04、 changelog に "Fix macOS 26" と明記) | 同上 (screens() の fix は入ってるが display 更新は同じく silent fail) | 誤 target |
| **Swift 自作**: `NSWorkspace.shared.setDesktopImageURL(url, for: NSScreen.main, options: [:])` (Cocoa 公式 API 直接) | エラー無しで返るが `desktopImageURL(for:)` が別の image を返す、 **display 変わらず** | Cocoa API 自体 dead |
| `defaults write com.apple.wallpaper SystemWallpaperURL "file://..."` | value は stuck するが display 変わらず | 効果無し |
| `killall -9 WallpaperAgent` (SIGKILL) + write + Dock kill | respawn 時に **`/var/db/Wallpapers/<uuid>/Metadata.plist` (root:wheel)** から last-known-good 復元 = write が revert | SIGTERM でないと駄目 |
| `SIGSTOP` で全 wallpaper 系プロセス凍結 + write + `SIGCONT` | `SIGCONT` で resume 直後に fs watcher が変更を検知して即 revert | 効果無し |
| **`ChoiceRequests.ImageFiles`** (WallpaperImageExtension.plist の history array、 実測 1960 entries) を空にする | display 変わらず、 revert source ではなかった | 誤診断 |
| `notifyutil -p com.apple.wallpaper.reload` (推測 name) 等 distributed notification | どの name も反応せず (WallpaperAgent の subscribe 一覧は非公開) | dead-end |
| `com.apple.wallpaper.debug.listener` XPC endpoint (WallpaperAgent binary strings に存在) | Apple internal build 前提、 pref key での有効化不明 | dead-end |
| **`/var/db/Wallpapers/<uuid>/Metadata.plist`** を直接 rewrite | root:wheel = sudo 必須 = 自動化 launchd context では通せない | dead-end |
| `class-dump` で **`com.apple.wallpaper.choice.image-folder` provider** の Configuration schema を reverse engineer (WallpaperAgent 内に定数として実在、 GUI 側の `AddPhotoButton` + `_showImageFolderPicker` も存在) | class-dump が CLT に無く追加 install 要、 進めても built-in shuffle interval は `12H/1D/2D/1W/1M/CONTINUOUSLY` (＋ dead code の `Every 5 Seconds Internal`) しか無く 60s rotation の user goal 未達 | scope 外 |
| System Settings → 壁紙 → Add Photos → folder shuffle UI | **Tahoe 26.5.1 で UI 削除済** (実装 binary には残ってるが到達 path 消失、 実測) | UI dead |
| System Settings → プライバシーとセキュリティ → アプリ管理 で **`WallpaperRotator.app` を「+」で追加** して toggle ON | prompt は毎 rotation で再発 (grant は毎回 Create event 記録されるが persist しない、 App Data protection が per-process semantic) | insufficient |
| launchd `StartInterval=60` で 60s ごと new process fork | **毎 fork で kTCCServiceSystemPolicyAppData の TCC prompt** 発火 = 60s ごと user が「許可」 押す羽目 | 常駐 applet に置換 |
| 通常 applet の `do shell script` で「script 内 sleep loop」 を永久 block 起動 (v1 常駐形) | TCC prompt は 1 回になるが **applet が ~120 MB/日 leak** (event loop に戻れず autorelease 非 drain、 実測 1.3 GB / 10.7 日) + 「応答なし」 | stay-open `on idle` に置換 (2026-07-22) |

**結論**: 上記全部が dead-end、 **Index.plist 再帰 walker + triple kill + stay-open applet 常駐 (launchd KeepAlive)** の組合せだけが動く。

---

## <a id="index-plist-structure"></a>Index.plist の state 8 箇所分散

`~/Library/Application Support/com.apple.wallpaper/Store/Index.plist` は binary plist で、 各 `Desktop.Content.Choices[0].Configuration` に **nested binary plist** (`{type: "imageFile", url: {relative: "file://<encoded>"}}`) が入る。 Tahoe では state が**以下の 8 (以上) 箇所に分散**:

```
.SystemDefault.Desktop.Content.Choices[0]                            # system default
.Spaces..Default.Desktop.Content.Choices[0]                          # 「default space」
.Spaces..Displays.<UUID>.Desktop.Content.Choices[0]                  # × 各 display
.Spaces.<space-uuid>.Default.Desktop.Content.Choices[0]              # × 各 Space (Mission Control)
.Spaces.<space-uuid>.Displays.<UUID>.Desktop.Content.Choices[0]      # × 各 Space × 各 Display
.Displays.<UUID>.Desktop.Content.Choices[0]                          # × 各 display (最上位)
```

**1 箇所だけ書くと WallpaperAgent respawn 時に別 location の値で self-repair される** (revert 現象)。 `Idle` (screensaver) は触らない (Desktop と分離管理)。

## <a id="stale-display-uuid"></a>stale display UUID mismatch = CLI tools が誤 target を狙う

Index.plist の `Displays` には**物理接続してない過去の display UUID も残ってる** (HDMI / 外付けを繋いだ履歴)。 一方 `NSWorkspace.setDesktopImageURL` / `NSScreen.screens` API は**現接続 screen 群の displayID** を返し、 これが Index.plist の UUID と mismatch する = **CLI tool (`wallpaper`, `desktoppr`) は stale UUID の枠に書いて active display の枠は触らない**、 実 display には届かない致命的 bug。

**回避策**: **UUID 非依存の再帰 walker** で Index.plist tree 全体を巡り、 全 `Desktop.Content.Choices` を上書きする (下記 recipe)。 現在アクティブな UUID を identify する必要無し。

## <a id="var-db-wallpapers"></a>system-level cache `/var/db/Wallpapers/<uuid>/`

`/var/db/Wallpapers/<user-uuid>/` (root:wheel) に **`Metadata.plist` + rendered `Wallpaper.png`** が保存されている。 これは System Settings が privileged XPC 経由で書く「真の SoT」 で、 sudo 無しには書き換え不能。

**SIGKILL `WallpaperAgent` の revert 挙動の source** は多分ここで、 crash 扱いで再起動された Agent はこの Metadata.plist から復元する。 SIGTERM (graceful shutdown) だと復元パスを通らないっぽい (実測)。

---

## <a id="tahoe-full-write"></a>完成 recipe (1): Index.plist 全 Desktop write

`Idle` は触らず `Desktop.Content.Choices` のみ再帰置換:

```python
#!/usr/bin/env python3
import plistlib, urllib.parse, sys

target, index_path = sys.argv[1], sys.argv[2]
enc = urllib.parse.quote(target, safe='/')
inner_bytes = plistlib.dumps(
    {"type": "imageFile", "url": {"relative": f"file://{enc}"}},
    fmt=plistlib.FMT_BINARY,
)
new_choice = {
    'Configuration': inner_bytes,
    'Files': [],
    'Provider': 'com.apple.wallpaper.choice.image',
}

def rewrite_desktop(obj):
    n = 0
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if k == 'Desktop' and isinstance(v, dict) and 'Content' in v and isinstance(v['Content'], dict):
                if 'Choices' in v['Content']:
                    v['Content']['Choices'] = [new_choice]
                    n += 1
            n += rewrite_desktop(v)
    elif isinstance(obj, list):
        for v in obj:
            n += rewrite_desktop(v)
    return n

with open(index_path, 'rb') as f: d = plistlib.load(f)
n = rewrite_desktop(d)
with open(index_path, 'wb') as f: plistlib.dump(d, f, fmt=plistlib.FMT_BINARY)
sys.exit(0 if n > 0 else 1)
```

呼び出し例:

```bash
python3 rewrite.py "$TARGET_IMAGE" "$HOME/Library/Application Support/com.apple.wallpaper/Store/Index.plist"
```

**verification** (8 箇所全部が同一 URL に更新されたか):

```bash
python3 <<'PY'
import plistlib
from collections import Counter
d = plistlib.load(open('/Users/<you>/Library/Application Support/com.apple.wallpaper/Store/Index.plist', 'rb'))
def urls(o):
    r = []
    if isinstance(o, dict):
        for v in o.values(): r += urls(v)
    elif isinstance(o, list):
        for v in o: r += urls(v)
    elif isinstance(o, bytes):
        try: r += urls(plistlib.loads(o))
        except: pass
    elif isinstance(o, str) and 'file://' in o:
        r.append(o[-40:])
    return r
print(Counter(urls(d)).most_common(3))  # top 1 が (url, 8) なら成功
PY
```

## <a id="tahoe-refresh-sigterm"></a>完成 recipe (2): display refresh triple kill

Index.plist write 直後に:

```bash
/usr/bin/killall -HUP cfprefsd 2>/dev/null   # defaults cache 無効化
/usr/bin/killall WallpaperAgent 2>/dev/null  # SIGTERM (default) — graceful shutdown で新 plist 読込
/usr/bin/killall Dock 2>/dev/null            # SIGTERM — wallpaper composite 層再構築
```

⚠️ **`-9` (SIGKILL) を使わない**: `/var/db/Wallpapers/<uuid>/Metadata.plist` から last-known-good 復元されて write が revert する。 SIGTERM で graceful shutdown させれば復元 path を通らない (実測)。

⚠️ **副作用**: Dock が **1-2 秒消えて再表示** される。 60s rotation なら毎分 Dock フラッシュ。

## <a id="tahoe-app-data-per-process"></a>完成 recipe (3): stay-open applet 常駐で TCC prompt を 1 回に

Tahoe 26 で `~/Library/Application Support/com.apple.wallpaper/Store/Index.plist` への書込みは **`kTCCServiceSystemPolicyAppData`** (アプリ管理 / 他アプリのデータへのアクセス権) の TCC prompt を発火する。 System Settings → プライバシーとセキュリティ → アプリ管理 で該当 app を明示 grant しても **grant が persist しない** (TCC log で `AUTHREQ_PROMPTING` → `Create` event が毎回発行される、 実測)。

**hypothesized 原因**: Tahoe が `kTCCServiceSystemPolicyAppData` を **1 process 1 grant** の semantic に変更した (session 限定 grant)。 launchd `StartInterval=60` で毎回 new process を fork すると新規 grant が要求される。

**回避策 (実測有効)**: applet を **常駐** させる = `StartInterval` 削除 + `KeepAlive=true` + `RunAtLoad=true`。 → **1 プロセスが常駐**、 TCC prompt は起動時 1 回のみ、 user が「許可」 1 回押せば以後静か。 子プロセスは毎 cycle fresh でも parent (applet) の grant を継承する (実測: python3 が毎 cycle fresh spawn で Index.plist を書けている)。

⚠️ **常駐のさせ方に罠 (2026-07-22 実測)**: v1 recipe (= 通常 applet が `do shell script` で「script 内 `while true; sleep N` loop」 を**永久 block 起動**する形) は **applet が ~120 MB/日 leak する** (実測 1.3 GB / 10.7 日、 26.5.2)。 機構 = `do shell script` の待機中 AppleScript runtime は内部 poll loop を回すが **event loop に一度も戻らないため autorelease pool が drain されない** (footprint 内訳 = MALLOC_SMALL dirty : untagged VM_ALLOCATE ≈ 3:1 = 小 object + pool page の署名)。 Activity Monitor で「応答なし」 表示になるのも同根 (= event 処理ゼロ)。 → **v2 recipe (下記、 stay-open applet + `on idle`) を使う**: 毎 idle で 1 回分 rotation だけ `do shell script` し、 idle 間で event loop に戻る = autorelease が毎周期 drain、 「応答なし」 も消える。 applet process は同一のまま常駐なので per-process grant は維持される。

**applet source (stay-open、 v2)**:

```applescript
on idle
	try
		do shell script "$HOME/.local/bin/rotate-wallpaper.sh --once"
	end try
	set iv to 60
	try
		set envval to system attribute "WALLPAPER_INTERVAL"
		if envval is not "" then
			set n to envval as integer
			if n >= 10 then set iv to n
		end if
	end try
	return iv
end idle
```

⚠️ `system attribute` の unset env は `""` を返し、 **AppleScript の `"" as integer` は error でなく `0` に化ける** (実測)。 「coerce → 下限 clamp」 の素朴な書き方だと unset 時に clamp 値 (例 10 秒) が interval になる — 空文字を明示 check してから coerce する (上記形)。

```bash
osacompile -s -o ~/Applications/WallpaperRotator.app rotator.applescript   # -s = stay-open
plutil -replace CFBundleIdentifier -string com.example.WallpaperRotator \
  ~/Applications/WallpaperRotator.app/Contents/Info.plist
plutil -replace LSUIElement -bool true \
  ~/Applications/WallpaperRotator.app/Contents/Info.plist                  # Dock icon 非表示
codesign -f -s - ~/Applications/WallpaperRotator.app                       # Info.plist 編集後に ad-hoc 再署名
```

**launchd plist template (applet binary 直接 exec)**:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.example.wallpaper-rotate</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/<you>/Applications/WallpaperRotator.app/Contents/MacOS/applet</string>
  </array>
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
  <!-- StartInterval は無し。 周期は applet の on idle が持つ -->
  <key>StandardErrorPath</key><string>/tmp/wallpaper-rotate.err</string>
</dict>
</plist>
```

⚠️ `open -g -a` 間接起動 + `KeepAlive` の組合せは使わない: `open` が即 exit するため launchd は app 本体を追跡できず、 KeepAlive が `open` の respawn loop に化ける (v1 の残骸 pattern)。 applet binary 直接 exec なら KeepAlive が applet 自体に効く (= crash 時自動再起動)。

**shell script 側**: rotation 1 回分を `--once` として切り出す (loop も sleep も持たない)。 §tahoe-full-write の Python 書換え + §tahoe-refresh-sigterm の triple kill + §cache prune を 1 pass 実行して exit。

**trade-off**:
- ○ TCC prompt 1 回 (user が 1 回「許可」 で以後 grant 保持)
- ○ 60s rotation 維持 (周期は applet の `return` 値、 `WALLPAPER_INTERVAL` env で override)
- ○ applet 常駐 RSS ~100 MB (AppKit 分) で **flat** (v1 は単調増加)
- × **再起動 / logout / `launchctl bootout` で prompt 復活** (新 process = 新 grant、 起動時に 1 回押す)
- × `launchctl kickstart -k` (再起動と等価) も同様

**併用推奨**: System Settings → プライバシーとセキュリティ → **アプリ管理** に該当 app を「+」 で追加して toggle ON (これだけでは insufficient、 常駐化と併用が本命)。

**rebuild と TCC grant (2026-07-22 実測)**: applet を osacompile で作り直しても (= ad-hoc 再署名で cdhash が変わっても)、 **bundle ID + 絶対 path が同一なら FDA / アプリ管理の既存 grant はそのまま効く** (re-toggle 不要だった)。 rebuild 後の初回起動も新 process なので App Data prompt は 1 回想定 (実測では prompt 無しで書けたケースあり = 直前 grant の残存と推定、 出たら 1 回押す)。

---

## <a id="wallpaper-cache-bloat-extension"></a>cache 肥大は静止画 rotation でも起きる (既知 bug の拡張)

layer 1 [`macos-post-update-slowdown.md#wallpaper-cache-bloat`](macos-post-update-slowdown.md#wallpaper-cache-bloat) は動画壁紙が `~/Library/Containers/com.apple.wallpaper.agent/Data/Library/Caches` を 100 GB+ に育てる既知 bug を記述しているが、 **静止画 rotation でも同型で肥大する** (実測 2026-07-11: 60秒間隔 rotation を 3 日間放置で 21 GB / 1,556 file)。

WallpaperImageExtension は set された画像を **非圧縮 bmp (3456×2234、 ~13 MB/枚)** に decode して `com.apple.wallpaper.caches/extension-com.apple.wallpaper.extension.image/` に生成し **GC しない**。

**対策** (rotation script 末尾で file-count cap prune):

```zsh
CACHE="$HOME/Library/Containers/com.apple.wallpaper.agent/Data/Library/Caches/com.apple.wallpaper.caches/extension-com.apple.wallpaper.extension.image"
KEEP=1  # content-addressable ゆえ hit rate ほぼ 0、 現行 1 枚だけあれば足りる
if [[ -d "$CACHE" ]]; then
  bmps=($CACHE/*.bmp(N))  # zsh (N) = nullglob
  if (( ${#bmps} > KEEP )); then
    /bin/ls -1t "${bmps[@]}" | /usr/bin/tail -n +$((KEEP+1)) | while IFS= read -r f; do
      /bin/rm -f "$f"
    done
  fi
fi
```

**ceiling**: `KEEP × ~13 MB` (KEEP=1 なら ~13 MB)。 interval 非依存。

⚠️ `KEEP=0` (全消し) も動くが、 osascript 完了と async cache write の race で「今書かれた bmp」 を巻き添えする余地あるので safety margin として 1 を残す。

---

## <a id="aerial-disable"></a>Aerial extension を disable (副次的軽量化)

自作 rotation が静止画のみ使うなら `WallpaperAerialsExtension.appex` (Aerial 動画壁紙 backend) は不要:

```bash
pluginkit -e ignore -i com.apple.wallpaper.extension.aerials

# verify (行頭 '-' が ignored marker)
pluginkit -mAvvv 2>/dev/null | grep -B1 "com.apple.wallpaper.extension.aerials" | head -4
```

⚠️ appex process 自体は system が spawn するので `killall WallpaperAerialsExtension` 後も 20 MB 程度 resident する可能性 (0% CPU なので実質無害)。 `pluginkit -e ignore` は「wallpaper 選択 UI に表示しない」 相当で activation を止めるだけ。

**revert**: `pluginkit -e use -i com.apple.wallpaper.extension.aerials`。

---

## <a id="debugging-methodology"></a>デバッグ方法論 (関連する探索テクニック)

Tahoe の wallpaper API 侵入で使った手法、 他の macOS TCC / cache 問題にも転用可:

### 1. mtime tracking で revert 犯人特定

「A 書いた → kill → 別 file に revert される」 時、 revert の write は「殺してないどこかのプロセス」 が触ってる。

```bash
touch /tmp/before
# ... 操作 ...
touch /tmp/after
find <対象 dir> -type f -newer /tmp/before ! -newer /tmp/after
# = kill 後の write source を特定
```

### 2. TCC log 直読で prompt / grant 発火追跡

```bash
/usr/bin/log show --predicate 'subsystem == "com.apple.TCC"' --last 5m 2>&1 \
  | grep -E "AUTHREQ_PROMPTING|Publishing.*Create|Publishing.*Delete" \
  | grep <bundle-id or app-name>
```

- `AUTHREQ_PROMPTING` = 実 dialog 表示
- `Publishing Create event` = user 「許可」 で grant 記録
- `Publishing Delete event` = grant 削除
- 3 者を時系列で並べて grant 生存期間を測る

### 3. `strings` で private API name 探索

```bash
strings /System/Library/PrivateFrameworks/<Framework>.framework/<Binary> \
  | grep -iE "notification|reload|refresh|<keyword>"
```

または `WallpaperKit` のように shared cache に住む framework は fs 上 file 実体無しなので、 **同 subsystem の実行体** (`WallpaperAgent.app`, `Wallpaper*Extension.appex`) の binary を strings する。

### 4. `pluginkit -mAvvv` で extension list dump

Wallpaper.appex の内部 `com.apple.wallpaper.choice.*` provider 列挙、 `AddPhotoButton` 系の実装存在確認等。

### 5. Index.plist 全 leaf 再帰 dump で state 全 location 洗い出し

```python
def walk(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items(): yield from walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj): yield from walk(v, f"{path}[{i}]")
    elif isinstance(obj, bytes):
        try: yield from walk(plistlib.loads(obj), f"{path}<inner>")
        except: pass
    else: yield (path, obj)
```

nested binary plist (bytes) も展開する再帰 = state 分散箇所を漏れなく列挙。

### 6. `sqlite3 ~/Library/Application Support/com.apple.TCC/TCC.db`

**開けない** (SIP 保護、 authorization denied)。 grant 状態確認は System Settings GUI + log show の 2 経路のみ。 覚えとくと 5 分節約。

---

## 関連

- [`launchd-cloudstorage-tcc.md`](launchd-cloudstorage-tcc.md) — launchd + CloudStorage の A' pattern (narrow FDA)、 本 doc の rotation script はこの pattern の instance
- [`macos-post-update-slowdown.md`](macos-post-update-slowdown.md) `#wallpaper-cache-bloat` — 動画壁紙 cache bloat の元 SoT (本 doc の [§wallpaper-cache-bloat-extension](#wallpaper-cache-bloat-extension) で静止画 rotation にも拡張)
- [`hook-authoring.md`](hook-authoring.md) — hook 経路の TCC 挙動と 3 軸配信 audit
