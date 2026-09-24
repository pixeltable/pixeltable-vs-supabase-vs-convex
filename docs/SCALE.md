# Scale, measured

Two tiers, to test whether the ordering is a property of the platforms or of a small
corpus. Large is 20 videos, xl 100; footage per tier is `seconds_of_video` in the
artifact, at one frame per second. Each tier is ingested on top of the one before,
starting from the 3-video baseline, identically on all three, and measured over the
corpus it leaves (`corpus` in the artifact).

Reproduce:

```bash
python fixtures/videos/generate.py --tier large   # or --tier xl
python harness/benchmark.py --impl pixeltable --tier large
python harness/benchmark.py --impl supabase --base-url http://127.0.0.1:54321 --auth-token "$SECRET" --tier large
python harness/benchmark.py --impl convex --base-url http://127.0.0.1:3211 --tier large
```

Or every timing on this page and in [EVOLVE.md](EVOLVE.md) in one sitting, from empty
stacks, with the platforms interleaved so load drift falls across all three:

```bash
sh harness/remeasure.sh --reset   # empties all three local corpora first
```

Raw output is [`benchmarks.json`](benchmarks.json), which records the library
versions and the host load alongside the timings. Nothing below is typed by hand.

## Ingest

This run recorded no failed attempts. The attempt before it did not finish: an agent
query on Supabase's large tier returned a 500 when its Edge Function sent a request on
a pooled connection `compute-service` was closing. uvicorn drops an idle connection
after 5s by default, and under load the agent's calls landed about 5s apart. That was
this repo's configuration, so it was fixed (keep-alive now outlives the client's pool,
`KEEP_ALIVE_SEC` in `compute-service/app.py`) and the whole run started again from
empty stacks. A failed agent query is now recorded beside the timings rather than
stopping the tier.

**Faster than realtime** is footage seconds divided by wall seconds, because the
tiers hold different footage amounts. Higher is faster.

| | Tier | Wall time | Faster than realtime | Median video |
|---|---|---|---|---|
| Pixeltable | large | 77.4s | 7.80x | 3.5s |
| | **xl** | **496.8s** | **7.60x** | **4.8s** |
| Supabase | large | 55.4s | 10.90x | 2.4s |
| | **xl** | **248.1s** | **15.23x** | **2.4s** |
| Convex | large | 54.6s | 11.06x | 2.4s |
| | **xl** | **263.6s** | **14.33x** | **2.6s** |

Pixeltable is last at both tiers. That is one run per tier, so whether the gap grows
with the corpus is not something this table can say. Two asymmetries sit underneath,
neither measured separately: a different scene detector
per side (PySceneDetect in Python against ffmpeg's `select` filter in C) and
different frame work (a stored 320x180 still against base64 to object storage). And
the two that reach `compute-service` pay an average of 8.5 requests and 1.35 MB
per video across that boundary ([roundtrip.json](roundtrip.json)): loopback for
Convex, the Colima VM boundary for Supabase, and a network a deployment would
charge for.

These timings follow a fix to `compute-service`. Its endpoints were `async def` around
blocking ffmpeg and model calls, which runs them on the event loop and serialized every
request the two consumers fan out; they are now plain `def`, which FastAPI's
documentation prescribes for blocking work. That was this repo's bug and it cost only
the two competitors. The measuring machine was not quiet: each tier records the host
load average before and after it ran (`host_load`), and the three platforms were
interleaved within each tier so that load fell across all three rather than on one.

## Search

Ten queries, six passes, one untimed warm-up, over the corpus each tier leaves:
`corpus` in the artifact.

| | Tier | Frame search p50 | p95 | Transcript search p50 | p95 |
|---|---|---|---|---|---|
| Pixeltable | large | 43.8ms | 48.7ms | 18.6ms | 21.1ms |
| | **xl** | **54.5ms** | **64.1ms** | **20.8ms** | **23.4ms** |
| Supabase | large | 40.5ms | 64.6ms | 21.9ms | 32.6ms |
| | **xl** | **32.9ms** | **37.6ms** | **16.8ms** | **19.9ms** |
| Convex | large | 33.3ms | 37.1ms | 13.4ms | 18.6ms |
| | **xl** | **29.9ms** | **34.7ms** | **12.9ms** | **17.9ms** |

Pixeltable is last on frame search at both tiers and on transcript search at xl, but
read the size before the rank: every implementation's p50 is tens of milliseconds, and
part of each number is embedding the query, which all three do per request. This is an
ordering check, not a vector benchmark.

## The agent

The most expensive operation, and the one where the three differ most. Same model
weights everywhere: in Pixeltable's own process, behind `compute-service` for the other
two. Measured on the 3-video baseline, since the retrieval inside is a fixed top-4.

| | p50 | p95 |
|---|---|---|
| Pixeltable | 242.3ms | 283.4ms |
| Supabase | 4381.2ms | 5157.9ms |
| Convex | 4036.0ms | 5287.1ms |

Pixeltable answers fastest, and the device is most of why. Each library runs the model
on its default device: Pixeltable's `llama_cpp` UDF offloads to the GPU when there is
one, Metal on this Mac, and `llama-cpp-python` behind `compute-service` stays on CPU
unless asked. Timed alone, with the same weights, the agent's real prompts and nothing
else in the path, generation takes 4011.0ms on CPU at p50 and 210.4ms on Metal
([device.json](device.json), from `harness/bench_device.py`). What remains of the other
two's time is their own retrieval and three round trips to `compute-service` (embed for
frames, embed for transcripts, generate). On these numbers, `n_gpu_layers=-1` in
`compute-service` would close most of the gap; that was not run, since every model here
stays on its library's default.

