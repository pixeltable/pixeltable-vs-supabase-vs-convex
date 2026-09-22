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
table holding 103. All three finished every video at both tiers. One ingest attempt
failed - a Pixeltable job at xl, retried successfully and recorded in
`benchmarks.json`, not edited out of the count.

**Faster than realtime** is seconds of footage divided by seconds spent: at 10.45x,
Pixeltable chewed through 63 minutes of video in 6 minutes. It is here because the two
tiers hold different amounts of footage, 10 minutes against 63, so wall times are not
comparable between them and this is. Higher is faster.

| | Tier | Wall time | Faster than realtime | Median video |
|---|---|---|---|---|
| Pixeltable | large | 62.3s | 9.70x | 2.9s |
| | **xl** | **361.6s** | **10.45x** | **3.5s** |
| Supabase | large | 45.8s | 13.18x | 2.0s |
| | **xl** | **223.7s** | **16.89x** | **2.2s** |
| Convex | large | 47.6s | 12.68x | 1.9s |
| | **xl** | **231.5s** | **16.32x** | **2.3s** |

**The ordering holds and the gap widens.** Pixeltable was 1.36x slower than the fastest of
the other two at the large tier; at xl it is 1.62x slower. Per video, its median grew 21%
between tiers, against 10% for Supabase and 21% for Convex. All three got *faster* per
second of footage as the tier grew, because the xl videos are longer and the per-request
overhead is amortised over more work, but Pixeltable's gain was the smallest.

That is the answer to the question the large tier could not settle: the ordering is a
property of the implementations, not of a small corpus, and on ingest the distance grows
with the data rather than shrinking.

Two asymmetries sit underneath it, and neither is measured separately. The timed boundary
holds a different scene detector per side - PySceneDetect scoring frames in Python for
Pixeltable, ffmpeg's `select` filter in C for the other two - and different frame work:
Pixeltable resizes every frame for its stored still, while Supabase and Convex ship every
frame base64'd to the object store. Saying the gap is index maintenance would be a guess.
And Supabase and Convex reach `compute-service` over loopback here, 9 requests and
1.07 MB per video that cost nothing on one machine and would not be free in a deployment.
Their column is a lower bound; Pixeltable's is what it is. See the last caveat below.

The first video of each run is slower than the median on all three (cold model and
connection setup, recorded separately as `first_video_sec`), and it is inside the wall
time - a warm-up ingest would fix the measurement and pollute the corpus, so the record
shows the cost rather than hiding it.

## Search

Ten queries, five visual and five spoken, none of them the fixture queries the correctness
suites assert on. Six passes, one untimed warm-up. Large was measured over 23 videos and
648 frames; xl over **203 videos, 7,689 frames and 806 transcript chunks**.

| | Tier | Frame search p50 | p95 | Transcript search p50 | p95 |
|---|---|---|---|---|---|
| Pixeltable | large | 20.9ms | 22.4ms | 17.9ms | 21.1ms |
| | **xl** | **22.2ms** | **24.2ms** | **17.0ms** | **18.5ms** |
| Supabase | large | 20.4ms | 26.5ms | 17.0ms | 21.9ms |
| | **xl** | **17.3ms** | **21.2ms** | **16.6ms** | **22.2ms** |
| Convex | large | 13.9ms | 18.1ms | 11.2ms | 14.6ms |
| | **xl** | **15.3ms** | **21.5ms** | **11.4ms** | **16.5ms** |

The ordering is unchanged: Pixeltable is last at both tiers. Read the size of that before
reading the rank. Every implementation answers every query in under 25ms at 7,689 vectors,
the widest p50 spread at xl is about 7ms, and much of every one of these numbers is the
query embedding rather than the search: measured directly against `compute-service` on
this machine, one CLIP text embedding is about 10ms and one MiniLM embedding about 7ms.
Nobody picks a database on 7ms, and this table is not a reason to.

