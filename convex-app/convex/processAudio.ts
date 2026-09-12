// Scheduled action: transcribe each chunk's own span, then embed the transcript.
// The whole audio track is re-extracted once per chunk, because an action has
// nowhere to keep it between invocations.
//
// Compare, in pixeltable/app.py, inside the Chunks view:
//   transcript = transcribe(audio_segment, model='base.en').text.astype(pxt.String)
//   __indexes__ = [pxt.EmbeddingIndex(transcript, embedding=SEMANTIC)]

import { internalAction, internalMutation, internalQuery } from "./_generated/server";
import { v } from "convex/values";
import { internal } from "./_generated/api";

const COMPUTE_SERVICE_URL = process.env.COMPUTE_SERVICE_URL || "http://localhost:9000";

const post = async (path: string, body: unknown) => {
  const resp = await fetch(`${COMPUTE_SERVICE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`${path} failed: ${resp.status}`);
  return await resp.json();
};

export const transcribeAndEmbed = internalAction({
  args: { videoId: v.id("videos") },
  handler: async (ctx, args) => {
    const video = await ctx.runQuery(internal.videos.getVideo, { videoId: args.videoId });
    if (!video) return;

    const chunks = await ctx.runQuery(internal.processAudio.getUnembeddedChunks, { videoId: args.videoId });
    const audio = await post("/extract-audio", { video_url: video.videoUrl, format: "mp3" });

    for (const chunk of chunks) {
      const transcription = await post("/transcribe", {
        audio_b64: audio.audio_b64,
        start_sec: chunk.startSec,
        end_sec: chunk.endSec,
      });
      const embedded = await post("/embed-text", { texts: [transcription.text] });

      await ctx.runMutation(internal.processAudio.setChunkResult, {
        chunkId: chunk._id,
        transcript: transcription.text,
        embedding: embedded.embeddings[0],
      });
    }
  },
});

export const getUnembeddedChunks = internalQuery({
  args: { videoId: v.id("videos") },
  handler: async (ctx, args) => {
    const chunks = await ctx.db
      .query("audioChunks")
      .withIndex("by_video", (q) => q.eq("videoId", args.videoId))
      .collect();
    return chunks.filter((chunk) => chunk.embedding === undefined);
  },
});

export const setChunkResult = internalMutation({
  args: { chunkId: v.id("audioChunks"), transcript: v.string(), embedding: v.array(v.float64()) },
  handler: async (ctx, args) => {
    await ctx.db.patch(args.chunkId, { transcript: args.transcript, embedding: args.embedding });
  },
});
