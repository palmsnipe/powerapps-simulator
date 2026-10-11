"""Classic field-based search, last selection, scoped callbacks and form saves."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from powerapps_sim.fixtures import classic_combo_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.syntax import FxError
from powerapps_sim.classic_combobox import catalog

LEFT='ClassicComboLab/LeftPicker/Pick';RIGHT='ClassicComboLab/RightPicker/Pick'
OWNERS='ClassicComboLab/DraftForm/OwnersCard/OwnerInput'

@pytest.fixture
def r(tmp_path):
    runtime=Runtime(classic_combo_project(tmp_path/'combo'));runtime.restart();runtime.state()
    assert runtime.viewport=={'width':940,'height':620}
    assert not runtime.diagnostics
    yield runtime
    runtime.close()

def node(r,path=LEFT):
    def visit(n):
        if n['path']==path:return n
        for child in n.get('children',[]):
            found=visit(child)
            if found:return found
    return r.render(r.refs[path])

def choose(r,index,path=LEFT,operation='toggle'):
    n=node(r,path);r.event(path,'OnChange',{'operation':operation,'index':index,'option_token':n['option_token']})

def prop(r,name,value,path=LEFT):
    r.refs[path].control=deepcopy(r.refs[path].control)
    r.refs[path].control.properties[name]=value;r.invalidate()

@pytest.mark.parametrize('version',['2.3.0','2.3.1','2.4.0'])
def test_verified_versions_and_defaults(r,version):
    r.refs[LEFT].control=deepcopy(r.refs[LEFT].control)
    r.refs[LEFT].control.kind='Classic/ComboBox@'+version
    assert r.refs[LEFT].control.version==version
    r.invalidate()
    assert r.refs[LEFT].property('MultiValueDelimiter')==(',\\u2002' if version=='2.3.0' else ', ')
    assert catalog()['defaults']['DisplayFields']=='=["Value1"]'
    assert r.fx.evaluate('Single.Selected.ID')==1
    assert node(r)['props']['Template']=='Person'
    assert not r.state()['diagnostics']

def test_fields_and_last_selected_record_are_classic_contract(r):
    n=node(r);assert n['options'][1]['secondary']=='casey@example.test'
    choose(r,1);choose(r,2)
    assert r.fx.evaluate('LeftPicker.Latest.ID')==3
    assert r.fx.evaluate('CountRows(LeftPicker.Chosen)')==3
    assert r.fx.evaluate('Last(LeftPicker.History).Latest')=='Fictional Camille Roy'
    choose(r,2);assert r.fx.evaluate('LeftPicker.Latest.ID')==2
    choose(r,1,operation='remove');assert r.fx.evaluate('LeftPicker.Latest.ID')==1
    assert r.fx.evaluate('RightPicker.Latest.ID')==4

def test_search_uses_search_fields_independent_of_display_and_preserves_choice(r):
    r.event(LEFT,'OnSearch','casey@example')
    assert [o['index'] for o in node(r)['options']]==[1]
    assert r.fx.evaluate('LeftPicker.Latest.ID')==1
    assert not r.collections['events'] and not r.refs[LEFT].state.get('dirty')
    choose(r,1);assert r.fx.evaluate('LeftPicker.Latest.ID')==2
    assert node(r)['selected_labels']==['Fictional River Adams','Fictional Casey Martin']
    choose(r,0,operation='remove');assert r.fx.evaluate('CountRows(LeftPicker.Chosen)')==1

def test_search_fields_multiple_casefold_and_display_templates(r):
    r.event(LEFT,'OnSearch','CAMILLE@EXAMPLE');assert len(node(r)['options'])==1
    prop(r,'Template','=ListItemTemplate.Single');n=node(r)
    assert n['options'][0]['secondary']=='' and not n['options'][0]['person']

def test_numeric_search_field_is_visible_type_error(r):
    prop(r,'SearchFields','=["ID"]');r.event(LEFT,'OnSearch','2')
    assert any('must contain Text' in d['message'] for d in r.state()['diagnostics'])

def test_explicit_search_items_preserve_original_indices(r):
    prop(r,'SearchItems','=Filter(Self.Items,ID=3)')
    assert [o['index'] for o in node(r)['options']]==[2]
    choose(r,2);assert r.fx.evaluate('LeftPicker.Latest.ID')==3
    with pytest.raises(ValueError,match='search results'):choose(r,1)

def test_changed_fields_and_selected_tags_reject_stale_operations(r):
    n=node(r);v={'operation':'toggle','index':1,'option_token':n['option_token']}
    prop(r,'DisplayFields','=["Email","DisplayName"]')
    with pytest.raises(ValueError,match='Choices changed'):r.event(LEFT,'OnChange',v)
    n=node(r);choose(r,1)
    with pytest.raises(ValueError,match='Choices changed'):r.event(LEFT,'OnChange',{'operation':'remove','index':0,'option_token':n['option_token']})

def test_invalid_indices_and_hidden_search_results_leave_state_unchanged(r):
    before=deepcopy(r.refs[LEFT].state)
    for i in [-1,99,True,'1']:
        with pytest.raises(ValueError):choose(r,i)
    assert r.refs[LEFT].state==before
    r.event(LEFT,'OnSearch','camille')
    with pytest.raises(ValueError,match='search results'):choose(r,1)

def test_component_reset_cancels_pending_search_and_keeps_other_instance(r):
    choose(r,2);choose(r,1,RIGHT);r.event(LEFT,'OnSearch','casey');token=node(r)['search_reset']
    r.event('ClassicComboLab/ResetLeft','OnSelect')
    r.event(LEFT,'OnSearch',{'text':'river','reset_token':token})
    assert r.refs[LEFT].property('SearchText')==''
    assert r.fx.evaluate('LeftPicker.Latest.ID')==1 and r.fx.evaluate('RightPicker.Latest.ID')==2
    assert r.fx.evaluate('CountRows(LeftPicker.History)')==0
    assert r.fx.evaluate('CountRows(RightPicker.History)')==1

def test_default_record_blank_and_deprecated_default_are_supported(r):
    p='ClassicComboLab/Single'
    prop(r,'DefaultSelectedItems','=Last(People)',p);assert r.fx.evaluate('Single.Selected.ID')==4
    prop(r,'DefaultSelectedItems','=Blank()',p);assert r.fx.evaluate('IsBlank(Single.Selected)')
    r.refs[p].control.properties.pop('DefaultSelectedItems');prop(r,'Default','=First(People)',p)
    assert r.fx.evaluate('Single.Selected.ID')==1

def test_single_mode_rejects_multiple_indices_and_clear_is_blank(r):
    p='ClassicComboLab/Single'
    with pytest.raises(ValueError,match='one selected'):r.event(p,'OnChange',selection=[0,1])
    choose(r,2,p);assert r.fx.evaluate('Single.Selected.ID')==3
    r.event(p,'OnChange',{'operation':'clear','option_token':node(r,p)['option_token']})
    assert r.fx.evaluate('IsBlank(Single.Selected)')
    with pytest.raises(ValueError,match='Search is disabled'):r.event(p,'OnSearch','camille')

def test_navigation_callback_receives_row_without_mutating_selection(r):
    r.event(LEFT,'OnSearch','camille');n=node(r)
    before=r.fx.evaluate('LeftPicker.Chosen')
    r.event(LEFT,'OnNavigate',{'index':2,'option_token':n['option_token']})
    assert r.globals['navigated']=='Fictional Camille Roy'
    assert r.fx.evaluate('LeftPicker.Chosen')==before and not r.collections['events']
    with pytest.raises(ValueError,match='search results'):r.event(LEFT,'OnNavigate',{'index':0,'option_token':node(r)['option_token']})
    with pytest.raises(ValueError,match='Navigate requires'):r.event(LEFT,'OnNavigate',{'index':2})

def test_navigation_requires_configured_fields_and_rejects_wrong_family(r):
    p='ClassicComboLab/Single'
    with pytest.raises(ValueError,match='NavigateFields'):r.event(p,'OnNavigate',{'index':0,'option_token':node(r,p)['option_token']})
    with pytest.raises(ValueError):r.event('ClassicComboLab/Save','OnNavigate',{'index':0,'option_token':'x'})

@pytest.mark.parametrize('name,value',[('DisplayFields','=1'),('SearchFields','=[1]'),('NavigateFields','=[""]'),('Template','="Other"'),('SelectMultiple','=1'),('IsSearchable','="yes"'),('UsePhoneLayout','=0'),('Items','=1'),('DefaultSelectedItems','="x"'),('DefaultSelectedItems','=true'),('FlyoutMaximumHeight','=-1'),('MultiValueDelimiter','=1')])
def test_invalid_contract_values_isolate_affected_control(r,name,value):
    prop(r,name,value)
    with pytest.raises(FxError):r.refs[LEFT].property(name)
    assert r.fx.evaluate('RightPicker.Latest.ID')==4

@pytest.mark.parametrize('name',['Selected','SelectedItems','SearchText','NavigateItem','ItemDisplayText','DelayOutput','Required','AcceptsFocus','Layout'])
def test_unknown_modern_properties_and_authored_outputs_report_unsupported(r,name):
    prop(r,name,'=Blank()')
    assert any('does not support' in d['message'] or 'output' in d['message'] for d in r.state()['diagnostics'])

@pytest.mark.parametrize('mode',['Disabled','View'])
def test_modes_block_selection_search_and_navigation(r,mode):
    prop(r,'DisplayMode','=DisplayMode.'+mode)
    before=deepcopy(r.refs[LEFT].state)
    r.event(LEFT,'OnSearch','casey');choose(r,1)
    r.event(LEFT,'OnNavigate',{'index':0,'option_token':node(r)['option_token']})
    assert r.refs[LEFT].state==before and not r.collections['events']

def test_no_duplicate_callback_and_pure_inspection(r):
    before=deepcopy(r.control_state);r.state();r.fx.evaluate('LeftPicker.Latest');r.fx.evaluate('LeftPicker.Chosen')
    assert r.control_state==before
    r.event(LEFT,'OnChange',selection=[0]);assert not r.collections['events']

def test_selected_records_refresh_after_local_list_write(r):
    choose(r,1);r.store.patch('People',r.store.rows('People')[1],{'DisplayName':'Fictional updated Casey'});r.invalidate()
    assert r.fx.evaluate('LeftPicker.Latest.DisplayName')=='Fictional updated Casey'
    assert node(r)['selected_labels'][-1]=='Fictional updated Casey'

def test_form_validation_failed_save_recovery_and_persistence(r):
    r.event(OWNERS,'OnChange',selection=[])
    assert not r.fx.evaluate('DraftForm.Valid')
    r.event('ClassicComboLab/Save','OnSelect');assert len(r.store.rows('Drafts')[0]['Owners'])==1
    r.event(OWNERS,'OnChange',selection=[1,2]);assert r.fx.evaluate('DraftForm.Unsaved')
    r.store.failures['Drafts']='write';r.event('ClassicComboLab/Save','OnSelect')
    assert r.globals['status']=='Save failed' and len(r.store.rows('Drafts')[0]['Owners'])==1
    r.store.failures.clear();r.event('ClassicComboLab/Save','OnSelect')
    assert [v['ID'] for v in r.store.rows('Drafts')[0]['Owners']]==[2,3]
    assert not r.fx.evaluate('DraftForm.Unsaved')

@pytest.mark.parametrize('language,number_mode',[('en-US','float'),('en-US','decimal'),('fr-CA','float'),('fr-CA','decimal')])
def test_workflow_in_four_modes_preserves_owner(tmp_path,language,number_mode):
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision
    from powerapps_sim.workflows import data_revision
    p=classic_combo_project(tmp_path/'owner');w=Workspace(tmp_path,p.root)
    try:
        before=deepcopy(w.ai.read_runtime());source=revision(p.root);data=data_revision(w.runtime.store)
        s=w.workflows.catalog()['scenarios'][0]['scenario'];s={**s,'environment':{**s['environment'],'language':language,'number_mode':number_mode}}
        result=w.workflows.run(s,expected_revision=source)
        assert result['status']=='passed' and len(result['steps'])==69 and not result['diagnostics']
        assert w.ai.read_runtime()==before and revision(p.root)==source and data_revision(w.runtime.store)==data
    finally:w.runtime.close()

def test_logical_and_display_column_mapping(r):
    r.store.add_list('Mapped',{'fields':{'ID':{'type':'integer'},'InternalName':{'type':'string'},'InternalEmail':{'type':'string'}},'mapping':{'InternalName':'Person name','InternalEmail':'Contact email'}})
    r.store.import_rows('Mapped',[{'ID':9,'InternalName':'Fictional Mapped Person','InternalEmail':'mapped@example.test'}])
    p='ClassicComboLab/Single'
    prop(r,'Items','=Mapped',p);prop(r,'DisplayFields','=["Person name"]',p)
    prop(r,'SearchFields','=["InternalEmail"]',p);prop(r,'IsSearchable','=true',p)
    prop(r,'DefaultSelectedItems','=First(Mapped)',p)
    r.event(p,'OnSearch','mapped@example')
    assert node(r,p)['options'][0]['label']=='Fictional Mapped Person'
    assert r.fx.member(r.refs[p].property('Selected'),'InternalName',r.refs[p].context())=='Fictional Mapped Person'

def test_output_formulas_dont_repair_source_or_export_emulator_fields(r):
    from powerapps_sim.source import Project
    source=(r.project.root/'Src/classic-combo.pa.yaml').read_bytes()
    choose(r,2);r.event(LEFT,'OnSearch','camille')
    assert (r.project.root/'Src/classic-combo.pa.yaml').read_bytes()==source
    p=Project(r.project.root)
    assert p.screens['ClassicComboLab'].raw['Children'][2]['LeftPicker']['ComponentName']=='PeoplePicker'
    assert 'option_token' not in source.decode() and 'search_reset' not in source.decode()

@pytest.mark.parametrize('value',[None,[],False,1,{'text':'casey','reset_token':1}])
def test_malformed_search_payload_is_rejected(r,value):
    with pytest.raises(ValueError):r.event(LEFT,'OnSearch',value)

def test_http_event_tokens_and_navigation_are_server_owned(tmp_path):
    from powerapps_sim.web import create_app
    p=classic_combo_project(tmp_path/'project');app=create_app(tmp_path/'workspace',p.root);client=app.test_client()
    w=app.extensions['workspace'];n=node(w.runtime)
    try:
        payload={'path':LEFT,'name':'OnNavigate','value':{'index':1,'option_token':n['option_token']}}
        assert client.post('/api/event',json=payload).status_code==403
        response=client.post('/api/event',json=payload,headers={'X-Emulator-Request':'1'})
        assert response.status_code==200 and response.json['globals']['navigated']=='Fictional Casey Martin'
        payload['value']['option_token']='stale'
        assert client.post('/api/event',json=payload,headers={'X-Emulator-Request':'1'}).status_code==400
    finally:w.runtime.close()

def test_phone_layout_reports_unsupported_explicitly(r):
    prop(r,'UsePhoneLayout','=true')
    assert any('phone layout is not implemented' in d['message'] for d in r.state()['diagnostics'])

def test_gallery_scroll_resets_classic_selection_without_callback(tmp_path):
    from powerapps_sim.source import load_yaml,dump_yaml
    from powerapps_sim.gallery_loading import token
    p=classic_combo_project(tmp_path/'gallery')
    filename='Src/classic-combo.pa.yaml';d=load_yaml((p.root/filename).read_text())
    choice={'Control':'Classic/ComboBox@2.4.0','Properties':{'Items':'=People','DefaultSelectedItems':'=Table(First(People))','DisplayFields':'=["DisplayName"]','SearchFields':'=["Email"]','Width':'=400','Height':'=40','OnChange':'=Collect(events,{Panel:"Row",Name:Self.Selected.DisplayName})'}}
    gallery_source={'Control':'Gallery@2.15.0','Properties':{'X':'=16','Y':'=600','Width':'=500','Height':'=100','TemplateSize':'=50','TemplatePadding':'=0','Items':'=People'},'Children':[{'RowChoice':choice}]}
    d['Screens']['ClassicComboLab']['Children'].append({'PeopleRows':gallery_source})
    p.update_source(filename,dump_yaml(d));rr=Runtime(p);rr.restart();rr.state()
    try:
        gallery=rr.global_refs['PeopleRows'];paths=[p for p in rr.refs if p.startswith(gallery.path+'/row:') and p.endswith('/RowChoice')]
        path=paths[0];n=rr.render(rr.refs[path]);rr.event(path,'OnChange',{'operation':'toggle','index':2,'option_token':n['option_token']})
        assert rr.refs[path].property('Selected')['ID']==3
        count=len(rr.collections['events'])
        rr.event(gallery.path,'OnViewport',{'offset':50,'extent':100,'viewport_token':token(gallery)})
        assert rr.refs[path].property('Selected')['ID']==1 and len(rr.collections['events'])==count
        assert rr.fx.evaluate('RightPicker.Latest.ID')==4
    finally:rr.close()
