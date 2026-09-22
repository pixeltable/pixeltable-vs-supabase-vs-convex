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

    evolve_doc = (DOCS / 'EVOLVE.md').read_text().replace('**', '')
    for cell in evolve_cells(json.loads((DOCS / 'evolve.json').read_text())):
        if cell not in evolve_doc:
            failures.append(f'EVOLVE.md missing evolve cell: {cell}')

    for failure in failures:
        print(f'FAIL {failure}')
    if failures:
        print(f'{len(failures)} doc cells disagree with the committed artifacts')
        return 1
    print('docs quote the committed artifacts')
    return 0


if __name__ == '__main__':
    sys.exit(main())
