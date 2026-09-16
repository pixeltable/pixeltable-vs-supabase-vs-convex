#!/usr/bin/env python3
"""Generate short synthetic test videos for the benchmark.

Creates 3 videos (~14-16 seconds each) with:
  - Colour background + text overlay (so CLIP can match visual queries)
  - Synthesised speech audio via gTTS (so Whisper can transcribe)
  - Scene changes (colour shifts) for scene-detection tests

Requires: ffmpeg on PATH, pip install gTTS

Run once from the repo root:
    python fixtures/videos/generate.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

VIDEOS_DIR = Path(__file__).resolve().parent


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
) -> None:
    """Build a video from colour segments + text overlay + TTS audio."""
    outpath = VIDEOS_DIR / filename
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


def main() -> None:
    if not _has_ffmpeg():
        print('ffmpeg not found on PATH. Install ffmpeg first.')
        sys.exit(1)

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
