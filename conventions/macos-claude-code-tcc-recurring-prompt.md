<!-- doc-meta
when: Claude Code の App Management TCC dialog が繰り返し出るとき
category: macos
summary: Claude Code の app bundle が `~/Library/Application Support/Claude/claude-code/<version>/claude.app` という versioned path に置かれているため、 App Management TCC 権限が auto-update 毎に invalidate されて dialog が再 prompt される構造的症状 (= sibling pty-leak と同じく Anthropic 側 fix 待ち候補、 stable launcher path 化が root 対策)
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

## 関連

- `macos-claude-app-pty-leak.md` (= sibling、 Claude.app Desktop 側の別 pty leak 症状、 同じく Anthropic side fix 待ち)
- `launchd-cloudstorage-tcc.md` (= 別型の TCC 症状 — launchd 経由の script が `~/Library/CloudStorage/` を読めない、 invoker 単位で TCC 判定される macOS 15+ の permission 継承挙動が原因。 本 doc が「versioned path で TCC db entry 無効化」 なのに対し、 sibling は「invoker の TCC identity 不足」 が root)
- macOS App Management TCC service: `kTCCServiceSystemPolicyAppData` (Ventura 13.0+)
