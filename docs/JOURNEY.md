# Developer Journey Comparison

For the full 10-phase developer journey comparison with side-by-side code, step-by-step walkthroughs, and developer emotion mapping, see the detailed analysis in the Pixeltable main repo:

[`docs/_internal/DEVELOPER_JOURNEY_COMPARISON.md`](https://github.com/pixeltable/pixeltable/blob/main/docs/_internal/DEVELOPER_JOURNEY_COMPARISON.md)

This repo is the **runnable companion** to that document. Each implementation directory contains working code for every phase described in the journey map.

## Phase-to-File Mapping

| Phase | Pixeltable | Supabase | Convex | Modal |
|-------|-----------|----------|--------|-------|
| 2. Schema | `setup_pixeltable.py` | `migrations/001_schema.sql` | `convex/schema.ts` | `schema.sql` |
| 3. Ingest | `routers/data.py` | `functions/upload/index.ts` | `convex/upload.ts` | `ingest.py` |
| 4. Embed | `setup_pixeltable.py` (computed column) | `functions/upload/index.ts` (manual) | `convex/upload.ts` (manual) | `embeddings.py` (manual) |
| 5. Search | `routers/search.py` | `functions/search/index.ts` + `002_search_function.sql` | `convex/search.ts` | `search.py` |
| 6. Serve | `main.py` | Edge Functions (Deno.serve) | `convex/http.ts` | `@modal.fastapi_endpoint` |
| 7. Agent | `routers/agent.py` | `functions/agent/index.ts` | `convex/agent.ts` | `agent.py` |
