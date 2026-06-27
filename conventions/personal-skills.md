# Personal skills — 規律の発火を doc recall でなく description dispatch に乗せる

`~/.claude/skills/<name>/SKILL.md` (= personal skill) を「規律・手順の発火面」として使う規約。
公式 doc: https://code.claude.com/docs/en/skills (frontmatter reference / where skills live)。
scheduled task の SKILL.md (= 別機構、 backend に prompt が保存される) は
[`scheduled-tasks.md`](scheduled-tasks.md) が正本 — 本 file は **全 session 常時可視の
auto-discover skill** のみを扱う。

## §0. 発火面の選択 — doc / skill / hook / scheduled task

規律や手順を書く前に、 それが「いつ・どうやって発火するか」 を選ぶ
(一般原則 = `docs/convention-design-principles.md §8.12`):

| 発火面 | 発火機構 | 向く場合 |
|---|---|---|
| hook | tool call の決定的 interception | 止める / 書き換えるべき呼び出しを**機械条件で識別できる** |
| **personal skill** | description が全 session 常時 context 内、 model が「今がその瞬間」 と判断して自律 invoke | trigger を機械条件で書けないが、 **正しい瞬間の想起**が問題 (= doc 記載 reflex の不発) |
| scheduled task | 無人定期 + Claude judgment | [`scheduled-tasks.md` execution-locus-selection](scheduled-tasks.md#execution-locus-selection) |
| doc 記載 | 読んだ session の recall 依存 | 上 3 つが不可のときの最弱手段。 後日格上げの trigger 条件を書き残す |

**skill の非対称性が要点**: 非発火時の noise はゼロで、 worst case = skill が無いのと同じ
(= 現状維持)。 hook の false positive と違い、 機構 fleet 全体の信号価値を毀損しない
(= hook を見送るべき場合の判定は [`hook-authoring.md` hook-no-go-judgment](hook-authoring.md#hook-no-go-judgment))。
代償は発火が**確率的** (model 判断) であること — 不発が実害を生む domain では
hook への格上げを evidence-driven で検討する (escalation trigger を skill 導入時に書き残す)。

## §1. 機構 facts (2026-06-13 検証、 claude-code 2.1.170 / macOS)

- `~/.claude/skills/<name>/SKILL.md` は**全 session で auto-discover** され、 frontmatter
  `description` を根拠に model が自律 invoke する (project 単位は `.claude/skills/`)。
  dir 名がそのまま slash command 名になる (= `/name` で手動起動も可)
- frontmatter は全 field optional、 `description` のみ推奨 (= auto-invoke の判断材料。
  `when_to_use` と**合算 1536 char cap**)
- **symlink された skill dir も拾われる** (= 公式 doc 未記載の実測、 2026-06-13
  claude-code 2.1.170)。 build 依存の可能性に注意 (= [`hook-authoring.md` build-dependent-behavior](hook-authoring.md#build-dependent-behavior) と同類:
  upstream docs / build 挙動は変わりうる、 新環境では §4 の検証を回す)
- **discovery は session 開始時** (= 新規 skill は既存 session に現れず、 新 session で
  出現するのを実測。 hook の snapshot 挙動 [`hook-authoring.md` new-hook-session-snapshot](hook-authoring.md#new-hook-session-snapshot) と整合)

## §2. description の書き方 (= trigger 品質が設計の本体)

dispatch は description だけで決まる。 body がどれだけ良くても description が悪いと発火しない。

- **user 発話の形で trigger を書く**: 「過去の○○の状況を参照したら」 + 例文 2-3 個を
  description 内に直接埋める (例: 「あのメール返事来てる?」「〜さんの件どうなってた?」)
- **負の空間も書く**: 「△△する前にまずこれを起動」 (= before grepping / before external
  search)。 model が代替手段に流れる分岐点を名指しで塞ぐ
- **禁止形も 1 文**: その skill が防ぎたい結論飛躍があるなら description に書く
  (= 「外部検索 null でも内部未確認のまま不在と結論しない」 等)
- **body は薄く**: 手順 + 参照 pointer に徹する。 規律の正本・RCA は別 doc に置き、
  skill は dispatch + 手順書 (= SoT 重複を作らない)

## §3. git 配信 + 多 machine 配線 pattern

skill 実体は git repo (個人層) に置き、 installer が `~/.claude/skills/` に symlink する。
このとき **「file 到着 (git pull)」 と 「配線 (machine-local symlink)」 の 2 段配達**になる
ことに注意 — prose の「あとで install して」 は発火しない (= [`hook-authoring.md` delivery-audit-4-axes](hook-authoring.md#delivery-audit-4-axes) / [`hook-authoring.md` partial-install-state](hook-authoring.md#partial-install-state) の
hook 配信問題と同型)。

- installer に read-only `--check` mode を持たせ、 SessionStart hook から毎 session 呼ぶ
  (= 未配線 drift を全 machine で自動 surface)
- 同 repo に **scheduled-task 専用 skill が同居**する場合、 配線対象は **explicit allowlist**
  (registry file、 1 行 1 skill 名) にする。 default-include だと専用 skill が全 session
  可視になり、 定期 publish flow 等の誤発火 risk を作る
- 新規機構 (専用 installer 等) を増やす前に、 既存の installer / `--check` channel に
  相乗りできないか先に問う (= 機構増殖の抑制)

## <a id="verification-procedure"></a>§4. 検証作法

**順序が重要: trigger test → discovery test** (skill 名を一度でも口にすると、 以後の
「自然に発火するか」 test が汚染される)。

1. **trigger test (本体)**: 新 session に **skill 名を含まない自然な質問** (= その skill が
   守るべき瞬間を再現する質問) を投げる。 成功 = transcript の text より先に
   `Skill(<name>)` tool call が出る。 「skill を経由せず中身の script を直接叩いた」 は
   behavior としては正解だが dispatch の検証としては未確定 — Skill call の有無で切り分ける
2. **discovery test**: `/` 補完一覧に出るか、 または「available skills に <name> ある?」
3. **事後 forensic**: session transcript (JSONL) を grep — `"name":"Skill"` 近傍に
   skill 名があれば起動の機械的証拠

**headless `claude -p` での検証は制約が多い** (2026-06-13 実測):

- stdin が開いた pipe (never-EOF) のとき、 prompt を引数で渡していても **stdin を待つ**。 旧 build (2.1.53) は無期限 hang、 新 build (2.1.177) は 3 秒 grace 後に `Warning: no stdin data received in 3s, proceeding without it...` で進む (= build 依存、 [`hook-authoring.md` build-dependent-docs-drift](hook-authoring.md#build-dependent-docs-drift) と同類。 upstream は最新で緩和済、 docs issue #68118 起票時に確認)。 **いずれの build でも `< /dev/null` を付けるのが綺麗** (待ち時間ゼロ + 警告なし)
- Claude Code session 内から起動するには `env -u CLAUDECODE` が要る (nested guard)
- CLI の auth は GUI app と別レイヤー — 未認証 machine では 401 (`claude auth login` は user 操作、 machine ごとに必要)
- そもそも **trigger 品質は headless で測れない** (prompt に skill 名を入れた時点で汚染)

→ **実 session での trace 確認が上位互換** (discovery + trigger を一発で検証できる)。

## 関連

- [`hook-authoring.md`](hook-authoring.md) — [hook-no-go-judgment](hook-authoring.md#hook-no-go-judgment) (hook を見送る判定 = skill へ切替える分岐) / [build-dependent-behavior](hook-authoring.md#build-dependent-behavior) (build 依存挙動) / [delivery-audit-4-axes](hook-authoring.md#delivery-audit-4-axes)・[partial-install-state](hook-authoring.md#partial-install-state) (配信 2 段配達)
- [`scheduled-tasks.md`](scheduled-tasks.md) — 無人定期実行の SKILL.md (= 別機構、 混同注意: あちらは backend に prompt が保存され、 本 file の auto-discover とは独立)
- `docs/convention-design-principles.md §8.12` — 発火面 hierarchy の一般原則 (本 file は skill 面の機構詳細)
