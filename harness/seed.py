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
from harness.api_contract import IngestAck  # noqa: E402
from harness.conftest import PATHS, auth_headers  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 900.0

TIERS = {
    'small': ROOT / 'fixtures' / 'videos',
    'large': ROOT / 'fixtures' / 'videos' / 'large',
    'xl': ROOT / 'fixtures' / 'videos' / 'xl',
}


def videos_for(tier: str) -> list[Path]:
    return sorted(TIERS[tier].glob('*.mp4'))


def wait_for_job(client: httpx.Client, job_url: str, deadline: float, poll_sec: float = 2.0) -> None:
    """Poll a Pixeltable background job until it leaves `pending`.

    The interval is an argument because it lands in the measurement: a 2s poll rounds
    every asynchronous ingest up to the next 2s and charges Pixeltable for the harness.
    Timing code passes a small value; seeding does not need to.
    """
    while time.monotonic() < deadline:
        resp = client.get(job_url)
        resp.raise_for_status()
        status = resp.json().get('status')
        if status == 'done':
            return
        if status == 'error':
            raise RuntimeError(f'ingest job failed: {job_url}')
        time.sleep(poll_sec)
    raise TimeoutError(f'ingest job still pending: {job_url}')


def seed(impl: str, base_url: str, auth_token: str = '', tier: str = 'small', skip_existing: bool = False) -> int:
    videos = videos_for(tier)
    if not videos:
        sys.exit(f'no {tier}-tier fixture videos. Run: python fixtures/videos/generate.py --tier {tier}')

    paths = PATHS[impl]
    headers = auth_headers(impl, auth_token)
    with httpx.Client(base_url=base_url.rstrip('/'), headers=headers, timeout=TIMEOUT) as client:
        method, path = paths['ingest']
        if skip_existing:
            listed = client.request(*paths['list'])
            listed.raise_for_status()
            have = {row['video_title'] for row in listed.json()['rows']}
            videos = [v for v in videos if v.name not in have]
            print(f'{len(have)} already seeded, {len(videos)} to go')
        for video in videos:
            started = time.monotonic()
            response = client.request(method, path, json={'video': str(video), 'title': video.name})
            response.raise_for_status()
            body = response.json()
            # The ack shape is part of the contract; parse it here because the one test
            # that validates it skips whenever the target is already seeded.
            ack = IngestAck(**body if 'rows' not in body else body['rows'][0])
            if ack.job_url:
                wait_for_job(client, ack.job_url, started + TIMEOUT)
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
    parser.add_argument(
        '--skip-existing',
        action='store_true',
        help='Skip titles the list route already returns. No implementation exposes a '
        'delete route, so a duplicate seeded by mistake cannot be removed.',
    )
    args = parser.parse_args()

    base_url = args.base_url
    if not base_url and args.impl == 'pixeltable':
        from harness.conftest import _auto_discover_pixeltable_url

        discovered = _auto_discover_pixeltable_url()
        if discovered:
            base_url = discovered

    if not base_url:
        sys.exit(f'--base-url required for {args.impl} (or start Pixeltable service)')

    return seed(args.impl, base_url, args.auth_token, args.tier, args.skip_existing)


if __name__ == '__main__':
    sys.exit(main())
