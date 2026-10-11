"""Output publication is separate from modern text input blur behavior."""
from copy import deepcopy
import pytest
from powerapps_sim.fixtures import text_project
from powerapps_sim.fx import Context
from powerapps_sim.runtime import Runtime
from powerapps_sim.syntax import FxError

@pytest.fixture
def text_app(tmp_path):
    r=Runtime(text_project(tmp_path/'text'));r.restart();r.state()
    yield r;r.close()

def publish(r,name,value,event='OnInput',token=None):
    ref=r.global_refs.get(name) or r.refs[name]
    if token is not None:value={'text':value,'reset_token':token}
    r.event(ref.path,event,value)

def test_version_defaults_form_default_and_enum_binding(text_app):
    r=text_app
    assert r.fx.evaluate('Keys.Type')=='SingleLine'
    assert r.fx.evaluate('Focus.Type')=='Text'
    assert r.fx.evaluate('Keys.TriggerOutput')=='Keypress'
    assert r.fx.evaluate('FormTitle.TriggerOutput')=='Delayed'
    assert r.fx.evaluate('TextInputType.SingleLine')=='SingleLine'
    assert r.fx.evaluate('ReadOnly.Text')=='Selectable read-only text'
    assert not r.diagnostics

def test_keypress_publishes_reactivity_without_running_onchange(text_app):
    r=text_app;publish(r,'Keys','first');publish(r,'Keys','second')
    assert r.fx.evaluate('Keys.Text')=='second' and r.collections.get('events',[])==[]
    assert r.global_refs['KeysValue'].property('Text')=='Output: second'
    publish(r,'Keys','second','OnChange')
    assert r.collections['events']==[{'Kind':'Keys','Value':'second'}]
    publish(r,'Keys','second','OnChange')
    assert len(r.collections['events'])==1 and not r.diagnostics

def test_change_back_before_blur_has_no_callback(text_app):
    r=text_app;publish(r,'Keys','temporary');publish(r,'Keys','');publish(r,'Keys','','OnChange')
    assert r.fx.evaluate('Keys.Text')=='' and not r.global_refs['Keys'].state['dirty']
    assert r.collections.get('events',[])==[]

def test_focusout_rejects_early_publication_and_commits_on_blur(text_app):
    r=text_app
    with pytest.raises(ValueError,match='only on blur'):publish(r,'Focus','draft')
    assert r.fx.evaluate('Focus.Text')==''
    publish(r,'Focus','draft','OnChange')
    assert r.fx.evaluate('Focus.Text')=='draft' and r.collections['events']==[{'Kind':'Focus','Value':'draft'}]

@pytest.mark.parametrize('name',['Keys','Delayed','Password','SearchInput'])
def test_blank_and_unchanged_blur_do_not_fire(name,text_app):
    r=text_app;publish(r,name,None,'OnChange');publish(r,name,'','OnChange')
    assert r.fx.evaluate(name+'.Text')=='' and r.collections.get('events',[])==[]

def test_delayed_output_is_published_without_callback_until_blur(text_app):
    r=text_app;publish(r,'Delayed','delayed result')
    assert r.fx.evaluate('Delayed.Text')=='delayed result' and r.collections.get('events',[])==[]
    publish(r,'Delayed','delayed result','OnChange')
    assert r.collections['events']==[{'Kind':'Delayed','Value':'delayed result'}]

def test_form_output_dirties_and_updates_before_blur_then_saves(text_app):
    r=text_app;publish(r,'FormTitle','Typed title')
    assert r.fx.evaluate('NoteForm.Unsaved') is True
    assert r.fx.evaluate('NoteForm.Updates.Title')=='Typed title'
    assert r.collections.get('events',[])==[]
    publish(r,'FormTitle','Typed title','OnChange');r.event('TextOutputs/Save','OnSelect')
    assert r.fx.evaluate('NoteForm.LastSubmit.Title')=='Typed title'
    assert r.store.rows('Notes')[0]['Title']=='Typed title'
    assert r.collections['events']==[{'Kind':'form','Value':'Typed title'},{'Kind':'saved','Value':'Typed title'}]
    assert r.fx.evaluate('NoteForm.Unsaved') is False

def test_reset_invalidates_pending_token_and_does_not_notify(text_app):
    r=text_app;ref=r.global_refs['Delayed'];node=r.render(ref);token=node['text_reset']
    publish(r,'Delayed','published',token=token)
    r.fx.evaluate('Reset(Delayed)',Context(r,behavior=True))
    assert r.render(ref)['text_reset']!=token
    publish(r,'Delayed','stale','OnChange',token=token)
    assert r.fx.evaluate('Delayed.Text')=='' and r.collections.get('events',[])==[]

def test_changed_default_invalidates_pending_and_callback_baseline(text_app):
    r=text_app;token=r.render(r.global_refs['Keys'])['text_reset'];publish(r,'Keys','pending',token=token)
    r.event('TextOutputs/ChangeSeed','OnSelect');new=r.render(r.global_refs['Keys'])
    assert new['value']=='+' and new['text_reset']!=token
    publish(r,'Keys','pending','OnChange',token=token);publish(r,'Keys','+','OnChange')
    assert r.collections.get('events',[])==[] and r.fx.evaluate('Keys.Text')=='+'

