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

import itertools
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / 'docs'

IMPLS = ('pixeltable', 'supabase', 'convex')

CONSUMERS = ('supabase', 'convex')
SWEEP_BASELINE = '0'
SWEEP_LEVELS = ('20', '80')
# A delta subtracts one point from another, so both must be the same measurement.
# bench_roundtrip.py drops a point's runs when these change, but only within one level;
# nothing stops a `--videos 5` smoke run at 80ms from sitting beside a 20-video baseline.
SWEEP_SHAPE = ('videos', 'requests', 'compute_service_rev')
# Every published delta is a level's median minus the baseline's, so the evidence for it
# is both sets of runs, not one. The test is the exact one-sided Mann-Whitney: is a run at
# the level slower than a baseline run more often than chance allows? 0.025 is the
# one-sided half of the usual two-sided 0.05. At n=4 against 4 the smallest p is 1/70 and
# the next is 2/70, above it, so publishing means every run at the level is slower
# than every baseline run. Fewer than four runs on either side can never publish (3 vs 4
# bottoms out at 1/35); more runs let the test tolerate an outlier that separation cannot.
SWEEP_ALPHA = 0.025
# The proxy sleeps --add-latency-ms before each forwarded request, and a delay only adds
# wall time when nothing else is waiting with it. Both consumers ingest a video in six
# sequential compute calls: extract-frames, embed-clip, extract-audio, one Promise.all of
# transcribes (one delay however many segments), embed-text, detect-scenes
# (supabase-app/supabase/functions/api/index.ts, convex-app/convex/ingest.ts). Counting
# every request instead charges the fan-out once per segment. bench_roundtrip.py
# records the stages the proxy saw as `serial_requests`; this is the count for points
# written before it did, and it is a fact about the code to re-check when the code changes.
SERIAL_CALLS_PER_VIDEO = 6
# Under the prediction means some delay overlapped something the model calls serial; over
# it is time the proxy did not inject, which is not the boundary cost the sweep claims to
# report. The rank test has already said the point differs from the baseline; this says
# the size of the difference is the boundary's. 1.5x leaves half the prediction again for
# the noise in a median of a handful of runs.
SWEEP_RATIO_CEILING = 1.5


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
        # The baseline has no ingest or search rows in SCALE.md, but its reads and load do.
        small = b[impl]['small']
        r = small['read']
        cells.append(
            f'| {r["list"]["p50_ms"]}ms | {r["list"]["p95_ms"]}ms | '
            f'{r["frame_fetch"]["p50_ms"]}ms | {r["frame_fetch"]["p95_ms"]}ms |'
        )
        cells.append(f'| {small["load"]["p50_ms"]}ms | {small["load"]["p95_ms"]}ms |')
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
    return cells


def hosted_row_failures(h: dict, doc: str) -> list[str]:
    """A bare `29` matches anywhere, so the line count is checked at the end of its own row."""
    failures = []
    for impl in IMPLS:
        prefix = f'| {impl.capitalize()} | {h[impl]["succeeded"]}/{h["questions"]} |'
        rows = [line for line in doc.splitlines() if line.startswith(prefix)]
        if not any(line.rstrip().endswith(f'| {h[impl]["lines_written"]} |') for line in rows):
            failures.append(f'SCALE.md hosted row for {impl} does not end with {h[impl]["lines_written"]} lines')
    return failures


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
    lo, hi = min(lines[1:]), max(lines[1:])
    cells.append(f'against {lo} lines' if lo == hi else f'against {lo}-{hi} lines')
    return cells


