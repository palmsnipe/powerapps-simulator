"""Modern rating validation, scopes, resets, persistence and error isolation."""
from copy import deepcopy
import pytest
from powerapps_sim.fixtures import rating_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.syntax import FxError

@pytest.fixture
def r(tmp_path):
    result=Runtime(rating_project(tmp_path/'ratings'));result.restart();result.state()
    assert not result.diagnostics
    yield result;result.close()

def score(r,panel='LeftRating'):return r.refs['RatingLab/'+panel+'/Score']
def change(r,ref,value,token=None):
    r.event(ref.path,'OnChange',{'value':value,'reset_token':token if token is not None else r.scalar_token(ref)});r.state()
def authored(r,ref,**props):
    ref.control=deepcopy(ref.control);ref.control.properties.update(props);r.invalidate()

def test_documented_defaults_version_and_half_steps(r):
    g=score(r);assert g.property('Value')==2.5
    assert r.binder.property_type(g.control,'Value').kind=='Number'
    change(r,g,4.5)
    assert r.fx.evaluate('LeftRating.Current=4.5 && RightRating.Current=2.5')
    assert r.fx.evaluate('CountRows(LeftRating.History)=1 && CountRows(RightRating.History)=0')
    assert r.collections['events']==[{'Panel':'LeftRating','Value':4.5}]
    change(r,g,4.5);assert len(r.collections['events'])==1

def test_component_reset_is_isolated_and_does_not_call_change(r):
    change(r,score(r),4.5);change(r,score(r,'RightRating'),3.5)
    r.event('RatingLab/ResetLeftRating','OnSelect');r.state()
    assert r.fx.evaluate('LeftRating.Current=2.5 && CountRows(LeftRating.History)=0')
    assert r.fx.evaluate('RightRating.Current=3.5 && CountRows(RightRating.History)=1')
    assert len(r.collections['events'])==2

def test_reactive_defaults_and_stale_reset_events(r):
    g=score(r);change(r,g,4.5);old=r.scalar_token(g)
    r.event('RatingLab/ChangeDefaults','OnSelect');r.state()
    assert g.property('Value')==1 and not g.state.get('dirty')
    change(r,g,5,old);assert g.property('Value')==1
    old=r.scalar_token(g);r.reset_ref(g);change(r,g,5,old)
    assert g.property('Value')==1 and len(r.collections['events'])==1

@pytest.mark.parametrize('raw',[True,'3',None,float('nan'),float('inf'),-.5,5.5,2.25])
def test_invalid_values_never_commit_or_callback(r,raw):
    with pytest.raises((ValueError,FxError)):change(r,score(r),raw)
    assert score(r).property('Value')==2.5 and not r.collections['events']

def test_full_steps_keyboard_boundary_values_and_changed_contract_token(r):
    g=score(r);authored(r,g,Step='=RatingStep.Full');old=r.scalar_token(g)
    with pytest.raises(ValueError,match='Step'):change(r,g,2.5)
    change(r,g,0);assert g.property('Value')==0
    change(r,g,5);assert g.property('Value')==5
    authored(r,g,Max='=7');change(r,g,3,old)
    assert g.property('Value')==5
    change(r,g,7);assert g.property('Value')==7

@pytest.mark.parametrize('property,raw',[('Max','=1'),('Max','=2.5'),('Max','="five"'),('Default','="bad"'),('Step','=0.5'),('Icon','="MissingFictionalGlyph"')])
def test_invalid_properties_report_errors_and_preserve_peer(r,property,raw):
    g=score(r);authored(r,g,**{property:raw});r.state()
    assert r.diagnostics and score(r,'RightRating').property('Value')==2.5

def test_authored_outputs_unknown_versions_and_events_remain_visible(r):
    g=score(r);authored(r,g,Value='=4')
    with pytest.raises(FxError,match='output'):g.property('Value')
    r.state();assert any('output' in d['message'] for d in r.diagnostics)
    with pytest.raises(ValueError):r.event(g.path,'OnSelect')
    authored(r,g,Value='=4',OnInput='=Set(invented,true)')
    assert 'OnInput' in __import__('powerapps_sim.controls',fromlist=['contract_errors']).contract_errors(g.control)
    r.project.controls['Score'][0].kind='ModernRating@9.0.0';r.analyze();assert any('version' in d['message'].lower() for d in r.diagnostics)

@pytest.mark.parametrize('mode',['View','Disabled'])
def test_modes_and_hidden_ancestors_block_input(r,mode):
    g=score(r);authored(r,g,DisplayMode='=DisplayMode.'+mode);change(r,g,5)
    assert not r.collections['events'] and g.property('Value')==2.5
    authored(r,g,DisplayMode='=DisplayMode.Edit');authored(r,g.parent,Visible='=false');change(r,g,5)
    assert not r.collections['events']

def test_gallery_alias_and_patch_refresh_only_affected_row(r):
    row=r.fx.evaluate('Index(FeedbackRows.AllItems,2).RowScore');other=r.fx.evaluate('First(FeedbackRows.AllItems).RowScore')
    change(r,row,4)
    assert r.store.rows('Feedback')[1]['Score']==4 and other.property('Value')==1
    assert r.collections['events']==[{'Panel':'Row','Value':4}]
    assert not r.diagnostics

