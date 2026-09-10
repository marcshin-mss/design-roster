/* 디자인실 대시보드 — 공유 기준 저장소
   Cloudflare Workers 대시보드에 그대로 붙여 넣으세요.
   · KV 바인딩 이름 : ROSTER
   · 변수(Secret)   : GATE_HASH  = GATE_PASS 의 SHA-256 (소문자 16진)
   저장되는 내용은 GATE_PASS 로 암호화된 덩어리라 서버도 읽지 못합니다. */
const ORIGIN = "https://marcshin-mss.github.io";
const KEY = "basis";

export default {
  async fetch(req, env) {
    const cors = {
      "Access-Control-Allow-Origin": ORIGIN,
      "Access-Control-Allow-Methods": "GET,PUT,OPTIONS",
      "Access-Control-Allow-Headers": "content-type,x-gate",
      "Access-Control-Max-Age": "86400",
    };
    if (req.method === "OPTIONS") return new Response(null, { headers: cors });

    if (req.method === "GET") {
      const v = await env.ROSTER.get(KEY);
      return new Response(v || "null", {
        headers: { ...cors, "content-type": "application/json", "cache-control": "no-store" },
      });
    }

    if (req.method === "PUT") {
      const gate = req.headers.get("x-gate") || "";
      if (!env.GATE_HASH || gate.toLowerCase() !== env.GATE_HASH.toLowerCase())
        return new Response('{"error":"gate"}', { status: 403, headers: { ...cors, "content-type": "application/json" } });

      const body = await req.text();
      if (body.length > 512 * 1024)
        return new Response('{"error":"too large"}', { status: 413, headers: { ...cors, "content-type": "application/json" } });
      let box;
      try { box = JSON.parse(body); } catch (e) {
        return new Response('{"error":"bad json"}', { status: 400, headers: { ...cors, "content-type": "application/json" } });
      }
      if (!box || box.enc !== "AES-GCM" || !box.ct || !box.salt || !box.iv)
        return new Response('{"error":"bad shape"}', { status: 400, headers: { ...cors, "content-type": "application/json" } });

      const prev = await env.ROSTER.get(KEY);          /* 직전 값 1개는 백업으로 남긴다 */
      if (prev) await env.ROSTER.put(KEY + ":prev", prev);
      await env.ROSTER.put(KEY, body);
      return new Response('{"ok":true}', { headers: { ...cors, "content-type": "application/json" } });
    }

    return new Response('{"error":"method"}', { status: 405, headers: { ...cors, "content-type": "application/json" } });
  },
};
