#!/usr/bin/env python3
"""Time the agent's generation step on each device, with nothing else in the path.

    python harness/bench_device.py --impl convex --base-url http://127.0.0.1:3211

The agent gap in docs/SCALE.md mixes two things: Pixeltable's `llama_cpp` UDF offloads
the model to the GPU when one is available, `llama-cpp-python` behind compute-service
stays on CPU unless asked, and the other two also make three round trips per query. This
separates the first from the second. It loads the same GGUF with the same arguments as
compute-service twice, once per device, and times the same prompts the agent sends: the
real retrieval context for each benchmark question, fetched from a running
implementation, in the order `benchmark.py` asks them. No HTTP, no retrieval, no
database inside the timed call.

Writes docs/device.json. The device names are what this machine offers: on Apple silicon
`n_gpu_layers=-1` is Metal.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harness.benchmark import AGENT_QUESTIONS, percentile  # noqa: E402
from harness.conftest import PATHS, auth_headers  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'docs' / 'device.json'

# The arguments compute-service/app.py and pixeltable/app.py both pass.
REPO_ID = 'Qwen/Qwen2.5-1.5B-Instruct-GGUF'
FILENAME = '*q4_k_m.gguf'
N_CTX = 4096
MAX_TOKENS = 256
TEMPERATURE = 0.2
DEVICES = {'cpu': 0, 'gpu': -1}


def build_prompt(question: str, visual: list[dict], spoken: list[dict]) -> str:
    """The agent prompt, as pixeltable/app.py and both TypeScript agents build it."""
    seen = '\n'.join(f'- {r["video_title"]}, frame {r["frame_idx"]}' for r in visual) or '(nothing)'
    heard = (
        '\n'.join(f'- [{r["video_title"]} @ {r["start_sec"]:.0f}s] {r["transcript"]}' for r in spoken) or '(nothing)'
    )
    return (
        'Answer the question using only the retrieved context. Be brief.\n\n'
        f'## Seen in the videos\n{seen}\n\n## Said in the videos\n{heard}\n\n## Question\n{question}'
    )


def prompts(client: httpx.Client, impl: str) -> dict[str, str]:
    out = {}
    for question in AGENT_QUESTIONS:
        hits = {}
        for kind in ('frames', 'transcripts'):
            method, path = PATHS[impl][kind]
            response = client.request(method, path, json={'query': question, 'limit': 4})
            response.raise_for_status()
            hits[kind] = response.json()['rows']
        out[question] = build_prompt(question, hits['frames'], hits['transcripts'])
    return out


def time_device(n_gpu_layers: int, by_question: dict[str, str], iterations: int) -> dict:
    from llama_cpp import Llama

    model = Llama.from_pretrained(
        repo_id=REPO_ID, filename=FILENAME, n_ctx=N_CTX, verbose=False, n_gpu_layers=n_gpu_layers
    )

    def ask(question: str) -> None:
        model.create_chat_completion(
            messages=[{'role': 'user', 'content': by_question[question]}],
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
        )

    ask(AGENT_QUESTIONS[0])  # untimed warm-up, as benchmark.py does
    samples = []
    for _ in range(iterations):
        for question in AGENT_QUESTIONS:
            started = time.monotonic()
            ask(question)
            samples.append((time.monotonic() - started) * 1000)
    return {
        'n_gpu_layers': n_gpu_layers,
        'samples': len(samples),
        'p50_ms': round(percentile(samples, 50), 1),
        'p95_ms': round(percentile(samples, 95), 1),
        'min_ms': round(min(samples), 1),
        'max_ms': round(max(samples), 1),
        'mean_ms': round(statistics.mean(samples), 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--impl', required=True, choices=sorted(PATHS), help='where the retrieval context comes from')
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--auth-token', default='')
    parser.add_argument('--iterations', type=int, default=4, help='passes over the agent questions')
    args = parser.parse_args()

    with httpx.Client(
        base_url=args.base_url.rstrip('/'), headers=auth_headers(args.impl, args.auth_token), timeout=60.0
    ) as client:
        by_question = prompts(client, args.impl)

    load_before = [round(x, 2) for x in os.getloadavg()]
    devices = {}
    for name, layers in DEVICES.items():
        devices[name] = time_device(layers, by_question, args.iterations)
        print(f'{name}: p50 {devices[name]["p50_ms"]}ms  p95 {devices[name]["p95_ms"]}ms', flush=True)
    result = {
        'measured_at': datetime.now(UTC).isoformat(timespec='seconds'),
        'model': f'{REPO_ID} {FILENAME}',
        'n_ctx': N_CTX,
        'max_tokens': MAX_TOKENS,
        'temperature': TEMPERATURE,
        'context_from': args.impl,
        'host': {'platform': platform.platform(), 'machine': platform.machine()},
        'llama_cpp_python': version('llama_cpp_python'),
        'host_load': {'before_1_5_15m': load_before, 'after_1_5_15m': [round(x, 2) for x in os.getloadavg()]},
        'devices': devices,
    }
    OUT.write_text(json.dumps(result, indent=2) + '\n')
    print(f'wrote {OUT.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
