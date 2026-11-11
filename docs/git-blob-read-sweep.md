# Git の版を読む処理の棚卸しと修正方針

状態: **調査結果と方針案。実装には未着手**。実装は方針の確認後に別途依頼する。

推す案は、任意の repo の本文を読む **16 file・17 呼出箇所**を、Python では `lib/git_blob.py`、shell では既存の暗号化 path の分岐に揃えること。すでに復号する処理、公開時の保存内容を調べる処理、暗号文を確認する試験は用途を保つ。共通 helper の失敗時の契約は変更しない。

根拠の規則: [blob の読み方](../conventions/hook-authoring.md#blob-read-git-crypt)、[方針の段の委任](../conventions/policy-before-implementation.md#delegating)、[規則変更の権限](../conventions/agent-rule-ownership.md#rule)。本書は既存規則の例外を追加するものではなく、各呼出しの用途と修正候補を記録する。

## 調査範囲

- 基準版: `0a1c98b2c8f62e6fa98f76b2526e9dafdb36fe55`。表の行番号はこの版。通常の fetch は実行環境のネットワーク制限で失敗したため、調査時点の remote 最新版との一致は未確認。
- `git ls-files scripts` の Python / shell **510 file**を母集団とし、`show` の文字列検索、Python の AST の呼出し抽出、呼び元の用途を照合した。下表は `git show` で blob を読む本番経路の **34 箇所**を含む。
- `cat-file` と `read_blob` の利用も検索し、既に復号している経路と、生の object を検査する経路を区別した。`hooks/`、`codex/`、他 repo の実装の網羅調査ではない。動的に組み立てる未知のコマンドまで完全検出する保証はない。
- 非公開 repo の本文・鍵・個人の履歴は検証材料にしていない。再現に使った file の内容はすべて合成値。

## 本文を読むために揃える箇所

Python の 13 file・14 箇所。`read_blob()` は `(rc, bytes)`、`read_blob_text()` は文字列または `None` を返す。`None` と空 file を同一視しない必要がある場所は bytes の API を使う。

| file・関数・基準版の行 | 判定と理由 | 直し方 |
|---|---|---|
| [agent-rule-guard-history.py](../scripts/agent-rule-guard-history.py) `show` L52 | 揃える。指定 repo の規則文書の旧版・新版を読む。暗号化した文書では decode が落ちる | 本文取得だけ helper に替える。欠落した親や新規 file と、存在するが読めない版を分け、後者を判定件数から黙って消さない |
| [check-legacy-append-only.py](../scripts/check-legacy-append-only.py) `git_show` L56 | 揃える。HEAD と index の `*.index.yaml`。暗号文の decode 例外を空文字にして、旧対応表を見失う | HEAD / index 両方を helper で読む。空の旧対応表と検査不能を分け、削除違反を平文の場合と同じに検出する |
| [commit-hunk-anchors.py](../scripts/commit-hunk-anchors.py) `hunks` L112 | 揃える。指定 repo の commit の本文から、差分位置に最も近い anchor / def を探す | 本文の cache に入れる取得だけ変更。L92 の差分取得は維持。読めない場合は anchor 不在と断定しない |
| [fix-md-links.py](../scripts/fix-md-links.py) `target_problem` L413 | 揃える。`--verify-diff` の比較後の版の anchor 検査。staged の別経路は既に helper を使う | 既存 import の `read_blob` を使う。L409 の存在確認と本文の読取失敗を区別し、暗号文を anchor 一覧に渡さない |
| [latexdiff-flatten.py](../scripts/latexdiff-flatten.py) `reader` L173 | 揃える。旧版の sub-file を展開する。今は暗号文を `surrogateescape` で文字列化する | helper の bytes を従来の `ENC` で decode。先に暗号文の印を調べる。主 file を読む shell の変更と一緒に検証する |
| [letter-word-count.py](../scripts/letter-word-count.py) `git_text` L110 | 揃える。任意の返答書の `--git-rev` の語数。暗号化された TeX で例外になる | helper で読み、既存の「その版を読めない」表示へ戻す。空の本文と失敗の区別、改行の扱いを保つ |
| [manuscript-candidate-regions.py](../scripts/manuscript-candidate-regions.py) `candidate_regions` L39 | 揃える。保護領域の事前検査に使う原稿の基準版。暗号化原稿で例外になる | helper の rc と暗号文の印を確認してから、同じ `protected_changes` に渡す。読めない基準版を空の原稿にしない |
| [memory-budget-pay.py](../scripts/memory-budget-pay.py) `head_bytes` L90 | 揃える。表示対象は本文の byte 数だが、HEAD だけ保存 blob の長さを数えている | `len(read_blob(...)[1])` 相当を rc と暗号文の印の確認後に使う。読めなければ既存の `None`。LFS pointer のままという helper の契約を保つ |
| [permission-dialog-audit.py](../scripts/permission-dialog-audit.py) `HookHistory.cmd_at` L733 | 揃える。現在の層1だけでなく、指定された hook の実体の repo から旧版を取り出す | 本文取得だけ helper、既存 timeout 20 秒を引き継ぐ。読めない版は実行用の写しを作らず、既存の「過去版を比較できない」経路へ |
| [pr-routine.py](../scripts/pr-routine.py) `published_state` L498 | 揃える。設定 `publish.repo` の state JSON には平文限定の契約がない | helper で bytes を読み、暗号文・decode・JSON の失敗は `None` として既存の扱いへ。fetch・公開先・merge の判断は変更しない |
| [routine-host-gate.py](../scripts/routine-host-gate.py) `read_ledger` L104–109 | 揃える。remote ref の JSON 台帳は private path も想定する。現状は復号失敗で作業 tree の台帳に戻り得る | committed の本文を helper で読む。読めなければ今と同じ作業 tree fallback。host 比較と fail-open の仕様は変更しない |
| [tex-prose-pass-invariants.py](../scripts/tex-prose-pass-invariants.py) `main` L291 / L295 | 揃える。`--base` と `--head` の 2 箇所。暗号化した原稿の式・引用の比較を始められない | 両側を helper に替える。`rev:./path` と呼出 cwd を保持。読めない場合は既存の exit 2 とし、比較結果を出さない |
| [lib/git_rewrite_follow.py](../scripts/lib/git_rewrite_follow.py) `upstream_manifest_files` L276 | 揃える。指定 repo の `.rewrite-follow/` を本文として解析する。調べた実装と契約には、この dir を暗号化から外す保証がない | manifest の本文だけ helper に替える。存在して読めない manifest を空の対応表として扱わない。object ID・保存 blob・履歴の照会は変更しない |

shell の 3 file・3 箇所。規則が示す [staged-conflict-markers.sh](../scripts/lib/staged-conflict-markers.sh) の形、すなわち `filter=git-crypt` の path だけ `git cat-file --filters` で取り出す案を推す。`GIT_LFS_SKIP_SMUDGE=1` を付け、任意の filter を新たに走らせる範囲を広げない。

| file・基準版の行 | 判定と理由 | 直し方 |
|---|---|---|
| [latexdiff-review-snapshot.sh](../scripts/latexdiff-review-snapshot.sh) L257 | 揃える。旧版の主 TeX を一時 file に書くため、暗号文のままでは flatten / latexdiff の入力が壊れる | source repo 側の属性を確認して復号。取得失敗や暗号文のままなら、従来の `die` 経路で止める。sub-file 側と同じ版を読む |
| [overleaf-push-file.sh](../scripts/overleaf-push-file.sh) L56 | 揃える。HEAD の file を Overleaf 用 worktree へコピーする処理で、本文が必要 | source repo の filter で取り出してから target に配置する。読めなければ `add` より前で停止。target branch の属性だけで復号を決めない。公開範囲・`--push` の条件・mode / symlink の扱いは別件として変えない |
| [lib/hook-stub.sh](../scripts/lib/hook-stub.sh) `hook_stub_restore_drift` L84 | 揃える。track された stub の HEAD 本文を照合する。暗号化された tracked hook のある repo も受け取れる | 一時 file の読み方だけを替える。復号できず照合できなければ従来どおり復元しない。実際の復元は現行の `checkout --` を保つ |

## 今回は置換を要しない箇所

残りの本番 blob 呼出し 17 箇所。これは未検査の全利用場面に対する安全宣言ではない。

| file・基準版の行 | 判定と理由 |
|---|---|
| [check-activity-facts.py](../scripts/check-activity-facts.py) L66 | 要らない。通常は shared helper。raw show は import できない旧配置用 fallback |
| [check-degenerate-text.py](../scripts/check-degenerate-text.py) L157 | 要らない。通常は shared helper。raw show は helper 不在時だけ |
| [check-session-shape.py](../scripts/check-session-shape.py) L523 | 要らない。通常は shared helper。例外時の raw fallback の意味を変えるのは別の判断 |
| [check-text-section-refs.py](../scripts/check-text-section-refs.py) L925 | 要らない。通常は shared helper。fallback の後にも暗号文の印を確認する |
| [check-unpublished-quote.py](../scripts/check-unpublished-quote.py) L102 | 要らない。通常は shared helper。import 失敗時だけ raw fallback |
| [manuscript-claim-guard.py](../scripts/manuscript-claim-guard.py) L3044 / L3519 | 要らない。通常は shared helper。raw は helper 不在時。batch の復号経路も既に存在する |
| [lib/git_blob.py](../scripts/lib/git_blob.py) L40 | 要らない。filter 失敗時に元の blob を返す API 自体の fallback。消すと全利用者の契約が変わる |
| [check-doc-truncation.py](../scripts/check-doc-truncation.py) `_blob` L127 | 要らない。先に `cat-file --filters` を実行し、fallback 後も暗号文の印を確認する。helper への統合は整理としては可能だが、今回の未復号読取の修正には不要 |
| [owner-ask-validate.py](../scripts/owner-ask-validate.py) `_git_text` L70 | 要らない。先に `cat-file --filters`、続いて `_plain` の厳密 decode と暗号文確認。欠落と検査不能を分ける既存処理を維持する |
| [lib/staged-conflict-markers.sh](../scripts/lib/staged-conflict-markers.sh) L47 | 要らない。raw show は `filter=git-crypt` 以外の分岐。暗号化 path は L45 で復号するという規則の参照実装 |
| [guard-review-compare.py](../scripts/guard-review-compare.py) L17 | 要らない。対象は指定された claude-config の旧 engine `scripts/manuscript-claim-guard.py`。任意の project の本文を読む処理ではない。暗号化された engine の clone も対応対象にするなら再判定 |
| [check-session-carryover.py](../scripts/check-session-carryover.py) L384 / L473 | 要らない。公開 repo の「すでに公開された値」の集合と、replay の公開行の表示。暗号文の復号結果を自動で「すでに公開済み」と数える変更は意味を変えるため、この sweep でしない |
| [check-unpublished-quote.py](../scripts/check-unpublished-quote.py) `replay` L898 | 今回は要らない。公開 repo の過去の本文を使う較正の経路。staged は別に helper 済み。暗号化 path を含む replay を保証するなら、diff と全文の対応を含めた別の検証が必要 |
| [replay-public-gate.sh](../scripts/replay-public-gate.sh) L68 / L79 | 今回は要らない。公開 commit の保存内容を一時 repo へ再構成する経路。復号して公開時の bytes を変えるだけの置換はしない。filter 設定も含めた暗号化 repo の replay 対応は、この公開 repo 用の道具の別の設計になる |

既存 fallback の維持は「helper の配布漏れでも検査できる」という主張ではない。実装の検証は lib を含む通常配置で行い、helper 不在・鍵不在・filter 不成立の保証範囲を区別する。

### blob 本文ではないもの・試験の raw 読取

- `show --format= --name-only`、`show --stat`、`show -s --format=%B`、patch の `show -U0`、`reflog show` は blob 本文の API に替えない。対象: `agent-rule-guard-history`、`audit-push-provenance`、`check-activity-facts`、`check-session-carryover`、`check-unpublished-quote`、`commit-from-origin-worktree`、`commit-hunk-anchors`、`foreign-hunk-check`、`git-commit-own-hunk`、`prepare-commit-msg-session`、`lib/git_rewrite_follow`。
- 生の保存形を確かめる試験は raw のまま: `lib/git_blob.py` L95 / L114、`intersect-sync.py` L301、`commit-from-origin-worktree.py` L551 / L562、`owner-ask-validate.py` L223 / L230、`selftest-on-old.py` L177、`lib/staged-conflict-markers.test.sh` L109。最後の旧読取の試験は、退行の対照として raw を使うこと自体に意味がある。
- 平文の合成 repo の内容を確認する試験も今回の修正対象外: `commit-from-origin-worktree.py` L411、`probe-codex-wrap.py` L232、`upstream-pr.py` L1510、`pre-commit-bib.test.sh` L234。
- `log show`、board の `show`、CLI の subcommand 名、判定用の文字列集合、コメントだけの記載は Git blob の読取ではない。
- 横の点検: `check-ledger-merge-loss`、`check-tex-engine`、`check-tex-papersize`、`formcase/guard`、`commit-from-origin-worktree`、`git-commit-own-hunk`、`lib/intersect_sync` は既に `--filters` を使う。今回の文字列置換に巻き込まない。`check-gitcrypt-readable`、`check-history-growth`、`check-student-identifiers`、`git-scrub-history`、`lib/git_rewrite_follow` の保存 object の検査も、復号で対象を変えない。

## 再現したことと未確認のこと

既存 `python3 scripts/lib/git_blob.py` の試験は **8 検査が成功**。平文・index と commit の違い・欠落・rot13・実 git-crypt の index / commit を含む。

追加の読取 probe は一時 repo に `*.md / *.tex / *.yaml filter=git-crypt diff=git-crypt` を設定して commit した。Markdown は架空の `anchor`、TeX は短い Introduction、YAML は `legacy: "1"` だけの合成内容。実 repo は変更せず、次を観測した。

| 現行関数を直接呼んだ対象 | 観測した結果 |
|---|---|
| `memory-budget-pay.head_bytes` | HEAD が本文より 22 byte 大きい |
| `letter-word-count.git_text` | `UnicodeDecodeError` |
| `agent-rule-guard-history.show` | `UnicodeDecodeError` |
| `latexdiff-flatten.reader` | 取得した文字列が平文と一致しない |
| `fix-md-links.target_problem` | 存在する `#anchor` を HEAD に無いと報告 |
| `check-legacy-append-only.git_show` → `legacy_set` | 存在する旧対応表を空集合と読む |
| `manuscript-candidate-regions.candidate_regions` | `UnicodeDecodeError` |

同じ repo の `read_blob` は本文と byte 単位で一致した。別の合成 filter (clean で `\0GITCRYPT\0` と非 UTF-8 byte を付加し、smudge を失敗させる) では、helper が **rc 0 と暗号文の bytes を返す**ことも確認した。これは fallback の現在の仕様であり、rc だけで復号成功とみなせない。

この probe は各関数の読取の観測であり、修正後の CLI 全体や本番 hook の検証ではない。上表以外の移行候補は静的な用途の追跡まで。Overleaf の送信、無人 routine の実行、private データでの較正は行っていない。

### 原出力と再現コード

根拠に使った一回きりの code と出力の扱いは、[締めの evidence script の規則](../conventions/closing-sweep.md#evidence-scripts)に従う。下の出力は調査時の実行結果を回収したもので、修正後に取り直した結果ではない。

| 根拠 | 保存先と読み方 |
|---|---|
| 本文の読取候補を列挙した AST の走査 | [inventory.py](git-blob-read-sweep-evidence/inventory.py) と [原出力](git-blob-read-sweep-evidence/inventory.txt)。基準版の checkout の root で `python3 docs/git-blob-read-sweep-evidence/inventory.py` を実行する。文字列の候補一覧であり、表の用途判定そのものを自動で証明するものではない |
| 合成 filter の probe | [原出力](git-blob-read-sweep-evidence/synthetic-filter.txt)。`link target AttributeError` は誤った関数名で呼んだ失敗であり、anchor の結論の根拠には使わない。後半の smudge 失敗時に rc 0 の暗号文が返る結果が根拠 |
| 実 git-crypt の probe | [原出力](git-blob-read-sweep-evidence/git-crypt.txt)。7 関数の観測と本文の 22 byte の差はこの出力に対応する |

probe 2 本の code は `agent-rule-guard-history.py` を名前で読み込むため、実行用 script としての配置は保護対象となる。候補全文は [合成 filter の候補](git-blob-read-sweep-evidence/synthetic-filter.py.txt) と [実 git-crypt の候補](git-blob-read-sweep-evidence/git-crypt.py.txt) に text として置き、実行用 file には適用していない。候補の受け渡しに `.txt` を使う形は [締めの保護対象の手順](../conventions/closing-sweep.md#protected-files-need-ruling)に従う。元の一回きりの code から、repo の位置の決定だけを file の相対位置に替えた。原出力は上に保存し、実行用 file への適用は既存の承認手順の対象として残す。名前を隠して保護を外す書き換えはしない。

ほかの一回きりの code は、本文の部分表示・文字列での候補抽出・掲示板表示の絞り込みに用いた。新しい判定や再現結果を持たない表示用の枠なので恒久配置しない。数値の集計は上の AST code、静的な用途の判断は基準版と本書の各呼出しの表を根拠とする。

## 実装の方針案

1. **範囲**: 上の 16 file の本文読取を修正する。担当は Codex の実装 worker 1 窓、model / effort は `gpt-6-astra / xhigh` を候補とする。guard に当たる file は、候補差分を作って既存の承認手順を通す。今回の方針提出を適用の承認として扱わない。
2. **共通 API**: Python は `Path(__file__).resolve()` から既存 lib を import。用途別の rc・timeout・decode・改行正規化を保つ。shell は既存の git-crypt 分岐を使う。新しい汎用 CLI や batch reader はこの修正のためには増やさない。
3. **読めない場合**: `read_blob` の rc が非 0、先頭が `\0GITCRYPT`、または必要な text decode ができない場合を識別する。比較不能を「同じ」「違反なし」「anchor 不在」「空の旧版」に変換しない。既存の fail-open / fallback / exit code を保ち、検査不能が必要な箇所ではその旨だけを短く出す。blob の内容や例外の `repr` は出さない。
4. **互換性**: helper の `.decode()` は `subprocess(text=True)` の改行変換と同じではない。CRLF・日本語・空 file・空白を含む path・subdir の `rev:./path` を確認する。`surrogateescape` を使う flatten はその方針を勝手に変えない。LFS は取りに行かない。
5. **順序**: まず読取だけの道具と対の latexdiff、次に gate・台帳・履歴追従、最後にコピーを伴う shell。各まとまりで試験と commit を切る。規則本文の書き換えは不要で、古い `git show` の説明コメントだけを実際の呼び方へ更新する。

検証は各変更の成否を独立に示す。少なくとも平文の既存結果が変わらないこと、rot13 と長さが変わる非 UTF-8 filter、実 git-crypt があればその fixture、復号失敗、存在しない版と空 file の違いを含める。旧版の読取で落ちる対照を 1 回走らせる。gate は「違反する入力を止める・正常な入力を通す・内部エラーで素通りしない」、出力する道具は具体的な anchor・語数・サイズ・本文、コピーする道具は受け取り側の bytes と失敗時に先へ進まないことを見る。

`read_blob` が使う filter / 属性は呼出元の checkout の状態に依存する。古い版の `.gitattributes` や鍵を自動復元する契約はないため、今回の置換で「すべての歴史的な鍵・属性に対応した」とは報告しない。性能の batch 化、既に復号する独自実装の統合、公開 replay の暗号化 repo 対応は今回の必須範囲から外す。

依頼側への提案は、この範囲で実装に進めること。追加の選択が必要なら、公開 replay まで用途を広げるか、既存の独自復号処理を同時に統合するかを分ける。推すのはどちらも今回には加えず、未復号の本文読取を先に直す案である。
