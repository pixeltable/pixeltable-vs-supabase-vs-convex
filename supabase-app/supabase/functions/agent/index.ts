// Multi-modal RAG agent. Two embedding models, two RPCs, one chat call, and the
// prompt assembled by hand. The two searches are duplicated here rather than
// reused, because an Edge Function cannot call another one cheaply.
//
// Compare, in pixeltable/app.py, the whole agent:
//   class Conversations(TableModel, name='conversations'):
//       question: pxt.String
//       visual = search_frames(question, limit=4)
//       spoken = search_transcripts(question, limit=4)
//       answer = create_chat_completion(...)
// Retrieval is a column there, so the evidence survives the request.

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const COMPUTE_SERVICE_URL = Deno.env.get("COMPUTE_SERVICE_URL") || "http://localhost:9000";
const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

const post = async (path: string, body: unknown) => {
  const resp = await fetch(`${COMPUTE_SERVICE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`${path} failed: ${resp.status}`);
  return await resp.json();
};

Deno.serve(async (req) => {
  const { question } = await req.json();
  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);

  const clip = await post("/embed-clip", { texts: [question] });
  const { data: visual } = await supabase.rpc("search_frames", {
    query_embedding: clip.embeddings[0],
    match_count: 4,
  });

  const text = await post("/embed-text", { texts: [question] });
  const { data: spoken } = await supabase.rpc("search_transcripts", {
    query_embedding: text.embeddings[0],
    match_count: 4,
  });

  const seen = (visual || []).map((r: any) => `- ${r.video_title}, frame ${r.frame_idx}`).join("\n") || "(nothing)";
  const heard = (spoken || [])
    .map((r: any) => `- [${r.video_title} @ ${Math.round(r.start_sec)}s] ${r.transcript}`)
    .join("\n") || "(nothing)";

  const chat = await post("/chat", {
    messages: [
      {
        role: "user",
        content:
          `Answer the question using only the retrieved context. Be brief.\n\n` +
          `## Seen in the videos\n${seen}\n\n## Said in the videos\n${heard}\n\n## Question\n${question}`,
      },
    ],
  });

  // Nothing is stored. The next request re-runs both searches from scratch and the
  // evidence behind this answer is gone once the response is written.
  return new Response(
    JSON.stringify({
      rows: [{ answer: chat.content, visual: visual || [], spoken: spoken || [] }],
    }),
    { headers: { "Content-Type": "application/json" } },
  );
});
