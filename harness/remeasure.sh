#!/bin/sh
# Re-measure every timing artifact from empty stacks, in one sitting.
#
#     sh harness/remeasure.sh --reset
#     sh harness/remeasure.sh --reset --from sweep     # resume a run that stopped
#
# Needs all three stacks and compute-service running as their READMEs describe, with
# compute-service on :9000 started from compute-service/ as
# `python3 -m uvicorn app:app --host 0.0.0.0 --port 9000 ...`. Writes docs/benchmarks.json,
# docs/device.json, docs/evolve.json and docs/roundtrip.json; check_docs.py then says
# which doc cells moved.
#
# --reset is required because this empties all three local corpora: `supabase db reset`,
# an empty import over every Convex table, and a dropped and recreated Pixeltable
# directory. None of the three has a delete route, so there is no gentler way back to a
# known corpus, and a corpus nobody can account for is how xl once sat on 203 videos.
#
# Order is the design. Load on the measuring machine is not controlled, so the three
# platforms are interleaved within each tier rather than run one after another: drift in
# load then falls across platforms instead of on whichever ran last. The latency sweep
# interleaves levels and platforms within each round for the same reason. Every
# measurement records the host load average beside it.

set -eu

if [ "${1:-}" != "--reset" ]; then
    echo 'refusing to run without --reset: this empties all three local corpora' >&2
    exit 2
fi

# Stages, in order: bench, device, evolve (at 123 videos), sweep, evolve23. --from skips
# the stages before the one named, for a run that stopped partway; the corpus it resumes
# on is whatever the stopped run left, which every artifact records beside its numbers.
FROM=bench
if [ "${2:-}" = "--from" ]; then
    FROM=${3:?--from needs a stage: bench, device, evolve, sweep or evolve23}
fi
STAGES='bench device evolve sweep evolve23'
case " $STAGES " in *" $FROM "*) ;; *) echo "unknown stage: $FROM" >&2; exit 2 ;; esac
# True when STAGE comes at or after FROM.
due() { echo "$STAGES" | awk -v from="$FROM" -v stage="$1" '{for (i = 1; i <= NF; i++) {if ($i == from) f = i; if ($i == stage) s = i}} END {exit !(s >= f)}'; }

cd "$(dirname "$0")/.."
SUPABASE=http://127.0.0.1:54321
CONVEX=http://127.0.0.1:3211
# Read at run time and never written anywhere: the Edge Function checks the secret key.
SECRET=$(cd supabase-app && npx supabase status -o env 2>/dev/null | awk -F= '/^SECRET_KEY=/{gsub(/"/,"",$2);print $2}')
# `convex import` reads the format from the extension.
EMPTY="$(mktemp -d)/empty.jsonl"
: >"$EMPTY"

stamp() { echo "=== $* $(date -u +%H:%M:%S)"; }
# set -e stops at the first failing step; say so, rather than leaving a log that just ends.
trap 'rc=$?; [ "$rc" -eq 0 ] || stamp "failed with exit $rc"' EXIT

wait_for() {
    until curl -sf -o /dev/null -X POST "$1/embed-text" -H 'content-type: application/json' -d '{"texts":["x"]}'; do
        sleep 1
    done
}

compute_on() {
    pkill -f 'uvicorn app:app --host 0.0.0.0 --port' || true
    sleep 2
    # Keep-alive as in every launch: KEEP_ALIVE_SEC in compute-service/app.py.
    (cd compute-service && nohup python3 -m uvicorn app:app --host 0.0.0.0 --port "$1" --timeout-keep-alive 120 \
        >"${TMPDIR:-/tmp}/compute-$1.log" 2>&1 &)
    wait_for "http://127.0.0.1:$1"
}

reset_all() {
    stamp reset
    (cd supabase-app && npx supabase db reset)
    # Every table in convex-app/convex/schema.ts. Stored frame files stay in _storage,
    # unreferenced; nothing the contract lists can see them.
    for table in videos frames audioChunks scenes conversations; do
        (cd convex-app && npx convex import --table "$table" --replace -y "$EMPTY")
    done
    # A running service keeps handles to the dropped tables and answers TABLE_NOT_FOUND
    # until it restarts onto the recreated ones.
    (cd pixeltable && pxt drop-dir media -r -f && pxt schema update app.py media -f && pxt service restart media/api)
    PIXELTABLE=$(cd pixeltable && pxt service list 2>/dev/null | awk '/^media\/api/{print $2}')
}

seed() {
    python3 harness/seed.py --impl pixeltable --base-url "$PIXELTABLE" --tier "$1"
    python3 harness/seed.py --impl supabase --base-url "$SUPABASE" --auth-token "$SECRET" --tier "$1"
    python3 harness/seed.py --impl convex --base-url "$CONVEX" --tier "$1"
}

bench() {
    stamp "$1 tier"
    python3 harness/benchmark.py --impl pixeltable --base-url "$PIXELTABLE" --tier "$@"
    python3 harness/benchmark.py --impl supabase --base-url "$SUPABASE" --auth-token "$SECRET" --tier "$@"
    python3 harness/benchmark.py --impl convex --base-url "$CONVEX" --tier "$@"
}

compute_on 9000
PIXELTABLE=$(cd pixeltable && pxt service list 2>/dev/null | awk '/^media\/api/{print $2}')
if due bench; then
    reset_all
    seed small
    bench small --skip-ingest
    bench large
    bench xl
fi

if due device; then
    stamp "agent generation per device"
    python3 harness/bench_device.py --impl convex --base-url "$CONVEX"
fi

if due evolve; then
    stamp "evolve at 123 videos"
    python3 harness/bench_evolve.py --supabase-token "$SECRET"
fi

# The proxy takes :9000, where both consumers already point, and forwards to :9100.
if due sweep; then
    compute_on 9100
    for round in 1 2 3 4; do
        for level in 0 20 80; do
            stamp "sweep round $round +${level}ms"
            python3 harness/bench_roundtrip.py --impl supabase --base-url "$SUPABASE" --auth-token "$SECRET" \
                --add-latency-ms "$level"
            python3 harness/bench_roundtrip.py --impl convex --base-url "$CONVEX" --add-latency-ms "$level"
        done
    done
    compute_on 9000
fi

reset_all
seed small
seed large
stamp "evolve at 23 videos"
python3 harness/bench_evolve.py --supabase-token "$SECRET"
# bench_evolve's Pixeltable leg changes the schema under the running service.
(cd pixeltable && pxt service restart media/api)

rm -rf "$(dirname "$EMPTY")"
stamp done
