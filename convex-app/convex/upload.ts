'use node';

import { action } from './_generated/server';
import { internal } from './_generated/api';
import { v } from 'convex/values';
import OpenAI from 'openai';

const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

async function embedText(text: string): Promise<number[]> {
  const response = await openai.embeddings.create({
    model: 'text-embedding-3-small',
    input: text,
  });
  return response.data[0].embedding;
}

async function describeImage(imageUrl: string): Promise<string> {
  const response = await openai.chat.completions.create({
    model: 'gpt-4o-mini',
    messages: [
      {
        role: 'user',
        content: [
          {
            type: 'text',
            text: 'Describe this image in detail for use as a searchable document.',
          },
          { type: 'image_url', image_url: { url: imageUrl } },
        ],
      },
    ],
    max_tokens: 500,
  });
  return response.choices[0].message.content ?? '';
}

export const upload = action({
  args: {
    content: v.optional(v.string()),
    imageUrl: v.optional(v.string()),
    source: v.string(),
    metadata: v.optional(v.any()),
  },
  handler: async (ctx, { content, imageUrl, source, metadata }) => {
    let textToEmbed: string;
    let modality: string;
    let finalContent: string;

    if (imageUrl) {
      modality = 'image';
      finalContent = await describeImage(imageUrl);
      textToEmbed = finalContent;
    } else if (content) {
      modality = 'text';
      finalContent = content;
      textToEmbed = content;
    } else {
      throw new Error('Either content or imageUrl must be provided');
    }

    const embedding = await embedText(textToEmbed);

    const id = await ctx.runMutation(internal.documents.insertDocument, {
      content: finalContent,
      source,
      modality,
      imageUrl,
      metadata: metadata ?? {},
      embedding,
    });

    return { id, source, modality };
  },
});
