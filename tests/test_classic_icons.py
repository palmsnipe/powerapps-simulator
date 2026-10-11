"""Classic 2.5.0 contracts: enum identity, pointer/keyboard and scoped events."""
from pathlib import Path
from copy import deepcopy
import pytest
from powerapps_sim.fixtures import classic_icons_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.icons import classic_catalog,classic_glyph,IconValue
from powerapps_sim.fx import Context,ENUMS
from powerapps_sim.binding import value_type
from powerapps_sim.syntax import FxError

@pytest.fixture
def r(tmp_path):
    r=Runtime(classic_icons_project(tmp_path/'classic'));r.restart();r.state()
    assert not r.diagnostics
    yield r
    r.close()

def test_every_verified_enum_binds_and_resolves_offline(r):
    metadata=classic_catalog();assert metadata['version']=='2.5.0' and len(metadata['icons'])==181
    assert 'a497d6c19880d5a4496127ec9c20d682a8cb38c9' in metadata['source']
    for name,spec in metadata['icons'].items():
        value=r.fx.evaluate('Icon.'+name)
        assert isinstance(value,IconValue) and value.legacy_name==name
        assert value_type(value).kind=='Icon'
        assert r.binder.globals['Icon'].fields[name].kind=='Icon'
        resolved=classic_glyph(value)
        assert resolved['name']==spec['name'] and resolved['style']==spec['style']
    assert not r.diagnostics

def test_enum_identity_survives_branches_records_copies_and_distinct(r):
    smile=r.fx.evaluate('Icon.EmojiSmile');neutral=r.fx.evaluate('Icon.EmojiNeutral')
    assert str(smile)==str(neutral) and smile!=neutral
    assert len({smile,neutral})==2 and deepcopy(smile)==smile
    assert r.fx.evaluate('Icon.EmojiSmile=Icon.EmojiNeutral') is False
    for formula in ('If(true,Icon.BookmarkFilled,Icon.Bookmark)','Coalesce(Blank(),Icon.BookmarkFilled)','First(Table({Glyph:Icon.BookmarkFilled})).Glyph'):
        value=r.fx.evaluate(formula);assert isinstance(value,IconValue)
        assert classic_glyph(value)['style']=='Filled'
    assert r.fx.evaluate('CountRows(Distinct(Table({Glyph:Icon.EmojiSmile},{Glyph:Icon.EmojiNeutral}),Glyph))')==2
    assert type(r.fx.evaluate('Text(Icon.Check)')) is str

def test_classic_template_defaults_and_pointer_keyboard_semantics(r):
    decorative=r.global_refs['Decorative'];node=r.render(decorative)
    assert node['props']['TabIndex']==-1 and node['props']['PreserveAspectRatio'] is True
    assert not node['tab_stop'] and not node['selectable'] and node['icon']['style']=='Filled'
    for key in ('Width','Height'):decorative.control.properties.pop(key)
    decorative.control.properties.pop('Icon');r.invalidate();node=r.render(decorative)
    assert node['props']['Width']==64 and node['props']['Height']==64 and node['icon']['legacy_name']=='ArrowDown'
    pointer=r.render(r.global_refs['Pointer']);assert pointer['selectable'] and not pointer['tab_stop']
    button=r.render(r.global_refs['KeyboardBlank']);assert button['tab_stop'] and not button['selectable']
    r.event(pointer['path'],'OnSelect');r.event(button['path'],'OnSelect')
    assert r.globals['angle']==45 and r.globals['status']=='Pointer rotated'
    assert not r.diagnostics

@pytest.mark.parametrize('name',['Disabled','ReadOnly'])
def test_blocked_icons_and_ancestor_gates_preserve_behavior(r,name):
    before=dict(r.globals);r.event('ClassicScreen/'+name,'OnSelect');assert r.globals==before
    left=r.global_refs['LeftPanel'];left.control.properties['DisplayMode']='=DisplayMode.Disabled';r.invalidate()
    r.event('ClassicScreen/LeftPanel/IncreaseIcon','OnSelect');assert r.fx.evaluate('LeftPanel.Total')==10

def test_gallery_implicit_action_selects_its_own_row_and_preserves_default_tabindex(r):
    gallery=r.render(r.global_refs['IconGallery']);child=gallery['rows'][2]['children'][0]
    assert child['selectable'] and child['tab_stop']
    r.event(child['path'],'OnSelect')
    assert r.fx.evaluate('IconGallery.Selected.Name')=='ArrowLeft' and r.globals['status']=='Selected ArrowLeft'
    pointer=next(c for c in gallery['rows'][3]['children'] if c['name']=='ImplicitPointer')
    assert pointer['selectable'] and not pointer['tab_stop'] and pointer['props']['TabIndex']==-1
    r.event(pointer['path'],'OnSelect');assert r.fx.evaluate('IconGallery.Selected.Name')=='ArrowRight'
    assert not r.diagnostics

