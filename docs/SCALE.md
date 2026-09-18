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

**Faster than realtime** is seconds of footage divided by seconds spent: at 8.04x,
Pixeltable chewed through 63 minutes of video in 7.8 minutes. It is here because the two
tiers hold different amounts of footage, 10 minutes against 63, so wall times are not
comparable between them and this is. Higher is faster.

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
| Pixeltable | large | 39.0ms | 42.9ms | 18.5ms | 21.6ms |
| | **xl** | **47.0ms** | **55.4ms** | **17.7ms** | **21.7ms** |
| Supabase | large | 26.1ms | 30.5ms | 13.7ms | 16.3ms |
| | **xl** | **34.5ms** | **38.0ms** | **16.0ms** | **18.2ms** |
| Convex | large | 26.6ms | 40.7ms | 11.8ms | 17.7ms |
| | **xl** | **27.9ms** | **34.3ms** | **12.5ms** | **16.5ms** |

The ordering is unchanged: Pixeltable is last at both tiers. Read the size of that before
reading the rank. Every implementation answers every query in under 56ms at 7,689 vectors,
the whole spread at xl is 19ms, and around 20ms of every one of these numbers is the query
embedding rather than the search. Measured directly against `compute-service` on this machine, one CLIP
text embedding is about 20ms and one MiniLM embedding about 17ms. Nobody picks a database on
19ms, and this table is not a reason to.

What is worth reading is how each absorbed 12x the vectors: Convex's frame search grew 5%,
Pixeltable's 21%, Supabase's HNSW 32%. On that axis, the one the index is actually
responsible for, Convex scales best and Supabase worst, and Pixeltable sits between them.

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
| Pixeltable | **292.6ms** | **815.1ms** |
| Supabase | 1311.6ms | 1898.9ms |
| Convex | 979.7ms | 1281.5ms |

**Pixeltable is 4.5x faster than Supabase and 3.3x faster than Convex here**, and all three
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
  Pixeltable 0.7.8, sentence-transformers 5.7.0, transformers 4.57.6, torch 2.8.0.
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

  In a deployment those 8 round trips cross a network. Convex actions run on Convex's
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
