"""Focused authoring, isolated batch evidence and explicit preview lifecycle."""
from copy import deepcopy

import pytest

from powerapps_sim.application import Workspace
from powerapps_sim.authoring import RevisionConflict, data_revision, revision
from powerapps_sim.fixtures import ai_development_project, forms_project
from powerapps_sim.source import Project


@pytest.fixture
def workspace(tmp_path):
    p = ai_development_project(tmp_path / 'app')
    w = Workspace(tmp_path, p.root)
    yield w
    w.runtime.close()


def call(w, operation, **args):
    return w.ai.call(operation, args, expected_project=str(w.project.root))


def candidate(w):
    task = w.project.read_json('benchmark.task.json', {})
    return call(w, 'stage_control_edits', expected_revision=revision(w.project.root),
                edits=task['reference_edits'], strict=True)


def test_focused_reads_are_paged_saved_source_and_do_not_fetch_rows_or_run_events(workspace, monkeypatch):
    w = workspace
    w.runtime.event_queue.append((w.runtime.global_refs['SaveProject'], 'OnSelect', ()))
    before = deepcopy(w.runtime.control_state)
    found = call(w, 'read_controls', query='Projects', limit=1)
    assert found['total'] >= 2 and found['next_offset'] == 1
    assert 'properties' not in found['controls'][0]
    second = call(w, 'read_controls', query='Projects', offset=1, limit=1, include_properties=True)
    assert found['controls'][0]['path'] != second['controls'][0]['path']
    form = call(w, 'read_control', path='Workspace/ProjectForm')
    assert form['definition']['Properties']['DataSource'] == '=Projects'
    assert form['contract']['supported'] and 'Unsaved' in form['contract']['outputs']
    assert form['property_lines']['OnFailure'] > form['line']
    assert 'Children' not in form['definition']
    monkeypatch.setattr(w.runtime.store, 'rows', lambda *args: pytest.fail('Schema discovery fetched records'))
    schema = call(w, 'read_list_schema', name='Projects')
    assert schema['definition']['required'] == ['Title', 'Status', 'Amount']
    schema['definition']['required'].clear()
    assert w.runtime.store.definitions['Projects']['required']
    assert w.runtime.control_state == before and len(w.runtime.event_queue) == 1


def test_targeted_candidate_is_isolated_applies_restarts_and_undoes(workspace):
    w = workspace
    base, data = revision(w.project.root), data_revision(w.runtime.store)
    original = dict(w.project.documents)
    w.runtime.state()
    w.runtime.event('Workspace/ProjectForm/TitleCard/TitleInput', 'OnChange', 'Live unsaved edit')
    live = call(w, 'read_runtime')
    change = candidate(w)
    assert change['status'] == 'staged' and change['changed_sources'] == ['Src/ai-development.pa.yaml']
    assert 'sources' not in change and 'lists' not in change and change['diffs']
    catalog = call(w, 'list_workflows')
    reports = call(w, 'run_workflows', expected_revision=base, change_id=change['id'],
                   workflows=[{'scenario_file': e['file']} for e in catalog['scenarios']])
    assert reports['passed'] == 4 and reports['failed'] == 0
    assert call(w, 'read_runtime') == live and data_revision(w.runtime.store) == data
    assert Project(w.project.root).documents == original
    for report in reports['runs']:
        assert 'trace' not in report and not report['failures'] and not report['diagnostics']
        complete = call(w, 'read_workflow_report', run_id=report['id'])
        assert complete['trace'] and len(complete['steps']) == report['steps_passed']
    applied = call(w, 'apply_change', change_id=change['id'], expected_revision=base)
    assert w.runtime.pending_source
    # Discovery reads saved edits while evaluation still uses the old runtime.
    assert call(w, 'read_control', path='Workspace/StatusFilter')['definition']['Properties']['Default'] == '="All"'
    assert call(w, 'read_runtime')['running_source']['source_matches_saved'] is False
    restarted = call(w, 'restart_preview', expected_revision=applied['after_revision'])
    assert restarted['started'] and not restarted['pending_source'] and restarted['running_source']['source_matches_saved']
    w.runtime.state()
    assert w.runtime.global_refs['TitleInput'].property('Text') == 'Bridge study'
    assert not w.runtime.diagnostics
    call(w, 'undo_change', change_id=change['id'], expected_revision=applied['after_revision'])
    assert Project(w.project.root).documents == original and data_revision(w.runtime.store) == data
    assert revision(w.project.root) == base


