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
| Pixeltable | large | 96.2s | 6.28x | 4.7s |
| | **xl** | **518.9s** | **7.28x** | **5.0s** |
| Supabase | large | 60.0s | 10.05x | 2.8s |
| | **xl** | **406.3s** | **9.30x** | **3.1s** |
| Convex | large | 53.8s | 11.22x | 2.6s |
| | **xl** | **279.2s** | **13.53x** | **2.7s** |

Pixeltable is last at both tiers. That is one run per tier, so whether the gap grows
with the corpus is not something this table can say. Supabase's xl ingest ran slower
per video than Convex's, through the same `compute-service` code; the difference is on
Supabase's side of the boundary, most plausibly its Colima VM under load, and was not
isolated. Two asymmetries sit underneath,
neither measured separately: a different scene detector
per side (PySceneDetect in Python against ffmpeg's `select` filter in C) and
different frame work (a stored 320x180 still against base64 to object storage). And
the two that reach `compute-service` pay an average of 8.5 requests and 1.53 MB
per video across that boundary ([roundtrip.json](roundtrip.json)): loopback for
Convex, the Colima VM boundary for Supabase, and a network a deployment would
charge for.

These timings follow three fixes to `compute-service`, each a cost this repo's code put
on the two competitors alone. Its endpoints were `async def` around blocking ffmpeg and
model calls, which serialized every request the two consumers fan out; they are now
plain `def`, which FastAPI's documentation prescribes for blocking work. Its chat model
stayed on CPU, `llama-cpp-python`'s default, while Pixeltable's UDF offloads to the GPU;
it now applies the same rule. And it squeezed speech through two lossy MP3 encodes at
16 kHz before Whisper heard it, where Pixeltable encodes once and cuts chunks without
re-encoding; it now does the same. Two later changes were not re-measured: chunks are
now cut from decoded PCM rather than MP3 packets, which on the fixture corpus made its
transcripts match Pixeltable's word for word, and a bearer-token check that is off on a
laptop. The measuring machine was not quiet: each tier records the host
load average before and after it ran (`host_load`), and the three platforms were
interleaved within each tier so that load fell across all three rather than on one.

## Search

Ten queries, six passes, one untimed warm-up, over the corpus each tier leaves:
`corpus` in the artifact.

| | Tier | Frame search p50 | p95 | Transcript search p50 | p95 |
|---|---|---|---|---|---|
| Pixeltable | large | 53.4ms | 75.9ms | 23.6ms | 33.5ms |
| | **xl** | **50.4ms** | **64.2ms** | **23.3ms** | **45.5ms** |
| Supabase | large | 28.9ms | 57.4ms | 16.6ms | 19.7ms |
| | **xl** | **32.6ms** | **39.1ms** | **16.4ms** | **19.8ms** |
| Convex | large | 26.0ms | 32.3ms | 13.3ms | 19.2ms |
| | **xl** | **29.9ms** | **36.0ms** | **13.1ms** | **19.8ms** |

Pixeltable is last on both searches at both tiers, but every implementation's p50 is tens of milliseconds, and part of each number is
embedding the query, which all three do per request. This is an ordering check, not a
vector benchmark.

## The agent

The most expensive operation, and the one where the three differ most. Same model
weights everywhere: in Pixeltable's own process, behind `compute-service` for the other
two. Measured on the 3-video baseline, since the retrieval inside is a fixed top-4.

| | p50 | p95 |
|---|---|---|
| Pixeltable | 302.4ms | 388.8ms |
| Supabase | 280.4ms | 381.3ms |
| Convex | 220.5ms | 349.7ms |

All three now run the model on Metal, and the gap this section used to report is gone:
Convex answers fastest and Pixeltable slowest, with the other two paying three round
trips to `compute-service` (embed for frames, embed for transcripts, generate) that
Pixeltable does not. That gap was the device. Timed alone, with the same weights, the
agent's real prompts and nothing else in the path, generation takes 3919.1ms on CPU at
p50 and 245.7ms on Metal ([device.json](device.json), from `harness/bench_device.py`),
and `compute-service` ran on CPU because `llama-cpp-python` offloads nothing unless
asked, while Pixeltable's UDF offloads whenever the build supports it. It now applies
the same rule. Why Pixeltable's path is slower once the device is equal, a table insert
and a read-back against three HTTP calls, was not isolated.

## Reads

`GET /videos` list latency plus a real fetch of one returned `frame_url`. The fetch
exists because a local Supabase stack once emitted `kong:8000` URLs no client could
resolve; `test_equivalence.py` fetches one on every run as the regression guard.

| | Tier | `GET /videos` p50 | p95 | Frame fetch p50 | p95 |
|---|---|---|---|---|---|
| Pixeltable | small / 3 videos | 5.4ms | 8.0ms | 1.0ms | 2.9ms |
| | large / 23 | 4.4ms | 5.3ms | 1.0ms | 2.8ms |
| | **xl / 123** | **4.4ms** | **6.2ms** | **0.8ms** | **1.3ms** |
| Supabase | small / 3 videos | 23.7ms | 33.5ms | 8.4ms | 23.7ms |
| | large / 23 | 6.4ms | 12.8ms | 3.6ms | 12.4ms |
| | **xl / 123** | **6.8ms** | **8.2ms** | **2.5ms** | **11.9ms** |
| Convex | small / 3 videos | 2.4ms | 2.7ms | 0.5ms | 1.0ms |
| | large / 23 | 2.4ms | 4.9ms | 0.4ms | 0.9ms |
| | **xl / 123** | **2.3ms** | **8.9ms** | **0.4ms** | **0.9ms** |

Convex is fastest on the read path at every tier. Every
Supabase request passes the stack's Kong gateway and `withSupabase` auth verification,
which the other two do not run; that cost was not isolated. The frame fetches are not
byte-equal: Pixeltable serves its stored 320x180 still, the other two the full 640x360
JPEG.

## Under load

The same ten searches, eight clients in flight at once: degradation, not speed.

| | Tier | Concurrent p50 | p95 |
|---|---|---|---|
| Pixeltable | small | 200.9ms | 332.6ms |
| | large | 139.1ms | 269.4ms |
| | **xl** | **251.0ms** | **609.5ms** |
| Supabase | small | 104.6ms | 243.9ms |
| | large | 69.1ms | 145.7ms |
| | **xl** | **53.2ms** | **96.4ms** |
| Convex | small | 66.2ms | 92.9ms |
| | large | 58.9ms | 77.0ms |
| | **xl** | **65.3ms** | **82.1ms** |

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
  need a second service.** Their 8.5 requests and 1.53 MB per video never leave the
  laptop. A proxy adding 20 or 80ms to every call was run four times at each level. A
  level publishes a number only when every one of its runs is slower than every run at
  0ms, which at four runs apiece is what the exact one-sided rank test at 0.025 reduces
  to ([roundtrip.json](roundtrip.json)):

  - supabase +20ms: did not resolve (n=4, 53.6-74.5s vs 53.5-75.2s at 0ms)
  - supabase +80ms: did not resolve (n=4, 67.8-75.9s vs 53.5-75.2s at 0ms)
  - convex +20ms: did not resolve (n=4, 57.3-67.4s vs 52.5-73.2s at 0ms)
  - convex +80ms: did not resolve (n=4, 68.4-77.4s vs 52.5-73.2s at 0ms)

  None resolves in this run. The baseline's own runs spread by more than the delay the
  proxy adds across the serial calls, even at 80ms, on a machine that was also serving
  another Pixeltable project through the same daemon. At this noise the sweep cannot
  size the boundary cost at all; the run before this one resolved both 80ms points, and
  its numbers are in this file's history. The levels were interleaved within each
  of four rounds, and each run records its start time, host load and the corpus it
  started against, which grows by one ingest per run. In a deployment neither edge
  runtime can reach this laptop's `compute-service` at all, so their ingest numbers stay
  a lower bound.
- **Not a cost comparison.**

## What survives the numbers

The line counts, file counts and orchestration hops are properties of the code; this
page is a property of one afternoon on one machine. Where the two disagree, say both.
