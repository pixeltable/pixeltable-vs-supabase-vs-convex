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
pxt errors media/chunks --col transcript
pxt history media/videos
```

## Known limit on the released package

Building the transcript embedding index needs a Pixeltable build newer than the current
release. Released 0.7.7 resolves the index dimension by calling
`SentenceTransformer.get_embedding_dimension()`, which no sentence-transformers version
defines, so `pxt schema check` fails before any table is created:

```
pxt: 422 error loading app.py: 'SentenceTransformer' object has no attribute 'get_embedding_dimension'
```

It is fixed on Pixeltable main and tracked as PXT-1419. Until that ships, install
Pixeltable from source. Everything else here works on the release.

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