def test_batch_reports_independent_failures_and_locations(workspace):
    w = workspace
    base = revision(w.project.root)
    report = call(w, 'run_workflows', expected_revision=base, workflows=[
        {'scenario': {'format_version': 1, 'name': 'Missing control', 'steps': [
            {'op': 'event', 'path': 'Workspace/Missing', 'event': 'OnSelect'},
            {'op': 'assert', 'formula': 'true'}]}},
        {'scenario': {'format_version': 1, 'name': 'Independent fresh app', 'steps': [
            {'op': 'assert', 'formula': 'selectedId', 'expect': 1}]}}])
    assert report['status'] == 'failed' and report['failed'] == report['passed'] == 1
    failed = report['runs'][0]
    assert failed['steps_skipped'] == 1 and failed['failures'][0]['path'] == 'Workspace/Missing'
    assert 'Control path' in failed['failures'][0]['error']


def test_batch_checks_all_definitions_before_running(workspace):
    w = workspace
    with pytest.raises(ValueError):
        call(w, 'run_workflows', expected_revision=revision(w.project.root), workflows=[
            {'scenario_file': 'required-title.workflow.json'}, {'scenario': {}}])
    assert not (w.project.root / '.emu/runs').exists()


def test_compact_workflow_catalog_preserves_invalid_entries(workspace):
    w = workspace
    (w.project.root / 'tests/broken.workflow.json').write_text('{}')
    catalog = call(w, 'list_workflows', include_scenarios=False)
    assert len(catalog['scenarios']) == 5
    valid = [e for e in catalog['scenarios'] if 'error' not in e]
    assert len(valid) == 4 and all('scenario' not in e and e['step_count'] > 0 and e['name'] for e in valid)
    with pytest.raises(ValueError):
        call(w, 'list_workflows', include_scenarios='false')


@pytest.mark.parametrize('operation,args', [
    ('read_controls', {'limit': True}), ('read_controls', {'offset': -1}),
    ('read_controls', {'include_properties': 'yes'}), ('read_controls', {'source': '../outside'}),
    ('read_controls', {'query': []}), ('read_control', {'path': 'Missing'}),
    ('read_control', {'path': 'Workspace', 'source': []}),
    ('read_list_schema', {'name': ['Projects']}),
    ('stage_control_edits', {'edits': []}),
    ('stage_control_edits', {'edits': [{'op': 'set_property', 'path': 'Workspace/Heading', 'property': 'Text', 'value': 'not a formula'}]}),
    ('stage_control_edits', {'edits': [{'op': 'set_property', 'path': 'Workspace/Heading', 'property': 'Text', 'value': '=1', 'typo': 1}]}),
    ('stage_control_edits', {'edits': [{'op': 'remove_property', 'path': 'Workspace/Heading', 'property': 'Missing'}]}),
    ('stage_control_edits', {'edits': [{'op': 'add_control', 'parent': 'Workspace', 'name': 'Heading', 'control': {'Control': 'ModernText@1.0.0'}}]}),
    ('stage_control_edits', {'edits': [{'op': 'add_control', 'parent': 'Workspace', 'name': 'New', 'index': True, 'control': {'Control': 'ModernText@1.0.0'}}]}),
    ('run_workflows', {'workflows': []}),
    ('run_workflows', {'workflows': [{'scenario_file': 'missing'}]}),
    ('run_workflows', {'workflows': [{'scenario_file': 'required-title.workflow.json', 'scenario': {}}]}),
])
def test_invalid_arguments_preserve_source_data_and_change_history(workspace, operation, args):
    w = workspace
    base, data = revision(w.project.root), data_revision(w.runtime.store)
    if operation in ('stage_control_edits', 'run_workflows'):
        args = {'expected_revision': base, **args}
    with pytest.raises(ValueError):
        call(w, operation, **args)
    assert revision(w.project.root) == base and data_revision(w.runtime.store) == data
    assert not w.authoring.history()


@pytest.mark.parametrize('operation,args', [
    ('stage_control_edits', {'edits': [{'op': 'set_property', 'path': 'Workspace/Heading', 'property': 'Text', 'value': '="Changed"'}]}),
    ('run_workflows', {'workflows': [{'scenario_file': 'required-title.workflow.json'}]}),
    ('restart_preview', {})])
def test_new_writes_require_identity_and_reject_stale_revisions_before_effects(workspace, operation, args):
    w = workspace
    old_runtime = w.runtime
    with pytest.raises(ValueError, match='expected_project'):
        w.ai.call(operation, {'expected_revision': revision(w.project.root), **args})
    with pytest.raises(RevisionConflict):
        call(w, operation, expected_revision='stale', **args)
    assert w.runtime is old_runtime and not w.authoring.history()
    assert not (w.project.root / '.emu/runs').exists()


