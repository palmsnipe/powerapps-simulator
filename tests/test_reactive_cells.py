"""Row lifetimes, shared defaults, actual input state, and read-only telemetry."""
from copy import deepcopy
import pytest
from powerapps_sim.authoring import revision,data_revision
from powerapps_sim.runtime import serial

@pytest.fixture
def workspace(tmp_path):
    from powerapps_sim.application import Workspace
    from powerapps_sim.fixtures import reactive_cells_project
    p=reactive_cells_project(tmp_path/'project');w=Workspace(tmp_path,p.root)
    yield w
    w.runtime.close()

def column(r,family,name):return r.refs['ReactiveLab/'+family+'/'+family+name]
def rows(r,family):return r.render(r.refs['ReactiveLab/'+family])['rows']
def states(r):return {key:rng.getstate() for key,rng in r.reactive.streams.items()}
def cells(r,family):return [[cell['text'] for cell in row['cells']] for row in rows(r,family)]

@pytest.mark.parametrize('mode',['float','decimal'])
@pytest.mark.parametrize('language',['en-CA','fr-CA'])
def test_row_formula_lifetimes_shared_form_defaults_and_workflow(workspace,mode,language):
    w=workspace;r=w.runtime;r.environment.update(number_mode=mode,language=language);r.restart();r.state()
    assert not r.diagnostics
    first={family:cells(r,family) for family in ('Classic','Grid')};input_=r.refs['ReactiveLab/Editor/AmountCard/AmountInput']
    default=input_.property('Text');before=states(r)
    r.event('ReactiveLab/Unrelated','OnSelect');r.state()
    assert before==states(r) and input_.property('Text')==default
    assert first=={family:cells(r,family) for family in first}
    r.store.patch('Cards',r.store.rows('Cards')[0],{'Amount':35});r.invalidate();r.state()
    for family in first:
        current=cells(r,family)
        assert current[0][1]==first[family][0][1] # Unread ThisItem: fixed per row.
        assert current[0][2]!=first[family][0][2]
        assert current[1:]==first[family][1:]
    scenario=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario']);scenario['environment'].update(number_mode=mode,language=language)
    before=(serial(w.ai.read_runtime()),revision(w.project.root),data_revision(r.store),states(r),r.reactive.describe())
    result=w.workflows.run(scenario,expected_revision=before[1])
    assert result['status']=='passed' and len(result['steps'])==17 and not result['diagnostics'],result['steps']
    assert before==(serial(w.ai.read_runtime()),revision(w.project.root),data_revision(r.store),states(r),r.reactive.describe())

@pytest.mark.parametrize('family',['Classic','Grid'])
def test_duplicate_rows_reorder_selection_and_row_errors(workspace,family):
    r=workspace.runtime;ref=r.refs['ReactiveLab/'+family]
    ref.control.properties['Items']='=Table({ID:1,Title:"duplicate",Amount:5},{ID:1,Title:"duplicate",Amount:5},{ID:2,Title:"other",Amount:8})';r.invalidate()
    original=cells(r,family)
    assert original[0][1]!=original[1][1]
    # Stable identity plus duplicate occurrence, across source order changes.
    ref.control.properties['Items']='=Table({ID:2,Title:"other",Amount:8},{ID:1,Title:"duplicate",Amount:5},{ID:1,Title:"duplicate",Amount:5})';r.invalidate()
    reordered=cells(r,family);assert reordered==[original[2],original[0],original[1]]
    c=column(r,family,'Roll');c.control.properties['Text']='=Rand()+If(ThisItem.ID=1,1/0,ThisItem.Amount)';r.invalidate()
    result=rows(r,family);assert not result[0]['cells'][2].get('error') and all(row['cells'][2].get('error') for row in result[1:])
    before=states(r);r.invalidate();rows(r,family);assert states(r)==before
    c.control.properties['Text']='=Text(ThisRecord.Amount+Rand(),"0.000000")';r.invalidate()
    healthy=cells(r,family);assert all(not row['cells'][2].get('error') for row in rows(r,family))
    r.invalidate();assert healthy==cells(r,family)

@pytest.mark.parametrize('family',['Classic','Grid'])
def test_cell_selection_exports_and_own_source_changes(workspace,family):
    r=workspace.runtime
    original=cells(r,family);c=column(r,family,'Fixed')
    if family=='Classic':
        from powerapps_sim.data_table import token
        r.event('ReactiveLab/Classic','OnSelect',{'index':1,'items_token':token(r.refs['ReactiveLab/Classic'])})
    else:
        from powerapps_sim.modern_grid import token
        r.event('ReactiveLab/Grid','OnChange',{'indices':[1],'items_token':token(r.refs['ReactiveLab/Grid'])})
    assert c.property('Text')==original[1][1]
    assert original==cells(r,family)
    c.control.properties['Text']='=Text(10+Rand(),"0.000000")';r.invalidate()
    changed=cells(r,family);assert changed[1][1]!=original[1][1]
    r.invalidate();assert changed==cells(r,family)


