# Methodology

## What We Measure

### Lines of Code (LOC)

Counts non-empty, non-comment lines in application source files.

**Included:**
- Application code (`.py`, `.ts`, `.sql`)
- Schema definitions
- Route handlers / Edge Functions
- Test files

**Excluded:**
- Generated code (`_generated/`, `__pycache__/`)
- Lock files (`uv.lock`, `package-lock.json`)
- Configuration files (`pyproject.toml`, `package.json`, `config.toml`)
- Environment files (`.env`, `.env.example`)
- Documentation (`README.md`, `AGENTS.md`)

### External Services

A service counts if it requires:
1. Creating an account
2. Obtaining an API key or token
3. The application cannot function without it

### Languages

Counts distinct programming languages required to build the application. SQL counts as a separate language when migrations or RPC functions must be hand-written.

### Developer Journey Scorecard

Assessed manually against 10 phases:

1. **Install & Setup** -- Time and steps from zero to first line of code
2. **Define Schema** -- Decisions required, language used, flexibility
3. **Ingest Data** -- Batch insert, auto-processing, error handling
4. **Add Embeddings** -- Automatic vs manual, retry, error tracking
5. **Semantic Search** -- Lines of code, languages, limitations
6. **Serve API** -- Lines to expose endpoints, auto-generated docs
7. **Dev Loop** -- Offline capable, hot reload, schema change workflow
8. **Deploy to Prod** -- Steps, commands, zero-downtime
9. **Schema Evolution** -- Model swap difficulty, downtime, rollback
10. **Monitor & Scale** -- Auto-scaling, GPU access, observability

Ratings:
- **Strong** -- Clear advantage; best-in-class for this phase
- **Okay** -- Functional but with notable friction
- **Weak** -- Significant pain; requires extensive workarounds
- **Gap** -- Not available or requires external tooling

## Fairness Principles

- All implementations use the same OpenAI models and API
- All implementations use the same fixture data
- All implementations expose the same HTTP API contract
- Each implementation follows its platform's idiomatic patterns
- We do not artificially inflate code in any implementation
- The comparison is updated when platforms ship relevant features

## Running Metrics

```bash
python harness/run_comparison.py
```

This generates `docs/metrics.json` with the full breakdown.
