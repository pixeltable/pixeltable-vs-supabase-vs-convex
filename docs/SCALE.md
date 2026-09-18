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

**Faster than realtime** is seconds of footage divided by seconds spent: at 10.59x,
Pixeltable chewed through 63 minutes of video in 5.9 minutes. It is here because the two
tiers hold different amounts of footage, 10 minutes against 63, so wall times are not
comparable between them and this is. Higher is faster.

| | Tier | Wall time | Faster than realtime | Median video |
|---|---|---|---|---|
| Pixeltable | large | 62.0s | 9.73x | 2.8s |
| | **xl** | **356.9s** | **10.59x** | **3.5s** |
| Supabase | large | 51.4s | 11.75x | 2.1s |
| | **xl** | **213.4s** | **17.71x** | **2.1s** |
| Convex | large | 45.8s | 13.19x | 2.0s |
| | **xl** | **220.7s** | **17.12x** | **2.2s** |

**The ordering holds and the gap widens.** Pixeltable was 1.35x slower than the fastest of
the other two at the large tier; at xl it is 1.67x slower. Per video, its median grew 25%
between tiers where Supabase's held flat and Convex's grew 10%, which is what index
maintenance on a growing table looks like. All three got *faster* per second of footage
as the tier grew, because the xl videos are longer and the per-request overhead is
amortised over more work, but Pixeltable's gain was the smallest.

That is the answer to the question the large tier could not settle: the ordering is a
property of the implementations, not of a small corpus, and on ingest the distance grows
with the data rather than shrinking.

One asymmetry sits underneath it. Supabase and Convex reach `compute-service` over
loopback here, 9 requests and 1.07 MB per video that cost nothing on one machine and
would not be free in a deployment. Their column is a lower bound; Pixeltable's is what it
is. See the last caveat below.

## Search

Ten queries, five visual and five spoken, none of them the fixture queries the correctness
suites assert on. Six passes, one untimed warm-up. Large was measured over 23 videos and
648 frames; xl over **203 videos, 7,689 frames and 806 transcript chunks**.

| | Tier | Frame search p50 | p95 | Transcript search p50 | p95 |
|---|---|---|---|---|---|
| Pixeltable | large | 22.9ms | 26.4ms | 17.2ms | 29.6ms |
| | **xl** | **22.4ms** | **23.3ms** | **19.3ms** | **20.2ms** |
| Supabase | large | 22.5ms | 41.5ms | 15.5ms | 18.7ms |
| | **xl** | **16.9ms** | **25.6ms** | **15.8ms** | **20.1ms** |
| Convex | large | 17.3ms | 21.4ms | 14.2ms | 18.2ms |
| | **xl** | **14.1ms** | **17.8ms** | **10.1ms** | **13.7ms** |

The ordering is unchanged: Pixeltable is last at both tiers. Read the size of that before
reading the rank. Every implementation answers every query in under 26ms at 7,689 vectors,
the whole spread at xl is 9ms, and much of every one of these numbers is the query
embedding rather than the search: measured directly against `compute-service` on this machine,
one CLIP text embedding is about 10ms and one MiniLM embedding about 7ms. Nobody picks a
database on 9ms, and this table is not a reason to.

How each absorbed 12x the vectors is not readable in this table: the frame-search p50s all
fell between tiers and the transcript p50s moved within 5ms in both directions. At this
size the index is a rounding error next to the embedding and the request path, which is
why the caveats below call this an ordering check and not a vector benchmark.

## The agent

The most expensive operation in the app, and the one where the three differ most. A
question goes in, both indexes are searched, the hits become a prompt, and
Qwen2.5-1.5B-Instruct writes an answer. Same model everywhere: in Pixeltable's own process
through `create_chat_completion`, and behind `compute-service` for the other two.

Measured on the 3-video baseline, because the retrieval inside it is a fixed top-4 from
each index regardless of how large the corpus is, so the number is dominated by generation
rather than by corpus size. Four passes over three questions.

| | p50 | p95 |
|---|---|---|
| Pixeltable | **230.9ms** | **358.8ms** |
| Supabase | 702.4ms | 1057.4ms |
| Convex | 711.8ms | 1742.4ms |

**Pixeltable is 3.0x faster than Supabase and 3.1x faster than Convex here**, and all three
return the same answer from the same weights. This is the one measurement in this repo
where the architecture shows up directly in the clock rather than in the line count: one
agent query costs Supabase and Convex three round trips to `compute-service`, one to embed
the question for the frame index, one for the transcript index, and one to generate.
Pixeltable makes none, because the model runs where the data is.

It is also the operation this benchmark had never measured, in a repo that measures
everything else.

## What these numbers are not

- **One laptop, one run, CPU only, local models.** They compare the three against each
  other on identical work, which is the question this repo asks. They are not a capacity
  estimate for anyone's production, and they move: the same three measured on a busier
  machine were 20% slower across the board with the same ordering. Read the gaps, not the
  milliseconds.
- **One set of library versions**, recorded in `benchmarks.json` beside the timings.
  Pixeltable 0.7.8, sentence-transformers 5.7.0, transformers 4.57.6, torch 2.14.0.
- **7,689 vectors is still not a vector benchmark.** HNSW and Convex's vector index are
  both well inside the range where a linear scan would also be fast, and nothing here
  measures recall. The tiers answer whether the ordering survives 12x, not what happens at
  a million rows.
- **Everything here runs on one machine, which is the assumption most favourable to the
  two that need a second service.** `compute-service` answers on `127.0.0.1`, so its
  round trips cost nothing. Measured on one 31-second video, a Supabase or Convex ingest
  makes **9 requests to it and moves 1.07 MB across that boundary, 3.4x the size of the
  source file**, because the frames come down base64-encoded and go straight back up to be
  embedded, and the audio is re-sent once per transcript chunk. Pixeltable makes zero
  requests and moves zero bytes: the models run in its own process.

  In a deployment those 9 round trips cross a network. Convex actions run on Convex's
  infrastructure and Supabase Edge Functions on Supabase's, so neither can reach a compute
  service on `127.0.0.1` at all, which `convex-app/README.md` already says. What that
  costs is not measured here and would not favour the two making the calls. Read the
  ingest numbers as a lower bound for them and an accurate figure for Pixeltable.
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