How each absorbed 12x the vectors is not readable in this table: the frame-search p50s
moved within ~3ms in both directions and the transcript p50s within 1ms. At this
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
| Pixeltable | **206.1ms** | **235.0ms** |
| Supabase | 700.3ms | 851.1ms |
| Convex | 807.8ms | 1104.3ms |

**Pixeltable is 3.4x faster than Supabase and 3.9x faster than Convex here**, and all three
return the same answer from the same weights. This is the one measurement in this repo
where the architecture shows up directly in the clock rather than in the line count: one
agent query costs Supabase and Convex three round trips to `compute-service`, one to embed
the question for the frame index, one for the transcript index, and one to generate.
Pixeltable makes none, because the model runs where the data is.

It is also the operation this benchmark had never measured, in a repo that measures
everything else.

## Reads

The contract's fifth operation: what it costs to read back what was ingested. Two
measurements per tier - `GET /videos` list latency, and fetching a real `frame_url`
the API returned (an end-to-end media fetch, not a string check). Added after the
suites had passed for months without anyone fetching one: a local Supabase stack was
returning `kong:8000` URLs no client could resolve until the ingest code was taught
to rebuild the public origin from Kong's `X-Forwarded-*` headers. The regression
guard in `test_equivalence.py` now fetches a returned URL on every run.

| | Tier | `GET /videos` p50 | p95 | Frame fetch p50 | p95 |
|---|---|---|---|---|---|
| Pixeltable | small / 3 videos | 1.8ms | 2.0ms | 0.6ms | 1.0ms |
| | large / 23 | 6.1ms | 8.4ms | 1.7ms | 2.5ms |
| | **xl / 203** | **5.1ms** | **6.8ms** | **0.7ms** | **0.9ms** |
| Supabase | small / 3 videos | 6.8ms | 12.9ms | 2.8ms | 4.2ms |
| | large / 23 | 6.4ms | 20.1ms | 2.8ms | 11.6ms |
| | **xl / 203** | **7.8ms** | **17.6ms** | **2.1ms** | **3.0ms** |
| Convex | small / 3 videos | 1.4ms | 2.2ms | 0.4ms | 0.8ms |
| | large / 23 | 1.9ms | 4.8ms | 0.4ms | 1.0ms |
| | **xl / 203** | **2.4ms** | **12.9ms** | **0.4ms** | **0.9ms** |

Convex wins the read path outright: the query layer lists 203 rows in ~2ms and its
object store answers frames in 0.4ms. Pixeltable's list cost grows with rows (the
JSON it assembles per row does), landing between the other two; its media serving is
fast. Supabase is slowest on both - every request traverses Kong into Postgres, and
media bytes traverse Kong again into the storage service. All three are still
single-digit-to-low-double-digit milliseconds; this is an ordering table, not a
problem for anyone.

Two footnotes on what the stopwatch contains. The frame fetches are not byte-equal:
Pixeltable serves the stored 320x180 `still` it computed at ingest, while Supabase and
Convex serve the full 640x360 JPEG they uploaded - different payloads through different
stores. And every Supabase request on this page pays `withSupabase` auth verification
the other two do not run, a real platform cost that is nonetheless a cost only one
column carries.

## Under load

Same ten search queries, but eight clients in flight at once (`--workers 8`, one
persistent connection each, 48 requests total). This measures how the serial numbers
degrade, which is a different question than latency.

| | Tier | Concurrent p50 | p95 | vs serial p50 |
|---|---|---|---|---|
| Pixeltable | small | 121.3ms | 174.1ms | ~6x |
| | large | 173.6ms | 264.6ms | ~8x |
| | **xl** | **119.5ms** | **173.7ms** | ~6x |
| Supabase | small | 59.4ms | 138.9ms | ~3x |
| | large | 64.9ms | 197.3ms | ~3x |
| | **xl** | **67.0ms** | **123.9ms** | ~4x |
| Convex | small | 64.3ms | 124.4ms | ~4.5x |
| | large | 63.1ms | 72.9ms | ~4x |
| | **xl** | **65.2ms** | **72.8ms** | ~4.5x |

