"""Documented icon contracts, offline glyphs and typed media in components."""
from pathlib import Path
import json,xml.etree.ElementTree as ET
import pytest
from powerapps_sim.fixtures import icons_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.fx import Context
from powerapps_sim.icons import catalog,glyph,CLASSIC
from powerapps_sim.syntax import FxError
from powerapps_sim.json_fx import Media
from powerapps_sim.binding import BindScope,value_type

@pytest.fixture
def r(tmp_path):
    runtime=Runtime(icons_project(tmp_path/'icons'));runtime.restart();runtime.state()
    assert not runtime.diagnostics
    yield runtime
    runtime.close()

def test_all_offline_glyphs_resolve_and_have_no_active_content():
    root=Path(__file__).parents[1]/'powerapps_sim/static'
    svg=ET.parse(root/'fluent-icons.svg').getroot()
    symbols={child.get('id') for child in svg};metadata=catalog()
    assert metadata['version']=='1.1.344' and len(metadata['icons'])==2977 and len(symbols)==5899
    for name,styles in metadata['icons'].items():
        for style,symbol in styles.items():assert glyph(name,style)['symbol']==symbol and symbol in symbols
    assert all(element.tag.split('}')[-1] not in ('script','foreignObject','image') for element in svg.iter())
    assert all(not key.startswith('on') and not key.endswith('href') for element in svg.iter() for key in element.attrib)
    assert 'Microsoft Corporation' in (root/'fluent-icons-LICENSE.txt').read_text()

@pytest.mark.parametrize('name,expected',[('Reload','ArrowClockwise'),('Cancel','Dismiss'),('ShoppingCart','Cart'),('View','Eye'),('Add','Add')])
def test_classic_names_and_fluent_names_share_real_glyphs(r,name,expected):
    assert glyph(r.fx.evaluate('Icon.'+name))['name']==expected
    assert glyph(expected.casefold())['name']==expected


def test_decorative_noop_and_interactive_modes(r):
    for name in ('Decorative','HiddenFromAT'):
        node=r.render(r.global_refs[name]);assert not node['selectable'] and not node['tab_stop']
        with pytest.raises(ValueError,match='Decorative'):r.event(node['path'],'OnSelect')
    node=r.render(r.global_refs['Rotate']);assert node['selectable'] and node['tab_stop']
    assert node['props']['Width']==42 and node['icon']['name']=='ArrowClockwise'
    ref=r.global_refs['Rotate'];ref.control.properties['OnSelect']='= /* retained comment */ Blank()';r.invalidate()
    assert not r.render(ref)['selectable'] and not r.render(ref)['tab_stop']

@pytest.mark.parametrize('name',['Disabled','ReadOnly'])
def test_view_and_disabled_events_are_blocked(r,name):
    node=r.render(r.global_refs[name]);assert not node['tab_stop']
    r.event(node['path'],'OnSelect')
    assert r.fx.evaluate('status')=='Ready'


def test_icon_properties_and_component_callbacks_are_reactive_and_isolated(r):
    r.event('IconsScreen/LeftPanel/IncreaseIcon','OnSelect')
    assert r.fx.evaluate('LeftPanel.Total')==11 and r.fx.evaluate('RightPanel.Total')==100
    assert r.globals['leftValue']==11 and r.collections['history']==[{'Panel':'LeftPanel','Total':11}]
    assert r.component_state['IconsScreen/LeftPanel']['variables']['current']==11
    r.event('IconsScreen/Rotate','OnSelect');r.event('IconsScreen/ToggleStyle','OnSelect')
    node=r.render(r.global_refs['Rotate']);assert node['props']['Rotation']==45 and node['icon']['style']=='Filled'
    assert r.render(r.global_refs['SaveSnapshot'])['icon']['name']=='Save'
    assert not r.diagnostics

@pytest.mark.parametrize('prop,raw',[('Icon','=true'),('Icon','="UnregisteredIcon"'),('IconStyle','="Wireframe"'),('Rotation','=true'),('Width','=-2'),('PaddingTop','=-1'),('IconColor','=false'),('IconColor','="red"')])
def test_invalid_icon_properties_are_isolated_without_fake_glyphs(r,prop,raw):
    ref=r.global_refs['Rotate'];ref.control.properties[prop]=raw;r.invalidate()
    node=r.render(ref);assert node['errors'] and r.diagnostics
    assert r.fx.evaluate('LeftPanel.Total')==10
    if prop=='Icon':assert not node.get('icon')

@pytest.mark.parametrize('prop',['Style','TabIndex','AcceptsFocus'])
def test_removed_properties_remain_in_source_and_report_diagnostics(r,prop):
    ref=r.global_refs['Rotate'];ref.control.properties[prop]='=0';r.invalidate()
    node=r.render(ref)
    assert any(prop in e for e in node['errors']) and prop in ref.control.properties


