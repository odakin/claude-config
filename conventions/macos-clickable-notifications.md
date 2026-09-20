<!-- doc-meta
when: script や定期ジョブから macOS 通知を出す前 + 出している通知をクリックしても何も起きない / 関係ないアプリが開くと気づいたとき + 通知を出すアプリを作り直す前 + 複数の source から集めた finding の 1 行を通知本文に選ぶとき
category: macos
summary: osascript の display notification はスクリプトエディタの通知になり、クリックしても空の書類選択ダイアログが開くだけで本文の 1 行から先に進めない。自前の applet から投稿して click 先を持たせる recipe (queue file で投稿と click を分ける / 投稿直後に終了すると配送されない / 新しいアプリは許可を出すまで通知センターに溜まるだけ / ad-hoc 署名の rebuild で許可が消える / 通知本文は入力順でなく重大度で選ぶ)
-->
# macOS 通知を「押して役に立つ」ものにする

**いつ読むか**: script や定期ジョブから macOS 通知を出す前 + 出している通知をクリックしても
何も起きない / 関係ないアプリが開くと気づいた時。

## <a id="osascript-notifications-are-unclickable"></a>`osascript` の通知は押せない

`osascript -e 'display notification ...'` は最短だが、**通知の持ち主がスクリプトエディタになる**。
macOS の通知のクリックは「投稿したアプリを activate する」という動作しか持たないので、
押すとスクリプトエディタが前面に出て、空の書類選択ダイアログが開くだけになる。
通知本文の 1 行から先に進む手段が無い (実測: 期限の一覧を抱えた通知を押しても、
空の書類選択ダイアログが開くだけだった)。

`terminal-notifier` の `-execute` は click に任意のコマンドを割り当てられるが、
別途 install が要り、これも「そのツールの通知」として登録される。

**規則**: 人に行動してほしい通知は、**自前の小さなアプリから投稿する**。
そのアプリの起動処理が、押された時に開くもの (一覧・レポート・該当ファイル) を開く。

## <a id="applet-recipe"></a>applet の作り方 (AppleScript 1 本で足りる)

投稿と click を同じ applet の `on run` で捌く。**queue file の有無**で 2 つの入口を分ける:

- queue がある = 投稿側 (`open -a` で起こされた) → 読んで `display notification` し、queue を消す
- queue が無い = 人が通知を押した → 開きたいものを開く

```applescript
on run
	my dispatch()
end run
on reopen        -- 投稿直後 (まだ生きている) に押された場合
	my dispatch()
end reopen
```

build は `osacompile -o X.app X.applescript` → `plutil -replace CFBundleIdentifier` →
`LSUIElement` を true (Dock に出さない。`LSBackgroundOnly` にすると通知を出せなくなる) →
`codesign -f -s -` → `~/Applications/` へ ditto → `lsregister -f`。

## <a id="post-then-exit-drops-the-notification"></a>投稿直後に終了すると通知は捨てられる

stay-open でない applet は `run` が終わった瞬間に終了する。`display notification` の直後に
終了すると通知は配送されない (実測: 0.14 秒で終了し、通知設定にも登録されなかった)。
**投稿のあとに `delay 3` を入れてプロセスを生かす**。

## <a id="new-app-is-silent-until-allowed"></a>新しいアプリは許可を出すまで黙っている

初めて通知を出すアプリは `notificationsAllowed: false` の状態で登録される。
このとき通知は**通知センターには溜まるが、バナーも音も出ない**。ログにはこう出る:

```
usernoted: ... successfully processed by pipeline, scheduled for delivery.
NotificationCenter: Should not play sound for <id>: ... notificationsAllowed: false
```

配送されているので「投稿は成功」に見えるが、人には届いていない。**切替えた瞬間に
リマインダーが黙って消える**ので:

1. 切替えは**安全弁つき**にする (許可を確認するまでは旧経路で鳴らす)
2. 「システム設定 > 通知」でそのアプリを許可してもらう
3. 実際にバナーが出せる状態かを確認してから、新経路に切替える

⚠️ **3 を人の宣言 (「許可したよ」「切替えコマンドを打った」) で代用しない**。
切替えコマンド自身が 1 通投げて log を読み、`notificationsAllowed: false` なら**切替えを断る**。
実測: 許可が入る前に切替えが通ってしまい、その間の通知は通知センターに溜まるだけだった
(= 安全弁を人の記憶に載せると、載せた意味が消える)。

