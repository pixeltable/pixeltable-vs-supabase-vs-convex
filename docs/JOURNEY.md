# The same ten steps, three ways

Every snippet below comes from this repo. Some are shortened with `...` or reflowed to
fit the page; none are invented, and none show code that is not there.

---

## 1. Install

**Pixeltable.** One package, one command, and the directory is a project.

```bash
pip install 'pixeltable[serve]'
pxt init
```

**Supabase.** Docker and 12 containers on this machine (db, kong, auth, rest,
realtime, storage, studio, pg_meta, edge_runtime, analytics, vector, inbucket), plus a
second Python service you build and operate yourself because Deno has no subprocess
and therefore no ffmpeg.

```bash
npm install && supabase start
cd ../compute-service && pip install -e . && uvicorn app:app --port 9000
```

**Convex.** An authenticated deployment before the code typechecks, plus the same
compute service.

```bash
npm install && npx convex dev     # needs a Convex account
```

`convex/_generated/` is not committed and cannot be produced offline. Until it exists,
`tsc --noEmit` reports an error on every file.

---

## 2. Schema

**Pixeltable.** One table and two views, in Python, in the same file as everything else.

```python
class Videos(TableModel, name='videos'):
    video: pxt.Video
    title: pxt.String

class Frames(TableModel, name='frames', base=Videos,
             iterator=frame_iterator(Videos.video, fps=1.0)): ...

class Chunks(TableModel, name='chunks', base=Videos,
             iterator=audio_splitter(Videos.audio, duration=10.0)): ...
```

A view is derived, so `Frames.title` is the base video's title. No join, no foreign key.

**Supabase.** Four tables, three foreign keys, two HNSW indexes, in SQL.

```sql
CREATE TABLE IF NOT EXISTS frames (
    id BIGSERIAL PRIMARY KEY,
    video_id BIGINT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    frame_idx INT NOT NULL,
    frame_url TEXT NOT NULL,
    embedding vector(512)
);
CREATE INDEX IF NOT EXISTS frames_embedding_idx ON frames USING hnsw (embedding vector_cosine_ops);
```

**Convex.** Four tables, and the fields the pipeline fills in later have to be optional,
so a row is valid while it is still unsearchable.

```ts
frames: defineTable({
  videoId: v.id("videos"),
  imageStorageId: v.optional(v.id("_storage")),
  embedding: v.optional(v.array(v.float64())),
}).index("by_video", ["videoId"])
  .vectorIndex("by_embedding", { vectorField: "embedding", dimensions: 512, filterFields: ["videoId"] }),
```

---

## 3. Ingest

**Pixeltable.** One row.

```python
Videos.insert([{'video': 'lecture.mp4', 'title': 'CS101'}])
```

**Supabase.** 91 lines: three calls to the compute service, a Storage upload and a row
insert per frame, chunk arithmetic, scene rows, and a try/catch that flips `status`.

```ts
const bytes = Uint8Array.from(atob(frames.frames[i]), (c) => c.charCodeAt(0));
const { error: uploadErr } = await supabase.storage
  .from("frames").upload(path, bytes, { contentType: "image/jpeg", upsert: true });
if (uploadErr) throw new Error(`frame upload failed: ${uploadErr.message}`);
const frameUrl = supabase.storage.from("frames").getPublicUrl(path).data.publicUrl;
const { error: rowErr } = await supabase
  .from("frames").insert({ video_id: videoId, frame_idx: i, frame_url: frameUrl });
if (rowErr) throw new Error(`frame row failed: ${rowErr.message}`);
```

**Convex.** 75 lines, the same shape, with every write going through a mutation hop.

```ts
const blob = new Blob([decodeBase64(frames.frames[i])], { type: "image/jpeg" });
const imageStorageId = await ctx.storage.store(blob);
await ctx.runMutation(internal.videos.insertFrame, { videoId, frameIdx: i, imageStorageId });
```

---

## 4. Process

**Pixeltable.** The processing is the schema. There is no separate step.

```python
audio = extract_audio(video, format='mp3')
scenes = video.scene_detect_content(threshold=8.0)
transcript = transcribe(audio_segment, model='base.en').text.astype(pxt.String)
```

**Supabase.** Two database triggers, two webhook handlers, and one HTTP round trip per
row. A 15 second video at 1 FPS fires 15 `process-frames` webhooks.

```sql
CREATE TRIGGER frames_embed_trigger AFTER INSERT ON frames
    FOR EACH ROW EXECUTE FUNCTION on_frame_inserted();
```

**Convex.** Two scheduled actions, fired after ingest returns.

