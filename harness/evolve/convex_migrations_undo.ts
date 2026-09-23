// Undoing it needs a second migration. Convex validates every existing document against
// the schema on push, so removing `titleEmbedding` from schema.ts while documents still
// carry it is rejected: the field has to come off the rows first.
import { internalMutation } from "./_generated/server";

export const clearTitleEmbeddings = internalMutation({
  args: {},
  handler: async (ctx) => {
    const videos = await ctx.db.query("videos").take(1000);
    for (const video of videos) {
      if (video.titleEmbedding !== undefined) {
        await ctx.db.patch(video._id, { titleEmbedding: undefined });
      }
    }
    return { cleared: videos.length };
  },
});
