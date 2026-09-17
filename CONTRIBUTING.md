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
6. **Timings come from `harness/benchmark.py`**, land in `docs/benchmarks.json`, and
   publish their failures. See [docs/SCALE.md](docs/SCALE.md).

## Checks

These need nothing running, and CI gates on all of them:

```bash
ruff check pixeltable/ compute-service/ harness/ fixtures/
ruff format --check pixeltable/ compute-service/ harness/ fixtures/
python harness/run_comparison.py          # must leave docs/metrics.json unchanged
python -m pytest harness/test_metrics.py  # the measuring code has its own tests
cd supabase-app && deno lint supabase/functions/
cd convex-app && npx eslint convex/ && npx tsc --noEmit
```

These need the implementation running. Pixeltable is auto-discovered; the other two take
a `--base-url`:

```bash
python -m pytest harness/test_equivalence.py --impl pixeltable
python -m pytest harness/test_differential.py --compare pixeltable \
  --compare supabase=$SUPABASE_URL --compare convex=$CONVEX_SITE_URL --auth-token "$SECRET"
python -m pytest harness/test_resilience.py --compare pixeltable \
  --compare supabase=$SUPABASE_URL --compare convex=$CONVEX_SITE_URL --auth-token "$SECRET"
```

`harness/test_recovery.py` writes to the corpus and needs `--destructive`. Re-seed the
fixtures afterwards; none of the three exposes a delete route.
