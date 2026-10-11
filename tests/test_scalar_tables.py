"""Single-column overload contracts, errors, host profiles and reactive components."""
from decimal import Decimal

import pytest

from powerapps_sim.binding import BindScope
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError


@pytest.mark.parametrize('expression, expected', [
    ('Len(Table({Title:"Hello"},{Title:Blank()},{Title:"🌲"}))', [5,0,2]),
    ('Lower(ShowColumns([{Title:"ÉTÉ",Extra:1}], Title))', ['été']),
    ('Upper(["été",Blank(),true])', ['ÉTÉ','','TRUE']),
    ('Trim(["  a\tb  "," a\nb "])', ['a b','a\nb']),
    ('TrimEnds(["\ta  b\n",Blank()])', ['a  b','']),
    ('Abs([-3,Blank(),"4.5"])', [3,0,4.5]),
    ('Round([123.456,987.593,542.639], 2)', [123.46,987.59,542.64]),
    ('RoundDown([123.456,987.593,542.639], [0,1,2])', [123,987.5,542.63]),
    ('RoundUp([123.456,987.593,542.639], [2])', [123.46,988,543]),
    ('Round(12.35, [0,1,2])', [12,12.4,12.35]),
    ('Len(Len(Table({Title:"abcdefghijklmn"},{Title:"hi"})))', [2,1]),
])
def test_scalar_table_values_columns_coercions_and_canvas_digits(runtime, expression, expected):
    assert runtime.fx.evaluate(expression) == [{'Value':value} for value in expected]


@pytest.mark.parametrize('name', ['Len','Lower','Upper','Trim','TrimEnds','Abs','Round','RoundDown','RoundUp'])
def test_scalar_table_schema_validation_before_empty_or_error_rows(runtime, name):
    suffix = ', 1' if name.startswith('Round') else ''
    for source in ['[]','Table()','Table({a:1,b:2})','FirstN(Table({a:1,b:2}),0)','If(false,Table({a:1,b:2}))']:
        expression = f'{name}({source}{suffix})'
        node = runtime.fx.parse(expression)
        runtime.binder.errors.clear()
        runtime.binder.bind(node, BindScope())
        assert any(error.kind == 'Type' for _,error in runtime.binder.errors)
        with pytest.raises(FxError, match='single-column') as error:
            runtime.fx.evaluate(expression)
        assert error.value.kind == 'Type' and error.value.end > error.value.start
    assert runtime.fx.evaluate(f'{name}(FirstN([1],0){suffix})') == []
    assert runtime.fx.evaluate(f'{name}(If(false,[1]){suffix})') is None
    with pytest.raises(FxError) as error:
        runtime.fx.evaluate(f'{name}(If(1/0=0,[1]){suffix})')
    assert error.value.kind == 'Div0'


def test_table_errors_remain_cells_and_rows_and_empty_tables_do_not_consume_scalars(runtime):
    values = runtime.fx.evaluate('Round([1.2,2.3,3.4], 1/0)')
    assert len(values) == 3 and all(row['Value'].kind == 'Div0' for row in values)
    assert runtime.fx.evaluate('IsError(Round([1.2,2.3], 1/0))') is False
    assert runtime.fx.evaluate('IfError(First(Round([1.2,2.3], 1/0)).Value, FirstError.Kind)') == 13
    assert runtime.fx.evaluate('Round(FirstN([1],0), 1/0)') == []
    assert runtime.fx.evaluate('Round(If(false,[1]), 1/0)') is None
    assert runtime.fx.evaluate('ForAll(Len(["ok",1/0,"four"]), IfError(Value, -FirstError.Kind))') == [{'Value':2},{'Value':-13},{'Value':4}]
    ctx = Context(runtime,behavior=True)
    runtime.fx.evaluate('Set(unknownRows, Table({Title:"ABC"},{Title:"DEF"}))',ctx)
    runtime.globals['unknownRows'] = [{'Title':'ABC'},None,FxError('row failure','Network'),{'Title':'DEF'}]
    result = runtime.fx.evaluate('Lower(unknownRows)')
    assert result[0] == {'Value':'abc'} and result[1] is None
    assert result[2].kind == 'Network' and result[3] == {'Value':'def'}
    assert runtime.globals['unknownRows'][0]['Title'] == 'ABC'
    error_cells = runtime.fx.evaluate('Round(["bad",1/0,3.56],1)')
    assert error_cells[0]['Value'].kind == 'InvalidArgument'
    assert error_cells[0]['Value'].end > error_cells[0]['Value'].start
    assert error_cells[1]['Value'].kind == 'Div0' and error_cells[2] == {'Value':3.6}


