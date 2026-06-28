# Android Chromium 系 (Brave / Chrome) の remote debugging

Android phone 上の Brave / Chrome で動いている web app の **生 state を、 reload なしで Mac から取得する** 手順。 mobile-only bug (= overnight runaway / background suspend / 等) の RCA で「タブを reload せずに state を吸い出したい」 class の問題で必須。

由来: 2026-05-06、 LorentzArena Bug 14 (= スマホ Brave で 8 時間 background 後に物理 state が runaway) の live state を capture するため確立、 universal applicable な手順として外出し。

---

## <a id="route-selection"></a>§1 経路選択: USB ADB vs WiFi ADB

**WiFi ADB を first-line 推奨**。 USB ADB は cable / port の data 通信疎通確認が必要で詰まりがち、 「Anker 等 high-quality cable でも data 非対応 model がある」 「MacBook の USB-C port が data 通すかは port 別」 等で時間溶ける。 WiFi ADB は Android 11+ なら ケーブル不要で 5 分で確立。

**USB ADB が要件**: WiFi 切断耐性が必要 (= 例: 切断テスト中に debug 維持) や Android 10 以下のみ。

**事前判定**: Android version が 11 以上か確認 (= `設定 → デバイス情報 → Android バージョン`)。 11+ なら WiFi 経路。

## <a id="wifi-adb-setup"></a>§2 WiFi ADB セットアップ

### <a id="wifi-adb-phone"></a>§2.1 スマホ側

1. **開発者モード有効化** (= 既に ON なら skip):
   - 設定 → デバイス情報 → 「ビルド番号」 を 7 回 tap
2. **ワイヤレスデバッグ ON**:
   - 設定 → システム → 開発者向けオプション → 「ワイヤレスデバッグ」 toggle ON
   - dialog 「許可」
3. **ペア設定コード生成**:
   - 「ワイヤレスデバッグ」 の文字 (= toggle ではなく行) を tap → 詳細画面
   - 「**ペア設定コードによるデバイスのペア設定**」 tap
   - 画面に **6 桁数字** + **IP:port** (例: `<RFC1918-IP>:<random-pair-port>` 形式、 RFC1918 は `192.168.x.x` / `10.x.x.x` / `172.16-31.x.x` のいずれか) 表示、 **画面を閉じない**

### <a id="wifi-adb-mac"></a>§2.2 Mac 側

```bash
# adb がなければ install (= homebrew)
brew install --cask android-platform-tools

# pair (= スマホ画面の 6 桁コード + IP:port を使う)
echo "<6-digit-code>" | adb pair <ip>:<pair-port>
# → "Successfully paired to <ip>:<pair-port> [guid=...]"

# connect (= ペア完了後、 同画面の上部に表示される別 port を使う、 通常 5555 or random)
adb connect <ip>:<connect-port>
# → "connected to <ip>:<connect-port>"

# 確認
adb devices -l
# → "<RFC1918-IP>:<connect-port>  device product:..."
```

### <a id="wifi-adb-same-network"></a>§2.3 同 WiFi 必須

スマホとこの Mac が **同じ WiFi network** に接続している必要あり。 違うなら片方を合わせる。

---

## <a id="cdp-connection"></a>§3 Chromium DevTools Protocol (CDP) 接続

### <a id="cdp-socket-forward"></a>§3.1 socket 確認 + port forward

```bash
# Brave / Chrome の devtools_remote socket を確認
adb -s <ip>:<connect-port> shell cat /proc/net/unix | grep devtools

# 通常見える: "@chrome_devtools_remote" (= Brave / Chrome / Edge 共通名)
# (注: socket は abstract namespace、 "@" prefix が abstract socket)

# Mac の localhost:9222 に forward
adb -s <ip>:<connect-port> forward tcp:9222 localabstract:chrome_devtools_remote

# 動作確認
curl -s http://localhost:9222/json/version
# → JSON return、 "Android-Package": "com.brave.browser" 等
```

### <a id="cdp-tab-search"></a>§3.2 LorentzArena タブ等の検索

