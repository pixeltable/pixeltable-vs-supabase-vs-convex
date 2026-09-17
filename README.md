# Pixeltable vs Supabase vs Convex

[![CI](https://github.com/pixeltable/pixeltable-vs-supabase-vs-convex/actions/workflows/ci.yml/badge.svg)](https://github.com/pixeltable/pixeltable-vs-supabase-vs-convex/actions/workflows/ci.yml)

Three implementations of one application: a video intelligence pipeline that extracts
frames, transcribes speech, embeds both, detects scenes, and answers questions about what
it saw and heard.

Most stacks glue a blob store, a warehouse, a vector database, an orchestrator and custom
endpoints together, and you pay for the joints. [Pixeltable](https://pixeltable.com) is
the database, the orchestration and the serving: tables, computed columns, indexes and
endpoints in one Python file. Insert a row. Transforms run.

Pixeltable also sponsors this repo, which is why the methodology below is written to be
attacked, and why every implementation here is held to its own vendor's checker.

Same contract, same fixtures, same models. All three run locally with no API key and no
account, and all three were executed end to end: 10 contract tests each, then 20
differential tests comparing them against each other and 32 resilience tests running
against all three at once. Every number here is produced by `harness/run_comparison.py`
reading the source; `n/a` means a metric does not apply to that platform, never that it
scored zero.

| | Pixeltable | Supabase | Convex |
|---|---|---|---|
| App code you maintain | **129** | 294 | 429 |
| Plus the shared compute service | **0** | 252 | 252 |
| **Total** | **129** | **546** | **681** |
| Files you open to read the backend | **1** | 7 | 7 |
| Schema objects | 2 tables, 2 views | 5 tables, 1 view, 3 FKs | 5 tables |
| Vector indexes | 2 | 2 | 2 |
| Orchestration hops | **3** | 12 | 9 |
| HTTP routes written by hand | 1 | 1 | 5 |

Those are properties of the code. Speed is not one of them, and on speed Pixeltable
loses: over 20 videos and 10 minutes of footage it ingests at 9.04x realtime against
Supabase's 11.64x, and answers a frame search in 39ms against Supabase's 26ms. Measured,
with the method, the library versions and the caveats, in [docs/SCALE.md](docs/SCALE.md).

**Read [docs/TRADEOFFS.md](docs/TRADEOFFS.md) before the rest.** It says which stack wins
under which conditions, using even swaps, and it concedes the cases where Pixeltable
loses. The short version: this app is media-heavy, which suits Pixeltable; if you need
realtime, row-level security or a managed database, the answer changes.

## Every implementation is held to its vendor's own checker

"Idiomatic" is a command here, not an opinion. CI runs each vendor's own tooling, so you
can re-run the claim:

| | Checker | What it gates |
|---|---|---|
| Supabase | `deno lint`, `supabase db advisors --local` | Edge Function style, and no security or performance errors on a live database |
| Convex | `@convex-dev/eslint-plugin`, `tsc --noEmit` | Their own best-practice rules against real generated code |
| Pixeltable | `ruff` | Generic Python. Pixeltable ships no conformance checker, so it has the weakest automated proof of the three. |

Supabase follows [develop few large functions, rather than many small
ones](https://supabase.com/docs/guides/functions/development-tips), the documented
handler shape, `npm:` and `jsr:` specifiers with pinned versions, RLS on every table, and
a locked `search_path`. Convex follows [most logic should be plain TypeScript
functions](https://docs.convex.dev/understanding/best-practices/), batched writes,
explicit table ids and bounded reads.

## The whole Pixeltable pipeline

Three class bodies, and the agent is a fourth. Insert a video and all of it runs.

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
```

Read the whole thing: [`pixeltable/app.py`](pixeltable/app.py). 129 lines, the entire
backend, HTTP included.

## What the difference actually is

Not the line count. Lines are the least durable thing in the table. What survives:

**Media processing has to live somewhere else.** Neither Deno nor the Convex runtime can
execute ffmpeg, so both need `compute-service/`. Three of its seven endpoints are ffmpeg
and have no hosted-API substitute, so this does not go away if you switch to OpenAI for
embeddings. Everything downstream follows from it: the second service, most of the
orchestration hops, and base64 on the wire.

**Adding a column to live data.** One edit and `pxt schema update`: the table that gained
the column backfills, and every table that did not need recomputing prints `unchanged`.
On a populated catalog that is 1.4 seconds, and no transcription re-runs. Removing the
column again is refused as `DESTRUCTIVE` until you pass a flag. On the other two it is a
migration plus a backfill script.

Measured on a populated catalog in [docs/EVOLVE.md](docs/EVOLVE.md), against what the
other two must write for the same feature: **1 line in 1 file, against 24 and 53**.
Supabase is the fastest of the three in wall time, and at two dozen rows that is noise.
The claim past this corpus is structural, not measured: what backfills incrementally stays
proportional to the rows that changed, and what re-runs a script does not.

**Processing fires for any writer.** A row inserted into a Pixeltable table by anything
at all gets processed, because the pipeline is the schema. On Supabase or Convex the
processing lives in the ingest path, so a row written by another client, a backfill, or a
`psql` session is not processed. Getting that behaviour back means database triggers on
Supabase or a scheduled action on Convex, and a webhook or a job per row.

**Retrieval knows its own model.** `similarity(string=q)` asks the index. The other two
embed the query themselves and nothing checks it came from the model that filled the
column; the dimension is the only guard, and 384 equals 384.

**Errors are per cell.** A Pixeltable cell holds a value or its own `errormsg` and
`errortype`, selectable like any other column:
`Videos.select(err=Videos.audio.errormsg)`. The `pxt errors` CLI view wants a primary
key, which this schema does not declare, so here the column is the way in. Elsewhere a
failed step leaves a NULL and finding out which rows are affected is a query you write.

**Lineage is in the catalog, not in a diagram somebody maintains.** Every computed column
carries the expression that produced it, and a view carries its base's:

```
$ pxt columns media/frames
/media/frames  still        Image[(320, 180)]  computed  resize(frame, [320, 180])
/media/frames  audio        Audio | None       computed  extract_audio(video, format='mp3')
/media/frames  scene_count  Int                computed  count_items(scenes)

$ pxt idxs media/frames
/media/frames  idx0  embedding  frame  cosine  clip(frame, model_id='openai/clip-vit-base-patch32')
```

`pxt dashboard` draws the same thing: a local UI, no deploy and no account, with a column
lineage graph, a table lineage graph, per-version history and a data browser that renders
the frames. Supabase Studio and the Convex dashboard are both good and both ship in this
benchmark; neither knows what produced a column, because on those stacks nothing recorded
it.

**A `Json` column is queryable, not a blob.** Paths, negative indices, slices and wildcards
are expressions, so `scenes` needs no parsing step:

```python
Videos.select(first=Videos.scenes[0].start_time, every=Videos.scenes['*'].start_time)
```

Seven iterators ship (`FrameIterator`, `AudioSplitter`, `VideoSplitter`, `DocumentSplitter`,
`StringSplitter`, `TileIterator`, `ComponentIterator`); this app uses two.

**Model calls are scheduled, not looped.** Eighteen provider modules declare a resource
pool, and the scheduler reads the rate limits the provider reports, stays under them, and
retries with exponential backoff. Configuration is per provider: `openai.rate_limits`,
`anthropic.api_key`, `gemini.rate_limits`, `openai.max_connections`. **This benchmark does
not exercise any of it**, because every model here is local. Swap one line to a hosted
model and the concurrency, the rate limiting and the retries arrive with it; on the other
two they are yours to write.

**A failed ingest must not become a listed video.** A zero-byte file, a truncated file,
random bytes with an `.mp4` extension, a path that does not exist: all three reject all
four and none of them appears in `GET /videos`. Pixeltable rejects the insert outright, so
no row exists and the error is typed (`INVALID_DATA_FORMAT: Not a valid video`). Supabase
and Convex write the row first to get an id, so the failure leaves a `status='error'` row
behind and answers a bare 500; each filters that row out of its list, which is one line in
a view and one in a query, and both lines exist because this test asked for them.
`harness/test_recovery.py` holds all three to it.

**Rejecting a bad request is free on one and hand-written on two.** `add_query_route`
derives the route signature from the query function, so a missing `query` or a negative
`limit` is a 422 before any handler runs. Deno has no request-validation layer, and
Convex's argument validators sit inside the function, where a failure is a 500 rather
than a 400: 28 lines in `supabase-app` and 46 in `convex-app` exist to turn a client's
mistake back into a client error. `harness/test_resilience.py` holds all three to it.

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

Into an environment that already holds `sentence-transformers` older than 5.4, add
`pip install -U 'sentence-transformers>=5.4'`. See
[pixeltable/README.md](pixeltable/README.md).

### Supabase and Convex

Convex picks its own ports. `npx convex dev` writes `CONVEX_SITE_URL` into
`convex-app/.env.local`, and that is the base URL for every command below; the `3211` in
the examples is only what it chose here.

Both need `compute-service/` first:

```bash
cd compute-service && pip install -e . && uvicorn app:app --port 9000
```

Then [`supabase-app/README.md`](supabase-app/README.md) or
[`convex-app/README.md`](convex-app/README.md).

### Measure and test

Measure lines of code and architecture metrics:

```bash
python harness/run_comparison.py
```

Seed fixture videos into any running platform:

```bash
# Against Pixeltable (auto-discovers the running service, or pass --base-url):
python harness/seed.py --impl pixeltable

# Against Supabase or Convex:
python harness/seed.py --impl supabase --base-url http://127.0.0.1:54321
python harness/seed.py --impl convex --base-url http://127.0.0.1:3211
```

Run contract and relevance equivalence tests against one live implementation:

```bash
# Against Pixeltable (auto-discovers the running service, or pass --base-url):
pytest harness/test_equivalence.py

# Against Supabase or Convex:
pytest harness/test_equivalence.py --impl supabase --base-url http://127.0.0.1:54321
pytest harness/test_equivalence.py --impl convex --base-url http://127.0.0.1:3211
```

Run the suite that writes to the corpus. It ingests broken files and runs concurrent
ingests, and none of the three has a delete route, so re-seed afterwards:

```bash
pytest harness/test_recovery.py --destructive \
  --compare pixeltable --compare supabase=http://127.0.0.1:54321 --compare convex=http://127.0.0.1:3211
```

Run differential tests comparing implementations against each other:

```bash
# Auto-discovers Pixeltable, or pass --compare pixeltable=URL:
pytest harness/test_differential.py \
  --compare pixeltable \
  --compare supabase=http://127.0.0.1:54321 \
  --compare convex=http://127.0.0.1:3211
```

Or measure and test in one step:

```bash
python harness/run_comparison.py --test --impl pixeltable
```

Measure ingest throughput and search latency over the 20-video tier:

```bash
python fixtures/videos/generate.py --tier large
python harness/benchmark.py --impl pixeltable --tier large
```

## Reading the rest

- [docs/TRADEOFFS.md](docs/TRADEOFFS.md): even swaps, and which stack wins when.
- [docs/SCALE.md](docs/SCALE.md): ingest throughput and search latency over 20 videos,
  where Pixeltable is the slowest of the three.
- [docs/EVOLVE.md](docs/EVOLVE.md): adding a column to live data, run on all three, with
  the code each one required and the costs the clock does not show.
- [docs/METHODOLOGY.md](docs/METHODOLOGY.md): what is measured, what is a judgment call,
  which implementations were executed, and where this is favourable to Pixeltable.
- [docs/JOURNEY.md](docs/JOURNEY.md): the same ten steps on all three, with the code.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). If you work on Supabase or Convex and think your
platform is misrepresented here, that is the most useful issue you could open, and the
history of this repo shows we act on it.

## Pixeltable

- [Quickstart](https://docs.pixeltable.com/overview/quick-start) and
  [docs](https://docs.pixeltable.com/)
- [Why Pixeltable](https://docs.pixeltable.com/overview/pixeltable) and
  [how it works](https://docs.pixeltable.com/overview/how-it-works)
- [Starter kit](https://github.com/pixeltable/pixeltable-starter-kit): `uvx pixeltable-new myapp`.
  Its `video-search` app is this same pipeline, maintained by the people who build Pixeltable.
- [Migrating from another stack](https://docs.pixeltable.com/howto/coming-from)
- [Discord](https://discord.gg/QPyqFYx2UN)

## License

Apache 2.0
