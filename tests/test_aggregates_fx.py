"""Aggregate Blank contracts, coercions, errors and temporal result types."""
import json
from decimal import Decimal
from pathlib import Path

import pytest

from powerapps_sim.binding import BindScope
from powerapps_sim.conformance import run_case
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError
from powerapps_sim.temporal import Temporal


@pytest.mark.parametrize('mode', ['float', 'decimal'])
@pytest.mark.parametrize('formula,expected', [
    ('Average(5,Blank(),"")', 5), ('Min(5,Blank())', 5),
    ('Max(-5,Blank())', -5), ('Sum(Blank())', None),
    ('Min(Blank())', None), ('Max(Blank())', None),
    ('Sum(FirstN([1],0),Value)', None), ('Min(FirstN([1],0),Value)', None),
    ('Average(If(false,[1]),Value)', None),
    ('Sum(If(false,[1]),Value)', None),
    ('Average(Table({N:Blank()},{N:2},{N:4}),N)', 3),
    ('Average(Table({N:""},{N:"2"},{N:"4"}),N)', 3),
    ('Min(Table({N:Blank()},{N:"2"},{N:"4"}),N)', 2),
    ('Sum(Table(Blank(),{N:3}),Coalesce(N,10))', 13),
    ('Sum(Table({N:1/0},{N:3}),IfError(N,10))', 13),
    ('Average(Table({N:2,Unused:1/0},{N:4,Unused:1/0}),N)', 3),
    ('Average([2,4] As outer,Sum([1,2] As inner,outer.Value*inner.Value))', 9),
])
def test_blank_scope_and_conversion_contracts(runtime, mode, formula, expected):
    runtime.environment['number_mode'] = mode; runtime.invalidate()
    runtime.binder.errors.clear()
    runtime.binder.bind(runtime.fx.parse(formula), BindScope())
    assert not runtime.binder.errors
    value = runtime.fx.evaluate(formula)
    assert value == expected
    if value is not None:
        assert isinstance(value, Decimal if mode == 'decimal' else float)


@pytest.mark.parametrize('name', ['Sum', 'Average', 'Min', 'Max'])
def test_scalar_errors_aggregate_and_table_errors_stop_at_first(runtime, name):
    assert runtime.fx.evaluate(f'IfError({name}(1/0,"bad"),CountRows(AllErrors))') == 2
    assert runtime.fx.evaluate(f'IfError({name}("bad","worse"),CountRows(AllErrors))') == 2
    assert runtime.fx.evaluate(f'IfError({name}([0,0],1/Value),CountRows(AllErrors))') == 1
    assert runtime.fx.evaluate(f'IfError({name}([1,2],If(Value=1,1/0,Value("bad"))),FirstError.Kind)') == 13
    # The row error is contained by its projection, not rejected beforehand.
    assert runtime.fx.evaluate(f'{name}(Table({{N:1}},Error({{Kind:ErrorKind.Div0}})),IfError(N,3))') == {'Sum':4,'Average':2,'Min':1,'Max':3}[name]


@pytest.mark.parametrize('formula', ['Average(Blank())', 'Average("")', 'Average(FirstN([1],0),Value)', 'Average([Blank(),Blank()],Value)'])
def test_empty_average_is_located_catchable_div0(runtime, formula):
    with pytest.raises(FxError) as error:
        runtime.fx.evaluate(formula, Context(runtime,error_source='Aggregate.Rule'))
    assert error.value.kind == 'Div0' and error.value.source == 'Aggregate.Rule'
    assert error.value.end > error.value.start
    assert runtime.fx.evaluate(f'IfError({formula},FirstError.Kind)') == 13
    assert not runtime.app_errors.pending


@pytest.mark.parametrize('name', ['Sum', 'Average', 'Min', 'Max'])
@pytest.mark.parametrize('suffix', ['([1])', '([1],Value,2)', '([1],ThisRecord)', '({N:1})'])
def test_invalid_overloads_report_binding_errors(runtime, name, suffix):
    runtime.binder.errors.clear(); runtime.binder.bind(runtime.fx.parse(name+suffix),BindScope())
    assert runtime.binder.errors
    assert all(error.end > error.start for _,error in runtime.binder.errors)


