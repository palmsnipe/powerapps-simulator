"""Archived display contracts, scoping, hidden heights and error isolation."""
from copy import deepcopy
import hashlib,io,zipfile
from pathlib import Path
import pytest
from powerapps_sim.canvas_text import catalog
from powerapps_sim.source import Project,dump_yaml
from powerapps_sim.runtime import Runtime
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError

KINDS=('Text@0.0.47','FluentV8/Label@1.6.0')
def make(tmp_path,kind=KINDS[0],props=None,environment=None,parent=False):
 p=Project(tmp_path/'native')
 leaf={'Control':kind,'Properties':{'Text':'=caption',**(props or {})}}
 children=[{'Native':leaf}]
 if parent:children=[{'Group':{'Control':'GroupContainer@1.5.0','Variant':'AutoLayout','Properties':{'Visible':'=shown','LayoutDirection':'=LayoutDirection.Vertical','Height':'=800'},'Children':children}}]
 p.update_source('Src/native.pa.yaml',dump_yaml({'App':{'Properties':{'OnStart':'=Set(count,0);Clear(events);Set(caption,"A short caption");Set(shown,true);Set(wide,300)'}},'Screens':{'Home':{'Children':children+[{'Healthy':{'Control':'ModernText@1.0.0','Properties':{'Text':'="Healthy"'}}}]}}}))
 p.config['environment'].update(environment or {});p.save_config();r=Runtime(p);r.restart();r.state();return r

def ref(r):return r.refs['Home/Group/Native'] if 'Home/Group/Native' in r.refs else r.refs['Home/Native']
def behavior(r,s):return r.fx.evaluate(s,Context(r,behavior=True))

@pytest.mark.parametrize('kind',KINDS)
@pytest.mark.parametrize('numbers',['float','decimal'])
@pytest.mark.parametrize('enums',['legacy','strong'])
def test_descriptor_defaults_native_names_and_pure_text(tmp_path,kind,numbers,enums):
 r=make(tmp_path,kind,environment={'number_mode':numbers,'enum_mode':enums})
 try:
  g=ref(r);s=catalog()[g.family][g.control.version]
  assert not r.diagnostics,r.diagnostics
  for name in s['types']:g.property(name)
  assert g.property('Text')=='A short caption' and g.property('Height')==32
  if g.family=='Text':
   assert g.property('Width')==96 and g.property('Size')==14 and g.property('Weight')=='Regular'
   assert g.property('Align')=='Start' and not r.render(g)['selectable']
   assert r.fx.evaluate('TextCanvas.Weight.Semibold')=='Semibold'
  else:
   assert g.property('Width')==320 and g.property('FontSize')==10.5
   assert g.property('Alignment')=='left' and g.property('FontWeight')=='normal'
   assert g.property('PaddingStart')==0 and g.property('TextRole')=='Default'
  assert not r.render(g)['errors']
  assert r.binder.property_type(g.control,'Text').kind=='Text'
 finally:r.close()

@pytest.mark.parametrize('kind,prop',[(k,p) for k in KINDS for p in ('AcceptsFocus','OnInput','Reset','AccessibleLabel','PCFTeamsTheme')]+[(KINDS[0],p) for p in ('FontWeight','FontSize','Color','OnSelect','OnChange','Role')]+[(KINDS[1],p) for p in ('Size','Align','VerticalAlign','PaddingLeft','Role','OnChange')])
def test_unknown_aliases_and_unverified_events_preserved_without_poisoning_peer(tmp_path,kind,prop):
 r=make(tmp_path,kind,{prop:'=false'})
 try:
  g=ref(r);assert g.control.properties[prop]=='=false'
  assert any(d['kind']=='Unsupported' for d in r.diagnostics)
  with pytest.raises(FxError):g.property(prop)
  assert not r.render(r.refs['Home/Healthy'])['errors']
  assert prop+':' in r.project.documents['Src/native.pa.yaml']
 finally:r.close()

