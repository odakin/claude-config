<!-- doc-meta
when: 長文ドキュメント (提案書・原稿・メール draft 等) を音声読み上げで校正したいとき
category: office
summary: macOS `say` による長文の音声読み上げ校正 (= 日本語 voice の選択・WPM・数式記号 / 英略語の読み替え前処理・「聞いて初めてバレる不自然な日本語」 の self-review 用途。 office-automation.md から 2026-07-10 切り出し)
-->
# 長文を音声で校正する (macOS `say` で TTS review)

**いつ読む**: 長文 (提案書・論文和文・原稿・重要メール draft 等) を書き終えて、 視覚読み以外の校正 pass をかけたいとき。

> 起源は 2026-05 の研究費応募書類 (= 様式 xlsx の fill 作業、 [`office-automation.md`](office-automation.md))。 音声校正自体は form fill と独立に任意の長文に効くため、 2026-07-10 に単独 file へ切り出した。

## <a id="tts-review"></a>基本形

長文 (= 6 セクション数千字) を視覚読みで疲れた時、 macOS 標準の `say` で TTS して耳で確認。

```bash
say -v "Kyoko (Enhanced)" -r 200 "本研究の目的は..."
```

- 日本語音声: `Kyoko` (女性) / `Otoya` (男性)、 各 Enhanced 版が高音質
- `-r 200` は WPM (Words Per Minute)、 200 が読み上げに自然なペース
- 長文を sections で区切って速報生成: `bash` script で `say` を順次呼ぶと中断 (`killall say`) しやすい
- 数式記号や英略語 (LLM、 H₀、 EJP-C 等) は読みづらいので script で読みやすく書き換え (例: `H₀` → `エイチゼロ`)

提案書 self-review 用途では、 自分で書いた文章の「不自然な日本語」 が聞いて初めてバレることが多い。
