"""Workflow isolation, pure assertions, staged changes and browser-equivalent events."""
from copy import deepcopy
import json
import subprocess
import sys

import pytest

from powerapps_sim.application import Workspace
from powerapps_sim.authoring import RevisionConflict, data_revision, revision
from powerapps_sim.fixtures import forms_project, lifecycle_project
from powerapps_sim.workflows import STARTER, validate


@pytest.fixture
def workspace(tmp_path):
    p = forms_project(tmp_path / 'forms')
    w = Workspace(tmp_path, p.root)
    yield w
    w.runtime.close()


def scenario(*steps, **kwargs):
    return {'format_version': 1, 'name': 'Fictional check', 'steps': list(steps), **kwargs}


def check(formula, expected=True, **kwargs):
    return {'op': 'assert', 'formula': formula, 'expect': expected, **kwargs}


def event(path, name='OnSelect', **kwargs):
    return {'op': 'event', 'path': 'Forms/' + path, 'event': name, **kwargs}


def run(w, s, **kwargs):
    return w.workflows.run(s, expected_revision=revision(w.project.root), **kwargs)


TITLE = 'DraftForm/TitleCard/TitleInput'


def test_form_workflow_is_repeatable_and_does_not_change_live_workspace(workspace):
    w = workspace
    w.runtime.event('Forms/' + TITLE, 'OnChange', 'Live unsaved title')
    w.runtime.store.failures['Drafts'] = 'all'
    old_state = deepcopy(w.runtime.control_state)
    before, data = revision(w.project.root), data_revision(w.runtime.store)
    config = (w.project.root / 'emulator.json').read_bytes()
    s = scenario(event(TITLE, 'OnChange', value='Fictional workflow edit'),
        check('DraftForm.Unsaved'), event('SaveDraft'),
        check('LookUp(Drafts, ID = 1).Title', 'Fictional workflow edit'),
        check('DraftForm.LastSubmit.Title', 'Fictional workflow edit'), check('DraftForm.Unsaved', False),
        {'op': 'diagnostics', 'expect': 0})
    a, b = run(w, s), run(w, s)
    assert a['status'] == b['status'] == 'passed'
    assert a['steps'] == b['steps'] and a['trace'] == b['trace']
    assert a['writes'] == [{'list': 'Drafts', 'id': 1, 'operation': 'update'}]
    assert any(t.get('function') == 'SubmitForm' for t in a['trace'])
    assert any(t.get('member') == 'DraftForm.OnSuccess' for t in a['trace'])
    assert w.runtime.control_state == old_state and w.runtime.store.failures == {'Drafts': 'all'}
    assert revision(w.project.root) == before and data_revision(w.runtime.store) == data
    assert (w.project.root / 'emulator.json').read_bytes() == config
    assert not w.runtime.trace
    assert len(list((w.project.root / '.emu/runs').glob('*.json'))) == 2


def test_failed_save_and_recovery_are_assertable(workspace):
    s = scenario(event(TITLE, 'OnChange', value='Fictional failed edit'),
        {'op': 'failure', 'list': 'Drafts', 'mode': 'write'}, event('SaveDraft'),
        check('IsBlank(DraftForm.LastSubmit)'), check('DraftForm.Unsaved'),
        check('IsBlank(DraftForm.Error)', False), check('LookUp(Drafts, ID = 1).Title', 'Fictional bridge study'),
        {'op': 'failure', 'list': 'Drafts', 'mode': None}, event('SaveDraft'),
        check('DraftForm.LastSubmit.Title', 'Fictional failed edit'))
    report = run(workspace, s)
    assert report['status'] == 'passed', report['steps']
    assert any(t.get('member') == 'DraftForm.OnFailure' for t in report['trace'])
    assert report['steps'][2]['writes'] == []


def test_assertions_are_pure_and_preserve_error_blank_and_boolean(workspace):
    report = run(workspace, scenario(check('Blank()', None), check('true', 1),
        {'op': 'assert', 'formula': 'Set(selectedId, 2)', 'error_kind': 'Validation'},
        check('selectedId', 1), {'op': 'assert', 'formula': 'missing_identifier', 'error_kind': 'Name'}))
    assert report['status'] == 'failed'
    assert [s['status'] for s in report['steps']] == ['passed', 'failed', 'passed', 'passed', 'passed']
    assert report['steps'][2]['actual']['$error']
    assert report['diagnostics'] == []  # Test assertion errors are reported on their own step.


