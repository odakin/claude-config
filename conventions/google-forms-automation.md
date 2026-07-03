# Google Forms の構造解析と prefill 自動化の限界

Google Forms を programmatic に扱う (= 構造解析、 prefill URL 生成、 submit 自動化) ときの実装パターンと、 失敗する境界を documented する。

## FB_PUBLIC_LOAD_DATA_ HTML scrape で form 構造取得

Google Forms の `viewform` ページは、 form 全体のメタデータと questions の構造を `<script>` 内の **JavaScript 変数 `FB_PUBLIC_LOAD_DATA_`** に JSON 配列として埋め込んでいる。 これを scrape すれば **anonymous fetch だけで form 構造が取得可能** (= Workspace-restricted form でも viewform page 自体は anonymous でも 200 OK で返る、 submission のみ auth 要)。

### Forms API との違い

| | Forms API | HTML scrape |
|---|---|---|
| 取得対象 | form metadata + items | 同 + 内部 questionId と表示順 |
| **entry id (= prefill URL の `entry.<N>`)** | **取得不可** (= API の questionId とは別 mapping) | **取得可** (= `FB_PUBLIC_LOAD_DATA_` 内に raw 形式) |
| Auth | OAuth `forms.body.readonly` scope + form 所有者/編集者権限要 | 不要 (= anonymous fetch、 ただし auth wall page が返る form もある) |
| 適用範囲 | 自分が owner / editor の form のみ | 公開済 form 全般 (respondent からも見える) |

**重要**: Forms API は **prefill URL に使う `entry.<N>` を返さない**。 prefill 自動化のためには HTML scrape が事実上唯一の path。

### Parser パターン (Python)

```python
import urllib.request, re, json

def fetch_form_structure(view_url: str) -> dict:
    """Forms viewform URL → 構造化された fields list"""
    req = urllib.request.Request(view_url, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="replace")
    m = re.search(r"FB_PUBLIC_LOAD_DATA_ ?= ?(\[.*?\]);</script>", html, re.DOTALL)
    if not m:
        raise ValueError("FB_PUBLIC_LOAD_DATA_ not found (= login wall or not a form)")
    data = json.loads(m.group(1))
    # data[1] = form meta、 data[1][1] = items array
    items = data[1][1] if len(data) > 1 and isinstance(data[1], list) and len(data[1]) > 1 else []
    result = []
    for f in items:
        if not isinstance(f, list):
            continue
        label = f[1] if len(f) > 1 else ""
        ftype = f[3] if len(f) > 3 else None
        sub = f[4] if len(f) > 4 and isinstance(f[4], list) else []
        entry_ids = []
        options = []
        required = False
        for s in sub:
            if isinstance(s, list) and len(s) > 0 and isinstance(s[0], int):
                entry_ids.append(s[0])  # ← prefill URL の entry.<N> の N
                if len(s) > 2 and s[2]:
                    required = True
                if len(s) > 1 and isinstance(s[1], list):
                    for o in s[1]:
                        if isinstance(o, list) and len(o) > 0:
                            options.append(o[0])  # ← radio/dropdown の表示ラベル
        result.append({
            "label": label,
            "type": ftype,  # 0=短文 / 1=段落 / 2=ラジオ / 3=プルダウン / 4=チェック / 5=スケール / 6=セクション / 8=区切 / 9=日付 / 10=時刻
            "entry_ids": entry_ids,
            "options": options,
            "required": required,
        })
    return {"items": result, "form_title": data[1][8] if len(data[1]) > 8 else ""}
```

### `FB_PUBLIC_LOAD_DATA_` 構造 (= field 配列の semantics)

各 question item の配列 layout (= reverse engineered):

```
[internal_id, label, description_or_null, type, sub, ...]
```

- `internal_id` (int): question 内部 ID (= questionId と一致するかは未確認)
- `label` (str): question text
- `description_or_null` (str | null): 補足説明
- `type` (int): 0=短文 / 1=段落 / 2=ラジオ / 3=プルダウン / 4=チェック / 5=スケール / 8=区切 / 9=日付 / 10=時刻
- `sub` (array of subarrays): question 構成要素

`sub[i]` の layout:

```
[entry_id, options_or_null, required_bool, ...]
```

- `entry_id` (int): **prefill URL の `entry.<N>` の N**
- `options_or_null`: radio/dropdown/checkbox の選択肢
  - 各 option = `[label_text, ...]`
- `required_bool`: bool / 1 で必須

## Prefill URL の限界

`?usp=pp_url&entry.<N>=<value>` パターンの prefill URL は **section navigation を持つ multi-page form では 1 ページ目の field しか正しく適用されない**。

### 失敗パターン

実測 (= 2026-05-15、 複数 section + radio 分岐を持つ Google Form):
- 1 ページ目 (= 在籍区分 等) は prefill 値が selected で表示される ✓
- 「次へ」 で 2 ページ目に移ると、 prefill 対象だった field が **未選択** (= blank radio / empty dropdown)
- 「以前の下書き」 dialog (= Google Forms の auto-save) が prefill state と競合する場合あり

### 原因仮説

- Google Forms の section navigation で URL params が破棄される (= 内部 state 管理)
- prefill は initial DOM 描画時のみ適用、 subsequent section へは propagate しない設計
- 「以前の下書き」 機能と prefill が同 form 同 user 内で衝突