def test_host_alignment_modes_and_missing_numbers_are_explicit(runtime):
    assert runtime.fx.evaluate('Round([1.23,2.78], [1])') == [{'Value':1.2},{'Value':3}]
    runtime.environment['round_table_mode'] = 'powerfx-errors'
    result = runtime.fx.evaluate('Round([1.23,2.78], [1])')
    assert result[0] == {'Value':1.2} and result[1]['Value'].kind == 'NotApplicable'
    runtime.environment['round_table_mode'] = 'canvas-zero'
    result = runtime.fx.evaluate('Round([1.23], [1,2])')
    assert result[0] == {'Value':1.2} and result[1]['Value'].kind == 'NotApplicable'
    assert runtime.fx.evaluate('Round([1.23,2.78], FirstN([1],0))') == [{'Value':1},{'Value':3}]


def test_scalar_table_types_decimal_and_localized_text(runtime):
    runtime.environment['number_mode'] = 'decimal'
    runtime.environment['language'] = 'fr-CA'
    runtime.binder.nodes.clear();runtime.binder.node_refs.clear()
    for expression,kind in [('Len(["été"])','Decimal'),('Round([1.25],1)','Decimal'),('Lower([1.25])','Text')]:
        typ = runtime.binder.bind(runtime.fx.parse(expression),BindScope())
        assert typ.kind == 'Table' and set(typ.row.fields) == {'Value'}
        assert typ.row.fields['Value'].kind == kind and not typ.row.open
    assert runtime.fx.evaluate('Lower([1.25])') == [{'Value':'1,25'}]
    assert runtime.fx.evaluate('Len(["🌲",Blank()])') == [{'Value':Decimal(2)},{'Value':Decimal(0)}]
    result = runtime.fx.evaluate('Round([9007199254740993.25,9007199254740993.35],1)')
    assert result == [{'Value':Decimal('9007199254740993.3')},{'Value':Decimal('9007199254740993.4')}]
    runtime.fx.set_definitions('Names := Type([{Value:Text}]); Lengths := Type([{Value:Number}]); Measure(values:Names):Lengths = Len(values);')
    assert runtime.fx.evaluate('Measure(["été","🌲"])') == [{'Value':Decimal(3)},{'Value':Decimal(2)}]
    assert runtime.fx.evaluate('Measure(If(false,["x"]))') is None
    assert runtime.fx.evaluate('Measure([])') == []


def test_alignment_settings_are_validated_and_persist_without_source_changes(post,runtime):
    source = dict(runtime.project.documents)
    before = dict(runtime.environment)
    assert post('/api/scenario',{'environment':{**before,'round_table_mode':'truncate'}}).status_code == 400
    assert runtime.environment == before
    assert post('/api/scenario',{'environment':{**before,'round_table_mode':'powerfx-errors'}}).status_code == 200
    assert runtime.project.read_json('emulator.json',{})['environment']['round_table_mode'] == 'powerfx-errors'
    assert runtime.project.documents == source


def test_component_outputs_use_overload_schemas_recalculate_and_keep_instances_isolated(tmp_path):
    from powerapps_sim.fixtures import tables_project
    from powerapps_sim.runtime import Runtime
    runtime = Runtime(tables_project(tmp_path/'overload-components'))
    try:
        runtime.restart();runtime.state()
        assert runtime.fx.evaluate('First(LeftQueue.Names).Value') == 'fictional wetland study'
        assert runtime.fx.evaluate('First(RightQueue.Names).Value') == 'fictional river survey'
        assert runtime.fx.evaluate('First(LeftQueue.TitleLengths).Value') == 23
        assert runtime.fx.evaluate('LeftQueue.Measure(If(false,["a"]))') is None
        assert runtime.fx.evaluate('LeftQueue.Measure([])') == []
        assert runtime.fx.evaluate('LeftQueue.RoundedAmounts') == [{'Value':33.3},{'Value':67},{'Value':100},{'Value':133}]
        assert runtime.fx.evaluate('RightQueue.RoundedAmounts') == [{'Value':33.33},{'Value':66.67},{'Value':100},{'Value':133.33}]
        source = dict(runtime.project.documents)
        runtime.event('Queues/SearchInput','OnChange','river');runtime.state()
        assert runtime.fx.evaluate('LeftQueue.TitleLengths') == [{'Value':22}]
        assert len(runtime.fx.evaluate('RightQueue.TitleLengths')) == 4
        runtime.environment['round_table_mode'] = 'powerfx-errors';runtime.invalidate();runtime.state()
        assert runtime.fx.evaluate('LeftQueue.RoundedAmounts')[1]['Value'].kind == 'NotApplicable'
        assert runtime.fx.evaluate('RightQueue.RoundedAmounts')[1]['Value'] == 66.67
        assert runtime.project.documents == source and not runtime.diagnostics
    finally:
        runtime.close()
