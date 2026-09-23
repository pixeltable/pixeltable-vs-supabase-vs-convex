# Methodology

What this benchmark measures, what it does not, and where it is tilted.

## What is compared

One application, three implementations, one contract:

| Operation | Request | Response |
|---|---|---|
| `POST /videos` | `{video, title}` | `{id, job_url?, video_title?, status?}` (`IngestAck`) |
| `GET /videos` | | `{rows: [{video_title, duration_sec, scene_count}]}` |
| `POST /search/frames` | `{query, limit}` | `{rows: [{frame_url, frame_idx, video_title, similarity}]}` |
| `POST /search/transcripts` | `{query, limit}` | `{rows: [{transcript, video_title, start_sec, similarity}]}` |
| `POST /agent/query` | `{question}` | `{rows: [{answer, visual, spoken}]}` |

Defined in [`harness/api_contract.py`](../harness/api_contract.py). Ingest returns an
`IngestAck`: Pixeltable returns a job to poll, the other two return synchronously once
processing completes. Paths differ per platform (Supabase serves under
`/functions/v1`); `harness/conftest.py` holds the path map.

Every implementation uses the same models: `openai/clip-vit-base-patch32` for frames,
`sentence-transformers/all-MiniLM-L6-v2` for transcripts, Whisper `base.en` for
speech, and `Qwen2.5-1.5B-Instruct` for the agent. All local, each on its library's
default device: MiniLM on MPS and CLIP and Whisper on CPU on both paths; Qwen on Metal
through Pixeltable's `llama_cpp` UDF and on CPU through `compute-service`, whose
`llama-cpp-python` offloads nothing unless asked. The agent timings carry that
difference. Same fixture videos, frame rate, chunk length and scene threshold.

Not one substrate, though. Supabase's local stack is Docker, which on the measuring Mac
is a Colima Linux VM, so its Edge Function reaches `compute-service` through
`host.docker.internal` across the VM boundary. Convex's local backend, Pixeltable and
`compute-service` run natively on the host, and Convex's calls stay on loopback.

## What is measured

`harness/metrics.py` reads the source and derives every number. Nothing is typed by
hand.

- **Lines of code.** Non-blank, non-comment, using each language's own comment
  syntax. Lock files and unavoidable toolchain manifests (`deno.json`,
  `eslint.config.js`) are counted nowhere; `package.json`, `pyproject.toml`,
  `tsconfig.json`, `config.toml` and `.env.example` are counted separately as config.
- **Architecture.** Tables, views, vector indexes, foreign keys, triggers,
  orchestration hops and hand-written routes are counted by pattern per
  implementation; the patterns are in `PATTERNS` in `metrics.py`, readable and
  arguable.
- **A metric with no pattern renders `n/a`, never `0`** - a structural zero printed
  as a measurement flatters whichever platform lacks the pattern.
- **Orchestration hops** counts `ctx.runMutation` / `ctx.runQuery` / `ctx.runAction` /
  `scheduler.runAfter` in Convex and `supabase.from()` / `.storage.` / `.rpc()` /
  `PERFORM notify_edge_function` in Supabase. It excludes pure HTTP dispatch
  (`convex/http.ts`), which is already counted as hand-written routes; counting both
  would charge Convex twice. Convex's raw count is 14, its pipeline count 9;
  Supabase's is 13.
- **HTTP routes written by hand** counts handler bodies, not route bindings.
  Pixeltable scores 1 (the `@api.post` for the agent); Supabase's `fetch` export
  dispatches five branches to five handlers and Convex's five `http.route` blocks
  each hold one, so both score 5.
- **Two metrics are deliberately absent.** An `.env.example` line count measures
  whether a file exists, not what a deployment needs, and an external-hosts regex
  cannot see a hostname a library assembles - it would report 0 for `app.py` while
  it downloads CLIP, MiniLM and a Qwen GGUF from huggingface.co.

`CLASSIFIED` in `metrics.py` holds what a regex cannot derive - whether work runs on
insert, whether adding a column backfills incrementally, how many runtimes you
operate. These are labelled hand-classified wherever they appear.

## What was actually executed

Stated per implementation, because "it typechecks" and "it ran" are different claims.

| | Executed end to end | How |
|---|---|---|
| **Pixeltable** | Yes | Catalog created, three videos ingested over HTTP with background jobs, contract suite green against the live service |
| **compute-service** | Yes | All seven endpoints exercised against the fixture videos |
| **Supabase** | Yes | `supabase start` applied all five migrations, the `api` Edge Function served behind Kong at :54321, three videos ingested, 45/45 frames and 6/6 chunks embedded, contract suite green; `deno lint` and `deno check` clean |
| **Convex** | Yes | `npx convex dev` (anonymous local backend), three videos ingested over HTTP actions, contract suite green, `tsc --noEmit` clean |

All three produce the same counts from the same fixtures: 3 videos, 45 frames
(16 / 15 / 14), 6 transcript chunks, the same top-ranked video for all five fixture
queries. Scene counts differ by design: Pixeltable uses PySceneDetect (2 per video),
`compute-service` uses ffmpeg's `select` filter (3 / 2 / 3), and the harness asserts
only that each video has at least one.

## The suites

[`harness/seed.py`](../harness/seed.py) loads the fixtures into any of the three.

| Suite | Needs | Asks |
|---|---|---|
| [`test_metrics.py`](../harness/test_metrics.py) | nothing running | does the measuring code measure what it claims? |
| [`test_equivalence.py`](../harness/test_equivalence.py) | one implementation | does it satisfy the contract, and rank the right video first? |
| [`test_differential.py`](../harness/test_differential.py) | all three | do they agree with each other? |
| [`test_resilience.py`](../harness/test_resilience.py) | all three | what do they do with a request they should refuse? |
| [`test_recovery.py`](../harness/test_recovery.py) | all three, `--destructive` | what does a failed or concurrent ingest leave behind? |

