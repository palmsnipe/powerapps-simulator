"""App scaffolding, atomic validation, project binding and isolated acceptance."""
from copy import deepcopy

import pytest

from powerapps_sim.application import Workspace
from powerapps_sim.authoring import RevisionConflict, data_revision, revision
from powerapps_sim.fixtures import forms_project
from powerapps_sim.mcp_server import HeadlessBackend
from powerapps_sim.source import Project
from powerapps_sim.syntax import FxError


SOURCE = '''# Authored from scratch
App:
  Properties:
    StartScreen: =Home
    OnStart: =Set(startups, 1)
Screens:
  Home:
    Children:
      - Count:
          Control: ModernText@1.0.0
          Properties:
            Text: =Text(CountRows(Projects))
      - Add:
          Control: ModernButton@1.0.0
          Properties:
            Text: ="Add project"
            OnSelect: =Patch(Projects, Defaults(Projects), {Title:"Added", Amount:5})
'''
SCHEMA = {'fields': {'ID': {'type': 'integer', 'x-ms-permission': 'read-only'},
                      'Title': {'type': 'string', 'maxLength': 80}, 'Amount': {'type': 'number', 'minimum': 0}},
          'required': ['Title']}
SCENARIO = {'format_version': 1, 'name': 'Create a project', 'steps': [
    {'op': 'assert', 'formula': 'startups', 'expect': 1},
    {'op': 'assert', 'formula': 'CountRows(Projects)', 'expect': 2},
    {'op': 'event', 'path': 'Home/Add', 'event': 'OnSelect'},
    {'op': 'assert', 'formula': 'CountRows(Projects)', 'expect': 3},
    {'op': 'diagnostics', 'expect': 0}]}


def payload():
    return {'name': 'project-desk', 'title': 'Project desk', 'sources': {'Src/Home.pa.yaml': SOURCE},
            'lists': {'Projects': deepcopy(SCHEMA)},
            'records': {'Projects': [{'ID': 1, 'Title': 'First', 'Amount': 10}, {'ID': 2, 'Title': 'Second', 'Amount': 20}]},
            'workflows': {'create.workflow.json': deepcopy(SCENARIO)},
            'viewport': {'width': 400, 'height': 900},
            'environment': {'clock': '2026-10-13T12:00:00+00:00', 'language': 'en-US'}}


@pytest.fixture
def backend(tmp_path):
    result = HeadlessBackend(workspace=tmp_path / 'workspace')
    yield result
    result.close()


def test_empty_workspace_can_create_full_app_and_keep_workflow_writes_isolated(backend):
    described = backend.call('describe_project')
    assert described['project_path'] is None and described['revision'] is None
    assert not (backend.workspace.root / 'demo').exists()
    with pytest.raises(ValueError, match='create_project first'):
        backend.call('read_runtime')
    supplied = payload()
    created = backend.call('create_project', **supplied)
    assert created['status'] == 'created' and created['project_path'] == backend.project
    assert created['revision'] == revision(backend.project)
    assert created['sample_record_counts'] == {'Projects': 2}
    assert created['workflow_files'] == ['create.workflow.json'] and not created['diagnostics']
    assert not created['runtime_started']
    assert backend.call('read_runtime')['globals'] == {}
    assert backend.call('read_source', name='Src/Home.pa.yaml')['text'] == SOURCE
    supplied['lists']['Projects']['fields'].clear()
    assert backend.call('read_list_schema', name='Projects')['definition']['fields']
    before = data_revision(backend.workspace.runtime.store)
    result = backend.call('run_workflows', expected_revision=created['revision'],
                          workflows=[{'scenario_file': 'create.workflow.json'}])
    assert result['passed'] == 1 and result['failed'] == 0
    assert data_revision(backend.workspace.runtime.store) == before
    assert backend.call('read_runtime')['globals'] == {}
    backend.call('restart_preview', expected_revision=created['revision'])
    assert backend.call('read_runtime')['globals']['startups'] == 1
    assert backend.call('read_list', name='Projects')['total'] == 2


