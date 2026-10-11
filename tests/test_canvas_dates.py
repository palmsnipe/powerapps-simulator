from copy import deepcopy
from datetime import date
import json

import pytest

from powerapps_sim.canvas_dates import catalog, token
from powerapps_sim.fixtures import canvas_dates_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.source import Project, dump_yaml
from powerapps_sim.syntax import FxError
from powerapps_sim.fx import Context


def make(tmp_path, version='0.0.42', properties=None, number='float', language='en-US'):
    p = Project(tmp_path / 'dates')
    p.update_source('Src/dates.pa.yaml', dump_yaml({
        'App': {'Properties': {'OnStart': '=Set(seed,Date(2026,1,15));Clear(changes)'}},
        'Screens': {'Home': {'Children': [
            {'Picker': {'Control': 'DatePicker@' + version, 'Properties': {
                'SelectedDate': '=seed', 'OnChange': '=Collect(changes,{Day:Self.SelectedDate})', **(properties or {})}}},
            {'Peer': {'Control': 'DatePicker@' + version, 'Properties': {'SelectedDate': '=seed'}}},
            {'Modern': {'Control': 'ModernDatePicker@1.0.0', 'Properties': {'DefaultDate': '=Date(2026,7,15)'}}}]}}}))
    p.config['environment'].update(number_mode=number, language=language, clock='2026-01-01T12:00:00+00:00')
    p.save_config()
    r = Runtime(p);r.restart();r.state()
    return r


def send(r, day, **payload):
    g = r.refs['Home/Picker']
    r.event(g.path, 'OnChange', {'value': day, 'source': 'calendar', 'reset_token': token(g), **payload})


@pytest.mark.parametrize('version', ['0.0.38', '0.0.42'])
@pytest.mark.parametrize('number', ['float', 'decimal'])
@pytest.mark.parametrize('language', ['en-US', 'fr-CA'])
def test_native_resettable_binding_callbacks_and_modern_defaults_remain_distinct(tmp_path, version, number, language):
    r = make(tmp_path, version, number=number, language=language)
    try:
        assert not r.diagnostics
        g = r.refs['Home/Picker'];initial = token(g)
        assert r.fx.evaluate('Picker.SelectedDate=Date(2026,1,15)')
        send(r, '2026-02-03');send(r, '2026-02-03')
        assert len(r.collections['changes']) == 1 and g.state['dirty']
        assert r.fx.evaluate('Last(changes).Day=Picker.SelectedDate && Peer.SelectedDate=Date(2026,1,15)')
        assert r.fx.evaluate('Modern.SelectedDate=Date(2026,7,15)')
        send(r, None);assert g.property('SelectedDate') is None and len(r.collections['changes']) == 2
        r.fx.evaluate('Reset(Picker)', Context(r, behavior=True));r.state()
        assert r.fx.evaluate('Picker.SelectedDate=seed') and token(g) != initial
        assert len(r.collections['changes']) == 2 and not g.state.get('dirty')
        stale = token(g)
        r.fx.evaluate('Set(seed,Date(2026,3,4))', Context(r, behavior=True));r.state()
        send(r, '2026-04-05', reset_token=stale)
        assert r.fx.evaluate('Picker.SelectedDate=Date(2026,3,4)')
        assert token(g) != token(r.refs['Home/Peer'])
        assert not r.diagnostics
    finally:r.close()


@pytest.mark.parametrize('prop', ['DefaultDate', 'Language', 'ContentLanguage', 'OnSelect', 'TriggerOutput', 'DelayOutput', 'AcceptsFocus', 'Reset', 'PCFTeamsTheme'])
def test_unsupported_authored_properties_preserved_and_peers_unaffected(tmp_path, prop):
    r = make(tmp_path, properties={prop: '=Blank()'})
    try:
        assert any(d['kind'] == 'Unsupported' for d in r.diagnostics)
        assert prop in r.refs['Home/Picker'].control.properties
        assert r.fx.evaluate('Peer.SelectedDate=Date(2026,1,15)')
        with pytest.raises(FxError):r.refs['Home/Picker'].property(prop)
    finally:r.close()