@pytest.mark.parametrize('kind,prop,value',[(KINDS[0],'Weight','="Normal"'),(KINDS[0],'Align','=Align.Left'),(KINDS[0],'Size','=-1'),(KINDS[0],'Text','=123'),(KINDS[0],'FontItalic','=1'),(KINDS[1],'Overflow','="Auto"'),(KINDS[1],'TextRole','="Heading9"'),(KINDS[1],'FontSize','=true'),(KINDS[1],'PaddingStart','=-2'),(KINDS[1],'Alignment','="Start"'),(KINDS[1],'VerticalAlignment','="Center"'),(KINDS[1],'TabIndex','=0.5')])
def test_type_range_and_enum_errors_are_located(tmp_path,kind,prop,value):
 r=make(tmp_path,kind,{prop:value})
 try:
  assert any(d.get('source')=='Src/native.pa.yaml' and d['member'].endswith('.'+prop) for d in r.diagnostics),r.diagnostics
  assert not r.render(r.refs['Home/Healthy'])['errors']
 finally:r.close()

@pytest.mark.parametrize('kind',KINDS)
@pytest.mark.parametrize('parent',[False,True])
def test_hidden_autoheight_and_show_recalculates_width_and_caption(tmp_path,kind,parent):
 props={'AutoHeight':'=true','Text':'=caption','Width':'=wide','Visible':'=shown' if not parent else '=true','Height':'=32'}
 r=make(tmp_path,kind,props,parent=parent)
 try:
  g=ref(r);initial=g.property('Height')
  behavior(r,'Set(shown,false);Set(caption,Concat(Sequence(8),"Fictional long caption for wrapping "));Set(wide,100)')
  assert g.property('Height')==initial
  behavior(r,'Set(shown,true)');assert g.property('Height')>initial
  long=g.property('Height');behavior(r,'Set(caption,"Short");Set(wide,300)');assert g.property('Height')<long
  assert not r.render(g)['errors'] and not r.diagnostics
 finally:r.close()

@pytest.mark.parametrize('kind',KINDS)
def test_auto_layout_insets_do_not_read_unrelated_members(tmp_path,kind):
 r=make(tmp_path,kind,parent=True)
 try:
  g=ref(r);s=r.render(g);assert not s['errors']
  assert g.property('LayoutMinWidth')==(320 if g.family=='FluentV8/Label' else 96)
  assert g.property('LayoutMinHeight')==32
 finally:r.close()

@pytest.mark.parametrize('mode',['View','Disabled'])
def test_fluent_clicks_blocked_without_changing_collections(tmp_path,mode):
 r=make(tmp_path,KINDS[1],{'DisplayMode':'=DisplayMode.'+mode,'OnSelect':'=Set(count,count+1);Collect(events,{Count:count})'})
 try:
  r.event(ref(r).path,'OnSelect');assert r.globals['count']==0 and not r.collections['events']
 finally:r.close()

@pytest.mark.parametrize('kind',KINDS)
def test_focus_and_reset_are_unsupported_for_native_versions(tmp_path,kind):
 r=make(tmp_path,kind)
 try:
  with pytest.raises(FxError,match='SetFocus does not support'):behavior(r,'SetFocus(Native)')
  with pytest.raises(FxError):behavior(r,'Reset(Native)')
  assert not r.render(r.refs['Home/Healthy'])['errors']
 finally:r.close()

@pytest.mark.parametrize('kind,name,value,selection',[(KINDS[0],'OnSelect',None,None),(KINDS[1],'OnChange',None,None),(KINDS[1],'OnSelect','edited',None),(KINDS[1],'OnSelect',None,[0])])
def test_event_payloads_do_not_invent_input_state(tmp_path,kind,name,value,selection):
 r=make(tmp_path,kind)
 try:
  with pytest.raises(ValueError):r.event(ref(r).path,name,value,selection)
  assert not ref(r).state and not r.collections['events']
 finally:r.close()


