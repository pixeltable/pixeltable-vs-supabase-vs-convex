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
and are labelled that way in the scorecard. Disagree with one and the line to argue
with is in the file.

## What was actually executed

Stated per implementation, because "it typechecks" and "it ran" are different claims.

| | Executed end to end | How |
|---|---|---|
| **Pixeltable** | Yes | Catalog created, three videos ingested over HTTP with background jobs, `harness/test_equivalence.py` 10/10 against the live service |
| **compute-service** | Yes | All seven endpoints exercised against the fixture videos |
| **Supabase** | Yes | `supabase start` applied all three migrations, the `api` Edge Function served under `supabase functions serve`, three videos ingested, 45/45 frames and 6/6 chunks embedded, `harness/test_equivalence.py` 10/10. Also typechecks clean under Deno 2.9.6. |
| **Convex** | Yes | `npx convex dev` (anonymous local backend, no account), three videos ingested over its HTTP actions port, `harness/test_equivalence.py` 10/10, and `tsc --noEmit` clean against real generated code. |

All three produced the same counts from the same fixtures: 3 videos, 45 frames
(16 / 15 / 14, per video), 6 transcript chunks, and the same top-ranked video for all
five fixture queries. The suite that checks that is the same file with a different
`--impl`.

Scene counts differ, and should: Pixeltable uses PySceneDetect's content detector and
found 2 per video, while `compute-service` uses ffmpeg's `select='gt(scene,T)'` filter
and found 3 / 2 / 3. Same videos, different detectors. The harness asserts only that
each video has at least one scene, because requiring equality would be requiring two
different algorithms to agree.

Two claims about Pixeltable's behaviour are checked by hand rather than by a suite, and
both were re-run against the live catalog:

- **Processing fires for any writer.** A plain `videos.insert([...])` in a Python shell,
  with the HTTP service not involved, produced 30 frames and 3 chunks, all columns
  computed, and the new frames were returned by a similarity query in the same session.
- **Adding a column backfills incrementally.** Adding one computed column to `Videos` and
  running `pxt schema update` took 1.4s: `media/videos` updated, `media/frames`,
  `media/chunks` and `media/conversations` each reported `unchanged`, and no transcription
  re-ran. Removing it again is refused as `DESTRUCTIVE` without an explicit flag.

All three run live at once for `harness/test_differential.py` (20 tests) and
`harness/test_resilience.py` (32 tests), and `harness/test_metrics.py` (27 tests) checks
the measuring code itself against fixtures with known counts. Where a claim is about
runtime behaviour, it comes from the table above.

Seeding fixture videos across any implementation is managed by
[`harness/seed.py`](../harness/seed.py), accommodating Pixeltable's asynchronous job polling
and the synchronous pipelines of Supabase and Convex.

In addition to single-platform contract testing in `test_equivalence.py`,
[`harness/test_differential.py`](../harness/test_differential.py) tests live implementations
against each other across three explicit tiers:
- **Identical**: same videos listed and same top hit for all search queries.
- **Tolerance**: durations within 0.1s, top-1 similarities within 0.05, and transcript token
  overlap of at least 90% (accounting for audio boundary variations).
- **Known divergence**: rank ordering below the top hit and differing scene counts between
  PySceneDetect and ffmpeg scene filters are recorded rather than asserted.

[`harness/test_resilience.py`](../harness/test_resilience.py) sends the requests the
contract does not describe: a missing field, a negative `limit`, a query that is a number,
a body that is an array. Its one assertion is that a malformed request never draws a 5xx,
because a 5xx tells a client the server broke and to retry, and a retry of a malformed
request can only fail again. Which 4xx is recorded and not enforced: Pixeltable answers
422 from Pydantic, the other two 400 from checks written by hand.

It also pins the semantics `limit` has to have. Omitted means 10, `0` means no rows, and a
limit past the corpus returns the corpus. Those are easy to get subtly wrong in a way no
contract test notices: `limit || 10` in TypeScript turns a request for zero rows into a
request for ten, and Convex's `vectorSearch` rejects a limit below 1, so clamping into
range silently answers a request for zero rows with one.

Throughput and latency are measured separately, over a 20-video tier, in
[SCALE.md](SCALE.md). Pixeltable is the slowest of the three on both.

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
6. **`compute-service` is charged in full to both competitors** and is 47% of Supabase's
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

The Pixeltable row is the one that was checked hardest, because this repo carried the
opposite claim, and `pyproject.toml` now pins the two dependencies that decide it. `pixeltable[serve]` needs `sentence-transformers` 5.4 or newer and a clean
install resolves 6.0.1, where everything works. An environment that already holds an older
one keeps it, and the code path that resolves an index's dimension then calls a method
that version does not define, so the failure reads as a missing attribute rather than the
version error Pixeltable prints everywhere else. That is PXT-1419, and it is a confusing
message on a stale environment, not a broken release.

## Fairness rules

- Each implementation follows its own platform's idioms. No platform is made to
  imitate another.
- Known limits are written into each implementation's README rather than left for a
  reader to discover.
- A change to the contract is a change to all three.
- `python harness/run_comparison.py` regenerates `docs/metrics.json`, and every number
  in the README and the scorecard comes from that file.