```ts
await ctx.scheduler.runAfter(0, internal.processFrames.embedAllFrames, { videoId });
await ctx.scheduler.runAfter(0, internal.processAudio.transcribeAndEmbed, { videoId });
```

Neither retries. A failed invocation leaves a NULL embedding and the row drops out of
search with nothing recording that it did.

---

## 5. Embed

**Pixeltable.** One line inside the view. The index knows its own model.

```python
__indexes__ = [pxt.EmbeddingIndex(frame, embedding=VISUAL)]
```

**Supabase and Convex.** The frame has to be read back out of storage, base64 encoded,
posted to the compute service, and patched into the row it came from.

```ts
const blob = await ctx.storage.get(frame.imageStorageId);
const imageB64 = encodeBase64(new Uint8Array(await blob.arrayBuffer()));
const resp = await fetch(`${COMPUTE_SERVICE_URL}/embed-clip`, { ... });
await ctx.runMutation(internal.processFrames.setFrameEmbedding, { frameId: frame._id, embedding: ... });
```

---

## 6. Search

**Pixeltable.** An expression. The view supplies the title.

```python
sim = Frames.frame.similarity(string=query)
Frames.order_by(sim, asc=False).limit(limit).select(
    frame_url=Frames.still, frame_idx=Frames.pos, video_title=Frames.title, similarity=sim)
```

**Supabase.** Embed the query yourself with the model you hope matches the index, then
call a SQL function that joins back to `videos`.

```sql
SELECT f.frame_url, v.title AS video_title, 1 - (f.embedding <=> query_embedding) AS similarity
FROM frames f JOIN videos v ON f.video_id = v.id
WHERE f.embedding IS NOT NULL
ORDER BY f.embedding <=> query_embedding LIMIT match_count;
```

**Convex.** `vectorSearch` returns ids and scores only, so each hit costs another query.

```ts
const hits = await ctx.vectorSearch("frames", "by_embedding", {
  vector: embedded.embeddings[0], limit: Math.min(args.limit ?? 10, 256),
});
for (const hit of hits) {
  const detail = await ctx.runQuery(internal.searchFrames.getFrameWithVideo, { frameId: hit._id });
}
```

Ten results is eleven round trips.

---

## 7. The agent

**Pixeltable.** A table. Retrieval is a column, so the evidence is stored with the answer.

```python
class Conversations(TableModel, name='conversations'):
    request_id: pxt.String   # only so the hand-written route can find its own row
    question: pxt.String
    visual = frames_seen(question, limit=4)
    spoken = search_transcripts(question, limit=4)
    answer = create_chat_completion(messages=[...], repo_id='Qwen/Qwen2.5-1.5B-Instruct-GGUF')
```

**Supabase and Convex.** Both searches re-invoked, the prompt assembled by hand, the
chat call sent to the compute service, and nothing persisted. The next request starts
from nothing, and the evidence behind an answer is gone once the response is written.

---

## 8. Serve

**Pixeltable.** Routes are declared next to the queries they run.

```python
api.add_query_route(path='/search/frames', query=search_frames, method='post')
```

```bash
pxt service update app.py media
```

**Supabase.** Seven `Deno.serve` handlers, deployed one at a time, each parsing and
re-serialising JSON.

**Convex.** Five `http.route` blocks that unwrap a body and re-wrap a result.

---

## 9. Evolve

This is the one that compounds.

**Pixeltable.** Adding `scene_count` and `still` to a populated catalog, observed in
this repo:

```
$ pxt schema update app.py media -f
updated   media/videos
updated   media/frames
unchanged media/chunks
```

Existing rows kept. Only the new columns computed. `chunks` was not touched, so no
transcript was re-run and no Whisper pass was repeated.

Not free, though: `still` changed the return type of `search_frames`, which changed the
inferred type of the `Conversations` column that calls it. That is a `FATAL` schema
difference, so that one table had to be dropped and recreated. The base table and both
views backfilled in place.

**Supabase.** A migration, a backfill script, and a decision about what to do with the
rows already in the table.

**Convex.** A schema edit, plus a migration action that walks the table in batches,
plus `v.optional()` on the new field until the walk finishes.

---

## 10. Inspect and recover

**Pixeltable.** Per-cell errors, schema history, and a way back.

```bash
pxt errors media/chunks --col transcript
pxt describe media/frames
pxt history media/videos
pxt revert media/videos
```

**Supabase and Convex.** There is no per-cell error. A failed step leaves a NULL, and
finding out which rows are affected means writing the query yourself:

```sql
SELECT CASE WHEN EXISTS (SELECT 1 FROM frames WHERE video_id = v_id AND embedding IS NULL)
       THEN 'processing' ELSE 'ready' END;
```

Neither versions data. There is nothing to revert to.
