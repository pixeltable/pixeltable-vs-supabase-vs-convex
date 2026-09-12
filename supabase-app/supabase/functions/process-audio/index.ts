// Webhook, one invocation per audio chunk row: transcribe just this chunk's span,
// then embed the transcript. Both through the external compute service.
//
// Compare, in pixeltable/app.py, inside the Chunks view:
//   transcript = transcribe(audio_segment, model='base.en').text.astype(pxt.String)
//   __indexes__ = [pxt.EmbeddingIndex(transcript, embedding=SEMANTIC)]

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
  const { record } = await req.json();
  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);

  const { data: video } = await supabase
    .from("videos")
    .select("video_url")
    .eq("id", record.video_id)
    .single();

  if (!video) {
    return new Response(JSON.stringify({ error: "video not found" }), { status: 404 });
  }

  try {
    // The whole audio track is re-extracted for every chunk, because the chunk row
    // holds only its boundaries and this function has nowhere to cache.
    const audio = await post("/extract-audio", { video_url: video.video_url, format: "mp3" });
    const transcription = await post("/transcribe", {
      audio_b64: audio.audio_b64,
      start_sec: record.start_sec,
      end_sec: record.end_sec,
    });
    const embedded = await post("/embed-text", { texts: [transcription.text] });

    const { error } = await supabase
      .from("audio_chunks")
      .update({ transcript: transcription.text, embedding: embedded.embeddings[0] })
      .eq("id", record.id);
    if (error) throw new Error(error.message);
  } catch (err) {
    // Nothing retries this. The chunk keeps a NULL embedding and drops out of search.
    return new Response(JSON.stringify({ error: String(err) }), { status: 500 });
  }

  return new Response(JSON.stringify({ success: true }), {
    headers: { "Content-Type": "application/json" },
  });
});
