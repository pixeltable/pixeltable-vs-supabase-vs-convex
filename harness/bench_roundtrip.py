#!/usr/bin/env python3
"""Count the requests and bytes an implementation sends across the compute-service boundary.

    python harness/bench_roundtrip.py --impl convex --base-url http://127.0.0.1:3211
    python harness/bench_roundtrip.py --impl supabase --base-url http://127.0.0.1:54321 --auth-token "$SECRET"

The proxy listens where both consumers already point (COMPUTE_SERVICE_URL, port 9000) and
forwards to a compute-service started on --upstream, so the measured code changes nowhere.
Bytes are the JSON request and response bodies; the base64 payloads dominate and headers
are noise next to them.

--add-latency-ms delays each forwarded request, the cheapest model of a boundary that
stops being loopback. Every run records its wall time under that latency level, so three
runs at 0/20/80 produce the sweep. --repeats runs the ingest more than once at one level;
the sweep point keeps every wall time it is given, here and across invocations, because a
sweep point of n=1 cannot tell the boundary cost from a slow afternoon. Each run also
records when it started, its index in the invocation and how many videos the consumer
already held, since nothing resets the consumer between runs and drift has to be visible
to be ruled out. --discard-warmup ingests once first and keeps that time apart from the
runs.

Pixeltable's row is written with basis 'structural': it has no compute-service call to
count, which is a fact about the code, not a measurement. The two that do have one are
the rows this script fills.

docs/roundtrip.json is committed; harness/check_docs.py holds the published cells to it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harness.benchmark import AGENT_QUESTIONS  # noqa: E402
from harness.conftest import PATHS, auth_headers  # noqa: E402
from harness.seed import videos_for  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'docs' / 'roundtrip.json'
UPSTREAM_TIMEOUT = 600.0


class _Proxy(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port: int, upstream: str, add_latency_ms: float):
        self.upstream = upstream.rstrip('/')
        self.add_latency_ms = add_latency_ms
        # One record per forwarded request: path, request bytes in, response bytes out.
        self.records: list[dict] = []
        self.lock = threading.Lock()
        handler = self._make_handler()
        super().__init__(('0.0.0.0', port), handler)
        # 0.0.0.0 because Supabase reaches this from a container via host.docker.internal
        self.client = httpx.Client(timeout=UPSTREAM_TIMEOUT)

    def _make_handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *_args) -> None:
                pass

            def do_GET(self) -> None:
                self._forward()

            def do_POST(self) -> None:
                self._forward()

            def _forward(self) -> None:
                received = time.monotonic()
                body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
                if server.add_latency_ms:
                    time.sleep(server.add_latency_ms / 1000)
                resp = server.client.request(
                    self.command,
                    f'{server.upstream}{self.path}',
                    content=body,
                    headers={'Content-Type': 'application/json'},
                )
                # Recorded before the response goes out: once the consumer has it, the ingest
                # POST can return and `measure` slices the records, so a later append is lost.
                with server.lock:
                    server.records.append(
                        {
                            'path': self.path,
                            'req_bytes': len(body),
                            'resp_bytes': len(resp.content),
                            'received': received,
                            'answered': time.monotonic(),
                        }
                    )
                self.send_response(resp.status_code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(resp.content)))
                self.end_headers()
                self.wfile.write(resp.content)

        return Handler


def serial_requests(calls: list[dict]) -> int:
    """How many of one video's requests the added latency is paid for, one after another.

    The proxy sleeps inside each request, so requests in flight together share one delay.
    Sorting by arrival and counting each request that arrives after every earlier one was
    answered gives the number of sequential stages: a Promise.all fan-out counts once. This
    is what check_docs.py's ratio model multiplies by the added latency, measured instead
    of read off the consumer's source.
    """
    stages, answered = 0, float('-inf')
    for call in sorted(calls, key=lambda c: c['received']):
        if call['received'] >= answered:
            stages += 1
        answered = max(answered, call['answered'])
    return stages


def corpus_size(client: httpx.Client, impl: str) -> int:
    """Videos the consumer holds, through the contract's list route."""
    method, path = PATHS[impl]['list']
    resp = client.request(method, path)
    resp.raise_for_status()
    return len(resp.json()['rows'])


