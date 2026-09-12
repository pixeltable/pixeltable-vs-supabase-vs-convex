// Transcript search. Same shape as searchFrames, against a different index and a
// different model, with the same per-hit join to recover the video title.
//
// Compare, in pixeltable/app.py:
//   sim = Chunks.transcript.similarity(string=query)

import { action, internalQuery } from "./_generated/server";
import { v } from "convex/values";
import { internal } from "./_generated/api";

const COMPUTE_SERVICE_URL = process.env.COMPUTE_SERVICE_URL || "http://localhost:9000";

export const searchTranscripts = action({
  args: { query: v.string(), limit: v.optional(v.number()) },
  handler: async (ctx, args) => {
    const resp = await fetch(`${COMPUTE_SERVICE_URL}/embed-text`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ texts: [args.query] }),
    });
    const embedded = await resp.json();

    const hits = await ctx.vectorSearch("audioChunks", "by_embedding", {
      vector: embedded.embeddings[0],
      limit: Math.min(args.limit ?? 10, 256),
    });

    const rows = [];
    for (const hit of hits) {
      const detail = await ctx.runQuery(internal.searchTranscripts.getChunkWithVideo, { chunkId: hit._id });
      if (!detail) continue;
      rows.push({
        transcript: detail.transcript,
        video_title: detail.videoTitle,
        start_sec: detail.startSec,
        similarity: hit._score,
      });
    }

    return { rows };
  },
});

export const getChunkWithVideo = internalQuery({
  args: { chunkId: v.id("audioChunks") },
  handler: async (ctx, args) => {
    const chunk = await ctx.db.get(args.chunkId);
    if (!chunk) return null;
    const video = await ctx.db.get(chunk.videoId);
    return {
      transcript: chunk.transcript ?? "",
      startSec: chunk.startSec,
      videoTitle: video?.title ?? "",
    };
  },
});
