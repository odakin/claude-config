<!-- doc-meta
when: shell で多バイト文字列を truncate・加工するとき + **grep / sed の角括弧に非 ASCII を書くとき**
category: infra
summary: シェルの多バイト UTF-8 切り詰め gotchas (= cut -c/head -c/bash 部分文字列は byte 単位で多バイト文字を割り invalid UTF-8 → osascript 等下流で文字列全体が文字化け、 launchd は LANG 空で C locale ゆえ特に注意、 安全策=python 文字単位 truncate + valid UTF-8 検証 1-liner、 2026-06-24 osascript 通知 RCA)
-->
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

## <a id="bracket-expression-c-locale"></a>`grep` / `sed` の角括弧に非 ASCII を入れると、C locale では byte の集合になる (2026-09-13)

`LANG` と `LC_ALL` が空の shell では、`[^。]` は「。」という 1 文字の否定ではなく、その UTF-8 表現の 3 byte (`E3 80 82`) それぞれの否定になる。ひらがな・カタカナの UTF-8 はどれも `E3` で始まるので、`[^。]*。` は最初の「。」に届く前の仮名で止まり、**一致しないのに error も出さない**。Claude Code の Bash tool も `LANG` と `LC_ALL` が空だった (desktop app、2026-09-13 実測)。

- 実例: 挿入した一文を `/usr/bin/grep -o '…[^。]*。'` で表示してから commit する `&&` chain を書いた。表示が 0 件で exit 1 になって commit は走らず、`;` の後ろに置いた検査の出力だけが出た。同じ pattern は先頭に `LC_ALL=en_US.UTF-8` を付けると一致した。
- 書き方: 非 ASCII を含む pattern は python で書くか、`LC_ALL=en_US.UTF-8` を明示する。表示のための grep を gate の chain に入れない ([shell-env.md#test-gate-no-pipe](shell-env.md#test-gate-no-pipe))。

## まとめ (reflex)

- shell で非 ASCII を切る時は `cut -c` / `head -c` / byte slice を**使わない** → python の文字単位 truncate。
- 切った結果を別プロセスに渡す前に valid UTF-8 を検証。
- daemon (launchd/cron) は `LANG` 空 = C locale 前提で組む。
- `grep` / `sed` の `[...]` に非 ASCII を入れない (C locale では byte の集合)。Claude Code の Bash tool も `LANG` 空の前提で書く。

## <a id="prose-args-quoting"></a>自然文を CLI 引数で渡すときの quoting — backtick は double quote の中で消える (2026-09)

長い自然文 (投稿の summary・commit message・issue 本文) を shell 経由で渡すとき、**double quote の中では `` `…` `` と `$…` と (対話 shell の) `!` が展開される**。`` `2026-09-07-foo` `` のような ID を強調のつもりで書くと、shell がそれを command として実行し (「command not found」)、引数からは**空文字**になって届く。届いた側では「thread 名が消えている」以外に痕跡が無い。

- **規律**: 自然文の引数は **single quote** で囲む (single quote の中は一切展開されない)。文中に `'` が要るなら heredoc (`<<'EOF'`) か file 経由で渡す。
- **痕跡**: 消えた token の場所には空の backtick 対 ` `` ` が残る。受け側の tool は**この指紋を拒否**して「引用符を直して再送」と言える (= 記録が immutable な board で事故を止めた実例、agent-board の writer gate)。
- **痕跡が残らない形もある** (2026-09-13 実測、zsh): double quote の中の `` `x` `` は backtick ごと消えて空白だけが残り、`` ``x`` `` は中身だけが残る。どちらも空の backtick の対は残らないので、指紋で拒否する受け側もこの形は捕まえない。同日、commit message に書いた `` `~` `` が home dir の実行に化けて消え、`permission denied` が 1 行出ただけで commit と push は通った (履歴には「latex.md:  の無い」 が残った)。**再発 2 件目**。3 件目が出たら、`git commit -m` などの double quote の引数に backtick があれば止める PreToolUse guard を足す (校正の道具 = [`scripts/calibrate-bash-command-pattern.py`](../scripts/calibrate-bash-command-pattern.py))。それまでは commit message を `-F <file>` で渡す。
- 関連: 文面を user が貼る側の規律は [`paste-destined-plain-text.md`](paste-destined-plain-text.md)、tool 入力に書いた文は user に見えていない = [`mid-turn-text-visibility.md`](mid-turn-text-visibility.md)。

