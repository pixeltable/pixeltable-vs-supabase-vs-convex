#!/usr/bin/env python3
"""Measure the implementations, and optionally test one that is running.

python harness/run_comparison.py
python harness/run_comparison.py --test --impl pixeltable --base-url http://localhost:8123
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from metrics import collect_all, export_json, print_comparison

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description='Platform comparison harness')
    parser.add_argument('--test', action='store_true', help='Also run the equivalence suite')
    parser.add_argument('--impl', default='pixeltable', help='Which implementation is running')
    parser.add_argument('--base-url', default='http://localhost:8000')
    parser.add_argument('--auth-token', default='')
    args = parser.parse_args()

    results = collect_all()
    print_comparison(results)
    export_json(results, ROOT / 'docs' / 'metrics.json')

    if not args.test:
        return 0

    print(f'\ntesting {args.impl} at {args.base_url}\n')
    cmd = [
        sys.executable,
        '-m',
        'pytest',
        str(ROOT / 'harness' / 'test_equivalence.py'),
        f'--base-url={args.base_url}',
        f'--impl={args.impl}',
        '-v',
    ]
    if args.auth_token:
        cmd.append(f'--auth-token={args.auth_token}')
    # The previous version dropped this return code, so --test-all exited 0 on failure.
    return subprocess.run(cmd).returncode


if __name__ == '__main__':
    sys.exit(main())
