# Contributing

The most valuable contribution is telling us this benchmark is wrong about your
platform. Open an issue or a PR; corrections that shrink the gap get published.

We want to hear about:

- code that is not how your platform's engineers would write it;
- a capability of your platform the benchmark ignores;
- a claim in the docs that is overstated or true only under our specific choices.

## Rules

The working rules live in [AGENTS.md](AGENTS.md): numbers come from
`harness/run_comparison.py`, `n/a` never renders as `0`, one contract across all
three implementations, and only observed behaviour gets claimed.

## Checks

`ci.yml` runs on every push, needs nothing running:

```bash
ruff check pixeltable/ compute-service/ harness/ fixtures/
ruff format --check pixeltable/ compute-service/ harness/ fixtures/
python harness/run_comparison.py          # must leave docs/metrics.json unchanged
python -m pytest harness/test_metrics.py
cd supabase-app && deno lint supabase/functions/
cd convex-app && npx eslint convex/ && npx convex dev --once && npx tsc --noEmit
```

`live.yml` runs nightly and on pull requests: it stands up all three plus the
compute service and runs every suite. The local commands are in
[README.md](README.md#measure-and-test); `test_recovery.py` writes to the corpus,
needs `--destructive`, and wants a re-seed afterwards.
