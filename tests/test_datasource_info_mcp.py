"""A mapped-column/schema edit through the real optional MCP transport."""
import asyncio
from copy import deepcopy
import sys
import pytest
from powerapps_sim.fixtures import metadata_project


def test_mcp_metadata_candidate_and_undo(tmp_path):
    sdk = pytest.importorskip('mcp')
    from mcp.client.stdio import StdioServerParameters
    project = metadata_project(tmp_path/'metadata-sdk')
    async def exercise():
        params = StdioServerParameters(command=sys.executable,args=['-m','powerapps_sim.mcp_server','--project',str(project.root)])
        async with sdk.Client(params,raise_exceptions=True) as client:
            async def call(operation,**arguments):
                response = await client.call_tool(operation,arguments)
                assert not response.is_error, response.content
                return response.structured_content
            owner = await call('read_runtime')
            description = await call('describe_project')
            data = await call('read_list',name='Scores')
            name = 'Src/validation.pa.yaml'
            original = (await call('read_source',name=name))['text']
            source = original.replace('Completion percent','Progress score').replace('Seed: =80','Seed: =60')
            definition = deepcopy(data['definition'])
            definition['mapping']['Percentage'] = 'Progress score'
            definition['fields']['Percentage']['maximum'] = 75
            staged = await call('stage_change',expected_revision=description['revision'],strict=True,
                sources={name:source},lists={'Scores':definition})
            scenario = deepcopy((await call('list_workflows'))['scenarios'][0]['scenario'])
            scenario['environment'] = {'language':'fr-CA','number_mode':'decimal','enum_mode':'strong'}
            for step in scenario['steps']:
                if step.get('op') == 'event' and step.get('value') == 100: step['value'] = 75
                if 'formula' in step:
                    step['formula'] = step['formula'].replace('Completion percent','Progress score').replace('Right.Candidate=80','Right.Candidate=60').replace('MaxValue,Percentage)=100','MaxValue,Percentage)=75').replace('Percentage=100','Percentage=75').replace('Percentage,100)','Percentage,75)')
            result = await call('run_workflow',scenario=scenario,change_id=staged['id'],expected_revision=description['revision'])
            assert result['status'] == 'passed' and len(result['steps']) == 30 and not result['diagnostics'], ([step for step in result['steps'] if step['status'] != 'passed'],result['diagnostics'])
            assert await call('read_runtime') == owner
            assert (await call('read_list',name='Scores')) == data
            applied = await call('apply_change',change_id=staged['id'],expected_revision=description['revision'])
            evaluated = await call('evaluate_formula',formula='DataSourceInfo(Scores,DataSourceInfo.DisplayName,Percentage)')
            assert evaluated['status'] == 'ok' and evaluated['value'] == 'Progress score'
            await call('undo_change',change_id=staged['id'],expected_revision=applied['after_revision'])
            assert (await call('read_source',name=name))['text'] == original
            assert (await call('read_list',name='Scores')) == data
            final = await call('describe_project')
            assert final['revision'] == description['revision'] and final['data_revision'] == description['data_revision']
    asyncio.run(exercise())
