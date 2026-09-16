# Supabase: video intelligence pipeline

Five tables, three foreign keys, two HNSW indexes, two SQL search functions, one view,
a Storage bucket, one Edge Function, and an external compute service.

## Written to Supabase's own guidance

Supabase publishes concrete rules for Edge Functions, and this implementation follows
them:

- [Few large functions, not many small ones](https://supabase.com/docs/guides/functions/development-tips),
  with shared code under `_shared/`. All five contract routes are one Function.
- [Do not use `Deno.serve`](https://supabase.com/docs/guides/getting-started/ai-prompts/edge-functions).
  The handler is a default export whose `fetch` is wrapped with `withSupabase`.
- `npm:` specifiers with pinned versions, not `esm.sh`.

`withSupabase({ auth: 'secret' })` means the endpoint is authenticated: an
unauthenticated request gets a 401 naming the accepted auth modes, and the handler
receives a client that bypasses RLS. A multi-tenant application would declare
`auth: 'user'` instead and get an RLS-scoped client. Neither of the other two
implementations in this benchmark authenticates anything.

## Why the compute service

Edge Functions run on Deno, which has no subprocess and therefore no ffmpeg. Every media
operation is an HTTP call to `../compute-service/`, which you operate. Moving the models
to a hosted API would shrink that service but not remove it: frame extraction, audio
extraction and scene detection are ffmpeg.

## Setup

```bash
supabase start                  # local Docker, 12 containers, or use hosted
supabase db reset               # 001_schema, 002_search_functions, 003_storage
supabase functions deploy api
```

Also required: `../compute-service/` running on port 9000.

## Endpoints

All five contract routes are served by one Function at `/functions/v1/api`:

| Contract endpoint | Path |
|---|---|
| `POST /videos` | `/functions/v1/api/videos` |
| `GET /videos` | `/functions/v1/api/videos` |
| `POST /search/frames` | `/functions/v1/api/search/frames` |
| `POST /search/transcripts` | `/functions/v1/api/search/transcripts` |
| `POST /agent/query` | `/functions/v1/api/agent/query` |

## Known limits, stated rather than hidden

- Processing lives in the ingest path, so a row inserted by anything else is not
  processed. Restoring that means database triggers and one webhook per row.
- Nothing enforces that a query vector came from the model that filled the column it
  searches. The dimension is the only guard, and 384 equals 384.
- Adding a derived column later means a migration and a backfill script.

## What this benchmark does not use, and should be counted in Supabase's favour

PostgREST would serve `GET /videos` and both searches with no handler code at all.
Realtime, Auth and row-level security, Storage image transforms, point-in-time recovery
and database branching are all absent here. See [../docs/TRADEOFFS.md](../docs/TRADEOFFS.md).