def test_default_scaffold_and_existing_project_switch_are_explicit(backend):
    created = backend.call('create_project', name='first', title='My "quoted" app')
    assert [s['name'] for s in created['screens']] == ['Main']
    assert not created['runtime_started']
    old_root = backend.workspace.project.root
    with pytest.raises(ValueError, match='expected_revision'):
        backend.call('create_project', name='second')
    with pytest.raises(RevisionConflict):
        backend.call('create_project', name='second', expected_revision='stale')
    assert backend.workspace.project.root == old_root
    backend.call('restart_preview', expected_revision=created['revision'])
    assert backend.call('evaluate_formula', formula='Title.Text')['value'] == 'My "quoted" app'
    second = backend.call('create_project', name='second', expected_revision=created['revision'])
    assert backend.project == second['project_path'] and backend.workspace.project.root != old_root
    assert old_root.exists() and not second['runtime_started']
    # Creation releases the old owner lease without changing that project's source.
    other = HeadlessBackend(old_root)
    other.close()


def test_startup_writes_wait_for_explicit_preview_and_workflow_writes_stay_private(backend):
    supplied = payload()
    supplied['sources']['Src/Home.pa.yaml'] = SOURCE.replace(
        '=Set(startups, 1)', '=Patch(Projects, Defaults(Projects), {Title:"Startup", Amount:1})')
    supplied['workflows']['create.workflow.json']['steps'] = [
        {'op': 'assert', 'formula': 'CountRows(Projects)', 'expect': 3},
        {'op': 'event', 'path': 'Home/Add', 'event': 'OnSelect'},
        {'op': 'assert', 'formula': 'CountRows(Projects)', 'expect': 4},
        {'op': 'diagnostics', 'expect': 0}]
    created = backend.call('create_project', **supplied)
    assert backend.call('read_list', name='Projects')['total'] == 2
    before = data_revision(backend.workspace.runtime.store)
    assert backend.call('run_workflow', expected_revision=created['revision'],
                        scenario_file='create.workflow.json')['status'] == 'passed'
    assert data_revision(backend.workspace.runtime.store) == before
    assert not backend.call('describe_project')['runtime_started']
    backend.call('restart_preview', expected_revision=created['revision'])
    assert backend.call('read_list', name='Projects')['total'] == 3


def test_create_continue_stage_test_apply_restart_export_and_undo(backend):
    created = backend.call('create_project', **payload())
    original = dict(Project(backend.project).documents)
    change = backend.call('stage_control_edits', expected_revision=created['revision'],
        edits=[{'op': 'set_property', 'path': 'Home/Count', 'property': 'Text', 'value': '="Projects: " & Text(CountRows(Projects))'}], strict=True)
    assert backend.call('run_workflow', expected_revision=created['revision'], change_id=change['id'],
                        scenario_file='create.workflow.json')['status'] == 'passed'
    applied = backend.call('apply_change', expected_revision=created['revision'], change_id=change['id'])
    backend.call('restart_preview', expected_revision=applied['after_revision'])
    assert backend.call('evaluate_formula', formula='Count.Text')['value'] == 'Projects: 2'
    exported = backend.call('export_source')
    assert exported['documents'] == Project(backend.project).documents
    assert all(n.startswith('Src/') for n in exported['documents'])
    backend.call('undo_change', expected_revision=applied['after_revision'], change_id=change['id'])
    assert Project(backend.project).documents == original


