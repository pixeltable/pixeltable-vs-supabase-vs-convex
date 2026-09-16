# Tradeoffs

Which stack you should pick, and under what conditions. This uses the even-swap method:
build one table of consequences, then trade attributes off against each other until an
attribute is equal across all three and can be struck out. Each swap has to name a
price, which is what stops it being an argument dressed as arithmetic.

Numbers come from `docs/metrics.json`. Judgments are marked as judgments.

## The consequences table

| | Pixeltable | Supabase | Convex |
|---|---|---|---|
| App code you maintain | 128 | 254 | 383 |
| Plus the shared compute service | 0 | 252 | 252 |
| Files you open to read the backend | 1 | 5 | 7 |
| Services you operate | 1 | 2 | 2 |
| Orchestration hops | 3 | 12 | 9 |
| ffmpeg, Whisper, CLIP run in-platform | yes | no | no |
| Add a derived column to live data | backfills in place* | migration + backfill script | migration action |
| Processing fires for writes from any client | yes | no, unless you add triggers | no, unless you add a scheduler |
| Per-cell error state | yes (`errormsg`, `pxt errors`) | no | no |
| Data versioning | per-table history and revert | PITR, branching, migrations | snapshot export/import |
| Realtime push to clients | no | yes | yes, and it is the core idea |
| Endpoints authenticated by default | no | **yes**, one config line | no |
| Row-level security | no | **yes**, enabled and verified | no |
| Vendor ships a conformance checker | no | **yes**, `db advisors` on a live database | **yes**, an ESLint plugin |
| Operations | you run the process | managed | managed |
| Free tier | n/a, self-hosted | yes | yes |

\* With a caveat this repo found the hard way: adding a *query-backed* column to an
existing table fails today. See `pixeltable/README.md`.

## The swaps

**Swap 1: equalise "services you operate".** Supabase and Convex each need the compute
service because neither Deno nor the Convex runtime can execute ffmpeg. Swap the model
work to a hosted API (OpenAI embeddings, hosted Whisper) and the service shrinks, but it
does not vanish: three of its seven endpoints (`/extract-frames`, `/extract-audio`,
`/detect-scenes`) are ffmpeg and have no hosted-API substitute short of adding a
different vendor. Price of the swap: per-call cost, an API key, and no offline path.

After it, the row reads 1 / 2 / 2 still. **It does not strike out**, and that is the
single most durable finding in this repo: on Supabase and Convex, media processing lives
somewhere else. Everything downstream -- the extra service, most of the orchestration
hops, the base64 round trips -- follows from that one fact.

**Swap 2: equalise "realtime push".** Pixeltable has none here. To match Supabase or
Convex you would put a polling client or a websocket layer in front, and pay latency plus
the code to write it. Price: Pixeltable's 128 goes up, and the thing you build yourself
is what the other two ship. For an app whose clients need live updates, this swap is
expensive enough to decide the question on its own.

**Swap 3: equalise "authenticated endpoints".** Supabase's Edge Function declares
`withSupabase({ auth: 'secret' })`, and an unauthenticated request gets a 401 with a
machine-readable body naming the accepted auth modes. That is one config line. The
Pixeltable and Convex endpoints in this repo are open, and the harness has to send a key
only to Supabase. To equalise you would put a gateway in front of the other two and write
the check yourself. Price: code you did not have to write on Supabase.

Row-level security is now enabled on all five Supabase tables and an anonymous client
gets an empty result from a direct table read. That is a real protection Pixeltable and
Convex do not have here. Per-tenant policies against `auth.uid()` are still unwritten, so
multi-tenant authorization proper remains unmeasured, and for a multi-tenant product it is
the feature you would otherwise build. Another swap that does not strike out.

**Swap 4: equalise "add a derived column to live data".** Give Supabase and Convex the
migration plus backfill they need and the row becomes equal. Price: on 45 rows it is a
script you run once; on 45 million it is a maintenance window. This swap gets cheaper the
smaller your data and more expensive the larger it is, which is why it belongs in the
conditional answer rather than the headline.

**What survives every swap**: lines of code and files to open (128/1 against 254/6 and
383/7), orchestration hops (3 against 12 and 9), and where media processing runs.

## The conditional recommendation

**Pick Pixeltable** when the workload is media-heavy and the pipeline is the product:
video, audio, images, documents, embeddings, and a retrieval step over them. The whole
backend is one file, the processing is the schema, and nothing extra has to exist to run
ffmpeg. The stronger reason is not the line count: it is that adding a column to a
populated table backfills only that column, and a row inserted by anything at all gets
processed. That compounds; a 2x line difference does not.

**Pick Supabase** when you want Postgres and the things around it. If your clients need
realtime subscriptions, if you need row-level security for multi-tenancy, if you want an
auto-generated REST API you did not write, PITR, database branching, or simply a managed
database your team already knows how to operate, Supabase wins and this benchmark does
not measure most of the reasons why. Media work will live in a second service. That is
the trade.

**Pick Convex** when reactivity is the point. It also has the easiest install of the
three: `npx convex dev` gives you a working local backend with no account and no Docker.
Its 383 lines here are the worst showing in the table, and they are mostly two taxes this contract imposes: `videos.ts` (109 lines)
because an action cannot write to the database directly, and `http.ts` (46) because we
asked for REST. Build the same app with Convex's reactive client instead of five REST
endpoints and `http.ts` disappears, the client re-renders on write for free, and mutations
are transactional. A REST-shaped benchmark is Convex's worst event and you should discount
this column accordingly.

**Pick more than one.** These are not mutually exclusive. Pixeltable as the media and
retrieval layer behind a Supabase or Convex application is a coherent architecture, and
for a team that already runs one of those it is likely the cheaper answer than moving.

## What this benchmark does not measure

Cost in dollars. Auth and multi-tenancy. Realtime and reactivity. Managed operations,
uptime and on-call. Cold starts and p99 latency. Team familiarity. Migration cost from
whatever you run today. Any of these can outweigh everything in the table above.
