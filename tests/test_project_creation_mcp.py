"""Real stdio and HTTP transport for create-project binding and follow-up authoring."""
import asyncio
import sys
import threading
from urllib.parse import quote

import pytest
from werkzeug.serving import make_server

from powerapps_sim.ai_service import OPERATIONS
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
            assert set(tools) == set(OPERATIONS) and tools['create_project'].annotations.destructive_hint
            assert tools['open_project'].annotations.destructive_hint
            assert tools['create_project'].input_schema['properties']['records']['anyOf'][0]['type'] == 'object'
            create_sources = tools['create_project'].input_schema['properties']['sources']
            stage_sources = tools['stage_change'].input_schema['properties']['sources']
            sample, = create_sources['examples']
            assert stage_sources['examples'] == [sample] and '>-' in create_sources['description']
            source_file = 'Src/Main.pa.yaml'
            broken = {source_file: sample[source_file].replace('OnSelect: >-\n              ', 'OnSelect: ')}
            assert broken != sample
            rejection = await client.call_tool('create_project', {'name': 'bad-yaml', 'sources': broken})
            assert rejection.is_error and source_file in rejection.content[0].text
            assert 'block scalar' in rejection.content[0].text and not (root / 'bad-yaml').exists()
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
            rejected_stage = await client.call_tool('stage_change', {
                'expected_revision': created['revision'], 'sources': broken,
            })
            assert rejected_stage.is_error and 'block scalar' in rejected_stage.content[0].text
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
            second = await call('create_project', name='second', expected_revision=applied['after_revision'], sources=sample)
            assert (await call('describe_project'))['project_path'] == second['project_path']
            button = await call('read_control', path='Main/SampleButton')
            assert button['definition']['Properties']['OnSelect'] == '=Set(settings, {Enabled: true})'
            listing = await call('list_projects')
            assert listing['active_project_id'] == 'second'
            assert {p['id'] for p in listing['projects']} == {'scratch', 'second'}
            reopened = await call('open_project', project_id='scratch')
            assert reopened['project_path'] == created['project_path'] and not reopened['runtime_started']
            suite = await call('validate_workflows', expected_revision=reopened['revision'])
            assert suite['status'] == 'passed' and [r['file'] for r in suite['runs']] == ['count.workflow.json']
            repaired = await call('stage_change', expected_revision=reopened['revision'],
                expected_workflow_revision=reopened['workflow_revision'],
                workflows={'count.workflow.json': {'format_version': 1, 'name': 'Check the seeded record', 'steps': [
                    {'op': 'assert', 'formula': 'First(Projects).Title', 'expect': 'Fictional example'}]}})
            candidate = await call('validate_workflows', expected_revision=reopened['revision'], change_id=repaired['id'])
            assert candidate['status'] == 'passed' and candidate['runs'][0]['name'] == 'Check the seeded record'
            applied = await call('apply_change', expected_revision=reopened['revision'], change_id=repaired['id'])
            saved = await call('validate_workflows', expected_revision=applied['after_revision'])
            assert saved['status'] == 'passed' and saved['workflow_revision'] == applied['after_workflow_revision']
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
        connection = client.get('/api/ai-connection', base_url=url).json
        assert connection['args'][-2:] == ['--url', url]
        assert connection['project_path'] == str(tmp_path / 'scratch')
        assert client.get('/api/state').json['tree']['children'][0]['props']['Text'] == 'Created over MCP'
        # Direct HTTP calls still require the existing project-identity/header rules.
        assert client.post('/api/ai/create_project', json={'arguments': {'name': 'no-header'}}).status_code == 403
        response = client.post('/api/ai/create_project', json={'arguments': {'name': 'no-identity'}},
                               headers={'X-Emulator-Request': '1'})
        assert response.status_code == 400 and not (tmp_path / 'no-identity').exists()
        stale_browser = client.post('/api/restart', json={}, headers={
            'X-Emulator-Request': '1', 'X-Emulator-Project': quote(str(initial.root))})
        assert stale_browser.status_code == 409
        assert other.call('list_projects')['active_project_id'] == 'scratch'
        with pytest.raises(ValueError, match='workspace'):
            other.call('open_project', project_id='../old')
        assert client.get('/api/project').json['project_path'] == str(tmp_path / 'scratch')

        sdk = pytest.importorskip('mcp')
        from mcp.client.stdio import StdioServerParameters

        async def exercise():
            params = StdioServerParameters(command=connection['command'], args=connection['args'], cwd=str(tmp_path))
            async with sdk.Client(params, raise_exceptions=True) as mcp:
                assert client.get('/api/session').json['mcp_attached'] == 1
                result = await mcp.call_tool('open_project', {'project_id': 'old'})
                assert not result.is_error and result.structured_content['project_path'] == str(initial.root)
                assert not result.structured_content['runtime_started']
                assert client.get('/api/project').json['project_path'] == str(initial.root)
                with pytest.raises(RevisionConflict, match='different project'):
                    creator.call('describe_project')
                assert creator.call('open_project', project_id='old')['project_path'] == str(initial.root)
                result = await mcp.call_tool('describe_project')
                assert result.structured_content['project_path'] == str(initial.root)
                result = await mcp.call_tool('open_project', {'project_id': 'scratch'})
                assert not result.is_error and result.structured_content['project_path'] == created['project_path']
                assert (await mcp.call_tool('describe_project')).structured_content['title'] == 'Created over MCP'
                assert client.get('/api/session').json['mcp_attached'] == 1

        asyncio.run(exercise())
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        workspace.runtime.close()
