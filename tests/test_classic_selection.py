"""Classic Boolean/radio contracts with component, form and gallery scopes."""
from pathlib import Path
import pytest
from powerapps_sim.fixtures import classic_selection_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError
from powerapps_sim.binding import BOOLEAN,TEXT
from powerapps_sim.classic_inputs import catalog

@pytest.fixture
def r(tmp_path):
 r=Runtime(classic_selection_project(tmp_path/'p'));r.restart();r.state();assert not r.diagnostics
 yield r
 r.close()

def test_defaults_version_provenance_and_public_types(r):
 spec=catalog()['Classic/CheckBox'];assert spec['reference_version']=='2.0.1' and spec['version']=='2.1.0'
 assert 'unverified' in spec['notes'] and spec['archive_sha256']
 assert catalog()['Classic/Radio']['approximate_defaults']
 assert r.fx.evaluate('LeftPanel.Current')=={'Enabled':False,'Stage':'Draft'}
 assert r.fx.evaluate('RightPanel.Current')=={'Enabled':True,'Stage':'Review'}
 assert r.binder.property_type(r.global_refs['Standalone'].control,'Value')==BOOLEAN
 assert r.binder.property_type(r.refs['ClassicSelection/LeftPanel/Choice'].control,'Value')==TEXT
 assert r.fx.evaluate('Standalone.Value') is False and not r.collections['trace']
 assert not r.component_state.get('ClassicSelection/LeftPanel',{}).get('collections',{}).get('captured')

def test_checkbox_select_and_change_callbacks_observe_committed_value_and_deduplicate(r):
 ref=r.global_refs['Standalone'];r.event(ref.path,'OnChange',True)
 assert r.collections['trace']==[{'Kind':'select','Enabled':True},{'Kind':'check','Enabled':True}]
 r.event(ref.path,'OnChange',True)
 assert len(r.collections['trace'])==3 and r.collections['trace'][-1]['Kind']=='select'
 r.event(ref.path,'OnChange',False)
 assert r.collections['trace'][-2:]==[{'Kind':'select','Enabled':False},{'Kind':'uncheck','Enabled':False}]
 assert not r.diagnostics

def test_checkbox_reset_and_reactive_default_invalidate_pending_events_without_callbacks(r):
 ref=r.global_refs['Standalone'];node=r.render(ref)
 r.event(ref.path,'OnChange',{'checked':True,'reset_token':node['check_reset']})
 assert ref.property('Value') is True
 r.fx.evaluate('Reset(Standalone)',Context(r,behavior=True));new=r.render(ref)
 assert new['check_reset']!=node['check_reset'] and new['value'] is False
 trace=list(r.collections['trace']);r.event(ref.path,'OnChange',{'checked':True,'reset_token':node['check_reset']})
 assert ref.property('Value') is False and r.collections['trace']==trace
 r.event('ClassicSelection/ChangeSeed','OnSelect');current=r.render(ref)
 assert current['check_reset']!=new['check_reset'] and current['value'] is True
 r.event(ref.path,'OnChange',{'checked':False,'reset_token':new['check_reset']})
 assert ref.property('Value') is True and r.collections['trace']==trace

@pytest.mark.parametrize('value',[1,0,None,'true',{}, {'checked':'true','reset_token':'old'}, {'checked':True,'reset_token':'old','other':0}])
def test_bad_checkbox_wire_values_do_not_mutate_state(r,value):
 with pytest.raises(ValueError):r.event('ClassicSelection/Standalone','OnChange',value)
 assert r.fx.evaluate('Standalone.Value') is False and not r.collections['trace']

def test_component_checkbox_radio_callbacks_and_reset_remain_isolated(r):
 r.event('ClassicSelection/LeftPanel/Agree','OnChange',True)
 r.event('ClassicSelection/RightPanel/Choice','OnChange',selection=[2])
 assert r.collections['history']==[{'Panel':'LeftPanel','Enabled':True,'Stage':'Draft'},{'Panel':'RightPanel','Enabled':True,'Stage':'Done'}]
 assert r.component_state['ClassicSelection/LeftPanel']['collections']['selects'][0]['Enabled'] is True
 r.event('ClassicSelection/ResetLeft','OnSelect')
 assert r.fx.evaluate('LeftPanel.Current')=={'Enabled':False,'Stage':'Draft'}
 assert r.fx.evaluate('RightPanel.Current')=={'Enabled':True,'Stage':'Done'}
 assert r.component_state['ClassicSelection/LeftPanel']['collections']['captured']==[]
 assert len(r.component_state['ClassicSelection/RightPanel']['collections']['captured'])==1
 assert len(r.collections['history'])==2 and not r.diagnostics

