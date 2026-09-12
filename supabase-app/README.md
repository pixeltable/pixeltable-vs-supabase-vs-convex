# Supabase: video intelligence pipeline

Five tables (four for the data, one to hold the URL and key the triggers call back
with), three foreign keys, two HNSW indexes, two SQL search functions, two database
triggers, a Storage bucket, seven Edge Functions, and an external compute service.
The whole of it does what `pixeltable/app.py` declares in one file.

## Why the compute service

Edge Functions run on Deno. Deno cannot run ffmpeg, Whisper, CLIP, or a local chat
model, so every media operation is an HTTP call to `../compute-service/`. That
service is not part of Supabase and you operate it yourself.

## Architecture

```
POST ingest
  ├─ compute-service /extract-frames  ─> Storage upload ─> INSERT frames  ─┐
  ├─ compute-service /extract-audio   ─> INSERT audio_chunks              ─┤ one trigger
  └─ compute-service /detect-scenes   ─> INSERT scenes                     │ per row
                                                                           v
         trigger ─> process-frames ─> compute-service /embed-clip ─> UPDATE frames
         trigger ─> process-audio  ─> compute-service /transcribe + /embed-text
                                   ─> UPDATE audio_chunks
```

A 15 second video at 1 FPS produces 15 frame rows, so ingesting it fires 15
`process-frames` webhooks and 2 `process-audio` webhooks. Nothing retries a failed
one: the row keeps a NULL embedding and silently drops out of search.

## Setup

```bash
npm install
supabase start                  # local Docker, 12 containers
supabase db push                # 001_schema, 002_search_functions, 003_pipeline
```

`supabase start` prints a `SERVICE_ROLE_KEY`. The triggers call the Edge Functions
back with it, so store it:

```bash
KEY=$(supabase status -o json | jq -r .SERVICE_ROLE_KEY)
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" \
  -c "UPDATE pipeline_config SET value='$KEY' WHERE key='service_role_key'"
```

Without this the triggers fire and are rejected, every embedding stays NULL, and every
search returns nothing.

Then deploy all seven functions:

```bash
for fn in ingest process-frames process-audio search-frames search-transcripts list-videos agent; do
  supabase functions deploy "$fn"
done
```

Also required: `../compute-service/` running on port 9000.

## Endpoints

| Contract endpoint | Edge Function |
|---|---|
| `POST /videos` | `/functions/v1/ingest` |
| `GET /videos` | `/functions/v1/list-videos` |
| `POST /search/frames` | `/functions/v1/search-frames` |
| `POST /search/transcripts` | `/functions/v1/search-transcripts` |
| `POST /agent/query` | `/functions/v1/agent` |

## Known limits, stated rather than hidden

- `videos.status` is written by the ingest function before any embedding exists, so
  it cannot be trusted. `video_status()` in `003_pipeline.sql` derives the real one
  by counting NULL embeddings.
- Nothing enforces that a query vector came from the model that filled the column
  it searches. The dimension check is the only guard, and 384 equals 384.
- Adding a column later means a migration, a backfill script, and a re-run.
