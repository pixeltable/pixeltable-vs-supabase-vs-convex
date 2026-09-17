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
pxt columns media/frames     # every column beside the expression that computes it
pxt idxs media/frames        # index, metric, and the model expression behind it
pxt dashboard                # local UI: lineage graphs, history, a data browser
```

`pxt columns` is the lineage, in text:

```
/media/frames  still        Image[(320, 180)]  computed  resize(frame, [320, 180])
/media/frames  audio        Audio | None       computed  extract_audio(video, format='mp3')
/media/frames  scene_count  Int                computed  count_items(scenes)
```

`still` is the view's own column; `audio` and `scene_count` are inherited from `videos`,
and the expression comes with them.

A failed cell keeps its own error beside the value, so you read it as a column:

```python
Chunks.select(Chunks.title, err=Chunks.transcript.errormsg).where(Chunks.transcript.errormsg != None)
```

`pxt errors` builds a view keyed by primary key and this schema declares none, so it
answers `no primary key defined`. The column is the way in here.

## One error worth recognising

`pip install -e .` into a fresh environment works, and this app runs on the released
package with no patch of any kind.

Into an environment that already holds `sentence-transformers` older than 5.4, the same
command leaves the old one in place, and `pxt schema check` fails before any table exists:

```
pxt: 422 error loading app.py: 'SentenceTransformer' object has no attribute 'get_embedding_dimension'
```

`pip install -U 'sentence-transformers>=5.4'` fixes it, and the floor is declared in
`pyproject.toml` so a fresh resolve cannot land there. The message is the problem rather
than the requirement: Pixeltable does need 5.4 or newer, and says so clearly everywhere
except the one path that resolves an index's dimension, which calls the new method with no
version check. Tracked as [PXT-1421](https://pixeltable.atlassian.net/browse/PXT-1421),
with the missing dependency floor as
[PXT-1422](https://pixeltable.atlassian.net/browse/PXT-1422).

## Two things that look odd, and why

`/agent/query` is the one route written by hand. Declaring it instead fails to load with
`A query over model 'Frames' cannot be serialized; bind it to a table first`: a route is
built before models bind to tables, and `Conversations.visual` and `Conversations.spoken`
are queries over other models.

`scene_count` is a one-line UDF because `pxtf.json.len()` raises `AssertionError` when
it is evaluated.

A column whose value is a `@pxt.query` can only be declared when the table is created.
Adding one to a table that already exists answers `500 A query over model 'Frames' cannot
be serialized; bind it to a table first`, so `Conversations` is the shape it is from the
start. Ordinary computed columns have no such limit and backfill in place.

## Swapping providers

Each model is one expression. To go hosted, change the line:

```python
SEMANTIC = openai.embeddings.using(model='text-embedding-3-small')
answer = openai.chat_completions(messages=..., model='gpt-4o-mini',
                                 tools=pxt.tools(search_frames, search_transcripts))
```

The pipeline does not change, and existing rows keep the vectors they have until you
rename the column and let it recompute.
