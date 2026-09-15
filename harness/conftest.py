"""pytest options for the equivalence suite.

`pytest_addoption` has to live in a conftest, not in the test module. It was in the
test module, which is why `--base-url` was an unrecognized argument and this suite
had never actually run.
"""

from __future__ import annotations

import pytest

# Each platform serves the same five operations at its own paths.
PATHS = {
    'pixeltable': {
        'ingest': ('POST', '/videos'),
        'list': ('GET', '/videos'),
        'frames': ('POST', '/search/frames'),
        'transcripts': ('POST', '/search/transcripts'),
        'agent': ('POST', '/agent/query'),
    },
    'supabase': {
        'ingest': ('POST', '/functions/v1/api/videos'),
        'list': ('GET', '/functions/v1/api/videos'),
        'frames': ('POST', '/functions/v1/api/search/frames'),
        'transcripts': ('POST', '/functions/v1/api/search/transcripts'),
        'agent': ('POST', '/functions/v1/api/agent/query'),
    },
    'convex': {
        'ingest': ('POST', '/videos'),
        'list': ('GET', '/videos'),
        'frames': ('POST', '/search/frames'),
        'transcripts': ('POST', '/search/transcripts'),
        'agent': ('POST', '/agent/query'),
    },
}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption('--base-url', default='http://localhost:8000', help='Root URL of the running implementation')
    parser.addoption('--impl', default='pixeltable', choices=sorted(PATHS), help='Which implementation is running')
    parser.addoption('--auth-token', default='', help='Bearer token, for Supabase Edge Functions')
    parser.addoption(
        '--compare',
        action='append',
        default=[],
        metavar='IMPL=URL',
        help='Repeatable. Two or more running implementations to diff against each other.',
    )


@pytest.fixture(scope='session')
def base_url(request: pytest.FixtureRequest) -> str:
    return str(request.config.getoption('--base-url')).rstrip('/')


@pytest.fixture(scope='session')
def paths(request: pytest.FixtureRequest) -> dict[str, tuple[str, str]]:
    return PATHS[str(request.config.getoption('--impl'))]


@pytest.fixture(scope='session')
def headers(request: pytest.FixtureRequest) -> dict[str, str]:
    token = str(request.config.getoption('--auth-token'))
    return {'Authorization': f'Bearer {token}'} if token else {}


@pytest.fixture(scope='session')
def comparands(request: pytest.FixtureRequest) -> dict[str, str]:
    """The implementations to diff, as {impl: base_url}, from repeated --compare."""
    pairs = {}
    for item in request.config.getoption('--compare'):
        impl, _, url = item.partition('=')
        if impl not in PATHS:
            raise pytest.UsageError(f'--compare: unknown implementation {impl!r}')
        pairs[impl] = url.rstrip('/')
    return pairs
