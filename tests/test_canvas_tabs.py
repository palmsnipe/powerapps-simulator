"""Archived TabList selection contracts across component, gallery and form scopes."""
from copy import deepcopy
import io
import json
from pathlib import Path
import zipfile

import pytest

from powerapps_sim.canvas_tabs import catalog, token
from powerapps_sim.fx import Context
from powerapps_sim.runtime import Runtime
from powerapps_sim.source import Project, dump_yaml
from powerapps_sim.syntax import FxError


def make(tmp_path, props=None, environment=None):
    props = {'Items': '=Table({ID:1,Label:"Draft",Code:"D"},{ID:2,Label:"Review",Code:"R"},{ID:3,Label:"Approved",Code:"A"})',
        'DefaultSelectedItems': '=Table({ID:2})',
        'Size': '=TabList.Size.Medium', 'Alignment': '=TabList.Alignment.Horizontal',
        'OnSelect': '=Collect(events,{Kind:"select",Code:Self.Selected.Code})',
        'OnChange': '=Collect(events,{Kind:"change",Code:First(Self.SelectedItems).Code})', **(props or {})}
    p = Project(tmp_path / 'tabs')
    p.update_source('Src/tabs.pa.yaml', dump_yaml({
        'App': {'Properties': {'OnStart': '=Clear(events)'}},
        'Screens': {'Home': {'Children': [
            {'Tabs': {'Control': 'TabList@2.2.29', 'Properties': props}},
            {'Peer': {'Control': 'TabList@2.2.29', 'Properties': deepcopy(props)}},
        ]}},
    }))
    p.config['environment'].update(environment or {});p.save_config()
    r = Runtime(p);r.restart();r.state()
    return r


def choose(r, index, ref=None, stamp=None):
    ref = ref or r.refs['Home/Tabs']
    r.event(ref.path, 'OnChange', {'indices': [index], 'option_token': stamp or token(ref)})
    r.state()


@pytest.mark.parametrize('number', ['float', 'decimal'])
@pytest.mark.parametrize('enums', ['legacy', 'strong'])
def test_archived_contract_defaults_outputs_and_commit_before_callbacks(tmp_path, number, enums):
    r = make(tmp_path, environment={'number_mode': number, 'enum_mode': enums})
    try:
        g = r.refs['Home/Tabs'];peer = r.refs['Home/Peer']
        assert not r.diagnostics, r.diagnostics
        assert g.property('Selected')['Code'] == 'R'
        assert g.property('SelectedItems') == [g.property('Selected')]
        assert r.binder.property_type(g.control, 'Selected').fields['Code'].kind == 'Text'
        for prop in catalog()['2.2.29']['types']:
            g.property(prop)
        assert token(g) != token(peer)
        choose(r, 2)
        assert r.collections['events'] == [{'Kind': 'select', 'Code': 'A'}, {'Kind': 'change', 'Code': 'A'}]
        choose(r, 2)
        assert len(r.collections['events']) == 3 and r.collections['events'][-1]['Kind'] == 'select'
        assert peer.property('Selected')['Code'] == 'R'
        assert g.state['dirty']
        r.fx.evaluate('Select(Tabs)', Context(r, behavior=True));r.drain_events()
        assert r.collections['events'][-1] == {'Kind': 'select', 'Code': 'A'}
    finally:
        r.close()


def test_omitted_items_are_native_template_defaults(tmp_path):
    r = make(tmp_path)
    try:
        g = r.refs['Home/Tabs'];g.control = deepcopy(g.control)
        for name in ('Items', 'DefaultSelectedItems', 'Size', 'Alignment', 'OnChange', 'OnSelect'):
            g.control.properties.pop(name)
        r.invalidate()
        assert g.property('Selected') == {'Value': 'Item 1'}
        assert g.property('Size') == 'Large' and g.property('Alignment') == 'Horizontal'
        assert (g.property('Width'), g.property('Height')) == (280, 55)
        assert [o['label'] for o in r.render(g)['options']] == ['Item 1', 'Item 2', 'Item 3']
    finally:
        r.close()


@pytest.mark.parametrize('raw,expected', [('=Table()', 'D'), ('=Blank()', 'D'), ('=Table({ID:3})', 'A'), ('=Table({ID:99})', None), ('=Table({ID:99},{ID:2})', 'R')])
def test_table_defaults_and_unmatched_selection_are_explicit(tmp_path, raw, expected):
    r = make(tmp_path, {'DefaultSelectedItems': raw})
    try:
        chosen = r.refs['Home/Tabs'].property('Selected')
        assert (chosen['Code'] if chosen else None) == expected
        assert not r.diagnostics, r.diagnostics
    finally:
        r.close()


