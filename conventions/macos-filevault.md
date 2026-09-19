<!-- doc-meta
when: FileVault を入れるか決めるとき + 有効か無効かを判断するとき + 復旧キーの置き場を決めるとき + 復旧キーを画面から書き取ったとき + 無人 routine を走らせる機を選ぶとき
category: macos
summary: FileVault の有無は fdesetup status だけが答え (記憶・toggle の色で判断しない)。 ログイン後は完全に透過なので agent の作業には影響せず、 唯一の差は再起動後ログインまで LaunchAgent が走らないこと。 復旧キーはそれが開けるディスクの中だけに置くと循環する = 別デバイスから辿れる置き場に台帳を作り、 転記は validaterecovery (root 要 = 人の操作) で照合する。 「On なのに鍵が無い」 は静かな穴なので scripts/check-filevault-posture.py で毎回見る
-->
# FileVault — 入れる判断と、 復旧キーの置き場

ディスク暗号化そのものより、 **復旧キーをどこに置くか**で詰む。 鍵が要る場面はその Mac に入れない場面なので、
置き場を間違えると「保管したのに読めない」 が成立する。 しかも平時はそれが見えない。

## <a id="status-is-the-only-answer"></a>有効か無効かは `fdesetup status` だけが答え

```bash
fdesetup status        # → "FileVault is On." / "FileVault is Off."
```

- **記憶で判断しない**。 有効化は一瞬で終わるので、 初期設定で流して通したことを覚えていない側に倒れる (実測)
- **画面の toggle を色で読まない**。 sheet が前面にあると window 全体が減光され、 有効色が灰色に落ちる。
  つまみの左右で読む (= [photographed-document-transcription.md#control-state](photographed-document-transcription.md#control-state))
- 本人の申告と実測が食い違ったら、 **実測の出力をそのまま見せて**判断を渡す

⚠️ Apple Silicon はハードウェア暗号化が常に効いているが、 **FileVault が Off だと鍵が自動でアンロックされる**。
「どうせ暗号化されている」 は Off を正当化しない。

## <a id="transparent-to-agents"></a>agent の作業には影響しない — 例外は 1 つだけ

FileVault は「起動時にログインするまで復号されない」 だけで、 **ログイン後は完全に透過**。
file 読み書き・MCP・git・透過暗号 (git-crypt 等)・速度、 いずれも変わらない。

唯一の差: **再起動後、 誰かがログインするまで LaunchAgent が走らない**。

- 無人 routine の稼働ホストを選ぶときだけ効く (= 停電・OS update 後に人が触るまで止まる)
- LaunchAgent はそもそもログイン後にしか走らないので、 **FileVault Off でも「ログイン前に走る」 わけではない**。
  差が出るのは「自動再起動 → 無人で復帰」 を当てにしている構成だけ
- 常時起動の据置機を稼働ホストにする設計 ([multi-machine-state.md](multi-machine-state.md)) とは素直に両立する

逆に、 上の層の暗号化 (透過暗号の鍵・OAuth credential・token) は **鍵をローカル平文で持つ**ので、
FileVault はその土台になる。 上だけ暗号化して土台を空けておく構成は、 見た目ほど守っていない。

## <a id="recovery-key-custody"></a>復旧キーの置き場 — 循環させない

復旧キーを**それが開けるディスクの中だけ**に置くと、 要るときに読めない。 一般則と検査の 1 問は
[secret-handoff.md#do-not-store-inside-the-lock](secret-handoff.md#do-not-store-inside-the-lock)。

このドメインでの具体形:

- **台帳を 1 つ持つ** (1 台 1 ブロック)。 有効なのに未保管の機を**書いて残す** = 穴が見える形にする
- 台帳の置き場は、 **別デバイスから別の資格情報で開ける**こと。 台帳自体は暗号化してよいが、
  その復号鍵が同じディスクの中にしか無ければ循環は解けていない
- 各ブロックに `hostname` を書く (= 機械が「この機のブロック」 を引ける key。 通称だけだと照合できない)
- Mac を手放すときは、 **ブロックを消す**までが 1 単位 (= ディスク初期化と一緒に)

## <a id="obtain-and-redisplay"></a>取得と再表示 — 「初期設定の一瞬だけ」 ではない

- 初期設定 (Setup Assistant) で 1 度表示される
- 近年の macOS は **システム設定 → プライバシーとセキュリティ → FileVault → パスワードリセット → 復旧キー「表示」**
  で**再表示できる**。 「もう見られない」 前提で鍵を作り直す前に、 まずこの画面を開く
- 同画面は「復旧キーは iCloud キーチェーンがオンのすべてのデバイスで表示できます」 とも書く =
  **別デバイス経路がすでに 1 本ある**。 ただしその account から締め出されると同時に消える経路なので、
  独立した第 2 経路 (= 自分の台帳) を持つ理由は残る
- 再表示が無い OS 版・表示できない場合は発行し直す:

```bash
sudo fdesetup changerecovery -personal   # 新しい鍵を発行 = 旧鍵は無効化される
```

## <a id="validate-the-transcription"></a>書き取ったら checker に通す

画面から書き取った文字列は「転記」 ではなく「生成」 で、 1 文字違っても**使う瞬間まで気づけない**
(字形の読み方と規律 = [photographed-document-transcription.md#opaque-string](photographed-document-transcription.md#opaque-string))。

```bash
sudo fdesetup validaterecovery   # 鍵の入力を求められる → "true" なら転記は正しい
```

⚠️ **root が要る**。 agent は利用者の管理者パスワードを扱わないので、 **この 1 コマンドは人の操作**。
台帳には照合済みか未照合かを必ず書き、 **未照合を「保管済み」 と書かない**。

## <a id="posture-check"></a>機械で見る — 「On なのに鍵が無い」 を毎回出す

有効化と鍵の保管は別の操作なので、 **前者だけ済んだ状態**が静かに残る。 人の記憶は carrier にならないので、
台帳と実機の状態を突き合わせる検査を発火面 (dashboard / session 開始) に載せる。

```bash
python3 scripts/check-filevault-posture.py --ledger PATH_TO_LEDGER
```

述語と出力の約束 (詳細は script 冒頭が正本):

- **鍵の値を一切出力しない** (= 有無と照合状態だけを見る。 末尾数文字も出さない)
- 台帳が**読めない**とき (暗号化されたまま / 権限が無い) は緑にせず、 **読めないと言う**
  (= fail-open を可視化する。 「finding 0 件」 と区別がつかない状態を作らない)
- `--ledger` を渡さなければ何も言わない (= 台帳を使っていない環境の出力を汚さない opt-in)

## 関連

- [secret-handoff.md#do-not-store-inside-the-lock](secret-handoff.md#do-not-store-inside-the-lock) — 循環する置き場の一般則
- [secret-handoff.md#placement-and-durability](secret-handoff.md#placement-and-durability) — 「今動く配置」 ≠ 「耐久な配置」
- [photographed-document-transcription.md#screen-derived-values](photographed-document-transcription.md#screen-derived-values) — 画面から読んだ値・状態の検証
- [multi-machine-state.md](multi-machine-state.md) — 無人 routine の稼働ホスト判定
