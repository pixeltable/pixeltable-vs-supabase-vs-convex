# Convex: video intelligence pipeline

Four tables, two vector indexes, three by_video indexes, nine TypeScript files, six
actions, thirteen internal queries and mutations, two scheduled jobs, and an external
compute service. The whole of it does what `pixeltable/app.py` declares in one file.

## Why the compute service

The Convex runtime cannot run ffmpeg, Whisper, CLIP, or a local chat model, so every
media operation is an HTTP call to `../compute-service/`. That service is not part of
Convex and you operate it yourself.

## Architecture

```
ingestVideo action
  ├─ compute-service /extract-frames ─> ctx.storage.store ─> insertFrame mutation
  ├─ compute-service /extract-audio  ─> insertAudioChunk mutation
  └─ compute-service /detect-scenes  ─> insertScene mutation
        │
        └─ scheduler.runAfter(0, ...)
              ├─ embedAllFrames     ─> compute-service /embed-clip  ─> patch frames
              └─ transcribeAndEmbed ─> compute-service /transcribe
                                       + /embed-text                ─> patch audioChunks
```

Every database write from an action is a `ctx.run*` hop into a mutation that restates
its own argument schema. The two scheduled actions run after `ingestVideo` returns,
and nothing tells it whether they succeeded.

## Setup

```bash
npm install
npx convex dev          # generates convex/_generated/ and deploys
npx convex env set COMPUTE_SERVICE_URL http://localhost:9000
```

Also required: `../compute-service/` running on port 9000.

Nothing in `convex/` typechecks until `npx convex dev` or `npx convex codegen` has
written `convex/_generated/`, which is not committed.

## Endpoints

| Contract endpoint | Convex |
|---|---|
| `POST /videos` | `ingest.ingestVideo` |
| `GET /videos` | `videos.listVideos` |
| `POST /search/frames` | `searchFrames.searchFrames` |
| `POST /search/transcripts` | `searchTranscripts.searchTranscripts` |
| `POST /agent/query` | `agent.queryAgent` |

## Known limits, stated rather than hidden

- `vectorSearch` returns ids and scores only. Recovering the frame url and the video
  title takes one extra query per hit, so a 10-result search is 11 round trips.
- `vectorSearch` caps at 256 results per call.
- `embedding` and `imageStorageId` have to be `v.optional()` because a later action
  fills them in. A row is therefore valid while it is still unsearchable.
- `videos.status` is written before the embedding work runs. `listVideos` derives the
  real one by counting rows that still have no embedding.
- Adding a field later means a schema edit and a migration action that walks the table.
