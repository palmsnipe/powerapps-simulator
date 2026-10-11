"""ListBox contracts, server-owned ranges, scoped callbacks and form persistence."""
from copy import deepcopy
import pytest
from powerapps_sim.fixtures import listbox_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.syntax import FxError
from powerapps_sim.listbox import token
L='ListBoxLab/LeftPicker/Pick';R='ListBoxLab/RightPicker/Pick';F='ListBoxLab/DraftForm/TopicCard/TopicInput'
@pytest.fixture
def r(tmp_path):
    value=Runtime(listbox_project(tmp_path/'list'));value.restart();value.state();assert not value.diagnostics
    yield value
    value.close()
def op(r,index=None,operation='toggle',path=L):
    value={'operation':operation,'option_token':token(r.refs[path])}
    if index is not None:value['index']=index
    r.event(path,'OnChange',value)
def prop(r,name,value,path=L):
    ref=r.refs[path];ref.control=deepcopy(ref.control);ref.control.properties[name]=value;r.invalidate()
@pytest.mark.parametrize('family',['ListBox','Classic/ListBox'])
def test_version_alias_outputs_and_single_default(r,family):
    r.refs[L].control=deepcopy(r.refs[L].control);r.refs[L].control.kind=family+'@2.2.0';r.invalidate()
    assert r.refs[L].family==family
    assert r.refs[L].property('Selected')['ID']==1
    assert r.refs[L].property('SelectedText')=='Fictional Bridge'
    assert r.refs[L].property('SelectedItemsText')==[{'Value':'Fictional Bridge'}]
def test_source_order_latest_clicked_and_callbacks(r):
    op(r,5);op(r,2)
    assert [v['ID'] for v in r.refs[L].property('SelectedItems')]==[1,3,6]
    assert r.fx.evaluate('LeftPicker.Latest.ID')==3
    assert r.fx.evaluate('LeftPicker.Touches')==2
    assert r.fx.evaluate('CountRows(LeftPicker.History)')==2
    assert r.fx.evaluate('RightPicker.Latest.ID')==8
    op(r,2);assert r.fx.evaluate('LeftPicker.Latest.ID')==6
    assert r.refs[L].property('SelectedItemsText')[-1]=={'Value':'Fictional Housing'}
def test_server_anchor_range_clear_and_select_all(r):
    op(r,2,'replace');op(r,5,'range')
    assert [v['ID'] for v in r.refs[L].property('SelectedItems')]==[3,4,5,6]
    assert r.fx.evaluate('LeftPicker.Latest.ID')==6
    op(r,operation='all');assert len(r.refs[L].property('SelectedItems'))==8
    op(r,operation='clear');assert r.refs[L].property('Selected') is None
    assert r.refs[L].property('SelectedText')==''
    assert r.refs[L].property('SelectedItemsText')==[]
def test_same_selection_fires_only_onselect(r):
    r.event(L,'OnChange',selection=[0]);r.event(L,'OnChange',selection=[0])
    assert not r.collections['events'] and r.fx.evaluate('LeftPicker.Touches')==2
    r.fx.evaluate('Select(Pick)',r.refs[L].parent.children[0].context(True));r.drain_events()
    assert r.fx.evaluate('LeftPicker.Touches')==3

def test_reset_default_change_and_single_mode_reactive_outputs(r):
    op(r,4);prop(r,'Default','="Fictional Culture"')
    assert r.refs[L].property('SelectedItemsText')==[{'Value':'Fictional Culture'}]
    assert r.refs[L].property('Selected')['ID']==4
    op(r,6);prop(r,'SelectMultiple','=false')
    assert len(r.refs[L].property('SelectedItems'))==1

def test_component_reset_epoch_and_other_instance_state(r):
    op(r,2);op(r,3,path=R);stale={'operation':'toggle','index':1,'option_token':token(r.refs[L])}
    r.event('ListBoxLab/ResetLeft','OnSelect')
    with pytest.raises(ValueError,match='changed'):r.event(L,'OnChange',stale)
    assert r.fx.evaluate('LeftPicker.Latest.ID')==1 and r.fx.evaluate('RightPicker.Latest.ID')==4
    assert r.fx.evaluate('LeftPicker.Touches')==0 and r.fx.evaluate('CountRows(LeftPicker.History)')==0
