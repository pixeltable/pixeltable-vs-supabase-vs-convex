"""Check a day's results before they are published. Exits non-zero on any failure.

    python validate.py results/2026-10-07

- every run measured every target in every section (a failure counts, as a recorded error);
- every latency and read test took SAMPLES timed requests;
- every load window kept its requests in flight: summed request time over the load window is close to `c`, so the
  client was never the bottleneck (checked when under 1% of requests failed, since failures carry no latency);
- every cold pass followed COLD_IDLE_MINUTES in which neither client sent traffic.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

SAMPLES = 300
COLD_IDLE_MINUTES = 20
MIN_OCCUPANCY = 0.7  # the drain after the window closes lowers it; below this the client fell behind
SECTIONS = {
    'run': ('latency', 'reads', 'batch', 'load_c50', 'load_c100', 'media_decode', 'media_persist'),
    'near': ('latency', 'reads'),
}


def when(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def main(day: Path) -> None:
    problems: list[str] = []
    traffic: list[tuple[datetime, datetime]] = []
    colds: list[tuple[str, datetime]] = []
    for region_dir in sorted(p for p in day.iterdir() if p.is_dir()):
        region = region_dir.name
        files = sorted(region_dir.glob('run-*.json')) + sorted(region_dir.glob('near-*.json'))
        if len(files) < 3:
            problems.append(f'{region}: {len(files)} runs, need 3')
        names: dict[str, set[str]] = {}
        for f in files:
            d = json.loads(f.read_text())
            kind = f.name.split('-')[0]
            traffic.append((when(d['started']), when(d['finished'])))
            for section in SECTIONS[kind]:
                rows = d.get(section, {})
                names.setdefault(section, set()).update(rows)
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
        for f in files:
            d = json.loads(f.read_text())
            kind = f.name.split('-')[0]
            for section in SECTIONS[kind]:
                missing = names.get(section, set()) - set(d.get(section, {}))
                if missing:
                    problems.append(f'{region}/{f.name} {section}: no entry for {sorted(missing)}')
        for f in sorted(region_dir.glob('cold-*.json')):
            colds.append((f'{region}/{f.name}', when(json.loads(f.read_text())['started'])))
    for label, start in colds:
        last = max((end for begin, end in traffic if begin < start), default=None)
        if last is not None and (start - last).total_seconds() < COLD_IDLE_MINUTES * 60:
            problems.append(
                f'{label}: only {(start - last).total_seconds() / 60:.1f} idle minutes before the cold pass'
            )
    if problems:
        print('FAILED:\n' + '\n'.join(f'  - {p}' for p in problems))
        sys.exit(1)
    print(f'ok: {day.name}, {len(colds)} cold passes, every run complete and consistent')


if __name__ == '__main__':
    main(Path(sys.argv[1]))
