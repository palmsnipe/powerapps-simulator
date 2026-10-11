import json
import pytest
from powerapps_sim.source import Project,Control,dump_yaml
from powerapps_sim.runtime import Runtime,serial
from powerapps_sim.syntax import FxError
from powerapps_sim.enum_fx import EnumValue
from powerapps_sim.authoring import revision,data_revision


@pytest.fixture
def r(tmp_path):
    p=Project(tmp_path/'p')
    p.update_source('Src/links.pa.yaml',dump_yaml({'Screens':{'Home':{}}}))
    r=Runtime(p);r.restart()
    yield r
    r.close()


def control(r,props=None,version='1.0.0'):
    ref=r.build(Control('Link','ModernLink@'+version,{'Properties':props or {}},'Src/links.pa.yaml'),'Home/Link',r.refs['Home'])
    r.invalidate()
    return ref


def test_documented_defaults(r):
    ref=control(r)
    assert [ref.property(p) for p in ('Width','Height','Size','PaddingTop','PaddingBottom','PaddingLeft','PaddingRight')]==[150,32,15,5,5,5,5]
    assert [ref.property(p) for p in ('Align','VerticalAlign','Wrap','Type')]==['Left','Middle',True,'Default']
    assert not r.render(ref)['link_url'] and not r.render(ref)['tab_stop']


@pytest.mark.parametrize('formula,expected',[('=123','123'),('=true','true'),('="A ""quoted"" title"','A "quoted" title')])
def test_text_property_coerces_compatible_scalars(r,formula,expected):
    assert control(r,{'Text':formula}).property('Text')==expected


def test_link_does_not_invent_programmatic_activation_or_reset(r):
    ref=control(r,{'URL':'="https://example.test/"'})
    for formula in ('Reset(Self)','SetFocus(Self)'):
        with pytest.raises(FxError):r.fx.evaluate(formula,ref.context(True))


@pytest.mark.parametrize('spelling',['URL','Url'])
@pytest.mark.parametrize('url', ['http://127.0.0.1:8846/static/link-target.html','https://example.test/path?x=1#section','HTTP://localhost/','https://[::1]:8846/','https://éxample.test/','mailto:fictional@example.test?subject=Hello','tel:+15550102020'])
def test_evaluated_safe_destinations_and_source_spelling(r,spelling,url):
    props={spelling:'="'+url.replace('"','""')+'"','Text':'="Fictional link"'}
    ref=control(r,props)
    assert ref.property('URL')==url and ref.property('Url')==url
    node=r.render(ref)
    assert node['link_url']==url and node['tab_stop'] and not node['selectable']
    assert not node['errors'] and ref.control.properties==props


@pytest.mark.parametrize('url',['javascript:alert(1)','JaVaScRiPt:alert(1)','data:text/html,<script>1</script>','file:///tmp/a','vbscript:1','blob:https://example.test/id','https://example.test\\@other.test/','https://example.test\n/','https://exa mple.test/','https://','https://example.test:70000/','https://example.test:bad/','mailto:','tel:'])
def test_invalid_destinations_are_isolated_errors(r,url):
    ref=control(r,{'URL':'="'+url.replace('"','""')+'"','Text':'="Still readable"'})
    with pytest.raises(FxError):ref.property('URL')
    assert ref.property('Text')=='Still readable'
    node=r.render(ref)
    assert node['link_url'] is None and not node['tab_stop'] and node['errors']


@pytest.mark.parametrize('url',['ftp://example.test/','custom:target','/relative','//example.test/'])
def test_unverified_protocols_and_relative_destinations_report_unsupported(r,url):
    ref=control(r,{'URL':'='+json.dumps(url)})
    with pytest.raises(FxError) as error:ref.property('URL')
    assert error.value.kind=='Unsupported'


@pytest.mark.parametrize('url',['=Blank()','=""','="   "'])
def test_blank_destinations_have_no_activation(r,url):
    node=r.render(control(r,{'URL':url}))
    assert not node['link_url'] and not node['tab_stop'] and not node['errors']


