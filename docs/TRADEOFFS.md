# Tradeoffs

Which stack you should pick, and under what conditions. This uses the even-swap method:
build one table of consequences, then trade attributes off against each other until an
attribute is equal across all three and can be struck out. Each swap has to name a
price, which is what stops it being an argument dressed as arithmetic.

Numbers in this table come from `docs/metrics.json`, `docs/benchmarks.json`,
`docs/evolve.json` and `docs/hosted.json`. Rows without numbers are structural facts of
the code as written; `†` marks the one row this contract cannot exercise at all.
Judgments are marked as judgments.

## The consequences table

| | Pixeltable | Supabase | Convex |
|---|---|---|---|
| App code you maintain | 129 | 302 | 425 |
| Plus the shared compute service | 0 | 246 | 246 |
| Files you open to read the backend | 1 | 7 | 7 |
| Services you operate | 1 | 2 | 2 |
| Install to a running local stack | `pip install` + `pxt init`, heavy deps | Docker, 12 containers | `npx convex dev`, no account |
| Orchestration hops | 3 | 13 | 9 |
| HTTP routes with a hand-written handler | 1 | 5 | 5 |
| Ingest call semantics | async job, polled | synchronous response | synchronous response |
| ffmpeg, Whisper, CLIP run in-platform | yes | no | no |
| Round trips to a second service per agent query | 0 | 3 | 3 |
| Concurrent search p50, 8 clients (xl) | 119.5ms | 67.0ms | 65.2ms |
| Add a derived column to live data | backfills in place* | migration + backfill script | migration action |
| Processing fires for writes from any client | yes | no, unless you add triggers | no, unless you add a scheduler |
| Derived value stays fresh on row update† | yes, recomputed | no, silent staleness | no |
| Embedding index knows its own model | yes | no, the dimension is the guard | no |
| Per-cell error state | yes (`errormsg`, `errortype`) | no | no |
| Column lineage | expression per column, in the catalog | nothing recorded to draw | nothing recorded |
| Data versioning | per-table history and revert | PITR, branching, migrations | snapshot export/import |
| Request validation before handlers | derived from signature, 422 | ~28 lines by hand | ~46 lines by hand |
| Failed ingest becomes a listed row | no, insert rejected | error row, filtered out | error row, filtered out |
| Hosted-model pacing and retries | request-rate scheduler, 7-line swap | 36-line loop | 37-line loop |
| Realtime push to clients | no | yes | yes, and it is the core idea |
| Endpoints authenticated by default | no | **yes**, one config line | no |
| Row-level security | no | **yes**, enabled and verified | no |
| Vendor ships a conformance checker | no | **yes**, `db advisors` on a live database | **yes**, an ESLint plugin |
| Local UI | dashboard, with lineage graphs | Studio | dashboard |
| Operations | you run the process | managed | managed |
| Free tier | n/a, self-hosted | yes | yes |

\* Not every column. A column whose value is a `@pxt.query` cannot be added to a table
that already exists: `pxt schema update` answers `500 A query over model 'Frames' cannot
be serialized; bind it to a table first`. Ordinary computed columns backfill in place, and
that is what the row claims.

† The contract has no UPDATE, so this row is structural, not measured. What it claims:
on the two hand-backfilled platforms a title UPDATE leaves `title_embedding` serving
vectors computed from the old value until something re-runs the backfill - the index
cannot tell the data changed. Pixeltable recomputes the derived column on write, so the
staleness does not exist to be measured. The same holds for swapping the embedding
model: on the other two, nothing checks that the query was embedded by the model that
filled the column.

## The swaps

**Swap 1: equalise "services you operate".** Supabase and Convex each need the compute
service because neither Deno nor the Convex runtime can execute ffmpeg. Swap the model
work to a hosted API (OpenAI embeddings, hosted Whisper) and the service shrinks, but it
does not vanish: three of its seven endpoints (`/extract-frames`, `/extract-audio`,
`/detect-scenes`) are ffmpeg and have no hosted-API substitute short of adding a
different vendor. Price of the swap: per-call cost, an API key, and no offline path.

