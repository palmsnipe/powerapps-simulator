"""Classic scalar values cross component, form and reset boundaries."""
from pathlib import Path
import json
import pytest
from powerapps_sim.fixtures import classic_scalars_project
from powerapps_sim.runtime import Runtime,serial
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError
from powerapps_sim.classic_inputs import catalog
from powerapps_sim.binding import BOOLEAN,NUMBER,DATE

@pytest.fixture
def r(tmp_path):
 r=Runtime(classic_scalars_project(tmp_path/'p'));r.restart();r.state();assert not r.diagnostics
 yield r
 r.close()

def test_template_versions_defaults_and_public_outputs(r):
 assert catalog()['Classic/Toggle']['reference_version']=='2.1.0'
 assert catalog()['Classic/DatePicker']['reference_version']=='2.6.0'
 assert catalog()['Classic/Slider']['reference_version']=='2.0.1'
 assert 'unverified' in catalog()['Classic/Slider']['notes']
 assert serial(r.fx.evaluate('LeftPanel.Current'))=={'Enabled':False,'Amount':-5.0,'Day':'2026-01-15'}
 for name,prop,typ in [('Standalone','Value',BOOLEAN),('Vertical','Value',NUMBER),('DayInput','SelectedDate',DATE)]:assert r.binder.property_type(r.global_refs[name].control,prop)==typ
 assert r.fx.evaluate('ReadOnly.Value')==10 and not r.collections['history']

def test_toggle_committed_callbacks_deduplicate(r):
 ref=r.global_refs['Standalone'];r.event(ref.path,'OnChange',True)
 assert [x['Kind'] for x in r.collections['trace']]==['select','check','change']
 assert all(x['Enabled'] is True for x in r.collections['trace'])
 r.event(ref.path,'OnChange',True);assert len(r.collections['trace'])==4
 r.event(ref.path,'OnChange',False);assert [x['Kind'] for x in r.collections['trace']][-3:]==['select','uncheck','change']

def test_slider_preview_then_commit_deduplicate_and_component_isolation(r):
 ref=r.refs['ClassicScalars/LeftPanel/Amount'];r.event(ref.path,'OnInput',-3.25)
 assert r.fx.evaluate('LeftPanel.Current.Amount')==-3.25 and not r.collections['history']
 r.event(ref.path,'OnInput',2.5);r.event(ref.path,'OnChange',2.5)
 assert len(r.collections['history'])==1 and r.collections['history'][0]['Amount']==2.5
 r.event(ref.path,'OnChange',2.5);assert len(r.collections['history'])==1
 assert r.fx.evaluate('RightPanel.Current.Amount')==10
 r.event('ClassicScalars/ResetLeft','OnSelect');assert r.fx.evaluate('LeftPanel.Current.Amount')==-5
 assert not r.component_state['ClassicScalars/LeftPanel']['collections']['captured']

@pytest.mark.parametrize('value',[None,True,'5',float('nan'),float('inf'),{}, {'value':0,'reset_token':3}])
def test_invalid_slider_wires_do_not_mutate(r,value):
 with pytest.raises(ValueError):r.event('ClassicScalars/Vertical','OnChange',value)
 assert r.fx.evaluate('Vertical.Value')==0

def test_slider_bounds_null_defaults_readonly_and_dirty_clamp(r):
 ref=r.global_refs['Vertical'];ref.control.properties['Default']='=50';r.invalidate()
 assert ref.property('Value')==10
 r.event(ref.path,'OnInput',10);assert not ref.state['dirty']
 r.event(ref.path,'OnChange',-100);assert ref.property('Value')==-10 and ref.state['dirty']
 ref.control.properties.update(Default='=Blank()',Min='=Blank()',Max='=Blank()');r.invalidate()
 assert ref.property('Value')==0
 r.reset_ref(ref);r.invalidate();assert ref.property('Value')==50
 r.event('ClassicScalars/ReadOnly','OnChange',-10);assert r.fx.evaluate('ReadOnly.Value')==10

@pytest.mark.parametrize('family,path,output,wire',[
 ('toggle','ClassicScalars/Standalone','Value',{'checked':True}),
 ('slider','ClassicScalars/Vertical','Value',{'value':8}),
 ('date','ClassicScalars/DraftForm/DayCard/DayInput','SelectedDate',{'value':'2026-02-05','source':'calendar'})])
def test_reset_invalidates_pending_scalar_and_boolean_events(r,family,path,output,wire):
 ref=r.refs[path];node=r.render(ref);token=node['check_reset' if family=='toggle' else 'input_reset']
 before=serial(ref.property(output));r.reset_ref(ref);r.invalidate()
 r.event(path,'OnChange',{**wire,'reset_token':token})
 assert serial(ref.property(output))==before and not r.collections['history'] and not r.collections['trace']

def test_reactive_defaults_invalidate_slider_baseline_and_queued_events(r):
 ref=r.global_refs['Vertical'];token=r.render(ref)['input_reset'];r.event(ref.path,'OnInput',8)
 r.event('ClassicScalars/ChangeSeed','OnSelect');assert ref.property('Value')==1
 r.event(ref.path,'OnChange',{'value':8,'reset_token':token});assert ref.property('Value')==1
 assert 'slider_last_change' not in ref.state