def test_gallery_decorations_aliases_are_stable_and_observed(workspace):
    r=workspace.runtime;gallery=r.refs['ReactiveLab/Decorations']
    initial=r.render(gallery)['rows'];before=states(r)
    r.invalidate();second=r.render(gallery)['rows'];assert [row['props'] for row in initial]==[row['props'] for row in second] and states(r)==before
    r.store.patch('Cards',r.store.rows('Cards')[0],{'Title':'Fictional changed'});r.invalidate()
    third=r.render(gallery)['rows']
    assert initial[0]['props']['TemplateFill']==third[0]['props']['TemplateFill']
    assert initial[0]['props']['ItemAccessibleLabel']!=third[0]['props']['ItemAccessibleLabel']
    assert [row['props'] for row in initial[1:]]==[row['props'] for row in third[1:]]


def test_form_random_item_default_user_draft_and_explicit_reset(workspace):
    r=workspace.runtime;r.state();form=r.refs['ReactiveLab/Editor'];input_=r.refs['ReactiveLab/Editor/AmountCard/AmountInput']
    default=input_.property('Text');r.event(input_.path,'OnChange','72');r.state()
    assert input_.property('Text')=='72' and form.property('Unsaved')
    r.event('ReactiveLab/Unrelated','OnSelect');r.state();assert input_.property('Text')=='72'
    r.event('ReactiveLab/Reset','OnSelect');r.state();assert input_.property('Text')==default and not form.property('Unsaved')
    r.event('ReactiveLab/RandomPick','OnSelect');r.state();item=form.property('Item');value=input_.property('Text');before=states(r)
    for _ in range(3):r.invalidate();r.state()
    assert item==form.property('Item') and value==input_.property('Text') and states(r)==before


def test_volatile_default_does_not_cache_user_value_or_read_unrelated_state(workspace):
    from powerapps_sim.source import Control
    r=workspace.runtime
    ctl=Control('RawInput','ModernNumberInput@1.1.2',{'Properties':{'Value':'=Rand()'}},'Src/reactive-cells.pa.yaml')
    ref=r.build(ctl,'ReactiveLab/RawInput');initial=ref.property('Value');before=states(r)
    r.event(ref.path,'OnChange',42);r.invalidate()
    assert ref.property('Value')==42
    assert before==states(r)
    ref.state['unrelated']='ignored';r.invalidate();assert ref.property('Value')==42 and states(r)==before
    r.reset_ref(ref);r.invalidate();assert ref.property('Value')==initial and states(r)==before


def test_read_only_dependencies_filters_pagination_reasons_and_detachment(workspace):
    w=workspace;r=w.runtime;r.state();snapshot=(states(r),serial(w.ai.read_runtime()),deepcopy(r.control_state),r.reactive.describe())
    report=w.ai.call('read_dependencies',{'query':'GridRoll','limit':1})
    assert report['total']>=3 and report['next_offset']==1
    assert len(report['rows'])==1 and report['rows'][0]['kind']=='row'
    assert report['rows'][0]['formula']=='=Text(ThisItem.Amount+Rand(),"0.000000")'
    assert isinstance(report['rows'][0]['value'],str)
    report['rows'][0]['dependencies'].append(['mutated']);report['rows'][0]['value']='mutated'
    result=w.ai.read_dependencies(query='GridRoll',offset=1,limit=1,include_values=False)
    assert len(result['rows'])==1 and 'value' not in result['rows'][0]
    assert snapshot==(states(r),serial(w.ai.read_runtime()),deepcopy(r.control_state),r.reactive.describe())
    r.store.patch('Cards',r.store.rows('Cards')[0],{'Amount':61});r.invalidate();r.state()
    changed=w.ai.read_dependencies(query='GridRoll')
    assert sum(row['evaluations']==2 for row in changed['rows'])==1
    assert any(row['reason']=='Input changed' and row['changed_input'][0]=='field' for row in changed['rows'])
    for args in ({'offset':True},{'offset':-1},{'limit':501},{'limit':0},{'query':None},{'include_values':'false'}):
        with pytest.raises(ValueError):w.ai.read_dependencies(**args)


def test_control_state_copy_detaches_observers_and_default_profile(workspace):
    r=workspace.runtime;ref=r.refs['ReactiveLab/Editor/AmountCard/AmountInput'];ref.property('Text')
    copied=deepcopy(r.control_state);assert copied==r.control_state
    assert all(type(value) is dict for value in copied.values())
    r.event(ref.path,'OnChange','55');assert copied!=r.control_state
    before=r.reactive.describe();r.environment['language']='fr-CA';r.invalidate();r.state()
    assert any(row['reason']=='Host profile changed' for row in r.reactive.describe()['rows'])


