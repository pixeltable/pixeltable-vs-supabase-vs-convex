# Modal Implementation

> **676 lines across Python + SQL. 2 languages. 3 external services. 5 env vars.**

Modal is compute-only -- it has no data layer. This implementation pairs Modal's serverless containers with Supabase pgvector for storage.

## Prerequisites

- Python 3.10+
- Modal account (modal.com)
- Supabase/Neon account (for pgvector storage)
- `OPENAI_API_KEY`

## Setup (6 steps)

```bash
pip install -e ".[test]"                           # 1. Install
modal setup                                        # 2. Browser auth for Modal
# Run schema.sql on your Supabase/Neon instance    # 3. Create pgvector tables
modal secret create comparison-secrets \            # 4. Configure secrets
  OPENAI_API_KEY=sk-... \
  SUPABASE_URL=https://... \
  SUPABASE_SERVICE_ROLE_KEY=...
cp .env.example .env                               # 5. Local env for tests
modal deploy app.py                                 # 6. Deploy all endpoints
```

## What Happens at Each Phase

### Phase 1: Install

`pip install modal` + `modal setup` (browser auth). Then set up a separate pgvector database.

### Phase 2: Schema

Run SQL migrations on your external database. Modal has no schema concept.

### Phase 3: Ingest

Modal function receives upload, calls OpenAI to embed, writes to external Supabase via API.

### Phase 4: Embed

Modal function calls OpenAI embeddings API. Results stored in external pgvector. Three services wired for one embed operation.

### Phase 5: Search

Modal function embeds query via OpenAI, queries Supabase RPC, returns results. Two network hops per search.

### Phase 6: Serve

`@modal.fastapi_endpoint` decorators. Auto-scaling, per-second billing. Deploy with `modal deploy`.

### Phase 7: Dev Loop

`modal serve app.py` for ephemeral endpoints with live-reload. No data persistence in Modal -- external DB always needed.

## Architecture

```
Modal Cloud                          External Services
┌──────────────────────┐             ┌─────────────┐
│  ingest.py  (POST /upload)  ───────>│  OpenAI API │
│  search.py  (POST /search) ───────>│  (embed +   │
│  agent.py   (POST /agent)  ───────>│   chat)     │
│  search.py  (GET /documents)       └─────────────┘
└──────────┬───────────┘                     │
           │                                 │
           └──────> Supabase pgvector <──────┘
                    (external storage)
```

Every endpoint = Modal container -> OpenAI API -> Supabase pgvector.

## File Map

| File | Purpose | Lines |
|------|---------|-------|
| `app.py` | Modal App, image, secrets, helpers | 29 |
| `embeddings.py` | Embedding service class | 65 |
| `ingest.py` | Upload endpoint | 66 |
| `search.py` | Search + documents endpoints | 94 |
| `agent.py` | Agent endpoint | 80 |
| `schema.sql` | pgvector schema (run on external DB) | 62 |

## Run Tests

```bash
modal deploy app.py          # deploy first
pytest tests/ -v             # hit deployed endpoints
```

## Known Limitations

- No data layer -- requires external database for all storage
- Three services to manage (Modal + OpenAI + pgvector DB)
- Five env vars / secrets to configure
- No automatic embedding on insert
- No per-cell error tracking
- Schema lives outside Modal -- SQL migration management is separate
