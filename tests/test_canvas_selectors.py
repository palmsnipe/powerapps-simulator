from copy import deepcopy
from pathlib import Path
import json
import pytest
from powerapps_sim.fixtures import canvas_selectors_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision,data_revision
from powerapps_sim.canvas_selectors import catalog,token,search_token
from powerapps_sim.syntax import FxError

@pytest.fixture
def r(tmp_path):
 r=Runtime(canvas_selectors_project(tmp_path/'owner'));r.restart();r.state();assert not r.diagnostics,r.diagnostics
 yield r;r.close()
def picker(r,side='Left'):return r.refs[f'Home/{side}/Picker']
def authored(r,g,**p):
 g.control=deepcopy(g.control);g.control.properties.update(p);r.invalidate()
def send(r,g,indices=None,**p):
 value={'indices':indices} if indices is not None else p
 r.event(g.path,'OnChange',{**value,'option_token':token(g)});r.state()
def search(r,g,text,tok=None):r.event(g.path,'OnSearch',{'text':text,'reset_token':tok or search_token(g)});r.state()

@pytest.mark.parametrize('language',['en-US','fr-CA'])
@pytest.mark.parametrize('numbers',['float','decimal'])
@pytest.mark.parametrize('enums',['legacy','strong'])
def test_isolated_workflow_owner_source_records_runtime_preserved(tmp_path,language,numbers,enums):
 p=canvas_selectors_project(tmp_path/'owner');w=Workspace(tmp_path,p.root,start=False)
 try:
  before=revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime(),w.ai.export_source()
  s=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario']);s['environment']={'language':language,'number_mode':numbers,'enum_mode':enums}
  result=w.workflows.run(s,expected_revision=before[0]);assert result['status']=='passed' and len(result['steps'])==26 and not result['diagnostics'],result
  assert before==(revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime(),w.ai.export_source())
 finally:w.runtime.close()

@pytest.mark.parametrize('family,version',[(f,v) for f in ['ComboBox','DropDown'] for v in catalog()[f]])
def test_native_versions_defaults_outputs_and_types(r,family,version):
 g=r.refs['Home/Single'];g.control=deepcopy(g.control);g.control.kind=family+'@'+version;g.control.raw['Properties']={};r.invalidate();r.state()
 assert g.property('Items')==[{'Value':'Item 1'},{'Value':'Item 2'},{'Value':'Item 3'}]
 assert g.property('Selected') is None and g.property('SelectedItems')==[] and g.property('Width')==320 and g.property('Height')==32
 if family=='ComboBox':assert g.property('SelectMultiple') is False and g.property('TriggerOutput')=='Keypress' and g.property('SearchText')==''
 for p in catalog()[family][version]['types']:g.property(p)
 send(r,g,[1]);assert g.property('Selected')=={'Value':'Item 2'}
 assert r.binder.property_type(g.control,'Selected').kind=='Record'
 assert r.binder.property_type(g.control,'SelectedItems').kind=='Table'
 assert not r.diagnostics,r.diagnostics

@pytest.mark.parametrize('family,prop',[(f,p) for f,ps in {'ComboBox':['Selected','SelectedItems','SearchText','OnSelect','Default','ItemDisplayText','Fields','DelayOutput','Reset','PCFTeamsTheme','Color','Size'],'DropDown':['Selected','SelectedItems','OnSelect','Default','ItemDisplayText','SelectMultiple','SearchText','Font','FontColor','Reset','PCFTeamsTheme']}.items() for p in ps])
def test_authored_unsupported_properties_retained_with_peer_isolation(r,family,prop):
 g=r.refs['Home/Single' if family=='ComboBox' else 'Home/Dropdown'];authored(r,g,**{prop:'=Blank()'});r.state()
 assert any(d['kind']=='Unsupported' for d in r.diagnostics)
 assert prop in g.control.properties and picker(r).property('SelectedItems')==[]

@pytest.mark.parametrize('prop,formula',[('Items','=42'),('Items','=Table(1)'),('DefaultSelectedItems','={Value:"Draft"}'),('SelectMultiple','="true"'),('IsSearchable','=1'),('Required','="yes"'),('TriggerOutput','="Immediate"'),('Appearance','="Primary"'),('ValidationState','="Invalid"'),('FontSize','=-1'),('TabIndex','=0.5'),('BorderRadius','=-1'),('Fill','=3')])
def test_invalid_native_properties_isolate_failures(r,prop,formula):
 authored(r,r.refs['Home/Single'],**{prop:formula});r.state();assert r.diagnostics,(prop,r.diagnostics)
 assert picker(r).property('SelectedItems')==[]

@pytest.mark.parametrize('family',['ComboBox','DropDown','ComboBoxDataField'])
def test_unknown_version_keeps_other_controls_live(r,family):
 g=picker(r) if family=='ComboBox' else r.refs['Home/Dropdown'] if family=='DropDown' else picker(r).children[0]
 g.control=deepcopy(g.control);g.control.kind=family+'@9.0.0';r.invalidate();r.state();assert r.diagnostics
 send(r,r.refs['Home/Single'],[1]);assert r.refs['Home/Single'].property('Selected').get('Value')=='Review'