- **Differential** runs three tiers: identical (same videos, same top hit), tolerance
  (durations within 0.25s, top-1 similarities within 0.05, transcript overlap at
  least 80% - bounds fitted to two machines' ffmpeg/Whisper builds, recorded beside
  each constant), and known divergence (rank ordering below the top hit, the two
  scene detectors).
- **Resilience** asserts a malformed request never draws a 5xx, and pins `limit`:
  omitted is 10, `0` is no rows, past the corpus returns the corpus.
- **Recovery** is the only suite that writes, so it sits behind `--destructive` and
  the fixtures are re-seeded after. All three reject the four bad ingests and none
  lists the failure; Supabase and Convex leave a `status='error'` row they filter
  out of the list.

Three Pixeltable behaviours are checked by hand against the live catalog, not by a
suite: a plain `videos.insert` outside the HTTP service produced 30 frames and
3 chunks, all columns computed, and a similarity query returned the new frames;
`pxt schema update` backfills one added column without touching the rest and
refuses removal without `--allow-destructive` (the control in
[EVOLVE.md](EVOLVE.md)); and `pxt revert --steps 1` removed a column and kept the
rows, with `pxt history` showing the rollback as a new version.

## Beyond the suites

Measured in [SCALE.md](SCALE.md): `harness/benchmark.py` (reads, load),
`harness/bench_hosted.py` (the hosted swap: private daemon on `PXT_PORT`, per-cell
`errormsg`/`errortype` recorded before teardown, `--model` selects the endpoint,
`OPENROUTER_API_KEY` reaches each stack through its own config path and is never
written to the repo), `harness/probe_hosted.py` (the provider's raw response shapes),
`harness/bench_roundtrip.py` (requests and bytes across the compute-service
boundary, per video and per agent query; `--add-latency-ms` models a deployment
where the boundary stops being loopback; [roundtrip.json](roundtrip.json)),
`harness/render_summary.py` (`docs/summary.svg`, regenerated and diffed in CI).

## Pixeltable capabilities the contract leaves out

- **Hosted-model scheduling.** Hosted-provider UDFs declare a resource pool. The
  OpenRouter UDF the hosted tier calls runs under `RequestRateScheduler`: a configured
  request rate, with retries and exponential backoff; `RateLimitsScheduler` paces the
  providers that report their own limits. The local-model corpus never sees it; the
  hosted tier exercises it. On the other two the equivalent is request-path code
  ([hosted.json](hosted.json), `lines_written`).
- **Five of seven iterators** go unmeasured; this app uses `FrameIterator` and
  `AudioSplitter`.
- **The dashboard** (`pxt dashboard`) draws lineage graphs and version history; the
  part with no counterpart is the lineage, because the other two record nothing.

The same accounting for Supabase and Convex - the longer list - is in
[TRADEOFFS.md](TRADEOFFS.md#what-this-benchmark-does-not-measure). Adding a column to
a populated table is measured rather than listed: [EVOLVE.md](EVOLVE.md).

## Where this is favourable to Pixeltable

1. **The response envelope is `{"rows": [...]}`**, Pixeltable's native shape.
2. **Local models** remove a hosted dependency the other two would share with it.
3. **The app is media-heavy**, what computed columns are for; a CRUD app with
   subscriptions would read very differently.
4. **One author wrote all three**; the other two pass their vendors' checkers but
   were not written by their platforms' experts.
5. **The contract is REST-shaped** - Pixeltable's native surface, Convex's worst
   (`http.ts` is 90 lines that exist only because we asked for REST).
6. **`compute-service` is charged in full to both competitors** (the README's
   shared-compute row); a hosted embedding API removes about half, not the ffmpeg half.
7. **Auth, RLS, realtime and cost are out of frame** and decisive for a
   multi-tenant product; see [TRADEOFFS.md](TRADEOFFS.md).

## Each implementation is held to its vendor's own checker

| | Tool | What it proves |
|---|---|---|
| Supabase | `deno lint`, `supabase db advisors --local` | Edge Function style; no security or performance errors on a live database |
| Convex | `@convex-dev/eslint-plugin`, `tsc --noEmit` | Their own best-practice rules, against real generated code |
| Pixeltable | `ruff` | Generic Python only - the sponsor's implementation has the weakest automated proof of the three |

## What a clean install gets you

Verified by cloning the published repo and following its own README.

| | Clean install runs? |
|---|---|
| Supabase | Yes. `supabase start`, migrations, one Edge Function. |
| Convex | Yes. `npx convex dev`, anonymous local backend, no account. |
| compute-service | Yes. |
| Pixeltable | Yes, on released 0.7.8: fresh venv, `pip install -e .`, `pxt init`, `pxt schema update`, then an ingest and a transcript query. |

Two pins decide the Pixeltable row. `sentence-transformers>=5.4`: an environment that
already holds an older one keeps it, and `pxt schema check` fails with a missing
attribute rather than a version error ([PXT-1421](https://pixeltable.atlassian.net/browse/PXT-1421),
[PXT-1422](https://pixeltable.atlassian.net/browse/PXT-1422)). `transformers<5`:
5.x returns `BaseModelOutputWithPooling` from CLIP's `get_image_features`, which
`compute-service` does not handle.

## Fairness rules

- Each implementation follows its own platform's idioms. No platform is made to
  imitate another.
- Known limits are written into each implementation's README rather than left for a
  reader to discover.
- A change to the contract is a change to all three.
- `python harness/run_comparison.py` regenerates `docs/metrics.json`, and every
  number in the docs comes from that file.
