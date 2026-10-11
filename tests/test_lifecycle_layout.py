"""Behavior ordering and formula geometry, with an independent clean source fixture."""
from zipfile import ZipFile
from io import BytesIO

import pytest
from powerapps_sim.fixtures import lifecycle_project
from powerapps_sim.fx import Context
from powerapps_sim.runtime import Runtime
from powerapps_sim.source import Project, dump_yaml
from powerapps_sim.syntax import FxError


@pytest.fixture
def lifecycle(tmp_path):
    runtime = Runtime(lifecycle_project(tmp_path/'lifecycle'))
    runtime.restart()
    yield runtime
    runtime.close()


def trace(runtime):
    return [r['Step'] for r in runtime.collections['trace']]


def test_component_input_reset_and_explicit_reset_order(lifecycle):
    r = lifecycle
    assert not r.diagnostics
    assert trace(r) == ['start', 'visible']
    r.event('Lifecycle/Panels/LeftPanel/Increase', 'OnSelect')
    r.event('Lifecycle/Panels/RightPanel/Increase', 'OnSelect')
    assert r.fx.evaluate('LeftPanel.Total') == 11
    assert r.fx.evaluate('RightPanel.Total') == 101
    r.event('Lifecycle/Panels/LeftPanel/Note', 'OnChange', 'edited note')
    r.event('Lifecycle/ChangeSeed', 'OnSelect')
    assert trace(r)[-3:] == ['before seed', 'after seed', 'LeftPanel reset 20']
    assert r.fx.evaluate('LeftPanel.ResetCount') == 1
    assert r.fx.evaluate('LeftPanel.Total') == 20
    assert r.fx.evaluate('RightPanel.Total') == 101
    assert r.refs['Lifecycle/Panels/LeftPanel/Note'].property('Text') == 'component note'
    r.event('Lifecycle/ResetLeft', 'OnSelect')
    assert trace(r)[-3:] == ['before reset', 'LeftPanel reset 20', 'after reset']
    assert r.fx.evaluate('LeftPanel.ResetCount') == 2
    r.state(); r.state()
    assert r.fx.evaluate('LeftPanel.ResetCount') == 2
    r.restart()
    assert trace(r) == ['start', 'visible']
    assert r.fx.evaluate('LeftPanel.ResetCount') == 0
    assert not r.diagnostics


def test_property_reads_are_pure_and_input_changes_settle(lifecycle):
    r = lifecycle
    ctx = Context(r, behavior=True)
    r.fx.evaluate('Set(seed, 30)', ctx)
    assert r.fx.evaluate('LeftPanel.Seed') == 30
    assert r.fx.evaluate('LeftPanel.ResetCount') == 0
    r.drain_events()
    assert r.fx.evaluate('LeftPanel.ResetCount') == 1
    r.fx.evaluate('Set(seed, 30)', ctx); r.drain_events()
    assert r.fx.evaluate('LeftPanel.ResetCount') == 1


def test_gallery_child_select_is_queued_and_uses_requested_row(lifecycle):
    r = lifecycle
    # No state/render call is needed to materialize the selected template.
    r.event('Lifecycle/QueueSelect', 'OnSelect')
    assert trace(r)[-4:] == ['before select', 'after select', 'child second', 'gallery second']
    assert r.fx.evaluate('EventsGallery.Selected.ID') == 2
    assert not r.diagnostics


@pytest.mark.parametrize('expression', ['Select(EventsGallery,0)', 'Select(EventsGallery,-1)', 'Select(EventsGallery,3)', 'Select(EventsGallery,1.5)', 'Select(EventsGallery,Blank())', 'Select(EventsGallery,true)', 'Select(ChangeSeed,1)', 'Select(EventsGallery,1,NotAChild)'])
def test_select_invalid_targets_do_not_mutate_selection(lifecycle, expression):
    r = lifecycle
    before = r.fx.evaluate('EventsGallery.Selected')
    with pytest.raises(FxError):
        r.fx.evaluate(expression, Context(r, behavior=True))
    assert r.fx.evaluate('EventsGallery.Selected') == before
    assert not r.event_queue


def simple_runtime(tmp_path, children, other=None):
    p = Project(tmp_path/'custom')
    p.update_source('Src/custom.pa.yaml', dump_yaml({'Screens':{'Home':{'Children':children}, **(other or {})}}))
    r = Runtime(p); r.restart()
    return r


def button(name, formula):
    return {name:{'Control':'ModernButton@1.0.0','Properties':{'OnSelect':formula}}}


