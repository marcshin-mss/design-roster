// 지라 이력 스냅샷 — Worker 의 지라 계정이 프로젝트를 못 보게 되어(11-07, /dlt · /pel · /launch · /ft-lt 가 0건)
// 같은 계산을 GitHub Actions(갱신 작업의 지라 계정)에서 돌려 data.json(봉인)에 넣는다. 계산 코드는 worker.js 를 그대로 씀.
// 사용: JIRA_EMAIL · JIRA_TOKEN 환경변수 → node jira-snap.mjs → jira-snap.json (build.py 가 읽고 지움 — 공개 배포물에 남지 않게)
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(HERE, "worker.js"), "utf8").replace(/export\s+default\s*\{/, "const __WORKER__ = {");
const W = new Function(src + "\n;return { ftLeadTimes, pelRows, tlRows, dsgRows };")();
const env = { JIRA_EMAIL: process.env.JIRA_EMAIL || "", JIRA_TOKEN: process.env.JIRA_TOKEN || "" };
const out = { at: Date.now() };
for (const [k, fn] of [["dlt", W.dsgRows], ["pel", W.pelRows], ["tl", W.tlRows], ["ftlt", W.ftLeadTimes]]) {
  const t0 = Date.now();
  try { out[k] = await fn(env); console.log(`지라 이력 ${k}: ${out[k].length}행 (${Math.round((Date.now() - t0) / 1000)}초)`); }
  catch (e) { out[k] = null; console.log(`지라 이력 ${k}: 실패 — ${String(e && e.message || e).slice(0, 120)}`); }
}
fs.writeFileSync(path.join(HERE, "jira-snap.json"), JSON.stringify(out));