def measure(client: httpx.Client, impl: str, videos: list[Path], proxy: _Proxy, agent_iterations: int) -> dict:
    """Ingest each video and fire each agent question, attributing proxy traffic per call.

    Ingest is synchronous on both consumers, so the counter read before and after one
    POST is that video's whole boundary cost. The agent path is the same trick per query.
    """
    method, path = PATHS[impl]['ingest']
    per_video = []
    wall_started = time.monotonic()
    for video in videos:
        before = len(proxy.records)
        started = time.monotonic()
        client.request(method, path, json={'video': str(video), 'title': video.name}).raise_for_status()
        elapsed = time.monotonic() - started
        calls = proxy.records[before:]
        per_video.append(
            {
                'video': video.name,
                'wall_sec': round(elapsed, 2),
                'requests': len(calls),
                'serial_requests': serial_requests(calls),
                'bytes': sum(c['req_bytes'] + c['resp_bytes'] for c in calls),
            }
        )
        print(f'  {video.name}: {len(calls)} requests, {per_video[-1]["bytes"] / 1e6:.2f} MB, {elapsed:.1f}s')
    ingest_wall = time.monotonic() - wall_started

    method, path = PATHS[impl]['agent']
    client.request(method, path, json={'question': AGENT_QUESTIONS[0]}).raise_for_status()  # warm-up, uncounted
    before = len(proxy.records)
    per_query = []
    for _ in range(agent_iterations):
        for question in AGENT_QUESTIONS:
            q_before = len(proxy.records)
            client.request(method, path, json={'question': question}).raise_for_status()
            calls = proxy.records[q_before:]
            per_query.append({'requests': len(calls), 'bytes': sum(c['req_bytes'] + c['resp_bytes'] for c in calls)})
    agent_calls = proxy.records[before:]

    videos_n = len(per_video)
    return {
        'ingest': {
            'videos': videos_n,
            'wall_sec': round(ingest_wall, 1),
            'requests': sum(v['requests'] for v in per_video),
            'requests_per_video': round(sum(v['requests'] for v in per_video) / videos_n, 2),
            'serial_requests': sum(v['serial_requests'] for v in per_video),
            'bytes': sum(v['bytes'] for v in per_video),
            'bytes_per_video': round(sum(v['bytes'] for v in per_video) / videos_n),
            'per_video': per_video,
        },
        'agent': {
            'queries': len(per_query),
            'requests_per_query': round(sum(q['requests'] for q in per_query) / len(per_query), 2),
            'bytes_per_query': round(sum(q['bytes'] for q in per_query) / len(per_query)),
            'per_query': per_query,
        },
        'paths_called': sorted({c['path'] for c in proxy.records}),
        '_agent_records': len(agent_calls),
    }


def compute_service_rev() -> str:
    """Short hash of the compute-service source the proxy forwards to."""
    return hashlib.sha256((ROOT / 'compute-service' / 'app.py').read_bytes()).hexdigest()[:12]


