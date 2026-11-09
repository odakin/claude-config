# Codex app の数式表示を確かめる見本

規則と確認範囲の正本は [チャットの数式表示](../../conventions/chat-math-rendering.md#codex-app-katex)。以下を会話の返事として出し、読む画面で比較する。この Markdown ファイルのプレビューだけでは、会話本文の描画を確かめたことにならない。

文中: 条件 \(a>0\) のもとで、ガウス積分の値は \(\sqrt{\frac{\pi}{a}}\) です。波束の幅を \(\sigma_x\) とすると、不確定性関係は \(\sigma_x\sigma_p\geq\frac{\hbar}{2}\) と書けます。

A: 別行の角括弧区切りと `aligned`

\[
\begin{aligned}
I(a) &= \int_{-\infty}^{\infty} e^{-a x^2}\,dx \\
     &= \sqrt{\frac{\pi}{a}}
\end{aligned}
\]

B: 元テキストを一行にする

\[\begin{aligned} I(a) &= \int_{-\infty}^{\infty} e^{-a x^2}\,dx \\ &= \sqrt{\frac{\pi}{a}} \end{aligned}\]

C: 別行の二重ドル区切りと `aligned`

$$
\begin{aligned}
I(a) &= \int_{-\infty}^{\infty} e^{-a x^2}\,dx \\
     &= \sqrt{\frac{\pi}{a}}
\end{aligned}
$$

D: `math` 指定の fenced block

```math
\begin{aligned}
I(a) &= \int_{-\infty}^{\infty} e^{-a x^2}\,dx \\
     &= \sqrt{\frac{\pi}{a}}
\end{aligned}
```
