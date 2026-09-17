# The same ten steps, three ways

Every snippet comes from this repo. Some are shortened with `...` or reflowed to fit;
none are invented, and none show code that is not there.

Supabase and Convex follow their vendors' own documented guidance, enforced in CI by
each vendor's checker. Where a step below names a cost, it is a cost the platform
imposes, not one this repo chose.

## Summary

Ratings are judgments, not measurements. All three implementations were executed
end to end: see [METHODOLOGY.md](METHODOLOGY.md).

| Step | Pixeltable | Supabase | Convex |
|---|---|---|---|
| 1. Install | Adequate: big Python deps | Weak: Docker, or managed | Strong: one command, no account |
| 2. Schema | Strong: 2 tables, 2 views | Adequate: 5 tables, 3 FKs | Adequate: optional-free schema |
| 3. Ingest | Strong: one insert | Adequate: 67-line function | Adequate: 61 lines plus mutations |
| 4. Process | Strong: it is the schema | Weak: lives in the ingest path | Weak: lives in the ingest path |
| 5. Embed | Strong: one line | Weak: second service | Weak: second service |
| 6. Search | Strong: an expression | Adequate: SQL function plus join | Adequate: vector search plus lookup |
| 7. Agent | Strong: retrieval is a column | Adequate: assembled by hand | Adequate: assembled by hand |
| 8. Serve | Strong: declared routes | Strong: one function, or PostgREST | Weak for REST, strong for reactive |
| 9. Evolve | Strong: incremental backfill | Weak: migration plus backfill | Weak: migration action |
| 10. Inspect | Strong: per-cell errors, lineage, revert | Adequate: PITR, branching | Adequate: snapshot export |

---

## 1. Install

**Pixeltable.** One package, one command, and the directory is a project. The package is
not small: it pulls `torch`, `transformers`, `openai-whisper`, `sentence-transformers`,
`scenedetect` and `llama-cpp-python`, which compiles.

```bash
pip install 'pixeltable[serve]'
pxt init
```

**Supabase.** Docker and 12 containers locally, or nothing at all if you use hosted.
Plus the compute service, because Deno has no subprocess and therefore no ffmpeg.

**Convex.** `npx convex dev` sets up an anonymous local backend with no account, writes
`convex/_generated/`, and serves HTTP actions. No Docker, no signup. This is the easiest
install of the three.

## 2. Schema

**Pixeltable.** Two tables and two views, in the same file as everything else. `Videos`
carries the pipeline, `Conversations` carries the agent, and the two views are derived
from `Videos`. A view carries its base's columns, so `Frames.title` is just there.

```python
class Frames(TableModel, name='frames', base=Videos,
             iterator=frame_iterator(Videos.video, fps=1.0)): ...
```

**Supabase.** Five tables, three foreign keys, two HNSW indexes, and one view.

```sql
CREATE INDEX IF NOT EXISTS frames_embedding_idx ON frames
    USING hnsw (embedding vector_cosine_ops);
```

**Convex.** Five tables and two vector indexes. Ingest writes complete rows, so no field
needs `v.optional()`:

```ts
  frames: defineTable({
    videoId: v.id("videos"),
    frameIdx: v.number(),
    imageStorageId: v.id("_storage"),
    embedding: v.array(v.float64()),
```

## 3. Ingest

**Pixeltable.** One row.

```python
Videos.insert([{'video': 'lecture.mp4', 'title': 'CS101'}])
```

**Supabase.** 67 lines in one function: extract, embed the batch, upload each frame,
one insert per table.

```ts
    const { frames } = await compute("/extract-frames", { video_url, fps: FRAME_FPS });
    const { embeddings } = await compute("/embed-clip", { images_b64: frames });
```

**Convex.** 61 lines of the same shape, plus 109 lines of mutations in `videos.ts`,
because an action cannot write to the database directly.

```ts
      await ctx.runMutation(internal.videos.insertFrames, { videoId, rows: frameRows });
```

## 4. Process

**Pixeltable.** The processing is the schema. There is no separate step.

```python
audio = extract_audio(video, format='mp3')
scenes = video.scene_detect_content(threshold=8.0)
```

**Supabase and Convex.** The processing lives inside the ingest path. That is the
idiomatic shape and it is fast, but it means a row that arrives any other way is not
processed: a backfill, a second client, a `psql` session. Getting that back means adding
database triggers on Supabase or a scheduled action on Convex, and paying for the
webhook or job per row.

