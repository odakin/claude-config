# discord-bot: Discord Bot を運用するときの規律

Bot を Discord API 経由で動かす場合の一般則。具体的な server / channel / Bot ID は個人層 (private リポ) に置き、本ファイルには generic pattern のみ。

## 権限ポリシー: Token 漏洩時の被害想定で決める

Bot に付ける channel-level / server-level 権限は「Token が漏れた時にどこまで被害が広がるか」を逆算して最小化する。以下は **「中立 (Allow しない、Deny もしない、= グレー)」がデフォ推奨**:

| 権限 | 中立にする理由 |
|---|---|
| Administrator | 絶対 NG (= 全権限相当) |
| Manage Channel | Token 漏洩時に channel 削除が可能 |
| Manage Permissions / Manage Roles | 他人の権限改変が可能 |
| Manage Webhooks | 外部にデータ流出経路を作れる |
| Manage Messages | 他人のメッセージ削除が可能 |
| Manage Threads | 他人のスレッド削除が可能 |
| Mention @everyone, @here, all roles | annoyance 源、本当に必要になったら個別追加 |
| Send TTS Messages | bot 用途で意味なし、ノイズ源 |

通常の posting bot に必要十分な権限セット (これらを Allow):

- 読み取り: View Channel, Read Message History
- 投稿: Send Messages, Embed Links, Attach Files, Send Voice Messages, Create Polls, Pin Messages
- インタラクション: Add Reactions, Use External Emojis, Use External Stickers, Use Application Commands, Use Embedded Activities, Use External Apps
- スレッド: Create Public Threads, Create Private Threads, Send Messages in Threads
- メンバーシップ: Create Invite (任意)

## Private channel への Bot 追加手順

`@everyone` の View Channel が deny された private channel では、server-level role による View Channel allow も override される。Bot を入れる手順:

1. **Bot user 自身、または Bot 用 role** を channel の「アクセス可」リスト (permission overwrite の allow 側) に追加
2. これで View Channel が channel-level で allow され、Read Message History 等の他権限は server-level role から継承される
3. 詳細権限 (Send Messages, Pin, Polls など) を追加で個別に Allow したい場合は、追加した role/member の詳細 toggle 画面で個別 ON

### Bot 自身が UI 操作の代行をできない理由

Bot が channel の permission overwrite を API 経由で変更するには `Manage Roles` 権限が必要。これを持たない bot は **自分自身に対する allow を API で追加できない** → server admin (人間) が UI で 1 度だけ操作する必要がある。これを最初に踏まえずに「API で全自動」と思い込むと、最後の 1 ステップで詰まる。

## 複数 channel から data を fetch するときの error handling

複数 channel を巡回する fetcher は **per-channel error を non-fatal に**。1 channel の権限欠如 (`Missing Access`) で全体を kill すると、他の正常 channel の data まで止まってしまう (= 1 channel の問題が全 channel の data 鮮度を巻き込む)。

```python
def fetch_channel(channel_id, name):
    # ...
    if not isinstance(msgs, list):
        if first_call:
            print(f'ERROR: {name}: ...', file=sys.stderr)
            return None  # ← sys.exit(1) ではなく None
        break
    # ...

failed = []
for name, cid in channels.items():
    msgs = fetch_channel(cid, name)
    if msgs is None:
        failed.append(name); continue
    # ... write to file ...

if failed:
    print(f'NOTE: failed channels skipped: {", ".join(failed)}', file=sys.stderr)
    sys.exit(1)  # ← 末尾で non-zero exit して UI failure を維持
```

GitHub Actions の workflow 側で **後続 step に `if: always()`** を付け、partial failure でも commit/push を走らせる:

```yaml
- name: Commit if changed
  if: always()  # partial-failure でも successful channels は commit
  run: |
    git add ... && (git diff --cached --quiet || (git commit ... && git push))
```

これで「UI failure を見て修復する signal を保つ」+「正常 channel の data は反映される」を両立。1 channel が permission 系で死んでいても他の data 鮮度は守られる。

## Bot Token の取り扱い

- canonical 配置: `~/.secrets/<bot>-token` の形 (チーム / project 単位、`secrets-config` 規約と整合)
- リポ内 backup を持つ場合は **git-crypt 暗号化必須**。平文 commit は禁止
- chat / public リポ / メール本文への literal 貼付は禁止
- GitHub Actions では `${{ secrets.<NAME> }}` 経由で env var に注入し、log で `***` mask されることを確認 (`echo $TOKEN` のような直接出力をしない)
- **Token を初回 `~/.secrets/<bot>-token` に配置する手順は [`secret-handoff.md`](secret-handoff.md) を参照** — `pbpaste` 系で書き込む案は clipboard 上書きの罠で確実に破綻するため厳禁。stdin-wait 先行 pattern (`cat > file` または `read -rs`) が canonical