def test_radio_display_default_and_selectedtext_contract(r):
 ref=r.refs['ClassicSelection/RightPanel/Choice'];node=r.render(ref)
 assert [o['label'] for o in node['options']]==['Draft','In review','Completed']
 assert ref.property('Value')=='Caption' and ref.property('SelectedText')=='In review'
 ref.control.properties['Default']='="missing"';r.invalidate();assert ref.property('Selected') is None
 assert ref.property('SelectedText') is None
 r.event(ref.path,'OnChange',selection=[0]);assert ref.property('Selected')=={'Code':'Draft','Caption':'Draft'}
 assert ref.property('SelectedText')=='Draft'
 assert r.binder.property_type(ref.control,'SelectedText')==TEXT

def test_numeric_scalar_default_and_logical_display_mapping(r):
 ref=r.refs['ClassicSelection/RightPanel/Choice'];ref.control.properties.update(Items='=Table({Caption:"1",Code:"Low"},{Caption:"2",Code:"High"})',Default='=2');r.invalidate()
 assert ref.property('Selected')['Code']=='High'
 ref=r.global_refs['StageInput'];ref.control.properties.update(Items='=Drafts',Value='="Title"',Default='="Fictional first draft"');r.invalidate()
 assert r.render(ref)['options'][0]['label']=='Fictional first draft'
 assert ref.property('Selected')['ID']==1

def test_radio_select_without_change_no_duplicate_typed_callback(r):
 ref=r.refs['ClassicSelection/RightPanel/Choice'];r.event(ref.path,'OnChange',selection=[1])
 assert not r.collections['history'] and len(r.component_state['ClassicSelection/RightPanel']['collections']['selects'])==1
 r.event(ref.path,'OnChange',selection=[2]);assert len(r.collections['history'])==1
 r.event(ref.path,'OnChange',selection=[2]);assert len(r.collections['history'])==1
 assert len(r.component_state['ClassicSelection/RightPanel']['collections']['selects'])==3

def test_radio_removed_row_and_reactive_seed_fallback_do_not_invent_events(r):
 ref=r.refs['ClassicSelection/RightPanel/Choice'];r.event(ref.path,'OnChange',selection=[2])
 ref.control.properties['Items']='=Table({Caption:"In review",Code:"Review"})';r.invalidate()
 assert ref.property('Selected')['Code']=='Review' and len(r.collections['history'])==1
 ref.control.properties['Items']='=Table({Caption:"Other",Code:"Other"})';r.invalidate()
 assert ref.property('Selected') is None and len(r.collections['history'])==1

def test_radio_option_contract_and_reset_tokens_reject_stale_selection(r):
 ref=r.refs['ClassicSelection/RightPanel/Choice'];node=r.render(ref)
 r.fx.evaluate('Reset(RightPanel)',Context(r,behavior=True));r.state()
 with pytest.raises(ValueError,match='Choices changed'):r.event(ref.path,'OnChange',{'indices':[2],'option_token':node['option_token']})
 assert ref.property('Selected')['Code']=='Review' and not r.collections['history']
 fresh=r.render(ref);ref.control.properties['Value']='="Code"';r.invalidate()
 with pytest.raises(ValueError,match='Choices changed'):r.event(ref.path,'OnChange',{'indices':[2],'option_token':fresh['option_token']})

def test_french_radio_translation_keeps_codes_and_typed_component_values(r):
 r.environment['language']='fr-CA';r.restart();r.state()
 ref=r.refs['ClassicSelection/RightPanel/Choice']
 assert [o['label'] for o in r.render(ref)['options']]==['Brouillon','À examiner','Terminé']
 assert ref.property('SelectedText')=='À examiner' and r.fx.evaluate('RightPanel.Current.Stage')=='Review'
 r.event(ref.path,'OnChange',selection=[2]);assert r.collections['history'][0]['Stage']=='Done'
 assert not r.diagnostics

@pytest.mark.parametrize('control,prop,raw',[('Standalone','Default','="true"'),('Standalone','CheckboxSize','=-1'),('Standalone','CheckmarkFill','="red"'),('Standalone','TabIndex','=1.5'),('StageInput','Layout','="Diagonal"'),('StageInput','RadioSize','=-1'),('StageInput','RadioSelectionFill','="red"'),('StageInput','Default','={Code:"Draft"}')])
def test_invalid_property_types_are_visible_and_source_is_preserved(r,control,prop,raw):
 ref=r.global_refs[control];ref.control.properties[prop]=raw;r.analyze();r.invalidate()
 assert r.render(ref)['errors'] and r.diagnostics
 assert ref.control.properties[prop]==raw and r.fx.evaluate('RightPanel.Current.Enabled') is True