## Reads

`GET /videos` list latency plus a real fetch of one returned `frame_url`. The fetch
exists because a local Supabase stack once emitted `kong:8000` URLs no client could
resolve; `test_equivalence.py` fetches one on every run as the regression guard.

| | Tier | `GET /videos` p50 | p95 | Frame fetch p50 | p95 |
|---|---|---|---|---|---|
| Pixeltable | small / 3 videos | 1.9ms | 2.0ms | 0.6ms | 2.4ms |
| | large / 23 | 2.2ms | 3.1ms | 0.6ms | 1.0ms |
| | **xl / 123** | **3.9ms** | **5.5ms** | **0.6ms** | **1.0ms** |
| Supabase | small / 3 videos | 4.1ms | 6.5ms | 2.3ms | 3.6ms |
| | large / 23 | 7.0ms | 10.4ms | 2.9ms | 9.7ms |
| | **xl / 123** | **7.9ms** | **10.6ms** | **2.8ms** | **8.6ms** |
| Convex | small / 3 videos | 2.0ms | 3.2ms | 0.4ms | 0.7ms |
| | large / 23 | 1.6ms | 4.9ms | 0.4ms | 0.8ms |
| | **xl / 123** | **2.1ms** | **10.8ms** | **0.4ms** | **0.8ms** |

Convex is fastest on the read path at large and xl, and on every frame fetch. Every
Supabase request passes the stack's Kong gateway and `withSupabase` auth verification,
which the other two do not run; that cost was not isolated. The frame fetches are not
byte-equal: Pixeltable serves its stored 320x180 still, the other two the full 640x360
JPEG.

## Under load

The same ten searches, eight clients in flight at once: degradation, not speed.

| | Tier | Concurrent p50 | p95 |
|---|---|---|---|
| Pixeltable | small | 116.7ms | 175.7ms |
| | large | 119.0ms | 266.8ms |
| | **xl** | **121.0ms** | **189.0ms** |
| Supabase | small | 51.1ms | 100.1ms |
| | large | 61.0ms | 103.0ms |
| | **xl** | **52.6ms** | **121.3ms** |
| Convex | small | 57.8ms | 97.1ms |
| | large | 55.4ms | 69.2ms |
| | **xl** | **57.2ms** | **71.3ms** |

Pixeltable degrades most. The other two send every query embedding to
`compute-service` and hold lower at every tier, and did so in this file's previous run
too, when that service still served one request at a time; where Pixeltable's
in-process path queues under eight clients was not isolated.

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

  - supabase +20ms: did not resolve (n=4, 49.9-51.1s vs 47.0-51.2s at 0ms)
  - supabase +80ms: added 8.1s (n=4)
  - convex +20ms: did not resolve (n=4, 51.1-54.9s vs 48.0-53.7s at 0ms)
  - convex +80ms: added 13.4s (n=4)

  At 80ms both resolve; at 20ms the delay added across the serial calls is smaller than
  the spread between baseline runs, so neither does. Supabase added less than the delay
  the proxy injected on its serial calls, which means some of it overlapped other work;
  Convex added more, and why was not isolated. The levels were interleaved within each
  of four rounds, and each run records its start time, host load and the corpus it
  started against, which grows by one ingest per run. In a deployment neither edge
  runtime can reach this laptop's `compute-service` at all, so their ingest numbers stay
  a lower bound.
- **Not a cost comparison.**

## What survives the numbers

The line counts, file counts and orchestration hops are properties of the code; this
page is a property of one afternoon on one machine. Where the two disagree, say both.
