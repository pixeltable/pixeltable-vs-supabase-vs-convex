'use node';

import { action } from './_generated/server';
import { internal } from './_generated/api';
import { v } from 'convex/values';
import OpenAI from 'openai';

const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

export const search = action({
  args: {
    query: v.string(),
    limit: v.optional(v.number()),
  },
  handler: async (ctx, { query, limit }) => {
    const effectiveLimit = Math.min(limit ?? 10, 256); // Convex vector search caps at 256 results

    // Step 1: Manually embed the query — no automatic embedding in Convex
    const embeddingResponse = await openai.embeddings.create({
      model: 'text-embedding-3-small',
      input: query,
    });
    const queryVector = embeddingResponse.data[0].embedding;

    // Step 2: Vector search only available in actions, returns IDs + scores
    const vectorResults = await ctx.vectorSearch('documents', 'by_embedding', {
      vector: queryVector,
      limit: effectiveLimit,
    });

    if (vectorResults.length === 0) {
      return [];
    }

    // Step 3: Must run a separate query to load full documents (two-step pattern)
    const ids = vectorResults.map((r) => r._id);
    const docs = await ctx.runQuery(internal.documents.getByIds, { ids });

    // Step 4: Merge scores with documents
    return docs.map((doc, i) => ({
      ...doc,
      score: vectorResults[i]._score,
    }));
  },
});
