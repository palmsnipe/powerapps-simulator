import asyncio
import sys

import pytest

from powerapps_sim.fixtures import component_feedback_project
from powerapps_sim.source import load_yaml, dump_yaml


def test_stdio_feedback_workflow_and_candidate_preserve_owner(tmp_path):
    sdk = pytest.importorskip('mcp')
    from mcp.client.stdio import StdioServerParameters
    p = component_feedback_project(tmp_path / 'sdk')

    async def exercise():
        params = StdioServerParameters(command=sys.executable,
            args=['-m', 'powerapps_sim.mcp_server', '--project', str(p.root)])
        async with sdk.Client(params, raise_exceptions=True) as client:
            assert len((await client.list_tools()).tools) == 16
            assert len((await client.list_resources()).resources) == 7

            async def call(operation, **arguments):
                result = await client.call_tool(operation, arguments)
                assert not result.is_error, result.content
                return result.structured_content

            description = await call('describe_project')
            owner = await call('read_runtime')
            name = 'Src/component-feedback.pa.yaml'
            original = (await call('read_source', name=name))['text']
            source = load_yaml(original)
            source['Screens']['Home']['Children'][0]['Heading']['Properties']['Text'] = '="Component callback recovery"'
            staged = await call('stage_change', expected_revision=description['revision'], strict=True,
                sources={name: dump_yaml(source)})
            scenario = (await call('list_workflows'))['scenarios'][0]['scenario']
            scenario['environment'] = {'language': 'fr-CA', 'number_mode': 'decimal'}
            report = await call('run_workflow', scenario=scenario, change_id=staged['id'], expected_revision=description['revision'])
            assert report['status'] == 'passed' and len(report['steps']) == 23
            assert len(report['diagnostics']) == 1 and report['diagnostics'][0]['kind'] == 'Cycle'
            assert await call('read_runtime') == owner
            assert (await call('read_source', name=name))['text'] == original
            applied = await call('apply_change', change_id=staged['id'], expected_revision=description['revision'])
            await call('undo_change', change_id=staged['id'], expected_revision=applied['after_revision'])
            assert (await call('read_source', name=name))['text'] == original
            final = await call('describe_project')
            assert final['revision'] == description['revision']
            assert final['data_revision'] == description['data_revision']

    asyncio.run(exercise())
