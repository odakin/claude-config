#!/usr/bin/env python3
"""surface-discord-bot-dm.py — Discord bot DM channel の未記録 message surface engine（daily fetcher が吐く JSON と user 側 ledger（text/YAML 内 messageId）の diff で「bot DM に返事が来ても誰も読まない」 死角を埋める汎用 CLI、 個別環境への依存ゼロ＝引数で bot ID / json-dir / ledger-dir / counterpart map / title を渡す、 finding 0 件 silent、 --selftest 内蔵。 personal layer に thin wrapper を 1 つ置いて呼ぶ、 conventions/discord-bot.md#bot-dm-surface）
surface-discord-bot-dm.py — Discord bot DM channel の未記録 message 検出 engine。

「daily fetcher で取得した bot DM の JSON は更新されるが、 そこへの返信を読む経路が
無く『誰も読まないまま放置される』」 という構造的死角を塞ぐ汎用 engine。 fetch (=
JSON 取得) と surface (= 未処理 message を出す) は別物で、 後者が無いと前者だけでは
incidental に user が Discord 通知を見るしか catch 経路がない。

設計動機: ある Discord bot の DM channel に重要返信が来ても、 mail surface fleet
(= 名指し未 triage / 待ち返信新着 / 素材待ち speaker mail 等) は Gmail 専用で
射程外。 daily fetcher が JSON を吐いただけでは「読む」 機構ゼロ。 本 engine は
daily fetcher の output (Discord JSON) と user 側 ledger (= inbox/threads/notes 等
text/YAML 系 record) を diff し、 bot 自身の送信を除いた未記録 message を CRITICAL
で出す。

汎用化点 (= layer 1 hoist の理由):
- bot user ID / counterpart map / paths / glob pattern は CLI 引数で受け取る
- ledger は 「Discord snowflake (17-19 digit) が text として埋まっている file 群」
  と抽象化、 YAML/JSON/MD/プレーンテキスト どれでも OK
- output / selftest 内蔵、 個別環境への依存ゼロ

使い方 (CLI):
    surface-discord-bot-dm.py \\
        --bot-id <DISCORD_USER_ID> \\
        --json-dir <PATH> \\
        --ledger-dir <PATH> \\
        [--json-glob "discord_*_dm.json"] \\
        [--ledger-glob "*.yaml"] \\
        [--counterpart <ID>:<NAME>] \\
        [--title <STRING>]

例 (layer 3 thin wrapper から):
    python3 surface-discord-bot-dm.py \\
        --bot-id <DISCORD_BOT_USER_ID> \\
        --json-dir ~/Claude/<fetcher-output-repo>/src/_data \\
        --ledger-dir ~/Claude/<inbox-repo>/inbox \\
        --counterpart <COUNTERPART_USER_ID>:<DISPLAY_NAME> \\
        --title "<bot-name> DM channel の未記録 message"

検出 logic:
- json-dir/json-glob にマッチする JSON ファイル群を読む (= Discord API
  `GET /channels/{id}/messages` の output 形式を仮定: list of message dicts)
- 各 message について:
    - author.bot == True → skip (= API field の信頼)
    - author.id in --bot-id list → skip (= bot ID の明示 fallback)
    - message.id ∈ harvested set → skip (= 既に ledger に記録済)
    - 残り → 未記録 = surface
- harvested set = ledger-dir/ledger-glob 全 file の text 内 Discord snowflake
  (17-19 digit number) を regex で全部抽出
  - false positive (= user ID / channel ID が含まれても) は harmless: それらは
    real message ID と globally unique なので collide しない
  - 漏れる category (= 17 digit 未満の極初期 snowflake、 2015 年初頭) は
    現実的に存在しない bot DM では問題にならない

⚠️ 効果限定:
- daily fetcher の latency (= cron 周期) を超えた即時性は出ない
- ledger に message ID を明示記録する規律が前提 (= ledger に messageId が書かれて
  いれば surface 消える、 書かれていなければ surface し続ける、 = 「読んだ」 を
  intake で encode する原則)
- JSON 取得元 (= daily fetcher) の git-crypt 等 access 経路は別途確保が前提

selftest: --selftest で内蔵 fixture (5 検証) を実行
"""
import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

# Discord snowflake = 17-19 digit number。 message ID / user ID / channel ID は
# 同 range だが globally unique なので collide しない (= harvest set に user/channel
# ID が混入しても harmless)。 17 digit 未満の極初期 (2015 年初頭) は無視。
SNOWFLAKE_RE = re.compile(r"\b\d{17,19}\b")