def test_resets_changed_defaults_refresh_and_cross_instance_events(tmp_path):
    r = make(tmp_path)
    try:
        g = r.refs['Home/Tabs'];peer = r.refs['Home/Peer'];old = token(g)
        choose(r, 0, peer, old)
        assert not r.collections['events'] and peer.property('Selected')['Code'] == 'R'
        choose(r, 2)
        r.fx.evaluate('Reset(Tabs)', Context(r, behavior=True));r.state()
        assert token(g) != old and g.property('Selected')['Code'] == 'R'
        choose(r, 0, stamp=old)
        assert len(r.collections['events']) == 2
        old = token(g);g.control = deepcopy(g.control)
        g.control.properties['DefaultSelectedItems'] = '=Table({ID:1})';r.invalidate()
        choose(r, 2, stamp=old)  # Bindings settle before an event, without a preview first.
        assert g.property('Selected')['Code'] == 'D' and len(r.collections['events']) == 2
        choose(r, 2);old = token(g)
        g.control.properties['Items'] = '=Table({ID:3,Label:"Updated",Code:"new"},{ID:1,Label:"First",Code:"D"})';r.invalidate()
        node = r.render(g)
        assert node['selection'] == [0] and g.property('Selected')['Code'] == 'new'
        choose(r, 1, stamp=old)
        assert g.property('Selected')['Code'] == 'new'
        g.control.properties['Items'] = '=Table({ID:1,Label:"First",Code:"D"})';r.invalidate()
        assert g.property('Selected')['Code'] == 'D'
    finally:
        r.close()


def test_duplicate_records_keep_occurrence_selection(tmp_path):
    r = make(tmp_path, {'Items': '=Table({ID:1,Label:"Same",Code:"D"},{ID:1,Label:"Same",Code:"D"})', 'DefaultSelectedItems': '=Table()'})
    try:
        g = r.refs['Home/Tabs'];choose(r, 1)
        assert r.render(g)['selection'] == [1]
        assert len(r.collections['events']) == 2
        choose(r, 1);assert len(r.collections['events']) == 3
        choose(r, 0);assert len(r.collections['events']) == 5 and not g.state['dirty']
    finally:
        r.close()


@pytest.mark.parametrize('property,raw', [
    ('Default', '=Blank()'), ('Selected', '=Blank()'), ('SelectedItems', '=Table()'),
    ('ItemDisplayText', '=ThisItem.Label'), ('TabSize', '=TabSize.Medium'),
    ('Appearance', '=TabListAppearance.Subtle'), ('SelectMultiple', '=false'),
    ('Reset', '=false'), ('PCFTeamsTheme', '=Blank()'),
])
def test_newer_aliases_and_output_authoring_are_diagnosed_without_source_repair(tmp_path, property, raw):
    r = make(tmp_path, {property: raw})
    try:
        g = r.refs['Home/Tabs'];assert g.control.properties[property] == raw
        assert any(d['kind'] == 'Unsupported' for d in r.diagnostics)
        with pytest.raises(FxError):g.property(property)
        # Remove the bad field only from the peer fixture, leaving authored source unchanged.
        r.refs['Home/Peer'].control = deepcopy(r.refs['Home/Peer'].control)
        r.refs['Home/Peer'].control.properties.pop(property);r.invalidate()
        assert not r.render(r.refs['Home/Peer'])['errors']
    finally:
        r.close()


@pytest.mark.parametrize('property,raw', [('Size', '="Huge"'), ('Alignment', '="Center"'), ('FontSize', '=-1'), ('TabIndex', '=0.5'), ('Items', '={ID:1}'), ('DefaultSelectedItems', '={ID:1}'), ('FontItalic', '="yes"')])
def test_type_and_enum_failures_keep_source_locations(tmp_path, property, raw):
    r = make(tmp_path, {property: raw})
    try:
        assert r.diagnostics and any(d.get('source') == 'Src/tabs.pa.yaml' for d in r.diagnostics)
    finally:
        r.close()


@pytest.mark.parametrize('indices', [[], [0, 1], [-1], [3], [True], ['1'], None])
def test_invalid_index_payloads_do_not_commit(tmp_path, indices):
    r = make(tmp_path)
    try:
        with pytest.raises(ValueError):r.event('Home/Tabs', 'OnChange', {'indices': indices, 'option_token': token(r.refs['Home/Tabs'])})
        assert not r.collections['events'] and r.refs['Home/Tabs'].property('Selected')['Code'] == 'R'
    finally:
        r.close()


@pytest.mark.parametrize('mode', ['View', 'Disabled'])
def test_mode_gates_and_unsupported_version_keep_healthy_controls(tmp_path, mode):
    r = make(tmp_path, {'DisplayMode': '=DisplayMode.' + mode})
    try:
        choose(r, 2)
        assert not r.collections['events']
        g = r.refs['Home/Tabs'];g.control = deepcopy(g.control);g.control.kind = 'TabList@9.9.9'
        r.analyze();r.invalidate()
        assert r.render(g)['errors'] and r.refs['Home/Peer'].property('Selected')['Code'] == 'R'
    finally:
        r.close()


