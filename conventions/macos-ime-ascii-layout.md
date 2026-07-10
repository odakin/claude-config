<!-- doc-meta
when: macOS で直接入力と IME のキー配列を分けたいとき
category: macos
summary: macOS で「直接入力=非 US 配列、IME 中=US 配列」を共存させる gotchas (= IME のキー変換は MRU ASCII-capable layout 従属 / TISSetInputMethodKeyboardLayoutOverride は外部から効かない / 無効化 layout は MRU 候補外 / CGEvent 書き換え 2 経路は IME バイパス・mozc の Option=ALT 扱いで不成立 / 成立解 = IME 切替検知 + US layout 動的有効化+瞬間選択〔権限不要〕 / CLI バイナリの tap は .app bundle 化で TCC 安定)
-->
# macOS IME × 非 US キーボードレイアウト共存の gotchas

**読むタイミング**: 「直接入力は非 US 配列 (= Canadian-CSA / AZERTY 等)、日本語 IME のローマ字・英数入力は US 配列」のような **配列の使い分け**を macOS で組もうとした時。または「IME に切り替えたら記号の配置が変 (= フランス語配列っぽい等)」という症状の診断時。

**結論 (= 成立解は §4 の 1 つだけ)**: IME 切替検知 + US layout の動的有効化/瞬間選択。イベント書き換え系 (= CGEvent tap) は **2 経路とも不成立** (§3)。

## §1 原理: IME のキー変換は「MRU ASCII-capable layout」に従う

macOS の IME (= Google 日本語入力 / Apple 日本語 IM) はローマ字・英数のキー変換に **most-recently-used ASCII-capable keyboard layout** (= `TISCopyCurrentASCIICapableKeyboardLayoutInputSource`) を使う。直接入力用に非 US 配列を選択すると、**IME に切り替えた後もその配列が変換に使われ続ける** — これが「IME 中だけ記号がずれる」症状の正体。診断:

```bash
defaults read com.apple.HIToolbox AppleEnabledInputSources   # 有効な layout 一覧
```

```swift
TISCopyCurrentASCIICapableKeyboardLayoutInputSource()  // IME が使う変換 layout
```

## §2 確認済み事実 (2026-06-12, macOS Darwin 25 / Google 日本語入力 3.33)

| # | 事実 | 帰結 |
|---|---|---|
| 1 | `TISSetInputMethodKeyboardLayoutOverride` は外部プロセスから呼ぶと **status=0 (成功) を返すが保存されない** (= 読み返すと none、IME 選択中に呼んでも同じ) | 正規 API での外部矯正は不可。IME 自身のプロセス専用 |
| 2 | **無効化した layout は MRU 候補から外れる** (= US を入力メニューから消すと MRU が非 US 配列に戻る) | 「メニューに出さない + MRU 維持」は静的には両立しない → §4 の動的化 |
| 3 | ASCII-capable layout を 0 個にはできない (= 最後の 1 個への `TISDisableInputSource` は status=0 でも **黙殺される**) | 「全部無効化して fallback を US にする」案は不成立 |
| 4 | `TISSelectInputSource` / `TISEnableInputSource` / `TISDisableInputSource` は外部プロセス (LaunchAgent 含む) から動く | §4 の機構が権限なしで組める |
| 5 | TIS の状態読み (MRU / IsEnabled) は **プロセス内 cache が stale** になる。長寿命プロセス内の読みと fresh プロセスの読みが食い違う | 検証は fresh プロセスで読む (= 検証 script の再利用読みを信用しない) |

## §3 イベント書き換え系の失敗 2 経路 (= 再試行しない)

**(a) CGEvent unicode string 書き換え** (`CGEventKeyboardSetUnicodeString` で US 翻訳を焼き込む): 文字列を焼き込んだイベントは **IME の変換処理をバイパス**して直接挿入される → ひらがなが一切打てなくなる。英字のような「同じ文字」の書き換えでも壊れる (= バイパスは内容でなくイベント属性で起きる)。

**(b) keycode + 修飾キー差し替え** (= Karabiner 原理。「US で記号 X のキー」→「非 US 配列で X が出る keycode+modifier」): 非 US 配列で **Option レイヤーにしかない文字** (CSA の `[` `]` `{` `}` 等) が壊れる。mozc は **Shift のみの修飾のときだけ** `[event characters]` を文字として使い、**Option は `KeyEvent::ALT` 扱い**で変換に入らず素通し → 半角のまま直接挿入 + 直接入力モードへの意図しない切替 (mozc `src/mac/KeyCodeMap.mm` で確認)。Shift リマップだけで足りる配列ペアなら (b) は成立するが、CSA⇔US は Option レイヤー必須なので不成立。Karabiner-Elements を使っても同じ原理なので同じ壁に当たる。

## §4 成立解: IME 切替検知 + US layout の動的有効化/瞬間選択

常駐 watcher (LaunchAgent) で入力ソース切替を監視し:

1. **IME モード選択を検知** → US (ABC) layout を `TISEnableInputSource` → `TISSelectInputSource` で瞬間選択 → 元の IME モードに戻す (= MRU が ABC になる)。**IME 使用中は ABC を有効のまま維持** (§2-2 のため)
2. **通常 layout (非 US 配列) へ戻ったら** ABC を `TISDisableInputSource` (= 入力メニューから消える)
3. ユーザーが誤って ABC を選択したら本来の配列へ自動再選択 (= bounce)

性質: イベントに一切触れない → **かな変換を壊しようがない** + **アクセシビリティ等の TCC 権限不要**。trade-off は (i) IME 使用中だけメニューに ABC が見える、(ii) 切替直後 ~0.2s の瞬間選択フラッシュ。全キーが正しく変換される (= §3(b) で不可能な dead-key 専用文字も OK)。

実装 notes:

- 監視は **CFNotificationCenter** (`kTISNotifySelectedKeyboardInputSourceChanged`, `.deliverImmediately`) + 1s ポーリングの二段構え。`NSDistributedNotificationCenter` は **バックグラウンドプロセスだと配送が保留**されるので使わない
- handler は「選択中が IME かつ MRU≠ABC のときだけ動く」構造にすると自己の切替で再発火しても自己安定 (= ループしない)
- 自前の連続 `TISSelectInputSource` の間は 80ms 程度 sleep (= TextInputSwitcher の反映待ち)

## §5 関連 (CGEvent tap を別用途で使う場合の TCC note)

tap 方式自体は本件で廃案だが、素の CLI バイナリで `CGEvent.tapCreate` する場合: アクセシビリティ許可が **バイナリの cdhash に紐付く**ため、再ビルドのたびに **System Settings 上は ON のまま実際は無効**という stale 状態になる (= [`macos-claude-code-tcc-recurring-prompt.md`](macos-claude-code-tcc-recurring-prompt.md) と同族の versioned-binary TCC 問題)。`tccutil reset` も path ベースの client は受け付けない。緩和 = **Info.plist (CFBundleIdentifier + LSUIElement) 付きの .app bundle に包んで ad-hoc 署名** (= TCC が bundle ID で管理され、設定画面の表示名もまともになり、`tccutil reset Accessibility <bundle-id>` が効くようになる)。
