"""Pinned native month-shift oracles, scalar contracts and temporal boundaries."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from powerapps_sim.binding import BindScope, value_type
from powerapps_sim.conformance import run_case
from powerapps_sim.fx import Context
from powerapps_sim.runtime import serial
from powerapps_sim.syntax import FxError

CASES = json.loads((Path(__file__).parents[1]/'powerapps_sim/conformance_cases/month_shifts.json').read_text())['cases']


@pytest.mark.parametrize('mode', ['float', 'decimal'])
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['id'])
def test_complete_pinned_edate_eomonth_file(runtime, mode, case):
    case = deepcopy(case)
    case['environment']['number_mode'] = mode
    if mode == 'decimal' and isinstance(case.get('expected'), int):
        case['expected'] = {'$decimal': str(case['expected'])}
    result = run_case(runtime, case)
    assert result['status'] == 'passed', result
    if case['expression'].startswith(('EDate(', 'EOMonth(')):
        assert result['inferred_type'] == 'Date'


@pytest.mark.parametrize('name', ['EDate', 'EOMonth'])
@pytest.mark.parametrize('arguments', ['true,1', '{D:Date(2024,1,31)},1', '[Date(2024,1,31)],1',
                                    'Date(2024,1,31),[1]', 'Date(2024,1,31),{N:1}'])
def test_scalar_contracts_reject_tables_records_and_boolean_dates(runtime, name, arguments):
    formula = f'{name}({arguments})'
    runtime.binder.errors.clear()
    runtime.binder.bind(runtime.fx.parse(formula), BindScope())
    assert runtime.binder.errors and all(e.kind == 'Type' for _, e in runtime.binder.errors)
    with pytest.raises(FxError) as error:
        runtime.fx.evaluate(formula)
    assert error.value.kind == 'Type' and error.value.end > error.value.start


@pytest.mark.parametrize('name', ['EDate', 'EOMonth'])
def test_errors_are_aggregated_catchable_and_lazy(runtime, name):
    assert runtime.fx.evaluate(f'If(false,{name}(Date(9999,12,31),1),Date(2024,1,1))').isoformat() == '2024-01-01'
    assert runtime.fx.evaluate(f'IfError(Text({name}(Date(9999,12,31),1)),Text(FirstError.Kind))') == '25'
    with pytest.raises(FxError) as error:
        runtime.fx.evaluate(f'{name}(1/0,Error({{Kind:ErrorKind.Network}}))')
    assert [r['Kind'] for r in error.value.records()] == [13,23]
    with pytest.raises(FxError) as error:
        runtime.fx.evaluate(f'{name}("bad date","bad months")')
    assert len(error.value.records()) == 2
    assert serial(runtime.fx.evaluate(f'{name}(Blank(),"")')) == ('1899-12-30' if name == 'EDate' else '1899-12-31')


@pytest.mark.parametrize('name', ['EDate', 'EOMonth'])
def test_canvas_milliseconds_profile_is_not_silently_changed(runtime, name):
    assert serial(runtime.fx.evaluate(f'{name}(86400000,1)')) == ('1970-02-02' if name == 'EDate' else '1970-02-28')
    assert runtime.fx.evaluate(f'Value({name}(DateTime(1970,1,2,12,30,0),0))') == (86400000 if name == 'EDate' else 2592000000)
    assert runtime.environment['date_numeric_mode'] == 'canvas-milliseconds'


@pytest.mark.parametrize('mode', ['float', 'decimal'])
def test_typed_udfs_nested_scopes_and_collections_keep_date(runtime, mode):
    runtime.environment['number_mode'] = mode
    runtime.fx.set_definitions('=Shift(d:DateTime,n:Number):Date=EDate(d,n); End(d:Date,n:Number):Date=EOMonth(d,n);')
    result = runtime.fx.evaluate('With({Months:1.9},ForAll(Table({D:Date(2024,1,31)},{D:Date(2023,1,31)}) As row, {Due:Shift(row.D,Months),Cutoff:End(row.D,Months)}))')
    assert [serial(row) for row in result] == [{'Due':'2024-02-29','Cutoff':'2024-02-29'}, {'Due':'2023-02-28','Cutoff':'2023-02-28'}]
    assert all(row['Due'].kind == row['Cutoff'].kind == 'Date' for row in result)
    formula = 'ClearCollect(dates,ForAll(Sequence(3),{Due:EDate(Date(2024,1,31),Value)}))'
    runtime.binder.bind(runtime.fx.parse(formula), BindScope(behavior=True))
    runtime.fx.evaluate(formula, Context(runtime, behavior=True))
    assert all(row['Due'].kind == 'Date' for row in runtime.collections['dates'])
    assert value_type(runtime.collections['dates']).row.fields['Due'].kind == 'Date'


def test_month_offsets_localize_and_preserve_dateadd_time(runtime):
    runtime.environment['language'] = 'fr-CA'
    assert serial(runtime.fx.evaluate('EDate("31/01/2024","1,9")')) == '2024-02-29'
    assert serial(runtime.fx.evaluate('EOMonth("15/05/2023","-1,9")')) == '2023-04-30'
    assert serial(runtime.fx.evaluate('DateAdd(DateTime(2024,1,31,9,30,0),1,TimeUnit.Months)')) == '2024-02-29T09:30:00+00:00'
