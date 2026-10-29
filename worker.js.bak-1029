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
   · KV kpi:allow — 지표 열람 허용 이메일 배열 (없으면 소유자 1명) */
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

async function allowList(env) {
  let a;
  try { a = JSON.parse((await env.ROSTER.get("kpi:allow")) || "null"); } catch (e) { a = null; }
  if (!Array.isArray(a)) a = [OWNER];
  return a.map(x => String(x).toLowerCase());
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
      "Access-Control-Allow-Headers": "content-type,x-gate,x-deploy",
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
                 kpi: allow.includes(email), admin: email === OWNER }, 200, cors);
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
      if (!deployOK()) return J({ error: "deploy-gate" }, 403, cors);
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
