"""Classic text/dropdown contracts, scopes, resets and mapped form persistence."""
from pathlib import Path
import pytest
from powerapps_sim.fixtures import classic_inputs_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.syntax import FxError
from powerapps_sim.fx import Context
from powerapps_sim.classic_inputs import catalog

@pytest.fixture
def r(tmp_path):
    r=Runtime(classic_inputs_project(tmp_path/'p'));r.restart();r.state();assert not r.diagnostics
    yield r
    r.close()

def test_verified_template_defaults_and_classic_outputs(r):
    spec=catalog();assert spec['Classic/TextInput']['version']=='2.3.2' and spec['Classic/DropDown']['version']=='2.3.1'
    node=r.render(r.global_refs['Immediate']);assert node['props']['Mode']=='SingleLine' and node['props']['Format']=='Text'
    assert node['props']['Height']==40 and node['props']['FocusedBorderThickness']==3 and node['value']=='hello'
    assert r.fx.evaluate('IsBlank(Optional.Selected)') is True
    assert r.fx.evaluate('RightPanel.Current.Stage')=='Review'
    assert r.binder.property_type(r.project.controls['Optional'][0],'SelectedText').fields['Value'].kind=='Text'

def test_immediate_output_separate_blur_callback_and_no_duplicate_event(r):
    r.event('ClassicInputs/LeftPanel/Inner','OnInput','Edited')
    assert r.fx.evaluate('LeftPanel.Current.Title')=='Edited' and not r.collections['history']
    r.event('ClassicInputs/LeftPanel/Inner','OnChange','Edited');r.event('ClassicInputs/LeftPanel/Inner','OnChange','Edited')
    assert len(r.collections['history'])==1
    assert r.collections['history'][0]=={'Panel':'LeftPanel','Title':'Edited','Stage':'Draft'}
    assert r.fx.evaluate('RightPanel.Current.Title')=='Beta'
    assert not r.diagnostics

def test_default_change_reset_tokens_and_stale_pending_drafts(r):
    ref=r.global_refs['Immediate'];old=r.render(ref)['text_reset']
    r.event(ref.path,'OnInput',{'text':'draft','reset_token':old})
    r.event('ClassicInputs/ChangeSeed','OnSelect')
    assert r.fx.evaluate('Immediate.Text')=='hello+'
    current=r.render(ref)['text_reset'];assert current!=old
    r.event(ref.path,'OnInput',{'text':'stale','reset_token':old});assert r.fx.evaluate('Immediate.Text')=='hello+'
    r.fx.evaluate('Reset(Immediate)',Context(r,behavior=True));assert r.render(ref)['text_reset']!=current
    assert not r.diagnostics

def test_component_reset_clears_only_owned_text_selection_and_collections(r):
    r.event('ClassicInputs/LeftPanel/Inner','OnChange','edited');r.event('ClassicInputs/RightPanel/Stage','OnChange',selection=[2])
    r.event('ClassicInputs/ResetLeft','OnSelect')
    assert r.fx.evaluate('LeftPanel.Current')=={'Title':'Alpha','Stage':'Draft'}
    assert r.fx.evaluate('RightPanel.Current.Stage')=='Done'
    assert not r.component_state['ClassicInputs/LeftPanel']['collections'].get('captured')
    assert len(r.component_state['ClassicInputs/RightPanel']['collections']['captured'])==1
    assert len(r.collections['history'])==2

def test_display_field_scalar_default_and_deprecated_selectedtext(r):
    ref=r.refs['ClassicInputs/RightPanel/Stage'];node=r.render(ref)
    assert [o['label'] for o in node['options']]==['Draft','In review','Completed']
    assert ref.property('Selected')['Code']=='Review' and ref.property('SelectedText')=={'Value':'In review'}
    r.event(ref.path,'OnChange',selection=[2]);assert ref.property('Selected')['Code']=='Done'
    assert ref.property('SelectedText')['Value']=='Completed'
    assert r.collections['history'][-1]['Stage']=='Done'

def test_default_fallback_and_empty_selection_contract(r):
    ref=r.refs['ClassicInputs/LeftPanel/Stage'];ref.control.properties['Default']='="missing"';r.invalidate()
    assert ref.property('Selected')['Code']=='Draft'
    with pytest.raises(ValueError,match='does not allow an empty'):r.event(ref.path,'OnChange',selection=[])
    optional=r.global_refs['Optional'];r.event(optional.path,'OnChange',selection=[1]);r.event(optional.path,'OnChange',selection=[])
    assert optional.property('Selected') is None and optional.property('SelectedText') is None
    ref.control.properties['AllowEmptySelection']='=true';r.invalidate();assert ref.property('Selected') is None

def test_removed_selected_record_falls_back_without_inventing_callback(r):
    ref=r.global_refs['Optional'];ref.control.properties['AllowEmptySelection']='=false';r.invalidate()
    r.event(ref.path,'OnChange',selection=[2]);ref.control.properties['Items']='=Table({Code:"Other",Caption:"Other"})';r.invalidate()
    assert ref.property('Selected')['Code']=='Other' and r.globals['status']=='Optional Completed'

def test_option_tokens_include_classic_display_contract_and_limit_500(r):
    ref=r.global_refs['Optional'];ref.control.properties['Items']='=ForAll(Sequence(501),{Caption:Text(Value),ID:Value})';r.invalidate()
    node=r.render(ref);assert len(node['options'])==500 and len(ref.property('Items'))==501
    with pytest.raises(ValueError,match='at most 500'):r.event(ref.path,'OnChange',selection=[500])
    token=node['option_token'];ref.control.properties['Value']='="ID"';r.invalidate()
    with pytest.raises(ValueError,match='Choices changed'):r.event(ref.path,'OnChange',{'indices':[0],'option_token':token})

