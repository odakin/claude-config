# シェルの多バイト文字 (UTF-8) 切り詰め gotchas

**読むタイミング**: shell script で日本語等の**非 ASCII text を切り詰め / 部分抽出**する時 (= 通知本文・ログ・サマリの短縮、ファイル名生成 等)。または **macOS 通知 (osascript) や CLI 出力が文字化けして読めない**症状の診断時。

## 原則: byte 単位の文字列操作は多バイト文字を割る

UTF-8 では日本語 1 文字 = 3 バイト、絵文字 = 4 バイト。**byte 単位で切る操作は多バイト境界を無視して文字の途中で割り、invalid UTF-8 (壊れた byte 列) を生む。** 非 ASCII を含み得る text は**必ず文字単位で**切ること。

### byte 単位で切ってしまう代表的な操作 (= 罠)

| 操作 | 挙動 | 安全な代替 |
|---|---|---|
| `cut -c1-N` | **macOS / BSD は byte 単位** (GNU cut は UTF-8 locale なら文字単位だが、移植性のため依存しない) | `python3 -c 'import sys;sys.stdout.write(sys.stdin.read()[:N])'` |
| `head -c N` / `dd bs=1 count=N` | 定義上 byte 単位 | 同上 (文字単位 truncate) |
| `${var:0:N}` (bash 部分文字列) | locale が C/POSIX (= `LANG` 空) や bash 3.2 だと byte 単位 | python / perl、または `LC_ALL` を `*.UTF-8` に確実に設定 |
| `awk 'substr(...)'` | BSD awk は多バイト非対応のことが多い | `python3` / `perl -CSD` |

⚠️ **launchd / cron から走る script は `LANG` が空 (= C locale) になりがち** (= user の shell profile を読まないため)。bash の `${var:0:N}` 等が byte 単位に落ちるので、daemon 系 script では特に文字単位の truncate を明示する。

## amplifier: invalid UTF-8 は「末尾だけ」でなく「全体」を化けさせ得る

切り詰めで末尾 1 文字を割っただけでも、その invalid UTF-8 を**下流が再 decode する時に文字列全体を別エンコーディングで解釈し直す**ことがあり、壊れるのは末尾だけでなく**文字列全体**になる。「末尾が少し欠けるだけ」と侮らない。

**実例 (macOS osascript / 2026-06-24 RCA)**: 通知 daemon が finding 1 行を `cut -c1-80` で短縮 → 80 byte 目で日本語を割り invalid UTF-8 に → `osascript -e "display notification \"...\""` がその文字列を valid UTF-8 と認識できず**全体を別エンコーディング (MacRoman 等) で再解釈** → 通知**全体**が文字化けして読めなくなった。修正は `cut -c` → python の文字単位 truncate (= 常に valid UTF-8)。

## 検証: 切り詰め結果が valid UTF-8 か

切り詰めた text を osascript / 通知 / 別プロセスに渡す**前に**、valid UTF-8 か確認する習慣をつける (= 末尾 byte が中途半端な多バイト列なら INVALID):

```bash
printf '%s' "$truncated" | python3 -c "import sys
try: sys.stdin.buffer.read().decode('utf-8'); print('VALID')
except UnicodeDecodeError as e: print('INVALID', e)"
```

## まとめ (reflex)

- shell で非 ASCII を切る時は `cut -c` / `head -c` / byte slice を**使わない** → python の文字単位 truncate。
- 切った結果を別プロセスに渡す前に valid UTF-8 を検証。
- daemon (launchd/cron) は `LANG` 空 = C locale 前提で組む。