def test_select_self_indirect_and_cross_screen_are_diagnosed(tmp_path):
    r = simple_runtime(tmp_path, [button('A','=Select(B)'),button('B','=Select(A)'),button('SelfButton','=Select(Self)'),button('Cross','=Select(OtherButton)')], {'Other':{'Children':[button('OtherButton','=Notify("wrong")')]}})
    try:
        r.event('Home/A', 'OnSelect')
        assert any(d['kind']=='Cycle' and d['member']=='B.OnSelect' for d in r.diagnostics)
        assert not r.event_queue
        r.event('Home/SelfButton', 'OnSelect')
        assert any(d['kind']=='Cycle' and d['member']=='SelfButton.OnSelect' for d in r.diagnostics)
        r.event('Home/Cross', 'OnSelect')
        assert any('another screen' in d['message'] for d in r.diagnostics)
        # Unhandled rule errors now display the App.OnError fallback. The
        # cross-screen Select must still never execute the target's Notify.
        assert not any(n.get('origin')!='App.OnError' for n in r.notifications)
    finally:
        r.close()


def test_flexible_dimensions_are_visible_to_powerfx(lifecycle):
    r = lifecycle
    r.viewport.update(width=1000); r.invalidate()
    # Container 960 - padding24 - gaps24 - fixed60 = 852, shared1:2.
    assert r.fx.evaluate('LeftPanel.Width') == 284
    assert r.fx.evaluate('RightPanel.Width') == 568
    assert r.fx.evaluate('LeftPanel.Height') == 184
    assert r.fx.evaluate('LeftPanel.X') == 12
    assert r.fx.evaluate('RightPanel.X') == 380
    r.event('Lifecycle/HideSpacer', 'OnSelect')
    # Hidden controls contribute neither their fixed size nor an extra gap.
    assert r.fx.evaluate('LeftPanel.Width') == 308
    assert r.fx.evaluate('RightPanel.Width') == 616
    assert r.fx.evaluate('RightPanel.X') == 332
    r.viewport.update(width=460); r.invalidate()
    assert r.fx.evaluate('LeftPanel.Width') == 180
    assert r.fx.evaluate('RightPanel.Width') == 204
    r.viewport.update(width=400); r.invalidate()
    # Minimums cause overflow rather than silently shrinking controls.
    assert r.fx.evaluate('LeftPanel.Width') == 180
    assert r.fx.evaluate('RightPanel.Width') == 180
    assert not r.diagnostics


def test_responsive_defaults_and_maximum_redistribution(tmp_path):
    children = [{'Row':{'Control':'GroupContainer@1.5.0','Variant':'AutoLayout','Properties':{'Width':'=800','Height':'=200','LayoutDirection':'=LayoutDirection.Horizontal','LayoutAlignItems':'=LayoutAlignItems.Stretch'},'Children':[
        {'Fixed':{'Control':'ModernButton@1.0.0','Properties':{'Width':'=120'}}},
        {'Small':{'Control':'GroupContainer@1.5.0','Properties':{'LayoutMaxWidth':'=100'}}},
        {'Large':{'Control':'GroupContainer@1.5.0','Properties':{}}},
    ]}}]
    r = simple_runtime(tmp_path, children)
    try:
        assert r.fx.evaluate('Fixed.FillPortions') == 0
        assert r.fx.evaluate('Fixed.LayoutMinWidth') == 96  # Version1.0.0 default, not authored120.
        assert r.fx.evaluate('Small.FillPortions') == 1
        assert r.fx.evaluate('Small.LayoutMinWidth') == 32
        assert r.fx.evaluate('Small.Width') == 100
        assert r.fx.evaluate('Large.Width') == 580
        assert r.fx.evaluate('Small.X') == 120
        assert r.fx.evaluate('Large.X') == 220
        assert r.fx.evaluate('Fixed.Height') == 200
        assert not r.diagnostics
    finally:
        r.close()


def test_lifecycle_export_preserves_raise_on_reset_without_emulator_fields(lifecycle):
    r = lifecycle
    with ZipFile(BytesIO(r.project.export())) as z:
        assert z.namelist() == ['Src/lifecycle.pa.yaml']
        source = z.read(z.namelist()[0]).decode()
        assert 'RaiseOnReset: true' in source
        assert 'viewport' not in source and 'environment' not in source
    assert r.project.documents['Src/lifecycle.pa.yaml'] == source