@pytest.mark.parametrize('mode',['Disabled','View'])
def test_modes_block_events_and_keep_state(r,mode):
    prop(r,'DisplayMode','=DisplayMode.'+mode);before=deepcopy(r.control_state)
    op(r,3);r.event(L,'OnSelect')
    assert r.control_state==before
@pytest.mark.parametrize('index',[-1,999,True,'1',None])
def test_invalid_index_is_atomic(r,index):
    before=deepcopy(r.control_state)
    with pytest.raises(ValueError):op(r,index)
    assert r.control_state==before
@pytest.mark.parametrize('selection',[[0,0],[True],[-1],[99],'x'])
def test_invalid_direct_selection_is_atomic(r,selection):
    before=deepcopy(r.control_state)
    with pytest.raises(ValueError):r.event(L,'OnChange',selection=selection)
    assert r.control_state==before

def test_queued_operations_share_source_token_but_stale_rows_and_columns_reject(r):
    stale={'operation':'toggle','index':2,'option_token':token(r.refs[L])}
    op(r,1)
    r.event(L,'OnChange',stale)
    assert [v['ID'] for v in r.refs[L].property('SelectedItems')]==[1,2,3]
    r.event(L,'OnChange',{**stale,'operation':'range','index':5})
    assert [v['ID'] for v in r.refs[L].property('SelectedItems')]==[3,4,5,6]
    r.event(L,'OnChange',{**stale,'operation':'all','index':None})
    assert len(r.refs[L].property('SelectedItems'))==8
    stale['option_token']=token(r.refs[L]);r.store.patch('Topics',r.store.rows('Topics')[2],{'Title':'Fictional changed topic'});r.invalidate()
    with pytest.raises(ValueError):r.event(L,'OnChange',stale)
    stale['option_token']=token(r.refs[L]);prop(r,'Value','="ID"')
    with pytest.raises(ValueError):r.event(L,'OnChange',stale)

def test_single_select_rejects_multiple_and_range(r):
    p='ListBoxLab/Single'
    with pytest.raises(ValueError,match='only one'):r.event(p,'OnChange',selection=[0,1])
    with pytest.raises(ValueError):op(r,4,'range',p)
    with pytest.raises(ValueError):op(r,operation='all',path=p)
    op(r,4,path=p);assert r.refs[p].property('Selected')['ID']==5

def test_selection_refreshes_records_and_drops_removed_items(r):
    op(r,2);r.store.patch('Topics',r.store.rows('Topics')[2],{'Title':'Fictional revised transit'});r.invalidate()
    assert r.fx.evaluate('LeftPicker.Latest.Title')=='Fictional revised transit'
    prop(r,'Items','=Filter(TopicPicker.Records,ID<>3)')
    assert r.fx.evaluate('LeftPicker.Latest.ID')==1

@pytest.mark.parametrize('name,value',[('Default','=Table({Value:"x"})'),('Default','={Value:"x"}'),('SelectMultiple','=1'),('Value','=Blank()'),('Value','=1'),('LineHeight','=-1'),('ItemPaddingLeft','=-2'),('Items','=1')])
def test_invalid_property_contract(r,name,value):
    prop(r,name,value)
    with pytest.raises(FxError):r.refs[L].property(name)
    assert r.fx.evaluate('RightPicker.Latest.ID')==8
@pytest.mark.parametrize('name',['Selected','SelectedItems','SelectedText','SelectedItemsText','DefaultSelectedItems','SearchFields','IsSearchable','Required','ItemDisplayText'])
def test_authored_outputs_and_modern_properties_are_visible(r,name):
    prop(r,name,'=Blank()');assert any('output' in x['message'] or 'does not support' in x['message'] for x in r.state()['diagnostics'])

def test_error_row_is_disabled_healthy_rows_work(r):
    prop(r,'Items','=Table({Title:"Fictional good"},IfError(1/0,Error({Kind:ErrorKind.Network,Message:"row failed"})))')
    prop(r,'Default','=Blank()');n=r.render(r.refs[L]);assert n['options'][1]['disabled']
    op(r,0);assert r.refs[L].property('Selected')['Title']=='Fictional good'
    with pytest.raises(FxError,match='row failed'):op(r,1)

def test_form_required_failed_save_and_recovery(r):
    op(r,operation='clear',path=F);assert not r.fx.evaluate('DraftForm.Valid')
    r.event('ListBoxLab/Save','OnSelect');assert r.store.rows('Drafts')[0]['Topic']['ID']==1
    op(r,2,path=F);r.store.failures['Drafts']='write';r.event('ListBoxLab/Save','OnSelect')
    assert r.globals['status']=='Save failed' and r.fx.evaluate('DraftForm.Unsaved')
    r.store.failures.clear();r.event('ListBoxLab/Save','OnSelect')
    assert r.store.rows('Drafts')[0]['Topic']['ID']==3 and not r.fx.evaluate('DraftForm.Unsaved')

