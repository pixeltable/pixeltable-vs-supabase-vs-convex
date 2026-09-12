// Search transcripts. Embed the query with the same model that filled the column,
// then call the SQL function that joins back to videos.
//
// Compare, in pixeltable/app.py:
//   sim = Chunks.transcript.similarity(string=query)
// The index knows its own model, and the view knows its own base.

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const COMPUTE_SERVICE_URL = Deno.env.get("COMPUTE_SERVICE_URL") || "http://localhost:9000";
const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

Deno.serve(async (req) => {
  const { query, limit } = await req.json();
  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);

  // Nothing checks that this is the model that produced the stored vectors.
  const embedResp = await fetch(`${COMPUTE_SERVICE_URL}/embed-text`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ texts: [query] }),
  });
  const embedData = await embedResp.json();

  const { data, error } = await supabase.rpc("search_transcripts", {
    query_embedding: embedData.embeddings[0],
    match_count: limit || 10,
  });

  if (error) {
    return new Response(JSON.stringify({ error: error.message }), { status: 500 });
  }

  return new Response(
    JSON.stringify({
      rows: (data || []).map((r: any) => ({
        transcript: r.transcript,
        video_title: r.video_title,
        start_sec: r.start_sec,
        similarity: r.similarity,
      })),
    }),
    { headers: { "Content-Type": "application/json" } },
  );
});
