#!/usr/bin/env node
// smoke-googleapis.mjs — googleapis / google-auth-library の依存 bump 後 read-only smoke test (対象 dir 自身の node_modules を createRequire で load し、 実 API read か token refresh で更新実体を検証。 書き込み API・token 永続化なし。 規約 = conventions/google-api-direct-access.md)
//
// usage: node smoke-googleapis.mjs <pkg-dir> <creds.json> <mode> [keys.json]
//   pkg-dir   : googleapis を dependencies に持つ dir (= その node_modules が検証対象)
//   creds.json: OAuth token file (refresh_token を含む)。 pkg-dir 相対 or 絶対 path
//   mode      : calendar = calendarList.list / classroom = courses.list /
//               token = access-token refresh のみ (= scope 上 read 対象が無い時の最小 smoke)
//   keys.json : OAuth client keys (installed/web 形式)。 省略時 = <pkg-dir>/gcp-oauth.keys.json
//
// 全 mode read-only。 token event handler も付けないので creds file は書き換わらない。
// 設計動機: major bump の「merge して動くか」 は lockfile でなく install 済み実体で
// 検証すべき — createRequire(<pkg-dir>/package.json) がそれを保証する。
import { createRequire } from "module";
import { readFile } from "fs/promises";
import path from "path";

const [dir, credsFile, mode, keysFile] = process.argv.slice(2);
if (!dir || !credsFile || !mode) {
  console.error("usage: smoke-googleapis.mjs <pkg-dir> <creds.json> <calendar|classroom|token> [keys.json]");
  process.exit(2);
}
const req = createRequire(path.join(dir, "package.json"));
const { google } = req("googleapis");

const resolveIn = (f) => (path.isAbsolute(f) ? f : path.join(dir, f));
const keys = JSON.parse(await readFile(resolveIn(keysFile || "gcp-oauth.keys.json"), "utf8"));
const creds = JSON.parse(await readFile(resolveIn(credsFile), "utf8"));
const k = keys.installed || keys.web;
const client = new google.auth.OAuth2(k.client_id, k.client_secret, k.redirect_uris[0]);
client.setCredentials({ refresh_token: creds.refresh_token });

if (mode === "calendar") {
  const cal = google.calendar({ version: "v3", auth: client });
  const r = await cal.calendarList.list({ maxResults: 50 });
  const items = r.data.items || [];
  console.log(`OK calendar: ${items.length} calendars (first: ${items[0]?.summary ?? "-"})`);
} else if (mode === "classroom") {
  const cr = google.classroom({ version: "v1", auth: client });
  const r = await cr.courses.list({ pageSize: 10 });
  console.log(`OK classroom: ${(r.data.courses || []).length} courses visible`);
} else {
  const t = await client.getAccessToken();
  console.log(`OK token refresh: access_token ${t.token ? "obtained (len " + t.token.length + ")" : "MISSING"}`);
}
