#!/usr/bin/env python3
"""Time the agent endpoint when generation calls a hosted chat model.

    OPENROUTER_API_KEY=sk-or-... python harness/bench_hosted.py --supabase-token "$SECRET"

Each implementation's local generation model is swapped for the same hosted model on
OpenRouter. On Pixeltable the swap is a schema change - the answer is already a computed
column and the openrouter UDF paces and retries on its own request-rate pool, so those
are the platform's job. On the other two the swap is a code change: the retry loop,
Retry-After handling and backoff are application code, and the lines it takes are
counted with the rest of the diff.

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
import shutil
import socket
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
from harness.conftest import PATHS, auth_headers  # noqa: E402

HOSTED = ROOT / 'harness' / 'hosted'
OUT = ROOT / 'docs' / 'hosted.json'
OPENROUTER_BASE = 'https://openrouter.ai/api/v1'
HOSTED_MODEL = 'nvidia/nemotron-3-super-120b-a12b'
# The untimed warm-up asks a question no timed request uses, so the row it writes on
# Pixeltable can be told apart from the measured ones when the cells' error state is read.
WARMUP_QUESTION = 'Summarize what the videos cover.'
SUPABASE_APP = ROOT / 'supabase-app'
CONVEX_APP = ROOT / 'convex-app'
# Defaults, not assumptions. Both are overridable so a leg can be pointed at a deployed
# project; nothing else in this file knows where the endpoint lives.
SUPABASE_URL = 'http://127.0.0.1:54321'
CONVEX_URL = 'http://127.0.0.1:3211'


def pxt_bin() -> str:
    """The pxt that can load app.py: the repo venv's, which has transformers. The Cellar
    install on PATH serves `service list` fine but cannot load the app file."""
    venv_pxt = ROOT / '.venv' / 'bin' / 'pxt'
    return str(venv_pxt) if venv_pxt.exists() else shutil.which('pxt') or 'pxt'


def pxt_python() -> str:
    """The interpreter that owns the pxt install; `python` here need not have pixeltable."""
    return str(Path(pxt_bin()).resolve().parent / 'python')


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

    # Untimed warm-up, the same shape as agent_latency in benchmark.py: each stack is
    # restarted immediately before this fires, and the first request pays cold client
    # and service init that has nothing to do with the model being measured. The
    # sentinel question marks the row it leaves behind, so _cell_errors can exclude it.
    warmup = ask(0, WARMUP_QUESTION)
    started = time.monotonic()
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda iq: ask(*iq), enumerate(questions)))
    wall = time.monotonic() - started
    for client in clients:
        client.close()

    done = [r['sec'] for r in results if r['ok']]
    attempts = [r['attempts'] for r in results if r['attempts']]
    # Only successful responses carry an attempt count on the two hand-written loops: a
    # request that exhausts its retries throws, and the 500 body holds no count. Empty
    # attempts on those two therefore means no request succeeded; on Pixeltable it is
    # always empty because the retries are the scheduler's.
    if attempts:
        retries: int | str = sum(a - 1 for a in attempts)
    elif impl == 'pixeltable':
        retries = 'n/a: scheduler-internal'
    else:
        retries = 'n/a: no successful request returned one'
    return {
        'succeeded': len(done),
        'failed': len(results) - len(done),
        'warmup_ok': warmup['ok'],
        'wall_sec': round(wall, 2),
        'p50_sec': round(percentile(done, 50), 3) if done else None,
        'p95_sec': round(percentile(done, 95), 3) if done else None,
        'retries': retries,
        'statuses': sorted({r['status'] for r in results}),
    }


# ----------------------------------------------------------------- pixeltable


def _drop_conversations(env: dict) -> None:
    """Drop the derived conversations table so `schema update` recreates it.

    pxt refuses to change an existing computed column's expression in place, and
    re-pointing `answer` at the hosted model is exactly that. The table holds only
    agent results that re-derive on each question, so dropping it loses nothing.
    """
    run(
        [pxt_python(), '-c', "import pixeltable as pxt; pxt.drop_table('media.conversations', force=True)"],
        env=env,
    )


def _cell_errors(env: dict) -> dict:
    """Per-cell error state of the timed answers this run just wrote, read before the
    restore drops the conversations table. The HTTP layer only sees 200s: a failed
    answer is a null cell, and the reason sits in the row's errormsg/errortype - detail
    the platform keeps that a status code cannot carry. The warm-up's row is filtered
    out by its sentinel question, so `empty` and `rows` describe the timed set only.
    """
    code = (
        'import json, pixeltable as pxt\n'
        f'WARMUP = {json.dumps(WARMUP_QUESTION)}\n'
        "t = pxt.get_table('media.conversations')\n"
        'sel = t.select(q=t.question, ans=t.answer, err=t.answer.errormsg, et=t.answer.errortype)\n'
        'rows = [dict(r) for r in sel.collect()]\n'
        "rows = [r for r in rows if r['q'] != WARMUP]\n"
        "errs = [str(r['et']) + ': ' + str(r['err']) for r in rows if r['err']]\n"
        "empty = sum(1 for r in rows if r['err'] is None and not r['ans'])\n"
        "print(json.dumps({'errors': errs, 'empty': empty, 'rows': len(rows)}))\n"
    )
    try:
        # The last stdout line is the JSON; pxt announces its catalog connection first.
        out = run([pxt_python(), '-c', code], env=env, timeout=180)
        return json.loads(out.strip().splitlines()[-1])
    except Exception as exc:
        return {'unavailable': str(exc)[:200]}


def _free_port() -> str:
    """A loopback port nothing holds, for the run's private pxt daemon."""
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return str(s.getsockname()[1])


