"""Shared AI operations, attachment identity, MCP schemas and real stdio workflows."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest
from werkzeug.serving import make_server

from powerapps_sim.application import Workspace
from powerapps_sim.authoring import RevisionConflict, data_revision, revision
from powerapps_sim.fixtures import forms_project
from powerapps_sim.mcp_server import BackendError, HeadlessBackend, HTTPBackend, local_url, create_server
from powerapps_sim.source import Project
from powerapps_sim.workflows import STARTER


@pytest.fixture
def workspace(tmp_path):
    p = forms_project(tmp_path / 'forms')
    w = Workspace(tmp_path, p.root)
    yield w
    w.runtime.close()


def call(w, operation, **arguments):
    return w.ai.call(operation, arguments, expected_project=str(w.project.root))


@contextmanager
def serving(app):
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_read_source_export_list_paging_and_detached_results(workspace):
    w = workspace
    description = call(w, 'describe_project')
    assert description['runtime_started'] and description['api_version'] == 1
    source = call(w, 'read_source', name='Src/forms.pa.yaml')
    assert source['text'] == w.project.documents['Src/forms.pa.yaml']
    assert 'Set(selectedId, 1)' in call(w, 'read_source', app_property='OnStart')['text']
    assert 'Forms:' in call(w, 'read_source', control_name='Forms')['text']
    listed = call(w, 'read_list', name='Drafts', limit=1)
    assert len(listed['rows']) == 1 and listed['next_offset'] == 1
    listed['definition']['fields']['Title']['type'] = 'boolean'
    assert w.runtime.store.definitions['Drafts']['fields']['Title']['type'] == 'string'
    exported = call(w, 'export_source')
    assert all(name.startswith('Src/') for name in exported['documents'])
    assert 'emulator.json' not in exported['documents']
    assert 'named' in call(w, 'read_analysis')


def test_pure_evaluation_preserves_state_and_errors(workspace):
    w = workspace
    w.runtime.state()
    w.runtime.event('Forms/DraftForm/TitleCard/TitleInput', 'OnChange', 'Unsaved fictional edit')
    before = deepcopy(w.runtime.control_state)
    data = data_revision(w.runtime.store)
    assert call(w, 'evaluate_formula', formula='Self.Text', scope='Forms/DraftForm/TitleCard/TitleInput')['value'] == 'Unsaved fictional edit'
    assert call(w, 'evaluate_formula', formula='Blank()')['value'] is None
    for formula in ('Set(selectedId, 2)', 'Patch(Drafts, Defaults(Drafts), {Title:"Forbidden", Amount:1})'):
        result = call(w, 'evaluate_formula', formula=formula)
        assert result['status'] == 'error' and result['value']['$error']
    assert call(w, 'evaluate_formula', formula='missing_name')['error_kind'] == 'Name'
    assert w.runtime.globals['selectedId'] == 1
    assert w.runtime.control_state == before and data_revision(w.runtime.store) == data
    assert call(w, 'read_runtime')['globals']['selectedId'] == 1


def test_runtime_observation_does_not_drain_queued_behaviors(workspace):
    w = workspace
    w.runtime.event_queue.append((w.runtime.global_refs['ChooseOther'], 'OnSelect', ()))
    call(w, 'read_runtime')
    call(w, 'read_diagnostics')
    assert len(w.runtime.event_queue) == 1 and w.runtime.globals['selectedId'] == 1


def test_historical_findings_remain_separate(workspace):
    w = workspace
    w.project.write_json('metadata/checker.json', {'runs':[{'results':[{'message':'Old missing name'}]}]})
    assert call(w, 'read_diagnostics')['diagnostics'] == []
    result = call(w, 'read_diagnostics', historical=True)
    assert result['category'] == 'historical' and result['checker']['runs']


@pytest.mark.parametrize('operation,arguments', [('_open', {}), ('read_source', {}),
    ('read_source', {'name':'../../secret.yaml'}), ('read_source', {'name':'Src/forms.pa.yaml', 'app_property':'OnStart'}),
    ('read_list', {'name':'Drafts','limit':True}), ('read_list', {'name':'Drafts','offset':-1}),
    ('evaluate_formula', {'formula':'true','scope':'nonexistent'}), ('describe_project', {'unexpected':1}),
    ('run_workflow', {'expected_revision':'x'}), ('read_diagnostics', {'historical':'true'})])
def test_invalid_operations_are_rejected(workspace, operation, arguments):
    with pytest.raises(ValueError):
        call(workspace, operation, **arguments)


def test_project_identity_required_on_writes_and_guarded_on_reads(workspace):
    w = workspace
    with pytest.raises(ValueError, match='expected_project'):
        w.ai.call('stage_change', {'expected_revision':revision(w.project.root)})
    with pytest.raises(RevisionConflict, match='different project'):
        w.ai.call('read_runtime', {}, expected_project='/different/project')


def test_combined_ai_changes_and_named_workflow_do_not_start_pending_source(workspace):
    w = workspace
    base = revision(w.project.root)
    definition = deepcopy(w.runtime.store.definitions['Drafts'])
    definition['fields']['Priority'] = {'type':'string','default':'Normal'}
    definition['mapping']['Priority'] = 'Project priority'
    source = w.project.documents['Src/forms.pa.yaml'].replace('Set(selectedId, 1)', 'Set(selectedId, 2)', 1)
    change = call(w, 'stage_change', expected_revision=base, sources={'Src/forms.pa.yaml':source}, lists={'Drafts':definition})
    scenario = {**deepcopy(STARTER), 'steps':[{'op':'assert','formula':'selectedId','expect':2},
        {'op':'assert','formula':"First(Drafts).'Project priority'",'expect':'Normal'}]}
    report = call(w, 'run_workflow', expected_revision=base, scenario=scenario, change_id=change['id'])
    assert report['status'] == 'passed' and w.runtime.globals['selectedId'] == 1
    assert call(w, 'read_workflow_report', run_id=report['id'])['steps'] == report['steps']
    names = call(w, 'list_workflows')['scenarios']
    named = call(w, 'run_workflow', expected_revision=base, scenario_file=names[0]['file'])
    assert named['status'] == 'passed'
    applied = call(w, 'apply_change', change_id=change['id'], expected_revision=base)
    assert w.runtime.globals['selectedId'] == 1 and w.runtime.pending_source
    assert not call(w, 'read_runtime')['running_source']['source_matches_saved']
    call(w, 'undo_change', change_id=change['id'], expected_revision=applied['after_revision'])
    assert revision(w.project.root) == base


def test_headless_owner_runs_no_startup_and_rejects_second_owner(tmp_path):
    p = forms_project(tmp_path / 'forms')
    backend = HeadlessBackend(p.root)
    try:
        assert backend.call('read_runtime')['globals'] == {}
        assert not backend.call('describe_project')['runtime_started']
        with pytest.raises(ValueError, match='workspace'):
            HeadlessBackend(p.root)
    finally:
        backend.close()
    backend = HeadlessBackend(p.root)
    backend.close()


@pytest.mark.parametrize('url', ['https://127.0.0.1:8765','http://example.com:8765','http://127.0.0.1/api',
    'http://user:pass@localhost:8765','http://127.0.0.1:8765/?x=1','http://127.0.0.1:8765/#data'])
def test_nonlocal_or_ambiguous_urls_are_rejected(url):
    with pytest.raises(ValueError):
        local_url(url)


def test_http_adapter_pins_project_and_reports_conflicts(app, monkeypatch):
    # Attachment must reach the local owner even when the host configures a proxy.
    monkeypatch.setenv('http_proxy', 'http://127.0.0.1:1')
    monkeypatch.setenv('no_proxy', '')
    w = app.extensions['workspace']
    with serving(app) as url:
        backend = HTTPBackend(url)
        assert backend.call('describe_project')['project_path'] == str(w.project.root)
        assert backend.call('read_list', name='Projects', limit=1)['total'] == 3
        with pytest.raises(RevisionConflict):
            backend.call('stage_change', expected_revision='stale', sources={'Src/demo.pa.yaml':'Screens: {}'})
        other = forms_project(w.root / 'other')
        w.open(other)
        with pytest.raises(RevisionConflict, match='different project'):
            backend.call('describe_project')
        with pytest.raises(RevisionConflict):
            HTTPBackend(url, expected_project='/wrong/project')
    from flask import Flask, redirect
    redirecting = Flask(__name__)
    calls = []

    @redirecting.post('/api/ai/describe_project')
    def redirected():
        calls.append(1)
        return redirect('http://127.0.0.1:1/unexpected', code=307)

    with serving(redirecting) as url:
        with pytest.raises(BackendError, match='no redirect was followed'):
            HTTPBackend(url)
    assert calls == [1]  # No follow or retry after the first request.


def test_http_dispatcher_requires_existing_local_header_and_project(app, client, post):
    w = app.extensions['workspace']
    assert client.post('/api/ai/describe_project', json={}).status_code == 403
    assert post('/api/ai/describe_project', {}) .status_code == 200
    assert post('/api/ai/stage_change', {'arguments':{'expected_revision':revision(w.project.root)}}).status_code == 400
    assert post('/api/ai/_private', {}).status_code == 400
    assert post('/api/ai/read_list', {'arguments':{'name':'Projects','limit':2}, 'expected_project':str(w.project.root)}).json['total'] == 3


def test_mcp_discovery_annotations_structured_results_and_resources(tmp_path):
    sdk = pytest.importorskip('mcp')
    backend = HeadlessBackend(forms_project(tmp_path / 'forms').root)
    async def exercise():
        async with sdk.Client(create_server(backend), raise_exceptions=True) as client:
            tools = (await client.list_tools()).tools
            assert len(tools) == 16 and all(t.output_schema for t in tools)
            by_name = {t.name:t for t in tools}
            assert by_name['read_source'].annotations.read_only_hint
            assert by_name['apply_change'].annotations.destructive_hint
            assert not by_name['run_workflow'].annotations.read_only_hint  # Creates a private report.
            result = await client.call_tool('describe_project')
            assert not result.is_error and not result.structured_content['runtime_started']
            result = await client.call_tool('read_list', {'name':'Drafts','limit':999})
            assert result.is_error
            result = await client.call_tool('evaluate_formula', {'formula':'Set(selectedId,2)'})
            assert not result.is_error and result.structured_content['status'] == 'error'
            assert result.structured_content['value']['$error']
            resources = (await client.list_resources()).resources
            assert len(resources) == 7
            resource = await client.read_resource('powerapps://project')
            assert json.loads(resource.contents[0].text)['project_path'] == backend.project
    try:
        asyncio.run(exercise())
    finally:
        backend.close()


def test_real_stdio_source_schema_workflow_apply_undo_and_shutdown(tmp_path):
    sdk = pytest.importorskip('mcp')
    from mcp.client.stdio import StdioServerParameters
    p = forms_project(tmp_path / 'forms')
    params = StdioServerParameters(command=sys.executable, args=['-m','powerapps_sim.mcp_server','--project',str(p.root)])
    async def exercise():
        async with sdk.Client(params, raise_exceptions=True) as client:
            described = (await client.call_tool('describe_project')).structured_content
            definition = (await client.call_tool('read_list', {'name':'Drafts'})).structured_content['definition']
            definition['fields']['Priority'] = {'type':'string','default':'Normal'}
            definition['mapping']['Priority'] = 'Project priority'
            source = (await client.call_tool('read_source', {'name':'Src/forms.pa.yaml'})).structured_content['text']
            source = source.replace('Set(selectedId, 1)', 'Set(selectedId, 2)', 1)
            change = (await client.call_tool('stage_change', {'expected_revision':described['revision'],
                'sources':{'Src/forms.pa.yaml':source},'lists':{'Drafts':definition}})).structured_content
            assert change['status'] == 'staged' and not change['diagnostics']
            scenario = {**deepcopy(STARTER), 'steps':[{'op':'assert','formula':'selectedId','expect':2},
                {'op':'assert','formula':"First(Drafts).'Project priority'",'expect':'Normal'}]}
            report = (await client.call_tool('run_workflow', {'expected_revision':described['revision'],
                'scenario':scenario,'change_id':change['id']})).structured_content
            assert report['status'] == 'passed'
            state = (await client.call_tool('read_runtime')).structured_content
            assert state['globals'] == {} and not state['started']
            bad = await client.call_tool('apply_change', {'change_id':change['id'],'expected_revision':'stale'})
            assert bad.is_error and 'Conflict' in bad.content[0].text
            applied = (await client.call_tool('apply_change', {'change_id':change['id'],'expected_revision':described['revision']})).structured_content
            assert applied['status'] == 'applied'
            undone = (await client.call_tool('undo_change', {'change_id':change['id'],'expected_revision':applied['after_revision']})).structured_content
            assert undone['status'] == 'undone'
    asyncio.run(exercise())
    # The subprocess emitted valid MCP framing and released its OS project lock.
    backend = HeadlessBackend(p.root)
    assert len(backend.call('read_list', name='Drafts')['rows']) == 2
    backend.close()


def test_real_stdio_http_attachment_shares_browser_owner(app):
    sdk = pytest.importorskip('mcp')
    from mcp.client.stdio import StdioServerParameters
    w = app.extensions['workspace']
    with serving(app) as url:
        params = StdioServerParameters(command=sys.executable, args=['-m','powerapps_sim.mcp_server','--url',url,'--expect-project',str(w.project.root)])
        async def exercise():
            async with sdk.Client(params, raise_exceptions=True) as client:
                result = (await client.call_tool('evaluate_formula', {'formula':'varLanguage'})).structured_content
                assert result['value'] == 'en' and result['started']
                workflows = (await client.call_tool('list_workflows')).structured_content
                base = (await client.call_tool('describe_project')).structured_content['revision']
                report = (await client.call_tool('run_workflow', {'expected_revision':base,
                    'scenario_file':workflows['scenarios'][0]['file']})).structured_content
                assert report['status'] == 'passed'
                assert w.runtime.globals['varLanguage'] == 'en' and w.runtime.active_screen == 'Home'
        asyncio.run(exercise())
