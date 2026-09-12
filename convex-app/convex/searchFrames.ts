// Visual search. vectorSearch returns ids and scores only, so every hit needs a
// second round trip to recover the frame url and the video title.
//
// Compare, in pixeltable/app.py:
//   sim = Frames.frame.similarity(string=query)
//   Frames.order_by(sim, asc=False).limit(limit).select(..., video_title=Frames.title)

import { action, internalQuery } from "./_generated/server";
import { v } from "convex/values";
import { internal } from "./_generated/api";

const COMPUTE_SERVICE_URL = process.env.COMPUTE_SERVICE_URL || "http://localhost:9000";

export const searchFrames = action({
  args: { query: v.string(), limit: v.optional(v.number()) },
  handler: async (ctx, args) => {
    // Nothing checks that this is the model that produced the stored vectors.
    const resp = await fetch(`${COMPUTE_SERVICE_URL}/embed-clip`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ texts: [args.query] }),
    });
    const embedded = await resp.json();

    const hits = await ctx.vectorSearch("frames", "by_embedding", {
      vector: embedded.embeddings[0],
      limit: Math.min(args.limit ?? 10, 256),
    });

    const rows = [];
    for (const hit of hits) {
      const detail = await ctx.runQuery(internal.searchFrames.getFrameWithVideo, { frameId: hit._id });
      if (!detail) continue;
      rows.push({
        frame_url: detail.frameUrl ?? "",
        frame_idx: detail.frameIdx,
        video_title: detail.videoTitle,
        similarity: hit._score,
      });
    }

    return { rows };
  },
});

export const getFrameWithVideo = internalQuery({
  args: { frameId: v.id("frames") },
  handler: async (ctx, args) => {
    const frame = await ctx.db.get(args.frameId);
    if (!frame) return null;
    const video = await ctx.db.get(frame.videoId);
    return {
      frameIdx: frame.frameIdx,
      frameUrl: frame.imageStorageId ? await ctx.storage.getUrl(frame.imageStorageId) : null,
      videoTitle: video?.title ?? "",
    };
  },
});
