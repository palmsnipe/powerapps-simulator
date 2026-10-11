"""Recovered button defaults, glyph selection, typed properties and scoped behavior."""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile
import pytest
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision,data_revision
from powerapps_sim.fixtures import buttons_project
from powerapps_sim.runtime import Runtime,serial
from powerapps_sim.syntax import FxError


@pytest.fixture
def r(tmp_path):
    result=Runtime(buttons_project(tmp_path/'buttons'));result.restart();result.state()
    assert not result.diagnostics
    yield result
    result.close()


def test_imported_manifest_defaults_and_numeric_property_binding(r):
    ref=r.global_refs['TextOnly']
    for name,expected in [('IconStyle','Outline'),('IconRotation',0),('Width',180),('Height',40)]:
        assert ref.property(name)==expected
    ref.control.properties.pop('Layout');ref.control.properties.pop('Icon');r.invalidate()
    assert ref.property('Layout')=='IconBefore' and ref.property('Icon')==''
    assert r.binder.property_type(ref.control,'IconRotation').kind=='Number'
    assert r.binder.property_type(ref.control,'Color').kind=='Color'


@pytest.mark.parametrize('mode',['float','decimal'])
def test_icon_rotation_retains_native_number_identity_in_both_hosts(tmp_path,mode):
    from powerapps_sim.binding import value_type
    p=buttons_project(tmp_path/'p');p.config['environment']['number_mode']=mode;p.save_config()
    r=Runtime(p)
    try:
        r.restart();r.event('ButtonsLab/Rotate','OnSelect')
        ref=r.refs['ButtonsLab/LeftPanel/Increase']
        value=ref.property('IconRotation')
        assert value==45 and value_type(value).kind=='Number'
        assert r.binder.property_type(ref.control,'IconRotation').kind=='Number'
    finally:r.close()


def test_glyph_style_rotation_and_component_inputs_are_reactive_without_reset(r):
    left=r.refs['ButtonsLab/LeftPanel/Increase'];right=r.refs['ButtonsLab/RightPanel/Increase']
    assert r.render(left)['icon']['style']=='Outline'
    r.event(left.path,'OnSelect');r.event('ButtonsLab/ToggleStyle','OnSelect');r.event('ButtonsLab/Rotate','OnSelect')
    node=r.render(left);peer=r.render(right)
    assert node['icon']['style']=='Filled' and node['props']['IconRotation']==45
    assert peer['icon']['style']=='Outline' and peer['props']['IconRotation']==0
    assert node['icon']['symbol']!=peer['icon']['symbol']
    assert r.fx.evaluate('LeftPanel.Count')==1 and r.fx.evaluate('RightPanel.Count')==0
    r.event('ButtonsLab/ToggleLayout','OnSelect')
    assert r.render(left)['props']['Layout']=='IconAfter' and r.render(right)['props']['Layout']=='IconBefore'
    assert not r.diagnostics


@pytest.mark.parametrize('prop,raw',[
 ('Icon','=true'),('Icon','="UnknownButtonGlyph"'),('IconStyle','="Wireframe"'),
 ('IconRotation','=true'),('IconRotation','="45"'),('IconRotation','=1/0'),
 ('Layout','="Vertical"'),('Appearance','="Flat"'),('Align','="Middle"'),
 ('VerticalAlign','="Center"'),('BorderStyle','="Double"'),('FontWeight','="Heavy"'),
 ('BorderThickness','=-1'),('RadiusTopRight','=-2'),('Size','=true'),
 ('Italic','="yes"'),('Underline','=1'),('Strikethrough','=[]'),
 ('Color','="red"'),('BorderColor','=false')])
def test_bad_properties_are_isolated_and_reported_once_per_observation(r,prop,raw):
    ref=r.global_refs['IconOnly'];ref.control.properties[prop]=raw;r.invalidate()
    r.state()
    assert any(d['member']==f'IconOnly.{prop}' for d in r.diagnostics)
    assert len(r.collections['failures'])==1
    r.state();assert len(r.collections['failures'])==1
    assert not r.render(r.global_refs['TextOnly'])['errors']


def test_errors_can_be_caught_before_the_control_observes_them(r):
    ref=r.global_refs['IconOnly'];ref.control.properties['IconRotation']='=IfError(1/0,45)';r.invalidate()
    assert r.render(ref)['props']['IconRotation']==45
    assert not r.diagnostics and not r.collections['failures']


def test_blank_style_and_rotation_keep_theme_fallbacks_without_fabricated_glyphs(r):
    ref=r.global_refs['IconOnly'];ref.control.properties.update(Icon='=Blank()',IconStyle='=Blank()',IconRotation='=Blank()');r.invalidate()
    node=r.render(ref)
    assert node['icon'] is None and node['props']['IconRotation'] is None and not node['errors']


def test_disabled_view_and_component_resets(r):
    r.event('ButtonsLab/IconOnly','OnSelect');assert r.fx.evaluate('LeftPanel.Count')==2
    r.event('ButtonsLab/ToggleGate','OnSelect')
    r.event('ButtonsLab/Gated','OnSelect');assert r.fx.evaluate('LeftPanel.Count')==2
    ref=r.global_refs['Gated'];ref.control.properties['DisplayMode']='=DisplayMode.View';r.invalidate()
    r.event(ref.path,'OnSelect');assert r.fx.evaluate('LeftPanel.Count')==2
    r.event('ButtonsLab/LeftPanel/ResetCounter','OnSelect')
    assert r.fx.evaluate('LeftPanel.Count')==0 and r.fx.evaluate('IsEmpty(LeftPanel.History)')


@pytest.mark.parametrize('mode',['float','decimal'])
@pytest.mark.parametrize('language',['en-US','fr-CA'])
def test_workflow_and_source_exports_preserve_owner(tmp_path,mode,language):
    p=buttons_project(tmp_path/'p');w=Workspace(tmp_path/'workspace',p.root)
    try:
        before=deepcopy(serial(w.ai.read_runtime())),revision(p.root),data_revision(w.runtime.store)
        scenario=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario'])
        scenario['environment']={'language':language,'number_mode':mode,'enum_mode':'strong'}
        result=w.workflows.run(scenario,expected_revision=revision(p.root))
        assert result['status']=='passed' and len(result['steps'])==32,result['steps']
        assert len(result['diagnostics'])==1 and result['diagnostics'][0]['member']=='SaveSnapshot.OnSelect'
        assert before==(serial(w.ai.read_runtime()),revision(p.root),data_revision(w.runtime.store))
        with ZipFile(BytesIO(p.export())) as archive:
            assert archive.namelist()==['Src/buttons.pa.yaml']
            source=archive.read(archive.namelist()[0]).decode()
            assert 'IconRotation:' in source and 'button_authored' not in source and 'component_contracts' not in source
    finally:w.runtime.close()


def test_snapshot_writes_use_display_names_and_persist_after_restart(r):
    r.event('ButtonsLab/LeftPanel/Increase','OnSelect');r.event('ButtonsLab/Rotate','OnSelect');r.event('ButtonsLab/SaveSnapshot','OnSelect')
    assert r.store.rows('Snapshots')[0]['Icon rotation']==45 and r.store.rows('Snapshots')[0]['Clicks']==1
    r.restart();r.state()
    assert r.store.rows('Snapshots')[0]['Clicks']==1 and r.fx.evaluate('LeftPanel.Count')==0
