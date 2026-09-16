// One Function serving all five contract routes, per Supabase's guidance to "develop
// few large functions, rather than many small functions".
// https://supabase.com/docs/guides/functions/development-tips
//
// The handler is a default export with a `fetch` property wrapped in `withSupabase`,
// which is the shape Supabase documents: "do NOT use `Deno.serve`. Instead, export a
// default object with a `fetch` handler." `auth: 'secret'` gives `ctx.supabaseAdmin`,
// a client that bypasses RLS, which is what this benchmark uses throughout. A real
// multi-tenant application would declare `auth: 'user'` and get an RLS-scoped client.
// https://supabase.com/docs/guides/getting-started/ai-prompts/edge-functions
//
// Compare pixeltable/app.py, where the same five are four `add_*_route` declarations
// and one hand-written handler.

import { decodeBase64 } from "jsr:@std/encoding@^1/base64";
import { withSupabase } from "npm:@supabase/server@^1";
import type { SupabaseClient } from "npm:@supabase/supabase-js@2.116.0";
import { BadRequest, compute, json, readJson, readLimit, requireString } from "../_shared/client.ts";

type FrameHit = { video_title: string; frame_idx: number };
type ChunkHit = { video_title: string; start_sec: number; transcript: string };

const FRAME_FPS = 1.0;
const CHUNK_SECONDS = 10.0;

async function ingest(req: Request, supabase: SupabaseClient): Promise<Response> {
  const body = await readJson(req);
  const video_url = requireString(body.video, "video");
  const title = requireString(body.title, "title");

  const { data: video, error } = await supabase
    .from("videos")
    .insert({ title, video_url })
    .select("id")
    .single();
  if (error) return json({ error: error.message }, 500);

  const videoId = video.id;

  try {
    // Frames: extract, embed the whole batch in one call, upload each to Storage,
    // then one INSERT for all of them.
    const { frames } = await compute("/extract-frames", { video_url, fps: FRAME_FPS });
    const { embeddings } = await compute("/embed-clip", { images_b64: frames });

    const frameRows = await Promise.all(frames.map(async (b64: string, i: number) => {
      const path = `videos/${videoId}/frame_${i.toString().padStart(4, "0")}.jpg`;
      const { error: upErr } = await supabase.storage
        .from("frames")
        .upload(path, decodeBase64(b64), { contentType: "image/jpeg", upsert: true });
      if (upErr) throw new Error(`frame upload failed: ${upErr.message}`);
      return {
        video_id: videoId,
        frame_idx: i,
        frame_url: supabase.storage.from("frames").getPublicUrl(path).data.publicUrl,
        embedding: embeddings[i],
      };
    }));
    const { error: frameErr } = await supabase.from("frames").insert(frameRows);
    if (frameErr) throw new Error(frameErr.message);

    // Audio: one extraction, then one transcription per chunk span, then one embedding
    // call for every transcript, then one INSERT.
    const audio = await compute("/extract-audio", { video_url, format: "mp3" });
    const spans = [];
    for (let start = 0; start < audio.duration_sec; start += CHUNK_SECONDS) {
      spans.push({ start, end: Math.min(start + CHUNK_SECONDS, audio.duration_sec) });
    }
    const transcripts = await Promise.all(
      spans.map((s) =>
        compute("/transcribe", { audio_b64: audio.audio_b64, start_sec: s.start, end_sec: s.end })
          .then((t) => t.text)
      ),
    );
    const { embeddings: textEmbeddings } = await compute("/embed-text", { texts: transcripts });
    const { error: chunkErr } = await supabase.from("audio_chunks").insert(
      spans.map((s, i) => ({
        video_id: videoId,
        start_sec: s.start,
        end_sec: s.end,
        transcript: transcripts[i],
        embedding: textEmbeddings[i],
      })),
    );
    if (chunkErr) throw new Error(chunkErr.message);

    const { scenes } = await compute("/detect-scenes", { video_url });
    const { error: sceneErr } = await supabase.from("scenes").insert(
      scenes.map((s: { start_sec: number; end_sec: number }) => ({
        video_id: videoId,
        start_sec: s.start_sec,
        end_sec: s.end_sec,
      })),
    );
    if (sceneErr) throw new Error(sceneErr.message);

    await supabase.from("videos").update({ status: "ready" }).eq("id", videoId);
  } catch (err) {
    await supabase.from("videos").update({ status: "error" }).eq("id", videoId);
    return json({ error: String(err) }, 500);
  }

  return json({ rows: [{ id: String(videoId), video_title: title, status: "ready" }] });
}