@pytest.mark.parametrize('control,prop',[('Standalone','Value'),('Standalone','Checked'),('Standalone','OnChange'),('Standalone','Label'),('StageInput','Selected'),('StageInput','SelectedText'),('StageInput','ItemDisplayText'),('StageInput','AllowEmptySelection')])
def test_modern_only_and_output_properties_are_reported_without_repair(r,control,prop):
 ref=r.global_refs[control];ref.control.properties[prop]='=Blank()';r.analyze();r.invalidate()
 assert r.render(ref)['errors'] and any(d['kind']=='Unsupported' for d in r.diagnostics)
 assert prop in ref.control.properties

def test_required_boolean_false_form_and_missing_radio_failed_save_recovery(r):
 r.event('ClassicSelection/DraftForm/EnabledCard/EnabledInput','OnChange',False)
 assert r.fx.evaluate('DraftForm.Valid') is True and r.fx.evaluate('DraftForm.Unsaved') is True
 r.event('ClassicSelection/Save','OnSelect');assert r.fx.evaluate("LookUp(Drafts,ID=1).'Is Enabled'") is False
 assert r.fx.evaluate('DraftForm.Unsaved') is False
 r.event('ClassicSelection/ClearStage','OnSelect');assert r.fx.evaluate('DraftForm.Valid') is False
 r.event('ClassicSelection/Save','OnSelect');assert r.globals['status']=='Save failed'
 assert r.fx.evaluate("LookUp(Drafts,ID=1).'Project Stage'")=='Draft'
 r.event('ClassicSelection/Restore','OnSelect');assert r.fx.evaluate('DraftForm.Valid') is True
 assert r.fx.evaluate('EnabledInput.Value') is False and not r.diagnostics

def test_gallery_checkbox_patch_row_scope_mappings_selection_and_reactive_form(r):
 r.state();paths=[p for p,ref in r.refs.items() if ref.name=='RowEnabled'];assert len(paths)==2
 r.event(paths[1],'OnChange',True);r.state()
 assert r.store.rows('Drafts')[1]['Is Enabled'] is True
 assert r.fx.evaluate('Rows.Selected.ID')==2 and r.globals['status']=='Selected Fictional second draft'
 assert r.fx.evaluate('EnabledInput.Value') is True
 r.event(paths[0],'OnChange',False);r.state()
 assert r.store.rows('Drafts')[0]['Is Enabled'] is False and r.fx.evaluate('EnabledInput.Value') is False
 assert r.fx.evaluate('DraftForm.Unsaved') is False and not r.diagnostics

def test_view_disabled_ancestor_gates_and_negative_tab_index(r):
 r.event('ClassicSelection/ReadOnly','OnChange',False);r.event('ClassicSelection/Disabled','OnChange',True)
 assert r.fx.evaluate('ReadOnly.Value') is True and r.fx.evaluate('Disabled.Value') is False
 assert r.render(r.global_refs['PointerOnly'])['tab_stop'] is False
 r.global_refs['LeftPanel'].control.properties['DisplayMode']='=DisplayMode.View';r.invalidate()
 r.event('ClassicSelection/LeftPanel/Agree','OnChange',True);r.event('ClassicSelection/LeftPanel/Choice','OnChange',selection=[2])
 assert r.fx.evaluate('LeftPanel.Current')=={'Enabled':False,'Stage':'Draft'} and not r.collections['history']
 for f in ('Standalone','StageInput'):
  with pytest.raises(FxError,match='SetFocus'):r.fx.evaluate(f'SetFocus({f})',Context(r,behavior=True))

def test_repeatable_packaged_scenario_owner_and_export_preservation(tmp_path):
 from powerapps_sim.application import Workspace
 from powerapps_sim.authoring import revision,data_revision
 p=classic_selection_project(tmp_path/'p');source=(p.root/'Src/classic-selection.pa.yaml').read_bytes();w=Workspace(tmp_path,p.root,start=False)
 try:
  before=w.ai.read_runtime();rev=revision(p.root);data=data_revision(w.runtime.store);scenario=w.workflows.catalog()['scenarios'][0]['scenario']
  for _ in range(2):
   result=w.workflows.run(scenario,expected_revision=rev)
   assert result['status']=='passed' and len(result['steps'])==58 and not result['diagnostics'],result['steps']
  assert w.ai.read_runtime()==before and revision(p.root)==rev and data_revision(w.runtime.store)==data
  assert (p.root/'Src/classic-selection.pa.yaml').read_bytes()==source
 finally:w.runtime.close()
