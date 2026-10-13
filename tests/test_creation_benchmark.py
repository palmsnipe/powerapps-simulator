"""Verify scratch-trial isolation, native telemetry and phase scoring without model usage."""
from copy import deepcopy
import json
import pytest

from powerapps_sim.agent_benchmark import MeasuredBackend, codex_command, read_events
from powerapps_sim.creation_benchmark import SEEDS, TOOLS, acceptance_workflows, phase_evidence, trial_prompt, verify_trial
from powerapps_sim.mcp_server import HeadlessBackend
from powerapps_sim.workflows import validate


def test_prompt_requires_ai_authored_creation_then_edits_without_reference_source():
    prompt = trial_prompt()
    assert 'create_project' in prompt and 'initially empty' in prompt
    assert 'at least THREE' in prompt and 'Phase 2' in prompt and 'staged edits' in prompt
    assert 'Screens:' not in prompt and 'Children:' not in prompt and '=Patch(' not in prompt
    assert 'Do not use shell' in prompt
    workflows = acceptance_workflows()
    assert len(workflows) == 4
    assert all(validate(s) == s for s in workflows)
    assert all('records' not in s for s in workflows)  # Score real seeds, not replacement fixture rows.


def phase_calls():
    def call(operation, arguments=None, result=None):
        return {'operation': operation, 'status': 'completed', 'arguments': arguments or {}, 'result': result or {}}
    files = {'add.workflow.json': {}, 'toggle.workflow.json': {}, 'retry.workflow.json': {}}
    workflows = [{'scenario_file': f} for f in files]
    return [call('describe_project'), call('create_project', {'sources': {'Src/App.yaml': 'AI authored source'}, 'workflows': files}),
            call('run_workflows', {'workflows': workflows}, {'status': 'passed'}),
            call('stage_control_edits', {}, {'id': 'candidate'}),
            call('run_workflows', {'change_id': 'candidate', 'workflows': workflows}, {'status': 'passed'}),
            call('apply_change', {'change_id': 'candidate'}), call('restart_preview'), call('export_source')]


def test_phase_scoring_requires_creation_baseline_tests_candidate_tests_apply_restart_export():
    calls = phase_calls()
    assert phase_evidence(calls)['passed']
    for index in (1, 2, 3, 4, 5, 6, 7):
        missing = deepcopy(calls)
        missing[index]['status'] = 'failed'
        assert not phase_evidence(missing)['passed'], index
    prematurely_filtered = deepcopy(calls)
    prematurely_filtered[1]['arguments']['sources']['Src/App.yaml'] = 'StatusFilter'
    assert not phase_evidence(prematurely_filtered)['passed']
    assert not phase_evidence(calls + [calls[1]])['passed']
    no_candidate = deepcopy(calls)
    no_candidate[4]['arguments'].pop('change_id')
    assert not phase_evidence(no_candidate)['passed']


def test_no_created_app_fails_scoring_without_creating_fixture(tmp_path):
    assert not verify_trial(tmp_path, [])['passed']
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('id_metadata', [{'x-ms-permission': 'read-only'}, {'readOnly': True}, {}])
def test_independent_scorer_rejects_a_scaffold_and_preserves_the_retained_app(tmp_path, id_metadata):
    backend = HeadlessBackend(workspace=tmp_path / 'projects')
    measured = MeasuredBackend(backend, tmp_path / 'calls.jsonl', TOOLS)
    try:
        measured.call('create_project', name='task-desk', lists={'Tasks': {
            'fields': {'ID': {'type': 'integer', **id_metadata},
                       'Title': {'type': 'string'}, 'Done': {'type': 'boolean'}}, 'required': ['Title']}},
            records={'Tasks': SEEDS}, workflows={'smoke.workflow.json': {
                'format_version': 1, 'name': 'Smoke', 'steps': [{'op': 'diagnostics', 'expect': 0}]}})
        exported = measured.call('export_source')
    finally:
        backend.close()
    calls = read_events(tmp_path / 'calls.jsonl')
    result = verify_trial(tmp_path, calls)
    assert not result['passed'] and not result['undo_verified']
    assert result['schema_verified'] and result['schemas_unchanged'] and result['records_preserved']
    assert result['id_readonly_verified']
    assert result['export_verified'] and result['saved_workflows_unchanged']
    assert any(r['status'] == 'failed' for r in result['acceptance'])
    reader = HeadlessBackend(tmp_path / 'projects/task-desk')
    try:
        assert reader.call('export_source')['documents'] == exported['documents']
        assert reader.call('read_list', name='Tasks')['rows'] == SEEDS
    finally:
        reader.close()


def test_creation_command_uses_empty_workspace_and_only_the_disposable_server(tmp_path, monkeypatch):
    config = tmp_path / 'config'
    config.mkdir()
    (config / 'config.toml').write_text('model="configured-model"\n[mcp_servers.unrelated]\ncommand="unused"\n')
    monkeypatch.setenv('CODEX_HOME', str(config))
    monkeypatch.setattr('subprocess.check_output', lambda *a, **kw: 'codex-cli test\n')
    command, metadata = codex_command(tmp_path, 'from_scratch', 'codex', workspace=True,
                                     server_module='powerapps_sim.creation_benchmark')
    assert metadata['model'] == 'configured-model'
    assert 'mcp_servers.unrelated.enabled=false' in command
    server = next(v for v in command if v.startswith('mcp_servers.simulator='))
    assert 'creation_benchmark' in server and '--workspace' in server and '--project' not in server
    assert json.dumps(str(tmp_path / 'projects')) in server
    assert 'default_tools_approval_mode="approve"' in server
    assert 'shell_tool' in command and 'web_search="disabled"' in command
