# Convex Implementation

> **434 lines of TypeScript. 1 language. 2 external services. 2 env vars.**

## Prerequisites

- Node.js 18+
- GitHub account (for Convex auth)
- `OPENAI_API_KEY`

## Setup (4 steps)

```bash
npm install                    # 1. Install deps
npx convex dev                 # 2. Create project + sync schema (GitHub login)
# Set OPENAI_API_KEY in Convex dashboard  # 3. Add env var
npm test                       # 4. Run tests
```

## What Happens at Each Phase

### Phase 1: Install

`npx convex dev` handles project creation, schema sync, and code generation. Requires GitHub login and internet connection.

### Phase 2: Schema

TypeScript schema with vector index:

```typescript
documents: defineTable({
  content: v.string(),
  embedding: v.array(v.float64()),
  ...
}).vectorIndex('by_embedding', { vectorField: 'embedding', dimensions: 1536 })
```

Must declare dimensions upfront. Auto-syncs on file save.

### Phase 3: Ingest

Insert via mutation, but embedding requires a separate action (external API calls not allowed in mutations).

### Phase 4: Embed

Manual OpenAI call inside an action. Must schedule or trigger for each document.

### Phase 5: Search

Vector search only in actions (not queries/mutations). Two-step: `ctx.vectorSearch()` returns IDs, then `ctx.runQuery()` loads full docs. Hard 256-result limit.

### Phase 6: Serve

`convex/http.ts` maps HTTP routes to actions/queries. Deploy with `npx convex deploy`.

### Phase 7: Dev Loop

`npx convex dev` provides continuous sync. No offline mode -- always requires internet.

## Architecture

```
convex/
  ├── schema.ts          defineTable + vectorIndex
  ├── documents.ts       mutations + internal queries
  ├── upload.ts          action: OpenAI embed + store
  ├── search.ts          action: OpenAI embed + vectorSearch + load
  ├── agent.ts           action: embed + search + OpenAI chat
  └── http.ts            HTTP router (4 routes)
```

## File Map

| File | Purpose | Lines |
|------|---------|-------|
| `convex/schema.ts` | Schema + vector index definition | 22 |
| `convex/documents.ts` | CRUD mutations + internal queries | 56 |
| `convex/upload.ts` | Upload action (embed + insert) | 66 |
| `convex/search.ts` | Search action (embed + vectorSearch) | 37 |
| `convex/agent.ts` | Agent action (RAG + chat) | 58 |
| `convex/http.ts` | HTTP route mappings | 63 |

## Run Tests

```bash
npx convex dev              # must be running
npm test                    # vitest
```

## Known Limitations

- Vector search only in actions (not queries/mutations)
- 256-result limit on vector search
- No offline development
- Manual embedding on every insert
- No per-cell error tracking
- Re-embedding on model swap requires a manual migration action
