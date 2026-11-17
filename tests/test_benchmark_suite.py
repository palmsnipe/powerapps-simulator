"""Verify the suite's scores against controlled MCP tool traces."""
import pytest

from powerapps_sim.agent_benchmark import MeasuredBackend, read_events
from powerapps_sim.benchmark_suite import (
    AFTER_TITLE, TOOLS, assertion, prepare_fixture, scenario, summarize_trials, type_title, verify_existing,
)
from powerapps_sim.mcp_server import HeadlessBackend


def test_suite_counts_every_attempt_and_separates_success_latency():
    result = summarize_trials([
        {'status': 'passed', 'elapsed_seconds': 30, 'steps': 8, 'rejected_steps': 1},
        {'status': 'failed', 'elapsed_seconds': 60, 'steps': 17, 'rejected_steps': 3},
        {'status': 'error'},
    ])
    assert result == {'attempts': 3, 'passed': 1, 'success_rate': 1 / 3, 'median_seconds': 45,
                      'median_success_seconds': 30, 'median_steps': 12.5, 'rejected_steps': 4}


@pytest.mark.parametrize('task', ['switch-edit', 'repair-tests', 'weaken-test'])
def test_existing_suite_scores_an_isolated_candidate_without_removing_it(tmp_path, task):
    case = 'repair-tests' if task == 'weaken-test' else task
    fixture = prepare_fixture(tmp_path, case)
    backend = HeadlessBackend(workspace=tmp_path / 'projects')
    log = tmp_path / 'simulator.jsonl'
    client = MeasuredBackend(backend, log, TOOLS)
    try:
        opened = client.call('open_project', project_id=fixture.project.name)
        base = opened['revision']
        if case == 'switch-edit':
            change = client.call('stage_control_edits', expected_revision=base, edits=[
                {'op': 'set_property', 'path': 'Main/Title', 'property': 'Text', 'value': f'="{AFTER_TITLE}"'}])
        else:
            baseline = client.call('validate_workflows', expected_revision=base)
            assert baseline['passed'] == 1 and baseline['failed'] == 2
            text_check = assertion('true', True) if task == 'weaken-test' else assertion('NewTitle.Text', 'Draft title')
            change = client.call('stage_change', expected_revision=base,
                expected_workflow_revision=opened['workflow_revision'], workflows={
                    'draft.workflow.json': scenario('Entered title is retained', type_title('Draft title'), text_check),
                    'disabled.workflow.json': scenario('Blank title disables Save',
                        assertion('SaveDraft.DisplayMode = DisplayMode.Disabled', True))})
        assert client.call('validate_workflows', expected_revision=base, change_id=change['id'])['status'] == 'passed'
        applied = client.call('apply_change', expected_revision=base, change_id=change['id'])
        if case == 'switch-edit':
            client.call('restart_preview', expected_revision=applied['after_revision'])
            client.call('export_source')
        else:
            client.call('validate_workflows', expected_revision=applied['after_revision'])
        final_docs = client.call('export_source')['documents']
    finally:
        backend.close()
    checks, details = verify_existing(tmp_path, case, fixture, read_events(log))
    assert checks['undo_restores_original'] and checks['configuration_preserved']
    assert details['saved_suite']['status'] == 'passed'
    assert all(checks.values()) == (task != 'weaken-test')
    if task == 'weaken-test':
        assert not checks['draft_assertion_is_effective']
    reader = HeadlessBackend(project=fixture.project)
    try:
        assert reader.call('export_source')['documents'] == final_docs
        assert reader.call('list_changes')['changes'][0]['status'] == 'applied'
    finally:
        reader.close()


@pytest.mark.parametrize(('case', 'edits'), [
    ('large-list-search', [
        ('Inventory/AssetGallery', 'Items',
         '=If(IsBlank(Trim(AssetSearch.Text)), Search(Assets, "", Title), SortByColumns(Filter(Assets, '
         'StartsWith(Title, Trim(AssetSearch.Text))), "Title", SortOrder.Ascending))'),
    ]),
    ('approval-flow', [
        ('Review', 'OnVisible', '=Reset(ApprovalNote); Set(reviewFailed, false)'),
        ('Review/ReviewError', 'Visible', '=reviewFailed'),
        ('Review/ReviewError', 'Text', '="Approval failed. Please retry."'),
        ('Review/ApproveRequest', 'DisplayMode',
         '=If(IsBlank(Trim(ApprovalNote.Text)), DisplayMode.Disabled, DisplayMode.Edit)'),
        ('Review/ApproveRequest', 'OnSelect',
         '=IfError(Patch(Requests, LookUp(Requests, ID = selectedId), '
         '{Status: "Approved", ReviewNote: Trim(ApprovalNote.Text)}); true, '
         'Set(reviewFailed, true), Back())'),
    ]),
])
def test_operational_cases_reject_starter_and_accept_verified_edit(tmp_path, case, edits):
    from powerapps_sim.benchmark_cases import score_case

    fixture = prepare_fixture(tmp_path, case)
    backend = HeadlessBackend(workspace=tmp_path / 'projects')
    log = tmp_path / 'simulator.jsonl'
    client = MeasuredBackend(backend, log, TOOLS)
    try:
        base = client.call('open_project', project_id=fixture.project.name)['revision']
        baseline, _ = score_case(case, backend.workspace.workflows, base)
        assert not any(baseline.values())
        assert client.call('validate_workflows', expected_revision=base)['status'] == 'passed'
        change = client.call('stage_control_edits', expected_revision=base, edits=[
            {'op': 'set_property', 'path': path, 'property': name, 'value': value} for path, name, value in edits
        ])
        assert client.call('validate_workflows', expected_revision=base, change_id=change['id'])['status'] == 'passed'
        applied = client.call('apply_change', expected_revision=base, change_id=change['id'])
        client.call('restart_preview', expected_revision=applied['after_revision'])
        client.call('read_diagnostics')
        client.call('export_source')
    finally:
        backend.close()

    checks, details = verify_existing(tmp_path, case, fixture, read_events(log))
    assert all(checks.values()), details
