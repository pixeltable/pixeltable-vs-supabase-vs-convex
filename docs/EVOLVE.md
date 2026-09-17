# Adding a column to live data, measured

The claim this repo makes most often is that a schema change on a table that already
holds rows is cheap on Pixeltable and a project on the other two. Here it is run.

**The task.** Make the video title semantically searchable. The column is new, the rows
already exist, and an embedding is not derivable in SQL, so every existing row has to be
read, sent to a model, and written back. That is the shape of every real schema change on
a populated table.

**The corpus.** The 20-video tier on top of the fixtures: 24 videos on Pixeltable, 23 on
the other two. The backfill touches one row per video.

**What is committed.** Nothing. The contract does not need title search, so putting it in
all three would inflate every line count in the repo with a feature nobody calls. Each
change is applied, timed, and reverted. The diffs are in
[`harness/evolve/`](../harness/evolve/) and the runner is
[`harness/bench_evolve.py`](../harness/bench_evolve.py). Raw output:
[`evolve.json`](evolve.json).

## What it cost

| | Schema change | Backfill | Total | Lines written | Files touched |
|---|---|---|---|---|---|
| Pixeltable | 3.88s | same step | 3.88s | **1** | **1** |
| Supabase | 0.07s | 1.52s | **1.6s** | 24 | 2 |
| Convex | 5.98s | 1.39s | 7.37s | 53 | 2 |

**Supabase is the fastest, and Pixeltable is not.** At two dozen rows the backfill is one
batched embedding call and a couple of dozen updates, so wall time is dominated by what
surrounds it: building an HNSW index, or pushing a deployment. Anyone quoting these
seconds as a scaling result is quoting noise.

The column that is not noise is the last two. Pixeltable's entire change:

```python
class Videos(TableModel, name='videos'):
    ...
    __indexes__ = [pxt.EmbeddingIndex(title, embedding=SEMANTIC)]
```

Then `pxt schema update app.py media`. The index is declared, the existing rows are
backfilled by the same command, and nothing else is written.

Supabase needs the DDL and then a script, because Postgres cannot call a model and a
generated column cannot hold an embedding:

```sql
ALTER TABLE videos ADD COLUMN IF NOT EXISTS title_embedding vector(384);
CREATE INDEX IF NOT EXISTS videos_title_embedding_idx ON videos
    USING hnsw (title_embedding vector_cosine_ops);
```

```ts
const { data: rows } = await db.from("videos").select("id,title").is("title_embedding", null);
for (let i = 0; i < rows.length; i += BATCH) { /* embed the batch, update each row */ }
```

Convex needs the schema edit, a vector index, and a migration action that pages rows
through a query and a mutation, because an action cannot write to the database:

```ts
export const backfillTitleEmbeddings = internalAction({ ... });
```

## Three things the clock does not show

**Reverting is not symmetric.** Pixeltable takes the line back out and re-runs
`pxt schema update --allow-destructive`, which refuses by default because it drops an
index. Supabase drops the column and the index. Convex needs **a second migration**:
pushing a schema that no longer declares `titleEmbedding` is rejected while documents
still carry it, so the field has to be unset on every row first. That reverse migration is
17 of Convex's 53 lines and exists only to undo the forward one.

**Pixeltable's running service has to be restarted.** After `pxt schema update` changes a
table, an insert against the already-registered route answers
`409: table schema changed since route was registered; please restart the service`. The
catalog is updated and correct, and reads keep working; new writes need
`pxt service update` first. The other two have no equivalent step, because their handlers
resolve the table on every request. This is a real cost and it is not in the table above.

**Backfill time is the part that scales, and it is the part this corpus cannot show.**
1.5 seconds for 23 rows says nothing about 23 million. The structural claim stands on its
shape rather than these numbers: Pixeltable's backfill is work proportional to the rows
that changed and is the same command as the schema change, while a backfill script is
work proportional to the table and a separate thing to write, run, monitor and retry. This
page does not measure that, and neither does anything else in this repo.