@pytest.mark.parametrize('prop,formula',[('FieldName','="Missing"'),('FieldName','=""'),('FieldName','=42'),('Order','=1.5'),('Order','=-1'),('FieldType','="Unknown"'),('FieldVariantName','="personColumn"')])
def test_field_metadata_errors_preserve_source_and_peer(r,prop,formula):
 g=picker(r).children[0];authored(r,g,**{prop:formula});state=r.state();assert r.diagnostics,(prop,state)
 assert g.control.properties[prop]==formula
 assert picker(r,'Right').property('SelectedItems')==[]
 with pytest.raises(FxError):send(r,picker(r),[0])

def test_field_metadata_variants_parent_and_complex_values(r):
 g=picker(r).children[0];g.control=deepcopy(g.control);g.control.raw['Variant']='personColumn';r.invalidate();r.state();assert r.diagnostics
 g.control.raw['Variant']='textualColumn';authored(r,picker(r),Items='=Table({ID:1,Title:{Value:"Bad"},Group:"OK"})');r.state();assert any('scalar' in d['message'] for d in r.diagnostics)
 with pytest.raises(FxError):send(r,picker(r),[0])
 g.control.parent=r.refs['Home/Dropdown'].control;r.invalidate();r.state();assert any('parent' in d['message'] for d in r.diagnostics)

@pytest.mark.parametrize('data',[{}, {'indices':[True]},{'indices':[99]},{'indices':[0,0]},{'operation':'toggle','index':False},{'operation':'clear','extra':1},{'operation':'remove','index':9}])
def test_malformed_payload_has_no_callback_or_selection(r,data):
 g=picker(r)
 with pytest.raises(ValueError):r.event(g.path,'OnChange',{**data,'option_token':token(g)})
 assert g.property('SelectedItems')==[] and r.collections['events']==[]

def test_callbacks_commit_once_and_reset_defaults_have_no_callback(r):
 g=picker(r);send(r,g,[0,1]);send(r,g,[0,1]);assert r.collections['events']==[{'Panel':'Left','Count':2}]
 assert g.property('Selected')['ID']==1
 saved=token(g);r.event('Home/ResetLeft','OnSelect');r.state();assert not g.property('SelectedItems')
 r.event(g.path,'OnChange',{'indices':[2],'option_token':saved});assert not g.property('SelectedItems')
 r.event('Home/ChangeDefaults','OnSelect');r.state();assert g.property('Selected')['ID']==3 and len(r.collections['events'])==1
 send(r,g,operation='clear');assert g.property('Selected') is None

@pytest.mark.parametrize('mode',['Keypress','Delayed','FocusOut'])
def test_search_output_no_callback_token_resets_and_self_scope(r,mode):
 g=picker(r);authored(r,g,TriggerOutput='="'+mode+'"',Items='=Filter(SelectorPanel.Rows,StartsWith(Title,Self.SearchText))');r.state();old=search_token(g)
 send(r,g,[0]);search(r,g,'Fictional park');assert g.property('SearchText')=='Fictional park' and g.property('Selected')['ID']==1 and len(g.property('Items'))==1
 send(r,g,operation='toggle',index=0);assert [x['ID'] for x in g.property('SelectedItems')]==[1,2]
 send(r,g,operation='remove',index=0);assert g.property('Selected')['ID']==2
 assert len(r.collections['events'])==3 and search_token(g)==old
 r.event('Home/ResetLeft','OnSelect');r.state();search(r,g,'stale',old);assert g.property('SearchText')==''


def test_not_searchable_single_and_duplicate_record_identity(r):
 g=picker(r);authored(r,g,IsSearchable='=false');r.state()
 with pytest.raises(ValueError):search(r,g,'park')
 assert g.property('SearchText')==''
 authored(r,g,Items='=Table({Title:"Same",Group:"A"},{Title:"Same",Group:"A"})');r.state();send(r,g,[0,1]);assert len(g.property('SelectedItems'))==2
 send(r,g,operation='toggle',index=0);assert len(g.property('SelectedItems'))==1
 single=r.refs['Home/Single']
 with pytest.raises(ValueError):send(r,single,[0,1])
 send(r,single,[1]);send(r,single,operation='toggle',index=1);assert single.property('Selected').get('Value')=='Review'


def test_option_tokens_change_with_field_items_and_selection(r):
 g=picker(r);old=token(g);send(r,g,[0]);assert token(g)!=old
 saved=token(g);authored(r,g.children[0],Order='=3');r.state();assert token(g)!=saved
 r.event(g.path,'OnChange',{'indices':[1],'option_token':saved});assert g.property('Selected')['ID']==1


