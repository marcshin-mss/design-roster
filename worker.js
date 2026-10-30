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
   · /dd-log     POST {token[,key]} — 최근 변경 기록(KV dd:log, 최근 300건)
   · 변경마다 지라에 '대시보드에서 OOO 님이 변경' 코멘트를 남겨 실제 변경자를 기록 */
const ORIGIN = "https://marcshin-mss.github.io";
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
  async fetch(req, env) {
    const cors = {
      "Access-Control-Allow-Origin": ORIGIN,
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
      return J({ ok: true, issue, ch: line }, 200, cors);
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
