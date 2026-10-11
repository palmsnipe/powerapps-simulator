"""Search and grouped table values, column binding and nested scopes."""
import json
import pytest
from powerapps_sim.fx import Context
from powerapps_sim.binding import BindScope
from powerapps_sim.syntax import FxError
from powerapps_sim.runtime import serial

ROWS='Table({ID:1,Team:"A",Title:"North",Amount:10},{ID:2,Team:"B",Title:"South",Amount:20},{ID:3,Team:"A",Title:"NORTH east",Amount:30})'

@pytest.mark.parametrize('query,ids', [('"north"',[1,3]),('"oRtH"',[1,3]),('"B"',[2]),('""',[1,2,3]),('Blank()',[1,2,3]),('"absent"',[])])
def test_search_case_insensitive_any_column_blank_query(runtime,query,ids):
    result=runtime.fx.evaluate(f'Search({ROWS},{query},Title,Team)')
    assert [r['ID'] for r in result]==ids
    assert runtime.fx.evaluate(f'CountRows({ROWS})')==3

@pytest.mark.parametrize('fn', ['Search('+ROWS+',"",Amount)', 'Search(FirstN('+ROWS+',0),"x",Amount)', 'Search('+ROWS+',"x",Missing)', 'GroupBy('+ROWS+',Team,Team,Rows)', 'GroupBy('+ROWS+',Team,Title)', 'Ungroup('+ROWS+',Amount)', 'Ungroup(Table({Title:"parent",Rows:Table({Title:"child"})}),Rows)'])
def test_column_contracts_include_empty_tables_and_source_locations(runtime,fn):
    node=runtime.fx.parse(fn);runtime.binder.errors.clear();runtime.binder.bind(node,BindScope())
    assert runtime.binder.errors
    with pytest.raises(FxError) as err:runtime.fx.evaluate(fn)
    assert err.value.kind in ('Type','Name','Validation')


def test_group_aggregate_filter_scopes_and_ungroup_interleaved_order(runtime):
    groups=runtime.fx.evaluate(f'GroupBy({ROWS},Team,Members)')
    assert groups==[{'Team':'A','Members':[{'ID':1,'Title':'North','Amount':10},{'ID':3,'Title':'NORTH east','Amount':30}]},{'Team':'B','Members':[{'ID':2,'Title':'South','Amount':20}]}]
    assert runtime.fx.evaluate(f'DropColumns(AddColumns(GroupBy({ROWS},Team,Members) As g,Total,Sum(g.Members As m,m.Amount)),Members)')==[{'Team':'A','Total':40},{'Team':'B','Total':20}]
    restored=runtime.fx.evaluate(f'Ungroup(SortByColumns(AddColumns(GroupBy({ROWS},Team,Members),Total,Sum(Members,Amount)),Team,SortOrder.Descending),Members)')
    assert [r['ID'] for r in restored]==[1,2,3]
    assert [r['Total'] for r in restored]==[40,20,40]
    filtered=runtime.fx.evaluate(f'Ungroup(Filter(GroupBy({ROWS},Team,Members),Team="A"),Members)')
    assert [r['ID'] for r in filtered]==[1,3]
    assert all(not any(k.startswith('__') for k in r) for r in restored)
    assert json.loads(json.dumps(serial(restored)))==restored


def test_typed_empty_blank_and_manual_nested_tables(runtime):
    assert runtime.fx.evaluate(f'GroupBy(FirstN({ROWS},0),Team,Members)')==[]
    assert runtime.fx.evaluate(f'Search(If(false,{ROWS}),"north",Title)') is None
    assert runtime.fx.evaluate(f'Ungroup(If(false,GroupBy({ROWS},Team,Members)),Members)') is None
    assert runtime.fx.evaluate('Ungroup(Table({Team:"A",Rows:Table({ID:2},{ID:1})},{Team:"B",Rows:Blank()}),Rows)')==[{'Team':'A','ID':2},{'Team':'A','ID':1}]
    assert runtime.fx.evaluate('GroupBy(Table({Key:Blank(),N:1},{Key:0,N:2},{Key:Blank(),N:3}),Key,Rows)')==[{'Key':None,'Rows':[{'N':1},{'N':3}]},{'Key':0,'Rows':[{'N':2}]}]


def test_shaping_and_typed_function_preserve_group_order_without_fields(runtime):
    assert [r['ID'] for r in runtime.fx.evaluate(f'Ungroup(AddColumns(GroupBy({ROWS},Team,Members),Flag,true),Members)')]==[1,2,3]
    assert [r['ID'] for r in runtime.fx.evaluate(f'Ungroup(AddColumns(GroupBy({ROWS},Team,Members),Adjusted,ShowColumns(Members,ID)),Adjusted)')]==[1,2,3]
    runtime.fx.evaluate(f'ClearCollect(groups, GroupBy({ROWS},Team,Members))',Context(runtime,behavior=True))
    assert [r['ID'] for r in runtime.fx.evaluate('Ungroup(groups,Members)')]==[1,2,3]


def test_search_errors_propagate_and_lazy_branch_does_not_observe(runtime):
    assert runtime.fx.evaluate('IfError(CountRows(Search(Table({Title:Text(1/0)}),"x",Title)),FirstError.Kind)')==13
    assert runtime.fx.evaluate('CountRows(Search(Table({Title:Text(1/0)}),"",Title))')==1
    assert runtime.fx.evaluate('If(false,Search(Table({Title:1/0}),"x",Title),Table({Title:"ok"}))')==[{'Title':'ok'}]
    assert runtime.fx.evaluate('IfError(CountRows(GroupBy(Table({Key:1/0}),Key,Rows)),FirstError.Kind)')==13
    runtime.fx.evaluate('Set(rows,Table({Title:"one"}))',Context(runtime,behavior=True))
    runtime.globals['rows']=[{'Title':'one'},None,FxError('read failed','Network')]
    assert runtime.fx.evaluate('IfError(CountRows(Search(rows,"one",Title)),FirstError.Kind)')==23


def test_search_uses_language_lowering_without_accent_or_case_expansion(runtime):
    assert runtime.fx.evaluate('CountRows(Search(["été","ete","Straße"],"ete",Value))')==1
    assert runtime.fx.evaluate('CountRows(Search(["Straße"],"SS",Value))')==0
    runtime.environment['language']='tr-TR'
    assert runtime.fx.evaluate('Search(["Istanbul","İzmir"],"ı",Value)')==[{'Value':'Istanbul'}]


def test_typed_group_ungroup_functions_preserve_value_lineage(runtime):
    runtime.fx.set_definitions('Rows := Type([{Team:Text,ID:Number}]); Members := Type([{ID:Number}]); Groups := Type([{Team:Text,Members:Members}]); Group(rows:Rows):Groups = GroupBy(rows,Team,Members); Flatten(groups:Groups):Rows = Ungroup(groups,Members);')
    result=runtime.fx.evaluate('Flatten(Group(Table({Team:"A",ID:1},{Team:"B",ID:2},{Team:"A",ID:3})))')
    assert [r['ID'] for r in result]==[1,2,3]
    assert set(result[0])=={'Team','ID'}
