from copy import deepcopy
from decimal import Decimal
import pytest

from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision, data_revision
from powerapps_sim.canvas_scalars import catalog, token, enums
from powerapps_sim.fixtures import canvas_scalars_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.source import Project, dump_yaml
from powerapps_sim.syntax import FxError
from powerapps_sim.fx import Context

VERSIONS = [(f,v) for f,versions in catalog().items() for v in versions]


def make(tmp_path, family='Slider', version='1.0.29', properties=None):
    p=Project(tmp_path/'scalar')
    props={'OnChange':'=Collect(events,{Value:Self.Value})'} if family=='Slider' else {'OnCheck':'=Collect(events,{Event:"check",Value:Self.Checked})','OnUncheck':'=Collect(events,{Event:"uncheck",Value:Self.Checked})','OnSelect':'=Collect(events,{Event:"select",Value:Self.Checked})'}
    props.update(properties or {})
    p.update_source('Src/scalar.pa.yaml',dump_yaml({'App':{'Properties':{'OnStart':'=Clear(events)'}},'Screens':{'Home':{'Children':[
        {'Input':{'Control':family+'@'+version,'Properties':props}},
        {'Peer':{'Control':family+'@'+version}}]}}}))
    r=Runtime(p);r.restart();r.state();return r


def send(r, ref, raw, event=None, stale=None):
    r.event(ref.path,event or ('OnChange' if ref.family=='Slider' else 'OnSelect'),{('value' if ref.family=='Slider' else 'checked'):raw,'reset_token':stale or token(ref)})
    r.state()


@pytest.mark.parametrize('family,version',VERSIONS)
@pytest.mark.parametrize('numbers',['float','decimal'])
@pytest.mark.parametrize('enum_mode',['legacy','strong'])
def test_archived_defaults_bound_properties_and_reset(tmp_path,family,version,numbers,enum_mode):
    r=make(tmp_path,family,version)
    try:
        r.environment.update(number_mode=numbers,enum_mode=enum_mode);r.analyze();r.invalidate();r.state()
        g=r.refs['Home/Input'];peer=r.refs['Home/Peer'];prop=r.input_property(g);default=50 if family=='Slider' else False
        assert g.property(prop)==default
        for name in catalog()[family][version]['types']:g.property(name)
        assert r.binder.property_type(g.control,prop).kind==('Number' if family=='Slider' else 'Boolean')
        assert not r.diagnostics,r.diagnostics
        assert token(g)!=token(peer)
        send(r,g,75 if family=='Slider' else True)
        assert len(r.collections['events'])==(1 if family=='Slider' else 2) and g.state['dirty']
        if family=='Slider' and numbers=='decimal':assert isinstance(g.state[prop],Decimal)
        assert peer.property(prop)==default
        stale=token(g);r.fx.evaluate('Reset(Input)',Context(r,behavior=True));r.state()
        assert token(g)!=stale and g.property(prop)==default and not g.state.get('dirty')
        send(r,g,75 if family=='Slider' else True,stale=stale)
        assert g.property(prop)==default
    finally:r.close()


@pytest.mark.parametrize('family,prop',[(f,p) for f,ps in {'Slider':['Default','Step','LayoutDirection','OnInput','OnSelect','ReadOnly','Reset','PCFTeamsTheme','FontSize'], 'Toggle':['Default','Value','OnChange','Reset','PCFTeamsTheme','AcceptsFocus']}.items() for p in ps])
def test_invalid_authored_aliases_preserved_with_healthy_peer(tmp_path,family,prop):
    r=make(tmp_path,family,'1.0.31' if family=='Slider' else '1.1.5',{prop:'=Blank()'})
    try:
        assert prop in r.refs['Home/Input'].control.properties
        assert any(d['kind']=='Unsupported' and d.get('source')=='Src/scalar.pa.yaml' for d in r.diagnostics)
        with pytest.raises(FxError):r.refs['Home/Input'].property(prop)
        assert r.refs['Home/Peer'].property('Value' if family=='Slider' else 'Checked')==(50 if family=='Slider' else False)
    finally:r.close()


@pytest.mark.parametrize('family,prop,raw',[
    ('Slider','Value','="50"'),('Slider','Min','=false'),('Slider','Max','=-1'),('Slider','Min','=Blank()'),('Slider','Size','="Large"'),('Slider','Layout','="Diagonal"'),('Slider','TabIndex','=0.5'),('Slider','Width','=-1'),
    ('Toggle','Checked','="yes"'),('Toggle','ToggleSize','=-1'),('Toggle','LabelPosition','="Left"'),('Toggle','FontSize','=-1'),('Toggle','FontColor','=42'),('Toggle','Label','=123')])
def test_bad_types_ranges_and_enums_are_source_located(tmp_path,family,prop,raw):
    r=make(tmp_path,family,'1.0.29' if family=='Slider' else '1.1.4',{prop:raw})
    try:
        assert r.diagnostics and any(d.get('source')=='Src/scalar.pa.yaml' for d in r.diagnostics)
        assert not r.render(r.refs['Home/Peer'])['errors']
    finally:r.close()


