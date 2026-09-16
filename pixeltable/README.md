# Pixeltable: video intelligence pipeline

One file. [`app.py`](app.py) holds the schema, the pipeline, the agent, and the HTTP
API, and there is nothing else in this directory but a `pyproject.toml`.

Everything runs locally: CLIP for frames, sentence-transformers for transcripts,
Whisper for speech, Qwen2.5-1.5B for the agent. No API key.

## Run it

```bash
pip install -e .
pxt init
pxt schema update app.py media      # creates the tables; does not start HTTP
pxt service update app.py media     # starts HTTP; does not create tables
pxt service list                    # prints the assigned port
```

Ingest and search:

```bash
URL=$(pxt service list | awk '/^media/{print $2}')
curl -X POST $URL/videos -H 'Content-Type: application/json' \
  -d '{"video":"'$PWD'/../fixtures/videos/whiteboard_algorithms.mp4","title":"whiteboard_algorithms.mp4"}'
curl -X POST $URL/search/transcripts -H 'Content-Type: application/json' \
  -d '{"query":"quicksort pivot partition","limit":3}'
```

`POST /videos` returns a `job_url`; poll it until `status` is `done`.

## Endpoints

| Endpoint | Method | Declared as |
|---|---|---|
| `/videos` | POST | `add_insert_route(Videos, background=True)` |
| `/videos` | GET | `add_query_route(query=list_videos)` |
| `/search/frames` | POST | `add_query_route(query=search_frames)` |
| `/search/transcripts` | POST | `add_query_route(query=search_transcripts)` |
| `/agent/query` | POST | hand-written, see below |

## Inspect it

```bash
pxt ls -l media
pxt describe media/frames
pxt history media/videos
```

A failed cell keeps its own error beside the value, so you read it as a column:

```python
Chunks.select(Chunks.title, err=Chunks.transcript.errormsg).where(Chunks.transcript.errormsg != None)
```

`pxt errors` builds a view keyed by primary key and this schema declares none, so it
answers `no primary key defined`. The column is the way in here.

## One error worth recognising

`pip install -e .` into a fresh environment works: it resolves `pixeltable[serve]` 0.7.8
and `sentence-transformers` 6.0.1, and `pxt schema update` creates all four tables and
both embedding indexes.

Into an environment that already holds `sentence-transformers` older than 5.4, the same
command leaves the old one in place and `pxt schema check` fails before any table exists:

```
pxt: 422 error loading app.py: 'SentenceTransformer' object has no attribute 'get_embedding_dimension'
```

`pip install -U 'sentence-transformers>=5.4'` fixes it. The message is misleading rather
than the problem: Pixeltable needs `sentence-transformers` 5.4 or newer, and the code path
that resolves an index's dimension calls the new method without the version check that
every other path performs, so a version mismatch surfaces as a missing attribute instead
of the readable error Pixeltable already knows how to print. Tracked as PXT-1419.

## Two things that look odd, and why

`/agent/query` is the one route written by hand. `add_insert_route` resolves its target
model eagerly and cannot target a model whose columns call a `@pxt.query`, which the
`Conversations` table does.

`scene_count` is a one-line UDF rather than `pxtf.json.len()`.

## Swapping providers

Each model is one expression. To go hosted, change the line:

```python
SEMANTIC = openai.embeddings.using(model='text-embedding-3-small')
answer = openai.chat_completions(messages=..., model='gpt-4o-mini',
                                 tools=pxt.tools(search_frames, search_transcripts))
```

The pipeline does not change, and existing rows keep the vectors they have until you
rename the column and let it recompute.
