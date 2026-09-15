#!/usr/bin/env python3
"""Ingest the fixture videos into one running implementation.

    python harness/seed.py --impl convex --base-url http://127.0.0.1:3211

Ingest is asynchronous on Pixeltable, which answers with a job to poll, and synchronous
on Supabase and Convex, which answer when the pipeline has finished. This waits for
either, so the three are comparable once it returns.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harness.conftest import PATHS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
VIDEOS = sorted((ROOT / 'fixtures' / 'videos').glob('*.mp4'))
TIMEOUT = 900.0


def wait_for_job(client: httpx.Client, job_url: str, deadline: float) -> None:
    """Poll a Pixeltable background job until it leaves `pending`."""
    while time.monotonic() < deadline:
        status = client.get(job_url).json().get('status')
        if status == 'done':
            return
        if status == 'error':
            raise RuntimeError(f'ingest job failed: {job_url}')
        time.sleep(2)
    raise TimeoutError(f'ingest job still pending: {job_url}')


def seed(impl: str, base_url: str, auth_token: str = '') -> int:
    if not VIDEOS:
        sys.exit('no fixture videos. Run: python fixtures/videos/generate.py')

    paths = PATHS[impl]
    headers = {'Authorization': f'Bearer {auth_token}'} if auth_token else {}
    with httpx.Client(base_url=base_url.rstrip('/'), headers=headers, timeout=TIMEOUT) as client:
        method, path = paths['ingest']
        for video in VIDEOS:
            started = time.monotonic()
            response = client.request(method, path, json={'video': str(video), 'title': video.name})
            response.raise_for_status()
            body = response.json()
            if job_url := body.get('job_url'):
                wait_for_job(client, job_url, started + TIMEOUT)
            print(f'  {video.name} ({time.monotonic() - started:.1f}s)')

        listed = client.request(*paths['list']).json()['rows']
    print(f'{len(listed)} video(s) listed on {impl}')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Seed one implementation with the fixture videos')
    parser.add_argument('--impl', required=True, choices=sorted(PATHS))
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--auth-token', default='')
    args = parser.parse_args()
    return seed(args.impl, args.base_url, args.auth_token)


if __name__ == '__main__':
    sys.exit(main())
