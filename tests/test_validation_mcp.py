"""AI changes validation limits and component source through revision-checked staging."""
import asyncio
from copy import deepcopy
import sys
import pytest
from powerapps_sim.fixtures import validation_project
from powerapps_sim.source import load_yaml, dump_yaml


def test_mcp_validation_candidate_apply_and_undo(tmp_path):
    sdk = pytest.importorskip('mcp')
    from mcp.client.stdio import StdioServerParameters
    project = validation_project(tmp_path/'validation-sdk')
    async def exercise():
        params = StdioServerParameters(command=sys.executable, args=['-m','powerapps_sim.mcp_server','--project',str(project.root)])
        async with sdk.Client(params, raise_exceptions=True) as client:
            async def call(operation, **arguments):
                response = await client.call_tool(operation, arguments)
                assert not response.is_error, response.content
                return response.structured_content
            description = await call('describe_project')
            owner = await call('read_runtime')
            data = await call('read_list', name='Scores')
            source_names = ('Src/validation.pa.yaml','Src/Components/ScoreEditor.pa.yaml')
            originals = {name:(await call('read_source', name=name))['text'] for name in source_names}
            sources = {name:load_yaml(text) for name,text in originals.items()}
            for child in sources[source_names[0]]['Screens']['Home']['Children']:
                if 'Right' in child: child['Right']['Properties']['Seed'] = '=60'
            component = sources[source_names[1]]['ComponentDefinitions']['ScoreEditor']
            for child in component['Children']:
                if 'Feedback' in child: child['Feedback']['Properties']['Text'] = '=Coalesce(ScoreEditor.Message,"Within allowed range")'
            definition = deepcopy(data['definition'])
            definition['fields']['Percentage']['maximum'] = 75
            staged = await call('stage_change', expected_revision=description['revision'], strict=True,
                sources={name:dump_yaml(doc) for name,doc in sources.items()}, lists={'Scores':definition})
            scenario = deepcopy((await call('list_workflows'))['scenarios'][0]['scenario'])
            scenario['environment'] = {'language':'fr-CA','number_mode':'decimal','enum_mode':'strong'}
            for step in scenario['steps']:
                if step.get('op') == 'event' and step.get('value') == 100: step['value'] = 75
                if 'formula' in step:
                    step['formula'] = step['formula'].replace('Right.Candidate=80','Right.Candidate=60').replace('MaxValue,Percentage)=100','MaxValue,Percentage)=75').replace('Percentage=100','Percentage=75').replace('Percentage,100)','Percentage,75)')
            result = await call('run_workflow', scenario=scenario, change_id=staged['id'], expected_revision=description['revision'])
            assert result['status'] == 'passed' and len(result['steps']) == 24 and not result['diagnostics'], result['steps']
            assert await call('read_runtime') == owner
            assert (await call('read_list',name='Scores'))['rows'] == data['rows']
            applied = await call('apply_change', change_id=staged['id'], expected_revision=description['revision'])
            assert (await call('read_list',name='Scores'))['definition']['fields']['Percentage']['maximum'] == 75
            await call('undo_change', change_id=staged['id'], expected_revision=applied['after_revision'])
            for name,text in originals.items(): assert (await call('read_source',name=name))['text'] == text
            final = await call('describe_project')
            assert final['revision'] == description['revision'] and final['data_revision'] == description['data_revision']
            assert (await call('read_list',name='Scores'))['definition'] == data['definition']
    asyncio.run(exercise())
