/* 디자인실 대시보드 — 공유 기준 저장소 + 재빌드 트리거
   · KV 바인딩       : ROSTER
   · Secret GATE_HASH : GATE_PASS 의 SHA-256 (소문자 16진)
   · Secret GH_TOKEN  : GitHub fine-grained PAT (design-roster 의 Actions 읽기·쓰기)  ← 없으면 재빌드만 비활성
   저장되는 내용은 GATE_PASS 로 암호화된 덩어리라 서버도 읽지 못합니다. */
const ORIGIN = "https://marcshin-mss.github.io";
const KEY = "basis";
const REPO = "marcshin-mss/design-roster";
const WORKFLOW = "refresh.yml";
const COOLDOWN = 90;                       /* 초 — 여러 명이 눌러도 한 번만 돈다 */

const J = (o, status, cors) =>
  new Response(JSON.stringify(o), { status, headers: { ...cors, "content-type": "application/json" } });

export default {
  async fetch(req, env) {
    const cors = {
      "Access-Control-Allow-Origin": ORIGIN,
      "Access-Control-Allow-Methods": "GET,PUT,POST,OPTIONS",
      "Access-Control-Allow-Headers": "content-type,x-gate",
      "Access-Control-Max-Age": "86400",
    };
    if (req.method === "OPTIONS") return new Response(null, { headers: cors });

    const path = new URL(req.url).pathname;
    const gateOK = async () => {
      const g = (req.headers.get("x-gate") || "").toLowerCase();
      return !!env.GATE_HASH && g === env.GATE_HASH.toLowerCase();
    };

    /* ── 지금 다시 읽기 : GitHub Actions 를 깨운다 ── */
    if (req.method === "POST" && path === "/refresh") {
      if (!(await gateOK())) return J({ error: "gate" }, 403, cors);
      if (!env.GH_TOKEN) return J({ error: "no token" }, 501, cors);

      const last = await env.ROSTER.get("refresh:at");
      const now = Math.floor(Date.now() / 1000);
      if (last && now - (+last) < COOLDOWN) return J({ ok: true, skipped: "cooldown" }, 200, cors);
      await env.ROSTER.put("refresh:at", String(now));

      const r = await fetch(
        `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
        { method: "POST",
          headers: { "authorization": "Bearer " + env.GH_TOKEN,
                     "accept": "application/vnd.github+json",
                     "x-github-api-version": "2022-11-28",
                     "user-agent": "design-roster-sync",
                     "content-type": "application/json" },
          body: JSON.stringify({ ref: "main" }) });
      if (r.status === 204) return J({ ok: true }, 200, cors);
      return J({ error: "github", status: r.status, detail: (await r.text()).slice(0, 200) }, 502, cors);
    }

    /* ── 공유 기준 읽기 ── */
    if (req.method === "GET") {
      const v = await env.ROSTER.get(KEY);
      return new Response(v || "null", {
        headers: { ...cors, "content-type": "application/json", "cache-control": "no-store" },
      });
    }

    /* ── 공유 기준 쓰기 ── */
    if (req.method === "PUT") {
      if (!(await gateOK())) return J({ error: "gate" }, 403, cors);
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
