<!-- doc-meta
when: macOS で「新しいバージョンを使用」「旧版は削除できます」等が繰り返し出るとき + 同じアプリの旧新版が別 bundle で共存するとき + 旧版を退避して書類の既定アプリを新版へ切り替えるとき
category: macos
summary: macOS の別 bundle 版移行を、名前の部分一致による全 app 棚卸し → bundle/version/書類型の同定 → 新版で既知書類を開く → Finder「情報を見る」で既定 handler を確認 → 旧版をゴミ箱へ退避 → before/after の状態差で検収する。Spotlight・duti・exact-name find の単一 null は不在証明にせず、CLI の LaunchServices context と Finder の見え方を分離する
-->
# macOS の旧新版アプリが別 bundle で共存するときの移行

## <a id="side-by-side-root"></a>症状と根

アプリの大きな版替えが既存 `.app` の上書きでなく**別 bundle**として配られると、旧版と新版が同時に残る。旧版を Dock、Finder の「このアプリケーションで開く」、または書類の関連付けから起動すると、新版への誘導が毎回出ることがある。「今はしない」は移行の完了でなく先送りなので、旧版が起動経路に残る限り症状も残る。

名前は同じとは限らない。`find ... -name 'App.app'` の exact match は `App Creator Studio.app` のような新版を黙って落とす。最初の棚卸しは [`macos-app-bundle-audit.py`](../scripts/macos-app-bundle-audit.py) の部分一致を使う。

```bash
python3 scripts/macos-app-bundle-audit.py --match Keynote
```

この道具は `Info.plist` から path、表示名、`CFBundleShortVersionString`、build、`CFBundleIdentifier`、実行 file、宣言済み拡張子を読むだけで、アプリを起動しない。別 volume も見る必要がある場合だけ `--root /Volumes/EXTERNAL` のように明示追加する。

## <a id="inventory-evidence"></a>棚卸しの証拠規律

次の単一結果を「新版が無い」「既定が無い」の証拠にしない。

- `mdfind` が空 — Spotlight index / sandbox / privacy context の結果かもしれない。
- LaunchServices の dump が空、`lsregister` が scan error — GUI session と CLI process の control plane が一致しているとは限らない。
- `duti -x` が空、`duti -s` が dynamic UTI や `-10822` で失敗 — Finder の「情報を見る」が handler を正しく表示することがある。
- exact-name の filesystem search が1本だけ — 別名の sibling bundle を落としている。

最低2経路で照合する。物理 inventory は filesystem + `Info.plist`、ユーザーが実際に使う handler は**既知の書類を選んだ Finder「情報を見る」**を最終の可視証拠にする。null は `absent` でなく `unknown` に置き、別 probe へ進む（一般則 = [`debugging-discipline.md#recovery-state-dispatch`](debugging-discipline.md#recovery-state-dispatch)）。

## <a id="migration-state-machine"></a>移行は状態遷移として行う

1. **before を固定**: 旧新版の path / version / bundle id と、対象拡張子の既定 handler を記録する。
2. **新版を1回だけ起動**: 新版 bundle を明示し、既知の書類を開く。書類が表示されることとアプリの版を確認する。既に新版が healthy なら新しい instance を増やさない。
3. **既定 handler を確認・設定**: Finder の「情報を見る」→「このアプリケーションで開く」で新版を選び、「すべてを変更」。宣言的な個別設定を繰り返し適用する場合は [`set-file-associations.py`](../scripts/set-file-associations.py) を使う。
4. **旧版だけをゴミ箱へ**: `/Applications` の App Store app は直接削除が拒否されることがある。Finder の「ゴミ箱に入れる」を使い、**ゴミ箱は空にしない**。これで rollback を残す。
5. **after を読む**: 旧 path が消え、新版 path が残り、旧版がゴミ箱に在り、既知書類の「情報を見る」が新版をデフォルトと表示し、新版で書類が開くことを確認する。Dock に旧 path の固定 item があれば新版と入れ替える。

アプリ bundle とユーザー書類は別 object である。削除対象を `.app` の exact path と版で同定し、プレゼンテーションや文書の directory を削除操作に含めない。

## <a id="file-association-engine"></a>関連付け engine

汎用 engine は bundle id と拡張子の組を呼び出し側から受ける。owner 固有の選好は layer 3 の shim に残し、判定・read-back・exit code はこの engine に一元化する。

```bash
python3 scripts/set-file-associations.py \
  --set com.example.Reader .demo \
  --set-if-installed com.example.NewEditor .sample

python3 scripts/set-file-associations.py --check \
  --set com.example.Reader .demo
```

exit code は 0 = 全 mapping 一致、1 = 読み取り済みだが不一致、2 = `duti` 不在・書込失敗・read-back不能。`--set-if-installed` は探索できて bundle が無い machine では `SKIP` とし、別 machine の setup を壊さない。探索に権限エラーがあれば不在へ畳まず `UNKNOWN` / exit 2。通常の `--set` は「設定できたはず」で success にせず、`duti -x` の read-back が取れなければ `UNKNOWN` として失敗させる。

ただし agent sandbox / GUI session の LaunchServices context が分かれる環境では、engine の exit 2 は GUI 側の不一致を意味しない。その場合は Finder の「情報を見る」で確認し、CLI の null を成功にも不在にも読み替えない。

## <a id="iwork-15-transition"></a>Keynote / Pages / Numbers 14.5 → 15.1 以降

Source check: 2026-09-15。Apple は Mac 用 Keynote、Pages、Numbers 15.1 以降を、14.5 の上書き更新でなく**新しいアプリ**として配布している。旧版を残せる一方、ストレージを空けるなら14.5をゴミ箱へ移せる。通常の作成・表示・編集・共同作業はサブスクリプションなしでも利用でき、サブスクリプションはプレミアム content / intelligence 機能を加える。

- Apple Support: [Mac用Keynote、Pages、Numbersのバージョン15.1以降をインストールする](https://support.apple.com/ja-jp/126151)
- Apple Support: [MacのKeynoteの新機能](https://support.apple.com/ja-jp/guide/keynote/tan700f60676/mac)

新版の bundle id は旧版と異なり得るため、表示名や Dock icon だけで削除対象を決めない。`macos-app-bundle-audit.py --match <name>` の出力で旧新版を並べてから処理する。

## <a id="verification-boundary"></a>検収境界

完了条件は「ゴミ箱への移動 command が通った」でも「新版が一度開いた」でもない。次の状態ベクトルを直接読む。

- 旧 bundle: Applications から absent、Trash に present（回復可能）
- 新 bundle: Applications に present、期待する版・bundle id・実行 file
- document handler: Finder「情報を見る」で新版がデフォルト
- representative document: 新版で表示可能、意図しない保存・変換なし
- Dock: 旧 path の固定 item なし

この5点のうち読めないものは `unknown` と明示し、成功へ畳まない。
