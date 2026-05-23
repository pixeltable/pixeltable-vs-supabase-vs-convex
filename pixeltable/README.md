# Pixeltable Implementation

> **368 lines of Python. 1 language. 1 external service. 1 env var.**

## Prerequisites

- Python 3.10+
- `OPENAI_API_KEY`

No cloud account. No Docker. No browser.

## Setup (3 steps)

```bash
pip install -e ".[test]"       # 1. Install
cp .env.example .env           # 2. Add OPENAI_API_KEY
python main.py                 # 3. Run (schema auto-creates on startup)
```

## What Happens at Each Phase

### Phase 1: Install

`pip install pixeltable` -- embedded Postgres starts automatically on first import. No provisioning.

### Phase 2: Schema

`setup_pixeltable.py` creates the entire data model in ~20 lines:

```python
t = pxt.create_table('kb.documents', {
    'text': pxt.String, 'source': pxt.String, 'modality': pxt.String,
    'metadata': pxt.Json, 'image': pxt.Image,
}, if_exists='ignore')
```

No SQL. No migration files. No dimensions to pre-declare.

### Phase 3: Ingest

```python
t.insert([{'text': '...', 'source': 'doc.txt', 'modality': 'text'}])
```

One line. Computed columns fire automatically.

### Phase 4: Embed

Declared once as a computed column. Runs on every insert. Retries automatically. Per-cell error tracking.

```python
t.add_computed_column(embed_text=embeddings(input=t.text, model='text-embedding-3-small'))
t.add_embedding_index('text', embedding=embeddings.using(model='text-embedding-3-small'))
```

### Phase 5: Search

```python
sim = docs.text.similarity(string=query)
results = docs.order_by(sim, asc=False).limit(limit).select(docs.text, sim).collect()
```

Two lines. Query embedding handled internally.

### Phase 6: Serve

`pxt serve` for zero-code CLI, or `FastAPIRouter` for programmatic control. Auto-generated OpenAPI docs at `/docs`.

### Phase 7: Dev Loop

Just run Python. Schema changes via method calls. No Docker, no migration files, fully offline.

## Architecture

```
main.py (FastAPI)
  ├── routers/data.py      POST /upload, GET /documents
  ├── routers/search.py    POST /search
  └── routers/agent.py     POST /agent/query
        │
        └── setup_pixeltable.py (schema)
              ├── kb.documents (table + computed columns + embedding index)
              └── kb.conversations (chat history)
```

## File Map

| File | Purpose | Lines |
|------|---------|-------|
| `setup_pixeltable.py` | Schema, computed columns, indexes | 62 |
| `main.py` | FastAPI app with lifespan init | 17 |
| `routers/data.py` | Upload + list endpoints | 30 |
| `routers/search.py` | Semantic search endpoint | 26 |
| `routers/agent.py` | Agent chat endpoint | 48 |
| `functions.py` | web_search UDF + search query | 19 |
| `config.py` | Env-driven configuration | 7 |

## Run Tests

```bash
# Start the server first
python main.py &
pytest tests/ -v
```

## Known Limitations

- No managed cloud deployment yet (roadmap Q2-Q3 2026)
- No auto-scaling (single embedded Postgres)
- Schema evolution requires drop + re-add for computed columns (roadmap: `alter_computed_column`)
