// CRUD plumbing. Every write from an action has to hop through one of these,
// and each one restates its argument schema. None of it exists in
// pixeltable/app.py, where the table definition is the write path.

import { internalMutation, internalQuery, query } from "./_generated/server";
import { v } from "convex/values";

export const insertVideo = internalMutation({
  args: { title: v.string(), videoUrl: v.string() },
  handler: async (ctx, args) =>
    await ctx.db.insert("videos", {
      title: args.title,
      videoUrl: args.videoUrl,
      status: "processing",
      createdAt: Date.now(),
    }),
});

export const insertFrame = internalMutation({
  args: { videoId: v.id("videos"), frameIdx: v.number(), imageStorageId: v.id("_storage") },
  handler: async (ctx, args) =>
    await ctx.db.insert("frames", {
      videoId: args.videoId,
      frameIdx: args.frameIdx,
      imageStorageId: args.imageStorageId,
      createdAt: Date.now(),
    }),
});

export const insertAudioChunk = internalMutation({
  args: { videoId: v.id("videos"), startSec: v.number(), endSec: v.number() },
  handler: async (ctx, args) =>
    await ctx.db.insert("audioChunks", {
      videoId: args.videoId,
      startSec: args.startSec,
      endSec: args.endSec,
      createdAt: Date.now(),
    }),
});

export const insertScene = internalMutation({
  args: { videoId: v.id("videos"), startSec: v.number(), endSec: v.number() },
  handler: async (ctx, args) =>
    await ctx.db.insert("scenes", {
      videoId: args.videoId,
      startSec: args.startSec,
      endSec: args.endSec,
      createdAt: Date.now(),
    }),
});

export const setDuration = internalMutation({
  args: { videoId: v.id("videos"), durationSec: v.number() },
  handler: async (ctx, args) => {
    await ctx.db.patch(args.videoId, { durationSec: args.durationSec });
  },
});

export const updateStatus = internalMutation({
  args: { videoId: v.id("videos"), status: v.string() },
  handler: async (ctx, args) => {
    await ctx.db.patch(args.videoId, { status: args.status });
  },
});

export const getVideo = internalQuery({
  args: { videoId: v.id("videos") },
  handler: async (ctx, args) => await ctx.db.get(args.videoId),
});

// The stored status is set before any embedding exists, so it lies. This counts
// the rows that are still missing one and reports what is actually true.
export const listVideos = query({
  handler: async (ctx) => {
    const videos = await ctx.db.query("videos").collect();

    const rows = [];
    for (const video of videos) {
      const frames = await ctx.db
        .query("frames")
        .withIndex("by_video", (q) => q.eq("videoId", video._id))
        .collect();
      const chunks = await ctx.db
        .query("audioChunks")
        .withIndex("by_video", (q) => q.eq("videoId", video._id))
        .collect();
      const scenes = await ctx.db
        .query("scenes")
        .withIndex("by_video", (q) => q.eq("videoId", video._id))
        .collect();

      const pending =
        frames.some((f) => f.embedding === undefined) || chunks.some((c) => c.embedding === undefined);

      rows.push({
        video_title: video.title,
        duration_sec: video.durationSec ?? 0,
        scene_count: scenes.length,
        status: video.status === "error" ? "error" : pending ? "processing" : "ready",
      });
    }

    rows.sort((a, b) => a.video_title.localeCompare(b.video_title));
    return { rows };
  },
});
