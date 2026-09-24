# Adding a column to live data, measured

The repo's most-made claim is that a schema change on a populated table is cheap on
Pixeltable and a project on the other two. Here it is run.

**The task.** Make the video title semantically searchable: a new column over
existing rows, where the value is an embedding and so not derivable in SQL.

**The corpus.** 23 videos and 123 videos, on all three. The backfill touches one row
per video.

**What is committed.** Nothing. Each change is applied, timed and reverted, so the
repo's line counts keep measuring the contract. The diffs are in
[`harness/evolve/`](../harness/evolve/), the runner is
[`harness/bench_evolve.py`](../harness/bench_evolve.py), raw output
[`evolve.json`](evolve.json).

## What it cost

Each platform is timed twice: a **control** exercising the same mechanism with no
model work, then the change. The difference is the work that scales with rows.

| 23 videos | Control | Schema change | Backfill | Total | Lines written | Files touched |
|---|---|---|---|---|---|---|
| Pixeltable | 1.10s | 1.31s | same step | **1.31s** | **1** | **1** |
| Supabase | 0.05s | 0.04s | 1.27s | **1.31s** | 24 | 2 |
| Convex | 2.76s | 7.41s | 2.86s | 10.27s | 41 | 2 |

| 123 videos | Control | Schema change | Backfill | Total | Lines written | Files touched |
|---|---|---|---|---|---|---|
| Pixeltable | 1.08s | 4.38s | same step | 4.38s | **1** | **1** |
| Supabase | 0.06s | 0.04s | 2.11s | **2.16s** | 24 | 2 |
| Convex | 2.47s | 6.85s | 2.49s | 9.33s | 41 | 2 |

Controls: a `title_len` column for Pixeltable, an optional `titleTag` push for
Convex, a plain `title_tag` text column for Supabase. What each adds beyond its
control:

- **Pixeltable:** 0.2s at 23 rows, 3.3s at 123 rows: the fused backfill and index
  build, the one schema step here that grows with the table.
- **Supabase:** the DDL is metadata-only; the row-proportional work is the script,
  1.3s at 23 rows and 2.1s at 123 rows.
- **Convex:** the push costs 4.7s at 23 rows and 4.4s at 123 rows beyond its control,
  flat, so registering the vector index is a fixed deployment cost. Its backfill action
  did not grow between these two corpus sizes either.

### The same question asked the cheap way

Those numbers are the price of *semantic* title search. Ask only for text search and
Convex answers in one line, because `searchIndex` builds over a field the documents
already have:

| | Corpus | Total | Lines written | Files touched |
|---|---|---|---|---|
| Convex, `vectorIndex` (semantic) | 23 | 10.27s | 41 | 2 |
| | 123 | 9.33s | 41 | 2 |
| Convex, `searchIndex` (lexical) | 23 | **2.92s** | **1** | **1** |
| | 123 | **3.54s** | **1** | **1** |

Postgres's equivalent is a GIN index over `to_tsvector(title)`, Pixeltable's a
`BtreeIndex`. Read the 24 and the 41 as the cost of semantic parity; the row that
survives either reading is Pixeltable's 1 line, which buys the semantic version.

Pixeltable's entire change:

```python
class Videos(TableModel, name='videos'):
    ...
    __indexes__ = [pxt.EmbeddingIndex(title, embedding=SEMANTIC)]
```

Then `pxt schema update app.py media`. Supabase needs the DDL plus a script
(Postgres cannot call a model and a generated column cannot hold an embedding);
Convex needs the schema edit plus a migration action that pages rows through a query
and a mutation.

## Three things the clock does not show

- **Reverting is not symmetric.** Supabase drops the column; Convex needs a second
  migration, 13 more lines not charged above, because pushing a schema without
  `titleEmbedding` is rejected while documents have it. The
  `searchIndex` variant has no such problem. Pixeltable re-runs
  `pxt schema update --allow-destructive`, refused by default.
- **Pixeltable's running service has to be restarted.** An insert against an
  already-registered route answers `409: table schema changed` until
  `pxt service update` runs. The other two resolve the table per request.
- **Backfill time is the part that scales.** Pixeltable's fused residual grows with
  rows, Convex's index-registration cost does not, and at 123 rows Supabase's batched
  script overtakes Pixeltable on the clock - the fused step buys lines, not speed.
  Neither corpus size says what happens at millions of rows.
