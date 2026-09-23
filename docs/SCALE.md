# Scale, measured

Two tiers, each ingested on top of the corpus the previous left, to test whether the
ordering is a property of the platforms or of a small corpus:

| Tier | Videos | Footage | Frames at 1 fps | Transcript chunks |
|---|---|---|---|---|
| large | 20 | 10 min | 603 | 70 |
| xl | 100 | 63 min | 3,778 | 400 |

Reproduce:

```bash
python fixtures/videos/generate.py --tier large   # or --tier xl
python harness/benchmark.py --impl pixeltable --tier large
python harness/benchmark.py --impl supabase --base-url http://127.0.0.1:54321 --auth-token "$SECRET" --tier large
python harness/benchmark.py --impl convex --base-url http://127.0.0.1:3211 --tier large
```

Raw output is [`benchmarks.json`](benchmarks.json), which records the library
versions alongside the timings. Nothing below is typed by hand.

## Ingest

One ingest attempt failed - a Pixeltable job at xl, retried successfully and recorded
in `benchmarks.json`.

**Faster than realtime** is footage seconds divided by wall seconds, because the
tiers hold different footage amounts. Higher is faster.

| | Tier | Wall time | Faster than realtime | Median video |
|---|---|---|---|---|
| Pixeltable | large | 62.3s | 9.70x | 2.9s |
| | **xl** | **361.6s** | **10.45x** | **3.5s** |
| Supabase | large | 45.8s | 13.18x | 2.0s |
| | **xl** | **223.7s** | **16.89x** | **2.2s** |
| Convex | large | 47.6s | 12.68x | 1.9s |
| | **xl** | **231.5s** | **16.32x** | **2.3s** |

Pixeltable is last at both tiers and the gap widens (1.36x slower than the fastest at
large, 1.62x at xl). The ordering is a property of the implementations. Two
asymmetries sit underneath, neither measured separately: a different scene detector
per side (PySceneDetect in Python against ffmpeg's `select` filter in C) and
different frame work (a stored 320x180 still against base64 to object storage). And
the two that reach `compute-service` pay an average of 8.5 requests and 1.35 MB
per video over loopback ([roundtrip.json](roundtrip.json)), which a deployment
would charge for.

## Search

Ten queries, six passes, one untimed warm-up. Large was measured over 23 videos and
648 frames; xl over 203 videos, 7,689 frames and 806 chunks.

| | Tier | Frame search p50 | p95 | Transcript search p50 | p95 |
|---|---|---|---|---|---|
| Pixeltable | large | 20.9ms | 22.4ms | 17.9ms | 21.1ms |
| | **xl** | **22.2ms** | **24.2ms** | **17.0ms** | **18.5ms** |
| Supabase | large | 20.4ms | 26.5ms | 17.0ms | 21.9ms |
| | **xl** | **17.3ms** | **21.2ms** | **16.6ms** | **22.2ms** |
| Convex | large | 13.9ms | 18.1ms | 11.2ms | 14.6ms |
| | **xl** | **15.3ms** | **21.5ms** | **11.4ms** | **16.5ms** |

Pixeltable is last at both tiers, but read the size before the rank: every
implementation's p50 stays under 25ms at 7,689 vectors (worst p95 26.5ms), and much of each
number is the query embedding (~10ms CLIP, ~7ms MiniLM, measured directly). This is
an ordering check, not a vector benchmark.

## The agent

The most expensive operation, and the one where the three differ most. Same model
everywhere: in Pixeltable's own process, behind `compute-service` for the other two.
Measured on the 3-video baseline, since the retrieval inside is a fixed top-4.

| | p50 | p95 |
|---|---|---|
| Pixeltable | **206.1ms** | **235.0ms** |
| Supabase | 700.3ms | 851.1ms |
| Convex | 807.8ms | 1104.3ms |

Pixeltable is 3.4x faster than Supabase and 3.9x faster than Convex: one agent query
costs the other two three round trips to `compute-service` (embed for frames, embed
for transcripts, generate) and Pixeltable none.

## Reads

`GET /videos` list latency plus a real fetch of one returned `frame_url`. The fetch
exists because a local Supabase stack once emitted `kong:8000` URLs no client could
resolve; `test_equivalence.py` fetches one on every run as the regression guard.

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

Convex wins the read path outright; every Supabase request traverses Kong twice and
pays `withSupabase` auth verification the other two do not run. The frame fetches are
not byte-equal: Pixeltable serves its stored 320x180 still, the other two the full
640x360 JPEG.

## Under load

The same ten searches, eight clients in flight at once: degradation, not speed.

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

The property that wins the agent query loses this one: eight concurrent searches
queue behind one in-process CLIP and MiniLM, while the other two hand the work to
`compute-service` and hold ~60-67ms.

## Hosted model

The agent with local generation swapped for one hosted model,
`nvidia/nemotron-3-super-120b-a12b` on OpenRouter's paid endpoint, identical for all
three. The swap is what is measured: a 7-line schema change on Pixeltable against a
36-37 line retry/backoff helper on the other two. `harness/bench_hosted.py` applies
the patches, fires 12 questions at 6 workers, reverts everything. Numbers in
`docs/hosted.json`.

| | ok | Wall | p50 | p95 | Retries | Lines |
|---|---|---|---|---|---|---|
| Supabase | 12/12 | 9.4s | 2.3s | 5.2s | 0 | 36 |
| Convex | 12/12 | 18.8s | 3.9s | 18.8s | 0 | 37 |
| Pixeltable | 12/12 | 36.6s | 8.4s | 34.1s | scheduler-internal | 7 |

On a healthy pool the retry code is never exercised. Provider response time dominates
the medians, and the longest tail is Pixeltable's, where pacing serializes inside the
request-rate scheduler.

The failure that code exists to catch is real and measured: the free pool returned 3
of 36 responses as HTTP 200 with an `error` field and no content
([hosted_probe.json](hosted_probe.json), keyed by model). A hand-written loop
inspects the body and retries that shape; a computed column evaluates it to a null
answer - the earlier free-pool run recorded five empty cells and 7/12 on Pixeltable
where both loops held 12/12. Free-pool saturation moves minute to minute, so those
counts are snapshots, not platform properties; what does not move is who wrote the
retry code and who could see inside the response.

## What these numbers are not

- **One laptop, one run, CPU only, local models.** Read the gaps, not the
  milliseconds; a busier machine measured the same three 20% slower with the same
  ordering.
- **Two sets of library versions**, recorded in `benchmarks.json`: the harness env
  and the Pixeltable service env.
- **7,689 vectors is still not a vector benchmark.** Nothing measures recall; the
  tiers answer whether the ordering survives 12x, not what happens at a million rows.
- **Everything runs on one machine, the assumption most favourable to the two that
  need a second service.** `compute-service` answers on `127.0.0.1`, so its 8.5
  requests and 1.35 MB per video cost nothing; a proxy adding 20-80ms per call added
  2.7-11.8s to the 20-video ingest ([roundtrip.json](roundtrip.json)). In a
  deployment neither edge runtime can even reach it there; read their ingest numbers
  as a lower bound.
- **Not a cost comparison.**

## What survives the numbers

The line counts, file counts and orchestration hops are properties of the code; this
page is a property of one afternoon on one machine. Where the two disagree, say both.
