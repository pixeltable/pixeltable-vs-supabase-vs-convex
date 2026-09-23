// Backfill for the new field. An action cannot write, so the rows come back through a
// query and go out through a mutation, in pages, because a Convex function has a time
// limit and an unbounded read is what their linter exists to stop.
import { internalAction, internalMutation, internalQuery } from "./_generated/server";
import { internal } from "./_generated/api";
import { v } from "convex/values";
import { compute } from "./compute";

const BATCH = 64;

export const videosWithoutTitleEmbedding = internalQuery({
  args: {},
  handler: async (ctx) => {
    const videos = await ctx.db.query("videos").take(1000);
    return videos.filter((video) => video.titleEmbedding === undefined)
      .slice(0, BATCH)
      .map((video) => ({ id: video._id, title: video.title }));
  },
});

export const setTitleEmbeddings = internalMutation({
  args: { rows: v.array(v.object({ id: v.id("videos"), embedding: v.array(v.float64()) })) },
  handler: async (ctx, args) => {
    for (const row of args.rows) await ctx.db.patch(row.id, { titleEmbedding: row.embedding });
  },
});

export const backfillTitleEmbeddings = internalAction({
  args: {},
  handler: async (ctx): Promise<{ backfilled: number }> => {
    let total = 0;
    for (;;) {
      const pending: { id: string; title: string }[] = await ctx.runQuery(
        internal.migrations.videosWithoutTitleEmbedding, {},
      );
      if (pending.length === 0) return { backfilled: total };
      const { embeddings } = await compute("/embed-text", { texts: pending.map((p) => p.title) });
      await ctx.runMutation(internal.migrations.setTitleEmbeddings, {
        rows: pending.map((p, i) => ({ id: p.id as never, embedding: embeddings[i] })),
      });
      total += pending.length;
    }
  },
});