def test_source_roundtrip_and_pure_inspection(r):
    source=(r.project.root/'Src/listbox.pa.yaml').read_bytes();state=deepcopy(r.control_state)
    r.state();r.refs[L].property('SelectedItemsText');assert r.control_state==state
    op(r,3);assert (r.project.root/'Src/listbox.pa.yaml').read_bytes()==source
    assert b'option_token' not in source
@pytest.mark.parametrize('language,number',[('en-US','float'),('en-US','decimal'),('fr-CA','float'),('fr-CA','decimal')])
def test_workflow_modes_preserve_owner(tmp_path,language,number):
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision
    from powerapps_sim.workflows import data_revision
    p=listbox_project(tmp_path/'owner');w=Workspace(tmp_path,p.root)
    try:
        state=deepcopy(w.ai.read_runtime());source=revision(p.root);data=data_revision(w.runtime.store)
        scenario=w.workflows.catalog()['scenarios'][0]['scenario'];scenario={**scenario,'environment':{'language':language,'number_mode':number,'enum_mode':'strong'}}
        report=w.workflows.run(scenario,expected_revision=source)
        assert report['status']=='passed' and len(report['steps'])==59 and not report['diagnostics']
        assert w.ai.read_runtime()==state and revision(p.root)==source and data_revision(w.runtime.store)==data
    finally:w.runtime.close()

def test_mapped_display_and_default_aliases(r):
    r.store.add_list('Mapped',{'fields':{'ID':{'type':'integer'},'InternalTitle':{'type':'string'}},'mapping':{'InternalTitle':'Topic name'}})
    r.store.import_rows('Mapped',[{'ID':31,'InternalTitle':'Fictional mapped topic'}])
    prop(r,'Records','=Mapped',path='ListBoxLab/LeftPicker');prop(r,'Value','="Topic name"');prop(r,'Default','="Fictional mapped topic"')
    chosen=r.refs[L].property('Selected')
    assert r.fx.member(chosen,'InternalTitle',r.refs[L].context())=='Fictional mapped topic'
    assert r.refs[L].property('SelectedText')=='Fictional mapped topic'

def test_http_selection_token_and_headers(tmp_path):
    from powerapps_sim.web import create_app
    p=listbox_project(tmp_path/'project');app=create_app(tmp_path/'workspace',p.root);w=app.extensions['workspace'];client=app.test_client()
    try:
        body={'path':L,'name':'OnChange','value':{'operation':'toggle','index':2,'option_token':token(w.runtime.refs[L])}}
        assert client.post('/api/event',json=body).status_code==403
        response=client.post('/api/event',json=body,headers={'X-Emulator-Request':'1'});assert response.status_code==200
        assert w.runtime.fx.evaluate('LeftPicker.Latest.ID')==3
        client.post('/api/event',json={'path':'ListBoxLab/ResetLeft','name':'OnSelect'},headers={'X-Emulator-Request':'1'})
        assert client.post('/api/event',json=body,headers={'X-Emulator-Request':'1'}).status_code==400
    finally:w.runtime.close()


@pytest.mark.parametrize('name,value',[('Items','=Sort(TopicPicker.Records,ID,SortOrder.Descending)'),('Default','="Fictional Water"'),('SelectMultiple','=false')])
def test_source_configuration_change_rejects_queued_gesture(r,name,value):
    pending={'operation':'toggle','index':2,'option_token':token(r.refs[L])}
    prop(r,name,value)
    with pytest.raises(ValueError,match='changed'):r.event(L,'OnChange',pending)

def test_selection_output_types_follow_items_schema(r):
    from powerapps_sim.binding import TEXT,NUMBER
    binder=r.binder
    control=r.refs['ListBoxLab/Single'].control
    chosen=binder.property_type(control,'SelectedItems')
    assert chosen.kind=='Table' and chosen.row.fields['Title']==TEXT and chosen.row.fields['ID']==NUMBER
    assert binder.property_type(control,'Selected').fields['Title']==TEXT
    assert binder.property_type(control,'SelectedItemsText').row.fields['Value']==TEXT
