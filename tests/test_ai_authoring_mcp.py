"""Exercise focused authoring over the real optional stdio MCP transport."""
import asyncio
import sys

import pytest

from powerapps_sim.fixtures import ai_development_project


def test_focused_tools_over_stdio(tmp_path):
    sdk = pytest.importorskip('mcp')
    from mcp.client.stdio import StdioServerParameters
    project = ai_development_project(tmp_path / 'app')
    task = project.read_json('benchmark.task.json', {})
    async def exercise():
        params = StdioServerParameters(command=sys.executable,
            args=['-m', 'powerapps_sim.mcp_server', '--project', str(project.root)])
        async with sdk.Client(params, raise_exceptions=True) as client:
            async def call(operation, **args):
                result = await client.call_tool(operation, args)
                assert not result.is_error, result.content
                return result.structured_content
            tools = {t.name: t for t in (await client.list_tools()).tools}
            assert tools['read_controls'].annotations.read_only_hint
            assert tools['restart_preview'].annotations.destructive_hint
            assert not tools['stage_control_edits'].annotations.read_only_hint
            assert not tools['run_workflows'].annotations.read_only_hint
            described = await call('describe_project')
            discovered = await call('read_controls', query='Projects')
            assert any(c['path'] == 'Workspace/ProjectGallery' for c in discovered['controls'])
            inspected = await call('read_control', path='Workspace/ProjectForm')
            assert inspected['contract']['supported']
            schema = await call('read_list_schema', name='Projects')
            assert schema['definition']['fields']['Title']['maxLength'] == 80
            assert (await client.call_tool('read_controls', {'limit': True})).is_error
            owner = await call('read_runtime')
            change = await call('stage_control_edits', expected_revision=described['revision'], edits=task['reference_edits'], strict=True)
            catalog = await call('list_workflows', include_scenarios=False)
            assert all('scenario' not in e and e['step_count'] > 0 for e in catalog['scenarios'])
            batch = await call('run_workflows', expected_revision=described['revision'], change_id=change['id'],
                               workflows=[{'scenario_file': e['file']} for e in catalog['scenarios']])
            assert batch['passed'] == 4 and batch['status'] == 'passed'
            assert await call('read_runtime') == owner
            applied = await call('apply_change', change_id=change['id'], expected_revision=described['revision'])
            restarted = await call('restart_preview', expected_revision=applied['after_revision'])
            assert restarted['started'] and not restarted['diagnostics']
            assert (await call('evaluate_formula', formula='selectedId'))['value'] == 1
            await call('undo_change', change_id=change['id'], expected_revision=applied['after_revision'])
            assert (await call('describe_project'))['revision'] == described['revision']
    asyncio.run(exercise())
