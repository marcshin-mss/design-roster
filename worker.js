/* 디자인실 대시보드 — 공유 기준 저장소 + 재빌드 + 자동 배포 + 회사 계정 로그인
   · KV 바인딩        : ROSTER
   · Secret GATE_HASH  : GATE_PASS 의 SHA-256 (팀장 공용 — 기준 공유·재빌드용)
   · Secret GH_TOKEN   : GitHub PAT (design-roster 의 Actions 읽기·쓰기)
   · Secret DEPLOY_HASH : 배포 전용 암호의 SHA-256 (Marc 전용 — 코드 배포용)
   · Secret GATE_PASS   : 데이터/앱 복호화 비밀번호. 회사 구글 계정으로 인증 통과한 사람에게만 /auth 로 배급.
   공유 기준은 GATE_PASS 로 암호화된 덩어리라 서버도 읽지 못합니다.

   회사 계정 로그인(구글 OAuth):
   · /auth       POST {credential}  — 구글 ID 토큰 검증(도메인 제한) → 통과 시 복호화 키 배급 + 지표 권한 플래그
   · /kpi-allow  POST {credential[,list]} — 지표 이메일 허용목록 읽기/저장(소유자 Marc 전용)
   · KV kpi:allow — 지표 열람 허용 이메일 배열 (없으면 소유자 1명)

   Design Driven(FT) 지라 편집 (Marc 10-30 — 디자이너 전원 허용):
   · Secret JIRA_EMAIL / JIRA_TOKEN : 지라 API 계정 (Marc 가 직접 등록)
   · /auth 가 편집 토큰(12시간, GATE_HASH 로 서명)을 함께 배급 → 대시보드 sessionStorage pxd-et
   · /jira-edit  POST {token,key,set,add,remove} — FT 프로젝트 · 담당자/우선순위/시작일/마감일/라벨만
   · /dd-editors POST {token[,acc]} — 편집 허용 지라 계정 목록(KV dd:editors) 읽기/저장(소유자 전용, 대시보드가 로스터로 자동 동기화)
   · /ft-lt      POST {token[,fresh]} — FT 리드타임(경윤님 기준) 행 + 개발 진입 시각 dvs, KV ft:lt2 3시간 캐시
   · /impact     POST {token,keys[]} — 론치 후 결과(QBR 공유사항·Impact Sharing Date), 1시간 캐시
   · /pel        POST {token} 또는 x-gate — PEL 에픽(7/1 이후) 상태 · 부모 과제 · 담당 · 진행→완료 리드타임, KV pel:v1 3시간 캐시
   · /dlt        POST {token} 또는 x-gate — 디자인 과제(PD · M29CMPROD 에픽) 진행→완료 리드타임 · 주별 처리, KV dlt:v1 3시간 캐시
   · /launch     POST {token} 또는 x-gate — 론치 캘린더(지라 TL, 기한 7/1 이후): 론치 예정일 · 완료 · 연결 키 · 기대효과, KV tl:v1 1시간 캐시 (11-02)
   · /dd-log     POST {token[,key]} — 최근 변경 기록(KV dd:log, 최근 300건)
   · 변경마다 지라에 '대시보드에서 OOO 님이 변경' 코멘트를 남겨 실제 변경자를 기록 */
const ORIGIN = "https://marcshin-mss.github.io";
const RUNWAY_ORIGIN = "https://runway.lab.musinsa.io";   /* Runway 보드 스냅샷을 로그인한 Runway 탭에서 올림 (11-04) */
const SYNC_ITEMS = ["leave", "one", "runway"];               /* 맥 · 브라우저가 필요한 싱크 항목 — 지라는 /refresh */
const KEY = "basis";
const REPO = "marcshin-mss/design-roster";
const REFRESH_WF = "refresh.yml";
const DEPLOY_WF = "deploy.yml";
const COOLDOWN = 90;                       /* 초 — 여러 명이 눌러도 한 번만 돈다 */

/* 회사 계정 로그인 설정 (공개값이라 코드에 둬도 됨) */
const CLIENT_ID = "830037153887-18a8gh7nbeukd1rrsrb6vkt5l6uguf5i.apps.googleusercontent.com";
const OWNER = "marc.shin@musinsa.com";      /* 지표 관리자 */
const DOMAINS = ["musinsa.com", "29cm.co.kr"];
const CERTS = "https://www.googleapis.com/oauth2/v3/certs";

const J = (o, status, cors) =>
  new Response(JSON.stringify(o), { status, headers: { ...cors, "content-type": "application/json" } });

/* ── 구글 ID 토큰 검증 ─────────────────────────────────────── */
function b64u(s) {
  s = String(s).replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4) s += "=";
  const bin = atob(s), u = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
  return u;
}
const b64uStr = s => new TextDecoder().decode(b64u(s));

let JWKS = null, JWKS_AT = 0;
async function jwks() {
  const now = Date.now();
  if (JWKS && now - JWKS_AT < 3600000) return JWKS;
  const r = await fetch(CERTS);
  if (!r.ok) throw new Error("jwks");
  JWKS = (await r.json()).keys; JWKS_AT = now;
  return JWKS;
}

