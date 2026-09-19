#!/usr/bin/env python3
"""Time the agent endpoint when generation calls a hosted chat model.

    OPENROUTER_API_KEY=sk-or-... python harness/bench_hosted.py --supabase-token "$SECRET"

Each implementation's local generation model is swapped for the same hosted model over
an OpenAI-compatible endpoint. On Pixeltable the swap is a schema change - the answer is
already a computed column and the hosted function carries the rate-limit scheduler, so
pacing and retries are the platform's job. On the other two the swap is a code change:
the retry loop, Retry-After handling and backoff are application code, and the lines it
takes are counted with the rest of the diff.

Questions are fired at the agent endpoint concurrently, so the hosted model's rate limit
is real backpressure rather than a fast path. Wall time, per-request latency, retries
and failures are reported per implementation; on Pixeltable retries happen inside the
scheduler and the response carries no attempt count.

Nothing here is committed to the implementations - the diffs live in harness/hosted/ and
are reverted when the run ends. The run is gated on OPENROUTER_API_KEY the way the
destructive suite is gated on --destructive; the key reaches each service through its
own config path and never lands in the repo or the report.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.bench_evolve import _start_convex_watcher, _stop_convex_watcher, loc_of_patch, patch, run  # noqa: E402
from harness.benchmark import AGENT_QUESTIONS, percentile  # noqa: E402
from harness.conftest import PATHS, _auto_discover_pixeltable_url, auth_headers  # noqa: E402

HOSTED = ROOT / 'harness' / 'hosted'
OUT = ROOT / 'docs' / 'hosted.json'
OPENROUTER_BASE = 'https://openrouter.ai/api/v1'
SUPABASE_APP = ROOT / 'supabase-app'
CONVEX_APP = ROOT / 'convex-app'
SUPABASE_URL = 'http://127.0.0.1:54321'
CONVEX_URL = 'http://127.0.0.1:3211'
PXT_CONFIG = Path(os.environ.get('PIXELTABLE_HOME', str(Path.home() / '.pixeltable'))) / 'config.toml'


def pxt_python() -> str:
    """The interpreter that owns the pxt install; `python` here need not have pixeltable."""
    pxt = shutil.which('pxt')
    if not pxt:
        raise RuntimeError('pxt is not on PATH')
    return str(Path(pxt).resolve().parent / 'python')


def _wait_ready(url: str, headers: dict | None = None, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, headers=headers or {}, timeout=5).status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError(f'{url} did not come up in {timeout}s')


def fire_agent(impl: str, base_url: str, headers: dict, questions: list[str], workers: int) -> dict:
    """Fire the question list at the agent endpoint with a worker pool.

    One client per worker so connection setup is not part of the request time, the same
    shape as the load measurement in benchmark.py. `attempts` comes back on the rows of
    the two implementations whose retry loop is application code; on Pixeltable retries
    are internal to the scheduler and the field is absent.
    """
    method, path = PATHS[impl]['agent']
    clients = [httpx.Client(base_url=base_url, headers=headers, timeout=600.0) for _ in range(workers)]

    def ask(i: int, question: str) -> dict:
        started = time.monotonic()
        try:
            resp = clients[i % workers].request(method, path, json={'question': question})
            row = {}
            if resp.headers.get('content-type', '').startswith('application/json'):
                row = (resp.json().get('rows') or [{}])[0]
            return {
                'sec': time.monotonic() - started,
                'status': resp.status_code,
                'ok': resp.is_success and bool(row.get('answer')),
                'attempts': row.get('attempts'),
            }
        except Exception:
            return {'sec': time.monotonic() - started, 'status': 0, 'ok': False, 'attempts': None}

    started = time.monotonic()
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda iq: ask(*iq), enumerate(questions)))
    wall = time.monotonic() - started
    for client in clients:
        client.close()

    done = [r['sec'] for r in results if r['ok']]
    attempts = [r['attempts'] for r in results if r['attempts']]
    return {
        'succeeded': len(done),
        'failed': len(results) - len(done),
        'wall_sec': round(wall, 2),
        'p50_sec': round(percentile(done, 50), 3) if done else None,
        'p95_sec': round(percentile(done, 95), 3) if done else None,
        'retries': sum(a - 1 for a in attempts) if attempts else 'n/a: scheduler-internal',
        'statuses': sorted({r['status'] for r in results}),
    }


# ----------------------------------------------------------------- pixeltable


def _openai_config(key: str) -> str:
    """Point the openai function group at OpenRouter. Returns the config to restore.

    The service process reads ~/.pixeltable/config.toml at startup, which is how the key
    reaches it without touching app.py or the environment of a long-lived daemon.
    """
    original = PXT_CONFIG.read_text() if PXT_CONFIG.exists() else ''
    section = f'[openai]\napi_key = "{key}"\nbase_url = "{OPENROUTER_BASE}"\n'
    if '[openai]' in original:
        text = re.sub(r'\[openai\]\n[^[]*', section, original)
    else:
        text = f'{original.rstrip()}\n\n{section}'
    PXT_CONFIG.write_text(text)
    return original


def _empty_conversations() -> None:
    run([pxt_python(), '-c', "import pixeltable as pxt; pxt.get_table('media.conversations').delete()"])


def hosted_pixeltable(key: str, questions: list[str], workers: int) -> dict:
    app = ROOT / 'pixeltable' / 'app.py'
    original = app.read_text()
    patch(app, HOSTED / 'pixeltable_imports.patch')
    patch(app, HOSTED / 'pixeltable_answer.patch')
    saved_config = _openai_config(key)
    try:
        # Existing conversation rows would recompute against the hosted model on the
        # schema update and spend the rate limit on backfill, so the table starts empty.
        _empty_conversations()
        run(['pxt', 'schema', 'update', 'app.py', 'media', '-f'], cwd=app.parent)
        run(['pxt', 'service', 'restart', 'app.py', 'media'], cwd=app.parent)
        url = _auto_discover_pixeltable_url()
        if not url:
            raise RuntimeError('pixeltable service did not come back after restart')
        _wait_ready(f'{url}/videos')
        result = fire_agent('pixeltable', url, {}, questions, workers)
    finally:
        app.write_text(original)
        if saved_config:
            PXT_CONFIG.write_text(saved_config)
        else:
            PXT_CONFIG.unlink(missing_ok=True)
        run(['pxt', 'schema', 'update', 'app.py', 'media', '-f', '--allow-destructive'], cwd=app.parent)
        run(['pxt', 'service', 'restart', 'app.py', 'media'], cwd=app.parent)
        _empty_conversations()
    result.update(
        lines_written=loc_of_patch(HOSTED / 'pixeltable_imports.patch')
        + loc_of_patch(HOSTED / 'pixeltable_answer.patch'),
        files_touched=1,
        note='schema swap: the answer column re-points at chat_completions, whose scheduler paces and retries',
    )
    return result


# ------------------------------------------------------------------- supabase


def hosted_supabase(key: str, token: str, questions: list[str], workers: int) -> dict:
    index = SUPABASE_APP / 'supabase' / 'functions' / 'api' / 'index.ts'
    original = index.read_text()
    names = ['supabase_helper', 'supabase_call', 'supabase_return']
    for name in names:
        patch(index, HOSTED / f'{name}.patch')
    env_file = SUPABASE_APP / 'supabase' / 'functions' / '.env'
    # The file already exists in a working local stack - COMPUTE_SERVICE_URL lives here.
    # Replace only our key, and put the original content back afterwards.
    env_original = env_file.read_text() if env_file.exists() else ''
    kept = [line for line in env_original.splitlines() if not line.startswith('OPENROUTER_API_KEY=')]
    env_file.write_text('\n'.join(kept + [f'OPENROUTER_API_KEY={key}']) + '\n')
    headers = auth_headers('supabase', token)
    try:
        # The .env file reaches the edge runtime only at container creation, so this is
        # a stack restart rather than a function reload. Data survives in the volumes.
        run(['npx', 'supabase', 'stop'], cwd=SUPABASE_APP)
        run(['npx', 'supabase', 'start'], cwd=SUPABASE_APP)
        _wait_ready(f'{SUPABASE_URL}/functions/v1/api/videos', headers)
        result = fire_agent('supabase', SUPABASE_URL, headers, questions, workers)
    finally:
        index.write_text(original)
        if env_original:
            env_file.write_text(env_original)
        else:
            env_file.unlink(missing_ok=True)
        run(['npx', 'supabase', 'stop'], cwd=SUPABASE_APP)
        run(['npx', 'supabase', 'start'], cwd=SUPABASE_APP)
    result.update(
        lines_written=sum(loc_of_patch(HOSTED / f'{name}.patch') for name in names),
        files_touched=1,
        note='direct OpenRouter call from the Edge Function; the retry loop and backoff are application code',
    )
    return result


# --------------------------------------------------------------------- convex


def hosted_convex(key: str, questions: list[str], workers: int) -> dict:
    agent_ts = CONVEX_APP / 'convex' / 'agent.ts'
    original = agent_ts.read_text()
    names = ['convex_helper', 'convex_call', 'convex_return', 'convex_returntype']
    for name in names:
        patch(agent_ts, HOSTED / f'{name}.patch')
    try:
        run(['npx', 'convex', 'env', 'set', 'OPENROUTER_API_KEY', key], cwd=CONVEX_APP)
        _stop_convex_watcher()
        run(['npx', 'convex', 'dev', '--once'], cwd=CONVEX_APP)
        _start_convex_watcher(CONVEX_APP)
        _wait_ready(f'{CONVEX_URL}/videos')
        result = fire_agent('convex', CONVEX_URL, {}, questions, workers)
    finally:
        agent_ts.write_text(original)
        subprocess.run(['npx', 'convex', 'env', 'remove', 'OPENROUTER_API_KEY'], cwd=CONVEX_APP, capture_output=True)
        _stop_convex_watcher()
        run(['npx', 'convex', 'dev', '--once'], cwd=CONVEX_APP)
        _start_convex_watcher(CONVEX_APP)
    result.update(
        lines_written=sum(loc_of_patch(HOSTED / f'{name}.patch') for name in names),
        files_touched=1,
        note='same retry contract as the Edge Function, written in the action',
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--impl', action='append', choices=sorted(PATHS))
    parser.add_argument('--questions', type=int, default=12)
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--supabase-token', default='')
    args = parser.parse_args()

    key = os.environ.get('OPENROUTER_API_KEY')
    if not key:
        sys.exit(
            'OPENROUTER_API_KEY is not set. The hosted tier is gated on a real key the way '
            'the destructive suite is gated on --destructive.'
        )

    questions = [AGENT_QUESTIONS[i % len(AGENT_QUESTIONS)] for i in range(args.questions)]
    results: dict = {
        'measured_at': datetime.now(UTC).isoformat(timespec='seconds'),
        'endpoint': f'{OPENROUTER_BASE} (openai-compatible)',
        'model': 'meta-llama/llama-3.3-8b-instruct:free',
        'questions': args.questions,
        'workers': args.workers,
    }
    for impl in args.impl or sorted(PATHS):
        print(f'--- {impl} ---', flush=True)
        if impl == 'supabase' and not args.supabase_token:
            print('  skipped: --supabase-token required')
            continue
        result = {
            'pixeltable': lambda: hosted_pixeltable(key, questions, args.workers),
            'supabase': lambda: hosted_supabase(key, args.supabase_token, questions, args.workers),
            'convex': lambda: hosted_convex(key, questions, args.workers),
        }[impl]()
        results[impl] = result
        print(
            f'  {result["succeeded"]}/{args.questions} ok in {result["wall_sec"]}s wall, '
            f'p50 {result["p50_sec"]}s, {result["lines_written"]} lines in {result["files_touched"]} file(s)',
            flush=True,
        )

    existing = json.loads(OUT.read_text()) if OUT.exists() else {}
    existing.update(results)
    OUT.write_text(json.dumps(existing, indent=2) + '\n')
    print(f'wrote {OUT.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
