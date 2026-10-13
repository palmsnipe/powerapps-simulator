"""Real stdio and HTTP transport for create-project binding and follow-up authoring."""
import asyncio
import sys
import threading

import pytest
from werkzeug.serving import make_server

from powerapps_sim.authoring import RevisionConflict
from powerapps_sim.fixtures import forms_project
from powerapps_sim.mcp_server import HTTPBackend
from powerapps_sim.web import create_app


def test_empty_workspace_real_stdio_create_schema_records_workflows_and_continue(tmp_path):
    sdk = pytest.importorskip('mcp')
    from mcp.client.stdio import StdioServerParameters
    root = tmp_path / 'workspace'
    async def exercise():
        params = StdioServerParameters(command=sys.executable,
            args=['-m', 'powerapps_sim.mcp_server', '--workspace', str(root)])
        async with sdk.Client(params, raise_exceptions=True) as client:
            async def call(operation, **arguments):
                result = await client.call_tool(operation, arguments)
                assert not result.is_error, result.content
                return result.structured_content
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            assert len(tools) == 23 and tools['create_project'].annotations.destructive_hint
            assert tools['create_project'].input_schema['properties']['records']['anyOf'][0]['type'] == 'object'
            assert (await call('describe_project'))['project_path'] is None
            assert (await client.call_tool('read_control', {'path': 'Main'})).is_error
            # SDK validation rejects coerced booleans/dimensions before any publication.
            assert (await client.call_tool('create_project', {'name': 'bad', 'strict': 'true'})).is_error
            assert (await client.call_tool('create_project', {'name': 'bad', 'viewport': {'width': True, 'height': 600}})).is_error
            created = await call('create_project', name='scratch', title='Built from scratch',
                lists={'Projects': {'fields': {'ID': {'type': 'integer'}, 'Title': {'type': 'string'}}, 'required': ['Title']}},
                records={'Projects': [{'ID': 1, 'Title': 'Fictional example'}]},
                workflows={'count.workflow.json': {'format_version': 1, 'name': 'Seeded count', 'steps': [
                    {'op': 'assert', 'formula': 'CountRows(Projects)', 'expect': 1}, {'op': 'diagnostics', 'expect': 0}]}})
            assert created['project_path'] == str(root / 'scratch')
            assert not created['runtime_started'] and created['sample_record_counts'] == {'Projects': 1}
            assert (await call('read_list', name='Projects'))['rows'][0]['Title'] == 'Fictional example'
            assert (await call('describe_project'))['project_path'] == created['project_path']
            staged = await call('stage_control_edits', expected_revision=created['revision'], strict=True,
                edits=[{'op': 'set_property', 'path': 'Main/Title', 'property': 'Text', 'value': '=First(Projects).Title'}])
            batch = await call('run_workflows', expected_revision=created['revision'], change_id=staged['id'],
                workflows=[{'scenario_file': 'count.workflow.json'}])
            assert batch['status'] == 'passed'
            applied = await call('apply_change', expected_revision=created['revision'], change_id=staged['id'])
            assert (await call('restart_preview', expected_revision=applied['after_revision']))['started']
            assert (await call('evaluate_formula', formula='Title.Text'))['value'] == 'Fictional example'
            assert 'First(Projects)' in (await call('export_source'))['documents']['Src/App.pa.yaml']
            # Further creation is revision-guarded and explicitly rebinds the same client.
            assert (await client.call_tool('create_project', {'name': 'second'})).is_error
            second = await call('create_project', name='second', expected_revision=applied['after_revision'])
            assert (await call('describe_project'))['project_path'] == second['project_path']
    asyncio.run(exercise())
    assert (root / 'scratch/tests/count.workflow.json').exists() and not (root / 'demo').exists()


def test_http_create_rebinds_caller_other_connections_remain_pinned_and_browser_sees_project(tmp_path):
    initial = forms_project(tmp_path / 'old')
    app = create_app(tmp_path, initial.root)
    workspace = app.extensions['workspace']
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f'http://127.0.0.1:{server.server_port}'
        creator = HTTPBackend(url, expected_project=str(initial.root))
        other = HTTPBackend(url, expected_project=str(initial.root))
        base = creator.call('describe_project')['revision']
        with pytest.raises(RevisionConflict):
            creator.call('create_project', name='scratch', expected_revision='stale')
        assert creator.project == str(initial.root)
        created = creator.call('create_project', name='scratch', title='Created over MCP', expected_revision=base)
        assert creator.project == created['project_path'] == str(tmp_path / 'scratch')
        assert not creator.call('describe_project')['runtime_started']
        creator.call('restart_preview', expected_revision=created['revision'])
        assert creator.call('evaluate_formula', formula='Title.Text')['value'] == 'Created over MCP'
        with pytest.raises(RevisionConflict, match='different project'):
            other.call('describe_project')
        with pytest.raises(RevisionConflict):
            other.call('create_project', name='wrong', expected_revision=base)
        assert not (tmp_path / 'wrong').exists()
        client = app.test_client()
        assert any(p['id'] == 'scratch' for p in client.get('/api/projects').json)
        assert client.get('/api/project').json['project_path'] == str(tmp_path / 'scratch')
        assert client.get('/api/ai-connection').json['args'][-1] == str(tmp_path / 'scratch')
        assert client.get('/api/state').json['tree']['children'][0]['props']['Text'] == 'Created over MCP'
        # Direct HTTP calls still require the existing project-identity/header rules.
        assert client.post('/api/ai/create_project', json={'arguments': {'name': 'no-header'}}).status_code == 403
        response = client.post('/api/ai/create_project', json={'arguments': {'name': 'no-identity'}},
                               headers={'X-Emulator-Request': '1'})
        assert response.status_code == 400 and not (tmp_path / 'no-identity').exists()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        workspace.runtime.close()
