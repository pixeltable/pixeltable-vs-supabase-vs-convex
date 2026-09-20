# Adding a column to live data, measured

The claim this repo makes most often is that a schema change on a table that already
holds rows is cheap on Pixeltable and a project on the other two. Here it is run.

**The task.** Make the video title semantically searchable. The column is new, the rows
already exist, and an embedding is not derivable in SQL, so every existing row has to be
read, sent to a model, and written back. That is the shape of every real schema change on
a populated table.

**The corpus.** Two sizes on all three: 23 videos (the large tier on top of the
fixtures) and 123 (the xl tier on top of that). The backfill touches one row per video.

**What is committed.** Nothing. The contract does not need title search, so putting it in
all three would inflate every line count in the repo with a feature nobody calls. Each
change is applied, timed, and reverted. The diffs are in
[`harness/evolve/`](../harness/evolve/) and the runner is
[`harness/bench_evolve.py`](../harness/bench_evolve.py). Raw output:
[`evolve.json`](evolve.json).

## What it cost

The three schema changes are not the same kind of operation, so each platform is timed
twice: once for a **control** that exercises the same mechanism with no model work, and
once for the change itself. The mechanism is warmed first on the unchanged schema, so a
cold interpreter or bundler does not land in either number. The control is the fixed
price of the mechanism; the difference is the work that scales with rows.

| 23 videos | Control | Schema change | Backfill | Total | Lines written | Files touched |
|---|---|---|---|---|---|---|
| Pixeltable | 0.53s | 0.96s | same step | **0.96s** | **1** | **1** |
| Supabase | 0.23s | 0.08s | 2.63s | 2.71s | 24 | 2 |
| Convex | 1.52s | 7.01s | 2.09s | 9.10s | 53 | 2 |

| 123 videos | Control | Schema change | Backfill | Total | Lines written | Files touched |
|---|---|---|---|---|---|---|
| Pixeltable | 0.81s | 5.22s | same step | 5.22s | **1** | **1** |
| Supabase | 0.12s | 0.09s | 3.42s | **3.51s** | 24 | 2 |
| Convex | 1.52s | 6.19s | 1.48s | 7.66s | 53 | 2 |

What the controls are: a computed `title_len` column for Pixeltable (visits every row,
calls no model), an optional `titleTag` field for Convex (a push with no index), a plain
`title_tag` text column for Supabase. What each platform adds beyond its control is the
interesting part:

- **Pixeltable:** schema minus control is 0.4s at 23 rows and 4.4s at 123 - the fused
  backfill, embedding plus index build for every existing row, and the only one of the
  three whose schema step grows with the table.
- **Supabase:** the DDL is metadata-only at both sizes measured; everything
  row-proportional sits in the hand-written script: one batched embedding call per 64
  rows plus an UPDATE per row, 2.6s then 3.4s.
- **Convex:** push minus control is ~4.7-5.5s and flat across corpus size - registering
  the vector index is a fixed deployment cost (document validation runs on every push,
  so it is already in the control). The backfill action (1.5-2.1s) is the
  row-proportional part.

An earlier version of this table reported 9.06s for the same Pixeltable change: that
number was a cold measurement, the first `pxt schema update` of a session, and most of
it was importing the schema file. Warmed once, the fused step is the cheapest on the
table at 23 rows and still second at 123. Seconds at this corpus size remain noise for
scaling claims; what the control column adds is proof of *where* the noise lives.

### The same question asked the cheap way

Those numbers are the price of *semantic* title search, where the other two must compute a
vector per row. Ask only for text search and Convex answers in one line with no backfill
and no reverse migration, because `searchIndex` builds over a field the documents already
carry:

```ts
  }).searchIndex("by_title", { searchField: "title" }),
```

| | Total | Lines written | Files touched |
|---|---|---|---|
| Convex, `vectorIndex` (semantic, same feature as the other two) | 7.66s | 53 | 2 |
| Convex, `searchIndex` (lexical) | **1.67s** | **1** | **1** |

Both are measured and both are in [`evolve.json`](evolve.json). Postgres has the same
cheap answer in a GIN index over `to_tsvector(title)`, and Pixeltable in a `BtreeIndex`.
So read the 24 and the 53 as what semantic parity costs, not as what it costs to make a
title searchable. The row that survives either reading is Pixeltable's 1 line, which buys
the semantic version.

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
11 of Convex's 53 lines and exists only to undo the forward one. The `searchIndex` variant
has no such problem: nothing was written to the rows, so dropping the index from the schema
is the whole rollback.

**Pixeltable's running service has to be restarted.** After `pxt schema update` changes a
table, an insert against the already-registered route answers
`409: table schema changed since route was registered; please restart the service`. The
catalog is updated and correct, and reads keep working; new writes need
`pxt service update` first. The other two have no equivalent step, because their handlers
resolve the table on every request. This is a real cost and it is not in the table above.

**Backfill time is the part that scales, and two corpus sizes only start to show it.**
The controls do expose the slope: Pixeltable's schema-minus-control residual grows with
rows (0.4s to 4.4s) because embedding is fused into the change, while Convex's push
residual stays flat (~5s) because index registration is fixed deployment cost. At 123
rows Supabase's batched script overtakes Pixeltable's in-process embedding on the clock -
the fused step buys lines, not speed. But 123 rows still says nothing about 23 million:
a hand-written backfill is a separate thing to write, run, monitor and retry at any
size, and no corpus in this repo is large enough to make that the bottleneck over the
machinery around it.
