#!/usr/bin/env python3
"""Render docs/summary.svg, the top-level benchmark chart embedded in the README.

    python harness/render_summary.py

Pure-stdlib SVG: the repo carries no plotting dependency, and a deterministic render
keeps CI's regenerate-and-diff check meaningful. Every number comes from the committed
artifacts: docs/benchmarks.json (xl tier latencies, small tier for the local agent),
docs/evolve.json (123-video corpus), docs/hosted.json (the paid-endpoint run).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'docs' / 'summary.svg'

IMPLS = ('pixeltable', 'supabase', 'convex')
LABEL = {'pixeltable': 'Pixeltable', 'supabase': 'Supabase', 'convex': 'Convex'}
COLOR = {'pixeltable': '#4c78a8', 'supabase': '#3ecf8e', 'convex': '#f58518'}
INK = '#24292f'
FAINT = '#57606a'
GRID = '#d8dee4'

W, H = 920, 800


def esc(text: str) -> str:
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def plural(n: int) -> str:
    return 'line' if n == 1 else 'lines'


def fmt_ms(ms: float) -> str:
    if ms >= 1000:
        return f'{ms / 1000:.1f}s'
    return f'{ms:.1f}ms' if ms < 10 else f'{ms:.0f}ms'


def text(x: float, y: float, s: str, size: int = 11, fill: str = INK, anchor: str = 'start', weight: str = '') -> str:
    w = f' font-weight="{weight}"' if weight else ''
    return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}"{w}>{esc(s)}</text>'


def latency_panel(bench: dict, hosted: dict) -> str:
    """p50 per operation, grouped bars on a log ms axis. The hosted agent converts
    seconds to ms so one axis carries a 1ms read and an 8s hosted call."""
    rows = [
        ('search - frames', [b['xl']['search']['frames']['p50_ms'] for b in (bench[i] for i in IMPLS)]),
        ('search - transcripts', [b['xl']['search']['transcripts']['p50_ms'] for b in (bench[i] for i in IMPLS)]),
        ('read - list', [b['xl']['read']['list']['p50_ms'] for b in (bench[i] for i in IMPLS)]),
        ('read - frame', [b['xl']['read']['frame_fetch']['p50_ms'] for b in (bench[i] for i in IMPLS)]),
        ('load p50 (8 workers)', [b['xl']['load']['p50_ms'] for b in (bench[i] for i in IMPLS)]),
        ('agent - local 1.5B', [b['small']['agent']['p50_ms'] for b in (bench[i] for i in IMPLS)]),
        ('agent - hosted', [hosted[i]['p50_sec'] * 1000 for i in IMPLS]),
    ]
    left, right, top = 170.0, 880.0, 90.0
    bar_h, gap, group_gap = 11.0, 2.5, 16.0
    group_h = 3 * bar_h + 2 * gap + group_gap
    bottom = top + len(rows) * group_h
    lo, hi = math.log10(0.3), math.log10(30000)

    def x(ms: float) -> float:
        return left + (math.log10(ms) - lo) / (hi - lo) * (right - left)

    parts = [text(30, 40, 'p50 latency by operation - lower is better', 15, weight='bold')]
    lx = right - 260
    for i, impl in enumerate(IMPLS):
        parts.append(f'<rect x="{lx + i * 86:.0f}" y="30" width="10" height="10" rx="2" fill="{COLOR[impl]}"/>')
        parts.append(text(lx + 14 + i * 86, 39, LABEL[impl], 11, FAINT))

    for t, lab in ((1, '1ms'), (10, '10ms'), (100, '100ms'), (1000, '1s'), (10000, '10s')):
        tx = x(t)
        parts.append(f'<line x1="{tx:.1f}" y1="{top - 8}" x2="{tx:.1f}" y2="{bottom:.1f}" stroke="{GRID}"/>')
        parts.append(text(tx, bottom + 16, lab, 10, FAINT, 'middle'))
    for gi, (name, vals) in enumerate(rows):
        gy = top + gi * group_h
        parts.append(text(left - 12, gy + 2 * bar_h, name, 11, INK, 'end'))
        for i, v in enumerate(vals):
            by = gy + i * (bar_h + gap)
            parts.append(
                f'<rect x="{left:.1f}" y="{by:.1f}" width="{x(v) - left:.1f}" height="{bar_h}"'
                f' rx="2" fill="{COLOR[IMPLS[i]]}"/>'
            )
            parts.append(text(x(v) + 5, by + bar_h - 2, fmt_ms(v), 9, FAINT))
    return ''.join(parts)


def evolve_panel(evolve: dict) -> str:
    """Lines written vs wall seconds to land the schema change, 123-video corpus. The
    fourth point is Convex's declared-searchIndex variant, which writes one line too."""
    left, top, pw, ph = 70.0, 560.0, 340.0, 180.0
    xmax, ymax = 60.0, 9.0

    def x(v: float) -> float:
        return left + v / xmax * pw

    def y(v: float) -> float:
        return top + ph - v / ymax * ph

    # name -> label side; the rightmost point's label goes left so it stays in-panel
    points = [(i, 'start') for i in IMPLS] + [('convex-searchindex', 'start')]
    side = {'convex': 'end'}

    parts = [text(30, 528, 'Land a schema change - 123-video corpus', 13, weight='bold')]
    for t in range(0, 61, 15):
        parts.append(f'<line x1="{x(t):.1f}" y1="{top}" x2="{x(t):.1f}" y2="{top + ph}" stroke="{GRID}"/>')
        parts.append(text(x(t), top + ph + 14, str(t), 10, FAINT, 'middle'))
    for t in range(0, 10, 3):
        parts.append(f'<line x1="{left}" y1="{y(t):.1f}" x2="{left + pw}" y2="{y(t):.1f}" stroke="{GRID}"/>')
        parts.append(text(left - 8, y(t) + 4, f'{t}s', 10, FAINT, 'end'))
    parts.append(text(left + pw / 2, top + ph + 30, 'lines written', 10, FAINT, 'middle'))

    for name, default_side in points:
        e = evolve[name]['123']
        impl = name.split('-')[0]
        label = LABEL[impl] if name in IMPLS else 'Convex via searchIndex'
        px, py = x(e['lines_written']), y(e['total_sec'])
        anchor = side.get(name, default_side)
        tx = px - 9 if anchor == 'end' else px + 9
        parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="6" fill="{COLOR[impl]}"/>')
        parts.append(text(tx, py + 4, f'{label} ({e["lines_written"]} {plural(e["lines_written"])})', 10, INK, anchor))
    return ''.join(parts)