This is the difference that does not show up in a line count. On Pixeltable the pipeline
belongs to the table, so it fires for every writer.

## 5. Embed

**Pixeltable.** One line inside the view. The index knows its own model.

```python
__indexes__ = [pxt.EmbeddingIndex(frame, embedding=VISUAL)]
```

**Supabase and Convex.** An HTTP call to a service you operate, because neither runtime
can run CLIP. Three of that service's seven endpoints are ffmpeg and stay even if you
move the models to a hosted API.

## 6. Search

**Pixeltable.** An expression. The view supplies the title.

```python
sim = Frames.frame.similarity(string=query)
```

**Supabase.** Embed the query yourself with the model you hope matches the index, then
call a SQL function that joins back to `videos`.

```sql
    FROM frames f
    JOIN videos v ON f.video_id = v.id
```

**Convex.** `vectorSearch` returns ids and scores, so the rows are fetched in a second
query. One, taking every id, not one per hit.

```ts
    const rows = await ctx.runQuery(internal.search.framesByIds, {
      ids: hits.map((h) => h._id),
```

Convex's own guidance is to avoid a `ctx.run*` per row, and their ESLint plugin enforces
it, so one batched query is both the idiomatic and the measured shape.

## 7. The agent

**Pixeltable.** A table. Retrieval is a column, so the evidence is stored with the answer
by the schema.

```python
class Conversations(TableModel, name='conversations'):
    request_id: pxt.String
    question: pxt.String
    visual = frames_seen(question, limit=4)
    spoken = search_transcripts(question, limit=4)
```

**Supabase and Convex.** Both persist the conversation too, because not doing so would be
a choice this benchmark imposed rather than a platform limit. The difference is that they
assemble and write it:

```ts
  const { error } = await supabase.from("conversations").insert({
    question,
    answer: chat.content,
```

## 8. Serve

**Pixeltable.** Routes are declared next to the queries they run.

```python
api.add_query_route(path='/search/frames', query=search_frames, method='post')
```

**Supabase.** One function routing five paths, per Supabase's guidance to develop few
large functions. Note that two of these five would not need to exist at all: PostgREST
already exposes every table, view and function over REST with no handler code.

**Convex.** Five `http.route` blocks, 90 lines that exist only because this contract is
REST. Convex's actual interface is a reactive client where the UI re-renders on write.

## 9. Evolve

This is the one that compounds.

**Pixeltable.** Adding one computed column to `Videos` on a populated catalog, timed at
1.4 seconds:

```
$ pxt schema update app.py media
updated   media/videos
unchanged media/frames
unchanged media/chunks
unchanged media/conversations
```

Existing rows kept, only the new column computed, no transcription re-run. Removing it
again is refused as `DESTRUCTIVE` until you pass a flag.

Not every column: one whose value is a `@pxt.query` cannot be added to a table that
already exists. See the footnote in [TRADEOFFS.md](TRADEOFFS.md).

**Supabase.** A migration, a backfill script, and a decision about the rows already
there. `ALTER TABLE ADD COLUMN` is instant; filling it is not. A generated column or a
view avoids the backfill when the value is derivable in SQL, which an embedding is not.

**Convex.** A schema edit plus a migration action that walks the table in batches, or
the `@convex-dev/migrations` component.

## 10. Inspect and recover

**Pixeltable.** Per-cell errors, schema history, lineage, and a way back.

```bash
pxt history media/videos
pxt revert media/videos --steps 3 -f
pxt columns media/frames     # each column beside the expression that computes it
pxt dashboard                # the same thing as a graph, locally, no deploy
```

```python
Chunks.select(Chunks.title, err=Chunks.transcript.errormsg).where(Chunks.transcript.errormsg != None)
```

`pxt errors` is the CLI view of the same thing and wants a primary key, which this schema
does not declare, so here the column is the way in.

**Supabase.** No per-cell error: a failed step leaves a NULL and finding the affected
rows is a query you write. Against that, Postgres gives you point-in-time recovery,
database branching and versioned migrations, which are coarser but cover more.

**Convex.** Same lack of per-cell state, with snapshot export and import, and a dashboard
with function logs and a data browser.

All three ship a local UI. Only one of them can draw what produced a column, because only
one of them recorded it.
