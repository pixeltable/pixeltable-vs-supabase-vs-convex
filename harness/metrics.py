"""Measure the three implementations.

Everything in `MEASURED` is derived from the source on disk. Everything in
`CLASSIFIED` is a judgment call written down by hand, and is reported as such.
The distinction matters: an earlier version of this file hard-coded the
architecture numbers and the docs quoted them as if they had been measured.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Comment syntax per language. The previous counter treated '#' as the only comment
# marker, so every '//' in TypeScript and every '--' in SQL counted as code, which
# inflated both alternatives against Pixeltable.
LINE_COMMENTS = {'.py': ('#',), '.ts': ('//',), '.tsx': ('//',), '.sql': ('--',)}
BLOCK_COMMENTS = {'.ts': ('/*', '*/'), '.tsx': ('/*', '*/'), '.sql': ('/*', '*/')}

CONFIG_NAMES = {
    'package.json',
    'pyproject.toml',
    'tsconfig.json',
    'config.toml',
    'pixeltable.toml',
    '.env.example',
}
LOCK_NAMES = {'package-lock.json', 'uv.lock', 'poetry.lock'}  # generated, counted nowhere

IMPLEMENTATIONS = {
    'pixeltable': {
        'dir': ROOT / 'pixeltable',
        'extensions': {'.py'},
        'exclude_patterns': {'__pycache__', '.pyc'},
        'languages': ['Python'],
        'router_files': set(),
    },
    'supabase': {
        'dir': ROOT / 'supabase-app',
        'extensions': {'.ts', '.sql'},
        'exclude_patterns': {'node_modules', '_generated'},
        'languages': ['TypeScript', 'SQL'],
        'router_files': set(),  # each Deno.serve handler is the route and the logic
    },
    'convex': {
        'dir': ROOT / 'convex-app',
        'extensions': {'.ts'},
        'exclude_patterns': {'node_modules', '_generated'},
        'languages': ['TypeScript'],
        'router_files': {'http.ts'},  # pure dispatch, counted under HTTP routes instead
    },
    'compute-service': {
        'dir': ROOT / 'compute-service',
        'extensions': {'.py'},
        'exclude_patterns': {'__pycache__', '.pyc'},
        'languages': ['Python'],
        'router_files': set(),
    },
}

# Orchestration counts pipeline plumbing, not HTTP dispatch, which is already counted
# as `http_routes_written_by_hand`. Convex's http.ts is pure dispatch: every route
# there is a `ctx.runAction` into the function that does the work. Counting those
# would charge Convex twice for one layer, and Supabase has no equivalent file since
# each Deno.serve handler holds its own logic.
ROUTER_ONLY_METRICS = {'orchestration_hops'}

# Written by hand, reported as hand-classified, never presented as a measurement.
CLASSIFIED = {
    'pixeltable': {
        'runtimes_to_operate': ['Pixeltable (one process)'],
        'needs_compute_service': False,
        'work_runs_on_insert': True,
        'incremental_column_add': True,
        'data_versioning': True,
        'account_required_to_typecheck': False,
    },
    'supabase': {
        'runtimes_to_operate': ['Supabase (Postgres, Storage, Deno)', 'compute-service'],
        'needs_compute_service': True,
        'work_runs_on_insert': False,
        'incremental_column_add': False,
        'data_versioning': False,
        'account_required_to_typecheck': False,
    },
    'convex': {
        'runtimes_to_operate': ['Convex (database, actions, storage)', 'compute-service'],
        'needs_compute_service': True,
        'work_runs_on_insert': False,
        'incremental_column_add': False,
        'data_versioning': False,
        'account_required_to_typecheck': True,
    },
    'compute-service': {
        'runtimes_to_operate': ['compute-service'],
        'needs_compute_service': False,
        'work_runs_on_insert': False,
        'incremental_column_add': False,
        'data_versioning': False,
        'account_required_to_typecheck': False,
    },
}

# Counted per implementation rather than per language, because Supabase and Convex
# are both TypeScript and express the same concept differently. A pattern that does
# not apply to an implementation is simply absent.
PATTERNS = {
    'pixeltable': {
        'tables': r'class \w+\(\s*TableModel(?![^)]*base=)',
        'views': r'class \w+\(\s*\n?\s*TableModel,[^)]*base=',
        'vector_indexes': r'pxt\.EmbeddingIndex\(',
        'http_routes_written_by_hand': r'@api\.(?:get|post|put|delete)\(',
    },
    'supabase': {
        'tables': r'CREATE TABLE',
        'vector_indexes': r'USING hnsw',
        'foreign_keys': r'REFERENCES \w+\(',
        'db_triggers': r'CREATE TRIGGER',
        'orchestration_hops': (
            r'supabase\s*\n?\s*\.from\(|supabase\.from\(|supabase\.storage\.'
            r'|supabase\.rpc\(|PERFORM notify_edge_function'
        ),
        'http_routes_written_by_hand': r'Deno\.serve\(',
    },
    'convex': {
        'tables': r'defineTable\(',
        'vector_indexes': r'\.vectorIndex\(',
        'orchestration_hops': r'ctx\.run(?:Mutation|Query|Action)\(|scheduler\.runAfter\(',
        'http_routes_written_by_hand': r'http\.route\(',
    },
    'compute-service': {
        'http_routes_written_by_hand': r'@app\.(?:get|post)\(',
    },
}


@dataclass
class ImplMetrics:
    name: str
    app_loc: int = 0
    config_loc: int = 0
    app_files: int = 0
    languages: list[str] = field(default_factory=list)
    env_vars: list[str] = field(default_factory=list)
    tables: int = 0
    views: int = 0
    vector_indexes: int = 0
    foreign_keys: int = 0
    db_triggers: int = 0
    orchestration_hops: int = 0
    http_routes_written_by_hand: int = 0
    external_hosts: list[str] = field(default_factory=list)
    file_breakdown: dict[str, int] = field(default_factory=dict)
    classified: dict = field(default_factory=dict)


def count_lines(path: Path) -> int:
    """Non-blank, non-comment lines, using the comment syntax of the file's language."""
    try:
        text = path.read_text()
    except OSError:
        return 0

    markers = LINE_COMMENTS.get(path.suffix, ())
    block = BLOCK_COMMENTS.get(path.suffix)
    count, in_block = 0, False

    for raw in text.splitlines():
        line = raw.strip()
        if in_block:
            if block and block[1] in line:
                in_block = False
            continue
        if not line:
            continue
        if block and line.startswith(block[0]):
            if block[1] not in line:
                in_block = True
            continue
        if any(line.startswith(m) for m in markers):
            continue
        count += 1
    return count


