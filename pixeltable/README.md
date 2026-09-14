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

## Known limits, stated rather than hidden

Found while building this. The version each was observed on is named, because
"reproduces on the release" and "reproduces on my build" are different claims.

**One route is written by hand** (reproduced on released 0.7.7). `add_insert_route`
resolves its target model eagerly, so it fails on a model whose columns call a
`@pxt.query`. That is why `/agent/query` could not be declared. Minimal repro:

```python
class Docs(TableModel, name='docs'):
    body: pxt.String

@pxt.query
def find(q: str):
    return Docs.where(Docs.body == q).select(body=Docs.body).limit(3)

class Asks(TableModel, name='asks'):
    question: pxt.String
    hits = find(question)

api.add_insert_route(Asks, path='/ask', inputs=[Asks.question], outputs=[Asks.hits])
# pixeltable.exceptions.Error: A query over model `Docs` cannot be serialized;
# bind it to a table first.
```

**`pxtf.json.len()` raises an internal `AssertionError`** (reproduced on released
0.7.7), in a plain select as well as in a computed column. `scene_count` is a one-line
UDF instead. Minimal repro:

```python
t = pxt.create_table('d.t', {'blob': pxt.Json})
t.insert([{'blob': [1, 2, 3]}])
t.select(t.blob).collect()                    # fine
t.select(n=pxtf.json.len(t.blob)).collect()   # AssertionError: 0
```

**Changing a query's return shape is a FATAL schema difference** (released 0.7.7) for
any column that calls it, so that table has to be dropped rather than updated. Adding
the `still` column changed `search_frames`'s return type, which changed the inferred
type of `Conversations.visual`.

**After a destructive catalog reset, restart the service** (observed on 0.7.7.dev9).
`pxt service update` reports "up to date" and keeps serving stale table handles, which
then 500 with `TABLE_NOT_FOUND`. Run `pxt service stop media/api` first.

## Swapping providers

Each model is one expression. To go hosted, change the line:

```python
SEMANTIC = openai.embeddings.using(model='text-embedding-3-small')
answer = openai.chat_completions(messages=..., model='gpt-4o-mini',
                                 tools=pxt.tools(search_frames, search_transcripts))
```

The pipeline does not change, and existing rows keep the vectors they have until you
rename the column and let it recompute.