def _wait_daemon(port: str, timeout: float = 60.0) -> None:
    """Poll the run's private daemon until /api/health reports this venv's install.

    pxt restarts a daemon whose install differs from the invoking client's, so two installs
    sharing the default port respawn each other in a loop. PXT_PORT gives this run its own
    port, pidfile and daemon; checking the responder's install dir here turns a foreign
    daemon on our port into a clear failure instead of a dropped connection mid-schema.
    """
    expected = str(Path(pxt_bin()).resolve().parent.parent)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            health = httpx.get(f'http://127.0.0.1:{port}/api/health', timeout=5).json()
            if str(health.get('pxt_install_dir', '')).startswith(expected):
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError(f'pxt daemon on port {port} did not come up as the venv install in {timeout}s')


def _service_url() -> str | None:
    """The endpoint in media/api's service record, written by the serving process itself.

    Reading the record avoids `pxt service list`, which would resolve the default-port
    daemon - and any install mismatch there restarts a daemon we do not own.
    """
    home = Path(os.environ.get('PIXELTABLE_HOME', '~/.pixeltable')).expanduser()
    try:
        endpoint = json.loads((home / 'services' / 'media' / 'api.json').read_text()).get('endpoint')
    except (OSError, ValueError):
        return None
    return endpoint.rstrip('/') if endpoint else None