@pytest.mark.parametrize('first_read', ['Box.Height','Caption.Height'])
def test_content_sized_parent_measures_before_stretch(tmp_path, first_read):
    r = simple_runtime(tmp_path, [{'Column':{'Control':'GroupContainer@1.5.0','Variant':'AutoLayout','Properties':{'LayoutDirection':'=LayoutDirection.Vertical','Width':'=500','Height':'=400'},'Children':[
        {'Box':{'Control':'GroupContainer@1.5.0','Variant':'AutoLayout','Properties':{'FillPortions':'=0','LayoutDirection':'=LayoutDirection.Horizontal','LayoutAlignItems':'=LayoutAlignItems.Stretch','Height':'=Caption.Height + 20'},'Children':[
            {'Caption':{'Control':'ModernText@1.0.0','Properties':{'Height':'=60','Text':'="content"','LayoutMinHeight':'=0'}}},
        ]}},
    ]}}])
    try:
        r.fx.evaluate(first_read)
        assert r.fx.evaluate('Box.Height') == 80
        assert r.fx.evaluate('Caption.Height') == 80
        r.state()
        assert not r.diagnostics
    finally:
        r.close()


def test_genuine_dimension_cycle_is_not_hidden(tmp_path):
    r = simple_runtime(tmp_path, [{'Row':{'Control':'GroupContainer@1.5.0','Variant':'AutoLayout','Properties':{'LayoutDirection':'=LayoutDirection.Horizontal','LayoutAlignItems':'=LayoutAlignItems.Stretch','Height':'=Bad.Height'},'Children':[
        {'Bad':{'Control':'ModernText@1.0.0','Properties':{'Height':'=Self.Height'}}},
    ]}}])
    try:
        with pytest.raises(FxError, match='cycle'):
            r.fx.evaluate('Row.Height')
        assert any(d['kind']=='Cycle' for d in r.diagnostics)
    finally:
        r.close()


def test_wrapped_geometry_is_available_without_unsupported_warning(lifecycle):
    r = lifecycle
    r.global_refs['Panels'].control.properties['LayoutWrap'] = '=true'
    r.invalidate(); r.state()
    assert r.fx.evaluate('LeftPanel.Width') > 0
    assert not r.diagnostics


def test_self_reset_is_bounded_and_diagnosed(lifecycle):
    r = lifecycle
    r.project.components['ResetPanel'].properties['OnReset'] = '=Reset(ResetPanel)'
    r.event('Lifecycle/ResetLeft', 'OnSelect')
    assert any(d['kind']=='Cycle' and d['member']=='ResetPanel.OnReset' for d in r.diagnostics)
    assert not r.resetting


def test_multi_input_changes_raise_one_reset_per_instance(lifecycle):
    r = lifecycle
    custom = r.project.components['ResetPanel'].raw['CustomProperties']
    custom['Details'] = {'PropertyKind':'Input','DataType':'Record','RaiseOnReset':True,'Default':'={N: 0}'}
    r.global_refs['LeftPanel'].control.properties['Details'] = '={N: seed}'
    r.invalidate(); r.state()  # Register the new input baseline.
    r.event('Lifecycle/ChangeSeed', 'OnSelect')
    assert r.fx.evaluate('LeftPanel.ResetCount') == 1
    assert r.fx.evaluate('RightPanel.ResetCount') == 0
    assert trace(r).count('LeftPanel reset 20') == 1


def test_failed_input_is_isolated_and_recovers(lifecycle):
    r = lifecycle
    r.global_refs['LeftPanel'].control.properties['Seed'] = '=If(seed = 20, 1 / 0, seed)'
    r.invalidate(); r.state()
    r.event('Lifecycle/ChangeSeed', 'OnSelect')
    assert r.fx.evaluate('RightPanel.Total') == 100
    assert r.fx.evaluate('LeftPanel.ResetCount') == 0
    assert any(d['member']=='LeftPanel.Seed' for d in r.diagnostics)
    r.event('Lifecycle/ChangeSeed', 'OnSelect')
    assert r.fx.evaluate('LeftPanel.Total') == 30
    assert r.fx.evaluate('LeftPanel.ResetCount') == 1


def test_instance_size_formula_keeps_host_scope(lifecycle):
    r = lifecycle
    left = r.global_refs['LeftPanel']
    left.control.properties.update(FillPortions='=0', Width='=seed * 20', Height='=App.Height / 3')
    left.control.properties['AlignInContainer'] = '=AlignInContainer.Start'
    r.invalidate()
    assert left.property('Width') == 200
    assert left.property('Height') == 200
    assert not r.diagnostics
