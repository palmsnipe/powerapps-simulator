"""Population statistics, scoped errors and Float contracts in both host profiles."""
import json
from pathlib import Path

import pytest

from powerapps_sim.binding import BindScope, NUMBER
from powerapps_sim.conformance import run_case
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError


@pytest.mark.parametrize('mode', ['float', 'decimal'])
@pytest.mark.parametrize('formula,expected', [
    ('VarP(2,4,4,4,5,5,7,9)', 4),
    ('StdevP(2,4,4,4,5,5,7,9)', 2),
    ('VarP([2,4,4,4,5,5,7,9],Value)', 4),
    ('StdevP(Blank(),5,Blank())', 0),
    ('VarP(false,true)', .25),
    ('StdevP("1","3")', 1),
    ('VarP(["1","2","3"],Value)', 2/3),
    ('VarP(Table({N:Blank()},{N:4},{N:6}),N)', 1),
    ('StdevP(Table(Blank(),{N:4},{N:6}),N)', 1),
    ('VarP(1000000000001,1000000000002,1000000000003)', 2/3),
    ('StdevP([2,4] As amount,amount.Value)', 1),
    ('VarP(Table({N:1},{N:3}) As outer,Sum([1,2] As inner,outer.N*inner.Value))', 9),
    ('VarP(Table({N:2,Unrelated:1/0},{N:4,Unrelated:1/0}),N)', 1),
    ('VarP(Table({N:1},Error({Kind:ErrorKind.Div0})),IfError(N,3))', 1),
    ('StdevP(Table({N:1},Error({Kind:ErrorKind.Div0})),IfError(N,3))', 1),
])
def test_scalar_table_scopes_and_population_results(runtime, mode, formula, expected):
    runtime.environment['number_mode'] = mode; runtime.invalidate()
    value = runtime.fx.evaluate(formula)
    assert isinstance(value, float) and value == pytest.approx(expected)
    runtime.binder.errors.clear()
    assert runtime.binder.bind(runtime.fx.parse(formula), BindScope()) == NUMBER
    assert not runtime.binder.errors


@pytest.mark.parametrize('formula,kind', [
    ('VarP(Blank())', 'Div0'), ('StdevP(FirstN([1],0),Value)', 'Div0'),
    ('StdevP([Blank(),Blank()],Value)', 'Div0'),
    ('VarP("bad")', 'InvalidArgument'), ('StdevP("NaN")', 'InvalidArgument'),
    ('VarP(1/0,2)', 'Div0'), ('VarP(-1e308,1e308)', 'Numeric'),
    ('StdevP(1e308,-1e308)', 'Numeric'),
])
def test_errors_are_catchable_and_located(runtime, formula, kind):
    with pytest.raises(FxError) as error:
        runtime.fx.evaluate(formula, Context(runtime, error_source='Statistics.Rule'))
    assert error.value.kind == kind and error.value.end > error.value.start
    assert error.value.source == 'Statistics.Rule'
    assert runtime.fx.evaluate(f'IfError({formula},FirstError.Kind)') in (13,24,25)
    assert not runtime.app_errors.pending


@pytest.mark.parametrize('formula', [
    'VarP()', 'StdevP([1,2])', 'VarP([1,2],Value,2)',
    'VarP({N:1})', 'StdevP([{N:1}],ThisRecord)', 'VarP([1],missing)',
])
def test_invalid_contracts_report_binding_errors(runtime, formula):
    runtime.binder.errors.clear()
    runtime.binder.bind(runtime.fx.parse(formula), BindScope())
    assert runtime.binder.errors
    assert all(error.end > error.start for _, error in runtime.binder.errors)


def test_scalar_aggregation_and_table_first_error_policy(runtime):
    assert runtime.fx.evaluate('IfError(VarP(1/0,"bad"),CountRows(AllErrors))') == 2
    assert runtime.fx.evaluate('IfError(StdevP([0,0],1/Value),CountRows(AllErrors))') == 1
    assert runtime.fx.evaluate('If(false,VarP(Blank()),42)') == 42
    assert runtime.fx.evaluate('IfError(VarP(Blank()),7)') == 7


@pytest.mark.parametrize('name', ['VarP','StdevP'])
@pytest.mark.parametrize('mode', ['float','decimal'])
def test_typed_blank_table_stays_blank_instead_of_becoming_empty(runtime, name, mode):
    runtime.environment['number_mode']=mode;runtime.invalidate()
    assert runtime.fx.evaluate(f'{name}(If(false,[1]),Value)') is None
    assert runtime.fx.evaluate(f'IsError({name}(If(false,[1]),Value))') is False
    assert runtime.fx.evaluate(f'IfError({name}(FirstN([1],0),Value),FirstError.Kind)') == 13


def test_float_conversion_localization_dynamic_and_typed_functions(runtime):
    runtime.environment.update(number_mode='decimal', language='fr-CA'); runtime.invalidate()
    assert runtime.fx.evaluate('VarP("1,5","3,5")') == 1
    assert runtime.fx.evaluate('StdevP(ParseJSON("2"),ParseJSON("4"))') == 1
    runtime.fx.set_definitions('Samples:=Type([{Amount:Number}]); Spread(rows:Samples):Float=StdevP(rows,Amount);')
    assert runtime.fx.evaluate('Spread([{Amount:2},{Amount:4}])') == 1
    assert isinstance(runtime.fx.evaluate('Spread([{Amount:2},{Amount:4}])'), float)


def test_collection_writes_recalculate_named_statistics(runtime):
    ctx = Context(runtime, behavior=True)
    runtime.fx.evaluate('ClearCollect(samples,{N:2},{N:4})', ctx)
    runtime.fx.set_definitions('Spread=StdevP(samples,N);')
    assert runtime.fx.evaluate('Spread') == 1
    runtime.fx.evaluate('Collect(samples,{N:6})', ctx)
    assert runtime.fx.evaluate('Spread') == pytest.approx((8/3)**.5)
    assert runtime.collections['samples'] == [{'N':2},{'N':4},{'N':6}]


CASES = json.loads((Path(__file__).parents[1] / 'powerapps_sim/conformance_cases/statistics.json').read_text())['cases']


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
def test_pinned_reference_population_statistics(runtime, case):
    result = run_case(runtime, case)
    assert result['status'] == 'passed', result