def merge_sweep(entry: dict, add_latency_ms: float, results: list[dict], meta: list[dict], warmup: dict | None) -> dict:
    """Fold this invocation's ingest wall times into the sweep point for one latency level.

    The point used to be overwritten, so every published sweep number was n=1 and a single
    slow run was indistinguishable from the boundary cost it claimed to measure. Runs
    accumulate across invocations as well as within one: `--repeats 3` run twice leaves n=6.

    Spread is the observed min and max, not a half-range around the median. At these n the
    extremes are data rather than an estimate, and which side a point ran long on is the
    thing a reader needs to see; a symmetric half-range throws that away. `wall_sec` stays
    the headline key and is now the median, which at n=1 is the value it always held, so an
    artifact written before this change reads the same.

    `runs` stays a list of wall times so every reader of it is unchanged; `run_meta` is
    index-aligned with it, and runs recorded before it existed get an entry holding only
    their wall time rather than shifting every later entry onto the wrong run. A warm-up is
    not a run: it goes to `warmup_wall_sec` and `warmup_meta`, which accumulate the same way
    and never reach the median.
    """
    level = str(int(add_latency_ms))
    last = results[-1]['ingest']
    # The service's source is part of the shape: a change to how compute-service handles
    # concurrent requests changes the wall time the sweep subtracts, so runs against two
    # versions of it are two measurements. Points written before this was recorded carry
    # no revision and are dropped on the next run rather than pooled.
    shape = {'videos': last['videos'], 'requests': last['requests'], 'compute_service_rev': compute_service_rev()}
    point = entry.setdefault('sweep', {}).get(level, {})
    runs = _runs(point)
    run_meta = list(point.get('run_meta') or [])
    run_meta = [{'wall_sec': w} for w in runs[: max(0, len(runs) - len(run_meta))]] + run_meta
    warmups = list(point.get('warmup_wall_sec') or [])
    warmup_meta = list(point.get('warmup_meta') or [])
    if point and any(point.get(key) != value for key, value in shape.items()):
        # A different video or request count is a different measurement. Pooling it with
        # this one would publish the mean of two things, so the earlier runs go, and say so.
        print(f'sweep {level}ms: shape changed, dropping {len(runs)} earlier run(s) rather than pooling them')
        runs, run_meta, warmups, warmup_meta = [], [], [], []
    runs += [r['ingest']['wall_sec'] for r in results]
    run_meta += [{'wall_sec': r['ingest']['wall_sec'], **m} for r, m in zip(results, meta, strict=True)]
    if warmup:
        warmups.append(warmup['wall_sec'])
        warmup_meta.append(warmup)
    point = {
        'wall_sec': round(statistics.median(runs), 1),
        'wall_sec_min': min(runs),
        'wall_sec_max': max(runs),
        'n': len(runs),
        'runs': runs,
        'run_meta': run_meta,
        **shape,
        # Not part of the shape: it is derived from request timing, and a run that read one
        # stage differently should not discard the point's history.
        'serial_requests': last['serial_requests'],
    }
    if warmups:
        point['warmup_wall_sec'] = warmups
        point['warmup_meta'] = warmup_meta
    return point


def _runs(point: dict) -> list[float]:
    """A point's wall times. An artifact written before runs accumulated holds one median."""
    return list(point.get('runs') or ([point['wall_sec']] if 'wall_sec' in point else []))


def write_result(
    impl: str, tier: str, add_latency_ms: float, results: list[dict], meta: list[dict], warmup: dict | None
) -> None:
    """Merge one invocation into docs/roundtrip.json: counts refresh, sweep runs accumulate.

    The counts and per-video detail are the last repeat's, as they were before repeats
    existed. Only the sweep keeps history, because only the sweep is a timing.
    """
    result = results[-1]
    data = json.loads(OUT.read_text()) if OUT.exists() else {}
    data['measured_at'] = datetime.now(UTC).isoformat(timespec='seconds')
    data['method'] = (
        'counting proxy on :9000 forwarding to compute-service; bytes are JSON request+response bodies; '
        'pixeltable is structural: no compute-service dependency exists to measure'
    )
    data.setdefault(
        'pixeltable',
        {
            'ingest': {'requests_per_video': 0, 'bytes_per_video': 0},
            'agent': {'requests_per_query': 0, 'bytes_per_query': 0},
            'basis': 'structural: the models run in its own process, so no compute-service call exists to count',
        },
    )
    entry = data.setdefault(impl, {})
    agent_records = [r.pop('_agent_records') for r in results]
    entry['ingest'] = {'tier': tier, **result['ingest']}
    entry['agent'] = result['agent']
    entry['paths_called'] = result['paths_called']
    point = merge_sweep(entry, add_latency_ms, results, meta, warmup)
    entry['sweep'][str(int(add_latency_ms))] = point
    OUT.write_text(json.dumps(data, indent=1) + '\n')
    print(f'wrote {OUT} (agent calls seen: {agent_records[-1]})')
    print(f'sweep {int(add_latency_ms)}ms: median {point["wall_sec"]}s over n={point["n"]} {point["runs"]}')


