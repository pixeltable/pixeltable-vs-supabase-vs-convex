// HTTP router. Five routes, each unwrapping a JSON body and re-wrapping the result.

import { httpRouter } from "convex/server";
import { httpAction } from "./_generated/server";
import { api } from "./_generated/api";

const http = httpRouter();

const json = (body: unknown) =>
  new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });

http.route({
  path: "/videos",
  method: "POST",
  handler: httpAction(async (ctx, req) => {
    const body = await req.json();
    return json(await ctx.runAction(api.ingest.ingestVideo, { videoUrl: body.video, title: body.title }));
  }),
});

http.route({
  path: "/videos",
  method: "GET",
  handler: httpAction(async (ctx) => json(await ctx.runQuery(api.videos.listVideos))),
});

http.route({
  path: "/search/frames",
  method: "POST",
  handler: httpAction(async (ctx, req) => {
    const body = await req.json();
    return json(await ctx.runAction(api.searchFrames.searchFrames, { query: body.query, limit: body.limit }));
  }),
});

http.route({
  path: "/search/transcripts",
  method: "POST",
  handler: httpAction(async (ctx, req) => {
    const body = await req.json();
    return json(
      await ctx.runAction(api.searchTranscripts.searchTranscripts, { query: body.query, limit: body.limit }),
    );
  }),
});

http.route({
  path: "/agent/query",
  method: "POST",
  handler: httpAction(async (ctx, req) => {
    const body = await req.json();
    return json(await ctx.runAction(api.agent.queryAgent, { question: body.question }));
  }),
});

export default http;
