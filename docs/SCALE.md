# Scale, measured

Three videos is the right size for asserting that three implementations agree and the
wrong size for saying anything about throughput. This is the 20-video tier: 10 minutes of
footage, 603 frames at 1 fps, 70 transcript chunks, ingested over HTTP into each
implementation and timed.

Regenerate the fixtures and reproduce every number here:

```bash
python fixtures/videos/generate.py --tier large
python harness/benchmark.py --impl pixeltable --tier large
python harness/benchmark.py --impl supabase --base-url http://127.0.0.1:54321 --auth-token "$SECRET" --tier large
python harness/benchmark.py --impl convex --base-url http://127.0.0.1:3211 --tier large
```

Raw output is [`benchmarks.json`](benchmarks.json). Nothing below is typed by hand.

## Ingest

20 videos, 603.7 seconds of footage, on top of an existing 3-video corpus. All three
finished 20 of 20 with no failed attempts.

| | Wall time | Faster than realtime | First video | Median video |
|---|---|---|---|---|
| Pixeltable | 79.1s | 7.64x | 4.6s | 3.7s |
| Supabase | **53.5s** | **11.29x** | 3.3s | **2.4s** |
| Convex | 56.9s | 10.6x | 5.3s | 2.5s |

**Pixeltable is the slowest of the three here, by about 1.4x.** The first video is
reported separately because it pays for loading CLIP, Whisper and the embedding model.

Ingest is asynchronous on Pixeltable, which answers with a job, and synchronous on the
other two. The harness waits for completion either way, so the column compares the same
thing. It polls every 50ms; at the 2s interval used for seeding, every Pixeltable ingest
rounds up to the next 2s and the wall time reads 90.5s instead of 79.1s. That is the
harness, not the platform, and it is worth saying because it was in an earlier number.

## Search

Ten queries, five visual and five spoken, none of them the fixture queries the
correctness suites assert on. Six passes, one untimed warm-up, 23 videos in the corpus.

| | Frame search p50 | p95 | Transcript search p50 | p95 |
|---|---|---|---|---|
| Pixeltable | 55.3ms | 60.8ms | 21.2ms | 24.3ms |
| Supabase | 35.7ms | 40.2ms | 17.2ms | 22.7ms |
| Convex | **29.8ms** | **37.8ms** | **14.5ms** | **21.1ms** |

**Pixeltable is the slowest here too**, by about 1.9x on frame search.

Most of every number is embedding the query, not searching. Measured directly against
`compute-service`, one CLIP text embedding is 22.2ms and one MiniLM embedding is 8.8ms.
Subtract those and Convex's frame search is about 8ms of vector search, hydration and
HTTP, Supabase's about 14ms, and Pixeltable's about 33ms of everything it does in
process. At 603 vectors no index is working hard; this compares the code around the
index, not the index.

## What these numbers are not

- **One laptop, one run, CPU only, local models.** They compare the three against each
  other on identical work, which is the question this repo asks. They are not a capacity
  estimate for anyone's production.
- **603 vectors is not a vector benchmark.** HNSW and Convex's vector index are both
  well inside the range where a linear scan would also be fast. Nothing here says
  anything about recall or latency at a million rows.
- **Not a cost comparison.** Two of the three are also paying for a second Python
  process, and none of this measures what any of it costs to run.

## What survives the numbers

The line counts, the file counts and the orchestration hops in the
[README](../README.md) are unchanged by this: they are properties of the code, and this
page is a property of one afternoon on one machine. Where the two disagree, say both.

The structural claims in [TRADEOFFS.md](TRADEOFFS.md) are also untouched. Adding a column
to live data, processing firing for any writer, per-cell errors and data versioning are
not throughput questions. If throughput at this scale is the binding constraint, this
page says Supabase and Convex win it, and the honest recommendation follows the
constraint rather than the sponsor.
