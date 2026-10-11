import asyncio
from copy import deepcopy
import sys
import pytest
from powerapps_sim.fixtures import canvas_scalars_project
from powerapps_sim.source import load_yaml,dump_yaml


def test_mcp_canvas_scalars_candidate_apply_and_undo(tmp_path):
    sdk=pytest.importorskip('mcp')
    from mcp.client.stdio import StdioServerParameters
    project=canvas_scalars_project(tmp_path/'canvas-scalars-sdk')
    async def exercise():
        params=StdioServerParameters(command=sys.executable,args=['-m','powerapps_sim.mcp_server','--project',str(project.root)])
        async with sdk.Client(params,raise_exceptions=True) as client:
            async def call(operation,**arguments):
                result=await client.call_tool(operation,arguments)
                assert not result.is_error,result.content
                return result.structured_content
            description=await call('describe_project');owner=await call('read_runtime');data=await call('read_list',name='Plans')
            names=('Src/canvas-scalars.pa.yaml','Src/Components/ScalarPanel.pa.yaml')
            originals={n:(await call('read_source',name=n))['text'] for n in names}
            sources={n:load_yaml(text) for n,text in originals.items()}
            for child in sources[names[0]]['Screens']['Home']['Children']:
                if 'Heading' in child:child['Heading']['Properties']['Text']='="Native sliders and switches"'
            for child in sources[names[1]]['ComponentDefinitions']['ScalarPanel']['Children']:
                if 'EnabledToggle' in child:child['EnabledToggle']['Properties']['ToggleSize']='=44'
            definition=deepcopy(data['definition']);definition['fields']['Title']['maxLength']=40
            staged=await call('stage_change',expected_revision=description['revision'],strict=True,sources={n:dump_yaml(doc) for n,doc in sources.items()},lists={'Plans':definition})
            scenario=deepcopy((await call('list_workflows'))['scenarios'][0]['scenario'])
            scenario['environment']={'language':'fr-CA','number_mode':'decimal','enum_mode':'strong'}
            result=await call('run_workflow',scenario=scenario,change_id=staged['id'],expected_revision=description['revision'])
            assert result['status']=='passed' and len(result['steps'])==29 and not result['diagnostics'],result
            assert await call('read_runtime')==owner and await call('read_list',name='Plans')==data
            applied=await call('apply_change',change_id=staged['id'],expected_revision=description['revision'])
            assert (await call('read_list',name='Plans'))['definition']['fields']['Title']['maxLength']==40
            await call('undo_change',change_id=staged['id'],expected_revision=applied['after_revision'])
            for n,text in originals.items():assert (await call('read_source',name=n))['text']==text
            assert await call('read_list',name='Plans')==data
            final=await call('describe_project')
            assert final['revision']==description['revision'] and final['data_revision']==description['data_revision']
    asyncio.run(exercise())