def test_hidden_disabled_and_inactive_controls_are_not_exercised(workspace):
    report = run(workspace, scenario(event('ViewDraft'), event(TITLE, 'OnChange', value='Blocked'), check('true')))
    assert report['status'] == 'failed' and report['steps_skipped'] == 1
    assert 'disabled' in report['steps'][-1]['error']
    original = workspace.project.documents['Src/forms.pa.yaml']
    staged = workspace.authoring.stage(expected_revision=revision(workspace.project.root),
        sources={'Src/forms.pa.yaml': original.replace('Screens:\n', 'Screens:\n  Other: {}\n', 1)})
    report = run(workspace, scenario({'op': 'event', 'path': 'Other', 'event': 'OnSelect'}, check('true')), change_id=staged['id'])
    assert 'active screen' in report['steps'][0]['error']


def test_expected_blocked_events_assert_gates_without_executing_handlers(workspace):
    report = run(workspace, scenario(event('ViewDraft'),
        event(TITLE, 'OnChange', value='Blocked', expect_blocked=True),
        check('TitleInput.Text', 'Fictional bridge study')))
    assert report['status'] == 'passed' and report['steps'][1]['blocked']
    assert not report['writes']
    for step in (event('NewDraft', expect_blocked=True), event('Missing', expect_blocked=True)):
        report = run(workspace, scenario(step, check('true')))
        assert report['status'] == 'failed' and not report['writes']


def test_candidate_uses_combined_source_schema_migration_without_applying(workspace):
    w = workspace
    source = w.project.documents['Src/forms.pa.yaml']
    definition = deepcopy(w.runtime.store.definitions['Drafts'])
    definition['fields']['Priority'] = {'type': 'string', 'default': 'Normal'}
    definition['mapping']['Priority'] = 'Project priority'
    change = w.authoring.stage(expected_revision=revision(w.project.root), sources={
        'Src/forms.pa.yaml': source.replace('Set(selectedId, 1)', 'Set(selectedId, 2)', 1)}, lists={'Drafts': definition})
    data = data_revision(w.runtime.store)
    report = run(w, scenario(check('selectedId', 2), check('First(Drafts).\'Project priority\'', 'Normal')), change_id=change['id'])
    assert report['status'] == 'passed'
    assert report['candidate_revision'] != report['base_revision']
    assert w.runtime.globals['selectedId'] == 1 and data_revision(w.runtime.store) == data
    assert w.authoring.history()[0]['status'] == 'staged'
    w.runtime.store.patch('Drafts', {}, {'Title': 'Fictional new row', 'Amount': 1})
    with pytest.raises(RevisionConflict, match='stale'):
        run(w, STARTER, change_id=change['id'])


def test_scope_environment_and_disposable_fixture_records(workspace):
    s = scenario(check('CountRows(Drafts)', 1), check('Self.Text', 'Fictional scenario', scope='Forms/' + TITLE),
        check('User().Email', 'fictional@example.test'), check('Language()', 'fr-CA'), check('Param("role")', 'reviewer'),
        check('Year(Today())', 2025), records={'Drafts': [{'ID': 1, 'Title': 'Fictional scenario', 'Amount': 5}]},
        environment={'user': {'Email': 'fictional@example.test', 'FullName': 'Fictional Reviewer'},
                     'language': 'fr-CA', 'parameters': {'role': 'reviewer'}, 'clock': '2025-05-06T12:00:00+00:00'})
    report = run(workspace, s)
    assert report['status'] == 'passed', report['steps']
    assert len(workspace.runtime.store.rows('Drafts')) == 2


def test_component_reset_callback_trace_and_instance_isolation(tmp_path):
    p = lifecycle_project(tmp_path / 'lifecycle')
    w = Workspace(tmp_path, p.root)
    try:
        r = w.runtime
        r.state()
        button = r.global_refs['ChangeSeed'].path if 'ChangeSeed' in r.global_refs else next(
            ref.path for ref in r.refs.values() if str(ref.raw_property('OnSelect')).find('Set(seed, seed + 10)') >= 0)
        report = run(w, scenario({'op': 'event', 'path': button, 'event': 'OnSelect'}, check('seed', 20)))
        assert report['status'] == 'passed'
        assert any(t.get('member', '').endswith('.OnReset') for t in report['trace'])
        assert any(t.get('member', '').endswith('.OnResetDone') for t in report['trace'])
        assert r.globals['seed'] == 10
    finally:
        w.runtime.close()


