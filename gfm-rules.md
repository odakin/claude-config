# GFM Markdown Rendering Gotchas

GitHub-Flavored-Markdown rendering pitfalls and how to avoid them. Applies anywhere GFM is rendered (GitHub READMEs, issues/PRs, Zenn, chat output, etc.).

## `**bold**` failures with CJK text

How to fix `**bold**` rendering failures on GFM platforms (GitHub, Zenn, etc.) when using CJK (Chinese/Japanese/Korean) text.

### `**` Delimiter Rules

- **Opening `**` (left-flanking)**: Must be followed by a non-whitespace character. If followed by punctuation, must be preceded by whitespace or punctuation.
- **Closing `**` (right-flanking)**: Must be preceded by a non-whitespace character. If preceded by punctuation, must be followed by whitespace or punctuation.

### Common CJK Breakage Patterns

| Pattern | Problem | Fix |
|---|---|---|
| `は**「bold」**` | Opening `**` followed by punctuation, preceded by non-punctuation → left-flanking fails | `は **「bold」**` (add space before) |
| `（H3）**が` | Closing `**` preceded by punctuation, followed by non-punctuation → right-flanking fails | `（H3）** が` (add space after) |
| `**bold **next` | Closing `**` preceded by space → right-flanking fails | `**bold**next` (remove space) |

### Notes

- Only add spaces **before the opening `**`**, never before the closing one
- CJK characters are treated as "regular characters" in GFM. When closing `**` is preceded by fullwidth punctuation and followed by CJK, add a space after closing `**`
- Never nest `**` inside `**` — this creates `****` which breaks rendering

## Don't wrap a bare URL in `**…**` (breaks autolinking)

GFM's autolinker greedily extends a bare URL: if you write `**https://example.com**`, it swallows the trailing `**` (and any text right after it) into the link, turning the whole span into one broken link instead of bold text.

- **Fix**: use the explicit `[label](URL)` link form, e.g. `[Open the page](https://example.com)`. To emphasize, bold the *label* (`[**label**](URL)`), never the URL string itself.
- If you must leave a bare URL, surround it with whitespace and never place `**`, `)`, `。`, or other punctuation directly adjacent to it: `See https://example.com (updated)` works; `**https://example.com**(updated)` does not.

## A newline inside a table cell ends the row

A GFM table row is exactly one line. A newline in the middle of a cell ends the row there, and the following lines render as plain paragraphs after a truncated table (measured: appending an indented continuation paragraph into a long cell broke the table).

- **Fix**: keep each row on one line and use `<br>` for a line break inside a cell. When editing a long cell with a tool, check afterwards that the row is still one line (e.g. print the first characters of the surrounding lines).

---

# GFM Markdown レンダリングの落とし穴

GitHub-Flavored-Markdown のレンダリングではまる箇所と回避法。GFM がレンダーされる場所すべて（GitHub README・issue/PR・Zenn・チャット出力等）に適用される。

## 日本語テキストで `**bold**` が壊れる

zenn.dev 等の GFM プラットフォームで日本語テキストの `**bold**` が壊れるケースへの対処。

### `**` delimiter ルール

- **開き `**`（left-flanking）**: 直後が非空白。直後が句読点なら直前が空白か句読点。
- **閉じ `**`（right-flanking）**: 直前が非空白。直前が句読点なら直後が空白か句読点。

### 日本語で壊れるパターンと対処

| パターン | 問題 | 対処 |
|---|---|---|
| `は**「bold」**` | 開き直後が句読点、直前が非句読 → left-flanking 不成立 | `は **「bold」**`（前にスペース） |
| `（H3）**が` | 閉じ直前が句読点、直後が非句読 → right-flanking 不成立 | `（H3）** が`（後にスペース） |
| `**bold **next` | 閉じ直前がスペース → right-flanking 不成立 | `**bold**next`（スペース除去） |

### 注意事項

- スペース追加は **開き `**` の前** のみ。閉じの前にスペースを入れると壊れる
- CJK 文字は GFM 上「通常文字」扱い。閉じ `**` 直前が全角句読点で直後が CJK の場合、閉じの後にスペースを入れる
- `**...**` 内にさらに `**` を追加しない（`****` が発生して壊れる）

## 裸の URL を `**…**` で囲まない（autolink が壊れる）

GFM の autolinker は裸の URL を貪欲に伸ばす。`**https://example.com**` と書くと、後続の `**`（さらにその直後のテキスト）まで丸ごとリンクに飲み込み、bold ではなく「1 個の壊れたリンク」になる。

- **対処**: 明示的な `[ラベル](URL)` link 形式を使う（例: `[ページを開く](https://example.com)`）。強調したいときは *ラベル側* を bold（`[**ラベル**](URL)`）にし、URL 文字列そのものは `**` で囲まない
- どうしても裸の URL を置くなら前後に空白を入れ、`**`・`）`・`。` 等の記号を直後に密着させない: `https://example.com を参照` は可、`**https://example.com**（更新済み）` は不可

## 表のセルの中で改行しない（行がそこで終わる）

GFM の表の 1 行は、ファイルの 1 行そのもの。セルの途中で改行すると行はそこで終わり、続きの行は切れた表の後ろの普通の段落になる（実測: 長いセルに字下げした続きの段落を書き足して、表が壊れた）。

- **対処**: 1 行は 1 行のまま書き、セルの中の改行は `<br>`。長いセルを道具で書き換えたら、その行がまだ 1 行かを確かめる（前後の行の頭を数文字出すなど）