def hosted_pixeltable(key: str, model: str, questions: list[str], workers: int) -> dict:
    # No base_url parameter, deliberately. The other two legs take one because they only
    # need an endpoint to fire at. This one starts a private daemon, applies the schema and
    # brings up the service itself, so pointing it at a deployed database is not a flag: it
    # is `pxt db update` against a hosted uri and a service that lives there. The
    # asymmetry is worth seeing rather than papering over with an option that would not work.

    app = ROOT / 'pixeltable' / 'app.py'
    original = app.read_text()
    # The daemon resolves credentials from the environment it was started with, and
    # services it spawns inherit that environment. Starting it with OPENROUTER_API_KEY
    # set points every service at OpenRouter without touching config.toml. The daemon
    # also rejects a request whose config env it does not share, so every daemon-bound
    # call in this leg carries the same env. PXT_PORT gives the run a private daemon on
    # its own port: pxt respawns a daemon whose install differs from the caller's, and
    # another install sharing the default port would keep replacing ours mid-run.
    port = _free_port()
    env = {'PXT_PORT': port, 'OPENROUTER_API_KEY': key, 'HOSTED_MODEL': model}
    try:
        # Applied inside the try: if a patch's anchor has gone stale, the finally still
        # puts the original text back instead of leaving the file half-patched.
        patch(app, HOSTED / 'pixeltable_imports.patch')
        patch(app, HOSTED / 'pixeltable_answer.patch')
        try:
            run([pxt_bin(), 'daemon', 'stop', '--force'], cwd=app.parent, env=env)
        except Exception as exc:
            print(f'  daemon stop failed (continuing): {exc}', flush=True)
        run([pxt_bin(), 'daemon', 'start'], cwd=app.parent, env=env)
        _wait_daemon(port)
        _drop_conversations(env)
        run([pxt_bin(), 'schema', 'update', 'app.py', 'media', '-f'], cwd=app.parent, env=env)
        # `service update` respawns the service process against the restarted daemon,
        # which is how the key reaches it. `service restart` is not the
        # same path: it asserts `project_root is not None` when the running service was
        # not started from a project directory.
        run([pxt_bin(), 'service', 'update', 'app.py', 'media', '-f'], cwd=app.parent, env=env)
        url = _service_url()
        if not url:
            raise RuntimeError('pixeltable service did not come back after restart')
        _wait_ready(f'{url}/videos')
        result = fire_agent('pixeltable', url, {}, questions, workers)
        result['cell_errors'] = _cell_errors(env)
    finally:
        # Each restore step is guarded so a single failure cannot skip the rest of the
        # cleanup; the schema and the service must both come back to the local variant.
        # The daemon stop+start runs before the schema update: a dead daemon fails the
        # update and leaves the service blocked on a schema that never landed. The empty
        # values drop the key from the respawned daemon and the service it starts.
        try:
            app.write_text(original)
        except OSError as exc:
            print(f'  restore step failed: {exc}', flush=True)
        clean_env = {'PXT_PORT': port, 'OPENROUTER_API_KEY': '', 'HOSTED_MODEL': ''}
        for cmd in (
            [
                pxt_python(),
                '-c',
                "import pixeltable as pxt; pxt.drop_table('media.conversations', force=True, if_not_exists='ignore')",
            ],
            [pxt_bin(), 'daemon', 'stop', '--force'],
            [pxt_bin(), 'daemon', 'start'],
        ):
            try:
                run(cmd, cwd=app.parent, env=clean_env)
            except Exception as exc:
                print(f'  restore step failed: {exc}', flush=True)
        try:
            _wait_daemon(port)
            run(
                [pxt_bin(), 'schema', 'update', 'app.py', 'media', '-f', '--allow-destructive'],
                cwd=app.parent,
                env=clean_env,
            )
            run([pxt_bin(), 'service', 'update', 'app.py', 'media', '-f'], cwd=app.parent, env=clean_env)
            # the private daemon's work is done; the service runs independently of it
            run([pxt_bin(), 'daemon', 'stop', '--force'], cwd=app.parent, env=clean_env)
        except Exception as exc:
            print(f'  restore step failed: {exc}', flush=True)
    result.update(
        lines_written=loc_of_patch(HOSTED / 'pixeltable_imports.patch')
        + loc_of_patch(HOSTED / 'pixeltable_answer.patch'),
        files_touched=1,
        note='schema swap: the answer column re-points at openrouter.chat_completions, a request-rate pool',
    )
    return result


# ------------------------------------------------------------------- supabase


def hosted_supabase(
    key: str, token: str, model: str, questions: list[str], workers: int, base_url: str = SUPABASE_URL
) -> dict:
    index = SUPABASE_APP / 'supabase' / 'functions' / 'api' / 'index.ts'
    original = index.read_text()
    names = ['supabase_helper', 'supabase_call', 'supabase_return']
    env_file = SUPABASE_APP / 'supabase' / 'functions' / '.env'
    # The file already exists in a working local stack - COMPUTE_SERVICE_URL lives here.
    # Replace only our hosted-model variables, and put the original content back after.
    env_original = env_file.read_text() if env_file.exists() else ''
    headers = auth_headers('supabase', token)
    try:
        for name in names:
            patch(index, HOSTED / f'{name}.patch')
        kept = [
            line for line in env_original.splitlines() if not line.startswith(('OPENROUTER_API_KEY=', 'HOSTED_MODEL='))
        ]
        hosted = [f'OPENROUTER_API_KEY={key}', f'HOSTED_MODEL={model}']
        env_file.write_text('\n'.join(kept + hosted) + '\n')
        # The .env file reaches the edge runtime only at container creation, so this is
        # a stack restart rather than a function reload. Data survives in the volumes.
        run(['npx', 'supabase', 'stop'], cwd=SUPABASE_APP)
        run(['npx', 'supabase', 'start'], cwd=SUPABASE_APP)
        _wait_ready(f'{base_url}/functions/v1/api/videos', headers)
        result = fire_agent('supabase', base_url, headers, questions, workers)
    finally:
        # Each restore step is guarded so a single failure cannot skip the rest of the
        # cleanup; the env file holds the hosted key until it is put back, so its
        # restore must not depend on the index restore succeeding.
        try:
            index.write_text(original)
        except OSError as exc:
            print(f'  restore step failed: {exc}', flush=True)
        try:
            if env_original:
                env_file.write_text(env_original)
            else:
                env_file.unlink(missing_ok=True)
        except OSError as exc:
            print(f'  restore step failed: {exc}', flush=True)
        for cmd in (['npx', 'supabase', 'stop'], ['npx', 'supabase', 'start']):
            try:
                run(cmd, cwd=SUPABASE_APP)
            except Exception as exc:
                print(f'  restore step failed: {exc}', flush=True)
    result.update(
        lines_written=sum(loc_of_patch(HOSTED / f'{name}.patch') for name in names),
        files_touched=1,
        note='direct OpenRouter call from the Edge Function; the retry loop and backoff are application code',
    )
    return result