def test_form_record_switch_and_save_invalidate_pending_edits(text_app):
    r=text_app;ref=r.global_refs['FormTitle'];token=r.render(ref)['text_reset']
    publish(r,'FormTitle','saved',token=token);r.event('TextOutputs/Save','OnSelect')
    publish(r,'FormTitle','late','OnChange',token=token)
    assert r.store.rows('Notes')[0]['Title']=='saved' and r.fx.evaluate('FormTitle.Text')=='saved'
    token=r.render(ref)['text_reset'];r.global_refs['NoteForm'].control.properties['Item']='=Last(Notes)';r.invalidate();r.state()
    assert r.render(ref)['text_reset']!=token
    publish(r,'FormTitle','old record','OnChange',token=token)
    assert r.fx.evaluate('FormTitle.Text')=='Gamma note'

def test_restart_invalidates_pending_tokens(text_app):
    r=text_app;token=r.render(r.global_refs['Keys'])['text_reset'];publish(r,'Keys','before',token=token)
    r.restart();r.state();publish(r,'Keys','late','OnChange',token=token)
    assert r.fx.evaluate('Keys.Text')=='' and r.collections.get('events',[])==[]

@pytest.mark.parametrize('mode',['Disabled','View'])
def test_output_and_callbacks_gated_by_ancestor_mode(text_app,mode):
    r=text_app;r.global_refs['NoteForm'].control.properties['DisplayMode']=f'=DisplayMode.{mode}';r.invalidate()
    publish(r,'FormTitle','blocked');publish(r,'FormTitle','blocked','OnChange')
    assert r.fx.evaluate('FormTitle.Text')=='Alpha note' and r.collections.get('events',[])==[]

def test_component_output_and_typed_blur_callback_are_isolated(text_app):
    r=text_app;path='TextOutputs/LeftText/Inner';publish(r,path,'left')
    assert r.fx.evaluate('LeftText.Value')=='left' and r.fx.evaluate('RightText.Value')==''
    assert r.collections.get('events',[])==[]
    publish(r,path,'left','OnChange');assert r.collections['events']==[{'Kind':'LeftText','Value':'left'}]
    r.fx.evaluate('Reset(LeftText)',Context(r,behavior=True));assert r.fx.evaluate('LeftText.Value')==''

@pytest.mark.parametrize('bad',[1,True,[],{'text':'bad','reset_token':True},{'text':'bad','reset_token':0,'other':1}])
def test_invalid_browser_payload_is_atomic(text_app,bad):
    r=text_app;before=deepcopy(r.globals)
    with pytest.raises(ValueError):publish(r,'Keys',bad)
    assert r.fx.evaluate('Keys.Text')=='' and r.globals==before and r.collections.get('events',[])==[]

def test_limits_use_native_utf16_length_and_allow_blank_limit(text_app):
    r=text_app;ref=r.global_refs['Keys'];ref.control.properties['MaxLength']='=2';r.invalidate()
    publish(r,'Keys','😀');assert r.fx.evaluate('Keys.Text')=='😀'
    with pytest.raises(ValueError,match='MaxLength'):publish(r,'Keys','😀x')
    assert r.fx.evaluate('Keys.Text')=='😀'
    ref.control.properties['MaxLength']='=Blank()';r.invalidate();publish(r,'Keys','unlimited')
    assert ref.property('MaxLength')==0

@pytest.mark.parametrize('prop,value',[('TriggerOutput','"bad"'),('MaxLength','true'),('MaxLength','-1'),('MaxLength','1.5'),('Type','"Unknown"'),('Required','"yes"'),('ValidationState','"bad"')])
def test_invalid_control_contracts_are_visible(text_app,prop,value):
    r=text_app;r.global_refs['Keys'].control.properties[prop]='='+value;r.invalidate()
    r.render(r.global_refs['Keys']);assert any(d['member']==f'Keys.{prop}' for d in r.diagnostics)

def test_search_output_recalculates_gallery_without_blur_callback(text_app):
    r=text_app;publish(r,'SearchInput','beta');tree=r.render(r.global_refs['Filtered'])
    assert len(tree['rows'])==1 and tree['rows'][0]['item']['Title']=='Beta note'
    assert r.collections.get('events',[])==[]


def test_previous_runtime_token_cannot_edit_new_instance_of_same_source(text_app):
    r=text_app;token=r.render(r.global_refs['Keys'])['text_reset']
    fresh=Runtime(r.project);fresh.restart();fresh.state()
    try:
        assert fresh.render(fresh.global_refs['Keys'])['text_reset']!=token
        publish(fresh,'Keys','old workspace','OnChange',token=token)
        assert fresh.fx.evaluate('Keys.Text')=='' and fresh.collections.get('events',[])==[]
    finally:fresh.close()


def test_authored_output_and_transport_properties_remain_visible_errors(text_app):
    r=text_app;ref=r.global_refs['Keys']
    ref.control.properties.update(Text='="invalid output override"',OnInput='=Blank()',Visible='=false')
    r.analyze()
    assert any(d['member']=='Keys.Text' and 'output' in d['message'] for d in r.diagnostics)
    assert any(d['member']=='Keys.OnInput' and 'no OnInput property' in d['message'] for d in r.diagnostics)
    with pytest.raises(FxError,match='output'):ref.property('Text')
    assert r.fx.evaluate('Focus.Text')==''


def test_stored_workflow_keeps_live_records_and_runtime_state(text_app):
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision
    r=text_app;w=Workspace(r.project.root.parent,r.project.root,start=False)
    try:
        before=w.runtime.state();records=deepcopy(w.runtime.store.rows('Notes'))
        entries=w.workflows.catalog()['scenarios'];assert len(entries)==1
        result=w.workflows.run(entries[0]['scenario'],expected_revision=revision(r.project.root))
        assert result['status']=='passed',result['steps']
        assert not result['diagnostics'] and w.runtime.store.rows('Notes')==records
        assert w.runtime.state()==before
    finally:w.runtime.close()
