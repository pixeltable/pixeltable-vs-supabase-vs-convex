#!/usr/bin/env python3
"""Assert the published docs quote the committed measurement artifacts.

    python harness/check_docs.py

docs/metrics.json has a regenerate-and-diff check in CI; docs/benchmarks.json and
docs/evolve.json had none, and the tables quoting them drifted to numbers from a
different run without anyone noticing - including a 'no failed attempts' claim the
artifact contradicted. This formats every published table cell the way the doc renders
it and fails if the cell is absent. A prose claim that disagrees with the artifact is
not checkable this way; the tables are.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / 'docs'

IMPLS = ('pixeltable', 'supabase', 'convex')

CONSUMERS = ('supabase', 'convex')
SWEEP_LEVELS = ('20', '80')
# The proxy sleeps --add-latency-ms before each forwarded request and ingest is synchronous
# on both consumers, so a level's added wall time should land near requests x added ms.
# Under prediction means some of the delay overlapped; far over it is time the proxy did
# not inject, which is not the boundary cost the sweep claims to report. The points that
# agree sit at 0.8-0.9x, so 1.5x is slack of the same order as the agreement itself.
SWEEP_RATIO_CEILING = 1.5
# With n>=2 the spread is the only evidence the median is reproducible. A quarter of the
# median is already wider than the disagreement the consistent points show; past that the
# point is a range, and a range is not a number to publish.
SWEEP_SPREAD_FRACTION = 0.25


def benchmarks_cells(b: dict) -> list[str]:
    cells = []
    for impl in IMPLS:
        for tier in ('large', 'xl'):
            entry = b[impl][tier]
            i = entry['ingest']
            cells.append(f'| {i["wall_sec"]:.1f}s | {i["realtime_factor"]:.2f}x | {i["median_video_sec"]:.1f}s |')
            s = entry['search']
            cells.append(
                f'| {s["frames"]["p50_ms"]}ms | {s["frames"]["p95_ms"]}ms | '
                f'{s["transcripts"]["p50_ms"]}ms | {s["transcripts"]["p95_ms"]}ms |'
            )
            r = entry['read']
            cells.append(
                f'| {r["list"]["p50_ms"]}ms | {r["list"]["p95_ms"]}ms | '
                f'{r["frame_fetch"]["p50_ms"]}ms | {r["frame_fetch"]["p95_ms"]}ms |'
            )
            cells.append(f'| {entry["load"]["p50_ms"]}ms | {entry["load"]["p95_ms"]}ms |')
        agent = b[impl]['small']['agent']
        cells.append(f'{agent["p50_ms"]}ms')
        cells.append(f'{agent["p95_ms"]}ms')
    return cells


def hosted_cells(h: dict) -> list[str]:
    cells = [f'{h[impl]["succeeded"]}/{h["questions"]}' for impl in IMPLS]
    for impl in IMPLS:
        e = h[impl]
        cells.append(f'{e["wall_sec"]:.1f}s')
        cells.append(f'{e["p50_sec"]:.1f}s')
        cells.append(f'{e["p95_sec"]:.1f}s')
        cells.append(str(e['lines_written']))
    return cells


def readme_cells(m: dict, h: dict) -> list[str]:
    """The README summary table and hosted-tier prose, formatted the way the doc renders
    them - `**` is stripped before matching, so bolding is not part of the check."""

    def row(label: str, vals: list) -> str:
        return f'| {label} | ' + ' | '.join(str(v) for v in vals) + ' |'

    compute = m['compute-service']['app_loc']
    needs = [m[i]['classified']['needs_compute_service'] for i in IMPLS]
    app = [m[i]['app_loc'] for i in IMPLS]
    cells = [
        row('App code you maintain', app),
        row('Plus the shared compute service', [compute if n else 0 for n in needs]),
        row('Total', [a + (compute if n else 0) for a, n in zip(app, needs, strict=True)]),
        row('Files you open to read the backend', [m[i]['app_files'] for i in IMPLS]),
        row('Orchestration hops', [m[i]['orchestration_hops'] for i in IMPLS]),
        row('HTTP routes with a hand-written handler', [m[i]['http_routes_written_by_hand'] for i in IMPLS]),
    ]
    cells += [f'{h[i]["succeeded"]}/{h["questions"]}' for i in IMPLS]
    lines = [h[i]['lines_written'] for i in IMPLS]
    cells.append(f'{lines[0]}-line')
    cells.append(f'{min(lines[1:])}-{max(lines[1:])}')
    return cells


def roundtrip_cells(r: dict) -> list[str]:
    """SCALE.md's boundary claims: per-video requests and bytes for the two consumers plus
    one cell per sweep point, formatted the way the doc renders them.

    The deltas used to render as one pooled `added X-Ys` range whose ends came from
    different implementations. A range cannot disagree with itself, so an outlier at one
    level hid inside it and shipped. One cell per implementation and level lets a bad point
    be wrong on its own, and n travels with it so the doc cannot present a single run as a
    settled number.
    """
    cells = []
    for impl in CONSUMERS:
        i = r[impl]['ingest']
        cells.append(f'{i["requests_per_video"]:g} requests')
        cells.append(f'{i["bytes_per_video"] / 1e6:.2f} MB')
    for impl in CONSUMERS:
        sweep = r[impl]['sweep']
        for level in SWEEP_LEVELS:
            point = sweep[level]
            n = point.get('n') or len(point.get('runs') or []) or 1
            runs = point.get('runs') or []
            if _resolves(point):
                cells.append(f'{impl} +{level}ms: added {point["wall_sec"] - sweep["0"]["wall_sec"]:.1f}s (n={n})')
            else:
                cells.append(f'{impl} +{level}ms: did not resolve (n={n}, {min(runs):.1f}-{max(runs):.1f}s)')
    return cells


def _resolves(point: dict) -> bool:
    """Whether a sweep point's runs agree closely enough to quote a median.

    Below two runs there is no spread to judge, so the ratio check in `sweep_failures`
    carries it instead. Above the fraction, the median is a number the runs do not
    support and the cell says so rather than rounding disagreement into a point estimate.
    """
    runs = point.get('runs') or []
    if len(runs) < 2:
        return True
    return max(runs) - min(runs) <= point['wall_sec'] * SWEEP_SPREAD_FRACTION


def sweep_failures(r: dict) -> list[str]:
    """Refuse to publish a sweep point the sweep's own model contradicts.

    Same shape as the 'no failed attempts' check below: the artifact is asked whether it
    supports the claim, rather than the doc being asked whether it copied a number. A cell
    that only has to exist cannot catch a point that is noise.
    """
    failures = []
    for impl in CONSUMERS:
        sweep = r[impl]['sweep']
        base = sweep['0']['wall_sec']
        for level in SWEEP_LEVELS:
            point = sweep[level]
            delta = point['wall_sec'] - base
            injected = point['requests'] * int(level) / 1000
            # A point that did not resolve already says so in its own cell; holding its
            # median to the ratio model as well would fail it twice for one fact.
            if _resolves(point) and delta > injected * SWEEP_RATIO_CEILING:
                failures.append(
                    f'roundtrip.json {impl} +{level}ms added {delta:.1f}s, over {SWEEP_RATIO_CEILING:g}x the '
                    f'{injected:.1f}s the proxy injected across {point["requests"]} serialized requests'
                )
        walls = [sweep[level]['wall_sec'] for level in SWEEP_LEVELS]
        if walls != sorted(walls):
            failures.append(f'roundtrip.json {impl} sweep runs faster at more added latency: {walls}')
    return failures


def validation_cells(m: dict) -> list[tuple[str, str]]:
    """Hand-classified request-validation lines, (doc name, cell) per place that quotes
    them: TRADEOFFS per implementation, README and convex-app/README as prose."""
    sb = m['supabase']['classified']['request_validation_loc']
    cx = m['convex']['classified']['request_validation_loc']
    return [
        ('docs/TRADEOFFS.md', f'{sb} lines by hand'),
        ('docs/TRADEOFFS.md', f'{cx} lines by hand'),
        ('README.md', f'{sb} and {cx} hand-written lines'),
        ('convex-app/README.md', f'{cx} for REST bodies'),
    ]


def evolve_cells(e: dict) -> list[str]:
    cells = []
    for impl, tiers in e.items():
        if impl == 'measured_at':
            continue
        for entry in tiers.values():
            for key in ('control_sec', 'schema_change_sec', 'backfill_sec', 'total_sec'):
                if key in entry and entry[key]:
                    cells.append(f'{entry[key]:.2f}s')
    return cells


def main() -> int:
    failures: list[str] = []

    scale = (DOCS / 'SCALE.md').read_text().replace('**', '')
    benchmarks = json.loads((DOCS / 'benchmarks.json').read_text())
    for cell in benchmarks_cells(benchmarks):
        if cell not in scale:
            failures.append(f'SCALE.md missing benchmark cell: {cell}')
    for impl in IMPLS:
        for tier, entry in benchmarks[impl].items():
            if tier == 'small' or not isinstance(entry, dict):
                continue
            if entry.get('ingest', {}).get('failed_attempts') and 'no failed attempts' in scale:
                failures.append(f'SCALE.md claims no failed attempts but {impl} {tier} recorded one')

    hosted = json.loads((DOCS / 'hosted.json').read_text())
    for cell in hosted_cells(hosted):
        if cell not in scale:
            failures.append(f'SCALE.md missing hosted cell: {cell}')

    readme = (ROOT / 'README.md').read_text().replace('**', '')
    metrics = json.loads((DOCS / 'metrics.json').read_text())
    for cell in readme_cells(metrics, hosted):
        if cell not in readme:
            failures.append(f'README.md missing summary cell: {cell}')

    evolve_doc = (DOCS / 'EVOLVE.md').read_text().replace('**', '')
    for cell in evolve_cells(json.loads((DOCS / 'evolve.json').read_text())):
        if cell not in evolve_doc:
            failures.append(f'EVOLVE.md missing evolve cell: {cell}')

    scale_flat = ' '.join(scale.split())
    roundtrip = json.loads((DOCS / 'roundtrip.json').read_text())
    for cell in roundtrip_cells(roundtrip):
        if cell not in scale_flat:
            failures.append(f'SCALE.md missing roundtrip cell: {cell}')
    failures += sweep_failures(roundtrip)

    validation: dict[str, list[str]] = {}
    for name, cell in validation_cells(metrics):
        validation.setdefault(name, []).append(cell)
    for name, cells in validation.items():
        flat = ' '.join((ROOT / name).read_text().replace('**', '').split())
        for cell in cells:
            if cell not in flat:
                failures.append(f'{name} missing validation cell: {cell}')

    for failure in failures:
        print(f'FAIL {failure}')
    if failures:
        print(f'{len(failures)} doc cells disagree with the committed artifacts')
        return 1
    print('docs quote the committed artifacts')
    return 0


if __name__ == '__main__':
    sys.exit(main())
