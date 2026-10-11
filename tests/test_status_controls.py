"""Independent expectations from current Microsoft control documentation."""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile
from decimal import Decimal
import pytest
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision, data_revision
from powerapps_sim.fixtures import status_project
from powerapps_sim.runtime import Runtime,serial
from powerapps_sim.source import Control
from powerapps_sim.syntax import FxError
from powerapps_sim.enum_fx import EnumValue

@pytest.fixture
def r(tmp_path):
    runtime=Runtime(status_project(tmp_path/'p'));runtime.restart();runtime.state()
    assert not runtime.diagnostics
    yield runtime
    runtime.close()

def control(r,family='ModernBadge',props=None,name='Probe',version='1.0.0'):
    return r.build(Control(name,family+'@'+version,{'Properties':props or {}},'Src/status.pa.yaml'),'StatusLab/'+name)

def test_documented_defaults_and_explicit_phone_layout(r):
    badge=control(r);info=control(r,'ModernInformationButton',name='InfoProbe')
    assert [badge.property(p) for p in ('Content','Width','Height','Size','Fill','Color','Icon')]==['AB',64,32,None,None,None,None]
    assert [badge.property(p) for p in ('Intent','Appearance','Shape','IconPosition','Align','VerticalAlign')]==['Positive','Tint','Circular','Before','Center','Middle']
    assert [info.property(p) for p in ('Content','Width','Height','Size','FontWeight')]==['',32,32,15,'Normal']
    r.project.config['form_factor']='phone';r.invalidate()
    assert badge.property('Width')==88 and badge.property('Height')==44
    badge.control.properties['Width']='=120';r.invalidate();assert badge.property('Width')==120
    assert info.property('Width')==32

@pytest.mark.parametrize('mode',['float','decimal'])
@pytest.mark.parametrize('enum_mode',['legacy','strong'])
def test_enum_identity_binding_and_reactive_component_isolation(r,mode,enum_mode):
    from powerapps_sim.binding import Binder
    r.environment.update(number_mode=mode,enum_mode=enum_mode);r.binder=Binder(r);r.restart();r.state()
    left=r.refs['StatusLab/LeftPanel/Counter'];right=r.refs['StatusLab/RightPanel/Counter']
    assert r.render(left)['props']['Intent']=='Positive'
    r.event(left.path,'OnSelect');node=r.render(left)
    assert node['props']['Intent']=='Critical' and node['props']['IconPosition']=='After'
    assert node['props']['Content']==1 and right.property('Content')==0
    assert r.fx.evaluate('First(trace).Count')==1
    assert r.binder.property_type(left.control,'Intent').kind==('Enum' if enum_mode=='strong' else 'Text')
    if enum_mode=='strong':
        assert isinstance(left.property('Intent'),EnumValue)
        bad=control(r,props={'Intent':'=BadgeShape.Circular'});r.invalidate()
        with pytest.raises(FxError,match='BadgeIntent'):bad.property('Intent')
        assert r.render(right)['props']['Intent']=='Positive'

@pytest.mark.parametrize('property,formula',[('Content','=true'),('Content','=Table({Value:1})'),('Size','=-1'),('PaddingLeft','="1"'),('Icon','="NoSuchFluentGlyph"'),('Color','="red"'),('Intent','="Success"'),('Appearance','="Primary"'),('Shape','="Pill"'),('IconPosition','="Left"'),('Italic','=1'),('FontWeight','="Medium"')])
def test_invalid_properties_remain_errors_without_affecting_peers(r,property,formula):
    ref=control(r,props={property:formula})
    with pytest.raises(FxError):ref.property(property)
    node=r.render(ref);assert node['errors']
    assert not r.render(r.refs['StatusLab/RightPanel/Counter'])['errors']
    assert ref.control.properties[property]==formula

@pytest.mark.parametrize('formula',['=42','=Blank()','=0.5'])
def test_information_content_requires_text(r,formula):
    info=control(r,'ModernInformationButton',{'Content':formula})
    if formula=='=Blank()':assert info.property('Content') is None
    else:
        with pytest.raises(FxError,match='Text'):info.property('Content')

def test_formatted_information_is_sanitized_and_unsupported_features_visible(r):
    info=control(r,'ModernInformationButton',{'Content':'="<b>Help</b><script>bad()</script><img src=\"\"https://example.test/x\"\">"'})
    node=r.render(info)
    assert '<b>Help</b>' in node['info_html'] and 'bad()' not in node['info_html'] and 'https://example.test/x' not in node['info_html']
    assert node['errors'] and any(d['member']=='Probe.Content' for d in r.diagnostics)
    assert not r.render(r.refs['StatusLab/Info'])['errors']

@pytest.mark.parametrize('raw',[None,'=Blank()','=', '=0'])
def test_decorative_badge_is_not_focusable_or_event_target(r,raw):
    props={} if raw is None else {'OnSelect':raw}
    badge=control(r,props=props)
    if raw=='=': # malformed behavior is retained as an active rule for inspection
        assert r.render(badge)['selectable'];return
    assert not r.render(badge)['selectable'] and not r.render(badge)['tab_stop']
    with pytest.raises(ValueError):r.event(badge.path,'OnSelect')

