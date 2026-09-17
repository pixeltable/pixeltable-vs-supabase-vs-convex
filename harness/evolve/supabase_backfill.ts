// Backfill for the new column. ALTER TABLE is instant; this is the part that is not.
// Every existing row has to be read, embedded by the compute service, and written back,
// because Postgres cannot call a model and a generated column cannot hold an embedding.
import { createClient } from "npm:@supabase/supabase-js@2.116.0";

const db = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_KEY")!);
const COMPUTE = Deno.env.get("COMPUTE_SERVICE_URL") ?? "http://localhost:9000";
const BATCH = 64;

const { data: rows, error } = await db.from("videos").select("id,title").is("title_embedding", null);
if (error) throw new Error(error.message);

for (let i = 0; i < rows!.length; i += BATCH) {
  const batch = rows!.slice(i, i + BATCH);
  const resp = await fetch(`${COMPUTE}/embed-text`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ texts: batch.map((r) => r.title) }),
  });
  if (!resp.ok) throw new Error(`embed failed: ${resp.status}`);
  const { embeddings } = await resp.json();
  for (const [j, row] of batch.entries()) {
    const { error: upErr } = await db.from("videos").update({ title_embedding: embeddings[j] }).eq("id", row.id);
    if (upErr) throw new Error(upErr.message);
  }
}
console.log(`backfilled ${rows!.length} rows`);
