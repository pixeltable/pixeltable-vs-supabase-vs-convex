"""Collect DX metrics across all four platform implementations.

Measures:
- Lines of code (app code only, excluding generated/config/lock files)
- Number of source files
- Number of programming languages
- Number of external services required
- Number of env vars required
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

IMPLEMENTATIONS = {
    'pixeltable': {
        'dir': ROOT / 'pixeltable',
        'extensions': {'.py'},
        'exclude_patterns': {'__pycache__', '.pyc', 'uv.lock'},
        'languages': ['Python'],
        'external_services': ['OpenAI'],
        'env_vars': ['OPENAI_API_KEY'],
    },
    'supabase': {
        'dir': ROOT / 'supabase-app',
        'extensions': {'.ts', '.sql'},
        'exclude_patterns': {'node_modules', 'package-lock.json', '_generated'},
        'languages': ['TypeScript', 'SQL'],
        'external_services': ['Supabase Cloud', 'OpenAI'],
        'env_vars': ['SUPABASE_URL', 'SUPABASE_ANON_KEY', 'SUPABASE_SERVICE_ROLE_KEY', 'OPENAI_API_KEY'],
    },
    'convex': {
        'dir': ROOT / 'convex-app',
        'extensions': {'.ts'},
        'exclude_patterns': {'node_modules', 'package-lock.json', '_generated'},
        'languages': ['TypeScript'],
        'external_services': ['Convex Cloud', 'OpenAI'],
        'env_vars': ['CONVEX_URL', 'OPENAI_API_KEY'],
    },
    'modal': {
        'dir': ROOT / 'modal-app',
        'extensions': {'.py', '.sql'},
        'exclude_patterns': {'__pycache__', '.pyc', 'uv.lock'},
        'languages': ['Python', 'SQL'],
        'external_services': ['Modal', 'Supabase/Neon (pgvector)', 'OpenAI'],
        'env_vars': [
            'OPENAI_API_KEY',
            'SUPABASE_URL',
            'SUPABASE_SERVICE_ROLE_KEY',
            'MODAL_TOKEN_ID',
            'MODAL_TOKEN_SECRET',
        ],
    },
}


@dataclass
class ImplMetrics:
    name: str
    lines_of_code: int = 0
    num_files: int = 0
    languages: list[str] = field(default_factory=list)
    external_services: list[str] = field(default_factory=list)
    env_vars: list[str] = field(default_factory=list)
    file_breakdown: dict[str, int] = field(default_factory=dict)


def count_lines(filepath: Path) -> int:
    try:
        return sum(1 for line in filepath.read_text().splitlines() if line.strip() and not line.strip().startswith('#'))
    except Exception:
        return 0


def collect_metrics(name: str, config: dict) -> ImplMetrics:
    metrics = ImplMetrics(
        name=name,
        languages=config['languages'],
        external_services=config['external_services'],
        env_vars=config['env_vars'],
    )

    root = config['dir']
    for filepath in sorted(root.rglob('*')):
        if not filepath.is_file():
            continue
        if filepath.suffix not in config['extensions']:
            continue
        if any(pat in str(filepath) for pat in config['exclude_patterns']):
            continue

        loc = count_lines(filepath)
        rel = str(filepath.relative_to(root))
        metrics.file_breakdown[rel] = loc
        metrics.lines_of_code += loc
        metrics.num_files += 1

    return metrics


def collect_all() -> dict[str, ImplMetrics]:
    return {name: collect_metrics(name, cfg) for name, cfg in IMPLEMENTATIONS.items()}


def print_comparison(results: dict[str, ImplMetrics]) -> None:
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(title='Platform Comparison: DX Metrics')
        table.add_column('Metric', style='bold')
        for name in results:
            table.add_column(name.capitalize(), justify='right')

        table.add_row('Lines of Code', *[str(r.lines_of_code) for r in results.values()])
        table.add_row('Source Files', *[str(r.num_files) for r in results.values()])
        table.add_row('Languages', *[str(len(r.languages)) for r in results.values()])
        table.add_row('External Services', *[str(len(r.external_services)) for r in results.values()])
        table.add_row('Env Vars Required', *[str(len(r.env_vars)) for r in results.values()])
        console.print(table)

        for name, r in results.items():
            file_table = Table(title=f'{name.capitalize()} — File Breakdown')
            file_table.add_column('File', style='cyan')
            file_table.add_column('Lines', justify='right')
            for f, loc in sorted(r.file_breakdown.items()):
                file_table.add_row(f, str(loc))
            console.print(file_table)
    except ImportError:
        for name, r in results.items():
            print(f'\n{name}: {r.lines_of_code} LOC, {r.num_files} files, {len(r.languages)} langs')


def export_json(results: dict[str, ImplMetrics], output: Path | None = None) -> str:
    data = {}
    for name, r in results.items():
        data[name] = {
            'lines_of_code': r.lines_of_code,
            'num_files': r.num_files,
            'languages': r.languages,
            'num_languages': len(r.languages),
            'external_services': r.external_services,
            'num_external_services': len(r.external_services),
            'env_vars': r.env_vars,
            'num_env_vars': len(r.env_vars),
            'file_breakdown': r.file_breakdown,
        }
    out = json.dumps(data, indent=2)
    if output:
        output.write_text(out)
    return out


if __name__ == '__main__':
    results = collect_all()
    print_comparison(results)
    export_json(results, ROOT / 'docs' / 'metrics.json')
    print(f'\nMetrics exported to docs/metrics.json')
