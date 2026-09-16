"""Contract and relevance tests, run against one live implementation.

    pytest harness/test_equivalence.py --impl pixeltable --base-url http://localhost:8123

Asserting shape and HTTP 200 alone would pass a search that returns nothing, or the
wrong video. `expected_video` from the fixture file is checked here.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from harness.api_contract import AgentRow, FrameRow, IngestAck, Rows, TranscriptRow, VideoRow

TIMEOUT = 600.0
ROOT = Path(__file__).resolve().parent.parent
QUERIES = json.loads((ROOT / 'fixtures' / 'queries' / 'test_queries.json').read_text())


@pytest.fixture(scope='session')
def client(base_url: str, headers: dict[str, str]) -> httpx.Client:
    with httpx.Client(base_url=base_url, headers=headers, timeout=TIMEOUT) as c:
        yield c


# Which contract model each endpoint's rows must satisfy. `ingest` is absent because it
# does not return rows: see IngestAck and TestIngest.
ROW_MODELS = {
    'list': VideoRow,
    'frames': FrameRow,
    'transcripts': TranscriptRow,
    'agent': AgentRow,
}


def call(client: httpx.Client, paths: dict, name: str, **body) -> dict:
    """Call an endpoint and validate the response against harness/api_contract.py.

    Validating every row here is what makes the word "contract" true; a model nothing
    imports proves only that the file parses.
    """
    method, path = paths[name]
    response = client.request(method, path, json=body or None)
    assert response.status_code == 200, f'{method} {path} -> {response.status_code}: {response.text[:300]}'
    payload = Rows(**response.json())
    model = ROW_MODELS[name]
    for row in payload.rows:
        model(**row)  # raises ValidationError if the shape or a bound is wrong
    return {'rows': payload.rows}


class TestIngest:
    def test_ingest_acknowledges_and_makes_the_video_listed(self, client, paths):
        """POST /videos, then assert the effect rather than the acknowledgement.

        Ingest is asynchronous on Pixeltable and synchronous on the other two, so the
        response shape differs by design. What has to be the same is that the video is
        listed, with a real duration and at least one scene, once ingest reports done.
        """
        from harness.seed import wait_for_job

        titles_before = {row['video_title'] for row in call(client, paths, 'list')['rows']}
        if titles_before:
            pytest.skip('target already seeded; run this against an empty implementation')

        video = sorted((ROOT / 'fixtures' / 'videos').glob('*.mp4'))[0]
        method, path = paths['ingest']
        started = time.monotonic()
        response = client.request(method, path, json={'video': str(video), 'title': video.name})
        assert response.status_code == 200, f'{method} {path} -> {response.status_code}'
        ack = IngestAck(**response.json() if 'rows' not in response.json() else response.json()['rows'][0])
        if ack.job_url:
            wait_for_job(client, ack.job_url, started + TIMEOUT)

        rows = call(client, paths, 'list')['rows']
        listed = {row['video_title'] for row in rows}
        assert video.name in listed, f'{video.name} not listed after ingest reported done'
        row = next(r for r in rows if r['video_title'] == video.name)
        assert row['duration_sec'] > 0
        assert row['scene_count'] >= 1


class TestVideos:
    def test_list_returns_every_fixture_video(self, client, paths):
        rows = call(client, paths, 'list')['rows']
        assert rows, 'no videos ingested; seed the implementation first'
        for row in rows:
            assert row['video_title']
            assert row['duration_sec'] > 0, f'{row["video_title"]} has no duration'
            assert row['scene_count'] >= 1, f'{row["video_title"]} has no detected scenes'

    def test_every_expected_video_is_present(self, client, paths):
        titles = {row['video_title'] for row in call(client, paths, 'list')['rows']}
        for query in QUERIES:
            assert query['expected_video'] in titles, f'{query["expected_video"]} was never ingested'


class TestSearch:
    @pytest.mark.parametrize('query', [q for q in QUERIES if q['type'] == 'frames'], ids=lambda q: q['id'])
    def test_frame_search_ranks_the_right_video_first(self, client, paths, query):
        rows = call(client, paths, 'frames', query=query['query'], limit=5)['rows']
        assert rows, f'{query["id"]} returned nothing'
        for row in rows:
            assert row['frame_url'], 'frame_url is empty, so the result is not servable'
            assert 0 <= row['similarity'] <= 1
            assert isinstance(row['frame_idx'], int)
        assert rows[0]['video_title'] == query['expected_video'], (
            f'{query["id"]}: top hit was {rows[0]["video_title"]}, expected {query["expected_video"]}'
        )

    @pytest.mark.parametrize('query', [q for q in QUERIES if q['type'] == 'transcripts'], ids=lambda q: q['id'])
    def test_transcript_search_ranks_the_right_video_first(self, client, paths, query):
        rows = call(client, paths, 'transcripts', query=query['query'], limit=5)['rows']
        assert rows, f'{query["id"]} returned nothing'
        for row in rows:
            assert row['transcript'].strip(), 'transcript is empty'
            assert 0 <= row['similarity'] <= 1
        assert rows[0]['video_title'] == query['expected_video'], (
            f'{query["id"]}: top hit was {rows[0]["video_title"]}, expected {query["expected_video"]}'
        )

    def test_chunks_are_not_all_the_same_text(self, client, paths):
        """A video longer than one chunk must yield different text per chunk.

        Both alternatives originally transcribed the whole track once per chunk and
        wrote the same string to every row. This catches that.
        """
        rows = call(client, paths, 'transcripts', query='algorithm', limit=20)['rows']
        by_video: dict[str, set[str]] = {}
        for row in rows:
            by_video.setdefault(row['video_title'], set()).add(row['transcript'])
        multi = {title: texts for title, texts in by_video.items() if len(texts) > 1}
        assert multi or len(rows) <= 1, f'every chunk carries identical text: {by_video}'

    def test_limit_is_respected(self, client, paths):
        assert len(call(client, paths, 'frames', query='whiteboard', limit=2)['rows']) <= 2


class TestAgent:
    def test_agent_answers_and_keeps_its_evidence(self, client, paths):
        rows = call(client, paths, 'agent', question='What is the time complexity of quicksort?')['rows']
        assert rows, 'agent returned no row'
        answer = rows[0]
        assert answer['answer'].strip(), 'agent produced an empty answer'
        assert answer['visual'] or answer['spoken'], 'agent returned an answer with no retrieved evidence'
