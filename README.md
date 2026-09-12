# Pixeltable vs Supabase vs Convex

Three implementations of one application: a video intelligence pipeline that extracts
frames, transcribes speech, embeds both, detects scenes, and answers questions about
what it saw and heard.

Same contract, same fixtures, same models, all running locally with no API key. Every
number below is produced by `harness/run_comparison.py` reading the source, not typed
in by hand. `Services to operate` is the one exception: it is a judgment call, and it
lives with the other judgment calls in `CLASSIFIED` in `harness/metrics.py`.

| | **Pixeltable** | Supabase | Convex |
|---|---|---|---|
| App LOC | **128** | 473 | 458 |
| App files | **1** | 11 | 9 |
| Plus the shared compute service | **0** | 258 | 258 |
| **Total you maintain** | **128** | **731** | **716** |
| Tables / views | 2 / 2 | 5 / 0 | 4 / 0 |
| Foreign keys | 0 | 3 | 0 |
| Database triggers | 0 | 2 | 0 |
| Orchestration hops | **0** | 19 | 17 |
| HTTP routes written by hand | 1 | 7 | 5 |
| Services to operate (hand-classified) | **1** | 2 | 2 |
| Environment variables | **0** | 4 | 2 |

`compute-service/` is a FastAPI service providing ffmpeg, Whisper, CLIP, sentence
embeddings, and a local chat model over HTTP. Supabase and Convex both need it.
Supabase Edge Functions run on Deno with no subprocess, so ffmpeg is out of reach
entirely. Convex can run a Node action with `"use node"`, but it still has no ffmpeg
binary and no place to keep model weights, so in practice the work leaves the platform
either way. Pixeltable does not need the service: its seven operations are seven
expressions in `pixeltable/app.py` (`frame_iterator`, `extract_audio`,
`audio_splitter` plus `transcribe`, `clip`, `sentence_transformer`,
`scene_detect_content`, `create_chat_completion`).

## The whole Pixeltable pipeline

Four class bodies. Insert a video and all of it runs.

```python
class Videos(TableModel, name='videos'):
    video: pxt.Video
    title: pxt.String
    audio = extract_audio(video, format='mp3')
    duration_sec = pxtf.video.get_duration(video)
    scenes = video.scene_detect_content(threshold=8.0)

class Frames(TableModel, name='frames', base=Videos,
             iterator=frame_iterator(Videos.video, fps=1.0)):
    still = pxtf.image.resize(frame, (320, 180))
    __indexes__ = [pxt.EmbeddingIndex(frame, embedding=VISUAL)]

class Chunks(TableModel, name='chunks', base=Videos,
             iterator=audio_splitter(Videos.audio, duration=10.0)):
    transcript = transcribe(audio_segment, model='base.en').text.astype(pxt.String)
    __indexes__ = [pxt.EmbeddingIndex(transcript, embedding=SEMANTIC)]
```

Search is an expression, not a service call:

```python
sim = Frames.frame.similarity(string=query)
Frames.order_by(sim, asc=False).limit(limit).select(video_title=Frames.title, similarity=sim)
```

And the agent is a table. Insert a question, and retrieval and generation are columns,
so the evidence behind an answer is stored rather than thrown away with the prompt:

```python
class Conversations(TableModel, name='conversations'):
    request_id: pxt.String
    question: pxt.String
    visual = frames_seen(question, limit=4)
    spoken = search_transcripts(question, limit=4)
    answer = create_chat_completion(messages=[...], repo_id='Qwen/Qwen2.5-1.5B-Instruct-GGUF')
```