## Token 共有プロトコル: owner 単独運用 vs. collaborator 共有

Bot Token を **誰が持つか** を明示的に判断する。Token を持つ人だけが Bot 操作 (ローカル API call / Bot 投稿 script のテスト等) でき、持たない人は GitHub Actions 経由でのみ動かせる (= `workflow_dispatch` で trigger)。

**owner 単独運用** (推奨デフォルト): Token は owner のみが持つ。共同編集者は workflow yaml の編集 + push で Bot を間接実行 (workflow_dispatch も可)。Token 漏洩リスクが最小、信頼境界が明確。collaborator は iterative なローカル開発はできず owner がボトルネックになるが、Bot 運用が daily fetcher 中心なら問題ない。

**collaborator 共有**: 信頼できる共同編集者にも Token を渡す。共有手段:
- 同じ git-crypt 鍵を持つ collaborator → リポ内 `secrets/<bot>-token` に git-crypt 暗号化 commit、setup.sh 等で各マシンに展開
- 鍵未共有の collaborator → out-of-band (Signal / 1Password 等) で個別配布

判断軸: collaborator 数 (2-3 名以下で全員強い信頼関係なら共有 OK) + ローカル開発頻度 + Bot の権限範囲 (Manage 系を持つなら単独運用必須、read/write 程度なら共有許容)。

**shared リポの CLAUDE.md は方針を明記**: 「Token 必要な操作は owner に依頼」 or 「Token は `secrets/<bot>-token` の暗号化 backup から取得 (setup.sh 自動展開)」 — どちらかを書いて共同編集者の「Token どこ?」 の行き止まりを解消する。書いていないと collaborator が場面ごとに owner に問い合わせる手間が発生する。

## Discord API call の User-Agent header 必須

Discord Bot API (`discord.com/api/v10/...`) を curl / Python urllib / requests から叩く場合、**Discord 仕様で User-Agent header 必須**。 default UA (= `Python-urllib/3.x` 等) は Cloudflare で **error 1010 (Access denied) で reject** される。

正しい format (Discord 公式仕様):

```
User-Agent: DiscordBot (<source URL>, <version>) [optional 説明]
```

例:

```python
import urllib.request, json, os
token = open(os.path.expanduser('~/.secrets/<bot>-token')).read().strip()
req = urllib.request.Request(
    f'https://discord.com/api/v10/channels/{cid}/messages',
    data=json.dumps({'content': '...', 'allowed_mentions': {'users': [...]}}).encode(),
    headers={
        'Authorization': f'Bot {token}',
        'Content-Type': 'application/json',
        'User-Agent': 'DiscordBot (https://github.com/<org>/<repo>, 1.0)',
    },
    method='POST',
)
```

公式 SDK (discord.py / discord.js 等) は自動で正しい UA を付けるため、 SDK 経由なら気にする必要なし。 **生 HTTP request を書く時だけ落とし穴**。 ad-hoc な one-shot post script (= odakin が CLI からメッセージ送信する典型ユースケース) で頻発する。

## Cloudflare 1010 error の鑑別: User-Agent vs 組織 NW egress filter

`discord.com` への request が Cloudflare 1010 で reject されたら、 まず **どちらの原因か** を鑑別する:

| 原因 | 切り分け方 | 対処 |
|---|---|---|
| **User-Agent header 欠落** | request header に上記 format の `User-Agent` を付けて再送 | header 修正で即解決 |
| **組織 NW の egress filter** | UA を修正しても 1010、 別 NW (= 自宅 / モバイルテザリング) からだと通る | Bot operations を GitHub Actions / 自宅環境から実行する設計に倒す |

順序が重要: **まず UA を疑う** (= 即修正可能、 NW 経路に責を着せる前に自分の request を直す)。 UA 修正で通れば NW は無罪。 通らなければ NW egress filter を疑い、 自宅 / GHA で再現テスト。 NW 起因と確定したら、 組織 NW で API 動作を当てにしない設計 (= 動かないのが default と考える)。

## Developer Portal: application 名に AI provider 名を入れない

