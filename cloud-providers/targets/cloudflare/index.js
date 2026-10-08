// POST /compute is the shootout's compute handler, the same on every platform: read the JSON body and return
// title_upper and summary, storing nothing. The /docs routes are the D1 paths: one-row write, one-row read by
// primary key, and 100 rows in one D1 batch.
const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

export default {
  async fetch(req, env) {
    const url = new URL(req.url);

    if (url.pathname === "/compute" && req.method === "POST") {
      const { title } = await req.json();
      const summary = title.length > 12 ? `${title.slice(0, 12)}...` : title;
      return json({ id: crypto.randomUUID(), title_upper: title.toUpperCase(), summary });
    }

    if (url.pathname === "/docs" && req.method === "POST") {
      const { title, body } = await req.json();
      const id = crypto.randomUUID();
      await env.DB.prepare("INSERT INTO docs (id, title, body) VALUES (?, ?, ?)").bind(id, title, body ?? null).run();
      return json({ id, title });
    }

    if (url.pathname.startsWith("/docs/") && req.method === "GET") {
      const id = url.pathname.slice("/docs/".length);
      const row = await env.DB.prepare("SELECT id, title, body FROM docs WHERE id = ?").bind(id).first();
      return row ? json(row) : json({ error: "not found" }, 404);
    }

    if (url.pathname === "/docs/batch" && req.method === "POST") {
      const { docs } = await req.json();
      const insert = env.DB.prepare("INSERT INTO docs (id, title, body) VALUES (?, ?, ?)");
      await env.DB.batch(docs.map((doc) => insert.bind(crypto.randomUUID(), doc.title, doc.body ?? null)));
      return json({ inserted: docs.length });
    }

    return json({ status: "ok", platform: "cloudflare" });
  },
};
