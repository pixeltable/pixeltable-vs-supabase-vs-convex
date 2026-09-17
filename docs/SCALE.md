# Scale, measured

Three videos is the right size for asserting that three implementations agree and the
wrong size for saying anything about throughput. Two tiers answer the throughput question,
and the second exists to test whether the first one's answer was about the platforms or
about a small corpus:

| Tier | Videos | Footage | Frames at 1 fps | Transcript chunks |
|---|---|---|---|---|
| large | 20 | 10 min | 603 | 70 |
| xl | 100 | 63 min | 3,778 | 400 |

Regenerate the fixtures and reproduce every number here:

```bash
python fixtures/videos/generate.py --tier large   # or --tier xl
python harness/benchmark.py --impl pixeltable --tier large
python harness/benchmark.py --impl supabase --base-url http://127.0.0.1:54321 --auth-token "$SECRET" --tier large
python harness/benchmark.py --impl convex --base-url http://127.0.0.1:3211 --tier large
```

Raw output is [`benchmarks.json`](benchmarks.json), which records the library versions
alongside the timings, because a timing without them is not reproducible. Nothing below is
typed by hand.

## Ingest

Two tiers, each ingested on top of the corpus the previous one left. Large is 20 videos
and 10 minutes of footage into a table holding 3; xl is 100 videos and 63 minutes into a
table holding 103. All three finished every video at both tiers with no failed attempts.

| | Tier | Wall time | Faster than realtime | Median video |
|---|---|---|---|---|
| Pixeltable | large | 66.7s | 9.04x | 3.1s |
| | **xl** | **469.8s** | **8.04x** | **4.7s** |
| Supabase | large | 51.8s | 11.64x | 2.1s |
| | **xl** | **274.3s** | **13.78x** | **2.7s** |
| Convex | large | 53.7s | 11.25x | 2.4s |
| | **xl** | **290.1s** | **13.02x** | **2.9s** |

**The ordering holds and the gap widens.** Pixeltable was 1.29x slower than the fastest of
the other two at the large tier; at xl it is 1.71x slower. Per video, its median grew 52%
between tiers where Supabase's grew 29% and Convex's 21%, which is what index maintenance
on a growing table looks like. Supabase and Convex both got *faster* per second of footage
as the tier grew, because the xl videos are longer and the per-request overhead is amortised
over more work.

That is the answer to the question the large tier could not settle: the ordering is a
property of the implementations, not of a small corpus, and on ingest the distance grows
with the data rather than shrinking.

## Search

Ten queries, five visual and five spoken, none of them the fixture queries the correctness
suites assert on. Six passes, one untimed warm-up. Large was measured over 23 videos and
648 frames; xl over **203 videos, 7,689 frames and 806 transcript chunks**.

| | Tier | Frame search p50 | p95 | Transcript search p50 | p95 |
|---|---|---|---|---|---|
| Pixeltable | large | 39.0ms | 42.9ms | 18.5ms | 21.6ms |
| | **xl** | **47.0ms** | **55.4ms** | **17.7ms** | **21.7ms** |
| Supabase | large | 26.1ms | 30.5ms | 13.7ms | 16.3ms |
| | **xl** | **34.5ms** | **38.0ms** | **16.0ms** | **18.2ms** |
| Convex | large | 26.6ms | 40.7ms | 11.8ms | 17.7ms |
| | **xl** | **27.9ms** | **34.3ms** | **12.5ms** | **16.5ms** |

**Pixeltable is the slowest at both tiers**, and the ordering is unchanged. What did change
is how each one absorbed 12x the vectors: Convex's frame search grew 5%, Pixeltable's 21%,
Supabase's HNSW 32%. Convex's vector index scaled best of the three here.

Most of every number is still embedding the query, not searching. Measured directly against
`compute-service`, one CLIP text embedding is 19.9ms and one MiniLM embedding is 6.4ms.
Subtract those and at xl the frame search itself is roughly 8ms on Convex, 15ms on
Supabase, and 27ms on Pixeltable.

## What these numbers are not

- **One laptop, one run, CPU only, local models.** They compare the three against each
  other on identical work, which is the question this repo asks. They are not a capacity
  estimate for anyone's production, and they move: the same three measured on a busier
  machine were 20% slower across the board with the same ordering. Read the gaps, not the
  milliseconds.
- **One set of library versions**, recorded in `benchmarks.json` beside the timings.
  Pixeltable 0.7.8, sentence-transformers 5.7.0, transformers 4.57.6, torch 2.8.0.
- **7,689 vectors is still not a vector benchmark.** HNSW and Convex's vector index are
  both well inside the range where a linear scan would also be fast, and nothing here
  measures recall. The tiers answer whether the ordering survives 12x, not what happens at
  a million rows.
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
