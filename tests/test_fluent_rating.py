"""Recovered bound Value contracts and independent Fluent v8 keyboard cases."""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile
import pytest
from powerapps_sim.fixtures import fluent_rating_project
from powerapps_sim.web import Workspace
from powerapps_sim.runtime import Runtime
from powerapps_sim.source import Project
from powerapps_sim.syntax import FxError
from powerapps_sim.authoring import revision,data_revision
from powerapps_sim.fluent_rating import DEFAULTS,TYPES,catalog

@pytest.fixture
def r(tmp_path):
    r=Runtime(fluent_rating_project(tmp_path/'ratings'));r.restart();r.state()
    assert not r.diagnostics
    yield r;r.close()

def score(r,panel='LeftRating'):return r.refs['RatingLab/'+panel+'/Score']
def event(r,ref,value,name='OnChange',token=None):
    r.event(ref.path,name,{'value':value,'reset_token':token or r.scalar_token(ref)});r.state()
def authored(r,ref,**props):
    ref.control=deepcopy(ref.control);ref.control.properties.update(props);r.invalidate()

@pytest.mark.parametrize('name,expected',[('Max',5),('AcceptsFocus',True),('TabIndex',0),('Size',20),('Width',320),('Height',36),('PaddingStart',0),('PaddingEnd',0),('PaddingTop',0),('PaddingBottom',0),('CheckedFill',''),('UncheckedFill',''),('HoverFill',''),('DisabledFill','')])
def test_defaults_are_literal_first_party_metadata(r,name,expected):
    from powerapps_sim.fluent_rating import validate
    raw=r.fx.evaluate(DEFAULTS[name]);assert raw==expected
    validate(name,raw)
    native=next(p for p in catalog()['native_properties'] if p['Name']==name)
    assert DEFAULTS[name].removeprefix('=')==('""' if native['DefaultValue']=='' else native['DefaultValue'])

@pytest.mark.parametrize('mode',['float','decimal'])
@pytest.mark.parametrize('enums',['legacy','strong'])
def test_bound_value_contract_and_independent_component_callbacks(r,mode,enums):
    r.environment.update(number_mode=mode,enum_mode=enums);r.analyze();r.state()
    assert score(r).property('Value')==2.5
    assert r.binder.property_type(score(r).control,'Value').kind=='Number'
    event(r,score(r),4,'OnSelect')
    assert r.fx.evaluate('LeftRating.Current=4 && RightRating.Current=2.5 && CountRows(events)=1 && CountRows(taps)=1')
    event(r,score(r),4,'OnSelect')
    assert len(r.collections['events'])==1 and len(r.collections['taps'])==2
    event(r,score(r),3,'OnChange')
    assert len(r.collections['events'])==2 and len(r.collections['taps'])==2
    assert not r.diagnostics

@pytest.mark.parametrize('key,expected',[('ArrowRight',4),('ArrowDown',4),('ArrowLeft',2),('ArrowUp',2),('Home',1),('PageUp',1),('End',5),('PageDown',5)])
def test_pinned_react_radio_keyboard_conventions(r,key,expected):
    g=score(r);r.event(g.path,'OnChange',{'key':key,'reset_token':r.scalar_token(g)});r.state()
    assert g.property('Value')==expected
    assert not r.collections['taps']


def test_current_fractional_star_selection_does_not_change_bound_value(r):
    event(r,score(r),3,'OnSelect')
    assert score(r).property('Value')==2.5 and not r.collections['events']
    assert len(r.collections['taps'])==1

@pytest.mark.parametrize('raw',[True,'3',None,float('nan'),float('inf'),0,-1,5.5,2.5,6])
def test_bad_events_do_not_commit(r,raw):
    with pytest.raises((ValueError,FxError)):event(r,score(r),raw)
    assert score(r).property('Value')==2.5 and not r.collections['events'] and not r.collections['taps']


def test_reactive_bound_formula_and_reset_discard_stale_events(r):
    g=score(r);event(r,g,4);old=r.scalar_token(g)
    r.event('RatingLab/ChangeDefaults','OnSelect');r.state()
    assert g.property('Value')==1 and not g.state.get('dirty')
    event(r,g,5,token=old);assert g.property('Value')==1
    old=r.scalar_token(g);r.reset_ref(g);event(r,g,5,token=old)
    assert g.property('Value')==1 and len(r.collections['events'])==1

