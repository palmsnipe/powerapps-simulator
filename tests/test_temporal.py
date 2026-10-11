from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from powerapps_sim.binding import BindScope, value_type
from powerapps_sim.conformance import run_case
from powerapps_sim.fixtures import temporal_project
from powerapps_sim.fx import Context
from powerapps_sim.runtime import Runtime, serial
from powerapps_sim.source import Project
from powerapps_sim.syntax import FxError
from powerapps_sim.temporal import Temporal, schema_value


@pytest.fixture
def dates(tmp_path):
    runtime = Runtime(temporal_project(tmp_path / 'dates'))
    runtime.restart()
    yield runtime
    runtime.close()


@pytest.mark.parametrize('expression, kind, expected', [
    ('Date(2026, 1, 2)', 'Date', '2026-01-02'),
    ('DateTime(2026, 1, 2, 9, 30, 0, 1)', 'DateTime', '2026-01-02T09:30:00.001000+00:00'),
    ('Time(27, 0, 0)', 'Time', '03:00:00'),
    ('TimeValue("27:00:00")', 'Time', '03:00:00'),
    ('DateValue(DateTime(2026, 1, 2, 9, 30, 0))', 'Date', '2026-01-02'),
    ('DateTimeValue(Date(2026, 1, 2))', 'DateTime', '2026-01-02T00:00:00+00:00'),
    ('If(true, Date(2026, 1, 2), DateTime(2026, 1, 3, 12, 0, 0))', 'DateTime', '2026-01-02T00:00:00+00:00'),
    ('If(true, Time(12, 0, 0), DateTime(2026, 1, 3, 12, 0, 0))', 'DateTime', '1899-12-30T12:00:00+00:00'),
])
def test_temporal_values_keep_runtime_types(runtime, expression, kind, expected):
    value = runtime.fx.evaluate(expression)
    assert isinstance(value, Temporal)
    assert value.kind == kind
    assert value_type(value).kind == kind
    assert serial(value) == expected


@pytest.mark.parametrize('expression, expected', [
    ('Date(2026, 1, 2) = DateTime(2026, 1, 2, 0, 0, 0)', True),
    ('Date(2026, 1, 2) > Time(12, 0, 0)', True),
    ('Time(12, 0, 0) > Date(2026, 1, 2)', False),
    ('Date(2026, 1, 2) = "2026-01-02"', True),
    ('DateTimeValue("2026-01-02T10:00:00+00:00") = DateTimeValue("2026-01-02T05:00:00-05:00")', True),
    ('Date(2026, 1, 2) - Date(2026, 1, 1)', 1),
    ('Date(2026, 1, 1) + Time(9, 30, 0)', '2026-01-01T09:30:00+00:00'),
    ('Text(Time(12, 3, 4))', '12:03 PM'),
    ('Date(2026, 1, 1) + 2.5 + 0.5', '2026-01-04'),
    ('DateDiff(DateValue(DateTime(2026, 1, 2, 9, 30, 0)), Date(2026, 1, 2), TimeUnit.Hours)', 0),
])
def test_temporal_comparisons_and_arithmetic(runtime, expression, expected):
    assert serial(runtime.fx.evaluate(expression)) == expected


def test_numeric_profiles_are_explicit_and_conformance_restores_environment(runtime):
    assert runtime.fx.evaluate('Value(Date(1970, 1, 1))') == 0
    assert runtime.fx.evaluate('Value(Date(1970, 1, 2))') == 86400000
    assert runtime.fx.evaluate('Value(Time(12, 0, 0))') == 43200000
    assert runtime.fx.evaluate('Text(86400000, "yyyy-mm-dd")') == '1970-01-02'
    assert runtime.fx.evaluate('Date(1970, 1, 2) = 86400000') is True
    original = runtime.environment
    result = run_case(runtime, {'id':'profile', 'expression':'Value(Date(1970, 1, 1))', 'expected':25569,
                                'environment':{'date_numeric_mode':'powerfx-days'}})
    assert result['status'] == 'passed'
    assert runtime.environment is original
    assert runtime.fx.evaluate('Value(Date(1970, 1, 1))') == 0
    runtime.environment['date_numeric_mode'] = 'powerfx-days'
    assert runtime.fx.evaluate('Value(Time(30, 0, 0))') == 1.25
    assert runtime.fx.evaluate('Value(TimeValue("30:00:00"))') == .25


