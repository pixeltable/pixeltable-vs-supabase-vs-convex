// HTTP router. Five routes, each unwrapping a JSON body, validating it, and re-wrapping
// the result.
//
// Argument validators guard the function boundary, not this one: a body that fails
// `v.string()` throws inside the action and reaches the client as a 500, a server error
// for a client mistake. httpAction is the untyped edge, so the check belongs here.

import { httpRouter } from "convex/server";
import { httpAction } from "./_generated/server";
import { api } from "./_generated/api";

const http = httpRouter();

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

class BadRequest extends Error {}

const readJson = async (req: Request): Promise<Record<string, unknown>> => {
  const body = await req.json().catch(() => null);
  if (body === null || typeof body !== "object" || Array.isArray(body)) {
    throw new BadRequest("body must be a JSON object");
  }
  return body as Record<string, unknown>;
};

const requireString = (value: unknown, field: string): string => {
  if (typeof value !== "string") throw new BadRequest(`${field} must be a string`);
  return value;
};

const readLimit = (value: unknown): number | undefined => {
  if (value === undefined || value === null) return undefined;
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new BadRequest("limit must be a non-negative integer");
  }
  return value;
};

/** Turn a BadRequest into a 400; anything else stays a 500, which is what it is. */
const guarded = (handler: (req: Request) => Promise<Response>) => async (req: Request) => {
  try {
    return await handler(req);
  } catch (err) {
    if (err instanceof BadRequest) return json({ error: err.message }, 400);
    throw err;
  }
};

http.route({
  path: "/videos",
  method: "POST",
  handler: httpAction(async (ctx, req) =>
    guarded(async (r) => {
      const body = await readJson(r);
      return json(await ctx.runAction(api.ingest.ingestVideo, {
        videoUrl: requireString(body.video, "video"),
        title: requireString(body.title, "title"),
      }));
    })(req)
  ),
});

http.route({
  path: "/videos",
  method: "GET",
  handler: httpAction(async (ctx) => json(await ctx.runQuery(api.videos.listVideos, {}))),
});

http.route({
  path: "/search/frames",
  method: "POST",
  handler: httpAction(async (ctx, req) =>
    guarded(async (r) => {
      const body = await readJson(r);
      return json(await ctx.runAction(api.search.searchFrames, {
        query: requireString(body.query, "query"),
        limit: readLimit(body.limit),
      }));
    })(req)
  ),
});

http.route({
  path: "/search/transcripts",
  method: "POST",
  handler: httpAction(async (ctx, req) =>
    guarded(async (r) => {
      const body = await readJson(r);
      return json(await ctx.runAction(api.search.searchTranscripts, {
        query: requireString(body.query, "query"),
        limit: readLimit(body.limit),
      }));
    })(req)
  ),
});

http.route({
  path: "/agent/query",
  method: "POST",
  handler: httpAction(async (ctx, req) =>
    guarded(async (r) => {
      const body = await readJson(r);
      return json(await ctx.runAction(api.agent.queryAgent, {
        question: requireString(body.question, "question"),
      }));
    })(req)
  ),
});

export default http;
