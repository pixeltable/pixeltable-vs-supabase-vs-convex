import { defineSchema, defineTable } from 'convex/server';
import { v } from 'convex/values';

export default defineSchema({
  documents: defineTable({
    content: v.string(),
    source: v.string(),
    modality: v.string(),
    imageUrl: v.optional(v.string()),
    metadata: v.any(),
    embedding: v.array(v.float64()),
    createdAt: v.number(),
  }).vectorIndex('by_embedding', {
    vectorField: 'embedding',
    dimensions: 1536,
    filterFields: ['modality', 'source'],
  }),

  conversations: defineTable({
    message: v.string(),
    role: v.string(),
    conversationId: v.string(),
  }),
});