@pytest.mark.parametrize('prop,raw',[('Default','=3'),('Step','=RatingStep.Half'),('Icon','="Heart"'),('Reset','=true'),('ReadOnly','=true'),('PCFTeamsTheme','="custom"')])
def test_other_rating_contracts_and_theme_are_not_silently_accepted(r,prop,raw):
    g=score(r);authored(r,g,**{prop:raw});r.state()
    assert any('Unsupported'==d['kind'] for d in r.diagnostics)
    assert score(r,'RightRating').property('Value')==2.5

@pytest.mark.parametrize('prop,raw',[('Max','=0'),('Max','=2.5'),('Size','=-1'),('AcceptsFocus','="true"'),('Value','="bad"'),('PaddingStart','=-1')])
def test_bad_properties_isolate_the_instance(r,prop,raw):
    g=score(r);authored(r,g,**{prop:raw});r.state()
    assert r.diagnostics and score(r,'RightRating').property('Value')==2.5

@pytest.mark.parametrize('mode',['View','Disabled'])
def test_display_modes_and_hidden_ancestors_block_callbacks(r,mode):
    g=score(r);authored(r,g,DisplayMode='=DisplayMode.'+mode);event(r,g,4,'OnSelect')
    assert g.property('Value')==2.5 and not r.collections['events'] and not r.collections['taps']
    authored(r,g,DisplayMode='=DisplayMode.Edit');authored(r,g.parent,Visible='=false');event(r,g,4)
    assert g.property('Value')==2.5 and not r.collections['events']


def test_tab_stop_changes_and_stale_tokens_do_not_disable_mouse_input(r):
    from powerapps_sim.focus import tab_stop
    g=score(r);authored(r,g,TabIndex='=-1');assert not tab_stop(g)
    event(r,g,4,'OnSelect');assert g.property('Value')==4
    old=r.scalar_token(g);authored(r,g,AcceptsFocus='=false')
    r.event(g.path,'OnChange',{'key':'End','reset_token':r.scalar_token(g)})
    assert g.property('Value')==4
    event(r,g,5,token=old);assert g.property('Value')==4
    event(r,g,5,'OnSelect');assert g.property('Value')==5


def test_gallery_alias_updates_one_row_and_bound_form_tracks_failed_save(r):
    row=r.fx.evaluate('Index(FeedbackRows.AllItems,2).RowScore');peer=r.fx.evaluate('First(FeedbackRows.AllItems).RowScore')
    event(r,row,4);assert r.store.rows('Feedback')[1]['Feedback score']==4 and peer.property('Value')==1
    form=r.refs['RatingLab/FeedbackForm'];g=r.refs['RatingLab/FeedbackForm/ScoreCard/FormScore']
    event(r,g,5);assert form.property('Unsaved') and form.property('Updates')['Score']==5
    r.store.failures['Feedback']='write';r.event('RatingLab/SaveScore','OnSelect');r.state()
    assert form.property('Unsaved') and g.property('Value')==5 and r.store.rows('Feedback')[0]['Feedback score']==1
    r.store.failures.clear();r.event('RatingLab/SaveScore','OnSelect');r.state()
    assert not form.property('Unsaved') and r.fx.evaluate('FeedbackForm.LastSubmit.Score')==5
    other=Runtime(Project(r.project.root))
    try:assert other.fx.evaluate('First(Feedback).Score')==5
    finally:other.close()

@pytest.mark.parametrize('language',['en-US','fr-CA'])
@pytest.mark.parametrize('mode',['float','decimal'])
@pytest.mark.parametrize('enum_mode',['legacy','strong'])
def test_workflow_and_source_export_preserve_owner(tmp_path,language,mode,enum_mode):
    p=fluent_rating_project(tmp_path/'owner');w=Workspace(tmp_path,p.root,start=False)
    try:
        before=revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime(),w.ai.export_source()
        s=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario']);s['environment']={'language':language,'number_mode':mode,'enum_mode':enum_mode}
        result=w.workflows.run(s,expected_revision=before[0])
        assert result['status']=='passed' and len(result['steps'])==19 and not result['diagnostics'],result
        assert before==(revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime(),w.ai.export_source())
        with ZipFile(BytesIO(p.export())) as z:
            assert set(z.namelist())=={'Src/fluent-rating.pa.yaml','Src/Components/RatingPanel.pa.yaml'}
            assert 'FluentV8/Rating@1.5.1' in z.read('Src/Components/RatingPanel.pa.yaml').decode()
    finally:w.runtime.close()