Discord Developer Portal (= https://discord.com/developers/applications) で new application を作るとき、 **名前に "claude" を入れると create が拒絶される** (= 2026-06-20 user 報告 で観測、 odakin が `odakin-claude-secretary` で create 試行 → invalid)。 対処は名前から AI provider 識別子を抜く (例: `odakin-secretary`)。

**推定メカニズム** (= 観測から逆算、 Discord 公式 docs に明文の AI 命名規約は確認できていない):
- (a) Anthropic trademark policy への配慮 (= 「Claude」 は Anthropic の trademark、 Discord 側の自動 filter)
- (b) 広義の AI provider 名 filter (= "openai" "gpt" "gemini" "anthropic" 等も同じ filter で reject される可能性、 個別 reproduce はしていない)

**規律**: bot の **役割** に AI 駆動である事実を name で expose したい (= transparency) ケースでも、 application 名は AI provider 識別子を避けて命名する。 user-visible な「AI 駆動である」 announcement は bot の About 文 (Developer Portal の application Description field) や server 内 introduction post で代替する。

## Developer Portal: Message Content Intent は **message content fetch 用途では必須**

Discord Developer Portal の `Bot` page 下部に **`Privileged Gateway Intents`** という 3 toggle section があり、 default は全部 OFF:

- `Presence Intent` — member の online status を receive
- `Server Members Intent` — guild の member 一覧 + join/leave event を receive
- **`Message Content Intent`** — message の **`content` field を REST + Gateway 両方で受け取る**

2022 年 8 月の Discord 仕様変更で、 **`Message Content Intent` を OFF のままだと `GET /channels/{id}/messages` の response で全 message の `content: ''` (空文字) が返る** (= attachments / embeds / flags は普通に来るが本文だけ blank)。 bot 自身が mention された message と bot 自身が送信した message は intent 無くても content が返るが、 それ以外は不可視。

**fetch bot (= twcu-phys-bot / qm-textbook-bot / odakin-secretary catch-all 等) では必須**: 1 個目の toggle (Message Content Intent) を ON、 Save Changes。 他 2 つ (Presence / Server Members) は OFF のまま (= 用途上不要、 blast radius 最小化)。

100 server 未満なら toggle で即有効化可能 (= App Verification 不要)。 100 server 超え配布なら App Verification が要る (= 個人 bot は射程外、 上記 §「アプリ認証」 節参照)。

**観測 (2026-06-20)**: odakin-secretary を作成 → 招待 → fetch 試行で 100 message 全 content が `''` だった。 原因 = step 1 の私の誤指示「Privileged Gateway Intents は全部 OFF のまま」 (= 当時「fetch は intent 不要」 と誤認)。 Save Changes 後の retry で content 取得確認。 過去の twcu-phys-bot / qm-textbook-bot 立ち上げ時にもこの toggle 操作は行われていたはずだが、 institutional knowledge として落ちていた (= 上記「アプリ認証」 節と同型の記録漏れ)。

## Developer Portal: アプリ認証 (App Verification) は 100+ server 拡大用、 個人 bot は無視可能

Discord Developer Portal の左 sidebar には **`アプリ認証`** (英: `App Verification`) という entry があり、 click すると未達 checklist に ⚠️ アイコンが並ぶ画面が出る (例: チーム所属 / ToS link / Privacy Policy link / 全メンバー 2FA)。 これは **「アプリケーションを 100 件を超えるサーバーに拡大する」** ための opt-in 認証で、 個人運用 bot (= 数 server に invite するだけの用途) では **完全に無関係 + 無視可能**。 ⚠️ アイコンは「100+ server 配布を目指すなら N 件足りない」 の pre-flight checklist の意味であって、 「bot が動かない」 ではない。

**観測 (2026-06-20)**: odakin が `odakin-secretary` application 作成直後にこのページに行き当たり、「以前にも同じエラーを見た記憶があるが記録がない」 と flag。 検索の結果、 当 convention にも personal layer の `discord.md` にも記録なし = 過去 2 回の bot 作成 (twcu-phys-bot / qm-textbook-bot) の際に同 page を踏んでいたが institutional knowledge として落ちていた。 本節で記録化。

**規律**:
- Application 作成直後に sidebar `アプリ認証` を click しない (= 個人 bot 用途では用無し、 ⚠️ で動揺するだけ)
- Token 発行は sidebar **`Bot`** (= `OAuth2` の 1 つ下) に直行
- もし誤って `アプリ認証` page を開いて ⚠️ が並んでも、 そのまま閉じて `Bot` に移動して OK

## 関連

- `identity-in-config.md`: Discord user ID 等を config に書くときの PII レイヤ判定
- `mcp.md`: MCP 経由の Discord 連携を組む場合 (現状は Discord 用の標準 MCP がないため Bot Token + curl/SDK の直接 API call が一般的)
