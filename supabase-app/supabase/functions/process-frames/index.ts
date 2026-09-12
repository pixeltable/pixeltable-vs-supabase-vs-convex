// Webhook, one invocation per frame row: download the frame back out of Storage,
// base64 it again, and send it to the external compute service to be embedded.
// Wired by the trigger in migrations/003_pipeline.sql.
//
// Compare, in pixeltable/app.py, inside the Frames view:
//   __indexes__ = [pxt.EmbeddingIndex(frame, embedding=VISUAL)]

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const COMPUTE_SERVICE_URL = Deno.env.get("COMPUTE_SERVICE_URL") || "http://localhost:9000";
const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

// Spreading the byte array into String.fromCharCode blows the argument limit on a
// large frame, so encode it a chunk at a time.
const encodeBase64 = (bytes: Uint8Array) => {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
};

Deno.serve(async (req) => {
  const { record } = await req.json();
  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);

  try {
    // The frame was uploaded to Storage a moment ago by the ingest function. It is
    // downloaded here only to be encoded again and sent somewhere else.
    const imageResp = await fetch(record.frame_url);
    if (!imageResp.ok) throw new Error(`frame download failed: ${imageResp.status}`);
    const imageB64 = encodeBase64(new Uint8Array(await imageResp.arrayBuffer()));

    const embedResp = await fetch(`${COMPUTE_SERVICE_URL}/embed-clip`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ images_b64: [imageB64] }),
    });
    if (!embedResp.ok) throw new Error(`/embed-clip failed: ${embedResp.status}`);
    const embedData = await embedResp.json();

    if (embedData.embeddings.length > 0) {
      const { error } = await supabase
        .from("frames")
        .update({ embedding: embedData.embeddings[0] })
        .eq("id", record.id);
      if (error) throw new Error(error.message);
    }
  } catch (err) {
    // Nothing retries this. The frame keeps a NULL embedding and drops out of search.
    return new Response(JSON.stringify({ error: String(err) }), { status: 500 });
  }

  return new Response(JSON.stringify({ success: true }), {
    headers: { "Content-Type": "application/json" },
  });
});