def test_form_unsaved_choice_shapes_failed_save_and_reset(r):
 state=r.refs['Home/NoteForm/StateCard/FormState'];tags=r.refs['Home/NoteForm/TagsCard/FormTags'];form=r.refs['Home/NoteForm']
 assert not form.property('Unsaved');send(r,state,[2]);send(r,tags,[1,2]);assert form.property('Unsaved') and form.property('Valid')
 assert form.property('Updates')=={'State':{'Value':'Approved'},'Tags':[{'Value':'Design'},{'Value':'Urgent'}]}
 before=data_revision(r.store);r.store.failures['Notes']='write';r.event('Home/Save','OnSelect');r.state();assert data_revision(r.store)==before and form.property('Unsaved')
 r.store.failures.clear();r.event('Home/Save','OnSelect');r.state();assert not form.property('Unsaved') and r.fx.evaluate('First(Notes).State.Value="Approved" && CountRows(First(Notes).Tags)=2')
 send(r,state,[0]);r.fx.evaluate('ResetForm(NoteForm)',form.context(behavior=True));r.state();assert state.property('Selected')=={'Value':'Approved'} and not form.property('Unsaved')


def test_source_export_keeps_native_field_subtree_and_excludes_config(tmp_path):
 p=canvas_selectors_project(tmp_path/'owner');w=Workspace(tmp_path,p.root,start=False)
 try:
  result=w.ai.export_source();assert 'textualColumn' in json.dumps(result) and 'ComboBoxDataField@1.5.0' in json.dumps(result)
  assert 'canvas-selectors.json' not in json.dumps(result)
 finally:w.runtime.close()


def test_gallery_row_choice_write_refresh_and_owner_baseline(r):
 row=next(ref for ref in r.refs.values() if ref.name=='RowState' and '/row:' in ref.path and ref.context().item['ID']==2)
 send(r,row,[2]);assert r.fx.evaluate('Last(Notes).State.Value="Approved"')
 assert row.property('Selected')=={'Value':'Approved'} and not row.state.get('dirty')
 assert r.fx.evaluate('First(Notes).State.Value="Draft"')

@pytest.mark.parametrize('event,value',[('OnSelect',None),('OnInput','x'),('OnNavigate',{}),('OnChange','Draft')])
def test_native_selector_does_not_inherit_alias_events(r,event,value):
 with pytest.raises(ValueError):r.event('Home/Single',event,value)
 assert not r.collections['events']

def test_selector_setfocus_remains_explicitly_unsupported(r):
 with pytest.raises(FxError,match='SetFocus'):r.fx.evaluate('SetFocus(Single)',r.refs['Home/Single'].context(behavior=True))


def test_missing_display_fields_are_per_row_errors_with_source_location(r):
 g=picker(r);authored(r,g,Items='=Table({ID:1,Title:"OK",Group:"A"},{ID:2,Title:Error({Kind:ErrorKind.Validation,Message:"Bad field"}),Group:"B"})');state=r.state()
 from powerapps_sim.canvas_selectors import render
 node={'errors':[]};render(g,node)
 assert not node['options'][0]['disabled'] and node['options'][1]['disabled']
 send(r,g,[0]);assert g.property('Selected')['ID']==1
 assert any('Bad field' in d['message'] and d.get('source') for d in r.diagnostics)


def test_partial_defaults_match_identity_when_returning_to_baseline(r):
 g=picker(r);authored(r,g,DefaultSelectedItems='=Table({ID:1})');r.state();send(r,g,[1]);assert g.state['dirty']
 send(r,g,[0]);assert not g.state['dirty']


def test_unmatched_defaults_have_an_empty_clean_baseline(r):
 g=picker(r);authored(r,g,DefaultSelectedItems='=Table({ID:99})');r.state();send(r,g,[0]);assert g.state['dirty']
 send(r,g,operation='clear');assert not g.state['dirty']


def test_blank_table_fields_are_valid_and_distinct_from_missing_bindings(r):
 g=picker(r);authored(r,g,Items='=Table({Title:"OK",Group:"A"},{Other:"Blank"})');r.state()
 from powerapps_sim.canvas_selectors import render
 node={'errors':[]};render(g,node);assert not node['errors'] and node['options'][1]['label']==''


@pytest.mark.parametrize('payload',[{'text':'x','reset_token':3},{'text':7,'reset_token':'bad'}])
def test_malformed_search_has_no_state_change(r,payload):
 g=picker(r)
 with pytest.raises(ValueError):r.event(g.path,'OnSearch',payload)
 assert g.property('SearchText')=='' and not r.collections['events']



def test_runtime_bookkeeping_is_not_exposed_as_control_properties(r):
 from powerapps_sim.controls import inspect_properties
 g=picker(r);send(r,g,[0]);search(r,g,'park')
 assert not any('canvas_' in name or name.startswith('Canvas') for name in inspect_properties(g))
 assert g.property('Selected')['ID']==1 and g.property('SearchText')=='park'
