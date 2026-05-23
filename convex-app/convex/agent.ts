'use node';

import { action } from './_generated/server';
import { internal } from './_generated/api';
import { v } from 'convex/values';
import OpenAI from 'openai';

const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

export const queryAgent = action({
  args: {
    message: v.string(),
    conversationId: v.optional(v.string()),
  },
  handler: async (ctx, { message, conversationId }) => {
    const convId = conversationId ?? crypto.randomUUID();

    // Step 1: Embed the user message
    const embeddingResponse = await openai.embeddings.create({
      model: 'text-embedding-3-small',
      input: message,
    });
    const queryVector = embeddingResponse.data[0].embedding;

    // Step 2: Vector search for relevant context (only available in actions)
    const vectorResults = await ctx.vectorSearch('documents', 'by_embedding', {
      vector: queryVector,
      limit: 5,
    });

    // Step 3: Load full documents via separate internal query (two-step pattern)
    let contextDocs: Array<{ content: string; source: string; modality: string }> = [];
    if (vectorResults.length > 0) {
      const ids = vectorResults.map((r) => r._id);
      contextDocs = await ctx.runQuery(internal.documents.getByIds, { ids });
    }

    // Step 4: Build prompt with retrieved context
    const contextBlock = contextDocs
      .map((doc, i) => `[${i + 1}] (${doc.source}, ${doc.modality}): ${doc.content}`)
      .join('\n\n');

    const systemPrompt = `You are a helpful assistant with access to a knowledge base.
Use the following context to answer the user's question. Cite sources by number.
If the context doesn't contain relevant information, say so.

Context:
${contextBlock || 'No relevant documents found.'}`;

    // Step 5: Call OpenAI chat completions
    const chatResponse = await openai.chat.completions.create({
      model: 'gpt-4o-mini',
      messages: [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: message },
      ],
      temperature: 0.7,
      max_tokens: 1000,
    });

    const answer = chatResponse.choices[0].message.content ?? '';
    const sources = contextDocs.map((doc) => ({
      source: doc.source,
      modality: doc.modality,
      content: doc.content.slice(0, 200),
    }));

    return { answer, sources, conversationId: convId };
  },
});
