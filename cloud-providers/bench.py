"""One harness, one method, for every number on /compare/cloud-providers.

    python bench.py run      # every test below; writes results/<date>/<client region>/run-<UTC time>.json
    python bench.py near     # latency and reads only, for a client in a second region
    python bench.py cold     # only the cold-start pass (needs 20 minutes of silence first)

Method, the same for every target:
- latency: 5 untimed requests, then SAMPLES (300) timed sequential requests on one kept-alive connection.
  Every compute target runs the same handler: read {title, body}, return title_upper and summary, store nothing.
- reads: one seeded row read SAMPLES times by primary key, after 5 untimed reads. Every database stores the same
  row: docs(id text primary key, title text, body text).
- batch: 100 rows in one call, repeated 5 times; the median is published.
- load: open `c` connections and send `c` untimed requests first, then keep `c` requests in flight for
  LOAD_SECONDS. Throughput is successes divided by the time from start to the last completion. HTTP and
  SQL targets both start the clock with warm connections, so neither pays for connection setup.
- media: 20 videos at concurrency 5. A background route is timed from submit until its job reports done.
- cold: after COLD_IDLE_MINUTES with no traffic to any target, the first request on a new connection,
  then a request on a second new connection, whose difference is the wake-up.
Endpoints and credentials come from the environment; .env.example lists every variable.
"""

import asyncio
import json
import os
import socket
import statistics
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

import aiohttp
import asyncpg  # type: ignore[import-not-found, import-untyped, unused-ignore]
import psycopg
from aggregate import SHARES_DEPLOYMENT_WITH

HERE = Path(__file__).resolve().parent
VIDEO = (HERE / 'fixtures' / 'sample.mpg').read_bytes()
LOAD_SECONDS = float(os.environ.get('LOAD_SECONDS', '15'))
COLD_IDLE_MINUTES = float(os.environ.get('COLD_IDLE_MINUTES', '20'))
SAMPLES = int(os.environ.get('SAMPLES', '300'))
WARMUP = 5
MEDIA_VIDEOS = int(
    os.environ.get('MEDIA_VIDEOS', '20')
)  # a smoke test sets this, LOAD_SECONDS and SKIP_RESILIENCE lower
UA = {'User-Agent': 'Pixeltable-Shootout-Harness/2.0 (+https://pixeltable.com/compare/cloud-providers)'}
E = os.environ

PXT = E['PXT_URL'].rstrip('/')
RAILWAY = E['RAILWAY_URL'].rstrip('/')
RENDER = E['RENDER_URL'].rstrip('/')
VERCEL = E['VERCEL_URL'].rstrip('/')
MODAL = E['MODAL_URL'].rstrip('/')
CF = E['CLOUDFLARE_URL'].rstrip('/')
CONVEX = E['CONVEX_URL'].rstrip('/')
SUPA = E['SUPABASE_URL'].rstrip('/') + '/rest/v1/docs'


def pxt_h():
    return {**UA, 'Authorization': f'Bearer {E["PXT_TOKEN"]}', 'Content-Type': 'application/json'}


def supa_h(extra=None):
    return {
        **UA,
        'apikey': E['SUPABASE_KEY'],
        'Authorization': f'Bearer {E["SUPABASE_KEY"]}',
        'Content-Type': 'application/json',
        **(extra or {}),
    }


def turso_h():
    return {**UA, 'Authorization': f'Bearer {E["TURSO_TOKEN"]}', 'Content-Type': 'application/json'}


def neon_h():
    return {**UA, 'Neon-Connection-String': E['NEON_DSN'], 'Content-Type': 'application/json'}


def key():
    return uuid.uuid4().hex[:12]


def stats(seconds):
    if not seconds:
        return {'count': 0}
    s = sorted(x * 1000 for x in seconds)
    pick = lambda q: s[min(len(s) - 1, int(round(q * (len(s) - 1))))]  # noqa: E731
    return {
        'count': len(s),
        'min_ms': round(s[0], 2),
        'p50_ms': round(statistics.median(s), 2),
        'mean_ms': round(statistics.mean(s), 2),
        'p95_ms': round(pick(0.95), 2),
        'p99_ms': round(pick(0.99), 2),
        'max_ms': round(s[-1], 2),
    }


def turso_stmt(sql, args):
    return {
        'requests': [
            {'type': 'execute', 'stmt': {'sql': sql, 'args': [{'type': 'text', 'value': a} for a in args]}},
            {'type': 'close'},
        ]
    }


# ---------------------------------------------------------------------------------------------------------
# Targets. An HTTP target is (method, url, headers, body(i)); a SQL target is a DSN and statements.
# `kind` says what one request does, which is what the page's groups compare.
# ---------------------------------------------------------------------------------------------------------

