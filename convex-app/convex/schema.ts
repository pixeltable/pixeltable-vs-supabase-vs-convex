// Four tables, two vector indexes, three by_video indexes, and a status column.
// Compare pixeltable/app.py: one table, two views derived from it, and no status.

import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

export default defineSchema({
  videos: defineTable({
    title: v.string(),
    videoUrl: v.string(),
    durationSec: v.optional(v.number()),
    status: v.string(), // 'processing' | 'ready' | 'error'
    createdAt: v.number(),
  }),

  frames: defineTable({
    videoId: v.id("videos"),
    frameIdx: v.number(),
    imageStorageId: v.id("_storage"),
    embedding: v.array(v.float64()),
    createdAt: v.number(),
  })
    .index("by_video", ["videoId"])
    .vectorIndex("by_embedding", {
      vectorField: "embedding",
      dimensions: 512, // openai/clip-vit-base-patch32
    }),

  audioChunks: defineTable({
    videoId: v.id("videos"),
    startSec: v.number(),
    endSec: v.number(),
    transcript: v.string(),
    embedding: v.array(v.float64()),
    createdAt: v.number(),
  })
    .index("by_video", ["videoId"])
    .vectorIndex("by_embedding", {
      vectorField: "embedding",
      dimensions: 384, // sentence-transformers/all-MiniLM-L6-v2
    }),

  scenes: defineTable({
    videoId: v.id("videos"),
    startSec: v.number(),
    endSec: v.number(),
    createdAt: v.number(),
  }).index("by_video", ["videoId"]),

  // The agent's evidence. In pixeltable/app.py this is the Conversations table, where
  // retrieval is a column rather than something the handler assembles and writes.
  conversations: defineTable({
    question: v.string(),
    answer: v.string(),
    visual: v.array(v.any()),
    spoken: v.array(v.any()),
    createdAt: v.number(),
  }),
});