def _read(path: Path) -> str:
    try:
        return path.read_text()
    except OSError:
        return ''


def collect_env_vars(root: Path) -> list[str]:
    example = root / '.env.example'
    if not example.exists():
        return []
    return sorted(
        line.split('=', 1)[0].strip()
        for line in example.read_text().splitlines()
        if '=' in line and not line.strip().startswith('#')
    )


def collect_external_hosts(sources: list[Path]) -> list[str]:
    """Distinct network destinations the code reaches for at runtime."""
    hosts: set[str] = set()
    for path in sources:
        body = _read(path)
        for url in re.findall(r'https?://[a-zA-Z0-9._%-]+', body):
            host = url.split('//', 1)[1]
            if host.startswith(('localhost', '127.0.0.1', 'host.docker.internal')):
                continue
            if host.startswith('esm.sh'):
                continue  # a module import, not a runtime dependency
            hosts.add(host)
        if 'COMPUTE_SERVICE_URL' in body:
            hosts.add('compute-service (self-operated)')
    return sorted(hosts)


def collect_metrics(name: str, config: dict) -> ImplMetrics:
    root = config['dir']
    metrics = ImplMetrics(name=name, languages=config['languages'], classified=CLASSIFIED.get(name, {}))
    if not root.exists():
        raise FileNotFoundError(f'{name}: {root} does not exist')

    sources: list[Path] = []
    for path in sorted(root.rglob('*')):
        if not path.is_file() or any(p in str(path) for p in config['exclude_patterns']):
            continue
        rel = str(path.relative_to(root))
        if path.name in LOCK_NAMES:
            continue
        if path.name in CONFIG_NAMES:
            metrics.config_loc += count_lines(path)
            continue
        if path.suffix not in config['extensions']:
            continue
        loc = count_lines(path)
        metrics.file_breakdown[rel] = loc
        metrics.app_loc += loc
        metrics.app_files += 1
        sources.append(path)

    router_files = config.get('router_files', set())
    for field_name, pattern in PATTERNS.get(name, {}).items():
        paths = [p for p in sources if not (field_name in ROUTER_ONLY_METRICS and p.name in router_files)]
        setattr(metrics, field_name, sum(len(re.findall(pattern, _read(p), re.MULTILINE)) for p in paths))

    metrics.env_vars = collect_env_vars(root)
    metrics.external_hosts = collect_external_hosts(sources)
    return metrics


def collect_all() -> dict[str, ImplMetrics]:
    return {name: collect_metrics(name, config) for name, config in IMPLEMENTATIONS.items()}


ROWS = [
    ('App LOC', 'app_loc'),
    ('App files', 'app_files'),
    ('Config LOC', 'config_loc'),
    ('Tables', 'tables'),
    ('Views', 'views'),
    ('Vector indexes', 'vector_indexes'),
    ('Foreign keys', 'foreign_keys'),
    ('DB triggers', 'db_triggers'),
    ('Orchestration hops', 'orchestration_hops'),
    ('HTTP routes written by hand', 'http_routes_written_by_hand'),
    ('Env vars', 'env_vars'),
    ('External hosts', 'external_hosts'),
]


def print_comparison(results: dict[str, ImplMetrics]) -> None:
    names = list(results)
    width = max(len(label) for label, _ in ROWS) + 2
    header = f'{"Measured":<{width}}' + ''.join(f'{n:>20}' for n in names)
    print(header)
    print('-' * len(header))
    for label, attr in ROWS:
        cells = []
        for name in names:
            value = getattr(results[name], attr)
            cells.append(str(len(value)) if isinstance(value, list) else str(value))
        print(f'{label:<{width}}' + ''.join(f'{c:>20}' for c in cells))


def export_json(results: dict[str, ImplMetrics], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({name: asdict(m) for name, m in results.items()}, indent=2) + '\n')
    print(f'\nwrote {out.relative_to(ROOT)}')