COMPUTE = {
    'Cloudflare Workers': (
        'POST',
        CF + '/compute',
        {**UA, 'Content-Type': 'application/json'},
        lambda i: {'title': f't-{i}', 'body': 'b'},
    ),
    'Railway': (
        'POST',
        RAILWAY + '/docs',
        {**UA, 'Content-Type': 'application/json'},
        lambda i: {'title': f't-{i}', 'body': 'b'},
    ),
    'Render': (
        'POST',
        RENDER + '/docs',
        {**UA, 'Content-Type': 'application/json'},
        lambda i: {'title': f't-{i}', 'body': 'b'},
    ),
    'Vercel': (
        'POST',
        VERCEL + '/docs',
        {**UA, 'Content-Type': 'application/json'},
        lambda i: {'title': f't-{i}', 'body': 'b'},
    ),
    'Modal': (
        'POST',
        MODAL + '/docs',
        {**UA, 'Content-Type': 'application/json'},
        lambda i: {'title': f't-{i}', 'body': 'b'},
    ),
    'Pixeltable Compute Route': ('POST', PXT + '/ingest/titles', None, lambda i: {'title': f't-{i}'}),
    'Pixeltable Compute Route (background=True)': (
        'POST',
        PXT + '/ingest/titles/async',
        None,
        lambda i: {'title': f't-{i}'},
    ),
    'Modal Async (.spawn)': (
        'POST',
        MODAL + '/docs/async',
        {**UA, 'Content-Type': 'application/json'},
        lambda i: {'title': f't-{i}', 'body': 'b'},
    ),
}

HTTP_WRITES = {
    'Neon Serverless PG': (
        'POST',
        E.get('NEON_HTTP_ENDPOINT', ''),
        None,
        lambda i: {'query': 'INSERT INTO docs (id, title, body) VALUES ($1, $2, $3)', 'params': [key(), f't-{i}', 'b']},
    ),
    'Turso libSQL': (
        'POST',
        E.get('TURSO_ENDPOINT', ''),
        None,
        lambda i: turso_stmt('INSERT INTO docs (id, title, body) VALUES (?, ?, ?)', [key(), f't-{i}', 'b']),
    ),
    'Supabase PostgREST': ('POST', SUPA, None, lambda i: {'id': key(), 'title': f't-{i}', 'body': 'b'}),
    'Convex': (
        'POST',
        CONVEX + '/api/mutation',
        {**UA, 'Content-Type': 'application/json'},
        lambda i: {'path': 'docs:insertDoc', 'args': {'title': f't-{i}', 'body': 'b'}, 'format': 'json'},
    ),
    'Cloudflare Workers (D1)': (
        'POST',
        CF + '/docs',
        {**UA, 'Content-Type': 'application/json'},
        lambda i: {'title': f't-{i}', 'body': 'b'},
    ),
    'Pixeltable Insert Route': ('POST', PXT + '/ingest/docs', None, lambda i: {'title': f't-{i}', 'body': 'b'}),
    'Pixeltable Insert Route (background=True)': (
        'POST',
        PXT + '/ingest/docs/async',
        None,
        lambda i: {'title': f't-{i}', 'body': 'b'},
    ),
}

SQL_WRITES = {
    'Railway Postgres': 'RAILWAY_PG_DSN',
    'Render Postgres': 'RENDER_PG_DSN',
    'Prisma Postgres': 'PRISMA_POSTGRES_DSN',
}

KIND = {
    **{name: 'http-compute' for name in COMPUTE},
    **{name: 'http-write' for name in HTTP_WRITES},
    **{name: 'sql-write' for name in SQL_WRITES},
}


def headers_for(name, h):
    if h is not None:
        return h
    if name.startswith('Pixeltable'):
        return pxt_h()
    return {
        'Neon Serverless PG': neon_h,
        'Turso libSQL': turso_h,
        'Supabase PostgREST': lambda: supa_h({'Prefer': 'return=minimal'}),
    }[name]()


def http_target(name):
    method, url, h, body = {**COMPUTE, **HTTP_WRITES}[name]
    return method, url, headers_for(name, h), body


# Which Cloudflare location answered (the suffix of cf-ray), per target: anycast can route one client's requests
# to a distant location for a while, and a latency row should be able to say where it was served from.
SERVED_FROM: dict[str, dict[str, int]] = {}


async def http_once(session, name, i):
    method, url, h, body = http_target(name)
    async with session.request(method, url, headers=h, json=None if body is None else body(i)) as r:
        await r.read()
        ray = r.headers.get('cf-ray')
        if ray:
            where = SERVED_FROM.setdefault(name, {})
            location = ray.rsplit('-', 1)[-1]
            where[location] = where.get(location, 0) + 1
        return r.status


