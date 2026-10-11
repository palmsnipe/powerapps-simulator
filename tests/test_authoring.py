"""Authored schema/source changes, concurrency, migrations and recovery."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from zipfile import ZipFile

import pytest

from powerapps_sim.application import Workspace
from powerapps_sim.authoring import RevisionConflict, data_revision, revision, recover_changes
from powerapps_sim.catalog import json_text
from powerapps_sim.fixtures import forms_project
from powerapps_sim.source import Project
from powerapps_sim.store import ListStore
from powerapps_sim.syntax import FxError


@pytest.fixture
def workspace(tmp_path):
    p = forms_project(tmp_path/'forms')
    w = Workspace(tmp_path, p.root)
    yield w
    w.runtime.close()


def stage(w, **kwargs):
    return w.authoring.stage(expected_revision=revision(w.project.root), **kwargs)


def apply(w, change):
    return w.authoring.apply(change['id'], expected_revision=change['base_revision'])


def add_priority(w):
    d = deepcopy(w.runtime.store.definitions['Drafts'])
    d['fields']['Priority'] = {'type':'string', 'default':'Normal', 'maxLength':20}
    d['mapping']['Priority'] = 'Project priority'
    return d


def test_legacy_database_bootstraps_portable_schemas_without_changing_records(tmp_path):
    p = Project(tmp_path/'legacy')
    s = ListStore(p.root/'data.sqlite')
    s.add_list('A / strange: list', {'fields':{'ID':{'type':'integer'}, 'Title':{'type':'string'}}, 'required':['Title']})
    s.patch('A / strange: list', {}, {'Title':'Fictional'})
    before = data_revision(s); s.close()
    s = ListStore(p.root/'data.sqlite', schema_root=p.root/'lists')
    try:
        assert data_revision(s) == before
        files = list((p.root/'lists').glob('*.json'))
        assert len(files) == 1
        assert json.loads(files[0].read_text())['name'] == 'A / strange: list'
        assert (p.root/'metadata/schema-catalog.json').exists()
        assert not p.config.get('source_edited')
    finally:
        s.close()


def test_stage_is_pure_and_combined_change_uses_new_schema_for_binding(workspace):
    w = workspace
    before, data = revision(w.project.root), data_revision(w.runtime.store)
    original = w.project.documents['Src/forms.pa.yaml']
    source = original.replace('Mode ', 'Priority " & Coalesce(DraftForm.Item.\'Project priority\', "none") & " · Mode ', 1)
    change = stage(w, sources={'Src/forms.pa.yaml':source}, lists={'Drafts':add_priority(w)})
    assert not change['diagnostics']
    assert change['impacts'][0]['records_changed'] == 2
    assert revision(w.project.root) == before
    assert data_revision(w.runtime.store) == data
    assert w.project.documents['Src/forms.pa.yaml'] == original
    applied = apply(w, change)
    assert applied['status'] == 'applied'
    assert w.runtime.store.rows('Drafts')[0]['Project priority'] == 'Normal'
    assert w.runtime.pending_source
    assert w.runtime.project.documents['Src/forms.pa.yaml'] == original
    w.open(Project(w.project.root))
    assert not w.runtime.pending_source
    assert not w.runtime.diagnostics
    w.authoring.undo(change['id'], expected_revision=applied['after_revision'])
    assert revision(w.project.root) == before
    assert data_revision(w.runtime.store) == data


def test_explicit_rename_preserves_values_ids_and_display_mapping(workspace):
    w = workspace
    d = deepcopy(w.runtime.store.definitions['Drafts'])
    d['fields']['Budget'] = d['fields'].pop('Amount')
    d['mapping']['Budget'] = d['mapping'].pop('Amount')
    d['required'] = ['Budget' if n == 'Amount' else n for n in d['required']]
    with pytest.raises(ValueError, match='explicit'):
        stage(w, lists={'Drafts':d})
    change = stage(w, lists={'Drafts':d}, migrations={'Drafts':{'rename_columns':{'Amount':'Budget'}}})
    apply(w, change)
    row = json.loads(w.runtime.store.db.execute('SELECT record FROM items WHERE id=1').fetchone()[0])
    assert row['ID'] == 1 and row['Budget'] == 125 and 'Amount' not in row
    assert w.runtime.store.rows('Drafts')[0]['Amount'] == 125


def test_drop_is_explicit_and_undo_restores_removed_values(workspace):
    w = workspace
    d = deepcopy(w.runtime.store.definitions['Drafts'])
    del d['fields']['Amount']; del d['mapping']['Amount']; d['required'].remove('Amount')
    change = stage(w, lists={'Drafts':d}, migrations={'Drafts':{'drop_columns':['Amount']}})
    applied = apply(w, change)
    assert 'Amount' not in w.runtime.store.rows('Drafts')[0]
    w.authoring.undo(change['id'], expected_revision=applied['after_revision'])
    assert w.runtime.store.rows('Drafts')[0]['Amount'] == 125


@pytest.mark.parametrize('alter', ['required', 'length', 'type', 'id', 'mapping', 'default'])
def test_invalid_migration_is_rejected_without_any_mutation(workspace, alter):
    w = workspace
    d = add_priority(w)
    if alter == 'required':
        d['required'].append('Priority'); d['fields']['Priority'].pop('default')
    elif alter == 'length':
        d['fields']['Title']['maxLength'] = 2
    elif alter == 'type':
        d['fields']['Amount']['type'] = 'boolean'
    elif alter == 'id':
        d['fields']['ID']['type'] = 'string'
    elif alter == 'mapping':
        d['mapping']['Priority'] = 'Title'
    else:
        d['fields']['Priority']['default'] = 99
    old, data = revision(w.project.root), data_revision(w.runtime.store)
    with pytest.raises((ValueError, FxError)):
        stage(w, lists={'Drafts':d})
    assert revision(w.project.root) == old
    assert data_revision(w.runtime.store) == data
    assert not w.authoring.history()


def test_schema_change_rejects_new_records_after_staging(workspace):
    w = workspace
    change = stage(w, lists={'Drafts':add_priority(w)})
    w.runtime.store.patch('Drafts', {}, {'Title':'Fictional new row', 'Amount':3})
    with pytest.raises(RevisionConflict, match='records changed'):
        apply(w, change)
    assert 'Priority' not in w.runtime.store.definitions['Drafts']['fields']


def test_undo_schema_refuses_to_discard_newer_record_changes(workspace):
    w = workspace
    change = stage(w, lists={'Drafts':add_priority(w)})
    applied = apply(w, change)
    w.runtime.store.patch('Drafts', {'ID':1}, {'Title':'Newer fictional edit'})
    with pytest.raises(RevisionConflict, match='newer data'):
        w.authoring.undo(change['id'], expected_revision=applied['after_revision'])
    assert w.runtime.store.rows('Drafts')[0]['Title'] == 'Newer fictional edit'


def test_source_only_undo_preserves_new_data_and_environment_changes(workspace):
    w = workspace
    text = w.project.documents['Src/forms.pa.yaml'].replace('Form lifecycle', 'Changed fixture')
    change = stage(w, sources={'Src/forms.pa.yaml':text})
    applied = apply(w, change)
    w.project.config['environment']['language'] = 'fr-CA'; w.project.save_config()
    w.runtime.store.patch('Drafts', {'ID':1}, {'Title':'Keep this newer edit'})
    w.authoring.undo(change['id'], expected_revision=applied['after_revision'])
    assert w.runtime.store.rows('Drafts')[0]['Title'] == 'Keep this newer edit'
    assert Project(w.project.root).config['environment']['language'] == 'fr-CA'
    assert Project(w.project.root).config['source_edited']


def test_stale_source_and_staged_changes_do_not_overwrite_newer_edits(workspace):
    w = workspace
    old = revision(w.project.root)
    text = w.project.documents['Src/forms.pa.yaml']
    change = stage(w, sources={'Src/forms.pa.yaml':text.replace('reset and save', 'reviewed change')})
    w.authoring.save_source(expected_revision=old, name='Src/forms.pa.yaml', text=text.replace('reset and save', 'newer edit'))
    with pytest.raises(RevisionConflict):
        w.authoring.apply(change['id'], expected_revision=revision(w.project.root))
    with pytest.raises(RevisionConflict):
        w.authoring.save_source(expected_revision=old, name='Src/forms.pa.yaml', text=text)
    assert 'newer edit' in w.project.documents['Src/forms.pa.yaml']


def test_malformed_draft_retained_and_invalid_powerfx_remains_reviewable(workspace):
    w = workspace
    old = revision(w.project.root)
    with pytest.raises(Exception):
        w.authoring.save_source(expected_revision=old, name='Src/forms.pa.yaml', text='Screens: [bad')
    assert revision(w.project.root) == old
    assert (w.project.root/'drafts/Src/forms.pa.yaml').read_text() == 'Screens: [bad'
    text = w.project.documents['Src/forms.pa.yaml'].replace('Text: ="Title"', 'Text: =MissingOriginalControl.Text')
    change = stage(w, sources={'Src/forms.pa.yaml':text})
    assert any('MissingOriginalControl' in d['message'] for d in change['diagnostics'])
    with pytest.raises(ValueError, match='Strict'):
        stage(w, sources={'Src/forms.pa.yaml':text}, strict=True)
    apply(w, change)
    assert 'MissingOriginalControl' in w.project.documents['Src/forms.pa.yaml']


def test_file_edited_catalog_loads_explicitly_and_rejects_invalid_changes(workspace):
    w = workspace
    target = w.runtime.store.catalog.path('Drafts')
    catalog = json.loads(target.read_text())
    catalog['definition'] = add_priority(w)
    target.write_text(json_text(catalog))
    with pytest.raises(RevisionConflict, match='Restart'):
        stage(w, sources={'Src/forms.pa.yaml':w.project.documents['Src/forms.pa.yaml']})
    w.open(Project(w.project.root))
    assert w.runtime.store.rows('Drafts')[0]['Project priority'] == 'Normal'
    before = data_revision(w.runtime.store)
    catalog['definition']['fields']['Amount']['type'] = 'boolean'
    target.write_text(json_text(catalog))
    with pytest.raises(FxError):
        w.open(Project(w.project.root))
    assert data_revision(w.runtime.store) == before
    assert w.runtime.store.definitions['Drafts']['fields']['Amount']['type'] == 'number'


def test_deleted_catalog_is_not_silently_regenerated(workspace):
    w = workspace
    w.runtime.store.catalog.path('Drafts').unlink()
    with pytest.raises(ValueError, match='Missing authored'):
        w.open(Project(w.project.root))


def test_schema_apply_failure_restores_source_schema_and_database(workspace, monkeypatch):
    import powerapps_sim.catalog as catalog_module
    w = workspace
    before, data = revision(w.project.root), data_revision(w.runtime.store)
    change = stage(w, sources={'Src/forms.pa.yaml':w.project.documents['Src/forms.pa.yaml'].replace('Form lifecycle', 'Not committed')}, lists={'Drafts':add_priority(w)})
    write = catalog_module.atomic_write
    def fail(target, content):
        if Path(target).parent == w.project.root/'lists':
            raise OSError('Injected filesystem failure')
        return write(target, content)
    monkeypatch.setattr(catalog_module, 'atomic_write', fail)
    with pytest.raises(OSError):
        apply(w, change)
    assert revision(w.project.root) == before
    assert data_revision(w.runtime.store) == data
    assert w.authoring.history()[0]['status'] == 'rolled_back'


def test_interrupted_apply_recovers_on_open(workspace):
    w = workspace
    before, data = revision(w.project.root), data_revision(w.runtime.store)
    change = stage(w, lists={'Drafts':add_priority(w)})
    apply(w, change)
    manifest, entry = w.authoring._entry(change['id'])
    entry['status'] = 'applying'; manifest.write_text(json_text(entry))
    assert recover_changes(w.project.root)
    w.open(Project(w.project.root))
    assert revision(w.project.root) == before
    assert data_revision(w.runtime.store) == data
    assert w.authoring.history()[0]['recovered']


def test_new_list_is_authored_and_undo_removes_it(workspace):
    w = workspace
    change = stage(w, lists={'New list':{'fields':{'Title':{'type':'string'}}}})
    applied = apply(w, change)
    assert w.runtime.store.catalog.path('New list').exists()
    assert 'New list' in w.runtime.store.definitions
    w.authoring.undo(change['id'], expected_revision=applied['after_revision'])
    assert 'New list' not in w.runtime.store.definitions
    assert not w.runtime.store.catalog.path('New list').exists()


def test_export_excludes_all_catalog_and_journal_files(workspace):
    w = workspace
    apply(w, stage(w, lists={'Drafts':add_priority(w)}))
    with ZipFile(BytesIO(w.project.export())) as archive:
        assert archive.namelist() == ['Src/forms.pa.yaml']


def test_workspace_ownership_and_headless_cli_do_not_run_startup(workspace):
    w = workspace
    args = [sys.executable, '-m', 'powerapps_sim.authoring', str(w.project.root), 'describe']
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode != 0 and 'already open' in result.stderr
    root = w.project.root
    w.runtime.close()
    # Startup behavior would persist a third row if the CLI executed it.
    p = Project(root); p.update_app_property('OnStart', '=Patch(Drafts, Defaults(Drafts), {Title: "Startup mutation", Amount: 0})')
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0
    assert json.loads(result.stdout)['revision'] == revision(root)
    s = ListStore(root/'data.sqlite')
    assert len(s.rows('Drafts')) == 2
    s.close()
    w.open(Project(root))
    assert len(w.runtime.store.rows('Drafts')) == 3


def test_schema_http_review_apply_undo_and_revision_errors(app, client, post):
    w = app.extensions['workspace']
    before = client.get('/api/project').json['revision']
    d = deepcopy(w.runtime.store.definitions['Projects'])
    d['fields']['Priority'] = {'type':'string','default':'Normal'}; d['mapping']['Priority'] = 'Priority'
    missing = post('/api/changes', {'lists':{'Projects':d}, 'expected_revision':None})
    assert missing.status_code == 400
    response = post('/api/changes', {'lists':{'Projects':d}, 'expected_revision':before})
    assert response.status_code == 200
    change = response.json
    assert 'Priority' not in w.runtime.store.rows('Projects')[0]
    applied = post('/api/changes/'+change['id']+'/apply', {'expected_revision':before})
    assert applied.status_code == 200
    assert 'Priority' in w.runtime.store.rows('Projects')[0]
    stale = post('/api/source', {'name':'Src/demo.pa.yaml','text':'Screens: {}','expected_revision':before})
    assert stale.status_code == 409 and stale.json['conflict']
    undone = post('/api/changes/'+change['id']+'/undo', {'expected_revision':applied.json['after_revision']})
    assert undone.status_code == 200
    assert 'Priority' not in w.runtime.store.rows('Projects')[0]
    assert client.get('/api/changes').json['changes'][0]['status'] == 'undone'


def test_source_http_reads_external_edits_and_marks_old_draft_stale(app, client, post):
    w = app.extensions['workspace']
    old = revision(w.project.root)
    post('/api/source', {'name':'Src/demo.pa.yaml','text':'Screens: [bad','expected_revision':old})
    target = w.project.root/'Src/demo.pa.yaml'
    target.write_text(target.read_text().replace('Project workspace', 'External edit'))
    source = client.get('/api/source?name=Src/demo.pa.yaml').json
    assert 'External edit' in source['text']
    assert source['draft_stale'] and source['draft'] is None
    assert 'External edit' in client.get('/api/project').json['app']['Formulas']


def test_combined_source_move_is_validated_as_one_model(workspace):
    w = workspace
    original = w.project.documents['Src/forms.pa.yaml']
    change = stage(w, sources={'Src/new.pa.yaml':original, 'Src/forms.pa.yaml':None})
    assert not change['diagnostics']
    applied = apply(w, change)
    assert 'Src/new.pa.yaml' in w.project.documents
    assert 'Src/forms.pa.yaml' not in w.project.documents
    w.authoring.undo(change['id'], expected_revision=applied['after_revision'])
    assert list(w.project.documents) == ['Src/forms.pa.yaml']


def test_interrupted_undo_recovers_to_applied_state(workspace):
    w = workspace
    change = stage(w, lists={'Drafts':add_priority(w)})
    applied = apply(w, change)
    w.authoring.undo(change['id'], expected_revision=applied['after_revision'])
    manifest, entry = w.authoring._entry(change['id'])
    entry['status'] = 'undoing'; manifest.write_text(json_text(entry))
    w.open(Project(w.project.root))
    assert 'Priority' in w.runtime.store.definitions['Drafts']['fields']
    assert w.authoring.history()[0]['status'] == 'applied'
    assert w.runtime.store.rows('Drafts')[0]['Project priority'] == 'Normal'


def test_app_property_edit_uses_history_and_preserves_comments(workspace):
    w = workspace
    target = w.project.root/'Src/forms.pa.yaml'
    target.write_text('# Keep this comment\n'+target.read_text())
    w.authoring.save_source(expected_revision=revision(w.project.root), property='Formulas', text='Counter = 42;')
    assert target.read_text().startswith('# Keep this comment\n')
    assert 'Counter = 42' in w.project.app['Formulas']
    assert w.authoring.history()[0]['status'] == 'applied'


def test_undo_requires_latest_change_and_protects_external_source_edit(workspace):
    w = workspace
    text = w.project.documents['Src/forms.pa.yaml']
    first = stage(w, sources={'Src/forms.pa.yaml':text.replace('Form lifecycle', 'First version')})
    apply(w, first)
    second = stage(w, sources={'Src/forms.pa.yaml':text.replace('Form lifecycle', 'Second version')})
    applied = apply(w, second)
    with pytest.raises(ValueError, match='latest'):
        w.authoring.undo(first['id'], expected_revision=applied['after_revision'])
    target = w.project.root/'Src/forms.pa.yaml'; target.write_text(target.read_text()+'\n# external\n')
    with pytest.raises(RevisionConflict, match='newer edits'):
        w.authoring.undo(second['id'], expected_revision=revision(w.project.root))


def test_lookup_defaults_check_relationships_without_using_injected_failures(workspace):
    w = workspace
    d = add_priority(w)
    d['fields']['Related'] = {'type':'object','properties':{'Id':{},'Value':{}},'default':{'Id':1,'Value':'Fictional bridge study'}}
    d['mapping']['Related'] = 'Related'; d['lookups']['Related'] = 'Drafts'
    w.runtime.store.failures['Drafts'] = 'read'
    change = stage(w, lists={'Drafts':d})
    assert change['impacts'][0]['records_checked'] == 2
    assert w.runtime.store.failures['Drafts'] == 'read'
    d['fields']['Related']['default']['Id'] = 99
    with pytest.raises(FxError, match='lookup target'):
        stage(w, lists={'Drafts':d})


@pytest.mark.parametrize('sources', [[], False, {'../bad.yaml':'Screens: {}'}, {'Src/a.yaml':'Screens: {}','Src\\a.yaml':'Screens: {}'}])
def test_invalid_source_change_shapes_are_rejected(workspace, sources):
    with pytest.raises(ValueError):
        stage(workspace, sources=sources, lists={'Drafts':add_priority(workspace)})
