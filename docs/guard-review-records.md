# 規則保護の成果物と検収の記録

本書は資料の所在・来歴・検収状態の索引である。規則の正本は [agent-rule-ownership](../conventions/agent-rule-ownership.md)、実測の正本は [検証記録](agent-rule-guard-verification.md)、未採用の設計は [wiring の比較](guard-wiring-scope-proposal.md)。SESSION と README に本文を複製しない。

## 履歴の範囲

| 段階 | 正本と残した証拠 |
|---|---|
| 初期の原稿・権限保護 | `7f25cee`。綴りの近さによる誤通過、削除だけの commit、移動、入力 graph、候補 hash、故障時の拒否。実装・反例は engine / adapter の既存試験、経緯は検証記録 |
| 配置・信頼・再起動と発火 | 検証記録と [Codex runtime 仕様](../codex/PARITY.md)。構成監査は [audit-codex-hook-runtime.py](../scripts/audit-codex-hook-runtime.py)。信頼済み表示と実 tool の発火は別の証拠 |
| 一般規則への拡張と独立検品 | `ab95786`、[reviewer のラウンド記録](guard-review/REVIEW-RESULTS.md)、[成果物棚卸し](guard-review/HANDOFF.md)、[供給 snapshot の hash 台帳](guard-review/snapshot-manifests.json) |
| patch の改行・Git pathspec・実作業先の欠落 | 同 commit の回帰試験と検証記録。revision4 の22確認、revision6 の36比較、revision8 の24確認、revision9 の30確認は異なる対象・時点の限定検品 |
| CI 報告の訂正 | CodeQL の成功を全体 CI の成功とした誤りを検証記録で訂正済み。workflow / head / 結果を分離する |
| wiring の設計比較 | `de142cc` の未採用 proposal と、以下の観測用 script。現行規則の変更ではない |
| 後続の独立検収 | 機能の再確認と大量入力時の性能差し戻しを検証記録へ受領。追加案 F は proposal の受領欄に記録。最終設計・性能修正は後続作業であり、本整理では実装していない |
| 性能修正と wiring の裁定・実装 (2026-09-22、後続担当) | `c4456a5`。件数に比例しない Git 呼出し、redirect の誤停止・素通りの修正、F の採用 (block 限定 + canary の生存記録)。裁定と残る穴 = [agent-rule-ownership#wiring-scope](../conventions/agent-rule-ownership.md#wiring-scope)、実測・修正前で赤・依頼元 harness の結果 = [検証記録](agent-rule-guard-verification.md) の末尾 2 節。本人の承認は候補 8 file の hash に束縛して記録 |

初期作業を含む会話履歴と残存ファイルを照合した。元の stdin script や一時 fixture が削除されている箇所は、保存済みと装わない。reviewer の2文書は既存返信からの事後整理であり、新規の実行ログではない。初期 [依頼書](guard-review/REVIEW-SPEC.md) と [pathspec の追加依頼](guard-review/PATHSPEC-REVIEW.md) も保存した。初期の読取専用依頼と、後続ラウンドでの合成 fixture 実行の指示を同時点の指示として混ぜない。

## 再利用する道具

| 道具 | 所有する処理 | 例 |
|---|---|---|
| [guard-review-pathspec.sh](../scripts/guard-review-pathspec.sh) | Claude reviewer が独立に作った pathspec 観測。19個の機能例と、任意サイズの規模例1個 | `GUARD_REVIEW_SCALE_FILES=2 bash scripts/guard-review-pathspec.sh` |
| [guard-review-compare.py](../scripts/guard-review-compare.py) | 旧 engine と作業ツリー engine に同じ合成入力を当てる時間比較 | `python3 scripts/guard-review-compare.py 150 --before-ref 7f25cee` |
| [guard-review-profile.py](../scripts/guard-review-profile.py) | `changes_for_repo` の cProfile と subprocess 回数の観測 | `python3 scripts/guard-review-profile.py 150 .txt` |
| [guard-review-wiring.py](../scripts/guard-review-wiring.py) | 既存述語を変えずに、block 外の終了・差替え・失敗隠蔽などを合成 Bash で観測 | `python3 scripts/guard-review-wiring.py --output /tmp/wiring-results.json` |

比較・profile は `--repo`、wiring は `--guard` で入力元を指定できる。pathspec は `GUARD_REVIEW_HOOK` で対象 adapter を指定する。通常の既定値はこの checkout の source であり、機械に導入された設定や trust を検証するものではない。規模を測るときは `GUARD_REVIEW_SCALE_FILES=3000` などを明示し、[件数と外部 process の規律](../conventions/hook-authoring.md#hook-cost-per-item) に従って対象と時間を記録する。移設確認は N=2 の小さな対照だけで行い、性能修正の検証と混同しない。

移設では固定された個人の path を引数・既定の相対 path に分離し、BSD `sed -i` を同じ文字置換へ置き換えた。pathspec の旧/新出力は時間だけを正規化して一致し、20/20。旧/新比較 script の結果分類も N=2 で一致した。wiring の14観測レコードは元の記録と一致し、profile は N=2 で起動を確認した。元の入口は上層を呼ぶ shim とし、判定本体は複製しない。

### 観測 harness の限界

これらは reviewer の調査用 script の移設であり、稼働する guard や新しい CI gate ではない。pathspec script は元の表示・終了動作を保存しており、終了値だけで合格と判定してはいけない。`PASS` / `FAIL` の集計と各例を読む。空の hook 出力を allow と扱う旧 harness の性質、比較 script が旧 engine に現行の `scripts/lib` を組み合わせる性質も残る。異常終了・空出力まで扱う厳密な検査には、既存の [hook 回帰試験](../hooks/manuscript-claim-guard.test.sh) を併用する。profile の測定区間は code に書いた `changes_for_repo` であり、フック全体の時間ではない。

今回、性能改善・範囲選定に踏み込んでこれらの判定を改変していない。旧版比較、profile、時間・stderr の採取は、意味が違う測定をまとめて「合格」にしないための道具である。

## 情報を置く場所

- 実装と回帰試験は既存の上層 source を正本にし、修正用の一時 script を運用の入口にしない。
- 公開可能なレビュー所見・論理的な snapshot 名・hash は本書から辿る。元の独立 stdin harness は未保存のままであり、復元したことにしない。
- 作業時の候補全文・patch・実行ログ・移設前の reviewer script は、機械固有の path や本人の発言を含むため非公開の案件資料に保存した。運用正本でも、導入状態を復元する手順でもない。公開の規則・道具はこの非公開資料に依存しない。
- 案件固有の事故・原稿の裁定は案件側、依頼・返答・担当の変化は依頼側の記録と掲示板が所有する。未解決の性能・設計を資料整理の完了で閉じない。