def sql_insert(i):
    return 'INSERT INTO docs (id, title, body) VALUES ($1, $2, $3)', (key(), f't-{i}', 'b')


async def sql_pool(name, size):
    dsn = E[SQL_WRITES[name]]
    if name == 'Prisma Postgres':
        pool = await asyncpg.create_pool(dsn, min_size=size, max_size=size)
        return pool, None
    conns, refused_at = [], None
    for slot in range(size):
        try:
            conns.append(await psycopg.AsyncConnection.connect(dsn, autocommit=True, connect_timeout=10))
        except Exception:  # noqa: BLE001
            refused_at = slot
            break
    return conns, refused_at


async def sql_once(name, handle, i):
    sql, args = sql_insert(i)
    if name == 'Prisma Postgres':
        async with handle.acquire() as conn:
            await conn.execute(sql, *args)
    else:
        await handle.execute(sql.replace('$1', '%s').replace('$2', '%s').replace('$3', '%s'), args)
    return True


# ---------------------------------------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------------------------------------


async def latency(name):
    """WARMUP untimed, then SAMPLES timed sequential requests on one kept-alive connection (or one SQL connection)."""
    lat = []
    if name in SQL_WRITES:
        handle, _ = await sql_pool(name, 1)
        one = handle if name == 'Prisma Postgres' else handle[0]
        for i in range(WARMUP + SAMPLES):
            t0 = time.perf_counter()
            await sql_once(name, one, i)
            if i >= WARMUP:
                lat.append(time.perf_counter() - t0)
        await (handle.close() if name == 'Prisma Postgres' else handle[0].close())
        return stats(lat)
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=1)) as session:
        fails = 0
        for i in range(WARMUP + SAMPLES):
            t0 = time.perf_counter()
            ok = (await http_once(session, name, i)) < 400
            if i >= WARMUP:
                if ok:
                    lat.append(time.perf_counter() - t0)
                else:
                    fails += 1
    served_from = SERVED_FROM.pop(name, None)
    return {**stats(lat), 'errors': fails, **({'served_from': served_from} if served_from else {})}


async def load(name, c):
    """Warm `c` connections with `c` untimed requests, then keep `c` in flight for LOAD_SECONDS."""
    lat: list[float] = []
    errors: dict[str, int] = {}
    done_at: list[float] = []
    sql = name in SQL_WRITES
    refused_at = None
    if sql:
        handle, refused_at = await sql_pool(name, c)
        conns = handle if name != 'Prisma Postgres' else None
        width = len(conns) if conns is not None else c
        if conns is not None and not conns:
            return {'error': 'no connections'}
        if conns is not None:
            await asyncio.gather(*(conn.execute('SELECT 1') for conn in conns))
        else:
            await asyncio.gather(*(handle.fetchval('SELECT 1') for _ in range(c)))
    else:
        session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=c, force_close=False), timeout=aiohttp.ClientTimeout(total=60)
        )
        width = c
        await asyncio.gather(*(http_once(session, name, -i) for i in range(c)), return_exceptions=True)

    deadline = None
    counter = iter(range(10**9))

    async def worker(w):
        while time.perf_counter() < deadline:
            i = next(counter)
            t0 = time.perf_counter()
            try:
                if sql:
                    await sql_once(name, conns[w] if conns is not None else handle, i)
                    status = 'ok'
                else:
                    code = await http_once(session, name, i)
                    status = 'ok' if code < 400 else f'http_{code}'
            except Exception as e:  # noqa: BLE001
                status = type(e).__name__
            t1 = time.perf_counter()
            done_at.append(t1)
            if status == 'ok':
                lat.append(t1 - t0)
            else:
                errors[status] = errors.get(status, 0) + 1

    start = time.perf_counter()
    deadline = start + LOAD_SECONDS
    await asyncio.gather(*(worker(w) for w in range(width)))
    # Failed attempts take time too, and workers keep sending until the deadline: successes over less than the
    # window would overstate throughput.
    span = max(max(done_at, default=start) - start, LOAD_SECONDS)
    if sql:
        if conns is not None:
            await asyncio.gather(*(conn.close() for conn in conns), return_exceptions=True)
        else:
            await handle.close()
    else:
        await session.close()
    ok = len(lat)
    total = ok + sum(errors.values())
    out = {
        'concurrency': c,
        'effective_concurrency': width,
        'seconds': round(span, 2),
        'requests': total,
        'successful_requests': ok,
        'error_rate': round(1 - ok / total, 4) if total else 1.0,
        'errors': errors,
        'throughput_rps': round(ok / span, 2) if span else 0,
        'latency': stats(lat),
    }
    if refused_at is not None:
        out['connections_refused_at_slot'] = refused_at
    return out


