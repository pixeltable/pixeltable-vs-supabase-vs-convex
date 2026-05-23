import { httpRouter } from 'convex/server';
import { httpAction } from './_generated/server';
import { api, internal } from './_generated/api';

const http = httpRouter();

http.route({
  path: '/upload',
  method: 'POST',
  handler: httpAction(async (ctx, request) => {
    const body = await request.json();
    const result = await ctx.runAction(api.upload.upload, {
      content: body.content,
      imageUrl: body.imageUrl,
      source: body.source ?? 'api',
      metadata: body.metadata,
    });
    return new Response(JSON.stringify(result), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }),
});

http.route({
  path: '/search',
  method: 'POST',
  handler: httpAction(async (ctx, request) => {
    const body = await request.json();
    const results = await ctx.runAction(api.search.search, {
      query: body.query,
      limit: body.limit,
    });
    return new Response(JSON.stringify({ results }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }),
});

http.route({
  path: '/agent/query',
  method: 'POST',
  handler: httpAction(async (ctx, request) => {
    const body = await request.json();
    const result = await ctx.runAction(api.agent.queryAgent, {
      message: body.message,
      conversationId: body.conversationId,
    });
    return new Response(JSON.stringify(result), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }),
});

http.route({
  path: '/documents',
  method: 'GET',
  handler: httpAction(async (ctx) => {
    const docs = await ctx.runQuery(api.documents.getDocuments);
    return new Response(JSON.stringify({ documents: docs }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }),
});

export default http;
