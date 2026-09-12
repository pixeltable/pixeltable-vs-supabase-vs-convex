// Video ingest. Calls the external compute service for frames, audio and scenes,
// uploads every frame to Storage, and writes four tables by hand.
//
// Compare, in pixeltable/app.py:
//   Videos.insert([{'video': 'lecture.mp4', 'title': 'CS101'}])
// Frames, audio, chunks, transcripts, embeddings and scenes all follow from the
// column definitions. Nothing below has an equivalent there.

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const COMPUTE_SERVICE_URL = Deno.env.get("COMPUTE_SERVICE_URL") || "http://localhost:9000";
const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

const FRAME_FPS = 1.0;
const CHUNK_SECONDS = 10.0;

const post = async (path: string, body: unknown) => {
  const resp = await fetch(`${COMPUTE_SERVICE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`${path} failed: ${resp.status} ${await resp.text()}`);
  return await resp.json();
};

Deno.serve(async (req) => {
  const { video: video_url, title } = await req.json();
  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);

  const { data: video, error: insertErr } = await supabase
    .from("videos")
    .insert({ title, video_url, status: "processing" })
    .select("id")
    .single();

  if (insertErr) {
    return new Response(JSON.stringify({ error: insertErr.message }), { status: 500 });
  }

  const videoId = video.id;

  try {
    // Frames. Each one crosses the wire twice: base64 out of the compute service,
    // then bytes into Storage, then one INSERT, which fires one webhook.
    const frames = await post("/extract-frames", { video_url, fps: FRAME_FPS });
    for (let i = 0; i < frames.frames.length; i++) {
      const bytes = Uint8Array.from(atob(frames.frames[i]), (c) => c.charCodeAt(0));
      const path = `videos/${videoId}/frame_${i.toString().padStart(4, "0")}.jpg`;
      const { error: uploadErr } = await supabase.storage
        .from("frames")
        .upload(path, bytes, { contentType: "image/jpeg", upsert: true });
      if (uploadErr) throw new Error(`frame upload failed: ${uploadErr.message}`);
      const frameUrl = supabase.storage.from("frames").getPublicUrl(path).data.publicUrl;
      const { error: rowErr } = await supabase
        .from("frames")
        .insert({ video_id: videoId, frame_idx: i, frame_url: frameUrl });
      if (rowErr) throw new Error(`frame row failed: ${rowErr.message}`);
    }

    // Audio chunk boundaries. The transcript for each one is filled in later by
    // the process-audio webhook, which re-fetches the audio it needs.
    const audio = await post("/extract-audio", { video_url, format: "mp3" });
    for (let start = 0; start < audio.duration_sec; start += CHUNK_SECONDS) {
      const end = Math.min(start + CHUNK_SECONDS, audio.duration_sec);
      const { error: chunkErr } = await supabase
        .from("audio_chunks")
        .insert({ video_id: videoId, start_sec: start, end_sec: end });
      if (chunkErr) throw new Error(`chunk row failed: ${chunkErr.message}`);
    }

    const scenes = await post("/detect-scenes", { video_url });
    for (const scene of scenes.scenes) {
      const { error: sceneErr } = await supabase
        .from("scenes")
        .insert({ video_id: videoId, start_sec: scene.start_sec, end_sec: scene.end_sec });
      if (sceneErr) throw new Error(`scene row failed: ${sceneErr.message}`);
    }
  } catch (err) {
    await supabase.from("videos").update({ status: "error" }).eq("id", videoId);
    return new Response(JSON.stringify({ error: String(err) }), { status: 500 });
  }

  // Deliberately still 'processing'. Every embedding is filled in asynchronously by
  // a webhook, so a video is not searchable when this function returns. The real
  // answer comes from video_status(), which counts the NULLs.
  return new Response(JSON.stringify({ rows: [{ id: String(videoId), video_title: title, status: "processing" }] }), {
    headers: { "Content-Type": "application/json" },
  });
});