def test_read_dependency_http_is_readonly_and_limits(client,runtime):
    before=serial(runtime.globals),deepcopy(runtime.control_state),states(runtime)
    result=client.get('/api/dependencies?limit=1');assert result.status_code==200
    for query in ('limit=0','offset=-1','limit=501','limit=bad'):assert client.get('/api/dependencies?'+query).status_code==400
    assert before==(serial(runtime.globals),deepcopy(runtime.control_state),states(runtime))


def test_source_roundtrip_excludes_telemetry(workspace):
    from io import BytesIO
    from zipfile import ZipFile
    w=workspace;before=w.ai.export_source();w.runtime.state();w.ai.read_dependencies()
    with ZipFile(BytesIO(w.project.export())) as z:
        text=z.read('Src/reactive-cells.pa.yaml').decode()
    assert 'Rand()' in text and 'ThisItem.Amount' in text and 'ReactiveLab' in text
    assert 'row-input' not in text and 'evaluated_epoch' not in text and 'random_seed' not in text
    assert before==w.ai.export_source()

@pytest.mark.parametrize('kind',['ModernTabList@1.0.2','ModernRadio@1.0.0'])
def test_selector_row_scope_in_form_and_nested_record_scope(workspace,kind):
    from powerapps_sim.source import Control
    r=workspace.runtime;form=r.refs['ReactiveLab/Editor']
    ctl=Control('RowSelector',kind,{'Properties':{
        'Items':'=Table({ID:101,Title:"Fictional choice A"},{ID:102,Title:"Fictional choice B"})',
        'ItemDisplayText':'=ThisItem.Title & Text(With({Amount:7},ThisRecord.Amount)+Rand(),"0.000000")'}},'Src/reactive-cells.pa.yaml')
    ref=r.build(ctl,form.path+'/RowSelector',parent=form)
    initial=r.render(ref)['options'];before=states(r)
    assert initial[0]['label'].startswith('Fictional choice A7.') and initial[1]['label'].startswith('Fictional choice B7.')
    r.invalidate();assert initial==r.render(ref)['options'] and states(r)==before
    r.store.patch('Cards',r.store.rows('Cards')[0],{'Title':'Unrelated form record'});r.invalidate()
    assert initial==r.render(ref)['options'] and states(r)==before
    assert not r.diagnostics


def test_dependency_observation_preserves_queued_behavior_and_reports_source(workspace):
    r=workspace.runtime;r.state();r.fx.evaluate('Seeded');r.event_queue.append((r.refs['ReactiveLab/Unrelated'],'OnSelect',()))
    before=(states(r),len(r.event_queue),serial(r.globals),r.reactive.describe())
    result=workspace.ai.call('read_dependencies',{'query':'Seeded'})
    assert result['rows'] and all(row['source']=='Src/reactive-cells.pa.yaml' for row in result['rows'])
    assert any('Rand()' in row['formula'] for row in result['rows'])
    assert before==(states(r),len(r.event_queue),serial(r.globals),r.reactive.describe())


def test_real_attached_mcp_dependency_tool_and_resource_are_readonly(tmp_path):
    import asyncio,json,sys,threading
    sdk=pytest.importorskip('mcp')
    from mcp.client.stdio import StdioServerParameters
    from werkzeug.serving import make_server
    from powerapps_sim.fixtures import reactive_cells_project
    from powerapps_sim.web import create_app
    p=reactive_cells_project(tmp_path/'project');app=create_app(tmp_path/'workspace',p.root)
    w=app.extensions['workspace'];r=w.runtime;r.state()
    server=make_server('127.0.0.1',0,app,threaded=True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    before=(states(r),serial(w.ai.read_runtime()),r.reactive.describe(),revision(p.root),data_revision(r.store))
    params=StdioServerParameters(command=sys.executable,args=['-m','powerapps_sim.mcp_server','--url',f'http://127.0.0.1:{server.server_port}','--expect-project',str(p.root)])
    async def exercise():
        async with sdk.Client(params,raise_exceptions=True) as client:
            tool=next(tool for tool in (await client.list_tools()).tools if tool.name=='read_dependencies')
            assert tool.annotations.read_only_hint and not tool.annotations.destructive_hint
            report=(await client.call_tool('read_dependencies',{'query':'GridRoll','limit':1})).structured_content
            assert report['total']==3 and len(report['rows'])==1
            resource=await client.read_resource('powerapps://dependencies')
            assert json.loads(resource.contents[0].text)['coverage']=='Evaluated volatile rules and their consumers'
            error=await client.call_tool('read_dependencies',{'limit':501});assert error.is_error
    try:
        asyncio.run(exercise())
        assert before==(states(r),serial(w.ai.read_runtime()),r.reactive.describe(),revision(p.root),data_revision(r.store))
    finally:
        server.shutdown();thread.join(timeout=5);server.server_close();r.close()
