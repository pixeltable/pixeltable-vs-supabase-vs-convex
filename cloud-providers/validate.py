"""Check a day's results before they are published. Exits non-zero on any failure.

    python validate.py results/2026-10-07

- every run has every section, and measured every target in it (a failure counts, as a recorded error);
- every latency and read test took SAMPLES timed requests;
- every load window kept its requests in flight: summed request time over the load window is close to `c`, so the
  client was never the bottleneck (checked when under 1% of requests failed, since failures carry no latency);
- every client made COLD_PASSES cold passes, and none of them overlapped traffic from either client, other cold
  passes included, in the COLD_IDLE_MINUTES before it or while it ran. Passes in <day>-set-aside count as traffic.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

SAMPLES = 300
COLD_IDLE_MINUTES = 20
COLD_PASSES = 3
MIN_OCCUPANCY = 0.7  # the drain after the window closes lowers it; below this the client fell behind
# Every target a run must report, per section, whether it answered or failed. A target added to bench.py goes here
# too, so a run that skips it fails instead of publishing without it.
SERVED = (
    'Cloudflare Workers',
    'Cloudflare Workers (D1)',
    'Convex',
    'Modal',
    'Modal Async (.spawn)',
    'Neon Serverless PG',
    'Pixeltable Compute Route',
    'Pixeltable Compute Route (background=True)',
    'Pixeltable Insert Route',
    'Pixeltable Insert Route (background=True)',
    'Prisma Postgres',
    'Railway',
    'Railway Postgres',
    'Render',
    'Render Postgres',
    'Supabase PostgREST',
    'Turso libSQL',
    'Vercel',
)
DATABASES = (
    'Cloudflare Workers (D1)',
    'Convex',
    'Neon Serverless PG',
    'Prisma Postgres',
    'Railway Postgres',
    'Render Postgres',
    'Supabase PostgREST',
    'Turso libSQL',
)
# One cold target per deployment (aggregate.SHARES_DEPLOYMENT_WITH lists the routes that share one).
COLD = tuple(
    n
    for n in SERVED
    if n
    not in (
        'Modal Async (.spawn)',
        'Pixeltable Compute Route (background=True)',
        'Pixeltable Insert Route',
        'Pixeltable Insert Route (background=True)',
        'Cloudflare Workers (D1)',
    )
)
EXPECTED = {
    'run': {
        'latency': SERVED,
        'reads': (*DATABASES, 'Pixeltable Query Route'),
        'batch': (*DATABASES, 'Pixeltable Python SDK'),
        'load_c50': SERVED,
        'load_c100': SERVED,
        'media_decode': ('Modal', 'Railway', 'Render', 'Vercel'),
        'media_persist': (
            'Pixeltable Media Route',
            'Pixeltable Media Route (background=True)',
            'Railway + Postgres + object storage',
            'Render + Postgres + object storage',
        ),
        'resilience': ('async_insert_c200', 'decompression_bomb', 'microburst_c350', 'sync_insert_c250'),
    },
    'near': {'latency': SERVED, 'reads': (*DATABASES, 'Pixeltable Query Route')},
    'cold': {'cold': COLD},
}


def when(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def span(f: Path, d: dict) -> tuple[datetime, datetime]:
    """Start and end of a result's traffic. Cold passes saved before bench.py recorded 'finished' end at the save
    time in their file name (cold-HHMMSS.json), on the start's date or the day after."""
    start = when(d['started'])
    if 'finished' in d:
        return start, when(d['finished'])
    saved = datetime.strptime(f.stem.split('-')[1], '%H%M%S').time()
    end = datetime.combine(start.date(), saved, start.tzinfo)
    return start, end if end >= start else end + timedelta(days=1)


def main(day: Path) -> None:
    problems: list[str] = []
    traffic: list[tuple[str, datetime, datetime]] = []
    colds: list[tuple[str, datetime, datetime]] = []
    set_aside = day.parent / f'{day.name}-set-aside'
    for f in sorted(set_aside.glob('*/*.json')) if set_aside.is_dir() else []:
        traffic.append((f'set aside {f.parent.name}/{f.name}', *span(f, json.loads(f.read_text()))))
    for region_dir in sorted(p for p in day.iterdir() if p.is_dir()):
        region = region_dir.name
        files = sorted(region_dir.glob('run-*.json')) + sorted(region_dir.glob('near-*.json'))
        if len(files) < 3:
            problems.append(f'{region}: {len(files)} runs, need 3')
        for f in files:
            d = json.loads(f.read_text())
            kind = f.name.split('-')[0]
            traffic.append((f'{region}/{f.name}', *span(f, d)))
            for section, expected in EXPECTED[kind].items():
                rows = d.get(section, {})
                missing = set(expected) - set(rows)
                if missing:
                    problems.append(f'{region}/{f.name} {section}: no entry for {sorted(missing)}')
                for name, row in rows.items():
                    if 'error' in row:
                        continue
                    if section in ('latency', 'reads') and row.get('count') != SAMPLES:
                        problems.append(f'{region}/{f.name} {section} / {name}: {row.get("count")} samples')
                    if (
                        section.startswith('load_')
                        and row.get('successful_requests')
                        and row.get('error_rate', 1) < 0.01
                    ):
                        # Over the load window, not the full span: a straggler finishing after the window lengthens
                        # the span without the client falling behind. Drain time can lift this up to span / window.
                        window = d.get('load_seconds', 15)
                        busy = (row['latency']['mean_ms'] / 1000) * row['successful_requests']
                        occupancy = busy / window / row['effective_concurrency']
                        if not MIN_OCCUPANCY <= occupancy <= row['seconds'] / window + 0.05:
                            problems.append(f'{region}/{f.name} {section} / {name}: {occupancy:.0%} of c in flight')
        region_colds = sorted(region_dir.glob('cold-*.json'))
        if len(region_colds) < COLD_PASSES:
            problems.append(f'{region}: {len(region_colds)} cold passes, need {COLD_PASSES}')
        for f in region_colds:
            d = json.loads(f.read_text())
            colds.append((f'{region}/{f.name}', *span(f, d)))
            missing = set(EXPECTED['cold']['cold']) - set(d.get('cold', {}))
            if missing:
                problems.append(f'{region}/{f.name} cold: no entry for {sorted(missing)}')
    quiet = timedelta(minutes=COLD_IDLE_MINUTES)
    for label, start, end in colds:
        for other, begin, finish in traffic + colds:
            if other != label and begin < end and finish > start - quiet:
                idle = (start - finish).total_seconds() / 60
                problems.append(
                    f'{label}: {other} overlaps the pass'
                    if finish > start
                    else f'{label}: only {idle:.1f} idle minutes after {other}'
                )
    if problems:
        print('FAILED:\n' + '\n'.join(f'  - {p}' for p in problems))
        sys.exit(1)
    print(f'ok: {day.name}, {len(colds)} cold passes, every run complete and consistent')


if __name__ == '__main__':
    main(Path(sys.argv[1]))