The property that wins Pixeltable the agent query loses it this one: its embedding
model lives in the request path, so eight concurrent searches queue behind one
in-process CLIP and MiniLM. The other two hand the same work to `compute-service`,
whose own throughput is shared between them here - and still hold ~60-67ms because
the edge function and the action layers are stateless and parallel. Invert it again
on cost: the two that scale better are paying for a second process to do it.

## Hosted model

The agent again, but with local generation swapped for one hosted model -
`nvidia/nemotron-3-super-120b-a12b:free` on OpenRouter, identical for all three. The
swap is the thing being measured: on Pixeltable it is a 7-line schema change and the
`openrouter` function's request-rate scheduler paces and retries; on the other two it is a
36-37 line helper, because pacing, Retry-After and backoff are application code.
`harness/bench_hosted.py` applies the patches, delivers the key through each vendor's
own config path, fires 12 questions at 6 workers, then reverts everything. Numbers in
`docs/hosted.json`.

| | ok | Wall | p50 | p95 | Retries | Lines |
|---|---|---|---|---|---|---|
| Supabase | 12/12 | 6.0s | 1.5s | 3.7s | 2 | 36 |
| Convex | 12/12 | 10.5s | 2.8s | 7.3s | 1 | 37 |
| Pixeltable | 7/12 | 30.8s | 10.3s | 30.8s | scheduler-internal | 7 |

Two findings, neither flattering to a tidy story. First: the free pool degrades by
returning HTTP 200 with an `error` body (`503 upstream overloaded`) or a completion
whose `content` is empty - a status check alone cannot see either. The hand-written
loops inspect the body and retry on both, which is what keeps them at 12/12; Pixeltable's
computed column evaluates the response it is given, so a malformed 200 lands as a
null answer - the scheduler retries raised errors, not well-formed wrong ones.
`hosted.json` records the cells' `errormsg`/`errortype`, and all five misses are empty
answers with no recorded error. The run did not record which of the two shapes they
were. The token cap is the unlikely one: `harness/probe_hosted.py` sends the agent's
prompt to the paid endpoint of the same model, and every answer came back with its
reasoning far under `max_tokens` ([hosted_probe.json](hosted_probe.json)). The paid
endpoint routes to other providers than the free one, so the probe cannot reproduce
the free pool's errors.
Second: provider latency dominates the medians, but Pixeltable's spread is worse -
in the request-rate scheduler a retried request runs synchronously ahead of the
queued ones, so a single 429 stalls the line behind its backoff. The line counts are
the other half of the trade: 7 lines versus 36-37 buys pacing and retries, and gives
up the ability to inspect a bad 200.

The run above is the corrected swap. An earlier published run pointed the generic
`openai.chat_completions` at OpenRouter through `OPENAI_BASE_URL`, and that
function's scheduler paces off `x-ratelimit-*` response headers OpenRouter only
sends on errors - so the pool never initialized and every request ran the
scheduler's synchronous bootstrap path. The dedicated `openrouter.chat_completions`
UDF paces on a configured request rate instead, and the harness now records
per-cell errors before tearing the table down.

Free-tier provider saturation moves minute to minute - a repeat run showed Supabase
absorbing ten retries and Pixeltable losing only one of twelve - so the counts above
are a snapshot of one window, not a property of the platforms. What does not move:
who wrote the retry code, and who could see inside the response.

## What these numbers are not

- **One laptop, one run, CPU only, local models.** They compare the three against each
  other on identical work, which is the question this repo asks. They are not a capacity
  estimate for anyone's production, and they move: the same three measured on a busier
  machine were 20% slower across the board with the same ordering. Read the gaps, not the
  milliseconds.
- **Two sets of library versions**, both recorded in `benchmarks.json` beside the
  timings because they are different interpreters: `versions` is the harness and
  compute-service env (sentence-transformers 5.7.0, transformers 4.57.6, torch 2.8.0),
  `service_env_versions` is the env the Pixeltable service runs under (Pixeltable
  0.7.8, torch 2.14.0).
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