After it, the row reads 1 / 2 / 2 still. **It does not strike out**, and that is the
single most durable finding in this repo: on Supabase and Convex, media processing lives
somewhere else. The extra service, most of the orchestration hops and the base64 round
trips all follow from that one fact.

**Swap 2: equalise "realtime push".** Pixeltable has none here. To match Supabase or
Convex you would put a polling client or a websocket layer in front, and pay latency plus
the code to write it. Price: Pixeltable's 129 goes up, and the thing you build yourself
is what the other two ship. For an app whose clients need live updates, this swap is
expensive enough to decide the question on its own.

**Swap 3: equalise "authenticated endpoints".** Supabase's Edge Function declares
`withSupabase({ auth: 'secret' })`, and an unauthenticated request gets a 401 with a
machine-readable body naming the accepted auth modes. That is one config line. The
Pixeltable and Convex endpoints in this repo are open, and the harness has to send a key
only to Supabase. To equalise you would put a gateway in front of the other two and write
the check yourself. Price: code you did not have to write on Supabase.

Row-level security is enabled on all five Supabase tables and an anonymous client
gets an empty result from a direct table read. That is a real protection Pixeltable and
Convex do not have here. Per-tenant policies against `auth.uid()` are still unwritten, so
multi-tenant authorization proper remains unmeasured, and for a multi-tenant product it is
the feature you would otherwise build. Another swap that does not strike out.

**Swap 4: equalise "add a derived column to live data".** Give Supabase and Convex the
migration plus backfill they need and the row becomes equal. [EVOLVE.md](EVOLVE.md) runs
exactly that swap and prices it at two corpus sizes with a model-free control per
platform: 24 lines for Supabase and 53 for Convex against Pixeltable's 1. On the clock
the winner flips with corpus - Pixeltable is cheapest at 23 rows (0.96s) and Supabase
at 123 (3.51s), because Pixeltable's fused step scales with rows while the script's
fixed cost amortises. Two costs the clock misses cut both ways: Convex needs a second
migration to undo the first, and Pixeltable's running service answers 409 to inserts
until it is restarted.

The controls expose the slope behind that flip: Pixeltable's schema-minus-control
residual grew 0.4s to 4.4s between the two corpus sizes while Convex's push residual
stayed flat. That is still not the size where the structural claim bites - a backfill
script stays proportional to the table at a million rows and this corpus is not - so
the claim stays in the conditional answer rather than the headline.

**Swap 5: equalise the app shape.** Every swap above trades one attribute. This one trades
the premise. The contract is single-tenant, stateless, request/response and write-once:
`harness/api_contract.py` has no `PUT`, no `PATCH`, no `DELETE`, no user or tenant on any
row, no pagination, and a client that never uploads bytes. Give the benchmark a second
shape instead, a multi-tenant application with subscriptions, and the table inverts. Convex
gets reactivity back, which is the reason to choose it and which `http.ts` exists only to
throw away. Supabase gets Auth and RLS policies, which is the reason a large share of its
users are there at all. Pixeltable has no answer to either and would need one of them
underneath it.

Price of the swap: a second contract, three more implementations, and a second set of
suites. This repo has not paid it, so the swap **cannot be struck out** and the column it
would move is not measured anywhere here. That is the largest single caveat on everything
above, larger than any number in the table, and it is why this page recommends
conditionally rather than declaring a winner.

Throughput is not in the swaps because it has its own measurement:
[SCALE.md](SCALE.md), where Supabase ingests fastest and Convex searches fastest. If speed
at this scale is your binding constraint, that page decides it and this one does not.

**What survives every swap**: lines of code and files to open (129/1 against 302/7 and
425/7), orchestration hops (3 against 13 and 9), and where media processing runs.

## The conditional recommendation

**Pick Pixeltable** when the workload is media-heavy and the pipeline is the product:
video, audio, images, documents, embeddings, and a retrieval step over them. The whole
backend is one file, the processing is the schema, and nothing extra has to exist to run
ffmpeg. The stronger reason is not the line count: it is that adding a column to a
populated table backfills only that column, and a row inserted by anything at all gets
processed. That compounds; a line-count difference does not.

