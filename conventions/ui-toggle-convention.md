<!-- doc-meta
when: UI panel 内の toggle group を設計するとき
category: web
summary: UI panel 内 toggle group の default 側統一ルール (slider 位置 + bright label を panel scope で揃える)
-->
# Toggle switch のラベル配置 convention

UI panel に複数の toggle switch (= 左 label / slider / 右 label の構造) を並べるとき、 panel 内
で **default 状態の側 (= slider 位置 + bright label)** を統一する。

## ルール

- panel 内の toggle 群で **default state を全て同じ側に**揃える (= 例えば全部「default = 右」
  に統一)
- 個別 toggle の意味と無関係に、 panel scope で default 側を 1 方向に固定
- toggle の label は default を必ず特定側 (= 右に固定するか左に固定するか panel ごとに決める)

## Why

panel 内で toggle 群の **slider 位置と bright label 側**が揃っていると、 user は「default 状態
かどうか」 を panel 全体で 1 種類のパターン認識で把握できる。 toggle ごとに default 側がバラバラ
だと、 各 toggle の label を個別に読まないと state が取れず認知負荷が高い。

逆に default 側が揃っていれば「全部 default 状態 = 全部右に slider」 という単純な視覚パターンで
panel 全体の state が即読み取れる。

## 実装パターン (React + 3-segment toggle)

ToggleSwitch の `checked` semantics は「右 label が active」 を意味する設計が一般的:

```tsx
<ToggleSwitch
  checked={X}
  onChange={...}
  labelLeft="alternate"
  labelRight="default"   // ← default をここに置く
/>
```

`X` が default 状態なら true、 alternate なら false。 `X = !someState` のように boolean を
反転して渡すケースもある (= state は alternate を表す変数だが UI 上は default が右)。

例: 「showPLCSlice (= 通常 false)」 を `checked={!showPLCSlice}` で渡せば、 default = checked=true
= slider 右 = labelRight (= 通常 default の "時空図") が bright。

## How to apply

新規 toggle を panel に足すとき、 まず panel 内既存 toggle の default 側を確認:

1. 既存 toggle の `checked` が default 状態で true / false どちらか確認
2. 既存 default が右側 (= checked=true で knob 右) なら新 toggle も同じ pattern に
3. 必要なら label の左右と `checked` 式を反転 (= `!state` 等) で揃える

panel をまたいだ統一は不要 (= panel ごとに「右 default」 / 「左 default」 のどちらかに揃える、
panel ごとの local convention)。

## 由来

LorentzArena の `ControlPanel` toggle 群で `静止系` / `透視投影` / `2D⇆3D` は default を右
配置していたが、 `時空図 ⇆ PLCスライス` だけ左に配置されていた (= default = 時空図 = checked=false
で slider 左)。 odakin 指摘 「時空図がデフォなんだから時空図を右に書くべき」 (2026-05-07) で
panel 統一に修正。 詳細: [LorentzArena/2+1/DESIGN.md §PLC スライス全面リッチ化 §8](../../LorentzArena/2+1/DESIGN.md)。
