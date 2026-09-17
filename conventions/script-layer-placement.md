<!-- doc-meta
when: personal layer / shared project に script を新設するとき + 同じ役割の script が複数層にあると気づいたとき + generic engine と個別設定を分離するとき
category: harness-core
summary: script は現在の置き場所でなく audience と依存で配置する。汎用 predicate・変換・selftest は上層 engine、owner/project 固有の値・credential・対象一覧・scheduler wiring は下層 config / shim。下層入口を保つ場合も実装は複製せず exec/import で上層正本を呼ぶ
-->
# Script の層配置 — engine は上、instance は下

script の置き場所は「最初にどの案件で書いたか」ではなく、**誰が入力を用意でき、誰に再利用可能か**で決める。一般化できる predicate・変換・検証は可能な限り上層へ置き、狭い audience にしか意味のない値だけを下層へ残す。

## <a id="placement-test"></a>配置判定

1. owner の識別子、private SoT、credential、account、repo 一覧が無くても動く機械部分は **layer 1**。
2. 特定共有 project の schema・成果物・共同編集契約そのものを実装する決定的 engine は **layer 2**。
3. owner 固有の対象一覧、選好、private workflow、cross-machine credential 配線は **layer 3**。
4. hostname、絶対 path、導入済み app、local state、scheduler 登録は **layer 4**。再現可能な installer は上層に置けても、導入済みという事実は layer 4 のまま。

「private data を読む」は script 全体を private に固定する理由ではない。data の形を引数・config にして処理する部分が他人にも使えるなら、engine と instance を分ける。

## <a id="engine-instance-seam"></a>正しい seam

- **上層 engine**: 明示的な `--root` / `--config` / `--repo` 等を受け、owner 名・絶対 path・秘密を持たない。判定ロジック、既定値の意味、exit code、positive/negative/foil を含む selftest の正本はこちら。
- **下層 config / shim**: owner/project 固有の root、repo、account、例外、通知先だけを注入する。既存 dashboard や hook の path を保つ必要があれば薄い shim を残し、`exec` または import で上層 engine を呼ぶ。
- **私的な経路に依存する一部は callback にする**: 非公開の client でメールや API を読む部分は engine に入れず、呼び出し側から関数として渡す。engine は判定の純関数 (抽出・既知集合との照合・表示する 1 行) と「いつ呼ぶか」だけを持つ。判定の selftest は上層で合成データだけで回り、下層 shim の selftest は経路の形を真似た fake で継ぎ目だけを見る。
- **下層入口の import 名を保つ**: 下層 script の関数を別の script や手順書が import しているなら、shim はその名前を同じ引数で残す (engine から再 export し、account 名などで選ぶ関数は下層で wrap)。CLI の引数だけ保っても import する呼び出し元は壊れる。移設前に下層 path を全 repo で grep し、CLI 以外の使われ方を拾う。
- **engine の読み込み方**: shim が engine を module として読むなら、`importlib` の `exec_module` ではなく source を毎回 compile して exec する (macOS の system python は bytecode cache を別の場所に書き、同じ秒・同じ size で書き戻された source では古い `.pyc` を読みうる)。`check-script-layering.py` はこの形も shim と認める。
- **参照面**: 下層 README / instruction index は役割・発火面・個別値の所在と上層正本への pointer だけを持つ。上層の述語や閾値表を再 author しない。
- **SESSION**: 「何を移したか + 正本 pointer + 残作業」だけ。実装史、判定表、件数、恒久的な配置判断は engine/doc/ledger に置く。

同じ basename の script が上下層にあり、両方が判定ロジックを持つ状態は migration の途中形であって完成形ではない。byte-for-byte copy も二重正本なので、配布 mirror として明示・検査する場合を除き shim 化する。

## <a id="migration-gate"></a>移設の検収

1. 上層 engine を先に追加し、合成 fixture で selftest を通す。selftest の歯は、要所を 1 か所ずつ外した mutant を `<name>.mutants.json` に宣言して [`check-foil-teeth.py`](../scripts/check-foil-teeth.py) で確かめる (scratch の `sed` で壊して見るだけでは次の人が再現できない)。「途中の file が残っていない」 だけを見る検査が、途中の file を使わない版でも通っていた例がある (実測)。
2. 下層の呼び出し path を保ったまま shim 化し、**変更前に保存した旧入口の出力**と新入口の出力・exit code を照合する。
   - 実データでは出ない分岐 (未承認・見えない・新着・エラー) は、旧版と新版の写しの設定定数だけを scratch の config に差し替えて同じ呼び出しを通し、比べる。写しは元と同じ basename にする (argparse の usage に prog 名が出て、名前だけの差が混じる。実測)。
   - 関数を import する呼び出し元がいるなら、両版を同じ fake client で動かし、標準出力・呼び出しの列・書き出した file を 1 つの report にまとめて比べる。
   - 差が出たら原因を名指ししてから、その差だけを正規化して比べ直す (例: 定数の文字列を config 由来の名前に置き換えた)。正規化を広げて差を消さない。
   - 大きな副作用のある mode (実際の download・送信) を回さないなら、その経路は engine の selftest (fake + 一時 dir) で見た、と結果に書く。
3. 個別値を下層 config / shim に寄せ、上層 diff に owner・第三者・未公開案件の事実が無いか確認する。
4. 上層の規約・script index を正本にし、下層 index と SESSION は pointer 化する。
5. [`scripts/check-script-layering.py`](../scripts/check-script-layering.py) で同名二重実装が無いことを検査する。新しい lower-layer script は、上層 counterpart を同時に作らない正当な場合だけ先頭 40 行に `layer-placement: layer3 <理由>` を書く。これは配置理由の declaration であり、汎用化できないことの永久免罪ではない。

この checker が証明するのは「既知の二重実装がない」「新設時に配置判断を飛ばしていない」ことまで。lower-only script の意味が本当に owner 固有かは `--inventory` の棚卸しで定期的に読み直す。
