"""Archived Button contracts, typed actions, focus and error isolation."""
from copy import deepcopy
import io
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from powerapps_sim.canvas_buttons import catalog
from powerapps_sim.fx import Context
from powerapps_sim.runtime import Runtime
from powerapps_sim.source import Project, dump_yaml
from powerapps_sim.syntax import FxError


VERSIONS = tuple(catalog())


def make(tmp_path, version='0.0.43', props=None, environment=None):
    p = Project(tmp_path / 'buttons')
    p.update_source('Src/buttons.pa.yaml', dump_yaml({
        'App': {'Properties': {'OnStart': '=Set(count,0);Clear(events)'}},
        'Screens': {'Home': {'Children': [
            {'Action': {'Control': 'Button@' + version, 'Properties': {
                'OnSelect': '=Set(count,count+1);Collect(events,{Name:Self.Name,Count:count})', **(props or {})}}},
            {'Peer': {'Control': 'Button@' + version}},
            {'FocusAction': {'Control': 'ModernButton@1.0.0', 'Properties': {'OnSelect': '=SetFocus(Action)'}}},
        ]}},
    }))
    p.config['environment'].update(environment or {});p.save_config()
    r = Runtime(p);r.restart();r.state()
    return r


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('numbers', ['float', 'decimal'])
@pytest.mark.parametrize('enums', ['legacy', 'strong'])
def test_archived_defaults_enum_backings_actions_and_focus(tmp_path, version, numbers, enums):
    r = make(tmp_path, version, {
        'Layout': '=ButtonCanvas.Layout.IconAfter',
        'Appearance': '=ButtonCanvas.Appearance.Secondary',
        'IconStyle': '=ButtonCanvas.IconStyle.Filled',
        'Icon': '="Add"', 'IconRotation': '=-45', 'FontSize': '=18',
        'BorderRadius': '=8', 'BorderRadiusTopLeft': '=12',
    }, {'number_mode': numbers, 'enum_mode': enums})
    try:
        assert not r.diagnostics, r.diagnostics
        g = r.refs['Home/Action']
        for prop in catalog()[version]['types']:g.property(prop)
        assert (g.property('Text'), g.property('Width'), g.property('Height')) == ('Button', 96, 32)
        assert g.property('Layout') == 'Icon after'
        assert g.property('AcceptsFocus') is True
        assert r.binder.property_type(g.control, 'FontSize').kind == 'Number'
        node = r.render(g)
        assert not node['errors'] and node['icon']['style'] == 'Filled'
        assert node['canvas_button']['auto_disable'] and node['tab_stop']
        r.event(g.path, 'OnSelect');r.event(g.path, 'OnSelect')
        assert r.globals['count'] == 2 and len(r.collections['events']) == 2
        assert r.collections['events'][-1]['Name'] == 'Action'
        r.event('Home/FocusAction', 'OnSelect')
        assert r.focus_request['path'] == g.path
        assert not r.button_busy
    finally:r.close()


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('property,raw', [
    ('Size', '=18'), ('Color', '=Color.Red'), ('Italic', '=true'),
    ('RadiusTopLeft', '=8'), ('Pressed', '=false'), ('OnChange', '=Blank()'),
    ('AutoDisableOnSelect', '=false'), ('PCFTeamsTheme', '=Blank()'), ('Reset', '=false'),
])
def test_new_property_aliases_outputs_and_flags_are_not_authored(tmp_path, version, property, raw):
    r = make(tmp_path, version, {property: raw})
    try:
        g = r.refs['Home/Action']
        assert g.control.properties[property] == raw
        assert any(d['kind'] == 'Unsupported' for d in r.diagnostics)
        with pytest.raises(FxError):g.property(property)
        assert not r.render(r.refs['Home/Peer'])['errors']
        assert property + ':' in r.project.documents['Src/buttons.pa.yaml']
    finally:r.close()


@pytest.mark.parametrize('property,raw', [
    ('Layout', '=ButtonLayout.IconBefore'), ('Appearance', '="Danger"'),
    ('IconStyle', '="Regular"'), ('FontSize', '=-1'), ('BorderRadius', '=-1'),
    ('TabIndex', '=0.5'), ('AcceptsFocus', '="yes"'), ('FontItalic', '=1'),
    ('Text', '=123'), ('IconRotation', '=false'),
])
def test_bad_types_and_enum_values_are_source_located(tmp_path, property, raw):
    r = make(tmp_path, props={property: raw})
    try:
        assert r.diagnostics and any(d.get('source') == 'Src/buttons.pa.yaml' for d in r.diagnostics)
        assert not r.render(r.refs['Home/Peer'])['errors']
    finally:r.close()


