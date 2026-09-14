// Multi-modal RAG agent. Both retrievals run as plain async helpers rather than
// ctx.runAction on public actions, per Convex's best-practices guide.
//
// Compare, in pixeltable/app.py, the whole agent:
//   class Conversations(TableModel, name='conversations'):
//       question: pxt.String
//       visual = frames_seen(question, limit=4)
//       spoken = search_transcripts(question, limit=4)
//       answer = create_chat_completion(...)
// There, retrieval is a column. Here it is something the handler assembles and writes.

import { action } from "./_generated/server";
import { v } from "convex/values";
import { internal } from "./_generated/api";
import { compute } from "./compute";
import { findFrames, findTranscripts } from "./search";

export const queryAgent = action({
  args: { question: v.string() },
  // Explicit return type, same circular-reference reason as ingest.ts.
  handler: async (ctx, args): Promise<{ rows: { answer: string; visual: unknown[]; spoken: unknown[] }[] }> => {
    const [visual, spoken] = await Promise.all([
      findFrames(ctx, args.question, 4),
      findTranscripts(ctx, args.question, 4),
    ]);

    const seen = visual.map((r) => `- ${r.video_title}, frame ${r.frame_idx}`).join("\n") || "(nothing)";
    const heard =
      spoken.map((r) => `- [${r.video_title} @ ${Math.round(r.start_sec)}s] ${r.transcript}`).join("\n") ||
      "(nothing)";

    const chat = await compute("/chat", {
      messages: [{
        role: "user",
        content: `Answer the question using only the retrieved context. Be brief.\n\n` +
          `## Seen in the videos\n${seen}\n\n## Said in the videos\n${heard}\n\n` +
          `## Question\n${args.question}`,
      }],
    });

    await ctx.runMutation(internal.videos.saveConversation, {
      question: args.question,
      answer: chat.content,
      visual,
      spoken,
    });

    return { rows: [{ answer: chat.content, visual, spoken }] };
  },
});