async function listVideos(supabase: SupabaseClient): Promise<Response> {
  // One request against the video_summary view, which does the counting in SQL.
  const { data, error } = await supabase.from("video_summary").select("*").order("video_title");
  if (error) return json({ error: error.message }, 500);
  return json({ rows: data ?? [] });
}

async function search(req: Request, kind: "frames" | "transcripts", supabase: SupabaseClient): Promise<Response> {
  const body = await readJson(req);
  const query = requireString(body.query, "query");
  const limit = readLimit(body.limit);

  // The query has to be embedded with the same model that filled the column, and
  // nothing enforces that. The dimension is the only guard.
  const endpoint = kind === "frames" ? "/embed-clip" : "/embed-text";
  const { embeddings } = await compute(endpoint, { texts: [query] });

  const { data, error } = await supabase.rpc(`search_${kind}`, {
    query_embedding: embeddings[0],
    match_count: limit,
  });
  if (error) return json({ error: error.message }, 500);

  return json({ rows: data ?? [] });
}

async function agent(req: Request, supabase: SupabaseClient): Promise<Response> {
  const question = requireString((await readJson(req)).question, "question");

  const [clip, text] = await Promise.all([
    compute("/embed-clip", { texts: [question] }),
    compute("/embed-text", { texts: [question] }),
  ]);
  const [{ data: visual }, { data: spoken }] = await Promise.all([
    supabase.rpc("search_frames", { query_embedding: clip.embeddings[0], match_count: 4 }),
    supabase.rpc("search_transcripts", { query_embedding: text.embeddings[0], match_count: 4 }),
  ]);

  const seen = (visual ?? []).map((r: FrameHit) => `- ${r.video_title}, frame ${r.frame_idx}`).join("\n") ||
    "(nothing)";
  const heard = (spoken ?? [])
    .map((r: ChunkHit) => `- [${r.video_title} @ ${Math.round(r.start_sec)}s] ${r.transcript}`)
    .join("\n") || "(nothing)";

  const chat = await compute("/chat", {
    messages: [{
      role: "user",
      content: `Answer the question using only the retrieved context. Be brief.\n\n` +
        `## Seen in the videos\n${seen}\n\n## Said in the videos\n${heard}\n\n## Question\n${question}`,
    }],
  });

  const { error } = await supabase.from("conversations").insert({
    question,
    answer: chat.content,
    visual: visual ?? [],
    spoken: spoken ?? [],
  });
  if (error) return json({ error: error.message }, 500);

  return json({ rows: [{ answer: chat.content, visual: visual ?? [], spoken: spoken ?? [] }] });
}

export default {
  fetch: withSupabase({ auth: "secret" }, async (req: Request, ctx: { supabaseAdmin: SupabaseClient }) => {
    const db = ctx.supabaseAdmin;
    // Every route is prefixed with the function name, as Supabase routes it.
    const path = new URL(req.url).pathname.replace(/^\/api/, "");
    try {
      if (req.method === "POST" && path === "/videos") return await ingest(req, db);
      if (req.method === "GET" && path === "/videos") return await listVideos(db);
      if (req.method === "POST" && path === "/search/frames") return await search(req, "frames", db);
      if (req.method === "POST" && path === "/search/transcripts") return await search(req, "transcripts", db);
      if (req.method === "POST" && path === "/agent/query") return await agent(req, db);
    } catch (err) {
      if (err instanceof BadRequest) return json({ error: err.message }, 400);
      throw err;
    }
    return json({ error: `no route for ${req.method} ${path}` }, 404);
  }),
};
