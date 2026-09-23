"""Do the implementations agree with each other?

    pytest harness/test_differential.py \
      --compare pixeltable=http://127.0.0.1:8000 \
      --compare supabase=http://127.0.0.1:54321 \
      --compare convex=http://127.0.0.1:3211

`test_equivalence.py` checks each implementation against the contract on its own, so
three implementations could return three different answers and all pass. This checks
them against each other, which is where a divergence nobody intended shows up.

Three tiers, because they are not expected to agree on everything:

  identical   same ffmpeg, same Whisper, same spans. A difference is a bug in one.
  tolerance   floating point, chunk boundaries and the machine, bounded and stated.
  divergent   genuinely different algorithms. Asserted to differ, and why.

The tolerance bounds cover two machines, a laptop and a GitHub runner, because ffmpeg and
Whisper builds differ between them by more than either differs from itself. Each constant
records both observations, so widening one is an evidence question rather than a taste.
"""

from __future__ import annotations

import difflib
import json
import os
import re
from pathlib import Path

import httpx
import pytest

from harness.conftest import PATHS, auth_headers

TIMEOUT = 600.0
ROOT = Path(__file__).resolve().parent.parent
QUERIES = json.loads((ROOT / 'fixtures' / 'queries' / 'test_queries.json').read_text())

# Pixeltable reports the video container's duration; the other two report the duration of
# the audio track they extracted. Those are different quantities, and how far apart they
# land depends on the ffmpeg build: 0.02s on one machine, 0.104s on a GitHub runner, for
# the same fixture. The bound covers that spread rather than the tightest one observed,
# because a bound fitted to one machine is not a bound. It still catches what it is for: a
# wrong video, or a truncated ingest, moves this by seconds.
DURATION_TOLERANCE_SEC = 0.25

# Same model weights on both sides, but Pixeltable embeds through its own index while the
# other two call compute-service, so the two paths post-process vectors differently.
# Top-1 is unaffected; the raw score is not identical.
SIMILARITY_TOLERANCE = 0.05

# Pixeltable's audio_splitter cuts spans from the decoded audio; the other two do
# arithmetic on the duration ffprobe reports. The spans differ by a few milliseconds, so
# Whisper sees a slightly different window at each boundary and renders it differently:
# 'Deletion.' against 'deletion.', 'O of N log N' against 'O of n log n'. The words are
# the same; the casing and the boundary fragment are not.
#
# How different depends on the machine as well as the boundary: 1.0 overlap on one, 0.86
# on a GitHub runner, for the same fixture and the same weights. Both were read with an
# earlier set-intersection measure that scores same-order text no higher than the current
# one, so they are lower bounds under it. Under the current measure the laptop reads 0.95
# at worst. The bound covers both machines.
# At 0.8 it still fails on what it is for: the wrong video transcribed, an empty
# transcript, or the same text written to every chunk.
TRANSCRIPT_MIN_OVERLAP = 0.8


@pytest.fixture(scope='session')
def responses(comparands: dict[str, str], request: pytest.FixtureRequest) -> dict[str, dict]:
    """Collect every implementation's answers once, so each test just compares."""
    if len(comparands) < 2:
        pytest.skip('needs two or more --compare IMPL=URL to diff')

    def rows(client: httpx.Client, paths: dict, name: str, **body) -> list[dict]:
        method, path = paths[name]
        response = client.request(method, path, json=body or None)
        response.raise_for_status()
        return response.json()['rows']

    token = str(request.config.getoption('--auth-token'))
    collected: dict[str, dict] = {}
    for impl, base_url in comparands.items():
        paths = PATHS[impl]
        # Each implementation authenticates its own way: only Supabase requires it.
        with httpx.Client(base_url=base_url, headers=auth_headers(impl, token), timeout=TIMEOUT) as client:
            collected[impl] = {
                'videos': rows(client, paths, 'list'),
                'searches': {
                    q['id']: rows(
                        client,
                        paths,
                        'frames' if q['type'] == 'frames' else 'transcripts',
                        query=q['query'],
                        limit=10,
                    )
                    for q in QUERIES
                },
            }
    # A tolerance failure in CI is only diagnosable against the answers that produced it,
    # and the runner is gone by the time anyone looks. The workflow uploads this file.
    if dump := os.environ.get('DIFFERENTIAL_DUMP'):
        Path(dump).parent.mkdir(parents=True, exist_ok=True)
        Path(dump).write_text(json.dumps(collected, indent=2))
    return collected


def by_title(rows: list[dict]) -> dict[str, dict]:
    return {row['video_title']: row for row in rows}


class TestMustBeIdentical:
    def test_same_videos(self, responses):
        """Compare the full list, not the set.

        Keying by title collapses duplicates, so a doubled ingest looks identical to a
        clean one. Sort the raw titles instead and the row counts have to match too.
        """
        titles = {impl: sorted(row['video_title'] for row in data['videos']) for impl, data in responses.items()}
        assert len(set(map(tuple, titles.values()))) == 1, f'different videos ingested: {titles}'

    def test_no_duplicate_videos(self, responses):
        """A title appearing twice means the same file was ingested twice.

        None of the three enforces uniqueness, so a repeated seed silently doubles every
        downstream row and every count derived from it.
        """
        for impl, data in responses.items():
            titles = [row['video_title'] for row in data['videos']]
            dupes = {t for t in titles if titles.count(t) > 1}
            assert not dupes, f'{impl} has the same video ingested more than once: {sorted(dupes)}'

    @pytest.mark.parametrize('query', QUERIES, ids=lambda q: q['id'])
    def test_same_top_hit(self, responses, query):
        """Every implementation must return the same video first.

        This is the claim the repo actually makes and the one a reader cares about.
        Positions below the first are compared separately and not enforced: see
        TestKnownDivergence.
        """
        tops = {
            impl: (data['searches'][query['id']][0]['video_title'] if data['searches'][query['id']] else None)
            for impl, data in responses.items()
        }
        assert len(set(tops.values())) == 1, f'{query["id"]}: implementations disagree on the top hit: {tops}'


