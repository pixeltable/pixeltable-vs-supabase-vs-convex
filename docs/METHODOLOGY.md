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
acknowledgement identifying the work (`IngestAck`): Pixeltable returns an asynchronous
job (`{id, job_url}`) to poll until done; Supabase and Convex return synchronously once
processing completes (`{rows: [{id, video_title, status}]}`). Paths differ per
platform, because Supabase serves Edge Functions under `/functions/v1`; the harness
holds a path map in `harness/conftest.py` rather than pretending the URLs match.

Every implementation uses the same models: `openai/clip-vit-base-patch32` for frames,
`sentence-transformers/all-MiniLM-L6-v2` for transcripts, Whisper `base.en` for
speech, and `Qwen2.5-1.5B-Instruct` for the agent. All local, all CPU. Same fixture
videos, same frame rate, same chunk length, same scene threshold.

## What is measured

`harness/metrics.py` reads the source and derives every number in the `Measured`
table. Nothing in that table is typed by hand.

**Lines of code.** Non-blank, non-comment, using the comment syntax of each language:
`#` for Python, `//` and `/* */` for TypeScript, `--` for SQL, `#` for TOML and for
`.env.example`, which is matched by name because its suffix says nothing. Counting a
comment marker as code inflates whichever language uses it, so each gets its own rule.
Lock files are counted nowhere; `package.json`, `pyproject.toml`, `tsconfig.json`,
`config.toml` and `.env.example` are counted separately as config.

**Architecture.** Tables, views, vector indexes, foreign keys, database triggers,
orchestration hops, and hand-written HTTP routes are counted by pattern per
implementation, since Supabase and Convex are both TypeScript and express the same
concept differently. The patterns are in `PATTERNS` in `metrics.py`, readable and
arguable.

A metric is reported only for a platform that has a pattern for it; anything else renders
as `n/a`. A structural zero printed as a measurement is not a measurement, and a metric
that only one platform has a pattern for flatters that platform. Pixeltable's hop count is
3, from the one route it writes by hand.

Two metrics are deliberately absent. A count of `.env.example` lines measures whether a
file exists, not what a deployment needs. A regex for external hosts cannot see a hostname
a library assembles, so it would report 0 for `app.py` while it downloads CLIP, MiniLM and
a Qwen GGUF from huggingface.co.

**Orchestration hops** counts `ctx.runMutation` / `ctx.runQuery` / `ctx.runAction` /
`scheduler.runAfter` in Convex, and `supabase.from()` / `.storage.` / `.rpc()` /
`PERFORM notify_edge_function` in Supabase. It is a proxy for how many places the
pipeline can fall apart between a row arriving and that row being searchable, so it
excludes pure HTTP dispatch, which is already counted as hand-written routes. That
exclusion applies to `convex/http.ts`, where every route is a `ctx.runAction` into the
function that does the work; counting those would charge Convex twice for one layer,
and Supabase has no equivalent file because each `Deno.serve` handler holds its own
logic. Convex's raw count is 14 and its pipeline count is 9.

## What is a judgment call

`CLASSIFIED` in `metrics.py` holds what cannot be derived from a regex: whether work
runs on insert, whether adding a column backfills incrementally, whether the platform
versions data, how many runtimes you operate. These are reported as hand-classified
and are labelled that way wherever they appear. Disagree with one and the line to argue
with is in the file.

## What was actually executed

Stated per implementation, because "it typechecks" and "it ran" are different claims.

| | Executed end to end | How |
|---|---|---|
| **Pixeltable** | Yes | Catalog created, three videos ingested over HTTP with background jobs, contract suite green against the live service |
| **compute-service** | Yes | All seven endpoints exercised against the fixture videos |
| **Supabase** | Yes | `supabase start` applied all five migrations, the `api` Edge Function served under `supabase functions serve`, three videos ingested, 45/45 frames and 6/6 chunks embedded, contract suite green. Also `deno lint` and `deno check` clean. |
| **Convex** | Yes | `npx convex dev` (anonymous local backend, no account), three videos ingested over its HTTP actions port, contract suite green, and `tsc --noEmit` clean against real generated code. |

All three produce the same counts from the same fixtures: 3 videos, 45 frames
(16 / 15 / 14, per video), 6 transcript chunks, and the same top-ranked video for all
five fixture queries.

Scene counts differ, and should: Pixeltable uses PySceneDetect's content detector and
finds 2 per video, while `compute-service` uses ffmpeg's `select='gt(scene,T)'` filter and
finds 3 / 2 / 3. Same videos, different detectors. The harness asserts only that each
video has at least one scene, because requiring equality would be requiring two different
algorithms to agree.

## The suites

