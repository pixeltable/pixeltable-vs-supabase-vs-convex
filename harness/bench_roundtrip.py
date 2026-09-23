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
runs at 0/20/80 produce the sweep.

Pixeltable's row is written with basis 'structural': it has no compute-service call to
count, which is a fact about the code, not a measurement. The two that do have one are
the rows this script fills.

docs/roundtrip.json is committed; harness/check_docs.py holds the published cells to it.
"""

from __future__ import annotations

import argparse
import json
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
                body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
                if server.add_latency_ms:
                    time.sleep(server.add_latency_ms / 1000)
                resp = server.client.request(
                    self.command,
                    f'{server.upstream}{self.path}',
                    content=body,
                    headers={'Content-Type': 'application/json'},
                )
                with server.lock:
                    server.records.append({'path': self.path, 'req_bytes': len(body), 'resp_bytes': len(resp.content)})
                self.send_response(resp.status_code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(resp.content)))
                self.end_headers()
                self.wfile.write(resp.content)

        return Handler


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


def write_result(impl: str, tier: str, add_latency_ms: float, result: dict) -> None:
    """Merge one run into docs/roundtrip.json: counts refresh, sweep entries accumulate."""
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
    agent_records = result.pop('_agent_records')
    entry['ingest'] = {'tier': tier, **result['ingest']}
    entry['agent'] = result['agent']
    entry['paths_called'] = result['paths_called']
    entry.setdefault('sweep', {})[str(int(add_latency_ms))] = {
        'wall_sec': result['ingest']['wall_sec'],
        'videos': result['ingest']['videos'],
        'requests': result['ingest']['requests'],
    }
    OUT.write_text(json.dumps(data, indent=1) + '\n')
    print(f'wrote {OUT} (agent calls seen: {agent_records})')


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
    args = parser.parse_args()

    videos = videos_for(args.tier)
    if args.videos:
        videos = videos[: args.videos]
    if not videos:
        sys.exit(f'no {args.tier}-tier videos. Run: python fixtures/videos/generate.py --tier {args.tier}')

    proxy = _Proxy(args.listen_port, args.upstream, args.add_latency_ms)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    print(
        f'proxy on :{args.listen_port} -> {args.upstream}, +{args.add_latency_ms}ms per request; '
        f'{len(videos)} videos on {args.impl}'
    )
    try:
        with httpx.Client(
            base_url=args.base_url.rstrip('/'),
            headers=auth_headers(args.impl, args.auth_token),
            timeout=UPSTREAM_TIMEOUT,
        ) as client:
            result = measure(client, args.impl, videos, proxy, args.agent_iterations)
    finally:
        proxy.shutdown()
        proxy.server_close()
    write_result(args.impl, args.tier, args.add_latency_ms, result)
    return 0


if __name__ == '__main__':
    sys.exit(main())
