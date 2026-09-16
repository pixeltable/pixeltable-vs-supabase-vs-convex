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
account, all three were executed end to end, and all three pass the same 10-test suite
against the same fixtures. Every number here is produced by `harness/run_comparison.py`
reading the source; `n/a` means a metric does not apply to that platform, never that it
scored zero.

| | Pixeltable | Supabase | Convex |
|---|---|---|---|
| App code you maintain | **129** | 254 | 383 |
| Plus the shared compute service | **0** | 252 | 252 |
| **Total** | **129** | **506** | **635** |
| Files you open to read the backend | **1** | 5 | 7 |
| Schema objects | 2 tables, 2 views | 5 tables, 1 view, 3 FKs | 5 tables |
| Vector indexes | 2 | 2 | 2 |
| Orchestration hops | **3** | 12 | 9 |
| HTTP routes written by hand | 1 | 1 | 5 |

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
```

Read the whole thing: [`pixeltable/app.py`](pixeltable/app.py). 129 lines, the entire
backend, HTTP included.

## What the difference actually is

Not the line count. After the rewrite the gap is about 2x, and lines are the least
durable thing in the table. What survives:

**Media processing has to live somewhere else.** Neither Deno nor the Convex runtime can
execute ffmpeg, so both need `compute-service/`. Three of its seven endpoints are ffmpeg
and have no hosted-API substitute, so this does not go away if you switch to OpenAI for
embeddings. Everything downstream follows from it: the second service, most of the
orchestration hops, and base64 on the wire.

**Adding a column to live data.** Adding `scene_count` and `still` to a populated catalog
was one edit and `pxt schema update`: `videos` and `frames` backfilled, `chunks` reported
`unchanged` and re-ran no transcription. On the other two it is a migration plus a
backfill script. This costs nothing at 45 rows and decides the question at 45 million.

**Processing fires for any writer.** A row inserted into a Pixeltable table by anything
at all gets processed, because the pipeline is the schema. On Supabase or Convex the
processing lives in the ingest path, so a row written by another client, a backfill, or a
`psql` session is not processed. Getting that behaviour back means database triggers on
Supabase or a scheduled action on Convex, and a webhook or a job per row.

**Retrieval knows its own model.** `similarity(string=q)` asks the index. The other two
embed the query themselves and nothing checks it came from the model that filled the
column; the dimension is the only guard, and 384 equals 384.

**Errors are per cell.** A Pixeltable cell holds a value or its own `errormsg`, queryable
with `pxt errors`. Elsewhere a failed step leaves a NULL and finding out which rows are
affected is a query you write.

## Run it

Everything runs locally on CPU. No API key, for any of the three.

```bash
pip install gTTS && python fixtures/videos/generate.py
```

### Pixeltable

Install Pixeltable from source for now: the released 0.7.7 cannot build this app's
embedding index ([PXT-1419](https://pixeltable.atlassian.net/browse/PXT-1419), fixed on
main). See [pixeltable/README.md](pixeltable/README.md).

```bash
cd pixeltable && pip install -e . && pxt init
pxt schema update app.py media
pxt service update app.py media
URL=$(pxt service list | awk '/^media/{print $2}')
```

### Supabase and Convex

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

## Reading the rest

- [docs/TRADEOFFS.md](docs/TRADEOFFS.md): even swaps, and which stack wins when.
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
