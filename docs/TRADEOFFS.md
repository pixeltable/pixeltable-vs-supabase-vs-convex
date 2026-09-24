# Tradeoffs

Which stack to pick, and under what conditions, priced by even swap: trade attributes
until one is equal across all three, then strike it out. Each swap names its price.

Numbers come from `docs/metrics.json`, `docs/benchmarks.json`, `docs/evolve.json` and
`docs/hosted.json`. Rows without numbers are structural facts of the code; `†` marks
the row this contract cannot exercise. Judgments are marked as judgments.

## The consequences table

| | Pixeltable | Supabase | Convex |
|---|---|---|---|
| App code you maintain | 123 | 306 | 426 |
| Plus the shared compute service | 0 | 278 | 278 |
| Files you open to read the backend | 1 | 7 | 7 |
| Services you operate | 1 | 2 | 2 |
| Install to a running local stack | `pip install` + `pxt init`, heavy deps | Docker, 12 containers | `npx convex dev`, no account |
| Orchestration hops | 2 | 13 | 9 |
| HTTP routes with a hand-written handler | 1 | 5 | 5 |
| Ingest call semantics | async job, polled | synchronous response | synchronous response |
| ffmpeg, Whisper, CLIP run in-platform | yes | no | no |
| Round trips to a second service per agent query | 0 | 3 | 3 |
| Concurrent search p50, 8 clients (xl) | 251.0ms | 53.2ms | 65.3ms |
| Add a derived column to live data | backfills in place* | migration + backfill script | migration action |
| Processing fires for writes from any client | yes | no, unless you add triggers | no, unless you add a scheduler |
| Derived value stays fresh on row update† | yes, recomputed | no, silent staleness | no |
| Embedding index knows its own model | yes | no, the dimension is the guard | no |
| Rows one similarity search can return | the corpus | the corpus | 256, `vectorSearch`'s documented ceiling |
| Per-cell error state | yes (`errormsg`, `errortype`) | no | no |
| Column lineage | expression per column, in the catalog | nothing recorded to draw | nothing recorded |
| Data versioning | per-table history and revert | PITR, branching, migrations | snapshot export/import |
| Request validation before handlers | derived from signature, 422 | 28 lines by hand | 42 lines by hand |
| Failed ingest becomes a listed row | no, insert rejected | error row, filtered out | error row, filtered out |
| Hosted-model pacing and retries | request-rate scheduler, 6-line swap | 29-line loop | 29-line loop |
| Realtime push to clients | no | yes | yes, and it is the core idea |
| Endpoints authenticated by default | no | **yes**, one config line | no |
| Row-level security | no | **yes**, enabled and verified | no |
| Vendor ships a conformance checker | no | **yes**, `db advisors` on a live database | **yes**, an ESLint plugin |
| Local UI | dashboard, with lineage graphs | Studio | dashboard |
| Operations | you run the process | managed | managed |
| Free tier | n/a, self-hosted | yes | yes |

\* A column whose value is a `@pxt.query` cannot be added to a table that already
exists. Ordinary computed columns backfill in place, and that is what the row claims.

† The contract has no UPDATE, so this row is structural, not measured. On the two
hand-backfilled platforms a title UPDATE leaves `title_embedding` serving vectors
computed from the old value until the backfill re-runs; Pixeltable recomputes on write,
so the staleness does not exist to be measured.

## The swaps

**Swap 1: equalise "services you operate".** Move the model work to a hosted API and
the compute service shrinks but does not vanish: three of its seven endpoints are
ffmpeg, with no hosted substitute. The row stays 1 / 2 / 2 - **it does not strike
out**, the most durable finding here: on Supabase and Convex, media processing lives
somewhere else, and the extra service, most of the hops and the base64 round trips
follow from it.

**Swap 2: equalise "realtime push".** Pixeltable has none; matching it is a polling
client or websocket layer you write. For an app whose clients need live updates, this
swap decides the question alone.