@pytest.mark.parametrize('alter', [lambda s: s.update(typo=True), lambda s: s.update(format_version=True),
    lambda s: s.update(steps=[]), lambda s: s.update(steps=[{'op':'event', 'path':'Forms', 'event':'OnSelect'}]),
    lambda s: s.update(viewport={'width':False}), lambda s: s.update(environment={'clock':'2026-01-01'}),
    lambda s: s['steps'][0].update(typo=True), lambda s: s['steps'][0].update(error_kind='Name'),
    lambda s: s.update(environment={'user':{'Email':12}}),
    lambda s: s.update(steps=[{'op':'event','path':'Forms/ViewDraft','event':'OnSelect','expect_blocked':'true'},check('true')])])
def test_invalid_definitions_are_rejected_before_running(alter):
    s = deepcopy(STARTER)
    alter(s)
    with pytest.raises(ValueError):
        validate(s)


def test_invalid_records_and_stale_revision_preserve_live_state(workspace):
    old = data_revision(workspace.runtime.store)
    with pytest.raises(Exception, match='required'):
        run(workspace, scenario(check('true'), records={'Drafts':[{'Amount':1}]}))
    with pytest.raises(RevisionConflict):
        workspace.workflows.run(STARTER, expected_revision='stale')
    assert data_revision(workspace.runtime.store) == old


def test_catalog_reports_invalid_saved_scenarios(workspace):
    directory = workspace.project.root / 'tests'
    directory.mkdir(exist_ok=True)
    (directory / 'bad.workflow.json').write_text('{bad')
    (directory / 'good.workflow.json').write_text(json.dumps(STARTER))
    catalog = workspace.workflows.catalog()
    assert any(s.get('error') for s in catalog['scenarios'])
    assert any(s.get('scenario') == STARTER for s in catalog['scenarios'])


def test_http_workflow_does_not_navigate_open_preview(app, post):
    w = app.extensions['workspace']
    before = data_revision(w.runtime.store)
    result = post('/api/workflows/run', {'expected_revision':revision(w.project.root), 'scenario':STARTER})
    assert result.status_code == 200 and result.json['status'] == 'passed'
    assert data_revision(w.runtime.store) == before and w.runtime.active_screen == 'Home'
    assert post('/api/workflows/run', {'expected_revision':'stale', 'scenario':STARTER}).status_code == 409
    with app.test_client() as client:
        saved = client.get('/api/workflows/runs/' + result.json['id'])
        assert saved.json == result.json
        assert client.get('/api/workflows/runs/not-an-id').status_code == 400


