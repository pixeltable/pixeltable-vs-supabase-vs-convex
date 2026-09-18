"""What does each implementation do with a request it should refuse?

    pytest harness/test_resilience.py \
      --compare pixeltable=http://127.0.0.1:8000 \
      --compare supabase=http://127.0.0.1:54321 \
      --compare convex=http://127.0.0.1:3211

`test_equivalence.py` and `test_differential.py` both send well-formed requests. This
file sends the ones a real client sends by accident: a missing field, a negative limit, a
query that is a number. The contract says nothing about them, which is exactly why they
are where three implementations quietly drift apart.

The invariant asserted here is narrow and worth more than agreement on a status code:
**a malformed request never produces a 5xx.** A 5xx tells a client the server broke and
to retry; a 4xx tells it the request was wrong and not to. Get that backwards and a load
balancer opens a circuit, a retry storm starts, and an on-call engineer is paged for a
typo in a caller.

Which 4xx is left as a recorded difference. Pixeltable answers 422, because
`FastAPIRouter` derives the route signature from the query function and Pydantic rejects
the body before any handler runs. Supabase and Convex answer 400, from validation written
by hand at the HTTP edge: Deno has no request-validation layer, and Convex's argument
validators sit inside the function, where a failure is a server error rather than a
client one.
"""

from __future__ import annotations

import httpx
import pytest

from harness.conftest import PATHS

# Valid bodies whose extreme values still have one right answer.
WELL_FORMED = [
    ('limit omitted defaults to 10', {'query': 'a person'}, 10),
    ('limit=0 asks for nothing', {'query': 'a person', 'limit': 0}, 0),
    ('limit=1 asks for one', {'query': 'a person', 'limit': 1}, 1),
    # 45 frames are indexed, so a limit past the corpus returns the corpus.
    ('limit past the corpus returns the corpus', {'query': 'a person', 'limit': 1000}, 45),
]

# Bodies no implementation should accept.
MALFORMED = [
    ('query missing', {'limit': 3}),
    ('query is null', {'query': None, 'limit': 3}),
    ('query is a number', {'query': 42, 'limit': 3}),
    ('limit is negative', {'query': 'a person', 'limit': -5}),
    ('limit is a string', {'query': 'a person', 'limit': 'five'}),
    ('limit is fractional', {'query': 'a person', 'limit': 2.5}),
    ('body is an array', ['a person']),
]

# Valid but degenerate. Each must succeed, because none of them is a client error.
DEGENERATE = [
    ('empty query', ''),
    ('whitespace query', '   '),
    ('unicode and emoji', 'ünïcödé 🎬 查询'),
    ('10k characters', 'x ' * 5000),
]


def post(client: httpx.Client, impl: str, route: str, body) -> httpx.Response:
    method, path = PATHS[impl][route]
    return client.request(method, path, json=body)


def test_missing_credentials(comparands: dict[str, str]):
    """Only Supabase authenticates at the edge. With no token it answers 401; the other
    two answer the list route as if the request were authenticated. The asymmetry is a
    published finding (see the auth row in docs/TRADEOFFS.md), so it gets a pin."""
    if not comparands:
        pytest.skip('needs at least one --compare IMPL=URL')
    for impl, url in comparands.items():
        method, path = PATHS[impl]['list']
        resp = httpx.request(method, f'{url}{path}', timeout=30)
        expected = 401 if impl == 'supabase' else 200
        assert resp.status_code == expected, f'{impl} answered {resp.status_code} to a request with no credentials'


class TestMalformedRequestsAreClientErrors:
    @pytest.mark.parametrize('route', ['frames', 'transcripts'])
    @pytest.mark.parametrize('name,body', MALFORMED, ids=[n for n, _ in MALFORMED])
    def test_search_rejects_without_a_server_error(self, clients, route, name, body):
        for impl, client in clients.items():
            status = post(client, impl, route, body).status_code
            assert 400 <= status < 500, (
                f'{impl} {route} answered {status} to {name}; a 5xx here tells clients '
                'to retry a request that can never succeed'
            )

    @pytest.mark.parametrize(
        'name,body',
        [('question missing', {}), ('question is null', {'question': None}), ('question is a number', {'question': 7})],
        ids=['question missing', 'question is null', 'question is a number'],
    )
    def test_agent_rejects_without_a_server_error(self, clients, name, body):
        for impl, client in clients.items():
            status = post(client, impl, 'agent', body).status_code
            assert 400 <= status < 500, f'{impl} agent answered {status} to {name}'

    @pytest.mark.parametrize('name,body', MALFORMED, ids=[n for n, _ in MALFORMED])
    def test_which_4xx_is_recorded_not_enforced(self, clients, name, body):
        """Pixeltable 422 from Pydantic, the other two 400 from hand-written checks."""
        codes = {impl: post(client, impl, 'frames', body).status_code for impl, client in clients.items()}
        if len(set(codes.values())) > 1:
            print(f'  {name}: {codes}')


class TestLimitMeansTheSameThing:
    @pytest.mark.parametrize('name,body,expected', WELL_FORMED, ids=[n for n, _, _ in WELL_FORMED])
    def test_frames(self, clients, name, body, expected):
        counts = {}
        for impl, client in clients.items():
            response = post(client, impl, 'frames', body)
            response.raise_for_status()
            counts[impl] = len(response.json()['rows'])
        assert set(counts.values()) == {expected}, f'{name}: expected {expected} rows everywhere, got {counts}'


class TestDegenerateQueriesStillSucceed:
    @pytest.mark.parametrize('name,query', DEGENERATE, ids=[n for n, _ in DEGENERATE])
    def test_frames(self, clients, name, query):
        counts = {}
        for impl, client in clients.items():
            response = post(client, impl, 'frames', {'query': query, 'limit': 3})
            assert response.status_code == 200, (
                f'{impl} answered {response.status_code} to {name}, which is a valid query'
            )
            counts[impl] = len(response.json()['rows'])
        assert set(counts.values()) == {3}, f'{name}: expected 3 rows everywhere, got {counts}'