### 単一 section form では動く

- single-section form (= 区切なし) ではすべての field の prefill が initial 描画で適用される
- 多 section + 分岐 form では「現在表示中の section の field」 のみが prefill 適用

### Auto-collected email field は prefill 不可

「回答者のメールアドレスを収集する」 設定 ON の form では、 email field は通常の `entry.<N>` ではなく **special field** (= form structure の `meta` slot に分類、 通常の `data[1][1]` items array に出てこない)。 prefill URL からは制御できない。

## Submit 自動化の境界

Google Forms API は **response の create をサポートしない** (= read only)。 submission 自動化の path:

### Path 1: 直接 POST to formResponse endpoint

```
POST https://docs.google.com/forms/d/e/<publish_id>/formResponse
Body: entry.<N>=value&entry.<M>=value&...
```

- 公開 form (= 全員回答可) なら anonymous で POST 可能
- **Workspace-restricted form** (= 特定 domain の user のみ回答可) では **session cookie が必須** (= OAuth Bearer は通用しない、 Google web auth は cookie ベース)
- `browser_cookie3` 等で Brave / Chrome から cookie 抽出 → `requests.Session()` に注入 → POST、 が experimental path
- Cookie 期限は数時間〜数日、 cron での完全自動化は cookie refresh 機構が必要で fragile

### Path 2: Selenium / Playwright で browser 駆動

- user session を Brave profile 共有で再利用、 form を fill & submit
- 多 section form の section 遷移も自動化可
- setup cost 中程度、 確実性高い

### Path 3: Manual + prefill URL (= 単 section 限定)

- 単 section form なら prefill URL で fill 完了 → user は 1 click submit
- 多 section form は手動入力に fallback

## 実装パターン (= Phase 階段)

### Phase A: 構造把握のみ
- FB_PUBLIC_LOAD_DATA_ scrape で entry id 抽出
- user に「どの field に何を入れるか」 を可視化

### Phase B: prefill URL 生成 (= 単 section 限定)
- entry id + value dict → `?usp=pp_url&entry.<N>=...` 構築
- user 確認後 Brave で開いて submit

### Phase C: 完全自動化 (= 多 section / cookie 必要)
- Selenium / Playwright + cookie 抽出
- experimental、 fragile (cookie 期限管理)

## <a id="respondent-side-constraints"></a>回答者 (respondent) 側の提出制約

form を「作る・解析する」 側でなく「**提出する**」 側の制約。 file 添付付きの提出 workflow (= 様式 xlsx/docx を作って form に upload する類) を支援する時に効く。

### 観測済みの制約 4 点

1. **file-upload 質問付き form は Google ログイン強制 + 多くは Workspace domain 縛り**: form 所有 organization の account でしか回答できない設定が一般的で、 回答した account が form 側に記録される。 → **普段のメール account と提出 account が別になりうる** — どの account で提出したかを自分の記録側に残す (= 受領 mail・回答控えの届く場所が変わる)。
2. **回答回数制限 (= limit to 1 response) の form は再回答不可**: 提出後の追加・訂正は form でなく**別経路 (= 担当者宛メール等) に切り替わる** — 主催側からその指示が来るのが典型。 「form に出し直せばよい」 を前提に workflow を組まない。
3. **提出した file は form からは回収できない** (= form は提出物を返さない)。 → **提出版 snapshot を final 名でリポに保存してから提出する**。 提出後に「何を出したか」 を復元できる唯一の経路で、 2. (再回答不可) + 訂正メール経路と組み合わさると控えの有無が直接効く。
4. **受領 mail の「回答を編集」 link は form 設定依存**: あれば後から編集可、 無ければ 2. の別経路のみ。 提出直後に受領 mail と link の有無を確認して記録する。

### reflex (= 提出前 3 点 checklist)

- [ ] 提出版 file を final 名 (= `_draft` 抜き) でリポに保存したか
- [ ] どの account で提出するか (= domain 縛りの有無) を確認したか
- [ ] 提出後、 受領 mail と「回答を編集」 link の有無を記録したか

origin: 2026-07、 institutional compliance form (= 誓約チェック + 計画書 xlsx 添付) で 4 点を 1 事例で全部観測 — domain 縛りで通常メール account と別 account 提出 / 回答回数制限により追加提出は「担当者宛メールで」 の指示 / 提出版 xlsx はリポ保存済で控え確保。

## 関連

- Forms API 公式 doc (= form 構造 read 用、 ただし entry id 取得不可): https://developers.google.com/forms/api
- prefill URL spec (= 公式): https://support.google.com/docs/answer/2839588

## How to apply

- form 自動化を試す前に **section の数を確認** (= FB_PUBLIC_LOAD_DATA_ で `type=8` (区切) の count)
- 単 section form なら prefill URL で fully automate 可能
- 多 section form は **prefill URL の信用度を下げる** (= 1 ページ目のみ動作前提) + fallback として user に手動入力経路を案内
- Form の branching ロジック (= radio 選択で section jump、 「他にあるか」 で chain) は **schema から事前に読み取る**: dropdown 「いいえ」 で form 終了、 等の short-path を識別すれば過剰な draft 生成を回避可能