/* 유효하면 검증된 이메일(소문자)을 돌려주고, 아니면 throw */
async function verifyGoogle(token) {
  const p = String(token || "").split(".");
  if (p.length !== 3) throw new Error("format");
  const header = JSON.parse(b64uStr(p[0]));
  const payload = JSON.parse(b64uStr(p[1]));
  if (header.alg !== "RS256") throw new Error("alg");
  const jwk = (await jwks()).find(k => k.kid === header.kid);
  if (!jwk) throw new Error("kid");
  const key = await crypto.subtle.importKey(
    "jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
  const ok = await crypto.subtle.verify(
    "RSASSA-PKCS1-v1_5", key, b64u(p[2]), new TextEncoder().encode(p[0] + "." + p[1]));
  if (!ok) throw new Error("sig");
  if (payload.iss !== "accounts.google.com" && payload.iss !== "https://accounts.google.com") throw new Error("iss");
  if (payload.aud !== CLIENT_ID) throw new Error("aud");
  const now = Math.floor(Date.now() / 1000);
  if (!payload.exp || payload.exp < now - 60) throw new Error("exp");
  if (payload.email_verified !== true && payload.email_verified !== "true") throw new Error("unverified");
  const email = String(payload.email || "").toLowerCase();
  if (!DOMAINS.includes(email.split("@")[1] || "")) throw new Error("domain");
  return email;
}

/* ── 배포 토큰 : 소유자(Marc) 구글 로그인 때 /auth 가 발급, /publish 가 검증 — 배포 암호 없이 배포 (Marc 10-29) ── */
const DEPLOY_TTL = 24 * 3600;
async function hmac(secret, msg) {
  const k = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", k, new TextEncoder().encode(msg)));
  return btoa(String.fromCharCode(...sig)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
async function deployToken(env, email) {
  const body = btoa(JSON.stringify({ e: email, x: Math.floor(Date.now() / 1000) + DEPLOY_TTL })).replace(/=+$/, "");
  return body + "." + await hmac("deploy:" + env.DEPLOY_HASH, body);
}
async function deployTokenOK(env, tok) {
  try {
    const [body, sig] = String(tok || "").split(".");
    if (!body || !sig || !env.DEPLOY_HASH) return false;
    if (sig !== await hmac("deploy:" + env.DEPLOY_HASH, body)) return false;
    const p = JSON.parse(atob(body));
    return p.e === OWNER && p.x > Math.floor(Date.now() / 1000);
  } catch (e) { return false; }
}

async function allowList(env) {
  let a;
  try { a = JSON.parse((await env.ROSTER.get("kpi:allow")) || "null"); } catch (e) { a = null; }
  if (!Array.isArray(a)) a = [OWNER];
  return a.map(x => String(x).toLowerCase());
}

/* ── Design Driven 편집 ─────────────────────────────────────── */
const JIRA_BASE = "https://musinsa-oneteam.atlassian.net";
const EDIT_TTL = 12 * 3600;
const DD_PROJECT = "FT";
const DD_PRI = ["Highest", "High", "Medium", "Low", "Lowest"];
const DD_START = "customfield_10015";            /* 시작 날짜 */
/* 봇·프로세스용 라벨은 대시보드에서 지우지 못하게 */
const DD_LOCK = /^(one|fasttrack|fast-track-.*|conveyor.*|auto-.*|pel.*|ux-ft.*|DUE_.*|.*-bot|.*리뷰제외|standby.*|seamless-.*|track-.*|test)$/i;

async function editToken(env, email) {
  const body = btoa(JSON.stringify({ e: email, x: Math.floor(Date.now() / 1000) + EDIT_TTL })).replace(/=+$/, "");
  return body + "." + await hmac("edit:" + env.GATE_HASH, body);
}
async function editTokenEmail(env, tok) {
  try {
    const [body, sig] = String(tok || "").split(".");
    if (!body || !sig || !env.GATE_HASH) return "";
    if (sig !== await hmac("edit:" + env.GATE_HASH, body)) return "";
    const p = JSON.parse(atob(body));
    return p.x > Math.floor(Date.now() / 1000) ? String(p.e || "").toLowerCase() : "";
  } catch (e) { return ""; }
}
async function jira(env, method, path, body) {
  const r = await fetch(JIRA_BASE + path, { method,
    headers: { "authorization": "Basic " + btoa(env.JIRA_EMAIL + ":" + env.JIRA_TOKEN),
               "accept": "application/json", "content-type": "application/json" },
    body: body ? JSON.stringify(body) : undefined });
  const t = await r.text();
  let j = null; try { j = t ? JSON.parse(t) : null; } catch (e) { j = null; }
  return { ok: r.ok, status: r.status, j, t };
}
/* ── FT 리드타임 (경윤님 10/21 기준) ─────────────────────────────
   대상: FT Initiative 중 배포완료·론치완료에 처음 도달한 건. test·9월퀵윈·bot-duplicate 라벨 제외
   시작: Away·Home = SUGGESTED/Backlog → 활성 상태 첫 전이 / design-driven = 디자인중 첫 진입
   끝:   배포완료·론치완료 중 먼저 도달한 시각 · 단위: 근무일(주말·공휴일 제외, 소수)
   HOLD 기간 차감 · 착수→배포 6시간 이내는 사후 정리로 제외
   트랙: design-driven 라벨/[design-driven] 제목 > fast-track-away > Home
   보조(디자인 몫): dd 의 디자인중 → 개발 착수(핸드오프) · 개발 착수 → 배포
   진행 중(statusCategory In Progress, 아직 배포 전): 착수 후 경과 근무일 ag (HOLD 뺌) */
const LT_HOL = new Set(["2026-01-01","2026-02-16","2026-02-17","2026-02-18","2026-03-02","2026-05-05","2026-05-25",
  "2026-06-03","2026-08-17","2026-09-24","2026-09-25","2026-09-28","2026-10-05","2026-10-09","2026-12-25"]);
const LT_PRE = new Set(["SUGGESTED", "Backlog"]), LT_END = new Set(["배포완료", "론치완료"]);
const LT_DEV = new Set(["개발중", "개발완료", "QA중", "Waiting For Review", "진행중", "배포완료", "론치완료"]);
const LT_EXCL = new Set(["test", "9월퀵윈", "bot-duplicate"]);
const KST_MS = 9 * 3600e3;
function ltMs(v) { if (typeof v === "number") return v < 1e12 ? v * 1000 : v; const t = Date.parse(String(v).replace(/([+-]\d{2})(\d{2})$/, "$1:$2")); return isNaN(t) ? null : t; }
function ltWork(a, b) {                 /* 근무일 안에 든 시간(일) */
  if (!(b > a)) return 0;
  let t = a, tot = 0;
  while (t < b) {
    const k = new Date(t + KST_MS), day0 = Date.UTC(k.getUTCFullYear(), k.getUTCMonth(), k.getUTCDate()) - KST_MS;
    const nxt = Math.min(b, day0 + 864e5), dow = k.getUTCDay(), ds = k.toISOString().slice(0, 10);
    if (dow !== 0 && dow !== 6 && !LT_HOL.has(ds)) tot += nxt - t;
    t = nxt;
  }
  return tot / 864e5;
}
const r2 = v => Math.round(v * 100) / 100;
function ltCalc(iss, tr) {             /* iss {k,t,lb[],cr}, tr [[ms,from,to]] 시간순 */
  const lb = iss.lb || [], dd = lb.includes("design-driven") || /\[design-driven\]/i.test(iss.t || "");
  const track = dd ? "d" : lb.includes("fast-track-away") ? "a" : "h";
  const first = p => { const x = tr.find(([, f, to]) => p(f, to)); return x ? x[0] : null; };
  const end = first((f, to) => LT_END.has(to));
  const start = dd ? first((f, to) => to === "디자인중") : first((f, to) => LT_PRE.has(f) && !LT_PRE.has(to));
  const o = { k: iss.k, t: iss.t, tr: track, cr: iss.cr, st: iss.st || "" };
  const holdIn = (a, b) => { let hd = 0, h0 = null;
    for (const [t, f, to] of tr) {
      if (to === "HOLD" && h0 == null) h0 = t;
      else if (f === "HOLD" && h0 != null) { if (t > a && h0 < b) hd += ltWork(Math.max(h0, a), Math.min(t, b)); h0 = null; }
    }
    if (h0 != null && h0 < b) hd += ltWork(Math.max(h0, a), b);
    return hd; };
  { const dvT = first((f, to) => LT_DEV.has(to) && !LT_END.has(to)); if (dvT != null && (start == null || dvT >= start)) o.dvs = dvT; }   /* 개발 단계 첫 진입 시각 — 모든 트랙(Marc 10-31 「PEL 은 디자인 착수 → 개발 전달 → 개발」) */
  if (end == null) {                     /* 아직 배포 전 = 진행 중 경과(경윤님 M2 In-Progress aging) */
    o.x = "open"; if (start != null) { const now = Date.now(); o.s = start; o.ag = r2(ltWork(start, now) - holdIn(start, now)); } return o; }
  o.e = end;
  if (start == null || start >= end) { o.x = "no-start"; return o; }
  o.s = start;
  if (end - start <= 6 * 3600e3) { o.x = "bulk"; return o; }
  const hold = holdIn(start, end);
  o.lt = r2(ltWork(start, end) - hold);
  const cr = ltMs(iss.cr); if (cr != null) o.in = r2(ltWork(cr, end) - hold);
  if (dd) { const dv = first((f, to) => LT_DEV.has(to)); if (dv != null && dv >= start && dv <= end) { o.dz = r2(ltWork(start, dv)); o.dv = r2(ltWork(dv, end)); } }
  return o;
}
async function ftLeadTimes(env) {
  const jql = 'project = FT AND issuetype = Initiative AND (status CHANGED TO "배포완료" OR status CHANGED TO "론치완료" OR statusCategory = "In Progress")';
  const iss = []; let tok;
  for (let i = 0; i < 20; i++) {
    const r = await jira(env, "POST", "/rest/api/3/search/jql", { jql, fields: ["summary", "labels", "created", "status"], maxResults: 100, nextPageToken: tok });
    if (!r.ok || !r.j) throw new Error("search " + r.status);
    (r.j.issues || []).forEach(x => { const f = x.fields || {}; iss.push({ id: String(x.id), k: x.key, t: f.summary || "", lb: f.labels || [], cr: f.created, st: (f.status || {}).name || "" }); });
    tok = r.j.nextPageToken; if (!tok || r.j.isLast) break;
  }
  const keep = iss.filter(x => !x.lb.some(l => LT_EXCL.has(l)));
  const TR = {}; keep.forEach(x => TR[x.id] = []);
  for (let i = 0; i < keep.length; i += 1000) {
    let nt;
    for (let p = 0; p < 50; p++) {
      const r = await jira(env, "POST", "/rest/api/3/changelog/bulkfetch", { issueIdsOrKeys: keep.slice(i, i + 1000).map(x => x.id), fieldIds: ["status"], maxResults: 10000, nextPageToken: nt });
      if (!r.ok || !r.j) throw new Error("changelog " + r.status);
      (r.j.issueChangeLogs || []).forEach(c => { const L = TR[String(c.issueId)]; if (!L) return;
        (c.changeHistories || []).forEach(h => { const t = ltMs(h.created); (h.items || []).forEach(it => { if ((it.fieldId || it.field) === "status") L.push([t, it.fromString, it.toString]); }); }); });
      nt = r.j.nextPageToken; if (!nt) break;
    }
  }
  return keep.map(x => ltCalc(x, (TR[x.id] || []).filter(r => r[0] != null).sort((a, b) => a[0] - b[0])));
}

/* ── 론치 후 결과 — Tech PMO 표준 필드(QBR 공유사항 · Impact Sharing Date)를 대시보드가 보내는 디자인 과제 키로 읽음 ── */
const IMP_QBR = "customfield_10710", IMP_DATE = "customfield_19702", IMP_HC = "customfield_10071";   /* Health Check (GREEN · YELLOW · RED · Closed) — Tech MBR 콜아웃 기준 (11-02) */
function impAdf(n) {                     /* ADF → 글 (문단·목록·제목 줄바꿈) */
  if (!n) return "";
  if (typeof n === "string") return n;
  if (n.type === "text") return n.text || "";
  if (n.type === "hardBreak") return "\n";
  const c = (n.content || []).map(impAdf).join("");
  if (n.type === "listItem") return "* " + c.replace(/\n+$/, "") + "\n";
  if (n.type === "paragraph" || n.type === "heading") return c + "\n";
  return c;
}
async function impactRows(env, keys) {
  const out = []; let bad = new Set();
  for (let i = 0; i < keys.length; i += 100) {
    let ks = keys.slice(i, i + 100), tok;
    for (let p = 0; p < 6 && ks.length; p++) {
      const r = await jira(env, "POST", "/rest/api/3/search/jql", { jql: "key in (" + ks.join(",") + ")", fields: ["summary", "status", "resolutiondate", IMP_QBR, IMP_DATE, IMP_HC, "duedate"], maxResults: 100, nextPageToken: tok });
      if (r.status === 400 && /does not exist|존재하지/.test(r.t)) {   /* 없어진 키는 빼고 다시 */
        const b = [...r.t.matchAll(/'([A-Z][A-Z0-9]+-\d+)'/g)].map(m => m[1]); if (!b.length) throw new Error("impact 400");
        b.forEach(k => bad.add(k)); ks = ks.filter(k => !bad.has(k)); tok = undefined; continue;
      }
      if (!r.ok || !r.j) throw new Error("impact " + r.status);
      (r.j.issues || []).forEach(x => { const f = x.fields || {}, q = f[IMP_QBR];
        out.push([x.key, f.summary || "", (f.status || {}).name || "", String(f.resolutiondate || "").slice(0, 10), String(f[IMP_DATE] || "").slice(0, 10), q == null ? null : (typeof q === "string" ? q : impAdf(q)), String(((f[IMP_HC] || {}).value) || ""), String(f.duedate || "").slice(0, 10)]); });
      tok = r.j.nextPageToken; if (!tok) break;
    }
  }
  return out;
}

/* ── 론치 캘린더 (Marc 11-02) — TL 티켓 하나 = 론치 하나. 기한 = 론치 예정일, 상태 SUGGESTED(예정) · 완료, 연결 = TM · FT · PD 키
   행 = [TL 키, 론치일, 완료 1/0, 해결일, 연결 키[], 제목, 기대효과(설명의 '기대효과 · Success Criteria' 첫 3줄)] */
function tlEffect(txt) {
  const L = String(txt || "").split("\n").map(l => l.trim());
  let i = L.findIndex(l => /기대\s*효과|Success\s*Criteria/i.test(l)); if (i < 0) return "";
  const out = [];
  for (let j = i + 1; j < L.length && out.length < 3; j++) {
    const l = L[j]; if (!l) { if (out.length) { const nx = L[j + 1] || ""; if (nx && !/^[*•\-◦]/.test(nx)) break; } continue; }
    if (/^cc\b/i.test(l) || /^\(?cc\./i.test(l)) break;
    if (out.length && !/^[*•\-◦(]/.test(l) && l.length < 30) break;
    const t = l.replace(/^[*•\-◦\s]+/, "").replace(/\s*\/?\s*\(cc\.[\s\S]*$/, "").trim(); if (t) out.push(t);
  }
  return out.join(" / ").slice(0, 220);
}
async function tlRows(env) {
  const jql = 'project = TL AND duedate >= "2026-07-01"', out = []; let tok;
  for (let p = 0; p < 20; p++) {
    const r = await jira(env, "POST", "/rest/api/3/search/jql", { jql, fields: ["summary", "status", "duedate", "issuelinks", "resolutiondate", "description"], maxResults: 100, nextPageToken: tok });
    if (!r.ok || !r.j) throw new Error("tl search " + r.status);
    (r.j.issues || []).forEach(x => { const f = x.fields || {}, st = f.status || {};
      const ks = (f.issuelinks || []).map(l => ((l.outwardIssue || l.inwardIssue || {}).key)).filter(Boolean);
      const done = (st.statusCategory || {}).key === "done" || /완료/.test(st.name || "") ? 1 : 0;
      out.push([x.key, String(f.duedate || "").slice(0, 10), done, String(f.resolutiondate || "").slice(0, 10), ks, String(f.summary || "").replace(/\s+/g, " ").trim().slice(0, 90), tlEffect(impAdf(f.description))]); });
    tok = r.j.nextPageToken; if (!tok || r.j.isLast) break;
  }
  return out;
}

/* ── PEL 진행 상태 (Marc 10-31) ─────────────────────────────
   대상: PEL 프로젝트 Epic, 2026-07-01 이후 생성 · 부모(FT·TM·PEL 이니셔티브)와 담당을 그대로 넘기고 분류는 대시보드가 함
   시작: 제안·대기(SUGGESTED·Backlog·할 일) → 다른 상태 첫 전이. 처음부터 진행 상태로 만들어졌으면 생성 시각
   끝: 완료 계열 첫 진입 · 근무일(FT 리드타임과 같은 달력) · HOLD 기간 뺌 · h = 실제 경과 시간(6시간 안 일괄 처리 판별용) */
const PEL_PRE = new Set(["SUGGESTED", "Backlog", "할 일", "To Do", "TODO", "Open"]);
const PEL_END = new Set(["완료", "Done", "Closed", "배포완료", "론치완료", "해결됨", "Resolved"]);
function pelCalc(iss, tr) {
  const o = { k: iss.k, t: iss.t, st: iss.st, sc: iss.sc, asg: iss.asg, par: iss.par, pt: iss.pt, lb: iss.lb, cr: ltMs(iss.cr) };
  const cr = o.cr, firstFrom = tr.length ? tr[0][1] : null;
  let start = null;
  const s1 = tr.find(([, f, to]) => PEL_PRE.has(f) && !PEL_PRE.has(to)); if (s1) start = s1[0];
  if (start == null && cr != null && ((firstFrom && !PEL_PRE.has(firstFrom)) || (!tr.length && iss.sc !== "new"))) start = cr;
  const e1 = tr.find(([, , to]) => PEL_END.has(to)); let end = e1 ? e1[0] : null;
  if (end == null && iss.sc === "done") { const rd = ltMs(iss.rd); if (rd != null) end = rd; }
  const holdIn = (a, b) => { let hd = 0, h0 = null;
    for (const [t, f, to] of tr) {
      if (to === "HOLD" && h0 == null) h0 = t;
      else if (f === "HOLD" && h0 != null) { if (t > a && h0 < b) hd += ltWork(Math.max(h0, a), Math.min(t, b)); h0 = null; }
    }
    if (h0 != null && h0 < b) hd += ltWork(Math.max(h0, a), b);
    return hd; };
  if (start != null) o.s = start;
  if (end == null) { if (start != null && iss.sc !== "new") { const now = Date.now(); o.ag = r2(ltWork(start, now) - holdIn(start, now)); } return o; }
  o.e = end;
  if (start == null || start > end) { o.x = "no-start"; return o; }
  o.h = r2((end - start) / 3600e3);
  o.lt = r2(Math.max(0, ltWork(start, end) - holdIn(start, end)));
  return o;
}
async function pelRows(env) {
  const jql = 'project = PEL AND issuetype = Epic AND created >= "2026-07-01"';
  const iss = []; let tok;
  for (let i = 0; i < 20; i++) {
    const r = await jira(env, "POST", "/rest/api/3/search/jql", { jql, fields: ["summary", "status", "assignee", "parent", "created", "labels", "resolutiondate"], maxResults: 100, nextPageToken: tok });
    if (!r.ok || !r.j) throw new Error("pel search " + r.status);
    (r.j.issues || []).forEach(x => { const f = x.fields || {}, p = f.parent || {}, pf = p.fields || {}, st = f.status || {};
      iss.push({ id: String(x.id), k: x.key, t: f.summary || "", st: st.name || "", sc: (st.statusCategory || {}).key || "",
        asg: String((f.assignee || {}).displayName || "").split("/")[0].trim(), par: p.key || "", pt: pf.summary || "",
        lb: f.labels || [], cr: f.created, rd: f.resolutiondate || "" }); });
    tok = r.j.nextPageToken; if (!tok || r.j.isLast) break;
  }
  const TR = {}; iss.forEach(x => TR[x.id] = []);
  for (let i = 0; i < iss.length; i += 1000) {
    let nt;
    for (let p = 0; p < 50; p++) {
      const r = await jira(env, "POST", "/rest/api/3/changelog/bulkfetch", { issueIdsOrKeys: iss.slice(i, i + 1000).map(x => x.id), fieldIds: ["status"], maxResults: 10000, nextPageToken: nt });
      if (!r.ok || !r.j) throw new Error("pel changelog " + r.status);
      (r.j.issueChangeLogs || []).forEach(c => { const L = TR[String(c.issueId)]; if (!L) return;
        (c.changeHistories || []).forEach(h => { const t = ltMs(h.created); (h.items || []).forEach(it => { if ((it.fieldId || it.field) === "status") L.push([t, it.fromString, it.toString]); }); }); });
      nt = r.j.nextPageToken; if (!nt) break;
    }
  }
  return iss.map(x => pelCalc(x, (TR[x.id] || []).filter(r => r[0] != null).sort((a, b) => a[0] - b[0])));
}

/* ── 디자인 리드타임 · 처리량 (Marc 10-31 「AI 활용 · 서면보고로 리드타임이 줄고 처리 건수가 느는지 감지」) ──
   대상: PD(무신사) · M29CMPROD(29CM) Epic = 이니셔티브 하나의 디자인 과제 · 7/1 이후 완료 + 지금 진행 중
   시작: 할 일 계열(statusCategory new) → 다른 상태 첫 전이 (처음부터 진행이면 생성 시각) · 끝: 완료 계열 첫 진입
   근무일 · HOLD/보류 뺌 · h = 실제 경과 시간 */
async function statusCats(env) {
  const r = await jira(env, "GET", "/rest/api/3/status"); const M = {};
  if (r.ok && Array.isArray(r.j)) r.j.forEach(x => { const n = x.name, c = (x.statusCategory || {}).key; if (n && c && !M[n]) M[n] = c; });
  return M;
}
function dsgCalc(iss, tr, CAT) {
  const cat = n => CAT[n] || (PEL_PRE.has(n) ? "new" : PEL_END.has(n) ? "done" : "indeterminate"), isH = n => /HOLD|보류/i.test(String(n || ""));
  const o = { k: iss.k, t: iss.t, st: iss.st, sc: iss.sc, asg: iss.asg, par: iss.par, pt: iss.pt, lb: iss.lb, cr: ltMs(iss.cr) };
  let start = null; const s1 = tr.find(([, f, to]) => cat(f) === "new" && cat(to) !== "new"); if (s1) start = s1[0];
  if (start == null && o.cr != null && ((tr.length && cat(tr[0][1]) !== "new") || (!tr.length && iss.sc !== "new"))) start = o.cr;
  const e1 = tr.find(([, , to]) => cat(to) === "done"); let end = e1 ? e1[0] : null;
  if (end == null && iss.sc === "done") { const rd = ltMs(iss.rd); if (rd != null) end = rd; }
  const holdIn = (a, b) => { let hd = 0, h0 = null;
    for (const [t, f, to] of tr) {
      if (isH(to) && h0 == null) h0 = t;
      else if (isH(f) && !isH(to) && h0 != null) { if (t > a && h0 < b) hd += ltWork(Math.max(h0, a), Math.min(t, b)); h0 = null; }
    }
    if (h0 != null && h0 < b) hd += ltWork(Math.max(h0, a), b);
    return hd; };
  if (start != null) o.s = start;
  if (end == null) { if (start != null && iss.sc !== "new") { const now = Date.now(); o.ag = r2(Math.max(0, ltWork(start, now) - holdIn(start, now))); } return o; }
  o.e = end;
  if (start == null || start > end) { o.x = "no-start"; return o; }
  o.h = r2((end - start) / 3600e3);
  o.lt = r2(Math.max(0, ltWork(start, end) - holdIn(start, end)));
  return o;
}
async function dsgRows(env) {
  const jql = 'project in (PD, M29CMPROD) AND issuetype = Epic AND (resolved >= "2026-07-01" OR statusCategory = "In Progress")';
  const iss = []; let tok;
  for (let i = 0; i < 30; i++) {
    const r = await jira(env, "POST", "/rest/api/3/search/jql", { jql, fields: ["summary", "status", "assignee", "parent", "created", "labels", "resolutiondate"], maxResults: 100, nextPageToken: tok });
    if (!r.ok || !r.j) throw new Error("dlt search " + r.status);
    (r.j.issues || []).forEach(x => { const f = x.fields || {}, p = f.parent || {}, pf = p.fields || {}, st = f.status || {};
      iss.push({ id: String(x.id), k: x.key, t: f.summary || "", st: st.name || "", sc: (st.statusCategory || {}).key || "",
        asg: String((f.assignee || {}).displayName || "").split("/")[0].trim(), par: p.key || "", pt: pf.summary || "",
        lb: f.labels || [], cr: f.created, rd: f.resolutiondate || "" }); });
    tok = r.j.nextPageToken; if (!tok || r.j.isLast) break;
  }
  const CAT = await statusCats(env), TR = {}; iss.forEach(x => TR[x.id] = []);
  for (let i = 0; i < iss.length; i += 1000) {
    let nt;
    for (let p = 0; p < 50; p++) {
      const r = await jira(env, "POST", "/rest/api/3/changelog/bulkfetch", { issueIdsOrKeys: iss.slice(i, i + 1000).map(x => x.id), fieldIds: ["status"], maxResults: 10000, nextPageToken: nt });
      if (!r.ok || !r.j) throw new Error("dlt changelog " + r.status);
      (r.j.issueChangeLogs || []).forEach(c => { const L = TR[String(c.issueId)]; if (!L) return;
        (c.changeHistories || []).forEach(h => { const t = ltMs(h.created); (h.items || []).forEach(it => { if ((it.fieldId || it.field) === "status") L.push([t, it.fromString, it.toString]); }); }); });
      nt = r.j.nextPageToken; if (!nt) break;
    }
  }
  return iss.map(x => dsgCalc(x, (TR[x.id] || []).filter(r => r[0] != null).sort((a, b) => a[0] - b[0]), CAT));
}

/* ── 지라 변경 → 바로 재빌드 (Marc 11-04 「티켓 상태나 정보를 지라나 로스터에서 수정하면 바로 지라 연동」)
   · 대시보드(로스터)에서 고치면: /jira-edit · /tk-edit 성공 직후 refresh.yml 실행
   · 지라에서 직접 고치면: Worker 크론(평일 09~20시 5분마다)이 디자이너 담당 · FT 이슈의 최근 변경을 보고 새 변경이 있으면 실행
   · refresh.yml 은 concurrency(대기 1건)라 여러 번 불러도 마지막 변경까지 한 번 더 빌드하고 끝남 */
async function jiraKick(env, why) {
  if (!env.GH_TOKEN) return false;
  const t = Math.floor(Date.now() / 1000), last = +((await env.ROSTER.get("refresh:at")) || 0);
  if (t - last < 20) return true;                       /* 연속 클릭은 한 번으로 */
  await env.ROSTER.put("refresh:at", String(t));
  await env.ROSTER.put("jira:kick", JSON.stringify({ at: new Date().toISOString(), why: String(why || "").slice(0, 60) }));
  const r = await dispatch(env, REFRESH_WF);
  return r.status === 204;
}
async function jiraWatch(env) {
  if (!env.JIRA_TOKEN || !env.GH_TOKEN) return;
  const acc = await ddEditors(env);
  const who = acc.length ? "assignee in (" + acc.map(a => '"' + a + '"').join(",") + ") OR " : "";
  const jql = "(" + who + "project = FT) AND updated >= \"-15m\" ORDER BY updated DESC";
  const r = await jira(env, "POST", "/rest/api/3/search/jql", { jql, fields: ["updated"], maxResults: 1 });
  const top = r.ok && r.j && r.j.issues && r.j.issues[0];
  if (!top) return;
  const up = Date.parse(top.fields && top.fields.updated), seen = Date.parse((await env.ROSTER.get("jira:seen")) || "1970-01-01T00:00:00Z");
  if (!(up > seen)) return;
  await env.ROSTER.put("jira:seen", new Date(up).toISOString());
  await jiraKick(env, "jira " + top.key);
}

async function ddEditors(env) {
  try { const a = JSON.parse((await env.ROSTER.get("dd:editors")) || "null"); return Array.isArray(a) ? a : []; }
  catch (e) { return []; }
}
/* 로그인 이메일 → 지라 계정. 하루 캐시 */
async function jiraAccountOf(env, email) {
  const ck = "dd:acc:" + email, c = await env.ROSTER.get(ck);
  if (c) return JSON.parse(c);
  const r = await jira(env, "GET", "/rest/api/3/user/search?query=" + encodeURIComponent(email));
  const u = r.ok && Array.isArray(r.j) ? (r.j.find(x => String(x.emailAddress || "").toLowerCase() === email) || (r.j.length === 1 ? r.j[0] : null)) : null;
  const v = u ? { id: u.accountId, name: String(u.displayName || "").split("/")[0].trim() } : null;
  if (v) await env.ROSTER.put(ck, JSON.stringify(v), { expirationTtl: 86400 });
  return v;
}
const ddDay = s => s == null || s === "" ? null : (/^\d{4}-\d{2}-\d{2}$/.test(String(s)) ? String(s) : undefined);
function ddPick(f) {
  const a = f.assignee || null;
  return { pri: (f.priority || {}).name || "", sd: f[DD_START] || "", du: f.duedate || "",
           labs: f.labels || [], acc: a ? a.accountId : "", asg: a ? String(a.displayName || "").split("/")[0].trim() : "" };
}

async function dispatch(env, wf) {
  const url = "https://api.github.com/repos/" + REPO + "/actions/workflows/" + wf + "/dispatches";
  return fetch(url, { method: "POST",
    headers: { "authorization": "Bearer " + env.GH_TOKEN,
               "accept": "application/vnd.github+json",
               "x-github-api-version": "2022-11-28",
               "user-agent": "design-roster-sync",
               "content-type": "application/json" },
    body: JSON.stringify({ ref: "main" }) });
}

export default {
  async scheduled(ev, env, ctx) { ctx.waitUntil(jiraWatch(env).catch(() => null)); },
  async fetch(req, env) {
    const path0 = new URL(req.url).pathname, reqOrigin = req.headers.get("origin") || "";
    const cors = {
      "Access-Control-Allow-Origin": (reqOrigin === RUNWAY_ORIGIN && (path0 === "/rw-push" || path0 === "/sync-done" || path0 === "/sync-req")) ? RUNWAY_ORIGIN : ORIGIN,
      "Access-Control-Allow-Methods": "GET,PUT,POST,OPTIONS",
      "Access-Control-Allow-Headers": "content-type,x-gate,x-deploy,x-deploy-token",
      "Access-Control-Max-Age": "86400",
    };
    if (req.method === "OPTIONS") return new Response(null, { headers: cors });

    const path = new URL(req.url).pathname;
    const gateOK = () => {
      const g = (req.headers.get("x-gate") || "").toLowerCase();
      return !!env.GATE_HASH && g === env.GATE_HASH.toLowerCase();
    };
    const deployOK = () => {
      const g = (req.headers.get("x-deploy") || "").toLowerCase();
      return !!env.DEPLOY_HASH && g === env.DEPLOY_HASH.toLowerCase();
    };

    /* ── 회사 계정 로그인 : 구글 토큰 검증 → 복호화 키 배급 ── */
    if (req.method === "POST" && path === "/auth") {
      let body; try { body = await req.json(); } catch (e) { return J({ ok: false, error: "json" }, 400, cors); }
      let email;
      try { email = await verifyGoogle(body && body.credential); }
      catch (e) { return J({ ok: false, error: "auth" }, 403, cors); }
      if (!env.GATE_PASS) return J({ ok: false, error: "no-key" }, 501, cors);
      const allow = await allowList(env);
      return J({ ok: true, email, key: env.GATE_PASS,
                 kpi: allow.includes(email), admin: email === OWNER,
                 deploy: email === OWNER && env.DEPLOY_HASH ? await deployToken(env, email) : undefined,
                 edit: env.GATE_HASH ? await editToken(env, email) : undefined }, 200, cors);
    }

    /* ── 지표 허용목록 읽기/저장 (소유자 전용) ── */
    if (req.method === "POST" && path === "/kpi-allow") {
      let body; try { body = await req.json(); } catch (e) { return J({ ok: false, error: "json" }, 400, cors); }
      let email;
      try { email = await verifyGoogle(body && body.credential); }
      catch (e) { return J({ ok: false, error: "auth" }, 403, cors); }
      if (email !== OWNER) return J({ ok: false, error: "forbidden" }, 403, cors);
      if (Array.isArray(body.list)) {
        const clean = [...new Set(body.list.map(x => String(x).toLowerCase().trim()).filter(x => /.+@.+\..+/.test(x)))];
        await env.ROSTER.put("kpi:allow", JSON.stringify(clean));
        return J({ ok: true, list: clean }, 200, cors);
      }
      return J({ ok: true, list: await allowList(env) }, 200, cors);
    }

    /* ── Design Driven: 편집 허용 계정 목록 (소유자 전용) ── */
    if (req.method === "POST" && path === "/dd-editors") {
      let b; try { b = await req.json(); } catch (e) { return J({ ok: false, error: "json" }, 400, cors); }
      const email = await editTokenEmail(env, b && b.token);
      if (email !== OWNER) return J({ ok: false, error: "forbidden" }, 403, cors);
      if (Array.isArray(b.acc)) {
        const clean = [...new Set(b.acc.map(String).filter(x => /^[\w:-]{6,80}$/.test(x)))].slice(0, 200);
        await env.ROSTER.put("dd:editors", JSON.stringify(clean));
        return J({ ok: true, n: clean.length }, 200, cors);
      }
      return J({ ok: true, acc: await ddEditors(env) }, 200, cors);
    }

    /* ── FT 리드타임 (경윤님 기준, 3시간 캐시) ── */
    if (req.method === "POST" && path === "/ft-lt") {
      let b; try { b = await req.json(); } catch (e) { return J({ ok: false, error: "json" }, 400, cors); }
      const email = await editTokenEmail(env, b && b.token);
      if (!email && !gateOK()) return J({ ok: false, error: "auth" }, 403, cors);   /* 편집 토큰 또는 팀 공용 게이트 (10-31) */
      let c = null; try { c = JSON.parse((await env.ROSTER.get("ft:lt2")) || "null"); } catch (e) { c = null; }
      if (c && !(b.fresh && email === OWNER) && Date.now() - c.at < 3 * 3600e3) return J({ ok: true, at: c.at, rows: c.rows, cached: true }, 200, cors);
      if (!env.JIRA_EMAIL || !env.JIRA_TOKEN) return J({ ok: false, error: "no-jira" }, 501, cors);
      try { const rows = await ftLeadTimes(env); c = { at: Date.now(), rows }; await env.ROSTER.put("ft:lt2", JSON.stringify(c)); return J({ ok: true, at: c.at, rows }, 200, cors); }
      catch (e) { if (c) return J({ ok: true, at: c.at, rows: c.rows, stale: true }, 200, cors); return J({ ok: false, error: String(e && e.message || e) }, 502, cors); }
    }

    /* ── PEL 진행 상태 (3시간 캐시) — 편집 토큰 또는 팀 공용 게이트 ── */
    if (req.method === "POST" && path === "/pel") {
      let b; try { b = await req.json(); } catch (e) { b = {}; }
      const email = await editTokenEmail(env, b && b.token);
      if (!email && !gateOK()) return J({ ok: false, error: "auth" }, 403, cors);
      let c = null; try { c = JSON.parse((await env.ROSTER.get("pel:v1")) || "null"); } catch (e) { c = null; }
      if (c && !(b.fresh && email === OWNER) && Date.now() - c.at < 3 * 3600e3) return J({ ok: true, at: c.at, rows: c.rows, cached: true }, 200, cors);
      if (!env.JIRA_EMAIL || !env.JIRA_TOKEN) return J({ ok: false, error: "no-jira" }, 501, cors);
      try { const rows = await pelRows(env); c = { at: Date.now(), rows }; await env.ROSTER.put("pel:v1", JSON.stringify(c)); return J({ ok: true, at: c.at, rows }, 200, cors); }
      catch (e) { if (c) return J({ ok: true, at: c.at, rows: c.rows, stale: true }, 200, cors); return J({ ok: false, error: String(e && e.message || e) }, 502, cors); }
    }

    /* ── 론치 캘린더 (1시간 캐시) — 편집 토큰 또는 팀 공용 게이트 ── */
    if (req.method === "POST" && path === "/launch") {
      let b; try { b = await req.json(); } catch (e) { b = {}; }
      const email = await editTokenEmail(env, b && b.token);
      if (!email && !gateOK()) return J({ ok: false, error: "auth" }, 403, cors);
      let c = null; try { c = JSON.parse((await env.ROSTER.get("tl:v1")) || "null"); } catch (e) { c = null; }
      if (c && !(b.fresh && email === OWNER) && Date.now() - c.at < 3600e3) return J({ ok: true, at: c.at, rows: c.rows, cached: true }, 200, cors);
      if (!env.JIRA_EMAIL || !env.JIRA_TOKEN) return J({ ok: false, error: "no-jira" }, 501, cors);
      try { const rows = await tlRows(env); c = { at: Date.now(), rows }; await env.ROSTER.put("tl:v1", JSON.stringify(c)); return J({ ok: true, at: c.at, rows }, 200, cors); }
      catch (e) { if (c) return J({ ok: true, at: c.at, rows: c.rows, stale: true }, 200, cors); return J({ ok: false, error: String(e && e.message || e) }, 502, cors); }
    }

    /* ── 디자인 리드타임 · 처리량 (3시간 캐시) — 편집 토큰 또는 팀 공용 게이트 ── */
    if (req.method === "POST" && path === "/dlt") {
      let b; try { b = await req.json(); } catch (e) { b = {}; }
      const email = await editTokenEmail(env, b && b.token);
      if (!email && !gateOK()) return J({ ok: false, error: "auth" }, 403, cors);
      let c = null; try { c = JSON.parse((await env.ROSTER.get("dlt:v1")) || "null"); } catch (e) { c = null; }
      if (c && !(b.fresh && email === OWNER) && Date.now() - c.at < 3 * 3600e3) return J({ ok: true, at: c.at, rows: c.rows, cached: true }, 200, cors);
      if (!env.JIRA_EMAIL || !env.JIRA_TOKEN) return J({ ok: false, error: "no-jira" }, 501, cors);
      try { const rows = await dsgRows(env); c = { at: Date.now(), rows }; await env.ROSTER.put("dlt:v1", JSON.stringify(c)); return J({ ok: true, at: c.at, rows }, 200, cors); }
      catch (e) { if (c) return J({ ok: true, at: c.at, rows: c.rows, stale: true }, 200, cors); return J({ ok: false, error: String(e && e.message || e) }, 502, cors); }
    }

    /* ── 론치 후 결과 (디자인 과제 키 · 1시간 캐시) ── */
    if (req.method === "POST" && path === "/impact") {
      let b; try { b = await req.json(); } catch (e) { return J({ ok: false, error: "json" }, 400, cors); }
      if (!(await editTokenEmail(env, b && b.token))) return J({ ok: false, error: "auth" }, 403, cors);
      const keys = [...new Set((Array.isArray(b.keys) ? b.keys : []).map(String).filter(k => /^[A-Z][A-Z0-9]{1,15}-\d{1,7}$/.test(k)))].sort().slice(0, 900);
      if (!keys.length) return J({ ok: true, rows: [] }, 200, cors);
      const ck = "imp2:" + (await hmac("imp", keys.join(","))).slice(0, 24);
      let c = null; try { c = JSON.parse((await env.ROSTER.get(ck)) || "null"); } catch (e) { c = null; }
      if (c && Date.now() - c.at < 3600e3) return J({ ok: true, at: c.at, rows: c.rows, cached: true }, 200, cors);
      if (!env.JIRA_EMAIL || !env.JIRA_TOKEN) return J({ ok: false, error: "no-jira" }, 501, cors);
      try { const rows = await impactRows(env, keys); c = { at: Date.now(), rows }; await env.ROSTER.put(ck, JSON.stringify(c), { expirationTtl: 86400 }); return J({ ok: true, at: c.at, rows }, 200, cors); }
      catch (e) { if (c) return J({ ok: true, at: c.at, rows: c.rows, stale: true }, 200, cors); return J({ ok: false, error: String(e && e.message || e) }, 502, cors); }
    }

    /* ── Design Driven: 최근 변경 기록 ── */
    if (req.method === "POST" && path === "/dd-log") {
      let b; try { b = await req.json(); } catch (e) { return J({ ok: false, error: "json" }, 400, cors); }
      if (!(await editTokenEmail(env, b && b.token))) return J({ ok: false, error: "auth" }, 403, cors);
      let log = []; try { log = JSON.parse((await env.ROSTER.get("dd:log")) || "[]"); } catch (e) { log = []; }
      if (b.key) log = log.filter(x => x.key === b.key);
      return J({ ok: true, log: log.slice(0, 60) }, 200, cors);
    }

    /* ── Design Driven: 지라 직접 수정 (FT · 담당자/우선순위/진행시기/라벨) ── */
    if (req.method === "POST" && path === "/jira-edit") {
      let b; try { b = await req.json(); } catch (e) { return J({ ok: false, error: "json" }, 400, cors); }
      const email = await editTokenEmail(env, b && b.token);
      if (!email) return J({ ok: false, error: "auth" }, 403, cors);
      if (!env.JIRA_EMAIL || !env.JIRA_TOKEN) return J({ ok: false, error: "no-jira" }, 501, cors);
      const key = String(b.key || "").toUpperCase();
      if (!new RegExp("^" + DD_PROJECT + "-\\d{1,6}$").test(key)) return J({ ok: false, error: "key" }, 400, cors);
      const eds = await ddEditors(env), me = await jiraAccountOf(env, email);
      if (email !== OWNER && !(me && eds.includes(me.id))) return J({ ok: false, error: "not-editor" }, 403, cors);
      const FL = "project,assignee,priority,duedate,labels," + DD_START;
      const cur = await jira(env, "GET", "/rest/api/3/issue/" + key + "?fields=" + FL);
      if (!cur.ok) return J({ ok: false, error: "jira-get", status: cur.status }, 502, cors);
      if (((cur.j.fields || {}).project || {}).key !== DD_PROJECT) return J({ ok: false, error: "project" }, 403, cors);
      const before = ddPick(cur.j.fields), set = b.set || {}, fields = {}, update = {}, ch = [];
      if ("assignee" in set) {
        const a = set.assignee ? String(set.assignee) : null;
        if (a && !eds.includes(a) && a !== before.acc) return J({ ok: false, error: "assignee" }, 400, cors);
        if (a !== (before.acc || null)) { fields.assignee = a ? { accountId: a } : null; ch.push("담당자"); }
      }
      if ("priority" in set) {
        if (!DD_PRI.includes(set.priority)) return J({ ok: false, error: "priority" }, 400, cors);
        if (set.priority !== before.pri) { fields.priority = { name: set.priority }; ch.push("우선순위 " + (before.pri || "-") + "→" + set.priority); }
      }
      for (const [k, f, lab] of [["start", DD_START, "시작일"], ["due", "duedate", "마감일"]]) {
        if (!(k in set)) continue;
        const v = ddDay(set[k]); if (v === undefined) return J({ ok: false, error: k }, 400, cors);
        const pv = k === "start" ? before.sd : before.du;
        if ((v || "") !== (pv || "")) { fields[f] = v; ch.push(lab + " " + (pv || "-") + "→" + (v || "-")); }
      }
      const okLab = l => typeof l === "string" && /^[^\s]{1,60}$/.test(l);
      const add = (Array.isArray(b.add) ? b.add : []).filter(okLab).filter(l => !before.labs.includes(l)).slice(0, 10);
      const rem = (Array.isArray(b.remove) ? b.remove : []).filter(okLab).filter(l => before.labs.includes(l)).slice(0, 10);
      if (rem.some(l => DD_LOCK.test(l))) return J({ ok: false, error: "locked-label" }, 400, cors);
      if (add.length || rem.length) { update.labels = [...add.map(l => ({ add: l })), ...rem.map(l => ({ remove: l }))];
        ch.push("라벨" + (add.length ? " +" + add.join(" +") : "") + (rem.length ? " -" + rem.join(" -") : "")); }
      if (!ch.length) return J({ ok: true, same: true, issue: before }, 200, cors);
      const put = await jira(env, "PUT", "/rest/api/3/issue/" + key, { fields, update });
      if (!put.ok) return J({ ok: false, error: "jira-put", status: put.status, detail: (put.t || "").slice(0, 300) }, 502, cors);
      const aft = await jira(env, "GET", "/rest/api/3/issue/" + key + "?fields=" + FL);
      const issue = aft.ok ? ddPick(aft.j.fields) : null;
      const who = (me && me.name) || email.split("@")[0];
      if (ch.includes("담당자")) ch[ch.indexOf("담당자")] = "담당자 " + (before.asg || "미배정") + "→" + ((issue && issue.asg) || "미배정");
      const line = ch.join(" · ");
      /* 실제 변경자 기록 — 지라 이력엔 API 계정으로 남으므로 코멘트로 남긴다 */
      await jira(env, "POST", "/rest/api/3/issue/" + key + "/comment", { body: { type: "doc", version: 1, content: [{ type: "paragraph", content: [
        { type: "text", text: "[디자인 대시보드] " + who + " 님이 변경: " + line }] }] } }).catch(() => null);
      let log = []; try { log = JSON.parse((await env.ROSTER.get("dd:log")) || "[]"); } catch (e) { log = []; }
      log.unshift({ at: new Date().toISOString(), by: who, email, key, ch: line });
      await env.ROSTER.put("dd:log", JSON.stringify(log.slice(0, 300)));
      try { await env.ROSTER.put("jira:seen", new Date().toISOString()); await jiraKick(env, "edit " + key); } catch (e) {}
      return J({ ok: true, issue, ch: line }, 200, cors);
    }

    /* ── 디자인 티켓 직접 수정 (상태 · 시작 날짜 · 기한 · Estimate MD) — 본인 · 같은 팀 팀장 · 소유자 (Marc 11-03) ── */
    /* 명단: 소유자 페이지가 이메일·팀·팀장 여부를 올리면 지라 계정으로 바꿔 둔다 */
    if (req.method === "POST" && path === "/tk-roster") {
      let b; try { b = await req.json(); } catch (e) { return J({ ok: false, error: "json" }, 400, cors); }
      const email = await editTokenEmail(env, b && b.token);
      if (email !== OWNER) return J({ ok: false, error: "forbidden" }, 403, cors);
      if (!Array.isArray(b.rows)) { const v = await env.ROSTER.get("tk:roster"); return J({ ok: true, roster: v ? JSON.parse(v) : null }, 200, cors); }
      const out = {}, miss = [];
      for (const r of b.rows.slice(0, 120)) {
        const em = String(r.email || "").toLowerCase();
        if (!/^[\w.+-]+@musinsa\.com$/.test(em)) continue;
        const a = await jiraAccountOf(env, em);
        if (a) out[a.id] = { team: String(r.team || "").slice(0, 20), lead: !!r.lead, name: a.name }; else miss.push(em.split("@")[0]);
      }
      await env.ROSTER.put("tk:roster", JSON.stringify({ at: Date.now(), m: out }));
      return J({ ok: true, n: Object.keys(out).length, miss }, 200, cors);
    }
    if (req.method === "POST" && path === "/tk-edit") {
      let b; try { b = await req.json(); } catch (e) { return J({ ok: false, error: "json" }, 400, cors); }
      const email = await editTokenEmail(env, b && b.token);
      if (!email) return J({ ok: false, error: "auth" }, 403, cors);
      if (!env.JIRA_EMAIL || !env.JIRA_TOKEN) return J({ ok: false, error: "no-jira" }, 501, cors);
      const key = String(b.key || "").toUpperCase();
      if (!/^[A-Z][A-Z0-9]{1,15}-\d{1,7}$/.test(key)) return J({ ok: false, error: "key" }, 400, cors);
      const TK_START = "customfield_10015", TK_EST = "customfield_12766", FL = "assignee,status,duedate," + TK_START + "," + TK_EST;
      const cur = await jira(env, "GET", "/rest/api/3/issue/" + key + "?fields=" + FL);
      if (!cur.ok) return J({ ok: false, error: "jira-get", status: cur.status }, 502, cors);
      const f = cur.j.fields || {}, asg = (f.assignee || {}).accountId || "";
      let R = {}; try { R = (JSON.parse((await env.ROSTER.get("tk:roster")) || "{}").m) || {}; } catch (e) { R = {}; }
      const me = await jiraAccountOf(env, email);
      let allow = email === OWNER;
      if (!allow && me && asg && me.id === asg && R[asg]) allow = true;                                            // 본인 티켓(디자인 조직)
      if (!allow && me && R[me.id] && R[me.id].lead && R[asg] && R[asg].team === R[me.id].team) allow = true;      // 같은 팀 팀장
      if (!allow) return J({ ok: false, error: "not-allowed" }, 403, cors);
      const set = b.set || {}, fields = {}, ch = [];
      for (const [k, fid, lab] of [["start", TK_START, "시작 날짜"], ["due", "duedate", "기한"]]) {
        if (!(k in set)) continue;
        const v = ddDay(set[k]); if (v === undefined) return J({ ok: false, error: k }, 400, cors);
        const pv = String(f[fid] || "").slice(0, 10) || null;
        if ((v || null) !== pv) { fields[fid] = v; ch.push(lab + " " + (pv || "-") + "→" + (v || "-")); }
      }
      if ("est" in set) {
        const v = set.est === "" || set.est == null ? null : Math.round(Number(set.est) * 2) / 2;
        if (v !== null && !(v >= 0 && v <= 200)) return J({ ok: false, error: "est" }, 400, cors);
        const pv = typeof f[TK_EST] === "number" ? f[TK_EST] : null;
        if (v !== pv) { fields[TK_EST] = v; ch.push("Estimate MD " + (pv ?? "-") + "→" + (v ?? "-")); }
      }
      let tr = null;
      const ST = ["진행 중", "완료", "보류", "백로그"];
      if (set.status) {
        if (!ST.includes(set.status)) return J({ ok: false, error: "status" }, 400, cors);
        const sn = (f.status || {}).name || "", sc = ((f.status || {}).statusCategory || {}).key || "", hold = n => /보류|hold/i.test(n);
        const now = set.status === "보류" ? hold(sn) : set.status === "완료" ? sc === "done" : set.status === "진행 중" ? (sc === "indeterminate" && !hold(sn)) : (sc === "new" && !hold(sn));
        if (!now) {
          const T = await jira(env, "GET", "/rest/api/3/issue/" + key + "/transitions");
          const L = (T.ok && T.j && T.j.transitions) || [], cat = t => ((t.to || {}).statusCategory || {}).key || "", nm = t => (t.to || {}).name || t.name || "";
          const pick = (ok, pref) => { const c = L.filter(ok); return c.find(t => pref.test(nm(t))) || c[0] || null; };
          tr = set.status === "보류" ? pick(t => hold(nm(t)), /hold|보류/i)
             : set.status === "완료" ? pick(t => cat(t) === "done" && !/취소|cancel|drop|won/i.test(nm(t)), /완료|done|closed/i)
             : set.status === "진행 중" ? pick(t => cat(t) === "indeterminate" && !hold(nm(t)), /in progress|진행|in design/i)
             : pick(t => cat(t) === "new" && !hold(nm(t)), /backlog|백로그|할 일|to do/i);
          if (!tr) return J({ ok: false, error: "transition", from: sn, avail: L.map(nm) }, 409, cors);
          ch.push("상태 " + sn + "→" + nm(tr));
        }
      }
      if (!ch.length) return J({ ok: true, same: true }, 200, cors);
      if (Object.keys(fields).length) {
        const put = await jira(env, "PUT", "/rest/api/3/issue/" + key, { fields });
        if (!put.ok) return J({ ok: false, error: "jira-put", status: put.status, detail: (put.t || "").slice(0, 300) }, 502, cors);
      }
      if (tr) {
        const pt = await jira(env, "POST", "/rest/api/3/issue/" + key + "/transitions", { transition: { id: tr.id } });
        if (!pt.ok) return J({ ok: false, error: "jira-transition", status: pt.status, detail: (pt.t || "").slice(0, 300), saved: Object.keys(fields).length > 0 }, 502, cors);
      }
      const aft = await jira(env, "GET", "/rest/api/3/issue/" + key + "?fields=" + FL), af = (aft.ok && aft.j && aft.j.fields) || {};
      const issue = { status: (af.status || {}).name || "", cat: ((af.status || {}).statusCategory || {}).key || "", start: String(af[TK_START] || "").slice(0, 10), due: String(af.duedate || "").slice(0, 10), est: typeof af[TK_EST] === "number" ? af[TK_EST] : null };
      const who = (me && me.name) || email.split("@")[0], line = ch.join(" · ");
      /* 실제 변경자 기록 — 지라 이력엔 API 계정으로 남으므로 코멘트로 남긴다 */
      await jira(env, "POST", "/rest/api/3/issue/" + key + "/comment", { body: { type: "doc", version: 1, content: [{ type: "paragraph", content: [
        { type: "text", text: "[디자인 대시보드] " + who + " 님이 변경: " + line }] }] } }).catch(() => null);
      let log = []; try { log = JSON.parse((await env.ROSTER.get("tk:log")) || "[]"); } catch (e) { log = []; }
      log.unshift({ at: new Date().toISOString(), by: who, email, key, ch: line });
      await env.ROSTER.put("tk:log", JSON.stringify(log.slice(0, 500)));
      try { await env.ROSTER.put("jira:seen", new Date().toISOString()); await jiraKick(env, "edit " + key); } catch (e) {}
      return J({ ok: true, issue, ch: line }, 200, cors);
    }

    /* ── 데이터 싱크 (Marc 11-04 「오전 10시 · 오후 3시 두 번 예약 + 설정에서 일괄 또는 선택 수동」)
       · GET  /sync-req            — 남은 수동 요청 {leave|one|runway: {at,by}} · 마지막 싱크 시각(누구나 읽기, 민감정보 없음)
       · POST /sync-req  x-gate    {items[],by} — 대시보드 설정에서 수동 싱크 요청(예약 작업이 매시 30분에 처리)
       · POST /sync-done (Origin)  {items[],build} — 예약 작업이 처리 후 기록 · build 면 지라 재빌드(쿨다운)
       · POST /rw-push   (Runway Origin) — Runway 보드 스냅샷 저장(KV rw:snap) · GET /rw-snap x-gate — build.py 가 읽음 ── */
    if (path === "/sync-req" || path === "/sync-done" || path === "/rw-push" || path === "/rw-snap") {
      const rd = async k => { try { return JSON.parse((await env.ROSTER.get(k)) || "{}"); } catch (e) { return {}; } };
      const okOrigin = reqOrigin === ORIGIN || reqOrigin === RUNWAY_ORIGIN;
      const now = new Date().toISOString();
      if (req.method === "GET" && path === "/sync-req") {
        return J({ ok: true, req: await rd("sync:req"), done: await rd("sync:done") }, 200, { ...cors, "Access-Control-Allow-Origin": "*" });
      }
      if (req.method === "POST" && path === "/sync-req") {
        if (!gateOK()) return J({ error: "gate" }, 403, cors);
        let b; try { b = await req.json(); } catch (e) { return J({ error: "json" }, 400, cors); }
        const items = (Array.isArray(b && b.items) ? b.items : []).filter(x => SYNC_ITEMS.includes(x));
        if (!items.length) return J({ error: "no items" }, 400, cors);
        const rq = await rd("sync:req"), by = String((b && b.by) || "").slice(0, 40);
        items.forEach(x => { rq[x] = { at: now, by }; });
        await env.ROSTER.put("sync:req", JSON.stringify(rq));
        return J({ ok: true, req: rq, done: await rd("sync:done") }, 200, cors);
      }
      if (req.method === "POST" && path === "/sync-done") {
        if (!okOrigin) return J({ error: "origin" }, 403, cors);
        let b; try { b = await req.json(); } catch (e) { return J({ error: "json" }, 400, cors); }
        const items = (Array.isArray(b && b.items) ? b.items : []).filter(x => SYNC_ITEMS.includes(x));
        const rq = await rd("sync:req"), dn = await rd("sync:done");
        items.forEach(x => { delete rq[x]; dn[x] = now; });
        await env.ROSTER.put("sync:req", JSON.stringify(rq)); await env.ROSTER.put("sync:done", JSON.stringify(dn));
        let built = false;
        if (b && b.build && env.GH_TOKEN) {
          const last = await env.ROSTER.get("refresh:at"), t = Math.floor(Date.now() / 1000);
          if (!(last && t - (+last) < COOLDOWN)) { await env.ROSTER.put("refresh:at", String(t)); built = (await dispatch(env, REFRESH_WF)).status === 204; }
        }
        return J({ ok: true, req: rq, done: dn, built }, 200, cors);
      }
      if (req.method === "POST" && path === "/rw-push") {
        if (reqOrigin !== RUNWAY_ORIGIN) return J({ error: "origin" }, 403, cors);
        const body = await req.text();
        if (body.length > 2 * 1024 * 1024) return J({ error: "too large" }, 413, cors);
        let s; try { s = JSON.parse(body); } catch (e) { return J({ error: "json" }, 400, cors); }
        if (!s || !Array.isArray(s.rows) || !s.rows.length || typeof s.by !== "object" || typeof s.plan !== "object" || !/^\d{4}-\d{2}-\d{2}/.test(String(s.asof || "")))
          return J({ error: "shape" }, 400, cors);
        s.at = now;
        await env.ROSTER.put("rw:snap", JSON.stringify(s));
        const rq = await rd("sync:req"), dn = await rd("sync:done"); delete rq.runway; dn.runway = now;
        await env.ROSTER.put("sync:req", JSON.stringify(rq)); await env.ROSTER.put("sync:done", JSON.stringify(dn));
        return J({ ok: true, rows: s.rows.length, at: now }, 200, cors);
      }
      if (req.method === "GET" && path === "/rw-snap") {
        if (!gateOK()) return J({ error: "gate" }, 403, cors);
        const v = await env.ROSTER.get("rw:snap");
        return new Response(v || "null", { status: 200, headers: { ...cors, "content-type": "application/json" } });
      }
      return J({ error: "method" }, 405, cors);
    }

    /* ── 지금 다시 읽기 : 지라 재조회 워크플로를 깨운다 ── */
    if (req.method === "POST" && path === "/refresh") {
      if (!gateOK()) return J({ error: "gate" }, 403, cors);
      if (!env.GH_TOKEN) return J({ error: "no token" }, 501, cors);
      const last = await env.ROSTER.get("refresh:at");
      const now = Math.floor(Date.now() / 1000);
      if (last && now - (+last) < COOLDOWN) return J({ ok: true, skipped: "cooldown" }, 200, cors);
      await env.ROSTER.put("refresh:at", String(now));
      const r = await dispatch(env, REFRESH_WF);
      if (r.status === 204) return J({ ok: true }, 200, cors);
      return J({ error: "github", status: r.status, detail: (await r.text()).slice(0, 200) }, 502, cors);
    }

    /* ── 자동 배포 : 봉인된 파일을 큐에 넣고 배포 워크플로를 깨운다 (배포 전용 암호) ── */
    if (req.method === "POST" && path === "/publish") {
      if (!deployOK() && !(await deployTokenOK(env, req.headers.get("x-deploy-token")))) return J({ error: "deploy-gate" }, 403, cors);
      if (!env.GH_TOKEN) return J({ error: "no token" }, 501, cors);
      const body = await req.text();
      if (body.length > 12 * 1024 * 1024) return J({ error: "too large" }, 413, cors);
      let p;
      try { p = JSON.parse(body); } catch (e) { return J({ error: "bad json" }, 400, cors); }
      if (!p || !Array.isArray(p.files) || !p.files.length) return J({ error: "no files" }, 400, cors);
      for (const f of p.files) {
        if (typeof f.path !== "string" || typeof f.content !== "string")
          return J({ error: "bad file" }, 400, cors);
        if (!/^[\w./-]+$/.test(f.path) || f.path.includes(".."))
          return J({ error: "bad path: " + f.path }, 400, cors);
      }
      const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
      await env.ROSTER.put("deploy:payload", JSON.stringify({
        id, message: (p.message || "대시보드 배포").slice(0, 200), files: p.files,
      }));
      const r = await dispatch(env, DEPLOY_WF);
      if (r.status === 204) return J({ ok: true, id }, 200, cors);
      await env.ROSTER.delete("deploy:payload");
      return J({ error: "dispatch", status: r.status, detail: (await r.text()).slice(0, 200) }, 502, cors);
    }

    /* ── 배포 워크플로가 큐를 가져간다 ── */
    if (req.method === "GET" && path === "/pull") {
      const v = await env.ROSTER.get("deploy:payload");
      return new Response(v || "null", { headers: { ...cors, "content-type": "application/json", "cache-control": "no-store" } });
    }
    if (req.method === "POST" && path === "/pull-done") {
      const b = await req.json().catch(() => ({}));
      const cur = await env.ROSTER.get("deploy:payload");
      if (cur && b.id && JSON.parse(cur).id === b.id) await env.ROSTER.delete("deploy:payload");
      return J({ ok: true }, 200, cors);
    }

    /* ── 공유 기준 읽기 ── */
    if (req.method === "GET") {
      const v = await env.ROSTER.get(KEY);
      return new Response(v || "null", { headers: { ...cors, "content-type": "application/json", "cache-control": "no-store" } });
    }

    /* ── 공유 기준 쓰기 ── */
    if (req.method === "PUT") {
      if (!gateOK()) return J({ error: "gate" }, 403, cors);
      const body = await req.text();
      if (body.length > 512 * 1024) return J({ error: "too large" }, 413, cors);
      let box;
      try { box = JSON.parse(body); } catch (e) { return J({ error: "bad json" }, 400, cors); }
      if (!box || box.enc !== "AES-GCM" || !box.ct || !box.salt || !box.iv)
        return J({ error: "bad shape" }, 400, cors);
      const prev = await env.ROSTER.get(KEY);
      if (prev) await env.ROSTER.put(KEY + ":prev", prev);
      await env.ROSTER.put(KEY, body);
      return J({ ok: true }, 200, cors);
    }

    return J({ error: "method" }, 405, cors);
  },
};

// deploy-worker 첫 배포 2026-11-04 (시크릿 등록 후 · 재시도)
