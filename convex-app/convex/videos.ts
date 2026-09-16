// Writes and reads. An action cannot touch the database directly, so every write from
// `ingest` goes through one of these. Batched: one mutation per table, not one per row.

import { internalMutation, internalQuery, query } from "./_generated/server";
import { v } from "convex/values";

/** Bounded read. Convex advises against unbounded .collect() in a query. */
const MAX_VIDEOS = 1000;

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

export const insertFrames = internalMutation({
  args: {
    videoId: v.id("videos"),
    rows: v.array(
      v.object({
        frameIdx: v.number(),
        imageStorageId: v.id("_storage"),
        embedding: v.array(v.float64()),
      }),
    ),
  },
  handler: async (ctx, args) => {
    for (const row of args.rows) {
      await ctx.db.insert("frames", { videoId: args.videoId, ...row, createdAt: Date.now() });
    }
  },
});

export const insertChunks = internalMutation({
  args: {
    videoId: v.id("videos"),
    rows: v.array(
      v.object({
        startSec: v.number(),
        endSec: v.number(),
        transcript: v.string(),
        embedding: v.array(v.float64()),
      }),
    ),
  },
  handler: async (ctx, args) => {
    for (const row of args.rows) {
      await ctx.db.insert("audioChunks", { videoId: args.videoId, ...row, createdAt: Date.now() });
    }
  },
});

export const insertScenes = internalMutation({
  args: {
    videoId: v.id("videos"),
    rows: v.array(v.object({ startSec: v.number(), endSec: v.number() })),
  },
  handler: async (ctx, args) => {
    for (const row of args.rows) {
      await ctx.db.insert("scenes", { videoId: args.videoId, ...row, createdAt: Date.now() });
    }
  },
});

export const finishVideo = internalMutation({
  args: {
    videoId: v.id("videos"),
    durationSec: v.number(),
    sceneCount: v.number(),
    status: v.string(),
  },
  handler: async (ctx, args) => {
    await ctx.db.patch("videos", args.videoId, {
      durationSec: args.durationSec,
      sceneCount: args.sceneCount,
      status: args.status,
    });
  },
});

export const markError = internalMutation({
  args: { videoId: v.id("videos") },
  handler: async (ctx, args) => {
    await ctx.db.patch("videos", args.videoId, { status: "error" });
  },
});

export const saveConversation = internalMutation({
  args: {
    question: v.string(),
    answer: v.string(),
    visual: v.array(v.any()),
    spoken: v.array(v.any()),
  },
  handler: async (ctx, args) => {
    await ctx.db.insert("conversations", { ...args, createdAt: Date.now() });
  },
});

export const getVideo = internalQuery({
  args: { videoId: v.id("videos") },
  handler: async (ctx, args) => await ctx.db.get("videos", args.videoId),
});

export const listVideos = query({
  args: {},
  handler: async (ctx) => {
    // One bounded read of one table. The scene count is denormalized onto the row at
    // ingest, so this no longer collects every scene of every video.
    const videos = await ctx.db.query("videos").take(MAX_VIDEOS);
    const rows = videos.map((video) => ({
      video_title: video.title,
      duration_sec: video.durationSec ?? 0,
      scene_count: video.sceneCount ?? 0,
      status: video.status,
    }));
    rows.sort((a, b) => a.video_title.localeCompare(b.video_title));
    return { rows };
  },
});
