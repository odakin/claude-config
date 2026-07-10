<!-- doc-meta
when: 受信した URL / file を別 recipient に forward する前
category: infra
summary: 受信した URL / file を別 recipient に forward する前に「依頼の scope」 と「届いた data の scope」 を必ず照合する規律 (= over-share / permission mismatch / scope downscope 機会損失の 3 失敗モード回避)
-->
# Pass-through 時に scope を必ず照合する規律

依頼で「~~の URL / file を共有して」 と頼まれて、 受け取った別経路の URL や file を そのまま forward する reflex は **scope 取り違え事故を起こしやすい**。 「依頼の scope」 と「届いた data の scope」 を必ず照合する。

## 失敗パターン

ユーザー A から「課題 X のデータを共有してほしい」 と依頼を受ける。 並行で別経路 (= 上司 / 委員会 / event mail 等) から「課題 X 関連の集約データ URL」 が届く。 reflex で**届いた URL をユーザー A に forward** すると、 以下のいずれかの事故になりうる:

1. **Over-share**: 届いた URL の data scope が依頼の scope より広い (= 他者のデータも含まれる) → ユーザー A に対する権限外データの leak
2. **Permission mismatch**: 届いた URL は特定 grant list 限定 (= ユーザー A は access list 外) → ユーザー A は 403 で開けず、 結果としてユーザー A 視点で「共有された URL が機能しない」 trouble
3. **Scope downscope の機会損失**: ユーザー A が必要なのは class 単位の個別データなのに、 集約スプレッドシートを渡してしまい、 ユーザー A 側で fileter / 抽出の手間が発生

## Mitigation: 「受信した data の scope」 を「依頼の scope」 と照合

forward する**前**に必ず:

1. **依頼者の scope を明確化**: 何のために何 (= 単一クラス / 単一個人 / 単一プロジェクト) を必要としているか
2. **届いた data の scope を明確化**: data がカバーする範囲 (= 委員会全体 / 学科全体 / 全期分 / 特定 1 件)
3. **access list を確認**: 届いた data の共有設定 (= owner / share permission / Workspace 限定) が依頼者を含むか
4. **scope mismatch なら別 data source 検討**: 依頼スコープ専用の data が別経路で取得可能か (= institutional system の個別 download / 自前 query / 自前 upload + share 等)

照合の reflex 化が大事 — pass-through reflex は速いが、 scope confirmation の 1 stop で事故を防げる。

## How to apply

- 「届いた URL / file を forward」 という流れになった瞬間、 内的 stop sign を立てる
- **「これは依頼者の scope に合致しているか?」** を内的 self-check
- 不一致 or 確信が持てなければ「別経路で取得し直す」 ことを優先 (= 大概はその方が clean)
- forward する判断をした場合、 文面で「scope が大きいかもしれないが、 access 権限の都合で適切な部分のみ参照ください」 のような hedging を入れる

## 関連事象

- Public repo への commit 直前の安全弁 = `work-discipline.md §「4 軸 sweep は PII leak の事前 catch にも効く」` (= leak 検出の 4 軸 sweep)
- Email 文体 = recipient と scope の整合性 = `claude-config/conventions/japanese-email-honorifics.md` (= 身内 vs 外、 honorific の scope)
- Secret handoff = `claude-config/conventions/secret-handoff.md` (= secret を chat 経由で渡さない、 clipboard 経由)

## Generic な metapattern

「受信した X を Y へ pass-through」 という任意の操作で、 X の context と Y の context が一致しているかの照合は universal な discipline。 これは:

- URL pass-through (= 本規約)
- File forward (= 添付 forward、 share link forward)
- Quote forward (= 引用 quote を別 thread へ)
- Code snippet forward (= 受け取った snippet を別 codebase へ paste)
- Reference forward (= 「~~を参照」 と他者の reference を別 context で再利用)

いずれも「受信側 scope ≠ 送信側 scope」 を点検する 1 stop で事故を防ぐ。
