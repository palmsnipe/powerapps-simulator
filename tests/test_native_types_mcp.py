"""A real MCP client edits native contracts and validates an isolated candidate."""
import asyncio
from copy import deepcopy
import sys
import pytest
from powerapps_sim.fixtures import native_types_project
from powerapps_sim.source import load_yaml, dump_yaml


def test_native_types_stdio_candidate_and_undo(tmp_path):
    sdk=pytest.importorskip('mcp')
    from mcp.client.stdio import StdioServerParameters
    project=native_types_project(tmp_path/'native-sdk')
    params=StdioServerParameters(command=sys.executable,args=['-m','powerapps_sim.mcp_server','--project',str(project.root)])
    async def exercise():
        async with sdk.Client(params,raise_exceptions=True) as client:
            async def call(operation,**arguments):
                response=await client.call_tool(operation,arguments)
                assert not response.is_error,response.content
                return response.structured_content
            state=await call('describe_project')
            catalog=await call('list_workflows');scenario=catalog['scenarios'][0]['scenario']
            app='Src/native-types.pa.yaml';master='Src/Components/NativeCard.pa.yaml'
            originals={name:(await call('read_source',name=name))['text'] for name in (app,master)}
            assert (await call('evaluate_formula',formula='Left.Total'))['type']['kind']=='Currency'
            assert (await call('evaluate_formula',formula='Left.Page'))['type']['kind']=='Screen'
            assert (await call('evaluate_formula',formula='Left.Clip'))['type']['kind']=='Media'
            owner=await call('read_runtime');deps=await call('read_dependencies')
            result=await call('run_workflow',expected_revision=state['revision'],scenario=scenario)
            assert result['status']=='passed' and len(result['steps'])==19 and not result['diagnostics']
            assert await call('read_runtime')==owner and await call('read_dependencies')==deps
            sources={name:load_yaml(text) for name,text in originals.items()}
            sources[master]['ComponentDefinitions']['NativeCard']['CustomProperties']['Multiply']['Parameters'][1]['factor']['Default']='=3'
            for child in sources[app]['Screens']['Home']['Children']:
                if 'Snapshot' in child:
                    child['Snapshot']['Properties']['OnSelect']=child['Snapshot']['Properties']['OnSelect'].replace('Callbacks:CountRows(history)', 'Callbacks:CountRows(history),Reviewed:"AI candidate"')
            definition=(await call('read_list',name='Snapshots'))['definition']
            definition['fields']['Reviewed']={'type':'string','default':'Pending'}
            definition['mapping']['Reviewed']='Review note'
            staged=await call('stage_change',expected_revision=state['revision'],sources={n:dump_yaml(src) for n,src in sources.items()},lists={'Snapshots':definition},strict=True)
            candidate=deepcopy(scenario);candidate['environment']={'number_mode':'decimal','language':'fr-CA','enum_mode':'strong'}
            for step in candidate['steps']:
                if 'formula' in step:step['formula']=step['formula'].replace('Left.Multiply(4)=8','Left.Multiply(4)=12').replace('multiplied=24','multiplied=36')
            candidate['steps'].append({'op':'assert','formula':'First(Snapshots).Reviewed="AI candidate"','expect':True})
            result=await call('run_workflow',expected_revision=state['revision'],change_id=staged['id'],scenario=candidate)
            assert result['status']=='passed' and len(result['steps'])==20 and not result['diagnostics'],result['steps']
            assert await call('read_runtime')==owner and await call('read_dependencies')==deps
            assert (await call('describe_project'))['data_revision']==state['data_revision']
            applied=await call('apply_change',change_id=staged['id'],expected_revision=state['revision'])
            assert (await call('read_list',name='Snapshots'))['definition']['mapping']['Reviewed']=='Review note'
            await call('undo_change',change_id=staged['id'],expected_revision=applied['after_revision'])
            for name,text in originals.items():assert (await call('read_source',name=name))['text']==text
            final=await call('describe_project')
            assert final['revision']==state['revision'] and final['data_revision']==state['data_revision']
    asyncio.run(exercise())