def test_form_dirty_failed_save_retry_and_persistence(r):
    ref=r.refs['RatingLab/FeedbackForm/ScoreCard/FormScore'];form=r.refs['RatingLab/FeedbackForm']
    change(r,ref,4.5);assert form.property('Unsaved') and form.property('Updates')['Score']==4.5
    r.store.failures['Feedback']='write';r.event('RatingLab/SaveScore','OnSelect');r.state()
    assert form.property('Unsaved') and ref.property('Value')==4.5 and r.store.rows('Feedback')[0]['Score']==1
    r.store.failures.clear();r.event('RatingLab/SaveScore','OnSelect');r.state()
    assert not form.property('Unsaved') and form.property('LastSubmit')['Score']==4.5
    r.restart();r.state();assert ref.property('Value')==4.5

@pytest.mark.parametrize('number_mode,enum_mode',[('float','legacy'),('decimal','legacy'),('float','strong'),('decimal','strong')])
def test_numeric_profiles_and_symbolic_enum_identity(tmp_path,number_mode,enum_mode):
    p=rating_project(tmp_path/'ratings');p.config['environment'].update(number_mode=number_mode,enum_mode=enum_mode);p.save_config()
    r=Runtime(p)
    try:
        r.restart();r.state();change(r,score(r),3.5)
        assert r.fx.evaluate('LeftRating.Current=3.5 && RatingStep.Full<>RatingStep.Half')
        assert not r.diagnostics
        if enum_mode=='strong':
            with pytest.raises(FxError):r.fx.evaluate('Value(RatingStep.Full)')
    finally:r.close()

def test_default_blank_range_and_fraction_policies(r):
    g=score(r)
    for raw,expected in [('=Blank()',0),('=-1',0),('=8',5),('=2.25',2.25)]:
        authored(r,g,Default=raw);assert g.property('Value')==expected

@pytest.mark.parametrize('language,number',[('en-US','float'),('en-US','decimal'),('fr-CA','float'),('fr-CA','decimal')])
def test_workflow_owner_source_data_runtime_preserved(tmp_path,language,number):
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision,data_revision
    p=rating_project(tmp_path/'ratings');w=Workspace(tmp_path/'workspace',p.root)
    try:
        source=revision(p.root);data=data_revision(w.runtime.store);before=deepcopy(w.ai.read_runtime())
        scenario=w.workflows.catalog()['scenarios'][0]['scenario']
        result=w.workflows.run({**scenario,'environment':{'language':language,'number_mode':number}},expected_revision=source)
        assert result['status']=='passed',result['steps']
        assert len(result['steps'])==22 and not result['diagnostics']
        assert revision(p.root)==source and data_revision(w.runtime.store)==data and before==w.ai.read_runtime()
    finally:w.runtime.close()

def test_unsupported_reset_property_does_not_reset_state(r):
    g=score(r);change(r,g,4.5);authored(r,g,Reset='=true');r.state()
    assert g.property('Value')==4.5 and len(r.collections['events'])==1

def test_callback_error_isolated_after_committed_value(r):
    g=score(r);authored(r,g,OnChange='=Error({Kind:ErrorKind.Validation,Message:"Fictional callback failure"})');change(r,g,4.5)
    assert g.property('Value')==4.5 and score(r,'RightRating').property('Value')==2.5
    assert any('Fictional callback failure' in d['message'] for d in r.diagnostics)

def test_source_round_trip_preserves_unknown_properties_and_exports(tmp_path):
    from powerapps_sim.source import dump_yaml,load_yaml
    import zipfile,io
    p=rating_project(tmp_path/'ratings');name=next(iter(p.documents));raw=p.documents[name]
    p.update_source(name,raw.replace('Step: =RatingStep.Half','Step: =RatingStep.Half\n            FutureProperty: ="untouched"',1))
    normalized=dump_yaml(load_yaml(p.documents[name]));assert 'FutureProperty' in normalized and 'ModernRating@1.0.0' in normalized
    export=p.export()
    with zipfile.ZipFile(io.BytesIO(export)) as z:
        assert not any('simulator' in n or 'sqlite' in n for n in z.namelist())
        assert any(b'FutureProperty' in z.read(n) for n in z.namelist() if n.endswith('.yaml'))

def test_queued_keyboard_steps_accumulate_without_client_refresh(r):
    g=score(r);token=r.scalar_token(g)
    for _ in range(3):r.event(g.path,'OnChange',{'key':'ArrowRight','reset_token':token})
    assert g.property('Value')==4 and len(r.collections['events'])==3
    r.event(g.path,'OnChange',{'key':'End','reset_token':token});assert g.property('Value')==5
    r.event(g.path,'OnChange',{'key':'ArrowRight','reset_token':token});assert len(r.collections['events'])==4
    r.event(g.path,'OnChange',{'key':'Home','reset_token':token});assert g.property('Value')==0
    r.reset_ref(g);r.event(g.path,'OnChange',{'key':'End','reset_token':token});assert g.property('Value')==2.5

def test_keyboard_rounds_fractional_defaults_towards_next_allowed_step(r):
    g=score(r);authored(r,g,Default='=2.25',Step='=RatingStep.Full');r.state()
    r.event(g.path,'OnChange',{'key':'ArrowRight','reset_token':r.scalar_token(g)})
    assert g.property('Value')==3
    r.reset_ref(g);r.event(g.path,'OnChange',{'key':'ArrowLeft','reset_token':r.scalar_token(g)})
    assert g.property('Value')==2
    with pytest.raises(ValueError):r.event(g.path,'OnChange',{'key':True,'reset_token':r.scalar_token(g)})