def test_fluent_auto_disable_guards_reentrant_callbacks_and_releases_after_error(tmp_path):
 r=make(tmp_path,KINDS[1],{'OnSelect':'=Set(count,count+1)'})
 try:
  g=ref(r);original=r.execute;seen=[]
  def execute(formula,ctx,*args,**kwargs):
   if ctx.self_ref is g:
    seen.append(r.render(g)['native_text']['busy']);r.run_event(g,'OnSelect')
   return original(formula,ctx,*args,**kwargs)
  r.execute=execute;r.event(g.path,'OnSelect');assert seen==[True] and r.globals['count']==1 and not r.button_busy
  g.control=deepcopy(g.control);g.control.properties['OnSelect']='=Error({Kind:ErrorKind.Validation,Message:"Fictional label failure"})';r.invalidate();r.event(g.path,'OnSelect')
  assert not r.button_busy and not r.render(g)['native_text']['busy']
 finally:r.close()


def test_gallery_fluent_implicit_selection_and_text_is_static(tmp_path):
 p=Project(tmp_path/'gallery');p.update_source('Src/native.pa.yaml',dump_yaml({'Screens':{'Home':{'Children':[{'Rows':{'Control':'Gallery@2.15.0','Properties':{'Items':'=Table({ID:1,Title:"Left"},{ID:2,Title:"Right"})'},'Children':[{'Action':{'Control':KINDS[1],'Properties':{'Text':'=ThisItem.Title'}}},{'Static':{'Control':KINDS[0],'Properties':{'Text':'=ThisItem.Title'}}}]}}]}}}));r=Runtime(p);r.restart();r.state()
 try:
  rows=r.fx.evaluate('Rows.AllItems');g=rows[1]['Action'];assert g.raw_property('OnSelect')=='=Select(Parent)' and r.render(g)['selectable']
  r.event(g.path,'OnSelect');assert r.fx.evaluate('Rows.Selected.ID')==2
  assert not r.render(rows[1]['Static'])['selectable'] and not r.diagnostics
 finally:r.close()

@pytest.mark.parametrize('language',['en-US','fr-CA'])
@pytest.mark.parametrize('numbers',['float','decimal'])
@pytest.mark.parametrize('enums',['legacy','strong'])
def test_public_workflow_preserves_owner_source_data_runtime(tmp_path,language,numbers,enums):
 from powerapps_sim.fixtures import canvas_text_project
 from powerapps_sim.application import Workspace
 from powerapps_sim.authoring import revision,data_revision
 p=canvas_text_project(tmp_path/'public');w=Workspace(tmp_path,p.root,start=False)
 try:
  before=revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime(),w.ai.export_source()
  scenario=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario']);scenario['environment']={'language':language,'number_mode':numbers,'enum_mode':enums}
  result=w.workflows.run(scenario,expected_revision=before[0]);assert result['status']=='passed' and len(result['steps'])==41 and not result['diagnostics'],result
  assert before==(revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime(),w.ai.export_source())
 finally:w.runtime.close()


def test_first_party_windows_archive_preserves_native_text_and_labels(tmp_path):
 path=Path(__file__).parents[1]/'test-results/native-display-MDA_DisplayControls_1_0_0_1_managed.zip'
 if not path.exists():pytest.skip('Optional pinned archive unavailable')
 s=catalog()['Text']['0.0.47'];assert hashlib.sha256(path.read_bytes()).hexdigest()==s['artifact_sha256']
 with zipfile.ZipFile(path) as z:
  name=next(n for n in z.namelist() if n.endswith('.msapp'));p=Project.import_archive(z.read(name),tmp_path/'official')
 documents=dict(p.documents);r=Runtime(p)
 try:
  g=next(g for g in r.refs.values() if g.family=='Text');assert not r.render(g)['errors'] and g.property('Text')=='Text'
  labels=[g for g in r.refs.values() if g.family=='FluentV8/Label' and isinstance(g.raw_property('Text'),str) and g.raw_property('Text').startswith('="')]
  assert labels and all(not r.render(g)['errors'] for g in labels)
  assert p.documents==documents
 finally:r.close()