@pytest.mark.parametrize('arguments', [
    {'name': '../escape'}, {'name': '/absolute'}, {'name': 'CON'}, {'name': '.hidden'}, {'name': 'a' * 65},
    {'title': ''}, {'title': 'line\nbreak'}, {'strict': 'true'}, {'strict': 1},
    {'viewport': {'width': True, 'height': 600}}, {'viewport': {'width': 199, 'height': 600}},
    {'sources': {}}, {'sources': {'../bad.yaml': SOURCE}}, {'sources': {'Src/a.yaml': None}},
    {'sources': {'Src/a.yaml': 'Screens: [bad'}}, {'sources': {'Src/a.yaml': 'ComponentDefinitions: {}'}},
    {'sources': {'Src/a.yaml': SOURCE, 'Src/./a.yaml': SOURCE}},
    {'sources': {'Src/a.yaml': SOURCE, 'Src/A.yaml': SOURCE}},
    {'sources': {'Src/a.yaml': SOURCE.replace('=Text(CountRows(Projects))', '=missing_name')}},
    {'lists': {'Projects': {'fields': {'Title': {'type': 'invalid'}}}}},
    {'lists': {'Projects': {**SCHEMA, 'fields': {**SCHEMA['fields'], 'Amount': {'type': 'number', 'default': 'bad'}}}}},
    {'records': {'Other': []}}, {'records': {'Projects': [{'ID': 1, 'Title': ''}]}},
    {'records': {'Projects': [{'ID': 1, 'Title': 'First', 'Amount': -1}]}},
    {'records': {'Projects': [{'ID': 1, 'Title': 'A'}, {'ID': 1, 'Title': 'B'}]}},
    {'records': {'Projects': [{'ID': True, 'Title': 'A'}]}},
    {'records': {'Projects': [{'Title': 'A', 'Amount': float('nan')}]}},
    {'workflows': {'../bad.workflow.json': SCENARIO}}, {'workflows': {'bad.json': SCENARIO}},
    {'workflows': {'bad.workflow.json': {'format_version': 1, 'name': 'Bad', 'steps': []}}},
    {'workflows': {'CON.workflow.json': SCENARIO}},
    {'environment': {'unknown': 1}}, {'environment': {'clock': '2026-10-13'}},
    {'expected_revision': 'not-an-empty-workspace-revision'},
])
def test_invalid_creation_publishes_nothing_and_keeps_binding(backend, arguments):
    supplied = payload() | arguments
    with pytest.raises((ValueError, FxError)):
        backend.call('create_project', **supplied)
    assert backend.project is None and backend.workspace.runtime is None
    assert not list(backend.workspace.root.glob('*/emulator.json'))
    assert not list(backend.workspace.root.glob('.create-project-*'))


def test_existing_directory_or_symlink_is_never_replaced(backend, tmp_path):
    destination = backend.workspace.root / 'project-desk'
    destination.mkdir()
    with pytest.raises(ValueError, match='already exists'):
        backend.call('create_project', **payload())
    assert list(destination.iterdir()) == []
    destination.rmdir()
    destination.symlink_to(tmp_path / 'external', target_is_directory=True)
    with pytest.raises(ValueError, match='already exists'):
        backend.call('create_project', **payload())
    assert destination.is_symlink() and not (tmp_path / 'external').exists()


def test_schema_lookups_and_seed_references_work_in_any_order_and_cycles(backend):
    lookup = {'type': 'object', 'properties': {'Id': {'type': 'integer'}, 'Value': {'type': 'string'}}}
    fields = {'ID': {'type': 'integer'}, 'Title': {'type': 'string'}, 'Parent': lookup}
    created = backend.call('create_project', name='links', lists={
        'Details': {'fields': fields, 'lookups': {'Parent': 'Projects'}},
        'Projects': {'fields': fields, 'lookups': {'Parent': 'Details'}}}, records={
        'Details': [{'ID': 1, 'Title': 'Detail', 'Parent': {'Id': 2, 'Value': 'Project'}}],
        'Projects': [{'ID': 2, 'Title': 'Project', 'Parent': {'Id': 1, 'Value': 'Detail'}}]})
    assert created['sample_record_counts'] == {'Details': 1, 'Projects': 1}
    assert backend.call('read_list', name='Details')['rows'][0]['Parent']['Id'] == 2


