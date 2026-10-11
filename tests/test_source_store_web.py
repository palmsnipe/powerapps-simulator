from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile
import pytest

from powerapps_sim.source import Project, safe_path
from powerapps_sim.syntax import FxError
from powerapps_sim.scenarios import seed


def test_source_preserves_unknown_properties_comments_and_formulas(runtime):
    p = runtime.project
    name = 'Src/demo.pa.yaml'
    source = '# Keep this comment\n' + p.documents[name].replace('Fill: =RGBA(247, 249, 252, 1)', 'UnknownFutureProperty: =123\n      Fill: =RGBA(247, 249, 252, 1)', 1)
    p.update_source(name, source)
    p.update_app_property('StartScreen', 'Home')
    assert '# Keep this comment' in p.documents[name]
    assert 'UnknownFutureProperty: =123' in p.documents[name]
    assert p.app['StartScreen'] == '=Home'
    with ZipFile(BytesIO(p.export())) as z:
        assert z.namelist() == ['Src/demo.pa.yaml']
        assert b'UnknownFutureProperty' in z.read(name)
        assert 'emulator.json' not in z.namelist()


def test_invalid_draft_keeps_active_source_and_preview(runtime):
    p = runtime.project
    previous = p.documents['Src/demo.pa.yaml']
    with pytest.raises(Exception):
        p.update_source('Src/demo.pa.yaml', 'Screens: [broken')
    assert p.documents['Src/demo.pa.yaml'] == previous
    assert (p.root / 'drafts/Src/demo.pa.yaml').read_text() == 'Screens: [broken'
    assert runtime.state()['screen'] == 'Home'


def test_copy_control_subtree(runtime):
    code = runtime.project.export_control('TitleCard')
    assert 'Control: TypedDataCard@1.0.7' in code
    assert 'TitleInput' in code
    assert 'simulator' not in code


@pytest.mark.parametrize('name', ['../bad', '/absolute', 'C:\\bad', 'nested/../../bad'])
def test_paths_cannot_escape_project(tmp_path, name):
    with pytest.raises(ValueError):
        safe_path(tmp_path, name)


def test_backslash_archive_and_yml_import(tmp_path):
    content = BytesIO()
    with ZipFile(content, 'w') as z:
        z.writestr('Src\\Home.pa.yaml', 'Screens:\n  Home:\n    Properties:\n      Fill: =Color.White\n')
    p = Project.import_archive(content.getvalue(), tmp_path / 'archive')
    assert 'Home' in p.screens
    p = Project.import_yaml('Screens:\n  Home: {}\n', tmp_path / 'yaml', 'test.yml')
    assert 'Home' in p.screens


def test_clipboard_control_sequence(tmp_path):
    text = '# Clipboard comment\n- Hello:\n    Control: ModernText@1.0.0\n    Properties:\n      Text: ="Hi"\n'
    p = Project.import_yaml(text, tmp_path)
    assert p.screens['Scratch'].children[0].name == 'Hello'
    assert p.documents['Src/Imported.pa.yaml'] == text


def test_required_shapes_and_read_only_columns(runtime):
    store = runtime.store
    with pytest.raises(FxError, match='Title is required'):
        store.patch('Projects', {}, {'Title': '', 'Status': {'Value': 'Draft'}})
    with pytest.raises(FxError, match='Invalid choice'):
        store.patch('Projects', {}, {'Title': 'Bad', 'Status': {'Value': 'Invalid'}})
    with pytest.raises(FxError, match='Person record'):
        store.patch('Projects', {}, {'Title': 'Bad', 'Status': {'Value': 'Draft'}, 'Owner': {'Email': 'x'}})
    with pytest.raises(FxError, match='read-only'):
        store.patch('Projects', {}, {'ID': 2, 'Title': 'Bad', 'Status': {'Value': 'Draft'}})
    with pytest.raises(FxError, match='maximum length'):
        store.patch('Projects', {}, {'Title': 'x'*256, 'Status': {'Value': 'Draft'}})


def test_name_mapping_and_lookup_validation(runtime):
    s = runtime.store
    s.add_list('Details', {'fields': {'ID': {'type':'integer'}, 'InternalName': {'type':'string'}, 'Project': {'type':'object','properties':{'Id':{},'Value':{}}}},
        'mapping': {'InternalName':'Display Name'}, 'required': ['InternalName'], 'lookups': {'Project':'Projects'}})
    row = s.patch('Details', {}, {'Display Name':'A', 'Project':{'Id':1,'Value':'Wetland monitoring'}})
    assert row['Display Name']=='A'
    with pytest.raises(FxError, match='lookup target'):
        s.patch('Details', {}, {'Display Name':'B', 'Project':{'Id':999,'Value':'Missing'}})


