#!/usr/bin/env python3
"""Ingest the fixture videos into one running implementation.

    python harness/seed.py --impl convex --base-url http://127.0.0.1:3211
    python harness/seed.py --impl convex --base-url http://127.0.0.1:3211 --tier large

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
from harness.conftest import PATHS, auth_headers  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 900.0

TIERS = {'small': ROOT / 'fixtures' / 'videos', 'large': ROOT / 'fixtures' / 'videos' / 'large'}


def videos_for(tier: str) -> list[Path]:
    return sorted(TIERS[tier].glob('*.mp4'))


def wait_for_job(client: httpx.Client, job_url: str, deadline: float) -> None:
    """Poll a Pixeltable background job until it leaves `pending`."""
    while time.monotonic() < deadline:
        resp = client.get(job_url)
        resp.raise_for_status()
        status = resp.json().get('status')
        if status == 'done':
            return
        if status == 'error':
            raise RuntimeError(f'ingest job failed: {job_url}')
        time.sleep(2)
    raise TimeoutError(f'ingest job still pending: {job_url}')


def seed(impl: str, base_url: str, auth_token: str = '', tier: str = 'small') -> int:
    videos = videos_for(tier)
    if not videos:
        sys.exit(f'no {tier}-tier fixture videos. Run: python fixtures/videos/generate.py --tier {tier}')

    paths = PATHS[impl]
    headers = auth_headers(impl, auth_token)
    with httpx.Client(base_url=base_url.rstrip('/'), headers=headers, timeout=TIMEOUT) as client:
        method, path = paths['ingest']
        for video in videos:
            started = time.monotonic()
            response = client.request(method, path, json={'video': str(video), 'title': video.name})
            response.raise_for_status()
            body = response.json()
            if job_url := body.get('job_url'):
                wait_for_job(client, job_url, started + TIMEOUT)
            print(f'  {video.name} ({time.monotonic() - started:.1f}s)')

        list_resp = client.request(*paths['list'])
        list_resp.raise_for_status()
        listed = list_resp.json()['rows']
    print(f'{len(listed)} video(s) listed on {impl}')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Seed one implementation with the fixture videos')
    parser.add_argument('--impl', required=True, choices=sorted(PATHS))
    parser.add_argument('--base-url', default='', help='Root URL of the running implementation')
    parser.add_argument('--auth-token', default='')
    parser.add_argument('--tier', choices=sorted(TIERS), default='small')
    args = parser.parse_args()

    base_url = args.base_url
    if not base_url and args.impl == 'pixeltable':
        from harness.conftest import _auto_discover_pixeltable_url

        discovered = _auto_discover_pixeltable_url()
        if discovered:
            base_url = discovered

    if not base_url:
        sys.exit(f'--base-url required for {args.impl} (or start Pixeltable service)')

    return seed(args.impl, base_url, args.auth_token, args.tier)


if __name__ == '__main__':
    sys.exit(main())