def harvest_recorded_ids(ledger_dir: Path, ledger_glob: str) -> set[str]:
    """Read all ledger files matching glob, extract Discord snowflake IDs."""
    ids: set[str] = set()
    if not ledger_dir.exists():
        return ids
    for f in sorted(ledger_dir.glob(ledger_glob)):
        try:
            text = f.read_text(errors="replace")
        except Exception:
            continue
        ids.update(SNOWFLAKE_RE.findall(text))
    return ids


def author_label(author_obj: dict, counterpart_map: dict[str, str]) -> str:
    """Return display name for a Discord author."""
    author_id = author_obj.get("id", "")
    name = counterpart_map.get(author_id)
    if name:
        return name
    return (author_obj.get("global_name")
            or author_obj.get("username")
            or author_id)


def scan_dm_files(json_dir: Path, json_glob: str, bot_ids: set[str],
                  recorded_ids: set[str], counterpart_map: dict[str, str]) -> list[dict]:
    """Scan all DM JSON files, return list of unrecorded message records."""
    findings = []
    if not json_dir.exists():
        return findings
    for jf in sorted(json_dir.glob(json_glob)):
        try:
            msgs = json.loads(jf.read_text())
        except Exception as e:
            print(f"WARN: {jf.name} parse failed: {e}", file=sys.stderr)
            continue
        if not isinstance(msgs, list):
            continue
        for m in msgs:
            if not isinstance(m, dict):
                continue
            author = m.get("author") or {}
            if not isinstance(author, dict):
                continue
            if author.get("bot") or author.get("id", "") in bot_ids:
                continue
            mid = m.get("id", "")
            if not mid:
                continue
            if mid in recorded_ids:
                continue
            findings.append({
                "mid": mid,
                "from": author_label(author, counterpart_map),
                "from_id": author.get("id", ""),
                "timestamp": m.get("timestamp", ""),
                "snippet": (m.get("content") or "").replace("\n", " ")[:140],
                "channel_key": jf.stem.replace("discord_", "").replace("_dm", "_dm"),
                "channel_id": m.get("channel_id", ""),
            })
    findings.sort(key=lambda f: f["timestamp"])
    return findings


def render(findings: list[dict], title: str) -> None:
    if not findings:
        return
    print()
    print("=" * 64)
    print(f"📨 {title} ({len(findings)} 件)")
    print("=" * 64)
    print()
    print("Discord DM への新着 (= bot 自身の send 以外 ∧ ledger 未記録)。")
    print("対応 = 該当 ledger file の entry log に messageId 追記で消える。")
    print()
    for f in findings:
        print(f"🚨 [{f['timestamp']}] from {f['from']} (channel: {f['channel_key']})")
        print(f"   messageId: {f['mid']}")
        if f["snippet"]:
            print(f"   {f['snippet']}")
        print()


def parse_counterparts(items: list[str]) -> dict[str, str]:
    """Parse list of "ID:NAME" strings into dict."""
    out = {}
    for s in items or []:
        if ":" not in s:
            print(f"WARN: --counterpart skipped (no ':'): {s}", file=sys.stderr)
            continue
        cid, name = s.split(":", 1)
        out[cid.strip()] = name.strip()
    return out


