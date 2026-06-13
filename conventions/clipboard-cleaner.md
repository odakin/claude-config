# clipboard-cleaner — PDF コピーの改行・RTF 書式の後始末

## 問題

PDF からテキストをコピーして Word 等に貼ると、(a) PDF の見た目改行が
段落内にそのまま入る、(b) RTF 書式（イタリック・フォント等）が付いてくる。

## 構成（全て明示発火、常駐監視なし）

| 入口 | 実体 | 用途 |
|---|---|---|
| ⌃⌥⌘V hotkey | `hammerspoon/init.lua` → `scripts/clipboard-cleaner.py` | 推奨。**貼り付け先で押す** = 整形 + 即 Cmd+V 貼り付け（「ペーストしてスタイルを合わせる」の整形版、整形失敗時は貼り付けない。2026-06-13 user feedback で整形のみ → 整形+貼り付けに変更） |
| CLI | `python3 scripts/clipboard-cleaner.py` | Hammerspoon なし環境（整形のみ、貼り付けは手動） |
| ブラウザ | `scripts/pdf-cleaner.html` | macOS 以外 / pbcopy なし環境の fallback |

動作: 見た目だけの折り返し改行を除去し、**意図的な改行は保持**する。
意図的と判定する条件（どれか 1 つで改行を残す）:

1. 次の行が**字下げ**（全角スペース・タブ・半角スペース 2+）で始まる
2. 次の行が**箇条書き・条文マーカー**で始まる
   （・● / （１） / １．１、１　/ 一、一　/ 第○条・○項 / ①）
3. 前の行が**ブロック内最大幅より全角 2 文字以上短い**
   （折り返し行は右端まで詰まっている性質を利用 = 短い行は段落末・
   見出し・箇条書き項目末。幅は全角 1.0 / 半角 0.5 で近似）

空行 = 段落区切りは保持。結合時は行境界が日本語なら直結、英語同士は
スペースを挟み、英語のハイフネーション（行末 `beauti-` + `ful`）は復元。
クリップボード経路では `pbcopy` で書き戻すため RTF 書式も落ちる
（改行が無いテキストでも「書式落とし」として使える）。

既知の限界: 段落最終行がたまたま右端まで届いていて、かつ次の段落が
字下げ・マーカー無しで始まる場合は折り返しと区別できず結合される。

## 設計判断: なぜ常駐 daemon にしないか

クリップボードを定期 poll して自動書き換えする方式は採らない（PR #5 レビュー）:

1. **誤爆**: 「日本語 + 改行あり」の判定では、メール下書き・コード・YAML の
   コピーにもマッチし、構文の一部である改行を silent に破壊する。
   明示発火なら「整形したい時だけ」なので誤爆がない。
2. **secret-handoff.md との衝突**: [`secret-handoff.md`](secret-handoff.md) は
   クリップボードを secret の輸送路と規定し「clipboard は 1 個しかない」を
   中核原則に第三のアクターを排除している。常駐 daemon は clipboard を
   通過する全 secret が常時 subprocess を経由する読み取り面になる。
   明示発火は user が押した瞬間に 1 回読むだけなので、この原則と両立する。
3. **setup.sh での自動 install は scope 超過**: 個人の生産性ツールを
   全 user にデフォルト ON で入れない。Hammerspoon hotkey は
   Step 7（Hammerspoon インストール済み環境のみ、設定 symlink）に
   相乗りするだけで、新たな常駐プロセスを増やさない。

## 実装ノート

- 整形ロジックの**正本は `scripts/clipboard-cleaner.py`**。
  `scripts/pdf-cleaner.html` に同じロジックの JS 実装があるので、
  仕様変更時は両方を更新する（`--selftest` が Python 側の仕様を固定）。
- 日本語判定の文字クラスは両実装で同一:
  U+3000-30FF（全角記号・かな）、U+4E00-9FFF（CJK 統合漢字）、
  U+FF00-FFEF（全角英数）。
- Hammerspoon 側は `~/.hammerspoon/init.lua` の symlink を辿って
  repo 内の Python スクリプトを解決する（パスを焼き込まない）。
  symlink でない環境（手動 copy）では alert を出して何もしない。
- **hotkey からの合成 Cmd+V は修飾キー解放待ちが必須**: hotkey callback 内で
  `hs.eventtap.keyStroke({"cmd"}, "v")` を即送ると、user が物理的に押したままの
  ⌃⌥⌘ がハードウェア修飾状態として合成イベントに合流し、貼り付け先には
  ⌃⌥⌘V として届いて paste にならない（2026-06-13 実機で確認）。
  `hs.eventtap.checkKeyboardModifiers()` を `hs.timer.waitUntil` で 50ms poll し、
  **全修飾キーの解放を待ってから** keyStroke を送る。
- **個人層での自動化**: 「コピーだけで整形」したい場合は、layer 1 を
  fork せずに `~/.hammerspoon/local.lua`（init.lua 末尾の拡張 hook が読む）
  に個人の watcher を組める。その場合も本 doc の設計判断に従い、
  (1) 発火を PDF ビューワー等の特定アプリ由来のコピーに限定する
  （`hs.pasteboard.changeCount()` のみ監視し、対象外アプリのコピーは
  **内容を読まない**）、(2) 整形時に alert を出す、(3) ON/OFF 手段を
  用意する、の 3 点を守ること。
- **pbcopy の C ロケール罠**: `LANG` 未設定（C ロケール）の環境では
  pbcopy は「日本語 + 改行」を含む入力で **silent に空クリップボードを
  作る**（日本語のみ・ASCII のみの入力は通るため気づきにくい）。
  Hammerspoon の `hs.execute` / launchd 配下は `LANG` 未設定なので、
  Python 側が pbcopy/pbpaste 呼び出しに常に `LC_CTYPE=UTF-8` を明示する
  （`LC_ALL` は `LC_CTYPE` より優先されるため除去も必要）。
  実機再現: `printf 'にほんご\nつづき' | env -i /usr/bin/pbcopy` → 0 byte。
