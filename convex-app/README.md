# Convex: video intelligence pipeline

Five tables, two vector indexes, three by_video indexes, seven TypeScript files,
and an external compute service.

## Written to Convex's own guidance

Per [their best practices](https://docs.convex.dev/understanding/best-practices/):
batched writes (separate `ctx.run*` calls each run their own transaction), vector
hits hydrated in one query, plain helpers rather than `ctx.runAction`, explicit
table ids. Their ESLint plugin runs in CI: `npm run lint`.

## Why the compute service

The [default Convex runtime](https://docs.convex.dev/functions/runtimes) exposes no subprocess, so ffmpeg, Whisper, CLIP and
the local chat model run elsewhere and every media operation is an HTTP call to
`../compute-service/`. Bundling them into a `"use node"` action was not attempted. Against the local backend
`127.0.0.1:9000` works; on a hosted deployment actions run on Convex's
infrastructure, so use a tunnel or a deployed service.

## Setup

```bash
npm install
npx convex dev     # anonymous local backend, no account
npx convex env set COMPUTE_SERVICE_URL http://127.0.0.1:9000
```

Ports are chosen at startup; `CONVEX_SITE_URL` in `.env.local` is the HTTP-actions
base for every contract route.

## Known limits

- An action cannot write to the database, so every write goes through a mutation:
  `videos.ts` is 105 of this implementation's 425 lines for that reason.
- `vectorSearch` returns ids and scores; rows are fetched in a second query.
- `listVideos` filters to `status === "ready"`: ingest inserts the row before
  processing, and a failed media step leaves it behind.
- `http.ts` is 90 lines: 42 for REST bodies, the rest because argument validators
  run inside the function, so a bad body is a 500 unless the edge checks it.
- Processing lives in the ingest path; per-row automatic processing would take a
  scheduled action.

## What this benchmark does not use

Reactivity is the reason most teams choose Convex, and a REST contract discards it.
Absent by grep: `convex/react` / `useQuery`, `ctx.scheduler`, `convex.config.ts`
(so no components), `searchIndex` (priced in
[../docs/EVOLVE.md](../docs/EVOLVE.md)), Convex Auth, `generateUploadUrl`. Priced in
[../docs/TRADEOFFS.md](../docs/TRADEOFFS.md#what-this-benchmark-does-not-measure).