確認の経路 (= 推測しない):

```bash
log stream --style compact --predicate 'process == "usernoted" OR process == "NotificationCenter"'
```

`defaults read com.apple.ncprefs apps | grep <bundle-id>` は**遅れて反映される**ので、
そこに無いことを「配送されていない」の根拠にしない (実測で false negative)。

## <a id="rebuild-and-identity"></a>何を変えると許可が消えるか (通知と TCC で違う)

| 変えたもの | 通知の許可 | TCC (画面収録・アプリ管理等) |
|---|---|---|
| 中身だけ作り直す (bundle id 同じ、ad-hoc 署名) | **残る** (実測) | 消える (cdhash が変わる) |
| bundle id を変える | **消える** (= 別のアプリ) | 消える |

通知の許可は **bundle id で引かれる**ので、ad-hoc 署名の cdhash が変わっても残る。
一方 TCC は cdhash 基準なので、同じ rebuild で消える
([`macos-tahoe-wallpaper.md#adhoc-rebuild-loses-tcc`](macos-tahoe-wallpaper.md#adhoc-rebuild-loses-tcc))。

∴ **bundle id は最初に決めて、後から変えない**。中身の変更は自由にしてよい。
⚠️ この 2 つを「どちらも rebuild で消える」と一括りにしないこと — TCC の経験則を通知へ
そのまま延ばすと、変更のたびに人へ許可を求める無駄な手順が付く (実測で否定された)。

## <a id="click-target-contract"></a>click 先は投稿側の層が決める

applet に行き先を焼き込むと、そのアプリが 1 つの用途に縛られる。**applet は
`~/.claude/notify-click.sh` を `/bin/sh` で実行するだけ**にして、中身は使う側が置く
(installer が symlink を張る)。無ければ既定の場所を開くだけにする。

⚠️ その script の `PATH` は `/usr/bin:/bin` しかない。python 等を使うなら script 側で張る。

## <a id="click-target-page-design"></a>click 先の頁は「読む文書」でなく「見る盤面」

通知を押した人は読みに来たのではなく、**今すぐ動くものがあるか**を見に来ている。
元データが行で書かれた台帳でも、それを `<pre>` でそのまま流すと、目で探す仕事が残る。

- **一番大事な量を 1 カラムに固定する。** 期限の盤面ならそれは残り日数。等幅 +
  `font-variant-numeric: tabular-nums` で右揃えにすると、符号と桁が読む前に目に入る。
- **全部をカードにしない。** 重大度は行の左端の細い帯で出す。border・角丸・影を
  すべてのブロックに配ると階層が消え、どれが急ぐのか分からなくなる。
- **意味色とアクセント色を分ける。** 超過・接近は意味色、アクセントは押せるものに使う。
- **解析できなかった行は生のまま出す。** 台帳の書式は変わる。読めない行を落とす設計は、
  黙って情報を消す。パースは「読めたら表、読めなければ原文」の二段にする。
- **見出しと項目は字下げで分かる。** 台帳の多くは字下げで階層を書いているので、
  それを構造として読めば、見出しを別に用意しなくてよい。
- **外部 file を参照しない。** `file://` やオフラインで開かれる前提の頁なので、
  フォントも script も埋め込む。和文はシステムのゴシックで十分に読める。

実装 = [`scripts/lib/ledger_page.py`](../scripts/lib/ledger_page.py)
(`parse_item` で 1 行を marker / 残り日数 / 本文 / 出所 に分け、`render_page` で 1 枚にする。
合成データの selftest つき)。呼ぶ側は「どの台帳をどの順で、どの節に置くか」だけを持つ。

## <a id="notification-body-must-be-ranked"></a>通知本文の 1 行は「選ぶ」もの

通知に入るのは 1〜2 行しかない。複数の source から finding を集めて出すとき、
`cat *.txt | head -1` のような**入力順まかせの 1 行目**を本文にしてはいけない —
glob はアルファベット順なので、たまたま先頭に来た source の、たまたま最初の行が出る。
実測: 最も急ぐ finding が別の source にあるのに、本文は無関係な台帳の定期点検の行に
なっていた。**重大度 → source の優先順**で並べてから先頭を取る。
