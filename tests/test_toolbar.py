from copy import deepcopy
import pytest
from powerapps_sim.fixtures import toolbar_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision,data_revision
from powerapps_sim.toolbar import commands,token,catalog
from powerapps_sim.syntax import FxError

@pytest.fixture
def r(tmp_path):
 r=Runtime(toolbar_project(tmp_path/'owner'));r.restart();r.state();assert not r.diagnostics,r.diagnostics
 yield r;r.close()
def ref(r,panel='Left'):return r.refs['Home/'+panel+'/Commands']
def click(r,k,panel='Left',tok=None):
 g=ref(r,panel);r.event(g.path,'OnSelect',{'key':k,'option_token':tok or token(g,commands(g))});r.state()
def authored(r,g,**p):g.control=deepcopy(g.control);g.control.properties.update(p);r.invalidate()

@pytest.mark.parametrize('language',['en-US','fr-CA'])
@pytest.mark.parametrize('number',['float','decimal'])
@pytest.mark.parametrize('enums',['legacy','strong'])
def test_workflow(tmp_path,language,number,enums):
 p=toolbar_project(tmp_path/'owner');w=Workspace(tmp_path,p.root,start=False)
 try:
  before=revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime(),w.ai.export_source()
  s=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario']);s['environment']={'language':language,'number_mode':number,'enum_mode':enums}
  result=w.workflows.run(s,expected_revision=before[0]);assert result['status']=='passed' and len(result['steps'])==19 and not result['diagnostics'],result
  assert before==(revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime(),w.ai.export_source())
 finally:w.runtime.close()

def test_selection_commits_before_callback_and_repeated_clicks(r):
 click(r,'new');assert r.fx.evaluate('Left.ChosenKey="new" && First(Left.Picked).ItemKey="new" && CountRows(Left.History)=1 && CountRows(Notes)=1')
 click(r,'new');assert len(r.collections['events'])==2 and r.fx.evaluate('CountRows(Notes)')==2
 assert r.binder.property_type(ref(r).control,'Selected').kind=='Record'

@pytest.mark.parametrize('key',['edit','delete','hidden'])
def test_disabled_and_hidden_items_do_not_execute(r,key):
 click(r,key);assert not r.collections['events'] and ref(r).property('Selected') is None

@pytest.mark.parametrize('mode',['Disabled','View'])
def test_modes_and_ancestors(r,mode):
 g=ref(r);authored(r,g,DisplayMode='=DisplayMode.'+mode);click(r,'new');assert not r.collections['events']
 authored(r,g,DisplayMode='=DisplayMode.Edit');authored(r,g.parent,Visible='=false');click(r,'new');assert not r.collections['events']

def test_reset_defaults_and_stale_tokens(r):
 g=ref(r);click(r,'new');old=token(g,commands(g));r.reset_ref(g)
 with pytest.raises(ValueError,match='changed'):click(r,'new',tok=old)
 authored(r,g,DefaultSelectedItems='=Filter(CommandPanel.Rows,ItemKey="info")');r.state();assert g.property('Selected')['ItemKey']=='info'
 old=token(g,commands(g));authored(r,g,DefaultSelectedItems='=Filter(CommandPanel.Rows,ItemKey="new")');r.state()
 assert g.property('Selected')['ItemKey']=='new'
 with pytest.raises(ValueError,match='changed'):click(r,'new',tok=old)

def test_reactive_disabled_status_and_selection_record_refresh(r):
 click(r,'new');old=token(ref(r),commands(ref(r)));r.event('Home/EnableEdit','OnSelect');r.state()
 with pytest.raises(ValueError,match='changed'):click(r,'edit',tok=old)
 click(r,'edit');assert r.fx.evaluate('Left.ChosenKey="edit" && !First(Left.Picked).ItemDisabled')
 r.globals['canEdit']=False;r.invalidate();r.state();assert r.fx.evaluate('First(Left.Picked).ItemDisabled')

def test_unknown_keys_and_malformed_events_never_execute(r):
 for value in ({'key':'missing','option_token':token(ref(r),commands(ref(r)))},{'key':True,'option_token':'bad'},True,{'key':'new'}):
  with pytest.raises(ValueError):r.event(ref(r).path,'OnSelect',value)
 assert not r.collections['events']

@pytest.mark.parametrize('prop',catalog()['unsupported']+['Selected','SelectedItems','OnChange','Reset','Unknown'])
def test_unsupported_properties_are_preserved_and_diagnosed(r,prop):
 g=ref(r);authored(r,g,**{prop:'=Blank()'});r.state();assert any(d['kind']=='Unsupported' for d in r.diagnostics)
 assert ref(r,'Right').property('Items')

@pytest.mark.parametrize('prop,value',[('Items','=3'),('DefaultSelectedItems','={ItemKey:"new"}'),('Padding','="Huge"'),('Layout','="IconBefore"'),('Alignment','="Center"'),('FontSize','=-2'),('FontItalic','="yes"'),('TabIndex','=1.5')])
def test_bad_contracts_isolate_peer(r,prop,value):
 authored(r,ref(r),**{prop:value});r.state();assert r.diagnostics and ref(r,'Right').property('Items')

@pytest.mark.parametrize('items',[
 '=Table({ItemKey:"same",ItemDisplayName:"A"},{ItemKey:"same",ItemDisplayName:"B"},{ItemKey:"healthy",ItemDisplayName:"Healthy"})',
 '=Table({ItemKey:"bad",ItemDisplayName:"Bad",ItemDisabled:"true"},{ItemKey:"healthy",ItemDisplayName:"Healthy"})',
 '=Table({ItemKey:"bad",ItemDisplayName:"Bad",ItemIconName:"NonexistentFictionalIcon"},{ItemKey:"healthy",ItemDisplayName:"Healthy"})'])
def test_item_error_isolation(r,items):
 g=ref(r);authored(r,g,Items=items);state=r.state();assert r.diagnostics
 r.event(g.path,'OnSelect',{'key':'healthy','option_token':token(g,commands(g))});assert g.property('Selected')['ItemKey']=='healthy'
 assert len(r.collections['events'])==1

def test_native_items_default_table_matches_literal_archive(r):
 from powerapps_sim.toolbar import DEFAULTS
 rows=r.fx.evaluate(DEFAULTS['Items']);assert [v['ItemKey'] for v in rows]==['new','edit','delete','info']
 assert rows[2]['ItemDisabled'] is True and rows[2]['ItemIconStyle']=='Filled'
