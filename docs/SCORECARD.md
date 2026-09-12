# Scorecard

Measured on 2026-09-11. Every figure in the first table comes from
`docs/metrics.json`, written by `python harness/run_comparison.py` reading the source.
Regenerate it after any code change.

## Measured

| | Pixeltable | Supabase | Convex | compute-service |
|---|---|---|---|---|
| App LOC | **128** | 473 | 458 | 258 |
| App files | **1** | 11 | 9 | 1 |
| Config LOC | 19 | 39 | 32 | 20 |
| Tables | 2 | 5 | 4 | 0 |
| Views | 2 | 0 | 0 | 0 |
| Vector indexes | 2 | 2 | 2 | 0 |
| Foreign keys | **0** | 3 | 0 | 0 |
| Database triggers | **0** | 2 | 0 | 0 |
| Orchestration hops | **0** | 19 | 17 | 0 |
| HTTP routes written by hand | 1 | 7 | 5 | 8 |
| Environment variables | **0** | 4 | 2 | 0 |
| External hosts called | **0** | 1 | 1 | 0 |

Supabase and Convex both require `compute-service`, so the code you maintain is
**731** and **716** lines against Pixeltable's **128**.

## Hand-classified

These are judgment calls, not measurements. They live in `CLASSIFIED` in
`harness/metrics.py`; the line to argue with is there.

| | Pixeltable | Supabase | Convex |
|---|---|---|---|
| Runtimes to operate | 1 | 2 | 2 |
| Needs an external compute service | No | Yes | Yes |
| Work runs when the row arrives | **Yes** | No | No |
| Adding a column backfills incrementally | **Yes** | No | No |
| Data versioning and revert | **Yes** | No | No |
| Account required before it typechecks | No | No | **Yes** |

## Observed behavior

From the runs recorded in [METHODOLOGY.md](METHODOLOGY.md).

| | Pixeltable | Supabase | Convex |
|---|---|---|---|
| Ran end to end | Yes | Yes | Not run |
| Equivalence suite | 10/10 | 10/10 | not run |
| Videos / frames / chunks from the same fixtures | 3 / 45 / 6 | 3 / 45 / 6 | not run |
| Frames per video | 16 / 15 / 14 | 16 / 15 / 14 | not run |
| Top-ranked video correct, all 5 fixture queries | Yes | Yes | not run |
| Ingest of 3 videos, models warm | 14s in-process | not timed precisely | not run |

## The ten steps

Rated Strong / Adequate / Weak from the code in [JOURNEY.md](JOURNEY.md).

| Step | Pixeltable | Supabase | Convex |
|---|---|---|---|
| 1. Install | Strong | Weak: Docker plus a second service | Weak: account required |
| 2. Schema | Strong: 1 table, 2 views | Adequate: 4 tables, 3 FKs | Adequate: optional fields for pending work |
| 3. Ingest | Strong: one insert | Weak: 91 lines | Weak: 75 lines |
| 4. Process | Strong: it is the schema | Weak: triggers and webhooks | Weak: scheduler, no retry |
| 5. Embed | Strong: one line | Weak: storage round trip per row | Weak: storage round trip per row |
| 6. Search | Strong: an expression | Adequate: SQL function plus join | Weak: N+1 per hit |
| 7. Agent | Strong: a table, evidence stored | Weak: nothing persisted | Weak: nothing persisted |
| 8. Serve | Strong: declared routes | Adequate: 7 handlers | Adequate: 5 routes |
| 9. Evolve | Strong: incremental backfill | Weak: migration plus backfill | Weak: migration action |
| 10. Inspect | Strong: per-cell errors, history, revert | Weak: derive it yourself | Weak: derive it yourself |

## Changelog

- **2026-09-11** Rewrote all three on the current APIs. Pixeltable moved to
  `TableModel` + `FastAPIRouter` + `pxt schema/service update`. Modal dropped. All
  models local, no API key on any platform. Metrics changed from hand-typed constants
  to measurements, and the LOC counter was fixed to honour `//` and `--` comments,
  which lowered the Supabase and Convex totals. Pixeltable and Supabase verified end
  to end.
- **2026-05-28** Rewrite from a document knowledge base to a video pipeline.
- **2026-05-22** Initial benchmark.
