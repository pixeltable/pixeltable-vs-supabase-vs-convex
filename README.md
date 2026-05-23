# Platform Comparison: Multimodal AI Knowledge Base

> **How does building the same multimodal AI app compare across Pixeltable, Supabase, Convex, and Modal?**

This repo contains four implementations of the **same application** -- a multimodal knowledge base with semantic search and an AI agent -- built with four different platforms. Each implementation exposes identical HTTP endpoints, accepts the same inputs, and returns the same response shapes.

The goal: a living, runnable benchmark that measures developer experience, code complexity, and architectural trade-offs -- not runtime performance.

## The App

All four implementations build the same thing:

```
User uploads text docs + images
  -> auto-chunk, describe (vision LLM), embed (OpenAI)
  -> store in vector index
  -> semantic search across both modalities
  -> agent answers questions using RAG + web search tools
```

**API surface** (identical across all four):

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/upload` | POST | Upload a text document or image |
| `/search` | POST | Semantic search across the knowledge base |
| `/agent/query` | POST | Ask the AI agent a question (RAG) |
| `/documents` | GET | List all ingested documents |

## Quick Scorecard

### DX Metrics (auto-generated)

| Metric | Pixeltable | Supabase | Convex | Modal |
|--------|-----------|----------|--------|-------|
| **Lines of Code** | 368 | 617 | 434 | 676 |
| **Source Files** | 14 | 9 | 9 | 11 |
| **Languages** | 1 (Python) | 2 (TS + SQL) | 1 (TS) | 2 (Python + SQL) |
| **External Services** | 1 (OpenAI) | 2 (Supabase Cloud, OpenAI) | 2 (Convex Cloud, OpenAI) | 3 (Modal, Supabase, OpenAI) |
| **Env Vars Required** | 1 | 4 | 2 | 5 |
| **Cloud Account Needed** | No | Yes | Yes | Yes |

### Journey Scorecard

Rating: **Strong** = clear advantage, **Okay** = functional but friction, **Weak** = significant pain, **Gap** = not available.

| Phase | Pixeltable | Supabase | Convex | Modal |
|-------|-----------|----------|--------|-------|
| 1. Install & Setup | **Strong** | Okay | Okay | Okay |
| 2. Define Schema | **Strong** | Okay | Okay | Gap (no DB) |
| 3. Ingest Data | **Strong** | Okay | Okay | Gap (no DB) |
| 4. Add Embeddings | **Strong** | Weak | Weak | Okay |
| 5. Semantic Search | **Strong** | Okay | Okay | Gap (no DB) |
| 6. Serve API | **Strong** | Okay | Okay | Okay |
| 7. Dev Loop | **Strong** | Okay | Okay | Okay |
| 8. Deploy to Prod | Gap* | Okay | **Strong** | **Strong** |
| 9. Schema Evolution | Weak* | Weak | Weak | Okay |
| 10. Monitor & Scale | Gap* | Okay | **Strong** | **Strong** |

*Pixeltable's cloud deployment (Live Tables) is on the [Q2-Q3 2026 roadmap](https://github.com/pixeltable/pixeltable).

## Side-by-Side: The Same Operation, Four Ways

### Embed documents on insert

**Pixeltable** -- 3 lines (declarative, automatic):
```python
t.add_computed_column(embed=embeddings(input=t.text, model='text-embedding-3-small'))
t.add_embedding_index('text', embedding=embeddings.using(model='text-embedding-3-small'))
# Every future insert auto-embeds. Done.
```

**Supabase** -- 25+ lines (imperative, per-document):
```typescript
// Edge Function: manually call OpenAI, parse response, UPDATE row
const embeddingResp = await fetch('https://api.openai.com/v1/embeddings', {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${openaiKey}`, 'Content-Type': 'application/json' },
  body: JSON.stringify({ model: 'text-embedding-3-small', input: content }),
});
const { data } = await embeddingResp.json();
await supabase.from('documents').update({ embedding: data[0].embedding }).eq('id', docId);
// Must trigger this for every new document (webhook, cron, or inline)
```

**Convex** -- 15+ lines (action + mutation, per-document):
```typescript
// Action (required for external API calls):
const embeddingResp = await openai.embeddings.create({
  model: 'text-embedding-3-small', input: content,
});
// Separate mutation to store (vectorSearch requires action context):
await ctx.runMutation(internal.documents.insertDocument, {
  ...args, embedding: embeddingResp.data[0].embedding,
});
```

**Modal** -- 20+ lines (Modal function + external DB):
```python
# Modal function calls OpenAI, then writes to external Supabase pgvector:
response = openai_client.embeddings.create(model='text-embedding-3-small', input=content)
embedding = response.data[0].embedding
supabase_client.table('documents').insert({'content': content, 'embedding': embedding}).execute()
# Three services wired together for one insert
```

### Semantic search

**Pixeltable** -- 2 lines:
```python
sim = t.text.similarity(string=query)
results = t.order_by(sim, asc=False).limit(10).select(t.text, sim).collect()
```

**Supabase** -- 15 lines (SQL function + Edge Function + manual query embedding):
```sql
-- Step 1: SQL function (migration)
CREATE FUNCTION search_documents(query_embedding vector(1536), match_count int)
RETURNS TABLE(...) AS $$ SELECT ... ORDER BY embedding <=> query_embedding LIMIT match_count; $$;
```
```typescript
// Step 2: Edge Function — embed query, then RPC
const embedding = await embedQuery(query);
const { data } = await supabase.rpc('search_documents', { query_embedding: embedding, match_count: limit });
```

**Convex** -- 12 lines (action required, 256-result cap):
```typescript
const embedding = await getEmbedding(query);  // manual OpenAI call
const results = await ctx.vectorSearch('documents', 'by_embedding', {
  vector: embedding, limit: Math.min(limit, 256),  // hard 256 cap
});
const docs = await ctx.runQuery(internal.documents.getByIds, { ids: results.map(r => r._id) });
```

**Modal** -- 15 lines (Modal -> OpenAI -> Supabase):
```python
embedding = openai_client.embeddings.create(model='text-embedding-3-small', input=query)
result = supabase_client.rpc('search_documents', {
    'query_embedding': embedding.data[0].embedding, 'match_count': limit
}).execute()
```

## Repo Structure

```
platform-comparison/
├── README.md                    # This file
├── AGENTS.md                    # AI agent coding instructions
├── fixtures/                    # Shared test data (3 docs, 3 images, 5 queries)
├── pixeltable/                  # Implementation 1: Pixeltable (Python, 368 LOC)
├── supabase-app/                # Implementation 2: Supabase (TS + SQL, 617 LOC)
├── convex-app/                  # Implementation 3: Convex (TS, 434 LOC)
├── modal-app/                   # Implementation 4: Modal + pgvector (Python + SQL, 676 LOC)
├── harness/                     # Cross-platform test harness + metrics
│   ├── api_contract.py          # Shared Pydantic models for the API surface
│   ├── metrics.py               # LOC counter + DX metrics
│   ├── test_equivalence.py      # Same queries -> comparable results
│   └── run_comparison.py        # Run metrics + tests
└── docs/
    ├── JOURNEY.md               # Full 10-phase developer journey comparison
    ├── METHODOLOGY.md           # How we measure, what counts
    └── SCORECARD.md             # Living scorecard updated per release
```

## Run It Yourself

### Pixeltable

```bash
cd pixeltable
pip install -e ".[test]"       # or: uv sync
cp .env.example .env           # add OPENAI_API_KEY
python setup_pixeltable.py     # creates tables + computed columns + indexes
python main.py                 # FastAPI on :8000
pytest tests/                  # integration tests
```

### Supabase

```bash
cd supabase-app
npm install
supabase init                  # if not already initialized
supabase start                 # Docker-based local Postgres
supabase db push               # apply migrations
supabase functions deploy      # deploy Edge Functions
npx tsx scripts/seed.ts        # seed fixture data (manual embedding loop)
npm test                       # vitest
```

### Convex

```bash
cd convex-app
npm install
npx convex dev                 # creates project, syncs schema + functions
# Set OPENAI_API_KEY in Convex dashboard
npm test                       # vitest
```

### Modal

```bash
cd modal-app
pip install -e ".[test]"
modal setup                    # browser auth
# Run schema.sql on your Supabase/Neon instance
# Set secrets: modal secret create comparison-secrets OPENAI_API_KEY=... SUPABASE_URL=...
modal deploy app.py            # deploys all endpoints
pytest tests/                  # integration tests
```

### Metrics

```bash
python harness/run_comparison.py               # DX metrics (no servers needed)
python harness/run_comparison.py --test-all     # + equivalence tests
```

## Methodology

See [docs/METHODOLOGY.md](docs/METHODOLOGY.md) for full details. In brief:

- **Lines of Code** counts non-empty, non-comment lines in application source files. Generated code, lock files, and config files are excluded.
- **External Services** counts cloud services that require an account and API key.
- **Journey Scorecard** is assessed manually against the 10-phase developer journey in [docs/JOURNEY.md](docs/JOURNEY.md).
- All implementations use the same OpenAI models, the same fixture data, and expose the same API contract.

## Contributing

When a platform ships a new feature that changes the comparison:

1. Update the relevant implementation
2. Run `python harness/run_comparison.py` to refresh metrics
3. Update `docs/SCORECARD.md` if the journey scorecard changes
4. Open a PR with before/after metrics

## License

Apache 2.0. See [LICENSE](LICENSE).
