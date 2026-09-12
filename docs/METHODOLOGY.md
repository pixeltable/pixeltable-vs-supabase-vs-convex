# Methodology

What this benchmark measures, what it does not, and where it is tilted.

## What is compared

One application, three implementations, one contract:

| Operation | Request | Response |
|---|---|---|
| `POST /videos` | `{video, title}` | `{rows: [{...}]}` |
| `GET /videos` | | `{rows: [{video_title, duration_sec, scene_count}]}` |
| `POST /search/frames` | `{query, limit}` | `{rows: [{frame_url, frame_idx, video_title, similarity}]}` |
| `POST /search/transcripts` | `{query, limit}` | `{rows: [{transcript, video_title, start_sec, similarity}]}` |
| `POST /agent/query` | `{question}` | `{rows: [{answer, visual, spoken}]}` |

Defined in [`harness/api_contract.py`](../harness/api_contract.py). Paths differ per
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
`#` for Python, `//` and `/* */` for TypeScript, `--` for SQL. An earlier version of
this harness treated `#` as the only comment marker, so every `//` and `--` counted as
code. That inflated Supabase and Convex against Pixeltable, and fixing it lowered
their totals. Lock files are counted nowhere; `package.json`, `pyproject.toml`,
`tsconfig.json`, `config.toml` and `.env.example` are counted separately as config.

**Architecture.** Tables, views, vector indexes, foreign keys, database triggers,
orchestration hops, and hand-written HTTP routes are counted by pattern per
implementation, since Supabase and Convex are both TypeScript and express the same
concept differently. The patterns are in `PATTERNS` in `metrics.py`, readable and
arguable.

**Orchestration hops** counts `ctx.runMutation` / `ctx.runQuery` / `ctx.runAction` /
`scheduler.runAfter` in Convex, and `supabase.from()` / `.storage.` / `.rpc()` /
`PERFORM notify_edge_function` in Supabase. It is a proxy for how many places the
pipeline can fall apart between a row arriving and that row being searchable, so it
excludes pure HTTP dispatch, which is already counted as hand-written routes. That
exclusion applies to `convex/http.ts`, where every route is a `ctx.runAction` into the
function that does the work; counting those would charge Convex twice for one layer,
and Supabase has no equivalent file because each `Deno.serve` handler holds its own
logic. Convex's raw count is 22 and its pipeline count is 17.

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
| **Supabase** | Yes | `supabase start` applied all three migrations, seven Edge Functions served under `supabase functions serve`, three videos ingested, the `pg_net` triggers fired, 45/45 frames and 6/6 chunks embedded, `harness/test_equivalence.py` 10/10. Also typechecks clean under Deno 2.9.6. |
| **Convex** | No | Every error from `tsc --noEmit` traces to the missing `convex/_generated/`, which cannot be produced without an authenticated Convex deployment. That is itself a finding: Convex code does not typecheck, let alone run, until you have an account. |

Pixeltable and Supabase produced the same counts from the same fixtures: 3 videos, 45
frames (16 / 15 / 14, per video), 6 transcript chunks, and the same top-ranked video
for all five fixture queries. The suite that checks that is the same file with a
different `--impl`.

Scene counts differ, and should: Pixeltable uses PySceneDetect's content detector and
found 2 per video, while `compute-service` uses ffmpeg's `select='gt(scene,T)'` filter
and found 3 / 2 / 3. Same videos, different detectors. The harness asserts only that
each video has at least one scene, because requiring equality would be requiring two
different algorithms to agree.

No claim is made in this repo about behavior that was not observed. The Convex
implementation is written to the same contract and reviewed against the same bugs the
others had, but it has not been run, and this document will say so until it has.

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
   what the contract needed. The other two were written to be correct and idiomatic,
   not to be bad, but they were not written by their platforms' experts.

## Where Pixeltable came off worse

Also stated, for the same reason.

- `pixeltable/app.py` writes one HTTP route by hand. `add_insert_route` resolves its
  target model eagerly and fails on a model whose columns call a query, so the agent
  endpoint could not be declared. Reproduced on released 0.7.7.
- `pxtf.json.len()` raises an internal `AssertionError` on a stored Json column, in a
  plain select as well as in a computed column, so `scene_count` is a one-line UDF.
  Reproduced on released 0.7.7.
- Changing the return shape of a query changes the inferred type of any column that
  calls it, which is a `FATAL` schema difference that `pxt schema update` will not
  apply. The table has to be dropped. Reproduced on released 0.7.7.
- A destructive catalog reset leaves a running service holding stale table handles,
  and `pxt service update` reports "up to date" rather than restarting it. Observed on
  0.7.7.dev9; not retested on the release.

Minimal repros for the first two are in
[pixeltable/README.md](../pixeltable/README.md#known-limits-stated-rather-than-hidden).

## Fairness rules

- Each implementation follows its own platform's idioms. No platform is made to
  imitate another.
- Known limits are written into each implementation's README rather than left for a
  reader to discover.
- A change to the contract is a change to all three.
- `python harness/run_comparison.py` regenerates `docs/metrics.json`, and every number
  in the README and the scorecard comes from that file.