**Pick Supabase** when you want Postgres and the things around it. If your clients need
realtime subscriptions, if you need row-level security for multi-tenancy, if you want an
auto-generated REST API you did not write, PITR, database branching, or simply a managed
database your team already knows how to operate, Supabase wins and this benchmark does
not measure most of the reasons why. Media work will live in a second service. That is
the trade.

**Pick Convex** when reactivity is the point. It also has the easiest install of the
three: `npx convex dev` gives you a working local backend with no account and no Docker.
Its 425 lines here are the worst showing in the table, and they are mostly two taxes this
contract imposes: `videos.ts` (105 lines) because an action cannot write to the database
directly, and `http.ts` (90 lines) because we asked for REST and then had to validate
request bodies there by hand. Build the same app with Convex's reactive client instead of
five REST endpoints and `http.ts` disappears along with both taxes, the client re-renders
on write for free, and mutations are transactional. A REST-shaped benchmark is Convex's worst event and you should discount
this column accordingly.

**Pick more than one.** These are not mutually exclusive. Pixeltable as the media and
retrieval layer behind a Supabase or Convex application is a coherent architecture, and
for a team that already runs one of those it is likely the cheaper answer than moving.

## What this benchmark does not measure

Cost in dollars. Managed operations, uptime and on-call. Cold starts and p99 latency. Team
familiarity. Migration cost from whatever you run today. Any of these can outweigh
everything in the table above.

Then there is a larger omission, which is that both competitors are used here in a shape
their vendors would not call typical. Every line below was checked by grep against
`supabase-app/supabase/` and `convex-app/convex/`, so it is a statement about this repo,
not an opinion about the platforms.

### Supabase, as it is normally used

| | Used here? |
|---|---|
| Auth plus per-tenant RLS policies | **No.** RLS is enabled on all five tables and **zero policies are written**; every request runs on a service-role key that bypasses RLS. `CREATE POLICY` and `auth.uid()` appear nowhere outside a comment. |
| Realtime | **No.** No `[realtime]` stanza in `config.toml`, no table added to the `supabase_realtime` publication, no `.channel(` anywhere. |
| PostgREST called directly from a client | **No.** Every query goes through one Edge Function. PostgREST would serve `GET /videos` and both searches with no handler code at all. |
| Storage policies, signed URLs, image transforms | **No.** One public bucket, service-role uploads, `getPublicUrl`. |
| `pg_cron`, `pg_net`, queues, database triggers | **No.** Zero hits for each; `db_triggers` is a measured 0. |
| Branching, PITR | **No.** |

The first row is the one that matters. Auth plus RLS is the reason a large share of teams
choose Supabase at all, and this benchmark cannot express it: the contract has no user, no
tenant, and no owned row, so there is nothing for a policy to be about.

### Convex, as it is normally used

| | Used here? |
|---|---|
| Reactive queries | **No, and by construction.** There is no client in the repo: zero hits for `convex/react`, `useQuery`, `ConvexProvider`. A REST contract discards reactivity, which is why most teams pick Convex. |
| Optimistic updates | **No.** They are a reactive-client feature and there is no client. |
| Scheduled functions and crons | **No.** No `ctx.scheduler`, no `convex/crons.ts`. `harness/metrics.py` counts `scheduler.runAfter(` as an orchestration hop and matches nothing. |
| Components (`@convex-dev/*`) | **No.** No `convex.config.ts`, so none can be installed. The only `@convex-dev` dependency is their ESLint plugin. |
| `searchIndex` | **No** in the app. Priced separately in [EVOLVE.md](EVOLVE.md), where it turns a 53-line change into a 1-line one. |
| Convex Auth | **No.** All five routes are unauthenticated. |
| `generateUploadUrl` | **No.** Frames are base64'd through the compute service and uploaded server-side. |
| Transactional multi-table mutations | **Not as a design point.** Ingest splits writes across a separate `ctx.runMutation` call per table write, each its own transaction. |

### Pixeltable, as it is normally used

This *is* the shape. A multimodal pipeline with computed columns, indexes and a REST
surface is the thing Pixeltable is for, which is why it wins here. What the contract leaves
out for Pixeltable is listed in
[METHODOLOGY.md](METHODOLOGY.md#pixeltable-capabilities-the-contract-leaves-out): hosted
model scheduling, five of seven iterators, and the dashboard.