```bash
# 全 tab list (= 各 tab の WebSocket debug URL 含む)
curl -s http://localhost:9222/json
# → array、 各 entry に "title" / "url" / "id" / "webSocketDebuggerUrl"

# 特定 tab を絞り込み (= python で URL 含む tab を pick)
curl -s http://localhost:9222/json | python3 -c "
import json, sys
tabs = json.load(sys.stdin)
hit = [t for t in tabs if 'lorentz' in t.get('url','').lower()]
print(json.dumps(hit, indent=2))
"
```

### <a id="cdp-foreground-prereq"></a>§3.3 前提: スマホ側で対象 tab が foreground

Pixel 系 (and 一般 Android) では **対象タブが foreground でないと DevTools tab list に出ない / response 来ない** ことがある。 確認:

```bash
adb -s <ip>:<connect-port> shell "dumpsys window | grep mCurrentFocus"
# → "mCurrentFocus=Window{... com.brave.browser/...Main}" であること確認
# 設定 app 等が foreground なら Brave に切替必須
```

LorentzArena 等の long-running tab はこの間 background suspend の risk あり、 慎重に operate (= 対象タブを foreground に戻したら 5 秒待ってから query)。

---

## <a id="runtime-evaluate-ws"></a>§4 Runtime.evaluate via WebSocket (= JavaScript 実行)

### <a id="origin-header-workaround"></a>§4.1 origin header workaround

Chromium-based Android browser は WebSocket 接続元 origin を厳しく check、 `--remote-allow-origins` flag が無いと **HTTP 403 で reject** される (= browser 起動時に flag 渡せないため、 production app では設定不能)。

**workaround**: WebSocket client から **Origin header を空で送る** (= "" / null)、 browser が許可する。

### <a id="python-helper-script"></a>§4.2 Python helper script

```python
# /tmp/cdp_eval.py
import json, sys, websocket

WS_URL = "ws://localhost:9222/devtools/page/<TAB-ID>"

def evaluate(expression: str) -> dict:
    ws = websocket.create_connection(
        WS_URL,
        timeout=30,
        origin="",          # ← workaround: empty origin で 403 回避
        suppress_origin=True,
    )
    try:
        ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "returnByValue": True,
                "allowUnsafeEvalBlockedByCSP": True,
            },
        }))
        while True:
            resp = json.loads(ws.recv())
            if resp.get("id") == 1:
                return resp
    finally:
        ws.close()

if __name__ == "__main__":
    result = evaluate(sys.argv[1])
    print(json.dumps(result, indent=2, ensure_ascii=False))
```

依存:
```bash
pip3 install websocket-client --break-system-packages
```

### <a id="runtime-eval-usage"></a>§4.3 使い方

```bash
# 簡易 1-liner
python3 /tmp/cdp_eval.py "1 + 1"
# → returns {"id": 1, "result": {"result": {"type": "number", "value": 2}}}

# game state dump 等の長 expr
python3 /tmp/cdp_eval.py "JSON.stringify(window.__game.getState(), null, 2)"
```

---

## <a id="mobile-only-bug-rca"></a>§5 mobile-only bug RCA pattern

### <a id="performance-now-suspend"></a>§5.1 `performance.now()` vs `Date.now()` で suspend 時間を逆算

mobile Chromium の background tab は **timer suspend** されるが (= setInterval fire しない)、 `Date.now()` (= wall_clock) は経過、 一方 `performance.now()` は **suspend 中も停止しない場合があるが UA 依存**。 但し Android Chromium は **suspend 中も performance.now() が止まる** 挙動が観測されている。

→ live tab で:
```js
({
  perfTimeOrigin: performance.timeOrigin,
  perfNow: performance.now(),                     // active 実行時間
  dateNow: Date.now(),
  wallClockSinceOrigin: Date.now() - performance.timeOrigin, // total page 寿命
  suspendDurationSec: ((Date.now() - performance.timeOrigin) - performance.now()) / 1000,
})
```

