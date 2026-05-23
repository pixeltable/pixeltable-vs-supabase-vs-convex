# AGENTS.md

Instructions for AI coding agents working with this repo.

## Project Overview

This is a platform comparison benchmark. Four implementations of the same multimodal knowledge base + agent app, built with Pixeltable, Supabase, Convex, and Modal.

## Structure

- `fixtures/` -- Shared test data used by all implementations
- `pixeltable/` -- Pixeltable implementation (Python)
- `supabase-app/` -- Supabase implementation (TypeScript + SQL)
- `convex-app/` -- Convex implementation (TypeScript)
- `modal-app/` -- Modal + pgvector implementation (Python + SQL)
- `harness/` -- Cross-platform test harness and metrics
- `docs/` -- Journey comparison, methodology, scorecard

## Key Constraint

All four implementations must expose the **same API contract** defined in `harness/api_contract.py`:

- `POST /upload` -- Upload text or image
- `POST /search` -- Semantic search
- `POST /agent/query` -- Agent chat with RAG
- `GET /documents` -- List documents

## When Making Changes

1. If you change the API contract, update ALL four implementations
2. After any code change, run `python harness/run_comparison.py` to update metrics
3. Keep implementations minimal -- the comparison value is in the contrast, not in feature completeness
4. Follow each platform's idiomatic patterns (don't write Python-style TypeScript or vice versa)

## Code Style

- **Pixeltable / Modal**: Python, single quotes, 120-char lines, type hints
- **Supabase**: TypeScript (Deno for Edge Functions), standard formatting
- **Convex**: TypeScript, Convex conventions (actions vs mutations vs queries)
