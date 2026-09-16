// Vector search. `vectorSearch` returns ids and scores only, so the rows have to be
// fetched separately -- but in one query taking every id, not one query per hit.
// Convex's best-practices guide warns that separate ctx.run* calls each run in their
// own transaction: https://docs.convex.dev/understanding/best-practices/
//
// Compare, in pixeltable/app.py:
//   sim = Frames.frame.similarity(string=query)
//   Frames.order_by(sim, asc=False).limit(limit).select(..., video_title=Frames.title)

import { action, internalQuery } from "./_generated/server";
import type { ActionCtx } from "./_generated/server";
import { v } from "convex/values";
import { internal } from "./_generated/api";
import { compute } from "./compute";

const clamp = (n: number | undefined) => Math.min(Math.max(n ?? 10, 1), 256);

// Plain helpers, not actions. The agent calls these directly: routing it through
// ctx.runAction would both cost an extra function invocation and create a circular
// type reference that TypeScript cannot infer through.
export type FrameHit = { frame_url: string; frame_idx: number; video_title: string; similarity: number };
export type ChunkHit = { transcript: string; video_title: string; start_sec: number; similarity: number };

export async function findFrames(ctx: ActionCtx, query: string, limit?: number): Promise<FrameHit[]> {
  // Nothing checks that this is the model that produced the stored vectors.
  const { embeddings } = await compute("/embed-clip", { texts: [query] });
  const hits = await ctx.vectorSearch("frames", "by_embedding", {
    vector: embeddings[0],
    limit: clamp(limit),
  });
  return await ctx.runQuery(internal.search.framesByIds, {
    ids: hits.map((h) => h._id),
    scores: hits.map((h) => h._score),
  });
}

export async function findTranscripts(ctx: ActionCtx, query: string, limit?: number): Promise<ChunkHit[]> {
  const { embeddings } = await compute("/embed-text", { texts: [query] });
  const hits = await ctx.vectorSearch("audioChunks", "by_embedding", {
    vector: embeddings[0],
    limit: clamp(limit),
  });
  return await ctx.runQuery(internal.search.chunksByIds, {
    ids: hits.map((h) => h._id),
    scores: hits.map((h) => h._score),
  });
}

export const searchFrames = action({
  args: { query: v.string(), limit: v.optional(v.number()) },
  handler: async (ctx, args) => ({ rows: await findFrames(ctx, args.query, args.limit) }),
});

export const searchTranscripts = action({
  args: { query: v.string(), limit: v.optional(v.number()) },
  handler: async (ctx, args) => ({ rows: await findTranscripts(ctx, args.query, args.limit) }),
});

export const framesByIds = internalQuery({
  args: { ids: v.array(v.id("frames")), scores: v.array(v.number()) },
  handler: async (ctx, args) => {
    const rows = [];
    for (let i = 0; i < args.ids.length; i++) {
      const frame = await ctx.db.get("frames", args.ids[i]);
      if (!frame) continue;
      const video = await ctx.db.get("videos", frame.videoId);
      rows.push({
        frame_url: (await ctx.storage.getUrl(frame.imageStorageId)) ?? "",
        frame_idx: frame.frameIdx,
        video_title: video?.title ?? "",
        similarity: Math.max(0, Math.min(1, args.scores[i])),
      });
    }
    return rows;
  },
});

export const chunksByIds = internalQuery({
  args: { ids: v.array(v.id("audioChunks")), scores: v.array(v.number()) },
  handler: async (ctx, args) => {
    const rows = [];
    for (let i = 0; i < args.ids.length; i++) {
      const chunk = await ctx.db.get("audioChunks", args.ids[i]);
      if (!chunk) continue;
      const video = await ctx.db.get("videos", chunk.videoId);
      rows.push({
        transcript: chunk.transcript,
        video_title: video?.title ?? "",
        start_sec: chunk.startSec,
        similarity: Math.max(0, Math.min(1, args.scores[i])),
      });
    }
    return rows;
  },
});
