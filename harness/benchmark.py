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
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harness.conftest import PATHS, auth_headers  # noqa: E402
from harness.seed import TIERS, videos_for, wait_for_job  # noqa: E402

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
# The agent is the expensive one: two retrievals and a 1.5B model generating an answer.
# Separate from the search queries because the route takes a question, not a query and a
# limit, and because it is slow enough that it needs its own iteration count.
AGENT_QUESTIONS = [
    'What is the time complexity of quicksort?',
    'What did the speaker say about measuring instead of guessing?',
    'Which video covers database indexes?',
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


def service_env_versions() -> dict[str, str]:
    """Versions in the interpreter the Pixeltable service runs under (the repo .venv).

    This harness runs under a different interpreter - the one that also runs
    compute-service - so reporting only `versions()` would record the environment of
    the two competitors' model work and 'not installed' for the platform whose
    numbers it produced. Both are recorded; the labels say which is which.
    """
    venv_python = ROOT / '.venv' / 'bin' / 'python'
    if not venv_python.exists():
        return {}
    code = (
        'import importlib.metadata as m, json\n'
        'def v(p):\n'
        '    try: return m.version(p)\n'
        '    except m.PackageNotFoundError: return "not installed"\n'
        f'print(json.dumps({{p: v(p) for p in {TRACKED_PACKAGES!r}}}))'
    )
    try:
        out = subprocess.run([str(venv_python), '-c', code], capture_output=True, text=True, timeout=30)
        return json.loads(out.stdout) if out.returncode == 0 else {}
    except Exception:
        return {}


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


def agent_latency(client: httpx.Client, impl: str, iterations: int) -> dict:
    """Time the whole retrieval-and-answer path, which no other measurement covers.

    Same model everywhere: Qwen2.5-1.5B-Instruct GGUF, in Pixeltable's own process and
    behind `compute-service` for the other two. Answers are not scored here; equivalence
    already asserts that all three answer and keep their evidence.
    """
    method, path = PATHS[impl]['agent']
    client.request(method, path, json={'question': AGENT_QUESTIONS[0]})  # untimed warm-up

    samples = []
    for _ in range(iterations):
        for question in AGENT_QUESTIONS:
            started = time.monotonic()
            response = client.request(method, path, json={'question': question})
            response.raise_for_status()
            samples.append((time.monotonic() - started) * 1000)
    out = {
        'samples': len(samples),
        'p50_ms': round(percentile(samples, 50), 1),
        'p95_ms': round(percentile(samples, 95), 1),
        'min_ms': round(min(samples), 1),
        'max_ms': round(max(samples), 1),
    }
    print(f'  agent: p50 {out["p50_ms"]}ms  p95 {out["p95_ms"]}ms  (n={len(samples)})')
    return out


def read_latency(client: httpx.Client, impl: str, iterations: int) -> dict:
    """Two reads nothing else covers: the list route, and a stored frame fetched by URL.

    frame_url resolves to a different substrate per platform: Pixeltable's catalog media
    store, Supabase Storage, and Convex file storage. The URLs come from a frame search
    because the contract has no route that returns a frame by id.
    """
    method, path = PATHS[impl]['list']
    list_samples = []
    for _ in range(iterations):
        started = time.monotonic()
        response = client.request(method, path)
        response.raise_for_status()
        list_samples.append((time.monotonic() - started) * 1000)

    method, path = PATHS[impl]['frames']
    rows = client.request(method, path, json={'query': FRAME_QUERIES[0], 'limit': 10}).json()['rows']
    if not rows:
        sys.exit('frame search returned nothing; cannot measure frame fetch')
    urls = [r['frame_url'] for r in rows]
    fetch_samples = []
    for _ in range(iterations):
        for url in urls:
            started = time.monotonic()
            response = client.get(url)
            response.raise_for_status()
            fetch_samples.append((time.monotonic() - started) * 1000)

    out = {}
    for name, samples in (('list', list_samples), ('frame_fetch', fetch_samples)):
        out[name] = {
            'samples': len(samples),
            'p50_ms': round(percentile(samples, 50), 1),
            'p95_ms': round(percentile(samples, 95), 1),
            'min_ms': round(min(samples), 1),
            'max_ms': round(max(samples), 1),
        }
        print(f'  read/{name}: p50 {out[name]["p50_ms"]}ms  p95 {out[name]["p95_ms"]}ms  (n={len(samples)})')
    return out


def concurrent_search(base_url: str, headers: dict, impl: str, workers: int, iterations: int) -> dict:
    """The serial search numbers under N clients in flight at once.

    One client per worker rather than one shared client, so the connection pool each
    platform gives its handler is part of the measurement.
    """
    queries = [('frames', q) for q in FRAME_QUERIES] + [('transcripts', q) for q in TRANSCRIPT_QUERIES]
    tasks = [queries[i % len(queries)] for i in range(iterations * workers)]

    def worker(chunk: list[tuple[str, str]]) -> list[float]:
        samples = []
        with httpx.Client(base_url=base_url, headers=headers, timeout=TIMEOUT) as client:
            for route, query in chunk:
                method, path = PATHS[impl][route]
                started = time.monotonic()
                response = client.request(method, path, json={'query': query, 'limit': 10})
                response.raise_for_status()
                samples.append((time.monotonic() - started) * 1000)
        return samples

    started_all = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        samples = [ms for chunk in pool.map(worker, (tasks[i::workers] for i in range(workers))) for ms in chunk]
    wall = time.monotonic() - started_all
    out = {
        'workers': workers,
        'samples': len(samples),
        'wall_sec': round(wall, 1),
        'p50_ms': round(percentile(samples, 50), 1),
        'p95_ms': round(percentile(samples, 95), 1),
        'min_ms': round(min(samples), 1),
        'max_ms': round(max(samples), 1),
    }
    print(f'  load: {workers} workers, p50 {out["p50_ms"]}ms  p95 {out["p95_ms"]}ms  wall {wall:.1f}s')
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
    parser.add_argument('--tier', default='large', choices=sorted(TIERS))
    parser.add_argument('--iterations', type=int, default=6, help='passes over the query set')
    parser.add_argument(
        '--agent-iterations', type=int, default=4, help='passes over the agent questions, which are slower'
    )
    parser.add_argument('--skip-ingest', action='store_true', help='measure search only')
    parser.add_argument(
        '--workers', type=int, default=8, help='clients in flight for the concurrent-search measurement'
    )
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
        result['agent'] = agent_latency(client, args.impl, args.agent_iterations)
        result['read'] = read_latency(client, args.impl, args.iterations)
        result['load'] = concurrent_search(base_url, headers, args.impl, args.workers, args.iterations)
        result['corpus'] = corpus(client, args.impl)

    existing = json.loads(OUT.read_text()) if OUT.exists() else {}
    # Rewritten every run rather than set once: a timing is only reproducible alongside
    # the library versions that produced it, and those move.
    existing['host'] = {
        'platform': platform.platform(),
        'machine': platform.machine(),
        'python': platform.python_version(),
        'versions': versions(),
        'service_env_versions': service_env_versions(),
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