[`harness/seed.py`](../harness/seed.py) loads the fixtures into any of the three, waiting
out Pixeltable's asynchronous job and the other two's synchronous pipelines alike.

| Suite | Tests | Needs | Asks |
|---|---|---|---|
| [`test_metrics.py`](../harness/test_metrics.py) | 29 | nothing running | does the measuring code measure what it claims? |
| [`test_equivalence.py`](../harness/test_equivalence.py) | 11 | one implementation | does it satisfy the contract, and rank the right video first? |
| [`test_differential.py`](../harness/test_differential.py) | 20 | all three | do they agree with each other? |
| [`test_resilience.py`](../harness/test_resilience.py) | 32 | all three | what do they do with a request they should refuse? |
| [`test_recovery.py`](../harness/test_recovery.py) | 6 | all three, `--destructive` | what does a failed or concurrent ingest leave behind? |

**Differential** runs three explicit tiers, because the three are not expected to agree on
everything. Identical: same videos listed, same top hit for every query. Tolerance:
durations within 0.1s, top-1 similarities within 0.05, transcript token overlap at least
90%, which covers the audio boundary. Known divergence: rank ordering below the top hit,
and the two scene detectors, recorded rather than asserted.

**Resilience** sends a missing field, a negative `limit`, a query that is a number, a body
that is an array. Its one assertion is that a malformed request never draws a 5xx, because
a 5xx tells a client the server broke and to retry, and retrying a malformed request can
only fail again. Which 4xx is recorded and not enforced: Pixeltable answers 422 from
Pydantic, the other two 400 from checks written by hand. It also pins what `limit` means:
omitted is 10, `0` is no rows, and a limit past the corpus returns the corpus. Those are
easy to get subtly wrong in a way no contract test notices.

**Recovery** is the only suite that writes, so it is behind `--destructive` and the
fixtures are re-seeded after a run. All three reject a zero-byte file, a truncated file,
random bytes with an `.mp4` extension and a path that does not exist, and none of them
lists the failure. What each leaves behind differs: Pixeltable rejects the insert, so
there is no row and the error is typed, while Supabase and Convex write the row before
processing, leave `status='error'` in the table, answer a bare 500, and filter that row out
of their list endpoint.

Two claims about Pixeltable's behaviour are checked by hand rather than by a suite, both
re-run against the live catalog:

- **Processing fires for any writer.** A plain `videos.insert([...])` in a Python shell,
  with the HTTP service not involved, produced 30 frames and 3 chunks, all columns
  computed, and the new frames were returned by a similarity query in the same session.
- **Adding a column backfills incrementally.** Adding one computed column to `Videos` and
  running `pxt schema update` took 1.4s: `media/videos` updated, the other three
  `unchanged`, and no transcription re-ran. Removing it again is refused as `DESTRUCTIVE`
  without an explicit flag. Priced against the other two in [EVOLVE.md](EVOLVE.md).

Throughput and latency are measured separately, over two tiers, in [SCALE.md](SCALE.md).
Pixeltable is last on both, by a margin that matters on ingest and by 19ms on search.

## Pixeltable capabilities the contract leaves out