def test_localized_implicit_text_and_bad_dates(runtime):
    runtime.environment['language'] = 'fr-FR'
    assert runtime.fx.evaluate('"Date: " & Date(2026, 1, 2)') == 'Date: 02/01/2026'
    assert runtime.fx.evaluate('Text(DateTime(2026, 1, 2, 13, 30, 0))') == '02/01/2026 13:30'
    with pytest.raises(FxError):
        runtime.fx.evaluate('Date(2026, 1, 2) = "broken"')


def test_temporal_union_preserves_cell_types_and_isolated_errors(runtime):
    value = runtime.fx.evaluate('Table({D: Date(2026, 1, 1)}, {D: DateTime(2026, 1, 2, 12, 0, 0)}, {D: Error({Kind: ErrorKind.Div0})})')
    assert value[0]['D'].kind == value[1]['D'].kind == 'DateTime'
    assert isinstance(value[2]['D'], FxError)
    assert runtime.fx.evaluate('First(Table({D: Date(2026, 1, 1)}, {D: 1/0})).D').kind == 'Date'
    runtime.fx.set_definitions('=Row := Type({When: DateTime}); Read(row: Row): DateTime = row.When;')
    assert runtime.fx.evaluate('Read({When: Date(2026, 1, 1)})').kind == 'DateTime'
    assert runtime.fx.evaluate('Read({When: "2026-01-01"})').isoformat() == '2026-01-01T00:00:00+00:00'


def test_typed_component_callbacks_isolation_reset_and_reactivity(dates):
    dates.state()
    assert not dates.diagnostics
    dates.event('Dates/LeftDate/Advance', 'OnSelect')
    assert dates.fx.evaluate('LeftDate.Day').kind == 'Date'
    assert serial(dates.fx.evaluate('LeftDate.Day')) == '2026-01-02'
    assert serial(dates.fx.evaluate('RightDate.Day')) == '2026-07-01'
    assert dates.globals['leftChanged'].kind == 'DateTime'
    assert 'selectedDay' not in dates.globals
    assert dates.fx.evaluate('LeftDate.Caption(Date(2026, 1, 1))') == 'Thursday, January 1, 2026'
    dates.fx.evaluate('Reset(LeftDate)', Context(dates, behavior=True))
    assert serial(dates.fx.evaluate('LeftDate.Day')) == '2026-01-01'
    assert serial(dates.fx.evaluate('RightDate.Day')) == '2026-07-01'
    dates.environment['language'] = 'fr-CA'; dates.invalidate()
    assert dates.fx.evaluate('LeftDate.Caption(Date(2026, 1, 1))') == 'jeudi 1 janvier 2026'
    assert dates.fx.evaluate('LeftDate.Caption("2026-01-01")') == 'jeudi 1 janvier 2026'
    dates.binder.errors.clear()
    dates.binder.bind(dates.fx.parse('LeftDate.Caption("2026-01-01")'), BindScope())
    assert not dates.binder.errors