async def reads():
    """One seeded row, read SAMPLES times by primary key after WARMUP untimed reads."""
    out = {}
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=1)) as s:

        async def http_reads(name, seed, read):
            try:
                k = await seed()
                lat = []
                for i in range(WARMUP + SAMPLES):
                    t0 = time.perf_counter()
                    ok = await read(k)
                    if i >= WARMUP and ok:
                        lat.append(time.perf_counter() - t0)
                out[name] = stats(lat)
            except Exception as e:  # noqa: BLE001
                out[name] = {'error': f'{type(e).__name__}: {e}'[:200]}

        async def pxt_seed():
            async with s.post(PXT + '/ingest/docs', headers=pxt_h(), json={'title': 'seed', 'body': 'b'}) as r:
                return (await r.json())['id']

        async def pxt_read(k):
            async with s.post(PXT + '/ingest/docs/get', headers=pxt_h(), json={'doc_id': k}) as r:
                await r.read()
                return r.status == 200

        async def neon_seed():
            k = key()
            async with s.post(
                E['NEON_HTTP_ENDPOINT'],
                headers=neon_h(),
                json={'query': 'INSERT INTO docs (id, title, body) VALUES ($1, $2, $3)', 'params': [k, 'seed', 'b']},
            ) as r:
                await r.read()
            return k

        async def neon_read(k):
            async with s.post(
                E['NEON_HTTP_ENDPOINT'],
                headers=neon_h(),
                json={'query': 'SELECT id, title, body FROM docs WHERE id = $1', 'params': [k]},
            ) as r:
                return r.status == 200 and len((await r.json()).get('rows', [])) == 1

        async def turso_seed():
            k = key()
            async with s.post(
                E['TURSO_ENDPOINT'],
                headers=turso_h(),
                json=turso_stmt('INSERT INTO docs (id, title, body) VALUES (?, ?, ?)', [k, 'seed', 'b']),
            ) as r:
                await r.read()
            return k

        async def turso_read(k):
            async with s.post(
                E['TURSO_ENDPOINT'],
                headers=turso_h(),
                json=turso_stmt('SELECT id, title, body FROM docs WHERE id = ?', [k]),
            ) as r:
                body = await r.json()
                return r.status == 200 and len(body['results'][0]['response']['result']['rows']) == 1

        async def supa_seed():
            k = key()
            async with s.post(
                SUPA, headers=supa_h({'Prefer': 'return=minimal'}), json={'id': k, 'title': 'seed', 'body': 'b'}
            ) as r:
                await r.read()
            return k

        async def supa_read(k):
            async with s.get(f'{SUPA}?id=eq.{k}&select=*', headers=supa_h()) as r:
                return r.status == 200 and len(await r.json()) == 1

        async def convex_seed():
            async with s.post(
                CONVEX + '/api/mutation',
                json={'path': 'docs:insertDoc', 'args': {'title': 'seed', 'body': 'b'}, 'format': 'json'},
            ) as r:
                return (await r.json())['value']['id']

        async def convex_read(k):
            async with s.post(
                CONVEX + '/api/query', json={'path': 'docs:getDoc', 'args': {'id': k}, 'format': 'json'}
            ) as r:
                body = await r.json()
                return body.get('status') == 'success' and body.get('value') is not None

        async def d1_seed():
            async with s.post(CF + '/docs', headers=UA, json={'title': 'seed', 'body': 'b'}) as r:
                return (await r.json())['id']

        async def d1_read(k):
            async with s.get(f'{CF}/docs/{k}', headers=UA) as r:
                await r.read()
                return r.status == 200

        await http_reads('Pixeltable Query Route', pxt_seed, pxt_read)
        await http_reads('Neon Serverless PG', neon_seed, neon_read)
        await http_reads('Turso libSQL', turso_seed, turso_read)
        await http_reads('Supabase PostgREST', supa_seed, supa_read)
        await http_reads('Convex', convex_seed, convex_read)
        await http_reads('Cloudflare Workers (D1)', d1_seed, d1_read)

    for name in SQL_WRITES:
        try:
            handle, _ = await sql_pool(name, 1)
            one = handle if name == 'Prisma Postgres' else handle[0]
            k = key()
            sql = 'SELECT id, title, body FROM docs WHERE id = $1'
            if name == 'Prisma Postgres':
                await one.execute('INSERT INTO docs (id, title, body) VALUES ($1, $2, $3)', k, 'seed', 'b')
            else:
                await one.execute('INSERT INTO docs (id, title, body) VALUES (%s, %s, %s)', (k, 'seed', 'b'))
            lat = []
            for i in range(WARMUP + SAMPLES):
                t0 = time.perf_counter()
                if name == 'Prisma Postgres':
                    row = await one.fetchrow(sql, k)
                else:
                    cur = await one.execute(sql.replace('$1', '%s'), (k,))
                    row = await cur.fetchone()
                if i >= WARMUP and row is not None:
                    lat.append(time.perf_counter() - t0)
            out[name] = stats(lat)
            await (one.close() if name == 'Prisma Postgres' else one.close())
        except Exception as e:  # noqa: BLE001
            out[name] = {'error': f'{type(e).__name__}: {e}'[:200]}
    return out


