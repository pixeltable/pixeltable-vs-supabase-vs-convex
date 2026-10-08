"""validate.py and aggregate.py against the committed 2026-10-07 results and broken copies of them."""

import json
import shutil
from pathlib import Path

import aggregate
import pytest
import validate

RESULTS = Path(__file__).resolve().parent / 'results'
DAY = '2026-10-07'


@pytest.fixture
def day(tmp_path: Path) -> Path:
    shutil.copytree(RESULTS / DAY, tmp_path / DAY)
    shutil.copytree(RESULTS / f'{DAY}-set-aside', tmp_path / f'{DAY}-set-aside')
    return tmp_path / DAY


def edit(path: Path, change) -> None:
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


def test_committed_results_pass(day: Path) -> None:
    validate.main(day)


def test_a_target_missing_from_every_run_fails(day: Path) -> None:
    for run in day.glob('us-east-1/run-*.json'):
        edit(run, lambda d: d['latency'].pop('Render'))
    with pytest.raises(SystemExit):
        validate.main(day)


def test_a_section_missing_from_every_run_fails(day: Path) -> None:
    for run in day.glob('us-east-1/run-*.json'):
        edit(run, lambda d: d.pop('resilience'))
    with pytest.raises(SystemExit):
        validate.main(day)


def test_fewer_than_three_cold_passes_fails(day: Path) -> None:
    sorted(day.glob('eu-west-1/cold-*.json'))[0].unlink()
    with pytest.raises(SystemExit):
        validate.main(day)


def test_the_set_aside_pass_fails_when_published(day: Path) -> None:
    shutil.copy(day.parent / f'{DAY}-set-aside' / 'eu-west-1' / 'cold-233107.json', day / 'eu-west-1')
    with pytest.raises(SystemExit):
        validate.main(day)


def test_another_clients_run_starting_during_a_cold_pass_fails(day: Path) -> None:
    # The us-east-1 pass ran 22:54:25 to 22:54:59.
    edit(day / 'eu-west-1' / 'near-231138.json', lambda d: d.update(started='2026-10-07T22:54:40+00:00'))
    with pytest.raises(SystemExit):
        validate.main(day)


def test_a_load_row_is_rated_over_at_least_the_window() -> None:
    run = {
        'load_seconds': 15,
        'load_c50': {
            'early': {'seconds': 10.0, 'successful_requests': 1500, 'throughput_rps': 150.0},
            'full': {'seconds': 15.4, 'successful_requests': 1540, 'throughput_rps': 100.0},
            'failed': {'error': 'ConnectionError'},
        },
    }
    aggregate.correct_load_window(run)
    assert run['load_c50']['early'] == {'seconds': 15, 'successful_requests': 1500, 'throughput_rps': 100.0}
    assert run['load_c50']['full']['throughput_rps'] == 100.0


def test_aggregate_drops_cold_rows_that_share_a_deployment_and_reproduces_the_committed_file(day: Path) -> None:
    region = day / 'us-east-1'
    committed = json.loads((region / 'aggregate.json').read_text())
    aggregate.main(region)
    rebuilt = json.loads((region / 'aggregate.json').read_text())
    assert not set(aggregate.SHARES_DEPLOYMENT_WITH) & set(rebuilt['cold'])
    assert rebuilt == committed
