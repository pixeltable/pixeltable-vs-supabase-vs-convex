# Working in this repo

Three implementations of one video intelligence application, plus the compute service
that two of them need. The value is the contrast, so the rules below protect it.

## Layout

```
pixeltable/app.py          the whole backend: schema, pipeline, agent, HTTP
supabase-app/              4 tables, 3 migrations, 7 Edge Functions
convex-app/                4 tables, 9 TypeScript files
compute-service/           ffmpeg, Whisper, CLIP, embeddings, chat over HTTP
harness/                   the contract, the equivalence suite, the measurements
fixtures/                  generated videos and the query set with expected answers
docs/                      methodology, journey, scorecard, metrics.json
```

## The contract

Five operations, defined in `harness/api_contract.py`, served by all three. Change it
and you change all three, plus the path map in `harness/conftest.py`.

## Rules

1. **Every number in the docs comes from `docs/metrics.json`.** Run
   `python harness/run_comparison.py` after any code change. Do not type a figure into
   a README by hand; if it cannot be measured, put it in `CLASSIFIED` in
   `harness/metrics.py` and label it hand-classified.
2. **Do not claim behavior you did not observe.** `docs/METHODOLOGY.md` records which
   implementations were executed and which were only typechecked. Keep it accurate.
3. **Each implementation stays idiomatic for its platform.** No strawmen. If one of
   them has a genuine limit, write it into that implementation's README rather than
   leaving a reader to find it.
4. **State what favours Pixeltable.** The "Where this is favourable to Pixeltable"
   section of the methodology exists so the comparison survives scrutiny. Add to it
   when a new choice tilts things.
5. **No API keys.** Every model runs locally so anyone can reproduce the benchmark.

## Style

Python: single quotes, 120 columns, type hints. TypeScript: named exports only.
No em dashes anywhere. `ruff check` and `ruff format --check` are configured in the
root `pyproject.toml` and are enforced in CI.

## The comparison point

`pixeltable/app.py` is 128 lines and is the entire backend. The same application is
731 lines on Supabase and 716 on Convex, because a table that computes its own
columns replaces the triggers, webhooks, schedulers, storage round trips, status
columns, and joins that the other two have to write.
