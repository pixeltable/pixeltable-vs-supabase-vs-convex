"""pytest options for the equivalence suite.

`pytest_addoption` has to live in a conftest. pytest does not read the hook from a test
module, so `--base-url` would be an unrecognized argument.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

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
    parser.addoption('--base-url', default=None, help='Root URL of the running implementation')
    parser.addoption('--impl', default='pixeltable', choices=sorted(PATHS), help='Which implementation is running')
    parser.addoption(
        '--auth-token',
        default='',
        help="Supabase secret key. Its Edge Function declares auth: 'secret', so the "
        'endpoint requires credentials; the other two are unauthenticated.',
    )
    parser.addoption(
        '--compare',
        action='append',
        default=[],
        metavar='IMPL=URL',
        help='Repeatable. Two or more running implementations to diff against each other.',
    )
    parser.addoption(
        '--destructive',
        action='store_true',
        default=False,
        help='Run the tests that write to the corpus. None of the three exposes a delete '
        'route, so a run leaves rows behind and the fixtures have to be re-seeded after.',
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line('markers', 'destructive: writes to the corpus; needs --destructive')


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption('--destructive'):
        return
    skip = pytest.mark.skip(reason='writes to the corpus; pass --destructive and re-seed afterwards')
    for item in items:
        if 'destructive' in item.keywords:
            item.add_marker(skip)


def _is_pixeltable_alive(url: str) -> bool:
    try:
        with urllib.request.urlopen(f'{url.rstrip("/")}/videos', timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _auto_discover_pixeltable_url() -> str | None:
    pxt_bin = shutil.which('pxt') or str(Path(sys.executable).parent / 'pxt')
    try:
        proc = subprocess.run([pxt_bin, 'service', 'list'], capture_output=True, text=True, timeout=5)
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                parts = line.split()
                if parts and parts[0] == 'media/api' and len(parts) >= 2 and parts[1].startswith('http'):
                    url = parts[1].rstrip('/')
                    if _is_pixeltable_alive(url):
                        return url
    except Exception:
        pass
    return None


@pytest.fixture(scope='session')
def base_url(request: pytest.FixtureRequest) -> str:
    url = request.config.getoption('--base-url')
    if url:
        return str(url).rstrip('/')
    impl = str(request.config.getoption('--impl'))
    if impl == 'pixeltable':
        discovered = _auto_discover_pixeltable_url()
        if discovered:
            return discovered.rstrip('/')
    pytest.skip(
        f'No running {impl} service found and --base-url was not specified. '
        'Start the service or pass --base-url to run equivalence tests.'
    )


@pytest.fixture(scope='session')
def paths(request: pytest.FixtureRequest) -> dict[str, tuple[str, str]]:
    return PATHS[str(request.config.getoption('--impl'))]


@pytest.fixture(scope='session')
def headers(request: pytest.FixtureRequest) -> dict[str, str]:
    return auth_headers(str(request.config.getoption('--impl')), str(request.config.getoption('--auth-token')))


def auth_headers(impl: str, token: str) -> dict[str, str]:
    """Supabase's Edge Function authenticates every request; the other two do not.

    `withSupabase({ auth: 'secret' })` rejects an unauthenticated call with 401, which is
    the idiomatic shape for a service endpoint and a capability the other two implementations
    in this benchmark do not have.
    """
    if impl == 'supabase' and token:
        return {'apikey': token}
    return {'Authorization': f'Bearer {token}'} if token else {}


@pytest.fixture(scope='session')
def comparands(request: pytest.FixtureRequest) -> dict[str, str]:
    """The implementations to diff, as {impl: base_url}, from repeated --compare."""
    pairs = {}
    for item in request.config.getoption('--compare'):
        impl, _, url = item.partition('=')
        if impl not in PATHS:
            raise pytest.UsageError(f'--compare: unknown implementation {impl!r}')
        if not url and impl == 'pixeltable':
            discovered = _auto_discover_pixeltable_url()
            if discovered:
                url = discovered
        if not url:
            raise pytest.UsageError(f'--compare: missing URL for {impl!r} (expected --compare {impl}=URL)')
        pairs[impl] = url.rstrip('/')
    return pairs
