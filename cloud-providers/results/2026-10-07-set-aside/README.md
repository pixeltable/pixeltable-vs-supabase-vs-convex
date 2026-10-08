Results left out of the published 2026-10-07 data, kept as the record.

- `eu-west-1/cold-233107.json`: this cold pass followed 18.8 idle minutes, not the method's 20, because the eu-west-1
  latency run before it overran its slot. `validate.py` flagged it; a replacement pass ran at 01:32 UTC after 20
  silent minutes.