@pytest.mark.parametrize('enum',['legacy','strong'])
@pytest.mark.parametrize('number',['float','decimal'])
def test_enum_values_and_typed_binding(r,enum,number):
    from powerapps_sim.binding import Binder
    r.environment.update(enum_mode=enum,number_mode=number);r.binder=Binder(r)
    ref=control(r,{'Type':'=LinkAppearance.Subtle','URL':'="https://example.test/"'})
    value=ref.property('Type')
    assert (value.member if isinstance(value,EnumValue) else value)=='Subtle'
    assert r.binder.property_type(ref.control,'Type').kind==('Enum' if enum=='strong' else 'Text')
    assert r.render(ref)['props']['Type']=='Subtle'
    invalid=control(r,{'Type':'=DisplayMode.Edit'})
    with pytest.raises(FxError):invalid.property('Type')


@pytest.mark.parametrize('prop,formula', [('URL','=123'),('Wrap','=1'),('AutoHeight','="yes"'),('Size','=-1'),('PaddingLeft','="5"'),('Color','="red"'),('FontWeight','="Heavy"'),('Align','="Middle"'),('VerticalAlign','="Left"'),('Italic','=5'),('BorderStyle','="Double"')])
def test_invalid_property_types_and_values(r,prop,formula):
    with pytest.raises(FxError):control(r,{prop:formula}).property(prop)


@pytest.mark.parametrize('prop',['FontColor','FontSize','FontItalic','FontUnderline','FontStrikethrough','BorderRadius','Appearance','AcceptsFocus','TabIndex','OnChange','OnSelect','Reset','Tooltip','UnknownProperty'])
def test_removed_and_unverified_properties_remain_in_source(r,prop):
    ref=control(r,{prop:'=Blank()','URL':'="https://example.test/"'})
    with pytest.raises(FxError) as error:ref.property(prop)
    assert error.value.kind=='Unsupported'
    assert r.render(ref)['errors'] and prop in ref.control.properties


@pytest.mark.parametrize('version',['','0.0.1','1.1.0'])
def test_unknown_versions_remain_unsupported(r,version):
    ref=control(r,{'URL':'="https://example.test/"'},version)
    with pytest.raises(FxError) as error:ref.property('URL')
    assert error.value.kind=='Unsupported'
    assert not r.render(ref)['link_url']


def test_url_alias_collision_reports_errors_for_both_reads(r):
    ref=control(r,{'URL':'="https://first.test/"','Url':'="https://second.test/"'})
    for spelling in ('URL','Url'):
        with pytest.raises(FxError,match='both URL and Url'):ref.property(spelling)
    assert r.render(ref)['link_url'] is None


@pytest.mark.parametrize('wrap',[True,False])
def test_autoheight_uses_padding_and_authored_minimum(r,wrap):
    ref=control(r,{'Text':'="A long fictional link title that requires several lines"','Width':'=90','Height':'=32','AutoHeight':'=true','Wrap':'='+str(wrap).lower()})
    height=ref.property('Height')
    assert height>32 if wrap else height==32
    ref.control.properties['Text']='=""';r.invalidate();assert ref.property('Height')==32


@pytest.mark.parametrize('mode',['Edit','View','Disabled'])
def test_display_mode_and_pure_state_observations(r,mode):
    ref=control(r,{'URL':'="https://example.test/"','DisplayMode':'=DisplayMode.'+mode})
    before=serial(r.globals),serial(r.collections),revision(r.project.root),data_revision(r.store)
    node=r.render(ref)
    assert node['tab_stop']==(mode=='Edit')
    assert (serial(r.globals),serial(r.collections),revision(r.project.root),data_revision(r.store))==before
    with pytest.raises(ValueError):r.event(ref.path,'OnSelect')
    with pytest.raises(FxError):r.fx.evaluate('Select(Self)',ref.context(True))


def test_lowercase_url_error_retains_its_source_location(tmp_path):
    p=Project(tmp_path/'location')
    p.update_source('Src/links.pa.yaml','Screens:\n  Home:\n    Children:\n      - Link:\n          Control: ModernLink@1.0.0\n          Properties:\n            Url: ="javascript:bad"\n')
    r=Runtime(p)
    try:
        r.restart();r.state()
        diagnostics=[d for d in r.diagnostics if 'unsafe' in d['message']]
        assert diagnostics and diagnostics[0]['line']==7
    finally:r.close()
