<!-- doc-meta
when: claude.ai routines (RemoteTrigger / cloud cron) を作成・管理するとき
category: harness-core
summary: claude.ai routines (= RemoteTrigger API、 旧「scheduled remote agents」) の知識集 — cloud 側に CCR session を spawn する cron / one-time trigger、 local 機構の scheduled-tasks.md との区別、 操作は RemoteTrigger tool / /schedule skill 経由
-->
# claude.ai routines (= RemoteTrigger API) 規約

claude.ai の **routines** (= かつての「scheduled remote agents」) を扱う際の知識集。 cron expression or one-time trigger で **cloud 側に CCR (Claude Code Remote) session を spawn** する仕組みで、 user の local machine とは独立して動く。

`RemoteTrigger` tool (ToolSearch で `select:RemoteTrigger` で load 可) または `/schedule` skill 経由で操作する。

## 既存 `scheduled-tasks.md` との区別

- **`scheduled-tasks.md`**: Claude Code 内蔵の `create_scheduled_task` / `update_scheduled_task` MCP tool (= SKILL.md ベース、 ローカル Claude バックエンドが prompt を保存)
- **本 file**: claude.ai web 側の `RemoteTrigger` API (= CCR session を cloud で spawn、 cron_expression / run_once_at で trigger)

両者は別 mechanism。 互いに置換不可。 user の意図次第で使い分ける。

## 制約 (= 設計時に必ず考慮)

| 制約 | 意味 |
|---|---|
| **cloud 実行** | remote agent は Anthropic infrastructure 上で動く。 user の `~/Dropbox/`、 `~/Claude/`、 環境変数、 local CLI MCP 等に**一切アクセス不可** |
| **git clone 経由 source 取得** | input data は `job_config.ccr.session_context.sources[]` で git repository URL を指定して clone する形式のみ。 git 経由で取れないもの (= Dropbox / local file / 認証付き API) は agent からは見えない |
| **cron は UTC 解釈** | `cron_expression` は 5-field UTC。 user の local timezone との変換が必要 (= JST → UTC は −9h、 例: 9am JST 毎日 = `0 0 * * *`) |
| **minimum interval = 1 hour** | `*/30 * * * *` 等は reject される。 5 分刻みの polling 等は別 mechanism (= GitHub Actions cron 等) を選ぶ |
| **run_once_at は未来 UTC** | one-time trigger は `YYYY-MM-DDTHH:MM:SSZ` RFC3339 UTC、 過去なら reject。 user の相対表現 (= 「明日 9 時」) は `date -u` で fresh time を取得してから resolve |
| **routine 削除は API 不可** | `RemoteTrigger` action に `delete` なし。 user に <https://claude.ai/code/routines> へ誘導 |

## 推奨設計 pattern

### Hybrid notify pattern (= local-required workflow との橋渡し)

remote agent は local file に触れないため、 local 完結の workflow (= 例: `~/Dropbox/` の roster sync、 user の handwritten note 反映) を全自動化できない。 解決 pattern:

- **remote agent の仕事**: source repo に **reminder file を commit + push** (= 例: `reminders/YYYY-MM-DD-<task>.md`)
- **通知経路**: GitHub の commit-on-push email、 または user の dashboard で reminder file の存在を surface
- **実 sync**: user が手元 Mac で reminder の指示に従って手動実行

これは「remote agent の出力 = git commit」 という設計で、 cloud と local を非同期に bridge する。

### Prompt は self-contained

remote agent は zero context で起動する (= 前回 session の memory なし、 user の chat 履歴なし、 私の作業状態なし)。 prompt に以下を必ず含める:

- 「今日は何月何日 (= 4/1 or 8/1 等の trigger 日付)」 という anchor
- 背景 (= なぜ起動されたか、 何を達成すべきか)
- 詳細 plan file への path (= source repo に同梱、 例: `~/Claude/<repo>/plans/<plan>.md`)
- 完了 message として何を出力すべきか (= GitHub URL、 file path 等)
- **触らない範囲**の明示 (= 例: 「他リポは触らない」)

### MCP connectors の auto-attach

routine create 時、 `mcp_connections` を body に指定しなくても、 user の claude.ai connector 設定 (= Google_Calendar / Gmail 等) が**自動 attach される**。 prompt で使わないなら ignore で OK だが、 副作用 (= 意図しない calendar 操作) のリスクを認識。 minimize したい場合は routine create 後に web UI で disconnect。

