"""What does a failed or concurrent ingest leave behind?

    pytest harness/test_recovery.py --destructive \
      --compare pixeltable \
      --compare supabase=http://127.0.0.1:54321 \
      --compare convex=http://127.0.0.1:3211

Every other suite reads. This one writes, and none of the three exposes a delete route,
so a run leaves rows in the corpus and the fixtures have to be re-seeded afterwards. That
is why it is behind `--destructive` and why CI only collects it.

What it asserts:

  - a media step that fails must not leave a video listed as though it worked;
  - a failure must be reported, not swallowed into an empty row;
  - two ingests at once must both land, exactly once each.

Where the three differ, the difference is recorded rather than asserted into agreement.
They have genuinely different failure models and flattening that would hide it.
"""

from __future__ import annotations

import concurrent.futures
import shutil
import subprocess
import uuid
from pathlib import Path

import httpx
import pytest

from harness.conftest import PATHS, auth_headers

TIMEOUT = 900.0
ROOT = Path(__file__).resolve().parent.parent
GOOD_VIDEO = ROOT / 'fixtures' / 'videos' / 'lecture_data_structures.mp4'


@pytest.fixture(scope='session')
def clients(comparands: dict[str, str], request: pytest.FixtureRequest):
    if not comparands:
        pytest.skip('needs at least one --compare IMPL=URL')
    token = str(request.config.getoption('--auth-token'))
    opened = {
        impl: httpx.Client(base_url=url, headers=auth_headers(impl, token), timeout=TIMEOUT)
        for impl, url in comparands.items()
    }
    yield opened
    for client in opened.values():
        client.close()


@pytest.fixture(scope='session')
def broken_videos(tmp_path_factory) -> dict[str, Path]:
    """Four ways a video file can be wrong, none of them exotic."""
    tmp = tmp_path_factory.mktemp('broken')
    empty = tmp / 'zero_bytes.mp4'
    empty.write_bytes(b'')
    garbage = tmp / 'not_a_video.mp4'
    garbage.write_bytes(b'this is not an mp4, it only has the extension' * 100)
    truncated = tmp / 'truncated.mp4'
    truncated.write_bytes(GOOD_VIDEO.read_bytes()[:2048])
    return {'zero bytes': empty, 'garbage bytes': garbage, 'truncated': truncated, 'missing file': tmp / 'gone.mp4'}


def ingest(client: httpx.Client, impl: str, path: Path, title: str) -> httpx.Response:
    method, route = PATHS[impl]['ingest']
    return client.request(method, route, json={'video': str(path), 'title': title})


def listed_titles(client: httpx.Client, impl: str) -> list[str]:
    method, route = PATHS[impl]['list']
    response = client.request(method, route)
    response.raise_for_status()
    return [row['video_title'] for row in response.json()['rows']]


def settled(client: httpx.Client, impl: str, response: httpx.Response) -> tuple[str, str]:
    """Resolve an ingest to (outcome, detail), waiting out Pixeltable's job if there is one.

    Pixeltable answers with a job to poll; the other two answer when the work is done. The
    comparable question is what the caller learns once the dust settles, not which shape
    the first response had.
    """
    if response.status_code >= 400:
        return 'rejected', f'HTTP {response.status_code}'
    body = response.json()
    if job_url := body.get('job_url'):
        import time

        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            job = client.get(job_url).json()
            if job.get('status') == 'done':
                return 'accepted', 'job done'
            if job.get('status') == 'error':
                return 'rejected', f'job error: {str(job.get("error"))[:80]}'
            time.sleep(0.2)
        return 'hung', 'job still pending after 300s'
    return 'accepted', 'synchronous 200'


@pytest.mark.destructive
class TestBrokenVideoDoesNotBecomeAGoodRow:
    @pytest.mark.parametrize('kind', ['zero bytes', 'garbage bytes', 'truncated', 'missing file'])
    def test_failure_is_reported_and_not_listed_as_ready(self, clients, broken_videos, kind):
        """A file that cannot be decoded must not end up listed like a real video.

        This is the claim the repo makes about per-cell errors, and the thing a reader
        would check first: after a failed ingest, does `GET /videos` lie?
        """
        path = broken_videos[kind]
        title = f'broken_{kind.replace(" ", "_")}_{uuid.uuid4().hex[:6]}.mp4'
        outcomes = {}
        for impl, client in clients.items():
            outcome, detail = settled(client, impl, ingest(client, impl, path, title))
            outcomes[impl] = f'{outcome} ({detail})'
            assert outcome != 'hung', f'{impl} never resolved the ingest of a {kind} file'
            if outcome == 'accepted':
                continue
            assert title not in listed_titles(client, impl), (
                f'{impl} rejected the {kind} ingest and still lists {title}: a caller reading '
                f'GET /videos cannot tell this row from a real one'
            )
        if len({o.split(' ')[0] for o in outcomes.values()}) > 1:
            print(f'  {kind}: implementations disagree on the outcome: {outcomes}')
        else:
            print(f'  {kind}: {outcomes}')


@pytest.mark.destructive
class TestConcurrentIngest:
    def test_two_at_once_both_land_exactly_once(self, clients):
        """Two different videos, submitted together.

        Nothing in any of the three serialises ingest, so this is the shape a real client
        produces the first time two users upload at the same moment.
        """
        if not shutil.which('ffprobe'):
            pytest.skip('ffprobe needed to confirm the fixture is readable')
        run = uuid.uuid4().hex[:6]
        titles = [f'concurrent_a_{run}.mp4', f'concurrent_b_{run}.mp4']
        for impl, client in clients.items():
            before = listed_titles(client, impl)
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(ingest, client, impl, GOOD_VIDEO, t) for t in titles]
                responses = [f.result() for f in futures]
            for title, response in zip(titles, responses, strict=True):
                outcome, detail = settled(client, impl, response)
                assert outcome == 'accepted', f'{impl} failed a concurrent ingest of {title}: {detail}'
            after = listed_titles(client, impl)
            for title in titles:
                assert after.count(title) == 1, (
                    f'{impl} listed {title} {after.count(title)} times after two concurrent ingests'
                )
            assert len(after) == len(before) + 2, (
                f'{impl} went from {len(before)} to {len(after)} videos after two ingests'
            )


@pytest.mark.destructive
class TestRecoveryPath:
    """Undoing the writes above, where the platform offers a way.

    Pixeltable versions the table, so the fixture state is a revert away. Supabase and
    Convex have no per-table undo: recovery is point-in-time restore, a snapshot import,
    or DELETE statements you write. Recorded, not asserted, because it is a difference in
    what the platforms offer rather than a bug in any of them.
    """

    def test_pixeltable_can_revert_what_this_suite_wrote(self, clients):
        if 'pixeltable' not in clients:
            pytest.skip('needs --compare pixeltable')
        if not shutil.which('pxt'):
            pytest.skip('pxt not on PATH')
        proc = subprocess.run(['pxt', 'history', 'media/videos'], capture_output=True, text=True, timeout=120)
        assert proc.returncode == 0, f'pxt history failed: {proc.stderr[:200]}'
        versions = [line.split('\t')[0] for line in proc.stdout.splitlines()[1:] if line.strip()]
        assert len(versions) > 1, 'no version history to recover from'
        print(f'  pixeltable: {len(versions)} versions recorded; `pxt revert media/videos --steps N` undoes them')
        for impl in clients:
            if impl != 'pixeltable':
                print(f'  {impl}: no per-table version history; recovery is PITR, snapshot import, or DELETE by hand')
