<!-- doc-meta
when: Dropbox 配下の file が 0 byte に見えたとき
category: infra
summary: Dropbox の online-only placeholder (0 byte) 診断: xattr `com.dropbox.placeholder` 検出 + OS 別 materialize 方法 + 「0 byte = 配置忘れ」 reflex 防止
-->
# Dropbox の online-only placeholder (0 byte 診断)

`~/Dropbox/...` (macOS) や `%USERPROFILE%\Dropbox\...` (Windows) 配下の file が **0 byte に見える** とき、 第一仮説は **Dropbox Smart Sync の online-only placeholder** (= 実体はクラウド側、 ローカル file system 上は 0 byte stub)。

Dropbox は disk 容量節約のため、 一定期間 access していない file を自動 で online-only 化する設定を提供している (= "Make available online only" / "オンラインのみ")。 この状態の file は file system 上は size = 0 だが Dropbox app 経由で再 download される。

## 識別シグナル (macOS)

```bash
xattr <path>
# → com.dropbox.placeholder が含まれていれば online-only stub 確定
```

その他の特徴:

- `ls -la <path>` で size = 0、 mtime は作成時のまま
- `file <path>` は "empty" を返す
- `stat <path>` は 0 byte
- `cat <path>` / `cp <path>` / `qlmanage` (Quick Look) では materialize **トリガされない** (= Dropbox app の UI 経由のみ)

## 識別シグナル (Windows)

PowerShell:

```powershell
Get-Item <path> | Select-Object -ExpandProperty Attributes
# → "Offline" / "RecallOnDataAccess" attribute が含まれていれば online-only stub
```

Windows では cloud file API 経由で aggressive access が trigger になるが、 確実なのは Explorer UI 経由 (= 後述)。

## Materialize 方法 (= ローカル disk に実体 download)

| OS | 方法 |
|---|---|
| macOS | Finder で当該 file or 親ディレクトリを右クリック → **「オフラインで使用可能にする」** (英語: "Make available offline"、 親ディレクトリ単位で OK = 1 click で複数 file 一括) |
| Windows | エクスプローラーで右クリック → **「このデバイス上に常に保持する」** (英語: "Always keep on this device") |
| Linux (`dropbox` CLI) | `dropbox filestatus <path>` で確認 → `dropbox exclude remove <path>` で local 化 (= Dropbox Linux daemon 必須) |

Claude / 自動化 script から呼ぶ場合: `open <dir>` (macOS) で Finder を開いて user に右クリック操作を依頼するのが現実的。 直接 trigger する macOS API は user-space からは触れない (= Dropbox app extension にしか materialize 権限なし)。

## <a id="git-repo-online-only"></a>Dropbox の中の git repo: `.git` が online-only だと git が固まる

Dropbox 配下に `.git` ごと置いた repo では、 `.git` の中身 (object・index) が online-only のままのことがある (別の機械から移した直後・長く開いていなかった dir)。 このとき file の大きさは元のまま見えることがあり、 上の「0 byte で気づく」 経路に乗らない。

症状 (実測):

- `git status` が返ってこない。 作業ツリーの file の一部だけがまだ届いていないと `read error while indexing <path>: Operation timed out` で止まる
- git を呼ぶ hook (保護 gate・検査) が、 git の時間切れを「git の状態が読めない」 と報告して編集を止める (違反ではないので、 gate を外して通すのでなく git を直す)
- `du -sh .git` が object の数に比べて極端に小さい (数百の object で 100 KB 台)

直し方: repo の dir ごと「オフラインで使用可能にする」 (上の表)。 読み込みで 1 つずつ落とそうとするより、 この 1 操作のほうが確実。 届いたかは時間切れつきで確かめる = `timeout 30 git -C <repo> fsck --connectivity-only` が通り、 `du -sh .git` が実体の大きさになる。 `.git` が届いて作業ツリーがまだ届いていない間は、 `.git` だけを読む操作 (`git log` / `git cat-file`) は通り、 `git status` はまだ止まる。

予防: git repo を Dropbox に置くなら、 使う機械ごとにその dir をオフラインで使用可能にしておく。

## 代替仮説 (= online-only でない 0 byte の場合)

「だいたい」 online-only だが、 ごく稀に:

- 実際に空 file (= `touch` で placeholder 作成しただけで content 未配置) — リポの SESSION.md / 作業履歴に該当する作業履歴があれば確認
- sync 競合で 0 byte に上書きされた — 別マシンの Dropbox state を確認 (= Dropbox web UI で version history を見るのが確実)
- 過去に意図的に空 file を置いた — git history / Dropbox version history で確認

**診断順序**: まず `xattr` で `com.dropbox.placeholder` を check → ヒットすれば materialize で確定。 ヒットしなければ他の仮説に進む。

## 0 byte file を見たときの reflex

1. `xattr <path>` を実行して `com.dropbox.placeholder` 検出 → online-only 確定
2. user に Finder UI 経由の materialize を依頼 (= `open <親 dir>` で Finder を開く)
3. materialize 後に file size を再確認 (= 0 byte → 数 MB に化けるはず)
4. 後続処理に進む

「0 byte だから配置忘れ」 と reflex 推定して再 fetch / 再生成を提案する前に、 必ず step 1 (= xattr check) を回す。 これは §13「安価な操作で expensive 操作を bypass しない」 の Dropbox state 診断 domain への適用 (= 安価な `xattr` を回して expensive な再 fetch / 再生成を避ける)。

## 設計動機

2026-05-18、 odakin の大学講義の板書 PDF 配置確認時、 過去回 (4/17 + 5/8) の 3 file が 0 byte 表示。 当初「placeholder の touch だけして content 配置忘れ」 と誤推定して Google Photos Picker API 経由で再 fetch を提案。 user の「Dropbox オンラインオンリーやな」 指摘で本診断に切替 → Finder「オフラインアクセスを許可」 で 1 操作で 3 file 全 materialize、 2.3-9.7 MB の実 PDF として復活。

以後この pattern を最優先仮説に格上げ。

## 関連

- `dropbox-refs.md`: Dropbox 上の共有 PDF を git リポから symlink 参照する規約 (= 別 topic、 file の sync 状態ではなく path 参照戦略)