`suspendDurationSec` が大きければ background suspend されていた時間が判明。 LorentzArena の「12.5h suspend 確認」 はこの diff から逆算した。

### <a id="live-state-capture"></a>§5.2 Live state capture before reload

mobile bug は reload で state 失う class が多い (= localStorage で persist しない揮発 state が原因)。 RCA で「reload して直る = 真因不明」 を避けるには **reload 前に state 完全 dump**:

```bash
# 1. window object に exposed な store / state を JSON dump
python3 /tmp/cdp_eval.py "
JSON.stringify(window.__game.getState(), (k, v) => {
  if (v instanceof Map) return ['__map__', [...v.entries()]];
  if (v instanceof Set) return ['__set__', [...v]];
  return v;
})"

# 2. localStorage / sessionStorage
python3 /tmp/cdp_eval.py "
JSON.stringify({
  localStorage: Object.fromEntries(Object.keys(localStorage).map(k => [k, localStorage.getItem(k)])),
  sessionStorage: Object.fromEntries(Object.keys(sessionStorage).map(k => [k, sessionStorage.getItem(k)])),
})"

# 3. 結果を repo の repro/<date>-<bug-name>/ に persist
```

### <a id="ring-buffer-gc"></a>§5.3 ring buffer GC を意識した「真因 event の痕跡が消える」 problem

worldLine.history 等の **直近 N entry cap** を持つ data structure は、 真因 event から **N × dτ 時間以上経過すると GC されて消える**。 LorentzArena では history.length=2000 + dτ=0.013 sec = 26 sec の寿命。 真因が「数時間前」 に発生していると痕跡なし。

→ live capture は **真因発生から短時間内**でしか有効。 long-running bug は **定期 dump (= 1 時間ごと等) を仕込む** か、 **MAX_HISTORY を一時的に上げる version で repro** する pattern が必要。

---

## <a id="gotchas"></a>§6 注意点 / よくあるハマり

| 症状 | 原因 | 対処 |
|---|---|---|
| `adb devices` で device 出ない | USB cable が data 非対応 (= 充電のみ) / Android side で USB debug OFF | WiFi ADB に切替が早い。 USB 続けるなら cable 交換 + 設定確認 |
| `chrome://inspect` で device 出るが tab list 空 | 対象 tab が foreground でない / phone 画面 sleep | tab を foreground に + 画面 ON |
| WebSocket 接続で 403 Forbidden | `--remote-allow-origins` 制約 | `origin=""` workaround (§4.1) |
| `curl http://localhost:9222/json/version` がタイムアウト | port forward 確立済だが対象 tab が background suspended | tab を foreground に戻す + 数秒待つ |
| `chrome_devtools_remote` socket が複数 app で競合 (= Chrome + Brave 同時 install 等) | abstract namespace で同名 socket、 後続 app は **別名 (例: `webview_devtools_remote_<pid>`)** で listen | `cat /proc/net/unix` で実 socket 名確認 + その名前で forward |
| `public-precommit-runner.sh` が UA `Chrome/N.0.0.0` (= `N` は major version 整数) を ipv4 false positive | Tier-A ipv4 detector regex `(\d+\.){3}\d+` が `N.0.0.0` 形式の version string も match | escape hatch (`--no-verify`) で bypass + 各 user の incidents 記録に記載。 detector 改修は false positive 2 件目以降で検討 |

---

## <a id="references"></a>§7 References

- 由来 session: 2026-05-06 LorentzArena Bug 14 live state capture (= [`2+1/repro/2026-05-06-bug14-state/README.md`](https://github.com/sogebu/LorentzArena/blob/main/2%2B1/repro/2026-05-06-bug14-state/README.md))
- Android ADB docs: https://developer.android.com/tools/adb
- Chrome DevTools Protocol: https://chromedevtools.github.io/devtools-protocol/
- 関連 odakin-prefs 規律: `work-discipline.md §「USB ADB が詰まったら WiFi ADB に即切替」` + `§「mobile-only bug は reload 前に state 吸い出す」`
