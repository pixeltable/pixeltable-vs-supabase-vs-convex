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

The working rules live in [AGENTS.md](AGENTS.md): numbers come from
`harness/run_comparison.py`, `n/a` never renders as `0`, one contract across all three
implementations, and only observed behaviour gets claimed. Keep each implementation
idiomatic for its platform; the point is the contrast, not a strawman.

## Checks

`ci.yml` runs these on every push, in about a minute. They need nothing running:

```bash
ruff check pixeltable/ compute-service/ harness/ fixtures/
ruff format --check pixeltable/ compute-service/ harness/ fixtures/
python harness/run_comparison.py          # must leave docs/metrics.json unchanged
python -m pytest harness/test_metrics.py  # the measuring code has its own tests
cd supabase-app && deno lint supabase/functions/
cd convex-app && npx eslint convex/ && npx convex dev --once && npx tsc --noEmit
```

`live.yml` runs the rest on pull requests to main and nightly: it brings up all three
implementations plus the compute service, seeds the same fixtures into each, and runs
every suite below. Locally, Pixeltable is auto-discovered and the other two take a
`--base-url`:

```bash
python -m pytest harness/test_equivalence.py --impl pixeltable
python -m pytest harness/test_differential.py --compare pixeltable \
  --compare supabase=$SUPABASE_URL --compare convex=$CONVEX_SITE_URL --auth-token "$SECRET"
python -m pytest harness/test_resilience.py --compare pixeltable \
  --compare supabase=$SUPABASE_URL --compare convex=$CONVEX_SITE_URL --auth-token "$SECRET"
```

`harness/test_recovery.py` writes to the corpus and needs `--destructive`. Re-seed the
fixtures afterwards; none of the three exposes a delete route.
