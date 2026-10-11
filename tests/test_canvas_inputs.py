from copy import deepcopy
import pytest
from powerapps_sim.fixtures import canvas_inputs_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision,data_revision
from powerapps_sim.canvas_inputs import catalog,token
from powerapps_sim.syntax import FxError

@pytest.fixture
def r(tmp_path):
 r=Runtime(canvas_inputs_project(tmp_path/'owner'));r.restart();r.state();assert not r.diagnostics,r.diagnostics
 yield r;r.close()
def ref(r,name='Draft',panel='Left'):return r.refs[f'Home/{panel}/{name}']
def authored(r,g,**p):
 g.control=deepcopy(g.control);g.control.properties.update(p);r.invalidate()
def send(r,g,value,event=None,tok=None):
 r.event(g.path,event or ('OnChange' if g.family=='TextInput' else 'OnSelect'),{('text' if g.family=='TextInput' else 'checked'):value,'reset_token':tok or token(g)});r.state()

@pytest.mark.parametrize('language',['en-US','fr-CA'])
@pytest.mark.parametrize('numbers',['float','decimal'])
@pytest.mark.parametrize('enums',['legacy','strong'])
def test_isolated_workflow_and_owner_preservation(tmp_path,language,numbers,enums):
 p=canvas_inputs_project(tmp_path/'owner');w=Workspace(tmp_path,p.root,start=False)
 try:
  before=revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime(),w.ai.export_source()
  s=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario']);s['environment']={'language':language,'number_mode':numbers,'enum_mode':enums}
  result=w.workflows.run(s,expected_revision=before[0]);assert result['status']=='passed' and len(result['steps'])==24 and not result['diagnostics'],result
  assert before==(revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime(),w.ai.export_source())
 finally:w.runtime.close()

VERSIONS=[(f,v) for f,versions in catalog().items() for v in versions]
@pytest.mark.parametrize('family,version',VERSIONS)
def test_versions_native_defaults_and_bound_properties(r,family,version):
 g=ref(r,'Draft' if family=='TextInput' else 'Approved');g.control=deepcopy(g.control);g.control.kind=family+'@'+version;g.control.raw['Properties']={};r.invalidate();r.state()
 prop='Value' if family=='TextInput' else 'Checked';assert g.property(prop)==('' if family=='TextInput' else False)
 for p in catalog()[family][version]['types']:
  g.property(p)
 assert g.property('Width')==(320 if family=='TextInput' else 160) and g.property('Height')==32
 if family=='TextInput':assert g.property('TriggerOutput')=='FocusOut' and g.property('MaxLength')==-1
 assert not r.diagnostics,r.diagnostics
 assert r.binder.property_type(g.control,prop).kind==('Text' if family=='TextInput' else 'Boolean')

@pytest.mark.parametrize('family,prop',[(f,p) for f,ps in {'TextInput':['Text','Default','OnSelect','DelayOutput','Selected','Unknown','Reset','PCFTeamsTheme'],'CheckBox':['Default','Value','OnChange','Unknown','Reset','PCFTeamsTheme']}.items() for p in ps])
def test_unsupported_authored_properties_preserved_and_isolated(r,family,prop):
 g=ref(r,'Draft' if family=='TextInput' else 'Approved');authored(r,g,**{prop:'=Blank()'});r.state()
 assert any(d['kind']=='Unsupported' for d in r.diagnostics)
 assert prop in g.control.properties and ref(r,panel='Right').property('Value')=='Fictional draft'

@pytest.mark.parametrize('family,version',[('TextInput','9.0.0'),('CheckBox','9.0.0')])
def test_unknown_versions_isolate_preview(r,family,version):
 g=ref(r,'Draft' if family=='TextInput' else 'Approved');g.control=deepcopy(g.control);g.control.kind=f'{family}@{version}';r.invalidate();r.state();assert r.diagnostics
 assert ref(r,panel='Right').property('Value')=='Fictional draft'

@pytest.mark.parametrize('prop,formula',[('Value','=42'),('Required','="yes"'),('MaxLength','=-2'),('MaxLength','=2.5'),('TabIndex','=0.5'),('FontSize','=-1'),('FontItalic','="true"'),('Mode','="MultiLine"'),('Type','="Email"'),('TriggerOutput','="Immediate"'),('Appearance','="Primary"'),('BorderRadius','=-2'),('Fill','=3'),('Align','="Invalid"')])
def test_invalid_properties_are_visible_without_peer_failure(r,prop,formula):
 g=ref(r);g.control=deepcopy(g.control);g.control.kind='TextInput@0.0.51';authored(r,g,**{prop:formula});r.state();assert r.diagnostics,(prop,r.diagnostics)
 assert ref(r,panel='Right').property('Value')=='Fictional draft'

