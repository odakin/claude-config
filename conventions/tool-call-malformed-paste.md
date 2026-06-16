# Tool call malformed バグ — 別セッションへのペースト用メモ

> 正本: `claude-config/conventions/tool-call-robustness.md`

## 現象

`Your tool call was malformed and could not be parsed. Please retry.` で tool call が失敗し、retry も連続失敗する。

## 真因

**Anthropic backend の Opus 4.8 model serialization bug**。  
Claude Code CLI の bug でも、prompt の書き方の問題でもない。  
大きい context (1M-context session) で tool_use block を壊れた形で出力する。

## 報告先

| URL | 役割 |
|---|---|
| https://github.com/anthropics/claude-code/issues/64774 | **canonical evidence** (= 6/2 開設・~1万ターン統計・model 別失敗率 Opus 4.8 のみ ~1.5% / 他 model 0%・CLI 横断 = model 起因、 新規 occurrence はここにコメント) |
| https://github.com/anthropics/claude-code/issues/64684 | 衛星: XML タグ prefix 脱落 |
| https://github.com/anthropics/claude-code/issues/64955 | 衛星: 並列 tool call / 非 ASCII で頻発 |
| https://github.com/anthropics/claude-code/issues/64235 | 衛星: stop_reason=tool_use なのに block 不在 |
| https://github.com/anthropics/claude-code/issues/62344 | 副次機序: 一度 malformed が context に入ると後続も poisoning |
| https://github.com/anthropics/claude-code/issues/62123 | ⚠️ **別 variant** (= 5/25 開設・Opus 4.7 + VS Code 系、 同症状でも root が別、 4.8 系の occurrence はここに報告しない) |

## 緩和策 (確実順)

1. **model 切替** (最優先) — Opus 4.8 固有。本命は **Opus 4.7 1M** (`/model claude-opus-4-7[1m]` = 賢さ最大 × バグ 0%)、Sonnet 4.6 は次善 (#64774)
2. **新 session** — poisoned context を断ち切る
3. **sub-agent 委譲** — work tool 実行を Agent に逃がす (現 session の context 保持可)
4. **1 ターン 1 tool call** — 並列を避ける (#64955 対策)
5. 複雑 Bash は `Write` でファイル化 → 単純コマンドで実行
6. tool call を含むターンの本文はプレーン短文 (装飾・絵文字は別ターンに)

## session が poisoned したら

work tool (Bash/Edit 等) を自分で実行せず、**全 tool 実行を sub-agent 委譲**に切り替える。  
指示が長い / 特殊文字が多い場合は `Write` でファイル化し、short ASCII の pointer prompt だけ Agent に渡す。  
sub-agent の完了報告は claim として扱い、`git log` / `grep` で裏取りする。