@pytest.mark.parametrize('prop,formula', [
    ('SelectedDate', '="2026-01-15"'), ('SelectedDate', '=Time(12,0,0)'),
    ('StartDate', '=42'), ('EndDate', '=true'), ('StartOfWeek', '=StartOfWeek.Monday'),
    ('Format', '="Long"'), ('Format', '="yyyy-mm-dd"'), ('DateTimeZone', '="Europe/Paris"'),
    ('IsEditable', '="true"'), ('Required', '=1'), ('ValidationState', '="Invalid"'),
    ('BorderRadius', '=-1'), ('FontSize', '=-1'), ('TabIndex', '=0.5')])
def test_invalid_native_properties_report_without_breaking_other_controls(tmp_path, prop, formula):
    r = make(tmp_path, properties={prop: formula})
    try:
        assert r.diagnostics
        assert r.fx.evaluate('Peer.SelectedDate=seed && Modern.SelectedDate=Date(2026,7,15)')
    finally:r.close()


@pytest.mark.parametrize('enum_mode', ['legacy', 'strong'])
@pytest.mark.parametrize('fmt,expected', [('Short', '1/15/2026'), ('LongAbbreviated', 'Jan 15, 2026'), ('YearMonth', 'January 2026')])
def test_native_enum_names_backing_values_and_calendar_headings(tmp_path, enum_mode, fmt, expected):
    r = make(tmp_path, properties={'Format': '=DatePickerCanvas.Format.' + fmt, 'StartOfWeek': '=DatePickerCanvas.StartOfWeek.Monday'})
    try:
        r.environment['enum_mode'] = enum_mode;r.analyze();r.invalidate()
        n = r.state()['tree']['children'][0]
        assert not r.diagnostics
        assert n['calendar']['formatted'] == expected
        assert n['calendar']['weekdays'][0] == 'Mon'
        assert r.fx.evaluate('DatePickerCanvas.Format.LongAbbreviated') == 'Long Abbreviated'
        assert r.fx.evaluate('DatePickerCanvas.Format.YearMonth') == 'Year Month'
    finally:r.close()


@pytest.mark.parametrize('zone,expected', [('Local', '2026-01-01'), ('UTC', '2026-01-02')])
def test_datetime_binding_uses_existing_simulated_offset_convention(tmp_path, zone, expected):
    r = make(tmp_path, properties={'SelectedDate': '=DateTimeValue("2026-01-02T02:30:00Z")', 'DateTimeZone': '="' + zone + '"'})
    try:
        r.environment['clock'] = '2026-01-01T12:00:00-05:00';r.invalidate()
        assert r.refs['Home/Picker'].property('SelectedDate').isoformat() == expected
        assert not r.diagnostics
    finally:r.close()


@pytest.mark.parametrize('prop', ['BasePaletteColor', 'Fill', 'BorderColor', 'FontColor'])
def test_canvas_color_values_are_accepted_for_native_text_backed_style_properties(tmp_path, prop):
    r = make(tmp_path, properties={prop: '=Color.Red'})
    try:
        assert not r.diagnostics
        assert str(r.refs['Home/Picker'].property(prop)) == '#ff0000'
    finally:r.close()


@pytest.mark.parametrize('payload', [{}, {'value': 'bad'}, {'value': True}, {'source': 'unknown'}, {'extra': 1}, {'reset_token': True}])
def test_malformed_date_events_have_no_callbacks_or_writes(tmp_path, payload):
    r = make(tmp_path)
    try:
        g = r.refs['Home/Picker'];before = g.property('SelectedDate')
        if payload == {}:
            with pytest.raises(ValueError):r.event(g.path, 'OnChange', {})
        else:
            with pytest.raises(ValueError):send(r, '2026-02-03', **payload)
        assert g.property('SelectedDate') == before and not r.collections['changes']
    finally:r.close()