@pytest.mark.parametrize('prop,formula',[('Checked','="yes"'),('Label','=7'),('CheckboxSize','=-1'),('FontSize','="large"'),('FontUnderline','=1'),('FontColor','=true')])
def test_checkbox_type_validation(r,prop,formula):
 authored(r,ref(r,'Approved'),**{prop:formula});r.state();assert r.diagnostics

@pytest.mark.parametrize('blank',[False,True])
def test_bound_text_and_checkbox_defaults_resets_and_tokens(r,blank):
 text=ref(r);check=ref(r,'Approved')
 if blank:authored(r,text,Value='=Blank()');authored(r,check,Checked='=Blank()');r.state()
 old=token(text);send(r,text,'New draft');send(r,check,True)
 assert r.fx.evaluate('Left.CurrentText="New draft" && Left.CurrentChecked && CountRows(Left.History)=2 && CountRows(Right.History)=0')
 r.event('Home/ResetLeft','OnSelect');r.state();assert text.property('Value')==(None if blank else 'Fictional draft') and check.property('Checked') is False
 send(r,text,'Stale',tok=old);assert text.property('Value')==(None if blank else 'Fictional draft')
 assert not r.diagnostics
 if blank:
  send(r,check,False);assert check.state.get('dirty') is False

@pytest.mark.parametrize('mode',['FocusOut','Keypress','Delayed'])
def test_trigger_output_commits_once_and_callback_sees_server_value(r,mode):
 g=ref(r);authored(r,g,TriggerOutput='="'+mode+'"');r.state()
 if mode=='FocusOut':
  with pytest.raises(ValueError,match='blur'):send(r,g,'New','OnInput')
  assert g.property('Value')=='Fictional draft'
 else:send(r,g,'New','OnInput')
 send(r,g,'New','OnChange');assert len(r.collections['events'])==1 and r.collections['events'][0]['Text']=='New'
 send(r,g,'New','OnChange');assert len(r.collections['events'])==1

def test_blank_focusout_without_change_preserves_blank(r):
 g=ref(r);authored(r,g,Value='=Blank()');r.state();send(r,g,'');assert g.property('Value') is None and not r.collections['events']

@pytest.mark.parametrize('maximum,text,valid',[(0,'',True),(0,'a',False),(-1,'a'*1000,True),(1,'é',True),(1,'e\u0301',False),(1,'😀',False),(2,'😀',True),(2,'😀x',False)])
def test_max_length_guard_uses_utf16_units(r,maximum,text,valid):
 g=ref(r);authored(r,g,Value='=""',MaxLength='='+str(maximum));r.state()
 if valid:send(r,g,text);assert g.property('Value')==text
 else:
  with pytest.raises(ValueError,match='MaxLength'):send(r,g,text)
  assert g.property('Value')==''

@pytest.mark.parametrize('prop,formula',[('MaxLength','=8'),('TriggerOutput','="Keypress"'),('Mode','="Multiline"'),('Type','="Password"')])
def test_changed_text_contract_invalidates_pending_drafts(r,prop,formula):
 g=ref(r);old=token(g);authored(r,g,**{prop:formula});r.state();assert token(g)!=old
 send(r,g,'Stale',tok=old);assert g.property('Value')=='Fictional draft'

def test_password_multiline_is_explicitly_unsupported(r):
 authored(r,ref(r),Mode='="Multiline"',Type='="Password"');r.state();assert any(d['kind']=='Unsupported' for d in r.diagnostics)

@pytest.mark.parametrize('mode',['Disabled','View'])
@pytest.mark.parametrize('family',['TextInput','CheckBox'])
def test_native_control_display_modes_gate_events(r,mode,family):
 g=ref(r,'Draft' if family=='TextInput' else 'Approved');authored(r,g,DisplayMode='=DisplayMode.'+mode);send(r,g,'New' if family=='TextInput' else True);assert not r.collections['events']

def test_hidden_ancestor_and_stale_checkbox_default(r):
 g=ref(r,'Approved');old=token(g);r.globals['initialChecked']=True;r.invalidate();r.state();send(r,g,False,tok=old);assert g.property('Checked') is True
 authored(r,g.parent,Visible='=false');send(r,g,False);assert g.property('Checked') is True and not r.collections['events']

