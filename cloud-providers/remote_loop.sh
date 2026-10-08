#!/bin/bash
# Runs on a runner VM. Both runners share one clock (START_EPOCH) so every cold pass follows 20 minutes in which
# neither client sends traffic. Per cycle, from its start:
#   us  +0:00 full run (must finish within 30 min)   +0:50 cold pass
#   eu  +0:52 latency and reads only                 +1:26 cold pass
# Cycles repeat RUNS times, GAP_HOURS apart, so the runs fall at different times of day. A cold pass also waits
# until 20 minutes after this runner's own last traffic, in case a run overran its slot; validate.py checks the
# silence across both runners.
set -u
cd "$(dirname "$0")"
set -a; source ~/shootout.env; set +a
export PIXELTABLE_API_KEY=$PXT_TOKEN  # the SDK batch test authenticates with it
ROLE=${ROLE:?us or eu} START_EPOCH=${START_EPOCH:?unix time of the first cycle}
RUNS=${RUNS:-3} GAP_HOURS=${GAP_HOURS:-4}
mkdir -p logs

at() {  # sleep until START_EPOCH + seconds
  local now; now=$(date +%s)
  (( $1 + START_EPOCH > now )) && sleep $(( $1 + START_EPOCH - now ))
}

quiet_since() {  # sleep until 20 minutes after the epoch second given
  local now; now=$(date +%s)
  (( $1 + 1200 > now )) && sleep $(( $1 + 1200 - now ))
}

for (( i = 0; i < RUNS; i++ )); do
  base=$(( i * GAP_HOURS * 3600 ))
  # One results folder per cycle, named for its start, so a cycle that crosses midnight stays together.
  export RESULTS_DAY; RESULTS_DAY=$(date -u -d @$(( START_EPOCH + base )) +%F)
  if [ "$ROLE" = us ]; then
    at $base;            python3.11 bench.py run  > logs/run-$i.log 2>&1
    last=$(date +%s); at $(( base + 3000 )); quiet_since $last
    python3.11 bench.py cold > logs/cold-$i.log 2>&1
  else
    at $(( base + 3120 )); python3.11 bench.py near > logs/near-$i.log 2>&1
    last=$(date +%s); at $(( base + 5160 )); quiet_since $last
    python3.11 bench.py cold > logs/cold-$i.log 2>&1
  fi
done
touch logs/done
