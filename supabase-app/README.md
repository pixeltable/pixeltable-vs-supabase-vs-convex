# Supabase Implementation

> **617 lines across TypeScript + SQL. 2 languages. 2 external services. 4 env vars.**

## Prerequisites

- Node.js 18+
- Supabase CLI (`npm install -g supabase`)
- Docker (for local Supabase)
- Supabase account (supabase.com)
- `OPENAI_API_KEY`

## Setup (7 steps)

```bash
npm install                            # 1. Install deps
supabase init                          # 2. Initialize project (if fresh)
supabase start                         # 3. Start local Postgres (Docker)
supabase db push                       # 4. Apply migrations (pgvector + HNSW)
cp .env.example .env                   # 5. Add all 4 keys
supabase functions deploy              # 6. Deploy Edge Functions
npx tsx scripts/seed.ts                # 7. Seed data (manual embedding loop)
```

## What Happens at Each Phase

### Phase 1: Install

Create Supabase project in browser. Copy 3 API keys. Install supabase-js. Enable pgvector extension via SQL.

### Phase 2: Schema

Hand-write SQL migration:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  content TEXT, source TEXT, modality TEXT,
  embedding VECTOR(1536), ...
);
CREATE INDEX ON documents USING hnsw (embedding vector_cosine_ops);
```

Must choose vector dimensions (1536) and index type (HNSW vs IVFFlat) upfront.

### Phase 3: Ingest

Insert row with embedding = NULL. Must backfill embeddings separately.

### Phase 4: Embed

Write an Edge Function that calls OpenAI, parses the response, and UPDATEs the row. Repeat for every document. Handle rate limits and retries manually.

### Phase 5: Search

Write a SQL RPC function (`002_search_function.sql`), then call it from another Edge Function that first embeds the query. Two languages for one search operation.

### Phase 6: Serve

Each endpoint is a separate Deno Edge Function with `Deno.serve()`. Deploy with `supabase functions deploy`.

### Phase 7: Dev Loop

`supabase start` requires Docker. Schema changes require SQL migration files. Must manually re-run embedding for schema changes.

## Architecture

```
supabase/functions/
  ├── upload/index.ts      POST /upload (embed + insert, ~87 lines)
  ├── search/index.ts      POST /search (embed query + RPC, ~47 lines)
  └── agent/index.ts       POST /agent/query (embed + search + chat, ~82 lines)

supabase/migrations/
  ├── 001_schema.sql       pgvector table + HNSW index
  └── 002_search_function.sql  search_documents() RPC
```

## File Map

| File | Purpose | Lines |
|------|---------|-------|
| `migrations/001_schema.sql` | pgvector table, HNSW index, RLS | 32 |
| `migrations/002_search_function.sql` | Vector search RPC function | 32 |
| `functions/upload/index.ts` | Embed + insert Edge Function | 87 |
| `functions/search/index.ts` | Query embed + RPC Edge Function | 47 |
| `functions/agent/index.ts` | RAG agent Edge Function | 82 |
| `scripts/seed.ts` | Fixture seeder (manual embed loop) | 138 |

## Run Tests

```bash
supabase start                  # local Postgres + Edge Functions
npm test                        # vitest
```

## Known Limitations

- Manual embedding on every insert (no computed columns)
- Two languages required (SQL + TypeScript)
- No per-cell error tracking
- Re-embedding on model swap requires a manual backfill script
- Docker required for local development
