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
    },
    'supabase': {
        'runtimes_to_operate': ['Supabase (Postgres, Storage, Deno)', 'compute-service'],
        'needs_compute_service': True,
        'work_runs_on_insert': False,
        'incremental_column_add': False,
        'data_versioning': False,
    },
    'convex': {
        'runtimes_to_operate': ['Convex (database, actions, storage)', 'compute-service'],
        'needs_compute_service': True,
        'work_runs_on_insert': False,
        'incremental_column_add': False,
        'data_versioning': False,
    },
    'compute-service': {
        'runtimes_to_operate': ['compute-service'],
        'needs_compute_service': False,
        'work_runs_on_insert': False,
        'incremental_column_add': False,
        'data_versioning': False,
    },
}

# Counted per implementation rather than per language, because Supabase and Convex
# are both TypeScript and express the same concept differently.
#
# A metric is only reported for an implementation that has a pattern for it here.
# Anything absent renders as `n/a`, never as 0. An earlier version of this file had no
# `orchestration_hops`, `foreign_keys` or `db_triggers` pattern for Pixeltable, so the
# dataclass default of 0 was rendered in the README as if it had been measured, under a
# sentence promising every number was read from the source. Three of the bolded zeros in
# the headline table were not measurements. If a metric genuinely does not apply to a
# platform, say so; do not score it zero.
PATTERNS = {
    'pixeltable': {
        'tables': r'class \w+\(\s*TableModel(?![^)]*base=)',
        'views': r'class \w+\(\s*\n?\s*TableModel,[^)]*base=',
        'vector_indexes': r'pxt\.EmbeddingIndex\(',
        # The declared routes do no orchestration. The one hand-written route does:
        # it resolves a table, inserts, and reads the row back. That is 3, not 0.
        'orchestration_hops': r'pxt\.get_table\(|\.insert\(\[|\.collect\(\)',
        'http_routes_written_by_hand': r'@api\.(?:get|post|put|delete)\(',
    },
    'supabase': {
        'tables': r'CREATE TABLE',
        'views': r'CREATE (?:OR REPLACE )?VIEW',
        'vector_indexes': r'USING hnsw',
        'foreign_keys': r'REFERENCES \w+\(',
        'db_triggers': r'CREATE TRIGGER',
        'orchestration_hops': (
            r'supabase\s*\n?\s*\.from\(|supabase\.from\(|supabase\.storage\.'
            r'|supabase\.rpc\(|PERFORM notify_edge_function'
        ),
        # The documented handler shape: a default export whose fetch is wrapped.
        'http_routes_written_by_hand': r'fetch:\s*withSupabase\(|Deno\.serve\(',
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
    # None means the metric does not apply to this platform and renders as `n/a`.
    # It must never be conflated with a measured 0.
    tables: int | None = None
    views: int | None = None
    vector_indexes: int | None = None
    foreign_keys: int | None = None
    db_triggers: int | None = None
    orchestration_hops: int | None = None
    http_routes_written_by_hand: int | None = None
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
            if value is None:
                cells.append('n/a')  # no pattern for this platform; not a measured 0
            elif isinstance(value, list):
                cells.append(str(len(value)))
            else:
                cells.append(str(value))
        print(f'{label:<{width}}' + ''.join(f'{c:>20}' for c in cells))


def export_json(results: dict[str, ImplMetrics], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({name: asdict(m) for name, m in results.items()}, indent=2) + '\n')
    print(f'\nwrote {out.relative_to(ROOT)}')
