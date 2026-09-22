# Supabase: video intelligence pipeline

Five tables, three foreign keys, two HNSW indexes, two SQL search functions, one
view, a Storage bucket, one Edge Function, and an external compute service.

## Written to Supabase's own guidance

- [Few large functions, not many small ones](https://supabase.com/docs/guides/functions/development-tips):
  all five routes are one Function, shared code under `_shared/`.
- [Not `Deno.serve`](https://supabase.com/docs/guides/getting-started/ai-prompts/edge-functions):
  a default export whose `fetch` is wrapped with `withSupabase`.
- `npm:` specifiers with pinned versions, not `esm.sh`.
- Bodies validated at the handler (`_shared/client.ts`): Deno has no request
  validation, so an unchecked missing field becomes a 500.
- `video_summary` lists only `status = 'ready'`: ingest writes the row before
  processing, and a failed media step would otherwise list it.

`withSupabase({ auth: 'secret' })` authenticates the endpoint (a 401 naming the
accepted modes) and hands the handler a client that bypasses RLS. Neither other
implementation authenticates anything.

## Why the compute service

Deno has no subprocess, so no ffmpeg. Every media operation is an HTTP call to
`../compute-service/`; a hosted API would shrink it but not remove it.

## Setup

`../compute-service/` on port 9000 first, then:

```bash
cp .env.example supabase/functions/.env   # COMPUTE_SERVICE_URL, read inside the runtime
supabase start                            # local Docker, 12 containers; applies all migrations
```

`COMPUTE_SERVICE_URL` defaults to `http://localhost:9000`, which inside the edge
runtime is the container; `host.docker.internal` is the host. The runtime reads
`supabase/functions/.env` at creation, so a change takes `supabase stop && supabase
start`.

## Endpoints

One Function at `/functions/v1/api`, five routes: `videos` (POST, GET),
`search/frames`, `search/transcripts`, `agent/query`.

## Supabase's own advisors

`supabase db advisors --local --type all` reports **no errors**. RLS is enabled on
all five tables, `video_summary` is `security_invoker`, both search functions pin
`search_path = ''` (which is why `OPERATOR(public.<=>)` appears in
`002_search_functions.sql`). With no policies, PostgREST's anon role is denied
direct table access:

```bash
curl "$SUPABASE_URL/rest/v1/videos?select=*" -H "apikey: $PUBLISHABLE_KEY"   # []
```

One warning is left deliberately: `extension_in_public`, because `pgvector` lives in
`public`.

## Known limits

- Processing lives in the ingest path; a row inserted any other way is not
  processed.
- Nothing checks a query vector came from the model that filled the column.
- Adding a derived column means a migration and a backfill script.

## What this benchmark does not use

PostgREST would serve `GET /videos` and both searches with no handler code. Absent
by grep: `CREATE POLICY`, `auth.uid()`, `[realtime]`, `pg_cron`, `pg_net`, triggers,
Storage policies, transforms. Priced in
[../docs/TRADEOFFS.md](../docs/TRADEOFFS.md#what-this-benchmark-does-not-measure).
