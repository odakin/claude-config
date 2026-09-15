<!-- doc-meta
when: 未知の言語・転写された人名や語の発音を調べるとき / user が「実際に音で聞きたい」と言ったとき
category: harness-core
summary: 発音 evidence ladder (本人・母語話者録音 > 対象言語辞書音声 > 対象言語 TTS > IPA、他言語 TTS は近似のみ) + lossy なローマ字を英語音声へ渡さない + target script を正本から確定 + agent 側 player を user-visible と誤認せず、最終応答に実際に開ける音声 link / file を置く。ウイグル語は scripts/uyghur-tts.py が公開 Idirak/MMS-TTS API を再利用
-->
# 人名・未知言語の発音を音で検証する

人名のローマ字 field は綴りの表示であって、英語の phonetic spelling ではない。
特に別文字体系を中国語式・英語式に転写した形は、母音・子音・音節境界を一意に戻せない。
**ローマ字を macOS `say` の英語 voice へ渡して鳴った音は、その言語の発音 evidence ではない。**

表記の復元・正本 source の優先順位は [`name-rendering.md`](name-rendering.md) が所有する。
本 file は、表記を確定した後の **発音 evidence・音声生成・user への提示**を所有する。
長文の音声校正は [`tts-review.md`](tts-review.md) が別に所有する。

## <a id="pronunciation-evidence-ladder"></a>発音 evidence ladder

上から順に探し、見つかった段と限界を明記する。

1. **本人の録音・本人の自己申告** — その人名の読みの正本。
2. **母語話者による同じ名前・同じ語の録音** — 対象言語の辞書・発音集・講演自己紹介等。話者・方言が違う限界は残る。
3. **対象言語専用 TTS** — 文字列から対象言語の音韻で合成する。実音を聞くためには使えるが、本人の読みを確定したとは言わない。
4. **対象言語の辞書・文法に基づく IPA** — 音素と音節を説明できるが、音声そのものではない。
5. **近縁言語・英語・日本語 TTS** — 最後の近似。対象言語の実発音として提示しない。

「音を出せた」と「正しい発音を得た」は別の postcondition。段 5 を即座に鳴らすより、
対象言語・native script・段 1〜4 の有無を先に確かめる。

## <a id="target-script-before-audio"></a>音声化の前に target script を確定する

1. 入力の言語と転写規則を同定する。見た目が Latin alphabet でも英語名とは限らない。
2. 本人・所属機関・本人の出版物・対象言語辞書の順で native script を探す。
3. 見つからない native script をローマ字から推測で作らない。候補を生成した場合は候補と明示し、本人の表記と扱わない。
4. 姓名順は元 source の field と本人の用法を保つ。音声化の都合で並べ替えない。
5. TTS へは、確定した target script をそのまま渡す。ローマ字の各綴りを英語風の音節に分解して渡さない。

同じ Arabic script でも言語ごとに字価が違う。Arabic voice に Uyghur text を渡す等、
「文字が読める voice」を「言語が合う voice」の代用にしない。

## <a id="language-native-tts"></a>対象言語 TTS の検収

- サービスが対象言語を明示し、入力 script を正しく検出・正規化したことを読む。
- 生成 response の normalized text が入力と意図せず変わっていないか確認する。
- 可能なら単語単体と fullname の両方を生成する。連結時の強勢・間・同化は単語音声の連結では再現できない。
- 合成音声は「対象言語 TTS」と呼び、「母語話者の録音」「本人の発音」と呼ばない。
- 第三者サービスへ text を送る。user がその送信を依頼・許可した範囲だけにし、秘密・未公開文書・scope 外の個人情報を渡さない。

## <a id="uyghur-tts-route"></a>ウイグル語: Idirak/MMS-TTS の API 経路

公開 web client [Idirak Uyghur TTS](https://tts.idirak.com/) は、ウイグル語の Arabic / Latin / Cyrillic script を受け、
`https://uyghurai-uyghurai-tts.hf.space/tts/speak` へ JSON を送る。2026-09-15 に公開 client bundle と非個人名の
挨拶文で確認した request field は `text` / `voice` / `speed` / `noiseScale`、既定は
`voice=default` / `speed=1.0` / `noiseScale=0.667`。response は `audioUrl` / `normalizedText` / `format` 等を返す。

再利用実装は [`scripts/uyghur-tts.py`](../scripts/uyghur-tts.py)。標準 library のみで、既定は
生成された HTTPS 音声 URL を 1 行で返す。WAV 保存は明示 `--output` のときだけで、既存 file は
`--force` なしに上書きしない。

```bash
python3 scripts/uyghur-tts.py "ياخشىمۇسىز"
```

text を shell history / process list に残したくない場合は stdin を使う。

```bash
printf '%s\n' 'ياخشىمۇسىز' | python3 scripts/uyghur-tts.py
```

送信前に payload だけ確認する場合:

```bash
python3 scripts/uyghur-tts.py "ياخشىمۇسىز" --dry-run --json
```

API・voice は第三者の現在状態であり、恒久仕様ではない。失敗時は web client の現行 bundle / request を再確認し、
古い endpoint を推測で増やさない。生成 URL は一時 deliverable であって、SESSION や人名 SoT に UUID を保存しない。

## <a id="audio-delivery-surface"></a>agent 側で鳴った音と user に届いた音を分ける

browser / computer-use の accessibility tree に player が現れ、agent 側で `play` 状態になっても、
**user の Codex 画面に player が提示された証拠にはならない**。`markDeliverable`、side pane の表示、
スクリーンショット上のボタンも、user が同じ surface を見ていることを単独では証明しない。

user が「音を聞きたい」と言ったときの delivery postcondition:

1. 対象言語の音声を生成できた。
2. 最終応答に、user が実際に開ける **直接音声 link** または app が描画できる **local audio file** を置いた。
3. 「再生ボタンが見える」とは、user-visible surface で確認できた時だけ言う。tool 側 screenshot から推測しない。
4. pane が見えない・raw audio page が crash する場合は、同じ操作を繰り返さず通常の Markdown link に縮退する。

この提示面の一般則は [`mid-turn-text-visibility.md#tool-side-media-not-user-visible`](mid-turn-text-visibility.md#tool-side-media-not-user-visible)、
経路を一度作って自動発見面へ載せる責務は [`machine-route-first.md#build-the-route-first`](machine-route-first.md#build-the-route-first) が正本。

## <a id="pronunciation-closure"></a>報告の書き方

短く次の 3 点を分ける。

- **確認した表記**: native script と source class。
- **得た音**: 本人録音 / 母語話者録音 / 対象言語 TTS / IPA / 近似のどれか。
- **未確定部分**: 方言・姓名順・本人固有の読み等。

対象言語 TTS が生成できても、「本人の正確な発音を確認済み」とは閉じない。
