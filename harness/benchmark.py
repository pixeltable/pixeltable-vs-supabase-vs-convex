#!/usr/bin/env python3
"""Measure ingest throughput and search latency against one running implementation.

    python harness/benchmark.py --impl convex --base-url http://127.0.0.1:3211 --tier large

The correctness suites run on three videos, which is the right size for asserting that
three implementations agree and the wrong size for saying anything about scale. This
ingests the 20-video tier and times it, then measures search latency over the resulting
corpus, and writes both into docs/benchmarks.json.

What the numbers are and are not: one laptop, CPU only, local models, one run. They
compare the three implementations against each other on identical work, which is the
question this repo asks. They are not a capacity estimate for anyone's production.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harness.conftest import PATHS, auth_headers  # noqa: E402
from harness.seed import videos_for, wait_for_job  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'docs' / 'benchmarks.json'
TIMEOUT = 900.0

# Pixeltable answers an ingest with a job to poll; Supabase and Convex answer when the
# work is done. Poll fast enough that the interval does not show up in the number: at 2s
# every asynchronous ingest rounds up to the next 2s, which is most of a 3s ingest.
POLL_SEC = 0.05

# Ten queries, five visual and five spoken, none of them the fixture queries the
# correctness suites assert on. Latency should not be measured on the cases we tuned.
FRAME_QUERIES = [
    'a dark slide with white text',
    'a title card about databases',
    'a summary slide at the end of a talk',
    'a diagram on a green background',
    'text reading worked example',
]
TRANSCRIPT_QUERIES = [
    'measuring is better than guessing',
    'the common mistake is ignoring constant factors',
    'breadth first and depth first search',
    'snapshot isolation and write skew',
    'approximate nearest neighbours and recall',
]


# The libraries that decide what the numbers mean. Pixeltable runs the models in its own
# process; compute-service runs the same ones for the other two, from this environment.
TRACKED_PACKAGES = ('pixeltable', 'sentence-transformers', 'transformers', 'torch', 'openai-whisper')


def versions() -> dict[str, str]:
    import importlib.metadata as md

    found = {}
    for name in TRACKED_PACKAGES:
        try:
            found[name] = md.version(name)
        except md.PackageNotFoundError:
            found[name] = 'not installed'
    return found


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile. No interpolation, so every number is one observed run."""
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(p / 100 * len(ordered) + 0.5) - 1))
    return ordered[index]


def ingest(client: httpx.Client, impl: str, tier: str) -> dict:
    videos = videos_for(tier)
    if not videos:
        sys.exit(f'no {tier}-tier videos. Run: python fixtures/videos/generate.py --tier {tier}')

    method, path = PATHS[impl]['ingest']
    per_video: list[float] = []
    failures: list[dict] = []
    started_all = time.monotonic()
    for video in videos:
        # One retry, recorded. A benchmark that aborts on the first failure publishes no
        # number, and one that retries silently publishes a throughput nobody can
        # reproduce. Both the retry count and what failed go into the output.
        for attempt in (1, 2):
            started = time.monotonic()
            try:
                response = client.request(method, path, json={'video': str(video), 'title': video.name})
                response.raise_for_status()
                if job_url := response.json().get('job_url'):
                    wait_for_job(client, job_url, started + TIMEOUT, poll_sec=POLL_SEC)
            except httpx.HTTPStatusError as exc:
                # A rejected credential is a setup mistake, not a throughput measurement.
                # Failing on the first one beats publishing 20 identical 401s.
                if exc.response.status_code in (401, 403):
                    sys.exit(f'{impl} rejected the request ({exc.response.status_code}). Check --auth-token.')
                failures.append({'video': video.name, 'attempt': attempt, 'error': str(exc)[:300]})
                print(f'  {video.name} FAILED on attempt {attempt}: {str(exc)[:120]}')
                if attempt == 2:
                    break
                continue
            except Exception as exc:  # noqa: BLE001 - the failure is the measurement
                failures.append({'video': video.name, 'attempt': attempt, 'error': str(exc)[:300]})
                print(f'  {video.name} FAILED on attempt {attempt}: {str(exc)[:120]}')
                if attempt == 2:
                    break
                continue
            elapsed = time.monotonic() - started
            per_video.append(elapsed)
            print(f'  {video.name} {elapsed:.1f}s')
            break

    wall = time.monotonic() - started_all
    if not per_video:
        sys.exit(f'{impl} ingested nothing; {len(failures)} attempts failed. First: {failures[0]["error"]}')

    seconds_of_video = sum(_duration(v) for v in videos)
    return {
        'videos': len(videos),
        'ingested': len(per_video),
        'failed_attempts': failures,
        'seconds_of_video': round(seconds_of_video, 1),
        'wall_sec': round(wall, 1),
        # The first video pays for loading CLIP, Whisper and the embedding model, so it
        # is reported on its own rather than averaged into the rest.
        'first_video_sec': round(per_video[0], 1),
        'median_video_sec': round(statistics.median(per_video[1:] or per_video), 1),
        # Seconds of footage per second spent. Normalises across tiers, which hold
        # different amounts of video, so their wall times cannot be compared directly.
        'realtime_factor': round(seconds_of_video / wall, 2),
    }