async def batches():
    """100 rows in one call, 5 times per target, on a warmed connection."""
    rows = lambda: [(key(), f't-{i}', 'b') for i in range(100)]  # noqa: E731
    out = {}

    def failed() -> NoReturn:
        raise RuntimeError('batch call failed')

    async def repeat(name, one_batch, warm=None):
        # Only confirmed inserts are rated; a failed call is counted, never a zero-row sample.
        rates, errors = [], []
        try:
            if warm:
                await warm()
        except Exception as e:  # noqa: BLE001
            out[name] = {'error': f'{type(e).__name__}: {e}'[:200]}
            return
        for _ in range(5):
            t0 = time.perf_counter()
            try:
                n = await one_batch()
            except Exception as e:  # noqa: BLE001
                errors.append(f'{type(e).__name__}: {e}'[:200])
                continue
            rates.append(n / (time.perf_counter() - t0))
        if not rates:
            out[name] = {'error': errors[0]}
            return
        out[name] = {
            'reps_rows_per_sec': [round(r, 2) for r in rates],
            'rows_per_sec': round(statistics.median(rates), 2),
            **({'failed_calls': len(errors)} if errors else {}),
        }

    async with aiohttp.ClientSession() as s:

        async def neon():
            vals = ', '.join(f"('{a}', '{b}', '{c}')" for a, b, c in rows())
            async with s.post(
                E['NEON_HTTP_ENDPOINT'],
                headers=neon_h(),
                json={'query': f'INSERT INTO docs (id, title, body) VALUES {vals}'},
            ) as r:
                await r.read()
                return 100 if r.status == 200 else failed()

        async def turso():
            reqs = [
                {
                    'type': 'execute',
                    'stmt': {
                        'sql': 'INSERT INTO docs (id, title, body) VALUES (?, ?, ?)',
                        'args': [{'type': 'text', 'value': v} for v in rw],
                    },
                }
                for rw in rows()
            ]
            body = {
                'requests': [
                    {'type': 'execute', 'stmt': {'sql': 'BEGIN'}},
                    *reqs,
                    {'type': 'execute', 'stmt': {'sql': 'COMMIT'}},
                    {'type': 'close'},
                ]
            }
            async with s.post(E['TURSO_ENDPOINT'], headers=turso_h(), json=body) as r:
                await r.read()
                return 100 if r.status == 200 else failed()

        async def supa():
            async with s.post(
                SUPA,
                headers=supa_h({'Prefer': 'return=minimal'}),
                json=[{'id': key(), 'title': f't-{i}', 'body': 'b'} for i in range(100)],
            ) as r:
                await r.read()
                return 100 if r.status in (200, 201) else failed()

        async def convex():
            async with s.post(
                CONVEX + '/api/mutation',
                json={
                    'path': 'docs:insertDocsBatch',
                    'args': {'docs': [{'title': f't-{i}', 'body': 'b'} for i in range(100)]},
                    'format': 'json',
                },
            ) as r:
                body = await r.json()
                return 100 if body.get('status') == 'success' else failed()

        async def d1():
            async with s.post(
                CF + '/docs/batch',
                headers={**UA, 'Content-Type': 'application/json'},
                json={'docs': [{'title': f't-{i}', 'body': 'b'} for i in range(100)]},
            ) as r:
                await r.read()
                return 100 if r.status == 200 else failed()

        async def warm_get(url, h):
            async def go():
                async with s.get(url, headers=h) as r:
                    await r.read()

            return go

        await repeat('Neon Serverless PG', neon, await warm_get(E['NEON_HTTP_ENDPOINT'].replace('/sql', '/'), UA))
        await repeat('Turso libSQL', turso)
        await repeat('Supabase PostgREST', supa)
        await repeat('Convex', convex)
        await repeat('Cloudflare Workers (D1)', d1, await warm_get(CF + '/', UA))

    for name in SQL_WRITES:
        try:
            handle, _ = await sql_pool(name, 1)
        except Exception as e:  # noqa: BLE001
            out[name] = {'error': f'{type(e).__name__}: {e}'[:200]}
            continue
        one = handle if name == 'Prisma Postgres' else handle[0]

        async def go(one=one, name=name):
            data = rows()
            if name == 'Prisma Postgres':
                await one.executemany('INSERT INTO docs (id, title, body) VALUES ($1, $2, $3)', data)
            else:
                async with one.cursor() as cur:
                    await cur.executemany('INSERT INTO docs (id, title, body) VALUES (%s, %s, %s)', data)
            return 100

        await repeat(name, go)
        await one.close()
    return out


