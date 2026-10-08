"""Combine one client's runs into aggregate.json: each metric's median across runs, with its min and max.

python aggregate.py results/2026-10-07/us-east-1
python aggregate.py results/2026-10-07/eu-west-1    # near-*.json: latency and reads only

Two corrections apply to runs recorded before bench.py fixed them, so the published numbers follow the method:
- a load row's throughput is its successes over at least the load window. Workers keep sending until the window
  closes, and older runs divided by the time to the last success, which overstates a target whose successes
  stopped early while its failures went on;
- a cold row is dropped when its target shares a deployment with an earlier cold target, which had already woken it.
"""

import json
import statistics
import sys
from pathlib import Path
from typing import Any

# Cold targets that run on the same deployment as an earlier one in the cold pass (bench.py skips them).
SHARES_DEPLOYMENT_WITH = {
    'Pixeltable Compute Route (background=True)': 'Pixeltable Compute Route',
    'Pixeltable Insert Route': 'Pixeltable Compute Route',
    'Cloudflare Workers (D1)': 'Cloudflare Workers',
}


def correct_load_window(run: dict) -> None:
    window = run.get('load_seconds', 15)
    for section in ('load_c50', 'load_c100'):
        for row in run.get(section, {}).values():
            if 'error' not in row and row.get('seconds', window) < window:
                row['seconds'] = window
                row['throughput_rps'] = round(row['successful_requests'] / window, 2)


def med(values):
    values = [v for v in values if isinstance(v, (int, float))]
    if not values:
        return None
    return {
        'median': round(statistics.median(values), 2),
        'min': round(min(values), 2),
        'max': round(max(values), 2),
        'runs': len(values),
    }


def per_target(runs, section, getters, one_run_by=None):
    """With one_run_by, every median comes from the run whose value of that field is the median.

    That keeps a row's fields from one run, so its successes, attempts and latencies agree.
    """
    names = sorted({n for r in runs for n in r.get(section, {})})
    out: dict[str, Any] = {}
    for name in names:
        rows = [r[section][name] for r in runs if name in r.get(section, {}) and 'error' not in r[section][name]]
        if not rows:
            out[name] = {'error': [r[section][name].get('error') for r in runs if name in r.get(section, {})]}
            continue
        out[name] = {field: med([get(row) for row in rows]) for field, get in getters.items()}
        if one_run_by:
            middle = sorted(rows, key=getters[one_run_by])[(len(rows) - 1) // 2]
            for field, get in getters.items():
                if out[name][field] is not None and isinstance(get(middle), (int, float)):
                    out[name][field]['median'] = round(get(middle), 2)
        errors: dict[str, int] = {}
        for run in runs:
            for kind, n in (run.get(section, {}).get(name, {}).get('errors') or {}).items():
                errors[kind] = errors.get(kind, 0) + n
        if errors:
            out[name]['errors_all_runs'] = errors
    return out


def lat(key):
    return lambda row: (row.get('latency') or row).get(key)


def main(day: Path) -> None:
    runs = [json.loads(p.read_text()) for p in sorted(day.glob('run-*.json')) or sorted(day.glob('near-*.json'))]
    colds = [json.loads(p.read_text()) for p in sorted(day.glob('cold-*.json'))]
    for run in runs:
        correct_load_window(run)
    for c in colds:
        for name in SHARES_DEPLOYMENT_WITH:
            c['cold'].pop(name, None)
    stat = {k: lat(k) for k in ('min_ms', 'p50_ms', 'mean_ms', 'p95_ms', 'p99_ms')}
    load = {
        'throughput_rps': lambda r: r.get('throughput_rps'),
        'error_rate': lambda r: r.get('error_rate'),
        'requests': lambda r: r.get('requests'),
        'successful_requests': lambda r: r.get('successful_requests'),
        'seconds': lambda r: r.get('seconds'),
        'effective_concurrency': lambda r: r.get('effective_concurrency'),
        'connections_refused_at_slot': lambda r: r.get('connections_refused_at_slot'),
        **stat,
    }
    media = {
        'videos_per_sec': lambda r: r.get('videos_per_sec'),
        **stat,
        'ack_p50_ms': lambda r: (r.get('ack') or {}).get('p50_ms'),
    }
    out = {
        'runs': [{'started': r['started'], 'finished': r.get('finished'), 'client': r['client']} for r in runs],
        'cold_runs': [
            {'started': c['started'], 'idle_minutes': c['idle_minutes'], 'client': c['client']} for c in colds
        ],
        'latency': per_target(runs, 'latency', stat),
        'reads': per_target(runs, 'reads', stat),
        'batch': per_target(runs, 'batch', {'rows_per_sec': lambda r: r.get('rows_per_sec')}),
        'load_c50': per_target(runs, 'load_c50', load, 'throughput_rps'),
        'load_c100': per_target(runs, 'load_c100', load, 'throughput_rps'),
        'media_decode': per_target(runs, 'media_decode', media),
        'media_persist': per_target(runs, 'media_persist', media),
        'cold': per_target(
            colds,
            'cold',
            {k: (lambda r, k=k: r.get(k)) for k in ('first_request_ms', 'fresh_connection_warm_ms', 'wake_ms')},
        ),
    }
    res: dict[str, Any] = {}
    for check in ('microburst_c350', 'sync_insert_c250', 'async_insert_c200'):
        rows = [r['resilience'][check] for r in runs if check in r.get('resilience', {})]
        statuses: dict[str, int] = {}
        for row in rows:
            for code, n in row['statuses'].items():
                statuses[code] = statuses.get(code, 0) + n
        res[check] = {
            'rps': med([r['rps'] for r in rows]),
            'p50_ms': med([r['latency'].get('p50_ms') for r in rows]),
            'statuses_all_runs': statuses,
            'requests_per_run': rows[0]['requests'] if rows else None,
            'concurrency': rows[0]['concurrency'] if rows else None,
        }
    bombs = [r['resilience']['decompression_bomb'] for r in runs if 'decompression_bomb' in r.get('resilience', {})]
    res['decompression_bomb'] = {
        'statuses': sorted({b['status'] for b in bombs}),
        'seconds': med([b['seconds'] for b in bombs]),
        'response': bombs[0]['response'] if bombs else None,
    }
    out['resilience'] = res
    (day / 'aggregate.json').write_text(json.dumps(out, indent=2))
    print('wrote', day / 'aggregate.json', len(runs), 'runs,', len(colds), 'cold passes')


if __name__ == '__main__':
    main(Path(sys.argv[1]))