@pytest.mark.parametrize('formula,kind,expected', [
    ('Min(Date(2022,3,8),DateTime(2021,2,3,4,5,6))','Date','2021-02-03'),
    ('Max(DateTime(2022,3,8,13,50,0),Date(2022,3,9))','DateTime','2022-03-09T00:00:00+00:00'),
    ('Min(Table({D:Date(2022,3,8)},{D:Date(2021,2,3)}),D)','Date','2021-02-03'),
    ('Max([1,2],DateAdd(Date(2022,3,8),Value))','Date','2022-03-10'),
    ('Min([1,2],DateAdd(Time(12,0,0),Value,TimeUnit.Hours))','Time','13:00:00'),
    ('Min(Time(12,0,0),DateTimeValue("1888-10-20T12:34:56.789"))','Time','12:34:56.789000'),
    ('Min(Date(2023,3,15),45000)','Date','2023-03-15'),
])
def test_temporal_minmax_preserves_bound_type(runtime, formula, kind, expected):
    runtime.environment['date_numeric_mode']='powerfx-days'; runtime.invalidate()
    runtime.binder.errors.clear(); typ=runtime.binder.bind(runtime.fx.parse(formula),BindScope())
    assert not runtime.binder.errors and typ.kind == kind
    value=runtime.fx.evaluate(formula)
    assert isinstance(value,Temporal) and value.kind == kind and value.isoformat() == expected


def test_first_numeric_argument_selects_numeric_kind(runtime):
    runtime.environment['number_mode']='decimal'; runtime.invalidate()
    for name in ('Sum','Average','Min','Max'):
        assert isinstance(runtime.fx.evaluate(f'{name}(Float(2),Decimal(1))'),float)
        assert isinstance(runtime.fx.evaluate(f'{name}(Decimal(2),Float(1))'),Decimal)


@pytest.mark.parametrize('name,expected', [('Min',2),('Max',3)])
def test_date_aggregates_retain_time_parts_from_dateadd(runtime,name,expected):
    formula=f'{name}(DateAdd(Date(2024,1,1),2,TimeUnit.Hours),DateAdd(Date(2024,1,1),3,TimeUnit.Hours))'
    value=runtime.fx.evaluate(formula)
    assert value.kind=='Date' and value.value.hour==expected
    assert runtime.fx.evaluate(f'Hour({formula})')==expected


def test_typed_functions_reactive_collections_and_localized_coercions(runtime):
    runtime.environment.update(number_mode='decimal',language='fr-CA'); runtime.invalidate()
    runtime.fx.set_definitions('Rows:=Type([{N:Number}]); Mean(rows:Rows):Number=Average(rows,N); Earliest(a:Date,b:Date):Date=Min(a,b);')
    assert runtime.fx.evaluate('Mean([{N:2},{N:4}])') == Decimal(3)
    assert runtime.fx.evaluate('Earliest(Date(2022,3,8),Date(2021,2,3))').kind == 'Date'
    assert runtime.fx.evaluate('Average("1,5","3,5")') == Decimal('2.5')
    ctx=Context(runtime,behavior=True)
    runtime.fx.evaluate('ClearCollect(samples,{N:2},{N:4})',ctx)
    runtime.fx.set_definitions('Summary={Mean:Average(samples,N),Total:Sum(samples,N),Minimum:Min(samples,N)};')
    assert runtime.fx.evaluate('Summary.Mean') == 3
    runtime.fx.evaluate('Collect(samples,{N:6})',ctx)
    assert runtime.fx.evaluate('Summary.Mean') == 4
    runtime.fx.evaluate('Clear(samples)',ctx)
    assert runtime.fx.evaluate('IsError(Summary)') is False
    assert runtime.fx.evaluate('IsError(Summary.Mean)') is True
    assert runtime.fx.evaluate('Summary.Total') is None
    assert runtime.fx.evaluate('Summary.Minimum') is None


@pytest.mark.parametrize('name',['Sum','Average'])
def test_accumulator_overflow_does_not_hide_later_table_error(runtime,name):
    assert runtime.fx.evaluate(f'IfError({name}([1,2,3],If(Value=3,1/0,1e308)),FirstError.Kind)') == 13
    assert runtime.fx.evaluate(f'IfError({name}(1e308,1e308),FirstError.Kind)') == 24


@pytest.mark.parametrize('name',['VarP','StdevP'])
def test_population_overflow_does_not_hide_later_projection_error(runtime,name):
    projection='If(Value=3,1/0,If(Value=1,1e308,-1e308))'
    assert runtime.fx.evaluate(f'IfError({name}([1,2,3],{projection}),FirstError.Kind)') == 13
    assert runtime.fx.evaluate(f'IfError({name}(1e308,-1e308),FirstError.Kind)') == 24


CASES=json.loads((Path(__file__).parents[1]/'powerapps_sim/conformance_cases/aggregates.json').read_text())['cases']
@pytest.mark.parametrize('case',CASES,ids=lambda case:case['id'])
def test_independent_pinned_aggregate_cases(runtime,case):
    result=run_case(runtime,case)
    assert result['status']==('known_gap' if case.get('known_gap') else 'passed'),result
