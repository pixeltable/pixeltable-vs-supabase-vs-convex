"""Does the measuring code measure what it claims?

    pytest harness/test_metrics.py

Every line count and architecture count in the README and the docs comes from
`harness/metrics.py`, and a miscount nobody catches is indistinguishable from a lie. These
tests use fixtures with counts that can be read off by eye.
"""

from __future__ import annotations

import re
from dataclasses import fields
from pathlib import Path

import pytest

from harness.metrics import (
    CONFIG_NAMES,
    IMPLEMENTATIONS,
    LOCK_NAMES,
    PATTERNS,
    ROUTER_ONLY_METRICS,
    ROWS,
    ImplMetrics,
    collect_metrics,
    count_lines,
)


def write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


class TestCountLines:
    def test_python_skips_blanks_and_comments(self, tmp_path):
        path = write(
            tmp_path,
            'a.py',
            '# a comment\n\nx = 1\n   \n    # indented comment\ny = 2  # trailing comment is code\n',
        )
        assert count_lines(path) == 2

    def test_typescript_skips_line_and_block_comments(self, tmp_path):
        path = write(
            tmp_path,
            'a.ts',
            '// header\n/* block\n   still block\n*/\nconst x = 1;\n/* one liner */\nconst y = 2; // trailing\n',
        )
        assert count_lines(path) == 2

    def test_sql_uses_its_own_marker(self, tmp_path):
        """`--` is a comment in SQL and nothing at all in Python or TypeScript."""
        path = write(tmp_path, 'a.sql', '-- comment\nCREATE TABLE t (id int);\n\n-- another\nSELECT 1;\n')
        assert count_lines(path) == 2

    def test_a_marker_inside_a_line_is_code(self, tmp_path):
        """Only a line that begins with the marker is a comment."""
        path = write(tmp_path, 'a.ts', 'const url = "http://x"; // not a comment until here\n')
        assert count_lines(path) == 1

    def test_toml_comments_are_comments(self, tmp_path):
        """Config files carry explanatory comments; counting them inflates config LOC."""
        path = write(tmp_path, 'pyproject.toml', '# why this dep\n[project]\nname = "x"\n\n# note\n')
        assert count_lines(path) == 2

    def test_env_example_is_matched_by_name(self, tmp_path):
        """`.env.example` has the suffix `.example`, which says nothing about comments."""
        path = write(tmp_path, '.env.example', '# what this is for\nFOO=bar\n')
        assert count_lines(path) == 1

    def test_unreadable_file_counts_zero(self, tmp_path):
        assert count_lines(tmp_path / 'missing.py') == 0


class TestCollect:
    @pytest.fixture
    def impl(self, tmp_path):
        write(tmp_path, 'app.py', 'import x\n\n# comment\nprint(1)\n')
        write(tmp_path, 'lib/helper.py', 'def f():\n    return 1\n')
        write(tmp_path, 'pyproject.toml', '[project]\nname = "x"\n')
        write(tmp_path, 'uv.lock', '\n'.join(f'line {i}' for i in range(500)))
        write(tmp_path, 'README.md', 'not code\n')
        write(tmp_path, '__pycache__/app.pyc', 'binary-ish\n')
        return {
            'dir': tmp_path,
            'extensions': {'.py'},
            'exclude_patterns': {'__pycache__', '.pyc'},
            'languages': ['Python'],
            'router_files': set(),
        }

    def test_counts_only_source(self, impl):
        metrics = collect_metrics('x', impl)
        assert metrics.app_loc == 4
        assert metrics.app_files == 2

    def test_config_is_separate_and_locks_are_nowhere(self, impl):
        metrics = collect_metrics('x', impl)
        assert metrics.config_loc == 2
        assert 'uv.lock' not in metrics.file_breakdown
        assert metrics.app_loc == 4  # 500 lock lines are in neither total

    def test_excluded_directories_are_skipped(self, impl):
        assert '__pycache__/app.pyc' not in collect_metrics('x', impl).file_breakdown

    def test_a_metric_with_no_pattern_is_none_not_zero(self, impl):
        """`n/a` and `0` are different claims, and only one of them is a measurement."""
        metrics = collect_metrics('x', impl)
        assert metrics.tables is None
        assert metrics.foreign_keys is None
        assert metrics.db_triggers is None

    def test_missing_directory_is_an_error_not_an_empty_row(self, tmp_path, impl):
        impl = {**impl, 'dir': tmp_path / 'nope'}
        with pytest.raises(FileNotFoundError):
            collect_metrics('x', impl)


class TestRouterExclusion:
    def test_orchestration_skips_router_files_but_loc_does_not(self, tmp_path):
        """A pure-dispatch file is counted in LOC and excluded from pipeline hops.

        Counting its `ctx.runAction` calls would charge the same layer twice: once as
        hand-written routes and once as orchestration.
        """
        write(tmp_path, 'http.ts', 'ctx.runAction(a);\nctx.runAction(b);\nhttp.route({});\n')
        write(tmp_path, 'ingest.ts', 'ctx.runMutation(c);\n')
        config = {
            'dir': tmp_path,
            'extensions': {'.ts'},
            'exclude_patterns': set(),
            'languages': ['TypeScript'],
            'router_files': {'http.ts'},
        }
        metrics = collect_metrics('convex', config)
        assert metrics.orchestration_hops == 1
        assert metrics.http_routes_written_by_hand == 1
        assert metrics.app_loc == 4


class TestPatternsAreWellFormed:
    @pytest.mark.parametrize('impl', sorted(PATTERNS))
    def test_every_pattern_compiles(self, impl):
        for name, pattern in PATTERNS[impl].items():
            re.compile(pattern), f'{impl}.{name}'

    @pytest.mark.parametrize('impl', sorted(PATTERNS))
    def test_every_pattern_names_a_real_field(self, impl):
        """`setattr` invents an attribute for a typo, and the typo then reports as `n/a`."""
        known = {f.name for f in fields(ImplMetrics)}
        unknown = set(PATTERNS[impl]) - known
        assert not unknown, f'{impl} has patterns for fields ImplMetrics does not declare: {sorted(unknown)}'

    def test_every_printed_row_names_a_real_field(self):
        known = {f.name for f in fields(ImplMetrics)}
        unknown = {attr for _, attr in ROWS} - known
        assert not unknown, f'ROWS names fields ImplMetrics does not declare: {sorted(unknown)}'

    def test_router_only_metrics_are_real_fields(self):
        known = {f.name for f in fields(ImplMetrics)}
        assert not ROUTER_ONLY_METRICS - known

    def test_config_and_lock_names_do_not_overlap(self):
        assert not CONFIG_NAMES & LOCK_NAMES


class TestAgainstTheRealTree:
    """The patterns have to find the things the docs say they find."""

    def test_every_implementation_directory_exists(self):
        for name, config in IMPLEMENTATIONS.items():
            assert config['dir'].exists(), f'{name}: {config["dir"]} is missing'

    def test_pixeltable_is_one_file(self):
        metrics = collect_metrics('pixeltable', IMPLEMENTATIONS['pixeltable'])
        assert metrics.app_files == 1
        assert metrics.app_loc > 0

    @pytest.mark.parametrize('impl', ['pixeltable', 'supabase', 'convex'])
    def test_every_implementation_has_two_vector_indexes(self, impl):
        """One for frames, one for transcripts. A pattern that stops matching reads as 0."""
        assert collect_metrics(impl, IMPLEMENTATIONS[impl]).vector_indexes == 2