### allowed_tools 最小化

`session_context.allowed_tools` で agent が使える tool を絞る。 reminder file 作成だけなら:

```json
"allowed_tools": ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
```

= file 操作 + git command (= Bash) のみ。 Network fetch / WebSearch 不要なら除外。

## RemoteTrigger API quick reference

| action | 用途 | required |
|---|---|---|
| `list` | 全 routine 一覧 | (なし) |
| `get` | 単一 routine 取得 | `trigger_id` |
| `create` | 新規作成 | `body` (= name + cron/run_once + job_config) |
| `update` | 部分更新 | `trigger_id` + `body` |
| `run` | 即時実行 (= test 用) | `trigger_id` |

create body の minimal shape:

```json
{
  "name": "<descriptive name>",
  "cron_expression": "<5-field UTC>",
  "enabled": true,
  "job_config": {
    "ccr": {
      "environment_id": "<env_id>",
      "session_context": {
        "model": "<model id、 例は執筆時点 (2026-06) の claude-sonnet-4-6 — 現行 lineup から選ぶ>",
        "sources": [{"git_repository": {"url": "https://github.com/<org>/<repo>"}}],
        "allowed_tools": ["Bash", "Read", "Write", "Edit"]
      },
      "events": [{
        "data": {
          "uuid": "<fresh lowercase v4 uuid>",
          "session_id": "",
          "type": "user",
          "parent_tool_use_id": null,
          "message": {"content": "<self-contained prompt>", "role": "user"}
        }
      }]
    }
  }
}
```

one-time の場合は `cron_expression` を `run_once_at` (= RFC3339 UTC) に置換。

## 反パターン

- **local 完結 workflow を remote agent で全自動化を試みる** (= cloud で local file に触れないため必ず失敗する)。 hybrid pattern (= reminder のみ remote + 実 sync は local) に divert する
- **cron expression を JST で書く** (= UTC に変換せず `0 9 1 4 *` を「毎年 4/1 09:00 JST」 と意図 → 実際は毎年 4/1 09:00 UTC = JST 18:00 で発火、 9h ずれ)
- **prompt を「先回 session の続き」 と書く** (= remote agent は zero context、 必ず stand-alone に書く)
- **`scheduled-tasks.md` の SKILL.md 同期 ルールを本 routine に適用** (= SKILL.md は別 mechanism で、 本 routine の prompt は API response 内に保存される。 git 同期 task 不要)

## 反パターン一般化: skill capability の名前ベース評価

未経験 skill / API の capability を skill 内容 (= help / docstring) を read せず名前 + memory 推測で評価する trap が再現性高い。 典型: `schedule` skill を「cloud で動く = マシン依存しない ◎」 と partial truth から ◎ 評価 → 実装直前に内容を read → 「local file 一切アクセス不可」 という critical 制約が発覚 → hybrid pattern (= 上記推奨設計 pattern) に redesign を強いられる。

**規律**: 新 skill / tool / API の capability assertion をする前に必ず help / docstring を read + 結果を expose してから断言。 名前ベース推測は「安価な操作で expensive 操作 (= help read) を bypass する」 trait の典型現れ。

## 関連 doc

- `~/Claude/claude-config/docs/convention-design-principles.md#automation-trigger-routing` — 「自動化」 intent から routine を直結せず、 wake event / judgment / context continuity / locus / authority で発火経路を選ぶ製品横断原則
- ~/Claude/claude-config/conventions/scheduled-tasks.md — **別 mechanism** (= Claude Code 内蔵 scheduled task / launchd 等の実行 locus)、 本 file とは別 system で **互いに置換不可・どちらも現行** (⚠️ 2026-09-02 訂正: 旧記述「旧 mechanism」 は誤り — 本 file 冒頭が「両者は別 mechanism。 互いに置換不可」 と書いており、 実行 locus の選択は `scheduled-tasks.md#execution-locus-selection` が現行の正本)
- `~/Claude/claude-config/conventions/multi-session-coordination.md` — cross-session 一般則
- `~/Claude/claude-config/conventions/mcp.md` — MCP / connectors 全般

## 由来

2026-05 確立。 claude.ai routines API を初めて運用した際に発見した制約 + 推奨設計 pattern を集約。