`request_id` is not part of the idea. It is there because one route in this file is
written by hand and has to find the row it just wrote; see
[the known limits](pixeltable/README.md#known-limits-stated-rather-than-hidden).

Read the whole thing: [`pixeltable/app.py`](pixeltable/app.py). It is 128 lines and it
is the entire backend, HTTP included.

## What the other two have to build

Every item below is something Supabase and Convex must write, operate, or work around,
and that has no counterpart in `app.py`.

**A second service.** `compute-service/` exists only because neither runtime can
execute ffmpeg, Whisper, or CLIP where the data is. It is 258 lines you deploy, scale,
and page for.

**Media on the wire, twice.** Supabase base64s every extracted frame out of the compute
service, decodes it, uploads it to Storage, then a webhook downloads it again and
re-encodes it to send it back for embedding. A 15 second video at 1 FPS does that 15
times. In Pixeltable the frame is a column; `still` is its stored derivative and the
router serves it as a URL.

**A status column that lies.** Both write `status` before any embedding exists, so both
need a second, derived answer: Supabase counts NULL embeddings in a SQL function,
Convex counts them in `listVideos`. Pixeltable has no status column. A cell holds a
value or holds its own `errormsg`, per row, queryable with `pxt errors`.

**Orchestration.** 19 hops in Supabase (edge function to Postgres to trigger to edge
function to compute service), 17 in Convex (`ctx.runMutation` / `ctx.runQuery` /
`scheduler.runAfter`, not counting its HTTP router). Nothing retries a failed one in either: the row keeps a NULL
embedding and drops out of search silently. Pixeltable has none, because the column
definition is the schedule.

**Embedding models kept in sync by hand.** Both must embed the query with the same
model that filled the column, and nothing enforces it. The only guard is the dimension,
and 384 equals 384. `similarity(string=q)` asks the index, which knows its own model.

**Joins for lineage.** `frames` and `audio_chunks` are separate tables with foreign
keys, so every search joins back to `videos` to recover a title. Convex's `vectorSearch`
returns ids and scores only, so a 10-result search is 11 round trips. A Pixeltable view
carries its base columns: `Frames.title` is just there.

**A migration to add a column.** Adding a derived field later means a migration, a
backfill script, and a re-run for both. In this repo, adding `scene_count` and `still`
to a populated catalog was one edit and `pxt schema update`: `videos` and `frames`
backfilled their new columns, existing rows were kept, and `chunks` reported
`unchanged` and re-ran no transcription. One caveat, since it is not free: `still`
changed the return type of a query, so the one table with a column calling that query
had to be dropped and recreated. Details in
[METHODOLOGY.md](docs/METHODOLOGY.md#where-pixeltable-came-off-worse).

## Run it

Everything runs locally on CPU. No API key, for any of the three.

```bash
pip install gTTS && python fixtures/videos/generate.py
```

### Pixeltable

```bash
cd pixeltable && pip install -e . && pxt init
pxt schema update app.py media
pxt service update app.py media
URL=$(pxt service list | awk '/^media/{print $2}')
```

Then ingest and ask:

```bash
curl -X POST $URL/videos -H 'Content-Type: application/json' \
  -d '{"video":"'$PWD'/../fixtures/videos/whiteboard_algorithms.mp4","title":"whiteboard_algorithms.mp4"}'
curl -X POST $URL/search/transcripts -H 'Content-Type: application/json' \
  -d '{"query":"quicksort pivot partition","limit":3}'
```

### Supabase and Convex

Both need `compute-service/` first:

```bash
cd compute-service && pip install -e . && uvicorn app:app --port 9000
```

Then follow [`supabase-app/README.md`](supabase-app/README.md) or
[`convex-app/README.md`](convex-app/README.md).

### Measure and test

```bash
python harness/run_comparison.py
python harness/run_comparison.py --test --impl pixeltable --base-url http://127.0.0.1:PORT
```

## Reading the rest

- [docs/METHODOLOGY.md](docs/METHODOLOGY.md): what is measured, what is a judgment
  call, which implementations were actually executed, and where this comparison is
  favourable to Pixeltable by construction.
- [docs/JOURNEY.md](docs/JOURNEY.md): the same ten steps on all three, with the code.
- [docs/SCORECARD.md](docs/SCORECARD.md): the numbers, regenerated from
  `docs/metrics.json`.

## Contributing

Change the contract and you change all three. Run `python harness/run_comparison.py`
afterwards so the docs and `docs/metrics.json` stay in step, and keep each
implementation idiomatic for its platform: the point is the contrast, not a
strawman.

## License

Apache 2.0
