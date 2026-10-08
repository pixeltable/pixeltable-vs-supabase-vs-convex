import { mutation, query } from "./_generated/server";
import { v } from "convex/values";

export const insertDoc = mutation({
  args: {
    title: v.string(),
    body: v.string(),
  },
  handler: async (ctx, args) => {
    const docId = await ctx.db.insert("docs", {
      title: args.title,
      body: args.body,
      createdAt: Date.now(),
    });
    return { id: docId, title: args.title, status: "created" };
  },
});

export const listDocs = query({
  args: {},
  handler: async (ctx) => {
    const docs = await ctx.db.query("docs").order("desc").take(10);
    return docs;
  },
});

// 100 documents in one mutation, which Convex runs as one transaction: the batch-ingest path.
export const insertDocsBatch = mutation({
  args: {
    docs: v.array(v.object({ title: v.string(), body: v.string() })),
  },
  handler: async (ctx, args) => {
    const createdAt = Date.now();
    for (const doc of args.docs) {
      await ctx.db.insert("docs", { title: doc.title, body: doc.body, createdAt });
    }
    return { inserted: args.docs.length };
  },
});

// One document by id: the read path.
export const getDoc = query({
  args: { id: v.id("docs") },
  handler: async (ctx, args) => {
    return await ctx.db.get(args.id);
  },
});
