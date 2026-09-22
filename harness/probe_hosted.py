#!/usr/bin/env python3
"""Classify the hosted model's raw responses, outside any of the three implementations.

    OPENROUTER_API_KEY=sk-or-... python harness/probe_hosted.py --model nvidia/nemotron-3-super-120b-a12b

bench_hosted.py records only whether an answer came back. This fires the agent's prompt
straight at OpenRouter and keeps what that hides: the HTTP status, an `error` field inside
a 200 body, `finish_reason`, and the reasoning tokens spent against `max_tokens`. An empty
answer with an `error` field is a provider fault; an empty answer with
`finish_reason=length` is the token cap. Results in `docs/hosted_probe.json`, keyed by model.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.bench_hosted import HOSTED_MODEL, OPENROUTER_BASE  # noqa: E402
from harness.benchmark import AGENT_QUESTIONS  # noqa: E402

OUT = ROOT / 'docs' / 'hosted_probe.json'
MAX_TOKENS = 1024

# Four frames and four transcript segments: the shape pixeltable/app.py retrieves
# (limit=4 each). The text is fixed so every call sends the same prompt length.
TITLES = ['lecture_data_structures', 'whiteboard_algorithms', 'code_review_session', 'lecture_data_structures']
TRANSCRIPT = (
    'Measuring is better than guessing. Quicksort runs in n log n on average but degrades '
    'to quadratic on sorted input, and the common mistake is ignoring constant factors when comparing.'
)


def build_prompt(question: str) -> str:
    # Same text as build_prompt() in pixeltable/app.py; importing app.py would load its schema.
    seen = '\n'.join(f'- {title}, frame {12 * i}' for i, title in enumerate(TITLES))
    heard = '\n'.join(f'- [{title} @ {30 * i}s] {TRANSCRIPT}' for i, title in enumerate(TITLES))
    return (
        'Answer the question using only the retrieved context. Be brief.\n\n'
        f'## Seen in the videos\n{seen}\n\n## Said in the videos\n{heard}\n\n## Question\n{question}'
    )


def call(client: httpx.Client, model: str, i: int) -> dict:
    question = AGENT_QUESTIONS[i % len(AGENT_QUESTIONS)]
    body = {
        'model': model,
        'messages': [{'role': 'user', 'content': build_prompt(question)}],
        'max_tokens': MAX_TOKENS,
        'temperature': 0.2,
    }
    try:
        resp = client.post(f'{OPENROUTER_BASE}/chat/completions', json=body)
    except httpx.HTTPError as e:
        return {'status': None, 'error': f'{type(e).__name__}: {e}'[:200]}
    try:
        data = resp.json()
    except ValueError:
        return {'status': resp.status_code, 'error': resp.text[:200]}
    choice = (data.get('choices') or [{}])[0]
    usage = data.get('usage') or {}
    error = data.get('error') or choice.get('error')
    return {
        'status': resp.status_code,
        'error': str(error)[:200] if error else None,
        'finish_reason': choice.get('finish_reason'),
        'content_chars': len((choice.get('message') or {}).get('content') or ''),
        'completion_tokens': usage.get('completion_tokens'),
        'reasoning_tokens': (usage.get('completion_tokens_details') or {}).get('reasoning_tokens'),
        'provider': data.get('provider'),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default=HOSTED_MODEL)
    parser.add_argument('--calls', type=int, default=36)
    parser.add_argument('--workers', type=int, default=6)
    args = parser.parse_args()
    if args.calls < 1 or args.workers < 1:
        parser.error('--calls and --workers must be at least 1')
    key = os.environ.get('OPENROUTER_API_KEY')
    if not key:
        sys.exit('OPENROUTER_API_KEY is not set.')

    headers = {'Authorization': f'Bearer {key}'}
    with httpx.Client(headers=headers, timeout=120) as client, ThreadPoolExecutor(args.workers) as pool:
        rows = list(pool.map(lambda i: call(client, args.model, i), range(args.calls)))

    shapes = collections.Counter(
        f'{r["status"]} finish={r.get("finish_reason")} error={bool(r["error"])} '
        f'content={"yes" if r.get("content_chars") else "empty"}'
        for r in rows
    )
    completion = [r['completion_tokens'] for r in rows if r.get('completion_tokens') is not None]
    reasoning = [r['reasoning_tokens'] for r in rows if r.get('reasoning_tokens') is not None]
    result = {
        'measured_at': datetime.now(UTC).isoformat(timespec='seconds'),
        'calls': args.calls,
        'workers': args.workers,
        'max_tokens': MAX_TOKENS,
        'shapes': dict(shapes.most_common()),
        'empty': sum(1 for r in rows if not r.get('content_chars')),
        'max_completion_tokens': max(completion) if completion else 'n/a',
        'max_reasoning_tokens': max(reasoning) if reasoning else 'n/a',
        'providers': dict(collections.Counter(r['provider'] for r in rows if r.get('provider'))),
        'errors': sorted({r['error'] for r in rows if r['error']}),
    }
    for shape, n in shapes.most_common():
        print(f'  {n:3d}  {shape}')
    print(f'  max completion tokens {result["max_completion_tokens"]}, max reasoning {result["max_reasoning_tokens"]}')

    existing = json.loads(OUT.read_text()) if OUT.exists() else {}
    existing[args.model] = result
    OUT.write_text(json.dumps(existing, indent=2) + '\n')
    print(f'wrote {OUT.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