@pytest.mark.parametrize('family,data',[('TextInput',True),('TextInput',{'text':3,'reset_token':'x'}),('TextInput',{'text':'x'}),('CheckBox','true'),('CheckBox',{'checked':1,'reset_token':'x'}),('CheckBox',{'checked':True,'reset_token':False}),('TextInput',{'text':'x','reset_token':'x','extra':1})])
def test_malformed_events_rejected_without_writes(r,family,data):
 g=ref(r,'Draft' if family=='TextInput' else 'Approved')
 if isinstance(data,dict) and data.get('reset_token')=='x':data={**data,'reset_token':token(g)}
 with pytest.raises((ValueError,FxError)):r.event(g.path,'OnChange' if family=='TextInput' else 'OnSelect',data)
 assert not r.collections['events']

def test_checkbox_only_select_and_programmatic_select(r):
 g=ref(r,'Approved');send(r,g,True);send(r,g,True);assert len(r.collections['events'])==2
 r.event(g.path,'OnSelect');assert len(r.collections['events'])==3 and g.property('Checked') is True
 with pytest.raises(ValueError):r.event(g.path,'OnChange',False)
 with pytest.raises(ValueError):r.event(ref(r).path,'OnSelect')

def test_form_failed_save_recovery_persists_mapped_values(r):
 g=r.refs['Home/NoteForm/TitleCard/FormTitle'];check=r.refs['Home/NoteForm/ApprovedCard/FormApproved'];form=r.refs['Home/NoteForm']
 send(r,g,'Fictional recovered');send(r,check,True);assert form.property('Unsaved')
 r.store.failures['Notes']='write';r.event('Home/Save','OnSelect');r.state();assert form.property('Unsaved') and form.property('LastSubmit') is None and r.store.rows('Notes')[0]['Note title']=='Fictional note 1'
 r.store.failures.clear();r.event('Home/Save','OnSelect');r.state();assert not form.property('Unsaved') and r.fx.evaluate('NoteForm.LastSubmit.Approved') is True
 assert r.fx.evaluate('First(Notes).\'Note title\'="Fictional recovered" && First(Notes).\'Note approved\'')
 from powerapps_sim.store import ListStore
 store=ListStore(r.project.root/'data.sqlite',schema_root=r.project.root/'lists')
 try:assert store.rows('Notes')[0]['Note approved'] is True
 finally:store.close()

def test_form_required_blank_draft_retained(r):
 g=r.refs['Home/NoteForm/TitleCard/FormTitle'];send(r,g,'');r.event('Home/Save','OnSelect');r.state()
 assert r.refs['Home/NoteForm'].property('Unsaved') and not r.refs['Home/NoteForm'].property('Valid')
 assert g.property('Value')=='' and r.store.rows('Notes')[0]['Note title']=='Fictional note 1'

@pytest.mark.parametrize('version',['0.0.26','0.0.27','0.0.30'])
def test_check_uncheck_callbacks_commit_before_events(r,version):
 g=ref(r,'Approved');g.control=deepcopy(g.control);g.control.kind='CheckBox@'+version
 authored(r,g,OnCheck='=Collect(sequence,{Event:"Check",Checked:Self.Checked})',OnUncheck='=Collect(sequence,{Event:"Uncheck",Checked:Self.Checked})',OnSelect='=Collect(sequence,{Event:"Select",Checked:Self.Checked})')
 send(r,g,True);send(r,g,True);send(r,g,False);r.event(g.path,'OnSelect')
 assert [(v['Event'],v['Checked']) for v in r.component_state[g.component.path]['collections']['sequence']]==[('Check',True),('Select',True),('Select',True),('Uncheck',False),('Select',False),('Select',False)]

@pytest.mark.parametrize('version',['0.0.26','0.0.27','0.0.30'])
def test_reset_does_not_fire_check_callbacks(r,version):
 g=ref(r,'Approved');g.control=deepcopy(g.control);g.control.kind='CheckBox@'+version
 authored(r,g,OnUncheck='=Collect(history,{Kind:"Uncheck",Text:"",Checked:Self.Checked})')
 send(r,g,True);before=deepcopy(r.component_state[g.component.path]['collections']['history']);r.reset_ref(g);r.state()
 assert g.property('Checked') is False and r.component_state[g.component.path]['collections']['history']==before

def test_native_text_setfocus_and_existing_boundary_restrictions(r):
 from powerapps_sim.focus import validate_target
 g=r.refs['Home/Delayed'];validate_target(g.control)
 r.execute('SetFocus(Delayed)',r.refs['Home'].context(True));assert r.focus_request['path']==g.path
 with pytest.raises(FxError,match='inside'):validate_target(ref(r).control)
 with pytest.raises(FxError,match='support'):validate_target(ref(r,'Approved').control)