def test_gallery_icon_selection_requires_explicit_formula(r):
    ref=r.global_refs['IconsGallery'];node=r.render(ref)
    child=next(c for c in node['rows'][1]['children'] if c['name']=='RowIcon')
    r.event(child['path'],'OnSelect');assert r.fx.evaluate('IconsGallery.Selected.ID')==2
    assert r.fx.evaluate('status')=='Selected Search'
    template=ref.control.children[0];template.properties.pop('OnSelect');r.invalidate()
    icon=next(c for c in r.render(ref)['rows'][0]['children'] if c['name']=='RowIcon')
    assert not icon['selectable'] and not icon['tab_stop']


def test_image_contracts_preserve_media_through_data_function_and_json(r):
    value=r.fx.evaluate('LeftPanel.CurrentPicture')
    assert isinstance(value,Media) and value_type(value).kind=='Image'
    assert r.binder.property_type(r.project.controls['LeftPanel'][0],'Picture').kind=='Image'
    echo=r.fx.evaluate('LeftPanel.EchoPicture(LeftPanel.CurrentPicture)')
    assert isinstance(echo,Media) and echo==value
    assert r.fx.evaluate('LeftPanel.EchoPicture(Blank())') is None
    assert type(r.fx.evaluate('Text(LeftPanel.CurrentPicture)')) is str
    encoded=r.fx.evaluate('JSON(LeftPanel.CurrentPicture,JSONFormat.IncludeBinaryData)',Context(r,behavior=True))
    assert json.loads(encoded)==value
    assert r.fx.evaluate('JSON({Picture:LeftPanel.CurrentPicture},JSONFormat.IgnoreBinaryData)',Context(r,behavior=True))=='{}'
    with pytest.raises(FxError):r.fx.evaluate('LeftPanel.EchoPicture(123)')
    preview=r.refs['IconsScreen/LeftPanel/PicturePreview'];assert r.render(preview)['props']['Image']==value


def test_image_parameters_preserve_local_asset_origin_and_reject_aggregate_values(r,tmp_path):
    media=Media('/api/asset/fixture.svg',tmp_path)
    fn=r.global_refs['LeftPanel'].property('EchoPicture');result=fn([media])
    assert result is media and result.asset_root==tmp_path
    assert isinstance(fn(['data:image/svg+xml;base64,PHN2Zy8+']),Media)
    with pytest.raises(FxError):fn([{'Image':'bad'}])


def test_image_named_functions_bind_and_run(r):
    r.fx.set_definitions('Echo(p:Image):Image=p;')
    r.analyze();r.invalidate()
    assert isinstance(r.fx.evaluate('Echo(LeftPanel.CurrentPicture)'),Media)
    assert not r.diagnostics


@pytest.mark.parametrize('spec',['Image','{Picture:Image}','[{Picture:Image}]'])
def test_image_type_specifications_report_documented_unsupported_type(r,spec):
    r.fx.set_definitions('I := Type('+spec+');')
    r.analyze();r.invalidate()
    assert r.binder.declared_type('I').kind=='Unknown'
    assert r.binder.type_errors['I'].kind=='Unsupported'
    assert any('Image' in d['message'] for d in r.diagnostics)
    assert r.fx.evaluate('LeftPanel.Total')==10


def test_image_errors_in_aggregate_cells_stay_lazy(r):
    typ=r.binder.declared_type('Record')
    from powerapps_sim.binding import record,FxType
    typ=record({'Good':FxType('Image'),'Bad':FxType('Image')})
    converted=r.fx.coerce_function({'Good':'data:image/png;base64,AAAA','Bad':1},typ,restrictive=False)
    assert isinstance(converted['Good'],Media) and isinstance(converted['Bad'],FxError)


def test_packaged_icon_workflow_roundtrip_and_live_state_isolation(tmp_path):
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision,data_revision
    p=icons_project(tmp_path/'fixture');w=Workspace(tmp_path,p.root,start=False)
    try:
        before=revision(p.root);data=data_revision(w.runtime.store)
        scenario=w.workflows.catalog()['scenarios'][0]['scenario'];result=w.workflows.run(scenario,expected_revision=before)
        assert result['status']=='passed' and len(result['steps'])==32 and not result['diagnostics'],result['steps']
        assert result['collections']['history'][-1]=={'Panel':'RightPanel','Total':101}
        assert not w.runtime.started and not w.runtime.store.rows('Snapshots')
        assert revision(p.root)==before and data_revision(w.runtime.store)==data
        assert 'ModernIcon@1.1.0' in (p.root/'Src/icons.pa.yaml').read_text()
    finally:w.runtime.close()