Pixeltable only. The same accounting for Supabase and Convex, which is the longer list, is
in [TRADEOFFS.md](TRADEOFFS.md#what-this-benchmark-does-not-measure), along with the app
shape that decides all of it.

- **Hosted-model scheduling.** Eighteen provider modules (`openai`, `anthropic`, `gemini`,
  `groq`, `mistralai`, `together`, `voyageai`, `jina`, `fireworks`, `deepseek`, `nebius`,
  `openrouter`, `replicate`, `runwayml`, `twelvelabs`, `bfl`, `fal`, `fabric`) declare a
  resource pool. `RateLimitsScheduler` reads the limits a provider reports, keeps requests
  under them, and retries with exponential backoff up to ten times; `RequestRateScheduler`
  covers providers that report nothing, with three. Configuration is per provider
  (`openai.rate_limits`, `openai.max_connections`, `gemini.rate_limits`). Every model in
  this benchmark is local, so none of that runs, and none of it is measured. On Supabase
  and Convex the equivalent is code in the ingest path.
- **Iterators beyond two.** `FrameIterator` and `AudioSplitter` are used here.
  `VideoSplitter`, `DocumentSplitter`, `StringSplitter`, `TileIterator` and
  `ComponentIterator` also ship and go unmeasured.
- **The dashboard.** `pxt dashboard` serves a local UI with no deploy and no account:
  directories, tables and views with version and error counts, every column beside the
  expression that computes it, indexes with their metric and model, table and column
  lineage graphs, version history, and a data browser that renders frames and video.
  Supabase Studio and the Convex dashboard both ship too, and are also unmeasured; the
  part with no counterpart is the lineage, because the other two record nothing to draw.

One of them is measured rather than listed: adding a column to a populated table, in
[EVOLVE.md](EVOLVE.md). Each platform's change is applied, timed and reverted, and nothing
is committed to the implementations, so the line counts above keep measuring the
contract.

## Where this is favourable to Pixeltable

Stated so you do not have to find it yourself.

1. **The response envelope is `{"rows": [...]}`**, which is what Pixeltable's
   `FastAPIRouter.add_query_route` emits natively. Supabase and Convex build their
   JSON by hand either way, so it costs them nothing, but it was not chosen neutrally.
2. **Local models suit Pixeltable.** Running everything on CPU with no API key makes
   the benchmark reproducible, and it also removes a hosted-API dependency that
   Pixeltable would otherwise share with the other two. With OpenAI, all three would
   gain one external host; Pixeltable would still gain no orchestration.
3. **The app is media-heavy.** Video ingest, frame extraction and transcription are
   exactly what computed columns are for. A CRUD application with real-time
   subscriptions would read very differently, and Convex in particular would look
   much better.
4. **One author wrote all three.** The Pixeltable version had the benefit of knowing
   what the contract needed. The other two follow their vendors' documented guidance and
   pass their vendors' own checkers, but they were still not written by their platforms'
   experts.
5. **The contract is REST-shaped**, which is Pixeltable's native serving surface,
   Supabase's third-best (behind PostgREST and Realtime) and Convex's worst. Convex's
   `http.ts` is 90 lines that exist only because we asked for REST instead of using its
   reactive client, and choosing REST discards reactivity, the reason most teams pick it.
6. **`compute-service` is charged in full to both competitors** and is 46% of Supabase's
   total and 37% of Convex's. Roughly half of it would disappear behind a hosted
   embedding API; the ffmpeg half would not.
7. **Auth, row-level security, realtime and cost are entirely out of frame.** This repo
   runs on a service-role key and writes no policy. For a multi-tenant product those are
   decisive and Supabase and Convex both have answers where Pixeltable, here, does not.
   See [TRADEOFFS.md](TRADEOFFS.md).

## Each implementation is held to its vendor's own checker

Where a vendor ships a tool that inspects our code or our database and exits non-zero,
CI runs it, so "idiomatic" is a command a reader can re-run rather than a claim.

| | Tool | What it proves |
|---|---|---|
| Supabase | `deno lint`, `supabase db advisors --local` | Edge Function style; no security or performance errors on a live database |
| Convex | `@convex-dev/eslint-plugin`, `tsc --noEmit` | Their own best-practice rules, against real generated code |
| Pixeltable | `ruff` | Generic Python only. Pixeltable ships no conformance checker, so its claim to being idiomatic rests on prose and a reference app, not a command. |

That asymmetry is worth stating plainly: the sponsor's implementation is the one with the
weakest automated proof that it follows its own vendor's guidance.

## What a clean install gets you

Verified by cloning the published repo and following its own README, which is a different
claim from "it runs on the author's machine".

| | Clean install runs? |
|---|---|
| Supabase | Yes. `supabase start`, migrations, one Edge Function. |
| Convex | Yes. `npx convex dev` gives an anonymous local backend, no account. |
| compute-service | Yes. |
| Pixeltable | Yes, on released 0.7.8 with no patch and no source install. A fresh venv, `pip install -e .`, `pxt init`, `pxt schema update`: four tables and both embedding indexes. Then a video ingested and a transcript similarity query answered from it, so the check covers running the pipeline and not only creating it. |

`pyproject.toml` pins the two dependencies that decide the Pixeltable row.
`pixeltable[serve]` needs `sentence-transformers` 5.4 or
newer, where the index-dimension call it makes exists; a clean install of this app
resolves 5.7.0. An environment that already holds an older one keeps it, and that call
site has no version check, so the failure reads as a missing attribute rather than the
version error Pixeltable prints everywhere else. That is
[PXT-1421](https://pixeltable.atlassian.net/browse/PXT-1421), with the absent dependency
floor as [PXT-1422](https://pixeltable.atlassian.net/browse/PXT-1422). It is a confusing
message on a stale environment, not a broken release.

`transformers` is pinned under 5 for a different reason: 5.x returns a
`BaseModelOutputWithPooling` from CLIP's `get_image_features` rather than a tensor, which
`compute-service` does not handle, and Pixeltable's own source records that top-k results
are wrong there. All three implementations have to embed with the same semantics.

## Fairness rules

- Each implementation follows its own platform's idioms. No platform is made to
  imitate another.
- Known limits are written into each implementation's README rather than left for a
  reader to discover.
- A change to the contract is a change to all three.
- `python harness/run_comparison.py` regenerates `docs/metrics.json`, and every number
  in the README and the docs comes from that file.