def roundtrip_cells(r: dict) -> list[str]:
    """SCALE.md's boundary claims: per-video requests and bytes for the two consumers plus
    one cell per sweep point, formatted the way the doc renders them.

    The deltas used to render as one pooled `added X-Ys` range whose ends came from
    different implementations. A range cannot disagree with itself, so an outlier at one
    level hid inside it and shipped. One cell per implementation and level lets a bad point
    be wrong on its own, and n travels with it so the doc cannot present a single run as a
    settled number. A point that does not resolve shows its runs beside the baseline's,
    because the overlap between the two is the reason it has no number.
    """
    cells = []
    for impl in CONSUMERS:
        i = r[impl]['ingest']
        cells.append(f'{i["requests_per_video"]:g} requests')
        cells.append(f'{i["bytes_per_video"] / 1e6:.2f} MB')
    for impl in CONSUMERS:
        sweep = r[impl]['sweep']
        base = _runs(sweep[SWEEP_BASELINE])
        for level in SWEEP_LEVELS:
            point = sweep[level]
            runs = _runs(point)
            n = point.get('n') or len(runs)
            if _resolves(sweep, level):
                cells.append(f'{impl} +{level}ms: added {_delta(sweep, level):.1f}s (n={n})')
            else:
                cells.append(
                    f'{impl} +{level}ms: did not resolve (n={n}, {min(runs):.1f}-{max(runs):.1f}s '
                    f'vs {min(base):.1f}-{max(base):.1f}s at {SWEEP_BASELINE}ms)'
                )
    return cells


def _runs(point: dict) -> list[float]:
    """A point's wall times. An artifact written before runs accumulated holds one median."""
    return list(point.get('runs') or ([point['wall_sec']] if 'wall_sec' in point else []))


def _shape(point: dict) -> tuple:
    return tuple(point.get(key) for key in SWEEP_SHAPE)


def _delta(sweep: dict, level: str) -> float:
    return sweep[level]['wall_sec'] - sweep[SWEEP_BASELINE]['wall_sec']


def _slower_p(runs: list[float], base: list[float]) -> float:
    """Exact one-sided Mann-Whitney p that `runs` are slower than `base`.

    U counts the (run, baseline) pairs where the run is slower, a tie as half. Under the
    null the level labels are exchangeable, so p is the share of all ways to split the
    pooled times into groups of these sizes whose U is at least the observed one.
    Enumerating the splits is exact with ties and needs no table; at the n the sweep keeps
    the count is small (8 choose 4 is 70).
    """

    def u(xs: list[float], ys: list[float]) -> float:
        return sum(1.0 if x > y else 0.5 if x == y else 0.0 for x in xs for y in ys)

    pooled = runs + base
    observed = u(runs, base)
    as_extreme = 0
    for picked in itertools.combinations(range(len(pooled)), len(runs)):
        chosen = set(picked)
        xs = [pooled[i] for i in picked]
        ys = [v for i, v in enumerate(pooled) if i not in chosen]
        as_extreme += u(xs, ys) >= observed
    return as_extreme / math.comb(len(pooled), len(runs))


def _resolves(sweep: dict, level: str) -> bool:
    """Whether a sweep point's median delta is a number the runs support.

    It resolves when it is the same measurement as the baseline, its median is slower,
    and its runs are slower than the baseline's by the exact rank test. One run on either
    side can never pass (its smallest p is 1/(n+1)), which is the point: n=1 cannot tell
    the boundary cost from a slow afternoon. The spread check this replaces looked only at
    the level's own runs, so a noisy baseline, or a level sitting inside the baseline's
    range, still published a delta.
    """
    point, baseline = sweep[level], sweep[SWEEP_BASELINE]
    if _shape(point) != _shape(baseline) or _delta(sweep, level) <= 0:
        return False
    return _slower_p(_runs(point), _runs(baseline)) <= SWEEP_ALPHA


