// Multi-modal RAG agent. Both searches are re-invoked as actions, the prompt is
// assembled by hand, and the chat call goes to the external compute service
// because the Convex runtime cannot host a model.
//
// Compare, in pixeltable/app.py, the whole agent:
//   class Conversations(TableModel, name='conversations'):
//       question: pxt.String
//       visual = search_frames(question, limit=4)
//       spoken = search_transcripts(question, limit=4)
//       answer = create_chat_completion(...)

import { action } from "./_generated/server";
import { v } from "convex/values";
import { api } from "./_generated/api";

const COMPUTE_SERVICE_URL = process.env.COMPUTE_SERVICE_URL || "http://localhost:9000";

export const queryAgent = action({
  args: { question: v.string() },
  handler: async (ctx, args) => {
    const visual = await ctx.runAction(api.searchFrames.searchFrames, { query: args.question, limit: 4 });
    const spoken = await ctx.runAction(api.searchTranscripts.searchTranscripts, {
      query: args.question,
      limit: 4,
    });

    const seen = visual.rows.map((r) => `- ${r.video_title}, frame ${r.frame_idx}`).join("\n") || "(nothing)";
    const heard =
      spoken.rows.map((r) => `- [${r.video_title} @ ${Math.round(r.start_sec)}s] ${r.transcript}`).join("\n") ||
      "(nothing)";

    const resp = await fetch(`${COMPUTE_SERVICE_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: [
          {
            role: "user",
            content:
              `Answer the question using only the retrieved context. Be brief.\n\n` +
              `## Seen in the videos\n${seen}\n\n## Said in the videos\n${heard}\n\n` +
              `## Question\n${args.question}`,
          },
        ],
      }),
    });
    const chat = await resp.json();

    // Nothing is stored. The evidence behind this answer is gone once it is sent.
    return { rows: [{ answer: chat.content, visual: visual.rows, spoken: spoken.rows }] };
  },
});