def transcript_overlap(a: str, b: str) -> float:
    """Order-aware word similarity, 1.0 for identical text.

    Casefolded and stripped of punctuation first, so 'Deletion.' matches 'deletion'. A set
    intersection would score a transcript below 1.0 against itself whenever a word repeats,
    and would not notice the right words in the wrong order.
    """
    left, right = _words(a), _words(b)
    if not left and not right:
        return 1.0
    return difflib.SequenceMatcher(None, left, right, autojunk=False).ratio()


def _words(text: str) -> list[str]:
    return re.findall(r"[\w']+", text.casefold())


class TestWithinTolerance:
    def test_transcripts_agree(self, responses):
        """Same words, allowing for the boundary effect described above."""
        per_impl: dict[str, dict[tuple[str, int], str]] = {}
        for impl, data in responses.items():
            found: dict[tuple[str, int], str] = {}
            for rows in data['searches'].values():
                for row in rows:
                    if 'transcript' in row:
                        found[(row['video_title'], round(row['start_sec']))] = row['transcript'].strip()
            per_impl[impl] = found

        reference_impl, reference = next(iter(per_impl.items()))
        for impl, found in per_impl.items():
            if impl == reference_impl:
                continue
            for key, text in found.items():
                if key not in reference:
                    continue
                overlap = transcript_overlap(text, reference[key])
                assert overlap >= TRANSCRIPT_MIN_OVERLAP, (
                    f'{key}: {impl} and {reference_impl} transcripts overlap {overlap:.2f}, '
                    f'below {TRANSCRIPT_MIN_OVERLAP}\n  {impl}: {text!r}\n  {reference_impl}: {reference[key]!r}'
                )

    def test_durations_agree(self, responses):
        titles = sorted(by_title(next(iter(responses.values()))['videos']))
        for title in titles:
            values = {
                impl: by_title(data['videos'])[title]['duration_sec']
                for impl, data in responses.items()
                if title in by_title(data['videos'])
            }
            assert len(values) == len(responses), f'{title} not present across all implementations: {values}'
            spread = max(values.values()) - min(values.values())
            assert spread <= DURATION_TOLERANCE_SEC, (
                f'{title}: duration_sec spread {spread:.3f}s exceeds {DURATION_TOLERANCE_SEC}s: {values}'
            )

    @pytest.mark.parametrize('query', QUERIES, ids=lambda q: q['id'])
    def test_top_similarity_agrees(self, responses, query):
        tops = {
            impl: data['searches'][query['id']][0]['similarity']
            for impl, data in responses.items()
            if data['searches'][query['id']]
        }
        assert tops, f'{query["id"]}: no results returned by any implementation'
        assert len(tops) == len(responses), f'{query["id"]}: some implementations returned no hits: {tops}'
        spread = max(tops.values()) - min(tops.values())
        assert spread <= SIMILARITY_TOLERANCE, (
            f'{query["id"]}: top similarity spread {spread:.4f} exceeds {SIMILARITY_TOLERANCE}: {tops}'
        )


class TestKnownDivergence:
    @pytest.mark.parametrize('query', QUERIES, ids=lambda q: q['id'])
    def test_full_ranking_may_differ_below_the_top(self, responses, query):
        """Recorded, not enforced.

        The embedding paths differ slightly, so videos that score close together can
        swap places below the first. Only the top hit is asserted, above.
        """
        rankings = {}
        for impl, data in responses.items():
            seen, order = set(), []
            for row in data['searches'][query['id']]:
                if row['video_title'] not in seen:
                    seen.add(row['video_title'])
                    order.append(row['video_title'])
            rankings[impl] = order
        if len({tuple(order) for order in rankings.values()}) > 1:
            print(f'  {query["id"]} ranks differently below the top: {rankings}')

    def test_scene_counts_may_differ(self, responses):
        """Recorded, not enforced.

        Pixeltable uses PySceneDetect's content detector; compute-service uses ffmpeg's
        `select='gt(scene,T)'`. Two algorithms on the same footage. Requiring them to
        agree would be requiring the wrong thing, so this reports the difference and
        only fails if a detector finds nothing at all.
        """
        titles = sorted(by_title(next(iter(responses.values()))['videos']))
        for title in titles:
            counts = {
                impl: by_title(data['videos'])[title]['scene_count']
                for impl, data in responses.items()
                if title in by_title(data['videos'])
            }
            assert len(counts) == len(responses), f'{title} not present across all implementations: {counts}'
            assert all(c >= 1 for c in counts.values()), f'{title}: a detector found no scenes: {counts}'
            if len(set(counts.values())) > 1:
                print(f'  scene counts differ for {title}: {counts}')