def selftest() -> None:
    """Verify regex + harvest + scan logic with synthetic fixtures (generic placeholders)."""
    # Snowflake regex
    assert SNOWFLAKE_RE.findall("message `1234567890123456789`") == ["1234567890123456789"]
    assert SNOWFLAKE_RE.findall("foo 123 bar") == []
    # Multiple IDs (= 17-digit + 19-digit)
    assert SNOWFLAKE_RE.findall("a=12345678901234567 b=9876543210987654321") == [
        "12345678901234567", "9876543210987654321"
    ]
    # Boundary: 16-digit (too short) and 20-digit (too long) excluded
    assert SNOWFLAKE_RE.findall("1234567890123456") == []
    assert SNOWFLAKE_RE.findall("12345678901234567890") == []

    # author_label
    cmap = {"1000000000000000001": "Alice"}
    assert author_label({"id": "1000000000000000001"}, cmap) == "Alice"
    assert author_label({"id": "2000000000000000002", "username": "carol"}, cmap) == "carol"
    assert author_label({"id": "2000000000000000002", "global_name": "Carol",
                         "username": "carol_user"}, cmap) == "Carol"

    # End-to-end fixture (= 4 messages: 2 bot sends + 2 counterpart replies、
    # ledger records 3 IDs leaving 1 unrecorded reply → expected surface)
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        json_dir = tmpdir / "data"
        ledger_dir = tmpdir / "ledger"
        json_dir.mkdir()
        ledger_dir.mkdir()

        BOT_ID = "3000000000000000003"
        COUNTERPART_ID = "1000000000000000001"
        fixture = [
            {"id": "4000000000000000004",
             "author": {"id": BOT_ID, "username": "fixture-bot", "bot": True},
             "timestamp": "2026-06-25T07:17:53.135000+00:00",
             "content": "[bot send 1]"},
            {"id": "4000000000000000005",
             "author": {"id": BOT_ID, "username": "fixture-bot", "bot": True},
             "timestamp": "2026-06-29T07:41:18.472000+00:00",
             "content": "[bot send 2]"},
            {"id": "4000000000000000006",
             "author": {"id": COUNTERPART_ID, "username": "alice_user"},
             "timestamp": "2026-06-29T07:47:40.812000+00:00",
             "content": "[recorded reply]"},
            {"id": "4000000000000000007",
             "author": {"id": COUNTERPART_ID, "username": "alice_user"},
             "timestamp": "2026-06-29T07:52:24.136000+00:00",
             "content": "[UNRECORDED reply — should surface]"},
        ]
        (json_dir / "discord_test_dm.json").write_text(
            json.dumps(fixture, ensure_ascii=False, indent=2))
        # ledger records 3 IDs but NOT 4000000000000000007
        (ledger_dir / "ledger.yaml").write_text(
            "log:\n"
            "  - 'send 4000000000000000004'\n"
            "  - 'send 4000000000000000005'\n"
            "  - 'reply 4000000000000000006'\n"
        )

        recorded = harvest_recorded_ids(ledger_dir, "*.yaml")
        findings = scan_dm_files(json_dir, "discord_*_dm.json",
                                 {BOT_ID}, recorded,
                                 {COUNTERPART_ID: "Alice"})

    assert len(findings) == 1, f"expected 1 finding, got {len(findings)}: {findings}"
    assert findings[0]["mid"] == "4000000000000000007"
    assert findings[0]["from"] == "Alice"
    assert "UNRECORDED" in findings[0]["snippet"]

    print("OK: selftest passed (5 checks)")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Discord bot DM channel の未記録 message surface engine "
                    "(layer 1 generic、 layer 3 thin wrapper から呼ぶ)。",
    )
    ap.add_argument("--bot-id", action="append", default=[],
                    help="Discord user ID of bot accounts to skip (= 我々の send)。 "
                         "repeated 可、 1 つ以上必要。")
    ap.add_argument("--json-dir", type=Path,
                    help="Directory containing Discord DM JSON files "
                         "(= daily fetcher の output 先)")
    ap.add_argument("--json-glob", default="discord_*_dm.json",
                    help='JSON file glob within --json-dir (default: "discord_*_dm.json")')
    ap.add_argument("--ledger-dir", type=Path,
                    help="Directory containing ledger files (text/YAML) "
                         "with messageId 記録")
    ap.add_argument("--ledger-glob", default="*.yaml",
                    help='Ledger file glob within --ledger-dir (default: "*.yaml")')
    ap.add_argument("--counterpart", action="append", default=[],
                    help='"ID:NAME" pair for display name mapping (repeated 可)')
    ap.add_argument("--title", default="Discord bot DM channel の未記録 message",
                    help="Header title for the surface output")
    ap.add_argument("--selftest", action="store_true",
                    help="Run built-in selftest and exit")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return 0

    if not args.bot_id:
        ap.error("--bot-id is required (≥1)")
    if not args.json_dir:
        ap.error("--json-dir is required")
    if not args.ledger_dir:
        ap.error("--ledger-dir is required")

    counterpart_map = parse_counterparts(args.counterpart)
    recorded_ids = harvest_recorded_ids(args.ledger_dir, args.ledger_glob)
    findings = scan_dm_files(args.json_dir, args.json_glob,
                             set(args.bot_id), recorded_ids, counterpart_map)
    render(findings, args.title)
    return 0


if __name__ == "__main__":
    sys.exit(main())
