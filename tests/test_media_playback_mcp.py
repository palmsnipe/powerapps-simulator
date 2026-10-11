"""Real MCP transport stages a playback callback and mapped SQLite field."""
import asyncio
from copy import deepcopy
import sys
import pytest
from powerapps_sim.fixtures import media_playback_project
from powerapps_sim.source import load_yaml,dump_yaml

def test_playback_stdio_candidate_and_undo(tmp_path):
    sdk=pytest.importorskip('mcp')
    from mcp.client.stdio import StdioServerParameters
    project=media_playback_project(tmp_path/'playback-sdk')
    params=StdioServerParameters(command=sys.executable,args=['-m','powerapps_sim.mcp_server','--project',str(project.root)])
    async def exercise():
        async with sdk.Client(params,raise_exceptions=True) as client:
            async def call(operation,**arguments):
                response=await client.call_tool(operation,arguments)
                assert not response.is_error,response.content
                return response.structured_content
            state=await call('describe_project');scenario=(await call('list_workflows'))['scenarios'][0]['scenario']
            owner=await call('read_runtime');deps=await call('read_dependencies')
            result=await call('run_workflow',expected_revision=state['revision'],scenario=scenario)
            assert result['status']=='passed' and len(result['steps'])==27 and not result['diagnostics']
            assert await call('read_runtime')==owner and await call('read_dependencies')==deps
            app='Src/media-playback.pa.yaml';master='Src/Components/MediaPanel.pa.yaml'
            originals={n:(await call('read_source',name=n))['text'] for n in (app,master)}
            sources={n:load_yaml(t) for n,t in originals.items()}
            for child in sources[app]['Screens']['Home']['Children']:
                if 'Save' in child:child['Save']['Properties']['OnSelect']=child['Save']['Properties']['OnSelect'].replace('Callbacks:CountRows(history)','Callbacks:CountRows(history),Reviewed:"AI playback candidate"')
            for child in sources[master]['ComponentDefinitions']['MediaPanel']['Children']:
                if 'Player' in child:child['Player']['Properties']['OnEnd']='=MediaPanel.Changed("finished",Self.Time)'
            definition=(await call('read_list',name='Snapshots'))['definition']
            definition['fields']['Reviewed']={'type':'string','default':'Pending'};definition['mapping']['Reviewed']='Review note'
            staged=await call('stage_change',expected_revision=state['revision'],sources={n:dump_yaml(s) for n,s in sources.items()},lists={'Snapshots':definition},strict=True)
            candidate=deepcopy(scenario);candidate['environment']={'number_mode':'decimal','language':'fr-CA','enum_mode':'strong'}
            for step in candidate['steps']:
                if 'formula'in step:step['formula']=step['formula'].replace('Last(history).Phase="end"','Last(history).Phase="finished"')
            candidate['steps'].append({'op':'assert','formula':'First(Snapshots).Reviewed="AI playback candidate"','expect':True})
            result=await call('run_workflow',expected_revision=state['revision'],change_id=staged['id'],scenario=candidate)
            assert result['status']=='passed' and len(result['steps'])==28 and not result['diagnostics'],result
            assert await call('read_runtime')==owner and await call('read_dependencies')==deps
            applied=await call('apply_change',change_id=staged['id'],expected_revision=state['revision'])
            assert (await call('read_list',name='Snapshots'))['definition']['mapping']['Reviewed']=='Review note'
            await call('undo_change',change_id=staged['id'],expected_revision=applied['after_revision'])
            for n,t in originals.items():assert (await call('read_source',name=n))['text']==t
            final=await call('describe_project')
            assert final['revision']==state['revision'] and final['data_revision']==state['data_revision']
    asyncio.run(exercise())
