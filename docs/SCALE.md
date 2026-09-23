# Scale, measured

Two tiers, to test whether the ordering is a property of the platforms or of a small
corpus. Large is 20 videos, xl 100; footage per tier is `seconds_of_video` in the
artifact, at one frame per second. Each tier is measured over the corpus it leaves,
recorded as `corpus`: in the committed run large sits on the 3-video baseline, and xl
on the baseline plus the xl tier ingested twice, the same on all three.

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

Pixeltable is last at both tiers. That is one run per tier, so whether the gap grows
with the corpus is not something this table can say. Two asymmetries sit underneath,
neither measured separately: a different scene detector
per side (PySceneDetect in Python against ffmpeg's `select` filter in C) and
different frame work (a stored 320x180 still against base64 to object storage). And
the two that reach `compute-service` pay an average of 8.5 requests and 1.35 MB
per video across that boundary ([roundtrip.json](roundtrip.json)): loopback for
Convex, the Colima VM boundary for Supabase, and a network a deployment would
charge for.

**The Supabase and Convex timings above predate a fix to `compute-service`.** Its
endpoints were `async def` around blocking ffmpeg and model calls, which runs them on
the event loop and serializes every request the two consumers fan out. They are now
plain `def`, which FastAPI's documentation prescribes for blocking work: four
concurrent ffmpeg calls went from four times one call's latency to about one. That
was this repo's bug and it cost only the two competitors, so these two rows are an
overstate their ingest and load times until they are re-measured on a quiet machine.

## Search

Ten queries, six passes, one untimed warm-up, over the corpus each tier leaves:
`corpus` in the artifact.

| | Tier | Frame search p50 | p95 | Transcript search p50 | p95 |
|---|---|---|---|---|---|
| Pixeltable | large | 20.9ms | 22.4ms | 17.9ms | 21.1ms |
| | **xl** | **22.2ms** | **24.2ms** | **17.0ms** | **18.5ms** |
| Supabase | large | 20.4ms | 26.5ms | 17.0ms | 21.9ms |
| | **xl** | **17.3ms** | **21.2ms** | **16.6ms** | **22.2ms** |
| Convex | large | 13.9ms | 18.1ms | 11.2ms | 14.6ms |
| | **xl** | **15.3ms** | **21.5ms** | **11.4ms** | **16.5ms** |

Pixeltable is last at both tiers, but read the size before the rank: every
implementation's p50 is tens of milliseconds, and part of each number is embedding the
query, which all three do per request. This is an ordering check, not a vector
benchmark.

## The agent

The most expensive operation, and the one where the three differ most. Same model
weights everywhere: in Pixeltable's own process, behind `compute-service` for the other
two. Measured on the 3-video baseline, since the retrieval inside is a fixed top-4.

| | p50 | p95 |
|---|---|---|
| Pixeltable | **206.1ms** | **235.0ms** |
| Supabase | 700.3ms | 851.1ms |
| Convex | 807.8ms | 1104.3ms |

Pixeltable answers fastest. Two differences sit under the gap and were not
separated. Each library runs the model on its default device: Pixeltable's `llama_cpp`
UDF offloads to Metal on this Mac, and `llama-cpp-python` behind `compute-service` stays
on CPU unless asked. And one agent query costs the other two three round trips to
`compute-service` (embed for frames, embed for transcripts, generate), against none. How
much of the gap each accounts for is not measured here.

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

Convex is fastest on the read path. Every Supabase request passes the stack's Kong
gateway and `withSupabase` auth verification, which the other two do not run; that cost
was not isolated. The frame fetches are
not byte-equal: Pixeltable serves its stored 320x180 still, the other two the full
640x360 JPEG.

## Under load

The same ten searches, eight clients in flight at once: degradation, not speed.

| | Tier | Concurrent p50 | p95 |
|---|---|---|---|
| Pixeltable | small | 121.3ms | 174.1ms |
| | large | 173.6ms | 264.6ms |
| | **xl** | **119.5ms** | **173.7ms** |
| Supabase | small | 59.4ms | 138.9ms |
| | large | 64.9ms | 197.3ms |
| | **xl** | **67.0ms** | **123.9ms** |
| Convex | small | 64.3ms | 124.4ms |
| | large | 63.1ms | 72.9ms |
| | **xl** | **65.2ms** | **72.8ms** |

Pixeltable degrades most. The other two sent every query embedding to a
`compute-service` that, when this was measured, served one request at a time, and still
held lower; where Pixeltable's in-process path queues under eight clients was not
isolated.

## Hosted model

The agent with local generation swapped for one hosted model,
`nvidia/nemotron-3-super-120b-a12b` on OpenRouter's paid endpoint, identical for all
three. The swap is what is measured: a 6-line schema change on Pixeltable against a
29-line retry/backoff helper on the other two, counted like every other line here
(comments out, and the `attempts` field that only feeds this table not charged). `harness/bench_hosted.py` applies
the patches, fires 12 questions at 6 workers, reverts everything. Numbers in
`docs/hosted.json`.

| | ok | Wall | p50 | p95 | Retries | Lines |
|---|---|---|---|---|---|---|
| Supabase | 12/12 | 9.4s | 2.3s | 5.2s | 0 | 29 |
| Convex | 12/12 | 18.8s | 3.9s | 18.8s | 0 | 29 |
| Pixeltable | 12/12 | 36.6s | 8.4s | 34.1s | scheduler-internal | 6 |

In this run the retry code was not exercised: no leg recorded a retry. Provider
response time dominates the medians. The longest tail is Pixeltable's, and its cause
was not isolated: the configured request rate is far above 12 questions, so the
scheduler's pacing alone does not account for it.

The failure that code exists to catch is real and measured: the free pool returned 3
of 36 responses as HTTP 200 with an `error` field and no content
([hosted_probe.json](hosted_probe.json), keyed by model). A hand-written loop
inspects the body and retries that shape; a computed column evaluates it to a null
answer - the earlier free-pool run recorded five empty cells and 7/12 on Pixeltable
where both loops held 12/12. Free-pool saturation moves minute to minute, so those
counts are snapshots, not platform properties; what does not move is who wrote the
retry code and who could see inside the response.

## What these numbers are not

- **One laptop, one run, local models on their default devices** (which device each
  model ran on is in [METHODOLOGY.md](METHODOLOGY.md)). The laptop was also running
  other work, and load is not controlled; each tier records the host load average
  before and after it ran, as `host_load`. Read the gaps, not the milliseconds.
- **Two sets of library versions**, recorded in `benchmarks.json`: the harness env
  and the Pixeltable service env.
- **The xl corpus is still not a vector benchmark.** Nothing measures recall; the
  tiers answer whether the ordering survives a larger corpus, not what happens at a
  million rows.
- **Everything runs on one machine, the assumption most favourable to the two that
  need a second service.** Their 8.5 requests and 1.35 MB per video never leave the
  laptop. A proxy adding 20 or 80ms to every call was run four times at each level. A
  level publishes a number only when every one of its runs is slower than every run at
  0ms, which at four runs apiece is what the exact one-sided rank test at 0.025 reduces
  to ([roundtrip.json](roundtrip.json)):

  - supabase +20ms: did not resolve (n=4, 54.9-58.1s vs 52.2-59.8s at 0ms)
  - supabase +80ms: added 7.5s (n=4)
  - convex +20ms: did not resolve (n=4, 64.1-68.9s vs 52.6-82.6s at 0ms)
  - convex +80ms: did not resolve (n=4, 64.4-93.6s vs 52.6-82.6s at 0ms)

  One point resolves. The others overlap their own baseline: at those levels the spread
  between runs is larger than the delay being measured, so the sweep gives the shape of
  the cost and one size, on Supabase at 80ms. These runs were taken level by level,
  against the `compute-service` from before the fix above, so drift across the
  afternoon fell on the levels unevenly; `bench_roundtrip.py` now records each run's
  start time and the corpus it started against, and a sweep point no longer pools runs
  against two versions of the service. In a deployment neither edge runtime can reach
  this laptop's `compute-service` at all, so their ingest numbers stay a lower bound.
- **Not a cost comparison.**

## What survives the numbers

The line counts, file counts and orchestration hops are properties of the code; this
page is a property of one afternoon on one machine. Where the two disagree, say both.
