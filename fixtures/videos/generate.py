#!/usr/bin/env python3
"""Generate synthetic test videos for the benchmark.

Every video is colour cards with text drawn on them (so CLIP has something to match),
synthesised speech (so Whisper has something to transcribe), and colour changes (so the
scene detectors have something to find).

Three tiers:
  small   3 videos, ~15s each. The correctness fixtures. Every equivalence, differential
          and resilience test runs against these.
  large   20 videos, ~30s each. The scale fixtures, in large/. Nothing asserts against
          them; they exist so ingest throughput and search latency are measured rather
          than extrapolated from 45 rows.
  xl      100 videos, ~30s each, in xl/. The same 20 areas crossed with 5 aspects, so a
          run answers whether the large-tier ordering is a property of the platforms or
          of a small corpus. Near-duplicate topics within an area are deliberate: they
          are the hard case for vector search.

Requires: ffmpeg on PATH, pip install gTTS

Run from the repo root:
    python fixtures/videos/generate.py                # small
    python fixtures/videos/generate.py --tier large   # large
    python fixtures/videos/generate.py --tier xl      # xl
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

VIDEOS_DIR = Path(__file__).resolve().parent
LARGE_DIR = VIDEOS_DIR / 'large'
XL_DIR = VIDEOS_DIR / 'xl'


def _has_ffmpeg() -> bool:
    return shutil.which('ffmpeg') is not None


def _generate_tts(text: str, outpath: Path) -> None:
    """Generate a short MP3 speech clip via gTTS.

    Hard-fails when gTTS is missing rather than falling back to silence. Silent fixtures
    give Whisper nothing to transcribe, and the transcript-search suite then fails for a
    reason its message cannot explain.
    """
    try:
        from gtts import gTTS  # type: ignore[import-untyped]
    except ImportError:
        sys.exit('gTTS not installed. Run: pip install gTTS')
    gTTS(text=text, lang='en', slow=False).save(str(outpath))


def _generate_video(
    filename: str,
    segments: list[dict],
    speech_text: str,
    outdir: Path = VIDEOS_DIR,
) -> None:
    """Build a video from colour segments + text overlay + TTS audio."""
    outdir.mkdir(parents=True, exist_ok=True)
    outpath = outdir / filename
    if outpath.exists():
        print(f'  {filename} already exists, skipping')
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Generate TTS audio
        audio_path = tmp / 'speech.mp3'
        _generate_tts(speech_text, audio_path)

        # Get audio duration
        probe = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(audio_path)],
            capture_output=True,
            text=True,
        )
        audio_dur = float(probe.stdout.strip()) if probe.stdout.strip() else 5.0

        # One colour card per segment, each with its title drawn in the middle.
        seg_dur = audio_dur / len(segments)
        inputs = [
            f'color=c={seg["color"]}:s=640x360:d={seg_dur:.2f},'
            f"drawtext=text='{seg['text'].replace(chr(39), chr(92) + chr(39)).replace(':', chr(92) + ':')}':"
            f'fontsize=28:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2'
            for seg in segments
        ]

        # Concatenate segments
        filter_parts = []
        for i, inp in enumerate(inputs):
            filter_parts.append(f'{inp}[v{i}];')
        concat_inputs = ''.join(f'[v{i}]' for i in range(len(inputs)))
        filter_parts.append(f'{concat_inputs}concat=n={len(inputs)}:v=1:a=0[outv]')
        filter_complex = ''.join(filter_parts)

        cmd = [
            'ffmpeg',
            '-y',
            '-i',
            str(audio_path),
            '-filter_complex',
            filter_complex,
            '-map',
            '[outv]',
            '-map',
            '0:a',
            '-c:v',
            'libx264',
            '-preset',
            'ultrafast',
            '-crf',
            '28',
            '-c:a',
            'aac',
            '-b:a',
            '64k',
            '-shortest',
            '-movflags',
            '+faststart',
            str(outpath),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f'  ERROR generating {filename}:\n{result.stderr[-500:]}')
            return

    print(f'  Created {filename} ({outpath.stat().st_size / 1024:.0f} KB)')


# Twenty topics for the scale tier. Each one is four colour cards and eight spoken
# sentences, which gTTS renders as roughly 30 seconds: enough for three transcript chunks
# and about 30 frames at 1 fps, so 20 videos is ~600 frames and ~60 chunks.
LARGE_TOPICS = [
    ('binary_search_trees', 'Binary Search Trees', '#1a237e', 'balanced tree rotation and height'),
    ('graph_traversal', 'Graph Traversal', '#0d47a1', 'breadth first and depth first search'),
    ('dynamic_programming', 'Dynamic Programming', '#01579b', 'memoisation and overlapping subproblems'),
    ('hash_collisions', 'Hash Collisions', '#006064', 'open addressing and separate chaining'),
    ('heap_priority_queues', 'Heaps and Priority Queues', '#004d40', 'sift up sift down and heapify'),
    ('string_matching', 'String Matching', '#1b5e20', 'prefix functions and rolling hashes'),
    ('sorting_stability', 'Sorting Stability', '#33691e', 'merge sort and stable ordering'),
    ('amortised_analysis', 'Amortised Analysis', '#827717', 'dynamic arrays and the potential method'),
    ('cache_locality', 'Cache Locality', '#f57f17', 'row major traversal and prefetching'),
    ('concurrency_locks', 'Concurrency and Locks', '#ff6f00', 'mutexes deadlock and lock ordering'),
    ('database_indexes', 'Database Indexes', '#e65100', 'b trees and index selectivity'),
    ('query_planning', 'Query Planning', '#bf360c', 'join order and cardinality estimates'),
    ('transaction_isolation', 'Transaction Isolation', '#3e2723', 'snapshot isolation and write skew'),
    ('vector_search', 'Vector Search', '#b71c1c', 'approximate nearest neighbours and recall'),
    ('embedding_models', 'Embedding Models', '#880e4f', 'contrastive training and cosine distance'),
    ('http_caching', 'HTTP Caching', '#4a148c', 'etags and cache control headers'),
    ('load_balancing', 'Load Balancing', '#311b92', 'consistent hashing and health checks'),
    ('observability', 'Observability', '#1a237e', 'traces metrics and structured logs'),
    ('code_review_practice', 'Code Review Practice', '#263238', 'small diffs and review latency'),
    ('incident_response', 'Incident Response', '#37474f', 'blameless postmortems and error budgets'),
]


def _large_speech(title: str, subject: str) -> str:
    """Eight sentences naming the topic, so transcript search has something to rank."""
    return (
        f'This session covers {title.lower()}. '
        f'The subject today is {subject}. '
        f'We begin with the definition and the cost model. '
        f'Then we walk through a worked example on the board. '
        f'The common mistake is to ignore the constant factors. '
        f'Measuring is always better than guessing about {subject}. '
        f'We close with the cases where this approach does not apply. '
        f'Next session continues from {title.lower()}.'
    )


# Five angles on each area, so 20 areas make 100 videos whose speech stays distinct
# without hand-writing 80 more topic rows.
XL_ASPECTS = [
    ('fundamentals', 'the definition and the cost model'),
    ('in_practice', 'what it looks like in production code'),
    ('failure_modes', 'the ways it goes wrong under load'),
    ('measurement', 'how to measure it instead of guessing'),
    ('alternatives', 'when to reach for something else entirely'),
]


def _generate_xl() -> None:
    total = len(LARGE_TOPICS) * len(XL_ASPECTS)
    print(f'Generating {total} xl-tier videos in {XL_DIR.relative_to(VIDEOS_DIR.parent.parent)}...')
    for slug, title, colour, subject in LARGE_TOPICS:
        for aspect_slug, aspect in XL_ASPECTS:
            _generate_video(
                f'{slug}__{aspect_slug}.mp4',
                segments=[
                    {'color': colour, 'text': title},
                    {'color': '#212121', 'text': aspect_slug.replace('_', ' ').title()},
                    {'color': colour, 'text': 'Worked Example'},
                    {'color': '#212121', 'text': 'Summary'},
                ],
                speech_text=_large_speech(f'{title}, {aspect_slug.replace("_", " ")}', f'{subject}, {aspect}'),
                outdir=XL_DIR,
            )


def _generate_large() -> None:
    print(f'Generating {len(LARGE_TOPICS)} scale-tier videos in {LARGE_DIR.relative_to(VIDEOS_DIR.parent.parent)}...')
    for slug, title, colour, subject in LARGE_TOPICS:
        _generate_video(
            f'{slug}.mp4',
            segments=[
                {'color': colour, 'text': title},
                {'color': '#212121', 'text': 'Definition'},
                {'color': colour, 'text': 'Worked Example'},
                {'color': '#212121', 'text': 'Summary'},
            ],
            speech_text=_large_speech(title, subject),
            outdir=LARGE_DIR,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tier', choices=['small', 'large', 'xl'], default='small')
    args = parser.parse_args()

    if not _has_ffmpeg():
        print('ffmpeg not found on PATH. Install ffmpeg first.')
        sys.exit(1)

    if args.tier in ('large', 'xl'):
        (_generate_large if args.tier == 'large' else _generate_xl)()
        print('Done.')
        return

    print('Generating test videos...')

    _generate_video(
        'lecture_data_structures.mp4',
        segments=[
            {'color': '#1a237e', 'text': 'Data Structures'},
            {'color': '#0d47a1', 'text': 'Arrays and Linked Lists'},
            {'color': '#01579b', 'text': 'Hash Tables and Trees'},
        ],
        speech_text=(
            'Today we will discuss fundamental data structures. '
            'Arrays provide constant time access by index. '
            'Linked lists allow efficient insertion and deletion. '
            'Hash tables offer average constant time lookups.'
        ),
    )

    _generate_video(
        'whiteboard_algorithms.mp4',
        segments=[
            {'color': '#1b5e20', 'text': 'Sorting Algorithms'},
            {'color': '#33691e', 'text': 'Whiteboard: Quicksort'},
            {'color': '#827717', 'text': 'Performance Analysis'},
        ],
        speech_text=(
            'Let me explain quicksort on the whiteboard. '
            'We pick a pivot element and partition the array. '
            'The average time complexity is O of n log n. '
            'This makes quicksort efficient for large datasets.'
        ),
    )

    _generate_video(
        'code_review_session.mp4',
        segments=[
            {'color': '#b71c1c', 'text': 'Code Review'},
            {'color': '#880e4f', 'text': 'Python Best Practices'},
            {'color': '#4a148c', 'text': 'Performance Optimization'},
        ],
        speech_text=(
            'In this code review we discuss performance optimization. '
            'Using list comprehensions is faster than for loops. '
            'Caching results with decorators reduces redundant computation. '
            'Always profile before you optimize.'
        ),
    )

    print('Done.')


if __name__ == '__main__':
    main()