**Swap 3: equalise "authenticated endpoints".** Supabase's `withSupabase({ auth:
'secret' })` is one config line; RLS is enabled on all five tables. The other two are
open here, and equalising means a gateway plus a check you write. Per-tenant
`auth.uid()` policies are unwritten, so multi-tenant authorization is unmeasured.

**Swap 4: equalise "add a derived column to live data".** [EVOLVE.md](EVOLVE.md)
prices the migration-plus-backfill at two corpus sizes: 24 and 41 lines against
Pixeltable's 1. On the clock Supabase is cheapest at both corpus sizes: its DDL is
metadata-only and its script is quick, while Pixeltable's one step carries the backfill
and the index build together.

**Swap 5: equalise the app shape.** The contract is single-tenant, stateless,
request/response, write-once. A multi-tenant application with subscriptions inverts
the table: Convex gets reactivity back, Supabase gets Auth and RLS, Pixeltable has no
answer to either. This repo has not paid for a second contract, so the swap **cannot
be struck out** - the largest caveat on this page and the reason it recommends
conditionally.

Throughput is not in the swaps because [SCALE.md](SCALE.md) measures it: Supabase
ingests fastest, Convex reads and searches fastest.

**What survives every swap**: lines and files (129/1 against 302/7 and 425/7),
orchestration hops (3 against 13 and 9), and where media processing runs.

## The conditional recommendation

- **Pixeltable** when the workload is media-heavy and the pipeline is the product.
  The stronger reason is not the line count: adding a column backfills only that
  column, and a row inserted by anything at all gets processed. That compounds; a
  line-count difference does not.
- **Supabase** when you want Postgres and the things around it: realtime
  subscriptions, row-level security, a managed database your team knows. Media work
  will live in a second service.
- **Convex** when reactivity is the point. Its 425 lines here are mostly two taxes
  this contract imposes (`videos.ts` because an action cannot write directly,
  `http.ts` because we asked for REST); a REST-shaped benchmark is Convex's worst
  event and its install is the easiest of the three.
- **More than one.** Pixeltable as the media and retrieval layer behind a Supabase or
  Convex application is a coherent architecture.

## What this benchmark does not measure

Cost in dollars, managed operations, cold starts and p99, team familiarity, migration
cost. Any of these can outweigh the table above. The larger omission is that both
competitors are used here in a shape their vendors would not call typical; every line
below was checked by grep, so it is a statement about this repo, not the platforms.

### Supabase, as it is normally used

| | Used here? |
|---|---|
| Auth plus per-tenant RLS policies | **No.** RLS is enabled on all five tables and zero policies are written; every request runs on a service-role key that bypasses it. |
| Realtime | **No.** No `[realtime]` stanza, no publication entry, no `.channel(`. |
| PostgREST called directly | **No.** Every query goes through one Edge Function. |
| Storage policies, signed URLs, transforms | **No.** One public bucket. |
| `pg_cron`, `pg_net`, queues, triggers | **No.** Zero hits. |
| Branching, PITR | **No.** |

Auth plus RLS is the reason a large share of teams choose Supabase, and this contract
has no user, no tenant and no owned row.

### Convex, as it is normally used

| | Used here? |
|---|---|
| Reactive queries | **No, and by construction.** There is no client in the repo. |
| Optimistic updates | **No.** A reactive-client feature. |
| Scheduled functions and crons | **No.** No `ctx.scheduler`, no `crons.ts`. |
| Components (`@convex-dev/*`) | **No.** No `convex.config.ts`. |
| `searchIndex` | **No** in the app. Priced in [EVOLVE.md](EVOLVE.md), where it turns a 41-line change into a 1-line one. |
| Convex Auth | **No.** All five routes are unauthenticated. |
| `generateUploadUrl` | **No.** Frames go base64 through the compute service. |
| Transactional multi-table mutations | **Not as a design point.** Ingest splits writes across one `ctx.runMutation` per table. |

### Pixeltable, as it is normally used

This *is* the shape. What the contract leaves out for it is listed in
[METHODOLOGY.md](METHODOLOGY.md#pixeltable-capabilities-the-contract-leaves-out).