def test_edits_keep_comments_multiline_formulas_versions_and_unedited_documents(tmp_path):
    p = forms_project(tmp_path / 'forms')
    source = p.root / 'Src/forms.pa.yaml'
    source.write_text('# Preserve this comment\n' + source.read_text())
    extra = p.root / 'Src/other.pa.yaml'
    other = 'Screens:\n  Other:  # untouched spacing\n    Children: []\n'
    extra.write_text(other)
    w = Workspace(tmp_path, p.root)
    try:
        change = call(w, 'stage_control_edits', expected_revision=revision(p.root), edits=[
            {'op': 'set_property', 'path': 'Forms/Heading', 'property': 'Text', 'value': '=With(\n {caption: "New title"},\n caption\n)'},
            {'op': 'remove_property', 'path': 'Forms/Heading', 'property': 'Size'}], strict=True)
        assert change['changed_sources'] == ['Src/forms.pa.yaml']
        call(w, 'apply_change', change_id=change['id'], expected_revision=change['base_revision'])
        assert source.read_text().startswith('# Preserve this comment\n') and extra.read_text() == other
        c = call(w, 'read_control', path='Forms/Heading')
        assert c['kind'] == 'ModernText@1.0.0' and 'Size' not in c['definition']['Properties']
        assert c['definition']['Properties']['Text'] == '=With(\n {caption: "New title"},\n caption\n)'
    finally:
        w.runtime.close()


def test_add_nested_controls_then_edit_new_child_in_same_candidate(workspace):
    w = workspace
    change = call(w, 'stage_control_edits', expected_revision=revision(w.project.root), edits=[
        {'op': 'add_control', 'parent': 'Workspace', 'name': 'Panel', 'control': {
            'Control': 'GroupContainer@1.5.0', 'Children': [{'Caption': {
                'Control': 'ModernText@1.0.0', 'Properties': {'Text': '="Original"'}}}]}},
        {'op': 'set_property', 'path': 'Workspace/Panel/Caption', 'property': 'Text', 'value': '="Updated"'}], strict=True)
    call(w, 'apply_change', change_id=change['id'], expected_revision=change['base_revision'])
    assert call(w, 'read_control', path='Workspace/Panel/Caption')['definition']['Properties']['Text'] == '="Updated"'


def test_combined_control_and_schema_candidate_uses_new_field(workspace):
    w = workspace
    schema = call(w, 'read_list_schema', name='Projects')['definition']
    schema['fields']['Priority'] = {'type': 'string', 'default': 'Normal'}
    schema['mapping']['Priority'] = 'Priority'
    change = call(w, 'stage_control_edits', expected_revision=revision(w.project.root), lists={'Projects': schema},
        edits=[{'op': 'set_property', 'path': 'Workspace/Heading', 'property': 'Text', 'value': '=First(Projects).Priority'}], strict=True)
    assert change['changed_lists'] == ['Projects'] and not change['diagnostics']
    report = call(w, 'run_workflows', expected_revision=change['base_revision'], change_id=change['id'], workflows=[
        {'scenario': {'format_version': 1, 'name': 'New schema', 'steps': [{'op': 'assert', 'formula': 'Heading.Text', 'expect': 'Normal'}]}}])
    assert report['status'] == 'passed' and 'Priority' not in w.runtime.store.definitions['Projects']['fields']


def test_headless_explicit_restart_runs_startup_and_retains_exclusive_lease(tmp_path):
    from powerapps_sim.mcp_server import HeadlessBackend
    p = ai_development_project(tmp_path / 'app')
    backend = HeadlessBackend(p.root)
    try:
        assert not backend.call('describe_project')['runtime_started']
        result = backend.call('restart_preview', expected_revision=revision(p.root))
        assert result['started'] and backend.call('read_runtime')['globals']['selectedId'] == 1
        with pytest.raises(ValueError, match='workspace'):
            HeadlessBackend(p.root)
    finally:
        backend.close()


@pytest.mark.parametrize('source', [
    '- Caption:\n    Control: ModernText@1.0.0\n    Properties:\n      Text: ="Before"\n',
    'Control: ModernText@1.0.0\nName: Caption\nProperties:\n  Text: ="Before"\n',
    'Caption:\n  Control: ModernText@1.0.0\n  Properties:\n    Text: ="Before"\n'])