def test_range_typed_input_month_navigation_and_stale_instance_events(tmp_path):
    r = make(tmp_path, properties={'StartDate': '=Date(2026,1,1)', 'EndDate': '=Date(2026,3,31)', 'IsEditable': '=true'})
    try:
        g = r.refs['Home/Picker']
        send(r, '2/28/2026', source='typed')
        assert r.fx.evaluate('Picker.SelectedDate=Date(2026,2,28)')
        for value in ('2026-02-30', '2026-04-01', '0000-01-01'):
            with pytest.raises(ValueError):send(r, value)
        r.event(g.path, 'OnCalendar', {'month': '2026-03', 'reset_token': token(g)})
        n = r.state()['tree']['children'][0]
        assert n['calendar']['month'] == '2026-03' and not n['calendar']['next']
        assert len(r.collections['changes']) == 1
        with pytest.raises(ValueError):r.event(g.path, 'OnCalendar', {'month': '2026-04', 'reset_token': token(g)})
        send(r, '2026-03-04', reset_token=token(r.refs['Home/Peer']))
        assert r.fx.evaluate('Picker.SelectedDate=Date(2026,2,28)')
    finally:r.close()


@pytest.mark.parametrize('mode', ['Disabled', 'View'])
def test_mode_gates_events_and_preserves_selection(tmp_path, mode):
    r = make(tmp_path, properties={'DisplayMode': '=DisplayMode.' + mode})
    try:
        send(r, '2026-02-03')
        assert r.fx.evaluate('Picker.SelectedDate=seed') and not r.collections['changes']
    finally:r.close()


@pytest.mark.parametrize('version', ['0.0.38', '0.0.42'])
def test_blank_defaults_unbounded_calendar_and_unknown_version_isolation(tmp_path, version):
    r = make(tmp_path, version, properties={'SelectedDate': '=Blank()'})
    try:
        n = r.state()['tree']['children'][0]
        assert n['value'] is None and n['calendar']['start'] == '0001-01-01' and n['calendar']['end'] == '9999-12-31'
        assert not r.diagnostics
        r.refs['Home/Picker'].control.properties.pop('SelectedDate')
        r.invalidate()
        omitted = r.state()['tree']['children'][0]
        assert omitted['value'] is None and 'calendar' in omitted and not omitted['errors']
        g = r.refs['Home/Picker'];g.control = deepcopy(g.control);g.control.kind = 'DatePicker@9.0.0'
        r.invalidate();r.state()
        assert any(d['kind'] == 'Unsupported' for d in r.diagnostics)
        assert r.fx.evaluate('Modern.SelectedDate=Date(2026,7,15)')
    finally:r.close()


@pytest.mark.parametrize('number', ['float', 'decimal'])
@pytest.mark.parametrize('language', ['en-US', 'fr-CA'])
def test_public_native_date_workflow_preserves_owner_source_data_and_runtime(tmp_path, number, language):
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision, data_revision
    p = canvas_dates_project(tmp_path / 'public');w = Workspace(tmp_path, p.root, start=False)
    try:
        # A scenario owns its initial data even after the author edits the live list.
        w.runtime.store.patch('Plans', {'ID': 1}, {'Target date': '2026-02-28'})
        before = w.ai.read_runtime(), revision(p.root), data_revision(w.runtime.store), w.ai.export_source()
        scenario = deepcopy(w.workflows.catalog()['scenarios'][0]['scenario'])
        scenario['environment'] = {'number_mode': number, 'language': language, 'enum_mode': 'strong'}
        report = w.workflows.run(scenario, expected_revision=before[1])
        assert report['status'] == 'passed' and len(report['steps']) == 24 and not report['diagnostics'], report
        assert before == (w.ai.read_runtime(), revision(p.root), data_revision(w.runtime.store), w.ai.export_source())
    finally:w.runtime.close()
