# Convex: video intelligence pipeline

Five tables, two vector indexes, three by_video indexes, seven TypeScript files, and an
external compute service.

## Written to Convex's own guidance

An earlier version ran one `ctx.runQuery` per search hit and one `ctx.runMutation` per
row. Convex documents the opposite: [most logic should be plain TypeScript
functions](https://docs.convex.dev/understanding/best-practices/), and separate `ctx.run*`
calls each run in their own transaction, so a loop of them loses atomicity. Following that
took this implementation from 458 lines to 378.

## Why the compute service

The Convex runtime cannot run ffmpeg, Whisper, CLIP or a local chat model, so every media
operation is an HTTP call to `../compute-service/`, which you operate.

Against the local backend `127.0.0.1:9000` works. Against a hosted deployment it does
not, because actions run on Convex's infrastructure rather than your machine: use a
tunnel or a deployed compute service.

## Setup

```bash
npm install
npx convex dev     # anonymous local backend, no account needed
npx convex env set COMPUTE_SERVICE_URL http://127.0.0.1:9000
```

That writes `convex/_generated/` (not committed) and prints two ports: `CONVEX_URL` for
the client and `CONVEX_SITE_URL` for HTTP actions. The contract routes are on the HTTP
actions port. On a hosted deployment those are `.convex.cloud` and `.convex.site`
respectively, and the compute service must be reachable from Convex's cloud, so
`127.0.0.1` will not do there.

## Known limits, stated rather than hidden

- An action cannot write to the database, so every write goes through a mutation.
  `videos.ts` is 106 of this implementation's 378 lines for that reason.
- `vectorSearch` returns ids and scores, so rows are fetched in a second query.
- `http.ts` is 46 lines that exist only because this benchmark's contract is REST.
- Processing lives in the ingest path; restoring per-row automatic processing means a
  scheduled action.

## What this benchmark does not use, and should be counted in Convex's favour

Reactivity is the reason most teams choose Convex, and a REST contract discards it
entirely: with the reactive client, `http.ts` disappears and the UI re-renders on write.
Transactional mutations, end-to-end types from schema to client, and the retry and
workflow components are all unused here. See [../docs/TRADEOFFS.md](../docs/TRADEOFFS.md).