@pytest.mark.parametrize('mode', ['View', 'Disabled'])
def test_non_edit_modes_block_native_clicks(tmp_path, mode):
    r = make(tmp_path, props={'DisplayMode': '=DisplayMode.' + mode})
    try:
        r.event('Home/Action', 'OnSelect')
        assert r.globals['count'] == 0 and not r.collections['events']
    finally:r.close()


def test_accepts_focus_and_negative_tab_index_are_independent(tmp_path):
    r = make(tmp_path, props={'AcceptsFocus': '=false'})
    try:
        g = r.refs['Home/Action'];assert not r.render(g)['tab_stop']
        r.event('Home/FocusAction', 'OnSelect');assert r.focus_request is None
        r.event(g.path, 'OnSelect');assert r.globals['count'] == 1
        g.control = deepcopy(g.control);g.control.properties['AcceptsFocus'] = '=true';g.control.properties['TabIndex'] = '=-1'
        r.invalidate();assert not r.render(g)['tab_stop']
    finally:r.close()


@pytest.mark.parametrize('name,value,selection', [('Pressed', True, None), ('OnChange', None, None), ('OnSelect', 1, None), ('OnSelect', None, [0])])
def test_native_event_payloads_do_not_create_unsupported_outputs(tmp_path, name, value, selection):
    r = make(tmp_path)
    try:
        with pytest.raises(ValueError):r.event('Home/Action', name, value, selection)
        assert not r.refs['Home/Action'].state and not r.collections['events']
    finally:r.close()


def test_auto_disabled_subscription_prevents_reentrant_action_and_releases_after_error(tmp_path):
    r = make(tmp_path)
    try:
        g = r.refs['Home/Action'];original = r.execute;seen = []
        def execute(formula, ctx, *args, **kwargs):
            if ctx.self_ref is g:
                seen.append(r.render(g)['canvas_button']['busy'])
                r.run_event(g, 'OnSelect')
            return original(formula, ctx, *args, **kwargs)
        r.execute = execute;r.event(g.path, 'OnSelect')
        assert seen == [True] and r.globals['count'] == 1 and not r.button_busy
        g.control = deepcopy(g.control);g.control.properties['OnSelect'] = '=Error({Kind:ErrorKind.Validation,Message:"Fictional failure"})'
        r.invalidate();r.event(g.path, 'OnSelect')
        assert not r.button_busy and not r.render(g)['canvas_button']['busy']
    finally:r.close()


@pytest.mark.parametrize('version', VERSIONS)
def test_archive_import_preserves_windows_paths_and_native_actions(tmp_path, version):
    artifact = 'classic-rating-MDA_' + ('ClassicControls_Solution_1_0_0_3.zip' if version == '0.0.43' else 'InputControls_Solution_1_0_0_4.zip')
    path = Path(__file__).parents[1] / 'test-results' / artifact
    if not path.exists():pytest.skip('Optional pinned first-party archive unavailable')
    assert hashlib.sha256(path.read_bytes()).hexdigest() == catalog()[version]['artifact_sha256']
    with zipfile.ZipFile(path) as outer:
        for name in outer.namelist():
            if not name.endswith('.msapp'):continue
            payload = outer.read(name)
            with zipfile.ZipFile(io.BytesIO(payload)) as inner:
                if not any(('Button@' + version).encode() in inner.read(n) for n in inner.namelist() if n.replace('\\', '/').startswith('Src/') and n.endswith('.yaml')):continue
            p = Project.import_archive(payload, tmp_path / 'official');documents = dict(p.documents)
            r = Runtime(p)
            try:
                g = next(g for g in r.refs.values() if g.family == 'Button')
                assert not r.render(g)['errors']
                r.event(g.path, 'OnSelect')
                assert r.screen_context[r.screen_for(g)]['SelectText'] == 'Button Clicked!'
                assert p.documents == documents
            finally:r.close()
            return
    pytest.fail('Native Button missing from pinned archive')