def _run_meta(client: httpx.Client, impl: str) -> dict:
    """When a run started and what it started against, read before its first ingest."""
    return {
        'started_at': datetime.now(UTC).isoformat(timespec='seconds'),
        'corpus_before': corpus_size(client, impl),
        # The machine is not quiet by construction; a run under twice the load of its
        # neighbours is the first suspect when a point does not resolve.
        'host_load_1m': round(os.getloadavg()[0], 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Measure requests and bytes across the compute-service boundary')
    parser.add_argument('--impl', required=True, choices=['supabase', 'convex'])
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--auth-token', default='')
    parser.add_argument('--tier', default='large')
    parser.add_argument('--videos', type=int, default=0, help='Cap the ingest count; default is the whole tier')
    parser.add_argument('--agent-iterations', type=int, default=1)
    parser.add_argument('--listen-port', type=int, default=9000)
    parser.add_argument('--upstream', default='http://127.0.0.1:9100')
    parser.add_argument('--add-latency-ms', type=float, default=0.0)
    parser.add_argument(
        '--repeats',
        type=int,
        default=1,
        help='Ingest sweeps to run at this latency; the sweep point keeps every wall time, so n grows',
    )
    parser.add_argument(
        '--discard-warmup',
        action='store_true',
        help='Ingest once before the repeats and record it as warmup_wall_sec, outside the runs',
    )
    args = parser.parse_args()
    if args.repeats < 1:
        sys.exit('--repeats must be at least 1')

    videos = videos_for(args.tier)
    if args.videos:
        videos = videos[: args.videos]
    if not videos:
        sys.exit(f'no {args.tier}-tier videos. Run: python fixtures/videos/generate.py --tier {args.tier}')

    proxy = _Proxy(args.listen_port, args.upstream, args.add_latency_ms)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    print(
        f'proxy on :{args.listen_port} -> {args.upstream}, +{args.add_latency_ms}ms per request; '
        f'{len(videos)} videos on {args.impl} x{args.repeats}'
    )
    results: list[dict] = []
    meta: list[dict] = []
    warmup = None
    try:
        with httpx.Client(
            base_url=args.base_url.rstrip('/'),
            headers=auth_headers(args.impl, args.auth_token),
            timeout=UPSTREAM_TIMEOUT,
        ) as client:
            if args.discard_warmup:
                print('warm-up (recorded apart from the runs)')
                warmup = _run_meta(client, args.impl)
                warmup_result = measure(client, args.impl, videos, proxy, args.agent_iterations)
                warmup['wall_sec'] = warmup_result['ingest']['wall_sec']
            # Each repeat re-ingests the same videos, which is what running this script
            # twice already did. Nothing here resets the consumer between repeats, which is
            # why each run records the corpus it started against.
            for run in range(args.repeats):
                if args.repeats > 1:
                    print(f'run {run + 1}/{args.repeats}')
                meta.append({**_run_meta(client, args.impl), 'index': run})
                results.append(measure(client, args.impl, videos, proxy, args.agent_iterations))
    finally:
        proxy.shutdown()
        proxy.server_close()
    write_result(args.impl, args.tier, args.add_latency_ms, results, meta, warmup)
    return 0


if __name__ == '__main__':
    sys.exit(main())
