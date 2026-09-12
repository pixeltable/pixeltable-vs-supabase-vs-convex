// Search frames. Embed the query text with CLIP through the external compute
// service, then call the SQL function that joins back to videos.
//
// Compare, in pixeltable/app.py:
//   sim = Frames.frame.similarity(string=query)

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const COMPUTE_SERVICE_URL = Deno.env.get("COMPUTE_SERVICE_URL") || "http://localhost:9000";
const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

Deno.serve(async (req) => {
  const { query, limit } = await req.json();
  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);

  // Embed query text with CLIP via external compute service
  const embedResp = await fetch(`${COMPUTE_SERVICE_URL}/embed-clip`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ texts: [query] }),
  });
  const embedData = await embedResp.json();
  const queryEmbedding = embedData.embeddings[0];

  // Search via SQL RPC function
  const { data, error } = await supabase.rpc("search_frames", {
    query_embedding: queryEmbedding,
    match_count: limit || 10,
  });

  if (error) {
    return new Response(JSON.stringify({ error: error.message }), { status: 500 });
  }

  return new Response(
    JSON.stringify({
      rows: (data || []).map((r: any) => ({
        frame_url: r.frame_url,
        frame_idx: r.frame_idx,
        video_title: r.video_title,
        similarity: r.similarity,
      })),
    }),
    { headers: { "Content-Type": "application/json" } },
  );
});
