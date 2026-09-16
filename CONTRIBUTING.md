# Contributing

The most valuable contribution is telling us this benchmark is wrong about your platform.

## If you work on Supabase or Convex

Open an issue or a PR. Corrections that shrink the gap get published, because a benchmark
that survives scrutiny is worth more than a flattering number.

Concretely, we want to hear about:

- code that is not how your platform's engineers would write it;
- a capability of your platform the benchmark ignores;
- a claim in the docs that is overstated or true only under our specific choices.

## Rules

1. **Never type a number into a doc.** Run `python harness/run_comparison.py`; every
   figure comes from `docs/metrics.json`, and CI fails if it goes stale.
2. **A metric with no pattern for a platform renders `n/a`, never `0`.**
3. **Change the contract and you change all three** implementations plus the path map in
   `harness/conftest.py`.
4. **Do not claim runtime behaviour you did not observe.** `docs/METHODOLOGY.md` records
   which implementations were actually executed.
5. Keep each implementation idiomatic for its platform. The point is the contrast, not a
   strawman.

## Checks

```bash
ruff check pixeltable/ compute-service/ harness/ fixtures/
ruff format --check pixeltable/ compute-service/ harness/ fixtures/
python harness/run_comparison.py
python harness/run_comparison.py --test --impl pixeltable --base-url http://127.0.0.1:PORT
```
