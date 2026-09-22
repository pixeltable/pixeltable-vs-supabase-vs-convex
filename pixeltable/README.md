# Pixeltable: video intelligence pipeline

One file. [`app.py`](app.py) holds the schema, the pipeline, the agent, and the HTTP
API. Everything runs locally: CLIP for frames, sentence-transformers for
transcripts, Whisper for speech, Qwen2.5-1.5B for the agent. No API key.

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
pxt history media/videos
pxt columns media/frames     # every column beside the expression that computes it
pxt idxs media/frames        # index, metric, and the model expression behind it
pxt dashboard                # local UI: lineage graphs, history, a data browser
```

A failed cell keeps its error beside the value:

```python
Chunks.select(Chunks.title, err=Chunks.transcript.errormsg).where(Chunks.transcript.errormsg != None)
```

`pxt errors` wants a primary key this schema does not declare; the column is the way
in.

## One error worth recognising

Into an environment holding `sentence-transformers` older than 5.4, `pxt schema
check` fails with `'SentenceTransformer' object has no attribute
'get_embedding_dimension'` rather than a version error.
`pip install -U 'sentence-transformers>=5.4'` fixes it; tracked as
[PXT-1421](https://pixeltable.atlassian.net/browse/PXT-1421) and
[PXT-1422](https://pixeltable.atlassian.net/browse/PXT-1422).

## Two things that look odd, and why

`/agent/query` is the one route written by hand: a route is built before models bind
to tables, and `Conversations.visual` / `.spoken` are queries over other models, so
declaring it fails with `cannot be serialized; bind it to a table first`. The same
limit means a `@pxt.query` column can only be declared at table creation.

`scene_count` is a one-line UDF because `pxtf.json.len()` raises `AssertionError`.

## Swapping providers

Each model is one expression:

```python
SEMANTIC = openai.embeddings.using(model='text-embedding-3-small')
```

The pipeline does not change; existing rows keep their vectors until the column is
renamed and recomputed.