def sdk_batches():
    """Pixeltable's Python SDK: t.insert() of 100 rows into the hosted table, 5 times after one warm insert."""
    import pixeltable as pxt

    t = pxt.get_table(E['PXT_DOCS_TABLE'])
    t.insert([{'title': 'warm', 'body': 'b'}])
    rates = []
    for _ in range(5):
        data = [{'title': f'sdk-{key()}', 'body': 'b'} for _ in range(100)]
        t0 = time.perf_counter()
        t.insert(data)
        rates.append(100 / (time.perf_counter() - t0))
    return {'reps_rows_per_sec': [round(r, 2) for r in rates], 'rows_per_sec': round(statistics.median(rates), 2)}


MEDIA_DECODE = {
    'Railway': RAILWAY + '/clip',
    'Render': RENDER + '/clip',
    'Vercel': VERCEL + '/clip',
    'Modal': MODAL + '/clip',
}
MEDIA_PERSIST = {
    'Pixeltable Media Route': PXT + '/media/clip',
    'Railway + Postgres + object storage': RAILWAY + '/clip/persist',
    'Render + Postgres + object storage': RENDER + '/clip/persist',
}


async def media_run(url, n=MEDIA_VIDEOS, c=5, pxt=False):
    sem, lat = asyncio.Semaphore(c), []
    errors: dict[str, int] = {}

    async def one(session, i):
        async with sem:
            form = aiohttp.FormData()
            form.add_field('clip', VIDEO, filename=f'v{i}.mpg', content_type='video/mpeg')
            form.add_field('title', f'video {i}')
            t0 = time.perf_counter()
            try:
                async with session.post(
                    url, data=form, headers={**UA, **({'Authorization': f'Bearer {E["PXT_TOKEN"]}'} if pxt else {})}
                ) as r:
                    body = await r.read()
                    ok = r.status == 200 and b'"error"' not in body
            except Exception as e:  # noqa: BLE001
                errors[type(e).__name__] = errors.get(type(e).__name__, 0) + 1
                return
            if ok:
                lat.append(time.perf_counter() - t0)
            else:
                errors[f'http_{r.status}'] = errors.get(f'http_{r.status}', 0) + 1

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
        await one(session, -1)  # warm-up: one untimed video
        lat.clear()
        errors.clear()
        t0 = time.perf_counter()
        await asyncio.gather(*(one(session, i) for i in range(n)))
        span = time.perf_counter() - t0
    return {
        'videos': n,
        'concurrency': c,
        'seconds': round(span, 2),
        'videos_per_sec': round(len(lat) / span, 2),
        'errors': errors,
        'latency': stats(lat),
    }


async def media_background(n=MEDIA_VIDEOS, c=5):
    """Pixeltable's background media route, each job timed from submit until it reports done."""
    sem, ack, total = asyncio.Semaphore(c), [], []
    errors: dict[str, int] = {}

    async def one(session, i):
        try:
            await submit_and_wait(session, i)
        except Exception as e:  # noqa: BLE001
            errors[type(e).__name__] = errors.get(type(e).__name__, 0) + 1

    async def submit_and_wait(session, i):
        async with sem:
            form = aiohttp.FormData()
            form.add_field('clip', VIDEO, filename=f'a{i}.mpg', content_type='video/mpeg')
            form.add_field('title', f'async {i}')
            t0 = time.perf_counter()
            async with session.post(
                PXT + '/media/clip/async', data=form, headers={**UA, 'Authorization': f'Bearer {E["PXT_TOKEN"]}'}
            ) as r:
                if r.status != 200:
                    errors[f'http_{r.status}'] = errors.get(f'http_{r.status}', 0) + 1
                    return
                job = (await r.json())['id']
                ack.append(time.perf_counter() - t0)
            while time.perf_counter() - t0 < 120:
                async with session.get(
                    f'{PXT}/media/_pxt/jobs/{job}', headers={**UA, 'Authorization': f'Bearer {E["PXT_TOKEN"]}'}
                ) as r:
                    if r.status == 200 and (await r.json()).get('status') == 'done':
                        total.append(time.perf_counter() - t0)
                        return
                await asyncio.sleep(0.25)
            errors['timeout'] = errors.get('timeout', 0) + 1

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
        t0 = time.perf_counter()
        await asyncio.gather(*(one(session, i) for i in range(n)))
        span = time.perf_counter() - t0
    return {
        'videos': n,
        'concurrency': c,
        'seconds': round(span, 2),
        'videos_per_sec': round(len(total) / span, 2),
        'errors': errors,
        'ack': stats(ack),
        'latency': stats(total),
    }