def _duration(video: Path) -> float:
    import subprocess

    probe = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(video)],
        capture_output=True,
        text=True,
    )
    return float(probe.stdout.strip() or 0.0)


def latency(client: httpx.Client, impl: str, iterations: int) -> dict:
    out = {}
    for route, queries in (('frames', FRAME_QUERIES), ('transcripts', TRANSCRIPT_QUERIES)):
        method, path = PATHS[impl][route]
        # One untimed pass, so the first query does not pay for a cold model or an
        # unopened connection on behalf of every other measurement.
        client.request(method, path, json={'query': queries[0], 'limit': 10})

        samples = []
        for _ in range(iterations):
            for query in queries:
                started = time.monotonic()
                response = client.request(method, path, json={'query': query, 'limit': 10})
                response.raise_for_status()
                samples.append((time.monotonic() - started) * 1000)
        out[route] = {
            'samples': len(samples),
            'p50_ms': round(percentile(samples, 50), 1),
            'p95_ms': round(percentile(samples, 95), 1),
            'min_ms': round(min(samples), 1),
            'max_ms': round(max(samples), 1),
        }
        print(f'  {route}: p50 {out[route]["p50_ms"]}ms  p95 {out[route]["p95_ms"]}ms  (n={len(samples)})')
    return out


def corpus(client: httpx.Client, impl: str) -> dict:
    method, path = PATHS[impl]['list']
    rows = client.request(method, path).json()['rows']
    return {'videos_listed': len(rows), 'seconds_listed': round(sum(r['duration_sec'] for r in rows), 1)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--impl', required=True, choices=sorted(PATHS))
    parser.add_argument('--base-url', default='')
    parser.add_argument('--auth-token', default='')
    parser.add_argument('--tier', default='large', choices=['small', 'large', 'xl'])
    parser.add_argument('--iterations', type=int, default=6, help='passes over the query set')
    parser.add_argument('--skip-ingest', action='store_true', help='measure search only')
    args = parser.parse_args()

    base_url = args.base_url
    if not base_url and args.impl == 'pixeltable':
        from harness.conftest import _auto_discover_pixeltable_url

        base_url = _auto_discover_pixeltable_url() or ''
    if not base_url:
        sys.exit(f'--base-url required for {args.impl}')

    headers = auth_headers(args.impl, args.auth_token)
    result: dict = {'tier': args.tier, 'measured_at': datetime.now(UTC).isoformat(timespec='seconds')}
    with httpx.Client(base_url=base_url.rstrip('/'), headers=headers, timeout=TIMEOUT) as client:
        if not args.skip_ingest:
            print(f'ingest ({args.impl}, {args.tier}):')
            result['ingest'] = ingest(client, args.impl, args.tier)
        print(f'search ({args.impl}):')
        result['search'] = latency(client, args.impl, args.iterations)
        result['corpus'] = corpus(client, args.impl)

    existing = json.loads(OUT.read_text()) if OUT.exists() else {}
    # Rewritten every run rather than set once: a timing is only reproducible alongside
    # the library versions that produced it, and those move.
    existing['host'] = {
        'platform': platform.platform(),
        'machine': platform.machine(),
        'python': platform.python_version(),
        'versions': versions(),
    }
    # Keyed by implementation then tier, so tiers accumulate instead of overwriting each
    # other. A flat entry from a single-tier run is migrated into its own tier first.
    entry = existing.get(args.impl, {})
    if 'tier' in entry:
        entry = {entry['tier']: entry}
    entry[args.tier] = result
    existing[args.impl] = entry
    OUT.write_text(json.dumps(existing, indent=2) + '\n')
    print(f'wrote {OUT.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
