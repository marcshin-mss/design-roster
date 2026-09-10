/* 디자인실 대시보드 — 공유 기준 저장소 + 재빌드 + 자동 배포
   · KV 바인딩        : ROSTER
   · Secret GATE_HASH  : GATE_PASS 의 SHA-256 (팀장 공용 — 기준 공유·재빌드용)
   · Secret GH_TOKEN   : GitHub PAT (design-roster 의 Actions 읽기·쓰기)
   · Secret DEPLOY_HASH : 배포 전용 암호의 SHA-256 (Marc 전용 — 코드 배포용, 팀장과 분리)
   공유 기준은 GATE_PASS 로 암호화된 덩어리라 서버도 읽지 못합니다. */
const ORIGIN = "https://marcshin-mss.github.io";
const KEY = "basis";
const REPO = "marcshin-mss/design-roster";
const REFRESH_WF = "refresh.yml";
const DEPLOY_WF = "deploy.yml";
const COOLDOWN = 90;                       /* 초 — 여러 명이 눌러도 한 번만 돈다 */

const J = (o, status, cors) =>
  new Response(JSON.stringify(o), { status, headers: { ...cors, "content-type": "application/json" } });

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

    /* ── 배포 워크플로가 큐를 가져간다 (내용은 암호화됐거나 이미 공개 코드라 별도 잠금 없음) ── */
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