def test_bad_lookup_definition_and_bad_seed_reference_are_rejected(backend):
    fields = {'ID': {'type': 'integer'}, 'Title': {'type': 'string'},
              'Parent': {'type': 'object', 'properties': {'Id': {}, 'Value': {}}}}
    with pytest.raises(ValueError, match='lookup target'):
        backend.call('create_project', name='bad-links', lists={'Details': {'fields': fields, 'lookups': {'Parent': 'Missing'}}})
    with pytest.raises(FxError, match='lookup target'):
        backend.call('create_project', name='bad-links', lists={
            'Details': {'fields': fields, 'lookups': {'Parent': 'Projects'}}, 'Projects': SCHEMA},
            records={'Details': [{'Title': 'Detail', 'Parent': {'Id': 999, 'Value': 'Missing'}}]})
    assert not (backend.workspace.root / 'bad-links').exists()


def test_seed_implicit_ids_do_not_replace_explicit_ids_and_mappings_work(backend):
    created = backend.call('create_project', name='ids', lists={'Projects': {
        **SCHEMA, 'mapping': {'ID': 'ID', 'Title': 'Project name', 'Amount': 'Budget'}}}, records={'Projects': [
            {'Project name': 'Implicit', 'Budget': 5}, {'ID': 1, 'Project name': 'Explicit', 'Budget': 10}]})
    assert created['sample_record_counts']['Projects'] == 2
    rows = backend.call('read_list', name='Projects')['rows']
    assert [(r['ID'], r['Project name']) for r in rows] == [(1, 'Explicit'), (2, 'Implicit')]


def test_strict_false_retains_findings_and_failing_workflows_are_saved_without_running(backend):
    supplied = payload()
    supplied['sources']['Src/Home.pa.yaml'] = SOURCE.replace('=Text(CountRows(Projects))', '=missing_name')
    supplied['strict'] = False
    supplied['workflows']['create.workflow.json']['steps'][0]['expect'] = 99
    created = backend.call('create_project', **supplied)
    assert created['diagnostics'] and not created['runtime_started']
    assert not (backend.workspace.project.root / '.emu/runs').exists()
    assert backend.call('list_workflows')['scenarios'][0]['scenario']['steps'][0]['expect'] == 99


def test_failed_creation_preserves_live_unsaved_state_and_source(tmp_path):
    project = forms_project(tmp_path / 'old')
    workspace = Workspace(tmp_path, project.root)
    try:
        workspace.runtime.state()
        workspace.runtime.event('Forms/DraftForm/TitleCard/TitleInput', 'OnChange', 'Unsaved edit')
        before = workspace.ai.call('read_runtime', expected_project=str(project.root))
        original = dict(project.documents)
        args = payload() | {'expected_revision': revision(project.root), 'records': {'Projects': [{'Title': ''}]}}
        with pytest.raises(FxError):
            workspace.ai.call('create_project', args, expected_project=str(project.root))
        assert workspace.ai.call('read_runtime', expected_project=str(project.root)) == before
        assert Project(project.root).documents == original
        with pytest.raises(ValueError, match='expected_project'):
            workspace.ai.call('create_project', payload())
    finally:
        workspace.runtime.close()


def test_activation_failure_preserves_valid_new_app_and_old_binding(backend, monkeypatch):
    first = backend.call('create_project', name='first')
    original_runtime = backend.workspace.runtime
    def fail_open(project, *, start=None):
        raise ValueError('Injected ownership conflict')
    monkeypatch.setattr(backend.workspace, 'open', fail_open)
    with pytest.raises(ValueError, match='new directory was preserved'):
        backend.call('create_project', name='second', expected_revision=first['revision'])
    assert backend.project == first['project_path'] and backend.workspace.runtime is original_runtime
    assert (backend.workspace.root / 'second/emulator.json').is_file()
    reopened = HeadlessBackend(backend.workspace.root / 'second')
    reopened.close()