def test_logical_display_column_names_work_with_sharepoint_records(r):
    ref=r.global_refs['Optional'];ref.control.properties.update(Items='=Drafts',Value='="Title"',Default='="Fictional draft"');r.invalidate()
    assert r.render(ref)['options'][0]['label']=='Fictional draft'
    assert ref.property('Selected')['Project Title']=='Fictional draft'
    assert ref.property('SelectedText')['Value']=='Fictional draft'

def test_stale_selection_is_rejected_after_reset_and_items_changes(r):
    ref=r.global_refs['Optional'];node=r.render(ref);r.fx.evaluate('Reset(Optional)',Context(r,behavior=True));r.state()
    with pytest.raises(ValueError,match='Choices changed'):r.event(ref.path,'OnChange',{'indices':[0],'option_token':node['option_token']})

def test_numeric_input_remains_text_and_checks_symbols_and_utf16_lengths(r):
    ref=r.global_refs['Numeric'];r.event(ref.path,'OnChange','1,25');assert r.fx.evaluate('Numeric.Text')=='1,25'
    assert type(ref.property('Text')) is str
    with pytest.raises(ValueError,match='numeric symbols'):r.event(ref.path,'OnInput','bad')
    delayed=r.global_refs['Delayed'];delayed.control.properties['MaxLength']='=2';r.invalidate()
    r.event(delayed.path,'OnInput','😀')
    with pytest.raises(ValueError,match='MaxLength'):r.event(delayed.path,'OnInput','😀a')
    assert delayed.property('Text')=='😀'

@pytest.mark.parametrize('family,prop,raw',[('Immediate','DelayOutput','=1'),('Immediate','Clear','="true"'),('Immediate','Mode','="RichText"'),('Immediate','Format','="Currency"'),('Immediate','VirtualKeyboardMode','="Email"'),('Immediate','MaxLength','=-1'),('Immediate','HoverColor','="green"'),('Optional','AllowEmptySelection','=0'),('Optional','Value','=false'),('Optional','Default','={Caption:"Draft"}')])
def test_invalid_properties_are_visible_and_isolated(r,family,prop,raw):
    ref=r.global_refs[family];ref.control.properties[prop]=raw;r.analyze();r.invalidate()
    assert r.render(ref)['errors'] and r.diagnostics
    assert ref.control.properties[prop]==raw and r.fx.evaluate('RightPanel.Current.Title')=='Beta'

@pytest.mark.parametrize('name,prop',[('Immediate','Text'),('Immediate','TriggerOutput'),('Immediate','OnInput'),('Optional','DefaultSelectedItems'),('Optional','ItemDisplayText'),('Optional','Selected')])
def test_modern_or_output_properties_remain_unsupported_without_rewriting_source(r,name,prop):
    ref=r.global_refs[name];ref.control.properties[prop]='=Blank()';r.analyze();r.invalidate()
    assert r.render(ref)['errors'] and any(d['kind']=='Unsupported' for d in r.diagnostics)
    assert prop in ref.control.properties

def test_disabled_view_and_hidden_ancestors_reject_text_and_selection_events(r):
    left=r.global_refs['LeftPanel'];left.control.properties['DisplayMode']='=DisplayMode.View';r.invalidate()
    r.event('ClassicInputs/LeftPanel/Inner','OnInput','changed');r.event('ClassicInputs/LeftPanel/Stage','OnChange',selection=[2])
    assert r.fx.evaluate('LeftPanel.Current')=={'Title':'Alpha','Stage':'Draft'}
    left.control.properties['Visible']='=false';r.invalidate();r.event('ClassicInputs/LeftPanel/Inner','OnChange','changed')
    assert not r.collections['history']

def test_classic_setfocus_supports_text_but_excludes_dropdown(r):
    r.event('ClassicInputs/FocusText','OnSelect');assert r.focus_request['path']=='ClassicInputs/Immediate'
    with pytest.raises(FxError,match='SetFocus does not support Classic/DropDown'):r.fx.evaluate('SetFocus(Optional)',Context(r,behavior=True))

def test_form_unsaved_validation_persistence_failed_write_and_recovery(r):
    path='ClassicInputs/DraftForm/TitleCard/TitleInput';r.event(path,'OnChange','Saved classic edit')
    assert r.fx.evaluate('DraftForm.Unsaved') is True
    r.store.failures['Drafts']='write'
    r.event('ClassicInputs/Save','OnSelect');assert r.globals['status']=='Save failed'
    assert r.fx.evaluate('TitleInput.Text')=='Saved classic edit' and r.fx.evaluate('First(Drafts).\'Project Title\'')=='Fictional draft'
    r.store.failures.clear();r.event('ClassicInputs/Save','OnSelect')
    assert r.fx.evaluate('First(Drafts).\'Project Title\'')=='Saved classic edit' and r.fx.evaluate('DraftForm.Unsaved') is False
    assert not r.diagnostics

def test_repeatable_packaged_scenario_retains_live_owner_and_source(tmp_path):
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision,data_revision
    p=classic_inputs_project(tmp_path/'p');w=Workspace(tmp_path,p.root,start=False)
    try:
        before=revision(p.root);data=data_revision(w.runtime.store);state=w.ai.read_runtime();scenario=w.workflows.catalog()['scenarios'][0]['scenario']
        for _ in range(2):
            result=w.workflows.run(scenario,expected_revision=before)
            assert result['status']=='passed' and len(result['steps'])==43 and not result['diagnostics'],result['steps']
        assert w.ai.read_runtime()==state and data_revision(w.runtime.store)==data and revision(p.root)==before
        assert 'Classic/TextInput@2.3.2' in (p.root/'Src/classic-inputs.pa.yaml').read_text()
    finally:w.runtime.close()