def test_form_date_shapes_persistence_last_submit_and_failed_save(dates):
    form = dates.global_refs['DateForm']
    picker = dates.global_refs['DueInput']
    assert picker.property('SelectedDate').kind == 'Date'
    assert form.property('Item')['Appointment'].kind == 'DateTime'
    dates.event(picker.path, 'OnChange', '2026-02-03')
    assert form.property('Unsaved') is True
    assert form.property('Updates')['Due date'].kind == 'Date'
    dates.store.failures['Events'] = 'write'
    dates.submit_form(form)
    assert 'Simulated write failure' in form.property('Error')
    assert dates.store.rows('Events') == []
    assert serial(picker.property('SelectedDate')) == '2026-02-03'
    assert form.property('Unsaved') is True
    dates.store.failures.clear()
    dates.submit_form(form)
    assert form.property('Error') == ''
    assert form.property('Unsaved') is False
    assert form.property('LastSubmit')['Due date'].kind == 'Date'
    assert form.property('LastSubmit')['Appointment'].kind == 'DateTime'
    assert dates.store.rows('Events')[0]['Due date'] == '2026-02-03'
    assert dates.store.rows('Events')[0]['Appointment'] == '2026-01-01T09:30:00+00:00'
    root = dates.project.root
    reopened = Runtime(Project(root))
    try:
        assert reopened.fx.evaluate('First(Events).\'Due date\'').kind == 'Date'
        assert serial(reopened.fx.evaluate('First(Events).\'Due date\'')) == '2026-02-03'
    finally:
        reopened.close()


def test_empty_date_validation_then_changed_default_resets_input(dates):
    form = dates.global_refs['DateForm']; picker = dates.global_refs['DueInput']
    dates.event(picker.path, 'OnChange', '')
    assert picker.property('SelectedDate') is None
    dates.submit_form(form)
    assert form.property('Error')
    assert dates.store.rows('Events') == []
    dates.event(picker.path, 'OnChange', '2026-04-05')
    dates.globals['seedDate'] = dates.fx.evaluate('Date(2026, 6, 1)')
    picker.control.properties['DefaultDate'] = '=seedDate'; dates.invalidate()
    assert serial(picker.property('SelectedDate')) == '2026-06-01'
    assert not picker.state.get('dirty')
    with pytest.raises(ValueError, match='ISO calendar date'):
        dates.event(picker.path, 'OnChange', '2026-02-30')


def test_patch_hydrates_mapped_fields_and_rejects_nested_errors(dates):
    result = dates.fx.evaluate('Patch(Events, Defaults(Events), {Title: "Typed patch", \'Due date\': Date(2026, 3, 1), Appointment: Date(2026, 3, 1) + Time(10, 15, 0)})', Context(dates, behavior=True))
    assert result['Due date'].kind == 'Date'
    assert result['Appointment'].kind == 'DateTime'
    assert dates.fx.evaluate('CountRows(Filter(Events, \'Due date\' > Date(2026, 2, 1)))') == 1
    assert dates.store.rows('Events')[0]['Appointment'] == '2026-03-01T10:15:00+00:00'
    assert isinstance(schema_value('wrong', {'format':'date'}), FxError)
    with pytest.raises(FxError):
        dates.fx.evaluate('Patch(Events, Defaults(Events), {Title: "Bad", \'Due date\': Date(2026, 3, 1), Appointment: {When: 1/0}})', Context(dates, behavior=True))
    assert len(dates.store.rows('Events')) == 1


def test_temporal_fixture_export_keeps_powerapps_source_and_refuses_overwrite(dates):
    exported = dates.project.documents['Src/temporal.pa.yaml']
    import zipfile
    from io import BytesIO
    with zipfile.ZipFile(BytesIO(dates.project.export())) as archive:
        assert all(name.startswith('Src/') or name.startswith('assets/') for name in archive.namelist())
    assert 'DatePanel' in exported and 'DateTime' in exported
    assert 'date_numeric_mode' not in exported and 'sqlite' not in exported.lower()
    with pytest.raises(ValueError, match='existing projects'):
        temporal_project(dates.project.root)


def test_uniform_temporal_tables_do_not_promote_identical_kinds(runtime):
    for constructor, kind in [('Date(2026,1,1)', 'Date'), ('Time(12,0,0)', 'Time')]:
        rows = runtime.fx.evaluate(f'Table({{D: {constructor}}}, {{D: {constructor}}})')
        assert [row['D'].kind for row in rows] == [kind, kind]


def test_simulation_rejects_an_unknown_numeric_date_mode(post, runtime):
    before = dict(runtime.environment)
    response = post('/api/scenario', {'environment':{**before, 'date_numeric_mode':'guess'}})
    assert response.status_code == 400
    assert runtime.environment == before