def test_official_windows_path_archive_retains_native_tablist_source(tmp_path):
    archive = Path(__file__).parents[1] / 'test-results/classic-rating-MDA_InputControls_Solution_1_0_0_4.zip'
    if not archive.exists():pytest.skip('Optional pinned first-party archive unavailable')
    import hashlib
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == catalog()['2.2.29']['artifact_sha256']
    with zipfile.ZipFile(archive) as outer:
        for name in outer.namelist():
            if not name.endswith('.msapp'):continue
            payload = outer.read(name)
            with zipfile.ZipFile(io.BytesIO(payload)) as inner:
                if not any(b'TabList@2.2.29' in inner.read(n) for n in inner.namelist() if n.replace('\\', '/').startswith('Src/') and n.endswith('.yaml')):continue
            p = Project.import_archive(payload, tmp_path / 'official');documents = dict(p.documents)
            r = Runtime(p)
            try:
                ref = next(ref for ref in r.refs.values() if ref.family == 'TabList')
                node = r.render(ref)
                assert not node['errors'] and node['selection'] == [0]
                assert [o['label'] for o in node['options']] == ['Item 1', 'Item 2', 'Item 3']
                assert p.documents == documents and 'TabList@2.2.29' in ''.join(documents.values())
            finally:r.close()
            return
    pytest.fail('Pinned archive lacks TabList source')


@pytest.mark.parametrize('number', ['float', 'decimal'])
@pytest.mark.parametrize('language', ['en-US', 'fr-CA'])
@pytest.mark.parametrize('enums', ['legacy', 'strong'])
def test_bilingual_component_form_workflow_preserves_owner(tmp_path, number, language, enums):
    from powerapps_sim.fixtures import canvas_tabs_project
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision, data_revision
    p = canvas_tabs_project(tmp_path / 'owner');w = Workspace(tmp_path, p.root, start=False)
    try:
        before = revision(p.root), data_revision(w.runtime.store), w.ai.read_runtime(), w.ai.export_source()
        scenario = deepcopy(w.workflows.catalog()['scenarios'][0]['scenario'])
        scenario['environment'] = {'number_mode': number, 'language': language, 'enum_mode': enums}
        result = w.workflows.run(scenario, expected_revision=before[0])
        assert result['status'] == 'passed' and len(result['steps']) == 27 and not result['diagnostics'], result
        assert before == (revision(p.root), data_revision(w.runtime.store), w.ai.read_runtime(), w.ai.export_source())
    finally:w.runtime.close()


def test_gallery_row_selection_callback_reset_boundary_and_peer_isolation(tmp_path):
    p = Project(tmp_path / 'gallery')
    p.update_source('Src/gallery.pa.yaml', dump_yaml({
        'App': {'Properties': {'OnStart': '=Clear(events)'}},
        'Screens': {'Home': {'Children': [
            {'Rows': {'Control': 'Gallery@2.15.0', 'Properties': {'Items': '=Table({ID:1},{ID:2})'}, 'Children': [
                {'Tabs': {'Control': 'TabList@2.2.29', 'Properties': {'OnChange': '=Collect(events,{Row:ThisItem.ID,Label:Self.Selected.Value})'}}},
                {'ResetRow': {'Control': 'ModernButton@1.0.0', 'Properties': {'OnSelect': '=Reset(Tabs)'}}},
            ]}},
            {'ResetChosen': {'Control': 'ModernButton@1.0.0', 'Properties': {'OnSelect': '=ForAll(Filter(Rows.AllItems,ID=Rows.Selected.ID) As row,Select(row.ResetRow))'}}},
        ]}},
    }))
    r = Runtime(p);r.restart();r.state()
    try:
        rows = r.fx.evaluate('Rows.AllItems');left = rows[0]['Tabs'];right = rows[1]['Tabs']
        old = token(left);choose(r, 2, right, old)
        assert not r.collections['events']
        choose(r, 1, left);choose(r, 2, right)
        assert r.collections['events'] == [{'Row': 1, 'Label': 'Item 2'}, {'Row': 2, 'Label': 'Item 3'}]
        r.event('Home/Rows', 'OnSelect', selection=[0]);r.event('Home/ResetChosen', 'OnSelect');r.state()
        assert left.property('Selected')['Value'] == 'Item 1' and right.property('Selected')['Value'] == 'Item 3'
        assert token(left) != old and not r.diagnostics
    finally:r.close()


def test_error_in_one_display_row_retains_healthy_tab_output(tmp_path):
    r = make(tmp_path, {'Items': '=Table({ID:1,Value:Error({Kind:ErrorKind.Validation,Message:"bad label"}),Code:"D"},{ID:2,Value:"Healthy",Code:"R"})'})
    try:
        g = r.refs['Home/Tabs'];node = r.render(g)
        assert node['options'][0]['disabled'] and node['options'][1]['label'] == 'Healthy'
        choose(r, 1)
        assert g.property('Selected')['Code'] == 'R'
        assert r.collections['events'][-1]['Code'] == 'R'
        assert g.control.properties['Items'].startswith('=Table(')
    finally:r.close()
