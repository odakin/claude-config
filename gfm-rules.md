# GFM Markdown Rules for CJK Bold Text

How to fix `**bold**` rendering failures on GFM platforms (GitHub, Zenn, etc.) when using CJK (Chinese/Japanese/Korean) text.

## `**` Delimiter Rules

- **Opening `**` (left-flanking)**: Must be followed by a non-whitespace character. If followed by punctuation, must be preceded by whitespace or punctuation.
- **Closing `**` (right-flanking)**: Must be preceded by a non-whitespace character. If preceded by punctuation, must be followed by whitespace or punctuation.

## Common CJK Breakage Patterns

| Pattern | Problem | Fix |
|---|---|---|
| `は**「bold」**` | Opening `**` followed by punctuation, preceded by non-punctuation → left-flanking fails | `は **「bold」**` (add space before) |
| `（H3）**が` | Closing `**` preceded by punctuation, followed by non-punctuation → right-flanking fails | `（H3）** が` (add space after) |
| `**bold **next` | Closing `**` preceded by space → right-flanking fails | `**bold**next` (remove space) |

## Notes

- Only add spaces **before the opening `**`**, never before the closing one
- CJK characters are treated as "regular characters" in GFM. When closing `**` is preceded by fullwidth punctuation and followed by CJK, add a space after closing `**`
- Never nest `**` inside `**` — this creates `****` which breaks rendering

---

# GFM Markdown ルール（日本語 bold 対策）

zenn.dev 等の GFM プラットフォームで日本語テキストの `**bold**` が壊れるケースへの対処。

## `**` delimiter ルール

- **開き `**`（left-flanking）**: 直後が非空白。直後が句読点なら直前が空白か句読点。
- **閉じ `**`（right-flanking）**: 直前が非空白。直前が句読点なら直後が空白か句読点。

## 日本語で壊れるパターンと対処

| パターン | 問題 | 対処 |
|---|---|---|
| `は**「bold」**` | 開き直後が句読点、直前が非句読 → left-flanking 不成立 | `は **「bold」**`（前にスペース） |
| `（H3）**が` | 閉じ直前が句読点、直後が非句読 → right-flanking 不成立 | `（H3）** が`（後にスペース） |
| `**bold **next` | 閉じ直前がスペース → right-flanking 不成立 | `**bold**next`（スペース除去） |

## 注意事項

- スペース追加は **開き `**` の前** のみ。閉じの前にスペースを入れると壊れる
- CJK 文字は GFM 上「通常文字」扱い。閉じ `**` 直前が全角句読点で直後が CJK の場合、閉じの後にスペースを入れる
- `**...**` 内にさらに `**` を追加しない（`****` が発生して壊れる）
