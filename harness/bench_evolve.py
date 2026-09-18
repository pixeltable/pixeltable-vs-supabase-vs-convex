#!/usr/bin/env python3
"""Time one evolution task on all three, against a populated corpus.

    python harness/bench_evolve.py --supabase-token "$SECRET" --convex-url http://127.0.0.1:3211

The task: make the video title semantically searchable. The column is new, the rows
already exist, and an embedding is not derivable in SQL, so every existing row has to be
read, sent to a model, and written back. That is the shape of every real schema change on
a table that already holds data, and it is the claim this repo makes and does not measure.

Each platform's change is applied, timed end to end, and reverted. Nothing here is
committed to the implementations, because the contract does not need the feature; the
diffs live in `harness/evolve/` and are quoted in `docs/EVOLVE.md` with these timings.

Wall time is measured from "the change is applied" to "every existing row has the new
value". On Pixeltable that is one command. On the other two it is a schema change and
then a backfill, and both halves are reported.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import tomllib  # noqa: E402

from harness.metrics import count_lines  # noqa: E402

EVOLVE = ROOT / 'harness' / 'evolve'
OUT = ROOT / 'docs' / 'evolve.json'
with open(ROOT / 'supabase-app' / 'supabase' / 'config.toml', 'rb') as f:
    DB_CONTAINER = f'supabase_db_{tomllib.load(f)["project"]["id"]}'


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None, timeout: int = 1800) -> str:
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env={**os.environ, **(env or {})}
    )
    if proc.returncode != 0:
        raise RuntimeError(f'{" ".join(cmd[:4])}... failed:\n{proc.stdout[-600:]}\n{proc.stderr[-600:]}')
    return proc.stdout


def patch(path: Path, patch_file: Path, reverse: bool = False) -> None:
    before, after = patch_file.read_text().split('\n---\n')
    old, new = (after, before) if reverse else (before, after)
    text = path.read_text()
    if old.rstrip('\n') not in text:
        raise RuntimeError(f'{path.name}: cannot apply {patch_file.name}; anchor not found')
    path.write_text(text.replace(old.rstrip('\n'), new.rstrip('\n'), 1))


# ----------------------------------------------------------------- pixeltable


def evolve_pixeltable() -> dict:
    app = ROOT / 'pixeltable' / 'app.py'
    original = app.read_text()
    patch(app, EVOLVE / 'pixeltable.patch')
    try:
        started = time.monotonic()
        out = run(['pxt', 'schema', 'update', 'app.py', 'media', '-f'], cwd=app.parent)
        elapsed = time.monotonic() - started
    finally:
        app.write_text(original)
        run(['pxt', 'schema', 'update', 'app.py', 'media', '-f', '--allow-destructive'], cwd=app.parent)
    return {
        'schema_change_sec': round(elapsed, 2),
        'backfill_sec': 0.0,
        'total_sec': round(elapsed, 2),
        'lines_written': loc_of_patch(EVOLVE / 'pixeltable.patch'),
        'files_touched': 1,
        'note': 'one command; the schema change and the backfill are the same step',
        'output': out.strip().splitlines()[-4:],
    }


def loc_of_patch(patch_file: Path) -> int:
    """Lines the patch writes, ignoring the context it anchors on.

    A changed line counts the same as an added one: replacing `})` with
    `}).searchIndex(...)` is a line you write, and a length difference of zero would say
    otherwise.
    """
    before, after = patch_file.read_text().split('\n---\n')
    unchanged = [line for line in before.splitlines() if line.strip()]
    written = 0
    for line in after.splitlines():
        if not line.strip():
            continue
        if line in unchanged:
            unchanged.remove(line)
        else:
            written += 1
    return written


# ------------------------------------------------------------------- supabase


def psql(sql: str) -> str:
    return run(['docker', 'exec', DB_CONTAINER, 'psql', '-U', 'postgres', '-d', 'postgres', '-c', sql])


def evolve_supabase(token: str) -> dict:
    ddl = (EVOLVE / 'supabase.sql').read_text()
    backfill = EVOLVE / 'supabase_backfill.ts'
    try:
        started = time.monotonic()
        psql(ddl)
        schema_sec = time.monotonic() - started

        backfill_started = time.monotonic()
        out = run(
            ['npx', '--yes', 'deno@2.5.5', 'run', '-A', str(backfill)],
            env={
                'SUPABASE_URL': 'http://127.0.0.1:54321',
                'SUPABASE_KEY': token,
                'COMPUTE_SERVICE_URL': 'http://127.0.0.1:9000',
            },
        )
        backfill_sec = time.monotonic() - backfill_started
    finally:
        psql(
            'DROP INDEX IF EXISTS videos_title_embedding_idx; ALTER TABLE videos DROP COLUMN IF EXISTS title_embedding;'
        )
    return {
        'schema_change_sec': round(schema_sec, 2),
        'backfill_sec': round(backfill_sec, 2),
        'total_sec': round(schema_sec + backfill_sec, 2),
        'lines_written': count_lines(backfill) + count_lines(EVOLVE / 'supabase.sql'),
        'files_touched': 2,
        'note': 'ALTER TABLE is instant; the backfill reads, embeds and writes every row',
        'output': out.strip().splitlines()[-2:],
    }


# --------------------------------------------------------------------- convex


def _stop_convex_watcher() -> None:
    """`convex dev --once` refuses to share the port with the watcher."""
    subprocess.run(['pkill', '-f', 'convex dev'], capture_output=True)
    # The watcher supervises a separate convex-local-backend binary that keeps the port
    # after the watcher exits, and `--once` refuses to start while it holds one.
    subprocess.run(['pkill', '-f', 'convex-local-backend'], capture_output=True)
    time.sleep(5)


def _start_convex_watcher(app: Path) -> None:
    log = Path(os.environ.get('TMPDIR', '/tmp')) / 'convex-dev-evolve.log'
    with log.open('w') as handle:
        subprocess.Popen(['npx', 'convex', 'dev'], cwd=app, stdout=handle, stderr=handle, start_new_session=True)
    time.sleep(25)


def evolve_convex() -> dict:
    app = ROOT / 'convex-app'
    schema = app / 'convex' / 'schema.ts'
    migrations = app / 'convex' / 'migrations.ts'
    original = schema.read_text()
    _stop_convex_watcher()
    try:
        patch(schema, EVOLVE / 'convex_schema.patch')
        shutil.copy(EVOLVE / 'convex_migrations.ts', migrations)

        started = time.monotonic()
        run(['npx', 'convex', 'dev', '--once'], cwd=app)
        schema_sec = time.monotonic() - started

        backfill_started = time.monotonic()
        out = run(['npx', 'convex', 'run', 'migrations:backfillTitleEmbeddings'], cwd=app)
        backfill_sec = time.monotonic() - backfill_started
    finally:
        # Convex validates existing documents against the schema on push, so the field has
        # to come off every row before schema.ts can stop declaring it. Reverting this
        # migration is another migration.
        run(['npx', 'convex', 'run', 'migrations:clearTitleEmbeddings'], cwd=app)
        schema.write_text(original)
        migrations.unlink(missing_ok=True)
        run(['npx', 'convex', 'dev', '--once'], cwd=app)
        _start_convex_watcher(app)
    return {
        'schema_change_sec': round(schema_sec, 2),
        'backfill_sec': round(backfill_sec, 2),
        'total_sec': round(schema_sec + backfill_sec, 2),
        'lines_written': count_lines(EVOLVE / 'convex_migrations.ts') + loc_of_patch(EVOLVE / 'convex_schema.patch'),
        'files_touched': 2,
        'note': 'a push, then an action that pages rows through a query and a mutation',
        'output': out.strip().splitlines()[-2:],
    }


def evolve_convex_searchindex() -> dict:
    """The same task answered with Convex's built-in full-text index instead.

    `searchIndex` builds over a field the documents already carry, so there is no backfill
    and no reverse migration. It is not the same feature: this is lexical search over the
    title, where the other two embed it. Measured so the vector number can be read for what
    it is, the price of semantic parity rather than the price of searching a title.
    """
    app = ROOT / 'convex-app'
    schema = app / 'convex' / 'schema.ts'
    original = schema.read_text()
    _stop_convex_watcher()
    try:
        patch(schema, EVOLVE / 'convex_schema_searchindex.patch')
        started = time.monotonic()
        run(['npx', 'convex', 'dev', '--once'], cwd=app)
        schema_sec = time.monotonic() - started
    finally:
        schema.write_text(original)
        run(['npx', 'convex', 'dev', '--once'], cwd=app)
        _start_convex_watcher(app)
    return {
        'schema_change_sec': round(schema_sec, 2),
        'backfill_sec': 0.0,
        'total_sec': round(schema_sec, 2),
        'lines_written': loc_of_patch(EVOLVE / 'convex_schema_searchindex.patch'),
        'files_touched': 1,
        'note': 'lexical, not semantic: searchIndex builds over an existing field, so no backfill',
        'output': ['no backfill step'],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--supabase-token', default='')
    parser.add_argument('--only', choices=['pixeltable', 'supabase', 'convex', 'convex-searchindex'], action='append')
    args = parser.parse_args()
    wanted = args.only or ['pixeltable', 'supabase', 'convex', 'convex-searchindex']

    results: dict = {'measured_at': datetime.now(UTC).isoformat(timespec='seconds')}
    for name in wanted:
        print(f'--- {name} ---', flush=True)
        if name == 'supabase' and not args.supabase_token:
            print('  skipped: --supabase-token required')
            continue
        result = {
            'pixeltable': evolve_pixeltable,
            'convex': evolve_convex,
            'convex-searchindex': evolve_convex_searchindex,
        }.get(name, lambda: evolve_supabase(args.supabase_token))()
        results[name] = result
        print(
            f'  schema {result["schema_change_sec"]}s + backfill {result["backfill_sec"]}s '
            f'= {result["total_sec"]}s, {result["lines_written"]} lines in {result["files_touched"]} file(s)',
            flush=True,
        )

    existing = json.loads(OUT.read_text()) if OUT.exists() else {}
    existing.update(results)
    OUT.write_text(json.dumps(existing, indent=2) + '\n')
    print(f'wrote {OUT.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
