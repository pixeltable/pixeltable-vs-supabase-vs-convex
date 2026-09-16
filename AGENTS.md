# Working in this repo

Three implementations of one video intelligence application, plus the compute service
that two of them need. The value is the contrast, so these rules protect it.

Read [docs/METHODOLOGY.md](docs/METHODOLOGY.md) for the fairness rules and what is
measured, and [docs/TRADEOFFS.md](docs/TRADEOFFS.md) for the argument. Both are the
source of truth; do not restate them here.

## Rules that are easy to break

1. **Never type a number into a doc.** Everything comes from `docs/metrics.json` via
   `python harness/run_comparison.py`. Raw `wc -l` is not the measurement: the harness
   excludes blanks and comments, so pasting a file's line count inflates it.
2. **A metric with no pattern for a platform renders `n/a`, never `0`.** A structural
   zero presented as a measurement is the most attackable thing this repo can ship.
3. **Hold every implementation to its own vendor's documentation.** If a competitor's
   code is more verbose than their docs recommend, that is our bug, not their cost.
4. **Do not claim runtime behaviour you did not observe.** `METHODOLOGY.md` records which
   implementations were executed.
5. **A change to one implementation is a change to all three.** The contract, the fixtures
   and the models are shared, and a fix applied to one of them is a finding about the
   other two until you check.
6. **Timings come from `harness/benchmark.py` and land in `docs/benchmarks.json`.** Same
   rule as the line counts: nothing is typed in by hand, and a failed ingest is published
   rather than retried away.

## Style

Python: single quotes, 120 columns, type hints. TypeScript: named exports only.
No em dashes anywhere. `ruff check` and `ruff format --check` are configured in the root
`pyproject.toml` and enforced in CI.
