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
| Pixeltable | 0.53s | 0.96s | same step | **0.96s** | **1** | **1** |
| Supabase | 0.23s | 0.08s | 2.63s | 2.71s | 24 | 2 |
| Convex | 1.52s | 7.01s | 2.09s | 9.10s | 53 | 2 |

| 123 videos | Control | Schema change | Backfill | Total | Lines written | Files touched |
|---|---|---|---|---|---|---|
| Pixeltable | 0.81s | 5.22s | same step | 5.22s | **1** | **1** |
| Supabase | 0.12s | 0.09s | 3.42s | **3.51s** | 24 | 2 |
| Convex | 1.52s | 6.19s | 1.48s | 7.66s | 53 | 2 |

Controls: a `title_len` column for Pixeltable, an optional `titleTag` push for
Convex, a plain `title_tag` text column for Supabase. What each adds beyond its
control:

- **Pixeltable:** 0.4s at 23 rows, 4.4s at 123 - the fused backfill and index build,
  the only schema step that grows with the table.
- **Supabase:** the DDL is metadata-only; the row-proportional work is the script,
  2.6s then 3.4s.
- **Convex:** push minus control is ~4.7-5.5s and flat - registering the vector index
  is a fixed deployment cost; the backfill action is the row-proportional part.

### The same question asked the cheap way

Those numbers are the price of *semantic* title search. Ask only for text search and
Convex answers in one line, because `searchIndex` builds over a field the documents
already have:

| | Corpus | Total | Lines written | Files touched |
|---|---|---|---|---|
| Convex, `vectorIndex` (semantic) | 23 | 9.10s | 53 | 2 |
| | 123 | 7.66s | 53 | 2 |
| Convex, `searchIndex` (lexical) | 23 | **2.75s** | **1** | **1** |
| | 123 | **1.67s** | **1** | **1** |

Postgres's equivalent is a GIN index over `to_tsvector(title)`, Pixeltable's a
`BtreeIndex`. Read the 24 and the 53 as the cost of semantic parity; the row that
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
  migration - 11 of its 53 lines exist only to undo the forward one, because pushing
  a schema without `titleEmbedding` is rejected while documents have it. The
  `searchIndex` variant has no such problem. Pixeltable re-runs
  `pxt schema update --allow-destructive`, refused by default.
- **Pixeltable's running service has to be restarted.** An insert against an
  already-registered route answers `409: table schema changed` until
  `pxt service update` runs. The other two resolve the table per request.
- **Backfill time is the part that scales.** Pixeltable's fused residual grows with
  rows, Convex's index-registration cost does not, and at 123 rows Supabase's batched
  script overtakes Pixeltable on the clock - the fused step buys lines, not speed.
  Neither corpus size says what happens at millions of rows.