def test_drag_preview_release_deduplication_and_stale_bounds(tmp_path):
    r=make(tmp_path,properties={'Value':'=-25.5','Min':'=-100','Max':'=100','Layout':'=Slider.Layout.Vertical','Size':'=Slider.Size.Small'})
    try:
        g=r.refs['Home/Input'];send(r,g,-50.25,'OnInput')
        assert g.property('Value')==-50.25 and not r.collections['events']
        send(r,g,-50.25);send(r,g,-50.25)
        assert len(r.collections['events'])==1
        stale=token(g);g.control=deepcopy(g.control);g.control.properties['Max']='=-40';r.invalidate();r.state()
        send(r,g,0,stale=stale);assert g.property('Value')==-50.25
        send(r,g,0);assert g.property('Value')==-40
        assert enums('Slider')=={'Size':{'Small':'Small','Medium':'Medium'},'Layout':{'Vertical':'Vertical','Horizontal':'Horizontal'}}
        assert not r.diagnostics,r.diagnostics
    finally:r.close()


def test_toggle_callback_order_programmatic_select_and_dirty_return(tmp_path):
    r=make(tmp_path,'Toggle','1.1.5')
    try:
        g=r.refs['Home/Input'];send(r,g,True);send(r,g,True);send(r,g,False)
        assert [e['Event'] for e in r.collections['events']]==['check','select','select','uncheck','select']
        assert [e['Value'] for e in r.collections['events']]==[True,True,True,False,False]
        assert not g.state['dirty']
        r.fx.evaluate('Select(Input)',Context(r,behavior=True));r.drain_events()
        assert r.collections['events'][-1]=={'Event':'select','Value':False}
        assert not r.diagnostics
    finally:r.close()


@pytest.mark.parametrize('family,version',VERSIONS)
def test_event_contracts_bad_payloads_and_other_instance_token(tmp_path,family,version):
    r=make(tmp_path,family,version)
    try:
        g=r.refs['Home/Input'];peer=r.refs['Home/Peer'];raw=75 if family=='Slider' else True
        send(r,peer,raw,stale=token(g));assert peer.property(r.input_property(peer))==(50 if family=='Slider' else False)
        event='OnChange' if family=='Slider' else 'OnSelect'
        for payload in (raw,{'value':raw},{'checked':raw,'reset_token':token(g),'extra':1}):
            with pytest.raises(ValueError):r.event(g.path,event,payload)
        for payload in (None,'yes',float('nan'),True if family=='Slider' else 1):
            with pytest.raises((ValueError,FxError)):send(r,g,payload)
        assert not g.state and not r.collections['events']
    finally:r.close()


@pytest.mark.parametrize('family,version',VERSIONS)
def test_display_mode_is_enforced_and_unsupported_versions_visible(tmp_path,family,version):
    r=make(tmp_path,family,version,{'DisplayMode':'=DisplayMode.View'})
    try:
        g=r.refs['Home/Input'];send(r,g,75 if family=='Slider' else True)
        assert not g.state and not r.collections['events']
        g.control=deepcopy(g.control);g.control.kind=family+'@9.9.9';r.analyze();r.invalidate();r.state()
        assert any(d['kind']=='Unsupported' for d in r.diagnostics)
        assert not r.render(r.refs['Home/Peer'])['errors']
    finally:r.close()


@pytest.mark.parametrize('version',['1.1.2','1.1.4','1.1.5'])
def test_gallery_toggle_explicit_reset_respects_row_boundary(tmp_path,version):
    p=Project(tmp_path/'gallery')
    p.update_source('Src/gallery.pa.yaml',dump_yaml({'Screens':{'Home':{'Children':[
        {'Rows':{'Control':'Gallery@2.15.0','Properties':{'Items':'=Table({ID:1,Enabled:false},{ID:2,Enabled:true})'},'Children':[
            {'Input':{'Control':'Toggle@'+version,'Properties':{'Checked':'=ThisItem.Enabled'}}},
            {'RowReset':{'Control':'ModernButton@1.0.0','Properties':{'OnSelect':'=Reset(Input)'}}}]}},
        {'ResetSelected':{'Control':'ModernButton@1.0.0','Properties':{'OnSelect':'=ForAll(Filter(Rows.AllItems,ID=Rows.Selected.ID) As row,Select(row.RowReset))'}}}
    ]}}}))
    r=Runtime(p);r.restart();r.state()
    try:
        rows=r.fx.evaluate('Rows.AllItems');send(r,rows[0]['Input'],True);send(r,rows[1]['Input'],False)
        r.event('Home/Rows','OnSelect',selection=[0]);r.event('Home/ResetSelected','OnSelect');r.state()
        assert not rows[0]['Input'].property('Checked') and not rows[1]['Input'].property('Checked')
        assert not r.diagnostics
    finally:r.close()


@pytest.mark.parametrize('language',['en-US','fr-CA'])
@pytest.mark.parametrize('numbers',['float','decimal'])
@pytest.mark.parametrize('enum_mode',['legacy','strong'])
def test_component_form_workflow_and_owner_preservation(tmp_path,language,numbers,enum_mode):
    p=canvas_scalars_project(tmp_path/'owner');w=Workspace(tmp_path,p.root,start=False)
    try:
        before=revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime(),w.ai.export_source()
        s=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario']);s['environment']={'language':language,'number_mode':numbers,'enum_mode':enum_mode}
        result=w.workflows.run(s,expected_revision=before[0]);assert result['status']=='passed' and len(result['steps'])==29 and not result['diagnostics'],result
        assert before==(revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime(),w.ai.export_source())
    finally:w.runtime.close()