async def resilience():
    out = {}
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit=400), timeout=aiohttp.ClientTimeout(total=60)
    ) as s:

        async def blast(url, n, c, body):
            sem, lat = asyncio.Semaphore(c), []
            statuses: dict[str, int] = {}

            async def one(i):
                async with sem:
                    t0 = time.perf_counter()
                    try:
                        async with s.post(url, headers=pxt_h(), json=body(i)) as r:
                            await r.read()
                            statuses[str(r.status)] = statuses.get(str(r.status), 0) + 1
                            lat.append(time.perf_counter() - t0)
                    except Exception as e:  # noqa: BLE001
                        statuses[type(e).__name__] = statuses.get(type(e).__name__, 0) + 1

            t0 = time.perf_counter()
            await asyncio.gather(*(one(i) for i in range(n)))
            span = time.perf_counter() - t0
            return {
                'requests': n,
                'concurrency': c,
                'seconds': round(span, 2),
                'rps': round(n / span, 1),
                'statuses': statuses,
                'latency': stats(lat),
            }

        out['microburst_c350'] = await blast(PXT + '/ingest/titles', 500, 350, lambda i: {'title': f'burst-{i}'})
        await asyncio.sleep(10)
        out['sync_insert_c250'] = await blast(
            PXT + '/ingest/docs', 250, 250, lambda i: {'title': f'pool-{i}', 'body': 'b'}
        )
        await asyncio.sleep(10)
        out['async_insert_c200'] = await blast(
            PXT + '/ingest/docs/async', 400, 200, lambda i: {'title': f'async-{i}', 'body': 'b'}
        )
        await asyncio.sleep(5)
        from PIL import Image  # a 25,000 x 25,000 PNG that compresses to a few hundred KB

        buf = __import__('io').BytesIO()
        Image.new('L', (25000, 25000)).save(buf, format='PNG')
        form = aiohttp.FormData()
        form.add_field('photo', buf.getvalue(), filename='bomb.png', content_type='image/png')
        form.add_field('label', 'bomb')
        t0 = time.perf_counter()
        async with s.post(
            PXT + '/media/photo', data=form, headers={**UA, 'Authorization': f'Bearer {E["PXT_TOKEN"]}'}
        ) as r:
            body = (await r.text())[:300]
            out['decompression_bomb'] = {
                'status': r.status,
                'seconds': round(time.perf_counter() - t0, 2),
                'response': body,
            }
    return out


# A route that shares a deployment with an earlier cold target finds it awake, so only the first is a cold start.
COLD_TARGETS = {
    n: v
    for n, v in {
        **{n: v for n, v in COMPUTE.items() if n != 'Modal Async (.spawn)'},
        **{n: v for n, v in HTTP_WRITES.items() if 'background' not in n},
    }.items()
    if n not in SHARES_DEPLOYMENT_WITH
}


async def cold():
    """First request after COLD_IDLE_MINUTES of silence, then a fresh connection to the now-warm server."""
    out = {}
    for name in COLD_TARGETS:
        res: dict[str, Any] = {}
        for label in ('first_request', 'fresh_connection_warm'):
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as s:
                t0 = time.perf_counter()
                try:
                    code = await http_once(s, name, 0)
                    res[label + '_ms'] = round((time.perf_counter() - t0) * 1000, 1) if code < 400 else None
                    if code >= 400:
                        res['error'] = f'http_{code}'
                except Exception as e:  # noqa: BLE001
                    res[label + '_ms'] = None
                    res['error'] = type(e).__name__
        if res.get('first_request_ms') and res.get('fresh_connection_warm_ms'):
            res['wake_ms'] = round(res['first_request_ms'] - res['fresh_connection_warm_ms'], 1)
        out[name] = res
        print('cold', name, res, flush=True)
    for name in SQL_WRITES:
        res = {}
        try:
            for label in ('first_request', 'fresh_connection_warm'):
                t0 = time.perf_counter()
                if name == 'Prisma Postgres':
                    conn = await asyncpg.connect(E[SQL_WRITES[name]])
                    await conn.execute(*([sql_insert(0)[0], *sql_insert(0)[1]]))
                    await conn.close()
                else:
                    conn = await psycopg.AsyncConnection.connect(E[SQL_WRITES[name]], autocommit=True)
                    await conn.execute('INSERT INTO docs (id, title, body) VALUES (%s, %s, %s)', (key(), 'cold', 'b'))
                    await conn.close()
                res[label + '_ms'] = round((time.perf_counter() - t0) * 1000, 1)
            res['wake_ms'] = round(res['first_request_ms'] - res['fresh_connection_warm_ms'], 1)
        except Exception as e:  # noqa: BLE001
            res = {'error': f'{type(e).__name__}: {e}'[:200]}
        out[name] = res
        print('cold', name, res, flush=True)
    return out


