"""Check that comparisons preserve attempt evidence and keep runs comparable."""
import csv
from copy import deepcopy
from io import StringIO
import json

import pytest

from powerapps_sim.benchmark_report import comparison_rows, conditions, csv_text, markdown_text, read_runs


def write_run(root, report):
    root.mkdir()
    (root / 'report.json').write_text(json.dumps(report), encoding='utf-8')
    return root


def test_combine_runs_with_same_settings_without_double_counting(tmp_path):
    report = {
        'format_version': 1, 'suite_version': 2, 'run_id': 'run-1', 'started_at': '2026-11-17T22:00:00+00:00',
        'settings': {'model': 'terra', 'repeats': 2, 'timeout': 300, 'reasoning_effort': 'high',
                     'service_tier': 'priority', 'skill_sha256': 'abcdef1234567890'},
        'cases': {'large-list-search': {}},
        'trials': [
            {'case': 'large-list-search', 'repeat': 1, 'status': 'passed', 'elapsed_seconds': 20, 'steps': 10,
             'client': {'codex_version': 'codex-cli test'}, 'checks': {'scored': True}},
            {'case': 'large-list-search', 'repeat': 2, 'status': 'error', 'error': '=1+1'},
        ],
    }
    terra = write_run(tmp_path / 'terra', report)
    duplicate = write_run(tmp_path / 'duplicate', report)
    second = deepcopy(report)
    second['run_id'] = 'run-2'
    second['settings']['model'] = 'luna'
    second['trials'] = [dict(second['trials'][0], status='failed', elapsed_seconds=40, steps=17,
                            checks={'scored': False}, client_metrics={'usage': {'input_tokens': 100, 'output_tokens': 20}})]
    luna = write_run(tmp_path / 'luna', second)
    older = deepcopy(second)
    older['suite_version'] = 1
    del older['run_id'], older['started_at']
    legacy = write_run(tmp_path / 'luna-20261117T220000Z', older)

    runs = read_runs([terra, duplicate / 'report.json', luna, legacy])
    groups = conditions(runs)
    assert len(runs) == 3 and len(groups) == 2
    overall = dict(comparison_rows(groups[0][1]))
    assert overall['terra']['success_rate'] == 0.5
    assert overall['terra']['median_success_seconds'] == 20
    assert overall['luna']['median_seconds'] == 40
    assert overall['luna']['median_success_seconds'] is None
    comparison = markdown_text(groups)
    assert '1 pending attempt.' in comparison
    assert 'luna · large-list-search · scored (1)' in comparison

    attempts = list(csv.DictReader(StringIO(csv_text(runs))))
    assert len(attempts) == 4
    assert {row['input_tokens'] for row in attempts} == {'100', ''}
    assert {row['failed_checks'] for row in attempts} == {'scored', ''}
    error = next(row for row in attempts if row['status'] == 'error')
    assert error['error'] == "'=1+1" and error['elapsed_seconds'] == ''
    assert [row['started_at'] for row in attempts if row['suite_version'] == '1'] == ['2026-11-17T22:00:00+00:00']

    second['run_id'] = 'run-1'
    conflicting = write_run(tmp_path / 'conflict', second)
    with pytest.raises(ValueError, match='share a run ID'):
        read_runs([terra, conflicting])
