# AskUserQuestion (選択肢 UI) の使い所 — blocking 特性と平文質問との使い分け

**いつ読む**: Claude が user に確認・質問を出そうとする時 (特に AskUserQuestion tool を呼ぶ直前)。

## 機構 fact

- AskUserQuestion は **turn を同期 block する** — user が回答 (or 却下) するまで他の処理が一切進まない。 並行で進められたはずの作業も止まる。
- user が chat 入力欄に text を打ちかけている時に選択肢 dialog が出ると、 **入力中 text が宙に浮く** (= UI 競合。 user は「書きかけの説明」 と「dialog の選択肢」 の二択を強いられる)。
- 選択肢は少数 + 「Other」 固定の構造 = **open-ended な質問・背景説明が要る質問には構造が合わない** (選択肢に押し込むと user の真の回答空間を狭める)。

## 使い分け

| 場面 | 手段 |
|---|---|
| 選択肢が真に enumerable で user 専権の分岐、 かつ回答が無いと作業が全く進められない | AskUserQuestion 可 |
| open-ended な確認 / 背景説明つきの質問 / 複数論点の一括確認 | **平文質問** (= chat 本文に選択肢を番号付きで書く)。 user は自分のペースで答えられ、 Claude は回答不要な部分を並行で進められる |
| 回答が無くても安全に進められる (= reversible で、 採った前提を明示できる) | 質問せず推奨案で進め、 採用した前提を本文に明示する (= 確認質問の乱発は broad 指示の下では逆に規律違反) |

## owner ごとの選好

tool の使用頻度そのものは owner 選好 (= 個人層で override される代表例: 「なるべく使わず平文で」)。 本 doc は全ユーザーで true の**機構 fact と trade-off** のみを SoT として持つ。