@pytest.mark.parametrize('language', ['en-US', 'fr-CA'])
@pytest.mark.parametrize('numbers', ['float', 'decimal'])
@pytest.mark.parametrize('enums', ['legacy', 'strong'])
def test_public_component_form_workflow_preserves_owner(tmp_path, language, numbers, enums):
    from powerapps_sim.fixtures import canvas_buttons_project
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision, data_revision
    p = canvas_buttons_project(tmp_path / 'public');w = Workspace(tmp_path, p.root, start=False)
    try:
        before = revision(p.root), data_revision(w.runtime.store), w.ai.read_runtime(), w.ai.export_source()
        scenario = deepcopy(w.workflows.catalog()['scenarios'][0]['scenario'])
        scenario['environment'] = {'language': language, 'number_mode': numbers, 'enum_mode': enums}
        result = w.workflows.run(scenario, expected_revision=before[0])
        assert result['status'] == 'passed' and len(result['steps']) == 31 and not result['diagnostics'], result
        assert before == (revision(p.root), data_revision(w.runtime.store), w.ai.read_runtime(), w.ai.export_source())
    finally:w.runtime.close()


def test_responsive_native_button_minimums_follow_template_and_authored_values_win(tmp_path):
    p = Project(tmp_path / 'layout')
    p.update_source('Src/layout.pa.yaml', dump_yaml({'Screens': {'Home': {'Children': [
        {'Group': {'Control': 'GroupContainer@1.5.0', 'Variant': 'AutoLayout', 'Properties': {'LayoutDirection': '=LayoutDirection.Horizontal'}, 'Children': [
            {'Action': {'Control': 'Button@0.0.43'}},
            {'Peer': {'Control': 'Button@0.0.44', 'Properties': {'LayoutMinWidth': '=130'}}},
        ]}},
    ]}}}))
    r = Runtime(p)
    try:
        g = r.refs['Home/Group/Action'];peer = r.refs['Home/Group/Peer']
        assert (g.property('LayoutMinWidth'), g.property('LayoutMinHeight')) == (96, 32)
        assert peer.property('LayoutMinWidth') == 130
        assert not r.render(g)['errors']
    finally:r.close()


def test_gallery_actions_select_own_row_and_update_context_with_stable_peer(tmp_path):
    p = Project(tmp_path / 'gallery')
    p.update_source('Src/gallery.pa.yaml', dump_yaml({'App': {'Properties': {'OnStart': '=Clear(events)'}}, 'Screens': {'Home': {'Children': [
        {'Rows': {'Control': 'Gallery@2.15.0', 'Properties': {'Items': '=Table({ID:1,Title:"Left"},{ID:2,Title:"Right"})'}, 'Children': [
            {'Action': {'Control': 'Button@0.0.44', 'Properties': {'Text': '=ThisItem.Title', 'OnSelect': '=UpdateContext({picked:ThisItem.ID});Collect(events,{ID:ThisItem.ID,Control:Self.Name})'}}},
        ]}},
    ]}}}))
    r = Runtime(p);r.restart();r.state()
    try:
        rows = r.fx.evaluate('Rows.AllItems');left = rows[0]['Action'];right = rows[1]['Action']
        r.event(right.path, 'OnSelect')
        assert r.fx.evaluate('Rows.Selected.ID') == 2 and r.fx.evaluate('picked') == 2
        assert r.collections['events'] == [{'ID': 2, 'Control': 'Action'}]
        assert left.property('Text') == 'Left' and not r.diagnostics
    finally:r.close()


def test_component_focus_boundaries_and_bad_native_versions_remain_visible(tmp_path):
    from powerapps_sim.fixtures import canvas_buttons_project
    r = Runtime(canvas_buttons_project(tmp_path / 'component'));r.restart();r.state()
    try:
        with pytest.raises(FxError, match='Unknown property Left.Increase'):
            r.fx.evaluate('SetFocus(Left.Increase)', Context(r, behavior=True))
        child = r.refs['Home/Left/Increase']
        with pytest.raises(FxError, match='inside Component'):
            r.fx.evaluate('SetFocus(Increase)', child.context(behavior=True))
        g = r.refs['Home/FocusTarget'];g.control = deepcopy(g.control);g.control.kind = 'Button@9.9.9'
        r.analyze();r.invalidate()
        assert r.render(g)['errors']
        with pytest.raises(FxError, match='SetFocus does not support'):
            r.fx.evaluate('SetFocus(FocusTarget)', Context(r, behavior=True))
        assert not r.render(r.refs['Home/Right/Increase'])['errors']
    finally:r.close()