def test_information_clicks_are_authoritative_and_view_hidden_gates_apply(r):
    info=r.refs['StatusLab/Info']
    r.event(info.path,'OnSelect');assert r.fx.evaluate('helpClicks')==1
    for prop,formula in [('DisplayMode','=DisplayMode.View'),('DisplayMode','=DisplayMode.Disabled'),('Visible','=false')]:
        info.control.properties[prop]=formula;r.invalidate();r.event(info.path,'OnSelect');assert r.fx.evaluate('helpClicks')==1
        info.control.properties.pop(prop);r.invalidate()
    with pytest.raises(ValueError):r.event(info.path,'OnChange')
    r.event('StatusLab/DisableLeft','OnSelect');r.event('StatusLab/LeftPanel/Counter','OnSelect');assert r.global_refs['LeftPanel'].property('Count')==0
    r.event('StatusLab/RightPanel/Counter','OnSelect');assert r.global_refs['RightPanel'].property('Count')==1

@pytest.mark.parametrize('family',['ModernBadge','ModernInformationButton'])
def test_removed_properties_version_and_source_preservation(r,family):
    ref=control(r,family,{'AcceptsFocus':'=false','FontColor':'=Color.Red','Visible':'=false'})
    node=r.render(ref)
    assert any('AcceptsFocus' in e for e in node['errors']) and any('FontColor' in e for e in node['errors'])
    assert ref.control.properties['FontColor']=='=Color.Red'
    unknown=control(r,family,version='9.9.9',name='Future')
    r.project.controls.setdefault('Future',[]).append(unknown.control);r.analyze()
    assert any('version' in d['message'].lower() for d in r.diagnostics if d.get('member','').startswith('Future'))

@pytest.mark.parametrize('mode',['float','decimal'])
@pytest.mark.parametrize('language',['en-CA','fr-CA'])
def test_isolated_workflow_and_clean_exports(tmp_path,mode,language):
    p=status_project(tmp_path/'p');w=Workspace(tmp_path/'work',p.root)
    try:
        before=(deepcopy(serial(w.ai.read_runtime())),revision(p.root),data_revision(w.runtime.store))
        scenario=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario']);scenario['environment']={'language':language,'number_mode':mode,'enum_mode':'strong'}
        result=w.workflows.run(scenario,expected_revision=revision(p.root))
        assert result['status']=='passed' and len(result['steps'])==23,result
        assert not result['diagnostics']
        assert before==(serial(w.ai.read_runtime()),revision(p.root),data_revision(w.runtime.store))
        with ZipFile(BytesIO(p.export())) as archive:
            assert archive.namelist()==['Src/status.pa.yaml']
            source=archive.read(archive.namelist()[0]).decode()
            assert 'ModernBadge@1.0.0' in source and 'ModernInformationButton@1.0.0' in source
            assert 'status_authored' not in source and 'info_html' not in source and 'form_factor' not in source
    finally:w.runtime.close()


def test_strong_badge_enums_reject_untyped_strings_and_cross_namespace_comparison(tmp_path):
    p=status_project(tmp_path/'typed');p.config['environment']['enum_mode']='strong';p.save_config()
    r=Runtime(p)
    try:
        r.restart();r.state();assert not r.diagnostics
        for prop,formula in [('Intent','="Positive"'),('Shape','="Circular"'),('Appearance','="Tint"'),('IconPosition','="Before"')]:
            bad=control(r,props={prop:formula},name=prop+'Probe')
            with pytest.raises(FxError,match='requires Badge'):bad.property(prop)
        assert r.fx.evaluate('BadgeIntent.Positive=BadgeIntent.Positive') is True
        with pytest.raises(FxError,match='different enum'):r.fx.evaluate('BadgeIntent.Positive=BadgeShape.Circular')
        with pytest.raises(FxError):r.fx.evaluate('Value(BadgeIntent.Positive)')
        assert r.render(r.refs['StatusLab/RightPanel/Counter'])['props']['Intent']=='Positive'
    finally:r.close()


@pytest.mark.parametrize('family,prop,formula',[('ModernBadge','IconStyle','=IconStyle.Filled'),('ModernInformationButton','Icon','="Alert"')])
def test_unimplemented_style_contracts_cannot_silently_change_properties(r,family,prop,formula):
    ref=control(r,family,{prop:formula})
    with pytest.raises(FxError,match='does not support'):ref.property(prop)
    node=r.render(ref);assert any(prop in error for error in node['errors'])
    assert ref.control.properties[prop]==formula
    assert not r.render(r.refs['StatusLab/RightPanel/Counter'])['errors']


@pytest.mark.parametrize('language,expected',[('en-CA','9007199254740993.123456789'),('fr-CA','9007199254740993,123456789')])
def test_numeric_badge_display_preserves_decimal_precision_and_language(r,language,expected):
    from powerapps_sim.binding import Binder
    r.environment.update(language=language,number_mode='decimal');r.binder=Binder(r)
    badge=control(r,props={'Content':'=Decimal("9007199254740993.123456789","en-CA")'})
    assert badge.property('Content')==Decimal('9007199254740993.123456789')
    assert r.render(badge)['badge_text']==expected