def client_info():
    from importlib.metadata import version

    info: dict[str, Any] = {'hostname': socket.gethostname(), 'python': sys.version.split()[0]}
    for package in ('aiohttp', 'asyncpg', 'psycopg', 'pixeltable'):
        try:
            info[package] = version(package)
        except Exception:  # noqa: BLE001
            info[package] = None
    try:
        import urllib.request

        for k in ('placement/region', 'placement/availability-zone', 'instance-type'):
            tok = (
                urllib.request.urlopen(
                    urllib.request.Request(
                        'http://169.254.169.254/latest/api/token',
                        method='PUT',
                        headers={'X-aws-ec2-metadata-token-ttl-seconds': '60'},
                    ),
                    timeout=1,
                )
                .read()
                .decode()
            )
            info[k] = (
                urllib.request.urlopen(
                    urllib.request.Request(
                        f'http://169.254.169.254/latest/meta-data/{k}', headers={'X-aws-ec2-metadata-token': tok}
                    ),
                    timeout=1,
                )
                .read()
                .decode()
            )
    except Exception:  # noqa: BLE001
        info['ec2'] = False
    return info


async def guarded(coro):
    """One target's test: an exception becomes that target's recorded error, so one dead target cannot end a run."""
    try:
        return await coro
    except Exception as e:  # noqa: BLE001
        return {'error': f'{type(e).__name__}: {e}'[:200]}


async def run():
    out = {
        'started': datetime.now(UTC).isoformat(timespec='seconds'),
        'client': client_info(),
        'load_seconds': LOAD_SECONDS,
    }
    targets = [*COMPUTE, *HTTP_WRITES, *SQL_WRITES]
    print('== latency', flush=True)
    out['latency'] = {}
    for n in targets:
        out['latency'][n] = await guarded(latency(n))
        print(n, out['latency'][n].get('p50_ms'), flush=True)
    print('== reads', flush=True)
    out['reads'] = await reads()
    print('== batch', flush=True)
    out['batch'] = await batches()
    for c in (50, 100):
        print(f'== load c={c}', flush=True)
        out[f'load_c{c}'] = {}
        for n in targets:
            out[f'load_c{c}'][n] = await guarded(load(n, c))
            print(n, out[f'load_c{c}'][n].get('throughput_rps'), out[f'load_c{c}'][n].get('error_rate'), flush=True)
            await asyncio.sleep(3)
    print('== media', flush=True)
    out['media_decode'] = {n: await media_run(u) for n, u in MEDIA_DECODE.items()}
    out['media_persist'] = {n: await media_run(u, pxt=n.startswith('Pixeltable')) for n, u in MEDIA_PERSIST.items()}
    out['media_persist']['Pixeltable Media Route (background=True)'] = await media_background()
    print('== resilience', flush=True)
    out['resilience'] = {} if E.get('SKIP_RESILIENCE') else await resilience()
    out['finished'] = datetime.now(UTC).isoformat(timespec='seconds')
    return out


async def near():
    """Latency and reads only: what a second-region client measures. No load is sent from there."""
    out = {'started': datetime.now(UTC).isoformat(timespec='seconds'), 'client': client_info()}
    out['latency'] = {n: await guarded(latency(n)) for n in [*COMPUTE, *HTTP_WRITES, *SQL_WRITES]}
    out['reads'] = await reads()
    out['finished'] = datetime.now(UTC).isoformat(timespec='seconds')
    return out


def save(name, data):
    # remote_loop.sh sets RESULTS_DAY so a cycle that crosses midnight keeps its runs and cold passes together.
    day = os.environ.get('RESULTS_DAY') or datetime.now(UTC).strftime('%Y-%m-%d')
    region = data['client'].get('placement/region') or 'local'
    path = HERE / 'results' / day / region / f'{name}-{datetime.now(UTC).strftime("%H%M%S")}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    print('saved', path, flush=True)


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'run'
    if mode == 'run':
        data = asyncio.run(run())
        try:
            data['batch']['Pixeltable Python SDK'] = sdk_batches()
        except Exception as e:  # noqa: BLE001
            data['batch']['Pixeltable Python SDK'] = {'error': f'{type(e).__name__}: {e}'[:200]}
        save('run', data)
    elif mode == 'near':
        save('near', asyncio.run(near()))
    elif mode == 'cold':
        started = datetime.now(UTC).isoformat(timespec='seconds')
        measured = asyncio.run(cold())
        save(
            'cold',
            {
                'started': started,
                'finished': datetime.now(UTC).isoformat(timespec='seconds'),
                'client': client_info(),
                'idle_minutes': COLD_IDLE_MINUTES,
                'cold': measured,
            },
        )
