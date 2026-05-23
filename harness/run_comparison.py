#!/usr/bin/env python3
"""Run the platform comparison and generate a report.

Usage:
    python harness/run_comparison.py              # Metrics only (no servers needed)
    python harness/run_comparison.py --test-all    # Metrics + equivalence tests
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from metrics import collect_all, export_json, print_comparison

ROOT = Path(__file__).resolve().parent.parent


def run_metrics():
    print('=' * 60)
    print('PLATFORM COMPARISON: DX METRICS')
    print('=' * 60)
    results = collect_all()
    print_comparison(results)
    out = ROOT / 'docs' / 'metrics.json'
    export_json(results, out)
    print(f'\nExported to {out}')
    return results


def run_equivalence_tests(urls: list[str]):
    print('\n' + '=' * 60)
    print('PLATFORM COMPARISON: EQUIVALENCE TESTS')
    print('=' * 60)
    cmd = [sys.executable, '-m', 'pytest', 'harness/test_equivalence.py', '-v']
    for url in urls:
        cmd.extend(['--base-url', url])
    result = subprocess.run(cmd, cwd=str(ROOT))
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description='Platform comparison harness')
    parser.add_argument('--test-all', action='store_true', help='Run equivalence tests')
    parser.add_argument('--urls', nargs='*', default=[], help='Base URLs of running servers')
    args = parser.parse_args()

    run_metrics()

    if args.test_all:
        urls = args.urls or ['http://localhost:8000']
        sys.exit(run_equivalence_tests(urls))


if __name__ == '__main__':
    main()
