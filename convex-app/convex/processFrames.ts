// Scheduled action: read each frame back out of Convex storage and send it to the
// external compute service to be embedded with CLIP.
//
// Compare, in pixeltable/app.py, inside the Frames view:
//   __indexes__ = [pxt.EmbeddingIndex(frame, embedding=VISUAL)]

import { internalAction, internalMutation, internalQuery } from "./_generated/server";
import { v } from "convex/values";
import { internal } from "./_generated/api";

const COMPUTE_SERVICE_URL = process.env.COMPUTE_SERVICE_URL || "http://localhost:9000";

const encodeBase64 = (bytes: Uint8Array) => {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
};

export const embedAllFrames = internalAction({
  args: { videoId: v.id("videos") },
  handler: async (ctx, args) => {
    const frames = await ctx.runQuery(internal.processFrames.getUnembeddedFrames, {
      videoId: args.videoId,
    });

    for (const frame of frames) {
      if (!frame.imageStorageId) continue;
      const blob = await ctx.storage.get(frame.imageStorageId);
      if (!blob) continue;

      const imageB64 = encodeBase64(new Uint8Array(await blob.arrayBuffer()));
      const resp = await fetch(`${COMPUTE_SERVICE_URL}/embed-clip`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ images_b64: [imageB64] }),
      });
      if (!resp.ok) continue; // nothing retries; the frame stays out of search
      const embedded = await resp.json();

      if (embedded.embeddings.length > 0) {
        await ctx.runMutation(internal.processFrames.setFrameEmbedding, {
          frameId: frame._id,
          embedding: embedded.embeddings[0],
        });
      }
    }
  },
});

export const getUnembeddedFrames = internalQuery({
  args: { videoId: v.id("videos") },
  handler: async (ctx, args) => {
    const frames = await ctx.db
      .query("frames")
      .withIndex("by_video", (q) => q.eq("videoId", args.videoId))
      .collect();
    return frames.filter((frame) => frame.embedding === undefined);
  },
});

export const setFrameEmbedding = internalMutation({
  args: { frameId: v.id("frames"), embedding: v.array(v.float64()) },
  handler: async (ctx, args) => {
    await ctx.db.patch(args.frameId, { embedding: args.embedding });
  },
});