def test_atomic_import_csv_and_json_roundtrip(runtime):
    s = runtime.store
    before = s.rows('Projects')
    with pytest.raises(FxError):
        s.import_rows('Projects', [{'Title':'Valid', 'Status':{'Value':'Draft'}}, {'Title':'', 'Status':{'Value':'Draft'}}])
    assert s.rows('Projects') == before
    import csv
    from io import StringIO
    rows = list(csv.DictReader(StringIO(s.export_csv('Projects'))))
    s.reset();s.import_rows('Projects', rows)
    assert s.rows('Projects') == before


def test_repeatable_scenarios(runtime):
    seed(runtime.store, '2026-10-09T12:00:00+00:00')
    before = runtime.store.rows('Projects')
    seed(runtime.store, '2026-10-09T12:00:00+00:00')
    assert runtime.store.rows('Projects') == before


def test_http_source_restart_and_drafts(client, post):
    project = client.get('/api/project').json
    response = post('/api/source', {'expected_revision': project['revision'], 'name': project['documents'][0], 'text':'Screens: [broken'})
    assert response.status_code == 400
    assert response.json['draft_saved'] is True
    assert client.get('/api/state').json['screen'] == 'Home'
    source = client.get('/api/source', query_string={'name':project['documents'][0]}).json['text']
    assert post('/api/source', {'expected_revision': project['revision'], 'name':project['documents'][0], 'text':source.replace('Project workspace', 'Changed title')}).status_code == 200
    assert client.get('/api/state').json['pending_source'] is True
    assert client.application.extensions['workspace'].runtime.fx.evaluate('T("title", [])') == 'Project workspace'
    assert post('/api/restart', {}).json['pending_source'] is False
    assert client.application.extensions['workspace'].runtime.fx.evaluate('T("title", [])') == 'Changed title'


def test_standalone_component_preview(client, post):
    response = post('/api/component', {'name':'Header'})
    assert response.status_code == 200
    assert response.json['component_preview'] is True
    assert response.json['active_screen'] == 'Home'
    assert response.json['tree']['children'][0]['family'] == 'CanvasComponent'
    response = post('/api/screen', {'name': None})
    assert response.json['component_preview'] is False


def test_local_mutations_require_request_header(client):
    assert client.post('/api/restart', json={}).status_code == 403


@pytest.mark.parametrize('host', ['localhost', 'localhost:8765', '127.0.0.1', '127.0.0.1:8766'])
def test_loopback_hosts_allow_ui_api_and_mcp_connection(client, host):
    for path in ('/', '/api/project', '/api/ai-connection'):
        assert client.get(path, headers={'Host': host}).status_code == 200
    response = client.get('/api/ai-connection', headers={'Host': host})
    assert response.json['args'][3] == 'http://' + host
    assert client.post('/api/restart', json={}, headers={
        'Host': host, 'X-Emulator-Request': '1'}).status_code == 200


@pytest.mark.parametrize('host', [
    'attacker.invalid', 'attacker.invalid:8765', 'localhost.attacker.invalid',
    '127.0.0.1.attacker.invalid', '192.168.1.2', '[2001:db8::1]', '',
])
def test_untrusted_hosts_cannot_read_or_mutate_workspace(client, runtime, host):
    runtime.globals['host_guard_probe'] = 'preserve runtime'
    headers = {'Host': host, 'X-Emulator-Request': '1',
               'X-Forwarded-Host': 'localhost', 'Forwarded': 'host=localhost'}
    for path in ('/', '/api/project', '/api/ai-connection'):
        assert client.get(path, headers=headers).status_code == 400
    assert client.post('/api/restart', json={}, headers=headers).status_code == 400
    assert runtime.globals['host_guard_probe'] == 'preserve runtime'


def test_historical_results_separate(client):
    assert client.get('/api/checker').json['historical'] is True


def test_import_api_and_export(client, post):
    assert post('/api/import', {'text':'Screens:\n  Test: {}\n'}).status_code == 200
    assert client.get('/api/state').json['screen'] == 'Test'
    response = client.get('/api/export')
    assert response.status_code == 200
    with ZipFile(BytesIO(response.data)) as z:
        assert z.namelist() == ['Src/Pasted.pa.yaml']