def test_cli_runs_without_starting_live_app_and_returns_failure_exit_code(tmp_path):
    p = forms_project(tmp_path / 'forms')
    path = tmp_path / 'scenario.json'
    path.write_text(json.dumps(scenario(check('selectedId', 99))))
    result = subprocess.run([sys.executable, '-m', 'powerapps_sim.workflows', str(p.root), str(path)], capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    assert json.loads(result.stdout)['status'] == 'failed'


@pytest.mark.parametrize('factory', [forms_project, lifecycle_project])
def test_packaged_workflows_pass_for_clean_fixtures(tmp_path, factory):
    p = factory(tmp_path / 'fixture')
    w = Workspace(tmp_path, p.root)
    try:
        catalog = w.workflows.catalog()
        assert catalog['scenarios']
        for entry in catalog['scenarios']:
            report = run(w, entry['scenario'])
            assert report['status'] == 'passed', report['steps']
    finally:
        w.runtime.close()


def test_demo_translation_filtering_navigation_and_component_callback(app):
    w = app.extensions['workspace']
    catalog = w.workflows.catalog()
    demo = next(s for s in catalog['scenarios'] if s['scenario']['name'].startswith('Translation'))
    report = run(w, demo['scenario'])
    assert report['status'] == 'passed', report['steps']
    assert any(t['kind'] == 'navigation' for t in report['trace'])
    assert w.runtime.active_screen == 'Home' and w.runtime.globals['varLanguage'] == 'en'


def test_trace_limit_is_explicit_and_does_not_change_behavior(workspace, monkeypatch):
    from powerapps_sim.runtime import Runtime
    original = Runtime.restart
    def small_trace(r):
        r.trace_limit = 3
        original(r)
    monkeypatch.setattr(Runtime, 'restart', small_trace)
    report = run(workspace, scenario(check('selectedId', 1)))
    assert report['status'] == 'passed' and report['trace_truncated']
    assert len(report['trace']) == 3


def test_invalid_selection_fails_action_and_skips_dependent_steps(app):
    w = app.extensions['workspace']
    report = run(w, scenario({'op':'event', 'path':'Home/Page/ProjectGallery', 'event':'OnSelect', 'selection':[99]}, check('true')))
    assert report['status'] == 'failed' and report['steps_skipped'] == 1
    assert 'index' in report['steps'][0]['error']


def test_decimal_assertions_keep_exact_json_values(workspace):
    source = workspace.project.documents['Src/forms.pa.yaml'].replace('    StartScreen:',
        "    Formulas: '=Identity(n: Number): Number = n; Exact = Identity(.1 + .2); Explicit = Decimal(\"0.3\");'\n    StartScreen:", 1)
    candidate = workspace.authoring.stage(expected_revision=revision(workspace.project.root), sources={'Src/forms.pa.yaml':source})
    report = run(workspace, scenario(check('0.1 + 0.2', {'$decimal':'0.3'}), check('Exact', {'$decimal':'0.3'}),
        check('Explicit', {'$decimal':'0.3'}), {'op':'diagnostics','expect':0},
        environment={'number_mode':'decimal'}), change_id=candidate['id'])
    assert report['status'] == 'passed'


def test_wall_clock_is_frozen_and_report_can_be_replayed(workspace):
    workspace.runtime.project.config['environment']['clock'] = None
    workspace.runtime.project.save_config()
    report = run(workspace, scenario(check('Now() = Now()')))
    assert report['status'] == 'passed' and report['clock_frozen']
    replay = deepcopy(report['scenario'])
    replay['environment'] = report['environment']
    second = run(workspace, replay)
    assert second['status'] == 'passed' and not second['clock_frozen']
    assert second['environment']['clock'] == report['environment']['clock']


@pytest.mark.parametrize('step',[
 {'op':'event','event':'OnSelect'},
 {'op':'event','path':'Forms/NewDraft','target':'NewDraft','event':'OnSelect'},
 {'op':'event','target':123,'event':'OnSelect'},
 {'op':'event','target':'','event':'OnSelect'},
 {'op':'event','path':'Forms/NewDraft','scope':'Forms','event':'OnSelect'},
 {'op':'event','target':'NewDraft','scope':None,'event':'OnSelect'},
])
def test_target_formula_schema_rejects_ambiguous_or_malformed_events(step):
    with pytest.raises(ValueError):validate(scenario(step,check('true')))


@pytest.mark.parametrize('target,scope',[('42',None),('Missing',None),('NewDraft','Missing'),('Set(mustStayBlank,1);NewDraft',None)])
def test_target_formula_failure_is_pure_and_preserves_owner(workspace,target,scope):
    w=workspace;before=deepcopy(w.ai.read_runtime());data=data_revision(w.runtime.store)
    step={'op':'event','target':target,'event':'OnSelect'}
    if scope:step['scope']=scope
    report=run(w,scenario(step,check('true')))
    assert report['status']=='failed' and w.ai.read_runtime()==before and data_revision(w.runtime.store)==data
    assert 'mustStayBlank' not in w.runtime.globals


def test_target_formula_resolves_same_control_and_visibility_gate(workspace):
    w=workspace
    report=run(w,scenario({'op':'event','target':'Self','scope':'Forms/NewDraft','event':'OnSelect'},check('DraftForm.Mode=FormMode.New')))
    assert report['status']=='passed' and report['steps'][0]['control_path']=='Forms/NewDraft'
    report=run(w,scenario(event('ViewDraft'),{'op':'event','target':'TitleInput','event':'OnChange','value':'blocked','expect_blocked':True},check('DraftForm.Mode=FormMode.View')))
    assert report['status']=='passed'