def test_isolated_component_actions_callbacks_and_reset(r):
    r.event('ClassicScreen/LeftPanel/IncreaseIcon','OnSelect');r.event('ClassicScreen/RightPanel/IncreaseIcon','OnSelect')
    assert r.fx.evaluate('LeftPanel.Total')==11 and r.fx.evaluate('RightPanel.Total')==101
    assert r.collections['history']==[{'Panel':'LeftPanel','Total':11},{'Panel':'RightPanel','Total':101}]
    r.event('ClassicScreen/ResetLeft','OnSelect')
    assert r.fx.evaluate('LeftPanel.Total')==10 and r.fx.evaluate('RightPanel.Total')==101
    assert len(r.collections['history'])==2 and not r.diagnostics

@pytest.mark.parametrize('prop,formula,kind',[('Icon','"Add"','Type'),('Icon','Icon.Missing','Name'),('Icon','Icon.Upload','Unsupported'),('Color','"red"','Type'),('HoverColor','false','Type'),('PreserveAspectRatio','0','Type'),('Rotation','true','Type'),('Width','-1','Validation'),('TabIndex','0.5','Type'),('FocusedBorderThickness','-2','Validation')])
def test_invalid_properties_remain_in_source_and_are_isolated(r,prop,formula,kind):
    ref=r.global_refs['Pointer'];ref.control.properties[prop]='='+formula;r.analyze();r.invalidate()
    node=r.render(ref);assert node['errors'] and any(d['kind']==kind for d in r.diagnostics)
    assert ref.control.properties[prop]=='='+formula and r.fx.evaluate('LeftPanel.Total')==10
    if prop=='Icon':assert not node.get('icon')

@pytest.mark.parametrize('prop',['IconStyle','IconColor','AcceptsFocus','BasePaletteColor','Style'])
def test_modern_only_properties_are_visible_unsupported_contracts(r,prop):
    ref=r.global_refs['Pointer'];ref.control.properties[prop]='=Blank()';r.invalidate()
    assert any(prop in e for e in r.render(ref)['errors'])
    assert prop in ref.control.properties

def test_setfocus_does_not_silently_extend_unsupported_targets(r):
    with pytest.raises(FxError,match='SetFocus does not support Classic/Icon'):
        r.fx.evaluate('SetFocus(KeyboardBlank)',Context(r,behavior=True))

def test_positive_tabindex_normalizes_to_a_stop_and_nonfinite_rejects(r):
    ref=r.global_refs['Pointer'];ref.control.properties['TabIndex']='=5';r.invalidate()
    assert r.render(ref)['tab_stop']
    ref.control.properties['TabIndex']='=1/0';r.invalidate()
    assert not r.render(ref)['tab_stop'] and r.render(ref)['errors']

def test_packaged_workflow_and_source_roundtrip_leave_live_owner_unchanged(tmp_path):
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision,data_revision
    p=classic_icons_project(tmp_path/'p');w=Workspace(tmp_path,p.root,start=False)
    try:
        before=revision(p.root);data=data_revision(w.runtime.store)
        scenario=w.workflows.catalog()['scenarios'][0]['scenario'];result=w.workflows.run(scenario,expected_revision=before)
        assert result['status']=='passed' and len(result['steps'])==29 and not result['diagnostics'],result['steps']
        assert result['collections']['history'][-1]=={'Panel':'RightPanel','Total':101}
        assert revision(p.root)==before and data_revision(w.runtime.store)==data
        assert not w.runtime.started and not w.runtime.store.rows('Snapshots')
        text=(p.root/'Src/classic-icons.pa.yaml').read_text();assert 'Classic/Icon@2.5.0' in text and 'Icon.BookmarkFilled' in text
    finally:w.runtime.close()


def test_classic_only_accepts_real_selection_events(r):
    with pytest.raises(ValueError,match='only accept OnSelect'):
        r.event('ClassicScreen/Pointer','OnChange',True)
    with pytest.raises(ValueError,match='only accept OnSelect'):
        r.event('ClassicScreen/Pointer','Pressed',True)
    assert r.globals['angle']==0


def test_unknown_versions_are_reported_without_rewriting_source(r):
    ref=r.global_refs['Pointer'];ref.control.raw['Control']='Classic/Icon@9.9.9';ref.control.kind='Classic/Icon@9.9.9'
    r.analyze()
    assert any(d['kind']=='Unsupported' and '9.9.9' in d['message'] for d in r.diagnostics)
    assert ref.control.raw['Control']=='Classic/Icon@9.9.9'


def test_enum_json_serialization_does_not_claim_studio_fidelity(r):
    with pytest.raises(FxError,match='has not been verified'):
        r.fx.evaluate('JSON(Icon.Check)',Context(r,behavior=True))
    assert r.fx.evaluate('JSON({Glyph:Icon.Check,Title:"kept"},JSONFormat.IgnoreUnsupportedTypes)',Context(r,behavior=True))=='{"Title":"kept"}'
    assert r.fx.evaluate('JSON(Text(Icon.Check))',Context(r,behavior=True))=='"Checkmark"'
