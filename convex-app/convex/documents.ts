import { query, mutation, internalQuery, internalMutation } from './_generated/server';
import { v } from 'convex/values';
import { Id } from './_generated/dataModel';

export const getDocuments = query({
  args: {},
  handler: async (ctx) => {
    const docs = await ctx.db.query('documents').collect();
    return docs.map(({ embedding, ...rest }) => rest);
  },
});

export const getByIds = internalQuery({
  args: { ids: v.array(v.id('documents')) },
  handler: async (ctx, { ids }) => {
    const results = [];
    for (const id of ids) {
      const doc = await ctx.db.get(id);
      if (doc) {
        const { embedding, ...rest } = doc;
        results.push(rest);
      }
    }
    return results;
  },
});

export const insertDocument = internalMutation({
  args: {
    content: v.string(),
    source: v.string(),
    modality: v.string(),
    imageUrl: v.optional(v.string()),
    metadata: v.any(),
    embedding: v.array(v.float64()),
  },
  handler: async (ctx, args) => {
    return await ctx.db.insert('documents', {
      ...args,
      createdAt: Date.now(),
    });
  },
});

export const insert = mutation({
  args: {
    content: v.string(),
    source: v.string(),
    modality: v.string(),
    imageUrl: v.optional(v.string()),
    metadata: v.any(),
  },
  handler: async (ctx, args) => {
    return await ctx.db.insert('documents', {
      ...args,
      embedding: [],
      createdAt: Date.now(),
    });
  },
});