def test_date_typed_custom_format_year_bounds_calendar_and_language(r):
 ref=r.refs['ClassicScalars/LeftPanel/Day'];node=r.render(ref)
 assert node['calendar']['formatted']=='15/01/2026' and node['calendar']['start']=='2025-01-01'
 r.event(ref.path,'OnChange',{'value':'05/02/2026','source':'typed','reset_token':node['input_reset']})
 assert serial(ref.property('SelectedDate'))=='2026-02-05'
 assert r.collections['history'][0]['Day'].kind=='Date'
 token=r.render(ref)['input_reset'];count=len(r.collections['history'])
 r.event(ref.path,'OnCalendar',{'month':'2027-03','reset_token':token})
 assert r.render(ref)['calendar']['month']=='2027-03' and len(r.collections['history'])==count
 with pytest.raises(ValueError):r.event(ref.path,'OnCalendar',{'month':'2028-01','reset_token':token})
 with pytest.raises(ValueError):r.event(ref.path,'OnChange','2024-12-31')
 r.environment['language']='fr-CA';r.invalidate();assert r.render(ref)['calendar']['title']=='mars 2027'
 assert not r.diagnostics

@pytest.mark.parametrize('value',['31/02/2026','not a date','2028-01-01','2026-01-40'])
def test_invalid_date_preserves_value_and_callbacks(r,value):
 ref=r.refs['ClassicScalars/LeftPanel/Day'];node=r.render(ref)
 with pytest.raises(ValueError):r.event(ref.path,'OnChange',{'value':value,'source':'typed','reset_token':node['input_reset']})
 assert serial(ref.property('SelectedDate'))=='2026-01-15' and not r.collections['history']

def test_date_noneditable_and_temporal_zone_defaults(r):
 ref=r.refs['ClassicScalars/LeftPanel/Day'];ref.control.properties.update(IsEditable='=false',DefaultDate='=DateTimeValue("2026-01-02T01:00:00Z")',Format='=DateTimeFormat.LongDate');r.environment['clock']='2026-01-01T12:00:00-05:00';r.invalidate()
 assert serial(ref.property('SelectedDate'))=='2026-01-01'
 ref.control.properties['DateTimeZone']='=DateTimeZone.UTC';r.invalidate();assert serial(ref.property('SelectedDate'))=='2026-01-02'
 with pytest.raises(ValueError):r.event(ref.path,'OnChange',{'value':'03/01/2026','source':'typed','reset_token':r.render(ref)['input_reset']})
 r.event(ref.path,'OnChange','2026-01-03');assert serial(ref.property('SelectedDate'))=='2026-01-03'

@pytest.mark.parametrize('props',[{'StartYear':'=2028','EndYear':'=2027'}, {'StartYear':'=999'}, {'EndYear':'=10000'}, {'StartYear':'=2025.5'}, {'IsEditable':'="yes"'}, {'DateTimeZone':'="other"'}])
def test_date_invalid_contract_visible_isolated(r,props):
 ref=r.refs['ClassicScalars/LeftPanel/Day'];ref.control.properties.update(props);r.invalidate()
 assert r.render(ref)['errors'] and r.fx.evaluate('RightPanel.Current.Amount')==10

def test_form_mapped_boolean_number_date_failure_retry_reset(r):
 r.event('ClassicScalars/DraftForm/EnabledCard/EnabledInput','OnChange',False)
 r.event('ClassicScalars/DraftForm/AmountCard/AmountInput','OnChange',-12.5)
 r.event('ClassicScalars/DraftForm/DayCard/DayInput','OnChange','2026-04-05')
 assert r.fx.evaluate('DraftForm.Valid') and r.fx.evaluate('DraftForm.Unsaved')
 r.store.failures['Drafts']='write';r.event('ClassicScalars/Save','OnSelect');assert r.globals['status']=='Save failed'
 assert r.store.rows('Drafts')[0]['Project Amount']==-5
 r.store.failures.clear();r.event('ClassicScalars/Save','OnSelect');assert r.globals['status']=='Saved'
 row=r.store.rows('Drafts')[0];assert row['Is Enabled'] is False and row['Project Amount']==-12.5 and row['Target Date']=='2026-04-05'
 assert not r.fx.evaluate('DraftForm.Unsaved')
 r.event('ClassicScalars/ClearDate','OnSelect');assert not r.fx.evaluate('DraftForm.Valid')
 r.event('ClassicScalars/Save','OnSelect');assert r.globals['status']=='Save failed'
 r.event('ClassicScalars/RestoreDate','OnSelect');r.event('ClassicScalars/ResetForm','OnSelect');assert r.fx.evaluate('DraftForm.Valid') and not r.fx.evaluate('DraftForm.Unsaved')
 assert not r.diagnostics

@pytest.mark.parametrize('control,prop',[('Standalone','Checked'),('Vertical','Step'),('DayInput','StartDate'),('DayInput','SelectedDate'),('DayInput','DateFontSize')])
def test_incompatible_authored_properties_remain_visible(r,control,prop):
 ref=r.global_refs[control];ref.control.properties[prop]='=1';r.invalidate();assert r.render(ref)['errors']
