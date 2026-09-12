// Four tables, two vector indexes, four by_video indexes, and a status column.
// v.optional() on embedding and imageStorageId is not a design choice: those
// fields are filled in by a later scheduled action, so the row has to be valid
// without them. Compare pixeltable/app.py, where a computed column cannot be
// half-written.

import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

export default defineSchema({
  videos: defineTable({
    title: v.string(),
    videoUrl: v.string(),
    videoStorageId: v.optional(v.id("_storage")),
    durationSec: v.optional(v.number()),
    status: v.string(), // 'processing' | 'ready' | 'error', written before the work runs
    createdAt: v.number(),
  }),

  frames: defineTable({
    videoId: v.id("videos"),
    frameIdx: v.number(),
    imageStorageId: v.optional(v.id("_storage")),
    embedding: v.optional(v.array(v.float64())),
    createdAt: v.number(),
  })
    .index("by_video", ["videoId"])
    .vectorIndex("by_embedding", {
      vectorField: "embedding",
      dimensions: 512, // openai/clip-vit-base-patch32
      filterFields: ["videoId"],
    }),

  audioChunks: defineTable({
    videoId: v.id("videos"),
    startSec: v.number(),
    endSec: v.number(),
    transcript: v.optional(v.string()),
    embedding: v.optional(v.array(v.float64())),
    createdAt: v.number(),
  })
    .index("by_video", ["videoId"])
    .vectorIndex("by_embedding", {
      vectorField: "embedding",
      dimensions: 384, // sentence-transformers/all-MiniLM-L6-v2
      filterFields: ["videoId"],
    }),

  scenes: defineTable({
    videoId: v.id("videos"),
    startSec: v.number(),
    endSec: v.number(),
    createdAt: v.number(),
  }).index("by_video", ["videoId"]),
});
