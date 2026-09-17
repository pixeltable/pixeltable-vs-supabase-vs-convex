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
- Request bodies are validated at the handler, in `_shared/client.ts`. Deno has no
  request-validation layer, so without it a missing field is an unhandled throw and
  the Edge Runtime reports a client's mistake as a 500.
- `video_summary` lists only `status = 'ready'`. Ingest writes the row before processing
  it, to get an id, so a failed media step leaves the row behind; the contract's list row
  carries no status, so listing it would tell a caller it processed.

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

`../compute-service/` has to be running on port 9000 first.

```bash
cp .env.example .env.local      # COMPUTE_SERVICE_URL, reachable from inside the runtime
supabase start                  # local Docker, 12 containers; applies all four migrations
supabase functions serve --env-file .env.local
```

`--env-file` is not optional. The Function reads `COMPUTE_SERVICE_URL` and falls back to
`http://localhost:9000`, which inside the Edge Runtime container is the container, so
every ingest fails at the first media call. `host.docker.internal` is the host from
there.

`supabase functions deploy` is the hosted path and needs a linked project; `serve` is the
local one, and it is what this benchmark runs.

## Endpoints

All five contract routes are served by one Function at `/functions/v1/api`:

| Contract endpoint | Path |
|---|---|
| `POST /videos` | `/functions/v1/api/videos` |
| `GET /videos` | `/functions/v1/api/videos` |
| `POST /search/frames` | `/functions/v1/api/search/frames` |
| `POST /search/transcripts` | `/functions/v1/api/search/transcripts` |
| `POST /agent/query` | `/functions/v1/api/agent/query` |

## Supabase's own advisors

`supabase db advisors --local --type all` inspects the running database and exits
non-zero on findings. Against this schema it reports **no errors**. Row-level security is
enabled on all five tables, `video_summary` is `security_invoker`, and both search
functions pin `search_path = ''`.

Enabling RLS with no policies is the right shape here: every client goes through the
Edge Function holding the service role, which bypasses RLS, while PostgREST's anon and
authenticated roles are denied direct table access. You can check that:

```bash
curl "$SUPABASE_URL/rest/v1/videos?select=*" -H "apikey: $PUBLISHABLE_KEY"   # []
```

A multi-tenant application would write per-table policies against `auth.uid()` instead.

One warning is left deliberately: `extension_in_public`, because `pgvector` lives in
`public`. Moving it means qualifying the `<=>` operator and the `vector` type at every
use, which trades a hygiene warning for noticeably more SQL. Locking `search_path`
already forced `OPERATOR(public.<=>)` into both search functions; that is the visible
cost of the fix, and it is in `002_search_functions.sql`.

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
