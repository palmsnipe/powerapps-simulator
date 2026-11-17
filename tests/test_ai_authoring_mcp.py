"""Exercise focused authoring over the real optional stdio MCP transport."""
import asyncio
from copy import deepcopy
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
            assert 'ModernDropdown@1.0.0, author Default' in tools['stage_control_edits'].description
            assert 'Default ="First"' in tools['stage_control_edits'].description
            assert not tools['run_workflows'].annotations.read_only_hint
            entry = tools['run_workflows'].input_schema['properties']['workflows']['items']['oneOf'][1]
            scenario_schema = entry['properties']['scenario']
            step_schema = scenario_schema['properties']['steps']['items']
            example, = step_schema['examples']
            assert example['selection'] == [1] and example['event'] == 'OnChange'
            selection_schema = step_schema['properties']['selection']
            assert selection_schema['type'] == 'array'
            assert selection_schema['items'] == {'type': 'integer', 'minimum': 0}
            assert tools['run_workflow'].input_schema['properties']['scenario']['anyOf'][0] == scenario_schema
            creation_workflows = tools['create_project'].input_schema['properties']['workflows']['anyOf'][0]
            assert creation_workflows['additionalProperties'] == scenario_schema
            described = await call('describe_project')
            discovered = await call('read_controls', query='Projects')
            assert any(c['path'] == 'Workspace/ProjectGallery' for c in discovered['controls'])
            inspected = await call('read_control', path='Workspace/ProjectForm')
            assert inspected['contract']['supported']
            schema = await call('read_list_schema', name='Projects')
            assert schema['definition']['fields']['Title']['maxLength'] == 80
            assert (await client.call_tool('read_controls', {'limit': True})).is_error
            owner = await call('read_runtime')
            unsupported = deepcopy(task['reference_edits'])
            dropdown = next(edit['control'] for edit in unsupported if edit.get('name') == 'StatusFilter')
            dropdown['Properties'].pop('Default')
            dropdown['Properties']['DefaultSelectedItems'] = '=["All"]'
            rejected_default = await call('stage_control_edits', expected_revision=described['revision'], edits=unsupported)
            assert any(finding['member'] == 'StatusFilter.DefaultSelectedItems'
                       and 'author Default for the initial selection' in finding['message']
                       for finding in rejected_default['diagnostics'])
            change = await call('stage_control_edits', expected_revision=described['revision'], edits=task['reference_edits'], strict=True)
            catalog = await call('list_workflows', include_scenarios=False)
            assert all('scenario' not in e and e['step_count'] > 0 for e in catalog['scenarios'])
            selection = {'format_version': 1, 'name': 'Select the second status', 'steps': [
                {**example, 'path': 'Workspace/StatusFilter'},
                {'op': 'assert', 'formula': 'StatusFilter.Selected.Value', 'expect': 'Draft'},
            ]}
            invalid = {**selection, 'steps': [
                {**selection['steps'][0], 'selection': 1}, selection['steps'][1],
            ]}
            rejected = await client.call_tool('run_workflows', {'expected_revision': described['revision'],
                'change_id': change['id'], 'workflows': [{'scenario': invalid}]})
            assert rejected.is_error and 'Workflow step 1' in rejected.content[0].text
            assert 'Use [1]' in rejected.content[0].text
            batch = await call('run_workflows', expected_revision=described['revision'], change_id=change['id'],
                               workflows=[*({'scenario_file': e['file']} for e in catalog['scenarios']),
                                          {'scenario': selection}])
            assert batch['passed'] == 5 and batch['status'] == 'passed'
            assert await call('read_runtime') == owner
            applied = await call('apply_change', change_id=change['id'], expected_revision=described['revision'])
            contract = await call('read_control', path='Workspace/StatusFilter')
            assert 'author Default for the initial selection' in contract['contract']['note']
            restarted = await call('restart_preview', expected_revision=applied['after_revision'])
            assert restarted['started'] and not restarted['diagnostics']
            assert (await call('evaluate_formula', formula='selectedId'))['value'] == 1
            await call('undo_change', change_id=change['id'], expected_revision=applied['after_revision'])
            assert (await call('describe_project'))['revision'] == described['revision']
    asyncio.run(exercise())