def sweep_failures(r: dict) -> list[str]:
    """Refuse to publish a sweep point the sweep's own model contradicts.

    Same shape as the 'no failed attempts' check below: the artifact is asked whether it
    supports the claim, rather than the doc being asked whether it copied a number. A cell
    that only has to exist cannot catch a point that is noise.
    """
    failures = []
    for impl in CONSUMERS:
        sweep = r[impl]['sweep']
        shapes = {level: _shape(sweep[level]) for level in (SWEEP_BASELINE, *SWEEP_LEVELS)}
        if len(set(shapes.values())) > 1:
            # Every delta below would subtract two different measurements, so each would
            # fail for this one fact. Name it once and skip the rest of this consumer.
            failures.append(f'roundtrip.json {impl} sweep points differ in {"/".join(SWEEP_SHAPE)}: {shapes}')
            continue
        for level in SWEEP_LEVELS:
            point = sweep[level]
            delta = _delta(sweep, level)
            if delta <= 0:
                # Added latency cannot remove wall time, so the baseline and this point were
                # not run under the same conditions, resolved or not.
                failures.append(f'roundtrip.json {impl} +{level}ms ran {-delta:.1f}s faster than {SWEEP_BASELINE}ms')
                continue
            serial = point.get('serial_requests') or point['videos'] * SERIAL_CALLS_PER_VIDEO
            injected = serial * int(level) / 1000
            # A point that did not resolve already says so in its own cell; holding its
            # median to the ratio model as well would fail it twice for one fact.
            if _resolves(sweep, level) and delta > injected * SWEEP_RATIO_CEILING:
                failures.append(
                    f'roundtrip.json {impl} +{level}ms added {delta:.1f}s, over {SWEEP_RATIO_CEILING:g}x the '
                    f'{injected:.1f}s the proxy injected across {serial} serial requests'
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
            # Total, lines and files together, so a line count is tied to its own row.
            cells.append(f'{entry["total_sec"]:.2f}s | {entry["lines_written"]} | {entry["files_touched"]} |')
            if 'undo_lines_written' in entry:
                cells.append(f'{entry["undo_lines_written"]} more lines')
            # What the change adds beyond its control, as EVOLVE.md's bullets state it:
            # the fused step on Pixeltable, the script on Supabase, the push on Convex.
            corpus = entry['corpus_videos']
            if impl in ('pixeltable', 'convex'):
                cells.append(f'{entry["schema_change_sec"] - entry["control_sec"]:.1f}s at {corpus} rows')
            elif impl == 'supabase':
                cells.append(f'{entry["backfill_sec"]:.1f}s at {corpus} rows')
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
        for tier, entry in benchmarks[impl].items():
            if not isinstance(entry, dict):
                continue
            # A failed agent query stays out of the percentiles, so the table alone would
            # never show it; the doc has to say it happened.
            failed = len(entry.get('agent', {}).get('failed') or [])
            if failed:
                total = entry['agent']['samples'] + failed
                cell = f'{impl.capitalize()} {tier}: {failed} of {total} agent queries failed'
                if cell not in scale:
                    failures.append(f'SCALE.md missing agent failure: {cell}')

    hosted = json.loads((DOCS / 'hosted.json').read_text())
    for cell in hosted_cells(hosted):
        if cell not in scale:
            failures.append(f'SCALE.md missing hosted cell: {cell}')
    failures += hosted_row_failures(hosted, scale)

    readme = (ROOT / 'README.md').read_text().replace('**', '')
    metrics = json.loads((DOCS / 'metrics.json').read_text())
    for cell in readme_cells(metrics, hosted):
        if cell not in readme:
            failures.append(f'README.md missing summary cell: {cell}')
    # TRADEOFFS.md repeats some of the same rows. A repeated row has to agree; a row it
    # leaves out is fine, which is why the check is keyed on the row's label.
    tradeoffs = (DOCS / 'TRADEOFFS.md').read_text().replace('**', '')
    load_row = ' | '.join(f'{benchmarks[i]["xl"]["load"]["p50_ms"]}ms' for i in IMPLS)
    if f'| Concurrent search p50, 8 clients (xl) | {load_row} |' not in tradeoffs:
        failures.append(f'TRADEOFFS.md concurrent-search row does not read {load_row}')
    for cell in readme_cells(metrics, hosted):
        label = cell.split(' | ')[0] + ' |' if cell.startswith('| ') else None
        if label and f'\n{label}' in tradeoffs and cell not in tradeoffs:
            failures.append(f'TRADEOFFS.md repeats a summary row with other values: {cell}')

    # The agent paragraph attributes the gap to the device; the attribution is only as
    # good as the numbers it quotes, so they are held to device.json like any other cell.
    devices = json.loads((DOCS / 'device.json').read_text())['devices']
    for cell in (f'{devices["cpu"]["p50_ms"]}ms on CPU', f'{devices["gpu"]["p50_ms"]}ms on Metal'):
        if cell not in scale:
            failures.append(f'SCALE.md missing device cell: {cell}')

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