def test_targeted_edits_preserve_clipboard_document_shape(tmp_path, source):
    from powerapps_sim.source import yaml_engine
    p = Project.import_yaml(source, tmp_path / 'clipboard')
    w = Workspace(tmp_path, p.root)
    try:
        change = call(w, 'stage_control_edits', expected_revision=revision(p.root), edits=[
            {'op': 'set_property', 'path': 'Scratch/Caption', 'property': 'Text', 'value': '="After"'}], strict=True)
        call(w, 'apply_change', change_id=change['id'], expected_revision=change['base_revision'])
        saved = next(iter(Project(p.root).documents.values()))
        before, after = yaml_engine().load(source), yaml_engine().load(saved)
        assert isinstance(after, type(before))
        if isinstance(before, dict):
            assert after.keys() == before.keys()
        assert call(w, 'read_control', path='Scratch/Caption')['definition']['Properties']['Text'] == '="After"'
    finally:
        w.runtime.close()


def test_ambiguous_saved_paths_need_a_source_selector(tmp_path):
    p = Project.import_yaml('Caption:\n  Control: ModernText@1.0.0\n  Properties:\n    Text: ="One"\n',
                            tmp_path / 'app', 'one.pa.yaml')
    (p.root / 'Src/two.pa.yaml').write_text('Caption:\n  Control: ModernText@1.0.0\n  Properties:\n    Text: ="Two"\n')
    w = Workspace(tmp_path, p.root)
    try:
        with pytest.raises(ValueError, match='ambiguous'):
            call(w, 'read_control', path='Scratch/Caption')
        inspected = call(w, 'read_control', path='Scratch/Caption', source='Src/two.pa.yaml')
        assert inspected['definition']['Properties']['Text'] == '="Two"'
        change = call(w, 'stage_control_edits', expected_revision=revision(p.root), edits=[
            {'op': 'set_property', 'path': 'Scratch/Caption', 'source': 'Src/two.pa.yaml', 'property': 'Text', 'value': '="Changed"'}])
        assert change['changed_sources'] == ['Src/two.pa.yaml']
    finally:
        w.runtime.close()


def test_restart_source_error_preflight_keeps_live_state(workspace):
    w = workspace
    old_runtime = w.runtime
    before = call(w, 'read_runtime')
    (w.project.root / 'Src/ai-development.pa.yaml').write_text('Screens: [invalid\n')
    with pytest.raises(ValueError, match='Saved source has errors'):
        call(w, 'restart_preview', expected_revision=revision(w.project.root))
    assert w.runtime is old_runtime
    # The saved/running revision note correctly changes, but the live app stays intact.
    after = call(w, 'read_runtime')
    before.pop('running_source'); after.pop('running_source')
    assert after == before


def test_focused_authoring_and_restart_through_shared_http_dispatcher(app, post):
    w = app.extensions['workspace']
    project_id = str(w.project.root)
    def http(operation, **args):
        result = post('/api/ai/' + operation, {'expected_project': project_id, 'arguments': args})
        assert result.status_code == 200, result.json
        return result.json
    base = http('describe_project')['revision']
    discovery = http('read_controls', query='ProjectGallery')
    path = next(c['path'] for c in discovery['controls'] if c['name'] == 'ProjectGallery')
    assert http('read_control', path=path)['contract']['supported']
    assert http('read_list_schema', name='Projects')['definition']['fields']
    change = http('stage_control_edits', expected_revision=base, edits=[
        {'op': 'set_property', 'path': path, 'property': 'Visible', 'value': '=false'}], strict=True)
    report = http('run_workflows', expected_revision=base, change_id=change['id'], workflows=[
        {'scenario': {'format_version': 1, 'name': 'Hidden candidate', 'steps': [
            {'op': 'assert', 'formula': 'ProjectGallery.Visible', 'expect': False}]}}])
    assert report['status'] == 'passed'
    applied = http('apply_change', expected_revision=base, change_id=change['id'])
    restarted = http('restart_preview', expected_revision=applied['after_revision'])
    assert restarted['running_source']['source_matches_saved']
    assert http('evaluate_formula', formula='ProjectGallery.Visible')['value'] is False
    stale = post('/api/ai/restart_preview', {'expected_project': project_id, 'arguments': {'expected_revision': base}})
    assert stale.status_code == 409


def test_reference_benchmark_measures_real_payloads_and_verifies_lifecycle():
    from powerapps_sim.benchmark import run_benchmark
    result = run_benchmark()
    assert result['status'] == 'passed'
    for mode in result['results']:
        assert all(r['status'] == 'passed' for r in mode['candidate'])
        assert any(r['status'] == 'failed' for r in mode['baseline'])
        assert mode['undo_verified'] and mode['preview_verified']
        assert mode['model_tokens'] is mode['manual_interventions'] is None
        assert mode['request_bytes'] == sum(c['request_bytes'] for c in mode['calls'])
    assert result['comparison']['request_bytes_saved'] > 0 and result['comparison']['response_bytes_saved'] > 0
