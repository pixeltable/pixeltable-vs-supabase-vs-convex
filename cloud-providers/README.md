# Cloud providers: free plans, timed

The harness, the code every target ran, and the raw results behind
[pixeltable.com/compare/cloud-providers](https://www.pixeltable.com/compare/cloud-providers): Neon, Supabase,
Turso, Prisma Postgres, Convex, Railway, Render, Vercel, Modal, Cloudflare and Pixeltable, timed the same way
from AWS.

Pixeltable sponsors this repo and wrote this harness, so every target, Pixeltable included, is timed and ranked
by the same rules, and every failure is published. Numbers live in `results/`, never in this file.

## What one run measures

| Test | What is timed | Samples per run |
|---|---|---|
| Latency | 5 untimed requests, then sequential requests on one kept-alive connection | 300 |
| Point reads | one seeded row read by primary key | 300 |
| Batch | 100 rows in one call | 5 calls |
| Load c=50, c=100 | `c` connections warmed with `c` untimed requests, then `c` in flight for 15 s; throughput is successes over the window, or to the last completion if later | one window |
| Media | 20 videos at concurrency 5: decode only, or decode, store and insert a row | 20 videos |
| Cold start | after 20 minutes with no traffic to any target, the first request on a new connection, then one on a second new connection; one route per deployment | 1 |
| Resilience (Pixeltable only) | a c=350 microburst, c=250 synchronous inserts, c=200 background inserts, a decompression bomb | 250 to 500 |

## What makes two rows comparable

- **One handler.** Every compute target serves the same function: read `{title, body}`, return
  `title_upper` and `summary`, store nothing (`targets/fastapi/main.py` and its ports). Pixeltable's compute
  route is the exception: it reads `title` and returns `title_upper` only (`targets/pixeltable/app.py`).
- **One row.** Every database stores `docs(id, title, body)` (`targets/sql/schema.sql`; Convex: `targets/convex`).
- **Warm connections.** HTTP and SQL targets both start every load window with open connections.
- **Three runs, four hours apart.** A published number is the median of three runs; the charts show the
  lowest and highest run beside it.
- **Two clients.** The full suite runs from `us-east-1`; latency, reads and cold start also run from
  `eu-west-1`, so edge platforms show what they are for. The two clients share one clock (`remote_loop.sh`),
  so every cold pass follows 20 minutes in which neither sends traffic.
- **Protocol stays visible.** A request over the Postgres wire protocol on an open connection is not an HTTP
  request through an API; the page tags each row and compares within a tag.

## Plans that ran

Each target ran on the plan below. Supabase, Render, Railway, Vercel and Cloudflare were read from the
provider's API or CLI before the run; Neon, Turso, Convex and Modal were confirmed by the account owner.

| Target | Plan | Note |
|---|---|---|
| Neon, Turso, Convex, Modal, Supabase, Render, Railway | Free (Modal: Starter) | Railway's services have Serverless on, so they sleep when idle |
| Prisma Postgres | Free | Its monthly operations ran out during an earlier run; the harness records `planLimitReached` |
| Vercel | Pro | The deployment lives in a Pro team; no Hobby scope was available |
| Cloudflare Workers and D1 | Workers Paid | |
| Pixeltable | Community (free) | |

## What failed or was left out

The harness records every failed request by kind. A load or media row whose median run failed more than 10%
of its requests is left out of its chart and listed with its errors; the rest stay, with their success rate.
A target that failed in every run is published as failed, with its error. Vercel's firewall answers 403 to a
single client address under load, and Pixeltable's gateway limits one API key to about 100 requests a second
per gateway pod: rows that hit either are labelled.

## Known issues in the 2026-10-07 results

- **Decode on Railway, Render and Modal used the first frame.** Their handlers call
  `container.seek(500000, stream=stream)`, which PyAV reads in the stream's time base (1/90,000 s for the
  fixture), so it seeks past the end of the 3.55 s clip and falls back to frame 0. Pixeltable decodes the frame at
  0.5 s, which is more work. The deployed code is kept as it ran; convert 0.5 s through `stream.time_base` before
  the next run.
- **Older raw files overstate two things, and `aggregate.py` corrects both.** Vercel's c=50 rows divided their
  successes by the time to the last success (about 10 s), while failures went on to the 15 s deadline. And three
  cold rows (`Pixeltable Compute Route (background=True)`, `Pixeltable Insert Route`, `Cloudflare Workers (D1)`)
  share a deployment with an earlier target in the pass, which had already woken it; they are dropped.

## Deploying the targets

The targets take unauthenticated writes and uploads, as the measured path does. Keep their URLs out of anything
public, and delete the deployments, or turn their writes off, between runs.

## Not measured

Global latency beyond the two client regions; Supabase's pause after a week idle and Turso's archive after
ten days; paid tiers other than those in the table; cost per request.

## Run it

1. Deploy each target from `targets/` and apply `targets/sql/schema.sql` to every database.
2. Fill `.env.example` into `~/shootout.env` on two runners (one in `us-east-1`, one in `eu-west-1`), with
   Python 3.11 and `pip install aiohttp asyncpg "psycopg[binary]" pixeltable==<the service's version>`: a client
   on another version than the service skews the SDK batch test (0.7.14 for the published results).
3. Copy this folder to `~/shootout` on both, pick a start time, and run
   `ROLE=us START_EPOCH=<unix time> ./remote_loop.sh` and `ROLE=eu START_EPOCH=<same time> ./remote_loop.sh`.
4. Copy `results/` back, run `python validate.py results/<day>`, which checks that every section is there, sample
   counts, that every load window kept its requests in flight, and that every cold pass followed 20 minutes with
   no traffic from either runner, other cold passes included (CI runs it on every committed day), then
   `python aggregate.py results/<day>/us-east-1` and the same for `eu-west-1`.

`results/<day>/<region>/` holds one JSON file per run (`run-*`, `near-*`, `cold-*`) and the `aggregate.json`
the page is generated from.
