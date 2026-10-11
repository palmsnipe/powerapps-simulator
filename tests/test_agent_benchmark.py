"""Integrity checks for live-agent telemetry and independent benchmark scoring."""
import json

import pytest

from powerapps_sim.agent_benchmark import MeasuredBackend, client_metrics, prepare_trial, trial_prompt, verify_trial
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision
from powerapps_sim.fixtures import ai_development_project


def test_client_usage_is_native_and_completed_items_are_counted_once():
    item = {'id': 'call1', 'type': 'mcp_tool_call', 'server': 'simulator', 'tool': 'read_source'}
    events = [{'type': 'item.started', 'item': item},
              {'type': 'item.completed', 'item': item},
              {'type': 'item.completed', 'item': item},
              {'type': 'turn.completed', 'usage': {'input_tokens': 200, 'cached_input_tokens': 150, 'output_tokens': 20}},
              {'type': 'turn.completed', 'usage': {'input_tokens': 50, 'cached_input_tokens': 0, 'output_tokens': 5}}]
    result = client_metrics(events)
    assert result['mcp_tool_calls'] == 1
    assert result['usage'] == {'input_tokens': 250, 'cached_input_tokens': 150, 'output_tokens': 25, 'total_tokens': 275}
    assert not result['other_mcp_servers']
    assert client_metrics(events[:3])['usage'] is None


def test_client_metrics_expose_non_simulator_activity_and_errors():
    result = client_metrics([
        {'type': 'item.completed', 'item': {'id': 'a', 'type': 'mcp_tool_call', 'server': 'other'}},
        {'type': 'item.completed', 'item': {'id': 'b', 'type': 'command_execution'}},
        {'type': 'item.completed', 'item': {'id': 'c', 'type': 'file_change'}},
        {'type': 'turn.failed', 'error': {'message': 'Failed'}}])
    assert result['other_mcp_servers'] == ['other']
    assert result['shell_calls'] == result['file_changes'] == 1
    assert result['errors'] and result['usage'] is None


def test_trial_removes_reference_and_baseline_exposes_unfinished_feature(tmp_path):
    project, task, original, data, baseline = prepare_trial(tmp_path)
    assert 'reference_edits' not in task
    assert 'reference_edits' not in (project.root / 'benchmark.task.json').read_text()
    assert any(r['status'] == 'failed' for r in baseline)
    assert any(r['status'] == 'passed' for r in baseline)  # Existing required-title validation works.
    for mode in ('full_document', 'focused'):
        prompt = trial_prompt(task, mode)
        assert task['request'] in prompt
        assert 'Notify(Self.Error' not in prompt and 'ModernDropdown' not in prompt
    result = verify_trial(tmp_path, original, data)
    assert not result['passed'] and result['applied_changes'] == 0


def test_service_audit_includes_failed_and_unavailable_calls(tmp_path):
    class Backend:
        project = '/fictional/project'
        def call(self, operation, **arguments):
            if operation == 'fail':
                raise ValueError('Rejected edit')
            return {'ok': True}
    log = tmp_path / 'calls.jsonl'
    measured = MeasuredBackend(Backend(), log, {'read', 'fail'})
    assert measured.call('read', query='x') == {'ok': True}
    with pytest.raises(ValueError, match='Rejected edit'):
        measured.call('fail')
    with pytest.raises(ValueError, match='unavailable'):
        measured.call('outside_mode')
    entries = [json.loads(line) for line in log.read_text().splitlines()]
    assert [e['status'] for e in entries] == ['completed', 'failed', 'failed']
    assert all(e['request_bytes'] > 0 and e['response_bytes'] > 0 for e in entries)


def test_independent_verifier_scores_source_and_records_and_undoes(tmp_path):
    # A reference candidate tests the scorer, never the real model's generation.
    reference = ai_development_project(tmp_path / 'reference').read_json('benchmark.task.json', {})['reference_edits']
    root = tmp_path / 'trial'
    project, task, original, data, baseline = prepare_trial(root)
    workspace = Workspace(root, project.root)
    try:
        base = revision(project.root)
        change = workspace.ai.call('stage_control_edits', {'expected_revision': base, 'edits': reference},
                                   expected_project=str(project.root))
        workspace.ai.call('apply_change', {'expected_revision': base, 'change_id': change['id']},
                          expected_project=str(project.root))
    finally:
        workspace.runtime.close()
    result = verify_trial(root, original, data)
    assert result['passed'] and result['undo_verified']
    assert all(r['status'] == 'passed' for r in result['acceptance'])
    assert all(all(g['controls_fit'].values()) for g in result['geometry'])