# --------------------------------------------------------------------- convex


def hosted_convex(key: str, model: str, questions: list[str], workers: int, base_url: str = CONVEX_URL) -> dict:
    agent_ts = CONVEX_APP / 'convex' / 'agent.ts'
    original = agent_ts.read_text()
    names = ['convex_helper', 'convex_call', 'convex_return', 'convex_returntype']
    try:
        for name in names:
            patch(agent_ts, HOSTED / f'{name}.patch')
        run(['npx', 'convex', 'env', 'set', 'OPENROUTER_API_KEY', key], cwd=CONVEX_APP)
        run(['npx', 'convex', 'env', 'set', 'HOSTED_MODEL', model], cwd=CONVEX_APP)
        _stop_convex_watcher()
        run(['npx', 'convex', 'dev', '--once'], cwd=CONVEX_APP)
        _start_convex_watcher(CONVEX_APP)
        _wait_ready(f'{base_url}/videos')
        result = fire_agent('convex', base_url, {}, questions, workers)
    finally:
        # Same guarded restore shape as the other legs: one failed step cannot skip the
        # rest. The env vars hold the hosted key, so their removal gets its own guard
        # with a timeout - the CLI must not be able to hang the cleanup.
        try:
            agent_ts.write_text(original)
        except OSError as exc:
            print(f'  restore step failed: {exc}', flush=True)
        for var in ('OPENROUTER_API_KEY', 'HOSTED_MODEL'):
            try:
                run(['npx', 'convex', 'env', 'remove', var], cwd=CONVEX_APP, timeout=120)
            except Exception as exc:
                print(f'  restore step failed: {exc}', flush=True)
        try:
            _stop_convex_watcher()
            run(['npx', 'convex', 'dev', '--once'], cwd=CONVEX_APP)
        except Exception as exc:
            print(f'  restore step failed: {exc}', flush=True)
        try:
            _start_convex_watcher(CONVEX_APP)
        except Exception as exc:
            print(f'  restore step failed: {exc}', flush=True)
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
    parser.add_argument('--model', default=HOSTED_MODEL)
    parser.add_argument('--supabase-url', default=SUPABASE_URL, help='point the Supabase leg at a deployed project')
    parser.add_argument('--convex-url', default=CONVEX_URL, help='point the Convex leg at a cloud deployment')
    args = parser.parse_args()
    if args.questions < 1:
        parser.error('--questions must be at least 1')
    if args.workers < 1:
        parser.error('--workers must be at least 1')

    key = os.environ.get('OPENROUTER_API_KEY')
    if not key:
        sys.exit(
            'OPENROUTER_API_KEY is not set. The hosted tier is gated on a real key the way '
            'the destructive suite is gated on --destructive.'
        )

    questions = [AGENT_QUESTIONS[i % len(AGENT_QUESTIONS)] for i in range(args.questions)]
    measured_at = datetime.now(UTC).isoformat(timespec='seconds')
    results: dict = {
        'measured_at': measured_at,
        'endpoint': f'{OPENROUTER_BASE} (openai-compatible)',
        'model': args.model,
        # 1024, not the local agent's 256: the hosted model spends reasoning tokens
        # before content, and a 256 cap returns finish_reason=length with an empty answer.
        'max_tokens': 1024,
        'questions': args.questions,
        'workers': args.workers,
    }
    for impl in args.impl or sorted(PATHS):
        print(f'--- {impl} ---', flush=True)
        if impl == 'supabase' and not args.supabase_token:
            print('  skipped: --supabase-token required')
            continue
        result = {
            'pixeltable': lambda: hosted_pixeltable(key, args.model, questions, args.workers),
            'supabase': lambda: hosted_supabase(
                key, args.supabase_token, args.model, questions, args.workers, args.supabase_url
            ),
            'convex': lambda: hosted_convex(key, args.model, questions, args.workers, args.convex_url),
        }[impl]()
        # Stamped per leg: a run over a subset of implementations must not make stale
        # legs look freshly measured by updating only the file-level fields.
        result['measured_at'] = measured_at
        result['model'] = args.model
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