def hosted_panel(hosted: dict) -> str:
    """The swap measured on the paid endpoint: identical outcome, very different
    line counts. Bars are lines written; the left label keeps the p50."""
    left, top, pw = 660.0, 560.0, 200.0
    xmax = 48.0
    bar_h, gap = 18.0, 30.0
    bottom = top + 3 * (bar_h + gap)
    parts = [
        text(500, 528, 'Hosted agent swap - same model, all 12/12', 13, weight='bold'),
        text(500, 542, 'bars are lines of retry/backoff written', 10, FAINT),
    ]
    for t in range(0, 49, 12):
        tx = left + t / xmax * pw
        parts.append(f'<line x1="{tx:.1f}" y1="{top}" x2="{tx:.1f}" y2="{bottom:.1f}" stroke="{GRID}"/>')
        parts.append(text(tx, bottom + 14, str(t), 10, FAINT, 'middle'))
    for i, impl in enumerate(IMPLS):
        e = hosted[impl]
        by = top + 10 + i * (bar_h + gap)
        w = e['lines_written'] / xmax * pw
        parts.append(
            f'<rect x="{left:.1f}" y="{by:.1f}" width="{w:.1f}" height="{bar_h}" rx="2" fill="{COLOR[impl]}"/>'
        )
        parts.append(text(left + w + 6, by + bar_h - 5, f'{e["lines_written"]} {plural(e["lines_written"])}', 10))
        parts.append(text(left - 10, by + bar_h - 5, f'{LABEL[impl]} - p50 {e["p50_sec"]:.1f}s', 10, INK, 'end'))
    return ''.join(parts)


def main() -> int:
    bench = json.loads((ROOT / 'docs' / 'benchmarks.json').read_text())
    evolve = json.loads((ROOT / 'docs' / 'evolve.json').read_text())
    hosted = json.loads((ROOT / 'docs' / 'hosted.json').read_text())

    stamp = (
        f'sources: benchmarks.json {bench["pixeltable"]["xl"]["measured_at"][:10]}, '
        f'evolve.json {evolve["measured_at"][:10]}, hosted.json {hosted["measured_at"][:10]} - '
        'rendered by harness/render_summary.py'
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}"'
        f' font-family="system-ui,-apple-system,sans-serif">'
        f'<rect width="{W}" height="{H}" fill="#ffffff"/>'
        + latency_panel(bench, hosted)
        + evolve_panel(evolve)
        + hosted_panel(hosted)
        + text(30, H - 14, stamp, 9, FAINT)
        + '</svg>'
    )
    OUT.write_text(svg + '\n')
    print(f'wrote {OUT.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
